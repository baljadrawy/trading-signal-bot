"""
الباكتيستر — الجزء 37: SMC المتقدّم من OHLC الحقيقي
====================================================
المسار A — الأولوية القصوى (2026-05-27)

الفرق عن v2 (part33): يحسب الميزات من شموع OHLC حقيقية (Binance API)
بدلاً من score_details كـ proxies — هذا هو المميّز.

الميزات الجديدة (5 ميزات SMC متقدّمة):
  1. imbalance_body_ratio  — نسبة شمعة بجسم ≥ 2× متوسط 20 شمعة (Imbalance Candle)
  2. choch_real            — CHoCH حقيقي: BOS صعودي بعد BOS هابط عبر swing points
  3. discount_dist         — المسافة من entry لمنتصف أقرب FVG (Discount Zone)
  4. fvg_age               — عمر آخر FVG بالشموع (طازج ≤10 = أقوى)
  5. ob_vol_ratio          — نسبة الحجم داخل Order Block لمتوسط 20 شمعة

الميزات المعاد تقييمها من part13 (بإصلاح الحساب):
  6. bos_bullish           — BOS صعودي حقيقي من swing points
  7. fvg_count             — عدد FVG في آخر 30 شمعة
  8. liq_sweep_bull        — Liquidity Sweep صعودي موثَّق
  9. ob_bullish            — Order Block صعودي موجود

منهج البحث:
  - Phase A: ETHUSDT 1d (n≈3) — pipeline smoke-test فقط
  - Phase B: جميع 1d (n=380) — تحليل الحافة الكامل
  - Walk-Forward: 5 نوافذ زمنية، 60% train / 40% OOS
  - IC = Spearman(feature_vals_in_OOS_window, profit_adj_in_OOS_window) — صحيح
  - FDR: Benjamini-Hochberg α=0.10
  - Bootstrap CI: 1000 iteration على E_adj في top_quartile
  - E_adj: محسوبة per-feature من decile المُرتَّب (لا قيمة ثابتة كـ v2)

قيود:
  - لا حزم جديدة (numpy/pandas/asyncpg/binance فقط)
  - معالجة متدفّقة — عملة-عملة (لا تجميع في الذاكرة)
  - لا حذف من DB، لا تعديل حيّ
  - Pickle cache لتجنب إعادة طلب Binance مرات متعددة
  - حد ذاكرة آمن لـ aarch64/3.7GB RAM مشترك

تحذيرات إحصائية موثَّقة:
  - n=380 مع 9 ميزات وفصل زمني (WF) → BH صارمة
  - أي ناجٍ يحتاج post-freeze OOS (n≥30) قبل أي توصية حيّة
  - n_post_freeze=12 حالياً — غير كافٍ لقرار حيّ

المخرج: backtest_results_part37.jsonl + ملخص طباعي
"""

import asyncio
import json
import math
import pickle
import random
import sys
import os
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

logger = setup_logger('backtester.part37')

OUTPUT_FILE   = '/app/backtest_results_part37.jsonl'
CACHE_FILE    = '/app/part37_ohlc_cache.pkl'

# ثوابت
CANDLES_1D     = 100     # 100 يوم سياق للـ 1d swing structure
SWING_LBK      = 5       # lookback لـ swing points
FEE_PCT        = 0.003   # 0.3% per trade
N_WF_WINDOWS   = 5       # نوافذ Walk-Forward
TRAIN_RATIO    = 0.60    # 60% train / 40% OOS
MIN_N_WINDOW   = 8       # حد أدنى للحساب الموثوق في كل نافذة
N_BOOTSTRAP    = 1000    # Bootstrap iterations (مناسب للخادم)
FDR_ALPHA      = 0.10    # Benjamini-Hochberg threshold
TOP_DECILE     = 0.25    # أعلى 25% (quartile) لـ E_adj (بدلاً من 10% لأن n صغير)
API_DELAY_S    = 0.15    # تأخير بين طلبات API


# ═══════════════════════════════════════════════════════════════════════════
# 1. تحميل الإشارات من DB
# ═══════════════════════════════════════════════════════════════════════════

