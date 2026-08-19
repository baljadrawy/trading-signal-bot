"""find_best_signal_live يجب ألا يبرمج تفضيل نوع (trade_type) — حُيِّد 2026-07-29 عكساً
لـ flip 4f84717. عند توفّر عدة مرشّحين صالحين غير مخنوقين، الأول ترتيباً يفوز بغضّ النظر
عن النوع؛ الخنق المُتعلَّم (learned_gates) هو من يقرّر لا انحياز مبرمَج (كلا النوعين بلا حافة).
"""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'signal_engine')
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


def _engine(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_EVIDENCE_RECORDER", False)

    async def fake_fetch(*a, **k):   # لا خلايا مخنوقة، لا رموز مفتوحة
        return []
    monkeypatch.setattr(Database, "fetch", fake_fetch)
    engine = signal_logic.SignalEngine()

    async def no_cooldown():
        return set()
    monkeypatch.setattr(engine, "_get_symbol_cooldown_set", no_cooldown)
    return engine


def _cand(sym, tt):
    return {"symbol": sym,
            "analysis_data": {"symbol": sym, "trade_type": tt, "timeframe": "15m",
                              "order_book": {"valid": True, "spread_pct": 0.01}}}


def test_first_candidate_wins_momentum_before_reversion(monkeypatch):
    """momentum أولاً ثم reversion → يفوز momentum (لا تفضيل reversion كما كان في flip 4f84717).
    على الكود المقلوب كان يعيد reversion رغم أن momentum جاء أولاً."""
    engine = _engine(monkeypatch)
    results = [_cand("AAAUSDT", "momentum"), _cand("BBBUSDT", "reversion")]
    out = _run(engine.find_best_signal_live(results, FakeMacro()))
    assert out["symbol"] == "AAAUSDT" and out["trade_type"] == "momentum"


def test_fixed_policy_does_not_depend_on_database_input_order(monkeypatch):
    """With equal execution data, the stable symbol tiebreaker replaces first-row bias."""
    engine = _engine(monkeypatch)
    results = [_cand("BBBUSDT", "reversion"), _cand("AAAUSDT", "momentum")]
    out = _run(engine.find_best_signal_live(results, FakeMacro()))
    assert out["symbol"] == "AAAUSDT" and out["trade_type"] == "momentum"
