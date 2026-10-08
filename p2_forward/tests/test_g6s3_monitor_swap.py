"""G6 step 3: monitor swap isolation - offline tests of the read-only preflight / verify rules. Stdlib only.

Nothing here talks to systemd, Docker or a cgroup: subprocess is replaced by a recorder and every file path points
into a temp dir.
"""
import configparser
import copy
import datetime as dt
import hashlib
import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL = ROOT / "ops" / "g6s3_monitor_swap.py"
UNIT = ROOT / "ops" / "systemd" / "tsb-p2f-monitor.service"
DROPIN = ROOT / "ops" / "systemd" / "tsb-p2f-monitor.service.d" / "50-MemorySwapMax.conf"


def load():
    sp = importlib.util.spec_from_file_location("g6s3", TOOL)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


G = load()
T_OK = dt.datetime(2026, 10, 9, 9, 40, tzinfo=dt.timezone.utc).timestamp()   # outside every protected window
CID = "ce4e" + "0" * 60


def pre_snapshot(t=T_OK):
    unit = {"ActiveState": "active", "SubState": "running", "MainPID": "3551927",
            "InvocationID": "28260c0e369843e1bec159168ddc37dc", "NRestarts": "0",
            "ActiveEnterTimestampMonotonic": "945833056953", "MemoryMax": "268435456", "MemoryHigh": "201326592",
            "MemorySwapMax": "infinity", "CPUWeight": "1000", "TasksMax": "32", "OOMScoreAdjust": "100",
            "DropInPaths": "", "ControlGroup": "/user.slice/x/tsbops.slice/tsb-p2f-monitor.service"}
    return {"t": t, "unit": unit, "unit_file_sha256": G.UNIT_SHA256, "dropin_files": {},
            "cgroup": {"memory.max": "268435456", "memory.high": "201326592", "memory.swap.max": "max",
                       "memory.swap.current": "0",
                       "memory.events": {"low": 0, "high": 0, "max": 0, "oom": 0, "oom_kill": 0, "oom_group_kill": 0}},
            "status": {"readable": True, "severity": "WARNING", "t_ms": int(t * 1000) - 20_000, "age_s": 20.0,
                       "writer": {"supervisor": "systemd-user", "unit": G.UNIT, "pid": 3551927,
                                  "invocation_id": "28260c0e369843e1bec159168ddc37dc"},
                       "next_refresh_ms": 1791504600000},
            "research_units": [],
            "collector": {"bound_cid": CID, "id": CID, "running": True, "health": "healthy",
                          "started_at": "2026-10-08T08:27:10Z", "restart_count": "0"}}


def post_snapshot(pre, dt_s=90):
    s = copy.deepcopy(pre)
    s["t"] = pre["t"] + dt_s
    s["unit"]["MemorySwapMax"] = "0"
    s["unit"]["DropInPaths"] = G.EXPECTED_DROPIN
    s["cgroup"]["memory.swap.max"] = "0"
    s["dropin_files"] = {G.EXPECTED_DROPIN: "# This is a drop-in unit file extension, created via \"systemctl "
                                            "set-property\"\n# or an equivalent operation. Do not edit.\n"
                                            "[Service]\nMemorySwapMax=0\n"}
    s["status"]["t_ms"] = int(s["t"] * 1000) - 10_000
    s["status"]["age_s"] = 10.0
    return s


