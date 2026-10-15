"""A47: tracker-vs-replay calibration, intrabar ambiguity, exchange rules, cost reconciliation.

Synthetic events only. These prove mathematical correctness and model agreement (levels 1–2);
they do not establish real-world execution validity (level 3) or any trading edge."""
import math
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests')

import pytest

from shared.candidate_selection import EligibilityPolicy, eligibility_reasons, normalize
from shared.counterfactual_barrier import Bar
from shared.exchange_rules import (FIXTURES, check_order, plan_bracket_orders, remainder_after_fills,
                                   round_to)
from shared.execution_calibration import (Poll, bars_from_polls, calibrate, detect_cost_overlap,
                                          ordering_interval, tracker_cost_decomposition,
                                          tracker_poll_model)
from shared.fees import economic_close
from shared.signal_identity import freshness_at
from shared.trade_geometry import ExecutionCosts, exit_ledger, Bracket, References, BASELINE

T0 = 20_720 * 86_400_000
M = 60_000
BR = dict(trade_type="momentum", planned_entry=100.0, stop_loss=98.0, target_1=102.0,
          target_2=103.6, target_3=104.4, timeframe="4h", signal_ms=T0)


def path(*prices, start=T0, step=M):
    return [Poll(start + i * step, p) for i, p in enumerate(prices)]


def bars_path(*segments):
    """One price per 15-minute bar boundary region: each segment = prices inside one bar."""
    out = []
    for k, seg in enumerate(segments):
        out += [Poll(T0 + k * 900_000 + i * M, p) for i, p in enumerate(seg)]
    return out


def model(polls, **kw):
    return tracker_poll_model(**{**BR, **kw, "polls": polls})


def cal(name, polls, **kw):
    return calibrate(name, **{**BR, **kw, "polls": polls})


# 1–6, 33–34 ── calibration on canonical paths ──────────────────────────────

CANONICAL = {
    "01_clean_entry_full_exit_t3": bars_path([100, 100.2], [101, 102.1], [103, 103.7], [104, 104.5]),
    "02_t1_then_break_even": bars_path([100, 100.1], [101.5, 102.1], [101.2, 100.4004004]),
    "04_stop_before_t1": bars_path([100, 99.5], [99.0, 98.0]),          # stop poll exactly at the level
    "05_t2_then_trailing": bars_path([100, 101], [102.1, 103.7], [105.0, 106.0], [104.0, 103.2]),
}
EXPIRY = bars_path([100.0, 100.2], *[[100.1, 100.2]] * 3) + [Poll(T0 + 25 * 3_600_000, 100.3)]


@pytest.mark.parametrize("name", sorted(CANONICAL))
def test_calibration_matches_on_unambiguous_paths(name):
    row = cal(name, CANONICAL[name])
    assert row.classification in ("MATCH", "EXPECTED_ROUNDING_DIFFERENCE"), row.explanation
    assert row.tracker.exit_reason == row.replay.exit_reason
    assert row.net_label_tracker == row.net_label_replay


def test_expiry_differs_by_poll_time_vs_bar_end_and_is_classified():
    row = cal("expiry", EXPIRY, expected_difference="expiry_at_poll_time_vs_bar_end")
    assert row.tracker.exit_reason == "no_T1_expired_24h"
    assert row.classification in ("MATCH", "MODEL_ASSUMPTION_DIFFERENCE")


def test_03_12_t1_t2_t3_progression_books_25_50_25():
    out = model(CANONICAL["01_clean_entry_full_exit_t3"])
    assert out.exit_reason == "T3" and [(t, f) for t, f, _ in out.fills] == [(1, .25), (2, .5), (3, .25)]
    assert out.gross_pct == pytest.approx(.25 * 2 + .5 * 3.6 + .25 * 4.4)


def test_33_reversion_trade_calibrates():
    row = cal("reversion", bars_path([100, 99.8], [101.0, 102.1], [101.0, 100.4004004]), trade_type="reversion")
    assert row.classification == "MATCH" and row.tracker.exit_reason == "break_even"


