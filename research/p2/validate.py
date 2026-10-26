"""Fail-closed validators for the P2 canonical dataset (P2-A).

Each validator takes canonical rows (dicts of strings, as read from the CSV layer) and returns a list of
violation strings. An empty list means PASS. Missing required columns raise (fail closed). Validators never print
row values: violations carry identities and rule names only, so they cannot leak outcomes.
"""
from __future__ import annotations

from collections import Counter

from . import contract as C


def _require(rows, cols, entity):
    if rows and not set(cols) <= set(rows[0]):
        raise KeyError(f"{entity}: missing required columns {sorted(set(cols) - set(rows[0]))}")


def _int(v):
    return None if v in (None, "") else int(v)


def check_no_w3(tables: dict) -> list:
    """Every authoritative timestamp in every canonical entity is strictly before the freeze."""
    out = []
    for entity, cols in C.TIME_COLUMNS_MS.items():
        rows = tables.get(entity, [])
        _require(rows, cols, entity)
        for r in rows:
            for col in cols:
                v = _int(r.get(col))
                if v is not None and v >= C.FREEZE_MS:
                    out.append(f"W3_LEAK:{entity}.{col}:{r.get('decision_uid') or r.get('active_trade_id') or r.get('fill_id')}")
        if entity in ("decision", "execution_outcome", "trade_lifecycle"):
            for r in rows:
                if r.get("window") not in ("W1", "W2"):
                    out.append(f"W3_WINDOW:{entity}:{r.get('decision_uid')}")
    for r in tables.get("risk_context", []):
        if r["risk_date"] >= C.FREEZE_UTC[:10]:
            out.append(f"W3_LEAK:risk_context.risk_date:{r['risk_date']}")
    return out


def check_decision_identity(decisions: list) -> list:
    _require(decisions, ["decision_uid", "signal_id", "symbol", "timeframe", "decision_time_utc"], "decision")
    out = [f"DUPLICATE_DECISION_UID:{k}" for k, n in Counter(r["decision_uid"] for r in decisions).items() if n > 1]
    for r in decisions:
        if r["signal_id"] and C.decision_uid(int(r["signal_id"]), r["symbol"], r["timeframe"],
                                             r["decision_time_utc"]) != r["decision_uid"]:
            out.append(f"NONDETERMINISTIC_UID:{r['decision_uid']}")
    return out


def check_window_assignment(decisions: list) -> list:
    _require(decisions, ["decision_time_ms", "window"], "decision")
    return [f"WINDOW_MISMATCH:{r['decision_uid']}" for r in decisions
            if C.window_for_ms(int(r["decision_time_ms"])) != r["window"]]


def check_inferred_candle_closed(decisions: list) -> list:
    """Inferred decision candle must have closed strictly before the decision and be tf-aligned."""
    cols = ["timeframe", "decision_time_ms", "inferred_candle_open_ms", "inferred_candle_close_ms",
            "candle_ambiguous", "candle_provenance"]
    _require(decisions, cols, "decision")
    out = []
    for r in decisions:
        if not r["inferred_candle_open_ms"]:
            continue
        tf = C.TF_MS[r["timeframe"]]
        o, c, d = int(r["inferred_candle_open_ms"]), int(r["inferred_candle_close_ms"]), int(r["decision_time_ms"])
        if not (c < d):
            out.append(f"CANDLE_NOT_CLOSED_AT_DECISION:{r['decision_uid']}")
        if o % tf != 0 or c != o + tf - 1:
            out.append(f"CANDLE_MISALIGNED:{r['decision_uid']}")
        if r["candle_provenance"] != "INFERRED":
            out.append(f"INFERRED_CANDLE_NOT_LABELLED:{r['decision_uid']}")
        expect = C.infer_decision_candle(d, r["timeframe"])
        if (r["candle_ambiguous"] == "true") != expect["ambiguous"] or o != expect["open_ms"]:
            out.append(f"AMBIGUITY_FLAG_WRONG:{r['decision_uid']}")
    return out


