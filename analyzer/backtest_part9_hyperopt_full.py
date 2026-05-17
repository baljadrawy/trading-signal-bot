"""
الباكتيستر — الجزء التاسع: Hyperopt على البيانات الكاملة (265 صفقة)
===================================================================
نفس منهج الجزء السادس، لكن على كامل trade_results من DB (لا من jsonl).

التغيير عن الجزء 6:
  - n=265 بدل n=30 → نتائج أكثر موثوقية
  - يقرأ من DB مباشرة عبر asyncio
  - يستخدم 5-fold Walk-Forward بدل 60/40 ثابت

المخرج: backtest_results_part9.jsonl
"""

import asyncio
import json
import os
import random
import sys
from datetime import datetime
from typing import Dict, List, Tuple

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')

from shared.database import Database

OUTPUT_FILE = '/app/backtest_results_part9.jsonl'

INDICATORS = [
    'rsi', 'bollinger', 'stoch_rsi', 'rsi_divergence',
    'fibonacci', 'macd', 'ema_cross', 'volume', 'obv', 'btc_trend'
]

WEIGHT_SPACE = {
    'rsi':            (0.5, 2.0, 0.25),  # RSI أقوى مؤشر — لا نُلغيه
    'bollinger':      (0.0, 2.0, 0.25),
    'stoch_rsi':      (0.0, 2.0, 0.25),
    'rsi_divergence': (0.0, 3.0, 0.5),
    'fibonacci':      (0.0, 2.0, 0.25),
    'macd':           (0.0, 0.0, 1.0),   # مُعطَّل — ثابت عند 0
    'ema_cross':      (0.0, 0.0, 1.0),   # مُعطَّل
    'volume':         (0.0, 0.0, 1.0),   # مُعطَّل
    'obv':            (0.0, 0.0, 1.0),   # مُعطَّل
    'btc_trend':      (0.0, 0.0, 1.0),   # مُعطَّل
}

MIN_SCORE_CANDIDATES = [2.5, 3.0, 3.5, 4.0]
MAX_TRIALS  = 500
N_FOLDS     = 5
MIN_FOLD_N  = 5
TOP_K       = 10
RANDOM_SEED = 42


async def load_trades() -> List[Dict]:
    rows = await Database.fetch("""
        SELECT
            tr.result,
            tr.profit_usdt,
            tr.profit_percent,
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
        ORDER BY s.signal_time ASC
    """)
    result = []
    for r in rows:
        sd = r['score_details']
        if isinstance(sd, str):
            sd = json.loads(sd)
        result.append({
            'result': r['result'],
            'profit_usdt': float(r['profit_usdt']),
            'profit_percent': float(r['profit_percent'] or 0),
            'signal_time': str(r['signal_time']),
            'score': r['score'],
            'timeframe': r['timeframe'],
            'market_condition': r['market_condition'],
            'score_details': sd or {},
        })
    return result


def rescore(trade: Dict, weights: Dict[str, float]) -> float:
    """يُعيد حساب النقاط بأوزان جديدة. score_details تحتوي القيم الخام."""
    sd = trade.get('score_details', {})
    total = 0.0
    for ind in INDICATORS:
        raw = float(sd.get(ind, 0.0))
        total += raw * weights.get(ind, 0.0)
    return round(total, 4)


def expectancy(trades: List[Dict]) -> float:
    if not trades:
        return 0.0
    wins = [t for t in trades if t['result'] == 'WIN']
    losses = [t for t in trades if t['result'] == 'LOSS']
    wr = len(wins) / len(trades)
    avg_win = sum(t['profit_usdt'] for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t['profit_usdt'] for t in losses) / len(losses) if losses else 0.0
    return wr * avg_win + (1 - wr) * avg_loss


