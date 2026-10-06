"""P2-RM0 portfolio & risk measurement tests (synthetic markets and the synthetic sealed dataset only; no real data,
no W3, no Paper, no outcomes)."""
import ast
import copy
import hashlib
import json
import math
import os
import random
import shutil
import tempfile
import unittest

from p2_research import instrument as IN, ledger as LG, reader as RD
from p2_research.execution import contracts as XC1, contracts_v2 as X2
from p2_research.execution.market_state import PITViolation
from p2_research.risk import contracts as RC
from p2_research.risk import drawdown as DD
from p2_research.risk import pitcheck as PC
from p2_research.risk import portfolios as PF
from p2_research.risk import position as PO
from p2_research.risk import reference as REF
from p2_research.risk import realdata as RDT
from p2_research.risk import snapshot as SN
from p2_research.risk import stats as ST
from p2_research.risk import values as V
from p2_research.risk.market import RiskMarket, RiskView, load_risk_market
from p2_research.tests import common as CM
from p2_research.tests import rm0_synth as R
from p2_research.tests.synth import ms

RISK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "risk")
P2D0_SUMS = "2bedc3f5c3a4de4fde8d9c8518270f7cd0078033fd754c75c20297954e408573"
P2X1_SUMS = "3c554702948867fa26d4bba95b922f5e1db5902e42b088d9cdc49fdceefeec2f"
P2X2_SUMS = "f20e22a5e79b2ab36caa180ca25d652e6e273c2ad72392ed860c2d7f72aa88d0"
_MARKET = None


def market():
    global _MARKET
    if _MARKET is None:
        _MARKET = R.make_market()
    return _MARKET


def snap(positions, M=None, t=R.T, **kw):
    return SN.build_snapshot(M or market(), positions, t, **kw)


def line(s):
    return SN.canonical_line(s)


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _write(p, text):
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def _sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ====================================================================== contracts ======
class TestContracts(unittest.TestCase):
    def test_rm0_frozen_and_upstream_untouched(self):
        C = RC.RiskContracts()
        self.assertEqual(sorted(C.sums), sorted(RC.FILES))
        root = os.path.dirname(RISK_DIR)
        self.assertEqual(_sha(os.path.join(root, "research", "FROZEN_SHA256SUMS.json")), P2D0_SUMS)
        self.assertEqual(XC1.ContractSet().sha256, P2X1_SUMS)
        self.assertEqual(X2.ContractSetV2().sha256, P2X2_SUMS)
        from p2_research import protocol
        protocol.verify_frozen()

    def test_tamper_and_file_set_refused(self):
        d = tempfile.mkdtemp()
        try:
            for f in os.listdir(RC.CONTRACT_DIR):
                shutil.copy(os.path.join(RC.CONTRACT_DIR, f), d)
            RC.RiskContracts(d)
            p = os.path.join(d, "policy_v1.json")
            doc = json.loads(_read(p))
            doc["research_flag_thresholds"][0]["value"] = 0.9
            _write(p, json.dumps(doc))
            with self.assertRaises(RC.RiskContractError):
                RC.RiskContracts(d)
            sp = os.path.join(d, RC.SUMS_FILE)
            s = json.loads(_read(sp))
            s["files"]["extra.json"] = "0" * 64
            _write(sp, json.dumps(s))
            with self.assertRaises(RC.RiskContractError):
                RC.RiskContracts(d, verify=False)
        finally:
            shutil.rmtree(d)

    def test_p2x_reuse_references_exist_and_match(self):
        C, X = RC.default(), X2.default()
        reuse = C.metrics["liquidity"]["p2x_reuse"]
        self.assertEqual(reuse["contract_set_sha256"], X.sha256)
        for key in ("stale_policy", "data_quality_policy", "depth_walk"):
            mid, ver = reuse[key].split(" ")[0].split("@")
            self.assertEqual(X.model(mid)["version"], ver)
        self.assertEqual(X.model("X1-S2-DEPTHWALK")["kind"], "displayed_depth_walk")
        self.assertEqual(X.scenario("EXEC-BASE")["latency_model"], "X1-LAT-1S")     # stays an ASSUMED P2-X scenario

    def test_thresholds_are_policy_assumed_uncalibrated_and_not_b3(self):
        C = RC.default()
        b3 = {3, 10, 15, 7, 50}
        for t in C.policy["research_flag_thresholds"]:
            self.assertEqual((t["class"], t["provenance"], t["calibrated"]), ("POLICY", "ASSUMED", False))
        for k, v in C.policy["research_references"].items():
            self.assertEqual((v["class"], v["provenance"], v["calibrated"]), ("POLICY", "ASSUMED", False))
        heat = json.dumps(C.metrics["heat"])
        for n in ("MAX_DAILY", "MAX_DRAWDOWN", "MAX_WEEKLY", "RISK_CANARY"):
            self.assertNotIn(n, heat)
        self.assertNotIn(C.thresholds["RM0-F-VOL-HEAT"]["value"] * 100, b3)

    def test_documented_paper_policy_is_never_read_by_code(self):
        for f in sorted(os.listdir(RISK_DIR)):
            if f.endswith(".py"):
                src = _read(os.path.join(RISK_DIR, f))
                for name in ("documented_paper_policy", "MAX_DAILY_LOSS", "MAX_DRAWDOWN_PERCENT", "stake_usdt",
                             "hard_halt", "soft_reduce"):
                    self.assertNotIn(name, src, f"{f} references {name}")

    def test_no_side_effect_imports(self):
        bad = {"socket", "subprocess", "requests", "urllib", "http", "psycopg", "psycopg2", "telegram", "asyncio",
               "sqlite3", "smtplib", "p2_forward"}
        for f in sorted(os.listdir(RISK_DIR)):
            if f.endswith(".py"):
                tree = ast.parse(_read(os.path.join(RISK_DIR, f)))
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name.split(".")[0] for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0:
                        names = [(node.module or "").split(".")[0]]
                    self.assertFalse(set(names) & bad, f"{f} imports {names}")


