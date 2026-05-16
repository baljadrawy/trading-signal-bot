"""
الباكتيستر — الجزء الثالث: Walk-Forward Validation
=======================================================
يأخذ نتائج الجزء الثاني (backtest_results_part2.jsonl) ويقسمها زمنياً:
  - Train set (60%): لتحديد أفضل عتبة score
  - Test set  (40%): لتقييم تلك العتبة بشكل صادق (out-of-sample)
الهدف: اكتشاف هل رفع min_score يتحسن expectancy بشكل حقيقي أم مجرد تكيّف مع الضوضاء.

قيود الخادم: مهمة دفعية، لا network/DB، ذاكرة ضئيلة.
المخرج: ملف backtest_results_part3.jsonl + ملخص مطبوع.
"""

import json
import sys
from datetime import datetime
from typing import Dict, List, Tuple

INPUT_FILE  = '/app/backtest_results_part2.jsonl'
OUTPUT_FILE = '/app/backtest_results_part3.jsonl'

TRAIN_RATIO = 0.60          # 60% تدريب، 40% اختبار
SCORE_CANDIDATES = [3.0, 3.13, 3.4, 3.5, 4.0, 4.5]  # عتبات نختبر تحسينها
MIN_SAMPLE_TEST  = 5        # حد أدنى لعينة الاختبار


def expectancy(trades: List[Dict]) -> Tuple[float, float, float]:
    """يحسب expectancy = WR * avg_win - (1-WR) * abs(avg_loss)"""
    if not trades:
        return 0.0, 0.0, 0.0
    wins   = [t for t in trades if t['sim_result'] == 'WIN']
    losses = [t for t in trades if t['sim_result'] == 'LOSS']
    wr     = len(wins) / len(trades)
    avg_w  = (sum(t['sim_profit_pct'] for t in wins)   / len(wins))   if wins   else 0.0
    avg_l  = (sum(t['sim_profit_pct'] for t in losses) / len(losses)) if losses else 0.0
    exp    = wr * avg_w - (1 - wr) * abs(avg_l)
    return round(exp, 4), round(wr, 4), round(avg_l, 4)


def filter_by_score(trades: List[Dict], min_score: float) -> List[Dict]:
    return [t for t in trades if t.get('total_score', 0) >= min_score]


