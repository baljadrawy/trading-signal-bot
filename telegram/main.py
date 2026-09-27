"""
Telegram - إرسال الإشارات مع نظام الموافقة والـ Whitelist
"""
import asyncio
import sys
import json
from datetime import datetime
from functools import wraps
sys.path.append('/app')

from telegram import Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from shared.config import config
from shared.database import Database
from shared.fees import net_pct, net_usdt, fee_usdt
from shared.logger import setup_logger
from shared.alerts import send_alert
from shared.retry_utils import format_error, is_network_error, compute_backoff, alert_threshold
from shared.health import mark_started, mark_success, mark_failure
from shared.schema import require_schema
from shared import evidence_v2
from shared.outbox import worker_id, claim, ack, fail, enqueue
from shared.telegram_messages import (
    opened_message, target_message, closed_message, risk_halted_message,
    runtime_status_message,
)
from shared.trading_state import get_pause_state
from shared.signal_readiness import (
    LEGACY_SIGNAL_REVIEWED_EVENT, READY_SQL_PREDICATE, SIGNAL_READY_EVENT,
    decision_breakdown, decision_breakdown_lines, decision_label, is_deliverable_for_event,
    is_ready_row,
)
from shared.risk_epoch import (
    LOSS_STREAK_HALTED, LOSS_STREAK_RECOVERY_REQUIRED, TRADING_PAUSED,
    RecoveryRejected, loss_streak_state, operational_state, record_recovery,
)
from whitelist import WhitelistManager, ApprovalManager, BlacklistManager

logger = setup_logger('telegram_sender')


