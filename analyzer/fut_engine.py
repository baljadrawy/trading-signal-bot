#!/usr/bin/env python3
"""Futures Reality Test — المستويات 1-3. الكون المُغطّى (131)، 2024-2025.
3 تشغيلات مطابقة الكون: A) spot كامل-250، B) spot على الـ131، C) futures على الـ131 + funding حقيقي.
funding مفكّك: long×short×regime. الحافة 94% شورت → الحَكَم هو funding على الشورت.
دخول/خروج: نفس النموذج (look30 hold14 dec10% univ=Top30-ADV gated, long-short dollar-neutral).
"""
import sys, glob, zipfile
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load as load_spot, DATA as SPOT_DATA

FUT="/app/logs/fut_data"
LOOK,HOLD,DEC,UNIV=30,14,0.10,30
TRADE_FEE=0.004  # taker round-trip per side, futures

def load_fut_klines(sym):
    fs=sorted(glob.glob(f"{FUT}/klines/{sym}/1d/{sym}-1d-*.zip"))
    if not fs: return None
    rows=[]
    for f in fs:
        try:
            z=zipfile.ZipFile(f); n=z.namelist()[0]
            for ln in z.read(n).decode().splitlines():
                if ln.startswith('open_time'): continue
                p=ln.split(',')
                rows.append((int(p[0]),float(p[1]),float(p[2]),float(p[3]),float(p[4]),float(p[5])))
        except Exception: pass
    if len(rows)<LOOK+5: return None
    df=pd.DataFrame(rows,columns=['t','open','high','low','close','volume']).drop_duplicates('t').sort_values('t').reset_index(drop=True)
    df['t']=df['t'].apply(lambda x:x//1000 if x>1e14 else x)
    return df

def load_funding(sym):
    """يرجع Series: date -> daily funding sum (مجموع الـ3 دفعات اليومية، rate)."""
    fs=sorted(glob.glob(f"{FUT}/fundingRate/{sym}/{sym}-fundingRate-*.zip"))
    if not fs: return None
    recs=[]
    for f in fs:
        try:
            z=zipfile.ZipFile(f); n=z.namelist()[0]
            for ln in z.read(n).decode().splitlines():
                if ln.startswith('calc_time'): continue
                p=ln.split(',')
                recs.append((int(p[0]),float(p[2])))
        except Exception: pass
    if not recs: return None
    s=pd.Series([r[1] for r in recs], index=pd.to_datetime([r[0] for r in recs],unit='ms'))
    daily=s.groupby(s.index.normalize()).sum()  # مجموع التمويل اليومي (long يدفع إذا موجب)
    return daily

print("loading futures klines + funding for covered universe...",flush=True)
syms=[s.strip() for s in open("/app/logs/futures_covered_syms.txt") if s.strip()]
fk={}; fund={}; fdv={}
for s in syms:
    df=load_fut_klines(s)
    if df is None: continue
    ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
    c=pd.Series(df['close'].values,index=ix); c=c[~c.index.duplicated()]
    d=pd.Series((df['close']*df['volume']).values,index=ix); d=d[~d.index.duplicated()]
    fk[s]=c; fdv[s]=d
    fn=load_funding(s)
    if fn is not None: fund[s]=fn
print(f"futures klines loaded: {len(fk)} | funding loaded: {len(fund)}",flush=True)

fpanel=pd.DataFrame(fk).sort_index(); fdvp=pd.DataFrame(fdv).reindex(fpanel.index)
fundp=pd.DataFrame(fund).reindex(fpanel.index).fillna(0.0)
idx=fpanel.index
btc=fpanel['BTCUSDT'].dropna() if 'BTCUSDT' in fpanel else None
ema50=btc.ewm(span=50).mean(); ema200=btc.ewm(span=200).mean()
def riskon(date):
    p=btc.get(date,np.nan); e5=ema50.get(date,np.nan); e2=ema200.get(date,np.nan)
    if np.isnan(p) or np.isnan(e2): return True
    return p>e5 and p>e2
def maxdd(eq):
    eq=np.array(eq); pk=np.maximum.accumulate(eq); return float(((eq-pk)/pk).min()*100)

def run_fut(use_funding=True, y0=2024):
    """التشغيل C: آجلة + funding حقيقي. يفكّك long/short/funding/regime."""
    pl=set(); ps=set(); rets=[]
    agg=dict(long=0.0,short=0.0,fund_long=0.0,fund_short=0.0,
             fl_on=0.0,fl_off=0.0,fs_on=0.0,fs_off=0.0)
    i=LOOK
    while i+HOLD<len(idx):
        date=idx[i]
        if date.year<y0: i+=HOLD; continue
        now=fpanel.iloc[i]; fut=fpanel.iloc[i+HOLD]; past=fpanel.iloc[i-LOOK]
        fwd=(fut/now-1); ret=0.0; L=set(); S=set(); on=riskon(date)
        if on:
            mom=(now/past-1); v=mom.notna()&fwd.notna()&past.notna()&(now>0); mom=mom[v]
            liq=fdvp.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(mom.index)]
            mom=mom[mom.index.isin(set(liq.sort_values(ascending=False).head(UNIV).index))]
            if len(mom)>=10:
                k=max(1,int(len(mom)*DEC))
                L=set(mom.sort_values(ascending=False).head(k).index)
                S=set(mom.sort_values(ascending=True).head(k).index)
                lr=float(fwd[list(L)].mean()); sr=-float(fwd[list(S)].mean())
                # funding على فترة الحجز: long يدفع مجموع funding الموجب؛ short يقبضه
                f_l=0.0; f_s=0.0
                if use_funding:
                    win=fundp.iloc[i:i+HOLD]
                    f_l=float(win[list(L)].sum(axis=0).mean())   # long يدفع هذا (تكلفة)
                    f_s=float(win[list(S)].sum(axis=0).mean())   # short يقبض هذا (ربح إن موجب)
                tl=len(pl^L)/(2*max(1,len(pl|L))) if (pl|L) else (1.0 if L else 0)
                tsh=len(ps^S)/(2*max(1,len(ps|S))) if (ps|S) else (1.0 if S else 0)
                gross=0.5*(lr+sr); fee=(tl+tsh)*TRADE_FEE
                fund_eff=0.5*(-f_l + f_s)   # long: -funding ; short: +funding
                ret=gross+fund_eff-fee
                agg['long']+=0.5*lr; agg['short']+=0.5*sr
                agg['fund_long']+=0.5*(-f_l); agg['fund_short']+=0.5*(f_s)
                if on:
                    agg['fl_on']+=0.5*(-f_l); agg['fs_on']+=0.5*(f_s)
        rets.append((date,ret)); pl=L; ps=S; i+=HOLD
    return rets,agg

