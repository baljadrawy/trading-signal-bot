"""G3-F1 (per-tier depth / book freshness) and G3-F2 (verifier CLI JSON export) regression tests."""
import datetime as dt
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from p2_forward import app as A, config as C, universe as U
from tests.test_regression_g2r import mk, book, depth, mini, gaps, drain, healthy_collector, stop_writer
from p2_forward import writer as W
from tests.test_g3_prereqs import run_g3_e2e, g3_test_spec, VI, segs_of, recertify

UNI = {**U.tier0_only(C.DEFAULTS), "tier1": ["ADAUSDT"], "tier2": ["SOLUSDT"]}
T1D, T2D, T0D = "adausdt@depth10", "soldusdt@depth10".replace("sold", "sol"), "btcusdt@depth20"


def tamper_first_matching(base, typ, pick, mutate):
    """Apply `mutate` to the first record (segment order) for which `pick` is true, searching ALL `typ` segments.

    Segments are cut at the writer's wall-clock UTC hour (writer.py `_write`), so a run that crosses an hour boundary
    can leave the wanted record outside the first segment. Fails loudly when nothing matched, so a tamper test can
    never pass or fail vacuously. Returns the recertified segment."""
    for seg in segs_of(base, typ):
        if not any(pick(json.loads(line)) for line in gzip.open(seg, "rt")):
            continue
        changed = []

        def transform(ls):
            for x in ls:
                if pick(x):
                    mutate(x); changed.append(x)
                    break
            return ls
        recertify(base, seg, transform)
        assert len(changed) == 1, "exactly one record must be mutated"
        return seg
    raise AssertionError(f"no {typ} record matched the tamper predicate: the test would be vacuous")


def make_stale_tier2(x):
    """Tier-2 depth value 15.001 s old (Tier-2 pinned threshold: 15 s)."""
    x["recv_ts_ns"] = (x["sample_ms"] - 15_001) * 1_000_000
    x["observed_at_ms"] = x["available_at_ms"] = x["sample_ms"] - 15_001


def is_tier2(x):
    return x.get("tier") == 2


def mkt(d, **over):
    return mk(d, universe=dict(UNI), **over)


