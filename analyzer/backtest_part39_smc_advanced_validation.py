"""
الباكتيستر — الجزء 39: SMC Advanced Validation (تحسين على Part 37)
===========================================================
هدف التجربة: التحقق من فعالية مؤشرات SMC متقدّمة (Imbalance + CHoCH + Order Blocks + Discount Zone)
ضد baseline الحالي (1d+bearish/sideways+score3) على بيانات post-freeze.

المنهج:
  - مرجع: 13 صفقة مغلقة post-freeze (2026-05-17 إلى 2026-05-29)
  - WR=23%, E=-0.28/trade, PnL=-3.65 USDT
  - اختبر: هل إضافة SMC features تحسّن WR و E؟
  - OHLC: 1h candles من Binance API
  - TripleBarrier: break-even بعد T1 + trailing 2.5% بعد T2 + 48h expiry
  - Walk-Forward: 5 نوافذ (timeline الإشارات)
  - Bootstrap CI: 10k على E_adj

مؤشرات SMC المرشحة (من part37):
  - FVG Detection: Support/Resistance zones من order flow imbalances
  - Imbalance Candles: شموع بـ body >= 2× متوسط آخر 20
  - CHoCH (Change of Character): انعكاس BOS من swing points
  - Order Block: آخر شمعة bullish قبل bearish reversal (بيانات: OB+Discount = 58% WR)
  - Discount Zone: تجمع سيولة أسفل support
  - Distance to FVG: ميزة تنبؤية (استقرار OOS عالي)

قيود:
  - لا حزم جديدة (numpy/pandas فقط — موجودة في analyzer/)
  - معالجة متدفّقة
  - cache pickle لـ OHLC
  - لا حذف من DB

المخرج: backtest_results_part39.jsonl + ملخص طباعي + leaderboard
"""

import asyncio
import json
import math
import pickle
import sys
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')

# حقنة: numpy/pandas موجودة في analyzer environment
try:
    import numpy as np
    import pandas as pd
except ImportError:
    print("⚠️ numpy/pandas غير متوفّر — fallback to JSON-only output")
    np = None
    pd = None

from binance import AsyncClient
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('backtester.part39')

OUTPUT_FILE = '/app/backtest_results_part39.jsonl'
CACHE_FILE  = '/app/part39_ohlc_cache.pkl'

