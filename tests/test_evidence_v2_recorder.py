"""Evidence recorder v2 (P1): identities, schema, idempotency, failure and saturation behaviour."""
import sys; sys.path.insert(0, '.')
import asyncio
import json
import threading
import time
from dataclasses import dataclass

from shared import evidence_v2 as ev2
from shared.evidence_v2 import ListSink, RecorderV2

IDENT = {'strategy_version': 'sb-test', 'code_sha': 'c' * 64, 'config_hash': 'h' * 64,
         'build_revision': 'unknown', 'phase_id': None}


def make(**kw):
    sink = kw.pop('sink', None) or ListSink()
    return RecorderV2('svc', sink, IDENT, **kw), sink


# ---------------------------------------------------------------- identities (P1-A) --------
def test_candle_and_candidate_ids_are_deterministic_and_discriminating():
    c1 = ev2.candle_id('BTCUSDT', '15m', 1700000100000)
    assert c1 == 'BTCUSDT|15m|1700000100000'
    a = ev2.candidate_id(c1, 'momentum', 'sb-1')
    assert a == ev2.candidate_id(c1, 'momentum', 'sb-1') and a.startswith('cand_') and len(a) == 29
    assert ev2.candidate_id(c1, 'reversion', 'sb-1') != a                 # other setup
    assert ev2.candidate_id(ev2.candle_id('BTCUSDT', '15m', 1700001000000), 'momentum', 'sb-1') != a
    assert ev2.candidate_id(c1, 'momentum', 'sb-2') != a                  # other strategy version
    assert ev2.candle_id('BTCUSDT', '15m', None) is None
    assert ev2.candidate_id(None, 'momentum', 'sb-1') is None


def test_event_id_ignores_dict_key_order():
    assert (ev2.event_id('s', 't', {'a': 1, 'b': 2}, {'x': 1})
            == ev2.event_id('s', 't', {'b': 2, 'a': 1}, {'x': 1}))


def test_config_hash_excludes_secrets_process_fields_and_recorder_settings():
    @dataclass
    class C:
        APP_VERSION: str = 'v'
        MAX_SPREAD_PCT: float = 0.15
        BINANCE_API_KEY: str = 'k1'
        POSTGRES_PASSWORD: str = 'p1'
        TELEGRAM_CHAT_ID: str = '1'
        EVIDENCE_V2_ENABLED: bool = False
        SERVICE_NAME: str = 'a'
    base = ev2.compute_config_hash(C())
    assert ev2.compute_config_hash(C(BINANCE_API_KEY='k2', POSTGRES_PASSWORD='p2', TELEGRAM_CHAT_ID='2',
                                     EVIDENCE_V2_ENABLED=True, SERVICE_NAME='b')) == base
    assert ev2.compute_config_hash(C(MAX_SPREAD_PCT=0.2)) != base
    assert set(ev2.strategy_config_snapshot(C())) == {'APP_VERSION', 'MAX_SPREAD_PCT'}


def test_real_config_snapshot_contains_no_secret_like_field():
    from shared.config import config
    snap = ev2.strategy_config_snapshot(config)
    assert 'APP_VERSION' in snap and 'MAX_SPREAD_PCT' in snap
    assert not [k for k in snap if ev2._SECRET_NAME_RE.search(k)]
    assert not [k for k in snap if k.startswith('EVIDENCE') or k == 'ENABLE_EVIDENCE_RECORDER']


def test_code_sha_is_stable_content_sensitive_and_ignores_mounted_dirs(tmp_path):
    (tmp_path / 'a.py').write_text('x = 1\n')
    (tmp_path / 'logs').mkdir()
    (tmp_path / 'logs' / 'b.py').write_text('ignored')
    first = ev2.compute_code_sha(str(tmp_path))
    ev2._CODE_SHA_CACHE.clear()
    (tmp_path / 'logs' / 'b.py').write_text('changed')
    assert ev2.compute_code_sha(str(tmp_path)) == first
    ev2._CODE_SHA_CACHE.clear()
    (tmp_path / 'a.py').write_text('x = 2\n')
    assert ev2.compute_code_sha(str(tmp_path)) != first
    ev2._CODE_SHA_CACHE.clear()


# ---------------------------------------------------------------- schema ------------------
def test_envelope_has_all_schema_fields_and_utc_millisecond_times():
    rec, sink = make()
    t0 = ev2.now_ms()
    assert rec.emit('candidate.evaluated', {'candidate_id': 'cand_x'}, {'k': 1},
                    state={'decision': 'rejected'}, dedup_key='k')
    rec.flush_now()
    [e] = sink.records()
    for field in ('schema', 'schema_version', 'event_id', 'event_type', 'service', 'boot_id', 'seq',
                  'event_time_ms', 'recorded_at_ms', 'restated', 'strategy_version', 'code_sha',
                  'config_hash', 'build_revision', 'phase_id', 'subject', 'state', 'payload'):
        assert field in e, field
    assert (e['schema'], e['schema_version'], e['seq']) == ('tsb.evidence', 2, 1)
    assert t0 <= e['recorded_at_ms'] <= ev2.now_ms() and isinstance(e['event_time_ms'], int)
    assert ev2.ms_to_iso(0) == '1970-01-01T00:00:00.000Z'
    assert ev2.to_ms(ev2._dt.datetime(1970, 1, 1, 0, 0, 1)) == 1000       # naive = UTC


