#!/usr/bin/env python3
"""
TASK B3 — feature-gate overlay collector on the historical OOS engine.
Reuses target_policy_bt to faithfully replicate the live bot: closed-candle,
down-market (bearish|sideways) score>=3 entries, arm A (current) exit logic,
non-overlapping by exit index (the honest 'natural' baseline that reaches ~25% T1).

At each entry candle i we reconstruct the SAME features the bot records:
  dist_ema200 = (close - ema200) / close        (bot: divided by close)
  macd_hist   = ta MACD(12,26,9).macd_diff()    (bot uses ta.trend.MACD)
  cci20       = ta CCI(20)                        (bot prefers pta, falls back to ta; close)
  bb_pos      = (close - bb_l) / (bb_u - bb_l)
Records gross% (arm A), symbol, tf, year, and the features -> b3_trades.csv.
NO look-ahead: every feature uses only data up to and including candle i.
"""
import os, sys, glob, math, json
import numpy as np, pandas as pd, ta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from target_policy_bt import (load, indicators, regime_array, score_array, simulate,
                              MAX_SL, TF_HOURS, WARM, MIN_SCORE, DATA)

TFS = ["1h", "4h", "1d"]


def add_extra(df):
    c, h, l = df['close'], df['high'], df['low']
    macd = ta.trend.MACD(close=c, window_fast=12, window_slow=26, window_sign=9)
    df['macd_hist'] = macd.macd_diff()
    df['cci20'] = ta.trend.CCIIndicator(h, l, c, window=20).cci()
    return df


def run(syms):
    out = []
    nsym = 0
    for sym in syms:
        for tf in TFS:
            df = load(sym, tf)
            if df is None:
                continue
            try:
                df = indicators(df)
                df = add_extra(df)
            except Exception:
                continue
            L = len(df)
            close = df['close'].to_numpy(); high = df['high'].to_numpy(); low = df['low'].to_numpy()
            e20 = df['ema20'].to_numpy(); e50 = df['ema50'].to_numpy(); e200 = df['ema200'].to_numpy()
            atr = df['atr'].to_numpy(); avg = df['avg_atr'].to_numpy()
            bb_u = df['bb_u'].to_numpy(); bb_l = df['bb_l'].to_numpy()
            macd_hist = df['macd_hist'].to_numpy(); cci20 = df['cci20'].to_numpy()
            years = pd.to_datetime(df['t'], unit='ms', errors='coerce').dt.year.to_numpy()
            reg = regime_array(close, e20, e50, e200, atr, avg)
            sc_bear = score_array(df, 'bearish'); sc_side = score_array(df, 'sideways')
            sc = np.where(reg == 'bearish', sc_bear, np.where(reg == 'sideways', sc_side, 0.0))
            down = (reg == 'bearish') | (reg == 'sideways')
            cand = down & (sc >= MIN_SCORE)
            cand[:WARM] = False; cand[L - 1:] = False
            sup20 = pd.Series(low).rolling(20).min().to_numpy()
            res20 = pd.Series(high).rolling(20).max().to_numpy()
            idxs = np.nonzero(cand)[0]

            nxt = WARM
            for i in idxs:
                if i < nxt:
                    continue
                entry = close[i]; a = atr[i]
                if entry <= 0 or np.isnan(a):
                    continue
                stop = max(entry - a * 1.5, sup20[i] * 0.99)
                if stop >= entry:
                    stop = entry * 0.97
                cap = MAX_SL.get(tf, 0.04); mr = entry * cap
                if (entry - stop) > mr:
                    stop = entry - mr
                if np.isnan(stop) or stop >= entry:
                    continue
                risk = entry - stop
                t1 = entry + risk; t2 = entry + risk * 1.8; t3 = entry + risk * 2.2
                if t1 > res20[i] > entry:
                    t1 = res20[i] * 0.99
                if not (t1 > entry) or np.isnan(t1):
                    continue
                t2 = max(t2, t1 + entry * 0.001); t3 = max(t3, t2 + entry * 0.001)
                r = simulate(high, low, close, i, entry, stop, t1, t2, t3, tf)
                if r is None:
                    continue
                g, xi, r1, r2 = r
                de200 = (entry - e200[i]) / entry if (e200[i] == e200[i] and entry) else np.nan
                bbrng = bb_u[i] - bb_l[i]
                bbp = (entry - bb_l[i]) / bbrng if (bbrng == bbrng and bbrng > 0) else np.nan
                yr = int(years[i]) if years[i] == years[i] else 0
                out.append((sym, tf, yr, g, r1, r2, sc[i], de200,
                            macd_hist[i], cci20[i], bbp))
                nxt = xi + 1
        nsym += 1
        if nsym % 50 == 0:
            print(f"  {nsym}/{len(syms)}", flush=True)
    cols = ['symbol', 'tf', 'year', 'gross', 'reach_t1', 'reach_t2', 'score',
            'dist_ema200', 'macd_hist', 'cci20', 'bb_pos']
    return pd.DataFrame(out, columns=cols)


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    syms = sorted({os.path.basename(p) for p in glob.glob(f"{DATA}/*") if os.path.isdir(p)})
    syms = [s for s in syms if glob.glob(f"{DATA}/{s}/*/*.zip")]
    if limit:
        syms = syms[:limit]
    print(f"symbols: {len(syms)}  MIN_SCORE={MIN_SCORE} down-market arm-A natural entries", flush=True)
    res = run(syms)
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "b3_trades.csv")
    res.to_csv(p, index=False)
    print(f"WROTE {p}  rows={len(res)}  symbols={res['symbol'].nunique()}  years={sorted(res['year'].unique())}")
    print(res[['gross', 'reach_t1', 'dist_ema200', 'macd_hist', 'cci20', 'bb_pos']].describe().round(4).to_string())
