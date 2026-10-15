"""A44 migration 9 -> 10 -> 11 and mixed-version compatibility (disposable PostgreSQL only).

The runner below mirrors database/migrate.py exactly (schema_migrations ledger, sha256 checksum,
one `BEGIN; <file>; INSERT ledger; COMMIT` per file, checksum mismatch refused) but talks to the
test cluster; migrate.py itself is hard-wired to `docker exec postgres` (production) and is never
run. Old/A38 trees run in their own process with their own shared/ (tests/a44_tree_driver.py):
set A44_OLD_TREE (59297305) and A44_A38_TREE (fb1d40e)."""
import asyncio
import hashlib
import json
import os
import subprocess
import sys; sys.path.insert(0, '.')
import time
from pathlib import Path

import pytest

asyncpg = pytest.importorskip('asyncpg')

DSN = os.getenv('P1R_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='P1R_TEST_DSN not set (disposable PostgreSQL required)')
REPO = Path(__file__).resolve().parents[1]
BASE = [REPO / 'database' / 'init.sql', REPO / 'database' / 'migrate_features_snapshot_2026_06_23.sql',
        REPO / 'database' / 'migrate_live_learning_2026_06_25.sql']
MIGRATIONS = sorted((REPO / 'database' / 'migrations').glob('[0-9][0-9][0-9]_*.sql'))
OLD_TREE, A38_TREE = os.getenv('A44_OLD_TREE'), os.getenv('A44_A38_TREE')
DB = 'a44_migr'


async def apply(conn, upto):
    """database/migrate.py:apply, restricted to versions <= upto. Returns '+name' / '=name'."""
    await conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum CHAR(64) NOT NULL,
        applied_at TIMESTAMP NOT NULL DEFAULT NOW())""")
    applied = {r['version']: r['checksum'].strip() for r in
               await conn.fetch('SELECT version, checksum FROM schema_migrations')}
    log = []
    for path in MIGRATIONS:
        version = int(path.name.split('_', 1)[0])
        if version > upto:
            continue
        body = path.read_text(encoding='utf-8')
        checksum = hashlib.sha256(body.encode()).hexdigest()
        if version in applied:
            if applied[version] != checksum:
                raise RuntimeError(f'checksum mismatch for applied migration {path.name}')
            log.append('=' + path.name)
            continue
        await conn.execute('BEGIN')
        try:
            await conn.execute(body)
            await conn.execute('INSERT INTO schema_migrations(version,name,checksum) VALUES($1,$2,$3)',
                               version, path.name, checksum)
            await conn.execute('COMMIT')
        except BaseException:
            await conn.execute('ROLLBACK')
            raise
        log.append('+' + path.name)
    return log


async def fresh():
    admin = await asyncpg.connect(DSN)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS {DB} WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE {DB}')
    finally:
        await admin.close()
    dsn = DSN.rsplit('/', 1)[0] + '/' + DB
    conn = await asyncpg.connect(dsn)
    for path in BASE:
        await conn.execute(path.read_text(encoding='utf-8'))
    return dsn, conn


SEED = """
INSERT INTO signals (symbol,timeframe,market_condition,entry_price,target_1,target_2,target_3,stop_loss,
                     score,telegram_sent,features_snapshot,trade_type,decision_source,strategy_version)
SELECT 'H'||(g%%50)||'USDT','4h','bullish',100,102,103.6,104.4,98,3,true,'{}'::jsonb,'momentum',
       'policy_ready','sb-2026.08'
