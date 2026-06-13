#!/usr/bin/env python3
"""Rolling Walk-Forward صارم: نوافذ متحرّكة (train 12 شهر / test 3 أشهر، خطوة 3 أشهر).
في كل نافذة: انتقاء التهيئة آلياً من TRAIN فقط (أعلى Sharpe)، ثم تطبيق أعمى على TEST.
+ Stability by Universe Size (Top 20/30/50/100) عبر النوافذ.
الانتقاء داخل كل نافذة = لا data-snooping من رؤية كامل البيانات.
"""
import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA

FEE=0.004; FUND=0.003
syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
closes={}; dvol={}
for s in syms:
    df=load(s,'1d')
    if df is None: continue
    ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
    c=pd.Series(df['close'].values,index=ix); c=c[~c.index.duplicated()]
    d=pd.Series((df['close']*df['volume']).values,index=ix); d=d[~d.index.duplicated()]
    closes[s]=c; dvol[s]=d
panel=pd.DataFrame(closes).sort_index(); dv=pd.DataFrame(dvol).reindex(panel.index)
idx=panel.index
btc=panel['BTCUSDT'].dropna(); ema50=btc.ewm(span=50).mean(); ema200=btc.ewm(span=200).mean()
def riskon(date):
    p=btc.get(date,np.nan); e50=ema50.get(date,np.nan); e200=ema200.get(date,np.nan)
    if np.isnan(p) or np.isnan(e200): return True
    return p>e50 and p>e200
def maxdd(eq):
    eq=np.array(eq); pk=np.maximum.accumulate(eq); return float(((eq-pk)/pk).min()*100)

# نحسب سلسلة عوائد كل تهيئة مرة واحدة على كامل المدى (date->ret) ثم نقطّعها للنوافذ
def returns_series(look,hold,dec,univ):
    pl=set(); ps=set(); out={}; i=look
    while i+hold<len(idx):
        date=idx[i]; now=panel.iloc[i]; fut=panel.iloc[i+hold]; past=panel.iloc[i-look]
        fwd=(fut/now-1); ret=0.0; L=set(); S=set()
        if riskon(date):
            mom=(now/past-1); v=mom.notna()&fwd.notna()&past.notna()&(now>0); mom=mom[v]
            liq=dv.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(mom.index)]
            mom=mom[mom.index.isin(set(liq.sort_values(ascending=False).head(univ).index))]
            if len(mom)>=10:
                k=max(1,int(len(mom)*dec))
                L=set(mom.sort_values(ascending=False).head(k).index)
                S=set(mom.sort_values(ascending=True).head(k).index)
                gross=0.5*(float(fwd[list(L)].mean())-float(fwd[list(S)].mean()))
                tl=len(pl^L)/(2*max(1,len(pl|L))) if (pl|L) else (1.0 if L else 0)
                tsh=len(ps^S)/(2*max(1,len(ps|S))) if (ps|S) else (1.0 if S else 0)
                ret=gross-(tl+tsh)*FEE-FUND*0.5
        out[date]=ret; pl=L; ps=S; i+=hold
    return pd.Series(out)

GRID=[(look,hold,dec,univ) for look in (14,30,60) for hold in (7,14) for dec in (0.10,0.20) for univ in (30,50,100)]
print(f"computing {len(GRID)} config return-series...",flush=True)
SER={cfg:returns_series(*cfg) for cfg in GRID}

def stats(s):
    r=s.values
    if len(r)<4: return None
    eq=np.cumprod(1+r); sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    pos=r[r>0].sum(); neg=-r[r<0].sum(); pf=(pos/neg) if neg>0 else float('inf')
    return dict(n=len(r),tot=(eq[-1]-1)*100,sh=sh,pf=pf,dd=maxdd(eq))

# نوافذ متحركة: train=12 شهر، test=3 أشهر، خطوة=3 أشهر
start=idx.min(); end=idx.max()
windows=[]
ts=pd.Timestamp('2023-01-01')
while True:
    tr0=ts; tr1=ts+pd.DateOffset(months=12); te1=tr1+pd.DateOffset(months=3)
    if te1>end+pd.Timedelta(days=1): break
    windows.append((tr0,tr1,te1)); ts=ts+pd.DateOffset(months=3)

