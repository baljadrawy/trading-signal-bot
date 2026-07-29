"""مصدر واحد لحساب الصافي بعد رسوم الذهاب والإياب عبر المشروع.

القيم الخام في DB (`trade_results.profit_percent` و`profit_usdt`) تُخزَّن **إجمالية**
(بلا رسوم) عمداً: المُتعلّم (`continuous_learner.compute_cells`) يطرح الرسوم بنفسه من
`profit_percent`، فلو خُزِّنت صافية لطُرحت الرسوم مرتين. الصافي يُحسب عند نقطة العرض
(تقارير تيليجرام) هنا بطرح `config.FEE_ROUNDTRIP_PCT` — نفس نموذج الرسوم المستخدم في
المُتعلّم (0.1%/جهة + انزلاق، افتراضي 0.3% ذهاباً وإياباً، قابل للتعديل عبر .env).
"""
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
