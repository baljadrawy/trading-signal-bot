"""P2-X0 execution & cost model tests (synthetic market states; no real data, no W3, no Paper)."""
import copy
import hashlib
import json
import os
import random
import shutil
import tempfile
import unittest

from p2_research import instrument as IN, labels as LB, ledger as LG
from p2_research.execution import contracts as CT, model as M, quality as QL
from p2_research.execution.market_state import ForwardMarketState, PITMarketView, PITViolation, load_sealed
from p2_research.execution.schema import (ASSUMED, DEGRADED, DERIVED, ESTIMATED, INVALID, MEASURED, UNAVAILABLE,
                                          VALID, check_quantity_tree, canon)
from p2_research.tests import common as C
from p2_research.tests.synth import ms

BTC = IN.binance_spot_instrument("BTCUSDT")
ALT = IN.binance_spot_instrument("AAAUSDT")
T0 = ms("2026-10-05T01:00:00Z")                     # run start (after W3)
T = T0 + 3_600_000                                  # decision time used by most tests
BOOT = "ab" * 16
STALE = {"book_t0": 120_000, "book_t12_dead": 600_000, "book_t12_suspect": 120_000, "depth": 2_000,
         "depth_by_tier": {"t0": 2_000, "t1": 180_000, "t2": 15_000}, "market": 10_000}
RUN = {"boot_id": BOOT, "boot8": BOOT[:8], "ws_start_ms": T0, "end_ms": None, "stale_ms": STALE,
       "cadence_ms": {"t0_book": 1000, "t0_depth": 1000, "t1_book": 10000, "t1_depth": 60000}}


def _sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _dump(o, p):
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(o, fh, indent=1)


def book(t_obs, sample, bid, ask, tier=0, cad=1000, seq=None, unchanged=False, cs=False, boot8=BOOT[:8], bq=1.0, aq=1.0):
    return (t_obs, sample, t_obs, bid, ask, bq, aq, seq if seq is not None else sample, unchanged, cs, tier, cad, boot8)


def ladder(p0, step, n, qty, sign):
    return tuple((p0 + sign * i * step, qty) for i in range(n))


def depth(t_obs, sample, bid0, ask0, n=20, qty=0.01, step=1.0, tier=0, cad=1000, seq=None, boot8=BOOT[:8], cs=False):
    return (t_obs, sample, t_obs, ladder(bid0, step, n, qty, -1), ladder(ask0, step, n, qty, +1), n,
            seq if seq is not None else sample, False, cs, tier, cad, boot8)


def grid_state(sym="BTCUSDT", start=T0, end=T + 120_000, cad=1000, tier=0, bid=100.0, ask=100.02, dcad=1000,
               extra_book=(), extra_depth=(), health=None, lifecycle=(), clock=(), gaps=(), drop=None, dqty=0.01,
               runs=None):
    """Book + depth every cadence from ``start`` (observed 100 ms before each boundary), constant prices."""
    bk, dp = [], []
    for s in range(start + cad, end + 1, cad):
        if drop and drop[0] <= s <= drop[1]:
            continue
        bk.append((sym, book(s - 100, s, bid, ask, tier=tier, cad=cad, seq=s)))
    for s in range(start + dcad, end + 1, dcad):
        if drop and drop[0] <= s <= drop[1]:
            continue
        dp.append((sym, depth(s - 100, s, bid, ask, qty=dqty, step=0.01, tier=tier, cad=dcad, seq=s - 1)))
    bk += [(sym, r) for r in extra_book]
    dp += [(sym, r) for r in extra_depth]
    hl = health if health is not None else [(h, "HEALTHY", frozenset(), ()) for h in range(start + 1000, end, 60_000)]
    return ForwardMarketState.from_records(book=bk, depth=dp, runs=runs or [RUN], health=hl, lifecycle=lifecycle,
                                           clock=clock, gaps=gaps, meta={"dataset_id": "synthetic-x0"})


def est(state, side="buy", scenario="EXEC-IDEALIZED", notional=50.0, t=T, inst=BTC, **kw):
    return M.estimate_leg(state, inst, side, notional, t, scenario, **kw)


