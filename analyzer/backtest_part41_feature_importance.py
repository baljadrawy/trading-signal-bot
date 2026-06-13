#!/usr/bin/env python3
import sys, asyncio, json, numpy as np, pandas as pd
from datetime import datetime

sys.path.insert(0, '/app')
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('part41')

async def main():
    logger.info("="*70)
    logger.info("Part 41 — Feature Importance from 20 Post-Freeze Trades")
    logger.info("="*70)
    
    try:
        # Load trades
        rows = await Database.fetch("""
            SELECT 
                tr.id, tr.symbol, tr.result, tr.profit_percent, tr.stop_hit,
                s.score, s.score_details, s.market_condition
            FROM trade_results tr
            LEFT JOIN signals s ON tr.signal_id = s.id
            WHERE tr.exit_time >= '2026-05-17T00:00:00'::timestamp
            ORDER BY tr.exit_time ASC
        """)
        
        logger.info(f"Loaded {len(rows)} trades")
        
        if not rows:
            return
        
        # Extract features
        features = []
        for row in rows:
            feat = {
                'result': 1 if row['result'] == 'WIN' else 0,
                'profit': float(row['profit_percent']),
                'score': float(row['score']) if row['score'] else 0,
                'stop_hit': 1 if row['stop_hit'] else 0,
                'symbol': row['symbol'],
                'condition': row['market_condition'],
            }
            
            # Parse score_details
            if row['score_details']:
                try:
                    details = json.loads(row['score_details']) if isinstance(row['score_details'], str) else row['score_details']
                    for k, v in details.items():
                        try:
                            feat[f'd_{k}'] = float(v)
                        except:
                            pass
                except:
                    pass
            
            features.append(feat)
        
        df = pd.DataFrame(features)
        
        # Stats
        wins = df['result'].sum()
        losses = len(df) - wins
        
        logger.info(f"\nOutcome: {wins}W / {losses}L ({100*wins/len(df):.1f}% WR)")
        logger.info(f"Avg Profit: {df['profit'].mean():+.2f}%")
        logger.info(f"Score Range: {df['score'].min():.1f} - {df['score'].max():.1f}")
        
        logger.info(f"\nFeature Importance (Correlation with WIN):")
        logger.info(f"  {'Feature':<25} {'Corr':>8} {'Win μ':>10} {'Loss μ':>10}")
        logger.info(f"  {'-'*60}")
        
        import warnings
        warnings.filterwarnings('ignore')
        
        for col in sorted(df.columns):
            if col in ['result', 'profit', 'symbol', 'condition']:
                continue
            
            mask = df[col].notna()
            if mask.sum() < 3:
                continue
            
            x = df.loc[mask, col].values
            y = df.loc[mask, 'result'].values
            
            if np.std(x) > 0.01:
                try:
                    corr = np.corrcoef(x, y)[0, 1]
                    if not np.isnan(corr):
                        win_m = df.loc[df['result']==1, col].mean()
                        loss_m = df.loc[df['result']==0, col].mean()
                        logger.info(f"  {col:<25} {corr:>8.3f} {win_m:>10.2f} {loss_m:>10.2f}")
                except:
                    pass
        
        logger.info("\n" + "="*70 + "\n")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