# ====================================================================== position contract ======
class TestPosition(unittest.TestCase):
    def test_valid_long(self):
        p = PO.validate(R.position("BTCUSDT", 1000))
        self.assertEqual((p.side, p.sign, p.instrument_id), ("long", 1, "crypto:binance:spot:BTCUSDT"))

    def test_malformed_refused(self):
        good = R.position("BTCUSDT", 1000)
        cases = [
            dict(good, quantity=-1.0), dict(good, quantity=float("nan")), dict(good, reference_price=0),
            dict(good, notional=999.0), dict(good, symbol="btcusdt"), dict(good, instrument_id="crypto:binance:spot:ETHUSDT"),
            dict(good, quote_currency="USDC"), dict(good, reference_time_ms=good["decision_time_ms"] + 1),
            dict(good, decision_time_ms=1.5), dict(good, hypothesis_id="X01"), dict(good, side="buy"),
            dict(good, extra_field=1), dict(good, provenance={"class": "SYNTHETIC_FIXTURE"}),
            dict(good, provenance={"class": "PAPER_POSITION", "source": "x"}),
            dict(good, provenance={"class": "HYPOTHETICAL_RESEARCH", "source": "paper-r1 trade 12"}),
            dict(good, provenance={"class": "HYPOTHETICAL_RESEARCH", "source": "account balance"}),
            {k: v for k, v in good.items() if k != "notional"}, "not-a-dict", dict(good, quantity=True)]
        for c in cases:
            with self.assertRaises((PO.PositionError, TypeError), msg=str(c)[:120]):
                PO.validate(c)

    def test_other_market_refused(self):
        with self.assertRaises(IN.UnsupportedMarket):
            PO.validate(R.position("BTCUSDT", 1000, venue="coinbase"))
        with self.assertRaises(IN.UnsupportedMarket):
            PO.validate(R.position("BTCUSDT", 1000, asset_class="equity"))

    def test_short_conceptual_only(self):
        with self.assertRaises(PO.UnauthorizedSide):
            PO.validate(R.position("BTCUSDT", 1000, side="short"))
        with self.assertRaises(PO.UnauthorizedSide):
            PO.normalize([R.position("BTCUSDT", 1000, side="short")])
        p = PO.validate(R.position("BTCUSDT", 1000, side="short"), conceptual_short=True)
        self.assertEqual(p.signed_notional, -1000.0)

    def test_w3_decision_time_refused(self):
        t = ms("2026-09-01T00:00:00Z")
        with self.assertRaises(LG.W3SealedError):
            PO.validate(R.position("BTCUSDT", 1000, t=t))

    def test_duplicates(self):
        a, b = R.position("ETHUSDT", 1000), R.position("ETHUSDT", 500, px=125.0)
        with self.assertRaises(PO.DuplicateIdentity):
            PO.normalize([a, b])
        ps, log = PO.normalize([a, b], duplicates="aggregate")
        self.assertEqual(len(ps), 1)
        self.assertEqual(ps[0].notional, 1500.0)
        self.assertAlmostEqual(ps[0].quantity, 10 + 4)
        self.assertAlmostEqual(ps[0].reference_price, 1500 / 14)
        self.assertEqual(log[0]["merged"], 2)
        ps2, _ = PO.normalize([b, a], duplicates="aggregate")
        self.assertEqual(ps, ps2)
        with self.assertRaises(PO.DuplicateIdentity):
            PO.normalize([a, R.position("ETHUSDT", 10, side="short")], duplicates="aggregate", conceptual_short=True)

    def test_order_invariance(self):
        ps = [R.position(s, 100 * (i + 1)) for i, s in enumerate(("ETHUSDT", "AAAUSDT", "BTCUSDT"))]
        self.assertEqual(PO.normalize(ps)[0], PO.normalize(list(reversed(ps)))[0])


# ====================================================================== values / quality ======
class TestValues(unittest.TestCase):
    def test_null_rules(self):
        with self.assertRaises(V.ValueRuleError):
            V.mv(None, V.DERIVED)
        with self.assertRaises(V.ValueRuleError):
            V.mv(0.0, V.UNAVAILABLE, V.ST_UNAVAILABLE, "x")
        with self.assertRaises(V.ValueRuleError):
            V.mv(None, V.UNAVAILABLE, V.ST_UNAVAILABLE)
        with self.assertRaises(V.ValueRuleError):
            V.mv(None, V.UNAVAILABLE, V.STALE_INPUT, "x")
        with self.assertRaises(V.ValueRuleError):
            V.mv(float("nan"), V.DERIVED)
        with self.assertRaises(V.ValueRuleError):
            V.check_tree({"a": {"value": None, "class": "DERIVED", "state": "VALID", "reason": None, "flags": []}})

    def test_precedence(self):
        self.assertEqual(V.worst(V.VALID, V.GAP_AFFECTED, V.STALE_INPUT), V.STALE_INPUT)
        self.assertEqual(V.worst(V.INSUFFICIENT_HISTORY, V.ST_UNAVAILABLE), V.ST_UNAVAILABLE)
        self.assertEqual(tuple(RC.default().quality["precedence_worst_first"]), V.PRECEDENCE)
        self.assertEqual(set(RC.default().quality["states"]), set(V.PRECEDENCE))


