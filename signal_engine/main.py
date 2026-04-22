"""
Signal Engine - يقرر أي العملات تستحق إشارة
بناءً على النقاط والتأكيدات المتعددة من Timeframes مختلفة
"""
import asyncio
import json
import sys
sys.path.append('/app')

from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
from signal_logic import SignalEngine

logger = setup_logger('signal_engine')

async def main():
    logger.info("🚀 بدء تشغيل Signal Engine...")

    await Database.connect()

    engine = SignalEngine()

    # اطبع العتبات الحيّة من DB بدل قيم الـ env الافتراضية
    live_score, live_tf = await engine._get_live_thresholds()
    logger.info(
        f"📊 Timeframes: {', '.join(config.TIMEFRAMES)} | "
        f"تأكيد مطلوب: {live_tf} | الحد الأدنى للنقاط: {live_score}"
    )

    # تأكد من وجود عمود timeframe في الجدول
    await Database.execute("""
        ALTER TABLE analysis_results
        ADD COLUMN IF NOT EXISTS timeframe VARCHAR(10) DEFAULT '4h'
    """)

    try:
        while True:
            try:
                # جلب نتائج التحليل لجميع الـ Timeframes
                # مستثنى: العملات المرفوضة + العملات التي لديها صفقة مفتوحة
                results = await Database.fetch("""
                    SELECT symbol, timeframe, analysis_data FROM analysis_results
                    WHERE signal_generated = false
                    AND analyzed_at > NOW() - INTERVAL '30 minutes'
                    AND symbol NOT IN (
                        SELECT symbol FROM active_trades WHERE status = 'open'
                    )
                    AND symbol NOT IN (
                        SELECT symbol FROM approval_requests WHERE status = 'rejected'
                    )
                    ORDER BY symbol, (analysis_data->>'total_score')::float DESC
                    LIMIT 200
                """)

                if not results:
                    await asyncio.sleep(30)
                    continue

                # إيجاد أفضل فرصة مع تأكيد متعدد الـ Timeframes
                best_signal = await engine.find_best_signal(results)

                if best_signal:
                    tfs = ', '.join(best_signal.get('confirmed_timeframes', []))
                    logger.info(
                        f"🎯 إشارة: {best_signal['symbol']} | "
                        f"نقاط: {best_signal['total_score']}/10 | "
                        f"تأكيد: {tfs}"
                    )

                    # حفظ الإشارة في قاعدة البيانات
                    signal_id = await engine.save_signal(best_signal)

                    # تحديث حالة التحليل لجميع الـ Timeframes لهذه العملة
                    await Database.execute(
                        "UPDATE analysis_results SET signal_generated = true WHERE symbol = $1",
                        best_signal['symbol']
                    )

                    logger.info(f"✅ تم حفظ الإشارة بـ ID: {signal_id}")

                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"❌ خطأ في Signal Engine: {e}")
                await asyncio.sleep(30)

    finally:
        await Database.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