def restricted(func):
    """حارس صلاحيات: يرفض أي أمر/زر من غير صاحب البوت (TELEGRAM_CHAT_ID).

    يتجاهل الدخيل بصمت (لا يردّ عليه حتى لا يكشف وجود البوت) ويسجّل المحاولة.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        chat_id = str(chat.id) if chat else None
        if not config.TELEGRAM_CHAT_ID or chat_id != str(config.TELEGRAM_CHAT_ID):
            user = update.effective_user
            uname = f"@{user.username}" if user and user.username else (
                str(user.id) if user else "?")
            logger.warning(
                f"🚫 محاولة وصول غير مصرّح بها — chat_id={chat_id} user={uname} "
                f"handler={func.__name__}"
            )
            return
        return await func(update, context)
    return wrapper


MARKET_CONDITION_AR = {
    'bullish': 'صاعد 📈',
    'bearish': 'هابط 📉',
    'sideways': 'جانبي ↔️',
    'volatile': 'متقلب ⚡',
    'strong_bullish': 'صاعد قوي 🚀',
    'strong_bearish': 'هابط قوي 🔻',
}


# ── Evidence recorder v2 (P1-D) — delivery refusals and owner risk controls. Helpers read their
# inputs, never raise and are no-ops unless EVIDENCE_V2_ENABLED; delivery behaviour is unchanged.
def _with_ev2(metadata: dict) -> dict:
    """Heartbeat metadata plus recorder health when v2 is enabled (unchanged otherwise)."""
    health = evidence_v2.health('telegram')
    return {**metadata, 'evidence_v2': health} if health is not None else metadata


def _v2_signal_subject(signal) -> dict:
    features = signal['features_snapshot'] if 'features_snapshot' in signal.keys() else None
    if isinstance(features, str):
        features = json.loads(features)
    identity = (features or {}).get('identity') or {}
    return {'signal_id': signal['id'], 'candidate_id': identity.get('candidate_id'),
            'symbol': signal['symbol'], 'timeframe': signal['timeframe']}


def _v2_delivery(event_type: str, signal, outcome: str, reason=None, event_id=None, **extra) -> None:
    """delivery.* — one event per signal and delivery state (idempotent by signal)."""
    if not evidence_v2.enabled():
        return
    try:
        subject = (_v2_signal_subject(signal) if signal is not None
                   else {'signal_id': None, 'outbox_event_id': event_id})
        if outcome == 'skipped' and reason is None:
            reason = ('signal_missing' if not signal else 'already_sent' if signal['telegram_sent']
                      else 'not_approved')
        evidence_v2.emit('telegram', event_type, subject, {'outbox_event_id': event_id, **extra},
                         state={'outcome': outcome, 'reason': reason},
                         dedup_key=f"delivery:{subject.get('signal_id') or event_id}")
    except Exception as exc:
        evidence_v2.hook_error('telegram', exc)


def _v2_streak_details(streak) -> dict:
    return {k: getattr(streak, k, None) for k in ('consecutive_losses', 'halt_threshold',
                                                   'open_positions', 'halt_active')}


def _v2_control(command: str, outcome: str, streak=None, recovery=None, error=None, **details) -> None:
    """control.command — an owner risk-control action and its result (no chat identifiers).
    Raw objects are passed in and read here, inside the guard, never in the caller."""
    if not evidence_v2.enabled():
        return
    try:
        if streak is not None:
            details.update(_v2_streak_details(streak))
        if recovery is not None:
            details.update({k: recovery.get(k) for k in ('id', 'consecutive_losses_before',
                                                          'epoch_started_at', 'reason')})
        if error is not None:
            details['detail'] = str(error)[:200]
        evidence_v2.emit('telegram', 'control.command', {'stream': 'telegram.control', 'command': command},
                         details, state={'command': command, 'outcome': outcome}, transition=True)
    except Exception as exc:
        evidence_v2.hook_error('telegram', exc)


async def main():
    logger.info("🚀 بدء تشغيل Telegram Bot...")
    await Database.connect()
    await require_schema('telegram')
    await mark_started('telegram')

    whitelist_mgr = WhitelistManager()
    approval_mgr = ApprovalManager()

    # بناء التطبيق
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # تسجيل الأوامر
    app.add_handler(CommandHandler("start",            cmd_start))
    app.add_handler(CommandHandler("status",           cmd_status))
    app.add_handler(CommandHandler("whitelist",        cmd_whitelist))
    app.add_handler(CommandHandler("blacklist",        cmd_blacklist))
    app.add_handler(CommandHandler("remove_blacklist", cmd_remove_blacklist))
    app.add_handler(CommandHandler("remove_whitelist", cmd_remove_whitelist))
    app.add_handler(CommandHandler("pause",            cmd_pause))
    app.add_handler(CommandHandler("resume",           cmd_resume))
    app.add_handler(CommandHandler("recover_risk",     cmd_recover_risk))
    app.add_handler(CommandHandler("stats",            cmd_stats))
    app.add_handler(CommandHandler("performance",      cmd_performance))
    app.add_handler(CommandHandler("signals",          cmd_signals))
    app.add_handler(CommandHandler("daily",            cmd_daily))
    app.add_handler(CommandHandler("trades",           cmd_trades))

    # معالج أزرار الموافقة
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("✅ البوت يعمل...")

    async with app:
        # تسجيل الأوامر في قائمة التيليغرام
        await app.bot.set_my_commands([
            BotCommand("start",            "🤖 قائمة الأوامر"),
            BotCommand("status",           "📊 حالة النظام"),
            BotCommand("performance",      "🏆 أداء Claude والإشارات"),
            BotCommand("signals",          "📡 آخر الإشارات"),
            BotCommand("trades",           "💹 نتائج الصفقات"),
            BotCommand("daily",            "📅 ملخص اليوم الكامل"),
            BotCommand("whitelist",        "✅ العملات المعتمدة (قائمة بيضاء)"),
            BotCommand("blacklist",        "🚫 العملات المحظورة (قائمة سوداء)"),
            BotCommand("remove_blacklist", "♻️ إزالة عملة من القائمة السوداء"),
            BotCommand("remove_whitelist", "🗑️ إزالة عملة من القائمة البيضاء"),
            BotCommand("stats",            "📈 إحصائيات آخر 7 أيام"),
            BotCommand("pause",            "⏸️ إيقاف البوت مؤقتاً"),
            BotCommand("resume",           "▶️ استئناف البوت"),
            BotCommand("recover_risk",     "🔑 رفع قاطع سلسلة الخسائر بإقرار"),
        ])
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        signal_task = asyncio.create_task(signal_loop(app.bot, whitelist_mgr, approval_mgr))
        ev2_task = evidence_v2.start_flusher('telegram')   # None unless EVIDENCE_V2_ENABLED
        try:
            await asyncio.Event().wait()
        finally:
            signal_task.cancel()
            try:
                await signal_task
            except asyncio.CancelledError:
                pass
            await evidence_v2.stop('telegram', ev2_task)
            await app.updater.stop()
            await app.stop()


async def signal_loop(bot: Bot, whitelist_mgr: WhitelistManager,
                      approval_mgr: ApprovalManager):
    """حلقة مستمرة تراقب الإشارات الجديدة"""
    consecutive_errors = 0
    owner = worker_id('telegram')
    while True:
        try:
            # تنظيف الطلبات المنتهية
            expired = await approval_mgr.expire_old_requests()
            for req in expired:
                await notify_expired(bot, req['symbol'])

            lifecycle_delivered = await deliver_trade_lifecycle_events(bot, owner)

            # CR-1: signal.ready هو المسار النشط؛ signal.reviewed يبقى مقبولاً للأحداث
            # القديمة العالقة وللتراجع إلى claude_review (قبول مزدوج).
            events_claimed = 0
            delivered = 0
            for event_type in CANDIDATE_EVENT_TYPES:
                events = await claim(event_type, owner, limit=5)
                events_claimed += len(events)
                for event in events:
                    if await handle_candidate_event(
                            bot, approval_mgr, owner, event_type, event):
                        delivered += 1

            consecutive_errors = 0
            await mark_success('telegram', _with_ev2({
                'events_claimed': events_claimed, 'delivered': delivered,
                'lifecycle_delivered': lifecycle_delivered,
                'expired_requests': len(expired)}))
            await asyncio.sleep(15)

        except Exception as e:
            consecutive_errors += 1
            await mark_failure('telegram', e)
            network = is_network_error(e)
            wait = compute_backoff(consecutive_errors, network)
            msg = f"❌ خطأ في signal_loop ({consecutive_errors}): {format_error(e)}"
            if network:
                logger.warning(msg)
            else:
                logger.error(msg)
            if consecutive_errors >= alert_threshold(network):
                await send_alert(
                    f"Telegram signal_loop فشل {consecutive_errors} مرات متتالية\nالخطأ: {format_error(e)[:200]}",
                    level='critical', component='Telegram'
                )
            await asyncio.sleep(wait)


CANDIDATE_EVENT_TYPES = (SIGNAL_READY_EVENT, LEGACY_SIGNAL_REVIEWED_EVENT)
DELIVERY_PACING_SECONDS = 2


async def handle_candidate_event(bot: Bot, approval_mgr: ApprovalManager, owner: str,
                                 event_type: str, event) -> bool:
    """Gate and deliver one claimed candidate event; returns True when delivered.

    Not ready (per event type), missing or already-sent signals are acked without
    delivery. The pause/B3 gate (can_deliver_candidate) runs before any delivery.
    Any error -> fail() so the outbox retries / dead-letters as before.
    """
    try:
        signal = await Database.fetchrow(
            "SELECT * FROM signals WHERE id=$1", event['aggregate_id'])
        if not is_deliverable_for_event(event_type, signal):
            await ack(event['id'], owner)
            return False
        allowed, block_reason = await can_deliver_candidate()
        if not allowed:
            logger.info(
                "عدم إرسال المرشح %s إلى Telegram: %s",
                signal['symbol'], block_reason)
            await ack(event['id'], owner)
            return False
        signal = dict(signal)
        action = await approval_mgr.process_signal(signal)
        if action == 'sent_direct':
            await send_signal_direct(bot, signal)
        elif action == 'awaiting_approval':
            await send_approval_request(bot, signal)
        await ack(event['id'], owner)
        await asyncio.sleep(DELIVERY_PACING_SECONDS)
        return True
    except Exception as event_error:
        await fail(event['id'], owner, event_error)
        logger.error("outbox %s %s failed: %s",
                     event_type, event['id'], format_error(event_error))
        return False


async def send_signal_direct(bot: Bot, signal: dict):
    """Queue an approved candidate silently; Telegram reports only actual trade opens."""
    try:
        await mark_delivered(signal['id'])
        logger.info(f"📥 مرشح معتمد أُرسل لحارس المخاطر: {signal['symbol']}")
    except Exception as e:
        logger.error(f"❌ خطأ في الإرسال المباشر لـ {signal.get('symbol')}: {format_error(e)}")
        raise


async def can_deliver_candidate() -> tuple[bool, str]:
    """Avoid user-facing candidates that cannot become an actual tracked trade."""
    paused, pause_reason = await get_pause_state()
    tracker_heartbeat = await Database.fetchrow(
        "SELECT metadata FROM service_heartbeats WHERE service_name='trade_tracker'")
    tracker_meta = tracker_heartbeat['metadata'] if tracker_heartbeat else {}
    if isinstance(tracker_meta, str):
        tracker_meta = json.loads(tracker_meta)
    stream_meta = tracker_meta.get('price_stream') or {}
    stream_status = ('✅ لحظي' if stream_meta.get('connected')
                     else '⚠️ REST احتياطي')
    if paused:
        return False, pause_reason or 'trading_paused'
    open_count = await Database.fetchval(
        "SELECT COUNT(*) FROM active_trades WHERE status='open'") or 0
    capacity = min(config.MAX_OPEN_TRADES, config.RISK_CANARY_MAX_OPEN_TRADES)
    if capacity > 0 and open_count >= capacity:
        return False, f'portfolio_capacity_{open_count}/{capacity}'
    return True, 'eligible'


async def deliver_trade_lifecycle_events(bot: Bot, owner: str) -> int:
    """Deliver idempotent opened/target/closed events from the transactional outbox."""
    delivered = 0
    for event_type in (
        'risk.halted', 'price_stream.down', 'price_stream.restored',
        'tracker.recovered', 'trade.opened', 'trade.target_hit', 'trade.closed',
    ):
        events = await claim(event_type, owner, limit=20)
        for event in events:
            try:
                payload = event['payload']
                if isinstance(payload, str):
                    payload = json.loads(payload)
                if event_type in (
                    'price_stream.down', 'price_stream.restored', 'tracker.recovered'):
                    message = runtime_status_message(event_type, payload)
                elif event_type == 'risk.halted':
                    message = risk_halted_message(payload)
                elif event_type == 'trade.opened':
                    trade = await Database.fetchrow("""
                        SELECT at.*, s.trade_type
                        FROM active_trades at LEFT JOIN signals s ON s.id=at.signal_id
                        WHERE at.id=$1
                    """, payload['active_trade_id'])
                    if not trade:
                        await ack(event['id'], owner)
                        continue
                    message = opened_message(dict(trade), config.TRADE_AMOUNT_USDT)
                elif event_type == 'trade.target_hit':
                    trade = await Database.fetchrow(
                        "SELECT * FROM active_trades WHERE id=$1",
                        payload['active_trade_id'])
                    if not trade:
                        await ack(event['id'], owner)
                        continue
                    message = target_message(
                        dict(trade), payload['target'], payload['current_price'],
                        config.TRADE_AMOUNT_USDT, config.FEE_ROUNDTRIP_PCT,
                        effective_stop=payload.get('effective_stop'),
                        sold_fraction=payload.get('sold_fraction'),
                        remaining_fraction=payload.get('remaining_fraction'))
                else:
                    result = await Database.fetchrow("""
                        SELECT tr.* FROM trade_results tr WHERE tr.id=$1
                    """, payload['trade_result_id'])
                    if not result:
                        await ack(event['id'], owner)
                        continue
                    result = dict(result)
                    result['active_trade_id'] = payload.get('active_trade_id')
                    result['target_fills'] = [dict(row) for row in await Database.fetch("""
                        SELECT target_number,quantity_fraction,fill_price
                        FROM trade_target_fills
                        WHERE active_trade_id=$1 ORDER BY target_number
                    """, payload.get('active_trade_id'))]
                    message = closed_message(
                        result, config.FEE_ROUNDTRIP_PCT,
                        config.TRADE_AMOUNT_USDT)
                await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=message)
                await ack(event['id'], owner)
                delivered += 1
            except Exception as event_error:
                await fail(event['id'], owner, event_error)
                logger.error("outbox %s %s failed: %s", event_type, event['id'],
                             format_error(event_error))
    return delivered


async def send_approval_request(bot: Bot, signal: dict):
    """إرسال طلب موافقة مع أزرار للعملات الجديدة"""
    try:
        message = build_approval_message(signal)

        # أزرار الموافقة
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ موافق - شرعياً مقبولة",
                    callback_data=f"approve_{signal['id']}"
                ),
                InlineKeyboardButton(
                    "❌ رفض",
                    callback_data=f"reject_{signal['id']}"
                ),
            ]
        ])

        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=message,
            reply_markup=keyboard
        )

        # لا ننشر signal.delivered قبل موافقة المستخدم؛ وإلا قد تُفتح الصفقة
        # بينما رسالة Telegram ما زالت مجرد طلب موافقة.
        logger.info(f"🔍 طلب موافقة: {signal['symbol']}")

    except Exception as e:
        logger.error(f"❌ خطأ في إرسال طلب الموافقة لـ {signal.get('symbol')}: {format_error(e)}")
        raise


async def mark_delivered(signal_id: int):
    """Record Telegram delivery and publish trade registration atomically."""
    async with Database.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE signals SET telegram_sent=true WHERE id=$1", signal_id)
            await enqueue(conn, 'signal.delivered', 'signal', signal_id,
                          {'signal_id': signal_id})


@restricted
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة ضغط أزرار الموافقة/الرفض"""
    query = update.callback_query
    await query.answer()

    data = query.data
    approval_mgr = ApprovalManager()

    if data.startswith("approve_") or data.startswith("reject_"):
        signal_id = int(data.split("_")[1])
        approved = data.startswith("approve_")

        # جلب السعر الحالي للتحقق
        signal = await Database.fetchrow(
            "SELECT symbol, entry_price FROM signals WHERE id = $1", signal_id
        )
        if not signal:
            await query.edit_message_text("⚠️ الإشارة غير موجودة")
            return

        # جلب السعر الحالي من Binance
        current_price = await get_current_price(signal['symbol'])
        if not current_price:
            current_price = float(signal['entry_price'])

        result = await approval_mgr.handle_approval(signal_id, approved, current_price)

        if result['action'] == 'send':
            # أرسل الإشارة للبوت المنفذ
            full_signal = await Database.fetchrow(
                "SELECT * FROM signals WHERE id = $1", signal_id
            )
            await send_signal_direct(context.bot, dict(full_signal))
            await query.edit_message_text(
                f"✅ تمت الموافقة وإرسال المرشح لحارس المخاطر\n"
                f"سيصلك إشعار منفصل فقط إذا فُتحت الصفقة فعلياً\n"
                f"📋 {signal['symbol']} أُضيفت للـ Whitelist تلقائياً"
            )

        elif result['action'] == 'reject':
            await query.edit_message_text(
                f"🚫 تم رفض {signal['symbol']} وإضافتها للقائمة السوداء\n"
                f"لن يسألك البوت عنها مجدداً\n\n"
                f"إذا أردت إعادتها لاحقاً:\n"
                f"/remove_blacklist {signal['symbol']}"
            )

        elif result['action'] == 'expired':
            await query.edit_message_text(
                f"⏰ انتهت صلاحية الإشارة\n"
                f"السبب: {result['reason']}"
            )

        elif result['action'] == 'price_changed':
            await query.edit_message_text(
                f"⚠️ تعذّر إرسال الإشارة\n"
                f"السبب: {result['reason']}\n"
                f"🔍 سيبحث البوت عن فرصة أخرى"
            )


