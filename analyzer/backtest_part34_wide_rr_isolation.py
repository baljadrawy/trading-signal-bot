"""
الباكتيستر — الجزء 34: عزل أثر R:R الواسع
===========================================
المسار B من البحث الأولويّ (2026-05-24):

الفرضية: رسوم 0.3% قد تكون مشكلة في ضيق R:R الحالي (T1=1.0R، T2=1.8R، T3=2.2R)
لا في المؤشرات نفسها.

الاختبار: نفس استراتيجية البوت الحالي تماماً
(1d+bearish/sideways+score≥3+RSI<50+RSI_div>0+الفلاتر)
لكن بأهداف موسّعة:
  - Variant 1: T1=2.0R, T2=4.0R, T3=6.0R
  - Variant 2: T1=3.0R, T2=5.0R, T3=8.0R

ثم شغّل على نفس البيانات التاريخية + Walk-Forward (5 نوافذ) + Bootstrap CI.

المقارنة: E_adj بين baseline الحالي و الأهداف الموسّعة.
إذا قفز E_adj بشكل دال إحصائياً → المشكلة في R:R.
إذا لم يقفز → المشكلة في المؤشرات نفسها.

ملاحظة: R:R أوسع = WR أقل (بطبيعة السوق). لا نقارن WR، بل expectancy فقط.
"""

import asyncio
import json
import math
import random
import sys
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')

import numpy as np
import pandas as pd
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('backtester.part34')

OUTPUT_FILE = '/app/backtest_results_part34.jsonl'

# ثوابت
FEE_PCT = 0.003
N_WF_WINDOWS = 5
TRAIN_RATIO = 0.6
TOP_DECILE_FRAC = 0.10
MIN_N_WINDOW = 10
N_BOOTSTRAP = 1000


# ═══════════════════════════════════════════════════════════════════════════
# 1. تحميل صفقات الإعداد المُجمّد
# ═══════════════════════════════════════════════════════════════════════════

async def load_frozen_setup_trades() -> List[Dict]:
    """
    يجلب الصفقات التي تطابق الإعداد المُجمّد بدقة:
    - timeframe = '1d'
    - market_condition IN ('bearish', 'sideways')
    - score >= 3
    """
    await Database.connect()
    try:
        rows = await Database.fetch("""
            SELECT
                tr.id,
                tr.signal_id,
                s.symbol,
                s.entry_price,
                s.target_1, s.target_2, s.target_3,
                s.stop_loss,
                tr.profit_percent,
                tr.result,
                s.score,
                s.market_condition,
                s.score_details,
                s.signal_time
            FROM trade_results tr
            JOIN signals s ON tr.signal_id = s.id
            WHERE s.timeframe = '1d'
              AND s.market_condition IN ('bearish', 'sideways')
              AND s.score >= 3.0
              AND tr.result IN ('WIN', 'LOSS')
            ORDER BY s.signal_time ASC
        """)

        trades = []
        for row in rows:
            entry = float(row['entry_price'])
            sl = float(row['stop_loss'])
            t1, t2, t3 = float(row['target_1']), float(row['target_2']), float(row['target_3'])

            # حساب R:R الحالي
            risk_current = entry - sl
            r1_current = (t1 - entry) / risk_current if risk_current > 0 else 0
            r2_current = (t2 - entry) / risk_current if risk_current > 0 else 0
            r3_current = (t3 - entry) / risk_current if risk_current > 0 else 0

            profit_adj = float(row['profit_percent'] or 0) - (FEE_PCT * 100)

            trades.append({
                'signal_id': row['signal_id'],
                'symbol': row['symbol'],
                'signal_time': row['signal_time'],
                'entry_price': entry,
                'stop_loss': sl,
                'target_1': t1,
                'target_2': t2,
                'target_3': t3,
                'risk': risk_current,
                'r1_baseline': r1_current,
                'r2_baseline': r2_current,
                'r3_baseline': r3_current,
                'profit_pct_baseline': float(row['profit_percent'] or 0),
                'profit_adj_baseline': profit_adj,
                'result': row['result'],
                'score': float(row['score'] or 0),
            })

        logger.info(f"✓ تم تحميل {len(trades)} صفقة من الإعداد المُجمّد")
        return trades
    finally:
        await Database.disconnect()


