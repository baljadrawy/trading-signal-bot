"""A48 Phase E: Mode 2 (tracker_event_v1) vs the REAL Paper tracker on a disposable database.

Each scenario is a list of steps in hours since the signal. The REAL code paths are driven:
  rest     -> track_open_trades() (candle invalidation, then exits) then the main-loop delivery
              section (register_new_signals = the only entry path), with get_current_price and
              get_last_closed_candle returning the step's values
  ws       -> a real BinancePriceStream._handle() (aggTrade-id dedup) -> handle_stream_price()
  restart  -> a fresh stream instance and cleared module-level in-memory state
Time is moved by shifting signal_time / opened_at, so the tracker's wall clock equals the step.
The same steps become Poll events for tracker_poll_model, and every field named in
docs/a48/A48_ACCEPTANCE_CRITERIA.md (AC1) is compared. Synthetic events only (level 2)."""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests'); sys.path.insert(0, 'trade_tracker')
import asyncio
import json
import logging
import math
import time

import pytest

from shared.config import config
from shared.execution_calibration import Poll, cost_ledger, legs_from_poll_outcome, tracker_poll_model

e2e = pytest.importorskip('test_p1r_cr2_e2e')
pytestmark = e2e.pytestmark
H = 3_600_000
SYM = 'CALUSDT'
BASE = dict(trade_type='reversion', planned_entry=100.0, stop_loss=97.0, target_1=102.0,
            target_2=104.0, target_3=106.0, timeframe='4h')
S = 0.995                                             # rebase scale for a 99.5 fill
R8 = lambda x: round(x, 8)
P = 99.123456789
SP = P / 100

