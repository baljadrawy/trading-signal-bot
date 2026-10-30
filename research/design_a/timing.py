"""Design A v1.0 timing: the weekly decision instant, candle availability, the 200-day signal
window and the execution reference schedule. All instants are UTC (spec §4, §5)."""
from __future__ import annotations

from datetime import datetime, timedelta

from research.design_a.state import (DAY, DECISION_OFFSET_SECONDS, WEEK, Candle, DesignAError,
                                     Event, Snapshot, available_from, is_decision_instant, utc)

__all__ = ["is_decision_instant", "next_decision_instant", "day_start", "available_from",
           "is_available", "is_overdue", "available", "latest_sunday_open",
           "scheduled_reference_open", "signal_window"]


def next_decision_instant(after: datetime) -> datetime:
    """The first decision instant strictly after ``after``."""
    utc(after, "after")
    this_week = (day_start(after) - DAY * after.weekday()
                 + timedelta(seconds=DECISION_OFFSET_SECONDS))
    return this_week if this_week > after else this_week + WEEK


def day_start(at: datetime) -> datetime:
    return at.replace(hour=0, minute=0, second=0, microsecond=0)


def is_available(candle: Candle, as_of: datetime) -> bool:
    """The provisional availability rule (``state.available_from``) applied to a candle."""
    return as_of >= available_from(candle.open_time)


def is_overdue(open_time: datetime, as_of: datetime) -> bool:
    """True once the candle opening at ``open_time`` would be available if it existed."""
    return as_of >= available_from(open_time)


def available(snapshot: Snapshot) -> dict[datetime, Candle]:
    """The snapshot's candles keyed by open_time (all available: ``Snapshot`` refuses others)."""
    return {c.open_time: c for c in snapshot.candles if is_available(c, snapshot.as_of)}


def latest_sunday_open(decision_time: datetime) -> datetime:
    """Open time of the latest completed Sunday candle, for a Monday decision instant."""
    return day_start(decision_time) - DAY


def scheduled_reference_open(decided_at: datetime) -> datetime:
    """Open time of the scheduled execution candle: the Tuesday after a Monday decision."""
    return day_start(decided_at) + DAY


def signal_window(snapshot: Snapshot, n: int) -> tuple[tuple[Candle, ...], tuple[Event, str] | None]:
    """At a decision instant, the ``n`` consecutive daily candles ending with the latest completed
    Sunday.

    Returns ``(window, None)``, or ``((), (event, reason))`` when there is none: no history yet,
    or history starts inside the window without a hole (WARMUP); the Sunday candle is unavailable
    (SKIP_MISSING_SUNDAY); or a day inside the window is missing (SKIP_INVALID_DATA). Nothing is
    filled, interpolated or taken from outside the window."""
    if not is_decision_instant(snapshot.as_of) or n < 1:
        raise DesignAError("signal_window needs a decision instant and a positive window")
    by_open = available(snapshot)
    if not by_open:
        return (), (Event.WARMUP, "INSUFFICIENT_HISTORY")
    end = latest_sunday_open(snapshot.as_of)
    if end not in by_open:
        return (), (Event.SKIP_MISSING_SUNDAY, "SUNDAY_CANDLE_UNAVAILABLE")
    days = [end - DAY * k for k in range(n - 1, -1, -1)]
    missing = [d for d in days if d not in by_open]
    if not missing:
        return tuple(by_open[d] for d in days), None
    if max(missing) < min(by_open):
        return (), (Event.WARMUP, "INSUFFICIENT_HISTORY")
    return (), (Event.SKIP_INVALID_DATA, "GAP_IN_WINDOW")
