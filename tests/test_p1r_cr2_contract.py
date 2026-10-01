"""P1-R: forward instrumentation adapted to the CR-2 contract (signal.ready / policy_ready).

Unit level, no database: outcome vocabulary, agreement with the readiness gate, the admission
window, strict OFF semantics (no recorder, no files, no extra DB access, no P1 persistence), and
recorder failures that never change a decision. The DB-backed flow is tests/test_p1r_cr2_e2e.py.
"""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'signal_engine'); sys.path.insert(0, 'trade_tracker')
import asyncio
import copy
import importlib.util
import inspect
import json

import pytest

from shared import evidence_v2 as ev2
from shared.config import config
from shared.database import Database
from shared.signal_readiness import is_deliverable_for_event
from evidence_v2_fakes import IDENT, FakeMacro, analysis_row, inject_recorder
from cr1_support import load_telegram_main


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def tracker():
    return _load('tracker_p1r_unit', 'trade_tracker/main.py')


@pytest.fixture(autouse=True)
def _reset():
    ev2.reset_for_tests()
    yield
    ev2.reset_for_tests()


# ---------------------------------------------------------------- vocabulary --------------------
def test_classifiers_only_return_known_codes():
    codes = set(ev2.OUTCOME_CODES)
    reasons = ['risk:loss_streak_halt', 'loss_streak_halt', 'manual_pause', 'إيقاف يدوي',
               'risk_state_missing', 'risk_state_inconsistent', 'trading_paused',
               'portfolio_capacity_2/2', 'max_open_trades', 'daily_loss_limit',
               'risk:daily_loss_limit', 'gross_exposure_limit', None, '']
    for r in reasons:
        assert ev2.pause_outcome_code(r) in codes
        assert ev2.risk_outcome_code(r) in codes
    for o in ('admitted', 'no_price', 'bracket_invalid', 'already_registered',
              'halt_under_admission_lock', 'risk_rejected', 'something_new'):
        assert ev2.admission_outcome_code(o, 'loss_streak_halt') in codes
    for a in ('market', 'limit_wait', 'reject', None, 'weird'):
        assert ev2.entry_outcome_code(a) in codes
    for last in (None, 'AWAITING_FILL', 'B3_BLOCKED', 'CAPACITY'):
        assert ev2.expiry_outcome_code(last) in codes


def test_b3_pause_capacity_and_risk_mapping():
    assert ev2.pause_outcome_code('risk:loss_streak_halt') == 'B3_BLOCKED'
    assert ev2.pause_outcome_code('manual_pause') == 'PAUSED'
    assert ev2.pause_outcome_code('إيقاف يدوي') == 'PAUSED'
    assert ev2.pause_outcome_code('risk_state_missing') == 'PAUSED'        # fail-closed state
    assert ev2.pause_outcome_code('portfolio_capacity_1/1') == 'CAPACITY'
    assert ev2.risk_outcome_code('loss_streak_halt') == 'B3_BLOCKED'
    assert ev2.risk_outcome_code('risk:loss_streak_halt') == 'B3_BLOCKED'  # pause reason passed through
    assert ev2.risk_outcome_code('manual_pause') == 'PAUSED'
    assert ev2.risk_outcome_code('max_open_trades') == 'CAPACITY'
    assert ev2.risk_outcome_code('daily_loss_limit') == 'RISK_REJECTED'
    assert ev2.admission_outcome_code('risk_rejected', 'loss_streak_halt') == 'B3_BLOCKED'
    assert ev2.admission_outcome_code('halt_under_admission_lock') == 'B3_BLOCKED'
    assert ev2.admission_outcome_code('admitted') == 'OPENED'
    assert ev2.admission_outcome_code('already_registered') == 'DUPLICATE'
    assert ev2.entry_outcome_code('limit_wait') == 'AWAITING_FILL'
    assert ev2.entry_outcome_code('market') == 'ENTRY_MARKET'               # not yet admitted
    assert ev2.expiry_outcome_code('AWAITING_FILL') == 'NO_FILL'
    assert ev2.expiry_outcome_code('B3_BLOCKED') == 'EXPIRED'
    assert ev2.expiry_outcome_code(None) == 'EXPIRED_UNOBSERVED'


def _signal(**kw):
    base = {'id': 1, 'symbol': 'AUSDT', 'timeframe': '15m', 'telegram_sent': False,
            'decision_source': 'policy_ready', 'claude_approved': None}
    base.update(kw)
    return base