# name -> (signal overrides, invalidation, min_notional, steps)
SCENARIOS = {
    'entry_market_then_stop_overshoot': ({}, None, 5.0, [('rest', .1, 99.5), ('rest', .2, 96.0)]),
    'entry_rejected_below_stop': ({}, None, 5.0, [('rest', .1, 96.5), ('rest', .2, 99.0)]),
    'entry_touch_at_limit': ({}, None, 5.0, [('rest', .1, 100.5), ('rest', .2, 100.0), ('rest', .3, 98.0)]),
    'entry_skipped_by_gap': ({}, None, 5.0, [('rest', .1, 100.5), ('rest', .2, 96.0), ('rest', .3, 99.0)]),
    'entry_admission_expiry': ({}, None, 5.0, [('rest', .1, 100.5), ('rest', 2.2, 99.0)]),
    'restart_before_entry': ({}, None, 5.0, [('rest', .1, 100.5), ('restart', .15), ('rest', .2, 99.8),
                                             ('rest', .3, 102.1)]),
    'stop_exact': ({}, None, 5.0, [('rest', .1, 99.5), ('rest', .2, 97.0 * S)]),
    'stop_large_gap': ({}, None, 5.0, [('rest', .1, 99.5), ('rest', .2, 90.0)]),
    't1_then_break_even': ({}, None, 5.0, [('rest', .1, 99.5), ('rest', .2, 101.6), ('rest', .3, 99.7)]),
    't1_t2_t3_progression': ({}, None, 5.0, [('rest', .1, 99.5), ('rest', .2, 101.6), ('rest', .3, 103.6),
                                             ('rest', .4, 105.6)]),
    'same_poll_t1_t2_then_trailing': ({}, None, 5.0, [('rest', .1, 99.5), ('rest', .2, 103.6),
                                                      ('rest', .3, 104.5), ('rest', .4, 101.8)]),
    'same_poll_t1_t2_t3': ({}, None, 5.0, [('rest', .1, 99.5), ('rest', .2, 106.0)]),
    'no_t1_expiry': ({}, None, 5.0, [('rest', .1, 99.5), ('rest', 1.0, 99.8), ('rest', 25.2, 99.7)]),
    't1_expiry': ({}, None, 5.0, [('rest', .1, 99.5), ('rest', .2, 101.6), ('rest', 49.0, 100.5)]),
    'repeated_observations': ({}, None, 5.0, [('rest', .1, 99.5)] + [('rest', .2 + .01 * i, 100.0)
                                                                    for i in range(4)] + [('rest', .5, 96.4)]),
    'ws_duplicate_and_older_ids_dropped': ({}, None, 5.0, [('rest', .1, 99.5), ('ws', .2, 101.6, 10),
                                                           ('ws', .25, 101.6, 10), ('ws', .3, 99.7, 9),
                                                           ('ws', .4, 99.6, 11)]),
    'ws_older_stop_crossing_ignored': ({}, None, 5.0, [('rest', .1, 99.5), ('ws', .2, 99.0, 7),
                                                       ('ws', .25, 96.0, 6), ('rest', .3, 99.1)]),
    'delayed_processing_expires': ({}, None, 5.0, [('rest', .1, 99.5), ('rest', 30.0, 99.0)]),
    'restart_after_partial_exit': ({}, None, 5.0, [('rest', .1, 99.5), ('ws', .2, 101.6, 50),
                                                   ('restart', .25), ('ws', .3, 99.6, 1)]),
    'invalidation_rest_candle_close': ({}, 98.5, 5.0, [('rest', .1, 99.5),
                                                       ('rest', .5, 98.3, (.4, 97.9))]),
    'invalidation_not_checked_on_stream': ({}, 98.5, 5.0, [('rest', .1, 99.5), ('ws', .5, 98.3, 1),
                                                           ('rest', .6, 98.4)]),
    'invalidation_through_gap_no_slippage': ({}, 98.5, 5.0, [('rest', .1, 99.5),
                                                             ('rest', .5, 96.0, (.4, 97.0))]),
    'invalidation_candle_before_entry_ignored': ({}, 98.5, 5.0, [('rest', .1, 99.5),
                                                                 ('rest', .5, 98.3, (.05, 97.9))]),
    'momentum_setup': ({'trade_type': 'momentum'}, None, 5.0, [('rest', .1, 99.0), ('rest', .2, 95.9)]),
    'price_rounding_exact_levels': ({}, None, 5.0, [('rest', .1, P), ('rest', .2, R8(102.0 * SP)),
                                                    ('rest', .3, R8(P) * (1 + 0.003) / (1 - 0.001))]),
    'min_notional_merge_into_t2': ({}, None, 15.0, [('rest', .1, 99.5), ('rest', .2, 101.6), ('rest', .3, 103.6),
                                                    ('rest', .4, 101.4)]),
    'missing_price_skipped': ({}, None, 5.0, [('rest', .05, None), ('rest', .1, 99.5), ('rest', .2, None),
                                              ('rest', .3, 96.0)]),
}

# Behaviours the tracker does not have: classified, never "matched" by invented behaviour.
UNSUPPORTED = {
    'exchange_partial_fills': 'UNSUPPORTED_BY_TRACKER: entries and tranches fill in full at one price',
    'quantity_step_rounding': 'UNSUPPORTED_BY_TRACKER: positions are notional (USDT), no LOT_SIZE step',
    'session_trading_hours': 'NOT_APPLICABLE: the tracker has no session or trading-hour restriction',
}


def to_polls(steps):
    out = []
    for st in steps:
        kind, t = st[0], int(round(st[1] * H))
        if kind == 'restart':
            out.append(Poll(t, None, 'restart'))
        elif kind == 'ws':
            out.append(Poll(t, st[2], 'websocket', agg_id=st[3]))
        else:
            c = st[3] if len(st) > 3 else None
            out.append(Poll(t, st[2], 'rest_backup',
                            candle_close_ms=int(round(c[0] * H)) if c else None,
                            candle_close=c[1] if c else None))
    return out


def model(name):
    over, inv, mn, steps = SCENARIOS[name]
    br = {**BASE, **over}
    return tracker_poll_model(**br, polls=to_polls(steps), signal_ms=0, invalidation_price=inv,
                              min_notional=mn)


