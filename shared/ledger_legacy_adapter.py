"""WP-E02 legacy-mode ledger adapter and reconciliation (PR-C03, PR-I13; R7.b).

Maps one closed tracker position (its ``active_trades`` row, its ``trade_target_fills`` and the
``trade_results`` economics the tracker just booked) onto ``shared/portfolio_ledger.py`` events,
folds them in a per-position reconciliation ledger, and compares the ledger's realized net with
the tracker's booked net. Pure: no I/O, clock, configuration or randomness. The tracker calls it
behind ``LEDGER_SHADOW`` (``shared/accounting_flags.py``) after its own close transaction, so it
never changes a decision or a database write.

Mapping (PORTFOLIO_RISK_AND_COMPOUNDING.md §3.3):

* quantity ``q = notional / entry`` (quantized to ``QTY_QUANTUM``), at the tracker's fill price;
  ``Deposit`` and ``Reserve`` of exactly the entry outlay, so the ledger is self-funded and no
  genesis amount is chosen (PR-OD1 and PR-OD2 stay open for the portfolio ledger, WP-E04);
* one ``ExitFill`` per target fill (``q × fraction`` at the fill price) and one for the final
  exit of the remainder, so the leg that empties the position closes it;
* costs follow the stored ``label_policy``: ``net_after_modeled_cost_v1`` books no per-leg fee and
  one flat ``notional × FEE_ROUNDTRIP_PCT / 100`` cost on the closing leg, which reproduces
  ``shared/fees.py:L52-L60``; ``net_single_count_legacy_v1`` books the per-leg fee of
  ``shared/cost_label_policy.py`` on each leg and no flat cost.

Reconciliation (PR-I13): ledger realized net equals the booked ``net_profit_usdt`` within
``NET_TOLERANCE``, the quantum of the stored gross (``round(profit_usdt, 4)``,
``trade_tracker/main.py`` ``close_trade_barrier``). A mismatch is ``F7.ledger_mismatch`` plus a
discrepancy record, never an adjustment. Named discrepancies of the legacy path:

* ``PR-17``: the notional at open differs from the one at close. No per-position notional is
  persisted (PR-03), so the shadow passes ``notional_at_open=None`` and records the note
  ``notional_at_open_not_persisted``;
* ``PR-07``: ``pr07_divergence`` reproduces the legacy unrealized formula (full notional at the
  mark, ``trade_tracker/main.py`` ``assess_new_trade_risk``) against the ledger's realized tranche
  plus open-quantity unrealized; the difference is ``Σ fraction × notional × (mark − T) / entry``.

Unrealized gains never become spendable: ``spendable_capital`` is the ledger's ``available``
(cash − reserved), which marks never move (PR-I9, PR-I10).

Enforcement is not built: a mismatch does not halt admissions here (that is a decision change,
PR-C07 / WP-G21, and needs persistence, WP-E03 / WP-E04).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import (ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, Inexact, InvalidOperation,
                     Overflow, localcontext)
from typing import Sequence

from shared import portfolio_ledger as pl
from shared.accounting_flags import LEGACY_LABEL_POLICY, SINGLE_COUNT_LABEL_POLICY
from shared.cost_label_policy import fee_per_side, leg_notionals
from shared.cost_models import LEGACY_TRACKER_V1, LegacyTrackerV1

ADAPTER_VERSION = "wp-e02-legacy-adapter-v1"
QUOTE_ASSET = "USDT"
QTY_QUANTUM = Decimal("1e-18")          # base quantity of the reconciliation ledger
MONEY_QUANTUM = Decimal("1e-12")        # pro-rata cost release on a partial exit
NET_TOLERANCE = Decimal("0.0001")       # stored gross is round(profit_usdt, 4)
COST_TOLERANCE = Decimal("0.000001")    # stored cost is round(cost, 6)
FRACTION_TOLERANCE = 1e-9
LEDGER_MISMATCH_CODE = "F7.ledger_mismatch"
_DIV = Context(prec=60, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow])
# Sums and products of finite decimals are exact at this precision; Inexact is trapped.
_EXACT = Context(prec=60, rounding=ROUND_HALF_EVEN,
                 traps=[InvalidOperation, DivisionByZero, Overflow, Inexact])


def _d(value) -> Decimal:
    """Exact decimal of a float's shortest repr (the tracker's float columns)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    return Decimal(repr(float(value)))


@dataclass(frozen=True)
class TrackerClose:
    """One closed tracker position, as the close path holds it."""
    trade_id: int
    symbol: str
    strategy_id: str
    opened_at: datetime
    closed_at: datetime
    entry_price: float
    notional: float
    target_fills: tuple           # ((quantity_fraction, fill_price), ...)
    final_exit_price: float
    remaining_fraction: float
    booked_profit_usdt: float     # the stored round(profit_usdt, 4)
    booked_cost_usdt: float
    booked_net_profit_usdt: float
    label_policy: str
    notional_at_open: float | None = None


