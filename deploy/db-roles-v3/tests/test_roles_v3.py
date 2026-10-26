"""R-5 least-privilege conformance suite for roles_v3.sql (schema 11). DISPOSABLE TEST CLUSTER ONLY.

Every login role is exercised with its own credentials over the (internal) network; NOLOGIN roles (learner,
dashboard, research) are exercised through `SET ROLE` from the test admin, which applies exactly that role's
privileges. Statement checks use the SQL the containers actually run (/deployed/<container>, extracted from the
release images): static literals AND f-string SQL rendered with the real constants. Synthetic data only.
"""
import ast
import datetime
import glob
import importlib.util
import json
import os
import re
import sys

import asyncpg
import pytest

sys.path.insert(0, '/t')
import sql_inventory                                   # noqa: E402
sys.path.insert(0, '/deployed/trading_tracker')       # outbox, B3, risk_epoch, health exactly as deployed (ea8ae4f)
import shared.health as health                         # noqa: E402
import shared.outbox as outbox                         # noqa: E402
import shared.risk_epoch as risk_epoch                 # noqa: E402
import shared.trading_state as trading_state           # noqa: E402
from shared.trading_state import RISK_STATE_MISSING    # noqa: E402

pytestmark = pytest.mark.asyncio
HOST, DB, ADMIN = os.environ['TSB_PGHOST'], 'trading_signals', 'trading_signal_bot'
HBA = os.environ.get('R5_HBA_ACTIVE') == '1'
OUT = os.environ.get('R5_OUT')
FREEZE = datetime.datetime(2026, 8, 19, 9, 33, 46)
RUNTIME = {'tsb_scanner': ('trading_scanner', ['main.py']), 'tsb_analyzer': ('trading_analyzer', ['main.py']),
           'tsb_signal_engine': ('trading_signal_engine', ['main.py']), 'tsb_telegram': ('trading_telegram', ['main.py']),
           'tsb_tracker': ('trading_tracker', ['main.py'])}
CODE = {**RUNTIME, 'tsb_learner': ('trading_signal_engine', ['research/continuous_learner.py',
                                                             'research/rollback_learned_gates.py'])}
LOGIN = set(RUNTIME) | {'tsb_backup', 'tsb_migrator'}
NOLOGIN = {'tsb_learner', 'tsb_dashboard_ro', 'tsb_research_ro', 'tsb_owner', 'tsb_login_group', 'tsb_net_group'}
ALL_TSB = LOGIN | NOLOGIN
PW = {k[7:].lower(): v for k, v in os.environ.items() if k.startswith('TSB_PW_')}
ROLE_DB = {'tsb_migrator': 'owner_stage'}   # the migrator has CONNECT only where it owns objects (ownership stage)
NETWORK = set(RUNTIME) | {'tsb_learner', 'tsb_dashboard_ro'}   # tsb_net_group
POOL_MAX, HEALTHCHECK_POOL, SERVICE_LIMIT = 10, 2, 20
DENIED = (asyncpg.exceptions.InsufficientPrivilegeError,)
NON_EXECUTABLE = (asyncpg.exceptions.PostgresSyntaxError, asyncpg.exceptions.UndefinedColumnError,
                  asyncpg.exceptions.UndefinedTableError, asyncpg.exceptions.IndeterminateDatatypeError,
                  asyncpg.exceptions.DataError, asyncpg.exceptions.AmbiguousParameterError,
                  asyncpg.exceptions.FeatureNotSupportedError, asyncpg.exceptions.UndefinedFunctionError,
                  asyncpg.exceptions.DatatypeMismatchError)
# Statements present in a module a service imports but whose function that service never calls. Each entry is
# re-justified at run time: the function must be absent from that service's call graph (see test_exceptions_justified).
BY_DESIGN = {('tsb_tracker', 'shared/risk_epoch.py', 'INSERT INTO risk_recovery_events'): 'record_recovery'}


async def connect(role, db=None):
    if HBA and role in LOGIN and role not in NETWORK:
        pytest.skip(f'{role} network login is rejected by pg_hba by design (covered by test_hba_v3)')
    return await asyncpg.connect(host=HOST, user=role, password=PW[role], database=db or ROLE_DB.get(role, DB))


async def session(role):
    """A connection that acts with exactly `role`'s privileges."""
    if role in LOGIN:
        return await connect(role)
    c = await connect(ADMIN)
    await c.execute(f'SET ROLE {role}')
    return c


def out(name, lines):
    if OUT:
        with open(os.path.join(OUT, name), 'w') as fh:
            fh.writelines(f'{l}\n' for l in lines)


# ------------------------------------------------------------------ statement inventory ------------------------
def _module_strings(root, files):
    """Module-level string constants of every file in the import graph (for rendering f-string SQL). Plain strings
    first; module-level f-strings are then rendered from already-known constants until nothing new resolves."""
    ns, pending = {}, []
    for f in files:
        try:
            tree = ast.parse(open(os.path.join(root, f), encoding='utf-8').read())
        except (OSError, SyntaxError):
            continue
        for n in tree.body:
            if isinstance(n, ast.Assign):
                names = [t.id for t in n.targets if isinstance(t, ast.Name)]
                if isinstance(n.value, ast.Constant) and isinstance(n.value.value, (str, int, float)) \
                        and not isinstance(n.value.value, bool):
                    ns.update({k: str(n.value.value) for k in names})
                elif isinstance(n.value, ast.JoinedStr):
                    pending.append((names, n.value))
    changed = True
    while changed and pending:
        changed = False
        for item in list(pending):
            names, js = item
            parts = []
            for v in js.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                elif isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name) and v.value.id in ns:
                    parts.append(ns[v.value.id])
                else:
                    break
            else:
                ns.update({k: ''.join(parts) for k in names}); pending.remove(item); changed = True
    return ns


