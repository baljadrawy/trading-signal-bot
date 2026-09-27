import json, numpy as np, pandas as pd
from scipy import stats
from sklearn.metrics import roc_auc_score

rows=[json.loads(l) for l in open('/home/tradmin/trading-signal-bot/research/skill_application/scripts/a2_data.jsonl')]
df=pd.DataFrame(rows)
# coerce booleans possibly as strings
for c in ['trend_ok','target_reached','stop_hit']:
    if c in df: df[c]=df[c].map(lambda v: True if v in (True,'t','true','True') else (False if v in (False,'f','false','False') else np.nan))
df['profit_usdt']=pd.to_numeric(df['profit_usdt'],errors='coerce')
df['profit_percent']=pd.to_numeric(df['profit_percent'],errors='coerce')
df['is_win']=(df['profit_usdt']>0).astype(int)
print("N=",len(df),"win_rate_net=",df['is_win'].mean().round(3))
print("avg net usdt=",df['profit_usdt'].mean().round(3),"median=",df['profit_usdt'].median().round(3))
print("avg gross pct=",df['profit_percent'].mean().round(3))

# 27 numeric features
FEATS=['rsi','adx14','cci20','cmf20','mfi14','roc10','bb_pos','bb_width','atr_pct','stoch_d','stoch_k',
'willr14','ob_score','obv_vs_ema','macd_hist','dist_ema20','dist_ema50','dist_ema200','spread_pct',
'volume_ratio','volume_usdt','bid_ask_ratio','trend_ok']
# also total_score present; trend_ok is boolean numeric
for f in FEATS:
    if f in df: df[f]=pd.to_numeric(df[f],errors='coerce')

# winsorize net return for expectancy computations
def wins(s,lo=0.01,hi=0.99):
    ql,qh=s.quantile(lo),s.quantile(hi)
    return s.clip(ql,qh)
df['net_w']=wins(df['profit_usdt'])
df['gross_w']=wins(df['profit_percent'])

results=[]
for f in FEATS:
    if f not in df: continue
    x=df[f]; y=df['is_win']; ret=df['gross_w']
    m=x.notna()&y.notna()
    if m.sum()<30 or x[m].nunique()<3:
        continue
    try:
        auc=roc_auc_score(y[m],x[m])
    except Exception:
        auc=np.nan
    ic,ic_p=stats.spearmanr(x[m],df['profit_percent'][m])
    # AUC permutation-free p via Mann-Whitney U equivalence
    wins_grp=x[m][y[m]==1]; loss_grp=x[m][y[m]==0]
    try:
        U,p_mw=stats.mannwhitneyu(wins_grp,loss_grp,alternative='two-sided')
    except Exception:
        p_mw=np.nan
    results.append(dict(feature=f,n=int(m.sum()),auc=round(auc,4),absdev=round(abs(auc-0.5),4),
                        ic=round(ic,4),ic_p=round(ic_p,4),p_auc=round(p_mw,4)))

R=pd.DataFrame(results).sort_values('absdev',ascending=False)
# Benjamini-Hochberg on AUC p-values
from statsmodels.stats.multitest import multipletests
mask=R['p_auc'].notna()
rej,q,_,_=multipletests(R.loc[mask,'p_auc'],alpha=0.05,method='fdr_bh')
R.loc[mask,'bh_q']=q
R.loc[mask,'sig_bh']=rej
# also BH on IC p
rej2,q2,_,_=multipletests(R.loc[mask,'ic_p'],alpha=0.05,method='fdr_bh')
R.loc[mask,'ic_bh_q']=q2
R.loc[mask,'ic_sig_bh']=rej2
pd.set_option('display.width',200,'display.max_columns',30)
print(R[['feature','n','auc','absdev','p_auc','bh_q','sig_bh','ic','ic_p','ic_bh_q','ic_sig_bh']].to_string(index=False))
R.to_csv('/home/tradmin/trading-signal-bot/research/skill_application/scripts/a2_ranked.csv',index=False)
print("\nAny AUC significant after BH:",bool(R['sig_bh'].fillna(False).any()))
print("Any IC significant after BH:",bool(R['ic_sig_bh'].fillna(False).any()))
