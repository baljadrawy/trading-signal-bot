import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA
LOOK=30; HOLD=7; FEE=0.004
syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
closes={}; dvol={}
for s in syms:
    df=load(s,'1d')
    if df is None: continue
    ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
    c=pd.Series(df['close'].values,index=ix); c=c[~c.index.duplicated()]
    d=pd.Series((df['close']*df['volume']).values,index=ix); d=d[~d.index.duplicated()]
    closes[s]=c; dvol[s]=d
panel=pd.DataFrame(closes).sort_index(); dv=pd.DataFrame(dvol).reindex(panel.index); idx=panel.index
btc=panel['BTCUSDT'].dropna(); ema50=btc.ewm(span=50).mean(); ema200=btc.ewm(span=200).mean()
def riskon(d):
    p=btc.get(d,np.nan); e50=ema50.get(d,np.nan); e200=ema200.get(d,np.nan)
    if np.isnan(p) or np.isnan(e200): return True
    return p>e50 and p>e200
def run(mode, liquid_top=50, decile=0.10):
    eq=1.0; curve=[]; wk=[]; pl=set(); ps=set(); i=LOOK
    while i+HOLD<len(idx):
        date=idx[i]; now=panel.iloc[i]; fut=panel.iloc[i+HOLD]; past=panel.iloc[i-LOOK]
        fwd=(fut/now-1); L=set(); S=set(); ret=0.0
        if riskon(date):
            mom=(now/past-1); v=mom.notna()&fwd.notna()&past.notna()&(now>0); mom=mom[v]; univ=mom.index
            if liquid_top>0:
                liq=dv.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(univ)]
                keep=set(liq.sort_values(ascending=False).head(liquid_top).index); mom=mom[mom.index.isin(keep)]
            if len(mom)>=20:
                k=max(1,int(len(mom)*decile))
                L=set(mom.sort_values(ascending=False).head(k).index); S=set(mom.sort_values(ascending=True).head(k).index)
                rl=float(fwd[list(L)].mean()); rs=float(fwd[list(S)].mean()); gross=0.5*(rl-rs)
                if mode=='code':
                    tl=len(pl^L)/(2*max(1,len(pl|L))) if (pl|L) else (1.0 if L else 0)
                    tsh=len(ps^S)/(2*max(1,len(ps|S))) if (ps|S) else (1.0 if S else 0)
                else: # correct one-way notional fraction per leg: (#out + #in)/k
                    tl=(len(pl-L)+len(L-pl))/max(1,len(L)) if L else 0
                    tsh=(len(ps-S)+len(S-ps))/max(1,len(S)) if S else 0
                cost=(tl+tsh)*FEE; ret=gross-cost
        eq*=(1+ret); curve.append(eq); wk.append((date.year,ret)); pl=L; ps=S; i+=HOLD
    c=np.array(curve); tot=(c[-1]-1)*100
    r=np.diff(np.concatenate([[1.0],c]))/np.concatenate([[1.0],c])[:-1]
    sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    py={y:(np.prod([1+x for yy,x in wk if yy==y])-1)*100 for y in (2023,2024,2025)}
    return tot,sh,py
for m in ['code','correct']:
    tot,sh,py=run(m)
    print(f"{m:8s} totRet={tot:+.1f}% Sharpe={sh:.2f} 2025={py[2025]:+.0f}%")