def _economic_label_sql(root):
    src = open(os.path.join(root, 'shared/fees.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'economic_result_sql'), None)
    if fn is None:
        return None                                       # older image (scanner 63b38e7a): no economic labels
    ns = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'fees', 'exec'), ns)   # the deployed function, verbatim
    return ns['economic_result_sql']('$1::numeric')


_CACHE = {}
# Local variables interpolated into f-string SQL, bound to the deployed function that produces them at run time.
LOCAL_BINDINGS = {'candle_case': ('shared/candle.py', 'candle_interval_case_sql', ('s.timeframe',))}


def statements(role):
    """[(file, line, kind, sql)] for the role's code: static literals plus every rendering of each f-string."""
    if role in _CACHE:
        return _CACHE[role]
    container, mains = CODE[role]
    root = f'/deployed/{container}'
    inv = sql_inventory.collect(root, mains)
    files = sorted({s['file'] for s in inv['static'] + inv['dynamic']} |
                   {os.path.relpath(p, root) for p in glob.glob(f'{root}/**/*.py', recursive=True)})
    ns = _module_strings(root, files)
    if 'READY_SQL_PREDICATE' not in ns:                  # parenthesised implicit concatenation is still one Constant
        ns.update(_module_strings(root, ['shared/signal_readiness.py']))
    label = _economic_label_sql(root)
    if label is not None:
        ns['label'] = label
    for name, (rel, fn, args) in LOCAL_BINDINGS.items():      # f-string locals produced by deployed helper functions
        path = os.path.join(root, rel)
        if os.path.exists(path):
            spec = importlib.util.spec_from_file_location(f'r5_{container}_{fn}', path)
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            ns[name] = getattr(mod, fn)(*args)
    choices = {'column': ['wins', 'losses']}               # tracker main.py: column = 'wins' if WIN else 'losses'
    res = [(s['file'], s['line'], 'static', s['sql']) for s in inv['static']]
    for d in inv['dynamic']:
        names = re.findall(r'\{([^{}]+)\}', d['sql'])
        variants = [{}]
        for name in dict.fromkeys(names):
            if name in choices:
                variants = [dict(v, **{name: c}) for v in variants for c in choices[name]]
            elif name in ns:
                variants = [dict(v, **{name: ns[name]}) for v in variants]
            else:
                raise AssertionError(f'unrenderable f-string SQL {d["file"]}:{d["line"]} placeholder {name!r}')
        for v in variants:
            res.append((d['file'], d['line'], 'dynamic', re.sub(r'\{([^{}]+)\}', lambda m: v[m.group(1)], d['sql'])))
    _CACHE[role] = (res, set(inv['calls']))
    return _CACHE[role]


def by_design(role, path, sql):
    return any(role == r and path.endswith(f) and pat in ' '.join(sql.split()) for (r, f, pat) in BY_DESIGN)


async def check_statements(c, role):
    """EXPLAIN (GENERIC_PLAN) each statement in a READ ONLY transaction: privileges are checked, nothing runs."""
    stmts, _ = statements(role)
    denied, ok, skipped = [], 0, []
    outer = c.transaction(readonly=True)
    await outer.start()
    try:
        for path, line, kind, sql in stmts:
            try:
                async with c.transaction():
                    await c.execute(f'EXPLAIN (GENERIC_PLAN) {sql}')
                ok += 1
            except DENIED as e:
                denied.append((path, line, kind, ' '.join(sql.split())[:110], str(e)[:70]))
            except NON_EXECUTABLE as e:
                skipped.append((path, line, kind, type(e).__name__, ' '.join(sql.split())[:160]))
    finally:
        await outer.rollback()
    return ok, denied, skipped


# ------------------------------------------------------------------ role attributes -------------------------------
async def test_role_attributes_and_memberships():
    c = await connect(ADMIN)
    try:
        rows = {r['rolname']: r for r in await c.fetch(
            "SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolreplication, rolcanlogin, "
            "rolconnlimit, rolinherit, rolconfig FROM pg_roles WHERE rolname LIKE 'tsb\\_%'")}
        mem = await c.fetch("SELECT pg_get_userbyid(roleid) g, pg_get_userbyid(member) m, admin_option, inherit_option, "
                            "set_option FROM pg_auth_members WHERE pg_get_userbyid(member) LIKE 'tsb\\_%'")
    finally:
        await c.close()
    assert set(rows) == ALL_TSB, set(rows) ^ ALL_TSB
    for r in rows.values():
        assert not any([r['rolsuper'], r['rolcreaterole'], r['rolcreatedb'], r['rolbypassrls'], r['rolreplication']]), r['rolname']
    assert {n for n, r in rows.items() if r['rolcanlogin']} == LOGIN
    for n in RUNTIME:
        assert rows[n]['rolconnlimit'] == SERVICE_LIMIT and not rows[n]['rolinherit'], n
    assert rows['tsb_backup']['rolconnlimit'] == 2 and rows['tsb_migrator']['rolconnlimit'] == 2
    for n in ('tsb_research_ro', 'tsb_dashboard_ro', 'tsb_backup'):
        assert 'default_transaction_read_only=on' in (rows[n]['rolconfig'] or []), n
    groups = {}
    for m in mem:
        groups.setdefault(m['g'], {})[m['m']] = (m['admin_option'], m['inherit_option'], m['set_option'])
    assert set(groups['tsb_login_group']) == (ALL_TSB - {'tsb_owner', 'tsb_login_group', 'tsb_net_group'})
    assert set(groups['tsb_net_group']) == set(RUNTIME) | {'tsb_learner', 'tsb_dashboard_ro'}
    for g in ('tsb_login_group', 'tsb_net_group'):
        assert all(v == (False, False, False) for v in groups[g].values()), g
    assert groups['tsb_owner'] == {'tsb_migrator': (False, False, True)}         # SET only, for DDL
    assert set(groups) == {'tsb_login_group', 'tsb_net_group', 'tsb_owner'}       # no other role memberships at all


