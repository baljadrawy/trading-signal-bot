"""PIT return series and second moments (RM0-RET, RM0-VOL, RM0-CORR, RM0-BTC beta, RM0-COV). Deterministic: every
sum is ``math.fsum`` (correctly rounded, order independent); returns are keyed by bar open time; no bridging.
"""
from __future__ import annotations

import math

from . import values as V


class Series:
    """15m log returns of one symbol over the declared window ending at the last bar closed by T."""

    def __init__(self, sym: str, n: int, rets: dict, expected: int, stale: bool, gap: bool, clock_suspect: bool,
                 w3_masked: int, invalid_close: int):
        self.sym, self.n_window, self.rets = sym, n, rets
        self.expected, self.stale, self.gap, self.clock_suspect = expected, stale, gap, clock_suspect
        self.w3_masked, self.invalid_close = w3_masked, invalid_close

    @property
    def present(self) -> int:
        return len(self.rets)

    def state(self, min_obs: int) -> tuple:
        """(state, reason or None, flags) for a statistic needing ``min_obs`` returns."""
        flags = set()
        if self.w3_masked:
            flags.add("w3_masked_history")
        if self.invalid_close:
            flags.add("invalid_close_skipped")
        if self.stale:
            flags.add(V.STALE_INPUT)
        if self.gap:
            flags.add(V.GAP_AFFECTED)
        if self.clock_suspect:
            flags.add(V.DEGRADED_INPUT)
        if self.present < min_obs:
            return V.INSUFFICIENT_HISTORY, f"insufficient_history:{self.present}<{min_obs}", flags
        return V.worst(*(f for f in flags if f in V.STATE_RANK)), None, flags


def last_closed_open(t_ms: int, bar_ms: int) -> int:
    """Open of the last bar closed by T: open + bar_ms - 1 < T  <=>  open <= T - bar_ms."""
    return ((t_ms - bar_ms) // bar_ms) * bar_ms


def series(view, sym: str, n: int, bar_ms: int, tf: str = "15m") -> Series:
    E = last_closed_open(view.T, bar_ms)
    lo = E - n * bar_ms
    bars, masked = view.closed_candles(sym, tf, lo, E)
    rets, invalid = {}, 0
    for j in range(n):
        o = E - (n - 1 - j) * bar_ms
        a, b = bars.get(o - bar_ms), bars.get(o)
        if a is None or b is None:
            continue
        if not (a[4] > 0 and b[4] > 0):
            invalid += 1
            continue
        rets[o] = math.log(b[4] / a[4])
    present = sorted(bars)
    gap = bool(present) and any(o not in bars for o in range(present[0], present[-1] + 1, bar_ms))
    cs = any(bars[o][9] for o in bars)
    return Series(sym, n, rets, n, stale=E not in bars, gap=gap, clock_suspect=cs, w3_masked=masked,
                  invalid_close=invalid)


def mean(xs) -> float:
    return math.fsum(xs) / len(xs)


def stdev(xs) -> float | None:
    if len(xs) < 2:
        return None
    m = mean(xs)
    return math.sqrt(math.fsum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def aligned(a: dict, b: dict) -> tuple:
    ks = sorted(set(a) & set(b))
    return [a[k] for k in ks], [b[k] for k in ks]


def cov(xs, ys) -> float:
    mx, my = mean(xs), mean(ys)
    return math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) - 1)


def pearson(xs, ys):
    """(r or None, reason)."""
    if len(xs) < 3:
        return None, "fewer_than_3_obs"
    mx, my = mean(xs), mean(ys)
    sxx = math.fsum((x - mx) ** 2 for x in xs)
    syy = math.fsum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None, "zero_variance"
    sxy = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys))
    r = sxy / math.sqrt(sxx * syy)
    return max(-1.0, min(1.0, r)), None


def fisher_ci95(r: float, n: int):
    if n <= 3 or abs(r) >= 1:
        return None
    z, h = math.atanh(r), 1.959963984540054 / math.sqrt(n - 3)
    return [math.tanh(z - h), math.tanh(z + h)]


def beta(xs, ys_ref):
    """(beta of xs on ys_ref or None, reason)."""
    if len(xs) < 3:
        return None, "fewer_than_3_obs"
    vr = cov(ys_ref, ys_ref)
    if vr == 0:
        return None, "zero_reference_variance"
    return cov(xs, ys_ref) / vr, None


def common_matrix(series_list: list) -> tuple:
    """(common bar opens, rows per series) where EVERY series has a return."""
    if not series_list:
        return [], []
    ks = set(series_list[0].rets)
    for s in series_list[1:]:
        ks &= set(s.rets)
    ks = sorted(ks)
    return ks, [[s.rets[k] for k in ks] for s in series_list]


def cov_matrix(rows: list) -> list:
    k = len(rows)
    return [[cov(rows[i], rows[j]) for j in range(k)] for i in range(k)]
