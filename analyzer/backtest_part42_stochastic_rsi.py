#!/usr/bin/env python3
"""
Part 42 — Stochastic RSI Filter Testing
Stochastic RSI أظهر ارتباط +0.572 بالفوز في Part 41.
اختبر إضافته كـ filter منفصل على كل الإشارات التاريخية.
"""

import sys, asyncio, json, numpy as np, pandas as pd
from datetime import datetime

sys.path.insert(0, '/app')
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('part42')

async def main():
    logger.info("="*70)
    logger.info("Part 42 — Stochastic RSI Filter Testing")
    logger.info("="*70)
    
    try:
        # Load all trades with score_details
        rows = await Database.fetch("""
            SELECT 
                tr.id, tr.result, tr.profit_percent, tr.stop_hit,
                s.score, s.score_details
            FROM trade_results tr
            LEFT JOIN signals s ON tr.signal_id = s.id
            WHERE tr.exit_time >= '2026-04-22T00:00:00'::timestamp
            ORDER BY tr.exit_time ASC
        """)
        
        logger.info(f"Loaded {len(rows)} trades")
        
        features = []
        for row in rows:
            feat = {
                'result': 1 if row['result'] == 'WIN' else 0,
                'profit': float(row['profit_percent']),
                'score': float(row['score']) if row['score'] else 0,
            }
            
            stoch_rsi = None
            if row['score_details']:
                try:
                    details = json.loads(row['score_details']) if isinstance(row['score_details'], str) else row['score_details']
                    if 'stoch_rsi' in details:
                        stoch_rsi = float(details['stoch_rsi'])
                except:
                    pass
            
            feat['stoch_rsi'] = stoch_rsi
            features.append(feat)
        
        df = pd.DataFrame(features)
        df = df[df['stoch_rsi'].notna()]  # Keep only trades with stoch_rsi
        
        logger.info(f"Trades with stoch_rsi data: {len(df)}")
        
        wins_all = df['result'].sum()
        wr_all = 100 * wins_all / len(df)
        
        logger.info(f"\nAll Trades (n={len(df)}): WR={wr_all:.1f}% | Avg={df['profit'].mean():+.2f}%")
        
        # Stratify by stoch_rsi threshold
        logger.info(f"\nStochastic RSI Stratification:")
        logger.info(f"  {'Threshold':<20} {'n':>5} {'WR':>8} {'Avg Profit':>12} {'Cumulative':>12}")
        logger.info(f"  {'-'*60}")
        
        import warnings
        warnings.filterwarnings('ignore')
        
        for threshold in [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
            high = df[df['stoch_rsi'] >= threshold]
            if len(high) > 0:
                wr = 100 * high['result'].sum() / len(high)
                avg = high['profit'].mean()
                cumulative_pnl = high[high['result']==1]['profit'].sum() - abs(high[high['result']==0]['profit'].sum())
                logger.info(f"  stoch_rsi≥{threshold:<6.1f}     {len(high):>5} {wr:>7.1f}% {avg:>12.2f}% {cumulative_pnl:>12.2f}")
        
        logger.info("\n" + "="*70 + "\n")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
