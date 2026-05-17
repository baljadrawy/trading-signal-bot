"""
الباكتيستر — الجزء السابع: تحقق فلتر RSI>=1.2 بمنهج Walk-Forward
===================================================================
هدف:
    تحقق ما إذا كان فلتر rsi_score>=1.2 يُحسّن الأداء Out-of-Sample
    بشكل متسق، أم مجرد overfitting على 265 صفقة.

المنهج:
    Walk-Forward بـ 5 folds على 265 صفقة كاملة:
    - كل fold: 80% train + 20% test
    - في كل fold: نقارن baseline (لا فلتر) vs filtered (rsi>=1.2)
    - المقياس: expectancy = WR*avg_win + (1-WR)*avg_loss

النتيجة:
    إذا filtered.oos_exp > baseline.oos_exp في 3/5 folds → فلتر صالح
    backtest_results_part7.jsonl

قيد: offline — يقرأ من DB مباشرة عبر asyncio.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Tuple, Optional

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')

from shared.database import Database

OUTPUT_FILE = '/app/backtest_results_part7.jsonl'
N_FOLDS = 5


async def load_trades() -> List[Dict]:
    """تحميل جميع الصفقات المغلقة مع RSI score"""
    rows = await Database.fetch("""
        SELECT
            tr.symbol,
            tr.result,
            tr.profit_usdt,
            tr.profit_percent,
            tr.stop_hit,
            tr.target_reached,
            tr.exit_time,
            s.signal_time,
            s.score,
            s.timeframe,
            s.market_condition,
            s.score_details
        FROM trade_results tr
        JOIN signals s ON tr.signal_id = s.id
        WHERE s.signal_time >= '2026-04-22'
          AND tr.profit_usdt IS NOT NULL
          AND s.score_details IS NOT NULL
          AND s.score_details->>'rsi' IS NOT NULL
        ORDER BY s.signal_time ASC
    """)
    return [dict(r) for r in rows]


def get_rsi_score(trade: Dict) -> float:
    """استخراج RSI score من score_details"""
    try:
        sd = trade.get('score_details', {})
        if isinstance(sd, str):
            sd = json.loads(sd)
        return float(sd.get('rsi', 0))
    except (TypeError, ValueError):
        return 0.0


def compute_expectancy(trades: List[Dict]) -> Dict:
    """حساب expectancy و WR"""
    if not trades:
        return {'n': 0, 'wr': 0.0, 'avg_win': 0.0, 'avg_loss': 0.0, 'expectancy': 0.0}

    wins = [t for t in trades if t['result'] == 'WIN']
    losses = [t for t in trades if t['result'] == 'LOSS']

    wr = len(wins) / len(trades)
    avg_win = float(sum(float(t['profit_usdt']) for t in wins) / len(wins)) if wins else 0.0
    avg_loss = float(sum(float(t['profit_usdt']) for t in losses) / len(losses)) if losses else 0.0
    expectancy = wr * avg_win + (1 - wr) * avg_loss

    return {
        'n': len(trades),
        'n_win': len(wins),
        'n_loss': len(losses),
        'wr': round(wr, 4),
        'avg_win': round(avg_win, 4),
        'avg_loss': round(avg_loss, 4),
        'expectancy': round(expectancy, 4),
        'net_pnl': round(float(sum(float(t['profit_usdt']) for t in trades)), 2),
    }


def walk_forward(trades: List[Dict], n_folds: int = 5) -> List[Dict]:
    """Walk-Forward: n_folds folds، كل fold = train 80% + test 20%"""
    fold_size = len(trades) // n_folds
    results = []

    for fold_idx in range(n_folds):
        test_start = fold_idx * fold_size
        test_end = (fold_idx + 1) * fold_size if fold_idx < n_folds - 1 else len(trades)

        test_set = trades[test_start:test_end]
        train_set = trades[:test_start] + trades[test_end:]

        if len(test_set) < 5:
            continue

        # baseline: كل الصفقات
        baseline_test = compute_expectancy(test_set)
        baseline_train = compute_expectancy(train_set)

        # filtered: فقط rsi>=1.2
        filtered_test_trades = [t for t in test_set if get_rsi_score(t) >= 1.2]
        filtered_train_trades = [t for t in train_set if get_rsi_score(t) >= 1.2]

        filtered_test = compute_expectancy(filtered_test_trades)
        filtered_train = compute_expectancy(filtered_train_trades)

        # rejected trades في الاختبار
        rejected_test = [t for t in test_set if get_rsi_score(t) < 1.2]
        rejected_perf = compute_expectancy(rejected_test)

        fold_result = {
            'fold': fold_idx + 1,
            'test_range': f"index {test_start}-{test_end}",
            'baseline': {
                'train': baseline_train,
                'test': baseline_test,
            },
            'filtered': {
                'train': filtered_train,
                'test': filtered_test,
            },
            'rejected_test': rejected_perf,
            'improvement': round(filtered_test['expectancy'] - baseline_test['expectancy'], 4),
            'filter_pass_rate': round(filtered_test['n'] / max(baseline_test['n'], 1), 3),
        }
        results.append(fold_result)

        # طباعة فورية
        print(f"\nFold {fold_idx+1}/{n_folds}:")
        print(f"  Test n={baseline_test['n']} | Filtered n={filtered_test['n']}"
              f" ({fold_result['filter_pass_rate']*100:.0f}%)")
        print(f"  Baseline OOS:  WR={baseline_test['wr']*100:.1f}%,"
              f" E={baseline_test['expectancy']:+.3f}")
        print(f"  Filtered OOS:  WR={filtered_test['wr']*100:.1f}%,"
              f" E={filtered_test['expectancy']:+.3f}")
        print(f"  Rejected perf: WR={rejected_perf['wr']*100:.1f}%,"
              f" E={rejected_perf['expectancy']:+.3f}")
        print(f"  Improvement: {fold_result['improvement']:+.3f}")

    return results


async def run_analysis():
    print("=" * 65)
    print("الجزء 7: Walk-Forward تحقق فلتر RSI>=1.2")
    print("التاريخ:", datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'))
    print("=" * 65)

    await Database.connect()
    trades = await load_trades()

    print(f"\nتحميل {len(trades)} صفقة من قاعدة البيانات")

    # فحص توزيع RSI
    rsi_scores = [get_rsi_score(t) for t in trades]
    rsi_pass = sum(1 for r in rsi_scores if r >= 1.2)
    print(f"RSI>=1.2: {rsi_pass}/{len(trades)} ({rsi_pass*100/len(trades):.1f}%)")

    # أداء كامل baseline
    baseline_all = compute_expectancy(trades)
    filtered_all = compute_expectancy([t for t in trades if get_rsi_score(t) >= 1.2])
    rejected_all = compute_expectancy([t for t in trades if get_rsi_score(t) < 1.2])

    print(f"\nكل البيانات — Baseline:")
    print(f"  n={baseline_all['n']}, WR={baseline_all['wr']*100:.1f}%,"
          f" E={baseline_all['expectancy']:+.4f}, PnL={baseline_all['net_pnl']:.2f}")
    print(f"\nكل البيانات — Filtered (rsi>=1.2):")
    print(f"  n={filtered_all['n']}, WR={filtered_all['wr']*100:.1f}%,"
          f" E={filtered_all['expectancy']:+.4f}, PnL={filtered_all['net_pnl']:.2f}")
    print(f"\nكل البيانات — Rejected (rsi<1.2):")
    print(f"  n={rejected_all['n']}, WR={rejected_all['wr']*100:.1f}%,"
          f" E={rejected_all['expectancy']:+.4f}, PnL={rejected_all['net_pnl']:.2f}")

    # Walk-Forward
    print("\n--- Walk-Forward Results ---")
    fold_results = walk_forward(trades, N_FOLDS)

    # ملخص
    improvements = [f['improvement'] for f in fold_results]
    positive_folds = sum(1 for i in improvements if i > 0)
    avg_improvement = sum(improvements) / len(improvements) if improvements else 0

    print("\n--- ملخص Walk-Forward ---")
    print(f"Folds حُسن فيها الفلتر: {positive_folds}/{len(fold_results)}")
    print(f"متوسط التحسين: {avg_improvement:+.4f}")

    # حكم
    if positive_folds >= 4 and avg_improvement > 0.05:
        verdict = "قوي — طبّق فوراً"
        action = "apply"
    elif positive_folds >= 3 and avg_improvement > 0:
        verdict = "واعد — طبّق مع مراقبة"
        action = "apply_with_monitoring"
    else:
        verdict = "غير موثوق — لا تُطبَّق"
        action = "hold"

    print(f"الحكم: {verdict}")

    # حفظ النتائج
    output = {
        'run_date': datetime.utcnow().isoformat(),
        'part': 7,
        'description': 'Walk-Forward تحقق فلتر RSI score >= 1.2',
        'n_total': len(trades),
        'n_folds': N_FOLDS,
        'rsi_pass_count': rsi_pass,
        'rsi_pass_rate': round(rsi_pass / len(trades), 3),
        'full_sample': {
            'baseline': baseline_all,
            'filtered': filtered_all,
            'rejected': rejected_all,
        },
        'fold_results': fold_results,
        'summary': {
            'positive_folds': positive_folds,
            'total_folds': len(fold_results),
            'avg_improvement': round(avg_improvement, 4),
            'improvements': improvements,
        },
        'verdict': verdict,
        'action': action,
        'threshold': 1.2,
        'warning': (
            'فلتر RSI>=1.2 أُضيف لـ signal_logic.py — يُقلّص الإشارات بنسبة 50%. '
            'راقب أول 30 إشارة بعد التطبيق. '
            'إذا WR<45% أو n<10 في 2 أسابيع → راجع الـ threshold.'
        ),
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nالنتائج محفوظة: {OUTPUT_FILE}")
    await Database.disconnect()


if __name__ == '__main__':
    asyncio.run(run_analysis())
