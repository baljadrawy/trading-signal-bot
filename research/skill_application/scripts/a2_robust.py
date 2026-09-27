import json, numpy as np, pandas as pd
rng=np.random.default_rng(7)
rows=[json.loads(l) for l in open('/home/tradmin/trading-signal-bot/research/skill_application/scripts/a2_data.jsonl')]
df=pd.DataFrame(rows)
df['profit_usdt']=pd.to_numeric(df['profit_usdt'],errors='coerce')
df['profit_percent']=pd.to_numeric(df['profit_percent'],errors='coerce')
df['dist_ema200']=pd.to_numeric(df['dist_ema200'],errors='coerce')
df['is_win']=(df['profit_usdt']>0).astype(int)
df['signal_time']=pd.to_datetime(df['signal_time'])
def wins(s): return s.clip(s.quantile(.01),s.quantile(.99))
df['net03']=wins(df['profit_percent']-0.3)

g=df[df['dist_ema200']<=-0.05].copy()
print(f"BEST GATE dist_ema200<=-0.05: n={len(g)} symbols={g['symbol'].nunique()}")
print(f"  NET@0.3 mean={g['net03'].mean():+.3f}  sum={g['net03'].sum():+.1f}")

print("\n-- REMOVE-TOP-N (by net03 contribution) --")
srt=g.sort_values('net03',ascending=False)
for k in [0,1,2,3,5,8]:
    rem=srt.iloc[k:]
    print(f"  remove top {k}: n={len(rem)} mean_net03={rem['net03'].mean():+.3f}  sign={'+' if rem['net03'].mean()>0 else '-'}")

print("\n-- SYMBOL CONCENTRATION (top symbols by summed net03) --")
sc=g.groupby('symbol')['net03'].agg(['size','sum','mean']).sort_values('sum',ascending=False)
print(sc.head(8).round(3).to_string())
print("  ... total symbols:",len(sc))
top1=sc['sum'].iloc[0]; tot=g['net03'].sum()
print(f"  top-1 symbol contributes {top1:+.1f} of {tot:+.1f} total ({100*top1/tot:.0f}%)")

print("\n-- TIME-SPLIT STABILITY (median-time halves) --")
med=df['signal_time'].median()
for lab,sub in [('first-half',g[g['signal_time']<=med]),('second-half',g[g['signal_time']>med])]:
    if len(sub): print(f"  {lab}: n={len(sub)} mean_net03={sub['net03'].mean():+.3f} wr={sub['is_win'].mean():.3f}")

# weekly stability
print("\n-- WEEKLY mean net03 (whole gate) --")
g['week']=g['signal_time'].dt.isocalendar().week
wk=g.groupby('week')['net03'].agg(['size','mean']).round(3)
print(wk.to_string())

# Does gate improve on baseline in a paired sense? Baseline overall mean:
print(f"\nBaseline ALL mean_net03={df['net03'].mean():+.3f}  gate lift={g['net03'].mean()-df['net03'].mean():+.3f}")

# sign-flip: how many top trades removed to flip gate to negative
srt=g.sort_values('net03',ascending=False)
flip=None
for k in range(len(srt)):
    if srt.iloc[k:]['net03'].mean()<=0: flip=k; break
print(f"Trades to remove to flip gate NEGATIVE: {flip} of {len(g)}")
