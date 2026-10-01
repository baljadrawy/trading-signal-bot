"""CR-1 end-to-end against a REAL disposable PostgreSQL, without claude_review:

signal_engine.save_signal -> outbox 'signal.ready' -> telegram consumer
(handle_candidate_event, bot mocked) -> 'signal.delivered' -> trade_tracker
register_new_signals (real risk guard + B3 pause state) -> active_trades.

Skipped unless SIGNAL_READY_TEST_DSN points at a THROWAWAY server. The test
creates (and drops) its own database `tsb_cr1_e2e` on that server; it never
touches any other database. Never point it at production.
"""
import os
from pathlib import Path

import pytest

from cr1_support import (REPO, load_signal_logic, load_telegram_main, load_tracker_main,
                         valid_signal)

asyncpg = pytest.importorskip('asyncpg')
DSN = os.getenv('SIGNAL_READY_TEST_DSN')
DB_NAME = 'tsb_cr1_e2e'

pytestmark = pytest.mark.skipif(
    not DSN, reason='SIGNAL_READY_TEST_DSN not set (disposable PostgreSQL required)')

SCHEMA_FILES = [
    REPO / 'database' / 'init.sql',
    REPO / 'database' / 'migrate_features_snapshot_2026_06_23.sql',
    REPO / 'database' / 'migrate_live_learning_2026_06_25.sql',
    *sorted((REPO / 'database' / 'migrations').glob('[0-9][0-9][0-9]_*.sql')),
]


class Env:
    """One fresh schema per test; wires shared.database.Database to it."""

    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch

    async def __aenter__(self):
        admin = await asyncpg.connect(DSN)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)')
            await admin.execute(f'CREATE DATABASE {DB_NAME}')
        finally:
            await admin.close()
        dsn = DSN.rsplit('/', 1)[0] + '/' + DB_NAME
        conn = await asyncpg.connect(dsn)
        try:
            for path in SCHEMA_FILES:
                await conn.execute(Path(path).read_text(encoding='utf-8'))
        finally:
            await conn.close()
        self.pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)

        from shared.database import Database
        self.monkeypatch.setattr(Database, '_pool', self.pool)
        self.signal_logic = load_signal_logic()
        self.tg = load_telegram_main()
        self.tracker = load_tracker_main()
        self.monkeypatch.setattr(self.tg, 'DELIVERY_PACING_SECONDS', 0)

        async def price(symbol):
            return 99.5            # <= planned entry -> market fill for reversion

        async def notional(symbol):
            return 5.0

        self.monkeypatch.setattr(self.tracker, 'get_current_price', price)
        self.monkeypatch.setattr(self.tracker, 'get_min_notional', notional)
        self.sent_messages = []
        return self

    async def __aexit__(self, *exc):
        await self.pool.close()
        admin = await asyncpg.connect(DSN)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)')
        finally:
            await admin.close()

    # ---- helpers ------------------------------------------------------------------
    async def q(self, sql, *args):
        return await self.pool.fetch(sql, *args)

    async def val(self, sql, *args):
        return await self.pool.fetchval(sql, *args)

    async def resume(self):
        await self.pool.execute(
            "INSERT INTO risk_management (date, is_trading_paused, pause_reason) "
            "VALUES (CURRENT_DATE - 1, false, 'manual_resume')")

    async def halt_loss_streak(self):
        await self.pool.execute(
            "INSERT INTO risk_management (date, is_trading_paused, pause_reason) "
            "VALUES (CURRENT_DATE, true, 'risk:loss_streak_halt') "
            "ON CONFLICT (date) DO UPDATE SET is_trading_paused=true, "
            "pause_reason='risk:loss_streak_halt'")

    async def save(self, **overrides):
        engine = self.signal_logic.SignalEngine()
        return await engine.save_signal(valid_signal(**overrides))

    async def telegram_pass(self):
        """One iteration of telegram.signal_loop's candidate section."""
        tg = self.tg
        owner = tg.worker_id('telegram-e2e')
        mgr = tg.ApprovalManager()
        delivered = 0
        for event_type in tg.CANDIDATE_EVENT_TYPES:
            for event in await tg.claim(event_type, owner, limit=5):
                if await tg.handle_candidate_event(None, mgr, owner, event_type, event):
                    delivered += 1
        return delivered

    async def tracker_pass(self):
        """One iteration of trade_tracker's registration + delivery-ack section."""
        tr = self.tracker
        owner = tr.worker_id('tracker-e2e')
        events = await tr.claim('signal.delivered', owner, limit=50)
        await tr.register_new_signals()
        outcome = {}
        for event in events:
            if await self.val("SELECT 1 FROM active_trades WHERE signal_id=$1",
                              event['aggregate_id']):
                await tr.ack(event['id'], owner)
                outcome[event['aggregate_id']] = 'opened'
                continue
            if await self.val(tr.DELIVERY_TERMINAL_SQL, event['aggregate_id']):
                await tr.ack(event['id'], owner)
                outcome[event['aggregate_id']] = 'terminal'
            else:
                await tr.fail(event['id'], owner, RuntimeError('deferred'), 300)
                outcome[event['aggregate_id']] = 'deferred'
        return outcome

    async def events(self, signal_id):
        rows = await self.q(
            "SELECT event_type, status FROM outbox_events "
            "WHERE aggregate_type='signal' AND aggregate_id=$1 ORDER BY id", signal_id)
        return [(r['event_type'], r['status']) for r in rows]

    async def trades(self, signal_id):
        return await self.val(
            "SELECT COUNT(*) FROM active_trades WHERE signal_id=$1", signal_id)


