"""WP-E01 portfolio ledger (PR-C02, R7) — pure, deterministic, Decimal; no production caller.

An event-sourced cash and position ledger for a spot, long-only, unleveraged book held in one
quote asset (docs/design/remediation-design-pack-20261101/PORTFOLIO_RISK_AND_COMPOUNDING.md §3).
Every balance change is one ``LedgerEntry`` derived from one domain event; the state is the
deterministic fold of the entries, and every transition re-checks the ledger invariants before it
is committed. A refused event raises ``LedgerError`` and leaves the ledger unchanged.

Balances (quote asset, exact ``Decimal`` under an explicit local context):

* ``cash``            total quote held, including the part set aside for working entry intents;
* ``reserved``        the unconsumed remainder of active reservations (PR-C11 / PR-12);
* ``available``       ``cash − reserved``: the only capital for new trades. Marks never move it;
* ``committed_cost``  the open cost basis, Σ qty × entry price, fees excluded;
* ``realized_gross``  Σ exit proceeds − released cost basis, before any fee or cost;
* ``fees`` / ``costs`` exchange fees and explicit modeled costs, booked per leg and kept apart;
* ``realized_net``    ``realized_gross − fees − costs``.

Identity checked after every transition (PR-I1, with explicit costs kept beside fees)::

    cash + committed_cost = net_contributions + realized_gross − fees − costs

Mark-to-market equity is ``cash + Σ qty_open × mark`` = ``equity_cost + unrealized``; it is
UNKNOWN (``None``) while any open position has no mark.

Integration boundary (not wired; owner gates):

* no service imports this module; the shadow writer is WP-E04 (gated on PR-OD1, PR-OD2);
* the fee asset is the ledger's quote asset only, until PR-OD8 is decided;
* the helpers at the end never choose a value: the gain settlement rule (PR-OD9), the de-risking
  ladders (PR-OD20, PR-OD21) and the mark staleness bound (PR-OD4) are required inputs;
* compounding caps C-1..C-3, sizing methods M1..M4, constraint stages and step rounding are the
  ``SizingDecision`` engine (WP-G22 / PR-C08); the daily UTC series is WP-E05 (PR-OD6, WP3).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import (ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, Inexact,
                     InvalidOperation, Overflow, localcontext)
from typing import Iterable, Mapping, Sequence

LEDGER_VERSION = "wp2-portfolio-ledger-v1"
# WP-IR-07: the three cost-model identifiers; one ledger books exactly one model (§3.1 item 5).
COST_MODEL_IDS = ("legacy_tracker_v1", "research_baseline_v1", "research_stress_v1")
GENESIS_HASH = "0" * 64
MARK_STALE_CODE = "F7.mark_stale"
EVENT_CONFLICT_CODE = "F7.ledger_event_conflict"

# Every booking is an addition or a multiplication of finite decimals, so it is exact at this
# precision. Inexact is trapped: if precision were ever exceeded the event is refused, never
# silently rounded.
_EXACT = Context(prec=60, rounding=ROUND_HALF_EVEN, Emin=-999_999, Emax=999_999,
                 traps=[InvalidOperation, DivisionByZero, Overflow, Inexact])
# Division (pro-rata cost release on a partial exit, display prices) rounds; the booked result
# is quantized to the ledger's declared money quantum.
_DIVIDE = Context(prec=60, rounding=ROUND_HALF_EVEN, Emin=-999_999, Emax=999_999,
                  traps=[InvalidOperation, DivisionByZero, Overflow])
ZERO = Decimal(0)
ONE = Decimal(1)


class LedgerError(ValueError):
    """An event or input the ledger refuses. ``reason`` is a stable machine-readable code."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class LedgerEventConflict(LedgerError):
    """PR-I7: a repeated ``event_id`` with a different payload (a technical halt reason)."""
    f7_code = EVENT_CONFLICT_CODE


class LedgerInvariantViolation(LedgerError):
    """A PR-I* invariant does not hold; the ledger is not reconciled."""


# ── validation ─────────────────────────────────────────────────────────────────────────────

def _dec(value, name: str, *, positive: bool = False, non_negative: bool = False) -> Decimal:
    """A finite Decimal from a Decimal or int. Floats are refused: they are not exact."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise LedgerError("invalid_event", f"{name} must be Decimal or int, not {type(value).__name__}")
    number = Decimal(value)
    if not number.is_finite():
        raise LedgerError("invalid_event", f"{name} is not finite")
    if positive and number <= 0:
        raise LedgerError("invalid_event", f"{name} must be > 0")
    if non_negative and number < 0:
        raise LedgerError("invalid_event", f"{name} must be >= 0")
    return number


def _utc(value, name: str) -> datetime:
    """PR-I14: a tz-aware time, normalized to UTC. Naive times are refused."""
    if not isinstance(value, datetime):
        raise LedgerError("invalid_time", f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise LedgerError("naive_time", name)
    return value.astimezone(timezone.utc)


def _ident(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LedgerError("invalid_event", f"{name} must be a non-empty string")
    return value


def _sum(values: Iterable[Decimal]) -> Decimal:
    with localcontext(_EXACT):
        total = ZERO
        for value in values:
            total += value
        return total


def _canon(value):
    """Canonical JSON-ready form, so equal values hash equally (Decimal('5.0') == 5)."""
    if isinstance(value, Decimal):
        if value == 0:
            return "0"
        with localcontext(_EXACT):
            return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Mapping):
        return {str(k): _canon(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    if dataclasses.is_dataclass(value):
        return {f.name: _canon(getattr(value, f.name)) for f in dataclasses.fields(value)}
    return value


def _sha(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()


# ── events ─────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Deposit:
    """Explicit contribution; the first event of a ledger is its genesis deposit."""
    event_id: str
    as_of: datetime
    amount: Decimal


@dataclass(frozen=True)
class Reserve:
    """Set aside ``amount`` of available cash for one working entry intent."""
    event_id: str
    as_of: datetime
    intent_id: str
    symbol: str
    strategy_id: str
    amount: Decimal


@dataclass(frozen=True)
class ReleaseReservation:
    """End an intent's reservation (reject, cancel, expiry or done): release exactly the remainder."""
    event_id: str
    as_of: datetime
    intent_id: str


