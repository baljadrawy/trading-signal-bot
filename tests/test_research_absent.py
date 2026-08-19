"""Regression: research/* now enters the signal path via a lazy import. If the research
package is missing from the production image (or a partial build), the signal engine must
run NORMALLY (graceful degradation to a no-op), not fail at startup or per-signal.
"""
import sys, builtins; sys.path.insert(0, '.'); sys.path.insert(0, 'signal_engine')
import asyncio
import signal_logic
from shared.config import config
from shared.database import Database


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
                                  "order_book": {"valid": True, "spread_pct": 0.01},
                                  "timeframe": "1h", "features": {"rsi": 30.0}}}]
    return engine, results


def test_signal_engine_starts_without_research_package(monkeypatch):
    # recorder ENABLED, but the research package is unavailable in the image
    monkeypatch.setattr(config, "ENABLE_EVIDENCE_RECORDER", True)
    monkeypatch.setattr(signal_logic, "_evidence_recorder", None, raising=False)
    monkeypatch.setattr(signal_logic, "_evidence_unavailable", False, raising=False)

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "research" or name.startswith("research."):
            raise ImportError("research package not in image")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    engine, results = _setup(monkeypatch)
    out = _run(engine.find_best_signal_live(results, FakeMacro()))   # must NOT raise
    assert out["symbol"] == "BTCUSDT"
    # recorder degrades to None (unavailable), no crash
    assert signal_logic.get_evidence_recorder() is None
    assert signal_logic._evidence_unavailable is True
