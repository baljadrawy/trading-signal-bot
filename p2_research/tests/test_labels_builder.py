import gzip
import json
import math
import os
import random
import unittest
from unittest import mock

from p2_research import builder as BD, features as FE, labels as LB, reader as RD
from p2_research.tests import common as C
from p2_research.tests.test_features import T_at
from p2_research.tests.test_reader import _segs, _write
from p2_research.tests.synth import refresh_hashes

H = 3_600_000


def _rows(path, name):
    with gzip.open(os.path.join(path, name), "rt") as fh:
        return [json.loads(x) for x in fh]


class Labels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = RD.load_days(C.base_dataset(), [C.D1, C.D2])

    def test_anchor_strictly_after_decision(self):
        for T in (T_at(C.D2_MS, 3), C.D2_MS + 900_000, C.D2_MS + 899_999):
            self.assertGreater(LB.anchor(T), T)
            self.assertEqual(LB.anchor(T) % 900_000, 0)

    def test_hand_computed_market_labels(self):
        T = T_at(C.D1_MS, 22, 0)
        L, R = LB.compute_labels(self.B, "BTCUSDT", T)
        st = self.B.candles[("BTCUSDT", "15m")]
        A = LB.anchor(T)
        bars = [st[A + i * 900_000] for i in range(4)]
        p0 = bars[0][1]
        self.assertAlmostEqual(L["mkt.fwd_ret_1h"], math.log(bars[-1][4] / p0), places=10)
        self.assertAlmostEqual(L["mkt.mfe_1h"], max(b[2] for b in bars) / p0 - 1, places=10)
        self.assertAlmostEqual(L["mkt.mae_1h"], min(b[3] for b in bars) / p0 - 1, places=10)
        self.assertIn(L["mkt.decline_1h"], (0, 1))
        self.assertGreaterEqual(L["mkt.max_dd_1h"], 0)
        self.assertIsNotNone(L["mkt.fwd_ret_24h"])                            # D1 22:00 + 24 h within D2
        self.assertIsNone(L["exe.paper_outcome"])
        self.assertEqual(R["exe.paper_outcome"], "paper_r1_linkage_not_authorized")
        self.assertGreater(L["exe.entry_delay_ms"], 0)                       # entry strictly after T

    def test_beyond_loaded_range_is_null(self):
        L, R = LB.compute_labels(self.B, "BTCUSDT", T_at(C.D2_MS, 23, 0))
        self.assertIsNone(L["mkt.fwd_ret_4h"])
        self.assertEqual(R["mkt.fwd_ret_4h"], "beyond_loaded_range")
        self.assertEqual(R["exe.net_ret_24h"], "beyond_loaded_range")

    def test_missing_forward_candle_is_null(self):
        L, R = LB.compute_labels(self.B, "EEEUSDT", T_at(C.D2_MS, 11, 30))
        self.assertEqual(R["mkt.fwd_ret_1h"], "forward_candle_missing")