@dataclass(frozen=True)
class EntryFill:
    """One (possibly partial) entry fill against an active reservation; position id = intent id."""
    event_id: str
    as_of: datetime
    intent_id: str
    qty: Decimal
    price: Decimal
    fee: Decimal
    fee_asset: str
    cost: Decimal
    ref_price: Decimal | None = None     # attribution only (PR-I11); never booked


@dataclass(frozen=True)
class ExitFill:
    """One exit leg; the leg that brings ``qty_open`` to zero closes the position."""
    event_id: str
    as_of: datetime
    position_id: str
    leg_id: str
    qty: Decimal
    price: Decimal
    fee: Decimal
    fee_asset: str
    cost: Decimal
    ref_price: Decimal | None = None     # attribution only (PR-I11); never booked


@dataclass(frozen=True)
class Mark:
    """A mark-to-market price for one symbol at ``as_of``. Moves no balance (PR-I9)."""
    event_id: str
    as_of: datetime
    symbol: str
    price: Decimal
    source: str


EVENT_TYPES = (Deposit, Reserve, ReleaseReservation, EntryFill, ExitFill, Mark)


def _normalize(event, quote_asset: str):
    if not isinstance(event, EVENT_TYPES):
        raise LedgerError("invalid_event", f"unknown event type {type(event).__name__}")
    _ident(event.event_id, "event_id")
    changes = {"as_of": _utc(event.as_of, "as_of")}
    if isinstance(event, Deposit):
        changes["amount"] = _dec(event.amount, "amount", positive=True)
    elif isinstance(event, Reserve):
        for name in ("intent_id", "symbol", "strategy_id"):
            _ident(getattr(event, name), name)
        changes["amount"] = _dec(event.amount, "amount", positive=True)
    elif isinstance(event, ReleaseReservation):
        _ident(event.intent_id, "intent_id")
    elif isinstance(event, (EntryFill, ExitFill)):
        _ident(event.intent_id if isinstance(event, EntryFill) else event.position_id, "id")
        if isinstance(event, ExitFill):
            _ident(event.leg_id, "leg_id")
        changes["qty"] = _dec(event.qty, "qty", positive=True)
        changes["price"] = _dec(event.price, "price", positive=True)
        changes["fee"] = _dec(event.fee, "fee", non_negative=True)
        changes["cost"] = _dec(event.cost, "cost", non_negative=True)
        if event.fee_asset != quote_asset:          # PR-OD8: quote-asset fees only until decided
            raise LedgerError("fee_asset_unsupported", f"{event.fee_asset!r} != {quote_asset!r}")
        if event.ref_price is not None:
            changes["ref_price"] = _dec(event.ref_price, "ref_price", positive=True)
    elif isinstance(event, Mark):
        _ident(event.symbol, "symbol")
        _ident(event.source, "source")
        changes["price"] = _dec(event.price, "price", positive=True)
    return dataclasses.replace(event, **changes)


def event_fingerprint(event) -> str:
    """Hash of the normalized payload, used for PR-I7 idempotency."""
    return _sha({"type": type(event).__name__, "payload": _canon(event)})


# ── state records ──────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Reservation:
    intent_id: str
    symbol: str
    strategy_id: str
    amount: Decimal
    consumed: Decimal
    released: Decimal
    remaining: Decimal
    active: bool


@dataclass(frozen=True)
class EntryLeg:
    event_id: str
    qty: Decimal
    price: Decimal
    notional: Decimal
    fee: Decimal
    cost: Decimal
    consumed_reservation: Decimal
    slippage_attribution: Decimal


@dataclass(frozen=True)
class ExitLeg:
    leg_id: str
    event_id: str
    qty: Decimal
    price: Decimal
    proceeds: Decimal
    released_cost: Decimal
    gross: Decimal
    fee: Decimal
    cost: Decimal
    slippage_attribution: Decimal


@dataclass(frozen=True)
class Position:
    position_id: str
    symbol: str
    strategy_id: str
    opened_at: datetime
    entries: tuple
    exits: tuple
    qty_open: Decimal
    cost_basis: Decimal
    state: str                      # "open" -> "partially_exited" -> "closed" (WP-IR-06 projection)
    closed_at: datetime | None
    close_index: int | None

    @property
    def qty_entered(self) -> Decimal:
        return _sum(leg.qty for leg in self.entries)

    @property
    def qty_exited(self) -> Decimal:
        return _sum(leg.qty for leg in self.exits)

    @property
    def realized_gross(self) -> Decimal:
        return _sum(leg.gross for leg in self.exits)

    @property
    def fees(self) -> Decimal:
        return _sum([leg.fee for leg in self.entries] + [leg.fee for leg in self.exits])

    @property
    def costs(self) -> Decimal:
        return _sum([leg.cost for leg in self.entries] + [leg.cost for leg in self.exits])

    @property
    def realized_net(self) -> Decimal:
        with localcontext(_EXACT):
            return self.realized_gross - self.fees - self.costs

    @property
    def avg_entry_price(self) -> Decimal | None:
        """Display only; accounting uses ``cost_basis``."""
        if self.qty_open == 0:
            return None
        with localcontext(_DIVIDE):
            return self.cost_basis / self.qty_open


