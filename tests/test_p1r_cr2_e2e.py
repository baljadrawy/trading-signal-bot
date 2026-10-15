"""P1-R end to end on a REAL disposable PostgreSQL: forward instrumentation on the CR-2 contract.

signal_engine.save_signal -> outbox 'signal.ready' -> telegram.handle_candidate_event (bot stubbed)
-> 'signal.delivered' -> trade_tracker (register_new_signals + delivery-event loop + expiry sweep).

Every scenario runs in independent fresh databases for each arm and compares the decision-relevant
database state:
  * P1-R with forward instrumentation OFF  — must write no evidence and no P1 persistence;
  * P1-R with instrumentation ON           — must record the expected outcome codes;
  * develop (P1_BEFORE_TREE, optional)     — the decision code before P1-R.
OFF == ON == develop for every decision field (signals, outbox, trades, risk state). Only the
P1 lineage key features_snapshot.identity may differ, and only in the ON arm.

Skipped unless P1R_TEST_DSN points at a THROWAWAY server. The test creates and drops its own
databases (p1r_e2e_*) there; never point it at production.
"""
import sys; sys.path.insert(0, '.')
import asyncio
import datetime as dt
import importlib.util
import json
import os
import types
from pathlib import Path

import pytest

asyncpg = pytest.importorskip('asyncpg')
from shared import evidence_v2 as ev2                     # noqa: E402
from shared.config import config                          # noqa: E402
from shared.database import Database                      # noqa: E402
from evidence_v2_fakes import IDENT                       # noqa: E402

DSN = os.getenv('P1R_TEST_DSN')
BEFORE = os.getenv('P1_BEFORE_TREE')
AFTER = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not DSN, reason='P1R_TEST_DSN not set (disposable PostgreSQL required)')

SCHEMA = [AFTER / 'database' / 'init.sql',
          AFTER / 'database' / 'migrate_features_snapshot_2026_06_23.sql',
          AFTER / 'database' / 'migrate_live_learning_2026_06_25.sql',
          *sorted((AFTER / 'database' / 'migrations').glob('[0-9][0-9][0-9]_*.sql'))]
VOLATILE = {'id', 'signal_id', 'active_trade_id', 'aggregate_id', 'signal_time', 'opened_at',
            'closed_at', 'created_at', 'updated_at', 'available_at', 'locked_at', 'locked_by',
            'processed_at', 'date', 'payload', 'last_error', 'decision_at', 'requested_at',
            'expires_at', 'responded_at', 'exit_time', 'last_price_check', 'risk_epoch_start',
            # A38 metadata (NULL in trees before A38; asserted in tests/test_a38_*):
            'entry_fill_model', 'deferrals', 'outcome'}


# ---------------------------------------------------------------- module sets per code tree --------
def _load(name, path, extra_path=None):
    if extra_path:
        sys.path.insert(0, extra_path)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        if extra_path:
            sys.path.remove(extra_path)


def _ptb_stubs():
    class _Any:
        def __init__(self, *a, **k):
            pass
    tg = types.ModuleType('telegram')
    for n in ('Bot', 'BotCommand', 'InlineKeyboardButton', 'InlineKeyboardMarkup', 'Update'):
        setattr(tg, n, type(n, (_Any,), {}))
    ext = types.ModuleType('telegram.ext')
    for n in ('Application', 'CallbackQueryHandler', 'CommandHandler'):
        setattr(ext, n, type(n, (_Any,), {}))
    ext.ContextTypes = type('ContextTypes', (), {'DEFAULT_TYPE': object})
    tg.ext = ext
    return {'telegram': tg, 'telegram.ext': ext}


_SETS = {}


