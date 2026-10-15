"""A42 counterfactual replay of one long bracket over closed bars — pure, no I/O.

Purpose: give *non-selected* or *policy-refused* candidates an outcome under
the same frozen entry/exit rules as admitted trades, so selection and gate
candidates (A42-C1/C2) become evaluable on a prospective stream. Nothing in
production calls this module; running it on real forward bars is a
prospective experiment that needs separate authorisation.

Declared approximations versus the poll-based tracker:
* bars, not ticks: ``step_barrier``'s conservative within-bar order applies
  (the standing stop is checked before targets);
* a gap below the standing stop fills at the bar open (× stop slippage);
* a resting limit fills only on a strict trade-through (low < limit), never
  on a touch — this removes the optimistic touch-fill A37 measured;
* a bar that both trades through the limit and reaches the invalidation level
  is treated as invalidated (no fill).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from shared.entry_execution import decide_long_entry
from shared.execution import rebase_long_bracket
from shared.partial_exits import aggregate_close, fills_between
from shared.signal_quality import TIMEFRAME_MS, CostModel, bar_gaps
from shared.triple_barrier import (TripleBarrierConfig, TripleBarrierState,
                                   expiry_policy_for_timeframe, step_barrier)

MODEL_VERSION = "a42-cf-bar-v1"


@dataclass(frozen=True)
class Bar:
    open_ms: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class CounterfactualOutcome:
    status: str                 # closed | open_at_end | not_filled | rejected | invalid
    reason: str | None
    entry_action: str | None
    fill_price: float | None = None
    fill_bar_ms: int | None = None
    exit_reason: str | None = None
    exit_price: float | None = None
    target_reached: int = 0
    gross_pct: float | None = None
    net_pct: float | None = None
    bars_used: int = 0
    model_version: str = MODEL_VERSION


def _invalid(reason):
    return CounterfactualOutcome("invalid", reason, None)


def replay_bracket(*, trade_type: str, planned_entry: float, stop_loss: float,
                   target_1: float, target_2: float, target_3: float, signal_timeframe: str,
                   bars: Sequence[Bar], bar_timeframe: str, decision_ms: int,
                   invalidation_price: float | None = None, cost: CostModel = CostModel(),
                   trade_amount: float = 50.0, min_notional: float = 5.0,
                   admission_window_ms: int = 2 * 3_600_000,
                   break_even_roundtrip: float = 0.003,
                   spread_pct: float | None = None) -> CounterfactualOutcome:
    """Replay entry → partial exits → terminal exit under the frozen rules."""
    if bar_timeframe not in TIMEFRAME_MS:
        return _invalid("unknown_bar_timeframe")
    if not bars:
        return _invalid("no_bars")
    try:
        cost_pct = cost.roundtrip_pct(spread_pct)
    except ValueError as exc:
        return _invalid(str(exc))
    if bars[0].open_ms < decision_ms:
        return _invalid("bar_before_decision")                 # look-ahead guard
    if bar_gaps([b.open_ms for b in bars], bar_timeframe):
        return _invalid("bar_gap")
    if any(not (b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high) or b.low <= 0
           for b in bars):
        return _invalid("malformed_bar")
    bar_h = TIMEFRAME_MS[bar_timeframe] / 3_600_000

    # ── entry ──────────────────────────────────────────────────────────────
    first = decide_long_entry(trade_type=trade_type, planned_entry=planned_entry,
                              current_price=bars[0].open, stop_loss=stop_loss,
                              invalidation_price=invalidation_price)
    rejection = max(float(stop_loss), float(invalidation_price or stop_loss))
    if first.action == "reject":
        return CounterfactualOutcome("rejected", first.reason, first.action)
    fill_i = fill_price = None
    if first.action == "market":
        fill_i, fill_price = 0, bars[0].open
    else:
        for i, b in enumerate(bars):
            if b.open_ms - bars[0].open_ms >= admission_window_ms:
                break
            if b.low <= rejection:
                return CounterfactualOutcome("rejected", "invalidated_while_waiting", first.action,
                                             bars_used=i + 1)
            if b.low < planned_entry:
                fill_i, fill_price = i, float(planned_entry)
                break
        if fill_i is None:
            return CounterfactualOutcome("not_filled", "limit_not_traded_through", first.action)
    try:
        br = rebase_long_bracket(planned_entry, fill_price, target_1, target_2, target_3, stop_loss)
    except ValueError as exc:
        return CounterfactualOutcome("invalid", f"bracket_invalid:{exc}", first.action)

    # ── exits ──────────────────────────────────────────────────────────────
    expiry_h, t1_h, no_t1_h = expiry_policy_for_timeframe(signal_timeframe)
    entry = br["entry_price"]
    cfg = TripleBarrierConfig(symbol="CF", entry=entry, target_1=br["target_1"],
                              target_2=br["target_2"], target_3=br["target_3"],
                              stop_loss=br["stop_loss"], trade_amount=trade_amount,
                              expiry_h=expiry_h, t1_expiry_h=t1_h, no_t1_expiry_h=no_t1_h,
                              stop_slippage=cost.stop_slippage_frac,
                              roundtrip_cost=break_even_roundtrip)
    if cfg.validate():
        return CounterfactualOutcome("invalid", f"config:{cfg.validate()}", first.action)
    targets = {1: cfg.target_1, 2: cfg.target_2, 3: cfg.target_3}
    state = TripleBarrierState(peak=entry)
    realized_pct = realized_usdt = 0.0
    remaining = 1.0
    for i in range(fill_i, len(bars)):
        b = bars[i]
        prev = state.highest_target
        # On the fill bar of a resting limit the pre-fill part of the bar is unknown:
        # treat the bar as starting at the fill price (conservative for the high side).
        high = b.high if not (i == fill_i and first.action == "limit_wait") else max(b.close, entry)
        standing_stop, _ = state.effective_stop(cfg)
        gap = b.open if i > fill_i and b.open < standing_stop else None   # gap through the stop
        result = step_barrier(cfg, state, high=high, low=b.low, close=b.close,
                              hours_elapsed=bar_h, stop_observation_price=gap)
        if state.highest_target > prev:
            for f in fills_between(previous_target=prev, reached_target=state.highest_target,
                                   entry=entry, targets=targets, trade_amount=trade_amount,
                                   min_notional=min_notional):
                realized_pct += f.gross_pct_contribution
                realized_usdt += f.gross_usdt
                remaining -= f.fraction
        if result is not None:
            gross, _ = aggregate_close(entry=entry, final_exit=result.exit_price,
                                       trade_amount=trade_amount, realized_pct=realized_pct,
                                       realized_usdt=realized_usdt,
                                       remaining_fraction=max(0.0, remaining))
            return CounterfactualOutcome(
                "closed", None, first.action, fill_price, bars[fill_i].open_ms,
                result.exit_reason, result.exit_price, state.highest_target,
                gross, gross - cost_pct, i + 1)
    return CounterfactualOutcome("open_at_end", "insufficient_bars", first.action, fill_price,
                                 bars[fill_i].open_ms, target_reached=state.highest_target,
                                 bars_used=len(bars))
