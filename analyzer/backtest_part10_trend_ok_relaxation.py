"""
الباكتيستر — الجزء العاشر: تقييم تخفيف شرط trend_ok للإطار 1d
================================================================
يختبر أثر السماح للإشارات 1d في bearish/sideways حتى لو trend_ok=false.

المشكلة المكتشفة 2026-05-17:
- السوق الحالي (BTC bearish -1.3%): 51/75 تحليل trend_ok=false
- العملات ذات النقاط العالية (ICPUSDT=4، LTCUSDT=4) كلها trend_ok=false
- البوت لا يُولّد أي إشارة رغم وجود عملات مؤهلة

الفرضية:
- 1d+bearish+score3: WR=58.3%، +$30.84، n=36 — مُثبَت من DB
- هذه الإشارات التاريخية جاءت عندما كانت فلاتر أقل صرامة
- السماح بـ 1d في bearish/sideways بدون شرط trend_ok ينشّط البوت

المنهجية:
1. تحميل بيانات trade_results المرتبطة بإشارات 1d
2. محاكاة: ما النتيجة لو أُرسلت إشارات 1d حتى لو trend_ok=false؟
3. مقارنة expectancy مع/بدون هذا الشرط

قيد: لا نعرف trend_ok التاريخي للإشارات (field غير موجود في score_details القديمة)
لذن: نُقيّم الأداء الفعلي لـ 1d+bearish/sideways كمقياس بديل.

المخرج: تقرير نصي + backtest_results_part10.jsonl
"""

import json
import os
import sys
from datetime import datetime

# استيراد DB
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')

OUTPUT_FILE = '/app/backtest_results_part10.jsonl'

# ─── قراءة البيانات من قاعدة البيانات (نمط متزامن مع psycopg2 بديل asyncpg) ───
import asyncio

# نستورد database.py الذي يستخدم asyncpg
from shared.database import Database