# ====================================================================== exposure / concentration ======
class TestExposureConcentration(unittest.TestCase):
    def test_zero_positions(self):
        s = snap([])
        self.assertEqual(s["exposure"]["gross"]["value"], 0)
        self.assertEqual(s["exposure"]["gross"]["state"], V.VALID)
        for k in ("largest_share", "hhi", "effective_n_notional"):
            self.assertIsNone(s["concentration"][k]["value"])
            self.assertEqual(s["concentration"][k]["reason"], "flat_portfolio")
        self.assertIsNone(s["btc_exposure"]["portfolio_beta_to_btc"]["value"])
        self.assertEqual(s["heat"]["exposure_heat"]["value"], 0)
        self.assertEqual(s["actions"], [])
        self.assertIn("$.concentration.hhi", [u["path"] for u in s["unavailable"]])

    def test_one_position(self):
        s = snap([R.position("BTCUSDT", 1000)])
        c = s["concentration"]
        self.assertEqual((c["largest_share"]["value"], c["hhi"]["value"], c["effective_n_notional"]["value"]), (1, 1, 1))
        self.assertIsNone(s["correlation"]["average_pairwise_weighted"]["value"])
        self.assertEqual(s["correlation"]["average_pairwise_weighted"]["reason"], "fewer_than_two_positions")
        self.assertEqual(s["btc_exposure"]["direct_btc_weight"]["value"], 1)
        self.assertEqual(s["exposure"]["by_tier"]["tier0"]["count"], 1)

    def test_dominant_and_invariants(self):
        ps = [R.position("ETHUSDT", 6000)] + [R.position(x, 500) for x in ("DDDUSDT", "EEEUSDT", "FFFUSDT")]
        s = snap(ps)
        c = s["concentration"]
        self.assertAlmostEqual(c["largest_share"]["value"], 0.8)
        self.assertAlmostEqual(c["top3_share"]["value"], (6000 + 1000) / 7500)
        k = len(ps)
        self.assertTrue(1 / k <= c["hhi"]["value"] <= 1)
        self.assertTrue(1 <= c["effective_n_notional"]["value"] <= k)
        self.assertIn("RM0-F-LARGEST-SHARE", s["diversification"]["limiting_factors"])
        self.assertIn("RM0-F-LOW-EFFECTIVE-N", s["diversification"]["limiting_factors"])
        eq = snap([R.position(x, 700) for x in ("DDDUSDT", "EEEUSDT", "FFFUSDT", "GGGUSDT")])
        self.assertAlmostEqual(eq["concentration"]["effective_n_notional"]["value"], 4)
        self.assertAlmostEqual(sum(v["value"] for v in eq["concentration"]["tier_shares"].values()), 1)

    def test_conceptual_short_exposure(self):
        ps = [R.position("BTCUSDT", 1000), R.position("ETHUSDT", 400, side="short")]
        with self.assertRaises(PO.UnauthorizedSide):
            snap(ps)
        s = snap(ps, conceptual_short=True)
        e = s["exposure"]
        self.assertEqual((e["gross"]["value"], e["net"]["value"], e["long"]["value"], e["short"]["value"]),
                         (1400, 600, 1000, 400))
        self.assertIn("RM0-S-SHORT-CONCEPTUAL-NOT-AUTHORIZED", [f["id"] for f in s["flags"]])

    def test_identical_symbols(self):
        with self.assertRaises(PO.DuplicateIdentity):
            snap([R.position("BTCUSDT", 500), R.position("BTCUSDT", 500)])
        s = snap([R.position("BTCUSDT", 500), R.position("BTCUSDT", 500)], duplicates="aggregate")
        self.assertEqual(s["exposure"]["count"], 1)
        self.assertEqual(s["correlation"]["pairs"], {})

    def test_not_in_universe_bucket_and_capital(self):
        s = snap([R.position("ZZZUSDT", 100)])
        self.assertIn(SN.NOT_IN_UNIVERSE, s["exposure"]["by_tier"])
        self.assertIsNone(s["volatility"]["per_position"]["crypto:binance:spot:ZZZUSDT"]["sigma_15m_long"]["value"])
        big = snap([R.position("BTCUSDT", 20000)])
        self.assertIn("RM0-S-EXCEEDS-CAPITAL", [f["id"] for f in big["flags"]])
        with self.assertRaises(SN.SnapshotInputError):
            snap([], capital={"value": 5000, "provenance": "ACCOUNT_BALANCE"})
        s2 = snap([R.position("BTCUSDT", 1000)], capital={"value": 5000, "currency": "USDT",
                                                          "provenance": "ASSUMED_HYPOTHETICAL"})
        self.assertAlmostEqual(s2["heat"]["exposure_heat"]["value"], 0.2)
        self.assertEqual(s2["heat"]["exposure_heat"]["class"], V.ASSUMED)


