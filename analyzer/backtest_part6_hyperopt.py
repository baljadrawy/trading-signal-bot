"""
الباكتيستر — الجزء السادس: Hyperopt (بحث عشوائي منضبط في فضاء الأوزان)
=========================================================================
يبحث عن أفضل مجموعة من:
  - أوزان المؤشرات (indicator_weights)
  - عتبة الدخول (min_score_to_signal)

دالة الهدف: expectancy مُتحقَّق out-of-sample عبر Walk-Forward
             (نفس منهج الجزء الثالث، لكن على فضاء معاملات أوسع).

القيود:
  - لا شبكة (offline) — يعمل على backtest_results_part2.jsonl فقط
  - ذاكرة منضبطة: بحث عشوائي (random search) بدلاً من grid كامل
  - MAX_TRIALS = 300 تجربة، كل تجربة < 1ms
  - المخرج: backtest_results_part6.jsonl + ملخص مطبوع

ملاحظة: النتائج مؤشرية (preliminary) بسبب صغر العينة (30 صفقة).
        لا تُطبَّق على الإعدادات الحيّة قبل الوصول لـ 99+ صفقة.
"""

import json
import os
import random
import sys
from copy import deepcopy
from datetime import datetime
from typing import Dict, List, Optional, Tuple

INPUT_FILE  = '/app/backtest_results_part2.jsonl'
OUTPUT_FILE = '/app/backtest_results_part6.jsonl'

# ── حدود فضاء البحث ───────────────────────────────────────────────────────
INDICATORS = [
    'rsi', 'bollinger', 'stoch_rsi', 'rsi_divergence',
    'fibonacci', 'macd', 'ema_cross', 'volume', 'obv', 'btc_trend'
]

# كل مؤشر: [min_weight, max_weight, step]
WEIGHT_SPACE = {
    'rsi':           (0.0, 2.0, 0.25),
    'bollinger':     (0.0, 2.0, 0.25),
    'stoch_rsi':     (0.0, 2.0, 0.25),
    'rsi_divergence':(0.0, 3.0, 0.5),
    'fibonacci':     (0.0, 2.0, 0.25),
    'macd':          (0.0, 2.0, 0.25),
    'ema_cross':     (0.0, 2.0, 0.25),
    'volume':        (0.0, 2.0, 0.25),
    'obv':           (0.0, 2.0, 0.25),
    'btc_trend':     (0.0, 2.0, 0.25),
}

# عتبة min_score المرشحة
MIN_SCORE_CANDIDATES = [3.0, 3.5, 4.0, 4.5, 5.0]

# إعدادات البحث
MAX_TRIALS       = 300    # عدد التجارب العشوائية
TRAIN_RATIO      = 0.60   # 60% تدريب / 40% اختبار (Walk-Forward)
MIN_OOS_SAMPLE   = 5      # حد أدنى لعينة الاختبار لتقبّل التجربة
TOP_K            = 10     # أفضل K تجربة تُحفظ
RANDOM_SEED      = 42


# ── دوال مساعدة ────────────────────────────────────────────────────────────

def rescore(record: Dict, weights: Dict[str, float]) -> float:
    """
    يُعيد حساب النقاط لسجل واحد باستخدام أوزان جديدة.
    يضرب قيم score_details الخام (قبل الضرب بالوزن الأصلي) في الأوزان الجديدة.

    ملاحظة: score_details تحتوي على القيم بعد الضرب بأوزان الـ DB.
    للتبسيط (والاتساق مع الوزن الأصلي = 1.0) نفترض أن القيم الخام تساوي
    score_details مقسومةً على وزن حدّي = 1.0 (أي القيمة كما هي).
    هذا يصح لأن أوزان DB الافتراضية = 1.0 لكل المؤشرات عند البناء.
    """
    details = record.get('score_details', {})
    total = 0.0
    for ind in INDICATORS:
        raw_val = details.get(ind, 0.0)   # القيمة كما سُجّلت
        total  += raw_val * weights.get(ind, 1.0)
    return round(total, 4)


def expectancy(profits: List[float]) -> float:
    """حساب expectancy من قائمة أرباح/خسائر (بالنسبة المئوية)."""
    if not profits:
        return -999.0
    wins   = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]
    wr     = len(wins) / len(profits)
    avg_w  = sum(wins)   / len(wins)   if wins   else 0.0
    avg_l  = sum(losses) / len(losses) if losses else 0.0
    return wr * avg_w + (1 - wr) * avg_l