class TestTouchAndCosts(unittest.TestCase):
    def test_buy_uses_ask_sell_uses_bid(self):
        S = grid_state()
        b, s = est(S, "buy"), est(S, "sell")
        self.assertEqual((b["touch"]["value"], b["fill"]["value"]), (100.02, 100.02))
        self.assertEqual((s["touch"]["value"], s["fill"]["value"]), (100.0, 100.0))
        self.assertEqual((b["leg"], s["leg"]), ("entry", "exit"))
        self.assertEqual(b["touch"]["provenance"], MEASURED)
        self.assertEqual(b["mid"]["provenance"], DERIVED)
        self.assertNotEqual(b["fill"]["value"], b["decision_mid"]["value"])      # never silently the decision price

    def test_spread_decomposition_exact(self):
        S = grid_state()
        for side in ("buy", "sell"):
            for sc in ("EXEC-IDEALIZED", "EXEC-BASE", "EXEC-STRESS"):
                e = est(S, side, sc, notional=5.0)
                mid = 100.01
                self.assertAlmostEqual(e["spread_bps"]["value"], 0.02 / mid * 1e4, places=9)
                self.assertAlmostEqual(e["spread_cost_bps"]["value"], 0.01 / mid * 1e4, places=9)
                parts = sum(e[k]["value"] for k in ("spread_cost_bps", "slippage_bps", "fee_bps", "interaction_bps"))
                self.assertAlmostEqual(parts, e["total_cost_bps"]["value"], places=8)
                sg = 1 if side == "buy" else -1
                eff = e["fill"]["value"] * (1 + sg * e["fee_bps"]["value"] / 1e4)
                self.assertAlmostEqual(e["total_cost_bps"]["value"], sg * (eff - mid) / mid * 1e4, places=6)
                self.assertLess(abs(e["interaction_bps"]["value"]), 0.1)

    def test_fees_versioned_assumption(self):
        e = est(grid_state())
        self.assertEqual(e["fee_bps"], {"value": 10.0, "provenance": ASSUMED, "reason": None})
        self.assertEqual(e["fee_bps"]["value"], LB.FEE_BPS_PER_SIDE)              # reconciled with P2-C labels
        self.assertEqual(e["models"]["fee_schedule"], {"id": "X0-FEE-BINANCE-SPOT-STD", "version": "1.0.0"})
        self.assertEqual(e["cost_provenance"], ASSUMED)                         # never presented as measured
        fs = CT.default().fee_schedule("X0-FEE-BINANCE-SPOT-STD")
        self.assertTrue(all(x["provenance"] == ASSUMED for x in fs["entries"]))
        with self.assertRaises(CT.ContractError):
            CT.fee_rate_bps(fs, "binance", "futures", "taker")

    def test_zero_slippage_baseline(self):
        e = est(grid_state(), "buy", "EXEC-IDEALIZED")
        self.assertEqual(e["slippage_bps"], {"value": 0.0, "provenance": ASSUMED, "reason": None})
        self.assertEqual(e["fill"]["value"], e["touch"]["value"])
        self.assertEqual(e["latency_ms"]["value"], 0)
        self.assertEqual(e["execution_time_ms"], e["decision_time_ms"])
        self.assertEqual([m["id"] for m in e["models"]["slippage"]], ["X0-S0"])

    def test_explicit_stress(self):
        S = grid_state(dqty=1.0)
        base, stress = est(S, "buy", "EXEC-BASE", notional=5.0), est(S, "buy", "EXEC-STRESS", notional=5.0)
        self.assertEqual(base["slippage_bps"]["provenance"], ESTIMATED)
        self.assertEqual(stress["slippage_bps"]["provenance"], ASSUMED)          # weakest of walk + fixed add-on
        self.assertAlmostEqual(stress["slippage_bps"]["value"] - base["slippage_bps"]["value"], 10.0, places=9)
        self.assertAlmostEqual(stress["fill"]["value"], 100.02 * (1 + 10 / 1e4), places=9)
        s1 = {m["id"]: m["bps_per_side"] for m in CT.default().docs["models_v1.json"]["slippage_models"] if m["kind"] == "fixed_stress"}
        self.assertEqual(s1, {"X0-S1-ZERO": 0.0, "X0-S1-LOW": 5.0, "X0-S1-MODERATE": 10.0, "X0-S1-SEVERE": 25.0})
        self.assertEqual(sorted(CT.default().scenarios), ["EXEC-BASE", "EXEC-IDEALIZED", "EXEC-STRESS"])

    def test_unavailable_never_zero_and_schema(self):
        S = grid_state()
        for sc in CT.default().scenarios:
            for side in ("buy", "sell"):
                e = est(S, side, sc)
                check_quantity_tree(e)
                for k in ("adverse_selection_bps", "market_impact_bps", "gross_return", "net_return"):
                    self.assertEqual(e[k]["provenance"], UNAVAILABLE)
                    self.assertIsNone(e[k]["value"])
                fields = [f for f, _ in CT.default().docs["result_schema_v1.json"]["leg_fields"]]
                self.assertEqual(sorted(fields), sorted(e))
        e = est(grid_state(end=T0 + 5_000), "buy", "EXEC-BASE")                 # no book at T at all
        for k in ("fill", "touch", "total_cost_bps", "slippage_bps", "spread_bps"):
            self.assertIsNone(e[k]["value"])
            self.assertEqual(e[k]["provenance"], UNAVAILABLE)
            self.assertTrue(e[k]["reason"])
        self.assertEqual(e["cost_provenance"], UNAVAILABLE)

    def test_round_trip(self):
        S = grid_state()
        a, b = est(S, "buy", "EXEC-BASE", notional=5.0), est(S, "sell", "EXEC-BASE", notional=5.0, t=T + 60_000)
        rt = M.round_trip(a, b)
        eff_in = a["fill"]["value"] * 1.001
        eff_out = b["fill"]["value"] * 0.999
        self.assertAlmostEqual(rt["net_return"]["value"], eff_out / eff_in - 1, places=12)
        self.assertEqual(rt["gross_return"]["value"], 0.0)                      # constant mid
        self.assertLess(rt["net_return"]["value"], 0)
        self.assertEqual(rt["net_return"]["provenance"], ASSUMED)
        bad = est(grid_state(end=T + 30_000), "sell", "EXEC-BASE", t=T + 60_000)   # exit book missing
        self.assertEqual(M.round_trip(a, bad)["net_return"]["provenance"], UNAVAILABLE)
        with self.assertRaises(M.ExecutionError):
            M.round_trip(b, a)

    def test_short_and_other_markets_refused(self):
        S = grid_state()
        with self.assertRaises(M.UnsupportedDirection):
            est(S, direction="short")
        fake = IN.Instrument(asset_class="equity", venue="nyse", product="cash", instrument_id="equity:nyse:cash:IBM",
                             symbol="IBM", base_currency="IBM", quote_currency="USD", settlement_currency="USD",
                             calendar_id="crypto-24x7-utc")
        with self.assertRaises(IN.UnsupportedMarket):
            est(S, inst=fake)
        with self.assertRaises(M.ExecutionError):
            est(S, notional=0)


