#!/usr/bin/env python3
"""FC steel-man variants (fair test of the MECHANISM, not the churny pre-registered gate).
  V1 ALWAYS-ON: hold every contiguous period (near-zero churn; ~1 spell/symbol). This is what the
     rough +8.8% assumed. Pays funding during backwardation. True basis+liq included.
  V2 SMOOTHED GATE: hold iff trailing 9-period (3-day) mean funding (shifted, no look-ahead) > 0.
     Natural hysteresis cuts churn vs the strict single-lag gate. Exploratory, NOT pre-registered.
Reports net annual on CAPITAL (committed) at 0.3/0.4/0.6%, L=2,3; liq freq & worst tail;
symbol-clustered bootstrap; per-year; 6-mo stability."""
import numpy as np, pandas as pd

ROOT = "/home/tradmin/trading-signal-bot/research/skill_application"
df = pd.read_csv(f"{ROOT}/scripts/fc_periods.csv").sort_values(['sym','period']).reset_index(drop=True)
PPY=1095; MAINT=0.005; COSTS=[0.003,0.004,0.006]; LS=[2,3]
N_DEC=len(df); YEARS=N_DEC/PPY

# smoothed-gate signal (no look-ahead): trailing mean of PRIOR rates
df['roll9']=df.groupby('sym')['rate'].transform(lambda s: s.shift(1).rolling(9,min_periods=3).mean())
df['hold_always']=True
df['hold_smooth']=df['roll9']>0

def thr(L): return 1.0/L-MAINT
def winsor(x,lo=0.01,hi=0.99):
    a,b=np.quantile(x,[lo,hi]); return np.clip(x,a,b)

def run(hold_col, model, L):
    t=thr(L); out=[]
    for sym,g in df.groupby('sym',sort=False):
        g=g.reset_index(drop=True)
        hold=g[hold_col].fillna(False).values; period=g['period'].values
        gross=g['gross_pnl'].values; priseR=g['perp_rise_R'].values
        Ph=g['P_high'].values; Pp=g['P_prev'].values; Sp=g['S_prev'].values
        Sat=g['S_at_ph'].values; scR=g['spot_conc'].values
        yr=g['year'].values; ym=g['ym'].values
        sid=-1; ins=False; eP=np.nan; eS=np.nan; prev=None
        for i in range(len(g)):
            if not hold[i]: ins=False; prev=period[i]; continue
            new=(not ins) or (prev is not None and period[i]-prev!=1)
            if new: sid+=1; ins=True; eP=Pp[i]; eS=Sp[i]
            if model=='R': rise=priseR[i]; soff=scR[i]
            else: rise=Ph[i]/eP-1; soff=Sat[i]/eS-1
            if rise>=t:
                out.append((sym,yr[i],ym[i],soff-t,1,sid,1)); ins=False
            else:
                out.append((sym,yr[i],ym[i],gross[i],0,sid,0))
            prev=period[i]
    return pd.DataFrame(out,columns=['sym','year','ym','pnl','is_liq','spell_id','rehedge']),t

def stats(hold_col,label):
    print("\n"+"="*96); print(f"VARIANT: {label}"); print("="*96)
    for L in LS:
        hR,t=run(hold_col,'R',L); hP,_=run(hold_col,'P',L)
        cap=1+1/L; nheld=len(hR)
        nsp=hR.groupby(['sym','spell_id']).ngroups
        # liq
        for tag,h in [('R',hR),('P',hP)]:
            nl=int(h['is_liq'].sum())
            if nl:
                worst=h[h['is_liq']==1]['pnl'].min()
                print(f"  L={L} LIQ[{tag}]: {nl}/{nheld} ({nl/nheld*100:.3f}%) worst={worst*100:+.2f}% notional = {worst/cap*100:+.2f}% cap")
            else:
                print(f"  L={L} LIQ[{tag}]: 0 events")
        print(f"  L={L} spells={nsp} (frac_held={nheld/N_DEC*100:.0f}%)  net annual on CAPITAL (committed, winsor):")
        for cost in COSTS:
            fee=(nsp+int(hR['rehedge'].sum()))*cost/nheld
            net=winsor(hR['pnl'].values-fee)
            net_cap_comm=net.sum()/N_DEC/cap*PPY*100
            net_cap_dep=net.mean()/cap*PPY*100
            gross_cap_dep=winsor(hR['pnl'].values).mean()/cap*PPY*100
            print(f"     cost {cost*100:.1f}%: gross(cap,dep)={gross_cap_dep:+.2f}%  NET(cap,committed)={net_cap_comm:+.2f}%  net(cap,dep)={net_cap_dep:+.2f}%")
        # robustness at 0.6% (base)
        cost=0.006; fee=(nsp+int(hR['rehedge'].sum()))*cost/nheld
        hh=hR.copy(); hh['net']=hh['pnl']-fee
        dec=df.groupby('sym').size()
        sym_ann={s:(winsor(gg['net'].values).sum()/dec[s])/cap*PPY*100 for s,gg in hh.groupby('sym')}
        arr=np.array(list(sym_ann.values())); rng=np.random.default_rng(7)
        boots=[np.mean(rng.choice(arr,size=len(arr),replace=True)) for _ in range(3000)]
        lo,hi=np.percentile(boots,[2.5,97.5])
        print(f"  L={L} @0.6%: sym-mean net={arr.mean():+.2f}% 95%CI=[{lo:+.2f},{hi:+.2f}]")
        yrp=[]
        for y,gg in hh.groupby('year'):
            decy=df[df['year']==y].shape[0]
            yrp.append((y,(winsor(gg['net'].values).sum()/decy)/cap*PPY*100,(gg['is_liq']==1).sum()))
        print("        per-year net%: "+"  ".join(f"{y}:{v:+.1f}(liq{lq})" for y,v,lq in yrp))
        npos=sum(1 for _,v,_ in yrp if v>0)
        mser=pd.Series({m:winsor(gg['net'].values).sum()/df[df['ym']==m].shape[0]/cap*PPY*100 for m,gg in hh.groupby('ym') if len(gg)>5}).sort_index()
        vals=mser.values; ok6=[ (vals[i:i+6]>0).sum()>=4 for i in range(len(vals)-5)]
        print(f"        years pos={npos}/{len(yrp)}  monthly pos share={(mser>0).mean()*100:.0f}%  6mo-windows>=4pos={np.mean(ok6)*100 if ok6 else 0:.0f}%")

print("="*96)
print(f"STEEL-MAN variants | {df['sym'].nunique()} syms | {N_DEC} periods | {YEARS:.1f} yr")
print(f"[ref] gross funding on NOTIONAL always-on = {df['rate'].mean()*PPY*100:.2f}%/yr (matches ~8.8% rough)")
print("="*96)
stats('hold_always','V1 ALWAYS-ON (no gate, hold every period — steel-man of the mechanism)')
stats('hold_smooth','V2 SMOOTHED GATE (trailing-9 mean funding>0, no look-ahead — exploratory)')
