"""Deterministic RiskSnapshot (record ``tsb.p2rm.risk_snapshot`` v1, RM0-SNAPSHOT 1.0.0).

PIT market state -> hypothetical portfolio -> exposure engine -> metrics -> flags -> snapshot. No actions: the
``actions`` field is always empty; nothing is ordered, sized, limited, halted, resumed, notified or written.
Identical inputs give byte-identical canonical output (``canonical_line``) and the same ``snapshot_id``.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics

from ..execution import contracts_v2 as X2
from ..execution.market_state import PITViolation
from ..execution.schema import rnd
from . import contracts as RC
from . import drawdown as DD
from . import liquidity as LQ
from . import regime as RG
from . import stats as ST
from . import values as V
from .market import RiskView
from .position import normalize

RECORD, RECORD_VERSION = "tsb.p2rm.risk_snapshot", 1
NOT_IN_UNIVERSE = "NOT_IN_UNIVERSE_AT_T"
# D-RM0-2 (RM0-UNITS 1.1.0): a cross-position monetary or notional-weighted aggregate is VALID only when every
# position it aggregates has the same canonical quote currency. No FX conversion exists, none is invented.
MIXED = "mixed_quote_currencies_no_fx_conversion"
CAP_MISMATCH = "capital_currency_mismatch_no_fx_conversion"


class SnapshotInputError(ValueError):
    pass


class Context:
    """Per-(market, T) caches shared by every portfolio snapshotted at T (pure functions of market and T)."""

    def __init__(self, market, t_ms: int, C=None):
        self.C = C or RC.default()
        self.market = market
        self.view = RiskView(market, t_ms)
        self.T = self.view.T
        self._series, self._uliq = {}, {}
        self.tiers = self.view.tiers()

    def series(self, sym: str, n: int) -> ST.Series:
        k = (sym, n)
        if k not in self._series:
            self._series[k] = ST.series(self.view, sym, n, self.C.bar_ms)
        return self._series[k]

    def universe_liq(self, sym: str) -> dict:
        if sym not in self._uliq:
            v = self.view
            b = v.book(sym)
            cb = v.classify("book", sym, b)
            d = v.depth(sym)
            cd = v.classify("depth", sym, d)
            ok_b, ok_d = b is not None and cb["state"] != "INVALID", d is not None and cd["state"] != "INVALID"
            self._uliq[sym] = {"book_ok": ok_b, "spread_bps": ((b[4] - b[3]) / ((b[3] + b[4]) / 2) * 1e4) if ok_b else None,
                               "depth_ok": ok_d, "depth_age_ms": cd["quote_age_ms"] if ok_d else None}
        return self._uliq[sym]


def _utc(ms: int) -> str:
    d = dt.datetime.fromtimestamp(ms // 1000, tz=dt.timezone.utc) + dt.timedelta(milliseconds=ms % 1000)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def deep_round(o):
    if isinstance(o, float):
        return rnd(o)
    if isinstance(o, dict):
        return {k: deep_round(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [deep_round(v) for v in o]
    return o


def _capital(capital, C) -> dict:
    cap = dict(C.capital) if capital is None else dict(capital)
    if capital is not None:
        if cap.get("provenance") != C.capital["provenance_required"]:
            raise SnapshotInputError("capital must be an ASSUMED_HYPOTHETICAL input (never a private balance)")
    v = cap.get("value")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0 or v != v or v == float("inf"):
        raise SnapshotInputError("capital value must be a positive finite number")
    return {"value": v, "currency": cap.get("currency", "USDT"), "class": V.ASSUMED,
            "provenance": C.capital["provenance_required"]}


def _fs(xs) -> float:
    return math.fsum(xs)


# ------------------------------------------------------------------ blocks ------
def _exposure(ctx, ps, cap) -> dict:
    tiers = ctx.tiers
    quotes = sorted({p.quote_currency for p in ps})
    G = _fs(abs(p.signed_notional) for p in ps)
    out = {"basis": "reference_notional", "quote_currencies": quotes, "count": len(ps),
           "count_long": sum(1 for p in ps if p.side == "long"), "count_short": sum(1 for p in ps if p.side == "short")}
    if len(quotes) > 1:
        for k in ("gross", "net", "long", "short"):
            out[k] = V.na("mixed_quote_currencies_no_fx_conversion")
    else:
        out["gross"] = V.mv(G, V.DERIVED)
        out["net"] = V.mv(_fs(p.signed_notional for p in ps), V.DERIVED)
        out["long"] = V.mv(_fs(p.notional for p in ps if p.side == "long"), V.DERIVED)
        out["short"] = V.mv(_fs(p.notional for p in ps if p.side == "short"), V.DERIVED)

    def bd(keyf, refuse_mixed=False):
        acc = {}
        for p in ps:
            acc.setdefault(keyf(p), []).append(p)
        def one(v):
            # D-RM0-2: a cross-portfolio breakdown whose buckets may be in different currencies is unlabelled, so
            # it is refused as a whole when the portfolio is mixed (by_quote_currency is the valid partition).
            if (refuse_mixed and len(quotes) > 1) or len({p.quote_currency for p in v}) > 1:
                return {"gross": V.na(MIXED), "net": V.na(MIXED), "count": len(v)}
            return {"gross": V.mv(_fs(abs(p.signed_notional) for p in v), V.DERIVED),
                    "net": V.mv(_fs(p.signed_notional for p in v), V.DERIVED), "count": len(v)}
        return {str(k): one(v) for k, v in sorted(acc.items(), key=lambda kv: str(kv[0]))}
    out["by_symbol"] = bd(lambda p: p.symbol)
    out["by_tier"] = bd(lambda p: f"tier{tiers[p.symbol]}" if p.symbol in tiers else NOT_IN_UNIVERSE, refuse_mixed=True)
    out["by_venue"] = bd(lambda p: p.venue)
    out["by_quote_currency"] = bd(lambda p: p.quote_currency)
    marks = {}
    for p in ps:
        b = ctx.view.book(p.symbol)
        c = ctx.view.classify("book", p.symbol, b)
        if b is None or c["state"] == "INVALID":
            marks[p.instrument_id] = V.na("book_state_invalid:" + ",".join(c["flags"]))
        else:
            st, fl = LQ._state_from_dq(c)
            marks[p.instrument_id] = V.mv(p.sign * p.quantity * (b[3] + b[4]) / 2, V.DERIVED, st, flags=fl)
    out["mark_to_market_signed_notional_at_t"] = marks
    out["mark_to_market_net_at_t"] = (V.na(MIXED) if len(quotes) > 1 else
                                      V.combine([marks[p.instrument_id] for p in ps], _fs))
    refs = ctx.C.policy["count_references_documented_only"]["references"]
    out["count_references_documented_only"] = {k: {"reference": v, "headroom": v - len(ps)} for k, v in sorted(refs.items())}
    return out, (None if len(quotes) > 1 else G)


def _concentration(ctx, ps, G) -> dict:
    if G is None:
        return {k: V.na(MIXED) for k in ("largest_share", "top3_share", "hhi", "effective_n_notional", "tier_hhi")} | {
            "tier_shares": {}}
    if not ps or G <= 0:
        r = "flat_portfolio"
        return {k: V.na(r) for k in ("largest_share", "top3_share", "hhi", "effective_n_notional", "tier_hhi")} | {
            "tier_shares": {}}
    w = sorted((abs(p.signed_notional) / G for p in ps), reverse=True)
    hhi = _fs(x * x for x in w)
    tiers = ctx.tiers
    tg = {}
    for p in ps:
        k = f"tier{tiers[p.symbol]}" if p.symbol in tiers else NOT_IN_UNIVERSE
        tg[k] = tg.get(k, 0.0) + abs(p.signed_notional)
    ts = {k: tg[k] / G for k in sorted(tg)}
    return {"largest_share": V.mv(w[0], V.DERIVED), "top3_share": V.mv(_fs(w[:3]), V.DERIVED),
            "hhi": V.mv(hhi, V.DERIVED), "effective_n_notional": V.mv(1 / hhi, V.DERIVED),
            "effective_n_note": "notional-only count; ignores correlation, volatility and liquidity; not a number of independent bets",
            "tier_shares": {k: V.mv(v, V.DERIVED) for k, v in ts.items()},
            "tier_hhi": V.mv(_fs(v * v for v in ts.values()), V.DERIVED)}


def _sigma_mv(s: ST.Series, min_obs: int) -> dict:
    st, why, fl = s.state(min_obs)
    if why:
        return V.na(why, st, fl)
    sd = ST.stdev(list(s.rets.values()))
    return V.mv(sd, V.DERIVED, st, flags=fl)


def _volatility(ctx, ps, G):
    C, vol = ctx.C, ctx.C.vol
    L, Ls = vol["lookback_long_returns"], vol["lookback_short_returns"]
    uni = sorted(ctx.tiers)
    usig = [x for x in (ST.stdev(list(ctx.series(s, L).rets.values())) if ctx.series(s, L).present >= vol["min_obs_long"]
                        else None for s in uni) if x is not None]
    need = (len(uni) + 1) // 2
    if uni and len(usig) >= max(1, need):
        umed = V.mv(statistics.median(sorted(usig)), V.DERIVED)
    else:
        umed = V.na(f"universe_sigma_coverage_{len(usig)}_of_{len(uni)}_below_half", V.INSUFFICIENT_HISTORY)
    hv_mult, spike = C.refs["high_vol_multiple_of_universe_median"], C.refs["vol_spike_ratio"]
    per, sig1d = {}, {}
    for p in ps:
        sl, ss = ctx.series(p.symbol, L), ctx.series(p.symbol, Ls)
        a = _sigma_mv(sl, vol["min_obs_long"])
        b = _sigma_mv(ss, vol["min_obs_short"])
        if V.is_null(a):
            d1 = V.na(a["reason"], a["state"], a["flags"])
        else:
            d1 = V.mv(a["value"] * math.sqrt(96), V.ASSUMED, V.worst(a["state"], V.ASSUMED_INPUT),
                      flags=list(a["flags"]) + ["sqrt_time_scaling_assumed"])
        if V.is_null(a) or V.is_null(b):
            ratio = V.na("sigma_unavailable", V.worst(*(m["state"] for m in (a, b) if V.is_null(m))))
        elif a["value"] == 0:
            ratio = V.na("zero_long_sigma")
        else:
            ratio = V.mv(b["value"] / a["value"], V.DERIVED, V.worst(a["state"], b["state"]),
                         flags=set(a["flags"]) | set(b["flags"]))
        hv = None if (V.is_null(a) or V.is_null(umed)) else a["value"] >= hv_mult * umed["value"]
        vs = None if V.is_null(ratio) else ratio["value"] >= spike
        per[p.instrument_id] = {"sigma_15m_long": a, "sigma_15m_short": b, "sigma_1d_equiv": d1,
                                "vol_ratio_short_long": ratio, "n_returns_long": sl.present, "n_returns_short": ss.present,
                                "high_vol": hv, "vol_spike": vs}
        sig1d[p.instrument_id] = d1
    out = {"timeframe": "15m", "lookback_long_returns": L, "lookback_short_returns": Ls, "per_position": per,
           "universe_median_sigma_15m_long": umed}
    if G is None:
        out["notional_weighted_sigma_1d"] = V.na(MIXED)
        out["high_vol_notional_share"] = V.na(MIXED)
    elif not ps or G <= 0:
        out["notional_weighted_sigma_1d"] = V.na("flat_portfolio")
        out["high_vol_notional_share"] = V.na("flat_portfolio")
    else:
        out["notional_weighted_sigma_1d"] = V.combine([sig1d[p.instrument_id] for p in ps],
                                                      lambda vs: _fs(abs(p.signed_notional) / G * v for p, v in zip(ps, vs)))
        if any(per[p.instrument_id]["high_vol"] is None for p in ps):
            nulls = [umed] + [per[p.instrument_id]["sigma_15m_long"] for p in ps]
            out["high_vol_notional_share"] = V.na("high_vol_unknown_for_some_positions",
                                                  V.worst(*(m["state"] for m in nulls if V.is_null(m))))
        else:
            out["high_vol_notional_share"] = V.mv(_fs(abs(p.signed_notional) for p in ps if per[p.instrument_id]["high_vol"]) / G, V.DERIVED)
    return out, sig1d


def _pair(ctx, a: ST.Series, b: ST.Series, min_obs: int, kind: str = "corr") -> dict:
    xs, ys = ST.aligned(a.rets, b.rets)
    sa, _, fa = a.state(0)
    sb, _, fb = b.state(0)
    fl = set(fa) | set(fb)
    st = V.worst(sa, sb)
    if len(xs) < min_obs:
        return V.na(f"insufficient_history:{len(xs)}<{min_obs}", V.INSUFFICIENT_HISTORY, fl), len(xs), None
    if kind == "corr":
        r, why = ST.pearson(xs, ys)
        ci = ST.fisher_ci95(r, len(xs)) if r is not None else None
    else:
        r, why = ST.beta(xs, ys)
        ci = None
    if r is None:
        return V.na(why, V.ST_UNAVAILABLE, fl), len(xs), None
    return V.mv(r, V.DERIVED, st, flags=fl), len(xs), ci


def _correlation(ctx, ps, G) -> dict:
    cc = ctx.C.corr
    L, mo = cc["lookback_returns"], cc["min_obs"]
    pairs, vals = {}, []
    for i in range(len(ps)):
        for j in range(i + 1, len(ps)):
            a, b = ps[i], ps[j]
            m, n, ci = _pair(ctx, ctx.series(a.symbol, L), ctx.series(b.symbol, L), mo)
            pairs[f"{a.symbol}|{b.symbol}"] = {"rho": m, "n_obs": n, "ci95_descriptive": ci}
            vals.append((a, b, m))
    out = {"timeframe": "15m", "lookback_returns": L, "min_obs": mo, "pairs": pairs,
           "pair_coverage": {"pairs": len(vals), "available": sum(1 for *_, m in vals if not V.is_null(m))},
           "confidence_note": "Fisher-z 95% intervals are descriptive; <= 96 15m returns from about 1.4 days: no stable estimate"}
    if len(ps) < 2:
        r = "flat_portfolio" if not ps else "fewer_than_two_positions"
        for k in ("average_pairwise_weighted", "average_pairwise_unweighted", "max_pairwise"):
            out[k] = V.na(r)
        return out
    ms = [m for *_, m in vals]
    wts = [abs(a.signed_notional) * abs(b.signed_notional) for a, b, _ in vals]
    out["average_pairwise_weighted"] = (V.na(MIXED) if G is None else
                                        V.combine(ms, lambda vs: _fs(w * v for w, v in zip(wts, vs)) / _fs(wts)))
    out["average_pairwise_unweighted"] = V.combine(ms, lambda vs: _fs(vs) / len(vs))
    out["max_pairwise"] = V.combine(ms, max)
    return out


def _btc(ctx, ps, G) -> dict:
    C = ctx.C
    L, mo = C.corr["lookback_returns"], C.corr["min_obs"]
    ref_sym = C.btc_reference.split(":")[-1]
    rs = ctx.series(ref_sym, L)
    per, rhos, betas = {}, [], []
    for p in ps:
        s = ctx.series(p.symbol, L)
        rho, n, ci = _pair(ctx, s, rs, mo, "corr")
        bet, _, _ = _pair(ctx, s, rs, mo, "beta")
        per[p.instrument_id] = {"correlation_with_btc": rho, "beta_to_btc": bet, "n_obs": n, "ci95_descriptive": ci}
        rhos.append(rho)
        betas.append(bet)
    bps = [p for p in ps if p.base_currency == "BTC"]
    direct = _fs(abs(p.signed_notional) for p in bps)
    out = {"reference_instrument": C.btc_reference, "reference_choice_class": V.ASSUMED,
           "naming_rule": "correlation and beta are separate measures; correlation is never called beta",
           "per_position": per,
           "direct_btc_notional": (V.na(MIXED) if len({p.quote_currency for p in bps}) > 1 else V.mv(direct, V.DERIVED))}
    if G is None:
        for k in ("direct_btc_weight", "weighted_correlation_with_btc", "portfolio_beta_to_btc",
                  "btc_beta_equivalent_notional"):
            out[k] = V.na(MIXED)
        return out
    if not ps or G <= 0:
        for k in ("direct_btc_weight", "weighted_correlation_with_btc", "portfolio_beta_to_btc",
                  "btc_beta_equivalent_notional"):
            out[k] = V.na("flat_portfolio")
        return out
    out["direct_btc_weight"] = V.mv(direct / G, V.DERIVED)
    out["weighted_correlation_with_btc"] = V.combine(rhos, lambda vs: _fs(abs(p.signed_notional) / G * v for p, v in zip(ps, vs)))
    out["portfolio_beta_to_btc"] = V.combine(betas, lambda vs: _fs(p.signed_notional / G * v for p, v in zip(ps, vs)))
    out["btc_beta_equivalent_notional"] = V.combine(betas, lambda vs: _fs(p.signed_notional * v for p, v in zip(ps, vs)))
    return out


def _covariance(ctx, ps, G) -> dict:
    C = ctx.C
    L, mo = C.vol["lookback_long_returns"], C.vol["min_obs_long"]
    k = len(ps)
    req = max(mo, 5 * k)
    out = {"alignment": "common bars where every position has a return", "k": k, "n_required": req}
    keys = ("portfolio_sigma_1d_ccy", "portfolio_sigma_1d_fraction_of_gross", "diversification_ratio")
    if G is None:
        out["n_common"] = 0
        out.update({x: V.na(MIXED) for x in keys})
        out["euler_contribution"] = {p.instrument_id: V.na(MIXED) for p in ps}
        return out
    if k == 0 or G <= 0:
        out["n_common"] = 0
        out.update({x: V.na("flat_portfolio") for x in keys})
        out["euler_contribution"] = {}
        return out
    ser = [ctx.series(p.symbol, L) for p in ps]
    ks, rows = ST.common_matrix(ser)
    out["n_common"] = len(ks)
    fl = set()
    st = V.VALID
    for s in ser:
        s_st, _, s_fl = s.state(0)
        fl |= set(s_fl)
        st = V.worst(st, s_st)
    if len(ks) < req:
        why = f"covariance_condition_not_met:n_common={len(ks)}<{req}"
        out.update({x: V.na(why, V.INSUFFICIENT_HISTORY, fl) for x in keys})
        out["euler_contribution"] = {p.instrument_id: V.na(why, V.INSUFFICIENT_HISTORY, fl) for p in ps}
        return out
    S = ST.cov_matrix(rows)
    s = [p.signed_notional for p in ps]
    Ss = [_fs(S[i][j] * s[j] for j in range(k)) for i in range(k)]
    var_p = _fs(s[i] * Ss[i] for i in range(k))
    if not var_p > 0:
        why = "zero_portfolio_variance"
        out.update({x: V.na(why, V.ST_UNAVAILABLE, fl) for x in keys})
        out["euler_contribution"] = {p.instrument_id: V.na(why, V.ST_UNAVAILABLE, fl) for p in ps}
        return out
    sp = math.sqrt(var_p)
    sflag = list(fl) + ["sqrt_time_scaling_assumed"]
    out["portfolio_sigma_1d_ccy"] = V.mv(sp * math.sqrt(96), V.ASSUMED, V.worst(st, V.ASSUMED_INPUT), flags=sflag)
    out["portfolio_sigma_1d_fraction_of_gross"] = V.mv(sp * math.sqrt(96) / G, V.ASSUMED, V.worst(st, V.ASSUMED_INPUT), flags=sflag)
    sig = [math.sqrt(S[i][i]) for i in range(k)]
    out["diversification_ratio"] = V.mv(_fs(abs(s[i]) * sig[i] for i in range(k)) / sp, V.DERIVED, st, flags=fl)
    out["euler_contribution"] = {p.instrument_id: V.mv(s[i] * Ss[i] / var_p, V.DERIVED, st, flags=fl) for i, p in enumerate(ps)}
    return out


def _heat(ps, G, cap, sig1d) -> dict:
    C_ = cap["value"]
    quotes = sorted({p.quote_currency for p in ps})
    if G is None:
        return {"definition": "RM0-HEAT 1.0.0 (not a B3 limit; an ex-ante exposure measure)",
                "measured_exposure_gross": V.na(MIXED), "hypothetical_capital": V.mv(C_, V.ASSUMED, V.ASSUMED_INPUT),
                "exposure_heat": V.na(MIXED), "vol_heat_ccy": V.na(MIXED), "vol_heat": V.na(MIXED),
                "coverage": {"positions": len(ps), "with_sigma": sum(1 for p in ps if not V.is_null(sig1d[p.instrument_id]))},
                "exceeds_hypothetical_capital": None}
    cap_ok = not quotes or quotes == [cap["currency"]]
    vh = V.combine([sig1d[p.instrument_id] for p in ps], lambda vs: _fs(abs(p.signed_notional) * v for p, v in zip(ps, vs)),
                   cls_floor=V.ASSUMED) if ps else V.mv(0.0, V.DERIVED)
    out = {"definition": "RM0-HEAT 1.0.0 (not a B3 limit; an ex-ante exposure measure)",
           "measured_exposure_gross": V.mv(G, V.DERIVED),
           "hypothetical_capital": V.mv(C_, V.ASSUMED, V.ASSUMED_INPUT),
           "exposure_heat": V.mv(G / C_, V.ASSUMED, V.ASSUMED_INPUT) if cap_ok else V.na(CAP_MISMATCH),
           "vol_heat_ccy": vh,
           "vol_heat": (V.na(CAP_MISMATCH) if not cap_ok else V.na(vh["reason"], vh["state"], vh["flags"]) if V.is_null(vh) else
                        V.mv(vh["value"] / C_, V.ASSUMED, V.worst(vh["state"], V.ASSUMED_INPUT), flags=vh["flags"])),
           "coverage": {"positions": len(ps), "with_sigma": sum(1 for p in ps if not V.is_null(sig1d[p.instrument_id]))},
           "exceeds_hypothetical_capital": (G > C_) if cap_ok else None}
    return out


def _get(rec: dict, path: str):
    o = rec
    for part in path.split("."):
        if not isinstance(o, dict) or part not in o:
            return None
        o = o[part]
    return o


_OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<": lambda a, b: a < b, "<=": lambda a, b: a <= b}


def _flags(rec: dict, ps, C) -> list:
    out = []
    for tid in sorted(C.thresholds):
        t = C.thresholds[tid]
        m = _get(rec, t["metric"])
        if V.is_metric(m) and m["value"] is not None and _OPS[t["op"]](m["value"], t["value"]):
            out.append({"id": tid, "metric": t["metric"], "op": t["op"], "threshold": t["value"], "value": m["value"],
                        "class": "POLICY", "provenance": "ASSUMED", "calibrated": False})
    if rec["heat"]["exceeds_hypothetical_capital"]:
        out.append({"id": "RM0-S-EXCEEDS-CAPITAL", "class": "STRUCTURAL", "metric": "heat.exposure_heat"})
    if any(p.side == "short" for p in ps):
        out.append({"id": "RM0-S-SHORT-CONCEPTUAL-NOT-AUTHORIZED", "class": "STRUCTURAL", "metric": "exposure.short"})
    if len(rec["exposure"]["quote_currencies"]) > 1:
        out.append({"id": "RM0-S-MIXED-QUOTE-CURRENCIES", "class": "STRUCTURAL", "metric": "exposure.gross"})
    for p in ps:
        v = rec["volatility"]["per_position"][p.instrument_id]
        if v["vol_spike"]:
            out.append({"id": "RM0-P-VOL-SPIKE", "class": "POLICY", "provenance": "ASSUMED", "calibrated": False,
                        "metric": f"volatility.per_position.{p.instrument_id}.vol_ratio_short_long",
                        "threshold": C.refs["vol_spike_ratio"], "value": v["vol_ratio_short_long"]["value"]})
        if v["high_vol"]:
            out.append({"id": "RM0-P-HIGH-VOL", "class": "POLICY", "provenance": "ASSUMED", "calibrated": False,
                        "metric": f"volatility.per_position.{p.instrument_id}.sigma_15m_long",
                        "threshold": C.refs["high_vol_multiple_of_universe_median"], "value": v["sigma_15m_long"]["value"]})
    return sorted(out, key=lambda f: (f["id"], f["metric"]))


# ------------------------------------------------------------------ public ------
def build_snapshot(market_or_ctx, positions, snapshot_time_ms: int | None = None, capital=None, equity_curve=None,
                   C=None, duplicates: str = "reject", conceptual_short: bool = False, portfolio_meta=None) -> dict:
    """Build one RiskSnapshot. ``market_or_ctx`` is a RiskMarket (with ``snapshot_time_ms``) or a Context."""
    if isinstance(market_or_ctx, Context):
        ctx = market_or_ctx
        if snapshot_time_ms is not None and int(snapshot_time_ms) != ctx.T:
            raise SnapshotInputError("snapshot_time_ms differs from the context time")
    else:
        ctx = Context(market_or_ctx, snapshot_time_ms, C)
    C = ctx.C
    T = ctx.T
    ps, nlog = normalize(list(positions), duplicates, conceptual_short)
    for p in ps:
        if p.decision_time_ms > T or p.reference_time_ms > T:
            raise PITViolation(f"position {p.instrument_id} decision/reference time after the snapshot time {T}")
    cap = _capital(capital, C)
    tiers = ctx.tiers
    exposure, G = _exposure(ctx, ps, cap)
    vol, sig1d = _volatility(ctx, ps, G)
    cov = _covariance(ctx, ps, G)
    vol["portfolio_vol_proxy"] = {k: cov[k] for k in ("portfolio_sigma_1d_ccy", "portfolio_sigma_1d_fraction_of_gross")}
    vol["portfolio_vol_proxy"]["condition"] = {"k": cov["k"], "n_common": cov["n_common"], "n_required": cov["n_required"]}
    liq_per = {p.instrument_id: LQ.position_liquidity(ctx.view, p, tiers.get(p.symbol), C.refs) for p in ps}
    liq = {"per_position": liq_per, **LQ.aggregate(liq_per, ps, C.refs, mixed=G is None),
           "time_basis": "snapshot time T, zero latency (not an EXEC-* scenario; EXEC-BASE stays ASSUMED in P2-X)"}
    rec = {
        "record": RECORD, "record_version": RECORD_VERSION,
        "snapshot_time_ms": T, "snapshot_time_utc": _utc(T),
        "contracts": {"rm0_contract_set_sha256": C.sha256, "rm0_versions": C.versions(),
                      "rm0_units_amendment_sha256": RC.units_amendment_sha256(),
                      "p2x_contract_set_sha256": X2.default().sha256,
                      "p2x_policies": C.metrics["liquidity"]["p2x_reuse"]},
        "inputs": {"capital": cap, "duplicate_policy": duplicates, "conceptual_short": conceptual_short,
                   "normalization_log": nlog, "equity_curve_supplied": equity_curve is not None,
                   "portfolio": portfolio_meta},
        "positions": [dict(p.as_dict(), tier_at_t=tiers.get(p.symbol), signed_notional=p.signed_notional) for p in ps],
        "exposure": exposure,
        "heat": _heat(ps, G, cap, sig1d),
        "concentration": _concentration(ctx, ps, G),
        "volatility": vol,
        "correlation": _correlation(ctx, ps, G),
        "btc_exposure": _btc(ctx, ps, G),
        "liquidity": liq,
        "regime": RG.primitives(ctx.view, C, ctx.series, ctx.universe_liq),
        "drawdown": DD.drawdown(equity_curve, T),
        "actions": [],
    }
    tot = V.combine([sig1d[p.instrument_id] for p in ps],
                    lambda vs: _fs(abs(p.signed_notional) * v for p, v in zip(ps, vs)), cls_floor=V.ASSUMED)
    if not ps:
        sav = {}
    elif G is None:
        sav = {p.instrument_id: V.na(MIXED) for p in ps}
    elif V.is_null(tot):
        sav = {p.instrument_id: V.na(tot["reason"], tot["state"], tot["flags"]) for p in ps}
    elif not tot["value"] > 0:
        sav = {p.instrument_id: V.na("zero_total_standalone_vol") for p in ps}
    else:
        sav = {p.instrument_id: V.mv(abs(p.signed_notional) * sig1d[p.instrument_id]["value"] / tot["value"], V.DERIVED,
                                     tot["state"], flags=tot["flags"]) for p in ps}
    rec["risk_contribution"] = {
        "notional": ({p.instrument_id: V.na(MIXED) for p in ps} if G is None else
                     {p.instrument_id: V.mv(abs(p.signed_notional) / G, V.DERIVED) for p in ps} if G > 0 else {}),
        "standalone_vol": sav,
        "covariance_euler": cov["euler_contribution"],
        "covariance_condition": {"k": cov["k"], "n_common": cov["n_common"], "n_required": cov["n_required"]},
        "no_optimization": "descriptive decomposition only",
    }
    flags = _flags(rec, ps, C)
    conc, corr, btc = rec["concentration"], rec["correlation"], rec["btc_exposure"]
    rec["diversification"] = {
        "symbol_count": len(ps), "symbol_count_note": "reported for context; never a diversification measure on its own",
        "components": {"effective_n_notional": conc["effective_n_notional"], "largest_share": conc["largest_share"],
                       "average_pairwise_correlation_weighted": corr["average_pairwise_weighted"],
                       "max_pairwise_correlation": corr["max_pairwise"],
                       "direct_btc_weight": btc["direct_btc_weight"], "portfolio_beta_to_btc": btc["portfolio_beta_to_btc"],
                       "weighted_correlation_with_btc": btc["weighted_correlation_with_btc"],
                       "high_vol_notional_share": vol["high_vol_notional_share"],
                       "weak_liquidity_share": liq["weak_liquidity_share"],
                       "diversification_ratio": cov["diversification_ratio"]},
        "effective_bets": V.na("refused_by_design:precision_not_supported_by_about_1.4_days_of_15m_data"),
        "single_score": None, "single_score_policy": "NONE_BY_DESIGN",
        "limiting_factors": sorted({f["id"] for f in flags}),
    }
    rec["flags"] = flags
    rec["provenance"] = {"market_data": {k: ctx.market.meta[k] for k in sorted(ctx.market.meta)},
                         "inputs_sha256": V.sha256_text(V.canon(deep_round({
                             "T": T, "positions": [p.as_dict() for p in ps], "capital": cap,
                             "equity_curve": equity_curve, "duplicates": duplicates,
                             "conceptual_short": conceptual_short})))}
    rec = deep_round(rec)
    counts, unavailable = {}, []
    for path, m in V.walk_metrics(rec):
        counts[m["state"]] = counts.get(m["state"], 0) + 1
        if m["value"] is None:
            unavailable.append({"path": path, "state": m["state"], "reason": m["reason"]})
    rec["quality"] = {"state_counts": dict(sorted(counts.items())),
                      "worst": V.worst(*counts) if counts else V.VALID,
                      "precedence_worst_first": list(V.PRECEDENCE)}
    rec["unavailable"] = unavailable
    V.check_tree(rec)
    body = {k: v for k, v in rec.items() if k != "snapshot_id"}
    rec["snapshot_id"] = V.sha256_text(V.canon(body))
    return rec


def canonical_line(rec: dict) -> str:
    return V.canon(rec)
