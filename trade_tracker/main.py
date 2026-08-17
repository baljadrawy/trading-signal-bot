"""
Trade Tracker - يراقب الإشارات المرسلة ويسجل نتائجها تلقائياً
يتحقق من السعر كل 5 دقائق ويسجل: WIN / LOSS / EXPIRED
يستخدم shared.triple_barrier كمصدر حقيقة واحد لمنطق الخروج.
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
from shared.retry_utils import format_error, is_network_error, compute_backoff, alert_threshold
from shared.health import mark_started, mark_success, mark_failure
from shared.schema import require_schema
from shared.outbox import worker_id, claim, ack, fail
from shared.candle import candle_interval_case_sql
from shared.triple_barrier import (
    create_config_from_trade,
    create_state_from_trade,
    step_barrier,
    barrier_status_summary,
    modeled_stop_exit,
    TripleBarrierConfig,
    TripleBarrierState,
)

logger = setup_logger('trade_tracker')

# مدة انتهاء الصفقة بالساعات — يُستخدم في TripleBarrierConfig تلقائياً
TRADE_EXPIRY_HOURS = 48

# نسبة الـ trailing stop — يُستخدم في TripleBarrierConfig تلقائياً
TRAIL_STOP_PCT = 2.5


async def main():
    logger.info("🚀 بدء تشغيل Trade Tracker...")
    await Database.connect()
    await require_schema('trade_tracker')
    await mark_started('trade_tracker')

    consecutive_errors = 0
    owner = worker_id('trade_tracker')

    try:
        while True:
            try:
                await close_blacklisted_trades()
                await enforce_max_open_trades()
                await track_open_trades()
                delivery_events = await claim('signal.delivered', owner, limit=50)
                await register_new_signals()
                for event in delivery_events:
                    active = await Database.fetchval(
                        "SELECT 1 FROM active_trades WHERE signal_id=$1",
                        event['aggregate_id'])
                    if active:
                        await ack(event['id'], owner)
                        continue
                    terminal = await Database.fetchval("""
                        SELECT 1 FROM signals s
                        WHERE s.id=$1 AND (
                            NOT s.telegram_sent OR NOT s.claude_approved
                            OR s.signal_time <= NOW()-INTERVAL '2 hours'
                            OR EXISTS (SELECT 1 FROM symbol_blacklist b WHERE b.symbol=s.symbol)
                            OR EXISTS (SELECT 1 FROM approval_requests ar
                                       WHERE ar.signal_id=s.id AND ar.status='rejected'))
                        """, event['aggregate_id'])
                    if terminal:
                        await ack(event['id'], owner)
                    else:
                        await fail(event['id'], owner,
                                   RuntimeError('trade registration deferred'), 300)
                consecutive_errors = 0
                await mark_success('trade_tracker', {
                    'delivery_events': len(delivery_events)})
                await asyncio.sleep(300)  # كل 5 دقائق

            except Exception as e:
                consecutive_errors += 1
                await mark_failure('trade_tracker', e)
                network = is_network_error(e)
                wait = compute_backoff(consecutive_errors, network)
                msg = f"❌ خطأ في Trade Tracker ({consecutive_errors}): {format_error(e)}"
                if network:
                    logger.warning(msg)
                else:
                    logger.error(msg)
                if consecutive_errors >= alert_threshold(network):
                    await send_alert(
                        f"Trade Tracker فشل {consecutive_errors} مرات متتالية\nالخطأ: {format_error(e)[:200]}",
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
    """إذا الصفقات المفتوحة تجاوزت الحد الأقصى، أغلق الأكثر خسارة حتى نصل للحد.
    المنطق: نتخلص من الصفقات الخاسرة أولاً (يحرر رأس المال ويقطع النزيف)،
    بدلاً من إغلاق الأقدم التي قد تكون على وشك تحقيق هدف.
    """
    if config.MAX_OPEN_TRADES <= 0:
        return

    open_trades = await Database.fetch("""
        SELECT id, symbol, entry_price, opened_at
        FROM active_trades
        WHERE status = 'open'
    """)

    excess = len(open_trades) - config.MAX_OPEN_TRADES
    if excess <= 0:
        return

    logger.warning(f"⚠️ {len(open_trades)} صفقة مفتوحة تتجاوز الحد {config.MAX_OPEN_TRADES} — إغلاق {excess} الأكثر خسارة")

    # جلب الأسعار الحالية وترتيب الصفقات من الأكثر خسارة للأقل
    trades_with_pnl = []
    for trade in open_trades:
        current_price = await get_current_price(trade['symbol'])
        if current_price:
            entry = float(trade['entry_price'])
            pnl_pct = ((current_price - entry) / entry) * 100
            trades_with_pnl.append((pnl_pct, dict(trade), current_price))
        else:
            # إذا لم نجد السعر نضعه كأسوأ حالة (يُغلق أولاً)
            trades_with_pnl.append((float('-inf'), dict(trade), None))

    # ترتيب من الأكثر خسارة (أدنى pnl) للأقل
    trades_with_pnl.sort(key=lambda x: x[0])

    for pnl_pct, trade_info, current_price in trades_with_pnl[:excess]:
        if current_price:
            trade_dict = dict(await Database.fetchrow(
                "SELECT * FROM active_trades WHERE id = $1", trade_info['id']
            ))
            result = 'WIN' if pnl_pct > 0 else 'LOSS'
            await close_trade(trade_dict, result, pnl_pct, current_price,
                              f"إغلاق تلقائي - تجاوز حد MAX_OPEN_TRADES={config.MAX_OPEN_TRADES} (خسارة: {pnl_pct:.2f}%)")
        else:
            await Database.execute(
                "UPDATE active_trades SET status = 'closed' WHERE id = $1", trade_info['id']
            )
            logger.info(f"🚫 إغلاق {trade_info['symbol']} (بدون سعر) - تجاوز الحد الأقصى")


async def register_new_signals():
    """تسجيل الإشارات المرسلة حديثاً كصفقات نشطة — صفقة واحدة لكل (عملة، إطار) لكل شمعة"""
    # تحقق من حد الصفقات المفتوحة
    if config.MAX_OPEN_TRADES > 0:
        open_count = await Database.fetchval(
            "SELECT COUNT(*) FROM active_trades WHERE status = 'open'"
        ) or 0
        if open_count >= config.MAX_OPEN_TRADES:
            logger.info(f"⏸️ وصلنا للحد الأقصى للصفقات المفتوحة: {open_count}/{config.MAX_OPEN_TRADES}")
            return

    candle_case = candle_interval_case_sql('s.timeframe')
    new_signals = await Database.fetch(f"""
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
            -- صفقة واحدة لكل (رمز، إطار) خلال فترة الشمعة — يمنع عدّ نفس الإعداد المُعاد إطلاقه مراراً
            SELECT 1 FROM active_trades at3
            WHERE at3.symbol = s.symbol
              AND at3.timeframe = s.timeframe
              AND at3.opened_at > NOW() - ({candle_case})
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
        if config.MAX_OPEN_TRADES > 0:
            open_count = await Database.fetchval(
                "SELECT COUNT(*) FROM active_trades WHERE status = 'open'"
            ) or 0
            if open_count >= config.MAX_OPEN_TRADES:
                logger.info(f"⏸️ توقف تسجيل إشارات جديدة — وصلنا الحد: {open_count}/{config.MAX_OPEN_TRADES}")
                break

        await Database.execute("""
            INSERT INTO active_trades
            (signal_id, symbol, entry_price, target_1, target_2, target_3,
             stop_loss, timeframe, is_paper_trade)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (signal_id) WHERE signal_id IS NOT NULL DO NOTHING
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
    """تقييم صفقة واحدة وتسجيل نتيجتها — يستخدم shared.triple_barrier (مصدر حقيقة واحد)

    الجزء الخامس من الباكتيستر (2026-05-16): تم نقل منطق الخروج كاملاً إلى
    shared/triple_barrier.py — trade_tracker والباكتيستر يستوردان نفس الكود.
    """
    symbol = trade['symbol']
    entry  = float(trade['entry_price'])

    # حساب مدة الصفقة
    now    = datetime.now(timezone.utc)
    opened = trade['opened_at']
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    hours_open = (now - opened).total_seconds() / 3600

    # بناء Config و State من صف DB
    cfg   = create_config_from_trade(trade, trade_amount=config.TRADE_AMOUNT_USDT)
    state = create_state_from_trade(trade)
    # ضبط ساعات الفتح الحالية (تُحسب من DB)
    state.hours_open = hours_open

    # تحديث القمة بالسعر الحالي (فحص نقطة في الزمن — لا شمعة كاملة)
    if current_price > state.peak:
        state.peak = current_price

    # تحديث الأهداف بالسعر الحالي
    prev_highest = state.highest_target
    if current_price >= cfg.target_3 and state.highest_target < 3:
        state.highest_target = 3
    elif current_price >= cfg.target_2 and state.highest_target < 2:
        state.highest_target = 2
    elif current_price >= cfg.target_1 and state.highest_target < 1:
        state.highest_target = 1

    # تسجيل الأهداف الجديدة في DB
    if state.highest_target > prev_highest:
        await Database.execute(
            "UPDATE active_trades SET highest_target_hit = $1 WHERE id = $2",
            state.highest_target, trade['id']
        )
        logger.info(f"🎯 {symbol} وصل T{state.highest_target}! السعر: {current_price:.6f}")

    # تحديث peak_price في DB
    stored_peak = float(trade.get('peak_price') or entry)
    if state.peak > stored_peak:
        await Database.execute(
            "UPDATE active_trades SET peak_price = $1 WHERE id = $2",
            state.peak, trade['id']
        )

    # احسب الستوب الفعّال وتحقق منه (المحاكاة الحيّة — نقطة واحدة في الزمن)
    eff_stop, stop_label = state.effective_stop(cfg)

    # فحص T3 — إغلاق فوري
    if state.highest_target == 3:
        profit_pct  = ((cfg.target_3 - entry) / entry) * 100
        profit_usdt = (profit_pct / 100) * config.TRADE_AMOUNT_USDT
        await close_trade_barrier(trade, 'WIN', profit_pct, profit_usdt, cfg.target_3, 'T3', state.highest_target, False)
        return

    # فحص ضرب الستوب الديناميكي — نمذجة التعبئة عند مستوى الستوب لا عند سعر الاستطلاع المتجاوز
    if current_price <= eff_stop:
        fill_price, profit_pct = modeled_stop_exit(entry, eff_stop, config.STOP_SLIPPAGE)
        profit_usdt = (profit_pct / 100) * config.TRADE_AMOUNT_USDT
        is_win      = fill_price > entry
        if state.highest_target >= 2:
            reason = 'trailing_stop'
        elif state.highest_target == 1:
            reason = 'break_even'
        else:
            reason = 'stop_loss'
        original_stop_hit = (not is_win) and (fill_price <= cfg.stop_loss)
        await close_trade_barrier(
            trade, 'WIN' if is_win else 'LOSS',
            profit_pct, profit_usdt, fill_price,
            f"{reason} ({stop_label})", state.highest_target, original_stop_hit
        )
        return

    # صفقة عالقة عند T1 فقط بعد 24 ساعة
    if hours_open >= 24 and state.highest_target == 1:
        profit_pct  = ((current_price - entry) / entry) * 100
        profit_usdt = (profit_pct / 100) * config.TRADE_AMOUNT_USDT
        is_win      = current_price > entry
        await close_trade_barrier(
            trade, 'WIN' if is_win else 'LOSS',
            profit_pct, profit_usdt, current_price,
            'T1_expired_24h', state.highest_target, False
        )
        return

    # صفقة لم تصل حتى T1 بعد 24 ساعة — أغلقها
    if hours_open >= 24 and state.highest_target == 0:
        profit_pct  = ((current_price - entry) / entry) * 100
        profit_usdt = (profit_pct / 100) * config.TRADE_AMOUNT_USDT
        is_win      = current_price > entry
        await close_trade_barrier(
            trade, 'WIN' if is_win else 'LOSS',
            profit_pct, profit_usdt, current_price,
            'no_T1_expired_24h', state.highest_target, False
        )
        return

    # انتهاء الصلاحية الكلية
    if hours_open >= TRADE_EXPIRY_HOURS:
        profit_pct  = ((current_price - entry) / entry) * 100
        profit_usdt = (profit_pct / 100) * config.TRADE_AMOUNT_USDT
        is_win      = current_price > entry
        await close_trade_barrier(
            trade, 'WIN' if is_win else 'LOSS',
            profit_pct, profit_usdt, current_price,
            f'expired_{TRADE_EXPIRY_HOURS}h', state.highest_target, False
        )
        return


async def close_trade_barrier(
    trade: dict, result: str, profit_pct: float, profit_usdt: float,
    exit_price: float, reason: str, target_reached: int, stop_hit: bool
):
    """إغلاق الصفقة وتسجيل النتيجة — مع stop_hit الصحيح من TripleBarrier"""
    symbol = trade['symbol']
    entry  = float(trade['entry_price'])

    hours_open = ((datetime.now(timezone.utc) - trade['opened_at'].replace(tzinfo=timezone.utc)
                   if trade['opened_at'].tzinfo is None
                   else datetime.now(timezone.utc) - trade['opened_at'])
                  .total_seconds() / 3600)

    async with Database.acquire() as conn:
        async with conn.transaction():
            inserted = await conn.fetchval("""
                INSERT INTO trade_results
                (signal_id, symbol, entry_price, exit_price, profit_percent,
                 profit_usdt, result, exit_time, notes, duration_hours,
                 target_reached, stop_hit)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8, $9, $10, $11)
                ON CONFLICT (signal_id) WHERE signal_id IS NOT NULL DO NOTHING
                RETURNING id
            """,
                trade['signal_id'], symbol, entry, exit_price,
                round(profit_pct, 4), round(profit_usdt, 4),
                result, reason, round(hours_open, 2), target_reached, stop_hit)
            await conn.execute(
                "UPDATE active_trades SET status='closed' WHERE id=$1", trade['id'])
            if inserted:
                column = 'wins' if result == 'WIN' else 'losses'
                await conn.execute(f"""
                    INSERT INTO risk_management (date, {column})
                    VALUES (CURRENT_DATE, 1)
                    ON CONFLICT (date) DO UPDATE
                    SET {column}=risk_management.{column}+1
                """)

    icon = "✅" if result == 'WIN' else "❌"
    logger.info(
        f"{icon} {symbol} | {result} | "
        f"ربح: {profit_pct:.2f}% ({profit_usdt:.2f} USDT) | {reason}"
    )


async def close_trade(trade: dict, result: str, profit_pct: float,
                      exit_price: float, reason: str):
    """إغلاق الصفقة — wrapper لـ enforce_max_open_trades و close_blacklisted_trades"""
    symbol      = trade['symbol']
    entry       = float(trade['entry_price'])
    profit_usdt = (profit_pct / 100) * config.TRADE_AMOUNT_USDT
    stop_hit    = result == 'LOSS' and exit_price <= float(trade['stop_loss'])
    target_hit  = int(trade.get('highest_target_hit') or 0)

    await close_trade_barrier(
        trade, result, profit_pct, profit_usdt,
        exit_price, reason, target_hit, stop_hit
    )


async def get_current_price(symbol: str) -> float:
    """جلب السعر الحالي من Binance"""
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
        logger.error(f"خطأ في جلب سعر {symbol}: {format_error(e)}")
        return None


if __name__ == "__main__":
    asyncio.run(main())