@dataclass(frozen=True)
class MarkRecord:
    price: Decimal
    as_of: datetime
    source: str
    event_id: str


@dataclass(frozen=True)
class LedgerState:
    sequence: int
    as_of: datetime | None
    net_contributions: Decimal
    cash: Decimal
    reserved: Decimal
    committed_cost: Decimal
    realized_gross: Decimal
    fees: Decimal
    costs: Decimal
    reservations: Mapping[str, Reservation]
    positions: Mapping[str, Position]
    marks: Mapping[str, MarkRecord]
    close_count: int

    @property
    def available(self) -> Decimal:
        with localcontext(_EXACT):
            return self.cash - self.reserved

    @property
    def realized_net(self) -> Decimal:
        with localcontext(_EXACT):
            return self.realized_gross - self.fees - self.costs

    @property
    def equity_cost(self) -> Decimal:
        with localcontext(_EXACT):
            return self.cash + self.committed_cost


EMPTY_STATE = LedgerState(sequence=0, as_of=None, net_contributions=ZERO, cash=ZERO, reserved=ZERO,
                          committed_cost=ZERO, realized_gross=ZERO, fees=ZERO, costs=ZERO,
                          reservations={}, positions={}, marks={}, close_count=0)


def state_digest(state: LedgerState) -> str:
    """Canonical hash of the full state (display-only derived values excluded)."""
    return _sha(_canon(state))


def _violation(invariant: str, detail: str):
    raise LedgerInvariantViolation("invariant_violation", f"{invariant}: {detail}")


def check_invariants(state: LedgerState) -> None:
    """Raise ``LedgerInvariantViolation`` unless PR-I1 to PR-I6 and the time rule hold exactly."""
    with localcontext(_EXACT):
        if state.cash + state.committed_cost != (state.net_contributions + state.realized_gross
                                                 - state.fees - state.costs):
            _violation("PR-I1", "cash + committed_cost != contributions + realized_gross - fees - costs")
        for name in ("cash", "reserved", "committed_cost", "fees", "costs", "net_contributions"):
            if getattr(state, name) < 0:
                _violation("PR-I2", f"{name} < 0")
        if state.cash - state.reserved < 0:
            _violation("PR-I2", "available (cash - reserved) < 0")
        active = ZERO
        for intent_id, res in state.reservations.items():
            if min(res.remaining, res.consumed, res.released) < 0:
                _violation("PR-I3", f"negative reservation component for {intent_id}")
            if res.consumed + res.released + res.remaining != res.amount:
                _violation("PR-I3", f"reservation {intent_id} does not conserve its amount")
            if res.active:
                if res.released != 0:
                    _violation("PR-I3", f"active reservation {intent_id} has a release")
                active += res.remaining
            elif res.remaining != 0:
                _violation("PR-I3", f"ended reservation {intent_id} still holds {res.remaining}")
        if active != state.reserved:
            _violation("PR-I3", "reserved != sum of active reservations")
        committed = ZERO
        gross = fees = costs = ZERO
        for pid, pos in state.positions.items():
            if pos.qty_open < 0 or pos.cost_basis < 0:
                _violation("PR-I2", f"position {pid} has negative quantity or cost")
            if pos.qty_entered - pos.qty_exited != pos.qty_open:
                _violation("PR-I4", f"position {pid} quantity not conserved")
            if _sum(leg.notional for leg in pos.entries) - _sum(
                    leg.released_cost for leg in pos.exits) != pos.cost_basis:
                _violation("PR-I5", f"position {pid} cost basis not conserved")
            if (pos.qty_open == 0) != (pos.state == "closed"):
                _violation("PR-I4", f"position {pid} state {pos.state!r} with qty_open {pos.qty_open}")
            if len({leg.leg_id for leg in pos.exits}) != len(pos.exits):
                _violation("PR-I6", f"position {pid} has a double-booked exit leg")
            committed += pos.cost_basis
            gross += pos.realized_gross
            fees += pos.fees
            costs += pos.costs
        if committed != state.committed_cost:
            _violation("PR-I5", "committed_cost != sum of position cost bases")
        if (gross, fees, costs) != (state.realized_gross, state.fees, state.costs):
            _violation("PR-I6", "realized gross, fees or costs != sum of position legs")
    if state.as_of is not None and (state.as_of.tzinfo is None
                                    or state.as_of.utcoffset() != timedelta(0)):
        _violation("PR-I14", "state time is not UTC")


# ── transitions ────────────────────────────────────────────────────────────────────────────

def _adverse(qty: Decimal, price: Decimal, ref: Decimal | None, *, buying: bool) -> Decimal:
    if ref is None:
        return ZERO
    with localcontext(_EXACT):
        gap = (price - ref) if buying else (ref - price)
        return qty * gap if gap > 0 else ZERO


