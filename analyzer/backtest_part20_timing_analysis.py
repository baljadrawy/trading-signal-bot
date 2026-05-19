"""
الجزء 20 من الباكتيستر — Timing Analysis (توقيت الإشارات 1d)
الهدف: تحليل تأثير ساعة الإشارة (UTC) على WR و E_adj لإشارات 1d+bearish/sideways+score=3
المنهج: تجميع بالساعة UTC، Permutation Test للساعات الواعدة/الضعيفة
قيود الخادم: معالجة كاملة في DB، لا حزم إضافية
"""
import json
import os
import sys
import asyncio
import asyncpg
import random
from collections import defaultdict

sys.path.insert(0, '/home/tradmin/trading-signal-bot')

FEE_PCT = 0.003
DB_URL = "postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals"
PERMUTATIONS = 1000
random.seed(42)


def permutation_test_wr(group_wins, group_n, total_wins, total_n, n_perms=PERMUTATIONS):
    """Permutation test: هل WR هذه المجموعة مختلف عن WR الكلي؟"""
    if group_n == 0 or total_n == 0:
        return 1.0
    observed_wr = group_wins / group_n
    # نولّد توزيع عشوائي للـ WR على نفس الحجم
    count_extreme = 0
    for _ in range(n_perms):
        simulated_wins = sum(1 for _ in range(group_n) if random.random() < total_wins/total_n)
        sim_wr = simulated_wins / group_n
        if sim_wr >= observed_wr:
            count_extreme += 1
    return count_extreme / n_perms


