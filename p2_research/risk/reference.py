"""Independent reference implementation of key RM0 metrics (determinism / correctness cross-check).

Deliberately a separate code path: its own PIT / W3 candle filter on the raw candle lists (no RiskView), its own
window arithmetic, ``fractions.Fraction`` for exposure shares and ``statistics`` (stdev, correlation, covariance,
variance) for second moments. It shares only the frozen parameters with the production path.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics
from fractions import Fraction

W3_START = dt.datetime(2026, 8, 19, 9, 33, 46, tzinfo=dt.timezone.utc)
W3_END = dt.datetime(2026, 10, 4, 15, 26, 43, 497803, tzinfo=dt.timezone.utc)


def _eligible(c, T: int) -> bool:
    open_dt = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(milliseconds=c[0])
    close_dt = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(milliseconds=c[6])
    overlaps_w3 = open_dt < W3_END and close_dt >= W3_START
    return c[8] <= T and c[6] < T and not overlaps_w3


def returns(candles: dict, sym: str, T: int, n: int, bar: int) -> dict:
    E = (T // bar - 1) * bar
    closes = {c[0]: c[4] for c in candles.get((sym, "15m"), []) if E - n * bar <= c[0] <= E and _eligible(c, T)}
    out = {}
    for k in range(1, n + 1):
        o = E - (n - k) * bar
        if o in closes and o - bar in closes and closes[o] > 0 and closes[o - bar] > 0:
            out[o] = math.log(closes[o] / closes[o - bar])
    return out


def _corr(x, y):
    try:
        return statistics.correlation(x, y)
    except statistics.StatisticsError:
        return None


def _beta(x, y):
    vy = statistics.variance(y)
    return None if vy == 0 else statistics.covariance(x, y) / vy


def metrics(candles: dict, positions: list, T: int, P: dict) -> dict:
    """positions: [(symbol, signed_notional)] or [(symbol, signed_notional, quote_currency)]. P: lookback / min_obs
    parameters. Returns a flat {key: value|None}. Independent D-RM0-2 rule: with more than one quote currency every
    cross-position monetary or notional-weighted value is None (no FX conversion)."""
    mixed = len({t[2] for t in positions if len(t) > 2}) > 1
    positions = [(t[0], t[1]) for t in positions]
    out = {}
    L, mo, cmo, bar = P["lookback"], P["min_obs_long"], P["min_obs_corr"], P["bar_ms"]
    g = sum(Fraction(abs(s)) for _, s in positions)
    out["exposure.gross"] = None if mixed else float(g)
    out["exposure.net"] = None if mixed else float(sum(Fraction(s) for _, s in positions))
    if mixed and positions:
        for k in ("largest_share", "top3_share", "hhi", "effective_n_notional"):
            out[f"concentration.{k}"] = None
    elif g > 0:
        w = sorted((Fraction(abs(s)) / g for _, s in positions), reverse=True)
        h = sum(x * x for x in w)
        out["concentration.largest_share"] = float(w[0])
        out["concentration.top3_share"] = float(sum(w[:3]))
        out["concentration.hhi"] = float(h)
        out["concentration.effective_n_notional"] = float(1 / h)
    R = {sym: returns(candles, sym, T, L, bar) for sym, _ in positions}
    btc = returns(candles, P["btc_symbol"], T, L, bar)
    for sym, _ in positions:
        r = R[sym]
        out[f"sigma.{sym}"] = statistics.stdev(list(r.values())) if len(r) >= mo else None
        ks = sorted(set(r) & set(btc))
        if len(ks) >= cmo:
            x, y = [r[k] for k in ks], [btc[k] for k in ks]
            out[f"beta.{sym}"] = _beta(x, y)
            out[f"rho_btc.{sym}"] = _corr(x, y)
        else:
            out[f"beta.{sym}"] = out[f"rho_btc.{sym}"] = None
    syms = [s for s, _ in positions]
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            a, b = R[syms[i]], R[syms[j]]
            ks = sorted(set(a) & set(b))
            out[f"rho.{syms[i]}|{syms[j]}"] = (_corr([a[k] for k in ks], [b[k] for k in ks])
                                              if len(ks) >= cmo else None)
    k = len(positions)
    if k:
        common = set(R[syms[0]])
        for s in syms[1:]:
            common &= set(R[s])
        common = sorted(common)
        if len(common) >= max(mo, 5 * k):
            cols = [[R[s][t] for t in common] for s in syms]
            sn = [s for _, s in positions]
            var = sum(sn[i] * sn[j] * statistics.covariance(cols[i], cols[j]) for i in range(k) for j in range(k))
            out["portfolio_sigma_1d_ccy"] = math.sqrt(var) * math.sqrt(96) if var > 0 else None
        else:
            out["portfolio_sigma_1d_ccy"] = None
        if mixed:
            out["portfolio_sigma_1d_ccy"] = None
    return out


def snapshot_values(snap: dict) -> dict:
    """The same keys read from a RiskSnapshot (None for null metrics)."""
    def v(m):
        return None if m is None else m["value"]
    out = {"exposure.gross": v(snap["exposure"]["gross"]), "exposure.net": v(snap["exposure"]["net"])}
    c = snap["concentration"]
    if snap["positions"]:
        for k in ("largest_share", "top3_share", "hhi", "effective_n_notional"):
            out[f"concentration.{k}"] = v(c[k])
    for p in snap["positions"]:
        iid, sym = p["instrument_id"], p["symbol"]
        out[f"sigma.{sym}"] = v(snap["volatility"]["per_position"][iid]["sigma_15m_long"])
        out[f"beta.{sym}"] = v(snap["btc_exposure"]["per_position"][iid]["beta_to_btc"])
        out[f"rho_btc.{sym}"] = v(snap["btc_exposure"]["per_position"][iid]["correlation_with_btc"])
    for key, pr in snap["correlation"]["pairs"].items():
        out[f"rho.{key}"] = v(pr["rho"])
    if snap["positions"]:
        out["portfolio_sigma_1d_ccy"] = v(snap["volatility"]["portfolio_vol_proxy"]["portfolio_sigma_1d_ccy"])
    return out


CCY_KEYS = ("exposure.gross", "exposure.net", "portfolio_sigma_1d_ccy")


def compare(ref: dict, snap_vals: dict, tol: float = 1e-9) -> list:
    """List of differences (empty = agreement). Null must match null; currency values compared relatively."""
    diffs = []
    for k in sorted(set(ref) | set(snap_vals)):
        a, b = ref.get(k, "MISSING"), snap_vals.get(k, "MISSING")
        if a is None or b is None or a == "MISSING" or b == "MISSING":
            if a != b:
                diffs.append({"key": k, "reference": a, "snapshot": b})
            continue
        scale = max(1.0, abs(a)) if k in CCY_KEYS else 1.0
        if abs(a - b) > tol * scale:
            diffs.append({"key": k, "reference": a, "snapshot": b, "abs_diff": abs(a - b)})
    return diffs


def max_abs_diff(ref: dict, snap_vals: dict) -> float:
    m = 0.0
    for k in ref:
        a, b = ref[k], snap_vals.get(k)
        if isinstance(a, float) and isinstance(b, (int, float)):
            scale = max(1.0, abs(a)) if k in CCY_KEYS else 1.0
            m = max(m, abs(a - b) / scale)
    return m
