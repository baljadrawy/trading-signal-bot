"""P2-CR packages A (explicit continuous mode), E (dataset identity / startup refusal), F (fail-closed controls),
G (incident state), H (GC observability beyond 1,000 events). Offline; production calendar unless stated."""
import asyncio
import contextlib
import io
import json
import os
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from p2_forward import app as A, cal, config as C, incidents as I, procwatch as PW, writer as W
from tests.test_g3_prereqs import FakeExchange
from tests.test_p2cr_continuous import cont_cfg, run_continuous
from tests.test_verify_independent import ENV, FakeResp

ROOT = pathlib.Path(__file__).resolve().parents[1]


def prod_cont_cfg(d, **over):
    return cont_cfg(d, ws_rotation_s=82800, day_close_after_s=600, universe_refresh_at_s=600, **over)


def collector(d, **over):
    cfg = prod_cont_cfg(d, **over); C.validate(cfg)
    return A.Collector(cfg)


class ExplicitContinuousMode(unittest.TestCase):                      # Package A
    def ok(self, **kw):
        C.validate({**C.DEFAULTS, **kw})

    def bad(self, **kw):
        with self.assertRaises(C.ConfigError):
            C.validate({**C.DEFAULTS, **kw})

    def test_bounded_unchanged(self):
        self.ok(enabled=True, max_runtime_s=21600)
        self.ok(enabled=True, mode="bounded", max_runtime_s=28800)
        self.bad(enabled=True, max_runtime_s=0)                          # omitted / zero timeout is NOT continuous
        self.bad(enabled=True, max_runtime_s=28801)
        self.bad(enabled=True, mode="bounded", max_runtime_s=0)

    def test_continuous_accepted_only_when_explicit_and_complete(self):
        self.ok(enabled=True, mode="continuous", max_runtime_s=0, dataset_id="p2-forward-main", certifier_mode="process")
        self.bad(enabled=True, mode="continuous", max_runtime_s=3600, dataset_id="p2-forward-main")   # no hidden limit
        self.bad(enabled=True, mode="continuous", max_runtime_s=0)                                   # no dataset id
        self.bad(enabled=True, mode="continuous", max_runtime_s=0, dataset_id="Bad Id")
        self.bad(enabled=True, mode="continuous", max_runtime_s=0, dataset_id="ds-1", reconnect_test_at_s=10)
        self.bad(enabled=True, mode="continuous", max_runtime_s=0, dataset_id="ds-1", rotation_test_at_s=10)
        self.bad(enabled=True, mode="continuous", max_runtime_s=0, dataset_id="ds-1", certifier_mode="thread")
        self.bad(enabled=True, mode="continuous", max_runtime_s=0, dataset_id="ds-1", ws_rotation_s=86400)
        self.bad(enabled=True, mode="continuous", max_runtime_s=0, dataset_id="ds-1", fc_writer_stall_s=5)

    def test_malformed_never_becomes_continuous(self):
        for m in ("Continuous", "CONTINUOUS", "", None, True, "continuous "):
            self.bad(enabled=True, mode=m, max_runtime_s=0, dataset_id="ds-1")
        self.bad(enabled=True, max_runtime_s="21600")
        self.bad(enabled=True, max_runtime_s=True)
        self.bad(enabled="true", max_runtime_s=21600)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            json.dump({"enabled": True, "continuous": True, "max_runtime_s": 0}, open(p, "w"))
            with self.assertRaises(C.ConfigError):
                C.load(p)                                                 # unknown key, never an implied mode
            json.dump({"enabled": True, "max_runtime_s": 0}, open(p, "w"))
            with self.assertRaises(C.ConfigError):
                C.load(p)

    def test_continuous_run_has_no_runtime_limit_and_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            base = os.path.join(d, "data")
            c, code, _ = run_continuous(base, 12, ws_rotation_s=82800, day_close_after_s=600, universe_refresh_at_s=600)
            self.assertEqual((code, c.state, c.stop_reason), (0, "STOPPED", "signal"))
            self.assertEqual(c.cfg["max_runtime_s"], 0)
            self.assertFalse([f for _, _, fs in os.walk(os.path.join(base, "raw")) for f in fs
                              if f.endswith((".partial", ".pending", ".certifying"))])
            marker = json.load(open(os.path.join(base, "control", f"stop-{c.boot_id[:8]}.json")))
            self.assertEqual((marker["state"], marker["mode"]), ("STOPPED", "continuous"))
            self.assertIsNotNone(marker["ws_start_ms"]); self.assertIsNotNone(marker["stop_requested_ms"])