@dataclass(frozen=True)
class Reconciliation:
    trade_id: int
    label_policy: str
    ok: bool
    reason_code: str | None
    ledger_realized_gross: Decimal | None
    ledger_costs: Decimal | None
    ledger_realized_net: Decimal | None
    booked_net: Decimal
    difference: Decimal | None
    discrepancies: tuple
    notes: tuple
    state_hash: str | None
    adapter_version: str = ADAPTER_VERSION
    cost_model_id: str = LEGACY_TRACKER_V1
    tolerance: Decimal = field(default=NET_TOLERANCE)

    def as_dict(self) -> dict:
        def s(v):
            return None if v is None else format(v, "f")
        return {"trade_id": self.trade_id, "label_policy": self.label_policy, "ok": self.ok,
                "reason_code": self.reason_code, "ledger_realized_gross": s(self.ledger_realized_gross),
                "ledger_costs": s(self.ledger_costs), "ledger_realized_net": s(self.ledger_realized_net),
                "booked_net": s(self.booked_net), "difference": s(self.difference),
                "tolerance": s(self.tolerance), "discrepancies": list(self.discrepancies),
                "notes": list(self.notes), "state_hash": self.state_hash,
                "adapter_version": self.adapter_version, "cost_model_id": self.cost_model_id}


def _quantity(notional: Decimal, entry: Decimal) -> Decimal:
    with localcontext(_DIV):
        return (notional / entry).quantize(QTY_QUANTUM)


def _leg_fees(close: TrackerClose, bound: LegacyTrackerV1) -> list:
    """Per-leg fees in leg order (entry, targets..., final) under the stored label policy."""
    n_legs = 1 + len(close.target_fills) + (1 if float(close.remaining_fraction) > 0 else 0)
    if close.label_policy == LEGACY_LABEL_POLICY:
        return [pl.ZERO] * n_legs
    rate = fee_per_side(bound)
    notionals = leg_notionals(notional=close.notional, entry_price=close.entry_price,
                              target_fills=close.target_fills,
                              final_exit_price=close.final_exit_price,
                              remaining_fraction=close.remaining_fraction)
    return [_d(rate * n) for n in notionals]


def ledger_events(close: TrackerClose, bound: LegacyTrackerV1) -> list:
    """The ledger events of one closed position (see the module docstring)."""
    if close.label_policy not in (LEGACY_LABEL_POLICY, SINGLE_COUNT_LABEL_POLICY):
        raise ValueError(f"label_policy_unknown:{close.label_policy!r}")
    tid = f"trade:{int(close.trade_id)}"
    entry = _d(close.entry_price)
    qty = _quantity(_d(close.notional), entry)
    fees = _leg_fees(close, bound)
    flat = _d(bound.fee_usdt()) if close.label_policy == LEGACY_LABEL_POLICY else pl.ZERO
    with localcontext(_EXACT):
        outlay = qty * entry + fees[0]
    events = [pl.Deposit(f"{tid}:deposit", close.opened_at, outlay),
              pl.Reserve(f"{tid}:reserve", close.opened_at, tid, close.symbol,
                         close.strategy_id or "unassigned", outlay),
              pl.EntryFill(f"{tid}:entry", close.opened_at, tid, qty, entry, fees[0], QUOTE_ASSET,
                           pl.ZERO)]
    exits = [(f"T{i}", _d(frac), _d(price)) for i, (frac, price) in enumerate(close.target_fills, 1)]
    if float(close.remaining_fraction) > 0:
        exits.append(("final", None, _d(close.final_exit_price)))
    if not exits:
        raise ValueError("no_exit_leg")
    open_qty = qty
    for index, (leg, frac, price) in enumerate(exits):
        last = index == len(exits) - 1
        with localcontext(_EXACT):
            leg_qty = open_qty if (last or frac is None) else qty * frac
        if leg_qty <= 0 or leg_qty > open_qty:
            raise ValueError(f"leg_quantity_invalid:{leg}")
        events.append(pl.ExitFill(f"{tid}:exit:{leg}", close.closed_at, tid, leg, leg_qty, price,
                                  fees[index + 1], QUOTE_ASSET, flat if last else pl.ZERO))
        with localcontext(_EXACT):
            open_qty -= leg_qty
    return events