async def notify_expired(bot: Bot, symbol: str):
    """إشعار انتهاء صلاحية طلب الموافقة"""
    try:
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=f"⏰ انتهت صلاحية إشارة {symbol} (30 دقيقة)\n"
                 f"🔍 البوت يبحث عن فرصة أخرى..."
        )
    except Exception as e:
        logger.warning(f"تعذر إشعار انتهاء {symbol}: {format_error(e)}")


async def get_current_price(symbol: str) -> float:
    """جلب السعر الحالي من Binance"""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:200]
                    raise RuntimeError(f"Binance HTTP {resp.status}: {body}")
                data = await resp.json()
                if 'price' not in data:
                    raise ValueError(f"Binance response missing price: {str(data)[:200]}")
                return float(data['price'])
    except Exception as e:
        logger.warning(f"تعذر جلب سعر {symbol} للموافقة: {format_error(e)}")
        return None


# ==================== أوامر التحكم ====================

@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Trading Signal Bot\n\n"
        "الأوامر المتاحة:\n"
        "/status   - حالة النظام\n"
        "/whitelist - العملات المعتمدة\n"
        "/stats    - إحصائيات اليوم\n"
        "/pause    - إيقاف مؤقت\n"
        "/resume   - استئناف\n"
        "/recover_risk <السبب> - رفع قاطع سلسلة الخسائر بإقرار صريح"
    )

