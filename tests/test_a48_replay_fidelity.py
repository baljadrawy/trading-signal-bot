"""A48: replay fidelity — reproductions, versioned modes, stop-fill semantics, cost accounting,
metamorphic / property tests and the synthetic bias grid.

Synthetic inputs only. Passing establishes level 1 (mathematical correctness) and, with
tests/test_a48_tracker_parity_db.py, level 2 (Paper-tracker fidelity). It does NOT establish
level 3 (exchange realism) and says nothing about any strategy's profitability."""
import asyncio
import json
import math
import random
import re
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
from pathlib import Path

import pytest

from shared.counterfactual_barrier import MODEL_VERSION, Bar, replay_bracket
from shared.execution_calibration import (TRACKER_EVENT_VERSION, ExecutedLeg, Poll, bars_from_polls,
                                          cost_ledger, legs_from_poll_outcome, tracker_poll_model)
from shared.fees import economic_close
from shared.replay_execution import (ASSUMPTIONS, MODES, OHLC_VERSION, OhlcUncertainty, bias_grid,
                                     bias_row, legacy_legs, ohlc_uncertainty, replay)
from shared.trade_geometry import BASELINE, Bracket, ExecutionCosts, References, exit_ledger

T0 = 20_720 * 86_400_000
M = 60_000
H = 3_600_000
B = 900_000
BR = dict(trade_type="momentum", planned_entry=100.0, stop_loss=98.0, target_1=102.0,
          target_2=103.6, target_3=104.4)
LV = {k: v for k, v in BR.items() if k != "trade_type"}


def m2(polls, **kw):
    return tracker_poll_model(**{**BR, "timeframe": "4h", "signal_ms": T0, **kw, "polls": polls})


def legacy(bars, **kw):
    return replay_bracket(**{**BR, "signal_timeframe": "4h", "bar_timeframe": "15m",
                             "decision_ms": T0, **kw, "bars": bars})


def m3(bars, **kw):
    return ohlc_uncertainty(**{**BR, "signal_timeframe": "4h", "bar_timeframe": "15m",
                               "decision_ms": T0, **kw, "bars": bars})


def polls(*prices, start=T0, step=M, **kw):
    return [Poll(start + i * step, p, **kw) for i, p in enumerate(prices)]


# ── Phase A: reproductions of every tracker-vs-replay discrepancy ──────────

def test_a1_stop_overshoot_bias_is_exactly_the_overshoot():
    for over in (0.1, 0.5, 1.0):
        p = polls(100.0, 99.0, 98.0 - over)
        t, r = m2(p), legacy(bars_from_polls(p, "15m"))
        assert t.exit_price == pytest.approx((98.0 - over) * 0.999)
        assert r.exit_price == pytest.approx(98.0 * 0.999)
        assert r.gross_pct - t.gross_pct == pytest.approx(over * 0.999)       # legacy optimistic


def test_a2_exact_stop_touch_is_identical():
    p = polls(100.0, 99.0, 98.0)
    assert m2(p).gross_pct == pytest.approx(legacy(bars_from_polls(p, "15m")).gross_pct, abs=1e-12)


def test_a3_entry_touch_fills_in_tracker_but_not_in_legacy():
    p = polls(100.5, 100.0, 100.4, step=B)
    t, r = m2(p), legacy(bars_from_polls(p, "15m"))
    assert t.fill_price == 100.0 and r.status == "not_filled"


def test_a4_expiry_at_poll_time_vs_bar_end():
    p = polls(100.0, 100.1) + [Poll(T0 + 25 * H + 7 * M, 100.3)]        # 4h no-T1 = 24 h
    t = m2(p)
    assert t.exit_reason == "no_T1_expired_24h" and t.exit_t_ms == T0 + 25 * H + 7 * M
    assert t.exit_price == 100.3                                       # the late poll's price


