import numpy as np, pandas as pd
from scipy import stats
np.random.seed(7)
df = pd.read_csv('/home/tradmin/trading-signal-bot/research/skill_application/scripts/a1_data.csv',
    header=None, names=['signal_id','symbol','tt','timeframe','score','market_condition',
    'usdtd_trend','profit_usdt','profit_percent','result','target_reached','stop_hit',
    'duration_hours','signal_time','exit_time','failure_reason'],
    keep_default_na=False, na_values=[''])   # do NOT treat 'null' as NaN
for c in ['profit_usdt','profit_percent']: df[c]=pd.to_numeric(df[c])
df['win']=(df['result']=='WIN').astype(int)
df['tagged']=df['tt'].isin(['momentum','reversion'])
df['signal_time']=pd.to_datetime(df['signal_time'])

# ---- FEE MODEL confirmation ----
resid=(df.profit_usdt-0.5*df.profit_percent)
print(f"CONFIRM profit_usdt == 0.5*profit_percent (GROSS, $50 notional, NO fee):")
print(f"  residual mean={resid.mean():.6f} std={resid.std():.6f} max_abs={resid.abs().max():.6f}")
print(f"  => recorded -785.48 is GROSS. TRUE NET after fees:")
N=len(df)
for fee,lab in [(0.003,'0.3%'),(0.006,'0.6%')]:
    net=df.profit_usdt.sum()-N*50*fee
    print(f"     @{lab} round-trip: net = -785.48 - {N*50*fee:.2f} = {net:.2f}")

# ---- tagged vs untagged loss split ----
print(f"\nLOSS SPLIT (recorded/gross $):")
for lab,sub in [('untagged(pre-tag, mostly April)',df[~df.tagged]),('tagged(reversion+momentum)',df[df.tagged])]:
    print(f"  {lab:34s} n={len(sub):5d} gross$={sub.profit_usdt.sum():8.2f} WR={sub.win.mean()*100:4.1f}% gross%mean={sub.profit_percent.mean():.4f}")
print(f"  reversion n={ (df.tt=='reversion').sum() } gross$={df.loc[df.tt=='reversion','profit_usdt'].sum():.2f} true_net@0.3={df.loc[df.tt=='reversion','profit_usdt'].sum()-(df.tt=='reversion').sum()*50*0.003:.2f}")
print(f"  momentum  n={ (df.tt=='momentum').sum() } gross$={df.loc[df.tt=='momentum','profit_usdt'].sum():.2f} true_net@0.3={df.loc[df.tt=='momentum','profit_usdt'].sum()-(df.tt=='momentum').sum()*50*0.003:.2f}")

# ---- win/loss magnitude asymmetry (mechanism of adverse selection) ----
w=df[df.win==1].profit_percent; l=df[df.win==0].profit_percent
print(f"\nWIN/LOSS ASYMMETRY (gross %):")
print(f"  win  n={len(w)} mean=+{w.mean():.3f}% median={w.median():.3f} p95={np.percentile(w,95):.2f} max={w.max():.2f}")
print(f"  loss n={len(l)} mean={l.mean():.3f}% median={l.median():.3f} p5={np.percentile(l,5):.2f} min={l.min():.2f}")
print(f"  payoff ratio (avgWin/|avgLoss|)={w.mean()/abs(l.mean()):.3f}  breakeven WR needed @0.3fee={ (abs(l.mean())+0.3)/(w.mean()+abs(l.mean()))*100:.1f}% vs actual {df.win.mean()*100:.1f}%")

# ---- stop-hit / target mechanism ----
df['stop_hit_b']=df['stop_hit']=='t'
print(f"\nSTOP/TARGET MECHANISM:")
print(f"  stop_hit share={df.stop_hit_b.mean()*100:.1f}%  target_reached>0 share={(pd.to_numeric(df.target_reached)>0).mean()*100:.1f}%")
print(f"  among LOSSES: stop_hit share={df[df.win==0].stop_hit_b.mean()*100:.1f}%")

# ---- reversion robustness recap with proper data ----
rev=df[df.tt=='reversion'].copy()
def wins(x): a,b=np.nanpercentile(x,[1,99]); return np.clip(x,a,b)
rev['net3']=wins(rev.profit_percent-0.30)
def cboot(sub,col,reps=3000):
    u=sub.symbol.unique(); by={s:sub.loc[sub.symbol==s,col].values for s in u}
    m=[np.concatenate([by[s] for s in np.random.choice(u,len(u),True)]).mean() for _ in range(reps)]
    return np.percentile(m,[2.5,97.5])
lo,hi=cboot(rev,'net3')
print(f"\nREVERSION (n={len(rev)}) net%@0.3 winsorized mean={rev.net3.mean():.4f} sym-clustered CI=({lo:.3f},{hi:.3f})")
print(f"  => true_net$ after 0.3% fees = {rev.profit_percent.sub(0.30).mul(0.5).sum():.2f} ; CI includes 0 -> NOT a robust positive")
