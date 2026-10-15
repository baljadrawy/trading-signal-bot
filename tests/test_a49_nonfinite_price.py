"""A49: the tracker must never act on a non-finite or non-positive price observation.

Defect (found in A48): a NaN price reaching an expiry poll was booked as a trade result with
NaN P&L, and the A38 economic label classified it BREAKEVEN. NaN, +/-inf and negative quotes
were truthy, so every `if not price` guard let them through; the stream only rejected `<= 0`.

Correction: such observations are treated exactly like a failed fetch (skipped), the stream
drops them without advancing its aggregate-id watermark, evaluate_trade_safely ignores them,
and economic_close refuses a non-finite gross instead of labelling it. Valid prices are
unchanged. The DB tests drive the real tracker on a disposable PostgreSQL (P1R_TEST_DSN)."""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests'); sys.path.insert(0, 'trade_tracker')
import asyncio
import json
import logging
import math

import pytest

from shared.fees import economic_close

BAD = [float('nan'), float('inf'), float('-inf'), 0.0, -1.0]
BAD_TEXT = ['NaN', 'nan', 'Infinity', 'inf', '-inf', '0', '0.00000000', '-1.5']


# ── pure ───────────────────────────────────────────────────────────────────

def test_economic_close_refuses_non_finite_gross_and_keeps_finite_labels():
    for bad in (float('nan'), float('inf'), float('-inf')):
        with pytest.raises(ValueError):
            economic_close(bad)
    assert economic_close(0.15)['economic_result'] == 'BREAKEVEN'
    assert economic_close(1.0)['economic_result'] == 'WIN'
    assert economic_close(-1.0)['economic_result'] == 'LOSS'


@pytest.mark.parametrize('bad', BAD)
def test_stream_drops_unusable_prices_without_advancing_the_watermark(bad):
    from binance_price_stream import BinancePriceStream

    async def go():
        async def provider():
            return {'calusdt'}

        async def sink(sym, px):
            return None
        s = BinancePriceStream(symbol_provider=provider, on_price=sink, logger=logging.getLogger('t'))
        msg = lambda a, p: json.dumps({'e': 'aggTrade', 's': 'CALUSDT', 'a': a, 'p': repr(p)})
        await s._handle(msg(7, bad), {'calusdt'})
        assert s.last_aggregate_id.get('CALUSDT') is None and s._queue.empty()
        await s._handle(msg(7, 99.5), {'calusdt'})                 # same id, valid: accepted
        return [s._queue.get_nowait() for _ in range(s._queue.qsize())]
    assert asyncio.run(go()) == [('CALUSDT', 99.5)]


# ── real tracker on a disposable database ──────────────────────────────────

e2e = pytest.importorskip('test_p1r_cr2_e2e')
db = e2e.pytestmark
ORIGINAL_GET_PRICE = e2e.modules('after')[2].get_current_price     # before any Env stubs it


class _Resp:
    def __init__(self, text):
        self.status, self._text = 200, text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self):
        return json.loads('{"price": "%s"}' % self._text)

    async def text(self):
        return self._text


def _fake_session(text):
    class S:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, *a, **k):
            return _Resp(text)
    return S


@pytest.mark.parametrize('text', BAD_TEXT)
def test_rest_quote_that_is_not_a_usable_price_is_a_failed_fetch(text, monkeypatch):
    tr = e2e.modules('after')[2]
    monkeypatch.setattr(tr.aiohttp, 'ClientSession', _fake_session(text))
    assert asyncio.run(tr.get_current_price('CALUSDT')) is None
    monkeypatch.setattr(tr.aiohttp, 'ClientSession', _fake_session('99.5'))
    assert asyncio.run(tr.get_current_price('CALUSDT')) == 99.5


async def _open_trade(env):
    sid = await env.save(symbol='CALUSDT', trade_type='reversion', stop_loss=97.0,
                         target_1=102.0, target_2=104.0, target_3=106.0)
    await env.telegram_pass()
    env.prices['CALUSDT'] = 99.5
    await env.tracker_pass()
    tid = await env.val("SELECT id FROM active_trades WHERE signal_id=$1", sid)
    assert tid is not None
    await env.sql("UPDATE active_trades SET opened_at = NOW() - INTERVAL '25 hours 12 minutes' "
                  "WHERE id=$1", tid)                                # past the 4h no-T1 expiry
    return sid, tid


@db
@pytest.mark.parametrize('bad', BAD)
def test_unusable_price_at_expiry_persists_nothing_then_a_valid_price_closes(bad, monkeypatch, tmp_path):
    from shared.config import config

    async def go():
        monkeypatch.setattr(config, 'PAPER_ENTRY_FILL_MODEL', 'observed_price_v0')
        async with e2e.Env('after', 'off', monkeypatch, tmp_path / 'x') as env:
            await env.resume()
            sid, tid = await _open_trade(env)
            row = await env.pool.fetchrow("SELECT * FROM active_trades WHERE id=$1", tid)
            await env.tr.evaluate_trade_safely(dict(row), bad, 'a49')             # direct path
            await env.tr.handle_stream_price('CALUSDT', bad)                       # stream path
            env.prices['CALUSDT'] = bad
            await env.tr.track_open_trades()                                        # REST path (stubbed)
            after_bad = (await env.val("SELECT count(*) FROM trade_results WHERE signal_id=$1", sid),
                         await env.val("SELECT status FROM active_trades WHERE id=$1", tid))
            env.prices['CALUSDT'] = 99.7
            await env.tr.track_open_trades()
            res = await env.pool.fetchrow("SELECT * FROM trade_results WHERE signal_id=$1", sid)
            return after_bad, res
    (n_bad, status_bad), res = asyncio.run(go())
    assert (n_bad, status_bad) == (0, 'open')
    assert res is not None and res['notes'] == 'no_T1_expired_24h'
    assert math.isfinite(float(res['profit_usdt'])) and float(res['exit_price']) == 99.7
    assert res['economic_result'] == economic_close(float(res['profit_usdt']))['economic_result']


@db
def test_unusable_quote_before_entry_does_not_kill_the_signal(monkeypatch, tmp_path):
    """A negative or NaN quote used to reach decide_long_entry (negative -> invalid_price ->
    signal made terminal). It is now a failed fetch, and a later valid quote still fills."""
    from shared.config import config

    async def go():
        monkeypatch.setattr(config, 'PAPER_ENTRY_FILL_MODEL', 'observed_price_v0')
        async with e2e.Env('after', 'off', monkeypatch, tmp_path / 'y') as env:
            await env.resume()
            sid = await env.save(symbol='CALUSDT', trade_type='reversion', stop_loss=97.0,
                                 target_1=102.0, target_2=104.0, target_3=106.0)
            await env.telegram_pass()
            seen = []
            for text in ('-1.5', 'NaN', '99.5'):
                monkeypatch.setattr(env.tr, 'get_current_price', ORIGINAL_GET_PRICE)  # real fetch
                monkeypatch.setattr(env.tr.aiohttp, 'ClientSession', _fake_session(text))
                await env.tracker_pass()
                seen.append((await env.val("SELECT telegram_sent FROM signals WHERE id=$1", sid),
                             await env.val("SELECT count(*) FROM active_trades WHERE signal_id=$1", sid)))
            return seen
    seen = asyncio.run(go())
    assert seen == [(True, 0), (True, 0), (True, 1)]


