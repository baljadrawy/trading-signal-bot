"""
Signal Engine - يقرر أي العملات تستحق إشارة
بناءً على النقاط والتأكيدات المتعددة
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
    
    # إنشاء جدول نتائج التحليل إن لم يوجد
    await Database.execute("""
        CREATE TABLE IF NOT EXISTS analysis_results (
            symbol VARCHAR(20) PRIMARY KEY,
            analysis_data JSONB NOT NULL,
            analyzed_at TIMESTAMP DEFAULT NOW(),
            signal_generated BOOLEAN DEFAULT false
        )
    """)

    try:
        while True:
            try:
                # جلب نتائج التحليل الجديدة
                results = await Database.fetch("""
                    SELECT symbol, analysis_data FROM analysis_results
                    WHERE signal_generated = false
                    AND analyzed_at > NOW() - INTERVAL '30 minutes'
                    ORDER BY (analysis_data->>'total_score')::float DESC
                    LIMIT 20
                """)
                
                if not results:
                    await asyncio.sleep(30)
                    continue

                # إيجاد أفضل فرصة
                best_signal = await engine.find_best_signal(results)
                
                if best_signal:
                    logger.info(f"🎯 إشارة قوية: {best_signal['symbol']} - النقاط: {best_signal['total_score']}/10")
                    
                    # حفظ الإشارة في قاعدة البيانات
                    signal_id = await engine.save_signal(best_signal)
                    
                    # تحديث حالة التحليل
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
