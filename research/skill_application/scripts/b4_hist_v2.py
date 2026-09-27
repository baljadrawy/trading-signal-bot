#!/usr/bin/env python3
"""B4 HISTORICAL OOS analysis on saved reversion rows (b4_hist_rows.csv).
Engine generates REVERSION (down-market) signals ONLY -> tests the reversion leg of the
alignment premise: does reversion's post-fee expectancy depend on macro state, and is any
ordering stable across years? Symbol-clustered CI + leave-one-year-out + remove-top-N.
Universe cap = top-80 symbols by 1d-file count (STATED). Macro proxy = BTC 3d return."""
import numpy as np, pandas as pd, scipy.stats as st
np.random.seed(7)
R=pd.read_csv('/home/tradmin/trading-signal-bot/research/skill_application/scripts/b4_hist_rows.csv')
# re-winsorize defensively at 1/99
lo,hi=np.percentile(R.gross,[1,99]); R['gw']=R.gross.clip(lo,hi)
FEE=0.3; FEE6=0.6
print(f"rows={len(R)} syms={R.sym.nunique()} years={R.year.min()}-{R.year.max()} winsor=[{lo:.2f},{hi:.2f}]")
print(f"macro dist: {R.macro.value_counts().to_dict()}")
print(f"NOTE: reversion-only (engine has no momentum path; no 15m history). break-even exits (gross=0) = {round((R.gross==0).mean()*100,1)}%")

def cboot(sub,fee,reps=3000):
    syms=sub.sym.unique(); grp={s:sub[sub.sym==s].gw.values for s in syms}
    m=np.empty(reps)
    for k in range(reps):
        pk=np.random.choice(syms,len(syms),True)
        m[k]=np.concatenate([grp[s] for s in pk]).mean()-fee
    return np.percentile(m,[2.5,97.5]),(m>0).mean()

print("\n=== PER MACRO-STATE (ALL years): net after fees + symbol-clustered CI ===")
print(f"{'state':8s}{'n':>7}{'syms':>5}{'gross':>8}{'net03':>8}{'net06':>8}   CI95(net03)        P(net03>0)")
for mc in ['falling','flat','rising']:
    s=R[R.macro==mc]; g=s.gw.mean(); ci,p=cboot(s,FEE)
    print(f"{mc:8s}{len(s):>7}{s.sym.nunique():>5}{g:>+8.3f}{g-FEE:>+8.3f}{g-FEE6:>+8.3f}   [{ci[0]:+.3f},{ci[1]:+.3f}]   {p:.3f}")

print("\n=== ALIGNMENT ORDERING CLAIM: reversion better in FALLING (risk-on) than RISING? ===")
gf=R[R.macro=='falling'].gw.mean(); gr=R[R.macro=='rising'].gw.mean()
print(f"  falling gross={gf:+.3f}  rising gross={gr:+.3f}  falling>rising? {gf>gr}")
# Kruskal across macro
g=[R[R.macro==m].gw.values for m in ['falling','flat','rising']]
H,p=st.kruskal(*g); print(f"  Kruskal reversion across macro: H={H:.3f} p={p:.4f}")

print("\n=== LEAVE-ONE-YEAR-OUT: falling>rising each dropped-year? & any state net03>0? ===")
years=sorted(R.year.unique())
print(f"{'drop_yr':>8} | {'fall_net03':>10} {'flat_net03':>10} {'rise_net03':>10} | fall>rise?")
flags=[]
for y in years:
    sub=R[R.year!=y]
    vals={m:sub[sub.macro==m].gw.mean()-FEE for m in ['falling','flat','rising']}
    fw=vals['falling']>vals['rising']; flags.append(fw)
    anypos=any(v>0 for v in vals.values())
    print(f"{y:>8} | {vals['falling']:>+10.3f} {vals['flat']:>+10.3f} {vals['rise' if False else 'rising']:>+10.3f} | {fw}  anyPos={anypos}")
print(f"  falling>rising held in {sum(flags)}/{len(flags)} LOYO folds")

print("\n=== PER-YEAR raw (is the ordering stable? sign flips = artifact) ===")
print(f"{'year':>6} | {'fall_n':>6}{'fall03':>9} | {'flat_n':>6}{'flat03':>9} | {'rise_n':>6}{'rise03':>9} | fall>rise")
signs=[]
for y in years:
    Ry=R[R.year==y]; d={}
    for m in ['falling','flat','rising']:
        s=Ry[Ry.macro==m]; d[m]=(len(s), s.gw.mean()-FEE if len(s) else float('nan'))
    fw=(d['falling'][0]>0 and d['rising'][0]>0 and d['falling'][1]>d['rising'][1])
    signs.append(fw)
    print(f"{y:>6} | {d['falling'][0]:>6}{d['falling'][1]:>+9.3f} | {d['flat'][0]:>6}{d['flat'][1]:>+9.3f} | {d['rising'][0]:>6}{d['rising'][1]:>+9.3f} | {fw}")
print(f"  falling>rising in {sum(signs)}/{len(signs)} individual years")

print("\n=== REMOVE-TOP-N on best gross state ===")
best=max(['falling','flat','rising'],key=lambda m:R[R.macro==m].gw.mean())
bs=R[R.macro==best].sort_values('gw',ascending=False)
print(f"  best state = {best}")
for n in [0,5,10,20,50,100]:
    t=bs.iloc[n:]; print(f"  remove top {n:>3}: n={len(t):>6} gross={t.gw.mean():+.3f} net03={t.gw.mean()-FEE:+.3f}")
