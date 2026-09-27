#!/usr/bin/env python3
"""Test 20/50 daily strong-uptrend as a GATE on our ACTUAL live paper trades.
Falsify-first, no look-ahead. Read-only.

For each live trade (symbol, signal_time, profit_percent):
  Compute daily MA20/MA50 from bt_data using ONLY daily bars CLOSED strictly
  before signal_time. Strong-uptrend = MA20>MA50 & MA20 rising & MA50 rising
  (over SLOPE bars). Split trades: gate PASS vs gate FAIL vs no-data.
  Compare net expectancy (profit_percent - fee), WR, PF, per-year, bootstrap.
Question: does gating our real signals on the uptrend filter turn the
book from net-negative to net-positive? (i.e., is it a useful speculation gate?)
"""
import os, glob, zipfile
import numpy as np, pandas as pd

ROOT = "/home/tradmin/trading-signal-bot/research/skill_application"
SPOT = f"{ROOT}/data/bt_data"
TRADES = "/tmp/claude-1000/-home-tradmin/f9e8015a-2572-40e2-8955-cabae27535bf/scratchpad/live_trades.tsv"
MA_FAST, MA_SLOW, SLOPE = 20, 50, 3
FEE = 0.3  # round-trip %, bot accounting


def parse_klines(lines):
    rows = []
    for ln in lines:
        p = ln.split(',')
        if not p or not p[0] or p[0][:1].isalpha():
            continue
        try:
            rows.append((int(p[0]), float(p[4])))  # t, close
        except Exception:
            pass
    return rows


def load_daily_close(sym):
    files = sorted(glob.glob(f"{SPOT}/{sym}/1d/{sym}-1d-*.zip"))
    rows = []
    for f in files:
        try:
            z = zipfile.ZipFile(f); n = z.namelist()[0]
            rows += parse_klines(z.read(n).decode().splitlines())
        except Exception:
            pass
    if len(rows) < MA_SLOW + SLOPE + 2:
        return None
    df = pd.DataFrame(rows, columns=['t','c']).drop_duplicates('t').sort_values('t')
    df['t'] = df['t'].apply(lambda x: x//1000 if x > 1e14 else x)
    df['close_dt'] = pd.to_datetime(df['t'], unit='ms')
    # daily bar with open time t CLOSES at t + 1 day
    df['bar_close_time'] = df['close_dt'] + pd.Timedelta(days=1)
    df['ma_f'] = df['c'].rolling(MA_FAST).mean()
    df['ma_s'] = df['c'].rolling(MA_SLOW).mean()
    df['ma_f_prev'] = df['ma_f'].shift(SLOPE)
    df['ma_s_prev'] = df['ma_s'].shift(SLOPE)
    df['strong'] = (df['ma_f'] > df['ma_s']) & (df['ma_f'] > df['ma_f_prev']) & (df['ma_s'] > df['ma_s_prev'])
    return df.dropna(subset=['ma_s_prev']).reset_index(drop=True)


def stats(rets, label):
    r = np.asarray(rets, float); n = len(r)
    if n == 0:
        return f"{label:<22} n=0"
    w = r[r > 0]; l = r[r <= 0]
    pf = w.sum()/abs(l.sum()) if l.sum() != 0 else float('inf')
    mean = r.mean(); se = r.std(ddof=1)/np.sqrt(n) if n > 1 else float('nan')
    t = mean/se if se and se == se and se != 0 else float('nan')
    return (f"{label:<22} n={n:>5}  net_mean={mean:+.3f}%  t={t:+.2f}  "
            f"PF={pf:.3f}  WR={(r>0).mean()*100:.1f}%  sum={r.sum():+.1f}%")


if __name__ == "__main__":
    tr = pd.read_csv(TRADES, sep='\t')
    tr.columns = ['symbol','signal_time','trade_type','timeframe','profit_percent']
    tr['signal_time'] = pd.to_datetime(tr['signal_time'])
    tr['net'] = tr['profit_percent'].astype(float) - FEE
    tr['year'] = tr['signal_time'].dt.year

    cache = {}
    flags = []
    for _, row in tr.iterrows():
        sym = row['symbol']
        if sym not in cache:
            cache[sym] = load_daily_close(sym)
        d = cache[sym]
        if d is None:
            flags.append(None); continue
        # last daily bar that CLOSED strictly before the signal
        elig = d[d['bar_close_time'] <= row['signal_time']]
        flags.append(bool(elig['strong'].iloc[-1]) if len(elig) else None)
    tr['gate'] = flags

    have = tr[tr['gate'].notna()]
    passd = have[have['gate'] == True]
    faild = have[have['gate'] == False]
    nodata = tr[tr['gate'].isna()]

    print(f"=== 20/50 DAILY UPTREND GATE on {len(tr)} live trades "
          f"(fee {FEE}% RT) ===")
    print(f"resolved={len(have)}  no-daily-data={len(nodata)}  "
          f"gate PASS={len(passd)} ({len(passd)/max(len(have),1)*100:.0f}%)  FAIL={len(faild)}\n")
    print(stats(tr['net'], "ALL (ungated)"))
    print(stats(have['net'], "ALL resolved"))
    print(stats(passd['net'], ">> GATE PASS (trade)"))
    print(stats(faild['net'], "   GATE FAIL (skip)"))

    print("\nPASS by year:")
    for y in sorted(passd['year'].unique()):
        print("   " + stats(passd[passd['year'] == y]['net'], f"{y}"))
    print("PASS by timeframe:")
    for tf in sorted(passd['timeframe'].unique()):
        print("   " + stats(passd[passd['timeframe'] == tf]['net'], f"{tf}"))

    # symbol-clustered bootstrap on PASS mean
    if len(passd) > 5:
        s = passd['symbol'].values; net = passd['net'].values
        uniq = np.array(sorted(set(s)))
        idx = {u: np.where(s == u)[0] for u in uniq}
        rng = np.random.default_rng(42); nU = len(uniq); boot = []
        for _ in range(2000):
            pick = uniq[rng.integers(0, nU, nU)]
            ii = np.concatenate([idx[p] for p in pick])
            boot.append(net[ii].mean())
        boot = np.sort(boot)
        print(f"\nPASS sym-clustered bootstrap mean 95% CI = "
              f"[{boot[50]:+.3f}%, {boot[1950]:+.3f}%]")
    # remove top-N concentration on PASS
    if len(passd) > 25:
        net = np.sort(passd['net'].values)[::-1]
        for k in (5, 20):
            print("   " + stats(net[k:], f"PASS remove_top{k}"))
