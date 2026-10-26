"""Collection capacity in Paper observe mode with the runtime configuration (owner item 3).

Runtime (container env, non-secret): RISK_CANARY_MAX_OPEN_TRADES=2, MAX_OPEN_TRADES unset
(default 10), TRADE_AMOUNT_USDT=50, RISK_CAPITAL_USDT=500, MAX_GROSS_EXPOSURE_PERCENT=80,
MAX_SYMBOL_EXPOSURE_PERCENT=10, STOP_ON_CONSECUTIVE_LOSSES=7.

base_max = min(min(10, 2), floor(500 * 0.8 / 50) = 8) = 2 and
effective_max = max(1, floor(base_max * multiplier)), so with any economic stop and any
sizing multiplier, observe mode admits from a flat book (collection never stops) and
capacity is never below 1; a multiplier <= 0.5 throttles 2 -> 1 (it does not stop).
No database: the tracker's Database facade is faked.
"""
import inspect
import itertools
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from shared.config import config
from shared.economic_halt_policy import (
    ECONOMIC_HARD_STOPS, OBSERVE, ENFORCE, SIZING_REASONS, classify_reason, evaluate_with_policy,
)
from shared.risk_management import RiskSnapshot

try:
    import trade_tracker.main as tracker
except ImportError:                                    # pragma: no cover
    import importlib
    tracker = importlib.import_module('main')
    if not hasattr(tracker, 'assess_new_trade_risk'):
        pytest.skip('main.py is not the trade_tracker service', allow_module_level=True)

RUNTIME = dict(RISK_CANARY_MAX_OPEN_TRADES=2, MAX_OPEN_TRADES=10, TRADE_AMOUNT_USDT=50.0,
               RISK_CAPITAL_USDT=500.0, MAX_GROSS_EXPOSURE_PERCENT=80.0,
               MAX_SYMBOL_EXPOSURE_PERCENT=10.0, STOP_ON_CONSECUTIVE_LOSSES=7)


class _DB:
    async def fetch(self, sql, *args):
        return []

    async def fetchval(self, sql, *args):
        return None

    async def fetchrow(self, sql, *args):
        return None


@pytest.fixture
def runtime_limits(monkeypatch):
    """The RiskLimits the tracker itself builds from the runtime configuration."""
    for name, value in RUNTIME.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(config, 'PAPER_TRADING', True)
    monkeypatch.setattr(config, 'PAPER_ECONOMIC_HALT_MODE', 'observe')
    monkeypatch.setattr(tracker, 'Database', _DB())
    monkeypatch.setattr('shared.risk_epoch.Database', _DB())
    monkeypatch.setattr(tracker, 'get_pause_state', AsyncMock(return_value=(False, None)))
    captured = {}
    real = tracker.evaluate_with_policy

    def capture(snapshot, limits, mode):
        captured['limits'] = limits
        return real(snapshot, limits, mode)
    monkeypatch.setattr(tracker, 'evaluate_with_policy', capture)
    import asyncio
    decision = asyncio.run(tracker.assess_new_trade_risk('BTCUSDT'))
    assert decision.allowed and decision.max_positions == 2
    return captured['limits']


def test_runtime_limits_base_capacity_is_two(runtime_limits):
    lim = runtime_limits
    assert lim.max_open_trades == 2                    # min(MAX_OPEN_TRADES=10, CANARY=2)
    assert lim.trade_amount_usdt == 50 and lim.capital_usdt == 500
    assert lim.max_gross_exposure_pct == 80 and lim.max_symbol_exposure_pct == 10
    assert lim.loss_halt_count == 7


def test_notional_is_never_scaled_by_the_sizing_multiplier():
    """Trade notional is always config.TRADE_AMOUNT_USDT: the tracker never reads the
    multiplier, so a minimum-notional floor cannot turn sizing into a stop."""
    source = inspect.getsource(tracker)
    assert 'size_multiplier' not in source and 'max_positions' not in source


# Realized / daily / weekly P&L (USDT) and loss streaks spanning every economic hard stop
# and every sizing band with the runtime limits (capital 500):
#   drawdown 6% caution / 11% warning / 16% hard; daily -3.2% hard;
#   weekly -5.2% reduce / -7.2% minimum / -10.2% hard; streak 3 reduce / 5 minimum / 7, 9 hard.
REALIZED = (0.0, -30.0, -55.0, -80.0)
DAILY = (0.0, -16.0)
WEEKLY = (0.0, -26.0, -36.0, -51.0)
STREAK = (0, 3, 5, 7, 9)
GRID = list(itertools.product(REALIZED, DAILY, WEEKLY, STREAK))


