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

# Assume $50 nominal. gross_usdt from gross_pct. fee_gap = gross_usdt - net_usdt
df['gross_usdt50']=df['gross_pct']/100*50
df['fee_gap']=df['gross_usdt50']-df['net_usdt']   # >0 means net penalized vs gross
fix=pd.Timestamp('2026-07-19')
df['cohort']=np.where(df['exit_time']>=fix,'POST','PRE')

print("=== FEE GAP (gross_usdt@$50 - net_usdt) ===")
print("Overall fee_gap describe ($/trade):")
print(df['fee_gap'].describe())
print("\nfee_gap by cohort:")
print(df.groupby('cohort')['fee_gap'].agg(['count','mean','median','std','min','max']))
print("\nfee_gap by win/loss (full):")
print(df.groupby('iswin')['fee_gap'].agg(['count','mean','median','min','max']))
print("\nfee_gap by cohort x win:")
print(df.groupby(['cohort','iswin'])['fee_gap'].agg(['count','mean','median']))

# what fraction of trades have essentially-zero fee gap (<$0.001)?
print("\nfrac |fee_gap|<0.001 :",(df['fee_gap'].abs()<0.001).mean())
print("frac fee_gap between 0.09 and 0.16 (~0.2-0.3% of $50):",((df['fee_gap']>0.09)&(df['fee_gap']<0.16)).mean())

# Establish whether net_usdt == round(gross_pct/2,4) exactly (i.e. NO fees)
df['pred_no_fee']=(df['gross_pct']/100*50)
df['diff_nofee']=df['net_usdt']-df['pred_no_fee']
print("\ndiff (net_usdt - gross@$50) describe (==0 -> NO fee applied):")
print(df['diff_nofee'].describe())
print("by cohort:")
print(df.groupby('cohort')['diff_nofee'].agg(['mean','median','min','max','std']))

# Are there rows where fee clearly applied (diff meaningfully negative)?
sig=df[df['diff_nofee']< -0.02]
print("\nrows with net at least $0.02 below gross@50:",len(sig))
if len(sig):
    print(sig.groupby('cohort').size().to_dict())
    print("their gross_pct sign:",sig['iswin'].value_counts().to_dict())