def modules(arm):
    """(signal_logic, telegram main, tracker main) of the tree behind `arm` ('after' or 'before')."""
    if arm in _SETS:
        return _SETS[arm]
    root = Path(BEFORE) if arm == 'before' else AFTER
    se = _load(f'p1r_signal_logic_{arm}', root / 'signal_engine' / 'signal_logic.py',
               str(root / 'signal_engine'))
    saved = {k: sys.modules.get(k) for k in ('telegram', 'telegram.ext', 'whitelist')}
    try:
        sys.modules.update(_ptb_stubs())
        sys.modules.pop('whitelist', None)
        tg = _load(f'p1r_telegram_{arm}', root / 'telegram' / 'main.py', str(root / 'telegram'))
    finally:
        for k, v in saved.items():
            sys.modules.pop(k, None) if v is None else sys.modules.__setitem__(k, v)
    tr = _load(f'p1r_tracker_{arm}', root / 'trade_tracker' / 'main.py', str(root / 'trade_tracker'))
    _SETS[arm] = (se, tg, tr)
    return _SETS[arm]


# ---------------------------------------------------------------- environment ---------------------
class Env:
    def __init__(self, arm, mode, monkeypatch, tmp):
        self.arm, self.mode, self.mp, self.tmp = arm, mode, monkeypatch, tmp
        self.db = f"p1r_e2e_{arm}_{mode}"
        self.se, self.tg, self.tr = modules(arm)
        self.prices = {}
        self.sinks = {}

    async def __aenter__(self):
        admin = await asyncpg.connect(DSN)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS {self.db} WITH (FORCE)')
            await admin.execute(f'CREATE DATABASE {self.db}')
        finally:
            await admin.close()
        dsn = DSN.rsplit('/', 1)[0] + '/' + self.db
        conn = await asyncpg.connect(dsn)
        try:
            for path in SCHEMA:
                await conn.execute(Path(path).read_text(encoding='utf-8'))
        finally:
            await conn.close()
        self.pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
        self.mp.setattr(Database, '_pool', self.pool)
        self.mp.setattr(config, 'ENABLE_EVIDENCE_RECORDER', False)
        self.mp.setattr(config, 'MAX_OPEN_TRADES', 10)
        self.mp.setattr(config, 'RISK_CANARY_MAX_OPEN_TRADES', 5)
        self.mp.setattr(config, 'EVIDENCE_V2_DIR', str(self.tmp / 'evidence_v2'))
        self.mp.setattr(config, 'EVIDENCE_V2_ENABLED', self.mode == 'on')
        ev2.reset_for_tests()
        if self.mode == 'on':
            for svc in ('signal_engine', 'telegram', 'trade_tracker'):
                sink = ev2.ListSink()
                ev2._RECORDERS[svc] = ev2.RecorderV2(svc, sink, IDENT)
                self.sinks[svc] = sink
        if hasattr(self.tg, 'DELIVERY_PACING_SECONDS'):
            self.mp.setattr(self.tg, 'DELIVERY_PACING_SECONDS', 0)

        async def price(symbol):
            return self.prices.get(symbol, 99.5)

        async def notional(symbol):
            return 5.0
        self.mp.setattr(self.tr, 'get_current_price', price)
        self.mp.setattr(self.tr, 'get_min_notional', notional)
        if hasattr(self.tr, '_V2_EXPIRY_STATE'):          # P1-FIX watermark (per scenario)
            self.tr._V2_EXPIRY_STATE.clear()
        if hasattr(self.tr, '_V2_LAST_OUTCOME'):
            self.tr._V2_LAST_OUTCOME.clear()
            self.mp.setattr(self.tr, '_V2_PROCESS_STARTED',
                            dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=1))
        return self

    async def __aexit__(self, *exc):
        await self.pool.close()
        admin = await asyncpg.connect(DSN)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS {self.db} WITH (FORCE)')
        finally:
            await admin.close()

    # -- helpers ------------------------------------------------------------------------------
    async def sql(self, q, *a):
        return await self.pool.execute(q, *a)

    async def val(self, q, *a):
        return await self.pool.fetchval(q, *a)

    async def resume(self):
        await self.sql("INSERT INTO risk_management (date, is_trading_paused, pause_reason) "
                       "VALUES (CURRENT_DATE - 1, false, 'manual_resume')")

    async def pause(self, reason):
        await self.sql("INSERT INTO risk_management (date, is_trading_paused, pause_reason) "
                       "VALUES (CURRENT_DATE, true, $1) ON CONFLICT (date) DO UPDATE "
                       "SET is_trading_paused=true, pause_reason=$1", reason)

    async def save(self, **kw):
        sig = {'symbol': 'P1RUSDT', 'timeframe': '4h', 'market_condition': 'bullish',
               'entry_price': 100.0, 'target_1': 102.0, 'target_2': 104.0, 'target_3': 106.0,
               'stop_loss': 97.0, 'total_score': 4, 'trade_type': 'reversion', 'score_details': {},
               'confirmed_timeframes': ['4h'], 'timeframe_confirmations': 1,
               'macro_snapshot': {'usdtd_trend': 'flat'}}
        sig.update(kw)
        return await self.se.SignalEngine().save_signal(sig)

    async def enqueue(self, event_type, sid, payload=None):
        from shared.outbox import enqueue
        async with self.pool.acquire() as conn:
            return await enqueue(conn, event_type, 'signal', sid, payload or {'signal_id': sid})

    async def telegram_pass(self):
        tg = self.tg
        owner = tg.worker_id('telegram-p1r')
        mgr, delivered = tg.ApprovalManager(), 0
        for et in tg.CANDIDATE_EVENT_TYPES:
            for ev in await tg.claim(et, owner, limit=5):
                if await tg.handle_candidate_event(None, mgr, owner, et, ev):
                    delivered += 1
        return delivered

    async def tracker_pass(self):
        """Verbatim transcription of trade_tracker.main()'s delivery section (P1-R hooks are called
        only when the module has them; tests/test_p1r_cr2_e2e asserts the transcription matches)."""
        tr = self.tr
        owner = tr.worker_id('tracker-p1r')
        hooks = hasattr(tr, '_v2_delivery_consumed')
        delivery_events = await tr.claim('signal.delivered', owner, limit=50)
        await tr.register_new_signals()
        if hasattr(tr, 'reconcile_delivery_events'):        # A38: the loop is a function
            await tr.reconcile_delivery_events(delivery_events, owner)
            await tr._v2_expiry_sweep()
            return
        for event in delivery_events:
            active = await Database.fetchval("SELECT 1 FROM active_trades WHERE signal_id=$1",
                                             event['aggregate_id'])
            if active:
                await tr.ack(event['id'], owner)
                if hooks:
                    await tr._v2_delivery_consumed(event, 'opened')
                continue
            terminal = await Database.fetchval(tr.DELIVERY_TERMINAL_SQL, event['aggregate_id'])
            if terminal:
                await tr.ack(event['id'], owner)
                if hooks:
                    await tr._v2_delivery_consumed(event, 'terminal')
            else:
                await tr.fail(event['id'], owner, RuntimeError('trade registration deferred'), 300)
                if hooks:
                    await tr._v2_delivery_consumed(event, 'deferred')
        if hooks:
            await tr._v2_expiry_sweep()

    async def force_delivered(self, sid):
        await self.sql("UPDATE signals SET telegram_sent=true WHERE id=$1", sid)
        await self.enqueue('signal.delivered', sid)

    async def due_now(self):
        await self.sql("UPDATE outbox_events SET available_at=NOW() WHERE status='pending'")

    async def snapshot(self):
        tables = {
            'signals': "SELECT * FROM signals ORDER BY symbol, id",
            'outbox': "SELECT event_type, aggregate_type, status, attempts, max_attempts "
                      "FROM outbox_events ORDER BY id",
            'active_trades': "SELECT * FROM active_trades ORDER BY symbol, id",
            'risk': "SELECT is_trading_paused, pause_reason, signals_sent FROM risk_management "
                    "ORDER BY date",
            'blacklist': "SELECT symbol FROM symbol_blacklist ORDER BY symbol",
        }
        out = {}
        for name, q in tables.items():
            rows = []
            for r in await self.pool.fetch(q):
                d = {}
                for k, v in dict(r).items():
                    if k in VOLATILE or isinstance(v, (dt.datetime, dt.date)):
                        continue
                    if k == 'features_snapshot' and v is not None:
                        fs = json.loads(v) if isinstance(v, str) else dict(v)
                        fs.pop('identity', None)            # P1 lineage key (ON arm only)
                        v = fs
                    d[k] = round(float(v), 9) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
                rows.append(d)
            out[name] = rows
        return json.loads(json.dumps(out, sort_keys=True, default=str))

    async def identity_count(self):
        return await self.val("SELECT count(*) FROM signals WHERE features_snapshot ? 'identity'")

    def events(self):
        out = []
        for svc, sink in self.sinks.items():
            ev2._RECORDERS[svc].flush_now()
            out.extend(sink.records())
        return out


