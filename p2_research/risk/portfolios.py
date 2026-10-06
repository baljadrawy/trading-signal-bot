"""Deterministic hypothetical portfolio fixtures P0-P7 (RM0-PORTFOLIOS 1.0.0). Test fixtures, not strategies.

Membership uses only the universe epoch known at T, alphabetical order and (P6) the displayed depth at T; never
returns, signals, P&L, trials, Paper or W3. A member without a usable PIT reference price is refused and recorded,
never substituted.
"""
from __future__ import annotations

import math

from .. import instrument as IN
from . import contracts as RC
from .position import normalize


def _ref_price(view, sym):
    b = view.book(sym)
    c = view.classify("book", sym, b)
    if b is None or c["state"] == "INVALID":
        return None, None, "book_state_invalid:" + ",".join(c["flags"])
    return (b[3] + b[4]) / 2, b[0], None


def _displayed_bid(view, sym):
    d = view.depth(sym)
    c = view.classify("depth", sym, d)
    if d is None or c["state"] == "INVALID":
        return None
    return math.fsum(px * qt for px, qt in d[3])


def _members(view, spec, tiers):
    by_tier = {}
    for s, t in tiers.items():
        by_tier.setdefault(t, []).append(s)
    for t in by_tier:
        by_tier[t].sort()
    picks, notes = [], []
    taken = set()
    for m in spec["members"]:
        r = m["rule"]
        if r == "symbol":
            cand = [m["symbol"]]
            if m["symbol"] not in tiers:
                notes.append({"symbol": m["symbol"], "reason": "not_in_universe_at_t"})
                continue
        elif r == "tier_first":
            ex = set(m.get("exclude_base") or [])
            cand = [s for s in by_tier.get(m["tier"], []) if IN.binance_spot_instrument(s).base_currency not in ex
                    and s not in taken][:m["n"]]
        elif r == "all_tiers_first":
            cand = [s for t in sorted(by_tier) for s in by_tier[t] if s not in taken][:m["n"]]
        elif r == "tier_weakest_displayed_bid":
            vals = []
            for s in by_tier.get(m["tier"], []):
                v = _displayed_bid(view, s)
                if v is None:
                    notes.append({"symbol": s, "reason": "depth_unavailable_not_eligible_for_p6_selection"})
                else:
                    vals.append((v, s))
            cand = [s for _, s in sorted(vals)[:m["n"]]]
        else:
            raise RC.RiskContractError(f"unknown fixture rule {r}")
        for s in cand:
            taken.add(s)
            picks.append((s, float(m["notional"])))
    return picks, notes


def build(pid: str, view, C=None) -> dict:
    """Return {"portfolio_id", "positions" (normalized tuple), "fixture_refusals", "selection_notes"}."""
    C = C or RC.default()
    spec = C.portfolios[pid]
    tiers = view.tiers()
    picks, notes = _members(view, spec, tiers)
    raws, refusals = [], []
    for sym, notional in picks:
        px, avail, why = _ref_price(view, sym)
        if px is None:
            refusals.append({"symbol": sym, "reason": why})
            continue
        ins = IN.binance_spot_instrument(sym)
        raws.append({"asset_class": ins.asset_class, "venue": ins.venue, "product": ins.product,
                     "instrument_id": ins.instrument_id, "symbol": sym, "quote_currency": ins.quote_currency,
                     "side": "long", "quantity": notional / px, "reference_price": px, "notional": notional,
                     "decision_time_ms": view.T, "reference_time_ms": avail,
                     "provenance": {"class": "SYNTHETIC_FIXTURE", "source": f"RM0-PORTFOLIOS@1.0.0:{pid}"}})
    positions, _ = normalize(raws)
    return {"portfolio_id": pid, "positions": positions, "fixture_refusals": sorted(refusals, key=lambda x: x["symbol"]),
            "selection_notes": sorted(notes, key=lambda x: (x["symbol"], x["reason"]))}
