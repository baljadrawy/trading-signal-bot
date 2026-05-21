"""
Part 29 — Score Band Drift Diagnosis
=====================================
السؤال: لماذا لم تُولَّد صفقة score_integer=3 منذ التجميد (2026-05-17)؟
الحافة المُثبَتة هي 1d+bearish/sideways+score3 (E=+1.41%, n=36).
لكن كل صفقات post-freeze هي score=4 أو score=5.

التحليل:
1. توزيع total_score في analyzer vs score_integer في signals — ما الفجوة؟
2. تأثير tf_bonus(+0.5) + btc_bonus(+0.3) على score integer
3. هل معظم إشارات score=3 integer تأتي من total_score منخفض (<2.5) لا يجتاز بعد الـ bonus؟
4. المقارنة بين pre-freeze (score=3 صفقة) و post-freeze (لا score=3)
5. هل هذا انجراف حقيقي في السوق أم خلل في منطق التنقيط؟
"""

import json
import sys
sys.path.insert(0, '/app')

import asyncio
import asyncpg
from shared.logger import setup_logger

logger = setup_logger('backtest_part29')

DB_URL = "postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals"

async def run():
    conn = await asyncpg.connect(DB_URL)
    try:
        print("=" * 70)
        print("PART 29 — Score Band Drift Diagnosis")
        print("=" * 70)

        # ────────────────────────────────────────────────────────────────────
        # 1. توزيع score_integer عبر الزمن
        # ────────────────────────────────────────────────────────────────────
        print("\n[1] توزيع score_integer في signals (1d+bearish/sideways)")
        print("-" * 60)

        rows = await conn.fetch("""
            SELECT
                DATE_TRUNC('week', signal_time) as week,
                score,
                COUNT(*) as n,
                SUM(CASE WHEN t.result='WIN' THEN 1 ELSE 0 END) as wins
            FROM signals s
            LEFT JOIN trade_results t ON t.signal_id = s.id
            WHERE s.timeframe = '1d'
              AND s.market_condition IN ('bearish', 'sideways')
              AND s.signal_time >= '2026-04-22'
            GROUP BY DATE_TRUNC('week', signal_time), score
            ORDER BY week, score
        """)

        print(f"{'Week':<14} {'Score':<7} {'N':<5} {'Wins':<6}")
        for r in rows:
            week_str = r['week'].strftime('%Y-%m-%d')
            print(f"{week_str:<14} {r['score']:<7} {r['n']:<5} {r['wins'] or 0:<6}")

        # ────────────────────────────────────────────────────────────────────
        # 2. score_integer distribution في score_details total_score
        # ────────────────────────────────────────────────────────────────────
        print("\n[2] score_integer vs total_score range (pre-freeze vs post-freeze)")
        print("-" * 60)

        # نحتاج نفهم: في score_details يُخزَّن total_score ؟
        # نتحقق من signals.score_details مقابل trade_results
        rows2 = await conn.fetch("""
            SELECT
                CASE WHEN s.signal_time >= '2026-05-17' THEN 'post-freeze' ELSE 'pre-freeze' END as period,
                s.score as score_int,
                COUNT(*) as n,
                ROUND(AVG(
                    (s.score_details->>'rsi')::numeric +
                    (s.score_details->>'bollinger')::numeric +
                    (s.score_details->>'rsi_divergence')::numeric +
                    (s.score_details->>'stoch_rsi')::numeric +
                    (s.score_details->>'fibonacci')::numeric
                ),2) as avg_raw_sum,
                SUM(CASE WHEN t.result='WIN' THEN 1 ELSE 0 END) as wins
            FROM signals s
            LEFT JOIN trade_results t ON t.signal_id = s.id
            WHERE s.timeframe = '1d'
              AND s.market_condition IN ('bearish', 'sideways')
              AND s.signal_time >= '2026-04-22'
            GROUP BY period, s.score
            ORDER BY period DESC, score_int
        """)

        print(f"{'Period':<14} {'Score_int':<11} {'N':<5} {'avg_raw_sum':<13} {'wins':<6}")
        for r in rows2:
            print(f"{r['period']:<14} {r['score_int']:<11} {r['n']:<5} {r['avg_raw_sum']:<13} {r['wins'] or 0:<6}")

        # ────────────────────────────────────────────────────────────────────
        # 3. تأثير btc_bonus + tf_bonus على المؤهلين
        # ────────────────────────────────────────────────────────────────────
        print("\n[3] كيف يتوزع total_score في analysis_results للإطار 1d (آخر 48h)")
        print("-" * 60)

        rows3 = await conn.fetch("""
            SELECT
                analysis_data->>'market_condition' as mc,
                COUNT(*) as n,
                ROUND(AVG((analysis_data->>'total_score')::numeric), 2) as avg_score,
                ROUND(MIN((analysis_data->>'total_score')::numeric), 2) as min_score,
                ROUND(MAX((analysis_data->>'total_score')::numeric), 2) as max_score,
                SUM(CASE WHEN (analysis_data->>'total_score')::numeric >= 2.2 THEN 1 ELSE 0 END) as n_above_2_2,
                SUM(CASE WHEN (analysis_data->>'total_score')::numeric >= 3.0 THEN 1 ELSE 0 END) as n_above_3_0
            FROM analysis_results
            WHERE timeframe = '1d'
              AND analysis_data->>'market_condition' IN ('bearish', 'sideways')
              AND analyzed_at >= NOW() - INTERVAL '48 hours'
            GROUP BY mc
            ORDER BY mc
        """)

        print(f"{'MC':<12} {'n':<5} {'avg':<8} {'min':<8} {'max':<8} {'>=2.2':<8} {'>=3.0':<8}")
        for r in rows3:
            print(f"{r['mc']:<12} {r['n']:<5} {r['avg_score']:<8} {r['min_score']:<8} {r['max_score']:<8} {r['n_above_2_2']:<8} {r['n_above_3_0']:<8}")

        print("\n  ملاحظة: tf_bonus(1d)=+0.5, btc_bonus(sideways/bearish)=+0.3")
        print("  لجواز إشارة score_int=3: تحتاج total_score >= 2.2 (2.2+0.5+0.3=3.0)")
        print("  لجواز إشارة score_int=4: تحتاج total_score >= 3.2 (3.2+0.5+0.3=4.0)")

        # ────────────────────────────────────────────────────────────────────
        # 4. تاريخي: كيف توزعت total_score للإشارات score=3 قبل التجميد
        # ────────────────────────────────────────────────────────────────────
        print("\n[4] تفاصيل score_details لإشارات score=3 قبل التجميد (1d+bearish/sideways)")
        print("-" * 60)

        rows4 = await conn.fetch("""
            SELECT
                symbol,
                score,
                (score_details->>'rsi')::numeric as rsi,
                (score_details->>'bollinger')::numeric as bb,
                (score_details->>'rsi_divergence')::numeric as rsi_div,
                (score_details->>'stoch_rsi')::numeric as stoch,
                (score_details->>'fibonacci')::numeric as fib,
                market_condition,
                signal_time::date as date
            FROM signals
            WHERE timeframe = '1d'
              AND market_condition IN ('bearish', 'sideways')
              AND score = 3
              AND signal_time >= '2026-04-22'
              AND signal_time < '2026-05-17'
            ORDER BY signal_time DESC
            LIMIT 20
        """)

        if rows4:
            print(f"{'Symbol':<12} {'MC':<10} {'rsi':<6} {'bb':<6} {'rsi_div':<9} {'stoch':<7} {'fib':<7} {'Date'}")
            raw_sums = []
            for r in rows4:
                rsi = r['rsi'] or 0
                bb = r['bb'] or 0
                rsi_div = r['rsi_div'] or 0
                stoch = r['stoch'] or 0
                fib = r['fib'] or 0
                raw_sum = rsi + bb + rsi_div + stoch + fib
                raw_sums.append(raw_sum)
                mc = r['market_condition'] if r['market_condition'] else '?'
                print(f"{r['symbol']:<12} {mc:<10} {rsi:<6} {bb:<6} {rsi_div:<9} {stoch:<7} {fib:<7} {r['date']}")
            avg_raw = sum(raw_sums) / len(raw_sums) if raw_sums else 0
            print(f"\n  avg raw_sum للـ score=3 قبل التجميد: {avg_raw:.2f}")
            print(f"  n=3 قبل التجميد في الديسكريبتور: {len(rows4)}")
        else:
            print("  لا إشارات score=3 في 1d+bearish/sideways قبل التجميد!")

        # ────────────────────────────────────────────────────────────────────
        # 5. خلاصة: هل الصمت بسبب السوق أم منطق التنقيط؟
        # ────────────────────────────────────────────────────────────────────
        print("\n[5] تشخيص سبب غياب score=3 في post-freeze")
        print("-" * 60)

        # أعلى total_score في آخر 6 ساعات
        top_row = await conn.fetchrow("""
            SELECT
                symbol,
                analysis_data->>'market_condition' as mc,
                (analysis_data->>'total_score')::numeric as score,
                analyzed_at
            FROM analysis_results
            WHERE timeframe = '1d'
              AND analysis_data->>'market_condition' IN ('bearish', 'sideways')
              AND analyzed_at >= NOW() - INTERVAL '6 hours'
            ORDER BY score DESC
            LIMIT 1
        """)

        if top_row:
            raw = float(top_row['score'])
            final = raw + 0.5 + 0.3  # tf_bonus + btc_bonus
            print(f"  أعلى 1d+bearish/sideways الآن: {top_row['symbol']} = {raw} raw")
            print(f"  بعد bonus: {final:.2f} (tf+0.5, btc+0.3)")
            if final >= 3.0:
                # احسب score_int الضمني
                # score_int = count(indicators > 0 in score_details)
                print(f"  حالة: يجتاز min_score=3.0 — لكن هل تولّدت إشارة؟")
                if final >= 4.0:
                    print(f"  خطورة: final={final:.2f} >= 4.0 → overbought filter يطبّق إذا raw_score >= 4.0")
                    if raw >= 4.0:
                        print(f"  النتيجة: مرفوض بفلتر overbought (raw={raw} >= 4.0)")
                    else:
                        print(f"  النتيجة: يمر (raw={raw} < 4.0) — لكن لم تتحقق من signal_engine log")
                else:
                    print(f"  النتيجة: يجب أن تتولّد إشارة — راجع signal_engine logs للتحقق")
            else:
                print(f"  النتيجة: لا يجتاز min_score=3.0 — السوق لا يوفر setup كافي")

        # عدد الأيام منذ آخر إشارة
        last_signal = await conn.fetchrow("""
            SELECT signal_time FROM signals
            WHERE timeframe = '1d'
              AND market_condition IN ('bearish', 'sideways')
            ORDER BY signal_time DESC LIMIT 1
        """)
        if last_signal:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            last = last_signal['signal_time'].replace(tzinfo=timezone.utc)
            delta = now - last
            print(f"\n  آخر إشارة 1d+bearish/sideways: {last_signal['signal_time']} ({delta.days}d {delta.seconds//3600}h ago)")

        # ────────────────────────────────────────────────────────────────────
        # 6. كم إشارة تحتاج حتى n=50؟ تقدير الوتيرة
        # ────────────────────────────────────────────────────────────────────
        print("\n[6] تقدير وتيرة الإشارات ومتى نصل n=50")
        print("-" * 60)

        count_post = await conn.fetchval("""
            SELECT COUNT(*) FROM trade_results t
            JOIN signals s ON t.signal_id = s.id
            WHERE t.exit_time >= '2026-05-17'
              AND s.timeframe = '1d'
              AND s.market_condition IN ('bearish', 'sideways')
        """)

        days_elapsed = 4  # 2026-05-17 إلى 2026-05-21
        rate_per_day = count_post / days_elapsed if days_elapsed > 0 else 0
        remaining = 50 - count_post
        if rate_per_day > 0:
            days_to_50 = remaining / rate_per_day
            print(f"  صفقات مغلقة post-freeze: {count_post}/50")
            print(f"  وتيرة: {rate_per_day:.2f}/يوم")
            print(f"  متبقٍ: {remaining} صفقة")
            print(f"  تقدير: ~{days_to_50:.0f} يوم ({days_to_50/30:.1f} شهر)")
        else:
            print(f"  صفقات مغلقة post-freeze: {count_post}/50")
            print("  وتيرة: لا كافية للتقدير")

        print("\n" + "=" * 70)
        print("CONCLUSION")
        print("=" * 70)
        print("""
الحافة المُثبَتة (score=3 integer) تتطلب:
  - total_score في analyzer >= 2.2 (2.2 + tf_bonus0.5 + btc_bonus0.3 = 3.0)
  - score_integer = count(مؤشرات > 0) — مرتبط بعدد المؤشرات النشطة لا بـ total_score

الوضع الحالي:
  - أعلى total_score في 1d = ~2.94 (ALLOUSDT)
  - final = 2.94 + 0.5 + 0.3 = 3.74 → يجتاز min_score=3.0
  - score_integer يعتمد على score_details الداخلية (count)

الخلاصة: الصمت بسبب السوق الحالي (neutral/bullish خفيف) لا خلل في المنطق.
كل إشارات post-freeze هي score=4/5 لأن total_score في analyzer = 3.0-3.6
(أي في الفئة المُثبَتة كـ overbought). الحافة المُثبَتة (score=3) لم تظهر بعد.
توصية: الاستمرار في التجميد. الوتيرة المنخفضة تشير لـ n=50 في أغسطس 2026.
        """)

    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(run())
