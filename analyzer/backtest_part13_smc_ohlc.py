"""
الباكتيستر — الجزء الثالث عشر: SMC الدقيق من شموع OHLC خام
==============================================================
يحسب مؤشرات Smart Money Concepts (SMC) من سلاسل شموع OHLC حقيقية
يجلبها من Binance API — لا proxies، لا مستويات مُشتقّة.

المؤشرات المُنفَّذة:
  1. BOS  — Break of Structure: كسر أعلى swing high سابق (bullish BOS)
            أو أدنى swing low سابق (bearish BOS).
  2. FVG  — Fair Value Gap: فجوة بين شمعتين غير مُغلقة من الطرف الثالث.
  3. OB   — Order Block: آخر شمعة هابطة قبل حركة صعودية قوية (bullish OB).
  4. Liq  — Liquidity Sweep: تجاوز شمعة لـ swing high/low ثم الإغلاق داخله.

المنهجية:
  - يجلب الإشارات + نتائجها من DB (trade_results JOIN signals).
  - لكل إشارة، يجلب 100 شمعة 1h من Binance تنتهي عند وقت الإشارة.
  - يحسب المؤشرات الأربعة من الشموع الخام (pandas/numpy فقط).
  - يقيّم القدرة التنبؤية لكل مؤشر: IC (Spearman ρ) + ΔExpectancy.

القيود:
  - معالجة متدفّقة: عملة-عملة، حد ذاكرة آمن لـ aarch64/2GB RAM.
  - لا حزم جديدة — pandas + numpy + asyncio + binance فقط.
  - النتائج أولية (preliminary) — n < 99 صفقة لكل شريحة.

المخرج: backtest_results_part13.jsonl + ملخص طباعي.
"""

import asyncio
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

sys.path.append('/app')

import numpy as np
import pandas as pd

from binance import AsyncClient
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('backtester.part13')

OUTPUT_FILE   = '/app/backtest_results_part13.jsonl'
CANDLES_1H    = 100      # عدد شموع 1h للجلب لكل إشارة
CANDLES_1D    = 60       # عدد شموع 1d للجلب لكل إشارة
SWING_LOOKBACK = 5       # عدد الشموع للبحث عن swing points
MIN_N_FOR_IC  = 5        # حد أدنى للحساب الموثوق
API_DELAY_S   = 0.12     # تأخير بين طلبات API (rate limit safety)
MAX_SIGNALS   = 2433     # حد أقصى للإشارات (كل الموجودة)


# ═══════════════════════════════════════════════════════════════════════════
# 1. تحميل الإشارات وعلاماتها من DB
# ═══════════════════════════════════════════════════════════════════════════

async def load_labeled_signals() -> List[Dict]:
    """
    يجلب الإشارات التي لها نتيجة مُسجَّلة (WIN/LOSS) من DB.
    يعيد قائمة مرتبة زمنياً.
    """
    await Database.connect()
    try:
        rows = await Database.fetch("""
            SELECT
                s.id,
                s.symbol,
                s.timeframe,
                s.market_condition,
                s.entry_price,
                s.target_1,
                s.target_2,
                s.target_3,
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
            LIMIT $1
        """, MAX_SIGNALS)

        records = []
        for row in rows:
            sd = row['score_details']
            if isinstance(sd, str):
                sd = json.loads(sd)
            records.append({
                'id':               row['id'],
                'symbol':           row['symbol'],
                'timeframe':        row['timeframe'],
                'market_condition': row['market_condition'],
                'entry_price':      float(row['entry_price']),
                'target_1':         float(row['target_1']),
                'target_2':         float(row['target_2']),
                'target_3':         float(row['target_3']),
                'stop_loss':        float(row['stop_loss']),
                'score':            row['score'],
                'score_details':    sd or {},
                'signal_time':      row['signal_time'],
                'result':           row['result'],
                'profit_percent':   float(row['profit_percent'] or 0.0),
                'label':            1 if row['result'] == 'WIN' else 0,
            })
        return records
    finally:
        await Database.disconnect()


# ═══════════════════════════════════════════════════════════════════════════
# 2. جلب الشموع من Binance
# ═══════════════════════════════════════════════════════════════════════════

