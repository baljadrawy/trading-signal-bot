"""Displayed-liquidity measures at the snapshot time (RM0-LIQ 1.0.0), reusing the frozen P2-X v2 primitives:
X1-STALE-POLICY / X1-DQ (``execution.quality.classify``) and X1-S2-DEPTHWALK (``execution.model.depth_walk``).

This is NOT impact: the walk consumes the displayed ladder of one sampled snapshot; impact, realized slippage and
fill probability stay UNAVAILABLE (P2-X truth boundary). Zero latency at T: not an EXEC-* scenario.
"""
from __future__ import annotations

import math

from ..execution import model as XM
from . import values as V

DQ_STALENESS_DEGRADED = ("book_age_degraded", "depth_age_degraded")
DQ_NON_STALENESS = ("collector_not_healthy", "clock_suspect", "book_confirmation_degraded",
                    "depth_confirmation_degraded", "stream_recovered_after_not_observing",
                    "quote_predates_connection_event", "no_health_record_in_run")


def _state_from_dq(cls: dict) -> tuple:
    """Map a P2-X classification to an RM0 (state, flags). INVALID -> UNAVAILABLE."""
    if cls["state"] == "INVALID":
        return V.ST_UNAVAILABLE, set()
    flags = set()
    if cls["staleness"] != "VALID":
        flags.add(V.STALE_INPUT)
    if any(f in DQ_NON_STALENESS for f in cls["flags"]):
        flags.add(V.DEGRADED_INPUT)
    return V.worst(*flags) if flags else V.VALID, flags


def position_liquidity(view, p, tier, refs: dict) -> dict:
    sym = p.symbol
    b = view.book(sym)
    cb = view.classify("book", sym, b)
    d = view.depth(sym)
    cd = view.classify("depth", sym, d)
    bst, bfl = _state_from_dq(cb)
    dst, dfl = _state_from_dq(cd)
    out = {"tier": tier, "book_dq": {k: cb[k] for k in ("state", "staleness", "confirmation", "flags")},
           "depth_dq": {k: cd[k] for k in ("state", "staleness", "confirmation", "flags")},
           "book_record_tier": b[10] if b is not None else None, "depth_record_tier": d[9] if d is not None else None}
    if bst == V.ST_UNAVAILABLE:
        why = "book_state_invalid:" + ",".join(cb["flags"])
        out["spread_bps"] = V.na(why)
        out["book_quote_age_ms"] = V.na(why)
        out["half_spread_cost_ccy"] = V.na(why)
    else:
        bid, ask = b[3], b[4]
        m = (bid + ask) / 2
        sb = (ask - bid) / m * 1e4
        out["spread_bps"] = V.mv(sb, V.DERIVED, bst, flags=bfl)
        out["book_quote_age_ms"] = V.mv(cb["quote_age_ms"], V.DERIVED, bst, flags=bfl)
        out["half_spread_cost_ccy"] = V.mv(p.notional * sb / 2 / 1e4, V.DERIVED, bst, flags=bfl)
    side = -1 if p.side == "long" else 1                       # liquidation: long sells into bids
    if dst == V.ST_UNAVAILABLE:
        why = "depth_state_invalid:" + ",".join(cd["flags"])
        out["depth_age_ms"] = V.na(why)
        out["displayed_side_notional"] = V.na(why)
        out["utilization"] = V.na(why)
        out["depth_sufficiency"] = "UNAVAILABLE"
        out["depth_refusal"] = why
    else:
        out["depth_age_ms"] = V.mv(cd["quote_age_ms"], V.DERIVED, dst, flags=dfl)
        lv = d[3] if side < 0 else d[4]
        disp = math.fsum(px * qt for px, qt in lv)
        if disp > 0:
            out["displayed_side_notional"] = V.mv(disp, V.DERIVED, dst, flags=dfl)
            out["utilization"] = V.mv(p.notional / disp, V.DERIVED, dst, flags=dfl)
        else:
            out["displayed_side_notional"] = V.na("empty_depth_side")
            out["utilization"] = V.na("empty_depth_side")
        walk, why = XM.depth_walk(d, side, p.notional)
        if walk is None:
            out["depth_sufficiency"] = ("BEYOND_DISPLAYED_DEPTH" if why == "notional_exceeds_displayed_depth"
                                        else "UNAVAILABLE")
            out["depth_refusal"] = why
        else:
            out["depth_sufficiency"] = "SUFFICIENT"
            out["depth_refusal"] = None
            out["depth_levels_used"] = walk["levels_used"]
    out["market_impact"] = V.na("refused_unsupported_by_data:p2x_truth_boundary")
    weak, why_weak = None, []
    if out["depth_sufficiency"] == "BEYOND_DISPLAYED_DEPTH":
        why_weak.append("beyond_displayed_depth")
    if not V.is_null(out["utilization"]) and out["utilization"]["value"] >= refs["weak_liquidity_utilization"]:
        why_weak.append("utilization_reference")
    if not V.is_null(out["spread_bps"]) and out["spread_bps"]["value"] >= refs["weak_liquidity_spread_bps"]:
        why_weak.append("spread_reference")
    known = out["depth_sufficiency"] != "UNAVAILABLE" and not V.is_null(out["spread_bps"])
    if why_weak:
        weak = True
    elif known:
        weak = False
    out["weak_liquidity"] = weak                                 # None = unknown (never folded into liquid)
    out["weak_reasons"] = why_weak
    if "depth_too_stale" in cd["flags"] or cd["staleness"] == "DEGRADED":
        out["stale_depth_policy"] = True
    elif cd["state"] == "INVALID":
        out["stale_depth_policy"] = None                         # unknown, never "fresh"
    else:
        out["stale_depth_policy"] = False
    out["depth_age_over_research_reference"] = (None if V.is_null(out["depth_age_ms"]) else
                                                out["depth_age_ms"]["value"] > refs["depth_age_research_reference_ms"])
    return out


