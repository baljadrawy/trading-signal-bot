"""A48 versioned replay execution layer — pure, research-only, never imported by production.

Three explicitly named modes over the SAME frozen entry/exit rules (shared.triple_barrier etc.):

  legacy_bar_v1        A42 ``replay_bracket`` (a42-cf-bar-v1), unchanged, for regression comparison.
                       Stops fill AT the level (or the bar open on a gap) × (1 − s): optimistic
                       relative to the tracker whenever monitoring is discrete (A47).
  tracker_event_v1     ``execution_calibration.tracker_poll_model`` (a48-tev-v1): the Paper
                       tracker's decisions and fills on the same ordered observations. An
                       engineering reference, NOT an exchange-execution truth model.
  ohlc_uncertainty_v1  OHLC bars only. No intrabar order and no fill timestamp is inferred. Every
                       feasible path-order branch is reported, and each terminal fill carries an
                       interval whose bounds are CONDITIONAL on named assumptions. No branch,
                       bound or midpoint is an expected execution price.

Nothing here may be activated in production; the active Paper fill model stays observed_price_v0.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Sequence

from shared.counterfactual_barrier import MODEL_VERSION as LEGACY_VERSION
from shared.counterfactual_barrier import Bar, replay_bracket
from shared.entry_execution import decide_long_entry
from shared.execution import rebase_long_bracket
from shared.execution_calibration import (STOP_REASONS, TRACKER_EVENT_VERSION, ExecutedLeg, Poll,
                                          bars_from_polls, cost_ledger, legs_from_poll_outcome,
                                          tracker_poll_model)
from shared.partial_exits import aggregate_close, fills_between
from shared.signal_quality import TIMEFRAME_MS, bar_gaps
from shared.triple_barrier import (TripleBarrierConfig, TripleBarrierState,
                                   expiry_policy_for_timeframe, step_barrier)

VERSION = "a48-rx-v1"
OHLC_VERSION = "a48-ohlc-v1"
ADMISSION_WINDOW_MS = 2 * 3_600_000

MODES = {
    "legacy_bar_v1": {
        "model_version": LEGACY_VERSION, "input": "OHLC bars",
        "stop_fill": "stop level, or the bar open when the bar opens below it, x (1 - s)",
        "entry_fill": "resting limit at the limit on a strict trade-through; market at bar 0 open",
        "role": "legacy; regression comparison only (known optimistic stop fills)"},
    "tracker_event_v1": {
        "model_version": TRACKER_EVENT_VERSION, "input": "ordered observations (Poll)",
        "stop_fill": "first observed price at/below the stop, x (1 - s)",
        "entry_fill": "observed_price_v0: fill at the observed price when at/below the plan",
        "role": "engineering reference for Paper-tracker fidelity, not exchange truth"},
    "ohlc_uncertainty_v1": {
        "model_version": OHLC_VERSION, "input": "OHLC bars",
        "stop_fill": "interval [bar low, min(stop, bar open)] x (1 - s), conditional on A_OBS_IN_BAR",
        "entry_fill": "interval [max(bar low, rejection), min(plan, bar high)], conditional",
        "role": "research default for bar data; reports branches and conditional intervals"},
}

ASSUMPTIONS = {
    "A_FIRST_OBS_AT_OPEN": "the first entry observation is the first bar's open",
    "A_OBS_IN_BAR": "the tracker observes at least one price inside the bar in which a level is first "
                    "crossed (poll cadence much shorter than the bar); without it no bound exists",
    "A_LEVEL_WAYPOINTS": "intrabar paths are enumerated as moves between turning points at the bar "
                         "extremes and the bracket levels inside the bar; a continuous path in "
                         "[low, high] yields an event sequence realised by one such waypoint path "
                         "(trailing peaks between waypoints are bounded by monotonicity)",
    "A_TARGET_TOUCH": "a target fills at its price when the bar high reaches it (tracker rule; queue "
                      "position and partial fills are not modeled)",
    "A_EXPIRY_IN_BAR": "an expiry inside a bar exits at an unknown price within that bar's [low, high]",
    "A_FILL_TIME_IN_BAR": "a limit fill happens at an unknown time inside its bar; both ends are evaluated",
}


# ── Mode 3: OHLC uncertainty ──────────────────────────────────────────────

@dataclass(frozen=True)
class OhlcScenario:
    entry: str                       # market_at_open | limit_<fill region>_<early|late>
    path: tuple                      # ((bar_index, order), ...) where the order changed the state
    status: str                      # closed | open_at_end | rejected | not_filled
    reason: str | None
    fill_interval: tuple | None = None           # entry fill prices this scenario covers
    exit_reason: str | None = None
    exit_bar: int | None = None
    target_reached: int = 0
    remaining_fraction: float | None = None
    exit_fill_interval: tuple | None = None      # (worst, best) terminal execution price at the
                                                 # region's representative fill
    gross_pct_interval: tuple | None = None      # (worst, best) gross % over the whole fill region
    conditional_on: tuple = ()


@dataclass(frozen=True)
class OhlcUncertainty:
    model_version: str
    status: str          # DETERMINED | FILL_PRICE_UNCERTAIN | PATH_AMBIGUOUS | INSUFFICIENT_INFORMATION
                         # | rejected | not_filled | invalid
    reason: str | None
    scenarios: tuple = ()
    exit_reasons: tuple = ()
    conditional_gross_envelope_pct: tuple | None = None   # (worst, best) over all scenarios
    conditional_stress_gross_pct: float | None = None     # the worst end, labelled stress, not expected
    order_relevant_bars: int = 0
    assumptions: tuple = ()
    notes: tuple = field(default_factory=tuple)


@dataclass
class _Branch:
    state: TripleBarrierState
    realized_pct: float
    realized_usdt: float
    remaining: float
    path: tuple
    pending_invalidation: bool = False


def _clone(b: _Branch) -> _Branch:
    return _Branch(replace(b.state), b.realized_pct, b.realized_usdt, b.remaining, b.path,
                   b.pending_invalidation)


def _key(b: _Branch):
    s = b.state
    return (s.highest_target, round(s.peak, 10), round(b.realized_pct, 10), round(b.remaining, 12),
            b.pending_invalidation)


def _point(cfg, targets, br: _Branch, price, hours, *, gap_open: bool, trade_amount, min_notional):
    """One observation through the production step_barrier. Stop fills reference the LEVEL (or
    the open on a gap); the interval's other end (the bar low) is attached by the caller."""
    br.state.hours_open = hours
    prev = br.state.highest_target
    res = step_barrier(cfg, br.state, price, price, price, 0.0,
                       stop_observation_price=price if gap_open else None)
    if br.state.highest_target > prev:
        for f in fills_between(previous_target=prev, reached_target=br.state.highest_target,
                               entry=cfg.entry, targets=targets, trade_amount=trade_amount,
                               min_notional=min_notional):
            br.realized_pct += f.gross_pct_contribution
            br.realized_usdt += f.gross_usdt
            br.remaining = max(0.0, br.remaining - f.fraction)
    return res


