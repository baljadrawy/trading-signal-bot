"""P2-A canonical dataset: fail-closed PIT / W3 / identity tests (stdlib unittest).

Synthetic fixtures prove each validator FAILS on a violation. When P2A_DATASET points to a built dataset
directory, the same validators must return zero violations on it. No production access.
"""
import os
import pathlib
import unittest

from research.p2 import contract as C
from research.p2 import validate as V


def _decision(signal_id=1, symbol="BTCUSDT", tf="4h", t="2026-07-01 10:05:00.123456", window=None):
    ms = C.naive_utc_text_to_ms(t)
    c = C.infer_decision_candle(ms, tf)
    return {"decision_uid": C.decision_uid(signal_id, symbol, tf, t), "signal_id": str(signal_id), "symbol": symbol,
            "timeframe": tf, "decision_time_utc": t, "decision_time_ms": str(ms),
            "window": window or C.window_for_ms(ms), "inferred_candle_open_ms": str(c["open_ms"]),
            "inferred_candle_close_ms": str(c["close_ms"]), "candle_ambiguous": "true" if c["ambiguous"] else "false",
            "candle_provenance": "INFERRED", "decision_time_provenance": "OBSERVED",
            "geometry_provenance": "STORED_SNAPSHOT"}


def _ctx(d, name="rsi", avail=None, observed="", source="signals.features_snapshot", ns="features_snapshot"):
    return {"decision_uid": d["decision_uid"], "namespace": ns, "feature_name": name, "value_json": "1",
            "value_type": "number", "provenance": "STORED_SNAPSHOT", "source": source, "observed_at_ms": observed,
            "available_at_ms": str(avail if avail is not None else d["decision_time_ms"]), "pit_safe": "true",
            "available_at_basis": "x", "feature_version": "t"}


class TestContract(unittest.TestCase):
    def test_freeze_constant(self):
        self.assertEqual(C.FREEZE_MS, 1787132026000)
        self.assertEqual(C.window_for_ms(C.FREEZE_MS - 1), "W2")
        self.assertEqual(C.window_for_ms(C.FREEZE_MS), "W3")
        self.assertEqual(C.window_for_ms(C.W1_END_MS - 1), "W1")
        self.assertEqual(C.window_for_ms(C.W1_END_MS), "W2")

    def test_identity_deterministic_and_order_independent(self):
        a = C.decision_uid(42, "ETHUSDT", "15m", "2026-04-08 16:49:53.833002")
        self.assertEqual(a, C.decision_uid(42, "ETHUSDT", "15m", "2026-04-08 16:49:53.833002"))
        self.assertNotEqual(a, C.decision_uid(43, "ETHUSDT", "15m", "2026-04-08 16:49:53.833002"))
        self.assertTrue(a.startswith("dec_") and len(a) == 28)

    def test_candle_inference_closed_and_aligned(self):
        for tf, tfms in C.TF_MS.items():
            for d in (C.FREEZE_MS - 1, C.W1_END_MS, C.W1_END_MS + 1, 1780000000123):
                c = C.infer_decision_candle(d, tf)
                self.assertLess(c["close_ms"], d)
                self.assertEqual(c["open_ms"] % tfms, 0)
                self.assertGreaterEqual(c["close_ms"] + 1 + tfms, d)  # latest closed, not an older one

    def test_candle_ambiguity(self):
        self.assertTrue(C.infer_decision_candle(C.W1_END_MS + 60_000, "15m")["ambiguous"])  # 15m always ambiguous
        self.assertFalse(C.infer_decision_candle(C.W1_END_MS + 2 * 3600_000, "4h")["ambiguous"])
        self.assertTrue(C.infer_decision_candle(C.W1_END_MS + 10 * 60_000, "1h")["ambiguous"])

    def test_candle_id_matches_p1_format(self):
        self.assertEqual(C.candle_id("BTCUSDT", "4h", 1780000000000), "BTCUSDT|4h|1780000000000")


