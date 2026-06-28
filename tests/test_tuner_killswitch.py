"""Kill-switch + telemetry for the recent-trade auto-tuner (ParameterTuner.auto_tune).

Rule (live-trading auditor mandate): no dynamic threshold tuning based on recent
trades. When ENABLE_AUTO_TUNE is False the tuner must NOT write optimizer_settings.
On every bypass it must increment a counter and emit a structured telemetry record
(so we can later detect unexpected auto_tune calls). Code is preserved, only gated.
"""
import sys; sys.path.insert(0, '.')
import asyncio
from shared.config import config
import optimizer.tuner as tmod
from optimizer.tuner import ParameterTuner


def _run(coro):
    return asyncio.run(coro)


def test_auto_tune_disabled_never_writes(monkeypatch):
    """ENABLE_AUTO_TUNE=False -> returns [] and never WRITES optimizer_settings."""
    monkeypatch.setattr(config, "ENABLE_AUTO_TUNE", False, raising=False)
    tuner = ParameterTuner()

    async def _read_stub():
        return (3.0, 2)

    async def _boom_write(*a, **k):
        raise AssertionError("auto_tune wrote settings while disabled")

    monkeypatch.setattr(tuner, "_current_settings_for_log", _read_stub, raising=False)
    monkeypatch.setattr(tuner, "_save_setting", _boom_write)

    stats = {"win_rate": 20.0, "avg_profit": -1.0, "total_trades": 100}  # would normally tighten
    changes = _run(tuner.auto_tune(stats))
    assert changes == []


def test_auto_tune_bypass_increments_counter_and_records(monkeypatch):
    """Each bypass increments AUTO_TUNE_BYPASS_COUNT and the telemetry record carries
    reason + current thresholds + timestamp."""
    monkeypatch.setattr(config, "ENABLE_AUTO_TUNE", False, raising=False)
    tmod.AUTO_TUNE_BYPASS_COUNT = 0
    tuner = ParameterTuner()

    async def _read_stub():
        return (3.0, 2)

    monkeypatch.setattr(tuner, "_current_settings_for_log", _read_stub, raising=False)

    stats = {"win_rate": 20.0, "avg_profit": -1.0, "total_trades": 100}
    _run(tuner.auto_tune(stats))
    _run(tuner.auto_tune(stats))
    assert tmod.AUTO_TUNE_BYPASS_COUNT == 2

    rec = tmod._bypass_record(3.0, 2, tmod.AUTO_TUNE_BYPASS_COUNT)
    assert rec["reason"] == "ENABLE_AUTO_TUNE=False"
    assert rec["current_min_score"] == 3.0
    assert rec["current_min_tf"] == 2
    assert rec["bypass_count"] == 2
    assert "timestamp" in rec and rec["timestamp"]


def test_auto_tune_enabled_still_adjusts(monkeypatch):
    """Guard: with the flag ON the tuner still functions (conditional gate, not blanket off)."""
    monkeypatch.setattr(config, "ENABLE_AUTO_TUNE", True, raising=False)
    tuner = ParameterTuner()
    saved = {}

    async def _get():
        return {"min_score": 2.0, "min_tf_confirmations": 1}

    async def _save(key, value):
        saved[key] = value

    monkeypatch.setattr(tuner, "_get_current_settings", _get)
    monkeypatch.setattr(tuner, "_save_setting", _save)

    stats = {"win_rate": 20.0, "avg_profit": -1.0, "total_trades": 100}  # very bad -> tighten
    changes = _run(tuner.auto_tune(stats))
    assert changes
    assert saved.get("min_score_to_signal") == "3.0"   # 2.0 + 1.0 (very-bad branch)
