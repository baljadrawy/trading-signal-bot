"""Integration: the evidence hook in signal_logic must NOT change the live signal output
(recorder on or off) and must capture evidence when enabled. First touch on the live line.
"""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'signal_engine')
import asyncio
import copy
import signal_logic
from shared.config import config
from shared.database import Database
from research.null_a.recorder import EvidenceRecorder
from research.null_a.sinks import ListSink


class FakeMacro:
    async def should_block_now(self):
        return False
    def macro_state_key(self):
        return "usdtd_flat"
    def snapshot(self):
        return {"btc_trend": "neutral"}
    def state(self):
        return {"usdtd": "flat"}


def _run(coro):
    return asyncio.run(coro)


def _setup(monkeypatch):
    async def fake_fetch(*a, **k):
        return []
    monkeypatch.setattr(Database, "fetch", fake_fetch)
    engine = signal_logic.SignalEngine()

    async def no_cooldown():
        return set()
    monkeypatch.setattr(engine, "_get_symbol_cooldown_set", no_cooldown)
    results = [{"symbol": "BTCUSDT",
                "analysis_data": {"symbol": "BTCUSDT", "trade_type": "momentum",
                                  "timeframe": "15m", "features": {"rsi": 30.0}}}]
    return engine, results


def test_hook_disabled_output_unchanged(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_EVIDENCE_RECORDER", False)
    engine, results = _setup(monkeypatch)
    out = _run(engine.find_best_signal_live(results, FakeMacro()))
    assert out["symbol"] == "BTCUSDT" and out["trade_type"] == "momentum"


def test_hook_enabled_same_output_and_captures(monkeypatch):
    # disabled run = ground truth
    monkeypatch.setattr(config, "ENABLE_EVIDENCE_RECORDER", False)
    engine, results = _setup(monkeypatch)
    expected = _run(engine.find_best_signal_live(copy.deepcopy(results), FakeMacro()))

    # enabled run with an injected in-memory recorder
    monkeypatch.setattr(config, "ENABLE_EVIDENCE_RECORDER", True)
    sink = ListSink()
    monkeypatch.setattr(signal_logic, "_evidence_recorder",
                        EvidenceRecorder(sink=sink, enabled=True), raising=False)
    monkeypatch.setattr(signal_logic, "_evidence_unavailable", False, raising=False)
    engine2, results2 = _setup(monkeypatch)
    got = _run(engine2.find_best_signal_live(results2, FakeMacro()))

    assert got == expected                      # signal output byte-identical
    signal_logic._evidence_recorder.flush_now()
    assert len(sink.records) == 1               # evidence captured
    assert sink.records[0]["source"] == "live"
    assert sink.records[0]["symbol"] == "BTCUSDT"
    assert sink.records[0]["ohlcv_status"] == "deferred"


def test_hook_survives_recorder_failure(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_EVIDENCE_RECORDER", True)

    class Boom:
        enabled = True
        def capture(self, **k):
            raise RuntimeError("boom")
    monkeypatch.setattr(signal_logic, "_evidence_recorder", Boom(), raising=False)
    monkeypatch.setattr(signal_logic, "_evidence_unavailable", False, raising=False)
    engine, results = _setup(monkeypatch)
    out = _run(engine.find_best_signal_live(results, FakeMacro()))   # must not raise
    assert out["symbol"] == "BTCUSDT"


def test_hook_never_raises_even_if_logging_fails(monkeypatch):
    """Audit regression: the except-handler's OWN logging must not propagate.
    Recorder crashes AND the logger crashes -> signal must still be returned."""
    monkeypatch.setattr(config, "ENABLE_EVIDENCE_RECORDER", True)

    class Boom:
        enabled = True
        def capture(self, **k):
            raise RuntimeError("boom")
    monkeypatch.setattr(signal_logic, "_evidence_recorder", Boom(), raising=False)
    monkeypatch.setattr(signal_logic, "_evidence_unavailable", False, raising=False)

    def bad_warn(*a, **k):
        raise OSError("log handler dead")
    monkeypatch.setattr(signal_logic.logger, "warning", bad_warn)

    engine, results = _setup(monkeypatch)
    out = _run(engine.find_best_signal_live(results, FakeMacro()))   # must NOT raise
    assert out["symbol"] == "BTCUSDT"
