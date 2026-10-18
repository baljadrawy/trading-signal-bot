"""A49 follow-up: the risk guard must stay fail-closed on non-finite or missing P&L.

Hypothesis (raised in A49): a NaN `trade_results.profit_usdt` could poison the aggregate risk
metrics so that every limit comparison evaluates False (fail-open).

These tests pin what the REAL code does on a disposable PostgreSQL:
- PostgreSQL `DECIMAL(10,4)` stores NaN but rejects +/-Infinity.
- The tracker reads rows into Python floats. A NaN total reaches `evaluate_new_trade`, whose
  finite-input check refuses admission ('invalid_risk_state'). Python `nan >= 0` is False, so
  `tail_loss_streak` counts a NaN close as a LOSS (conservative) and never resets the streak.
- A NULL profit raises before any decision, so no admission happens on that cycle.
- Valid histories keep their exact previous decisions.
Pure checks need no database; the DB checks need P1R_TEST_DSN (throwaway server only)."""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
import asyncio
import math

import pytest

from shared.risk_epoch import tail_loss_streak
from shared.risk_management import RiskLimits, RiskSnapshot, evaluate_new_trade

NAN, INF = float('nan'), float('inf')
LIMITS = RiskLimits(capital_usdt=500.0, trade_amount_usdt=50.0, max_open_trades=5)


def snap(**kw):
    base = dict(realized_total_usdt=0.0, daily_pnl_usdt=0.0, weekly_pnl_usdt=0.0,
                unrealized_pnl_usdt=0.0, peak_equity_usdt=500.0, open_count=0,
                symbol_open_count=0, consecutive_losses=0)
    base.update(kw)
    return RiskSnapshot(**base)


# ── pure policy ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('field', ['realized_total_usdt', 'daily_pnl_usdt', 'weekly_pnl_usdt',
                                   'unrealized_pnl_usdt', 'peak_equity_usdt'])
@pytest.mark.parametrize('bad', [NAN, INF, -INF])
def test_policy_refuses_any_non_finite_input(field, bad):
    d = evaluate_new_trade(snap(**{field: bad}), LIMITS)
    assert (d.allowed, d.reason) == (False, 'invalid_risk_state')


def test_policy_finite_decisions_unchanged():
    assert evaluate_new_trade(snap(), LIMITS).allowed
    assert evaluate_new_trade(snap(daily_pnl_usdt=-15.0), LIMITS).reason == 'daily_loss_limit'
    assert evaluate_new_trade(snap(consecutive_losses=7), LIMITS).reason == 'loss_streak_halt'


def test_aggregate_poisoning_reaches_the_finite_check():
    """The tracker builds totals by Python addition: one NaN poisons the sum, and the policy
    then refuses instead of comparing a NaN against the limits."""
    total = sum([1.0, -2.0, NAN, 3.0])
    assert math.isnan(total)
    d = evaluate_new_trade(snap(realized_total_usdt=total, daily_pnl_usdt=total,
                                weekly_pnl_usdt=total), LIMITS)
    assert (d.allowed, d.reason) == (False, 'invalid_risk_state')


def test_loss_streak_counts_a_nan_close_as_a_loss():
    assert tail_loss_streak([1.0, -1.0, NAN, -1.0]) == 3          # NaN does not break the run
    assert tail_loss_streak([-1.0] * 6 + [NAN]) == 7                # reaches the halt count
    assert tail_loss_streak([-1.0, 0.0, -1.0]) == 1                 # finite semantics unchanged


# ── real tracker on a disposable database ──────────────────────────────────

e2e = pytest.importorskip('test_p1r_cr2_e2e')


def _rows(env, values):
    async def go():
        for i, v in enumerate(values):
            await env.sql("INSERT INTO trade_results (symbol, entry_price, exit_price, profit_percent, "
                          "profit_usdt, result, exit_time, notes) VALUES ('RGUSDT', 100, 100, 0, $1::numeric, "
                          "'LOSS', NOW() - make_interval(secs => $2), 'a49')", v, float(100 - i))
    return go()


async def _decide(env, values):
    from shared.risk_epoch import effective_consecutive_losses
    await _rows(env, values)
    decision = await env.tr.assess_new_trade_risk('RGUSDT')
    return decision, await effective_consecutive_losses()


@e2e.pytestmark
def test_db_infinity_cannot_be_stored(monkeypatch, tmp_path):
    asyncpg = pytest.importorskip('asyncpg')

    async def go():
        async with e2e.Env('after', 'off', monkeypatch, tmp_path / 'inf') as env:
            for v in ('Infinity', '-Infinity'):
                with pytest.raises(asyncpg.exceptions.NumericValueOutOfRangeError):
                    await _rows(env, [v])
    asyncio.run(go())


@e2e.pytestmark
def test_db_nan_profit_refuses_admission_and_counts_as_a_loss(monkeypatch, tmp_path):
    async def go():
        async with e2e.Env('after', 'off', monkeypatch, tmp_path / 'nan') as env:
            await env.resume()
            return await _decide(env, ['1.0', '-2.0', 'NaN'])
    decision, streak = asyncio.run(go())
    assert (decision.allowed, decision.reason) == (False, 'invalid_risk_state')
    assert streak == 2                                              # -2.0 and the NaN close


@e2e.pytestmark
def test_db_null_profit_fails_before_any_decision(monkeypatch, tmp_path):
    async def go():
        async with e2e.Env('after', 'off', monkeypatch, tmp_path / 'null') as env:
            await env.resume()
            await _rows(env, ['1.0', None])
            with pytest.raises(TypeError):
                await env.tr.assess_new_trade_risk('RGUSDT')
            from shared.risk_epoch import loss_streak_halt_active
            with pytest.raises(TypeError):
                await loss_streak_halt_active()
    asyncio.run(go())


@e2e.pytestmark
def test_db_finite_history_decisions_unchanged(monkeypatch, tmp_path):
    async def go():
        async with e2e.Env('after', 'off', monkeypatch, tmp_path / 'ok') as env:
            await env.resume()
            ok = await _decide(env, ['1.0', '-0.5'])
        async with e2e.Env('after', 'off', monkeypatch, tmp_path / 'daily') as env:
            await env.resume()
            daily = await _decide(env, ['-16.0'])
        return ok, daily
    (ok, ok_streak), (daily, _) = asyncio.run(go())
    assert ok.allowed and ok_streak == 1
    assert (daily.allowed, daily.reason) == (False, 'daily_loss_limit')