@restricted
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    risk = await Database.fetchrow(
        "SELECT * FROM risk_management WHERE date = CURRENT_DATE"
    )
    whitelist_count = await Database.fetchval(
        "SELECT COUNT(*) FROM symbol_whitelist"
    )
    pending = await Database.fetchval(
        "SELECT COUNT(*) FROM approval_requests WHERE status = 'pending'"
    )
    open_trades = await Database.fetchval(
        "SELECT COUNT(*) FROM active_trades WHERE status='open'"
    ) or 0
    paused, pause_reason = await get_pause_state()

    # حالة بثّ الأسعار من نبضة trade_tracker. كانت تُقرأ سابقاً كمتغيّر عام
    # بينما هي محليّة داخل can_deliver_candidate، فكان /status يرفع NameError
    # في كل استدعاء.
    tracker_heartbeat = await Database.fetchrow(
        "SELECT metadata FROM service_heartbeats WHERE service_name='trade_tracker'")
    tracker_meta = tracker_heartbeat['metadata'] if tracker_heartbeat else {}
    if isinstance(tracker_meta, str):
        tracker_meta = json.loads(tracker_meta)
    stream_meta = (tracker_meta or {}).get('price_stream') or {}
    stream_status = ('✅ لحظي' if stream_meta.get('connected')
                     else '⚠️ REST احتياطي')

    # العتبات الحيّة من optimizer_settings (يحدّثها Optimizer تلقائياً)
    thresholds = await Database.fetch(
        "SELECT key, value FROM optimizer_settings "
        "WHERE key IN ('min_score_to_signal','min_timeframe_confirmations')"
    )
    settings = {row['key']: row['value'] for row in thresholds}
    min_score = settings.get('min_score_to_signal', '—')
    min_tf    = settings.get('min_timeframe_confirmations', '—')

    # حالة المخاطر تسبق حالة الإيقاف في العرض: رفع الإيقاف وحده يترك القبول
    # مرفوضاً، وهذا بالضبط اللبس الذي يجب ألا يتكرر.
    streak = await loss_streak_state()
    op_state = operational_state(streak, paused)
    status = {
        LOSS_STREAK_RECOVERY_REQUIRED:
            "🛑 قاطع سلسلة الخسائر — لا يُقبل أي دخول (يحتاج إقراراً يدوياً)",
        LOSS_STREAK_HALTED:
            "🛑 قاطع سلسلة الخسائر — لا يُقبل أي دخول",
        TRADING_PAUSED: "⏸️ موقوف",
    }.get(op_state, "✅ يبحث ويراقب")
    reason_line = f"\n🧯 سبب الإيقاف: {pause_reason}" if paused else ""
    if streak.halt_active:
        reason_line += (
            f"\n🔢 الخسائر المتتالية: {streak.consecutive_losses}/{streak.halt_threshold}"
            f"\n⚠️ الماسح قد يعمل ويولّد إشارات، لكن كل دخول جديد مرفوض"
        )
        if streak.manual_recovery_required:
            reason_line += (
                "\n🔑 لا توجد صفقة مفتوحة تستطيع كسر السلسلة تلقائياً — "
                "الاستئناف يحتاج /recover_risk <السبب>"
            )
        else:
            reason_line += (
                f"\n⏳ {streak.open_positions} صفقة مفتوحة قد تكسر السلسلة بإغلاق رابح"
            )
    capacity = min(config.MAX_OPEN_TRADES, config.RISK_CANARY_MAX_OPEN_TRADES)
    await update.message.reply_text(
        f"📊 حالة النظام: {status}{reason_line}\n\n"
        f"📅 اليوم:\n"
        f"  مرشحون اجتازوا الفحص: {risk['signals_sent'] if risk else 0}\n"
        f"  صفقات مفتوحة فعلياً: {open_trades}/{capacity}\n"
        f"  إغلاقات رابحة: {risk['wins'] if risk else 0}\n"
        f"  إغلاقات خاسرة: {risk['losses'] if risk else 0}\n\n"
        f"🎯 العتبات الحيّة:\n"
        f"  الحد الأدنى للنقاط: {min_score}\n"
        f"  تأكيد Timeframes: {min_tf}\n\n"
        f"📋 الـ Whitelist: {whitelist_count} عملة\n"
        f"⏳ طلبات معلّقة: {pending}\n"
        f"📡 مراقبة الأسعار: {stream_status}"
    )

