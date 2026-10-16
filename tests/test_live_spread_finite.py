"""Live selector: a non-finite, negative or malformed order-book spread is rejected before ranking.

Defect (A43-D): `float(nan) > MAX_SPREAD_PCT` is False, so a NaN spread passed the gate and
`min()` over a NaN key made the pick depend on input order — a NaN-spread candidate could be
SELECTED. These tests drive the REAL SignalEngine.find_best_signal_live (fake DB, stub volume)."""
import asyncio
import itertools
import json
import random
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'signal_engine')

import pytest

import signal_logic
from shared.candidate_selection import normalize, select
from shared.config import config
from shared.database import Database

BAD = [float("nan"), float("inf"), float("-inf"), -0.01, "abc", "nan", True, [], {}]


class Macro:
    async def should_block_now(self): return False
    def macro_state_key(self): return "usdtd_flat"
    def snapshot(self): return {}
    def state(self): return {}


def cand(symbol, tf="4h", spread=0.02, **kw):
    d = {"symbol": symbol, "timeframe": tf, "trade_type": "momentum", "stop_valid": True,
         "order_book": {"valid": True, "spread_pct": spread}, "entry_price": 100.0, "stop_loss": 98.0,
         "target_1": 102.0, "target_2": 103.6, "target_3": 104.4}
    d.update(kw)
    return d


@pytest.fixture
def run(monkeypatch):
    async def fetch(sql, *a):
        return []
    monkeypatch.setattr(Database, "fetch", fetch)
    monkeypatch.setattr(config, "ENABLE_EVIDENCE_RECORDER", False)
    monkeypatch.setattr(config, "LEARNING_GATES_ENABLED", False)
    monkeypatch.setattr(config, "SIGNAL_INTEGRITY_MODE", "off", raising=False)

    def go(cands, vols=None):
        eng = signal_logic.SignalEngine()

        async def vol(s):
            return (vols or {}).get(s, 1e6)

        async def no_cd():
            return set()
        monkeypatch.setattr(eng, "_get_volume_usdt", vol)
        monkeypatch.setattr(eng, "_get_symbol_cooldown_set", no_cd)
        rows = [{"symbol": c["symbol"], "timeframe": c["timeframe"], "analysis_data": json.dumps(c)}
                for c in cands]
        out = asyncio.run(eng.find_best_signal_live(rows, Macro()))
        return ((out["symbol"], out["timeframe"]) if out else None), eng.last_decisions
    return go


@pytest.mark.parametrize("bad", BAD, ids=repr)
def test_invalid_spread_is_rejected_with_a_reason(run, bad):
    pick, decisions = run([cand("AUSDT", spread=bad)])
    assert pick is None and decisions == {"AUSDT": "spread_invalid"}


def test_order_book_edge_cases(run):
    assert run([cand("AUSDT", order_book={"valid": False, "spread_pct": 0.02})])[1] == {"AUSDT": "order_book_unavailable"}
    assert run([cand("AUSDT", order_book={"valid": True})])[1] == {"AUSDT": "order_book_unavailable"}
    assert run([cand("AUSDT", order_book=None)])[1] == {"AUSDT": "order_book_unavailable"}
    assert run([cand("AUSDT", spread=0.0)])[0] == ("AUSDT", "4h")                     # zero is valid
    assert run([cand("AUSDT", spread="0.02")])[0] == ("AUSDT", "4h")                  # numeric string kept
    assert run([cand("AUSDT", spread=0.2)])[1] == {"AUSDT": "spread_exceeds_limit"}


def test_all_invalid_set_is_no_trade(run):
    pick, decisions = run([cand(f"{x}USDT", spread=b) for x, b in zip("ABCD", BAD)])
    assert pick is None and set(decisions.values()) == {"spread_invalid"}


def test_mixed_sets_never_select_an_invalid_spread_in_any_order(run):
    base = [cand("AUSDT", spread=0.03), cand("BUSDT", spread=float("nan")), cand("CUSDT", spread=0.02),
            cand("DUSDT", spread=float("-inf"))]
    picks = {run(list(p))[0] for p in itertools.permutations(base)}
    assert picks == {("CUSDT", "4h")}                                                   # 24 orders, one pick


def test_valid_finite_sets_keep_the_previous_selection(run):
    """Parity with the unchanged ranking key on valid inputs (the fix only removes invalid rows)."""
    rng = random.Random(61)
    checked = 0
    for _ in range(300):
        cands, vols = [], {}
        for _ in range(rng.randint(1, 6)):
            c = cand(f"V{rng.randint(0, 5)}USDT", tf=rng.choice(["15m", "4h", "1d"]),
                     spread=rng.choice([0.0, 0.01, 0.02, 0.05, 0.15, 0.2]))
            if not any((x["symbol"], x["timeframe"]) == (c["symbol"], c["timeframe"]) for x in cands):
                cands.append(c)
                vols.setdefault(c["symbol"], rng.choice([1e6, 2e6, None]))
        live, _ = run(cands, vols)
        eligible = [c for c in cands if c["order_book"]["spread_pct"] <= config.MAX_SPREAD_PCT]
        old_key = lambda c: (c["order_book"]["spread_pct"], -float(vols.get(c["symbol"]) or 0.0),
                             c["symbol"], c["timeframe"])                                 # pre-fix key
        expected = min(eligible, key=old_key) if eligible else None
        assert live == ((expected["symbol"], expected["timeframe"]) if expected else None)
        replica = select([normalize(c, vols.get(c["symbol"])) for c in cands], ranker="production_parity").selected
        assert live == ((replica.symbol, replica.timeframe) if replica else None)
        checked += expected is not None
    assert checked > 200


def test_helper_contract():
    f = signal_logic.finite_spread_pct
    assert [f(x) for x in (0.02, "0.02", 0, 0.0)] == [0.02, 0.02, 0.0, 0.0]
    assert all(f(x) is None for x in BAD + [None])
