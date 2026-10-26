"""Pure, mobile-first Telegram lifecycle formatting."""
from datetime import datetime, timezone

from shared.fees import fee_usdt, net_pct, net_usdt


def _price(value) -> str:
    value = float(value)
    if value < 0.00001:
        return f"{value:.8f}"
    if value < 0.01:
        return f"{value:.7f}"
    if value < 1:
        return f"{value:.6f}"
    if value < 100:
        return f"{value:.4f}"
    return f"{value:.2f}"


def _elapsed(opened_at) -> str:
    if not opened_at:
        return 'الآن'
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=timezone.utc)
    minutes = max(0, int((datetime.now(timezone.utc) - opened_at).total_seconds() / 60))
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if days:
        parts.append(f'{days}ي')
    if hours:
        parts.append(f'{hours}س')
    if minutes or not parts:
        parts.append(f'{minutes}د')
    return ' '.join(parts)


def _targets(trade: dict, reached: int) -> str:
    items = []
    for number in (1, 2, 3):
        marker = '✅' if number <= reached else '🎯' if number == reached + 1 else '⏳'
        items.append(f"T{number}{marker} {_price(trade[f'target_{number}'])}")
    return ' → '.join(items)


def _live_pnl(trade: dict, current_price: float, trade_amount: float,
              roundtrip_cost_pct: float) -> tuple[float, float, float, float]:
    entry = float(trade['entry_price'])
    gross_pct = (float(current_price) / entry - 1) * 100
    gross_usdt = gross_pct / 100 * trade_amount
    return (
        gross_pct, gross_usdt,
        net_pct(gross_pct, roundtrip_cost_pct),
        net_usdt(gross_usdt, trade_amount, roundtrip_cost_pct),
    )


def opened_message(trade: dict, trade_amount: float) -> str:
    kind = trade.get('trade_type') or 'غير مصنف'
    paper = '🧪 ورقية' if trade.get('is_paper_trade', True) else '💰 حقيقية'
    order_type = 'Market' if trade.get('entry_order_type') == 'market' else 'Limit'
    policy = {
        'momentum_breakout': 'إبطال اختراق',
        'reversion_structure': 'إبطال ارتداد',
        'legacy_atr_support': 'ATR + دعم',
    }.get(trade.get('stop_policy'), trade.get('stop_policy') or 'قديم')
    partial = trade.get('exit_policy_version') == 'partial_25_50_25_v1'
    return (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 {trade['symbol']} • {kind} • {trade.get('timeframe') or '?'}\n"
        f"{paper} • صفقة #{trade['id']}\n\n"
        f"💼 الحجم: {trade_amount:.2f} USDT\n"
        f"🧾 الدخول: {order_type} • الوقف: {policy}\n"
        f"📈 الدخول: {_price(trade['entry_price'])}\n"
        f"🛑 الستوب: {_price(trade['stop_loss'])}\n\n"
        f"{_targets(trade, int(trade.get('highest_target_hit') or 0))}\n"
        f"{'📤 التوزيع: 25% / 50% / 25%\n' if partial else ''}"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ فُتحت صفقة فعلياً وليست مجرد إشارة"
    )