def run_spot(symset=None, y0=2024):
    """تشغيل سبوت على بيانات السبوت، مقيّد بكون symset (للمطابقة)."""
    sclose={}; sdv={}
    pool=symset if symset is not None else [s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{SPOT_DATA}/{s}/1d/*.zip")]
    for s in pool:
        df=load_spot(s,'1d')
        if df is None: continue
        ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
        c=pd.Series(df['close'].values,index=ix); c=c[~c.index.duplicated()]
        d=pd.Series((df['close']*df['volume']).values,index=ix); d=d[~d.index.duplicated()]
        sclose[s]=c; sdv[s]=d
    sp=pd.DataFrame(sclose).sort_index(); sdvp=pd.DataFrame(sdv).reindex(sp.index)
    sidx=sp.index
    sb=sp['BTCUSDT'].dropna(); se5=sb.ewm(span=50).mean(); se2=sb.ewm(span=200).mean()
    def ro(d):
        p=sb.get(d,np.nan); a=se5.get(d,np.nan); b=se2.get(d,np.nan)
        return True if (np.isnan(p) or np.isnan(b)) else (p>a and p>b)
    pl=set(); ps=set(); rets=[]; i=LOOK
    while i+HOLD<len(sidx):
        date=sidx[i]
        if date.year<y0: i+=HOLD; continue
        now=sp.iloc[i]; fut=sp.iloc[i+HOLD]; past=sp.iloc[i-LOOK]
        fwd=(fut/now-1); ret=0.0; L=set(); S=set()
        if ro(date):
            mom=(now/past-1); v=mom.notna()&fwd.notna()&past.notna()&(now>0); mom=mom[v]
            liq=sdvp.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(mom.index)]
            mom=mom[mom.index.isin(set(liq.sort_values(ascending=False).head(UNIV).index))]
            if len(mom)>=10:
                k=max(1,int(len(mom)*DEC))
                L=set(mom.sort_values(ascending=False).head(k).index)
                S=set(mom.sort_values(ascending=True).head(k).index)
                gross=0.5*(float(fwd[list(L)].mean())-float(fwd[list(S)].mean()))
                tl=len(pl^L)/(2*max(1,len(pl|L))) if (pl|L) else (1.0 if L else 0)
                tsh=len(ps^S)/(2*max(1,len(ps|S))) if (ps|S) else (1.0 if S else 0)
                ret=gross-(tl+tsh)*TRADE_FEE
        rets.append((date,ret)); pl=L; ps=S; i+=HOLD
    return rets

def perf(rets):
    r=np.array([x for d,x in rets])
    if len(r)<4: return None
    eq=np.cumprod(1+r); sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    pos=r[r>0].sum(); neg=-r[r<0].sum(); pf=(pos/neg) if neg>0 else float('inf')
    return dict(n=len(r),tot=(eq[-1]-1)*100,sh=sh,pf=pf,dd=maxdd(eq))
def fmt(m):
    if not m: return "n<4"
    pf='inf' if m['pf']==float('inf') else f"{m['pf']:.2f}"
    return f"n={m['n']:>3} tot={m['tot']:>+6.0f}% Sharpe={m['sh']:>5.2f} PF={pf:>5} MaxDD={m['dd']:>5.0f}%"

out=[]
covered=set(fk.keys())
out.append(f"FUTURES REALITY TEST — covered universe={len(covered)} symbols, period 2024-2025, fee={TRADE_FEE*100}%/side")
out.append("="*108)
out.append("LEVEL 1+2 — matched-universe runs (separate universe-shrink cost from futures/funding cost):")
A=perf(run_spot(symset=None,y0=2024))
B=perf(run_spot(symset=list(covered),y0=2024))
C_rets,agg=run_fut(use_funding=True,y0=2024)
Cnf,_=run_fut(use_funding=False,y0=2024)
C=perf(C_rets); Cn=perf(Cnf)
out.append(f"  A) SPOT full-250 universe       : {fmt(A)}")
out.append(f"  B) SPOT on covered-{len(covered)} subset   : {fmt(B)}")
out.append(f"  C) FUTURES prices, NO funding   : {fmt(Cn)}")
out.append(f"  C') FUTURES + REAL funding      : {fmt(C)}")
out.append(f"  --> universe-shrink cost (A->B) = {(B['tot']-A['tot']) if (A and B) else 0:+.0f}% total")
out.append(f"  --> futures-price effect (B->C) = {(Cn['tot']-B['tot']) if (Cn and B) else 0:+.0f}% total")
out.append(f"  --> REAL FUNDING cost (C->C')   = {(C['tot']-Cn['tot']) if (C and Cn) else 0:+.0f}% total")
out.append("")
out.append("LEVEL 3 — per-leg decomposition (cumulative, 2024-25, futures):")
out.append(f"  {'component':<22}{'cum return':>12}")
out.append(f"  {'Long leg (gross)':<22}{agg['long']*100:>+11.1f}%")
out.append(f"  {'Short leg (gross)':<22}{agg['short']*100:>+11.1f}%")
out.append(f"  {'Funding on LONG':<22}{agg['fund_long']*100:>+11.1f}%   (long pays positive funding)")
out.append(f"  {'Funding on SHORT':<22}{agg['fund_short']*100:>+11.1f}%   (short receives positive funding)")
out.append(f"  {'NET funding':<22}{(agg['fund_long']+agg['fund_short'])*100:>+11.1f}%")
tot_net=(agg['long']+agg['short']+agg['fund_long']+agg['fund_short'])*100
out.append(f"  {'NET (pre-fee)':<22}{tot_net:>+11.1f}%")
out.append("="*108)
out.append("VERDICT: does real funding kill it? if C' Sharpe still >0.7 and funding doesn't flip net negative => survives reality.")
text="\n".join(out); print(text)
with open('/app/logs/fut_reality_report.txt','w') as f: f.write(text)
