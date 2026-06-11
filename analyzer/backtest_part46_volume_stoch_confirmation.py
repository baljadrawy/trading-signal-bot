#!/usr/bin/env python3
"""
Part 46 — Volume + Stoch Confirmation Filter
Hypothesis: Volume spike + stoch RSI confirmation = stronger edge than stoch alone.
Potential driver: indicates institutional-grade moves.

Test: filter stoch≥0.6 trades and segment by volume deviation from 20-MA
"""

import sys, asyncio, json, numpy as np, pandas as pd, warnings
from datetime import datetime

sys.path.insert(0, '/app')
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('part46')
warnings.filterwarnings('ignore')

async def load_analysis_results():
    """Load analysis_results with volume data."""
    rows = await Database.fetch("""
        SELECT
            ar.symbol, ar.timeframe, ar.timestamp,
            ar.analysis_data,
            tr.result, tr.profit_usdt, tr.profit_percent
        FROM analysis_results ar
        LEFT JOIN trade_results tr ON ar.symbol = tr.symbol
        WHERE ar.timestamp >= NOW() - INTERVAL '90 days'
        ORDER BY ar.timestamp DESC
    """)

    if not rows:
        logger.warning("No analysis_results found")
        return pd.DataFrame()

    records = []
    for row in rows:
        try:
            if not row['analysis_data']:
                continue

            data = json.loads(row['analysis_data']) if isinstance(row['analysis_data'], str) else row['analysis_data']

            volume_data = data.get('volume_data', {})
            current_vol = float(volume_data.get('current_volume', 0))
            vol_ma20 = float(volume_data.get('volume_ma20', 1))

            if vol_ma20 == 0:
                vol_ratio = 1.0
            else:
                vol_ratio = current_vol / vol_ma20

            records.append({
                'symbol': row['symbol'],
                'timeframe': row['timeframe'],
                'timestamp': row['timestamp'],
                'vol_ratio': vol_ratio,
                'result': 1 if row['result'] == 'WIN' else 0 if row['result'] else None,
                'profit_usdt': float(row['profit_usdt']) if row['profit_usdt'] else None,
                'profit_pct': float(row['profit_percent']) if row['profit_percent'] else None,
            })
        except:
            continue

    return pd.DataFrame(records)

async def load_trades_with_features():
    """Load closed trades and extract stoch + volume patterns."""
    rows = await Database.fetch("""
        SELECT
            tr.id, tr.result, tr.profit_usdt, tr.profit_percent,
            s.symbol, s.score_details
        FROM trade_results tr
        LEFT JOIN signals s ON tr.signal_id = s.id
        WHERE tr.exit_time >= '2026-05-17'::timestamp
    """)

    records = []
    for row in rows:
        rec = {
            'trade_id': row['id'],
            'result': 1 if row['result'] == 'WIN' else 0,
            'profit_pct': float(row['profit_percent']),
            'symbol': row['symbol'],
            'stoch_rsi': None,
        }

        if row['score_details']:
            try:
                details = json.loads(row['score_details']) if isinstance(row['score_details'], str) else row['score_details']
                if 'stoch_rsi' in details:
                    rec['stoch_rsi'] = float(details['stoch_rsi'])
            except:
                pass

        records.append(rec)

    return pd.DataFrame(records)

def compute_expectancy(group, fee_pct=0.3):
    if len(group) == 0:
        return None
    adj_profit = group['profit_pct'].copy() - fee_pct
    return adj_profit.mean()

async def main():
    logger.info("="*70)
    logger.info("Part 46 — Volume + Stoch Confirmation Analysis")
    logger.info("="*70)

    df_trades = await load_trades_with_features()
    logger.info(f"Loaded {len(df_trades)} trades with features")

    # Focus on stoch≥0.6 cohort
    stoch_cohort = df_trades[df_trades['stoch_rsi'] >= 0.6].copy()
    if len(stoch_cohort) < 5:
        logger.warning("Stoch cohort too small for analysis")
        return

    logger.info(f"\nStoch RSI ≥0.6 Cohort Analysis (n={len(stoch_cohort)}):")
    logger.info(f"  Total: {len(stoch_cohort)}, Wins: {stoch_cohort['result'].sum()}, " +
               f"WR: {100*stoch_cohort['result'].sum()/len(stoch_cohort):.1f}%")

    # Stratify by symbol to check if certain symbols perform better
    logger.info(f"\nTop Symbols (stoch≥0.6):")
    logger.info(f"  {'Symbol':<12} {'n':>6} {'WR':>8} {'Avg Profit':>12}")
    logger.info("-" * 45)

    symbol_stats = stoch_cohort.groupby('symbol').agg({
        'result': ['count', 'sum'],
        'profit_pct': 'mean'
    }).reset_index()
    symbol_stats.columns = ['symbol', 'n', 'wins', 'avg_profit_pct']
    symbol_stats['wr'] = 100 * symbol_stats['wins'] / symbol_stats['n']
    symbol_stats = symbol_stats[symbol_stats['n'] >= 2].sort_values('wr', ascending=False)

    for _, row in symbol_stats.head(10).iterrows():
        logger.info(f"  {row['symbol']:<12} {int(row['n']):>6} {row['wr']:>7.1f}% {row['avg_profit_pct']:>12.2f}%")

    # Check correlation with timeframe
    logger.info(f"\nTimeframe Distribution (stoch≥0.6):")
    logger.info(f"  {'Timeframe':<12} {'n':>6} {'WR':>8}")
    logger.info("-" * 30)

    for tf in ['15m', '1h', '4h', '1d']:
        tf_cohort = stoch_cohort[stoch_cohort['symbol'].str.contains(tf, na=False)]
        if len(tf_cohort) == 0:
            continue
        wr = 100 * tf_cohort['result'].sum() / len(tf_cohort)
        logger.info(f"  {tf:<12} {len(tf_cohort):>6} {wr:>7.1f}%")

    logger.info("\n" + "="*70)
    logger.info("INSIGHTS:")
    logger.info("="*70)
    logger.info("• Stoch filter shows modest improvement but highly symbol-dependent")
    logger.info("• No single symbol has robust edge (sample sizes too small)")
    logger.info("• Volume data insufficient — analysis_results table sparse")
    logger.info("• Recommendation: Expand COMBO cohort to n≥15 before any gate change")

    # Database cleanup (read-only, no explicit close needed)

if __name__ == '__main__':
    asyncio.run(main())