def test_a5_gap_open_tracker_first_observation_vs_legacy_bar_open():
    p = polls(100.0, 99.0) + [Poll(T0 + B, 97.0), Poll(T0 + B + M, 96.5)]
    t, r = m2(p), legacy(bars_from_polls(p, "15m"))
    assert t.exit_price == pytest.approx(97.0 * 0.999)                 # first poll beyond the stop
    assert r.exit_price == pytest.approx(97.0 * 0.999)                 # = bar open here
    late = polls(100.0, 99.0) + [Poll(T0 + B + 5 * M, 96.5)]           # first poll later in the bar
    bars = bars_from_polls(polls(100.0, 99.0) + [Poll(T0 + B, 97.0), Poll(T0 + B + 5 * M, 96.5)], "15m")
    assert m2(late).exit_price < legacy(bars).exit_price


def test_a6_arrival_order_not_event_time():
    in_order = [Poll(T0, 100.0), Poll(T0 + 2 * M, 99.0, observed_ms=T0 + M),
                Poll(T0 + 3 * M, 103.7, observed_ms=T0 + 2 * M)]
    assert m2(in_order).diagnostics["out_of_order_observations"] == 0
    late = [Poll(T0, 100.0), Poll(T0 + 2 * M, 99.0, observed_ms=T0 + 2 * M),
            Poll(T0 + 3 * M, 103.7, observed_ms=T0 + M)]                # older event arrives last
    t = m2(late)
    assert t.diagnostics["out_of_order_observations"] == 1 and t.target_reached == 2   # still applied


def test_a7_admission_window_boundary_is_strict():
    """A47 admitted at exactly 2 h; the tracker SQL is signal_time > NOW() - 2 h (strict)."""
    assert m2([Poll(T0 + 2 * H, 99.9)]).reason == "admission_window_expired"
    assert m2([Poll(T0 + 2 * H - 1, 99.9)]).status == "open_at_end"


def test_a8_candle_invalidation_exit_rest_only_without_slippage():
    inv = 99.0
    cl = dict(candle_close_ms=T0 + 15 * M, candle_close=98.9)
    p = [Poll(T0, 100.0, "rest_backup"), Poll(T0 + 16 * M, 98.5, "rest_backup", **cl)]
    t = m2(p, invalidation_price=inv)
    assert t.exit_reason == "signal_candle_invalidation" and t.exit_price == 98.5
    assert t.stop_invalidation == pytest.approx(99.0)
    ws = [Poll(T0, 100.0, "rest_backup"), Poll(T0 + 16 * M, 98.5, "websocket", agg_id=1)]
    assert m2(ws, invalidation_price=inv).status == "open_at_end"       # stream: no candle check
    early = [Poll(T0, 100.0, "rest_backup"),
             Poll(T0 + 16 * M, 98.5, "rest_backup", candle_close_ms=T0, candle_close=98.9)]
    assert m2(early, invalidation_price=inv).status == "open_at_end"    # candle not after entry
    gap = [Poll(T0, 100.0, "rest_backup"), Poll(T0 + 16 * M, 97.0, "rest_backup", **cl)]
    g = m2(gap, invalidation_price=inv)
    assert g.exit_reason == "signal_candle_invalidation" and g.exit_price == 97.0   # no x 0.999
    assert m2(gap).exit_price == pytest.approx(97.0 * 0.999)            # same gap as a stop


def test_a9_stream_drops_aggregate_ids_that_are_not_newer():
    sys.path.insert(0, "trade_tracker")
    from binance_price_stream import BinancePriceStream                  # the real stream code
    import logging

    async def go():
        async def provider():
            return {"calusdt"}

        async def sink(sym, px):
            return None
        s = BinancePriceStream(symbol_provider=provider, on_price=sink, logger=logging.getLogger("t"))
        for a, px in ((5, 99.0), (5, 98.0), (4, 97.0), (6, 96.0)):
            await s._handle(json.dumps({"e": "aggTrade", "s": "CALUSDT", "a": a, "p": str(px)}), {"calusdt"})
        return [s._queue.get_nowait() for _ in range(s._queue.qsize())]
    assert asyncio.run(go()) == [("CALUSDT", 99.0), ("CALUSDT", 96.0)]
    p = [Poll(T0, 100.0, "rest_backup")] + [Poll(T0 + (i + 1) * M, px, "websocket", agg_id=a)
                                             for i, (a, px) in enumerate(((5, 99.0), (5, 98.0), (4, 97.0), (6, 96.0)))]
    t = m2(p)
    assert t.diagnostics["dropped_stream_not_newer"] == 2 and t.exit_price == pytest.approx(96.0 * 0.999)


