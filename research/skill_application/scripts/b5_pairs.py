#!/usr/bin/env python3
"""B5 pairs feasibility: cointegration screen on liquid L1s from bt_data (1d) +
walk-forward z-score mean-reversion spread backtest with fees & robustness.
Falsify-first: hedge ratio & spread stats estimated ONLY on trailing window
(no look-ahead); fees charged per completed pairs trade on GROSS capital;
robustness = pair-clustered bootstrap + leave-one-year-out + remove-top-N."""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/tradmin/trading-signal-bot/research/skill_application/scripts")
import numpy as np, pandas as pd
from itertools import combinations
from statsmodels.tsa.stattools import adfuller, coint
from target_policy_bt import load

L1 = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","ADAUSDT","AVAXUSDT","DOTUSDT",
      "MATICUSDT","LINKUSDT","ATOMUSDT","NEARUSDT","INJUSDT","FTMUSDT","ALGOUSDT",
      "EGLDUSDT","APTUSDT"]

# ---- load aligned 1d log-close panel ----
cl = {}
for s in L1:
    df = load(s, "1d")
    if df is None: continue
    ix = pd.to_datetime(df["t"], unit="ms").dt.normalize()
    c = pd.Series(df["close"].values, index=ix)
    c = c[~c.index.duplicated()].sort_index()
    cl[s] = c
panel = pd.DataFrame(cl).sort_index()
logp = np.log(panel)
print(f"panel: {panel.shape[0]} days x {panel.shape[1]} syms | {panel.index.min().date()}..{panel.index.max().date()}")

def half_life(spread):
    s = pd.Series(spread).dropna().values
    if len(s) < 30: return np.nan
    y = np.diff(s); x = s[:-1]
    b = np.polyfit(x, y, 1)[0]
    if b >= 0: return np.nan
    return -np.log(2)/np.log(1+b)

def hurst(ts):
    ts = np.asarray(ts); ts = ts[~np.isnan(ts)]
    if len(ts) < 50: return np.nan
    lags = range(2, 20)
    tau = [np.std(ts[l:]-ts[:-l]) for l in lags]
    tau = np.array(tau); tau[tau<=0] = 1e-9
    return np.polyfit(np.log(list(lags)), np.log(tau), 1)[0]

# ---- STEP 1: full-sample cointegration screen (in-sample; screening only) ----
print("\n=== COINTEGRATION SCREEN (full-sample Engle-Granger, both directions) ===")
print(f"{'pair':<22}{'n':>5}{'corr':>7}{'EG_p_min':>10}{'beta':>8}{'half_life_d':>12}{'hurst':>7}")
screen = []
for a, b in combinations(L1, 2):
    sub = logp[[a,b]].dropna()
    if len(sub) < 250: continue
    x = sub[a].values; y = sub[b].values
    corr = np.corrcoef(x, y)[0,1]
    # Engle-Granger both directions
    try:
        p1 = coint(y, x)[1]; p2 = coint(x, y)[1]
    except Exception:
        continue
    pmin = min(p1, p2)
    # hedge ratio in the stronger direction
    if p1 <= p2:
        beta = np.polyfit(x, y, 1)[0]; spr = y - beta*x
    else:
        beta = np.polyfit(y, x, 1)[0]; spr = x - beta*y
    hl = half_life(spr); hu = hurst(spr)
    screen.append(dict(a=a,b=b,n=len(sub),corr=corr,egp=pmin,beta=beta,hl=hl,hu=hu))
sc = pd.DataFrame(screen).sort_values("egp")
for _, r in sc.iterrows():
    flag = " <== coint p<.05" if r["egp"] < 0.05 else ""
    print(f"{r['a'][:-4]+'/'+r['b'][:-4]:<22}{int(r['n']):>5}{r['corr']:>7.2f}{r['egp']:>10.4f}{r['beta']:>8.3f}{r['hl']:>12.1f}{r['hu']:>7.3f}{flag}")
n_coint = (sc.egp < 0.05).sum()
print(f"\ncointegrated pairs (full-sample EG p<0.05): {n_coint} / {len(sc)}  (expected by chance @5%: {0.05*len(sc):.1f})")

