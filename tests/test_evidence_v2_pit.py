"""Point-in-time and leakage tests (P1): exchange-native candle identity, closed candles only,
availability timestamps precede the decision, and no outcome field exists before an outcome."""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'analyzer'); sys.path.insert(0, 'signal_engine')
import asyncio
import json
import re

from shared import evidence_v2 as ev2
from shared.config import config
from evidence_v2_fakes import (TF_MS, FakeClient, FakeMacro, analysis_row, inject_recorder,
                               synthetic_klines)

# The analyzer's result keys before P1 (develop 4e3eb0a). P1 may only ADD 'pit'.
PRE_P1_KEYS = {'symbol', 'timeframe', 'market_condition', 'regime', 'total_score', 'score_details',
               'features', 'research_features', 'execution_features', 'entry_reason',
               'selection_policy', 'entry_price', 'target_1', 'target_2', 'target_3', 'stop_loss',
               'stop_policy', 'stop_invalidation', 'stop_risk_pct', 'stop_valid',
               'stop_reject_reason', 'atr', 'rsi', 'macd_signal', 'volume_ratio', 'trend_ok',
               'trade_type'}
OUTCOME_KEY = re.compile(r'(profit|pnl|result|exit|realized|weighted_exit|hours_open)', re.I)


_ANALYZER = {}


def _branch_analyzer():
    """Load THIS branch's analyzer by path under a unique name (other tests may leave a different
    build of `technical_analyzer` in sys.modules)."""
    if 'mod' not in _ANALYZER:
        import importlib.util
        spec = importlib.util.spec_from_file_location('technical_analyzer_p1_branch',
                                                      'analyzer/technical_analyzer.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ANALYZER['mod'] = mod
    return _ANALYZER['mod']


def _analyze(rows, monkeypatch, tf='15m', live=True):
    technical_analyzer = _branch_analyzer()
    monkeypatch.setattr(config, 'LIVE_LEARNING_MODE', live)
    analyzer = technical_analyzer.TechnicalAnalyzer(FakeClient(rows))
    return asyncio.run(analyzer.analyze('SYNTHUSDT', tf))


def test_pit_identity_is_the_last_closed_exchange_candle(monkeypatch):
    rows, current_open = synthetic_klines('15m')
    out = _analyze(rows, monkeypatch)
    pit = out['pit']
    assert pit['candle_open_time_ms'] == current_open - TF_MS['15m']      # not the open candle
    assert pit['candle_close_time_ms'] == current_open - 1
    assert pit['candle_open_time_ms'] % TF_MS['15m'] == 0
    assert pit['candle_close_time_ms'] < pit['klines_fetched_at_ms'] <= pit['analyzed_at_ms']
    assert pit['candle_id'] == f"SYNTHUSDT|15m|{pit['candle_open_time_ms']}"
    assert pit['candidate_id'] == ev2.candidate_id(pit['candle_id'], out['trade_type'], config.APP_VERSION)
    assert len(pit['code_sha']) == 64 and len(pit['config_hash']) == 64 and pit['weights_hash']
    assert pit['strategy_version'] == config.APP_VERSION and pit['bars'] == config.CANDLES_TO_FETCH


def test_pit_block_is_purely_additive(monkeypatch):
    rows, _ = synthetic_klines('15m')
    for live in (True, False):
        out = _analyze(rows, monkeypatch, live=live)
        assert set(out) - {'pit'} == PRE_P1_KEYS


def test_open_candle_cannot_influence_any_analysis_value(monkeypatch):
    base_rows, _ = synthetic_klines('15m', seed=11)
    spiked_rows, _ = synthetic_klines('15m', seed=11, open_candle_close=10_000.0)
    a, b = _analyze(base_rows, monkeypatch), _analyze(spiked_rows, monkeypatch)
    volatile = {'klines_fetched_at_ms', 'analyzed_at_ms'}
    assert {k: v for k, v in a.items() if k != 'pit'} == {k: v for k, v in b.items() if k != 'pit'}
    assert ({k: v for k, v in a['pit'].items() if k not in volatile}
            == {k: v for k, v in b['pit'].items() if k not in volatile})


class _Clock:
    """A controlled wall clock for the modules that decide which candles are closed."""
    def __init__(self, t):
        import time as real
        self._real, self.t = real, t

    def time(self):
        return self.t

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_candidate_same_candle_same_id_next_candle_new_id(monkeypatch):
    now = ev2.now_ms()
    monkeypatch.setattr('shared.ohlcv.time', _Clock(now / 1000))
    monkeypatch.setattr('shared.evidence_v2.time', _Clock(now / 1000))
    rows, current_open = synthetic_klines('15m', seed=3, now_ms=now)
    first = _analyze(rows, monkeypatch)['pit']
    again = _analyze(rows, monkeypatch)['pit']
    later_now = current_open + TF_MS['15m'] + 5000                 # the next candle has closed
    monkeypatch.setattr('shared.ohlcv.time', _Clock(later_now / 1000))
    monkeypatch.setattr('shared.evidence_v2.time', _Clock(later_now / 1000))
    later_rows, _ = synthetic_klines('15m', seed=3, now_ms=later_now)
    later = _analyze(later_rows, monkeypatch)['pit']
    assert first['candidate_id'] == again['candidate_id']
    assert later['candle_open_time_ms'] == first['candle_open_time_ms'] + TF_MS['15m']
    assert later['candidate_id'] != first['candidate_id']
    assert later['candle_close_time_ms'] < later['klines_fetched_at_ms']


def _engine(monkeypatch):
    import signal_logic
    from shared.database import Database

    async def fake_fetch(*a, **k):
        return []
    monkeypatch.setattr(Database, 'fetch', fake_fetch)
    engine = signal_logic.SignalEngine()

    async def no_cooldown():
        return set()

    async def volume(symbol):
        return 1_000_000.0
    monkeypatch.setattr(engine, '_get_symbol_cooldown_set', no_cooldown)
    monkeypatch.setattr(engine, '_get_volume_usdt', volume)
    return engine


def _all_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_keys(v)


def test_decision_events_follow_their_inputs_and_carry_no_outcomes(monkeypatch):
    rec, sink = inject_recorder(monkeypatch, 'signal_engine')
    engine = _engine(monkeypatch)
    rows = [analysis_row('AAAUSDT'), analysis_row('BBBUSDT', spread=5.0),
            analysis_row('CCCUSDT', stop_valid=False), analysis_row('DDDUSDT', trade_type=None)]
    asyncio.run(engine.find_best_signal_live(rows, FakeMacro()))
    rec.flush_now()
    events = sink.records()
    assert {e['event_type'] for e in events} == {'candidate.evaluated'}
    for e in events:
        pit, decided = e['payload']['pit'], e['event_time_ms']
        for field in ('candle_close_time_ms', 'klines_fetched_at_ms', 'analyzed_at_ms',
                      'orderbook_fetched_at_ms'):
            assert pit[field] <= decided, field
        assert e['payload']['macro']['macro_valid_at_ms'] <= decided
        assert not [k for k in _all_keys(e['payload']) if OUTCOME_KEY.search(k)]
        assert all(isinstance(e[k], int) for k in ('event_time_ms', 'recorded_at_ms'))
    ev2.reset_for_tests()


def test_iso_timestamps_are_utc_z():
    assert ev2.ms_to_iso(1700000000123) == '2023-11-14T22:13:20.123Z'
    assert json.loads(ev2.canonical_json({'t': ev2._dt.datetime(2026, 9, 27, 12, 0)})) == {
        't': '2026-09-27T12:00:00Z'}
