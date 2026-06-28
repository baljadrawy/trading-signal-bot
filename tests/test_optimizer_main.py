"""Optimizer cycle must handle an EMPTY auto_tune result (the disabled-tuner case)
without crashing and without sending a 'changes' report. Replaces the manual
inspection of optimizer/main.py:85-92.
"""
import sys, types; sys.path.insert(0, '.')
import asyncio
# aiohttp is a Docker-only dep (used by shared.alerts at import); stub it so the
# optimizer.main import chain loads in the lean test venv. Never actually called here.
sys.modules.setdefault('aiohttp', types.ModuleType('aiohttp'))
import optimizer.main as m


def test_main_handles_empty_auto_tune_result(monkeypatch):
    calls = {"logged": None, "report_sent": False}

    class FakeAnalyzer:
        async def get_overall_stats(self):
            return {"total_trades": 50, "win_rate": 20.0, "avg_profit": -1.0}

        async def update_indicator_weights(self):
            return 0

    class FakeTuner:
        async def auto_tune(self, stats):
            return []   # the empty result the cycle must handle

    async def fake_log(stats, weights_updated, changes):
        calls["logged"] = (weights_updated, changes)

    async def fake_report(*a, **k):
        calls["report_sent"] = True

    monkeypatch.setattr(m, "log_optimization", fake_log)
    monkeypatch.setattr(m, "send_optimization_report", fake_report)

    asyncio.run(m.run_optimization_cycle(FakeAnalyzer(), FakeTuner()))

    assert calls["logged"] == (0, [])        # logged with empty changes, no crash
    assert calls["report_sent"] is False     # no report when nothing changed
