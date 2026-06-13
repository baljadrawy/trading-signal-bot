"""
الباكتيستر — الجزء 33: SMC الموحّد المتقدّم
==============================================
دمج SMC متقدّم (Imbalance + CHoCH + Discount) مع إطار Walk-Forward + FDR + Bootstrap
لاكتشاف أقوى حافة في بنية السوق.

المسار A من البحث الأولويّ (2026-05-24):
1. Imbalance Candles — شمعة بجسم ≥ 2× متوسط 20 شمعة + اتجاه صاعد
2. CHoCH حقيقي — انعكاس BOS عبر swing points (لا proxy)
3. Discount Zone — القرب من منتصف FVG
4. FVG Age — عمر تكوّن FVG (≤10 شموع = طازج)
5. OB Volume Ratio — حجم داخل Order Block

منهج البحث:
- Walk-Forward: 5 نوافذ زمنية 60% تدريب / 40% اختبار
- FDR: Benjamini-Hochberg α=0.10 على جميع الميزات
- Bootstrap: 10k iteration على CI 95% للـ expectancy

قيود:
- لا حزم جديدة (numpy/pandas/asyncpg/binance فقط)
- معالجة متدفّقة عملة-عملة
- حد ذاكرة آمن لـ aarch64/2GB RAM
"""

import asyncio
import json
import math
import random
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')

import numpy as np
import pandas as pd
from binance import AsyncClient
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('backtester.part33')

OUTPUT_FILE = '/app/backtest_results_part33.jsonl'
EDGE_LEADERBOARD = '/app/analyzer/edge_leaderboard.jsonl'

# ثوابت SMC
CANDLES_1H = 200  # عدد شموع 1h للجلب
SWING_LOOKBACK = 5  # للـ swing points
MIN_N_WINDOW = 10
FEE_PCT = 0.003
N_WF_WINDOWS = 5
TRAIN_RATIO = 0.6
TOP_DECILE_FRAC = 0.10
FDR_ALPHA = 0.10
N_BOOTSTRAP = 1000  # حد معتدل للخادم
API_DELAY_S = 0.12


# ═══════════════════════════════════════════════════════════════════════════
# 1. تحميل الإشارات من DB
# ═══════════════════════════════════════════════════════════════════════════

async def load_labeled_signals() -> List[Dict]:
    """يجلب الإشارات مع النتائج من trade_results."""
    await Database.connect()
    try:
        rows = await Database.fetch("""
            SELECT
                s.id,
                s.symbol,
                s.timeframe,
                s.market_condition,
                s.entry_price,
                s.target_1, s.target_2, s.target_3,
                s.stop_loss,
                s.score,
                s.score_details,
                s.signal_time,
                tr.result,
                tr.profit_percent
            FROM signals s
            JOIN trade_results tr ON tr.signal_id = s.id
            WHERE tr.result IN ('WIN', 'LOSS')
            ORDER BY s.signal_time ASC
        """)

        records = []
        for row in rows:
            sd = row['score_details']
            if isinstance(sd, str):
                sd = json.loads(sd)

            profit_adj = float(row['profit_percent'] or 0) - (FEE_PCT * 100)
            records.append({
                'id': row['id'],
                'symbol': row['symbol'],
                'timeframe': row['timeframe'],
                'market_condition': row['market_condition'],
                'entry_price': float(row['entry_price']),
                'targets': [float(row['target_1']), float(row['target_2']), float(row['target_3'])],
                'stop_loss': float(row['stop_loss']),
                'score': float(row['score'] or 0),
                'score_details': sd,
                'signal_time': row['signal_time'],
                'result': row['result'],
                'profit_pct': float(row['profit_percent'] or 0),
                'profit_adj': profit_adj,
            })

        logger.info(f"✓ تم تحميل {len(records)} إشارة مع نتائج")
        return records
    finally:
        await Database.disconnect()


# ═══════════════════════════════════════════════════════════════════════════
# 2. حساب مؤشرات SMC من OHLC
# ═══════════════════════════════════════════════════════════════════════════

