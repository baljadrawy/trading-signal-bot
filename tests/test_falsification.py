"""Known-answer tests for the unified falsification library (research/falsification).

Philosophy: assume NO alpha. The library must FAIL no-edge data and only PASS data
that genuinely beats a random-entry null with a CI that excludes zero, a positive
information ratio, no remove-best collapse, and OOS consistency.
"""
import sys; sys.path.insert(0, '.')
import numpy as np
import pytest

from research.falsification import validate, StrategyData
from research.falsification.random_null import p_strategy_gt_random
from research.falsification.bootstrap import mean_ci
from research.falsification.remove_best import remove_best_pf
from research.falsification.metrics import profit_factor, cohens_d, sharpe


# ---------------- component-level known answers ----------------
def test_random_null_no_edge_is_calibrated():
    """No-edge data: P centers on ~0.5 over many draws and the false-positive rate
    (P>0.95) is roughly controlled (~5%). A single draw is noisy by design, so we
    assert the distributional property, not one value."""
    null = np.random.default_rng(0).normal(0.0, 0.02, 5000)
    ps = np.array([
        p_strategy_gt_random(
            np.random.default_rng(100 + s).normal(0.0, 0.02, 300),
            null, n_boot=2000, seed=s)
        for s in range(60)
    ])
    assert 0.40 < ps.mean() < 0.60          # centered ~0.5 (no systematic edge)
    assert (ps > 0.95).mean() < 0.15        # false-positive rate ~5% (slack for n=60)


def test_random_null_strong_edge_detected():
    rng = np.random.default_rng(0)
    strat = rng.normal(0.02, 0.02, 300)   # clearly positive mean
    null = rng.normal(0.0, 0.02, 5000)
    p = p_strategy_gt_random(strat, null, n_boot=4000, seed=1)
    assert p > 0.95


def test_bootstrap_ci_includes_zero_for_zero_mean():
    rng = np.random.default_rng(2)
    r = rng.normal(0.0, 0.02, 200)
    lo, hi = mean_ci(r, n=4000, seed=3)
    assert lo <= 0 <= hi


def test_remove_best_collapses_when_concentrated():
    # 50 tiny losers + 3 huge winners -> PF collapses after removing top trades
    r = np.array([-0.01] * 50 + [3.0, 3.0, 3.0])
    full = profit_factor(r)
    after = remove_best_pf(r, k=5)
    assert full > 1.5 and after < 1.0


def test_cohens_d_sign_and_magnitude():
    a = np.full(100, 0.02); b = np.full(100, 0.0)
    # zero within-group variance -> guard returns nan, so use small noise
    rng = np.random.default_rng(4)
    a = rng.normal(0.02, 0.01, 200); b = rng.normal(0.0, 0.01, 200)
    d = cohens_d(a, b)
    assert d > 0.8                  # large effect


# ---------------- unified validate() contract ----------------
def _shape_ok(res):
    assert set(res.keys()) >= {"pass", "metrics", "failure_reasons", "recommendation"}
    assert set(res["metrics"].keys()) >= {
        "P_strategy_gt_random", "Sharpe", "PF", "InformationRatio", "CohensD"}
    assert isinstance(res["failure_reasons"], list)
    assert isinstance(res["recommendation"], list)


def test_validate_rejects_no_edge():
    rng = np.random.default_rng(5)
    data = StrategyData(
        returns=rng.normal(0.0, 0.02, 300),
        null_returns=rng.normal(0.0, 0.02, 5000),
    )
    res = validate(data)
    _shape_ok(res)
    assert res["pass"] is False
    assert res["failure_reasons"]                     # at least one reason
    assert "keep_shadow_mode" in res["recommendation"]


def test_validate_accepts_genuine_edge():
    rng = np.random.default_rng(6)
    data = StrategyData(
        returns=rng.normal(0.02, 0.02, 400),
        null_returns=rng.normal(0.0, 0.02, 8000),
        timestamps=list(range(400)),
    )
    res = validate(data)
    _shape_ok(res)
    assert res["metrics"]["P_strategy_gt_random"] > 0.95
    assert res["pass"] is True


def test_validate_missing_null_stays_shadow():
    rng = np.random.default_rng(7)
    data = StrategyData(returns=rng.normal(0.02, 0.02, 300))   # no null provided
    res = validate(data)
    _shape_ok(res)
    assert res["pass"] is False
    assert res["metrics"]["P_strategy_gt_random"] is None
    assert any("null" in r.lower() for r in res["failure_reasons"])
    assert "keep_shadow_mode" in res["recommendation"]
