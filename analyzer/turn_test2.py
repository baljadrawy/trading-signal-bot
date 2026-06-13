import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA
LOOK=30; HOLD=7
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
def run(mode, FEE, liquid_top=50, decile=0.10):
    eq=1.0; wk=[]; pl=set(); ps=set(); i=LOOK; tot_turn=0; n=0
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
                else:
                    tl=(len(pl-L)+len(L-pl))/max(1,len(L)) if L else 0
                    tsh=(len(ps-S)+len(S-ps))/max(1,len(S)) if S else 0
                cost=(tl+tsh)*FEE; ret=gross-cost; tot_turn+=(tl+tsh); n+=1
        eq*=(1+ret); wk.append((date.year,ret)); i+=HOLD
    sh_per=tot_turn/n if n else 0
    return eq, sh_per
# realistic per-side fee ~0.1% with the CORRECT (both-side) turnover is the truth.
e_truth,t=run('correct',0.001); print(f"TRUTH (correct turnover, realistic 0.1%/side): eq={e_truth:.2f}")
e_code,_=run('code',0.004); print(f"CODE (buggy turnover, 0.4%/side): eq={e_code:.2f}")
e_code_real,_=run('code',0.001); print(f"CODE turnover but realistic 0.1%/side: eq={e_code_real:.2f}")
