"""A45 deterministic synthetic OHLCV for the production setups (engineering properties only)."""
import numpy as np
import pandas as pd

STEP = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
T0 = 20_720 * 86_400_000


def frame(close, *, tf="15m", volume=None, wick=0.002, seed=0, upper=None, start=T0):
    """OHLCV frame indexed by Binance open time (UTC) with a close_time column, like prepare_ohlcv."""
    rng = np.random.default_rng(seed)
    close = np.asarray(close, dtype=float)
    open_ = np.r_[close[0], close[:-1]]
    hi = np.maximum(open_, close) * (1 + wick * rng.uniform(0.2, 1.0, len(close)))
    lo = np.minimum(open_, close) * (1 - wick * rng.uniform(0.2, 1.0, len(close)))
    if upper is not None:                                   # explicit upper wick on the last bar
        hi[-1] = close[-1] * (1 + upper)
    vol = np.full(len(close), 1_000.0) if volume is None else np.asarray(volume, dtype=float)
    opens = start + STEP[tf] * np.arange(len(close))
    idx = pd.DatetimeIndex(pd.to_datetime(opens, unit="ms", utc=True), name="open_time")
    return pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close, "volume": vol,
                         "close_time": opens + STEP[tf] - 1}, index=idx)


def trend(n=200, drift=0.004, noise=0.002, seed=1):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(drift + rng.normal(0, noise, n)))


def breakout(n=200, extension=0.012, vol_spike=3.0, seed=1, upper=None, drift=0.004):
    """Uptrend whose last bar closes `extension` above the prior 20-bar high on a volume spike."""
    c = trend(n, drift=drift, seed=seed)
    prior_high_proxy = c[-21:-1].max() * 1.0021            # above the synthetic wicks
    c[-1] = prior_high_proxy * (1 + extension)
    v = np.full(n, 1_000.0)
    v[-1] = 1_000.0 * vol_spike
    return frame(c, volume=v, seed=seed, upper=upper)


def sideways(n=200, seed=2):
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 0.001, n)
    noise[-40:] *= 0.5
    return frame(100 * (1 + 0.002 * np.sin(np.arange(n) / 2.0) + noise), seed=seed, wick=0.001)


def random_walk(n=200, seed=0):
    rng = np.random.default_rng(seed)
    drift = rng.choice([-0.003, 0.0, 0.003])
    c = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.004, n)))
    v = rng.lognormal(7, 0.4, n)
    if rng.random() < 0.5:
        v[-1] *= rng.uniform(1, 4)
    if rng.random() < 0.4:                                  # force a breakout attempt
        c[-1] = c[-21:-1].max() * rng.uniform(0.995, 1.03)
    return frame(c, volume=v, seed=seed, wick=0.003)