@pytest.mark.asyncio
async def test_ready_signal_flows_to_opened_trade_without_claude_review(monkeypatch):
    async with Env(monkeypatch) as env:
        await env.resume()
        sid = await env.save()
        row = (await env.q("SELECT * FROM signals WHERE id=$1", sid))[0]
        assert row['decision_source'] == 'policy_ready'
        assert row['claude_approved'] is None and row['claude_comment'] is None
        assert await env.events(sid) == [('signal.ready', 'pending')]
        payload = await env.val(
            "SELECT payload FROM outbox_events WHERE aggregate_id=$1", sid)
        assert '"decision_source": "policy_ready"' in payload

        assert await env.telegram_pass() == 1
        assert await env.val("SELECT telegram_sent FROM signals WHERE id=$1", sid) is True
        outcome = await env.tracker_pass()
        assert outcome == {sid: 'opened'}
        assert await env.trades(sid) == 1
        assert ('trade.opened', 'pending') in [
            (r['event_type'], r['status']) for r in await env.q(
                "SELECT event_type, status FROM outbox_events WHERE aggregate_type='active_trade'")]
        assert await env.events(sid) == [
            ('signal.ready', 'completed'), ('signal.delivered', 'completed')]
        # nothing was ever produced for claude_review
        assert await env.val(
            "SELECT COUNT(*) FROM outbox_events WHERE event_type IN "
            "('signal.created','signal.reviewed')") == 0


@pytest.mark.asyncio
async def test_b3_loss_streak_halt_blocks_delivery_and_admission(monkeypatch):
    async with Env(monkeypatch) as env:
        await env.resume()
        await env.halt_loss_streak()
        sid = await env.save()
        assert await env.telegram_pass() == 0
        assert await env.val("SELECT telegram_sent FROM signals WHERE id=$1", sid) is False
        assert await env.events(sid) == [('signal.ready', 'completed')]
        assert await env.tracker_pass() == {}
        assert await env.trades(sid) == 0
        # Even a signal that was delivered before the halt cannot become a trade:
        # readiness never bypasses the tracker's risk guard.
        await env.pool.execute("UPDATE signals SET telegram_sent=true WHERE id=$1", sid)
        await env.tracker_pass()
        assert await env.trades(sid) == 0


