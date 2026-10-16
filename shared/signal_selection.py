"""S3 signal selection (s3-sel-v1): pure, deterministic, DISABLED. No production caller.

The operational selector, ``SignalEngine.find_best_signal_live`` (LIVE_LEARNING_MODE=true in
production), stays the baseline and is not modified. This module composes reviewed parts:
``candidate_selection`` (A43/A44: normalisation, non-alphabetical universe, hash tie-break) and
``signal_quality`` (A42: bracket geometry, cost model, cost-coverage policy). It adds the stages
the S3 audit found missing, each with machine-readable reason codes:

  0 universe      bounded, never alphabetical; every dropped row is reported
  1 data quality  mandatory before any scoring: known setup type, finite and strictly ordered
                  bracket (the tracker's rebase rule), stop explicitly validated, valid order book,
                  finite non-negative spread within the production limit, known liquidity
  2 state         open position, symbol cooldown, learned-gate throttle, emitted setup key
  3 integrity     A44 identity/freshness, only when ``enforce_integrity`` and inputs exist
  4 economics     execution feasibility: T1-then-break-even path net of modelled costs must be
                  > 0, and round-trip cost must not exceed ``max_cost_over_risk`` of the stop
  5 dedupe        one candidate per symbol and per setup key (best-ranked kept)
  6 ranking       lexicographic, no weights: cost/R asc, spread asc, liquidity desc, hash
  7 selection     top-1 (the production capacity rule); otherwise an explicit NO_TRADE

Why this ranking (engineering argument, not a performance claim): every eligible candidate is
traded under the same frozen exit rules, which pay in multiples of R. No validated information
distinguishes the gross edge of eligible setups (the indicator score has AUC about 0.50, so it is
deliberately NOT used). Under that stated no-information assumption, net expectancy in R equals
an unknown common gross term minus cost/R, so the candidate losing the smallest fraction of its
risk unit to modelled costs dominates. Spread, then liquidity, then a hash only break ties.
Timeframes are compared through cost/R, never by string order.

Thresholds: ``max_spread_pct`` is the production limit (config.MAX_SPREAD_PCT default 0.15).
``max_cost_over_risk`` 0.25 is A42-C1's first-principles cap and is EXPERIMENTAL. "T1 path net
positive" is arithmetic: a setup that loses money even when its first target is hit cannot be
economically attractive. Costs: 0.10 %/side (20 bps round trip, no BNB discount) plus the
observed spread plus a separately declared slippage assumption (default 0). Nothing here is
evidence of profitability.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Iterable, Mapping, Sequence

from shared.candidate_selection import (Candidate, _tie_hash, bounded_universe, normalize,
                                        production_parity_key)
from shared.signal_identity import IdentityError, identity_from_candidate, integrity_check
from shared.signal_quality import CostCoveragePolicy, CostModel, assess_candidate

VERSION = "s3-sel-v1"
ENABLED = False                       # nothing in production imports or calls this module
KNOWN_TRADE_TYPES = ("momentum", "reversion")

# Every code this module can emit, with its stage. Callers may rely on this vocabulary.
REASON_CODES = {
    "no_trade_setup": "data", "unknown_trade_type": "data", "bracket_missing": "data",
    "bracket_non_finite": "data", "bracket_not_ordered": "data", "stop_not_validated": "data",
    "stop_rejected": "data", "order_book_unavailable": "data", "spread_invalid": "data",
    "spread_exceeds_limit": "data", "liquidity_unknown": "data",
    "open_trade_exists": "state", "symbol_cooldown": "state", "learned_gate_throttled": "state",
    "setup_already_emitted": "state",
    "integrity_inputs_missing": "integrity", "integrity": "integrity",
    "cost_unavailable": "economics", "cost_over_risk_exceeds_cap": "economics",
    "t1_path_net_non_positive": "economics",
    "duplicate_symbol_lower_rank": "dedupe", "duplicate_setup_key": "dedupe",
    "not_selected_capacity": "selection", "selected": "selection",
}
NO_TRADE_REASONS = ("empty_universe", "no_eligible_candidate")


def _code(reason: str) -> str:
    return reason.split(":", 1)[0]


@dataclass(frozen=True)
class S3Policy:
    version: str = VERSION
    enabled: bool = False                     # experimental; must stay False until approved
    max_spread_pct: float = 0.15              # production limit (config.MAX_SPREAD_PCT default)
    max_cost_over_risk: float = 0.25          # A42-C1 first-principles cap — EXPERIMENTAL
    require_t1_path_net_positive: bool = True  # arithmetic necessity, not a tuned threshold
    fee_roundtrip_pct: float = 0.20           # 0.10 %/side Binance Spot, no BNB discount
    slippage_roundtrip_pct: float = 0.0       # declared assumption, reported separately
    require_liquidity: bool = True            # unknown 24h volume -> cannot verify executability
    max_universe_rows: int = 2000
    enforce_integrity: bool = False           # A44 identity/freshness (needs candle identity)
    strategy_version: str | None = None

    def validate(self) -> list[str]:
        errors = []
        for name in ("max_spread_pct", "fee_roundtrip_pct", "slippage_roundtrip_pct"):
            v = getattr(self, name)
            if not (isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v < 5):
                errors.append(f"{name}_out_of_range")
        if not (math.isfinite(self.max_cost_over_risk) and 0 < self.max_cost_over_risk <= 1):
            errors.append("max_cost_over_risk_out_of_range")
        if self.max_universe_rows < 1:
            errors.append("max_universe_rows_out_of_range")
        if self.enforce_integrity and not self.strategy_version:
            errors.append("strategy_version_required_for_integrity")
        return errors

    def cost_model(self) -> CostModel:
        return CostModel(exchange_fee_roundtrip_pct=self.fee_roundtrip_pct,
                         exit_slippage_pct=self.slippage_roundtrip_pct, include_spread=True,
                         label=f"s3_{self.fee_roundtrip_pct:g}fee_{self.slippage_roundtrip_pct:g}slip_spread")


@dataclass(frozen=True)
class CandidateRecord:
    symbol: str
    timeframe: str
    trade_type: str | None
    stage: str                                # data|state|integrity|economics|dedupe|selection
    reasons: tuple
    rank: int | None
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "timeframe": self.timeframe, "trade_type": self.trade_type,
                "stage": self.stage, "reasons": list(self.reasons), "rank": self.rank,
                "metrics": dict(self.metrics)}


@dataclass(frozen=True)
class S3Decision:
    version: str
    outcome: str                              # SELECTED | NO_TRADE
    no_trade_reason: str | None
    selected: Candidate | None
    records: tuple                            # one per considered candidate, input order
    universe: dict
    reason_counts: dict
    policy: dict
    input_digest: str

    def to_dict(self) -> dict:
        """Machine-readable audit record (JSON-serialisable, deterministic key order)."""
        sel = self.selected
        return {"version": self.version, "outcome": self.outcome,
                "no_trade_reason": self.no_trade_reason,
                "selected": None if sel is None else {"symbol": sel.symbol, "timeframe": sel.timeframe,
                                                       "trade_type": sel.trade_type},
                "universe": dict(self.universe), "reason_counts": dict(self.reason_counts),
                "policy": dict(self.policy), "input_digest": self.input_digest,
                "candidates": [r.to_dict() for r in self.records]}


def _finite_pos(x) -> bool:
    try:
        return math.isfinite(float(x)) and float(x) > 0
    except (TypeError, ValueError):
        return False


def data_quality_reasons(c: Candidate, policy: S3Policy) -> tuple:
    """Mandatory gates; the full list is reported (not first-reason-only)."""
    if not c.trade_type:
        return ("no_trade_setup",)
    reasons = []
    if c.trade_type not in KNOWN_TRADE_TYPES:
        reasons.append("unknown_trade_type")
    d = c.data
    levels = [d.get(k) for k in ("entry_price", "stop_loss", "target_1", "target_2", "target_3")]
    if any(v is None for v in levels):
        reasons.append("bracket_missing")
    elif not all(_finite_pos(v) for v in levels):
        reasons.append("bracket_non_finite")
    else:
        e, s, t1, t2, t3 = (float(v) for v in levels)
        if not s < e < t1 < t2 < t3:                      # shared.execution.rebase_long_bracket
            reasons.append("bracket_not_ordered")
    if c.stop_valid is False:
        reasons.append(f"stop_rejected:{c.stop_reject_reason or 'invalid_signal_stop'}")
    elif c.stop_valid is not True:
        reasons.append("stop_not_validated")              # production accepts None (legacy rows)
    if not c.order_book_valid or c.spread_raw is None:
        reasons.append("order_book_unavailable")
    elif c.spread_pct is None:
        reasons.append("spread_invalid")                  # NaN/inf/negative (production passes NaN)
    elif c.spread_pct > policy.max_spread_pct:
        reasons.append("spread_exceeds_limit")
    if policy.require_liquidity and not (c.liquidity_usdt is not None and c.liquidity_usdt > 0):
        reasons.append("liquidity_unknown")
    return tuple(reasons)


def _setup_key(c: Candidate, policy: S3Policy) -> str | None:
    ident = c.data.get("setup_identity")
    if isinstance(ident, Mapping) and ident.get("key"):
        return str(ident["key"])
    if policy.strategy_version:
        try:
            return identity_from_candidate(c.data, strategy_version=policy.strategy_version,
                                           allow_pit_fallback=False).key
        except IdentityError:
            return None
    return None


def _economics(c: Candidate, policy: S3Policy) -> tuple[tuple, dict]:
    report = assess_candidate({**c.data, "order_book": {"spread_pct": c.spread_pct}},
                              policy.cost_model())
    m = report.metrics or {}
    metrics = {k: m.get(k) for k in ("cost_pct", "cost_over_risk", "net_t1_path_pct",
                                     "net_stop_pct", "net_t3_path_pct")}
    metrics["risk_pct"] = report.geometry.get("risk_pct")
    if not m:
        return (("cost_unavailable:" + ",".join(report.flags)),), metrics
    gate = CostCoveragePolicy(enabled=True, max_cost_over_risk=policy.max_cost_over_risk,
                              require_t1_path_net_positive=policy.require_t1_path_net_positive)
    return gate.evaluate(report).reasons, metrics


def rank_key(c: Candidate, metrics: Mapping) -> tuple:
    """cost/R asc, spread asc, liquidity desc, then a stable hash and a content digest."""
    ratio = metrics.get("cost_over_risk")
    ratio = float(ratio) if ratio is not None and math.isfinite(float(ratio)) else float("inf")
    spread = c.spread_pct if c.spread_pct is not None else float("inf")
    return (ratio, spread, -(c.liquidity_usdt or 0.0), _tie_hash(c), _digest(c.data))


def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def select_s3(candidates: Sequence[Candidate], *, policy: S3Policy = S3Policy(),
              open_symbols=frozenset(), cooldown=frozenset(), throttled=frozenset(),
              emitted_keys=frozenset(), decision_ms: int | None = None,
              universe_rows: Iterable[Mapping] | None = None) -> S3Decision:
    """Run stages 1-7 over normalised candidates. Pure; never raises on candidate data."""
    errors = policy.validate()
    if errors:
        raise ValueError("invalid_s3_policy:" + ",".join(errors))
    universe = {"total": len(candidates), "considered": len(candidates), "dropped": [], "capped": False}
    if universe_rows is not None:
        u = bounded_universe(universe_rows, max_rows=policy.max_universe_rows)
        universe = {"total": u.total, "considered": len(u.rows),
                    "dropped": [list(x) for x in u.dropped], "capped": u.capped}
    records: dict[int, CandidateRecord] = {}
    survivors = []
    for c in candidates:
        rec = lambda stage, reasons, metrics=None: CandidateRecord(
            c.symbol, c.timeframe, c.trade_type, stage, tuple(reasons), None, metrics or {})
        reasons = data_quality_reasons(c, policy)
        if reasons:
            records[id(c)] = rec("data", reasons)
            continue
        state = []
        if c.symbol in open_symbols:
            state.append("open_trade_exists")
        if c.symbol in cooldown:
            state.append("symbol_cooldown")
        if (c.trade_type, c.timeframe) in throttled:
            state.append("learned_gate_throttled")       # no exploration: no adaptive learning
        key = _setup_key(c, policy)
        if key is not None and key in emitted_keys:
            state.append("setup_already_emitted")
        if state:
            records[id(c)] = rec("state", state)
            continue
        if policy.enforce_integrity:
            if decision_ms is None:
                records[id(c)] = rec("integrity", ["integrity_inputs_missing"])
                continue
            verdict = integrity_check(c.data, decision_ms=decision_ms,     # = live enforce path
                                      strategy_version=policy.strategy_version,
                                      emitted_keys=frozenset(emitted_keys),
                                      allow_pit_fallback=False)
            if not verdict.eligible:
                records[id(c)] = rec("integrity", [f"integrity:{r}" for r in verdict.reasons])
                continue
        econ, metrics = _economics(c, policy)
        metrics.update({"spread_pct": c.spread_pct, "liquidity_usdt": c.liquidity_usdt})
        if econ:
            records[id(c)] = rec("economics", econ, metrics)
            continue
        survivors.append((c, metrics, key))
    ordered = sorted(survivors, key=lambda t: rank_key(t[0], t[1]))
    seen_symbols, seen_keys, kept = set(), set(), []
    for c, metrics, key in ordered:
        if c.symbol in seen_symbols:
            records[id(c)] = CandidateRecord(c.symbol, c.timeframe, c.trade_type, "dedupe",
                                             ("duplicate_symbol_lower_rank",), None, metrics)
            continue
        if key is not None and key in seen_keys:
            records[id(c)] = CandidateRecord(c.symbol, c.timeframe, c.trade_type, "dedupe",
                                             ("duplicate_setup_key",), None, metrics)
            continue
        seen_symbols.add(c.symbol)
        if key is not None:
            seen_keys.add(key)
        kept.append((c, metrics))
    for i, (c, metrics) in enumerate(kept):
        records[id(c)] = CandidateRecord(c.symbol, c.timeframe, c.trade_type, "selection",
                                         ("selected" if i == 0 else "not_selected_capacity",),
                                         i + 1, metrics)
    selected = kept[0][0] if kept else None
    out = tuple(records[id(c)] for c in candidates)
    counts: dict[str, int] = {}
    for r in out:
        for reason in r.reasons:
            counts[_code(reason)] = counts.get(_code(reason), 0) + 1
    no_trade = None if selected else ("empty_universe" if not candidates else "no_eligible_candidate")
    digest = _digest({"candidates": sorted(_digest({"data": c.data, "liquidity": c.liquidity_usdt})
                                           for c in candidates),                 # order-independent
                      "open": sorted(open_symbols), "cooldown": sorted(cooldown),
                      "throttled": sorted(map(list, throttled)), "emitted": sorted(emitted_keys),
                      "decision_ms": decision_ms})
    return S3Decision(VERSION, "SELECTED" if selected else "NO_TRADE", no_trade, selected, out,
                      universe, dict(sorted(counts.items())), asdict(policy), digest)


def select_s3_rows(rows: Iterable[Mapping], liquidity: Mapping[str, float | None], *,
                   policy: S3Policy = S3Policy(), **state) -> S3Decision:
    """Convenience: ``analysis_results`` rows (as the engine reads them) + a liquidity map.
    The universe is bounded without alphabetical truncation; dropped rows are reported."""
    rows = list(rows)
    u = bounded_universe(rows, max_rows=policy.max_universe_rows)
    cands = [normalize(r, liquidity.get(r.get("symbol") or (r.get("analysis_data") or {}).get("symbol")))
             for r in u.rows]
    return select_s3(cands, policy=policy, universe_rows=rows, **state)


# ── offline comparison harness (permitted inputs only; no outcomes, no protected windows) ──

@dataclass(frozen=True)
class ComparisonSummary:
    sets: int
    production_selected: int
    s3_selected: int
    same_pick: int
    s3_no_trade_where_production_traded: int
    production_pick_rejected_by_s3: dict      # reason code -> count
    s3_reason_counts: dict

    def to_dict(self) -> dict:
        return asdict(self)


def compare_with_production(candidate_sets: Iterable[tuple], *, policy: S3Policy = S3Policy(),
                            max_spread_pct: float = 0.15) -> ComparisonSummary:
    """For each ``(candidates, state)`` set: the production pick (exact replica of the live key,
    via candidate_selection's parity selector) beside the S3 decision. Reports how often S3
    would trade, decline, or choose differently, and why the production pick would be refused.
    Describes selector behaviour only; it says nothing about which choice would have profited."""
    from shared.candidate_selection import EligibilityPolicy, select
    n = prod_n = s3_n = same = declined = 0
    refused: dict[str, int] = {}
    s3_counts: dict[str, int] = {}
    for cands, state in candidate_sets:
        n += 1
        prod = select(cands, policy=EligibilityPolicy(max_spread_pct=max_spread_pct),
                      ranker="production_parity", **{k: v for k, v in state.items()
                                                     if k in ("open_symbols", "cooldown", "throttled")}).selected
        dec = select_s3(cands, policy=policy, **state)
        prod_n += prod is not None
        s3_n += dec.selected is not None
        if prod is not None and dec.selected is not None and prod is dec.selected:
            same += 1
        if prod is not None and dec.selected is None:
            declined += 1
        if prod is not None and prod is not dec.selected:
            rec = next(r for c, r in zip(cands, dec.records) if c is prod)
            for reason in rec.reasons:
                refused[_code(reason)] = refused.get(_code(reason), 0) + 1
        for k, v in dec.reason_counts.items():
            s3_counts[k] = s3_counts.get(k, 0) + v
    return ComparisonSummary(n, prod_n, s3_n, same, declined, dict(sorted(refused.items())),
                             dict(sorted(s3_counts.items())))


__all__ = ["VERSION", "ENABLED", "REASON_CODES", "NO_TRADE_REASONS", "S3Policy", "S3Decision",
           "CandidateRecord", "data_quality_reasons", "rank_key", "select_s3", "select_s3_rows",
           "compare_with_production", "ComparisonSummary", "production_parity_key"]
