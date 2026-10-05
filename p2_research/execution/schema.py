"""Canonical execution schema primitives: provenance classes, Quantity encoding, canonical hashing.

A Quantity is ``{"value": number|None, "provenance": <class>, "reason": str|None}``. UNAVAILABLE always carries
``value=None`` and a reason; a missing value is never encoded as 0 (contracts/result_schema_v1.json).
"""
from __future__ import annotations

import hashlib
import json

MEASURED, DERIVED, ESTIMATED, ASSUMED, UNAVAILABLE = "MEASURED", "DERIVED", "ESTIMATED", "ASSUMED", "UNAVAILABLE"
PROVENANCE_RANK = {MEASURED: 0, DERIVED: 1, ESTIMATED: 2, ASSUMED: 3, UNAVAILABLE: 4}
VALID, DEGRADED, INVALID = "VALID", "DEGRADED", "INVALID"
STATE_RANK = {VALID: 0, DEGRADED: 1, INVALID: 2}


class SchemaError(ValueError):
    pass


def rnd(v):
    """12 significant digits (same convention as P2-C) so canonical output is stable across platforms."""
    return None if v is None else float(f"{v:.12g}")


def q(value, provenance: str, reason: str | None = None) -> dict:
    if provenance not in PROVENANCE_RANK:
        raise SchemaError(f"unknown provenance {provenance!r}")
    if provenance == UNAVAILABLE:
        if value is not None:
            raise SchemaError("UNAVAILABLE must have value None")
        if not reason:
            raise SchemaError("UNAVAILABLE needs a reason")
        return {"value": None, "provenance": UNAVAILABLE, "reason": reason}
    if value is None:
        raise SchemaError(f"{provenance} quantity without a value (use UNAVAILABLE + reason)")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        raise SchemaError(f"non-finite or non-numeric value {value!r}")
    return {"value": rnd(float(value)) if isinstance(value, float) else value, "provenance": provenance, "reason": reason}


def na(reason: str) -> dict:
    return q(None, UNAVAILABLE, reason)


def weakest(*provs: str) -> str:
    return max(provs, key=lambda p: PROVENANCE_RANK[p]) if provs else UNAVAILABLE


def worst_state(*states: str) -> str:
    return max(states, key=lambda s: STATE_RANK[s]) if states else INVALID


def canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def with_id(rec: dict, key: str = "estimate_id") -> dict:
    """Attach a content identity: sha256 of the canonical record without the id field."""
    body = {k: v for k, v in rec.items() if k != key}
    return {**body, key: sha256_text(canon(body))}


def check_quantity_tree(o, path="$") -> None:
    """Validate every Quantity-shaped dict in a record (used by tests and the coverage writer)."""
    if isinstance(o, dict):
        if set(o) == {"value", "provenance", "reason"}:
            if o["provenance"] == UNAVAILABLE and (o["value"] is not None or not o["reason"]):
                raise SchemaError(f"{path}: malformed UNAVAILABLE")
            if o["provenance"] != UNAVAILABLE and o["value"] is None:
                raise SchemaError(f"{path}: {o['provenance']} without value")
            return
        for k, v in o.items():
            check_quantity_tree(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            check_quantity_tree(v, f"{path}[{i}]")
