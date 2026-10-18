"""A47 Binance Spot order-filter validator — pure, research-only, no exchange calls.

Rules follow https://developers.binance.com/docs/binance-spot-api-docs/filters (fetched
2026-10-15): PRICE_FILTER (price >= minPrice, price <= maxPrice, price % tickSize == 0; a 0
disables that sub-rule), LOT_SIZE / MARKET_LOT_SIZE (quantity >= minQty, <= maxQty,
quantity % stepSize == 0; MARKET_LOT_SIZE for MARKET orders only), MIN_NOTIONAL
(price * quantity >= minNotional; MARKET only if applyToMarket, priced at the average price),
NOTIONAL (minNotional <= price * quantity <= maxNotional; applyMinToMarket / applyMaxToMarket).
PERCENT_PRICE* and MAX_NUM_ORDERS need live reference prices / account state and are out of scope.

Rounding policy (explicit, conservative for evaluation — never makes an order better for us):
  BUY limit price  -> DOWN to tick (never pay more than the strategy price)
  SELL target      -> UP to tick   (never sell below the strategy target)
  SELL stop        -> DOWN to tick (never stop out at a better price than specified)
  quantity         -> DOWN to step (never exceed the planned notional)
An adjustment that moves a level by more than ``max_adjust_fraction_of_risk`` of the bracket's
risk distance is REJECTED as a materially different order, not silently rounded.
Nothing in production imports this module.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from typing import Mapping

VERSION = "a47-xr-v1"


def _d(x) -> Decimal:
    try:
        v = Decimal(str(x))
    except (InvalidOperation, ValueError):
        raise ValueError("not_a_number") from None
    if not v.is_finite():
        raise ValueError("non_finite")
    return v


@dataclass(frozen=True)
class SymbolFilters:
    """One symbol's filters as published by exchangeInfo. Fixtures are versioned and illustrative."""
    symbol: str
    tick_size: str
    min_price: str = "0"
    max_price: str = "0"
    step_size: str = "0"
    min_qty: str = "0"
    max_qty: str = "0"
    market_step_size: str | None = None
    market_min_qty: str | None = None
    market_max_qty: str | None = None
    min_notional: str = "0"                 # NOTIONAL (or legacy MIN_NOTIONAL)
    max_notional: str = "0"
    apply_min_to_market: bool = True
    apply_max_to_market: bool = False
    fixture_version: str = "illustrative-2026-10-15"


# Illustrative fixtures (NOT live values; verify against exchangeInfo before any real use).
FIXTURES: Mapping[str, SymbolFilters] = {
    "HIGHPRICEUSDT": SymbolFilters("HIGHPRICEUSDT", tick_size="0.01", min_price="0.01",
                                   max_price="1000000", step_size="0.00001", min_qty="0.00001",
                                   max_qty="9000", min_notional="5", max_notional="9000000"),
    "LOWPRICEUSDT": SymbolFilters("LOWPRICEUSDT", tick_size="0.0001", min_price="0.0001",
                                  max_price="1000", step_size="1", min_qty="1", max_qty="9000000",
                                  market_step_size="1", market_min_qty="1", market_max_qty="500000",
                                  min_notional="5", max_notional="9000000"),
}


@dataclass(frozen=True)
class OrderCheck:
    valid: bool
    reasons: tuple
    price: float | None
    quantity: float | None
    notional: float | None


def _multiple(value: Decimal, step: Decimal) -> bool:
    return step == 0 or (value % step) == 0


def round_to(value, step: str, mode: str) -> float:
    v, s = _d(value), _d(step)
    if s == 0:
        return float(v)
    q = (v / s).to_integral_value(rounding=ROUND_FLOOR if mode == "down" else ROUND_CEILING)
    return float(q * s)


def check_order(f: SymbolFilters, *, side: str, order_type: str, price, quantity,
                average_price=None) -> OrderCheck:
    """Validate one order exactly against the documented rules; never adjusts."""
    reasons = []
    try:
        q = _d(quantity)
        p = _d(price) if order_type != "MARKET" else _d(average_price if average_price is not None else price)
    except ValueError as exc:
        return OrderCheck(False, (f"input:{exc}",), None, None, None)
    if side not in ("BUY", "SELL") or order_type not in ("LIMIT", "MARKET", "STOP_LOSS_LIMIT"):
        return OrderCheck(False, ("unsupported_order",), None, None, None)
    if q <= 0 or p <= 0:
        reasons.append("non_positive")
    if order_type != "MARKET":
        tick, lo, hi = _d(f.tick_size), _d(f.min_price), _d(f.max_price)
        if lo > 0 and p < lo:
            reasons.append("PRICE_FILTER:min_price")
        if hi > 0 and p > hi:
            reasons.append("PRICE_FILTER:max_price")
        if not _multiple(p, tick):
            reasons.append("PRICE_FILTER:tick_size")
    step, mn, mx = _d(f.step_size), _d(f.min_qty), _d(f.max_qty)
    if mn > 0 and q < mn:
        reasons.append("LOT_SIZE:min_qty")
    if mx > 0 and q > mx:
        reasons.append("LOT_SIZE:max_qty")
    if not _multiple(q, step):
        reasons.append("LOT_SIZE:step_size")
    if order_type == "MARKET" and f.market_step_size is not None:
        ms, mmn, mmx = _d(f.market_step_size), _d(f.market_min_qty or "0"), _d(f.market_max_qty or "0")
        if mmn > 0 and q < mmn:
            reasons.append("MARKET_LOT_SIZE:min_qty")
        if mmx > 0 and q > mmx:
            reasons.append("MARKET_LOT_SIZE:max_qty")
        if not _multiple(q, ms):
            reasons.append("MARKET_LOT_SIZE:step_size")
    notional = p * q
    nmin, nmax = _d(f.min_notional), _d(f.max_notional)
    if nmin > 0 and notional < nmin and (order_type != "MARKET" or f.apply_min_to_market):
        reasons.append("NOTIONAL:min_notional")
    if nmax > 0 and notional > nmax and (order_type != "MARKET" or f.apply_max_to_market):
        reasons.append("NOTIONAL:max_notional")
    return OrderCheck(not reasons, tuple(reasons), float(p), float(q), float(notional))


