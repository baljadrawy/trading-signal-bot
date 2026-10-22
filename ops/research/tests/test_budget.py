"""Unit tests for research_exec.budget (admission controller I-1). Fakes only; no systemd, no real jobs.

Each test maps to a row of RESEARCH_ADMISSION_CONTROLLER_DESIGN.md (sections 2, 2a, 4) or of the implementation plan.
"""
from __future__ import annotations

import datetime as dt
import json
import multiprocessing as mp
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research_exec import budget as B  # noqa: E402

T0 = dt.datetime(2026, 10, 22, 12, 0, tzinfo=dt.timezone.utc)


class World:
    """A fake host: units, pids (with start ticks), boot id, clocks, lab slice and marker processes."""

    def __init__(self):
        self.units, self.pids, self.boot = {}, {100: 5000, 200: 6000, 300: 7000}, "boot-a"
        self.wall, self.mono, self.lab, self.markers = T0, 1000.0, 0, []
        self.quota, self.live = None, []

    def probes(self):
        return B.Probes(is_unit_active=lambda u: self.units.get(u, False), pid_start_ticks=lambda p: self.pids.get(p),
                        boot_id=lambda: self.boot, wall_utc=lambda: self.wall, mono_s=lambda: self.mono,
                        lab_slice_pct=lambda: self.lab, marker_procs_outside_slice=lambda: self.markers,
                        slice_quota_pct=lambda: self.quota, live_job_units=lambda: self.live)

    def advance(self, s):
        self.wall += dt.timedelta(seconds=s); self.mono += s


def req(job, profile="R1", pct=400, pid=100, unit=None, runtime=3600):
    return B.Request(job_id=job, unit=unit or f"rj-{job}.service", profile=profile, pct=pct, pid=pid,
                     max_runtime_s=runtime)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = self.tmp.name; self.w = World()

    def tearDown(self):
        self.tmp.cleanup()

    def reserve(self, r, **cfg):
        return B.reserve(self.d, r, self.w.probes(), cfg)

    def state(self):
        return B.load(os.path.join(self.d, "budget.json"))


class Budget(Base):
    def test_r1_job_admitted_and_lease_recorded(self):
        d = self.reserve(req("a"))
        self.assertTrue(d.admit, d.reasons); self.assertEqual((d.capacity_pct, d.held_pct), (400, 0))
        ls = self.state()["leases"][0]
        self.assertEqual((ls["job_id"], ls["pct"], ls["pid_start_ticks"], ls["boot_id"]), ("a", 400, 5000, "boot-a"))

    def test_light_refused_while_r1_holds_the_budget(self):                     # design 4.1 (R1 mode)
        self.w.units["rj-a.service"] = True
        self.assertTrue(self.reserve(req("a")).admit)
        d = self.reserve(req("l", profile="LIGHT", pct=200, pid=200))
        self.assertFalse(d.admit); self.assertIn("budget_exceeded held=400 requested=200 capacity=400", d.reasons)

    def test_light_refused_while_r2_holds_500(self):                            # design 4.1 (R2 mode)
        self.w.units["rj-a.service"] = True
        self.assertTrue(self.reserve(req("a", profile="R2", pct=500)).admit)
        d = self.reserve(req("l", profile="LIGHT", pct=200, pid=200))
        self.assertFalse(d.admit); self.assertEqual(d.capacity_pct, 500)

    def test_light_fits_beside_a_200_job(self):
        self.w.units["rj-a.service"] = True
        self.assertTrue(self.reserve(req("a", profile="LIGHT", pct=200)).admit)
        self.assertTrue(self.reserve(req("b", profile="LIGHT", pct=200, pid=200)).admit)

    def test_r2_mode_returns_to_r1_after_release(self):                         # design 4.5
        self.w.units["rj-a.service"] = True
        self.assertTrue(self.reserve(req("a", profile="R2", pct=500)).admit)
        self.assertTrue(B.release(self.d, "a"))
        b, _ = B.capacity(self.state(), self.w.probes(), B.DEFAULTS)
        self.assertEqual(b, 400)

    def test_lab_slice_reduces_budget_by_100(self):                              # design 4.6 / A4
        self.w.lab = 100
        d = self.reserve(req("a"))
        self.assertFalse(d.admit); self.assertEqual(d.capacity_pct, 300)
        self.assertTrue(self.reserve(req("b", pct=300)).admit)

    def test_unreadable_lab_probe_refuses(self):
        self.w.lab = None
        self.assertIn("lab_probe_unreadable", self.reserve(req("a")).reasons)

    def test_release_is_idempotent(self):
        self.reserve(req("a"))
        self.assertTrue(B.release(self.d, "a")); self.assertFalse(B.release(self.d, "a"))


