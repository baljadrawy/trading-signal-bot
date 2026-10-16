"""DB-backed tracker lifecycle (P1-C): admission, entry, target fills, stop/exit and risk events,
with BEFORE/AFTER parity against the develop tracker. Disposable PostgreSQL + synthetic data only.

Requires P1_DB_DSN (owner DSN of a disposable cluster holding the schema template P1_SCHEMA_TEMPLATE,
default p1_schema). The before/after arm also needs P1_BEFORE_TREE (a develop checkout)."""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'trade_tracker')
import asyncio
import datetime as dt
import importlib.util
import json
import os
from urllib.parse import urlsplit

import asyncpg
import pytest

from shared import evidence_v2 as ev2
from shared.config import config
from shared.database import Database
from evidence_v2_fakes import IDENT

DSN = os.getenv('P1_DB_DSN')
TEMPLATE = os.getenv('P1_SCHEMA_TEMPLATE', 'p1_schema')
BEFORE = os.getenv('P1_BEFORE_TREE')
pytestmark = pytest.mark.skipif(not DSN, reason='P1_DB_DSN not set (disposable PostgreSQL required)')
VOLATILE = {'id', 'opened_at', 'closed_at', 'created_at', 'updated_at', 'exit_time', 'signal_time',
            'decision_at', 'analyzed_at', 'available_at', 'claimed_at', 'processed_at',
            'lease_until', 'last_error', 'payload', 'owner', 'attempts', 'date', 'signal_id',
            'active_trade_id', 'aggregate_id',
            # A38 metadata, NULL in trees before A38 (values asserted in tests/test_a38_*):
            'entry_fill_model', 'cost_usdt', 'net_profit_usdt', 'economic_result',
            'label_policy', 'deferrals', 'outcome'}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def fresh_db(name, monkeypatch):
    owner = await asyncpg.connect(DSN)
    await owner.execute(f'DROP DATABASE IF EXISTS {name}')
    await owner.execute(f'CREATE DATABASE {name} TEMPLATE {TEMPLATE}')
    await owner.close()
    u = urlsplit(DSN)
    for field, value in (('POSTGRES_HOST', u.hostname), ('POSTGRES_PORT', u.port or 5432),
                         ('POSTGRES_USER', u.username), ('POSTGRES_PASSWORD', u.password),
                         ('POSTGRES_DB', name)):
        monkeypatch.setattr(config, field, value)
    await Database.disconnect()
    await Database.connect()


SIGNALS = [  # symbol, planned entry, first observed price -> expected entry decision
    ('AAAUSDT', 10.0, 9.99),      # market fill (price <= entry)
    ('BBBUSDT', 20.0, 20.5),      # limit_wait (do not chase), filled on a later pass
    ('CCCUSDT', 30.0, 29.0),      # reject: price at/below stop before fill
]


async def seed():
    await Database.execute("INSERT INTO risk_management (date, is_trading_paused, pause_reason) "
                           "VALUES (CURRENT_DATE, false, 'manual_resume') ON CONFLICT (date) DO UPDATE "
                           "SET is_trading_paused=false, pause_reason='manual_resume'")
    for symbol, entry, _ in SIGNALS:
        identity = {'candidate_id': f'cand_{symbol.lower()}', 'candle_id': f'{symbol}|15m|0'}
        await Database.execute("""
            INSERT INTO signals (symbol, timeframe, market_condition, entry_price, target_1, target_2,
                target_3, stop_loss, score, score_details, is_paper_trade, volume_usdt,
                features_snapshot, trade_type, macro_snapshot, decision_source, strategy_version,
                telegram_sent, claude_approved, signal_time)
            VALUES ($1,'15m','ranging',$2,$3,$4,$5,$6,5,'{}',true,1e6,$7,'momentum','{}','policy_ready',
                    'sb-test',true,NULL,NOW())""",   # CR-2 contract: readiness, no Claude approval
            symbol, entry, entry * 1.02, entry * 1.036, entry * 1.044, entry * 0.98,
            json.dumps({'stop_invalidation': entry * 0.985, 'stop_policy': 'invalidation_atr_v1',
                        'identity': identity}))


async def snapshot():
    tables = {
        'active_trades': "SELECT * FROM active_trades ORDER BY symbol",
        'fills': "SELECT * FROM trade_target_fills ORDER BY symbol, target_number",
        'results': "SELECT * FROM trade_results ORDER BY symbol",
        'signals': "SELECT symbol, telegram_sent FROM signals ORDER BY symbol",
        'risk': "SELECT is_trading_paused, pause_reason, wins, losses, consecutive_losses "
                "FROM risk_management ORDER BY date",
        'outbox': "SELECT event_type, aggregate_type, status FROM outbox_events ORDER BY id",
    }
    out = {}
    for name, sql in tables.items():
        rows = []
        for r in await Database.fetch(sql):
            rows.append({k: (round(float(v), 9) if isinstance(v, (int, float)) and not isinstance(v, bool)
                             else v) for k, v in dict(r).items()
                         if k not in VOLATILE and not isinstance(v, (dt.datetime, dt.date))})
        out[name] = rows
    return json.loads(json.dumps(out, sort_keys=True, default=str))