class TestStalenessAndQuality(unittest.TestCase):
    def test_stale_quote_fails_closed(self):
        # tier-1 book (cadence 10 s), quote received long ago and held (unchanged) every boundary
        held = [book(T0 + 500, s, 50.0, 50.1, tier=1, cad=10_000, seq=7, unchanged=True) for s in range(T0 + 10_000, T + 1, 10_000)]
        S = ForwardMarketState.from_records(book=[("AAAUSDT", r) for r in held], runs=[RUN],
                                            health=[(T - 30_000, "HEALTHY", frozenset(), ())])
        e = est(S, inst=ALT)                                                     # age ~ 1 h > 600 s dead limit
        self.assertEqual(e["data_quality"]["state"], INVALID)
        self.assertEqual(e["data_quality"]["book"]["staleness"], "TOO_STALE")
        self.assertIsNone(e["fill"]["value"])
        self.assertEqual(e["fill"]["provenance"], UNAVAILABLE)
        # 200 s old (> 120 s suspect, <= 600 s dead): degraded but estimated
        held2 = [book(T - 200_000, s, 50.0, 50.1, tier=1, cad=10_000, seq=7) for s in range(T - 190_000, T + 1, 10_000)]
        S2 = ForwardMarketState.from_records(book=[("AAAUSDT", r) for r in held2], runs=[RUN],
                                             health=[(T - 30_000, "HEALTHY", frozenset(), ())])
        e2 = est(S2, inst=ALT)
        self.assertEqual(e2["data_quality"]["state"], DEGRADED)
        self.assertIn("book_age_degraded", e2["data_quality"]["book"]["flags"])
        self.assertEqual(e2["fill"]["value"], 50.1)
        self.assertEqual(e2["market_data_age"]["book_quote_age_ms"]["value"], 200_000)

    def test_missing_quote_and_confirmation(self):
        e = est(grid_state(drop=(T - 10_000, T + 10_000)))                      # boundaries missing around T
        self.assertEqual(e["data_quality"]["state"], INVALID)
        self.assertIn("book_stream_missing", e["data_quality"]["book"]["flags"])
        self.assertIsNone(e["fill"]["value"])
        e = est(grid_state(drop=(T - 1_500, T)))                                 # one-two boundaries missing
        self.assertEqual(e["data_quality"]["book"]["confirmation"], DEGRADED)
        self.assertEqual(e["data_quality"]["state"], DEGRADED)
        run2 = dict(RUN, end_ms=T - 10_000)                                       # downtime at T
        e = est(grid_state(runs=[run2]))
        self.assertIn("no_run_at_time", e["data_quality"]["book"]["flags"])
        self.assertIsNone(e["fill"]["value"])
        new = dict(RUN, boot_id="cd" * 16, boot8="cd" * 4, ws_start_ms=T - 1000, end_ms=None)
        e = est(grid_state(runs=[dict(RUN, end_ms=T - 2000), new]))               # record from the previous boot
        self.assertIn("from_previous_run", e["data_quality"]["book"]["flags"])
        self.assertIsNone(e["fill"]["value"])

    def test_gap_and_data_quality_failures(self):
        hl = [(T - 20_000, "DEGRADED", frozenset({"btcusdt@bookTicker"}), ("stream_stale",))]
        S = grid_state(health=hl, drop=(T - 25_000, T + 5_000), extra_book=[book(T - 25_500, T - 25_000, 100.0, 100.02)])
        e = est(S)
        self.assertEqual(e["data_quality"]["state"], INVALID)
        self.assertIn("stream_not_observing", e["data_quality"]["book"]["flags"])
        S = grid_state(health=hl)                                                # stream recovered after the record
        e = est(S)
        self.assertIn("stream_recovered_after_not_observing", e["data_quality"]["book"]["flags"])
        self.assertIn("collector_not_healthy", e["data_quality"]["book"]["flags"])
        self.assertEqual(e["data_quality"]["state"], DEGRADED)
        crossed = grid_state(bid=100.02, ask=100.02)
        e = est(crossed)
        self.assertIn("crossed_or_locked_book", e["data_quality"]["book"]["flags"])
        self.assertIsNone(e["fill"]["value"])
        ev = [(T - 50, "ws_rotation", {"conn": "conn0-book"}, BOOT[:8])]          # quote observed before rotation
        e = est(grid_state(lifecycle=ev))
        self.assertIn("quote_predates_connection_event", e["data_quality"]["book"]["flags"])
        self.assertEqual(e["market_data_age"]["connection_event_age_ms"]["value"], 50)
        e = est(grid_state(lifecycle=[(T - 50, "ws_rotation", {"conn": "conn1-depth"}, BOOT[:8])]))
        self.assertNotIn("quote_predates_connection_event", e["data_quality"]["book"]["flags"])
        e = est(grid_state(clock=[(T - 1000, 0, True)]))
        self.assertIn("clock_suspect", e["data_quality"]["book"]["flags"])
        g = {"available_at_ms": T - 600_000, "stream_key": "book|BTCUSDT", "first_missing_ms": T - 900_000,
             "last_missing_ms": T - 700_000, "end_ms": T - 699_000, "cadence_ms": 1000, "cause": "stale_stream"}
        e = est(grid_state(gaps=[g]))
        self.assertIn("gap_known_1h", e["data_quality"]["book"]["flags"])
        self.assertEqual(e["data_quality"]["state"], VALID)                      # informational only
        e = est(grid_state(health=[]))
        self.assertIn("no_health_record_in_run", e["data_quality"]["book"]["flags"])

    def test_limits_come_from_run_record(self):
        self.assertEqual(QL.limits(RUN, "book", 0), (120_000, 120_000))
        self.assertEqual(QL.limits(RUN, "book", 1), (600_000, 120_000))
        self.assertEqual(QL.limits(RUN, "depth", 1), (180_000, None))
        r = dict(RUN, stale_ms=dict(STALE, book_t12_dead=300_000))
        self.assertEqual(QL.limits(r, "book", 2), (300_000, 120_000))


