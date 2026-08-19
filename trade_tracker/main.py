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
from shared.outbox import worker_id, claim, ack, fail, enqueue
from shared.candle import candle_interval_case_sql
from shared.execution import rebase_long_bracket
from shared.entry_execution import decide_long_entry
from shared.partial_exits import aggregate_close, fills_between
from shared.signal_stop import candle_invalidated
from shared.risk_management import RiskLimits, RiskSnapshot, evaluate_new_trade
from shared.trading_state import get_pause_state
from shared.triple_barrier import (
    create_config_from_trade,
    create_state_from_trade,
    step_barrier,
    barrier_status_summary,
    TripleBarrierConfig,
    TripleBarrierState,
    expiry_policy_for_timeframe,
)
try:
    from .binance_price_stream import BinancePriceStream
except ImportError:  # container executes /app/main.py as a top-level module
    from binance_price_stream import BinancePriceStream

logger = setup_logger('trade_tracker')

# مدة انتهاء الصفقة بالساعات — يُستخدم في TripleBarrierConfig تلقائياً
TRADE_EXPIRY_HOURS = 48

# نسبة الـ trailing stop — يُستخدم في TripleBarrierConfig تلقائياً
TRAIL_STOP_PCT = 2.5

_trade_locks: dict[int, asyncio.Lock] = {}
_closing: set[int] = set()
_min_notional_cache: dict[str, float] = {}
price_stream: BinancePriceStream | None = None


async def main():
    logger.info("🚀 بدء تشغيل Trade Tracker...")
    await Database.connect()
    await require_schema('trade_tracker')
    await mark_started('trade_tracker')

    consecutive_errors = 0
    owner = worker_id('trade_tracker')
    global price_stream
    stream_task = None
    if config.PRICE_STREAM_ENABLED:
        price_stream = BinancePriceStream(
            symbol_provider=get_open_symbols,
            on_price=handle_stream_price,
            logger=logger,
            refresh_seconds=config.PRICE_STREAM_REFRESH_SECONDS,
            alert_after_seconds=config.PRICE_STREAM_ALERT_AFTER_SECONDS,
            on_status=publish_stream_status,
        )
        stream_task = asyncio.create_task(price_stream.run(), name='binance-price-stream')
    await publish_recovery_event()

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
                    'delivery_events': len(delivery_events),
                    'price_stream': price_stream.snapshot() if price_stream else None})
                # REST backup checker: catches missed WebSocket events and fills
                # waiting limit candidates without making REST the primary feed.
                await asyncio.sleep(config.PRICE_BACKUP_CHECK_SECONDS)

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
        if stream_task:
            stream_task.cancel()
            await asyncio.gather(stream_task, return_exceptions=True)
        await Database.disconnect()


async def get_open_symbols() -> set[str]:
    rows = await Database.fetch(
        "SELECT DISTINCT symbol FROM active_trades WHERE status='open'")
    return {row['symbol'] for row in rows}


async def handle_stream_price(symbol: str, price: float):
    """Evaluate every open trade for one symbol from an ordered WebSocket tick."""
    rows = await Database.fetch(
        "SELECT * FROM active_trades WHERE status='open' AND symbol=$1", symbol)
    for row in rows:
        await evaluate_trade_safely(dict(row), price, source='websocket')


async def _publish_runtime_event(event_type: str, payload: dict):
    async with Database.acquire() as conn:
        async with conn.transaction():
            key = await conn.fetchval(
                "SELECT nextval(pg_get_serial_sequence('outbox_events','id'))")
            await enqueue(conn, event_type, 'runtime_transition', key, payload)


async def publish_stream_status(status: str, details: dict):
    await _publish_runtime_event(f'price_stream.{status}', details)


async def publish_recovery_event():
    rows = await Database.fetch(
        "SELECT id,symbol FROM active_trades WHERE status='open' ORDER BY id")
    if rows:
        await _publish_runtime_event('tracker.recovered', {
            'count': len(rows),
            'symbols': [row['symbol'] for row in rows],
            'websocket_enabled': config.PRICE_STREAM_ENABLED,
        })


