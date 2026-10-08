"""MI CPU guard: offline G1-G7 tests with injected counters / killers / clocks and temp-dir ledgers.

No systemd unit is started and no real cgroup is touched here (see test_mi_cpuguard_integration.py, opt-in).
"""
from __future__ import annotations

import multiprocessing as mp
import os
import random
import tempfile
import unittest

import _helpers  # noqa: F401  (package root on sys.path)

from mi_cpuguard import CAP_CPU_S, MARGIN_CPU_S, QUOTA_CORES, SLICE
from mi_cpuguard import ledger as L
from mi_cpuguard import units as U
from mi_cpuguard.guard import Guard, GuardFault, read_usage_usec

US = 1_000_000


class Counter:
    """Fake slice counter: advances by a per-poll CPU amount; can be made to fail or go backwards."""

    def __init__(self, start=5 * US, per_poll_cpu_s=1.0, fail_at=None, back_at=None, after_kill_cpu_s=None):
        self.u, self.d, self.n = start, int(per_poll_cpu_s * US), 0
        self.fail_at, self.back_at, self.killed = fail_at, back_at, False
        self.after_kill = int((per_poll_cpu_s if after_kill_cpu_s is None else after_kill_cpu_s) * US)
        self.final_unreadable = False

    def read(self):
        if self.killed:
            if self.final_unreadable:
                raise GuardFault("cgroup gone")
            return self.u + self.after_kill
        self.n += 1
        if self.fail_at is not None and self.n >= self.fail_at:
            raise GuardFault("cpu.stat unreadable")
        if self.back_at is not None and self.n == self.back_at:
            return self.u - 1
        if self.n > 1:
            self.u += self.d
        return self.u

    def kill(self):
        self.killed = True


class Clock:
    def __init__(self, step=1.0):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def mk(tmp, counter, reservation=100.0, clock=None, **kw):
    led = L.BudgetLedger(os.path.join(tmp, "budget.jsonl"))
    g = Guard(reader=counter.read, killer=counter.kill, ledger=led, campaign=kw.pop("campaign", "c1"),
              reservation_cpu_s=reservation, clock=clock or Clock(1.0), sleep=lambda s: None, **kw)
    return g, led


class G1BudgetKill(unittest.TestCase):
    def test_kill_before_reservation_at_max_rate(self):
        with tempfile.TemporaryDirectory() as td:
            c = Counter(per_poll_cpu_s=QUOTA_CORES * 1.0)          # 600 % for 1 s per poll = worst case
            g, led = mk(td, c, reservation=100.0)
            self.assertTrue(g.start())
            out = g.run(max_polls=1000)
            self.assertEqual(out["verdict"], "KILL")
            self.assertIn("budget", out["reason"])
            self.assertTrue(c.killed)
            self.assertLessEqual(out["charged_cpu_s"], 100.0)
            self.assertEqual(out["basis"], "cgroup_usage_usec")
            self.assertEqual(led.state()["charged_cpu_s"], out["charged_cpu_s"])

    def test_randomized_rates_never_exceed_reservation(self):
        rnd = random.Random(20261008)
        for i in range(300):
            with tempfile.TemporaryDirectory() as td:
                rate = rnd.uniform(0.01, QUOTA_CORES)
                c = Counter(per_poll_cpu_s=rate, after_kill_cpu_s=rnd.uniform(0, QUOTA_CORES))
                res = rnd.uniform(MARGIN_CPU_S + 1, 500)
                g, _ = mk(td, c, reservation=res)
                g.start()
                out = g.run(max_polls=100000)
                self.assertLessEqual(out["charged_cpu_s"], res + 1e-9, (i, rate, res))

    def test_margin_is_two_polls_at_quota(self):
        self.assertEqual(MARGIN_CPU_S, 12.0)
        with self.assertRaises(ValueError):
            Guard(reader=lambda: 0, killer=lambda: None, ledger=None, campaign="x", reservation_cpu_s=12.0)