class ProposedChange(unittest.TestCase):
    def test_reference_dropin_is_exactly_swap0(self):
        self.assertTrue(G.dropin_is_exactly_swap0(DROPIN.read_text()))

    def test_base_unit_is_the_g4_unit_and_has_no_swap_setting(self):
        self.assertEqual(hashlib.sha256(UNIT.read_bytes()).hexdigest(), G.UNIT_SHA256)
        self.assertNotIn("MemorySwapMax", UNIT.read_text())

    def test_effective_config_changes_only_swap(self):
        def cp(*texts):
            c = configparser.ConfigParser(strict=False, interpolation=None)
            c.optionxform = str
            for t in texts:
                c.read_string(t)
            return dict(c["Service"])
        base, merged = cp(UNIT.read_text()), cp(UNIT.read_text(), DROPIN.read_text())
        self.assertEqual(merged.pop("MemorySwapMax"), "0")
        self.assertEqual(base, merged)
        self.assertEqual((base["MemoryHigh"], base["MemoryMax"], base["CPUWeight"], base["Restart"]),
                         ("192M", "256M", "1000", "on-failure"))

    def test_dropin_parser_rejects_extras(self):
        self.assertFalse(G.dropin_is_exactly_swap0("[Service]\nMemorySwapMax=0\nMemoryMax=1G\n"))
        self.assertFalse(G.dropin_is_exactly_swap0("[Service]\nMemorySwapMax=infinity\n"))
        self.assertFalse(G.dropin_is_exactly_swap0("[Unit]\nMemorySwapMax=0\n"))
        self.assertTrue(G.dropin_is_exactly_swap0("# c\n\n[Service]\nMemorySwapMax=0\n"))

    def test_commands_are_live_set_property_and_reversible(self):
        self.assertEqual(G.APPLY_CMD, "systemctl --user set-property tsb-p2f-monitor.service MemorySwapMax=0")
        self.assertNotIn("--runtime", G.APPLY_CMD)            # persistent across user-manager restarts
        self.assertTrue(G.ROLLBACK_CMDS[0].endswith("MemorySwapMax=infinity"))
        self.assertFalse(any("restart" in c or "stop" in c for c in (G.APPLY_CMD, *G.ROLLBACK_CMDS)))


class Windows(unittest.TestCase):
    def at(self, h, m):
        return dt.datetime(2026, 10, 9, h, m, tzinfo=dt.timezone.utc)

    def test_protected_windows(self):
        self.assertEqual(G.window_problems(self.at(9, 40)), [])
        self.assertIn("protected_window hh:12-25", G.window_problems(self.at(9, 12)))
        self.assertIn("protected_window hh:12-25", G.window_problems(self.at(9, 25)))
        self.assertEqual(G.window_problems(self.at(9, 26)), [])
        self.assertIn("protected_window 23:50-00:45", G.window_problems(self.at(23, 55)))
        self.assertIn("protected_window 23:50-00:45", G.window_problems(self.at(0, 30)))
        self.assertIn("protected_window 01:10-01:45", G.window_problems(self.at(1, 30)))

    def test_rotation_guard(self):
        rot = self.at(10, 0).timestamp() * 1000
        self.assertIn("rotation_within_30min", G.window_problems(self.at(9, 40), rot))
        self.assertEqual(G.window_problems(self.at(9, 29), rot), [])


class Preflight(unittest.TestCase):
    def test_clean_state_is_go(self):
        self.assertEqual(G.preflight_problems(pre_snapshot()), [])

    def test_each_precondition_blocks(self):
        cases = [
            (lambda s: s.update(unit_file_sha256="0" * 64), "unit_file_changed"),
            (lambda s: s["unit"].update(DropInPaths="/x.conf"), "unexpected_dropins"),
            (lambda s: s["unit"].update(MemorySwapMax="0"), "MemorySwapMax=0"),
            (lambda s: s["unit"].update(MemoryMax="1"), "property MemoryMax"),
            (lambda s: s["cgroup"].update({"memory.swap.max": "0"}), "cgroup memory.swap.max"),
            (lambda s: s.update(research_units=["rj-x.service"]), "research_units_loaded"),
            (lambda s: s["status"].update(age_s=500.0), "monitor_stale"),
            (lambda s: s["status"].update(severity="CRITICAL"), "monitor_severity"),
            (lambda s: s["status"]["writer"].update(pid=1), "monitor_writer_not_unit_main"),
            (lambda s: s["collector"].update(health="unhealthy"), "collector_not_healthy"),
            (lambda s: s.update(t=dt.datetime(2026, 10, 9, 9, 15, tzinfo=dt.timezone.utc).timestamp()),
             "protected_window"),
        ]
        for mut, needle in cases:
            s = pre_snapshot()
            mut(s)
            probs = G.preflight_problems(s)
            self.assertTrue(any(needle in p for p in probs), (needle, probs))


