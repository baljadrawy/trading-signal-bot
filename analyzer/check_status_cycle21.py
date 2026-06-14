#!/usr/bin/env python3
"""Check current status for cycle 21"""
import asyncio, sys
sys.path.insert(0, '/app')
from shared.database import Database

async def main():
    await Database.connect()
    rows = await Database.fetch("""
        SELECT tr.result, tr.profit_percent, tr.profit_usdt,
               s.score, s.timeframe, s.market_condition,
               tr.stop_hit, tr.target_reached, tr.exit_time
        FROM trade_results tr
        JOIN signals s ON tr.signal_id = s.id
        WHERE tr.exit_time >= '2026-06-07'
        ORDER BY tr.exit_time
    """)
    n = len(rows)
    if n == 0:
        print("No trades since 2026-06-07")
        await Database.disconnect()
        return

    wins = sum(1 for r in rows if r['result'] == 'WIN')
    total_pnl = sum(float(r['profit_usdt'] or 0) for r in rows)
    print(f"Post-refreeze (since 2026-06-07): n={n}, WR={wins/n*100:.1f}%, total_pnl=${total_pnl:.2f}")
    print(f"E/trade=${total_pnl/n:.3f}")
    print()
    print("Last 15 trades:")
    for r in rows[-15:]:
        print(f"  {str(r['exit_time'])[:10]} {r['result']:4s} pnl=${float(r['profit_usdt'] or 0):.2f}"
              f" {r['timeframe']} {r['market_condition']} score={r['score']} t={r['target_reached']}")

    # Cohort: 1d + bearish/sideways + score=3
    cohort = [r for r in rows if r['timeframe'] == '1d'
              and r['market_condition'] in ('bearish', 'sideways')
              and float(r['score'] or 0) >= 3.0]
    print(f"\n1d+bearish/sideways+score>=3 cohort: n={len(cohort)}")
    if cohort:
        cw = sum(1 for r in cohort if r['result'] == 'WIN')
        cpnl = sum(float(r['profit_usdt'] or 0) for r in cohort)
        print(f"  WR={cw/len(cohort)*100:.1f}%, pnl=${cpnl:.2f}")

    await Database.disconnect()

asyncio.run(main())
