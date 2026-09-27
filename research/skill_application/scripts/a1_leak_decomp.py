import numpy as np, pandas as pd
from scipy import stats
pd.set_option('display.width', 200); pd.set_option('display.max_columns', 40)
np.random.seed(42)

df = pd.read_csv('/home/tradmin/trading-signal-bot/research/skill_application/scripts/a1_data.csv',
    header=None, names=['signal_id','symbol','tt','timeframe','score','market_condition',
    'usdtd_trend','profit_usdt','profit_percent','result','target_reached','stop_hit',
    'duration_hours','signal_time','exit_time','failure_reason'])
for c in ['profit_usdt','profit_percent','duration_hours']:
    df[c]=pd.to_numeric(df[c],errors='coerce')
df['score']=pd.to_numeric(df['score'],errors='coerce')
df['stop_hit']=df['stop_hit'].astype(int)
df['win']=(df['result']=='WIN').astype(int)
df['signal_time']=pd.to_datetime(df['signal_time'])
df['macro_state']=np.where(df['usdtd_trend']=='null','untagged','usdtd_'+df['usdtd_trend'])
df['tagged']=df['tt']!='null'
N=len(df)
print(f"N={N}  net_usdt_sum={df.profit_usdt.sum():.2f}  gross%mean={df.profit_percent.mean():.4f}")

# ---- fee model: implied notional ----
mask=df.profit_percent.abs()>0.01
df['ratio']=df.profit_usdt/(df.profit_percent/100.0)   # = notional if usdt is gross
print("\n== implied notional (usdt/ (gross%/100)) distribution ==")
print(df.loc[mask,'ratio'].describe(percentiles=[.05,.25,.5,.75,.95]).round(3))
# residual test: does usdt = 0.5*profit_percent exactly (=> $50 notional, GROSS, no fee)?
df['resid_nofee']=df.profit_usdt-0.5*df.profit_percent
print("\n== residual usdt - 0.5*gross%  (0 => $50 notional & NO fee) ==")
for label,sub in [('April(untagged)',df[~df.tagged]),('post(tagged)',df[df.tagged])]:
    print(f"{label:16s} n={len(sub):5d} resid mean={sub.resid_nofee.mean():.4f} median={sub.resid_nofee.median():.4f} std={sub.resid_nofee.std():.4f}")

# ---- consistent net % of fees (independent of usdt fee treatment) ----
def wins(x,lo=1,hi=99):
    x=np.asarray(x,float); a,b=np.nanpercentile(x,[lo,hi]); return np.clip(x,a,b)
df['g_w']=wins(df.profit_percent)             # winsorized gross %
df['net3']=df.profit_percent-0.30             # net % @0.3% round trip
df['net6']=df.profit_percent-0.60             # net % @0.6% pessimistic
df['net3_w']=wins(df.net3); df['net6_w']=wins(df.net6)

print("\n== overall expectancy (winsorized 1/99) ==")
print(f"gross% mean={df.g_w.mean():.4f}  net%@0.3 mean={df.net3_w.mean():.4f}  net%@0.6 mean={df.net6_w.mean():.4f}  WR={df.win.mean()*100:.1f}%")

# ---- fee vs adverse selection share of loss ----
gm=df.g_w.mean(); nm=df.net3_w.mean(); nm6=df.net6_w.mean()
print("\n== fee vs adverse-selection share of NET loss (% expectancy terms) ==")
print(f"@0.3: adverse(gross)={gm:.4f}  fee=-0.30  net={nm:.4f}  -> fee share={0.30/(-nm)*100:.1f}%  adverse share={(-gm)/(-nm)*100:.1f}%")
print(f"@0.6: net={nm6:.4f}  -> fee share={0.60/(-nm6)*100:.1f}%  adverse share={(-gm)/(-nm6)*100:.1f}%")
# dollar terms assuming $50 notional round-trip 0.3%
notional=50.0
gross_usd=(df.profit_percent/100*notional).sum()
fee_usd_03=N*notional*0.003; fee_usd_06=N*notional*0.006
print(f"\n== dollar terms ($50 notional) ==")
print(f"gross$ (adverse)={gross_usd:.2f}  fees@0.3={-fee_usd_03:.2f} -> net={gross_usd-fee_usd_03:.2f}  | fees@0.6={-fee_usd_06:.2f} -> net={gross_usd-fee_usd_06:.2f}")
print(f"actual recorded net_usdt sum={df.profit_usdt.sum():.2f}")

# ---- loss concentration ----
print("\n== loss concentration ==")
s=df.profit_usdt.sort_values()
for pct in [0.01,0.05,0.10]:
    k=int(N*pct); rem=df.profit_usdt.sort_values().iloc[k:].sum()  # remove k worst
    print(f"remove worst {pct*100:.0f}% (n={k}): net_usdt -> {rem:.2f}  (flips positive: {rem>0})")
# on net% @0.3
s2=df.net3.sort_values()
for pct in [0.05,0.10]:
    k=int(N*pct); rem=df.net3.sort_values().iloc[k:].mean()
    print(f"remove worst {pct*100:.0f}% net%@0.3 -> mean {rem:.4f}  (flips positive: {rem>0})")

# ---- symbol-clustered bootstrap helper ----
def clustered_boot(sub, col, reps=3000):
    syms=sub.symbol.values; vals=sub[col].values
    uniq=sub.symbol.unique()
    by={s:vals[syms==s] for s in uniq}
    means=np.empty(reps)
    for i in range(reps):
        pick=np.random.choice(uniq,size=len(uniq),replace=True)
        cat=np.concatenate([by[s] for s in pick])
        means[i]=cat.mean()
    return np.percentile(means,[2.5,97.5])