# ---------------------------------------------------------------- scenarios ------------------------
async def s_ready_opened(env):
    await env.resume()
    sid = await env.save()
    assert await env.telegram_pass() == 1
    await env.tracker_pass()
    assert await env.val("SELECT count(*) FROM active_trades WHERE signal_id=$1", sid) == 1


async def s_incomplete(env):
    await env.resume()
    with pytest.raises(ValueError):
        await env.save(stop_loss=0)
    assert await env.val("SELECT count(*) FROM signals") == 0


async def s_b3_blocked(env):
    await env.resume()
    await env.pause('risk:loss_streak_halt')
    sid = await env.save()
    assert await env.telegram_pass() == 0
    await env.force_delivered(sid)                      # even forced past telegram: no trade
    await env.tracker_pass()
    assert await env.val("SELECT count(*) FROM active_trades") == 0


async def s_paused(env):
    await env.resume()
    await env.pause('إيقاف يدوي')
    await env.save()
    assert await env.telegram_pass() == 0


async def s_not_ready(env):
    await env.resume()
    sid = await env.val("""INSERT INTO signals (symbol, timeframe, market_condition, entry_price,
        target_1, target_2, target_3, stop_loss, score, decision_source, strategy_version, trade_type)
        VALUES ('NRUSDT','4h','bullish',100,102,104,106,97,4,'signal_engine','v','reversion') RETURNING id""")
    await env.enqueue('signal.ready', sid)
    assert await env.telegram_pass() == 0
    await env.force_delivered(sid)
    await env.tracker_pass()
    assert await env.val("SELECT count(*) FROM active_trades") == 0


