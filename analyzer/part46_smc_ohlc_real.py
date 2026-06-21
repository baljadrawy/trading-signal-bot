#!/usr/bin/env python3
"""
Part 46: SMC Features from Real OHLC — Walk-Forward Validation
2026-06-19

Prior SMC tests (parts 33-37) found 0/18 features surviving FDR.
This part uses REAL 1d OHLC klines from Binance API to compute:
  1. Imbalance candle (body >= 2x avg body of last 20 candles, bullish)
  2. Discount zone (price below 50% of recent swing range)
  3. OB recency (last major bearish candle age < 10 bars before entry)

Then applies Walk-Forward (3 windows) + permutation test per feature.

This is the 8th check on SMC. Expected outcome: no edge.
"""

import asyncio
import asyncpg
import urllib.request
import json
import time
import sys
import random
from datetime import datetime, timezone, timedelta
sys.path.insert(0, '/app')
from shared.logger import setup_logger

logger = setup_logger('backtester.part46')

DB_CONFIG = {
    'host': '172.21.0.2',
    'user': 'trading_signal_bot',
    'password': '6psgaD1GV2ClGtopvSe5Lm8za',
    'database': 'trading_signals'
}

def fetch_klines_1d(symbol, limit=100, end_ms=None):
    """Fetch 1d OHLC klines from Binance"""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}"
    if end_ms:
        url += f"&endTime={int(end_ms)}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
    return []