def _outcome(s: OhlcScenario):
    """A scenario's outcome without its labels (paths / entry names that reach it are merged)."""
    return (s.status, s.reason, s.fill_interval, s.exit_reason, s.exit_bar, s.target_reached,
            s.remaining_fraction, s.exit_fill_interval, s.gross_pct_interval)


def _fill_regions(lo: float, hi: float, ratios: Sequence[float], xs: Sequence[float],
                  trail_highs: Sequence[float], cap: int):
    """Entry fills inside [lo, hi] that can change which rebased level is reachable.

    Rebasing scales every level by fill / plan, so a level L·f/plan meets a bar extreme x at
    f = x / (L / plan). Between consecutive breakpoints reachability is constant; each breakpoint
    and each open region (represented by its midpoint) is evaluated. Returns None above ``cap``."""
    pts = {lo, hi}
    for r in ratios:
        pts |= {x / r for x in xs if lo < x / r < hi}
    pts |= {x / ratios[0] for x in trail_highs if lo < x / ratios[0] < hi}
    pts = sorted(pts)
    if len(pts) > cap:
        return None
    regions = [(p, p, p) for p in pts]
    regions += [((a + b) / 2, a, b) for a, b in zip(pts, pts[1:])]
    return regions


def ohlc_uncertainty(*, trade_type: str, planned_entry: float, stop_loss: float, target_1: float,
                     target_2: float, target_3: float, signal_timeframe: str, bars: Sequence[Bar],
                     bar_timeframe: str, decision_ms: int, invalidation_price: float | None = None,
                     stop_slippage: float = 0.001, roundtrip_cost: float = 0.003,
                     trade_amount: float = 50.0, min_notional: float = 5.0,
                     max_branches: int = 512, max_fill_points: int = 32) -> OhlcUncertainty:
    """Mode 3. Feasible outcomes of one bracket when only OHLC bars are known."""
    inv = lambda r: OhlcUncertainty(OHLC_VERSION, "invalid", r)
    insufficient = lambda r, notes=(): OhlcUncertainty(OHLC_VERSION, "INSUFFICIENT_INFORMATION", r,
                                                       assumptions=tuple(ASSUMPTIONS), notes=notes)
    if bar_timeframe not in TIMEFRAME_MS:
        return inv("unknown_bar_timeframe")
    if not bars:
        return inv("no_bars")
    vals = [planned_entry, stop_loss, target_1, target_2, target_3] + (
        [invalidation_price] if invalidation_price is not None else [])
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in vals):
        return inv("non_finite_or_non_positive_bracket")
    if any(not all(math.isfinite(x) for x in (b.open, b.high, b.low, b.close)) for b in bars):
        return inv("non_finite_bar")
    if bars[0].open_ms < decision_ms:
        return inv("bar_before_decision")
    if bar_gaps([b.open_ms for b in bars], bar_timeframe):
        return inv("bar_gap")
    if any(not (b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high) or b.low <= 0
           for b in bars):
        return inv("malformed_bar")
    if invalidation_price is not None and bar_timeframe != signal_timeframe:
        # The tracker invalidates on CLOSED signal-timeframe candles; other bars cannot show them.
        return insufficient("candle_invalidation_needs_signal_timeframe_bars")
    bar_ms = TIMEFRAME_MS[bar_timeframe]
    rejection = max(float(stop_loss), float(invalidation_price or stop_loss))
    expiry_h, t1_h, no_t1_h = expiry_policy_for_timeframe(signal_timeframe)
    deadlines = sorted({expiry_h, t1_h, no_t1_h})

    # ── entry: (label, representative fill, (fill lo, fill hi), bar index, opened_ms, conditions)
    entries, terminal, notes = [], [], []
    first = decide_long_entry(trade_type=trade_type, planned_entry=planned_entry,
                              current_price=bars[0].open, stop_loss=stop_loss,
                              invalidation_price=invalidation_price)
    if first.action == "reject":
        return OhlcUncertainty(OHLC_VERSION, "rejected", first.reason,
                               assumptions=("A_FIRST_OBS_AT_OPEN",))
    if first.action == "market":
        b0 = bars[0]
        entries.append(("market_at_open", b0.open, (b0.open, b0.open), 0, b0.open_ms,
                        ("A_FIRST_OBS_AT_OPEN",)))
    else:
        deadline = decision_ms + ADMISSION_WINDOW_MS
        for k, b in enumerate(bars):
            if b.open_ms >= deadline:
                break
            if b.low > planned_entry:
                continue
            if b.open_ms + bar_ms > deadline:
                notes.append("entry_bar_straddles_admission_deadline")
                terminal.append(OhlcScenario("limit_late", (), "not_filled", "admission_window_expired"))
            p_hi = min(planned_entry, b.high) if k > 0 and b.open <= planned_entry else planned_entry
            p_lo = max(b.low, math.nextafter(rejection, math.inf)) if b.low <= rejection else b.low
            if b.low <= rejection:
                terminal.append(OhlcScenario("limit_rejected", (), "rejected",
                                             "signal_invalidated_before_fill",
                                             conditional_on=("A_OBS_IN_BAR",)))
            if p_lo <= p_hi:
                plan = float(planned_entry)
                be = min(target_1 / plan, (1 + roundtrip_cost) / (1 - stop_slippage))
                ratios = [target_1 / plan, target_2 / plan, target_3 / plan, stop_loss / plan, be, 1.0]
                if invalidation_price is not None:
                    ratios.append(invalidation_price / plan)
                later = bars[k:]
                xs = [x for bb in later for x in (bb.high, bb.low, bb.close)]
                trail = [bb.high * (1 - TripleBarrierConfig.trail_stop_pct / 100) for bb in later]
                regions = _fill_regions(p_lo, p_hi, ratios, xs, trail, max_fill_points)
                if regions is None:
                    return insufficient("entry_fill_price_unresolved", ("fill_breakpoints_over_cap",))
                for rep, a, z in regions:
                    for tlab, t in (("early", b.open_ms), ("late", b.open_ms + bar_ms - 1)):
                        entries.append((f"limit_{a:.10g}_{z:.10g}_{tlab}", rep, (a, z), k, t,
                                        ("A_OBS_IN_BAR", "A_FILL_TIME_IN_BAR")))
            break
        if not entries and not terminal:
            return OhlcUncertainty(OHLC_VERSION, "not_filled", "limit_not_reached")

    # ── exits ──
    for label, fill, span, k, opened, conds in entries:
        try:
            br0 = rebase_long_bracket(planned_entry, fill, target_1, target_2, target_3, stop_loss)
        except ValueError as exc:
            terminal.append(OhlcScenario(label, (), "rejected", f"bracket_invalid:{exc}"))
            continue
        cfg = TripleBarrierConfig(symbol="OHLC", entry=br0["entry_price"], target_1=br0["target_1"],
                                  target_2=br0["target_2"], target_3=br0["target_3"],
                                  stop_loss=br0["stop_loss"], trade_amount=trade_amount,
                                  expiry_h=expiry_h, t1_expiry_h=t1_h, no_t1_expiry_h=no_t1_h,
                                  stop_slippage=stop_slippage, roundtrip_cost=roundtrip_cost)
        stop_inv = invalidation_price * fill / planned_entry if invalidation_price is not None else None
        targets = {1: cfg.target_1, 2: cfg.target_2, 3: cfg.target_3}
        kw = dict(trade_amount=trade_amount, min_notional=min_notional)

        def finish(c: _Branch, reason: str, worst_abs, best: float, best_scaled: bool,
                   bar_i: int, cond: tuple):
            """Price the terminal leg over the whole fill region along THIS path. A rebased price
            (a level) scales with the fill, so its gross % is constant; an absolute bar price
            (low, high, open, close, a peak-based trail) is evaluated at both region ends."""
            g_w, g_b = [], []
            for f in (span[0], fill, span[1]):
                bf = best * f / fill if best_scaled else best
                wf = bf if worst_abs is None else min(worst_abs, bf)
                g_w.append(c.realized_pct + (wf / f - 1) * 100 * c.remaining)
                g_b.append(c.realized_pct + (bf / f - 1) * 100 * c.remaining)
            w0 = best if worst_abs is None else min(worst_abs, best)
            sc = OhlcScenario(label, c.path, "closed", None, span, reason, bar_i, c.state.highest_target,
                              c.remaining, (w0, best), (min(g_w), max(g_b)),
                              tuple(dict.fromkeys(conds + cond)))
            if _outcome(sc) not in {_outcome(t) for t in terminal}:
                terminal.append(sc)

        def stop_is_rebased(c: _Branch, res) -> bool:
            level, _ = c.state.effective_stop(cfg)
            if res.exit_price < round(level * (1 - stop_slippage), 8):   # _stop_result rounds to 8 dp
                return False                                    # gap: filled at the bar open
            if c.state.highest_target >= 2:                     # trailing: T1 floor vs peak-based
                return cfg.target_1 >= c.state.peak * (1 - cfg.trail_stop_pct / 100)
            return True                                         # original stop / break-even

        levels = (cfg.target_1, cfg.target_2, cfg.target_3, cfg.stop_loss, cfg.net_break_even_stop())

        def settle(c: _Branch, res, b: Bar, i: int, deadline_bar: bool):
            """Record a terminal event, or return the branch to keep it alive."""
            if res == "invalidation":
                finish(c, "signal_candle_invalidation", b.low, b.high, False, i, ("A_OBS_IN_BAR",))
            elif res.exit_reason in STOP_REASONS:
                finish(c, res.exit_reason, b.low * (1 - stop_slippage), res.exit_price,
                       stop_is_rebased(c, res), i, ("A_OBS_IN_BAR",))
            elif res.exit_reason == "T3":
                finish(c, "T3", None, res.exit_price, True, i, ("A_TARGET_TOUCH",))
            elif deadline_bar:
                finish(c, res.exit_reason, b.low, b.high, False, i, ("A_EXPIRY_IN_BAR",))
            else:
                finish(c, res.exit_reason, None, res.exit_price, False, i, ())

        live = [_Branch(TripleBarrierState(peak=cfg.entry), 0.0, 0.0, 1.0, ())]
        for i in range(k, len(bars)):
            b = bars[i]
            h0 = max(0.0, (b.open_ms - opened) / 3_600_000)
            h1 = max(0.0, (b.open_ms + bar_ms - opened) / 3_600_000)
            deadline_bar = any(h0 < d <= h1 for d in deadlines)
            fill_bar = i == k
            start = fill if fill_bar else b.open
            way = sorted({b.open, b.low, b.high, b.close, start}
                         | {x for x in levels if b.low <= x <= b.high})
            nxt, seen_live = [], set()
            for br in live:
                ends = []                              # (branch, result | None, waypoint path)
                queue, seen = [], set()
                if br.pending_invalidation and br.state.highest_target == 0:
                    # A REST poll checks the closed candle BEFORE any exit (track_open_trades), so
                    # the bar's first observation may close it even through a gap below the stop.
                    ends.append((_clone(br), "invalidation", ("rest_check",)))
                c0 = _clone(br)
                r0 = None if fill_bar else _point(cfg, targets, c0, b.open, h0, gap_open=True, **kw)
                if r0 is not None:
                    ends.append((c0, r0, (b.open,)))
                else:
                    queue.append((c0, start, start == b.low, start == b.high, (start,)))
                while queue:
                    c, pos, vl, vh, wp = queue.pop()
                    sk = (_key(c), pos, vl, vh)
                    if sk in seen:
                        continue
                    seen.add(sk)
                    if len(seen) > 20 * max_branches:
                        return insufficient("intrabar_state_limit_exceeded", tuple(notes))
                    if deadline_bar:                   # the first observation after the deadline
                        e = _clone(c)
                        r = _point(cfg, targets, e, pos, h1, gap_open=False, **kw)
                        if r is not None:
                            ends.append((e, r, wp + ("expiry",)))
                    if c.pending_invalidation and c.state.highest_target == 0:
                        ends.append((_clone(c), "invalidation", wp + ("rest_check",)))
                    if fill_bar or (vl and vh):        # the bar can close from here
                        e = _clone(c)
                        r = _point(cfg, targets, e, b.close, h1, gap_open=False, **kw)
                        if r is None and e.pending_invalidation and e.state.highest_target == 0:
                            r = "invalidation"         # the REST check must happen in this bar
                        ends.append((e, r, wp + (b.close,)))
                    for w in way:
                        if w == pos:
                            continue
                        e = _clone(c)
                        r = _point(cfg, targets, e, w, h0, gap_open=False, **kw)
                        if r is not None:
                            ends.append((e, r, wp + (w,)))
                        else:
                            queue.append((e, w, vl or w == b.low, vh or w == b.high, wp + (w,)))
                distinct = {(_key(e), r if isinstance(r, str) or r is None
                             else (r.exit_reason, r.exit_price)) for e, r, _ in ends}
                for e, r, wp in ends:
                    if len(distinct) > 1:
                        e.path = e.path + ((i, ">".join(x if isinstance(x, str) else f"{x:.10g}"
                                                         for x in wp)),)
                    if r is not None:
                        settle(e, r, b, i, deadline_bar)
                    else:
                        e.pending_invalidation = bool(
                            stop_inv is not None and e.state.highest_target == 0 and b.close <= stop_inv)
                        if _key(e) not in seen_live:
                            seen_live.add(_key(e))
                            nxt.append(e)
            live = nxt
            if len(live) + len(terminal) > max_branches:
                return insufficient("branch_limit_exceeded", tuple(notes))
            if not live:
                break
        for br in live:
            sc = OhlcScenario(label, br.path, "open_at_end", "insufficient_bars", span,
                              target_reached=br.state.highest_target,
                              remaining_fraction=br.remaining, conditional_on=conds)
            if _outcome(sc) not in {_outcome(t) for t in terminal}:
                terminal.append(sc)

    closed = [s for s in terminal if s.status == "closed"]
    relevant_bars = len({p[0] for s in terminal for p in s.path})
    used = tuple(dict.fromkeys(a for s in terminal for a in s.conditional_on))
    reasons = tuple(sorted({s.exit_reason or s.status for s in terminal}))
    env = ((min(s.gross_pct_interval[0] for s in closed), max(s.gross_pct_interval[1] for s in closed))
           if closed else None)
    if any(s.status == "open_at_end" for s in terminal):
        status, reason = "INSUFFICIENT_INFORMATION", "bars_end_before_exit"
    elif len({(s.status, s.exit_reason, s.exit_bar, s.target_reached) for s in terminal}) > 1:
        status, reason = "PATH_AMBIGUOUS", None
    elif closed and (len({s.gross_pct_interval for s in closed}) > 1
                     or any(s.gross_pct_interval[0] != s.gross_pct_interval[1] for s in closed)):
        status, reason = "FILL_PRICE_UNCERTAIN", None
    elif closed:
        status, reason = "DETERMINED", None
    else:
        status, reason = terminal[0].status, terminal[0].reason
    return OhlcUncertainty(OHLC_VERSION, status, reason, tuple(terminal), reasons, env,
                           env[0] if env else None, relevant_bars, used, tuple(dict.fromkeys(notes)))