class G2FailClosed(unittest.TestCase):
    def test_unreadable_counter_kills_and_charges_full_reservation(self):
        with tempfile.TemporaryDirectory() as td:
            c = Counter(fail_at=4)
            c.final_unreadable = True
            g, led = mk(td, c, reservation=50.0)
            g.start()
            out = g.run(max_polls=100)
            self.assertEqual(out["verdict"], "KILL")
            self.assertIn("read_fault", out["reason"])
            self.assertTrue(c.killed)
            self.assertEqual((out["charged_cpu_s"], out["basis"]), (50.0, "full_reservation_unreadable"))
            self.assertTrue(out["stop_campaign"])

    def test_non_monotonic_counter_kills(self):
        with tempfile.TemporaryDirectory() as td:
            c = Counter(back_at=3)
            g, _ = mk(td, c)
            g.start()
            self.assertIn("non_monotonic", g.run(max_polls=100)["reason"])

    def test_guard_gap_kills(self):
        with tempfile.TemporaryDirectory() as td:
            c = Counter()
            g, _ = mk(td, c, clock=Clock(5.0))                       # every poll 5 s apart > 3 s max gap
            g.start()
            out = g.run(max_polls=100)
            self.assertIn("guard_gap", out["reason"])
            self.assertTrue(c.killed)

    def test_baseline_unreadable_refuses_and_charges_reservation(self):
        with tempfile.TemporaryDirectory() as td:
            c = Counter(fail_at=1)
            c.final_unreadable = True
            g, led = mk(td, c, reservation=20.0)
            self.assertFalse(g.start())
            self.assertEqual(led.state()["charged_cpu_s"], 20.0)

    def test_kill_error_still_charges(self):
        with tempfile.TemporaryDirectory() as td:
            c = Counter(per_poll_cpu_s=6.0)

            def bad_kill():
                c.killed = True
                raise OSError("systemctl failed")
            led = L.BudgetLedger(os.path.join(td, "b.jsonl"))
            g = Guard(reader=c.read, killer=bad_kill, ledger=led, campaign="k", reservation_cpu_s=40.0,
                      clock=Clock(), sleep=lambda s: None)
            g.start()
            out = g.run(max_polls=100)
            self.assertIn("kill_error", out["reason"])
            self.assertEqual(led.state()["open_reservations"], {})

    def test_cpu_stat_parser_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "cpu.stat")
            for body in ("", "user_usec 5\n", "usage_usec abc\n", "usage_usec -3\n"):
                with open(p, "w") as fh:
                    fh.write(body)
                with self.assertRaises(GuardFault):
                    read_usage_usec(td)
            with self.assertRaises(GuardFault):
                read_usage_usec(os.path.join(td, "missing"))
            with open(p, "w") as fh:
                fh.write("usage_usec 12345\nuser_usec 1\n")
            self.assertEqual(read_usage_usec(td), 12345)


class G3GuardLiveness(unittest.TestCase):
    def test_jobs_and_anchor_are_bound_to_the_guard(self):
        p = U.job_props("c1", 3600)
        for need in (f"--slice={SLICE}", "BindsTo=mi-cpuguard-c1.service", "Requisite=mi-cpuguard-c1.service",
                     "After=mi-cpuguard-c1.service", "MemorySwapMax=0", "RuntimeMaxSec=3600"):
            self.assertIn(need, p)
        a = U.anchor_cmd("c1", 3600)
        self.assertIn("BindsTo=mi-cpuguard-c1.service", a)
        self.assertIn(f"--slice={SLICE}", a)

    def test_guard_runs_outside_the_slice_and_never_restarts(self):
        g = U.guard_cmd("c1", "/usr/bin/python3", [], 7200)
        self.assertIn("--slice=app.slice", g)
        self.assertNotIn(f"--slice={SLICE}", g)
        self.assertIn("Restart=no", g)
        self.assertIn("CollectMode=inactive-or-failed", g)             # I3: a dead guard cannot be re-started

    def test_slice_rate_cap_is_600_percent(self):
        s = U.slice_cmd()
        for need in ("CPUQuota=600%", "CPUWeight=idle", "MemorySwapMax=0", "--runtime", SLICE):
            self.assertIn(need, s)
        self.assertEqual(SLICE, "research-mi.slice")                  # child of research.slice (800 %)


class G4Charging(unittest.TestCase):
    def test_done_charges_measured(self):
        with tempfile.TemporaryDirectory() as td:
            c = Counter(per_poll_cpu_s=2.0, after_kill_cpu_s=0)
            polls = {"n": 0}

            def done():
                polls["n"] += 1
                return polls["n"] >= 5
            g, led = mk(td, c, reservation=100.0, done=done)
            g.start()
            out = g.run(max_polls=100)
            self.assertEqual(out["verdict"], "DONE")
            self.assertFalse(c.killed)
            self.assertEqual(out["basis"], "cgroup_usage_usec")
            self.assertAlmostEqual(out["charged_cpu_s"], 12.0)          # 5 polls + the final read, 2 CPU-s each
            self.assertFalse(out["stop_campaign"])
            self.assertAlmostEqual(led.state()["remaining_cpu_s"], CAP_CPU_S - 12.0)

    def test_over_reservation_is_surfaced(self):
        with tempfile.TemporaryDirectory() as td:
            c = Counter(per_poll_cpu_s=6.0, after_kill_cpu_s=60.0)    # pathological kill latency
            g, _ = mk(td, c, reservation=30.0)
            g.start()
            out = g.run(max_polls=100)
            self.assertEqual(out["basis"], "cgroup_usage_usec_OVER_RESERVATION")
            self.assertTrue(out["stop_campaign"])


