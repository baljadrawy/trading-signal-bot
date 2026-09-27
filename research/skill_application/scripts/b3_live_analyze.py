#!/usr/bin/env python3
"""B3 live-join cross-check (in-sample for these features -> treat positives skeptically).
Gross% = profit_percent (already gross); net = gross - fee. profit_usdt is size-scaled -> ignore for expectancy.
Robustness: winsorize gross 1/99, symbol-clustered bootstrap CI 2000 reps, remove-top-N, direction checks."""
import numpy as np, pandas as pd
rng = np.random.default_rng(99)
cols = ['symbol','tf','mc','ttype','score','dist_ema200','macd_hist','cci20','bb_pos','obv_vs_ema',
        'gross','net_usdt','result','stop_hit','target_reached','dur','stime']
df = pd.read_csv("/home/tradmin/trading-signal-bot/research/skill_application/scripts/b3_live_full.csv",
                 names=cols, header=None)
for c in ['score','dist_ema200','macd_hist','cci20','bb_pos','obv_vs_ema','gross','net_usdt','dur']:
    df[c] = pd.to_numeric(df[c], errors='coerce')
df['stop_hit'] = df['stop_hit'].map({'t':True,'f':False})
df['stime'] = pd.to_datetime(df['stime'])
df['is_win'] = (df['result']=='WIN').astype(int)
lo,hi = df['gross'].quantile(0.01), df['gross'].quantile(0.99)
df['gross_w'] = df['gross'].clip(lo,hi)
df['net03'] = df['gross_w']-0.3
df['net06'] = df['gross_w']-0.6
print(f"LIVE n={len(df)} sym={df['symbol'].nunique()} range={df['stime'].min().date()}..{df['stime'].max().date()}")
print(f"winsorize gross to [{lo:.3f},{hi:.3f}]  tf: {df['tf'].value_counts().to_dict()}")
print(f"baseline gross mean={df['gross_w'].mean():+.3f}  net03={df['net03'].mean():+.3f}  wr={df['is_win'].mean():.3f}")

def ci(sub, col, reps=2000):
    uniq = sub['symbol'].unique()
    by = {s: sub.index[sub['symbol']==s].to_numpy() for s in uniq}
    v = sub[col]; m = np.empty(reps)
    for r in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        m[r] = v.loc[np.concatenate([by[s] for s in pick])].mean()
    return np.percentile(m,2.5), np.percentile(m,97.5)

def rep(name, sub):
    if len(sub) < 15:
        print(f"  {name:34s} n={len(sub)} (small)"); return
    lo3,hi3 = ci(sub,'net03'); lo6,hi6 = ci(sub,'net06')
    s3 = 'POS*' if lo3>0 else ('NEG*' if hi3<0 else '')
    print(f"  {name:34s} n={len(sub):4d} sym={sub['symbol'].nunique():3d} wr={sub['is_win'].mean():.3f} "
          f"NET03={sub['net03'].mean():+.3f} NET06={sub['net06'].mean():+.3f} "
          f"CI03[{lo3:+.3f},{hi3:+.3f}] CI06[{lo6:+.3f},{hi6:+.3f}] {s3}")

GATES = [
    ("BASELINE ungated", df),
    ("dist_ema200<=0", df[df['dist_ema200']<=0]),
    ("dist_ema200<=-0.05", df[df['dist_ema200']<=-0.05]),
    ("dist_ema200<=-0.10", df[df['dist_ema200']<=-0.10]),
    ("macd_hist<=0", df[df['macd_hist']<=0]),
    ("ema200<=0 & macd<=0", df[(df['dist_ema200']<=0)&(df['macd_hist']<=0)]),
    ("ema200<=-0.05 & macd<=0", df[(df['dist_ema200']<=-0.05)&(df['macd_hist']<=0)]),
    ("cci20>=0", df[df['cci20']>=0]),
    ("cci20<=0", df[df['cci20']<=0]),
    ("bb_pos<=0", df[df['bb_pos']<=0]),
    ("obv_vs_ema<=0", df[df['obv_vs_ema']<=0]),
]
print("\n=== GATES on FULL LIVE (all tf) — symbol-clustered CI ===")
for name,sub in GATES: rep(name,sub)

print("\n=== quintile monotonicity (net03, winsorized) ===")
for feat in ['dist_ema200','macd_hist','cci20','bb_pos']:
    d = df.dropna(subset=[feat]).copy()
    try:
        d['q'] = pd.qcut(d[feat],5,labels=False,duplicates='drop')
    except Exception:
        continue
    agg = d.groupby('q').agg(n=('net03','size'),gross=('gross_w','mean'),net03=('net03','mean'),wr=('is_win','mean')).round(3)
    print(f"\n[{feat}]"); print(agg.to_string())

print("\n=== 4h+1d only (OOS-comparable; no 15m in history) ===")
d = df[df['tf'].isin(['4h','1d'])]
for name,sub in [("baseline 4h+1d",d),("dist_ema200<=0",d[d['dist_ema200']<=0]),
                 ("dist_ema200<=-0.05",d[d['dist_ema200']<=-0.05]),("macd_hist<=0",d[d['macd_hist']<=0])]:
    rep(name,sub)

print("\n=== REMOVE-TOP-N (best live gate dist_ema200<=-0.05, by net03 desc) ===")
g = df[df['dist_ema200']<=-0.05].sort_values('net03',ascending=False)
print(f"  full: n={len(g)} mean_net03={g['net03'].mean():+.3f}")
for k in [1,2,3,5,10]:
    if len(g)>k: print(f"  remove top {k}: mean_net03={g.iloc[k:]['net03'].mean():+.3f}")
flip = next((k for k in range(len(g)) if g.iloc[k:]['net03'].mean()<=0), None)
print(f"  trades to remove to flip NEG: {flip} of {len(g)} ({100*flip/len(g):.1f}%)" if flip is not None else "  never flips")
