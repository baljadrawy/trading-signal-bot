#!/usr/bin/env python3
"""B1 OOS analysis — threshold sweep on reconstructed bot score.
Winsorize 1/99, symbol-clustered bootstrap CI, leave-one-YEAR-out, remove-top-N.
"""
import sys
import numpy as np, pandas as pd
np.random.seed(7)
path = sys.argv[1] if len(sys.argv)>1 else "out/b1_oos_trades.csv"
df = pd.read_csv(path)
df["fscore"] = np.floor(df["score"]).astype(int)   # integer bucket like DB score
print(f"N={len(df)}  symbols={df.symbol.nunique()}  years={sorted(df.year.unique())}")

# winsorize gross 1/99
lo,hi = df["gross"].quantile([0.01,0.99])
df["gw"] = df["gross"].clip(lo,hi)
print(f"winsor [{lo:.3f},{hi:.3f}] raw[{df.gross.min():.1f},{df.gross.max():.1f}]")

def ne(sub,fee): return sub["gw"].mean()-fee

print("\n=== PER-BUCKET floor(score) ===")
print(f"{'sc':>3} {'n':>7} {'nsym':>5} {'reachT1%':>8} {'gross':>8} {'net03':>8} {'net06':>8}")
for sc in sorted(df.fscore.unique()):
    s=df[df.fscore==sc]
    print(f"{sc:>3} {len(s):>7} {s.symbol.nunique():>5} {s.reach_t1.mean()*100:>8.1f} "
          f"{ne(s,0):>+8.3f} {ne(s,0.3):>+8.3f} {ne(s,0.6):>+8.3f}")

def clustered_ci(sub,fee=0.3,reps=2000):
    syms=sub["symbol"].values; g=sub["gw"].values
    uniq=np.unique(syms); by={s:g[syms==s] for s in uniq}
    out=np.empty(reps)
    for b in range(reps):
        pick=np.random.choice(uniq,len(uniq),replace=True)
        out[b]=np.concatenate([by[s] for s in pick]).mean()-fee
    return np.percentile(out,[2.5,97.5])

print("\n=== CUMULATIVE score>=T sweep ===")
print(f"{'T':>3} {'n':>7} {'nsym':>5} {'reachT1%':>8} {'gross':>8} {'net03':>8} {'net06':>8}   net03 clustered95CI")
for T in sorted(df.fscore.unique()):
    s=df[df.score>=T]
    if len(s)<20: continue
    ci=clustered_ci(s,0.3)
    print(f"{T:>3} {len(s):>7} {s.symbol.nunique():>5} {s.reach_t1.mean()*100:>8.1f} "
          f"{ne(s,0):>+8.3f} {ne(s,0.3):>+8.3f} {ne(s,0.6):>+8.3f}   [{ci[0]:+.3f},{ci[1]:+.3f}]")

print("\n=== LEAVE-ONE-YEAR-OUT (net@0.3) ===")
yrs=[y for y in sorted(df.year.unique()) if y>2000]
for T in [2,3,4,5]:
    base=df[df.score>=T]
    cells=[]
    for y in yrs:
        s=base[base.year!=y]
        cells.append(f"{y}:{ne(s,0.3):+.3f}")
    # also per-year value
    print(f"score>={T} full={ne(base,0.3):+.3f} | LOYO " + " ".join(cells))
print("\n  per-year net@0.3 (score>=3):")
b=df[df.score>=3]
for y in yrs:
    s=b[b.year==y]
    print(f"    {y}: n={len(s):>6} net03={ne(s,0.3):+.3f} net06={ne(s,0.6):+.3f}")

print("\n=== REMOVE-TOP-N (sign flip) ===")
for T,fee in [(2,0.3),(3,0.3),(2,0.6)]:
    s=df[df.score>=T].sort_values("gw",ascending=False)["gw"].to_numpy()
    base=s.mean()-fee; flip=None
    if base>0:
        for k in range(1,200):
            if s[k:].mean()-fee<=0: flip=k; break
    print(f"score>={T} net{fee}: base={base:+.3f} n={len(s)} -> "
          + (f"flips after top-{flip}" if flip else "base<=0 (already negative)"))
