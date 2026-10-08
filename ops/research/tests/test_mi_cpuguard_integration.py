"""MI CPU guard: real-kernel checks through throwaway systemd --user transient units (opt-in).

Run only with MI_CPUGUARD_INTEGRATION=1, outside protected windows, after the host admission gate admits. Uses a
private test slice migt<rand>.slice (NOT research.slice, NOT the runner), CPUWeight=idle, MemorySwapMax=0, and
spends about 13 CPU-s in total. Every unit carries the migt<rand> prefix; tearDown stops all and asserts none remain.
"""
from __future__ import annotations

import os
import random
import string
import subprocess
import tempfile
import time
import unittest

import _helpers  # noqa: F401

from mi_cpuguard import ledger as L
from mi_cpuguard.guard import Guard, read_usage_usec, systemd_kill

ENABLED = os.environ.get("MI_CPUGUARD_INTEGRATION") == "1"
CGBASE = f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"
BURN = ("import multiprocessing as m,time,sys\n"
        "def b(t):\n"
        "    e=time.time()+t\n"
        "    while time.time()<e: pass\n"
        "n,t=int(sys.argv[1]),float(sys.argv[2])\n"
        "ps=[m.Process(target=b,args=(t,)) for _ in range(n)]\n"
        "[p.start() for p in ps];[p.join() for p in ps]\n")


def sh(*a, timeout=60):
    return subprocess.run(list(a), capture_output=True, text=True, timeout=timeout)


def active(unit):
    return sh("systemctl", "--user", "show", "-p", "ActiveState", "--value", unit).stdout.strip()


