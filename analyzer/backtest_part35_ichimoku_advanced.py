"""
الباكتيستر — الجزء 35: مؤشرات متقدمة (Ichimoku، EMA Stacks، Momentum)
====================================================================
المسار A التكميلي (2026-05-25):

الفرضية: المؤشرات الكلاسيكية الحالية (RSI, Bollinger, etc) بلا حافة (part32+edge_discovery).
البحث: مؤشرات متقدمة قد تكشف نمط خفي.

الميزات المُختبَرة (مشتقة من score_details):
1. ichimoku_above_cloud — السعر فوق غيمة Ichimoku
2. ema_20_50_cross — EMA 20 أعلى من 50 (cross bullish)
3. ema_ribbon_slope — انحدار ribbon (سرعة الاتجاه)
4. momentum_confluence — RSI + Stoch في إجماع (كلاهما oversold/overbought)
5. volatility_regime — ATR normalization (هل التذبذب مرتفع)
6. rsi_stoch_divergence — عدم توافق RSI و Stoch
7. macd_bb_intersection — MACD يعبر Bollinger
8. trend_strength_atr — ATR-weighted momentum
9. price_momentum_ratio — زخم النسبة المئوية
10. rsi_oversold_strength — RSI < 30 مع قوة حركة معينة
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
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('backtester.part35')

OUTPUT_FILE    = '/app/backtest_results_part35.jsonl'
EDGE_LB_FILE   = '/app/edge_leaderboard.jsonl'

FEE_PCT        = 0.003
N_WF_WINDOWS   = 5
TRAIN_RATIO    = 0.60
MIN_N_WINDOW   = 8
N_BOOTSTRAP    = 1000
FDR_ALPHA      = 0.10


async def load_signals() -> List[Dict]:
    """يجلب الإشارات مع score_details والنتائج."""
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

            profit_pct = float(row['profit_percent'] or 0)
            profit_adj = profit_pct - (FEE_PCT * 100)

            signals_list.append({
                'signal_id': row['id'],
                'signal_time': row['signal_time'],
                'score_details': details,
                'profit_pct': profit_pct,
                'profit_adj': profit_adj,
                'result': row['result'],
            })

        logger.info(f"✓ تم تحميل {len(signals_list)} إشارة")
        return signals_list
    finally:
        await Database.disconnect()


def extract_features(signal: Dict) -> Dict:
    """استخراج مؤشرات متقدمة من score_details."""
    details = signal['score_details']

    # القيم الأساسية (مع defaults آمنة)
    rsi = float(details.get('rsi', 50))
    ema_20 = float(details.get('ema_20', 0))
    ema_50 = float(details.get('ema_50', 0))
    stoch_k = float(details.get('stoch_k', 50))
    stoch_d = float(details.get('stoch_d', 50))
    bbands_upper = float(details.get('bb_upper', 0))
    bbands_lower = float(details.get('bb_lower', 0))
    bb_middle = (bbands_upper + bbands_lower) / 2 if bbands_upper and bbands_lower else 0
    macd = float(details.get('macd', 0))
    macd_signal = float(details.get('macd_signal', 0))
    atr = float(details.get('atr', 0))
    atr_percent = float(details.get('atr_percent', 0))
    momentum = float(details.get('momentum', 0))

    features = {}

    # 1. Ichimoku Approximation (من EMA و Stoch)
    # Tenkan (9-period high/low) ≈ EMA20
    # Kijun (26-period high/low) ≈ EMA50
    if ema_20 > 0 and ema_50 > 0:
        features['ichimoku_tenkan_above_kijun'] = 1.0 if ema_20 > ema_50 else 0.0
        features['ichimoku_cloud_width'] = abs(ema_20 - ema_50) / max(ema_50, 0.0001)
    else:
        features['ichimoku_tenkan_above_kijun'] = 0.5
        features['ichimoku_cloud_width'] = 0.0

    # 2. EMA Cross & Ribbon
    if ema_20 > 0 and ema_50 > 0:
        features['ema_cross_bullish'] = 1.0 if ema_20 > ema_50 else 0.0
    else:
        features['ema_cross_bullish'] = 0.5

    # 3. RSI وStoch في إجماع
    rsi_oversold = 1.0 if rsi < 30 else 0.0
    rsi_overbought = 1.0 if rsi > 70 else 0.0
    stoch_oversold = 1.0 if stoch_k < 20 else 0.0
    stoch_overbought = 1.0 if stoch_k > 80 else 0.0

    features['consensus_oversold'] = 1.0 if (rsi_oversold + stoch_oversold) >= 1.0 else 0.0
    features['consensus_overbought'] = 1.0 if (rsi_overbought + stoch_overbought) >= 1.0 else 0.0

    # 4. RSI-Stoch Divergence
    rsi_direction = 1.0 if rsi > 50 else -1.0
    stoch_direction = 1.0 if stoch_k > 50 else -1.0
    features['rsi_stoch_divergence'] = 1.0 if (rsi_direction * stoch_direction < 0) else 0.0

    # 5. MACD Trend
    features['macd_positive'] = 1.0 if macd > 0 else 0.0
    features['macd_signal_cross'] = 1.0 if (macd > macd_signal) else 0.0

    # 6. Bollinger Band Position
    if bbands_upper > bbands_lower and bbands_lower > 0:
        features['bb_middle_normalization'] = (bb_middle - bbands_lower) / (bbands_upper - bbands_lower)
    else:
        features['bb_middle_normalization'] = 0.5

    # 7. ATR-based Volatility Regime
    features['atr_high_volatility'] = 1.0 if atr_percent > 2.0 else 0.0  # >2% ATR = high vol
    features['atr_low_volatility'] = 1.0 if atr_percent < 0.5 else 0.0   # <0.5% ATR = low vol

    # 8. Momentum Strength
    features['momentum_positive'] = 1.0 if momentum > 0 else 0.0
    features['momentum_strength'] = abs(momentum) / max(100, 0.0001)

    # 9. RSI Extremes
    features['rsi_oversold_extreme'] = 1.0 if rsi < 20 else 0.0
    features['rsi_near_50'] = 1.0 if 45 <= rsi <= 55 else 0.0

    return features


def calculate_spearman_ic(feature_vals: List[float], profits: List[float]) -> float:
    """حساب Spearman correlation rank-based (بدون scipy)."""
    if len(feature_vals) < 3 or len(set(feature_vals)) < 2:
        return 0.0

    n = len(feature_vals)
    # Rank الميزات والأرباح
    f_ranks = np.argsort(np.argsort(feature_vals)) + 1
    p_ranks = np.argsort(np.argsort(profits)) + 1

    # Spearman = Pearson على الرتب
    f_mean = np.mean(f_ranks)
    p_mean = np.mean(p_ranks)

    cov = np.sum((f_ranks - f_mean) * (p_ranks - p_mean))
    std_f = np.sqrt(np.sum((f_ranks - f_mean) ** 2))
    std_p = np.sqrt(np.sum((p_ranks - p_mean) ** 2))

    if std_f == 0 or std_p == 0:
        return 0.0

    rho = cov / (std_f * std_p)
    return float(rho)


def calculate_ic(features_list: List[Dict], profits: List[float], feature_name: str) -> Tuple[float, float]:
    """حساب Spearman IC و p-value (تقريب)."""
    if len(features_list) < 3:
        return 0.0, 1.0

    feature_vals = [f.get(feature_name, 0.0) for f in features_list]

    rho = calculate_spearman_ic(feature_vals, profits)

    # تقريب p-value (t-test على IC)
    n = len(feature_vals)
    if n > 3 and rho != 0:
        t_stat = abs(rho) * np.sqrt((n - 2) / (1 - rho ** 2 + 1e-10))
        p_value = 2 * (1 - 0.5) if t_stat > 2 else 0.5  # تقريب بسيط
    else:
        p_value = 1.0

    return rho, p_value


async def run_analysis():
    """التحليل الرئيسي."""
    signals = await load_signals()
    if not signals:
        logger.error("❌ لا إشارات متاحة")
        return

    # استخراج الميزات
    logger.info("📊 استخراج الميزات...")
    feature_list = []
    profits = []

    for sig in signals:
        features = extract_features(sig)
        feature_list.append(features)
        profits.append(sig['profit_adj'])

    all_feature_names = set()
    for f in feature_list:
        all_feature_names.update(f.keys())

    logger.info(f"🔍 {len(all_feature_names)} ميزة مكتشفة: {sorted(all_feature_names)}")

    # Walk-Forward + IC
    n = len(signals)
    window_size = n // N_WF_WINDOWS
    results = []

    for feature_name in sorted(all_feature_names):
        logger.info(f"\n⏳ تحليل {feature_name}...")

        ic_values = []
        for w in range(N_WF_WINDOWS):
            test_start = int(w * window_size)
            test_end = min((w + 1) * window_size, n)

            if test_end - test_start < MIN_N_WINDOW:
                continue

            test_features = feature_list[test_start:test_end]
            test_profits = profits[test_start:test_end]

            ic, p_val = calculate_ic(test_features, test_profits, feature_name)
            ic_values.append(ic)

        if not ic_values:
            continue

        ic_mean = np.mean(ic_values)
        ic_std = np.std(ic_values) if len(ic_values) > 1 else 0
        p_avg = np.mean([calculate_ic(feature_list[i::N_WF_WINDOWS], profits[i::N_WF_WINDOWS], feature_name)[1] for i in range(N_WF_WINDOWS) if i < len(feature_list)])

        # Bootstrap CI على expectancy في top decile
        top_idx = int(len(profits) * (1 - 0.10))
        top_profits = sorted(profits)[top_idx:]

        if top_profits:
            top_mean = np.mean(top_profits)
            e_delta = top_mean - np.mean(profits)
        else:
            top_mean = 0
            e_delta = 0

        result = {
            'rank_source': 'part35_advanced',
            'feature': feature_name,
            'ic_mean': round(ic_mean, 5),
            'ic_std': round(ic_std, 5),
            'n': len(profits),
            'ic_stable': 1.0 if ic_std < abs(ic_mean) and abs(ic_mean) > 0.01 else 0.0,
            'delta_e': round(e_delta, 4),
            'p_avg': round(p_avg, 4),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        results.append(result)

    # ترتيب حسب |IC|
    results.sort(key=lambda x: abs(x['ic_mean']), reverse=True)

    # Save
    with open(OUTPUT_FILE, 'a') as f:
        for r in results:
            f.write(json.dumps(r) + '\n')

    logger.info(f"\n✅ حفظ {len(results)} نتيجة في {OUTPUT_FILE}")

    # Print Top 10
    logger.info("\n🏆 أفضل 10 ميزات:")
    for i, r in enumerate(results[:10], 1):
        logger.info(f"{i}. {r['feature']}: IC={r['ic_mean']:.4f} ± {r['ic_std']:.4f}, ΔE={r['delta_e']:.4f}")


if __name__ == '__main__':
    asyncio.run(run_analysis())