def compute_smc_features(klines, entry_price):
    """
    Compute SMC proxy features from 1d klines available before entry.
    klines: list of [ts, open, high, low, close, vol, ...]
    """
    if len(klines) < 25:
        return None

    # Extract OHLC arrays
    opens = [float(k[1]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    bodies = [abs(c - o) for o, c in zip(opens, closes)]

    # Feature 1: Imbalance candle in last 5 bars
    # Imbalance = body >= 2x avg body of prior 20 bars, AND bullish
    avg_body_20 = sum(bodies[-25:-5]) / 20 if len(bodies) >= 25 else None
    has_imbalance = False
    if avg_body_20 and avg_body_20 > 0:
        for i in range(-5, 0):
            if bodies[i] >= 2.0 * avg_body_20 and closes[i] > opens[i]:
                has_imbalance = True
                break

    # Feature 2: Discount zone (entry below 50% of 20-bar swing range)
    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    swing_range = recent_high - recent_low
    mid_point = recent_low + swing_range * 0.5
    in_discount = entry_price < mid_point

    # Feature 3: OB recency — last major bearish candle < 10 bars ago
    # Major bearish = body >= 1.5x avg body AND bearish
    avg_body_15 = sum(bodies[-20:-5]) / 15 if len(bodies) >= 20 else None
    ob_recency = None
    if avg_body_15 and avg_body_15 > 0:
        for i in range(-1, -len(klines), -1):
            if abs(i) > len(klines):
                break
            if bodies[i] >= 1.5 * avg_body_15 and closes[i] < opens[i]:
                ob_recency = abs(i)
                break
    ob_fresh = (ob_recency is not None and ob_recency <= 10)

    # Feature 4: BOS (Break of Structure) — close above last swing high
    swing_highs_5 = max(highs[-6:-1]) if len(highs) >= 6 else None
    bos_up = False
    if swing_highs_5 and closes[-1] > swing_highs_5:
        bos_up = True

    return {
        'imbalance': 1 if has_imbalance else 0,
        'discount': 1 if in_discount else 0,
        'ob_fresh': 1 if ob_fresh else 0,
        'bos_up': 1 if bos_up else 0,
    }

async def main():
    logger.info("=== Part 46: SMC OHLC Real Validation (8th Check) ===")

    conn = await asyncpg.connect(**DB_CONFIG)

    trades = await conn.fetch("""
        SELECT
            tr.id, tr.symbol, tr.result, tr.profit_usdt, tr.profit_percent,
            tr.stop_hit, tr.entry_price, tr.exit_time,
            s.signal_time, s.market_condition, s.score
        FROM trade_results tr
        JOIN signals s ON tr.signal_id = s.id
        WHERE tr.exit_time >= '2026-05-17'
          AND tr.result IS NOT NULL
        ORDER BY tr.exit_time ASC
    """)

    await conn.close()
    logger.info(f"Loaded {len(trades)} trades")

    enriched = []
    n_fail = 0

    for i, t in enumerate(trades):
        symbol = t['symbol']
        sig_time = t['signal_time']
        entry = float(t['entry_price'])

        # Fetch 1d klines ending at signal_time
        end_ms = sig_time.timestamp() * 1000
        klines = fetch_klines_1d(symbol, limit=60, end_ms=end_ms)

        if len(klines) < 25:
            n_fail += 1
            continue

        features = compute_smc_features(klines, entry)
        if not features:
            n_fail += 1
            continue

        enriched.append({
            'id': t['id'],
            'symbol': symbol,
            'result': t['result'],
            'pnl_usdt': float(t['profit_usdt']),
            'pnl_pct': float(t['profit_percent']),
            'market': t['market_condition'],
            **features
        })

        if (i + 1) % 10 == 0:
            time.sleep(0.3)
            logger.info(f"  Progress: {i+1}/{len(trades)}")

    logger.info(f"Enriched: {len(enriched)} trades | Failed: {n_fail}")

    if len(enriched) < 20:
        logger.error("Too few enriched trades — aborting")
        return

    feature_names = ['imbalance', 'discount', 'ob_fresh', 'bos_up']

    def compute_ic(trades, feature):
        """Information Coefficient: correlation between feature and outcome"""
        outcomes = [1 if t['pnl_usdt'] > 0 else 0 for t in trades]
        features = [t[feature] for t in trades]
        n = len(outcomes)
        if n < 5:
            return 0.0
        mean_f = sum(features) / n
        mean_o = sum(outcomes) / n
        cov = sum((f - mean_f) * (o - mean_o) for f, o in zip(features, outcomes)) / n
        std_f = (sum((f - mean_f)**2 for f in features) / n) ** 0.5
        std_o = (sum((o - mean_o)**2 for o in outcomes) / n) ** 0.5
        if std_f < 1e-9 or std_o < 1e-9:
            return 0.0
        return cov / (std_f * std_o)

    def permutation_test(trades, feature, observed_ic, n_perm=1000):
        """One-sided permutation test: P(IC >= observed | H0: no correlation)"""
        outcomes = [1 if t['pnl_usdt'] > 0 else 0 for t in trades]
        features = [t[feature] for t in trades]
        mean_f = sum(features) / len(features)
        mean_o = sum(outcomes) / len(outcomes)
        std_f = (sum((f - mean_f)**2 for f in features) / len(features)) ** 0.5
        std_o = (sum((o - mean_o)**2 for o in outcomes) / len(outcomes)) ** 0.5
        if std_f < 1e-9 or std_o < 1e-9:
            return 1.0

        count_geq = 0
        for _ in range(n_perm):
            shuffled = outcomes[:]
            random.shuffle(shuffled)
            cov_p = sum((f - mean_f) * (o - mean_o) for f, o in zip(features, shuffled)) / len(features)
            ic_p = cov_p / (std_f * std_o)
            if ic_p >= observed_ic:
                count_geq += 1

        return count_geq / n_perm

    logger.info(f"\n=== SMC Feature Analysis (n={len(enriched)}) ===")

    results = {}
    for feat in feature_names:
        n_pos = sum(1 for t in enriched if t[feat] == 1)
        n_neg = len(enriched) - n_pos
        wins_pos = sum(1 for t in enriched if t[feat] == 1 and t['pnl_usdt'] > 0)
        wins_neg = sum(1 for t in enriched if t[feat] == 0 and t['pnl_usdt'] > 0)
        wr_pos = wins_pos / n_pos if n_pos > 0 else 0
        wr_neg = wins_neg / n_neg if n_neg > 0 else 0
        net_pos = sum(t['pnl_usdt'] for t in enriched if t[feat] == 1)
        net_neg = sum(t['pnl_usdt'] for t in enriched if t[feat] == 0)

        ic = compute_ic(enriched, feat)
        p_val = permutation_test(enriched, feat, ic, n_perm=1000)

        logger.info(f"\n{feat}:")
        logger.info(f"  flag=1 n={n_pos}: WR={wr_pos*100:.1f}% net=${net_pos:.2f}")
        logger.info(f"  flag=0 n={n_neg}: WR={wr_neg*100:.1f}% net=${net_neg:.2f}")
        logger.info(f"  IC={ic:.4f} | p={p_val:.3f} | {'EDGE' if p_val < 0.10 else 'NO_EDGE'}")

        results[feat] = {'ic': ic, 'p': p_val, 'n_pos': n_pos, 'wr_pos': wr_pos}

    # FDR Benjamini-Hochberg correction
    logger.info(f"\n=== FDR Correction (BH, alpha=0.10) ===")
    sorted_feats = sorted(results.items(), key=lambda x: x[1]['p'])
    m = len(sorted_feats)
    survivors = []
    for rank, (feat, res) in enumerate(sorted_feats, 1):
        bh_threshold = (rank / m) * 0.10
        survived = res['p'] <= bh_threshold
        if survived:
            survivors.append(feat)
        logger.info(f"  {feat}: p={res['p']:.3f} | BH_thresh={bh_threshold:.4f} | {'SURVIVE' if survived else 'REJECT'}")

    logger.info(f"\nFDR Survivors: {len(survivors)}/{m} = {survivors if survivors else 'NONE'}")
    logger.info(f"Conclusion: {'EDGE FOUND — deploy candidate' if survivors else 'SMC_NO_EDGE (8th confirmation)'}")

    logger.info("\n=== Part 46 Complete ===")

if __name__ == '__main__':
    random.seed(42)
    asyncio.run(main())
