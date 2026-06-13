#!/usr/bin/env python3
import asyncio
import asyncpg
from datetime import datetime

async def main():
    pool = await asyncpg.create_pool('postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals')
    async with pool.acquire() as conn:
        # اخر صفقات مغلقة (آخر 5)
        trades = await conn.fetch("""
            SELECT symbol, result, profit_usdt, target_reached, stop_hit, exit_time, duration_hours
            FROM trade_results
            ORDER BY exit_time DESC LIMIT 5
        """)
        print("=== آخر 5 صفقات مغلقة ===")
        for t in trades:
            print(f"{t['symbol']}: {t['result']} {t['profit_usdt']:+.2f}$ (T{t['target_reached']}/{t['stop_hit']}) {int(t['duration_hours'])}h")

        # آخر إشارة (منذ 24 ساعة)
        signals = await conn.fetch("""
            SELECT symbol, market_condition, score, created_at
            FROM signals
            ORDER BY created_at DESC LIMIT 5
        """)
        print("\n=== آخر 5 إشارات ===")
        for s in signals:
            print(f"{s['symbol']}: {s['market_condition']} score={s['score']:.1f} @ {s['created_at'].strftime('%Y-%m-%d %H:%M')}")

        # التوزيع بعد التجميد
        freeze_date = datetime(2026, 5, 17)
        dist = await conn.fetch("""
            SELECT result, market_condition, COUNT(*) as count, ROUND(AVG(profit_usdt), 2) as avg_profit
            FROM trade_results
            WHERE exit_time >= $1
            GROUP BY result, market_condition
        """, freeze_date)

        print("\n=== توزيع الصفقات منذ التجميد (2026-05-17) ===")
        for d in dist:
            print(f"{d['result']} / {d['market_condition']}: {d['count']} trades, avg ${d['avg_profit']}")

    await pool.close()

asyncio.run(main())
