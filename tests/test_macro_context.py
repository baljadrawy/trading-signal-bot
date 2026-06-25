import sys; sys.path.insert(0, '.')
from shared.macro_context import classify_usdtd_trend, should_block

def test_usdtd_rising_fast():
    # +0.6 نقطة مئوية فوق متوسط 3 أيام، عتبة 0.5
    assert classify_usdtd_trend(9.3, 8.7, 0.5) == 'rising_fast'

def test_usdtd_rising_not_fast():
    assert classify_usdtd_trend(8.9, 8.7, 0.5) == 'rising'

def test_usdtd_falling():
    assert classify_usdtd_trend(8.4, 8.7, 0.5) == 'falling'

def test_usdtd_flat():
    assert classify_usdtd_trend(8.71, 8.70, 0.5) == 'flat'

def test_block_on_btc_crash():
    assert should_block('strong_bearish', 'falling') is True

def test_block_on_usdtd_spike():
    assert should_block('neutral', 'rising_fast') is True

def test_no_block_normal():
    assert should_block('bullish', 'falling') is False
