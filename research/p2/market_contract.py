"""P2-B market-data contract: W2 window, freeze guard, Binance source identities, request planning.

Pure stdlib. The freeze guard is the single source of truth for "may this candle exist in P2 data":
a candle is admissible only if its close_time is strictly before the freeze. Archives that physically contain any
post-freeze candle (the 2026-08 monthly file, the 2026-08-19 daily file) are never planned; the partial freeze day
is taken from the public REST endpoint with an endTime that cannot return a candle closing at/after the freeze.
"""
from __future__ import annotations

import datetime as dt

from . import contract as C

MARKET_CONTRACT_VERSION = "p2b-market-v1"
W2_START_UTC = "2026-06-01T00:00:00Z"
W2_START_MS = C._ms(W2_START_UTC)
FREEZE_MS = C.FREEZE_MS
TIMEFRAMES = ("15m", "1h", "4h", "1d")
TF_MS = C.TF_MS
LOOKBACK_BARS = 200          # analyzer CANDLES_TO_FETCH (closed candles) incl. the decision candle
LOOKBACK_MARGIN_BARS = 2     # alternative (ambiguous) decision candle + 1
ARCHIVE_BASE = "https://data.binance.vision/data/spot"
REST_URL = "https://api.binance.com/api/v3/klines"

CANDLE_KEY_FMT = "{symbol}|{timeframe}|{open_ms}"     # identical to P1 Evidence V2 candle_id


class FreezeViolation(Exception):
    """Raised whenever a candle closing at/after the freeze is about to be admitted (fail closed)."""


def assert_closed_before_freeze(close_time_ms: int, open_time_ms: int, timeframe: str) -> None:
    tf = TF_MS[timeframe]
    if close_time_ms >= FREEZE_MS:
        raise FreezeViolation(f"close_time {close_time_ms} >= freeze {FREEZE_MS}")
    if not (open_time_ms < close_time_ms < open_time_ms + tf):
        raise ValueError("close_time outside its candle")


def last_admissible_open_ms(timeframe: str) -> int:
    """Largest tf-aligned open whose candle closes (open + tf - 1ms/us) strictly before the freeze."""
    tf = TF_MS[timeframe]
    return ((FREEZE_MS - tf) // tf) * tf


def _d(ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)


def month_starts(start_ms: int, end_ms_exclusive: int) -> list:
    d = _d(start_ms).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    out = []
    while int(d.timestamp() * 1000) < end_ms_exclusive:
        out.append(d.strftime("%Y-%m"))
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return out


def archive_is_pre_freeze(kind: str, period: str) -> bool:
    """True only if every candle the archive can contain closes strictly before the freeze."""
    if kind == "monthly":
        start = dt.datetime.strptime(period + "-01", "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    elif kind == "daily":
        start = dt.datetime.strptime(period, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        end = start + dt.timedelta(days=1)
    else:
        raise ValueError(kind)
    return int(end.timestamp() * 1000) <= FREEZE_MS     # last close = end - 1 unit < freeze


def archive_url(kind: str, symbol: str, timeframe: str, period: str) -> str:
    if not archive_is_pre_freeze(kind, period):
        raise FreezeViolation(f"archive {kind} {period} can contain post-freeze candles")
    return f"{ARCHIVE_BASE}/{kind}/klines/{symbol}/{timeframe}/{symbol}-{timeframe}-{period}.zip"


def w2_requests(symbol: str, timeframe: str) -> list:
    """Archive + REST requests covering [W2 start, freeze) without any post-freeze archive."""
    reqs = [("monthly", p) for p in month_starts(W2_START_MS, C._ms("2026-08-01T00:00:00Z"))]
    day = C._ms("2026-08-01T00:00:00Z")
    freeze_day = (FREEZE_MS // 86_400_000) * 86_400_000
    while day < freeze_day:
        reqs.append(("daily", _d(day).strftime("%Y-%m-%d")))
        day += 86_400_000
    if last_admissible_open_ms(timeframe) >= freeze_day:
        reqs.append(("rest", f"{freeze_day}:{last_admissible_open_ms(timeframe)}"))
    for kind, period in reqs:
        if kind != "rest" and not archive_is_pre_freeze(kind, period):
            raise FreezeViolation(period)
    return reqs