def kfold_score(
    trades: List[Dict],
    weights: Dict[str, float],
    min_score: float,
    n_folds: int = N_FOLDS,
) -> Tuple[float, float, int, float]:
    """
    K-Fold Walk-Forward: لكل fold، نُعيد التسجيل ونُطبّق العتبة.
    تُعيد: (avg_oos_exp, avg_oos_wr, avg_oos_n, train_exp)
    """
    fold_size = len(trades) // n_folds
    oos_exps, oos_wrs, oos_ns = [], [], []
    train_exps = []

    for i in range(n_folds):
        s, e = i * fold_size, (i + 1) * fold_size if i < n_folds - 1 else len(trades)
        test_fold = trades[s:e]
        train_fold = trades[:s] + trades[e:]

        def apply_filter(subset):
            return [t for t in subset if rescore(t, weights) >= min_score]

        test_pass = apply_filter(test_fold)
        train_pass = apply_filter(train_fold)

        if len(test_pass) < MIN_FOLD_N:
            continue

        oos_exps.append(expectancy(test_pass))
        oos_wrs.append(len([t for t in test_pass if t['result'] == 'WIN']) / len(test_pass))
        oos_ns.append(len(test_pass))
        train_exps.append(expectancy(train_pass))

    if not oos_exps:
        return -999.0, 0.0, 0, -999.0

    avg_oos_exp = sum(oos_exps) / len(oos_exps)
    avg_oos_wr = sum(oos_wrs) / len(oos_wrs)
    avg_oos_n = int(sum(oos_ns) / len(oos_ns))
    avg_train_exp = sum(train_exps) / len(train_exps)

    return avg_oos_exp, avg_oos_wr, avg_oos_n, avg_train_exp


def sample_weights(rng: random.Random) -> Dict[str, float]:
    weights = {}
    for ind in INDICATORS:
        lo, hi, step = WEIGHT_SPACE[ind]
        if hi == lo:
            weights[ind] = lo
        else:
            steps = int((hi - lo) / step) + 1
            choice = rng.randint(0, steps - 1)
            weights[ind] = round(lo + choice * step, 4)
    return weights


