#!/usr/bin/env python3
"""Stress-test the ONLY candidate: 1d-only on the OOS engine (marginal + @0.3%).
Falsify via: recent-regime split, remove-top-N-SYMBOL, clustered p-value + BH, live-vs-oos contradiction."""
import numpy as np, pandas as pd

def winsor(x, lo=1, hi=99):
    x = np.asarray(x, float)
    a, b = np.percentile(x, [lo, hi]); return np.clip(x, a, b)

def clustered_draws(sub, fee, reps=5000, seed=1):
    rng = np.random.default_rng(seed)
    gw = winsor(sub['gross'].values); tmp = sub.assign(net=gw - fee)
    g = {s: tmp.loc[tmp.symbol == s, 'net'].values for s in tmp.symbol.unique()}
    syms = np.array(list(g.keys())); draws = np.empty(reps)
    for i in range(reps):
        pick = rng.choice(syms, size=len(syms), replace=True)
        draws[i] = np.concatenate([g[s] for s in pick]).mean()
    return draws

def summ(sub, fee):
    gw = winsor(sub['gross'].values); net = gw - fee
    d = clustered_draws(sub, fee)
    lo, hi = np.percentile(d, [2.5, 97.5])
    # two-sided clustered p for mean>0
    p = 2 * min((d <= 0).mean(), (d >= 0).mean())
    return net.mean(), lo, hi, p, len(sub), sub.symbol.nunique()

oos = pd.read_csv("b2_oos_trades.csv")
d1 = oos[oos.tf == '1d'].copy()

print("### 1d-only OOS: recent-regime split (clustered CI, 0.3% and 0.6%) ###")
for lbl, mask in [('ALL 2017-2026', d1.year >= 0),
                  ('2021-2022 (bull)', d1.year.isin([2021,2022])),
                  ('2023-2026 (recent)', d1.year >= 2023),
                  ('2024-2026 (recent2)', d1.year >= 2024),
                  ('2025-2026 (newest)', d1.year >= 2025)]:
    sub = d1[mask]
    for fee in (0.3, 0.6):
        m, lo, hi, p, n, ns = summ(sub, fee)
        tag = 'POS' if lo > 0 else ('neg' if hi < 0 else '~0')
        print(f"  {lbl:<22} fee={fee} meanNet={m:>+6.3f}% n={n:>5} sym={ns:>3} "
              f"CI95=[{lo:>+6.3f},{hi:>+6.3f}] p={p:.3f} {tag}")

print("\n### remove-top-N SYMBOL concentration (1d, 0.3%, ALL years) ###")
fee = 0.3
gw = winsor(d1['gross'].values); tmp = d1.assign(net=gw - fee)
sym_tot = tmp.groupby('symbol')['net'].sum().sort_values(ascending=False)
grand = tmp['net'].sum()
print(f"  grand total net (winsor,0.3) = {grand:+.1f} over {d1.symbol.nunique()} symbols; "
      f"mean/trade={tmp.net.mean():+.4f}%")
run = grand; flipped = None
for k, (s, v) in enumerate(sym_tot.items(), 1):
    run -= v
    if run < 0: flipped = k; break
print(f"  removing top {flipped} winning SYMBOLS flips total NEGATIVE "
      f"({flipped}/{d1.symbol.nunique()} = {100*flipped/d1.symbol.nunique():.1f}% of symbols)")
print("  top 8 contributing symbols:", [f"{s}:{v:+.1f}" for s,v in sym_tot.head(8).items()])

print("\n### Benjamini-Hochberg across the TF-subset scan (OOS, 0.3%) ###")
tests = {'1h':oos[oos.tf=='1h'],'4h':oos[oos.tf=='4h'],'1d':d1,
         '4h+1d':oos[oos.tf.isin(['4h','1d'])],'1h+4h+1d':oos}
res = {k: summ(v, 0.3) for k, v in tests.items()}
ps = sorted([(k, r[3]) for k, r in res.items()], key=lambda x: x[1])
m = len(ps)
print("  rank  test        p        BH_thresh(0.05)  sig?  meanNet   dir")
for i, (k, p) in enumerate(ps, 1):
    thr = 0.05 * i / m
    mean = res[k][0]; direction = 'POS' if res[k][1] > 0 else ('neg' if res[k][2] < 0 else '~0')
    print(f"  {i:>4}  {k:<10} {p:<8.4f} {thr:<15.4f} {'YES' if p<=thr else 'no ':<4}  {mean:>+6.3f}%  {direction}")

print("\n### LIVE vs OOS contradiction on 1d (forward test) ###")
cols=['signal_id','symbol','timeframe','signal_time','gross','profit_usdt','result',
      'stop_hit','target_reached','duration_hours','trade_type','market_condition']
live=pd.read_csv("b2_live_fresh.csv",header=None,names=cols)
live['gross']=pd.to_numeric(live['gross'],errors='coerce'); live=live.dropna(subset=['gross'])
l1=live[live.timeframe=='1d']
for fee in (0.3,0.6):
    m,lo,hi,p,n,ns=summ(l1,fee)
    print(f"  LIVE 1d fee={fee} meanNet={m:+.3f}% n={n} sym={ns} CI95=[{lo:+.3f},{hi:+.3f}] p={p:.3f}  "
          f"{'POS' if lo>0 else ('neg' if hi<0 else '~0')}")