async def s_duplicate(env):
    await env.resume()
    sid = await env.save()
    assert await env.enqueue('signal.ready', sid) is None          # outbox uniqueness
    await env.sql("UPDATE signals SET claude_approved=true WHERE id=$1", sid)
    assert await env.enqueue('signal.reviewed', sid) is not None   # rollback overlap
    assert await env.telegram_pass() == 1
    assert await env.telegram_pass() == 0
    await env.tracker_pass()
    await env.tracker_pass()
    assert await env.val("SELECT count(*) FROM active_trades WHERE signal_id=$1", sid) == 1


async def s_stale(env):
    await env.resume()
    sid = await env.save()
    env.prices['P1RUSDT'] = 100.5                       # limit wait first ...
    assert await env.telegram_pass() == 1
    await env.sql("UPDATE signals SET signal_time = NOW() - INTERVAL '3 hours' WHERE id=$1", sid)
    await env.tracker_pass()                             # ... then stale at handling time


async def s_blacklisted(env):
    await env.resume()
    sid = await env.save()
    assert await env.telegram_pass() == 1
    await env.sql("INSERT INTO symbol_blacklist (symbol) VALUES ('P1RUSDT')")
    await env.tracker_pass()
    assert await env.val("SELECT count(*) FROM active_trades WHERE signal_id=$1", sid) == 0


async def s_rejected(env):
    await env.resume()
    sid = await env.save()
    assert await env.telegram_pass() == 1
    await env.sql("INSERT INTO approval_requests (signal_id, symbol, expires_at, status, "
                  "entry_price_at_request) VALUES ($1, 'P1RUSDT', NOW() + INTERVAL '1 hour', "
                  "'rejected', 100)", sid)
    await env.tracker_pass()
    assert await env.val("SELECT count(*) FROM active_trades WHERE signal_id=$1", sid) == 0


