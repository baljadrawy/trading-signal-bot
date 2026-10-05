"""Quote staleness and data-quality classification (policies X0-STALE-COLLECTOR 1.0.0 and X0-DQ 1.0.0).

Every threshold comes from the collector's own semantics in the run record of the boot that wrote the record
(``semantics.stale_ms``; cadence from the record itself), never from returns. Fail closed: INVALID means the
execution price is UNAVAILABLE; nothing is bridged, interpolated or replaced by a fallback.
"""
from __future__ import annotations

from .. import reader as RD
from .schema import DEGRADED, INVALID, VALID

GAP_INFO_WINDOW_MS = 3_600_000


def limits(run: dict, kind: str, tier) -> tuple:
    """(hard_ms, soft_ms or None=cadence) for a stream, from the run record's stale_ms (SCHEMA.md defaults)."""
    st = (run or {}).get("stale_ms") or RD.DEFAULT_STALE
    if kind == "book":
        if tier == 0:
            return st.get("book_t0", 120_000), st.get("book_t0", 120_000)
        return st.get("book_t12_dead", 600_000), st.get("book_t12_suspect", 120_000)
    return (st.get("depth_by_tier") or {}).get(f"t{tier}", st.get("depth", 2_000)), None


def _stream_match(name, sym: str, kind: str) -> bool:
    s = str(name).lower()
    if not s.startswith(sym.lower() + "@"):
        return False
    return "bookticker" in s if kind == "book" else "@depth" in s


def _conn_relevant(payload, kind: str) -> bool:
    conn = str((payload or {}).get("conn") or "").lower()
    if "book" in conn:
        return kind == "book"
    if "depth" in conn:
        return kind == "depth"
    return True                                          # unknown connection name: assume it affects every stream


def classify(view, kind: str, sym: str, t: int, rec) -> dict:
    """Quality of the PIT-selected record ``rec`` of stream (kind, sym) used at time ``t`` (view horizon >= t)."""
    inv, deg, info = [], [], []
    out = {"state": INVALID, "staleness": "MISSING", "confirmation": "MISSING", "flags": [], "quote_age_ms": None,
           "confirmation_gap_ms": None, "connection_event_age_ms": None, "hard_limit_ms": None, "soft_limit_ms": None}
    run = view.run_at(t)
    if rec is None:
        inv.append(f"no_{kind}_state")
    if run is None:
        inv.append("no_run_at_time")
    if inv:
        out["flags"] = sorted(inv)
        return out
    if rec[-1] != run["boot8"] or rec[2] < run["ws_start_ms"]:
        inv.append("from_previous_run")
    tier, cad = rec[-3], rec[-2]
    hard, soft = limits(run, kind, tier)
    soft = cad if soft is None else soft
    out["hard_limit_ms"], out["soft_limit_ms"] = hard, soft
    age = t - rec[2]
    out["quote_age_ms"] = age
    if age > hard:
        inv.append(f"{kind}_too_stale")
        out["staleness"] = "TOO_STALE"
    elif age > soft:
        deg.append(f"{kind}_age_degraded")
        out["staleness"] = DEGRADED
    else:
        out["staleness"] = VALID
    ls = view.last_sample(kind, sym, t)
    if ls is None or ls < run["ws_start_ms"]:
        inv.append(f"{kind}_stream_missing")
    else:
        gap = t - ls
        out["confirmation_gap_ms"] = gap
        if gap > 3 * cad:
            inv.append(f"{kind}_stream_missing")
        elif gap > cad:
            deg.append(f"{kind}_confirmation_degraded")
            out["confirmation"] = DEGRADED
        else:
            out["confirmation"] = VALID
    if kind == "book":
        bid, ask = rec[3], rec[4]
        if bid <= 0 or ask <= 0:
            inv.append("non_positive_price")
        elif bid >= ask:
            inv.append("crossed_or_locked_book")
    h = view.health(t)
    if h is None or h[0] < run["ws_start_ms"]:
        deg.append("no_health_record_in_run")
    else:
        if h[1] != "HEALTHY":
            deg.append("collector_not_healthy")
        if any(_stream_match(s, sym, kind) for s in h[2]):
            (deg if rec[2] > h[0] else inv).append(
                "stream_recovered_after_not_observing" if rec[2] > h[0] else "stream_not_observing")
    ev = [x[0] for x in view.connection_events(t, run["boot8"]) if x[0] >= run["ws_start_ms"] and _conn_relevant(x[2], kind)]
    last = max(ev) if ev else run["ws_start_ms"]
    out["connection_event_age_ms"] = t - last
    if ev and rec[2] < last:
        deg.append("quote_predates_connection_event")
    clk = view.clock(t)
    if rec[-4] or (clk is not None and clk[2]):
        deg.append("clock_suspect")
    if any(g["end_ms"] > t - GAP_INFO_WINDOW_MS for g in view.gaps_known(t, f"{kind}|{sym}")):
        info.append("gap_known_1h")
    if rec[-5]:
        info.append("unchanged")
    out["state"] = INVALID if inv else DEGRADED if deg else VALID
    out["flags"] = sorted(set(inv)) + sorted(set(deg)) + sorted(set(info))
    return out