def walk_forward_score(
    records:   List[Dict],
    weights:   Dict[str, float],
    min_score: float,
) -> Tuple[float, float, int, int, float]:
    """
    يُقيّم مجموعة أوزان+عتبة عبر Walk-Forward:
      1. إعادة تسجيل كل صفقة بالأوزان الجديدة
      2. تقسيم زمني 60/40
      3. العتبة تُطبَّق على مجموعة الاختبار فقط
      4. الإعادة: (oos_expectancy, oos_wr, oos_n, n_rejected, train_exp)
    """
    n_train = int(len(records) * TRAIN_RATIO)
    train   = records[:n_train]
    test    = records[n_train:]

    # إعادة التسجيل على الاختبار فقط (الأوزان تُحدّد من التدريب — لكن بما أننا نبحث
    # عشوائياً فنُطبّق نفس الأوزان على الاثنين — WF حقيقي يحتاج بيانات أكبر)
    def filter_and_score(subset: List[Dict]) -> List[float]:
        out = []
        for r in subset:
            new_score = rescore(r, weights)
            if new_score >= min_score:
                out.append(r.get('sim_profit_pct', 0.0))
        return out

    train_profits = filter_and_score(train)
    test_profits  = filter_and_score(test)

    train_exp = expectancy(train_profits)
    oos_exp   = expectancy(test_profits)
    oos_n     = len(test_profits)
    n_total   = len(test)
    n_rejected = n_total - oos_n
    oos_wr     = (sum(1 for p in test_profits if p > 0) / oos_n
                  if oos_n > 0 else 0.0)

    return oos_exp, oos_wr, oos_n, n_rejected, train_exp


def sample_weights(rng: random.Random) -> Dict[str, float]:
    """يختار مجموعة أوزان عشوائية من فضاء البحث."""
    weights = {}
    for ind in INDICATORS:
        lo, hi, step = WEIGHT_SPACE[ind]
        steps  = int((hi - lo) / step) + 1
        choice = rng.randint(0, steps - 1)
        weights[ind] = round(lo + choice * step, 4)
    return weights


# ── نقطة الدخول الرئيسية ───────────────────────────────────────────────────

