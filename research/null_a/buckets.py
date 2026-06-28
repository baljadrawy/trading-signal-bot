"""Conditioning buckets for the matched Null-A sampler.

Matching on symbol+timeframe alone makes the null too weak: if signals cluster in
high-volatility / strong-trend / US-session / volume-expansion, a random entry from a
quiet market is an easier benchmark than the strategy faced. So we bucket on regime,
volatility, liquidity, time-of-day and holding-period and match within buckets.
"""
import numpy as np


class Bucketer:
    """Quantile bucketer fit on the candidate pool, so 'high vol' means high relative
    to the market we actually sample the null from."""

    def __init__(self, edges):
        self.edges = np.asarray(edges, float)

    @classmethod
    def fit(cls, values, n: int = 3):
        v = np.asarray(values, float)
        v = v[~np.isnan(v)]
        qs = np.linspace(0, 1, n + 1)[1:-1]
        edges = np.quantile(v, qs) if v.size else np.array([])
        return cls(edges)

    def assign(self, value) -> int:
        if self.edges.size == 0:
            return 0
        return int(np.searchsorted(self.edges, value, side="right"))


def time_of_day_bucket(ts_epoch_seconds) -> str:
    """Coarse session bucket from a UTC epoch timestamp."""
    h = int((ts_epoch_seconds // 3600) % 24)
    if 0 <= h < 7:
        return "asia"
    if 7 <= h < 13:
        return "europe"
    return "us"
