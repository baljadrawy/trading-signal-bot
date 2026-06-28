"""
Signal Engine - يقرر أي العملات تستحق إشارة
بناءً على النقاط والتأكيدات المتعددة من Timeframes مختلفة
"""
import asyncio
import json
import sys
import time
sys.path.append('/app')

from binance import AsyncClient
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
from shared.alerts import send_alert
from shared.retry_utils import format_error, is_network_error, compute_backoff, alert_threshold
from shared.macro_context import MacroContext
from signal_logic import SignalEngine

logger = setup_logger('signal_engine')

async def main():
    logger.info("🚀 بدء تشغيل Signal Engine...")

    await Database.connect()

    # MacroContext only calls public klines (BTC/ETH 4h) — no auth needed.
    # Using empty keys avoids exposing live trading credentials to this container.
    client = await AsyncClient.create('', '')
    macro_ctx = MacroContext(client)

    engine = SignalEngine()

    # Evidence flight-recorder: start the async flusher ONLY when enabled (guarded; any
    # failure is buried and the engine continues unaffected).
    if config.ENABLE_EVIDENCE_RECORDER:
        try:
            from signal_logic import get_evidence_recorder
            _rec = get_evidence_recorder()
            if _rec is not None:
                asyncio.create_task(_rec.run_flusher())
                logger.info("🛫 Evidence flight-recorder ON (shadow; async flush)")
        except Exception:
            logger.warning("evidence flusher start failed; continuing without it", exc_info=True)

    # اطبع العتبات الحيّة من DB بدل قيم الـ env الافتراضية
    live_score, live_tf = await engine._get_live_thresholds()
    logger.info(
        f"📊 Timeframes: {', '.join(config.TIMEFRAMES)} | "
        f"تأكيد مطلوب: {live_tf} | الحد الأدنى للنقاط: {live_score} | "
        f"LIVE_LEARNING_MODE: {config.LIVE_LEARNING_MODE}"
    )

    # تأكد من وجود عمود timeframe في الجدول
    await Database.execute("""
        ALTER TABLE analysis_results
        ADD COLUMN IF NOT EXISTS timeframe VARCHAR(10) DEFAULT '4h'
    """)

    consecutive_errors = 0
    _last_heartbeat = 0.0  # لوج دوري كل 10 دقائق

    try:
        while True:
            try:
                # جلب نتائج التحليل لجميع الـ Timeframes
                # مستثنى: العملات المرفوضة + العملات التي لديها صفقة مفتوحة
                # ملاحظة: استثناء approval_requests المرفوضة حُذف من هنا —
                # كل العملات المرفوضة مُضافة لـ symbol_blacklist ومحظورة من Scanner.
                results = await Database.fetch("""
                    SELECT symbol, timeframe, analysis_data FROM analysis_results
                    WHERE signal_generated = false
                    AND analyzed_at > NOW() - INTERVAL '30 minutes'
                    AND symbol NOT IN (
                        SELECT symbol FROM active_trades WHERE status = 'open'
                    )
                    ORDER BY symbol, (analysis_data->>'total_score')::float DESC
                    LIMIT 200
                """)

                consecutive_errors = 0

                if not results:
                    now = time.time()
                    if now - _last_heartbeat >= 600:  # كل 10 دقائق
                        logger.info("💤 لا نتائج تحليل طازجة — البوت ينتظر")
                        _last_heartbeat = now
                    await asyncio.sleep(30)
                    continue

                # إيجاد أفضل فرصة مع تأكيد متعدد الـ Timeframes
                if config.LIVE_LEARNING_MODE:
                    best_signal = await engine.find_best_signal_live(results, macro_ctx)
                else:
                    best_signal = await engine.find_best_signal(results)

                # لوج دوري كل 10 دقائق حتى لو لا توجد إشارة
                now = time.time()
                if now - _last_heartbeat >= 600:
                    def _get_score(row):
                        try:
                            d = row['analysis_data']
                            if isinstance(d, str):
                                import json as _json
                                d = _json.loads(d)
                            return float(d.get('total_score', 0))
                        except Exception:
                            return 0.0
                    top_scores = sorted(
                        [(r['symbol'], _get_score(r)) for r in results],
                        key=lambda x: -x[1]
                    )[:3]
                    top_str = ', '.join(f"{s}({sc:.1f})" for s, sc in top_scores)
                    logger.info(f"💤 لا إشارة — أعلى النقاط: {top_str} | نتائج مفحوصة: {len(results)}")
                    _last_heartbeat = now

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
                consecutive_errors += 1
                network = is_network_error(e)
                wait = compute_backoff(consecutive_errors, network)
                msg = f"❌ خطأ في Signal Engine ({consecutive_errors}): {format_error(e)}"
                if network:
                    logger.warning(msg)
                else:
                    logger.error(msg)
                if consecutive_errors >= alert_threshold(network):
                    await send_alert(
                        f"Signal Engine فشل {consecutive_errors} مرات متتالية\nالخطأ: {format_error(e)[:200]}",
                        level='critical', component='SignalEngine'
                    )
                await asyncio.sleep(wait)

    finally:
        await client.close_connection()
        await Database.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
