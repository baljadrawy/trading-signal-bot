"""BEFORE/AFTER decision parity (P1-F, P1-R hard gate): the develop (f973cace) decision code and
this branch, fed identical synthetic inputs, must decide identically with forward instrumentation
OFF and ON. Runs only when P1_BEFORE_TREE points at a develop checkout."""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'signal_engine'); sys.path.insert(0, 'analyzer')
import asyncio
import copy
import importlib.util
import json
import os

import pytest

from shared import evidence_v2 as ev2
from shared.config import config
from shared.database import Database
from evidence_v2_fakes import FakeClient, FakeMacro, inject_recorder, synthetic_klines
from test_evidence_v2_signal_engine import scenario

BEFORE = os.getenv('P1_BEFORE_TREE')
pytestmark = pytest.mark.skipif(not BEFORE, reason='P1_BEFORE_TREE not set (develop checkout)')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def decide(module, sc, monkeypatch):
    async def fake_fetch(sql, *args):
        if 'learned_gates' in sql:
            return sc['throttled']
        if 'active_trades' in sql:
            return [{'symbol': s} for s in sorted(sc['open'])]
        return []
    monkeypatch.setattr(Database, 'fetch', fake_fetch)
    monkeypatch.setattr(config, 'LEARNING_GATES_ENABLED', sc['gates'])
    monkeypatch.setattr(config, 'ENABLE_EVIDENCE_RECORDER', False)
    engine = module.SignalEngine()

    async def cooldown():
        return set(sc['cooldown'])

    async def volume(symbol):
        return sc['volume'][symbol]
    monkeypatch.setattr(engine, '_get_symbol_cooldown_set', cooldown)
    monkeypatch.setattr(engine, '_get_volume_usdt', volume)
    rows = copy.deepcopy(sc['rows'])
    for r in rows:                                   # develop never saw a pit block: strip it
        r['analysis_data'].pop('pit', None) if module.__name__ == 'signal_logic_before' else None
    best = asyncio.run(engine.find_best_signal_live(rows, FakeMacro(blocked=sc['blocked'])))
    if best:
        best.pop('pit', None)
    return json.loads(json.dumps({'best': best, 'decisions': engine.last_decisions},
                                 sort_keys=True, default=str))


@pytest.fixture(scope='module')
def before_logic():
    return load('signal_logic_before', os.path.join(BEFORE, 'signal_engine', 'signal_logic.py'))


@pytest.mark.parametrize('mode', ['off', 'on'])
@pytest.mark.parametrize('seed', range(300))
def test_signal_selection_before_after(seed, mode, before_logic, monkeypatch):
    import signal_logic as after_logic
    sc = scenario(seed)
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', False)
    ev2.reset_for_tests()
    before = decide(before_logic, sc, monkeypatch)
    if mode == 'on':
        inject_recorder(monkeypatch, 'signal_engine')
    after = decide(after_logic, sc, monkeypatch)
    ev2.reset_for_tests()
    assert after == before


@pytest.mark.parametrize('mode', ['off', 'on'])
@pytest.mark.parametrize('tf', ['15m', '4h', '1d'])
@pytest.mark.parametrize('seed', range(8))
@pytest.mark.parametrize('live', [True, False])
def test_analyzer_before_after(tf, seed, live, mode, monkeypatch):
    before_mod = load('technical_analyzer_before', os.path.join(BEFORE, 'analyzer', 'technical_analyzer.py'))
    after_mod = load('technical_analyzer_after', 'analyzer/technical_analyzer.py')
    monkeypatch.setattr(config, 'LIVE_LEARNING_MODE', live)
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', mode == 'on')
    rows, _ = synthetic_klines(tf, seed=seed)
    b = asyncio.run(before_mod.TechnicalAnalyzer(FakeClient(rows)).analyze('SYNTHUSDT', tf))
    a = asyncio.run(after_mod.TechnicalAnalyzer(FakeClient(rows)).analyze('SYNTHUSDT', tf))
    assert b is not None and a is not None
    if mode == 'off':                     # OFF: byte-identical analysis result (no pit at all)
        assert 'pit' not in a and 'pit' not in b
        assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    else:                                 # ON: identical apart from pit (reference may itself carry pit
        assert 'pit' in a                 # when it already contains P1, e.g. develop da256f74)
        strip = lambda d: json.dumps({k: v for k, v in d.items() if k != 'pit'}, sort_keys=True, default=str)
        assert strip(a) == strip(b)