async def close_blacklisted_trades():
    """إغلاق أي صفقة مفتوحة لعملة في القائمة السوداء (مرفوضة من المستخدم)"""
    blacklisted = await Database.fetch("""
        SELECT at.*
        FROM active_trades at
        JOIN symbol_blacklist bl ON at.symbol = bl.symbol
        WHERE at.status = 'open'
    """)
    for trade in blacklisted:
        current_price = await get_current_price(trade['symbol'])
        if not current_price:
            logger.warning(
                f"تعذر إغلاق {trade['symbol']} المدرجة في القائمة السوداء: لا يوجد سعر")
            continue
        trade = dict(trade)
        entry = float(trade['entry_price'])
        pnl_pct = ((current_price - entry) / entry) * 100
        result = 'WIN' if pnl_pct > 0 else 'LOSS'
        await close_trade(
            trade, result, pnl_pct, current_price,
            'إغلاق تلقائي - أُضيف الرمز إلى القائمة السوداء')


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
            # لا نُحوّل المركز إلى مغلق دون سعر ونتيجة؛ وإلا يختفي من المتابعة
            # ولا يمكن إنشاء إشعار إغلاق محاسبي صحيح.
            logger.error(
                f"تعذر إغلاق {trade_info['symbol']} لتجاوز الحد: لا يوجد سعر؛ ستبقى تحت المتابعة")


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
               s.stop_loss, s.timeframe, s.is_paper_trade, s.trade_type,
               s.features_snapshot
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

        fill_entry = await get_current_price(sig['symbol'])
        if not fill_entry:
            logger.warning(f"تعذر تسجيل {sig['symbol']}: لا يوجد سعر تعبئة حالي")
            continue

        features = sig['features_snapshot'] or {}
        if isinstance(features, str):
            features = json.loads(features)
        entry_decision = decide_long_entry(
            trade_type=sig['trade_type'],
            planned_entry=float(sig['entry_price']),
            current_price=fill_entry,
            stop_loss=float(sig['stop_loss']),
            invalidation_price=features.get('stop_invalidation'),
        )
        if entry_decision.action == 'reject':
            logger.warning(
                f"⛔ رفض تعبئة {sig['symbol']}: {entry_decision.reason} "
                f"(الآن={fill_entry}, stop={sig['stop_loss']})")
            # Make the rejection terminal without mislabelling it as a model decision.
            await Database.execute(
                "UPDATE signals SET telegram_sent=false WHERE id=$1", sig['id'])
            continue
        if entry_decision.action == 'limit_wait':
            logger.info(
                f"⏳ Limit paper order {sig['symbol']} @ {entry_decision.order_price}; "
                f"السعر الحالي {fill_entry} — لا نطارد السعر")
            continue
        min_notional = await get_min_notional(sig['symbol'])

        macro_state = await Database.fetchval(
            "SELECT COALESCE(macro_snapshot->>'usdtd_trend', market_condition) FROM signals WHERE id=$1",
            sig['id'])
        trade_type = await Database.fetchval(
            "SELECT trade_type FROM signals WHERE id=$1", sig['id'])
        risk_decision = await assess_new_trade_risk(
            sig['symbol'], trade_type=trade_type, regime=macro_state)
        await record_risk_decision(risk_decision)
        if not risk_decision.allowed:
            logger.warning(
                f"⛔ رفض صفقة {sig['symbol']} بواسطة حارس المخاطر: "
                f"{risk_decision.reason} (daily={risk_decision.daily_pnl_pct:.2f}%, "
                f"weekly={risk_decision.weekly_pnl_pct:.2f}%, "
                f"drawdown={risk_decision.drawdown_pct:.2f}%)")
            continue
        try:
            bracket = rebase_long_bracket(
                float(sig['entry_price']), fill_entry,
                float(sig['target_1']), float(sig['target_2']), float(sig['target_3']),
                float(sig['stop_loss']),
            )
        except ValueError as exc:
            logger.error(f"رفض bracket غير صالح لـ {sig['symbol']}: {exc}")
            continue

        expiry_h, t1_expiry_h, no_t1_expiry_h = expiry_policy_for_timeframe(sig['timeframe'])
        async with Database.acquire() as conn:
            async with conn.transaction():
                trade_id = await conn.fetchval("""
                    INSERT INTO active_trades
                    (signal_id, symbol, entry_price, target_1, target_2, target_3,
                     stop_loss, timeframe, is_paper_trade, entry_order_type,
                     stop_policy, stop_invalidation, exit_policy_version,
                     min_order_notional_usdt, expiry_policy_version,
                     expiry_h, t1_expiry_h, no_t1_expiry_h)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                            $15, $16, $17, $18)
                    ON CONFLICT (signal_id) WHERE signal_id IS NOT NULL DO NOTHING
                    RETURNING id
                """,
                    sig['id'], sig['symbol'],
                    bracket['entry_price'], bracket['target_1'], bracket['target_2'], bracket['target_3'],
                    bracket['stop_loss'], sig['timeframe'], sig['is_paper_trade'],
                    entry_decision.action, features.get('stop_policy'),
                    (float(features['stop_invalidation'])
                     * fill_entry / float(sig['entry_price'])
                     if features.get('stop_invalidation') else bracket['stop_loss']),
                    'partial_25_50_25_v1', min_notional, 'timeframe_v1',
                    expiry_h, t1_expiry_h, no_t1_expiry_h)
                if trade_id:
                    await enqueue(conn, 'trade.opened', 'active_trade', trade_id,
                                  {'active_trade_id': trade_id})
        if trade_id:
            drift_pct = (fill_entry / float(sig['entry_price']) - 1) * 100
            logger.info(
                f"📋 صفقة جديدة مسجلة: {sig['symbol']} @ {fill_entry} "
                f"(سعر الإشارة {sig['entry_price']}، drift {drift_pct:+.3f}%)")