async def main():
    conn = await asyncpg.connect(DB_URL)

    # جلب إشارات 1d+bearish/sideways مغلقة مع ساعة الإشارة
    rows = await conn.fetch("""
        SELECT
            EXTRACT(HOUR FROM s.signal_time)::int as hour_utc,
            s.market_condition,
            s.score,
            tr.result,
            tr.profit_percent,
            tr.profit_usdt,
            tr.stop_hit,
            tr.target_reached,
            s.score_details
        FROM signals s
        JOIN trade_results tr ON tr.signal_id = s.id
        WHERE s.timeframe = '1d'
          AND s.market_condition IN ('bearish', 'sideways')
        ORDER BY s.signal_time
    """)

    await conn.close()

    print(f"\n{'='*70}")
    print("PART 20 — TIMING ANALYSIS (توقيت إشارات 1d)")
    print(f"{'='*70}")
    print(f"إجمالي الصفقات المحللة: {len(rows)}")

    # تجميع حسب الساعة
    hour_data = defaultdict(lambda: {'n': 0, 'wins': 0, 'pnl': [], 'pnl_usdt': 0.0})

    total_wins = 0
    total_n = 0

    for row in rows:
        h = row['hour_utc']
        result = row['result']
        pnl = float(row['profit_percent'])
        pnl_usdt = float(row['profit_usdt'])

        hour_data[h]['n'] += 1
        hour_data[h]['pnl'].append(pnl)
        hour_data[h]['pnl_usdt'] += pnl_usdt
        if result == 'WIN':
            hour_data[h]['wins'] += 1
            total_wins += 1
        total_n += 1

    overall_wr = total_wins / total_n * 100 if total_n > 0 else 0

    print(f"\nWR الكلي لـ 1d+bearish/sideways: {overall_wr:.1f}% ({total_wins}/{total_n})")
    print(f"\n{'─'*70}")
    print(f"{'ساعة UTC':>10} {'n':>5} {'WR%':>7} {'avg_pnl%':>10} {'total$':>9} {'p-val':>8}")
    print(f"{'─'*70}")

    # ساعات واعدة وضعيفة
    promising_hours = []
    weak_hours = []

    for h in sorted(hour_data.keys()):
        d = hour_data[h]
        n = d['n']
        wins = d['wins']
        wr = wins / n * 100 if n > 0 else 0
        avg_pnl = sum(d['pnl']) / n if n > 0 else 0
        total_pnl = d['pnl_usdt']

        # Permutation test فقط إذا n >= 5
        if n >= 5:
            p_val = permutation_test_wr(wins, n, total_wins, total_n)
            p_str = f"{p_val:.3f}"
            flag = " ***" if p_val < 0.05 else (" *" if p_val < 0.10 else "")

            if p_val < 0.05 and wr > overall_wr:
                promising_hours.append((h, n, wr, avg_pnl, total_pnl, p_val))
            elif p_val < 0.10 and wr < overall_wr:
                weak_hours.append((h, n, wr, avg_pnl, total_pnl, p_val))
        else:
            p_str = "n<5"
            flag = ""

        wr_bar = "+" if wr > overall_wr else "-"
        print(f"  {h:02d}:00 UTC   {n:5d}  {wr:6.1f}%  {avg_pnl:+9.2f}%  {total_pnl:+8.2f}$  {p_str}{flag}")

    # تحليل بالنهار (صباح/مساء UTC)
    print(f"\n{'─'*50}")
    print("تحليل فترات اليوم:")
    periods = {
        'فجر (00-05 UTC)': range(0, 6),
        'صباح (06-11 UTC)': range(6, 12),
        'ظهر (12-17 UTC)': range(12, 18),
        'مساء (18-23 UTC)': range(18, 24),
    }

    for period_name, hours in periods.items():
        period_n = sum(hour_data[h]['n'] for h in hours if h in hour_data)
        period_wins = sum(hour_data[h]['wins'] for h in hours if h in hour_data)
        period_pnl = sum(hour_data[h]['pnl_usdt'] for h in hours if h in hour_data)
        if period_n > 0:
            period_wr = period_wins / period_n * 100
            period_avg_pnl = sum(
                p for h in hours if h in hour_data for p in hour_data[h]['pnl']
            ) / period_n
        else:
            period_wr = 0
            period_avg_pnl = 0
        print(f"  {period_name}: n={period_n:4d}, WR={period_wr:.1f}%, avg_pnl={period_avg_pnl:+.2f}%, total=${period_pnl:+.2f}")

    # ساعات واعدة
    if promising_hours:
        print(f"\n{'─'*50}")
        print("الساعات الواعدة إحصائياً (p<0.05, WR > avg):")
        for h, n, wr, avg_pnl, total_pnl, p in promising_hours:
            print(f"  {h:02d}:00 UTC — n={n}, WR={wr:.1f}%, avg={avg_pnl:+.2f}%, p={p:.3f}")

    if weak_hours:
        print(f"\n{'─'*50}")
        print("الساعات الضعيفة إحصائياً (p<0.10, WR < avg):")
        for h, n, wr, avg_pnl, total_pnl, p in weak_hours:
            print(f"  {h:02d}:00 UTC — n={n}, WR={wr:.1f}%, avg={avg_pnl:+.2f}%, p={p:.3f}")

    # تحليل score=3 فقط (الحافة الحقيقية)
    print(f"\n{'─'*50}")
    print("تحليل score=3 فقط (الحافة المثبتة):")
    rows_score3 = await asyncpg.connect(DB_URL) if False else None

    # إعادة استخدام البيانات من rows
    conn2 = await asyncpg.connect(DB_URL)
    score3_rows = await conn2.fetch("""
        SELECT
            EXTRACT(HOUR FROM s.signal_time)::int as hour_utc,
            tr.result,
            tr.profit_percent,
            tr.profit_usdt
        FROM signals s
        JOIN trade_results tr ON tr.signal_id = s.id
        WHERE s.timeframe = '1d'
          AND s.market_condition IN ('bearish', 'sideways')
          AND s.score = 3
        ORDER BY s.signal_time
    """)
    await conn2.close()

    score3_hours = defaultdict(lambda: {'n': 0, 'wins': 0, 'pnl': 0.0})
    s3_total_n = 0
    s3_total_wins = 0
    for row in score3_rows:
        h = row['hour_utc']
        score3_hours[h]['n'] += 1
        score3_hours[h]['pnl'] += float(row['profit_usdt'])
        if row['result'] == 'WIN':
            score3_hours[h]['wins'] += 1
            s3_total_wins += 1
        s3_total_n += 1

    s3_wr = s3_total_wins / s3_total_n * 100 if s3_total_n > 0 else 0
    print(f"  WR score=3 الكلي: {s3_wr:.1f}% ({s3_total_wins}/{s3_total_n})")
    print(f"\n  {'ساعة':>8} {'n':>4} {'WR%':>7} {'total$':>9}")

    for h in sorted(score3_hours.keys()):
        d = score3_hours[h]
        n = d['n']
        wr = d['wins'] / n * 100 if n > 0 else 0
        print(f"  {h:02d}:00    {n:4d}  {wr:6.1f}%  {d['pnl']:+8.2f}$")

    # الخلاصة والتوصية
    print(f"\n{'─'*50}")
    print("الخلاصة:")
    print(f"  n الكلي 1d+bearish/sideways: {total_n}")
    print(f"  WR الكلي: {overall_wr:.1f}%")
    print(f"  أفضل فترة: انظر أعلاه")
    print(f"  ملاحظة: التجميد ساري — هذا تحليل فقط (لا تغيير حيّ)")
    print(f"\n{'='*70}")
    print("الجزء 20 مكتمل.")


if __name__ == '__main__':
    asyncio.run(main())