def test_stop_overshoot_is_a_quantified_replay_optimism():
    """KEY CALIBRATION FINDING. The tracker fills a stop at the first OBSERVED price beyond it
    (every overshooting poll is treated as a gap); the replay fills at the stop level unless the
    bar opened below it. With discrete monitoring the replay is optimistic by the overshoot."""
    for overshoot in (0.1, 0.5, 1.0):
        row = cal("overshoot", bars_path([100, 99.5], [99.0, 98.0 - overshoot]),
                  expected_difference="stop_fill_at_first_observed_poll_beyond_stop_vs_at_level")
        assert row.tracker.exit_reason == row.replay.exit_reason == "stop_loss"
        assert row.classification == "MODEL_ASSUMPTION_DIFFERENCE"
        assert row.gross_diff_pp == pytest.approx(overshoot * 0.999, abs=1e-6)       # replay − tracker > 0


def test_06_gap_through_stop_boundary_vs_intrabar():
    boundary = cal("gap_boundary", bars_path([100, 100.2], [96.0, 95.5]))
    assert boundary.tracker.exit_price == pytest.approx(96.0 * 0.999) and boundary.classification == "MATCH"
    intrabar = cal("gap_intrabar", bars_path([100, 100.2], [99.0, 96.5]),
                   expected_difference="gap_fill_first_poll_vs_bar_open")
    assert intrabar.tracker.exit_price == pytest.approx(96.5 * 0.999)
    assert intrabar.classification in ("MATCH", "MODEL_ASSUMPTION_DIFFERENCE")


# 7–10 ── intrabar ambiguity ──────────────────────────────────────────────

def test_07_10_stop_and_target_in_one_bar_are_reported_as_an_interval():
    bars = [Bar(T0, 100, 100.2, 99.9, 100.1), Bar(T0 + 900_000, 100.1, 102.5, 97.5, 100.0)]
    iv = ordering_interval(**{k: v for k, v in BR.items() if k != "signal_ms"}, bars=bars, signal_ms=T0)
    sf, tf = iv["outcomes"]["stop_first"], iv["outcomes"]["target_first"]
    assert iv["ambiguous"] and sf.exit_reason == "stop_loss" and tf.exit_reason in ("break_even", "stop_loss")
    assert iv["conservative_gross_pct"] == sf.gross_pct <= iv["favourable_gross_pct"]
    row = cal("ambiguous", [Poll(b.open_ms + i * M, px) for b in bars
                            for i, px in enumerate((b.open, b.low, b.high, b.close))])
    assert row.classification in ("MATCH", "INSUFFICIENT_MARKET_INFORMATION")
    assert row.replay.exit_reason == sf.exit_reason                                  # replay orders stop-first
    assert row.replay.gross_pct >= iv["conservative_gross_pct"]                      # but fills at the level


# 11–19 ── entry and event handling ──────────────────────────────────────

def test_13_duplicate_events_are_idempotent():
    p = CANONICAL["02_t1_then_break_even"]
    dup = sorted(p + p[2:4], key=lambda x: x.t_ms)
    assert model(dup).gross_pct == pytest.approx(model(p).gross_pct)


def test_14_15_delayed_and_out_of_order_events_follow_arrival_order():
    p = CANONICAL["04_stop_before_t1"]
    late = p[:2] + [Poll(T0 + 30 * 3_600_000, p[2].price)]          # same price, processed 30 h later
    assert model(late).exit_reason == "no_T1_expired_24h"             # tracker uses processing time
    swapped = [p[0], p[3], p[1], p[2]]                                # arrival order ≠ event time
    row = cal("out_of_order", swapped, expected_difference="tracker_processes_arrival_order")
    assert row.tracker.status == "closed"
    assert row.classification in ("MATCH", "MODEL_ASSUMPTION_DIFFERENCE")


def test_16_restart_before_fill_is_stateless_and_18_19_expiry_and_rejection():
    waiting = path(100.6, 100.5, 100.4)
    assert model(waiting).status == "not_filled"
    assert model(waiting + path(99.9, start=T0 + 10 * M)).fill_price == 99.9   # resumed, then touched
    assert model(path(100.6, start=T0 + 3 * 3_600_000)).reason == "admission_window_expired"
    assert model(path(97.5)).status == "rejected"


