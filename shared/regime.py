"""Deterministic, point-in-time market-regime classification."""
from __future__ import annotations

import math
from typing import Mapping

import pandas as pd


def classify_regime(df: pd.DataFrame, *, adx_trend: float = 25.0,
                    adx_range: float = 20.0, slope_bars: int = 5,
                    vol_lookback: int = 100,
                    high_vol_percentile: float = 0.75) -> Mapping[str, float | str]:
    """Classify direction and volatility from closed bars only.

    ADX measures trend strength, EMA20 slope/price position measures direction,
    and ATR/close percentile measures volatility without price-level bias.
    Ambiguous or high-volatility ranges are conservatively labelled volatile.
    """
    required = {'close', 'ema20', 'atr', 'adx'}
    if df is None or len(df) < max(slope_bars + 1, vol_lookback):
        raise ValueError('insufficient_regime_history')
    if not required.issubset(df.columns):
        raise ValueError(f'missing_regime_columns:{sorted(required - set(df.columns))}')

    close = float(df['close'].iloc[-1])
    ema20 = float(df['ema20'].iloc[-1])
    prior_ema20 = float(df['ema20'].iloc[-(slope_bars + 1)])
    adx = float(df['adx'].iloc[-1])
    atr_pct = (df['atr'] / df['close']).replace([float('inf'), -float('inf')], pd.NA).dropna()
    window = atr_pct.tail(vol_lookback)
    values = (close, ema20, prior_ema20, adx)
    if not all(math.isfinite(v) for v in values) or close <= 0 or prior_ema20 <= 0:
        raise ValueError('invalid_regime_input')
    if len(window) < vol_lookback:
        raise ValueError('insufficient_volatility_history')

    current_atr_pct = float(window.iloc[-1])
    # Strict rank keeps a constant-volatility window at the bottom rather than
    # falsely labelling every tied observation as the 100th percentile.
    vol_percentile = float((window < current_atr_pct).mean())
    ema_slope_pct = (ema20 / prior_ema20 - 1.0) * 100.0
    high_vol = vol_percentile > high_vol_percentile

    if adx >= adx_trend and ema_slope_pct > 0 and close > ema20:
        condition = 'bullish'
        trend_state = 'trending'
        direction = 'up'
    elif adx >= adx_trend and ema_slope_pct < 0 and close < ema20:
        condition = 'bearish'
        trend_state = 'trending'
        direction = 'down'
    elif adx < adx_range and not high_vol:
        condition = 'sideways'
        trend_state = 'ranging'
        direction = 'neutral'
    else:
        condition = 'volatile'
        trend_state = 'transitional' if not high_vol else 'high_volatility'
        direction = 'neutral'

    return {
        'condition': condition,
        'trend_state': trend_state,
        'direction': direction,
        'adx14': round(adx, 6),
        'atr_pct': round(current_atr_pct, 8),
        'atr_percentile_100': round(vol_percentile, 6),
        'ema20_slope_5_pct': round(ema_slope_pct, 6),
    }
