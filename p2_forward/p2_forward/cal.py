"""UTC calendar for segment hour keys, day directories and day-scoped continuous-mode work (P2-CR).

Production values are fixed: 1 h hours, 24 h days, Unix epoch, so `hour_key(ms)` equals
`datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y%m%dT%H")` exactly (the pre-P2-CR writer rule).

The offline harness may substitute an ACCELERATED calendar in the collector parent process only (`configure`):
`hour_ms` real milliseconds per calendar hour, counted from `epoch_hour` (an hour index of real time) at `base`.
Every artifact that depends on the calendar records `params()` so an independent reader can re-derive day bounds.
"""
from __future__ import annotations

import datetime as dt

UTC = dt.timezone.utc
HOURS_PER_DAY = 24
_P = {"hour_ms": 3_600_000, "epoch_hour": 0, "base": dt.datetime(1970, 1, 1, tzinfo=UTC)}
PRODUCTION = {"hour_ms": 3_600_000, "epoch_hour": 0, "base": "1970-01-01T00:00:00+00:00"}


def configure(hour_ms: int, epoch_hour: int, base: dt.datetime) -> None:
    """Test / harness only: accelerated calendar (whole hours, aligned to the 1 s sample grid)."""
    if not (isinstance(hour_ms, int) and hour_ms >= 1000 and hour_ms % 1000 == 0):
        raise ValueError("hour_ms must be a positive multiple of 1 s (the sample grid)")
    _P.update(hour_ms=hour_ms, epoch_hour=int(epoch_hour), base=base)


def reset() -> None:
    _P.update(hour_ms=3_600_000, epoch_hour=0, base=dt.datetime(1970, 1, 1, tzinfo=UTC))


def params() -> dict:
    return {"hour_ms": _P["hour_ms"], "epoch_hour": _P["epoch_hour"], "base": _P["base"].isoformat()}


def is_production() -> bool:
    return params() == PRODUCTION


def hour_ms() -> int:
    return _P["hour_ms"]


def day_ms() -> int:
    return _P["hour_ms"] * HOURS_PER_DAY


def _hours(ms: int) -> int:
    return ms // _P["hour_ms"] - _P["epoch_hour"]


def utc_of_ms(ms: int) -> dt.datetime:
    """Calendar time of `ms`, at hour resolution."""
    return _P["base"] + dt.timedelta(hours=_hours(ms))


def hour_key(ms: int) -> str:
    return utc_of_ms(ms).strftime("%Y%m%dT%H")


def day_key(ms: int) -> str:
    return utc_of_ms(ms).strftime("%Y-%m-%d")


def day_start_ms(day: str) -> int:
    d = dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
    hours = int((d - _P["base"]).total_seconds() // 3600) + _P["epoch_hour"]
    return hours * _P["hour_ms"]


def day_end_ms(day: str) -> int:
    return day_start_ms(day) + day_ms()


def hour_key_start_ms(key: str) -> int:
    """Inverse of hour_key: first ms of calendar hour 'YYYYMMDDTHH'."""
    d = dt.datetime.strptime(key, "%Y%m%dT%H").replace(tzinfo=UTC)
    return (int((d - _P["base"]).total_seconds() // 3600) + _P["epoch_hour"]) * _P["hour_ms"]


def is_day_start(ms: int) -> bool:
    return ms % _P["hour_ms"] == 0 and _hours(ms) % HOURS_PER_DAY == 0
