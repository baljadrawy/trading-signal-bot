"""
Trade Tracker - يراقب الإشارات المرسلة ويسجل نتائجها تلقائياً
يتحقق من السعر كل 5 دقائق ويسجل: WIN / LOSS / EXPIRED
"""
import asyncio
import sys
import json
from datetime import datetime, timezone
sys.path.append('/app')

import aiohttp
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
from shared.alerts import send_alert

logger = setup_logger('trade_tracker')

# مدة انتهاء الصفقة بالساعات
TRADE_EXPIRY_HOURS = 48


async def main():
    logger.info("🚀 بدء تشغيل Trade Tracker...")
    await Database.connect()

    # إنشاء جدول active_trades إذا لم يوجد
    await Database.execute("""
        CREATE TABLE IF NOT EXISTS active_trades (
            id SERIAL PRIMARY KEY,
            signal_id INTEGER REFERENCES signals(id),
            symbol VARCHAR(20) NOT NULL,
            entry_price DECIMAL(20,8) NOT NULL,
            target_1 DECIMAL(20,8) NOT NULL,
            target_2 DECIMAL(20,8) NOT NULL,
            target_3 DECIMAL(20,8) NOT NULL,
            stop_loss DECIMAL(20,8) NOT NULL,
            timeframe VARCHAR(10),
            is_paper_trade BOOLEAN DEFAULT true,
            opened_at TIMESTAMP DEFAULT NOW(),
            highest_target_hit INTEGER DEFAULT 0,
            status VARCHAR(20) DEFAULT 'open'
        )
    """)

    consecutive_errors = 0

    try:
        while True:
            try:
                await close_blacklisted_trades()
                await enforce_max_open_trades()
                await track_open_trades()
                await register_new_signals()
                consecutive_errors = 0
                await asyncio.sleep(300)  # كل 5 دقائق

            except Exception as e:
                consecutive_errors += 1
                wait = min(60 * consecutive_errors, 300)
                logger.error(f"❌ خطأ في Trade Tracker ({consecutive_errors}): {e}")
                if consecutive_errors >= 3:
                    await send_alert(
                        f"Trade Tracker فشل {consecutive_errors} مرات متتالية\nالخطأ: {str(e)[:200]}",
                        level='critical', component='TradeTracker'
                    )
                await asyncio.sleep(wait)

    finally:
        await Database.disconnect()


async def close_blacklisted_trades():
    """إغلاق أي صفقة مفتوحة لعملة في القائمة السوداء (مرفوضة من المستخدم)"""
    blacklisted = await Database.fetch("""
        SELECT at.id, at.symbol
        FROM active_trades at
        JOIN symbol_blacklist bl ON at.symbol = bl.symbol
        WHERE at.status = 'open'
    """)
    for trade in blacklisted:
        await Database.execute(
            "UPDATE active_trades SET status = 'closed' WHERE id = $1",
            trade['id']
        )
        logger.info(f"🚫 إغلاق صفقة {trade['symbol']} - العملة في القائمة السوداء")


async def enforce_max_open_trades():
    """إذا الصفقات المفتوحة تجاوزت الحد الأقصى، أغلق الأقدم حتى نصل للحد"""
    if config.MAX_OPEN_TRADES <= 0:
        return

    open_trades = await Database.fetch("""
        SELECT id, symbol, opened_at
        FROM active_trades
        WHERE status = 'open'
        ORDER BY opened_at ASC
    """)

    excess = len(open_trades) - config.MAX_OPEN_TRADES
    if excess <= 0:
        return

    logger.warning(f"⚠️ {len(open_trades)} صفقة مفتوحة تتجاوز الحد {config.MAX_OPEN_TRADES} — إغلاق {excess} قديمة")

    for trade in open_trades[:excess]:
        current_price = await get_current_price(trade['symbol'])
        if current_price:
            trade_dict = dict(await Database.fetchrow(
                "SELECT * FROM active_trades WHERE id = $1", trade['id']
            ))
            entry = float(trade_dict['entry_price'])
            profit_pct = ((current_price - entry) / entry) * 100
            result = 'WIN' if current_price > entry else 'LOSS'
            await close_trade(trade_dict, result, profit_pct, current_price,
                              f"إغلاق تلقائي - تجاوز حد MAX_OPEN_TRADES={config.MAX_OPEN_TRADES}")
        else:
            await Database.execute(
                "UPDATE active_trades SET status = 'closed' WHERE id = $1", trade['id']
            )
            logger.info(f"🚫 إغلاق {trade['symbol']} (بدون سعر) - تجاوز الحد الأقصى")


