"""WP-D03 position lifecycle state machine (SE-66, WP-IR-06): pure, deterministic, Decimal.

One machine for the life of one long spot position, from the entry intent to a terminal state
(docs/design/remediation-design-pack-20261101/STRATEGY_AND_EXECUTION_CONTRACT.md §B6). The
portfolio ``Position.state`` (PORTFOLIO_RISK_AND_COMPOUNDING.md §3.2) is its projection,
``PROJECTION``, never a second source of truth (WP-IR-06).

Two layers, both free of I/O, clocks and randomness:

* ``apply(record, event)`` is the transition function. It looks ``(record.state, event.kind)`` up
  in ``TRANSITIONS``, validates every quantity and level, and returns the new record plus a
  ``Transition`` that names the table row, the ledger events the step implies (PR §3.3) and, for
  a refusal before fill, its F7 reason code. Any other pair, a terminal state, an overfill, an
  over-exit, a partial "exit remaining" or a malformed value raises ``TransitionRefused``.
  Records are immutable, so a refused event leaves the caller's record unchanged; no event is
  ever a silent no-op.
* Guards turn market observations into events: ``entry_guard`` (the PLANNED rows of §B6),
  ``observation_events`` (stop in force, targets, post-target stop, time rules; SE-41) and
  ``closed_bar_events`` (the pre-T1 closed-bar invalidation). ``step`` applies their events in
  order through ``apply``.

The machine never chooses a value. Quantities, levels, exit fractions, the lot step, the stop
policy, the stop fill model and the time rules are required inputs; none has a default.

Rows whose ``source`` is ``extension`` are lifecycle steps the §B6 table does not list, but which
the contract implies (RESERVE at intent, the fill of a resting order, partial entry fills, stop
moves) or which the current tracker performs (owner and operational closes). They are kept in the
same table so that each gap is explicit and testable.

Conventions on one observation, the same as ``shared/triple_barrier.py`` (parity-tested):

1. The stop in force at the start of the observation wins over every target (SE-41).
2. Targets the observation reaches are taken in order, each at its own level, so a gap through
   several targets is one transition per target.
3. The stop that the policy gives after those targets and the new peak is checked against the
   same observation; then the declared time rules, in their declared order.

Quantities: the last target with a non-zero exit fraction sells the remainder; other tranches are
``qty_filled × fraction`` floored to the lot step. Any exit leg that leaves no open quantity
closes the position (§B6 ``CLOSED``: quantity 0). Entry fills are allowed only before the first
exit; the first exit ends an unfilled entry remainder and releases its reservation.

Integration: ``Transition.ledger_events`` map one-to-one onto ``shared/portfolio_ledger.py``
events (``RESERVE`` -> Reserve, ``ENTRY_FILL`` -> EntryFill, ``EXIT_FILL`` -> ExitFill,
``RELEASE`` -> ReleaseReservation) with ``position_id`` = ``intent_id``. Refusal codes are
taxonomy-v1 codes (``shared/funnel_records.py``) with ``sub_stage`` ``shared.order_intent``.
``restore`` rebuilds a record from persisted fields, so a service can validate each lifecycle
step it takes; ``decimal_from_legacy`` converts the tracker's float columns exactly.
"""
from __future__ import annotations

import dataclasses
import math
import re
from dataclasses import dataclass
from decimal import (ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, Inexact, InvalidOperation,
                     Overflow, localcontext)
from typing import Callable, ClassVar, Sequence

MACHINE_VERSION = "wp-d03-position-state-v1"

# ── states (§B6) ───────────────────────────────────────────────────────────────────────────

PLANNED = "PLANNED"
WORKING = "WORKING"
OPEN = "OPEN"
PARTIAL_T1 = "PARTIAL_T1"
PARTIAL_T2 = "PARTIAL_T2"
CLOSED = "CLOSED"
REJECTED = "REJECTED"
EXPIRED_UNFILLED = "EXPIRED_UNFILLED"
STATES = (PLANNED, WORKING, OPEN, PARTIAL_T1, PARTIAL_T2, CLOSED, REJECTED, EXPIRED_UNFILLED)
PRE_FILL_STATES = (PLANNED, WORKING)
OPEN_STATES = (OPEN, PARTIAL_T1, PARTIAL_T2)
TERMINAL_STATES = (CLOSED, REJECTED, EXPIRED_UNFILLED)
TARGETS = (1, 2, 3)
_STATE_FOR_TARGET = {0: OPEN, 1: PARTIAL_T1, 2: PARTIAL_T2}

# WP-IR-06: projection onto PR §3.2 ``Position.state``; None means no position was created.
PROJECTION = {PLANNED: "pending", WORKING: "pending", OPEN: "open", PARTIAL_T1: "partially_exited",
              PARTIAL_T2: "partially_exited", CLOSED: "closed", REJECTED: None,
              EXPIRED_UNFILLED: None}
PROJECTION_STEPS = frozenset({
    ("pending", "pending"), ("pending", "open"), ("pending", None),
    ("open", "open"), ("open", "partially_exited"), ("open", "closed"),
    ("partially_exited", "partially_exited"), ("partially_exited", "closed"),
})

# PR §3.3 ledger event names.
RESERVE = "RESERVE"
ENTRY_FILL = "ENTRY_FILL"
EXIT_FILL = "EXIT_FILL"
RELEASE = "RELEASE"
LEDGER_EVENTS = (RESERVE, ENTRY_FILL, EXIT_FILL, RELEASE)

