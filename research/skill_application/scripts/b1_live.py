#!/usr/bin/env python3
"""B1 LIVE — score-threshold selectivity on the live join.
Falsify-first: does raising MIN_SCORE turn net expectancy positive, robustly?
Win-rate is NOT primary. Winsorize 1/99, symbol-clustered bootstrap CI,
leave-one-MONTH-out (only ~4 months live), remove-top-N concentration.
"""
import numpy as np, pandas as pd

np.random.seed(7)
df = pd.read_csv("scripts/b1_live.csv", header=None,
                names=["id","symbol","score","tf","ttype","mc","ym","gross","usdt","result","stop_hit","tgt"])
df["gross"] = pd.to_numeric(df["gross"], errors="coerce")
df = df.dropna(subset=["gross","score"]).copy()
df["score"] = df["score"].astype(int)
print(f"N total = {len(df)}  symbols={df.symbol.nunique()}  months={sorted(df.ym.unique())}")
print(f"April share = {(df.ym=='2026-04').mean():.1%}")

# --- winsorize gross returns at 1/99 pct ---
lo, hi = df["gross"].quantile([0.01, 0.99])
df["gw"] = df["gross"].clip(lo, hi)
print(f"winsor bounds [{lo:.3f}, {hi:.3f}]  (raw min/max {df.gross.min():.2f}/{df.gross.max():.2f})")

FEES = {"gross":0.0, "net03":0.3, "net06":0.6}

def net_exp(sub, fee):  # mean net expectancy % after round-trip fee
    return sub["gw"].mean() - fee

print("\n=== PER-BUCKET (winsorized gross mean, then subtract fee) ===")
print(f"{'score':>5} {'n':>5} {'WR%':>6} {'gross':>8} {'net03':>8} {'net06':>8}")
for sc in sorted(df.score.unique()):
    sub = df[df.score==sc]
    wr = (sub.result=="WIN").mean()*100
    print(f"{sc:>5} {len(sub):>5} {wr:>6.1f} {net_exp(sub,0):>+8.3f} {net_exp(sub,0.3):>+8.3f} {net_exp(sub,0.6):>+8.3f}")

# --- symbol-clustered bootstrap CI of net@0.3 expectancy ---
def clustered_ci(sub, fee=0.3, reps=3000):
    syms = sub["symbol"].values
    g = sub["gw"].values
    uniq = np.unique(syms)
    by = {s: g[syms==s] for s in uniq}
    means = np.empty(reps)
    for b in range(reps):
        pick = np.random.choice(uniq, size=len(uniq), replace=True)
        vals = np.concatenate([by[s] for s in pick])
        means[b] = vals.mean() - fee
    return np.percentile(means, [2.5, 97.5])

print("\n=== CUMULATIVE score>=T sweep (raising selectivity) ===")
print(f"{'T':>3} {'n':>5} {'nsym':>5} {'WR%':>6} {'gross':>8} {'net03':>8} {'net06':>8}   net03 clustered95CI")
sweep = {}
for T in sorted(df.score.unique()):
    sub = df[df.score>=T]
    if len(sub) < 5: continue
    wr = (sub.result=="WIN").mean()*100
    ci = clustered_ci(sub, 0.3)
    sweep[T] = (len(sub), net_exp(sub,0.3), ci)
    print(f"{T:>3} {len(sub):>5} {sub.symbol.nunique():>5} {wr:>6.1f} {net_exp(sub,0):>+8.3f} "
          f"{net_exp(sub,0.3):>+8.3f} {net_exp(sub,0.6):>+8.3f}   [{ci[0]:+.3f}, {ci[1]:+.3f}]")

# --- best single bucket (score==2 looked positive gross) full robustness ---
print("\n=== FOCUS: individual buckets net@0.3 clustered CI ===")
for sc in [2,3,4,5]:
    sub = df[df.score==sc]
    ci = clustered_ci(sub, 0.3)
    print(f"score={sc:>1} n={len(sub):>4} nsym={sub.symbol.nunique():>3} net03={net_exp(sub,0.3):+.3f}  CI95[{ci[0]:+.3f},{ci[1]:+.3f}]")

# --- leave-one-MONTH-out stability (net@0.3) for score>=2 and each bucket ---
print("\n=== LEAVE-ONE-MONTH-OUT (net@0.3) ===")
months = sorted(df.ym.unique())
for label, mask in [("score>=2", df.score>=2), ("score>=3", df.score>=3),
                    ("score>=4", df.score>=4), ("score==2", df.score==2), ("score==3", df.score==3)]:
    row=[]
    for m in months:
        sub = df[mask & (df.ym!=m)]
        row.append(f"{m}:{net_exp(sub,0.3):+.3f}(n{len(sub)})")
    # per-month value too
    full = df[mask]
    print(f"{label:>9} full={net_exp(full,0.3):+.3f} | drop-> " + "  ".join(row))
print("\n  per-month net@0.3 by bucket score>=2:")
for m in months:
    sub = df[(df.score>=2)&(df.ym==m)]
    print(f"    {m}: n={len(sub):>4} net03={net_exp(sub,0.3):+.3f}")

# --- remove-top-N concentration: how many best trades flip the sign? ---
print("\n=== REMOVE-TOP-N (does removing best winners flip sign?) ===")
for label, mask, fee in [("score>=2 net03", df.score>=2, 0.3), ("score==2 net03", df.score==2, 0.3),
                         ("score>=2 net06", df.score>=2, 0.6)]:
    sub = df[mask].sort_values("gw", ascending=False).reset_index(drop=True)
    base = sub["gw"].mean()-fee
    flipped=None
    for k in range(0, min(40,len(sub))):
        m = sub["gw"].iloc[k:].mean()-fee
        if base>0 and m<=0:
            flipped=k; break
    print(f"{label}: base={base:+.3f} n={len(sub)}  -> sign flips after removing top-{flipped} trades"
          + ("" if flipped else "  (already <=0 or never flips)"))
