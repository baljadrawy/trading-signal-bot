"""Declared experimental (production-disconnected) modules under shared/.

Isolation tests use this one registry: production code must never import these, while they may
import each other. Wired A43/A44 modules (signal_identity, dependency_safety) are NOT listed."""
EXPERIMENTAL_SHARED = (
    "signal_quality",            # A42
    "counterfactual_barrier",    # A42
    "candidate_selection",       # A43/A44
    "candidate_diagnostics",     # A43
    "setup_diagnostics",         # A45
    "trade_geometry",            # A46
    "exchange_rules",            # A47
    "execution_calibration",     # A47 (A48: tracker_event_v1 + cost ledger)
    "replay_execution",          # A48
    "signal_selection",          # S3 (disabled; no production caller)
    "s3_shadow",                 # S3 shadow evaluation (disabled; no production caller)
    "s3_shadow_store",           # S3 shadow bounded JSONL store (disabled)
    "s3_shadow_sidecar",         # S3 shadow out-of-process read-only runner (disabled)
    "shadow_opportunity",        # shadow opportunity ledger (capacity-blocked; not wired)
)