def target_message(trade: dict, target: int, current_price: float,
                   trade_amount: float, roundtrip_cost_pct: float,
                   effective_stop: float | None = None,
                   sold_fraction: float | None = None,
                   remaining_fraction: float | None = None) -> str:
    protection = {
        1: 'رُفع الوقف إلى التعادل الصافي قدر الإمكان',
        2: 'فُعّل الوقف المتحرك مع حماية T1',
        3: 'سيُغلق المركز عند T3',
    }.get(int(target), 'تحدّثت حماية الصفقة')
    gross_pct, gross_usdt, final_pct, final_usdt = _live_pnl(
        trade, current_price, trade_amount, roundtrip_cost_pct)
    active_stop = float(effective_stop or trade['stop_loss'])
    stop_distance = (active_stop / float(current_price) - 1) * 100
    tranche_line = ''
    if sold_fraction is not None and float(sold_fraction) > 0:
        tranche_line = (
            f"\n📤 بيع الهدف: {float(sold_fraction) * 100:.0f}%"
            f" • المتبقي: {float(remaining_fraction or 0) * 100:.0f}%")
    return (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 {trade['symbol']} حققت T{int(target)} ✅\n"
        f"⏱️ {_elapsed(trade.get('opened_at'))} • صفقة #{trade['id']}\n\n"
        f"💼 الحجم: {trade_amount:.2f} USDT\n"
        f"📈 إجمالي: {gross_pct:+.2f}% | {gross_usdt:+.2f} USDT\n"
        f"💰 الصافي: {final_pct:+.2f}% | {final_usdt:+.2f} USDT\n\n"
        f"الدخول: {_price(trade['entry_price'])}\n"
        f"الآن: {_price(current_price)}\n"
        f"🛑 الستوب الفعّال: {_price(active_stop)} ({stop_distance:+.2f}% من الآن)"
        f"{tranche_line}\n\n"
        f"{_targets(trade, int(target))}\n"
        f"🛡️ {protection}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


def closed_message(result: dict, roundtrip_cost_pct: float,
                   trade_amount: float) -> str:
    gross_pct = float(result.get('profit_percent') or 0.0)
    gross_usdt = float(result.get('profit_usdt') or 0.0)
    final_pct = net_pct(gross_pct, roundtrip_cost_pct)
    final_usdt = net_usdt(gross_usdt, trade_amount, roundtrip_cost_pct)
    cost = fee_usdt(trade_amount, roundtrip_cost_pct)
    icon = '✅' if final_usdt > 0 else '❌' if final_usdt < 0 else '➖'
    outcome = 'ربح صافٍ' if final_usdt > 0 else 'خسارة صافية' if final_usdt < 0 else 'تعادل صافٍ'
    fills = result.get('target_fills') or []
    fills_line = ''
    if fills:
        rendered = ' • '.join(
            f"T{int(fill['target_number'])} {float(fill['quantity_fraction']) * 100:.0f}%"
            for fill in fills)
        fills_line = f"📤 شرائح منفذة: {rendered}\n"
    return (
        f"{icon} أُغلقت الصفقة #{result.get('active_trade_id', '?')} — {result['symbol']}\n"
        f"{'─' * 28}\n"
        f"📈 الدخول: {_price(result['entry_price'])}\n"
        f"📉 الخروج: {_price(result['exit_price'])}\n"
        f"🏁 السبب: {result.get('notes') or result.get('result') or 'غير معروف'}\n"
        f"🎯 أعلى هدف: T{int(result.get('target_reached') or 0)}\n"
        f"{fills_line}"
        f"⏱️ المدة: {float(result.get('duration_hours') or 0):.1f} ساعة\n\n"
        f"الإجمالي: {gross_pct:+.2f}% ({gross_usdt:+.2f} USDT)\n"
        f"التكلفة المقدرة: -{roundtrip_cost_pct:.2f}% (-{cost:.2f} USDT)\n"
        f"{outcome}: {final_pct:+.2f}% ({final_usdt:+.2f} USDT)"
    )


def risk_halted_message(event: dict) -> str:
    reasons = {
        'daily_loss_limit': 'بلوغ حد الخسارة اليومية',
        'weekly_loss_limit': 'بلوغ حد الخسارة الأسبوعية',
        'max_drawdown_limit': 'بلوغ الحد الأقصى للتراجع',
        'loss_streak_halt': 'بلوغ حد الخسائر المتتالية',
        'invalid_risk_state': 'بيانات المخاطر غير صالحة أو ناقصة',
    }
    reason = event.get('reason') or 'unknown'
    limit_line = ''
    if reason == 'loss_streak_halt':
        limit_line = (
            f"\n🔢 السلسلة: {int(event.get('consecutive_losses') or 0)}"
            f"/{int(event.get('loss_halt_limit') or 0)} خسائر")
    return (
        f"⛔ أوقف حارس المخاطر فتح صفقات جديدة\n"
        f"{'─' * 28}\n"
        f"السبب: {reasons.get(reason, reason)}{limit_line}\n"
        f"📅 اليومي: {float(event.get('daily_pnl_pct') or 0):+.2f}%\n"
        f"📆 الأسبوعي: {float(event.get('weekly_pnl_pct') or 0):+.2f}%\n"
        f"📉 التراجع: {float(event.get('drawdown_pct') or 0):.2f}%\n\n"
        f"🛡️ الصفقات المفتوحة ستبقى تحت المتابعة\n"
        f"▶️ راجع الحالة ثم استخدم /resume للاستئناف"
    )


def runtime_status_message(event_type: str, payload: dict) -> str:
    if event_type == 'tracker.recovered':
        symbols = ', '.join(payload.get('symbols') or []) or 'لا يوجد'
        return (
            f"♻️ استعاد مراقب الصفقات حالته\n"
            f"الصفقات المستعادة: {int(payload.get('count') or 0)}\n"
            f"الأزواج: {symbols}\n"
            f"📡 WebSocket: {'مفعّل' if payload.get('websocket_enabled') else 'معطّل'}"
        )
    if event_type == 'price_stream.down':
        return (
            f"⚠️ انقطاع مراقبة WebSocket لأكثر من دقيقة\n"
            f"المدة: {int(payload.get('outage_seconds') or 0)} ثانية\n"
            f"🛡️ فاحص REST الاحتياطي يعمل كل 30 ثانية"
        )
    return (
        f"✅ عادت مراقبة WebSocket اللحظية\n"
        f"🛡️ الصفقات المفتوحة تحت المتابعة الفورية"
    )


# ---- Paper economic-loss observation (owner decision 2026-10-26) ------------------------
# Used only when the effective PAPER_ECONOMIC_HALT_MODE is 'observe'; enforce-mode texts in
# telegram/main.py are unchanged.
OBSERVED_LABEL = 'observed (Paper observe mode, not blocking)'
OBSERVED_STATUS_LINE = f"✅ يبحث ويراقب — سلسلة الخسائر: {OBSERVED_LABEL}"


def observed_loss_streak_status_lines(consecutive_losses: int, threshold: int) -> str:
    """/status detail for an active loss streak that does not block (observe mode)."""
    return (
        f"\n🔢 الخسائر المتتالية: {int(consecutive_losses)}/{int(threshold)} — {OBSERVED_LABEL}"
        f"\n👁️ ملاحظة فقط: الخسارة الاقتصادية تُسجَّل ولا تمنع الدخول في وضع Paper"
        f"\n🛡️ الضمانات التقنية والإيقاف اليدوي وحدود المحفظة ما زالت مانعة"
    )


def observed_loss_streak_resume_note(consecutive_losses: int, threshold: int) -> str:
    """/resume note for an active loss streak that does not block (observe mode)."""
    return (
        f"\n\n👁️ سلسلة الخسائر ({int(consecutive_losses)}/{int(threshold)}): {OBSERVED_LABEL}"
        f"\nلا تمنع القبول؛ تُسجَّل كملاحظة فقط"
    )
