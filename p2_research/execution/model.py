"""Execution & transaction-cost model X0 (entry / exit legs, round trip). Deterministic, PIT-safe, fail-closed.

Cost decomposition (all bps, side = +1 buy / -1 sell, fractions h, s, f):
  h = side * (touch - mid) / mid            spread_cost_bps = h * 1e4          (DERIVED)
  s = side * (fill - touch) / touch         slippage_bps    = s * 1e4          (model provenance)
  f = fee rate                              fee_bps         = f * 1e4          (fee schedule, ASSUMED in v1)
  total = side * (fill * (1 + side*f) - mid) / mid; interaction = total - h - s - f  (exact)
Latency drift (decision mid -> execution mid) is market movement, reported separately and never counted as cost.
"""
from __future__ import annotations

import datetime as dt

from .. import instrument as IN, ledger as LG
from . import contracts as CT
from . import quality as QL
from .market_state import PITMarketView
from .schema import (ASSUMED, DERIVED, ESTIMATED, INVALID, MEASURED, UNAVAILABLE, VALID, canon, na, q, rnd,
                     weakest, with_id, worst_state)

RECORD = "tsb.p2x.execution_estimate"
RECORD_VERSION = 1
SIDES = {"buy": (1, "entry"), "sell": (-1, "exit")}


class ExecutionError(ValueError):
    pass


class UnsupportedDirection(ExecutionError):
    pass


def _us(d: dt.datetime) -> int:
    return int(d.timestamp()) * 1_000_000 + d.microsecond


W3_START_US, W3_END_US = _us(LG.W3_START), _us(LG.W3_END)


def require_outside_w3(t_ms: int, what: str) -> None:
    """Refuse any time inside the sealed holdout W3 = [W3_START, W3_END) (half-open, microsecond exact)."""
    if W3_START_US <= t_ms * 1000 < W3_END_US:
        raise LG.W3SealedError(f"{what} {t_ms} lies inside the sealed holdout W3; refused")


def book_ref(sym, b):
    return None if b is None else f"bt|{sym}|{b[7]}|c{b[11]}|t{b[1]}"


def depth_ref(sym, d):
    return None if d is None else f"dp{d[5]}|{sym}|{d[6]}|c{d[10]}|t{d[1]}"


# ---------------------------------------------------------------- slippage models ------
def depth_walk(d, side: int, notional: float) -> tuple:
    """(result dict, None) or (None, reason). Relative to the snapshot's own level 1; never extrapolated."""
    if d is None:
        return None, "no_depth_state"
    levels = d[4] if side > 0 else d[3]
    other = d[3] if side > 0 else d[4]
    if not levels:
        return None, "empty_depth_side"
    for p, qty in levels:
        if p <= 0 or qty < 0:
            return None, "invalid_depth_ladder"
    ps = [p for p, _ in levels]
    if any((b <= a) if side > 0 else (b >= a) for a, b in zip(ps, ps[1:])):
        return None, "invalid_depth_ladder"
    if other and ((other[0][0] >= levels[0][0]) if side > 0 else (other[0][0] <= levels[0][0])):
        return None, "crossed_depth_snapshot"
    l1 = levels[0][0]
    displayed = sum(p * qty for p, qty in levels)
    if side > 0:
        remaining, base, used = notional, 0.0, 0
        for p, qty in levels:
            if remaining <= notional * 1e-12:
                break
            take = min(qty, remaining / p)
            if take > 0:
                base += take
                remaining -= take * p
                used += 1
        if remaining > notional * 1e-9:
            return None, "notional_exceeds_displayed_depth"
        vwap = notional / base
    else:
        target = notional / l1
        remaining, proceeds, used = target, 0.0, 0
        for p, qty in levels:
            if remaining <= target * 1e-12:
                break
            take = min(qty, remaining)
            if take > 0:
                proceeds += take * p
                remaining -= take
                used += 1
        if remaining > target * 1e-9:
            return None, "notional_exceeds_displayed_depth"
        base, vwap = target, proceeds / target
    if used == 1:
        vwap = l1                                        # filled entirely at level 1: exactly zero walk slippage
    s = side * (vwap - l1) / l1
    return {"depth_levels": d[5], "n_side": len(levels), "levels_used": used, "displayed_notional": rnd(displayed),
            "filled_base_qty": rnd(base), "vwap": rnd(vwap), "depth_l1": l1, "s": s if s > 0 else 0.0}, None


