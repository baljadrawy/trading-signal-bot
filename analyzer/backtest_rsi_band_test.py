"""
backtest_rsi_band_test.py — اختبار شرائح RSI على 2435+ صفقة تاريخية
----------------------------------------------------------------------
هدف: تحديد ما إذا كانت شريحة RSI>50 لها حافة موجبة بعد الرسوم أم القيد الحالي محمي.

قيود المعرفة:
- لا يوجد RSI خام (0-100) مخزّن تاريخياً — الجدول analysis_results يُحدَّث مع كل مسح
- score_details.rsi = درجة محوّلة (0, 0.3×w, 1.0×w, 1.5×w)
- شرائح قابلة للاستنتاج: 20-30, 30-40, 40-50, >=50

المنهجية:
1. استخراج الشريحة من درجة RSI
2. حساب E_adj (توقع بعد رسوم 0.3%)
3. تقسيم فرعي للحافة (40-50) حسب 1d trend
4. Walk-forward 60/40 لكل شريحة كافية
5. تصحيح FDR (Benjamini-Hochberg)
"""

import json
import sys
import os
import math
import statistics
import random

sys.path.insert(0, '/app')

import asyncio
import asyncpg

DB_URL = "postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals"
FEE_PCT = 0.003  # 0.3% لكل صفقة (رسوم + انزلاق)
TRADE_AMOUNT = 50.0  # USDT


def classify_rsi_band(rsi_score: float) -> str:
    """
    استنتاج شريحة RSI من درجة score_details.rsi

    المنطق (من technical_analyzer.py):
    - RSI 20-30 → score = weight × 1.5 ≈ 1.4-1.5 (weight=1.0 معظم الأحيان)
    - RSI 30-40 → score = weight × 1.0 ≈ 0.57-1.07
    - RSI 40-50 → score = weight × 0.3 ≈ 0.25-0.55
    - RSI >= 50 → score = 0

    ملاحظة: volatile market_condition weight=0.849
    - RSI 30-40 volatile → score ≈ 0.849 → فوق الحد 0.56
    - RSI 40-50 volatile → score ≈ 0.255 → تحت الحد 0.56

    تمييز 30-40 عن 40-50:
    - score=0 → RSI >= 50
    - 0 < score < 0.56 → RSI 40-50 (أو volatile RSI~40)
    - 0.56 <= score < 1.35 → RSI 30-40
    - score >= 1.35 → RSI 20-30
    """
    if rsi_score == 0:
        return ">=50"
    elif rsi_score < 0.56:
        return "40-50"
    elif rsi_score < 1.35:
        return "30-40"
    else:
        return "20-30"


def compute_expectancy(trades):
    """حساب التوقع المعدّل بعد رسوم 0.3%"""
    if not trades:
        return None, 0, 0, 0

    wins = [t for t in trades if t['profit_pct'] is not None and t['profit_pct'] - FEE_PCT * 100 > 0]
    losses = [t for t in trades if t['profit_pct'] is not None and t['profit_pct'] - FEE_PCT * 100 <= 0]

    n = len(trades)
    n_wins = len(wins)
    wr = n_wins / n if n > 0 else 0

    adj_profits = [(t['profit_pct'] - FEE_PCT * 100) for t in trades if t['profit_pct'] is not None]
    if not adj_profits:
        return None, n, 0, 0

    e_adj = statistics.mean(adj_profits)

    # Profit Factor
    gross_wins = sum(p for p in adj_profits if p > 0)
    gross_losses = abs(sum(p for p in adj_profits if p < 0))
    pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')

    return e_adj, n, wr, pf


