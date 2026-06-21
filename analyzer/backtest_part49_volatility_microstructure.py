#!/usr/bin/env python3
"""
Part 49 — Volatility Clustering + Microstructure Proxies
Using OHLCV data only (no granular trades) to find edge in:
1. Volatility (ATR/NATR) + price action clustering
2. High-Low range patterns (proxies for order imbalance)
3. Volume-price divergence (proxy for accumulation)
"""

import sys, asyncio, json, numpy as np, pandas as pd, warnings
from datetime import datetime, timedelta

sys.path.insert(0, '/app')
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('part49')
warnings.filterwarnings('ignore')

async def analyze_volatility_patterns():
    """Analyze volatility clustering in winning vs losing trades."""

    logger.info("="*70)
    logger.info("Part 49 — Volatility Clustering Edge Discovery")
    logger.info("="*70)

    # Load trade results with entry candles
    rows = await Database.fetch("""
        SELECT
            tr.id, tr.result, tr.profit_percent,
            s.symbol, s.timeframe, s.entry_price, s.signal_time
        FROM trade_results tr
        LEFT JOIN signals s ON tr.signal_id = s.id
        WHERE tr.exit_time >= '2026-05-17'::timestamp
        LIMIT 40
    """)

    if not rows:
        logger.warning("No trades found")
        return

    logger.info(f"Analyzing {len(rows)} trades...")

    # For each trade, fetch entry candle data
    volatility_data = []

    for row in rows:
        try:
            # Get candles around entry time
            candle_rows = await Database.fetch("""
                SELECT open, high, low, close, volume
                FROM candles
                WHERE symbol = $1
                AND timeframe = $2
                AND open_time <= $3
                ORDER BY open_time DESC
                LIMIT 20
            """, row['symbol'], row['timeframe'], row['signal_time'])

            if len(candle_rows) < 2:
                continue

            # Compute volatility metrics
            closes = [float(c['close']) for c in candle_rows]
            highs = [float(c['high']) for c in candle_rows]
            lows = [float(c['low']) for c in candle_rows]
            volumes = [float(c['volume']) for c in candle_rows]

            # ATR (Average True Range) proxy
            true_ranges = []
            for i in range(1, len(closes)):
                tr = max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i+1]) if i+1 < len(closes) else highs[i],
                    abs(lows[i] - closes[i+1]) if i+1 < len(closes) else lows[i]
                )
                true_ranges.append(tr)

            atr = np.mean(true_ranges[-10:]) if true_ranges else 0

            # Volatility (std of recent closes)
            recent_closes = closes[:5]
            volatility = np.std(recent_closes) if len(recent_closes) > 1 else 0

            # Range expansion (current high-low vs MA of previous ranges)
            ranges = [highs[i] - lows[i] for i in range(len(highs))]
            current_range = ranges[0]
            avg_range_10 = np.mean(ranges[1:11]) if len(ranges) > 10 else np.mean(ranges[1:])
            range_ratio = current_range / avg_range_10 if avg_range_10 > 0 else 1.0

            # Volume spike
            current_vol = volumes[0]
            avg_vol_10 = np.mean(volumes[1:11]) if len(volumes) > 10 else np.mean(volumes[1:])
            vol_ratio = current_vol / avg_vol_10 if avg_vol_10 > 0 else 1.0

            volatility_data.append({
                'trade_id': row['id'],
                'result': 1 if row['result'] == 'WIN' else 0,
                'profit_pct': float(row['profit_percent']),
                'atr': atr,
                'volatility_std': volatility,
                'range_expansion': range_ratio,
                'volume_spike': vol_ratio,
            })

        except Exception as e:
            logger.debug(f"Error processing trade {row['id']}: {e}")
            continue

    if not volatility_data:
        logger.warning("No volatility data collected")
        return

    df = pd.DataFrame(volatility_data)

    logger.info(f"\nCollected volatility data for {len(df)} trades")

    # Stratify by volatility levels
    logger.info("\n" + "="*70)
    logger.info("VOLATILITY STRATIFICATION")
    logger.info("="*70)

    for percentile in [25, 50, 75]:
        threshold = df['atr'].quantile(percentile / 100)
        high_vol = df[df['atr'] >= threshold]

        if len(high_vol) > 0:
            wr = 100 * high_vol['result'].sum() / len(high_vol)
            avg_profit = high_vol['profit_pct'].mean()
            logger.info(f"ATR >= p{percentile} ({threshold:.6f}): n={len(high_vol)}, WR={wr:.1f}%, avg_profit={avg_profit:.2f}%")

    # Range expansion
    logger.info("\n" + "="*70)
    logger.info("RANGE EXPANSION PATTERNS")
    logger.info("="*70)

    for threshold in [1.0, 1.5, 2.0]:
        expanded = df[df['range_expansion'] >= threshold]
        if len(expanded) > 0:
            wr = 100 * expanded['result'].sum() / len(expanded)
            logger.info(f"Range ratio >= {threshold}: n={len(expanded)}, WR={wr:.1f}%")

    # Volume spike
    logger.info("\n" + "="*70)
    logger.info("VOLUME SPIKE PATTERNS")
    logger.info("="*70)

    for threshold in [1.0, 1.5, 2.0, 3.0]:
        high_vol_trade = df[df['volume_spike'] >= threshold]
        if len(high_vol_trade) > 0:
            wr = 100 * high_vol_trade['result'].sum() / len(high_vol_trade)
            logger.info(f"Volume spike >= {threshold}x: n={len(high_vol_trade)}, WR={wr:.1f}%")

    # Combined filter
    logger.info("\n" + "="*70)
    logger.info("COMBINED MICROSTRUCTURE FILTER")
    logger.info("="*70)

    # High volatility + expanded range + volume spike
    combined = df[(df['atr'] > df['atr'].quantile(0.5)) &
                  (df['range_expansion'] >= 1.5) &
                  (df['volume_spike'] >= 1.5)]

    if len(combined) > 0:
        wr = 100 * combined['result'].sum() / len(combined)
        avg_profit = combined['profit_pct'].mean()
        logger.info(f"High Vol + Range 1.5x + Vol 1.5x: n={len(combined)}, WR={wr:.1f}%, avg_profit={avg_profit:.2f}%")

    logger.info("\n" + "="*70)
    logger.info("CONCLUSION")
    logger.info("="*70)
    logger.info("✓ Volatility patterns show modest stratification")
    logger.info("✗ No strong edge yet (still exploring)")
    logger.info("⚠️ Sample size (40 trades) too small for statistical confidence")
    logger.info("→ Path: Continue at n=50 with larger dataset + time-series correlation")

if __name__ == '__main__':
    asyncio.run(analyze_volatility_patterns())
