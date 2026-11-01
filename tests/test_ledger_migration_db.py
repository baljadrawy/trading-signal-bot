"""WP-E03 (PR-C04, R7.c, PR-T18): migration 012 and shared/ledger_store.py.

Offline tests always run: the migration text is additive and carries its rollback, and the store's
row mapping, replay verification and append logic hold against an in-memory connection.

Database tests need a disposable PostgreSQL and skip cleanly without one. They create and drop
their own databases, so never point them at a cluster that holds anything of value.
* ``P1R_TEST_DSN``: fresh databases built from init.sql, the two legacy migrate_* files and the
  numbered migrations. The runner mirrors database/migrate.py (schema_migrations, sha256 checksum,
  one ``BEGIN; <file>; INSERT; COMMIT`` per file), as tests/test_a44_migration_db.py does;
  migrate.py itself targets the production container and is never run.
* ``P1_DB_DSN`` + ``P1_SCHEMA_TEMPLATE``: databases cloned from the CI schema template, which
  .github/ci/build_schema_template.sh builds with every numbered migration, 012 included.

Amounts, prices and identifiers are arbitrary synthetic fixtures, not proposals for any owner
decision (PR-OD1, PR-OD2 and the rest stay open)."""
import asyncio
import copy
import dataclasses
import json
import os
import re
import sys; sys.path.insert(0, '.')
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from shared import ledger_store as store
from shared import portfolio_ledger as pl
from shared.portfolio_ledger import (Deposit, EntryFill, ExitFill, Mark, ReleaseReservation,
                                     Reserve)

try:
    import asyncpg
except ImportError:                     # the offline tests still run
    asyncpg = None

REPO = Path(__file__).resolve().parents[1]
MIGRATION = REPO / 'database' / 'migrations' / '012_portfolio_ledger.sql'
BASE = [REPO / 'database' / 'init.sql', REPO / 'database' / 'migrate_features_snapshot_2026_06_23.sql',
        REPO / 'database' / 'migrate_live_learning_2026_06_25.sql']
MIGRATIONS = sorted((REPO / 'database' / 'migrations').glob('[0-9][0-9][0-9]_*.sql'))
FRESH_DSN = os.getenv('P1R_TEST_DSN')
TEMPLATE_DSN = os.getenv('P1_DB_DSN')
TEMPLATE = os.getenv('P1_SCHEMA_TEMPLATE', 'p1_schema')
needs_fresh = pytest.mark.skipif(not FRESH_DSN or asyncpg is None,
                                 reason='P1R_TEST_DSN not set (disposable PostgreSQL required)')
needs_template = pytest.mark.skipif(not TEMPLATE_DSN or asyncpg is None,
                                    reason='P1_DB_DSN not set (disposable PostgreSQL required)')

UTC = timezone.utc
T0 = datetime(2026, 1, 5, 10, tzinfo=UTC)
Q = D('0.00000001')
USDT = 'USDT'
NEW_TABLES = {'portfolio_ledgers', 'portfolio_ledger_entries', 'portfolio_ledger_repeats'}
NEW_FUNCTIONS = {'portfolio_ledger_check_append', 'portfolio_ledger_refuse_mutation'}
NEW_TRIGGERS = {'trg_portfolio_ledger_entries_append',
                'trg_portfolio_ledgers_no_mutation', 'trg_portfolio_ledgers_no_truncate',
                'trg_portfolio_ledger_entries_no_mutation', 'trg_portfolio_ledger_entries_no_truncate',
                'trg_portfolio_ledger_repeats_no_mutation', 'trg_portfolio_ledger_repeats_no_truncate'}
