#!/usr/bin/env python3
"""20/50 MA Strong-Uptrend backtest — falsify-first, no look-ahead, net of fees.
Read-only research. Tests the user's classic trend-following rule on our own 1d data.

RULE (all decided on CLOSED daily bars; fills at NEXT bar OPEN -> no look-ahead):
  Strong uptrend at bar t iff:
    MA20 > MA50                     (order)
    MA20[t] > MA20[t-SLOPE]         (20 rising)
    MA50[t] > MA50[t-SLOPE]         (50 rising)
  ENTRY (trend variant):  flat & strong-uptrend TRUE at close t -> BUY at open t+1
  ENTRY (pullback var):   strong-uptrend TRUE & bar t low touched <=20MA*(1+TOL)
                          & close t back above 20MA -> BUY at open t+1
  EXIT: (close < MA50) OR (MA20 < MA50) at close t -> SELL at open t+1
  Long-only, one position/symbol, full notional. Fees charged per round trip.
OUTPUT: per-trade CSV + A-F style console summary with debiasing tests.
"""
import os, glob, zipfile, sys
import numpy as np, pandas as pd

ROOT = "/home/tradmin/trading-signal-bot/research/skill_application"
SPOT = f"{ROOT}/data/bt_data"
OUT  = f"{ROOT}/scripts/ma2050_trades.csv"

MA_FAST, MA_SLOW = 20, 50
SLOPE = 3          # bars used to judge "rising"
PULLBACK_TOL = 0.02
FEES = [0.003, 0.006]   # round-trip: bot-accounting 0.3%, pessimistic 0.6%
MIN_BARS = 120


def parse_klines(lines):
    rows = []
    for ln in lines:
        p = ln.split(',')
        if not p or not p[0] or p[0][:1].isalpha():
            continue
        try:
            rows.append((int(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4])))
        except Exception:
            pass
    return rows


