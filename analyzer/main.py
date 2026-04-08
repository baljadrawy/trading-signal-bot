"""
Analyzer - يحلل المؤشرات الفنية على عدة Timeframes ويحسب نقاط كل عملة
"""
import asyncio
import json
import sys
sys.path.append('/app')

from binance import AsyncClient
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
from technical_analyzer import TechnicalAnalyzer
from orderbook_analyzer import OrderBookAnalyzer

logger = setup_logger('analyzer')

async def main():
    logger.info("🚀 بدء تشغيل Analyzer...")
    logger.info(f"📊 Timeframes المفعّلة: {', '.join(config.TIMEFRAMES)}")

    await Database.connect()

    # تحديث جدول analysis_results ليدعم timeframe
    await Database.execute("""
        ALTER TABLE analysis_results
        ADD COLUMN IF NOT EXISTS timeframe VARCHAR(10) DEFAULT '4h'
    """)
    await Database.execute("""
        ALTER TABLE analysis_results
        DROP CONSTRAINT IF EXISTS analysis_results_pkey
    """)
    await Database.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'analysis_results_symbol_timeframe_key'
            ) THEN
                ALTER TABLE analysis_results
                ADD CONSTRAINT analysis_results_symbol_timeframe_key
                UNIQUE (symbol, timeframe);
            END IF;
        END $$;
    """)

    client = await AsyncClient.create(
        api_key=config.BINANCE_API_KEY,
        api_secret=config.BINANCE_API_SECRET
    )

    tech_analyzer = TechnicalAnalyzer(client)
    ob_analyzer = OrderBookAnalyzer(client)

    try:
        while True:
            try:
                # جلب المرشحين غير المحللين
                candidates = await Database.fetch(
                    """
                    SELECT id, symbol, data FROM scan_candidates
                    WHERE analyzed = false
                    ORDER BY scan_time DESC
                    LIMIT 50
                    """
                )

                if not candidates:
                    await asyncio.sleep(30)
                    continue

                logger.info(f"🔬 تحليل {len(candidates)} عملة × {len(config.TIMEFRAMES)} timeframes...")

                # تحليل كل عملة على جميع الـ Timeframes
                tasks = [
                    analyze_symbol_all_timeframes(tech_analyzer, ob_analyzer, row)
                    for row in candidates
                ]
                await asyncio.gather(*tasks, return_exceptions=True)

                await asyncio.sleep(10)

            except Exception as e:
                logger.error(f"❌ خطأ في دورة التحليل: {e}")
                await asyncio.sleep(30)

    finally:
        await client.close_connection()
        await Database.disconnect()

async def analyze_symbol_all_timeframes(tech_analyzer, ob_analyzer, row):
    """تحليل عملة واحدة على جميع الـ Timeframes"""
    symbol = row['symbol']
    results = {}

    for tf in config.TIMEFRAMES:
        try:
            tech_result = await tech_analyzer.analyze(symbol, timeframe=tf)
            if not tech_result:
                continue

            # Order Book نجلبه مرة واحدة فقط (نفس لكل الـ timeframes)
            if not results:
                ob_result = await ob_analyzer.analyze(symbol)
            else:
                ob_result = list(results.values())[0].get('order_book')

            combined = {**tech_result, 'order_book': ob_result, 'timeframe': tf}

            await Database.execute(
                """
                INSERT INTO analysis_results (symbol, timeframe, analysis_data, analyzed_at, signal_generated)
                VALUES ($1, $2, $3, NOW(), false)
                ON CONFLICT (symbol, timeframe) DO UPDATE
                SET analysis_data = $3, analyzed_at = NOW(), signal_generated = false
                """,
                symbol, tf, json.dumps(combined)
            )

            results[tf] = combined
            logger.info(f"✅ {symbol} [{tf}] - النقاط: {combined.get('total_score', 0)}/10")

        except Exception as e:
            logger.error(f"❌ خطأ في تحليل {symbol} [{tf}]: {e}")

    # تحديث حالة المرشح بعد تحليل جميع الـ Timeframes
    if results:
        await Database.execute(
            "UPDATE scan_candidates SET analyzed = true WHERE id = $1",
            row['id']
        )

if __name__ == "__main__":
    asyncio.run(main())