def test_entry_touch_vs_trade_through_is_a_documented_model_difference():
    touch = path(100.5, 100.0, 101.0, 102.2, 101.0, 100.1, start=T0, step=900_000)
    row = cal("touch", touch, expected_difference="entry_touch_at_observed_vs_strict_trade_through")
    assert row.tracker.fill_price == 100.0 and row.replay.status in ("not_filled", "closed")
    assert row.classification in ("MATCH", "MODEL_ASSUMPTION_DIFFERENCE")


def test_31_non_finite_inputs_are_invalid():
    assert model(path(100, float("nan"))).status == "invalid"
    assert check_order(FIXTURES["HIGHPRICEUSDT"], side="BUY", order_type="LIMIT", price=float("inf"),
                       quantity=1).reasons == ("input:non_finite",)


# 11, 20–23, 32 ── exchange rules ─────────────────────────────────────────

def test_20_21_22_tick_step_and_notional_rules():
    f = FIXTURES["HIGHPRICEUSDT"]
    assert check_order(f, side="BUY", order_type="LIMIT", price="100.005", quantity="0.1").reasons == ("PRICE_FILTER:tick_size",)
    assert check_order(f, side="BUY", order_type="LIMIT", price="100.01", quantity="0.000015").reasons == \
        ("LOT_SIZE:step_size", "NOTIONAL:min_notional")
    assert check_order(f, side="BUY", order_type="LIMIT", price="100.00", quantity="0.04").reasons == ("NOTIONAL:min_notional",)
    assert check_order(f, side="BUY", order_type="LIMIT", price="100.00", quantity="0.05").valid
    assert round_to("100.005", "0.01", "down") == 100.0 and round_to("100.001", "0.01", "up") == 100.01


def test_11_23_partial_entry_budget_and_dust_after_partial_exit():
    lo = FIXTURES["LOWPRICEUSDT"]                                     # step 1 unit
    plan = plan_bracket_orders(lo, entry=0.1234, stop=0.1200, t1=0.1268, t2=0.1295, t3=0.1309)
    entry = plan.orders[0]
    assert entry.quantity == 405 and entry.quantity * entry.price < 50     # floor: < full budget
    assert sum(o.quantity for o in plan.orders if o.role.startswith("t")) == entry.quantity
    rem = remainder_after_fills(lo, quantity=405, sold=404.6, price=0.13)
    assert rem["sellable"] is False                                   # dust cannot be sold
    hi = plan_bracket_orders(FIXTURES["HIGHPRICEUSDT"], entry=100, stop=98, t1=102, t2=103.6, t3=104.4,
                             notional_usdt=12)
    assert "t1_merged_into_t2" in hi.notes and "t3_merged_into_t2" in hi.notes


def test_32_same_bracket_different_symbol_filters():
    br = dict(entry=0.1234567, stop=0.12, t1=0.1269, t2=0.1295, t3=0.1309)
    assert plan_bracket_orders(FIXTURES["LOWPRICEUSDT"], **br).valid
    hi_plan = plan_bracket_orders(FIXTURES["HIGHPRICEUSDT"], **br)
    assert not hi_plan.valid and any("rounding_material" in r or "PRICE_FILTER" in r for r in hi_plan.reasons)
    big = plan_bracket_orders(FIXTURES["HIGHPRICEUSDT"], entry=100.004, stop=99.99, t1=100.03,
                              t2=100.05, t3=100.06)
    assert not big.valid and big.reasons[0].startswith("rounding_material")   # rounding would change the trade
    market = check_order(FIXTURES["LOWPRICEUSDT"], side="BUY", order_type="MARKET", price=0.1,
                         quantity=600000, average_price=0.1)
    assert "MARKET_LOT_SIZE:max_qty" in market.reasons


# 24–30 ── costs, data quality, liquidity ─────────────────────────────────

