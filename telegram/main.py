"""
Telegram - يرسل الإشارات المعتمدة بالصيغة المطلوبة
ويراقب نتائج الصفقات
"""
import asyncio
import sys
sys.path.append('/app')

import telegram
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('telegram_sender')

MARKET_CONDITION_AR = {
    'bullish': 'صاعد',
    'bearish': 'هابط',
    'sideways': 'جانبي',
    'volatile': 'متقلب',
    'strong_bullish': 'صاعد قوي',
    'strong_bearish': 'هابط قوي',
}

async def main():
    logger.info("🚀 بدء تشغيل Telegram Sender...")
    await Database.connect()
    
    bot = telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)
    
    try:
        while True:
            try:
                # جلب الإشارات المعتمدة وغير المرسلة
                signals = await Database.fetch("""
                    SELECT id, symbol, timeframe, market_condition,
                           entry_price, target_1, target_2, target_3,
                           stop_loss, score, claude_comment, is_paper_trade
                    FROM signals
                    WHERE claude_approved = true
                    AND telegram_sent = false
                    AND signal_time > NOW() - INTERVAL '2 hours'
                    ORDER BY score DESC, signal_time DESC
                """)
                
                for signal in signals:
                    await send_signal(bot, dict(signal))
                    await asyncio.sleep(2)  # تجنب Rate Limiting
                
                # مراقبة الصفقات المفتوحة
                await monitor_open_trades(bot)
                
                await asyncio.sleep(15)
                
            except Exception as e:
                logger.error(f"❌ خطأ في Telegram Sender: {e}")
                await asyncio.sleep(30)
                
    finally:
        await Database.disconnect()

async def send_signal(bot: telegram.Bot, signal: dict):
    """إرسال إشارة بالصيغة المطلوبة"""
    try:
        market_ar = MARKET_CONDITION_AR.get(signal['market_condition'], signal['market_condition'])
        paper_badge = "📝 بيبر تريد | " if signal['is_paper_trade'] else ""
        
        # حساب الكمية بناءً على حجم الصفقة والسعر
        entry_price = float(signal['entry_price'])
        trade_amount = config.TRADE_AMOUNT_USDT
        quantity = trade_amount / entry_price

        # صيغة الرسالة
        message = (
            f"{'─'*30}\n"
            f"🎯 {signal['symbol']}\n"
            f"{paper_badge}وضع السوق: {market_ar}\n\n"
            f"💰 حجم الصفقة: {trade_amount} USDT\n"
            f"📊 الكمية: {format_quantity(quantity)}\n\n"
            f"📈 Buy: {format_price(signal['entry_price'])}\n\n"
            f"🎯 Target:\n"
            f"  T1: {format_price(signal['target_1'])}\n"
            f"  T2: {format_price(signal['target_2'])}\n"
            f"  T3: {format_price(signal['target_3'])}\n\n"
            f"🛑 Stop: {format_price(signal['stop_loss'])}\n\n"
            f"⏰ اغلاق {signal['timeframe']} أقل من\n"
            f"⭐ القوة: {signal['score']}/10\n"
        )
        
        if signal.get('claude_comment'):
            message += f"\n🤖 Claude: {signal['claude_comment']}\n"
        
        message += f"{'─'*30}"
        
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=message,
            parse_mode='HTML'
        )
        
        # تحديث حالة الإرسال
        await Database.execute(
            "UPDATE signals SET telegram_sent = true WHERE id = $1",
            signal['id']
        )
        
        logger.info(f"📤 تم إرسال إشارة {signal['symbol']} بنجاح")
        
    except Exception as e:
        logger.error(f"❌ فشل إرسال إشارة {signal['symbol']}: {e}")

async def monitor_open_trades(bot: telegram.Bot):
    """مراقبة الصفقات المفتوحة وإرسال تحديثات"""
    try:
        # جلب الإشارات المرسلة وغير المغلقة
        open_signals = await Database.fetch("""
            SELECT s.id, s.symbol, s.entry_price, s.target_1, s.stop_loss,
                   s.signal_time
            FROM signals s
            LEFT JOIN trade_results tr ON s.id = tr.signal_id
            WHERE s.telegram_sent = true
            AND tr.id IS NULL
            AND s.signal_time > NOW() - INTERVAL '24 hours'
        """)
        
        # هنا نضيف مراقبة السعر الحالي مستقبلاً
        # في الإصدار الأول نترك هذا للبوت المنفذ
        
    except Exception as e:
        logger.error(f"خطأ في مراقبة الصفقات: {e}")

def format_quantity(quantity: float) -> str:
    """تنسيق الكمية بشكل مناسب"""
    if quantity >= 1000:
        return f"{quantity:,.0f}"
    elif quantity >= 1:
        return f"{quantity:.4f}"
    elif quantity >= 0.001:
        return f"{quantity:.6f}"
    else:
        return f"{quantity:.8f}"

def format_price(price) -> str:
    """تنسيق السعر بشكل مناسب"""
    price = float(price)
    if price < 0.00001:
        return f"{price:.8f}"
    elif price < 0.01:
        return f"{price:.7f}"
    elif price < 1:
        return f"{price:.6f}"
    elif price < 100:
        return f"{price:.4f}"
    else:
        return f"{price:.2f}"

if __name__ == "__main__":
    asyncio.run(main())