NEW_INDEXES = {'idx_portfolio_ledger_entries_subject', 'idx_portfolio_ledger_entries_as_of',
               'idx_portfolio_ledger_repeats_event'}


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def rich_events():
    """Two positions with partial entries, a partial and a final exit, a stop exit, marks, a
    release and a second deposit. Trailing zeros check that canonical payloads replay exactly."""
    return [
        Deposit('d0', at(0), D('1000')),
        Reserve('r-a', at(1), 'pos-a', 'BTCUSDT', 's_a', D('120.5')),
        EntryFill('e-a1', at(2), 'pos-a', D('1'), D('50'), D('0.05'), USDT, D('0'), D('49.9')),
        EntryFill('e-a2', at(3), 'pos-a', D('1.250'), D('50.40'), D('0.063'), USDT, D('0.01')),
        ReleaseReservation('rel-a', at(4), 'pos-a'),
        Mark('m-btc-1', at(5), 'BTCUSDT', D('52.25'), 'stream'),
        Reserve('r-b', at(5), 'pos-b', 'ETHUSDT', 's_b', D('30')),
        EntryFill('e-b', at(6), 'pos-b', D('0.3'), D('99.99'), D('0.03'), USDT, D('0'), D('100')),
        ReleaseReservation('rel-b', at(6), 'pos-b'),
        ExitFill('x-a-t1', at(7), 'pos-a', 'T1', D('0.75'), D('53'), D('0.04'), USDT, D('0'), D('53.1')),
        Mark('m-eth-1', at(8), 'ETHUSDT', D('97.5'), 'rest'),
        Deposit('d1', at(9), D('25.00')),
        ExitFill('x-a-final', at(10), 'pos-a', 'final', D('1.5'), D('51.2'), D('0.0768'), USDT, D('0.02')),
        ExitFill('x-b-stop', at(11), 'pos-b', 'stop', D('0.3'), D('95.1'), D('0.0285'), USDT,
                 D('0.005'), D('96')),
    ]


def rich_ledger(ledger_id='wpe03:L1', events=None, model='research_baseline_v1'):
    ledger = pl.PortfolioLedger(ledger_id=ledger_id, quote_asset=USDT, cost_model_id=model,
                                money_quantum=Q)
    ledger.apply_all(rich_events() if events is None else events)
    return ledger


def db_row(entry):
    """``entry_row`` as the database returns it: JSONB comes back re-formatted text."""
    row = store.entry_row(entry)
    for column in ('event_payload', 'deltas'):
        row[column] = json.dumps(json.loads(row[column]))
    return row


def assert_same_ledger(loaded, ledger):
    assert loaded.state_hash == ledger.state_hash
    assert pl.state_digest(loaded.state) == pl.state_digest(ledger.state)
    assert [e.state_hash for e in loaded.entries] == [e.state_hash for e in ledger.entries]
    assert loaded.snapshot() == ledger.snapshot()


# ── migration text (offline) ───────────────────────────────────────────────────────────────

def _statements(text):
    body = text.split('-- rollback:begin', 1)[0]
    body = re.sub(r'\$\$.*?\$\$', '$$body$$', body, flags=re.S)       # function bodies
    body = '\n'.join(line.split('--', 1)[0] for line in body.splitlines())
    return [' '.join(s.split()) for s in body.split(';') if s.strip()]


def rollback_sql():
    block = MIGRATION.read_text(encoding='utf-8').split('-- rollback:begin\n', 1)[1]
    block = block.split('-- rollback:end', 1)[0]
    assert all(line.startswith('-- ') for line in block.splitlines())
    return '\n'.join(line[3:] for line in block.splitlines())


def test_migration_is_the_next_number_and_only_creates_its_own_objects():
    numbers = [int(p.name[:3]) for p in MIGRATIONS]
    assert MIGRATION in MIGRATIONS and numbers.index(12) == numbers.index(11) + 1
    allowed = (r"SET LOCAL (lock|statement)_timeout = '\d+s'",
               r'CREATE TABLE IF NOT EXISTS portfolio_ledger(s|_entries|_repeats) \(',
               r'CREATE INDEX IF NOT EXISTS idx_portfolio_ledger_\w+ ON portfolio_ledger_(entries|repeats) \(',
               r'CREATE OR REPLACE FUNCTION portfolio_ledger_\w+\(\) RETURNS trigger LANGUAGE plpgsql AS \$\$body\$\$$',
               r'CREATE OR REPLACE TRIGGER trg_portfolio_ledger\w+ BEFORE (INSERT|UPDATE OR DELETE|TRUNCATE) '
               r'ON portfolio_ledger(s|_entries|_repeats) FOR EACH (ROW|STATEMENT) EXECUTE FUNCTION portfolio_ledger_\w+\(\)$')
    statements = _statements(MIGRATION.read_text(encoding='utf-8'))
    unexpected = [s for s in statements if not any(re.match(p, s) for p in allowed)]
    assert unexpected == []
    created = {m.group(1) for s in statements for m in [re.match(
        r'CREATE (?:TABLE IF NOT EXISTS|INDEX IF NOT EXISTS|OR REPLACE FUNCTION|OR REPLACE TRIGGER) (\w+)', s)] if m}
    assert created == NEW_TABLES | NEW_FUNCTIONS | NEW_TRIGGERS | NEW_INDEXES
    references = set(re.findall(r'REFERENCES (\w+)', ' '.join(statements)))
    assert references <= NEW_TABLES                       # no foreign key into an existing table


