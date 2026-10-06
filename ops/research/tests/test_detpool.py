"""Determinism, resume, partial-unit and corruption tests for research_exec.detpool."""
from __future__ import annotations

import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

from _helpers import ROOT, wait_until  # noqa: F401  (sets sys.path)

from research_exec.detpool import (CorruptUnit, PlanMismatch, derive_seed, make_units, run_units,
                                   verify_checkpoint)

sys.path.insert(0, os.path.join(ROOT, "examples"))
import synthetic_cpu  # noqa: E402

SCRIPT = os.path.join(ROOT, "examples", "synthetic_cpu.py")


def units(n=12, iters=4000):
    return make_units([f"u{i:04d}" for i in range(n)], 7, params={"iters": iters})


class TestDeterminism(unittest.TestCase):
    def test_seed_derivation_is_stable(self):
        self.assertEqual(derive_seed(7, "u0001"), derive_seed(7, "u0001"))
        self.assertNotEqual(derive_seed(7, "u0001"), derive_seed(7, "u0002"))
        self.assertNotEqual(derive_seed(7, "u0001"), derive_seed(8, "u0001"))
        # fixed value guards against accidental algorithm changes
        self.assertEqual(derive_seed(0, "a"), 0x1df3c5fab8ef8fe7)

    def test_same_hash_any_worker_count_and_completion_order(self):
        us = units()
        ref = run_units(synthetic_cpu.mc_unit, us, workers=1, fn_id="t")
        os.environ["SYNTH_JITTER_S"] = "0.15"
        try:
            hashes = {ref.result_sha256}
            orders = []
            for w, sh in ((2, None), (4, None), (4, 1), (4, 2), (3, 99)):
                r = run_units(synthetic_cpu.mc_unit, us, workers=w, fn_id="t", _test_shuffle_seed=sh)
                hashes.add(r.result_sha256)
                orders.append(tuple(r.completion_order))
                self.assertEqual(r.merged_bytes, ref.merged_bytes)
        finally:
            os.environ.pop("SYNTH_JITTER_S", None)
        self.assertEqual(len(hashes), 1)
        self.assertGreater(len(set(orders)), 1, "completion order should actually vary")
        self.assertTrue(any(o != tuple(u.key for u in us) for o in orders))

    def test_rejects_bad_keys_and_duplicates(self):
        from research_exec.detpool import Unit
        with self.assertRaises(ValueError):
            run_units(synthetic_cpu.mc_unit, [Unit("a/b", 1, {"iters": 1})], workers=1)
        with self.assertRaises(ValueError):
            run_units(synthetic_cpu.mc_unit, [Unit("a", 1, {"iters": 1}), Unit("a", 2, {"iters": 1})])


