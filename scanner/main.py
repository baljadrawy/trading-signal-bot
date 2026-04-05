"""
Scanner - يمسح جميع عملات USDT على Binance Spot
ويفلتر العملات المؤهلة للتحليل
"""
import asyncio
import sys
sys.path.append('/app')

from binance import AsyncClient
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
from scanner_logic import BinanceScanner

logger = setup_logger('scanner')

async def main():
    logger.info("🚀 بدء تشغيل Scanner...")
    
    # الاتصال بقاعدة البيانات
    await Database.connect()
    
    # إنشاء عميل Binance
    client = await AsyncClient.create(
        api_key=config.BINANCE_API_KEY,
        api_secret=config.BINANCE_API_SECRET
    )
    
    scanner = BinanceScanner(client)
    
    try:
        while True:
            try:
                logger.info("🔍 بدء دورة المسح...")
                candidates = await scanner.scan()
                logger.info(f"✅ وجدنا {len(candidates)} عملة مؤهلة للتحليل")
                
                # انتظر الدورة التالية
                await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)
                
            except Exception as e:
                logger.error(f"❌ خطأ في دورة المسح: {e}")
                await asyncio.sleep(60)
                
    finally:
        await client.close_connection()
        await Database.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