@pytest.mark.parametrize('event_type', ['signal.ready', 'signal.reviewed', 'signal.created'])
@pytest.mark.parametrize('sig', [
    None,
    _signal(),
    _signal(telegram_sent=True),
    _signal(decision_source='signal_engine'),
    _signal(decision_source='policy_auto', claude_approved=True),
    _signal(decision_source='policy_auto', claude_approved=False),
    _signal(decision_source=None, claude_approved=None),
])
def test_skip_classification_agrees_with_readiness_gate(event_type, sig):
    """Every candidate the CR-1 gate refuses gets a reason/code; the codes match the gate's logic."""
    if is_deliverable_for_event(event_type, sig):
        return                                  # delivered path, not a skip
    reason, code = ev2.candidate_skip(event_type, sig)
    assert code in ev2.OUTCOME_CODES
    if sig is None:
        assert (reason, code) == ('signal_missing', 'SIGNAL_MISSING')
    elif sig['telegram_sent']:
        assert (reason, code) == ('already_sent', 'DUPLICATE')
    else:
        assert code == 'NOT_READY'


def test_admission_window_matches_production_queries(tracker):
    """The NO_FILL window and the terminal classifier use exactly the tracker's admission window."""
    src = inspect.getsource(tracker.register_new_signals)
    assert f"s.signal_time > NOW() - {tracker.V2_ADMISSION_WINDOW_SQL}" in src
    assert f"NOW()-{tracker.V2_ADMISSION_WINDOW_SQL}" in tracker.DELIVERY_TERMINAL_SQL
    # the classifier names the same five terminal conditions as DELIVERY_TERMINAL_SQL
    for cond in ('NOT s.telegram_sent', 'symbol_blacklist', "ar.status='rejected'"):
        assert cond in tracker.DELIVERY_TERMINAL_SQL and cond in tracker.DELIVERY_OUTCOME_SQL


# ---------------------------------------------------------------- OFF semantics -------------------
def _db_tripwire(monkeypatch):
    calls = []

    async def boom(*a, **k):
        calls.append(a[:1])
        raise AssertionError('instrumentation touched the database while OFF')
    for name in ('fetch', 'fetchrow', 'fetchval', 'execute'):
        monkeypatch.setattr(Database, name, boom)
    return calls


def test_off_hooks_do_nothing_and_touch_no_database(monkeypatch, tmp_path, tracker):
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', False)
    monkeypatch.setattr(config, 'EVIDENCE_V2_DIR', str(tmp_path / 'ev2'))
    calls = _db_tripwire(monkeypatch)
    memory_before = dict(tracker._V2_LAST_OUTCOME)
    event = {'id': 5, 'aggregate_id': 9, 'attempts': 8, 'max_attempts': 8}
    asyncio.run(tracker._v2_delivery_consumed(event, 'deferred'))
    asyncio.run(tracker._v2_delivery_consumed(event, 'terminal'))
    asyncio.run(tracker._v2_expiry_sweep())
    tracker._v2_admission({'id': 9, 'symbol': 'A', 'timeframe': '15m'}, 'admitted')
    tg = load_telegram_main()
    tg._v2_delivery('delivery.refused', _signal(), 'refused', 'risk:loss_streak_halt', 1, 'signal.ready')
    import signal_logic
    signal_logic._v2_signal_refused({'symbol': 'A'}, ValueError('x'))
    assert calls == []
    assert ev2.get_recorder('trade_tracker') is None and ev2._RECORDERS == {}
    assert ev2.health('trade_tracker') is None             # heartbeat metadata unchanged
    assert not (tmp_path / 'ev2').exists()                 # no evidence directory, no files
    assert dict(tracker._V2_LAST_OUTCOME) == memory_before          # no outcome memory while OFF