def _transition(state: LedgerState, ev, money_quantum: Decimal) -> LedgerState:
    if state.sequence == 0 and not isinstance(ev, Deposit):
        raise LedgerError("genesis_required", "the first event must be a Deposit")
    reservations = dict(state.reservations)
    positions = dict(state.positions)
    marks = dict(state.marks)
    with localcontext(_EXACT):
        if isinstance(ev, Deposit):
            return dataclasses.replace(state, net_contributions=state.net_contributions + ev.amount,
                                       cash=state.cash + ev.amount)

        if isinstance(ev, Reserve):
            if ev.intent_id in reservations or ev.intent_id in positions:
                raise LedgerError("intent_exists", ev.intent_id)
            if state.available < ev.amount:
                raise LedgerError("insufficient_available", f"{ev.amount} > {state.available}")
            reservations[ev.intent_id] = Reservation(
                intent_id=ev.intent_id, symbol=ev.symbol, strategy_id=ev.strategy_id,
                amount=ev.amount, consumed=ZERO, released=ZERO, remaining=ev.amount, active=True)
            return dataclasses.replace(state, reserved=state.reserved + ev.amount,
                                       reservations=reservations)

        if isinstance(ev, ReleaseReservation):
            res = reservations.get(ev.intent_id)
            if res is None:
                raise LedgerError("unknown_intent", ev.intent_id)
            if not res.active:
                raise LedgerError("reservation_inactive", ev.intent_id)
            reservations[ev.intent_id] = dataclasses.replace(
                res, released=res.remaining, remaining=ZERO, active=False)
            return dataclasses.replace(state, reserved=state.reserved - res.remaining,
                                       reservations=reservations)

        if isinstance(ev, EntryFill):
            res = reservations.get(ev.intent_id)
            if res is None:
                raise LedgerError("unknown_intent", ev.intent_id)
            if not res.active:
                raise LedgerError("reservation_inactive", ev.intent_id)
            pos = positions.get(ev.intent_id)
            if pos is not None and (pos.state != "open" or pos.exits):
                raise LedgerError("position_not_accepting_entries", ev.intent_id)
            notional = ev.qty * ev.price
            outlay = notional + ev.fee + ev.cost
            consumed = min(res.remaining, outlay)
            cash = state.cash - outlay
            reserved = state.reserved - consumed
            if cash - reserved < 0:
                raise LedgerError("insufficient_available", f"entry outlay {outlay} exceeds cash")
            leg = EntryLeg(event_id=ev.event_id, qty=ev.qty, price=ev.price, notional=notional,
                           fee=ev.fee, cost=ev.cost, consumed_reservation=consumed,
                           slippage_attribution=_adverse(ev.qty, ev.price, ev.ref_price, buying=True))
            if pos is None:
                pos = Position(position_id=ev.intent_id, symbol=res.symbol,
                               strategy_id=res.strategy_id, opened_at=ev.as_of, entries=(leg,),
                               exits=(), qty_open=ev.qty, cost_basis=notional, state="open",
                               closed_at=None, close_index=None)
            else:
                pos = dataclasses.replace(pos, entries=pos.entries + (leg,),
                                          qty_open=pos.qty_open + ev.qty,
                                          cost_basis=pos.cost_basis + notional)
            positions[ev.intent_id] = pos
            reservations[ev.intent_id] = dataclasses.replace(
                res, consumed=res.consumed + consumed, remaining=res.remaining - consumed)
            return dataclasses.replace(
                state, cash=cash, reserved=reserved, committed_cost=state.committed_cost + notional,
                fees=state.fees + ev.fee, costs=state.costs + ev.cost,
                reservations=reservations, positions=positions)

        if isinstance(ev, ExitFill):
            pos = positions.get(ev.position_id)
            if pos is None:
                raise LedgerError("unknown_position", ev.position_id)
            if pos.state == "closed":
                raise LedgerError("position_closed", ev.position_id)
            if any(leg.leg_id == ev.leg_id for leg in pos.exits):
                raise LedgerError("duplicate_leg", f"{ev.position_id}/{ev.leg_id}")
            if ev.qty > pos.qty_open:
                raise LedgerError("over_exit", f"{ev.qty} > qty_open {pos.qty_open}")
            if ev.qty == pos.qty_open:
                released = pos.cost_basis                     # the final leg releases the remainder
            else:
                with localcontext(_DIVIDE):
                    released = (pos.cost_basis * ev.qty / pos.qty_open).quantize(money_quantum)
                released = min(max(released, ZERO), pos.cost_basis)
            proceeds = ev.qty * ev.price
            gross = proceeds - released
            cash = state.cash + proceeds - ev.fee - ev.cost
            if cash < 0 or cash - state.reserved < 0:
                raise LedgerError("insufficient_available", "exit fee and cost exceed cash")
            leg = ExitLeg(leg_id=ev.leg_id, event_id=ev.event_id, qty=ev.qty, price=ev.price,
                          proceeds=proceeds, released_cost=released, gross=gross, fee=ev.fee,
                          cost=ev.cost,
                          slippage_attribution=_adverse(ev.qty, ev.price, ev.ref_price, buying=False))
            qty_open = pos.qty_open - ev.qty
            close_count = state.close_count
            if qty_open == 0:
                close_count += 1
                pos = dataclasses.replace(pos, exits=pos.exits + (leg,), qty_open=qty_open,
                                          cost_basis=pos.cost_basis - released, state="closed",
                                          closed_at=ev.as_of, close_index=close_count)
            else:
                pos = dataclasses.replace(pos, exits=pos.exits + (leg,), qty_open=qty_open,
                                          cost_basis=pos.cost_basis - released,
                                          state="partially_exited")
            positions[ev.position_id] = pos
            return dataclasses.replace(
                state, cash=cash, committed_cost=state.committed_cost - released,
                realized_gross=state.realized_gross + gross, fees=state.fees + ev.fee,
                costs=state.costs + ev.cost, positions=positions, close_count=close_count)

        marks[ev.symbol] = MarkRecord(price=ev.price, as_of=ev.as_of, source=ev.source,
                                      event_id=ev.event_id)
        return dataclasses.replace(state, marks=marks)


