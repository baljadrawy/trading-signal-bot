"""MI Phase 1S: synthetic statistical calibration of the frozen MI-C v1.0 rules (implementation only).

Synthetic-only. Reads nothing but the frozen contract set (p2_research/mi/contracts_v1_0). Never imports the MI CPU
guard, the CPU budget ledger, the MI trial ledger, the reader / stream / execution code or any database client.
See docs/mi/MI_PHASE1S_IMPL.md for the protocol coverage matrix, the implementation choices awaiting owner review
(OD-1..OD-7) and the pilot plan. Nothing in this package reserves, spends or verifies CPU budget.
"""

EXPECTED_CONTRACT_SET_SHA256 = "fdf3366480976db6ada1ac90b62f6b6db1edc35a59d1f3527cfcd6fcbf28e157"
EXPECTED_PROTOCOL_SHA256 = "412cb6062ea5b4f4c9b8bd9fa34cf0d449b4f8abcab4c173858791a9f9464202"
IMPL_VERSION = "mi-phase1s-impl-1.0.0"
