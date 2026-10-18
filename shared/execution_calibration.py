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
from shared.signal_stop import candle_invalidated
from shared.triple_barrier import (TripleBarrierConfig, TripleBarrierState,
                                   expiry_policy_for_timeframe, step_barrier)

VERSION = "a47-cal-v1"                 # calibrate(): classes unchanged since A47
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
ADMISSION_WINDOW_MS = 2 * 3_600_000


TRACKER_EVENT_VERSION = "a48-tev-v1"
SOURCES = (None, "rest_backup", "websocket", "restart")
STALE_AFTER_MS = 60_000             # config.PRICE_STREAM_ALERT_AFTER_SECONDS (diagnostic only)
STOP_REASONS = ("stop_loss", "break_even", "trailing_stop")


@dataclass(frozen=True)
class Poll:
    """One tracker observation, in ARRIVAL order.

    t_ms         processing time: the tracker's wall clock when it evaluates (all decisions use it)
    price        the observed last-trade price; None = the REST fetch failed (tracker skips)
    source       None         evaluate_trade_safely directly (A47 semantics: entry + exit, no candle)
                 rest_backup  main loop: track_open_trades (candle invalidation, then exits) and
                              register_new_signals (entry) — the ONLY entry path
                 websocket    handle_stream_price for an open trade; dropped unless agg_id is
                              greater than the last one seen (BinancePriceStream._handle)
                 restart      process restart: in-memory stream state is lost, DB state survives
    agg_id       Binance aggregate-trade id (websocket only)
    observed_ms  exchange event time (diagnostics only: the tracker never reads it)
    candle_close_ms / candle_close   the last CLOSED signal-timeframe candle a REST poll would fetch
    """
    t_ms: int
    price: float | None
    source: str | None = None
    agg_id: int | None = None
    observed_ms: int | None = None
    candle_close_ms: int | None = None
    candle_close: float | None = None


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
    exit_reference_price: float | None = None   # price before modeled slippage (stop: min(level, observed))
    remaining_fraction: float | None = None     # position fraction closed by the terminal exit
    stop_hit: bool | None = None
    stop_invalidation: float | None = None
    diagnostics: dict = field(default_factory=dict)
    model_version: str = TRACKER_EVENT_VERSION


def _finite_pos(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x) and x > 0


def _sequence_defect(polls: Sequence[Poll]) -> str | None:
    """Sequences the tracker could not have produced; reported, never silently repaired."""
    last_t = None
    for p in polls:
        if p.source not in SOURCES:
            return "unknown_source"
        if not isinstance(p.t_ms, int) or (last_t is not None and p.t_ms < last_t):
            return "processing_time_not_monotone"
        last_t = p.t_ms
        if p.source == "restart":
            continue
        if p.price is not None and not _finite_pos(p.price):
            return "non_finite_or_non_positive_price"
        if p.source == "websocket" and (p.agg_id is None or p.price is None):
            return "websocket_without_aggregate_id_or_price"
        if p.observed_ms is not None and p.observed_ms > p.t_ms:
            return "observation_after_processing"
        if (p.candle_close_ms is None) != (p.candle_close is None):
            return "candle_incomplete"
        if p.candle_close is not None and (not _finite_pos(p.candle_close) or p.candle_close_ms > p.t_ms):
            return "candle_invalid_or_from_future"
    return None


