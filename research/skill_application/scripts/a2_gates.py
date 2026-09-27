import json, numpy as np, pandas as pd
from scipy import stats
rng=np.random.default_rng(42)
rows=[json.loads(l) for l in open('/home/tradmin/trading-signal-bot/research/skill_application/scripts/a2_data.jsonl')]
df=pd.DataFrame(rows)
df['profit_usdt']=pd.to_numeric(df['profit_usdt'],errors='coerce')
df['profit_percent']=pd.to_numeric(df['profit_percent'],errors='coerce')
df['is_win']=(df['profit_usdt']>0).astype(int)
for f in ['dist_ema200','macd_hist','cci20','rsi','roc10','obv_vs_ema','dist_ema50','bb_pos']:
    df[f]=pd.to_numeric(df[f],errors='coerce')

def wins(s):
    return s.clip(s.quantile(.01),s.quantile(.99))
df['net_w']=wins(df['profit_usdt'])          # winsorized NET usdt
df['gross_w']=wins(df['profit_percent'])      # winsorized GROSS pct
# net pct = gross pct - 0.3 (round trip); pessimistic - 0.6
df['net_pct_03']=df['profit_percent']-0.3
df['net_pct_06']=df['profit_percent']-0.6
df['net_pct_03_w']=wins(df['net_pct_03'])
df['net_pct_06_w']=wins(df['net_pct_06'])

print("=== QUANTILE MONOTONICITY of NET gross-pct expectancy (winsorized) ===")
for f in ['dist_ema200','macd_hist','cci20','rsi','roc10']:
    d=df.dropna(subset=[f]).copy()
    d['q']=pd.qcut(d[f],5,labels=False,duplicates='drop')
    g=d.groupby('q').agg(n=('gross_w','size'),wr=('is_win','mean'),
                         gross=('gross_w','mean'),net03=('net_pct_03_w','mean')).round(3)
    print(f"\n{f}:")
    print(g.to_string())

def cluster_boot(sub,col='net_pct_03_w',reps=3000):
    # symbol-clustered bootstrap mean
    syms=sub['symbol'].values; vals=sub[col].values
    uniq=sub['symbol'].unique()
    by={s:sub.index[sub['symbol']==s].values for s in uniq}
    means=[]
    arr=sub.set_index(sub.index)
    for _ in range(reps):
        pick=rng.choice(uniq,size=len(uniq),replace=True)
        idx=np.concatenate([by[s] for s in pick])
        means.append(sub.loc[idx,col].mean())
    means=np.array(means)
    return np.nanpercentile(means,2.5),np.nanpercentile(means,97.5)

print("\n\n=== THRESHOLD GATES (net expectancy, symbol-clustered 95% CI) ===")
def report(name,sub):
    n=len(sub); nsym=sub['symbol'].nunique()
    wr=sub['is_win'].mean()
    for col,lab in [('gross_w','GROSS%'),('net_pct_03_w','NET%@0.3'),('net_pct_06_w','NET%@0.6')]:
        m=sub[col].mean()
        lo,hi=cluster_boot(sub,col)
        print(f"  {name:28s} n={n:3d} sym={nsym:2d} wr={wr:.3f} {lab}: mean={m:+.3f}  CI[{lo:+.3f},{hi:+.3f}] {'POS' if lo>0 else ''}")

report("ALL (baseline)",df)
# gates from negative-IC direction: take LOW momentum / below-trend
for f,thr,op in [('dist_ema200',0,'<='),('dist_ema200',-0.05,'<='),('rsi',50,'<='),('rsi',40,'<='),
                 ('roc10',0,'<='),('macd_hist',0,'<='),('cci20',-100,'<='),('bb_pos',0,'<=')]:
    if op=='<=':
        sub=df[df[f]<=thr]
    else:
        sub=df[df[f]>=thr]
    if len(sub)>=25:
        report(f"{f}{op}{thr}",sub)

# combined best: below ema200 AND macd_hist<0
sub=df[(df['dist_ema200']<=0)&(df['macd_hist']<=0)]
if len(sub)>=25: report("ema200<=0 & macd<0",sub)
sub=df[(df['rsi']<=45)&(df['dist_ema200']<=0)]
if len(sub)>=25: report("rsi<=45 & ema200<=0",sub)
