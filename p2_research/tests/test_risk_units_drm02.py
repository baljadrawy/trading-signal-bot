"""D-RM0-2 regression: portfolio aggregates must never silently mix quote currencies (RM0-UNITS 1.1.0).

Synthetic markets only (no real data, no W3). These tests fail on 9c7b750 and pass after the repair.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from p2_research.risk import contracts as RC
from p2_research.risk import portfolios as PF
from p2_research.risk import reference as REF
from p2_research.risk import snapshot as SN
from p2_research.risk import values as V
from p2_research.tests import rm0_synth as R

MIXED = "mixed_quote_currencies_no_fx_conversion"
CAPMIS = "capital_currency_mismatch_no_fx_conversion"
TIERS = dict(R.TIERS, ETHBTC=1, BTCFDUSD=1, ETHFDUSD=2)
# Cross-position monetary / notional-weighted aggregates (the audit list). Unitless per-instrument values,
# unweighted correlation, counts, regime and drawdown are not in this list.
AGG = ("exposure.gross", "exposure.net", "exposure.long", "exposure.short", "exposure.mark_to_market_net_at_t",
       "heat.measured_exposure_gross", "heat.exposure_heat", "heat.vol_heat", "concentration.",
       "volatility.notional_weighted_sigma_1d", "volatility.high_vol_notional_share", "volatility.portfolio_vol_proxy.",
       "correlation.average_pairwise_weighted", "btc_exposure.direct_btc_weight",
       "btc_exposure.weighted_correlation_with_btc", "btc_exposure.portfolio_beta_to_btc",
       "btc_exposure.btc_beta_equivalent_notional", "liquidity.notional_", "liquidity.weak_liquidity_share",
       "liquidity.weighted_spread_bps", "liquidity.half_spread_cost_ccy_total", "risk_contribution.",
       "diversification.components.effective_n_notional", "diversification.components.largest_share",
       "diversification.components.average_pairwise_correlation_weighted", "diversification.components.direct_btc_weight",
       "diversification.components.portfolio_beta_to_btc", "diversification.components.weighted_correlation_with_btc",
       "diversification.components.high_vol_notional_share", "diversification.components.weak_liquidity_share",
       "diversification.components.diversification_ratio")
ALLOWED_FLAGS = {"RM0-S-MIXED-QUOTE-CURRENCIES", "RM0-P-VOL-SPIKE", "RM0-P-HIGH-VOL", "RM0-S-SHORT-CONCEPTUAL-NOT-AUTHORIZED"}
_M = None


def mkt():
    global _M
    if _M is None:
        _M = R.make_market(tiers=TIERS)
    return _M


def snap(ps, **kw):
    return SN.build_snapshot(mkt(), ps, R.T, **kw)


def valid_aggregates(s):
    return [p for p, m in V.walk_metrics(s) if m["value"] is not None and any(p.startswith("$." + a) for a in AGG)]


class TestMixedQuoteFailsClosed(unittest.TestCase):
    def _assert_closed(self, s):
        self.assertEqual(valid_aggregates(s), [])
        self.assertIsNone(s["heat"]["exceeds_hypothetical_capital"])
        self.assertTrue({f["id"] for f in s["flags"]} <= ALLOWED_FLAGS, s["flags"])
        self.assertIn("RM0-S-MIXED-QUOTE-CURRENCIES", {f["id"] for f in s["flags"]})
        for p in ("exposure", "heat", "concentration"):
            for k, m in s[p].items():
                if V.is_metric(m) and m["value"] is None and k not in ("hypothetical_capital",):
                    self.assertIn(m["reason"], (MIXED, "flat_portfolio"), (p, k))

    def test_btcusdt_plus_ethbtc_demo(self):
        s = snap([R.position("BTCUSDT", 5000), R.position("ETHBTC", 0.5, px=0.03)])
        self._assert_closed(s)
        self.assertEqual(s["exposure"]["by_quote_currency"]["USDT"]["gross"]["value"], 5000.0)   # partition stays valid
        self.assertEqual(s["exposure"]["by_quote_currency"]["BTC"]["gross"]["value"], 0.5)
        self.assertEqual(s["btc_exposure"]["direct_btc_notional"]["value"], 5000.0)             # single-quote subset

    def test_three_quotes(self):
        self._assert_closed(snap([R.position("BTCUSDT", 1000), R.position("ETHBTC", 0.2, px=0.03),
                                  R.position("BTCFDUSD", 800)]))

    def test_vanishing_second_quote_is_still_mixed(self):
        self._assert_closed(snap([R.position("BTCUSDT", 5000), R.position("ETHBTC", 1e-6, px=0.03)]))

    def test_stablecoins_are_distinct_units(self):
        s = snap([R.position("BTCUSDT", 1000), R.position("BTCFDUSD", 1000)])
        self._assert_closed(s)
        self.assertIsNone(s["btc_exposure"]["direct_btc_notional"]["value"])                   # BTC subset spans quotes

    def test_mixed_bucket_in_tier_breakdown_refused(self):
        s = snap([R.position("BTCUSDT", 1000), R.position("ETHBTC", 0.2, px=0.03)])
        for b in s["exposure"]["by_venue"].values():
            self.assertIsNone(b["gross"]["value"])
        # acceptance gap 1: tier buckets are single-quote here (tier0 USDT, tier1 BTC) but unlabelled -> refused
        tiers = s["exposure"]["by_tier"]
        self.assertGreaterEqual(len(tiers), 2)
        for b in tiers.values():
            for k in ("gross", "net"):
                self.assertIsNone(b[k]["value"])
                self.assertEqual(b[k]["reason"], MIXED)
                self.assertEqual(b[k]["class"], V.UNAVAILABLE)
            self.assertIsInstance(b["count"], int)                                   # non-monetary count kept
        for b in s["exposure"]["by_quote_currency"].values():                        # the valid partition
            self.assertIsNotNone(b["gross"]["value"])

    def test_single_quote_tier_breakdown_still_valid(self):
        s = snap([R.position("BTCUSDT", 1000), R.position("AAAUSDT", 500)])
        self.assertTrue(all(b["gross"]["value"] is not None for b in s["exposure"]["by_tier"].values()))

    def test_realdata_feeds_quote_currency_to_reference(self):
        """acceptance gap 2: the real-data validation call passes (symbol, signed_notional, quote_currency)."""
        import inspect
        from p2_research.risk import realdata as RDT
        src = inspect.getsource(RDT)
        self.assertIn('(p["symbol"], p["signed_notional"], p["quote_currency"])', src)
        s = snap([R.position("BTCUSDT", 5000), R.position("ETHBTC", 0.5, px=0.03)])
        P = {"lookback": 96, "min_obs_long": 48, "min_obs_corr": 48, "bar_ms": 900_000, "btc_symbol": "BTCUSDT"}
        rv = REF.metrics({}, [(p["symbol"], p["signed_notional"], p["quote_currency"]) for p in s["positions"]], R.T, P)
        self.assertEqual(REF.compare({k: rv[k] for k in ("exposure.gross", "exposure.net")},
                                     {k: REF.snapshot_values(s)[k] for k in ("exposure.gross", "exposure.net")}), [])
        self.assertIsNone(rv["exposure.gross"])


class TestSingleQuote(unittest.TestCase):
    def test_single_non_usdt_book_consistent_but_capital_ratio_refused(self):
        s = snap([R.position("ETHBTC", 0.5, px=0.03)])
        self.assertEqual(s["exposure"]["gross"]["value"], 0.5)
        self.assertIsNotNone(s["concentration"]["hhi"]["value"])
        self.assertIsNone(s["heat"]["exposure_heat"]["value"])
        self.assertEqual(s["heat"]["exposure_heat"]["reason"], CAPMIS)
        self.assertIsNone(s["heat"]["exceeds_hypothetical_capital"])

    def test_single_non_usdt_book_with_matching_capital(self):
        cap = {"value": 1.0, "currency": "BTC", "provenance": RC.default().capital["provenance_required"]}
        s = snap([R.position("ETHBTC", 0.5, px=0.03)], capital=cap)
        self.assertEqual(s["heat"]["exposure_heat"]["value"], 0.5)
        self.assertIs(s["heat"]["exceeds_hypothetical_capital"], False)

    def test_flat_book_unchanged_semantics(self):
        s = snap([])
        self.assertEqual(s["exposure"]["gross"]["value"], 0.0)
        self.assertIs(s["heat"]["exceeds_hypothetical_capital"], False)


class TestReferenceRefusesIndependently(unittest.TestCase):
    def test_reference_mixed(self):
        P = {"lookback": 96, "min_obs_long": 48, "min_obs_corr": 48, "bar_ms": 900_000, "btc_symbol": "BTCUSDT"}
        out = REF.metrics({}, [("BTCUSDT", 5000.0, "USDT"),
                                                                              ("ETHBTC", 0.5, "BTC")], R.T, P)
        self.assertIsNone(out["exposure.gross"])
        self.assertIsNone(out["concentration.hhi"])
        out2 = REF.metrics({}, [("BTCUSDT", 5000.0, "USDT"), ("ETHUSDT", 1000.0, "USDT")], R.T, P)
        self.assertEqual(out2["exposure.gross"], 6000.0)


class TestContractsAndHistory(unittest.TestCase):
    def test_amendment_frozen_and_base_unchanged(self):
        self.assertEqual(RC.default().sha256[:8], "9d9faaf6")
        self.assertEqual(len(RC.units_amendment_sha256()), 64)

    def test_usdt_only_outputs_identical_to_9c7b750_except_provenance(self):
        """USDT-only P0-P7 fixtures: the repair must not change any value (only contracts block + snapshot_id)."""
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        prog = ("import json,sys\n"
                "from p2_research.risk import snapshot as SN, portfolios as PF, contracts as RC\n"
                "from p2_research.tests import rm0_synth as R\n"
                "M=R.make_market(); ctx=SN.Context(M,R.T); out={}\n"
                "for pid in sorted(RC.default().portfolios):\n"
                "  fx=PF.build(pid,ctx.view); s=SN.build_snapshot(ctx,fx['positions'],R.T)\n"
                "  s.pop('snapshot_id'); s.pop('contracts'); out[pid]=SN.canonical_line(s)\n"
                "print(json.dumps(out))\n")

        def run(r):
            p = subprocess.run([sys.executable, "-c", prog], cwd=r, capture_output=True, text=True, timeout=300,
                               env=dict(os.environ, PYTHONPATH=r, PYTHONHASHSEED="0"))
            self.assertEqual(p.returncode, 0, p.stderr[-2000:])
            return json.loads(p.stdout)
        with tempfile.TemporaryDirectory() as td:
            g = subprocess.run(f"git -C {root} archive 9c7b750 p2_research | tar -x -C {td}", shell=True)
            self.assertEqual(g.returncode, 0)
            old, new = run(td), run(root)
        self.assertEqual(sorted(old), sorted(new))
        for pid in old:
            self.assertEqual(old[pid], new[pid], pid)


if __name__ == "__main__":
    unittest.main()