async def assess_new_trade_risk(symbol: str, trade_type: str | None = None,
                                regime: str | None = None):
    """Build a UTC, net-of-cost portfolio snapshot and evaluate one admission."""
    risk_start = datetime.fromisoformat(config.LEARNING_CLEAN_START.replace('Z', '+00:00'))
    if risk_start.tzinfo is None:
        risk_start = risk_start.replace(tzinfo=timezone.utc)
    results = await Database.fetch("""
        SELECT profit_usdt, result, exit_time
        FROM trade_results
        WHERE exit_time >= $1::timestamptz
        ORDER BY exit_time, id
    """, risk_start)
    open_trades = await Database.fetch("""
        SELECT at.symbol, at.entry_price, s.trade_type,
               COALESCE(s.macro_snapshot->>'usdtd_trend', s.market_condition) AS regime
        FROM active_trades at
        LEFT JOIN signals s ON s.id=at.signal_id
        WHERE at.status='open'
    """)
    is_paused, pause_reason = await get_pause_state()

    now = datetime.now(timezone.utc)
    week_start = now.date()
    week_start = week_start.fromordinal(week_start.toordinal() - week_start.weekday())
    fee_usdt = config.TRADE_AMOUNT_USDT * config.FEE_ROUNDTRIP_PCT / 100.0
    cumulative = 0.0
    peak = config.RISK_CAPITAL_USDT
    daily = weekly = 0.0
    net_results = []
    for row in results:
        net = float(row['profit_usdt']) - fee_usdt
        cumulative += net
        peak = max(peak, config.RISK_CAPITAL_USDT + cumulative)
        exit_time = row['exit_time']
        if exit_time.tzinfo is None:
            exit_time = exit_time.replace(tzinfo=timezone.utc)
        if exit_time.date() == now.date():
            daily += net
        if exit_time.date() >= week_start:
            weekly += net
        net_results.append(net)

    consecutive_losses = 0
    for net in reversed(net_results):
        if net >= 0:
            break
        consecutive_losses += 1

    unrealized = 0.0
    for trade in open_trades:
        price = await get_current_price(trade['symbol'])
        if not price:
            unrealized = float('nan')  # Missing market state must fail closed.
            break
        entry = float(trade['entry_price'])
        unrealized += ((price / entry) - 1.0) * config.TRADE_AMOUNT_USDT - fee_usdt

    limits = RiskLimits(
        capital_usdt=config.RISK_CAPITAL_USDT,
        trade_amount_usdt=config.TRADE_AMOUNT_USDT,
        max_open_trades=min(config.MAX_OPEN_TRADES, config.RISK_CANARY_MAX_OPEN_TRADES),
        max_gross_exposure_pct=config.MAX_GROSS_EXPOSURE_PERCENT,
        max_symbol_exposure_pct=config.MAX_SYMBOL_EXPOSURE_PERCENT,
        max_strategy_exposure_pct=config.MAX_STRATEGY_EXPOSURE_PERCENT,
        max_regime_exposure_pct=config.MAX_REGIME_EXPOSURE_PERCENT,
        max_daily_loss_pct=config.MAX_DAILY_LOSS_PERCENT,
        max_weekly_loss_pct=config.MAX_WEEKLY_LOSS_PERCENT,
        max_drawdown_pct=config.MAX_DRAWDOWN_PERCENT,
        loss_halt_count=config.STOP_ON_CONSECUTIVE_LOSSES,
    )
    return evaluate_new_trade(RiskSnapshot(
        realized_total_usdt=cumulative,
        daily_pnl_usdt=daily,
        weekly_pnl_usdt=weekly,
        unrealized_pnl_usdt=unrealized,
        peak_equity_usdt=peak,
        open_count=len(open_trades),
        symbol_open_count=sum(1 for t in open_trades if t['symbol'] == symbol),
        consecutive_losses=consecutive_losses,
        strategy_open_count=sum(
            1 for t in open_trades if trade_type and t['trade_type'] == trade_type),
        regime_open_count=sum(
            1 for t in open_trades if regime and t['regime'] == regime),
        manually_paused=is_paused,
        manual_pause_reason=pause_reason,
    ), limits)


