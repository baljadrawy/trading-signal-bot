"""P1-FIX: regression tests for the three P1-M evidence-quality findings.

MINOR-1  NO_FILL expiry starvation  -> keyset watermark (trade_tracker._v2_expiry_sweep)
MINOR-2  seen-before-queue          -> dedup state committed only after queue acceptance
MINOR-3  telegram evidence pre-ACK  -> completed-outcome evidence only after a successful ack

Unit tests need no database. The DB tests run only with P1R_TEST_DSN (THROWAWAY server).
"""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'signal_engine')
import asyncio
import datetime as dt

import pytest

from shared import evidence_v2 as ev2
from shared.config import config
from shared.database import Database
from evidence_v2_fakes import IDENT, inject_recorder
from cr1_support import load_telegram_main


@pytest.fixture(autouse=True)
def _reset():
    ev2.reset_for_tests()
    yield
    ev2.reset_for_tests()


# ================================================================ MINOR-2 ===========================
def test_accepted_event_commits_dedup_state(monkeypatch):
    rec, sink = inject_recorder(monkeypatch, 'svc')
    assert rec.emit('x', {'k': 1}, {}, state={'s': 1}, dedup_key='k1') is True
    assert ev2.is_recorded('svc', 'k1', {'s': 1})
    assert rec.emit('x', {'k': 1}, {}, state={'s': 1}, dedup_key='k1') is False   # dedup still works
    assert rec.suppressed == 1


def test_queue_full_drop_is_not_marked_seen_and_a_later_retry_succeeds(monkeypatch):
    rec, sink = inject_recorder(monkeypatch, 'svc', max_queue=1)
    assert rec.emit('filler', {}, {}) is True                                  # queue now full
    assert rec.emit('x', {'k': 1}, {}, state={'s': 1}, dedup_key='k1') is False
    assert rec.dropped == 1 and not ev2.is_recorded('svc', 'k1', {'s': 1})      # counted, not seen
    assert rec.health()['dropped'] == 1                                         # observable
    rec.flush_now()                                                             # queue drains
    assert rec.emit('x', {'k': 1}, {}, state={'s': 1}, dedup_key='k1') is True # retry succeeds
    assert ev2.is_recorded('svc', 'k1', {'s': 1})
    assert rec.emit('x', {'k': 1}, {}, state={'s': 1}, dedup_key='k1') is False # then dedups
    rec.flush_now()
    seqs = [r['seq'] for r in sink.records()]
    assert seqs == [1, 3]                                  # the dropped event left a visible seq gap


def test_serialization_failure_is_not_marked_seen(monkeypatch):
    rec, sink = inject_recorder(monkeypatch, 'svc')
    loop = {}
    loop['self'] = loop                                                         # unserializable
    assert rec.emit('x', {'k': 1}, {'bad': loop}, state={'s': 1}, dedup_key='k1') is False
    assert rec.errors == 1 and not ev2.is_recorded('svc', 'k1', {'s': 1})
    assert rec.emit('x', {'k': 1}, {'ok': 1}, state={'s': 1}, dedup_key='k1') is True


def test_is_recorded_is_false_when_disabled(monkeypatch):
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', False)
    assert ev2.is_recorded('trade_tracker', 'expiry:1', {'outcome_code': 'NO_FILL'}) is False


def test_queue_full_never_changes_the_selection(monkeypatch):
    from test_p1r_cr2_contract import _rows, _select
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', False)
    baseline = _select(monkeypatch, _rows())
    rec, _ = inject_recorder(monkeypatch, 'signal_engine', max_queue=1)
    rec.emit('filler', {}, {})
    assert _select(monkeypatch, _rows()) == baseline
    assert rec.dropped > 0


# ================================================================ MINOR-3 ===========================
class _Box:
    def __init__(self, ack_raises=False):
        self.calls, self.ack_raises = [], ack_raises

    async def ack(self, event_id, owner):
        self.calls.append(('ack', event_id))
        if self.ack_raises:
            raise ConnectionError('ack lost')

    async def fail(self, event_id, owner, err):
        self.calls.append(('fail', event_id, type(err).__name__))


