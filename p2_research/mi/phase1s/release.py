"""Frozen-input verification and the non-circular implementation identity.

Identity = code_tree_sha256: SHA-256 over the sorted lines "<file>\\t<sha256>\\n" of every *.py file in this package.
The git commit is an attestation recorded beside it (--impl-commit), never hashed into the tree, so a commit can pin
the tree hash in a later commit without circularity. Pilot / full runs refuse to start unless the running tree
equals --expect-tree-sha256.
"""
from __future__ import annotations

import hashlib
import os
import re

from .. import contract as MC

from . import EXPECTED_CONTRACT_SET_SHA256, EXPECTED_PROTOCOL_SHA256

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class FrozenError(Exception):
    pass


def tree_files() -> list:
    return sorted(f for f in os.listdir(PKG_DIR) if f.endswith(".py"))


def code_tree_sha256() -> str:
    h = hashlib.sha256()
    for f in tree_files():
        with open(os.path.join(PKG_DIR, f), "rb") as fh:
            h.update(f"{f}\t{hashlib.sha256(fh.read()).hexdigest()}\n".encode())
    return h.hexdigest()


def frozen_inputs():
    """Verify MI-C v1.0 and return (protocol, contract_set_sha256, protocol_sha256). Any mismatch -> FrozenError."""
    try:
        info = MC.verify()
    except MC.ContractError as e:
        raise FrozenError(f"FROZEN_SET_INVALID: {e}")
    cs = info["contract_set_sha256"]
    if cs != EXPECTED_CONTRACT_SET_SHA256:
        raise FrozenError(f"CONTRACT_SET_SHA256 {cs} != expected {EXPECTED_CONTRACT_SET_SHA256}")
    ps = MC.protocol_sha256()
    if ps != EXPECTED_PROTOCOL_SHA256:
        raise FrozenError(f"PROTOCOL_SHA256 {ps} != expected {EXPECTED_PROTOCOL_SHA256}")
    return MC.protocol(), cs, ps
