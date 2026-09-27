#!/usr/bin/env python3
"""TASK B2 — TIMEFRAME SELECTION. Independent falsify-first re-audit.
LIVE join (15m/1h/4h/1d) + HISTORICAL OOS engine (1h/4h/1d; NO 15m history).
Net expectancy in %: net = winsor(gross%) - fee.  Fee 0.3% (bot) and 0.6% (pessimistic).
Robustness: symbol-clustered bootstrap CI (resample SYMBOLS, 3000 reps),
leave-one-year-out (OOS) / leave-one-month-out (live), remove-top-N concentration."""
import numpy as np, pandas as pd, sys

def winsor(x, lo=1, hi=99):
    x = np.asarray(x, float)
    if len(x) < 5: return x
    a, b = np.percentile(x, [lo, hi]); return np.clip(x, a, b)

def clustered_boot(sub, fee, reps=3000, seed=0):
    """resample SYMBOLS with replacement -> net-expectancy CI. winsor within full sub."""
    rng = np.random.default_rng(seed)
    gw = winsor(sub['gross'].values)
    tmp = sub.assign(net=gw - fee)
    g = {s: tmp.loc[tmp.symbol == s, 'net'].values for s in tmp.symbol.unique()}
    syms = np.array(list(g.keys()))
    means = np.empty(reps)
    for i in range(reps):
        pick = rng.choice(syms, size=len(syms), replace=True)
        means[i] = np.concatenate([g[s] for s in pick]).mean()
    return np.percentile(means, [2.5, 97.5])

def remove_topN_flip(net):
    """If total is NEGATIVE: how many top LOSERS removed to flip positive (fragility of the loss).
       If total POSITIVE: how many top WINNERS removed to flip negative (fragility of the win)."""
    net = np.asarray(net, float); tot = net.sum()
    if tot > 0:
        s = np.sort(net)[::-1]; run = tot
        for i, v in enumerate(s):
            run -= v
            if run < 0: return ('win_flips_after_removing', i + 1)
        return ('win_never_flips', None)
    else:
        s = np.sort(net)  # most negative first
        run = tot
        for i, v in enumerate(s):
            run -= v
            if run > 0: return ('loss_flips_after_removing', i + 1)
        return ('loss_never_flips', None)

def analyze(sub, label, fee=0.3):
    n = len(sub); nsym = sub.symbol.nunique()
    gw = winsor(sub['gross'].values); net = gw - fee
    mean_net = net.mean()
    wr_net = (net > 0).mean() * 100
    pos = net[net > 0].sum(); neg = -net[net < 0].sum()
    pf = pos / neg if neg > 0 else np.inf
    ci = clustered_boot(sub, fee)
    # per-trade t-stat (naive, not clustered) for reference
    se = net.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    t = mean_net / se if se and se > 0 else np.nan
    flip = remove_topN_flip(net)
    return dict(label=label, n=n, nsym=nsym, mean_net=mean_net, wr=wr_net, pf=pf,
                ci_lo=ci[0], ci_hi=ci[1], t=t, flip=flip)

def show(r):
    pf = 'inf' if r['pf'] == np.inf else f"{r['pf']:.3f}"
    excl = (r['ci_lo'] > 0 or r['ci_hi'] < 0)
    tag = 'CI_EXCL_0' if excl else 'CI_incl_0'
    sign = 'POS' if r['ci_lo'] > 0 else ('neg' if r['ci_hi'] < 0 else '~0')
    print(f"{r['label']:<18} n={r['n']:>6} sym={r['nsym']:>3} meanNet={r['mean_net']:>+7.3f}% "
          f"WR={r['wr']:>4.1f}% PF={pf:>5} t={r['t']:>+5.2f} "
          f"CI95=[{r['ci_lo']:>+6.3f},{r['ci_hi']:>+6.3f}] {tag}({sign})  flip={r['flip']}")

def run_panel(df, tf_col, single_tfs, subsets, title, has_year=False, time_col=None):
    print(f"\n########## {title} ##########")
    for fee in (0.3, 0.6):
        print(f"\n===== SINGLE TIMEFRAMES (fee={fee}%) =====")
        for tf in single_tfs:
            sub = df[df[tf_col] == tf]
            if len(sub): show(analyze(sub, tf, fee))
        print(f"----- SUBSETS (fee={fee}%) -----")
        for lbl, tfs in subsets.items():
            sub = df[df[tf_col].isin(tfs)]
            if len(sub): show(analyze(sub, lbl, fee))
    # stability
    if has_year:
        print("\n===== LEAVE-ONE-YEAR-OUT (mean net% @0.3, winsor within panel) =====")
        keys = sorted(df['year'].unique())
        kcol = 'year'
    else:
        print("\n===== LEAVE-ONE-MONTH-OUT (mean net% @0.3, winsor within panel) =====")
        keys = sorted(df['month'].unique())
        kcol = 'month'
    for tf in single_tfs:
        sub = df[df[tf_col] == tf]
        if not len(sub): continue
        loo, per = [], []
        for k in keys:
            s2 = sub[sub[kcol] != k]
            loo.append(f"{k}:{(winsor(s2.gross.values)-0.3).mean():+.3f}" if len(s2) else f"{k}:—")
            s1 = sub[sub[kcol] == k]
            per.append(f"{k}:{(winsor(s1.gross.values)-0.3).mean():+.3f}(n{len(s1)})" if len(s1) else f"{k}:—")
        print(f"  {tf:<5} drop-each -> " + "  ".join(loo))
        print(f"        standalone-> " + "  ".join(per))

# ============ LIVE ============
cols = ['signal_id','symbol','timeframe','signal_time','gross','profit_usdt',
        'result','stop_hit','target_reached','duration_hours','trade_type','market_condition']
live = pd.read_csv("b2_live_fresh.csv", header=None, names=cols)
live['signal_time'] = pd.to_datetime(live['signal_time'])
live['gross'] = pd.to_numeric(live['gross'], errors='coerce')
live['month'] = live['signal_time'].dt.strftime('%m')
live = live.dropna(subset=['gross'])
print(f"LIVE rows={len(live)} symbols={live.symbol.nunique()} "
      f"months={sorted(live.month.unique())} tf_counts={live.timeframe.value_counts().to_dict()}")
run_panel(live, 'timeframe',
          single_tfs=['15m','1h','4h','1d'],
          subsets={'4h+1d(drop15m/1h)':['4h','1d'],'15m+4h+1d(botTFs)':['15m','4h','1d'],
                   '15m+1h+4h+1d(all)':['15m','1h','4h','1d'],'1h+4h+1d':['1h','4h','1d']},
          title="LIVE JOIN (all 2026; leave-one-MONTH-out)", has_year=False)

# ============ OOS ============
oos = pd.read_csv("b2_oos_trades.csv")
oos = oos.rename(columns={'tf':'timeframe'})
print(f"\nOOS rows={len(oos)} symbols={oos.symbol.nunique()} years={sorted(oos.year.unique())} "
      f"tf_counts={oos.timeframe.value_counts().to_dict()}")
run_panel(oos, 'timeframe',
          single_tfs=['1h','4h','1d'],
          subsets={'4h+1d':['4h','1d'],'1h+4h+1d':['1h','4h','1d']},
          title="HISTORICAL OOS ENGINE (multi-year; NO 15m history; leave-one-YEAR-out)",
          has_year=True)
