"""Failure classification and bounded retry policy for outbox consumers (A38).

TRANSIENT and RATE_LIMITED failures are deferred (shared.outbox.defer): they do not consume
the event's retry budget, and each consumer bounds them by an explicit deadline. PERMANENT
failures use fail(), the counted retry budget, and become observable dead letters.

Telegram error classes are matched by name along the exception's MRO, so this module never
imports python-telegram-bot (trade_tracker does not ship it). In PTB 21, BadRequest and
Forbidden subclass NetworkError, so they are tested first.
"""
import asyncio

from shared.retry_utils import is_network_error

TRANSIENT = 'transient'
RATE_LIMITED = 'rate_limited'
PERMANENT = 'permanent'

_TG_PERMANENT = {'BadRequest', 'Forbidden', 'InvalidToken', 'ChatMigrated', 'Conflict'}
_TG_TRANSIENT = {'TimedOut', 'NetworkError'}


def _names(exc: BaseException) -> set:
    return {cls.__name__ for cls in type(exc).__mro__}


def classify_failure(exc: BaseException) -> tuple:
    """(kind, retry_after_seconds or None)."""
    names = _names(exc)
    if 'RetryAfter' in names:
        after = getattr(exc, 'retry_after', None)
        try:
            after = float(after.total_seconds() if hasattr(after, 'total_seconds') else after)
        except (TypeError, ValueError):
            after = None
        return RATE_LIMITED, after
    if names & _TG_PERMANENT:
        return PERMANENT, None
    if names & _TG_TRANSIENT or is_network_error(exc) or isinstance(exc, asyncio.TimeoutError):
        return TRANSIENT, None
    return PERMANENT, None


def backoff_seconds(deferrals: int, base: float = 60.0, cap: float = 600.0) -> float:
    """60, 120, 240, 480, 600, 600, ... seconds for the n-th consecutive deferral (n >= 0)."""
    n = max(0, int(deferrals or 0))
    return float(min(cap, base * (2 ** min(n, 16))))


def bounded_delay(delay: float, remaining_s) -> float:
    """Never schedule a retry past the deadline. A deferral that would cross it is shortened,
    so the event is re-examined just after the deadline and resolved to its terminal state."""
    if remaining_s is None:
        return max(1.0, float(delay))
    return max(1.0, min(float(delay), float(remaining_s) + 1.0))
