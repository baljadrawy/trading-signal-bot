"""Decision-time signal rules (s4-mech-v1).

Every rule is a callable ``rule(past, t) -> {asset: weight}``. ``past[asset]`` is a read-only view of
closes up to and including day ``t`` (``simulate.run`` passes a view that cannot index the future).
The weight is held from close ``t`` to close ``t + 1``.

Parameters have **no defaults**: each must be declared from literature or a frozen spec, never
tuned here. Weights sum to at most 1 in absolute value (no leverage); the remainder is cash.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


class SignalError(ValueError):
    """Invalid parameters or price history."""


def _price(x, asset) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise SignalError(f"{asset}: non-numeric price")
    v = float(x)
    if not math.isfinite(v) or v <= 0:
        raise SignalError(f"{asset}: price must be finite and > 0")
    return v


def _int(v, name, lo):
    if isinstance(v, bool) or not isinstance(v, int) or v < lo:
        raise SignalError(f"{name} must be an int >= {lo}")
    return v


def trailing_return(series, lookback: int, asset="?") -> float | None:
    """close[t] / close[t - lookback] - 1, or None with insufficient history."""
    if len(series) <= lookback:
        return None
    return _price(series[-1], asset) / _price(series[-1 - lookback], asset) - 1.0


def realized_vol(series, window: int, asset="?") -> float | None:
    """Sample standard deviation of the last ``window`` daily simple returns (not annualized)."""
    if len(series) <= window:
        return None
    px = [_price(series[-1 - i], asset) for i in range(window, -1, -1)]
    r = [px[i + 1] / px[i] - 1.0 for i in range(window)]
    m = sum(r) / window
    return math.sqrt(sum((x - m) ** 2 for x in r) / (window - 1)) if window > 1 else None


@dataclass(frozen=True)
class TimeSeriesMomentum:
    """Per asset: long if its own trailing return is positive; short if negative and shorting is
    allowed; otherwise flat. Equal risk budget 1/N per asset in the universe. Optional volatility
    scaling: |w| = min(1, target_daily_vol / realized_vol) / N."""
    lookback: int
    long_only: bool
    vol_window: int | None
    target_daily_vol: float | None

    def __post_init__(self):
        _int(self.lookback, "lookback", 1)
        if not isinstance(self.long_only, bool):
            raise SignalError("long_only must be a bool")
        if (self.vol_window is None) != (self.target_daily_vol is None):
            raise SignalError("vol_window and target_daily_vol are declared together or not at all")
        if self.vol_window is not None:
            _int(self.vol_window, "vol_window", 2)
            t = self.target_daily_vol
            if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t <= 0:
                raise SignalError("target_daily_vol must be finite and > 0")

    def __call__(self, past, t) -> dict:
        n = len(past)
        if n == 0:
            return {}
        w = {}
        for asset, series in past.items():
            r = trailing_return(series, self.lookback, asset)
            if r is None or r == 0:
                continue
            side = 1.0 if r > 0 else (0.0 if self.long_only else -1.0)
            if side == 0.0:
                continue
            scale = 1.0
            if self.vol_window is not None:
                vol = realized_vol(series, self.vol_window, asset)
                if vol is None or vol == 0:
                    continue
                scale = min(1.0, self.target_daily_vol / vol)
            w[asset] = side * scale / n
        return w


@dataclass(frozen=True)
class CrossSectionalMomentum:
    """Rank assets with full history by trailing return. Long-only: equal weight 1/k on the top k.
    Long/short: +1/(2k) on the top k and -1/(2k) on the bottom k (dollar-neutral). Ties are broken
    by asset name so the rule is deterministic."""
    lookback: int
    top_k: int
    long_only: bool

    def __post_init__(self):
        _int(self.lookback, "lookback", 1)
        _int(self.top_k, "top_k", 1)
        if not isinstance(self.long_only, bool):
            raise SignalError("long_only must be a bool")

    def __call__(self, past, t) -> dict:
        scored = []
        for asset, series in past.items():
            r = trailing_return(series, self.lookback, asset)
            if r is not None:
                scored.append((r, asset))
        need = self.top_k if self.long_only else 2 * self.top_k
        if len(scored) < need:
            return {}
        scored.sort(key=lambda x: (-x[0], x[1]))
        if self.long_only:
            return {a: 1.0 / self.top_k for _, a in scored[:self.top_k]}
        w = {a: 0.5 / self.top_k for _, a in scored[:self.top_k]}
        w.update({a: -0.5 / self.top_k for _, a in scored[-self.top_k:]})
        return w