class DatasetIdentity(unittest.TestCase):                             # Package E
    def test_fresh_dir_becomes_dataset_and_mismatch_is_refused_without_writes(self):
        with tempfile.TemporaryDirectory() as d:
            collector(d)
            ds = json.load(open(os.path.join(d, "dataset.json")))
            self.assertEqual((ds["dataset_id"], ds["calendar"]), ("test-ds", cal.params()))
            before = sorted(os.listdir(d))
            with self.assertRaises(A.StartupRefused):
                collector(d, dataset_id="other-ds")
            self.assertEqual(sorted(os.listdir(d)), before)

    def test_nonempty_dir_without_identity_is_never_adopted(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "raw", "book", "2026-10-03")); open(os.path.join(d, "raw", "book", "2026-10-03", "x"), "w").close()
            with self.assertRaises(A.StartupRefused):
                collector(d)
            self.assertFalse(os.path.exists(os.path.join(d, "dataset.json")))

    def test_changed_closed_day_refuses_start(self):
        with tempfile.TemporaryDirectory() as d:
            collector(d)
            dd = os.path.join(d, "raw", "book", "2026-10-01"); os.makedirs(dd)
            os.makedirs(os.path.join(d, "days"))
            json.dump({"files": [], "bytes_total": 0}, open(os.path.join(d, "days", "2026-10-01.json"), "w"))
            open(os.path.join(dd, "book-20261001T05Z-aaaaaaaa-0001.jsonl.gz.partial"), "w").close()   # late write
            with self.assertRaises(A.StartupRefused) as cm:
                collector(d)
            self.assertIn("closed_day", str(cm.exception))

    def test_main_returns_startup_code_on_refusal(self):
        with tempfile.TemporaryDirectory() as d:
            collector(d)
            p = os.path.join(d, "c.json")
            json.dump({k: v for k, v in prod_cont_cfg(d, dataset_id="other-ds").items() if k in C.DEFAULTS}, open(p, "w"))
            with mock.patch.dict(os.environ, {"P2F_CONFIG": p}), contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(A.main(), A.EXIT_STARTUP)
            self.assertIn("startup_refused", err.getvalue())

    def test_crash_gap_never_starts_at_epoch(self):
        with tempfile.TemporaryDirectory() as d:
            dd = os.path.join(d, "raw", "book", "2026-10-04"); os.makedirs(dd)
            p = os.path.join(dd, "book-20261004T10Z-aaaaaaaa-0001.jsonl.gz.partial")
            open(p, "wb").write(b"\x1f\x8b garbage")                       # nothing salvageable
            gaps = W.recover_partials(d, "b" * 32, W.new_stats())
            self.assertEqual(gaps[0]["last_salvaged_recv_ns"], None)
            self.assertEqual(gaps[0]["segment_start_ms"], cal.hour_key_start_ms("20261004T10"))
            self.assertGreater(gaps[0]["segment_start_ms"], 1_700_000_000_000)


