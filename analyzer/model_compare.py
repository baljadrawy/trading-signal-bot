#!/usr/bin/env python3
"""تقرير المقارنة البسيط — كل النماذج بطريقة الشرائح اليومية المُزال-تحيّزها (14 طوراً، 1/14 رأس مال).
Long/Short (آجلة) · Long-Only+Cash (سبوت) · Top5 Long-Only · BTC Buy&Hold.
السؤال: هل توجد نسخة سبوت قابلة للتنفيذ، أم الحافة معتمدة على الشورت؟"""
import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA
LOOK,HOLD,UNIV=30,14,30; FEE=0.004
syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
closes={}; dvol={}
for s in syms:
    df=load(s,'1d')
    if df is None: continue
    ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
    closes[s]=pd.Series(df['close'].values,index=ix).pipe(lambda x:x[~x.index.duplicated()])
    dvol[s]=pd.Series((df['close']*df['volume']).values,index=ix).pipe(lambda x:x[~x.index.duplicated()])
panel=pd.DataFrame(closes).sort_index(); dv=pd.DataFrame(dvol).reindex(panel.index)
idx=panel.index; N=len(idx); dret=panel.pct_change()
btc=panel['BTCUSDT'].dropna(); e5=btc.ewm(span=50).mean(); e2=btc.ewm(span=200).mean()
def ro_at(i):
    d=idx[i]; p=btc.get(d,np.nan); a=e5.get(d,np.nan); b=e2.get(d,np.nan)
    return True if (np.isnan(p) or np.isnan(b)) else (p>a and p>b)
def pick(i,klong,kshort,rel=False):
    if not ro_at(i): return set(),set()
    now=panel.iloc[i]; past=panel.iloc[i-LOOK]
    v=(now>0)&past.notna(); cand=now.index[v]
    liq=dv.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(cand)]
    cand=liq.sort_values(ascending=False).head(UNIV).index
    if len(cand)<10: return set(),set()
    mom=(now/past-1)[list(cand)].dropna()
    if rel:  # relative to BTC momentum
        bm=float(btc.iloc[i]/btc.iloc[i-LOOK]-1); mom=mom-bm
    L=set(mom.sort_values(ascending=False).head(klong).index) if klong else set()
    S=set(mom.sort_values(ascending=True).head(kshort).index) if kshort else set()
    return L,S
def tranche_daily(mode):
    """mode: 'ls'(long-short neutral) | 'lo3'/'lo5'(long-only+cash) | 'lo3rel'(relative)"""
    port=np.zeros(N)
    for off in range(HOLD):
        reb=set(range(LOOK+off,N-1,HOLD))
        curL=set();curS=set();prevL=set();prevS=set()
        for i in range(LOOK,N):
            if i in reb:
                prevL,prevS=curL,curS
                if mode=='ls': curL,curS=pick(i,3,3)
                elif mode=='lo3': curL,curS=pick(i,3,0)
                elif mode=='lo5': curL,curS=pick(i,5,0)
                elif mode=='lo3rel': curL,curS=pick(i,3,0,rel=True)
            if idx[i].year<2024: continue
            r=0.0
            if mode=='ls':
                if curL or curS:
                    rl=np.nanmean([dret[s].iloc[i] for s in curL]) if curL else 0.0
                    rs=np.nanmean([dret[s].iloc[i] for s in curS]) if curS else 0.0
                    r=0.5*(rl-rs)
                    if i in reb:
                        tl=len(prevL^curL)/(2*max(1,len(prevL|curL))) if (prevL|curL) else (1 if curL else 0)
                        ts=len(prevS^curS)/(2*max(1,len(prevS|curS))) if (prevS|curS) else (1 if curS else 0)
                        r-=(tl+ts)*FEE
            else:  # long-only + cash
                if curL:
                    r=np.nanmean([dret[s].iloc[i] for s in curL])
                    if i in reb:
                        tl=len(prevL^curL)/(2*max(1,len(prevL|curL))) if (prevL|curL) else (1 if curL else 0)
                        r-=tl*FEE
                # لو risk-off: curL فارغة → r=0 (نقد)
            if not np.isnan(r): port[i]+=r/HOLD
    return port
def btc_daily():
    r=np.zeros(N)
    for i in range(1,N):
        if idx[i].year>=2024:
            a=btc.get(idx[i-1],np.nan); b=btc.get(idx[i],np.nan)
            if not np.isnan(a) and not np.isnan(b) and a>0: r[i]=b/a-1
    return r
def stats(dr,yr=None):
    m=np.array([idx[i].year>=2024 and (yr is None or idx[i].year==yr) for i in range(N)])
    x=dr[m]; x=x[~np.isnan(x)]
    if len(x)<20: return None
    eq=np.cumprod(1+x); sh=x.mean()/x.std()*np.sqrt(252) if x.std()>0 else 0
    pos=x[x>0].sum(); neg=-x[x<0].sum(); pf=(pos/neg) if neg>0 else float('inf')
    pk=np.maximum.accumulate(eq); dd=float(((eq-pk)/pk).min()*100)
    return dict(tot=(eq[-1]-1)*100,sh=sh,pf=pf,dd=dd)
def line(name,dr):
    F=stats(dr); Y=stats(dr,2025)
    def f(m): return f"Sh={m['sh']:>5.2f} PF={m['pf']:>5.2f} ret={m['tot']:>+6.0f}% DD={m['dd']:>5.0f}%" if m else "n<20"
    return f"  {name:<26} FULL: {f(F)}   |  2025: {f(Y)}"
out=[]
out.append("MODEL COMPARISON — de-biased daily staggered-tranche (14 phases), 2024-25 + 2025 OOS. fee0.4%/side.")
out.append("="*120)
out.append(line("Long/Short (futures)", tranche_daily('ls')))
out.append(line("Long-Only top3 +Cash", tranche_daily('lo3')))
out.append(line("Long-Only top5 +Cash", tranche_daily('lo5')))
out.append(line("Long-Only top3 RELATIVE", tranche_daily('lo3rel')))
out.append(line("BTC Buy&Hold", btc_daily()))
out.append("="*120)
out.append("KEY: if Long/Short >> Long-Only => edge is short-dependent (needs futures), spot versions won't capture it.")
out.append("     if Long-Only <= BTC Buy&Hold => no executable spot edge; just hold BTC.")
text="\n".join(out); print(text)
open('/app/logs/model_compare_report.txt','w').write(text)