# ====================================================================== correlation / BTC / vol ======
class TestCorrelationBtcVol(unittest.TestCase):
    def test_high_and_low_correlation(self):
        M = R.make_market(betas={"AAAUSDT": 1.0, "BBBUSDT": 1.0, "DDDUSDT": 0.0, "EEEUSDT": 0.0},
                          idio={"AAAUSDT": 1e-5, "BBBUSDT": 1e-5, "DDDUSDT": 0.003, "EEEUSDT": 0.003})
        s = snap([R.position(x, 500) for x in ("AAAUSDT", "BBBUSDT", "DDDUSDT", "EEEUSDT")], M)
        pr = s["correlation"]["pairs"]
        self.assertGreater(pr["AAAUSDT|BBBUSDT"]["rho"]["value"], 0.99)
        self.assertLess(abs(pr["DDDUSDT|EEEUSDT"]["rho"]["value"]), 0.3)
        vals = [p["rho"]["value"] for p in pr.values()]
        self.assertTrue(all(-1 <= v <= 1 for v in vals))
        avg = s["correlation"]["average_pairwise_weighted"]["value"]
        self.assertTrue(min(vals) - 1e-12 <= avg <= max(vals) + 1e-12)
        self.assertEqual(s["correlation"]["max_pairwise"]["value"], max(vals))
        lo, hi = pr["AAAUSDT|BBBUSDT"]["ci95_descriptive"]
        self.assertTrue(lo <= pr["AAAUSDT|BBBUSDT"]["rho"]["value"] <= hi)

    def test_btc_heavy_vs_alt_basket_with_high_beta(self):
        M = R.make_market(betas={x: 1.5 for x in ("DDDUSDT", "EEEUSDT", "FFFUSDT")},
                          idio={x: 0.0005 for x in ("DDDUSDT", "EEEUSDT", "FFFUSDT")})
        heavy = snap([R.position("BTCUSDT", 5000), R.position("ETHUSDT", 1000)], M)
        self.assertAlmostEqual(heavy["btc_exposure"]["direct_btc_weight"]["value"], 5000 / 6000)
        alt = snap([R.position(x, 1000) for x in ("DDDUSDT", "EEEUSDT", "FFFUSDT")], M)
        b = alt["btc_exposure"]
        self.assertEqual(b["direct_btc_weight"]["value"], 0)
        self.assertGreater(b["portfolio_beta_to_btc"]["value"], 1.3)
        self.assertLess(b["weighted_correlation_with_btc"]["value"], 1.0)
        self.assertNotEqual(b["portfolio_beta_to_btc"]["value"], b["weighted_correlation_with_btc"]["value"])
        self.assertIn("RM0-F-BTC-BETA", [f["id"] for f in alt["flags"]])
        own = heavy["btc_exposure"]["per_position"]["crypto:binance:spot:BTCUSDT"]
        self.assertAlmostEqual(own["beta_to_btc"]["value"], 1.0, places=12)
        self.assertAlmostEqual(own["correlation_with_btc"]["value"], 1.0, places=12)

    def test_insufficient_history_and_beta_history(self):
        t = R.T0 + 20 * R.BAR + 390_000                           # only ~19 returns since the run start
        M = R.make_market(t=t)
        s = snap([R.position("BTCUSDT", 1000, t=t), R.position("AAAUSDT", 1000, t=t)], M, t=t)
        m = s["volatility"]["per_position"]["crypto:binance:spot:AAAUSDT"]
        self.assertIsNone(m["sigma_15m_long"]["value"])
        self.assertEqual(m["sigma_15m_long"]["state"], V.INSUFFICIENT_HISTORY)
        self.assertIsNotNone(m["sigma_15m_short"]["value"])
        bt = s["btc_exposure"]["per_position"]["crypto:binance:spot:AAAUSDT"]["beta_to_btc"]
        self.assertEqual((bt["value"], bt["state"]), (None, V.INSUFFICIENT_HISTORY))
        self.assertEqual(s["correlation"]["pairs"]["AAAUSDT|BTCUSDT"]["rho"]["state"], V.INSUFFICIENT_HISTORY)
        self.assertIsNone(s["heat"]["vol_heat"]["value"])
        self.assertEqual(s["heat"]["vol_heat"]["state"], V.INSUFFICIENT_HISTORY)
        self.assertEqual(s["heat"]["coverage"]["with_sigma"], 0)

    def test_missing_btc_history_never_zero(self):
        M = R.make_market()
        M.candles.pop(("BTCUSDT", "15m"))
        M = RiskMarket(M.state, M.candles)
        s = snap([R.position("AAAUSDT", 1000)], M)
        b = s["btc_exposure"]["per_position"]["crypto:binance:spot:AAAUSDT"]
        self.assertIsNone(b["beta_to_btc"]["value"])
        self.assertIsNone(b["correlation_with_btc"]["value"])
        self.assertIsNone(s["btc_exposure"]["portfolio_beta_to_btc"]["value"])

    def test_gap_in_correlation_window(self):
        E = R.last_open(R.T)
        miss = {("AAAUSDT", E - 10 * R.BAR), ("AAAUSDT", E - 11 * R.BAR)}
        M = R.make_market(missing=miss)
        s = snap([R.position("AAAUSDT", 500), R.position("BBBUSDT", 500)], M)
        r = s["correlation"]["pairs"]["AAAUSDT|BBBUSDT"]
        self.assertEqual(r["rho"]["state"], V.GAP_AFFECTED)
        self.assertEqual(r["n_obs"], 96 - 3)                       # 2 missing bars remove 3 returns (no bridging)
        self.assertEqual(s["volatility"]["per_position"]["crypto:binance:spot:AAAUSDT"]["n_returns_long"], 93)

    def test_stale_latest_candle(self):
        E = R.last_open(R.T)
        M = R.make_market(missing={(s, E) for s in R.TIERS})
        s = snap([R.position("AAAUSDT", 500)], M)
        self.assertEqual(s["volatility"]["per_position"]["crypto:binance:spot:AAAUSDT"]["sigma_15m_long"]["state"],
                         V.STALE_INPUT)

    def test_vol_spike_and_high_vol(self):
        M = R.make_market(spike={"DDDUSDT": (16, 6.0)}, idio={"EEEUSDT": 0.02})
        s = snap([R.position("DDDUSDT", 500), R.position("EEEUSDT", 500), R.position("FFFUSDT", 500)], M)
        d = s["volatility"]["per_position"]["crypto:binance:spot:DDDUSDT"]
        self.assertTrue(d["vol_spike"])
        self.assertGreater(d["vol_ratio_short_long"]["value"], 2)
        e = s["volatility"]["per_position"]["crypto:binance:spot:EEEUSDT"]
        self.assertTrue(e["high_vol"])
        ids = [f["id"] for f in s["flags"]]
        self.assertIn("RM0-P-VOL-SPIKE", ids)
        self.assertIn("RM0-P-HIGH-VOL", ids)
        self.assertEqual(d["sigma_1d_equiv"]["class"], V.ASSUMED)
        self.assertAlmostEqual(d["sigma_1d_equiv"]["value"], d["sigma_15m_long"]["value"] * math.sqrt(96), places=9)

    def test_covariance_invariants(self):
        ps = [R.position(x, 300 + 100 * i) for i, x in enumerate(("BTCUSDT", "ETHUSDT", "AAAUSDT", "DDDUSDT"))]
        s = snap(ps)
        rc = s["risk_contribution"]
        self.assertAlmostEqual(sum(v["value"] for v in rc["covariance_euler"].values()), 1, places=9)
        self.assertAlmostEqual(sum(v["value"] for v in rc["notional"].values()), 1, places=12)
        self.assertAlmostEqual(sum(v["value"] for v in rc["standalone_vol"].values()), 1, places=9)
        dr = s["diversification"]["components"]["diversification_ratio"]["value"]
        self.assertGreaterEqual(dr, 1 - 1e-12)                     # long-only: sigma_p <= sum |s_i| sigma_i
        self.assertIsNone(s["diversification"]["effective_bets"]["value"])
        self.assertIsNone(s["diversification"]["single_score"])
        self.assertLessEqual(s["volatility"]["portfolio_vol_proxy"]["portfolio_sigma_1d_ccy"]["value"],
                             s["heat"]["vol_heat_ccy"]["value"] + 1e-6)

    def test_covariance_condition(self):
        t = R.T0 + 51 * R.BAR + 390_000                            # 50 returns >= min_obs 48 but < 5 x 11 = 55
        M = R.make_market(t=t)
        ps = [R.position(x, 100, t=t) for x in sorted(R.TIERS)]
        s = snap(ps, M, t=t)
        self.assertIsNone(s["volatility"]["portfolio_vol_proxy"]["portfolio_sigma_1d_ccy"]["value"])
        self.assertIn("covariance_condition_not_met",
                      s["volatility"]["portfolio_vol_proxy"]["portfolio_sigma_1d_ccy"]["reason"])


