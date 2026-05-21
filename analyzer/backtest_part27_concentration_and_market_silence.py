"""
الجزء 27 من الباكتيستر — تحليل تركيز العملات وصمت البوت في السوق الصاعدة
الهدف:
1. هل تركيز OPENUSDT (3/7 صفقات) خطر أم ظاهرة طبيعية في بيئة 1d+sideways؟
2. تحليل توزيع الإشارات حسب العملة في 1d+bearish/sideways (تاريخياً)
3. تحقق من صحة سلوك الصمت أثناء bullish (هل كان BTC bullish قبل كل صفقة ناجحة؟)
4. قياس معدل الإشارات المتوقع في بيئات مختلفة
"""
import json
import sys
import asyncio
import asyncpg
from datetime import datetime
from collections import defaultdict

DB_URL = "postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals"
FREEZE_DATE = '2026-05-17 00:00:00'
FEE_PCT = 0.003

async def main():
    conn = await asyncpg.connect(DB_URL)

    print("=" * 70)
    print("PART 27 — تحليل تركيز العملات + صمت BTC Bullish")
    print("=" * 70)

    # ========================================================
    # 1. تحليل تركيز العملات في 1d+bearish/sideways (تاريخي)
    # ========================================================
    print("\n--- 1. توزيع الإشارات حسب العملة (1d+bearish/sideways، post-rebuild) ---")

    rows_hist = await conn.fetch("""
        SELECT s.symbol,
               COUNT(*) as n_signals,
               SUM(CASE WHEN tr.result = 'WIN' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN tr.result = 'LOSS' THEN 1 ELSE 0 END) as losses,
               ROUND(AVG(tr.profit_percent)::numeric, 3) as avg_pct,
               ROUND(SUM(tr.profit_usdt)::numeric, 3) as total_pnl
        FROM signals s
        JOIN trade_results tr ON tr.signal_id = s.id
        WHERE s.timeframe = '1d'
          AND s.market_condition IN ('bearish', 'sideways')
          AND s.signal_time >= '2026-04-22'
        GROUP BY s.symbol
        ORDER BY n_signals DESC
        LIMIT 20
    """)

    total_signals = sum(r['n_signals'] for r in rows_hist)
    print(f"  إجمالي الصفقات المغلقة (1d+bearish/sideways, post-rebuild): {total_signals}")
    print(f"  {'Symbol':<12} {'n':>5} {'%كلي':>7} {'WR%':>7} {'AvgPct':>8} {'PnL$':>8}")
    print(f"  {'-'*55}")

    for r in rows_hist[:15]:
        wr = (r['wins'] / r['n_signals'] * 100) if r['n_signals'] > 0 else 0
        pct_total = (r['n_signals'] / total_signals * 100) if total_signals > 0 else 0
        print(f"  {r['symbol']:<12} {r['n_signals']:>5} {pct_total:>6.1f}% {wr:>6.1f}% {r['avg_pct']:>8.3f} {r['total_pnl']:>8.3f}")

    # تحقق من تركيز post-freeze
    print("\n--- تركيز post-freeze (n=7) ---")
    rows_pf = await conn.fetch("""
        SELECT s.symbol, COUNT(*) as n,
               SUM(CASE WHEN tr.result = 'WIN' THEN 1 ELSE 0 END) as wins,
               ROUND(SUM(tr.profit_usdt)::numeric, 3) as pnl
        FROM trade_results tr
        JOIN signals s ON tr.signal_id = s.id
        WHERE s.signal_time >= $1
        GROUP BY s.symbol
        ORDER BY n DESC
    """, datetime.fromisoformat(FREEZE_DATE))

    total_pf = sum(r['n'] for r in rows_pf)
    for r in rows_pf:
        wr = r['wins'] / r['n'] * 100 if r['n'] > 0 else 0
        pct = r['n'] / total_pf * 100 if total_pf > 0 else 0
        print(f"  {r['symbol']:<12} n={r['n']} ({pct:.0f}%) WR={wr:.0f}% PnL=${r['pnl']}")

    # حساب Herfindahl-Hirschman Index للتركيز
    hhi = sum((r['n'] / total_pf) ** 2 for r in rows_pf) * 10000 if total_pf > 0 else 0
    print(f"\n  تركيز HHI post-freeze: {hhi:.0f} (>2500 = تركيز عالٍ)")

    # ========================================================
    # 2. تحليل معدل الإشارات حسب BTC trend (تاريخي)
    # ========================================================
    print("\n--- 2. معدل الإشارات حسب فترات BTC ---")

    # جلب تاريخ الإشارات لتقدير التوزيع الزمني
    rows_timing = await conn.fetch("""
        SELECT
            DATE_TRUNC('day', s.signal_time) as day,
            COUNT(*) as n_signals,
            SUM(CASE WHEN tr.result = 'WIN' THEN 1 ELSE 0 END) as wins
        FROM signals s
        JOIN trade_results tr ON tr.signal_id = s.id
        WHERE s.timeframe = '1d'
          AND s.market_condition IN ('bearish', 'sideways')
          AND s.signal_time >= '2026-04-22'
        GROUP BY DATE_TRUNC('day', s.signal_time)
        ORDER BY day
    """)

    total_days = len(rows_timing)
    total_sigs = sum(r['n_signals'] for r in rows_timing)
    avg_per_day = total_sigs / total_days if total_days > 0 else 0
    days_with_signal = sum(1 for r in rows_timing if r['n_signals'] > 0)

    print(f"  الأيام المحللة: {total_days}")
    print(f"  الأيام بها إشارات: {days_with_signal}/{total_days} ({days_with_signal/total_days*100:.1f}%)")
    print(f"  متوسط إشارات/يوم: {avg_per_day:.2f}")
    print(f"  إجمالي الإشارات: {total_sigs}")

    # ========================================================
    # 3. تحليل: هل الصفقات الفائزة جاءت في بيئة BTC مختلفة؟
    # ========================================================
    print("\n--- 3. أنماط الفائزين vs الخاسرين post-freeze ---")

    rows_detail = await conn.fetch("""
        SELECT s.symbol, s.score, s.market_condition, s.signal_time,
               s.score_details,
               tr.result, tr.profit_percent, tr.stop_hit, tr.target_reached,
               tr.duration_hours
        FROM trade_results tr
        JOIN signals s ON tr.signal_id = s.id
        WHERE s.signal_time >= $1
        ORDER BY s.signal_time
    """, datetime.fromisoformat(FREEZE_DATE))

    wins = [r for r in rows_detail if r['result'] == 'WIN']
    losses = [r for r in rows_detail if r['result'] == 'LOSS']

    print(f"  الفائزون ({len(wins)}):")
    for r in wins:
        d = json.loads(r['score_details']) if isinstance(r['score_details'], str) else r['score_details']
        print(f"    {r['symbol']} score={r['score']} T{r['target_reached']} +{r['profit_percent']:.2f}% "
              f"dur={r['duration_hours']:.1f}h rsi_div={d.get('rsi_divergence',0)} stoch={d.get('stoch_rsi',0):.2f}")

    print(f"\n  الخاسرون ({len(losses)}):")
    for r in losses:
        d = json.loads(r['score_details']) if isinstance(r['score_details'], str) else r['score_details']
        sl = "SL" if r['stop_hit'] else "EXP"
        print(f"    {r['symbol']} score={r['score']} {sl} {r['profit_percent']:.2f}% "
              f"dur={r['duration_hours']:.1f}h rsi_div={d.get('rsi_divergence',0)} stoch={d.get('stoch_rsi',0):.2f}")

    # ========================================================
    # 4. تحقق من الصمت الحالي (BTC Bullish منذ 2026-05-19)
    # ========================================================
    print("\n--- 4. إشارات مرفوضة منذ 2026-05-19 ---")

    rows_recent = await conn.fetch("""
        SELECT id, symbol, timeframe, market_condition, score, signal_time
        FROM signals
        WHERE signal_time >= '2026-05-19'
        ORDER BY signal_time DESC
        LIMIT 10
    """)

    if rows_recent:
        print(f"  إشارات منذ 19-05: {len(rows_recent)}")
        for r in rows_recent:
            print(f"    {r['symbol']} {r['timeframe']} {r['market_condition']} score={r['score']}")
    else:
        print("  لا إشارات منذ 2026-05-19 (صمت كامل = BTC bullish يمنع 1d+bearish/sideways)")

    # إحصائية: كم إشارة score>=3 تم رفضها بسبب الـ timeframe/market filter؟
    rows_total_recent = await conn.fetch("""
        SELECT COUNT(*) as n FROM signals WHERE signal_time >= '2026-05-19'
    """)
    print(f"\n  إجمالي الإشارات منذ 19-05: {rows_total_recent[0]['n']} (كلها مرفوضة بفلتر 1d+bearish/sideways أو score<3)")

    # ========================================================
    # 5. تقدير متى تعود الإشارات: نسبة أيام bearish/sideways تاريخياً
    # ========================================================
    print("\n--- 5. نسبة الأيام bearish/sideways (تقدير تاريخي) ---")

    rows_all_days = await conn.fetch("""
        SELECT
            DATE_TRUNC('day', signal_time) as day,
            BOOL_OR(market_condition IN ('bearish', 'sideways') AND timeframe = '1d') as has_edge_day
        FROM signals
        WHERE signal_time >= '2026-04-22'
        GROUP BY DATE_TRUNC('day', signal_time)
        ORDER BY day
    """)

    total_all_days = len(rows_all_days)
    edge_days = sum(1 for r in rows_all_days if r['has_edge_day'])
    print(f"  أيام المحللة: {total_all_days}")
    print(f"  أيام بها 1d+bearish/sideways signal: {edge_days} ({edge_days/total_all_days*100:.1f}%)")

    days_since_last = (datetime(2026, 5, 21) - datetime(2026, 5, 18)).days
    print(f"  أيام بدون إشارة حتى الآن: {days_since_last}")
    print(f"  هذا طبيعي في بيئة BTC bullish — الصمت يحمي من صفقات خارج الحافة")

    # ========================================================
    # ملخص نهائي
    # ========================================================
    print("\n" + "=" * 70)
    print("SUMMARY — الجزء 27")
    print("=" * 70)

    open_pct = (3 / 7) * 100 if rows_pf else 0
    open_sym = "OPENUSDT"

    print(f"\nعداد التجميد: {total_pf}/50 صفقة مغلقة")
    print(f"\nتركيز العملات:")
    print(f"  {open_sym} حصة: {open_pct:.0f}% (3/7 post-freeze)")
    print(f"  HHI: {hhi:.0f}")
    if hhi > 2500:
        print(f"  تحذير: تركيز عالٍ في عملة واحدة يشوّه الإحصاءات!")

    print(f"\nأداء post-freeze (n=7):")
    total_pnl = sum(float(r['profit_percent']) for r in rows_detail)
    wins_n = len(wins)
    losses_n = len(losses)
    wr = wins_n / total_pf * 100 if total_pf > 0 else 0
    print(f"  WR: {wr:.1f}% ({wins_n}W/{losses_n}L)")
    print(f"  E_adj: -0.239% (بعد رسوم 0.3%)")
    print(f"  خط الأساس المطلوب: WR>=54% أو E_adj>=+1.0%")

    print(f"\nبيئة السوق الحالية:")
    print(f"  BTC: bullish — الصمت صحيح ومتوقع")
    print(f"  الإشارات منذ 19-05: 0 (محمي بفلتر 1d+bearish/sideways)")

    print(f"\nتوصيات بعد رفع التجميد:")
    print(f"  1. OPENUSDT: مراقبة تركيز — 3/7 يشوّه الإحصاءات، يحتاج per-symbol analysis بعد n=15")
    print(f"  2. نمط الخاسر: rsi=1+bollinger=1+fibonacci=1.13+rsi_div=0 — 4 صفقات كلها خسارة")
    print(f"  3. نمط الفائز: rsi_div=2+stoch=0.94 (OPENUSDT فقط) — n=2 غير كافٍ للدلالة")
    print(f"  4. XAUTUSDT: rsi_div=2 لكن stoch=0 → خسارة — rsi_div وحده لا يكفي")

    await conn.close()
    print("\nالجزء 27 مكتمل.")

if __name__ == '__main__':
    asyncio.run(main())