def test_a10_restart_resets_only_the_stream_watermark():
    p = [Poll(T0, 100.0, "rest_backup"), Poll(T0 + M, 102.2, "websocket", agg_id=9),
         Poll(T0 + 2 * M, None, "restart"), Poll(T0 + 3 * M, 100.2, "websocket", agg_id=3)]
    t = m2(p)
    assert t.diagnostics["restarts"] == 1 and t.exit_reason == "break_even"     # T1 state survived
    no_restart = [x for x in p if x.source != "restart"]
    assert m2(no_restart).status == "open_at_end"                       # id 3 <= 9: dropped


def test_a11_missing_price_is_skipped_like_the_tracker():
    p = [Poll(T0, None, "rest_backup"), Poll(T0 + M, 100.0, "rest_backup"),
         Poll(T0 + 2 * M, None, "rest_backup"), Poll(T0 + 3 * M, 98.0, "rest_backup")]
    t = m2(p)
    assert t.diagnostics["skipped_missing_price"] == 2 and t.exit_reason == "stop_loss"


def test_a12_pre_fill_stream_ticks_cannot_fill():
    p = [Poll(T0, 100.5, "rest_backup"), Poll(T0 + M, 99.5, "websocket", agg_id=1),
         Poll(T0 + 2 * M, 100.4, "rest_backup")]
    t = m2(p)
    assert t.status == "not_filled" and t.diagnostics["ignored_pre_fill_stream"] == 1


# ── Phase B: versioned modes ───────────────────────────────────────────────

def test_b1_modes_are_explicit_and_legacy_is_unchanged():
    assert set(MODES) == {"legacy_bar_v1", "tracker_event_v1", "ohlc_uncertainty_v1"}
    assert MODEL_VERSION == "a42-cf-bar-v1" == MODES["legacy_bar_v1"]["model_version"]
    assert MODES["tracker_event_v1"]["model_version"] == TRACKER_EVENT_VERSION == "a48-tev-v1"
    assert MODES["ohlc_uncertainty_v1"]["model_version"] == OHLC_VERSION
    bars = bars_from_polls(polls(100.0, 99.0, 97.5), "15m")
    kw = {**BR, "signal_timeframe": "4h", "bar_timeframe": "15m", "decision_ms": T0, "bars": bars}
    assert replay("legacy_bar_v1", **kw) == replay_bracket(**kw)
    with pytest.raises(ValueError):
        replay("resting_limit_v1", **kw)                               # never a replay mode


def test_b2_mode3_has_no_point_estimate():
    fields = set(OhlcUncertainty.__dataclass_fields__)
    assert not fields & {"gross_pct", "net_pct", "exit_price", "expected", "fill_price"}
    assert all(k.startswith("A_") for k in ASSUMPTIONS)


# ── Phase C: stop-fill semantics ────────────────────────────────────────────

def test_c1_stops_after_partial_exits_use_remaining_and_reference_prices():
    be = m2(polls(100.0, 102.1, 100.3))                                # T1 then BE (100.4004)
    assert be.exit_reason == "break_even" and be.remaining_fraction == 0.75
    assert be.exit_reference_price == pytest.approx(100.3)              # observed < level
    tr = m2(polls(100.0, 103.7, 104.0, 101.0))                         # T2 then trailing
    assert tr.exit_reason == "trailing_stop" and tr.remaining_fraction == 0.25
    assert tr.exit_reference_price == pytest.approx(101.0)
    lvl = m2(polls(100.0, 103.7, 104.0, 102.0))                        # trail floored at T1 = 102
    assert lvl.exit_reference_price == pytest.approx(102.0)


