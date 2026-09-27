#!/usr/bin/env python3
"""B5 funding-carry feasibility: download real Binance USD-M funding history and
characterize the gross carry distribution across symbols and market regimes.
Mechanism (cash-and-carry basis): long spot + short perp collects funding when
funding>0 (perp premium). Gross carry ~= time-mean of funding rate, annualized.
This is a MECHANISM estimate, not a fitted directional backtest."""
import os, urllib.request, urllib.error, zipfile, io, concurrent.futures as cf
import numpy as np, pandas as pd

BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
DEST = "/tmp/b5_fund/raw"
os.makedirs(DEST, exist_ok=True)

SYMS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT",
        "AVAXUSDT","LINKUSDT","DOTUSDT","LTCUSDT","ATOMUSDT","NEARUSDT","MATICUSDT",
        "ARBUSDT","OPUSDT","APTUSDT","INJUSDT","SUIUSDT","FILUSDT"]
MONTHS = [f"{y}-{m:02d}" for y in range(2021,2027) for m in range(1,13)]

def dl(a):
    sym, ym = a
    fn = f"{sym}-fundingRate-{ym}.zip"
    zp = f"{DEST}/{sym}__{ym}.csv"
    mk = zp + ".404"
    if os.path.exists(zp) or os.path.exists(mk): return ("skip", sym)
    url = f"{BASE}/{sym}/{fn}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r: data = r.read()
        z = zipfile.ZipFile(io.BytesIO(data)); n = z.namelist()[0]
        open(zp, "wb").write(z.read(n)); return ("ok", sym)
    except urllib.error.HTTPError as e:
        if e.code == 404: open(mk, "w").close(); return ("404", sym)
        return ("err", sym)
    except Exception as e:
        return ("err", sym)

jobs = [(s, ym) for s in SYMS for ym in MONTHS]
ok = c4 = ce = sk = 0
with cf.ThreadPoolExecutor(max_workers=16) as ex:
    for t, sym in ex.map(dl, jobs):
        if t == "ok": ok += 1
        elif t == "404": c4 += 1
        elif t == "skip": sk += 1
        else: ce += 1
print(f"download done: ok={ok} 404={c4} skip={sk} err={ce}", flush=True)

# ---- load per-symbol funding series ----
def load(sym):
    recs = []
    for ym in MONTHS:
        p = f"{DEST}/{sym}__{ym}.csv"
        if not os.path.exists(p): continue
        for ln in open(p).read().splitlines():
            if ln.startswith("calc_time"): continue
            q = ln.split(",")
            try: recs.append((int(q[0]), int(float(q[1])), float(q[2])))
            except Exception: pass
    if not recs: return None
    df = pd.DataFrame(recs, columns=["t","ivl","rate"]).drop_duplicates("t").sort_values("t")
    df["dt"] = pd.to_datetime(df["t"], unit="ms")
    return df

series = {s: load(s) for s in SYMS}
series = {s: d for s, d in series.items() if d is not None and len(d) > 100}
print(f"symbols with funding: {len(series)}", flush=True)

# per-8h rate; annualization factor = payments/year. Binance = 3/day (8h) mostly.
rows = []
for s, d in series.items():
    r = d["rate"].values
    # payments per year using observed interval hours (default 8)
    ph = d["ivl"].replace(0, 8).values
    ann = (r * (24.0/ph)).mean() * 365.0 * 100.0   # annualized mean funding %/yr
    rows.append(dict(sym=s, n=len(r),
        start=str(d["dt"].iloc[0].date()), end=str(d["dt"].iloc[-1].date()),
        mean_8h_pct=r.mean()*100, median_8h_pct=np.median(r)*100,
        pct_positive=(r>0).mean()*100, ann_carry_pct=ann,
        std_8h_pct=r.std()*100))
summ = pd.DataFrame(rows).sort_values("ann_carry_pct", ascending=False)
pd.set_option("display.width",200); pd.set_option("display.max_columns",20)
print("\n=== PER-SYMBOL FUNDING (full available history) ===")
print(summ.to_string(index=False))

# ---- regime split by year, pooled across symbols (equal-weight per symbol per year) ----
allrec = []
for s, d in series.items():
    dd = d.copy(); dd["year"] = dd["dt"].dt.year; dd["sym"] = s
    allrec.append(dd[["year","sym","rate","ivl"]])
big = pd.concat(allrec)
big["ann_contrib"] = big["rate"] * (24.0/big["ivl"].replace(0,8)) * 365.0 * 100.0
print("\n=== ANNUALIZED GROSS CARRY BY YEAR (equal-weight symbols) ===")
gy = big.groupby("year").agg(
    mean_ann_carry_pct=("ann_contrib","mean"),
    median_ann_carry_pct=("ann_contrib","median"),
    pct_positive=("rate", lambda x: (x>0).mean()*100),
    n_obs=("rate","size"),
    n_syms=("sym","nunique")).reset_index()
print(gy.to_string(index=False))

# ---- overall pooled ----
print("\n=== POOLED (all symbols, all years) ===")
r_all = big["rate"].values
print(f"mean 8h funding = {r_all.mean()*100:.5f}%  median = {np.median(r_all)*100:.5f}%  pct_positive = {(r_all>0).mean()*100:.1f}%")
print(f"mean annualized gross carry (long-spot/short-perp always on) = {big['ann_contrib'].mean():.2f}%/yr")
# symbol-level annual carry dist
sym_ann = big.groupby("sym")["ann_contrib"].mean()
print(f"cross-symbol annual carry: median={sym_ann.median():.2f}% p25={sym_ann.quantile(.25):.2f}% p75={sym_ann.quantile(.75):.2f}% min={sym_ann.min():.2f}% max={sym_ann.max():.2f}%")
