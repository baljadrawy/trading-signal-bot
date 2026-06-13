import sys, glob, zipfile
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load as load_spot, DATA as SPOT_DATA
FUT="/app/logs/fut_data"; LOOK,HOLD,DEC,UNIV=30,14,0.10,30; FEE=0.004
def load_fut(sym):
    fs=sorted(glob.glob(f"{FUT}/klines/{sym}/1d/{sym}-1d-*.zip"))
    if not fs: return None
    rows=[]
    for f in fs:
        try:
            z=zipfile.ZipFile(f); n=z.namelist()[0]
            for ln in z.read(n).decode().splitlines():
                if ln.startswith('open_time'): continue
                p=ln.split(','); rows.append((int(p[0]),float(p[4])))
        except: pass
    if len(rows)<5: return None
    s=pd.Series([r[1] for r in rows],index=pd.to_datetime([r[0] if r[0]<1e14 else r[0]//1000 for r in rows],unit='ms').normalize())
    return s[~s.index.duplicated()]
covered=[s.strip() for s in open("/app/logs/futures_covered_syms.txt") if s.strip()]
sclose={}; sdv={}; fclose={}
for s in covered:
    df=load_spot(s,'1d')
    if df is not None:
        ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
        c=pd.Series(df['close'].values,index=ix); sclose[s]=c[~c.index.duplicated()]
        d=pd.Series((df['close']*df['volume']).values,index=ix); sdv[s]=d[~d.index.duplicated()]
    f=load_fut(s)
    if f is not None: fclose[s]=f
sp=pd.DataFrame(sclose).sort_index(); sdvp=pd.DataFrame(sdv).reindex(sp.index); fp=pd.DataFrame(fclose).reindex(sp.index)
idx=sp.index; btc=sp['BTCUSDT'].dropna(); e5=btc.ewm(span=50).mean(); e2=btc.ewm(span=200).mean()
def ro(d):
    p=btc.get(d,np.nan); a=e5.get(d,np.nan); b=e2.get(d,np.nan)
    return True if (np.isnan(p) or np.isnan(b)) else (p>a and p>b)
def perf(rets):
    r=np.array(rets);
    if len(r)<4: return None
    eq=np.cumprod(1+r); sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    pos=r[r>0].sum(); neg=-r[r<0].sum(); pf=(pos/neg) if neg>0 else 99
    pk=np.maximum.accumulate(eq); dd=((eq-pk)/pk).min()*100
    return len(r),(eq[-1]-1)*100,sh,pf,dd
# signal from SPOT, execute on SPOT vs FUTURES — identical coins, covered-131 universe
pl=set();ps=set(); rs_spot=[]; rs_fut=[]; i=LOOK
while i+HOLD<len(idx):
    date=idx[i]
    if date.year<2024: i+=HOLD; continue
    now=sp.iloc[i]; futs=sp.iloc[i+HOLD]; past=sp.iloc[i-LOOK]
    fwd=(futs/now-1); rsp=0.0; rft=0.0; L=set(); S=set()
    if ro(date):
        mom=(now/past-1); v=mom.notna()&fwd.notna()&past.notna()&(now>0); mom=mom[v]
        liq=sdvp.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(mom.index)]
        mom=mom[mom.index.isin(set(liq.sort_values(ascending=False).head(UNIV).index))]
        if len(mom)>=10:
            k=max(1,int(len(mom)*DEC))
            L=set(mom.sort_values(ascending=False).head(k).index); S=set(mom.sort_values(ascending=True).head(k).index)
            lr_s=float(fwd[list(L)].mean()); sr_s=-float(fwd[list(S)].mean())
            fnow=fp.iloc[i]; ffut=fp.iloc[i+HOLD]
            def fret(s):
                a=fnow.get(s); b=ffut.get(s)
                return (b/a-1) if (not pd.isna(a) and not pd.isna(b) and a>0) else fwd[s]
            lr_f=np.mean([fret(s) for s in L]); sr_f=-np.mean([fret(s) for s in S])
            tl=len(pl^L)/(2*max(1,len(pl|L))) if (pl|L) else (1.0 if L else 0)
            tsh=len(ps^S)/(2*max(1,len(ps|S))) if (ps|S) else (1.0 if S else 0)
            fee=(tl+tsh)*FEE
            rsp=0.5*(lr_s+sr_s)-fee; rft=0.5*(lr_f+sr_f)-fee
    rs_spot.append(rsp); rs_fut.append(rft); pl=L; ps=S; i+=HOLD
print("IDENTICAL signals (spot-generated, covered-131 univ), executed on:")
print("  SPOT   : n=%d tot=%+.0f%% Sharpe=%.2f PF=%.2f MaxDD=%.0f%%"%perf(rs_spot))
print("  FUTURES: n=%d tot=%+.0f%% Sharpe=%.2f PF=%.2f MaxDD=%.0f%%"%perf(rs_fut))
