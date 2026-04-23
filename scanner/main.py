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
from shared.retry_utils import format_error, is_network_error, compute_backoff, alert_threshold
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
                network = is_network_error(e)
                wait = compute_backoff(consecutive_errors, network)
                msg = f"❌ خطأ في دورة المسح ({consecutive_errors}): {format_error(e)}"
                if network:
                    logger.warning(msg)
                else:
                    logger.error(msg)

                if consecutive_errors >= alert_threshold(network):
                    await send_alert(
                        f"Scanner فشل {consecutive_errors} مرات متتالية\nالخطأ: {format_error(e)[:200]}",
                        level='critical', component='Scanner'
                    )
                await asyncio.sleep(wait)
                
    finally:
        await client.close_connection()
        await Database.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
