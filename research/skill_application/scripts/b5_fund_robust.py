#!/usr/bin/env python3
"""B5 funding carry robustness: winsorize, symbol-clustered bootstrap CI, funding-sign
gating, and explicit fee amortization. Mechanism: long spot + short perp collects funding
when funding>0 (delta-neutral). No look-ahead: funding is pre-announced each period."""
import os, numpy as np, pandas as pd
DEST="/tmp/b5_fund/raw"
SYMS=["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT",
      "AVAXUSDT","LINKUSDT","DOTUSDT","LTCUSDT","ATOMUSDT","NEARUSDT","MATICUSDT",
      "ARBUSDT","OPUSDT","APTUSDT","INJUSDT","SUIUSDT","FILUSDT"]
MONTHS=[f"{y}-{m:02d}" for y in range(2021,2027) for m in range(1,13)]

def load(sym):
    recs=[]
    for ym in MONTHS:
        p=f"{DEST}/{sym}__{ym}.csv"
        if not os.path.exists(p): continue
        for ln in open(p).read().splitlines():
            if ln.startswith("calc_time"): continue
            q=ln.split(",")
            try: recs.append((int(q[0]),int(float(q[1])),float(q[2])))
            except: pass
    if not recs: return None
    df=pd.DataFrame(recs,columns=["t","ivl","rate"]).drop_duplicates("t").sort_values("t")
    df["dt"]=pd.to_datetime(df["t"],unit="ms"); df["ivl"]=df["ivl"].replace(0,8)
    return df

series={s:load(s) for s in SYMS}; series={s:d for s,d in series.items() if d is not None and len(d)>100}
big=[]
for s,d in series.items():
    dd=d.copy(); dd["sym"]=s; big.append(dd[["sym","dt","rate","ivl"]])
big=pd.concat(big); big["year"]=big["dt"].dt.year
# per-payment annualized contribution (payments/yr = 24/ivl * 365)
big["ann"]=big["rate"]*(24.0/big["ivl"])*365.0*100.0

# winsorize the per-payment rate 1/99 (LUNA-style outlier guard), then annualize
lo,hi=big["rate"].quantile([.01,.99])
big["rate_w"]=big["rate"].clip(lo,hi)
big["ann_w"]=big["rate_w"]*(24.0/big["ivl"])*365.0*100.0

print("=== POOLED GROSS CARRY (long-spot / short-perp, always on) ===")
print(f"raw  mean annualized carry = {big['ann'].mean():+.2f}%/yr")
print(f"winsorized(1/99) mean       = {big['ann_w'].mean():+.2f}%/yr   <- robust")
print(f"median per-payment funding  = {big['rate'].median()*100:.5f}% (8h) -> {big['rate'].median()*3*365*100:+.2f}%/yr")
print(f"pct periods funding>0       = {(big['rate']>0).mean()*100:.1f}%")

# symbol-clustered bootstrap of the cross-symbol mean annual carry (winsorized)
sym_ann={s:big[big.sym==s]["ann_w"].mean() for s in series}
arr=np.array(list(sym_ann.values()))
rng=np.random.default_rng(7); boot=[]
syms=list(series)
for _ in range(5000):
    samp=rng.choice(syms,size=len(syms),replace=True)
    boot.append(np.mean([sym_ann[x] for x in samp]))
lo_ci,hi_ci=np.percentile(boot,[2.5,97.5])
print(f"\nsymbol-clustered bootstrap 95% CI of cross-symbol mean annual carry (winsor):")
print(f"  point={arr.mean():+.2f}%/yr  CI=[{lo_ci:+.2f}%, {hi_ci:+.2f}%]  (n_syms={len(syms)})")
print(f"  cross-symbol: median={np.median(arr):+.2f}% p25={np.percentile(arr,25):+.2f}% p75={np.percentile(arr,75):+.2f}% min={arr.min():+.2f}% max={arr.max():+.2f}%")

# funding-sign GATED carry: only collect when the (pre-announced) rate>0; else flat.
# no look-ahead: Binance announces next funding rate before the period.
gated=big[big["rate_w"]>0]
frac_on=len(gated)/len(big)
gated_ann=gated["rate_w"]*(24.0/gated["ivl"])*365.0*100.0
# effective yield = gated per-payment yield * fraction of time deployed
eff=gated["rate_w"].mean()*(24.0/gated["ivl"].mean())*365.0*100.0*frac_on
print(f"\n=== FUNDING-SIGN GATED (collect only when rate>0, else flat) ===")
print(f"time deployed={frac_on*100:.1f}%  mean carry while on={gated_ann.mean():+.2f}%/yr  effective(time-weighted)~{eff:+.2f}%/yr")

# fee amortization: setup+unwind ~0.30% one-time (spot 0.1%+perp 0.05% each side).
for hold_days,fee in [(90,0.30),(180,0.30),(365,0.30),(365,0.60)]:
    carry=big['ann_w'].mean()*(hold_days/365.0)
    net=carry-fee
    print(f"  hold {hold_days:>3}d @ {fee:.2f}% setup/unwind: gross={carry:+.2f}% - fee={fee:.2f}% = NET {net:+.2f}% over the hold "
          f"({net*365.0/hold_days:+.2f}%/yr)")

print("\n=== BY-YEAR (winsorized, equal-weight symbols) ===")
gy=big.groupby("year").agg(mean_ann=("ann_w","mean"),pct_pos=("rate",lambda x:(x>0).mean()*100),n_syms=("sym","nunique")).reset_index()
print(gy.to_string(index=False))