@restricted
async def cmd_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mgr = WhitelistManager()
    symbols = await mgr.get_all()
    if not symbols:
        await update.message.reply_text("✅ القائمة البيضاء فارغة حتى الآن\nسيُضاف إليها كل عملة توافق عليها")
        return
    lines = [f"• {s['symbol']}" for s in symbols]
    await update.message.reply_text(
        f"✅ القائمة البيضاء — العملات المعتمدة ({len(symbols)}):\n"
        f"(تمر مرشحاتها مباشرة إلى حارس المخاطر؛ ويصلك إشعار عند فتح صفقة فعلية)\n\n" +
        "\n".join(lines)
    )

@restricted
async def cmd_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mgr = BlacklistManager()
    symbols = await mgr.get_all()
    if not symbols:
        await update.message.reply_text("🚫 القائمة السوداء فارغة\nالعملات المرفوضة ستظهر هنا")
        return
    lines = [f"• {s['symbol']}" for s in symbols]
    await update.message.reply_text(
        f"🚫 القائمة السوداء — العملات المحظورة ({len(symbols)}):\n"
        f"(لن تُحلَّل ولن تُرسل أبداً)\n\n" +
        "\n".join(lines) +
        f"\n\nللإزالة: /remove_blacklist SYMBOL"
    )

@restricted
async def cmd_remove_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إزالة عملة من القائمة السوداء — /remove_blacklist BTCUSDT"""
    if not context.args:
        await update.message.reply_text(
            "⚠️ يرجى تحديد العملة\nمثال: /remove_blacklist BTCUSDT"
        )
        return
    symbol = context.args[0].upper()
    mgr = BlacklistManager()
    if not await mgr.is_blacklisted(symbol):
        await update.message.reply_text(f"⚠️ {symbol} غير موجودة في القائمة السوداء")
        return
    await mgr.remove_from_blacklist(symbol)
    await update.message.reply_text(
        f"✅ تمت إزالة {symbol} من القائمة السوداء\n"
        f"سيبدأ البوت بتحليلها مجدداً في الدورة القادمة"
    )

@restricted
async def cmd_remove_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إزالة عملة من القائمة البيضاء ونقلها للسوداء — /remove_whitelist BTCUSDT"""
    if not context.args:
        await update.message.reply_text(
            "⚠️ يرجى تحديد العملة\nمثال: /remove_whitelist BTCUSDT"
        )
        return
    symbol = context.args[0].upper()
    wl = WhitelistManager()
    bl = BlacklistManager()
    if not await wl.is_whitelisted(symbol):
        await update.message.reply_text(f"⚠️ {symbol} غير موجودة في القائمة البيضاء")
        return
    await wl.remove(symbol)
    await bl.add_to_blacklist(symbol, reason="نُقلت من القائمة البيضاء للسوداء يدوياً")
    await update.message.reply_text(
        f"🚫 تمت إزالة {symbol} من القائمة البيضاء وإضافتها للسوداء\n"
        f"لن تُحلَّل ولن تُرسل مجدداً\n\n"
        f"للتراجع: /remove_blacklist {symbol}"
    )


@restricted
async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await Database.execute("""
        INSERT INTO risk_management (date, is_trading_paused, pause_reason)
        VALUES (CURRENT_DATE, true, 'manual_pause')
        ON CONFLICT (date) DO UPDATE SET
            is_trading_paused=true, pause_reason='manual_pause'
    """)
    _v2_control('pause', 'paused', pause_reason='manual_pause')
    await update.message.reply_text(
        "⏸️ تم إيقاف البحث وفتح صفقات جديدة حتى تستخدم /resume\n"
        "🛡️ الصفقات المفتوحة ستبقى تحت المتابعة وستصلك تحديثاتها وإغلاقاتها"
    )

@restricted
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await Database.execute("""
        INSERT INTO risk_management (date, is_trading_paused, pause_reason)
        VALUES (CURRENT_DATE, false, 'manual_resume')
        ON CONFLICT (date) DO UPDATE SET
            is_trading_paused=false, pause_reason='manual_resume'
    """)
    # لا يجوز أن يبدو النظام سليماً بينما القاطع ما زال يرفض كل دخول.
    streak = await loss_streak_state()
    _v2_control('resume', 'resumed', streak=streak)
    if streak.halt_active:
        extra = (
            f"\n\n🛑 لكن قاطع سلسلة الخسائر ما زال نشطاً "
            f"({streak.consecutive_losses}/{streak.halt_threshold}) — "
            f"**كل دخول جديد سيُرفض رغم الاستئناف**"
        )
        extra += (
            "\n🔑 لا توجد صفقة مفتوحة تكسرها تلقائياً؛ استخدم /recover_risk <السبب>"
            if streak.manual_recovery_required else
            f"\n⏳ {streak.open_positions} صفقة مفتوحة قد تكسرها بإغلاق رابح"
        )
        await update.message.reply_text(
            "▶️ تم رفع الإيقاف الإداري" + extra)
        return
    await update.message.reply_text("▶️ تم استئناف البحث والسماح لحارس المخاطر بقبول صفقات جديدة")

