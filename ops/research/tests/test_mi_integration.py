"""MI runner integration: offline end-to-end tests (no systemd unit, no real cgroup, no heavy compute).

A FakeHost stands in for `systemctl --user` / `systemd-run`: it runs the REAL guard (python -m mi_cpuguard.guard_main)
as a subprocess against a fake cgroup directory, applies BindsTo/Requisite/CollectMode semantics, and puts a
`systemctl` shim first on the guard's PATH so the guard's own kill calls are recorded, never sent to systemd.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from _helpers import ROOT

from research_exec import config, launcher
from research_exec import mi_campaign as MIC
from mi_cpuguard import ledger as L
from mi_cpuguard.guard_main import valid_kill_target

US = 1_000_000
SHIM = """#!/bin/sh
echo "$*" >> "$MI_SHIM_LOG"
exit 0
"""


class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


class FakeHost:
    def __init__(self, tmp):
        self.tmp = tmp
        self.cg_root = os.path.join(tmp, "cg")
        self.shim_dir = os.path.join(tmp, "shim")
        os.makedirs(self.shim_dir)
        with open(os.path.join(self.shim_dir, "systemctl"), "w") as fh:
            fh.write(SHIM)
        os.chmod(os.path.join(self.shim_dir, "systemctl"), 0o755)
        self.shim_log = os.path.join(tmp, "shim.log")
        open(self.shim_log, "w").close()
        self.units, self.calls = {}, []
        self.fail_unit_prefix = None

    # -------------------------------------------------- cgroup simulation
    def cgdir(self):
        return os.path.join(self.cg_root, "research.slice", "research-mi.slice")

    def usage(self):
        try:
            with open(os.path.join(self.cgdir(), "cpu.stat")) as fh:
                return int(fh.read().split()[1])
        except Exception:
            return None                                  # corrupted / missing: the harness never repairs it

    def _write(self, usage, pids):
        if usage is None:
            return
        d = self.cgdir()
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "cpu.stat.tmp"), "w") as fh:
            fh.write(f"usage_usec {usage}\nuser_usec {usage}\nsystem_usec 0\n")
        os.replace(os.path.join(d, "cpu.stat.tmp"), os.path.join(d, "cpu.stat"))
        with open(os.path.join(d, "pids.current"), "w") as fh:
            fh.write(f"{pids}\n")

    def burn(self, cpu_s):
        self.sync()
        if os.path.isdir(self.cgdir()):
            self._write(self.usage() + int(cpu_s * US), self._pids())

    def corrupt_counter(self):
        with open(os.path.join(self.cgdir(), "cpu.stat"), "w") as fh:
            fh.write("garbage\n")

    def _pids(self):
        return sum(1 for u in self.units.values() if u["kind"] in ("anchor", "job") and u["state"] == "active")

    # -------------------------------------------------- unit semantics
    def _guard_alive(self, name):
        u = self.units.get(name)
        return bool(u and u["kind"] == "guard" and u["proc"].poll() is None)

    def sync(self):
        """BindsTo: anchor/jobs die with their guard; CollectMode: a dead guard is unloaded; a slice kill (shim log)
        stops everything in the slice; an empty slice loses its cgroup."""
        with open(self.shim_log) as fh:
            fh.seek(getattr(self, "_shim_off", 0))
            new = fh.read()
            self._shim_off = fh.tell()
        slice_killed = "research-mi.slice" in new
        for n, u in list(self.units.items()):
            if u["kind"] == "guard" and u["proc"].poll() is not None:
                del self.units[n]
        for u in self.units.values():
            if u["kind"] in ("anchor", "job") and u["state"] == "active" and not self._guard_alive(u["binds"]):
                u["state"] = "inactive"
        if slice_killed:
            for u in self.units.values():
                if u["kind"] in ("anchor", "job"):
                    u["state"] = "inactive"
        if os.path.isdir(self.cgdir()) and self._pids() == 0:
            shutil.rmtree(self.cgdir())
        elif os.path.isdir(self.cgdir()):
            self._write(self.usage(), self._pids())

    def run(self, args, timeout=60):
        self.calls.append(list(args))
        self.sync()
        if args[0] == "systemd-run":
            name = next(a.split("=", 1)[1] for a in args if a.startswith("--unit="))
            if self.fail_unit_prefix and name.startswith(self.fail_unit_prefix):
                return R(1, err="simulated systemd-run failure")
            props = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
            req = next((p.split("=", 1)[1] for p in props if p.startswith("Requisite=")), None)
            if req and not self._guard_alive(req):
                return R(1, err=f"Unit {req} not active (Requisite)")
            if name.startswith("mi-cpuguard-"):
                i = args.index("mi_cpuguard.guard_main")
                env = dict(os.environ, PYTHONPATH=ROOT, INVOCATION_ID=uuid.uuid4().hex,
                           PATH=self.shim_dir + os.pathsep + os.environ["PATH"], MI_SHIM_LOG=self.shim_log)
                log = open(os.path.join(self.tmp, f"{name}.log"), "w")
                p = subprocess.Popen([sys.executable, "-m", "mi_cpuguard.guard_main", *args[i + 1:]], env=env,
                                     stdout=log, stderr=subprocess.STDOUT)
                self.units[name] = {"kind": "guard", "proc": p, "inv": env["INVOCATION_ID"], "log": log}
            else:
                binds = next((p.split("=", 1)[1] for p in props if p.startswith("BindsTo=")), None)
                kind = "anchor" if name.startswith("mi-anchor-") else "job"
                self.units[name] = {"kind": kind, "state": "active", "binds": binds}
                self._write(self.usage() if os.path.isdir(self.cgdir()) else 0, self._pids())
            return R(0)
        if args[:3] == ["systemctl", "--user", "show"]:
            name = args[-1]
            u = self.units.get(name)
            if not u:
                return R(0, out="ActiveState=inactive\nInvocationID=\nMainPID=0\n")
            if u["kind"] == "guard":
                return R(0, out=f"ActiveState=active\nInvocationID={u['inv']}\nMainPID={u['proc'].pid}\n")
            return R(0, out=f"ActiveState={u['state']}\nInvocationID=x\nMainPID=1\n")
        if args[:3] == ["systemctl", "--user", "stop"]:
            u = self.units.get(args[3])
            if u and u["kind"] == "guard" and u["proc"].poll() is None:
                u["proc"].send_signal(signal.SIGTERM)
                u["proc"].wait(15)
            elif u:
                u["state"] = "inactive"
            self.sync()
            return R(0)
        return R(0)                                       # set-property / others: recorded only

    def sigkill_guard(self, campaign):
        u = self.units[MIC.guard_unit(campaign)]
        u["proc"].send_signal(signal.SIGKILL)
        u["proc"].wait(10)
        self.sync()

    def wait_guard_exit(self, campaign, timeout=15):
        u = self.units.get(MIC.guard_unit(campaign))
        if u:
            rc = u["proc"].wait(timeout)
            self.sync()
            return rc
        return None

    def close(self):
        for u in self.units.values():
            if u["kind"] == "guard":
                if u["proc"].poll() is None:
                    u["proc"].kill()
                    u["proc"].wait(10)
                u["log"].close()


def make_cfg(tmp, **mi):
    cfg = config.load_config()
    cfg["state_dir"] = os.path.join(tmp, "state")
    cfg["python"] = sys.executable
    cfg["mi"].update({"enabled": True, "poll_s": 0.05, "margin_cpu_s": 1.0, "max_gap_s": 2.0,
                      "ready_timeout_s": 15.0, "wait_cgroup_s": 5.0, "close_timeout_s": 15.0,
                      "cgroup_root": os.path.join(tmp, "cg")})
    cfg["mi"].update(mi)
    return cfg


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.host = FakeHost(self.td.name)
        self.cfg = make_cfg(self.td.name)
        self.prof = config.resolve_profile(self.cfg, "R1", workers=None, allow_elevated=False, attended=False,
                                           max_runtime_s=None)

    def tearDown(self):
        self.host.close()
        self.td.cleanup()

    def open(self, c, res=10.0):
        return MIC.open_campaign(self.cfg, c, res, run=self.host.run, sleep=time.sleep)

    def ledger(self):
        return L.BudgetLedger(MIC.paths(self.cfg)["ledger"], cap_cpu_s=self.cfg["mi"]["cap_cpu_s"]).state()


# ====================================================================== 1-2: opt-in, non-MI behaviour preserved
class OptInAndRegression(unittest.TestCase):
    def test_disabled_by_default_everywhere(self):
        cfg = config.load_config()
        self.assertFalse(cfg["mi"]["enabled"])
        with tempfile.TemporaryDirectory() as td:
            cfg["state_dir"] = td
            with self.assertRaises(MIC.MIError):
                MIC.open_campaign(cfg, "c1", 100.0, run=lambda a, **k: self.fail(f"unexpected call {a}"))
            prof = config.resolve_profile(cfg, "R1", workers=None, allow_elevated=False, attended=False,
                                          max_runtime_s=None)
            with self.assertRaises(MIC.MIError):
                launcher.launch(cfg, job_id="j1", owner="t", profile=prof, cmd=["/bin/true"], mi_campaign="c1")
            self.assertFalse(os.path.exists(os.path.join(td, "jobs", "j1")))      # refused before any side effect

    def test_non_mi_argv_identical_to_baseline_runner(self):
        src = subprocess.run(["git", "-C", ROOT, "show", "0f12d3a:ops/research/research_exec/launcher.py"],
                             capture_output=True, text=True)
        if src.returncode != 0:
            self.skipTest("baseline 0f12d3a not reachable")
        spec = importlib.util.spec_from_loader("research_exec._baseline_launcher", loader=None)
        base = importlib.util.module_from_spec(spec)
        base.__package__ = "research_exec"
        base.__file__ = os.path.join(ROOT, "research_exec", "launcher.py")
        exec(compile(src.stdout, "baseline_launcher.py", "exec"), base.__dict__)
        cfg = config.load_config()
        for name in ("R1", "R2", "R3", "LIGHT"):
            prof = config.resolve_profile(cfg, name, workers=None, allow_elevated=True, attended=True,
                                          max_runtime_s=None)
            a = ("t1", "own", prof, "/tmp/j", "/tmp/l", ["/bin/true", "x"], "/tmp", ["K=V", "PYTHONPATH=/z"])
            self.assertEqual(launcher.build_job_cmd(cfg, *a), base.build_job_cmd(cfg, *a), name)
            self.assertEqual(launcher.build_watchdog_cmd(cfg, "t1", "own", prof, "/tmp/j", "/c.json"),
                             base.build_watchdog_cmd(cfg, "t1", "own", prof, "/tmp/j", "/c.json"), name)


# ====================================================================== 3: 600 % aggregate quota
class Quota(Base):
    def test_slice_and_job_placement(self):
        cmd = MIC.mi_slice_cmd(self.cfg)
        self.assertIn("CPUQuota=600%", cmd)
        self.assertIn("research-mi.slice", cmd)
        self.assertIn("MemorySwapMax=0", cmd)
        self.assertTrue(MIC.slice_cgroup_dir(self.cfg).endswith("research.slice/research-mi.slice"))
        self.open("q1")
        ex = MIC.job_extra(self.cfg, "q1", self.prof, run=self.host.run)
        argv = launcher.build_job_cmd(self.cfg, "j", "o", self.prof, "/tmp/j", "/tmp/l", ["/bin/true"], "/tmp", [],
                                      slice_name=ex["slice"], extra_props=ex["props"])
        self.assertIn("--slice=research-mi.slice", argv)
        for p in ("BindsTo=mi-cpuguard-q1.service", "Requisite=mi-cpuguard-q1.service", "After=mi-cpuguard-q1.service"):
            self.assertIn(p, argv)
        self.assertNotIn("--slice=research.slice", argv)

    def test_ceilings_cannot_be_raised(self):
        for over in ({"cpu_quota_pct": 700}, {"cap_cpu_s": 30_000}, {"slice": "tsbops.slice"},
                     {"slice": "research.slice"}, {"margin_cpu_s": 0.1}):
            cfg = make_cfg(self.td.name, **over)
            with self.assertRaises(MIC.MIError, msg=str(over)):
                MIC.mi_cfg(cfg)
        self.open("q2")
        r3 = config.resolve_profile(self.cfg, "R3", workers=None, allow_elevated=True, attended=True,
                                    max_runtime_s=None)
        with self.assertRaises(MIC.MIError):
            MIC.job_extra(self.cfg, "q2", r3, run=self.host.run)          # 800 % profile > 600 % slice


# ====================================================================== 4: cumulative budget, retries, crashes
class Budget(Base):
    def test_open_burn_close_charges_measured(self):
        self.open("b1", 10.0)
        self.host.burn(2.5)
        time.sleep(0.2)
        rec = MIC.close_campaign(self.cfg, "b1", run=self.host.run)
        self.assertEqual(rec["status"], "closed")
        st = self.ledger()
        self.assertEqual(st["open_reservations"], {})
        self.assertAlmostEqual(st["charged_cpu_s"], 2.5, places=3)

    def test_budget_kill_charges_at_most_the_reservation(self):
        self.open("b2", 5.0)
        for _ in range(200):
            if self.host.units.get(MIC.guard_unit("b2"), {}).get("proc") is None or \
                    self.host.units[MIC.guard_unit("b2")]["proc"].poll() is not None:
                break
            self.host.burn(0.25)
            time.sleep(0.05)
        rc = self.host.wait_guard_exit("b2")
        self.assertEqual(rc, 2)
        with open(self.host.shim_log) as fh:
            self.assertIn("kill --kill-whom=all --signal=SIGKILL research-mi.slice", fh.read())
        st = self.ledger()
        self.assertLessEqual(st["charged_cpu_s"], 5.0)
        self.assertGreaterEqual(st["charged_cpu_s"], 4.0)

    def test_retries_and_crashes_never_free_budget(self):
        cfg = make_cfg(self.td.name, cap_cpu_s=20.0)
        self.cfg = cfg
        self.open("r1", 12.0)
        with self.assertRaises(MIC.MIError):
            self.open("r1", 1.5)                                            # single-use id
        with self.assertRaises(MIC.MIError):
            self.open("r2", 9.0)                                            # 12 open + 9 > cap 20
        self.host.sigkill_guard("r1")                                       # crash: no charge written
        self.assertEqual(self.ledger()["open_reservations"], {"r1": 12.0})
        with self.assertRaises(MIC.MIError):
            self.open("r2", 9.0)                                            # crashed reservation still consumed
        rec = MIC.recover_campaign(cfg, "r1", run=self.host.run)
        self.assertEqual(rec["status"], "recovered")
        st = self.ledger()
        self.assertEqual((st["charged_cpu_s"], st["remaining_cpu_s"]), (12.0, 8.0))
        again = MIC.recover_campaign(cfg, "r1", run=self.host.run)          # idempotent
        self.assertEqual(again["status"], "recovered")
        self.assertEqual(self.ledger()["charged_cpu_s"], 12.0)
        self.open("r3", 7.0)                                                # within the remaining 8


# ====================================================================== 5: fail closed
class FailClosed(Base):
    def test_guard_death_stops_jobs_and_refuses_new_ones(self):
        self.open("f1")
        ex = MIC.job_extra(self.cfg, "f1", self.prof, run=self.host.run)
        argv = launcher.build_job_cmd(self.cfg, "j1", "o", self.prof, "/tmp/j", "/tmp/l", ["/bin/true"], "/tmp", [],
                                      slice_name=ex["slice"], extra_props=ex["props"])
        self.assertEqual(self.host.run(argv).returncode, 0)
        self.host.sigkill_guard("f1")
        self.assertEqual(self.host.units["rj-j1.service"]["state"], "inactive")
        with self.assertRaises(MIC.MIError):
            MIC.job_extra(self.cfg, "f1", self.prof, run=self.host.run)
        self.assertEqual(self.host.run(argv).returncode, 1)                 # Requisite: guard gone

    def test_counter_failure_kills_and_charges_full_reservation(self):
        self.open("f2", 6.0)
        self.host.burn(1.0)
        time.sleep(0.15)
        self.host.corrupt_counter()
        rc = self.host.wait_guard_exit("f2")
        self.assertEqual(rc, 2)
        with open(self.host.shim_log) as fh:
            self.assertIn("research-mi.slice", fh.read())
        st = self.ledger()
        self.assertEqual((st["charged_cpu_s"], st["open_reservations"]), (6.0, {}))

    def test_job_refused_when_ready_invocation_mismatches(self):
        self.open("f3")
        p = MIC.paths(self.cfg, "f3")
        with open(p["ready"]) as fh:
            ready = json.load(fh)
        ready["invocation_id"] = "deadbeef"
        with open(p["ready"], "w") as fh:
            json.dump(ready, fh)
        with self.assertRaises(MIC.MIError):
            MIC.job_extra(self.cfg, "f3", self.prof, run=self.host.run)

    def test_corrupted_ledger_refuses_open_without_side_effects(self):
        led = MIC.paths(self.cfg)["ledger"]
        os.makedirs(os.path.dirname(led), exist_ok=True)
        L.BudgetLedger(led).reserve("old", 1.0)
        with open(led, "a") as fh:
            fh.write('{"seq": 99, "bogus": true}\n')
        n = len(self.host.calls)
        with self.assertRaises(L.LedgerTamper):
            self.open("f4")
        self.assertEqual(len(self.host.calls), n)                            # nothing started
        with self.assertRaises(L.LedgerTamper):
            MIC.recover_campaign(self.cfg, "old", run=self.host.run)          # STOP for the owner

    def test_ledger_corrupted_mid_campaign_guard_kills_and_stops(self):
        self.open("f5", 6.0)
        self.host.burn(0.5)
        led = MIC.paths(self.cfg)["ledger"]
        with open(led, "a") as fh:
            fh.write("not json\n")
        self.host.burn(6.0)                                                  # forces the budget kill + charge
        rc = self.host.wait_guard_exit("f5")
        self.assertEqual(rc, 4)                                              # STOP: kill issued, charge impossible
        with open(self.host.shim_log) as fh:
            self.assertIn("research-mi.slice", fh.read())


# ====================================================================== 6: kill scope
class KillScope(unittest.TestCase):
    def test_only_an_mi_child_slice_of_research_can_be_killed(self):
        good = "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/research.slice/research-mi.slice"
        self.assertTrue(valid_kill_target("research-mi.slice", good))
        bad = [("research.slice", good.rsplit("/", 1)[0]),
               ("tsb-p2-forward-collector", good), ("docker-ce4e6b6656a5.scope", good),
               ("tsb-p2f-monitor.service", good), ("tsbops.slice", good), ("app.slice", good), ("user.slice", good),
               ("research-mi.slice", "/sys/fs/cgroup/system.slice/research-mi.slice"),
               ("research-mi.slice", good + "/../../system.slice/research-mi.slice"),
               ("research-mi.slice;rm", good), ("", good)]
        for unit, path in bad:
            self.assertFalse(valid_kill_target(unit, path), (unit, path))

    def test_guard_refuses_bad_target_before_reserving(self):
        from mi_cpuguard import guard_main
        with tempfile.TemporaryDirectory() as td:
            led = os.path.join(td, "b.jsonl")
            rc = guard_main.main(["--campaign", "x", "--reservation-cpu-s", "10", "--ledger", led,
                                  "--cgroup-dir", "/sys/fs/cgroup/system.slice/docker-x.scope",
                                  "--kill-unit", "docker-x.scope", "--ready-file", os.path.join(td, "r"),
                                  "--close-file", os.path.join(td, "c")])
            self.assertEqual(rc, 3)
            self.assertFalse(os.path.exists(led))

    def test_kill_always_goes_to_the_user_manager(self):
        from unittest import mock
        from mi_cpuguard import guard
        with mock.patch.object(guard.subprocess, "run") as r:
            guard.systemd_kill("research-mi.slice")
        for call in r.call_args_list:
            argv = call.args[0]
            self.assertEqual(argv[:2], ["systemctl", "--user"])
            self.assertNotIn("--system", argv)
            self.assertEqual(argv[-1], "research-mi.slice")


# ====================================================================== 7: rollback, idempotency, interrupted campaigns
class RollbackAndRecovery(Base):
    def test_failed_guard_start_aborts_without_reservation(self):
        self.host.fail_unit_prefix = "mi-cpuguard-"
        with self.assertRaises(MIC.MIError):
            self.open("o1")
        self.assertEqual(self.ledger()["events"], 0)
        with open(MIC.paths(self.cfg, "o1")["campaign"]) as fh:
            self.assertEqual(json.load(fh)["status"], "aborted")
        with self.assertRaises(MIC.MIError):
            self.open("o1")                                                  # ids stay single-use
        self.host.fail_unit_prefix = None
        self.open("o2")

    def test_failed_anchor_start_aborts_and_guard_charges(self):
        self.host.fail_unit_prefix = "mi-anchor-"
        with self.assertRaises(MIC.MIError):
            self.open("o3")
        self.host.wait_guard_exit("o3")
        st = self.ledger()
        self.assertEqual(st["open_reservations"], {})                        # never reserved (no cgroup) or charged

    def test_close_is_idempotent(self):
        self.open("o4")
        self.host.burn(1.0)
        a = MIC.close_campaign(self.cfg, "o4", run=self.host.run)
        b = MIC.close_campaign(self.cfg, "o4", run=self.host.run)
        self.assertEqual((a["status"], b["status"]), ("closed", "closed"))
        self.assertEqual(self.ledger()["events"], 2)                         # one reserve, one charge

    def test_recover_refused_while_guard_alive_then_clean_after_close(self):
        self.open("o5")
        with self.assertRaises(MIC.MIError):
            MIC.recover_campaign(self.cfg, "o5", run=self.host.run)
        MIC.close_campaign(self.cfg, "o5", run=self.host.run)
        rec = MIC.recover_campaign(self.cfg, "o5", run=self.host.run)
        self.assertEqual(self.ledger()["open_reservations"], {})
        self.assertIn(rec["status"], ("closed", "no_open_reservation"))

    def test_single_open_campaign_at_a_time(self):
        self.open("s1", 5.0)
        with self.assertRaises(MIC.MIError) as cm:
            self.open("s2", 5.0)
        self.assertIn("another campaign is open", str(cm.exception))
        MIC.close_campaign(self.cfg, "s1", run=self.host.run)
        self.open("s2", 5.0)

    def test_interrupted_open_after_reservation_is_recoverable(self):
        self.open("o6", 8.0)
        self.host.burn(1.0)
        self.host.sigkill_guard("o6")                                        # operator / host crash mid-campaign
        self.assertFalse(os.path.isdir(self.host.cgdir()))                   # slice emptied with the guard
        rec = MIC.recover_campaign(self.cfg, "o6", run=self.host.run)
        self.assertEqual((rec["status"], rec["charged_cpu_s"]), ("recovered", 8.0))
        self.open("o7", 5.0)


if __name__ == "__main__":
    unittest.main()