# ── snapshots ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PositionView:
    position_id: str
    symbol: str
    strategy_id: str
    state: str
    opened_at: datetime
    closed_at: datetime | None
    close_index: int | None
    qty_open: Decimal
    cost_basis: Decimal
    avg_entry_price: Decimal | None
    mark_price: Decimal | None
    mark_as_of: datetime | None
    market_value: Decimal | None
    unrealized: Decimal | None
    realized_gross: Decimal
    fees: Decimal
    costs: Decimal
    realized_net: Decimal
    slippage_attribution: Decimal


@dataclass(frozen=True)
class ExposureBucket:
    """Absolute exposure amounts. Ratios need a denominator, which is PR-OD10 and not chosen."""
    committed_cost: Decimal
    market_value: Decimal | None
    reserved: Decimal
    open_positions: int


@dataclass(frozen=True)
class LedgerSnapshot:
    sequence: int
    as_of: datetime | None
    quote_asset: str
    cost_model_id: str
    net_contributions: Decimal
    cash: Decimal
    reserved: Decimal
    available: Decimal
    committed_cost: Decimal
    realized_gross: Decimal
    fees: Decimal
    costs: Decimal
    realized_net: Decimal
    equity_cost: Decimal
    unrealized: Decimal | None
    equity_mtm: Decimal | None
    unmarked_symbols: tuple
    gross_exposure: ExposureBucket
    by_symbol: Mapping[str, ExposureBucket]
    by_strategy: Mapping[str, ExposureBucket]
    positions: tuple


def _bucket(views: Sequence[PositionView], reserved: Decimal) -> ExposureBucket:
    values = [v.market_value for v in views]
    return ExposureBucket(committed_cost=_sum(v.cost_basis for v in views),
                          market_value=None if any(x is None for x in values) else _sum(values),
                          reserved=reserved, open_positions=len(views))


def build_snapshot(state: LedgerState, *, quote_asset: str, cost_model_id: str,
                   usable_marks: Mapping[str, MarkRecord] | None = None) -> LedgerSnapshot:
    """Derive balances, P&L and exposure from a state. ``usable_marks`` defaults to the latest
    marks; ``PortfolioLedger.valuation`` passes only the fresh ones."""
    marks = state.marks if usable_marks is None else usable_marks
    views = []
    with localcontext(_EXACT):
        for pid in sorted(state.positions):
            pos = state.positions[pid]
            mark = marks.get(pos.symbol)
            if pos.qty_open == 0:
                value, unreal = ZERO, ZERO
            elif mark is None:
                value, unreal = None, None
            else:
                value = pos.qty_open * mark.price
                unreal = value - pos.cost_basis
            views.append(PositionView(
                position_id=pid, symbol=pos.symbol, strategy_id=pos.strategy_id, state=pos.state,
                opened_at=pos.opened_at, closed_at=pos.closed_at, close_index=pos.close_index,
                qty_open=pos.qty_open, cost_basis=pos.cost_basis,
                avg_entry_price=pos.avg_entry_price,
                mark_price=None if mark is None else mark.price,
                mark_as_of=None if mark is None else mark.as_of,
                market_value=value, unrealized=unreal, realized_gross=pos.realized_gross,
                fees=pos.fees, costs=pos.costs, realized_net=pos.realized_net,
                slippage_attribution=_sum([leg.slippage_attribution for leg in pos.entries]
                                          + [leg.slippage_attribution for leg in pos.exits])))
        open_views = [v for v in views if v.qty_open > 0]
        unmarked = tuple(sorted({v.symbol for v in open_views if v.market_value is None}))
        unrealized = None if unmarked else _sum(v.unrealized for v in open_views)
        equity_mtm = None if unmarked else state.cash + _sum(v.market_value for v in open_views)
        if equity_mtm is not None and equity_mtm != state.equity_cost + unrealized:
            _violation("equity identity", "equity_mtm != equity_cost + unrealized")
        active = [r for r in state.reservations.values() if r.active]

        def grouped(key):
            names = sorted({getattr(v, key) for v in open_views} | {getattr(r, key) for r in active})
            return {name: _bucket([v for v in open_views if getattr(v, key) == name],
                                  _sum(r.remaining for r in active if getattr(r, key) == name))
                    for name in names}

        return LedgerSnapshot(
            sequence=state.sequence, as_of=state.as_of, quote_asset=quote_asset,
            cost_model_id=cost_model_id, net_contributions=state.net_contributions,
            cash=state.cash, reserved=state.reserved, available=state.available,
            committed_cost=state.committed_cost, realized_gross=state.realized_gross,
            fees=state.fees, costs=state.costs, realized_net=state.realized_net,
            equity_cost=state.equity_cost, unrealized=unrealized, equity_mtm=equity_mtm,
            unmarked_symbols=unmarked, gross_exposure=_bucket(open_views, state.reserved),
            by_symbol=grouped("symbol"), by_strategy=grouped("strategy_id"),
            positions=tuple(views))


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: str
    ledger_id: str
    sequence: int
    event_id: str
    event_type: str
    as_of: datetime
    cost_model_id: str
    event: object                  # the normalized event (the replay input)
    deltas: Mapping[str, Decimal]
    prev_state_hash: str
    state_hash: str
    snapshot: LedgerSnapshot