class Hardening(Base):
    def test_duplicate_job_id_refused(self):
        self.w.units["rj-a.service"] = True
        self.assertTrue(self.reserve(req("a", pct=100)).admit)
        self.assertIn("duplicate_job_id job=a", self.reserve(req("a", pct=100)).reasons)

    def test_corrupt_state_refuses_and_is_left_untouched(self):
        p = os.path.join(self.d, "budget.json")
        with open(p, "w") as fh:
            fh.write("{not json")
        d = self.reserve(req("a"))
        self.assertFalse(d.admit); self.assertTrue(d.reasons[0].startswith("budget_state_unreadable"))
        self.assertEqual(open(p).read(), "{not json")

    def test_malformed_lease_and_unknown_schema_refuse(self):
        p = os.path.join(self.d, "budget.json")
        for doc in ({"schema": 2, "leases": []}, {"schema": 1, "leases": [{"job_id": "x"}]}):
            with open(p, "w") as fh:
                json.dump(doc, fh)
            self.assertFalse(self.reserve(req("a")).admit)

    def test_crash_orphan_kept_within_grace_then_reclaimed(self):              # SIGKILL after admission
        self.reserve(req("a"))                                   # unit never became active (runner killed)
        del self.w.pids[100]                                      # owner process gone
        self.w.advance(60)
        d = self.reserve(req("b", pid=200))
        self.assertFalse(d.admit); self.assertIn("budget_exceeded held=400 requested=400 capacity=400", d.reasons)
        self.w.advance(61)                                        # past the 120 s grace
        d = self.reserve(req("b", pid=200))
        self.assertTrue(d.admit, d.reasons); self.assertEqual(d.reclaimed, ["a"])

    def test_pid_reuse_counts_as_dead(self):
        self.reserve(req("a"))
        self.w.pids[100] = 9999                                   # same pid, different start ticks
        self.w.advance(130)
        self.assertEqual(self.reserve(req("b", pid=200)).reclaimed, ["a"])

    def test_unit_gone_but_process_alive_refuses_without_reclaim(self):
        self.reserve(req("a"))
        self.w.advance(300)
        d = self.reserve(req("b", pct=100, pid=200))
        self.assertIn("unit_gone_process_alive job=a", d.reasons); self.assertEqual(d.reclaimed, [])
        self.assertEqual([ls["job_id"] for ls in self.state()["leases"]], ["a"])

    def test_expired_lease_with_active_unit_refuses_and_is_kept(self):
        self.w.units["rj-a.service"] = True
        self.reserve(req("a", pct=100, runtime=60))
        self.w.advance(60 + 600 + 1)
        d = self.reserve(req("b", pct=100, pid=200))
        self.assertIn("lease_expired_unit_active job=a", d.reasons)
        self.assertEqual(len(self.state()["leases"]), 1)

    def test_unknown_unit_state_refuses(self):
        self.reserve(req("a", pct=100))
        self.w.units["rj-a.service"] = None
        self.assertIn("unit_state_unknown job=a", self.reserve(req("b", pct=100, pid=200)).reasons)

    def test_previous_boot_lease_reclaimed_only_if_unit_inactive(self):
        self.reserve(req("a"))
        self.w.boot = "boot-b"; self.w.pids = {200: 1}
        self.assertEqual(self.reserve(req("b", pid=200)).reclaimed, ["a"])

    def test_marker_process_outside_slice_refuses(self):                       # also covers lab without cgroup_parent
        self.w.markers = [{"pid": 4242, "cgroup": "/system.slice/docker-abc.scope"}]
        self.assertIn("marker_process_outside_slice n=1", self.reserve(req("a")).reasons)
        self.w.markers = None
        self.assertIn("marker_probe_unreadable", self.reserve(req("a")).reasons)

    def test_clock_step_refuses_once_then_reanchors(self):
        self.w.units["rj-a.service"] = True
        self.reserve(req("a", pct=100))
        self.w.wall += dt.timedelta(seconds=120)                  # wall jumps, monotonic does not
        d = self.reserve(req("b", pct=100, pid=200))
        self.assertFalse(d.admit); self.assertTrue(any(r.startswith("clock_step_detected") for r in d.reasons))
        self.assertTrue(self.reserve(req("b", pct=100, pid=200)).admit)

    def test_job_pid_must_exist(self):
        self.assertIn("job_pid_not_found pid=12345", self.reserve(req("a", pid=12345)).reasons)

    def test_bind_moves_lease_to_job_process(self):
        self.reserve(req("a"))
        self.assertTrue(B.bind(self.d, "a", 300, self.w.probes()))
        ls = self.state()["leases"][0]
        self.assertEqual((ls["pid"], ls["pid_start_ticks"]), (300, 7000))
        self.assertFalse(B.bind(self.d, "nope", 300, self.w.probes()))

    def test_readback_accounting_drift_and_slice_quota(self):                  # design 4.3
        self.w.units["rj-a.service"] = True
        self.reserve(req("a", pct=100))
        st = self.state()
        self.w.live = ["rj-a.service"]
        self.assertEqual(B.readback(st, self.w.probes(), {}), [])
        self.w.live = ["rj-a.service", "rj-x.service"]
        self.assertIn("accounting_drift units_vs_leases", B.readback(st, self.w.probes(), {}))
        self.w.live, self.w.quota = ["rj-a.service"], 800
        self.assertIn("slice_quota_mismatch quota=800 capacity=400", B.readback(st, self.w.probes(), {"enforce_slice": True}))
        self.w.quota = 400
        self.assertEqual(B.readback(st, self.w.probes(), {"enforce_slice": True}), [])

    def test_atomic_save_leaves_valid_state_on_crash_before_rename(self):
        self.reserve(req("a", pct=100))
        p = os.path.join(self.d, "budget.json"); before = open(p).read()
        real = os.replace
        def boom(*a, **k):
            raise OSError("crash between tmp write and rename")
        os.replace = boom
        try:
            with self.assertRaises(OSError):
                B.save(p, B.empty_state())
        finally:
            os.replace = real
        self.assertEqual(open(p).read(), before); B.load(p)


def _race(d, job, q):
    w = World()
    w.pids = {os.getpid(): 1}
    r = B.reserve(d, req(job, pct=300, pid=os.getpid()), w.probes(), {})
    q.put((job, r.admit))


class Concurrency(Base):
    def test_two_processes_racing_for_the_last_budget(self):                   # real flock, two processes
        ctx = mp.get_context("fork")
        q = ctx.Queue()
        ps = [ctx.Process(target=_race, args=(self.d, j, q)) for j in ("p1", "p2")]
        for p in ps:
            p.start()
        for p in ps:
            p.join(30)
        res = dict(q.get(timeout=5) for _ in ps)
        self.assertEqual(sorted(res.values()), [False, True], res)
        self.assertEqual(len(self.state()["leases"]), 1)


if __name__ == "__main__":
    unittest.main()
