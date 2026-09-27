#!/usr/bin/env python3
"""B4 HIST point-in-time macro test — regenerate reversion signals recording BOTH:
  macro_orig = BTC daily state of signal's own floor-day (same as b4_hist_macro.py; look-ahead for intraday)
  macro_pit  = BTC daily state of the LAST daily candle CLOSED at/before the signal candle's close (no look-ahead)
If falling-state edge is a look-ahead artifact, macro_pit will collapse it.
Universe cap = top-80 symbols by 1d-file count (STATED)."""
import os, sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/home/tradmin/trading-signal-bot/research/skill_application/scripts')
from target_policy_bt import (load, indicators, regime_array, score_array, simulate,
                              TFS, TF_HOURS, MAX_SL, WARM, MIN_SCORE)
np.random.seed(7)
DATA="/home/tradmin/trading-signal-bot/research/skill_application/data/bt_data"
DAY_MS=86400000

btc=load("BTCUSDT","1d"); btc=indicators(btc)
btc_t=btc['t'].to_numpy()                 # open time ms
btc_t=np.where(btc_t>1e14,btc_t//1000,btc_t)
btc_close_ms=btc_t+DAY_MS                  # candle close time
ret3=(btc['close'].pct_change(3)*100).to_numpy()
def state(r): return np.where(np.isnan(r),None,np.where(r>3.0,'falling',np.where(r<-3.0,'rising','flat')))
btc_state=np.array([None if np.isnan(x) else ('falling' if x>3 else ('rising' if x<-3 else 'flat')) for x in ret3],dtype=object)
btc_day=(pd.to_datetime(btc_t,unit='ms').floor('D'))
DAY2MACRO=dict(zip(btc_day,btc_state))    # for orig
print("BTC daily state dist:",pd.Series(btc_state).value_counts().to_dict())

TF_MS={'1h':3600000,'4h':14400000,'1d':DAY_MS}
CAP=80
cands=[]
for d in sorted(os.listdir(DATA)):
    if glob.glob(f"{DATA}/{d}/1d/*.zip"): cands.append((d,len(glob.glob(f"{DATA}/{d}/1d/*.zip"))))
cands.sort(key=lambda x:-x[1]); SYMS=[s for s,_ in cands[:CAP]]
print(f"UNIVERSE CAP top {CAP}; using {len(SYMS)}")

rows=[]
for si,sym in enumerate(SYMS):
    for tf in TFS:
        df=load(sym,tf)
        if df is None: continue
        try: df=indicators(df)
        except Exception: continue
        L=len(df)
        close=df['close'].to_numpy();high=df['high'].to_numpy();low=df['low'].to_numpy()
        e20=df['ema20'].to_numpy();e50=df['ema50'].to_numpy();e200=df['ema200'].to_numpy()
        atr=df['atr'].to_numpy();avg=df['avg_atr'].to_numpy()
        t=df['t'].to_numpy(); t=np.where(t>1e14,t//1000,t)
        close_ms=t+TF_MS[tf]
        ts=pd.to_datetime(t,unit='ms',errors='coerce')
        years=ts.year.to_numpy(); days=ts.floor('D')
        reg=regime_array(close,e20,e50,e200,atr,avg)
        sc_b=score_array(df,'bearish');sc_s=score_array(df,'sideways')
        sc=np.where(reg=='bearish',sc_b,np.where(reg=='sideways',sc_s,0.0))
        down=(reg=='bearish')|(reg=='sideways')
        cand=down&(sc>=MIN_SCORE);cand[:WARM]=False;cand[L-1:]=False
        sup20=pd.Series(low).rolling(20).min().to_numpy();res20=pd.Series(high).rolling(20).max().to_numpy()
        # point-in-time BTC daily index for each signal candle close time
        pit_idx=np.searchsorted(btc_close_ms,close_ms,side='right')-1
        idxs=np.nonzero(cand)[0];nxt=WARM
        for i in idxs:
            if i<nxt: continue
            entry=close[i];a=atr[i]
            stop=max(entry-a*1.5,sup20[i]*0.99)
            if stop>=entry: stop=entry*0.97
            cap=MAX_SL.get(tf,0.04)
            if (entry-stop)>entry*cap: stop=entry-entry*cap
            if entry<=0 or np.isnan(stop) or stop>=entry: continue
            risk=entry-stop;t1=entry+risk;t2=entry+risk*1.8;t3=entry+risk*2.2
            if t1>res20[i]>entry: t1=res20[i]*0.99
            if not (t1>entry): continue
            t2=max(t2,t1+entry*0.001);t3=max(t3,t2+entry*0.001)
            r=simulate(high,low,close,i,entry,stop,t1,t2,t3,tf)
            if r is None: continue
            g,xi,r1,r2=r;nxt=xi+1
            yr=int(years[i]) if not np.isnan(years[i]) else 0
            mo=DAY2MACRO.get(days[i])
            pj=pit_idx[i]; mp=btc_state[pj] if pj>=0 else None
            rows.append((sym,tf,yr,mo,mp,g))
    if (si+1)%20==0: print(f"  {si+1}/{len(SYMS)}",flush=True)

R=pd.DataFrame(rows,columns=['sym','tf','year','macro_orig','macro_pit','gross'])
R.to_csv('/home/tradmin/trading-signal-bot/research/skill_application/scripts/b4_hist_pit_rows.csv',index=False)
print(f"\nTOTAL={len(R)} saved b4_hist_pit_rows.csv")
lo,hi=np.percentile(R.gross,[1,99]);R['gw']=R.gross.clip(lo,hi)
FEE=0.3;FEE6=0.6
def cboot(sub,fee,reps=3000):
    syms=sub.sym.unique();grp={s:sub[sub.sym==s].gw.values for s in syms};m=np.empty(reps)
    for k in range(reps):
        pk=np.random.choice(syms,len(syms),True);m[k]=np.concatenate([grp[s] for s in pk]).mean()-fee
    return np.percentile(m,[2.5,97.5]),(m>0).mean()
for lbl,col in [('ORIG (same-day, look-ahead for intraday)','macro_orig'),('PIT (last closed daily, no look-ahead)','macro_pit')]:
    print(f"\n=== {lbl} ===")
    print(f"{'state':8s}{'n':>7}{'gross':>8}{'net03':>8}{'net06':>8}   CI95(net03)     P>0")
    for mc in ['falling','flat','rising']:
        s=R[R[col]==mc]
        if len(s)==0: continue
        g=s.gw.mean();ci,p=cboot(s,FEE)
        print(f"{mc:8s}{len(s):>7}{g:>+8.3f}{g-FEE:>+8.3f}{g-FEE6:>+8.3f}   [{ci[0]:+.3f},{ci[1]:+.3f}] {p:.3f}")
    gf=R[R[col]=='falling'].gw.mean();gr=R[R[col]=='rising'].gw.mean()
    print(f"  falling>rising? {gf>gr}  (fall={gf:+.3f} rise={gr:+.3f})")
# per-tf breakdown of the falling edge under both
print("\n=== falling-state net03 by timeframe (orig vs pit) ===")
for tf in ['1h','4h','1d']:
    for col in ['macro_orig','macro_pit']:
        s=R[(R.tf==tf)&(R[col]=='falling')]
        if len(s): print(f"  {tf:3s} {col:11s}: n={len(s):>6} net03={s.gw.mean()-FEE:+.3f}")
