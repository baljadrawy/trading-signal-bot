"""محرّك دخول بسيط شفّاف (long فقط) — momentum أو reversion على شمعة مغلقة."""
import pandas as pd


def detect_trade_type(df: pd.DataFrame, *, breakout_n: int = 20,
                      vol_mult: float = 1.2, rev_rsi: float = 35.0):
    """يُرجع 'momentum' | 'reversion' | None. momentum له الأولوية لو أطلق الاثنان."""
    if df is None or len(df) < 2:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(last['close'])

    # momentum: إغلاق فوق EMA20>EMA50 + اختراق قمة آخر breakout_n شمعة سابقة + حجم
    try:
        prior_high = float(df['high'].iloc[-(breakout_n + 1):-1].max())
        vol_ma = float(df['volume'].iloc[-(breakout_n + 1):-1].mean())
        if (close > float(last['ema20']) > float(last['ema50'])
                and close > prior_high
                and float(last['volume']) > vol_mult * vol_ma):
            return 'momentum'
    except (KeyError, ValueError, TypeError, IndexError):
        pass

    # reversion: RSI متشبّع + ارتداد (إغلاق>سابقه) + قرب الباند السفلي
    try:
        if (float(last['rsi']) < rev_rsi
                and close > float(prev['close'])
                and close < float(last['bb_lower']) * 1.01):
            return 'reversion'
    except (KeyError, ValueError, TypeError, IndexError):
        pass
    return None
