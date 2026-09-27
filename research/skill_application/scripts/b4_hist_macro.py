#!/usr/bin/env python3
"""B4 historical OOS: does the reversion signal's post-fee expectancy depend on
macro state (proxy USDT.D via BTC 3d trend), and is any ordering stable across years?
Universe cap STATED below. Symbol-clustered CI + leave-one-year-out."""
import os, sys, glob, math
import numpy as np, pandas as pd
sys.path.insert(0, '/home/tradmin/trading-signal-bot/research/skill_application/scripts')
from target_policy_bt import (load, indicators, regime_array, score_array, simulate,
                              TFS, TF_HOURS, MAX_SL, WARM, MIN_SCORE)
np.random.seed(7)

DATA = "/home/tradmin/trading-signal-bot/research/skill_application/data/bt_data"
FEE = 0.3; FEE6 = 0.6

# ---- macro proxy from BTC 1d: usdtd falling(risk-on)/rising(risk-off)/flat ----
btc = load("BTCUSDT", "1d")
btc = indicators(btc)
btc['day'] = pd.to_datetime(btc['t'], unit='ms').dt.floor('D')
btc['ret3'] = btc['close'].pct_change(3) * 100
# threshold ~ +/-3% over 3d (mirrors usdtd_3d_delta magnitude on risk assets)
def mstate(r):
    if np.isnan(r): return None
    if r > 3.0:  return 'falling'   # BTC up -> USDT.D falling (risk-on)
    if r < -3.0: return 'rising'    # BTC down -> USDT.D rising (risk-off)
    return 'flat'
btc['macro'] = btc['ret3'].apply(mstate)
DAY2MACRO = dict(zip(btc['day'], btc['macro']))
print("macro proxy dist (BTC days):", btc['macro'].value_counts().to_dict())

# ---- universe cap: top-N symbols by 1d history length (STATED) ----
CAP = 80
cands = []
for d in sorted(os.listdir(DATA)):
    zs = glob.glob(f"{DATA}/{d}/1d/*.zip")
    if zs: cands.append((d, len(zs)))
cands.sort(key=lambda x: -x[1])
SYMS = [s for s, _ in cands[:CAP]]
print(f"UNIVERSE CAP = top {CAP} symbols by 1d-file count; using {len(SYMS)} symbols")

rows = []  # (sym, tf, year, macro, gross)
for si, sym in enumerate(SYMS):
    for tf in TFS:
        df = load(sym, tf)
        if df is None: continue
        try: df = indicators(df)
        except Exception: continue
        L = len(df)
        close=df['close'].to_numpy(); high=df['high'].to_numpy(); low=df['low'].to_numpy()
        e20=df['ema20'].to_numpy(); e50=df['ema50'].to_numpy(); e200=df['ema200'].to_numpy()
        atr=df['atr'].to_numpy(); avg=df['avg_atr'].to_numpy()
        ts = pd.to_datetime(df['t'], unit='ms', errors='coerce')
        years = ts.dt.year.to_numpy(); days = ts.dt.floor('D')
        reg = regime_array(close,e20,e50,e200,atr,avg)
        sc_b=score_array(df,'bearish'); sc_s=score_array(df,'sideways')
        sc=np.where(reg=='bearish',sc_b,np.where(reg=='sideways',sc_s,0.0))
        down=(reg=='bearish')|(reg=='sideways')
        cand=down&(sc>=MIN_SCORE); cand[:WARM]=False; cand[L-1:]=False
        sup20=pd.Series(low).rolling(20).min().to_numpy(); res20=pd.Series(high).rolling(20).max().to_numpy()
        idxs=np.nonzero(cand)[0]; nxt=WARM
        for i in idxs:
            if i<nxt: continue
            entry=close[i]; a=atr[i]
            stop=max(entry-a*1.5, sup20[i]*0.99)
            if stop>=entry: stop=entry*0.97
            cap=MAX_SL.get(tf,0.04)
            if (entry-stop)>entry*cap: stop=entry-entry*cap
            if entry<=0 or np.isnan(stop) or stop>=entry: continue
            risk=entry-stop; t1=entry+risk; t2=entry+risk*1.8; t3=entry+risk*2.2
            if t1>res20[i]>entry: t1=res20[i]*0.99
            if not (t1>entry): continue
            t2=max(t2,t1+entry*0.001); t3=max(t3,t2+entry*0.001)
            r=simulate(high,low,close,i,entry,stop,t1,t2,t3,tf)
            if r is None: continue
            g,xi,r1,r2=r; nxt=xi+1
            yr=int(years[i]) if not np.isnan(years[i]) else 0
            mc=DAY2MACRO.get(days.iloc[i])
            if mc is None: continue
            rows.append((sym,tf,yr,mc,g))
    if (si+1)%20==0: print(f"  {si+1}/{len(SYMS)}",flush=True)