def reconcile(close: TrackerClose, bound: LegacyTrackerV1) -> Reconciliation:
    """PR-I13 for one close. Never raises for a ledger refusal: it is a discrepancy."""
    booked_net = _d(close.booked_net_profit_usdt)
    notes, discrepancies = [], []
    if close.notional_at_open is None:
        notes.append("notional_at_open_not_persisted")
    elif _d(close.notional_at_open) != _d(close.notional):
        discrepancies.append("PR-17")
    sold = sum(float(f) for f, _ in close.target_fills)
    if abs(sold + float(close.remaining_fraction) - 1.0) > FRACTION_TOLERANCE:
        discrepancies.append("fraction_not_conserved")
    try:
        ledger = pl.replay(ledger_events(close, bound), ledger_id=f"recon:{int(close.trade_id)}",
                           quote_asset=QUOTE_ASSET, cost_model_id=LEGACY_TRACKER_V1,
                           money_quantum=MONEY_QUANTUM)
    except (pl.LedgerError, ValueError, ArithmeticError) as exc:
        reason = getattr(exc, "reason", None) or str(exc).split(":", 1)[0]
        return Reconciliation(close.trade_id, close.label_policy, False, LEDGER_MISMATCH_CODE,
                              None, None, None, booked_net, None,
                              tuple(discrepancies + [f"ledger_refused:{reason}"]), tuple(notes), None)
    state = ledger.state
    pos = state.positions[f"trade:{int(close.trade_id)}"]
    if pos.state != "closed":
        discrepancies.append("position_not_closed")
    with localcontext(_EXACT):
        costs = state.fees + state.costs
        net = state.realized_net
        difference = net - booked_net
        gross_diff = state.realized_gross - _d(close.booked_profit_usdt)
        cost_diff = costs - _d(close.booked_cost_usdt)
    if abs(difference) > NET_TOLERANCE:
        discrepancies.append("net_mismatch")
    if abs(gross_diff) > NET_TOLERANCE:
        discrepancies.append("gross_mismatch")
    if abs(cost_diff) > COST_TOLERANCE:
        discrepancies.append("cost_mismatch")
    ok = not discrepancies
    return Reconciliation(close.trade_id, close.label_policy, ok,
                          None if ok else LEDGER_MISMATCH_CODE, state.realized_gross, costs, net,
                          booked_net, difference, tuple(discrepancies), tuple(notes),
                          ledger.state_hash)


def spendable_capital(ledger: pl.PortfolioLedger) -> Decimal:
    """Capital a new trade may use: ``available`` (cash − reserved). Marks never move it, so an
    unrealized gain is never spendable (PR-I9, PR-I10)."""
    return ledger.snapshot().available


def pr07_divergence(*, trade_id: int, symbol: str, opened_at: datetime, as_of: datetime,
                    entry_price: float, notional: float, target_fills: Sequence,
                    mark_price: float) -> dict:
    """PR-07 as a named discrepancy for an open position with target tranches already sold.

    ``legacy_gross`` is the tracker's unrealized formula before its fee,
    ``(mark / entry − 1) × notional``; the ledger values the sold tranches at their fills and only
    the open quantity at the mark. ``divergence = legacy_gross − (realized_gross + unrealized)``."""
    tid = f"trade:{int(trade_id)}"
    entry = _d(entry_price)
    qty = _quantity(_d(notional), entry)
    with localcontext(_EXACT):
        outlay = qty * entry
    ledger = pl.PortfolioLedger(ledger_id=f"pr07:{int(trade_id)}", quote_asset=QUOTE_ASSET,
                                cost_model_id=LEGACY_TRACKER_V1, money_quantum=MONEY_QUANTUM)
    ledger.apply_all([pl.Deposit(f"{tid}:deposit", opened_at, outlay),
                      pl.Reserve(f"{tid}:reserve", opened_at, tid, symbol, "unassigned", outlay),
                      pl.EntryFill(f"{tid}:entry", opened_at, tid, qty, entry, pl.ZERO, QUOTE_ASSET,
                                   pl.ZERO)])
    for i, (frac, price) in enumerate(target_fills, 1):
        with localcontext(_EXACT):
            leg_qty = qty * _d(frac)
        ledger.apply(pl.ExitFill(f"{tid}:exit:T{i}", as_of, tid, f"T{i}", leg_qty, _d(price),
                                 pl.ZERO, QUOTE_ASSET, pl.ZERO))
    before = spendable_capital(ledger)
    ledger.apply(pl.Mark(f"{tid}:mark", as_of, symbol, _d(mark_price), "pr07"))
    snap = ledger.snapshot()
    with localcontext(_DIV):
        legacy_gross = (_d(mark_price) / entry - 1) * _d(notional)
        divergence = legacy_gross - (snap.realized_gross + snap.unrealized)
    return {"legacy_gross": legacy_gross, "ledger_realized_gross": snap.realized_gross,
            "ledger_unrealized": snap.unrealized, "divergence": divergence,
            "spendable_before_mark": before, "spendable_after_mark": snap.available,
            "equity_mtm": snap.equity_mtm}
