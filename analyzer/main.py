"""
Analyzer - يحلل المؤشرات الفنية ويحسب نقاط كل عملة
"""
import asyncio
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
    
    await Database.connect()
    
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
                
                logger.info(f"🔬 تحليل {len(candidates)} عملة...")
                
                # تحليل كل عملة
                tasks = [
                    analyze_symbol(tech_analyzer, ob_analyzer, row)
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

async def analyze_symbol(tech_analyzer, ob_analyzer, row):
    """تحليل عملة واحدة"""
    try:
        symbol = row['symbol']
        
        # التحليل الفني
        tech_result = await tech_analyzer.analyze(symbol)
        if not tech_result:
            return
            
        # تحليل Order Book
        ob_result = await ob_analyzer.analyze(symbol)
        
        # دمج النتائج
        combined = {**tech_result, 'order_book': ob_result}
        
        # حفظ نتيجة التحليل للـ Signal Engine
        import json
        await Database.execute(
            """
            INSERT INTO analysis_results (symbol, analysis_data, analyzed_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (symbol) DO UPDATE
            SET analysis_data = $2, analyzed_at = NOW()
            """,
            symbol, json.dumps(combined)
        )
        
        # تحديث حالة المرشح
        await Database.execute(
            "UPDATE scan_candidates SET analyzed = true WHERE id = $1",
            row['id']
        )
        
        logger.info(f"✅ {symbol} - النقاط: {combined.get('total_score', 0)}/10")
        
    except Exception as e:
        logger.error(f"❌ خطأ في تحليل {row['symbol']}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