def _handle(monkeypatch, tg, event_type, sig, allowed=(True, 'eligible'), ack_raises=False):
    box, sent = _Box(ack_raises), []

    async def fetchrow(sql, *a):
        return sig

    async def can_deliver():
        return allowed

    async def direct(bot, s):
        sent.append(s['id'])

    class Mgr:
        async def process_signal(self, s):
            return 'sent_direct'
    monkeypatch.setattr(Database, 'fetchrow', fetchrow)
    monkeypatch.setattr(tg, 'ack', box.ack)
    monkeypatch.setattr(tg, 'fail', box.fail)
    monkeypatch.setattr(tg, 'can_deliver_candidate', can_deliver)
    monkeypatch.setattr(tg, 'send_signal_direct', direct)
    monkeypatch.setattr(tg, 'DELIVERY_PACING_SECONDS', 0)
    out = asyncio.run(tg.handle_candidate_event(None, Mgr(), 'o', event_type,
                                                {'id': 91, 'aggregate_id': sig['id']}))
    return out, box.calls, sent


def _sig(**kw):
    s = {'id': 5, 'symbol': 'AUSDT', 'timeframe': '15m', 'telegram_sent': False,
         'decision_source': 'policy_ready', 'claude_approved': None}
    s.update(kw)
    return s


def _records(monkeypatch, fn):
    rec, sink = inject_recorder(monkeypatch, 'telegram')
    result = fn()
    rec.flush_now()
    return result, [(e['event_type'], e['payload'].get('outcome_code')) for e in sink.records()]


def test_ack_success_records_success_after_ack(monkeypatch):
    tg = load_telegram_main()
    (out, calls, sent), ev = _records(monkeypatch, lambda: _handle(monkeypatch, tg, 'signal.ready', _sig()))
    assert out is True and calls == [('ack', 91)] and sent == [5]
    assert ev == [('delivery.sent', 'DELIVERED')]


@pytest.mark.parametrize('case', ['sent', 'refused', 'skipped'])
def test_ack_failure_leaves_no_success_evidence_and_runtime_is_unchanged(case, monkeypatch):
    tg = load_telegram_main()
    sig = _sig(telegram_sent=True) if case == 'skipped' else _sig()
    allowed = (False, 'risk:loss_streak_halt') if case == 'refused' else (True, 'eligible')
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', False)
    off = _handle(monkeypatch, tg, 'signal.ready', sig, allowed, ack_raises=True)
    on, ev = _records(monkeypatch, lambda: _handle(monkeypatch, tg, 'signal.ready', sig, allowed,
                                                   ack_raises=True))
    assert on == off                                    # same return, same ack/fail calls, same sends
    assert on[1] == [('ack', 91), ('fail', 91, 'ConnectionError')]     # ack failure NOT swallowed
    assert on[2] == ([5] if case == 'sent' else [])     # no extra send caused by instrumentation
    assert ev == [('delivery.failed', 'DELIVERY_FAILED')]   # attempt record only, no false success


def test_retry_after_ack_failure_records_success_once(monkeypatch):
    tg = load_telegram_main()
    rec, sink = inject_recorder(monkeypatch, 'telegram')
    _handle(monkeypatch, tg, 'signal.ready', _sig(), ack_raises=True)    # first attempt: ack lost
    _handle(monkeypatch, tg, 'signal.ready', _sig())                     # outbox retry
    rec.flush_now()
    assert [e['event_type'] for e in sink.records()] == ['delivery.failed', 'delivery.sent']


def test_legacy_reviewed_path_unchanged(monkeypatch):
    tg = load_telegram_main()
    legacy = _sig(decision_source='policy_auto', claude_approved=True)
    (out, calls, sent), ev = _records(monkeypatch, lambda: _handle(monkeypatch, tg, 'signal.reviewed', legacy))
    assert out is True and calls == [('ack', 91)] and ev == [('delivery.sent', 'DELIVERED')]


