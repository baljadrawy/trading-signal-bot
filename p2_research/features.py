"""Point-in-time feature engine (feature set v1). Labels are NOT reachable from here.

``PITView(bundle, T)`` is the only data access path for features. Every accessor refuses times after ``T``
(``PITViolation``) and only returns elements whose ``available_at_ms <= T``. Each feature returns
(value, feature_available_at_ms, null_reason); the builder re-checks ``feature_available_at <= T`` for every value.
Missing or uncertain inputs give ``None`` plus a reason; nothing is filled, interpolated or carried across runs.
"""
from __future__ import annotations

import math
import statistics

from .reader import TF_MS

MARKET_MAX_AGE_MS = 70_000                       # market cadence 60 s + stale limit 10 s
MIN_XS_SYMBOLS = 5
CONN_EVENTS = ("ws_connected", "ws_disconnected", "ws_connect_failed")


class PITViolation(Exception):
    pass


def rnd(v):
    return None if v is None else float(f"{v:.12g}")


class PITView:
    def __init__(self, bundle, T: int):
        self.B, self.T = bundle, T
        self.run = bundle.run_at(T)
        self.epoch = bundle.epoch_at(T)
        self._cc = {}

    def _guard(self, t):
        if t > self.T:
            raise PITViolation(f"access at {t} > decision time {self.T}")

    # ---------------- candles ----------------
    def closed(self, sym, tf, n):
        """Last ``n`` contiguous closed candles known at T (oldest first) or (None, reason)."""
        key = (sym, tf, n)
        if key in self._cc:
            return self._cc[key]
        L = TF_MS[tf]
        last_open = (self.T // L) * L - L
        self._guard(last_open + L - 1)
        store = self.B.candles.get((sym, tf), {})
        out, res = [], None
        for i in range(n):
            o = last_open - i * L
            c = store.get(o)
            if c is None or c[8] > self.T:
                if i == 0:
                    res = (None, "latest_closed_candle_unavailable")
                elif not any(k < o and v[8] <= self.T for k, v in store.items()):
                    res = (None, "insufficient_history")
                else:
                    res = (None, "candle_history_gap")
                break
            out.append(c)
        if res is None:
            res = (out[::-1], None)
        self._cc[key] = res
        return res

    # ---------------- sampled streams ----------------
    def latest(self, kind, sym, at=None):
        at = self.T if at is None else at
        self._guard(at)
        return self.B.latest(kind, sym, at)

    def window(self, kind, sym, lo, hi=None):
        hi = self.T if hi is None else hi
        self._guard(hi)
        return self.B.window(kind, sym, lo, hi)

    def gaps_known(self):
        return [g for g in self.B.gaps if g["available_at_ms"] <= self.T]

    def lifecycle_known(self, events):
        return [x for x in self.B.lifecycle if x[0] <= self.T and x[1] in events]


def _rets(cs):
    return [math.log(b[4] / a[4]) for a, b in zip(cs, cs[1:])]


def _sd(xs):
    return statistics.stdev(xs) if len(xs) >= 2 else None


class Out:
    def __init__(self, T):
        self.T, self.v, self.a, self.r = T, {}, {}, {}

    def set(self, fid, value, avail=None, reason=None):
        if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
            self.v[fid], self.a[fid], self.r[fid] = None, None, reason or "undefined"
        else:
            self.v[fid], self.a[fid] = rnd(value) if isinstance(value, float) else value, avail
            if fid in self.r:
                del self.r[fid]


def _cav(cs):
    return max(c[8] for c in cs)


def _candle_features(V: PITView, sym: str, o: Out):
    cs, why = V.closed(sym, "15m", 97)
    c17, w17 = V.closed(sym, "15m", 17)
    c8, w8 = V.closed(sym, "15m", 8)
    c2, w2 = V.closed(sym, "15m", 2)
    c1, w1 = V.closed(sym, "15m", 1)
    # 15m simple
    o.set("mom.ret_15m_1", math.log(c2[1][4] / c2[0][4]) if c2 else None, c2 and _cav(c2), w2)
    if c1:
        k = c1[0]
        rng = k[2] - k[3]
        o.set("mom.body_ratio_15m", (k[4] - k[1]) / rng if rng > 0 else None, k[8], None if rng > 0 else "zero_range")
        o.set("mom.range_rel_15m", rng / k[4], k[8])
    else:
        o.set("mom.body_ratio_15m", None, reason=w1)
        o.set("mom.range_rel_15m", None, reason=w1)
    for tf, fid in (("1h", "mom.ret_1h_1"), ("4h", "mom.ret_4h_1"), ("1d", "mom.ret_1d_1")):
        x, w = V.closed(sym, tf, 2)
        o.set(fid, math.log(x[1][4] / x[0][4]) if x else None, x and _cav(x), w)
    # 17-candle family
    if c17:
        r16 = _rets(c17)
        rv = _sd(r16)
        o.set("vol.rv_15m_16", rv, _cav(c17))
        lr = math.log(c17[-1][4] / c17[0][4])
        o.set("mom.mom_norm_15m_16", lr / (rv * 4) if rv else None, _cav(c17), None if rv else "zero_vol")
        prev_rng = [k[2] - k[3] for k in c17[:-1]]
        mr = sum(prev_rng) / len(prev_rng)
        o.set("vol.range_expansion_15m_16", (c17[-1][2] - c17[-1][3]) / mr if mr > 0 else None, _cav(c17),
              None if mr > 0 else "zero_range")
        mq = sum(k[7] for k in c17[:-1]) / 16
        if mq > 0:
            s = math.copysign(1.0, r16[-1]) if r16[-1] != 0 else 0.0
            o.set("act.volume_price_15m", s * math.log(1 + c17[-1][7] / mq), _cav(c17))
        else:
            o.set("act.volume_price_15m", None, reason="zero_volume")
    else:
        for fid in ("vol.rv_15m_16", "mom.mom_norm_15m_16", "vol.range_expansion_15m_16", "act.volume_price_15m"):
            o.set(fid, None, reason=w17)
    if c8:
        a, b = sum(k[7] for k in c8[4:]), sum(k[7] for k in c8[:4])
        o.set("act.volume_accel_15m_4", math.log(a / b) if a > 0 and b > 0 else None, _cav(c8),
              None if a > 0 and b > 0 else "zero_volume")
    else:
        o.set("act.volume_accel_15m_4", None, reason=w8)
    # 96/97-candle family
    if cs:
        last96 = cs[1:]
        o.set("mom.dist_high_15m_96", math.log(cs[-1][4] / max(k[2] for k in last96)), _cav(cs))
        o.set("mom.dist_low_15m_96", math.log(cs[-1][4] / min(k[3] for k in last96)), _cav(cs))
        r96 = _rets(cs)
        rv96, rv16 = _sd(r96), _sd(r96[-16:])
        o.set("vol.vol_ratio_15m_16_96", rv16 / rv96 if rv96 else None, _cav(cs), None if rv96 else "zero_vol")
        mq = sum(k[7] for k in cs[:-1]) / 96
        o.set("act.rel_volume_15m_96", cs[-1][7] / mq if mq > 0 else None, _cav(cs), None if mq > 0 else "zero_volume")
    else:
        for fid in ("mom.dist_high_15m_96", "mom.dist_low_15m_96", "vol.vol_ratio_15m_16_96", "act.rel_volume_15m_96"):
            o.set(fid, None, reason=why)
    # 1h family
    h25, w25 = V.closed(sym, "1h", 25)
    if h25:
        r = _rets(h25)
        o.set("vol.rv_1h_24", _sd(r), _cav(h25))
        path = sum(abs(x) for x in r)
        o.set("mom.trend_eff_1h_24", abs(math.log(h25[-1][4] / h25[0][4])) / path if path > 0 else None, _cav(h25),
              None if path > 0 else "zero_path")
    else:
        o.set("vol.rv_1h_24", None, reason=w25)
        o.set("mom.trend_eff_1h_24", None, reason=w25)
    h15, w15 = V.closed(sym, "1h", 15)
    if h15:
        trs = [max(b[2] - b[3], abs(b[2] - a[4]), abs(b[3] - a[4])) for a, b in zip(h15, h15[1:])]
        o.set("vol.atr_norm_1h_14", (sum(trs) / 14) / h15[-1][4], _cav(h15))
    else:
        o.set("vol.atr_norm_1h_14", None, reason=w15)


def _limits(V: PITView, tier):
    st = V.run["stale_ms"]
    book = st.get("book_t0", 120_000) if tier == 0 else st.get("book_t12_dead", 600_000)
    suspect = st.get("book_t0", 120_000) if tier == 0 else st.get("book_t12_suspect", 120_000)
    depth = (st.get("depth_by_tier") or {}).get(f"t{tier}", st.get("depth", 2_000))
    return book, suspect, depth


def _usable(V, rec, at, limit):
    """(ok, reason) for a sampled record used at time ``at``."""
    if rec is None:
        return False, "no_observation"
    run = V.B.run_at(at)
    if run is None or rec[-1] != run["boot8"] or rec[2] < run["ws_start_ms"]:
        return False, "from_previous_run"
    if at - rec[2] > limit:
        return False, "stale"
    return True, None


def _spread(b):
    mid = (b[3] + b[4]) / 2
    return (b[4] - b[3]) / mid * 1e4 if mid > 0 and b[4] >= b[3] > 0 else None


def _micro_features(V: PITView, sym: str, tier, o: Out):
    T = V.T
    lb, ls, ld = _limits(V, tier)
    b = V.latest("book", sym)
    ok, why = _usable(V, b, T, lb)
    why = "book_stale" if why == "stale" else why
    sp = _spread(b) if ok else None
    if ok and sp is None:
        ok, why = False, "crossed_or_zero_book"
    o.set("liq.spread_bps", sp, b and b[0], why)
    if ok and b[5] + b[6] > 0:
        o.set("liq.tob_imbalance", (b[5] - b[6]) / (b[5] + b[6]), b[0])
    else:
        o.set("liq.tob_imbalance", None, reason=why or "empty_book")
    if ok:
        hist = [x for x in V.window("book", sym, T - 3_600_000) if x[-1] == b[-1]]
        sps = [s for s in (_spread(x) for x in hist) if s is not None]
        if len(sps) < 10:
            o.set("liq.spread_norm_1h", None, reason="insufficient_history")
        else:
            med = statistics.median(sps)
            o.set("liq.spread_norm_1h", sp / med if med > 0 else None, b[0], None if med > 0 else "zero_spread_median")
        b5 = V.latest("book", sym, T - 300_000)
        ok5, w5 = _usable(V, b5, T - 300_000, lb)
        s5 = _spread(b5) if ok5 and b5[-1] == b[-1] else None
        o.set("liq.spread_change_5m_bps", sp - s5 if s5 is not None else None, b[0],
              None if s5 is not None else ("book_stale" if w5 == "stale" else (w5 or "from_previous_run")))
    else:
        o.set("liq.spread_norm_1h", None, reason=why)
        o.set("liq.spread_change_5m_bps", None, reason=why)
    d = V.latest("depth", sym)
    okd, wd = _usable(V, d, T, ld)
    wd = "depth_stale" if wd == "stale" else wd
    tot = (d[3] + d[4]) if d else 0.0
    if okd and tot <= 0:
        okd, wd = False, "empty_book"
    o.set("liq.depth_imbalance_10", (d[3] - d[4]) / tot if okd else None, d and d[0], wd)
    o.set("liq.depth_concentration_10", d[5] / tot if okd else None, d and d[0], wd)
    if okd:
        d15 = V.latest("depth", sym, T - 900_000)
        ok15, w15 = _usable(V, d15, T - 900_000, ld)
        t15 = (d15[3] + d15[4]) if ok15 and d15[-1] == d[-1] else 0.0
        o.set("liq.liq_change_15m", math.log(tot / t15) if t15 > 0 else None, d[0],
              None if t15 > 0 else ("depth_stale" if w15 == "stale" else (w15 or "from_previous_run")))
    else:
        o.set("liq.liq_change_15m", None, reason=wd)
    # ---- data quality ----
    for fid, rec in (("dq.book_age_s", b), ("dq.depth_age_s", d)):
        if rec is None:
            o.set(fid, None, reason="no_observation")
        elif V.run is None or rec[-1] != V.run["boot8"]:
            o.set(fid, None, reason="from_previous_run")
        else:
            o.set(fid, (T - rec[2]) / 1000.0, rec[0])
    stale = (not ok and why != "crossed_or_zero_book") or (b is not None and T - b[2] > ls) or not okd
    av = [x[0] for x in (b, d) if x is not None]
    o.set("dq.stale_flag", 1 if stale else 0, max(av) if av else T)
    clk = [x for x in V.B.clock if x[0] <= T]
    cs = bool((clk and clk[-1][2]) or (ok and b[9]) or (okd and d[11]))
    av2 = av + ([clk[-1][0]] if clk else [])
    o.set("dq.clock_suspect", 1 if cs else 0, max(av2) if av2 else T)


def _quality_features(V: PITView, sym: str, o: Out):
    T = V.T
    keys = {f"book|{sym}", f"depth|{sym}", "market|ALL"} | {f"candle|{tf}|{sym}" for tf in TF_MS}
    gk = [g for g in V.gaps_known() if g["stream_key"] in keys and g["first_missing_ms"] <= T and g["end_ms"] > T - 3_600_000]
    o.set("dq.gap_known_1h", len(gk), max((g["available_at_ms"] for g in gk), default=T))
    if V.run is None:
        o.set("dq.reconnect_age_s", None, reason="no_run_at_T")
        o.set("dq.run_age_s", None, reason="no_run_at_T")
    else:
        ws = V.run["ws_start_ms"]
        ev = [x[0] for x in V.lifecycle_known(CONN_EVENTS) if x[3] == V.run["boot8"] and x[0] >= ws]
        last = max(ev) if ev else ws
        o.set("dq.reconnect_age_s", min((T - last) / 1000.0, 86400.0), last)
        o.set("dq.run_age_s", min((T - ws) / 1000.0, 2_592_000.0), ws)
    h = V.latest("health", None)
    if h is None or V.run is None or h[0] < V.run["ws_start_ms"]:
        o.set("dq.degraded_flag", None, reason="no_health_record")
    else:
        mine = any(str(s).split("@")[0].upper() == sym for s in h[2])
        o.set("dq.degraded_flag", 1 if (h[1] != "HEALTHY" or mine) else 0, h[0])


def market_context(V: PITView) -> dict:
    """Shared per-T context: {sym: r24} for universe-at-T symbols + avail, or reason."""
    m = V.latest("market", None)
    if m is None:
        return {"reason": "no_market_snapshot"}
    if V.T - m[2] > MARKET_MAX_AGE_MS:
        return {"reason": "market_stale"}
    if not m[3]:
        return {"reason": "market_startup_incomplete"}
    if V.epoch is None:
        return {"reason": "no_universe_epoch_known"}
    r = {s: math.log(c / op) for s, (c, op, q) in m[5].items() if s in V.epoch["tiers"] and c > 0 and op > 0}
    if len(r) < MIN_XS_SYMBOLS:
        return {"reason": "too_few_symbols"}
    av = max(m[0], V.epoch["available_at_ms"])
    vals = sorted(r.values())
    return {"r": r, "avail": av, "breadth": sum(1 for x in vals if x > 0) / len(vals),
            "median": statistics.median(vals), "disp": statistics.pstdev(vals)}


def compute(V: PITView, sym: str, ctx: dict, btc: dict) -> Out:
    o = Out(V.T)
    tier = V.epoch["tiers"][sym]
    o.set("ctx.tier", tier, V.epoch["available_at_ms"])
    _candle_features(V, sym, o)
    _micro_features(V, sym, tier, o)
    _quality_features(V, sym, o)
    for fid in ("ctx.btc_ret_1h_1", "ctx.btc_rv_1h_24"):
        o.set(fid, btc["v"][fid], btc["a"].get(fid), btc["r"].get(fid))
    if "reason" in ctx:
        for fid in ("ctx.breadth_24h", "ctx.universe_ret_24h_median", "ctx.universe_disp_24h", "ctx.xs_rank_ret_24h"):
            o.set(fid, None, reason=ctx["reason"])
    else:
        o.set("ctx.breadth_24h", ctx["breadth"], ctx["avail"])
        o.set("ctx.universe_ret_24h_median", ctx["median"], ctx["avail"])
        o.set("ctx.universe_disp_24h", ctx["disp"], ctx["avail"])
        rs = ctx["r"].get(sym)
        if rs is None:
            o.set("ctx.xs_rank_ret_24h", None, reason="symbol_absent")
        else:
            others = [x for s, x in ctx["r"].items() if s != sym]
            o.set("ctx.xs_rank_ret_24h", (sum(1 for x in others if x < rs) + 0.5 * sum(1 for x in others if x == rs))
                  / len(others), ctx["avail"])
    return o


def btc_context(V: PITView) -> dict:
    o = Out(V.T)
    h, w = V.closed("BTCUSDT", "1h", 25)
    h2, w2 = V.closed("BTCUSDT", "1h", 2)
    o.set("ctx.btc_ret_1h_1", math.log(h2[1][4] / h2[0][4]) if h2 else None, h2 and _cav(h2), w2)
    o.set("ctx.btc_rv_1h_24", _sd(_rets(h)) if h else None, h and _cav(h), w)
    return {"v": o.v, "a": o.a, "r": o.r}
