#!/usr/bin/env python3
"""Survivorship test — 3 سيناريوهات على الاستراتيجية الفائزة (look30 hold14 dec0.10 univ30 gated).
1) Baseline (الكون الحالي = ناجون).
2) Point-in-Time: في كل قرار، الكون = الرموز المُدرَجة فعلاً قبل ذلك التاريخ + سيولة كافية (يزيل future-listing bias).
3) Delisting Haircut: أي عملة تفقد >DROP% خلال فترة الحجز تُعامل كشطب → عائد الفترة = -100% (long) / +ربح كامل (short).
ملاحظة: العملات الغائبة كلياً من المصدر لا تُستعاد — هذه حدّ أدنى للتحيّز لا إزالته.
"""
import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA

LOOK,HOLD,DEC,UNIV=30,14,0.10,30
FEE=0.004; FUND=0.003

syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
closes={}; dvol={}; firsts={}
for s in syms:
    df=load(s,'1d')
    if df is None: continue
    ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
    c=pd.Series(df['close'].values,index=ix); c=c[~c.index.duplicated()]
    d=pd.Series((df['close']*df['volume']).values,index=ix); d=d[~d.index.duplicated()]
    closes[s]=c; dvol[s]=d; firsts[s]=ix.min()
panel=pd.DataFrame(closes).sort_index(); dv=pd.DataFrame(dvol).reindex(panel.index)
idx=panel.index
btc=panel['BTCUSDT'].dropna(); ema50=btc.ewm(span=50).mean(); ema200=btc.ewm(span=200).mean()
def riskon(date):
    p=btc.get(date,np.nan); e50=ema50.get(date,np.nan); e200=ema200.get(date,np.nan)
    if np.isnan(p) or np.isnan(e200): return True
    return p>e50 and p>e200
def maxdd(eq):
    eq=np.array(eq); pk=np.maximum.accumulate(eq); return float(((eq-pk)/pk).min()*100)

def strat(mode='baseline', min_age_days=0, drop=None):
    pl=set(); ps=set(); rets=[]; i=LOOK
    while i+HOLD<len(idx):
        date=idx[i]; now=panel.iloc[i]; fut=panel.iloc[i+HOLD]; past=panel.iloc[i-LOOK]
        fwd=(fut/now-1); ret=0.0; L=set(); S=set()
        if riskon(date):
            mom=(now/past-1); v=mom.notna()&fwd.notna()&past.notna()&(now>0); mom=mom[v]
            # point-in-time: استبعد الرموز المُدرَجة حديثاً (أقل من min_age_days قبل date)
            if mode=='pit':
                keep=[s for s in mom.index if (date-firsts.get(s,date)).days>=min_age_days]
                mom=mom[mom.index.isin(set(keep))]
            # سيولة
            liq=dv.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(mom.index)]
            mom=mom[mom.index.isin(set(liq.sort_values(ascending=False).head(UNIV).index))]
            if len(mom)>=15:
                k=max(1,int(len(mom)*DEC))
                L=set(mom.sort_values(ascending=False).head(k).index)
                S=set(mom.sort_values(ascending=True).head(k).index)
                lr=fwd[list(L)].copy(); sr=fwd[list(S)].copy()
                # delisting haircut: من يفقد >drop% يُعتبر مشطوباً
                if drop is not None:
                    lr=lr.apply(lambda x: -1.0 if x<=-drop else x)   # long يخسر كامل
                    sr=sr.apply(lambda x: -1.0 if x<=-drop else x)   # short يربح كامل (عبر -rs)
                gross=0.5*(float(lr.mean())-float(sr.mean()))
                tl=len(pl^L)/(2*max(1,len(pl|L))) if (pl|L) else (1.0 if L else 0)
                tsh=len(ps^S)/(2*max(1,len(ps|S))) if (ps|S) else (1.0 if S else 0)
                ret=gross-(tl+tsh)*FEE-FUND*0.5
        rets.append((date,ret)); pl=L; ps=S; i+=HOLD
    return rets

def perf(rets,yr=None):
    r=np.array([x for d,x in rets if (yr is None or d.year==yr)])
    if len(r)<5: return None
    eq=np.cumprod(1+r); sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    pos=r[r>0].sum(); neg=-r[r<0].sum(); pf=(pos/neg) if neg>0 else float('inf')
    return dict(n=len(r),tot=(eq[-1]-1)*100,sh=sh,pf=pf,dd=maxdd(eq))

def fmt(m):
    if not m: return "n<5"
    pf='inf' if m['pf']==float('inf') else f"{m['pf']:.2f}"
    return f"n={m['n']:>3}  tot={m['tot']:>+6.0f}%  Sharpe={m['sh']:>5.2f}  PF={pf:>5}  MaxDD={m['dd']:>6.0f}%"

out=[]
out.append("SURVIVORSHIP TEST — winning config look30/hold14/dec10%/univ30, gated. (lower-bound on bias; fully-absent delists unrecoverable)")
out.append("="*118)
scen=[("1) BASELINE (current=survivors)", strat('baseline')),
      ("2) POINT-IN-TIME (age>=90d, no future-listing)", strat('pit',min_age_days=90)),
      ("2b) POINT-IN-TIME (age>=180d, stricter)", strat('pit',min_age_days=180)),
      ("3) DELISTING HAIRCUT (drop>=50% => -100%)", strat('baseline',drop=0.50)),
      ("3b) DELISTING HAIRCUT (drop>=35% => -100%)", strat('baseline',drop=0.35))]
for name,rets in scen:
    out.append(f"{name:<48} FULL: {fmt(perf(rets))}")
    out.append(f"{'':<48} 2025: {fmt(perf(rets,2025))}")
out.append("="*118)
out.append("PASS (user bar): Sharpe>1 AND PF>1.5 surviving across scenarios = very reassuring.")
text="\n".join(out); print(text)
with open('/app/logs/survivorship_report.txt','w') as f: f.write(text)
