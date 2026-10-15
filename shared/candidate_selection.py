"""A43 candidate selection: explicit eligibility, then ranking — pure; no production caller.

The live selector (``SignalEngine.find_best_signal_live`` @59297305) interleaves
eligibility and ranking and ranks by ``(spread, -volume, symbol, timeframe)``.
This module separates the two stages, names the objective, and offers:

* ``production_parity`` — an exact replica of ``_fixed_candidate_key`` used to
  prove parity (tests drive the real selector side by side);
* ``execution_quality_v2`` — same objective (cheapest execution, then deepest
  liquidity) but with explicit handling of invalid values and a hash
  tie-break, so ties no longer favour early-alphabet symbols or the ``'15m'``
  string. **Experimental, not enabled anywhere.**

Universe handling replaces the SQL ``ORDER BY symbol … LIMIT 200`` (which
would cut late-alphabet symbols) with a bounded, non-alphabetical cap that
reports what it dropped.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

from shared.signal_identity import integrity_check

SELECTION_VERSION = "a43-cs-v1"
OBJECTIVE = "minimise execution cost proxy (spread), then maximise liquidity (24h volume USDT)"


def _finite_nonneg(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


@dataclass(frozen=True)
class Candidate:
    symbol: str
    timeframe: str
    trade_type: str | None
    spread_pct: float | None          # None = missing or invalid (NaN/inf/negative)
    spread_raw: object
    order_book_valid: bool
    liquidity_usdt: float | None      # None = missing or invalid
    stop_valid: object                # True / False / None (legacy rows)
    stop_reject_reason: str | None
    data: Mapping = field(repr=False, compare=False, default_factory=dict)


def normalize(row: Mapping, liquidity_usdt=None) -> Candidate:
    """Accept an ``analysis_results`` row (``analysis_data`` str/dict) or a bare candidate dict."""
    data = row.get("analysis_data", row)
    if isinstance(data, str):
        data = json.loads(data)
    ob = data.get("order_book") or {}
    return Candidate(
        symbol=str(data.get("symbol") or row.get("symbol") or ""),
        timeframe=str(data.get("timeframe") or row.get("timeframe") or ""),
        trade_type=data.get("trade_type") or None,
        spread_pct=_finite_nonneg(ob.get("spread_pct")),
        spread_raw=ob.get("spread_pct"),
        order_book_valid=ob.get("valid") is True,
        liquidity_usdt=_finite_nonneg(liquidity_usdt),
        stop_valid=data.get("stop_valid"),
        stop_reject_reason=data.get("stop_reject_reason"),
        data=data,
    )


# ── eligibility ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EligibilityPolicy:
    max_spread_pct: float = 0.15                 # config.MAX_SPREAD_PCT default
    enforce_integrity: bool = False              # A43-B rules; OFF = production-equivalent
    strategy_version: str | None = None
    max_age_bars: float = 1.0
    reject_non_finite_spread: bool = False       # production lets NaN through (see A43-D)


def eligibility_reasons(c: Candidate, policy: EligibilityPolicy, *, open_symbols=frozenset(),
                        cooldown=frozenset(), throttled=frozenset(), emitted_keys=frozenset(),
                        decision_ms: int | None = None) -> tuple:
    """Rejection reasons in the production order; empty tuple = eligible.

    Production stops at the first reason; the full list is kept here for
    transparency, but ``reasons[0]`` equals the production decision.
    """
    reasons = []
    if not c.trade_type:
        return ("no_trade_setup",)
    if not c.order_book_valid or c.spread_raw is None:
        return ("order_book_unavailable",)
    if c.spread_pct is None:
        if policy.reject_non_finite_spread:
            return ("spread_invalid",)
        # production: float(nan) > limit is False → passes; negative spreads pass too
    elif c.spread_pct > policy.max_spread_pct:
        reasons.append("spread_exceeds_limit")
    if c.stop_valid is False:
        reasons.append(f"stop_rejected:{c.stop_reject_reason or 'invalid_signal_stop'}")
    if c.symbol in open_symbols:
        reasons.append("open_trade_exists")
    if c.symbol in cooldown:
        reasons.append("symbol_cooldown")
    if (c.trade_type, c.timeframe) in throttled:
        reasons.append("learned_gate_throttled")
    if policy.enforce_integrity:
        if decision_ms is None or not policy.strategy_version:
            reasons.append("integrity:inputs_missing")
        else:
            verdict = integrity_check(c.data, decision_ms=decision_ms,
                                      strategy_version=policy.strategy_version,
                                      emitted_keys=emitted_keys, max_age_bars=policy.max_age_bars)
            reasons.extend(verdict.reasons)
    return tuple(reasons)


# ── ranking ────────────────────────────────────────────────────────────────

def production_parity_key(c: Candidate) -> tuple:
    """Exact replica of ``SignalEngine._fixed_candidate_key`` (including its quirks)."""
    spread = float(c.spread_raw) if c.spread_raw is not None else float("inf")
    return (spread, -float(c.liquidity_usdt or 0.0), c.symbol, c.timeframe)


def _tie_hash(c: Candidate) -> str:
    ident = c.data.get("pit", {}).get("candidate_id") if isinstance(c.data.get("pit"), Mapping) else None
    basis = ident or f"{c.symbol}|{c.timeframe}|{c.trade_type}"
    return hashlib.sha256(f"{SELECTION_VERSION}|{basis}".encode()).hexdigest()


def execution_quality_v2_key(c: Candidate) -> tuple:
    """Spread asc; valid liquidity before missing, then liquidity desc; hash tie-break."""
    spread = c.spread_pct if c.spread_pct is not None else float("inf")
    liq_missing = c.liquidity_usdt is None
    return (spread, liq_missing, -(c.liquidity_usdt or 0.0), _tie_hash(c))


RANKERS: Mapping[str, Callable[[Candidate], tuple]] = {
    "production_parity": production_parity_key,
    "execution_quality_v2": execution_quality_v2_key,
}


@dataclass(frozen=True)
class SelectionResult:
    version: str
    objective: str
    ranker: str
    selected: Candidate | None
    ranked: tuple                      # ((candidate, position, key), …) eligible only, best first
    rejected: tuple                    # ((candidate, reasons), …) in input order
    selection_reason: str


def select(candidates: Sequence[Candidate], *, policy: EligibilityPolicy = EligibilityPolicy(),
           ranker: str = "production_parity", **state) -> SelectionResult:
    key = RANKERS[ranker]
    eligible, rejected = [], []
    for c in candidates:
        reasons = eligibility_reasons(c, policy, **state)
        (rejected.append((c, reasons)) if reasons else eligible.append(c))
    if ranker == "production_parity":
        # min() over a key that may contain NaN depends on input order — replicate exactly.
        best = min(eligible, key=key) if eligible else None
        ordered = ([best] + [c for c in eligible if c is not best]) if best else []
        rest = sorted(ordered[1:], key=lambda c: _nan_safe(key(c)))
        ranked_list = ([best] + rest) if best else []
    else:
        ranked_list = sorted(eligible, key=key)
        best = ranked_list[0] if ranked_list else None
    ranked = tuple((c, i + 1, key(c)) for i, c in enumerate(ranked_list))
    reason = ("no_eligible_candidate" if best is None
              else "single_eligible" if len(ranked_list) == 1 else f"best_by_{ranker}")
    return SelectionResult(SELECTION_VERSION, OBJECTIVE, ranker, best, ranked, tuple(rejected), reason)


def _nan_safe(key: tuple) -> tuple:
    return tuple((1, 0.0) if isinstance(v, float) and math.isnan(v) else (0, v) for v in key)


# ── candidate universe ─────────────────────────────────────────────────────

def production_query_window(rows: Iterable[Mapping], limit: int = 200) -> list:
    """Reproduce ``ORDER BY symbol, (analysis_data->>'total_score')::float DESC LIMIT 200``."""
    def score(r):
        data = r.get("analysis_data", r)
        if isinstance(data, str):
            data = json.loads(data)
        return float(data.get("total_score") or 0.0)
    return sorted(rows, key=lambda r: (r["symbol"], -score(r)))[:limit]


@dataclass(frozen=True)
class Universe:
    rows: tuple
    total: int
    dropped: tuple                    # (symbol, timeframe) of rows not considered
    capped: bool


def bounded_universe(rows: Iterable[Mapping], *, max_rows: int = 2000) -> Universe:
    """Consider every fresh row up to a hard cap; above it, drop by hash order, never by alphabet.

    The cap bounds memory/CPU (O(n log n) over at most ``max_rows`` rows) and
    every dropped row is reported, so truncation is never silent.
    """
    if max_rows < 1:
        raise ValueError("max_rows must be positive")
    rows = list(rows)
    if len(rows) <= max_rows:
        return Universe(tuple(rows), len(rows), (), False)
    order = sorted(rows, key=lambda r: hashlib.sha256(
        f"{SELECTION_VERSION}|{r['symbol']}|{r.get('timeframe', '')}".encode()).hexdigest())
    kept, dropped = order[:max_rows], order[max_rows:]
    return Universe(tuple(kept), len(rows), tuple((r["symbol"], r.get("timeframe")) for r in dropped), True)