def test_off_mode_writes_no_evidence_files_during_selection(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', False)
    monkeypatch.setattr(config, 'EVIDENCE_V2_DIR', str(tmp_path / 'ev2'))
    best, _ = _select(monkeypatch, _rows())
    assert best is not None
    assert not (tmp_path / 'ev2').exists() and ev2._RECORDERS == {}


# ---------------------------------------------------------------- recorder reliability ------------
def _rows():
    return [analysis_row('AAAUSDT'), analysis_row('BBBUSDT', spread=5.0),
            analysis_row('CCCUSDT', stop_valid=False), analysis_row('DDDUSDT', trade_type=None),
            analysis_row('EEEUSDT', timeframe='4h', entry=50.0)]


def _select(monkeypatch, rows):
    import signal_logic

    async def fake_fetch(sql, *a):
        return []
    monkeypatch.setattr(Database, 'fetch', fake_fetch)
    monkeypatch.setattr(config, 'LEARNING_GATES_ENABLED', False)
    monkeypatch.setattr(config, 'ENABLE_EVIDENCE_RECORDER', False)
    engine = signal_logic.SignalEngine()

    async def cooldown():
        return set()

    async def volume(symbol):
        return {'AAAUSDT': 2e6, 'EEEUSDT': 3e6}.get(symbol, 1e6)
    monkeypatch.setattr(engine, '_get_symbol_cooldown_set', cooldown)
    monkeypatch.setattr(engine, '_get_volume_usdt', volume)
    best = asyncio.run(engine.find_best_signal_live(copy.deepcopy(rows), FakeMacro()))
    if best:
        best = {k: v for k, v in best.items() if k != 'pit'}
    return json.loads(json.dumps(best, sort_keys=True, default=str)), dict(engine.last_decisions)


class _RaisingRecorder(ev2.RecorderV2):
    def emit(self, *a, **k):
        raise RuntimeError('recorder exploded')


class _FailingSink(ev2.ListSink):
    def write(self, batch):
        raise OSError('No space left on device')


@pytest.mark.parametrize('failure', ['raising_emit', 'unwritable_sink', 'malformed_payload',
                                     'hook_exception', 'duplicate_events'])
def test_recorder_failures_never_change_the_decision(failure, monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', False)
    baseline = _select(monkeypatch, _rows())
    rec, sink = inject_recorder(monkeypatch, 'signal_engine')
    rows = _rows()
    if failure == 'raising_emit':
        ev2._RECORDERS['signal_engine'] = _RaisingRecorder('signal_engine', ev2.ListSink(), IDENT)
    elif failure == 'unwritable_sink':
        rec.sink = _FailingSink()
    elif failure == 'malformed_payload':
        loop = {}
        loop['self'] = loop                                  # not serializable (circular)
        rows[0]['analysis_data']['pit']['debug'] = loop
    elif failure == 'hook_exception':
        def bad(*a, **k):
            raise ValueError('hook bug')
        monkeypatch.setattr(ev2, 'emit', bad)
    after = _select(monkeypatch, rows)
    if failure == 'duplicate_events':
        again = _select(monkeypatch, _rows())                # identical re-evaluation
        assert again == baseline
        rec.flush_now()
        assert rec.stats()['suppressed_repeats'] > 0         # duplicates suppressed, not re-emitted
    assert after == baseline
    if failure == 'unwritable_sink':
        assert rec.flush_now() == 0 and rec.stats()['flush_failures'] >= 1
        assert rec.health()['queue_depth'] > 0               # failure observable, events retained
    if failure == 'malformed_payload':
        assert rec.stats()['errors'] >= 1 and rec.stats()['last_error']


# ---------------------------------------------------------------- telegram CR-2 path --------------
class _FakeOutbox:
    def __init__(self):
        self.calls = []

    async def ack(self, event_id, owner):
        self.calls.append(('ack', event_id))

    async def fail(self, event_id, owner, err):
        self.calls.append(('fail', event_id, str(err)))


def _run_candidate(monkeypatch, tg, event_type, sig, allowed=(True, 'eligible')):
    box = _FakeOutbox()
    sent = []

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
    delivered = asyncio.run(tg.handle_candidate_event(None, Mgr(), 'o', event_type,
                                                      {'id': 77, 'aggregate_id': (sig or {}).get('id', 9)}))
    return delivered, box.calls, sent


CASES = [
    ('signal.ready', _signal(), (True, 'eligible'), 'delivery.sent', 'DELIVERED'),
    ('signal.ready', _signal(), (False, 'risk:loss_streak_halt'), 'delivery.refused', 'B3_BLOCKED'),
    ('signal.ready', _signal(), (False, 'manual_pause'), 'delivery.refused', 'PAUSED'),
    ('signal.ready', _signal(), (False, 'portfolio_capacity_1/1'), 'delivery.refused', 'CAPACITY'),
    ('signal.ready', _signal(decision_source='signal_engine'), None, 'delivery.skipped', 'NOT_READY'),
    ('signal.ready', _signal(telegram_sent=True), None, 'delivery.skipped', 'DUPLICATE'),
    ('signal.reviewed', _signal(decision_source='policy_auto', claude_approved=True), (True, 'eligible'),
     'delivery.sent', 'DELIVERED'),                                    # legacy rollback path
    ('signal.reviewed', _signal(), None, 'delivery.skipped', 'NOT_READY'),
]


@pytest.mark.parametrize('event_type,sig,allowed,etype,code', CASES)
def test_telegram_candidate_path_records_outcome_and_is_unchanged(event_type, sig, allowed, etype,
                                                                  code, monkeypatch):
    tg = load_telegram_main()
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', False)
    off = _run_candidate(monkeypatch, tg, event_type, sig, allowed or (True, 'eligible'))
    rec, sink = inject_recorder(monkeypatch, 'telegram')
    on = _run_candidate(monkeypatch, tg, event_type, sig, allowed or (True, 'eligible'))
    assert on == off                                     # same delivery, same ack/fail sequence
    rec.flush_now()
    [event] = sink.records()
    assert event['event_type'] == etype
    assert event['payload']['outcome_code'] == code
    assert event['payload']['claimed_event_type'] == event_type
    assert event['subject']['signal_id'] == sig['id']
