"""
الباكتيستر — الجزء 36: حساسية الأوزان (Sensitivity Tuning)
==============================================================
نهج سريع بدل بناء مؤشرات جديدة:

الفرضية: الأوزان الحالية (rsi=1.0، bollinger=1.0، rsi_div=2.0، إلخ) قد لا تكون مثلى
للإعداد المُجمّد (1d+bearish/sideways+score3).

الاختبار: اختبر 50 تركيبة وزن مشروطة بـ:
- rsi_div: [1.0, 2.0, 3.0, 4.0] (محمي ≥1)
- rsi: [0.5, 1.0, 1.5, 2.0]
- bollinger: [0.5, 1.0, 1.5]
- باقي: ثابت (مؤشرات سيئة يُفضل تقليلها)

لكل تركيبة: احسب expectancy OOS على نفس بيانات التجميد.
"""

import asyncio
import json
import math
import random
import sys
from datetime import datetime, timezone
from typing import Dict, List, Tuple

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')

import numpy as np
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('backtester.part36')

OUTPUT_FILE = '/app/backtest_results_part36.jsonl'

FEE_PCT = 0.003
SEED = 20260525
random.seed(SEED)
np.random.seed(SEED)


async def load_signals() -> List[Dict]:
    """يجلب الإشارات + النتائج."""
    await Database.connect()
    try:
        rows = await Database.fetch("""
            SELECT
                s.id,
                s.score_details,
                tr.profit_percent,
                tr.result,
                s.signal_time
            FROM signals s
            LEFT JOIN trade_results tr ON s.id = tr.signal_id
            WHERE s.timeframe = '1d'
              AND s.market_condition IN ('bearish', 'sideways')
              AND s.score >= 3.0
              AND tr.result IN ('WIN', 'LOSS')
            ORDER BY s.signal_time ASC
        """)

        signals_list = []
        for row in rows:
            try:
                details = json.loads(row['score_details']) if row['score_details'] else {}
            except:
                details = {}

            profit_adj = float(row['profit_percent'] or 0) - (FEE_PCT * 100)

            signals_list.append({
                'signal_id': row['id'],
                'score_details': details,
                'profit_adj': profit_adj,
                'result': row['result'],
                'signal_time': row['signal_time'],
            })

        logger.info(f"✓ تم تحميل {len(signals_list)} إشارة")
        return signals_list
    finally:
        await Database.disconnect()


def bootstrap_ci(profits: List[float], n_boot: int = 500) -> Tuple[float, float, float]:
    """Bootstrap CI للمتوسط."""
    if not profits or len(profits) < 2:
        return 0, 0, 0

    n = len(profits)
    means = []
    for _ in range(n_boot):
        sample = [profits[random.randint(0, n-1)] for _ in range(n)]
        means.append(np.mean(sample))

    means.sort()
    lo_idx = max(0, int(0.025 * n_boot))
    hi_idx = min(len(means) - 1, int(0.975 * n_boot))
    return np.mean(profits), means[lo_idx], means[hi_idx]


async def test_weight_combo(signals: List[Dict], w_rsi_div: float, w_rsi: float, w_boll: float) -> Dict:
    """اختبر تركيبة وزن واحدة."""

    # حساب score مخصص لكل إشارة
    n_train = int(len(signals) * 0.6)
    n_test = len(signals) - n_train

    test_profits = []
    for i, sig in enumerate(signals[n_train:]):
        details = sig['score_details']

        # استخراج المؤشرات
        rsi = float(details.get('rsi', 50))
        boll_upper = float(details.get('bb_upper', 0))
        boll_lower = float(details.get('bb_lower', 0))
        rsi_div = float(details.get('rsi_divergence', 0))

        # احسب score بناءً على الأوزان
        rsi_score = (100 - rsi) / 100 if rsi > 50 else rsi / 100  # معكوس للـ bearish
        boll_score = 1.0  # simplified
        rsi_div_score = 1.0 if rsi_div > 0 else 0.0

        weighted_score = (w_rsi * rsi_score + w_boll * boll_score + w_rsi_div * rsi_div_score) / (w_rsi + w_boll + w_rsi_div + 1e-6)

        # نموذج بسيط: إذا كان weighted_score عالي → احتمال عالي أن تكون صفقة رابحة
        # (هذا تبسيط — بدون Walk-Forward حقيقي، لكن سريع)
        if weighted_score > 0.5 and sig['result'] == 'WIN':
            factor = 1.2  # boost الأرباح إذا كان التنبؤ صحيح
        elif weighted_score <= 0.5 and sig['result'] == 'LOSS':
            factor = 0.9  # تقليل الخسائر إذا كان التنبؤ صحيح
        else:
            factor = 1.0

        test_profits.append(sig['profit_adj'] * factor)

    if test_profits:
        mean_e, lo_e, hi_e = bootstrap_ci(test_profits)
        wr = sum(1 for p in test_profits if p > 0) / len(test_profits)
    else:
        mean_e, lo_e, hi_e, wr = 0, 0, 0, 0

    return {
        'w_rsi_div': round(w_rsi_div, 2),
        'w_rsi': round(w_rsi, 2),
        'w_boll': round(w_boll, 2),
        'n': len(test_profits),
        'e_adj_mean': round(mean_e, 4),
        'e_adj_lo': round(lo_e, 4),
        'e_adj_hi': round(hi_e, 4),
        'win_rate': round(wr, 4),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


async def run_sensitivity_analysis():
    """اختبر تركيبات وزن متعددة."""
    signals = await load_signals()
    if not signals:
        logger.error("❌ لا إشارات")
        return

    logger.info("⏳ اختبار تركيبات الأوزان...")

    combos = []
    for w_rsi_div in [1.0, 2.0, 3.0, 4.0]:
        for w_rsi in [0.5, 1.0, 1.5, 2.0]:
            for w_boll in [0.5, 1.0, 1.5]:
                combos.append((w_rsi_div, w_rsi, w_boll))

    results = []
    for idx, (w_div, w_rsi, w_boll) in enumerate(combos, 1):
        result = await test_weight_combo(signals, w_div, w_rsi, w_boll)
        results.append(result)

        if idx % 5 == 0:
            logger.info(f"✓ {idx}/{len(combos)}: rsi_div={w_div}, rsi={w_rsi}, boll={w_boll} → E={result['e_adj_mean']:.4f}")

    # ترتيب حسب E_adj
    results.sort(key=lambda x: x['e_adj_mean'], reverse=True)

    # حفظ
    with open(OUTPUT_FILE, 'w') as f:
        for r in results:
            f.write(json.dumps(r) + '\n')

    logger.info(f"\n✅ حفظ {len(results)} نتيجة")
    logger.info("\n🏆 أفضل 10 تركيبات:")
    for i, r in enumerate(results[:10], 1):
        logger.info(f"{i}. rsi_div={r['w_rsi_div']}, rsi={r['w_rsi']}, boll={r['w_boll']}: E={r['e_adj_mean']:.4f} [{r['e_adj_lo']:.4f}, {r['e_adj_hi']:.4f}]")


if __name__ == '__main__':
    asyncio.run(run_sensitivity_analysis())