def _bracket():
    e, r = 100.0, 2.0
    return Bracket(BASELINE, "momentum", "4h", e, e - r, e - r, e + r, e + 1.8 * r, e + 2.2 * r,
                   "momentum_breakout", True, None, References(e, r, e - 1, e - r, e + 9, False), {})


def test_24_25_wide_spread_and_adverse_slippage_cost_more():
    b = _bracket()
    base = exit_ledger(b, "stop_before_t1").net_pct
    assert exit_ledger(b, "stop_before_t1", ExecutionCosts(entry_half_spread_pct=0.1, stop_half_spread_pct=0.1)).net_pct < base
    assert exit_ledger(b, "stop_before_t1", ExecutionCosts(stop_slippage_frac=0.005)).net_pct < base


def test_26_27_30_missing_book_stale_data_zero_liquidity_are_ineligible():
    missing = normalize({"symbol": "X", "timeframe": "4h", "trade_type": "momentum",
                         "order_book": {"valid": False, "spread_pct": None}})
    assert eligibility_reasons(missing, EligibilityPolicy()) == ("order_book_unavailable",)
    assert freshness_at("4h", T0 - 1, T0 + 14_400_000).reason == "superseded_by_newer_candle"


def test_28_29_tracker_flat_cost_overlaps_with_stop_fill_slippage():
    d = tracker_cost_decomposition(stop_fraction=1.0, stop_price_rel=0.98)
    assert d["fee_pct"] + d["flat_slippage_allowance_pct"] == pytest.approx(0.3)
    assert d["double_counted_slippage_pct"] == pytest.approx(0.098)
    assert tracker_cost_decomposition(0.0)["double_counted_slippage_pct"] == 0
    assert detect_cost_overlap({"stop_fill_price": ["slippage"], "flat_fee_roundtrip": ["fee", "slippage"]}) == ["slippage"]
    assert detect_cost_overlap({"per_leg_fee": ["fee"], "stop_fill_price": ["slippage"]}) == []
    led = exit_ledger(_bracket(), "stop_before_t1")
    assert led.cost_usdt / 50 * 100 == pytest.approx(0.1 + 0.1 * 0.98 * 0.999)   # per-leg: fee only


# 36–38 ── parity and determinism ─────────────────────────────────────────

def test_36_37_poll_model_gross_equals_geometry_ledger_and_labels_reconcile():
    b = _bracket()
    for name, p in (("stop", bars_path([100, 99.5], [99.0, 97.9])),
                    ("t3", bars_path([100, 100.2], [101, 102.1], [103, 103.7], [104, 104.5]))):
        out = model(p, target_1=102.0, target_2=103.6, target_3=104.4, stop_loss=98.0)
        led = exit_ledger(b, "stop_before_t1" if name == "stop" else "t3")
        if name == "t3":
            assert out.gross_pct == pytest.approx(led.tracker_gross_pct, abs=1e-9)
        assert economic_close(out.gross_usdt)["economic_result"] == economic_close(
            out.gross_pct / 100 * 50)["economic_result"]


def test_38_deterministic():
    p = CANONICAL["05_t2_then_trailing"]
    assert model(p) == model(list(p)) and cal("a", p) == cal("a", p)


def test_40_35_isolation_registry():
    import pathlib, re
    from experimental_modules import EXPERIMENTAL_SHARED
    assert {"exchange_rules", "execution_calibration"} <= set(EXPERIMENTAL_SHARED)
    root = pathlib.Path(__file__).resolve().parents[1]
    pat = re.compile(r"(from\s+shared(\.|\s+import\s+[^\n]*\b)|import\s+shared\.)(" +
                     "|".join(EXPERIMENTAL_SHARED) + r")\b")
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.py") if "tests" not in p.parts
                 and not (p.parent.name == "shared" and p.stem in EXPERIMENTAL_SHARED)
                 and pat.search(p.read_text(errors="ignore"))]
    assert offenders == []
    from shared.trade_geometry import CostFeasibleTarget
    from shared.setup_diagnostics import ExtensionCap, MarketStateGate
    assert not any(x.enabled for x in (CostFeasibleTarget(), ExtensionCap(), MarketStateGate()))
