import importlib.util, sys, os, zipfile
import numpy as np, pandas as pd
sys.argv=['x']
spec=importlib.util.spec_from_file_location("iv","/app/indep_verify.py")
iv=importlib.util.module_from_spec(spec); spec.loader.exec_module(iv)
with open(iv.SYMFILE) as f: symbols=[l.strip() for l in f if l.strip()]
closes={}; advols={}
for s in symbols:
    df=iv.load_symbol(s)
    if df is None or len(df)<60: continue
    closes[s]=df["close"]; advols[s]=df["dollar_vol"]
close_df=pd.DataFrame(closes).sort_index()
dv_df=pd.DataFrame(advols).reindex(close_df.index)
btc=close_df["BTCUSDT"].dropna()
regime_on=(btc>btc.ewm(span=50,adjust=False).mean())&(btc>btc.ewm(span=200,adjust=False).mean())
dates=close_df.index; n=len(dates)
def run(start):
    prev_long=set(); prev_short=set(); rec=[]; i=start
    while i+iv.HOLD<n:
        t=dates[i]
        adv=dv_df.iloc[i-iv.ADV_WIN:i].mean(axis=0)
        rt=close_df.iloc[i]; rtm=close_df.iloc[i-iv.LOOKBACK_MOM]; rth=close_df.iloc[i+iv.HOLD]
        valid=adv.notna()&rt.notna()&rtm.notna()&rth.notna()&(rt>0)&(rtm>0)
        uni=adv[valid].dropna().sort_values(ascending=False).head(iv.TOP_N).index.tolist()
        yr=t.year
        if len(uni)<10 or yr<2024: i+=iv.REBAL; continue
        mom=(rt[uni]/rtm[uni]-1).sort_values(ascending=False)
        k=max(1,int(round(len(uni)*0.10)))
        L=mom.head(k).index.tolist(); S=mom.tail(k).index.tolist()
        fwd=(rth[uni]/rt[uni]-1); active=bool(regime_on.get(t,False))
        if active:
            g=0.5*(fwd[L].mean()-fwd[S].mean()); nl,ns=set(L),set(S)
            def to(p,nw):
                u=p|nw; return len(p^nw)/(2*len(u)) if u else 0
            net=g-(to(prev_long,nl)+to(prev_short,ns))*iv.FEE_RATE; prev_long,prev_short=nl,ns
        else: net=0; prev_long,prev_short=set(),set()
        rec.append({"year":yr,"net":net}); i+=iv.REBAL
    r=pd.DataFrame(rec); x=r.net.values; x25=r[r.year==2025].net.values
    def pf(a): 
        p=a[a>0].sum(); ng=a[a<0].sum(); return p/abs(ng) if ng<0 else float('inf')
    return (np.prod(1+x)-1, pf(x), np.prod(1+x25)-1, pf(x25))
rows=[]
for st in range(30,44):
    comp,pff,c25,pf25=run(st)
    rows.append((st,dates[st].date(),comp,pff,c25,pf25))
    print(f"phase i={st} ({dates[st].date()}): FULL comp={comp*100:7.1f}% PF={pff:5.2f} | 2025 comp={c25*100:7.1f}% PF={pf25:5.2f}")
pfs25=[r[5] for r in rows]
ref=rows[0][5]
rank=sorted(pfs25,reverse=True).index(ref)+1
prof=sum(1 for p in pfs25 if p>1)
print(f"\n2025 PF across all 14 phases: min={min(pfs25):.2f} median={sorted(pfs25)[len(pfs25)//2]:.2f} max={max(pfs25):.2f}")
print(f"Reference phase (i=30) 2025 PF={ref:.2f} ranks #{rank} of 14 (1=best)")
print(f"Profitable phases (2025 PF>1): {prof}/14")