def load_1d(sym):
    files = sorted(glob.glob(f"{SPOT}/{sym}/1d/{sym}-1d-*.zip"))
    rows = []
    for f in files:
        try:
            z = zipfile.ZipFile(f); n = z.namelist()[0]
            rows += parse_klines(z.read(n).decode().splitlines())
        except Exception:
            pass
    if len(rows) < MIN_BARS:
        return None
    df = pd.DataFrame(rows, columns=['t','o','h','l','c']).drop_duplicates('t').sort_values('t')
    df['t'] = df['t'].apply(lambda x: x//1000 if x > 1e14 else x)
    df['dt'] = pd.to_datetime(df['t'], unit='ms')
    return df.reset_index(drop=True)


def backtest_symbol(sym, variant):
    df = load_1d(sym)
    if df is None:
        return []
    df['ma_f'] = df['c'].rolling(MA_FAST).mean()
    df['ma_s'] = df['c'].rolling(MA_SLOW).mean()
    df = df.dropna().reset_index(drop=True)
    if len(df) < SLOPE + 5:
        return []
    ma_f = df['ma_f'].values; ma_s = df['ma_s'].values
    c = df['c'].values; o = df['o'].values; l = df['l'].values
    dt = df['dt'].values
    n = len(df)
    strong = np.zeros(n, dtype=bool)
    for t in range(SLOPE, n):
        strong[t] = (ma_f[t] > ma_s[t]) and (ma_f[t] > ma_f[t-SLOPE]) and (ma_s[t] > ma_s[t-SLOPE])
    trades = []
    in_pos = False; entry_px = 0.0; entry_i = 0
    for t in range(SLOPE, n-1):
        if not in_pos:
            sig = False
            if strong[t]:
                if variant == 'trend':
                    sig = True
                elif variant == 'pullback':
                    sig = (l[t] <= ma_f[t]*(1+PULLBACK_TOL)) and (c[t] > ma_f[t])
            if sig:
                in_pos = True; entry_px = o[t+1]; entry_i = t+1
        else:
            exit_sig = (c[t] < ma_s[t]) or (ma_f[t] < ma_s[t])
            if exit_sig:
                exit_px = o[t+1]
                gross = exit_px/entry_px - 1.0
                trades.append({'sym': sym, 'entry_dt': dt[entry_i], 'exit_dt': dt[t+1],
                               'year': pd.Timestamp(dt[entry_i]).year,
                               'bars_held': t+1-entry_i, 'gross_ret': gross})
                in_pos = False
    # close any open position at last bar (mark-to-market, no fee escape)
    if in_pos:
        gross = c[n-1]/entry_px - 1.0
        trades.append({'sym': sym, 'entry_dt': dt[entry_i], 'exit_dt': dt[n-1],
                       'year': pd.Timestamp(dt[entry_i]).year,
                       'bars_held': n-1-entry_i, 'gross_ret': gross, 'open_at_end': True})
    return trades


def stats(rets, label):
    rets = np.asarray(rets, dtype=float)
    n = len(rets)
    if n == 0:
        return f"{label}: n=0"
    wins = rets[rets > 0]; losses = rets[rets <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float('inf')
    mean = rets.mean()*100
    se = rets.std(ddof=1)/np.sqrt(n)*100 if n > 1 else float('nan')
    t = mean/se if se and se == se and se != 0 else float('nan')
    wr = (rets > 0).mean()*100
    return (f"{label}: n={n:>5}  mean_net={mean:+.3f}%  t={t:+.2f}  "
            f"PF={pf:.3f}  WR={wr:.1f}%  sum={rets.sum()*100:+.0f}%")


if __name__ == "__main__":
    variant = sys.argv[1] if len(sys.argv) > 1 else 'trend'
    syms = sorted([os.path.basename(p) for p in glob.glob(f"{SPOT}/*") if os.path.isdir(p)])
    all_trades = []
    for i, s in enumerate(syms):
        all_trades += backtest_symbol(s, variant)
        if (i+1) % 100 == 0:
            print(f"  ...{i+1}/{len(syms)} symbols, {len(all_trades)} trades", flush=True)
    df = pd.DataFrame(all_trades)
    df.to_csv(OUT, index=False)
    print(f"\n=== 20/50 STRONG-UPTREND ({variant}) — {len(syms)} symbols, {len(df)} trades ===", flush=True)
    print(f"span {df['entry_dt'].min().date()} .. {df['exit_dt'].max().date()}  "
          f"median hold={df['bars_held'].median():.0f}d  mean hold={df['bars_held'].mean():.1f}d", flush=True)
    g = df['gross_ret'].values
    print("\n[A] GROSS (no fees):")
    print("   " + stats(g, "gross"))
    for fee in FEES:
        net = g - fee
        print(f"\n[NET @ {fee*100:.1f}% round-trip]:")
        print("   " + stats(net, f"net@{fee*100:.1f}"))
        # per-year
        print("   per-year:")
        for yr in sorted(df['year'].unique()):
            m = df['year'].values == yr
            print("      " + stats(net[m], f"{yr}"))
        # debias: remove top-N trades / top-N symbols
        order = np.argsort(net)[::-1]
        for k in (5, 20):
            keep = np.ones(len(net), bool); keep[order[:k]] = False
            print("   " + stats(net[keep], f"remove_top{k}_trades"))
        symsum = df.assign(net=net).groupby('sym')['net'].sum().sort_values(ascending=False)
        for k in (1, 5):
            drop = set(symsum.index[:k])
            m = ~df['sym'].isin(drop).values
            print("   " + stats(net[m], f"remove_top{k}_symbols"))
        # symbol-clustered bootstrap CI on mean (crypto is cross-correlated)
        syms_u = df['sym'].values
        uniq = np.array(sorted(set(syms_u)))
        idx_by_sym = {u: np.where(syms_u == u)[0] for u in uniq}
        rng = np.random.default_rng(42)
        nU = len(uniq)
        boot = []
        for b in range(2000):
            pick = uniq[rng.integers(0, nU, nU)]   # resample symbols WITH replacement
            ii = np.concatenate([idx_by_sym[p] for p in pick])
            boot.append(net[ii].mean()*100)
        boot = np.sort(boot)
        print(f"   sym-clustered bootstrap mean 95% CI = [{boot[25]:+.3f}%, {boot[975]:+.3f}%]")
    print("\nWROTE " + OUT, flush=True)
