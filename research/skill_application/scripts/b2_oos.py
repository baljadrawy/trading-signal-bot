#!/usr/bin/env python3
"""TASK B2 — Timeframe selection on HISTORICAL OOS engine (faithful bot replica, arm A = live policy).
Per-TF, per-year, per-symbol net expectancy. NO 15m history exists -> 1h/4h/1d only (focus 4h/1d).
Reuses load/indicators/score/simulate from target_policy_bt (faithful closed-candle replica)."""
import os, sys, glob, math, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from target_policy_bt import (load, indicators, regime_array, score_array, simulate,
                              DATA, WARM, MIN_SCORE, MAX_SL, TF_HOURS)

TFS = ['1h', '4h', '1d']          # engine has these; bot trades 4h/1d of them (+15m which has NO history)
FEES = {'gross': 0.0, 'net03': 0.3, 'net06': 0.6}

def process_symbol(sym):
    """Return list of trades: (tf, year, gross_pct, reach_t1) using arm-A live policy, non-overlapping."""
    trades = []
    for tf in TFS:
        df = load(sym, tf)
        if df is None: continue
        try: df = indicators(df)
        except Exception: continue
        L = len(df)
        close=df['close'].to_numpy(); high=df['high'].to_numpy(); low=df['low'].to_numpy()
        e20=df['ema20'].to_numpy(); e50=df['ema50'].to_numpy(); e200=df['ema200'].to_numpy()
        atr=df['atr'].to_numpy(); avg=df['avg_atr'].to_numpy()
        years=pd.to_datetime(df['t'], unit='ms', errors='coerce').dt.year.to_numpy()
        reg=regime_array(close,e20,e50,e200,atr,avg)
        sc_b=score_array(df,'bearish'); sc_s=score_array(df,'sideways')
        sc=np.where(reg=='bearish',sc_b,np.where(reg=='sideways',sc_s,0.0))
        down=(reg=='bearish')|(reg=='sideways')
        cand=down&(sc>=MIN_SCORE); cand[:WARM]=False; cand[L-1:]=False
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
            if not (t1>entry) or np.isnan(t1): continue
            t2=max(t2,t1+entry*0.001); t3=max(t3,t2+entry*0.001)
            r=simulate(high,low,close,i,entry,stop,t1,t2,t3,tf)
            if r is None: continue
            g,xi,r1,r2=r
            yr=int(years[i]) if not np.isnan(years[i]) else 0
            trades.append((tf,yr,g,r1)); nxt=xi+1
    return trades

def main():
    limit=int(sys.argv[1]) if len(sys.argv)>1 else 0
    syms=sorted({os.path.basename(p) for p in glob.glob(f"{DATA}/*") if os.path.isdir(p)})
    syms=[s for s in syms if glob.glob(f"{DATA}/{s}/*/*.zip")]
    if limit: syms=syms[:limit]
    print(f"symbols: {len(syms)}  TFS={TFS}  MIN_SCORE={MIN_SCORE}", flush=True)
    rows=[]
    for k,sym in enumerate(syms):
        for tf,yr,g,r1 in process_symbol(sym):
            rows.append((sym,tf,yr,g,r1))
        if (k+1)%50==0: print(f"  {k+1}/{len(syms)}  rows={len(rows)}", flush=True)
    out=pd.DataFrame(rows, columns=['symbol','tf','year','gross','reach_t1'])
    path="/home/tradmin/trading-signal-bot/research/skill_application/scripts/b2_oos_trades.csv"
    out.to_csv(path, index=False)
    print(f"WROTE {path}  ({len(out)} trades)", flush=True)

if __name__=="__main__":
    main()