# Refusals before fill (§B6; WP-IR-01, WP-IR-05): stage F7, sub_stage shared.order_intent.
ORDER_INTENT_SUB_STAGE = "shared.order_intent"
CODE_INVALIDATED = "F7.entry_rejected"
RULE_INVALIDATED = "signal_invalidated_before_fill"      # detail.rule of CODE_INVALIDATED
CODE_BELOW_MINIMUM = "F7.min_notional_infeasible"        # SE name below_exchange_minimum
CODE_WAIT_EXPIRED = "F7.entry_wait_expired"
_F7_CODE = re.compile(r"^F7\.[a-z0-9_]+(:[a-z0-9][a-z0-9_.]{0,63})?$")

# entry_guard outcomes (§B6 PLANNED rows).
ENTRY_INVALIDATED = "invalidated"    # price <= max(stop, invalidation): reject
ENTRY_FILLABLE = "fillable"          # price <= planned entry: fill under the active fill model
ENTRY_REST = "rest"                  # PLANNED and price > planned entry: rest (do not chase)
ENTRY_WAIT = "wait"                  # WORKING and price > planned entry: keep resting

# Exit leg kinds; also ``PositionRecord.exit_kind`` of a closed position.
EXIT_KINDS = ("target", "stop", "invalidation", "time", "thesis", "admin")

# Every addition, subtraction and multiplication of finite decimals is exact at this precision;
# Inexact is trapped, so a value that would need rounding is refused, never rounded silently.
_EXACT = Context(prec=60, rounding=ROUND_HALF_EVEN, Emin=-999_999, Emax=999_999,
                 traps=[InvalidOperation, DivisionByZero, Overflow, Inexact])
ZERO = Decimal(0)


class TransitionRefused(ValueError):
    """An event, record, plan or observation the machine refuses; ``reason`` is a stable code."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


# ── validation helpers ─────────────────────────────────────────────────────────────────────

def _dec(value, name: str, *, positive: bool = False, non_negative: bool = False,
         reason: str = "invalid_event") -> Decimal:
    """A finite Decimal from a Decimal or int. Floats are refused: they are not exact."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise TransitionRefused(reason, f"{name} must be Decimal or int, not {type(value).__name__}")
    number = Decimal(value)
    if not number.is_finite():
        raise TransitionRefused(reason, f"{name} is not finite")
    if positive and number <= 0:
        raise TransitionRefused(reason, f"{name} must be > 0")
    if non_negative and number < 0:
        raise TransitionRefused(reason, f"{name} must be >= 0")
    return number


def _text(value, name: str, reason: str = "invalid_event") -> str:
    if not isinstance(value, str) or not value.strip():
        raise TransitionRefused(reason, f"{name} must be a non-empty string")
    return value


def _aligned(qty: Decimal, step: Decimal, name: str, reason: str = "qty_not_step_aligned") -> None:
    with localcontext(_EXACT):
        if qty % step != 0:
            raise TransitionRefused(reason, f"{name} {qty} is not a multiple of {step}")


def _sum(values) -> Decimal:
    with localcontext(_EXACT):
        total = ZERO
        for value in values:
            total += value
        return total


def decimal_from_legacy(value) -> Decimal:
    """Exact Decimal for a legacy float/int/Decimal column: a float becomes its shortest repr,
    which round-trips to the same float. Non-finite values are refused."""
    if isinstance(value, bool):
        raise TransitionRefused("invalid_value", "bool is not a number")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TransitionRefused("invalid_value", f"non-finite {value!r}")
        return Decimal(repr(value))
    return _dec(value, "value", reason="invalid_value")


# ── plan and record ────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PositionPlan:
    """The entry intent: what the strategy and the SizingDecision fixed before anything is sent.

    ``targets`` and ``exit_fractions`` are (T1, T2, T3). Fractions are >= 0 and sum to exactly 1
    (SE-42); a tranche merged away for an exchange minimum is a zero fraction. ``invalidation``
    is the pre-T1 thesis level; pass the stop when the strategy declares none."""
    intent_id: str
    symbol: str
    strategy_id: str
    planned_qty: Decimal
    planned_entry: Decimal
    stop: Decimal
    invalidation: Decimal
    targets: tuple
    exit_fractions: tuple
    qty_step: Decimal


def validate_plan(plan: PositionPlan) -> PositionPlan:
    """Refuse an incomplete or inconsistent plan (``invalid_plan``); return it unchanged."""
    if not isinstance(plan, PositionPlan):
        raise TransitionRefused("invalid_plan", f"expected PositionPlan, not {type(plan).__name__}")
    for name in ("intent_id", "symbol", "strategy_id"):
        _text(getattr(plan, name), name, "invalid_plan")
    qty = _dec(plan.planned_qty, "planned_qty", positive=True, reason="invalid_plan")
    step = _dec(plan.qty_step, "qty_step", positive=True, reason="invalid_plan")
    _aligned(qty, step, "planned_qty", "invalid_plan")
    entry = _dec(plan.planned_entry, "planned_entry", positive=True, reason="invalid_plan")
    stop = _dec(plan.stop, "stop", positive=True, reason="invalid_plan")
    _dec(plan.invalidation, "invalidation", positive=True, reason="invalid_plan")
    if not isinstance(plan.targets, tuple) or len(plan.targets) != 3:
        raise TransitionRefused("invalid_plan", "targets must be a tuple (T1, T2, T3)")
    t1, t2, t3 = (_dec(t, f"T{i}", positive=True, reason="invalid_plan")
                  for i, t in enumerate(plan.targets, 1))
    if not stop < entry < t1 < t2 < t3:                      # SE-40 item 4
        raise TransitionRefused("invalid_plan", "levels must satisfy stop < entry < T1 < T2 < T3")
    if not isinstance(plan.exit_fractions, tuple) or len(plan.exit_fractions) != 3:
        raise TransitionRefused("invalid_plan", "exit_fractions must be a tuple (f1, f2, f3)")
    fractions = [_dec(f, f"f{i}", non_negative=True, reason="invalid_plan")
                 for i, f in enumerate(plan.exit_fractions, 1)]
    if _sum(fractions) != 1:
        raise TransitionRefused("invalid_plan", "exit fractions must sum to exactly 1")
    return plan


