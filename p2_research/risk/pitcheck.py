"""PIT counterfactual transforms of a RiskMarket at a snapshot time T (used by tests and the real-data validation).

``truncate(M, T)``: everything available after T removed (books, depth, confirmation boundaries, candles, health,
lifecycle, clock, gaps, universe epochs). ``poison(M, T)``: every record available after T replaced by an absurd
version and absurd future records injected (books, crossed depth ladders, candles incl. a BTC vol spike and a
closed-but-not-yet-available bar, a late-announced and a future universe epoch, DEGRADED health, a rotation, a gap,
a clock-suspect probe). A PIT-safe snapshot at T is byte-identical on all three markets.
``perturb_past(M, T, sym)`` changes one PAST close (positive control: the snapshot must change).
"""
from __future__ import annotations

import copy

from ..execution import market_state as MS
from .market import RiskMarket, w3_masked


def _clone_state(S: MS.ForwardMarketState) -> MS.ForwardMarketState:
    N = MS.ForwardMarketState()
    N.query_times = S.query_times
    N.runs = [dict(r) for r in S.runs]
    N.epochs = [dict(e) for e in S.epochs]
    N.health, N.lifecycle, N.clock, N.gaps = list(S.health), list(S.lifecycle), list(S.clock), [dict(g) for g in S.gaps]
    N.meta = dict(S.meta)
    for kind in ("book", "depth"):
        src, dst = getattr(S, kind), getattr(N, kind)
        for sym, st in src.items():
            ns = MS._Stream()
            ns.keys, ns.recs = list(st.keys), list(st.recs)
            dst[sym] = ns
    N.conf = {k: (list(a), list(b)) for k, (a, b) in S.conf.items()}
    for k in ("downtime", "range_start_ms", "range_end_ms"):
        if hasattr(S, k):
            setattr(N, k, getattr(S, k))
    return N


def _market(M: RiskMarket, S, candles) -> RiskMarket:
    N = RiskMarket(S, candles)
    N.meta = dict(M.meta)
    return N


def truncate(M: RiskMarket, T: int) -> RiskMarket:
    S = _clone_state(M.state)
    for kind in ("book", "depth"):
        for sym, st in getattr(S, kind).items():
            keep = [(k, r) for k, r in zip(st.keys, st.recs) if r[0] <= T]
            st.keys, st.recs = [k for k, _ in keep], [r for _, r in keep]
    S.conf = {k: ([a for a, b in zip(ka, kb) if b <= T and a <= T], [b for a, b in zip(ka, kb) if b <= T and a <= T])
              for k, (ka, kb) in S.conf.items()}
    S.health = [h for h in S.health if h[0] <= T]
    S.lifecycle = [x for x in S.lifecycle if x[0] <= T]
    S.clock = [x for x in S.clock if x[0] <= T]
    S.gaps = [g for g in S.gaps if g["available_at_ms"] <= T]
    S.epochs = [e for e in S.epochs if e["available_at_ms"] <= T and e["effective_from_ms"] <= T]
    candles = {k: [c for c in v if c[8] <= T] for k, v in M.candles.items()}
    return _market(M, S, candles)


def _absurd_book(r, t):
    r = list(r)
    r[0] = r[2] = t
    r[3], r[4] = 9.0e8, 1.0e-3                                           # crossed, absurd
    return tuple(r)


def _absurd_depth(r, t):
    r = list(r)
    r[0] = r[2] = t
    r[3] = tuple((1.0e9 - i, 1.0e9) for i in range(5))
    r[4] = tuple((1.0e-6 + i * 1e-9, 1.0e-9) for i in range(5))
    return tuple(r)


