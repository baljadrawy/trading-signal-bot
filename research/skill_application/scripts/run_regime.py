"""
TASK R_REGIME — Regime overlay: is there a regime where net expectancy is positive?

Per-trade regime built at signal_time (NO look-ahead: only bars strictly < signal_time):
  - volatility axis: realized-vol percentile (rolling std of log returns) over trailing window,
    ranked vs trailing lookback. ATR%-percentile when full OHLC available, else close-vol percentile.
  - trend axis: EMA(20) slope sign over trailing 5 bars + price-vs-EMA -> up / down / flat
  - BTC regime cross: BTC 24h return at signal_time -> up / down / flat (+-1% band)

Buckets: 4 quadrant (volHi/volLo x trendUp/trendDown) + flat, plus BTC cross.
Compare n / WR / net_exp / PF_net per bucket. Bootstrap CI on net_exp for any positive bucket.
promising=true ONLY if a bucket has net_exp>0, bootstrap 95% CI excludes 0, n>=30.
"""
import os, glob, json, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import lib

OUT = "/home/tradmin/trading-signal-bot/research/skill_application/out"
os.makedirs(OUT, exist_ok=True)
RNG = np.random.default_rng(42)
ICT_DIR = "/home/tradmin/trading-signal-bot/analyzer/research/cache/ict_ohlc"

# -------------------------------------------------- unified OHLC loader (full OHLC preferred)
def _to_df(rows):
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df.set_index("dt").sort_index()

# build index: ict_ohlc (full OHLC, ~6mo hourly) first, then lib klines (full OHLC), then close-only
_ICT = {}
for f in glob.glob(f"{ICT_DIR}/*_1h_ohlc.pkl"):
    sym = os.path.basename(f).replace("_1h_ohlc.pkl", "")
    _ICT[sym] = f

_cache = {}
def get_ohlc(sym):
    """Return DataFrame[o,h,l,c] hourly UTC (full OHLC) or close-only df, or None. Cached."""
    if sym in _cache:
        return _cache[sym]
    res = None
    if sym in _ICT:
        df = _to_df(pd.read_pickle(_ICT[sym]))
        if {"o", "h", "l", "c"}.issubset(df.columns):
            res = df[["o", "h", "l", "c"]].astype(float)
    if res is None:
        o = lib.load_ohlc(sym)  # klines full OHLC ~90d
        if o is not None:
            res = o
    if res is None:
        c = lib.load_close(sym)  # close-only fallback
        if c is not None:
            res = pd.DataFrame({"c": c.astype(float)})
    _cache[sym] = res
    return res

# -------------------------------------------------- indicators at a timestamp (no look-ahead)
def atr_series(o):
    h, l, c = o["h"], o["l"], o["c"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(14).mean()

def regime_at(sym, ts):
    """Compute (vol_pct, trend_dir, has_full) using ONLY bars with index < ts."""
    o = get_ohlc(sym)
    if o is None:
        return None
    o = o[o.index < ts]              # strict: no bar at/after signal_time
    if len(o) < 60:
        return None
    c = o["c"]
    full = {"o", "h", "l"}.issubset(o.columns)
    # ----- volatility percentile
    if full:
        atr = atr_series(o)
        atrp = (atr / c)                       # ATR as % of price
        volp = atrp.rolling(100).rank(pct=True)
    else:
        ret = np.log(c / c.shift(1))
        rv = ret.rolling(14).std()
        volp = rv.rolling(100).rank(pct=True)
    vp = volp.dropna()
    if vp.empty:
        return None
    vol_pct = float(vp.iloc[-1])
    # ----- trend direction (EMA20 slope over 5 bars + price vs EMA)
    ema = c.ewm(span=20, adjust=False).mean()
    slope = ema.diff(5)
    if pd.isna(slope.iloc[-1]):
        return None
    sl = float(slope.iloc[-1]); above = bool(c.iloc[-1] > ema.iloc[-1])
    if sl > 0 and above:
        tdir = "up"
    elif sl < 0 and not above:
        tdir = "down"
    else:
        tdir = "flat"
    return {"vol_pct": vol_pct, "trend": tdir, "full": full}

# -------------------------------------------------- BTC regime (24h return at signal_time)
_btc = None
def btc_regime(ts):
    global _btc
    if _btc is None:
        _btc = get_ohlc("BTCUSDT")
    if _btc is None:
        return "na"
    sub = _btc[_btc.index < ts]
    if len(sub) < 25:
        return "na"
    now = sub["c"].iloc[-1]
    prev = sub["c"].iloc[-25]            # ~24 hourly bars back
    r = (now / prev - 1.0) * 100
    if r > 1.0:
        return "up"
    if r < -1.0:
        return "down"
    return "flat"

# -------------------------------------------------- bootstrap CI on net_exp
def boot_ci(x, B=10000):
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return (np.nan, np.nan)
    means = x[RNG.integers(0, n, size=(B, n))].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))

