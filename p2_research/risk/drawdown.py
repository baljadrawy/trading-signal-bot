"""Drawdown engine (RM0-DD 1.0.0). Synthetic equity paths only: RM0 never manufactures a strategy equity curve.

Input: ``{"provenance": "SYNTHETIC_TEST_PATH", "points": [(t_ms, equity, available_at_ms), ...]}``. Every point must
be known at the snapshot time (t_ms <= T and available_at_ms <= T) or the whole curve is refused (PITViolation).
"""
from __future__ import annotations

from ..execution.market_state import PITViolation
from . import values as V

ACCEPTED_PROVENANCE = ("SYNTHETIC_TEST_PATH",)
DAY_MS = 86_400_000
METRICS = ("current_drawdown", "max_drawdown", "current_underwater_ms", "max_underwater_ms", "recovery_time_ms",
           "drawdown_velocity_per_day", "peak_equity", "last_equity")


class DrawdownInputError(ValueError):
    pass


def _absent(reason: str, state=V.ST_UNAVAILABLE) -> dict:
    return {k: V.na(reason, state) for k in METRICS}


def validate_curve(curve, snapshot_time_ms: int) -> list:
    if not isinstance(curve, dict) or curve.get("provenance") not in ACCEPTED_PROVENANCE:
        raise DrawdownInputError(f"equity curve provenance must be one of {ACCEPTED_PROVENANCE} (no strategy / Paper curves)")
    pts = curve.get("points")
    if not isinstance(pts, (list, tuple)):
        raise DrawdownInputError("points must be a list")
    out, last = [], None
    for x in pts:
        if not isinstance(x, (list, tuple)) or len(x) != 3:
            raise DrawdownInputError("each point is (t_ms, equity, available_at_ms)")
        t, e, a = x
        if isinstance(t, bool) or not isinstance(t, int) or isinstance(a, bool) or not isinstance(a, int):
            raise DrawdownInputError("t_ms and available_at_ms must be ints")
        if isinstance(e, bool) or not isinstance(e, (int, float)) or e != e or e in (float("inf"), float("-inf")) or e <= 0:
            raise DrawdownInputError(f"equity must be finite and > 0, got {e!r}")
        if a < t:
            raise DrawdownInputError("available_at_ms must be >= t_ms")
        if t > snapshot_time_ms or a > snapshot_time_ms:
            raise PITViolation(f"equity point t={t} available={a} is after the snapshot time {snapshot_time_ms}")
        if last is not None and t <= last:
            raise DrawdownInputError("points must be strictly increasing in t_ms")
        last = t
        out.append((t, float(e)))
    return out


def drawdown(curve, snapshot_time_ms: int) -> dict:
    if curve is None:
        return _absent("no_equity_curve_supplied")
    pts = validate_curve(curve, snapshot_time_ms)
    if len(pts) < 2:
        return _absent(f"insufficient_history:{len(pts)}<2", V.INSUFFICIENT_HISTORY)
    peak, peak_t = pts[0][1], pts[0][0]
    max_dd, mdd_peak_t, mdd_trough_t, mdd_peak = 0.0, None, None, None
    uw_start, max_uw, censored = None, 0, False
    for t, e in pts:
        if e >= peak:
            if uw_start is not None:
                max_uw = max(max_uw, t - uw_start)
                uw_start = None
            peak, peak_t = e, t
            continue
        if uw_start is None:
            uw_start = peak_t
        dd = 1 - e / peak
        if dd > max_dd:
            max_dd, mdd_peak_t, mdd_trough_t, mdd_peak = dd, peak_t, t, peak
    t_last, e_last = pts[-1]
    cur_dd = 1 - e_last / peak
    cur_uw = (t_last - uw_start) if uw_start is not None else 0
    if uw_start is not None:
        max_uw = max(max_uw, cur_uw)
        censored = True
    out = {"peak_equity": V.mv(peak, V.DERIVED), "last_equity": V.mv(e_last, V.DERIVED),
           "current_drawdown": V.mv(cur_dd, V.DERIVED), "max_drawdown": V.mv(max_dd, V.DERIVED),
           "current_underwater_ms": V.mv(cur_uw, V.DERIVED),
           "max_underwater_ms": V.mv(max_uw, V.DERIVED, flags=("underwater_censored_at_last_point",) if censored else ())}
    if mdd_trough_t is None:
        out["recovery_time_ms"] = V.na("no_drawdown_on_curve")
        out["drawdown_velocity_per_day"] = V.na("no_drawdown_on_curve")
        return out
    rec = next((t for t, e in pts if t > mdd_trough_t and e >= mdd_peak), None)
    out["recovery_time_ms"] = (V.mv(rec - mdd_trough_t, V.DERIVED) if rec is not None
                               else V.na("not_recovered_by_snapshot_time"))
    span = [t for t, _ in pts if mdd_peak_t <= t <= mdd_trough_t]
    if len(span) >= 3 and mdd_trough_t > mdd_peak_t:
        out["drawdown_velocity_per_day"] = V.mv(max_dd / ((mdd_trough_t - mdd_peak_t) / DAY_MS), V.DERIVED)
    else:
        out["drawdown_velocity_per_day"] = V.na("fewer_than_3_points_peak_to_trough")
    return out