# ------------------------------------------------------------------ statement-level privileges -------------------
@pytest.mark.parametrize('role', sorted(CODE))
async def test_every_statement_is_permitted(role):
    c = await session(role)
    try:
        ok, denied, skipped = await check_statements(c, role)
    finally:
        await c.close()
    stmts, _ = statements(role)
    unexpected = [d for d in denied if not by_design(role, d[0], d[3])]
    print(f'\n[{role}] statements={len(stmts)} permitted={ok} non_executable={len(skipped)} '
          f'denied_by_design={len(denied) - len(unexpected)} denied_unexpected={len(unexpected)}')
    out(f'statements_{role}.txt', [f'DENIED\t{d}' for d in denied] + [f'NONEXEC\t{s}' for s in skipped])
    assert not unexpected, unexpected
    assert ok > 0


@pytest.mark.parametrize('role', sorted(CODE))
async def test_non_executable_fragments_are_not_statements(role):
    """Anything EXPLAIN could not plan must be a fragment of a larger statement, never a whole query we skip."""
    c = await session(role)
    try:
        _, _, skipped = await check_statements(c, role)
    finally:
        await c.close()
    bad = [s for s in skipped if s[3] not in ('PostgresSyntaxError', 'UndefinedColumnError')]
    assert not bad, bad


async def test_exceptions_justified():
    for (role, path, pat), fn in BY_DESIGN.items():
        stmts, calls = statements(role)
        assert any(p.endswith(path) and pat in ' '.join(s.split()) for p, _, _, s in stmts), (role, pat)
        assert fn not in calls, f'{role} code calls {fn}(); the exception for {pat!r} is no longer valid'


TABLE_PRIVS = ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER')


async def held_privileges(c, role):
    return [(t, p) for (t,) in await c.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")
            for p in TABLE_PRIVS if await c.fetchval('SELECT has_table_privilege($1, $2, $3)', role, f'public.{t}', p)]


@pytest.mark.parametrize('role', sorted(CODE))
async def test_every_granted_privilege_is_needed(role):
    """Minimality: revoking any single table privilege makes at least one of the role's statements fail."""
    admin = await connect(ADMIN)
    c = await session(role)
    unneeded = []
    try:
        privs = await held_privileges(admin, role)
        assert privs
        for t, p in privs:
            await admin.execute(f'REVOKE {p} ON public.{t} FROM {role}')
            try:
                _, denied, _ = await check_statements(c, role)
                if not [d for d in denied if not by_design(role, d[0], d[3])]:
                    unneeded.append(f'{p} ON {t}')
            finally:
                await admin.execute(f'GRANT {p} ON public.{t} TO {role}')
    finally:
        await c.close(); await admin.close()
    print(f'\n[{role}] privileges={len(privs)} unneeded={unneeded}')
    out(f'privileges_{role}.txt', [f'{p} ON {t}' for t, p in privs])
    assert not unneeded, unneeded


async def test_write_authority_matrix():
    """Single-writer invariants for trading and accounting state (from roles_v3.sql; any drift fails)."""
    expect = {
        ('signals', 'INSERT'): {'tsb_signal_engine'},
        ('signals', 'UPDATE'): {'tsb_telegram', 'tsb_tracker'},
        ('active_trades', 'INSERT'): {'tsb_tracker'}, ('active_trades', 'UPDATE'): {'tsb_tracker'},
        ('paper_entry_orders', 'INSERT'): {'tsb_tracker'}, ('paper_entry_orders', 'UPDATE'): {'tsb_tracker'},
        ('trade_results', 'INSERT'): {'tsb_tracker'}, ('trade_results', 'UPDATE'): set(),
        ('trade_target_fills', 'INSERT'): {'tsb_tracker'}, ('trade_target_fills', 'UPDATE'): set(),
        ('risk_recovery_events', 'INSERT'): {'tsb_telegram'},
        ('learned_gates', 'INSERT'): {'tsb_learner'}, ('learned_gate_history', 'INSERT'): {'tsb_learner'},
    }
    c = await connect(ADMIN)
    try:
        for (t, p), roles in expect.items():
            holders = {r for r in ALL_TSB if await c.fetchval('SELECT has_table_privilege($1, $2, $3)', r, f'public.{t}', p)}
            assert holders == roles, (t, p, holders)
        for t in ('trade_results', 'trade_target_fills', 'signals', 'active_trades', 'outbox_events', 'paper_entry_orders',
                  'risk_recovery_events', 'schema_migrations'):
            for p in ('DELETE', 'TRUNCATE'):
                holders = {r for r in ALL_TSB if await c.fetchval('SELECT has_table_privilege($1, $2, $3)', r, f'public.{t}', p)}
                assert not holders, (t, p, holders)
    finally:
        await c.close()


