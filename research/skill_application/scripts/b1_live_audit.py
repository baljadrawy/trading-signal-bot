#!/usr/bin/env python3
"""B1 LIVE audit — score-threshold selectivity, falsify-first.
Net expectancy % = winsorized(1/99) mean gross% - fee. profit_usdt is NOT net
(it is gross%*0.5) so we do NOT use it for expectancy. Symbol-clustered bootstrap
CI (3000 reps), leave-one-month-out, remove-top-N, within-month score slope.
"""
import numpy as np, pandas as pd
np.random.seed(7)
cols=["id","symbol","score","tf","ttype","mc","ym","gross","usdt","result","stop_hit","tgt"]
df=pd.read_csv("scripts/b1_live_fresh.csv",header=None,names=cols)
df["gross"]=pd.to_numeric(df["gross"],errors="coerce")
df=df.dropna(subset=["gross","score"]).copy(); df["score"]=df["score"].astype(int)
df["win"]=(df["result"]=="WIN").astype(int)
print(f"N={len(df)} symbols={df.symbol.nunique()} months={sorted(df.ym.unique())}")
print(f"April share={ (df.ym=='2026-04').mean():.1%}")

# integrity: profit_usdt vs gross
print(f"[integrity] max|usdt - gross*0.5| = {(df.usdt-df.gross*0.5).abs().max():.2e}  -> profit_usdt is GROSS*0.5, NOT net of fees")

lo,hi=df["gross"].quantile([0.01,0.99]); df["gw"]=df["gross"].clip(lo,hi)
print(f"winsor bounds [{lo:.3f},{hi:.3f}] raw[{df.gross.min():.2f},{df.gross.max():.2f}]")

def ne(sub,fee): return sub["gw"].mean()-fee

print("\n=== PER-BUCKET (winsorized mean gross - fee) ===")
print(f"{'sc':>3}{'n':>6}{'nsym':>5}{'WR%':>7}{'gross':>9}{'net03':>9}{'net06':>9}")
for sc in sorted(df.score.unique()):
    s=df[df.score==sc]
    print(f"{sc:>3}{len(s):>6}{s.symbol.nunique():>5}{s.win.mean()*100:>7.1f}{ne(s,0):>+9.3f}{ne(s,0.3):>+9.3f}{ne(s,0.6):>+9.3f}")

def clustered_ci(sub,fee=0.3,reps=3000):
    syms=sub["symbol"].values; g=sub["gw"].values
    uniq=np.unique(syms); by={s:g[syms==s] for s in uniq}
    out=np.empty(reps)
    for b in range(reps):
        pick=np.random.choice(uniq,len(uniq),replace=True)
        out[b]=np.concatenate([by[s] for s in pick]).mean()-fee
    return np.percentile(out,[2.5,97.5])

print("\n=== CUMULATIVE score>=T sweep (RAISING selectivity) ===")
print(f"{'T':>3}{'n':>6}{'nsym':>5}{'WR%':>7}{'gross':>9}{'net03':>9}{'net06':>9}   net03 clustered95CI")
for T in sorted(df.score.unique()):
    s=df[df.score>=T]
    if len(s)<10: continue
    ci=clustered_ci(s,0.3)
    print(f"{T:>3}{len(s):>6}{s.symbol.nunique():>5}{s.win.mean()*100:>7.1f}{ne(s,0):>+9.3f}{ne(s,0.3):>+9.3f}{ne(s,0.6):>+9.3f}   [{ci[0]:+.3f},{ci[1]:+.3f}]")

print("\n=== per-bucket net03 clustered CI (individual score) ===")
for sc in sorted(df.score.unique()):
    s=df[df.score==sc]
    if len(s)<10: continue
    ci=clustered_ci(s,0.3)
    print(f"score={sc} n={len(s):>4} nsym={s.symbol.nunique():>3} net03={ne(s,0.3):+.3f} CI95[{ci[0]:+.3f},{ci[1]:+.3f}]  excl0={'Y' if (ci[0]>0 or ci[1]<0) else 'n'}")

print("\n=== WITHIN-MONTH score slope (score confounded w/ time?) ===")
for m in sorted(df.ym.unique()):
    sub=df[df.ym==m]
    parts=[]
    for sc in sorted(sub.score.unique()):
        s=sub[sub.score==sc]
        parts.append(f"s{sc}:n{len(s)} g{ne(s,0):+.2f}")
    # corr of score vs gross within month
    c=sub[["score","gw"]].corr().iloc[0,1] if sub.score.nunique()>1 else float('nan')
    print(f"  {m} (n{len(sub)} corr(score,gross)={c:+.3f}): " + "  ".join(parts))

print("\n=== LEAVE-ONE-MONTH-OUT net03 ===")
months=sorted(df.ym.unique())
for label,mask in [("all(>=0)",df.score>=0),("score>=2",df.score>=2),("score>=3",df.score>=3),
                   ("score>=4",df.score>=4),("score==2",df.score==2),("score==3",df.score==3)]:
    row=[]
    for m in months:
        s=df[mask&(df.ym!=m)]; row.append(f"drop{m[-2:]}:{ne(s,0.3):+.3f}")
    print(f"{label:>9} full={ne(df[mask],0.3):+.3f} | " + " ".join(row))

print("\n=== REMOVE-TOP-N (how many best trades flip sign) ===")
for label,mask,fee in [("score>=2 net00",df.score>=2,0.0),("score>=2 net03",df.score>=2,0.3),
                       ("score==2 net03",df.score==2,0.3),("score==2 net00",df.score==2,0.0)]:
    v=df[mask].sort_values("gw",ascending=False)["gw"].to_numpy()
    base=v.mean()-fee; flip=None
    if base>0:
        for k in range(1,len(v)):
            if v[k:].mean()-fee<=0: flip=k; break
    print(f"{label}: base={base:+.3f} n={len(v)} -> "+(f"flips after removing top-{flip}" if flip else "base<=0 (already negative)"))
