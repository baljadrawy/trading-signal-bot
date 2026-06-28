"""System-health monitor (research-only; NOT wired to the live system).

Reframes monitoring from profitability to SYSTEM HEALTH: dual null (random-entry +
bootstrap), 3 states (HEALTHY/DEGRADED/CRITICAL), input-distribution-shift indicators,
and a reviewable per-cycle decision record. Computes state only — never flips live flags.

    from research.monitoring import evaluate, MonitorWindow
    record = evaluate(current_window, reference_window, null_a_returns=...)
"""
from .health import evaluate, MonitorWindow

__all__ = ["evaluate", "MonitorWindow"]
