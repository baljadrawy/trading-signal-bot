"""Pure Telegram lifecycle message formatting (no network or database access)."""
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


def opened_message(trade: dict, trade_amount: float) -> str:
    kind = trade.get('trade_type') or 'غير مصنف'
    paper = '🧪 ورقية' if trade.get('is_paper_trade', True) else '💰 حقيقية'
    return (
        f"🟢 فُتحت صفقة {paper} #{trade['id']}\n"
        f"{'─' * 28}\n"
        f"🪙 {trade['symbol']} | {kind} | {trade.get('timeframe') or '?'}\n"
        f"💵 الحجم: {trade_amount:.2f} USDT\n"
        f"📈 التعبئة: {_price(trade['entry_price'])}\n"
        f"🛑 الوقف: {_price(trade['stop_loss'])}\n"
        f"🎯 T1 {_price(trade['target_1'])} | T2 {_price(trade['target_2'])} | T3 {_price(trade['target_3'])}\n"
        f"✅ هذه صفقة مسجلة فعلياً وليست مجرد إشارة"
    )


def target_message(trade: dict, target: int, current_price: float) -> str:
    protection = {
        1: 'رُفع الوقف إلى التعادل الصافي قدر الإمكان',
        2: 'فُعّل الوقف المتحرك مع حماية T1',
        3: 'سيُغلق المركز عند T3',
    }.get(int(target), 'تحدّثت حماية الصفقة')
    return (
        f"🎯 تحديث الصفقة #{trade['id']} — {trade['symbol']}\n"
        f"تم بلوغ T{int(target)} عند سعر {_price(current_price)}\n"
        f"🛡️ {protection}"
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
    return (
        f"{icon} أُغلقت الصفقة #{result.get('active_trade_id', '?')} — {result['symbol']}\n"
        f"{'─' * 28}\n"
        f"📈 الدخول: {_price(result['entry_price'])}\n"
        f"📉 الخروج: {_price(result['exit_price'])}\n"
        f"🏁 السبب: {result.get('notes') or result.get('result') or 'غير معروف'}\n"
        f"🎯 أعلى هدف: T{int(result.get('target_reached') or 0)}\n"
        f"⏱️ المدة: {float(result.get('duration_hours') or 0):.1f} ساعة\n\n"
        f"الإجمالي: {gross_pct:+.2f}% ({gross_usdt:+.2f} USDT)\n"
        f"التكلفة المقدرة: -{roundtrip_cost_pct:.2f}% (-{cost:.2f} USDT)\n"
        f"{outcome}: {final_pct:+.2f}% ({final_usdt:+.2f} USDT)"
    )
