"""Bootstrap confidence intervals for mean trade return and excess-over-null."""
import numpy as np


def mean_ci(returns, n: int = 10000, alpha: float = 0.05, seed: int = 0):
    r = np.asarray(returns, float)
    if r.size < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = rng.choice(r, size=(n, r.size), replace=True).mean(axis=1)
    lo = float(np.percentile(means, 100 * alpha / 2))
    hi = float(np.percentile(means, 100 * (1 - alpha / 2)))
    return (lo, hi)


def excess_ci(strat_returns, null_returns, n: int = 10000, alpha: float = 0.05, seed: int = 0):
    """Bootstrap CI of (mean strat - mean null) — the edge over random entry."""
    s = np.asarray(strat_returns, float)
    pool = np.asarray(null_returns, float)
    if s.size < 2 or pool.size < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    s_means = rng.choice(s, size=(n, s.size), replace=True).mean(axis=1)
    p_means = rng.choice(pool, size=(n, s.size), replace=True).mean(axis=1)
    diff = s_means - p_means
    lo = float(np.percentile(diff, 100 * alpha / 2))
    hi = float(np.percentile(diff, 100 * (1 - alpha / 2)))
    return (lo, hi)


def crosses_zero(ci) -> bool:
    lo, hi = ci
    if lo != lo or hi != hi:   # nan
        return True
    return lo <= 0 <= hi