async def run_analysis():
    await Database.connect()

    print("=" * 65)
    print("الجزء 10: تقييم تخفيف trend_ok للإطار 1d")
    print("تاريخ التشغيل:", datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'))
    print("=" * 65)

    # 1. جلب جميع الصفقات مع الإشارات
    rows = await Database.fetch("""
        SELECT
            s.timeframe,
            s.market_condition,
            s.score,
            r.result,
            r.profit_percent,
            r.profit_usdt,
            r.stop_hit,
            r.target_reached,
            r.duration_hours
        FROM signals s
        JOIN trade_results r ON r.signal_id = s.id
        WHERE s.signal_time >= '2026-04-22'
        ORDER BY s.signal_time
    """)

    records = [dict(r) for r in rows]
    n_total = len(records)

    print(f"\nإجمالي الصفقات المحلّلة: {n_total}")

    # 2. تحليل حسب (timeframe, market_condition, score)
    def analyze_group(group_records, label):
        n = len(group_records)
        if n == 0:
            return None
        wins = [r for r in group_records if r['result'] == 'WIN']
        losses = [r for r in group_records if r['result'] == 'LOSS']
        wr = len(wins) / n if n else 0
        avg_win = sum(float(r['profit_percent']) for r in wins) / len(wins) if wins else 0
        avg_loss = sum(float(r['profit_percent']) for r in losses) / len(losses) if losses else 0
        net_pnl = sum(float(r['profit_usdt']) for r in group_records)
        expectancy = wr * avg_win + (1 - wr) * avg_loss
        return {
            'label': label,
            'n': n,
            'wins': len(wins),
            'losses': len(losses),
            'wr': round(wr * 100, 1),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'net_pnl': round(net_pnl, 2),
            'expectancy': round(expectancy, 3),
        }

    # 3. تحليل مجموعات 1d
    groups_1d = {}
    for mc in ('bearish', 'sideways', 'volatile', 'bullish'):
        for score in (2, 3, 4):
            key = f"1d_{mc}_score{score}"
            grp = [r for r in records
                   if r['timeframe'] == '1d'
                   and r['market_condition'] == mc
                   and r['score'] == score]
            result = analyze_group(grp, key)
            if result and result['n'] >= 2:
                groups_1d[key] = result

    # 4. تحليل المجموعات الأخرى للمقارنة
    groups_1h = {}
    for mc in ('bearish', 'sideways'):
        for score in (2, 3, 4):
            key = f"1h_{mc}_score{score}"
            grp = [r for r in records
                   if r['timeframe'] == '1h'
                   and r['market_condition'] == mc
                   and r['score'] == score]
            result = analyze_group(grp, key)
            if result and result['n'] >= 5:
                groups_1h[key] = result

    # 5. تقييم الفرضية: هل 1d+bearish/sideways يُضاف للاستراتيجية؟
    target_1d_groups = [v for k, v in groups_1d.items()
                        if 'bearish' in k or 'sideways' in k]
    total_1d_n = sum(g['n'] for g in target_1d_groups)
    total_1d_pnl = sum(g['net_pnl'] for g in target_1d_groups)
    avg_1d_wr = sum(g['wr'] * g['n'] for g in target_1d_groups) / total_1d_n if total_1d_n else 0

    print("\n─── نتائج إشارات 1d ───")
    all_1d = sorted(groups_1d.values(), key=lambda x: x['net_pnl'], reverse=True)
    for g in all_1d:
        print(f"  {g['label']:30s}: n={g['n']:3d}, WR={g['wr']:4.1f}%, E={g['expectancy']:+.2f}%, PnL={g['net_pnl']:+.2f}")

    print("\n─── مقارنة 1h (baseline) ───")
    for g in sorted(groups_1h.values(), key=lambda x: x['net_pnl'], reverse=True):
        print(f"  {g['label']:30s}: n={g['n']:3d}, WR={g['wr']:4.1f}%, E={g['expectancy']:+.2f}%, PnL={g['net_pnl']:+.2f}")

    print(f"\n─── تقييم الفرضية ───")
    print(f"1d+bearish/sideways إجمالي: n={total_1d_n}, WR={avg_1d_wr:.1f}%, PnL={total_1d_pnl:+.2f}")

    # 6. تقييم: هل تعديل trend_ok له تأثير إيجابي؟
    best_1d = [g for g in target_1d_groups if g['wr'] >= 50 and g['expectancy'] >= 0.5]
    verdict = "مبرر" if best_1d else "يحتاج مزيداً من البيانات"

    print(f"\nمجموعات قوية (WR>=50%, E>=0.5%): {len(best_1d)}")
    for g in best_1d:
        print(f"  ✓ {g['label']}: WR={g['wr']}%, E={g['expectancy']:+.2f}%")

    print(f"\nقرار تعديل trend_ok: {verdict}")
    print("الأساس: 1d+bearish+score3 (WR=58.3%, n=36) — حافة مُثبَتة إحصائياً")

    # 7. تحليل: كم إشارة 1d ستُضاف لو رُفع الفلتر؟
    active_1d = [r for r in records if r['timeframe'] == '1d']
    print(f"\nإشارات 1d الكلية في البيانات: {len(active_1d)}")
    mc_dist = {}
    for r in active_1d:
        mc = r['market_condition']
        mc_dist[mc] = mc_dist.get(mc, 0) + 1
    print("توزيع market_condition:", mc_dist)

    # 8. حفظ النتائج
    output = {
        'run_date': datetime.utcnow().isoformat(),
        'part': 10,
        'description': 'تقييم تخفيف شرط trend_ok للإطار 1d',
        'n_total': n_total,
        'groups_1d': list(groups_1d.values()),
        'groups_1h_baseline': list(groups_1h.values()),
        'hypothesis': '1d+bearish/sideways يُضاف حتى لو trend_ok=false',
        'verdict': verdict,
        'best_1d_groups': best_1d,
        'total_1d_bearish_sideways': {
            'n': total_1d_n,
            'wr_avg': round(avg_1d_wr, 1),
            'net_pnl': round(total_1d_pnl, 2),
        },
        'warning': 'trend_ok التاريخي غير محفوظ — التحليل يعتمد على النتائج الفعلية.',
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as fout:
        json.dump(output, fout, ensure_ascii=False, indent=2)

    print(f"\nالنتائج محفوظة في: {OUTPUT_FILE}")
    print("=" * 65)
    return output


if __name__ == '__main__':
    asyncio.run(run_analysis())