# ------------------------------------------------------------------ sequences -----------------------------------
INSERT_RE = re.compile(r'\bINSERT\s+INTO\s+([A-Za-z_]+)', re.I)
SEQ_OWNERS_SQL = """SELECT c.relname AS tbl, format('%I.%I', sn.nspname, s.relname) AS seq
  FROM pg_depend d JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'
  JOIN pg_namespace sn ON sn.oid = s.relnamespace JOIN pg_class c ON c.oid = d.refobjid
  WHERE d.deptype IN ('a','i') AND sn.nspname = 'public'"""


def tables_inserted(role):
    stmts, _ = statements(role)
    return {t.lower() for p, _, _, s in stmts if not by_design(role, p, s) for t in INSERT_RE.findall(s)}


@pytest.mark.parametrize('role', sorted(ALL_TSB - {'tsb_login_group', 'tsb_net_group'}))
async def test_sequence_usage_matches_code(role):
    c = await connect(ADMIN)
    try:
        owners = await c.fetch(SEQ_OWNERS_SQL)
        assert len(owners) == 18
        need = tables_inserted(role) if role in CODE else set()
        expected = {r['seq'] for r in owners if r['tbl'] in need}
        usage = {r['seq'] for r in owners if await c.fetchval("SELECT has_sequence_privilege($1, $2, 'USAGE')", role, r['seq'])}
        update = {r['seq'] for r in owners if await c.fetchval("SELECT has_sequence_privilege($1, $2, 'UPDATE')", role, r['seq'])}
        select = {r['seq'] for r in owners if await c.fetchval("SELECT has_sequence_privilege($1, $2, 'SELECT')", role, r['seq'])}
    finally:
        await c.close()
    assert usage == expected, (sorted(usage), sorted(expected))
    assert not update                                        # nobody can setval()
    assert select == ({r['seq'] for r in owners} if role == 'tsb_backup' else set())


@pytest.mark.parametrize('role', sorted(CODE))
async def test_nextval_exactly_where_granted(role):
    c = await session(role)
    tr = c.transaction(); await tr.start()
    try:
        need = tables_inserted(role)
        for r in await c.fetch(SEQ_OWNERS_SQL):
            if r['tbl'] in need:
                assert await c.fetchval('SELECT nextval($1::text::regclass)', r['seq']) > 0
            else:
                with pytest.raises(DENIED):
                    async with c.transaction():
                        await c.fetchval('SELECT nextval($1::text::regclass)', r['seq'])
    finally:
        await tr.rollback(); await c.close()


# ------------------------------------------------------------------ functional paths under each role ------------
class Facade:
    """Stands in for shared.database.Database, bound to one role's connection."""
    def __init__(self, conn): self.conn = conn
    async def execute(self, q, *a): return await self.conn.execute(q, *a)
    async def fetch(self, q, *a): return await self.conn.fetch(q, *a)
    async def fetchrow(self, q, *a): return await self.conn.fetchrow(q, *a)
    async def fetchval(self, q, *a): return await self.conn.fetchval(q, *a)
    def acquire(self):
        conn = self.conn
        class _Ctx:
            async def __aenter__(self): return conn
            async def __aexit__(self, *exc): return False
        return _Ctx()


def bind(monkeypatch, conn):
    for mod in (trading_state, risk_epoch, outbox, health):
        monkeypatch.setattr(mod, 'Database', Facade(conn))


async def set_decisions(rows):
    c = await connect(ADMIN)
    try:
        async with c.transaction():
            await c.execute('DELETE FROM risk_management')
            for day, paused, reason in rows:
                await c.execute('INSERT INTO risk_management (date, is_trading_paused, pause_reason) VALUES ($1, $2, $3)',
                                datetime.date.fromisoformat(day), paused, reason)
    finally:
        await c.close()


@pytest.mark.parametrize('role', ['tsb_scanner', 'tsb_telegram', 'tsb_tracker'])
async def test_b3_gate_under_role(role, monkeypatch):
    c = await connect(role)
    bind(monkeypatch, c)
    try:
        await set_decisions([])
        assert await trading_state.get_pause_state() == (True, RISK_STATE_MISSING)
        await set_decisions([('2026-09-11', True, 'risk:loss_streak_halt')])
        assert await trading_state.get_pause_state() == (True, 'risk:loss_streak_halt')
        await set_decisions([('2026-09-11', True, 'risk:loss_streak_halt'), ('2026-09-12', False, 'manual_resume')])
        assert await trading_state.get_pause_state() == (False, None)
    finally:
        await set_decisions([('2026-09-11', True, 'risk:loss_streak_halt')])
        await c.close()


async def test_b3_role_without_grant_fails_closed_and_visibly(monkeypatch):
    c = await connect('tsb_analyzer')                      # has no grant on risk_management
    bind(monkeypatch, c)
    try:
        with pytest.raises(DENIED):
            await trading_state.get_pause_state()
    finally:
        await c.close()


