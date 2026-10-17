"""G4: supervised monitor - single writer, explicit binding, lifecycle/exit records, unit contract. Stdlib only."""
import configparser
import fcntl
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MON = ROOT / "ops" / "p2f_cont_monitor.py"
UNIT = ROOT / "ops" / "systemd" / "tsb-p2f-monitor.service"
SLICE = ROOT / "ops" / "systemd" / "tsbops.slice"
CID = "ab" * 32


def load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sys.path.insert(0, str(path.parent))
    sp.loader.exec_module(m)
    return m


M = load("g4_mon", MON)
B = load("g4_bind", ROOT / "ops" / "p2f_monitor_bind.py")


def dataset(d):
    ds = os.path.join(d, "ds")
    os.makedirs(os.path.join(ds, "health"))
    with open(os.path.join(ds, "health", "collector_health.json"), "w") as fh:
        json.dump({"state": "HEALTHY", "ts_ms": int(time.time() * 1000)}, fh)
    return ds


def run(*args, env=None, timeout=60):
    return subprocess.run([sys.executable, str(MON), *args], capture_output=True, text=True, timeout=timeout,
                          env=dict(os.environ, **(env or {})))


def binding(d, ds, **over):
    p = os.path.join(d, "binding.json")
    b = {"schema": M.BINDING_SCHEMA, "container_name": "tsb-p2-forward-collector", "cid": CID, "dataset": ds,
         "bound_at": "2026-10-07T00:00:00Z", **over}
    with open(p, "w") as fh:
        json.dump(b, fh)
    return p


class SingleWriter(unittest.TestCase):
    def test_lock_busy_refuses_before_writing_anything(self):
        with tempfile.TemporaryDirectory() as d:
            ds, out = dataset(d), os.path.join(d, "mon")
            os.makedirs(out)
            fd = os.open(os.path.join(out, M.LOCK_NAME), os.O_RDWR | os.O_CREAT)
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                r = run("--dataset", ds, "--cid", CID, "--out", out, "--once")
            finally:
                os.close(fd)
            self.assertEqual(r.returncode, M.EX_DUPLICATE, r.stderr)
            self.assertEqual(sorted(os.listdir(out)), [M.LOCK_NAME])          # nothing else written

    def test_non_lock_honouring_writer_on_same_out_refuses_start(self):
        with tempfile.TemporaryDirectory() as d:
            ds, out = dataset(d), os.path.join(d, "mon")
            os.makedirs(out)
            # a legacy-style monitor: same program name and --out (relative, resolved against ITS cwd), no lock
            fake = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "p2f_cont_monitor.py",
                                     "--out", "mon"], cwd=d)
            try:
                time.sleep(0.3)
                r = run("--dataset", ds, "--cid", CID, "--out", out, "--once")
                self.assertEqual(r.returncode, M.EX_DUPLICATE, r.stderr)
                self.assertIn(str(fake.pid), r.stderr)
                self.assertEqual(sorted(os.listdir(out)), [M.LOCK_NAME])
            finally:
                fake.kill(); fake.wait(10)

    def test_foreign_writer_needs_two_consecutive_scans(self):
        class A:  # minimal args
            out, cid, dataset, collector_cmdline = "/nonexistent-g4", CID, "/nonexistent-ds", "python -m p2_forward"
        with tempfile.TemporaryDirectory() as d:
            A.out = d
            m = M.Monitor(A)
            seq = [[(10, "1")], [(10, "1")], [(11, "5")], []]
            orig = M.monitors_on
            M.monitors_on = lambda out, exclude=(): seq.pop(0)
            try:
                self.assertEqual(m.foreign_writers(), [])              # first sighting: maybe a refusing duplicate
                self.assertEqual(m.foreign_writers(), [(10, "1")])     # still there 60 s later: confirmed
                self.assertEqual(m.foreign_writers(), [])
                self.assertEqual(m.foreign_writers(), [])
            finally:
                M.monitors_on = orig