def test_rollback_block_drops_exactly_the_new_objects():
    sql = rollback_sql()
    dropped = set(re.findall(r'DROP (?:TABLE|FUNCTION) IF EXISTS (\w+)', sql))
    assert dropped == NEW_TABLES | NEW_FUNCTIONS
    assert 'DELETE FROM schema_migrations WHERE version = 12' in sql
    assert not re.search(r'\b(ALTER|TRUNCATE|UPDATE)\b', sql)


# ── store row mapping and replay verification (offline) ───────────────────────────────────

def test_rows_replay_to_the_same_hash_as_the_in_memory_ledger():
    ledger = rich_ledger()
    rows = [db_row(e) for e in ledger.entries]
    loaded = store.ledger_from_rows(store.header_row(ledger), rows)
    assert_same_ledger(loaded, ledger)
    payload = json.loads(rows[3]['event_payload'])
    assert payload['qty'] == '1.25' and payload['price'] == '50.4'     # canonical exact strings
    assert all(isinstance(v, str) for r in rows for v in json.loads(r['deltas']).values())
    subjects = [(r['event_type'], r['subject_id'], r['symbol']) for r in rows[:6]]
    assert subjects == [('Deposit', None, None), ('Reserve', 'pos-a', 'BTCUSDT'),
                        ('EntryFill', 'pos-a', None), ('EntryFill', 'pos-a', None),
                        ('ReleaseReservation', 'pos-a', None), ('Mark', None, 'BTCUSDT')]
    assert rows[0]['prev_state_hash'] == pl.GENESIS_HASH
    assert all(r['entry_id'] == f"wpe03:L1:{r['sequence']}" for r in rows)


def _tampered(rows, index, column, change):
    rows = copy.deepcopy(rows)
    if column in ('event_payload', 'deltas'):
        value = json.loads(rows[index][column])
        change(value)
        rows[index][column] = json.dumps(value)
    else:
        rows[index][column] = change(rows[index][column])
    return rows


@pytest.mark.parametrize('index, column, change', [
    (0, 'event_payload', lambda p: p.update(amount='1001')),             # a different genesis
    (9, 'event_payload', lambda p: p.update(price='53.01')),
    (4, 'deltas', lambda d: d.update(reserved='0')),
    (6, 'state_hash', lambda h: 'f' * 64),
    (6, 'prev_state_hash', lambda h: 'e' * 64),
    (2, 'event_fingerprint', lambda h: '0' * 64),
    (7, 'as_of', lambda t: t + timedelta(microseconds=1)),
    (5, 'symbol', lambda s: 'ETHUSDT'),
])
def test_tampered_rows_are_refused_never_repaired(index, column, change):
    ledger = rich_ledger()
    rows = _tampered([db_row(e) for e in ledger.entries], index, column, change)
    with pytest.raises(pl.LedgerError):
        store.ledger_from_rows(store.header_row(ledger), rows)


def test_missing_reordered_or_foreign_rows_are_refused():
    ledger = rich_ledger()
    header = store.header_row(ledger)
    rows = [db_row(e) for e in ledger.entries]
    for broken in (rows[:3] + rows[4:], [rows[1], rows[0]] + rows[2:]):
        with pytest.raises(pl.LedgerInvariantViolation):
            store.ledger_from_rows(header, broken)
    with pytest.raises(store.LedgerStoreError, match='ledger_version_mismatch'):
        store.ledger_from_rows({**header, 'ledger_version': 'other'}, rows)
    other = rich_ledger(model='research_stress_v1')
    with pytest.raises(pl.LedgerInvariantViolation):     # the cost model enters every hash
        store.ledger_from_rows({**header, 'cost_model_id': 'research_stress_v1'}, rows)
    assert other.state_hash != ledger.state_hash


