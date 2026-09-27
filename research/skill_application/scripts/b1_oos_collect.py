#!/usr/bin/env python3
"""B1 OOS collector — reconstruct the live bot score via W weights on historical
data (598 syms, 1h/4h/1d), simulate the LIVE target policy (arm A) from each
non-overlapping down-market entry, record gross%, year, symbol, score(float).
Bucket/threshold-sweep done downstream. Faithfully replicates the live engine.
Scope limit: engine scores only bearish/sideways (down-market); no 15m history.
"""
import os, sys, glob, math, csv
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from target_policy_bt import (load, indicators, score_array, regime_array,
                              simulate, TFS, TF_HOURS, MAX_SL, WARM)

CAND_MIN = 2.0   # collect from score>=2 so we can sweep 2..6 downstream
ROOT = "/home/tradmin/trading-signal-bot/research/skill_application"
DATA = f"{ROOT}/data/bt_data"

def collect(syms, out_path):
    f = open(out_path, "w", newline="")
    w = csv.writer(f); w.writerow(["symbol","tf","year","score","gross","reach_t1","reach_t2"])
    nsym = 0; ntr = 0
    for sym in syms:
        for tf in TFS:
            df = load(sym, tf)
            if df is None: continue
            try: df = indicators(df)
            except Exception: continue
            L = len(df)
            close=df['close'].to_numpy(); high=df['high'].to_numpy(); low=df['low'].to_numpy()
            e20=df['ema20'].to_numpy(); e50=df['ema50'].to_numpy(); e200=df['ema200'].to_numpy()
            atr=df['atr'].to_numpy(); avg=df['avg_atr'].to_numpy()
            years=pd.to_datetime(df['t'],unit='ms',errors='coerce').dt.year.to_numpy()
            reg=regime_array(close,e20,e50,e200,atr,avg)
            sc_bear=score_array(df,'bearish'); sc_side=score_array(df,'sideways')
            sc=np.where(reg=='bearish',sc_bear,np.where(reg=='sideways',sc_side,0.0))
            down=(reg=='bearish')|(reg=='sideways')
            cand=down&(sc>=CAND_MIN); cand[:WARM]=False; cand[L-1:]=False
            sup20=pd.Series(low).rolling(20).min().to_numpy()
            res20=pd.Series(high).rolling(20).max().to_numpy()
            idxs=np.nonzero(cand)[0]
            nxt=WARM
            for i in idxs:
                if i<nxt: continue
                entry=close[i]; a=atr[i]
                if entry<=0 or np.isnan(a): continue
                stop=max(entry-a*1.5, sup20[i]*0.99)
                if stop>=entry: stop=entry*0.97
                cap=MAX_SL.get(tf,0.04); mr=entry*cap
                if (entry-stop)>mr: stop=entry-mr
                if np.isnan(stop) or stop>=entry: continue
                risk=entry-stop
                t1=entry+risk; t2=entry+risk*1.8; t3=entry+risk*2.2
                if t1>res20[i]>entry: t1=res20[i]*0.99
                if not (t1>entry): continue
                t2=max(t2,t1+entry*0.001); t3=max(t3,t2+entry*0.001)
                r=simulate(high,low,close,i,entry,stop,t1,t2,t3,tf)
                if r is None: continue
                g,xi,r1,r2=r
                yr=int(years[i]) if not np.isnan(years[i]) else 0
                w.writerow([sym,tf,yr,round(float(sc[i]),4),round(g,4),r1,r2]); ntr+=1
                nxt=xi+1
        nsym+=1
        if nsym%50==0: print(f"  {nsym}/{len(syms)} syms  trades={ntr}",flush=True)
    f.close()
    print(f"DONE {nsym} syms  {ntr} trades -> {out_path}",flush=True)

if __name__=="__main__":
    limit=int(sys.argv[1]) if len(sys.argv)>1 else 0
    out=sys.argv[2] if len(sys.argv)>2 else f"{ROOT}/out/b1_oos_trades.csv"
    os.makedirs(f"{ROOT}/out",exist_ok=True)
    syms=sorted({os.path.basename(p) for p in glob.glob(f"{DATA}/*") if os.path.isdir(p)})
    syms=[s for s in syms if glob.glob(f"{DATA}/{s}/*/*.zip")]
    if limit: syms=syms[:limit]
    print(f"symbols={len(syms)} CAND_MIN={CAND_MIN}",flush=True)
    collect(syms,out)