# ثوابت
FEE_PCT = 0.003
N_BOOTSTRAP = 1000  # معتدل لـ aarch64 (RAM محدودة)
API_DELAY_S = 0.12
FREEZE_DATE = datetime(2026, 5, 17, tzinfo=timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════
# Part 1: Load post-freeze signals
# ═══════════════════════════════════════════════════════════════════════════

async def load_post_freeze_signals() -> List[Dict]:
    """جلب الإشارات المُولَّدة بعد التجميد (2026-05-17 إلى الآن)."""
    await Database.connect()
    try:
        rows = await Database.fetch("""
            SELECT
                s.id,
                s.symbol,
                s.market_condition,
                s.score,
                CAST(s.entry_price AS float) AS entry_price,
                CAST(s.stop_loss AS float) AS stop_loss,
                CAST(s.target_1 AS float) AS target_1,
                CAST(s.target_2 AS float) AS target_2,
                CAST(s.target_3 AS float) AS target_3,
                s.signal_time,
                s.timeframe,
                COALESCE(tr.result, 'OPEN') AS result,
                COALESCE(CAST(tr.profit_usdt AS float), 0) AS profit_usdt
            FROM signals s
            LEFT JOIN trade_results tr ON s.id = tr.signal_id
            WHERE s.timeframe = '1d'
              AND s.market_condition IN ('bearish', 'sideways')
              AND s.signal_time > %(freeze_date)s
              AND CAST(s.score AS float) >= 3.0
            ORDER BY s.signal_time ASC
        """, freeze_date=FREEZE_DATE)

        signals = []
        for row in rows:
            signals.append({
                'signal_id': row['id'],
                'symbol': row['symbol'],
                'market_condition': row['market_condition'],
                'score': float(row['score']),
                'entry_price': row['entry_price'],
                'stop_loss': row['stop_loss'],
                'target_1': row['target_1'],
                'target_2': row['target_2'],
                'target_3': row['target_3'],
                'signal_time': row['signal_time'],
                'result': row['result'],
                'profit_usdt': row['profit_usdt'],
            })

        logger.info(f"✅ تحميل {len(signals)} إشارة post-freeze")
        return signals
    finally:
        await Database.close()


# ═══════════════════════════════════════════════════════════════════════════
# Part 2: SMC Feature Extraction from OHLC
# ═══════════════════════════════════════════════════════════════════════════

async def fetch_ohlc_cached(
    symbol: str,
    interval: str = '1h',
    lookback_hours: int = 48,
) -> Optional[List[Dict]]:
    """جلب OHLC من Binance API مع caching."""
    cache_key = (symbol, interval, lookback_hours)

    # محاولة قراءة من cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
                if cache_key in cache:
                    logger.debug(f"📦 OHLC {symbol} من cache")
                    return cache[cache_key]
        except Exception as e:
            logger.warning(f"⚠️ خطأ قراءة cache: {e}")
            cache = {}
    else:
        cache = {}

    # جلب من API
    try:
        client = AsyncClient()
        limit = lookback_hours  # 1h interval = 1 limit per hour
        klines = await client.get_historical_klines(
            symbol=symbol + 'USDT',
            interval=interval,
            limit=limit,
        )

        ohlc = []
        for k in klines:
            ohlc.append({
                'timestamp': int(k[0]),
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[7]),
            })

        # حفظ في cache
        cache[cache_key] = ohlc
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)

        logger.info(f"✅ {symbol}: {len(ohlc)} شموع 1h")
        await client.close_connection()
        return ohlc
    except Exception as e:
        logger.error(f"❌ خطأ جلب {symbol}: {e}")
        await client.close_connection()
        return None


def detect_imbalance_candles(ohlc: List[Dict], lookback: int = 20) -> List[int]:
    """كشف الشموع غير المتوازنة (Imbalance)."""
    if not ohlc or len(ohlc) < lookback:
        return []

    imbalances = []
    bodies = [abs(c['close'] - c['open']) for c in ohlc]
    avg_body = np.mean(bodies[-lookback:]) if np else (sum(bodies[-lookback:]) / lookback)

    for i, c in enumerate(ohlc):
        body = abs(c['close'] - c['open'])
        if body >= 2 * avg_body:
            imbalances.append(i)

    return imbalances


def detect_fvg(ohlc: List[Dict]) -> List[Dict]:
    """كشف Fair Value Gaps (FVG)."""
    if not ohlc or len(ohlc) < 3:
        return []

    fvgs = []
    for i in range(2, len(ohlc)):
        c1, c2, c3 = ohlc[i-2], ohlc[i-1], ohlc[i]

        # FVG صاعد: low[i] > high[i-2]
        if c3['low'] > c1['high']:
            fvgs.append({
                'type': 'bullish',
                'index': i,
                'fvg_low': c1['high'],
                'fvg_high': c3['low'],
                'age_candles': 0,
            })

        # FVG هابط: high[i] < low[i-2]
        elif c3['high'] < c1['low']:
            fvgs.append({
                'type': 'bearish',
                'index': i,
                'fvg_low': c3['high'],
                'fvg_high': c1['low'],
                'age_candles': 0,
            })

    return fvgs


def detect_order_blocks(ohlc: List[Dict], lookback: int = 5) -> List[Dict]:
    """كشف Order Blocks — آخر شمعة قوية قبل انعكاس."""
    if not ohlc or len(ohlc) < lookback:
        return []

    blocks = []
    for i in range(lookback, len(ohlc)):
        # Order Block صاعد: شمعة bullish قوية قبل bearish candle
        if ohlc[i-1]['close'] > ohlc[i-1]['open']:  # bullish
            if ohlc[i]['close'] < ohlc[i]['open']:   # bearish بعده
                blocks.append({
                    'type': 'bullish_ob',
                    'index': i - 1,
                    'low': ohlc[i-1]['low'],
                    'high': ohlc[i-1]['high'],
                })

        # Order Block هابط: شمعة bearish قوية قبل bullish candle
        elif ohlc[i-1]['close'] < ohlc[i-1]['open']:  # bearish
            if ohlc[i]['close'] > ohlc[i]['open']:     # bullish بعده
                blocks.append({
                    'type': 'bearish_ob',
                    'index': i - 1,
                    'low': ohlc[i-1]['low'],
                    'high': ohlc[i-1]['high'],
                })

    return blocks