@dataclass(frozen=True)
class Leg:
    """One fill. ``kind`` is ``entry`` or one of EXIT_KINDS; ``target`` is set for target legs."""
    kind: str
    qty: Decimal
    price: Decimal
    target: int | None


@dataclass(frozen=True)
class PositionRecord:
    """The lifecycle state of one intent. Quantities derive from the legs (one source of truth).

    ``reservation_active``: the intent's reservation still holds an unconsumed remainder.
    ``entry_open``: the unfilled entry remainder may still fill. ``stop_level``: the stop in
    force. ``reason_code``: F7 code of a refusal before fill. ``exit_kind``/``exit_rule``: how a
    closed position ended (``exit_rule`` labels time, thesis and admin exits)."""
    plan: PositionPlan
    state: str
    reservation_active: bool
    entry_open: bool
    entry_legs: tuple
    exit_legs: tuple
    highest_target: int
    stop_level: Decimal
    reason_code: str | None
    exit_kind: str | None
    exit_rule: str | None

    @property
    def qty_filled(self) -> Decimal:
        return _sum(leg.qty for leg in self.entry_legs)

    @property
    def qty_exited(self) -> Decimal:
        return _sum(leg.qty for leg in self.exit_legs)

    @property
    def qty_open(self) -> Decimal:
        with localcontext(_EXACT):
            return self.qty_filled - self.qty_exited

    @property
    def entry_remaining(self) -> Decimal:
        with localcontext(_EXACT):
            return self.plan.planned_qty - self.qty_filled

    @property
    def projection(self) -> str | None:
        return PROJECTION[self.state]


def _bad(detail: str):
    raise TransitionRefused("invalid_record", detail)


def check_record(record: PositionRecord) -> None:
    """Raise ``TransitionRefused('invalid_record')`` unless every lifecycle invariant holds."""
    if not isinstance(record, PositionRecord):
        _bad(f"expected PositionRecord, not {type(record).__name__}")
    plan = validate_plan(record.plan)
    if record.state not in STATES:
        _bad(f"unknown state {record.state!r}")
    if not isinstance(record.reservation_active, bool) or not isinstance(record.entry_open, bool):
        _bad("reservation_active and entry_open must be bool")
    if not isinstance(record.entry_legs, tuple) or not isinstance(record.exit_legs, tuple):
        _bad("legs must be tuples")
    for leg in record.entry_legs + record.exit_legs:
        if not isinstance(leg, Leg):
            _bad("legs must be Leg records")
        _dec(leg.qty, "leg qty", positive=True, reason="invalid_record")
        _dec(leg.price, "leg price", positive=True, reason="invalid_record")
        _aligned(leg.qty, plan.qty_step, "leg qty", "invalid_record")
    if any(leg.kind != "entry" or leg.target is not None for leg in record.entry_legs):
        _bad("entry legs must have kind 'entry' and no target")
    for leg in record.exit_legs:
        if leg.kind not in EXIT_KINDS:
            _bad(f"unknown exit leg kind {leg.kind!r}")
        if (leg.kind == "target") != (leg.target in TARGETS):
            _bad("target legs, and only target legs, carry a target 1..3")
        if leg.kind == "target" and leg.target > record.highest_target:
            _bad("a target leg above highest_target")
    if isinstance(record.highest_target, bool) or record.highest_target not in (0, 1, 2, 3):
        _bad(f"highest_target {record.highest_target!r}")
    _dec(record.stop_level, "stop_level", positive=True, reason="invalid_record")
    filled, exited = record.qty_filled, record.qty_exited
    if filled > plan.planned_qty:
        _bad("filled quantity exceeds the planned quantity")
    if exited > filled:
        _bad("exited quantity exceeds the filled quantity")
    state, open_qty = record.state, record.qty_open
    if record.reservation_active and not record.entry_open:
        _bad("an active reservation needs an open entry")
    if state in PRE_FILL_STATES:
        if record.entry_legs or record.exit_legs or record.highest_target or not record.entry_open:
            _bad(f"{state} has fills, a target or a closed entry")
        if state == WORKING and not record.reservation_active:
            _bad("WORKING needs an active reservation")
    elif state in OPEN_STATES:
        if filled == 0 or open_qty == 0:
            _bad(f"{state} needs an open quantity")
        if _STATE_FOR_TARGET.get(record.highest_target) != state:
            _bad(f"{state} with highest_target {record.highest_target}")
        if state == OPEN and record.exit_legs:
            _bad("OPEN has no exit legs")
        if state != OPEN and record.entry_open:
            _bad("entry is closed once exits begin")
        if record.entry_open != record.reservation_active:
            _bad("an open entry remainder holds its reservation")
        if record.entry_open and filled == plan.planned_qty:
            _bad("entry is complete but still open")
    elif state == CLOSED:
        if filled == 0 or open_qty != 0 or record.entry_open or record.reservation_active:
            _bad("CLOSED needs fills, zero open quantity and no reservation")
    else:                                                    # REJECTED, EXPIRED_UNFILLED
        if record.entry_legs or record.exit_legs or record.entry_open or record.reservation_active \
                or record.highest_target:
            _bad(f"{state} has fills, an open entry or a reservation")
    if state in (REJECTED, EXPIRED_UNFILLED):
        if not isinstance(record.reason_code, str) or not _F7_CODE.match(record.reason_code):
            _bad(f"{state} needs an F7 reason code")
    elif record.reason_code is not None:
        _bad(f"{state} carries a refusal code")
    if state == CLOSED:
        if record.exit_kind not in EXIT_KINDS:
            _bad("CLOSED needs an exit kind")
        if (record.exit_kind in ("time", "thesis", "admin")) != (record.exit_rule is not None):
            _bad("time, thesis and admin exits, and only they, carry an exit rule")
    elif record.exit_kind is not None or record.exit_rule is not None:
        _bad(f"{state} carries an exit kind")


