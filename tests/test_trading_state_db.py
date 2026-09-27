"""B3 against real PostgreSQL: the SQL, not a mock, decides the state.

Covers ordering (NULLS FIRST), CURRENT_DATE comparison, fresh/restored databases,
partial migration and outage. Skipped unless RISK_TEST_DSN points at a disposable
PostgreSQL. Never point it at production: every test truncates risk_management.
"""
import os
from datetime import date, timedelta

import pytest
import pytest_asyncio

import shared.trading_state as trading_state
from shared.trading_state import (
    RISK_STATE_INCONSISTENT, RISK_STATE_MISSING, get_pause_state)

DSN = os.getenv('RISK_TEST_DSN')
asyncpg = pytest.importorskip('asyncpg')

pytestmark = [
    pytest.mark.skipif(not DSN, reason='RISK_TEST_DSN not set (disposable PostgreSQL required)'),
    pytest.mark.asyncio,
]

# Mirrors database/init.sql exactly for the columns B3 reads.
DDL = """
CREATE TABLE IF NOT EXISTS risk_management (
    id SERIAL PRIMARY KEY,
    date DATE UNIQUE DEFAULT CURRENT_DATE,
    signals_sent INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    consecutive_losses INTEGER DEFAULT 0,
    daily_pnl_percent DECIMAL(10,4) DEFAULT 0,
    is_trading_paused BOOLEAN DEFAULT false,
    pause_reason TEXT
)"""

TODAY = date.today()


class Facade:
    """Stands in for shared.database.Database with a real connection."""

    def __init__(self, conn):
        self.conn = conn

    async def fetchrow(self, query, *args):
        return await self.conn.fetchrow(query, *args)


@pytest_asyncio.fixture
async def conn(monkeypatch):
    c = await asyncpg.connect(DSN)
    await c.execute(DDL)
    await c.execute('TRUNCATE risk_management RESTART IDENTITY')
    monkeypatch.setattr(trading_state, 'Database', Facade(c))
    yield c
    await c.close()


async def put(c, day, paused, reason):
    await c.execute(
        'INSERT INTO risk_management (date, is_trading_paused, pause_reason) '
        'VALUES ($1, $2, $3)', day, paused, reason)


async def test_fresh_empty_database_denies_trading(conn):
    assert await get_pause_state() == (True, RISK_STATE_MISSING)


async def test_counter_only_rows_are_not_an_authorization(conn):
    # signal_engine writes rows like this; they carry no pause decision.
    await put(conn, TODAY, False, None)
    await put(conn, TODAY - timedelta(days=1), False, None)
    assert await get_pause_state() == (True, RISK_STATE_MISSING)


async def test_explicit_resume_authorizes(conn):
    await put(conn, TODAY - timedelta(days=2), True, 'manual_pause')
    await put(conn, TODAY - timedelta(days=1), False, 'manual_resume')
    assert await get_pause_state() == (False, None)


async def test_latest_manual_pause_holds(conn):
    await put(conn, TODAY - timedelta(days=1), False, 'manual_resume')
    await put(conn, TODAY, True, 'manual_pause')
    assert await get_pause_state() == (True, 'manual_pause')


async def test_automatic_risk_halt_holds_across_rollover(conn):
    await put(conn, TODAY - timedelta(days=3), False, 'manual_resume')
    await put(conn, TODAY - timedelta(days=2), True, 'risk:loss_streak_halt')
    await put(conn, TODAY, False, None)          # a later counter-only day
    assert await get_pause_state() == (True, 'risk:loss_streak_halt')


async def test_undated_resume_cannot_outrank_a_real_halt(conn):
    await put(conn, TODAY, True, 'risk:loss_streak_halt')
    await put(conn, None, False, 'manual_resume')   # sorts first under DESC
    assert await get_pause_state() == (True, RISK_STATE_INCONSISTENT)


async def test_future_dated_resume_cannot_mask_todays_halt(conn):
    await put(conn, TODAY, True, 'manual_pause')
    await put(conn, TODAY + timedelta(days=30), False, 'manual_resume')
    assert await get_pause_state() == (True, RISK_STATE_INCONSISTENT)


async def test_null_paused_flag_is_rejected_by_the_real_query(conn):
    await put(conn, TODAY, None, 'manual_resume')
    assert await get_pause_state() == (True, RISK_STATE_INCONSISTENT)


async def test_restore_without_decision_rows_denies_trading(conn):
    # A backup restored from before any pause/resume decision existed.
    for d in range(5):
        await put(conn, TODAY - timedelta(days=10 + d), False, None)
    assert await get_pause_state() == (True, RISK_STATE_MISSING)


async def test_known_limitation_restored_pre_halt_resume_still_authorizes(conn):
    """Documents the residual risk rather than hiding it.

    A backup taken while trading was legitimately resumed contains a well-formed
    `manual_resume`. The database alone cannot tell it from a current one, so B3
    does not (and cannot) deny it. The loss-streak layer still recomputes from
    trade_results independently; closing this gap needs a separate mechanism.
    """
    await put(conn, TODAY - timedelta(days=20), False, 'manual_resume')
    assert await get_pause_state() == (False, None)


async def test_partial_migration_missing_table_raises(monkeypatch):
    c = await asyncpg.connect(DSN)
    try:
        await c.execute('CREATE SCHEMA IF NOT EXISTS b3_partial')
        await c.execute('SET search_path TO b3_partial')
        await c.execute('DROP TABLE IF EXISTS b3_partial.risk_management')
        monkeypatch.setattr(trading_state, 'Database', Facade(c))
        with pytest.raises(asyncpg.UndefinedTableError):
            await get_pause_state()
    finally:
        await c.execute('DROP SCHEMA IF EXISTS b3_partial CASCADE')
        await c.close()


async def test_closed_connection_raises(monkeypatch):
    c = await asyncpg.connect(DSN)
    await c.close()
    monkeypatch.setattr(trading_state, 'Database', Facade(c))
    with pytest.raises(asyncpg.InterfaceError):
        await get_pause_state()


async def test_outage_then_recovery_with_state_still_missing(monkeypatch):
    class Unreachable:
        async def fetchrow(self, *a):
            await asyncpg.connect(DSN, port=1, timeout=2)   # nothing listens

    monkeypatch.setattr(trading_state, 'Database', Unreachable())
    with pytest.raises((OSError, asyncpg.PostgresError, TimeoutError)):
        await get_pause_state()

    c = await asyncpg.connect(DSN)
    try:
        await c.execute(DDL)
        await c.execute('TRUNCATE risk_management RESTART IDENTITY')
        monkeypatch.setattr(trading_state, 'Database', Facade(c))
        assert await get_pause_state() == (True, RISK_STATE_MISSING)
    finally:
        await c.close()
