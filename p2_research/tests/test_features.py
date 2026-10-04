import json
import math
import os
import unittest

from p2_research import features as FE, reader as RD, registry as RG
from p2_research.tests import common as C

H = 3_600_000


def T_at(day_ms, h, m=0):
    """Decision time on the grid (15m boundary + 390 s)."""
    return day_ms + h * H + m * 60_000 + RG.DECISION_GRID["offset_ms"]


def feats(B, sym, T):
    V = FE.PITView(B, T)
    return FE.compute(V, sym, FE.market_context(V), FE.btc_context(V))


class PointInTime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = RD.load_days(C.base_dataset(), [C.D1, C.D2])

    def test_future_perturbation_does_not_change_features(self):
        """Strongest PIT test: corrupt/delete everything available after T; features at T must be identical."""
        Ts = [T_at(C.D2_MS, h, m) for h, m in ((0, 0), (6, 0), (10, 0), (13, 30), (22, 45))]
        Ts.append(C.D2_MS + 3 * H + 5_000)                 # off-grid: the 03:00 candles are closed but not yet fetched
        for T in Ts:
            ref = {s: feats(self.B, s, T).v for s in ("BTCUSDT", "AAAUSDT", "CCCUSDT", "DDDUSDT")}
            P = RD.load_days(C.base_dataset(), [C.D1, C.D2])
            for s in list(P.book):
                P.book[s] = [x if x[0] <= T else x[:3] + (x[3] * 3, x[4] * 5) + x[5:] for x in P.book[s]]
            for s in list(P.depth):
                P.depth[s] = [x for x in P.depth[s] if x[0] <= T]
            for k in list(P.candles):
                P.candles[k] = {o: (c if c[8] <= T else c[:4] + (c[4] * 7,) + c[5:]) for o, c in P.candles[k].items()}
            P.market = [m for m in P.market if m[0] <= T]
            P.gaps = [g for g in P.gaps if g["available_at_ms"] <= T]
            P.health = [h for h in P.health if h[0] <= T]
            P._keys = {}
            for s, v in ref.items():
                self.assertEqual(feats(P, s, T).v, v, f"{s}@{T}")

    def test_feature_available_at_never_after_decision(self):
        for T in (T_at(C.D2_MS, 1), T_at(C.D2_MS, 6, 0), T_at(C.D2_MS, 18, 15)):
            for s in ("BTCUSDT", "EEEUSDT", "AAAUSDT"):
                o = feats(self.B, s, T)
                for k, a in o.a.items():
                    if o.v[k] is not None:
                        self.assertIsNotNone(a, k)
                        self.assertLessEqual(a, T, k)

    def test_accessor_refuses_future(self):
        V = FE.PITView(self.B, T_at(C.D2_MS, 3))
        with self.assertRaises(FE.PITViolation):
            V.latest("book", "BTCUSDT", V.T + 1)
        with self.assertRaises(FE.PITViolation):
            V.window("book", "BTCUSDT", V.T - 1000, V.T + 1)

    def test_closed_but_not_yet_available_candle_is_not_used(self):
        T = T_at(C.D2_MS, 3)
        P = RD.load_days(C.base_dataset(), [C.D1, C.D2])
        last_open = (T // 900_000) * 900_000 - 900_000
        c = P.candles[("BTCUSDT", "15m")][last_open]
        P.candles[("BTCUSDT", "15m")][last_open] = c[:8] + (T + 1,) + c[9:]  # closed before T, fetched after T
        o = feats(P, "BTCUSDT", T)
        self.assertIsNone(o.v["mom.ret_15m_1"])
        self.assertEqual(o.r["mom.ret_15m_1"], "latest_closed_candle_unavailable")
        self.assertIsNotNone(feats(self.B, "BTCUSDT", T).v["mom.ret_15m_1"])

    def test_hand_computed_values(self):
        T = T_at(C.D2_MS, 5, 30)
        o = feats(self.B, "BTCUSDT", T)
        st = self.B.candles[("BTCUSDT", "15m")]
        lo = (T // 900_000) * 900_000 - 900_000
        self.assertAlmostEqual(o.v["mom.ret_15m_1"], math.log(st[lo][4] / st[lo - 900_000][4]), places=10)
        b = self.B.latest("book", "BTCUSDT", T)
        self.assertAlmostEqual(o.v["liq.spread_bps"], (b[4] - b[3]) / ((b[3] + b[4]) / 2) * 1e4, places=8)
        self.assertEqual(o.v["ctx.tier"], 0)
        self.assertEqual(o.a["liq.spread_bps"], b[0])


class UniverseAsOf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = RD.load_days(C.base_dataset(), [C.D1, C.D2])

    def test_transition_uses_announcing_record_availability(self):
        eff = C.D2_MS + 6 * H
        before = self.B.epoch_at(eff + 100)                                  # effective, but announced at +200 ms
        after = self.B.epoch_at(eff + 200)
        self.assertNotIn("NEWUSDT", before["tiers"])
        self.assertEqual(before["tiers"]["CCCUSDT"], 2)
        self.assertIn("NEWUSDT", after["tiers"])
        self.assertEqual(after["tiers"]["CCCUSDT"], 1)

    def test_no_retrospective_tier_in_features(self):
        self.assertEqual(feats(self.B, "CCCUSDT", T_at(C.D2_MS, 5, 45)).v["ctx.tier"], 2)
        self.assertEqual(feats(self.B, "CCCUSDT", T_at(C.D2_MS, 6, 0)).v["ctx.tier"], 1)
        V = FE.PITView(self.B, T_at(C.D2_MS, 5, 45))
        self.assertNotIn("NEWUSDT", V.epoch["tiers"])                        # future member invisible


class QualityExposure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = RD.load_days(C.base_dataset(), [C.D1, C.D2])

    def test_gap_known_only_after_it_closed(self):
        T_in = T_at(C.D1_MS, 23, 45)                                         # inside the DDD book gap
        o = feats(self.B, "DDDUSDT", T_in)
        self.assertEqual(o.v["dq.gap_known_1h"], 0)                          # not yet known at T (record written later)
        self.assertEqual(o.v["dq.degraded_flag"], 1)                         # but real-time health says so
        o2 = feats(self.B, "DDDUSDT", T_at(C.D2_MS, 0, 0))
        self.assertGreaterEqual(o2.v["dq.gap_known_1h"], 1)
        self.assertLess(o2.v["dq.reconnect_age_s"], 600)

    def test_missing_depth_is_null_with_reason(self):
        o = feats(self.B, "AAAUSDT", T_at(C.D2_MS, 10, 0))
        for k in ("liq.depth_imbalance_10", "liq.depth_concentration_10", "liq.liq_change_15m"):
            self.assertIsNone(o.v[k])
            self.assertEqual(o.r[k], "depth_stale")
        self.assertEqual(o.v["dq.stale_flag"], 1)
        self.assertGreater(o.v["dq.depth_age_s"], 180)

    def test_restart_boundary(self):
        W2 = C.D1_MS + 20 * H + 600_000
        T = T_at(C.D1_MS, 20, 15)                                            # first decision of run 2
        o = feats(self.B, "AAAUSDT", T)
        self.assertLess(o.v["dq.run_age_s"], 900)
        self.assertEqual(o.r.get("liq.liq_change_15m"), "from_previous_run")  # T-15m value belongs to run 1
        self.assertIsNone(FE.PITView(self.B, T_at(C.D1_MS, 20, 0)).run)       # downtime -> excluded row
        self.assertGreater(T, W2)

    def test_clock_suspect_exposed(self):
        self.assertEqual(feats(self.B, "BTCUSDT", T_at(C.D2_MS, 14, 0)).v["dq.clock_suspect"], 1)
        self.assertEqual(feats(self.B, "BTCUSDT", T_at(C.D2_MS, 16, 0)).v["dq.clock_suspect"], 0)

    def test_missing_candle_is_null_not_filled(self):
        o = feats(self.B, "EEEUSDT", T_at(C.D2_MS, 13, 0))
        self.assertIsNone(o.v["vol.rv_15m_16"])
        self.assertEqual(o.r["vol.rv_15m_16"], "candle_history_gap")


class Registry(unittest.TestCase):
    def test_registry_file_matches_code(self):
        with open(RG.REGISTRY_PATH, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), RG.registry_json())

    def test_registry_complete_and_consistent(self):
        B = RD.load_days(C.base_dataset(), [C.D2])
        o = feats(B, "BTCUSDT", T_at(C.D2_MS, 12))
        ids = [f["id"] for f in RG.FEATURES]
        self.assertEqual(sorted(o.v), sorted(ids))
        self.assertTrue(25 <= len(ids) <= 40)
        need = {"id", "version", "source", "formula", "required_history", "sampling_frequency", "availability_delay",
                "missing_data_behavior", "normalization", "expected_range", "pit_rule", "tier_applicability", "cost",
                "status"}
        for f in RG.FEATURES:
            self.assertTrue(need <= set(f), f["id"])
            self.assertIn(f["status"], RG.STATUSES)
        fams = {f["family"] for f in RG.FEATURES}
        self.assertEqual(fams, {"price_momentum", "volatility", "liquidity", "volume", "market_context", "data_quality"})
        self.assertFalse(any(k.startswith(("mkt.", "exe.")) for k in ids))


if __name__ == "__main__":
    unittest.main()
