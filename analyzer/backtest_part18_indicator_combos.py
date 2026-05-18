#!/usr/bin/env python3
"""
Backtest Part 18 — Indicator Combination Analysis
الهدف: اختبار توليفات مختزلة من المؤشرات على شريحة 1d+bearish/sideways
المصدر: score_details المخزّنة في قاعدة البيانات — بلا API
القاعدة: بحث فقط، التجميد ساري، لا تعديل على الاستراتيجية الحيّة
"""

import os
import sys
import json
import asyncio
import asyncpg
from itertools import combinations
from collections import defaultdict

# ─── إعدادات الاتصال ─────────────────────────────────────────────────────────
DB_DSN = (
    f"postgresql://{os.getenv('POSTGRES_USER', 'trading_signal_bot')}"
    f":{os.getenv('POSTGRES_PASSWORD', '6psgaD1GV2ClGtopvSe5Lm8za')}"
    f"@{os.getenv('POSTGRES_HOST', 'postgres')}"
    f":5432"
    f"/{os.getenv('POSTGRES_DB', 'trading_signals')}"
)

FEE = 0.003  # 0.3% per trade (fees + slippage)

# ─── المؤشرات المتاحة في المخطط القديم (قبل rebuild) ─────────────────────────
# rsi_divergence و fibonacci غير متاحَين في المخطط القديم (7 إشارات فقط)
OLD_SCHEMA_INDICATORS = [
    "rsi", "bollinger", "stoch_rsi", "order_book",
    "macd", "ema_cross", "obv"
]

# ─── التوليفات المطلوبة في الطلب ─────────────────────────────────────────────
# التوليفة الحالية (المخطط القديم): كل المؤشرات السبعة
# التوليفات المطلوبة في الطلب (مع ملاحظة: rsi_div/fibonacci غير متاحَين في old schema)
NAMED_COMBOS = {
    "all_7 (baseline)": ["rsi", "bollinger", "stoch_rsi", "order_book", "macd", "ema_cross", "obv"],
    "RSI+Bollinger": ["rsi", "bollinger"],
    "RSI+Stoch": ["rsi", "stoch_rsi"],
    "RSI+OB": ["rsi", "order_book"],
    "RSI+MACD": ["rsi", "macd"],
    "RSI+EMA": ["rsi", "ema_cross"],
    "RSI only": ["rsi"],
    "Bollinger+Stoch": ["bollinger", "stoch_rsi"],
    "RSI+Bollinger+Stoch": ["rsi", "bollinger", "stoch_rsi"],
    "RSI+Bollinger+OB": ["rsi", "bollinger", "order_book"],
    "RSI+Stoch+OB": ["rsi", "stoch_rsi", "order_book"],
    "RSI+MACD+OB": ["rsi", "macd", "order_book"],
    "RSI+MACD+Stoch": ["rsi", "macd", "stoch_rsi"],
    "Stoch+OB+MACD": ["stoch_rsi", "order_book", "macd"],
    "all_minus_OBV": ["rsi", "bollinger", "stoch_rsi", "order_book", "macd", "ema_cross"],
    "all_minus_EMA": ["rsi", "bollinger", "stoch_rsi", "order_book", "macd", "obv"],
}

TRADE_AMOUNT = 50.0
WALK_FORWARD_SPLITS = 5  # عدد شرائح walk-forward
# نستخدم median split: أعلى 50% من توزيع السكور لكل توليفة
# بدلاً من min_score ثابت غير قابل للمقارنة بين توليفات مختلفة الأحجام
PERCENTILE_THRESHOLD = 50  # أعلى 50% → n≈138 لكل توليفة (قابل للمقارنة)


def compute_combo_score(sd: dict, indicators: list) -> float:
    """احسب السكور من مجموع قيم المؤشرات المحددة فقط."""
    total = 0.0
    for ind in indicators:
        val = sd.get(ind, 0)
        if val is None:
            val = 0
        try:
            total += float(val)
        except (TypeError, ValueError):
            pass
    return total


