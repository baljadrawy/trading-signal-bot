"""Market/regime MEASUREMENT primitives (RM0-REGIME 1.0.0): direction, breadth, volatility, liquidity condition over
the universe known at T. No named states in v1, never a trading rule.
"""
from __future__ import annotations

import math
import statistics

from . import stats as ST
from . import values as V


def _median_mv(vals: list, n_universe: int, what: str) -> dict:
    need = (n_universe + 1) // 2
    if n_universe == 0:
        return V.na("no_universe_known_at_t")
    if len(vals) < max(1, need):
        return V.na(f"coverage_{len(vals)}_of_{n_universe}_below_half:{what}", V.INSUFFICIENT_HISTORY)
    return V.mv(statistics.median(sorted(vals)), V.DERIVED)


def _share_mv(num: int, den: int, n_universe: int, what: str) -> dict:
    need = (n_universe + 1) // 2
    if n_universe == 0:
        return V.na("no_universe_known_at_t")
    if den < max(1, need):
        return V.na(f"coverage_{den}_of_{n_universe}_below_half:{what}", V.INSUFFICIENT_HISTORY)
    return V.mv(num / den, V.DERIVED)


def window_return(view, sym: str, n_bars: int, bar_ms: int):
    E = ST.last_closed_open(view.T, bar_ms)
    bars, _ = view.closed_candles(sym, "15m", E - n_bars * bar_ms, E)
    a, b = bars.get(E - n_bars * bar_ms), bars.get(E)
    if a is None or b is None or not (a[4] > 0 and b[4] > 0):
        return None
    return math.log(b[4] / a[4])


def primitives(view, C, series_cache, liq_cache) -> dict:
    bar = C.bar_ms
    tiers = view.tiers()
    syms = sorted(tiers)
    n = len(syms)
    vol = C.vol
    out = {"named_state": None, "named_states_policy": "NONE_IN_V1", "universe_size": n,
           "universe_id": (view.epoch() or {}).get("universe_id")}
    for L in (16, 96):
        rs = {s: window_return(view, s, L, bar) for s in syms}
        vals = [v for v in rs.values() if v is not None]
        out[f"direction_median_logret_{L}x15m"] = _median_mv(vals, n, f"logret_{L}")
        if L == 16:
            out["breadth_positive_share_16x15m"] = _share_mv(sum(1 for v in vals if v > 0), len(vals), n, "breadth_16")
        btc = window_return(view, "BTCUSDT", L, bar) if "BTCUSDT" in tiers else None
        out[f"btc_logret_{L}x15m"] = V.mv(btc, V.DERIVED) if btc is not None else V.na("btc_window_bars_unavailable")
    sl, ss, ratios = [], [], []
    for s in syms:
        a = series_cache(s, vol["lookback_long_returns"])
        b = series_cache(s, vol["lookback_short_returns"])
        x = ST.stdev(list(a.rets.values())) if a.present >= vol["min_obs_long"] else None
        y = ST.stdev(list(b.rets.values())) if b.present >= vol["min_obs_short"] else None
        if x is not None:
            sl.append(x)
        if y is not None:
            ss.append(y)
        if x and y is not None:
            ratios.append(y / x)
    out["median_sigma_15m_long"] = _median_mv(sl, n, "sigma_long")
    out["median_sigma_15m_short"] = _median_mv(ss, n, "sigma_short")
    out["median_vol_ratio_short_long"] = _median_mv(ratios, n, "vol_ratio")
    spreads, ages, ok_book, ok_depth = [], [], 0, 0
    for s in syms:
        lb = liq_cache(s)
        if lb["book_ok"]:
            ok_book += 1
            spreads.append(lb["spread_bps"])
        if lb["depth_ok"]:
            ok_depth += 1
            ages.append(lb["depth_age_ms"])
    out["median_spread_bps"] = _median_mv(spreads, n, "spread")
    out["share_book_not_invalid"] = V.mv(ok_book / n, V.DERIVED) if n else V.na("no_universe_known_at_t")
    out["share_depth_not_invalid"] = V.mv(ok_depth / n, V.DERIVED) if n else V.na("no_universe_known_at_t")
    out["median_depth_age_ms"] = _median_mv(ages, n, "depth_age")
    return out
