"""A43 signal identity, freshness and idempotent emission — pure; no production caller.

One actionable setup on one closed candle may be emitted **once**, whatever
the cooldown clock says. Identity is anchored to the exchange candle, not to
wall-clock time, so process restarts, concurrent cycles and late re-analysis
of an old candle all map to the same key.

Integration boundary (not wired; owner approval required):
* the analyzer must stamp ``candle_open_time_ms`` / ``candle_close_time_ms``
  unconditionally (today they are written only while EVIDENCE_V2_ENABLED);
* ``signals.setup_key`` + a partial unique index make the insert itself
  idempotent (proposal: ``docs/a43/proposed_011_signal_setup_key.sql``);
* ``save_signal`` would insert with ``ON CONFLICT (setup_key) DO NOTHING`` and
  publish ``signal.ready`` only when a row was created.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from typing import Iterable, Mapping

IDENTITY_VERSION = "a43-sid-v1"
INTEGRITY_MODES = ("off", "enforce")


def integrity_mode(cfg) -> str:
    """The configured SIGNAL_INTEGRITY_MODE; an unknown value refuses to start (fail closed)."""
    mode = str(getattr(cfg, "SIGNAL_INTEGRITY_MODE", "off")).strip().lower()
    if mode not in INTEGRITY_MODES:
        raise RuntimeError(f"unknown SIGNAL_INTEGRITY_MODE {mode!r}; expected one of {INTEGRITY_MODES}")
    return mode

TIMEFRAME_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
DIRECTIONS = ("long",)                     # the strategy is long-only today


class IdentityError(ValueError):
    """The candidate cannot be identified; callers must treat it as ineligible."""


def _sha(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _int_ms(value, name) -> int:
    if value is None:
        raise IdentityError(f"{name}_missing")
    if isinstance(value, int) and not isinstance(value, bool):
        number = value
    elif isinstance(value, str) and value.isdigit():
        number = int(value)
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    else:
        raise IdentityError(f"{name}_malformed")
    if number <= 0:
        raise IdentityError(f"{name}_malformed")
    return number


@dataclass(frozen=True)
class SetupIdentity:
    """Semantic identity of an actionable setup. Bracket prices are *not* part
    of the key (same candle ⇒ same setup); they are hashed separately so a
    recomputed, different bracket on the same candle is detected as a conflict."""
    symbol: str
    timeframe: str
    candle_open_ms: int
    candle_close_ms: int
    trade_type: str
    direction: str
    strategy_version: str
    setup_policy: str                       # e.g. fixed_execution_quality_v1
    identity_version: str = IDENTITY_VERSION

    @property
    def candle_end_ms(self) -> int:
        """First millisecond after the candle (Binance close_time is open + tf − 1)."""
        return self.candle_close_ms + 1

    @property
    def key(self) -> str:
        return "sk_" + _sha([self.identity_version, self.symbol, self.timeframe, self.candle_open_ms,
                             self.trade_type, self.direction, self.strategy_version,
                             self.setup_policy])[:40]


def identity_from_candidate(candidate: Mapping, *, strategy_version: str,
                            direction: str = "long") -> SetupIdentity:
    """Build the identity from an analyzer candidate (``pit`` block). Fails closed."""
    symbol = candidate.get("symbol")
    timeframe = candidate.get("timeframe")
    trade_type = candidate.get("trade_type")
    if not symbol or not isinstance(symbol, str):
        raise IdentityError("symbol_missing")
    if timeframe not in TIMEFRAME_MS:
        raise IdentityError("timeframe_unknown")
    if not trade_type:
        raise IdentityError("trade_type_missing")
    if direction not in DIRECTIONS:
        raise IdentityError("direction_unsupported")
    if not strategy_version:
        raise IdentityError("strategy_version_missing")
    # Correctness-critical block written by the analyzer (A44); the evidence ``pit`` block is
    # accepted only as a fallback for A43 fixtures — both come from candle_bounds().
    block = candidate.get("candle_identity")
    if block is None:
        if candidate.get("candle_identity_error"):
            raise IdentityError(str(candidate["candle_identity_error"]))
        block = candidate.get("pit") or {}
    if not isinstance(block, Mapping):
        raise IdentityError("candle_identity_malformed")
    open_ms, close_ms = _validated_bounds(block, timeframe)
    return SetupIdentity(symbol=symbol, timeframe=timeframe, candle_open_ms=open_ms,
                         candle_close_ms=close_ms, trade_type=str(trade_type), direction=direction,
                         strategy_version=str(strategy_version),
                         setup_policy=str(candidate.get("selection_policy") or "unspecified"))


CANDLE_BLOCK_VERSION = 1


def candle_bounds(df, timeframe: str) -> dict:
    """Exchange bounds of the last CLOSED candle of a prepared OHLCV frame, validated.

    The derivation itself is ``evidence_v2.candle_pit`` (the existing, single implementation of
    "index = Binance open time, ``close_time`` column = Binance close ms"); this layer makes it
    correctness-critical: anything it cannot derive, or that is misaligned / inconsistent,
    raises ``IdentityError`` instead of degrading to an empty block."""
    from shared import evidence_v2
    if timeframe not in TIMEFRAME_MS:
        raise IdentityError("timeframe_unknown")
    if df is None or len(df) == 0:
        raise IdentityError("candle_frame_empty")
    pit = evidence_v2.candle_pit(df, timeframe, None)
    if not pit:
        raise IdentityError("candle_bounds_unavailable")
    block = {"version": CANDLE_BLOCK_VERSION, "candle_open_time_ms": pit["candle_open_time_ms"],
             "candle_close_time_ms": pit["candle_close_time_ms"]}
    _validated_bounds(block, timeframe)
    return block


def _validated_bounds(block: Mapping, timeframe: str) -> tuple:
    open_ms = _int_ms(block.get("candle_open_time_ms"), "candle_open_time")
    close_ms = _int_ms(block.get("candle_close_time_ms"), "candle_close_time")
    step = TIMEFRAME_MS[timeframe]
    if open_ms % step:
        raise IdentityError("candle_open_not_aligned")
    if close_ms != open_ms + step - 1:
        raise IdentityError("candle_close_inconsistent")
    return open_ms, close_ms


def bracket_hash(candidate: Mapping) -> str:
    """Hash of the executable bracket (entry, stop, targets, stop policy)."""
    fields = ("entry_price", "stop_loss", "target_1", "target_2", "target_3", "stop_policy")
    return _sha([repr(candidate.get(f)) for f in fields])[:24]


# ── freshness ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Freshness:
    admissible: bool
    reason: str | None
    age_ms: int
    age_bars: float


def freshness(identity: SetupIdentity, decision_ms: int, *, max_age_bars: float = 1.0) -> Freshness:
    """A setup is actionable from its candle end until the next candle closes.

    Once a newer candle has closed, the setup is *superseded*: re-emitting it
    acts on stale data (A43 found 4h signals emitted 244 min after close).
    """
    return freshness_at(identity.timeframe, identity.candle_close_ms, decision_ms,
                        max_age_bars=max_age_bars)


def freshness_at(timeframe: str, candle_close_ms: int, decision_ms: int, *,
                 max_age_bars: float = 1.0) -> Freshness:
    """The freshness rule on raw candle bounds (used by the tracker on stored identities)."""
    if not 0 < max_age_bars <= 1.0:
        raise ValueError("max_age_bars must be in (0, 1]")
    if timeframe not in TIMEFRAME_MS:
        return Freshness(False, "timeframe_unknown", 0, float("nan"))
    step = TIMEFRAME_MS[timeframe]
    age = int(decision_ms) - (int(candle_close_ms) + 1)
    bars = age / step
    if age < 0:
        return Freshness(False, "decision_before_candle_close", age, bars)
    if age >= step * max_age_bars:
        return Freshness(False, "superseded_by_newer_candle", age, bars)
    return Freshness(True, None, age, bars)


# ── idempotent emission ledger ──────────────────────────────────────────────

@dataclass(frozen=True)
class Claim:
    status: str          # claimed | duplicate | conflict
    key: str
    first_bracket: str | None = None


@dataclass
class EmissionLedger:
    """In-memory model of the proposed ``signals.setup_key`` unique index.

    ``claim`` is atomic under one asyncio lock, mirroring what the unique index
    gives across processes. ``snapshot``/``restore`` model a restart: the DB
    keeps the keys, so a restarted worker sees earlier emissions.
    """
    _seen: dict = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def claim_sync(self, identity: SetupIdentity, bracket: str) -> Claim:
        first = self._seen.get(identity.key)
        if first is None:
            self._seen[identity.key] = bracket
            return Claim("claimed", identity.key)
        return Claim("duplicate" if first == bracket else "conflict", identity.key, first)

    async def claim(self, identity: SetupIdentity, bracket: str) -> Claim:
        async with self._lock:
            await asyncio.sleep(0)               # a scheduling point inside the critical section
            return self.claim_sync(identity, bracket)

    def snapshot(self) -> dict:
        return dict(self._seen)

    @classmethod
    def restore(cls, snapshot: Mapping) -> "EmissionLedger":
        return cls(_seen=dict(snapshot))


# ── combined eligibility verdict ───────────────────────────────────────────

@dataclass(frozen=True)
class IntegrityVerdict:
    eligible: bool
    reasons: tuple
    key: str | None
    freshness: Freshness | None


def integrity_check(candidate: Mapping, *, decision_ms: int, strategy_version: str,
                    emitted_keys: Iterable[str] = (), max_age_bars: float = 1.0) -> IntegrityVerdict:
    """Pure pre-emission check: identifiable, fresh, not already emitted."""
    try:
        ident = identity_from_candidate(candidate, strategy_version=strategy_version)
    except IdentityError as exc:
        return IntegrityVerdict(False, (f"identity:{exc}",), None, None)
    fresh = freshness(ident, decision_ms, max_age_bars=max_age_bars)
    reasons = [] if fresh.admissible else [f"freshness:{fresh.reason}"]
    if ident.key in set(emitted_keys):
        reasons.append("duplicate_setup")
    return IntegrityVerdict(not reasons, tuple(reasons), ident.key, fresh)