# ====================================================================== liquidity ======
class TestLiquidity(unittest.TestCase):
    def test_insufficient_depth(self):
        M = R.make_market(depth_qty={"DDDUSDT": 0.01})
        s = snap([R.position("DDDUSDT", 3000), R.position("EEEUSDT", 100)], M)
        d = s["liquidity"]["per_position"]["crypto:binance:spot:DDDUSDT"]
        self.assertEqual(d["depth_sufficiency"], "BEYOND_DISPLAYED_DEPTH")
        self.assertTrue(d["weak_liquidity"])
        self.assertEqual(s["liquidity"]["notional_beyond_displayed_depth"]["value"], 3000)
        self.assertIn("RM0-F-WEAK-LIQ-SHARE", [f["id"] for f in s["flags"]])
        self.assertIsNone(s["liquidity"]["market_impact"]["value"])
        self.assertIsNone(d["market_impact"]["value"])

    def test_stale_liquidity(self):
        M = R.make_market(depth_age={"EEEUSDT": 9_000}, book_age={"FFFUSDT": 700_000})
        s = snap([R.position(x, 100) for x in ("DDDUSDT", "EEEUSDT", "FFFUSDT")], M)
        L = s["liquidity"]["per_position"]
        e = L["crypto:binance:spot:EEEUSDT"]
        self.assertTrue(e["stale_depth_policy"])
        self.assertEqual(e["depth_age_ms"]["state"], V.STALE_INPUT)
        f = L["crypto:binance:spot:FFFUSDT"]
        self.assertIsNone(f["spread_bps"]["value"])
        self.assertIsNone(f["weak_liquidity"])
        self.assertEqual(s["liquidity"]["notional_liquidity_unknown"]["value"], 100)
        self.assertIsNone(s["liquidity"]["weak_liquidity_share"]["value"])
        self.assertIsNone(s["liquidity"]["weighted_spread_bps"]["value"])
        self.assertIn("RM0-F-LIQ-UNKNOWN", [x["id"] for x in s["flags"]])

    def test_missing_book_refuses_fixture_member(self):
        M = R.make_market(drop_book=("BTCUSDT",))
        ctx = SN.Context(M, R.T)
        fx = PF.build("P1", ctx.view)
        self.assertEqual(fx["positions"], ())
        self.assertEqual(fx["fixture_refusals"][0]["symbol"], "BTCUSDT")

    def test_degraded_health(self):
        M = R.make_market(health_state="DEGRADED")
        s = snap([R.position("AAAUSDT", 100)], M)
        self.assertEqual(s["liquidity"]["per_position"]["crypto:binance:spot:AAAUSDT"]["spread_bps"]["state"],
                         V.DEGRADED_INPUT)