@pytest.mark.parametrize('role', ['tsb_signal_engine', 'tsb_telegram', 'tsb_tracker'])
async def test_outbox_enqueue_claim_ack_defer_retry_deadletter(role, monkeypatch):
    c = await connect(role)
    bind(monkeypatch, c)
    tr = c.transaction(); await tr.start()
    try:
        owner = f'{role}-w'
        eid = await outbox.enqueue(c, 'r5.test', 'r5', 1, {'k': role})
        assert eid and await outbox.enqueue(c, 'r5.test', 'r5', 1, {}) is None       # idempotent producer
        rows = await outbox.claim('r5.test', owner, limit=5)
        assert [r['id'] for r in rows] == [eid] and rows[0]['attempts'] == 1
        await outbox.defer(eid, owner, 0, 'r5 deferral')                               # not an attempt
        await c.execute("UPDATE outbox_events SET available_at = NOW() - interval '1 second' WHERE id = $1", eid)
        assert (await outbox.claim('r5.test', owner))[0]['attempts'] == 1
        await c.execute('UPDATE outbox_events SET max_attempts = 2 WHERE id = $1', eid)
        await outbox.fail(eid, owner, RuntimeError('r5 retry'), retry_delay_seconds=0)   # attempt 1 of 2: retry
        st = await c.fetchrow('SELECT status, deferrals FROM outbox_events WHERE id = $1', eid)
        assert st['status'] == 'pending' and st['deferrals'] == 1
        await c.execute("UPDATE outbox_events SET available_at = NOW() - interval '1 second' WHERE id = $1", eid)
        assert (await outbox.claim('r5.test', owner))[0]['attempts'] == 2
        await outbox.fail(eid, owner, RuntimeError('r5 exhausted'))                      # attempt 2 of 2: dead letter
        st = await c.fetchrow('SELECT status, outcome FROM outbox_events WHERE id = $1', eid)
        assert (st['status'], st['outcome']) == ('dead', 'retry_exhausted')
        dl = await outbox.dead_letters_since(['r5.test'], (datetime.datetime(2000, 1, 1), 0))
        assert [r['id'] for r in dl] == [eid]
        eid2 = await outbox.enqueue(c, 'r5.test', 'r5', 2, {})
        await outbox.claim('r5.test', owner)
        await outbox.ack(eid2, owner, 'r5:ok')
        assert await c.fetchval('SELECT status FROM outbox_events WHERE id = $1', eid2) == 'completed'
    finally:
        await tr.rollback(); await c.close()


@pytest.mark.parametrize('role', sorted(CODE))
async def test_heartbeat_upsert(role, monkeypatch):
    c = await session(role)
    bind(monkeypatch, c)
    tr = c.transaction(); await tr.start()
    try:
        await health.mark_started(role, {'r5': True})
        await health.mark_success(role, {'r5': True})
        await health.mark_failure(role, RuntimeError('r5'))
        assert await c.fetchval('SELECT count(*) FROM service_heartbeats WHERE service_name=$1', role) == 1
    finally:
        await tr.rollback(); await c.close()


async def test_tracker_admission_lock_and_streak(monkeypatch):
    c = await connect('tsb_tracker')
    bind(monkeypatch, c)
    tr = c.transaction(); await tr.start()
    try:
        await risk_epoch.acquire_risk_admission_lock(c)
        assert await risk_epoch.effective_consecutive_losses(c) >= 0
        assert (await risk_epoch.loss_streak_state()) is not None
    finally:
        await tr.rollback(); await c.close()


async def test_telegram_pause_resume_and_recovery(monkeypatch):
    c = await connect('tsb_telegram')
    bind(monkeypatch, c)
    tr = c.transaction(); await tr.start()
    try:
        await c.execute("INSERT INTO risk_management (date, is_trading_paused, pause_reason) VALUES (CURRENT_DATE, true, "
                        "'manual_pause') ON CONFLICT (date) DO UPDATE SET is_trading_paused=true, pause_reason='manual_pause'")
        assert await trading_state.get_pause_state() == (True, 'manual_pause')
        await c.execute("INSERT INTO risk_management (date, is_trading_paused, pause_reason) VALUES (CURRENT_DATE, false, "
                        "'manual_resume') ON CONFLICT (date) DO UPDATE SET is_trading_paused=false, pause_reason='manual_resume'")
        assert await trading_state.get_pause_state() == (False, None)
        ev = await risk_epoch.record_recovery(acknowledged_by='r5-test', reason='role conformance test')
        assert ev['consecutive_losses_before'] >= 7
    finally:
        await tr.rollback(); await c.close()


async def test_telegram_symbol_list_upserts():
    c = await connect('tsb_telegram')
    tr = c.transaction(); await tr.start()
    try:
        for _ in range(2):
            await c.execute("INSERT INTO symbol_whitelist (symbol, approved_by, notes) VALUES ($1, 'user_telegram', $2) "
                            "ON CONFLICT (symbol) DO UPDATE SET approved_at = NOW(), notes = $2", 'R5TESTUSDT', 'r5')
            await c.execute("INSERT INTO symbol_blacklist (symbol, reason) VALUES ($1, $2) ON CONFLICT (symbol) DO UPDATE "
                            "SET rejected_at = NOW(), reason = $2", 'R5TESTUSDT', 'r5')
        await c.execute('DELETE FROM symbol_whitelist WHERE symbol = $1', 'R5TESTUSDT')
        await c.execute('DELETE FROM symbol_blacklist WHERE symbol = $1', 'R5TESTUSDT')
    finally:
        await tr.rollback(); await c.close()


def _literal(path, name):
    tree = ast.parse(open(path, encoding='utf-8').read())
    return next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))