@dataclass(frozen=True)
class Valuation:
    """Point-in-time valuation under an explicit staleness bound (PR-OD4 supplies the bound)."""
    status: str                    # "FRESH" or "UNKNOWN"
    reason: str | None             # MARK_STALE_CODE when UNKNOWN
    stale_symbols: tuple
    now: datetime
    snapshot: LedgerSnapshot


_BALANCES = ("net_contributions", "cash", "reserved", "committed_cost", "realized_gross",
             "fees", "costs")


class PortfolioLedger:
    """Append-only, event-sourced ledger. ``apply`` is the only way to change it."""

    def __init__(self, *, ledger_id: str, quote_asset: str, cost_model_id: str,
                 money_quantum: Decimal):
        self.ledger_id = _ident(ledger_id, "ledger_id")
        self.quote_asset = _ident(quote_asset, "quote_asset")
        if cost_model_id not in COST_MODEL_IDS:
            raise LedgerError("cost_model_unknown", repr(cost_model_id))
        self.cost_model_id = cost_model_id
        self.money_quantum = _dec(money_quantum, "money_quantum", positive=True)
        self._state = EMPTY_STATE
        self._entries: list[LedgerEntry] = []
        self._seen: dict[str, tuple[int, str]] = {}
        self._duplicates: list[str] = []

    @property
    def state(self) -> LedgerState:
        return self._state

    @property
    def entries(self) -> tuple:
        return tuple(self._entries)

    @property
    def duplicate_log(self) -> tuple:
        """Event ids re-applied with an identical payload (recorded no-ops, PR-I7)."""
        return tuple(self._duplicates)

    @property
    def state_hash(self) -> str:
        return self._entries[-1].state_hash if self._entries else GENESIS_HASH

    def snapshot(self) -> LedgerSnapshot:
        return build_snapshot(self._state, quote_asset=self.quote_asset,
                              cost_model_id=self.cost_model_id)

    def apply(self, event) -> LedgerEntry:
        ev = _normalize(event, self.quote_asset)
        fingerprint = event_fingerprint(ev)
        seen = self._seen.get(ev.event_id)
        if seen is not None:
            sequence, prior = seen
            if prior != fingerprint:
                raise LedgerEventConflict("ledger_event_conflict", ev.event_id)
            self._duplicates.append(ev.event_id)
            return self._entries[sequence - 1]
        before = self._state
        if before.as_of is not None and ev.as_of < before.as_of:
            raise LedgerError("time_regression", f"{ev.as_of.isoformat()} < {before.as_of.isoformat()}")
        after = dataclasses.replace(_transition(before, ev, self.money_quantum),
                                    sequence=before.sequence + 1, as_of=ev.as_of)
        check_invariants(after)
        with localcontext(_EXACT):
            deltas = {name: getattr(after, name) - getattr(before, name) for name in _BALANCES}
        if isinstance(ev, Mark) and any(value != 0 for value in deltas.values()):
            _violation("PR-I9", "a mark moved a balance")
        snapshot = build_snapshot(after, quote_asset=self.quote_asset,
                                  cost_model_id=self.cost_model_id)
        prev_hash = self.state_hash
        state_hash = _sha({"prev": prev_hash, "event": fingerprint, "state": state_digest(after),
                           "ledger": [self.ledger_id, self.cost_model_id, self.quote_asset,
                                      LEDGER_VERSION]})
        entry = LedgerEntry(
            entry_id=f"{self.ledger_id}:{after.sequence}", ledger_id=self.ledger_id,
            sequence=after.sequence, event_id=ev.event_id, event_type=type(ev).__name__,
            as_of=ev.as_of, cost_model_id=self.cost_model_id, event=ev, deltas=deltas,
            prev_state_hash=prev_hash, state_hash=state_hash, snapshot=snapshot)
        self._state = after
        self._entries.append(entry)
        self._seen[ev.event_id] = (after.sequence, fingerprint)
        return entry

    def apply_all(self, events: Iterable) -> list:
        return [self.apply(event) for event in events]

    def valuation(self, *, now: datetime, mark_max_age: timedelta) -> Valuation:
        """E_mtm and unrealized P&L only from marks with ``now − as_of ≤ mark_max_age``. Any open
        position with a stale or missing mark makes the valuation UNKNOWN (``F7.mark_stale``)."""
        now = _utc(now, "now")
        if not isinstance(mark_max_age, timedelta) or mark_max_age < timedelta(0):
            raise LedgerError("invalid_input", "mark_max_age must be a non-negative timedelta")
        if self._state.as_of is not None and now < self._state.as_of:
            raise LedgerError("time_regression", "valuation time precedes the ledger")
        fresh = {sym: m for sym, m in self._state.marks.items() if now - m.as_of <= mark_max_age}
        snap = build_snapshot(self._state, quote_asset=self.quote_asset,
                              cost_model_id=self.cost_model_id, usable_marks=fresh)
        stale = snap.unmarked_symbols
        return Valuation(status="UNKNOWN" if stale else "FRESH",
                         reason=MARK_STALE_CODE if stale else None,
                         stale_symbols=stale, now=now, snapshot=snap)


def replay(events: Iterable, *, ledger_id: str, quote_asset: str, cost_model_id: str,
           money_quantum: Decimal) -> PortfolioLedger:
    ledger = PortfolioLedger(ledger_id=ledger_id, quote_asset=quote_asset,
                             cost_model_id=cost_model_id, money_quantum=money_quantum)
    ledger.apply_all(events)
    return ledger


