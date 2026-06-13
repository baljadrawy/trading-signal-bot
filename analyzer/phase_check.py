# Re-run with different rebalance-grid start offsets to test robustness of 2025 PF
import importlib.util, sys
sys.argv=['x']
spec=importlib.util.spec_from_file_location("iv","/app/indep_verify.py")
import os, zipfile
import numpy as np, pandas as pd
iv=importlib.util.module_from_spec(spec); spec.loader.exec_module(iv)

# rebuild data once
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
    prev_long=set(); prev_short=set(); rec=[]
    i=start
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
        fwd=(rth[uni]/rt[uni]-1)
        active=bool(regime_on.get(t,False))
        if active:
            g=0.5*(fwd[L].mean()-fwd[S].mean())
            nl,ns=set(L),set(S)
            def to(p,nw):
                u=p|nw; return len(p^nw)/(2*len(u)) if u else 0
            net=g-(to(prev_long,nl)+to(prev_short,ns))*iv.FEE_RATE
            prev_long,prev_short=nl,ns
        else:
            net=0; prev_long,prev_short=set(),set()
        rec.append({"year":yr,"net":net}); i+=iv.REBAL
    r=pd.DataFrame(rec)
    out={}
    for lab,sub in [("full",r),("2025",r[r.year==2025])]:
        x=sub.net.values
        pos=x[x>0].sum(); neg=x[x<0].sum()
        pf=pos/abs(neg) if neg<0 else float('inf')
        sd=x.std(ddof=1)
        sh=x.mean()/sd*np.sqrt(52) if sd>0 else float('nan')
        out[lab]=(np.prod(1+x)-1, sh, pf, len(sub))
    return out

for st in [28,29,30,31,32,33,34]:
    o=run(st)
    print(f"start_i={st} ({dates[st].date()}): FULL comp={o['full'][0]*100:6.1f}% Sh={o['full'][1]:.2f} PF={o['full'][2]:.2f} | 2025 comp={o['2025'][0]*100:6.1f}% Sh={o['2025'][1]:.2f} PF={o['2025'][2]:.2f} np={o['2025'][3]}")
