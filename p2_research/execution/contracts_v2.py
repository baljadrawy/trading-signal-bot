"""Frozen P2-X1 contract set (version 2): load, verify against contracts_v2/FROZEN_SHA256SUMS.json, look up models.

The v1 set (``contracts/``, X0) is untouched and stays byte-identical; v2 is a NEW, separately frozen set. Estimates
made with v2 carry the v2 ``contract_set_sha256`` and v2 model / scenario versions, so a v1 estimate is never
rewritten. ``ContractSetV2`` exposes the same interface as ``contracts.ContractSet`` (model, ref, scenario,
fee_schedule, add_fee_schedule, sha256), so ``model.estimate_leg(..., contracts=ContractSetV2())`` works unchanged.

Fee contract (``fee_schedule_v2.json``): every entry states venue, market type, liquidity role, rate, account scope
(GENERIC_PUBLIC_STANDARD_TIER vs ACCOUNT_SPECIFIC), verification status, provenance, effective/version dates and
discounts. ``validate_fee_schedule`` refuses an unevidenced discount, an ACCOUNT_SPECIFIC or MEASURED entry without
evidence, and a generic entry presented as anything but ASSUMED. A verified account fee is substituted by adding a
NEW schedule version (``add_fee_schedule``); history is never rewritten.
"""
from __future__ import annotations

import hashlib
import json
import os

from .contracts import ContractError
from .schema import PROVENANCE_RANK

CONTRACT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contracts_v2")
SUMS_FILE = "FROZEN_SHA256SUMS.json"
FILES = ("calibration_plan_v2.json", "terminology_v2.json", "fee_schedule_v2.json", "models_v2.json",
         "scenarios_v2.json", "result_schema_v2.json", "p2c_join_v2.json", "reconciliation_design_v2.json")
SUMS_RECORD, SUMS_RECORD_VERSION = "tsb.p2x.frozen_sha256", 2
ACCOUNT_SCOPES = ("GENERIC_PUBLIC_STANDARD_TIER", "ACCOUNT_SPECIFIC")
VERIFICATION = ("UNVERIFIED_ASSUMPTION", "VERIFIED_PUBLIC_SCHEDULE_SNAPSHOT", "VERIFIED_ACCOUNT_RECORD",
                "VERIFIED_REALIZED_COMMISSIONS")
FEE_KEYS = ("venue", "market_type", "liquidity_role", "rate_bps", "account_scope", "verification_status",
            "provenance", "effective_from", "effective_basis", "discounts", "evidence")


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def validate_fee_schedule(doc: dict) -> None:
    """Refuse a fee schedule that overstates its evidence (fail closed)."""
    for k in ("contract", "id", "version", "entries", "version_date"):
        if k not in doc:
            raise ContractError(f"FEE_SCHEDULE_FIELD_MISSING: {k}")
    if not doc["entries"]:
        raise ContractError("FEE_SCHEDULE_EMPTY")
    seen = set()
    for e in doc["entries"]:
        miss = [k for k in FEE_KEYS if k not in e]
        if miss:
            raise ContractError(f"FEE_ENTRY_FIELDS_MISSING: {miss}")
        key = (e["venue"], e["market_type"], e["liquidity_role"])
        if key in seen:
            raise ContractError(f"FEE_ENTRY_DUPLICATE: {key}")
        seen.add(key)
        r = e["rate_bps"]
        if isinstance(r, bool) or not isinstance(r, (int, float)) or r != r or r < 0:
            raise ContractError(f"FEE_RATE_INVALID: {r!r}")
        if e["account_scope"] not in ACCOUNT_SCOPES:
            raise ContractError(f"FEE_ACCOUNT_SCOPE_UNKNOWN: {e['account_scope']}")
        if e["verification_status"] not in VERIFICATION:
            raise ContractError(f"FEE_VERIFICATION_UNKNOWN: {e['verification_status']}")
        if e["provenance"] not in PROVENANCE_RANK or e["provenance"] == "UNAVAILABLE":
            raise ContractError(f"FEE_PROVENANCE_INVALID: {e['provenance']}")
        verified = e["verification_status"] != "UNVERIFIED_ASSUMPTION"
        if verified and not e["evidence"]:
            raise ContractError("FEE_VERIFIED_WITHOUT_EVIDENCE")
        if e["account_scope"] == "ACCOUNT_SPECIFIC" and e["verification_status"] not in (
                "VERIFIED_ACCOUNT_RECORD", "VERIFIED_REALIZED_COMMISSIONS"):
            raise ContractError("FEE_ACCOUNT_SPECIFIC_UNVERIFIED")
        if e["provenance"] == "MEASURED" and e["verification_status"] != "VERIFIED_REALIZED_COMMISSIONS":
            raise ContractError("FEE_MEASURED_WITHOUT_REALIZED_COMMISSIONS")
        if not verified and e["provenance"] != "ASSUMED":
            raise ContractError("FEE_UNVERIFIED_MUST_BE_ASSUMED")
        for d in e["discounts"]:
            if not isinstance(d, dict) or not d.get("evidence") or not verified:
                raise ContractError("FEE_DISCOUNT_WITHOUT_EVIDENCE")