@pytest.mark.parametrize('event_type, payload, reason', [
    ('Correction', {'event_id': 'c1'}, 'event_type_unsupported'),
    ('Deposit', {'event_id': 'd0', 'as_of': T0.isoformat(), 'amount': 5}, 'payload_shape'),
    ('Deposit', {'event_id': 'd0', 'as_of': T0.isoformat(), 'amount': '5', 'x': '1'}, 'payload_shape'),
    ('Deposit', {'event_id': 'd0', 'as_of': T0.isoformat(), 'amount': 'five'}, 'payload_shape'),
    ('Deposit', {'event_id': 'd0', 'as_of': 'yesterday', 'amount': '5'}, 'payload_shape'),
    ('Mark', {'event_id': 'm', 'as_of': T0.isoformat(), 'symbol': 'X', 'price': None,
              'source': 's'}, 'payload_shape'),
])
def test_event_payload_shape_is_strict(event_type, payload, reason):
    with pytest.raises(store.LedgerStoreError) as info:
        store.event_from_payload(event_type, payload)
    assert info.value.reason == reason


class FakeConn:
    """In-memory stand-in for the four store statements, with a rollback-able transaction and
    the database's gap-free chain rule (sqlstate 23514), to test the append logic offline."""

    class Refusal(Exception):
        sqlstate = '23514'

    def __init__(self):
        self.ledgers, self.entries, self.repeats = {}, {}, []

    def transaction(self):
        conn = self

        class Tx:
            async def __aenter__(self):
                self.saved = copy.deepcopy((conn.ledgers, conn.entries, conn.repeats))

            async def __aexit__(self, kind, exc, tb):
                if kind is not None:
                    conn.ledgers, conn.entries, conn.repeats = self.saved
                return False
        return Tx()

    async def execute(self, sql, *args):
        if sql is store._INSERT_LEDGER:
            if args[0] in self.ledgers:
                return 'INSERT 0 0'
            self.ledgers[args[0]] = dict(zip(('ledger_id', 'quote_asset', 'cost_model_id',
                                              'money_quantum', 'ledger_version'), args))
            return 'INSERT 0 1'
        if sql is store._INSERT_ENTRY:
            row = dict(zip(store._ENTRY_COLUMNS, args))
            chain = sorted((r for r in self.entries.values() if r['ledger_id'] == row['ledger_id']),
                           key=lambda r: r['sequence'])
            prev = chain[-1]['state_hash'] if chain else pl.GENESIS_HASH
            if row['sequence'] != len(chain) + 1 or row['prev_state_hash'] != prev:
                raise self.Refusal('portfolio_ledger_chain')
            self.entries[(row['ledger_id'], row['event_id'])] = row
            return 'INSERT 0 1'
        assert sql is store._INSERT_REPEAT
        self.repeats.append(args[3])
        return 'INSERT 0 1'

    async def fetchrow(self, sql, *args):
        if sql is store._SELECT_LEDGER:
            return self.ledgers.get(args[0])
        assert sql is store._SELECT_EVENT
        return self.entries.get(args)

    async def fetch(self, sql, ledger_id):
        assert sql is store._SELECT_ENTRIES
        return sorted((r for r in self.entries.values() if r['ledger_id'] == ledger_id),
                      key=lambda r: r['sequence'])