class TestPIT(unittest.TestCase):
    def test_future_data_rejected(self):
        S = grid_state()
        ref = est(S, "buy", "EXEC-BASE")
        fut_b = [book(T + 1001 + i, T + 2000 + i * 1000, 1.0, 1.01, seq=10**12 + i) for i in range(30)]
        fut_d = [depth(T + 1001 + i, T + 2000 + i * 1000, 1.0, 1.01, qty=10**6, seq=10**12 + i) for i in range(30)]
        hl = [(h, "HEALTHY", frozenset(), ()) for h in range(T0 + 1000, T + 120_000, 60_000)]
        hl += [(T + 1500, "DEGRADED", frozenset({"btcusdt@bookTicker"}), ())]
        lc = [(T + 1200, "ws_rotation", {"conn": "conn0-book"}, BOOT[:8])]
        g = [{"available_at_ms": T + 1300, "stream_key": "book|BTCUSDT", "first_missing_ms": T - 5000,
              "last_missing_ms": T - 4000, "end_ms": T - 3000, "cadence_ms": 1000, "cause": "stale_stream"}]
        bk = [(s, r) for s, st in S.book.items() for r in st.recs if r[0] <= T + 1000] + [("BTCUSDT", r) for r in fut_b]
        dp = [(s, r) for s, st in S.depth.items() for r in st.recs if r[0] <= T + 1000] + [("BTCUSDT", r) for r in fut_d]
        S2 = ForwardMarketState.from_records(book=bk, depth=dp, runs=[RUN], health=hl, lifecycle=lc, gaps=g,
                                             meta={"dataset_id": "synthetic-x0"})
        self.assertEqual(est(S2, "buy", "EXEC-BASE"), ref)                        # identical, incl. estimate_id
        V = PITMarketView(S, T + 1000)
        with self.assertRaises(PITViolation):
            V.book("BTCUSDT", T + 1001)
        with self.assertRaises(PITViolation):
            V.depth("BTCUSDT", T + 5000)

    def test_faulty_source_cannot_leak_future(self):
        class Leaky(ForwardMarketState):
            def latest(self, kind, sym, t):
                r = super().latest(kind, sym, t + 10_000)                        # a buggy adapter returning the future
                return r
        S = grid_state()
        L = Leaky.from_records(book=[(s, r) for s, st in S.book.items() for r in st.recs], runs=[RUN],
                               health=S.health)
        with self.assertRaises(PITViolation):
            est(L, "buy", "EXEC-IDEALIZED")

    def test_latency_semantics(self):
        # price steps up at boundary T+600 (observed T+500): visible to execution at T+1000, not at decision T
        S = grid_state(extra_book=[book(T + 500, T + 600, 200.0, 200.04, seq=T + 550)],
                       end=T)                                                     # stream ends at T, then the step
        S = ForwardMarketState.from_records(
            book=[(s, r) for s, st in S.book.items() for r in st.recs] + [("BTCUSDT", book(T + 900, T + 1000, 200.0, 200.04, seq=T + 950)),
                                                                           ("BTCUSDT", book(T + 1001, T + 2000, 300.0, 300.06, seq=T + 1990))],
            runs=[RUN], health=S.health)
        e0 = est(S, "buy", "EXEC-IDEALIZED")                                     # L = 0: state at T
        self.assertEqual(e0["fill"]["value"], 100.02)
        self.assertEqual(e0["latency_drift_bps"]["value"], 0.0)
        e1 = M.estimate_leg(S, BTC, "buy", 50.0, T, "EXEC-BASE")                 # L = 1 s: the T+900 quote, not T+1001
        self.assertEqual(e1["execution_time_ms"], T + 1000)
        self.assertEqual(e1["ask"]["value"], 200.04)
        self.assertEqual(e1["decision_ask"]["value"], 100.02)
        self.assertAlmostEqual(e1["latency_drift_bps"]["value"], (200.02 - 100.01) / 100.01 * 1e4, places=6)
        self.assertEqual(e1["latency_ms"]["provenance"], ASSUMED)
        # the drift is market movement: it is NOT inside the cost components
        self.assertLess(e1["spread_cost_bps"]["value"] if e1["spread_cost_bps"]["value"] is not None else 0, 5)

    def test_w3_refused(self):
        S = grid_state()
        inside = ms("2026-10-04T15:00:00Z")
        with self.assertRaises(LG.W3SealedError):
            M.estimate_leg(S, BTC, "buy", 50.0, inside, "EXEC-IDEALIZED")
        with self.assertRaises(LG.W3SealedError):                                 # execution time inside W3 too
            M.require_outside_w3(ms("2026-10-04T15:26:43Z"), "execution_time")
        M.require_outside_w3(ms("2026-10-04T15:26:44Z"), "after")                 # the end is exclusive