def new_position(plan: PositionPlan) -> PositionRecord:
    """The entry intent (§B6 PLANNED): no reservation, no fill, the plan's stop in force."""
    validate_plan(plan)
    return PositionRecord(plan=plan, state=PLANNED, reservation_active=False, entry_open=True,
                          entry_legs=(), exit_legs=(), highest_target=0, stop_level=plan.stop,
                          reason_code=None, exit_kind=None, exit_rule=None)


def restore(plan: PositionPlan, *, state: str, reservation_active: bool, entry_open: bool,
            entry_legs: tuple, exit_legs: tuple, highest_target: int, stop_level: Decimal,
            reason_code: str | None, exit_kind: str | None, exit_rule: str | None) -> PositionRecord:
    """Rebuild a record from persisted fields (for example a tracker row and its target fills),
    refusing any combination the machine could not have produced (``invalid_record``)."""
    record = PositionRecord(plan=plan, state=state, reservation_active=reservation_active,
                            entry_open=entry_open, entry_legs=entry_legs, exit_legs=exit_legs,
                            highest_target=highest_target, stop_level=stop_level,
                            reason_code=reason_code, exit_kind=exit_kind, exit_rule=exit_rule)
    check_record(record)
    return record


# ── events ─────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Reserve:
    """Set aside quote cash for this intent (ledger RESERVE; PR §5 step 5)."""
    kind: ClassVar[str] = "reserve"
    amount: Decimal


@dataclass(frozen=True)
class RestEntry:
    """The entry order rests at the planned entry (do-not-chase)."""
    kind: ClassVar[str] = "rest_entry"


@dataclass(frozen=True)
class EntryFill:
    """A full or partial entry fill, priced by the active fill model."""
    kind: ClassVar[str] = "entry_fill"
    qty: Decimal
    price: Decimal


@dataclass(frozen=True)
class EndEntry:
    """The unfilled remainder of a partly filled entry is cancelled; the position stays OPEN."""
    kind: ClassVar[str] = "end_entry"
    rule: str


@dataclass(frozen=True)
class ExpireEntry:
    """The declared entry wait elapsed with nothing filled (F7.entry_wait_expired)."""
    kind: ClassVar[str] = "expire_entry"


@dataclass(frozen=True)
class InvalidatedBeforeFill:
    """The entry observation is at or below max(stop, invalidation) (F7.entry_rejected)."""
    kind: ClassVar[str] = "invalidated_before_fill"


@dataclass(frozen=True)
class BelowExchangeMinimum:
    """Rounding made the order infeasible: quantity below step or notional below minimum."""
    kind: ClassVar[str] = "below_exchange_minimum"


@dataclass(frozen=True)
class RiskRefused:
    """A risk or capacity refusal that ends the intent; ``reason_code`` is its F7 code."""
    kind: ClassVar[str] = "risk_refused"
    reason_code: str


@dataclass(frozen=True)
class TargetFill:
    """Target ``target`` (1..3) reached: sell ``qty`` (zero for a merged tranche) at ``price``.
    ``new_stop`` is the stop in force afterwards; it is None exactly when the leg closes."""
    target: int
    qty: Decimal
    price: Decimal
    new_stop: Decimal | None

    @property
    def kind(self) -> str:
        return f"target_{self.target}"


@dataclass(frozen=True)
class StopUpdate:
    """The declared stop policy moves the stop in force (break-even, trailing; SE-42)."""
    kind: ClassVar[str] = "stop_update"
    new_stop: Decimal


@dataclass(frozen=True)
class StopExit:
    """The stop in force was reached: the remainder exits at the stop fill model's price."""
    kind: ClassVar[str] = "stop_exit"
    qty: Decimal
    price: Decimal


@dataclass(frozen=True)
class InvalidationExit:
    """A closed bar closed at or below the invalidation level before T1."""
    kind: ClassVar[str] = "invalidation_exit"
    qty: Decimal
    price: Decimal


@dataclass(frozen=True)
class TimeExit:
    """A declared holding ceiling or stall rule elapsed (SE-43); ``rule`` is its label."""
    kind: ClassVar[str] = "time_exit"
    qty: Decimal
    price: Decimal
    rule: str


@dataclass(frozen=True)
class ThesisExit:
    """A strategy ``manage`` action closed the position (for example a regime flip)."""
    kind: ClassVar[str] = "thesis_exit"
    qty: Decimal
    price: Decimal
    rule: str


@dataclass(frozen=True)
class AdminExit:
    """An owner or operational close that is not a strategy rule (blacklist, slot ceiling)."""
    kind: ClassVar[str] = "admin_exit"
    qty: Decimal
    price: Decimal
    rule: str


