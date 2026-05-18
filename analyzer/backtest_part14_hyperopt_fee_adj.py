"""
الباكتيستر — الجزء الرابع عشر: Hyperopt مع E_adj (بعد رسوم 0.3%)
===================================================================
نفس منهج الجزء التاسع (5-fold K-Fold Walk-Forward، 500 تجربة عشوائية)
لكن دالة الخسارة = expectancy مُعدَّلة بعد حسم رسوم Binance 0.3% لكل صفقة.

الهدف: إيجاد أوزان تُحقق E_adj > 0 على بيانات تاريخية مع التحقق OOS.

الجديد عن الجزء 9:
  - FEE_PCT = 0.003 (0.3% لكل صفقة)
  - دالة expectancy_adj تحسم الرسوم من profit_percent قبل الحساب
  - تركيز على 1d+bearish/sideways+score3 (الحافة المُثبتة)
  - إحصائيات مفصّلة لأفضل 10 توليفات

المخرج: backtest_results_part14.jsonl
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

OUTPUT_FILE = '/app/backtest_results_part14.jsonl'

# رسوم Binance + انزلاق (0.2% + 0.1%)
FEE_PCT = 0.003

INDICATORS = [
    'rsi', 'bollinger', 'stoch_rsi', 'rsi_divergence',
    'fibonacci', 'macd', 'ema_cross', 'volume', 'obv', 'btc_trend'
]

# فضاء البحث — مُعطَّلات ثابتة عند 0
WEIGHT_SPACE = {
    'rsi':            (0.5, 2.0, 0.25),
    'bollinger':      (0.0, 2.0, 0.25),
    'stoch_rsi':      (0.0, 2.0, 0.25),
    'rsi_divergence': (0.0, 3.0, 0.5),
    'fibonacci':      (0.0, 2.0, 0.25),
    'macd':           (0.0, 0.0, 1.0),   # معطّل
    'ema_cross':      (0.0, 0.0, 1.0),   # معطّل
    'volume':         (0.0, 0.0, 1.0),   # معطّل
    'obv':            (0.0, 0.0, 1.0),   # معطّل
    'btc_trend':      (0.0, 0.0, 1.0),   # معطّل
}

MIN_SCORE_CANDIDATES = [2.5, 3.0, 3.5, 4.0]
MAX_TRIALS  = 500
N_FOLDS     = 5
MIN_FOLD_N  = 5
TOP_K       = 10
RANDOM_SEED = 42


async def load_trades() -> List[Dict]:
    """يحمّل الصفقات من DB مع score_details."""
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
    """يُعيد حساب النقاط بأوزان جديدة."""
    sd = trade.get('score_details', {})
    total = 0.0
    for ind in INDICATORS:
        raw = float(sd.get(ind, 0.0))
        total += raw * weights.get(ind, 0.0)
    return round(total, 4)


def expectancy_adj(trades: List[Dict], fee_pct: float = FEE_PCT) -> float:
    """
    Expectancy مُعدَّلة بعد حسم الرسوم.
    profit_percent هو الربح الخام؛ نحسم fee_pct * 100 (بالنسبة المئوية).
    ثم نُحوّل للدولار بافتراض TRADE_AMOUNT=50 USDT.
    """
    if not trades:
        return 0.0
    TRADE_AMOUNT = 50.0
    fee_pct_display = fee_pct * 100  # 0.3%

    adj_profits = []
    for t in trades:
        raw_pct = t['profit_percent']
        adj_pct = raw_pct - fee_pct_display  # حسم الرسوم من النسبة المئوية
        adj_usdt = (adj_pct / 100.0) * TRADE_AMOUNT
        adj_profits.append({
            'result': t['result'],
            'profit_usdt': adj_usdt,
            'profit_percent': adj_pct,
        })

    wins = [t for t in adj_profits if t['profit_usdt'] > 0]
    losses = [t for t in adj_profits if t['profit_usdt'] <= 0]
    wr = len(wins) / len(adj_profits)
    avg_win = sum(t['profit_usdt'] for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t['profit_usdt'] for t in losses) / len(losses) if losses else 0.0
    return wr * avg_win + (1 - wr) * avg_loss


def expectancy_raw(trades: List[Dict]) -> float:
    """Expectancy الخام بدون رسوم (للمقارنة)."""
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
) -> Tuple[float, float, int, float, float]:
    """
    K-Fold Walk-Forward مع E_adj.
    تُعيد: (avg_oos_exp_adj, avg_oos_wr, avg_oos_n, avg_train_exp_adj, avg_oos_exp_raw)
    """
    fold_size = len(trades) // n_folds
    oos_exps_adj, oos_exps_raw, oos_wrs, oos_ns = [], [], [], []
    train_exps_adj = []

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

        oos_exps_adj.append(expectancy_adj(test_pass))
        oos_exps_raw.append(expectancy_raw(test_pass))
        oos_wrs.append(len([t for t in test_pass if t['result'] == 'WIN']) / len(test_pass))
        oos_ns.append(len(test_pass))
        train_exps_adj.append(expectancy_adj(train_pass))

    if not oos_exps_adj:
        return -999.0, 0.0, 0, -999.0, -999.0

    avg_oos_exp_adj = sum(oos_exps_adj) / len(oos_exps_adj)
    avg_oos_exp_raw = sum(oos_exps_raw) / len(oos_exps_raw)
    avg_oos_wr = sum(oos_wrs) / len(oos_wrs)
    avg_oos_n = int(sum(oos_ns) / len(oos_ns))
    avg_train_exp_adj = sum(train_exps_adj) / len(train_exps_adj)

    return avg_oos_exp_adj, avg_oos_wr, avg_oos_n, avg_train_exp_adj, avg_oos_exp_raw


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


def analyze_edge_slice(trades: List[Dict], weights: Dict[str, float], min_score: float) -> Dict:
    """تحليل مفصّل للحافة 1d+bearish/sideways+score3 مع الأوزان المُعطاة."""
    filtered = [t for t in trades
                if t['timeframe'] == '1d'
                and t['market_condition'] in ('bearish', 'sideways')
                and rescore(t, weights) >= min_score]

    if not filtered:
        return {'n': 0, 'wr': 0, 'e_adj': 0, 'e_raw': 0}

    wins = [t for t in filtered if t['result'] == 'WIN']
    wr = len(wins) / len(filtered)
    e_adj = expectancy_adj(filtered)
    e_raw = expectancy_raw(filtered)

    return {
        'n': len(filtered),
        'wr': round(wr * 100, 1),
        'e_adj': round(e_adj, 4),
        'e_raw': round(e_raw, 4),
    }


async def run_hyperopt():
    print("=" * 70)
    print("الجزء 14: Hyperopt مع E_adj (رسوم 0.3%) — K-Fold Walk-Forward")
    print("التاريخ:", datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'))
    print("=" * 70)

    await Database.connect()
    trades = await load_trades()
    n = len(trades)
    print(f"\nعدد الصفقات المحملة: {n}")

    if n == 0:
        print("لا صفقات — إنهاء.")
        await Database.close()
        return

    rng = random.Random(RANDOM_SEED)

    # Baseline — الأوزان الحالية
    baseline_w = {
        'rsi': 1.0, 'bollinger': 1.0, 'stoch_rsi': 1.0,
        'rsi_divergence': 1.0, 'fibonacci': 1.0,
        'macd': 0.0, 'ema_cross': 0.0, 'volume': 0.0,
        'obv': 0.0, 'btc_trend': 0.0
    }
    bl_oos_adj, bl_oos_wr, bl_oos_n, bl_train_adj, bl_oos_raw = kfold_score(trades, baseline_w, 3.0)
    print(f"\nBaseline (أوزان=1.0 للكل، min_score=3.0):")
    print(f"  OOS E_adj={bl_oos_adj:+.4f}$, OOS E_raw={bl_oos_raw:+.4f}$, OOS-WR={bl_oos_wr*100:.1f}%, avg_n={bl_oos_n}")

    # Baseline مع rsi_divergence=2.0 (الإعداد الحالي في DB)
    baseline_w_live = {**baseline_w, 'rsi_divergence': 2.0}
    bl2_oos_adj, bl2_oos_wr, bl2_oos_n, bl2_train_adj, bl2_oos_raw = kfold_score(trades, baseline_w_live, 3.0)
    print(f"\nBaseline Live (rsi_div=2.0، min_score=3.0):")
    print(f"  OOS E_adj={bl2_oos_adj:+.4f}$, OOS E_raw={bl2_oos_raw:+.4f}$, OOS-WR={bl2_oos_wr*100:.1f}%, avg_n={bl2_oos_n}")

    # تحليل الحافة المُثبتة بالأوزان الحالية
    edge_live = analyze_edge_slice(trades, baseline_w_live, 3.0)
    print(f"\nحافة 1d+bearish/sideways+score3 (كامل البيانات، رسوم محسومة):")
    print(f"  n={edge_live['n']}, WR={edge_live['wr']}%, E_adj={edge_live['e_adj']:+.4f}$, E_raw={edge_live['e_raw']:+.4f}$")

    print(f"\n{'='*70}")
    print(f"بدء الـ Hyperopt: {MAX_TRIALS} تجربة × {N_FOLDS}-Fold...")
    print(f"{'='*70}\n")

    top_results = []
    skipped = 0

    for trial in range(MAX_TRIALS):
        w = sample_weights(rng)
        ms = rng.choice(MIN_SCORE_CANDIDATES)

        oos_adj, oos_wr, oos_n, train_adj, oos_raw = kfold_score(trades, w, ms)

        if oos_n < MIN_FOLD_N:
            skipped += 1
            continue

        # نسجّل فقط التوليفات التي تتفوق على الـ baseline في E_adj
        result = {
            'trial': trial,
            'weights': w,
            'min_score': ms,
            'oos_exp_adj': round(oos_adj, 4),
            'oos_exp_raw': round(oos_raw, 4),
            'oos_wr': round(oos_wr, 4),
            'oos_n': oos_n,
            'train_exp_adj': round(train_adj, 4),
            'overfit_gap': round(train_adj - oos_adj, 4),
            'edge_slice': analyze_edge_slice(trades, w, ms),
        }
        top_results.append(result)

        if (trial + 1) % 100 == 0:
            ranked = sorted(top_results, key=lambda x: x['oos_exp_adj'], reverse=True)
            best = ranked[0] if ranked else None
            print(f"تجربة {trial+1}/{MAX_TRIALS} | أفضل E_adj={best['oos_exp_adj']:+.4f}$ "
                  f"(WR={best['oos_wr']*100:.1f}%, n={best['oos_n']}, ms={best['min_score']})")

    # ترتيب النتائج
    top_results.sort(key=lambda x: x['oos_exp_adj'], reverse=True)
    top10 = top_results[:TOP_K]
    positive_adj = [r for r in top_results if r['oos_exp_adj'] > 0]

    print(f"\n{'='*70}")
    print(f"النتائج النهائية:")
    print(f"  إجمالي التجارب: {MAX_TRIALS} | محجوبة (n<{MIN_FOLD_N}): {skipped}")
    print(f"  نتائج E_adj>0 (إيجابية بعد الرسوم): {len(positive_adj)}/{len(top_results)}")
    print(f"\nأفضل 10 توليفات (مرتّبة بـ E_adj):")
    print(f"{'#':>3} {'E_adj':>8} {'E_raw':>8} {'WR':>6} {'n':>4} {'ms':>5} {'overfit':>8} | slice_n WR% E_adj")
    print("-" * 80)

    for i, r in enumerate(top10):
        sl = r['edge_slice']
        print(f"{i+1:>3} {r['oos_exp_adj']:>+8.4f} {r['oos_exp_raw']:>+8.4f} "
              f"{r['oos_wr']*100:>5.1f}% {r['oos_n']:>4} {r['min_score']:>5} "
              f"{r['overfit_gap']:>+8.4f} | {sl['n']:>7} {sl.get('wr', 0):>4.1f}% {sl.get('e_adj', 0):>+.4f}$")

    # حفظ النتائج
    results_out = {
        'meta': {
            'date': datetime.utcnow().isoformat(),
            'n_trades': n,
            'fee_pct': FEE_PCT,
            'max_trials': MAX_TRIALS,
            'n_folds': N_FOLDS,
            'skipped': skipped,
            'positive_adj_count': len(positive_adj),
        },
        'baseline': {
            'oos_exp_adj': round(bl_oos_adj, 4),
            'oos_exp_raw': round(bl_oos_raw, 4),
            'oos_wr': round(bl_oos_wr, 4),
            'oos_n': bl_oos_n,
        },
        'baseline_live': {
            'rsi_divergence_w': 2.0,
            'oos_exp_adj': round(bl2_oos_adj, 4),
            'oos_exp_raw': round(bl2_oos_raw, 4),
            'oos_wr': round(bl2_oos_wr, 4),
            'oos_n': bl2_oos_n,
        },
        'edge_slice_live': edge_live,
        'top10': top10,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results_out, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nالنتائج حُفظت في: {OUTPUT_FILE}")

    # خلاصة التوصية
    if top10:
        best = top10[0]
        print(f"\n{'='*70}")
        print("الخلاصة:")
        bl_e = bl2_oos_adj  # baseline live
        best_e = best['oos_exp_adj']
        improvement = best_e - bl_e
        print(f"  Baseline Live E_adj = {bl_e:+.4f}$")
        print(f"  أفضل توليفة   E_adj = {best_e:+.4f}$ (تحسن: {improvement:+.4f}$)")
        print(f"  min_score المثالي  = {best['min_score']}")
        w = best['weights']
        print(f"  الأوزان المثالية: rsi={w['rsi']}, boll={w['bollinger']}, stoch={w['stoch_rsi']}, rsi_div={w['rsi_divergence']}, fib={w['fibonacci']}")
        print(f"  Overfit gap = {best['overfit_gap']:+.4f}$ (أصغر = أقل overfit)")

        if best_e > 0:
            print(f"\n  ملاحظة: التوليفة المثلى تُحقق E_adj إيجابية — تُقترح للمراجعة بعد رفع التجميد")
        else:
            print(f"\n  ملاحظة: لا توليفة تُحقق E_adj>0 مع {n} صفقة — الحافة ضعيفة أو العينة صغيرة")

    await Database.close()
    print("\nانتهى الجزء 14.")


if __name__ == '__main__':
    asyncio.run(run_hyperopt())