out=[]
out.append("ROLLING WALK-FORWARD — train=12mo, test=3mo, step=3mo. config auto-selected per-window on TRAIN Sharpe, tested BLIND.")
out.append("="*120)
out.append(f"{'#':>2} {'train':<19}{'test':<11}{'sel_cfg(look/hold/dec/univ)':<26}{'trSh':>6} | {'TEST_Sh':>8}{'TEST_PF':>8}{'TEST_ret':>9}")
out.append("-"*120)
test_sh=[]; test_pf=[]; test_ret=[]
for wi,(tr0,tr1,te1) in enumerate(windows,1):
    # اختر أفضل cfg على train
    best=None
    for cfg in GRID:
        s=SER[cfg]; trs=s[(s.index>=tr0)&(s.index<tr1)]
        m=stats(trs)
        if m and (best is None or m['sh']>best[1]):
            best=(cfg,m['sh'])
    cfg=best[0]; s=SER[cfg]; tes=s[(s.index>=tr1)&(s.index<te1)]
    tm=stats(tes)
    if not tm: continue
    test_sh.append(tm['sh']); test_pf.append(tm['pf'] if tm['pf']!=float('inf') else 3.0); test_ret.append(tm['tot'])
    pf='inf' if tm['pf']==float('inf') else f"{tm['pf']:.2f}"
    cfgs=f"{cfg[0]}/{cfg[1]}/{cfg[2]}/{cfg[3]}"
    out.append(f"{wi:>2} {str(tr0.date()):<10}-{str(tr1.date())[:7]:<8}{str(te1.date())[:7]:<11}{cfgs:<26}{best[1]:>6.2f} | {tm['sh']:>8.2f}{pf:>8}{tm['tot']:>+8.0f}%")
out.append("-"*120)
sh=np.array(test_sh); pf=np.array(test_pf); rt=np.array(test_ret)
out.append(f"WINDOWS: {len(sh)} | positive return: {int((rt>0).sum())}/{len(rt)} ({(rt>0).mean()*100:.0f}%) | Sharpe>0: {int((sh>0).sum())}/{len(sh)}")
out.append(f"  median Sharpe={np.median(sh):.2f}  mean={sh.mean():.2f}  std={sh.std():.2f}  | worst={sh.min():.2f}  best={sh.max():.2f}")
out.append(f"  median PF={np.median(pf):.2f}  | median ret={np.median(rt):+.1f}%  worst window={rt.min():+.0f}%  best={rt.max():+.0f}%")
out.append(f"  USER BAR — excellent: >=70% positive & medianPF>1.2 & medianSh>0.8 -> {'YES' if (rt>0).mean()>=0.70 and np.median(pf)>1.2 and np.median(sh)>0.8 else 'no'}")
out.append("")
out.append("="*120)
out.append("STABILITY BY UNIVERSE SIZE — fixed look30/hold14/dec10, vary univ, full-period + per-year (does edge hold across sizes?):")
out.append(f"  {'univ':>5}{'tot':>8}{'Sharpe':>8}{'PF':>7}{'MaxDD':>8}   {'2023':>7}{'2024':>7}{'2025':>7}")
for univ in (20,30,50,100):
    s=returns_series(30,14,0.10,univ); m=stats(s)
    pys=[]
    for y in (2023,2024,2025):
        sy=s[s.index.year==y]; my=stats(sy); pys.append(my['tot'] if my else 0)
    pf='inf' if m['pf']==float('inf') else f"{m['pf']:.2f}"
    out.append(f"  {univ:>5}{m['tot']:>+7.0f}%{m['sh']:>8.2f}{pf:>7}{m['dd']:>7.0f}%   {pys[0]:>+6.0f}%{pys[1]:>+6.0f}%{pys[2]:>+6.0f}%")
text="\n".join(out); print(text)
with open('/app/logs/rolling_wf_report.txt','w') as f: f.write(text)
