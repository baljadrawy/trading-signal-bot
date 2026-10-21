"""Pure production strategy calculations shared by live analysis and research replay."""
from __future__ import annotations

from typing import Any
import pandas as pd
import ta

from shared.signal_stop import plan_signal_stop
from shared.t1_cap import LEGACY_WINDOW_V1, capped_t1, resistance_for


def calculate_production_indicators(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Add the exact indicators consumed or recorded by production."""
    df = df.copy()
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=params["rsi_period"]).rsi()
    macd = ta.trend.MACD(df["close"], window_fast=params["macd_fast"],
                        window_slow=params["macd_slow"], window_sign=params["macd_signal"])
    df["macd"] = macd.macd(); df["macd_signal"] = macd.macd_signal(); df["macd_hist"] = macd.macd_diff()
    df["ema20"] = ta.trend.EMAIndicator(df["close"], window=params["ema_short"]).ema_indicator()
    df["ema50"] = ta.trend.EMAIndicator(df["close"], window=params["ema_medium"]).ema_indicator()
    df["ema200"] = ta.trend.EMAIndicator(df["close"], window=params["ema_long"]).ema_indicator()
    bb = ta.volatility.BollingerBands(df["close"], window=params["bb_period"],
                                     window_dev=params["bb_std"])
    df["bb_upper"] = bb.bollinger_hband(); df["bb_middle"] = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]
    df["atr"] = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"],
                                               window=params["atr_period"]).average_true_range()
    df["adx"] = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14).adx()
    stoch = ta.momentum.StochRSIIndicator(df["close"], window=params["stoch_rsi_window"],
                                         smooth1=params["stoch_k"], smooth2=params["stoch_d"])
    df["stoch_k"] = stoch.stochrsi_k(); df["stoch_d"] = stoch.stochrsi_d()
    df["obv"] = ta.volume.OnBalanceVolumeIndicator(df["close"], df["volume"]).on_balance_volume()
    df["obv_ema"] = ta.trend.EMAIndicator(df["obv"], window=20).ema_indicator()
    df["volume_ma"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma"]
    return df


def production_indicator_params(config: Any) -> dict[str, Any]:
    return {"rsi_period": config.RSI_PERIOD, "macd_fast": config.MACD_FAST,
            "macd_slow": config.MACD_SLOW, "macd_signal": config.MACD_SIGNAL,
            "ema_short": config.EMA_SHORT, "ema_medium": config.EMA_MEDIUM,
            "ema_long": config.EMA_LONG, "bb_period": config.BB_PERIOD,
            "bb_std": config.BB_STD, "atr_period": config.ATR_PERIOD,
            "stoch_rsi_window": config.STOCH_RSI_WINDOW, "stoch_k": config.STOCH_K,
            "stoch_d": config.STOCH_D}


def calculate_signal_levels(df: pd.DataFrame, timeframe: str, trade_type: str | None,
                            *, breakout_n: int = 20,
                            t1_cap_policy: str = LEGACY_WINDOW_V1) -> dict[str, Any]:
    """Build the production long bracket. Extraction only; the T1 cap policy is explicit
    (default = production default, shared/t1_cap.py)."""
    last = df.iloc[-1]; atr = float(last["atr"]); entry = float(last["close"])
    recent = df.tail(20); support = float(recent["low"].min()); resistance = float(recent["high"].max())
    stop_loss = max(entry - atr * 1.5, support * 0.99)
    if stop_loss >= entry: stop_loss = entry * 0.97
    caps = {"1d": 0.03, "4h": 0.05, "1h": 0.04, "15m": 0.02}
    cap = caps.get(timeframe, 0.04)
    policy, invalidation, valid, reject = "legacy_atr_support", stop_loss, True, None
    if trade_type in ("momentum", "reversion"):
        breakout = float(df["high"].iloc[-(breakout_n + 1):-1].max())
        plan = plan_signal_stop(entry=entry, atr=atr, trade_type=trade_type,
                                structure_low=support, breakout_level=breakout,
                                max_risk_pct=cap)
        stop_loss, policy, invalidation, valid, reject = (plan.stop_price, plan.policy,
                                                          plan.invalidation_price,
                                                          plan.valid, plan.reason)
    elif entry - stop_loss > entry * cap:
        stop_loss = entry - entry * cap
    risk = entry - stop_loss
    if t1_cap_policy != LEGACY_WINDOW_V1:
        resistance = resistance_for(df, entry, trade_type, t1_cap_policy)
    t1, t2, t3 = capped_t1(entry, risk, resistance), entry + risk * 1.8, entry + risk * 2.2
    levels = {"entry": round(entry, 8), "stop": round(stop_loss, 8),
              "stop_policy": policy, "stop_invalidation": round(invalidation, 8),
              "stop_risk_pct": round((entry - stop_loss) / entry * 100, 4),
              "stop_valid": valid, "stop_reject_reason": reject,
              "t1": round(t1, 8), "t2": round(t2, 8), "t3": round(t3, 8)}
    if t1_cap_policy != LEGACY_WINDOW_V1:
        levels["t1_cap_policy"] = t1_cap_policy
    return levels
