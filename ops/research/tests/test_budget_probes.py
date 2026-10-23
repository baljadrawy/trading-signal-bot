"""Tests for research_exec.budget_probes (I-1b): fake /proc trees and fake systemctl output; read-only smoke on the
real /proc of this process only. Nothing starts, stops or changes a unit."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research_exec import budget_probes as P  # noqa: E402


def fake_run(table):
    def run(args):
        return table.get(tuple(args))
    return run


def stat_line(pid, comm, start):
    # fields 3..21 filler, field 22 = start ticks
    rest = ["S"] + ["0"] * 18 + [str(start)] + ["0"] * 10
    return f"{pid} ({comm}) " + " ".join(rest)


class FakeProc:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = self.tmp.name

    def add(self, pid, comm="python3", start=12345, env=(), cgroup="0::/user.slice/x.scope"):
        d = os.path.join(self.root, str(pid)); os.makedirs(d)
        open(os.path.join(d, "stat"), "w").write(stat_line(pid, comm, start))
        open(os.path.join(d, "environ"), "wb").write(b"\0".join(e.encode() for e in env) + b"\0")
        open(os.path.join(d, "cgroup"), "w").write(cgroup + "\n")


class Probes(unittest.TestCase):
    def test_pid_start_ticks_parses_field_22_even_with_spaces_in_comm(self):
        fp = FakeProc(); fp.add(42, comm="weird) name (x", start=987654)
        self.assertEqual(P.pid_start_ticks(42, proc=fp.root), 987654)
        self.assertIsNone(P.pid_start_ticks(43, proc=fp.root))

    def test_real_proc_smoke_read_only(self):
        t = P.pid_start_ticks(os.getpid())
        self.assertIsInstance(t, int); self.assertGreater(t, 0)
        self.assertEqual(t, P.pid_start_ticks(os.getpid()))
        self.assertRegex(P.boot_id(), r"^[0-9a-f-]{36}$")

    def test_unit_states(self):
        run = fake_run({("is-active", "a"): "active\n", ("is-active", "b"): "inactive\n",
                        ("is-active", "c"): "failed\n", ("is-active", "d"): "weird\n"})
        self.assertIs(P.is_unit_active("a", run), True)
        self.assertIs(P.is_unit_active("b", run), False)
        self.assertIs(P.is_unit_active("c", run), False)
        self.assertIsNone(P.is_unit_active("d", run))                 # unknown -> refuse
        self.assertIsNone(P.is_unit_active("e", run))                 # systemctl unavailable -> refuse

    def test_quota_parsing(self):
        for v, pct in (("8s", 800), ("1.5s", 150), ("800ms", 80), ("infinity", None), ("", None), ("bogus", None)):
            self.assertEqual(P._quota_pct(v), pct, v)

    def test_slice_and_lab_quota(self):
        show = ("show", "-p", "LoadState,ActiveState,CPUQuotaPerSecUSec")
        run = fake_run({show + ("research.slice",): "LoadState=loaded\nActiveState=active\nCPUQuotaPerSecUSec=8s\n",
                        show + ("tsblab.slice",): "LoadState=not-found\nActiveState=inactive\nCPUQuotaPerSecUSec=infinity\n"})
        self.assertEqual(P.slice_quota_pct(run=run), 800)
        self.assertEqual(P.lab_slice_pct(run=run), 0)                 # no lab slice
        run2 = fake_run({show + ("tsblab.slice",): "LoadState=loaded\nActiveState=active\nCPUQuotaPerSecUSec=1s\n"})
        self.assertEqual(P.lab_slice_pct(run=run2), 100)
        run3 = fake_run({show + ("tsblab.slice",): "LoadState=loaded\nActiveState=active\nCPUQuotaPerSecUSec=infinity\n"})
        self.assertIsNone(P.lab_slice_pct(run=run3))                  # active lab slice without a quota: refuse
        self.assertIsNone(P.lab_slice_pct(run=fake_run({})))          # unreadable: refuse

    def test_marker_processes_outside_slice(self):
        fp = FakeProc(); uid = os.getuid()
        fp.add(10, env=("RESEARCH_JOB_ID=j1",), cgroup="0::/user.slice/user-1000.slice/user@1000.service/research.slice/rj-j1.service")
        fp.add(11, env=("RESEARCH_JOB_ID=j2",), cgroup="0::/system.slice/docker-abc.scope")
        fp.add(12, env=("PATH=/bin",), cgroup="0::/user.slice/other.scope")
        fp.add(13, env=("RESEARCH_JOB_ID=j3",), cgroup="0::/user.slice/user@1000.service/research-mi.slice/x.service")
        hits = P.marker_procs_outside_slice(proc=fp.root, uid=uid)
        self.assertEqual([h["pid"] for h in hits], [11])
        self.assertIsNone(P.marker_procs_outside_slice(proc="/nonexistent-proc-root", uid=uid))

    def test_live_job_units(self):
        lst = ("list-units", "--all", "--no-legend", "--plain", "rj-*.service")
        run = fake_run({lst: "rj-a.service loaded active running x\nrj-b.service loaded inactive dead y\n"
                             "rj-c.service loaded activating start z\n"})
        self.assertEqual(P.live_job_units(run), ["rj-a.service", "rj-c.service"])
        self.assertIsNone(P.live_job_units(fake_run({})))

    def test_host_probes_wire_into_budget(self):
        from research_exec import budget as B
        pr = P.host_probes()
        self.assertIsInstance(pr, B.Probes)
        self.assertEqual(pr.pid_start_ticks(os.getpid()), P.pid_start_ticks(os.getpid()))

    def test_host_probes_systemctl_timeout(self):
        for kw, want in (({}, 10), ({"systemctl_timeout_s": 0.5}, 0.5)):
            pr = P.host_probes(**kw)
            with mock.patch.object(P.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="active\n")) as r:
                self.assertTrue(pr.is_unit_active("rj-a.service"))
                pr.lab_slice_pct(), pr.slice_quota_pct(), pr.live_job_units()
            self.assertEqual([c.kwargs["timeout"] for c in r.call_args_list], [want] * 4, kw)
        with mock.patch.object(P.subprocess, "run", side_effect=P.subprocess.TimeoutExpired("systemctl", 0.5)):
            self.assertIsNone(P.host_probes(systemctl_timeout_s=0.5).is_unit_active("rj-a.service"))


if __name__ == "__main__":
    unittest.main()