def new_stream(tr):
    from binance_price_stream import BinancePriceStream

    async def provider():
        return {SYM.lower()}
    return BinancePriceStream(symbol_provider=provider, on_price=tr.handle_stream_price,
                              logger=logging.getLogger('a48'))


async def drive(env, name, monkeypatch):
    over, inv, mn, steps = SCENARIOS[name]
    tr = env.tr
    candle = {'v': None}

    async def last_candle(*a, **k):
        if candle['v'] is None:
            return None
        hours_before_now, close = candle['v']
        return {'close_time': int(time.time() * 1000 - hours_before_now * H), 'close': close}

    async def notional(symbol):
        return mn
    monkeypatch.setattr(tr, 'get_last_closed_candle', last_candle)
    monkeypatch.setattr(tr, 'get_min_notional', notional)
    sig = {k: v for k, v in {**BASE, **over}.items() if k not in ('planned_entry', 'timeframe')}
    sid = await env.save(symbol=SYM, entry_price=BASE['planned_entry'], **sig)
    if inv is not None:
        await env.sql("UPDATE signals SET features_snapshot = COALESCE(features_snapshot, '{}'::jsonb)"
                      " || jsonb_build_object('stop_invalidation', $2::float8) WHERE id=$1", sid, inv)
    await env.telegram_pass()
    stream, fill_t = new_stream(tr), None
    for st in steps:
        kind, t = st[0], st[1]
        await env.sql("UPDATE signals SET signal_time = NOW() - make_interval(secs => $2) WHERE id=$1",
                      sid, t * 3600.0)
        tid = await env.val("SELECT id FROM active_trades WHERE signal_id=$1", sid)
        if tid and fill_t is not None:
            await env.sql("UPDATE active_trades SET opened_at = NOW() - make_interval(secs => $2) "
                          "WHERE id=$1", tid, (t - fill_t) * 3600.0)
        if kind == 'restart':
            stream = new_stream(tr)
            for attr in ('_trade_locks', '_min_notional_cache'):
                getattr(tr, attr, {}).clear()
            tr._closing.clear()
        elif kind == 'ws':
            await stream._handle(json.dumps({'e': 'aggTrade', 's': SYM, 'a': st[3], 'p': str(st[2])}),
                                 {SYM.lower()})
            while not stream._queue.empty():
                s, px = stream._queue.get_nowait()
                await stream.on_price(s, px)
        else:
            env.prices[SYM] = st[2]
            c = st[3] if len(st) > 3 else None
            candle['v'] = (t - c[0], c[1]) if c else None
            await tr.track_open_trades()
            await env.tracker_pass()
            if fill_t is None and await env.val("SELECT id FROM active_trades WHERE signal_id=$1", sid):
                fill_t = t
    return sid


async def observed(env, sid):
    trade = await env.pool.fetchrow("SELECT * FROM active_trades WHERE signal_id=$1", sid)
    fills = await env.pool.fetch("SELECT target_number, quantity_fraction, fill_price FROM trade_target_fills "
                                 "WHERE signal_id=$1 ORDER BY target_number", sid)
    res = await env.pool.fetchrow("SELECT * FROM trade_results WHERE signal_id=$1", sid)
    sent = await env.val("SELECT telegram_sent FROM signals WHERE id=$1", sid)
    return trade, fills, res, sent


