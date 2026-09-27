#!/usr/bin/env python3
"""B3 OOS feature-gate analysis on full historical engine (target_policy_bt arm-A natural entries).
Adversarial gates: dist_ema200 / macd_hist (top-2 from A2), plus cci20 both directions.
Robustness: winsorize gross 1/99, FAST exact symbol-clustered bootstrap CI (2000 reps) for net03 & net06,
t-stats, BH correction across the gate scan, per-tf, leave-one-year-out sign-count, remove-top-N,
symbol concentration. SURVIVES only if net-positive after fees AND clustered CI excludes 0
AND stable across years AND not concentration-fragile."""
import sys, numpy as np, pandas as pd
from scipy import stats
rng = np.random.default_rng(20260729)
P = sys.argv[1] if len(sys.argv) > 1 else "/home/tradmin/trading-signal-bot/research/skill_application/scripts/b3_trades.csv"
df = pd.read_csv(P)
for c in ['gross','dist_ema200','macd_hist','cci20','bb_pos','score','reach_t1','reach_t2','year']:
    df[c] = pd.to_numeric(df[c], errors='coerce')
lo,hi = df['gross'].quantile(0.01), df['gross'].quantile(0.99)
df['gross_w'] = df['gross'].clip(lo,hi)
df['net03'] = df['gross_w']-0.3
df['net06'] = df['gross_w']-0.6
df['symcode'] = df['symbol'].astype('category').cat.codes
print(f"OOS rows={len(df)} symbols={df['symbol'].nunique()} years={sorted(df['year'].dropna().unique().astype(int))}")
print(f"winsorize gross to [{lo:.3f},{hi:.3f}]  tf: {df['tf'].value_counts().to_dict()}")
print(f"BASELINE gross={df['gross_w'].mean():+.4f} net03={df['net03'].mean():+.4f} net06={df['net06'].mean():+.4f} "
      f"reachT1={df['reach_t1'].mean()*100:.1f}%")

def cluster_ci(sub, col, reps=2000):
    """Exact clustered bootstrap of the MEAN: resample symbols, mean = sum(picked sums)/sum(picked counts)."""
    codes = sub['symcode'].to_numpy(); vals = sub[col].to_numpy()
    uniq, inv = np.unique(codes, return_inverse=True)
    ns = len(uniq)
    ssum = np.bincount(inv, weights=vals, minlength=ns)
    scnt = np.bincount(inv, minlength=ns).astype(float)
    pick = rng.integers(0, ns, size=(reps, ns))
    num = ssum[pick].sum(axis=1); den = scnt[pick].sum(axis=1)
    m = num/den
    return np.percentile(m,2.5), np.percentile(m,97.5), ns

def tstat(sub, col):
    v = sub[col].to_numpy()
    return v.mean()/(v.std(ddof=1)/np.sqrt(len(v))) if len(v)>1 and v.std()>0 else 0.0

def report(name, sub, ci=True):
    n=len(sub); nsym=sub['symbol'].nunique()
    if n<20: print(f"  {name:30s} n={n:5d} (too small)"); return None
    wr=(sub['gross']>0.3).mean(); rt1=sub['reach_t1'].mean()*100
    g=sub['gross_w'].mean(); n03=sub['net03'].mean(); n06=sub['net06'].mean(); t03=tstat(sub,'net03')
    out={'name':name,'n':n,'nsym':nsym,'net03':n03,'net06':n06,'t03':t03}
    line=(f"  {name:30s} n={n:6d} sym={nsym:3d} reachT1={rt1:4.1f} wr={wr:.3f} "
          f"GROSS={g:+.3f} NET03={n03:+.3f} NET06={n06:+.3f} t03={t03:+.2f}")
    if ci:
        lo3,hi3,_=cluster_ci(sub,'net03'); lo6,hi6,_=cluster_ci(sub,'net06')
        s3='POS*' if lo3>0 else ('NEG*' if hi3<0 else '')
        out['ci03']=(lo3,hi3); out['ci06']=(lo6,hi6); out['star']=s3
        line+=f" CI03[{lo3:+.3f},{hi3:+.3f}] CI06[{lo6:+.3f},{hi6:+.3f}] {s3}"
    print(line); return out

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
    ("cci20<=-100", df[df['cci20']<=-100]),
    ("bb_pos<=0", df[df['bb_pos']<=0]),
]
print("\n=== GATES on FULL OOS (all tf 1h/4h/1d, all years) — symbol-clustered CI + t-stat ===")
results=[]
for name,sub in GATES:
    r=report(name,sub)
    if r: results.append((r,sub))

