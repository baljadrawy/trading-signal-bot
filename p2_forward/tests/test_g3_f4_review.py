"""G3-F4 bounded-review fixes (process certifier): fail-closed drain, EOF exit, counter mirroring across restarts,
restart manifest completion, run-record provenance, verifier provenance check, config validation."""
import json
import os
import queue
import shutil
import signal
import tempfile
import time
import unittest

from p2_forward import config as C, writer as Wm
from p2_forward.certproc import ProcessCertifier
from tests.test_g3_f3 import one_segment, manifest, BOOT
from tests.test_regression_g2r import healthy_collector, stop_writer
from tests.test_g3_prereqs import run_g3_e2e, g3_test_spec, VI


def wait(pred, s=20.0):
    end = time.monotonic() + s
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def conflict_segment(d, hour="20261003T01"):
    """A finalized segment whose certified name is already taken -> certify() quarantines it (conflict)."""
    seg = one_segment(d, hour=hour); p = seg.finalize()
    with open(p[: -len(Wm.PENDING)], "w") as fh:
        fh.write("occupied")
    return p


class ReviewFixes(unittest.TestCase):
    def test_drain_fails_closed_after_abnormal_worker_exit(self):
        with tempfile.TemporaryDirectory() as d:
            c = ProcessCertifier(d, BOOT, Wm.new_stats(), lambda: None); c.start(); self.assertTrue(c.wait_ready(10))
            os.kill(c.ident, signal.SIGKILL); c.join(5)
            self.assertFalse(c.drain(1.0))                       # nothing pending, but the exit was not clean
            c = ProcessCertifier(d, BOOT, Wm.new_stats(), lambda: None); c.start(); self.assertTrue(c.wait_ready(10))
            self.assertTrue(c.drain(5.0)); self.assertEqual(c.proc.exitcode, 0)

    def test_worker_exits_on_wake_pipe_eof(self):
        with tempfile.TemporaryDirectory() as d:
            c = ProcessCertifier(d, BOOT, Wm.new_stats(), lambda: None); c.start(); self.assertTrue(c.wait_ready(10))
            c._wake_w.close()                                    # every write end closed = the parent is gone
            c.join(5); self.assertFalse(c.is_alive())

    def test_quarantine_mirrored_to_collector_and_health(self):
        with tempfile.TemporaryDirectory() as d:
            col = healthy_collector(d, certifier_mode="process")
            try:
                cert = col.writer.certifier; self.assertTrue(cert.wait_ready(10))
                conflict_segment(d); cert.submit("x")
                self.assertTrue(wait(lambda: not cert.pending() and cert._quar.value == 1))
                st, hard, _, _ = col.health_eval()
                self.assertEqual(col.stats["segments_quarantined"], 1)
                self.assertIn("segments_quarantined", hard); self.assertNotEqual(st, "HEALTHY")
            finally:
                stop_writer(col)

    def test_counters_survive_worker_restart(self):
        with tempfile.TemporaryDirectory() as d:
            stats = Wm.new_stats()
            w = Wm.SegmentWriter(d, BOOT, queue.Queue(), stats, certifier_mode="process")
            w.certifier.start(); self.assertTrue(w.certifier.wait_ready(10))
            conflict_segment(d, "20261003T01"); w.certifier.submit("x")
            self.assertTrue(wait(lambda: not w.certifier.pending() and w.certifier._quar.value == 1))   # published
            os.kill(w.certifier.ident, signal.SIGKILL); w.certifier.join(5)
            w.restart_certifier()                                # syncs the dead worker's counters first
            self.assertEqual(stats["segments_quarantined"], 1)
            self.assertTrue(w.certifier.wait_ready(10))
            # the new worker's startup manifest completion finds the conflict's occupant (certified name, no sidecar,
            # no manifest entry) and quarantines it: fail closed, counted (mirroring is eventual: bounded wait)
            self.assertTrue(wait(lambda: (w.certifier.status(), stats["segments_quarantined"])[1] == 2))
            conflict_segment(d, "20261003T02"); w.certifier.submit("x")
            self.assertTrue(wait(lambda: (w.certifier.status(), stats["segments_quarantined"])[1] == 3))
            self.assertEqual(stats["segments_quarantined"], 3)   # accumulated, never overwritten by a new worker
            self.assertTrue(w.certifier.drain(10))

    def test_restarted_worker_completes_missing_manifest_entry(self):
        with tempfile.TemporaryDirectory() as d:
            p = one_segment(d).finalize()
            Wm.certify(d, p, Wm.new_stats(), BOOT, "runs/run-x.json")
            for f in os.listdir(os.path.join(d, "manifests")):  # died after promotion, before the manifest append
                os.remove(os.path.join(d, "manifests", f))
            c = ProcessCertifier(d, BOOT, Wm.new_stats(), lambda: "runs/run-x.json"); c.start()
            self.assertTrue(c.wait_ready(20))                     # completed BEFORE readiness
            m = manifest(d)
            self.assertEqual(len(m), 1); self.assertTrue(m[0]["recovered"]); self.assertEqual(m[0]["run_record"], "runs/run-x.json")
            self.assertTrue(c.drain(5))

    def test_run_record_reaches_segments_found_by_the_periodic_scan(self):
        with tempfile.TemporaryDirectory() as d:
            ref = {"rr": None}
            c = ProcessCertifier(d, BOOT, Wm.new_stats(), lambda: ref["rr"]); c.start(); self.assertTrue(c.wait_ready(10))
            ref["rr"] = "runs/run-y.json"; c.set_run_record()    # what the collector does when the record exists
            one_segment(d).finalize()                            # no submit(): only the worker's own 1 s scan
            self.assertTrue(wait(lambda: len(manifest(d)) == 1))
            self.assertEqual(manifest(d)[0]["run_record"], "runs/run-y.json")
            self.assertTrue(c.drain(5))

    def test_config_validates_ready_timeout(self):
        for bad in (0, -1, 121, "10"):
            with self.assertRaises(C.ConfigError):
                C.validate({**C.DEFAULTS, "certifier_ready_timeout_s": bad})


class VerifierProvenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = os.path.join(cls.tmp.name, "data"); os.makedirs(cls.base)
        run_g3_e2e(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_e2e_manifest_run_records_consistent(self):
        r = VI.verify(self.base, spec=g3_test_spec())
        self.assertNotIn("MANIFEST_RUN_RECORD_MISMATCH", r["failures"])

    def test_manifest_without_run_record_detected(self):
        d = tempfile.mkdtemp(dir=self.tmp.name); dst = os.path.join(d, "data"); shutil.copytree(self.base, dst)
        mdir = os.path.join(dst, "manifests")
        for f in os.listdir(mdir):
            p = os.path.join(mdir, f); os.chmod(p, 0o644)
            ls = [json.loads(x) for x in open(p)]
            for e in ls:
                if e["type"] == "book":
                    e["run_record"] = None
            with open(p, "w") as fh:
                fh.write("".join(json.dumps(e, sort_keys=True) + "\n" for e in ls))
        self.assertIn("MANIFEST_RUN_RECORD_MISMATCH", VI.verify(dst, spec=g3_test_spec())["failures"])


if __name__ == "__main__":
    unittest.main()
