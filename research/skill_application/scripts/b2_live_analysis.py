#!/usr/bin/env python3
"""TASK B2 — Timeframe selection on LIVE DB join. Falsify-first robustness battery."""
import numpy as np, pandas as pd

CSV = "/home/tradmin/trading-signal-bot/research/skill_application/scripts/b2_live.csv"
cols = ['signal_id','symbol','timeframe','signal_time','profit_percent','profit_usdt',
        'result','stop_hit','target_reached','duration_hours']
df = pd.read_csv(CSV, header=None, names=cols)
df['signal_time'] = pd.to_datetime(df['signal_time'])
df['profit_percent'] = pd.to_numeric(df['profit_percent'], errors='coerce')
df['stop_hit'] = df['stop_hit'].map({'t':True,'f':False})
df['target_reached'] = pd.to_numeric(df['target_reached'], errors='coerce')
df['month'] = df['signal_time'].dt.to_period('M').astype(str)
df = df.dropna(subset=['profit_percent'])
print(f"total rows: {len(df)}  symbols: {df.symbol.nunique()}  months: {sorted(df.month.unique())}")

def winsor(x, lo=1, hi=99):
    a,b = np.percentile(x, [lo,hi]); return np.clip(x, a, b)

def clustered_boot(sub, fee, reps=3000, seed=0):
    """resample SYMBOLS with replacement -> net-expectancy CI."""
    rng = np.random.default_rng(seed)
    g = {s: sub.loc[sub.symbol==s,'net_g'].values for s in sub.symbol.unique()}
    syms = np.array(list(g.keys()))
    means = np.empty(reps)
    for i in range(reps):
        pick = rng.choice(syms, size=len(syms), replace=True)
        vals = np.concatenate([g[s] for s in pick])
        means[i] = vals.mean()
    return np.percentile(means, [2.5, 97.5])

def analyze(sub, label, fee=0.3):
    n = len(sub); nsym = sub.symbol.nunique()
    gross = winsor(sub['profit_percent'].values)
    net = gross - fee
    sub = sub.assign(net_g=net)
    mean_net = net.mean()
    wr = (net > 0).mean()*100
    # profit factor (net)
    pos = net[net>0].sum(); neg = -net[net<0].sum()
    pf = pos/neg if neg>0 else np.inf
    ci = clustered_boot(sub, fee)
    # remove-top-N concentration: sort by net desc, how many removals flip sign of SUM? (sign already neg usually)
    s = np.sort(net)[::-1]
    tot = net.sum(); k=0; run=tot
    # how many top winners to remove to flip a positive total to negative
    flip = None
    if tot > 0:
        run = tot
        for i,v in enumerate(s):
            run -= v
            if run < 0: flip = i+1; break
    return dict(label=label, n=n, nsym=nsym, mean_net=mean_net, wr=wr, pf=pf,
               ci_lo=ci[0], ci_hi=ci[1], flip=flip, tot=tot)

def show(r):
    pf = 'inf' if r['pf']==np.inf else f"{r['pf']:.3f}"
    print(f"{r['label']:<16} n={r['n']:>4} sym={r['nsym']:>3}  meanNet={r['mean_net']:>+7.3f}%  "
          f"WR={r['wr']:>4.1f}%  PF={pf:>5}  CI95=[{r['ci_lo']:>+6.3f},{r['ci_hi']:>+6.3f}]  "
          f"{'CI_EXCLUDES_0' if (r['ci_lo']>0 or r['ci_hi']<0) else 'CI_INCLUDES_0'}")

# ---- Single TFs ----
print("\n================ SINGLE TIMEFRAMES (fee=0.3% round-trip) ================")
for tf in ['15m','1h','4h','1d']:
    show(analyze(df[df.timeframe==tf], tf, 0.3))

print("\n================ SINGLE TIMEFRAMES (fee=0.6% pessimistic) ================")
for tf in ['15m','1h','4h','1d']:
    show(analyze(df[df.timeframe==tf], tf, 0.6))

# ---- Subsets of bot TFs {15m,4h,1d} ----
print("\n================ SUBSETS of bot TFs 15m/4h/1d (fee=0.3%) ================")
subsets = {
    '15m-only': ['15m'], '4h-only': ['4h'], '1d-only': ['1d'],
    '15m+4h': ['15m','4h'], '15m+1d': ['15m','1d'], '4h+1d(drop15m)': ['4h','1d'],
    '15m+4h+1d(all)': ['15m','4h','1d'],
}
for lbl, tfs in subsets.items():
    show(analyze(df[df.timeframe.isin(tfs)], lbl, 0.3))

print("\n================ SUBSETS (fee=0.6%) ================")
for lbl, tfs in subsets.items():
    show(analyze(df[df.timeframe.isin(tfs)], lbl, 0.6))

# ---- Leave-one-MONTH-out stability (proxy for LOYO; live data all 2026) ----
print("\n================ LEAVE-ONE-MONTH-OUT (mean net%, fee=0.3%) ================")
months = sorted(df.month.unique())
for tf in ['15m','4h','1d']:
    sub = df[df.timeframe==tf]
    row=[]
    for m in months:
        s2 = sub[sub.month != m]
        if len(s2)==0: row.append('—'); continue
        row.append(f"{(winsor(s2.profit_percent.values)-0.3).mean():+.3f}")
    print(f"{tf:<6} drop-each-month -> " + "  ".join(f"{m[-2:]}:{v}" for m,v in zip(months,row)))
    # also per-month standalone
    row2=[]
    for m in months:
        s2 = sub[sub.month==m]
        if len(s2)==0: row2.append(f"{m[-2:]}:—"); continue
        row2.append(f"{m[-2:]}:{(winsor(s2.profit_percent.values)-0.3).mean():+.3f}(n{len(s2)})")
    print(f"       per-month standalone -> " + "  ".join(row2))