def permutation_test(trades, n_permutations=1000, seed=42):
    """اختبار دلالة E_adj ≠ 0 باستخدام permutation test"""
    if len(trades) < 5:
        return 1.0

    random.seed(seed)
    adj_profits = [(t['profit_pct'] - FEE_PCT * 100) for t in trades if t['profit_pct'] is not None]
    observed_mean = statistics.mean(adj_profits)

    # حساب p-value باستخدام bootstrap عن الصفر
    count_extreme = 0
    for _ in range(n_permutations):
        sample = [random.choice(adj_profits) for _ in range(len(adj_profits))]
        sample_mean = statistics.mean(sample)
        # اختبار ثنائي الطرف
        if abs(sample_mean) >= abs(observed_mean):
            count_extreme += 1

    # p-value: نسبة العينات التي تساوي أو تتجاوز الملاحظ بافتراض الصفر
    # نصحح: نستخدم resampled zero-centred
    count_extreme = 0
    centered = [p - statistics.mean(adj_profits) for p in adj_profits]
    for _ in range(n_permutations):
        sample = [random.choice(centered) for _ in range(len(centered))]
        if abs(statistics.mean(sample)) >= abs(observed_mean):
            count_extreme += 1

    p_value = (count_extreme + 1) / (n_permutations + 1)
    return p_value


def benjamini_hochberg(p_values, alpha=0.10):
    """تصحيح FDR بطريقة Benjamini-Hochberg"""
    n = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    rejected = [False] * n
    for rank, (i, p) in enumerate(indexed, 1):
        threshold = alpha * rank / n
        if p <= threshold:
            rejected[i] = True
        else:
            break  # بمجرد الفشل نتوقف (BH monotone)
    return rejected


def walk_forward_split(trades, train_ratio=0.60):
    """تقسيم زمني 60/40"""
    if not trades:
        return [], []
    sorted_t = sorted(trades, key=lambda x: x['exit_time'] or '')
    split_idx = int(len(sorted_t) * train_ratio)
    return sorted_t[:split_idx], sorted_t[split_idx:]


