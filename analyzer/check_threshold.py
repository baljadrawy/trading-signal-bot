#!/usr/bin/env python3
import asyncio
import asyncpg

async def main():
    pool = await asyncpg.create_pool('postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals')
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT value FROM optimizer_settings WHERE key='min_score_to_signal'")
        print(f"min_score_to_signal in DB: {val}")
    await pool.close()

asyncio.run(main())
