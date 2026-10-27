"""Serial-dependence-robust inference for a daily return series. Standard library only; research only.

* ``newey_west_se`` / ``hac_t``: Newey-West (1987) heteroskedasticity- and autocorrelation-consistent standard error
  of the sample mean, Bartlett kernel weights 1 - l / (L + 1) for l = 1..L.
* ``stationary_bootstrap_ci``: Politis-Romano (1994) stationary bootstrap (geometric block lengths with mean
  ``mean_block``, circular wrap), percentile interval, for the mean and the per-observation Sharpe ratio. Seeded with
  ``random.Random(seed)`` so a result is reproducible from (series, mean_block, n_resamples, seed).

Lag rule (documented, fixed before data)
----------------------------------------
``REGISTER_HAC_LAG = 7`` is the lag named in docs/strategy/HYPOTHESIS_REGISTER.md and NEXT_LICENSED_DATA_STEP.md §4
(Bartlett, lag 7 for daily returns: one week of serial dependence). It is the default and the preregistered choice.
``newey_west_lag_rule(n)`` = floor(4 (n / 100) ** (2 / 9)) (Newey-West 1994 plug-in starting value) is provided as a
reported sensitivity only; it must never be chosen after seeing which lag gives the larger t.

Small-sample convention: with ``ddof=1`` (default) the long-run variance is multiplied by n / (n - 1), so at lag 0
the HAC standard error equals the classical s / sqrt(n) with s the ddof-1 sample standard deviation. ``ddof=0`` gives
the textbook (biased) Newey-West estimator.

Evidence class: these are inference tools. Running them on synthetic data proves engineering properties only.
"""
import math
import random
from dataclasses import dataclass

REGISTER_HAC_LAG = 7
DEFAULT_MEAN_BLOCK = 20          # NEXT_LICENSED_DATA_STEP.md §4: stationary bootstrap, mean block 20 days


def _series(xs, minimum=2) -> list:
    out = []
    for x in xs:
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
            raise ValueError("observations must be finite numbers")
        out.append(float(x))
    if len(out) < minimum:
        raise ValueError(f"need at least {minimum} observations")
    return out


def _count(name, v, lo):
    if isinstance(v, bool) or not isinstance(v, int) or v < lo:
        raise ValueError(f"{name} must be an int >= {lo}")
    return v


def newey_west_lag_rule(n: int) -> int:
    """Newey-West (1994) plug-in starting lag floor(4 (n/100)^(2/9)); a sensitivity, not the preregistered lag."""
    _count("n", n, 1)
    return int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))


def newey_west_se(xs, lag: int = REGISTER_HAC_LAG, *, ddof: int = 1) -> float:
    """HAC standard error of the mean of ``xs`` (Bartlett kernel, ``lag`` autocovariances)."""
    x = _series(xs)
    n = len(x)
    _count("lag", lag, 0)
    if lag >= n:
        raise ValueError("lag must be < number of observations")
    if ddof not in (0, 1):
        raise ValueError("ddof must be 0 or 1")
    m = sum(x) / n
    d = [v - m for v in x]
    lrv = sum(v * v for v in d) / n
    for lg in range(1, lag + 1):
        gamma = sum(d[t] * d[t - lg] for t in range(lg, n)) / n
        lrv += 2.0 * (1.0 - lg / (lag + 1.0)) * gamma
    if ddof == 1:
        lrv *= n / (n - 1.0)
    if lrv <= 0:
        raise ValueError("non-positive long-run variance")
    return math.sqrt(lrv / n)


def plain_se(xs) -> float:
    """Classical standard error s / sqrt(n), s with ddof = 1."""
    x = _series(xs)
    n = len(x)
    m = sum(x) / n
    return math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1) / n)


def hac_t(xs, lag: int = REGISTER_HAC_LAG, *, ddof: int = 1) -> float:
    """t statistic of the mean against 0 with the Newey-West standard error."""
    x = _series(xs)
    return (sum(x) / len(x)) / newey_west_se(x, lag, ddof=ddof)


def stationary_bootstrap_indices(n: int, mean_block: float, rng: random.Random) -> list:
    """One Politis-Romano resample of indices 0..n-1: start uniform, continue with probability 1 - 1/mean_block,
    wrap around the end (circular)."""
    _count("n", n, 1)
    if isinstance(mean_block, bool) or not isinstance(mean_block, (int, float)) or not mean_block >= 1:
        raise ValueError("mean_block must be >= 1")
    p = 1.0 / float(mean_block)
    idx, i = [], rng.randrange(n)
    for _ in range(n):
        idx.append(i)
        i = rng.randrange(n) if rng.random() < p else (i + 1) % n
    return idx


def _mean(x):
    return sum(x) / len(x)


def _sharpe(x):
    n = len(x)
    m = sum(x) / n
    v = sum((a - m) ** 2 for a in x) / (n - 1)
    return m / math.sqrt(v) if v > 0 else float("nan")


STATISTICS = {"mean": _mean, "sharpe": _sharpe}


@dataclass(frozen=True)
class BootstrapCI:
    statistic: str
    estimate: float
    lower: float
    upper: float
    level: float
    mean_block: float
    n_resamples: int
    seed: int

    def covers(self, value: float) -> bool:
        return self.lower <= value <= self.upper


def _quantile(sorted_xs, q):
    """Linear-interpolation quantile (type 7) of an already sorted list."""
    h = (len(sorted_xs) - 1) * q
    lo = math.floor(h)
    hi = min(lo + 1, len(sorted_xs) - 1)
    return sorted_xs[lo] + (h - lo) * (sorted_xs[hi] - sorted_xs[lo])


def stationary_bootstrap_ci(xs, statistic: str = "mean", *, mean_block: float = DEFAULT_MEAN_BLOCK,
                            n_resamples: int = 1000, level: float = 0.95, seed: int) -> BootstrapCI:
    """Percentile CI of ``statistic`` ('mean' or per-observation 'sharpe') by the stationary bootstrap."""
    x = _series(xs, minimum=3)
    if statistic not in STATISTICS:
        raise ValueError(f"statistic must be one of {tuple(STATISTICS)}")
    _count("n_resamples", n_resamples, 10)
    _count("seed", seed, 0)
    if not 0.0 < level < 1.0:
        raise ValueError("level must be in (0, 1)")
    f = STATISTICS[statistic]
    rng = random.Random(seed)
    n = len(x)
    draws = []
    for _ in range(n_resamples):
        v = f([x[i] for i in stationary_bootstrap_indices(n, mean_block, rng)])
        if math.isfinite(v):
            draws.append(v)
    if len(draws) < 10:
        raise ValueError("too few finite bootstrap draws")
    draws.sort()
    a = (1.0 - level) / 2.0
    return BootstrapCI(statistic, f(x), _quantile(draws, a), _quantile(draws, 1.0 - a), level, float(mean_block),
                       n_resamples, seed)
