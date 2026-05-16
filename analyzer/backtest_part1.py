"""
الباكتيستر — الجزء الأول: إعادة التشغيل التاريخية
=====================================================
يُشغَّل كمهمة دفعية داخل حاوية trading_analyzer (بدون حاوية جديدة).
يجلب شموع تاريخية عبر Binance API ويمرّرها عبر نفس كود التنقيط الموجود.
مقيّد بالذاكرة: عملة-عملة (streaming)، ≤2.2GB RAM.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

sys.path.append('/app')

from binance import AsyncClient
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
from technical_analyzer import TechnicalAnalyzer

logger = setup_logger('backtester.part1')

# إعدادات الباكتيستر
TIMEFRAME         = '1h'            # الإطار المدروس (1h هو الأفضل تاريخياً)
CANDLES_COUNT     = 500             # 500 شمعة 1h ≈ 20 يوم (RAM-safe)
MIN_CANDLES       = 200             # حد أدنى للتحليل الموثوق
# المعايير الزمنية: نُنتج إشارات افتراضية كل 24 شمعة (≈ يوم) للتنوع
STEP_CANDLES      = 24

# ملف النتائج — JSON بسيط، عملة-عملة متدفّق
OUTPUT_FILE = '/app/backtest_results_part1.jsonl'


class HistoricalScorer:
    """
    يعيد تشغيل نفس منطق التنقيط الموجود على شموع تاريخية.
    يستورد TechnicalAnalyzer مباشرة — لا يعيد كتابة المنطق.
    """

    def __init__(self, client: AsyncClient):
        self.analyzer = TechnicalAnalyzer(client)

    async def score_symbol_history(
        self,
        symbol: str,
        timeframe: str = TIMEFRAME,
        candles: int = CANDLES_COUNT,
        step: int = STEP_CANDLES,
    ) -> List[Dict]:
        """
        يجلب `candles` شمعة للعملة ويُقيّم كل `step` شمعة.
        يعود بقائمة من نقاط التنقيط مع وقت كل تقييم.
        """
        import pandas as pd

        try:
            # جلب الشموع التاريخية
            klines = await self.analyzer.client.get_klines(
                symbol=symbol,
                interval=timeframe,
                limit=candles,
            )
            if not klines or len(klines) < MIN_CANDLES:
                logger.warning(f"{symbol}: شموع غير كافية ({len(klines) if klines else 0})")
                return []

            # تحويل إلى DataFrame بنفس طريقة TechnicalAnalyzer
            import pandas as pd
            df_full = pd.DataFrame(klines, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume']:
                df_full[col] = pd.to_numeric(df_full[col])
            df_full['open_time'] = pd.to_datetime(df_full['open_time'], unit='ms')
            df_full = df_full.set_index('open_time')

            results = []
            # نُنتج نقطة تقييم كل `step` شمعة، بدءاً من MIN_CANDLES
            eval_points = range(MIN_CANDLES, len(df_full), step)

            for end_idx in eval_points:
                df_slice = df_full.iloc[:end_idx].copy()
                if len(df_slice) < MIN_CANDLES:
                    continue

                # نفس منطق TechnicalAnalyzer
                df_slice = self.analyzer._calculate_indicators(df_slice)
                mc       = self.analyzer._detect_market_condition(df_slice)

                # جلب الأوزان الحيّة من DB (نفس ما يفعله البوت)
                weights  = await self.analyzer._get_indicator_weights(mc)
                scores   = self.analyzer._calculate_scores(df_slice, weights)
                levels   = self.analyzer._calculate_levels(df_slice)

                import pandas as pd_inner
                last_close   = float(df_slice['close'].iloc[-1])
                ema200_val   = df_slice['ema200'].iloc[-1]
                trend_ok     = bool(not pd_inner.isna(ema200_val) and last_close > float(ema200_val))
                eval_time    = df_slice.index[-1].isoformat()

                results.append({
                    'symbol':           symbol,
                    'timeframe':        timeframe,
                    'eval_time':        eval_time,
                    'market_condition': mc,
                    'total_score':      round(scores['total'], 4),
                    'score_details':    scores['details'],
                    'trend_ok':         trend_ok,
                    'entry_price':      levels['entry'],
                    'target_1':         levels['t1'],
                    'target_2':         levels['t2'],
                    'target_3':         levels['t3'],
                    'stop_loss':        levels['stop'],
                })

            logger.info(f"{symbol}: {len(results)} نقطة تقييم تاريخية")
            return results

        except Exception as e:
            logger.error(f"خطأ في {symbol}: {e}")
            return []


async def get_symbols_to_backtest() -> List[str]:
    """
    يجلب العملات الموجودة في trade_results (عملات فعلية تداول البوت بها).
    مُقيّد بـ 30 عملة فقط للحفاظ على الذاكرة.
    """
    rows = await Database.fetch("""
        SELECT DISTINCT symbol FROM trade_results
        WHERE exit_time > NOW() - INTERVAL '30 days'
        ORDER BY symbol
        LIMIT 30
    """)
    return [r['symbol'] for r in rows]


async def run_part1():
    """نقطة الدخول الرئيسية للجزء الأول"""
    logger.info("=" * 60)
    logger.info("الباكتيستر — الجزء الأول: إعادة التشغيل التاريخية")
    logger.info("=" * 60)

    await Database.connect()

    try:
        client = await AsyncClient.create(
            api_key=config.BINANCE_API_KEY,
            api_secret=config.BINANCE_API_SECRET,
        )
        scorer = HistoricalScorer(client)

        symbols = await get_symbols_to_backtest()
        logger.info(f"عدد العملات للاختبار: {len(symbols)}")
        if not symbols:
            logger.error("لا توجد عملات في trade_results — أجري صفقات أولاً")
            return

        total_evals = 0
        

        with open(OUTPUT_FILE, 'w', encoding='utf-8') as fout:
            for i, symbol in enumerate(symbols, 1):
                logger.info(f"[{i}/{len(symbols)}] معالجة {symbol}...")

                evals = await scorer.score_symbol_history(symbol)

                for ev in evals:
                    fout.write(json.dumps(ev, ensure_ascii=False) + '\n')
                    fout.flush()  # متدفّق — حفظ فوري

                total_evals += len(evals)

                # استراحة قصيرة بين العملات لتجنب rate-limit
                await asyncio.sleep(0.3)

        logger.info(f"تم الانتهاء: {total_evals} نقطة تقييم لـ {len(symbols)} عملة")
        logger.info(f"النتائج محفوظة في: {OUTPUT_FILE}")

        # ملخص إحصائي سريع
        await _print_summary(OUTPUT_FILE)

    finally:
        try:
            await client.close_connection()
        except Exception:
            pass
        await Database.disconnect()


async def _print_summary(filepath: str):
    """ملخص إحصائي للنتائج"""
    try:
        from collections import defaultdict
        stats: Dict[str, List] = defaultdict(list)
        total = 0

        with open(filepath, 'r') as f:
            for line in f:
                d = json.loads(line.strip())
                mc = d['market_condition']
                stats[mc].append(d['total_score'])
                total += 1

        logger.info(f"\nملخص الجزء الأول ({total} نقطة تقييم):")
        for mc, scores in sorted(stats.items()):
            avg = sum(scores) / len(scores)
            above_3 = sum(1 for s in scores if s >= 3.0)
            pct = above_3 / len(scores) * 100
            logger.info(
                f"  {mc:12s}: {len(scores):4d} نقطة | "
                f"avg_score={avg:.2f} | score>=3: {above_3} ({pct:.1f}%)"
            )
    except Exception as e:
        logger.warning(f"لم يتمكن من طباعة الملخص: {e}")


if __name__ == '__main__':
    asyncio.run(run_part1())
