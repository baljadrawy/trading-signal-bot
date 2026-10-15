"""A43 compact, versioned per-candidate diagnostic record — local serialization only.

Not connected to the production evidence stream (shadow recording is not
approved). Fields are an explicit whitelist: nothing from config, env or the
order book beyond the spread is copied, so no secret can leak through.
One record ≈ 1 KB of canonical JSON.
"""
from __future__ import annotations

import json
import math
from typing import Mapping

from shared.candidate_selection import Candidate, SelectionResult
from shared.signal_identity import IdentityError, SetupIdentity, freshness, identity_from_candidate
from shared.signal_quality import CostModel, assess_candidate

SCHEMA = "tsb.a43.candidate_diag"
SCHEMA_VERSION = 1

FIELDS = (
    "schema", "schema_version", "setup_key", "identity_error", "strategy_version", "symbol",
    "timeframe", "candle_open_ms", "trade_type", "eligible", "reasons", "spread_pct",
    "liquidity_usdt", "bracket", "risk_pct", "t1_pct", "cost_pct", "cost_over_risk",
    "net_paths_pct", "risk_atr", "atr_pct", "quality_flags", "duplicate", "age_bars", "fresh",
    "rank", "ranker", "selected", "selection_reason", "exposure",
)


def _r(x, nd=6):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def build_record(c: Candidate, *, strategy_version: str, decision_ms: int,
                 selection: SelectionResult | None = None, reasons: tuple = (),
                 emitted_keys=frozenset(), exposure: Mapping | None = None,
                 cost: CostModel = CostModel()) -> dict:
    d = c.data
    ident: SetupIdentity | None = None
    ident_err = None
    try:
        ident = identity_from_candidate(d, strategy_version=strategy_version)
    except IdentityError as exc:
        ident_err = str(exc)
    fresh = freshness(ident, decision_ms) if ident else None
    report = assess_candidate({**d, "order_book": {"spread_pct": c.spread_pct}}, cost)
    m, g = report.metrics, report.geometry
    rank = selected = None
    sel_reason = ranker = None
    if selection is not None:
        ranker, sel_reason = selection.ranker, selection.selection_reason
        for cand, pos, _ in selection.ranked:
            if cand is c:
                rank = pos
        selected = selection.selected is c
    rec = {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION,
        "setup_key": ident.key if ident else None, "identity_error": ident_err,
        "strategy_version": strategy_version, "symbol": c.symbol, "timeframe": c.timeframe,
        "candle_open_ms": ident.candle_open_ms if ident else None, "trade_type": c.trade_type,
        "eligible": not reasons, "reasons": list(reasons),
        "spread_pct": _r(c.spread_pct), "liquidity_usdt": _r(c.liquidity_usdt, 2),
        "bracket": [_r(d.get(k), 8) for k in ("entry_price", "stop_loss", "target_1", "target_2", "target_3")],
        "risk_pct": _r(g.get("risk_pct")), "t1_pct": _r(g.get("t1_pct")),
        "cost_pct": _r(m.get("cost_pct")), "cost_over_risk": _r(m.get("cost_over_risk")),
        "net_paths_pct": ({k: _r(v) for k, v in sorted(report.payoffs["net"].items())}
                          if report.payoffs else None),
        "risk_atr": _r(g.get("risk_atr")), "atr_pct": _r(g.get("atr_pct")),
        "quality_flags": sorted(report.flags),
        "duplicate": (ident.key in emitted_keys) if ident else None,
        "age_bars": _r(fresh.age_bars, 4) if fresh else None,
        "fresh": fresh.admissible if fresh else None,
        "rank": rank, "ranker": ranker, "selected": selected, "selection_reason": sel_reason,
        "exposure": dict(sorted(exposure.items())) if exposure else None,
    }
    validate_record(rec)
    return rec


def serialize(rec: Mapping) -> str:
    """Canonical one-line JSON (sorted keys, compact, ASCII); NaN is impossible by construction."""
    validate_record(rec)
    return json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def deserialize(line: str) -> dict:
    rec = json.loads(line)
    validate_record(rec)
    return rec


def validate_record(rec: Mapping) -> None:
    keys = set(rec)
    if keys != set(FIELDS):
        raise ValueError(f"diag_fields_mismatch:missing={sorted(set(FIELDS) - keys)},"
                         f"extra={sorted(keys - set(FIELDS))}")
    if rec["schema"] != SCHEMA or rec["schema_version"] != SCHEMA_VERSION:
        raise ValueError("diag_schema_unknown")
    if not isinstance(rec["reasons"], list) or rec["eligible"] != (not rec["reasons"]):
        raise ValueError("diag_eligibility_inconsistent")
