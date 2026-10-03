"""G3-F3: asynchronous segment certification (writer hot path never certifies). Scratch dirs only."""
import contextlib
import glob
import gzip
import io
import json
import os
import queue
import tempfile
import threading
import time
import unittest
from unittest import mock

from p2_forward import writer as Wm, record as R, app as A
from tests.test_regression_g2r import mk, healthy_collector, stop_writer, lifes
from tests.test_verify_independent import VI

BOOT = "c" * 32


def rec(i, typ="lifecycle"):
    return R.make(type=typ, obs_id=f"life|{BOOT}|{i}|x", symbol=None, payload={"i": i}, boot_id=BOOT,
                  endpoint="collector", transport="internal", recv_ts_ns=time.time_ns())


def manifest(d):
    return [json.loads(l) for f in glob.glob(os.path.join(d, "manifests", "*.jsonl")) for l in open(f)]


def one_segment(d, n=50, typ="lifecycle", hour="20261003T01"):
    seg = Wm._Segment(d, typ, hour, BOOT[:8], 1)
    for i in range(n):
        seg.write(rec(i, typ))
    seg.sync()
    return seg


class HourOffset:
    """Shift the writer's wall-clock hour key on demand (forces an hourly rotation inside a test)."""
    def __init__(self): self.h = 0
    def __call__(self, ns): return Wm.dt.datetime.fromtimestamp(ns / 1e9 + 3600 * self.h, Wm.dt.timezone.utc)


