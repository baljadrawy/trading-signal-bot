"""MI-ML contract MI-C v1.0: load and verify the frozen set (contracts_v1_0/FROZEN_SHA256SUMS.json).

contract_set_sha256 = SHA-256 of the sums file. The sums cover the three JSON documents AND the code that implements
them (timeline, folds, derive, this loader), so a code change is a contract change. Nothing here writes anything.
"""
from __future__ import annotations

import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SET_DIR = os.path.join(HERE, "contracts_v1_0")
SUMS = os.path.join(SET_DIR, "FROZEN_SHA256SUMS.json")
FILES = ("contracts_v1_0/mi_contract_v1_0.json", "contracts_v1_0/mi_phase1s_protocol_v1_0.json",
         "contracts_v1_0/mi_derivation_map_v1_0.json", "timeline.py", "folds.py", "derive.py", "contract.py")


class ContractError(Exception):
    pass


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def sums() -> dict:
    with open(SUMS, encoding="utf-8") as fh:
        return json.load(fh)


def contract_set_sha256() -> str:
    return _sha(SUMS)


def verify() -> dict:
    s = sums()
    if s.get("record") != "tsb.mi.frozen_sums" or s.get("contract_version") != "1.0.0":
        raise ContractError("not an MI-C v1.0 sums file")
    if sorted(s["files"]) != sorted(FILES):
        raise ContractError(f"sums cover {sorted(s['files'])}, expected {sorted(FILES)}")
    bad = [f for f in FILES if _sha(os.path.join(HERE, f)) != s["files"][f]]
    if bad:
        raise ContractError(f"frozen file changed: {bad}")
    return {"contract_set_sha256": contract_set_sha256(), "files": s["files"]}


def load(name: str) -> dict:
    verify()
    with open(os.path.join(SET_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def protocol() -> dict:
    return load("mi_phase1s_protocol_v1_0.json")


def protocol_sha256() -> str:
    return _sha(os.path.join(SET_DIR, "mi_phase1s_protocol_v1_0.json"))
