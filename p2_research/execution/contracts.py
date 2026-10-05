"""Frozen P2-X0 contracts: load, verify against FROZEN_SHA256SUMS.json, and look up models by id.

The JSON files in ``contracts/`` are the source of truth. Loading refuses any file whose SHA-256 differs from the
recorded sum (old research is never silently rewritten: a change needs a new version and a new recorded hash).
"""
from __future__ import annotations

import hashlib
import json
import os

CONTRACT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contracts")
SUMS_FILE = "FROZEN_SHA256SUMS.json"
FILES = ("terminology_v1.json", "fee_schedule_v1.json", "models_v1.json", "scenarios_v1.json", "result_schema_v1.json")


class ContractError(ValueError):
    pass


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class ContractSet:
    def __init__(self, directory: str = CONTRACT_DIR, verify: bool = True):
        self.directory = directory
        sp = os.path.join(directory, SUMS_FILE)
        with open(sp, encoding="utf-8") as fh:
            sums = json.load(fh)
        if sums.get("record") != "tsb.p2x.frozen_sha256" or sums.get("record_version") != 1:
            raise ContractError("FROZEN_SUMS_RECORD_UNSUPPORTED")
        self.sums = sums["files"]
        self.sha256 = _sha(sp)
        self.docs = {}
        for f in FILES:
            p = os.path.join(directory, f)
            if verify and _sha(p) != self.sums.get(f):
                raise ContractError(f"CONTRACT_HASH_MISMATCH: {f}")
            with open(p, encoding="utf-8") as fh:
                self.docs[f] = json.load(fh)
        m = self.docs["models_v1.json"]
        self.models = {}
        for group in ("execution_models", "latency_models", "slippage_models", "stale_policies", "data_quality_policies"):
            for e in m[group]:
                if e["id"] in self.models:
                    raise ContractError(f"DUPLICATE_MODEL_ID: {e['id']}")
                self.models[e["id"]] = dict(e, group=group)
        fs = self.docs["fee_schedule_v1.json"]
        self.fee_schedules = {fs["id"]: fs}
        self.scenarios = {s["id"]: s for s in self.docs["scenarios_v1.json"]["scenarios"]}

    # ---------------- lookups ----------------
    def model(self, mid: str, group: str | None = None) -> dict:
        e = self.models.get(mid)
        if e is None or (group is not None and e["group"] != group):
            raise ContractError(f"UNKNOWN_MODEL: {mid} ({group})")
        return e

    def ref(self, mid: str) -> dict:
        e = self.models[mid] if mid in self.models else self.fee_schedules[mid]
        return {"id": e["id"], "version": e["version"]}

    def scenario(self, sid: str) -> dict:
        if sid not in self.scenarios:
            raise ContractError(f"UNKNOWN_SCENARIO: {sid}")
        return self.scenarios[sid]

    def add_fee_schedule(self, doc: dict) -> None:
        """Register an additional fee-schedule VERSION (tests / future versions). Same id+version must not differ."""
        key = doc["id"]
        cur = self.fee_schedules.get(key)
        if cur is not None and cur["version"] == doc["version"] and cur != doc:
            raise ContractError(f"FEE_SCHEDULE_VERSION_CONFLICT: {key} {doc['version']}")
        self.fee_schedules[f"{key}@{doc['version']}"] = doc

    def fee_schedule(self, sid: str) -> dict:
        if sid not in self.fee_schedules:
            raise ContractError(f"UNKNOWN_FEE_SCHEDULE: {sid}")
        return self.fee_schedules[sid]


def fee_rate_bps(schedule: dict, venue: str, market_type: str, role: str) -> tuple:
    """(rate_bps, provenance, entry) for one venue/market/role; refuses an ambiguous or missing entry."""
    hits = [e for e in schedule["entries"]
            if e["venue"] == venue and e["market_type"] == market_type and e["liquidity_role"] == role]
    if len(hits) != 1:
        raise ContractError(f"FEE_ENTRY_NOT_UNIQUE: {venue}/{market_type}/{role}: {len(hits)}")
    e = hits[0]
    return float(e["rate_bps"]), e.get("provenance", schedule.get("assumption_status", "ASSUMED")), e


_DEFAULT = None


def default() -> ContractSet:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ContractSet()
    return _DEFAULT