# ---- STEP 2: WALK-FORWARD z-score MR backtest (no look-ahead) ----
# rolling window W: estimate beta + spread mean/std on [t-W, t-1]; trade at t.
W = 90; ENTRY = 2.0; EXITZ = 0.0; STOPZ = 3.5; MAXHOLD = 60
def wf_backtest(a, b):
    sub = logp[[a,b]].dropna()
    if len(sub) < W+60: return None
    X = sub[a].values; Y = sub[b].values; dates = sub.index
    ret_a = np.concatenate([[0], np.diff(X)])  # log returns
    ret_b = np.concatenate([[0], np.diff(Y)])
    trades = []  # (exit_date, gross_ret_on_gross_capital, hold_days)
    pos = 0; entry_i = None; wY = wX = beta = None; dir_ = 0
    daily = []  # (date, gross daily ret while in position)
    for i in range(W, len(sub)):
        xw = X[i-W:i]; yw = Y[i-W:i]
        beta_i = np.polyfit(xw, yw, 1)[0]
        spr_w = yw - beta_i*xw
        mu = spr_w.mean(); sd = spr_w.std()
        if sd <= 0: continue
        spr_now = Y[i] - beta_i*X[i]
        z = (spr_now - mu)/sd
        # manage open position P&L for day i (position established at close of i-1)
        if pos != 0:
            wYc = 1.0/(1.0+abs(beta)); wXc = abs(beta)/(1.0+abs(beta))
            # long spread(pos=+1): long Y short X ; short spread(pos=-1): short Y long X
            dret = pos*(wYc*ret_b[i] - wXc*ret_a[i])
            daily.append((dates[i], dret))
            hold = i - entry_i
            exit_now = (pos==1 and z>=EXITZ) or (pos==-1 and z<=EXITZ) or abs(z)>STOPZ or hold>=MAXHOLD
            if exit_now:
                seg = [d for dd,d in daily if dd>dates[entry_i]]
                trades.append((dates[i], float(np.sum(seg)), hold, a, b))
                pos = 0; entry_i=None; daily=[]
        if pos == 0:
            if z > ENTRY:
                pos = -1; entry_i = i; beta = beta_i   # short spread
            elif z < -ENTRY:
                pos = 1; entry_i = i; beta = beta_i     # long spread
    return trades

# run on pairs that pass a permissive screen (corr>0.5 & half-life in 3..60)
cands = sc[(sc["corr"]>0.5) & (sc["hl"].between(3,60))]
print(f"\n=== WALK-FORWARD Z-SCORE MR BACKTEST ===")
print(f"candidates (corr>0.5, half-life 3-60d): {len(cands)}  | W={W} entry|z|>{ENTRY} exit z->0 stop|z|>{STOPZ} maxhold{MAXHOLD}d")
all_trades = []
for _, r in cands.iterrows():
    t = wf_backtest(r.a, r.b)
    if t: all_trades.extend(t)
T = pd.DataFrame(all_trades, columns=["exit_date","gross_ret","hold_d","a","b"])
T["year"] = pd.to_datetime(T["exit_date"]).dt.year
T["pair"] = T["a"].str[:-4]+"/"+T["b"].str[:-4]
# winsorize gross returns 1/99
lo, hi = T["gross_ret"].quantile([.01,.99])
T["gw"] = T["gross_ret"].clip(lo, hi)
print(f"total completed pairs trades: {len(T)}  | mean hold={T.hold_d.mean():.1f}d")

def summarize(df, fee):
    g = df["gw"].values
    net = g - fee
    return dict(n=len(g), gross_mean=g.mean()*100, net_mean=net.mean()*100,
                gross_tot=g.sum()*100, net_tot=net.sum()*100,
                winrate=(net>0).mean()*100)

for fee, lab in [(0.0,"GROSS (no fee)"),(0.003,"NET 0.3% pairs round-trip"),(0.006,"NET 0.6% pessimistic")]:
    s = summarize(T, fee)
    print(f"  {lab:<30} n={s['n']} mean/trade={s['net_mean']:+.3f}%  total={s['net_tot']:+.1f}%  winrate={s['winrate']:.1f}%")

# per-year net @0.3%
print("\n  leave-one-year-out (net mean %/trade @0.3% fee):")
for y in sorted(T.year.unique()):
    sub = T[T.year!=y]; inc = T[T.year==y]
    print(f"    exclude {y}: n={len(sub)} mean={ (sub['gw'].mean()-0.003)*100:+.3f}%  | that-year-only n={len(inc)} mean={(inc['gw'].mean()-0.003)*100:+.3f}%")

# remove-top-N concentration (does removing best trades flip net sign @0.3%?)
net_sorted = np.sort((T["gw"].values-0.003))[::-1]
cum = net_sorted.sum()
flip = None
for k in range(len(net_sorted)):
    if cum - net_sorted[:k].sum() <= 0:
        flip = k; break
print(f"\n  remove-top-N: total net@0.3% = {cum*100:+.1f}%; removing top {flip} winners flips it negative (n={len(T)})" if flip else f"\n  remove-top-N: net stays positive removing all winners? total={cum*100:+.1f}%")

# pair-clustered bootstrap of net mean/trade @0.3%
rng = np.random.default_rng(42)
pairs = T["pair"].unique()
by_pair = {p: T[T.pair==p]["gw"].values-0.003 for p in pairs}
boot = []
for _ in range(3000):
    samp = rng.choice(pairs, size=len(pairs), replace=True)
    vals = np.concatenate([by_pair[p] for p in samp])
    boot.append(vals.mean()*100)
lo_ci, hi_ci = np.percentile(boot, [2.5, 97.5])
print(f"\n  pair-clustered bootstrap 95% CI of net mean/trade @0.3%: [{lo_ci:+.3f}%, {hi_ci:+.3f}%]  (point {(T['gw'].mean()-0.003)*100:+.3f}%)")

# top per-pair net contribution
print("\n  per-pair net@0.3% (top/bottom):")
pp = T.groupby("pair").apply(lambda d: pd.Series(dict(n=len(d), net_mean=(d['gw'].mean()-0.003)*100, net_tot=(d['gw'].sum()-0.003*len(d))*100))).sort_values("net_tot", ascending=False)
print(pp.to_string())
