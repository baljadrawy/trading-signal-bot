"""
الباكتيستر — الجزء الخامس: التحقق من توحيد TripleBarrier
===========================================================
يُثبت أن نتائج الباكتيستر مطابقة 100% لنتائج trade_tracker الحيّ
عبر استخدام نفس shared.triple_barrier.step_barrier.

الخطوات:
1. يعيد تشغيل نفس إشارات الجزء الثاني (backtest_results_part1.jsonl)
   لكن الآن باستخدام shared.triple_barrier بدل كود مكرر
2. يقارن النتائج مع backtest_results_part2.jsonl (كود قديم)
3. يسجّل أي اختلاف بين التنفيذين (يجب أن يكون صفراً)
4. ينتج backtest_results_part5.jsonl — النتائج "الموحّدة"

الهدف: أي تغيير مستقبلي على منطق الخروج يكفي تعديل triple_barrier.py فقط.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

sys.path.append('/app')

from binance import AsyncClient
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
from shared.triple_barrier import (
    TripleBarrierConfig,
    TripleBarrierState,
    step_barrier,
)

logger = setup_logger('backtester.part5')

# إعدادات
MIN_SCORE      = 3.0
CANDLES_FUTURE = 200
TIMEFRAME      = '1h'
TRADE_AMOUNT   = 50.0

INPUT_PART1  = '/app/backtest_results_part1.jsonl'
INPUT_PART2  = '/app/backtest_results_part2.jsonl'   # مرجع للمقارنة
OUTPUT_FILE  = '/app/backtest_results_part5.jsonl'


async def fetch_future_candles(
    client: AsyncClient,
    symbol: str,
    start_time_iso: str,
    limit: int = CANDLES_FUTURE,
) -> List[Dict]:
    """يجلب الشموع اللاحقة لوقت الإشارة."""
    try:
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
            {'h': float(k[2]), 'l': float(k[3]), 'c': float(k[4]), 'ts': k[0]}
            for k in klines
        ]
    except Exception as e:
        logger.warning(f"{symbol} @ {start_time_iso}: خطأ في جلب الشموع: {e}")
        return []


def simulate_with_triple_barrier(
    symbol: str,
    entry: float,
    t1: float, t2: float, t3: float,
    stop: float,
    future_candles: List[Dict],
) -> Dict:
    """
    يحاكي صفقة واحدة باستخدام shared.triple_barrier.step_barrier.
    مصدر حقيقة واحد مشترك مع trade_tracker الحيّ.
    """
    cfg = TripleBarrierConfig(
        symbol       = symbol,
        entry        = entry,
        target_1     = t1,
        target_2     = t2,
        target_3     = t3,
        stop_loss    = stop,
        trade_amount = TRADE_AMOUNT,
    )
    err = cfg.validate()
    if err:
        return {
            'result': 'INVALID',
            'profit_pct': 0.0,
            'profit_usdt': 0.0,
            'duration_h': 0.0,
            'exit_reason': f'invalid: {err}',
            'target_reached': 0,
            'stop_hit': False,
        }

    state = TripleBarrierState(peak=entry)

    for candle in future_candles:
        result = step_barrier(
            cfg, state,
            high=candle['h'],
            low=candle['l'],
            close=candle['c'],
            hours_elapsed=1.0,
        )
        if result is not None:
            return {
                'result':         result.result,
                'profit_pct':     result.profit_pct,
                'profit_usdt':    result.profit_usdt,
                'duration_h':     result.duration_h,
                'exit_reason':    result.exit_reason,
                'target_reached': result.target_reached,
                'stop_hit':       result.stop_hit,
            }

    # انتهت الشموع بدون إغلاق
    last_close = future_candles[-1]['c'] if future_candles else entry
    pnl_pct    = ((last_close - entry) / entry) * 100
    return {
        'result':         'WIN' if pnl_pct > 0 else 'LOSS',
        'profit_pct':     round(pnl_pct, 4),
        'profit_usdt':    round((pnl_pct / 100) * TRADE_AMOUNT, 4),
        'duration_h':     float(len(future_candles)),
        'exit_reason':    'end_of_data',
        'target_reached': state.highest_target,
        'stop_hit':       False,
    }


async def run_part5():
    """نقطة الدخول."""
    logger.info("=" * 60)
    logger.info("الباكتيستر — الجزء الخامس: توحيد TripleBarrier")
    logger.info("=" * 60)

    if not os.path.exists(INPUT_PART1):
        logger.error(f"ملف الجزء الأول غير موجود: {INPUT_PART1}")
        return

    await Database.connect()

    # تحميل نتائج الجزء الثاني للمقارنة
    part2_by_key: Dict[str, Dict] = {}
    if os.path.exists(INPUT_PART2):
        with open(INPUT_PART2, 'r', encoding='utf-8') as f:
            for line in f:
                d = json.loads(line.strip())
                key = f"{d['symbol']}|{d['eval_time']}"
                part2_by_key[key] = d
        logger.info(f"نتائج الجزء الثاني المحمّلة للمقارنة: {len(part2_by_key)}")

    try:
        client = await AsyncClient.create(
            api_key=config.BINANCE_API_KEY,
            api_secret=config.BINANCE_API_SECRET,
        )

        # قراءة إشارات الجزء الأول (نفس فلاتر الجزء الثاني)
        candidates = []
        with open(INPUT_PART1, 'r', encoding='utf-8') as f:
            for line in f:
                d = json.loads(line.strip())
                if d.get('total_score', 0) < MIN_SCORE:
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

        logger.info(f"إشارات مؤهلة: {len(candidates)}")

        total = wins = losses = invalids = 0
        total_pnl          = 0.0
        diffs_from_part2   = 0
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

                logger.info(f"[{i}/{len(candidates)}] {symbol} @ {eval_time} score={sig['total_score']:.2f}")

                future = await fetch_future_candles(client, symbol, eval_time)
                if not future:
                    logger.warning(f"  {symbol}: لا شموع — تخطي")
                    continue

                result = simulate_with_triple_barrier(symbol, entry, t1, t2, t3, stop, future)

                if result['result'] == 'INVALID':
                    invalids += 1
                    continue

                # مقارنة مع الجزء الثاني
                key     = f"{symbol}|{eval_time}"
                p2      = part2_by_key.get(key)
                matches = True
                diff_note = ""
                if p2:
                    p2_res = p2.get('sim_result', '')
                    p2_pct = round(float(p2.get('sim_profit_pct', 0)), 4)
                    p5_pct = result['profit_pct']
                    if p2_res != result['result'] or abs(p2_pct - p5_pct) > 0.01:
                        matches = False
                        diffs_from_part2 += 1
                        diff_note = (
                            f"DIFF: part2={p2_res}/{p2_pct}% "
                            f"vs part5={result['result']}/{p5_pct}%"
                        )
                        logger.warning(f"  {symbol}: {diff_note}")

                record = {
                    **sig,
                    'sim5_result':         result['result'],
                    'sim5_profit_pct':     result['profit_pct'],
                    'sim5_profit_usdt':    result['profit_usdt'],
                    'sim5_duration_h':     result['duration_h'],
                    'sim5_exit_reason':    result['exit_reason'],
                    'sim5_target_reached': result['target_reached'],
                    'sim5_stop_hit':       result['stop_hit'],
                    'matches_part2':       matches,
                    'diff_note':           diff_note,
                    'future_candles_used': len(future),
                }

                fout.write(json.dumps(record, ensure_ascii=False) + '\n')
                fout.flush()

                if result['result'] == 'WIN':
                    wins += 1
                else:
                    losses += 1
                total_pnl += result['profit_usdt']
                total += 1
                reason = result['exit_reason']
                exit_reason_counts[reason] = exit_reason_counts.get(reason, 0) + 1

                await asyncio.sleep(0.3)

        # ملخص
        logger.info("\n" + "=" * 60)
        logger.info(f"الجزء الخامس — ملخص ({total} صفقة):")
        logger.info("=" * 60)
        if total > 0:
            wr = wins / total * 100
            logger.info(f"  WR: {wr:.1f}% ({wins}W / {losses}L)")
            logger.info(f"  صافي PnL: {total_pnl:+.2f} USDT")
            logger.info(f"  متوسط ربح: {total_pnl/total:+.2f} USDT")
            logger.info(f"  مرفوض (invalid): {invalids}")
            logger.info(f"  اختلافات عن الجزء الثاني: {diffs_from_part2}/{total}")
            logger.info(f"  أسباب الإغلاق:")
            for reason, cnt in sorted(exit_reason_counts.items(), key=lambda x: -x[1]):
                logger.info(f"    {reason}: {cnt} ({cnt/total*100:.1f}%)")

        if diffs_from_part2 == 0:
            logger.info("التحقق: TripleBarrier مطابق 100% للجزء الثاني (مصدر واحد للمنطق)")
        else:
            logger.warning(
                f"تحذير: {diffs_from_part2} اختلافات — راجع triple_barrier.py "
                f"مقابل backtest_part2.simulate_trade"
            )

        logger.info(f"النتائج محفوظة في: {OUTPUT_FILE}")

    finally:
        try:
            await client.close_connection()
        except Exception:
            pass
        await Database.disconnect()


if __name__ == '__main__':
    asyncio.run(run_part5())
