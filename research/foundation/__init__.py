"""Deterministic, offline-only research foundation for the live strategy contract."""

from .contract import current_contract, contract_hash, compare_contracts
from .dataset import DatasetSnapshot, create_snapshot, verify_snapshot
from .opportunity import RejectionCode, OpportunityRecord

__all__ = [
    "current_contract", "contract_hash", "compare_contracts",
    "DatasetSnapshot", "create_snapshot", "verify_snapshot",
    "RejectionCode", "OpportunityRecord",
]