# -------------------------------------------------- main
df = lib.load_trades()
recs = []
for _, row in df.iterrows():
    sym, ts = row["symbol"], row["signal_time"]
    r = regime_at(sym, ts)
    if r is None:
        continue
    vol_lab = "volHi" if r["vol_pct"] >= 0.5 else "volLo"   # median split (robust w/ small windows)
    recs.append({
        "idx": row.name, "symbol": sym, "signal_time": ts,
        "net": row["net_usdt"], "gross": row["profit_usdt"], "win": row["win"],
        "vol_pct": r["vol_pct"], "vol_lab": vol_lab, "trend": r["trend"], "full": r["full"],
        "btc": btc_regime(ts), "month": ts.to_period("M").strftime("%Y-%m"),
    })

R = pd.DataFrame(recs)
print(f"trades with regime computed: {len(R)} / {len(df)}  ({100*len(R)/len(df):.1f}%)")
print(f"  full-OHLC trades: {R.full.sum()}  close-only: {(~R.full).sum()}")
print(f"  BTC regime available: {(R.btc!='na').sum()}")
print()

def summarize(g):
    net = g["net"].values
    return pd.Series({
        "n": len(g), "WR": 100 * g["win"].mean(),
        "net_exp": net.mean(), "gross_exp": g["gross"].mean(),
        "PF_net": lib.pf(net), "net_sum": net.sum(),
    })

results = {}

# ---- 4-quadrant (vol x trend), trend flat kept separate
R["quad"] = R["vol_lab"] + "_" + R["trend"]
q = R.groupby("quad").apply(summarize, include_groups=False).sort_values("net_exp", ascending=False)
print("=== VOL x TREND quadrants ===")
print(q.to_string(float_format=lambda x: f"{x:.3f}"))
results["quad"] = q.reset_index().to_dict("records")

# ---- BTC cross
print("\n=== BTC regime ===")
b = R[R.btc != "na"].groupby("btc").apply(summarize, include_groups=False).sort_values("net_exp", ascending=False)
print(b.to_string(float_format=lambda x: f"{x:.3f}"))
results["btc"] = b.reset_index().to_dict("records")

# ---- quad x BTC cross
print("\n=== VOL x TREND x BTC (n>=15 only) ===")
R["cross"] = R["quad"] + "|btc_" + R["btc"]
c = R[R.btc != "na"].groupby("cross").apply(summarize, include_groups=False)
c = c[c["n"] >= 15].sort_values("net_exp", ascending=False)
print(c.to_string(float_format=lambda x: f"{x:.3f}"))
results["cross"] = c.reset_index().to_dict("records")

# ---- vol decile sweep (continuous look for monotone edge)
print("\n=== vol_pct quintile ===")
R["vq"] = pd.qcut(R["vol_pct"], 5, labels=False, duplicates="drop")
vq = R.groupby("vq").apply(summarize, include_groups=False)
print(vq.to_string(float_format=lambda x: f"{x:.3f}"))
results["vol_quintile"] = vq.reset_index().to_dict("records")

# -------------------------------------------------- bootstrap any positive bucket with n>=30
print("\n=== POSITIVE buckets (net_exp>0) bootstrap 95% CI ===")
pos = []
all_buckets = []
for label, sub in (
    [(f"quad:{k}", R[R.quad == k]) for k in R.quad.unique()] +
    [(f"btc:{k}", R[(R.btc == k)]) for k in R.btc.unique() if k != "na"] +
    [(f"cross:{k}", R[R.cross == k]) for k in R.cross.unique()] +
    [(f"volQ:{k}", R[R.vq == k]) for k in R.vq.dropna().unique()]
):
    if len(sub) < 10:
        continue
    ne = sub["net"].mean()
    lo, hi = boot_ci(sub["net"].values)
    rec = {"bucket": label, "n": int(len(sub)), "net_exp": float(ne),
           "ci_lo": lo, "ci_hi": hi, "WR": float(100 * sub["win"].mean()),
           "PF_net": float(lib.pf(sub["net"].values))}
    all_buckets.append(rec)
    if ne > 0 and len(sub) >= 30:
        flag = "*** CI EXCLUDES 0 ***" if lo > 0 else "(CI includes 0)"
        print(f"  {label:34s} n={len(sub):4d} net_exp={ne:+.4f} CI=[{lo:+.4f},{hi:+.4f}] WR={100*sub['win'].mean():.1f}% {flag}")
        pos.append(rec)
if not pos:
    print("  (none with net_exp>0 AND n>=30)")
results["positive_buckets"] = pos
results["all_buckets"] = all_buckets

# ---- promising criterion
promising = any(b["ci_lo"] > 0 and b["n"] >= 30 and b["net_exp"] > 0 for b in pos)
results["promising"] = promising

# coverage stats
cov = {
    "trades_total": int(len(df)),
    "trades_with_regime": int(len(R)),
    "coverage_pct": round(100 * len(R) / len(df), 1),
    "symbols_total": int(df.symbol.nunique()),
    "symbols_with_regime": int(R.symbol.nunique()),
    "full_ohlc_trades": int(R.full.sum()),
    "btc_avail_trades": int((R.btc != "na").sum()),
    "n_buckets_tested": len(all_buckets),
}
results["coverage"] = cov
print("\ncoverage:", json.dumps(cov))
print("PROMISING:", promising)

with open(f"{OUT}/regime_results.json", "w") as fh:
    json.dump(results, fh, indent=2, default=str)
print(f"\nwrote {OUT}/regime_results.json")
