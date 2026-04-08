"""
Telegram - إرسال الإشارات مع نظام الموافقة والـ Whitelist
"""
import asyncio
import sys
import json
sys.path.append('/app')

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
from whitelist import WhitelistManager, ApprovalManager

logger = setup_logger('telegram_sender')

MARKET_CONDITION_AR = {
    'bullish': 'صاعد 📈',
    'bearish': 'هابط 📉',
    'sideways': 'جانبي ↔️',
    'volatile': 'متقلب ⚡',
    'strong_bullish': 'صاعد قوي 🚀',
    'strong_bearish': 'هابط قوي 🔻',
}


async def main():
    logger.info("🚀 بدء تشغيل Telegram Bot...")
    await Database.connect()

    whitelist_mgr = WhitelistManager()
    approval_mgr = ApprovalManager()

    # بناء التطبيق
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # تسجيل الأوامر
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("whitelist",cmd_whitelist))
    app.add_handler(CommandHandler("pause",    cmd_pause))
    app.add_handler(CommandHandler("resume",   cmd_resume))
    app.add_handler(CommandHandler("stats",    cmd_stats))

    # معالج أزرار الموافقة
    app.add_handler(CallbackQueryHandler(handle_callback))

    # تشغيل حلقة إرسال الإشارات في الخلفية
    asyncio.create_task(signal_loop(app.bot, whitelist_mgr, approval_mgr))

    logger.info("✅ البوت يعمل...")
    await app.run_polling(drop_pending_updates=True)


async def signal_loop(bot: Bot, whitelist_mgr: WhitelistManager,
                      approval_mgr: ApprovalManager):
    """حلقة مستمرة تراقب الإشارات الجديدة"""
    while True:
        try:
            # تنظيف الطلبات المنتهية
            expired = await approval_mgr.expire_old_requests()
            for req in expired:
                await notify_expired(bot, req['symbol'])

            # جلب الإشارات المعتمدة من Claude وغير المرسلة
            signals = await Database.fetch("""
                SELECT s.*
                FROM signals s
                LEFT JOIN approval_requests ar ON s.id = ar.signal_id
                WHERE s.claude_approved = true
                AND s.telegram_sent = false
                AND s.signal_time > NOW() - INTERVAL '2 hours'
                AND ar.id IS NULL
                ORDER BY s.score DESC
                LIMIT 5
            """)

            for signal in signals:
                signal = dict(signal)
                action = await approval_mgr.process_signal(signal)

                if action == 'sent_direct':
                    await send_signal_direct(bot, signal)
                elif action == 'awaiting_approval':
                    await send_approval_request(bot, signal)

                await asyncio.sleep(2)

            await asyncio.sleep(15)

        except Exception as e:
            logger.error(f"❌ خطأ في signal_loop: {e}")
            await asyncio.sleep(30)


async def send_signal_direct(bot: Bot, signal: dict):
    """إرسال الإشارة مباشرة (عملة في الـ Whitelist)"""
    try:
        message = build_signal_message(signal, is_direct=True)
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=message
        )
        await Database.execute(
            "UPDATE signals SET telegram_sent = true WHERE id = $1",
            signal['id']
        )
        logger.info(f"📤 إرسال مباشر: {signal['symbol']}")
    except Exception as e:
        logger.error(f"❌ خطأ في الإرسال المباشر: {e}")


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

        # تحديث حالة الإشارة
        await Database.execute(
            "UPDATE signals SET telegram_sent = true WHERE id = $1",
            signal['id']
        )
        logger.info(f"🔍 طلب موافقة: {signal['symbol']}")

    except Exception as e:
        logger.error(f"❌ خطأ في إرسال طلب الموافقة: {e}")


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
                f"✅ تمت الموافقة وإرسال الإشارة\n"
                f"📋 {signal['symbol']} أُضيفت للـ Whitelist تلقائياً"
            )

        elif result['action'] == 'reject':
            await query.edit_message_text(
                f"❌ تم رفض إشارة {signal['symbol']}\n"
                f"🔍 سيبحث البوت عن فرصة أخرى"
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
    except Exception:
        pass


async def get_current_price(symbol: str) -> float:
    """جلب السعر الحالي من Binance"""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                data = await resp.json()
                return float(data['price'])
    except Exception:
        return None


# ==================== أوامر التحكم ====================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Trading Signal Bot\n\n"
        "الأوامر المتاحة:\n"
        "/status   - حالة النظام\n"
        "/whitelist - العملات المعتمدة\n"
        "/stats    - إحصائيات اليوم\n"
        "/pause    - إيقاف مؤقت\n"
        "/resume   - استئناف"
    )

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

    status = "⏸️ موقوف" if (risk and risk['is_trading_paused']) else "✅ يعمل"
    await update.message.reply_text(
        f"📊 حالة النظام: {status}\n\n"
        f"📅 اليوم:\n"
        f"  إشارات: {risk['signals_sent'] if risk else 0}\n"
        f"  أرباح: {risk['wins'] if risk else 0}\n"
        f"  خسائر: {risk['losses'] if risk else 0}\n\n"
        f"📋 الـ Whitelist: {whitelist_count} عملة\n"
        f"⏳ طلبات معلّقة: {pending}"
    )

