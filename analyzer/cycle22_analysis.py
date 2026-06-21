#!/usr/bin/env python3
"""
Cycle 22 Analysis — Comprehensive performance audit + SMC/WRR research plan
"""
import asyncio
import sys
import json
from datetime import datetime, timedelta
from decimal import Decimal

sys.path.insert(0, '/app')

from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('cycle22_analysis')


async def get_recent_trades(days=14):
    """Get all closed trades from last N days"""
    query = """
    SELECT
        id, symbol, entry_price, exit_price, result, profit_usdt,
        duration_hours, stop_hit, exit_time, target_reached
    FROM trade_results
    WHERE exit_time > NOW() - ($1 * INTERVAL '1 day')
    ORDER BY exit_time DESC
    """
    return await Database.fetch(query, days)


async def get_all_trades_since_freeze():
    """Get all trades since freeze lift (2026-06-07)"""
    query = """
    SELECT
        id, symbol, entry_price, exit_price, result, profit_usdt,
        duration_hours, stop_hit, exit_time, target_reached
    FROM trade_results
    WHERE exit_time > TIMESTAMP '2026-06-07 00:00:00'
    ORDER BY exit_time ASC
    """
    return await Database.fetch(query)


async def analyze_stop_impact():
    """Analyze impact of SL hits on profitability"""
    query = """
    SELECT
        stop_hit,
        COUNT(*) as count,
        SUM(CASE WHEN profit_usdt > 0 THEN 1 ELSE 0 END) as wins,
        ROUND(AVG(profit_usdt)::numeric, 2) as avg_pnl,
        ROUND(SUM(profit_usdt)::numeric, 2) as total_pnl
    FROM trade_results
    WHERE exit_time > TIMESTAMP '2026-06-07 00:00:00'
    GROUP BY stop_hit
    ORDER BY stop_hit
    """
    return await Database.fetch(query)


async def analyze_target_hit_impact():
    """Analyze impact of target hit level on profitability"""
    query = """
    SELECT
        target_reached,
        COUNT(*) as count,
        SUM(CASE WHEN profit_usdt > 0 THEN 1 ELSE 0 END) as wins,
        ROUND(AVG(profit_usdt)::numeric, 2) as avg_pnl,
        ROUND(SUM(profit_usdt)::numeric, 2) as total_pnl
    FROM trade_results
    WHERE exit_time > TIMESTAMP '2026-06-07 00:00:00'
    GROUP BY target_reached
    ORDER BY target_reached
    """
    return await Database.fetch(query)


async def analyze_by_symbol():
    """Top/worst symbols post-freeze"""
    query = """
    SELECT
        symbol,
        COUNT(*) as trades,
        SUM(CASE WHEN profit_usdt > 0 THEN 1 ELSE 0 END) as wins,
        ROUND(100.0 * SUM(CASE WHEN profit_usdt > 0 THEN 1 ELSE 0 END)::numeric / COUNT(*), 1) as wr_pct,
        ROUND(AVG(profit_usdt)::numeric, 2) as avg_pnl,
        ROUND(SUM(profit_usdt)::numeric, 2) as total_pnl
    FROM trade_results
    WHERE exit_time > TIMESTAMP '2026-06-07 00:00:00'
    GROUP BY symbol
    HAVING COUNT(*) >= 3
    ORDER BY total_pnl DESC
    """
    return await Database.fetch(query)


async def main():
    await Database.connect()

    print("\n" + "="*80)
    print("CYCLE 22 ANALYSIS — 2026-06-14")
    print("="*80)

    # Overall stats
    trades_14d = await get_recent_trades(14)
    trades_all = await get_all_trades_since_freeze()

    print(f"\n📊 OVERALL STATS")
    print(f"  Last 14 days: {len(trades_14d)} trades")
    print(f"  Since freeze lift (2026-06-07): {len(trades_all)} trades")

    if trades_all:
        wins = sum(1 for t in trades_all if t['result'] == 'WIN')
        total_pnl = sum(float(t['profit_usdt'] or 0) for t in trades_all)
        avg_pnl = total_pnl / len(trades_all)
        wr = 100.0 * wins / len(trades_all)
        expectancy = total_pnl / len(trades_all)

        print(f"  Win Rate: {wr:.1f}% ({wins}/{len(trades_all)})")
        print(f"  Total P&L: ${total_pnl:.2f}")
        print(f"  Avg P&L: ${avg_pnl:.2f}")
        print(f"  Expectancy: ${expectancy:.2f}/trade")

    # Stop impact analysis
    print(f"\n🛑 STOP HIT IMPACT")
    stop_impact = await analyze_stop_impact()
    for row in stop_impact:
        sl_type = "SL HIT" if row['stop_hit'] else "REACHED TARGET"
        wr = 100.0 * row['wins'] / row['count'] if row['count'] > 0 else 0
        print(f"  {sl_type}: {row['count']} trades, WR={wr:.1f}%, Avg=${row['avg_pnl']}, Total=${row['total_pnl']}")

    # Target hit level
    print(f"\n🎯 TARGET LEVEL IMPACT")
    target_impact = await analyze_target_hit_impact()
    for row in target_impact:
        target_name = f"T{row['target_reached']}" if row['target_reached'] else "NO TARGET"
        wr = 100.0 * row['wins'] / row['count'] if row['count'] > 0 else 0
        print(f"  {target_name}: {row['count']} trades, WR={wr:.1f}%, Avg=${row['avg_pnl']}, Total=${row['total_pnl']}")

    # Top/worst symbols
    print(f"\n📈 BY SYMBOL (≥3 trades)")
    symbols = await analyze_by_symbol()
    print(f"  Top performers:")
    for row in symbols[:5]:
        print(f"    {row['symbol']}: {row['trades']} trades, WR={row['wr_pct']}%, Total=${row['total_pnl']}")

    print(f"  Worst performers:")
    for row in reversed(symbols[-5:]):
        print(f"    {row['symbol']}: {row['trades']} trades, WR={row['wr_pct']}%, Total=${row['total_pnl']}")

    # Research paths readiness
    print(f"\n🔬 RESEARCH PATHS READINESS")
    print(f"  Path A (SMC Advanced): Ready — historical data available")
    print(f"  Path B (Wide R:R): Ready — can retest baseline vs wider targets")
    print(f"  Prerequisite: SMC/R:R parts exhausted per cycle 21")
    print(f"  Decision: Limited to monitoring + research reconfirmation")

    print("\n" + "="*80 + "\n")

    await Database.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
