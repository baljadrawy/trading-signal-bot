import pandas as pd

from shared.regime import classify_regime


def _frame(direction='flat', adx=15.0, spike=False):
    n = 120
    if direction == 'up':
        ema = [100 + i * .1 for i in range(n)]
        close = [x + 1 for x in ema]
    elif direction == 'down':
        ema = [112 - i * .1 for i in range(n)]
        close = [x - 1 for x in ema]
    else:
        ema = [100.0] * n
        close = [100.0] * n
    atr = [1.0] * n
    if spike:
        atr[-1] = 4.0
    return pd.DataFrame({'close': close, 'ema20': ema, 'atr': atr, 'adx': [adx] * n})


def test_regime_direction_requires_strength_and_slope():
    assert classify_regime(_frame('up', 30))['condition'] == 'bullish'
    assert classify_regime(_frame('down', 30))['condition'] == 'bearish'


def test_regime_distinguishes_range_from_volatile_transition():
    assert classify_regime(_frame('flat', 15))['condition'] == 'sideways'
    assert classify_regime(_frame('flat', 22, spike=True))['condition'] == 'volatile'
