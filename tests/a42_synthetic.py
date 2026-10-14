"""A42 deterministic synthetic market fixtures (engineering properties only — not evidence of edge)."""
import numpy as np
import pandas as pd

BAR_MS = {"15m": 900_000, "4h": 14_400_000, "1d": 86_400_000}
START_MS = 1_790_000_000_000


def _frame(close, *, seed, wick=0.002, volume=None, timeframe="15m"):
    rng = np.random.default_rng(seed)
    close = np.asarray(close, dtype=float)
    open_ = np.r_[close[0], close[:-1]]
    body_hi, body_lo = np.maximum(open_, close), np.minimum(open_, close)
    high = body_hi * (1 + wick * rng.uniform(0.2, 1.0, len(close)))
    low = body_lo * (1 - wick * rng.uniform(0.2, 1.0, len(close)))
    vol = np.full(len(close), 1_000.0) if volume is None else np.asarray(volume, dtype=float)
    idx = START_MS + BAR_MS[timeframe] * np.arange(len(close))
    return pd.DataFrame({"open_time": idx, "open": open_, "high": high, "low": low,
                         "close": close, "volume": vol})


def strong_trend(n=320, seed=1, drift=0.004):
    """Steady uptrend; the last bar breaks the prior 20-bar high on 3× volume."""
    rng = np.random.default_rng(seed)
    steps = drift + rng.normal(0, 0.002, n)
    close = 100 * np.exp(np.cumsum(steps))
    close[-1] = close[-21:-1].max() * 1.012
    vol = np.full(n, 1_000.0); vol[-1] = 3_000.0
    return _frame(close, seed=seed, volume=vol)


def sideways(n=320, seed=2):
    """Range-bound oscillation that ends calm (low ADX, low volatility percentile)."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 0.001, n); noise[-40:] *= 0.5
    close = 100 * (1 + 0.002 * np.sin(np.arange(n) / 2.0) + noise)
    return _frame(close, seed=seed, wick=0.001)


def volatility_spike(n=320, seed=3):
    """Calm series, then eight whipsaw bars of ±4 % (no direction, extreme ATR)."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 0.002, n); steps[-8:] = 0.04 * np.array([1, -1] * 4)
    return _frame(100 * np.exp(np.cumsum(steps)), seed=seed, wick=0.02)


def correlated_pair(n=400, seed=4, beta=1.5, idio=0.002):
    """(btc_closes, alt_closes) with alt log-return = beta × btc + noise."""
    rng = np.random.default_rng(seed)
    btc_r = rng.normal(0, 0.004, n)
    alt_r = beta * btc_r + rng.normal(0, idio, n)
    return list(100 * np.exp(np.cumsum(btc_r))), list(10 * np.exp(np.cumsum(alt_r)))
