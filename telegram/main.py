"""
Telegram - إرسال الإشارات مع نظام الموافقة والـ Whitelist
"""
import asyncio
import sys
import json
from datetime import datetime
sys.path.append('/app')

from telegram import Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
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
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("status",      cmd_status))
    app.add_handler(CommandHandler("whitelist",   cmd_whitelist))
    app.add_handler(CommandHandler("pause",       cmd_pause))
    app.add_handler(CommandHandler("resume",      cmd_resume))
    app.add_handler(CommandHandler("stats",       cmd_stats))
    app.add_handler(CommandHandler("performance", cmd_performance))
    app.add_handler(CommandHandler("signals",     cmd_signals))
    app.add_handler(CommandHandler("daily",       cmd_daily))
    app.add_handler(CommandHandler("trades",      cmd_trades))

    # معالج أزرار الموافقة
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("✅ البوت يعمل...")

    async with app:
        # تسجيل الأوامر في قائمة التيليغرام
        await app.bot.set_my_commands([
            BotCommand("start",       "🤖 قائمة الأوامر"),
            BotCommand("status",      "📊 حالة النظام"),
            BotCommand("performance", "🏆 أداء Claude والإشارات"),
            BotCommand("signals",     "📡 آخر الإشارات"),
            BotCommand("trades",      "💹 نتائج الصفقات"),
            BotCommand("daily",       "📅 ملخص اليوم الكامل"),
            BotCommand("whitelist",   "📋 العملات المعتمدة"),
            BotCommand("stats",       "📈 إحصائيات آخر 7 أيام"),
            BotCommand("pause",       "⏸️ إيقاف البوت مؤقتاً"),
            BotCommand("resume",      "▶️ استئناف البوت"),
        ])
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        signal_task = asyncio.create_task(signal_loop(app.bot, whitelist_mgr, approval_mgr))
        try:
            await asyncio.Event().wait()
        finally:
            signal_task.cancel()
            try:
                await signal_task
            except asyncio.CancelledError:
                pass
            await app.updater.stop()
            await app.stop()


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
        lines.append(f"\n📊 آخر النتائج:")
        for t in closed:
            icon = "✅" if t['result'] == 'WIN' else "❌"
            pct  = f"+{t['profit_percent']:.2f}%" if t['profit_percent'] > 0 else f"{t['profit_percent']:.2f}%"
            usdt = f"{t['profit_usdt']:.2f}" if t['profit_usdt'] else "0.00"
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

async def cmd_performance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أداء Claude ونسبة القبول/الرفض"""
    total = await Database.fetchval("SELECT COUNT(*) FROM signals") or 0
    approved = await Database.fetchval("SELECT COUNT(*) FROM signals WHERE claude_approved = true") or 0
    rejected = await Database.fetchval("SELECT COUNT(*) FROM signals WHERE claude_approved = false") or 0
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

    approval_rate = f"{(approved/total*100):.1f}%" if total > 0 else "0%"

    await update.message.reply_text(
        f"🏆 أداء النظام\n"
        f"{'─'*28}\n\n"
        f"🤖 مراجعة Claude:\n"
        f"  إجمالي الإشارات: {total}\n"
        f"  ✅ موافق عليها: {approved} ({approval_rate})\n"
        f"  ❌ مرفوضة: {rejected}\n"
        f"  📤 مرسلة: {sent}\n\n"
        f"📊 نتائج الصفقات (7 أيام):\n"
        f"  أرباح: {wins} ✅\n"
        f"  خسائر: {losses} ❌\n"
        f"  نسبة النجاح: {win_rate}\n"
        f"{'─'*28}"
    )


async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """آخر 5 إشارات مع حالتها"""
    signals = await Database.fetch("""
        SELECT symbol, timeframe, score, claude_approved, telegram_sent,
               signal_time, claude_comment
        FROM signals
        ORDER BY signal_time DESC
        LIMIT 5
    """)

    if not signals:
        await update.message.reply_text("📡 لا توجد إشارات بعد")
        return

    lines = ["📡 آخر الإشارات\n" + "─"*28]
    for s in signals:
        claude_icon = "✅" if s['claude_approved'] else "❌"
        sent_icon = "📤" if s['telegram_sent'] else "⏳"
        time_str = s['signal_time'].strftime("%H:%M") if s['signal_time'] else "؟"
        lines.append(
            f"\n{sent_icon} {s['symbol']} [{s['timeframe']}]\n"
            f"  ⭐ {s['score']}/10 | Claude: {claude_icon} | {time_str}\n"
            f"  💬 {(s['claude_comment'] or '')[:60]}"
        )

    await update.message.reply_text("\n".join(lines))


async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ملخص يومي كامل"""
    risk = await Database.fetchrow(
        "SELECT * FROM risk_management WHERE date = CURRENT_DATE"
    )
    signals_today = await Database.fetchval(
        "SELECT COUNT(*) FROM signals WHERE signal_time::date = CURRENT_DATE"
    ) or 0
    approved_today = await Database.fetchval(
        "SELECT COUNT(*) FROM signals WHERE signal_time::date = CURRENT_DATE AND claude_approved = true"
    ) or 0
    rejected_today = await Database.fetchval(
        "SELECT COUNT(*) FROM signals WHERE signal_time::date = CURRENT_DATE AND claude_approved = false"
    ) or 0
    sent_today = await Database.fetchval(
        "SELECT COUNT(*) FROM signals WHERE signal_time::date = CURRENT_DATE AND telegram_sent = true"
    ) or 0

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
    status = "⏸️ موقوف" if (risk and risk['is_trading_paused']) else "✅ يعمل"
    wins = risk['wins'] if risk else 0
    losses = risk['losses'] if risk else 0

    best_line = f"  🥇 أفضل إشارة: {best['symbol']} ({best['score']}/10)" if best else "  لا توجد بعد"

    await update.message.reply_text(
        f"📅 ملخص اليوم\n"
        f"{'─'*28}\n\n"
        f"⚙️ الحالة: {status}\n"
        f"🌍 وضع السوق: {market_ar}\n\n"
        f"📊 الإشارات:\n"
        f"  إجمالي: {signals_today}\n"
        f"  ✅ وافق Claude: {approved_today}\n"
        f"  ❌ رفض Claude: {rejected_today}\n"
        f"  📤 أُرسلت: {sent_today}\n"
        f"{best_line}\n\n"
        f"💰 الصفقات:\n"
        f"  أرباح: {wins} ✅\n"
        f"  خسائر: {losses} ❌\n"
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