def test_append_logic_is_idempotent_and_conflicts_write_nothing():
    async def go():
        conn, ledger = FakeConn(), rich_ledger()
        first = ledger.entries[:5]
        assert await store.ensure_ledger(conn, ledger) == 'created'
        assert await store.append_entries(conn, first) == ['inserted'] * 5
        out = await store.sync_ledger(conn, ledger)
        assert out == ['duplicate'] * 5 + ['inserted'] * (len(ledger.entries) - 5)
        assert conn.repeats == ['duplicate_noop'] * 5
        assert_same_ledger(await store.load_ledger(conn, ledger.ledger_id), ledger)
        # the same event_id with another payload: F7.ledger_event_conflict, recorded, nothing written
        events = rich_events()
        events[1] = dataclasses.replace(events[1], amount=D('120.6'))
        forked = rich_ledger(events=events)
        before = copy.deepcopy(conn.entries)
        with pytest.raises(pl.LedgerEventConflict) as info:
            await store.append_entries(conn, [forked.entries[1]])
        assert info.value.f7_code == 'F7.ledger_event_conflict'
        assert conn.entries == before and conn.repeats[-1] == 'conflict'
        # a batch that ends in a conflict is rolled back as a whole
        tail = rich_ledger(events=rich_events() + [Mark('m-late', at(20), 'BTCUSDT', D('1'), 's')])
        with pytest.raises(pl.LedgerEventConflict):
            await store.append_entries(conn, [tail.entries[-1], forked.entries[1]])
        assert conn.entries == before and conn.repeats[-1] == 'conflict'
        # a header that differs is refused; a chain the database refuses is a store refusal
        other = pl.PortfolioLedger(ledger_id=ledger.ledger_id, quote_asset=USDT,
                                   cost_model_id='research_baseline_v1', money_quantum=D('0.01'))
        with pytest.raises(store.LedgerStoreError, match='ledger_header_conflict'):
            await store.ensure_ledger(conn, other)
        gap = FakeConn()
        await store.ensure_ledger(gap, ledger)
        with pytest.raises(store.LedgerStoreError, match='database_refused'):
            await store.append_entries(gap, [ledger.entries[0], ledger.entries[2]])
        assert gap.entries == {}
        with pytest.raises(store.LedgerStoreError, match='unknown_ledger'):
            await store.load_ledger(gap, 'nope')
    asyncio.run(go())


# ── database helpers ───────────────────────────────────────────────────────────────────────

def _dsn(admin, name):
    return admin.rsplit('/', 1)[0] + '/' + name


async def _recreate(admin_dsn, name, template=None):
    admin = await asyncpg.connect(admin_dsn)
    try:
        if template is not None and not await admin.fetchval(
                'SELECT 1 FROM pg_database WHERE datname = $1', template):
            pytest.skip(f'schema template {template!r} not built (.github/ci/build_schema_template.sh)')
        await admin.execute(f'DROP DATABASE IF EXISTS {name} WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE {name}' + (f' TEMPLATE {template}' if template else ''))
    finally:
        await admin.close()
    return await asyncpg.connect(_dsn(admin_dsn, name))


async def apply(conn, upto):
    """database/migrate.py:apply, restricted to versions <= upto. Returns '+name' / '=name'."""
    import hashlib
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


CATALOG = {
    'columns': "SELECT table_name, column_name, data_type, is_nullable, coalesce(column_default, '') "
               "FROM information_schema.columns WHERE table_schema = 'public'",
    'constraints': "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                   "WHERE connamespace = 'public'::regnamespace",
    'indexes': "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'",
    'triggers': "SELECT tgrelid::regclass::text, tgname, pg_get_triggerdef(oid) FROM pg_trigger "
                "WHERE NOT tgisinternal",
    'functions': "SELECT proname, pg_get_functiondef(oid) FROM pg_proc "
                 "WHERE pronamespace = 'public'::regnamespace AND prokind = 'f'",
    'sequences': "SELECT sequence_name, data_type FROM information_schema.sequences "
                 "WHERE sequence_schema = 'public'",
    'views': "SELECT viewname, definition FROM pg_views WHERE schemaname = 'public'",
}


async def catalog(conn):
    out = {}
    for kind, sql in CATALOG.items():
        out[kind] = sorted(tuple(r) for r in await conn.fetch(sql))
    return out


def split_catalog(cat):
    """(existing objects, objects of migration 012); every 012 object is named portfolio_ledger*."""
    mine = {k: [r for r in rows if r[0].startswith('portfolio_ledger')] for k, rows in cat.items()}
    rest = {k: [r for r in rows if not r[0].startswith('portfolio_ledger')] for k, rows in cat.items()}
    return rest, mine


async def data_fingerprint(conn, tables):
    return {t: await conn.fetchval(
        f"SELECT count(*)::text || ':' || coalesce(md5(string_agg(md5(t::text), ',' "
        f"ORDER BY md5(t::text))), '') FROM {t} t") for t in tables}


