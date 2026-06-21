#!/usr/bin/env python3
"""
Part 48 — Order Imbalance + Volatility Clustering (New Edge Class)
Cycle 18 Conclusion: Previous 47 parts exhausted traditional indicators.
Time to explore structural/micro patterns.

Hypothesis: Order book imbalance (bid-ask volume asymmetry) + recent volatility
clustering predicts short-term moves better than momentum alone.

Challenge: This requires aggregated trades or LOB snapshots, not just OHLCV.
Workaround: Use trades table (if available) to reconstruct microstructure signals.
"""

import sys, asyncio, json, numpy as np, pandas as pd, warnings
from datetime import datetime, timedelta

sys.path.insert(0, '/app')
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('part48')
warnings.filterwarnings('ignore')

async def check_available_tables():
    """Audit database schema for micro-structure data sources."""
    logger.info("Checking for microstructure data sources...")

    # Check what tables exist
    rows = await Database.fetch("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='public'
        AND table_type='BASE TABLE'
        ORDER BY table_name
    """)

    tables = [row['table_name'] for row in rows]
    logger.info(f"Available tables: {', '.join(tables)}")

    # Audit each table for relevant columns
    for table in tables:
        try:
            cols_result = await Database.fetch("SELECT column_name FROM information_schema.columns WHERE table_name=$1", table)
            cols = [c['column_name'] for c in cols_result]
            logger.info(f"\n{table}: {', '.join(cols[:10])}" + ("..." if len(cols) > 10 else ""))
        except:
            pass

    logger.info("\n" + "="*70)
    logger.info("Analysis Result:")
    logger.info("="*70)

    if 'trades' in tables or 'trades_aggregated' in tables:
        logger.info("✓ Trade-level data available → can reconstruct buy/sell imbalance")
    else:
        logger.info("✗ No granular trade data → cannot compute order imbalance")
        logger.info("  Workaround: Use OHLCV + bid-ask spread (if available)")

    logger.info("\nConclusion:")
    logger.info("Order imbalance edge requires either:")
    logger.info("  1. Binance Aggtrades API (real-time aggregated trades)")
    logger.info("  2. Historical trades table in DB (currently unavailable)")
    logger.info("  3. Level 2 orderbook snapshots (paid data subscription)")
    logger.info("\nPath forward: Evaluate feasibility of Binance Aggtrades download.")

if __name__ == '__main__':
    asyncio.run(check_available_tables())
