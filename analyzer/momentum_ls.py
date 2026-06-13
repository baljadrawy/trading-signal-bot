#!/usr/bin/env python3
"""اختبار الـalpha النقي كـ منحنى رأس مال long-short (لا متوسط فترات).
market-neutral: long أقوى decile + short أضعف decile. dollar-neutral (0.5 لكل ساق).
حاسم: يقارن الكون الكامل مقابل 'الكون القابل للشورت' (أعلى 50 سيولة) — لأن alpha الـbottom
غالباً من عملات صغيرة لا تُشورت. regime-gated (long-short في risk-on فقط). رسوم على الساقين.
"""
import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA

LOOK=30; HOLD=7; FEE=0.004  # per side per full rotation
syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
closes={}; dvol={}
for s in syms:
    df=load(s,'1d')
    if df is None: continue
    ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
    c=pd.Series(df['close'].values,index=ix); c=c[~c.index.duplicated()]
    d=pd.Series((df['close']*df['volume']).values,index=ix); d=d[~d.index.duplicated()]
    closes[s]=c; dvol[s]=d
panel=pd.DataFrame(closes).sort_index()
dv=pd.DataFrame(dvol).reindex(panel.index)
idx=panel.index
print(f"panel {panel.shape}",flush=True)

btc=panel['BTCUSDT'].dropna()
ema50=btc.ewm(span=50).mean(); ema200=btc.ewm(span=200).mean()
def riskon(date):
    p=btc.get(date,np.nan); e50=ema50.get(date,np.nan); e200=ema200.get(date,np.nan)
    if np.isnan(p) or np.isnan(e200): return True
    return p>e50 and p>e200

def maxdd(eq):
    eq=np.array(eq); pk=np.maximum.accumulate(eq); return float(((eq-pk)/pk).min()*100)

def run(liquid_top=0, gate=True, decile=0.10):
    eq=1.0; curve=[]; wk=[]; pl=set(); ps=set()
    i=LOOK
    while i+HOLD<len(idx):
        date=idx[i]; now=panel.iloc[i]; fut=panel.iloc[i+HOLD]; past=panel.iloc[i-LOOK]
        fwd=(fut/now-1)
        on=riskon(date)
        do = on or (not gate)
        L=set(); S=set(); ret=0.0
        if do:
            mom=(now/past-1); v=mom.notna()&fwd.notna()&past.notna()&(now>0); mom=mom[v]
            univ=mom.index
            if liquid_top>0:
                liq=dv.iloc[max(0,i-30):i].mean().dropna()
                liq=liq[liq.index.isin(univ)]
                keep=set(liq.sort_values(ascending=False).head(liquid_top).index)
                mom=mom[mom.index.isin(keep)]
            if len(mom)>=20 or (liquid_top>0 and len(mom)>=20):
                k=max(1,int(len(mom)*decile))
                L=set(mom.sort_values(ascending=False).head(k).index)
                S=set(mom.sort_values(ascending=True).head(k).index)
                rl=float(fwd[list(L)].mean()); rs=float(fwd[list(S)].mean())
                gross=0.5*(rl-rs)   # dollar-neutral
                tl=len(pl^L)/(2*max(1,len(pl|L))) if (pl|L) else (1.0 if L else 0)
                tsh=len(ps^S)/(2*max(1,len(ps|S))) if (ps|S) else (1.0 if S else 0)
                cost=(tl+tsh)*FEE
                ret=gross-cost
        eq*=(1+ret); curve.append(eq); wk.append((date.year,ret)); pl=L; ps=S
        i+=HOLD
    return curve,wk

def stats(curve,wk,label):
    c=np.array(curve); tot=(c[-1]-1)*100
    r=np.diff(np.concatenate([[1.0],c]))/np.concatenate([[1.0],c])[:-1]
    sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    py={y:(np.prod([1+x for _,x in [(yy,xx) for yy,xx in wk if yy==y]])-1)*100 for y in (2023,2024,2025)}
    return f"{label:<34} totRet={tot:>+8.1f}%  Sharpe={sh:>5.2f}  MaxDD={maxdd(curve):>7.1f}%  2023:{py[2023]:+.0f}% 2024:{py[2024]:+.0f}% 2025:{py[2025]:+.0f}%"

out=[]
out.append("LONG-SHORT EQUITY CURVE TEST (market-neutral, dollar-neutral, net of fees) — does the +1.27%/wk survive compounding?")
out.append(f"weekly, look={LOOK} hold={HOLD}, fee={FEE*100}%/side. KEY comparison: full universe vs liquid-shortable (top-50 $vol).")
out.append("="*125)
c,w=run(liquid_top=0,gate=True);     out.append(stats(c,w,"FULL universe, risk-on-gated"))
c,w=run(liquid_top=0,gate=False);    out.append(stats(c,w,"FULL universe, always-on"))
c,w=run(liquid_top=50,gate=True);    out.append(stats(c,w,"LIQUID-50 (shortable), risk-on-gated"))
c,w=run(liquid_top=50,gate=False);   out.append(stats(c,w,"LIQUID-50 (shortable), always-on"))
c,w=run(liquid_top=30,gate=True);    out.append(stats(c,w,"LIQUID-30 (most shortable), gated"))
out.append("="*125)
out.append("READ: if FULL >> LIQUID, the alpha is in unshortable micro-caps (mirage). Only LIQUID curve is harvestable on futures.")
text="\n".join(out); print(text)
with open('/app/logs/momentum_ls_report.txt','w') as f: f.write(text)