def _slippage(C, model_ids, depth, side, notional):
    """(s fraction or None, provenance, reason, depth_walk info)."""
    total, provs, walk = 0.0, [], None
    for mid in model_ids:
        m = C.model(mid, "slippage_models")
        if m["kind"] in ("touch_only", "fixed_stress"):
            total += m["bps_per_side"] / 1e4
            provs.append(m["provenance"])
        elif m["kind"] == "displayed_depth_walk":
            walk, why = depth_walk(depth, side, notional)
            if walk is None:
                return None, UNAVAILABLE, why, None
            total += walk["s"]
            provs.append(m["provenance"])
        else:
            raise ExecutionError(f"unknown slippage kind {m['kind']}")
    return total, weakest(*provs), None, walk


# ---------------------------------------------------------------- leg estimate ------
def _book_quantities(b, ok):
    if b is None or not ok:
        why = "no_book_state" if b is None else "book_state_invalid"
        return na(why), na(why), na(why)
    return q(b[3], MEASURED), q(b[4], MEASURED), q((b[3] + b[4]) / 2, DERIVED)


def _ageq(cls, key):
    v = cls.get(key) if cls else None
    return q(v, DERIVED) if v is not None else na("not_computable")


def estimate_leg(state, instrument, side: str, order_notional: float, decision_time_ms: int, scenario_id: str,
                 contracts=None, fee_schedule_id: str | None = None, direction: str = "long") -> dict:
    """One execution leg under a frozen scenario. ``state`` is a ForwardMarketState (any source)."""
    C = contracts or CT.default()
    if direction != "long":
        raise UnsupportedDirection(f"direction {direction!r} is not authorized (long-only, Binance spot)")
    if side not in SIDES:
        raise ExecutionError(f"side must be buy|sell, got {side!r}")
    if isinstance(order_notional, bool) or not isinstance(order_notional, (int, float)) or not order_notional > 0:
        raise ExecutionError("order_notional must be a positive number (input, never optimized)")
    if not isinstance(instrument, IN.Instrument):
        raise ExecutionError("instrument must be a canonical p2_research.instrument.Instrument")
    IN.require_supported_market({"asset_class": instrument.asset_class, "venue": instrument.venue,
                                 "product": instrument.product, "calendar_id": instrument.calendar_id})
    sc = C.scenario(scenario_id)
    ex_m = C.model(sc["execution_model"], "execution_models")
    lat_m = C.model(sc["latency_model"], "latency_models")
    st_m = C.model(sc["stale_policy"], "stale_policies")
    dq_m = C.model(sc["data_quality_policy"], "data_quality_policies")
    fs = C.fee_schedule(fee_schedule_id or sc["fee_schedule"])
    sgn, leg = SIDES[side]
    T = int(decision_time_ms)
    L = int(lat_m["latency_ms"])
    TE = T + L
    require_outside_w3(T, "decision_time")
    require_outside_w3(TE, "execution_time")
    sym = instrument.symbol
    # ---- decision reference: a view truncated at T ----
    VD = PITMarketView(state, T)
    bd = VD.book(sym, T)
    cd = QL.classify(VD, "book", sym, T, bd)
    dbid, dask, dmid = _book_quantities(bd, cd["state"] != INVALID)
    # ---- execution state: a view truncated at T + latency ----
    VE = PITMarketView(state, TE)
    be = VE.book(sym, TE)
    ce = QL.classify(VE, "book", sym, TE, be)
    bid, ask, mid = _book_quantities(be, ce["state"] != INVALID)
    uses_depth = any(C.model(m, "slippage_models")["kind"] == "displayed_depth_walk" for m in sc["slippage_models"])
    de = VE.depth(sym, TE) if uses_depth else None
    cdep = QL.classify(VE, "depth", sym, TE, de) if uses_depth else None
    rate_bps, fee_prov, _ = CT.fee_rate_bps(fs, instrument.venue, instrument.product, "taker")
    f = rate_bps / 1e4
    fee_q = q(rate_bps, fee_prov)
    walk = None
    if ce["state"] == INVALID:
        why = "book_state_invalid:" + ",".join(x for x in ce["flags"] if x)
        touch = fill = spread = spread_bps = spread_cost = slip = inter = total = na(why)
    else:
        b, a = be[3], be[4]
        m = (a + b) / 2
        tch = a if sgn > 0 else b
        h = sgn * (tch - m) / m
        touch, spread = q(tch, MEASURED), q(a - b, DERIVED)
        spread_bps, spread_cost = q((a - b) / m * 1e4, DERIVED), q(h * 1e4, DERIVED)
        if cdep is not None and cdep["state"] == INVALID:
            s, sprov, swhy = None, UNAVAILABLE, "depth_state_invalid:" + ",".join(cdep["flags"])
        else:
            s, sprov, swhy, walk = _slippage(C, sc["slippage_models"], de, sgn, float(order_notional))
        if s is None:
            fill = slip = inter = total = na(swhy)
        else:
            fp = tch * (1 + sgn * s)
            tot = sgn * (fp * (1 + sgn * f) - m) / m
            fill, slip = q(fp, weakest(MEASURED, sprov)), q(s * 1e4, sprov)
            total = q(tot * 1e4, weakest(DERIVED, sprov, fee_prov))
            inter = q((tot - h - s - f) * 1e4, weakest(DERIVED, sprov, fee_prov))
    if walk is not None:
        walk = dict(walk)
        walk.pop("s")
        walk["depth_book_l1_diff_bps"] = rnd(sgn * (walk["depth_l1"] - (be[4] if sgn > 0 else be[3])) / mid["value"] * 1e4)
        walk["depth_minus_book_seq"] = (de[6] - be[7]) if isinstance(de[6], int) and isinstance(be[7], int) else None
        if walk["n_side"] < walk["depth_levels"]:
            cdep["flags"] = sorted(set(cdep["flags"]) | {"depth_incomplete"})
        if (walk["depth_l1"] <= be[3]) if sgn > 0 else (walk["depth_l1"] >= be[4]):
            cdep["flags"] = sorted(set(cdep["flags"]) | {"depth_book_inconsistent"})       # depth L1 crosses the touch
    if dmid["value"] is not None and mid["value"] is not None:
        drift = q(sgn * (mid["value"] - dmid["value"]) / dmid["value"] * 1e4, DERIVED)
    else:
        drift = na("decision_or_execution_book_unavailable")
    states = [ce["state"]] + ([cdep["state"]] if cdep is not None else [])
    comps = [spread_cost["provenance"], fee_q["provenance"], slip["provenance"]]
    rec = {
        "record": RECORD, "record_version": RECORD_VERSION, "kind": "leg",
        "scenario": {"id": sc["id"], "version": sc["version"]},
        "models": {"execution": C.ref(ex_m["id"]), "latency": C.ref(lat_m["id"]),
                   "slippage": [C.ref(x) for x in sc["slippage_models"]],
                   "fee_schedule": {"id": fs["id"], "version": fs["version"]},
                   "stale_policy": C.ref(st_m["id"]), "data_quality_policy": C.ref(dq_m["id"])},
        "contract_set_sha256": C.sha256,
        "market_data": dict(state.meta),
        "instrument": instrument.as_dict(), "tier": be[10] if be is not None else None,
        "direction": direction, "side": side, "leg": leg, "liquidity_role": "taker",
        "order_notional": {"value": rnd(float(order_notional)), "currency": instrument.quote_currency},
        "decision_time_ms": T, "execution_time_ms": TE, "latency_ms": q(L, lat_m["provenance"]),
        "decision_bid": dbid, "decision_ask": dask, "decision_mid": dmid,
        "bid": bid, "ask": ask, "mid": mid, "touch": touch, "fill": fill,
        "spread": spread, "spread_bps": spread_bps, "spread_cost_bps": spread_cost, "fee_bps": fee_q,
        "slippage_bps": slip, "interaction_bps": inter, "total_cost_bps": total, "latency_drift_bps": drift,
        "adverse_selection_bps": na("future_research_label_not_computed_in_x0"),
        "market_impact_bps": na("refused_unsupported_by_data"),
        "gross_return": na("leg_only"), "net_return": na("leg_only"),
        "market_data_age": {"book_quote_age_ms": _ageq(ce, "quote_age_ms"),
                            "book_confirmation_gap_ms": _ageq(ce, "confirmation_gap_ms"),
                            "depth_quote_age_ms": _ageq(cdep, "quote_age_ms") if cdep else na("depth_not_used_by_scenario"),
                            "depth_confirmation_gap_ms": _ageq(cdep, "confirmation_gap_ms") if cdep else na("depth_not_used_by_scenario"),
                            "decision_book_quote_age_ms": _ageq(cd, "quote_age_ms"),
                            "connection_event_age_ms": _ageq(ce, "connection_event_age_ms")},
        "data_quality": {"state": worst_state(*states),
                         "book": {k: ce[k] for k in ("state", "staleness", "confirmation", "flags")},
                         "depth": {k: cdep[k] for k in ("state", "staleness", "confirmation", "flags")} if cdep else None,
                         "decision_book": {k: cd[k] for k in ("state", "staleness", "confirmation", "flags")}},
        "cost_provenance": UNAVAILABLE if total["provenance"] == UNAVAILABLE else weakest(*comps),
        "depth_walk": walk,
        "source_refs": {"decision_book": book_ref(sym, bd), "book": book_ref(sym, be), "depth": depth_ref(sym, de)},
    }
    return with_id(rec)