def test_c2_impossible_sequences_are_reported_not_repaired():
    bad = {
        "processing_time_not_monotone": [Poll(T0 + M, 100.0), Poll(T0, 99.0)],
        "observation_after_processing": [Poll(T0, 100.0, observed_ms=T0 + 1)],
        "websocket_without_aggregate_id_or_price": [Poll(T0, 100.0, "websocket")],
        "candle_incomplete": [Poll(T0, 100.0, "rest_backup", candle_close=99.0)],
        "candle_invalid_or_from_future": [Poll(T0, 100.0, "rest_backup", candle_close_ms=T0 + 1,
                                               candle_close=99.0)],
        "unknown_source": [Poll(T0, 100.0, "fix")],
        "non_finite_or_non_positive_price": [Poll(T0, float("inf"))],
    }
    for reason, p in bad.items():
        assert m2(p).reason == reason, reason
    assert m2(polls(100.0), stop_loss=float("nan")).reason == "non_finite_or_non_positive_bracket"


def test_c3_stale_observations_are_flagged_but_processed_as_the_tracker_does():
    p = [Poll(T0, 100.0), Poll(T0 + 10 * M, 97.9, observed_ms=T0 + 2 * M)]
    t = m2(p)
    assert t.diagnostics["stale_observations"] == 1 and t.exit_reason == "stop_loss"


def test_c4_delayed_observation_uses_processing_time():
    assert m2([Poll(T0, 100.0), Poll(T0 + 30 * H, 99.0, observed_ms=T0 + M)]).exit_reason == "no_T1_expired_24h"


def test_c5_mode3_stop_interval_and_legacy_at_its_optimistic_end():
    bars = [Bar(T0, 100, 100.2, 99.9, 100.1), Bar(T0 + B, 100.1, 100.3, 97.0, 97.5)]
    r = m3(bars)
    (s,) = r.scenarios
    assert s.exit_reason == "stop_loss" and s.exit_fill_interval == pytest.approx((97.0 * 0.999, 98.0 * 0.999))
    assert "A_OBS_IN_BAR" in s.conditional_on and r.status == "FILL_PRICE_UNCERTAIN"
    assert legacy(bars).gross_pct == pytest.approx(s.gross_pct_interval[1])
    assert r.conditional_stress_gross_pct == pytest.approx(s.gross_pct_interval[0])
    exact = [Bar(T0, 100, 100.2, 99.9, 100.1), Bar(T0 + B, 100.1, 100.3, 98.0, 98.5)]
    assert m3(exact).status == "DETERMINED"                            # low == stop: no uncertainty


def test_c6_mode3_represents_stop_vs_target_ambiguity():
    bars = [Bar(T0, 100, 100.2, 99.9, 100.1), Bar(T0 + B, 100.1, 102.5, 97.5, 100.0)]
    r = m3(bars)
    assert r.status == "PATH_AMBIGUOUS" and set(r.exit_reasons) == {"stop_loss", "break_even"}
    assert r.order_relevant_bars >= 1 and len(r.scenarios) >= 2


def test_c7_mode3_gap_open_interval():
    bars = [Bar(T0, 100, 100.2, 99.9, 100.1), Bar(T0 + B, 97.0, 97.4, 96.0, 96.5)]
    (s,) = m3(bars).scenarios
    assert s.exit_fill_interval == pytest.approx((96.0 * 0.999, 97.0 * 0.999))


def test_c8_mode3_intrabar_round_trip_above_the_bar_low():
    """O -> T1 -> back to break-even -> high: neither extreme order (O-L-H-C / O-H-L-C) shows it."""
    bars = [Bar(T0, 100, 100.2, 99.9, 100.1), Bar(T0 + B, 100.3, 104.5, 100.3, 104.5)]
    r = m3(bars)
    assert {"T3", "break_even"} <= set(r.exit_reasons)
    t = m2([Poll(T0, 100), Poll(T0 + M, 100.2), Poll(T0 + B, 100.3), Poll(T0 + B + M, 102.1),
            Poll(T0 + B + 2 * M, 100.35), Poll(T0 + B + 3 * M, 104.5)])
    assert t.exit_reason == "break_even"
    assert any(s.exit_reason == "break_even" and s.gross_pct_interval[0] - 1e-9 <= t.gross_pct
               <= s.gross_pct_interval[1] + 1e-9 for s in r.scenarios)


