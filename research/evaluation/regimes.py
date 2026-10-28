"""Causal market-regime labels for research (a45g-rg-v1). Research only; production never imports it.

The production classifier ``shared/regime.classify_regime`` labels one indicator frame (per symbol and
timeframe). This module answers a different research need (A45 H1 / W6, roadmap S1 "regime-dependence"):
a *series* of regime labels for a reference market (for example BTC closes) that can be joined to trades
without look-ahead, so a trade population can be stratified by market state.

No look-ahead, by construction
------------------------------
* ``closed_bars`` keeps only bars whose close time is strictly before the decision instant (the same
  rule as production ``close_time < now``).
* The label at bar t uses closes[0..t] only: trend = sign of the ``trend_lookback``-bar return; volatility
  = realised volatility of the last ``vol_window`` log returns ranked against the ``vol_rank_window``
  *previous* realised-volatility values (strict rank, current value excluded from its own reference).
* The confirmation (hysteresis) filter is a left-to-right state machine: a new label is adopted only after
  it has been the raw label for ``confirm_bars`` consecutive bars. It reduces label switching (and so the
  turnover of any regime-gated rule) at the price of detection delay.
* Prefix invariance holds: ``labels(closes[:k]) == labels(closes)[:k]`` for every k (asserted by tests).
* ``label_as_of`` joins a trade to the last bar that closed strictly before its decision time.

Parameters have **no defaults**: they must come from a frozen spec or literature, never be tuned here.
Labels are descriptive conditioning variables, not signals, and imply nothing about returns.
"""
from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

VERSION = "a45g-rg-v1"
TRENDS = ("up", "down", "flat")
VOLS = ("normal_vol", "high_vol")


class RegimeError(ValueError):
    """Invalid parameters or bars."""


def _int(v, name, lo):
    if isinstance(v, bool) or not isinstance(v, int) or v < lo:
        raise RegimeError(f"{name} must be an int >= {lo}")
    return v


def _closes(closes) -> list:
    out = []
    for x in closes:
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0:
            raise RegimeError("closes must be finite and > 0")
        out.append(float(x))
    return out


def closed_bars(close_times: Sequence[float], closes: Sequence[float], as_of: float) -> tuple[list, list]:
    """Prefix of strictly increasing bars with ``close_time < as_of`` (incomplete bars excluded)."""
    if len(close_times) != len(closes):
        raise RegimeError("close_times and closes must be aligned")
    ts = []
    for x in close_times:
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
            raise RegimeError("close_times must be finite numbers")
        ts.append(float(x))
    if any(b <= a for a, b in zip(ts, ts[1:])):
        raise RegimeError("close_times must be strictly increasing (no duplicates, no reordering)")
    cs = _closes(closes)
    k = bisect.bisect_left(ts, float(as_of))
    return ts[:k], cs[:k]


def trend_of(label: str | None) -> str | None:
    return None if label is None else label.split("|", 1)[0]


def vol_of(label: str | None) -> str | None:
    return None if label is None else label.split("|", 1)[1]


@dataclass(frozen=True)
class TrendVolRegime:
    trend_lookback: int
    vol_window: int
    vol_rank_window: int
    high_vol_quantile: float
    confirm_bars: int

    def __post_init__(self):
        _int(self.trend_lookback, "trend_lookback", 1)
        _int(self.vol_window, "vol_window", 2)
        _int(self.vol_rank_window, "vol_rank_window", 1)
        _int(self.confirm_bars, "confirm_bars", 1)
        q = self.high_vol_quantile
        if isinstance(q, bool) or not isinstance(q, (int, float)) or not 0 < q < 1:
            raise RegimeError("high_vol_quantile must be in (0, 1)")

    @property
    def warmup(self) -> int:
        """Index of the first bar that can carry a raw label."""
        return max(self.trend_lookback, self.vol_window + self.vol_rank_window)

    def _vols(self, cs):
        lr = [math.log(cs[i] / cs[i - 1]) for i in range(1, len(cs))]
        w = self.vol_window
        vols = [None] * len(cs)
        for t in range(w, len(cs)):
            win = lr[t - w:t]                       # log returns ending at bar t (lr[i-1] is bar i)
            m = sum(win) / w
            vols[t] = math.sqrt(sum((x - m) ** 2 for x in win) / (w - 1))
        return vols

    def raw_labels(self, closes: Sequence[float]) -> list:
        cs = _closes(closes)
        vols = self._vols(cs)
        out = [None] * len(cs)
        for t in range(self.warmup, len(cs)):
            r = cs[t] / cs[t - self.trend_lookback] - 1.0
            trend = "up" if r > 0 else ("down" if r < 0 else "flat")
            ref = vols[t - self.vol_rank_window:t]
            pct = sum(v < vols[t] for v in ref) / len(ref)
            out[t] = f"{trend}|{'high_vol' if pct > self.high_vol_quantile else 'normal_vol'}"
        return out

    def labels(self, closes: Sequence[float]) -> list:
        """Confirmed labels (None until the first label has persisted ``confirm_bars`` bars)."""
        out, confirmed, cand, run = [], None, None, 0
        for raw in self.raw_labels(closes):
            if raw is None:
                out.append(None)
                continue
            if raw == cand:
                run += 1
            else:
                cand, run = raw, 1
            if run >= self.confirm_bars and cand != confirmed:
                confirmed = cand
            out.append(confirmed)
        return out


def switch_count(labels: Sequence) -> int:
    """Number of label changes after the first labelled bar (a proxy for regime-gate turnover)."""
    seen = [x for x in labels if x is not None]
    return sum(a != b for a, b in zip(seen, seen[1:]))


def label_as_of(close_times: Sequence[float], labels: Sequence, decision_ts: float):
    """Label of the last bar with ``close_time < decision_ts``; None if no such bar or still warming up."""
    if len(close_times) != len(labels):
        raise RegimeError("close_times and labels must be aligned")
    i = bisect.bisect_left(list(close_times), float(decision_ts)) - 1
    return labels[i] if i >= 0 else None


def attach_regimes(trades, close_times: Sequence[float], labels: Sequence, *, part: str = "label") -> list:
    """Copy of each trade record with ``regime`` set from the as-of label at its ``entry_ts``.
    ``part``: 'label' (full), 'trend' or 'vol'."""
    pick = {"label": lambda x: x, "trend": trend_of, "vol": vol_of}
    if part not in pick:
        raise RegimeError("part must be 'label', 'trend' or 'vol'")
    return [replace(t, regime=pick[part](label_as_of(close_times, labels, t.entry_ts))) for t in trades]
