"""DB-backed: with RISK_PRICE_FETCH_RETRIES > 0, an admission whose risk check needed a retry is
deferred, never opened on the fill price observed before that check. Disposable PostgreSQL and
synthetic data only.

Requires P1_DB_DSN (owner DSN of a disposable cluster holding the schema template P1_SCHEMA_TEMPLATE,
default p1_schema), as tests/test_evidence_v2_tracker_db.py.
"""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'trade_tracker')
import asyncio
import importlib.util
import json
import os
from urllib.parse import urlsplit

import asyncpg
import pytest

from shared.config import config
from shared.database import Database

DSN = os.getenv('P1_DB_DSN')
TEMPLATE = os.getenv('P1_SCHEMA_TEMPLATE', 'p1_schema')
pytestmark = pytest.mark.skipif(not DSN, reason='P1_DB_DSN not set (disposable PostgreSQL required)')


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


async def seed_signal(symbol, entry):
    identity = {'candidate_id': f'cand_{symbol.lower()}', 'candle_id': f'{symbol}|15m|0'}
    await Database.execute("""
        INSERT INTO signals (symbol, timeframe, market_condition, entry_price, target_1, target_2,
            target_3, stop_loss, score, score_details, is_paper_trade, volume_usdt,
            features_snapshot, trade_type, macro_snapshot, decision_source, strategy_version,
            telegram_sent, claude_approved, signal_time)
        VALUES ($1,'15m','ranging',$2,$3,$4,$5,$6,5,'{}',true,1e6,$7,'momentum','{}','policy_ready',
                'sb-test',true,NULL,NOW())""",
        symbol, entry, entry * 1.02, entry * 1.036, entry * 1.044, entry * 0.98,
        json.dumps({'stop_invalidation': entry * 0.985, 'stop_policy': 'invalidation_atr_v1',
                    'identity': identity}))


async def scenario(mod):
    # symbol -> scripted results (consumed first, then the steady value); None = failed fetch
    script = {}
    steady = {'AAAUSDT': 9.99, 'DDDUSDT': 39.9}
    calls = []

    async def price(symbol):
        calls.append(symbol)
        queue = script.get(symbol)
        return queue.pop(0) if queue else steady.get(symbol)

    async def min_notional(symbol):
        return 5.0

    async def no_candle(symbol, timeframe):
        return None

    mod.get_current_price, mod.get_min_notional, mod.get_last_closed_candle = price, min_notional, no_candle
    await Database.execute("INSERT INTO risk_management (date, is_trading_paused, pause_reason) "
                           "VALUES (CURRENT_DATE, false, 'manual_resume') ON CONFLICT (date) DO UPDATE "
                           "SET is_trading_paused=false, pause_reason='manual_resume'")

    async def state(symbol):
        return {
            'open': await Database.fetchval(
                "SELECT count(*) FROM active_trades WHERE symbol=$1 AND status='open'", symbol),
            'sent': await Database.fetchval(
                "SELECT telegram_sent FROM signals WHERE symbol=$1", symbol),
            'order': await Database.fetchval(
                "SELECT status FROM paper_entry_orders o JOIN signals s ON s.id=o.signal_id "
                "WHERE s.symbol=$1", symbol),
            'paused': await Database.fetchval(
                "SELECT is_trading_paused FROM risk_management ORDER BY date DESC, id DESC LIMIT 1"),
        }

    await seed_signal('AAAUSDT', 10.0)
    await mod.register_new_signals()                 # flat book: no risk price fetch; AAA opens
    after_first = await state('AAAUSDT')

    await seed_signal('DDDUSDT', 40.0)
    calls.clear()
    script['AAAUSDT'] = [None]                       # AAA's risk price fails once, then recovers
    await mod.register_new_signals()
    deferred = await state('DDDUSDT')
    deferred_calls = list(calls)

    await mod.register_new_signals()                 # next cycle: fresh prices, no retry needed
    admitted = await state('DDDUSDT')
    return after_first, deferred, deferred_calls, admitted


def _run(mod, db, monkeypatch):
    async def go():
        await fresh_db(db, monkeypatch)
        try:
            return await scenario(mod)
        finally:
            await Database.disconnect()
    return asyncio.run(go())


@pytest.fixture
def tracker(monkeypatch):
    for field, value in (('MAX_OPEN_TRADES', 10), ('RISK_CANARY_MAX_OPEN_TRADES', 5),
                         ('PRICE_STREAM_ENABLED', False), ('RISK_PRICE_FETCH_RETRIES', 1)):
        monkeypatch.setattr(config, field, value)
    return load('tracker_retry_freshness', 'trade_tracker/main.py')


def test_admission_after_a_risk_price_retry_is_deferred_not_opened(tracker, monkeypatch):
    after_first, deferred, calls, admitted = _run(tracker, 'p1_risk_retry_fresh', monkeypatch)
    assert after_first['open'] == 1 and after_first['paused'] is False
    # The DDD cycle: DDD's fill price, then AAA's risk price failed and the retry recovered it.
    assert calls.index('DDDUSDT') < calls.index('AAAUSDT') and calls.count('AAAUSDT') >= 2
    assert deferred == {'open': 0, 'sent': True, 'order': 'working', 'paused': False}
    # Next cycle observes a fresh fill price and the risk check needs no retry: DDD opens.
    assert admitted['open'] == 1 and admitted['paused'] is False
