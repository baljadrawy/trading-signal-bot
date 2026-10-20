"""End-to-end tests through real `systemd --user` transient units (opt-in).

Run only with RESEARCH_EXEC_INTEGRATION=1 on a host where research is allowed to run; they
start small synthetic CPU jobs (<= 2 vCPU for seconds) under test profiles TINT/TOOM.
Collector inputs are FAKE files in a temp dir (never the real Collector), so degradation is
simulated by rewriting the fake health file. Every unit is named rj-/rw-g1g2t-<rand> and
carries owner tag g1g2-validation; tearDown stops anything left (bounded) and asserts none.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import string
import subprocess
import sys
import time
import unittest

from _helpers import ROOT, make_env, wait_until, write_health

from research_exec.detpool import make_units, run_units

sys.path.insert(0, os.path.join(ROOT, "examples"))
import synthetic_cpu  # noqa: E402

RUN = os.path.join(ROOT, "bin", "research-run")
SCRIPT = os.path.join(ROOT, "examples", "synthetic_cpu.py")
OWNER = "g1g2-validation"
TMP = os.environ.get("TMPDIR")
ENABLED = os.environ.get("RESEARCH_EXEC_INTEGRATION") == "1"


def sh(*a, timeout=60):
    return subprocess.run(list(a), capture_output=True, text=True, timeout=timeout)


def prop(unit, name):
    return sh("systemctl", "--user", "show", "-p", name, "--value", unit).stdout.strip()


def is_live(unit):
    return prop(unit, "ActiveState") in ("active", "activating", "deactivating", "reloading")


def cg_dir(unit):
    cg = prop(unit, "ControlGroup")
    return "/sys/fs/cgroup" + cg if cg else None


def read(path):
    with open(path) as fh:
        return fh.read().strip()


def usage_usec(cgd):
    for line in read(os.path.join(cgd, "cpu.stat")).splitlines():
        if line.startswith("usage_usec"):
            return int(line.split()[1])


def procs_with_job_env(job_id):
    """One-shot /proc scan for processes carrying RESEARCH_JOB_ID=<job_id> (straggler check)."""
    needle = f"RESEARCH_JOB_ID={job_id}".encode()
    out = []
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                with open(f"/proc/{d}/environ", "rb") as fh:
                    if needle in fh.read().split(b"\0"):
                        out.append(int(d))
            except OSError:
                pass
    return out


@unittest.skipUnless(ENABLED, "set RESEARCH_EXEC_INTEGRATION=1 to run systemd integration tests")
class TestSystemdIntegration(unittest.TestCase):
    def setUp(self):
        self.env = make_env(TMP)
        self.jobs = []
        self.log = []

    def tearDown(self):
        for j in self.jobs:
            for u in (f"rj-{j}.service", f"rw-{j}.service"):
                if is_live(u):
                    sh("systemctl", "--user", "kill", "--kill-whom=all", "--signal=SIGKILL", u)
                    sh("systemctl", "--user", "stop", u)
            self.assertFalse(is_live(f"rj-{j}.service"))
            self.assertFalse(is_live(f"rw-{j}.service"))
            self.assertEqual(procs_with_job_env(j), [], f"stragglers for {j}")
        out = os.environ.get("G1G2_EVIDENCE_OUT")
        if out:
            for j in self.jobs:      # keep the per-job artefacts (records, watchdog.jsonl) as evidence
                src = self.job_dir(j)
                if os.path.isdir(src):
                    shutil.copytree(src, os.path.join(out, "jobs", j), dirs_exist_ok=True)
            with open(os.path.join(out, f"{self.id().split('.')[-1]}.json"), "w") as fh:
                json.dump({"jobs": self.jobs, "log": self.log,
                           "records": {j: self.record(j) for j in self.jobs}}, fh, indent=2, default=str)
        shutil.rmtree(self.env["dir"], ignore_errors=True)

    # ---------------------------------------------------------------- helpers
    def new_id(self):
        j = "g1g2t-" + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))
        self.jobs.append(j)
        return j

    def start(self, job, profile, cmd, extra=(), wait=False, timeout=240):
        args = [RUN, "run", "--job-id", job, "--owner", OWNER, "--profile", profile,
                "--config", self.env["config"], "--cwd", self.env["dir"], *extra]
        if wait:
            args.append("--wait")
        r = sh(*args, "--", *cmd, timeout=timeout)
        self.log.append({"job": job, "rc": r.returncode, "stdout": r.stdout, "stderr": r.stderr})
        return r

    def job_dir(self, job):
        return os.path.join(self.env["dir"], "state", "jobs", job)

    def record(self, job):
        p = os.path.join(self.job_dir(job), "job_record.json")
        if os.path.exists(p):
            with open(p) as fh:
                return json.load(fh)
        return None

    def synth(self, n, iters, out_name="merged.json"):
        return [sys.executable, SCRIPT, "--units", str(n), "--iters", str(iters),
                "--checkpoint", os.path.join(self.env["dir"], out_name + ".ckpt"),
                "--out", os.path.join(self.env["dir"], out_name)]

    def expected(self, n, iters):
        us = make_units([f"u{i:04d}" for i in range(n)], 20261006, params={"iters": iters})
        return run_units(synthetic_cpu.mc_unit, us, workers=1, fn_id="synthetic_cpu.mc_unit",
                         meta={"iters": iters}).result_sha256

    def merged_sha(self, out_name="merged.json"):
        import hashlib
        with open(os.path.join(self.env["dir"], out_name), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    # ---------------------------------------------------------------- tests
    def test_1_envelope_oom_adj_watchdog_lifetime_record(self):
        n, iters = 6, 3000000
        want = self.expected(n, iters)
        j = self.new_id()
        r = self.start(j, "TINT", self.synth(n, iters))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        rj, rw = f"rj-{j}.service", f"rw-{j}.service"
        cgd = wait_until(lambda: cg_dir(rj) if is_live(rj) else None, 15, what="job cgroup")
        # wait until workers exist (more than jobwrap + main)
        wait_until(lambda: len(read(os.path.join(cgd, "cgroup.procs")).split()) >= 3, 30,
                   what="worker processes")
        snap = {f: read(os.path.join(cgd, f)) for f in
                ("cpu.max", "cpu.idle", "cpu.weight", "memory.high", "memory.max", "pids.max",
                 "memory.oom.group")}
        pids = read(os.path.join(cgd, "cgroup.procs")).split()
        adjs = {}
        for p in pids:
            try:
                adjs[p] = read(f"/proc/{p}/oom_score_adj")
            except OSError:
                pass
        slice_cg = "/sys/fs/cgroup" + prop("research.slice", "ControlGroup")
        snap["slice.cpu.max"] = read(os.path.join(slice_cg, "cpu.max"))
        snap["slice.cpu.idle"] = read(os.path.join(slice_cg, "cpu.idle"))
        snap["slice.memory.max"] = read(os.path.join(slice_cg, "memory.max"))
        snap["watchdog_active"] = prop(rw, "ActiveState")
        snap["watchdog_bindsto"] = prop(rw, "BindsTo")
        snap["oom_score_adj"] = adjs
        self.log.append({"envelope_snapshot": snap})
        self.assertEqual(snap["cpu.max"], "200000 100000")
        self.assertEqual(snap["memory.max"], str(1536 * 1024 ** 2))
        self.assertEqual(snap["memory.high"], str(1024 * 1024 ** 2))
        self.assertEqual(snap["pids.max"], "64")
        self.assertEqual(snap["memory.oom.group"], "1")
        self.assertEqual(snap["cpu.idle"], "1")
        self.assertEqual(snap["slice.cpu.idle"], "1")
        self.assertEqual(snap["slice.cpu.max"], "800000 100000")
        self.assertEqual(snap["watchdog_active"], "active")
        self.assertIn(rj, snap["watchdog_bindsto"])
        self.assertTrue(adjs and all(v == "500" for v in adjs.values()), adjs)
        wait_until(lambda: not is_live(rj), 180, what="job end")
        t_end = time.monotonic()
        wait_until(lambda: not is_live(rw), 30, what="watchdog exit")
        self.log.append({"watchdog_exit_after_job_s": round(time.monotonic() - t_end, 2)})
        rec = wait_until(lambda: self.record(j), 20, what="job record")
        self.assertEqual((rec["status"], rec["exit_code"]), ("finished", 0))
        self.assertEqual(self.merged_sha(), want)
        self.assertGreater(rec["cpu_s_cgroup"], 0.5)
        self.assertGreater(rec["memory_peak_bytes"], 0)
        self.assertEqual(rec["admission"]["admit"], True)

    def test_2_freeze_stops_cpu_then_thaw_completes_correctly(self):
        n, iters = 8, 6000000
        want = self.expected(n, iters)
        j = self.new_id()
        rj, rw = f"rj-{j}.service", f"rw-{j}.service"
        self.assertEqual(self.start(j, "TINT", self.synth(n, iters)).returncode, 0)
        cgd = wait_until(lambda: cg_dir(rj) if is_live(rj) else None, 15, what="job cgroup")
        wait_until(lambda: usage_usec(cgd) > 1_500_000, 60, what="job burning CPU")
        write_health(self.env["health"], state="DEGRADED")          # simulated degradation
        t0 = time.monotonic()
        wait_until(lambda: prop(rj, "FreezerState") == "frozen", 15, what="freeze")
        freeze_latency = time.monotonic() - t0
        u1 = usage_usec(cgd)
        time.sleep(6)
        u2 = usage_usec(cgd)
        frozen_events = read(os.path.join(cgd, "cgroup.events"))
        self.log.append({"freeze_latency_s": round(freeze_latency, 2), "cpu_usec_delta_6s_frozen": u2 - u1,
                         "cgroup.events": frozen_events})
        self.assertLess(u2 - u1, 20000, "CPU must not advance while frozen")
        self.assertIn("frozen 1", frozen_events)
        self.assertTrue(is_live(rj))
        write_health(self.env["health"], state="HEALTHY")
        wait_until(lambda: prop(rj, "FreezerState") == "running", 20, what="thaw")
        u3 = usage_usec(cgd)
        time.sleep(2)
        self.log.append({"cpu_usec_delta_2s_after_thaw": usage_usec(cgd) - u3})
        wait_until(lambda: not is_live(rj), 240, what="job end")
        wait_until(lambda: not is_live(rw), 30, what="watchdog exit")
        rec = wait_until(lambda: self.record(j), 20, what="job record")
        self.assertEqual((rec["status"], rec["exit_code"]), ("finished", 0))
        self.assertEqual(self.merged_sha(), want)
        self.assertGreaterEqual(rec["frozen_total_s"], 6)
        self.assertIn("collector_state=DEGRADED", rec["freeze_periods"][0]["reasons"])

    def test_3_escalation_group_kill_no_stragglers(self):
        # cfg override: escalate after 3 s frozen
        with open(self.env["config"]) as fh:
            c = json.load(fh)
        c["watchdog"]["max_frozen_s"] = 3.0
        with open(self.env["config"], "w") as fh:
            json.dump(c, fh)
        j = self.new_id()
        rj, rw = f"rj-{j}.service", f"rw-{j}.service"
        self.assertEqual(self.start(j, "TINT", self.synth(8, 20_000_000)).returncode, 0)
        cgd = wait_until(lambda: cg_dir(rj) if is_live(rj) else None, 15, what="job cgroup")
        wait_until(lambda: len(read(os.path.join(cgd, "cgroup.procs")).split()) >= 3, 30, what="workers")
        before = read(os.path.join(cgd, "cgroup.procs")).split()
        write_health(self.env["health"], state="DEGRADED")
        wait_until(lambda: prop(rj, "FreezerState") == "frozen", 15, what="freeze")
        wait_until(lambda: not is_live(rj), 30, what="group kill")
        wait_until(lambda: not is_live(rw), 30, what="watchdog exit")
        alive = [p for p in before if os.path.exists(f"/proc/{p}")]
        self.log.append({"pids_before_kill": before, "alive_after": alive,
                         "cgroup_exists_after": os.path.exists(cgd)})
        self.assertEqual(alive, [])
        self.assertFalse(os.path.exists(cgd))
        rec = wait_until(lambda: self.record(j), 20, what="job record")
        self.assertEqual(rec["status"], "killed")
        self.assertTrue(rec["group_kills"][0]["reasons"][0].startswith("frozen_for_s"))
        self.assertEqual(rec["measurement_source"], "watchdog_last_sample")

    def test_4_cgroup_oom_kills_whole_group(self):
        j = self.new_id()
        rj, rw = f"rj-{j}.service", f"rw-{j}.service"
        hog = ("import subprocess,sys,time;"
               "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']);"
               "time.sleep(1);b=[]\n"
               "for i in range(64): b.append(bytearray(16*1024*1024)); time.sleep(0.02)\n"
               "time.sleep(30)")
        self.assertEqual(self.start(j, "TOOM", [sys.executable, "-c", hog]).returncode, 0)
        wait_until(lambda: not is_live(rj), 60, what="OOM group kill")
        wait_until(lambda: not is_live(rw), 30, what="watchdog exit")
        rec = wait_until(lambda: self.record(j), 20, what="job record")
        with open(os.path.join(self.job_dir(j), "watchdog_summary.json")) as fh:
            wd = json.load(fh)
        self.log.append({"job_unit_final": wd["job_unit_final"]})
        self.assertEqual(wd["job_unit_final"]["Result"], "oom-kill")
        self.assertIsNone(rec["exit_code"])     # jobwrap itself was killed with the group
        self.assertEqual(rec["status"], "oom-killed")
        self.assertEqual(procs_with_job_env(j), [])

    def test_5_admission_refusals_start_nothing(self):
        cases = []
        # (a) unhealthy collector
        write_health(self.env["health"], state="DEGRADED")
        j = self.new_id()
        r = self.start(j, "TINT", ["/bin/true"])
        cases.append((j, r.returncode, "collector_state=DEGRADED"))
        write_health(self.env["health"], state="HEALTHY")
        # (b) protected window covering every minute
        with open(self.env["config"]) as fh:
            c = json.load(fh)
        c["windows_utc"] = [{"name": "test-window", "hourly": [0, 60]}]
        with open(self.env["config"], "w") as fh:
            json.dump(c, fh)
        j = self.new_id()
        r = self.start(j, "TINT", ["/bin/true"])
        cases.append((j, r.returncode, "protected_window=test-window"))
        c["windows_utc"] = []
        with open(self.env["config"], "w") as fh:
            json.dump(c, fh)
        # (c) lock held by another holder
        import fcntl
        lp = os.path.join(self.env["dir"], "state", "test-heavy.lock")
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        fd = os.open(lp, os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            j = self.new_id()
            r = self.start(j, "TINT", ["/bin/true"])
            cases.append((j, r.returncode, "lock_held=test-heavy"))
        finally:
            os.close(fd)
        for j, rc, reason in cases:
            rec = self.record(j)
            self.assertEqual(rc, 3)
            self.assertEqual(rec["status"], "refused")
            self.assertIn(reason, rec["admission"]["reasons"])
            self.assertEqual(prop(f"rj-{j}.service", "LoadState"), "not-found")
            self.assertEqual(prop(f"rw-{j}.service", "LoadState"), "not-found")
        self.log.append({"refusals": cases})


if __name__ == "__main__":
    unittest.main()