def compare(m, trade, fills, res, sent) -> list:
    """Field-by-field differences (AC1). Empty list = SUPPORTED_MATCH."""
    d = []
    if m.status in ('rejected', 'not_filled'):
        if trade is not None:
            d.append(f'trade opened, model {m.status}')
        if m.status == 'rejected' and sent is not False:
            d.append('rejection not terminal (telegram_sent still true)')
        return d
    if trade is None:
        return [f'no trade, model {m.status}']
    if float(trade['entry_price']) != m.fill_price:
        d.append(f"entry {trade['entry_price']} != {m.fill_price}")
    got = [(int(f['target_number']), float(f['quantity_fraction']), float(f['fill_price'])) for f in fills]
    if len(got) != len(m.fills) or any(a[0] != b[0] or abs(a[1] - b[1]) > 1e-12 or abs(a[2] - b[2]) > 1e-8
                                       for a, b in zip(got, m.fills)):
        d.append(f'fills {got} != {list(m.fills)}')
    if m.status == 'open_at_end':
        if trade['status'] != 'open' or res is not None:
            d.append(f"closed in tracker ({res and res['notes']}), model open")
        if int(trade['highest_target_hit'] or 0) != m.target_reached:
            d.append('highest target')
        if abs(float(trade['remaining_fraction']) - m.remaining_fraction) > 1e-12:
            d.append('remaining fraction')
        return d
    if res is None:
        return d + [f'tracker open, model closed {m.exit_reason}']
    if res['notes'] != m.exit_reason:
        d.append(f"reason {res['notes']} != {m.exit_reason}")
    if abs(float(res['profit_percent']) - round(m.gross_pct, 4)) > 1e-4:
        d.append(f"gross% {res['profit_percent']} != {m.gross_pct}")
    if abs(float(res['profit_usdt']) - round(m.gross_usdt, 4)) > 1e-4:
        d.append(f"gross$ {res['profit_usdt']} != {m.gross_usdt}")
    if res['target_reached'] != m.target_reached:
        d.append('target_reached')
    if bool(res['stop_hit']) != bool(m.stop_hit):
        d.append(f"stop_hit {res['stop_hit']} != {m.stop_hit}")
    weighted = sum(fr * px for _, fr, px in m.fills) + m.exit_price * m.remaining_fraction
    if abs(float(res['exit_price']) - weighted) > 1e-8 * weighted:
        d.append(f"weighted exit {res['exit_price']} != {weighted}")
    led = cost_ledger(legs_from_poll_outcome(m))
    if (float(res['cost_usdt']), float(res['net_profit_usdt']), res['economic_result']) != \
            (0.15, led.legacy_tracker_net_usdt, led.legacy_economic_result):
        d.append(f"A38 label {res['cost_usdt']}/{res['net_profit_usdt']}/{res['economic_result']} != "
                 f"ledger {led.legacy_tracker_net_usdt}/{led.legacy_economic_result}")
    return d


@pytest.mark.parametrize('name', sorted(SCENARIOS))
def test_mode2_equals_real_tracker(name, monkeypatch, tmp_path):
    async def go():
        monkeypatch.setattr(config, 'PAPER_ENTRY_FILL_MODEL', 'observed_price_v0')
        monkeypatch.setattr(config, 'SIGNAL_INTEGRITY_MODE', 'off')
        async with e2e.Env('after', 'off', monkeypatch, tmp_path / name) as env:
            await env.resume()
            sid = await drive(env, name, monkeypatch)
            return await observed(env, sid)
    trade, fills, res, sent = asyncio.run(go())
    m = model(name)
    assert m.status != 'invalid', m.reason
    assert compare(m, trade, fills, res, sent) == [], 'SUPPORTED_MISMATCH'


