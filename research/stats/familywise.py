"""Family-wise error control: Holm step-down and Romano-Wolf bootstrap step-down. Standard library only.

References:
* Holm, S. (1979), "A simple sequentially rejective multiple test procedure", Scand. J. Statist. 6: 65-70.
* Romano, J. P. and Wolf, M. (2005), "Stepwise multiple testing as formalized data snooping", Econometrica 73(4);
  Romano, J. P. and Wolf, M. (2016), "Efficient computation of adjusted p-values for resampling-based stepdown
  multiple testing", Statist. Probab. Lett. 113: 38-40 (the adjusted p-value algorithm used here).

The roadmap pairs them: Romano-Wolf is the primary family-wise adjustment, Holm the check (§1.4 c, §5.4).
"""
import random
from dataclasses import dataclass
from math import isfinite, sqrt


def _pvalues(ps):
    ps = list(ps)
    if not ps:
        raise ValueError("need at least one p-value")
    for p in ps:
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not isfinite(p) or not 0.0 <= p <= 1.0:
            raise ValueError("p-values must be finite numbers in [0, 1]")
    return [float(p) for p in ps]


def holm_adjust(pvalues) -> list:
    """Holm-adjusted p-values, in the input order: p_(i) * (m - i + 1), made monotone and capped at 1."""
    ps = _pvalues(pvalues)
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * ps[i]))
        adj[i] = running
    return adj


def holm_reject(pvalues, alpha) -> list:
    """True where the hypothesis is rejected at family-wise level ``alpha`` by Holm's procedure."""
    alpha = float(alpha)
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    return [p <= alpha for p in holm_adjust(pvalues)]


@dataclass(frozen=True)
class RomanoWolfResult:
    t_stats: tuple          # studentized mean per hypothesis, input order
    adjusted_p: tuple       # Romano-Wolf step-down adjusted p-values, input order
    n_boot: int
    seed: int
    block_length: int

    def rejected(self, alpha) -> list:
        return [p <= float(alpha) for p in self.adjusted_p]


def _mean_sd(xs):
    n = len(xs)
    mu = sum(xs) / n
    var = sum((x - mu) ** 2 for x in xs) / (n - 1)
    return mu, sqrt(var)


def _circular_block_indices(rng, n, block_length):
    out = []
    while len(out) < n:
        start = rng.randrange(n)
        out.extend((start + j) % n for j in range(block_length))
    return out[:n]


def romano_wolf_stepdown(series, *, n_boot=1000, seed, block_length=1) -> RomanoWolfResult:
    """One-sided (H1: mean > 0) Romano-Wolf step-down over K paired series of equal length T.

    ``series[k][t]`` is hypothesis k's observation in period t (e.g. a daily net active return). All series are
    resampled with the SAME time indices, so cross-hypothesis dependence is kept; ``block_length`` > 1 uses the
    circular block bootstrap for serial dependence. ``seed`` is mandatory, so every result is reproducible.
    Statistic t_k = sqrt(T) mean_k / sd_k; bootstrap statistics are centred at the sample mean and studentized.
    Adjusted p-values use the (1 + count) / (1 + B) convention, so they are never zero."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an int")
    if isinstance(n_boot, bool) or not isinstance(n_boot, int) or n_boot < 1:
        raise ValueError("n_boot must be an int >= 1")
    if isinstance(block_length, bool) or not isinstance(block_length, int) or block_length < 1:
        raise ValueError("block_length must be an int >= 1")
    data = [[float(x) for x in s] for s in series]
    if not data:
        raise ValueError("need at least one series")
    t_len = len(data[0])
    if t_len < 3 or any(len(s) != t_len for s in data):
        raise ValueError("series must share one length >= 3")
    if any(not isfinite(x) for s in data for x in s):
        raise ValueError("observations must be finite")
    if block_length > t_len:
        raise ValueError("block_length must not exceed the series length")

    k = len(data)
    root_t = sqrt(t_len)
    stats = []
    means = []
    for s in data:
        mu, sd = _mean_sd(s)
        if sd <= 0:
            raise ValueError("a series has zero variance")
        means.append(mu)
        stats.append(root_t * mu / sd)

    rng = random.Random(seed)
    boot = []                                   # boot[b][k] centred, studentized bootstrap statistic
    for _ in range(n_boot):
        idx = _circular_block_indices(rng, t_len, block_length)
        row = []
        for j in range(k):
            s = data[j]
            mu_b, sd_b = _mean_sd([s[i] for i in idx])
            row.append(root_t * (mu_b - means[j]) / sd_b if sd_b > 0 else 0.0)
        boot.append(row)

    order = sorted(range(k), key=lambda j: -stats[j])
    adj = [1.0] * k
    previous = 0.0
    for step, j in enumerate(order):
        remaining = order[step:]
        exceed = sum(1 for row in boot if max(row[r] for r in remaining) >= stats[j])
        p = (1 + exceed) / (1 + n_boot)
        previous = max(previous, p)
        adj[j] = previous
    return RomanoWolfResult(tuple(stats), tuple(adj), n_boot, seed, block_length)