# ── dispatcher ────────────────────────────────────────────────────────────

def replay(mode: str, **kw):
    """Run one named mode. ``legacy_bar_v1`` and ``ohlc_uncertainty_v1`` take bars;
    ``tracker_event_v1`` takes polls. Unknown modes fail closed."""
    if mode == "legacy_bar_v1":
        return replay_bracket(**kw)
    if mode == "tracker_event_v1":
        return tracker_poll_model(**kw)
    if mode == "ohlc_uncertainty_v1":
        return ohlc_uncertainty(**kw)
    raise ValueError(f"unknown_replay_mode:{mode}")


def legacy_legs(o, *, planned_entry: float, target_1: float, target_2: float, target_3: float,
                stop_loss: float, stop_slippage: float = 0.001, trade_amount: float = 50.0,
                min_notional: float = 5.0) -> list:
    """ExecutedLeg list for a closed legacy outcome (reference = level / open; exec = x (1 - s))."""
    if o.status != "closed":
        raise ValueError("outcome_not_closed")
    br = rebase_long_bracket(planned_entry, o.fill_price, target_1, target_2, target_3, stop_loss)
    targets = {1: br["target_1"], 2: br["target_2"], 3: br["target_3"]}
    legs = [ExecutedLeg("entry", 1.0, o.fill_price, o.fill_price, o.entry_action == "market")]
    fills = fills_between(previous_target=0, reached_target=o.target_reached, entry=br["entry_price"],
                          targets=targets, trade_amount=trade_amount, min_notional=min_notional)
    legs += [ExecutedLeg(f"target_{f.target}", f.fraction, f.price, f.price, False) for f in fills]
    rem = max(0.0, 1.0 - sum(f.fraction for f in fills))
    if rem > 0:
        ref = o.exit_price / (1 - stop_slippage) if o.exit_reason in STOP_REASONS else o.exit_price
        legs.append(ExecutedLeg(o.exit_reason, rem, ref, o.exit_price, True))
    return legs