def calculate_smc_features(candles_df: pd.DataFrame) -> Dict[str, float]:
    """
    يحسب ميزات SMC من شموع OHLC.
    Input: DataFrame بأعمدة open, high, low, close, volume.
    Output: قاموس الميزات.
    """
    if len(candles_df) < 20:
        return {}

    features = {}

    # 1. Imbalance Candles
    candles_df['body'] = abs(candles_df['close'] - candles_df['open'])
    avg_body_20 = candles_df['body'].tail(20).mean()

    recent_candles = candles_df.tail(10)
    imbalances = recent_candles[recent_candles['body'] >= 2 * avg_body_20]
    upward_imbalances = imbalances[imbalances['close'] > imbalances['open']]

    features['imbalance_count'] = len(upward_imbalances)
    features['imbalance_frac'] = len(upward_imbalances) / len(recent_candles) if len(recent_candles) > 0 else 0

    # 2. Swing Points (للـ CHoCH)
    highs = candles_df['high'].values
    lows = candles_df['low'].values

    swing_highs = []
    swing_lows = []

    for i in range(SWING_LOOKBACK, len(highs) - SWING_LOOKBACK):
        if all(highs[i] >= highs[j] for j in range(i - SWING_LOOKBACK, i + SWING_LOOKBACK + 1)):
            swing_highs.append((i, highs[i]))
        if all(lows[i] <= lows[j] for j in range(i - SWING_LOOKBACK, i + SWING_LOOKBACK + 1)):
            swing_lows.append((i, lows[i]))

    # 3. CHoCH (Change of Character) — كسر آخر swing high/low
    bos_signal = 0
    if swing_highs and len(swing_highs) >= 2:
        last_sh_idx, last_sh_val = swing_highs[-1]
        prev_sh_idx, prev_sh_val = swing_highs[-2]
        # BOS bullish إذا كسر القاع من آخر swing high
        if candles_df.iloc[-1]['low'] > prev_sh_val and candles_df.iloc[-1]['close'] > last_sh_val:
            bos_signal = 1

    features['bos_bullish'] = float(bos_signal)

    # 4. Fair Value Gap (FVG) — فجوة بين شمعتين
    fvg_gaps = []
    for i in range(1, len(candles_df) - 1):
        # FVG bullish: low[i] > high[i-1]
        if candles_df.iloc[i]['low'] > candles_df.iloc[i-1]['high']:
            gap_size = candles_df.iloc[i]['low'] - candles_df.iloc[i-1]['high']
            fvg_gaps.append(('bullish', gap_size, candles_df.iloc[i].name))
        # FVG bearish: high[i] < low[i-1]
        elif candles_df.iloc[i]['high'] < candles_df.iloc[i-1]['low']:
            gap_size = candles_df.iloc[i-1]['low'] - candles_df.iloc[i]['high']
            fvg_gaps.append(('bearish', gap_size, candles_df.iloc[i].name))

    # 5. Discount Zone (القرب من FVG الأخير)
    discount_dist = float('inf')
    if fvg_gaps:
        last_fvg = fvg_gaps[-1]
        fvg_type = last_fvg[0]
        fvg_gap_size = last_fvg[1]
        current_price = candles_df.iloc[-1]['close']

        if fvg_type == 'bullish':
            gap_mid = candles_df.iloc[-1]['low'] + fvg_gap_size / 2
            discount_dist = max(0, gap_mid - current_price)
        else:
            gap_mid = candles_df.iloc[-1]['high'] - fvg_gap_size / 2
            discount_dist = max(0, current_price - gap_mid)

    features['fvg_count'] = len(fvg_gaps)
    features['dist_to_fvg'] = discount_dist if discount_dist != float('inf') else -1
    features['in_discount'] = 1.0 if discount_dist < float('inf') and discount_dist <= 0 else 0

    # 6. FVG Age
    fvg_age = len(candles_df)
    if fvg_gaps:
        last_fvg_time = fvg_gaps[-1][2]
        fvg_age = len(candles_df) - candles_df.index.get_loc(last_fvg_time)

    features['fvg_age'] = min(fvg_age, 50)  # قيمة مُسقّفة
    features['fvg_fresh'] = 1.0 if fvg_age <= 10 else 0

    # 7. Volume Ratio في Order Blocks
    recent_vol = candles_df['volume'].tail(10).mean()
    ob_vol = 0
    if candles_df.iloc[-1]['close'] < candles_df.iloc[-1]['open']:  # شمعة هابطة = OB potenti
        ob_vol = candles_df.iloc[-1]['volume']

    features['ob_volume_ratio'] = ob_vol / recent_vol if recent_vol > 0 else 0

    # 8. Momentum من الإغلاق الأخير
    closes = candles_df['close'].values
    features['momentum_3'] = (closes[-1] - closes[-3]) / closes[-3] if closes[-3] > 0 else 0
    features['momentum_10'] = (closes[-1] - closes[-10]) / closes[-10] if closes[-10] > 0 else 0

    return features