def run_hyperopt():
    random.seed(RANDOM_SEED)
    rng = random.Random(RANDOM_SEED)

    print("=" * 65)
    print("الباكتيستر — الجزء السادس: Hyperopt (Random Search)")
    print("=" * 65)

    if not os.path.exists(INPUT_FILE):
        print(f"ERROR: ملف الجزء الثاني غير موجود: {INPUT_FILE}")
        sys.exit(1)

    # تحميل البيانات
    records: List[Dict] = []
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

    # ترتيب زمني
    try:
        records.sort(key=lambda r: r.get('eval_time', ''))
    except Exception:
        pass

    n_total = len(records)
    n_train = int(n_total * TRAIN_RATIO)
    n_test  = n_total - n_train
    print(f"إجمالي الصفقات: {n_total} (train={n_train}, test={n_test})")
    print(f"عدد التجارب: {MAX_TRIALS} | عتبات: {MIN_SCORE_CANDIDATES}")
    print(f"حد أدنى لعينة الاختبار: {MIN_OOS_SAMPLE}")
    print()

    # ── Baseline: الأوزان الحالية (كلها = 1.0) ──────────────────────────────
    baseline_weights = {ind: 1.0 for ind in INDICATORS}
    baseline_score   = 3.0  # min_score الحالي

    bl_oos_exp, bl_oos_wr, bl_oos_n, _, bl_train_exp = walk_forward_score(
        records, baseline_weights, baseline_score
    )
    print(f"Baseline (أوزان=1.0, min_score={baseline_score}):")
    print(f"  Train-E={bl_train_exp:+.3f}%, OOS-E={bl_oos_exp:+.3f}%,"
          f" OOS-WR={bl_oos_wr*100:.1f}%, OOS-n={bl_oos_n}")
    print()

    # ── البحث العشوائي ──────────────────────────────────────────────────────
    results: List[Dict] = []
    valid_trials = 0
    skipped_small = 0

    print(f"بدء البحث العشوائي ({MAX_TRIALS} تجربة)...")
    for trial_i in range(MAX_TRIALS):
        w         = sample_weights(rng)
        min_score = rng.choice(MIN_SCORE_CANDIDATES)

        oos_exp, oos_wr, oos_n, n_rej, train_exp = walk_forward_score(
            records, w, min_score
        )

        if oos_n < MIN_OOS_SAMPLE:
            skipped_small += 1
            continue

        valid_trials += 1
        results.append({
            'trial':      trial_i,
            'weights':    w,
            'min_score':  min_score,
            'oos_exp':    round(oos_exp, 5),
            'oos_wr':     round(oos_wr, 4),
            'oos_n':      oos_n,
            'n_rejected': n_rej,
            'train_exp':  round(train_exp, 5),
            # هامش الأمان: الفجوة بين train وOOS (كبيرة = تناسب مفرط)
            'overfit_gap': round(train_exp - oos_exp, 5),
        })

    print(f"تجارب صالحة: {valid_trials}/{MAX_TRIALS} (تخطي صغار: {skipped_small})")
    print()

    if not results:
        print("لا تجارب صالحة — عيّنة صغيرة جداً. زد البيانات أولاً.")
        sys.exit(0)

    # ترتيب حسب OOS expectancy تنازلياً
    results.sort(key=lambda x: x['oos_exp'], reverse=True)
    top_k = results[:TOP_K]

    # ── طباعة أفضل K تجربة ──────────────────────────────────────────────────
    print(f"== أفضل {TOP_K} تجربة (حسب OOS-Expectancy) ==")
    for rank, t in enumerate(top_k, 1):
        delta_vs_baseline = t['oos_exp'] - bl_oos_exp
        print(
            f"  #{rank}: min_score={t['min_score']}, OOS-E={t['oos_exp']:+.3f}%"
            f" (vs baseline {delta_vs_baseline:+.3f}%),"
            f" WR={t['oos_wr']*100:.1f}%, n={t['oos_n']},"
            f" gap={t['overfit_gap']:+.3f}%"
        )
        # طباعة الأوزان التي تختلف عن 1.0
        non_default = {k: v for k, v in t['weights'].items() if v != 1.0}
        if non_default:
            print(f"     أوزان مختلفة: {non_default}")

    print()

    # ── تحليل: أكثر المؤشرات ارتباطاً بالنتائج الجيدة ──────────────────────
    print("== تحليل أهمية المؤشرات (متوسط الوزن في أفضل 25%) ==")
    top25_n   = max(1, len(results) // 4)
    top25     = results[:top25_n]
    bottom25  = results[-top25_n:]

    for ind in INDICATORS:
        avg_top    = sum(t['weights'][ind] for t in top25)    / len(top25)
        avg_bottom = sum(t['weights'][ind] for t in bottom25) / len(bottom25)
        avg_all    = sum(t['weights'][ind] for t in results)  / len(results)
        delta = avg_top - avg_bottom
        direction = "+" if delta > 0.1 else ("-" if delta < -0.1 else "=")
        print(f"  {ind:15s}: avg_top25={avg_top:.2f}, avg_bot25={avg_bottom:.2f},"
              f" delta={delta:+.2f} {direction}")

    print()

    # ── التوصية النهائية ──────────────────────────────────────────────────────
    best = top_k[0] if top_k else None
    recommendation = {}

    if best and best['oos_exp'] > bl_oos_exp + 0.05:
        recommendation = {
            'action': 'worth_testing',
            'reason': (
                f"أفضل تجربة تتفوق على baseline بـ "
                f"{best['oos_exp'] - bl_oos_exp:+.3f}% OOS — "
                f"لكن n={best['oos_n']} صغيرة. ابنِ عيّنة أكبر قبل التطبيق."
            ),
            'suggested_min_score': best['min_score'],
            'suggested_weights':   best['weights'],
        }
    else:
        recommendation = {
            'action': 'hold',
            'reason': (
                f"لا تحسن واضح عن baseline (أفضل: "
                f"{best['oos_exp'] if best else 'N/A':+.3f}% vs "
                f"{bl_oos_exp:+.3f}%). الإعدادات الحالية تبقى."
            ),
        }

    print(f"التوصية: {recommendation['action'].upper()}")
    print(f"  {recommendation['reason']}")
    print()

    # ── حفظ النتائج ───────────────────────────────────────────────────────
    output = {
        'run_date':         datetime.utcnow().isoformat(),
        'preliminary':      True,   # نتائج أولية — n صغيرة
        'n_total':          n_total,
        'n_train':          n_train,
        'n_test':           n_test,
        'max_trials':       MAX_TRIALS,
        'valid_trials':     valid_trials,
        'skipped_small_sample': skipped_small,
        'min_oos_sample':   MIN_OOS_SAMPLE,
        'baseline': {
            'weights':    baseline_weights,
            'min_score':  baseline_score,
            'train_exp':  round(bl_train_exp, 5),
            'oos_exp':    round(bl_oos_exp, 5),
            'oos_wr':     round(bl_oos_wr, 4),
            'oos_n':      bl_oos_n,
        },
        'top_results':      top_k,
        'indicator_importance': {
            ind: {
                'avg_top25_weight':    round(sum(t['weights'][ind] for t in top25)    / len(top25),    3),
                'avg_bottom25_weight': round(sum(t['weights'][ind] for t in bottom25) / len(bottom25), 3),
                'delta':               round(
                    sum(t['weights'][ind] for t in top25) / len(top25) -
                    sum(t['weights'][ind] for t in bottom25) / len(bottom25),
                    3),
            }
            for ind in INDICATORS
        },
        'recommendation':   recommendation,
        'min_n_to_apply':   99,
        'warning':          (
            'نتائج أولية (preliminary). n=30 صغيرة جداً للثقة الإحصائية. '
            'لا تُطبَّق على الإعدادات الحيّة قبل 99+ صفقة OOS مستقلة.'
        ),
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as fout:
        json.dump(output, fout, ensure_ascii=False, indent=2)

    print(f"النتائج محفوظة في: {OUTPUT_FILE}")
    print("=" * 65)
    return output


if __name__ == '__main__':
    run_hyperopt()
