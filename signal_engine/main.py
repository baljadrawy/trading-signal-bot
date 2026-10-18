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
from shared.health import mark_started, mark_success, mark_failure
from shared.schema import require_schema
from shared.macro_context import MacroContext
from signal_logic import SignalEngine, signal_identity
from shared import evidence_v2
from shared.signal_identity import integrity_mode

logger = setup_logger('signal_engine')

SELECTION_LIMIT = 200          # the LIMIT of the candidate query below (unchanged)
_ELIGIBLE_WHERE = """
    WHERE signal_generated = false
    AND analyzed_at > NOW() - INTERVAL '30 minutes'
    AND symbol NOT IN (SELECT symbol FROM active_trades WHERE status = 'open')"""


def _with_ev2(metadata: dict) -> dict:
    """Heartbeat metadata plus recorder health when v2 is enabled (unchanged otherwise)."""
    health = evidence_v2.health('signal_engine')
    return {**metadata, 'evidence_v2': health} if health is not None else metadata


async def _v2_truncation(results) -> dict | None:
    """P1: measure LIMIT truncation with read-only queries, only when the limit was reached.
    Runs after the candidate query, so the rows given to the decision are never affected."""
    if not evidence_v2.enabled():
        return None
    try:
        if len(results) < SELECTION_LIMIT:
            info = {'truncated': False, 'returned': len(results)}
        else:
            total = await Database.fetchval("SELECT count(*) FROM analysis_results" + _ELIGIBLE_WHERE)
            cut = await Database.fetch(
                "SELECT symbol, timeframe FROM analysis_results" + _ELIGIBLE_WHERE +
                " ORDER BY symbol, (analysis_data->>'total_score')::float DESC"
                f" OFFSET {SELECTION_LIMIT} LIMIT 500")
            cut_rows = [[r['symbol'], r['timeframe']] for r in cut]
            info = {'truncated': int(total or 0) > SELECTION_LIMIT, 'returned': len(results),
                    'eligible_total': int(total or 0), 'truncated_count': max(0, int(total or 0) - len(results)),
                    'truncated_rows': cut_rows, 'count_is_separate_statement': True}
        evidence_v2.emit('signal_engine', 'selection.truncation', {'stream': 'signal_engine.selection'},
                         info, state={'truncated': info['truncated'],
                                      'rows': evidence_v2.sha256_hex(
                                          evidence_v2.canonical_json(info.get('truncated_rows')))[:16]},
                         dedup_key='selection.truncation', transition=True)
        return info
    except Exception as exc:
        evidence_v2.hook_error('signal_engine', exc)
        return None


def _v2_cycle(outcome: str, cycle_started_ms: int, results=(), decisions=None, context=None,
              truncation=None, signal_id=None) -> None:
    """P1: one cycle.outcome event per change of cycle state (idle/macro/no-trade/signal)."""
    if not evidence_v2.enabled():
        return
    try:
        histogram = {}
        for reason in (decisions or {}).values():
            key = reason.split(':')[0]
            histogram[key] = histogram.get(key, 0) + 1
        ctx = dict(context or {})
        payload = {
            'cycle_started_ms': cycle_started_ms,
            'duration_ms': evidence_v2.now_ms() - cycle_started_ms,
            'rows': len(results), 'symbols': len({r['symbol'] for r in results}),
            'decision_histogram': histogram, 'signal_id': signal_id,
            'macro': {k: ctx.get(k) for k in ('macro_state', 'macro_blocked', 'macro_data_valid',
                                              'macro_age_seconds', 'macro_valid_at_ms',
                                              'macro_snapshot', 'macro_trend_state')},
            'truncation': truncation,
        }
        evidence_v2.emit('signal_engine', 'cycle.outcome', {'stream': 'signal_engine.cycle'}, payload,
                         state={'outcome': outcome,
                                'truncated': bool(truncation and truncation.get('truncated'))},
                         dedup_key='cycle.outcome', transition=True, event_time_ms=cycle_started_ms)
    except Exception as exc:
        evidence_v2.hook_error('signal_engine', exc)