def poison(M: RiskMarket, T: int, bar_ms: int = 900_000) -> RiskMarket:
    S = _clone_state(M.state)
    t1 = T + 1
    for kind, fn in (("book", _absurd_book), ("depth", _absurd_depth)):
        for sym, st in getattr(S, kind).items():
            st.recs = [fn(r, r[0]) if r[0] > T else r for r in st.recs]
            if st.recs:
                nr = fn(st.recs[-1], t1)
                i = sum(1 for k in st.keys if k <= t1)
                st.keys.insert(i, t1)
                st.recs.insert(i, nr)
    for k, (ka, kb) in list(S.conf.items()):
        i = sum(1 for x in ka if x <= t1)
        S.conf[k] = (ka[:i] + [t1] + ka[i:], kb[:i] + [t1] + kb[i:])
    streams = frozenset(f"{s.lower()}@bookTicker" for s in S.book) | frozenset(f"{s.lower()}@depth20" for s in S.depth)
    S.health = sorted(S.health + [(t1, "DEGRADED", streams, ("pit_poison",))], key=lambda h: h[0])
    run = S.run_at(T)
    boot8 = run["boot8"] if run else "00000000"
    S.lifecycle = sorted(S.lifecycle + [(t1, "ws_rotation", {"event": "ws_rotation", "conn": "all"}, boot8)],
                         key=lambda x: x[0])
    S.clock = sorted(S.clock + [(t1, t1 + 10_000_000, True)], key=lambda x: x[0])
    S.gaps = S.gaps + [{"available_at_ms": t1, "stream_key": f"book|{s}", "first_missing_ms": T - 600_000,
                        "last_missing_ms": T, "cadence_ms": 1000, "cause": "pit_poison", "causes": ["pit_poison"],
                        "day_split": False, "open_at_stop": False, "recoverability": None, "boot8": boot8,
                        "obs_id": f"poison|{s}", "end_ms": T + 1000} for s in sorted(S.book)]
    syms = sorted({k[0] for k in M.candles})
    late_tiers = {s: 2 for s in syms}
    late_tiers["ZZZPOISONUSDT"] = 0
    S.epochs = S.epochs + [
        {"effective_from_ms": T - 3_600_000, "available_at_ms": t1, "universe_id": "poison-late", "kind": "transition",
         "boot8": boot8, "tiers": late_tiers},
        {"effective_from_ms": t1, "available_at_ms": t1, "universe_id": "poison-future", "kind": "transition",
         "boot8": boot8, "tiers": {"ZZZPOISONUSDT": 0}}]
    S.epochs.sort(key=lambda e: (e["effective_from_ms"], e["available_at_ms"], e["universe_id"]))
    candles = {}
    E = ((T - bar_ms) // bar_ms) * bar_ms
    for (sym, tf), lst in M.candles.items():
        new = []
        for c in lst:
            if c[8] > T:
                c = (c[0], 1e9, 2e9, 1e-9, 1e9 if sym == "BTCUSDT" else 1e-9, 1e12, c[6], 1e12, c[8], True)
            new.append(c)
        if tf == "15m":
            opens = {c[0] for c in new}
            for o, avail in ((E + bar_ms, t1), (E + 2 * bar_ms, E + 3 * bar_ms + 1)):
                if o not in opens:
                    new.append((o, 1.0, 1e9, 1e-9, 1e9, 1e12, o + bar_ms - 1, 1e12, max(avail, o + bar_ms), True))
            if E not in opens:                                           # closed by T but announced only after T
                new.append((E, 1.0, 1e9, 1e-9, 1e9, 1e12, E + bar_ms - 1, 1e12, t1, True))
        candles[(sym, tf)] = sorted(new, key=lambda c: c[0])
    return _market(M, S, candles)


def perturb_past(M: RiskMarket, T: int, sym: str, bar_ms: int = 900_000) -> RiskMarket:
    """Positive control: multiply the close of the last closed, available, non-W3 bar by 1.5 (a PAST input).
    Returns None when no such bar exists (the control is then not applicable)."""
    candles = copy.copy(M.candles)
    lst = list(candles.get((sym, "15m"), []))
    idx = [i for i, c in enumerate(lst) if c[8] <= T and c[6] < T and not w3_masked(c[0], c[6])]
    if not idx:
        return None                                              # no eligible past bar: control not applicable
    c = lst[idx[-1]]
    lst[idx[-1]] = (c[0], c[1], c[2], c[3], c[4] * 1.5, c[5], c[6], c[7], c[8], c[9])
    candles[(sym, "15m")] = lst
    return _market(M, M.state, candles)


CONTROL_CONSUMERS = ("volatility.per_position.crypto:binance:spot:BTCUSDT.sigma_15m_short",
                     "volatility.per_position.crypto:binance:spot:BTCUSDT.sigma_15m_long",
                     "regime.btc_logret_16x15m", "regime.btc_logret_96x15m")


def control_consumers(snap: dict) -> list:
    """Reported metrics of ``snap`` that consume the BTC 15m bar perturbed by ``perturb_past`` and are non-null.
    Empty -> the positive control cannot change the snapshot and is NOT APPLICABLE (D-RM0-1)."""
    out = []
    for path in CONTROL_CONSUMERS:
        o = snap
        for part in path.split("."):
            o = o.get(part) if isinstance(o, dict) else None
        if isinstance(o, dict) and o.get("value") is not None:
            out.append(path)
    return out
