"""Conditional Null-A: random entries matched to the strategy's bucket profile.

NOT random(timestamp, symbol) — but conditional_random(same_regime, same_volatility,
same_liquidity, same_time_of_day, same_holding_period). The exit is simulated by an
injected `exit_fn` (in production: the live triple_barrier exit on historical klines).
"""
from collections import defaultdict
import numpy as np

from .buckets import Bucketer

NUMERIC_DIMS = {"volatility", "liquidity", "holding_period"}


def _is_numeric(v):
    return isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool)


def _build_key_fn(pool, match_on, n_bins):
    bucketers = {}
    for dim in match_on:
        if pool and _is_numeric(pool[0].get(dim)):
            bucketers[dim] = Bucketer.fit([c[dim] for c in pool], n=n_bins)

    def key(item):
        k = []
        for dim in match_on:
            v = item.get(dim)
            k.append(bucketers[dim].assign(v) if dim in bucketers else v)
        return tuple(k)

    return key


def generate_conditional_null(real, pool, match_on, rng, n_bins: int = 3,
                              exit_fn=None, return_selected: bool = False):
    """For each real signal, sample a random pool entry sharing its bucket profile and
    record the entry's realised return via exit_fn. Returns null returns (+ selected
    candidates and an unmatched count when return_selected=True)."""
    exit_fn = exit_fn or (lambda c: c["future_return"])
    key = _build_key_fn(pool, match_on, n_bins)
    by_key = defaultdict(list)
    for c in pool:
        by_key[key(c)].append(c)

    null_returns, selected, unmatched = [], [], 0
    for r in real:
        cands = by_key.get(key(r))
        if not cands:
            unmatched += 1
            continue
        c = cands[int(rng.integers(len(cands)))]
        selected.append(c)
        null_returns.append(float(exit_fn(c)))

    if return_selected:
        return null_returns, selected, unmatched
    return null_returns


def signal_profile(items) -> dict:
    """Summarise a set of signals/candidates: mean volatility/holding + regime mix."""
    def m(dim):
        vals = [x[dim] for x in items if dim in x and x[dim] is not None]
        return float(np.mean(vals)) if vals else float("nan")
    regimes = [x["regime"] for x in items if "regime" in x]
    rdist = {}
    for r in regimes:
        rdist[r] = rdist.get(r, 0) + 1
    n = len(regimes) or 1
    rdist = {k: v / n for k, v in rdist.items()}
    return {"volatility_mean": m("volatility"), "holding_period_mean": m("holding_period"),
            "regime_dist": rdist, "n": len(items)}
