"""Frozen P2-RM0 contract set: load and verify against contracts_rm0/FROZEN_SHA256SUMS.json.

The P2-D0 specs (p2_research/research/*_v1.json) and the P2-X v1 / v2 contract sets are never modified; RM0 is a NEW,
separately frozen set. Code reads every parameter (lookbacks, minimum observations, research thresholds, fixture
definitions) from these files so the frozen JSON is the single source of truth.
"""
from __future__ import annotations

import hashlib
import json
import os

CONTRACT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contracts_rm0")
SUMS_FILE = "FROZEN_SHA256SUMS.json"
FILES = ("metrics_v1.json", "policy_v1.json", "position_contract_v1.json", "quality_states_v1.json",
         "portfolios_v1.json", "snapshot_schema_v1.json", "validation_plan_v1.json")
SUMS_RECORD, SUMS_RECORD_VERSION = "tsb.p2rm.frozen_sha256", 1


class RiskContractError(ValueError):
    pass


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class RiskContracts:
    def __init__(self, directory: str = CONTRACT_DIR, verify: bool = True):
        self.directory = directory
        sp = os.path.join(directory, SUMS_FILE)
        with open(sp, encoding="utf-8") as fh:
            sums = json.load(fh)
        if sums.get("record") != SUMS_RECORD or sums.get("record_version") != SUMS_RECORD_VERSION:
            raise RiskContractError("FROZEN_SUMS_RECORD_UNSUPPORTED")
        if sorted(sums.get("files") or {}) != sorted(FILES):
            raise RiskContractError("FROZEN_SUMS_FILE_SET_MISMATCH")
        self.sums = dict(sums["files"])
        self.sha256 = _sha(sp)
        self.docs = {}
        for f in FILES:
            p = os.path.join(directory, f)
            if verify and _sha(p) != self.sums[f]:
                raise RiskContractError(f"CONTRACT_HASH_MISMATCH: {f}")
            with open(p, encoding="utf-8") as fh:
                self.docs[f] = json.load(fh)
        self.metrics = self.docs["metrics_v1.json"]
        self.policy = self.docs["policy_v1.json"]
        self.position = self.docs["position_contract_v1.json"]
        self.quality = self.docs["quality_states_v1.json"]
        self.portfolios = {p["id"]: p for p in self.docs["portfolios_v1.json"]["portfolios"]}
        self.schema = self.docs["snapshot_schema_v1.json"]
        self.plan = self.docs["validation_plan_v1.json"]
        self.thresholds = {t["id"]: t for t in self.policy["research_flag_thresholds"]}
        self.refs = {k: v["value"] for k, v in self.policy["research_references"].items()}

    # ---------------- parameters (read from the frozen JSON, never hard-coded) ----------------
    @property
    def vol(self) -> dict:
        return self.metrics["volatility"]

    @property
    def corr(self) -> dict:
        return self.metrics["correlation"]

    @property
    def bar_ms(self) -> int:
        return int(self.metrics["returns"]["bar_ms"])

    @property
    def capital(self) -> dict:
        return self.policy["hypothetical_capital"]

    @property
    def btc_reference(self) -> str:
        return self.metrics["btc"]["reference_instrument"]

    def versions(self) -> dict:
        out = {}
        for f, d in self.docs.items():
            out[d["id"]] = d["version"]
        for k in ("returns", "exposure", "heat", "concentration", "volatility", "correlation", "btc", "covariance",
                  "liquidity", "regime_primitives", "drawdown", "diversification", "risk_contribution"):
            m = self.metrics[k]
            out[m["id"]] = m["version"]
        return dict(sorted(out.items()))


_DEFAULT = None


def default() -> RiskContracts:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = RiskContracts()
    return _DEFAULT

UNITS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contracts_rm0_v1_1")
_UNITS_SHA = None


def units_amendment_sha256() -> str:
    """RM0-UNITS 1.1.0 (D-RM0-2): verify the frozen amendment and return the hash of its FROZEN_SHA256SUMS file."""
    global _UNITS_SHA
    if _UNITS_SHA is None:
        sp = os.path.join(UNITS_DIR, SUMS_FILE)
        with open(sp, encoding="utf-8") as fh:
            sums = json.load(fh)
        if sums.get("record") != SUMS_RECORD or sorted(sums.get("files") or {}) != ["units_v1.json"]:
            raise RiskContractError("UNITS_AMENDMENT_SUMS_INVALID")
        if _sha(os.path.join(UNITS_DIR, "units_v1.json")) != sums["files"]["units_v1.json"]:
            raise RiskContractError("CONTRACT_HASH_MISMATCH: units_v1.json")
        _UNITS_SHA = _sha(sp)
    return _UNITS_SHA
