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
from shared.alerts import send_alert
from shared.health import mark_started, mark_success, mark_failure
from shared.schema import require_schema
from shared import evidence_v2
from technical_analyzer import TechnicalAnalyzer
from orderbook_analyzer import OrderBookAnalyzer

logger = setup_logger('analyzer')

async def main():
    logger.info("🚀 بدء تشغيل Analyzer...")
    logger.info(f"📊 Timeframes المفعّلة: {', '.join(config.TIMEFRAMES)}")

    await Database.connect()
    await require_schema('analyzer')
    await mark_started('analyzer')

    client = await AsyncClient.create(
        api_key=config.BINANCE_API_KEY,
        api_secret=config.BINANCE_API_SECRET
    )

    tech_analyzer = TechnicalAnalyzer(client)
    ob_analyzer = OrderBookAnalyzer(client)
    ev2_task = evidence_v2.start_flusher('analyzer')   # None unless EVIDENCE_V2_ENABLED

    consecutive_errors = 0

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
                    await mark_success('analyzer', _with_ev2({'candidates': 0, 'status': 'idle'}))
                    await asyncio.sleep(30)
                    continue

                consecutive_errors = 0
                logger.info(f"🔬 تحليل {len(candidates)} عملة × {len(config.TIMEFRAMES)} timeframes...")

                # تحليل كل عملة على جميع الـ Timeframes (timeout 60 ثانية لكل عملة)
                tasks = [
                    asyncio.wait_for(
                        analyze_symbol_all_timeframes(tech_analyzer, ob_analyzer, row),
                        timeout=60
                    )
                    for row in candidates
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, asyncio.TimeoutError):
                        symbol = candidates[i]['symbol']
                        logger.warning(f"⏰ timeout في تحليل {symbol} - تخطي")

                completed = sum(1 for result in results if not isinstance(result, Exception))
                await mark_success('analyzer', _with_ev2({
                    'candidates': len(candidates), 'completed': completed}))

                await asyncio.sleep(10)

            except Exception as e:
                consecutive_errors += 1
                await mark_failure('analyzer', e)
                wait = min(30 * consecutive_errors, 300)
                logger.error(f"❌ خطأ في دورة التحليل ({consecutive_errors}): {e}")
                if consecutive_errors >= 3:
                    await send_alert(
                        f"Analyzer فشل {consecutive_errors} مرات متتالية\nالخطأ: {str(e)[:200]}",
                        level='critical', component='Analyzer'
                    )
                await asyncio.sleep(wait)

    finally:
        await evidence_v2.stop('analyzer', ev2_task)
        await client.close_connection()
        await Database.disconnect()


def _with_ev2(metadata: dict) -> dict:
    """Heartbeat metadata plus recorder health when v2 is enabled (unchanged otherwise)."""
    health = evidence_v2.health('analyzer')
    return {**metadata, 'evidence_v2': health} if health is not None else metadata


def _record_candidate_analyzed(combined: dict) -> None:
    """P1: one event per new candidate state (same candle re-analysed = suppressed)."""
    if not evidence_v2.enabled():
        return
    try:
        pit = combined.get('pit') or {}
        ob = combined.get('order_book') or {}
        state = {'trade_type': combined.get('trade_type'),
                 'stop_valid': combined.get('stop_valid'),
                 'stop_reject_reason': combined.get('stop_reject_reason'),
                 'entry_price': combined.get('entry_price'),
                 'stop_loss': combined.get('stop_loss')}
        subject = {'candidate_id': pit.get('candidate_id'), 'candle_id': pit.get('candle_id'),
                   'symbol': combined.get('symbol'), 'timeframe': combined.get('timeframe')}
        payload = {
            'geometry': {k: combined.get(k) for k in (
                'entry_price', 'target_1', 'target_2', 'target_3', 'stop_loss',
                'stop_invalidation', 'stop_risk_pct', 'stop_policy', 'stop_valid',
                'stop_reject_reason')},
            'setup': {k: combined.get(k) for k in (
                'trade_type', 'entry_reason', 'selection_policy', 'market_condition',
                'total_score', 'trend_ok')},
            'order_book': {k: ob.get(k) for k in ('valid', 'spread_pct', 'score', 'bid_ask_ratio')},
            'features': combined.get('research_features') or combined.get('features') or {},
            'execution_features': combined.get('execution_features') or {},
            'regime': combined.get('regime'),
            'pit': pit,
        }
        evidence_v2.emit('analyzer', 'candidate.analyzed', subject, payload, state=state,
                         dedup_key=f"candidate:{subject['candidate_id'] or subject['symbol'] + '|' + str(subject['timeframe'])}",
                         event_time_ms=pit.get('analyzed_at_ms'))
    except Exception as exc:
        evidence_v2.hook_error('analyzer', exc)

async def analyze_symbol_all_timeframes(tech_analyzer, ob_analyzer, row):
    """تحليل عملة واحدة على جميع الـ Timeframes"""
    symbol = row['symbol']
    results = {}
    ob_fetched_at_ms = None   # P1 point-in-time stamp of the (shared) order book fetch

    for tf in config.TIMEFRAMES:
        try:
            tech_result = await tech_analyzer.analyze(symbol, timeframe=tf)
            if not tech_result:
                continue

            # Order Book نجلبه مرة واحدة فقط (نفس لكل الـ timeframes)
            if not results:
                ob_result = await ob_analyzer.analyze(symbol)
                ob_fetched_at_ms = evidence_v2.now_ms() if evidence_v2.enabled() else None   # P1 point-in-time stamp
            else:
                ob_result = list(results.values())[0].get('order_book')

            combined = {**tech_result, 'order_book': ob_result, 'timeframe': tf}
            if isinstance(combined.get('pit'), dict) and combined['pit']:
                combined['pit'] = {**combined['pit'], 'orderbook_fetched_at_ms': ob_fetched_at_ms}

            await Database.execute(
                """
                INSERT INTO analysis_results (symbol, timeframe, analysis_data, analyzed_at, signal_generated)
                VALUES ($1, $2, $3, NOW(), false)
                ON CONFLICT (symbol, timeframe) DO UPDATE
                SET analysis_data = $3, analyzed_at = NOW(), signal_generated = false,
                    processing_status = 'pending', decision_reason = NULL, decision_at = NULL
                """,
                symbol, tf, json.dumps(combined)
            )

            results[tf] = combined
            _record_candidate_analyzed(combined)
            logger.info(f"✅ {symbol} [{tf}] - النقاط: {combined.get('total_score', 0)}/10")

        except Exception as e:
            logger.error(f"❌ خطأ في تحليل {symbol} [{tf}]: {e}")

    # تحديث حالة المرشح بعد تحليل جميع الـ Timeframes
    if results:
        await Database.execute(
            """UPDATE scan_candidates
               SET analyzed=true, processing_status='analyzed', processed_at=NOW(), failure_reason=NULL
               WHERE id=$1""",
            row['id']
        )

if __name__ == "__main__":
    asyncio.run(main())
