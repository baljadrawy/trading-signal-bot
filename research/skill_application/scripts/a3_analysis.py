import numpy as np, pandas as pd
from scipy import stats

cols=['signal_id','symbol','result','gross_pct','net_usdt','target_reached','stop_hit',
      'duration_hours','failure_reason','exit_time','timeframe','trade_type','market_condition','score']
df=pd.read_csv('/home/tradmin/trading-signal-bot/research/skill_application/scripts/a3_trades.csv',
               header=None,names=cols)
# coerce booleans (postgres t/f)
df['stop_hit']=df['stop_hit'].map({'t':True,'f':False})
df['exit_time']=pd.to_datetime(df['exit_time'])
for c in ['gross_pct','net_usdt','target_reached','duration_hours','score']:
    df[c]=pd.to_numeric(df[c],errors='coerce')

print("=== BASIC ===")
print("n total:",len(df))
print("timeframes:",df['timeframe'].value_counts().to_dict())
print("trade_type:",df['trade_type'].value_counts(dropna=False).to_dict())
print("exit_time range:",df['exit_time'].min(),"->",df['exit_time'].max())

# infer position size from gross_pct vs net_usdt
# net_usdt is NET dollars; gross_pct is gross %. position ~ net_usdt/(gross_pct/100) roughly
df['implied_pos']=df['net_usdt']/(df['gross_pct']/100)
print("\nimplied position size (net_usdt / gross_frac) describe:")
print(df['implied_pos'].describe())

def winsorize(x,lo=1,hi=99):
    x=np.asarray(x,dtype=float)
    a,b=np.nanpercentile(x,[lo,hi])
    return np.clip(x,a,b)

def pf(gross_or_net):
    x=np.asarray(gross_or_net,dtype=float)
    pos=x[x>0].sum(); neg=-x[x<0].sum()
    return pos/neg if neg>0 else np.inf

def report(sub,label):
    n=len(sub)
    if n==0:
        print(f"\n--- {label}: EMPTY ---");return
    gross=sub['gross_pct'].values
    net_usdt=sub['net_usdt'].values
    # net % : reconstruct using implied position. But cleaner: gross PF from gross_pct, net PF from net_usdt
    pf_gross=pf(gross)
    pf_net=pf(net_usdt)
    # fee share of gross: total gross $ vs total net $. Need gross in $. Use per-trade implied pos.
    gross_usdt=sub['gross_pct'].values/100*sub['implied_pos'].values
    tot_gross=gross_usdt.sum()
    tot_net=net_usdt.sum()
    fees=tot_gross-tot_net  # positive = fees drag
    # T1 touch
    t1=(sub['target_reached']>=1).mean()
    sh=sub['stop_hit'].mean()
    wr=(sub['result']=='WIN').mean()
    # magnitude asymmetry on gross_pct winsorized
    gw=winsorize(gross)
    wins=gw[gw>0]; loss=gw[gw<0]
    mean_win=wins.mean() if len(wins) else np.nan
    mean_loss=loss.mean() if len(loss) else np.nan
    # net winsorized mean
    netw=winsorize(net_usdt)
    mean_net=netw.mean()
    t=stats.ttest_1samp(netw,0) if n>1 else (np.nan,np.nan)
    print(f"\n--- {label} (n={n}) ---")
    print(f"  WR={wr:.3f}  T1_touch(target>=1)={t1:.3f}  stop_hit={sh:.3f}")
    print(f"  PF_gross={pf_gross:.3f}  PF_net={pf_net:.3f}")
    print(f"  tot_gross=${tot_gross:.2f}  tot_net=${tot_net:.2f}  fee_drag=${fees:.2f}  fee_share_of_gross={fees/abs(tot_gross)*100 if tot_gross!=0 else float('nan'):.1f}% (rel |gross|)")
    print(f"  gross win mean={mean_win:.3f}%  gross loss mean={mean_loss:.3f}%  |win/loss|={abs(mean_win/mean_loss):.3f}")
    print(f"  net_usdt winsor mean/trade=${mean_net:.4f}  t={t[0]:.3f} p={t[1]:.4g}")
    print(f"  net_usdt SUM (raw)=${net_usdt.sum():.2f}   per-trade raw mean=${net_usdt.mean():.4f}")
    # target_reached distribution
    print(f"  target_reached dist: {sub['target_reached'].value_counts().sort_index().to_dict()}")

report(df,"FULL HISTORY")

# cohort split at fix deploy 2026-07-19
fix=pd.Timestamp('2026-07-19')
report(df[df['exit_time']>=fix],"POST-FIX (>=2026-07-19, last ~9-10d)")
report(df[df['exit_time']<fix],"PRE-FIX (<2026-07-19)")

# also last 9 days strictly
last9=pd.Timestamp('2026-07-29')-pd.Timedelta(days=9)
report(df[df['exit_time']>=last9],"LAST 9 DAYS (>=2026-07-20)")