def test_c9_mode3_invalidation_first_on_a_rest_check_through_a_gap():
    bars = [Bar(T0, 100, 100.0, 98.7, 98.8), Bar(T0 + B, 97.5, 97.8, 96.9, 97.0)]
    r = m3(bars, invalidation_price=99.0, signal_timeframe="15m")
    assert {"signal_candle_invalidation", "stop_loss"} <= set(r.exit_reasons)
    inv = [s for s in r.scenarios if s.exit_reason == "signal_candle_invalidation"]
    assert all(s.exit_fill_interval == (96.9, 97.8) for s in inv)       # no stop slippage


def test_c10_mode3_returns_insufficient_information_instead_of_precision():
    assert m3([Bar(T0, 100, 100.5, 99.5, 100.2)]).status == "INSUFFICIENT_INFORMATION"   # open
    r = m3([Bar(T0, 100, 100.5, 99.5, 100.2)], invalidation_price=99.0)
    assert (r.status, r.reason) == ("INSUFFICIENT_INFORMATION", "candle_invalidation_needs_signal_timeframe_bars")
    wait = [Bar(T0, 100.5, 100.6, 100.3, 100.4)] + [
        Bar(T0 + i * B, 100.4, 100.6 + 0.01 * i, 99.0 + 0.01 * i, 100.3) for i in range(1, 30)]
    r = m3(wait, max_fill_points=4)
    assert (r.status, r.reason) == ("INSUFFICIENT_INFORMATION", "entry_fill_price_unresolved")


def test_c11_mode3_rejects_malformed_or_non_finite_bars():
    assert m3([Bar(T0, 100, 99, 101, 100)]).reason == "malformed_bar"
    assert m3([Bar(T0, 100, float("nan"), 99, 100)]).reason == "non_finite_bar"
    assert m3([Bar(T0 - 1, 100, 100.5, 99.5, 100)]).reason == "bar_before_decision"
    assert m3([Bar(T0, 100, 100.5, 99.5, 100), Bar(T0 + 2 * B, 100, 100.5, 99.5, 100)]).reason == "bar_gap"


# ── Phase D: cost accounting ────────────────────────────────────────────────

PATHS = {
    "stop_overshoot": polls(100.0, 99.0, 97.5),
    "t1_then_be": polls(100.0, 102.1, 100.3),
    "t3": polls(100.0, 102.1, 103.7, 104.5),
    "trailing": polls(100.0, 103.7, 104.0, 101.0),
    "expiry": polls(100.0, 100.1) + [Poll(T0 + 25 * H, 100.3)],
}


@pytest.mark.parametrize("name", sorted(PATHS))
def test_d1_ledger_identities_and_legacy_reconciliation(name):
    t = m2(PATHS[name])
    for spread in (0.0, 0.05):
        L = cost_ledger(legs_from_poll_outcome(t), half_spread_pct=spread)
        assert L.execution_price_pnl_usdt == pytest.approx(L.gross_price_pnl_usdt - L.execution_slippage_usdt, abs=1e-12)
        assert L.execution_price_pnl_usdt == pytest.approx(t.gross_usdt, abs=1e-9)   # = tracker gross
        assert L.net_modeled_pnl_usdt == pytest.approx(
            L.gross_price_pnl_usdt - (L.explicit_fees_usdt + L.spread_cost_usdt + L.execution_slippage_usdt), abs=1e-12)
        assert L.legacy_tracker_net_usdt == pytest.approx(
            L.net_modeled_pnl_usdt + L.legacy_rounding_usdt + L.legacy_fee_basis_difference_usdt
            + L.spread_cost_usdt - 0.001 * 50, abs=1e-9)
        econ = economic_close(t.gross_usdt)
        assert (L.legacy_tracker_net_usdt, L.legacy_economic_result) == (econ["net_profit_usdt"], econ["economic_result"])


