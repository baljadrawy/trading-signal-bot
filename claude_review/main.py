"""
Claude Review - يراجع الإشارات قبل إرسالها
يستخدم claude CLI (اشتراك Claude Code) بدلاً من Anthropic SDK المباشر
"""
import asyncio
import json
import subprocess
import sys
sys.path.append('/app')

from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
from shared.alerts import send_alert
from shared.retry_utils import format_error, is_network_error, compute_backoff, alert_threshold
from shared.health import mark_started, mark_success, mark_failure
from shared.schema import require_schema
from shared.outbox import worker_id, claim, ack, fail, enqueue

logger = setup_logger('claude_review')

CLAUDE_BIN = '/usr/bin/claude'

async def main():
    logger.info("بدء تشغيل Claude Review (via claude CLI)...")
    await Database.connect()
    await require_schema('claude_review')
    await mark_started('claude_review')

    consecutive_errors = 0
    owner = worker_id('claude_review')

    try:
        while True:
            try:
                events = await claim('signal.created', owner, limit=20)
                reviewed = 0
                for event in events:
                    try:
                        signal = await Database.fetchrow("""
                            SELECT id, symbol, timeframe, market_condition,
                                   entry_price, target_1, target_2, target_3,
                                   stop_loss, score, score_details, trade_type,
                                   claude_comment
                            FROM signals WHERE id=$1""", event['aggregate_id'])
                        if signal and not signal['claude_comment']:
                            await review_signal(dict(signal))
                            reviewed += 1
                        await ack(event['id'], owner)
                    except Exception as event_error:
                        await fail(event['id'], owner, event_error)
                        logger.error("outbox signal.created %s failed: %s",
                                     event['id'], format_error(event_error))

                consecutive_errors = 0
                await mark_success('claude_review', {
                    'events_claimed': len(events), 'signals_reviewed': reviewed})
                await asyncio.sleep(15)

            except Exception as e:
                consecutive_errors += 1
                await mark_failure('claude_review', e)
                network = is_network_error(e)
                wait = compute_backoff(consecutive_errors, network)
                msg = f"❌ خطأ في Claude Review ({consecutive_errors}): {format_error(e)}"
                if network:
                    logger.warning(msg)
                else:
                    logger.error(msg)
                if consecutive_errors >= alert_threshold(network):
                    await send_alert(
                        f"Claude Review فشل {consecutive_errors} مرات متتالية\nالخطأ: {format_error(e)[:200]}",
                        level='critical', component='ClaudeReview'
                    )
                await asyncio.sleep(wait)
                
    finally:
        await Database.disconnect()

