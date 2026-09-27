import numpy as np, pandas as pd
cols=['signal_id','symbol','result','gross_pct','net_usdt','target_reached','stop_hit',
      'duration_hours','failure_reason','exit_time','timeframe','trade_type','market_condition','score']
df=pd.read_csv('/home/tradmin/trading-signal-bot/research/skill_application/scripts/a3_trades.csv',
               header=None,names=cols)
df['stop_hit']=df['stop_hit'].map({'t':True,'f':False})
df['exit_time']=pd.to_datetime(df['exit_time'])
for c in ['gross_pct','net_usdt','target_reached']:
    df[c]=pd.to_numeric(df[c],errors='coerce')
df['iswin']=(df['result']=='WIN')
df['ym']=df['exit_time'].dt.to_period('M')
def pf(x):
    x=np.asarray(x,float); p=x[x>0].sum(); n=-x[x<0].sum(); return p/n if n>0 else np.inf

print("=== MONTHLY GROSS PF + net (broad entry leak?) ===")
for ym,sub in df.groupby('ym'):
    g=sub['gross_pct'].values
    print(f" {ym}: n={len(sub):4d} WR={sub['iswin'].mean():.3f} T1={ (sub['target_reached']>=1).mean():.3f} PF_gross={pf(g):.3f} PF_net0.3={pf(g-0.3):.3f} grossMean={g.mean():.3f}%")

print("\n=== GROSS PF by timeframe ===")
for tf,sub in df.groupby('timeframe'):
    g=sub['gross_pct'].values
    print(f" {tf:4s}: n={len(sub):4d} WR={sub['iswin'].mean():.3f} PF_gross={pf(g):.3f} PF_net0.3={pf(g-0.3):.3f}")

print("\n=== GROSS PF by trade_type (tagged subset) ===")
for tt,sub in df.dropna(subset=['trade_type']).groupby('trade_type'):
    g=sub['gross_pct'].values
    print(f" {tt:10s}: n={len(sub):4d} WR={sub['iswin'].mean():.3f} PF_gross={pf(g):.3f} PF_net0.3={pf(g-0.3):.3f}")

# POST-FIX concentration: remove top-N winners, does gross-positive flip?
post=df[df['exit_time']>=pd.Timestamp('2026-07-19')].copy()
g=np.sort(post['gross_pct'].values)[::-1]
print(f"\n=== POST-FIX remove-top-N (n={len(post)}, PF_gross={pf(post['gross_pct'].values):.3f}, net$0.3={ (post['gross_pct'].values/100*50).sum()-len(post)*0.15:.2f}) ===")
gv=post['gross_pct'].values
for k in [0,1,2,3,5]:
    idx=np.argsort(gv)[::-1][k:]  # drop top k
    sub=gv[idx]
    net_usd=(sub/100*50).sum()-len(sub)*0.15
    print(f"  drop top {k}: PF_gross={pf(sub):.3f}  net$@0.3={net_usd:.2f}  (gross_sum$={(sub/100*50).sum():.2f})")
# top winners in post
print("  post-fix top 5 gross:", np.round(np.sort(gv)[::-1][:5],2), "symbols:",
      post.sort_values('gross_pct',ascending=False)['symbol'].head(5).tolist())

# FULL remove-top-N: how many trades removed to flip gross sign? (it's already negative, so how many to make positive)
gvf=df['gross_pct'].values
order=np.argsort(gvf)  # ascending -> remove worst losers
print(f"\n=== FULL remove-worst-N to flip gross-negative -> positive (gross_sum${gvf.sum()/100*50:.0f}) ===")
for k in [0,10,25,50,100]:
    keep=gvf[np.argsort(gvf)[k:]]  # drop k worst
    print(f"  drop {k} worst losers: gross_sum$={ (keep/100*50).sum():.2f}  PF_gross={pf(keep):.3f}")