def tracker_poll_model(*, trade_type, planned_entry, stop_loss, target_1, target_2, target_3,
                       timeframe, polls: Sequence[Poll], signal_ms: int, invalidation_price=None,
                       trade_amount=50.0, min_notional=5.0, stop_slippage=0.001,
                       roundtrip_cost=0.003, fill_model="observed_price_v0",
                       stale_after_ms: int = STALE_AFTER_MS) -> PollOutcome:
    """Mode 2 (tracker_event_v1): the tracker's decisions on the same ordered observations.

    Processes polls in ARRIVAL order exactly as the tracker does (no reordering by event time);
    calls the production functions for every decision. An engineering reference, not an
    exchange-execution truth model."""
    if not polls:
        return PollOutcome("invalid", "no_polls")
    if not all(_finite_pos(x) for x in (planned_entry, stop_loss, target_1, target_2, target_3)) \
            or (invalidation_price is not None and not _finite_pos(invalidation_price)):
        return PollOutcome("invalid", "non_finite_or_non_positive_bracket")
    defect = _sequence_defect(polls)
    if defect:
        return PollOutcome("invalid", defect)
    diag = {"skipped_missing_price": 0, "ignored_pre_fill_stream": 0, "dropped_stream_not_newer": 0,
            "stale_observations": 0, "out_of_order_observations": 0, "restarts": 0}
    max_obs = None
    for p in polls:
        if p.observed_ms is not None and p.price is not None:
            if p.t_ms - p.observed_ms > stale_after_ms:
                diag["stale_observations"] += 1
            if max_obs is not None and p.observed_ms < max_obs:
                diag["out_of_order_observations"] += 1
            max_obs = p.observed_ms if max_obs is None else max(max_obs, p.observed_ms)
    fill_i = fill_price = None
    action = None
    for i, p in enumerate(polls):
        if p.source == "restart":
            diag["restarts"] += 1
            continue
        if p.source == "websocket":                          # no open trade -> not subscribed
            diag["ignored_pre_fill_stream"] += 1
            continue
        if p.t_ms - signal_ms >= ADMISSION_WINDOW_MS:         # SQL: signal_time > NOW() - 2 hours
            return PollOutcome("not_filled", "admission_window_expired", action, diagnostics=diag)
        if p.price is None:                                   # `if not fill_entry: continue`
            diag["skipped_missing_price"] += 1
            continue
        decision = decide_long_entry(trade_type=trade_type, planned_entry=planned_entry,
                                     current_price=p.price, stop_loss=stop_loss,
                                     invalidation_price=invalidation_price)
        fill = resolve_entry_fill(model=fill_model, decision=decision, previous_kind=None,
                                  planned_entry=planned_entry, current_price=p.price,
                                  stop_loss=stop_loss, invalidation_price=invalidation_price)
        action = decision.action
        if fill.action == "reject":
            return PollOutcome("rejected", decision.reason, action, diagnostics=diag)
        if fill.action == "fill":
            fill_i, fill_price = i, float(fill.price)
            break
    if fill_i is None:
        return PollOutcome("not_filled", "limit_not_reached", action, diagnostics=diag)
    try:
        br = rebase_long_bracket(planned_entry, fill_price, target_1, target_2, target_3, stop_loss)
    except ValueError as exc:                                 # tracker: logged, not admitted
        return PollOutcome("rejected", f"bracket_invalid:{exc}", action, diagnostics=diag)
    expiry_h, t1_h, no_t1_h = expiry_policy_for_timeframe(timeframe)
    entry = br["entry_price"]
    diag["observed_fill_price"] = fill_price
    fill_price = entry                                        # stored round(fill, 8): the P&L basis
    stop_inv = (float(invalidation_price) * diag["observed_fill_price"] / float(planned_entry)
                if invalidation_price else br["stop_loss"])
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
    last_agg = None

    def closed(p, reason, exit_price, ref, stop_hit):
        g_pct, g_usdt = aggregate_close(entry=entry, final_exit=exit_price, trade_amount=trade_amount,
                                        realized_pct=realized_pct, realized_usdt=realized_usdt,
                                        remaining_fraction=remaining)
        return PollOutcome("closed", None, action, fill_price, opened, reason, exit_price, p.t_ms,
                           state.highest_target, g_pct, g_usdt, tuple(fills), ref, remaining,
                           stop_hit, stop_inv, diag)

    for p in polls[fill_i + 1:]:
        if p.source == "restart":
            diag["restarts"] += 1
            last_agg = None                                   # new BinancePriceStream instance
            continue
        if p.price is None:
            diag["skipped_missing_price"] += 1
            continue
        if p.source == "websocket":
            if last_agg is not None and p.agg_id <= last_agg:
                diag["dropped_stream_not_newer"] += 1
                continue
            last_agg = p.agg_id
        state.hours_open = (p.t_ms - opened) / 3_600_000      # the tracker's wall-clock hours
        if (p.source == "rest_backup" and state.highest_target == 0 and stop_inv
                and p.candle_close is not None
                and candle_invalidated(opened_ms=opened, candle_close_ms=p.candle_close_ms,
                                       candle_close=p.candle_close, invalidation_price=stop_inv,
                                       highest_target=state.highest_target)):
            # track_open_trades -> close_trade(current_price): no step_barrier, no stop slippage
            pnl = (p.price / entry - 1) * 100
            return closed(p, "signal_candle_invalidation", p.price, p.price,
                          pnl <= 0 and p.price <= cfg.stop_loss)
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
            ref = (min(state.effective_stop(cfg)[0], p.price) if result.exit_reason in STOP_REASONS
                   else result.exit_price)
            return closed(p, result.exit_reason, result.exit_price, ref, result.stop_hit)
    return PollOutcome("open_at_end", "insufficient_polls", action, fill_price, opened,
                       target_reached=state.highest_target, fills=tuple(fills),
                       remaining_fraction=remaining, stop_invalidation=stop_inv, diagnostics=diag)