async def review_signal(signal: dict):
    """مراجعة إشارة واحدة بواسطة claude CLI"""
    try:
        # ── وضع التعلّم الحي: موافقة تلقائية (المحرّك البسيط + بوابة الماكرو هما قرار الدخول) ──
        # نتجاوز معايير claude القديمة (الانعكاسية) لأنها ترفض إشارات الزخم وتُحيّز جمع البيانات.
        if config.LIVE_LEARNING_MODE:
            await store_review(signal['id'], True, 'policy_auto',
                               'live-learning policy: automatic approval (Claude not invoked)')
            logger.info(f"✅ {signal['symbol']} [{signal.get('trade_type')}/{signal.get('timeframe')}] "
                        f"— موافقة تلقائية (وضع التعلّم الحي)")
            return

        score_details = signal['score_details']
        if isinstance(score_details, str):
            score_details = json.loads(score_details)

        # حساب نسبة المخاطرة/المكافأة
        entry = float(signal['entry_price'])
        stop = float(signal['stop_loss'])
        t1 = float(signal['target_1'])
        risk = entry - stop
        reward = t1 - entry
        rr_ratio = reward / risk if risk > 0 else 0

        # جلب عدد Timeframes المؤكدة من score_details
        confirmed_tfs = score_details.get('confirmed_timeframes', [signal['timeframe']])
        tf_count = score_details.get('timeframe_confirmations', 1)

        t1_pct = (float(signal['target_1']) - entry) / entry * 100
        t2_pct = (float(signal['target_2']) - entry) / entry * 100
        sl_pct = (stop - entry) / entry * 100

        prompt = f"""أنت محلل تداول صارم. هدفك رفع نسبة الربح، لذا ارفض الإشارات المشكوك فيها.

نظام التسجيل الجديد (بعد إعادة بناء 2026-04-22):
- 3 مؤشرات نشطة فقط (mean-reverting): rsi, bollinger, stoch_rsi — كل واحد يعطي 0 إلى 1 نقطة
- مكافأة إضافية من order_book و BTC trend
- المفاتيح التالية في score_details دائماً 0 (المؤشرات معطّلة عمداً — لا تعتبرها نقطة ضعف):
  macd, ema_cross, volume, obv, btc_trend
- نطاق النقاط الفعلي: 0 إلى ~3.5 (وليس 0-10)
- قيمة النقاط {signal['score']} هنا مقبولة لأنها بالفعل تجاوزت عتبة النظام

الإشارة:
- العملة: {signal['symbol']} | الإطار الرئيسي: {signal['timeframe']}
- حالة السوق: {signal['market_condition']}
- النقاط: {signal['score']}
- الإطارات المؤكِّدة: {tf_count} إطار — {', '.join(confirmed_tfs)}
- تفاصيل المؤشرات: {json.dumps(score_details, indent=2, ensure_ascii=False)}

مستويات التداول:
- دخول: {entry} | SL: {stop} ({sl_pct:.2f}%)
- T1: {signal['target_1']} ({t1_pct:.2f}%) | T2: {signal['target_2']} ({t2_pct:.2f}%)
- R:R = {rr_ratio:.2f}

معايير الرفض (ارفض فقط إذا تحقق واحدة من هذه):
1. R:R < 1.0 (مخاطرة بلا عائد)
2. حالة السوق = volatile (تاريخياً 34% win rate)
3. عدد الإطارات المؤكِّدة < 2 — إلا إذا كان الإطار 1d في bearish أو sideways (بيانات: WR=57-58% على 66 صفقة — استثناء معتمد)
4. كل المؤشرات الثلاثة النشطة (rsi, bollinger, stoch_rsi) = 0 أو أقل من 0.3

وافق في كل حالة أخرى. لا تنظر إلى المؤشرات المعطّلة كسبب للرفض.

الشكل المطلوب (بدون أي نص إضافي):
DECISION: APPROVED أو REJECTED
REASON: [سبب محدد بجملة واحدة، اذكر الرقم إذا رفضت]"""

        # تشغيل claude CLI عبر stdin لتجنب حدود argument length
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [CLAUDE_BIN, '-p', '--output-format', 'text'],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=90
            )
        )

        if result.returncode != 0:
            raise RuntimeError(f"claude CLI exit {result.returncode}: {result.stderr[:200]}")

        response_text = result.stdout.strip()
        approved = "APPROVED" in response_text
        reason = ""

        if "REASON:" in response_text:
            reason = response_text.split("REASON:")[-1].strip()

        # تحديث قاعدة البيانات
        await store_review(signal['id'], approved, 'claude', reason)

        status = "موافق" if approved else "مرفوض"
        logger.info(f"{status} على إشارة {signal['symbol']} - {reason[:50]}")

    except Exception as e:
        logger.error(f"خطأ في مراجعة الإشارة {signal['id']}: {e}")
        # fail-closed: عند فشل CLI نرفض الإشارة (الأمان أولاً — لا تداول على إشارة غير مُراجَعة).
        # كتابة claude_comment تمنع إعادة التقاطها في الـloop؛ claude_approved=false يمنع إرسالها.
        await store_review(
            signal['id'], False, 'system_fail_closed',
            f'رفض تلقائي - فشل المراجعة (fail-closed): {str(e)[:100]}')
        await send_alert(
            f"Claude Review CLI failure — رفض تلقائي (fail-closed) على {signal['symbol']}\nالخطأ: {str(e)[:150]}",
            level='warning', component='ClaudeReview'
        )


async def store_review(signal_id: int, approved: bool, decision_source: str, comment: str):
    """Persist review and its next-stage event in one transaction."""
    async with Database.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """UPDATE signals SET claude_approved=$1,claude_comment=$2,
                                      decision_source=$3, strategy_version=$4
                   WHERE id=$5""", approved, comment, decision_source,
                config.APP_VERSION, signal_id)
            await enqueue(conn, 'signal.reviewed', 'signal', signal_id,
                          {'signal_id': signal_id, 'approved': approved,
                           'decision_source': decision_source,
                           'strategy_version': config.APP_VERSION})

if __name__ == "__main__":
    asyncio.run(main())