# ── Phase G: synthetic calibration-bias grid ──────────────────────────────
#
# Deterministic synthetic paths only. Rows quantify how the MODELS differ on the same path; they
# are not estimates of how often anything happens in a market, and say nothing about profitability.

SYNTH_SPEED_PCT_PER_S = 0.01          # declared synthetic price speed (not a market estimate)
SYNTH_POLL_PHASE = 0.5                # first poll after a crossing lands mid-interval (declared)


def synthetic_stop_path(*, stop_distance_pct: float, poll_s: float, gap_pct: float,
                        partial_state: int, entry: float = 100.0, t0_ms: int = 0,
                        speed_pct_per_s: float = SYNTH_SPEED_PCT_PER_S):
    """Bracket + polls for one synthetic stop exit after ``partial_state`` targets (0, 1 or 2).

    The price moves linearly at ``speed`` between waypoints; at the final descent it jumps by
    ``gap_pct`` (of the level) at the moment it crosses the standing stop. Polls are taken every
    ``poll_s`` seconds; the first poll after the crossing is SYNTH_POLL_PHASE of an interval later."""
    d = stop_distance_pct / 100
    br = dict(trade_type="momentum", planned_entry=entry, stop_loss=entry * (1 - d),
              target_1=entry * (1 + 0.8 * d), target_2=entry * (1 + 1.6 * d),
              target_3=entry * (1 + 2.4 * d), timeframe="4h")
    cfg = TripleBarrierConfig(symbol="S", entry=entry, target_1=br["target_1"], target_2=br["target_2"],
                              target_3=br["target_3"], stop_loss=br["stop_loss"])
    peak = {0: entry, 1: br["target_1"] * 1.0005, 2: br["target_2"] * 1.0005}[partial_state]
    st = TripleBarrierState(peak=peak, highest_target=partial_state)
    level = st.effective_stop(cfg)[0]
    v = speed_pct_per_s / 100 * entry                    # price units per second
    ms = int(poll_s * 1000)
    polls, t, px = [Poll(t0_ms, entry)], t0_ms, entry
    for target in ([peak] if partial_state else []) + [level]:
        while True:                                      # walk to the waypoint, polling on the way
            step = v * poll_s * (1 if target > px else -1)
            nxt = px + step
            if (step > 0 and round(nxt, 8) >= target) or (step < 0 and round(nxt, 8) <= target):
                break                                    # polls on the way stay strictly short
            t += ms
            px = nxt
            polls.append(Poll(t, round(px, 8)))
        if target == peak and partial_state:             # touch the waypoint exactly once
            t += ms
            px = target
            polls.append(Poll(t, round(px, 8)))
    # crossing: the next poll is SYNTH_POLL_PHASE of an interval after the level is crossed
    remaining_to_level = (px - level) / v                # seconds from the last poll to the level
    t_cross_ms = t + int(remaining_to_level * 1000)
    t_obs = t_cross_ms + int(SYNTH_POLL_PHASE * ms)
    obs = level * (1 - gap_pct / 100) - v * SYNTH_POLL_PHASE * poll_s
    polls.append(Poll(t_obs, round(obs, 8)))
    polls.append(Poll(t_obs + ms, round(obs, 8)))
    return br, polls, level, t_cross_ms