# ================================================================ MINOR-1 ===========================
def test_expiry_sweep_off_is_inert(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location('tracker_p1fix_off', 'trade_tracker/main.py')
    tr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tr)
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', False)

    async def boom(*a, **k):
        raise AssertionError('SQL while OFF')
    monkeypatch.setattr(Database, 'fetch', boom)
    asyncio.run(tr._v2_expiry_sweep())
    assert tr._V2_EXPIRY_STATE == {}                     # no watermark state while OFF


_DB = pytest.mark.skipif(not __import__('os').getenv('P1R_TEST_DSN'),
                         reason='P1R_TEST_DSN not set (disposable PostgreSQL required)')
INSERT = ("INSERT INTO signals (symbol, timeframe, market_condition, entry_price, target_1, target_2, "
          "target_3, stop_loss, score, decision_source, strategy_version, trade_type, telegram_sent, "
          "signal_time) VALUES ($1,'4h','bullish',100,102,104,106,97,4,'policy_ready','v','reversion',"
          "true, NOW() - $2::interval) RETURNING id")


async def _trading_state(env):
    return (await env.pool.fetch("SELECT id, telegram_sent, decision_source, claude_approved, "
                                 "signal_time FROM signals ORDER BY id"),
            await env.val("SELECT count(*) FROM active_trades"),
            await env.pool.fetch("SELECT id, status, attempts FROM outbox_events ORDER BY id"))


@_DB
def test_more_than_200_expired_no_starvation_bounded_and_dedup(monkeypatch, tmp_path):
    from test_p1r_cr2_e2e import Env, BEFORE, modules

    async def go():
        async with Env('after', 'on', monkeypatch, tmp_path) as env:
            tr, rec = env.tr, ev2._RECORDERS['trade_tracker']
            rows_seen = []
            real_fetch = Database.fetch

            async def counting_fetch(sql, *a):
                out = await real_fetch(sql, *a)
                if sql == tr.V2_EXPIRED_SQL:
                    rows_seen.append(len(out))
                return out
            monkeypatch.setattr(Database, 'fetch', counting_fetch)
            ids = [await env.val(INSERT, f'O{i:03d}USDT', dt.timedelta(hours=3, minutes=i))
                   for i in range(250)]                               # 250 historical expiries
            before_state = await _trading_state(env)
            await tr._v2_expiry_sweep()
            rec.flush_now()
            first = {e['subject']['signal_id'] for e in env.sinks['trade_tracker'].records()
                     if e['event_type'] == 'entry.expired'}
            new_id = await env.val(INSERT, 'NEWUSDT', dt.timedelta(hours=2, minutes=1))   # just expired
            starved = None
            if BEFORE:                                                # the pre-fix query, same data
                old = modules('before')[2]
                got = await real_fetch(old.V2_EXPIRED_SQL, tr._V2_PROCESS_STARTED)
                starved = new_id not in {r['id'] for r in got}
            await tr._v2_expiry_sweep()
            await tr._v2_expiry_sweep()                               # nothing left: no re-emission
            rec.flush_now()
            events = [e for e in env.sinks['trade_tracker'].records() if e['event_type'] == 'entry.expired']
            after_state = await _trading_state(env)
            return ids, new_id, first, events, rows_seen, before_state, after_state, starved
    ids, new_id, first, events, rows_seen, before, after, starved = asyncio.run(go())
    assert len(first) == 200                                          # bounded first page
    got = [e['subject']['signal_id'] for e in events]
    assert sorted(got) == sorted(ids + [new_id])                      # every expiry, incl. the new one
    assert len(got) == len(set(got))                                  # each exactly once
    assert all(e['payload']['outcome_code'] == 'EXPIRED_UNOBSERVED' for e in events)
    assert max(rows_seen) <= 200 and rows_seen == [200, 51, 0]        # bounded work per sweep
    assert [dict(r) for r in before[0]] == [dict(r) for r in after[0][:250]]   # untouched (+1 inserted)
    assert before[1] == after[1] == 0 and [dict(r) for r in before[2]] == [dict(r) for r in after[2]]
    if starved is not None:
        assert starved is True                                        # the old query would starve it
    ev2.reset_for_tests()


