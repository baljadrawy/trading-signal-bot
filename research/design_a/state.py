"""Design A v1.0 value types and their validation (spec §3, §9–§11).

Every price, balance and rate is a finite ``Decimal``; every instant is a ``datetime`` whose tzinfo
is ``timezone.utc``. Constructors refuse malformed values and the inconsistent combinations they
can check locally. Arithmetic runs in the fully specified contexts ``EXACT`` and ``FLOOR``, never
in the caller's ambient decimal context, and Decimals are serialised by ``text``.
"""
from __future__ import annotations

import enum
import functools
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from decimal import (ROUND_FLOOR, ROUND_HALF_EVEN, Context, Decimal, DecimalException,
                     DivisionByZero, Inexact, InvalidOperation, Overflow, localcontext)

from research.data_governance.governance import canonical_hash
from research.mechanisms.costs import BASELINE_FEE_PER_SIDE, CostModelError
from research.mechanisms.simulate import SYNTHETIC, DatasetPermission

EVIDENCE_CLASS = "SYNTHETIC"    # v1.0 accepts synthetic data only (spec §0)
# Synthetic snapshots must predate Bitcoin's first block: data carrying real BTC dates (2009 onward,
# including the forward holdout) cannot enter. A safeguard only, not proof of synthetic provenance:
# real prices re-dated before 2009 would pass; provenance rests on the permission declaration.
SYNTHETIC_BEFORE = datetime(2009, 1, 3, tzinfo=timezone.utc)

# Frozen timing (spec F7, F16, F18).
DECISION_OFFSET_SECONDS = 30                    # Monday 00:00 UTC plus 30 seconds
DEFERRAL_WINDOW = timedelta(days=3)             # reference opens within three calendar days
DAY = timedelta(days=1)
WEEK = 7 * DAY
SMA_WINDOW = 200    # the primary configuration; the diagnostics of spec §18 are not implemented

ZERO = Decimal(0)
ONE = Decimal(1)
_RANGE = {"Emin": -999999, "Emax": 999999, "capitals": 1, "clamp": 0, "flags": []}
# Sums, products and comparisons must be exact: any rounding raises instead of drifting.
EXACT = Context(prec=28, rounding=ROUND_HALF_EVEN,
                traps=[InvalidOperation, DivisionByZero, Overflow, Inexact], **_RANGE)
# The one inexact step, the affordable buy quantity, rounds toward zero so it never overspends.
FLOOR = Context(prec=28, rounding=ROUND_FLOOR, traps=[InvalidOperation, DivisionByZero, Overflow],
                **_RANGE)


class DesignAError(ValueError):
    """Refused input: a value, instant, snapshot or permission outside the v1.0 contract."""


class TransitionError(DesignAError):
    """Refused state transition."""


@contextmanager
def arithmetic(context: Context = EXACT):
    """Decimal arithmetic in ``context``; a precision or range failure becomes a DesignAError."""
    try:
        with localcontext(context):
            yield
    except DecimalException as exc:
        raise DesignAError(f"value outside exact Decimal arithmetic ({type(exc).__name__})") from exc


def text(value: Decimal) -> str:
    """Canonical string of a Decimal, independent of the ambient context."""
    return EXACT.to_sci_string(value)


class Target(enum.StrEnum):
    LONG = "LONG"
    FLAT = "FLAT"