print("\n=== Benjamini-Hochberg across gate net03 (one-sided H0: mean<=0) ===")
tests=[(r['name'], r['t03'], len(s)) for r,s in results if r['name']!='BASELINE ungated']
pvals=[(nm, float(stats.t.sf(t, dfree-1)) if t>0 else 1.0) for nm,t,dfree in tests]
pvals_sorted=sorted(pvals, key=lambda x:x[1]); mm=len(pvals_sorted)
for i,(nm,p) in enumerate(pvals_sorted,1):
    q=p*mm/i
    print(f"  {nm:30s} p1sided={p:.4f} BH_q={min(q,1):.4f} {'SIG' if q<0.05 else ''}")

print("\n=== dist_ema200 quintile monotonicity (net03 winsorized) ===")
d=df.dropna(subset=['dist_ema200']).copy()
d['q']=pd.qcut(d['dist_ema200'],5,labels=False,duplicates='drop')
print(d.groupby('q').agg(n=('net03','size'),reachT1=('reach_t1','mean'),gross=('gross_w','mean'),
                         net03=('net03','mean'),wr=('gross',lambda x:(x>0.3).mean())).round(3).to_string())

print("\n=== PER-TF (dist_ema200<=-0.05 & macd_hist<=0 vs baseline; live's strongest tf was 1d) ===")
for tf in ['1h','4h','1d']:
    dt=df[df['tf']==tf]
    report(f"{tf} baseline", dt)
    report(f"{tf} dist_ema200<=-0.05", dt[dt['dist_ema200']<=-0.05])
    report(f"{tf} macd_hist<=0", dt[dt['macd_hist']<=0])

print("\n=== LEAVE-ONE-YEAR-OUT (gate dist_ema200<=-0.05, net03 per held-out year) ===")
g=df[df['dist_ema200']<=-0.05]
neg=0; tot=0
for y in sorted(df['year'].dropna().unique().astype(int)):
    ys=g[g['year']==y]
    if len(ys)>=20:
        tot+=1; sgn='NEG' if ys['net03'].mean()<=0 else 'pos'
        if ys['net03'].mean()<=0: neg+=1
        print(f"  year={y}: n={len(ys):6d} sym={ys['symbol'].nunique():3d} net03={ys['net03'].mean():+.3f} "
              f"net06={ys['net06'].mean():+.3f} reachT1={ys['reach_t1'].mean()*100:.1f}% [{sgn}]")
print(f"  -> years with net03<=0: {neg}/{tot}")

print("\n=== REMOVE-TOP-N concentration (gate dist_ema200<=-0.05, net03 desc) ===")
srt=g.sort_values('net03',ascending=False); base=srt['net03'].mean()
print(f"  full gate: n={len(srt)} mean_net03={base:+.3f}")
for k in [1,3,5,10,20,50,100,200]:
    if len(srt)>k: print(f"  remove top {k:4d}: mean_net03={srt.iloc[k:]['net03'].mean():+.3f}")
csum=srt['net03'].to_numpy()[::-1].cumsum()[::-1]  # mean after removing top k
cnt=np.arange(len(srt),0,-1)
meanrem=csum/cnt
flip=next((k for k in range(len(srt)) if meanrem[k]<=0), None)
print(f"  trades to remove to flip NEG: {flip} of {len(srt)} ({100*flip/len(srt):.2f}%)" if flip is not None else "  never flips")
sc=g.groupby('symbol')['net03'].agg(['size','sum','mean']).sort_values('sum',ascending=False)
totn=g['net03'].sum()
print(f"  top-5 symbols by summed net03 (of {totn:+.1f} total):"); print(sc.head(5).round(3).to_string())
nex=len(g)-sc['size'].head(5).sum(); ex5=totn-sc['sum'].head(5).sum()
print(f"  ex-top5-symbols total={ex5:+.1f} mean={ex5/nex:+.4f}  (n={nex})")
print("\nDONE")