def expectancy_adj(wins: list, losses: list) -> float:
    """
    E_adj = WR * avg_win_adj - (1-WR) * avg_loss_abs
    حيث avg_win_adj = avg_win - FEE, avg_loss_abs = avg_loss + FEE (كنسبة)
    """
    n = len(wins) + len(losses)
    if n == 0:
        return 0.0
    wr = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0
    avg_win_adj = avg_win - FEE * 100
    avg_loss_adj = avg_loss + FEE * 100
    return wr * avg_win_adj - (1 - wr) * avg_loss_adj


def analyze_combo(trades: list, combo_inds: list, percentile: int = 50) -> dict:
    """
    لكل صفقة، أعد حساب السكور من التوليفة.
    نستخدم median split: أعلى (100-percentile)% من السكور = المجموعة المُختارة.
    هذا يُنتج n مماثلة (~50%) بغض النظر عن حجم التوليفة → مقارنة عادلة.
    trades = list of (score_details_dict, profit_percent, result)
    """
    # احسب سكور كل صفقة
    scored = []
    for sd, profit_pct, result in trades:
        new_score = compute_combo_score(sd, combo_inds)
        scored.append((new_score, profit_pct, result))

    if not scored:
        return {"n": 0, "wr": 0, "e_adj": 0, "avg_win": 0, "avg_loss": 0}

    # احسب الـ percentile threshold
    scores_sorted = sorted(s for s, _, _ in scored)
    idx = int(len(scores_sorted) * percentile / 100)
    threshold = scores_sorted[idx] if idx < len(scores_sorted) else scores_sorted[-1]

    # اختر أعلى (100-percentile)%
    qualified_trades = [(p, r) for s, p, r in scored if s >= threshold]

    if not qualified_trades:
        return {"n": 0, "wr": 0, "e_adj": 0, "avg_win": 0, "avg_loss": 0}

    wins = [p for p, r in qualified_trades if r == "WIN"]
    losses = [p for p, r in qualified_trades if r == "LOSS"]
    n = len(qualified_trades)
    wr = len(wins) / n if n > 0 else 0
    e_adj = expectancy_adj(wins, losses)

    return {
        "n": n,
        "wr": round(wr * 100, 1),
        "e_adj": round(e_adj, 3),
        "avg_win": round(sum(wins) / len(wins), 3) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 3) if losses else 0,
        "threshold": round(threshold, 3),
    }


def walk_forward_stability(trades: list, combo_inds: list, percentile: int = 50, n_splits: int = 5) -> dict:
    """
    Walk-Forward: قسّم الصفقات على n_splits شرائح زمنية متتالية
    احسب E_adj في كل شريحة وأعد الانحراف المعياري (stability)
    """
    if len(trades) < n_splits * 4:
        return {"wf_e_mean": None, "wf_e_std": None, "wf_n_slices": 0}

    slice_size = len(trades) // n_splits
    slice_results = []

    for i in range(n_splits):
        start = i * slice_size
        end = start + slice_size if i < n_splits - 1 else len(trades)
        slice_trades = trades[start:end]
        res = analyze_combo(slice_trades, combo_inds, percentile)
        if res["n"] >= 5:
            slice_results.append(res["e_adj"])

    if not slice_results:
        return {"wf_e_mean": None, "wf_e_std": None, "wf_n_slices": 0}

    mean_e = sum(slice_results) / len(slice_results)
    if len(slice_results) > 1:
        variance = sum((x - mean_e) ** 2 for x in slice_results) / (len(slice_results) - 1)
        std_e = variance ** 0.5
    else:
        std_e = 0.0

    return {
        "wf_e_mean": round(mean_e, 3),
        "wf_e_std": round(std_e, 3),
        "wf_n_slices": len(slice_results),
    }