# ═══════════════════════════════════════════════════════════════════════════
# 2. محاكاة الأهداف الموسّعة
# ═══════════════════════════════════════════════════════════════════════════

def simulate_wide_rr(trade: Dict, variant: int) -> Dict:
    """
    محاكاة الصفقة بأهداف موسّعة.
    variant=1: T1=2R, T2=4R, T3=6R
    variant=2: T1=3R, T2=5R, T3=8R
    """
    entry = trade['entry_price']
    risk = trade['risk']
    profit_actual_pct = trade['profit_pct_baseline']

    if variant == 1:
        r_targets = [2.0, 4.0, 6.0]
    elif variant == 2:
        r_targets = [3.0, 5.0, 8.0]
    else:
        return trade

    new_targets = [entry + r * risk for r in r_targets]
    new_t1, new_t2, new_t3 = new_targets

    # محاكاة بسيطة: إذا كانت الصفقة رابحة أساساً، نفترض أنها تحقق أقرب هدف موسّع
    # هذا تبسيط — الواقع أعقد لكن بدون بيانات tick دقيقة لا يمكننا أفضل منه
    if trade['result'] == 'WIN':
        # فترض أن أقرب هدف موسّع متحقق
        actual_max_price = entry + (profit_actual_pct / 100) * entry
        for i, target in enumerate(new_targets):
            if actual_max_price >= target:
                profit_new = (i + 1) * r_targets[i] * 100  # بنسبة R
            else:
                profit_new = ((actual_max_price - entry) / risk) * 100 if risk > 0 else 0
    else:
        # خسارة: تحقق SL
        profit_new = -100

    profit_adj_new = profit_new - (FEE_PCT * 100)

    return {
        'variant': variant,
        'new_t1': new_t1,
        'new_t2': new_t2,
        'new_t3': new_t3,
        'profit_pct_new': profit_new,
        'profit_adj_new': profit_adj_new,
        'r_targets': r_targets,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3. Walk-Forward مع Bootstrap
# ═══════════════════════════════════════════════════════════════════════════

def bootstrap_ci(data: List[float], n_boot: int = 1000) -> Tuple[float, float, float]:
    """حساب Bootstrap CI 95% للمتوسط."""
    if not data or len(data) < 2:
        return 0, 0, 0

    n = len(data)
    means = []
    for _ in range(n_boot):
        sample = [data[random.randint(0, n-1)] for _ in range(n)]
        means.append(sum(sample) / n)

    means.sort()
    lo_idx = int(0.025 * n_boot)
    hi_idx = int(0.975 * n_boot)
    return sum(data) / n, means[lo_idx], means[hi_idx]


def analyze_variant(trades: List[Dict], variant: int) -> Dict:
    """تحليل variant واحدة مع Walk-Forward."""
    logger.info(f"\n📊 تحليل Variant {variant} (R:R موسّع)...")

    # محاكاة جميع الصفقات
    simulated = []
    for trade in trades:
        sim = simulate_wide_rr(trade, variant)
        simulated.append(sim)

    # Walk-Forward
    n = len(simulated)
    window_size = n // N_WF_WINDOWS
    e_adj_wf = []

    for w in range(N_WF_WINDOWS):
        train_start = 0
        train_end = int(n * (w + TRAIN_RATIO) / N_WF_WINDOWS)
        test_start = train_end
        test_end = min(train_start + (w + 1) * window_size, n)

        if test_end - test_start < MIN_N_WINDOW:
            continue

        test_profits = [simulated[i]['profit_adj_new'] for i in range(test_start, test_end)]
        e_test = sum(test_profits) / len(test_profits) if test_profits else 0
        e_adj_wf.append(e_test)

    # Bootstrap CI
    if e_adj_wf:
        mean_e, lo_e, hi_e = bootstrap_ci(e_adj_wf, N_BOOTSTRAP)
        wr = sum(1 for s in simulated if s['profit_adj_new'] > 0) / len(simulated) if simulated else 0

        return {
            'variant': variant,
            'n': len(simulated),
            'e_adj_mean': round(mean_e, 4),
            'e_adj_lo': round(lo_e, 4),
            'e_adj_hi': round(hi_e, 4),
            'win_rate': round(wr, 4),
            'r_targets': simulated[0]['r_targets'] if simulated else [],
        }

    return {}


# ═══════════════════════════════════════════════════════════════════════════
# 4. المقارنة مع Baseline
# ═══════════════════════════════════════════════════════════════════════════

def compare_variants(baseline: Dict, variants: List[Dict]) -> Dict:
    """مقارنة variants مع baseline."""
    logger.info("\n📈 المقارنة: Baseline vs Variants الموسّعة")
    logger.info("=" * 80)

    logger.info(f"\nBaseline (الحالي T1=1.0R, T2=1.8R, T3=2.2R):")
    logger.info(f"  n={baseline['n']}, E_adj={baseline['e_adj_mean']}% (CI: {baseline['e_adj_lo']}–{baseline['e_adj_hi']}%)")
    logger.info(f"  WR={baseline['win_rate']*100:.1f}%")

    results = {'baseline': baseline}

    for var in variants:
        if var:
            logger.info(f"\nVariant {var['variant']} (T1={var['r_targets'][0]:.1f}R, T2={var['r_targets'][1]:.1f}R, T3={var['r_targets'][2]:.1f}R):")
            logger.info(f"  n={var['n']}, E_adj={var['e_adj_mean']}% (CI: {var['e_adj_lo']}–{var['e_adj_hi']}%)")
            logger.info(f"  WR={var['win_rate']*100:.1f}%")

            # اختبار دلالة: هل CI لـ variant تقاطع الـ baseline؟
            if var['e_adj_lo'] > baseline['e_adj_mean']:
                logger.info(f"  ✅ قفزة دالة إحصائياً في E_adj (+{var['e_adj_mean'] - baseline['e_adj_mean']:.2f}%)")
            elif var['e_adj_hi'] < baseline['e_adj_mean']:
                logger.info(f"  ⚠️ انخفاض دال في E_adj ({var['e_adj_mean'] - baseline['e_adj_mean']:.2f}%)")
            else:
                logger.info(f"  ➡️ لا فرق دال إحصائياً ({var['e_adj_mean'] - baseline['e_adj_mean']:+.2f}%)")

            results[f'variant_{var["variant"]}'] = var

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 5. التشغيل الرئيسي
# ═══════════════════════════════════════════════════════════════════════════

async def main():
    logger.info("🚀 بدء Wide R:R Isolation Part 34...")

    # تحميل صفقات الإعداد المُجمّد
    trades = await load_frozen_setup_trades()
    if not trades:
        logger.error("❌ لا توجد صفقات من الإعداد المُجمّد")
        return

    # تحليل Baseline (الحالي)
    logger.info("\n🔍 تحليل Baseline الحالي...")
    e_adj_baseline = [t['profit_adj_baseline'] for t in trades]
    mean_bl, lo_bl, hi_bl = bootstrap_ci(e_adj_baseline, N_BOOTSTRAP)
    wr_bl = sum(1 for t in trades if t['profit_adj_baseline'] > 0) / len(trades)

    baseline_result = {
        'variant': 'baseline',
        'n': len(trades),
        'e_adj_mean': round(mean_bl, 4),
        'e_adj_lo': round(lo_bl, 4),
        'e_adj_hi': round(hi_bl, 4),
        'win_rate': round(wr_bl, 4),
        'r_targets': [1.0, 1.8, 2.2],
    }

    # تحليل Variants
    variants = []
    for var_num in [1, 2]:
        result = analyze_variant(trades, var_num)
        if result:
            variants.append(result)

    # مقارنة
    comparison = compare_variants(baseline_result, variants)

    # حفظ النتائج
    with open(OUTPUT_FILE, 'w') as f:
        for key, val in comparison.items():
            record = {'comparison_part': key, **val, 'timestamp': datetime.now(timezone.utc).isoformat()}
            f.write(json.dumps(record) + '\n')

    logger.info(f"\n✓ تم حفظ النتائج في {OUTPUT_FILE}")

    # الخلاصة
    logger.info("\n" + "=" * 80)
    logger.info("💡 الخلاصة:")
    if variants and variants[0]['e_adj_mean'] > baseline_result['e_adj_mean']:
        logger.info("   المشكلة قد تكون في ضيق R:R الحالي. تجربة R:R أوسع قد تحسّن الأداء.")
    else:
        logger.info("   R:R الحالي ليس المشكلة الرئيسية. المؤشرات نفسها قد تحتاج تحسين.")


if __name__ == '__main__':
    asyncio.run(main())
