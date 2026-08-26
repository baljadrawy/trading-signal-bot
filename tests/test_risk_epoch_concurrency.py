"""Real-PostgreSQL serialization proof for recovery vs open-position creation.

RISK-1A proved the pre-fix implementation was racy: `SELECT COUNT(*)` under
READ COMMITTED takes no predicate lock on rows that do not yet exist, so a
recovery could be acknowledged on a flat-book assumption that a concurrent
admission was about to invalidate.

These tests exercise the ACTUAL `pg_advisory_xact_lock` primitive over two
independent database sessions. They deliberately do not use a Python mutex or
mock the lock -- a test that serialises the operations itself would prove
nothing about production.

Skipped unless RISK_TEST_DSN points at a disposable PostgreSQL. Never point it
at the shared production instance.
"""
import asyncio
import os
from contextlib import asynccontextmanager

import pytest

from shared.risk_epoch import RISK_ADMISSION_LOCK_KEY, tail_loss_streak

DSN = os.getenv('RISK_TEST_DSN')
asyncpg = pytest.importorskip('asyncpg')
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not DSN, reason='RISK_TEST_DSN not set (disposable PostgreSQL required)'),
]

SCHEMA = """
DROP TABLE IF EXISTS risk_recovery_events;
DROP TABLE IF EXISTS trade_results;
DROP TABLE IF EXISTS active_trades;

CREATE TABLE active_trades (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE trade_results (
    id SERIAL PRIMARY KEY,
    profit_usdt NUMERIC NOT NULL,
    exit_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE risk_recovery_events (
    id SERIAL PRIMARY KEY,
    epoch_started_at TIMESTAMPTZ NOT NULL,
    acknowledged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acknowledged_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    halt_reason TEXT NOT NULL,
    consecutive_losses_before INTEGER NOT NULL,
    open_positions_at_recovery INTEGER NOT NULL,
    CONSTRAINT risk_recovery_reason_not_blank CHECK (btrim(reason) <> ''),
    CONSTRAINT risk_recovery_actor_not_blank CHECK (btrim(acknowledged_by) <> ''),
    CONSTRAINT risk_recovery_requires_flat_book CHECK (open_positions_at_recovery = 0)
);
"""


async def fresh_schema(conn):
    await conn.execute(SCHEMA)


@asynccontextmanager
async def make_pool():
    """Explicit helper rather than an async fixture: the installed
    pytest-asyncio rejects async generator fixtures in this configuration."""
    pool = await asyncpg.create_pool(DSN, min_size=2, max_size=6)
    try:
        async with pool.acquire() as conn:
            await fresh_schema(conn)
        yield pool
    finally:
        await pool.close()


async def recovery_txn(pool, started, release, outcome):
    """The recovery critical section, mirroring shared.risk_epoch.record_recovery."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock($1)', RISK_ADMISSION_LOCK_KEY)
            started.set()
            await release.wait()          # hold the lock while the rival tries
            open_now = await conn.fetchval(
                "SELECT COUNT(*) FROM active_trades WHERE status='open'") or 0
            if open_now:
                outcome['recovery'] = f'rejected:{open_now}_open'
                return
            row = await conn.fetchrow("""
                INSERT INTO risk_recovery_events
                    (epoch_started_at, acknowledged_by, reason, halt_reason,
                     consecutive_losses_before, open_positions_at_recovery)
                VALUES (NOW(), 'operator-1', 'ack', 'loss_streak_halt', 7, 0)
                RETURNING id, epoch_started_at
            """)
            outcome['recovery'] = 'committed'
            outcome['epoch'] = row['epoch_started_at']


async def admission_txn(pool, started, release, outcome):
    """The admission critical section, mirroring trade_tracker's insert."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock($1)', RISK_ADMISSION_LOCK_KEY)
            started.set()
            await release.wait()
            await conn.execute(
                "INSERT INTO active_trades (symbol, status) VALUES ('BTCUSDT','open')")
            outcome['admission'] = 'committed'


async def test_case_a_recovery_wins_the_lock_first():
    """Admission must block until recovery commits, then see the new epoch."""
    async with make_pool() as pool:
        outcome = {}
        rec_started, rec_release = asyncio.Event(), asyncio.Event()
        adm_started, adm_release = asyncio.Event(), asyncio.Event()
        adm_release.set()                      # admission proceeds as soon as it gets the lock

        rec = asyncio.create_task(recovery_txn(pool, rec_started, rec_release, outcome))
        await asyncio.wait_for(rec_started.wait(), timeout=5)

        adm = asyncio.create_task(admission_txn(pool, adm_started, adm_release, outcome))
        # The rival must NOT be able to acquire the lock while recovery holds it.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(adm_started.wait()), timeout=1.0)
        assert 'admission' not in outcome, 'admission crossed the serialization boundary'

        rec_release.set()
        await asyncio.wait_for(rec, timeout=5)
        await asyncio.wait_for(adm, timeout=5)

        assert outcome['recovery'] == 'committed'
        assert outcome['admission'] == 'committed'
        async with pool.acquire() as conn:
            epochs = await conn.fetchval('SELECT COUNT(*) FROM risk_recovery_events')
            opened = await conn.fetchval(
                "SELECT COUNT(*) FROM active_trades WHERE status='open'")
        # The position exists only AFTER the epoch, so the flat-book assertion the
        # recovery recorded was true at the instant it was recorded.
        assert epochs == 1 and opened == 1


