"""Monitor: optional health-episode coalescing (--coalesce-health-episodes, OFF by default).

(a) flag off: every file the monitor writes is byte-identical to the monitor at the D0 base (1dc9ac5, identical to the
deployed blob) for the same inputs; (b) flag on: one `health_episode` line per collector health:DEGRADED episode with
start / end / duration / streams / causes; (c) everything that is not health:DEGRADED still alerts as before, and a
long episode is never silent."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
MON = ROOT / "ops" / "p2f_cont_monitor.py"
BASE_COMMIT = "1dc9ac5"
CID = "cd" * 32


def load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sys.path.insert(0, str(MON.parent))
    sp.loader.exec_module(m)
    return m


M = load("ep_mon", MON)


def base_monitor(d):
    """The monitor source at the D0 base commit, or None when git history is unavailable."""
    try:
        src = subprocess.run(["git", "show", f"{BASE_COMMIT}:p2_forward/ops/p2f_cont_monitor.py"], cwd=ROOT,
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    p = pathlib.Path(d) / "p2f_cont_monitor_base.py"
    p.write_bytes(src)
    return load("ep_mon_base", p)


def scope(root):
    s = os.path.join(root, f"docker-{CID}.scope")
    os.makedirs(s)
    for f, v in (("cgroup.procs", "1\n"), ("cpu.max", "150000 100000\n"), ("memory.max", "805306368\n"),
                 ("memory.swap.max", "0\n"), ("pids.max", "64\n"), ("memory.current", "1000\n"),
                 ("memory.stat", "anon 1000\n"), ("pids.current", "5\n")):
        with open(os.path.join(s, f), "w") as fh:
            fh.write(v)


H0 = 1_800_000_000_000
STEPS = [("HEALTHY", []), ("DEGRADED", ["stale:ada-t1-depth"]),
         ("DEGRADED", ["stale:ada-t1-depth", "gap_open:ada-t1-depth:stale_stream", "stale:sol-t2-depth"]),
         ("HEALTHY", []), ("DEGRADED", ["conn_not_data_live:conn1-depth", "gap_short:btc-t0-depth:conn_data_stale"]),
         ("DEGRADED_DISK", ["disk_hard_stop"]), ("HEALTHY", [])]


def drive(mod, d, steps=STEPS, step_s=60, **flags):
    """Run `mod`'s Monitor once per step (fixed clock), feeding the given collector health; return {file: bytes}."""
    ds, out, cg = os.path.join(d, "ds"), os.path.join(d, "out"), os.path.join(d, "cg")
    os.makedirs(os.path.join(ds, "health")); scope(cg)
    a = SimpleNamespace(out=out, dataset=ds, cid=CID, once=True, collector_cmdline="python -m p2_forward", **flags)
    clock = {"t": H0 / 1000}
    fake_time = SimpleNamespace(time=lambda: clock["t"], sleep=lambda s: None)
    with mock.patch.object(mod, "CGROOT", cg), mock.patch.object(mod, "time", fake_time), \
            mock.patch.object(mod, "monitors_on", lambda out, exclude=(): []), \
            mock.patch.object(mod.shutil, "disk_usage", lambda p: SimpleNamespace(total=10**12, used=0, free=5 * 10**11)):
        m = mod.Monitor(a)
        m.procs = lambda: (None, [])
        for state, reasons in steps:
            with open(os.path.join(ds, "health", "collector_health.json"), "w") as fh:
                json.dump({"ts_ms": int(clock["t"] * 1000), "state": state, "reasons": reasons, "warnings": []}, fh)
            m.run()
            clock["t"] += step_s
    files = {}
    for r, _, fs in os.walk(out):
        for f in fs:
            files[os.path.relpath(os.path.join(r, f), out)] = open(os.path.join(r, f), "rb").read()
    return files


def alerts(files):
    return [json.loads(x) for x in files["alerts.jsonl"].splitlines()]