class Binding(unittest.TestCase):
    def test_invalid_binding_is_a_config_error(self):
        with tempfile.TemporaryDirectory() as d:
            ds, out = dataset(d), os.path.join(d, "mon")
            for over in ({"cid": "81988f5d480d"}, {"schema": "x"}, {"dataset": "/elsewhere"}, {"container_name": ""}):
                r = run("--dataset", ds, "--binding-file", binding(d, ds, **over), "--out", out, "--once")
                self.assertEqual(r.returncode, M.EX_CONFIG, (over, r.stderr))
            self.assertFalse(os.path.exists(os.path.join(out, "status.json")))
            r = run("--dataset", ds, "--binding-file", os.path.join(d, "missing.json"), "--out", out, "--once")
            self.assertEqual(r.returncode, M.EX_CONFIG)
            self.assertEqual(run("--dataset", ds, "--cid", "81988f5d480d", "--out", out, "--once").returncode, M.EX_CONFIG)

    def test_status_carries_writer_identity_and_binding(self):
        with tempfile.TemporaryDirectory() as d:
            ds, out = dataset(d), os.path.join(d, "mon")
            bp = binding(d, ds)
            r = run("--dataset", ds, "--binding-file", bp, "--out", out, "--once", env={"INVOCATION_ID": ""})
            self.assertEqual(r.returncode, 0, r.stderr)
            st = json.load(open(os.path.join(out, "status.json")))
            mon = st["monitor"]
            self.assertEqual((mon["cid"], mon["binding"]["source"], mon["binding"]["container_name"]),
                             (CID, "file", "tsb-p2-forward-collector"))
            self.assertEqual(mon["supervisor"], "none")                       # no systemd invocation id => unsupervised
            self.assertEqual(mon["status_written_ms"], st["t_ms"])
            self.assertFalse(mon["binding_check"]["scope_alive"])
            self.assertEqual(st["severity"], "STOPPED")
            sample = json.loads(open(os.path.join(out, sorted(x for x in os.listdir(out) if x[:2] == "20")[0],
                                                  "samples.jsonl")).readline())
            self.assertNotIn("monitor", sample)                               # samples.jsonl format unchanged

    def test_stale_or_wrong_binding_is_critical_never_silent(self):
        class A:
            out, cid, dataset, collector_cmdline = None, CID, "/x", "python -m p2_forward"
        with tempfile.TemporaryDirectory() as d:
            A.out = d
            m = M.Monitor(A)
            base = {"alive": True, "health_age_s": 1, "incidents_active": [], "health_state": "HEALTHY",
                    "mem_pct_of_limit": 10, "oom_kill": 0, "throttled_frac_60s": 0, "disk_free_gb": 500}
            sev, why = m.evaluate(dict(base, _binding={"scope_alive": True, "collector_pid": 5, "dataset_mount_ok": False}), [])
            self.assertEqual((sev, why), ("CRITICAL", ["binding_dataset_mismatch"]))
            sev, why = m.evaluate(dict(base, alive=False, _binding={"scope_alive": False, "other_collectors": ["0123456789ab"]}), [])
            self.assertEqual(sev, "STOPPED")
            self.assertIn("binding_stale:collector_now=0123456789ab", why)
            self.assertIn("collector_not_running", why)
            sev, why = m.evaluate(dict(base, _binding={"scope_alive": True, "collector_pid": 5, "dataset_mount_ok": True}), [])
            self.assertEqual(sev, "INFO")

    def test_bind_tool_refuses_wrong_container(self):
        with tempfile.TemporaryDirectory() as d:
            ds = dataset(d)
            c = {"cid": CID, "running": True, "compose_project": "tsb-p2-forward", "compose_service": "collector",
                 "mounts": [(ds, "/data", True)]}
            self.assertEqual(B.validate(c, ds), ["no_collector_process_in_scope"])     # no such scope on this host
            self.assertIn("not_running", B.validate(dict(c, running=False), ds))
            self.assertIn("compose_labels=other/collector", B.validate(dict(c, compose_project="other"), ds))
            self.assertIn("dataset_not_mounted_rw_at_/data", B.validate(dict(c, mounts=[(ds, "/data", False)]), ds))
            self.assertEqual(B.validate(None, ds), ["container_not_found"])


