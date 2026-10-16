"""A46 trade-geometry engine — pure, deterministic, production-disconnected research code.

Baseline geometry is NOT re-implemented: ``baseline_bracket`` calls the shared production-
equivalent ``shared.strategy_math.calculate_signal_levels`` (held to the analyzer's
``_calculate_levels`` by tests), and every exit path is priced with the tracker's own
``partial_exits.fills_between`` / ``aggregate_close`` and the ``triple_barrier`` break-even rule.

What is new here:
* decision-time reference levels and T1-cap provenance (A45 W3);
* an exact per-leg cost ledger (fee per side on each leg's value, half-spread on market legs,
  stop slippage in the fill) next to the tracker's flat 0.3 % accounting;
* break-even requirements (minimum T1, required hit rates);
* three DISABLED, versioned geometry alternatives G1–G3.
Nothing in production imports this module (asserted by tests).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Mapping

import pandas as pd

from shared.partial_exits import aggregate_close, fills_between, target_distribution
from shared.signal_quality import StrategyBracketRules, required_win_rate
from shared.strategy_math import calculate_signal_levels

VERSION = "a46-tg-v1"
BASELINE = "prod-59297305-geometry"
G1 = "a46-g1-independent-resistance-v1"
G2 = "a46-g2-cost-feasible-target-v1"
G3 = "a46-g3-volatility-consistent-entry-v1"
TF_RISK_CAP = {"1d": 0.03, "4h": 0.05, "1h": 0.04, "15m": 0.02}   # analyzer _calculate_levels
RESISTANCE_FILL = 0.99                                            # analyzer _calculate_levels
PATHS = ("stop_before_t1", "t1_then_break_even", "t2_then_t1_floor", "t3")


class GeometryError(ValueError):
    """Inputs are missing, non-finite or inconsistent; no geometry is produced."""


def _fin(x, name) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise GeometryError(f"{name}_missing") from None
    if not math.isfinite(v):
        raise GeometryError(f"{name}_non_finite")
    return v


def quantize(price: float, tick: float, mode: str) -> float:
    """Deterministic exchange-tick rounding ('floor' | 'ceil'); Paper itself uses round(x, 8)."""
    if tick <= 0 or not math.isfinite(price):
        raise GeometryError("tick_or_price_invalid")
    q = Decimal(str(price)) / Decimal(str(tick))
    q = q.to_integral_value(rounding=ROUND_FLOOR if mode == "floor" else ROUND_CEILING)
    return float(q * Decimal(str(tick)))


# ── execution-cost assumption (evaluation, not strategy) ───────────────────

@dataclass(frozen=True)
class ExecutionCosts:
    """Per-leg costs. Baseline: 0.10 % per side (20 bps round trip); spread/slippage separate."""
    fee_rate_per_side: float = 0.001
    entry_half_spread_pct: float = 0.0     # market entry crosses half the spread
    stop_half_spread_pct: float = 0.0      # stop exits are market orders
    entry_slippage_pct: float = 0.0
    stop_slippage_frac: float = 0.001      # tracker STOP_SLIPPAGE: stop fill = stop × (1 − s)
    label: str = "baseline_20bps"

    def validate(self) -> list[str]:
        limits = {"fee_rate_per_side": 0.01,          # fraction per side (< 1 %)
                  "entry_half_spread_pct": 5.0,       # percent of price
                  "stop_half_spread_pct": 5.0,
                  "entry_slippage_pct": 5.0,
                  "stop_slippage_frac": 0.05}         # fraction of the stop price
        return sorted(n for n, cap in limits.items()
                      if not (math.isfinite(getattr(self, n)) and 0 <= getattr(self, n) < cap))


TRACKER_FLAT_COST_PCT = 0.3                # config.FEE_ROUNDTRIP_PCT (tracker / A38 accounting)


# ── decision-time references ───────────────────────────────────────────────

@dataclass(frozen=True)
class References:
    close: float
    atr: float
    breakout_level: float          # max high of the PRIOR breakout_n bars (excludes the decision bar)
    structure_low: float           # min low of the last 20 bars (includes the decision bar)
    window_high: float             # max high of the last 20 bars (includes the decision bar)
    window_high_is_decision_bar: bool


def references(df: pd.DataFrame, *, breakout_n: int = 20) -> References:
    if df is None or len(df) < breakout_n + 1:
        raise GeometryError("history_insufficient")
    last = df.iloc[-1]
    close, atr = _fin(last["close"], "close"), _fin(last["atr"], "atr")
    if close <= 0:
        raise GeometryError("close_non_positive")
    if atr <= 0:
        raise GeometryError("atr_non_positive")
    recent = df.tail(20)
    highs = recent["high"].astype(float)
    if not all(math.isfinite(h) for h in highs) or not all(math.isfinite(float(x)) for x in recent["low"]):
        raise GeometryError("structure_non_finite")
    return References(close, atr, _fin(df["high"].iloc[-(breakout_n + 1):-1].max(), "breakout_level"),
                      _fin(recent["low"].min(), "structure_low"), float(highs.max()),
                      int(highs.values.argmax()) == len(highs) - 1)


# ── bracket ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Bracket:
    version: str
    trade_type: str
    timeframe: str
    entry: float
    stop: float
    invalidation: float
    t1: float
    t2: float
    t3: float
    stop_policy: str
    valid: bool
    reject_reason: str | None
    refs: References
    t1_cap: Mapping = field(default_factory=dict)   # {'active', 'source', 'level'}

    @property
    def risk(self) -> float:
        return self.entry - self.stop


def resistance_cap(entry: float, risk: float, resistance: float | None) -> float:
    """The analyzer's T1 rule: if 1R > resistance > entry and 0.99 × resistance > entry,
    T1 = 0.99 × resistance; otherwise T1 = 1R. (Parity with production asserted by tests.)"""
    t1 = entry + risk
    if resistance is not None and t1 > resistance > entry:
        fill = resistance * RESISTANCE_FILL
        if fill > entry:
            t1 = fill
    return t1


def _check(timeframe, trade_type):
    if timeframe not in TF_RISK_CAP:
        raise GeometryError("timeframe_invalid")
    if trade_type not in ("momentum", "reversion"):
        raise GeometryError("trade_type_unsupported")


def baseline_bracket(df: pd.DataFrame, timeframe: str, trade_type: str, *,
                     breakout_n: int = 20) -> Bracket:
    """Production geometry (via strategy_math) plus provenance of any T1 cap."""
    _check(timeframe, trade_type)
    refs = references(df, breakout_n=breakout_n)
    lv = calculate_signal_levels(df, timeframe, trade_type, breakout_n=breakout_n)
    risk = lv["entry"] - lv["stop"]
    uncapped = round(lv["entry"] + risk, 8)
    active = lv["stop_valid"] and lv["t1"] < uncapped - 1e-9 * max(1.0, lv["entry"])
    cap = {"active": bool(active),
           "source": ("decision_bar" if refs.window_high_is_decision_bar else "prior_bars") if active else None,
           "level": refs.window_high if active else None}
    return Bracket(BASELINE, trade_type, timeframe, lv["entry"], lv["stop"], lv["stop_invalidation"],
                   lv["t1"], lv["t2"], lv["t3"], lv["stop_policy"], bool(lv["stop_valid"]),
                   lv["stop_reject_reason"], refs, cap)


def independent_resistance(df: pd.DataFrame, entry: float) -> float | None:
    """G1 reference: the NEAREST confirmed swing high above entry among bars that closed before
    the decision bar. A swing high is a bar whose high exceeds the highs of the two bars on each
    side (all five already closed). None when no such level exists in the available history."""
    prior = df.iloc[:-1]["high"].astype(float).values
    best = None
    for i in range(2, len(prior) - 2):
        h = prior[i]
        if h > entry and h > max(prior[i - 2], prior[i - 1], prior[i + 1], prior[i + 2]):
            best = h if best is None else min(best, h)
    return best


def g1_bracket(df: pd.DataFrame, timeframe: str, trade_type: str, *, breakout_n: int = 20) -> Bracket:
    """G1: identical to baseline except T1 is capped only by an independent (decision-time,
    prior-bar, confirmed) resistance; with none, T1 = 1R."""
    base = baseline_bracket(df, timeframe, trade_type, breakout_n=breakout_n)
    if not base.valid:
        return replace(base, version=G1)
    res = independent_resistance(df, base.entry)
    t1 = round(resistance_cap(base.entry, base.risk, res), 8)
    active = t1 < round(base.entry + base.risk, 8) - 1e-9 * max(1.0, base.entry)
    return replace(base, version=G1, t1=t1,
                   t1_cap={"active": active, "source": "independent_swing_high" if active else
                           ("none_above_entry" if res is None else None), "level": res})


def g3_bracket(df: pd.DataFrame, timeframe: str, trade_type: str, *, breakout_n: int = 20,
               max_extension_atr: float = 0.75) -> Bracket:
    """G3 (momentum): plan the entry no higher than level + 0.75 ATR, so the production stop rule
    gives exactly R = 1 ATR (stop = level − 0.25 ATR = entry − 1 ATR). The tracker's existing
    no-chase rule then rests a limit there when price is above it. Reversion is unchanged.
    Stop rule, TF caps, target multiples and the T1-cap rule are the production ones."""
    base = baseline_bracket(df, timeframe, trade_type, breakout_n=breakout_n)
    if trade_type != "momentum" or not math.isfinite(base.refs.breakout_level):
        return replace(base, version=G3)
    r = base.refs
    entry = round(min(r.close, r.breakout_level + max_extension_atr * r.atr), 8)
    invalidation = r.breakout_level - 0.25 * r.atr
    stop = min(invalidation, entry - r.atr)
    if not 0 < stop < entry:
        return replace(base, version=G3, valid=False, reject_reason="invalid_stop_geometry")
    risk = entry - stop
    if risk / entry > TF_RISK_CAP[timeframe] + 1e-12:
        return replace(base, version=G3, entry=entry, stop=round(stop, 8), valid=False,
                       reject_reason="structural_risk_exceeds_cap")
    t1 = round(resistance_cap(entry, risk, r.window_high), 8)
    return replace(base, version=G3, entry=entry, stop=round(stop, 8),
                   invalidation=round(invalidation, 8), t1=t1, t2=round(entry + 1.8 * risk, 8),
                   t3=round(entry + 2.2 * risk, 8), valid=True, reject_reason=None,
                   t1_cap={"active": t1 < round(entry + risk, 8) - 1e-9 * entry,
                           "source": "decision_bar" if r.window_high_is_decision_bar else "prior_bars",
                           "level": r.window_high})


# ── exit economics ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Leg:
    kind: str            # entry | target | stop
    fraction: float
    price: float
    gross_usdt: float
    fee_usdt: float
    spread_usdt: float


@dataclass(frozen=True)
class Ledger:
    path: str
    legs: tuple
    gross_usdt: float
    cost_usdt: float
    net_usdt: float
    net_pct: float
    tracker_gross_pct: float
    tracker_flat_net_pct: float


def break_even_stop(b: Bracket, rules: StrategyBracketRules = StrategyBracketRules()) -> float:
    """triple_barrier.net_break_even_stop: min(T1, entry × (1 + rt) / (1 − slip))."""
    required = b.entry * (1 + rules.break_even_roundtrip) / (1 - rules.break_even_stop_slippage)
    return min(b.t1, required)


def exit_ledger(b: Bracket, path: str, costs: ExecutionCosts = ExecutionCosts(), *,
                notional: float = 50.0, min_notional: float = 5.0,
                rules: StrategyBracketRules = StrategyBracketRules()) -> Ledger:
    """Exact per-leg ledger for one canonical path. Gross uses the tracker's own functions."""
    if not b.valid:
        raise GeometryError(f"bracket_invalid:{b.reject_reason}")
    if path not in PATHS:
        raise GeometryError("path_unknown")
    if costs.validate():
        raise GeometryError("costs_invalid:" + ",".join(costs.validate()))
    targets = {1: b.t1, 2: b.t2, 3: b.t3}
    reached = {"stop_before_t1": 0, "t1_then_break_even": 1, "t2_then_t1_floor": 2, "t3": 3}[path]
    fills = fills_between(previous_target=0, reached_target=reached, entry=b.entry, targets=targets,
                          trade_amount=notional, min_notional=min_notional)
    remaining = max(0.0, 1.0 - sum(f.fraction for f in fills))
    stop_level = {"stop_before_t1": b.stop, "t1_then_break_even": break_even_stop(b, rules),
                  "t2_then_t1_floor": b.t1, "t3": None}[path]
    exit_price = stop_level * (1 - costs.stop_slippage_frac) if stop_level is not None else b.t3
    g_pct, g_usdt = aggregate_close(entry=b.entry, final_exit=exit_price, trade_amount=notional,
                                    realized_pct=sum(f.gross_pct_contribution for f in fills),
                                    realized_usdt=sum(f.gross_usdt for f in fills),
                                    remaining_fraction=remaining)
    legs = [Leg("entry", 1.0, b.entry, 0.0, notional * costs.fee_rate_per_side,
                notional * (costs.entry_half_spread_pct + costs.entry_slippage_pct) / 100)]
    for f in fills:
        value = notional * f.fraction * f.price / b.entry
        legs.append(Leg("target", f.fraction, f.price, f.gross_usdt, value * costs.fee_rate_per_side, 0.0))
    if remaining > 0:
        value = notional * remaining * exit_price / b.entry
        legs.append(Leg("stop", remaining, exit_price, (exit_price / b.entry - 1) * notional * remaining,
                        value * costs.fee_rate_per_side, value * costs.stop_half_spread_pct / 100))
    cost = sum(l.fee_usdt + l.spread_usdt for l in legs)
    return Ledger(path, tuple(legs), g_usdt, cost, g_usdt - cost, (g_usdt - cost) / notional * 100,
                  g_pct, g_pct - TRACKER_FLAT_COST_PCT)


