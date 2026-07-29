"""الرسوم: مصدر واحد لحساب الصافي بعد رسوم الذهاب والإياب.
القيم الخام (profit_percent/profit_usdt) تبقى إجمالية في DB؛ الصافي يُحسب عند العرض
بطرح config.FEE_ROUNDTRIP_PCT — نفس فلسفة إصلاح المُتعلّم (تجنّب ازدواج طرح الرسوم)."""
import sys; sys.path.insert(0, '.')
from shared.config import config
from shared.fees import net_pct, fee_usdt, net_usdt


def test_net_pct_subtracts_fee():
    assert abs(net_pct(1.0, fee_roundtrip=0.3) - 0.7) < 1e-9
    assert abs(net_pct(-1.0, fee_roundtrip=0.3) - (-1.3)) < 1e-9   # الرسوم تعمّق الخسارة


def test_net_pct_default_uses_config():
    assert abs(net_pct(1.0) - (1.0 - config.FEE_ROUNDTRIP_PCT)) < 1e-9


def test_fee_usdt_on_notional():
    assert abs(fee_usdt(notional=50, fee_roundtrip=0.3) - 0.15) < 1e-9   # $50 × 0.3%
    # الافتراضي = TRADE_AMOUNT_USDT × FEE_ROUNDTRIP_PCT/100
    assert abs(fee_usdt() - (config.TRADE_AMOUNT_USDT * config.FEE_ROUNDTRIP_PCT / 100.0)) < 1e-9


def test_net_usdt_subtracts_one_fee():
    # ربح إجمالي +$0.50 على مركز $50 (=+1% إجمالي) → صافٍ +0.35 بعد رسوم $0.15
    assert abs(net_usdt(0.5, notional=50, fee_roundtrip=0.3) - 0.35) < 1e-9
    # خسارة إجمالية −$1.00 → صافٍ −$1.15 (الرسوم تعمّق)
    assert abs(net_usdt(-1.0, notional=50, fee_roundtrip=0.3) - (-1.15)) < 1e-9