class AsyncCertification(unittest.TestCase):
    def test_rotation_with_16s_certification_does_not_block_writer(self):
        with tempfile.TemporaryDirectory() as d:
            st = Wm.new_stats(); q = queue.Queue(); hk = HourOffset()
            w = Wm.SegmentWriter(d, BOOT, q, st, flush_interval_s=0.2, certify_grace_s=60)
            slept = threading.Event()
            def slow(cert):
                if not slept.is_set():
                    slept.set(); time.sleep(16)
            w.certifier.slow_test_hook = slow
            with mock.patch.object(Wm, "_utc", hk):
                w.start()
                for i in range(20):
                    q.put(rec(i)); time.sleep(0.02)
                hk.h = 1                                               # hour changes -> rotation -> handoff
                t0 = time.time(); i = 20; pend_seen = 0; durable_seen = 0
                while time.time() - t0 < 6:                            # keep writing while certification sleeps
                    q.put(rec(i)); i += 1; time.sleep(0.05)
                    pend_seen = max(pend_seen, w.certifier.status()["pending"])
                    idx = glob.glob(os.path.join(d, "raw", "lifecycle", "*", "*-0002.idx.partial"))
                    if idx:
                        durable_seen = max(durable_seen, sum(json.loads(l)["records"] for l in open(idx[0])))
                self.assertTrue(slept.is_set())                       # certifier is inside its 16 s sleep
                self.assertLess(w.status()["beat_age_ms"], 1000)
                self.assertLess(w.max_beat_gap_ms, 5000)              # hot path invariant held
                self.assertLess(w.max_durable_lag_ms, 10_000)
                self.assertGreaterEqual(pend_seen, 1)                 # backlog visible
                self.assertGreater(durable_seen, 50)                  # new-hour records durably written meanwhile
                w.stop(); w.join(90)
            self.assertTrue(w.certified_all, {"alive": w.is_alive(), "fatal": w.fatal, "life": {k: len(v) for k, v in Wm.scan_lifecycle(d).items()},
                                              "fail": st["certification_failures"], "err": st.get("last_certify_error"),
                                              "q": os.listdir(os.path.join(d, "quarantine"))})
            m = manifest(d)
            self.assertEqual(sum(e["records"] for e in m), i)        # nothing lost across the rotation
            ids = []
            for f in sorted(glob.glob(os.path.join(d, "raw", "lifecycle", "*", "*.jsonl.gz"))):
                blks = [json.loads(l)["blk"] for l in gzip.open(f, "rt")]
                self.assertEqual(blks, sorted(blks))                  # ordering within each segment
                ids += [json.loads(l)["payload"]["i"] for l in gzip.open(f, "rt")]
            self.assertEqual(ids, list(range(i)))                     # ordering across the rotation
            self.assertTrue(VI.verify(d)["failures"].keys() <= {"LIFECYCLE_START_COUNT", "LIFECYCLE_WS_START_COUNT",
                                                                 "LIFECYCLE_STOP_COUNT"})

    def test_certifier_crash_detected_and_restarted(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                def boom(cert): raise RuntimeError("certifier crashed")
                c.writer.certifier.slow_test_hook = boom
                one_segment(d).finalize(); c.writer.certifier.submit("x")
                with mock.patch.object(threading, "excepthook", lambda a: None):
                    c.writer.certifier.join(5)
                self.assertFalse(c.writer.certifier.is_alive())
                self.assertIn("certifier_dead", c.health_eval()[1])
                got = []
                orig = c.enq.put
                c.enq.put = lambda r, p: got.append(r) or orig(r, p)
                c.watchdog_once()
                self.assertTrue(lifes(got, "certifier_dead")); self.assertTrue(c.writer.certifier.is_alive())
                c.writer.certifier.slow_test_hook = None
                st, hard, _, _ = c.health_eval()
                self.assertEqual(st, "DEGRADED"); self.assertIn("certifier_restarted_10min", hard)
            finally:
                stop_writer(c)

    def test_certification_exception_and_failure_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            st = Wm.new_stats()
            p = one_segment(d).finalize()
            os.chmod(p, 0o644); b = bytearray(open(p, "rb").read()); b[len(b) // 2] ^= 0xFF; open(p, "wb").write(bytes(b))
            self.assertFalse(Wm.certify(d, p, st, BOOT))
            self.assertEqual(st["certification_failures"], 1)
            self.assertTrue(os.listdir(os.path.join(d, "quarantine")))
            self.assertEqual(glob.glob(os.path.join(d, "raw", "*", "*", "*.jsonl.gz")), [])   # never certified
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                c.stats["certification_failures"] = 1
                self.assertIn("certification_failed", c.health_eval()[1])
            finally:
                stop_writer(c)

    def test_backlog_degrades(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d, certify_max_pending=0)
            try:
                c.writer.certifier.slow_test_hook = lambda cert: time.sleep(3)
                one_segment(d).finalize(); c.writer.certifier.submit("x"); time.sleep(0.3)
                self.assertIn("certifier_backlog", c.health_eval()[1])
            finally:
                c.writer.certifier.slow_test_hook = None
                stop_writer(c)


class CrashRecovery(unittest.TestCase):
    def _final_files(self, d):
        return glob.glob(os.path.join(d, "raw", "*", "*", "*.jsonl.gz"))

    def test_restart_discovers_pending(self):
        with tempfile.TemporaryDirectory() as d:
            one_segment(d).finalize()
            st = Wm.new_stats(); Wm.recover_partials(d, BOOT, st)
            f = self._final_files(d)
            self.assertEqual(len(f), 1); self.assertFalse(os.stat(f[0]).st_mode & 0o222)    # certified, read-only
            self.assertEqual(st["recovered_pending_certified"], 1); self.assertEqual(len(manifest(d)), 1)

    def test_crash_before_handoff_finalized_partial(self):
        with tempfile.TemporaryDirectory() as d:
            seg = one_segment(d)
            seg.gz.close(); seg.fh.flush(); seg.fh.close(); seg.idx.close()          # closed, rename never happened
            st = Wm.new_stats(); gaps = Wm.recover_partials(d, BOOT, st)
            self.assertEqual(gaps, []); self.assertEqual(st["recovered_finalized"], 1)
            self.assertEqual(manifest(d)[0]["records"], 50)

    def test_crash_during_certification(self):
        with tempfile.TemporaryDirectory() as d:
            p = one_segment(d).finalize(); os.rename(p, p[: -len(".pending")] + ".certifying")
            st = Wm.new_stats(); Wm.recover_partials(d, BOOT, st)
            self.assertEqual(len(self._final_files(d)), 1); self.assertEqual(len(manifest(d)), 1)

    def test_crash_after_checksum_before_manifest_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            p = one_segment(d).finalize(); st = Wm.new_stats()
            self.assertTrue(Wm.certify(d, p, st, BOOT))
            for f in glob.glob(os.path.join(d, "manifests", "*.jsonl")):
                os.remove(f)                                                         # manifest append "lost"
            Wm.recover_partials(d, BOOT, st); Wm.recover_partials(d, BOOT, st)       # twice: idempotent
            self.assertEqual(len(manifest(d)), 1); self.assertEqual(st["recovered_manifest_completed"], 1)
            self.assertEqual(manifest(d)[0]["sha256"], Wm.sha256_file(self._final_files(d)[0]))

    def test_conflicting_second_copy_never_certified(self):
        with tempfile.TemporaryDirectory() as d:
            p = one_segment(d).finalize(); st = Wm.new_stats(); Wm.certify(d, p, st, BOOT)
            open(p, "wb").write(b"x")                                                # same name pending again
            self.assertFalse(Wm.certify(d, p, st, BOOT))
            self.assertEqual(len(manifest(d)), 1)

    def test_verifier_rejects_uncertified_segments(self):
        with tempfile.TemporaryDirectory() as d:
            one_segment(d).finalize()
            r = VI.verify(d)
            self.assertIn("UNCERTIFIED_SEGMENT_PRESENT", r["failures"]); self.assertEqual(r.get("segments", 0), 0)


class Shutdown(unittest.TestCase):
    def test_shutdown_waits_for_certification(self):
        with tempfile.TemporaryDirectory() as d:
            st = Wm.new_stats(); q = queue.Queue()
            w = Wm.SegmentWriter(d, BOOT, q, st, flush_interval_s=0.1, certify_grace_s=30)
            w.certifier.slow_test_hook = lambda cert: time.sleep(2)
            w.start(); [q.put(rec(i)) for i in range(10)]; time.sleep(0.3); w.stop(); w.join(60)
            self.assertTrue(w.certified_all); self.assertEqual(len(manifest(d)), 1)

    def test_shutdown_timeout_preserves_pending_and_reports_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d, flush_interval_s=0.1, certify_shutdown_grace_s=1)
            c.writer.certify_grace_s = 1
            c.writer.certifier.slow_test_hook = lambda cert: time.sleep(4)
            c.writer.start(); c.q.put(rec(1)); time.sleep(0.3); c.writer.stop(); c.writer.join(30)
            self.assertFalse(c.writer.certified_all)
            left = Wm.scan_lifecycle(d)
            self.assertTrue(left["pending"] or left["certifying"])                 # preserved, recoverable
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(c.finalize_stop(), "STOPPED_INCOMPLETE")
            time.sleep(4.5)
            st = Wm.new_stats(); Wm.recover_partials(d, BOOT, st)                   # next start certifies it
            self.assertEqual(len(manifest(d)), 1)


if __name__ == "__main__":
    unittest.main()


class ReviewFindings(unittest.TestCase):
    def test_F1_drain_waits_for_manifest_append(self):
        with tempfile.TemporaryDirectory() as d:
            orig = Wm._manifest_append
            def slow(*a, **k):
                time.sleep(1.0); return orig(*a, **k)
            with mock.patch.object(Wm, "_manifest_append", slow):
                st = Wm.new_stats(); q = queue.Queue(); w = Wm.SegmentWriter(d, BOOT, q, st, 0.1, certify_grace_s=30)
                w.start(); q.put(rec(1)); time.sleep(0.3); w.stop(); w.join(60)
            self.assertTrue(w.certified_all); self.assertFalse(w.certifier.is_alive()); self.assertEqual(len(manifest(d)), 1)

    def test_F2_crash_between_idx_and_data_rename(self):
        with tempfile.TemporaryDirectory() as d:
            p = one_segment(d).finalize(); stem = p[: -len(".jsonl.gz.pending")]
            os.rename(p, stem + ".jsonl.gz.certifying"); os.rename(stem + ".idx.pending", stem + ".idx")   # new order crash
            st = Wm.new_stats(); Wm.recover_partials(d, BOOT, st)
            self.assertEqual(len(manifest(d)), 1); self.assertEqual(st["certification_failures"], 0)
        with tempfile.TemporaryDirectory() as d:                                                     # old order crash
            p = one_segment(d).finalize(); st = Wm.new_stats(); stem = p[: -len(".jsonl.gz.pending")]
            Wm.certify(d, p, st, BOOT)
            os.chmod(stem + ".idx", 0o644); os.rename(stem + ".idx", stem + ".idx.pending")
            for f in glob.glob(os.path.join(d, "manifests", "*")): os.remove(f)
            Wm.recover_partials(d, BOOT, st)
            self.assertEqual(len(manifest(d)), 1); self.assertTrue(os.path.exists(stem + ".idx"))

    def test_F3_torn_manifest_repaired(self):
        with tempfile.TemporaryDirectory() as d:
            p = one_segment(d).finalize(); st = Wm.new_stats(); Wm.certify(d, p, st, BOOT)
            mf = glob.glob(os.path.join(d, "manifests", "*.jsonl"))[0]
            open(mf, "a").write('{"segment": "raw/x/torn')
            Wm.recover_partials(d, BOOT, st)
            self.assertEqual(st["manifest_repairs"], 1); self.assertEqual(len(manifest(d)), 1)

    def test_F4_idx_renamed_data_still_partial_and_orphan_sweep(self):
        with tempfile.TemporaryDirectory() as d:
            seg = one_segment(d); seg.gz.close(); seg.fh.close(); seg.idx.close()
            stem = seg.final[:-9]; os.rename(stem + ".idx.partial", stem + ".idx.pending")
            st = Wm.new_stats(); gaps = Wm.recover_partials(d, BOOT, st)
            self.assertEqual(gaps, []); self.assertEqual(manifest(d)[0]["records"], 50)
            lone = os.path.join(os.path.dirname(stem), "lifecycle-20261003T02Z-xxxxxxxx-0009.idx.pending")
            open(lone, "w").write("{}\n"); Wm.recover_partials(d, BOOT, st)
            self.assertFalse(os.path.exists(lone)); self.assertEqual(st["orphan_sidecars"], 1)

    def test_F5_conflict_quarantines_idx_too(self):
        with tempfile.TemporaryDirectory() as d:
            p = one_segment(d).finalize(); st = Wm.new_stats(); Wm.certify(d, p, st, BOOT)
            open(p, "wb").write(b"x"); stem = p[: -len(".jsonl.gz.pending")]; open(stem + ".idx.pending", "w").write("{}\n")
            Wm.certify(d, p, st, BOOT)
            self.assertFalse(os.path.exists(stem + ".idx.pending"))

    def test_F6_failure_during_drain_is_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d, flush_interval_s=0.1); c.writer.start(); c.writer.stop(); c.writer.join(30)
            c._stop_snapshot = (0, 0); c.stats["segments_quarantined"] = 1
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(c.finalize_stop(), "STOPPED_INCOMPLETE")

    def test_F7_backlog_limit_covers_all_types(self):
        from p2_forward import config as C
        self.assertGreaterEqual(C.DEFAULTS["certify_max_pending"], 2 * len(R.TYPES))
        self.assertEqual(VI.G3_SPEC["certifier"]["max_pending"], C.DEFAULTS["certify_max_pending"])

    def test_F8_durable_lag_counts_queue_time(self):
        with tempfile.TemporaryDirectory() as d:
            st = Wm.new_stats(); q = queue.Queue(); w = Wm.SegmentWriter(d, BOOT, q, st, 0.1)
            r = rec(1); r["queued_ts_ns"] = time.time_ns() - 3_000_000_000
            w.start(); q.put(r); time.sleep(0.4); w.stop(); w.join(30)
            self.assertGreaterEqual(w.max_durable_lag_ms, 3000)

    def test_F9_verifier_orphan_and_mandatory_cert_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            p = one_segment(d).finalize(); st = Wm.new_stats(); Wm.certify(d, p, st, BOOT)
            open(os.path.join(os.path.dirname(p), "lifecycle-20261003T05Z-zzzzzzzz-0001.idx"), "w").write("{}\n")
            mf = glob.glob(os.path.join(d, "manifests", "*.jsonl"))[0]
            e = json.loads(open(mf).read()); e.pop("certifier"); open(mf, "w").write(json.dumps(e) + "\n")
            r = VI.verify(d, spec=VI.G3_SPEC)
            self.assertIn("ORPHAN_SIDECAR", r["failures"]); self.assertIn("CERTIFICATION_METADATA_INVALID", r["failures"])

    def test_F10_recovery_validates_before_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            p = one_segment(d).finalize(); st = Wm.new_stats(); Wm.certify(d, p, st, BOOT)
            final = p[: -len(".pending")]
            os.chmod(final, 0o644); open(final, "wb").write(gzip.compress(b'{"not": "a record"}\n'))
            os.chmod(final + ".sha256", 0o644); open(final + ".sha256", "w").write(Wm.sha256_file(final) + "  x\n")
            for f in glob.glob(os.path.join(d, "manifests", "*")): os.remove(f)
            Wm.recover_partials(d, BOOT, st)
            self.assertEqual(manifest(d), []); self.assertFalse(os.path.exists(final))

    def test_F12_scan_error_visible(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                with mock.patch.object(Wm, "scan_lifecycle", side_effect=PermissionError("raw")):
                    self.assertIn("certifier_scan_error", c.health_eval()[1])
            finally:
                stop_writer(c)
