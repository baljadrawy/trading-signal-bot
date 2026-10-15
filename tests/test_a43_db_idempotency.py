"""A43-B database idempotency of the PROPOSED setup-key migration (disposable PostgreSQL only).

Set A43_TEST_DSN (or SIGNAL_READY_TEST_DSN) to an owner DSN of a throwaway cluster. Each test
creates a fresh database from the production schema files plus the proposed migration 011.
"""
import asyncio
import os
import sys; sys.path.insert(0, '.')
from pathlib import Path

import pytest

asyncpg = pytest.importorskip("asyncpg")

from shared.idempotent_emission import insert_signal_once
from shared.outbox import enqueue
from shared.signal_identity import bracket_hash, identity_from_candidate
from shared.signal_readiness import READY_DECISION_SOURCE, ready_payload

DSN = os.getenv("A43_TEST_DSN") or os.getenv("SIGNAL_READY_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="A43_TEST_DSN not set (disposable PostgreSQL required)")
REPO = Path(__file__).resolve().parents[1]
SCHEMA = [REPO / "database" / "init.sql",
          REPO / "database" / "migrate_features_snapshot_2026_06_23.sql",
          REPO / "database" / "migrate_live_learning_2026_06_25.sql",
          *sorted((REPO / "database" / "migrations").glob("[0-9][0-9][0-9]_*.sql"))]
PROPOSED = REPO / "docs" / "a43" / "proposed_011_signal_setup_key.sql"
DB = "a43_idem"
T0 = 20_720 * 86_400_000


def candidate(symbol="AAAUSDT", tf="4h", stop=98.0):
    return {"symbol": symbol, "timeframe": tf, "trade_type": "momentum", "market_condition": "bullish",
            "selection_policy": "fixed_execution_quality_v1", "entry_price": 100.0, "stop_loss": stop,
            "target_1": 102.0, "target_2": 103.6, "target_3": 104.4, "total_score": 3,
            "stop_policy": "momentum_breakout",
            "pit": {"candle_open_time_ms": T0, "candle_close_time_ms": T0 + 14_400_000 - 1}}


async def publish(conn, signal_id):
    await enqueue(conn, "signal.ready", "signal", signal_id, ready_payload(signal_id, "sb-2026.08"))


async def emit(conn, c, version="sb-2026.08"):
    ident = identity_from_candidate(c, strategy_version=version)
    return await insert_signal_once(conn, c, setup_key=ident.key, bracket_hash=bracket_hash(c),
                                    strategy_version=version, decision_source=READY_DECISION_SOURCE,
                                    publish=publish)


async def fresh_db(apply_proposed=True):
    admin = await asyncpg.connect(DSN)
    try:
        await admin.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
        await admin.execute(f"CREATE DATABASE {DB}")
    finally:
        await admin.close()
    dsn = DSN.rsplit("/", 1)[0] + "/" + DB
    conn = await asyncpg.connect(dsn)
    try:
        for path in SCHEMA:
            await conn.execute(path.read_text(encoding="utf-8"))
        if apply_proposed:
            for _ in range(2):                                   # idempotent re-application
                async with conn.transaction():
                    await conn.execute(PROPOSED.read_text(encoding="utf-8"))
    finally:
        await conn.close()
    return dsn


async def counts(conn):
    return (await conn.fetchval("SELECT count(*) FROM signals"),
            await conn.fetchval("SELECT count(*) FROM outbox_events WHERE event_type='signal.ready'"))


def test_migration_is_idempotent_and_old_inserts_still_work():
    async def go():
        dsn = await fresh_db()
        conn = await asyncpg.connect(dsn)
        try:
            idx = await conn.fetchval("SELECT indexdef FROM pg_indexes WHERE indexname='uq_signals_setup_key'")
            assert "UNIQUE" in idx and "WHERE (setup_key IS NOT NULL)" in idx
            for _ in range(2):                                   # an old image: no setup_key column use
                await conn.execute("""INSERT INTO signals (symbol,timeframe,market_condition,entry_price,
                    target_1,target_2,target_3,stop_loss,score) VALUES ('OLDUSDT','4h','x',1,2,3,4,0.5,0)""")
            assert await conn.fetchval("SELECT count(*) FROM signals WHERE setup_key IS NULL") == 2
        finally:
            await conn.close()
    asyncio.run(go())


def test_duplicate_and_conflict_and_version_separation():
    async def go():
        conn = await asyncpg.connect(await fresh_db())
        try:
            first = await emit(conn, candidate())
            again = await emit(conn, candidate())
            changed = await emit(conn, candidate(stop=97.0))
            other_version = await emit(conn, candidate(), version="sb-2026.09")
            assert (first.status, again.status, changed.status, other_version.status) == \
                ("created", "duplicate", "conflict", "created")
            assert again.existing_id == first.signal_id == changed.existing_id
            assert await counts(conn) == (2, 2)
        finally:
            await conn.close()
    asyncio.run(go())


def test_concurrent_workers_create_exactly_one_signal_and_event():
    async def go():
        dsn = await fresh_db()
        pool = await asyncpg.create_pool(dsn, min_size=12, max_size=12)
        try:
            async def worker():
                async with pool.acquire() as conn:
                    return await emit(conn, candidate())
            results = await asyncio.gather(*[worker() for _ in range(12)])
            statuses = sorted(r.status for r in results)
            assert statuses.count("created") == 1 and statuses.count("duplicate") == 11
            async with pool.acquire() as conn:
                assert await counts(conn) == (1, 1)
        finally:
            await pool.close()
    asyncio.run(go())


def test_restart_and_winner_rollback():
    async def go():
        dsn = await fresh_db()
        conn = await asyncpg.connect(dsn)

        async def failing_publish(c, sid):
            raise RuntimeError("publish failed")
        ident = identity_from_candidate(candidate(), strategy_version="sb-2026.08")
        with pytest.raises(RuntimeError):                        # winner aborts: row and event roll back
            await insert_signal_once(conn, candidate(), setup_key=ident.key,
                                     bracket_hash=bracket_hash(candidate()), strategy_version="sb-2026.08",
                                     decision_source=READY_DECISION_SOURCE, publish=failing_publish)
        assert await counts(conn) == (0, 0)
        assert (await emit(conn, candidate())).status == "created"
        await conn.close()
        conn = await asyncpg.connect(dsn)                        # "restart": new process, new connection
        try:
            assert (await emit(conn, candidate())).status == "duplicate"
            assert await counts(conn) == (1, 1)
        finally:
            await conn.close()
    asyncio.run(go())


def test_key_is_required():
    async def go():
        conn = await asyncpg.connect(await fresh_db())
        try:
            with pytest.raises(ValueError, match="setup_key_required"):
                await insert_signal_once(conn, candidate(), setup_key="", bracket_hash="x",
                                         strategy_version="v", decision_source="d", publish=publish)
        finally:
            await conn.close()
    asyncio.run(go())
