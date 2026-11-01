"""Shadow validation of the tracker's position lifecycle through ``shared/position_state.py``.

Behind ``POSITION_STATE_SHADOW`` (``shared/accounting_flags.py``) the tracker passes each lifecycle
step it has already committed (target hits in ``evaluate_trade``, the close in
``close_trade_barrier``) to these pure functions. They rebuild a ``PositionRecord`` from the
tracker's row, apply the matching events and return every refusal. They never decide, write or
raise: a refusal is data for the caller to log or record.

Quantities are fractions of the position (``planned_qty`` 1, lot step ``QTY_STEP``), which is how
the tracker stores them (``active_trades.remaining_fraction``, ``trade_target_fills``). The exit
fractions are the tracker's own 25/50/25 split with sub-minimum merging
(``shared/partial_exits.target_distribution``) for ``partial_25_50_25_v1``, else one T3 tranche.

Known difference, recorded and not resolved: when a tranche is merged away, the machine closes the
position on the leg that empties it ("the last target with a non-zero fraction sells the
remainder"), while the tracker keeps a row with ``remaining_fraction`` 0 open until T3 or a stop.
The later close is then refused as ``close_with_no_open_quantity``. Enforce mode (refusing a
tracker step) would change exits, so it needs a version boundary and is not built.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from shared import position_state as ps
from shared.partial_exits import target_distribution
from shared.triple_barrier import TripleBarrierState

SHADOW_VERSION = "wp-d03-tracker-shadow-v1"
LEGACY_EXIT_POLICY = "partial_25_50_25_v1"
QTY_STEP = Decimal("1e-12")
STOP_REASONS = ("stop_loss", "break_even", "trailing_stop")
INVALIDATION_REASON = "signal_candle_invalidation"
TIME_PREFIXES = ("T1_expired", "no_T1_expired", "expired_")
ADMIN_RULE = "tracker_admin_close"
_STATE_FOR_TARGET = {0: ps.OPEN, 1: ps.PARTIAL_T1, 2: ps.PARTIAL_T2}


@dataclass(frozen=True)
class ShadowRefusal:
    site: str
    step: str
    reason: str
    detail: str

    def as_dict(self) -> dict:
        return {"site": self.site, "step": self.step, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True)
class ShadowResult:
    site: str
    trade_id: int
    refusals: tuple
    final_state: str | None
    transitions: tuple            # rule ids applied
    version: str = SHADOW_VERSION

    @property
    def ok(self) -> bool:
        return not self.refusals

    def as_dict(self) -> dict:
        return {"site": self.site, "trade_id": self.trade_id, "ok": self.ok,
                "refusals": [r.as_dict() for r in self.refusals], "final_state": self.final_state,
                "transitions": list(self.transitions), "version": self.version}


def _d(value) -> Decimal:
    return ps.decimal_from_legacy(value)


def exit_fractions(trade: dict, *, notional: float, min_notional: float) -> tuple:
    if trade.get("exit_policy_version") == LEGACY_EXIT_POLICY:
        dist = target_distribution(notional, min_notional)
        return tuple(_d(dist[t]) for t in (1, 2, 3))
    return (Decimal(0), Decimal(0), Decimal(1))


def plan_from_trade(trade: dict, *, notional: float, min_notional: float) -> ps.PositionPlan:
    stop = _d(trade["stop_loss"])
    invalidation = trade.get("stop_invalidation")
    return ps.validate_plan(ps.PositionPlan(
        intent_id=f"trade:{int(trade['id'])}", symbol=str(trade["symbol"]),
        strategy_id=str(trade.get("trade_type") or "unassigned"), planned_qty=Decimal(1),
        planned_entry=_d(trade["entry_price"]), stop=stop,
        invalidation=_d(invalidation) if invalidation else stop,
        targets=tuple(_d(trade[f"target_{t}"]) for t in (1, 2, 3)),
        exit_fractions=exit_fractions(trade, notional=notional, min_notional=min_notional),
        qty_step=QTY_STEP))


def _restore(plan: ps.PositionPlan, *, highest: int, remaining, stop_level) -> ps.PositionRecord:
    remaining = _d(remaining)
    sold = Decimal(1) - remaining
    legs = ()
    if sold > 0:
        target = highest if highest in (1, 2, 3) else None
        legs = (ps.Leg("target" if target else "admin", sold, plan.targets[(target or 1) - 1], target),)
    state = _STATE_FOR_TARGET.get(highest)
    if state is None:
        raise ps.TransitionRefused("invalid_record", f"highest_target {highest} is not open")
    return ps.restore(plan, state=state, reservation_active=False, entry_open=False,
                      entry_legs=(ps.Leg("entry", Decimal(1), plan.planned_entry, None),),
                      exit_legs=legs, highest_target=highest, stop_level=_d(stop_level),
                      reason_code=None, exit_kind=None, exit_rule=None)


def _refusal(site: str, step: str, exc: BaseException) -> ShadowRefusal:
    if isinstance(exc, ps.TransitionRefused):
        return ShadowRefusal(site, step, exc.reason, exc.detail[:200])
    return ShadowRefusal(site, step, f"shadow_error:{type(exc).__name__}", str(exc)[:200])


def validate_target_hits(trade: dict, *, cfg, peak_before: float, peak: float, prev_highest: int,
                         new_highest: int,
                         fills: Sequence, notional: float, min_notional: float) -> ShadowResult:
    """Target hits ``prev_highest -> new_highest`` committed by ``evaluate_trade``. ``fills`` are
    the tracker's ``partial_exits.TargetFill`` rows; ``cfg`` its ``TripleBarrierConfig`` (read
    only, for the stop the tracker's policy gives after each target); ``peak_before`` the stored
    peak and ``peak`` the peak after this observation."""
    site, tid = "evaluate_trade:target_hit", int(trade["id"])
    applied, record = [], None
    try:
        plan = plan_from_trade(trade, notional=notional, min_notional=min_notional)
        prior_stop, _ = TripleBarrierState(peak=float(peak_before),
                                           highest_target=prev_highest).effective_stop(cfg)
        remaining = trade.get("remaining_fraction")
        record = _restore(plan, highest=prev_highest,
                          remaining=1.0 if remaining is None else remaining, stop_level=prior_stop)
        by_target = {f.target: f for f in fills}
        for target in range(prev_highest + 1, new_highest + 1):
            fill = by_target.get(target)
            if target == 3 and fill is None:
                break                    # no T3 tranche booked here: the close sells the remainder
            qty = _d(fill.fraction) if fill else Decimal(0)
            price = _d(fill.price) if fill else plan.targets[target - 1]
            flat = record.qty_open - qty == 0
            new_stop = None
            if not flat:
                stop, _ = TripleBarrierState(peak=float(peak), highest_target=target).effective_stop(cfg)
                new_stop = _d(stop)
            record, transition = ps.apply(record, ps.TargetFill(target=target, qty=qty, price=price,
                                                               new_stop=new_stop))
            applied.append(transition.rule_id)
    except Exception as exc:
        return ShadowResult(site, tid, (_refusal(site, f"T{len(applied) + prev_highest + 1}", exc),),
                            None if record is None else record.state, tuple(applied))
    return ShadowResult(site, tid, (), record.state, tuple(applied))


def close_event(reason: str, qty: Decimal, price: Decimal):
    if reason in STOP_REASONS:
        return ps.StopExit(qty=qty, price=price)
    if reason == INVALIDATION_REASON:
        return ps.InvalidationExit(qty=qty, price=price)
    if reason == "T3":
        return ps.TargetFill(target=3, qty=qty, price=price, new_stop=None)
    if any(str(reason).startswith(p) for p in TIME_PREFIXES):
        return ps.TimeExit(qty=qty, price=price, rule=str(reason))
    return ps.AdminExit(qty=qty, price=price, rule=ADMIN_RULE)


def validate_close(trade: dict, *, reason: str, exit_price: float, notional: float,
                   min_notional: float) -> ShadowResult:
    """The close committed by ``close_trade_barrier`` (row read before the close)."""
    site, tid = "close_trade_barrier", int(trade["id"])
    highest = int(trade.get("highest_target_hit") or 0)
    remaining = trade.get("remaining_fraction")
    remaining = 1.0 if remaining is None else float(remaining)
    try:
        if remaining <= 0:
            if highest == 3 and reason == "T3":
                return ShadowResult(site, tid, (), ps.CLOSED, ())
            raise ps.TransitionRefused("close_with_no_open_quantity",
                                       f"reason {reason!r} with highest_target {highest}")
        plan = plan_from_trade(trade, notional=notional, min_notional=min_notional)
        record = _restore(plan, highest=min(highest, 2), remaining=remaining, stop_level=plan.stop)
        record, transition = ps.apply(record, close_event(reason, record.qty_open, _d(exit_price)))
    except Exception as exc:
        return ShadowResult(site, tid, (_refusal(site, "close", exc),), None, ())
    return ShadowResult(site, tid, (), record.state, (transition.rule_id,))
