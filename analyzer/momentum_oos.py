#!/usr/bin/env python3
"""OOS صارم: انتقاء التهيئة آلياً على TRAIN (2023+2024) فقط، ثم اختبار أعمى على TEST (2025).
يكسر data-snooping: قرار الاختيار لا يرى بيانات الاختبار إطلاقاً.
يطبع: أفضل تهيئة على train، أداءها على test، + هل أفضل-5 train تبقى موجبة على test (ثبات الترتيب)."""
import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA

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

def weekly_returns(look,hold,decile,liquid_top,fee_side=0.004,funding=0.003):
    """يرجع list[(date, ret)] لكل فترة إعادة موازنة عبر كامل المدى."""
    pl=set(); ps=set(); res=[]; i=look
    while i+hold<len(idx):
        date=idx[i]; now=panel.iloc[i]; fut=panel.iloc[i+hold]; past=panel.iloc[i-look]
        fwd=(fut/now-1); ret=0.0; L=set(); S=set()
        if riskon(date):
            mom=(now/past-1); v=mom.notna()&fwd.notna()&past.notna()&(now>0); mom=mom[v]
            if liquid_top>0:
                liq=dv.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(mom.index)]
                mom=mom[mom.index.isin(set(liq.sort_values(ascending=False).head(liquid_top).index))]
            if len(mom)>=20:
                k=max(1,int(len(mom)*decile))
                L=set(mom.sort_values(ascending=False).head(k).index)
                S=set(mom.sort_values(ascending=True).head(k).index)
                gross=0.5*(float(fwd[list(L)].mean())-float(fwd[list(S)].mean()))
                tl=len(pl^L)/(2*max(1,len(pl|L))) if (pl|L) else (1.0 if L else 0)
                tsh=len(ps^S)/(2*max(1,len(ps|S))) if (ps|S) else (1.0 if S else 0)
                ret=gross-(tl+tsh)*fee_side-funding*0.5
        res.append((date,ret)); pl=L; ps=S; i+=hold
    return res

def perf(rets):
    if len(rets)<5: return None
    r=np.array([x for _,x in rets])
    eq=np.cumprod(1+r); sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    pos=r[r>0].sum(); neg=-r[r<0].sum(); pf=(pos/neg) if neg>0 else float('inf')
    return dict(n=len(r),tot=(eq[-1]-1)*100,sh=sh,pf=pf,dd=maxdd(eq),wr=(r>0).mean()*100)

def split(rets):
    tr=[(d,x) for d,x in rets if d.year in (2023,2024)]
    te=[(d,x) for d,x in rets if d.year==2025]
    return perf(tr),perf(te)

GRID=[(look,hold,dec,univ) for look in (14,30,60) for hold in (7,14) for dec in (0.10,0.20) for univ in (30,50,100)]
rows=[]
for (look,hold,dec,univ) in GRID:
    rets=weekly_returns(look,hold,dec,univ)
    tr,te=split(rets)
    if tr and te: rows.append(((look,hold,dec,univ),tr,te))

out=[]
out.append("STRICT OOS — select config on TRAIN(2023+2024) by Sharpe, then test BLIND on 2025. No param touched on test.")
out.append(f"grid size={len(GRID)}  |  selection metric = TRAIN Sharpe")
out.append("="*120)
# الترتيب حسب train Sharpe
rows.sort(key=lambda r:r[1]['sh'], reverse=True)
out.append("TOP 8 configs by TRAIN Sharpe — and their BLIND 2025 result:")
out.append(f"  {'look':>4}{'hold':>5}{'dec':>5}{'univ':>5}  | {'TRAIN_Sh':>9}{'TRAIN_ret':>10}{'TRAIN_PF':>9}  || {'TEST25_Sh':>10}{'TEST25_ret':>11}{'TEST25_PF':>10}{'TEST25_DD':>10}")
for cfg,tr,te in rows[:8]:
    pf_tr='inf' if tr['pf']==float('inf') else f"{tr['pf']:.2f}"
    pf_te='inf' if te['pf']==float('inf') else f"{te['pf']:.2f}"
    out.append(f"  {cfg[0]:>4}{cfg[1]:>5}{cfg[2]:>5.2f}{cfg[3]:>5}  | {tr['sh']:>9.2f}{tr['tot']:>+9.0f}%{pf_tr:>9}  || {te['sh']:>10.2f}{te['tot']:>+10.0f}%{pf_te:>10}{te['dd']:>9.0f}%")
out.append("")
# الحكم على الفائز الأوحد (أعلى train Sharpe)
win=rows[0]
out.append("="*120)
out.append(f">>> SELECTED (highest TRAIN Sharpe): look={win[0][0]} hold={win[0][1]} decile={win[0][2]} univ={win[0][3]}")
te=win[2]
pf_te='inf' if te['pf']==float('inf') else f"{te['pf']:.3f}"
out.append(f">>> BLIND 2025 TEST: Sharpe={te['sh']:.2f}  totRet={te['tot']:+.0f}%  PF={pf_te}  MaxDD={te['dd']:.0f}%  WR={te['wr']:.0f}%  n={te['n']}")
bar = (te['sh']>0.7) or (te['pf']>1.05) or (te['tot']>0)
out.append(f">>> USER BAR (Sharpe>0.7 OR PF>1.05 OR clearly positive): {'PASS ✓' if bar else 'FAIL ✗'}")
out.append("")
# ثبات الترتيب: كم من أفضل-5 train تبقى موجبة على 2025
top5=rows[:5]; pos25=sum(1 for _,_,te in top5 if te['tot']>0); sh25=sum(1 for _,_,te in top5 if te['sh']>0.7)
out.append(f"RANK STABILITY: of top-5 TRAIN configs, {pos25}/5 positive on 2025, {sh25}/5 Sharpe>0.7 on 2025.")
out.append("  (لو الفائز وحده ينجح بينما الباقي يفشل = حظ. لو الأغلبية تنجح = ثبات حقيقي.)")
text="\n".join(out); print(text)
with open('/app/logs/momentum_oos_report.txt','w') as f: f.write(text)