EVENT_TYPES = (Reserve, RestEntry, EntryFill, EndEntry, ExpireEntry, InvalidatedBeforeFill,
               BelowExchangeMinimum, RiskRefused, TargetFill, StopUpdate, StopExit,
               InvalidationExit, TimeExit, ThesisExit, AdminExit)
EVENT_KINDS = ("reserve", "rest_entry", "entry_fill", "end_entry", "expire_entry",
               "invalidated_before_fill", "below_exchange_minimum", "risk_refused", "target_1",
               "target_2", "target_3", "stop_update", "stop_exit", "invalidation_exit",
               "time_exit", "thesis_exit", "admin_exit")
_CLOSING_EXITS = {StopExit: "stop", InvalidationExit: "invalidation", TimeExit: "time",
                  ThesisExit: "thesis", AdminExit: "admin"}


# ── transition table ───────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Rule:
    """One row: ``(from_state, event_kind) -> to_state``. ``to_state_if_flat`` applies when the
    row's exit leg leaves no open quantity. ``source`` is ``SE-B6`` or ``extension``."""
    rule_id: str
    from_state: str
    event_kind: str
    to_state: str
    to_state_if_flat: str | None
    source: str
    note: str


_SAME = "<same>"
_SPEC = (
    # rule id, from states, event kind, to state, to state if flat, source, note
    ("B6-01", (PLANNED,), "invalidated_before_fill", REJECTED, None, "SE-B6",
     "entry price <= max(stop, invalidation): F7.entry_rejected, rule signal_invalidated_before_fill"),
    ("B6-02", (PLANNED,), "entry_fill", OPEN, None, "SE-B6",
     "entry price <= planned entry: fill under the active fill model"),
    ("B6-03", (PLANNED,), "rest_entry", WORKING, None, "SE-B6",
     "entry price > planned entry: rest at planned entry (strategy chase policy)"),
    ("B6-04", (WORKING,), "expire_entry", EXPIRED_UNFILLED, None, "SE-B6",
     "wait > declared entry window: F7.entry_wait_expired"),
    ("B6-05", (PLANNED, WORKING), "below_exchange_minimum", REJECTED, None, "SE-B6",
     "quantity < stepSize or notional < minNotional: F7.min_notional_infeasible"),
    ("B6-06", OPEN_STATES, "stop_exit", CLOSED, None, "SE-B6",
     "price <= effective stop: exit the remainder at the stop fill model"),
    ("B6-07", (OPEN,), "invalidation_exit", CLOSED, None, "SE-B6",
     "closed bar close <= invalidation (pre-T1): exit the remainder at the next observation"),
    ("B6-08", (OPEN,), "target_1", PARTIAL_T1, CLOSED, "SE-B6",
     "price >= T1: sell the T1 fraction; post-T1 stop policy"),
    ("B6-09", (PARTIAL_T1,), "target_2", PARTIAL_T2, CLOSED, "SE-B6",
     "price >= T2: sell the T2 fraction; post-T2 stop policy"),
    ("B6-10", (PARTIAL_T2,), "target_3", CLOSED, CLOSED, "SE-B6",
     "price >= T3: sell the remainder"),
    ("B6-11", OPEN_STATES, "time_exit", CLOSED, None, "SE-B6",
     "hours_open >= declared ceiling or stall rule (SE-43): exit the remainder"),
    ("B6-12", OPEN_STATES, "thesis_exit", CLOSED, None, "SE-B6",
     "strategy manage action (thesis exit): exit the remainder"),
    ("X-01", (PLANNED,), "reserve", PLANNED, None, "extension",
     "RESERVE at intent (WP-IR-06; PR §5 step 5); no §B6 row"),
    ("X-02", (WORKING,), "entry_fill", OPEN, None, "extension",
     "a resting entry order fills; §B6 has no WORKING -> OPEN row"),
    ("X-03", (WORKING,), "invalidated_before_fill", REJECTED, None, "extension",
     "a resting order is invalidated before it fills; §B6 lists this guard for PLANNED only"),
    ("X-04", (OPEN,), "entry_fill", OPEN, None, "extension",
     "a further partial entry fill before any exit (WP-IR-06: ENTRY_FILL per partial fill)"),
    ("X-05", (OPEN,), "end_entry", OPEN, None, "extension",
     "the unfilled entry remainder is cancelled; RELEASE of the unconsumed reservation"),
    ("X-06", (PLANNED, WORKING), "risk_refused", REJECTED, None, "extension",
     "§B6 REJECTED includes 'refused by risk' but the table has no row for it"),
    ("X-07", OPEN_STATES, "stop_update", _SAME, None, "extension",
     "the declared stop policy moves the stop in force (SE-42)"),
    ("X-08", OPEN_STATES, "admin_exit", CLOSED, None, "extension",
     "owner or operational close (blacklist, open-trade ceiling; WP-OD-02); not a strategy rule"),
)


def _build_table() -> tuple:
    rows = []
    for rule_id, sources, kind, to_state, flat, origin, note in _SPEC:
        for state in sources:
            rows.append(Rule(rule_id=rule_id if len(sources) == 1 else f"{rule_id}:{state}",
                             from_state=state, event_kind=kind,
                             to_state=state if to_state == _SAME else to_state,
                             to_state_if_flat=flat, source=origin, note=note))
    keys = [(r.from_state, r.event_kind) for r in rows]
    if len(set(keys)) != len(keys):
        raise RuntimeError("position_state transition table has a duplicate (state, event) pair")
    return tuple(rows)