class Side(enum.StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class Event(enum.StrEnum):
    # decisions (decision.decide)
    NO_SIGNAL = "NO_SIGNAL"                         # not the weekly decision instant
    WARMUP = "WARMUP"                               # initial warm-up: history not yet 200 days
    SKIP_MISSING_SUNDAY = "SKIP_MISSING_SUNDAY"     # the Sunday candle is unavailable
    SKIP_INVALID_DATA = "SKIP_INVALID_DATA"         # the 200-day window is incomplete
    DECIDE_LONG = "DECIDE_LONG"
    DECIDE_FLAT = "DECIDE_FLAT"
    # transitions (ledger)
    NO_CHANGE = "NO_CHANGE"                         # no genuine state transition
    PENDING_BUY = "PENDING_BUY"
    PENDING_SELL = "PENDING_SELL"
    MISSING_MARKET_DATA = "MISSING_MARKET_DATA"     # a reference candle was due but unavailable
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    REJECTED_MIN_ORDER = "REJECTED_MIN_ORDER"
    RESIDUAL_DUST = "RESIDUAL_DUST"


DECISION_EVENTS = frozenset({Event.NO_SIGNAL, Event.WARMUP, Event.SKIP_MISSING_SUNDAY,
                             Event.SKIP_INVALID_DATA, Event.DECIDE_LONG, Event.DECIDE_FLAT})


class ExecutionStatus(enum.StrEnum):
    PENDING = "PENDING"
    DEFERRED = "DEFERRED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    REJECTED_MIN_ORDER = "REJECTED_MIN_ORDER"


LIVE_STATUSES = frozenset({ExecutionStatus.PENDING, ExecutionStatus.DEFERRED})


def utc(value, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is not timezone.utc:
        raise DesignAError(f"{name} must be a datetime with tzinfo=timezone.utc")
    return value


def amount(value, name: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, not {type(value).__name__}")
    if not value.is_finite() or value < 0 or (positive and value == 0):
        raise DesignAError(f"{name} must be finite and {'> 0' if positive else '>= 0'}")
    return value


def optional(value, kind, name: str):
    if value is not None and not isinstance(value, kind):
        raise TypeError(f"{name} must be a {kind.__name__} or None")
    return value


def is_fingerprint(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef"
                                                               for ch in value)


def is_midnight(at: datetime) -> bool:
    return (at.hour, at.minute, at.second, at.microsecond) == (0, 0, 0, 0)


def is_decision_instant(at: datetime) -> bool:
    """True only at Monday 00:00 UTC plus ``DECISION_OFFSET_SECONDS`` seconds."""
    utc(at, "at")
    return (at.weekday() == 0 and at.hour == 0 and at.minute == 0
            and at.second == DECISION_OFFSET_SECONDS and at.microsecond == 0)


def available_from(open_time: datetime) -> datetime:
    """Provisional availability rule (spec §5, §19 item 1): a daily candle is available once it
    is complete, from the end of its UTC day. Every availability decision derives from here."""
    return open_time + DAY


def require_synthetic(permission) -> None:
    """v1.0 accepts only the synthetic permission itself: no real dataset has an owner record
    (spec §3). Exact type and value, so a subclass or a look-alike cannot pass."""
    if type(permission) is not DatasetPermission or permission != SYNTHETIC:
        raise DesignAError("Design A v1.0 accepts only the synthetic DatasetPermission")


def floor_to_step(quantity: Decimal, step: Decimal) -> Decimal:
    """``quantity`` rounded down to a multiple of ``step``, exactly."""
    with arithmetic():
        return (quantity - quantity % step).quantize(step)


@dataclass(frozen=True)
class Candle:
    """The UTC daily candle of the day opening at ``open_time`` (interval [open_time, +1 day)).
    Volume is used by no v1.0 rule and is not part of the contract."""
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    def __post_init__(self):
        utc(self.open_time, "open_time")
        if not is_midnight(self.open_time):
            raise DesignAError("open_time must be 00:00 UTC")
        for name in ("open", "high", "low", "close"):
            amount(getattr(self, name), name, positive=True)
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise DesignAError("inconsistent candle: open and close must lie within [low, high]")


@dataclass(frozen=True)
class Snapshot:
    """The completed daily candles available at ``as_of``, oldest first, under the synthetic
    permission. Future candles (not yet open) and incomplete ones (still open) are refused, as
    are duplicate or unordered open times, so no snapshot can carry a later observation."""
    as_of: datetime
    candles: tuple[Candle, ...]
    permission: DatasetPermission

    def __post_init__(self):
        utc(self.as_of, "as_of")
        if not isinstance(self.candles, tuple) or not all(isinstance(c, Candle) for c in self.candles):
            raise TypeError("candles must be a tuple of Candle")
        for before, after in zip(self.candles, self.candles[1:]):
            if after.open_time == before.open_time:
                raise DesignAError(f"duplicate candle at {after.open_time.isoformat()}")
            if after.open_time < before.open_time:
                raise DesignAError("candles must be in ascending open_time order")
        if self.candles and self.candles[-1].open_time >= self.as_of:
            raise DesignAError("future candle: open_time at or after as_of")
        if self.candles and available_from(self.candles[-1].open_time) > self.as_of:
            raise DesignAError("incomplete candle: still open at as_of")
        require_synthetic(self.permission)
        if self.as_of >= SYNTHETIC_BEFORE:
            raise DesignAError("synthetic snapshots must be dated before 2009-01-03")


@dataclass(frozen=True)
class CostSpec:
    """Per-side cost rates as fractions; the frozen v1.0 values are ``BASELINE`` and ``STRESS``."""
    fee: Decimal
    half_spread: Decimal
    slippage: Decimal
    label: str

    def __post_init__(self):
        for name in ("fee", "half_spread", "slippage"):
            amount(getattr(self, name), name)
        if self.fee < Decimal(str(BASELINE_FEE_PER_SIDE)):    # the approved 0.10 % floor
            raise CostModelError(
                f"fee {self.fee} is below the 0.10 % baseline; discounted fees are not modelled")
        with arithmetic():
            if self.fee >= ONE or self.half_spread + self.slippage >= ONE:
                raise DesignAError("fee and half_spread + slippage must each be below 1")
        if not isinstance(self.label, str) or not self.label.strip():
            raise DesignAError("label must be a non-empty string")


BASELINE = CostSpec(Decimal("0.001"), Decimal("0.0005"), Decimal("0.0005"), "design_a_baseline")
STRESS = CostSpec(Decimal("0.001"), Decimal("0.001"), Decimal("0.001"), "design_a_stress")


@dataclass(frozen=True)
class MinOrderRules:
    """Configurable minimum-order inputs; no venue values are built in (spec §11)."""
    min_notional: Decimal   # quote currency, compared with quantity x execution price
    min_qty: Decimal        # BTC
    qty_step: Decimal       # BTC; every order quantity is rounded down to a multiple of it

    def __post_init__(self):
        amount(self.min_notional, "min_notional")
        amount(self.min_qty, "min_qty")
        amount(self.qty_step, "qty_step", positive=True)


@dataclass(frozen=True)
class PendingTransition:
    """A decided transition awaiting its reference candle. ``next_open`` starts at the scheduled
    Tuesday open and moves forward one day per unavailable candle, never backward."""
    side: Side
    decided_at: datetime
    next_open: datetime

    def __post_init__(self):
        if not isinstance(self.side, Side):
            raise TypeError("side must be a Side")
        if not is_decision_instant(self.decided_at):
            raise DesignAError("decided_at must be a decision instant")
        utc(self.next_open, "next_open")
        if not is_midnight(self.next_open):
            raise DesignAError("next_open must be 00:00 UTC")
        if not self.decided_at < self.next_open <= self.expires_at:
            raise DesignAError("the reference must open strictly after the decision and within "
                               "three calendar days of it")

    @property
    def expires_at(self) -> datetime:
        return self.decided_at + DEFERRAL_WINDOW

    @property
    def target(self) -> Target:
        return Target.LONG if self.side is Side.BUY else Target.FLAT


@dataclass(frozen=True)
class Decision:
    """The outcome of ``decide`` at ``at``: ``target`` is the intended state and ``action`` the
    genuine state transition it requires (None means none)."""
    at: datetime
    event: Event
    target: Target | None = None
    action: Side | None = None
    reason: str | None = None
    sunday_close: Decimal | None = None
    sma: Decimal | None = None
    window: tuple[str, ...] = ()            # fingerprints of the 200 window candles, oldest first

    def __post_init__(self):
        utc(self.at, "at")
        if not isinstance(self.event, Event) or self.event not in DECISION_EVENTS:
            raise DesignAError(f"{self.event!r} is not a decision event")
        optional(self.action, Side, "action")
        optional(self.reason, str, "reason")
        for name in ("sunday_close", "sma"):
            if getattr(self, name) is not None:
                amount(getattr(self, name), name, positive=True)
        expected = {Event.DECIDE_LONG: Target.LONG, Event.DECIDE_FLAT: Target.FLAT}.get(self.event)
        if self.target is not expected:
            raise DesignAError("target does not match the decision event")
        allowed = {Target.LONG: {None, Side.BUY}, Target.FLAT: {None, Side.SELL}}.get(expected, {None})
        if self.action not in allowed:
            raise DesignAError("action does not match the decision event")
        signal = (self.sunday_close, self.sma)
        if expected is None and signal != (None, None):
            raise DesignAError("only DECIDE_LONG / DECIDE_FLAT carry a Sunday close and an SMA")
        if expected is not None and (None in signal
                                     or (self.sunday_close > self.sma) != (expected is Target.LONG)):
            raise DesignAError("the target must follow F5: LONG iff the Sunday close is above the SMA")
        if not isinstance(self.window, tuple) or not all(is_fingerprint(f) for f in self.window):
            raise DesignAError("window must be a tuple of sha256 fingerprints")
        if len(self.window) != (SMA_WINDOW if expected is not None else 0):
            raise DesignAError("an actionable decision carries the fingerprints of its 200 window "
                               "candles, and no other decision carries any")


@dataclass(frozen=True)
class LedgerEntry:
    """One append-only ledger record; ``cash`` and ``btc`` are the balances after it."""
    seq: int
    at: datetime                            # the decision instant, or when the outcome was known
    event: Event
    cash: Decimal
    btc: Decimal
    reason: str | None = None
    side: Side | None = None
    decided_at: datetime | None = None
    expires_at: datetime | None = None      # end of the three-day reference window
    reference_time: datetime | None = None  # event time: open_time of the reference candle
    reference_price: Decimal | None = None  # P, that candle's open
    execution_price: Decimal | None = None  # P_buy or P_sell
    quantity: Decimal | None = None
    notional: Decimal | None = None         # quantity x execution price
    fee: Decimal | None = None              # quote currency, charged once per executed leg
    spread_cost: Decimal | None = None      # inside the execution price; reported, never re-charged
    slippage_cost: Decimal | None = None    # inside the execution price; reported, never re-charged
    mark_price: Decimal | None = None
    sunday_close: Decimal | None = None
    sma: Decimal | None = None
    window_digest: str | None = None        # actionable decisions: digest of the window fingerprints
    reference_fingerprint: str | None = None  # execution attempts: the reference candle's fingerprint

    def __post_init__(self):
        if isinstance(self.seq, bool) or not isinstance(self.seq, int) or self.seq < 0:
            raise DesignAError("seq must be a non-negative int")
        utc(self.at, "at")
        if not isinstance(self.event, Event):
            raise TypeError("event must be an Event")
        optional(self.reason, str, "reason")
        optional(self.side, Side, "side")
        for name in ("decided_at", "expires_at", "reference_time"):
            if getattr(self, name) is not None:
                utc(getattr(self, name), name)
        amount(self.cash, "cash")
        amount(self.btc, "btc")
        for name in ("reference_price", "execution_price", "quantity", "notional", "fee",
                     "spread_cost", "slippage_cost", "mark_price", "sunday_close", "sma"):
            if getattr(self, name) is not None:
                amount(getattr(self, name), name)
        for name in ("window_digest", "reference_fingerprint"):
            if getattr(self, name) is not None and not is_fingerprint(getattr(self, name)):
                raise DesignAError(f"{name} must be a sha256 fingerprint")

    def record(self) -> dict:
        """JSON-ready form: every set field, with Decimals and instants as canonical strings."""
        out = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None:
                continue
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, Decimal):
                value = text(value)
            elif not isinstance(value, int):
                value = str(value)
            out[f.name] = value
        return out


@dataclass(frozen=True)
class State:
    """Actual balances, intended target, pending transition, execution status and the ledger,
    kept separately (spec F29). Operations never mutate a State; they return one."""
    cash: Decimal
    btc: Decimal
    costs: CostSpec
    rules: MinOrderRules
    target: Target | None = None
    pending: PendingTransition | None = None
    execution_status: ExecutionStatus | None = None
    last_decision_at: datetime | None = None
    ledger: tuple[LedgerEntry, ...] = ()
    consumed: tuple[tuple[datetime, str], ...] = ()   # integrity index: (open time, fingerprint)

    def __post_init__(self):
        amount(self.cash, "cash")
        amount(self.btc, "btc")
        if not isinstance(self.costs, CostSpec) or not isinstance(self.rules, MinOrderRules):
            raise TypeError("costs must be a CostSpec and rules a MinOrderRules")
        optional(self.target, Target, "target")
        optional(self.pending, PendingTransition, "pending")
        optional(self.execution_status, ExecutionStatus, "execution_status")
        if self.last_decision_at is not None:
            utc(self.last_decision_at, "last_decision_at")
        if not isinstance(self.ledger, tuple) or not all(isinstance(e, LedgerEntry)
                                                         for e in self.ledger):
            raise TypeError("ledger must be a tuple of LedgerEntry")
        if any(e.seq != i for i, e in enumerate(self.ledger)) or any(
                a.at > b.at for a, b in zip(self.ledger, self.ledger[1:])):
            raise DesignAError("ledger entries must be numbered 0, 1, ... in time order")
        if self.ledger and (self.ledger[-1].cash, self.ledger[-1].btc) != (self.cash, self.btc):
            raise DesignAError("the last ledger entry must carry the current balances")
        if not isinstance(self.consumed, tuple) or not all(
                isinstance(p, tuple) and len(p) == 2 and isinstance(p[0], datetime)
                and p[0].tzinfo is timezone.utc and is_midnight(p[0]) and is_fingerprint(p[1])
                for p in self.consumed):
            raise DesignAError("consumed must hold (00:00 UTC open time, sha256) pairs")
        if any(a[0] >= b[0] for a, b in zip(self.consumed, self.consumed[1:])):
            raise DesignAError("consumed open times must be strictly increasing")
        if (self.pending is not None) != (self.execution_status in LIVE_STATUSES):
            raise DesignAError("a pending transition exists exactly while the status is "
                               "PENDING or DEFERRED")
        if self.pending is not None and (self.pending.decided_at != self.last_decision_at
                                         or self.pending.target is not self.target):
            raise DesignAError("a pending transition must belong to the last decision and its target")


def initial_state(cash: Decimal, costs: CostSpec, rules: MinOrderRules) -> State:
    """Start in cash (spec F9)."""
    return State(cash=amount(cash, "cash", positive=True), btc=ZERO, costs=costs, rules=rules)


def actual_position(state: State) -> Target:
    """LONG iff the BTC balance rounded down to qty_step is positive and at least min_qty.

    From the frozen start in cash this is unambiguous: after a buy only cash too small for one
    more step remains, after a sell only BTC below one step. A state holding both a tradable BTC
    balance and buyable cash is outside the v1.0 contract (spec §9)."""
    tradable = floor_to_step(state.btc, state.rules.qty_step)
    return Target.LONG if tradable > 0 and tradable >= state.rules.min_qty else Target.FLAT


def required_action(state: State, target: Target) -> Side | None:
    """The transition a valid weekly ``target`` requires from the actual tradable position, or
    None when the portfolio is already positioned (no rebalance, no duplicate of a fill).

    Owner decision (2026-10-31, spec F10): an earlier transition that expired, was rejected by
    the minimum-order rules or otherwise did not execute is retried at the next valid weekly
    decision whose target still differs from the actual position, even if the target is
    unchanged. Retries happen only here, at weekly decisions; skipped decisions carry no target."""
    if not isinstance(target, Target):
        raise TypeError("target must be a Target")
    if target is actual_position(state):
        return None
    return Side.BUY if target is Target.LONG else Side.SELL


def check_inputs(state: State, snapshot: Snapshot) -> None:
    """Type checks, and the permission again: deliberate defence in depth beside ``Snapshot``."""
    if not isinstance(state, State) or not isinstance(snapshot, Snapshot):
        raise TypeError("expected (state: State, snapshot: Snapshot)")
    require_synthetic(snapshot.permission)
    check_consumed(state, snapshot)


# Candle integrity (spec §5). Integrity checks keep data already admitted under the permission
# consistent; passing them never authorizes access to any historical or protected data.

@functools.lru_cache(maxsize=65536)
def candle_fingerprint(candle: Candle) -> str:
    """sha256 (the repository's ``canonical_hash``) of a candle's open time and numeric OHLC
    values; trailing zeros do not count, so equal candles share one fingerprint."""
    with arithmetic():
        values = {name: text(getattr(candle, name).normalize())
                  for name in ("open", "high", "low", "close")}
    return canonical_hash({"open_time": candle.open_time.isoformat(), **values})


def window_days(decision_time: datetime) -> tuple[datetime, ...]:
    """Open times of the SMA_WINDOW candles an actionable decision at ``decision_time`` uses."""
    sunday = decision_time.replace(hour=0, minute=0, second=0, microsecond=0) - DAY
    return tuple(sunday - DAY * k for k in range(SMA_WINDOW - 1, -1, -1))


def merge_consumed(consumed, pairs) -> tuple[tuple[datetime, str], ...]:
    """``consumed`` plus (open time, fingerprint) ``pairs``; a different fingerprint for a candle
    already consumed is a revision and is refused."""
    index = dict(consumed)
    for day, fingerprint in pairs:
        if index.setdefault(day, fingerprint) != fingerprint:
            raise DesignAError(f"candle {day.isoformat()} differs from the one consumed earlier")
    return tuple(sorted(index.items()))


def check_consumed(state: State, snapshot: Snapshot, since: datetime | None = None) -> None:
    """Refuse a snapshot that contradicts a consumed candle, before anything is processed.

    Coverage: every consumed candle available at the snapshot's ``as_of`` that opens at or after
    its first candle, or at or after ``since`` when that is earlier, must be present and
    identical; an absent one is refused as missing, never assumed to match. ``decide`` passes the
    first day of the window it reads, so a snapshot cut short inside that window is refused, not
    skipped. Older consumed candles are read by nothing the snapshot can decide or execute, so
    that snapshot does not re-check them."""
    starts = [c.open_time for c in snapshot.candles[:1]] + ([] if since is None else [since])
    if not state.consumed or not starts:
        return
    first = min(starts)
    present = {c.open_time: c for c in snapshot.candles}
    for day, fingerprint in state.consumed:
        if day < first or available_from(day) > snapshot.as_of:
            continue
        candle = present.get(day)
        if candle is None:
            raise DesignAError(f"previously consumed candle {day.isoformat()} is missing")
        if candle_fingerprint(candle) != fingerprint:
            raise DesignAError(f"candle {day.isoformat()} differs from the one consumed earlier")


def verify_integrity(state: State) -> None:
    """Cross-check the consumed index with the ledger: every actionable decision's window digest
    and every execution attempt's reference fingerprint must match it, and it may hold nothing
    else. Run on restoration and at the start of every replay call."""
    index = dict(state.consumed)
    used = set()
    for e in state.ledger:
        if e.event in (Event.DECIDE_LONG, Event.DECIDE_FLAT):
            days = window_days(e.at)
            fingerprints = [index.get(d) for d in days]
            if None in fingerprints or e.window_digest != canonical_hash(fingerprints):
                raise DesignAError(f"integrity: the window of the decision at "
                                   f"{e.at.isoformat()} does not match the consumed index")
            used.update(days)
        elif e.event in (Event.EXECUTED, Event.REJECTED_MIN_ORDER):
            if (e.reference_fingerprint is None
                    or index.get(e.reference_time) != e.reference_fingerprint):
                raise DesignAError(f"integrity: the reference candle of entry {e.seq} does not "
                                   f"match the consumed index")
            used.add(e.reference_time)
        elif e.window_digest is not None or e.reference_fingerprint is not None:
            raise DesignAError(f"integrity: entry {e.seq} consumes no candle but carries a "
                               f"fingerprint")
    if used != set(index):
        raise DesignAError("integrity: the consumed index holds candles no ledger entry used")
