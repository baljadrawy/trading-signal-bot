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
    "execution_calibration",     # A47
)
