#!/usr/bin/env python3
"""B4 LIVE audit v2 — trade_type x macro (usdtd_trend) alignment, falsify-first.
Read-only. Gross from profit_percent (winsorized 1/99), net = gross-fee (0.3/0.6).
Symbol-clustered bootstrap CI (resample SYMBOLS). Interaction + rule comparison."""
import numpy as np, pandas as pd, scipy.stats as st
np.random.seed(7)
P='/home/tradmin/trading-signal-bot/research/skill_application/scripts/b4_live_fresh.csv'
cols=['sid','symbol','tf','tt','usdtd','btc','stime','result','gross','net_usdt','tr','sh','dur']
df=pd.read_csv(P,header=None,names=cols)
for c in ['tr','sh']: df[c]=df[c].map({'t':True,'f':False})
df['gross']=pd.to_numeric(df['gross'],errors='coerce')
df['stime']=pd.to_datetime(df['stime'])
df=df.dropna(subset=['gross','tt','usdtd']).reset_index(drop=True)
print(f"N={len(df)} syms={df.symbol.nunique()} range={df.stime.min().date()}->{df.stime.max().date()} months~{(df.stime.max()-df.stime.min()).days/30:.1f}")
lo,hi=np.percentile(df.gross,[1,99]); df['gw']=df.gross.clip(lo,hi)
print(f"winsor bounds gross=[{lo:.3f},{hi:.3f}] raw[{df.gross.min():.2f},{df.gross.max():.2f}]")

def cboot(sub,fee,reps=5000):
    syms=sub.symbol.unique(); grp={s:sub[sub.symbol==s].gw.values for s in syms}
    m=np.empty(reps)
    for k in range(reps):
        pk=np.random.choice(syms,len(syms),True)
        m[k]=np.concatenate([grp[s] for s in pk]).mean()-fee
    return np.percentile(m,[2.5,97.5]), (m>0).mean()

print("\n=== PER-CELL (gross winsorized; net after fee; symbol-clustered 95% CI on net@0.3) ===")
print(f"{'tt':9s}{'macro':8s}{'n':>4}{'syms':>5}{'gross':>8}{'net03':>8}{'net06':>8}   CI95(net03)        P(net03>0)")
for tt in ['reversion','momentum']:
    for mc in ['falling','flat','rising']:
        s=df[(df.tt==tt)&(df.usdtd==mc)]
        if len(s)==0: continue
        g=s.gw.mean(); ci,p=cboot(s,0.3)
        print(f"{tt:9s}{mc:8s}{len(s):>4}{s.symbol.nunique():>5}{g:>+8.3f}{g-0.3:>+8.3f}{g-0.6:>+8.3f}   [{ci[0]:+.3f},{ci[1]:+.3f}]   {p:.3f}")

print("\n=== DATA-DRIVEN macro-conditioning: best trade_type per macro state (gross) ===")
for mc in ['falling','flat','rising']:
    r=df[(df.tt=='reversion')&(df.usdtd==mc)].gw.mean()
    m=df[(df.tt=='momentum')&(df.usdtd==mc)].gw.mean()
    pick='reversion' if r>m else 'momentum'
    print(f"  {mc:8s}: reversion={r:+.3f}  momentum={m:+.3f}  -> PICK {pick}")

print("\n=== RULE PORTFOLIOS (net@0.3 & net@0.6, symbol-clustered CI) ===")
def rule_textbook(r): return (r.usdtd=='falling' and r.tt=='reversion') or (r.usdtd=='rising' and r.tt=='momentum') or (r.usdtd=='flat' and r.tt=='reversion')
def rule_flip(r): return r.tt=='reversion'                # 4f84717 flip = reversion-only
def rule_mom(r): return r.tt=='momentum'
def rule_all(r): return True
def rule_bestcell(r):   # in-sample optimal conditioning (peak-boundary reference)
    return r.tt=='reversion'  # data shows reversion wins in ALL states
rules=[('TEXTBOOK (rev-fall, mom-rise)',rule_textbook),
       ('FLIP=reversion-only (4f84717)',rule_flip),
       ('momentum-only',rule_mom),
       ('ALL trades',rule_all)]
for nm,fn in rules:
    s=df[df.apply(fn,axis=1)]
    g=s.gw.mean(); ci3,p3=cboot(s,0.3); ci6,p6=cboot(s,0.6)
    print(f"{nm:32s} n={len(s):3d} syms={s.symbol.nunique():2d} gross={g:+.3f} | net03={g-0.3:+.3f} CI[{ci3[0]:+.3f},{ci3[1]:+.3f}] P>0={p3:.3f} | net06={g-0.6:+.3f} P>0={p6:.3f}")

print("\n=== INTERACTION: does macro modulate the reversion-vs-momentum GROSS gap? (2-way) ===")
# Kruskal within each tt across macro; and diff-in-diff of the rev-mom gap
for tt in ['reversion','momentum']:
    g=[df[(df.tt==tt)&(df.usdtd==m)].gw.values for m in ['falling','flat','rising']]
    H,p=st.kruskal(*g)
    print(f"  {tt:9s} across macro: H={H:.3f} p={p:.3f} means fall={g[0].mean():+.3f} flat={g[1].mean():+.3f} rise={g[2].mean():+.3f}")
# Does the (reversion-momentum) gap differ by macro? bootstrap the gap per state
print("  gap = reversion_gross - momentum_gross per state:")
for mc in ['falling','flat','rising']:
    r=df[(df.tt=='reversion')&(df.usdtd==mc)].gw.values
    m=df[(df.tt=='momentum')&(df.usdtd==mc)].gw.values
    print(f"    {mc:8s}: gap={r.mean()-m.mean():+.3f} (rev n={len(r)} mom n={len(m)})")

print("\n=== BEST GROSS CELL (reversion+rising) remove-top-N concentration ===")
best=df[(df.tt=='reversion')&(df.usdtd=='rising')].sort_values('gw',ascending=False)
for n in [0,1,2,3,5]:
    t=best.iloc[n:]; print(f"  remove top {n}: n={len(t)} gross={t.gw.mean():+.3f} net03={t.gw.mean()-0.3:+.3f}")
print("=== reversion-only (the flip) remove-top-N ===")
rr=df[df.tt=='reversion'].sort_values('gw',ascending=False)
for n in [0,1,2,3,5,10]:
    t=rr.iloc[n:]; print(f"  remove top {n:2d}: n={len(t)} gross={t.gw.mean():+.3f} net03={t.gw.mean()-0.3:+.3f}")