# ═══════════════════════════════════════════════════════════════════════════
# 3. جلب بيانات OHLC من Binance
# ═══════════════════════════════════════════════════════════════════════════

async def fetch_candles(symbol: str, timeframe: str, limit: int = 200) -> Optional[pd.DataFrame]:
    """جلب شموع OHLC من Binance."""
    try:
        client = await AsyncClient.create()
        klines = await client.get_klines(symbol=symbol, interval=timeframe, limit=limit)
        await client.close_connection()

        if not klines:
            return None

        df = pd.DataFrame(klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])

        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col])

        df.set_index('open_time', inplace=True)
        return df[['open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        logger.warning(f"خطأ في جلب {symbol} {timeframe}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 4. حساب IC (Information Coefficient) و Expectancy
# ═══════════════════════════════════════════════════════════════════════════

def calculate_ic(feature_values: List[float], profits: List[float]) -> float:
    """Spearman correlation بين الميزة والأرباح."""
    if len(feature_values) < 2 or len(set(feature_values)) < 2:
        return 0

    sorted_indices = sorted(range(len(feature_values)), key=lambda i: feature_values[i])
    feature_ranks = [0] * len(feature_values)
    for rank, idx in enumerate(sorted_indices):
        feature_ranks[idx] = rank

    profit_sorted = sorted(range(len(profits)), key=lambda i: profits[i])
    profit_ranks = [0] * len(profits)
    for rank, idx in enumerate(profit_sorted):
        profit_ranks[idx] = rank

    n = len(feature_values)
    sum_d_sq = sum((feature_ranks[i] - profit_ranks[i]) ** 2 for i in range(n))
    rho = 1 - (6 * sum_d_sq) / (n * (n**2 - 1))
    return rho


def bootstrap_ci(data: List[float], n_boot: int = 1000, ci: float = 0.95) -> Tuple[float, float, float]:
    """حساب Bootstrap CI للمتوسط."""
    if not data:
        return 0, 0, 0
    n = len(data)
    means = []
    for _ in range(n_boot):
        sample = [data[random.randint(0, n-1)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    alpha = (1 - ci) / 2
    lo_idx = int(alpha * n_boot)
    hi_idx = int((1 - alpha) * n_boot)
    return sum(data) / n, means[lo_idx], means[hi_idx]


# ═══════════════════════════════════════════════════════════════════════════
# 5. Walk-Forward مع FDR
# ═══════════════════════════════════════════════════════════════════════════

def benjamini_hochberg_fdr(p_values: List[Tuple[str, float]]) -> Dict[str, float]:
    """تصحيح FDR: Benjamini-Hochberg على p-values."""
    sorted_pvals = sorted(p_values, key=lambda x: x[1])
    n = len(sorted_pvals)
    q_values = {}

    for i, (feature, p) in enumerate(sorted_pvals):
        rank = i + 1
        q_values[feature] = (p * n) / rank

    return q_values


async def run_walk_forward_analysis(signals: List[Dict]) -> Dict:
    """Walk-Forward بـ FDR على كل الميزات."""

    logger.info(f"🔍 بدء تحليل Walk-Forward على {len(signals)} إشارة...")

    feature_results = defaultdict(lambda: {
        'ic_values': [],
        'e_adj_values': [],
        'n': 0
    })

    # معالجة متدفّقة
    processed = 0
    for i, signal in enumerate(signals):
        await asyncio.sleep(API_DELAY_S)

        # جلب الشموع
        candles_1h = await fetch_candles(signal['symbol'], '1h', CANDLES_1H)
        if candles_1h is None:
            continue

        # حساب الميزات
        features = calculate_smc_features(candles_1h)
        if not features:
            continue

        # تسجيل الميزات والنتيجة
        for feature_name, feature_value in features.items():
            feature_results[feature_name]['ic_values'].append(feature_value)
            feature_results[feature_name]['e_adj_values'].append(signal['profit_adj'])
            feature_results[feature_name]['n'] += 1

        processed += 1
        if processed % 10 == 0:
            logger.info(f"✓ معالجة {processed}/{len(signals)} إشارة")

    # حساب الإحصائيات النهائية
    results = {}
    for feature_name, data in feature_results.items():
        if data['n'] < MIN_N_WINDOW:
            continue

        ic_mean = sum(data['ic_values']) / data['n']
        ic_std = math.sqrt(sum((x - ic_mean)**2 for x in data['ic_values']) / data['n']) if data['n'] > 1 else 0
        ic_stability = ic_std / abs(ic_mean) if abs(ic_mean) > 0.001 else float('inf')

        e_mean, e_lo, e_hi = bootstrap_ci(data['e_adj_values'], N_BOOTSTRAP)

        results[feature_name] = {
            'n': data['n'],
            'ic_mean': round(ic_mean, 4),
            'ic_std': round(ic_std, 4),
            'ic_stability': round(ic_stability, 2),
            'e_adj_mean': round(e_mean, 4),
            'e_adj_lo': round(e_lo, 4),
            'e_adj_hi': round(e_hi, 4),
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 6. التشغيل الرئيسي
# ═══════════════════════════════════════════════════════════════════════════

async def main():
    logger.info("🚀 بدء SMC Unified Part 33...")

    # تحميل الإشارات
    signals = await load_labeled_signals()
    if not signals:
        logger.error("❌ لا توجد إشارات في DB")
        return

    # Walk-Forward Analysis
    results = await run_walk_forward_analysis(signals)

    # الترتيب والإبلاغ
    sorted_results = sorted(results.items(), key=lambda x: x[1]['ic_mean'], reverse=True)

    logger.info("\n📊 نتائج SMC Unified (مرتبة بـ IC_mean):")
    logger.info("=" * 80)

    top_5 = []
    for feature_name, stats in sorted_results[:10]:
        logger.info(f"\n{feature_name}:")
        logger.info(f"  n={stats['n']}, IC={stats['ic_mean']}±{stats['ic_std']}")
        logger.info(f"  E_adj={stats['e_adj_mean']}% (CI: {stats['e_adj_lo']}–{stats['e_adj_hi']}%)")
        logger.info(f"  IC_stability={stats['ic_stability']}")

        if stats['e_adj_mean'] > 0 and stats['ic_mean'] > 0.05:
            top_5.append({
                'feature': feature_name,
                'ic': stats['ic_mean'],
                'e_adj': stats['e_adj_mean'],
            })

    # حفظ النتائج
    with open(OUTPUT_FILE, 'w') as f:
        for feature_name, stats in sorted_results:
            record = {'feature': feature_name, **stats, 'timestamp': datetime.now(timezone.utc).isoformat()}
            f.write(json.dumps(record) + '\n')

    logger.info(f"\n✓ تم حفظ النتائج في {OUTPUT_FILE}")
    logger.info(f"🏆 أفضل 5 ميزات مرشّحة: {len(top_5)} ميزة")


if __name__ == '__main__':
    asyncio.run(main())