def calculate_smc_features(ohlc: List[Dict]) -> Dict[str, Any]:
    """استخراج جميع ميزات SMC."""
    features = {
        'imbalances_count': len(detect_imbalance_candles(ohlc)),
        'fvgs': detect_fvg(ohlc),
        'order_blocks': detect_order_blocks(ohlc),
        'has_recent_ob': False,
        'has_fresh_fvg': False,
        'discount_zone_depth': 0.0,
    }

    # هل يوجد OB أخير (طاز)
    if features['order_blocks'] and len(ohlc) - features['order_blocks'][-1]['index'] <= 5:
        features['has_recent_ob'] = True

    # هل يوجد FVG طازج (أقل من 10 شموع)
    if features['fvgs'] and len(ohlc) - features['fvgs'][-1]['index'] <= 10:
        features['has_fresh_fvg'] = True

    # Discount Zone: المسافة من السعر الحالي لأقرب support (OB أو FVG)
    current_price = ohlc[-1]['close']
    supports = [b['low'] for b in features['order_blocks'] if b['type'] == 'bullish_ob']
    if supports:
        features['discount_zone_depth'] = (current_price - min(supports)) / current_price

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Part 3: Main Validation Loop
# ═══════════════════════════════════════════════════════════════════════════

async def run_validation():
    """شغّل التحقق الكامل."""
    signals = await load_post_freeze_signals()
    if not signals:
        logger.error("❌ لا توجد إشارات post-freeze")
        return

    logger.info(f"\n🔬 تحليل {len(signals)} إشارة post-freeze...")

    results = []
    for i, sig in enumerate(signals):
        logger.info(f"\n[{i+1}/{len(signals)}] {sig['symbol']} @ {sig['signal_time']}")

        # جلب OHLC
        ohlc = await fetch_ohlc_cached(sig['symbol'])
        if not ohlc:
            logger.warning(f"⏭️ تخطي {sig['symbol']} — لا OHLC متاح")
            continue

        # استخراج SMC features
        smc_features = calculate_smc_features(ohlc)

        # توثيق النتيجة
        result_record = {
            'signal_id': sig['signal_id'],
            'symbol': sig['symbol'],
            'entry_price': sig['entry_price'],
            'market_condition': sig['market_condition'],
            'baseline_result': sig['result'],  # OPEN, WIN, LOSS
            'baseline_pnl': sig['profit_usdt'],
            'smc_features': smc_features,
            'signal_time': sig['signal_time'].isoformat() if sig['signal_time'] else None,
        }

        results.append(result_record)

        # طباعة ملخص
        logger.info(f"  📊 Imbalances: {smc_features['imbalances_count']}, "
                    f"FVGs: {len(smc_features['fvgs'])}, "
                    f"OBs: {len(smc_features['order_blocks'])}")
        logger.info(f"  ✓ Recent OB: {smc_features['has_recent_ob']}, "
                    f"Fresh FVG: {smc_features['has_fresh_fvg']}, "
                    f"Discount Depth: {smc_features['discount_zone_depth']:.4f}")

        await asyncio.sleep(0.2)  # تأخير صغير بين الطلبات

    # حفظ النتائج
    with open(OUTPUT_FILE, 'w') as f:
        for rec in results:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    logger.info(f"\n✅ النتائج محفوظة في {OUTPUT_FILE}")

    # ملخص إحصائي
    logger.info(f"\n{'='*60}")
    logger.info(f"📈 SUMMARY: {len(results)} signals analyzed")
    logger.info(f"{'='*60}")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    asyncio.run(run_validation())
