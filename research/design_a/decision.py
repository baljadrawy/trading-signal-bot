"""Design A v1.0 signal (spec F3–F7): at Monday 00:00 UTC plus 30 seconds, LONG iff the latest
completed Sunday close is above the simple moving average of the 200 completed UTC daily closes
ending with that Sunday; equality is FLAT. No other input, indicator, band or parameter."""
from __future__ import annotations

from research.design_a.state import (SMA_WINDOW, ZERO, Decision, Event, Snapshot, State, Target,
                                     arithmetic, candle_fingerprint, check_consumed, check_inputs,
                                     required_action, window_days)
from research.design_a.timing import is_decision_instant, signal_window

__all__ = ["SMA_WINDOW", "decide"]


def decide(state: State, snapshot: Snapshot) -> Decision:
    """Pure: the weekly decision at ``snapshot.as_of``. ``state`` is read, never changed."""
    check_inputs(state, snapshot)
    at = snapshot.as_of
    if not is_decision_instant(at):
        return Decision(at, Event.NO_SIGNAL, reason="NOT_DECISION_INSTANT")
    check_consumed(state, snapshot, since=window_days(at)[0])   # also the window read below
    window, refusal = signal_window(snapshot, SMA_WINDOW)
    if refusal is not None:
        event, reason = refusal
        if event is Event.WARMUP and state.target is not None:
            event = Event.SKIP_INVALID_DATA     # warm-up is only the initial one (brief §7)
        return Decision(at, event, reason=reason)
    sunday_close = window[-1].close
    with arithmetic():
        total = sum((c.close for c in window), ZERO)
        long = sunday_close * SMA_WINDOW > total    # close > SMA, compared without division
        sma = total / SMA_WINDOW                     # reported; exact because 1/200 terminates
    target = Target.LONG if long else Target.FLAT
    return Decision(at, Event.DECIDE_LONG if long else Event.DECIDE_FLAT, target,
                    action=required_action(state, target), sunday_close=sunday_close, sma=sma,
                    window=tuple(candle_fingerprint(c) for c in window))