async def record_risk_decision(decision):
    """Expose the evaluated state to existing scanner/Telegram controls."""
    hard_halts = {
        'daily_loss_limit', 'weekly_loss_limit', 'max_drawdown_limit',
        'loss_streak_halt', 'invalid_risk_state',
    }
    paused = decision.reason in hard_halts
    async with Database.acquire() as conn:
        async with conn.transaction():
            prior = await conn.fetchrow("""
                SELECT is_trading_paused
                FROM risk_management
                WHERE is_trading_paused=true OR pause_reason='manual_resume'
                ORDER BY date DESC,id DESC LIMIT 1
                FOR UPDATE
            """)
            was_paused = bool(prior and prior['is_trading_paused'])
            risk_id = await conn.fetchval("""
                INSERT INTO risk_management
                    (date, daily_pnl_percent, consecutive_losses,
                     is_trading_paused, pause_reason)
                VALUES (CURRENT_DATE, $1, $2, $3, $4)
                ON CONFLICT (date) DO UPDATE SET
                    daily_pnl_percent=EXCLUDED.daily_pnl_percent,
                    consecutive_losses=EXCLUDED.consecutive_losses,
                    is_trading_paused=(risk_management.is_trading_paused
                                       OR EXCLUDED.is_trading_paused),
                    pause_reason=CASE WHEN EXCLUDED.is_trading_paused
                                      THEN EXCLUDED.pause_reason
                                      ELSE risk_management.pause_reason END
                RETURNING id
            """, decision.daily_pnl_pct, decision.consecutive_losses, paused,
                 f"risk:{decision.reason}" if paused else None)
            if paused and not was_paused:
                # Reserve a unique notification key so a later resume/re-halt on
                # the same day can produce a new, still-idempotent event.
                notification_key = await conn.fetchval(
                    "SELECT nextval(pg_get_serial_sequence('outbox_events','id'))")
                await enqueue(conn, 'risk.halted', 'risk_transition',
                              notification_key, {
                                  'risk_management_id': risk_id,
                                  'reason': decision.reason,
                                  'daily_pnl_pct': decision.daily_pnl_pct,
                                  'weekly_pnl_pct': decision.weekly_pnl_pct,
                                  'drawdown_pct': decision.drawdown_pct,
                                  'consecutive_losses': decision.consecutive_losses,
                                  'loss_halt_limit': config.STOP_ON_CONSECUTIVE_LOSSES,
                              })


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
        if (int(trade.get('highest_target_hit') or 0) == 0
                and trade.get('stop_invalidation')):
            candle = await get_last_closed_candle(
                trade['symbol'], trade.get('timeframe') or config.TIMEFRAME)
            opened_at = trade['opened_at']
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=timezone.utc)
            opened_ms = int(opened_at.timestamp() * 1000)
            if candle and candle_invalidated(
                    opened_ms=opened_ms, candle_close_ms=candle['close_time'],
                    candle_close=candle['close'],
                    invalidation_price=float(trade['stop_invalidation']),
                    highest_target=int(trade.get('highest_target_hit') or 0)):
                logger.warning(
                    f"🕯️ إبطال إشارة {trade['symbol']}: إغلاق "
                    f"{trade.get('timeframe')}={candle['close']} <= "
                    f"{trade['stop_invalidation']}")
                entry = float(trade['entry_price'])
                pnl_pct = (current_price / entry - 1) * 100
                await close_trade(
                    trade, 'WIN' if pnl_pct > 0 else 'LOSS', pnl_pct,
                    current_price, 'signal_candle_invalidation')
                continue
        await evaluate_trade_safely(trade, current_price, source='rest_backup')