@restricted
async def cmd_recover_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رفع قاطع سلسلة الخسائر بإقرار صريح — /recover_risk <السبب>

    ليس تصفيراً للتاريخ: الصفقات القديمة تبقى كما هي، ويُسجَّل الإقرار نفسه
    في risk_recovery_events. يبدأ العدّ من حدود الحقبة الجديدة فقط.
    """
    reason = ' '.join(context.args or []).strip()
    if not reason:
        _v2_control('recover_risk', 'rejected_missing_reason')
        await update.message.reply_text(
            "⚠️ الاستئناف بعد قاطع سلسلة الخسائر يحتاج سبباً صريحاً\n"
            "مثال: /recover_risk راجعت الصفقات التسع ولا يوجد خلل تنفيذي\n\n"
            "🛡️ هذا إقرار مسؤول يُسجَّل باسمك، وليس تصفيراً للسجل"
        )
        return
    state = await loss_streak_state()
    try:
        event = await record_recovery(
            acknowledged_by=str(update.effective_chat.id), reason=reason)
    except RecoveryRejected as exc:
        _v2_control('recover_risk', 'rejected', streak=state, error=exc)
        await update.message.reply_text(
            f"⛔ تعذّر رفع القاطع: {exc}\n\n"
            f"🔢 السلسلة الحالية: {state.consecutive_losses}/{state.halt_threshold}\n"
            f"📂 صفقات مفتوحة: {state.open_positions}"
        )
        return
    paused, _ = await get_pause_state()
    _v2_control('recover_risk', 'recovered', recovery=event, still_paused=paused)
    next_step = (
        "\n\n▶️ التداول ما زال موقوفاً إدارياً — استخدم /resume لاستئناف البحث"
        if paused else ""
    )
    await update.message.reply_text(
        f"✅ تم رفع قاطع سلسلة الخسائر بإقرار صريح (سجل #{event['id']})\n\n"
        f"🔢 السلسلة قبل الإقرار: {event['consecutive_losses_before']}\n"
        f"📝 السبب: {event['reason']}\n"
        f"🕒 بداية الحقبة الجديدة: {event['epoch_started_at']:%Y-%m-%d %H:%M} UTC\n\n"
        f"🗂️ لم يُحذف أي سجل؛ الصفقات السابقة تبقى للتدقيق"
        f"{next_step}"
    )


@restricted
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = await Database.fetchrow("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) as losses,
            ROUND(AVG(profit_percent)::numeric, 2) as avg_profit,
            COALESCE(SUM(profit_usdt), 0) as sum_usdt
        FROM trade_results
        WHERE exit_time > NOW() - INTERVAL '7 days'
    """)
    # القيم المخزَّنة إجمالية؛ نعرض الصافي بعد الرسوم (shared.fees، نفس FEE_ROUNDTRIP_PCT للمُتعلّم)
    total = int(stats['total'] or 0)
    avg_net = net_pct(float(stats['avg_profit'] or 0))
    total_net = float(stats['sum_usdt'] or 0) - total * fee_usdt()
    await update.message.reply_text(
        f"📊 إحصائيات آخر 7 أيام (صافٍ بعد الرسوم):\n\n"
        f"  إجمالي الصفقات: {total}\n"
        f"  أرباح: {stats['wins']}\n"
        f"  خسائر: {stats['losses']}\n"
        f"  متوسط الربح الصافي: {avg_net:.2f}%\n"
        f"  إجمالي PnL صافٍ: {total_net:+.2f} USDT"
    )


# ==================== بناء الرسائل ====================

