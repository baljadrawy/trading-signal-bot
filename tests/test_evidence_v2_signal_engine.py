"""Signal-engine instrumentation (P1-B): decision parity under every recorder mode, and the
content of the candidate/selection events. Synthetic inputs only."""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'signal_engine')
import asyncio
import copy
import json
import random

import pytest

import signal_logic
from shared import evidence_v2 as ev2
from shared.config import config
from shared.database import Database
from evidence_v2_fakes import FakeMacro, analysis_row, inject_recorder

SYMBOLS = [f"S{i:02d}USDT" for i in range(12)]


def scenario(seed):
    rng = random.Random(seed)
    rows = []
    for _ in range(rng.randint(0, 30)):
        tt = rng.choice([None, 'momentum', 'reversion', 'momentum'])
        rows.append(analysis_row(
            rng.choice(SYMBOLS), rng.choice(['15m', '4h', '1d']), tt,
            spread=rng.choice([None, round(rng.uniform(0, 0.4), 4)]),
            valid=rng.random() > 0.1, stop_valid=rng.choice([True, True, False, None]),
            entry=round(rng.uniform(0.5, 50), 4)))
    return {
        'rows': rows,
        'open': set(rng.sample(SYMBOLS, rng.randint(0, 3))),
        'cooldown': set(rng.sample(SYMBOLS, rng.randint(0, 3))),
        'blocked': rng.random() < 0.1,
        'gates': rng.random() < 0.3,
        'throttled': [{'trade_type': rng.choice(['momentum', 'reversion']),
                       'timeframe': rng.choice(['15m', '4h', '1d'])} for _ in range(rng.randint(0, 2))],
        'volume': {s: rng.uniform(1e5, 1e7) for s in SYMBOLS},
    }


def run(sc, monkeypatch):
    async def fake_fetch(sql, *args):
        if 'learned_gates' in sql:
            return sc['throttled']
        if 'active_trades' in sql:
            return [{'symbol': s} for s in sorted(sc['open'])]
        return []
    monkeypatch.setattr(Database, 'fetch', fake_fetch)
    monkeypatch.setattr(config, 'LEARNING_GATES_ENABLED', sc['gates'])
    engine = signal_logic.SignalEngine()

    async def cooldown():
        return set(sc['cooldown'])

    async def volume(symbol):
        return sc['volume'][symbol]
    monkeypatch.setattr(engine, '_get_symbol_cooldown_set', cooldown)
    monkeypatch.setattr(engine, '_get_volume_usdt', volume)
    rows = copy.deepcopy(sc['rows'])
    before = copy.deepcopy(rows)
    best = asyncio.run(engine.find_best_signal_live(rows, FakeMacro(blocked=sc['blocked'])))
    assert rows == before, 'instrumentation must not mutate the decision input'
    return json.loads(json.dumps({'best': best, 'decisions': engine.last_decisions},
                                 sort_keys=True, default=str))


class RaisingRecorder(ev2.RecorderV2):
    def emit(self, *a, **k):
        raise RuntimeError('recorder exploded')


@pytest.mark.parametrize('seed', range(300))
def test_decisions_identical_in_every_recorder_mode(seed, monkeypatch):
    sc = scenario(seed)
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', False)
    ev2.reset_for_tests()
    baseline = run(sc, monkeypatch)

    inject_recorder(monkeypatch, 'signal_engine')
    assert run(sc, monkeypatch) == baseline                          # recording on

    ev2._RECORDERS['signal_engine'] = RaisingRecorder('signal_engine', ev2.ListSink(), {})
    assert run(sc, monkeypatch) == baseline                          # recorder raises

    inject_recorder(monkeypatch, 'signal_engine', max_queue=1)
    assert run(sc, monkeypatch) == baseline                          # queue saturated

    def boom(*a, **k):
        raise RuntimeError('module emit exploded')
    monkeypatch.setattr(ev2, 'emit', boom)
    assert run(sc, monkeypatch) == baseline                          # module API raises
    ev2.reset_for_tests()


def _events(sink, event_type='candidate.evaluated'):
    return [e for e in sink.records() if e['event_type'] == event_type]


