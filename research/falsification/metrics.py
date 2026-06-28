"""Core metric primitives shared across the falsification battery."""
import numpy as np


def profit_factor(returns) -> float:
    r = np.asarray(returns, float)
    g = r[r > 0].sum()
    los = -r[r < 0].sum()
    if los == 0:
        return float("inf") if g > 0 else float("nan")
    return float(g / los)


def sharpe(returns, periods_per_year: float = 365.0) -> float:
    r = np.asarray(returns, float)
    if r.size < 2 or r.std(ddof=1) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=1) * np.sqrt(periods_per_year))


def cohens_d(a, b) -> float:
    a = np.asarray(a, float); b = np.asarray(b, float)
    na, nb = a.size, b.size
    if na < 2 or nb < 2:
        return float("nan")
    sp = np.sqrt(((na - 1) * a.var(ddof=1) + (nb - 1) * b.var(ddof=1)) / (na + nb - 2))
    return float((a.mean() - b.mean()) / sp) if sp > 0 else float("nan")


def information_ratio(strat, benchmark, periods_per_year: float = 365.0) -> float:
    """IR of strategy vs an aligned per-trade/per-period benchmark."""
    s = np.asarray(strat, float); b = np.asarray(benchmark, float)
    n = min(s.size, b.size)
    if n < 2:
        return float("nan")
    d = s[:n] - b[:n]
    if d.std(ddof=1) == 0:
        return float("nan")
    return float(d.mean() / d.std(ddof=1) * np.sqrt(periods_per_year))


def max_drawdown(equity) -> float:
    e = np.asarray(equity, float)
    if e.size < 2:
        return float("nan")
    peak = np.maximum.accumulate(e)
    return float((e / peak - 1).min())
