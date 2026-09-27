#!/usr/bin/env python3
"""Adversarial characterization of the only positive OOS cell: 1d.
Q: is the tiny 1d net03>0 a real edge, and does the dist_ema200 gate ADD to it? Test at 0.3 & 0.6 fees,
per-year, remove-top-N, and gate-minus-baseline difference bootstrap (clustered)."""
import numpy as np, pandas as pd
rng=np.random.default_rng(7)
df=pd.read_csv("/home/tradmin/trading-signal-bot/research/skill_application/scripts/b3_trades.csv")
for c in ['gross','dist_ema200','macd_hist','year','reach_t1']:
    df[c]=pd.to_numeric(df[c],errors='coerce')
lo,hi=df['gross'].quantile(0.01),df['gross'].quantile(0.99)
df['gross_w']=df['gross'].clip(lo,hi)
d1=df[df['tf']=='1d'].copy()
d1['symcode']=d1['symbol'].astype('category').cat.codes

def cl_ci(sub,vals,reps=3000):
    codes=sub['symcode'].to_numpy(); uniq,inv=np.unique(codes,return_inverse=True); ns=len(uniq)
    ssum=np.bincount(inv,weights=vals,minlength=ns); scnt=np.bincount(inv,minlength=ns).astype(float)
    pick=rng.integers(0,ns,size=(reps,ns)); m=ssum[pick].sum(1)/scnt[pick].sum(1)
    return np.percentile(m,2.5),np.percentile(m,97.5)

print(f"1d rows={len(d1)} sym={d1['symbol'].nunique()} years={sorted(d1['year'].dropna().unique().astype(int))}")
for fee,lab in [(0.3,'net03'),(0.6,'net06')]:
    print(f"\n--- fee {fee}% ---")
    for nm,sub in [("1d baseline",d1),("1d dist_ema200<=-0.05",d1[d1['dist_ema200']<=-0.05]),
                   ("1d dist_ema200<=-0.10",d1[d1['dist_ema200']<=-0.10]),
                   ("1d macd_hist<=0",d1[d1['macd_hist']<=0])]:
        v=sub['gross_w'].to_numpy()-fee
        loc,hic=cl_ci(sub,v); star='POS*' if loc>0 else ('NEG*' if hic<0 else '')
        print(f"  {nm:26s} n={len(sub):6d} mean={v.mean():+.3f} CI[{loc:+.3f},{hic:+.3f}] {star}")

print("\n--- 1d baseline net03 per-year (is the 0.3% positive stable?) ---")
neg=0;tot=0
for y in sorted(d1['year'].dropna().unique().astype(int)):
    ys=d1[d1['year']==y]
    if len(ys)>=30:
        m=(ys['gross_w']-0.3).mean(); tot+=1; neg+=int(m<=0)
        print(f"  {y}: n={len(ys):5d} net03={m:+.3f} net06={(ys['gross_w']-0.6).mean():+.3f}")
print(f"  years net03<=0: {neg}/{tot}")

print("\n--- 1d baseline net03 remove-top-N ---")
srt=(d1['gross_w']-0.3).sort_values(ascending=False).to_numpy()
for k in [1,5,10,25,50,100]:
    print(f"  remove top {k:4d}: mean={srt[k:].mean():+.4f}")

print("\n--- gate-minus-baseline (does dist_ema200<=-0.05 ADD value on 1d?) clustered diff bootstrap ---")
base=d1; gate=d1[d1['dist_ema200']<=-0.05]
diff=gate['gross_w'].mean()-base['gross_w'].mean()
# clustered bootstrap of difference of means (resample symbols shared)
codes=d1['symcode'].to_numpy(); uniq=np.unique(codes)
bym={s:{'g':gate.index[gate['symcode']==s].to_numpy(),'b':base.index[base['symcode']==s].to_numpy()} for s in uniq}
gv=gate['gross_w']; bv=base['gross_w']; reps=3000; dd=np.empty(reps)
for r in range(reps):
    pick=rng.choice(uniq,size=len(uniq),replace=True)
    gi=np.concatenate([bym[s]['g'] for s in pick]); bi=np.concatenate([bym[s]['b'] for s in pick])
    dd[r]=(gv.loc[gi].mean() if len(gi) else np.nan)-(bv.loc[bi].mean() if len(bi) else np.nan)
print(f"  gate_mean-base_mean = {diff:+.4f}  CI[{np.nanpercentile(dd,2.5):+.4f},{np.nanpercentile(dd,97.5):+.4f}]")
print("  (CI includes 0 or negative => gate adds NO value)")