class TestDepthWalk(unittest.TestCase):
    def test_notional_and_walk(self):
        d = depth(T, T, 99.0, 101.0, n=3, qty=1.0, step=1.0)                      # asks 101,102,103 x 1.0
        w, _ = M.depth_walk(d, +1, 50.0)
        self.assertEqual((w["levels_used"], w["vwap"], w["s"]), (1, 101.0, 0.0))
        w, _ = M.depth_walk(d, +1, 101.0 + 51.0)                                  # level 1 + half of level 2
        self.assertEqual(w["levels_used"], 2)
        self.assertAlmostEqual(w["vwap"], 152.0 / 1.5, places=9)
        self.assertAlmostEqual(w["s"], (152.0 / 1.5 - 101.0) / 101.0, places=12)
        w, why = M.depth_walk(d, +1, 307.0)                                       # > 101+102+103 = 306 displayed
        self.assertIsNone(w)
        self.assertEqual(why, "notional_exceeds_displayed_depth")
        w, _ = M.depth_walk(d, -1, 99.0 * 1.5)                                    # sell 1.5 base at 99, 98
        self.assertAlmostEqual(w["vwap"], (99.0 + 0.5 * 98.0) / 1.5, places=9)
        bad = (T, T, T, ((99.0, 1.0), (99.5, 1.0)), ((101.0, 1.0),), 2, 1, False, False, 0, 1000, BOOT[:8])
        self.assertEqual(M.depth_walk(bad, -1, 10.0)[1], "invalid_depth_ladder")
        crossed = (T, T, T, ((102.0, 1.0),), ((101.0, 1.0),), 1, 1, False, False, 0, 1000, BOOT[:8])
        self.assertEqual(M.depth_walk(crossed, +1, 10.0)[1], "crossed_depth_snapshot")

    def test_notional_is_an_input(self):
        S = grid_state(dqty=0.5)                                                 # 20 levels x 0.5 at 0.01 steps
        small = est(S, "buy", "EXEC-BASE", notional=10.0)
        big = est(S, "buy", "EXEC-BASE", notional=300.0)
        huge = est(S, "buy", "EXEC-BASE", notional=10_000.0)
        self.assertEqual(small["slippage_bps"]["value"], 0.0)
        self.assertGreater(big["slippage_bps"]["value"], 0.0)
        self.assertGreater(big["depth_walk"]["levels_used"], 1)
        self.assertEqual(huge["slippage_bps"]["provenance"], UNAVAILABLE)
        self.assertEqual(huge["slippage_bps"]["reason"], "notional_exceeds_displayed_depth")
        self.assertIsNone(huge["total_cost_bps"]["value"])
        self.assertEqual(huge["order_notional"], {"value": 10000.0, "currency": "USDT"})
        stale_depth = grid_state(dcad=1000, end=T + 5_000)
        stale_depth.depth["BTCUSDT"].keys = [k for k in stale_depth.depth["BTCUSDT"].keys if k < T - 10_000]
        stale_depth.depth["BTCUSDT"].recs = stale_depth.depth["BTCUSDT"].recs[:len(stale_depth.depth["BTCUSDT"].keys)]
        e = est(stale_depth, "buy", "EXEC-BASE")
        self.assertEqual(e["slippage_bps"]["provenance"], UNAVAILABLE)
        self.assertTrue(e["slippage_bps"]["reason"].startswith("depth_state_invalid"))
        self.assertEqual(est(stale_depth, "buy", "EXEC-IDEALIZED")["fill"]["value"], 100.02)   # S0 needs no depth


