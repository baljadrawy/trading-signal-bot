"""P2-X1 uncertainty-preserving result schema (``result_schema_v2.json``): gross AND net under every scenario.

A ``tsb.p2x.scenario_set_result`` keeps the three frozen scenarios side by side for one (hypothetical) long round
trip: the gross return (decision mid to decision mid, cost-free), and per scenario the net return, every cost
component of both legs with its own provenance, the latency drift (market movement, not a cost) and the coverage
(AVAILABLE or REFUSED + reason). It never collapses into one estimated price or one net figure.

``validate_evaluation_report`` encodes the economic success principle (no thresholds, no calculation here): a future
evaluation must report gross, the three nets, cost-to-gross per scenario, turnover sensitivity and execution
coverage / refusal; gross > 0 alone is never success.

Nothing here reads data; it only assembles leg estimates produced by ``model.estimate_leg``.
"""
from __future__ import annotations

from . import model as M
from .schema import DERIVED, UNAVAILABLE, SchemaError, check_quantity_tree, na, q, weakest, with_id

RECORD, RECORD_VERSION = "tsb.p2x.scenario_set_result", 1
SCENARIOS = ("EXEC-IDEALIZED", "EXEC-BASE", "EXEC-STRESS")
COMPONENTS = ("spread_cost_bps", "fee_bps", "slippage_bps", "interaction_bps", "total_cost_bps", "latency_drift_bps")
TOP_KEYS = {"record", "record_version", "kind", "result_id", "instrument", "direction", "order_notional",
            "entry_decision_time_ms", "exit_decision_time_ms", "p2c_row_ref", "gross_return", "scenarios",
            "component_provenance", "contract_set_sha256"}
FORBIDDEN_TOP = ("net_return", "estimated_price", "fill_price", "price", "cost_bps", "total_cost_bps")
REPORT_REQUIRED = ("gross", "net", "cost_to_gross_ratio", "turnover_sensitivity", "execution_coverage",
                   "component_provenance")


class ResultSchemaError(ValueError):
    pass


def _same(legs, key):
    vals = {repr(l[key]) for l in legs}
    if len(vals) != 1:
        raise ResultSchemaError(f"scenario legs differ in {key}")


def build(entry_legs: dict, exit_legs: dict, p2c_row_ref: dict | None = None) -> dict:
    if set(entry_legs) != set(SCENARIOS) or set(exit_legs) != set(SCENARIOS):
        raise ResultSchemaError(f"exactly the three scenarios are required: {SCENARIOS}")
    legs = list(entry_legs.values()) + list(exit_legs.values())
    for k in ("instrument", "direction", "order_notional", "contract_set_sha256"):
        _same(legs, k)
    _same(list(entry_legs.values()), "decision_time_ms")
    _same(list(exit_legs.values()), "decision_time_ms")
    ide_in, ide_out = entry_legs["EXEC-IDEALIZED"], exit_legs["EXEC-IDEALIZED"]
    if ide_in["latency_ms"]["value"] != 0 or ide_out["latency_ms"]["value"] != 0:
        raise ResultSchemaError("EXEC-IDEALIZED must have zero latency (gross = decision mid to decision mid)")
    if ide_in["decision_mid"]["value"] is None or ide_out["decision_mid"]["value"] is None:
        gross = na("decision_mid_unavailable")
    else:
        gross = q(ide_out["decision_mid"]["value"] / ide_in["decision_mid"]["value"] - 1, DERIVED)
    scen, prov = {}, {c: {} for c in COMPONENTS + ("net_return",)}
    for sc in SCENARIOS:
        e, x = entry_legs[sc], exit_legs[sc]
        if e["scenario"]["id"] != sc or x["scenario"]["id"] != sc:
            raise ResultSchemaError(f"leg scenario mismatch for {sc}")
        rt = M.round_trip(e, x)
        comps = {"entry": {c: e[c] for c in COMPONENTS}, "exit": {c: x[c] for c in COMPONENTS}}
        for c in COMPONENTS:
            prov[c][sc] = weakest(e[c]["provenance"], x[c]["provenance"])
        prov["net_return"][sc] = rt["net_return"]["provenance"]
        avail = rt["net_return"]["value"] is not None
        scen[sc] = {"scenario": e["scenario"], "entry_estimate_id": e["estimate_id"], "exit_estimate_id": x["estimate_id"],
                    "round_trip_id": rt["estimate_id"], "net_return": rt["net_return"],
                    "market_gross_return_at_execution_times": rt["gross_return"],
                    "components": comps, "cost_provenance": rt["cost_provenance"],
                    "data_quality_state": rt["data_quality_state"],
                    "coverage": {"state": "AVAILABLE" if avail else "REFUSED",
                                 "reason": None if avail else (rt["net_return"]["reason"] or "unavailable"),
                                 "entry_reason": e["total_cost_bps"]["reason"], "exit_reason": x["total_cost_bps"]["reason"]}}
    rec = {"record": RECORD, "record_version": RECORD_VERSION, "kind": "scenario_set_round_trip",
           "instrument": ide_in["instrument"], "direction": ide_in["direction"], "order_notional": ide_in["order_notional"],
           "entry_decision_time_ms": ide_in["decision_time_ms"], "exit_decision_time_ms": ide_out["decision_time_ms"],
           "p2c_row_ref": p2c_row_ref, "contract_set_sha256": ide_in["contract_set_sha256"],
           "gross_return": gross, "scenarios": scen, "component_provenance": prov}
    rec = with_id(rec, "result_id")
    validate_scenario_set(rec)
    return rec


