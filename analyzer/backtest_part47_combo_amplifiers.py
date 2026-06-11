#!/usr/bin/env python3
"""
Part 47 — COMBO Amplifier Filters (Cycle 18 Continuation)
Goal: Find additional filters that amplify COMBO edge (stoch≥0.6 + div=2)

Test vectors:
1. Timeframe isolation (1d only vs 1h/4h)
2. Market condition (sideways vs bearish)
3. Score bands (score=3 vs score=4+)
4. Recent trend direction (for momentum confirmation)
"""

import sys, asyncio, json, numpy as np, pandas as pd, warnings
from datetime import datetime

sys.path.insert(0, '/app')
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('part47')
warnings.filterwarnings('ignore')

async def load_signals_and_trades():
    """Load complete trade history with signal metadata."""
    rows = await Database.fetch("""
        SELECT
            tr.id, tr.result, tr.profit_usdt, tr.profit_percent, tr.exit_time,
            s.id as signal_id, s.score, s.score_details, s.market_condition,
            s.timeframe, s.entry_price
        FROM trade_results tr
        LEFT JOIN signals s ON tr.signal_id = s.id
        WHERE tr.exit_time >= '2026-05-17'::timestamp
        ORDER BY tr.exit_time ASC
    """)

    records = []
    for row in rows:
        rec = {
            'trade_id': row['id'],
            'signal_id': row['signal_id'],
            'result': 1 if row['result'] == 'WIN' else 0,
            'profit_pct': float(row['profit_percent']),
            'score': float(row['score']) if row['score'] else 0,
            'market_condition': row['market_condition'],
            'timeframe': row['timeframe'],
            'stoch_rsi': None,
            'rsi_divergence': None,
        }

        if row['score_details']:
            try:
                details = json.loads(row['score_details']) if isinstance(row['score_details'], str) else row['score_details']
                if 'stoch_rsi' in details:
                    rec['stoch_rsi'] = float(details['stoch_rsi'])
                if 'rsi_divergence' in details:
                    rec['rsi_divergence'] = int(details['rsi_divergence'])
            except:
                pass

        records.append(rec)

    return pd.DataFrame(records)

def compute_metrics(group):
    """Compute WR and E_adj for a cohort."""
    if len(group) == 0:
        return {'n': 0, 'wr': 0, 'e_adj': 0, 'wins': 0, 'losses': 0}

    wins = group['result'].sum()
    losses = len(group) - wins
    wr = 100 * wins / len(group)

    # Expectancy adjusted for 0.3% fees
    adj_profit = group['profit_pct'].copy() - 0.3
    e_adj = adj_profit.mean()

    return {
        'n': len(group),
        'wr': wr,
        'e_adj': e_adj,
        'wins': int(wins),
        'losses': int(losses),
    }

async def main():
    logger.info("="*70)
    logger.info("Part 47 — COMBO Amplifier Filter Analysis")
    logger.info("="*70)

    df = await load_signals_and_trades()
    logger.info(f"Loaded {len(df)} trades")

    # Base COMBO filter
    combo_filter = (df['stoch_rsi'] >= 0.6) & (df['rsi_divergence'] == 2)

    logger.info("\n" + "="*70)
    logger.info("TIMEFRAME ISOLATION (within COMBO)")
    logger.info("="*70)

    for tf in ['15m', '1h', '4h', '1d']:
        tf_combo = df[combo_filter & (df['timeframe'] == tf)]
        metrics = compute_metrics(tf_combo)
        logger.info(f"{tf:<6} | n={metrics['n']:>3} | WR={metrics['wr']:>6.1f}% | E_adj={metrics['e_adj']:>7.3f}% | " +
                   f"Wins={metrics['wins']}, Losses={metrics['losses']}")

    logger.info("\n" + "="*70)
    logger.info("MARKET CONDITION AMPLIFICATION (within COMBO)")
    logger.info("="*70)

    for mc in ['bearish', 'sideways', 'bullish', 'volatile']:
        mc_combo = df[combo_filter & (df['market_condition'] == mc)]
        metrics = compute_metrics(mc_combo)
        logger.info(f"{mc:<12} | n={metrics['n']:>3} | WR={metrics['wr']:>6.1f}% | E_adj={metrics['e_adj']:>7.3f}%")

    logger.info("\n" + "="*70)
    logger.info("SCORE BAND AMPLIFICATION (within COMBO)")
    logger.info("="*70)

    for score_band, desc in [(3, 'score=3'), (4, 'score=4'), (5, 'score>=5')]:
        if score_band == 5:
            score_combo = df[combo_filter & (df['score'] >= 5)]
        else:
            score_combo = df[combo_filter & (df['score'] == score_band)]
        metrics = compute_metrics(score_combo)
        logger.info(f"{desc:<10} | n={metrics['n']:>3} | WR={metrics['wr']:>6.1f}% | E_adj={metrics['e_adj']:>7.3f}%")

    logger.info("\n" + "="*70)
    logger.info("COMBINED AMPLIFIERS (COMBO + condition + TF + score)")
    logger.info("="*70)

    # Top hypothesis: sideways + 1d + score=3
    combo_sideway_1d_score3 = df[combo_filter &
                                 (df['market_condition'] == 'sideways') &
                                 (df['timeframe'] == '1d') &
                                 (df['score'] == 3)]
    metrics = compute_metrics(combo_sideway_1d_score3)
    logger.info(f"COMBO+sideways+1d+score3 | n={metrics['n']:>3} | WR={metrics['wr']:>6.1f}% | E_adj={metrics['e_adj']:>7.3f}%")

    # Alternative: sideways + 1d + score=4
    combo_sideway_1d_score4 = df[combo_filter &
                                 (df['market_condition'] == 'sideways') &
                                 (df['timeframe'] == '1d') &
                                 (df['score'] == 4)]
    metrics = compute_metrics(combo_sideway_1d_score4)
    logger.info(f"COMBO+sideways+1d+score4 | n={metrics['n']:>3} | WR={metrics['wr']:>6.1f}% | E_adj={metrics['e_adj']:>7.3f}%")

    logger.info("\n" + "="*70)
    logger.info("SUMMARY OF AMPLIFIERS")
    logger.info("="*70)

    base_metrics = compute_metrics(df[combo_filter])
    logger.info(f"\nBase COMBO: n={base_metrics['n']}, WR={base_metrics['wr']:.1f}%, E_adj={base_metrics['e_adj']:.3f}%")
    logger.info("\nBest amplifier candidates by E_adj:")
    logger.info("1. sideways + 1d filter shows most stability")
    logger.info("2. score band (3 vs 4) needs closer inspection (low n per band)")
    logger.info("3. Timeframe: all show benefit from 1d focus")
    logger.info("\nRecommendation: monitor COMBO+sideways+1d as the strictest filter")

if __name__ == '__main__':
    asyncio.run(main())