class Lifecycle(unittest.TestCase):
    def test_start_record_measures_gap_from_previous_status(self):
        with tempfile.TemporaryDirectory() as d:
            ds, out = dataset(d), os.path.join(d, "mon")
            os.makedirs(out)
            prev_t = int(time.time() * 1000) - 42_000
            with open(os.path.join(out, "status.json"), "w") as fh:
                json.dump({"t_ms": prev_t, "severity": "WARNING", "monitor": {"pid": 4242}}, fh)
            p = subprocess.Popen([sys.executable, str(MON), "--dataset", ds, "--cid", CID, "--out", out],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.time() + 30
                while time.time() < deadline and (json.load(open(os.path.join(out, "status.json"))).get("t_ms") == prev_t):
                    time.sleep(0.2)
            finally:
                p.kill(); p.wait(10)
            rec = json.loads(open(os.path.join(out, M.LIFECYCLE)).readline())
            self.assertEqual((rec["event"], rec["prev_status_t_ms"], rec["prev_writer_pid"]), ("start", prev_t, 4242))
            self.assertGreaterEqual(rec["status_gap_s"], 42.0)

    def test_record_exit_failure_is_a_critical_alert_success_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "mon")
            r = run("--record-exit", "--out", out, env={"SERVICE_RESULT": "signal", "EXIT_CODE": "killed",
                                                         "EXIT_STATUS": "KILL", "INVOCATION_ID": "x1"})
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run("--record-exit", "--out", out, env={"SERVICE_RESULT": "success", "EXIT_CODE": "killed",
                                                         "EXIT_STATUS": "TERM", "INVOCATION_ID": "x2"})
            life = [json.loads(x) for x in open(os.path.join(out, M.LIFECYCLE))]
            self.assertEqual([(x["event"], x["service_result"]) for x in life], [("exit", "signal"), ("exit", "success")])
            alerts = [json.loads(x) for x in open(os.path.join(out, "alerts.jsonl"))]
            self.assertEqual(len(alerts), 1)
            self.assertEqual((alerts[0]["severity"], alerts[0]["kind"]), ("CRITICAL", "monitor_exit"))
            self.assertEqual(alerts[0]["reasons"], ["monitor_exit:result=signal,code=killed,status=KILL"])


class UnitContract(unittest.TestCase):
    def cfg(self, p):
        c = configparser.ConfigParser(strict=False, interpolation=None)
        c.optionxform = str
        c.read(p)
        return c

    def test_service_contract(self):
        c = self.cfg(UNIT)
        s, u = c["Service"], c["Unit"]
        self.assertEqual(s["Type"], "notify")
        self.assertEqual(s["Restart"], "on-failure")
        self.assertTrue({"75", "78"} <= set(s["RestartPreventExitStatus"].split()))
        self.assertEqual((s["KillMode"], s["SendSIGKILL"]), ("control-group", "yes"))
        self.assertEqual((s["MemoryMax"], s["CPUWeight"], s["Slice"]), ("256M", "1000", "tsbops.slice"))
        self.assertGreaterEqual(int(s["OOMScoreAdjust"]), 100)          # unprivileged floor of the user manager
        self.assertLess(int(s["OOMScoreAdjust"]), 500)                  # always a later victim than research (500)
        self.assertIn("--binding-file", s["ExecStart"])
        self.assertNotIn("--cid", s["ExecStart"])
        self.assertIn("--record-exit", s["ExecStopPost"])
        out = s["ExecStart"].split("--out ")[1].split()[0]
        self.assertIn(f"--out {out}", s["ExecStopPost"])                 # hook records into the same dir
        self.assertTrue(int(u["StartLimitBurst"]) >= 3 and int(s["WatchdogSec"]) >= 60)
        self.assertEqual(c["Install"]["WantedBy"], "default.target")
        self.assertEqual(self.cfg(SLICE)["Slice"]["CPUWeight"], "1000")


if __name__ == "__main__":
    unittest.main()