def validate_scenario_set(rec: dict) -> None:
    """Refuse a record that collapses the scenarios, drops a scenario or hides provenance."""
    try:
        check_quantity_tree(rec)
    except SchemaError as e:
        raise ResultSchemaError(str(e)) from None
    extra = set(rec) - TOP_KEYS
    if extra:
        raise ResultSchemaError(f"unexpected top-level fields: {sorted(extra)}")
    for k in FORBIDDEN_TOP:
        if k in rec:
            raise ResultSchemaError(f"collapsed field not allowed: {k}")
    if set(rec.get("scenarios") or {}) != set(SCENARIOS):
        raise ResultSchemaError("all three scenarios must be present")
    g = rec["gross_return"]
    if not isinstance(g, dict) or set(g) != {"value", "provenance", "reason"}:
        raise ResultSchemaError("gross_return must be a Quantity")
    for sc, s in rec["scenarios"].items():
        nr = s["net_return"]
        if set(nr) != {"value", "provenance", "reason"}:
            raise ResultSchemaError(f"{sc}: net_return must be a Quantity")
        if (nr["value"] is None) != (s["coverage"]["state"] == "REFUSED"):
            raise ResultSchemaError(f"{sc}: coverage state inconsistent with net_return")
        if (nr["value"] is None) != (nr["provenance"] == UNAVAILABLE):
            raise ResultSchemaError(f"{sc}: a missing net is UNAVAILABLE with value null, never 0")
        for leg in ("entry", "exit"):
            for c in COMPONENTS:
                v = s["components"][leg][c]
                if set(v) != {"value", "provenance", "reason"}:
                    raise ResultSchemaError(f"{sc}.{leg}.{c}: not a Quantity with provenance")
    for c in COMPONENTS + ("net_return",):
        if set(rec["component_provenance"].get(c) or {}) != set(SCENARIOS):
            raise ResultSchemaError(f"component_provenance.{c} must cover every scenario")


def validate_evaluation_report(rep: dict) -> None:
    """Economic success principle (structure only; no thresholds, nothing computed here)."""
    miss = [k for k in REPORT_REQUIRED if k not in rep]
    if miss:
        raise ResultSchemaError(f"evaluation report missing: {miss}")
    for k in ("net", "cost_to_gross_ratio", "execution_coverage", "turnover_sensitivity"):
        if set(rep[k]) != set(SCENARIOS):
            raise ResultSchemaError(f"{k} must be reported for every scenario")
    for sc, cov in rep["execution_coverage"].items():
        for f in ("available", "refused", "refusal_rate", "refusal_reasons"):
            if f not in cov:
                raise ResultSchemaError(f"execution_coverage.{sc}.{f} missing")
    if rep.get("economic_success") is True:
        basis = rep.get("success_basis")
        if not isinstance(basis, (list, tuple)) or set(basis) in ({"gross"}, set()) or "gross" == basis:
            raise ResultSchemaError("gross > 0 alone is never success; success must rest on the net figures")
        if not {"net.EXEC-BASE", "net.EXEC-STRESS"} <= set(basis):
            raise ResultSchemaError("a success claim must cite the BASE and STRESS net figures and coverage")