async def evaluate_trade_safely(trade: dict, current_price: float,
                                source: str):
    """Serialize lifecycle changes per trade across WebSocket and REST paths."""
    trade_id = int(trade['id'])
    lock = _trade_locks.setdefault(trade_id, asyncio.Lock())
    async with lock:
        fresh = await Database.fetchrow(
            "SELECT * FROM active_trades WHERE id=$1 AND status='open'", trade_id)
        if not fresh:
            return
        await evaluate_trade(dict(fresh), current_price, source=source)


async def evaluate_trade(trade: dict, current_price: float,
                         source: str = 'rest_backup'):
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
    cfg   = create_config_from_trade(
        trade, trade_amount=config.TRADE_AMOUNT_USDT,
        stop_slippage=config.STOP_SLIPPAGE,
        roundtrip_cost=config.FEE_ROUNDTRIP_PCT / 100.0,
    )
    state = create_state_from_trade(trade)
    # ضبط ساعات الفتح الحالية (تُحسب من DB)
    state.hours_open = hours_open

    prev_highest = state.highest_target
    result = step_barrier(
        cfg, state, current_price, current_price, current_price, 0.0,
        stop_observation_price=current_price)

    # تسجيل الأهداف الجديدة في DB
    if state.highest_target > prev_highest:
        partial_fills = fills_between(
            previous_target=prev_highest,
            reached_target=state.highest_target,
            entry=entry,
            targets={1: float(trade['target_1']), 2: float(trade['target_2']),
                     3: float(trade['target_3'])},
            trade_amount=config.TRADE_AMOUNT_USDT,
            min_notional=float(
                trade.get('min_order_notional_usdt')
                or config.MIN_ORDER_NOTIONAL_USDT),
        ) if trade.get('exit_policy_version') == 'partial_25_50_25_v1' else []
        async with Database.acquire() as conn:
            async with conn.transaction():
                realized_pct = sum(fill.gross_pct_contribution for fill in partial_fills)
                realized_usdt = sum(fill.gross_usdt for fill in partial_fills)
                sold_fraction = sum(fill.fraction for fill in partial_fills)
                for fill in partial_fills:
                    await conn.execute("""
                        INSERT INTO trade_target_fills
                            (active_trade_id,signal_id,symbol,target_number,
                             fill_price,quantity_fraction,notional_usdt,
                             gross_profit_percent_contribution,gross_profit_usdt)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                        ON CONFLICT (active_trade_id,target_number) DO NOTHING
                    """, trade['id'], trade['signal_id'], symbol, fill.target,
                         fill.price, fill.fraction,
                         config.TRADE_AMOUNT_USDT * fill.fraction,
                         fill.gross_pct_contribution, fill.gross_usdt)
                await conn.execute("""
                    UPDATE active_trades SET
                        highest_target_hit=$1,
                        remaining_fraction=GREATEST(0,remaining_fraction-$2),
                        realized_profit_percent=realized_profit_percent+$3,
                        realized_profit_usdt=realized_profit_usdt+$4
                    WHERE id=$5
                """, state.highest_target, sold_fraction, realized_pct,
                     realized_usdt, trade['id'])
                # T3 يغلق فوراً؛ رسالة الإغلاق تكفي وتمنع إشعارين متتاليين لنفس الحدث.
                if state.highest_target < 3:
                    event_aggregate_id = int(trade['id']) * 10 + state.highest_target
                    effective_stop, _ = state.effective_stop(cfg)
                    previous_remaining = float(
                        trade.get('remaining_fraction')
                        if trade.get('remaining_fraction') is not None else 1.0)
                    await enqueue(conn, 'trade.target_hit', 'active_trade_target',
                                  event_aggregate_id, {
                                      'active_trade_id': trade['id'],
                                      'target': state.highest_target,
                                      'current_price': current_price,
                                      'effective_stop': effective_stop,
                                      'sold_fraction': sold_fraction,
                                      'remaining_fraction': max(
                                          0, previous_remaining - sold_fraction),
                                  })
        logger.info(
            f"🎯 {symbol} وصل T{state.highest_target} عبر {source}; "
            f"السعر={current_price:.6f}, شرائح={len(partial_fills)}")

    # تحديث peak_price في DB
    stored_peak = float(trade.get('peak_price') or entry)
    if state.peak > stored_peak:
        await Database.execute(
            "UPDATE active_trades SET peak_price = $1 WHERE id = $2",
            state.peak, trade['id']
        )

    if result is not None:
        # Reload partial accounting committed above (especially when the same
        # tick crosses T3) before producing the terminal aggregate result.
        refreshed = await Database.fetchrow(
            "SELECT * FROM active_trades WHERE id=$1", trade['id'])
        trade = dict(refreshed or trade)
        await close_trade_barrier(
            trade, result.result, result.profit_pct, result.profit_usdt,
            result.exit_price, result.exit_reason, result.target_reached, result.stop_hit,
        )
        return