@_DB
def test_no_fill_expiry_retried_after_queue_full_and_recorded_once(monkeypatch, tmp_path):
    from test_p1r_cr2_e2e import Env

    async def go():
        async with Env('after', 'on', monkeypatch, tmp_path) as env:
            tr, rec = env.tr, ev2._RECORDERS['trade_tracker']
            ids = [await env.val(INSERT, f'Q{i}USDT', dt.timedelta(hours=3, minutes=i)) for i in range(6)]
            for i in ids:
                tr._v2_note_outcome(i, 'AWAITING_FILL')               # observed limit waits
            rec.max_queue = 3
            await tr._v2_expiry_sweep()                                # 3 accepted, then a drop
            dropped_once = rec.dropped
            wm = tr._V2_EXPIRY_STATE['watermark']
            rec.flush_now()
            await tr._v2_expiry_sweep()                                # retry from the watermark
            rec.flush_now()
            await tr._v2_expiry_sweep()
            rec.flush_now()
            ev = [e for e in env.sinks['trade_tracker'].records() if e['event_type'] == 'entry.expired']
            return ids, ev, dropped_once, wm
    ids, ev, dropped_once, wm = asyncio.run(go())
    assert dropped_once >= 1
    assert sorted(e['subject']['signal_id'] for e in ev) == sorted(ids)   # nothing lost, none twice
    assert all(e['payload']['outcome_code'] == 'NO_FILL' for e in ev)
    assert wm[1] == ids[3]          # oldest-first order is ids[5], ids[4], ids[3]: stopped before the drop
    ev2.reset_for_tests()


@_DB
@pytest.mark.parametrize('scenario', ['ready_opened', 'no_fill', 'b3_blocked'])
def test_queue_full_decision_parity_db(scenario, monkeypatch, tmp_path):
    from test_p1r_cr2_e2e import Env, SCENARIOS

    async def run(mode, tiny):
        async with Env('after', mode, monkeypatch, tmp_path / f'{mode}{tiny}') as env:
            if tiny:
                for r in ev2._RECORDERS.values():
                    r.max_queue = 1
            await SCENARIOS[scenario][0](env)
            return await env.snapshot()
    off = asyncio.run(run('off', False))
    assert asyncio.run(run('on', True)) == off
    ev2.reset_for_tests()


@_DB
def test_non_retryable_expiry_failure_does_not_block_later_expiries(monkeypatch, tmp_path):
    """A row whose evidence can never be recorded (non-queue failure) is counted and skipped;
    the watermark keeps moving, so later expiries are still observed (forward progress)."""
    from test_p1r_cr2_e2e import Env

    async def go():
        async with Env('after', 'on', monkeypatch, tmp_path) as env:
            tr, rec = env.tr, ev2._RECORDERS['trade_tracker']
            ids = [await env.val(INSERT, f'P{i}USDT', dt.timedelta(hours=3, minutes=i)) for i in range(4)]
            poison = ids[2]
            real_emit = rec.emit

            def emit(event_type, subject, payload=None, **kw):
                if subject.get('signal_id') == poison:
                    rec.errors += 1                    # simulate a persistent serialization failure
                    return False
                return real_emit(event_type, subject, payload, **kw)
            monkeypatch.setattr(rec, 'emit', emit)
            await tr._v2_expiry_sweep()
            await tr._v2_expiry_sweep()
            rec.flush_now()
            ev = [e['subject']['signal_id'] for e in env.sinks['trade_tracker'].records()
                  if e['event_type'] == 'entry.expired']
            return ids, poison, ev, rec.errors
    ids, poison, ev, errors = asyncio.run(go())
    assert sorted(ev) == sorted(i for i in ids if i != poison) and errors >= 1
    ev2.reset_for_tests()