def test_d2_slippage_is_realized_once_and_the_allowance_is_stress_only():
    t = m2(PATHS["stop_overshoot"])
    L = cost_ledger(legs_from_poll_outcome(t))
    assert L.execution_slippage_usdt > 0 and L.stress_allowance_usdt == pytest.approx(0.05)
    assert L.total_modeled_costs_usdt == pytest.approx(L.explicit_fees_usdt + L.execution_slippage_usdt)
    assert L.stress_net_usdt == pytest.approx(L.net_modeled_pnl_usdt - 0.05)
    assert L.double_counted_slippage_usdt == pytest.approx(min(L.execution_slippage_usdt, 0.05))
    target_only = cost_ledger(legs_from_poll_outcome(m2(PATHS["t3"])))
    assert target_only.execution_slippage_usdt == 0 and target_only.double_counted_slippage_usdt == 0


def test_d3_fees_scale_with_executed_notional():
    t = m2(PATHS["t1_then_be"])
    a, b = cost_ledger(legs_from_poll_outcome(t)), cost_ledger(legs_from_poll_outcome(t), notional_usdt=100.0)
    assert b.explicit_fees_usdt == pytest.approx(2 * a.explicit_fees_usdt)
    legs = legs_from_poll_outcome(t)
    exec_notional = 50 + sum(l.fraction * 50 / t.fill_price * l.execution_price for l in legs[1:])
    assert a.explicit_fees_usdt == pytest.approx(0.001 * exec_notional)


def test_d4_quantity_conservation_dust_and_oversold():
    legs = [ExecutedLeg("entry", 1, 100, 100, True), ExecutedLeg("target_1", 0, 102, 102, False, quantity=0.12),
            ExecutedLeg("stop_loss", 0, 98, 97.9, True, quantity=0.37)]
    L = cost_ledger(legs, quantity=0.5)
    assert L.unsold_quantity == pytest.approx(0.01) and L.unsold_mark_usdt == pytest.approx(0.01 * 98)
    with pytest.raises(ValueError):
        cost_ledger(legs[:2] + [ExecutedLeg("stop_loss", 0, 98, 97.9, True, quantity=0.4)], quantity=0.5)
    for bad in ([], [ExecutedLeg("target_1", 1, 1, 1, False)], [ExecutedLeg("entry", 1, float("nan"), 1, True)]):
        with pytest.raises(ValueError):
            cost_ledger(bad)


def test_d5_ledger_equals_a46_per_leg_ledger_and_legacy_ledger_has_no_overshoot():
    refs = References(100, 1, 100, 97, 105, False)
    b = Bracket("a46-tg-v1", "momentum", "4h", 100.0, 98.0, 98.0, 102.0, 103.6, 104.4, 2.0, BASELINE, True, None, refs)
    a46 = exit_ledger(b, "stop_before_t1", ExecutionCosts())
    t = m2(polls(100.0, 99.0, 98.0))
    L = cost_ledger(legs_from_poll_outcome(t))
    assert L.execution_price_pnl_usdt == pytest.approx(a46.gross_usdt)
    assert L.explicit_fees_usdt == pytest.approx(a46.cost_usdt)
    r = legacy(bars_from_polls(PATHS["stop_overshoot"], "15m"))
    Ll = cost_ledger(legacy_legs(r, **LV))
    assert Ll.execution_price_pnl_usdt == pytest.approx(r.gross_pct / 100 * 50)
    assert Ll.net_modeled_pnl_usdt > cost_ledger(legs_from_poll_outcome(m2(PATHS["stop_overshoot"]))).net_modeled_pnl_usdt


# ── Phase F: metamorphic / property tests (fixed seeds) ─────────────────────

