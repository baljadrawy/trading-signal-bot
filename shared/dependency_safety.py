"""A43 failure safety for the signal decision's state reads — pure/async helpers, no production caller.

Not every read deserves the same failure rule. Each dependency is classified
by what an unavailable or stale answer could cause:

* ``SAFETY``     — an unknown answer could add exposure or duplicate a signal
                   (open positions, cooldown / emitted-setup ledger, enabled
                   learned-gate throttles). Unavailable ⇒ **no new exposure
                   this cycle** (fail closed), with an explicit reason.
* ``RANKING``    — affects only *which* eligible candidate wins (volume).
                   Unavailable ⇒ degrade deterministically and record it.
* ``DIAGNOSTIC`` — evidence / measurement only. Unavailable ⇒ ignore.

Retries are bounded (attempt count and total time budget); there is no loop
that can run forever, and nothing here restarts or touches other services.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Mapping

SAFETY_VERSION = "a43-ds-v1"


class Criticality(str, Enum):
    SAFETY = "safety"
    RANKING = "ranking"
    DIAGNOSTIC = "diagnostic"


# Classification of the live selector's reads (signal_engine/signal_logic.py @59297305).
DEPENDENCIES: Mapping[str, Criticality] = {
    "candidate_rows": Criticality.SAFETY,        # main.py query; failure today aborts the cycle
    "open_positions": Criticality.SAFETY,        # find_best_signal_live; failure today aborts the cycle
    "symbol_cooldown": Criticality.SAFETY,       # _get_symbol_cooldown_set; failure today returns set() — FAIL-OPEN
    "emitted_setups": Criticality.SAFETY,        # proposed setup-key ledger (A43-B)
    "learned_gates": Criticality.SAFETY,         # only when LEARNING_GATES_ENABLED; failure today aborts
    "macro_context": Criticality.SAFETY,         # MacroContext: already fails closed (stale ⇒ block)
    "selection_volume": Criticality.RANKING,     # _get_volume_usdt; failure today → None → ranks last
    "truncation_measure": Criticality.DIAGNOSTIC,  # _v2_truncation; already guarded
}


def classify_error(exc: BaseException) -> str:
    """Stable error class without importing driver modules."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    names = {c.__name__ for c in type(exc).__mro__}
    if names & {"ConnectionError", "ConnectionDoesNotExistError", "InterfaceError",
                "CannotConnectNowError", "TooManyConnectionsError", "OSError"}:
        return "connection"
    if names & {"PostgresError", "QueryCanceledError", "DataError", "ProgrammingError"}:
        return "query"
    return "unknown"


RETRYABLE = frozenset({"timeout", "connection"})


@dataclass(frozen=True)
class ReadOutcome:
    name: str
    criticality: Criticality
    ok: bool
    value: object = None
    error_class: str | None = None
    error: str | None = None
    attempts: int = 0
    elapsed_s: float = 0.0


async def guarded_read(name: str, fn: Callable[[], Awaitable], *,
                       criticality: Criticality | None = None, timeout_s: float = 2.0,
                       max_attempts: int = 2, backoff_s: float = 0.2, budget_s: float = 5.0,
                       sleep: Callable[[float], Awaitable] = asyncio.sleep,
                       clock: Callable[[], float] = time.monotonic) -> ReadOutcome:
    """Run ``fn`` with a per-attempt timeout, bounded retries and a total budget.

    Never raises for a dependency failure; returns a classified outcome. Only
    timeouts and connection errors are retried; a query error is permanent.
    """
    crit = criticality or DEPENDENCIES.get(name)
    if crit is None:
        raise ValueError(f"unclassified_dependency:{name}")
    if max_attempts < 1 or max_attempts > 5 or timeout_s <= 0 or budget_s <= 0:
        raise ValueError("invalid_retry_bounds")
    start, attempts, last = clock(), 0, None
    while attempts < max_attempts:
        remaining = budget_s - (clock() - start)
        if remaining <= 0:
            break
        attempts += 1
        try:
            value = await asyncio.wait_for(fn(), timeout=min(timeout_s, remaining))
            return ReadOutcome(name, crit, True, value, attempts=attempts, elapsed_s=clock() - start)
        except asyncio.CancelledError:
            raise
        except Exception as exc:                       # classified, never swallowed silently
            last = exc
            if classify_error(exc) not in RETRYABLE:
                break
            if attempts < max_attempts:
                await sleep(backoff_s * attempts)
    return ReadOutcome(name, crit, False, None, classify_error(last) if last else "budget_exhausted",
                       (type(last).__name__ + ": " + str(last))[:200] if last else None,
                       attempts, clock() - start)


@dataclass(frozen=True)
class CycleGate:
    """What the selector may do this cycle, given its reads."""
    allow_new_exposure: bool
    blocked_by: tuple                 # SAFETY reads that failed
    degraded: tuple                   # RANKING reads that failed
    events: tuple = field(default_factory=tuple)   # compact diagnostic events

    @property
    def reason(self) -> str | None:
        return None if self.allow_new_exposure else "safety_state_unverified:" + ",".join(self.blocked_by)


def cycle_gate(outcomes: Mapping[str, ReadOutcome]) -> CycleGate:
    """Combine read outcomes deterministically (sorted by name)."""
    blocked, degraded, events = [], [], []
    for name in sorted(outcomes):
        o = outcomes[name]
        if o.ok:
            continue
        events.append({"dependency": name, "criticality": o.criticality.value,
                       "error_class": o.error_class, "attempts": o.attempts,
                       "version": SAFETY_VERSION})
        if o.criticality is Criticality.SAFETY:
            blocked.append(name)
        elif o.criticality is Criticality.RANKING:
            degraded.append(name)
    return CycleGate(not blocked, tuple(blocked), tuple(degraded), tuple(events))