async def s_no_fill(env):
    await env.resume()
    sid = await env.save()
    env.prices['P1RUSDT'] = 100.5                       # above planned entry: limit wait, never fills
    assert await env.telegram_pass() == 1
    await env.sql("UPDATE outbox_events SET max_attempts=2 WHERE event_type='signal.delivered'")
    await env.tracker_pass()                             # attempt 1: deferred
    await env.due_now()
    await env.tracker_pass()                             # attempt 2
    status = await env.val("SELECT status FROM outbox_events WHERE event_type='signal.delivered'")
    a38 = hasattr(env.tr, 'reconcile_delivery_events')
    # before A38: the open admission window exhausted the budget -> a misleading dead letter.
    # A38: a deferral is not an attempt -> still pending, budget untouched.
    assert status == ('pending' if a38 else 'dead')
    await env.sql("UPDATE signals SET signal_time = NOW() - INTERVAL '2 hours 5 minutes' WHERE id=$1", sid)
    await env.due_now()
    await env.tracker_pass()                             # admission window closed: NO_FILL
    assert await env.val("SELECT count(*) FROM active_trades") == 0
    if a38:
        row = await env.pool.fetchrow("SELECT status, attempts, deferrals, outcome FROM outbox_events "
                                      "WHERE event_type='signal.delivered'")
        assert (row['status'], row['attempts'], row['outcome']) == ('completed', 1, 'terminal:STALE')
        assert row['deferrals'] == 2


async def s_entry_rejected(env):
    await env.resume()
    sid = await env.save()
    env.prices['P1RUSDT'] = 96.5                        # at/below stop before fill
    assert await env.telegram_pass() == 1
    await env.tracker_pass()
    assert await env.val("SELECT telegram_sent FROM signals WHERE id=$1", sid) is False


async def s_legacy_reviewed(env):
    await env.resume()
    sid = await env.val("""INSERT INTO signals (symbol, timeframe, market_condition, entry_price,
        target_1, target_2, target_3, stop_loss, score, decision_source, strategy_version, trade_type,
        claude_approved, claude_comment)
        VALUES ('LGUSDT','4h','bullish',100,102,104,106,97,4,'policy_auto','v','reversion',true,
                'legacy relay') RETURNING id""")
    await env.enqueue('signal.reviewed', sid, {'signal_id': sid, 'approved': True})
    assert await env.telegram_pass() == 1
    await env.tracker_pass()
    assert await env.val("SELECT count(*) FROM active_trades WHERE signal_id=$1", sid) == 1


async def s_capacity(env):
    await env.resume()
    env.mp.setattr(config, 'RISK_CANARY_MAX_OPEN_TRADES', 1)
    await env.sql("""INSERT INTO active_trades (signal_id, symbol, timeframe, entry_price, target_1,
        target_2, target_3, stop_loss, status) VALUES (NULL,'OPENUSDT','4h',10,11,12,13,9,'open')""")
    await env.save()
    assert await env.telegram_pass() == 0


