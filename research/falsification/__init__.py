"""Unified falsification battery (research-only; NOT wired to the live system).

Assume no alpha until proven. A signal/feature/weight passes only if it beats a
random-entry null (P>0.95) with a CI excluding zero, survives remove-best, holds
out-of-sample, and has a non-negative information ratio.

    from research.falsification import validate, StrategyData
    result = validate(StrategyData(returns=..., null_returns=...))
"""
from .core import validate, StrategyData

__all__ = ["validate", "StrategyData"]