TRANSITIONS = _build_table()
_LOOKUP = {(rule.from_state, rule.event_kind): rule for rule in TRANSITIONS}


def rule_for(state: str, event_kind: str) -> Rule | None:
    """The table row for ``(state, event_kind)``, or None when the pair is illegal."""
    return _LOOKUP.get((state, event_kind))


@dataclass(frozen=True)
class Transition:
    """One applied row: one DecisionRecord's worth of lifecycle facts (§B6, §E2)."""
    rule_id: str
    source: str
    from_state: str
    to_state: str
    event_kind: str
    ledger_events: tuple
    reason_code: str | None
    event: object


def check_projection_step(before: str | None, after: str | None) -> None:
    """WP-IT-06: refuse a projection step that ``Position.state`` may not take."""
    if (before, after) not in PROJECTION_STEPS:
        raise TransitionRefused("illegal_projection", f"{before!r} -> {after!r}")


# ── the transition function ────────────────────────────────────────────────────────────────

def _event_kind(event) -> str:
    if not isinstance(event, EVENT_TYPES):
        raise TransitionRefused("invalid_event", f"unknown event type {type(event).__name__}")
    if isinstance(event, TargetFill):
        if isinstance(event.target, bool) or event.target not in TARGETS:
            raise TransitionRefused("invalid_event", f"target must be 1, 2 or 3, not {event.target!r}")
    return event.kind


def _qty(record: PositionRecord, value, name: str, *, allow_zero: bool = False) -> Decimal:
    qty = _dec(value, name, non_negative=True)
    if qty == 0 and not allow_zero:
        raise TransitionRefused("invalid_event", f"{name} must be > 0")
    _aligned(qty, record.plan.qty_step, name)
    return qty


def _end_before_fill(record: PositionRecord, to_state: str, code: str):
    ledger = (RELEASE,) if record.reservation_active else ()
    return dataclasses.replace(record, state=to_state, reservation_active=False, entry_open=False,
                               reason_code=code), ledger, code


def _exit(record: PositionRecord, rule: Rule, *, kind: str, qty: Decimal, price: Decimal,
          target: int | None, new_stop, exit_rule: str | None, remainder: bool):
    ledger = []
    if record.entry_open:                   # exits end the entry: release the unconsumed remainder
        if record.reservation_active:
            ledger.append(RELEASE)
    open_qty = record.qty_open
    if qty > open_qty:
        raise TransitionRefused("over_exit", f"{qty} > open quantity {open_qty}")
    if remainder and qty != open_qty:
        raise TransitionRefused("remainder_mismatch", f"{qty} != open quantity {open_qty}")
    with localcontext(_EXACT):
        flat = open_qty - qty == 0
    legs = record.exit_legs
    if qty > 0:
        ledger.append(EXIT_FILL)
        legs = legs + (Leg(kind=kind, qty=qty, price=price, target=target),)
    stop = record.stop_level
    if kind == "target":
        if flat and new_stop is not None:
            raise TransitionRefused("new_stop_unexpected", "the leg closes the position")
        if not flat:
            if new_stop is None:
                raise TransitionRefused("new_stop_required", "the position stays open")
            stop = _dec(new_stop, "new_stop", positive=True)
    to_state = rule.to_state_if_flat if (flat and rule.to_state_if_flat) else rule.to_state
    closed = to_state == CLOSED
    new = dataclasses.replace(
        record, state=to_state, reservation_active=False, entry_open=False, exit_legs=legs,
        highest_target=target if target is not None else record.highest_target, stop_level=stop,
        exit_kind=kind if closed else None, exit_rule=exit_rule if closed else None)
    return new, tuple(ledger), None