class TestValidatorsFailClosed(unittest.TestCase):
    def test_w3_leak_detected(self):
        d = _decision(t="2026-08-19 09:33:46.000000", window="W2")  # mislabelled W3 row
        self.assertTrue(V.check_no_w3({"decision": [d]}))
        self.assertTrue(V.check_window_assignment([d]))

    def test_w3_leak_in_lifecycle_detected(self):
        lt = {"active_trade_id": "1", "decision_uid": "x", "window": "W2", "opened_ms": str(C.FREEZE_MS - 10),
              "exit_ms": str(C.FREEZE_MS + 1)}
        self.assertTrue(any("trade_lifecycle.exit_ms" in v for v in V.check_no_w3({"trade_lifecycle": [lt]})))

    def test_risk_freeze_day_detected(self):
        self.assertTrue(V.check_no_w3({"risk_context": [{"risk_date": "2026-08-19"}]}))
        self.assertFalse(V.check_no_w3({"risk_context": [{"risk_date": "2026-08-18"}]}))

    def test_boundary_one_ms_before_is_allowed(self):
        d = _decision(t="2026-08-19 09:33:45.999000")
        self.assertEqual(d["window"], "W2")
        self.assertFalse(V.check_no_w3({"decision": [d]}))

    def test_feature_available_after_decision_detected(self):
        d = _decision()
        bad = _ctx(d, avail=int(d["decision_time_ms"]) + 1)
        self.assertTrue(V.check_available_before_decision([bad], [d]))
        self.assertFalse(V.check_available_before_decision([_ctx(d)], [d]))

    def test_pit_safe_without_available_at_detected(self):
        d = _decision(); bad = _ctx(d); bad["available_at_ms"] = ""
        self.assertTrue(V.check_available_before_decision([bad], [d]))

    def test_candle_not_closed_detected(self):
        d = _decision(); d["inferred_candle_close_ms"] = d["decision_time_ms"]
        self.assertTrue(V.check_inferred_candle_closed([d]))

    def test_wrong_ambiguity_flag_detected(self):
        d = _decision(tf="15m"); d["candle_ambiguous"] = "false"
        self.assertTrue(any("AMBIGUITY" in v for v in V.check_inferred_candle_closed([d])))

    def test_inferred_candle_must_be_labelled_inferred(self):
        d = _decision(); d["candle_provenance"] = "OBSERVED"
        self.assertTrue(V.check_inferred_candle_closed([d]))

    def test_future_outcome_in_features_detected(self):
        d = _decision()
        for name in ("profit_percent", "result", "mfe_24h", "exit_price", "stop_hit", "return_24h", "pnl", "win_rate"):
            self.assertTrue(V.check_no_outcome_in_features([_ctx(d, name=name)]), name)
        for name in ("rsi", "atr_pct", "stop_risk_pct", "stop_invalidation", "dist_ema200", "volume_ratio", "trend_ok"):
            self.assertFalse(V.check_no_outcome_in_features([_ctx(d, name=name)]), name)

    def test_daily_macro_last_of_day_detected(self):
        d = _decision()
        self.assertTrue(V.check_no_daily_macro_last_of_day([_ctx(d, name="usdt_d", source="macro_history")]))

    def test_duplicate_identity_detected(self):
        d = _decision()
        self.assertTrue(V.check_decision_identity([d, dict(d)]))
        t = dict(d); t["decision_uid"] = "dec_000000000000000000000000"
        self.assertTrue(V.check_decision_identity([t]))

    def test_execution_as_market_label_detected(self):
        self.assertTrue(V.check_layer_separation({"market_outcome": [{"decision_uid": "x", "provenance": "PAPER_MODEL",
                                                                      "label_name": "fill_price"}]}))
        self.assertTrue(V.check_layer_separation({"execution_outcome": [{"decision_uid": "x", "execution_provenance": "LIVE_EXECUTION"}]}))

    def test_missing_columns_fail_closed(self):
        with self.assertRaises(KeyError):
            V.check_available_before_decision([{"decision_uid": "x"}], [])


@unittest.skipUnless(os.environ.get("P2A_DATASET") or os.environ.get("P2A_CANONICAL"),
                     "set P2A_DATASET (build dir) or P2A_CANONICAL (canonical/<dataset_id> dir)")
class TestBuiltDataset(unittest.TestCase):
    def test_built_dataset_has_zero_violations(self):
        from research.p2.extract import read_csv_gz
        base = pathlib.Path(os.environ.get("P2A_CANONICAL") or pathlib.Path(os.environ["P2A_DATASET"]) / "canonical")
        tables = {n: read_csv_gz(base / f"{n}.csv.gz") for n in C.SCHEMAS if n != "provenance"}
        result = V.run_all(tables)
        self.assertEqual({k: len(v) for k, v in result.items() if v}, {})
        self.assertEqual(tables["market_outcome"], [])


if __name__ == "__main__":
    unittest.main()