class FlagOff(unittest.TestCase):
    def test_byte_identical_to_base_monitor(self):
        with tempfile.TemporaryDirectory() as d:
            old = base_monitor(d)
            if old is None:
                self.skipTest("git history unavailable")
            with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
                a, b = drive(old, d1), drive(M, d2)
                self.assertEqual(sorted(a), sorted(b))
                for k in a:
                    self.assertEqual(a[k], b[k], k)
                with tempfile.TemporaryDirectory() as d3:
                    self.assertEqual(drive(M, d3, coalesce_health_episodes=False), b)
            self.assertIn("health:DEGRADED", {r for x in alerts(b) for r in x["reasons"]})

    def test_option_defaults_off(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(M.Monitor(SimpleNamespace(out=d)).coalesce)


class FlagOn(unittest.TestCase):
    def test_one_line_per_episode_and_other_alerts_unchanged(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            off, on = drive(M, d1), drive(M, d2, coalesce_health_episodes=True, episode_open_alert_s=300)
            for k in off:                                                      # status / samples / procs unchanged
                if k != "alerts.jsonl":
                    self.assertEqual(off[k], on[k], k)
            al = alerts(on)
            self.assertNotIn("health:DEGRADED", {r for x in al for r in x["reasons"]})
            eps = [x for x in al if x["kind"] == "health_episode"]
            self.assertEqual(len(eps), 2)
            e1, e2 = eps
            self.assertEqual((e1["start_ms"], e1["end_ms"], e1["duration_s"], e1["samples"]), (H0 + 60_000, H0 + 180_000, 120.0, 2))
            self.assertEqual(e1["streams"], ["ada-t1-depth", "sol-t2-depth"])
            self.assertEqual(e1["causes"], ["gap_open:stale_stream", "stale"])
            self.assertEqual((e1["end_state"], e1["severity"]), ("HEALTHY", "DEGRADED"))
            self.assertEqual(e2["streams"], ["btc-t0-depth"])
            self.assertEqual(e2["causes"], ["conn_not_data_live:conn1-depth", "gap_short:conn_data_stale"])
            self.assertEqual(e2["end_state"], "DEGRADED_DISK")
            disk = [x for x in al if "health:DEGRADED_DISK" in x["reasons"]]
            self.assertEqual(len(disk), 1)                                     # not coalesced: alerts as before
            self.assertEqual(disk[0]["kind"], "entry")
            self.assertEqual(al[-1]["kind"], "recovery")

    def test_long_episode_alerts_once_while_open(self):
        steps = [("DEGRADED", ["stale:ada-t1-depth"])] * 8 + [("HEALTHY", [])]
        with tempfile.TemporaryDirectory() as d:
            al = alerts(drive(M, d, steps=steps, coalesce_health_episodes=True, episode_open_alert_s=300))
            opens = [x for x in al if x["kind"] == "health_episode_open"]
            self.assertEqual(len(opens), 1)
            self.assertEqual((opens[0]["start_ms"], opens[0]["duration_s"]), (H0, 300.0))
            ends = [x for x in al if x["kind"] == "health_episode"]
            self.assertEqual(len(ends), 1); self.assertEqual(ends[0]["duration_s"], 480.0)

    def test_incidents_and_stale_health_file_still_alert(self):
        with tempfile.TemporaryDirectory() as d:
            ds = os.path.join(d, "ds"); os.makedirs(os.path.join(ds, "incidents"))
            with open(os.path.join(ds, "incidents", "state.json"), "w") as fh:
                json.dump({"incidents": [{"id": "i1", "key": "conn_outage:conn0-book", "severity": "DEGRADED",
                                          "active": True, "ack": None, "count": 1}]}, fh)
            al = alerts(drive(M, d, steps=[("DEGRADED", ["incident:conn_outage:conn0-book"])],
                              coalesce_health_episodes=True))
            self.assertEqual(al[0]["severity"], "DEGRADED")
            self.assertIn("incident:conn_outage:conn0-book", al[0]["reasons"])

    def test_episode_reason_parsing(self):
        P = M.episode_reason
        self.assertEqual(P("gap_short:a-depth:stale_stream"), ("a-depth", "gap_short:stale_stream"))
        self.assertEqual(P("stale:a-book"), ("a-book", "stale"))
        self.assertEqual(P("stream_failed:a-depth:FAILED"), ("a-depth", "stream_failed"))
        self.assertEqual(P("awaiting_post_reconnect:x"), ("x", "awaiting_post_reconnect"))
        self.assertEqual(P("writer_stale"), (None, "writer_stale"))
        self.assertEqual(P("gap_open:nocause"), (None, "gap_open:nocause"))

    def test_cli_rejects_non_positive_open_alert(self):
        r = subprocess.run([sys.executable, str(MON), "--dataset", "/nonexistent", "--cid", CID, "--out",
                            tempfile.mkdtemp(), "--once", "--episode-open-alert-s", "0"], capture_output=True, text=True,
                           timeout=60)
        self.assertNotEqual(r.returncode, 0); self.assertIn("episode-open-alert-s", r.stderr)


if __name__ == "__main__":
    unittest.main()
