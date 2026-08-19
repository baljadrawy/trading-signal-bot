import pandas as pd
import sys; sys.path.insert(0, '.')
from analyzer.simple_entry import detect_trade_setup, detect_trade_type

def _df(close, high=None, low=None, vol=None, rsi=50, ema20=None, ema50=None,
        bb_lower=None, bb_upper=None, open_=None):
    n = len(close)
    high = high if high is not None else [c*1.001 for c in close]
    low = low if low is not None else [c*0.999 for c in close]
    vol = vol if vol is not None else [100.0]*n
    return pd.DataFrame({
        'open': open_ if open_ is not None else [c * .999 for c in close],
        'high': high, 'low': low, 'close': close, 'volume': vol,
        'rsi': [rsi]*n,
        'ema20': ema20 if ema20 is not None else [c*0.95 for c in close],
        'ema50': ema50 if ema50 is not None else [c*0.90 for c in close],
        'bb_lower': bb_lower if bb_lower is not None else [c*0.80 for c in close],
        'bb_upper': bb_upper if bb_upper is not None else [c*1.20 for c in close],
    })

def test_momentum_breakout_with_volume():
    close = [10]*20 + [12]                       # last closes above prior 20-bar high (=~10.01)
    df = _df(close, vol=[100]*20 + [200])        # volume spike
    assert detect_trade_type(df, breakout_n=20, vol_mult=1.2) == 'momentum'

def test_momentum_blocked_without_volume():
    close = [10]*20 + [12]
    df = _df(close, vol=[100]*21)                # no volume spike
    assert detect_trade_type(df, breakout_n=20, vol_mult=1.2) != 'momentum'

def test_reversion_oversold_bounce():
    close = [10,9.5,9.0,8.5,8.6]                 # turning up at the end
    df = _df(close, rsi=30, bb_lower=[8.7]*5,    # close(8.6) < bb_lower*1.01 (8.787)
             ema20=[7]*5, ema50=[6]*5)
    assert detect_trade_type(df, rev_rsi=35) == 'reversion'

def test_no_signal_neutral():
    close = [10.0]*21
    df = _df(close, rsi=50)
    assert detect_trade_type(df) is None


def test_setup_explains_actual_momentum_inputs():
    close = [10] * 20 + [12]
    trade_type, reason, features = detect_trade_setup(
        _df(close, vol=[100] * 20 + [200]), breakout_n=20, vol_mult=1.2)
    assert trade_type == 'momentum'
    assert reason == 'close_above_ema20_ema50_breakout_with_volume'
    assert features['breakout_level'] < features['close']
    assert features['volume'] > features['volume_threshold']


def test_setup_explains_actual_reversion_inputs():
    df = _df([10, 9.5, 9.0, 8.5, 8.6], rsi=30, bb_lower=[8.7] * 5,
             ema20=[7] * 5, ema50=[6] * 5)
    trade_type, reason, features = detect_trade_setup(df, rev_rsi=35)
    assert trade_type == 'reversion'
    assert reason == 'rsi_oversold_bounce_near_lower_bollinger'
    assert features['rsi'] < features['rsi_threshold']
    assert features['close'] > features['previous_close']


def test_market_regime_routes_strategy():
    momentum = _df([10] * 20 + [12], vol=[100] * 20 + [200])
    assert detect_trade_type(momentum, market_condition='sideways') is None

    reversion = _df([10, 9.5, 9.0, 8.5, 8.6], rsi=30, bb_lower=[8.7] * 5,
                    ema20=[7] * 5, ema50=[6] * 5)
    assert detect_trade_type(reversion, market_condition='bullish') is None