# ---------------------------------------------------------------- state change / idempotency
def test_repeated_identical_decision_is_suppressed_and_counted():
    rec, sink = make()
    for i in range(5):
        rec.emit('candidate.evaluated', {'candidate_id': 'c1'}, {'n': i},
                 state={'d': 'rejected', 'r': 'spread'}, dedup_key='c1')
    rec.emit('candidate.evaluated', {'candidate_id': 'c1'}, {}, state={'d': 'selected'}, dedup_key='c1')
    rec.flush_now()
    events = sink.records()
    assert [e['state']['d'] for e in events] == ['rejected', 'selected']
    assert rec.suppressed == 4
    assert events[0]['restated'] is True and events[1]['restated'] is False


def test_same_fact_keeps_its_event_id_across_restarts():
    (r1, s1), (r2, s2) = make(), make()
    for rec in (r1, r2):
        rec.emit('trade.closed', {'active_trade_id': 7}, {'x': 1})
        rec.flush_now()
    a, b = s1.records()[0], s2.records()[0]
    assert a['event_id'] == b['event_id'] and a['boot_id'] != b['boot_id']


def test_transition_events_get_distinct_ids_when_a_state_recurs():
    rec, sink = make()
    for t, st in ((1000, 'a'), (2000, 'b'), (3000, 'a')):
        rec.emit('cycle.outcome', {'stream': 'c'}, {}, state={'o': st}, dedup_key='cycle',
                 transition=True, event_time_ms=t)
    rec.flush_now()
    ids = [e['event_id'] for e in sink.records()]
    assert len(ids) == 3 and len(set(ids)) == 3


def test_payload_is_frozen_at_emit_time():
    rec, sink = make()
    payload = {'price': 1.0, 'nested': {'a': 1}}
    rec.emit('x', {'id': 1}, payload)
    payload['price'] = 99.0
    payload['nested']['a'] = 99
    rec.flush_now()
    assert sink.records()[0]['payload'] == {'price': 1.0, 'nested': {'a': 1}}


def test_emit_never_raises_and_counts_bad_input():
    rec, _ = make()

    class Bad:
        def __str__(self):
            raise RuntimeError('boom')
    assert rec.emit('x', {'id': object()}, {'v': float('nan')}) is True
    assert rec.emit('x', {'id': 2}, {'bad': Bad()}) is False
    assert rec.errors == 1 and 'boom' in rec.last_error


def test_disabled_recorder_is_a_noop():
    rec, sink = make(enabled=False)
    assert rec.emit('x', {}, {}) is False
    rec.flush_now()
    assert sink.lines == [] and rec.stats()['emitted'] == 0


# ---------------------------------------------------------------- failure and saturation --
class FailingSink:
    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.lines = []

    def write(self, batch):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise OSError(28, 'No space left on device')
        self.lines.extend(line for _, line in batch)


def test_sink_failure_keeps_events_queued_visible_and_then_recovers_in_order():
    sink = FailingSink(fail_times=100)
    rec = RecorderV2('svc', sink, IDENT, flush_retry_count=1, flush_backoff_ms=0)
    for i in range(10):
        rec.emit('x', {'i': i}, {})
    assert rec.flush_now() == 0
    st = rec.stats()
    assert st['queue_depth'] == 10 and st['flush_failures'] == 2 and st['last_flush_ok_at'] is None
    assert 'No space left' in st['last_error'] and st['last_error_at']
    sink.fail_times = 0
    assert rec.flush_now() == 10
    assert rec.stats()['queue_depth'] == 0 and rec.stats()['last_flush_ok_at']
    assert [json.loads(line)['subject']['i'] for line in sink.lines] == list(range(10))


def test_queue_saturation_is_counted_and_leaves_detectable_sequence_gaps():
    rec, sink = make(max_queue=5)
    for i in range(12):
        rec.emit('x', {'i': i}, {})
    st = rec.stats()
    assert (st['dropped'], st['queue_depth'], st['max_depth_seen'], st['seq']) == (7, 5, 5, 12)
    rec.flush_now()
    assert [e['seq'] for e in sink.records()] == [1, 2, 3, 4, 5]


def test_state_cache_is_bounded():
    rec, _ = make(state_cache_size=3)
    for i in range(10):
        rec.emit('x', {'i': i}, {}, state={'s': 1}, dedup_key=f'k{i}')
    assert rec.stats()['state_keys'] == 3 and rec.state_evictions == 7


def test_unwritable_directory_is_counted_not_raised(tmp_path):
    ro = tmp_path / 'ro'
    ro.mkdir()
    ro.chmod(0o500)
    rec = RecorderV2('svc', ev2.JsonlDailySink(str(ro), 'svc'), IDENT, flush_retry_count=0)
    rec.emit('x', {}, {})
    assert rec.flush_now() == 0
    assert rec.stats()['flush_failures'] == 1 and 'Permission' in rec.stats()['last_error']


