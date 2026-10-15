"""مصدر واحد لحساب الصافي بعد رسوم الذهاب والإياب عبر المشروع.

القيم الخام في DB (`trade_results.profit_percent` و`profit_usdt`) تُخزَّن **إجمالية**
(بلا رسوم) عمداً: المُتعلّم (`continuous_learner.compute_cells`) يطرح الرسوم بنفسه من
`profit_percent`، فلو خُزِّنت صافية لطُرحت الرسوم مرتين. الصافي يُحسب عند نقطة العرض
(تقارير تيليجرام) هنا بطرح `config.FEE_ROUNDTRIP_PCT` — نفس نموذج الرسوم المستخدم في
المُتعلّم (0.1%/جهة + انزلاق، افتراضي 0.3% ذهاباً وإياباً، قابل للتعديل عبر .env).
"""
import math

from shared.config import config


def net_pct(gross_pct: float, fee_roundtrip: float = None) -> float:
    """النسبة الصافية = الإجمالية − رسوم الذهاب والإياب (بالنقاط المئوية)."""
    fee = config.FEE_ROUNDTRIP_PCT if fee_roundtrip is None else fee_roundtrip
    return gross_pct - fee


def fee_usdt(notional: float = None, fee_roundtrip: float = None) -> float:
    """رسوم صفقة واحدة بالدولار = المركز × الرسوم%/100 (المركز الافتراضي = TRADE_AMOUNT_USDT)."""
    n = config.TRADE_AMOUNT_USDT if notional is None else notional
    fee = config.FEE_ROUNDTRIP_PCT if fee_roundtrip is None else fee_roundtrip
    return n * fee / 100.0


def net_usdt(gross_usdt: float, notional: float = None, fee_roundtrip: float = None) -> float:
    """دولار صافٍ لصفقة واحدة = الإجمالي − رسوم صفقة واحدة. للمجاميع اطرح count×fee_usdt() صراحةً."""
    return gross_usdt - fee_usdt(notional, fee_roundtrip)


# ── A38: economic classification (net of the modeled cost) ──────────────────────────────────
# `trade_results.result` keeps its legacy meaning, WIN when GROSS P&L > 0, because strategy code
# (the signal_engine loss cooldown) and all history depend on it. The economic label below is
# the one reports, and every new trade_results row, use:
#   net = round(gross_usdt, 4) − cost_usdt; WIN if net > 0, LOSS if net < 0, BREAKEVEN if net == 0.
# A risk-control loss is net < 0. shared.risk_epoch.tail_loss_streak breaks the streak at
# net >= 0, so economic LOSS and risk loss are the same set, and BREAKEVEN is never a risk loss.
# The gross is rounded to the stored 4 decimals first, so the label equals what the risk guard
# computes from the stored row.
LABEL_POLICY = 'net_after_modeled_cost_v1'


def economic_result(net: float) -> str:
    if net > 0:
        return 'WIN'
    if net < 0:
        return 'LOSS'
    return 'BREAKEVEN'


def economic_close(gross_usdt: float, notional: float = None, fee_roundtrip: float = None) -> dict:
    """The economic fields stored with a trade result. A non-finite gross is refused rather than
    labelled (NaN compares neither > 0 nor < 0 and would otherwise become BREAKEVEN)."""
    if not math.isfinite(float(gross_usdt)):
        raise ValueError(f"economic_close: non-finite gross {gross_usdt!r}")
    cost = fee_usdt(notional, fee_roundtrip)
    net = round(round(float(gross_usdt), 4) - cost, 6)
    return {'cost_usdt': round(cost, 6), 'net_profit_usdt': net,
            'economic_result': economic_result(net), 'label_policy': LABEL_POLICY}


def economic_result_sql(cost_param: str = '$1') -> str:
    """SQL for the economic label of a trade_results row: the stored A38 label when present,
    otherwise derived at read time from the stored gross and the current modeled cost (the
    derivation closed_message has always used). Read-only: history is never rewritten."""
    net = f"(profit_usdt - {cost_param})"
    return (f"COALESCE(economic_result, CASE WHEN {net} > 0 THEN 'WIN' "
            f"WHEN {net} < 0 THEN 'LOSS' ELSE 'BREAKEVEN' END)")