async def test_signal_engine_idempotent_signal_transaction(monkeypatch):
    """The signal_engine's real insert-once SQL (setup_key, migration 011) + risk counter + outbox, as its role."""
    root = '/deployed/trading_signal_engine'
    insert_once = _literal(f'{root}/signal_logic.py', '_INSERT_ONCE_SQL')
    existing = _literal(f'{root}/signal_logic.py', '_EXISTING_SETUP_SQL')
    c = await connect('tsb_signal_engine')
    bind(monkeypatch, c)
    tr = c.transaction(); await tr.start()
    try:
        args = ('R5SIGUSDT', '15m', 'neutral', 1.0, 1.01, 1.02, 1.03, 0.99, 4, json.dumps({}), True, 1e6,
                json.dumps({'setup_identity': {'bracket_hash': 'h1'}}), 'reversion', json.dumps({}), 'policy_ready',
                'r5', 'R5|15m|1|reversion|r5')
        sid = await c.fetchval(insert_once, *args)
        assert sid
        await c.execute("INSERT INTO risk_management (date, signals_sent) VALUES (CURRENT_DATE, 1) ON CONFLICT (date) "
                        "DO UPDATE SET signals_sent = risk_management.signals_sent + 1")
        assert await outbox.enqueue(c, 'signal.ready', 'signal', sid, {'signal_id': sid})
        assert await c.fetchval(insert_once, *args) is None                   # same setup: not re-emitted
        row = await c.fetchrow(existing, args[-1])
        assert row['id'] == sid and row['bracket_hash'] == 'h1'
    finally:
        await tr.rollback(); await c.close()


# ------------------------------------------------------------------ denials --------------------------------------
FORBIDDEN_WRITES = {
    'tsb_scanner': ["INSERT INTO trade_results (symbol, entry_price) VALUES ('X', 1)"],
    'tsb_analyzer': ['UPDATE risk_management SET pause_reason = pause_reason'],
    'tsb_signal_engine': ['DELETE FROM trade_results', 'UPDATE active_trades SET status = status'],
    'tsb_telegram': ["INSERT INTO active_trades (symbol, entry_price, target_1, target_2, target_3, stop_loss) "
                     "VALUES ('X', 1, 1, 1, 1, 1)", 'UPDATE paper_entry_orders SET status = status'],
    'tsb_tracker': ['INSERT INTO risk_recovery_events DEFAULT VALUES', 'UPDATE trade_results SET profit_usdt = 0',
                    'DELETE FROM trade_target_fills', 'UPDATE trade_target_fills SET fill_price = fill_price'],
    'tsb_backup': ["INSERT INTO symbol_blacklist (symbol) VALUES ('X')", 'UPDATE signals SET id = id'],
    'tsb_migrator': ['SELECT count(*) FROM signals', 'UPDATE signals SET id = id'],
    'tsb_learner': ['UPDATE trade_results SET result = result', "INSERT INTO signals (symbol) VALUES ('X')"],
}
SUPERUSER_ONLY = [
    "COPY (SELECT 1) TO PROGRAM 'true'", "SELECT pg_read_file('PG_VERSION')", "ALTER SYSTEM SET work_mem = '8MB'",
    'CREATE ROLE r5_should_fail', 'CREATE DATABASE r5_should_fail', 'CREATE TABLE r5_should_fail (x int)',
    'CREATE TEMP TABLE r5_should_fail (x int)', 'TRUNCATE trade_results', 'DROP TABLE signals',
    'ALTER TABLE signals ADD COLUMN r5 int', 'CREATE SCHEMA r5_should_fail', 'SET ROLE trading_signal_bot',
    'SET ROLE tsb_login_group', 'SET ROLE tsb_net_group', 'SET ROLE tsb_backup', 'SET ROLE tsb_owner',
    'SELECT rolpassword FROM pg_authid LIMIT 1',
]
SELF_SET = {'tsb_backup': 'SET ROLE tsb_backup', 'tsb_migrator': 'SET ROLE tsb_owner'}   # own role / its one SET


@pytest.mark.parametrize('role', sorted(FORBIDDEN_WRITES))
async def test_least_privilege_denials(role):
    c = await session(role)
    try:
        await c.execute('SET default_transaction_read_only = off')            # privileges must be the barrier
        for stmt in FORBIDDEN_WRITES[role]:
            with pytest.raises(DENIED):
                await c.execute(stmt)
        if role in LOGIN:                                                     # SET ROLE sessions can always RESET to admin
            for stmt in SUPERUSER_ONLY:
                if SELF_SET.get(role) == stmt:
                    continue                                                  # permitted by definition (tested below)
                with pytest.raises(DENIED):
                    await c.execute(stmt)
    finally:
        await c.close()


@pytest.mark.parametrize('role', sorted(LOGIN))
async def test_cannot_grant_privileges_onward(role):
    """Without GRANT OPTION, GRANT is refused or a no-op with a warning; either way nothing is granted."""
    c = await connect(role)
    try:
        for stmt in ('GRANT SELECT ON signals TO tsb_research_ro', 'GRANT SELECT ON trade_results TO tsb_dashboard_ro',
                     'GRANT tsb_net_group TO tsb_research_ro'):
            try:
                await c.execute(stmt)
            except (asyncpg.exceptions.InsufficientPrivilegeError, asyncpg.exceptions.UndefinedTableError,
                    asyncpg.exceptions.ReadOnlySQLTransactionError):
                pass
    finally:
        await c.close()
    a = await connect(ADMIN)
    try:
        assert not await a.fetchval("SELECT has_table_privilege('tsb_research_ro', 'public.signals', 'SELECT')")
        assert not await a.fetchval("SELECT has_table_privilege('tsb_dashboard_ro', 'public.trade_results', 'SELECT')")
        assert not await a.fetchval("SELECT pg_has_role('tsb_research_ro', 'tsb_net_group', 'MEMBER')")
    finally:
        await a.close()