def _random_case(seed, n=360, inv=False):
    rng = random.Random(seed)
    pe = 100 * (1 + rng.choice([-0.002, 0.0, 0.002, 0.004]))
    d = rng.choice([0.01, 0.02, 0.03])
    br = dict(trade_type=rng.choice(["momentum", "reversion"]), planned_entry=pe, stop_loss=pe * (1 - d),
              target_1=pe * (1 + 0.8 * d), target_2=pe * (1 + 1.6 * d), target_3=pe * (1 + 2.4 * d))
    sigma = rng.choice([0.0008, 0.0015, 0.003])
    px, out = 100.0, []
    for i in range(n):
        if i:
            px *= math.exp(rng.gauss(0, sigma) + (rng.choice([-1, 1]) * 0.01 if rng.random() < 0.004 else 0))
        out.append(Poll(T0 + i * M, round(px, 6)))
    return br, (pe * (1 - d * 0.5) if inv else None), out


def _with_candles(ps, tf_ms=B):
    bars = bars_from_polls(ps, "15m", start_ms=T0)
    out = []
    for q in ps:
        cl = [b for b in bars if b.open_ms + tf_ms <= q.t_ms]
        out.append(Poll(q.t_ms, q.price, "rest_backup", candle_close_ms=cl[-1].open_ms + tf_ms if cl else None,
                        candle_close=cl[-1].close if cl else None))
    return out


@pytest.mark.parametrize("inv", [False, True])
def test_f1_soundness_tracker_outcome_lies_inside_the_ohlc_scenario_set(inv):
    """AC5: wherever A_OBS_IN_BAR and A_FIRST_OBS_AT_OPEN hold by construction (bars are built
    from the observations), the full-information Mode 2 outcome is one of Mode 3's scenarios."""
    checked = 0
    for seed in range(40):
        br, invp, ps = _random_case(seed, inv=inv)
        if inv:
            ps = _with_candles(ps)
        t = tracker_poll_model(**br, timeframe="15m", polls=ps, signal_ms=T0, invalidation_price=invp)
        r = ohlc_uncertainty(**br, signal_timeframe="15m", bars=bars_from_polls(ps, "15m", start_ms=T0),
                             bar_timeframe="15m", decision_ms=T0, invalidation_price=invp)
        if r.status == "INSUFFICIENT_INFORMATION" and r.reason != "bars_end_before_exit":
            continue                                                   # honest refusal, not a pass
        checked += 1
        if t.status in ("rejected", "not_filled", "open_at_end"):
            assert r.status == t.status or any(s.status == t.status for s in r.scenarios), seed
            continue
        assert any(s.status == "closed" and s.exit_reason == t.exit_reason
                   and s.gross_pct_interval[0] - 1e-7 <= t.gross_pct <= s.gross_pct_interval[1] + 1e-7
                   and s.fill_interval[0] - 1e-7 <= t.fill_price <= s.fill_interval[1] + 1e-7
                   for s in r.scenarios), seed
    assert checked >= 35


def test_f2_removing_information_widens_the_envelope():
    compared = 0
    for seed in range(30):
        br, _, ps = _random_case(seed, n=480)
        env = {}
        for tf in ("15m", "1h"):
            r = ohlc_uncertainty(**br, signal_timeframe="4h", bars=bars_from_polls(ps, tf, start_ms=T0),
                                 bar_timeframe=tf, decision_ms=T0)
            env[tf] = r
        a, b = env["15m"].conditional_gross_envelope_pct, env["1h"].conditional_gross_envelope_pct
        if a is None or b is None:
            continue
        compared += 1
        assert b[0] <= a[0] + 1e-7 and b[1] >= a[1] - 1e-7, seed
        assert set(env["15m"].exit_reasons) - {"open_at_end"} <= set(env["1h"].exit_reasons), seed
    assert compared >= 15


def test_f3_deterministic_and_wall_clock_free():
    br, _, ps = _random_case(7)
    a = tracker_poll_model(**br, timeframe="4h", polls=ps, signal_ms=T0)
    assert a == tracker_poll_model(**br, timeframe="4h", polls=list(ps), signal_ms=T0)
    bars = bars_from_polls(ps, "15m", start_ms=T0)
    kw = dict(**br, signal_timeframe="4h", bars=bars, bar_timeframe="15m", decision_ms=T0)
    assert ohlc_uncertainty(**kw) == ohlc_uncertainty(**kw)
    for mod in ("shared/replay_execution.py", "shared/execution_calibration.py"):
        src = Path(mod).read_text()
        assert not re.search(r"^\s*(import|from)\s+(time|datetime)\b", src, re.M), mod
        assert "random" not in re.findall(r"^\s*import\s+(\w+)", src, re.M), mod