def apply(record: PositionRecord, event) -> tuple:
    """Apply one event. Returns ``(new_record, Transition)``; raises ``TransitionRefused``."""
    check_record(record)
    kind = _event_kind(event)
    if record.state in TERMINAL_STATES:
        raise TransitionRefused("terminal_state", f"{record.state} is final; {kind} refused")
    rule = _LOOKUP.get((record.state, kind))
    if rule is None:
        raise TransitionRefused("illegal_transition", f"{kind} from {record.state}")
    plan = record.plan

    if isinstance(event, Reserve):
        _dec(event.amount, "amount", positive=True)
        if record.reservation_active:
            raise TransitionRefused("reservation_exists", plan.intent_id)
        new, ledger, code = dataclasses.replace(record, reservation_active=True), (RESERVE,), None
    elif isinstance(event, RestEntry):
        if not record.reservation_active:
            raise TransitionRefused("reservation_required", "a resting order needs a reservation")
        new, ledger, code = dataclasses.replace(record, state=WORKING), (), None
    elif isinstance(event, EntryFill):
        qty = _qty(record, event.qty, "qty")
        price = _dec(event.price, "price", positive=True)
        if not record.entry_open:
            raise TransitionRefused("entry_not_open", plan.intent_id)
        if not record.reservation_active:
            raise TransitionRefused("reservation_required", "an entry fill needs a reservation")
        remaining = record.entry_remaining
        if qty > remaining:
            raise TransitionRefused("overfill", f"{qty} > unfilled entry quantity {remaining}")
        complete = qty == remaining
        new = dataclasses.replace(record, state=OPEN, entry_open=not complete,
                                  reservation_active=not complete,
                                  entry_legs=record.entry_legs + (Leg("entry", qty, price, None),))
        ledger, code = ((ENTRY_FILL, RELEASE) if complete else (ENTRY_FILL,)), None
    elif isinstance(event, EndEntry):
        _text(event.rule, "rule")
        if not record.entry_open:
            raise TransitionRefused("entry_not_open", plan.intent_id)
        new = dataclasses.replace(record, entry_open=False, reservation_active=False)
        ledger, code = (RELEASE,), None
    elif isinstance(event, ExpireEntry):
        new, ledger, code = _end_before_fill(record, EXPIRED_UNFILLED, CODE_WAIT_EXPIRED)
    elif isinstance(event, InvalidatedBeforeFill):
        new, ledger, code = _end_before_fill(record, REJECTED, CODE_INVALIDATED)
    elif isinstance(event, BelowExchangeMinimum):
        new, ledger, code = _end_before_fill(record, REJECTED, CODE_BELOW_MINIMUM)
    elif isinstance(event, RiskRefused):
        if not isinstance(event.reason_code, str) or not _F7_CODE.match(event.reason_code):
            raise TransitionRefused("invalid_reason_code", repr(event.reason_code))
        new, ledger, code = _end_before_fill(record, REJECTED, event.reason_code)
    elif isinstance(event, TargetFill):
        qty = _qty(record, event.qty, "qty", allow_zero=True)
        price = _dec(event.price, "price", positive=True)
        new, ledger, code = _exit(record, rule, kind="target", qty=qty, price=price,
                                  target=event.target, new_stop=event.new_stop, exit_rule=None,
                                  remainder=event.target == 3)
    elif isinstance(event, StopUpdate):
        stop = _dec(event.new_stop, "new_stop", positive=True)
        if stop == record.stop_level:
            raise TransitionRefused("no_change", f"stop already {stop}")
        new, ledger, code = dataclasses.replace(record, stop_level=stop), (), None
    else:                                    # StopExit, InvalidationExit, TimeExit, ThesisExit, AdminExit
        qty = _qty(record, event.qty, "qty")
        price = _dec(event.price, "price", positive=True)
        label = _text(event.rule, "rule") if hasattr(event, "rule") else None
        new, ledger, code = _exit(record, rule, kind=_CLOSING_EXITS[type(event)], qty=qty,
                                  price=price, target=None, new_stop=None, exit_rule=label,
                                  remainder=True)

    check_record(new)
    check_projection_step(PROJECTION[record.state], PROJECTION[new.state])
    return new, Transition(rule_id=rule.rule_id, source=rule.source, from_state=record.state,
                           to_state=new.state, event_kind=kind, ledger_events=ledger,
                           reason_code=code, event=event)


def apply_all(record: PositionRecord, events: Sequence) -> tuple:
    """Apply events in order; returns ``(final_record, transitions)``. The first refusal raises,
    and the caller's record is unchanged."""
    transitions = []
    for event in events:
        record, transition = apply(record, event)
        transitions.append(transition)
    return record, tuple(transitions)


# ── guards ─────────────────────────────────────────────────────────────────────────────────

def entry_guard(record: PositionRecord, price) -> str:
    """The §B6 PLANNED guards, also applied to a WORKING order on each re-evaluation.

    Returns ENTRY_INVALIDATED, ENTRY_FILLABLE, ENTRY_REST (PLANNED) or ENTRY_WAIT (WORKING). How a
    fillable order fills (price, quantity) is the active fill model's decision, not the guard's."""
    check_record(record)
    if record.state not in PRE_FILL_STATES:
        raise TransitionRefused("illegal_transition", f"entry guard in {record.state}")
    observed = _dec(price, "price", positive=True, reason="invalid_observation")
    plan = record.plan
    if observed <= max(plan.stop, plan.invalidation):
        return ENTRY_INVALIDATED
    if observed <= plan.planned_entry:
        return ENTRY_FILLABLE
    return ENTRY_REST if record.state == PLANNED else ENTRY_WAIT


@dataclass(frozen=True)
class Observation:
    """One price observation: a bar (high, low, close) or a tick (all three equal).

    ``hours_open`` is the elapsed holding time at this observation. ``stop_observation`` is an
    observed price used as the stop reference when it is below the stop (a gap through the
    stop: the reference is min(stop, stop_observation)); None references the stop level."""
    high: Decimal
    low: Decimal
    close: Decimal
    hours_open: Decimal
    stop_observation: Decimal | None


@dataclass(frozen=True)
class TimeRule:
    """A declared holding ceiling or stall rule: exit when ``hours_open >= max_hours`` while the
    highest target reached is in ``at_targets`` (a subset of {0, 1, 2})."""
    label: str
    max_hours: Decimal
    at_targets: frozenset


@dataclass(frozen=True)
class ObservationEvents:
    events: tuple
    peak: Decimal


@dataclass(frozen=True)
class StepResult:
    record: PositionRecord
    transitions: tuple
    peak: Decimal


def _check_observation(obs: Observation) -> None:
    if not isinstance(obs, Observation):
        raise TransitionRefused("invalid_observation", f"expected Observation, not {type(obs).__name__}")
    high = _dec(obs.high, "high", positive=True, reason="invalid_observation")
    low = _dec(obs.low, "low", positive=True, reason="invalid_observation")
    close = _dec(obs.close, "close", positive=True, reason="invalid_observation")
    _dec(obs.hours_open, "hours_open", non_negative=True, reason="invalid_observation")
    if not low <= close <= high:
        raise TransitionRefused("invalid_observation", "requires low <= close <= high")
    if obs.stop_observation is not None:
        _dec(obs.stop_observation, "stop_observation", positive=True, reason="invalid_observation")