async def test_migrator_can_only_become_owner():
    c = await connect('tsb_migrator')        # in owner_stage, its own database
    try:
        await c.execute('SET ROLE tsb_owner')
        assert await c.fetchval('SELECT current_user') == 'tsb_owner'
        for stmt in ('SET ROLE trading_signal_bot', 'SET ROLE tsb_tracker', 'SET ROLE tsb_backup'):
            with pytest.raises(DENIED):
                await c.execute(stmt)
    finally:
        await c.close()


async def test_cannot_signal_other_sessions():
    admin = await connect(ADMIN)
    peer = await connect('tsb_telegram')
    try:
        targets = {ADMIN: await admin.fetchval('SELECT pg_backend_pid()'),
                   'tsb_telegram': await peer.fetchval('SELECT pg_backend_pid()')}
        for role in sorted(LOGIN):
            c = await connect(role)
            try:
                for owner_role, pid in targets.items():
                    if owner_role == role:
                        continue                                  # a role may signal its own sessions (PostgreSQL rule)
                    with pytest.raises(DENIED):
                        await c.fetchval('SELECT pg_terminate_backend($1)', pid)
            finally:
                await c.close()
    finally:
        await peer.close(); await admin.close()


@pytest.mark.parametrize('role', sorted(LOGIN))
@pytest.mark.parametrize('other_db', ['xsch', 'wishlist', 'prod_ref', 'trading_signals'])
async def test_cannot_reach_other_databases(role, other_db):
    # owner_stage is the test cluster's second copy of trading_signals (ownership end state, M-04): not 'other'.
    if other_db == ROLE_DB.get(role, DB):
        pytest.skip('the role\'s own database')
    with pytest.raises((asyncpg.exceptions.InsufficientPrivilegeError,
                        asyncpg.exceptions.InvalidAuthorizationSpecificationError)):
        c = await connect(role, db=other_db)
        await c.close()


@pytest.mark.parametrize('role', sorted(NOLOGIN - {'tsb_login_group', 'tsb_net_group', 'tsb_owner'}))
async def test_nologin_roles_cannot_log_in(role):
    with pytest.raises(asyncpg.exceptions.InvalidAuthorizationSpecificationError):
        await connect(role)                                 # a test password exists; the role still may not log in


# ------------------------------------------------------------------ holdout protection (D6 unresolved) -----------
STATS_ROWS_ADMIN = 0