def aggregate(per: dict, positions, refs: dict, mixed: bool = False) -> dict:
    """``mixed``: positions span more than one quote currency (D-RM0-2): every notional sum/weight is refused."""
    if mixed:
        MX = "mixed_quote_currencies_no_fx_conversion"
        return {"notional_weak_liquidity": V.na(MX), "notional_liquidity_unknown": V.na(MX),
                "notional_beyond_displayed_depth": V.na(MX),
                "positions_stale_depth_policy": sum(1 for p in positions if per[p.instrument_id]["stale_depth_policy"] is True),
                "positions_depth_age_over_research_reference": sum(
                    1 for p in positions if per[p.instrument_id]["depth_age_over_research_reference"] is True),
                "positions_depth_unavailable": sum(1 for p in positions if per[p.instrument_id]["depth_sufficiency"] == "UNAVAILABLE"),
                "market_impact": V.na("refused_unsupported_by_data:p2x_truth_boundary"),
                "weak_liquidity_share": V.na(MX), "weighted_spread_bps": V.na(MX), "half_spread_cost_ccy_total": V.na(MX)}
    G = math.fsum(p.notional for p in positions)
    weak = math.fsum(p.notional for p in positions if per[p.instrument_id]["weak_liquidity"] is True)
    unknown = math.fsum(p.notional for p in positions if per[p.instrument_id]["weak_liquidity"] is None)
    beyond = math.fsum(p.notional for p in positions if per[p.instrument_id]["depth_sufficiency"] == "BEYOND_DISPLAYED_DEPTH")
    out = {"notional_weak_liquidity": V.mv(weak, V.DERIVED),
           "notional_liquidity_unknown": V.mv(unknown, V.DERIVED),
           "notional_beyond_displayed_depth": V.mv(beyond, V.DERIVED),
           "positions_stale_depth_policy": sum(1 for p in positions if per[p.instrument_id]["stale_depth_policy"] is True),
           "positions_depth_age_over_research_reference": sum(
               1 for p in positions if per[p.instrument_id]["depth_age_over_research_reference"] is True),
           "positions_depth_unavailable": sum(1 for p in positions if per[p.instrument_id]["depth_sufficiency"] == "UNAVAILABLE"),
           "market_impact": V.na("refused_unsupported_by_data:p2x_truth_boundary")}
    if G <= 0:
        for k in ("weak_liquidity_share", "weighted_spread_bps", "half_spread_cost_ccy_total"):
            out[k] = V.na("flat_portfolio")
        return out
    if unknown > 0:
        out["weak_liquidity_share"] = V.na("liquidity_unknown_for_some_positions")
    else:
        out["weak_liquidity_share"] = V.mv(weak / G, V.DERIVED)
    sp = [per[p.instrument_id]["spread_bps"] for p in positions]
    out["weighted_spread_bps"] = V.combine(sp, lambda vs: math.fsum(p.notional * v for p, v in zip(positions, vs)) / G)
    hs = [per[p.instrument_id]["half_spread_cost_ccy"] for p in positions]
    out["half_spread_cost_ccy_total"] = V.combine(hs, lambda vs: math.fsum(vs))
    return out
