#!/usr/bin/env python3
"""Check stoch_rsi filter OOS performance for cycle 21"""
import asyncio, sys, json
sys.path.insert(0, '/app')
from shared.database import Database

async def main():
    await Database.connect()
    rows = await Database.fetch('''
        SELECT tr.result, tr.profit_usdt, s.score, s.score_details, tr.exit_time
        FROM trade_results tr
        JOIN signals s ON tr.signal_id = s.id
        WHERE tr.exit_time >= '2026-06-07'
        ORDER BY tr.exit_time
    ''')

    stoch_high = []
    stoch_low = []
    rsi_div_combos = []
    no_div = []

    for r in rows:
        sd = r['score_details']
        if isinstance(sd, str):
            try:
                sd = json.loads(sd)
            except Exception:
                sd = {}
        elif sd is None:
            sd = {}

        stoch = float(sd.get('stoch_rsi', 0) or 0)
        rsi_div = float(sd.get('rsi_divergence', 0) or 0)
        pnl = float(r['profit_usdt'] or 0)
        win = 1 if r['result'] == 'WIN' else 0

        if stoch >= 0.6:
            stoch_high.append((win, pnl))
        else:
            stoch_low.append((win, pnl))

        if stoch >= 0.6 and rsi_div > 0:
            rsi_div_combos.append((win, pnl))
        else:
            no_div.append((win, pnl))

    def report(name, data):
        if not data:
            print(f'{name}: n=0')
            return
        n = len(data)
        w = sum(x[0] for x in data)
        e = sum(x[1] for x in data) / n
        print(f'{name}: n={n} WR={w/n*100:.1f}% E/trade=${e:.3f}')

    print("=== Post-refreeze OOS (2026-06-07 to now) ===")
    report('ALL               ', [(1 if r['result']=='WIN' else 0, float(r['profit_usdt'] or 0)) for r in rows])
    report('stoch_rsi>=0.6    ', stoch_high)
    report('stoch_rsi<0.6     ', stoch_low)
    report('stoch>=0.6+div>0  ', rsi_div_combos)
    report('rest (no combo)   ', no_div)

    await Database.disconnect()

asyncio.run(main())
