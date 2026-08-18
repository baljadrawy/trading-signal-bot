import pytest

from shared.signal_stop import candle_invalidated, plan_signal_stop


def test_momentum_stop_is_below_breakout_with_atr_noise_allowance():
    plan = plan_signal_stop(entry=105, atr=2, trade_type='momentum',
                            structure_low=95, breakout_level=102,
                            max_risk_pct=0.05)
    assert plan.valid
    assert plan.policy == 'momentum_breakout'
    assert plan.invalidation_price == pytest.approx(101.5)
    assert plan.stop_price == pytest.approx(101.5)


def test_reversion_stop_is_below_structure_and_not_inside_one_atr():
    plan = plan_signal_stop(entry=100, atr=1, trade_type='reversion',
                            structure_low=99.5, breakout_level=None,
                            max_risk_pct=0.03)
    assert plan.valid
    assert plan.invalidation_price == pytest.approx(99.25)
    assert plan.stop_price == pytest.approx(99.0)


def test_structural_stop_too_wide_rejects_instead_of_tightening():
    plan = plan_signal_stop(entry=100, atr=4, trade_type='reversion',
                            structure_low=90, breakout_level=None,
                            max_risk_pct=0.03)
    assert not plan.valid
    assert plan.reason == 'structural_risk_exceeds_cap'
    assert plan.stop_price < 97


def test_candle_invalidation_requires_post_entry_close_and_stops_after_t1():
    assert candle_invalidated(opened_ms=100, candle_close_ms=200,
                              candle_close=96, invalidation_price=97,
                              highest_target=0)
    assert not candle_invalidated(opened_ms=100, candle_close_ms=90,
                                  candle_close=96, invalidation_price=97,
                                  highest_target=0)
    assert not candle_invalidated(opened_ms=100, candle_close_ms=200,
                                  candle_close=96, invalidation_price=97,
                                  highest_target=1)