async def load_1d_signals() -> List[Dict]:
    """يجلب إشارات 1d مع نتائجها من DB، مُرتَّبة زمنياً."""
    await Database.connect()
    try:
        rows = await Database.fetch("""
            SELECT
                s.id,
                s.symbol,
                s.timeframe,
                s.market_condition,
                s.entry_price,
                s.stop_loss,
                s.target_1,
                s.score,
                s.score_details,
                s.signal_time,
                tr.result,
                tr.profit_percent
            FROM signals s
            JOIN trade_results tr ON tr.signal_id = s.id
            WHERE s.timeframe = '1d'
              AND tr.result IN ('WIN', 'LOSS')
            ORDER BY s.signal_time ASC
        """)

        records = []
        for row in rows:
            sd = row['score_details']
            if isinstance(sd, str):
                sd = json.loads(sd)
            elif sd is None:
                sd = {}

            entry = float(row['entry_price'])
            stop  = float(row['stop_loss'])
            t1    = float(row['target_1'])
            pct   = float(row['profit_percent'] or 0.0)
            pct_adj = pct - (FEE_PCT * 100)

            records.append({
                'id':               row['id'],
                'symbol':           row['symbol'],
                'market_condition': row['market_condition'],
                'entry_price':      entry,
                'stop_loss':        stop,
                'target_1':         t1,
                'score':            float(row['score'] or 0),
                'score_details':    sd,
                'signal_time':      row['signal_time'],
                'result':           row['result'],
                'profit_pct':       pct,
                'profit_adj':       pct_adj,
                'label':            1 if row['result'] == 'WIN' else 0,
                # SMC features (يُحسب لاحقاً)
                'smc': {},
            })
        return records
    finally:
        await Database.disconnect()


# ═══════════════════════════════════════════════════════════════════════════
# 2. جلب OHLC مع Cache
# ═══════════════════════════════════════════════════════════════════════════