# ====================================================================== drawdown ======
class TestDrawdown(unittest.TestCase):
    H = 3_600_000

    def curve(self, eq, t0=R.T - 10 * 3_600_000):
        return {"provenance": "SYNTHETIC_TEST_PATH", "points": [(t0 + i * self.H, e, t0 + i * self.H) for i, e in enumerate(eq)]}

    def test_drawdown_and_recovery(self):
        d = DD.drawdown(self.curve([100, 110, 99, 88, 95, 110, 112]), R.T)
        self.assertAlmostEqual(d["max_drawdown"]["value"], 0.2)
        self.assertEqual(d["recovery_time_ms"]["value"], 2 * self.H)
        self.assertEqual(d["current_drawdown"]["value"], 0)
        self.assertEqual(d["current_underwater_ms"]["value"], 0)
        self.assertEqual(d["max_underwater_ms"]["value"], 4 * self.H)
        self.assertAlmostEqual(d["drawdown_velocity_per_day"]["value"], 0.2 / (2 / 24))

    def test_not_recovered_and_current(self):
        d = DD.drawdown(self.curve([100, 90, 80, 85]), R.T)
        self.assertIsNone(d["recovery_time_ms"]["value"])
        self.assertEqual(d["recovery_time_ms"]["reason"], "not_recovered_by_snapshot_time")
        self.assertAlmostEqual(d["current_drawdown"]["value"], 0.15)
        self.assertIn("underwater_censored_at_last_point", d["max_underwater_ms"]["flags"])

    def test_absent_insufficient_refused(self):
        s = snap([])
        self.assertTrue(all(m["value"] is None and m["reason"] == "no_equity_curve_supplied" for m in s["drawdown"].values()))
        d = DD.drawdown(self.curve([100]), R.T)
        self.assertEqual(d["max_drawdown"]["state"], V.INSUFFICIENT_HISTORY)
        with self.assertRaises(PITViolation):
            DD.drawdown(self.curve([100, 90], t0=R.T), R.T)
        with self.assertRaises(DD.DrawdownInputError):
            DD.drawdown({"provenance": "PAPER_R1_EQUITY", "points": []}, R.T)
        with self.assertRaises(DD.DrawdownInputError):
            DD.drawdown({"provenance": "SYNTHETIC_TEST_PATH", "points": [(1, 100, 1), (1, 90, 1)]}, R.T)
        s2 = snap([], equity_curve=self.curve([100, 90, 95]))
        self.assertAlmostEqual(s2["drawdown"]["max_drawdown"]["value"], 0.1)


# ====================================================================== PIT ======
class LeakyMarket(RiskMarket):
    def candles_between(self, sym, tf, lo, hi, t):
        return [c for c in self.candles.get((sym, tf), []) if lo <= c[0] <= hi]


