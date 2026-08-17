"""Price-process diagnostics for the phase-3 entry hypotheses.

This is supporting evidence, not a backtest: it tests whether cached raw price paths
look mean-reverting, persistent, or indistinguishable from a random walk.
"""
from __future__ import annotations

import argparse
import glob
import math
import pickle

import numpy as np


def variance_ratio(prices, horizon=5):
    log_prices = np.log(np.asarray(prices, dtype=float))
    one = np.diff(log_prices)
    if len(one) < horizon * 4 or np.var(one) == 0:
        return math.nan
    multi = log_prices[horizon:] - log_prices[:-horizon]
    return float(np.var(multi, ddof=1) / (horizon * np.var(one, ddof=1)))


def half_life(prices):
    values = np.log(np.asarray(prices, dtype=float))
    delta, lagged = np.diff(values), values[:-1]
    design = np.column_stack([np.ones(len(lagged)), lagged])
    beta = float(np.linalg.lstsq(design, delta, rcond=None)[0][1])
    if beta >= 0 or 1 + beta <= 0:
        return math.inf
    return float(-math.log(2) / math.log(1 + beta))


def hurst_rs(prices, max_lag=50):
    values = np.log(np.asarray(prices, dtype=float))
    lags, ratios = [], []
    for lag in range(8, min(max_lag, len(values) // 4) + 1, 4):
        samples = []
        for start in range(0, len(values) - lag + 1, lag):
            chunk = values[start:start + lag]
            deviations = chunk - chunk.mean()
            span = np.ptp(np.cumsum(deviations))
            std = chunk.std(ddof=1)
            if std > 0 and span > 0:
                samples.append(span / std)
        if samples:
            lags.append(lag)
            ratios.append(np.mean(samples))
    if len(lags) < 5:
        return math.nan
    return float(np.polyfit(np.log(lags), np.log(ratios), 1)[0])


def classify_path(hurst, vr, hl):
    if math.isfinite(hurst) and hurst < 0.4 and vr < 1 and math.isfinite(hl):
        return 'mean_reverting'
    if math.isfinite(hurst) and hurst > 0.6 and vr > 1:
        return 'persistent'
    return 'unconfirmed'


def review_files(pattern):
    rows = []
    for path in sorted(glob.glob(pattern)):
        with open(path, 'rb') as handle:
            raw = pickle.load(handle)
        closes = [float(row.get('c')) for row in raw if row.get('c') and float(row['c']) > 0]
        if len(closes) < 200:
            continue
        h, vr, hl = hurst_rs(closes), variance_ratio(closes), half_life(closes)
        rows.append((path, len(closes), h, vr, hl, classify_path(h, vr, hl)))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--glob', default='analyzer/research/cache/ict_ohlc/*_1h_ohlc.pkl')
    args = parser.parse_args()
    rows = review_files(args.glob)
    counts = {label: sum(row[-1] == label for row in rows)
              for label in ('mean_reverting', 'persistent', 'unconfirmed')}
    print('# Phase 3 — Raw-price process diagnostics')
    print(f"\n- Series: **{len(rows)}** (minimum 200 closed 1h bars)")
    print(f"- Mean-reverting by joint Hurst/VR/half-life rule: **{counts['mean_reverting']}**")
    print(f"- Persistent by joint Hurst/VR rule: **{counts['persistent']}**")
    print(f"- Unconfirmed/random: **{counts['unconfirmed']}**")
    if rows:
        print(f"- Median Hurst: **{np.nanmedian([r[2] for r in rows]):.3f}**")
        print(f"- Median variance ratio (q=5): **{np.nanmedian([r[3] for r in rows]):.3f}**")
        finite_hl = [r[4] for r in rows if math.isfinite(r[4])]
        print(f"- Median finite half-life: **{np.median(finite_hl):.1f} bars**" if finite_hl else '- No finite half-life')
    print('\nThis diagnoses raw prices only. Strategy promotion remains governed by net live/OOS trade results.')


if __name__ == '__main__':
    main()
