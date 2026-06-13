#!/usr/bin/env python3
"""اختبار الأولوية 1 بشكل صحيح: Cross-Sectional Momentum — alpha أم beta؟
يقارن: long أقوى 10% (top) مقابل أضعف 10% (bottom) مقابل السوق (equal-weight).
- top-bottom = انتقاء محايد للسوق (alpha النقي).
- top-market = هل التحيّز للأقوى يتفوّق على الاحتفاظ بالسوق.
فلتر النظام: BTC فوق/تحت EMA50 (risk-on/off). per-year. رسوم إعادة موازنة أسبوعية.
"""
import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA

LOOK=30; HOLD=7; DEC=0.10
FEE=0.4  # % تكلفة دوران لكل مركز أسبوعي (تقريب)

syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
closes={}
for s in syms:
    df=load(s,'1d')
    if df is None: continue
    ser=pd.Series(df['close'].values, index=pd.to_datetime(df['t'],unit='ms').dt.normalize())
    closes[s]=ser[~ser.index.duplicated()]
panel=pd.DataFrame(closes).sort_index()
print(f"panel: {panel.shape[0]} days x {panel.shape[1]} symbols",flush=True)

# نظام السوق من BTC
if 'BTCUSDT' in panel: btc=panel['BTCUSDT'].dropna()
else:
    b=load('BTCUSDT','1d'); btc=pd.Series(b['close'].values,index=pd.to_datetime(b['t'],unit='ms').dt.normalize())
regime=(btc>btc.ewm(span=50).mean())   # risk-on

idx=panel.index
rec=[]
i=LOOK
while i+HOLD<len(idx):
    date=idx[i]
    past=panel.iloc[i-LOOK]; now=panel.iloc[i]; fut=panel.iloc[i+HOLD]
    mom=(now/past-1); fwd=(fut/now-1)
    v=mom.notna()&fwd.notna()&past.notna()&(now>0)
    mom=mom[v]; fwd=fwd[v]
    if len(mom)<20: i+=HOLD; continue
    k=max(1,int(len(mom)*DEC))
    top=mom.sort_values(ascending=False).head(k).index
    bot=mom.sort_values(ascending=True).head(k).index
    rec.append((date.year, bool(regime.get(date,False)),
                fwd[top].mean()*100, fwd[bot].mean()*100, fwd.mean()*100))
    i+=HOLD
df=pd.DataFrame(rec,columns=['year','riskon','top','bot','mkt'])
N=len(df)

def summ(d,label):
    if len(d)==0: return f"{label:<22} (no periods)"
    top_g=d.top.mean(); bot_g=d.bot.mean(); mkt_g=d.mkt.mean()
    top_n=top_g-FEE; bot_n=bot_g-FEE
    spread=top_g-bot_g; tmm=top_g-mkt_g
    # PF of weekly net top returns
    x=d.top.values-FEE; pos=x[x>0].sum(); neg=-x[x<0].sum()
    pf=(pos/neg) if neg>0 else float('inf')
    wr=(d.top.values>FEE).mean()*100
    return (f"{label:<22} periods={len(d):>4}  top_net={top_n:>+6.2f}%  mkt={mkt_g:>+6.2f}%  bot_net={bot_n:>+6.2f}%  "
            f"|  top-mkt={tmm:>+6.2f}%  top-bot(alpha)={spread:>+6.2f}%  top_PF={('inf' if pf==float('inf') else f'{pf:.2f}')}  WR={wr:.0f}%")

out=[]
out.append("CROSS-SECTIONAL MOMENTUM — alpha vs beta test")
out.append(f"weekly rebalance, look={LOOK}d hold={HOLD}d, long top/bottom {int(DEC*100)}%, fee={FEE}%/position. N={N} periods")
out.append("returns are per-{}d-period %. top_net=long strongest(net). mkt=equal-weight all. bot=long weakest.".format(HOLD))
out.append("KEY: top-bot>0 = real selection alpha (market-neutral). top-mkt>0 = beats holding market.")
out.append("="*130)
out.append(summ(df,"ALL"))
out.append("-- by year --")
for y in (2023,2024,2025): out.append(summ(df[df.year==y],f"  {y}"))
out.append("-- by regime --")
out.append(summ(df[df.riskon],"  RISK-ON (BTC>EMA50)"))
out.append(summ(df[~df.riskon],"  RISK-OFF (BTC<EMA50)"))
out.append("="*130)
# verdict helpers
allm=df
out.append(f"VERDICT INPUTS: mean top-bot(alpha)={ (allm.top-allm.bot).mean():+.3f}%  mean top-mkt={(allm.top-allm.mkt).mean():+.3f}%  "
           f"alpha>0 share={ (allm.top>allm.bot).mean()*100:.0f}%")
text="\n".join(out); print(text)
with open('/app/logs/momentum_test_report.txt','w') as f: f.write(text)
