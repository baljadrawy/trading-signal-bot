"""Signal-thesis-aware initial stop planning for long trades."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SignalStopPlan:
    stop_price: float
    invalidation_price: float
    risk_pct: float
    policy: str
    valid: bool
    reason: str | None = None


def plan_signal_stop(*, entry: float, atr: float, trade_type: str,
                     structure_low: float, breakout_level: float | None,
                     max_risk_pct: float, atr_buffer: float = 0.25,
                     minimum_atr_distance: float = 1.0) -> SignalStopPlan:
    """Place the stop beyond thesis invalidation, or reject the setup."""
    values = (entry, atr, structure_low, max_risk_pct, atr_buffer,
              minimum_atr_distance)
    if not all(math.isfinite(float(v)) for v in values):
        return SignalStopPlan(0, 0, 0, str(trade_type), False, 'non_finite_input')
    if entry <= 0 or atr <= 0 or structure_low <= 0 or max_risk_pct <= 0:
        return SignalStopPlan(0, 0, 0, str(trade_type), False, 'non_positive_input')
    if trade_type == 'momentum':
        if breakout_level is None or not math.isfinite(float(breakout_level)):
            return SignalStopPlan(0, 0, 0, 'momentum_breakout', False,
                                  'missing_breakout_level')
        thesis_level, policy = float(breakout_level), 'momentum_breakout'
    elif trade_type == 'reversion':
        thesis_level, policy = float(structure_low), 'reversion_structure'
    else:
        return SignalStopPlan(0, 0, 0, str(trade_type), False,
                              'unsupported_trade_type')
    invalidation = thesis_level - atr * atr_buffer
    stop = min(invalidation, entry - atr * minimum_atr_distance)
    if stop <= 0 or stop >= entry:
        return SignalStopPlan(stop, invalidation, 0, policy, False,
                              'invalid_stop_geometry')
    risk_pct = (entry - stop) / entry
    if risk_pct > max_risk_pct + 1e-12:
        return SignalStopPlan(stop, invalidation, risk_pct * 100, policy, False,
                              'structural_risk_exceeds_cap')
    return SignalStopPlan(stop, invalidation, risk_pct * 100, policy, True)


def candle_invalidated(*, opened_ms: int, candle_close_ms: int,
                       candle_close: float, invalidation_price: float,
                       highest_target: int) -> bool:
    """Only post-entry closed candles can invalidate a pre-T1 signal thesis."""
    return (highest_target == 0
            and candle_close_ms > opened_ms
            and candle_close <= invalidation_price)
