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
from shared.health import mark_started, mark_success, mark_failure
from shared.schema import require_schema
from shared.maintenance import maintain_pipeline
from scanner_logic import BinanceScanner
from shared.funnel_flags import funnel_recording_enabled

logger = setup_logger('scanner')

async def main():
    logger.info("🚀 بدء تشغيل Scanner...")
    funnel_on = funnel_recording_enabled()       # WP-B01: unknown FUNNEL_RECORDING refuses to start
    await Database.connect()
    await require_schema('scanner')
    await mark_started('scanner')

    client = await AsyncClient.create(
        api_key=config.BINANCE_API_KEY,
        api_secret=config.BINANCE_API_SECRET
    )

    scanner = BinanceScanner(client)
    tap = None
    ev2_task = None
    if funnel_on:                                # observe-only F0-F2 records (shared/funnel_hooks.py)
        from shared import evidence_v2
        from shared.funnel_hooks import ScannerTap
        tap = ScannerTap(scanner)
        ev2_task = evidence_v2.start_flusher('scanner')
    consecutive_errors = 0

    try:
        while True:
            try:
                logger.info("🔍 بدء دورة المسح...")
                if tap is not None:
                    tap.begin()
                candidates = await scanner.scan()
                if tap is not None:
                    await tap.end(candidates)
                maintenance = await maintain_pipeline()
                logger.info(f"✅ وجدنا {len(candidates)} عملة مؤهلة للتحليل")
                consecutive_errors = 0  # reset عند النجاح
                metadata = {'candidates': len(candidates), 'maintenance': maintenance}
                if tap is not None:
                    metadata['funnel'] = tap.health()
                await mark_success('scanner', metadata)
                await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)

            except Exception as e:
                if tap is not None:
                    await tap.end(error=e)               # no-op when the cycle was already closed
                consecutive_errors += 1
                await mark_failure('scanner', e)
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
        if ev2_task is not None:
            from shared import evidence_v2
            await evidence_v2.stop('scanner', ev2_task)
        await client.close_connection()
        await Database.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