def verify_chain(entries: Sequence[LedgerEntry]) -> None:
    """PR-I8 / PR-I12 / PR-I14: gap-free sequence, linked hashes, non-decreasing UTC time."""
    prev_hash, prev_time = GENESIS_HASH, None
    for index, entry in enumerate(entries, start=1):
        if entry.sequence != index:
            _violation("PR-I8", f"sequence gap at {index}")
        if entry.prev_state_hash != prev_hash:
            _violation("PR-I8", f"hash chain broken at {index}")
        if entry.as_of.utcoffset() != timedelta(0) or (prev_time is not None
                                                       and entry.as_of < prev_time):
            _violation("PR-I14", f"time order broken at {index}")
        prev_hash, prev_time = entry.state_hash, entry.as_of


def replay_entries(entries: Sequence[LedgerEntry], *, money_quantum: Decimal,
                   quote_asset: str) -> PortfolioLedger:
    """Fold an entry log from empty; every recomputed hash must equal the logged one (PR-I8)."""
    verify_chain(entries)
    if not entries:
        raise LedgerError("invalid_input", "empty entry log")
    ledger = PortfolioLedger(ledger_id=entries[0].ledger_id, quote_asset=quote_asset,
                             cost_model_id=entries[0].cost_model_id, money_quantum=money_quantum)
    for entry in entries:
        rebuilt = ledger.apply(entry.event)
        if rebuilt.state_hash != entry.state_hash:
            _violation("PR-I8", f"replay hash differs at sequence {entry.sequence}")
    return ledger


# ── sizing inputs: realized-net compounding base and de-risking ladders ───────────────────

SETTLEMENT_KINDS = ("at_close", "next_utc_day", "next_utc_week", "after_n_closes")


@dataclass(frozen=True)
class SettlementRule:
    """When a closed position's realized net **gain** enters the sizing base (PR-OD9 S1–S4).
    Both fields are required: ``after_closes`` is an int for ``after_n_closes``, else None."""
    kind: str
    after_closes: int | None


@dataclass(frozen=True)
class SizingBase:
    base: Decimal
    starting_capital: Decimal
    settled_net: Decimal               # net of settled, reconciled closes (gains and losses)
    immediate_losses: Decimal          # unsettled realized losses, counted at once (<= 0)
    excluded_gains: Decimal            # unsettled realized gains, excluded (>= 0)
    floored_at_zero: bool
    settled_position_ids: tuple
    pending_position_ids: tuple
    as_of: datetime
    rule: SettlementRule


def _validate_rule(rule: SettlementRule) -> None:
    if not isinstance(rule, SettlementRule) or rule.kind not in SETTLEMENT_KINDS:
        raise LedgerError("invalid_input", f"settlement kind must be one of {SETTLEMENT_KINDS}")
    if rule.kind == "after_n_closes":
        if isinstance(rule.after_closes, bool) or not isinstance(rule.after_closes, int) \
                or rule.after_closes < 1:
            raise LedgerError("invalid_input", "after_n_closes needs an int after_closes >= 1")
    elif rule.after_closes is not None:
        raise LedgerError("invalid_input", f"after_closes must be None for {rule.kind}")


def _utc_day_start(moment: datetime) -> datetime:
    return datetime(moment.year, moment.month, moment.day, tzinfo=timezone.utc)


def settlement_point(rule: SettlementRule, closed_at: datetime) -> datetime | None:
    """The UTC time at which a close settles, or None for the count-based rule."""
    _validate_rule(rule)
    closed_at = _utc(closed_at, "closed_at")
    if rule.kind == "at_close":
        return closed_at
    day = _utc_day_start(closed_at)
    if rule.kind == "next_utc_day":
        return day + timedelta(days=1)
    if rule.kind == "next_utc_week":
        return day - timedelta(days=day.weekday()) + timedelta(days=7)
    return None


def compounding_base(snapshot: LedgerSnapshot, *, starting_capital: Decimal, as_of: datetime,
                     settlement: SettlementRule, reconciled_position_ids) -> SizingBase:
    """Sizing base from starting capital plus REALIZED NET profit only (§4.3 rule (a)).

    * Unrealized P&L never enters: marks are not read.
    * A realized net gain enters only when its position is fully closed, its close is in
      ``reconciled_position_ids`` (PR-I13 or the research equivalent) and its settlement point
      under ``settlement`` has passed by ``as_of``.
    * Realized net losses (including entry fees and partial legs of open positions) reduce the
      base at once. A symmetric rule would let the base exceed book equity, breaking PR-I10.
    * Deposits after genesis never feed the base: ``starting_capital`` is explicit (PR-OD2).
    """
    _validate_rule(settlement)
    as_of = _utc(as_of, "as_of")
    start = _dec(starting_capital, "starting_capital", positive=True)
    if snapshot.as_of is not None and as_of < snapshot.as_of:
        raise LedgerError("time_regression", "sizing time precedes the ledger snapshot")
    if start > snapshot.net_contributions:
        raise LedgerError("invalid_input", "starting_capital exceeds net contributions")
    reconciled = frozenset(reconciled_position_ids)
    closes = sorted((v for v in snapshot.positions if v.state == "closed"),
                    key=lambda v: v.close_index)
    total_closes = len(closes)
    settled_ids, pending_ids = [], []
    settled_net = immediate = excluded = ZERO
    with localcontext(_EXACT):
        for view in snapshot.positions:
            net = view.realized_net
            settled = False
            if view.state == "closed" and view.position_id in reconciled:
                if settlement.kind == "after_n_closes":
                    settled = view.close_index + settlement.after_closes <= total_closes
                else:
                    settled = settlement_point(settlement, view.closed_at) <= as_of
            if settled:
                settled_net += net
                settled_ids.append(view.position_id)
                continue
            pending_ids.append(view.position_id)
            if net < 0:
                immediate += net
            else:
                excluded += net
        raw = start + settled_net + immediate
        base = max(raw, ZERO)
        if base > snapshot.equity_cost:
            _violation("PR-I10", "sizing base exceeds book equity at cost")
    return SizingBase(base=base, starting_capital=start, settled_net=settled_net,
                      immediate_losses=immediate, excluded_gains=excluded,
                      floored_at_zero=raw < 0, settled_position_ids=tuple(sorted(settled_ids)),
                      pending_position_ids=tuple(sorted(pending_ids)), as_of=as_of,
                      rule=settlement)


