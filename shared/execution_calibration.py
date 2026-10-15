"""A47 event-level calibration: Paper tracker (poll level) vs A42 bar replay — research-only.

``tracker_poll_model`` transcribes the control flow of ``trade_tracker.register_new_signals`` /
``evaluate_trade`` and calls the SAME production functions (decide_long_entry, resolve_entry_fill,
rebase_long_bracket, step_barrier with high=low=close=price and stop_observation_price=price,
fills_between, aggregate_close). A DB test holds this transcription to the real ``evaluate_trade``.
``bars_from_polls`` aggregates the identical events into OHLC bars for ``replay_bracket``.

Pre-declared discrepancy classes (fixed before any comparison was run):
  MATCH                              same exit reason and |gross diff| <= 1e-6 pp
  EXPECTED_ROUNDING_DIFFERENCE       same exit reason and |gross diff| <= 1e-3 pp
  INSUFFICIENT_MARKET_INFORMATION    a bar where the standing stop and a new target were both
                                     reachable (OHLC hides the order)
  MODEL_ASSUMPTION_DIFFERENCE        a documented intentional difference: entry fills on touch at
                                     the observed price (tracker) vs strict trade-through at the
                                     limit (replay); expiry at poll time vs bar end; gap fill at the
                                     first poll price vs the bar open
  IMPLEMENTATION_DEFECT              anything else (acceptance requires zero)
Nothing in production imports this module.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from shared.counterfactual_barrier import Bar, CounterfactualOutcome, replay_bracket
from shared.entry_execution import decide_long_entry, resolve_entry_fill
from shared.execution import rebase_long_bracket
from shared.fees import economic_close
from shared.partial_exits import aggregate_close, fills_between
from shared.triple_barrier import (TripleBarrierConfig, TripleBarrierState,
                                   expiry_policy_for_timeframe, step_barrier)

VERSION = "a47-cal-v1"
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
ADMISSION_WINDOW_MS = 2 * 3_600_000


@dataclass(frozen=True)
class Poll:
    """One tracker evaluation: processing time (the tracker's clock) and the observed price."""
    t_ms: int
    price: float


@dataclass(frozen=True)
class PollOutcome:
    status: str                     # closed | open_at_end | not_filled | rejected | invalid
    reason: str | None
    entry_action: str | None = None
    fill_price: float | None = None
    fill_t_ms: int | None = None
    exit_reason: str | None = None
    exit_price: float | None = None
    exit_t_ms: int | None = None
    target_reached: int = 0
    gross_pct: float | None = None
    gross_usdt: float | None = None
    fills: tuple = field(default_factory=tuple)


def tracker_poll_model(*, trade_type, planned_entry, stop_loss, target_1, target_2, target_3,
                       timeframe, polls: Sequence[Poll], signal_ms: int, invalidation_price=None,
                       trade_amount=50.0, min_notional=5.0, stop_slippage=0.001,
                       roundtrip_cost=0.003, fill_model="observed_price_v0") -> PollOutcome:
    """Process polls in ARRIVAL order, exactly as the tracker loop does (it has no reordering)."""
    if not polls:
        return PollOutcome("invalid", "no_polls")
    if any(not (math.isfinite(p.price) and p.price > 0) for p in polls):
        return PollOutcome("invalid", "non_finite_or_non_positive_price")
    fill_i = fill_price = None
    action = None
    for i, p in enumerate(polls):
        if p.t_ms - signal_ms > ADMISSION_WINDOW_MS:          # signal_time > NOW() - 2 hours
            return PollOutcome("not_filled", "admission_window_expired", action)
        decision = decide_long_entry(trade_type=trade_type, planned_entry=planned_entry,
                                     current_price=p.price, stop_loss=stop_loss,
                                     invalidation_price=invalidation_price)
        fill = resolve_entry_fill(model=fill_model, decision=decision, previous_kind=None,
                                  planned_entry=planned_entry, current_price=p.price,
                                  stop_loss=stop_loss, invalidation_price=invalidation_price)
        action = decision.action
        if fill.action == "reject":
            return PollOutcome("rejected", decision.reason, action)
        if fill.action == "fill":
            fill_i, fill_price = i, float(fill.price)
            break
    if fill_i is None:
        return PollOutcome("not_filled", "limit_not_reached", action)
    br = rebase_long_bracket(planned_entry, fill_price, target_1, target_2, target_3, stop_loss)
    expiry_h, t1_h, no_t1_h = expiry_policy_for_timeframe(timeframe)
    entry = br["entry_price"]
    cfg = TripleBarrierConfig(symbol="CAL", entry=entry, target_1=br["target_1"],
                              target_2=br["target_2"], target_3=br["target_3"],
                              stop_loss=br["stop_loss"], trade_amount=trade_amount,
                              expiry_h=expiry_h, t1_expiry_h=t1_h, no_t1_expiry_h=no_t1_h,
                              stop_slippage=stop_slippage, roundtrip_cost=roundtrip_cost)
    targets = {1: cfg.target_1, 2: cfg.target_2, 3: cfg.target_3}
    state = TripleBarrierState(peak=entry)
    opened = polls[fill_i].t_ms
    realized_pct = realized_usdt = 0.0
    remaining = 1.0
    fills = []
    for p in polls[fill_i + 1:]:
        state.hours_open = (p.t_ms - opened) / 3_600_000      # the tracker's wall-clock hours
        prev = state.highest_target
        result = step_barrier(cfg, state, p.price, p.price, p.price, 0.0,
                              stop_observation_price=p.price)
        if state.highest_target > prev:
            for f in fills_between(previous_target=prev, reached_target=state.highest_target,
                                   entry=entry, targets=targets, trade_amount=trade_amount,
                                   min_notional=min_notional):
                realized_pct += f.gross_pct_contribution
                realized_usdt += f.gross_usdt
                remaining = max(0.0, remaining - f.fraction)
                fills.append((f.target, f.fraction, f.price))
        if result is not None:
            g_pct, g_usdt = aggregate_close(entry=entry, final_exit=result.exit_price,
                                            trade_amount=trade_amount, realized_pct=realized_pct,
                                            realized_usdt=realized_usdt, remaining_fraction=remaining)
            return PollOutcome("closed", None, action, fill_price, opened, result.exit_reason,
                               result.exit_price, p.t_ms, state.highest_target, g_pct, g_usdt,
                               tuple(fills))
    return PollOutcome("open_at_end", "insufficient_polls", action, fill_price, opened,
                       target_reached=state.highest_target, fills=tuple(fills))


def bars_from_polls(polls: Sequence[Poll], bar_timeframe: str, *, start_ms: int | None = None) -> list:
    """Aggregate polls (in time order) into gap-free OHLC bars; empty bars carry the last close."""
    step = TF_MS[bar_timeframe]
    ordered = sorted(polls, key=lambda p: p.t_ms)
    first = (ordered[0].t_ms // step) * step if start_ms is None else start_ms
    buckets: dict[int, list] = {}
    for p in ordered:
        buckets.setdefault((p.t_ms - first) // step, []).append(p.price)
    bars, last = [], ordered[0].price
    for k in range(max(buckets) + 1):
        prices = buckets.get(k) or [last]
        bars.append(Bar(first + k * step, prices[0], max(prices), min(prices), prices[-1]))
        last = prices[-1]
    return bars


def ambiguous_bars(bars: Sequence[Bar], *, stop: float, targets: Sequence[float]) -> int:
    """Bars whose range contains both the original stop and a target above it (order unknown)."""
    return sum(1 for b in bars if b.low <= stop and any(b.high >= t for t in targets))


@dataclass(frozen=True)
class CalibrationRow:
    name: str
    tracker: PollOutcome
    replay: CounterfactualOutcome
    gross_diff_pp: float | None
    net_label_tracker: str | None
    net_label_replay: str | None
    classification: str
    explanation: str


def calibrate(name, *, trade_type, planned_entry, stop_loss, target_1, target_2, target_3,
              timeframe, polls, signal_ms, bar_timeframe="15m", invalidation_price=None,
              expected_difference: str | None = None) -> CalibrationRow:
    """Run both models on identical events and classify the difference by the declared rules.

    ``expected_difference`` names the documented reason a scenario is EXPECTED to differ; it is
    accepted only if the outcomes actually differ in that dimension, otherwise the row is a defect."""
    t = tracker_poll_model(trade_type=trade_type, planned_entry=planned_entry, stop_loss=stop_loss,
                           target_1=target_1, target_2=target_2, target_3=target_3,
                           timeframe=timeframe, polls=polls, signal_ms=signal_ms,
                           invalidation_price=invalidation_price)
    bars = bars_from_polls(polls, bar_timeframe)
    r = replay_bracket(trade_type=trade_type, planned_entry=planned_entry, stop_loss=stop_loss,
                       target_1=target_1, target_2=target_2, target_3=target_3,
                       signal_timeframe=timeframe, bars=bars, bar_timeframe=bar_timeframe,
                       decision_ms=bars[0].open_ms, invalidation_price=invalidation_price)
    gd = (r.gross_pct - t.gross_pct) if (t.gross_pct is not None and r.gross_pct is not None) else None
    lt = economic_close(t.gross_usdt)["economic_result"] if t.gross_usdt is not None else None
    lr = economic_close(r.gross_pct / 100 * 50)["economic_result"] if r.gross_pct is not None else None
    same_reason = (t.status, t.exit_reason) == (r.status, r.exit_reason)
    amb = ambiguous_bars(bars, stop=stop_loss, targets=(target_1, target_2, target_3))
    if same_reason and (gd is None or abs(gd) <= 1e-6):
        cls, why = "MATCH", ""
    elif same_reason and gd is not None and abs(gd) <= 1e-3:
        cls, why = "EXPECTED_ROUNDING_DIFFERENCE", f"gross diff {gd:.2e} pp"
    elif amb:
        cls, why = "INSUFFICIENT_MARKET_INFORMATION", f"{amb} bar(s) reach both stop and a target"
    elif expected_difference:
        cls, why = "MODEL_ASSUMPTION_DIFFERENCE", expected_difference
    else:
        cls, why = "IMPLEMENTATION_DEFECT", f"tracker={t.exit_reason} replay={r.exit_reason} gd={gd}"
    return CalibrationRow(name, t, r, gd, lt, lr, cls, why)


def ordering_interval(*, trade_type, planned_entry, stop_loss, target_1, target_2, target_3,
                      timeframe, bars: Sequence[Bar], signal_ms: int, polls_per_bar_ms: int = 60_000):
    """Outcome interval of OHLC bars under the two extreme intrabar orders, via the tracker model:
    stop-first (O, L, H, C) and target-first (O, H, L, C) in every bar. Returns both outcomes;
    the research default is the WORSE net (never the favourable one)."""
    def polls(order):
        out = []
        for b in bars:
            seq = (b.open, b.low, b.high, b.close) if order == "stop_first" else (b.open, b.high, b.low, b.close)
            out += [Poll(b.open_ms + i * polls_per_bar_ms, px) for i, px in enumerate(seq)]
        return out
    res = {o: tracker_poll_model(trade_type=trade_type, planned_entry=planned_entry, stop_loss=stop_loss,
                                 target_1=target_1, target_2=target_2, target_3=target_3,
                                 timeframe=timeframe, polls=polls(o), signal_ms=signal_ms)
           for o in ("stop_first", "target_first")}
    g = [x.gross_pct for x in res.values() if x.gross_pct is not None]
    return {"outcomes": res, "ambiguous": len({(x.exit_reason, x.gross_pct) for x in res.values()}) > 1,
            "conservative_gross_pct": min(g) if g else None, "favourable_gross_pct": max(g) if g else None}


# ── cost overlap (Phase E) ─────────────────────────────────────────────────

TRACKER_FLAT_PCT = 0.3            # config.FEE_ROUNDTRIP_PCT: "0.1 %/side fee + ~0.1 % slippage"
TRACKER_FEE_PART_PCT = 0.2
TRACKER_SLIPPAGE_ALLOWANCE_PCT = 0.1
TRACKER_STOP_FILL_SLIPPAGE = 0.001  # config.STOP_SLIPPAGE, applied inside the stop fill price


def tracker_cost_decomposition(stop_fraction: float, stop_price_rel: float = 1.0) -> dict:
    """How the tracker's costs are composed for one trade.

    The flat 0.3 % (charged on every trade, reports and A38 labels) = 0.2 % fee + 0.1 % slippage
    allowance. Independently, every STOP exit is filled at stop × (1 − 0.1 %), so slippage on the
    stop fraction is charged twice: once in the fill price, once in the flat allowance. Targets are
    filled exactly at the target, so their share of the allowance is a pure cushion."""
    if not (0 <= stop_fraction <= 1) or not math.isfinite(stop_price_rel) or stop_price_rel <= 0:
        raise ValueError("invalid_inputs")
    stop_fill = stop_fraction * stop_price_rel * TRACKER_STOP_FILL_SLIPPAGE * 100
    return {"fee_pct": TRACKER_FEE_PART_PCT, "flat_slippage_allowance_pct": TRACKER_SLIPPAGE_ALLOWANCE_PCT,
            "stop_fill_slippage_pct": stop_fill,
            "double_counted_slippage_pct": min(stop_fill, TRACKER_SLIPPAGE_ALLOWANCE_PCT * stop_fraction),
            "total_charged_pct": TRACKER_FLAT_PCT + stop_fill}


def detect_cost_overlap(components: dict) -> list[str]:
    """Names of cost kinds charged by more than one component (e.g. slippage in fill AND flat)."""
    seen, dup = {}, []
    for comp, kinds in components.items():
        for k in kinds:
            if k in seen and k not in dup:
                dup.append(k)
            seen.setdefault(k, comp)
    return sorted(dup)
