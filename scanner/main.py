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
from shared.alerts import send_alert
from scanner_logic import BinanceScanner

logger = setup_logger('scanner')

async def main():
    logger.info("🚀 بدء تشغيل Scanner...")
    await Database.connect()

    client = await AsyncClient.create(
        api_key=config.BINANCE_API_KEY,
        api_secret=config.BINANCE_API_SECRET
    )

    scanner = BinanceScanner(client)
    consecutive_errors = 0

    try:
        while True:
            try:
                logger.info("🔍 بدء دورة المسح...")
                candidates = await scanner.scan()
                logger.info(f"✅ وجدنا {len(candidates)} عملة مؤهلة للتحليل")
                consecutive_errors = 0  # reset عند النجاح
                await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)

            except Exception as e:
                consecutive_errors += 1
                wait = min(60 * consecutive_errors, 300)  # backoff: 60s, 120s, 180s... max 5 دقائق
                logger.error(f"❌ خطأ في دورة المسح ({consecutive_errors}): {e}")

                if consecutive_errors >= 3:
                    await send_alert(
                        f"Scanner فشل {consecutive_errors} مرات متتالية\nالخطأ: {str(e)[:200]}",
                        level='critical', component='Scanner'
                    )
                await asyncio.sleep(wait)
                
    finally:
        await client.close_connection()
        await Database.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
