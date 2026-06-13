import sys, glob
sys.path.insert(0,'/app')
import numpy as np, pandas as pd
from bt_engine import load, DATA
syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
firsts={}; lasts={}; PMAX=None
for s in syms:
    df=load(s,'1d')
    if df is None:
        continue
    ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
    firsts[s]=ix.min(); lasts[s]=ix.max()
    PMAX=ix.max() if PMAX is None else max(PMAX,ix.max())
ld=pd.Series(lasts); fd=pd.Series(firsts)
print("symbols with data:",len(ld),"| panel max:",str(PMAX.date()))
for thr in [7,30,90,180]:
    n=int((ld < PMAX - pd.Timedelta(days=thr)).sum())
    print("  ended >%dd early (in-sample delist captured):"%thr, n)
print("first-listing by year:", {int(k):int(v) for k,v in fd.dt.year.value_counts().sort_index().items()})
for d in ['2023-01-15','2024-01-15','2025-01-15','2025-12-15']:
    dt=pd.Timestamp(d)
    alive=sum(1 for s in syms if firsts.get(s) is not None and firsts[s]<=dt and lasts[s]>=dt)
    print("  alive on %s:"%d, alive)