@restricted
async def cmd_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نتائج آخر الصفقات المسجلة"""
    # الصفقات المغلقة
    closed = await Database.fetch("""
        SELECT symbol, result, profit_percent, profit_usdt,
               target_reached, exit_time, notes
        FROM trade_results
        ORDER BY exit_time DESC
        LIMIT 8
    """)

    # الصفقات النشطة حالياً (عملة واحدة فقط لكل رمز)
    active = await Database.fetch("""
        SELECT DISTINCT ON (symbol)
               symbol, entry_price, highest_target_hit, opened_at
        FROM active_trades
        WHERE status = 'open'
        ORDER BY symbol, opened_at DESC
    """)

    lines = ["💹 نتائج الصفقات\n" + "─"*28]

    if active:
        lines.append(f"\n⏳ نشطة الآن ({len(active)}):")
        for t in active:
            hrs = ((datetime.now() - t['opened_at']).total_seconds() / 3600)
            lines.append(f"  • {t['symbol']} | T{t['highest_target_hit']} محقق | {hrs:.0f}س")

    if closed:
        lines.append(f"\n📊 آخر النتائج (صافٍ بعد الرسوم):")
        for t in closed:
            icon = "✅" if t['result'] == 'WIN' else "❌"
            # المخزَّن إجمالي؛ نعرض الصافي بعد الرسوم (shared.fees)
            np_ = net_pct(float(t['profit_percent'] or 0))
            nu_ = net_usdt(float(t['profit_usdt'] or 0))
            pct  = f"+{np_:.2f}%" if np_ > 0 else f"{np_:.2f}%"
            usdt = f"{nu_:.2f}"
            lines.append(f"  {icon} {t['symbol']} | {pct} ({usdt} USDT) | T{t['target_reached']}")
    else:
        lines.append("\nلا توجد نتائج بعد — الصفقات قيد المتابعة")

    await update.message.reply_text("\n".join(lines))


def build_signal_message(signal: dict, is_direct: bool = False) -> str:
    market_ar = MARKET_CONDITION_AR.get(
        signal['market_condition'], signal['market_condition']
    )
    entry = float(signal['entry_price'])
    stop  = float(signal['stop_loss'])
    t1    = float(signal['target_1'])
    trade_amount = config.TRADE_AMOUNT_USDT
    quantity = trade_amount / entry
    paper_badge = "🧪 بيبر تريد" if signal['is_paper_trade'] else "💰 تداول حقيقي"
    whitelist_badge = "✅ معتمدة" if is_direct else "🆕 تحتاج موافقة"
    rr = round((t1 - entry) / (entry - stop), 2) if (entry - stop) > 0 else 0

    # جلب الإطارات المؤكدة من score_details
    import json
    score_details = signal.get('score_details', {})
    if isinstance(score_details, str):
        score_details = json.loads(score_details)
    confirmed_tfs = score_details.get('confirmed_timeframes', [signal['timeframe']])
    tfs_str = ' + '.join(confirmed_tfs) if confirmed_tfs else signal['timeframe']

    t2   = float(signal['target_2'])
    t3   = float(signal['target_3'])
    t1_pct = ((t1   - entry) / entry) * 100
    t2_pct = ((t2   - entry) / entry) * 100
    t3_pct = ((t3   - entry) / entry) * 100
    sl_pct = ((stop - entry) / entry) * 100
    features_snapshot = signal.get('features_snapshot') or {}
    if isinstance(features_snapshot, str):
        features_snapshot = json.loads(features_snapshot)
    trade_type = signal.get('trade_type') or features_snapshot.get('trade_type') or 'legacy'
    reason = features_snapshot.get('entry_reason') or 'legacy_score_policy'
    reason_ar = {
        'close_above_ema20_ema50_breakout_with_volume': 'اختراق مؤكد بالاتجاه والحجم',
        'rsi_oversold_bounce_near_lower_bollinger': 'ارتداد تشبع قرب بولنجر السفلي',
        'legacy_score_policy': 'سياسة النقاط القديمة',
    }.get(reason, reason)

    return (
        f"{'─'*30}\n"
        f"🎯 {signal['symbol']}  {whitelist_badge}\n"
        f"{paper_badge} | وضع السوق: {market_ar}\n\n"
        f"💰 حجم الصفقة: {trade_amount} USDT\n"
        f"📊 الكمية: {format_quantity(quantity)}\n\n"
        f"📈 دخول: {format_price(entry)}\n\n"
        f"🎯 الأهداف:\n"
        f"  T1: {format_price(t1)}  (+{t1_pct:.2f}%)\n"
        f"  T2: {format_price(t2)}  (+{t2_pct:.2f}%)\n"
        f"  T3: {format_price(t3)}  (+{t3_pct:.2f}%)\n\n"
        f"🛑 وقف الخسارة: {format_price(stop)}  ({sl_pct:.2f}%)\n"
        f"⚖️ المخاطرة/المكافأة: {rr}\n\n"
        f"⏱️ الإطار: {tfs_str}\n"
        f"🧭 النوع: {trade_type}\n"
        f"🔎 سبب الدخول: {reason_ar}\n"
        f"📎 نقاط بحثية: {signal['score']}/10 (ليست سبب الاختيار)\n"
        f"{'─'*30}"
    )

def build_approval_message(signal: dict) -> str:
    market_ar = MARKET_CONDITION_AR.get(
        signal['market_condition'], signal['market_condition']
    )
    return (
        f"{'─'*30}\n"
        f"🔍 مرشح — مراجعة شرعية مطلوبة\n"
        f"{'─'*30}\n\n"
        f"🪙 {signal['symbol']}  🆕 عملة جديدة\n"
        f"وضع السوق: {market_ar}\n\n"
        f"📈 Buy: {format_price(signal['entry_price'])}\n"
        f"🎯 T1: {format_price(signal['target_1'])}\n"
        f"🎯 T2: {format_price(signal['target_2'])}\n"
        f"🎯 T3: {format_price(signal['target_3'])}\n"
        f"🛑 Stop: {format_price(signal['stop_loss'])}\n\n"
        f"💰 الحجم المقترح: {config.TRADE_AMOUNT_USDT} USDT\n"
        f"🧭 النوع: {signal.get('trade_type') or 'legacy'}\n"
        f"📎 نقاط بحثية: {signal['score']}/10 (ليست سبب الاختيار الحي)\n\n"
        f"⚠️ الموافقة لا تعني فتح صفقة؛ حارس المخاطر يقرر لاحقاً\n"
        f"⏰ ينتهي الطلب خلال 30 دقيقة\n"
        f"{'─'*30}"
    )

@restricted
async def cmd_performance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أداء قرارات الجاهزية حسب مصدرها الفعلي (decision_source) مع إبقاء التاريخ ظاهراً.

    claude_approved=true منذ 2026-06 تعني «سياسة آلية عبر المرحِّل» لا موافقة Claude؛
    لذلك نعدّ حسب المصدر بدل عرضها كموافقات Claude.
    """
    total = await Database.fetchval("SELECT COUNT(*) FROM signals") or 0
    decision_rows = await Database.fetch(
        "SELECT decision_source, claude_approved, COUNT(*) AS n FROM signals "
        "GROUP BY decision_source, claude_approved")
    breakdown = decision_breakdown(decision_rows or [])
    sent = await Database.fetchval("SELECT COUNT(*) FROM signals WHERE telegram_sent = true") or 0

    # أداء آخر 7 أيام
    wins = await Database.fetchval(
        "SELECT COUNT(*) FROM trade_results WHERE result='WIN' AND exit_time > NOW() - INTERVAL '7 days'"
    ) or 0
    losses = await Database.fetchval(
        "SELECT COUNT(*) FROM trade_results WHERE result='LOSS' AND exit_time > NOW() - INTERVAL '7 days'"
    ) or 0
    total_trades = wins + losses
    win_rate = f"{(wins/total_trades*100):.1f}%" if total_trades > 0 else "لا توجد بيانات بعد"

    decision_lines = "\n".join(decision_breakdown_lines(breakdown, total))

    await update.message.reply_text(
        f"🏆 أداء النظام\n"
        f"{'─'*28}\n\n"
        f"🧭 قرارات الجاهزية حسب المصدر:\n"
        f"  إجمالي الإشارات: {total}\n"
        f"{decision_lines}\n"
        f"  📤 مرسلة: {sent}\n\n"
        f"📊 نتائج الصفقات (7 أيام):\n"
        f"  أرباح: {wins} ✅\n"
        f"  خسائر: {losses} ❌\n"
        f"  نسبة النجاح: {win_rate}\n"
        f"{'─'*28}"
    )


