"""محرّك دخول بسيط شفّاف (long فقط) — momentum أو reversion على شمعة مغلقة."""
import pandas as pd


def detect_trade_setup(df: pd.DataFrame, *, breakout_n: int = 20,
                       vol_mult: float = 1.2, rev_rsi: float = 35.0,
                       bb_max_position: float = 0.20,
                       market_condition: str | None = None):
    """Return ``(trade_type, reason, execution_features)`` for the live policy."""
    if df is None or len(df) < 2:
        return None, None, {}
    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(last['close'])
    features = {
        'close': close,
        'previous_close': float(prev['close']),
        'ema20': float(last['ema20']),
        'ema50': float(last['ema50']),
        'rsi': float(last['rsi']),
        'bb_lower': float(last['bb_lower']),
        'bb_upper': float(last['bb_upper']),
        'volume': float(last['volume']),
    }

    # momentum: إغلاق فوق EMA20>EMA50 + اختراق قمة آخر breakout_n شمعة سابقة + حجم
    try:
        prior_high = float(df['high'].iloc[-(breakout_n + 1):-1].max())
        vol_ma = float(df['volume'].iloc[-(breakout_n + 1):-1].mean())
        features.update({
            'breakout_level': prior_high,
            'breakout_lookback': breakout_n,
            'volume_baseline': vol_ma,
            'volume_threshold': vol_mult * vol_ma,
        })
        if ((market_condition in (None, 'bullish'))
                and close > float(last['ema20']) > float(last['ema50'])
                and close > prior_high
                and float(last['volume']) > vol_mult * vol_ma):
            return (
                'momentum',
                'close_above_ema20_ema50_breakout_with_volume',
                features,
            )
    except (KeyError, ValueError, TypeError, IndexError):
        pass

    # reversion: RSI متشبّع + ارتداد (إغلاق>سابقه) + قرب الباند السفلي
    try:
        bb_range = float(last['bb_upper']) - float(last['bb_lower'])
        bb_position = ((close - float(last['bb_lower'])) / bb_range
                       if bb_range > 0 else float('inf'))
        features['bb_position'] = bb_position
        if ((market_condition in (None, 'sideways'))
                and float(last['rsi']) < rev_rsi
                and close > float(prev['close'])
                and close > float(last['open'])
                and bb_position <= bb_max_position):
            features.update({
                'rsi_threshold': rev_rsi,
                'bb_max_position': bb_max_position,
            })
            return (
                'reversion',
                'rsi_oversold_bounce_near_lower_bollinger',
                features,
            )
    except (KeyError, ValueError, TypeError, IndexError):
        pass
    return None, None, features


def detect_trade_type(df: pd.DataFrame, *, breakout_n: int = 20,
                      vol_mult: float = 1.2, rev_rsi: float = 35.0,
                      bb_max_position: float = 0.20,
                      market_condition: str | None = None):
    """Backward-compatible type-only view of :func:`detect_trade_setup`."""
    return detect_trade_setup(
        df, breakout_n=breakout_n, vol_mult=vol_mult, rev_rsi=rev_rsi,
        bb_max_position=bb_max_position, market_condition=market_condition,
    )[0]