def live(c, start, end, step=1000):
    """Keep BOTH connections data-live (other streams on them) without touching the stream under test."""
    for t in range(start, end + 1, step):
        mini(c, t - 5)                                                 # conn0 (book connection)
        depth(c, t // step, t - 5, sym="btcusdt", n=20)                 # conn1 carries Tier-0 depth


class TierFreshness(unittest.TestCase):
    def test_tier0_strict_2s_kept(self):
        with tempfile.TemporaryDirectory() as d:
            c = mkt(d); S = (A.now_ms() // 1000) * 1000 - 50_000
            self.assertEqual(c.tracks[T0D].stale_ms, 2000)
            depth(c, 1, S - 2001, sym="ethusdt", n=20); mini(c, S - 5); depth(c, 1, S - 5)
            c.sample(S)
            g = c.tracks["ethusdt@depth20"].gap
            self.assertEqual(g["cause"], "stale_stream")

    def test_tier1_quiet_depth_within_threshold_keeps_original_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            c = mkt(d); S = (A.now_ms() // 60_000) * 60_000 - 300_000
            self.assertEqual(c.tracks[T1D].stale_ms, 180_000)
            depth(c, 7, S - 100_000, sym="adausdt", n=10)                # quiet book: 100 s without a push
            live(c, S - 9_000, S)
            c.sample(S)
            r = [x for x in drain(c) if x["type"] == "depth" and x["symbol"] == "ADAUSDT"][0]
            self.assertEqual(r["observed_at_ms"], S - 100_000)          # original receive time preserved
            self.assertLessEqual(r["recv_ts_ns"], S * 1_000_000)
            self.assertIsNone(c.tracks[T1D].gap)
            self.assertEqual(c.freshness(c.tracks[T1D], S), "aging")

    def test_tier2_quiet_depth_within_threshold(self):
        with tempfile.TemporaryDirectory() as d:
            c = mkt(d); S = (A.now_ms() // 5000) * 5000 - 60_000
            self.assertEqual(c.tracks[T2D].stale_ms, 15_000)
            depth(c, 3, S - 12_000, sym="solusdt", n=10); live(c, S - 9_000, S)
            c.sample(S)
            self.assertTrue([x for x in drain(c) if x["type"] == "depth" and x["symbol"] == "SOLUSDT"])

    def test_tier1_exceeds_threshold_gap_and_degraded(self):
        with tempfile.TemporaryDirectory() as d:
            c = mkt(d); S = (A.now_ms() // 60_000) * 60_000 - 600_000
            depth(c, 7, S - 180_001, sym="adausdt", n=10); live(c, S - 9_000, S)
            c.sample(S)
            self.assertEqual(c.tracks[T1D].gap["cause"], "stale_stream")

    def test_tier2_exceeds_threshold_gap(self):
        with tempfile.TemporaryDirectory() as d:
            c = mkt(d); S = (A.now_ms() // 5000) * 5000 - 60_000
            depth(c, 3, S - 15_001, sym="solusdt", n=10); live(c, S - 9_000, S)
            c.sample(S)
            self.assertEqual(c.tracks[T2D].gap["cause"], "stale_stream")

    def test_dead_stream_not_hidden_behind_live_shared_connection(self):
        with tempfile.TemporaryDirectory() as d:
            c = mkt(d); S = (A.now_ms() // 5000) * 5000 - 120_000
            depth(c, 3, S - 1000, sym="solusdt", n=10)
            for k in range(0, 40):                                       # conn1 busy (Tier-0 depth), SOL depth dead
                live(c, S + k * 1000, S + k * 1000)
                c.sample(S + k * 1000)
            g = c.tracks[T2D].gap
            self.assertIsNotNone(g); self.assertEqual(g["cause"], "stale_stream")
            self.assertEqual(g["first"], S + 15_000)                   # first 5 s boundary with age > 15 s
            self.assertEqual(c.freshness(c.tracks[T2D], S + 39_000), "stale")

    def test_tier12_book_dead_bound(self):
        with tempfile.TemporaryDirectory() as d:
            c = mkt(d); S = (A.now_ms() // 10_000) * 10_000 - 1_000_000
            self.assertEqual(c.tracks["adausdt@bookTicker"].stale_ms, 600_000)
            book(c, 1, S - 600_001, sym="adausdt"); live(c, S - 9_000, S)
            c.sample(S)
            self.assertEqual(c.tracks["adausdt@bookTicker"].gap["cause"], "stale_stream")

    def test_no_future_observation_used(self):
        with tempfile.TemporaryDirectory() as d:
            c = mkt(d); S = (A.now_ms() // 60_000) * 60_000 - 300_000
            depth(c, 7, S - 50_000, sym="adausdt", n=10); depth(c, 8, S + 1, sym="adausdt", n=10); live(c, S - 9_000, S)
            c.sample(S)
            r = [x for x in drain(c) if x["type"] == "depth" and x["symbol"] == "ADAUSDT"][0]
            self.assertEqual(r["exchange_seq"], 7)

    def test_reconnect_resets_freshness(self):
        with tempfile.TemporaryDirectory() as d:
            c = mkt(d); S = (A.now_ms() // 60_000) * 60_000 - 300_000
            a = c.activity["conn1-depth"]
            a.transitions.append((S - 200_000, True))
            depth(c, 7, S - 30_000, sym="adausdt", n=10)                 # within 180 s ...
            a.transitions.append((S - 20_000, False)); a.transitions.append((S - 10_000, True))
            live(c, S - 9_000, S)                                        # ... but from BEFORE the reconnect
            c.sample(S)
            self.assertEqual(c.tracks[T1D].gap["cause"], "awaiting_post_reconnect_data")
            self.assertEqual(c.freshness(c.tracks[T1D], S), "reconnecting")
            depth(c, 8, S + 30_000, sym="adausdt", n=10); live(c, S + 51_000, S + 60_000); c.sample_until(S + 60_000)
            self.assertIsNone(c.tracks[T1D].gap)                          # recovered
            self.assertEqual(c.freshness(c.tracks[T1D], S + 60_000), "fresh")

    def test_healthy_prohibited_beyond_threshold(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                self.assertEqual(c.health_eval()[0], "HEALTHY")
                c.tracks["ethusdt@depth20"].values.latest = ((A.now_ms() - 2500) * 1_000_000, {}, 999)   # 2.5 s > 2 s
                st, hard, _, _ = c.health_eval()
                self.assertEqual(st, "DEGRADED"); self.assertIn("stale:ethusdt@depth20", hard)
            finally:
                stop_writer(c)

    def test_freshness_vocabulary_disconnected(self):
        with tempfile.TemporaryDirectory() as d:
            c = mkt(d); m = A.now_ms()
            depth(c, 1, m - 100, sym="adausdt", n=10)
            c.conns[1].connected = False
            self.assertEqual(c.freshness(c.tracks[T1D], m), "disconnected")
            self.assertEqual(c.freshness(c.tracks[T2D], m), "not_ready")


class VerifierFreshnessAndCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = os.path.join(cls.tmp.name, "data"); os.makedirs(cls.base)
        run_g3_e2e(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_verifier_applies_pinned_tier_thresholds(self):
        s = g3_test_spec(); s["depth_stale_ms_by_tier"] = {"t0": 2000, "t1": 60000, "t2": 5000}
        self.assertIn("ACC_FRESHNESS_THRESHOLDS_NOT_SPEC", VI.verify(self.base, spec=s)["failures"])
        d = tempfile.mkdtemp(dir=self.tmp.name); dst = os.path.join(d, "data"); shutil.copytree(self.base, dst)
        tamper_first_matching(dst, "depth", is_tier2, make_stale_tier2)   # any segment: hour-boundary safe
        self.assertIn("STALE_VALUE_PERSISTED", VI.verify(dst)["failures"])

    def test_tamper_helper_refuses_vacuous_tamper(self):
        d = tempfile.mkdtemp(dir=self.tmp.name); dst = os.path.join(d, "data"); shutil.copytree(self.base, dst)
        with self.assertRaises(AssertionError):
            tamper_first_matching(dst, "depth", lambda x: x.get("tier") == 99, make_stale_tier2)

    def test_str_keys_direct(self):
        self.assertEqual(json.loads(json.dumps(VI.str_keys({None: 1, 2: {None: 3}, "a": [{None: 4}]}), sort_keys=True)),
                         {"null": 1, "2": {"null": 3}, "a": [{"null": 4}]})

    def test_spec_without_freshness_fails_closed_for_per_tier_run(self):
        s = g3_test_spec(); del s["depth_stale_ms_by_tier"]; del s["book_t12_dead_ms"]
        self.assertIn("ACC_SPEC_MISSING_FRESHNESS", VI.verify(self.base, spec=s)["failures"])

    def test_cli_json_export_with_none_key(self):
        out = os.path.join(self.tmp.name, "rep.json")
        spec = os.path.join(self.tmp.name, "spec.json")
        json.dump(g3_test_spec(), open(spec, "w"))
        cli = os.path.join(os.path.dirname(VI.__file__), "verify_independent.py")
        p = subprocess.run([sys.executable, cli, self.base, "--spec", spec, "--json", out], capture_output=True, text=True)
        self.assertNotIn("Traceback", p.stderr)
        rep = json.load(open(out))
        direct = VI.str_keys(VI.verify(self.base, spec=g3_test_spec()))
        self.assertIn("selected", rep["universe"]["exclusions"])          # formerly the None key
        for k in ("PASS", "acceptance", "failures", "totals", "coverage", "universe", "gaps", "window"):
            self.assertEqual(json.loads(json.dumps(rep[k], sort_keys=True)), json.loads(json.dumps(direct[k], sort_keys=True, default=str)), k)
        self.assertEqual(p.returncode, 0 if rep["PASS"] else 1)


if __name__ == "__main__":
    unittest.main()


class HourBoundarySegmentation(unittest.TestCase):
    """Regression for the 2026-10-20 main CI failure (run 39504743271, 85d1c4a): the e2e run crossed a UTC hour, the
    first depth segment held no Tier-2 record, the old test tampered nothing and VI.verify returned no failures.

    Deterministic: the writer's hour clock (writer._utc) reports the previous hour until the first Tier-2 depth record
    is about to be written, so the boundary always falls between the first depth record and the first Tier-2 one."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = os.path.join(cls.tmp.name, "data"); os.makedirs(cls.base)
        flipped = {"v": False}
        real_utc, real_write = W._utc, W.SegmentWriter._write

        def utc(ns):
            t = real_utc(ns)
            return t if flipped["v"] else t - dt.timedelta(hours=1)

        def write(self, rec):
            if rec.get("type") == "depth" and rec.get("tier") == 2:
                flipped["v"] = True                                    # the hour turns before the first Tier-2 write
            return real_write(self, rec)
        with mock.patch.object(W, "_utc", utc), mock.patch.object(W.SegmentWriter, "_write", write):
            run_g3_e2e(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_boundary_puts_no_tier2_record_in_first_depth_segment(self):
        segs = segs_of(self.base, "depth")
        self.assertGreaterEqual(len(segs), 2)
        first = [json.loads(line) for line in gzip.open(segs[0], "rt")]
        self.assertTrue(first)                                         # earlier depth records exist (Tier 0/1)
        self.assertFalse([x for x in first if is_tier2(x)])            # ... but no Tier-2 one

    def test_old_first_segment_tamper_was_vacuous(self):
        """Reproduces the CI failure mode: tampering only segs[0] changes nothing and STALE is not reported."""
        d = tempfile.mkdtemp(dir=self.tmp.name); dst = os.path.join(d, "data"); shutil.copytree(self.base, dst)
        seg0 = segs_of(dst, "depth")[0]
        before = gzip.open(seg0, "rb").read()
        changed = []

        def old(ls):                                                   # the pre-fix transform, verbatim logic
            for x in ls:
                if x["tier"] == 2:
                    make_stale_tier2(x); changed.append(x)
                    break
            return ls
        recertify(dst, seg0, old)
        self.assertEqual(changed, [])                                  # nothing was tampered ...
        self.assertEqual(gzip.open(seg0, "rb").read(), before)
        self.assertNotIn("STALE_VALUE_PERSISTED", VI.verify(dst)["failures"])   # ... so the old assertion failed

    def test_tamper_across_segments_is_detected(self):
        d = tempfile.mkdtemp(dir=self.tmp.name); dst = os.path.join(d, "data"); shutil.copytree(self.base, dst)
        seg = tamper_first_matching(dst, "depth", is_tier2, make_stale_tier2)
        self.assertNotEqual(seg, segs_of(dst, "depth")[0])             # the Tier-2 record lives after the boundary
        self.assertIn("STALE_VALUE_PERSISTED", VI.verify(dst)["failures"])
