#!/usr/bin/env python3
"""
Backtest Part 31 — Bearish vs Sideways + MEGAUSDT scan pattern
هدف: هل الإعداد الحالي يميّز bearish عن sideways؟ ولماذا MEGAUSDT لا تُفتح؟
"""
import asyncio
import asyncpg
import os
import json
import sys

DB_URL = os.getenv('DATABASE_URL', 'postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals')

async def run():
    conn = await asyncpg.connect(DB_URL)
    print("=" * 60)
    print("PART 31 — Bearish vs Sideways + Filtered Signals Analysis")
    print("=" * 60)

    # 1. Breakdown by market_condition post-freeze
    rows = await conn.fetch("""
        SELECT s.market_condition,
               COUNT(tr.id) as closed,
               SUM(CASE WHEN tr.result='WIN' THEN 1 ELSE 0 END) as wins,
               ROUND(AVG(tr.profit_percent)::numeric, 3) as avg_pnl,
               ROUND(SUM(tr.profit_usdt)::numeric, 2) as total_pnl
        FROM signals s
        JOIN trade_results tr ON s.id = tr.signal_id
        WHERE s.signal_time >= '2026-05-17'
        GROUP BY s.market_condition
    """)
    print("\n--- أداء حسب market_condition post-freeze ---")
    for r in rows:
        wr = r['wins']*100.0/r['closed'] if r['closed'] else 0
        print(f"  {r['market_condition']:10s}: n={r['closed']}, WR={wr:.0f}%, avg_pnl={r['avg_pnl']}%, total={r['total_pnl']}$")

    # 2. Score = 3 vs 4 vs 5
    rows = await conn.fetch("""
        SELECT s.score,
               COUNT(tr.id) as closed,
               SUM(CASE WHEN tr.result='WIN' THEN 1 ELSE 0 END) as wins,
               ROUND(AVG(tr.profit_percent)::numeric, 3) as avg_pnl
        FROM signals s
        JOIN trade_results tr ON s.id = tr.signal_id
        WHERE s.signal_time >= '2026-05-17'
        GROUP BY s.score ORDER BY s.score
    """)
    print("\n--- أداء حسب score post-freeze ---")
    for r in rows:
        wr = r['wins']*100.0/r['closed'] if r['closed'] else 0
        print(f"  score={r['score']}: n={r['closed']}, WR={wr:.0f}%, avg_pnl={r['avg_pnl']}%")

    # 3. rsi_div threshold
    rows = await conn.fetch("""
        SELECT 
          CASE WHEN (s.score_details->>'rsi_divergence')::float > 0 THEN 'rsi_div>0' ELSE 'rsi_div=0' END as div_group,
          COUNT(tr.id) as closed,
          SUM(CASE WHEN tr.result='WIN' THEN 1 ELSE 0 END) as wins,
          ROUND(AVG(tr.profit_percent)::numeric, 3) as avg_pnl,
          ROUND(SUM(tr.profit_usdt)::numeric, 2) as total_pnl
        FROM signals s
        JOIN trade_results tr ON s.id = tr.signal_id
        WHERE s.signal_time >= '2026-05-17' AND s.score_details IS NOT NULL
        GROUP BY div_group
    """)
    print("\n--- أداء حسب rsi_divergence presence (تأكيد رابع) ---")
    for r in rows:
        wr = r['wins']*100.0/r['closed'] if r['closed'] else 0
        print(f"  {r['div_group']}: n={r['closed']}, WR={wr:.0f}%, avg_pnl={r['avg_pnl']}%, total={r['total_pnl']}$")

    # 4. MEGAUSDT — لماذا لا تُفتح صفقة؟
    rows = await conn.fetch("""
        SELECT s.symbol, s.timeframe, s.market_condition, s.score, s.score_details, s.signal_time, 
               s.claude_approved, s.telegram_sent
        FROM signals s
        WHERE s.symbol='MEGAUSDT'
        ORDER BY s.signal_time DESC
        LIMIT 5
    """)
    print("\n--- MEGAUSDT إشارات تاريخية ---")
    if rows:
        for r in rows:
            print(f"  [{r['signal_time'].strftime('%m-%d %H:%M')}] tf={r['timeframe']} {r['market_condition']} score={r['score']} approved={r['claude_approved']}")
    else:
        print("  لا إشارات تاريخية — MEGAUSDT لم تجتز فلتر min_score أبداً في signals")
        print("  (تظهر في scan_candidates لكن score < min_score_to_signal)")

    # 5. كم مرة MEGAUSDT ظهرت كأعلى نقاط بدون إشارة؟
    rows2 = await conn.fetch("""
        SELECT ar.symbol, COUNT(*) as scan_count, MAX(ar.scan_time) as last_seen
        FROM scan_candidates ar
        WHERE ar.symbol = 'MEGAUSDT'
        AND ar.scan_time >= '2026-05-17'
        GROUP BY ar.symbol
    """)
    if rows2:
        for r in rows2:
            print(f"  scan_candidates: MEGAUSDT مسحت {r['scan_count']} مرة، آخرها {r['last_seen']}")
    else:
        print("  MEGAUSDT غائبة من scan_candidates أيضاً")

    # 6. BTC trend سياق الخسائر vs الأرباح
    print("\n--- سياق BTC trend في الصفقات ---")
    rows = await conn.fetch("""
        SELECT s.symbol, s.market_condition, s.score,
               (s.score_details->>'rsi_divergence')::float as rsi_div,
               tr.result, tr.profit_percent,
               tr.duration_hours
        FROM signals s
        JOIN trade_results tr ON s.id = tr.signal_id
        WHERE s.signal_time >= '2026-05-17'
        ORDER BY tr.profit_percent DESC
    """)
    print(f"  {'Symbol':12s} {'MC':10s} {'Sc':3s} {'RsiDiv':6s} {'Result':5s} {'P%':8s} {'Dur':6s}")
    for r in rows:
        print(f"  {r['symbol']:12s} {r['market_condition']:10s} {r['score']:3d} {(r['rsi_div'] or 0):6.2f} {r['result']:5s} {float(r['profit_percent']):8.2f}% {float(r['duration_hours']):6.1f}h")

    # 7. Benchmark: الربح المطلوب لـ WR=54%
    print("\n--- تشخيص الأداء الحالي ---")
    target_wr = 54.0
    current_wr = 22.2
    n_remaining = 50 - 9
    n_wins_needed = int(target_wr/100 * 50) - 2
    print(f"  الهدف: WR={target_wr}% (خط أساس المخطط القديم)")
    print(f"  الحالي: WR={current_wr}% (2 فوز من 9)")
    print(f"  مطلوب في الـ 41 المتبقية: {n_wins_needed} فوز ({n_wins_needed/n_remaining*100:.0f}%) للوصول لـ WR=54%")
    print(f"  واقعي (WR=40%): {int(0.4*n_remaining)} فوز في 41 → إجمالي {2+int(0.4*n_remaining)}/50 = WR={int((2+int(0.4*n_remaining))/50*100)}%")

    print("\n" + "=" * 60)
    print("الجزء 31 مكتمل.")
    await conn.close()

asyncio.run(run())
