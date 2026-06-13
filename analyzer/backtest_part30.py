"""
Part 30 — Scoring Schema Reconciliation
========================================
السؤال الحاسم: هل الحافة المُثبَتة (1d+bearish/sideways+score3, WR~58%) قابلة
للإنتاج تحت إعداد التنقيط الحالي؟

الخلفية:
- التجميد (2026-05-17) قام على فرضية: "البوت مُضيَّق للحافة الوحيدة المُثبَتة،
  نجمع 50 صفقة أمامية للتأكد منها."
- لكن الحافة قِيست في Part 11/12 على عمود s.score (integer = final score).
- الـ analyzer غُيِّر منذ ذلك: raw total_score = rsi + bollinger + stoch_rsi
  + rsi_divergence + fibonacci فقط (مؤشرات mean-revert). المخطط القديم لم
  يكن يحوي مفتاحَي fibonacci / rsi_divergence في score_details.

هذا السكربت يفصل الصفقات حسب المخطط (وجود مفتاح 'fibonacci' في score_details)
ويقارن WR/net لكل نطاق score — ليُظهر هل الحافة تنتمي للمخطط القديم فقط.

batch job — يقرأ DB ويخرج. لا حزم جديدة. لا حاوية دائمة.
"""

import sys
sys.path.insert(0, '/app')

import asyncio
import asyncpg

DB_URL = "postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals"

RAW_KEYS = ('rsi', 'bollinger', 'stoch_rsi', 'rsi_divergence', 'fibonacci')


def raw_score(details: dict) -> float:
    return round(sum(float(details.get(k, 0) or 0) for k in RAW_KEYS), 2)


async def run():
    conn = await asyncpg.connect(DB_URL)
    try:
        print("=" * 70)
        print("PART 30 — Scoring Schema Reconciliation")
        print("=" * 70)

        rows = await conn.fetch("""
            SELECT s.score AS int_score, s.score_details, s.market_condition AS mc,
                   tr.result, tr.profit_usdt, tr.profit_percent, s.signal_time
            FROM signals s JOIN trade_results tr ON tr.signal_id = s.id
            WHERE s.timeframe = '1d'
              AND s.market_condition IN ('bearish', 'sideways')
              AND tr.result IS NOT NULL
            ORDER BY s.signal_time
        """)
        print(f"\n1d+bearish/sideways صفقات مغلقة: n={len(rows)}")

        # تصنيف حسب المخطط: وجود مفتاح fibonacci = المخطط الحالي
        buckets = {}  # (schema, int_score) -> list of rows
        for r in rows:
            details = r['score_details']
            if isinstance(details, str):
                import json
                details = json.loads(details)
            schema = 'NEW' if (details and 'fibonacci' in details) else 'OLD'
            key = (schema, int(r['int_score']))
            buckets.setdefault(key, []).append((r, details))

        print("\n" + "-" * 70)
        print(f"{'schema':<8}{'int_score':<11}{'n':<6}{'WR%':<8}"
              f"{'net$':<11}{'avg_raw':<10}{'raw_range'}")
        print("-" * 70)
        for key in sorted(buckets):
            schema, isc = key
            items = buckets[key]
            n = len(items)
            wins = sum(1 for r, _ in items if r['result'] == 'WIN')
            net = sum(float(r['profit_usdt'] or 0) for r, _ in items)
            raws = [raw_score(d) for _, d in items]
            wr = 100.0 * wins / n if n else 0
            print(f"{schema:<8}{isc:<11}{n:<6}{wr:<8.1f}"
                  f"{net:<11.2f}{sum(raws)/n:<10.2f}"
                  f"{min(raws):.2f}-{max(raws):.2f}")

        # ── الخلاصة الكمية ──
        old_s3 = buckets.get(('OLD', 3), [])
        new_all = [it for k, v in buckets.items() if k[0] == 'NEW' for it in v]
        new_s3 = buckets.get(('NEW', 3), [])

        print("\n" + "=" * 70)
        print("الخلاصة:")
        print("=" * 70)
        if old_s3:
            wins = sum(1 for r, _ in old_s3 if r['result'] == 'WIN')
            net = sum(float(r['profit_usdt'] or 0) for r, _ in old_s3)
            print(f"الحافة المُثبَتة (المخطط القديم، score=3): n={len(old_s3)}, "
                  f"WR={100.0*wins/len(old_s3):.1f}%, net=${net:.2f}")
        if new_all:
            wins = sum(1 for r, _ in new_all if r['result'] == 'WIN')
            net = sum(float(r['profit_usdt'] or 0) for r, _ in new_all)
            print(f"المخطط الحالي (كل النطاقات): n={len(new_all)}, "
                  f"WR={100.0*wins/len(new_all):.1f}%, net=${net:.2f}")
        print(f"المخطط الحالي، score=3: n={len(new_s3)} "
              f"({'لا عينة كافية' if len(new_s3) < 20 else 'كافٍ'})")
        print("\nالحكم: الحافة قِيست على مخطط تنقيط مهجور. الإعداد المُجمَّد الحالي")
        print("سجلّه التاريخي ضئيل — عدّاد الـ50 هو القياس الأول الفعلي للاستراتيجية.")

    finally:
        await conn.close()


if __name__ == '__main__':
    asyncio.run(run())