def test_f4_partial_exits_conserve_quantity_and_never_go_negative():
    for seed in range(60):
        br, _, ps = _random_case(seed, n=240)
        t = tracker_poll_model(**br, timeframe="4h", polls=ps, signal_ms=T0)
        if t.status not in ("closed", "open_at_end"):
            continue
        sold = sum(f[1] for f in t.fills)
        assert 0 <= t.remaining_fraction <= 1 and sold + t.remaining_fraction == pytest.approx(1.0)
        if t.status == "closed":
            L = cost_ledger(legs_from_poll_outcome(t))
            assert L.unsold_quantity == pytest.approx(0, abs=1e-12)
            assert L.execution_price_pnl_usdt == pytest.approx(t.gross_usdt, abs=1e-9)


def test_f5_overshoot_moves_the_fill_linearly():
    fills = [m2(polls(100.0, 99.0, 98.0 - o)).exit_price for o in (0, 0.2, 0.4, 0.6)]
    steps = [a - b for a, b in zip(fills, fills[1:])]
    assert steps == pytest.approx([0.2 * 0.999] * 3)


def test_f6_invalid_inputs_fail_safely_in_every_mode():
    assert m2([]).status == "invalid"
    assert m3([]).status == "invalid"
    assert m3([Bar(T0, 100, 100.5, 99.5, 100)], bar_timeframe="7m").status == "invalid"
    assert legacy([]).status == "invalid"


def test_f7_isolation_registry():
    from experimental_modules import EXPERIMENTAL_SHARED
    assert {"replay_execution", "execution_calibration", "counterfactual_barrier"} <= set(EXPERIMENTAL_SHARED)
    pat = re.compile(r"\b(?:from|import)\s+shared\.(" + "|".join(EXPERIMENTAL_SHARED) + r")\b")
    for p in Path(".").glob("*/*.py"):
        if p.parts[0] in ("tests", "research", "colab", "docs") or (p.parent.name == "shared"
                                                                    and p.stem in EXPERIMENTAL_SHARED):
            continue
        assert not pat.search(p.read_text(encoding="utf-8", errors="ignore")), p


# ── Phase G: synthetic bias grid ────────────────────────────────────────────

def test_g1_bias_grid_quantifies_overshoot_and_its_direction():
    rows = bias_grid(distances=(2.0,), polls=(1, 30, 300), gaps=(0.0, 1.0), states=(0, 1, 2))
    assert len(rows) == 18
    for r in rows:
        assert r["tracker_inside_mode3"]
        assert r["exit_delay_tracker_s"] == pytest.approx(0.5 * r["poll_s"], abs=1e-3)
        if r["reason_tracker"] == r["reason_legacy"]:
            assert r["fill_diff_bps_of_level"] < 0 and r["gross_diff_pp"] < 0   # legacy optimistic
        else:
            # A target touch and the stop crossing share one bar: legacy's stop-first rule books
            # the ORIGINAL stop although the tracker saw the target first. Direction can flip.
            assert r["mode3_status"] == "PATH_AMBIGUOUS"
    flipped = [r for r in rows if r["reason_tracker"] != r["reason_legacy"]]
    assert flipped and all(r["gross_diff_pp"] > 0 for r in flipped)
    r = bias_row(stop_distance_pct=2.0, poll_s=1, gap_pct=0.0, partial_state=0)
    # overshoot = speed (0.01 %/s of 100) x half a 1 s interval = 0.005; fill diff = -0.005 x 0.999
    assert r["fill_diff_bps_of_level"] == pytest.approx(-0.005 * 0.999 / 98.0 * 1e4, rel=1e-6)