async def close_trade_barrier(
    trade: dict, result: str, profit_pct: float, profit_usdt: float,
    exit_price: float, reason: str, target_reached: int, stop_hit: bool
):
    """إغلاق الصفقة وتسجيل النتيجة — مع stop_hit الصحيح من TripleBarrier"""
    trade_id = int(trade['id'])
    if trade_id in _closing:
        return
    _closing.add(trade_id)
    symbol = trade['symbol']
    entry  = float(trade['entry_price'])

    hours_open = ((datetime.now(timezone.utc) - trade['opened_at'].replace(tzinfo=timezone.utc)
                   if trade['opened_at'].tzinfo is None
                   else datetime.now(timezone.utc) - trade['opened_at'])
                  .total_seconds() / 3600)

    try:
        remaining_fraction = float(trade.get('remaining_fraction') or 0)
        realized_pct = float(trade.get('realized_profit_percent') or 0)
        realized_usdt = float(trade.get('realized_profit_usdt') or 0)
        profit_pct, profit_usdt = aggregate_close(
            entry=entry, final_exit=exit_price,
            trade_amount=config.TRADE_AMOUNT_USDT,
            realized_pct=realized_pct, realized_usdt=realized_usdt,
            remaining_fraction=remaining_fraction)
        # Weighted average exit keeps the legacy result row interpretable.
        sold_fraction = max(0.0, 1.0 - remaining_fraction)
        realized_exit_value = 0.0
        if sold_fraction > 0:
            fills = await Database.fetch(
                "SELECT fill_price,quantity_fraction FROM trade_target_fills "
                "WHERE active_trade_id=$1", trade_id)
            realized_exit_value = sum(
                float(f['fill_price']) * float(f['quantity_fraction']) for f in fills)
        weighted_exit = realized_exit_value + exit_price * remaining_fraction
        if sold_fraction + remaining_fraction <= 0:
            weighted_exit = exit_price

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
                    trade['signal_id'], symbol, entry, weighted_exit,
                    round(profit_pct, 4), round(profit_usdt, 4),
                    'WIN' if profit_usdt > 0 else 'LOSS', reason,
                    round(hours_open, 2), target_reached, stop_hit)
                await conn.execute(
                    "UPDATE active_trades SET status='closed',remaining_fraction=0 WHERE id=$1",
                    trade_id)
                if inserted:
                    final_result = 'WIN' if profit_usdt > 0 else 'LOSS'
                    column = 'wins' if final_result == 'WIN' else 'losses'
                    await conn.execute(f"""
                    INSERT INTO risk_management (date, {column})
                    VALUES (CURRENT_DATE, 1)
                    ON CONFLICT (date) DO UPDATE
                    SET {column}=risk_management.{column}+1
                    """)
                    await enqueue(conn, 'trade.closed', 'trade_result', inserted, {
                        'trade_result_id': inserted,
                        'active_trade_id': trade_id,
                    })

        result = 'WIN' if profit_usdt > 0 else 'LOSS'
    finally:
        _closing.discard(trade_id)

    icon = "✅" if result == 'WIN' else "❌"
    logger.info(
        f"{icon} {symbol} | {result} | "
        f"ربح: {profit_pct:.2f}% ({profit_usdt:.2f} USDT) | {reason}"
    )
    # لا تنتظر محاولة دخول لاحقة لتحديث لوحة المخاطر وسلسلة الخسائر.
    try:
        decision = await assess_new_trade_risk('__POST_CLOSE_RISK_REFRESH__')
        await record_risk_decision(decision)
    except Exception as exc:
        logger.error(f"تعذر تحديث حالة المخاطر بعد الإغلاق: {format_error(exc)}")


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