def bias_row(*, stop_distance_pct: float, poll_s: float, gap_pct: float, partial_state: int) -> dict:
    """One grid row: tracker-equivalent (Mode 2) vs legacy (Mode 1) vs OHLC interval (Mode 3)."""
    br, polls, level, t_cross = synthetic_stop_path(stop_distance_pct=stop_distance_pct, poll_s=poll_s,
                                                    gap_pct=gap_pct, partial_state=partial_state)
    sig = polls[0].t_ms
    m2 = tracker_poll_model(**br, polls=polls, signal_ms=sig)
    bars = bars_from_polls(polls, "15m", start_ms=sig)
    kw = {k: v for k, v in br.items() if k != "timeframe"}
    m1 = replay_bracket(**kw, signal_timeframe="4h", bars=bars, bar_timeframe="15m", decision_ms=sig)
    m3 = ohlc_uncertainty(**kw, signal_timeframe="4h", bars=bars, bar_timeframe="15m", decision_ms=sig)
    l2 = cost_ledger(legs_from_poll_outcome(m2))
    l1 = cost_ledger(legacy_legs(m1, **{k: v for k, v in kw.items() if k != "trade_type"}))
    bar_end = (t_cross - sig) // 900_000 * 900_000 + sig + 900_000
    return {
        "stop_distance_pct": stop_distance_pct, "poll_s": poll_s, "gap_pct": gap_pct,
        "partial_state": partial_state, "remaining_fraction": m2.remaining_fraction,
        "reason_tracker": m2.exit_reason, "reason_legacy": m1.exit_reason,
        "fill_diff_bps_of_level": (m2.exit_price - m1.exit_price) / level * 1e4,
        "exit_delay_tracker_s": (m2.exit_t_ms - t_cross) / 1000,
        "exit_time_legacy_bar_end_s": (bar_end - t_cross) / 1000,
        "gross_diff_pp": m2.gross_pct - m1.gross_pct,
        "net_modeled_diff_usdt": l2.net_modeled_pnl_usdt - l1.net_modeled_pnl_usdt,
        "legacy_label_tracker": l2.legacy_economic_result, "legacy_label_replay": l1.legacy_economic_result,
        "mode3_status": m3.status,
        "mode3_envelope_pct": m3.conditional_gross_envelope_pct,
        "tracker_inside_mode3": bool(m3.conditional_gross_envelope_pct
                                     and m3.conditional_gross_envelope_pct[0] - 1e-7 <= m2.gross_pct
                                     <= m3.conditional_gross_envelope_pct[1] + 1e-7),
    }


def bias_grid(distances=(1.0, 2.0, 4.0), polls=(1, 5, 30, 60, 300), gaps=(0.0, 0.25, 1.0),
              states=(0, 1, 2)) -> list:
    return [bias_row(stop_distance_pct=d, poll_s=c, gap_pct=g, partial_state=s)
            for d in distances for c in polls for g in gaps for s in states]


__all__ = ["VERSION", "MODES", "ASSUMPTIONS", "OhlcScenario", "OhlcUncertainty", "ohlc_uncertainty",
           "replay", "legacy_legs", "cost_ledger", "Poll", "Bar"]