class ContractSetV2:
    def __init__(self, directory: str = CONTRACT_DIR, verify: bool = True):
        self.directory = directory
        sp = os.path.join(directory, SUMS_FILE)
        with open(sp, encoding="utf-8") as fh:
            sums = json.load(fh)
        if sums.get("record") != SUMS_RECORD or sums.get("record_version") != SUMS_RECORD_VERSION:
            raise ContractError("FROZEN_SUMS_RECORD_UNSUPPORTED")
        if sorted(sums.get("files") or {}) != sorted(FILES):
            raise ContractError("FROZEN_SUMS_FILE_SET_MISMATCH")
        self.sums = sums["files"]
        self.sha256 = _sha(sp)
        self.docs = {}
        for f in FILES:
            p = os.path.join(directory, f)
            if verify and _sha(p) != self.sums.get(f):
                raise ContractError(f"CONTRACT_HASH_MISMATCH: {f}")
            with open(p, encoding="utf-8") as fh:
                self.docs[f] = json.load(fh)
        m = self.docs["models_v2.json"]
        self.models = {}
        for group in ("execution_models", "latency_models", "slippage_models", "stale_policies", "data_quality_policies"):
            for e in m[group]:
                if e["id"] in self.models:
                    raise ContractError(f"DUPLICATE_MODEL_ID: {e['id']}")
                self.models[e["id"]] = dict(e, group=group)
        fs = self.docs["fee_schedule_v2.json"]
        validate_fee_schedule(fs)
        self.fee_schedules = {fs["id"]: fs}
        self.scenarios = {s["id"]: s for s in self.docs["scenarios_v2.json"]["scenarios"]}
        self.knowledge_time = self.docs["result_schema_v2.json"]["leg_field_knowledge_time"]

    # ---------------- lookups (same interface as contracts.ContractSet) ----------------
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
        """Register a NEW fee-schedule version (e.g. a later verified account-specific fee). Validated; the same
        id+version must not differ; the registered key is ``<id>@<version>``; nothing existing is replaced."""
        validate_fee_schedule(doc)
        for cur in self.fee_schedules.values():
            if cur["id"] == doc["id"] and cur["version"] == doc["version"] and cur != doc:
                raise ContractError(f"FEE_SCHEDULE_VERSION_CONFLICT: {doc['id']} {doc['version']}")
        self.fee_schedules.setdefault(f"{doc['id']}@{doc['version']}", doc)

    def fee_schedule(self, sid: str) -> dict:
        if sid not in self.fee_schedules:
            raise ContractError(f"UNKNOWN_FEE_SCHEDULE: {sid}")
        return self.fee_schedules[sid]


_DEFAULT = None


def default() -> ContractSetV2:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ContractSetV2()
    return _DEFAULT
