#!/usr/bin/env python3
"""Aggregate OOS trades: per-TF net expectancy, symbol-clustered CI, leave-one-year-out, concentration."""
import numpy as np, pandas as pd, sys
CSV="/home/tradmin/trading-signal-bot/research/skill_application/scripts/b2_oos_trades.csv"
df=pd.read_csv(CSV)
print(f"trades={len(df)}  symbols={df.symbol.nunique()}  years={sorted(df.year.unique())}")
print("per-TF counts:\n", df.groupby('tf').size())

def winsor(x,lo=1,hi=99):
    a,b=np.percentile(x,[lo,hi]); return np.clip(x,a,b)

def clustered_boot(sub,fee,reps=2000,seed=0):
    rng=np.random.default_rng(seed)
    g={s:(winsor_map[s]-fee) for s in sub.symbol.unique()}
    syms=np.array(list(g.keys())); means=np.empty(reps)
    for i in range(reps):
        pick=rng.choice(syms,size=len(syms),replace=True)
        means[i]=np.concatenate([g[s] for s in pick]).mean()
    return np.percentile(means,[2.5,97.5])

def analyze(sub,label,fee=0.3):
    global winsor_map
    n=len(sub); nsym=sub.symbol.nunique()
    gw=winsor(sub['gross'].values)
    sub=sub.assign(gw=gw)
    winsor_map={s:sub.loc[sub.symbol==s,'gw'].values for s in sub.symbol.unique()}
    net=gw-fee
    mean_net=net.mean(); wr=(net>0).mean()*100
    pos=net[net>0].sum(); neg=-net[net<0].sum(); pf=pos/neg if neg>0 else np.inf
    ci=clustered_boot(sub,fee)
    reach_t1=sub['reach_t1'].mean()*100
    # remove-top-N: if total positive, how many top winners flip it negative
    tot=net.sum(); flip=None
    if tot>0:
        s=np.sort(net)[::-1]; run=tot
        for i,v in enumerate(s):
            run-=v
            if run<0: flip=i+1; break
    return dict(label=label,n=n,nsym=nsym,mean_net=mean_net,wr=wr,pf=pf,reach_t1=reach_t1,
                ci_lo=ci[0],ci_hi=ci[1],flip=flip,tot=tot)

def show(r):
    pf='inf' if r['pf']==np.inf else f"{r['pf']:.3f}"
    tag='CI_EXCLUDES_0' if (r['ci_lo']>0 or r['ci_hi']<0) else 'CI_INCLUDES_0'
    print(f"{r['label']:<16} n={r['n']:>6} sym={r['nsym']:>3} reachT1={r['reach_t1']:>4.1f}% "
          f"meanNet={r['mean_net']:>+7.3f}% WR={r['wr']:>4.1f}% PF={pf:>5} "
          f"CI95=[{r['ci_lo']:>+6.3f},{r['ci_hi']:>+6.3f}] {tag}")

for fee in (0.3,0.6):
    print(f"\n=========== SINGLE TFS (fee={fee}%) ===========")
    for tf in ['1h','4h','1d']:
        show(analyze(df[df.tf==tf],tf,fee))
    print(f"----------- SUBSETS (fee={fee}%) -----------")
    for lbl,tfs in {'4h+1d':['4h','1d'],'1h+4h+1d':['1h','4h','1d']}.items():
        show(analyze(df[df.tf.isin(tfs)],lbl,fee))

print("\n=========== LEAVE-ONE-YEAR-OUT (mean net% @0.3, winsor within each panel) ===========")
years=sorted(df.year.unique())
for tf in ['4h','1d']:
    sub=df[df.tf==tf]
    loo=[]
    for y in years:
        s2=sub[sub.year!=y]
        if len(s2)==0: loo.append('—'); continue
        loo.append(f"{(winsor(s2.gross.values)-0.3).mean():+.3f}")
    print(f"{tf:<4} drop-each-year -> " + "  ".join(f"{y}:{v}" for y,v in zip(years,loo)))
    peryr=[]
    for y in years:
        s2=sub[sub.year==y]
        if len(s2)==0: peryr.append(f"{y}:—"); continue
        peryr.append(f"{y}:{(winsor(s2.gross.values)-0.3).mean():+.3f}(n{len(s2)})")
    print(f"     per-year standalone -> " + "  ".join(peryr))