class TestDeterminismAndVersions(unittest.TestCase):
    def test_deterministic_rebuild(self):
        S = grid_state()
        a = [canon(est(S, sd, sc)) for sc in CT.default().scenarios for sd in ("buy", "sell")]
        rows = [(s, r) for s, st in S.book.items() for r in st.recs]
        drows = [(s, r) for s, st in S.depth.items() for r in st.recs]
        random.Random(7).shuffle(rows)
        random.Random(8).shuffle(drows)
        S2 = ForwardMarketState.from_records(book=rows, depth=drows, runs=[RUN], health=list(reversed(S.health)),
                                             meta={"dataset_id": "synthetic-x0"})
        b = [canon(est(S2, sd, sc)) for sc in CT.default().scenarios for sd in ("buy", "sell")]
        self.assertEqual(a, b)
        self.assertEqual(len({json.loads(x)["estimate_id"] for x in a}), len(a))

    def test_fee_version_change(self):
        S = grid_state()
        v1 = est(S)
        CS = CT.ContractSet()
        fs2 = copy.deepcopy(CS.fee_schedule("X0-FEE-BINANCE-SPOT-STD"))
        fs2["version"] = "2.0.0"
        for e in fs2["entries"]:
            e["rate_bps"] = 7.5
        CS.add_fee_schedule(fs2)
        v2 = est(S, contracts=CS, fee_schedule_id="X0-FEE-BINANCE-SPOT-STD@2.0.0")
        self.assertEqual(v2["fee_bps"]["value"], 7.5)
        self.assertEqual(v2["models"]["fee_schedule"]["version"], "2.0.0")
        self.assertNotEqual(v1["estimate_id"], v2["estimate_id"])
        self.assertEqual(est(S), v1)                                             # old estimate never rewritten
        clash = copy.deepcopy(fs2)
        clash["entries"][0]["rate_bps"] = 1.0
        with self.assertRaises(CT.ContractError):
            CS.add_fee_schedule(dict(clash, version="1.0.0"))

    def test_model_version_change_and_tamper(self):
        tmp = tempfile.mkdtemp(prefix="p2x-ct-")
        try:
            d = os.path.join(tmp, "c")
            shutil.copytree(CT.CONTRACT_DIR, d)
            p = os.path.join(d, "models_v1.json")
            doc = _load(p)
            for m in doc["slippage_models"]:
                if m["id"] == "X0-S1-MODERATE":
                    m["bps_per_side"], m["version"] = 12.0, "1.1.0"
            _dump(doc, p)
            with self.assertRaises(CT.ContractError):                            # silent edit refused
                CT.ContractSet(d)
            sums = _load(os.path.join(d, CT.SUMS_FILE))
            sums["files"]["models_v1.json"] = _sha(p)
            _dump(sums, os.path.join(d, CT.SUMS_FILE))
            CS = CT.ContractSet(d)                                               # explicitly re-frozen new version
            S = grid_state()
            old, new = est(S, "buy", "EXEC-STRESS", notional=5.0), est(S, "buy", "EXEC-STRESS", notional=5.0, contracts=CS)
            self.assertNotEqual(old["contract_set_sha256"], new["contract_set_sha256"])
            self.assertEqual([m["version"] for m in new["models"]["slippage"]], ["1.0.0", "1.1.0"])
            self.assertAlmostEqual(new["slippage_bps"]["value"] - old["slippage_bps"]["value"], 2.0, places=9)
            self.assertNotEqual(old["estimate_id"], new["estimate_id"])
        finally:
            shutil.rmtree(tmp, True)

    def test_contracts_frozen_hashes(self):
        CS = CT.ContractSet()
        for f in CT.FILES:
            self.assertEqual(_sha(os.path.join(CT.CONTRACT_DIR, f)), CS.sums[f])


