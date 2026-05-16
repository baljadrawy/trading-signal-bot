"""
الباكتيستر — الجزء الثاني: محاكاة الصفقة بالستوب الديناميكي
==============================================================
يأخذ نتائج الجزء الأول (backtest_results_part1.jsonl)
ويحاكي ماذا كان سيحدث لكل صفقة على الشموع اللاحقة.
منطق الصفقة مطابق تماماً لـ trade_tracker/main.py:
  - SL الأصلي قبل T1
  - بعد T1 → break-even (stop = entry)
  - بعد T2 → trailing stop 2.5% تحت القمة (أرضيته T1)
  - T3 → إغلاق فوري
  - 24h عند T1 فقط → إغلاق بالسعر الحالي
  - 48h بلا نتيجة → إغلاق بالسعر الحالي
مقيّد بالذاكرة: عملة-عملة streaming، ≤2.2GB RAM.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

sys.path.append('/app')

from binance import AsyncClient
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('backtester.part2')

# إعدادات الصفقة — مطابقة تماماً لـ trade_tracker
TRAIL_STOP_PCT   = 2.5    # % trailing stop تحت القمة (بعد T2)
TRADE_EXPIRY_H   = 48     # ساعة إغلاق إجباري
T1_EXPIRY_H      = 24     # ساعة إغلاق عند توقف عند T1
TRADE_AMOUNT     = 50.0   # USDT لكل صفقة (TRADE_AMOUNT_USDT)
MIN_SCORE        = 3.0    # حد النقاط الأدنى لتفعيل إشارة محاكاة
CANDLES_FUTURE   = 200    # شموع مستقبلية للمحاكاة (200 × 1h = ~8 أيام)
TIMEFRAME        = '1h'

INPUT_FILE  = '/app/backtest_results_part1.jsonl'
OUTPUT_FILE = '/app/backtest_results_part2.jsonl'


def simulate_trade(
    entry: float,
    t1: float, t2: float, t3: float,
    stop: float,
    future_candles: List[Dict],  # قائمة {'h': high, 'l': low, 'c': close, 'ts': timestamp_iso}
) -> Dict:
    """
    يحاكي صفقة واحدة على الشموع المستقبلية.
    يعيد dict بنتيجة الصفقة.
    """
    # حماية: إذا كانت الأهداف أو الـ SL خاطئة → رفض
    if t1 <= entry or t2 <= entry or t3 <= entry or stop >= entry:
        return {
            'result': 'INVALID',
            'profit_pct': 0.0,
            'profit_usdt': 0.0,
            'duration_h': 0.0,
            'exit_reason': 'invalid_levels',
            'target_reached': 0,
            'stop_hit': False,
        }

    highest_target = 0
    peak           = entry
    effective_stop = stop
    hours_open     = 0.0
    candle_h_prev  = None  # للمرور شمعة شمعة

    for candle in future_candles:
        high  = candle['h']
        low   = candle['l']
        close = candle['c']
        hours_open += 1.0  # كل شمعة 1h

        # تحديث القمة
        peak = max(peak, high)

        # فحص الأهداف (وفق أعلى سعر الشمعة)
        if high >= t3:
            highest_target = 3
        elif high >= t2 and highest_target < 2:
            highest_target = 2
        elif high >= t1 and highest_target < 1:
            highest_target = 1

        # تحديث الستوب الديناميكي
        if highest_target >= 2:
            trail          = peak * (1 - TRAIL_STOP_PCT / 100)
            effective_stop = max(t1, trail)
        elif highest_target >= 1:
            effective_stop = entry  # break-even
        else:
            effective_stop = stop   # SL الأصلي

        # فحص إغلاق T3
        if high >= t3:
            profit_pct = ((t3 - entry) / entry) * 100
            return {
                'result': 'WIN',
                'profit_pct': round(profit_pct, 4),
                'profit_usdt': round((profit_pct / 100) * TRADE_AMOUNT, 4),
                'duration_h': round(hours_open, 2),
                'exit_reason': 'T3',
                'target_reached': 3,
                'stop_hit': False,
            }

        # فحص ضرب الستوب (وفق أدنى سعر الشمعة)
        if low <= effective_stop:
            exit_price = effective_stop
            pnl_pct    = ((exit_price - entry) / entry) * 100
            is_win     = exit_price > entry
            return {
                'result': 'WIN' if is_win else 'LOSS',
                'profit_pct': round(pnl_pct, 4),
                'profit_usdt': round((pnl_pct / 100) * TRADE_AMOUNT, 4),
                'duration_h': round(hours_open, 2),
                'exit_reason': (
                    'break_even' if highest_target == 1
                    else 'trailing_stop' if highest_target >= 2
                    else 'stop_loss'
                ),
                'target_reached': highest_target,
                'stop_hit': not is_win,
            }

        # إغلاق بعد 24h عند T1 فقط
        if hours_open >= T1_EXPIRY_H and highest_target == 1:
            pnl_pct = ((close - entry) / entry) * 100
            is_win  = close > entry
            return {
                'result': 'WIN' if is_win else 'LOSS',
                'profit_pct': round(pnl_pct, 4),
                'profit_usdt': round((pnl_pct / 100) * TRADE_AMOUNT, 4),
                'duration_h': round(hours_open, 2),
                'exit_reason': 'T1_expired_24h',
                'target_reached': highest_target,
                'stop_hit': False,
            }

        # انتهاء الصلاحية
        if hours_open >= TRADE_EXPIRY_H:
            pnl_pct = ((close - entry) / entry) * 100
            is_win  = close > entry
            return {
                'result': 'WIN' if is_win else 'LOSS',
                'profit_pct': round(pnl_pct, 4),
                'profit_usdt': round((pnl_pct / 100) * TRADE_AMOUNT, 4),
                'duration_h': round(hours_open, 2),
                'exit_reason': f'expired_{TRADE_EXPIRY_H}h',
                'target_reached': highest_target,
                'stop_hit': False,
            }

    # انتهت الشموع المتاحة بدون إغلاق
    pnl_pct = ((future_candles[-1]['c'] - entry) / entry) * 100 if future_candles else 0
    is_win  = pnl_pct > 0
    return {
        'result': 'WIN' if is_win else 'LOSS',
        'profit_pct': round(pnl_pct, 4),
        'profit_usdt': round((pnl_pct / 100) * TRADE_AMOUNT, 4),
        'duration_h': round(hours_open, 2),
        'exit_reason': 'end_of_data',
        'target_reached': highest_target,
        'stop_hit': False,
    }


async def fetch_future_candles(
    client: AsyncClient,
    symbol: str,
    start_time_iso: str,
    limit: int = CANDLES_FUTURE,
) -> List[Dict]:
    """
    يجلب الشموع اللاحقة لوقت الإشارة للمحاكاة.
    """
    try:
        # تحويل ISO إلى timestamp ms
        dt = datetime.fromisoformat(start_time_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        start_ms = int(dt.timestamp() * 1000)

        klines = await client.get_klines(
            symbol=symbol,
            interval=TIMEFRAME,
            startTime=start_ms,
            limit=limit,
        )
        return [
            {
                'h': float(k[2]),
                'l': float(k[3]),
                'c': float(k[4]),
                'ts': k[0],
            }
            for k in klines
        ]
    except Exception as e:
        logger.warning(f"{symbol} @ {start_time_iso}: خطأ في جلب الشموع: {e}")
        return []


async def run_part2():
    """نقطة الدخول الرئيسية للجزء الثاني"""
    logger.info("=" * 60)
    logger.info("الباكتيستر — الجزء الثاني: محاكاة الصفقات")
    logger.info("=" * 60)

    if not os.path.exists(INPUT_FILE):
        logger.error(f"ملف الجزء الأول غير موجود: {INPUT_FILE}")
        logger.error("شغّل backtest_part1.py أولاً")
        return

    await Database.connect()

    try:
        client = await AsyncClient.create(
            api_key=config.BINANCE_API_KEY,
            api_secret=config.BINANCE_API_SECRET,
        )

        # قراءة إشارات الجزء الأول ذات النقاط الكافية
        candidates = []
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                d = json.loads(line.strip())
                score = d.get('total_score', 0)
                # فلاتر مطابقة للـ signal_engine
                if score < MIN_SCORE:
                    continue
                if not d.get('trend_ok', False):
                    continue
                if d.get('market_condition') in ('bullish', 'strong_bullish', 'volatile'):
                    continue
                entry = d.get('entry_price', 0)
                t1    = d.get('target_1', 0)
                stop  = d.get('stop_loss', 0)
                if not entry or not t1 or not stop:
                    continue
                if t1 <= entry or stop >= entry:
                    continue
                candidates.append(d)

        logger.info(f"إشارات مؤهلة من الجزء الأول: {len(candidates)} (score>={MIN_SCORE}, trend_ok, بدون bullish/volatile)")

        if not candidates:
            logger.warning("لا توجد إشارات مؤهلة — راجع معايير الفلترة أو شغّل الجزء الأول على عينة أكبر")
            return

        total_sims = 0
        wins = losses = invalids = 0
        total_pnl = 0.0
        exit_reason_counts: Dict[str, int] = {}

        with open(OUTPUT_FILE, 'w', encoding='utf-8') as fout:
            for i, sig in enumerate(candidates, 1):
                symbol    = sig['symbol']
                eval_time = sig['eval_time']
                entry     = float(sig['entry_price'])
                t1        = float(sig['target_1'])
                t2        = float(sig['target_2'])
                t3        = float(sig['target_3'])
                stop      = float(sig['stop_loss'])

                logger.info(f"[{i}/{len(candidates)}] محاكاة {symbol} @ {eval_time} (score={sig['total_score']:.2f})")

                # جلب الشموع اللاحقة
                future = await fetch_future_candles(client, symbol, eval_time)

                if not future:
                    logger.warning(f"  {symbol}: لا شموع مستقبلية — تخطي")
                    continue

                # تشغيل المحاكاة
                result = simulate_trade(entry, t1, t2, t3, stop, future)

                if result['result'] == 'INVALID':
                    invalids += 1
                    continue

                # دمج مع بيانات الإشارة
                record = {
                    **sig,
                    'sim_result':       result['result'],
                    'sim_profit_pct':   result['profit_pct'],
                    'sim_profit_usdt':  result['profit_usdt'],
                    'sim_duration_h':   result['duration_h'],
                    'sim_exit_reason':  result['exit_reason'],
                    'sim_target_reached': result['target_reached'],
                    'sim_stop_hit':     result['stop_hit'],
                    'future_candles_used': len(future),
                }

                fout.write(json.dumps(record, ensure_ascii=False) + '\n')
                fout.flush()

                # إحصاءات
                if result['result'] == 'WIN':
                    wins += 1
                else:
                    losses += 1
                total_pnl += result['profit_usdt']
                total_sims += 1
                reason = result['exit_reason']
                exit_reason_counts[reason] = exit_reason_counts.get(reason, 0) + 1

                # استراحة لتجنب rate-limit
                await asyncio.sleep(0.3)

        # ملخص نهائي
        logger.info("\n" + "=" * 60)
        logger.info(f"الجزء الثاني — ملخص المحاكاة ({total_sims} صفقة):")
        logger.info("=" * 60)
        if total_sims > 0:
            wr = wins / total_sims * 100
            avg_win  = (total_pnl + sum(
                r['sim_profit_usdt'] for r in []  # placeholder
            )) / wins if wins > 0 else 0
            logger.info(f"  WR: {wr:.1f}% ({wins}W / {losses}L)")
            logger.info(f"  صافي PnL: {total_pnl:+.2f} USDT")
            logger.info(f"  متوسط ربح الصفقة: {total_pnl/total_sims:+.2f} USDT")
            logger.info(f"  إشارات غير صالحة (مرفوضة): {invalids}")
            logger.info(f"  أسباب الإغلاق:")
            for reason, cnt in sorted(exit_reason_counts.items(), key=lambda x: -x[1]):
                logger.info(f"    {reason}: {cnt} ({cnt/total_sims*100:.1f}%)")
        logger.info(f"النتائج محفوظة في: {OUTPUT_FILE}")

    finally:
        try:
            await client.close_connection()
        except Exception:
            pass
        await Database.disconnect()


if __name__ == '__main__':
    asyncio.run(run_part2())
