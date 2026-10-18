"""A42 experimental signal-quality diagnostics — pure functions, no I/O, no config reads.

Nothing in production imports this module. Every policy below is **disabled by
default** and versioned; a disabled policy reports what it *would* have done
(shadow) and never blocks. Wiring any of it into a decision path is a separate,
owner-authorised change.

Strategy behaviour and evaluation assumptions are kept apart on purpose:

* ``StrategyBracketRules`` mirrors what the frozen tracker does (25/50/25
  tranches, the net break-even stop after T1 computed with its own 0.3 % /
  0.1 % constants). These describe the strategy and are not tunable here.
* ``CostModel`` is the *evaluation* assumption used to turn gross paths into
  net returns (A42 baseline: 20 bps Binance Spot round trip; operational
  slippage identified separately).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Iterable, Mapping, Sequence

VERSION = "a42-sq-v1"

TIMEFRAME_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _finite(*values) -> bool:
    try:
        return all(math.isfinite(float(v)) for v in values)
    except (TypeError, ValueError):
        return False


def canonical_sha256(payload) -> str:
    """sha256 of sorted-key, compact, ASCII JSON (the project's canonical form)."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


# ── evaluation cost assumption ──────────────────────────────────────────────

@dataclass(frozen=True)
class CostModel:
    """Round-trip cost in percentage points of notional, by component."""
    exchange_fee_roundtrip_pct: float = 0.20   # 0.10 % per side, Binance Spot baseline
    entry_slippage_pct: float = 0.0            # operational, identified separately
    exit_slippage_pct: float = 0.0             # operational, identified separately
    stop_slippage_frac: float = 0.001          # applied to stop fills (tracker STOP_SLIPPAGE)
    include_spread: bool = False               # add the observed spread (half in, half out)
    label: str = "binance_spot_baseline_20bps"

    def validate(self) -> list[str]:
        errors = []
        for name in ("exchange_fee_roundtrip_pct", "entry_slippage_pct", "exit_slippage_pct"):
            value = getattr(self, name)
            if not _finite(value) or not 0 <= value < 5:
                errors.append(f"{name}_out_of_range")
        if not _finite(self.stop_slippage_frac) or not 0 <= self.stop_slippage_frac < 0.05:
            errors.append("stop_slippage_frac_out_of_range")
        return errors

    def roundtrip_pct(self, spread_pct: float | None = None) -> float:
        cost = self.exchange_fee_roundtrip_pct + self.entry_slippage_pct + self.exit_slippage_pct
        if self.include_spread:
            if spread_pct is None or not _finite(spread_pct) or spread_pct < 0:
                raise ValueError("spread_required_by_cost_model")
            cost += float(spread_pct)
        return cost

    @classmethod
    def tracker_accounting(cls) -> "CostModel":
        """What Paper books today: FEE_ROUNDTRIP_PCT 0.3 = 0.2 fee + 0.1 slippage."""
        return cls(exit_slippage_pct=0.10, label="tracker_accounting_30bps")


@dataclass(frozen=True)
class StrategyBracketRules:
    """Frozen tracker exit behaviour (descriptive mirror, not a tuning surface)."""
    fractions: tuple = (0.25, 0.50, 0.25)      # partial_25_50_25_v1
    break_even_roundtrip: float = 0.003        # triple_barrier.ROUNDTRIP_COST_DEFAULT
    break_even_stop_slippage: float = 0.001    # triple_barrier.STOP_SLIPPAGE_DEFAULT

    def validate(self) -> list[str]:
        errors = []
        if len(self.fractions) != 3 or any(not _finite(f) or f < 0 for f in self.fractions) \
                or abs(sum(self.fractions) - 1.0) > 1e-9:
            errors.append("fractions_must_be_three_nonnegative_summing_to_1")
        if not 0 <= self.break_even_roundtrip < 0.05 or not 0 <= self.break_even_stop_slippage < 0.05:
            errors.append("break_even_constants_out_of_range")
        return errors


# ── bracket geometry ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BracketGeometry:
    valid: bool
    errors: tuple
    entry: float
    stop: float
    t1: float
    t2: float
    t3: float
    risk_pct: float = float("nan")
    t1_pct: float = float("nan")
    t2_pct: float = float("nan")
    t3_pct: float = float("nan")
    t1_r: float = float("nan")
    t2_r: float = float("nan")
    t3_r: float = float("nan")
    atr_pct: float | None = None
    risk_atr: float | None = None
    t1_capped_below_1r: bool = False
    break_even_stop: float = float("nan")
    break_even_stop_is_t1: bool = False


def bracket_geometry(entry, stop, t1, t2, t3, *, atr=None,
                     rules: StrategyBracketRules = StrategyBracketRules()) -> BracketGeometry:
    """Describe a long bracket. Invalid geometry is reported, never repaired."""
    errors = []
    if not _finite(entry, stop, t1, t2, t3):
        return BracketGeometry(False, ("non_finite_level",), *(float("nan"),) * 5)
    entry, stop, t1, t2, t3 = (float(v) for v in (entry, stop, t1, t2, t3))
    if entry <= 0 or stop <= 0:
        errors.append("non_positive_level")
    if not stop < entry:
        errors.append("stop_not_below_entry")
    if not entry < t1 <= t2 <= t3:
        errors.append("targets_not_ordered_above_entry")
    if errors:
        return BracketGeometry(False, tuple(errors), entry, stop, t1, t2, t3)
    risk = entry - stop
    pct = lambda level: (level / entry - 1.0) * 100.0
    atr_pct = risk_atr = None
    if atr is not None:
        if not _finite(atr) or float(atr) <= 0:
            return BracketGeometry(False, ("invalid_atr",), entry, stop, t1, t2, t3)
        atr_pct, risk_atr = float(atr) / entry * 100.0, risk / float(atr)
    required = entry * (1 + rules.break_even_roundtrip) / (1 - rules.break_even_stop_slippage)
    be_stop = min(t1, required)                 # identical to TripleBarrierConfig.net_break_even_stop
    return BracketGeometry(
        True, (), entry, stop, t1, t2, t3,
        risk_pct=risk / entry * 100.0, t1_pct=pct(t1), t2_pct=pct(t2), t3_pct=pct(t3),
        t1_r=(t1 - entry) / risk, t2_r=(t2 - entry) / risk, t3_r=(t3 - entry) / risk,
        atr_pct=atr_pct, risk_atr=risk_atr,
        t1_capped_below_1r=(t1 - entry) < risk * 0.999,
        break_even_stop=be_stop, break_even_stop_is_t1=be_stop >= t1 - 1e-12 * entry,
    )


def path_payoffs(geometry: BracketGeometry, cost: CostModel, *, spread_pct: float | None = None,
                 rules: StrategyBracketRules = StrategyBracketRules()) -> dict:
    """Gross and net % of notional for the four canonical exit paths.

    ``t2_then_t1_floor`` is the *worst case* of the T2 path (the trailing stop is
    floored at T1); the real trail can only be higher. Expiry paths depend on
    the closing price and are not enumerated.
    """
    if not geometry.valid:
        raise ValueError("invalid_geometry")
    g, (f1, f2, f3) = geometry, rules.fractions
    e, ss = g.entry, cost.stop_slippage_frac
    stop_fill = lambda level: (level * (1 - ss) / e - 1.0) * 100.0
    gross = {
        "stop_before_t1": stop_fill(g.stop),
        "t1_then_break_even": f1 * g.t1_pct + (f2 + f3) * stop_fill(g.break_even_stop),
        "t2_then_t1_floor": f1 * g.t1_pct + f2 * g.t2_pct + f3 * stop_fill(g.t1),
        "t3": f1 * g.t1_pct + f2 * g.t2_pct + f3 * g.t3_pct,
    }
    c = cost.roundtrip_pct(spread_pct)
    return {"cost_pct": c, "gross": gross, "net": {k: v - c for k, v in gross.items()}}


def required_win_rate(win_pct: float, loss_pct: float) -> float | None:
    """Break-even probability of the winning path in a two-outcome model.

    ``loss_pct`` is negative. ``None`` means no hit rate can repay the loss
    (the "winning" path is itself net non-positive).
    """
    if not _finite(win_pct, loss_pct):
        raise ValueError("non_finite_payoff")
    if win_pct <= 0:
        return None
    if loss_pct >= 0:
        return 0.0
    return -loss_pct / (win_pct - loss_pct)


# ── per-candidate report (provenance + explainability) ─────────────────────

@dataclass(frozen=True)
class SignalQualityReport:
    version: str
    input_sha256: str
    inputs: dict
    cost_model: dict
    geometry: dict
    payoffs: dict | None
    metrics: dict
    flags: tuple
    explanation: tuple

    def to_dict(self) -> dict:
        return asdict(self)


_REPORT_KEYS = ("symbol", "timeframe", "trade_type", "entry_price", "stop_loss",
                "target_1", "target_2", "target_3", "atr")


def assess_candidate(candidate: Mapping, cost: CostModel = CostModel(),
                     rules: StrategyBracketRules = StrategyBracketRules()) -> SignalQualityReport:
    """Annotate one analyzer/signal dict. Reads only; never mutates ``candidate``."""
    inputs = {k: candidate.get(k) for k in _REPORT_KEYS}
    spread = (candidate.get("order_book") or {}).get("spread_pct")
    inputs["spread_pct"] = spread
    config_errors = cost.validate() + rules.validate()
    if config_errors:
        raise ValueError("invalid_configuration:" + ",".join(config_errors))
    geo = bracket_geometry(inputs["entry_price"], inputs["stop_loss"], inputs["target_1"],
                           inputs["target_2"], inputs["target_3"], atr=inputs["atr"], rules=rules)
    flags, notes, metrics, payoffs = [], [], {}, None
    if not geo.valid:
        flags.extend(f"invalid:{e}" for e in geo.errors)
        notes.append("geometry invalid; no economics computed")
    else:
        try:
            payoffs = path_payoffs(geo, cost, spread_pct=spread, rules=rules)
        except ValueError as exc:
            flags.append(f"cost_unavailable:{exc}")
            notes.append("cost model needs a spread the candidate does not carry")
    if payoffs is not None:
        net, c = payoffs["net"], payoffs["cost_pct"]
        metrics = {
            "cost_pct": c,
            "cost_over_risk": c / geo.risk_pct,
            "cost_over_t1": c / geo.t1_pct,
            "net_stop_pct": net["stop_before_t1"],
            "net_t1_path_pct": net["t1_then_break_even"],
            "net_t3_path_pct": net["t3"],
            "required_t1_rate_two_path": required_win_rate(net["t1_then_break_even"], net["stop_before_t1"]),
            "required_t3_rate_two_path": required_win_rate(net["t3"], net["stop_before_t1"]),
        }
        if geo.t1_capped_below_1r:
            flags.append("t1_capped_below_1r")
            notes.append(f"T1 is {geo.t1_r:.2f}R (resistance cap), not 1R")
        if geo.break_even_stop_is_t1:
            flags.append("break_even_stop_equals_t1")
            notes.append("T1 lies below the net break-even level, so the post-T1 stop sits at T1")
        if net["t1_then_break_even"] <= 0:
            flags.append("t1_path_net_non_positive")
            notes.append(f"touching T1 then stopping at break-even nets {net['t1_then_break_even']:+.3f}%")
        if c >= geo.risk_pct:
            flags.append("cost_exceeds_risk")
        elif c > 0.25 * geo.risk_pct:
            flags.append("cost_exceeds_quarter_risk")
        notes.append(f"cost {c:.3f}% = {c / geo.risk_pct:.2f}R of a {geo.risk_pct:.3f}% stop")
    return SignalQualityReport(
        version=VERSION, input_sha256=canonical_sha256(inputs), inputs=inputs,
        cost_model=asdict(cost), geometry=asdict(geo), payoffs=payoffs,
        metrics=metrics, flags=tuple(flags), explanation=tuple(notes))


# ── experimental policies (all disabled by default) ────────────────────────

@dataclass(frozen=True)
class PolicyDecision:
    policy: str
    version: str
    enabled: bool
    would_allow: bool
    reasons: tuple

    @property
    def allow(self) -> bool:
        """The only value a caller may act on: a disabled policy never blocks."""
        return self.would_allow or not self.enabled


@dataclass(frozen=True)
class CostCoveragePolicy:
    """A42-C1 gate. Parameters fixed from first principles, not from outcomes."""
    enabled: bool = False
    version: str = "a42-c1-cost-coverage-v1"
    max_cost_over_risk: float = 0.25
    require_t1_path_net_positive: bool = True

    def validate(self) -> list[str]:
        return [] if _finite(self.max_cost_over_risk) and 0 < self.max_cost_over_risk <= 1 \
            else ["max_cost_over_risk_out_of_range"]

    def evaluate(self, report: SignalQualityReport) -> PolicyDecision:
        reasons = []
        if not report.metrics:
            reasons.append("no_economics:" + ",".join(report.flags))
        else:
            if report.metrics["cost_over_risk"] > self.max_cost_over_risk:
                reasons.append("cost_over_risk_exceeds_cap")
            if self.require_t1_path_net_positive and report.metrics["net_t1_path_pct"] <= 0:
                reasons.append("t1_path_net_non_positive")
        return PolicyDecision("cost_coverage", self.version, self.enabled, not reasons, tuple(reasons))


def cost_aware_rank_key(report: SignalQualityReport, volume_usdt: float | None = None) -> tuple:
    """A42-C1 alternative ordering: lowest cost per unit of risk first.

    Unassessable candidates sort last. Ties fall back to the production key's
    liquidity / symbol / timeframe order so the ranking stays deterministic.
    """
    ratio = report.metrics.get("cost_over_risk") if report.metrics else None
    ratio = float(ratio) if ratio is not None else float("inf")
    return (ratio, -float(volume_usdt or 0.0), str(report.inputs.get("symbol") or ""),
            str(report.inputs.get("timeframe") or ""))


# ── correlated exposure ─────────────────────────────────────────────────────

def log_returns(closes: Sequence[float]) -> list[float]:
    out = []
    for prev, cur in zip(closes, closes[1:]):
        out.append(math.log(cur / prev) if _finite(prev, cur) and prev > 0 and cur > 0 else float("nan"))
    return out


def beta_and_correlation(asset_closes: Sequence[float], reference_closes: Sequence[float], *,
                         min_observations: int = 30) -> tuple:
    """(beta, correlation, n) of aligned closed-bar log returns; (None, None, n) if too thin."""
    if len(asset_closes) != len(reference_closes):
        raise ValueError("series_not_aligned")
    pairs = [(a, b) for a, b in zip(log_returns(asset_closes), log_returns(reference_closes))
             if _finite(a, b)]
    n = len(pairs)
    if n < min_observations:
        return None, None, n
    ma = sum(a for a, _ in pairs) / n
    mb = sum(b for _, b in pairs) / n
    cov = sum((a - ma) * (b - mb) for a, b in pairs) / (n - 1)
    va = sum((a - ma) ** 2 for a, _ in pairs) / (n - 1)
    vb = sum((b - mb) ** 2 for _, b in pairs) / (n - 1)
    if vb <= 0:
        return None, None, n
    corr = cov / math.sqrt(va * vb) if va > 0 else 0.0
    return cov / vb, corr, n


@dataclass(frozen=True)
class Exposure:
    symbol: str
    notional_usdt: float
    beta: float | None          # None = unknown → treated conservatively


@dataclass(frozen=True)
class CorrelatedExposurePolicy:
    """A42-C2 cap on BTC-beta-weighted long notional across open positions."""
    enabled: bool = False
    version: str = "a42-c2-beta-cap-v1"
    max_beta_weighted_notional_usdt: float = 75.0   # 1.5 × one $50 position of beta 1
    unknown_beta: float = 1.5                       # fail-closed assumption

    def validate(self) -> list[str]:
        errors = []
        if not _finite(self.max_beta_weighted_notional_usdt) or self.max_beta_weighted_notional_usdt <= 0:
            errors.append("cap_must_be_positive")
        if not _finite(self.unknown_beta) or self.unknown_beta < 1:
            errors.append("unknown_beta_must_be_at_least_1")
        return errors

    def beta_weighted(self, positions: Iterable[Exposure]) -> float:
        total = 0.0
        for p in positions:
            beta = p.beta if p.beta is not None and _finite(p.beta) else self.unknown_beta
            total += abs(beta) * float(p.notional_usdt)
        return total

    def evaluate(self, open_positions: Sequence[Exposure], candidate: Exposure) -> PolicyDecision:
        reasons = []
        if any(p.symbol == candidate.symbol for p in open_positions):
            reasons.append("symbol_already_open")
        if self.beta_weighted([*open_positions, candidate]) > self.max_beta_weighted_notional_usdt + 1e-9:
            reasons.append("beta_weighted_cap_exceeded")
        return PolicyDecision("correlated_exposure", self.version, self.enabled, not reasons, tuple(reasons))


# ── duplicate, staleness and continuity checks ─────────────────────────────

def signal_fingerprint(symbol: str, timeframe: str, trade_type: str | None, candle_close_ms: int) -> str:
    """Identity of a setup: one closed bar can produce at most one admissible signal."""
    return canonical_sha256([VERSION, str(symbol), str(timeframe), str(trade_type), int(candle_close_ms)])[:32]


def split_duplicates(signals: Iterable[Mapping]) -> tuple[list, list]:
    """Keep the first signal per fingerprint (input order); return (kept, duplicates)."""
    seen, kept, dupes = set(), [], []
    for s in signals:
        fp = signal_fingerprint(s["symbol"], s["timeframe"], s.get("trade_type"), s["candle_close_ms"])
        (dupes if fp in seen else kept).append(s)
        seen.add(fp)
    return kept, dupes


@dataclass(frozen=True)
class Staleness:
    age_ms: int
    age_bars: float
    admissible: bool
    reason: str | None


def signal_staleness(candle_close_ms: int, decision_ms: int, timeframe: str, *,
                     max_age_bars: float = 1.0) -> Staleness:
    """A decision must come after its bar closed and within ``max_age_bars`` bars."""
    if timeframe not in TIMEFRAME_MS:
        return Staleness(0, float("nan"), False, "unknown_timeframe")
    age = int(decision_ms) - int(candle_close_ms)
    bars = age / TIMEFRAME_MS[timeframe]
    if age < 0:
        return Staleness(age, bars, False, "decision_before_bar_close")
    if bars > max_age_bars:
        return Staleness(age, bars, False, "stale_signal")
    return Staleness(age, bars, True, None)


def bar_gaps(open_times_ms: Sequence[int], timeframe: str) -> list[tuple]:
    """(after_open_ms, missing_bar_count) for every hole in a closed-bar series."""
    step = TIMEFRAME_MS[timeframe]
    gaps = []
    for prev, cur in zip(open_times_ms, open_times_ms[1:]):
        delta = int(cur) - int(prev)
        if delta <= 0:
            gaps.append((int(prev), -1))           # non-increasing: corrupt ordering
        elif delta != step:
            gaps.append((int(prev), delta // step - 1 if delta % step == 0 else -1))
    return gaps


def validate_policies(*objects) -> dict:
    """Map each object's class name to its validation errors (empty = valid)."""
    return {type(o).__name__: o.validate() for o in objects}
