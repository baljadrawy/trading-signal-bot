"""A44 Phase F: staged candidate-selection pipeline. Synthetic candidates only; these tests show
engineering properties (parity, determinism, frequency neutrality), not ranking quality."""
import pathlib
import random
import sys; sys.path.insert(0, '.')

import pytest

from shared.candidate_selection import (ACTIVE_RANKER, EXPERIMENTAL_RANKERS, RANKERS,
                                        EligibilityPolicy, cost_per_risk_v1_key, normalize,
                                        run_pipeline, select)
from shared.signal_quality import CorrelatedExposurePolicy, Exposure

ROOT = pathlib.Path(__file__).resolve().parents[1]


def cand(symbol, tf="4h", spread=0.02, risk=2.0, tt="momentum", **kw):
    d = {"symbol": symbol, "timeframe": tf, "trade_type": tt, "stop_valid": True,
         "order_book": {"valid": True, "spread_pct": spread},
         "entry_price": 100.0, "stop_loss": 100.0 - risk, "target_1": 100.0 + risk,
         "target_2": 100.0 + 1.8 * risk, "target_3": 100.0 + 2.2 * risk, "atr": risk / 1.5}
    d.update(kw)
    return d


def random_sets(n, seed):
    rng = random.Random(seed)
    for _ in range(n):
        cs = []
        for j in range(rng.randint(0, 7)):
            c = cand(f"R{rng.randint(0, 9)}USDT", tf=rng.choice(["15m", "4h", "1d"]),
                     spread=rng.choice([0.01, 0.02, 0.05, 0.2]), risk=rng.choice([0.3, 1.0, 2.5]),
                     tt=rng.choice(["momentum", "reversion", None]),
                     stop_valid=rng.choice([True, True, False]))
            if any(x.symbol == c["symbol"] and x.timeframe == c["timeframe"] for x in cs):
                continue
            cs.append(normalize(c, rng.choice([1e6, 3e6, None])))
        state = {"open_symbols": frozenset(s for s in {x.symbol for x in cs} if rng.random() < 0.15),
                 "cooldown": frozenset(s for s in {x.symbol for x in cs} if rng.random() < 0.15)}
        yield cs, state


def test_production_ranker_in_the_pipeline_matches_the_parity_selector():
    for cs, state in random_sets(400, 1):
        a = run_pipeline(cs, **state).selected
        b = select(cs, **state).selected
        ka = (a.symbol, a.timeframe) if a else None
        kb = (b.symbol, b.timeframe) if b else None
        assert ka == kb


def test_rankers_are_frequency_neutral_and_report_disagreement():
    """With stages 1–3 fixed, a ranker can change WHICH candidate is selected, never WHETHER one is."""
    selected_cycles = {r: 0 for r in RANKERS}
    disagree = {r: 0 for r in EXPERIMENTAL_RANKERS}
    total = 0
    for cs, state in random_sets(500, 2):
        res = {r: run_pipeline(cs, ranker=r, **state) for r in RANKERS}
        some = {r: res[r].selected is not None for r in RANKERS}
        assert len(set(some.values())) == 1
        total += 1
        for r in RANKERS:
            selected_cycles[r] += some[r]
        base = res[ACTIVE_RANKER].selected
        for r in EXPERIMENTAL_RANKERS:
            disagree[r] += base is not None and res[r].selected is not base
    assert len(set(selected_cycles.values())) == 1
    assert all(0 < v < selected_cycles[ACTIVE_RANKER] for v in disagree.values())


def test_cost_per_risk_ranker_prefers_lower_cost_burden_and_sorts_invalid_last():
    tight = normalize(cand("AAAUSDT", spread=0.01, risk=0.3))       # cost 0.21 / 0.3 = 0.70 R
    wide = normalize(cand("BBBUSDT", spread=0.05, risk=2.5))        # cost 0.25 / 2.5 = 0.10 R
    broken = normalize(cand("CCCUSDT", order_book={"valid": True, "spread_pct": float("nan")}))
    assert cost_per_risk_v1_key(wide) < cost_per_risk_v1_key(tight) < cost_per_risk_v1_key(broken)
    assert run_pipeline([tight, wide], ranker="cost_per_risk_v1").selected.symbol == "BBBUSDT"
    assert run_pipeline([tight, wide]).selected.symbol == "AAAUSDT"   # production: tightest spread


def test_risk_stage_enforces_only_when_enabled_and_every_candidate_is_explained():
    cs = [normalize(cand("HIGHUSDT"), 5e6), normalize(cand("LOWUSDT", spread=0.03), 1e6),
          normalize(cand("NOSETUP", tt=None)), normalize(cand("BADUSDT", entry_price=90.0))]
    open_ = [Exposure("ETHUSDT", 50, 1.0)]
    betas = {"HIGHUSDT": 1.4, "LOWUSDT": 0.3, "BADUSDT": 0.1}
    enforced = run_pipeline(cs, risk_policy=CorrelatedExposurePolicy(enabled=True),
                            open_exposures=open_, betas=betas)
    shadow = run_pipeline(cs, risk_policy=CorrelatedExposurePolicy(), open_exposures=open_, betas=betas)
    assert enforced.selected.symbol == "LOWUSDT" and shadow.selected.symbol == "HIGHUSDT"
    ex = enforced.explain()
    assert [e["stage"] for e in ex] == ["risk", "ranked", "eligibility", "execution"]
    assert ex[0]["reasons"] == ["beta_weighted_cap_exceeded"] and ex[3]["reasons"] == ["bracket_invalid"]
    assert sum(e["selected"] for e in ex) == 1 and len(ex) == len(cs)


def test_live_engine_uses_only_the_production_key():
    src = (ROOT / "signal_engine" / "signal_logic.py").read_text()
    assert "best = min(eligible, key=self._fixed_candidate_key)" in src
    assert "RANKERS" not in src and "run_pipeline" not in src and "candidate_selection" not in src
    assert ACTIVE_RANKER == "production_parity" and ACTIVE_RANKER not in EXPERIMENTAL_RANKERS
    with pytest.raises(ValueError, match="unknown_ranker"):
        run_pipeline([], ranker="weighted_blend")


def test_pipeline_is_input_order_invariant():
    for cs, state in random_sets(100, 3):
        for r in RANKERS:
            picks = set()
            for seed in range(4):
                shuffled = cs[:]
                random.Random(seed).shuffle(shuffled)
                s = run_pipeline(shuffled, ranker=r, **state).selected
                picks.add((s.symbol, s.timeframe) if s else None)
            assert len(picks) == 1