SCENARIOS = {
    'ready_opened': (s_ready_opened, {('signal.ready', 'POLICY_READY'), ('delivery.sent', 'DELIVERED'),
                                      ('entry.attempt', 'ENTRY_MARKET'), ('admission.decision', 'OPENED'),
                                      ('delivery.consumed', 'OPENED')}),
    'incomplete': (s_incomplete, {('signal.refused', 'INCOMPLETE_SIGNAL')}),
    'b3_blocked': (s_b3_blocked, {('delivery.refused', 'B3_BLOCKED'), ('admission.decision', 'B3_BLOCKED')}),
    'paused': (s_paused, {('delivery.refused', 'PAUSED')}),
    'not_ready': (s_not_ready, {('delivery.skipped', 'NOT_READY'), ('delivery.consumed', 'NOT_READY')}),
    'duplicate': (s_duplicate, {('delivery.sent', 'DELIVERED'), ('delivery.skipped', 'DUPLICATE'),
                                ('delivery.consumed', 'OPENED')}),
    'stale': (s_stale, {('delivery.consumed', 'STALE')}),
    'blacklisted': (s_blacklisted, {('delivery.consumed', 'BLACKLISTED')}),
    'rejected': (s_rejected, {('delivery.consumed', 'REJECTED')}),
    'no_fill': (s_no_fill, {('entry.attempt', 'AWAITING_FILL'), ('delivery.consumed', 'AWAITING_FILL'),
                            ('entry.expired', 'NO_FILL')}),
    'entry_rejected': (s_entry_rejected, {('entry.attempt', 'ENTRY_REJECTED'),
                                          ('delivery.consumed', 'ENTRY_REJECTED')}),
    'legacy_reviewed': (s_legacy_reviewed, {('delivery.sent', 'DELIVERED'), ('admission.decision', 'OPENED')}),
    'capacity': (s_capacity, {('delivery.refused', 'CAPACITY')}),
}


def _decision_view(snapshot):
    """Decision state for before/after-A38 parity: everything, except the reconciliation status
    of `signal.delivered` outbox rows, which A38 changes on purpose (an open admission window is
    a deferral, not a failed attempt). Asserted directly in s_no_fill and tests/test_a38_*."""
    view = json.loads(json.dumps(snapshot))
    for row in view.get('outbox', []):
        if row.get('event_type') == 'signal.delivered':
            row.pop('status', None)
            row.pop('attempts', None)
    return view


def _arm(name, arm, mode, monkeypatch, tmp_path):
    fn = SCENARIOS[name][0]

    async def go():
        async with Env(arm, mode, monkeypatch, tmp_path / f'{arm}_{mode}') as env:
            await fn(env)
            return await env.snapshot(), await env.identity_count(), (env.events() if mode == 'on' else [])
    return asyncio.run(go())


@pytest.mark.parametrize('name', list(SCENARIOS))
def test_scenario_decision_parity_and_outcomes(name, monkeypatch, tmp_path):
    off, off_ids, _ = _arm(name, 'after', 'off', monkeypatch, tmp_path)
    on, on_ids, events = _arm(name, 'after', 'on', monkeypatch, tmp_path)
    assert on == off, f'{name}: instrumentation changed decision state'
    assert off_ids == 0, 'features_snapshot.identity written while instrumentation OFF'
    assert not (tmp_path / 'after_off' / 'evidence_v2').exists(), 'evidence files written while OFF'
    if BEFORE:
        before, before_ids, _ = _arm(name, 'before', 'off', monkeypatch, tmp_path)
        assert _decision_view(before) == _decision_view(off), f'{name}: P1-R differs from develop'
        assert before_ids == 0
    got = {(e['event_type'], (e.get('payload') or {}).get('outcome_code')) for e in events}
    missing = SCENARIOS[name][1] - got
    assert not missing, f'{name}: missing evidence {missing}; got {sorted(map(str, got))}'
    for e in events:
        code = (e.get('payload') or {}).get('outcome_code')
        assert code is None or code in ev2.OUTCOME_CODES, code
    ev2.reset_for_tests()


def test_no_fill_dead_letter_is_explained(monkeypatch, tmp_path):
    """A38: an unfilled limit order no longer dead-letters its delivery event. Deferrals are not
    attempts, so no consumption is final, and the event completes as terminal STALE when the window
    closes. The evidence explains each wait (AWAITING_FILL) and records the expiry as NO_FILL."""
    _, _, events = _arm('no_fill', 'after', 'on', monkeypatch, tmp_path)
    consumed = [e for e in events if e['event_type'] == 'delivery.consumed']
    assert not [e for e in consumed if e['payload'].get('final_attempt')]
    waits = [e for e in consumed if e['payload']['outcome_code'] == 'AWAITING_FILL']
    assert len(waits) >= 1                       # identical repeats are suppressed by the recorder
    [terminal] = [e for e in consumed if e['payload']['outcome_code'] == 'STALE']
    assert terminal['payload'].get('resolved_code') == 'NO_FILL'
    [expired] = [e for e in events if e['event_type'] == 'entry.expired']
    assert expired['payload']['outcome_code'] == 'NO_FILL'
    assert expired['payload']['last_outcome_code'] == 'AWAITING_FILL'
    ev2.reset_for_tests()