async def register_new_signals():
    """تسجيل الإشارات المرسلة حديثاً كصفقات نشطة — صفقة واحدة لكل عملة"""
    # تحقق من حد الصفقات المفتوحة
    if config.MAX_OPEN_TRADES > 0:
        open_count = await Database.fetchval(
            "SELECT COUNT(*) FROM active_trades WHERE status = 'open'"
        ) or 0
        if open_count >= config.MAX_OPEN_TRADES:
            logger.info(f"⏸️ وصلنا للحد الأقصى للصفقات المفتوحة: {open_count}/{config.MAX_OPEN_TRADES}")
            return

    new_signals = await Database.fetch("""
        SELECT DISTINCT ON (s.symbol)
               s.id, s.symbol, s.entry_price, s.target_1, s.target_2, s.target_3,
               s.stop_loss, s.timeframe, s.is_paper_trade
        FROM signals s
        LEFT JOIN active_trades at ON s.id = at.signal_id
        WHERE s.telegram_sent = true
        AND s.claude_approved = true
        AND at.id IS NULL
        AND s.signal_time > NOW() - INTERVAL '2 hours'
        AND NOT EXISTS (
            SELECT 1 FROM active_trades at2
            WHERE at2.symbol = s.symbol AND at2.status = 'open'
        )
        AND NOT EXISTS (
            SELECT 1 FROM approval_requests ar
            WHERE ar.signal_id = s.id AND ar.status = 'rejected'
        )
        AND s.symbol NOT IN (
            SELECT symbol FROM symbol_blacklist
        )
        ORDER BY s.symbol, s.signal_time DESC
    """)

    for sig in new_signals:
        await Database.execute("""
            INSERT INTO active_trades
            (signal_id, symbol, entry_price, target_1, target_2, target_3,
             stop_loss, timeframe, is_paper_trade)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
            sig['id'], sig['symbol'],
            sig['entry_price'], sig['target_1'], sig['target_2'], sig['target_3'],
            sig['stop_loss'], sig['timeframe'], sig['is_paper_trade']
        )
        logger.info(f"📋 صفقة جديدة مسجلة: {sig['symbol']} @ {sig['entry_price']}")


async def track_open_trades():
    """متابعة الصفقات المفتوحة وتسجيل نتائجها"""
    open_trades = await Database.fetch("""
        SELECT * FROM active_trades
        WHERE status = 'open'
    """)

    if not open_trades:
        return

    logger.info(f"🔍 متابعة {len(open_trades)} صفقة مفتوحة...")

    for trade in open_trades:
        trade = dict(trade)
        current_price = await get_current_price(trade['symbol'])
        if not current_price:
            continue

        await evaluate_trade(trade, current_price)


async def evaluate_trade(trade: dict, current_price: float):
    """تقييم صفقة واحدة وتسجيل نتيجتها"""
    entry  = float(trade['entry_price'])
    stop   = float(trade['stop_loss'])
    t1     = float(trade['target_1'])
    t2     = float(trade['target_2'])
    t3     = float(trade['target_3'])
    symbol = trade['symbol']
    opened = trade['opened_at']

    # حساب مدة الصفقة
    now = datetime.now(timezone.utc)
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    hours_open = (now - opened).total_seconds() / 3600

    # تحقق من الأهداف
    target_hit = 0
    profit_pct = 0

    if current_price >= t3:
        target_hit = 3
        profit_pct = ((t3 - entry) / entry) * 100
    elif current_price >= t2:
        target_hit = 2
        profit_pct = ((t2 - entry) / entry) * 100
    elif current_price >= t1:
        target_hit = 1
        profit_pct = ((t1 - entry) / entry) * 100

    # تحديث أعلى هدف محقق
    if target_hit > trade['highest_target_hit']:
        await Database.execute(
            "UPDATE active_trades SET highest_target_hit = $1 WHERE id = $2",
            target_hit, trade['id']
        )
        logger.info(f"🎯 {symbol} وصل T{target_hit}! السعر: {current_price:.6f}")

    # تحقق من وقف الخسارة
    if current_price <= stop:
        loss_pct = ((current_price - entry) / entry) * 100
        await close_trade(trade, 'LOSS', loss_pct, current_price, f"ضرب Stop Loss عند {current_price:.6f}")
        return

    # إغلاق عند T3
    if current_price >= t3:
        await close_trade(trade, 'WIN', profit_pct, current_price, f"وصل الهدف T3 🎯🎯🎯")
        return

    # إغلاق بربح عند T1 بعد 24 ساعة
    if hours_open >= 24 and target_hit >= 1:
        await close_trade(trade, 'WIN', profit_pct, current_price,
                         f"انتهت 24 ساعة مع تحقيق T{target_hit}")
        return

    # انتهاء الصلاحية بدون نتيجة
    if hours_open >= TRADE_EXPIRY_HOURS:
        current_pct = ((current_price - entry) / entry) * 100
        result = 'WIN' if current_price > entry else 'LOSS'
        await close_trade(trade, result, current_pct, current_price,
                         f"انتهت {TRADE_EXPIRY_HOURS} ساعة - إغلاق تلقائي")
        return


async def close_trade(trade: dict, result: str, profit_pct: float,
                      exit_price: float, reason: str):
    """إغلاق الصفقة وتسجيل النتيجة"""
    symbol = trade['symbol']
    entry  = float(trade['entry_price'])
    profit_usdt = (profit_pct / 100) * config.TRADE_AMOUNT_USDT

    # تسجيل في trade_results
    hours_open = ((datetime.now(timezone.utc) - trade['opened_at'].replace(tzinfo=timezone.utc)
                   if trade['opened_at'].tzinfo is None
                   else datetime.now(timezone.utc) - trade['opened_at'])
                  .total_seconds() / 3600)

    await Database.execute("""
        INSERT INTO trade_results
        (signal_id, symbol, entry_price, exit_price, profit_percent,
         profit_usdt, result, exit_time, notes, duration_hours,
         target_reached, stop_hit)
        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8, $9, $10, $11)
    """,
        trade['signal_id'], symbol, entry, exit_price,
        round(profit_pct, 4), round(profit_usdt, 4),
        result, reason, round(hours_open, 2),
        trade['highest_target_hit'],
        result == 'LOSS' and exit_price <= float(trade['stop_loss'])
    )

    # تحديث حالة الصفقة
    await Database.execute(
        "UPDATE active_trades SET status = 'closed' WHERE id = $1",
        trade['id']
    )

    # تحديث risk_management
    if result == 'WIN':
        await Database.execute("""
            INSERT INTO risk_management (date, wins)
            VALUES (CURRENT_DATE, 1)
            ON CONFLICT (date) DO UPDATE
            SET wins = risk_management.wins + 1
        """)
    else:
        await Database.execute("""
            INSERT INTO risk_management (date, losses)
            VALUES (CURRENT_DATE, 1)
            ON CONFLICT (date) DO UPDATE
            SET losses = risk_management.losses + 1
        """)

    icon = "✅" if result == 'WIN' else "❌"
    logger.info(
        f"{icon} {symbol} | {result} | "
        f"ربح: {profit_pct:.2f}% ({profit_usdt:.2f} USDT) | {reason}"
    )


async def get_current_price(symbol: str) -> float:
    """جلب السعر الحالي من Binance"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                data = await resp.json()
                return float(data['price'])
    except Exception as e:
        logger.error(f"خطأ في جلب سعر {symbol}: {e}")
        return None


if __name__ == "__main__":
    asyncio.run(main())