@dataclass(frozen=True)
class PlannedOrder:
    role: str            # entry | stop | t1 | t2 | t3
    side: str
    order_type: str
    price: float
    quantity: float
    adjusted_from: float | None
    check: OrderCheck


@dataclass(frozen=True)
class BracketPlan:
    version: str
    valid: bool
    reasons: tuple
    orders: tuple
    dust_quantity: float
    notes: tuple = field(default_factory=tuple)


def plan_bracket_orders(f: SymbolFilters, *, entry, stop, t1, t2, t3, notional_usdt=50.0,
                        fractions=(0.25, 0.50, 0.25), max_adjust_fraction_of_risk=0.10) -> BracketPlan:
    """Turn a strategy bracket into exchange-valid orders, or say exactly why it cannot be.

    Tranche quantities are floored to the step; the LAST open tranche takes the remainder so no
    position is left stranded; a tranche below min notional merges into the next one (the
    production target_distribution rule); a remainder that is not sellable is reported as dust."""
    reasons, notes, orders = [], [], []
    try:
        e, s, ts = float(_d(entry)), float(_d(stop)), [float(_d(x)) for x in (t1, t2, t3)]
    except ValueError as exc:
        return BracketPlan(VERSION, False, (f"input:{exc}",), (), 0.0)
    if not (0 < s < e < ts[0] <= ts[1] <= ts[2]):
        return BracketPlan(VERSION, False, ("bracket_not_ordered",), (), 0.0)
    risk = e - s
    adj = {"entry": round_to(e, f.tick_size, "down"), "stop": round_to(s, f.tick_size, "down"),
           "t1": round_to(ts[0], f.tick_size, "up"), "t2": round_to(ts[1], f.tick_size, "up"),
           "t3": round_to(ts[2], f.tick_size, "up")}
    raw = {"entry": e, "stop": s, "t1": ts[0], "t2": ts[1], "t3": ts[2]}
    for k in adj:
        if abs(adj[k] - raw[k]) > max_adjust_fraction_of_risk * risk + 1e-15:
            reasons.append(f"rounding_material:{k}")
    if reasons:
        return BracketPlan(VERSION, False, tuple(reasons), (), 0.0)
    qty = round_to(notional_usdt / adj["entry"], f.step_size, "down")
    ec = check_order(f, side="BUY", order_type="LIMIT", price=adj["entry"], quantity=qty)
    orders.append(PlannedOrder("entry", "BUY", "LIMIT", adj["entry"], qty, raw["entry"], ec))
    if not ec.valid:
        return BracketPlan(VERSION, False, ("entry:" + ",".join(ec.reasons),), tuple(orders), 0.0)
    min_n = float(_d(f.min_notional))
    tranche = [round_to(qty * fr, f.step_size, "down") for fr in fractions]
    for i in (0, 2):                                         # merge sub-minimum edge tranches into T2
        if tranche[i] * adj[f"t{i + 1}"] < min_n:
            tranche[1] += tranche[i]
            tranche[i] = 0.0
            notes.append(f"t{i + 1}_merged_into_t2")
    last = max(i for i in range(3) if tranche[i] > 0)
    tranche[last] = round_to(qty - sum(t for j, t in enumerate(tranche) if j != last), f.step_size, "down")
    dust = qty - sum(tranche)
    for i, tq in enumerate(tranche):
        if tq <= 0:
            continue
        c = check_order(f, side="SELL", order_type="LIMIT", price=adj[f"t{i + 1}"], quantity=tq)
        orders.append(PlannedOrder(f"t{i + 1}", "SELL", "LIMIT", adj[f"t{i + 1}"], tq, raw[f"t{i + 1}"], c))
        if not c.valid:
            reasons.append(f"t{i + 1}:" + ",".join(c.reasons))
    sc = check_order(f, side="SELL", order_type="STOP_LOSS_LIMIT", price=adj["stop"], quantity=qty)
    orders.append(PlannedOrder("stop", "SELL", "STOP_LOSS_LIMIT", adj["stop"], qty, raw["stop"], sc))
    if not sc.valid:
        reasons.append("stop:" + ",".join(sc.reasons))
    if dust > 1e-15:
        notes.append("dust_remainder")
    return BracketPlan(VERSION, not reasons, tuple(reasons), tuple(orders), dust, tuple(notes))


def remainder_after_fills(f: SymbolFilters, quantity, sold, price) -> dict:
    """What is left after partial exits, and whether it is still sellable (else dust)."""
    rem = float(_d(quantity)) - float(_d(sold))
    c = check_order(f, side="SELL", order_type="LIMIT", price=round_to(price, f.tick_size, "up"),
                    quantity=round_to(rem, f.step_size, "down")) if rem > 0 else None
    return {"remaining": rem, "sellable": bool(c and c.valid), "reasons": c.reasons if c else ()}