async def main():
    conn = await asyncpg.connect(DB_URL)

    print("=" * 70)
    print("اختبار شرائح RSI — بحث فقط (التجميد ساري)")
    print("=" * 70)

    # 1. جلب كل الصفقات المغلقة مع درجة RSI
    rows = await conn.fetch("""
        SELECT
            tr.id,
            tr.symbol,
            tr.result,
            tr.profit_percent,
            tr.profit_usdt,
            tr.target_reached,
            tr.stop_hit,
            tr.duration_hours,
            tr.exit_time,
            s.market_condition,
            s.timeframe,
            s.score,
            s.signal_time,
            s.score_details,
            s.entry_price,
            s.target_1,
            s.stop_loss
        FROM trade_results tr
        JOIN signals s ON tr.signal_id = s.id
        WHERE tr.result IN ('WIN', 'LOSS')
          AND tr.profit_percent IS NOT NULL
          AND s.score_details IS NOT NULL
          AND s.score_details ? 'rsi'
        ORDER BY tr.exit_time
    """)

    print(f"\nإجمالي الصفقات القابلة للتحليل: {len(rows)}")

    # 2. تصنيف كل صفقة حسب شريحة RSI
    trades_by_band = {"20-30": [], "30-40": [], "40-50": [], ">=50": []}
    unclassified = 0

    for row in rows:
        try:
            details = json.loads(row['score_details']) if isinstance(row['score_details'], str) else row['score_details']
            rsi_score = float(details.get('rsi', 0))
        except (TypeError, ValueError):
            unclassified += 1
            continue

        band = classify_rsi_band(rsi_score)
        trades_by_band[band].append({
            'id': row['id'],
            'symbol': row['symbol'],
            'result': row['result'],
            'profit_pct': float(row['profit_percent']),
            'profit_usdt': float(row['profit_usdt'] or 0),
            'target_reached': row['target_reached'],
            'stop_hit': row['stop_hit'],
            'duration_hours': float(row['duration_hours'] or 0),
            'exit_time': str(row['exit_time']),
            'market_condition': row['market_condition'],
            'timeframe': row['timeframe'],
            'score': row['score'],
            'signal_time': str(row['signal_time']),
            'rsi_score': rsi_score,
        })

    print(f"غير مُصنَّف: {unclassified}")
    print(f"\nتوزيع الشرائح:")
    for band, t in trades_by_band.items():
        print(f"  RSI {band}: n={len(t)}")

    # 3. حساب الإحصائيات لكل شريحة
    print("\n" + "=" * 70)
    print("جدول الشرائح — E_adj بعد رسوم 0.3%")
    print("=" * 70)
    print(f"{'شريحة RSI':<12} {'n':>5} {'WR':>7} {'E_adj%':>8} {'PF':>6} {'T1':>4} {'T2':>4} {'T3':>4} {'p-val':>7}")
    print("-" * 70)

    band_results = {}
    all_p_values = []
    band_order = ["20-30", "30-40", "40-50", ">=50"]

    for band in band_order:
        trades = trades_by_band[band]
        if len(trades) < 5:
            print(f"RSI {band:<9} {'n='+str(len(trades)):>6} — بيانات غير كافية")
            band_results[band] = {'n': len(trades), 'skip': True}
            all_p_values.append(1.0)
            continue

        e_adj, n, wr, pf = compute_expectancy(trades)
        p_val = permutation_test(trades)
        all_p_values.append(p_val)

        t1 = sum(1 for t in trades if (t['target_reached'] or 0) >= 1)
        t2 = sum(1 for t in trades if (t['target_reached'] or 0) >= 2)
        t3 = sum(1 for t in trades if (t['target_reached'] or 0) >= 3)

        print(f"RSI {band:<9} {n:>5} {wr*100:>6.1f}% {e_adj:>8.3f} {pf:>6.2f} {t1:>4} {t2:>4} {t3:>4} {p_val:>7.3f}")

        band_results[band] = {
            'n': n, 'wr': wr, 'e_adj': e_adj, 'pf': pf,
            'p_val': p_val, 't1': t1, 't2': t2, 't3': t3,
            'trades': trades, 'skip': False
        }

    # 4. تصحيح FDR
    print("\n--- تصحيح FDR (Benjamini-Hochberg، α=10%) ---")
    rejected = benjamini_hochberg(all_p_values)
    for i, band in enumerate(band_order):
        if band in band_results and not band_results[band].get('skip'):
            sig_str = "* دال" if rejected[i] else "  غير دال"
            print(f"  RSI {band}: p={all_p_values[i]:.3f} → {sig_str}")

    # 5. تقسيم فرعي: شريحة (40-50) حسب timeframe=1d و market_condition
    print("\n" + "=" * 70)
    print("تقسيم فرعي: شريحة RSI 40-50 حسب 1d trend")
    print("=" * 70)

    band_40_50 = trades_by_band["40-50"]
    subgroups = {}
    for t in band_40_50:
        if t['timeframe'] == '1d':
            key = f"1d+{t['market_condition']}"
        else:
            key = f"{t['timeframe']}+{t['market_condition']}"
        subgroups.setdefault(key, []).append(t)

    # أيضاً عرض المجموع للـ 1d كلياً
    all_1d = [t for t in band_40_50 if t['timeframe'] == '1d']
    if all_1d:
        subgroups['1d+ALL'] = all_1d

    print(f"{'مجموعة':<22} {'n':>5} {'WR':>7} {'E_adj%':>8} {'PF':>6}")
    print("-" * 55)
    for key in sorted(subgroups.keys(), key=lambda x: -len(subgroups[x])):
        sg = subgroups[key]
        if len(sg) < 3:
            print(f"{key:<22} {len(sg):>5}   — غير كافٍ")
            continue
        e_adj, n, wr, pf = compute_expectancy(sg)
        print(f"{key:<22} {n:>5} {wr*100:>6.1f}% {e_adj:>8.3f} {pf:>6.2f}")

    # 6. Walk-Forward لكل شريحة كافية (n>=30)
    print("\n" + "=" * 70)
    print("Walk-Forward 60/40 (زمني) لكل شريحة ذات n>=30")
    print("=" * 70)
    print(f"{'شريحة RSI':<12} {'n_train':>8} {'E_IS%':>8} {'n_test':>8} {'E_OOS%':>8} {'WR_OOS':>8}")
    print("-" * 60)

    for band in band_order:
        res = band_results.get(band, {})
        if res.get('skip') or res.get('n', 0) < 30:
            if not res.get('skip'):
                print(f"RSI {band:<9} — n={res.get('n',0)} < 30, غير كافٍ")
            continue

        trades = res['trades']
        train, test = walk_forward_split(trades)

        e_is, n_is, wr_is, _ = compute_expectancy(train)
        e_oos, n_oos, wr_oos, _ = compute_expectancy(test)

        print(f"RSI {band:<9} {n_is:>8} {e_is:>8.3f} {n_oos:>8} {e_oos:>8.3f} {wr_oos*100:>7.1f}%")

    # 7. تحليل إضافي: >=50 منقسم حسب timeframe (هل 1d bearish يختلف؟)
    print("\n" + "=" * 70)
    print("تحليل RSI>=50: هل هناك edge في 1d+bearish/sideways؟")
    print("=" * 70)
    print("(المعيار: كيف تؤدي الإشارات التي RSI>=50 مع أهم شريحة معروفة)")
    print()

    band_50plus = trades_by_band[">=50"]
    subgroups_50 = {}
    for t in band_50plus:
        if t['timeframe'] == '1d' and t['market_condition'] in ('bearish', 'sideways'):
            key = f"1d+{t['market_condition']}"
            subgroups_50.setdefault(key, []).append(t)
        else:
            key = f"other_{t['timeframe']}"
            subgroups_50.setdefault(key, []).append(t)

    # ملخص مجمّع
    edge_1d_50 = [t for t in band_50plus if t['timeframe'] == '1d' and t['market_condition'] in ('bearish', 'sideways')]
    rest_50 = [t for t in band_50plus if not (t['timeframe'] == '1d' and t['market_condition'] in ('bearish', 'sideways'))]

    print(f"{'مجموعة':<30} {'n':>5} {'WR':>7} {'E_adj%':>8} {'PF':>6}")
    print("-" * 60)

    if len(edge_1d_50) >= 3:
        e_adj, n, wr, pf = compute_expectancy(edge_1d_50)
        print(f"{'1d+bearish/sideways (RSI>=50)':<30} {n:>5} {wr*100:>6.1f}% {e_adj:>8.3f} {pf:>6.2f}")
    else:
        print(f"{'1d+bearish/sideways (RSI>=50)':<30}   n={len(edge_1d_50)} — غير كافٍ")

    if len(rest_50) >= 5:
        e_adj, n, wr, pf = compute_expectancy(rest_50)
        print(f"{'باقي >=50 (non-edge)':<30} {n:>5} {wr*100:>6.1f}% {e_adj:>8.3f} {pf:>6.2f}")

    e_all_50, n_all_50, wr_all_50, pf_all_50 = compute_expectancy(band_50plus)
    if n_all_50 > 0:
        print(f"{'كل RSI>=50':<30} {n_all_50:>5} {wr_all_50*100:>6.1f}% {e_all_50:>8.3f} {pf_all_50:>6.2f}")

    # 8. ملخص الحكم
    print("\n" + "=" * 70)
    print("الحكم والاستنتاجات")
    print("=" * 70)

    for band in band_order:
        res = band_results.get(band, {})
        if res.get('skip'):
            continue
        e = res.get('e_adj', 0)
        p = res.get('p_val', 1)
        n = res.get('n', 0)
        status = "إيجابي" if e > 0 else "سالب"
        sig = "دال إحصائياً (BH)" if rejected[band_order.index(band)] else "غير دال"
        print(f"RSI {band}: E_adj={e:.3f}% | {status} | {sig} | n={n}")

    await conn.close()
    print("\nانتهى التحليل.")


if __name__ == "__main__":
    asyncio.run(main())