def test_candidate_events_carry_decision_reason_geometry_and_rank(monkeypatch):
    rec, sink = inject_recorder(monkeypatch, 'signal_engine')
    sc = {'rows': [analysis_row('AAAUSDT', spread=0.02), analysis_row('BBBUSDT', spread=0.01),
                   analysis_row('CCCUSDT', spread=9.0), analysis_row('DDDUSDT', stop_valid=False),
                   analysis_row('EEEUSDT', trade_type=None), analysis_row('FFFUSDT', valid=False),
                   analysis_row('GGGUSDT'), analysis_row('HHHUSDT')],
          'open': {'GGGUSDT'}, 'cooldown': {'HHHUSDT'}, 'blocked': False, 'gates': False,
          'throttled': [], 'volume': {s: 1e6 for s in ['AAAUSDT', 'BBBUSDT'] + SYMBOLS}}
    out = run(sc, monkeypatch)
    rec.flush_now()
    by_symbol = {e['subject']['symbol']: e for e in _events(sink)}
    reasons = {s: (e['state']['decision'], e['state']['reason']) for s, e in by_symbol.items()}
    assert reasons == {
        'BBBUSDT': ('selected', None), 'AAAUSDT': ('rejected', 'not_selected_capacity'),
        'CCCUSDT': ('rejected', 'spread_exceeds_limit'),
        'DDDUSDT': ('rejected', 'stop_rejected:risk_exceeds_cap'),
        'EEEUSDT': ('rejected', 'no_trade_setup'), 'FFFUSDT': ('rejected', 'order_book_unavailable'),
        'GGGUSDT': ('rejected', 'open_trade_exists'), 'HHHUSDT': ('rejected', 'symbol_cooldown')}
    assert out['best']['symbol'] == 'BBBUSDT'
    sel, runner_up = by_symbol['BBBUSDT'], by_symbol['AAAUSDT']
    assert sel['payload']['selection']['rank'] == 1 and runner_up['payload']['selection']['rank'] == 2
    assert sel['payload']['selection']['eligible_count'] == 2
    geo = by_symbol['DDDUSDT']['payload']['geometry']                # rejected geometry is kept
    assert geo['entry_price'] and geo['stop_loss'] and geo['target_3'] and geo['stop_valid'] is False
    assert by_symbol['CCCUSDT']['payload']['limit'] == {'max_spread_pct': config.MAX_SPREAD_PCT}
    assert all(e['subject']['candidate_id'] and e['payload']['identity_status'] == 'ok'
               for e in by_symbol.values())
    assert all(e['payload']['macro']['macro_state'] == 'usdtd_flat' for e in by_symbol.values())
    ev2.reset_for_tests()


def test_repeated_cycles_record_only_decision_changes(monkeypatch):
    rec, sink = inject_recorder(monkeypatch, 'signal_engine')
    sc = next(scenario(k) for k in range(1000) if len(scenario(k)['rows']) >= 8)
    unique = {}                                   # production: one row per (symbol, timeframe)
    for r in sc['rows']:
        unique.setdefault((r['symbol'], r['timeframe']), r)
    sc['rows'] = list(unique.values())
    sc['blocked'] = False
    for _ in range(5):
        run(sc, monkeypatch)
    rec.flush_now()
    first = len(_events(sink))
    assert rec.suppressed >= 4 * first and first > 0
    sc['blocked'] = True                                             # every candidate changes state
    run(sc, monkeypatch)
    rec.flush_now()
    blocked = [e for e in _events(sink) if e['state']['reason'] == 'macro_block']
    assert len(blocked) == len({r['analysis_data']['pit']['candidate_id'] for r in sc['rows']})
    ev2.reset_for_tests()


def test_legacy_rows_without_pit_are_recorded_as_such(monkeypatch):
    rec, sink = inject_recorder(monkeypatch, 'signal_engine')
    row = analysis_row('LEGUSDT')
    del row['analysis_data']['pit']
    run({'rows': [row], 'open': set(), 'cooldown': set(), 'blocked': False, 'gates': False,
         'throttled': [], 'volume': {'LEGUSDT': 1e6}}, monkeypatch)
    rec.flush_now()
    [e] = _events(sink)
    assert e['subject']['candidate_id'] is None and e['payload']['identity_status'] == 'missing_pit'
    ev2.reset_for_tests()


def test_signal_identity_is_persisted_shape(monkeypatch):
    row = analysis_row('IDTUSDT')['analysis_data']
    ident = signal_logic.signal_identity(row)
    assert set(ident) == {'candle_open_time_ms', 'candle_close_time_ms', 'candle_id', 'candidate_id',
                          'strategy_version', 'code_sha', 'config_hash', 'analyzer_code_sha',
                          'analyzer_config_hash', 'weights_hash', 'identity_version'}
    assert ident['candidate_id'] == row['pit']['candidate_id']
    assert signal_logic.signal_identity({'pit': None})['candidate_id'] is None