async def test_case_b_admission_wins_the_lock_first():
    """Recovery must block, then observe the position and refuse."""
    async with make_pool() as pool:
        outcome = {}
        adm_started, adm_release = asyncio.Event(), asyncio.Event()
        rec_started, rec_release = asyncio.Event(), asyncio.Event()
        rec_release.set()

        adm = asyncio.create_task(admission_txn(pool, adm_started, adm_release, outcome))
        await asyncio.wait_for(adm_started.wait(), timeout=5)

        rec = asyncio.create_task(recovery_txn(pool, rec_started, rec_release, outcome))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(rec_started.wait()), timeout=1.0)
        assert 'recovery' not in outcome

        adm_release.set()
        await asyncio.wait_for(adm, timeout=5)
        await asyncio.wait_for(rec, timeout=5)

        assert outcome['admission'] == 'committed'
        assert outcome['recovery'] == 'rejected:1_open', \
            'recovery must observe the committed position and refuse'
        async with pool.acquire() as conn:
            assert await conn.fetchval('SELECT COUNT(*) FROM risk_recovery_events') == 0


async def test_pre_fix_interleaving_is_no_longer_reachable():
    """Direct reproduction of the RISK-1A race, now blocked by the lock.

    Without the advisory lock the count-then-insert sequence below committed an
    epoch while a position existed. With both paths on the same lock the rival
    cannot commit inside the window at all.
    """
    async with make_pool() as pool:
        outcome = {}
        rec_started, rec_release = asyncio.Event(), asyncio.Event()
        rec = asyncio.create_task(recovery_txn(pool, rec_started, rec_release, outcome))
        await asyncio.wait_for(rec_started.wait(), timeout=5)

        async def rival_insert():
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        'SELECT pg_advisory_xact_lock($1)', RISK_ADMISSION_LOCK_KEY)
                    await conn.execute(
                        "INSERT INTO active_trades (symbol, status) VALUES ('ETHUSDT','open')")

        rival = asyncio.create_task(rival_insert())
        await asyncio.sleep(0.5)
        assert not rival.done(), 'the rival insert must be blocked by the shared lock'

        rec_release.set()
        await asyncio.wait_for(rec, timeout=5)
        await asyncio.wait_for(rival, timeout=5)
        assert outcome['recovery'] == 'committed'


async def test_advisory_lock_releases_on_rollback():
    """Transaction-scoped: an aborted recovery must not leak the lock."""
    async with make_pool() as pool:
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        'SELECT pg_advisory_xact_lock($1)', RISK_ADMISSION_LOCK_KEY)
                    raise RuntimeError('simulated failure mid-recovery')
        except RuntimeError:
            pass
        # A fresh session must be able to take it immediately.
        async with pool.acquire() as conn:
            got = await conn.fetchval(
                'SELECT pg_try_advisory_xact_lock($1)', RISK_ADMISSION_LOCK_KEY)
        assert got is True, 'lock leaked after rollback'


async def test_epoch_timestamp_is_database_generated():
    """The boundary and exit_time must come from the same clock."""
    async with make_pool() as pool:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO trade_results (profit_usdt) VALUES (-1)")
            row = await conn.fetchrow("""
                INSERT INTO risk_recovery_events
                    (epoch_started_at, acknowledged_by, reason, halt_reason,
                     consecutive_losses_before, open_positions_at_recovery)
                VALUES (NOW(), 'operator-1', 'ack', 'loss_streak_halt', 7, 0)
                RETURNING epoch_started_at
            """)
            await conn.execute("INSERT INTO trade_results (profit_usdt) VALUES (-1)")
            before = await conn.fetchval(
                'SELECT COUNT(*) FROM trade_results WHERE exit_time < $1',
                row['epoch_started_at'])
            after = await conn.fetchval(
                'SELECT COUNT(*) FROM trade_results WHERE exit_time >= $1',
                row['epoch_started_at'])
        # Exactly one on each side: the pre-recovery loss is excluded, the
        # post-recovery loss is counted. No skew window either way.
        assert (before, after) == (1, 1)


async def test_effective_streak_predicate_on_real_postgres():
    """The >= boundary rule, verified against real timestamps."""
    async with make_pool() as pool:
        async with pool.acquire() as conn:
            for _ in range(7):
                await conn.execute("INSERT INTO trade_results (profit_usdt) VALUES (-1)")
            row = await conn.fetchrow("""
                INSERT INTO risk_recovery_events
                    (epoch_started_at, acknowledged_by, reason, halt_reason,
                     consecutive_losses_before, open_positions_at_recovery)
                VALUES (NOW(), 'operator-1', 'ack', 'loss_streak_halt', 7, 0)
                RETURNING epoch_started_at
            """)
            rows = await conn.fetch(
                'SELECT profit_usdt FROM trade_results WHERE exit_time >= $1 ORDER BY exit_time, id',
                row['epoch_started_at'])
            assert tail_loss_streak(float(r['profit_usdt']) for r in rows) == 0

            for _ in range(7):
                await conn.execute("INSERT INTO trade_results (profit_usdt) VALUES (-1)")
            rows = await conn.fetch(
                'SELECT profit_usdt FROM trade_results WHERE exit_time >= $1 ORDER BY exit_time, id',
                row['epoch_started_at'])
        assert tail_loss_streak(float(r['profit_usdt']) for r in rows) == 7, \
            'seven NEW post-epoch losses must re-halt'
