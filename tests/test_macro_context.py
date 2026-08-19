import sys; sys.path.insert(0, '.')
import asyncio
from shared.macro_context import MacroContext, classify_usdtd_trend, should_block

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


def test_missing_macro_data_blocks_fail_closed(monkeypatch):
    context = MacroContext(client=None)

    async def failed_refresh():
        context._last_attempt_ts = 1
        context._last_error = 'offline'
        return False

    monkeypatch.setattr(context, 'refresh', failed_refresh)
    assert asyncio.run(context.should_block_now()) is True
    assert context.snapshot()['macro_data_valid'] is False