FROM generate_series(1,%d) g;
INSERT INTO signals (symbol,timeframe,market_condition,entry_price,target_1,target_2,target_3,stop_loss,score)
VALUES ('DUPUSDT','4h','x',100,102,103.6,104.4,98,3), ('DUPUSDT','4h','x',100,102,103.6,104.4,98,3);
INSERT INTO active_trades (signal_id,symbol,entry_price,target_1,target_2,target_3,stop_loss,timeframe,status)
SELECT id,symbol,entry_price,target_1,target_2,target_3,stop_loss,timeframe,'closed' FROM signals WHERE id<=200;
INSERT INTO trade_results (signal_id,symbol,entry_price,exit_price,profit_percent,profit_usdt,result)
SELECT signal_id,symbol,entry_price,101,1,0.5,'WIN' FROM active_trades;
INSERT INTO outbox_events (event_type,aggregate_type,aggregate_id,payload)
SELECT 'signal.ready','signal',id,'{}'::jsonb FROM signals WHERE id<=300;
"""
TABLES = {'signals': 'id', 'active_trades': 'id', 'trade_results': 'id', 'outbox_events': 'id'}


async def fingerprint(conn, columns):
    """Order-independent hash of each table restricted to its schema-9 columns."""
    out = {}
    for table, key in TABLES.items():
        cols = ','.join(columns[table])
        out[table] = await conn.fetchval(
            f"SELECT count(*)||':'||md5(coalesce(string_agg(md5(row({cols})::text), ',' "
            f"ORDER BY {key}),'')) FROM {table}")
    return out


async def columns_of(conn):
    return {t: [r['column_name'] for r in await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name=$1 ORDER BY ordinal_position", t)]
        for t in TABLES}


def test_migrations_9_to_10_to_11_preserve_history_and_are_idempotent():
    async def go():
        dsn, conn = await fresh()
        try:
            assert [x[0] for x in await apply(conn, 9)] == ['+'] * 9
            await conn.execute(SEED % 20000)
            cols9 = await columns_of(conn)
            fp9 = await fingerprint(conn, cols9)
            log10 = await apply(conn, 10)
            fp10 = await fingerprint(conn, cols9)
            t0 = time.monotonic()
            log11 = await apply(conn, 11)
            dt11 = time.monotonic() - t0
            fp11 = await fingerprint(conn, cols9)
            again = await apply(conn, 11)
            await conn.execute((REPO / 'database/migrations/011_a44_signal_setup_key.sql')
                               .read_text().replace('SET LOCAL', '-- SET LOCAL'))   # body re-run
            versions = [r['version'] for r in await conn.fetch('SELECT version FROM schema_migrations ORDER BY 1')]
            nulls = await conn.fetchval("SELECT count(*) FROM signals WHERE setup_key IS NOT NULL")
            dup = await conn.fetchval("SELECT count(*) FROM signals WHERE symbol='DUPUSDT'")
            col = await conn.fetchrow("SELECT is_nullable, data_type FROM information_schema.columns "
                                      "WHERE table_name='signals' AND column_name='setup_key'")
            fks = await conn.fetchval("SELECT count(*) FROM pg_constraint WHERE conrelid='signals'::regclass "
                                      "AND contype='f'")
            idx = await conn.fetchval("SELECT indexdef FROM pg_indexes WHERE indexname='uq_signals_setup_key'")
            return fp9, fp10, fp11, log10, log11, again, versions, nulls, dup, tuple(col), fks, idx, dt11
        finally:
            await conn.close()
    fp9, fp10, fp11, log10, log11, again, versions, nulls, dup, col, fks, idx, dt11 = asyncio.run(go())
    assert fp9 == fp10 == fp11                                   # no historical row changed
    assert log10[-1] == '+010_a38_execution_integrity.sql' and log11[-1] == '+011_a44_signal_setup_key.sql'
    assert all(x.startswith('=') for x in again) and versions == list(range(1, 12))
    assert nulls == 0 and dup == 2                               # no backfill; historical duplicates kept
    assert col == ('YES', 'text') and fks == 0 and 'WHERE (setup_key IS NOT NULL)' in idx
    assert dt11 < 5.0                                            # 20k signals; measured in the report


def test_unique_key_semantics_and_checksum_guard():
    async def go():
        dsn, conn = await fresh()
        try:
            await apply(conn, 11)
            ins = ("INSERT INTO signals (symbol,timeframe,market_condition,entry_price,target_1,target_2,"
                   "target_3,stop_loss,score,setup_key) VALUES ('K','4h','x',1,2,3,4,0.5,0,$1)")
            await conn.execute(ins, None)
            await conn.execute(ins, None)                        # NULLs never collide
            await conn.execute(ins, 'sk_a')
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(ins, 'sk_a')
            await conn.execute("UPDATE schema_migrations SET checksum=repeat('0',64) WHERE version=11")
            with pytest.raises(RuntimeError, match='checksum mismatch'):
                await apply(conn, 11)
        finally:
            await conn.close()
    asyncio.run(go())


def test_migration_011_fails_fast_and_atomically_behind_a_long_transaction():
    async def go():
        dsn, conn = await fresh()
        blocker = await asyncpg.connect(dsn)
        try:
            await apply(conn, 10)
            await blocker.execute('BEGIN')
            await blocker.execute("INSERT INTO signals (symbol,timeframe,market_condition,entry_price,"
                                  "target_1,target_2,target_3,stop_loss,score) VALUES ('L','4h','x',1,2,3,4,0.5,0)")
            t0 = time.monotonic()
            with pytest.raises(asyncpg.LockNotAvailableError):
                await apply(conn, 11)
            waited = time.monotonic() - t0
            await blocker.execute('ROLLBACK')
            col = await conn.fetchval("SELECT count(*) FROM information_schema.columns "
                                      "WHERE table_name='signals' AND column_name='setup_key'")
            ver = await conn.fetchval('SELECT max(version) FROM schema_migrations')
            log = await apply(conn, 11)                          # retried after the blocker ends
            return waited, col, ver, log
        finally:
            await blocker.close()
            await conn.close()
    waited, col, ver, log = asyncio.run(go())
    assert 4.5 < waited < 10 and col == 0 and ver == 10 and log[-1] == '+011_a44_signal_setup_key.sql'


def _drive(tree, dsn, symbol):
    out = subprocess.run([sys.executable, str(REPO / 'tests' / 'a44_tree_driver.py'), tree, dsn, symbol],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not (OLD_TREE and A38_TREE), reason='A44_OLD_TREE / A44_A38_TREE not set')
def test_old_and_a38_code_run_unchanged_on_schema_11_and_after_rollback():
    """Rollback order integrated -> A38 -> 59297305, schema left at 11 (no schema rollback)."""
    async def prepare():
        dsn, conn = await fresh()
        await apply(conn, 11)
        await conn.execute("INSERT INTO risk_management (date, is_trading_paused, pause_reason) "
                           "VALUES (CURRENT_DATE - 1, false, 'manual_resume')")
        # an integrated-image signal already in the table (keyed), as left behind by a rollback
        await conn.execute("INSERT INTO signals (symbol,timeframe,market_condition,entry_price,target_1,"
                           "target_2,target_3,stop_loss,score,setup_key) "
                           "VALUES ('KEYUSDT','4h','x',100,102,103.6,104.4,98,3,'sk_integrated')")
        await conn.close()
        return dsn
    dsn = asyncio.run(prepare())
    a38 = _drive(A38_TREE, dsn, 'A38USDT')
    old = _drive(OLD_TREE, dsn, 'OLDUSDT')
    assert (a38['schema_required'], old['schema_required']) == (10, 9)
    for r in (a38, old):
        assert r['signal_id'] and r['delivered'] == 1 and r['trade_opened'] and r['setup_key'] is None

    async def check():
        conn = await asyncpg.connect(dsn)
        try:
            return (await conn.fetchval("SELECT count(*) FROM signals WHERE setup_key='sk_integrated'"),
                    await conn.fetchval("SELECT count(*) FROM active_trades"),
                    await conn.fetchval("SELECT count(*) FROM outbox_events WHERE status='dead'"))
        finally:
            await conn.close()
    assert asyncio.run(check()) == (1, 2, 0)
