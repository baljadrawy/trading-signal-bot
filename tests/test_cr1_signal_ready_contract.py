"""CR-1 / Option 3 contract (no database): signal_engine -> signal.ready -> telegram
-> trade_tracker, with claude_review off the active path.
"""
import asyncio
import os
import re
import subprocess
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from cr1_support import (REPO, load_signal_logic, load_telegram_main, load_tracker_main,
                         valid_signal)
from shared import signal_readiness as sr



# ---------------------------------------------------------------- producer ----------
class TxConn:
    """Records every statement and whether it ran inside conn.transaction()."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.in_tx = False
        self.tx_outcome = None
        self.fail_on = fail_on

    @asynccontextmanager
    async def transaction(self):
        self.in_tx = True
        try:
            yield
            self.tx_outcome = 'commit'
        except BaseException:
            self.tx_outcome = 'rollback'
            raise
        finally:
            self.in_tx = False

    async def _record(self, kind, sql, args):
        self.calls.append((kind, sql, args, self.in_tx))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError('injected failure')

    async def fetchval(self, sql, *args):
        await self._record('fetchval', sql, args)
        return 501 if 'INSERT INTO signals' in sql else 9

    async def execute(self, sql, *args):
        await self._record('execute', sql, args)


def _patch_db(monkeypatch, signal_logic, conn):
    @asynccontextmanager
    async def acquire():
        yield conn

    monkeypatch.setattr(signal_logic.Database, 'acquire', acquire)


async def _engine(monkeypatch, signal_logic):
    engine = signal_logic.SignalEngine()

    async def volume(symbol):
        return 1_000_000.0

    monkeypatch.setattr(engine, '_get_volume_usdt', volume)
    return engine


@pytest.mark.asyncio
async def test_save_signal_emits_signal_ready_in_same_transaction(monkeypatch):
    signal_logic = load_signal_logic()
    conn = TxConn()
    _patch_db(monkeypatch, signal_logic, conn)
    engine = await _engine(monkeypatch, signal_logic)

    signal_id = await engine.save_signal(valid_signal())

    assert signal_id == 501
    insert = [c for c in conn.calls if 'INSERT INTO signals' in c[1]]
    outbox = [c for c in conn.calls if 'outbox_events' in c[1]]
    assert len(insert) == 1 and len(outbox) == 1
    assert insert[0][3] and outbox[0][3], 'insert and enqueue must share the transaction'
    assert conn.tx_outcome == 'commit'
    # decision_source column value is the explicit readiness marker; no claude_approved.
    assert 'decision_source' in insert[0][1] and 'claude_approved' not in insert[0][1]
    assert sr.READY_DECISION_SOURCE in insert[0][2]
    event_type, aggregate_type, aggregate_id, payload = outbox[0][2]
    assert (event_type, aggregate_type, aggregate_id) == ('signal.ready', 'signal', 501)
    import json
    assert json.loads(payload) == {
        'signal_id': 501, 'decision_source': 'policy_ready',
        'strategy_version': signal_logic.config.APP_VERSION}
    assert not any('signal.created' in str(c[2]) for c in conn.calls)


@pytest.mark.asyncio
async def test_enqueue_failure_rolls_back_signal(monkeypatch):
    signal_logic = load_signal_logic()
    conn = TxConn(fail_on='outbox_events')
    _patch_db(monkeypatch, signal_logic, conn)
    engine = await _engine(monkeypatch, signal_logic)
    with pytest.raises(RuntimeError):
        await engine.save_signal(valid_signal())
    assert conn.tx_outcome == 'rollback'


@pytest.mark.parametrize('bad', [
    {'entry_price': None}, {'stop_loss': float('nan')}, {'target_1': 0},
    {'target_3': -1.0}, {'symbol': ''}, {'total_score': 'x'}])
@pytest.mark.asyncio
async def test_incomplete_signal_is_never_saved(monkeypatch, bad):
    signal_logic = load_signal_logic()
    conn = TxConn()
    _patch_db(monkeypatch, signal_logic, conn)
    engine = await _engine(monkeypatch, signal_logic)
    with pytest.raises(ValueError):
        await engine.save_signal(valid_signal(**bad))
    assert conn.calls == []


def test_decision_source_fits_column():
    assert len(sr.READY_DECISION_SOURCE) <= 32


# ---------------------------------------------------------------- telegram ----------
class Recorder:
    def __init__(self):
        self.acked, self.failed, self.direct, self.approval = [], [], [], []
        self.deferred, self.window_remaining_s = [], 3600.0
        self.gate_calls = 0


def _telegram(monkeypatch, signal_row, *, allowed=(True, 'eligible'), action='sent_direct',
              send_error=None):
    tg = load_telegram_main()
    rec = Recorder()

    class DB:
        async def fetchrow(self, sql, *args):
            assert 'FROM signals' in sql
            if 'remaining_s' in sql:                  # A38 admission-window probe
                return {'remaining_s': rec.window_remaining_s}
            return signal_row

    async def ack(event_id, owner):
        rec.acked.append(event_id)

    async def fail(event_id, owner, err, *a):
        rec.failed.append((event_id, err))

    async def defer(event_id, owner, delay, reason):
        rec.deferred.append((event_id, delay, reason))

    async def gate():
        rec.gate_calls += 1
        return allowed

    async def direct(bot, signal):
        if send_error:
            raise send_error
        rec.direct.append(signal['id'])

    async def approval(bot, signal):
        rec.approval.append(signal['id'])

    class Mgr:
        async def process_signal(self, signal):
            return action

    monkeypatch.setattr(tg, 'Database', DB())
    monkeypatch.setattr(tg, 'ack', ack)
    monkeypatch.setattr(tg, 'fail', fail)
    monkeypatch.setattr(tg, 'defer', defer)
    monkeypatch.setattr(tg, 'can_deliver_candidate', gate)
    monkeypatch.setattr(tg, 'send_signal_direct', direct)
    monkeypatch.setattr(tg, 'send_approval_request', approval)
    monkeypatch.setattr(tg, 'DELIVERY_PACING_SECONDS', 0)
    return tg, rec, Mgr()


def _row(**kw):
    row = {'id': 7, 'symbol': 'CR1USDT', 'telegram_sent': False,
           'decision_source': 'policy_ready', 'claude_approved': None}
    row.update(kw)
    return row


EVENT = {'id': 70, 'aggregate_id': 7}


def test_telegram_consumes_ready_first_and_legacy_reviewed():
    tg = load_telegram_main()
    assert tg.CANDIDATE_EVENT_TYPES == ('signal.ready', 'signal.reviewed')


@pytest.mark.asyncio
async def test_ready_signal_is_delivered(monkeypatch):
    tg, rec, mgr = _telegram(monkeypatch, _row())
    assert await tg.handle_candidate_event(None, mgr, 'o', 'signal.ready', EVENT) is True
    assert rec.direct == [7] and rec.acked == [70] and rec.gate_calls == 1


@pytest.mark.parametrize('row', [
    _row(decision_source='signal_engine'),             # stuck pre-CR-1 row, not ready
    _row(decision_source=None),
    _row(decision_source='policy_auto', claude_approved=True),  # ready-event gate is strict
    _row(decision_source='claude', claude_approved=False),
    None,
])
@pytest.mark.asyncio
async def test_not_ready_signal_is_acked_never_delivered(monkeypatch, row):
    tg, rec, mgr = _telegram(monkeypatch, row)
    assert await tg.handle_candidate_event(None, mgr, 'o', 'signal.ready', EVENT) is False
    assert rec.direct == [] and rec.approval == [] and rec.acked == [70]
    assert rec.gate_calls == 0


@pytest.mark.asyncio
async def test_pause_gate_blocks_delivery(monkeypatch):
    tg, rec, mgr = _telegram(monkeypatch, _row(), allowed=(False, 'risk:loss_streak_halt'))
    assert await tg.handle_candidate_event(None, mgr, 'o', 'signal.ready', EVENT) is False
    assert rec.direct == [] and rec.acked == [70] and rec.gate_calls == 1


@pytest.mark.asyncio
async def test_already_sent_signal_is_not_delivered_again(monkeypatch):
    for event_type in ('signal.ready', 'signal.reviewed'):
        tg, rec, mgr = _telegram(
            monkeypatch, _row(telegram_sent=True, claude_approved=True))
        assert await tg.handle_candidate_event(None, mgr, 'o', event_type, EVENT) is False
        assert rec.direct == [] and rec.acked == [70] and rec.gate_calls == 0


@pytest.mark.asyncio
async def test_legacy_reviewed_requires_claude_approved_true(monkeypatch):
    tg, rec, mgr = _telegram(
        monkeypatch, _row(decision_source='policy_auto', claude_approved=True))
    assert await tg.handle_candidate_event(None, mgr, 'o', 'signal.reviewed', EVENT) is True
    assert rec.direct == [7]
    for approved in (None, False):
        tg, rec, mgr = _telegram(
            monkeypatch, _row(decision_source='policy_ready', claude_approved=approved))
        assert await tg.handle_candidate_event(None, mgr, 'o', 'signal.reviewed', EVENT) is False
        assert rec.direct == []


@pytest.mark.asyncio
async def test_unknown_event_type_never_delivers(monkeypatch):
    tg, rec, mgr = _telegram(monkeypatch, _row(claude_approved=True))
    assert await tg.handle_candidate_event(None, mgr, 'o', 'signal.created', EVENT) is False
    assert rec.direct == []


@pytest.mark.asyncio
async def test_approval_flow_preserved(monkeypatch):
    tg, rec, mgr = _telegram(monkeypatch, _row(), action='awaiting_approval')
    assert await tg.handle_candidate_event(None, mgr, 'o', 'signal.ready', EVENT) is True
    assert rec.approval == [7] and rec.direct == []


@pytest.mark.asyncio
async def test_delivery_error_is_retried_never_acked(monkeypatch):
    # A38 contract: a transient error inside the admission window is DEFERRED (retried later
    # without consuming an attempt); a permanent error still uses fail(). Neither is acked.
    tg, rec, mgr = _telegram(monkeypatch, _row(), send_error=ConnectionError('db'))
    assert await tg.handle_candidate_event(None, mgr, 'o', 'signal.ready', EVENT) is False
    assert rec.acked == [] and rec.failed == []
    assert rec.deferred and rec.deferred[0][0] == 70 and rec.deferred[0][1] <= 3601
    tg, rec, mgr = _telegram(monkeypatch, _row(), send_error=ValueError('defect'))
    assert await tg.handle_candidate_event(None, mgr, 'o', 'signal.ready', EVENT) is False
    assert rec.acked == [] and rec.deferred == [] and rec.failed and rec.failed[0][0] == 70


# ---------------------------------------------------------------- trade_tracker -----
def test_delivery_terminal_sql_uses_readiness_predicate():
    tracker = load_tracker_main()
    sql = tracker.DELIVERY_TERMINAL_SQL
    assert f'NOT {sr.READY_SQL_PREDICATE}' in sql
    for fragment in ('NOT s.telegram_sent', "INTERVAL '2 hours'", 'symbol_blacklist',
                     "ar.status='rejected'"):
        assert fragment in sql
    assert 'NOT s.claude_approved' not in sql


@pytest.mark.asyncio
async def test_new_signal_selection_requires_sent_and_ready(monkeypatch):
    tracker = load_tracker_main()
    seen = []

    class DB:
        async def fetchval(self, sql, *a):
            return 0

        async def fetch(self, sql, *a):
            seen.append(sql)
            return []

    monkeypatch.setattr(tracker, 'Database', DB())
    await tracker.register_new_signals()
    assert len(seen) == 1
    sql = ' '.join(seen[0].split())
    assert 's.telegram_sent = true' in sql
    assert f'AND {sr.READY_SQL_PREDICATE}' in sql
    for fragment in ('at.id IS NULL', "s.signal_time > NOW() - INTERVAL '2 hours'",
                     "at2.status = 'open'", 'at3.opened_at > NOW()',
                     "ar.status = 'rejected'", 'FROM symbol_blacklist'):
        assert fragment in sql
    assert 'AND s.claude_approved = true' not in sql


def test_ready_predicate_semantics():
    p = sr.READY_SQL_PREDICATE
    assert "s.decision_source IS NOT DISTINCT FROM 'policy_ready'" in p
    assert 's.claude_approved IS TRUE' in p and ' OR ' in p
    assert sr.is_ready_row({'decision_source': 'policy_ready', 'claude_approved': None})
    assert sr.is_ready_row({'decision_source': 'policy_auto', 'claude_approved': True})
    assert not sr.is_ready_row({'decision_source': 'signal_engine', 'claude_approved': None})
    assert not sr.is_ready_row({'decision_source': 'claude', 'claude_approved': False})


# ---------------------------------------------------------------- statistics --------
def test_policy_decisions_are_not_labelled_as_claude():
    assert 'Claude' not in sr.decision_label('policy_ready', None)
    assert 'Claude' not in sr.decision_label('policy_auto', True)
    assert 'Claude' in sr.decision_label('claude', True)
    assert 'قديمة' in sr.decision_label('claude', True)
    assert sr.decision_category('system_fail_closed', False) == 'fail_closed'
    assert sr.decision_category('legacy_unknown', True) == 'legacy_approved'
    assert sr.decision_category('signal_engine', None) == 'not_ready'


class Chat:
    id = 1


class Msg:
    def __init__(self):
        self.text = None

    async def reply_text(self, text, **kw):
        self.text = text


@pytest.mark.asyncio
async def test_performance_screen_counts_by_decision_source(monkeypatch):
    tg = load_telegram_main()
    monkeypatch.setattr(tg.config, 'TELEGRAM_CHAT_ID', '1')
    queries = []

    class DB:
        async def fetchval(self, sql, *a):
            queries.append(sql)
            return 10 if 'FROM signals' in sql and 'WHERE' not in sql else 0

        async def fetch(self, sql, *a):
            queries.append(sql)
            return [{'decision_source': 'policy_ready', 'claude_approved': None, 'n': 4},
                    {'decision_source': 'policy_auto', 'claude_approved': True, 'n': 5},
                    {'decision_source': 'claude', 'claude_approved': False, 'n': 1}]

    monkeypatch.setattr(tg, 'Database', DB())
    msg = Msg()
    update = SimpleNamespace(effective_chat=Chat(), effective_user=None, message=msg)
    await tg.cmd_performance(update, None)
    assert 'policy_ready' in msg.text and 'policy_auto' in msg.text
    assert 'مراجعة Claude قديمة — رفض: 1' in msg.text
    assert 'موافق عليها' not in msg.text
    assert not any('claude_approved = true' in q for q in queries)


@pytest.mark.asyncio
async def test_signals_screen_labels_policy_as_policy(monkeypatch):
    tg = load_telegram_main()
    monkeypatch.setattr(tg.config, 'TELEGRAM_CHAT_ID', '1')
    from datetime import datetime

    class DB:
        async def fetch(self, sql, *a):
            return [{'symbol': 'AUSDT', 'timeframe': '4h', 'score': 4,
                     'claude_approved': None, 'telegram_sent': True,
                     'signal_time': datetime(2026, 10, 1, 12, 0), 'claude_comment': None,
                     'decision_source': 'policy_ready', 'strategy_version': 'v'}]

    monkeypatch.setattr(tg, 'Database', DB())
    msg = Msg()
    await tg.cmd_signals(SimpleNamespace(effective_chat=Chat(), effective_user=None,
                                         message=msg), None)
    assert '✅' in msg.text and 'policy_ready' in msg.text and 'Claude' not in msg.text


# ------------------------------------------------- independence from claude_review ---
def test_active_path_runs_without_claude_review_or_anthropic():
    """Import the three active services with claude_review/anthropic import-blocked,
    ANTHROPIC_API_KEY unset and claude_review off sys.path."""
    code = r'''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in ('claude_review', 'anthropic'):
            raise ImportError('blocked: ' + name)
        return None
sys.meta_path.insert(0, Block())
sys.path[:] = [p for p in sys.path if 'claude_review' not in p]
sys.path.insert(0, 'tests')
import cr1_support
cr1_support.load_signal_logic(); cr1_support.load_tracker_main(); cr1_support.load_telegram_main()
import shared.signal_readiness
bad = [m for m in sys.modules if m.split('.')[0] in ('claude_review', 'anthropic')]
assert not bad, bad
print('ok')
'''
    env = {k: v for k, v in os.environ.items() if 'ANTHROPIC' not in k}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    out = subprocess.run([sys.executable, '-c', code], cwd=REPO, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().endswith('ok')


def test_active_sources_do_not_reference_claude_cli():
    for rel in ('signal_engine/signal_logic.py', 'telegram/main.py',
                'trade_tracker/main.py', 'shared/signal_readiness.py'):
        text = (REPO / rel).read_text(encoding='utf-8')
        assert not re.search(r'^\s*(from|import)\s+(claude_review|anthropic)\b', text, re.M), rel
        for needle in ('ANTHROPIC_API_KEY', 'CLAUDE_BIN', "'claude', '-p'"):
            assert needle not in text, (rel, needle)
