#!/usr/bin/env python3
"""B3 live-join cross-check. Fresh pull. Symbol-clustered CI, remove-top-N, weekly
stability (only ~1 month of live data so no LOYO possible)."""
import numpy as np, pandas as pd
rng = np.random.default_rng(99)
cols = ['symbol', 'tf', 'mc', 'ttype', 'dist_ema200', 'macd_hist', 'cci20', 'bb_pos',
        'gross', 'net_usdt', 'result', 'stime']
df = pd.read_csv("/tmp/claude-1000/-home-tradmin/b8bc2d11-b669-4b9c-adcf-4346a3815440/scratchpad/live_join.csv",
                 names=cols, header=None)
for c in ['dist_ema200', 'macd_hist', 'cci20', 'bb_pos', 'gross', 'net_usdt']:
    df[c] = pd.to_numeric(df[c], errors='coerce')
df['stime'] = pd.to_datetime(df['stime'])
df['is_win'] = (df['net_usdt'] > 0).astype(int)
lo, hi = df['gross'].quantile(0.01), df['gross'].quantile(0.99)
df['gross_w'] = df['gross'].clip(lo, hi)
df['net03'] = df['gross_w'] - 0.3
df['net06'] = df['gross_w'] - 0.6
print(f"live n={len(df)} sym={df['symbol'].nunique()} range={df['stime'].min().date()}..{df['stime'].max().date()}")


def cci(sub, col, reps=2000):
    uniq = sub['symbol'].unique()
    by = {s: sub.index[sub['symbol'] == s].to_numpy() for s in uniq}
    v = sub[col]; m = np.empty(reps)
    for r in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        m[r] = v.loc[np.concatenate([by[s] for s in pick])].mean()
    return np.percentile(m, 2.5), np.percentile(m, 97.5)


def rep(name, sub):
    if len(sub) < 15:
        print(f"  {name:32s} n={len(sub)} (small)"); return
    lo3, hi3 = cci(sub, 'net03')
    star = 'POS*' if lo3 > 0 else ('NEG*' if hi3 < 0 else '')
    print(f"  {name:32s} n={len(sub):4d} sym={sub['symbol'].nunique():3d} wr={sub['is_win'].mean():.3f} "
          f"NET03={sub['net03'].mean():+.3f} NET06={sub['net06'].mean():+.3f} "
          f"CI03[{lo3:+.3f},{hi3:+.3f}] {star}")


for tag, d in [("ALL tf", df), ("4h+1d only (OOS-comparable)", df[df['tf'].isin(['4h', '1d'])]),
               ("1d only", df[df['tf'] == '1d'])]:
    print(f"\n=== {tag} ===")
    rep("baseline", d)
    rep("dist_ema200<=0", d[d['dist_ema200'] <= 0])
    rep("dist_ema200<=-0.05", d[d['dist_ema200'] <= -0.05])
    rep("macd_hist<=0", d[d['macd_hist'] <= 0])
    rep("ema200<=0 & macd<=0", d[(d['dist_ema200'] <= 0) & (d['macd_hist'] <= 0)])

print("\n=== REMOVE-TOP-N (ALL tf, dist_ema200<=-0.05) ===")
g = df[df['dist_ema200'] <= -0.05].sort_values('net03', ascending=False)
print(f"  full: n={len(g)} mean_net03={g['net03'].mean():+.3f}")
flip = next((k for k in range(len(g)) if g.iloc[k:]['net03'].mean() <= 0), None)
for k in [1, 2, 3, 5, 10]:
    print(f"  remove top {k}: mean_net03={g.iloc[k:]['net03'].mean():+.3f}")
print(f"  flip-negative after removing: {flip} of {len(g)}")

print("\n=== WEEKLY stability (dist_ema200<=-0.05) ===")
g2 = df[df['dist_ema200'] <= -0.05].copy()
g2['wk'] = g2['stime'].dt.isocalendar().week
print(g2.groupby('wk').agg(n=('net03', 'size'), net03=('net03', 'mean'), wr=('is_win', 'mean')).round(3).to_string())