class TestPIT(unittest.TestCase):
    PS = [("BTCUSDT", 2000), ("ETHUSDT", 1000), ("AAAUSDT", 500), ("DDDUSDT", 500)]

    def base(self):
        return snap([R.position(s, n) for s, n in self.PS])

    def test_future_injection_everything_identical(self):
        M = market()
        ref = line(self.base())
        P = PC.poison(M, R.T)
        self.assertEqual(line(snap([R.position(s, n) for s, n in self.PS], P)), ref)
        Tm = PC.truncate(M, R.T)
        self.assertEqual(line(snap([R.position(s, n) for s, n in self.PS], Tm)), ref)

    def test_future_vol_corr_btc_returns_and_universe(self):
        M = market()
        ref = line(self.base())
        E = R.last_open(R.T)
        extra = {}
        for s in R.TIERS:
            fut = [(E + k * R.BAR, 1.0, 1e9, 1e-9, 1e6 * (k % 2 + 1), 1e12, E + (k + 1) * R.BAR - 1, 1.0,
                    E + (k + 1) * R.BAR + 5, False) for k in (1, 2, 3)]
            extra[(s, "15m")] = fut
        cand = {k: sorted(v + extra.get(k, []), key=lambda c: c[0]) for k, v in M.candles.items()}
        late = {"effective_from_ms": R.T0, "available_at_ms": R.T + 1, "universe_id": "late", "kind": "transition",
                "boot8": R.BOOT[:8], "tiers": {s: 2 for s in R.TIERS}}
        S = PC._clone_state(M.state)
        S.epochs = sorted(S.epochs + [late], key=lambda e: (e["effective_from_ms"], e["available_at_ms"]))
        M2 = RiskMarket(S, cand)
        M2.meta = dict(M.meta)
        self.assertEqual(line(snap([R.position(s, n) for s, n in self.PS], M2)), ref)

    def test_positive_control_not_applicable_without_eligible_bar(self):
        t = R.T0 + 390_000
        M = R.make_market(t=t, closes=R.factor_paths(sorted(R.TIERS), 1))
        self.assertIsNone(PC.perturb_past(M, t, "BTCUSDT"))

    def test_positive_control_needs_a_consumer_D_RM0_1(self):
        """D-RM0-1: an eligible past bar that no reported metric consumes (all INSUFFICIENT_HISTORY) cannot change
        the snapshot; the control is then NOT APPLICABLE, not a detection failure."""
        t = R.T0 + 10 * R.BAR + 390_000                            # 9 returns: every BTC-candle metric is null
        M = R.make_market(t=t)
        s = snap([R.position("BTCUSDT", 100, t=t)], M, t=t)
        self.assertIsNotNone(PC.perturb_past(M, t, "BTCUSDT"))
        self.assertEqual(PC.control_consumers(s), [])
        self.assertEqual(line(snap([R.position("BTCUSDT", 100, t=t)], PC.perturb_past(M, t, "BTCUSDT"), t=t)), line(s))
        full = snap([R.position("BTCUSDT", 100)])
        self.assertTrue(PC.control_consumers(full))

    def test_offgrid_closed_not_yet_available_bar(self):
        t = R.T - 390_000 + 30_000                                 # 30 s after a bar close: that bar is not fetched yet
        M = R.make_market(t=t)
        ps = [R.position(s, n, t=t) for s, n in self.PS]
        base = snap(ps, M, t=t)
        self.assertEqual(base["volatility"]["per_position"]["crypto:binance:spot:BTCUSDT"]["sigma_15m_long"]["state"],
                         V.STALE_INPUT)
        self.assertEqual(line(snap(ps, PC.poison(M, t), t=t)), line(base))
        self.assertEqual(line(snap(ps, PC.truncate(M, t), t=t)), line(base))

    def test_positive_control_past_change_detected(self):
        ref = line(self.base())
        M3 = PC.perturb_past(market(), R.T, "BTCUSDT")
        self.assertNotEqual(line(snap([R.position(s, n) for s, n in self.PS], M3)), ref)

    def test_leaky_sources_refused(self):
        E = R.last_open(R.T)
        Mm = R.make_market(missing={(s, E) for s in R.TIERS})     # the bar closed by T is not yet fetched ...
        L = LeakyMarket(Mm.state, PC.poison(Mm, R.T).candles)    # ... and a leaky source returns its later fetch
        with self.assertRaises(PITViolation):
            snap([R.position("BTCUSDT", 100)], L)
        self.assertEqual(line(snap([R.position("BTCUSDT", 100)], PC.poison(Mm, R.T))),
                         line(snap([R.position("BTCUSDT", 100)], Mm)))
        M = market()
        S = PC._clone_state(M.state)
        st = S.book["BTCUSDT"]
        r = list(st.recs[-1])
        r[0] = R.T + 5
        st.recs[-1] = tuple(r)                                    # key <= T but available after T
        with self.assertRaises(PITViolation):
            snap([R.position("BTCUSDT", 100)], RiskMarket(S, M.candles))

    def test_view_refuses_future_access_and_positions(self):
        v = RiskView(market(), R.T)
        with self.assertRaises(PITViolation):
            v.closed_candles("BTCUSDT", "15m", 0, R.T + R.BAR)
        with self.assertRaises(PITViolation):
            snap([R.position("BTCUSDT", 100, t=R.T + 1)])
        with self.assertRaises(PITViolation):
            snap([R.position("BTCUSDT", 100, reference_time_ms=R.T + 1, decision_time_ms=R.T + 1)])

    def test_w3(self):
        with self.assertRaises(LG.W3SealedError):
            RiskView(market(), ms("2026-10-04T15:00:00Z"))
        with self.assertRaises(LG.W3SealedError):
            RiskView(market(), ms("2026-10-04T15:26:43Z"))
        RiskView(market(), ms("2026-10-04T15:26:44Z"))
        from p2_research.risk.market import w3_masked
        e = ms("2026-10-04T15:26:43Z") + 497
        self.assertTrue(w3_masked(ms("2026-10-04T15:15:00Z"), ms("2026-10-04T15:29:59Z") + 999))
        self.assertTrue(w3_masked(e - 1, e + 10))
        self.assertFalse(w3_masked(ms("2026-10-04T15:30:00Z"), ms("2026-10-04T15:44:59Z") + 999))
        closes = R.factor_paths(sorted(R.TIERS), 30)
        cand = R.candles_from(closes, start_open=ms("2026-10-04T14:30:00Z"))
        M = R.make_market(t=ms("2026-10-04T21:06:30Z"), closes=closes)
        M = RiskMarket(M.state, cand)
        v = RiskView(M, ms("2026-10-04T21:06:30Z"))
        bars, masked = v.closed_candles("BTCUSDT", "15m", 0, ms("2026-10-04T21:00:00Z"))
        self.assertEqual(masked, 4)                                 # 14:30, 14:45, 15:00, 15:15 overlap W3
        self.assertEqual(min(bars), ms("2026-10-04T15:30:00Z"))


