#!/usr/bin/env python3
import asyncio
import asyncpg
from datetime import datetime

async def main():
    pool = await asyncpg.create_pool('postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals')
    async with pool.acquire() as conn:
        freeze_date = datetime(2026, 5, 17)

        # صفقات منذ التجميد
        result = await conn.fetchrow("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
                   ROUND(SUM(profit_usdt), 2) as total_profit,
                   ROUND(AVG(profit_usdt), 2) as avg_profit
            FROM trade_results WHERE exit_time >= $1
        """, freeze_date)

        print(f"✓ صفقات منذ التجميد: {result['total']}/50")
        if result['total'] > 0:
            wr = (result['wins'] / result['total']) * 100
            print(f"  WR: {wr:.1f}%, PnL: ${result['total_profit']}, Avg: ${result['avg_profit']}")

        # صفقات مفتوحة
        open_trades = await conn.fetch("SELECT symbol, highest_target_hit FROM active_trades WHERE status='open'")
        print(f"\n✓ صفقات مفتوحة: {len(open_trades)}")
        for t in open_trades:
            print(f"  {t['symbol']}: T{t['highest_target_hit']}")

        # إعدادات
        min_score = await conn.fetchval(
            "SELECT value FROM optimizer_settings WHERE key='min_score_to_signal' LIMIT 1"
        )
        rsi_div = await conn.fetchval(
            "SELECT weight FROM indicator_weights WHERE indicator_name='rsi_divergence' AND market_condition='sideways'"
        )

        print(f"\n✓ الإعدادات:")
        print(f"  min_score_to_signal: {min_score}")
        print(f"  rsi_divergence/sideways: {rsi_div}")

    await pool.close()

asyncio.run(main())
