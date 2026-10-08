"""MI-ML point-in-time timeline (contract MI-C v1.0, spec section 1.1). Pure, stdlib only, integer UTC milliseconds.

Terms: canonical bar end (close time), feature availability, forecast issuance, earliest actionable time, label
observation window. No candle is ever treated as available at its close. Any bar ending after the W3 freeze is a
hard failure for features AND labels.
"""
from __future__ import annotations

import datetime as dt
import math

MS = 1
S = 1000
MIN = 60 * S
H = 60 * MIN
D = 24 * H
TF_MS = {"15m": 15 * MIN, "1h": H, "4h": 4 * H, "1d": D}

DELTA_AVAIL_MS = {"15m": 120 * S, "1h": 120 * S, "4h": 120 * S, "1d": 300 * S}
DELTA_COMPUTE_MS = 60 * S
DELTA_ACT_MS = 60 * S
FREEZE_MS = int(dt.datetime(2026, 8, 19, 9, 33, 46, tzinfo=dt.timezone.utc).timestamp() * 1000)

T1_HORIZONS_MS = {"24h": 24 * H, "4h": 4 * H}
T2_LEVEL_BARS = 20
T2_LABEL_BARS = 6
T3_TARGET_DAYS = 7


class FreezeViolation(Exception):
    """A bar ending after the freeze was offered to a feature or a label (W3 / P2-B guard)."""


class PITViolation(Exception):
    pass


def ms(y, mo, d, h=0, mi=0, s=0) -> int:
    return int(dt.datetime(y, mo, d, h, mi, s, tzinfo=dt.timezone.utc).timestamp() * 1000)


# ---------------------------------------------------------------- canonical times
def canonical_end(open_ms: int, tf: str) -> int:
    if open_ms % TF_MS[tf]:
        raise PITViolation(f"misaligned {tf} open {open_ms}")
    return open_ms + TF_MS[tf]


def end_from_raw_close(raw_close: int, tf: str, unit: str) -> int:
    """Archive closes are end - 1 us (unit 'us'), REST closes end - 1 ms (unit 'ms'); both map to one canonical end."""
    if unit == "us":
        end = (raw_close + 1) // 1000
        if (raw_close + 1) % 1000:
            raise PITViolation("archive close is not end - 1 us")
    elif unit == "ms":
        end = raw_close + 1
    else:
        raise ValueError(unit)
    if end % TF_MS[tf]:
        raise PITViolation(f"close {raw_close}{unit} does not end a {tf} bar")
    return end


def check_freeze(end_ms: int) -> None:
    if end_ms > FREEZE_MS:
        raise FreezeViolation(f"bar ending {end_ms} > freeze {FREEZE_MS}")


def t_avail(end_ms: int, tf: str, scale: int = 1) -> int:
    return end_ms + scale * DELTA_AVAIL_MS[tf]


def t_issue(decision_end_ms: int, tf: str, scale: int = 1) -> int:
    return decision_end_ms + scale * (DELTA_AVAIL_MS[tf] + DELTA_COMPUTE_MS)


def t_act(decision_end_ms: int, tf: str, scale: int = 1) -> int:
    return t_issue(decision_end_ms, tf, scale) + scale * DELTA_ACT_MS


def feature_admissible(bar_end_ms: int, bar_tf: str, issue_ms: int, scale: int = 1) -> bool:
    check_freeze(bar_end_ms)
    return t_avail(bar_end_ms, bar_tf, scale) <= issue_ms


def admissible_bars(bars: list, issue_ms: int, scale: int = 1) -> list:
    """bars: [(end_ms, tf, arrived_ms or None)]. A bar is usable iff it is available by rule AND (when an arrival time
    is recorded) it actually arrived by issuance - late data is never back-filled into an earlier forecast."""
    out = []
    for end, tf, arrived in bars:
        if not feature_admissible(end, tf, issue_ms, scale):
            continue
        if arrived is not None and arrived > issue_ms:
            continue
        out.append((end, tf, arrived))
    return out


def ceil_to(x: int, step: int) -> int:
    return -(-x // step) * step


# ---------------------------------------------------------------- per-task windows
def t1_window(T: int, horizon: str = "24h", scale: int = 1) -> dict:
    """T = end of the 4h decision bar. Label = 15m bars with open in [ceil15(t_act), ceil15(t_act) + h)."""
    if T % TF_MS["4h"]:
        raise PITViolation("T1 decision time must be a 4h close")
    a = t_act(T, "4h", scale)
    start = ceil_to(a, TF_MS["15m"])
    return {"t_issue": t_issue(T, "4h", scale), "t_act": a, "label_open_from": start,
            "label_open_to_excl": start + T1_HORIZONS_MS[horizon], "label_end": start + T1_HORIZONS_MS[horizon],
            "reference": "close of the decision bar (reference price, NOT an executable entry price)"}


def t1_label_bar_ok(bar_open_ms: int, T: int, horizon: str = "24h", scale: int = 1) -> bool:
    w = t1_window(T, horizon, scale)
    check_freeze(canonical_end(bar_open_ms, "15m"))
    return w["label_open_from"] <= bar_open_ms < w["label_open_to_excl"]


def t2_level_bar_ends(T: int) -> list:
    """Ends of the 20 bars BEFORE the breakout (decision) bar ending at T; the breakout bar is excluded."""
    return [T - k * TF_MS["4h"] for k in range(1, T2_LEVEL_BARS + 1)]


def t2_label_close_ends(T: int, scale: int = 1) -> list:
    """Closes of bars t+1..t+6 that are observed after t_act; the breakout bar's own close is never a label."""
    a = t_act(T, "4h", scale)
    ends = [T + k * TF_MS["4h"] for k in range(1, T2_LABEL_BARS + 1)]
    for e in ends:
        check_freeze(e)
    return [e for e in ends if e > a]


def t2_window(T: int, scale: int = 1) -> dict:
    ends = t2_label_close_ends(T, scale)
    return {"t_issue": t_issue(T, "4h", scale), "t_act": t_act(T, "4h", scale), "label_close_ends": ends,
            "label_end": max(ends)}


def t3_window(day_open_ms: int, scale: int = 1) -> dict:
    """Decision bar = 1d bar of day d (end = d+1 00:00). Target R_{d+7} uses 1d bars ending <= end(d+7)."""
    end = canonical_end(day_open_ms, "1d")
    tgt_end = end + T3_TARGET_DAYS * D
    check_freeze(tgt_end)
    return {"t_issue": t_issue(end, "1d", scale), "t_act": t_act(end, "1d", scale), "decision_end": end,
            "label_end": tgt_end}


def universe_cutoff(month_start_ms: int) -> int:
    """Universe membership for a month uses only bars available at or before the month start."""
    return month_start_ms


def label_end(task: str, decision_time: int) -> int:
    if task == "T1":
        return t1_window(decision_time)["label_end"]
    if task == "T2":
        return t2_window(decision_time)["label_end"]
    if task == "T3":
        return t3_window(decision_time - D)["label_end"]
    raise ValueError(task)


def last_close_return(closes: list) -> float:
    """Tiny reference feature used by the shift canary."""
    return math.log(closes[-1] / closes[-2])
