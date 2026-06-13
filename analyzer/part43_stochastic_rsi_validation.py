#!/usr/bin/env python3
"""
Part 43: Stochastic RSI Validation on Growing Freeze Window
"""
import asyncio
import psycopg2
from datetime import datetime, timezone
import json
import sys
sys.path.insert(0, '/app')
from shared.logger import get_logger

logger = get_logger('backtester.part43')

async def main():
    conn = psycopg2.connect(
        host='postgres',
        user='trading_signal_bot',
        password='trading_signal_bot',
        dbname='trading_signals'
    )
    cur = conn.cursor()
    
    logger.info("=== Part 43: Stochastic RSI Validation ===")
    
    # Fetch post-freeze cohort
    cur.execute("""
    SELECT 
      COUNT(*),
      ROUND(100.0*SUM(CASE WHEN pnl_percent > 0 THEN 1 ELSE 0 END)::float/NULLIF(COUNT(*), 0), 1) as wr,
      ROUND(AVG(pnl_percent), 4),
      ROUND(SUM(pnl_dollar), 2)
    FROM trade_results
    WHERE closed_at >= '2026-05-17'::date
    """)
    
    n, wr, avg_pnl_pct, net_pnl = cur.fetchone()
    
    logger.info(f"\nPost-Freeze Cohort (since 2026-05-17): n={n}/50 | WR={wr}% | Avg={avg_pnl_pct}% | Net=${net_pnl}")
    
    logger.info(f"\nPart 42 Discovery (Historical n=295):")
    logger.info(f"  stoch_rsi≥0.6: WR=42.9%, E=+0.10%, cumulative PnL=+$5.67")
    
    logger.info(f"\nStatus: PROMISING but BLOCKED BY FREEZE")
    logger.info(f"  Current: {n}/50 forward trades collected")
    logger.info(f"  Next: At n=25, validate stoch_rsi≥0.6 on post-freeze subset")
    logger.info(f"  Decision: Deploy if post-freeze stoch_rsi≥0.6 WR > baseline+5% and no code changes (frozen)")
    
    result = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'part': 'part43',
        'post_freeze_count': n,
        'post_freeze_wr': wr,
        'post_freeze_avg_pnl': avg_pnl_pct,
        'post_freeze_net_pnl': net_pnl,
        'part42_stoch_rsi_finding': {
            'filter': 'stoch_rsi>=0.6',
            'n_filtered': 56,
            'wr': 0.429,
            'e_adj_pct': 0.10,
            'cumulative_pnl': 5.67
        },
        'action': 'MONITOR_UNTIL_N50_THEN_DEPLOY'
    }
    
    with open('/app/analyzer/backtest_results_part43.jsonl', 'a') as f:
        f.write(json.dumps(result) + '\n')
    
    logger.info(f"\n=== Part 43 Complete ===")
    
    conn.close()

if __name__ == '__main__':
    asyncio.run(main())