def load_cache() -> Dict:
    """يحمّل cache الشموع من ملف pickle إذا وُجد."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: Dict) -> None:
    """يحفظ cache الشموع في ملف pickle."""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
    except Exception as e:
        logger.warning(f"لم يُحفَظ الـ cache: {e}")


async def fetch_candles(
    client: AsyncClient,
    symbol: str,
    sig_time: datetime,
    cache: Dict,
) -> Optional[pd.DataFrame]:
    """
    يجلب CANDLES_1D شمعة 1d تنتهي عند وقت الإشارة.
    يستخدم cache لتجنب طلبات مكررة.
    """
    # مفتاح Cache: (symbol, تاريخ الإشارة)
    cache_key = (symbol, sig_time.strftime('%Y-%m-%d'))

    if cache_key in cache:
        return cache[cache_key]

    try:
        if sig_time.tzinfo is None:
            sig_time = sig_time.replace(tzinfo=timezone.utc)
        end_ms = int(sig_time.timestamp() * 1000)

        klines = await client.get_klines(
            symbol=symbol,
            interval='1d',
            limit=CANDLES_1D,
            endTime=end_ms,
        )

        if not klines or len(klines) < SWING_LBK + 3:
            cache[cache_key] = None
            return None

        df = pd.DataFrame(klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
        df = df.set_index('open_time').dropna(subset=['close'])

        cache[cache_key] = df
        return df

    except Exception as e:
        logger.warning(f"فشل جلب {symbol}: {e}")
        cache[cache_key] = None
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 3. حسابات SMC الدقيقة (من part13 مع تحسينات)
# ═══════════════════════════════════════════════════════════════════════════

def find_swing_points(df: pd.DataFrame) -> Tuple[List[float], List[float]]:
    """
    يجد swing highs وswing lows الحقيقية.
    شرط: high[i] > max(5 يسار + 5 يمين) للـ swing high.
    """
    highs = df['high'].values
    lows  = df['low'].values
    n     = len(highs)

    swing_highs: List[float] = []
    swing_lows:  List[float] = []

    for i in range(SWING_LBK, n - SWING_LBK):
        lh = highs[i - SWING_LBK:i]
        rh = highs[i + 1:i + SWING_LBK + 1]
        if highs[i] > max(lh) and highs[i] >= max(rh):
            swing_highs.append(float(highs[i]))

        ll = lows[i - SWING_LBK:i]
        rl = lows[i + 1:i + SWING_LBK + 1]
        if lows[i] < min(ll) and lows[i] <= min(rl):
            swing_lows.append(float(lows[i]))

    return swing_highs, swing_lows


def compute_imbalance(df: pd.DataFrame) -> Dict[str, float]:
    """
    Imbalance Candle: شمعة بجسم ≥ 2× متوسط جسم 20 شمعة.
    يقيس وجود حركة انفجارية واتجاهها.

    المخرجات:
    - imbalance_body_ratio: أكبر نسبة جسم/متوسط في آخر 10 شموع
    - imbalance_count: عدد شموع الـ imbalance في آخر 10 شموع
    - imbalance_bullish: هل آخر imbalance صعودي (close > open)
    """
    opens  = df['open'].values
    closes = df['close'].values
    n      = len(closes)

    result = {
        'imbalance_body_ratio': 0.0,
        'imbalance_count':      0.0,
        'imbalance_bullish':    0.0,
    }

    if n < 22:
        return result

    # جسم كل شمعة
    bodies = np.abs(closes - opens)

    # متوسط الجسم المتحرك (20 شمعة)
    window_size = 20
    max_ratio   = 0.0
    count_imb   = 0
    last_bull   = 0.0

    for i in range(window_size, n):
        avg_body = np.mean(bodies[i - window_size:i])
        if avg_body <= 1e-10:
            continue
        ratio = bodies[i] / avg_body
        if ratio >= 2.0:
            count_imb += 1
            if ratio > max_ratio:
                max_ratio = ratio
            if closes[i] > opens[i]:
                last_bull = 1.0

    result['imbalance_body_ratio'] = round(max_ratio, 4)
    result['imbalance_count']      = float(min(count_imb, 10))
    result['imbalance_bullish']    = last_bull

    return result


def compute_choch_real(df: pd.DataFrame) -> Dict[str, float]:
    """
    CHoCH (Change of Character) الحقيقي من swing points.

    المنهج:
    1. تحديد آخر BOS: هل آخر كسر هيكلي كان صعودياً أم هابطاً؟
       - BOS صعودي: close[i] > آخر swing_high موثَّق
       - BOS هابط: close[i] < آخر swing_low موثَّق
    2. CHoCH = عكس اتجاه BOS:
       - كان هابط → الآن صعودي = CHoCH صعودي (إشارة شراء)
       - كان صعودي → الآن هابط = CHoCH هابط (إشارة بيع)

    المخرجات:
    - choch_bullish: هل حدث CHoCH صعودي في آخر 20 شمعة
    - choch_count:   عدد CHoCH في آخر 30 شمعة
    - last_bos_dir:  اتجاه آخر BOS (1=صعودي، -1=هابط، 0=غير محدد)
    """
    swing_highs, swing_lows = find_swing_points(df)
    closes = df['close'].values
    n      = len(closes)

    result = {
        'choch_bullish': 0.0,
        'choch_count':   0.0,
        'last_bos_dir':  0.0,
    }

    if not swing_highs or not swing_lows or n < SWING_LBK + 5:
        return result

    # سجّل اتجاهات BOS كرونولوجياً
    bos_directions: List[int] = []  # 1=bullish, -1=bearish
    choch_events   = []

    for i in range(SWING_LBK, n):
        c = float(closes[i])

        # نستخدم swing points التي تكوّنت قبل هذه الشمعة
        # (تقريب: نستخدم الكل لأننا نحسب في الختام وليس في streaming)
        if swing_highs and c > swing_highs[-1]:
            bos_directions.append(1)
        elif swing_lows and c < swing_lows[-1]:
            bos_directions.append(-1)

    if not bos_directions:
        return result

    result['last_bos_dir'] = float(bos_directions[-1])

    # CHoCH: تغيير الاتجاه
    choch_count = 0
    for i in range(1, len(bos_directions)):
        if bos_directions[i] != bos_directions[i - 1]:
            choch_count += 1
            if bos_directions[i] == 1:
                result['choch_bullish'] = 1.0

    result['choch_count'] = float(min(choch_count, 5))

    return result


def compute_fvg_advanced(df: pd.DataFrame, entry_price: float) -> Dict[str, float]:
    """
    FVG متقدّم: يحسب discount distance وfvg_age.

    FVG Bullish: low[i+2] > high[i]
    Discount Zone: entry قريب من منتصف FVG (distance ≤ 50% من حجم FVG)
    FVG Age: عدد الشموع منذ تكوّن آخر FVG

    المخرجات:
    - fvg_count:       عدد FVG في آخر 30 شمعة
    - discount_dist:   distance = |entry - fvg_midpoint| / fvg_size (0=مثالي)
    - in_discount:     هل entry داخل منطقة discount (dist ≤ 0.5)
    - fvg_age:         عمر آخر FVG بالشموع (صغير = أحدث = أقوى)
    - fvg_fresh:       هل FVG طازج (≤10 شموع)
    """
    highs = df['high'].values
    lows  = df['low'].values
    n     = len(highs)

    result = {
        'fvg_count':    0.0,
        'discount_dist': 1.0,   # 1 = لا FVG قريب
        'in_discount':  0.0,
        'fvg_age':      float(min(n, 50)),  # worst case = قديم جداً
        'fvg_fresh':    0.0,
    }

    if n < 5:
        return result

    window   = min(30, n - 2)
    start    = max(0, n - window - 2)
    bull_fvgs = []  # (gap_lo, gap_hi, age_in_candles)

    for i in range(start, n - 2):
        if lows[i + 2] > highs[i]:
            gap_lo   = float(highs[i])
            gap_hi   = float(lows[i + 2])
            age      = n - 1 - (i + 2)  # عدد الشموع منذ التكوّن
            bull_fvgs.append((gap_lo, gap_hi, age))

    result['fvg_count'] = float(min(len(bull_fvgs), 10))

    if bull_fvgs:
        # أحدث FVG (أصغر age)
        freshest = min(bull_fvgs, key=lambda x: x[2])
        gap_lo, gap_hi, age = freshest

        fvg_size   = gap_hi - gap_lo
        fvg_mid    = (gap_lo + gap_hi) / 2

        result['fvg_age']   = float(age)
        result['fvg_fresh'] = 1.0 if age <= 10 else 0.0

        if fvg_size > 0 and entry_price > 0:
            dist = abs(entry_price - fvg_mid) / fvg_size
            result['discount_dist'] = round(min(dist, 2.0), 4)
            result['in_discount']   = 1.0 if dist <= 0.5 else 0.0

    return result


def compute_ob_volume(df: pd.DataFrame, entry_price: float) -> Dict[str, float]:
    """
    Order Block Volume Ratio: نسبة حجم OB لمتوسط 20 شمعة.

    OB Bullish: آخر شمعة هابطة قبل حركة قوية ≥1%.
    ob_vol_ratio: volume_OB / avg_volume_20 (كبير = OB مهم = أقوى)

    المخرجات:
    - ob_bullish:    هل يوجد OB صعودي
    - ob_vol_ratio:  نسبة الحجم (1=متوسط، >1=أعلى=أقوى)
    - ob_near_entry: هل OB قريب من entry (ضمن 5%)
    """
    opens   = df['open'].values
    closes  = df['close'].values
    highs   = df['high'].values
    lows    = df['low'].values
    volumes = df['volume'].values
    n       = len(closes)

    result = {
        'ob_bullish':    0.0,
        'ob_vol_ratio':  1.0,   # default = متوسط
        'ob_near_entry': 0.0,
    }

    if n < 25:
        return result

    avg_vol20 = np.mean(volumes[max(0, n - 20):n])
    if avg_vol20 <= 0:
        return result

    window = min(30, n - 4)
    start  = max(0, n - window - 4)
    best_ob = None  # (ob_lo, ob_hi, vol_ratio)

    for i in range(start, n - 3):
        # شمعة هابطة
        if closes[i] >= opens[i]:
            continue

        # حركة قوية بعدها
        future_close = closes[min(i + 3, n - 1)]
        move_pct     = (future_close - closes[i]) / closes[i] if closes[i] > 0 else 0

        if move_pct < 0.01:
            continue

        ob_lo     = float(lows[i])
        ob_hi     = float(highs[i])
        vol_ratio = float(volumes[i]) / avg_vol20

        if best_ob is None or vol_ratio > best_ob[2]:
            best_ob = (ob_lo, ob_hi, vol_ratio)

    if best_ob is not None:
        ob_lo, ob_hi, vol_ratio = best_ob
        result['ob_bullish']   = 1.0
        result['ob_vol_ratio'] = round(vol_ratio, 3)

        # هل OB قريب من entry (ضمن 5%)
        if entry_price > 0:
            ob_mid = (ob_lo + ob_hi) / 2
            dist_pct = abs(entry_price - ob_mid) / entry_price
            if dist_pct <= 0.05:
                result['ob_near_entry'] = 1.0

    return result


def compute_bos_real(df: pd.DataFrame) -> Dict[str, float]:
    """BOS حقيقي من swing points (من part13، مُبسَّط)."""
    swing_highs, swing_lows = find_swing_points(df)
    closes = df['close'].values
    n      = len(closes)

    result = {
        'bos_bullish': 0.0,
        'bos_bearish': 0.0,
    }

    if not swing_highs or not swing_lows or n < 2:
        return result

    last_close = float(closes[-2]) if n >= 2 else float(closes[-1])

    if last_close > swing_highs[-1]:
        result['bos_bullish'] = 1.0
    if last_close < swing_lows[-1]:
        result['bos_bearish'] = 1.0

    return result


def compute_liq_sweep(df: pd.DataFrame) -> Dict[str, float]:
    """Liquidity Sweep الحقيقي (من part13)."""
    swing_highs, swing_lows = find_swing_points(df)
    lows   = df['low'].values
    highs  = df['high'].values
    closes = df['close'].values
    n      = len(closes)

    result = {
        'liq_sweep_bull': 0.0,
        'liq_sweep_bear': 0.0,
    }

    if not swing_lows or not swing_highs or n < SWING_LBK + 2:
        return result

    if swing_lows:
        last_sl = swing_lows[-1]
        for i in range(SWING_LBK, n - 1):
            if lows[i] < last_sl and closes[i] > last_sl:
                result['liq_sweep_bull'] = 1.0
                break

    if swing_highs:
        last_sh = swing_highs[-1]
        for i in range(SWING_LBK, n - 1):
            if highs[i] > last_sh and closes[i] < last_sh:
                result['liq_sweep_bear'] = 1.0
                break

    return result


def compute_all_smc_features(df: pd.DataFrame, entry_price: float) -> Dict[str, float]:
    """يجمع جميع مؤشرات SMC المتقدّمة من DataFrame OHLC."""
    features = {}
    features.update(compute_imbalance(df))
    features.update(compute_choch_real(df))
    features.update(compute_fvg_advanced(df, entry_price))
    features.update(compute_ob_volume(df, entry_price))
    features.update(compute_bos_real(df))
    features.update(compute_liq_sweep(df))
    return features


# ═══════════════════════════════════════════════════════════════════════════
# 4. إحصاءات (من part15 — محقَّقة)
# ═══════════════════════════════════════════════════════════════════════════

def spearman_rho(x: List[float], y: List[float]) -> float:
    """Spearman rank correlation — صحيح."""
    n = len(x)
    if n < 3:
        return 0.0

    def rank_list(lst):
        sorted_idx = sorted(range(n), key=lambda i: lst[i])
        ranks = [0.0] * n
        for rank, idx in enumerate(sorted_idx):
            ranks[idx] = float(rank + 1)
        return ranks

    rx = rank_list(x)
    ry = rank_list(y)
    mr = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mr) * (ry[i] - my) for i in range(n))
    dx  = math.sqrt(sum((rx[i] - mr) ** 2 for i in range(n)))
    dy  = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _normal_cdf(z: float) -> float:
    """تقريب CDF للتوزيع الطبيعي."""
    sign = 1 if z >= 0 else -1
    z = abs(z)
    t = 1.0 / (1.0 + 0.2316419 * z)
    poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937
             + t * (-1.821255978 + t * 1.330274429))))
    phi = 1.0 - (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * z * z) * poly
    return 0.5 + sign * (phi - 0.5)


def ttest_one_sample(values: List[float]) -> Tuple[float, float]:
    """اختبار t على قائمة IC values: H0: mean=0."""
    n = len(values)
    if n < 2:
        return 0.0, 1.0
    mean_v = sum(values) / n
    var_v  = sum((v - mean_v) ** 2 for v in values) / (n - 1)
    std_v  = math.sqrt(var_v) if var_v > 0 else 0.0
    if std_v == 0:
        return 0.0, 1.0
    t = mean_v / (std_v / math.sqrt(n))
    abs_t = abs(t)
    df = n - 1
    p = 2.0 * (1.0 - _normal_cdf(abs_t)) if df >= 10 else (0.05 if abs_t >= 2.78 else 0.20)
    return round(t, 3), round(min(p, 1.0), 4)


def top_quartile_expectancy(
    feat_vals: List[float],
    adj_returns: List[float],
    frac: float = TOP_DECILE,
) -> Tuple[float, float, int]:
    """
    يحسب E_adj per-feature لأعلى quartile مُرتَّبة حسب الميزة.
    يعيد (e_adj_top, e_adj_bottom, n_top).
    """
    if len(feat_vals) < 8:
        return 0.0, 0.0, 0

    paired   = list(zip(feat_vals, adj_returns))
    paired.sort(key=lambda p: p[0], reverse=True)
    k        = max(1, int(len(paired) * frac))
    top_k    = [r for _, r in paired[:k]]
    bot_k    = [r for _, r in paired[-k:]]

    def expectancy(rets):
        if not rets:
            return 0.0
        wins   = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        wr     = len(wins) / len(rets)
        avg_w  = sum(wins)   / len(wins)   if wins   else 0.0
        avg_l  = sum(losses) / len(losses) if losses else 0.0
        return wr * avg_w + (1 - wr) * avg_l

    return round(expectancy(top_k), 4), round(expectancy(bot_k), 4), k


def bootstrap_expectancy_ci(
    feat_vals: List[float],
    adj_returns: List[float],
    n_boot: int = N_BOOTSTRAP,
    frac: float = TOP_DECILE,
) -> Tuple[float, float]:
    """Bootstrap CI 95% لـ E_adj في top quartile."""
    n = len(feat_vals)
    if n < 8:
        return float('nan'), float('nan')

    obs_e_top, _, _ = top_quartile_expectancy(feat_vals, adj_returns, frac)

    boot_means = []
    paired = list(zip(feat_vals, adj_returns))

    for _ in range(n_boot):
        sample = [paired[random.randint(0, n - 1)] for _ in range(n)]
        fv = [p[0] for p in sample]
        ar = [p[1] for p in sample]
        e, _, _ = top_quartile_expectancy(fv, ar, frac)
        boot_means.append(e)

    boot_means.sort()
    lo = boot_means[int(0.025 * n_boot)]
    hi = boot_means[int(0.975 * n_boot)]
    return round(lo, 4), round(hi, 4)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Walk-Forward IC (من part15 — محقَّق)
# ═══════════════════════════════════════════════════════════════════════════

def walk_forward_ic(
    records: List[Dict],
    feat_name: str,
) -> Dict:
    """
    يحسب IC على نوافذ Walk-Forward OOS.
    IC per-window = spearman(feat_vals_OOS, profit_adj_OOS) — صحيح.
    """
    n = len(records)

    if n < N_WF_WINDOWS * MIN_N_WINDOW:
        return {
            'feature':        feat_name,
            'ic_per_window':  [],
            'ic_mean':        0.0,
            'ic_std':         0.0,
            'icir':           0.0,
            't_stat':         0.0,
            'p_value':        1.0,
            'n_oos_total':    0,
            'note':           'insufficient_data',
        }

    feat_vals_all = [r['smc'].get(feat_name, 0.0) for r in records]

    if len(set(feat_vals_all)) < 2:
        return {
            'feature':        feat_name,
            'ic_per_window':  [],
            'ic_mean':        0.0,
            'ic_std':         0.0,
            'icir':           0.0,
            't_stat':         0.0,
            'p_value':        1.0,
            'n_oos_total':    0,
            'note':           'no_variance',
        }

    window_size = n // N_WF_WINDOWS
    ic_list     = []
    n_oos_total = 0

    for w in range(N_WF_WINDOWS):
        start = w * window_size
        end   = start + window_size if w < N_WF_WINDOWS - 1 else n
        window = records[start:end]

        split  = int(len(window) * TRAIN_RATIO)
        oos    = window[split:]

        if len(oos) < MIN_N_WINDOW:
            continue

        oos_feat = [r['smc'].get(feat_name, 0.0) for r in oos]
        oos_ret  = [r['profit_adj'] for r in oos]

        if len(set(oos_feat)) < 2:
            continue

        # IC الحقيقي: Spearman(feature_values_OOS, profit_adj_OOS)
        ic = spearman_rho(oos_feat, oos_ret)
        ic_list.append(ic)
        n_oos_total += len(oos)

    if not ic_list:
        return {
            'feature': feat_name, 'ic_per_window': [], 'ic_mean': 0.0,
            'ic_std': 0.0, 'icir': 0.0, 't_stat': 0.0, 'p_value': 1.0,
            'n_oos_total': 0, 'note': 'all_windows_skipped',
        }

    ic_mean = sum(ic_list) / len(ic_list)

    if len(ic_list) >= 2:
        ic_var = sum((v - ic_mean) ** 2 for v in ic_list) / (len(ic_list) - 1)
        ic_std = math.sqrt(ic_var) if ic_var > 0 else 1e-9
        icir   = max(-50.0, min(50.0, ic_mean / ic_std))
        t_stat, p_val = ttest_one_sample(ic_list)
    else:
        ic_std = 0.0
        icir   = ic_mean
        t_stat = 0.0
        p_val  = 0.20

    return {
        'feature':         feat_name,
        'ic_per_window':   [round(v, 4) for v in ic_list],
        'ic_mean':         round(ic_mean, 4),
        'ic_std':          round(ic_std, 4),
        'icir':            round(icir, 3),
        't_stat':          t_stat,
        'p_value':         p_val,
        'n_oos_total':     n_oos_total,
        'n_windows_used':  len(ic_list),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 6. Benjamini-Hochberg FDR
# ═══════════════════════════════════════════════════════════════════════════

def benjamini_hochberg(results: List[Dict], alpha: float = FDR_ALPHA) -> List[Dict]:
    """تصحيح BH على p-values."""
    m = len(results)
    if m == 0:
        return results

    sorted_res = sorted(enumerate(results), key=lambda x: x[1].get('p_value', 1.0))
    bh_thresh  = [(i + 1) / m * alpha for i in range(m)]
    max_k      = -1

    for rank, (orig_idx, res) in enumerate(sorted_res):
        if res.get('p_value', 1.0) <= bh_thresh[rank]:
            max_k = rank

    for rank, (orig_idx, res) in enumerate(sorted_res):
        results[orig_idx]['bh_rejected']  = (rank <= max_k)
        results[orig_idx]['bh_threshold'] = round(bh_thresh[rank], 5)

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 7. النقطة الرئيسية
# ═══════════════════════════════════════════════════════════════════════════

async def run_smc_advanced():
    random.seed(42)

    print("=" * 70)
    print("الباكتيستر — الجزء 37: SMC المتقدّم من OHLC الحقيقي")
    print(f"تاريخ التشغيل: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    # ── 1. تحميل البيانات ────────────────────────────────────────────────
    print("\n[1] تحميل إشارات 1d من DB...")
    records = await load_1d_signals()
    n_total = len(records)
    n_win   = sum(r['label'] for r in records)
    print(f"    الكل: {n_total} (WIN={n_win}, WR={n_win/n_total*100:.1f}%)")
    print(f"    النطاق: {records[0]['signal_time'].strftime('%Y-%m-%d')} → {records[-1]['signal_time'].strftime('%Y-%m-%d')}")

    # ── Phase A: ETHUSDT smoke-test ──────────────────────────────────────
    eth_records = [r for r in records if r['symbol'] == 'ETHUSDT']
    print(f"\n[Phase A] ETHUSDT pipeline smoke-test: n={len(eth_records)}")

    client = await AsyncClient.create(
        api_key=config.BINANCE_API_KEY,
        api_secret=config.BINANCE_API_SECRET,
    )
    cache = load_cache()

    if eth_records:
        for rec in eth_records[:3]:
            df = await fetch_candles(client, rec['symbol'], rec['signal_time'], cache)
            if df is not None:
                feats = compute_all_smc_features(df, rec['entry_price'])
                rec['smc'] = feats
                print(f"    {rec['symbol']} {rec['signal_time'].strftime('%Y-%m-%d')}: "
                      f"imbalance_ratio={feats.get('imbalance_body_ratio'):.2f}, "
                      f"choch_bull={feats.get('choch_bullish'):.0f}, "
                      f"discount_dist={feats.get('discount_dist'):.3f}, "
                      f"fvg_age={feats.get('fvg_age'):.0f}, "
                      f"ob_vol_ratio={feats.get('ob_vol_ratio'):.2f}")
                await asyncio.sleep(API_DELAY_S)
            else:
                print(f"    {rec['symbol']}: فشل جلب الشموع")
        print("    [Phase A] Pipeline OK")
    else:
        print("    لا إشارات ETHUSDT 1d — اكتمل الـ smoke-test بالتخطّي")

    # ── Phase B: جميع 1d ─────────────────────────────────────────────────
    print(f"\n[Phase B] تحليل الحافة الكامل — جميع 1d (n={n_total})")
    print(f"    جلب OHLC من Binance (مع cache)...")

    processed = 0
    skipped   = 0

    for i, rec in enumerate(records):
        if rec.get('smc'):
            processed += 1
            continue

        df = await fetch_candles(client, rec['symbol'], rec['signal_time'], cache)
        if df is not None and len(df) >= SWING_LBK + 3:
            rec['smc'] = compute_all_smc_features(df, rec['entry_price'])
            processed += 1
        else:
            rec['smc'] = {}
            skipped += 1

        await asyncio.sleep(API_DELAY_S)

        if (i + 1) % 50 == 0:
            print(f"    [{i+1}/{n_total}] معالجة={processed}, تخطّي={skipped}")
            save_cache(cache)

    await client.close_connection()
    save_cache(cache)

    print(f"\n    اكتمل: معالجة={processed}, تخطّي={skipped}")

    # تصفية السجلات الصالحة
    valid  = [r for r in records if r.get('smc')]
    n_valid = len(valid)
    print(f"    سجلات صالحة: {n_valid}/{n_total}")

    if n_valid < N_WF_WINDOWS * MIN_N_WINDOW:
        print(f"ERROR: n_valid={n_valid} < حد Walk-Forward")
        return

    # ── 3. أسماء الميزات ─────────────────────────────────────────────────
    all_feat_names = set()
    for r in valid:
        all_feat_names.update(r['smc'].keys())
    feature_names = sorted(all_feat_names)

    print(f"\n[3] الميزات المحسوبة: {len(feature_names)}")
    for fn in feature_names:
        n_nz = sum(1 for r in valid if r['smc'].get(fn, 0) != 0)
        pct  = n_nz / n_valid * 100
        print(f"    {fn:35s}: non-zero={n_nz}/{n_valid} ({pct:.0f}%)")

    # ── 4. Walk-Forward IC ────────────────────────────────────────────────
    print(f"\n[4] Walk-Forward IC ({N_WF_WINDOWS} نوافذ × OOS Spearman IC)...")
    wf_results = []
    for fname in feature_names:
        res = walk_forward_ic(valid, fname)
        wf_results.append(res)

    # ── 5. E_adj per-feature + Bootstrap CI ──────────────────────────────
    print("\n[5] E_adj per-feature + Bootstrap CI 95%...")
    for res in wf_results:
        fname  = res['feature']
        fvals  = [r['smc'].get(fname, 0.0) for r in valid]
        arets  = [r['profit_adj'] for r in valid]

        e_top, e_bot, n_q = top_quartile_expectancy(fvals, arets, TOP_DECILE)
        ci_lo, ci_hi      = bootstrap_expectancy_ci(fvals, arets)

        res['e_adj_top_q']  = e_top
        res['e_adj_bot_q']  = e_bot
        res['n_top_q']      = n_q
        res['e_adj_ci_lo']  = ci_lo
        res['e_adj_ci_hi']  = ci_hi

    # ── 6. Benjamini-Hochberg FDR ─────────────────────────────────────────
    wf_results = benjamini_hochberg(wf_results, alpha=FDR_ALPHA)

    # ── 7. ترتيب النتائج ──────────────────────────────────────────────────
    wf_results.sort(key=lambda r: (
        -int(r.get('bh_rejected', False)),
        -abs(r.get('icir', 0.0)),
    ))

    # ── 8. طباعة الجدول الكامل ───────────────────────────────────────────
    print()
    print(f"{'الميزة':30s} {'IC_mean':>9} {'IC_std':>7} {'ICIR':>7} {'p_val':>7} {'BH':>5} {'E_top25%':>10} {'CI_lo':>8} {'CI_hi':>8}")
    print("-" * 100)

    surviving_features = []
    for r in wf_results:
        note = r.get('note', '')
        if note in ('no_variance', 'insufficient_data', 'all_windows_skipped'):
            print(f"  {r['feature']:30s}: [محذوفة — {note}]")
            continue

        bh    = "YES" if r.get('bh_rejected') else "no"
        flag  = ""
        if r.get('bh_rejected') and r.get('e_adj_top_q', 0) > 0:
            flag = "<< ناجية"
            surviving_features.append(r)

        print(
            f"  {r['feature']:30s} "
            f"{r['ic_mean']:>+9.4f} "
            f"{r['ic_std']:>7.4f} "
            f"{r['icir']:>+7.3f} "
            f"{r['p_value']:>7.4f} "
            f"{bh:>5} "
            f"{r.get('e_adj_top_q', 0.0):>+10.4f} "
            f"{r.get('e_adj_ci_lo', float('nan')):>8.4f} "
            f"{r.get('e_adj_ci_hi', float('nan')):>8.4f} "
            f"{flag}"
        )

    # ── 9. الملخص ─────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("== الملخص ==")
    print()
    print(f"n الكلي:           {n_total}")
    print(f"n صالح (OHLC):     {n_valid}")
    print(f"n post-freeze:     {sum(1 for r in valid if r['signal_time'].strftime('%Y-%m-%d') > '2026-05-17')}")
    print(f"الميزات المختبرة:   {len(feature_names)}")
    print(f"الناجيات (FDR YES + E_top>0): {len(surviving_features)}")
    print()

    if surviving_features:
        print("الميزات الناجية:")
        for f in surviving_features:
            win_str = ", ".join(f"{v:+.3f}" for v in f.get('ic_per_window', []))
            print(f"\n  {f['feature']}:")
            print(f"    IC_mean={f['ic_mean']:+.4f} ± {f['ic_std']:.4f} (ICIR={f['icir']:+.3f})")
            print(f"    IC النوافذ: [{win_str}]")
            print(f"    p_value={f['p_value']:.4f} (بعد BH)")
            print(f"    E_adj أعلى 25%: {f['e_adj_top_q']:+.4f}% (n={f['n_top_q']}, CI=[{f['e_adj_ci_lo']:.4f}, {f['e_adj_ci_hi']:.4f}])")
        print()
        print("تحذير إحصائي: أي ناجٍ يحتاج post-freeze OOS (n≥30) قبل أي توصية حيّة.")
        print(f"  n_post_freeze حالياً = {sum(1 for r in valid if r['signal_time'].strftime('%Y-%m-%d') > '2026-05-17')} — غير كافٍ.")
    else:
        print("لا ميزات ناجية — تأكيد خامس على غياب حافة SMC في المؤشرات التقنية.")
        print("(انظر: edge_discovery, research_conclusion_2026_05_25, ICT v1+v3, killzone v2)")

    print()
    print("مقارنة مع baseline الحالي (1d+bearish/sideways+score=3):")
    base_1d_bs = [r for r in valid if r['market_condition'] in ('bearish', 'sideways') and r['score'] >= 3.0]
    if base_1d_bs:
        wt = sum(r['label'] for r in base_1d_bs)
        ea = sum(r['profit_adj'] for r in base_1d_bs) / len(base_1d_bs)
        print(f"  n={len(base_1d_bs)}, WR={wt/len(base_1d_bs)*100:.1f}%, E_adj={ea:+.4f}%")

    # ── 10. حفظ النتائج ──────────────────────────────────────────────────
    output_rows = []
    for r in wf_results:
        row = {k: v for k, v in r.items() if not isinstance(v, list)}
        row['ic_per_window']     = r.get('ic_per_window', [])
        row['phase']             = 'B_all_1d'
        row['n_total']           = n_total
        row['n_valid']           = n_valid
        row['base_wr_1d']        = round(n_win / n_total, 4)
        row['timestamp']         = datetime.utcnow().isoformat()
        output_rows.append(row)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for row in output_rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')

    print(f"\n[10] النتائج محفوظة في: {OUTPUT_FILE}")
    print("=" * 70)
    print("اكتمل الجزء 37")
    print("=" * 70)


if __name__ == '__main__':
    asyncio.run(run_smc_advanced())