class TestCheckpoint(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="detpool-")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_resume_reuses_and_matches(self):
        us = units()
        ck = os.path.join(self.d, "ck")
        a = run_units(synthetic_cpu.mc_unit, us, workers=2, checkpoint_dir=ck, fn_id="t")
        b = run_units(synthetic_cpu.mc_unit, us, workers=4, checkpoint_dir=ck, fn_id="t")
        self.assertEqual((a.computed, b.reused, b.computed), (12, 12, 0))
        self.assertEqual(a.result_sha256, b.result_sha256)
        self.assertTrue(verify_checkpoint(ck)["ok"])

    def test_plan_mismatch_refused(self):
        ck = os.path.join(self.d, "ck")
        run_units(synthetic_cpu.mc_unit, units(4), workers=1, checkpoint_dir=ck, fn_id="t")
        with self.assertRaises(PlanMismatch):
            run_units(synthetic_cpu.mc_unit, units(5), workers=1, checkpoint_dir=ck, fn_id="t")

    def test_tampered_unit_detected_quarantined_recomputed(self):
        us = units(6)
        ck = os.path.join(self.d, "ck")
        ref = run_units(synthetic_cpu.mc_unit, us, workers=2, checkpoint_dir=ck, fn_id="t")
        p = os.path.join(ck, "units", "u0003.json")
        with open(p, "rb") as fh:
            doc = json.loads(fh.read())
        doc["result"]["hits"] += 1                      # silent bit-rot / tampering
        with open(p, "w") as fh:
            fh.write(json.dumps(doc, sort_keys=True, separators=(",", ":")))
        v = verify_checkpoint(ck)
        self.assertFalse(v["ok"])
        self.assertEqual(v["problems"][0]["key"], "u0003")
        with self.assertRaises(CorruptUnit):
            run_units(synthetic_cpu.mc_unit, us, workers=2, checkpoint_dir=ck, fn_id="t", strict=True)
        r = run_units(synthetic_cpu.mc_unit, us, workers=2, checkpoint_dir=ck, fn_id="t")
        self.assertEqual((r.reused, r.computed), (5, 1))
        self.assertEqual([x["reason"] for x in r.rejected], ["sha256_mismatch", "sha256_mismatch"])
        self.assertEqual(r.result_sha256, ref.result_sha256)
        self.assertEqual(len(os.listdir(os.path.join(ck, "quarantine"))), 2)

    def test_kill_mid_run_then_resume(self):
        """SIGKILL a real multi-worker run part-way, plant partial files, resume."""
        ck, out = os.path.join(self.d, "ck"), os.path.join(self.d, "merged.json")
        n, iters = 16, 150000
        ref = run_units(synthetic_cpu.mc_unit,
                        make_units([f"u{i:04d}" for i in range(n)], 20261006, params={"iters": iters}),
                        workers=4, fn_id="synthetic_cpu.mc_unit", meta={"iters": iters})
        p = subprocess.Popen([sys.executable, SCRIPT, "--units", str(n), "--iters", str(iters),
                              "--workers", "2", "--checkpoint", ck], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_until(lambda: len(glob.glob(os.path.join(ck, "units", "*.sha256"))) >= 4, 120,
                       what="4 completed units")
            os.killpg(p.pid, signal.SIGKILL)            # our own session only (start_new_session)
            p.wait(timeout=30)
        finally:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait(timeout=30)
        # no straggler workers of the killed session
        wait_until(lambda: not _session_members(p.pid), 10, what="killed session to be empty")
        done = sorted(glob.glob(os.path.join(ck, "units", "*.sha256")))
        self.assertLess(len(done), n, "run should have been interrupted before completion")
        self.assertFalse(os.path.exists(os.path.join(ck, "manifest.json")))
        # plant a partial temp file and truncate one finished unit (simulated torn write)
        with open(os.path.join(ck, "units", ".u0099.json.tmp-12345"), "wb") as fh:
            fh.write(b'{"key":"u00')
        victim = done[0].replace(".sha256", ".json")
        with open(victim, "r+b") as fh:
            fh.truncate(10)
        r = subprocess.run([sys.executable, SCRIPT, "--units", str(n), "--iters", str(iters),
                            "--workers", "4", "--checkpoint", ck, "--out", out],
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(ck, "manifest.json")) as fh:
            man = json.load(fh)
        reasons = sorted(x["reason"] for x in man["rejected"])
        self.assertIn("partial_temp_file", reasons)
        self.assertIn("sha256_mismatch", reasons)
        self.assertEqual(man["reused"], len(done) - 1)
        self.assertEqual(man["result_sha256"], ref.result_sha256)
        with open(out, "rb") as fh:
            self.assertEqual(fh.read(), ref.merged_bytes)


def _session_members(sid):
    out = []
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                with open(f"/proc/{d}/stat") as fh:
                    f = fh.read().rsplit(")", 1)[1].split()
                if int(f[3]) == sid:
                    out.append(int(d))
            except (OSError, IndexError):
                pass
    return out


if __name__ == "__main__":
    unittest.main()
