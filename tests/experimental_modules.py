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
    "strategy_identity",         # WP2 lane A (R5): closure-hash identity, dormant
    "strategy_config_snapshot",  # WP2 lane A (R5): versioned decision-config snapshot, dormant
    "decision_metadata",         # WP2 lane A (R5): replay-stable decision records, dormant
    "strategy_version_boundary", # WP2 lane A (R5.e): pure version-boundary report, dormant
    "signal_integrity_v2",       # WP2 lane C (R3): candle/setup identity + freshness, dormant
    "funnel_records",            # WP2 lane B (R1/R6): RejectionRecord + conservation, dormant
    "funnel_recorder",           # WP2 lane B (R1/R6): default-off recorder, dormant
)