SEED = """
INSERT INTO signals (symbol,timeframe,market_condition,entry_price,target_1,target_2,target_3,stop_loss,
                     score,telegram_sent,features_snapshot,trade_type,decision_source,strategy_version)
SELECT 'H'||(g%10)||'USDT','4h','bullish',100,102,103.6,104.4,98,3,true,'{}'::jsonb,'momentum',
       'policy_ready','sb-2026.08'
FROM generate_series(1,60) g;
INSERT INTO active_trades (signal_id,symbol,entry_price,target_1,target_2,target_3,stop_loss,timeframe,status)
SELECT id,symbol,entry_price,target_1,target_2,target_3,stop_loss,timeframe,'closed' FROM signals WHERE id<=40;
INSERT INTO trade_results (signal_id,symbol,entry_price,exit_price,profit_percent,profit_usdt,result)
SELECT signal_id,symbol,entry_price,101,1,0.5,'WIN' FROM active_trades;
INSERT INTO outbox_events (event_type,aggregate_type,aggregate_id,payload)
SELECT 'signal.ready','signal',id,'{}'::jsonb FROM signals WHERE id<=50;
"""


# ── migration on fresh databases (P1R_TEST_DSN) ──────────────────────────────────────────────

@needs_fresh
def test_migration_012_is_additive_idempotent_and_rolls_back():
    async def go():
        conn = await _recreate(FRESH_DSN, 'wpe03_ledger_migr')
        try:
            for path in BASE:
                await conn.execute(path.read_text(encoding='utf-8'))
            assert all(x.startswith('+') for x in await apply(conn, 11))
            await conn.execute(SEED)
            cat11 = await catalog(conn)
            tables = [r['tablename'] for r in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> 'schema_migrations' ORDER BY 1")]       # the runner's own ledger
            data11 = await data_fingerprint(conn, tables)
            log12 = await apply(conn, 12)
            cat12 = await catalog(conn)
            data12 = await data_fingerprint(conn, tables)
            again = await apply(conn, 12)
            async with conn.transaction():                       # the body itself is re-runnable
                await conn.execute(MIGRATION.read_text(encoding='utf-8'))
            cat_rerun = await catalog(conn)
            versions = [r['version'] for r in await conn.fetch('SELECT version FROM schema_migrations ORDER BY 1')]
            await conn.execute(rollback_sql())
            cat_rb = await catalog(conn)
            versions_rb = [r['version'] for r in await conn.fetch('SELECT version FROM schema_migrations ORDER BY 1')]
            data_rb = await data_fingerprint(conn, tables)
            relog = await apply(conn, 12)                        # re-apply after the rollback
            cat_reapplied = await catalog(conn)
            return (cat11, cat12, data11, data12, log12, again, cat_rerun, versions, cat_rb,
                    versions_rb, data_rb, relog, cat_reapplied)
        finally:
            await conn.close()
    (cat11, cat12, data11, data12, log12, again, cat_rerun, versions, cat_rb, versions_rb, data_rb,
     relog, cat_reapplied) = asyncio.run(go())
    rest11, mine11 = split_catalog(cat11)
    rest12, mine12 = split_catalog(cat12)
    assert all(rows == [] for rows in mine11.values())           # nothing of 012 existed before
    assert rest12 == rest11                                      # no existing object changed
    assert data12 == data11 == data_rb                           # no existing row changed
    assert {r[0] for r in mine12['columns']} == NEW_TABLES
    assert {r[0] for r in mine12['functions']} == NEW_FUNCTIONS
    assert {r[1] for r in mine12['triggers']} == NEW_TRIGGERS
    assert NEW_INDEXES <= {r[1] for r in mine12['indexes']}
    assert log12 == ['=' + p.name for p in MIGRATIONS[:11]] + ['+012_portfolio_ledger.sql']
    assert all(x.startswith('=') for x in again) and versions == list(range(1, 13))
    assert cat_rerun == cat12                                    # idempotent body
    assert cat_rb == cat11 and versions_rb == list(range(1, 12))  # rollback restores schema 11
    assert relog[-1] == '+012_portfolio_ledger.sql' and cat_reapplied == cat12


# ── template databases (P1_DB_DSN + P1_SCHEMA_TEMPLATE) ─────────────────────────────────────

def template_test(name):
    def decorate(body):
        @needs_template
        def run():
            async def go():
                conn = await _recreate(TEMPLATE_DSN, name, TEMPLATE)
                try:
                    await body(conn)
                finally:
                    await conn.close()
            asyncio.run(go())
        run.__name__ = body.__name__
        run.__doc__ = body.__doc__
        return run
    return decorate


@template_test('wpe03_ledger_tpl_schema')
async def test_template_has_the_ledger_schema_and_reapplies_as_a_no_op(conn):
    cat = await catalog(conn)
    _, mine = split_catalog(cat)
    assert {r[0] for r in mine['columns']} == NEW_TABLES
    assert {r[1] for r in mine['triggers']} == NEW_TRIGGERS
    assert {r[0] for r in mine['functions']} == NEW_FUNCTIONS
    async with conn.transaction():
        await conn.execute(MIGRATION.read_text(encoding='utf-8'))
    assert await catalog(conn) == cat


@template_test('wpe03_ledger_tpl_roundtrip')
async def test_round_trip_through_the_store_replays_to_the_in_memory_hash(conn):
    ledger = rich_ledger()
    head = pl.PortfolioLedger(ledger_id=ledger.ledger_id, quote_asset=USDT,
                              cost_model_id=ledger.cost_model_id, money_quantum=Q)
    head.apply_all(rich_events()[:6])
    assert await store.ensure_ledger(conn, head) == 'created'
    assert await store.sync_ledger(conn, head) == ['inserted'] * 6
    out = await store.sync_ledger(conn, ledger)                  # resume from the stored prefix
    assert out == ['duplicate'] * 6 + ['inserted'] * (len(ledger.entries) - 6)
    loaded = await store.load_ledger(conn, ledger.ledger_id)
    assert_same_ledger(loaded, ledger)
    assert await conn.fetchval("SELECT count(*) FROM portfolio_ledger_repeats "
                               "WHERE outcome = 'duplicate_noop'") == 6
    kinds = await conn.fetch("SELECT DISTINCT jsonb_typeof(value) AS k FROM portfolio_ledger_entries, "
                             "jsonb_each(event_payload) WHERE value <> 'null'::jsonb")
    assert [r['k'] for r in kinds] == ['string']                 # exact decimals, never JSON numbers
    as_of = await conn.fetchval("SELECT as_of FROM portfolio_ledger_entries WHERE sequence = 3")
    assert as_of == at(2)
    # the same event_id with a different payload: refused, recorded, nothing written
    events = rich_events()
    events[2] = dataclasses.replace(events[2], fee=D('0.051'))
    count = await conn.fetchval('SELECT count(*) FROM portfolio_ledger_entries')
    with pytest.raises(pl.LedgerEventConflict):
        await store.sync_ledger(conn, rich_ledger(events=events))
    assert await conn.fetchval('SELECT count(*) FROM portfolio_ledger_entries') == count
    assert await conn.fetchval("SELECT count(*) FROM portfolio_ledger_repeats "
                               "WHERE outcome = 'conflict' AND event_id = 'e-a1'") == 1
    # a second ledger under another cost model lives beside the first
    stress = rich_ledger(ledger_id='wpe03:L2', model='research_stress_v1')
    await store.sync_ledger(conn, stress)
    assert_same_ledger(await store.load_ledger(conn, 'wpe03:L2'), stress)
    assert (await store.load_ledger(conn, ledger.ledger_id)).state_hash == ledger.state_hash


@template_test('wpe03_ledger_tpl_append_only')
async def test_update_delete_and_truncate_are_refused_on_every_ledger_table(conn):
    ledger = rich_ledger()
    await store.sync_ledger(conn, ledger)
    await store.append_entries(conn, ledger.entries[:1])          # one repeat row
    tables = {'portfolio_ledgers': 'quote_asset', 'portfolio_ledger_entries': 'symbol',
              'portfolio_ledger_repeats': 'outcome'}
    counts = {t: await conn.fetchval(f'SELECT count(*) FROM {t}') for t in tables}
    assert all(counts.values())
    for table, column in tables.items():
        for sql in (f'UPDATE {table} SET {column} = {column}', f'DELETE FROM {table}',
                    f'TRUNCATE {table} CASCADE'):
            with pytest.raises(asyncpg.RestrictViolationError, match='portfolio_ledger_append_only'):
                await conn.execute(sql)
    assert {t: await conn.fetchval(f'SELECT count(*) FROM {t}') for t in tables} == counts
    assert (await store.load_ledger(conn, ledger.ledger_id)).state_hash == ledger.state_hash


@template_test('wpe03_ledger_tpl_chain')
async def test_database_refuses_entries_that_break_the_chain(conn):
    ledger = rich_ledger()
    await store.ensure_ledger(conn, ledger)
    rows = [store.entry_row(e) for e in ledger.entries]

    async def insert(row):
        await conn.execute(store._INSERT_ENTRY, *(row[c] for c in store._ENTRY_COLUMNS))

    refusals = [
        ({**rows[0], 'event_type': 'Mark'}, asyncpg.CheckViolationError, 'must be a Deposit'),
        ({**rows[0], 'prev_state_hash': 'a' * 64}, asyncpg.CheckViolationError, 'genesis hash'),
    ]
    for row, error, message in refusals:
        with pytest.raises(error, match=message):
            await insert(row)
    await insert(rows[0])
    later = [
        (rows[2], asyncpg.CheckViolationError, 'sequence gap'),
        ({**rows[1], 'prev_state_hash': 'b' * 64}, asyncpg.CheckViolationError, 'hash chain broken'),
        ({**rows[1], 'as_of': at(0) - timedelta(minutes=1)}, asyncpg.CheckViolationError, 'time regression'),
        ({**rows[1], 'entry_id': 'wpe03:L1:9'}, asyncpg.CheckViolationError, ''),
        ({**rows[1], 'event_type': 'Correction'}, asyncpg.CheckViolationError, ''),
        ({**rows[1], 'cost_model_id': 'research_stress_v1'}, asyncpg.ForeignKeyViolationError, ''),
        ({**rows[1], 'state_hash': rows[1]['prev_state_hash']}, asyncpg.CheckViolationError, ''),
        ({**rows[1], 'event_fingerprint': 'not-a-hash'}, asyncpg.CheckViolationError, ''),
        ({**rows[1], 'event_id': rows[0]['event_id'],
          'event_payload': rows[1]['event_payload'].replace('"r-a"', '"d0"')},
         asyncpg.UniqueViolationError, ''),                     # PR-I7: one event_id per ledger
    ]
    for row, error, message in later:
        with pytest.raises(error, match=message):
            await insert(row)
    with pytest.raises(store.LedgerStoreError, match='database_refused'):
        await store.append_entries(conn, [ledger.entries[2]])   # the store surfaces the refusal
    await store.append_entries(conn, ledger.entries[1:])
    assert (await store.load_ledger(conn, ledger.ledger_id)).state_hash == ledger.state_hash
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute("INSERT INTO portfolio_ledgers (ledger_id, quote_asset, cost_model_id, "
                           "money_quantum, ledger_version) VALUES ('x', 'USDT', 'unknown_v1', '1E-8', 'v')")


@template_test('wpe03_ledger_tpl_tamper')
async def test_a_row_changed_behind_the_triggers_is_refused_on_load(conn):
    ledger = rich_ledger()
    await store.sync_ledger(conn, ledger)
    try:
        await conn.execute('ALTER TABLE portfolio_ledger_entries '
                           'DISABLE TRIGGER trg_portfolio_ledger_entries_no_mutation')
    except asyncpg.InsufficientPrivilegeError:
        pytest.skip('the test role cannot disable triggers (not the table owner)')
    await conn.execute("UPDATE portfolio_ledger_entries SET event_payload = "
                       "jsonb_set(event_payload, '{amount}', '\"1001\"') WHERE sequence = 1")
    await conn.execute('ALTER TABLE portfolio_ledger_entries '
                       'ENABLE TRIGGER trg_portfolio_ledger_entries_no_mutation')
    with pytest.raises(pl.LedgerInvariantViolation):
        await store.load_ledger(conn, ledger.ledger_id)
