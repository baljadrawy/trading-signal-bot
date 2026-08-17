import pytest

from shared.risk_management import RiskLimits, RiskSnapshot, evaluate_new_trade


def limits(**changes):
    values = dict(capital_usdt=500, trade_amount_usdt=50, max_open_trades=10)
    values.update(changes)
    return RiskLimits(**values)


def snapshot(**changes):
    values = dict(
        realized_total_usdt=0, daily_pnl_usdt=0, weekly_pnl_usdt=0,
        unrealized_pnl_usdt=0, peak_equity_usdt=500, open_count=0,
        symbol_open_count=0, consecutive_losses=0,
    )
    values.update(changes)
    return RiskSnapshot(**values)


def test_normal_trade_respects_80_percent_total_exposure():
    decision = evaluate_new_trade(snapshot(open_count=7), limits())
    assert decision.allowed
    assert decision.gross_exposure_pct_after == 80

    blocked = evaluate_new_trade(snapshot(open_count=8), limits())
    assert not blocked.allowed
    assert blocked.reason == 'gross_exposure_limit'


def test_single_symbol_concentration_is_limited():
    decision = evaluate_new_trade(snapshot(symbol_open_count=1), limits())
    assert not decision.allowed
    assert decision.reason == 'symbol_concentration_limit'


@pytest.mark.parametrize(('field', 'value', 'reason'), [
    ('daily_pnl_usdt', -15, 'daily_loss_limit'),
    ('weekly_pnl_usdt', -50, 'weekly_loss_limit'),
    ('consecutive_losses', 7, 'loss_streak_halt'),
])
def test_hard_circuit_breakers(field, value, reason):
    decision = evaluate_new_trade(snapshot(**{field: value}), limits())
    assert not decision.allowed
    assert decision.reason == reason


def test_drawdown_uses_peak_and_includes_unrealized_pnl():
    decision = evaluate_new_trade(snapshot(
        realized_total_usdt=50, unrealized_pnl_usdt=-25,
        peak_equity_usdt=550), limits(max_drawdown_pct=4, max_daily_loss_pct=10))
    assert decision.drawdown_pct == pytest.approx(25 / 550 * 100)
    assert not decision.allowed
    assert decision.reason == 'max_drawdown_limit'


def test_soft_breakers_reduce_effective_capacity():
    streak = evaluate_new_trade(snapshot(consecutive_losses=3, open_count=4), limits())
    assert streak.size_multiplier == 0.5
    assert streak.max_positions == 4  # 80% base exposure = 8, then half.
    assert not streak.allowed
    assert streak.reason == 'loss_streak_reduce'

    warning = evaluate_new_trade(snapshot(
        realized_total_usdt=-50, peak_equity_usdt=500, open_count=1), limits())
    assert warning.size_multiplier == 0.25
    assert warning.max_positions == 2


def test_invalid_or_nonfinite_state_fails_closed():
    decision = evaluate_new_trade(snapshot(unrealized_pnl_usdt=float('nan')), limits())
    assert not decision.allowed
    assert decision.reason == 'invalid_risk_state'
