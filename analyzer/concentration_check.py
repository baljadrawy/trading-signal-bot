#!/usr/bin/env python3
"""فحص هشاشة التركّز — Top30/decile10% = ~3 long + 3 short. هل Sharpe 1.74 من رهان 6 مراكز
يقوده عدد قليل من العملات/فترات؟ نشرّح PnL لكل ساق عبر العملات والفترات. بيانات السبوت الموجودة."""
import sys, glob
import numpy as np, pandas as pd
from collections import defaultdict
sys.path.insert(0,'/app')
from bt_engine import load, DATA

LOOK,HOLD,DEC,UNIV=30,14,0.10,30
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
    p=btc.get(date,np.nan); e5=ema50.get(date,np.nan); e2=ema200.get(date,np.nan)
    if np.isnan(p) or np.isnan(e2): return True
    return p>e5 and p>e2

long_by_coin=defaultdict(float); short_by_coin=defaultdict(float)
period_pnl=[]; long_contrib=[]; short_contrib=[]; i=LOOK
while i+HOLD<len(idx):
    date=idx[i]; now=panel.iloc[i]; fut=panel.iloc[i+HOLD]; past=panel.iloc[i-LOOK]
    fwd=(fut/now-1)
    if riskon(date):
        mom=(now/past-1); v=mom.notna()&fwd.notna()&past.notna()&(now>0); mom=mom[v]
        liq=dv.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(mom.index)]
        mom=mom[mom.index.isin(set(liq.sort_values(ascending=False).head(UNIV).index))]
        if len(mom)>=10:
            k=max(1,int(len(mom)*DEC))
            Ls=mom.sort_values(ascending=False).head(k).index
            Ss=mom.sort_values(ascending=True).head(k).index
            lr=float(fwd[list(Ls)].mean()); sr=-float(fwd[list(Ss)].mean())
            for s in Ls: long_by_coin[s]+=float(fwd[s])/len(Ls)
            for s in Ss: short_by_coin[s]+=(-float(fwd[s]))/len(Ss)
            period_pnl.append((date,0.5*(lr+sr))); long_contrib.append(lr*0.5); short_contrib.append(sr*0.5)
    i+=HOLD

tot=sum(x for _,x in period_pnl)
lc=sum(long_contrib); sc=sum(short_contrib)
out=[]
out.append("LONG-LEG / SHORT-LEG CONCENTRATION (spot proxy, gross of funding) — fragility of the 6-position bet")
out.append("="*92)
out.append(f"periods traded (risk-on): {len(period_pnl)}  | total cum gross spread = {tot*100:+.1f}%")
out.append(f"  LONG leg contribution : {lc*100:+.1f}%  ({lc/tot*100:.0f}% of total)" if tot else "")
out.append(f"  SHORT leg contribution: {sc*100:+.1f}%  ({sc/tot*100:.0f}% of total)" if tot else "")
out.append("")
out.append("TOP 10 LONG-leg coins by cumulative contribution:")
for s,v in sorted(long_by_coin.items(),key=lambda x:-x[1])[:10]:
    out.append(f"   {s:<14}{v*100:>+7.1f}%")
out.append("TOP 10 SHORT-leg coins by cumulative contribution:")
for s,v in sorted(short_by_coin.items(),key=lambda x:-x[1])[:10]:
    out.append(f"   {s:<14}{v*100:>+7.1f}%")
out.append("")
# تركّز الفترات
pv=sorted([x for _,x in period_pnl],reverse=True)
top3=sum(pv[:3]); top5=sum(pv[:5])
out.append(f"PERIOD concentration: top-3 periods = {top3*100:+.1f}% ({top3/tot*100:.0f}% of total), top-5 = {top5*100:+.1f}% ({top5/tot*100:.0f}%)")
out.append(f"  positive periods: {sum(1 for x in pv if x>0)}/{len(pv)} ({sum(1 for x in pv if x>0)/len(pv)*100:.0f}%)")
nL=len(long_by_coin); nS=len(short_by_coin)
out.append(f"  distinct coins used: long={nL}, short={nS}")
out.append("="*92)
out.append("READ: if long-leg contributes most AND short funding will be costly → net edge at risk.")
out.append("      if 1-2 coins or 3 periods dominate → fragile, not a broad factor.")
text="\n".join(out); print(text)
with open('/app/logs/concentration_report.txt','w') as f: f.write(text)