async def run():
    conn = await asyncpg.connect(DB_DSN)

    try:
        # ─── جلب بيانات 1d+bearish/sideways مع نتائج ─────────────────────────
        rows = await conn.fetch("""
            SELECT
                s.score_details,
                tr.profit_percent::float,
                tr.result,
                s.signal_time
            FROM signals s
            JOIN trade_results tr ON tr.signal_id = s.id
            WHERE s.timeframe = '1d'
              AND s.market_condition IN ('bearish', 'sideways')
              AND s.score_details IS NOT NULL
              AND NOT (s.score_details ? 'rsi_divergence')
              AND tr.result IN ('WIN', 'LOSS')
            ORDER BY s.signal_time ASC
        """)

        print(f"إجمالي الإشارات المغلقة: {len(rows)} (1d+bearish/sideways، مخطط قديم)")
        print(f"خط أساس: WIN={sum(1 for r in rows if r['result']=='WIN')}, "
              f"LOSS={sum(1 for r in rows if r['result']=='LOSS')}")
        print()

        # ─── تحويل الصفوف ─────────────────────────────────────────────────────
        trades = []
        for row in rows:
            try:
                sd = json.loads(row['score_details']) if isinstance(row['score_details'], str) else dict(row['score_details'])
                trades.append((sd, float(row['profit_percent']), row['result']))
            except Exception:
                continue

        print(f"بعد التحقق: {len(trades)} إشارة صالحة للتحليل")
        print()

        # ─── تشغيل التوليفات ─────────────────────────────────────────────────
        results = {}
        for name, inds in NAMED_COMBOS.items():
            res = analyze_combo(trades, inds, PERCENTILE_THRESHOLD)
            wf = walk_forward_stability(trades, inds, PERCENTILE_THRESHOLD, WALK_FORWARD_SPLITS)
            results[name] = {**res, **wf, "indicators": inds}

        # ─── طباعة الجدول ────────────────────────────────────────────────────
        print(f"المنهج: Median Split (أعلى 50% من سكور كل توليفة) → n≈{len(trades)//2} لكل توليفة")
        print(f"رسوم: {FEE*100}% لكل صفقة مُخصومة من E_adj")
        print()
        print("=" * 105)
        print(f"{'التوليفة':<28} {'n':>5} {'WR%':>7} {'E_adj%':>8} {'avg_win%':>9} {'avg_loss%':>10} {'threshold':>10} {'WF_E_mean':>10} {'WF_std':>8}")
        print("=" * 105)

        # ترتيب حسب E_adj
        sorted_results = sorted(results.items(), key=lambda x: x[1].get("e_adj", -999), reverse=True)

        for name, r in sorted_results:
            wf_mean = f"{r['wf_e_mean']:.3f}" if r.get("wf_e_mean") is not None else "N/A"
            wf_std = f"{r['wf_e_std']:.3f}" if r.get("wf_e_std") is not None else "N/A"
            thresh = f"{r.get('threshold', 0):.3f}"
            print(
                f"{name:<28} {r['n']:>5} {r['wr']:>7.1f} {r['e_adj']:>8.3f} "
                f"{r['avg_win']:>9.3f} {r['avg_loss']:>10.3f} "
                f"{thresh:>10} "
                f"{wf_mean:>10} {wf_std:>8}"
            )

        print("=" * 105)
        print()

        # ─── ملخص أفضل توليفة ────────────────────────────────────────────────
        best_name, best = sorted_results[0]
        baseline_name = "all_7 (baseline)"
        baseline = results.get(baseline_name, {})

        print(f"أفضل توليفة: {best_name}")
        print(f"  n={best['n']}, WR={best['wr']}%, E_adj={best['e_adj']}%")
        if best.get("wf_e_mean") is not None:
            print(f"  Walk-Forward: E_mean={best['wf_e_mean']}%, std={best['wf_e_std']}%")
        print()
        print(f"الخط الأساسي ({baseline_name}):")
        print(f"  n={baseline.get('n',0)}, WR={baseline.get('wr',0)}%, E_adj={baseline.get('e_adj',0)}%")
        delta = best['e_adj'] - baseline.get('e_adj', 0)
        print(f"  فرق E_adj: {delta:+.3f}% (أفضل توليفة vs الكل)")
        print()

        # ─── تحذير إحصائي ────────────────────────────────────────────────────
        max_n = max(r["n"] for _, r in results.items())
        print(f"تحذير إحصائي: أكبر عينة = {max_n} صفقة")
        if max_n < 100:
            print("  → العينة أصغر من 100 — الفوارق البسيطة غير حاسمة إحصائياً")
        print()
        print("ملاحظة: rsi_divergence وfibonacci غير متاحَين في المخطط القديم (7 إشارات فقط post-rebuild)")
        print("التوليفة المطلوبة '6 مؤشرات' لا يمكن اختبارها بشكل كافٍ على البيانات الحالية (n=5)")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run())