def remove_top_flip(sub,col):
    # for positive cell: remove biggest winners until mean<=0; return n removed & frac
    v=sub[col].sort_values(ascending=False).values
    base=v.mean()
    if base<=0: return None
    run=v.copy()
    for k in range(1,len(v)):
        if run[k:].mean()<=0: return k, k/len(v)
    return len(v), 1.0

# ---- CELL DECOMPOSITION ----
def decomp(dfx, keys, label, min_n=20, col='net3_w', gcol='g_w'):
    print(f"\n===== DECOMP: {label}  (col={col}) =====")
    rows=[]
    for kv,sub in dfx.groupby(keys):
        n=len(sub)
        if n<min_n: continue
        m=sub[col].mean(); gm=sub[gcol].mean(); wr=sub.win.mean()*100
        nsym=sub.symbol.nunique()
        lo,hi=clustered_boot(sub,col)
        t,p=stats.ttest_1samp(sub[col],0) if n>2 else (np.nan,np.nan)
        rows.append(dict(cell=str(kv),n=n,nsym=nsym,wr=round(wr,1),gross=round(gm,3),
            net=round(m,3),ci_lo=round(lo,3),ci_hi=round(hi,3),t=round(t,2),p=round(p,4),
            pos_ci=lo>0))
    r=pd.DataFrame(rows).sort_values('net',ascending=False)
    if len(r): print(r.to_string(index=False))
    return r

# full sample dims (all 3173): timeframe, score, market_condition
r_tf=decomp(df,['timeframe'],'ALL x timeframe',min_n=30)
r_sc=decomp(df,['score'],'ALL x score',min_n=30)
r_mc=decomp(df,['market_condition'],'ALL x market_condition',min_n=30)
# tagged-only dims (655): trade_type, macro_state
tg=df[df.tagged]
print(f"\n### tagged subset n={len(tg)} net_usdt={tg.profit_usdt.sum():.2f}")
r_tt=decomp(tg,['tt'],'TAGGED x trade_type',min_n=20)
r_ms=decomp(tg,['tt','macro_state'],'TAGGED x tt x macro_state',min_n=15)
r_ttf=decomp(tg,['tt','timeframe'],'TAGGED x tt x timeframe',min_n=15)

# candidate positive cells -> BH + remove-top-N
print("\n===== POSITIVE-CANDIDATE robustness (BH across all cells n>=min) =====")
allcells=pd.concat([r_tf,r_sc,r_mc,r_tt,r_ms,r_ttf],ignore_index=True)
allcells['p']=allcells['p'].fillna(1.0)
# BH
m=len(allcells); order=allcells['p'].argsort().values
ps=allcells['p'].values; ranked=np.sort(ps)
bh=ranked*m/np.arange(1,m+1)
bh_thresh=0.05
# find largest k with ranked[k]<=k/m*0.05
sig=np.zeros(m,bool)
for i in range(m-1,-1,-1):
    if ranked[i]<=(i+1)/m*bh_thresh:
        sig[np.argsort(ps)[:i+1]]=True; break
allcells['bh_sig']=sig
print(allcells[['cell','n','net','ci_lo','ci_hi','p','pos_ci','bh_sig']].to_string(index=False))

# detailed robustness on any cell with pos_ci
print("\n===== detailed on positive-CI cells =====")
for _,row in allcells[allcells.pos_ci].iterrows():
    print(f"  POS-CI: {row['cell']} n={row['n']} net={row['net']} CI=({row['ci_lo']},{row['ci_hi']}) bh_sig={row['bh_sig']}")
if not allcells.pos_ci.any():
    print("  NONE: no cell has symbol-clustered 95% CI excluding 0 on positive side")

# reversion deep dive (prior 'candidate')
rev=tg[tg.tt=='reversion']
print(f"\n== reversion deep dive: n={len(rev)} net_usdt={rev.profit_usdt.sum():.2f} net%@0.3 mean={rev.net3_w.mean():.4f} @0.6 mean={rev.net6_w.mean():.4f} WR={rev.win.mean()*100:.1f}%")
lo,hi=clustered_boot(rev,'net3_w'); print(f"   sym-clustered CI net%@0.3 = ({lo:.3f},{hi:.3f})")
lo6,hi6=clustered_boot(rev,'net6_w'); print(f"   sym-clustered CI net%@0.6 = ({lo6:.3f},{hi6:.3f})")
rt=remove_top_flip(rev,'net3_w'); print(f"   remove-top-N to flip (net%@0.3): {rt}")
# leave-one-month-out
rev=rev.copy(); rev['mon']=rev.signal_time.dt.to_period('M')
print("   leave-one-month-out net%@0.3 means:")
for mon in sorted(rev.mon.unique()):
    sub=rev[rev.mon!=mon]; print(f"     drop {mon}: mean={sub.net3_w.mean():.4f} n={len(sub)}")
print("   per-month:")
for mon in sorted(rev.mon.unique()):
    sub=rev[rev.mon==mon]; print(f"     {mon}: n={len(sub)} net%@0.3={sub.net3_w.mean():.4f} WR={sub.win.mean()*100:.0f}% net_usdt={sub.profit_usdt.sum():.2f}")