async def test_research_role_reads_nothing():
    global STATS_ROWS_ADMIN
    a = await connect(ADMIN)
    try:
        await a.execute('ANALYZE')
        STATS_ROWS_ADMIN = await a.fetchval("SELECT count(*) FROM pg_stats WHERE schemaname='public'")
    finally:
        await a.close()
    c = await session('tsb_research_ro')
    try:
        tables = [r['tablename'] for r in await c.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")]
        assert len(tables) == 26
        for t in tables:
            with pytest.raises(DENIED):
                async with c.transaction():
                    await c.fetchval(f'SELECT count(*) FROM public.{t}')
        for (s,) in await c.fetch("SELECT format('%I.%I', schemaname, sequencename) FROM pg_sequences WHERE schemaname='public'"):
            with pytest.raises(DENIED):
                async with c.transaction():
                    await c.fetchval(f'SELECT last_value FROM {s}')
        assert await c.fetchval("SELECT count(*) FROM pg_stats WHERE schemaname='public'") == 0      # no value histograms
        assert STATS_ROWS_ADMIN > 0                                   # the check is not vacuous: statistics exist
        assert await c.fetchval("SELECT count(*) FROM information_schema.column_privileges WHERE grantee='tsb_research_ro'") == 0
        for schema in ('dashboard',):
            with pytest.raises(DENIED):
                async with c.transaction():
                    await c.fetchval(f'SELECT count(*) FROM {schema}.service_health')
    finally:
        await c.close()


async def test_d6c_prototype_filters_holdout_and_is_not_left_applied():
    """Option (c) only, inside a rolled-back transaction: the research layer sees pre-freeze synthetic rows only."""
    proto = open('/r5/research_d6c_prototype.sql').read()
    c = await connect(ADMIN)
    tr = c.transaction(); await tr.start()
    try:
        await c.execute(proto)
        await c.execute('SET LOCAL ROLE tsb_research_ro')
        sig = await c.fetch('SELECT symbol, signal_time FROM research_pre_freeze.signals')
        assert sig and all(r['signal_time'] < FREEZE for r in sig)
        assert {r['symbol'] for r in sig} == {'SYNPREAUSDT', 'SYNPREBUSDT'}             # 09:33:45 in, 09:33:46 out
        for v in ('trade_results', 'active_trades', 'trade_target_fills'):
            n = await c.fetchval(f'SELECT count(*) FROM research_pre_freeze.{v}')
            assert n == 2, (v, n)
        with pytest.raises(DENIED):
            async with c.transaction():
                await c.fetchval('SELECT count(*) FROM public.trade_results')
    finally:
        await tr.rollback(); await c.close()
    c = await connect(ADMIN)
    try:
        assert not await c.fetchval("SELECT 1 FROM pg_namespace WHERE nspname='research_pre_freeze'")
    finally:
        await c.close()


# ------------------------------------------------------------------ A59 dashboard -------------------------------
DASH_VIEWS = ('service_health', 'open_positions', 'outbox_health', 'signal_flow_hourly', 'risk_state', 'schema_version')
FORBIDDEN_COLUMN = re.compile(r'profit|pnl|result|price|loss|feature|snapshot|score|target|peak|remaining|fraction|^last_error$', re.I)


async def test_dashboard_allowlist_only():
    c = await session('tsb_dashboard_ro')
    try:
        for v in DASH_VIEWS:
            await c.fetch(f'SELECT * FROM dashboard.{v} LIMIT 5')
        cols = await c.fetch("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='dashboard'")
        assert {r['table_name'] for r in cols} == set(DASH_VIEWS)
        bad = [f"{r['table_name']}.{r['column_name']}" for r in cols if FORBIDDEN_COLUMN.search(r['column_name'])]
        assert not bad, bad
        for t in ('signals', 'trade_results', 'active_trades', 'risk_management', 'service_heartbeats'):
            with pytest.raises(DENIED):
                async with c.transaction():
                    await c.fetchval(f'SELECT count(*) FROM public.{t}')
        await c.execute('SET default_transaction_read_only = off')
        for stmt in ("UPDATE dashboard.service_health SET consecutive_errors = 0",
                     "DELETE FROM dashboard.open_positions", "CREATE VIEW dashboard.r5 AS SELECT 1"):
            with pytest.raises(DENIED):
                async with c.transaction():
                    await c.execute(stmt)
    finally:
        await c.close()


async def test_only_dashboard_role_reads_dashboard_views():
    c = await connect(ADMIN)
    try:
        for role in ALL_TSB - {'tsb_dashboard_ro'}:
            assert not await c.fetchval("SELECT has_schema_privilege($1, 'dashboard', 'USAGE')", role), role
    finally:
        await c.close()


# ------------------------------------------------------------------ backup and migration separation ------------
async def test_backup_reads_everything_writes_nothing():
    c = await connect('tsb_backup')
    try:
        for (t,) in await c.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'"):
            await c.fetchval(f'SELECT count(*) FROM public.{t}')
        assert await c.fetchval('SHOW default_transaction_read_only') == 'on'
        with pytest.raises(asyncpg.exceptions.ReadOnlySQLTransactionError):
            await c.execute("INSERT INTO symbol_blacklist (symbol) VALUES ('X')")
    finally:
        await c.close()


async def test_future_tables_deny_by_default_except_backup():
    admin = await connect(ADMIN)
    try:
        await admin.execute('CREATE TABLE public.r5_future_table (x int)')
        for role in ALL_TSB:
            for p in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
                held = await admin.fetchval('SELECT has_table_privilege($1, $2, $3)', role, 'public.r5_future_table', p)
                assert held == (role == 'tsb_backup' and p == 'SELECT'), (role, p)
    finally:
        await admin.execute('DROP TABLE IF EXISTS public.r5_future_table')
        await admin.close()


async def test_runtime_roles_are_separate_from_admin_backup_and_migration():
    c = await connect(ADMIN)
    try:
        for role in set(RUNTIME) | {'tsb_learner', 'tsb_dashboard_ro', 'tsb_research_ro'}:
            for other in (ADMIN, 'tsb_backup', 'tsb_migrator', 'tsb_owner'):
                assert not await c.fetchval("SELECT pg_has_role($1, $2, 'USAGE') OR pg_has_role($1, $2, 'SET')", role, other)
        assert not await c.fetchval("SELECT pg_has_role('tsb_backup', 'tsb_owner', 'MEMBER')")
        assert not await held_privileges(c, 'tsb_migrator')        # no table privilege of its own anywhere in public
    finally:
        await c.close()


# ------------------------------------------------------------------ connections, timeouts, rollback -------------
@pytest.mark.parametrize('role', sorted(RUNTIME))
async def test_pool_plus_healthcheck_fit_connection_limit(role):
    conns = []
    try:
        for _ in range(POOL_MAX + HEALTHCHECK_POOL):
            conns.append(await connect(role))
    finally:
        for c in conns:
            await c.close()


async def test_connection_limit_is_enforced():
    conns = []
    try:
        for _ in range(SERVICE_LIMIT):
            conns.append(await connect('tsb_analyzer'))
        with pytest.raises(asyncpg.exceptions.TooManyConnectionsError):
            conns.append(await connect('tsb_analyzer'))
    finally:
        for c in conns:
            await c.close()


async def test_denied_statement_rolls_back_the_whole_transaction():
    """A privilege error inside a tracker transaction leaves no partial write behind."""
    c = await connect('tsb_tracker')
    try:
        with pytest.raises(DENIED):
            async with c.transaction():
                await c.execute("INSERT INTO active_trades (symbol, entry_price, target_1, target_2, target_3, stop_loss) "
                                "VALUES ('R5ROLLBACKUSDT', 1, 1.01, 1.02, 1.03, 0.99)")
                await c.execute('INSERT INTO risk_recovery_events DEFAULT VALUES')
        assert await c.fetchval("SELECT count(*) FROM active_trades WHERE symbol='R5ROLLBACKUSDT'") == 0
    finally:
        await c.close()


async def test_session_timeouts_apply_to_roles():
    c = await connect('tsb_tracker')
    try:
        await c.execute("SET statement_timeout = '200ms'")
        with pytest.raises(asyncpg.exceptions.QueryCanceledError):
            await c.execute('SELECT pg_sleep(1)')
        await c.execute("SET idle_in_transaction_session_timeout = '30s'")
        assert await c.fetchval('SELECT 1') == 1
    finally:
        await c.close()