class TestBoundaries(unittest.TestCase):
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_no_w3_paper_or_collector_dependency(self):
        src = os.path.join(self.ROOT, "execution")
        for f in sorted(os.listdir(src)):
            if f.endswith(".py"):
                with open(os.path.join(src, f), encoding="utf-8") as fh:
                    text = fh.read()
                for bad in ("import p2_forward", "from p2_forward", "psycopg", "asyncpg", "urllib", "http.client",
                            "socket", "requests", "trading_signals", "telegram", ".env"):
                    self.assertNotIn(bad, text, f"{f} references {bad}")

    def test_p2d0_frozen_hashes_unchanged(self):
        rd = os.path.join(self.ROOT, "research")
        sums = _load(os.path.join(rd, "FROZEN_SHA256SUMS.json"))
        for f, h in sums["files"].items():
            self.assertEqual(_sha(os.path.join(rd, f)), h, f)
        self.assertEqual(sorted(sums["files"]), ["benchmarks_v1.json", "hypotheses_v1.json", "planned_trials_v1.json",
                                                  "protocol_v1.json"])


class TestSealedAdapter(unittest.TestCase):
    """The real adapter path on the shared synthetic two-day dataset (collector layout from SCHEMA.md)."""

    def test_pruned_equals_full_and_refuses_unsealed(self):
        base = C.base_dataset()
        times = [C.D1_MS + 10 * 3_600_000 + k * 900_000 + 390_000 for k in range(6)]
        qts = sorted({t + L for t in times for L in (0, 1000, 5000)})
        full = load_sealed(base, [C.D1])
        pr = load_sealed(base, [C.D1], query_times=qts)
        n = 0
        for sym in ("BTCUSDT", "AAAUSDT", "CCCUSDT"):
            inst = IN.binance_spot_instrument(sym)
            for t in times:
                for sc in CT.default().scenarios:
                    for side in ("buy", "sell"):
                        a = M.estimate_leg(full, inst, side, 50.0, t, sc)
                        b = M.estimate_leg(pr, inst, side, 50.0, t, sc)
                        self.assertEqual(a, b)
                        check_quantity_tree(a)
                        n += a["fill"]["value"] is not None
        self.assertGreater(n, 0)
        self.assertEqual(pr.meta["days"], [C.D1])
        self.assertIn(C.D1, pr.meta["seal_sha256"])
        self.assertGreater(pr.audit["records"]["depth"], 0)
        with self.assertRaises(Exception):                                       # pruned state: unprepared time refused
            pr.latest("book", "BTCUSDT", times[0] + 1)
        unsealed = C.copy_dataset("x0-unsealed")
        os.chmod(os.path.join(unsealed, "seals"), 0o755)
        for f in os.listdir(os.path.join(unsealed, "seals")):
            if f.startswith(C.D2):
                p = os.path.join(unsealed, "seals", f)
                os.chmod(p, 0o644)
                os.remove(p)
        from p2_research import reader as RD
        with self.assertRaises(RD.NotSealed):
            load_sealed(unsealed, [C.D2])