# ====================================================================== determinism / reference / fixtures ======
class TestDeterminismReference(unittest.TestCase):
    def test_byte_identical_and_order_invariant(self):
        ps = [R.position(s, 100 * (i + 1)) for i, s in enumerate(("BTCUSDT", "ETHUSDT", "AAAUSDT", "GGGUSDT"))]
        a, b = snap(ps), snap(list(reversed(ps)))
        self.assertEqual(line(a), line(b))
        self.assertEqual(a["snapshot_id"], b["snapshot_id"])
        c = SN.build_snapshot(R.make_market(), ps, R.T)            # an independently rebuilt market
        self.assertEqual(line(a), line(c))
        body = {k: v for k, v in a.items() if k != "snapshot_id"}
        self.assertEqual(a["snapshot_id"], V.sha256_text(V.canon(body)))
        V.check_tree(a)
        self.assertEqual(sorted(a), sorted(RC.default().schema["required_blocks"]))

    def test_reference_agreement_all_fixtures(self):
        M, C = market(), RC.default()
        ctx = SN.Context(M, R.T)
        for pid in C.plan["portfolios"]:
            fx = PF.build(pid, ctx.view)
            s = SN.build_snapshot(ctx, fx["positions"])
            rv = REF.metrics(M.candles, [(p["symbol"], p["signed_notional"]) for p in s["positions"]], R.T,
                             RDT._ref_params(C))
            self.assertEqual(REF.compare(rv, REF.snapshot_values(s)), [], pid)

    def test_reference_detects_difference(self):
        s = snap([R.position("BTCUSDT", 100), R.position("ETHUSDT", 100)])
        sv = REF.snapshot_values(s)
        sv["rho.BTCUSDT|ETHUSDT"] += 1e-6
        rv = REF.metrics(market().candles, [("BTCUSDT", 100.0), ("ETHUSDT", 100.0)], R.T, RDT._ref_params(RC.default()))
        self.assertEqual(len(REF.compare(rv, sv)), 1)

    def test_fixture_rules(self):
        ctx = SN.Context(R.make_market(depth_qty={"HHHUSDT": 0.1, "EEEUSDT": 0.2, "IIIUSDT": 0.3}), R.T)
        got = {pid: [p.symbol for p in PF.build(pid, ctx.view)["positions"]] for pid in RC.default().portfolios}
        self.assertEqual(got["P0"], [])
        self.assertEqual(got["P1"], ["BTCUSDT"])
        self.assertEqual(got["P2"], ["AAAUSDT", "BBBUSDT", "BTCUSDT", "CCCUSDT", "ETHUSDT"])
        self.assertEqual(sorted(got["P5"]), ["DDDUSDT", "EEEUSDT", "FFFUSDT", "GGGUSDT", "HHHUSDT"])
        self.assertNotIn("BTCUSDT", got["P5"])
        self.assertEqual(sorted(got["P6"]), ["EEEUSDT", "HHHUSDT", "IIIUSDT"])
        self.assertEqual(len(got["P7"]), 9)
        p3 = PF.build("P3", ctx.view)["positions"]
        self.assertEqual(max(p3, key=lambda p: p.notional).symbol, "ETHUSDT")
        s7 = SN.build_snapshot(ctx, PF.build("P7", ctx.view)["positions"])
        ref = s7["exposure"]["count_references_documented_only"]
        self.assertEqual(ref["paper_nominal_max_open_trades"]["headroom"], 1)
        self.assertEqual(ref["paper_effective_max_open"]["headroom"], -7)

    def test_fixtures_never_use_returns(self):
        src = _read(os.path.join(RISK_DIR, "portfolios.py"))
        for name in ("closed_candles", "series", "stats", "candles"):
            self.assertNotIn(name, src)


# ====================================================================== sealed-dataset end to end ======
class TestSealedDatasetEndToEnd(unittest.TestCase):
    def test_load_snapshot_pit_and_refusals(self):
        base = CM.base_dataset()
        t = ms("2026-10-06T10:06:30Z")
        M = load_risk_market(base, [CM.D1, CM.D2], query_times=[t])
        self.assertTrue(M.candles)
        ctx = SN.Context(M, t)
        out = {}
        for pid in ("P0", "P1", "P2", "P7"):
            fx = PF.build(pid, ctx.view)
            out[pid] = line(SN.build_snapshot(ctx, fx["positions"]))
        for MM in (PC.truncate(M, t), PC.poison(M, t)):
            c2 = SN.Context(MM, t)
            for pid in out:
                self.assertEqual(line(SN.build_snapshot(c2, PF.build(pid, c2.view)["positions"])), out[pid], pid)
        M2 = load_risk_market(base, [CM.D1, CM.D2], query_times=[t])
        c3 = SN.Context(M2, t)
        self.assertEqual(line(SN.build_snapshot(c3, PF.build("P7", c3.view)["positions"])), out["P7"])
        d = CM.copy_dataset("rm0-unsealed")
        os.remove(os.path.join(d, "seals", f"{CM.D2}.json"))
        with self.assertRaises(RD.NotSealed):
            load_risk_market(d, [CM.D1, CM.D2], query_times=[t])

    def test_realdata_plan_guards(self):
        C = RC.default()
        Ts = RDT.plan_times(C, ["2026-10-04", "2026-10-05"])
        self.assertEqual(len(Ts), 14)
        self.assertEqual(sum(1 for t in Ts if (t - 390_000) % 900_000), 2)
        self.assertTrue(all(t * 1000 >= LG.W3_END.timestamp() * 1e6 for t in Ts))
        with self.assertRaises(RDT.PlanError):
            RDT.plan_times(C, ["2026-10-05", "2026-10-06"])
        with self.assertRaises(RDT.PlanError):
            RDT.run("/nonexistent", ["2026-10-04", "2026-10-05"],
                    "/home/tradmin/research-data/trading-signal-bot/p2/x", "test")


if __name__ == "__main__":
    unittest.main()