def test_delivery_outcome_sql_names_exactly_the_terminal_cases(monkeypatch, tmp_path):
    """DELIVERY_OUTCOME_SQL is non-NULL exactly when DELIVERY_TERMINAL_SQL is true."""
    async def go():
        async with Env('after', 'off', monkeypatch, tmp_path / 'eq') as env:
            tr = env.tr
            base = ("INSERT INTO signals (symbol, timeframe, market_condition, entry_price, target_1, "
                    "target_2, target_3, stop_loss, score, decision_source, strategy_version, trade_type, "
                    "telegram_sent, claude_approved, signal_time) VALUES ($1,'4h','bullish',100,102,104,"
                    "106,97,4,$2,'v','reversion',$3,$4,NOW() - $5::interval) RETURNING id")
            cases = []
            for sent in (True, False, None):
                for ds, ca in (('policy_ready', None), ('signal_engine', None), ('policy_auto', True),
                               ('policy_auto', False), (None, None)):
                    for age in (dt.timedelta(minutes=1), dt.timedelta(hours=3)):
                        cases.append(await env.val(base, f'S{len(cases)}USDT', ds, sent, ca, age))
            await env.sql("INSERT INTO symbol_blacklist (symbol) VALUES ('S1USDT')")
            await env.sql("INSERT INTO approval_requests (signal_id, symbol, expires_at, status, "
                          "entry_price_at_request) VALUES ($1,'S2USDT',NOW(),'rejected',100)", cases[2])
            mismatches = []
            for sid in cases:
                terminal = bool(await env.val(tr.DELIVERY_TERMINAL_SQL, sid))
                code = await env.val(tr.DELIVERY_OUTCOME_SQL, sid)
                if terminal != (code is not None):
                    mismatches.append((sid, terminal, code))
            return len(cases), mismatches
    n, mismatches = asyncio.run(go())
    assert n == 30 and mismatches == []


def test_tracker_pass_transcribes_main_loop():
    """The delivery section of trade_tracker.main() calls the hooks exactly where tracker_pass does."""
    import inspect
    _, _, tr = modules('after')
    src = ' '.join(inspect.getsource(tr.main).split())
    if hasattr(tr, 'reconcile_delivery_events'):       # A38: delivery loop extracted
        order = ["claim('signal.delivered', owner, limit=50)", 'register_new_signals()',
                 'await reconcile_delivery_events(delivery_events, owner)',
                 'await _v2_expiry_sweep()']
        pos = [src.find(o) for o in order]
        assert all(p >= 0 for p in pos) and pos == sorted(pos), pos
        body = ' '.join(inspect.getsource(tr.reconcile_delivery_events).split())
        hooks = ["await ack(event['id'], owner, 'opened')",
                 "await _v2_delivery_consumed(event, 'opened')",
                 "await ack(event['id'], owner, f\"terminal:{code or 'UNKNOWN'}\")",
                 "await _v2_delivery_consumed(event, 'terminal')",
                 "await defer(", "await _v2_delivery_consumed(event, 'deferred')"]
        pos = [body.find(h) for h in hooks]
        assert all(p >= 0 for p in pos) and pos == sorted(pos), pos
        return
    order = ["claim('signal.delivered', owner, limit=50)", 'register_new_signals()',
             "await ack(event['id'], owner) await _v2_delivery_consumed(event, 'opened') continue",
             "await ack(event['id'], owner) await _v2_delivery_consumed(event, 'terminal')",
             "RuntimeError('trade registration deferred'), 300) await _v2_delivery_consumed(event, 'deferred')",
             'await _v2_expiry_sweep()']
    pos = [src.find(o) for o in order]
    assert all(p >= 0 for p in pos) and pos == sorted(pos), pos