async def run_lifecycle(mod):
    prices = {s: p for s, _, p in SIGNALS}

    async def price(symbol):
        return prices.get(symbol)

    async def min_notional(symbol):
        return 5.0

    async def no_candle(symbol, timeframe):
        return None
    mod.get_current_price, mod.get_min_notional, mod.get_last_closed_candle = price, min_notional, no_candle
    await seed()
    await mod.register_new_signals()                       # AAA fills, BBB waits, CCC rejected
    await mod.register_new_signals()                       # repeat: BBB still waits (no new state)
    [aaa] = await Database.fetch("SELECT * FROM active_trades WHERE symbol='AAAUSDT'")
    t1, t2 = float(aaa['target_1']), float(aaa['target_2'])
    for p in (t1 * 1.001, t2 * 1.001, t1 * 0.995):          # T1, T2, then the trailing stop
        prices['AAAUSDT'] = p
        await mod.evaluate_trade_safely(dict(aaa), p, 'synthetic')
    prices['BBBUSDT'] = 19.9                                # now below entry: BBB fills
    await mod.register_new_signals()
    return await snapshot()


def _run(mod, db, monkeypatch):
    async def go():
        await fresh_db(db, monkeypatch)
        try:
            return await run_lifecycle(mod)
        finally:
            await Database.disconnect()
    return asyncio.run(go())


@pytest.fixture
def tracker(monkeypatch):
    for field, value in (('MAX_OPEN_TRADES', 10), ('RISK_CANARY_MAX_OPEN_TRADES', 5),
                         ('PRICE_STREAM_ENABLED', False)):
        monkeypatch.setattr(config, field, value)
    return load('tracker_after', 'trade_tracker/main.py')


def test_lifecycle_parity_and_events(tracker, monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', False)
    ev2.reset_for_tests()
    off = _run(tracker, 'p1_after_off', monkeypatch)
    assert [t['status'] for t in off['active_trades']] == ['closed', 'open']      # AAA closed, BBB open
    assert [s['telegram_sent'] for s in off['signals']] == [True, True, False]    # CCC terminal reject
    assert len(off['fills']) == 2 and off['results'][0]['result'] == 'WIN'

    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', True)
    ev2.reset_for_tests()
    rec = ev2.RecorderV2('trade_tracker', ev2.JsonlDailySink(str(tmp_path), 'trade_tracker'), IDENT)
    ev2._RECORDERS['trade_tracker'] = rec
    on = _run(tracker, 'p1_after_on', monkeypatch)
    assert on == off                                        # recording changes no decision/row

    class Raising(ev2.RecorderV2):
        def emit(self, *a, **k):
            raise RuntimeError('recorder exploded')
    ev2._RECORDERS['trade_tracker'] = Raising('trade_tracker', ev2.ListSink(), IDENT)
    assert _run(tracker, 'p1_after_raising', monkeypatch) == off

    if BEFORE:                                              # develop f973cace vs this branch
        before = load('tracker_before', os.path.join(BEFORE, 'trade_tracker', 'main.py'))
        assert _run(before, 'p1_before', monkeypatch) == off

    rec.flush_now()
    events = [json.loads(line) for f in sorted((tmp_path / 'trade_tracker').glob('events-*.jsonl'))
              for line in f.read_text().splitlines()]
    kinds = {}
    for e in events:
        kinds.setdefault(e['event_type'], []).append(e)
    entry = {e['subject']['symbol']: e['state']['action'] for e in kinds['entry.attempt']
             if e['state']['action'] != 'limit_wait'}
    assert entry == {'AAAUSDT': 'market', 'BBBUSDT': 'market', 'CCCUSDT': 'reject'}
    waits = [e for e in kinds['entry.attempt'] if e['state']['action'] == 'limit_wait']
    assert len(waits) == 1                                  # the repeated wait was suppressed
    assert sorted(e['subject']['symbol'] for e in kinds['trade.opened']) == ['AAAUSDT', 'BBBUSDT']
    assert all(e['subject']['candidate_id'] for e in kinds['trade.opened'])
    opened = kinds['trade.opened'][0]['payload']
    assert opened['risk_decision']['allowed'] is True and opened['risk_epoch_start']
    assert opened['risk_snapshot']['open_count'] == 0 and opened['risk_limits']['max_open_trades'] == 5
    assert sorted(e['subject']['target'] for e in kinds['trade.target_hit']) == [1, 2]
    [closed] = kinds['trade.closed']
    assert closed['payload']['exit_reason'] and closed['payload']['result_row_inserted'] is True
    assert kinds['risk.state'] and kinds['admission.capacity']
    assert rec.stats()['errors'] == 0 and rec.stats()['hook_errors'] == 0

    from research.evidence_v2.reconcile import reconcile
    report = reconcile(str(tmp_path), ev2.now_ms())
    assert report['trade_lifecycle']['opened'] == 2 and report['trade_lifecycle']['closed'] == 1
    assert report['trade_lifecycle']['open_within_horizon'] == 1
    assert not [c for c, f in report['findings'].items() if f['severity'] == 'critical']
    ev2.reset_for_tests()
