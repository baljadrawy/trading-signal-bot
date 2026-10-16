"""A47: the pure tracker poll model equals the REAL trade_tracker (A44 tree) on a disposable DB.

Signal → telegram → real register_new_signals (observed_price_v0 fill) → real
evaluate_trade_safely per poll, with opened_at shifted so the tracker's wall clock equals the
poll's elapsed time. Compared field by field with tracker_poll_model on the same events."""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
import asyncio

import pytest

from shared.config import config
from shared.execution_calibration import Poll, tracker_poll_model

e2e = pytest.importorskip('test_p1r_cr2_e2e')
pytestmark = e2e.pytestmark
H = 3_600_000
BR = dict(trade_type='reversion', planned_entry=100.0, stop_loss=97.0, target_1=102.0,
          target_2=104.0, target_3=106.0, timeframe='4h')
FILL = 99.5
PATHS = {
    'stop_exact': [(0.1, 98.0), (0.2, 97.0 * FILL / 100)],
    'stop_overshoot': [(0.1, 98.0), (0.2, 96.0)],
    't1_then_be': [(0.1, 101.6), (0.2, 102.0 * FILL / 100 + 0.01), (0.3, 99.7)],
    't3': [(0.1, 101.6), (0.2, 103.6), (0.3, 105.6)],
    'trailing': [(0.1, 101.6), (0.2, 103.6), (0.3, 104.5), (0.4, 101.8)],
    'no_t1_expiry': [(1.0, 99.8), (25.0, 99.7)],
}


def model(steps):
    polls = [Poll(0, FILL)] + [Poll(int(h * H), px) for h, px in steps]
    return tracker_poll_model(**BR, polls=polls, signal_ms=0)


@pytest.mark.parametrize('name', sorted(PATHS))
def test_poll_model_equals_real_tracker(name, monkeypatch, tmp_path):
    async def go():
        monkeypatch.setattr(config, 'PAPER_ENTRY_FILL_MODEL', 'observed_price_v0')
        monkeypatch.setattr(config, 'SIGNAL_INTEGRITY_MODE', 'off')
        async with e2e.Env('after', 'off', monkeypatch, tmp_path / name) as env:
            await env.resume()

            async def no_candle(*a, **k):
                return None
            monkeypatch.setattr(env.tr, 'get_last_closed_candle', no_candle)
            sid = await env.save(symbol='CALUSDT', trade_type='reversion', stop_loss=97.0,
                                 target_1=102.0, target_2=104.0, target_3=106.0)
            await env.telegram_pass()
            env.prices['CALUSDT'] = FILL
            await env.tracker_pass()
            tid = await env.val("SELECT id FROM active_trades WHERE signal_id=$1", sid)
            for h, px in PATHS[name]:
                await env.sql("UPDATE active_trades SET opened_at = NOW() - make_interval(secs => $2) "
                              "WHERE id=$1", tid, h * 3600.0)
                row = await env.pool.fetchrow("SELECT * FROM active_trades WHERE id=$1 AND status='open'", tid)
                if row is None:
                    break
                await env.tr.evaluate_trade_safely(dict(row), px, 'a47')
            return (await env.pool.fetchrow("SELECT * FROM trade_results WHERE signal_id=$1", sid),
                    await env.pool.fetchrow("SELECT entry_price FROM active_trades WHERE id=$1", tid))
    res, trade = asyncio.run(go())
    m = model(PATHS[name])
    assert float(trade['entry_price']) == m.fill_price
    assert res is not None and m.status == 'closed'
    assert res['notes'] == m.exit_reason
    assert float(res['profit_percent']) == pytest.approx(round(m.gross_pct, 4), abs=1e-4)
    assert float(res['profit_usdt']) == pytest.approx(round(m.gross_usdt, 4), abs=1e-4)
    assert res['target_reached'] == m.target_reached
