#!/usr/bin/env python3
"""تشريح الفترات العشر المربحة للنموذج الكامل (look30 hold14 dec10 Top30 gated، spot 2024-25).
1) جدول كل فترة: تاريخ، عائد، حالة سوق، BTC>EMA50، أداء BTC/ETH، breadth، عدد العملات، أكبر مساهمين.
2) توزّع زمني. 3) تكرار العملات عبر الفترات. 4) حذف أفضل N فترات → Sharpe/PF المتبقي.
لا شيء إضافي."""
import sys, glob
import numpy as np, pandas as pd
from collections import Counter
sys.path.insert(0,'/app')
from bt_engine import load, DATA
LOOK,HOLD,DEC,UNIV=30,14,0.10,30; FEE=0.004
syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
closes={}; dvol={}
for s in syms:
    df=load(s,'1d')
    if df is None: continue
    ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
    c=pd.Series(df['close'].values,index=ix); closes[s]=c[~c.index.duplicated()]
    d=pd.Series((df['close']*df['volume']).values,index=ix); dvol[s]=d[~d.index.duplicated()]
panel=pd.DataFrame(closes).sort_index(); dv=pd.DataFrame(dvol).reindex(panel.index)
idx=panel.index
btc=panel['BTCUSDT'].dropna(); e5=btc.ewm(span=50).mean(); e2=btc.ewm(span=200).mean()
eth=panel['ETHUSDT'].dropna() if 'ETHUSDT' in panel else None
def ro(d):
    p=btc.get(d,np.nan); a=e5.get(d,np.nan); b=e2.get(d,np.nan)
    return True if (np.isnan(p) or np.isnan(b)) else (p>a and p>b)

records=[]  # كل فترة نشطة: dict
i=LOOK
while i+HOLD<len(idx):
    date=idx[i]
    if date.year<2024: i+=HOLD; continue
    now=panel.iloc[i]; fut=panel.iloc[i+HOLD]; past=panel.iloc[i-LOOK]
    fwd=(fut/now-1); ret=0.0; on=ro(date); contrib={}
    if on:
        v=(now>0)&fwd.notna()&past.notna(); cand=fwd.index[v]
        liq=dv.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(cand)]
        cand=liq.sort_values(ascending=False).head(UNIV).index
        if len(cand)>=10:
            mom=(now/past-1)[list(cand)].dropna()
            k=max(1,int(len(mom)*DEC))
            L=list(mom.sort_values(ascending=False).head(k).index)
            S=list(mom.sort_values(ascending=True).head(k).index)
            for s in L: contrib[s]=contrib.get(s,0)+0.5*float(fwd[s])/k
            for s in S: contrib[s]=contrib.get(s,0)+0.5*(-float(fwd[s]))/k
            ret=sum(contrib.values())-(2*FEE)  # تقريب رسوم
            # breadth: نسبة العملات السائلة فوق EMA50 الخاص بها (تقريب: عائد 30 يوم موجب)
            breadth=float(((now/past-1)[list(cand)]>0).mean())
            btc_ret=float(btc.get(idx[i+HOLD],np.nan)/btc.get(date,np.nan)-1) if not np.isnan(btc.get(date,np.nan)) else np.nan
            eth_ret=float(eth.get(idx[i+HOLD],np.nan)/eth.get(date,np.nan)-1) if (eth is not None and not np.isnan(eth.get(date,np.nan))) else np.nan
            top3=sorted(contrib.items(),key=lambda x:-x[1])[:3]
            records.append(dict(date=date, ret=ret, on=on, breadth=breadth,
                btc_ret=btc_ret, eth_ret=eth_ret, ncoins=len(cand),
                top3=", ".join(f"{s}({v*100:+.0f})" for s,v in top3),
                longset=set(L), shortset=set(S)))
    i+=HOLD