@pytest.mark.asyncio
async def test_duplicate_events_never_duplicate_delivery_or_trade(monkeypatch):
    async with Env(monkeypatch) as env:
        await env.resume()
        sid = await env.save()
        from shared.outbox import enqueue
        async with env.pool.acquire() as conn:
            # same event again: unique (event_type, aggregate) -> no second row
            assert await enqueue(conn, 'signal.ready', 'signal', sid,
                                 {'signal_id': sid}) is None
            # a legacy event for the same signal (e.g. rollback overlap)
            await conn.execute("UPDATE signals SET claude_approved=true WHERE id=$1", sid)
            assert await enqueue(conn, 'signal.reviewed', 'signal', sid,
                                 {'signal_id': sid}) is not None
        assert await env.telegram_pass() == 1          # ready delivered, reviewed acked
        assert await env.telegram_pass() == 0
        await env.tracker_pass()
        await env.tracker_pass()
        assert await env.trades(sid) == 1
        assert await env.val(
            "SELECT COUNT(*) FROM outbox_events WHERE event_type='signal.delivered' "
            "AND aggregate_id=$1", sid) == 1
        statuses = dict(await env.events(sid))
        assert statuses == {'signal.ready': 'completed', 'signal.reviewed': 'completed',
                            'signal.delivered': 'completed'}


@pytest.mark.asyncio
async def test_not_ready_signal_is_never_delivered_or_tracked(monkeypatch):
    async with Env(monkeypatch) as env:
        await env.resume()
        sid = await env.val("""
            INSERT INTO signals (symbol, timeframe, market_condition, entry_price,
                target_1, target_2, target_3, stop_loss, score, decision_source,
                strategy_version, trade_type)
            VALUES ('NRUSDT','4h','bullish',100,102,104,106,97,4,'signal_engine','v',
                    'reversion') RETURNING id""")
        from shared.outbox import enqueue
        async with env.pool.acquire() as conn:
            await enqueue(conn, 'signal.ready', 'signal', sid, {'signal_id': sid})
            await enqueue(conn, 'signal.reviewed', 'signal', sid, {'signal_id': sid})
        assert await env.telegram_pass() == 0
        assert await env.val("SELECT telegram_sent FROM signals WHERE id=$1", sid) is False
        # Forced past telegram (corruption/manual edit): tracker still refuses it,
        # and its delivery event is terminal rather than retried.
        async with env.pool.acquire() as conn:
            await conn.execute("UPDATE signals SET telegram_sent=true WHERE id=$1", sid)
            await enqueue(conn, 'signal.delivered', 'signal', sid, {'signal_id': sid})
        assert await env.tracker_pass() == {sid: 'terminal'}
        assert await env.trades(sid) == 0


@pytest.mark.asyncio
async def test_legacy_reviewed_claude_approved_still_flows(monkeypatch):
    async with Env(monkeypatch) as env:
        await env.resume()
        sid = await env.val("""
            INSERT INTO signals (symbol, timeframe, market_condition, entry_price,
                target_1, target_2, target_3, stop_loss, score, decision_source,
                strategy_version, trade_type, claude_approved, claude_comment)
            VALUES ('LGUSDT','4h','bullish',100,102,104,106,97,4,'policy_auto','v',
                    'reversion', true, 'legacy relay') RETURNING id""")
        from shared.outbox import enqueue
        async with env.pool.acquire() as conn:
            await enqueue(conn, 'signal.reviewed', 'signal', sid,
                          {'signal_id': sid, 'approved': True})
        assert await env.telegram_pass() == 1
        assert await env.tracker_pass() == {sid: 'opened'}
        assert await env.trades(sid) == 1


@pytest.mark.asyncio
async def test_enqueue_failure_leaves_no_signal(monkeypatch):
    async with Env(monkeypatch) as env:
        await env.resume()

        async def broken(*a, **k):
            raise RuntimeError('outbox down')

        monkeypatch.setattr(env.signal_logic, 'enqueue', broken)
        with pytest.raises(RuntimeError):
            await env.save(symbol='RBUSDT')
        assert await env.val("SELECT COUNT(*) FROM signals") == 0
        assert await env.val("SELECT COUNT(*) FROM outbox_events") == 0
        assert await env.val(
            "SELECT COALESCE(SUM(signals_sent),0) FROM risk_management") == 0