def snap(realized, daily, weekly, streak, open_count=0, symbol_open=0):
    return RiskSnapshot(realized_total_usdt=realized, daily_pnl_usdt=daily,
                        weekly_pnl_usdt=weekly, unrealized_pnl_usdt=0.0,
                        peak_equity_usdt=500.0, open_count=open_count,
                        symbol_open_count=symbol_open, consecutive_losses=streak)


def test_grid_covers_every_economic_stop_and_sizing_label(runtime_limits):
    stops, labels = set(), set()
    for case in GRID:
        d = evaluate_with_policy(snap(*case), runtime_limits, OBSERVE)
        stops.update(d.economic_flags)
        e = evaluate_with_policy(snap(*case, open_count=1), runtime_limits, OBSERVE)
        if e.reason in SIZING_REASONS:
            labels.add(e.reason)
    assert stops == ECONOMIC_HARD_STOPS
    assert labels == SIZING_REASONS


@pytest.mark.parametrize('case', GRID)
def test_observe_flat_book_always_admits_and_capacity_at_least_one(runtime_limits, case):
    d = evaluate_with_policy(snap(*case), runtime_limits, OBSERVE)
    assert d.allowed, (case, d.reason)                 # collection never stops
    assert 1 <= d.max_positions <= 2
    assert d.max_positions == max(1, int(2 * d.size_multiplier))
    legacy = evaluate_with_policy(snap(*case), runtime_limits, ENFORCE)
    if legacy.economic_flags:
        assert not legacy.allowed                      # enforce would have stopped here
        assert d.observed_economic_stop == legacy.reason


@pytest.mark.parametrize('case', GRID)
def test_observe_second_slot_is_throttled_not_stopped(runtime_limits, case):
    """open_count=1 on another symbol: multiplier <= 0.5 -> capacity 1 -> blocked by a
    sizing-labelled capacity block (the max_open_trades class); multiplier 1.0 -> admitted."""
    d = evaluate_with_policy(snap(*case, open_count=1), runtime_limits, OBSERVE)
    flat = evaluate_with_policy(snap(*case), runtime_limits, OBSERVE)
    if d.size_multiplier <= 0.5:
        assert not d.allowed and d.max_positions == 1
        assert d.reason in SIZING_REASONS and classify_reason(d.reason) == 'sizing'
        assert flat.allowed, 'same state with a flat book still admits: throttling 2 -> 1'
    else:
        assert d.allowed and d.max_positions == 2, (case, d.reason)
    # A third concurrent position is never admitted (capacity 2).
    full = evaluate_with_policy(snap(*case, open_count=2), runtime_limits, OBSERVE)
    assert not full.allowed
    assert full.reason in SIZING_REASONS | {'max_open_trades'}


@pytest.mark.parametrize('case', [GRID[0], (0.0, 0.0, 0.0, 9), (-80.0, -16.0, -51.0, 9),
                                  (-30.0, 0.0, 0.0, 0)])
def test_symbol_concentration_allows_exactly_one_per_symbol(runtime_limits, case):
    first = evaluate_with_policy(snap(*case), runtime_limits, OBSERVE)
    assert first.allowed and first.symbol_exposure_pct_after == pytest.approx(10.0)
    second = evaluate_with_policy(snap(*case, open_count=1, symbol_open=1), runtime_limits,
                                  OBSERVE)
    assert not second.allowed and second.reason == 'symbol_concentration_limit'
    assert classify_reason(second.reason) == 'portfolio'


@pytest.mark.parametrize('mode', [OBSERVE, ENFORCE])
def test_open_position_occupies_the_only_slot_under_minimum_sizing(runtime_limits, mode):
    """A long-held position plus a deep streak leaves no free slot: a portfolio-capacity
    question for the owner, deliberately not changed here."""
    d = evaluate_with_policy(snap(0.0, 0.0, 0.0, 5, open_count=1), runtime_limits, mode)
    assert not d.allowed and d.reason == 'loss_streak_minimum' and d.max_positions == 1


@pytest.mark.asyncio
async def test_tracker_path_observe_flat_book_with_streak_admits(monkeypatch, runtime_limits):
    clean_start = datetime(2026, 7, 20, tzinfo=timezone.utc)
    LOSS_USDT = -2.0

    class DB(_DB):
        async def fetch(self, sql, *args):
            if 'trade_results' in sql:
                return [dict(profit_usdt=LOSS_USDT, result='LOSS',
                             exit_time=clean_start + timedelta(hours=i)) for i in range(9)]
            return []
    monkeypatch.setattr(tracker, 'Database', DB())
    monkeypatch.setattr('shared.risk_epoch.Database', DB())
    d = await tracker.assess_new_trade_risk('BTCUSDT')
    assert d.allowed and d.reason == 'observed:loss_streak_halt'
    assert d.max_positions == 1 and d.size_multiplier == 0.1