class Verify(unittest.TestCase):
    def test_expected_post_state_passes(self):
        pre = pre_snapshot()
        self.assertEqual(G.verify_problems(pre, post_snapshot(pre)), [])

    def test_restart_is_detected(self):
        pre = pre_snapshot()
        for k, v in (("MainPID", "4000000"), ("InvocationID", "f" * 32), ("NRestarts", "1"),
                     ("ActiveEnterTimestampMonotonic", "1")):
            post = post_snapshot(pre)
            post["unit"][k] = v
            self.assertTrue(any("identity_changed " + k in p for p in G.verify_problems(pre, post)), k)

    def test_not_applied_or_partially_applied(self):
        pre = pre_snapshot()
        post = post_snapshot(pre)
        post["cgroup"]["memory.swap.max"] = "max"
        self.assertTrue(any("cgroup memory.swap.max" in p for p in G.verify_problems(pre, post)))
        post = post_snapshot(pre)
        post["unit"]["MemorySwapMax"] = "infinity"
        self.assertTrue(any(p.startswith("MemorySwapMax=") for p in G.verify_problems(pre, post)))

    def test_collateral_changes_fail(self):
        pre = pre_snapshot()
        muts = [(lambda s: s["cgroup"].update({"memory.max": "1"}), "cgroup memory.max"),
                (lambda s: s["unit"].update(MemoryHigh="1"), "property MemoryHigh"),
                (lambda s: s["dropin_files"].update({"/home/x/other.conf": "[Service]\nCPUWeight=1\n"}), "dropin_set"),
                (lambda s: s["dropin_files"].update({G.EXPECTED_DROPIN: "[Service]\nMemorySwapMax=0\nTasksMax=1\n"}),
                 "dropin_content"),
                (lambda s: s["cgroup"]["memory.events"].update(oom_kill=1), "memory.events oom_kill"),
                (lambda s: s["cgroup"]["memory.events"].update(max=3), "memory.events max"),
                (lambda s: s["collector"].update(id="ab" * 32), "collector_changed"),
                (lambda s: s["status"].update(t_ms=pre["status"]["t_ms"]), "status_not_rewritten"),
                (lambda s: s["status"].update(age_s=999.0), "monitor_stale")]
        for mut, needle in muts:
            post = post_snapshot(pre)
            mut(post)
            probs = G.verify_problems(pre, post)
            self.assertTrue(any(needle in p for p in probs), (needle, probs))

    def test_rollback_verification(self):
        pre = pre_snapshot()
        rb = copy.deepcopy(pre)
        rb["t"] += 300
        rb["status"]["t_ms"] = int(rb["t"] * 1000) - 5000
        self.assertEqual(G.rollback_problems(pre, rb), [])
        bad = post_snapshot(pre)
        probs = G.rollback_problems(pre, bad)
        self.assertTrue(any("expected infinity" in p for p in probs))
        self.assertTrue(any("dropins_remain" in p for p in probs))


class ReadOnly(unittest.TestCase):
    """snapshot() may only run read-only commands and never writes outside its --out file."""

    def test_snapshot_runs_only_read_only_commands(self):
        calls = []

        def fake_run(args, timeout=15):
            calls.append(list(args))
            out = ""
            if args[:3] == ["systemctl", "--user", "show"]:
                out = "ActiveState=active\nMainPID=1\nControlGroup=/nope\n"
            return mock.Mock(returncode=0, stdout=out, stderr="")
        with tempfile.TemporaryDirectory() as td, mock.patch.object(G, "_run", fake_run), \
                mock.patch.object(G, "UNIT_FILE", os.path.join(td, "u")), \
                mock.patch.object(G, "STATUS", os.path.join(td, "s")), \
                mock.patch.object(G, "BINDING", os.path.join(td, "b")), \
                mock.patch.object(G, "DROPIN_DIRS", (os.path.join(td, "d"),)), \
                mock.patch.object(G, "CGROOT", td):
            s = G.snapshot()
            self.assertEqual(os.listdir(td), [])
        self.assertFalse(s["status"]["readable"])
        allowed = (("systemctl", "--user", "show"), ("systemctl", "--user", "list-units"), ("docker", "inspect"))
        for c in calls:
            self.assertTrue(any(tuple(c[:len(a)]) == a for a in allowed), c)

    def test_evidence_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "pre.json")
            G._write(p, {"a": 1})
            with self.assertRaises(FileExistsError):
                G._write(p, {"a": 2})

    def test_source_has_no_mutating_calls(self):
        src = TOOL.read_text()
        code = src.split('"""', 2)[2]                          # skip the module docstring
        for bad in ('"set-property"', '"restart"', '"stop"', '"daemon-reload"', "os.remove", "shutil",
                    '"rm"', "write_text"):
            self.assertNotIn(bad, code, bad)


if __name__ == "__main__":
    unittest.main()