class Builder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = C.scratch("out")
        cls.m1 = BD.build(C.base_dataset(), [C.D1, C.D2], cls.out, code_commit="testcommit", build_ts="2026-01-01T00:00:00Z")

    def test_label_feature_separation(self):
        f = _rows(self.m1["output_dir"], "features.jsonl.gz")
        lb = _rows(self.m1["output_dir"], "labels.jsonl.gz")
        self.assertEqual([r["row_id"] for r in f], [r["row_id"] for r in lb])
        for r in f:
            self.assertFalse(any(k.startswith(("mkt.", "exe.")) for k in r["features"]))
            self.assertNotIn("labels", r)
        for r in lb:
            self.assertNotIn("features", r)
            self.assertTrue(all(k.startswith(("mkt.", "exe.")) for k in r["labels"]))
        for r in f:
            for k, a in r["feature_available_at"].items():
                if r["features"][k] is not None:
                    self.assertLessEqual(a, r["decision_time_ms"])

    def test_manifest_contents(self):
        m = self.m1
        self.assertEqual(m["source"]["mode"], "sealed")
        self.assertTrue(m["source"]["reproducible"])
        self.assertEqual(m["source"]["schema_versions_consumed"], [2])
        self.assertEqual(m["excluded_by_reason"], {"in_downtime": 7})
        self.assertEqual(m["feature_set"]["count"], 40)
        self.assertGreater(m["row_count"], 1000)
        self.assertEqual(m["quality_summary"]["rows_posthoc_gap_at_decision"], 3)
        self.assertIn("NEWUSDT", m["symbols"])

    def test_deterministic_rebuild_and_relocation(self):
        m2 = BD.build(C.base_dataset(), [C.D1, C.D2], C.scratch("out2"), code_commit="testcommit",
                      build_ts="2030-12-31T23:59:59Z")
        self.assertEqual(m2["logical_hash"], self.m1["logical_hash"])
        for n in ("features.jsonl.gz", "labels.jsonl.gz", "excluded.jsonl.gz"):
            with open(os.path.join(self.m1["output_dir"], n), "rb") as a, open(os.path.join(m2["output_dir"], n), "rb") as b:
                self.assertEqual(a.read(), b.read(), n)
        moved = C.copy_dataset("relocated")
        m3 = BD.build(moved, [C.D1, C.D2], C.scratch("out3"), code_commit="testcommit", write=False)
        self.assertEqual(m3["logical_hash"], self.m1["logical_hash"])
        m4 = BD.build(C.base_dataset(), [C.D1, C.D2], self.out, code_commit="testcommit")
        self.assertTrue(m4.get("existing"))
        m5 = BD.build(C.base_dataset(), [C.D1, C.D2], self.out, code_commit="othercommit", write=False)
        self.assertNotEqual(m5["logical_hash"], self.m1["logical_hash"])

    def test_shuffled_duplicated_input_same_rows(self):
        base = C.copy_dataset("bshuf")
        rng = random.Random(3)
        for t in ("book", "depth", "candle", "market"):
            for p in _segs(base, t, C.D2):
                with gzip.open(p, "rt") as fh:
                    lines = [x.rstrip("\n") for x in fh if x.strip()]
                lines += lines[:5]
                rng.shuffle(lines)
                _write(p, None, raw_lines=lines)
        refresh_hashes(base)
        m = BD.build(base, [C.D1, C.D2], C.scratch("outshuf"), code_commit="testcommit", write=False)
        f1, l1 = self.m1["files"]["features.jsonl.gz"], self.m1["files"]["labels.jsonl.gz"]
        self.assertEqual(m["files"]["features.jsonl.gz"], f1)
        self.assertEqual(m["files"]["labels.jsonl.gz"], l1)

    def test_output_root_safety(self):
        base = C.base_dataset()
        with self.assertRaises(BD.BuildError):
            BD.build(base, [C.D2], os.path.join(base, "derived"), code_commit="x")
        with self.assertRaises(BD.BuildError):
            BD.build(base, [C.D2], "/home/tradmin/research-data/trading-signal-bot/p2/x", code_commit="x")
        with self.assertRaises(BD.BuildError):
            BD.build(base, [C.D2], "/home/tradmin/elsewhere", code_commit="x")
        with self.assertRaises(BD.BuildError):
            BD.build(base, [C.D2], C.scratch("o"), code_commit="x", feature_set="9.9.9")

    def test_builder_enforces_pit(self):
        real = FE.compute

        def leaky(V, sym, ctx, btc):
            o = real(V, sym, ctx, btc)
            o.a["mom.ret_15m_1"] = V.T + 1
            o.v["mom.ret_15m_1"] = 0.0
            return o
        with mock.patch.object(FE, "compute", leaky):
            with self.assertRaises(FE.PITViolation):
                BD.build(C.base_dataset(), [C.D2], C.scratch("leak"), code_commit="x", write=False)

    def test_experimental_build_is_marked_and_separated(self):
        base = C.new_dataset("bunsealed", seal_days=[C.D1], close_days=[C.D1])
        with self.assertRaises(RD.NotSealed):
            BD.build(base, [C.D1, C.D2], C.scratch("oexp"), code_commit="x")
        m = BD.build(base, [C.D2], C.scratch("oexp"), code_commit="x", experimental_active_day=True)
        self.assertFalse(m["source"]["reproducible"])
        self.assertIn("EXPERIMENTAL-nonreproducible", m["output_dir"])

    def test_cli(self):
        rc = BD.main(["--dataset", C.base_dataset(), "--days", C.D2, "--out", C.scratch("cli"), "--code-commit", "x",
                      "--no-write"])
        self.assertEqual(rc, 0)
        rc = BD.main(["--dataset", C.base_dataset(), "--days", "2026-10-09", "--out", C.scratch("cli"),
                      "--code-commit", "x", "--no-write"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
