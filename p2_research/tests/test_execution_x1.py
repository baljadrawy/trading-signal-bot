"""P2-X1 execution calibration & contract closure tests (synthetic data only; no real data, no W3, no Paper)."""
import hashlib
import json
import os
import unittest

from p2_research import instrument as IN
from p2_research.execution import calibration as CAL, model as M
from p2_research.execution.market_state import load_sealed
from p2_research.tests import common as C


def _sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


class TestCalibrationTool(unittest.TestCase):
    def test_plan_is_predeclared_and_fixed(self):
        plan, sha = CAL.load_plan()
        self.assertEqual(plan["notional_set_quote"], [50.0, 500.0, 5000.0])
        self.assertEqual(plan["execution_timestamps"]["latencies_ms"], [0, 1000, 5000])
        self.assertEqual(plan["id"], "X1-CALIBRATION-PLAN")
        self.assertEqual(sha, _sha(CAL.PLAN_FILE))

    def test_percentiles_and_buckets(self):
        p = CAL.pctl([5, 1, 4, 2, 3], [0.5, 0.99, 0.2])
        self.assertEqual((p["n"], p["min"], p["max"], p["p50"], p["p99"], p["p20"]), (5, 1, 5, 3, 5, 1))
        self.assertEqual(CAL.pctl([], [0.5]), {"n": 0})
        b, lab = [1000, 10000], ["a", "b", "c"]
        self.assertEqual([CAL.bucket(v, b, lab) for v in (0, 1000, 1001, 10000, 10001)], ["a", "a", "b", "b", "c"])
        self.assertEqual([CAL.liq_bucket(v, [10.0], ["lo", "hi"]) for v in (9.9, 10.0)], ["lo", "hi"])

    def test_observer_never_changes_state(self):
        base = C.base_dataset()
        times = [C.D1_MS + 9 * 3_600_000 + k * 900_000 + 390_000 for k in range(4)]
        qts = sorted({t + L for t in times for L in (0, 1000, 5000)})
        seen = []
        a = load_sealed(base, [C.D1], query_times=qts)
        b = load_sealed(base, [C.D1], query_times=qts, observer=seen.append)
        self.assertGreater(len(seen), 0)
        inst = IN.binance_spot_instrument("BTCUSDT")
        for t in times:
            for sc in ("EXEC-IDEALIZED", "EXEC-BASE", "EXEC-STRESS"):
                for side in ("buy", "sell"):
                    self.assertEqual(M.estimate_leg(a, inst, side, 50.0, t, sc), M.estimate_leg(b, inst, side, 50.0, t, sc))

    def test_calibration_deterministic_windowed_and_guarded(self):
        base = C.base_dataset()
        o1, o2 = C.scratch("x1-cal-1"), C.scratch("x1-cal-2")
        m1 = CAL.run(base, [C.D1], o1, "f" * 40)
        m2 = CAL.run(base, [C.D1], o2, "f" * 40)
        self.assertEqual(m1["logical_hash"], m2["logical_hash"])
        for f in ("exec_points.jsonl.gz", "calibration.json", "manifest.json"):
            self.assertEqual(_sha(os.path.join(o1, f)), _sha(os.path.join(o2, f)), f)
        self.assertGreaterEqual(m1["decision_time_range"][0], CAL.W3_END_MS)
        self.assertLess(m1["decision_time_range"][1] + 5000, m1["window_ms"][1])
        self.assertEqual(m1["plan"]["sha256"], _sha(CAL.PLAN_FILE))
        cal = _load(os.path.join(o1, "calibration.json"))
        tb = cal["truth_boundary_field_audit"]
        self.assertEqual(tb["trade_or_aggtrade_records"], [])
        self.assertNotIn("book", tb["exchange_event_time_present_by_type"])
        pb = cal["population_b_execution_timestamps"]
        self.assertIn("walk.t0.L1000.buy.50", pb["aggregates"])
        self.assertTrue(all(k.split(".")[-1] in ("50", "500", "5000") for k in pb["aggregates"] if k.startswith("walk.")))
        for f in ("exec_points.jsonl.gz", "calibration.json"):                   # no return / P&L field anywhere
            with open(os.path.join(o1, f), "rb") as fh:
                raw = fh.read()
            if f.endswith(".gz"):
                import gzip
                raw = gzip.decompress(raw)
            for bad in (b"return", b"pnl", b"net_ret", b"fwd_ret", b"label"):
                self.assertNotIn(bad, raw.lower(), f"{f}: {bad}")
        with self.assertRaises(SystemExit):
            CAL.run(base, [C.D1], os.path.join(base, "out"), "f" * 40)
        with self.assertRaises(SystemExit):
            CAL.run(base, [C.D1], os.path.join(CAL.FORBIDDEN_ROOT, "x1"), "f" * 40)


if __name__ == "__main__":
    unittest.main()