def check_available_before_decision(context: list, decisions: list) -> list:
    """PIT rule: available_at <= decision_time for every feature value used as decision context."""
    _require(context, ["decision_uid", "available_at_ms", "pit_safe", "provenance"], "decision_market_context")
    dt = {r["decision_uid"]: int(r["decision_time_ms"]) for r in decisions}
    out = []
    for r in context:
        d = dt.get(r["decision_uid"])
        if d is None:
            out.append(f"CONTEXT_ORPHAN:{r['decision_uid']}")
            continue
        if not r["available_at_ms"]:
            if r["pit_safe"] == "true":
                out.append(f"PIT_SAFE_WITHOUT_AVAILABLE_AT:{r['decision_uid']}:{r['feature_name']}")
            continue
        if int(r["available_at_ms"]) > d:
            out.append(f"FEATURE_AVAILABLE_AFTER_DECISION:{r['decision_uid']}:{r['feature_name']}")
        if r["observed_at_ms"] and int(r["observed_at_ms"]) > d:
            out.append(f"FEATURE_OBSERVED_AFTER_DECISION:{r['decision_uid']}:{r['feature_name']}")
    return out


def check_no_outcome_in_features(context: list) -> list:
    """Future market/trade outcomes must never appear in the feature layer."""
    _require(context, ["feature_name", "namespace"], "decision_market_context")
    return sorted({f"OUTCOME_NAME_IN_FEATURES:{r['namespace']}.{r['feature_name']}" for r in context
                   if C.OUTCOME_NAME_RE.search(r["feature_name"]) or C.OUTCOME_NAME_RE.search(r["namespace"])})


def check_no_daily_macro_last_of_day(context: list) -> list:
    """macro_history is one row per UTC day with last-write-wins: never PIT-safe for intraday decisions."""
    _require(context, ["source", "pit_safe"], "decision_market_context")
    return [f"DAILY_MACRO_LAST_OF_DAY_IN_CONTEXT:{r['decision_uid']}:{r['feature_name']}" for r in context
            if r["source"] == "macro_history" and r["pit_safe"] == "true"]


def check_layer_separation(tables: dict) -> list:
    """market_outcome and execution_outcome stay separate; execution never serves as a market label."""
    out = []
    mo = set(C.SCHEMAS["market_outcome"]); eo = set(C.SCHEMAS["execution_outcome"])
    shared = (mo & eo) - {"decision_uid"}
    if shared:
        out.append(f"SHARED_COLUMNS_MARKET_EXECUTION:{sorted(shared)}")
    for r in tables.get("market_outcome", []):
        if r.get("provenance") in ("OBSERVED", "PAPER_MODEL") or r.get("label_name", "").startswith(("fill", "exec")):
            out.append(f"EXECUTION_USED_AS_MARKET_LABEL:{r.get('decision_uid')}")
    for e in ("execution_outcome", "trade_lifecycle", "trade_target_fill"):
        for r in tables.get(e, []):
            if r.get("execution_provenance") != "PAPER_MODEL":
                out.append(f"EXECUTION_PROVENANCE_NOT_PAPER_MODEL:{e}:{r.get('decision_uid')}")
    return out


def check_provenance_vocabulary(tables: dict) -> list:
    out = []
    allowed = set(C.PROVENANCE)
    for entity, col in (("decision", "decision_time_provenance"), ("decision", "geometry_provenance"),
                        ("decision", "candle_provenance"), ("decision_market_context", "provenance"),
                        ("risk_context", "provenance")):
        for r in tables.get(entity, []):
            if r[col] not in allowed:
                out.append(f"BAD_PROVENANCE:{entity}.{col}={r[col]}")
    return sorted(set(out))


def run_all(tables: dict) -> dict:
    d, ctx = tables.get("decision", []), tables.get("decision_market_context", [])
    return {
        "w3_leakage": check_no_w3(tables),
        "decision_identity": check_decision_identity(d),
        "window_assignment": check_window_assignment(d),
        "inferred_candle_closed_and_ambiguity": check_inferred_candle_closed(d),
        "feature_available_after_decision": check_available_before_decision(ctx, d),
        "future_outcome_in_feature_layer": check_no_outcome_in_features(ctx),
        "daily_macro_last_of_day": check_no_daily_macro_last_of_day(ctx),
        "market_execution_separation": check_layer_separation(tables),
        "provenance_vocabulary": check_provenance_vocabulary(tables),
    }