async def main():
    logger.info("🚀 بدء تشغيل Signal Engine...")

    await Database.connect()
    await require_schema('signal_engine')
    integrity_mode(config)                       # A44: unknown SIGNAL_INTEGRITY_MODE refuses to start
    await mark_started('signal_engine')

    # MacroContext only calls public klines (BTC/ETH 4h) — no auth needed.
    # Using empty keys avoids exposing live trading credentials to this container.
    client = await AsyncClient.create('', '')
    macro_ctx = MacroContext(client)

    engine = SignalEngine()
    ev2_task = evidence_v2.start_flusher('signal_engine')   # None unless EVIDENCE_V2_ENABLED

    # Evidence flight-recorder: start the async flusher ONLY when enabled (guarded; any
    # failure is buried and the engine continues unaffected).
    _evidence_rec = None
    _evidence_flusher = None
    if config.ENABLE_EVIDENCE_RECORDER:
        try:
            from signal_logic import get_evidence_recorder
            _evidence_rec = get_evidence_recorder()
            if _evidence_rec is not None:
                _evidence_flusher = asyncio.create_task(_evidence_rec.run_flusher())
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

    consecutive_errors = 0
    _last_heartbeat = 0.0  # لوج دوري كل 10 دقائق

    try:
        while True:
            try:
                # جلب نتائج التحليل لجميع الـ Timeframes
                # مستثنى: العملات المرفوضة + العملات التي لديها صفقة مفتوحة
                # ملاحظة: استثناء approval_requests المرفوضة حُذف من هنا —
                # كل العملات المرفوضة مُضافة لـ symbol_blacklist ومحظورة من Scanner.
                cycle_started_ms = evidence_v2.now_ms()
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
                truncation = await _v2_truncation(results)

                if not results:
                    _v2_cycle('idle_no_fresh_analysis', cycle_started_ms)
                    await mark_success('signal_engine', _with_ev2({'results': 0, 'status': 'idle'}))
                    now = time.time()
                    if now - _last_heartbeat >= 600:  # كل 10 دقائق
                        logger.info("💤 لا نتائج تحليل طازجة — البوت ينتظر")
                        _last_heartbeat = now
                    await asyncio.sleep(30)
                    continue

                # إيجاد أفضل فرصة مع تأكيد متعدد الـ Timeframes
                engine.last_decisions = {}
                engine.last_v2_context = None
                if config.LIVE_LEARNING_MODE:
                    best_signal = await engine.find_best_signal_live(results, macro_ctx)
                else:
                    best_signal = await engine.find_best_signal(results)

                decisions = getattr(engine, 'last_decisions', {})
                evaluated_symbols = sorted({row['symbol'] for row in results})
                await Database.executemany(
                    """UPDATE analysis_results
                       SET processing_status='evaluated', decision_reason=$2, decision_at=NOW()
                       WHERE symbol=$1 AND signal_generated=false
                         AND analyzed_at > NOW() - INTERVAL '30 minutes'""",
                    [(symbol, decisions.get(symbol, 'not_selected_or_blocked'))
                     for symbol in evaluated_symbols])

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
                        f"نوع: {best_signal.get('trade_type') or 'legacy'} | "
                        f"سبب: {best_signal.get('entry_reason') or 'legacy_score_policy'} | "
                        f"سياسة: {best_signal.get('selection_policy') or 'legacy_score_v1'} | "
                        f"تأكيد: {tfs or best_signal.get('timeframe', '?')}"
                    )

                    # حفظ الإشارة في قاعدة البيانات
                    try:
                        signal_id = await engine.save_signal(best_signal)
                    except Exception:
                        # P1-R: close the cycle record for a refused save; behaviour unchanged.
                        _v2_cycle('signal_refused', cycle_started_ms, results, decisions,
                                  getattr(engine, 'last_v2_context', None), truncation)
                        raise

                    if signal_id is None:
                        # A44 enforce: the setup was emitted before (a concurrent worker or an
                        # earlier cycle) — nothing was persisted or published this cycle.
                        _v2_cycle('duplicate_setup_suppressed', cycle_started_ms, results, decisions,
                                  getattr(engine, 'last_v2_context', None), truncation)
                        await mark_success('signal_engine', _with_ev2({
                            'results': len(results), 'signal_created': False,
                            'duplicate_suppressed': getattr(engine, 'last_emission', None)}))
                        await asyncio.sleep(60)
                        continue

                    # تحديث حالة التحليل لجميع الـ Timeframes لهذه العملة
                    await Database.execute(
                        """UPDATE analysis_results
                           SET signal_generated=true, processing_status='signal_created',
                               decision_reason='signal_created', decision_at=NOW()
                           WHERE symbol=$1""",
                        best_signal['symbol']
                    )

                    logger.info(f"✅ تم حفظ الإشارة بـ ID: {signal_id}")

                v2_context = getattr(engine, 'last_v2_context', None)
                _v2_cycle('signal_ready' if best_signal
                          else ('macro_blocked' if (v2_context or {}).get('macro_blocked')
                                else 'no_eligible_candidate'),
                          cycle_started_ms, results, decisions, v2_context, truncation,
                          signal_id if best_signal else None)
                await mark_success('signal_engine', _with_ev2({
                    'results': len(results),
                    'signal_created': bool(best_signal),
                }))

                await asyncio.sleep(60)

            except Exception as e:
                consecutive_errors += 1
                await mark_failure('signal_engine', e)
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
        await evidence_v2.stop('signal_engine', ev2_task)
        # bounded drain of evidence on shutdown (guarded; never blocks teardown unduly)
        if _evidence_flusher is not None:
            _evidence_flusher.cancel()
            try:
                await _evidence_flusher
            except (asyncio.CancelledError, Exception):
                pass
        if _evidence_rec is not None:
            try:
                pending = _evidence_rec.shutdown()
                logger.info("🛬 Evidence recorder drained on shutdown (pending=%d)", pending)
            except Exception:
                logger.warning("evidence shutdown drain failed", exc_info=True)
        await client.close_connection()
        await Database.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
