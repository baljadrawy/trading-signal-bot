import numpy as np, pandas as pd
from scipy import stats
cols=['signal_id','symbol','result','gross_pct','net_usdt','target_reached','stop_hit',
      'duration_hours','failure_reason','exit_time','timeframe','trade_type','market_condition','score']
df=pd.read_csv('/home/tradmin/trading-signal-bot/research/skill_application/scripts/a3_trades.csv',
               header=None,names=cols)
df['stop_hit']=df['stop_hit'].map({'t':True,'f':False})
df['exit_time']=pd.to_datetime(df['exit_time'])
for c in ['gross_pct','net_usdt','target_reached','duration_hours','score']:
    df[c]=pd.to_numeric(df[c],errors='coerce')
df['iswin']=(df['result']=='WIN')
NOTIONAL=50.0

def winsor(x,lo=1,hi=99):
    x=np.asarray(x,float); a,b=np.nanpercentile(x,[lo,hi]); return np.clip(x,a,b)
def pf(x):
    x=np.asarray(x,float); p=x[x>0].sum(); n=-x[x<0].sum(); return p/n if n>0 else np.inf

def block(sub,label):
    n=len(sub)
    g=sub['gross_pct'].values                      # gross %
    net03=g-0.3                                     # net % @0.3% round trip
    net06=g-0.6                                     # net % @0.6% round trip
    gw=winsor(g); n3w=winsor(net03); n6w=winsor(net06)
    wr=sub['iswin'].mean()
    t1=(sub['target_reached']>=1).mean()
    sh=sub['stop_hit'].mean()
    # $ sums on $50 notional
    gross_usd=g/100*NOTIONAL
    fee_usd_03=n*0.003*NOTIONAL   # 0.3% of 50 = 0.15/trade
    fee_usd_06=n*0.006*NOTIONAL
    net_usd_03=gross_usd.sum()-fee_usd_03
    net_usd_06=gross_usd.sum()-fee_usd_06
    # asymmetry on GROSS winsorized
    wins=gw[gw>0]; loss=gw[gw<0]
    mw=wins.mean() if len(wins) else np.nan
    ml=loss.mean() if len(loss) else np.nan
    # tails (raw, not winsorized) to see if losses run
    print(f"\n===== {label}  n={n} =====")
    print(f" WR={wr:.3f}  T1_touch(tr>=1)={t1:.3f}  stop_hit={sh:.3f}")
    print(f" PF_gross={pf(g):.3f}  PF_net@0.3%={pf(net03):.3f}  PF_net@0.6%={pf(net06):.3f}")
    print(f" $ gross_sum={gross_usd.sum():.2f}  fee@0.3%={fee_usd_03:.2f}  net@0.3%={net_usd_03:.2f}  net@0.6%={net_usd_06:.2f}")
    fs03=fee_usd_03/abs(gross_usd.sum())*100 if gross_usd.sum()!=0 else float('nan')
    print(f" fee_drag_share_of_|gross|@0.3%={fs03:.1f}%   (fee $/trade=0.15@0.3, 0.30@0.6)")
    print(f" GROSS win_mean={mw:.3f}% loss_mean={ml:.3f}%  |win/loss|={abs(mw/ml):.3f}")
    print(f" RAW tails: max_win={g.max():.2f}%  min_loss={g.min():.2f}%  p95={np.percentile(g,95):.2f}  p5={np.percentile(g,5):.2f}")
    # mean net per trade + clustered-ish t (winsorized)
    t3=stats.ttest_1samp(n3w,0)
    print(f" net%@0.3 winsor mean/trade={n3w.mean():.4f}%  t={t3.statistic:.2f} p={t3.pvalue:.4g}")
    print(f" target_reached dist={sub['target_reached'].value_counts().sort_index().to_dict()}")
    # reconcile: of trades that touched T1, how many still LOSS?
    touched=sub[sub['target_reached']>=1]
    if len(touched):
        print(f" of T1-touchers (n={len(touched)}): WIN={touched['iswin'].mean():.3f} stop_hit_after={touched['stop_hit'].mean():.3f}")
    return dict(label=label,n=n,wr=wr,t1=t1,sh=sh,pfg=pf(g),pfn3=pf(net03),
                gross=gross_usd.sum(),net03=net_usd_03,mw=mw,ml=ml,maxwin=g.max(),minloss=g.min())

fix=pd.Timestamp('2026-07-19')
R=[]
R.append(block(df,"FULL HISTORY"))
R.append(block(df[df['exit_time']>=fix],"POST-FIX >=07-19"))
R.append(block(df[df['exit_time']<fix],"PRE-FIX <07-19"))

# symbol-clustered bootstrap on net%@0.3 mean for full + post
def clustered_boot(sub,fee=0.3,reps=3000,seed=1):
    rng=np.random.default_rng(seed)
    syms=sub['symbol'].unique()
    by={s:(sub.loc[sub['symbol']==s,'gross_pct'].values-fee) for s in syms}
    means=[]
    for _ in range(reps):
        pick=rng.choice(syms,size=len(syms),replace=True)
        vals=np.concatenate([by[s] for s in pick])
        vals=winsor(vals)
        means.append(vals.mean())
    lo,hi=np.percentile(means,[2.5,97.5])
    return lo,hi
lo,hi=clustered_boot(df)
print(f"\n[FULL] symbol-clustered 95% CI net%@0.3 mean/trade: [{lo:.4f}, {hi:.4f}]")
loP,hiP=clustered_boot(df[df['exit_time']>=fix])
print(f"[POST] symbol-clustered 95% CI net%@0.3 mean/trade: [{loP:.4f}, {hiP:.4f}]  (n_syms={df[df['exit_time']>=fix]['symbol'].nunique()})")

# entry-quality vs exit-quality decomposition:
# ENTRY health = gross PF. If gross PF<1, entry is the leak (setups have neg gross expectancy).
# EXIT/geometry effect: compare gross win/loss magnitude & T1 reach.
print("\n=== ENTRY vs EXIT SUMMARY ===")
for r in R:
    verdict = "GROSS-NEG (entry leak)" if r['pfg']<1 else "gross-positive"
    print(f"{r['label']:20s} PF_gross={r['pfg']:.3f} [{verdict}]  PF_net0.3={r['pfn3']:.3f}  net$@0.3={r['net03']:.2f}  win/loss_mag={abs(r['mw']/r['ml']):.2f}")