def _reserve_worker(path, q):
    try:
        L.BudgetLedger(path).reserve(f"w{os.getpid()}", 5000.0)
        q.put("ok")
    except L.BudgetExceeded:
        q.put("refused")


class G5Ledger(unittest.TestCase):
    def test_cap_and_open_reservations_count_as_consumed(self):
        with tempfile.TemporaryDirectory() as td:
            led = L.BudgetLedger(os.path.join(td, "b.jsonl"))
            self.assertEqual(led.cap, 28_800.0)
            led.reserve("a", 20_000)
            with self.assertRaises(L.BudgetExceeded):
                led.reserve("b", 9_000)                                # 20 000 open + 9 000 > cap
            led.charge("a", 1_000, "cgroup_usage_usec")
            led.reserve("b", 9_000)
            self.assertEqual(led.state()["committed_cpu_s"], 10_000)

    def test_crash_recovery_charges_full_reservation(self):
        with tempfile.TemporaryDirectory() as td:
            led = L.BudgetLedger(os.path.join(td, "b.jsonl"))
            led.reserve("crashed", 3_000)
            led.recover("crashed")
            st = led.state()
            self.assertEqual((st["charged_cpu_s"], st["open_reservations"]), (3_000, {}))

    def test_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "b.jsonl")
            led = L.BudgetLedger(p)
            led.reserve("a", 100)
            led.charge("a", 50, "cgroup_usage_usec")
            with open(p) as fh:
                lines = fh.read().splitlines()
            with open(p, "w") as fh:
                fh.write(lines[0] + "\n" + lines[1].replace('"actual_cpu_s":50.0', '"actual_cpu_s":5.0') + "\n")
            with self.assertRaises(L.LedgerTamper):
                led.state()
            with self.assertRaises(L.LedgerTamper):
                led.reserve("b", 1)
            with open(p, "w") as fh:
                fh.write(lines[1] + "\n")                             # truncated head
            with self.assertRaises(L.LedgerTamper):
                led.state()

    def test_double_charge_and_unknown_campaign_refused(self):
        with tempfile.TemporaryDirectory() as td:
            led = L.BudgetLedger(os.path.join(td, "b.jsonl"))
            led.reserve("a", 10)
            led.charge("a", 5, "x")
            with self.assertRaises(L.LedgerTamper):
                led.charge("a", 5, "x")
            with self.assertRaises(L.LedgerTamper):
                led.charge("zzz", 1, "x")

    def test_concurrent_reservations_are_serialized(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "b.jsonl")
            q = mp.get_context("fork").Queue()
            ps = [mp.get_context("fork").Process(target=_reserve_worker, args=(p, q)) for _ in range(8)]
            for x in ps:
                x.start()
            for x in ps:
                x.join(30)
            res = sorted(q.get(timeout=5) for _ in ps)
            self.assertEqual(res.count("ok"), 5)                       # 5 x 5 000 <= 28 800 < 6 x 5 000
            st = L.BudgetLedger(p).state()
            self.assertEqual((st["events"], st["committed_cpu_s"]), (5, 25_000))


class G6WallClock(unittest.TestCase):
    def test_wall_clock_is_only_an_additional_kill(self):
        with tempfile.TemporaryDirectory() as td:
            c = Counter(per_poll_cpu_s=0.01)
            g, _ = mk(td, c, reservation=100.0)
            g.start()
            out = g.run(max_polls=10)
            self.assertEqual(out["verdict"], "KILL")
            self.assertIn("wall-clock safeguard", out["reason"])
            self.assertEqual(out["basis"], "cgroup_usage_usec")         # still charged by measured CPU

    def test_runtime_max_rendered_everywhere(self):
        self.assertIn("RuntimeMaxSec=7200", U.guard_cmd("c", "py", [], 7200))
        self.assertIn("RuntimeMaxSec=3600", U.anchor_cmd("c", 3600))
        self.assertIn("RuntimeMaxSec=3600", U.job_props("c", 3600))


if __name__ == "__main__":
    unittest.main()