allrets=[r['ret'] for r in records]
recs_sorted=sorted(records,key=lambda r:r['ret'],reverse=True)
top10=recs_sorted[:10]
out=[]
out.append("PERIOD DISSECTION — FULL model (look30/hold14/dec10/Top30/gated), spot 2024-25, active periods only")
out.append(f"total active periods={len(records)}  net total={sum(allrets)*100:+.1f}%")
out.append("="*132)
out.append("(1) TOP 10 PERIODS:")
out.append(f"  {'entry_date':<12}{'exit~':<12}{'ret%':>7}{'BTC>E50':>8}{'btcRet%':>8}{'ethRet%':>8}{'breadth':>8}{'nCoins':>7}  top3 contributors")
for r in top10:
    exitd=(r['date']+pd.Timedelta(days=HOLD)).date()
    out.append(f"  {str(r['date'].date()):<12}{str(exitd):<12}{r['ret']*100:>+6.1f}{'Y' if r['on'] else 'N':>8}"
               f"{(r['btc_ret']*100 if not np.isnan(r['btc_ret']) else 0):>+7.1f}{(r['eth_ret']*100 if not np.isnan(r['eth_ret']) else 0):>+7.1f}"
               f"{r['breadth']*100:>7.0f}%{r['ncoins']:>7}  {r['top3']}")
out.append("")
# (2) توزّع زمني
out.append("="*132)
out.append("(2) TEMPORAL DISTRIBUTION of top-10 (by quarter):")
q=Counter(f"{r['date'].year}Q{(r['date'].month-1)//3+1}" for r in top10)
out.append("  "+"  ".join(f"{k}:{v}" for k,v in sorted(q.items())))
months=Counter(f"{r['date'].year}-{r['date'].month:02d}" for r in top10)
out.append("  by month: "+"  ".join(f"{k}:{v}" for k,v in sorted(months.items())))
# (3) تكرار العملات
out.append("")
out.append("="*132)
out.append("(3) COIN RECURRENCE across top-10 (long-leg picks):")
lc=Counter();
for r in top10:
    for s in r['longset']: lc[s]+=1
out.append("  long-leg coins appearing in >=2 of top-10 periods:")
for s,c in lc.most_common():
    if c>=2: out.append(f"    {s:<14}{c} periods")
out.append(f"  distinct long coins across top-10: {len(lc)}  (low=concentrated, high=diverse)")
# breadth في الأفضل مقابل البقية
top_breadth=np.mean([r['breadth'] for r in top10])
rest_breadth=np.mean([r['breadth'] for r in recs_sorted[10:]]) if len(recs_sorted)>10 else 0
out.append("")
out.append(f"(3b) avg breadth in top-10 = {top_breadth*100:.0f}%  vs rest = {rest_breadth*100:.0f}%  (high top-breadth => alt-expansion dependent)")
btc_top=np.nanmean([r['btc_ret'] for r in top10]); btc_rest=np.nanmean([r['btc_ret'] for r in recs_sorted[10:]])
out.append(f"     avg BTC return in top-10 = {btc_top*100:+.1f}%  vs rest = {btc_rest*100:+.1f}%")
# (4) حذف أفضل N
out.append("")
out.append("="*132)
out.append("(4) REMOVE TOP-N PERIODS — does edge survive without the best events?")
def perf(rl):
    r=np.array(rl)
    if len(r)<4: return None
    eq=np.cumprod(1+r); sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    pos=r[r>0].sum(); neg=-r[r<0].sum(); pf=(pos/neg) if neg>0 else float('inf')
    return sh,pf,(eq[-1]-1)*100
srt=sorted(allrets,reverse=True)
for n in [0,1,3,5,10]:
    kept=srt[n:]
    m=perf(kept)
    if m:
        pf='inf' if m[1]==float('inf') else f"{m[1]:.2f}"
        out.append(f"  remove top {n:>2}: Sharpe={m[0]:>5.2f}  PF={pf:>5}  tot={m[2]:>+6.0f}%   (n={len(kept)})")
out.append("  USER BAR: after removing top-5, PF>1.2 AND Sharpe>0.7 => robust edge. collapse => rare-event dependent.")
text="\n".join(out); print(text)
open('/app/logs/period_dissection_report.txt','w').write(text)