async def cmd_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mgr = WhitelistManager()
    symbols = await mgr.get_all()
    if not symbols:
        await update.message.reply_text("📋 الـ Whitelist فارغة حتى الآن")
        return
    lines = [f"• {s['symbol']}" for s in symbols]
    await update.message.reply_text(
        f"📋 العملات المعتمدة شرعياً ({len(symbols)}):\n\n" +
        "\n".join(lines)
    )

async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await Database.execute("""
        UPDATE risk_management SET is_trading_paused = true, pause_reason = 'إيقاف يدوي'
        WHERE date = CURRENT_DATE
    """)
    await update.message.reply_text("⏸️ تم إيقاف البوت مؤقتاً")

async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await Database.execute("""
        UPDATE risk_management SET is_trading_paused = false, pause_reason = NULL
        WHERE date = CURRENT_DATE
    """)
    await update.message.reply_text("▶️ تم استئناف البوت")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = await Database.fetchrow("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) as losses,
            ROUND(AVG(profit_percent)::numeric, 2) as avg_profit
        FROM trade_results
        WHERE exit_time > NOW() - INTERVAL '7 days'
    """)
    await update.message.reply_text(
        f"📊 إحصائيات آخر 7 أيام:\n\n"
        f"  إجمالي الصفقات: {stats['total']}\n"
        f"  أرباح: {stats['wins']}\n"
        f"  خسائر: {stats['losses']}\n"
        f"  متوسط الربح: {stats['avg_profit']}%"
    )


# ==================== بناء الرسائل ====================

def build_signal_message(signal: dict, is_direct: bool = False) -> str:
    market_ar = MARKET_CONDITION_AR.get(
        signal['market_condition'], signal['market_condition']
    )
    entry = float(signal['entry_price'])
    trade_amount = config.TRADE_AMOUNT_USDT
    quantity = trade_amount / entry
    paper_badge = "📝 بيبر تريد | " if signal['is_paper_trade'] else ""
    whitelist_badge = "✅ معتمدة" if is_direct else "🆕 جديدة"

    return (
        f"{'─'*30}\n"
        f"🎯 {signal['symbol']}  {whitelist_badge}\n"
        f"{paper_badge}وضع السوق: {market_ar}\n\n"
        f"💰 حجم الصفقة: {trade_amount} USDT\n"
        f"📊 الكمية: {format_quantity(quantity)}\n\n"
        f"📈 Buy: {format_price(entry)}\n\n"
        f"🎯 Target:\n"
        f"  T1: {format_price(signal['target_1'])}\n"
        f"  T2: {format_price(signal['target_2'])}\n"
        f"  T3: {format_price(signal['target_3'])}\n\n"
        f"🛑 Stop: {format_price(signal['stop_loss'])}\n\n"
        f"⏰ اغلاق {signal['timeframe']} أقل من\n"
        f"⭐ القوة: {signal['score']}/10\n"
        f"{'─'*30}"
    )

def build_approval_message(signal: dict) -> str:
    market_ar = MARKET_CONDITION_AR.get(
        signal['market_condition'], signal['market_condition']
    )
    return (
        f"{'─'*30}\n"
        f"🔍 مراجعة شرعية مطلوبة\n"
        f"{'─'*30}\n\n"
        f"🪙 {signal['symbol']}  🆕 عملة جديدة\n"
        f"وضع السوق: {market_ar}\n\n"
        f"📈 Buy: {format_price(signal['entry_price'])}\n"
        f"🎯 T1: {format_price(signal['target_1'])}\n"
        f"🎯 T2: {format_price(signal['target_2'])}\n"
        f"🎯 T3: {format_price(signal['target_3'])}\n"
        f"🛑 Stop: {format_price(signal['stop_loss'])}\n\n"
        f"💰 الصفقة: {config.TRADE_AMOUNT_USDT} USDT\n"
        f"⭐ القوة: {signal['score']}/10\n\n"
        f"⏰ ينتهي الطلب خلال 30 دقيقة\n"
        f"{'─'*30}"
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
