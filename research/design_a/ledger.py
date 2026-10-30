"""Design A v1.0 state machine and accounting (spec §7, §9–§13).

``apply_decision`` records a decision and opens a pending transition only for a genuine state
transition: the target changes and differs from the actual position. ``execute_pending`` fills it
at the open of the scheduled Tuesday candle, or of the next available candle opening within three
calendar days of the decision, with the frozen cost formulas; a reference candle that is due but
unavailable is recorded as missing market data, and the transition is cancelled once no eligible
candle remains. Balances change only on a fill, and nothing is charged otherwise.

Every execution-side entry is booked at the instant its outcome became known under the
availability rule, never at the instant a caller happened to look. For snapshots that never
deliver a candle late (``replay`` refuses revised ones), the ledger therefore does not depend on
how often snapshots were taken.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from decimal import Decimal

from research.data_governance.governance import canonical_hash
from research.design_a import VERSION
from research.design_a.decision import decide
from research.design_a.state import (DAY, EVIDENCE_CLASS, FLOOR, ONE, ZERO,
                                     Candle, Decision, DesignAError, Event, ExecutionStatus,
                                     LedgerEntry, MinOrderRules, PendingTransition, Side, Snapshot,
                                     State, Target, TransitionError, actual_position, amount,
                                     arithmetic, check_inputs, floor_to_step, required_action, text)
from research.design_a.timing import (available, available_from, is_decision_instant, is_overdue,
                                      next_decision_instant, scheduled_reference_open)


def _entry(state: State, entries: list, at, event: Event, **values) -> LedgerEntry:
    values.setdefault("cash", state.cash)
    values.setdefault("btc", state.btc)
    return LedgerEntry(seq=len(state.ledger) + len(entries), at=at, event=event, **values)


def apply_decision(state: State, decision: Decision) -> State:
    """Record ``decision``; open a pending transition only for a genuine state transition."""
    if not isinstance(state, State) or not isinstance(decision, Decision):
        raise TypeError("expected (state: State, decision: Decision)")
    if decision.event is Event.NO_SIGNAL:
        if is_decision_instant(decision.at):
            raise TransitionError("NO_SIGNAL cannot stand in for a weekly decision")
        return state
    if not is_decision_instant(decision.at):
        raise TransitionError("a decision can only be applied at a decision instant")
    if state.pending is not None:
        raise TransitionError("a pending transition is unresolved; call execute_pending first")
    if state.last_decision_at is not None and decision.at <= state.last_decision_at:
        raise TransitionError("decision already applied, or older than the last decision")
    if state.ledger and decision.at < state.ledger[-1].at:
        raise TransitionError("decision is older than the last ledger entry")
    if decision.event is Event.WARMUP and state.target is not None:
        raise TransitionError("warm-up is only the initial state")
    entries = [_entry(state, [], decision.at, decision.event, reason=decision.reason,
                      sunday_close=decision.sunday_close, sma=decision.sma)]
    if decision.target is None:     # warm-up or a skipped decision: holdings and target are kept
        return replace(state, last_decision_at=decision.at, ledger=state.ledger + tuple(entries))
    if required_action(state, decision.target) is not decision.action:
        raise TransitionError("decision was computed for a different target or position")
    changes = {"target": decision.target, "last_decision_at": decision.at}
    if decision.action is None:
        why = "TARGET_UNCHANGED" if decision.target is state.target else "ALREADY_AT_TARGET"
        entries.append(_entry(state, entries, decision.at, Event.NO_CHANGE, reason=why))
    else:
        pending = PendingTransition(decision.action, decision.at,
                                    scheduled_reference_open(decision.at))
        event = Event.PENDING_BUY if pending.side is Side.BUY else Event.PENDING_SELL
        entries.append(_entry(state, entries, decision.at, event, side=pending.side,
                              decided_at=pending.decided_at, expires_at=pending.expires_at,
                              reference_time=pending.next_open))
        changes.update(pending=pending, execution_status=ExecutionStatus.PENDING)
    return replace(state, ledger=state.ledger + tuple(entries), **changes)


def execute_pending(state: State, snapshot: Snapshot) -> State:
    """Advance the pending transition as far as ``snapshot`` allows (spec §7): fill it, record
    missing reference candles, or cancel it once none can remain within the window."""
    check_inputs(state, snapshot)
    pending = state.pending
    if pending is None:
        raise TransitionError("no pending transition to execute")
    as_of = snapshot.as_of
    if as_of <= pending.decided_at:
        raise TransitionError("execution is checked only strictly after the decision")
    if state.ledger and as_of < state.ledger[-1].at:
        raise TransitionError("snapshot is older than the last ledger entry")
    candles = available(snapshot)
    entries: list[LedgerEntry] = []
    status = state.execution_status
    while True:
        candle = candles.get(pending.next_open)
        if candle is not None:
            return _fill(state, pending, candle, entries)
        if not is_overdue(pending.next_open, as_of):
            break                                   # the reference candle cannot be complete yet
        due = available_from(pending.next_open)     # when it should have become available
        entries.append(_entry(state, entries, due, Event.MISSING_MARKET_DATA,
                              reason="REFERENCE_CANDLE_UNAVAILABLE", side=pending.side,
                              decided_at=pending.decided_at, reference_time=pending.next_open))
        following = pending.next_open + DAY
        if following > pending.expires_at:         # no eligible reference remains: cancel
            entries.append(_entry(state, entries, due, Event.EXPIRED,
                                  reason="NO_REFERENCE_WITHIN_THREE_DAYS", side=pending.side,
                                  decided_at=pending.decided_at, expires_at=pending.expires_at))
            return replace(state, pending=None, execution_status=ExecutionStatus.EXPIRED,
                           ledger=state.ledger + tuple(entries))
        pending = replace(pending, next_open=following)
        status = ExecutionStatus.DEFERRED
    return replace(state, pending=pending, execution_status=status,
                   ledger=state.ledger + tuple(entries))


def _min_order_failure(quantity: Decimal, notional: Decimal, rules: MinOrderRules) -> str | None:
    if quantity == 0:
        return "ZERO_QUANTITY"
    if quantity < rules.min_qty:
        return "BELOW_MIN_QTY"
    if notional < rules.min_notional:
        return "BELOW_MIN_NOTIONAL"
    return None


def _fill(state: State, pending: PendingTransition, candle: Candle, entries: list) -> State:
    """Frozen formulas (spec §10): P_buy = P(1 + hs + sl), quantity = Cash / (P_buy (1 + fee))
    rounded down to qty_step; P_sell = P(1 - hs - sl), quantity = BTC rounded down to qty_step.
    The fee is charged once, in quote currency, on quantity x execution price. The outcome is
    booked when the reference candle became available."""
    costs, rules = state.costs, state.rules
    reference = candle.open
    known = available_from(candle.open_time)
    common = {"side": pending.side, "decided_at": pending.decided_at,
              "reference_time": candle.open_time, "reference_price": reference}
    with arithmetic():
        if pending.side is Side.BUY:
            price = reference * (ONE + costs.half_spread + costs.slippage)
            per_unit = price * (ONE + costs.fee)
            with arithmetic(FLOOR):
                affordable = state.cash / per_unit
            quantity = floor_to_step(affordable, rules.qty_step)
        else:
            price = reference * (ONE - costs.half_spread - costs.slippage)
            quantity = floor_to_step(state.btc, rules.qty_step)
        notional = quantity * price
    failure = _min_order_failure(quantity, notional, rules)
    if failure is not None:     # no fill, nothing charged, no smaller order invented
        entries.append(_entry(state, entries, known, Event.REJECTED_MIN_ORDER, reason=failure,
                              execution_price=price, quantity=quantity, notional=notional,
                              **common))
        return replace(state, pending=None, execution_status=ExecutionStatus.REJECTED_MIN_ORDER,
                       ledger=state.ledger + tuple(entries))
    with arithmetic():
        fee = notional * costs.fee
        spread_cost = quantity * reference * costs.half_spread
        slippage_cost = quantity * reference * costs.slippage
        if pending.side is Side.BUY:
            cash, btc = state.cash - notional - fee, state.btc + quantity
        else:
            cash, btc = state.cash + notional - fee, state.btc - quantity
    if cash < 0 or btc < 0:     # unreachable: the buy quantity is floored and fee, hs + sl < 1
        raise ArithmeticError("a fill would make a balance negative")
    entries.append(_entry(state, entries, known, Event.EXECUTED, cash=cash, btc=btc,
                          execution_price=price, quantity=quantity, notional=notional, fee=fee,
                          spread_cost=spread_cost, slippage_cost=slippage_cost, **common))
    if pending.side is Side.SELL and btc > 0:   # marked at the latest close known at that instant
        entries.append(_entry(state, entries, known, Event.RESIDUAL_DUST, cash=cash, btc=btc,
                              reason="BELOW_QTY_STEP", quantity=btc, mark_price=candle.close))
    return replace(state, cash=cash, btc=btc, pending=None,
                   execution_status=ExecutionStatus.EXECUTED,
                   ledger=state.ledger + tuple(entries))


def mark_price(snapshot: Snapshot) -> Decimal:
    """Close of the latest available daily candle (provisional mark, spec §13)."""
    candles = available(snapshot)
    if not candles:
        raise DesignAError("no available candle to mark against")
    return candles[max(candles)].close


@dataclass(frozen=True)
class Valuation:
    """Equity at a mark price, with the residual balances a position label could hide."""
    cash: Decimal
    btc: Decimal
    mark_price: Decimal
    equity: Decimal
    target: Target | None       # intended state
    position: Target            # actual position
    residual_btc: Decimal       # BTC not intended by a LONG target held as a LONG position
    residual_value: Decimal     # residual_btc marked to market
    residual_cash: Decimal      # cash not deployed while the target is LONG


def valuation(state: State, mark: Decimal) -> Valuation:
    """Mark-to-market equity: cash + all BTC, dust included, x mark (no liquidation haircut).
    Residual exposure is reported whenever the strategy is not LONG in both intention and fact,
    so a FLAT target or position never hides BTC (spec §12)."""
    if not isinstance(state, State):
        raise TypeError("state must be a State")
    amount(mark, "mark", positive=True)
    position = actual_position(state)
    fully_long = state.target is Target.LONG and position is Target.LONG
    residual_btc = ZERO if fully_long else state.btc
    with arithmetic():
        equity = state.cash + state.btc * mark
        residual_value = residual_btc * mark
    return Valuation(state.cash, state.btc, mark, equity, state.target, position, residual_btc,
                     residual_value, state.cash if state.target is Target.LONG else ZERO)


def cost_totals(state: State) -> dict[str, Decimal]:
    """Fee, spread and slippage summed over executed fills, in quote currency."""
    executed = [e for e in state.ledger if e.event is Event.EXECUTED]
    with arithmetic():
        return {name: sum((getattr(e, name) for e in executed), ZERO)
                for name in ("fee", "spread_cost", "slippage_cost")}


def replay(state: State, snapshots: Iterable[Snapshot]) -> State:
    """Drive the state machine through ``snapshots`` in time order. At each snapshot a pending
    transition is advanced first, then the weekly decision is taken (NO_SIGNAL changes nothing).

    A snapshot is required at every decision instant from the first snapshot on (or from the
    state's last decision, when resuming); a skipped decision instant is refused, never silently
    passed over. A candle that differs from the one an earlier snapshot of this call carried for
    the same day is refused as revised data. Between decision instants any cadence then gives the
    same ledger, provided no candle arrives late."""
    previous = None
    seen: dict = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, Snapshot):
            raise TypeError("snapshots must be Snapshot objects")
        if previous is not None and snapshot.as_of <= previous:
            raise DesignAError("snapshots must be in strictly increasing as_of order")
        if previous is None and ((state.last_decision_at is not None
                                  and snapshot.as_of <= state.last_decision_at)
                                 or (state.ledger and snapshot.as_of < state.ledger[-1].at)):
            raise DesignAError("the first snapshot is not later than the state's ledger")
        for candle in snapshot.candles:
            if seen.setdefault(candle.open_time, candle) != candle:
                raise DesignAError(f"candle {candle.open_time.isoformat()} was revised "
                                   f"between snapshots")
        anchor = previous if previous is not None else state.last_decision_at
        if anchor is not None and snapshot.as_of > next_decision_instant(anchor):
            raise DesignAError(f"no snapshot at the decision instant "
                               f"{next_decision_instant(anchor).isoformat()}; replay needs one "
                               f"at every decision instant")
        previous = snapshot.as_of
        if state.pending is not None:
            state = execute_pending(state, snapshot)
        state = apply_decision(state, decide(state, snapshot))
    return state


def state_record(state: State) -> dict:
    """Canonical, JSON-ready description of ``state``: configuration, balances and ledger."""
    def iso(at):
        return None if at is None else at.isoformat()
    pending = state.pending
    return {
        "version": VERSION,
        "evidence_class": EVIDENCE_CLASS,
        "costs": {"fee": text(state.costs.fee), "half_spread": text(state.costs.half_spread),
                  "slippage": text(state.costs.slippage), "label": state.costs.label},
        "rules": {"min_notional": text(state.rules.min_notional),
                  "min_qty": text(state.rules.min_qty), "qty_step": text(state.rules.qty_step)},
        "cash": text(state.cash),
        "btc": text(state.btc),
        "target": None if state.target is None else str(state.target),
        "execution_status": None if state.execution_status is None else str(state.execution_status),
        "pending": None if pending is None else {"side": str(pending.side),
                                                "decided_at": iso(pending.decided_at),
                                                "next_open": iso(pending.next_open)},
        "last_decision_at": iso(state.last_decision_at),
        "ledger": [entry.record() for entry in state.ledger],
    }


def digest(state: State) -> str:
    """sha256 of the canonical record (the repository's ``canonical_hash`` convention)."""
    return canonical_hash(state_record(state))