# ---------------------------------------------------------------- round trip ------
def round_trip(entry: dict, exit_: dict) -> dict:
    """Long round trip from an entry (buy) leg and a later exit (sell) leg of the same instrument and scenario."""
    if entry.get("leg") != "entry" or exit_.get("leg") != "exit":
        raise ExecutionError("round_trip needs an entry (buy) leg and an exit (sell) leg")
    if entry["instrument"] != exit_["instrument"] or entry["scenario"] != exit_["scenario"]:
        raise ExecutionError("legs differ in instrument or scenario")
    if exit_["decision_time_ms"] <= entry["decision_time_ms"] or exit_["execution_time_ms"] <= entry["execution_time_ms"]:
        raise ExecutionError("exit must come strictly after entry")
    fe, fx = entry["fee_bps"]["value"], exit_["fee_bps"]["value"]
    if entry["fill"]["value"] is None or exit_["fill"]["value"] is None:
        net = na("leg_fill_unavailable")
    else:
        eff_in = entry["fill"]["value"] * (1 + fe / 1e4)
        eff_out = exit_["fill"]["value"] * (1 - fx / 1e4)
        net = q(eff_out / eff_in - 1, weakest(entry["cost_provenance"], exit_["cost_provenance"]))
    if entry["mid"]["value"] is None or exit_["mid"]["value"] is None:
        gross = na("leg_mid_unavailable")
    else:
        gross = q(exit_["mid"]["value"] / entry["mid"]["value"] - 1, DERIVED)
    rec = {"record": RECORD, "record_version": RECORD_VERSION, "kind": "round_trip",
           "entry_estimate_id": entry["estimate_id"], "exit_estimate_id": exit_["estimate_id"],
           "scenario": entry["scenario"], "instrument": entry["instrument"], "direction": "long",
           "order_notional": entry["order_notional"], "entry_decision_time_ms": entry["decision_time_ms"],
           "exit_decision_time_ms": exit_["decision_time_ms"], "gross_return": gross, "net_return": net,
           "entry_total_cost_bps": entry["total_cost_bps"], "exit_total_cost_bps": exit_["total_cost_bps"],
           "cost_provenance": weakest(entry["cost_provenance"], exit_["cost_provenance"]),
           "data_quality_state": worst_state(entry["data_quality"]["state"], exit_["data_quality"]["state"])}
    return with_id(rec)


def canonical_line(rec: dict) -> str:
    return canon(rec)