class TestCoverageTool(unittest.TestCase):
    def test_coverage_deterministic_and_guarded(self):
        from p2_research.execution import coverage as CV
        base = C.base_dataset()
        o1, o2 = C.scratch("x0-cov-1"), C.scratch("x0-cov-2")
        m1 = CV.run(base, [C.D1], o1, "f" * 40, notionals=(50.0, 5000.0))
        m2 = CV.run(base, [C.D1], o2, "f" * 40, notionals=(50.0, 5000.0))
        self.assertEqual(m1["logical_hash"], m2["logical_hash"])
        for f in ("estimates.jsonl.gz", "coverage.json", "manifest.json"):
            self.assertEqual(_sha(os.path.join(o1, f)), _sha(os.path.join(o2, f)), f)
        self.assertGreater(m1["files"]["estimates.jsonl.gz"]["records"], 0)
        self.assertGreaterEqual(m1["decision_time_range"][0], CV.W3_END_MS)
        cov = _load(os.path.join(o1, "coverage.json"))
        self.assertFalse(cov["audit"]["trade_prints_captured"])
        with self.assertRaises(SystemExit):
            CV.run(base, [C.D1], os.path.join(base, "out"), "f" * 40)
        with self.assertRaises(SystemExit):
            CV.run(base, [C.D1], os.path.join(CV.FORBIDDEN_ROOT, "x0"), "f" * 40)


if __name__ == "__main__":
    unittest.main()