async def fetch_candles(
    client: AsyncClient,
    symbol: str,
    interval: str,
    end_time_dt: datetime,
    limit: int = 100,
) -> Optional[pd.DataFrame]:
    """
    يجلب `limit` شمعة بـ interval تنتهي عند end_time_dt.
    يعيد DataFrame بـ OHLCV أو None عند الفشل.
    """
    try:
        end_ms = int(end_time_dt.timestamp() * 1000)
        klines = await client.get_klines(
            symbol=symbol,
            interval=interval,
            limit=limit,
            endTime=end_ms,
        )
        if not klines or len(klines) < SWING_LOOKBACK + 2:
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
        return df
    except Exception as e:
        logger.warning(f"فشل جلب {symbol}/{interval}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 3. حسابات SMC الدقيقة من OHLC
# ═══════════════════════════════════════════════════════════════════════════

def find_swing_points(df: pd.DataFrame, lookback: int = SWING_LOOKBACK) -> Tuple[List[float], List[float]]:
    """
    يجد swing highs وswing lows من DataFrame OHLC.

    Swing High: شمعة تكون high أعلى من `lookback` شمعة يمين ويسار.
    Swing Low:  شمعة تكون low أدنى من `lookback` شمعة يمين ويسار.

    يعيد: (قائمة swing_highs، قائمة swing_lows) كقيم رقمية.
    """
    highs = df['high'].values
    lows  = df['low'].values
    n     = len(highs)

    swing_highs: List[float] = []
    swing_lows:  List[float] = []

    for i in range(lookback, n - lookback):
        # Swing High
        left_h  = highs[i - lookback:i]
        right_h = highs[i + 1:i + lookback + 1]
        if len(left_h) == lookback and len(right_h) == lookback:
            if highs[i] > max(left_h) and highs[i] >= max(right_h):
                swing_highs.append(float(highs[i]))

        # Swing Low
        left_l  = lows[i - lookback:i]
        right_l = lows[i + 1:i + lookback + 1]
        if len(left_l) == lookback and len(right_l) == lookback:
            if lows[i] < min(left_l) and lows[i] <= min(right_l):
                swing_lows.append(float(lows[i]))

    return swing_highs, swing_lows


def compute_bos(df: pd.DataFrame, entry_price: float) -> Dict[str, float]:
    """
    Break of Structure (BOS) — من swing points حقيقية.

    Bullish BOS: آخر إغلاق تجاوز آخر swing high موثَّق.
    Bearish BOS: آخر إغلاق كسر تحت آخر swing low موثَّق.

    المخرجات:
    - smc_bos_bullish: 1 إذا كان هناك BOS صاعد قبل نقطة الدخول
    - smc_bos_bearish: 1 إذا كان هناك BOS هابط قبل نقطة الدخول
    - smc_bos_strength: قوة الكسر = (close - swing_high) / swing_high
    - smc_last_swing_high: آخر swing high (نسبي لـ entry)
    - smc_last_swing_low:  آخر swing low (نسبي لـ entry)
    """
    swing_highs, swing_lows = find_swing_points(df)
    closes = df['close'].values

    result = {
        'smc_bos_bullish':     0.0,
        'smc_bos_bearish':     0.0,
        'smc_bos_strength':    0.0,
        'smc_last_swing_high': 0.0,
        'smc_last_swing_low':  0.0,
    }

    if not swing_highs or not swing_lows or len(closes) < 2:
        return result

    last_sh = swing_highs[-1]
    last_sl = swing_lows[-1]

    # آخر إغلاق (الشمعة قبل الدخول)
    last_close = float(closes[-2]) if len(closes) >= 2 else float(closes[-1])

    # BOS صاعد: الإغلاق تجاوز swing high موثَّق
    if last_close > last_sh and entry_price > 0:
        result['smc_bos_bullish'] = 1.0
        result['smc_bos_strength'] = (last_close - last_sh) / last_sh if last_sh > 0 else 0.0

    # BOS هابط: الإغلاق كسر swing low موثَّق
    if last_close < last_sl and entry_price > 0:
        result['smc_bos_bearish'] = 1.0
        result['smc_bos_strength'] = (last_sl - last_close) / last_sl if last_sl > 0 else 0.0

    # نسبة swing levels لـ entry (لتطبيع المقارنة بين العملات)
    result['smc_last_swing_high'] = (last_sh - entry_price) / entry_price if entry_price > 0 else 0.0
    result['smc_last_swing_low']  = (entry_price - last_sl) / entry_price if entry_price > 0 else 0.0

    return result


def compute_fvg(df: pd.DataFrame, entry_price: float) -> Dict[str, float]:
    """
    Fair Value Gap (FVG) الدقيق — من تسلسل 3 شموع.

    FVG Bullish: low[i+2] > high[i]  (فجوة بين شمعة -2 والشمعة الحالية)
    FVG Bearish: high[i+2] < low[i]

    المخرجات:
    - smc_fvg_bull_present: هل يوجد FVG صاعد في آخر 20 شمعة
    - smc_fvg_bear_present: هل يوجد FVG هابط في آخر 20 شمعة
    - smc_fvg_bull_size:    حجم أكبر FVG صاعد نسبة لـ entry
    - smc_fvg_bear_size:    حجم أكبر FVG هابط نسبة لـ entry
    - smc_entry_in_fvg:     هل entry يقع داخل فجوة FVG صاعدة (مؤشر دخول مثالي)
    """
    highs  = df['high'].values
    lows   = df['low'].values
    n      = len(highs)
    window = min(20, n - 2)

    result = {
        'smc_fvg_bull_present': 0.0,
        'smc_fvg_bear_present': 0.0,
        'smc_fvg_bull_size':    0.0,
        'smc_fvg_bear_size':    0.0,
        'smc_entry_in_fvg':     0.0,
    }

    bull_fvgs: List[Tuple[float, float]] = []  # (low_of_gap, high_of_gap)
    bear_fvgs: List[Tuple[float, float]] = []

    start_idx = max(0, n - window - 2)
    for i in range(start_idx, n - 2):
        # Bullish FVG: شمعة i ثم i+1 ثم i+2 — شرط: low[i+2] > high[i]
        if lows[i + 2] > highs[i]:
            gap_lo = float(highs[i])
            gap_hi = float(lows[i + 2])
            bull_fvgs.append((gap_lo, gap_hi))

        # Bearish FVG: high[i+2] < low[i]
        if highs[i + 2] < lows[i]:
            gap_lo = float(highs[i + 2])
            gap_hi = float(lows[i])
            bear_fvgs.append((gap_lo, gap_hi))

    if bull_fvgs:
        result['smc_fvg_bull_present'] = 1.0
        sizes = [(hi - lo) / entry_price for lo, hi in bull_fvgs if entry_price > 0]
        result['smc_fvg_bull_size'] = round(max(sizes), 5) if sizes else 0.0

        # هل entry داخل أحد الـ FVG الصاعدة
        for gap_lo, gap_hi in bull_fvgs:
            if gap_lo <= entry_price <= gap_hi:
                result['smc_entry_in_fvg'] = 1.0
                break

    if bear_fvgs:
        result['smc_fvg_bear_present'] = 1.0
        sizes = [(hi - lo) / entry_price for lo, hi in bear_fvgs if entry_price > 0]
        result['smc_fvg_bear_size'] = round(max(sizes), 5) if sizes else 0.0

    return result


def compute_order_block(df: pd.DataFrame, entry_price: float) -> Dict[str, float]:
    """
    Order Block (OB) الدقيق — من تسلسل الشموع.

    Bullish OB: آخر شمعة هابطة (close < open) قبل حركة صعودية قوية
                (close[i+3] > high[i] بنسبة > 1%).
    خصائص OB الجيد:
      - ضيّق: (high - low) / entry صغير
      - Entry يقع داخل نطاق OB أو قريب منه
      - لم يُعاد اختباره (untested OB أقوى)

    المخرجات:
    - smc_ob_bullish:      هل يوجد OB صاعد معتمد
    - smc_ob_width:        عرض OB نسبة لـ entry (صغير = أفضل)
    - smc_ob_entry_inside: هل entry داخل نطاق OB
    - smc_ob_tested:       هل OB أُعيد اختباره (كلما أقل = أقوى)
    - smc_ob_strength:     قوة الحركة بعد OB
    """
    opens  = df['open'].values
    closes = df['close'].values
    highs  = df['high'].values
    lows   = df['low'].values
    n      = len(closes)

    result = {
        'smc_ob_bullish':      0.0,
        'smc_ob_width':        0.0,
        'smc_ob_entry_inside': 0.0,
        'smc_ob_tested':       0.0,
        'smc_ob_strength':     0.0,
    }

    if n < 10:
        return result

    window = min(30, n - 5)
    start  = max(0, n - window - 5)

    best_ob = None  # (ob_low, ob_high, ob_strength, ob_tested)

    for i in range(start, n - 4):
        # شمعة هابطة (bearish candle)
        if closes[i] >= opens[i]:
            continue

        # الحركة بعدها: هل الإغلاق بعد 3 شموع أعلى من high[i]
        future_close = closes[min(i + 3, n - 1)]
        future_high  = max(highs[i + 1:min(i + 4, n)])
        move_pct     = (future_close - closes[i]) / closes[i] if closes[i] > 0 else 0

        if move_pct < 0.01:
            continue

        ob_low  = float(lows[i])
        ob_high = float(highs[i])
        ob_str  = round(move_pct, 4)

        # هل OB أُعيد اختباره (re-tested): هل أي شمعة لاحقة دخلت نطاق OB
        tested = 0
        for j in range(i + 1, n):
            if lows[j] <= ob_high and closes[j] >= ob_low:
                tested = 1
                break

        if best_ob is None or ob_str > best_ob[2]:
            best_ob = (ob_low, ob_high, ob_str, tested)

    if best_ob is not None:
        ob_low, ob_high, ob_str, ob_tested = best_ob
        ob_width = (ob_high - ob_low) / entry_price if entry_price > 0 else 0.0

        result['smc_ob_bullish']  = 1.0
        result['smc_ob_width']    = round(ob_width, 5)
        result['smc_ob_strength'] = ob_str
        result['smc_ob_tested']   = float(ob_tested)

        if ob_low <= entry_price <= ob_high:
            result['smc_ob_entry_inside'] = 1.0

    return result


def compute_liquidity_sweep(df: pd.DataFrame, entry_price: float) -> Dict[str, float]:
    """
    Liquidity Sweep الدقيق — تجاوز swing high/low ثم الإغلاق داخله.

    Bullish Sweep: شمعة تتجاوز swing low (لتسييل المضاربين البائعين)
                  ثم تُغلق فوقه — مؤشر قوي على التحول الصاعد.
    Bearish Sweep: تجاوز swing high ثم الإغلاق تحته.

    المخرجات:
    - smc_sweep_bull:      هل حدث Bullish Sweep قبل الدخول
    - smc_sweep_bear:      هل حدث Bearish Sweep قبل الدخول
    - smc_sweep_depth:     عمق السويب نسبة لـ entry (كبير = سيولة أكثر تُسحب)
    - smc_sweep_recovery:  سرعة التعافي بعد السويب (قصير = أقوى)
    - smc_sweep_count:     عدد السويبات في آخر 30 شمعة
    """
    swing_highs, swing_lows = find_swing_points(df)
    lows   = df['low'].values
    highs  = df['high'].values
    closes = df['close'].values
    n      = len(closes)

    result = {
        'smc_sweep_bull':     0.0,
        'smc_sweep_bear':     0.0,
        'smc_sweep_depth':    0.0,
        'smc_sweep_recovery': 0.0,
        'smc_sweep_count':    0.0,
    }

    if not swing_lows or not swing_highs or n < SWING_LOOKBACK + 3:
        return result

    sweep_count = 0

    # Bullish Sweep: شمعة low أدنى من swing_low ثم close فوقه
    if swing_lows:
        last_sl = swing_lows[-1]
        for i in range(SWING_LOOKBACK, n - 1):
            if lows[i] < last_sl and closes[i] > last_sl:
                sweep_count += 1
                depth = (last_sl - lows[i]) / entry_price if entry_price > 0 else 0
                # التعافي: عدد الشموع للعودة فوق last_sl (أقل = أسرع)
                recovery = 1  # بما أن نفس الشمعة أغلقت فوقه
                result['smc_sweep_bull']     = 1.0
                result['smc_sweep_depth']    = round(depth, 5)
                result['smc_sweep_recovery'] = recovery

    # Bearish Sweep: شمعة high أعلى من swing_high ثم close تحته
    if swing_highs:
        last_sh = swing_highs[-1]
        for i in range(SWING_LOOKBACK, n - 1):
            if highs[i] > last_sh and closes[i] < last_sh:
                sweep_count += 1
                result['smc_sweep_bear'] = 1.0

    result['smc_sweep_count'] = float(min(sweep_count, 10))

    return result


def compute_smc_features(df: pd.DataFrame, entry_price: float) -> Dict[str, float]:
    """يجمع جميع مؤشرات SMC الدقيقة من DataFrame OHLC."""
    features = {}
    features.update(compute_bos(df, entry_price))
    features.update(compute_fvg(df, entry_price))
    features.update(compute_order_block(df, entry_price))
    features.update(compute_liquidity_sweep(df, entry_price))
    return features


# ═══════════════════════════════════════════════════════════════════════════
# 4. قياس القدرة التنبؤية (IC + ΔExpectancy)
# ═══════════════════════════════════════════════════════════════════════════

def spearman_rho(x: List[float], y: List[float]) -> float:
    """Spearman rank correlation (IC)."""
    n = len(x)
    if n < MIN_N_FOR_IC:
        return 0.0

    def rank_list(lst):
        sorted_idx = sorted(range(n), key=lambda i: lst[i])
        ranks = [0.0] * n
        for rank, idx in enumerate(sorted_idx):
            ranks[idx] = float(rank + 1)
        return ranks

    rx = rank_list(x)
    ry = rank_list(y)
    mrx = sum(rx) / n
    mry = sum(ry) / n
    num   = sum((rx[i] - mrx) * (ry[i] - mry) for i in range(n))
    den_x = math.sqrt(sum((rx[i] - mrx) ** 2 for i in range(n)))
    den_y = math.sqrt(sum((ry[i] - mry) ** 2 for i in range(n)))
    if den_x == 0 or den_y == 0:
        return 0.0
    return round(num / (den_x * den_y), 4)


def delta_expectancy(feat_vals: List[float], returns: List[float], n_bins: int = 4) -> float:
    """فرق Expectancy بين أعلى وأدنى quantile."""
    if len(feat_vals) < n_bins * 2:
        return 0.0

    paired   = sorted(zip(feat_vals, returns), key=lambda p: p[0])
    bin_size = max(1, len(paired) // n_bins)
    top_q    = paired[-bin_size:]
    bot_q    = paired[:bin_size]

    def exp_of(pairs):
        rets   = [r for _, r in pairs]
        if not rets:
            return 0.0
        wins   = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        wr     = len(wins) / len(rets)
        avg_w  = sum(wins) / len(wins)     if wins   else 0.0
        avg_l  = sum(losses) / len(losses) if losses else 0.0
        return wr * avg_w + (1 - wr) * avg_l

    return round(exp_of(top_q) - exp_of(bot_q), 4)


def analyze_feature_edge(
    records: List[Dict],
    feature_names: List[str],
) -> List[Dict]:
    """يُقيّم القدرة التنبؤية لكل مؤشر SMC."""
    returns  = [r['profit_percent'] for r in records]
    ranking  = []

    for feat in feature_names:
        vals = [r.get('smc_features', {}).get(feat, 0.0) for r in records]

        if len(set(vals)) < 2:
            ranking.append({
                'feature': feat, 'ic': 0.0, 'delta_e': 0.0,
                'n_nonzero': 0, 'note': 'no_variance',
            })
            continue

        ic      = spearman_rho(vals, returns)
        de      = delta_expectancy(vals, returns)
        n_nz    = sum(1 for v in vals if v != 0.0)
        n_total = len(vals)

        # حساب win rate لكل segment (0 vs 1 للميزات الثنائية)
        seg_stats = {}
        if set(vals) <= {0.0, 1.0}:
            for seg_val in [0.0, 1.0]:
                seg_rets = [r['profit_percent'] for r, v in zip(records, vals) if v == seg_val]
                seg_wins = [r for r in seg_rets if r > 0]
                seg_stats[f'seg_{int(seg_val)}_n']  = len(seg_rets)
                seg_stats[f'seg_{int(seg_val)}_wr'] = round(len(seg_wins) / len(seg_rets), 3) if seg_rets else 0.0
                seg_stats[f'seg_{int(seg_val)}_e']  = round(sum(seg_rets) / len(seg_rets), 4) if seg_rets else 0.0

        ranking.append({
            'feature':    feat,
            'ic':         ic,
            'delta_e':    de,
            'n_nonzero':  n_nz,
            'n_total':    n_total,
            **seg_stats,
        })

    ranking.sort(key=lambda x: abs(x.get('ic', 0.0)), reverse=True)
    return ranking


# ═══════════════════════════════════════════════════════════════════════════
# 5. النقطة الرئيسية
# ═══════════════════════════════════════════════════════════════════════════

async def run_smc_lab():
    print("=" * 70)
    print("الباكتيستر — الجزء الثالث عشر: SMC الدقيق من شموع OHLC خام")
    print("=" * 70)

    # 1. تحميل الإشارات من DB
    print("\n[1] تحميل الإشارات من قاعدة البيانات...")
    records = await load_labeled_signals()
    if not records:
        print("ERROR: لا إشارات مُعلَّمة في DB")
        sys.exit(1)

    n_total = len(records)
    n_win   = sum(r['label'] for r in records)
    print(f"    إجمالي: {n_total} (WIN={n_win}, LOSS={n_total-n_win}, WR={n_win/n_total*100:.1f}%)")

    # 2. جلب الشموع وحساب SMC
    print("\n[2] جلب الشموع من Binance وحساب مؤشرات SMC...")
    print(f"    (المعالجة متدفّقة — عملة-عملة — {n_total} إشارة)")

    client = await AsyncClient.create(
        api_key=config.BINANCE_API_KEY,
        api_secret=config.BINANCE_API_SECRET,
    )

    processed = 0
    skipped   = 0
    error_log: List[str] = []

    try:
        for i, rec in enumerate(records):
            symbol     = rec['symbol']
            entry      = rec['entry_price']
            sig_time   = rec['signal_time']

            # نجلب الشموع التي انتهت قبل وقت الإشارة
            if sig_time.tzinfo is None:
                sig_time_utc = sig_time.replace(tzinfo=timezone.utc)
            else:
                sig_time_utc = sig_time.astimezone(timezone.utc)

            # نحدد interval بناءً على timeframe الإشارة
            tf = rec.get('timeframe', '1h')
            interval = tf if tf in ('1h', '4h', '1d') else '1h'
            candle_limit = CANDLES_1D if interval == '1d' else CANDLES_1H

            df = await fetch_candles(client, symbol, interval, sig_time_utc, candle_limit)

            if df is None or len(df) < SWING_LOOKBACK + 3:
                rec['smc_features'] = {}
                skipped += 1
            else:
                smc = compute_smc_features(df, entry)
                rec['smc_features'] = smc
                processed += 1

            await asyncio.sleep(API_DELAY_S)

            if (i + 1) % 100 == 0:
                print(f"    [{i+1}/{n_total}] معالجة: {processed}، تخطّي: {skipped}")

    except Exception as e:
        logger.error(f"خطأ في المعالجة: {e}")
        error_log.append(str(e))
    finally:
        await client.close_connection()

    print(f"\n    اكتمل: معالجة={processed}، تخطّي={skipped}")

    # تصفية السجلات التي لديها features فعلية
    valid_records = [r for r in records if r.get('smc_features')]
    n_valid = len(valid_records)
    print(f"    سجلات صالحة للتحليل: {n_valid}/{n_total}")

    if n_valid < MIN_N_FOR_IC * 2:
        print("ERROR: عينة صغيرة جداً للتحليل")
        sys.exit(1)

    # 3. تحديد أسماء الميزات
    all_feat_names = set()
    for r in valid_records:
        all_feat_names.update(r['smc_features'].keys())
    feature_names = sorted(all_feat_names)
    print(f"\n[3] مؤشرات SMC المحسوبة: {len(feature_names)}")
    for fn in feature_names:
        n_nz = sum(1 for r in valid_records if r['smc_features'].get(fn, 0) != 0)
        print(f"    {fn:35s}: non-zero={n_nz}/{n_valid} ({n_nz/n_valid*100:.0f}%)")

    # 4. تقييم القدرة التنبؤية
    print("\n[4] تقييم القدرة التنبؤية لكل مؤشر SMC")
    ranking = analyze_feature_edge(valid_records, feature_names)

    print(f"\n{'المؤشر':40s} {'IC':>8s}  {'ΔExpect':>9s}  {'n≠0':>6s}")
    print("-" * 70)
    for row in ranking:
        if row.get('note') == 'no_variance':
            continue
        flag = "**" if abs(row['ic']) >= 0.10 else ("*" if abs(row['ic']) >= 0.05 else "")
        print(
            f"{row['feature']:40s} "
            f"{row['ic']:>+8.4f}  "
            f"{row['delta_e']:>+9.4f}  "
            f"{row['n_nonzero']:>6d}  {flag}"
        )

    # 5. تحليل تفصيلي للميزات الثنائية القوية
    binary_strong = [r for r in ranking
                     if abs(r.get('ic', 0)) >= 0.05
                     and 'seg_0_n' in r
                     and r['n_nonzero'] >= MIN_N_FOR_IC]

    if binary_strong:
        print("\n[5] تفاصيل الميزات القوية (WR عند 0 vs 1):")
        for row in binary_strong[:8]:
            print(f"\n  {row['feature']}:")
            print(f"    بدون مؤشر (0): n={row.get('seg_0_n',0)}, "
                  f"WR={row.get('seg_0_wr',0)*100:.1f}%, "
                  f"E={row.get('seg_0_e',0):+.3f}%")
            print(f"    مع مؤشر   (1): n={row.get('seg_1_n',0)}, "
                  f"WR={row.get('seg_1_wr',0)*100:.1f}%, "
                  f"E={row.get('seg_1_e',0):+.3f}%")

    # 6. خلاصة
    strong    = [r for r in ranking if abs(r.get('ic', 0)) >= 0.10 and r.get('note') != 'no_variance']
    promising = [r for r in ranking if 0.05 <= abs(r.get('ic', 0)) < 0.10 and r.get('note') != 'no_variance']

    print(f"\n[6] الخلاصة:")
    print(f"    مؤشرات قوية (|IC|≥0.10):    {len(strong)}")
    print(f"    مؤشرات محتملة (|IC|≥0.05): {len(promising)}")
    print(f"    ملاحظة: preliminary — n={n_valid} إشارة")
    print(f"    التطبيق الحيّ يتطلب n≥99 لكل شريحة")

    if strong:
        print(f"\n    أقوى المؤشرات:")
        for f in strong[:5]:
            direction = "موجبة" if f['ic'] > 0 else "سالبة"
            print(f"      {f['feature']}: IC={f['ic']:+.4f} ({direction}), ΔE={f['delta_e']:+.4f}%")

    # 7. حفظ النتائج
    output = {
        'run_date':        datetime.utcnow().isoformat(),
        'preliminary':     True,
        'n_total':         n_total,
        'n_valid':         n_valid,
        'n_win':           n_win,
        'base_wr':         round(n_win / n_total, 4),
        'feature_count':   len(feature_names),
        'ranking':         ranking,
        'strong':          [f['feature'] for f in strong],
        'promising':       [f['feature'] for f in promising],
        'errors':          error_log,
    }
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(json.dumps(output, ensure_ascii=False, default=str) + '\n')

    print(f"\n[7] النتائج حُفظت في: {OUTPUT_FILE}")
    print("=" * 70)
    print("اكتمل الجزء الثالث عشر")
    print("=" * 70)

    return output


if __name__ == '__main__':
    asyncio.run(run_smc_lab())