def test_unwritable_destination_independent_of_uid(tmp_path):
    """P1-R: the destination cannot be created even by root (its parent is a regular file):
    the failure is counted and visible, the event stays queued, nothing is raised."""
    blocker = tmp_path / 'not_a_dir'
    blocker.write_text('x')
    rec = RecorderV2('svc', ev2.JsonlDailySink(str(blocker / 'evidence'), 'svc'), IDENT,
                     flush_retry_count=0)
    assert rec.emit('x', {}, {}) is True
    assert rec.flush_now() == 0
    st = rec.stats()
    assert st['flush_failures'] == 1 and st['queue_depth'] == 1 and st['last_error']
    assert rec.health()['flush_failures'] == 1


def test_async_flusher_persists_everything_and_publishes_stats(tmp_path):
    rec = RecorderV2('svc', ev2.JsonlDailySink(str(tmp_path), 'svc'), IDENT,
                     flush_interval_s=0.05, stats_interval_s=0)

    async def go():
        task = asyncio.get_running_loop().create_task(rec.run_flusher())
        for i in range(50):
            rec.emit('x', {'i': i}, {})
        await asyncio.sleep(0.4)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    asyncio.run(go())
    [path] = list((tmp_path / 'svc').glob('events-*.jsonl'))
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert {e['subject'].get('i') for e in events if e['event_type'] == 'x'} == set(range(50))
    assert any(e['event_type'] == 'recorder.stats' for e in events)
    stats = json.loads((tmp_path / 'svc' / '_recorder_stats.json').read_text())
    assert stats['queue_depth'] == 0 and stats['flushed'] >= 50


def test_flush_runs_off_the_event_loop():
    class SlowSink:
        def __init__(self):
            self.batches = []

        def write(self, batch):
            time.sleep(0.3)
            self.batches.append(batch)
    rec = RecorderV2('svc', SlowSink(), IDENT)
    for i in range(3):
        rec.emit('x', {'i': i}, {})

    async def go():
        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(20):
                await asyncio.sleep(0.01)
                ticks += 1
        await asyncio.gather(rec.flush_async(), ticker())
        return ticks
    assert asyncio.run(go()) == 20


def test_concurrent_emit_during_threaded_flush_loses_nothing():
    class SlowSink:
        def __init__(self):
            self.lines = []

        def write(self, batch):
            for _, line in batch:
                time.sleep(0.0005)
                self.lines.append(line)
    sink = SlowSink()
    rec = RecorderV2('svc', sink, IDENT, batch_size=50, max_queue=100000)
    stop = threading.Event()

    def flusher():
        while not stop.is_set() or rec.stats()['queue_depth']:
            rec.flush_now()
    t = threading.Thread(target=flusher)
    t.start()
    for i in range(3000):
        rec.emit('x', {'i': i}, {})
    stop.set()
    t.join(timeout=30)
    assert not t.is_alive()
    seen = [json.loads(line)['subject']['i'] for line in sink.lines]
    assert seen == list(range(3000)) and rec.errors == 0


# ---------------------------------------------------------------- process singleton -------
def test_module_api_is_a_noop_when_disabled(monkeypatch):
    from shared.config import config
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', False)
    ev2.reset_for_tests()
    assert ev2.emit('svc', 'x', {}) is False
    assert ev2.health('svc') is None and ev2.get_recorder('svc') is None


def test_module_init_failure_is_visible_and_not_fatal(monkeypatch, tmp_path):
    from shared.config import config
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', True)
    monkeypatch.setattr(config, 'EVIDENCE_V2_DIR', str(tmp_path))
    monkeypatch.setattr(config, 'EVIDENCE_V2_MAX_QUEUE', 'not-a-number')
    ev2.reset_for_tests()
    try:
        assert ev2.emit('svc', 'x', {}) is False
        assert 'init_error' in ev2.health('svc')
    finally:
        ev2.reset_for_tests()


def test_module_recorder_writes_started_event_and_health(monkeypatch, tmp_path):
    from shared.config import config
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', True)
    monkeypatch.setattr(config, 'EVIDENCE_V2_DIR', str(tmp_path))
    ev2.reset_for_tests()
    try:
        assert ev2.emit('svc', 'x', {'a': 1}, {'b': 2})
        ev2.get_recorder('svc').flush_now()
        [path] = list((tmp_path / 'svc').glob('events-*.jsonl'))
        types = [json.loads(line)['event_type'] for line in path.read_text().splitlines()]
        assert types == ['recorder.started', 'x']
        started = json.loads(path.read_text().splitlines()[0])
        assert 'BINANCE_API_KEY' not in json.dumps(started)
        assert set(ev2.health('svc')) == {'queue_depth', 'dropped', 'errors', 'hook_errors',
                                          'flush_failures', 'last_flush_ok_at', 'last_error', 'seq'}
    finally:
        ev2.reset_for_tests()