async def get_min_notional(symbol: str) -> float:
    """Read Binance's current order-notional floor, cached for this process."""
    if symbol in _min_notional_cache:
        return _min_notional_cache[symbol]
    fallback = config.MIN_ORDER_NOTIONAL_USDT
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                'https://api.binance.com/api/v3/exchangeInfo',
                params={'symbol': symbol}, timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f'Binance exchangeInfo HTTP {resp.status}')
                data = await resp.json()
                filters = data['symbols'][0]['filters']
                values = [float(f['minNotional']) for f in filters
                          if f.get('filterType') in ('NOTIONAL', 'MIN_NOTIONAL')
                          and f.get('minNotional')]
                value = max(values) if values else fallback
                _min_notional_cache[symbol] = value
                return value
    except Exception as exc:
        logger.warning(
            f"تعذر جلب MIN_NOTIONAL لـ {symbol}; استخدام {fallback}: {format_error(exc)}")
        return fallback


async def get_last_closed_candle(symbol: str, timeframe: str) -> dict | None:
    """Return Binance's latest fully closed candle for signal invalidation."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                'https://api.binance.com/api/v3/klines',
                params={'symbol': symbol, 'interval': timeframe, 'limit': 2},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f'Binance klines HTTP {resp.status}')
                rows = await resp.json()
                now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                closed = [row for row in rows if int(row[6]) < now_ms]
                if not closed:
                    return None
                row = closed[-1]
                return {'open_time': int(row[0]), 'close_time': int(row[6]),
                        'close': float(row[4])}
    except Exception as exc:
        logger.warning(
            f"تعذر فحص شمعة الإبطال لـ {symbol}/{timeframe}: {format_error(exc)}")
        return None


if __name__ == "__main__":
    asyncio.run(main())