def run_walk_forward():
    print("=" * 60)
    print("الباكتيستر — الجزء الثالث: Walk-Forward")
    print("=" * 60)

    # تحميل الجزء الثاني
    if not __import__('os').path.exists(INPUT_FILE):
        print(f"ERROR: ملف الجزء الثاني غير موجود: {INPUT_FILE}")
        sys.exit(1)

    records = []
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception as e:
                print(f"WARNING: سطر تالف: {e}")

    if not records:
        print("ERROR: ملف الجزء الثاني فارغ")
        sys.exit(1)

    # ترتيب زمني بـ eval_time
    try:
        records.sort(key=lambda r: r.get('eval_time', ''))
    except Exception:
        pass

    print(f"إجمالي الصفقات المحاكاة (الجزء 2): {len(records)}")

    # تقسيم زمني
    n_train = int(len(records) * TRAIN_RATIO)
    n_test  = len(records) - n_train
    train   = records[:n_train]
    test    = records[n_train:]

    print(f"Train (60%): {len(train)} صفقة (حتى {train[-1].get('eval_time','?') if train else '?'})")
    print(f"Test  (40%): {len(test)} صفقة (من  {test[0].get('eval_time','?') if test else '?'})")
    print()

    # ─── مرحلة التدريب ───────────────────────────────────────
    print("-- مرحلة التدريب: إيجاد أفضل عتبة score --")
    best_score_thresh = SCORE_CANDIDATES[0]
    best_train_exp    = -999.0

    train_results = {}
    for thresh in SCORE_CANDIDATES:
        filtered = filter_by_score(train, thresh)
        if len(filtered) < 3:
            print(f"  min_score={thresh}: عينة صغيرة جداً ({len(filtered)}) — تخطي")
            continue
        exp, wr, avg_l = expectancy(filtered)
        net_pnl = sum(t['sim_profit_usdt'] for t in filtered)
        train_results[thresh] = {
            'n': len(filtered), 'exp': exp, 'wr': round(wr*100, 1),
            'avg_loss': avg_l, 'net': round(net_pnl, 2)
        }
        marker = ''
        if exp > best_train_exp:
            best_train_exp    = exp
            best_score_thresh = thresh
            marker = ' <-- أفضل'
        print(f"  min_score={thresh}: n={len(filtered)}, WR={wr*100:.0f}%, "
              f"E={exp:+.3f}%, net={net_pnl:+.2f}USDT{marker}")

    print(f"\nأفضل عتبة (على التدريب): min_score={best_score_thresh} "
          f"(E={best_train_exp:+.3f}%)\n")

    # ─── مرحلة الاختبار (out-of-sample) ─────────────────────
    print("-- مرحلة الاختبار (out-of-sample): قياس العتبة الفائزة --")

    # baseline: كل الإشارات في test بدون فلتر score
    base_exp, base_wr, base_avg_l = expectancy(test)
    base_net = sum(t['sim_profit_usdt'] for t in test)
    print(f"  Baseline (min_score=3.0): n={len(test)}, WR={base_wr*100:.0f}%, "
          f"E={base_exp:+.3f}%, net={base_net:+.2f}USDT")

    # best threshold
    test_filtered = filter_by_score(test, best_score_thresh)
    if len(test_filtered) >= MIN_SAMPLE_TEST:
        opt_exp, opt_wr, opt_avg_l = expectancy(test_filtered)
        opt_net = sum(t['sim_profit_usdt'] for t in test_filtered)
        print(f"  Optimized (min_score={best_score_thresh}): n={len(test_filtered)}, "
              f"WR={opt_wr*100:.0f}%, E={opt_exp:+.3f}%, net={opt_net:+.2f}USDT")
        improvement = opt_exp - base_exp
        print(f"\n  Delta-E (OOS): {improvement:+.3f}%  "
              f"({'تحسّن' if improvement > 0 else 'تدهور'})")
        adopted = improvement > 0.05  # حدّ التبني: تحسن > 0.05%
        print(f"  القرار: {'تبنّي العتبة الجديدة' if adopted else 'رفض — ليس كافياً (< 0.05%)'}")
    else:
        opt_exp = base_exp
        opt_wr  = base_wr
        opt_net = base_net
        print(f"  Optimized (min_score={best_score_thresh}): عينة صغيرة ({len(test_filtered)}) — الاحتفاظ بـ baseline")
        adopted = False

    # ─── كل العتبات على الاختبار ─────────────────────────────
    print("\n-- جدول كامل (Test set فقط) --")
    test_all_results = []
    for thresh in SCORE_CANDIDATES:
        filtered = filter_by_score(test, thresh)
        if not filtered:
            continue
        exp, wr, avg_l = expectancy(filtered)
        net = sum(t['sim_profit_usdt'] for t in filtered)
        test_all_results.append({
            'min_score': thresh,
            'n': len(filtered),
            'wr': round(wr * 100, 1),
            'exp': exp,
            'net': round(net, 2),
        })
        print(f"  min_score={thresh}: n={len(filtered)}, WR={wr*100:.0f}%, "
              f"E={exp:+.3f}%, net={net:+.2f}USDT")

    # ─── ملخص للذاكرة ────────────────────────────────────────
    summary = {
        'run_date': datetime.utcnow().isoformat(),
        'total_part2_records': len(records),
        'train_n': len(train),
        'test_n':  len(test),
        'train_period': {
            'from': train[0].get('eval_time') if train else None,
            'to':   train[-1].get('eval_time') if train else None,
        },
        'test_period': {
            'from': test[0].get('eval_time') if test else None,
            'to':   test[-1].get('eval_time') if test else None,
        },
        'baseline': {
            'min_score': 3.0,
            'n': len(test),
            'wr_pct': round(base_wr * 100, 1),
            'expectancy_pct': base_exp,
            'net_usdt': round(base_net, 2),
        },
        'best_train_threshold': best_score_thresh,
        'best_train_expectancy': best_train_exp,
        'oos_result': {
            'min_score': best_score_thresh,
            'n': len(test_filtered) if 'test_filtered' in dir() else 0,
            'wr_pct': round(opt_wr * 100, 1) if 'opt_wr' in dir() else 0,
            'expectancy_pct': opt_exp,
            'net_usdt': round(opt_net, 2) if 'opt_net' in dir() else 0,
            'improvement_pct': round(opt_exp - base_exp, 4),
            'adopted': adopted,
        },
        'all_thresholds_oos': test_all_results,
        'train_results': {str(k): v for k, v in train_results.items()},
        'recommendation': (
            f"رفع min_score إلى {best_score_thresh}"
            if adopted else
            f"الإبقاء على min_score=3.0 — OOS لا يدعم الرفع (عينة {n_test} صفقة)"
        ),
    }

    # حفظ النتائج
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as fout:
        json.dump(summary, fout, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"التوصية: {summary['recommendation']}")
    print(f"النتائج محفوظة في: {OUTPUT_FILE}")
    print("=" * 60)

    return summary


if __name__ == '__main__':
    run_walk_forward()
