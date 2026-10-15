"""A44 end-to-end signal integrity on a REAL disposable PostgreSQL (P1R_TEST_DSN; never production).

analyzer (real TechnicalAnalyzer, fake Binance client) -> signal_engine (real find_best_signal_live
+ save_signal) -> telegram (real handler, bot stubbed) -> trade_tracker (real admission, A38 entry
orders and reconciliation, real exit evaluation). SIGNAL_INTEGRITY_MODE=enforce unless stated.
Schema = init + 001..011 (the integrated candidate). Synthetic data only; no market outcome is
used and nothing here is evidence of profitability."""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests'); sys.path.insert(0, 'analyzer')
import asyncio
import json
import time

import pytest

from shared.config import config
from shared.database import Database

e2e = pytest.importorskip('test_p1r_cr2_e2e')
pytestmark = e2e.pytestmark
Env = e2e.Env
TF_MS = {'15m': 900_000, '4h': 14_400_000, '1d': 86_400_000}


def now_ms():
    return int(time.time() * 1000)


def last_closed_open(tf, at_ms=None):
    step = TF_MS[tf]
    return ((at_ms or now_ms()) // step) * step - step


def candidate(symbol='INTUSDT', tf='4h', tt='reversion', candle_open=None, spread=0.02, **kw):
    open_ms = last_closed_open(tf) if candle_open is None else candle_open
    d = {'symbol': symbol, 'timeframe': tf, 'trade_type': tt, 'market_condition': 'sideways',
         'selection_policy': 'fixed_execution_quality_v1', 'entry_reason': 'synthetic',
         'entry_price': 100.0, 'target_1': 102.0, 'target_2': 103.6, 'target_3': 104.4,
         'stop_loss': 98.0, 'stop_policy': 'reversion_structure', 'stop_valid': True,
         'stop_invalidation': 98.0, 'total_score': 3, 'score_details': {},
         'order_book': {'valid': True, 'spread_pct': spread, 'score': 1},
         'candle_identity': {'version': 1, 'candle_open_time_ms': open_ms,
                             'candle_close_time_ms': open_ms + TF_MS[tf] - 1}}
    d.update(kw)
    return d


def row(c):
    return {'symbol': c['symbol'], 'timeframe': c['timeframe'], 'analysis_data': json.dumps(c)}


class FakeMacro:
    async def should_block_now(self): return False
    def macro_state_key(self): return 'usdtd_flat'
    def snapshot(self): return {'usdtd_trend': 'flat'}
    def state(self): return {'usdtd_trend': 'flat'}


def run(fn, monkeypatch, tmp_path, mode='enforce', evidence='off'):
    async def go():
        monkeypatch.setattr(config, 'SIGNAL_INTEGRITY_MODE', mode)
        monkeypatch.setattr(config, 'PAPER_ENTRY_FILL_MODEL', 'observed_price_v0')
        monkeypatch.setattr(config, 'LEARNING_GATES_ENABLED', False)
        async with Env('after', evidence, monkeypatch, tmp_path / fn.__name__) as env:
            await env.resume()
            return await fn(env)
    return asyncio.run(go())


async def cycle(env, *cands, engine=None, at_ms=None):
    """One signal_engine cycle: select, then persist (as signal_engine/main.py does)."""
    engine = engine or env.se.SignalEngine()
    if at_ms is not None:
        engine._now_ms = lambda: at_ms
    best = await engine.find_best_signal_live([row(c) for c in cands], FakeMacro())
    sid = await engine.save_signal(best) if best else None
    return best, sid, engine


async def counts(env):
    return (await env.val("SELECT count(*) FROM signals"),
            await env.val("SELECT count(*) FROM outbox_events WHERE event_type='signal.ready'"),
            await env.val("SELECT count(*) FROM active_trades"))


async def age_signals(env, hours=3):
    """Move existing signals out of the 2 h cooldown / admission window (DB clock)."""
    await env.sql(f"UPDATE signals SET signal_time = signal_time - interval '{hours} hours'")


# ================================================================ identity and duplicates =========
def test_same_candle_repeated_scans_emit_once_even_after_cooldown(monkeypatch, tmp_path):
    async def go(env):
        _, sid, _ = await cycle(env, candidate())
        assert sid is not None
        best, _, eng = await cycle(env, candidate())                    # cooldown blocks first
        assert best is None and eng.last_decisions['INTUSDT'] == 'symbol_cooldown'
        await age_signals(env)                                         # cooldown expired
        best, _, eng = await cycle(env, candidate())
        assert best is None and eng.last_decisions['INTUSDT'] == 'duplicate_setup'
        key = await env.val("SELECT setup_key FROM signals WHERE id=$1", sid)
        snap = json.loads(await env.val("SELECT features_snapshot FROM signals WHERE id=$1", sid))
        return key, snap['setup_identity'], await counts(env)
    key, setup, c = run(go, monkeypatch, tmp_path)
    assert key == setup['key'] and key.startswith('sk_') and c == (1, 1, 0)


def test_new_candle_and_distinct_setups_are_legitimate(monkeypatch, tmp_path):
    async def go(env):
        step = TF_MS['4h']
        t_now = now_ms()
        _, a, _ = await cycle(env, candidate(candle_open=last_closed_open('4h') - step),
                              at_ms=t_now - step)                        # previous candle, then fresh
        await age_signals(env)
        _, b, _ = await cycle(env, candidate())                          # next candle, same bracket
        await age_signals(env)
        _, c, _ = await cycle(env, candidate(tf='1d'))                   # same symbol, other setup
        await age_signals(env)
        _, d, _ = await cycle(env, candidate(symbol='OTHUSDT'))
        keys = await env.pool.fetch("SELECT setup_key FROM signals ORDER BY id")
        return [a, b, c, d], [k['setup_key'] for k in keys], await counts(env)
    ids, keys, c = run(go, monkeypatch, tmp_path)
    assert all(ids) and len(set(keys)) == 4 and c == (4, 4, 0)


def test_concurrent_workers_and_restart_publish_once(monkeypatch, tmp_path):
    async def go(env):
        e1, e2 = env.se.SignalEngine(), env.se.SignalEngine()
        c = candidate()
        b1 = await e1.find_best_signal_live([row(c)], FakeMacro())       # both select before either saves
        b2 = await e2.find_best_signal_live([row(c)], FakeMacro())
        r = await asyncio.gather(e1.save_signal(b1), e2.save_signal(b2))
        loser = e2 if r[1] is None else e1
        await age_signals(env)
        restarted = env.se.SignalEngine()                                # new process
        best, _, _ = await cycle(env, candidate(), engine=restarted)
        return r, loser.last_emission, best, await counts(env)
    r, emission, best, c = run(go, monkeypatch, tmp_path)
    assert sorted(x is None for x in r) == [False, True]
    assert emission['status'] == 'duplicate' and emission['existing_signal_id'] in r
    assert best is None and c == (1, 1, 0)


def test_conflicting_bracket_on_same_candle_is_reported_not_emitted(monkeypatch, tmp_path):
    async def go(env):
        eng = env.se.SignalEngine()
        best = await eng.find_best_signal_live([row(candidate())], FakeMacro())
        await eng.save_signal(best)
        changed = dict(best, stop_loss=97.0,
                       setup_identity=dict(best['setup_identity'], bracket_hash='different'))
        out = await eng.save_signal(changed)
        return out, eng.last_emission, await counts(env)
    out, emission, c = run(go, monkeypatch, tmp_path)
    assert out is None and emission['status'] == 'conflict' and c == (1, 1, 0)


# ================================================================ freshness and identity ==========
def test_stale_and_unidentified_candidates_are_rejected(monkeypatch, tmp_path):
    async def go(env):
        step = TF_MS['4h']
        stale, _, e1 = await cycle(env, candidate(), at_ms=now_ms() + step)      # newer candle closed
        missing, _, e2 = await cycle(env, candidate(symbol='MISUSDT', candle_identity=None))
        pit = candidate()['candle_identity']                         # evidence pit only: not enough
        pit_only, _, e5 = await cycle(env, candidate(symbol='PITUSDT', candle_identity=None,
                                                     pit={'candle_open_time_ms': pit['candle_open_time_ms'],
                                                          'candle_close_time_ms': pit['candle_close_time_ms']}))
        broken, _, e3 = await cycle(env, candidate(symbol='BRKUSDT', candle_identity=None,
                                                   candle_identity_error='candle_close_inconsistent'))
        early, _, e4 = await cycle(env, candidate(symbol='ERLUSDT'),
                                   at_ms=last_closed_open('4h') + step - 10)   # before candle end
        with pytest.raises(ValueError, match='setup_identity_required'):
            await env.se.SignalEngine().save_signal({k: v for k, v in candidate().items()})
        return ([x is None for x in (stale, missing, broken, early, pit_only)],
                [e1.last_decisions['INTUSDT'], e2.last_decisions['MISUSDT'],
                 e3.last_decisions['BRKUSDT'], e4.last_decisions['ERLUSDT'],
                 e5.last_decisions['PITUSDT']], await counts(env))
    nones, reasons, c = run(go, monkeypatch, tmp_path)
    assert all(nones) and c == (0, 0, 0)
    assert reasons == ['freshness:superseded_by_newer_candle', 'identity:candle_identity_missing',
                       'identity:candle_close_inconsistent', 'freshness:decision_before_candle_close',
                       'identity:candle_identity_missing']


# ================================================================ failure safety ==================
@pytest.mark.parametrize('failing', ['COOLDOWN', 'OPEN', 'EMITTED'])
def test_database_failure_on_a_safety_read_emits_nothing(monkeypatch, tmp_path, failing):
    async def go(env):
        se = env.se
        sql = {'COOLDOWN': se.COOLDOWN_SQL, 'OPEN': se.OPEN_SYMBOLS_SQL,
               'EMITTED': se.EMITTED_SETUPS_SQL}[failing]
        real = Database.fetch

        async def fetch(q, *a):
            if q == sql:
                raise asyncio.TimeoutError()
            return await real(q, *a)
        monkeypatch.setattr(Database, 'fetch', fetch)
        best, _, eng = await cycle(env, candidate())
        monkeypatch.setattr(Database, 'fetch', real)
        recovered, sid, _ = await cycle(env, candidate())               # DB back -> emitted once
        return best, eng.last_safety_gate, sid, await counts(env)
    best, gate, sid, c = run(go, monkeypatch, tmp_path)
    expected = {'COOLDOWN': 'symbol_cooldown', 'OPEN': 'open_positions', 'EMITTED': 'emitted_setups'}
    assert best is None and gate.blocked_by == (expected[failing],)
    assert gate.events[0]['error_class'] == 'timeout' and gate.events[0]['attempts'] == 2
    assert sid is not None and c == (1, 1, 0)


def test_publication_failure_rolls_back_and_retry_creates_once(monkeypatch, tmp_path):
    async def go(env):
        eng = env.se.SignalEngine()
        best = await eng.find_best_signal_live([row(candidate())], FakeMacro())
        real = env.se.enqueue

        async def broken(*a, **k):
            raise RuntimeError('outbox unavailable')
        monkeypatch.setattr(env.se, 'enqueue', broken)
        with pytest.raises(RuntimeError):
            await eng.save_signal(best)
        after_failure = await counts(env)
        monkeypatch.setattr(env.se, 'enqueue', real)
        sid = await eng.save_signal(best)
        again = await eng.save_signal(best)
        return after_failure, sid, again, await counts(env)
    after_failure, sid, again, c = run(go, monkeypatch, tmp_path)
    assert after_failure == (0, 0, 0) and sid is not None and again is None and c == (1, 1, 0)


# ================================================================ Paper consumption ===============
def test_lifecycle_open_partial_break_even_and_accounting(monkeypatch, tmp_path):
    """Delivered once, admitted once, durable entry order filled, T1 partial, break-even close,
    economic label at close; replays of every event are no-ops."""
    async def go(env):
        _, sid, _ = await cycle(env, candidate())
        assert await env.telegram_pass() == 1
        await env.enqueue('signal.ready', sid)                          # duplicate delivery: no-op
        assert await env.telegram_pass() == 0
        env.prices['INTUSDT'] = 99.5                                    # <= entry: marketable
        await asyncio.gather(env.tracker_pass(), env.tracker_pass())    # concurrent admission
        await env.due_now(); await env.tracker_pass()
        trade = dict(await env.pool.fetchrow("SELECT * FROM active_trades WHERE signal_id=$1", sid))

        async def no_candle(*a, **k):
            return None
        monkeypatch.setattr(env.tr, 'get_last_closed_candle', no_candle)
        t1 = float(trade['target_1'])
        await env.tr.evaluate_trade_safely(trade, t1 * 1.0005, 'test')   # T1 → 25 % partial
        be = await env.pool.fetchrow("SELECT * FROM active_trades WHERE id=$1", trade['id'])
        await env.tr.evaluate_trade_safely(dict(be), float(trade['entry_price']), 'test')
        res = await env.pool.fetchrow("SELECT * FROM trade_results WHERE signal_id=$1", sid)
        order = await env.pool.fetchrow("SELECT * FROM paper_entry_orders WHERE signal_id=$1", sid)
        fills = await env.val("SELECT count(*) FROM trade_target_fills WHERE signal_id=$1", sid)
        delivered = await env.pool.fetch("SELECT status, outcome FROM outbox_events "
                                         "WHERE event_type='signal.delivered'")
        return trade, res, order, fills, [tuple(d) for d in delivered], await counts(env)
    trade, res, order, fills, delivered, c = run(go, monkeypatch, tmp_path)
    assert c == (1, 1, 1) and trade['entry_fill_model'] == 'observed_price_v0'
    assert (order['status'], order['fill_basis'], float(order['fill_price'])) == \
        ('filled', 'marketable_observed', 99.5)
    assert fills == 1 and res['notes'] == 'break_even' and res['target_reached'] == 1
    assert res['economic_result'] in ('WIN', 'LOSS', 'BREAKEVEN') and res['label_policy']
    assert float(res['net_profit_usdt']) == pytest.approx(float(res['profit_usdt'])
                                                          - float(res['cost_usdt']), abs=1e-6)
    assert delivered == [('completed', 'opened')]


def test_tracker_refuses_a_setup_superseded_while_waiting(monkeypatch, tmp_path):
    """A43 ADA/NEAR/ORCA/POL: delivered inside the 2 h window but after a newer candle closed."""
    async def go(env):
        _, sid, _ = await cycle(env, candidate())
        await env.telegram_pass()
        monkeypatch.setattr(env.tr, '_now_ms', lambda: now_ms() + TF_MS['4h'])
        env.prices['INTUSDT'] = 99.5
        await env.tracker_pass()
        sent = await env.val("SELECT telegram_sent FROM signals WHERE id=$1", sid)
        await env.due_now(); await env.tracker_pass()
        ev = await env.pool.fetchrow("SELECT status, outcome FROM outbox_events "
                                     "WHERE event_type='signal.delivered'")
        orders = await env.val("SELECT count(*) FROM paper_entry_orders")
        return sent, tuple(ev), orders, await counts(env)
    sent, ev, orders, c = run(go, monkeypatch, tmp_path)
    assert sent is False and ev == ('completed', 'terminal:ENTRY_REJECTED')
    assert orders == 0 and c == (1, 1, 0)


def test_tracker_refuses_signals_without_setup_identity_in_enforce(monkeypatch, tmp_path):
    async def go(env):
        monkeypatch.setattr(config, 'SIGNAL_INTEGRITY_MODE', 'off')      # an old-engine signal
        sid = await env.save(symbol='OLDUSDT')
        await env.telegram_pass()
        monkeypatch.setattr(config, 'SIGNAL_INTEGRITY_MODE', 'enforce')  # new tracker
        env.prices['OLDUSDT'] = 99.5
        await env.tracker_pass()
        return await env.val("SELECT telegram_sent FROM signals WHERE id=$1", sid), await counts(env)
    sent, c = run(go, monkeypatch, tmp_path)
    assert sent is False and c == (1, 1, 0)


# ================================================================ analyzer -> engine ==============
def test_real_analyzer_output_flows_through_enforce_mode(monkeypatch, tmp_path):
    from a42_synthetic import strong_trend
    import technical_analyzer as ta_mod

    def klines(tf):
        df = strong_trend(n=320)
        step = TF_MS[tf]
        last_open = last_closed_open(tf)
        out = []
        for i, r in enumerate(df.itertuples()):
            o = last_open - (len(df) - 1 - i) * step
            out.append([o, r.open, r.high, r.low, r.close, r.volume, o + step - 1, 0, 0, 0, 0, 0])
        cur = last_open + step                                           # the still-open candle
        out.append([cur, r.close, r.close, r.close, r.close, 1.0, cur + step - 1, 0, 0, 0, 0, 0])
        return out

    class FakeClient:
        async def get_klines(self, symbol, interval, limit):
            return klines(interval)

    async def go(env):
        monkeypatch.setattr(config, 'LIVE_LEARNING_MODE', True)
        tech = await ta_mod.TechnicalAnalyzer(FakeClient()).analyze('ANAUSDT', '15m')
        off_keys = None
        monkeypatch.setattr(config, 'SIGNAL_INTEGRITY_MODE', 'off')
        off = await ta_mod.TechnicalAnalyzer(FakeClient()).analyze('ANAUSDT', '15m')
        off_keys = set(off) ^ set(tech)
        monkeypatch.setattr(config, 'SIGNAL_INTEGRITY_MODE', 'enforce')
        cand = {**tech, 'order_book': {'valid': True, 'spread_pct': 0.02, 'score': 1}}
        _, sid, _ = await cycle(env, cand)
        _, again, eng = await cycle(env, cand)
        await age_signals(env)
        _, after_cooldown, eng2 = await cycle(env, cand)
        return tech, off_keys, sid, eng2.last_decisions.get('ANAUSDT'), await counts(env)
    tech, off_keys, sid, reason, c = run(go, monkeypatch, tmp_path)
    assert tech['trade_type'] == 'momentum'
    expected_open = last_closed_open('15m')
    assert tech['candle_identity'] == {'version': 1, 'candle_open_time_ms': expected_open,
                                       'candle_close_time_ms': expected_open + TF_MS['15m'] - 1}
    assert off_keys == {'candle_identity'}                               # off: block absent
    assert sid is not None and reason == 'duplicate_setup' and c == (1, 1, 0)


# ================================================================ off-mode parity =================
def test_off_mode_keeps_the_pre_a44_behaviour(monkeypatch, tmp_path):
    """off: no identity is required or written; the 2 h cooldown is again the only guard."""
    async def go(env):
        c = {k: v for k, v in candidate().items() if k != 'candle_identity'}
        _, a, _ = await cycle(env, c)
        await age_signals(env)
        _, b, _ = await cycle(env, c)                                    # re-emitted, as before A44
        keys = await env.pool.fetch("SELECT setup_key, features_snapshot FROM signals ORDER BY id")
        return a, b, [(k['setup_key'], 'setup_identity' in json.loads(k['features_snapshot']))
                      for k in keys]
    a, b, keys = run(go, monkeypatch, tmp_path, mode='off')
    assert a and b and keys == [(None, False), (None, False)]