def _check_time_rules(time_rules) -> tuple:
    if not isinstance(time_rules, (tuple, list)):
        raise TransitionRefused("invalid_policy", "time_rules must be a sequence (it may be empty)")
    for rule in time_rules:
        if not isinstance(rule, TimeRule):
            raise TransitionRefused("invalid_policy", "time rules must be TimeRule records")
        _text(rule.label, "label", "invalid_policy")
        _dec(rule.max_hours, "max_hours", non_negative=True, reason="invalid_policy")
        if not isinstance(rule.at_targets, frozenset) or not rule.at_targets \
                or not rule.at_targets <= {0, 1, 2}:
            raise TransitionRefused("invalid_policy", "at_targets must be a non-empty subset of {0, 1, 2}")
    return tuple(time_rules)


def _policy_stop(stop_policy: Callable, highest: int, peak: Decimal) -> Decimal:
    return _dec(stop_policy(highest, peak), "stop_policy result", positive=True,
                reason="invalid_policy_output")


def _stop_fill(stop_fill: Callable, stop: Decimal, obs: Observation) -> Decimal:
    reference = stop if obs.stop_observation is None else min(stop, obs.stop_observation)
    return _dec(stop_fill(reference), "stop_fill result", positive=True,
                reason="invalid_policy_output")


def tranche_qty(record: PositionRecord, target: int, open_qty: Decimal) -> Decimal:
    """Quantity sold at ``target``: the remainder when no later fraction is non-zero, otherwise
    ``qty_filled × fraction`` floored to the lot step and capped at the open quantity."""
    fractions = record.plan.exit_fractions
    if all(f == 0 for f in fractions[target:]):
        return open_qty
    step = record.plan.qty_step
    with localcontext(_EXACT):
        qty = ((record.qty_filled * fractions[target - 1]) // step) * step
    return min(qty, open_qty)


def observation_events(record: PositionRecord, obs: Observation, *, peak, stop_policy: Callable,
                       stop_fill: Callable, time_rules: Sequence) -> ObservationEvents:
    """The events one observation implies for an open position, in application order.

    ``peak``: the highest price since entry before this observation. ``stop_policy(highest_target,
    peak) -> Decimal``: the declared stop in force for a target level and peak. ``stop_fill(
    reference) -> Decimal``: the declared stop fill model. ``time_rules``: TimeRule records in
    their declared order (empty when the strategy declares none)."""
    check_record(record)
    if record.state not in OPEN_STATES:
        raise TransitionRefused("illegal_transition", f"observation in {record.state}")
    _check_observation(obs)
    peak = _dec(peak, "peak", positive=True, reason="invalid_observation")
    rules = _check_time_rules(time_rules)
    if not callable(stop_policy) or not callable(stop_fill):
        raise TransitionRefused("invalid_policy", "stop_policy and stop_fill must be callables")
    plan = record.plan
    remaining = record.qty_open
    if obs.low <= record.stop_level:                         # SE-41: the stop in force wins
        return ObservationEvents((StopExit(remaining, _stop_fill(stop_fill, record.stop_level, obs)),),
                                 peak)
    peak = max(peak, obs.high)
    events = []
    highest, stop = record.highest_target, record.stop_level
    for target in range(highest + 1, 4):
        level = plan.targets[target - 1]
        if obs.high < level:
            break
        qty = tranche_qty(record, target, remaining)
        with localcontext(_EXACT):
            remaining = remaining - qty
        if remaining == 0:
            events.append(TargetFill(target, qty, level, None))
            return ObservationEvents(tuple(events), peak)
        stop = _policy_stop(stop_policy, target, peak)
        events.append(TargetFill(target, qty, level, stop))
        highest = target
    after = _policy_stop(stop_policy, highest, peak)
    if after != stop:
        events.append(StopUpdate(after))
        stop = after
    if obs.low <= stop:                                      # post-target stop, same observation
        events.append(StopExit(remaining, _stop_fill(stop_fill, stop, obs)))
        return ObservationEvents(tuple(events), peak)
    for rule in rules:
        if highest in rule.at_targets and obs.hours_open >= rule.max_hours:
            events.append(TimeExit(remaining, obs.close, rule.label))
            break
    return ObservationEvents(tuple(events), peak)


def step(record: PositionRecord, obs: Observation, *, peak, stop_policy: Callable,
         stop_fill: Callable, time_rules: Sequence) -> StepResult:
    """``observation_events`` then ``apply_all``; returns the new record, transitions and peak."""
    result = observation_events(record, obs, peak=peak, stop_policy=stop_policy,
                                stop_fill=stop_fill, time_rules=time_rules)
    new, transitions = apply_all(record, result.events)
    return StepResult(record=new, transitions=transitions, peak=result.peak)


def closed_bar_events(record: PositionRecord, *, bar_close, exit_price) -> tuple:
    """§B6 B6-07: a closed bar at or below the invalidation level exits the remainder, pre-T1
    only. The caller passes only bars that closed after the entry fill (``shared/signal_stop.py``
    ``candle_invalidated``) and the next observation's price as ``exit_price``."""
    check_record(record)
    if record.state not in OPEN_STATES:
        raise TransitionRefused("illegal_transition", f"closed-bar check in {record.state}")
    close = _dec(bar_close, "bar_close", positive=True, reason="invalid_observation")
    price = _dec(exit_price, "exit_price", positive=True, reason="invalid_observation")
    if record.state == OPEN and close <= record.plan.invalidation:
        return (InvalidationExit(record.qty_open, price),)
    return ()