def bars_from_polls(polls: Sequence[Poll], bar_timeframe: str, *, start_ms: int | None = None) -> list:
    """Aggregate observations into gap-free OHLC bars by EVENT time (observed_ms when given, else
    t_ms); empty bars carry the last close. Restarts and failed fetches carry no price."""
    step = TF_MS[bar_timeframe]
    ev = lambda p: p.observed_ms if p.observed_ms is not None else p.t_ms
    ordered = sorted((p for p in polls if p.price is not None and p.source != "restart"), key=ev)
    first = (ev(ordered[0]) // step) * step if start_ms is None else start_ms
    buckets: dict[int, list] = {}
    for p in ordered:
        buckets.setdefault((ev(p) - first) // step, []).append(p.price)
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


# ── A48 cost accounting (Phase D) ──────────────────────────────────────────
#
# Convention (a48-cost-v1). Every leg carries a REFERENCE price (the observed / level price before
# any modeled execution deterioration) and an EXECUTION price (what the model fills at).
#   gross_price_pnl      = Σ q·ref(exit) − Q·ref(entry)                         (no costs at all)
#   execution_slippage   = Q·(exec(entry) − ref(entry)) + Σ q·(ref − exec)(exit)  (already IN prices)
#   execution_price_pnl  = gross_price_pnl − execution_slippage  (= the tracker's stored gross)
#   explicit_fees        = fee_rate × executed notional of every leg (10 bps/side, no BNB discount)
#   spread_cost          = half_spread × executed notional of taker legs (0 when not modeled)
#   total_modeled_costs  = explicit_fees + spread_cost + execution_slippage
#   net_modeled_pnl      = gross_price_pnl − total_modeled_costs
# Slippage is a realized cost exactly once: inside the execution price. The tracker's 0.1 %
# allowance is NOT a realized cost; it is reported as `stress_allowance` (stress_net = net − it).
# legacy_tracker_net is the A38 label (economic_close on the execution-price gross: flat 0.3 %),
# reproduced exactly and reconciled term by term:
#   legacy_net = net_modeled + legacy_rounding + (explicit_fees − 0.2 %·N) + spread − 0.1 %·N
COST_VERSION = "a48-cost-v1"
FEE_RATE_PER_SIDE = 0.001
LEGACY_FEE_PART_PCT = 0.2


@dataclass(frozen=True)
class ExecutedLeg:
    kind: str                        # entry | target | stop_loss | break_even | trailing_stop | ...
    fraction: float                  # of the bought quantity (ignored when quantity is given)
    reference_price: float
    execution_price: float
    taker: bool                      # crosses the spread (market / stop) vs resting limit
    quantity: float | None = None    # explicit exchange quantity (after step rounding)


@dataclass(frozen=True)
class CostLedger:
    version: str
    notional_usdt: float
    quantity: float
    gross_price_pnl_usdt: float
    explicit_fees_usdt: float
    spread_cost_usdt: float
    execution_slippage_usdt: float
    total_modeled_costs_usdt: float
    net_modeled_pnl_usdt: float
    execution_price_pnl_usdt: float
    stress_allowance_usdt: float
    stress_net_usdt: float
    legacy_tracker_net_usdt: float
    legacy_economic_result: str
    legacy_fee_basis_difference_usdt: float
    legacy_rounding_usdt: float
    double_counted_slippage_usdt: float      # charged twice ONLY by the legacy flat convention
    unsold_quantity: float
    unsold_mark_usdt: float                  # inventory left (dust / rejected), NOT a cost
    legs: tuple


def cost_ledger(legs: Sequence[ExecutedLeg], *, notional_usdt: float = 50.0,
                fee_rate_per_side: float = FEE_RATE_PER_SIDE, half_spread_pct: float = 0.0,
                allowance_pct: float = TRACKER_SLIPPAGE_ALLOWANCE_PCT,
                legacy_flat_pct: float = TRACKER_FLAT_PCT, quantity: float | None = None) -> CostLedger:
    """Separate, auditable cost fields for one closed trade (first leg = the entry)."""
    vals = [notional_usdt, fee_rate_per_side, half_spread_pct, allowance_pct, legacy_flat_pct]
    if not legs or legs[0].kind != "entry" or any(not math.isfinite(v) or v < 0 for v in vals):
        raise ValueError("invalid_ledger_inputs")
    for l in legs:
        if not (_finite_pos(l.reference_price) and _finite_pos(l.execution_price)
                and math.isfinite(l.fraction) and 0 <= l.fraction <= 1
                and (l.quantity is None or (math.isfinite(l.quantity) and l.quantity >= 0))):
            raise ValueError("invalid_leg")
    e = legs[0]
    q_total = notional_usdt / e.execution_price if quantity is None else float(quantity)
    exits = [(l, l.quantity if l.quantity is not None else l.fraction * q_total) for l in legs[1:]]
    sold = sum(q for _, q in exits)
    if sold > q_total * (1 + 1e-12) + 1e-15:
        raise ValueError("oversold_quantity")
    gross = sum(q * l.reference_price for l, q in exits) - q_total * e.reference_price
    slip = q_total * (e.execution_price - e.reference_price) + sum(
        q * (l.reference_price - l.execution_price) for l, q in exits)
    exec_notional = [(e, q_total * e.execution_price)] + [(l, q * l.execution_price) for l, q in exits]
    fees = fee_rate_per_side * sum(n for _, n in exec_notional)
    spread = half_spread_pct / 100 * sum(n for l, n in exec_notional if l.taker)
    total = fees + spread + slip
    net = gross - total
    exec_pnl = gross - slip
    allowance = allowance_pct / 100 * notional_usdt
    legacy = economic_close(exec_pnl, notional=notional_usdt, fee_roundtrip=legacy_flat_pct)
    rounding = round(exec_pnl, 4) - exec_pnl
    unsold = max(0.0, q_total - sold)
    last_ref = exits[-1][0].reference_price if exits else e.reference_price
    return CostLedger(COST_VERSION, notional_usdt, q_total, gross, fees, spread, slip, total, net,
                      exec_pnl, allowance, net - allowance, legacy["net_profit_usdt"],
                      legacy["economic_result"], fees - LEGACY_FEE_PART_PCT / 100 * notional_usdt,
                      rounding, min(max(slip, 0.0), allowance) if legacy_flat_pct > 0 else 0.0,
                      unsold, unsold * last_ref, tuple(legs))


def legs_from_poll_outcome(o: PollOutcome, *, stop_slippage: float = TRACKER_STOP_FILL_SLIPPAGE) -> list:
    """ExecutedLeg list for a closed Mode-2 outcome: entry (taker at the observed price), target
    tranches (resting limits at the target), terminal leg (stop: reference min(level, observed),
    execution × (1 − s); expiry / invalidation: the observed price)."""
    if o.status != "closed":
        raise ValueError("outcome_not_closed")
    legs = [ExecutedLeg("entry", 1.0, o.fill_price, o.fill_price, True)]
    legs += [ExecutedLeg(f"target_{t}", fr, px, px, False) for t, fr, px in o.fills]
    if o.remaining_fraction and o.remaining_fraction > 0:
        legs.append(ExecutedLeg(o.exit_reason, o.remaining_fraction, o.exit_reference_price,
                                o.exit_price, o.exit_reason in STOP_REASONS
                                or o.exit_reason == "signal_candle_invalidation"
                                or "expired" in (o.exit_reason or "")))
    return legs
