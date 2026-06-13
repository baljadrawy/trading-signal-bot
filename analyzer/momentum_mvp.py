#!/usr/bin/env python3
"""MVP المرحلة 1+2: regime-gated cross-sectional momentum (spot, long-only).
كل أسبوع: إذا risk-on → equal-weight أفضل decile بعائد 30 يوم؛ إذا risk-off → نقد.
يقارن منحنى رأس المال الصافي مع: BTC hold، equal-weight hold. Sharpe/MaxDD/عائد سنوي.
رسوم دوران 0.4% × نسبة التغيّر لكل إعادة موازنة.
"""
import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA

LOOK=30; HOLD=7; DEC=0.10; FEE=0.4/100  # round-trip per rotated fraction

syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
closes={}
for s in syms:
    df=load(s,'1d')
    if df is None: continue
    ser=pd.Series(df['close'].values, index=pd.to_datetime(df['t'],unit='ms').dt.normalize())
    closes[s]=ser[~ser.index.duplicated()]
panel=pd.DataFrame(closes).sort_index()
idx=panel.index
print(f"panel {panel.shape[0]}d x {panel.shape[1]} syms",flush=True)

btc=panel['BTCUSDT'].dropna() if 'BTCUSDT' in panel else None
if btc is None:
    b=load('BTCUSDT','1d'); btc=pd.Series(b['close'].values,index=pd.to_datetime(b['t'],unit='ms').dt.normalize())
ema50=btc.ewm(span=50).mean(); ema200=btc.ewm(span=200).mean()

def regime_on(date,variant):
    p=btc.get(date,np.nan); e50=ema50.get(date,np.nan); e200=ema200.get(date,np.nan)
    if np.isnan(p) or np.isnan(e200): return True  # default in (warmup)
    if variant=='ema200': return p>e200
    if variant=='ema50_200': return p>e50 and p>e200
    return True

def maxdd(equity):
    eq=np.array(equity); peak=np.maximum.accumulate(eq); return float(((eq-peak)/peak).min()*100)

def run_strategy(variant):
    eq=1.0; curve=[]; prev=set(); wk=[]
    i=LOOK
    while i+HOLD<len(idx):
        date=idx[i]
        now=panel.iloc[i]; fut=panel.iloc[i+HOLD]; past=panel.iloc[i-LOOK]
        fwd=(fut/now-1)
        on=regime_on(date,variant)
        if on:
            mom=(now/past-1)
            v=mom.notna()&fwd.notna()&past.notna()&(now>0)
            mom=mom[v]
            if len(mom)>=20:
                k=max(1,int(len(mom)*DEC)); sel=set(mom.sort_values(ascending=False).head(k).index)
                gross=float(fwd[list(sel)].mean())
            else: sel=set(); gross=0.0
        else:
            sel=set(); gross=0.0  # cash
        # turnover fee
        union=prev|sel
        turnover=(len(prev^sel)/ (2*max(1,len(union)))) if union else 0.0  # fraction changed (0..1)
        cost=turnover*FEE*2  # both sides
        net=gross-cost
        eq*= (1+net)
        wk.append((date.year,net,on))
        curve.append(eq); prev=sel
        i+=HOLD
    return curve, wk

def bench_series(kind):
    eq=1.0; curve=[]
    i=LOOK
    while i+HOLD<len(idx):
        now=panel.iloc[i]; fut=panel.iloc[i+HOLD]
        if kind=='btc':
            a=btc.get(idx[i],np.nan); b=btc.get(idx[i+HOLD],np.nan)
            r=(b/a-1) if (not np.isnan(a) and not np.isnan(b) and a>0) else 0.0
        else: # equal-weight all
            r=float(((fut/now-1)).replace([np.inf,-np.inf],np.nan).dropna().mean())
            if np.isnan(r): r=0.0
        eq*=(1+r); curve.append(eq); i+=HOLD
    return curve

def stats(curve,wk=None,label=""):
    c=np.array(curve); tot=(c[-1]-1)*100
    rets=np.diff(np.concatenate([[1.0],c]))/np.concatenate([[1.0],c])[:-1]
    sharpe=rets.mean()/rets.std()*np.sqrt(52) if rets.std()>0 else 0
    dd=maxdd(curve)
    line=f"{label:<26} totRet={tot:>+8.1f}%  Sharpe={sharpe:>5.2f}  MaxDD={dd:>7.1f}%  finalEq={c[-1]:.2f}"
    if wk is not None:
        inmkt=np.mean([w[2] for w in wk])*100
        line+=f"  inMkt={inmkt:.0f}%"
    return line, rets

def per_year(wk):
    s={}
    for y in (2023,2024,2025):
        r=[w[1] for w in wk if w[0]==y]
        if r:
            eq=np.prod([1+x for x in r]); s[y]=(eq-1)*100
    return s

out=[]
out.append("PHASE 1+2 MVP — regime-gated cross-sectional momentum (spot, long-only, net of 0.4% turnover fee)")
out.append(f"weekly rebalance, look={LOOK}d hold={HOLD}d, top {int(DEC*100)}% momentum. periods over 2023-2025.")
out.append("="*110)
for variant in ['ema200','ema50_200']:
    curve,wk=run_strategy(variant)
    ln,_=stats(curve,wk,f"STRATEGY [{variant}]")
    out.append(ln)
    py=per_year(wk)
    out.append("    per-year: "+"  ".join(f"{y}:{py.get(y,0):+.1f}%" for y in (2023,2024,2025)))
# always-on (no regime) for comparison
curve_on,wk_on=run_strategy('none')
out.append(stats(curve_on,wk_on,"STRATEGY [no regime/always]")[0])
out.append("-"*110)
out.append(stats(bench_series('btc'),None,"BENCH: BTC hold")[0])
out.append(stats(bench_series('ew'),None,"BENCH: equal-weight hold")[0])
out.append("="*110)
out.append("READ: strategy worth pursuing only if it beats BOTH benchmarks on risk-adjusted (Sharpe) AND MaxDD,")
out.append("      i.e. the regime gate must cut drawdown meaningfully while keeping most of the upside.")
text="\n".join(out); print(text)
with open('/app/logs/momentum_mvp_report.txt','w') as f: f.write(text)
