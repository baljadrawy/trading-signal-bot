"""Metric values, classification classes and quality states (RM0-QUALITY 1.0.0, RM0-METRICS classes).

A metric value is ``{"value", "class", "state", "reason", "flags"}``. Rules (enforced here and by ``check_tree``):
value null <=> class UNAVAILABLE <=> state in {UNAVAILABLE, INSUFFICIENT_HISTORY}; a null always has a reason;
an unknown quantity is never 0.
"""
from __future__ import annotations

import hashlib
import json

from ..execution.schema import rnd

MEASURED, DERIVED, ASSUMED, POLICY, UNAVAILABLE = "MEASURED", "DERIVED", "ASSUMED", "POLICY", "UNAVAILABLE"
CLASS_RANK = {MEASURED: 0, DERIVED: 1, ASSUMED: 2, POLICY: 3, UNAVAILABLE: 4}
VALID, ASSUMED_INPUT, DEGRADED_INPUT, GAP_AFFECTED, STALE_INPUT, INSUFFICIENT_HISTORY = (
    "VALID", "ASSUMED_INPUT", "DEGRADED_INPUT", "GAP_AFFECTED", "STALE_INPUT", "INSUFFICIENT_HISTORY")
ST_UNAVAILABLE = "UNAVAILABLE"
PRECEDENCE = (ST_UNAVAILABLE, INSUFFICIENT_HISTORY, STALE_INPUT, GAP_AFFECTED, DEGRADED_INPUT, ASSUMED_INPUT, VALID)
STATE_RANK = {s: len(PRECEDENCE) - i for i, s in enumerate(PRECEDENCE)}       # higher = worse
NULL_STATES = (ST_UNAVAILABLE, INSUFFICIENT_HISTORY)


class ValueRuleError(ValueError):
    pass


def worst(*states) -> str:
    st = [s for s in states if s]
    return max(st, key=lambda s: STATE_RANK[s]) if st else VALID


def weakest(*classes) -> str:
    cs = [c for c in classes if c]
    return max(cs, key=lambda c: CLASS_RANK[c]) if cs else UNAVAILABLE


def mv(value, cls: str, state: str = VALID, reason: str | None = None, flags=()) -> dict:
    """Build a metric value; validates the null / class / state rules."""
    if cls not in CLASS_RANK:
        raise ValueRuleError(f"unknown class {cls!r}")
    if state not in STATE_RANK:
        raise ValueRuleError(f"unknown state {state!r}")
    fl = sorted(set(f for f in flags if f and f != VALID) | ({state} if state != VALID else set()))
    if value is None:
        if cls != UNAVAILABLE or state not in NULL_STATES or not reason:
            raise ValueRuleError(f"null value needs class UNAVAILABLE, a null state and a reason ({cls}, {state}, {reason})")
        return {"value": None, "class": UNAVAILABLE, "state": state, "reason": reason, "flags": fl}
    if cls == UNAVAILABLE or state in NULL_STATES:
        raise ValueRuleError(f"value {value!r} with null class/state ({cls}, {state})")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        raise ValueRuleError(f"non-finite or non-numeric value {value!r}")
    return {"value": rnd(float(value)) if isinstance(value, float) else value, "class": cls, "state": state,
            "reason": reason, "flags": fl}


def na(reason: str, state: str = ST_UNAVAILABLE, flags=()) -> dict:
    return mv(None, UNAVAILABLE, state, reason, flags)


def is_null(m: dict) -> bool:
    return m is None or m.get("value") is None


def combine(parts: list, fn, cls_floor: str = DERIVED, extra_flags=(), reason_prefix="component") -> dict:
    """Apply ``fn`` to the values of ``parts`` (metric values) or return the worst null. Classes and states merge."""
    nulls = [p for p in parts if is_null(p)]
    flags = set(extra_flags)
    for p in parts:
        flags |= set(p.get("flags") or [])
    if nulls:
        st = worst(*(p["state"] for p in nulls))
        reasons = sorted(set(p["reason"] for p in nulls))
        return na(f"{reason_prefix}_{st.lower()}:" + ";".join(reasons)[:300], st, flags)
    v = fn([p["value"] for p in parts])
    st = worst(*(p["state"] for p in parts))
    return mv(v, weakest(cls_floor, *(p["class"] for p in parts)), st, None, flags)


def canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def is_metric(o) -> bool:
    return isinstance(o, dict) and set(o) == {"value", "class", "state", "reason", "flags"}


def check_tree(o, path="$") -> None:
    """Validate every metric-value-shaped dict in a record."""
    if is_metric(o):
        if o["value"] is None:
            if o["class"] != UNAVAILABLE or o["state"] not in NULL_STATES or not o["reason"]:
                raise ValueRuleError(f"{path}: malformed null metric")
        elif o["class"] == UNAVAILABLE or o["state"] in NULL_STATES:
            raise ValueRuleError(f"{path}: value with null class/state")
        if o["class"] not in CLASS_RANK or o["state"] not in STATE_RANK:
            raise ValueRuleError(f"{path}: unknown class/state")
        return
    if isinstance(o, dict):
        for k, v in o.items():
            check_tree(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            check_tree(v, f"{path}[{i}]")


def walk_metrics(o, path="$"):
    """Yield (path, metric) for every metric value in a record, in deterministic (sorted key) order."""
    if is_metric(o):
        yield path, o
        return
    if isinstance(o, dict):
        for k in sorted(o):
            yield from walk_metrics(o[k], f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk_metrics(v, f"{path}[{i}]")