def breakeven_requirements(b: Bracket, costs: ExecutionCosts = ExecutionCosts(), **kw) -> dict:
    """Minimum T1 distance for a non-negative T1→break-even path, and two-path hit rates."""
    net = {p: exit_ledger(b, p, costs, **kw).net_pct for p in PATHS}
    lo, hi = 1e-9, b.risk                                        # bisection on the T1 distance
    f = lambda d: exit_ledger(replace(b, t1=b.entry + d), "t1_then_break_even", costs, **kw).net_pct
    if f(hi) < 0:
        min_t1 = None
    else:
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
        min_t1 = hi / b.entry * 100
    return {"net_pct": net,
            "min_t1_pct_for_t1_path": min_t1,
            "t1_pct": (b.t1 / b.entry - 1) * 100,
            "gross_win_net_loss_t1_path": exit_ledger(b, "t1_then_break_even", costs, **kw).gross_usdt > 0
                                          and net["t1_then_break_even"] < 0,
            "required_t1_rate": required_win_rate(net["t1_then_break_even"], net["stop_before_t1"]),
            "required_t3_rate": required_win_rate(net["t3"], net["stop_before_t1"])}


# ── diagnostics and the G2 feasibility rule ────────────────────────────────

def diagnostics(b: Bracket, costs: ExecutionCosts = ExecutionCosts()) -> dict:
    r = b.refs
    out = {"version": b.version, "valid": b.valid, "reject_reason": b.reject_reason,
           "atr_pct": r.atr / r.close * 100, "t1_cap": dict(b.t1_cap), "flags": []}
    if not b.valid:
        return out
    risk = b.risk
    out.update({"risk_atr": risk / r.atr, "risk_pct": risk / b.entry * 100,
                "extension_atr": ((r.close - r.breakout_level) / r.atr) if b.trade_type == "momentum"
                else ((r.close - r.structure_low) / r.atr),
                "stop_anchor": "structure" if b.stop < b.entry - r.atr - 1e-9 * b.entry else "atr_floor",
                "t1_r": (b.t1 - b.entry) / risk, "t2_r": (b.t2 - b.entry) / risk,
                "t3_r": (b.t3 - b.entry) / risk})
    req = breakeven_requirements(b, costs)
    out["requirements"] = req
    if b.t1_cap.get("source") == "decision_bar":
        out["flags"].append("t1_capped_by_decision_bar")
    if b.t1 <= b.entry:
        out["flags"].append("t1_below_gross_breakeven")
    if req["net_pct"]["t1_then_break_even"] < 0:
        out["flags"].append("t1_path_net_negative")
    if req["gross_win_net_loss_t1_path"]:
        out["flags"].append("gross_win_net_loss")
    if risk / b.entry * 100 <= 2 * costs.fee_rate_per_side * 100:
        out["flags"].append("risk_not_above_round_trip_fee")
    return out


@dataclass(frozen=True)
class FeasibilityDecision:
    version: str
    enabled: bool
    would_allow: bool
    reasons: tuple

    @property
    def allow(self) -> bool:
        return self.would_allow or not self.enabled


@dataclass(frozen=True)
class CostFeasibleTarget:
    """G2: a bracket is feasible only if the T1 → break-even path is net non-negative under the
    actual 25/50/25 schedule and the stated costs (not 'the whole position exits at T1')."""
    enabled: bool = False
    version: str = G2
    costs: ExecutionCosts = ExecutionCosts()

    def evaluate(self, b: Bracket) -> FeasibilityDecision:
        if not b.valid:
            return FeasibilityDecision(self.version, self.enabled, False, (f"invalid:{b.reject_reason}",))
        net = exit_ledger(b, "t1_then_break_even", self.costs).net_pct
        reasons = () if net >= 0 else ("t1_path_net_negative",)
        return FeasibilityDecision(self.version, self.enabled, not reasons, reasons)
