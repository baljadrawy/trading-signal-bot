#!/usr/bin/env python3
"""إجهاد استراتيجية long-short المحايدة (liquid, regime-gated) قبل أي قرار بناء.
1) إجهاد رسوم + funding على الساق القصيرة. 2) survivorship. 3) مسح متانة المعاملات.
"""
import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA

syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
closes={}; dvol={}; lastdate={}
for s in syms:
    df=load(s,'1d')
    if df is None: continue
    ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
    c=pd.Series(df['close'].values,index=ix); c=c[~c.index.duplicated()]
    d=pd.Series((df['close']*df['volume']).values,index=ix); d=d[~d.index.duplicated()]
    closes[s]=c; dvol[s]=d; lastdate[s]=ix.max()
panel=pd.DataFrame(closes).sort_index(); dv=pd.DataFrame(dvol).reindex(panel.index)
idx=panel.index; PMAX=idx.max()
btc=panel['BTCUSDT'].dropna(); ema50=btc.ewm(span=50).mean(); ema200=btc.ewm(span=200).mean()
def riskon(date):
    p=btc.get(date,np.nan); e50=ema50.get(date,np.nan); e200=ema200.get(date,np.nan)
    if np.isnan(p) or np.isnan(e200): return True
    return p>e50 and p>e200
def maxdd(eq):
    eq=np.array(eq); pk=np.maximum.accumulate(eq); return float(((eq-pk)/pk).min()*100)

def run(look,hold,decile,liquid_top,fee_side,funding_wk,gate=True):
    eq=1.0; curve=[]; wk=[]; pl=set(); ps=set(); i=look
    while i+hold<len(idx):
        date=idx[i]; now=panel.iloc[i]; fut=panel.iloc[i+hold]; past=panel.iloc[i-look]
        fwd=(fut/now-1); ret=0.0; L=set(); S=set()
        if gate==False or riskon(date):
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
                cost=(tl+tsh)*fee_side + funding_wk*0.5   # short-leg funding drag
                ret=gross-cost
        eq*=(1+ret); curve.append(eq); wk.append((date.year,ret)); pl=L; ps=S; i+=hold
    c=np.array(curve);
    if len(c)<5: return None
    r=np.diff(np.concatenate([[1.0],c]))/np.concatenate([[1.0],c])[:-1]
    sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    py={y:(np.prod([1+x for yy,x in wk if yy==y])-1)*100 for y in (2023,2024,2025)}
    return dict(tot=(c[-1]-1)*100,sh=sh,dd=maxdd(curve),py=py,minyr=min(py.values()))

out=[]
out.append("STRESS TEST — long-short market-neutral momentum (liquid, regime-gated)")
out.append("="*120)
# --- survivorship ---
trunc=[s for s,ld in lastdate.items() if ld < PMAX - pd.Timedelta(days=30)]
out.append(f"SURVIVORSHIP: panel max date={PMAX.date()} | symbols={len(closes)} | "
           f"with history ending >30d early (possible delist-in-sample, captured): {len(trunc)}")
out.append("  NOTE: fully-delisted coins absent from data.binance.vision entirely → unmeasurable upward bias remains.")
out.append("")
# --- fee + funding stress on baseline (LIQUID-50, look30 hold7 dec0.1, gated) ---
out.append("FEE+FUNDING STRESS (baseline LIQUID-50, look30 hold7 decile10%, gated):")
out.append(f"  {'fee/side':>9}{'funding/wk':>12}{'totRet':>10}{'Sharpe':>8}{'MaxDD':>9}{'minYr':>8}")
for fee in [0.004,0.008,0.012]:
    for fund in [0.0,0.003,0.006]:
        m=run(30,7,0.10,50,fee,fund,True)
        if m: out.append(f"  {fee*100:>8.1f}%{fund*100:>11.1f}%{m['tot']:>+9.0f}%{m['sh']:>8.2f}{m['dd']:>8.0f}%{m['minyr']:>+7.0f}%")
out.append("")
# --- robustness sweep ---
out.append("ROBUSTNESS SWEEP (fee 0.4%/side, funding 0.3%/wk, gated):")
out.append(f"  {'look':>5}{'hold':>5}{'univ':>6}{'dec':>5}{'totRet':>10}{'Sharpe':>8}{'MaxDD':>9}{'minYr':>8}")
cnt=0; pos=0; shpos=0
for look in (14,30,60):
    for hold in (7,14):
        for univ in (30,50,100):
            for dec in (0.10,0.20):
                m=run(look,hold,dec,univ,0.004,0.003,True)
                if not m: continue
                cnt+=1; pos+= m['tot']>0; shpos+= m['sh']>0.5
                if (look,hold,dec) in [(30,7,0.10),(60,7,0.10),(30,14,0.10)] or m['sh']>0.9:
                    out.append(f"  {look:>5}{hold:>5}{univ:>6}{dec:>5.2f}{m['tot']:>+9.0f}%{m['sh']:>8.2f}{m['dd']:>8.0f}%{m['minyr']:>+7.0f}%")
out.append(f"  ... {cnt} configs total | positive totRet: {pos}/{cnt} | Sharpe>0.5: {shpos}/{cnt}")
out.append("")
out.append("FEE STRESS on LOW-TURNOVER configs (biweekly hold=14) — does a robust variant clear Sharpe>0.7 at 2-3x fees?")
out.append(f"  {'config':<22}{'fee/side':>9}{'fund/wk':>9}{'totRet':>9}{'Sharpe':>8}{'MaxDD':>8}{'minYr':>7}")
for (look,hold,univ,dec,name) in [(30,14,30,0.10,'L30/H14/U30/d10'),(30,14,50,0.20,'L30/H14/U50/d20'),(14,14,50,0.20,'L14/H14/U50/d20')]:
    for fee in [0.004,0.008,0.012]:
        m=run(look,hold,dec,univ,fee,0.003,True)
        if m: out.append(f"  {name:<22}{fee*100:>8.1f}%{0.3:>8.1f}%{m['tot']:>+8.0f}%{m['sh']:>8.2f}{m['dd']:>7.0f}%{m['minyr']:>+6.0f}%")
    out.append("")
out.append("="*120)
out.append("PASS if: survives 2-3x fees+funding with Sharpe>0.7, AND majority of sweep positive (not one lucky cell).")
text="\n".join(out); print(text)
with open('/app/logs/momentum_stress_report.txt','w') as f: f.write(text)