def test_scenario_coverage_and_expected_semantics():
    """Pins what each scenario exercises, so a parity pass cannot come from a degenerate path."""
    want = {
        'entry_rejected_below_stop': ('rejected', None), 'entry_skipped_by_gap': ('rejected', None),
        'entry_admission_expiry': ('not_filled', None), 'entry_touch_at_limit': ('open_at_end', None),
        'restart_before_entry': ('open_at_end', None), 'stop_exact': ('closed', 'stop_loss'),
        'stop_large_gap': ('closed', 'stop_loss'), 't1_then_break_even': ('closed', 'break_even'),
        't1_t2_t3_progression': ('closed', 'T3'), 'same_poll_t1_t2_t3': ('closed', 'T3'),
        'same_poll_t1_t2_then_trailing': ('closed', 'trailing_stop'),
        'no_t1_expiry': ('closed', 'no_T1_expired_24h'), 't1_expiry': ('closed', 'T1_expired_24h'),
        'delayed_processing_expires': ('closed', 'no_T1_expired_24h'),
        'ws_duplicate_and_older_ids_dropped': ('closed', 'break_even'),
        'ws_older_stop_crossing_ignored': ('open_at_end', None),
        'restart_after_partial_exit': ('closed', 'break_even'),
        'invalidation_rest_candle_close': ('closed', 'signal_candle_invalidation'),
        'invalidation_not_checked_on_stream': ('open_at_end', None),
        'invalidation_through_gap_no_slippage': ('closed', 'signal_candle_invalidation'),
        'invalidation_candle_before_entry_ignored': ('open_at_end', None),
        'momentum_setup': ('closed', 'stop_loss'), 'price_rounding_exact_levels': ('closed', 'break_even'),
        'min_notional_merge_into_t2': ('closed', 'trailing_stop'),
        'missing_price_skipped': ('closed', 'stop_loss'),
        'entry_market_then_stop_overshoot': ('closed', 'stop_loss'),
        'repeated_observations': ('closed', 'stop_loss'),
    }
    assert set(want) == set(SCENARIOS)
    for name, (status, reason) in want.items():
        m = model(name)
        assert (m.status, m.exit_reason) == (status, reason), name
    assert model('stop_exact').exit_price == pytest.approx(R8(97.0 * S) * 0.999)
    assert model('entry_market_then_stop_overshoot').exit_price == pytest.approx(96.0 * 0.999)
    assert model('invalidation_through_gap_no_slippage').exit_price == 96.0
    assert model('same_poll_t1_t2_then_trailing').fills[:2] == ((1, 0.25, R8(102 * S)), (2, 0.5, R8(104 * S)))
    assert [f[0] for f in model('min_notional_merge_into_t2').fills] == [2]
    assert model('min_notional_merge_into_t2').remaining_fraction == 0.0
    assert model('ws_duplicate_and_older_ids_dropped').diagnostics['dropped_stream_not_newer'] == 2
    assert model('missing_price_skipped').diagnostics['skipped_missing_price'] == 2
    be = model('price_rounding_exact_levels')
    assert be.fill_price == R8(P) and be.diagnostics['observed_fill_price'] == P      # stored at 8 dp
    assert be.exit_reference_price == R8(P) * (1 + 0.003) / (1 - 0.001)              # exactly the level
    assert set(UNSUPPORTED) == {'exchange_partial_fills', 'quantity_step_rounding', 'session_trading_hours'}


def test_nan_price_is_unsafe_input_for_the_tracker(monkeypatch, tmp_path):
    """TRACKER_UNSAFE_INPUT probe: Mode 2 refuses a non-finite price (fail closed). This records
    what the REAL tracker does with one at an expiry poll; production is not changed."""
    steps = [('rest', .1, 99.5), ('rest', 25.2, float('nan'))]
    SCENARIOS['_nan_probe'] = ({}, None, 5.0, steps)
    try:
        async def go():
            monkeypatch.setattr(config, 'PAPER_ENTRY_FILL_MODEL', 'observed_price_v0')
            monkeypatch.setattr(config, 'SIGNAL_INTEGRITY_MODE', 'off')
            async with e2e.Env('after', 'off', monkeypatch, tmp_path / 'nan') as env:
                await env.resume()
                sid = await drive(env, '_nan_probe', monkeypatch)
                return await observed(env, sid)
        trade, fills, res, sent = asyncio.run(go())
        assert model('_nan_probe').reason == 'non_finite_or_non_positive_price'
        assert res is not None and res['notes'] == 'no_T1_expired_24h'
        assert math.isnan(float(res['profit_usdt'])) and res['economic_result'] == 'BREAKEVEN'
    finally:
        SCENARIOS.pop('_nan_probe', None)