class FailClosed(unittest.TestCase):                                   # Package F
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = self.tmp.name
        self.c = collector(self.d)

    def tearDown(self):
        self.tmp.cleanup()

    def check(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.c._continuous_checks(A.now_ms())

    def stopped(self, reason):
        self.assertEqual(self.c.stop_reason, f"failclosed:{reason}")
        self.assertEqual(self.c.exit_code, A.EXIT_FAILCLOSED)
        self.assertTrue(any(i["key"] == f"failclosed:{reason}" and i["severity"] == "CRITICAL"
                            for i in self.c.incidents.active()))

    def test_first_quarantine_is_incident_second_is_stop(self):
        self.c.stats["segments_quarantined"] = 1; self.check()
        self.assertIsNone(self.c.stop_reason)
        self.assertTrue(any(i["key"] == "quarantine" for i in self.c.incidents.active()))
        self.c.stats["segments_quarantined"] = 2; self.check()
        self.stopped("quarantine_limit")

    def test_certification_failures(self):
        self.c.stats["certification_failures"] = 2; self.check()
        self.stopped("certification_limit")

    def test_429_first_warning_then_stop(self):
        self.c.rate.events["http_429"] = 1; self.check()
        self.assertIsNone(self.c.stop_reason)
        self.assertTrue(any(i["key"] == "http_429" and i["severity"] == "WARNING" for i in self.c.incidents.active()))
        self.c.rate.events["http_429"] = 2; self.check()
        self.stopped("http_429_limit")

    def test_418_stops_without_resume(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.c.rate.on_418("60")
        self.stopped("http_418")

    def test_clock_critical_persistent(self):
        self.c.clock.state = "CRITICAL"; self.check()
        self.assertIsNone(self.c.stop_reason)
        self.c.clock_critical_since = A.now_ms() - 3_600_001; self.check()
        self.stopped("clock_critical_persistent")

    def test_writer_stall_and_not_durable(self):
        self.c.writer.beat_ns = time.time_ns() - 61_000_000_000; self.check()
        self.stopped("writer_stalled")
        c2 = collector(self.d)
        c2.writer.beat_ns = time.time_ns(); c2.writer.pending_since_ns = time.time_ns() - 61_000_000_000
        with contextlib.redirect_stderr(io.StringIO()):
            c2._continuous_checks(A.now_ms())
        self.assertEqual(c2.stop_reason, "failclosed:writer_not_durable")

    def test_transient_warnings_do_not_stop(self):
        self.c.stats["handler_errors"] = 3; self.c.stats["wall_clock_steps"] = 1; self.check()
        self.assertIsNone(self.c.stop_reason)

    def test_disk_hard_stop_and_dataset_cap_stop_the_collector(self):
        for over in ({"disk_warn_free_gb": 1e9, "disk_stop_free_gb": 9e8}, {"dir_stop_gb": 1e-9}):
            with tempfile.TemporaryDirectory() as d:
                c, code, _ = run_continuous(os.path.join(d, "data"), 30, ws_rotation_s=82800, day_close_after_s=600,
                                            universe_refresh_at_s=600, **over)
                self.assertEqual((code, c.stop_reason), (A.EXIT_FAILCLOSED, "failclosed:disk_hard_stop"))

    def test_day_close_mismatch_is_detected(self):
        dd = os.path.join(self.d, "raw", "book", "2026-10-01"); os.makedirs(dd)
        seg = os.path.join(dd, "book-20261001T05Z-aaaaaaaa-0001.jsonl.gz")
        for p in (seg, seg + ".sha256", seg[:-9] + ".idx"):
            open(p, "w").write("x"); os.chmod(p, 0o444)
        res, problems = W.close_day(self.d, "2026-10-01", set())
        self.assertEqual(res, "mismatch")
        self.assertTrue(any(p.startswith("certified_not_in_manifest") for p in problems))
        self.assertFalse(os.path.exists(os.path.join(self.d, "days", "2026-10-01.json")))

    def test_certify_refuses_a_closed_day(self):
        os.makedirs(os.path.join(self.d, "days"))
        json.dump({"files": []}, open(os.path.join(self.d, "days", "2026-10-01.json"), "w"))
        dd = os.path.join(self.d, "raw", "book", "2026-10-01"); os.makedirs(dd)
        p = os.path.join(dd, "book-20261001T05Z-aaaaaaaa-0001.jsonl.gz.pending"); open(p, "w").close()
        st = W.new_stats()
        self.assertFalse(W.certify(self.d, p, st, "b" * 32))
        self.assertEqual(st["segments_quarantined"], 1)


class ProcessRoles(unittest.TestCase):                                 # Package F (process-role violation)
    def test_pinned_healthcheck_matches_dockerfile_and_verifier(self):
        df = (ROOT / "Dockerfile").read_text()
        self.assertIn("CMD " + PW.HC_CMD, df)
        import importlib.util
        sp = importlib.util.spec_from_file_location("vi_pw", ROOT / "verifier" / "verify_independent.py")
        vi = importlib.util.module_from_spec(sp); sp.loader.exec_module(vi)
        roles = vi.G3_SPEC["cgroup"]["process_roles"]
        self.assertEqual(PW.SHELL_CMDLINE, roles["container_healthcheck"]["shell_cmdline"])
        self.assertEqual(PW.PROBE_CMDLINE, roles["container_healthcheck"]["probe_cmdline"])
        self.assertEqual(PW.CERTIFIER_PREFIX, roles["certifier"]["cmdline_prefix"])
        self.assertEqual(PW.TRACKER_PREFIX, roles["tracker"]["cmdline_prefix"])

    def test_classification(self):
        self.assertEqual(PW.classify(1, "python -m p2_forward", 0, 1, "python -m p2_forward"), "collector")
        self.assertEqual(PW.classify(7, PW.CERTIFIER_PREFIX + "tracker_fd=5, pipe_handle=7)", 1, 1, "x"), "certifier")
        self.assertIsNone(PW.classify(7, PW.CERTIFIER_PREFIX + "x", 3, 1, "x"))          # not a child of the collector
        self.assertEqual(PW.classify(9, PW.SHELL_CMDLINE, 0, 1, "x"), "healthcheck_shell")
        self.assertEqual(PW.classify(10, PW.PROBE_CMDLINE, 9, 1, "x"), "healthcheck_probe")
        self.assertIsNone(PW.classify(11, "sh -c cat /data/health/collector_health.json", 0, 1, "x"))
        self.assertIsNone(PW.classify(12, "sleep 100", 0, 1, "x"))

    def test_unknown_process_persisting_is_a_violation(self):
        w = PW.ProcWatch(persist=2)
        w.enabled = True                                                 # host /proc: many unknown processes
        v1, t1 = w.check(); v2, t2 = w.check()
        self.assertFalse(v1); self.assertTrue(t1); self.assertTrue(v2)

    def test_violation_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            c = collector(d)
            c.procwatch.check = lambda: ([{"pid": 99, "cmd": "sleep 100", "count": 2}], [])

            async def go():
                return await asyncio.wait_for(c.procwatch_task(), 5)
            with contextlib.redirect_stderr(io.StringIO()):
                asyncio.run(go())
            self.assertEqual(c.stop_reason, "failclosed:process_role_violation")


class Incidents(unittest.TestCase):                                    # Package G
    def test_later_independent_incident_never_masked(self):
        with tempfile.TemporaryDirectory() as d:
            log = I.IncidentLog(d, "a" * 32)
            a = log.raise_("quarantine", "DEGRADED", {"seg": "s1"})
            self.assertEqual(log.raise_("quarantine", "DEGRADED", {"seg": "s2"})["id"], a["id"])   # same, counted
            self.assertEqual(a["count"], 2)
            json.dump({"by": "operator", "ref": "ticket-1"}, open(os.path.join(d, "incidents", "ack", a["id"] + ".json"), "w"))
            self.assertEqual(log.poll_acks(), 1)
            self.assertFalse(log.active())
            b = log.raise_("quarantine", "DEGRADED", {"seg": "s3"})                                  # new, own id
            self.assertNotEqual(a["id"], b["id"])
            self.assertEqual([i["id"] for i in log.active()], [b["id"]])
            c = log.raise_("disk_warning", "WARNING", {}, latched=False)
            log.resolve("disk_warning"); log.resolve("quarantine")                # latched: only an ack clears it
            self.assertEqual([i["id"] for i in log.active()], [b["id"]])
            log.flush()
            log2 = I.IncidentLog(d, "b" * 32)                                     # persistent across restarts
            self.assertEqual([i["id"] for i in log2.active()], [b["id"]])
            self.assertEqual({i["id"] for i in log2.items.values()}, {a["id"], b["id"], c["id"]})
            ev = [json.loads(l)["event"] for l in open(os.path.join(d, "incidents", "events.jsonl"))]
            self.assertEqual(ev.count("open"), 3); self.assertIn("ack", ev); self.assertIn("resolve", ev)

    def test_external_incident_raised_once(self):
        with tempfile.TemporaryDirectory() as d:
            log = I.IncidentLog(d, "a" * 32)
            json.dump({"job": "seal", "day": "2026-10-04", "result": "FAIL"}, open(os.path.join(d, "incidents", "external", "seal-1.json"), "w"))
            log.poll_external(); log.poll_external()
            self.assertEqual([(i["key"], i["severity"]) for i in log.active()], [("external:seal-1.json", "CRITICAL")])

    def test_health_reports_each_active_incident_and_recovers_after_ack(self):
        with tempfile.TemporaryDirectory() as d:
            c = collector(d)
            c.state, c.ws_start_ms = "RUNNING", A.now_ms()
            inc = c.incidents.raise_("quarantine", "DEGRADED", {"seg": "s1"})
            c.incidents.raise_("rotation_overlap_failed:conn0-book", "WARNING", {})
            _, hard, _, warn = c.health_eval()
            self.assertIn("incident:quarantine", hard)
            self.assertIn("incident:rotation_overlap_failed:conn0-book", warn)
            json.dump({"by": "op", "ref": "r"}, open(os.path.join(d, "incidents", "ack", inc["id"] + ".json"), "w"))
            c.incidents.poll_acks()
            _, hard, _, _ = c.health_eval()
            self.assertNotIn("incident:quarantine", hard)


class GcObservability(unittest.TestCase):                              # Package H
    def test_events_beyond_1000_are_reported_with_bounded_memory(self):
        with tempfile.TemporaryDirectory() as d:
            c = collector(d)
            for i in range(1500):
                c._gc_t0[2] = (time.perf_counter() - 0.15, time.time_ns())
                c._gc_cb("stop", {"generation": 2, "collected": 1})
                if i % 10 == 9:
                    c._drain_gc_events()
            c._drain_gc_events()
            self.assertEqual((c.gc_long, c._gc_reported, c.gc_events_dropped), (1500, 1500, 0))
            self.assertLessEqual(c.gc_pending.maxlen, 256)
            ins = c.instrumentation()
            self.assertEqual((ins["gc_pause_events_reported"], ins["gc_pause_events_dropped"]), (1500, 0))

    def test_overflow_between_drains_is_counted_not_silent(self):
        with tempfile.TemporaryDirectory() as d:
            c = collector(d)
            for _ in range(300):
                c._gc_t0[0] = (time.perf_counter() - 0.15, time.time_ns()); c._gc_cb("stop", {"generation": 0})
            c._drain_gc_events()
            self.assertEqual((c.gc_long, c._gc_reported, c.gc_events_dropped), (300, 256, 44))


if __name__ == "__main__":
    unittest.main()


class MonitorObserveOnly(unittest.TestCase):                          # owner D5
    SRC = (ROOT / "ops" / "p2f_cont_monitor.py").read_text()

    def test_no_lifecycle_signal_or_deletion_capability(self):
        code = self.SRC.split('"""', 2)[2]                                   # skip the module docstring
        for tok in ('"docker"', "docker stop", "docker kill", "docker start", "docker exec", "docker rm", "os.kill",
                    "import signal", "unlink(", "rmtree", "os.remove", "shutil.move"):
            self.assertFalse(tok in code, tok)

    def test_once_reads_dataset_and_writes_only_its_own_dir(self):
        import subprocess, sys
        with tempfile.TemporaryDirectory() as d:
            ds, out = os.path.join(d, "ds"), os.path.join(d, "mon")
            collector(ds)
            before = sorted((p, os.path.getmtime(os.path.join(r, p))) for r, _, fs in os.walk(ds) for p in fs)
            r = subprocess.run([sys.executable, str(ROOT / "ops" / "p2f_cont_monitor.py"), "--dataset", ds, "--cid", "0" * 64,
                                "--out", out, "--once"], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            st = json.load(open(os.path.join(out, "status.json")))
            self.assertEqual(st["severity"], "STOPPED")                       # no container => visible, not silent
            after = sorted((p, os.path.getmtime(os.path.join(r_, p))) for r_, _, fs in os.walk(ds) for p in fs)
            self.assertEqual(before, after)
            bad = subprocess.run([sys.executable, str(ROOT / "ops" / "p2f_cont_monitor.py"), "--dataset", ds, "--cid", "x",
                                  "--out", os.path.join(ds, "mon"), "--once"], capture_output=True, text=True, timeout=60)
            self.assertNotEqual(bad.returncode, 0)
