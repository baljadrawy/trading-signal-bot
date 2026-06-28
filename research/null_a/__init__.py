"""Conditional Null-A generator + Evidence Store (research-only; NOT wired to live).

Produces the mandatory primary null for the health monitor: random entries matched to the
strategy's regime / volatility / liquidity / session / holding-period buckets, gated by a
distribution-match quality check (a biased or weaker null is rejected, never used).
"""
from .conditional_null import generate_conditional_null, signal_profile
from .quality import null_quality
from .evidence_store import SignalSnapshot
from .buckets import Bucketer, time_of_day_bucket

__all__ = ["generate_conditional_null", "signal_profile", "null_quality",
           "SignalSnapshot", "Bucketer", "time_of_day_bucket"]