@restricted
async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """آخر 5 مرشحين مع حالة عبورهم إلى حارس المخاطر."""
    signals = await Database.fetch("""
        SELECT symbol, timeframe, score, claude_approved, telegram_sent,
               signal_time, claude_comment, decision_source, strategy_version
        FROM signals
        ORDER BY signal_time DESC
        LIMIT 5
    """)

    if not signals:
        await update.message.reply_text("📡 لا توجد إشارات بعد")
        return

    lines = ["📡 آخر المرشحين (ليست صفقات مفتوحة)\n" + "─"*28]
    for s in signals:
        decision_icon = "✅" if is_ready_row(s) else "❌"
        sent_icon = "📤" if s['telegram_sent'] else "⏳"
        time_str = s['signal_time'].strftime("%H:%M") if s['signal_time'] else "؟"
        decision_text = decision_label(s['decision_source'], s['claude_approved'])
        lines.append(
            f"\n{sent_icon} {s['symbol']} [{s['timeframe']}]\n"
            f"  ⭐ {s['score']}/10 | القرار: {decision_icon} {decision_text} | {time_str}\n"
            f"  💬 {(s['claude_comment'] or '')[:60]}"
        )

    await update.message.reply_text("\n".join(lines))


@restricted
async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ملخص يومي كامل"""
    risk = await Database.fetchrow(
        "SELECT * FROM risk_management WHERE date = CURRENT_DATE"
    )
    signals_today = await Database.fetchval(
        "SELECT COUNT(*) FROM signals WHERE signal_time::date = CURRENT_DATE"
    ) or 0
    ready_today = await Database.fetchval(
        "SELECT COUNT(*) FROM signals s WHERE s.signal_time::date = CURRENT_DATE "
        f"AND {READY_SQL_PREDICATE}"
    ) or 0
    not_ready_today = max(signals_today - ready_today, 0)
    sent_today = await Database.fetchval(
        "SELECT COUNT(*) FROM signals WHERE signal_time::date = CURRENT_DATE AND telegram_sent = true"
    ) or 0
    opened_today = await Database.fetchval(
        "SELECT COUNT(*) FROM active_trades WHERE opened_at::date=CURRENT_DATE"
    ) or 0
    open_now = await Database.fetchval(
        "SELECT COUNT(*) FROM active_trades WHERE status='open'"
    ) or 0
    closed = await Database.fetchrow("""
        SELECT COUNT(*) AS total,
               COALESCE(SUM(profit_usdt), 0) AS gross_usdt
        FROM trade_results WHERE exit_time::date=CURRENT_DATE
    """)
    closed_today = int(closed['total'] or 0)
    net_today = float(closed['gross_usdt'] or 0) - closed_today * fee_usdt()

    # أفضل إشارة اليوم
    best = await Database.fetchrow("""
        SELECT symbol, score, claude_approved FROM signals
        WHERE signal_time::date = CURRENT_DATE
        ORDER BY score DESC LIMIT 1
    """)

    # حالة السوق من آخر تحليل
    market = await Database.fetchval("""
        SELECT analysis_data->>'market_condition'
        FROM analysis_results
        ORDER BY analyzed_at DESC LIMIT 1
    """) or "غير معروف"

    market_ar = MARKET_CONDITION_AR.get(market, market)
    paused, pause_reason = await get_pause_state()
    status = "⏸️ موقوف" if paused else "✅ يبحث ويراقب"
    reason_line = f"\n🧯 السبب: {pause_reason}" if paused else ""
    wins = risk['wins'] if risk else 0
    losses = risk['losses'] if risk else 0

    best_line = f"  🥇 أفضل إشارة: {best['symbol']} ({best['score']}/10)" if best else "  لا توجد بعد"

    await update.message.reply_text(
        f"📅 ملخص اليوم\n"
        f"{'─'*28}\n\n"
        f"⚙️ الحالة: {status}{reason_line}\n"
        f"🌍 وضع السوق: {market_ar}\n\n"
        f"📊 المرشحون (ليست صفقات):\n"
        f"  إجمالي: {signals_today}\n"
        f"  ✅ جاهزة (سياسة آلية/مسار قديم): {ready_today}\n"
        f"  ❌ غير جاهزة أو مرفوضة: {not_ready_today}\n"
        f"  🛡️ عَبَروا إلى حارس المخاطر: {sent_today}\n"
        f"{best_line}\n\n"
        f"💰 الصفقات:\n"
        f"  فُتحت اليوم: {opened_today}\n"
        f"  مفتوحة الآن: {open_now}\n"
        f"  أُغلقت اليوم: {closed_today}\n"
        f"  أرباح/خسائر: {wins} ✅ / {losses} ❌\n"
        f"  الصافي بعد التكلفة: {net_today:+.2f} USDT\n"
        f"{'─'*28}"
    )


def format_price(price) -> str:
    price = float(price)
    if price < 0.00001:   return f"{price:.8f}"
    elif price < 0.01:    return f"{price:.7f}"
    elif price < 1:       return f"{price:.6f}"
    elif price < 100:     return f"{price:.4f}"
    else:                 return f"{price:.2f}"

def format_quantity(quantity: float) -> str:
    if quantity >= 1000:       return f"{quantity:,.0f}"
    elif quantity >= 1:        return f"{quantity:.4f}"
    elif quantity >= 0.001:    return f"{quantity:.6f}"
    else:                      return f"{quantity:.8f}"

if __name__ == "__main__":
    asyncio.run(main())