@unittest.skipUnless(ENABLED, "set MI_CPUGUARD_INTEGRATION=1 (real transient units)")
class RealKernel(unittest.TestCase):
    def setUp(self):
        self.tag = "migt" + "".join(random.choice(string.ascii_lowercase) for _ in range(6))
        self.slice = f"{self.tag}.slice"
        self.units = []

    def tearDown(self):
        for u in self.units:
            sh("systemctl", "--user", "kill", "--kill-whom=all", "--signal=SIGKILL", u)
            sh("systemctl", "--user", "stop", u)
            sh("systemctl", "--user", "reset-failed", u)
        sh("systemctl", "--user", "stop", self.slice)
        sh("systemctl", "--user", "revert", self.slice)
        left = sh("systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", f"{self.tag}*").stdout.strip()
        self.assertEqual(left, "", f"leftover units: {left}")

    def mk_slice(self, quota_pct):
        r = sh("systemctl", "--user", "set-property", "--runtime", self.slice, f"CPUQuota={quota_pct}%",
               "CPUWeight=idle", "MemoryMax=256M", "MemorySwapMax=0", "TasksMax=64")
        self.assertEqual(r.returncode, 0, r.stderr)

    def run_unit(self, name, cmd, slice_=None, props=(), wait=False, timeout=60):
        u = f"{self.tag}-{name}.service"
        self.units.append(u)
        a = ["systemd-run", "--user", "--quiet", f"--unit={u}", f"--slice={slice_ or self.slice}",
             "-p", "RuntimeMaxSec=120", "-p", "MemorySwapMax=0"]
        for p in props:
            a += ["-p", p]
        if wait:
            a.append("--wait")
        return u, sh(*a, *cmd, timeout=timeout)

    def cg(self):
        return f"{CGBASE}/{self.slice}"

    def test_i1_slice_quota_600_caps_all_children(self):
        self.mk_slice(600)
        self.run_unit("anchor", ["/bin/sleep", "60"])
        time.sleep(0.5)
        with open(f"{self.cg()}/cpu.max") as fh:
            self.assertEqual(fh.read().split(), ["600000", "100000"])
        u0, t0 = read_usage_usec(self.cg()), time.monotonic()
        _, r = self.run_unit("burn", ["/usr/bin/python3", "-c", BURN, "9", "1.5"], wait=True)
        u1, t1 = read_usage_usec(self.cg()), time.monotonic()
        self.assertEqual(r.returncode, 0, r.stderr)
        rate = (u1 - u0) / 1e6 / (t1 - t0)
        print(f"\nI1: 9 busy children, slice CPUQuota=600%: {(u1 - u0) / 1e6:.2f} CPU-s over {t1 - t0:.2f} s "
              f"= {rate:.2f} cores (cap 6.00)")
        self.assertLessEqual(rate, 6.05)

    def test_i2_guard_kills_on_cumulative_budget(self):
        self.mk_slice(200)
        self.run_unit("anchor", ["/bin/sleep", "90"])
        time.sleep(0.5)
        burn, r = self.run_unit("burn", ["/usr/bin/python3", "-c", BURN, "4", "60"])
        self.assertEqual(r.returncode, 0, r.stderr)
        with tempfile.TemporaryDirectory() as td:
            led = L.BudgetLedger(os.path.join(td, "b.jsonl"))
            g = Guard(reader=lambda: read_usage_usec(self.cg()), killer=lambda: systemd_kill(burn), ledger=led,
                      campaign=self.tag, reservation_cpu_s=4.0, margin_cpu_s=2.0, poll_s=0.5, max_gap_s=1.5)
            self.assertTrue(g.start())
            out = g.run(max_polls=200)
            print(f"\nI2: {out}")
            self.assertEqual(out["verdict"], "KILL")
            self.assertIn("budget", out["reason"])
            self.assertEqual(out["basis"], "cgroup_usage_usec")
            self.assertLessEqual(out["charged_cpu_s"], 4.0)
            time.sleep(1.0)
            self.assertIn(active(burn), ("inactive", "failed", ""))
            self.assertEqual(led.state()["open_reservations"], {})

    def test_i3_jobs_die_with_the_guard_and_never_start_without_it(self):
        self.mk_slice(100)
        guard, r = self.run_unit("guard", ["/bin/sleep", "100"], slice_="app.slice",
                                 props=("CollectMode=inactive-or-failed",))
        self.assertEqual(r.returncode, 0, r.stderr)
        time.sleep(0.5)
        props = (f"BindsTo={guard}", f"Requisite={guard}", f"After={guard}")
        job, r = self.run_unit("job", ["/bin/sleep", "100"], props=props)
        self.assertEqual(r.returncode, 0, r.stderr)
        time.sleep(0.5)
        self.assertEqual(active(job), "active")
        sh("systemctl", "--user", "kill", "--signal=SIGKILL", guard)                    # guard dies
        for _ in range(50):
            if active(job) in ("inactive", "failed", ""):
                break
            time.sleep(0.1)
        self.assertIn(active(job), ("inactive", "failed", ""))
        job2, r2 = self.run_unit("job2", ["/bin/sleep", "100"], props=props)            # guard gone -> refused
        time.sleep(0.5)
        self.assertIn(active(guard), ("inactive", "failed", ""), "a job start must never resurrect the guard")
        self.assertNotEqual(r2.returncode, 0)
        self.assertIn(active(job2), ("inactive", "failed", ""))
        print(f"\nI3: job stopped after guard SIGKILL; job2 start without guard rc={r2.returncode} "
              f"state={active(job2) or 'unloaded'}")

    def test_i4_counter_vanishes_kill_and_full_charge(self):
        self.mk_slice(100)
        anchor, _ = self.run_unit("anchor", ["/bin/sleep", "60"])
        time.sleep(0.5)
        with tempfile.TemporaryDirectory() as td:
            led = L.BudgetLedger(os.path.join(td, "b.jsonl"))
            killed = []
            g = Guard(reader=lambda: read_usage_usec(self.cg()), killer=lambda: killed.append(1), ledger=led,
                      campaign=self.tag, reservation_cpu_s=3.0, margin_cpu_s=1.0, poll_s=0.2, max_gap_s=1.0)
            self.assertTrue(g.start())
            sh("systemctl", "--user", "stop", anchor)                                    # slice empties -> cgroup gone
            sh("systemctl", "--user", "stop", self.slice)
            time.sleep(0.5)
            out = g.run(max_polls=50)
            print(f"\nI4: {out}")
            self.assertEqual(out["verdict"], "KILL")
            self.assertEqual(killed, [1])
            self.assertEqual((out["charged_cpu_s"], out["basis"]), (3.0, "full_reservation_unreadable"))


if __name__ == "__main__":
    unittest.main()