async def run_hyperopt():
    print("=" * 65)
    print("الجزء 9: Hyperopt على 265 صفقة — K-Fold Walk-Forward")
    print("التاريخ:", datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'))
    print("=" * 65)

    await Database.connect()
    trades = await load_trades()
    n = len(trades)
    print(f"\nعدد الصفقات المحملة: {n}")

    rng = random.Random(RANDOM_SEED)

    # Baseline
    baseline_w = {ind: 1.0 if ind in ('rsi', 'bollinger', 'stoch_rsi', 'rsi_divergence', 'fibonacci')
                  else 0.0 for ind in INDICATORS}
    bl_oos_exp, bl_oos_wr, bl_oos_n, bl_train_exp = kfold_score(trades, baseline_w, 3.0)
    print(f"\nBaseline (أوزان الحالية، min_score=3.0):")
    print(f"  OOS-E={bl_oos_exp:+.4f}, OOS-WR={bl_oos_wr*100:.1f}%, avg_n={bl_oos_n}")

    top_results = []
    skipped = 0

    for trial in range(MAX_TRIALS):
        w = sample_weights(rng)
        ms = rng.choice(MIN_SCORE_CANDIDATES)

        oos_exp, oos_wr, oos_n, train_exp = kfold_score(trades, w, ms)

        if oos_n < MIN_FOLD_N:
            skipped += 1
            continue

        result = {
            'trial': trial,
            'weights': w,
            'min_score': ms,
            'oos_exp': round(oos_exp, 5),
            'oos_wr': round(oos_wr, 4),
            'oos_n': oos_n,
            'train_exp': round(train_exp, 5),
            'overfit_gap': round(train_exp - oos_exp, 5),
        }

        if len(top_results) < TOP_K or oos_exp > top_results[-1]['oos_exp']:
            top_results.append(result)
            top_results.sort(key=lambda x: x['oos_exp'], reverse=True)
            if len(top_results) > TOP_K:
                top_results.pop()

        if trial % 100 == 0:
            best = top_results[0] if top_results else None
            if best:
                print(f"Trial {trial}/{MAX_TRIALS}: best OOS-E={best['oos_exp']:+.4f}"
                      f" (WR={best['oos_wr']*100:.1f}%, n={best['oos_n']})")

    print(f"\nمكتمل: {MAX_TRIALS} تجربة ({skipped} مرفوضة لعينة صغيرة)")
    print(f"\nأفضل {len(top_results)} نتيجة:")
    for r in top_results:
        print(f"  Trial {r['trial']}: OOS-E={r['oos_exp']:+.4f},"
              f" WR={r['oos_wr']*100:.1f}%, n={r['oos_n']}, ms={r['min_score']}")

    # تحليل أهمية المؤشرات
    active_inds = [ind for ind in INDICATORS
                   if WEIGHT_SPACE[ind][0] != WEIGHT_SPACE[ind][1]]

    # مقارنة أعلى 25% vs أسفل 25%
    sorted_by_oos = sorted(top_results + [
        {'oos_exp': bl_oos_exp, 'oos_wr': bl_oos_wr, 'oos_n': bl_oos_n,
         'weights': baseline_w, 'min_score': 3.0, 'trial': -1,
         'train_exp': bl_train_exp, 'overfit_gap': 0}
    ], key=lambda x: x['oos_exp'], reverse=True)

    importance = {}
    if len(sorted_by_oos) >= 4:
        top_q = sorted_by_oos[:max(1, len(sorted_by_oos)//4)]
        bot_q = sorted_by_oos[-max(1, len(sorted_by_oos)//4):]
        for ind in active_inds:
            top_avg = sum(r['weights'].get(ind, 0) for r in top_q) / len(top_q)
            bot_avg = sum(r['weights'].get(ind, 0) for r in bot_q) / len(bot_q)
            importance[ind] = {'top25': round(top_avg, 3), 'bot25': round(bot_avg, 3),
                               'delta': round(top_avg - bot_avg, 3)}

    if importance:
        print("\nأهمية المؤشرات (top25 vs bot25):")
        for ind, v in sorted(importance.items(), key=lambda x: abs(x[1]['delta']), reverse=True):
            print(f"  {ind:20}: delta={v['delta']:+.3f} (top={v['top25']:.2f}, bot={v['bot25']:.2f})")

    # أفضل توصية
    best = top_results[0] if top_results else None
    if best and best['oos_exp'] > bl_oos_exp + 0.05:
        action = 'worth_testing'
        reason = f"أفضل trial تتفوق على baseline بـ {best['oos_exp']-bl_oos_exp:+.3f} OOS"
    else:
        action = 'hold'
        reason = 'لا تحسين واضح على baseline'

    output = {
        'run_date': datetime.utcnow().isoformat(),
        'part': 9,
        'description': 'Hyperopt على 265 صفقة — K-Fold Walk-Forward',
        'n_total': n,
        'n_folds': N_FOLDS,
        'max_trials': MAX_TRIALS,
        'skipped': skipped,
        'baseline': {
            'weights': baseline_w,
            'min_score': 3.0,
            'oos_exp': bl_oos_exp,
            'oos_wr': bl_oos_wr,
            'oos_n': bl_oos_n,
        },
        'top_results': top_results,
        'indicator_importance': importance,
        'recommendation': {
            'action': action,
            'reason': reason,
            'best_weights': best['weights'] if best else None,
            'best_min_score': best['min_score'] if best else 3.0,
        },
        'warning': (
            'الـ Hyperopt تعمل على n=265 صفقة — أكبر بكثير من الجزء 6 (n=30). '
            'إذا action=worth_testing وOOS-E إيجابي على 3+ folds، '
            'يمكن تجربة الأوزان على الإشارات الجديدة بحذر. '
            'min_n_to_apply_live = 50 إشارة جديدة قبل قرار نهائي.'
        ),
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nالنتائج محفوظة: {OUTPUT_FILE}")
    await Database.disconnect()


if __name__ == '__main__':
    asyncio.run(run_hyperopt())
