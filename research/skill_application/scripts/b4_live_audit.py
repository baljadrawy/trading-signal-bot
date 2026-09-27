import sys, numpy as np, pandas as pd
np.random.seed(42)
cols=['signal_id','symbol','tf','trade_type','mktcond','usdtd','btc_trend','signal_time','exit_time','result','gross','net_usdt','target_reached','stop_hit','dur']
df=pd.read_csv('/home/tradmin/trading-signal-bot/research/skill_application/scripts/b4_live.csv',header=None,names=cols)
# coerce booleans t/f
for c in ['target_reached','stop_hit']:
    df[c]=df[c].map({'t':True,'f':False})
df['gross']=pd.to_numeric(df['gross'],errors='coerce')
df['net_usdt']=pd.to_numeric(df['net_usdt'],errors='coerce')
df['signal_time']=pd.to_datetime(df['signal_time'])
df=df.dropna(subset=['gross','trade_type','usdtd']).reset_index(drop=True)
print("N total:",len(df),"| symbols:",df.symbol.nunique(),"| date range:",df.signal_time.min().date(),"->",df.signal_time.max().date())
print("years present:",sorted(df.signal_time.dt.year.unique()))

# winsorize gross at 1/99
lo,hi=np.percentile(df.gross,[1,99])
df['grossw']=df.gross.clip(lo,hi)
print(f"winsor bounds gross: [{lo:.3f},{hi:.3f}]  (raw min/max {df.gross.min():.2f}/{df.gross.max():.2f})")

def netcol(g,fee): return g-fee

def clustered_boot(sub, fee=0.3, reps=3000):
    # resample SYMBOLS with replacement
    syms=sub.symbol.unique()
    groups={s:sub[sub.symbol==s]['grossw'].values for s in syms}
    means=[]
    for _ in range(reps):
        pick=np.random.choice(syms,size=len(syms),replace=True)
        vals=np.concatenate([groups[s] for s in pick])
        means.append(vals.mean()-fee)
    return np.percentile(means,[2.5,97.5])

print("\n=== PER-CELL net expectancy % (gross winsorized minus fee) + symbol-clustered 95% CI ===")
rows=[]
for tt in ['momentum','reversion']:
    for mc in ['falling','flat','rising']:
        sub=df[(df.trade_type==tt)&(df.usdtd==mc)]
        if len(sub)==0: continue
        g=sub.grossw.mean()
        ci=clustered_boot(sub,0.3)
        rows.append((tt,mc,len(sub),sub.symbol.nunique(),g,g-0.3,g-0.6,ci[0],ci[1]))
        print(f"{tt:9s} {mc:8s} n={len(sub):3d} syms={sub.symbol.nunique():2d} gross={g:+.3f} net03={g-0.3:+.3f} net06={g-0.6:+.3f}  CI95(net03)=[{ci[0]:+.3f},{ci[1]:+.3f}]")

# ---- ALIGNMENT RULES ----
print("\n=== ALIGNMENT RULE portfolios (net@0.3 with symbol-clustered CI) ===")
# R_textbook: reversion in falling, momentum in rising, (flat -> reversion, the less-bad)
def rule_textbook(r):
    if r.usdtd=='falling': return r.trade_type=='reversion'
    if r.usdtd=='rising':  return r.trade_type=='momentum'
    return r.trade_type=='reversion'
# R_datadriven: reversion in every state (best per-state)
def rule_reversion_only(r): return r.trade_type=='reversion'
# R_momentum_only
def rule_momentum_only(r): return r.trade_type=='momentum'
for name,fn in [('TEXTBOOK(rev-fall,mom-rise)',rule_textbook),('REVERSION-only(macro-agnostic best)',rule_reversion_only),('MOMENTUM-only',rule_momentum_only),('ALL trades',lambda r:True)]:
    mask=df.apply(fn,axis=1)
    sub=df[mask]
    g=sub.grossw.mean()
    ci=clustered_boot(sub,0.3)
    ci6=clustered_boot(sub,0.6)
    print(f"{name:38s} n={len(sub):3d} gross={g:+.3f} net03={g-0.3:+.3f} CI95=[{ci[0]:+.3f},{ci[1]:+.3f}]  net06={g-0.6:+.3f} CI95=[{ci6[0]:+.3f},{ci6[1]:+.3f}]")

# Does macro add anything beyond trade_type main effect? interaction test on gross
import scipy.stats as st
print("\n=== Interaction: does usdtd macro modulate reversion gross? (Kruskal across 3 macro states within reversion) ===")
rev=df[df.trade_type=='reversion']
groups=[rev[rev.usdtd==m].grossw.values for m in ['falling','flat','rising']]
H,p=st.kruskal(*groups)
print(f"reversion across macro: H={H:.3f} p={p:.3f}  (means: fall={groups[0].mean():+.3f} flat={groups[1].mean():+.3f} rise={groups[2].mean():+.3f})")
mom=df[df.trade_type=='momentum']
gm=[mom[mom.usdtd==m].grossw.values for m in ['falling','flat','rising']]
Hm,pm=st.kruskal(*gm)
print(f"momentum  across macro: H={Hm:.3f} p={pm:.3f}  (means: fall={gm[0].mean():+.3f} flat={gm[1].mean():+.3f} rise={gm[2].mean():+.3f})")

# Best candidate cell remove-top-N fragility (reversion rising, least-negative)
print("\n=== REMOVE-TOP-N fragility on best gross cell (reversion+rising) ===")
best=df[(df.trade_type=='reversion')&(df.usdtd=='rising')].copy().sort_values('grossw',ascending=False)
for n in [0,1,2,3,5]:
    trimmed=best.iloc[n:]
    print(f"remove top {n}: n={len(trimmed)} gross={trimmed.grossw.mean():+.3f} net03={trimmed.grossw.mean()-0.3:+.3f}")

# overall reversion-only remove top N (does the positive gross survive?)
print("\n=== REMOVE-TOP-N on REVERSION-only gross (is +gross concentration-driven?) ===")
rr=df[df.trade_type=='reversion'].copy().sort_values('grossw',ascending=False)
for n in [0,1,2,3,5,10]:
    t=rr.iloc[n:]
    print(f"remove top {n:2d}: n={len(t)} gross={t.grossw.mean():+.3f} net03={t.grossw.mean()-0.3:+.3f}")
