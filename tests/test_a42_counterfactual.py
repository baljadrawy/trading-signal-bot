"""A42: counterfactual bracket replay — synthetic bars only (engineering properties, not edge)."""
import sys; sys.path.insert(0, '.')

import pytest

from shared.counterfactual_barrier import Bar, replay_bracket
from shared.signal_quality import CostModel, bracket_geometry, path_payoffs

T0 = 1_790_000_000_000
M15 = 900_000
BRACKET = dict(trade_type="momentum", planned_entry=100.0, stop_loss=99.0, target_1=101.0,
               target_2=101.8, target_3=102.2, signal_timeframe="15m", bar_timeframe="15m",
               decision_ms=T0)


def bars(*ohlc):
    return [Bar(T0 + i * M15, *v) for i, v in enumerate(ohlc)]


def run(*ohlc, **kw):
    return replay_bracket(**{**BRACKET, **kw, "bars": bars(*ohlc)})


PAY = path_payoffs(bracket_geometry(100, 99, 101, 101.8, 102.2), CostModel())


def test_stop_path_matches_payoff_model():
    out = run((100, 100.2, 98.8, 99.0))
    assert (out.status, out.exit_reason, out.entry_action) == ("closed", "stop_loss", "market")
    assert out.net_pct == pytest.approx(PAY["net"]["stop_before_t1"], abs=1e-3)


def test_t1_then_break_even_matches_payoff_model():
    out = run((100, 100.5, 99.8, 100.45), (100.45, 101.1, 100.45, 101.0), (101.0, 101.0, 100.3, 100.35))
    assert (out.exit_reason, out.target_reached) == ("break_even", 1)
    assert out.gross_pct == pytest.approx(PAY["gross"]["t1_then_break_even"], abs=1e-3)


def test_t3_in_one_bar_books_all_tranches():
    out = run((100, 102.5, 99.9, 102.3))
    assert (out.exit_reason, out.target_reached) == ("T3", 3)
    assert out.gross_pct == pytest.approx(PAY["gross"]["t3"], abs=1e-3)


def test_touch_at_limit_does_not_fill_but_trade_through_does():
    touch = run((100.5, 100.8, 100.0, 100.6), (100.6, 100.9, 100.0, 100.7))   # chase → limit 100
    assert (touch.status, touch.entry_action) == ("not_filled", "limit_wait")
    through = run((100.5, 100.8, 100.2, 100.6), (100.6, 100.7, 99.95, 100.3), (100.3, 102.5, 100.2, 102.3))
    assert (through.status, through.fill_price, through.fill_bar_ms) == ("closed", 100.0, T0 + M15)


def test_invalidated_while_waiting_and_admission_window():
    inv = run((100.5, 100.8, 100.2, 100.6), (100.6, 100.6, 98.9, 99.0))
    assert (inv.status, inv.reason) == ("rejected", "invalidated_while_waiting")
    late = [(100.5, 100.8, 100.2, 100.6)] * 8 + [(100.6, 100.7, 99.9, 100.1)]   # trade-through after 2 h
    assert run(*late).status == "not_filled"


def test_rejected_when_open_is_through_invalidation():
    out = run((98.9, 99.2, 98.5, 99.0))
    assert (out.status, out.reason) == ("rejected", "signal_invalidated_before_fill")


def test_gap_through_stop_fills_at_open():
    out = run((100, 100.3, 99.6, 99.8), (97.0, 97.5, 96.5, 97.2))
    assert out.exit_reason == "stop_loss" and out.exit_price == pytest.approx(97.0 * 0.999)
    assert out.net_pct < PAY["net"]["stop_before_t1"]


def test_market_fill_below_plan_rebases_bracket():
    out = run((99.5, 101.0, 99.4, 100.9))         # T1 rebased to 101 × 0.995 = 100.495
    assert out.fill_price == 99.5 and out.target_reached == 1


def test_no_t1_expiry_uses_signal_timeframe_policy():
    out = run(*[(100, 100.3, 99.7, 100.05)] * 60)    # 15m signal: no-T1 expiry 12 h = 48 bars
    assert (out.exit_reason, out.bars_used) == ("no_T1_expired_12h", 48)


def test_insufficient_bars_and_input_validation():
    assert run((100, 100.3, 99.7, 100.1)).status == "open_at_end"
    assert run((100, 100.3, 99.7, 100.1), decision_ms=T0 + 1).reason == "bar_before_decision"
    gapped = replay_bracket(**{**BRACKET, "bars": [Bar(T0, 100, 100.3, 99.7, 100.1),
                                                   Bar(T0 + 3 * M15, 100, 100.3, 99.7, 100.1)]})
    assert gapped.reason == "bar_gap"
    assert run((100, 99.0, 99.7, 100.1)).reason == "malformed_bar"
    assert run((100, 100.3, 99.7, 100.1), bar_timeframe="2h").reason == "unknown_bar_timeframe"
    assert run((100, 100.3, 99.7, 100.1), cost=CostModel(include_spread=True)).reason == \
        "spread_required_by_cost_model"


def test_spread_is_charged_when_the_cost_model_includes_it():
    plain = run((100, 100.2, 98.8, 99.0))
    spread = run((100, 100.2, 98.8, 99.0), cost=CostModel(include_spread=True), spread_pct=0.05)
    assert spread.net_pct == pytest.approx(plain.net_pct - 0.05)
