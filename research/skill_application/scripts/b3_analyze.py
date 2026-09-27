#!/usr/bin/env python3
"""
TASK B3 analysis: apply feature gates to the OOS arm-A trades and stress-test.
Robustness: winsorize 1/99, symbol-clustered bootstrap CI (2000 reps), leave-one-year-out,
remove-top-N sign flip, per-tf, per-year. Adversarial: a gate must beat the ungated
baseline AND have a symbol-clustered CI excluding 0 AND survive LOYO AND not be
concentration-fragile.
"""
import sys, numpy as np, pandas as pd
rng = np.random.default_rng(12345)
P = sys.argv[1] if len(sys.argv) > 1 else "/home/tradmin/trading-signal-bot/research/skill_application/scripts/b3_trades.csv"
df = pd.read_csv(P)
for c in ['gross', 'dist_ema200', 'macd_hist', 'cci20', 'bb_pos', 'score']:
    df[c] = pd.to_numeric(df[c], errors='coerce')

# global winsorize of gross at 1/99
lo, hi = df['gross'].quantile(0.01), df['gross'].quantile(0.99)
df['gross_w'] = df['gross'].clip(lo, hi)
df['net03'] = df['gross_w'] - 0.3
df['net06'] = df['gross_w'] - 0.6
print(f"rows={len(df)} symbols={df['symbol'].nunique()} years={sorted(df['year'].unique())}")
print(f"winsorize gross to [{lo:.3f},{hi:.3f}]  tf mix:\n{df['tf'].value_counts().to_string()}")


def cluster_ci(sub, col, reps=2000):
    uniq = sub['symbol'].unique()
    by = {s: sub.index[sub['symbol'] == s].to_numpy() for s in uniq}
    vals = sub[col]
    means = np.empty(reps)
    for r in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([by[s] for s in pick])
        means[r] = vals.loc[idx].mean()
    return np.percentile(means, 2.5), np.percentile(means, 97.5)


def report(name, sub, ci=True):
    n = len(sub); nsym = sub['symbol'].nunique()
    if n < 20:
        print(f"  {name:34s} n={n:5d}  (too small)")
        return
    wr = (sub['gross'] > 0.3).mean()
    g = sub['gross_w'].mean(); n03 = sub['net03'].mean(); n06 = sub['net06'].mean()
    rt1 = sub['reach_t1'].mean()
    line = (f"  {name:34s} n={n:5d} sym={nsym:3d} reachT1={rt1:.2f} wr@.3={wr:.3f} "
            f"GROSS={g:+.3f} NET03={n03:+.3f} NET06={n06:+.3f}")
    if ci:
        lo3, hi3 = cluster_ci(sub, 'net03')
        star = 'POS*' if lo3 > 0 else ('NEG*' if hi3 < 0 else '')
        line += f"  CI_net03[{lo3:+.3f},{hi3:+.3f}] {star}"
    print(line)


GATES = [
    ("BASELINE ungated", df),
    ("dist_ema200<=0", df[df['dist_ema200'] <= 0]),
    ("dist_ema200<=-0.05", df[df['dist_ema200'] <= -0.05]),
    ("dist_ema200<=-0.10", df[df['dist_ema200'] <= -0.10]),
    ("macd_hist<=0", df[df['macd_hist'] <= 0]),
    ("ema200<=0 & macd<=0", df[(df['dist_ema200'] <= 0) & (df['macd_hist'] <= 0)]),
    ("ema200<=-0.05 & macd<=0", df[(df['dist_ema200'] <= -0.05) & (df['macd_hist'] <= 0)]),
    ("cci20>=0", df[df['cci20'] >= 0]),
    ("cci20>=100", df[df['cci20'] >= 100]),
    ("bb_pos<=0", df[df['bb_pos'] <= 0]),
]

print("\n=== GATES on FULL OOS (all tf, all years) — symbol-clustered CI ===")
for name, sub in GATES:
    report(name, sub)

print("\n=== quantile monotonicity of dist_ema200 (net03, winsorized) ===")
d = df.dropna(subset=['dist_ema200']).copy()
d['q'] = pd.qcut(d['dist_ema200'], 5, labels=False, duplicates='drop')
print(d.groupby('q').agg(n=('net03', 'size'), reachT1=('reach_t1', 'mean'),
                         gross=('gross_w', 'mean'), net03=('net03', 'mean')).round(3).to_string())

print("\n=== 1d-ONLY (closest to the live-join where dist_ema200 was strongest) ===")
d1 = df[df['tf'] == '1d']
for name, subfn in [("BASELINE 1d", d1),
                    ("1d dist_ema200<=0", d1[d1['dist_ema200'] <= 0]),
                    ("1d dist_ema200<=-0.05", d1[d1['dist_ema200'] <= -0.05]),
                    ("1d macd_hist<=0", d1[d1['macd_hist'] <= 0])]:
    report(name, subfn)

print("\n=== LEAVE-ONE-YEAR-OUT (best gate dist_ema200<=-0.05, net03 mean each held-out year) ===")
g = df[df['dist_ema200'] <= -0.05]
for y in sorted(df['year'].unique()):
    yr_sub = g[g['year'] == y]
    if len(yr_sub) >= 20:
        print(f"  year={y}: n={len(yr_sub):5d} sym={yr_sub['symbol'].nunique():3d} "
              f"net03={yr_sub['net03'].mean():+.3f} reachT1={yr_sub['reach_t1'].mean():.2f}")
neg_years = sum(1 for y in sorted(df['year'].unique())
                if len(g[g['year'] == y]) >= 20 and g[g['year'] == y]['net03'].mean() <= 0)
print(f"  -> years with net03<=0: {neg_years}")

print("\n=== REMOVE-TOP-N concentration (gate dist_ema200<=-0.05, by net03 desc) ===")
srt = g.sort_values('net03', ascending=False)
base = srt['net03'].mean()
print(f"  full gate: n={len(srt)} mean_net03={base:+.3f}")
flip = None
for k in [1, 3, 5, 10, 20, 50, 100]:
    m = srt.iloc[k:]['net03'].mean()
    print(f"  remove top {k:4d}: mean_net03={m:+.3f} {'(FLIPPED NEG)' if m <= 0 else ''}")
for k in range(len(srt)):
    if srt.iloc[k:]['net03'].mean() <= 0:
        flip = k; break
print(f"  trades to remove to flip NEGATIVE: {flip} of {len(srt)} ({100*flip/len(srt):.1f}%)")

# symbol concentration
sc = g.groupby('symbol')['net03'].agg(['size', 'sum', 'mean']).sort_values('sum', ascending=False)
tot = g['net03'].sum()
print(f"\n  top-5 symbols by summed net03 (of {tot:+.1f} total):")
print(sc.head(5).round(3).to_string())
ex5 = tot - sc['sum'].head(5).sum()
print(f"  total ex-top5-symbols={ex5:+.1f}  (mean would be {ex5/(len(g)-sc['size'].head(5).sum()):+.4f})")
