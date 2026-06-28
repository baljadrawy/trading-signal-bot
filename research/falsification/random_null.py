"""Random-entry null test.

H0: the strategy's trades are indistinguishable from random entries drawn from the
same market/period. `null_returns` is a POOL of per-trade returns produced by random
entries (the caller supplies it — e.g. random entries over the scanned universe).
P(strategy > random) = fraction of equal-sized random samples whose mean the
strategy's mean exceeds.
"""
import numpy as np


def p_strategy_gt_random(strat_returns, null_returns, n_boot: int = 10000, seed: int = 0) -> float:
    s = np.asarray(strat_returns, float)
    pool = np.asarray(null_returns, float)
    if s.size == 0 or pool.size == 0:
        return float("nan")
    rng = np.random.default_rng(seed)
    n = s.size
    null_means = rng.choice(pool, size=(n_boot, n), replace=True).mean(axis=1)
    return float(np.mean(s.mean() > null_means))


def permutation_null(strat_returns, n_boot: int = 10000, seed: int = 0) -> float:
    """Weaker fallback when no external null pool exists: sign-flip null
    (H0: returns symmetric about zero). Use only as a last resort."""
    s = np.asarray(strat_returns, float)
    if s.size == 0:
        return float("nan")
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_boot, s.size))
    flipped_means = (signs * np.abs(s)).mean(axis=1)
    return float(np.mean(s.mean() > flipped_means))