R=pd.DataFrame(rows,columns=['sym','tf','year','macro','gross'])
print(f"\nTOTAL reversion signals: {len(R)}  symbols={R.sym.nunique()}  years={sorted(R.year.unique())}")
# winsorize 1/99
lo,hi=np.percentile(R.gross,[1,99]); R['gw']=R.gross.clip(lo,hi)
print(f"winsor bounds [{lo:.2f},{hi:.2f}]")

def cboot(sub,fee=FEE,reps=2000):
    syms=sub.sym.unique(); grp={s:sub[sub.sym==s].gw.values for s in syms}
    m=[]
    for _ in range(reps):
        pk=np.random.choice(syms,len(syms),True)
        v=np.concatenate([grp[s] for s in pk]); m.append(v.mean()-fee)
    return np.percentile(m,[2.5,97.5])

print("\n=== Per macro-state: net expectancy after fees + symbol-clustered CI (ALL years) ===")
for mc in ['falling','flat','rising']:
    sub=R[R.macro==mc]
    g=sub.gw.mean(); ci=cboot(sub)
    print(f"{mc:8s} n={len(sub):6d} syms={sub.sym.nunique():3d} gross={g:+.3f} net03={g-FEE:+.3f} net06={g-FEE6:+.3f} CI95(net03)=[{ci[0]:+.3f},{ci[1]:+.3f}]")

print("\n=== ALIGNMENT ordering claim: does falling(risk-on) beat rising(risk-off) EACH year? (net03) ===")
print(f"{'year':>6} | {'fall_n':>7} {'fall':>8} | {'flat_n':>7} {'flat':>8} | {'rise_n':>7} {'rise':>8} | fall>rise?")
loyo=[]
for y in sorted(R.year.unique()):
    Ry=R[R.year==y]; line=[]
    vals={}
    for mc in ['falling','flat','rising']:
        s=Ry[Ry.macro==mc]; vals[mc]=(len(s), s.gw.mean()-FEE if len(s) else float('nan'))
    fw = vals['falling'][1]>vals['rising'][1] if (vals['falling'][0]>0 and vals['rising'][0]>0) else None
    loyo.append(fw)
    print(f"{y:>6} | {vals['falling'][0]:>7} {vals['falling'][1]:>+8.3f} | {vals['flat'][0]:>7} {vals['flat'][1]:>+8.3f} | {vals['rising'][0]:>7} {vals['rising'][1]:>+8.3f} | {fw}")

print("\n=== Leave-one-year-out: is ANY macro-state net-positive after fees when a year is dropped? ===")
allyears=sorted(R.year.unique())
for mc in ['falling','flat','rising']:
    print(f" state={mc}:")
    for y in allyears:
        sub=R[(R.macro==mc)&(R.year!=y)]
        if len(sub)<30: continue
        g=sub.gw.mean()-FEE
        print(f"   drop {y}: n={len(sub):6d} net03={g:+.3f}")

# best state remove-top-N
best=max(['falling','flat','rising'], key=lambda m:R[R.macro==m].gw.mean())
print(f"\n=== REMOVE-TOP-N on best gross state ({best}) ===")
bs=R[R.macro==best].sort_values('gw',ascending=False)
for n in [0,5,10,20,50]:
    t=bs.iloc[n:]; print(f"remove top {n:3d}: n={len(t):6d} gross={t.gw.mean():+.3f} net03={t.gw.mean()-FEE:+.3f}")
R.to_csv('/home/tradmin/trading-signal-bot/research/skill_application/scripts/b4_hist_rows.csv',index=False)
print("saved b4_hist_rows.csv")