def capital_available(snapshot: LedgerSnapshot) -> Decimal:
    """Capital for new trades: cash − reserved. Unrealized gains are never part of it."""
    return snapshot.available


def loss_streak(snapshot: LedgerSnapshot) -> int:
    """Trailing run of net-losing closes in close order; ``net >= 0`` breaks it, the semantics of
    ``shared.risk_epoch.tail_loss_streak``."""
    closes = sorted((v for v in snapshot.positions if v.state == "closed"),
                    key=lambda v: v.close_index)
    streak = 0
    for view in reversed(closes):
        if view.realized_net >= 0:
            break
        streak += 1
    return streak


@dataclass(frozen=True)
class LadderStep:
    """Fires when the trigger metric is >= ``threshold``; sizes are then × ``multiplier``."""
    threshold: Decimal
    multiplier: Decimal


@dataclass(frozen=True)
class DeRiskingLadder:
    """One externally supplied ladder. ``trigger`` names a non-negative 'badness' metric
    (for example a drawdown fraction, a loss-streak count or a period-loss magnitude)."""
    trigger: str
    steps: tuple


@dataclass(frozen=True)
class DeRiskingResult:
    base: Decimal
    multiplier: Decimal
    adjusted_base: Decimal
    reasons: tuple                     # (trigger, metric, threshold, multiplier) per fired ladder


def _validate_ladders(ladders) -> tuple:
    if isinstance(ladders, (str, bytes)) or not isinstance(ladders, (list, tuple)):
        raise LedgerError("invalid_input", "ladders must be a list or tuple of DeRiskingLadder")
    names = set()
    for ladder in ladders:
        if not isinstance(ladder, DeRiskingLadder):
            raise LedgerError("invalid_input", "ladders must contain DeRiskingLadder")
        _ident(ladder.trigger, "trigger")
        if ladder.trigger in names:
            raise LedgerError("invalid_input", f"duplicate trigger {ladder.trigger!r}")
        names.add(ladder.trigger)
        if not isinstance(ladder.steps, (list, tuple)) or not ladder.steps:
            raise LedgerError("invalid_input", f"ladder {ladder.trigger!r} has no steps")
        prev_threshold = prev_multiplier = None
        for step in ladder.steps:
            if not isinstance(step, LadderStep):
                raise LedgerError("invalid_input", "steps must be LadderStep")
            threshold = _dec(step.threshold, "threshold", non_negative=True)
            multiplier = _dec(step.multiplier, "multiplier", non_negative=True)
            if multiplier > ONE:
                raise LedgerError("invalid_input", "a de-risking multiplier cannot exceed 1")
            if prev_threshold is not None and threshold <= prev_threshold:
                raise LedgerError("invalid_input", "thresholds must be strictly increasing")
            if prev_multiplier is not None and multiplier > prev_multiplier:
                raise LedgerError("invalid_input", "multipliers must be non-increasing")
            prev_threshold, prev_multiplier = threshold, multiplier
    return tuple(ladders)


def apply_derisking(base: Decimal, *, ladders, metrics: Mapping) -> DeRiskingResult:
    """Apply externally supplied ladders to a sizing base: per ladder the deepest fired step,
    overall the minimum multiplier across ladders (§4.6 L-2). No threshold or multiplier has a
    default; an empty ``ladders`` is an explicit L-0 (multiplier 1). Every trigger needs a
    finite, non-negative metric, otherwise the call is refused (fail closed)."""
    base = _dec(base, "base", non_negative=True)
    ladders = _validate_ladders(ladders)
    if not isinstance(metrics, Mapping):
        raise LedgerError("invalid_input", "metrics must be a mapping")
    multiplier = ONE
    reasons = []
    for ladder in sorted(ladders, key=lambda item: item.trigger):
        if ladder.trigger not in metrics:
            raise LedgerError("invalid_input", f"missing metric {ladder.trigger!r}")
        value = _dec(metrics[ladder.trigger], ladder.trigger, non_negative=True)
        fired = [step for step in ladder.steps if value >= Decimal(step.threshold)]
        if fired:
            step = fired[-1]
            step_multiplier = Decimal(step.multiplier)
            reasons.append((ladder.trigger, value, Decimal(step.threshold), step_multiplier))
            multiplier = min(multiplier, step_multiplier)
    with localcontext(_EXACT):
        adjusted = base * multiplier
    return DeRiskingResult(base=base, multiplier=multiplier, adjusted_base=adjusted,
                           reasons=tuple(reasons))
