import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "analyzer")
from technical_analyzer import TechnicalAnalyzer, indicator_warmup_bars
from shared.config import config


def _market_frame(n=320):
    x = np.arange(n, dtype=float)
    close = 100 + 0.03 * x + 3 * np.sin(x / 7) + np.cos(x / 19)
    open_ = close + 0.25 * np.sin(x / 3)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.8,
            "low": np.minimum(open_, close) - 0.7,
            "close": close,
            "volume": 1000 + x * 2 + 80 * np.sin(x / 11),
        },
        index=pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC"),
    )


def _manual_rsi(close, window):
    delta = close.diff(1)
    up = delta.where(delta > 0, 0.0)
    down = -delta.where(delta < 0, 0.0)
    avg_up = up.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_down = down.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    relative = avg_up / avg_down
    return pd.Series(np.where(avg_down == 0, 100, 100 - 100 / (1 + relative)), index=close.index)


def _manual_atr(df, window):
    previous_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ], axis=1,
    ).max(axis=1)
    values = np.zeros(len(df))
    values[window - 1] = true_range.iloc[:window].mean()
    for i in range(window, len(df)):
        values[i] = (values[i - 1] * (window - 1) + true_range.iloc[i]) / window
    return pd.Series(values, index=df.index)


def _manual_stoch_rsi(close, window, smooth_k, smooth_d):
    rsi = _manual_rsi(close, window)
    low = rsi.rolling(window).min()
    high = rsi.rolling(window).max()
    raw = (rsi - low) / (high - low)
    k = raw.rolling(smooth_k).mean()
    return k, k.rolling(smooth_d).mean()


def test_core_indicators_match_independent_known_formulas():
    source = _market_frame()
    actual = TechnicalAnalyzer(None)._calculate_indicators(source.copy())
    close = source["close"]

    ema20 = close.ewm(span=config.EMA_SHORT, min_periods=config.EMA_SHORT, adjust=False).mean()
    ema50 = close.ewm(span=config.EMA_MEDIUM, min_periods=config.EMA_MEDIUM, adjust=False).mean()
    ema200 = close.ewm(span=config.EMA_LONG, min_periods=config.EMA_LONG, adjust=False).mean()
    macd = close.ewm(span=config.MACD_FAST, min_periods=config.MACD_FAST, adjust=False).mean() - close.ewm(
        span=config.MACD_SLOW, min_periods=config.MACD_SLOW, adjust=False
    ).mean()
    macd_signal = macd.ewm(span=config.MACD_SIGNAL, min_periods=config.MACD_SIGNAL, adjust=False).mean()
    middle = close.rolling(config.BB_PERIOD).mean()
    deviation = close.rolling(config.BB_PERIOD).std(ddof=0)

    references = {
        "rsi": _manual_rsi(close, config.RSI_PERIOD),
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd - macd_signal,
        "bb_middle": middle,
        "bb_upper": middle + config.BB_STD * deviation,
        "bb_lower": middle - config.BB_STD * deviation,
        "atr": _manual_atr(source, config.ATR_PERIOD),
    }
    for name, expected in references.items():
        np.testing.assert_allclose(actual[name], expected, rtol=1e-12, atol=1e-12, equal_nan=True)


def test_volume_obv_and_stoch_units_are_stable():
    source = _market_frame()
    actual = TechnicalAnalyzer(None)._calculate_indicators(source.copy())
    directions = np.where(source["close"] < source["close"].shift(1), -1, 1)
    expected_obv = (source["volume"] * directions).cumsum()
    expected_ratio = source["volume"] / source["volume"].rolling(20).mean()
    np.testing.assert_allclose(actual["obv"], expected_obv, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(actual["volume_ratio"], expected_ratio, rtol=1e-12, atol=1e-12, equal_nan=True)
    mature = actual[["stoch_k", "stoch_d"]].dropna()
    assert ((mature >= 0) & (mature <= 1)).all().all()


def test_stoch_rsi_matches_standard_14_3_3_definition():
    source = _market_frame()
    actual = TechnicalAnalyzer(None)._calculate_indicators(source.copy())
    expected_k, expected_d = _manual_stoch_rsi(
        source['close'], config.STOCH_RSI_WINDOW, config.STOCH_K, config.STOCH_D)
    np.testing.assert_allclose(actual['stoch_k'], expected_k, rtol=1e-10, atol=1e-10,
                               equal_nan=True)
    np.testing.assert_allclose(actual['stoch_d'], expected_d, rtol=1e-10, atol=1e-10,
                               equal_nan=True)


def test_raw_feature_store_has_finite_values_and_declared_units():
    calculated = TechnicalAnalyzer(None)._calculate_indicators(_market_frame())
    features = TechnicalAnalyzer(None)._raw_features(calculated)
    expected = {
        "rsi", "stoch_k", "stoch_d", "macd_hist", "bb_pos", "bb_width",
        "atr_pct", "volume_ratio", "dist_ema20", "dist_ema50", "dist_ema200",
        "obv_vs_ema", "adx14", "cci20", "willr14", "roc10", "mfi14", "cmf20",
    }
    assert set(features) == expected
    assert all(value is None or np.isfinite(value) for value in features.values())
    assert 0 <= features["rsi"] <= 100
    assert 0 <= features["stoch_k"] <= 1
    assert 0 <= features["stoch_d"] <= 1
    assert 0 <= features["mfi14"] <= 100
    assert -100 <= features["willr14"] <= 0


def test_warmup_covers_longest_production_indicator():
    assert indicator_warmup_bars() >= config.EMA_LONG == 200


def test_nearby_resistance_cannot_push_t1_below_entry():
    df = pd.DataFrame({
        "close": [99.0] * 19 + [100.0],
        "high": [100.5] * 20,
        "low": [98.0] * 20,
        "atr": [2.0] * 20,
    })
    levels = TechnicalAnalyzer(None)._calculate_levels(df, "1d")
    assert levels["stop"] < levels["entry"] < levels["t1"] < levels["t2"] < levels["t3"]


def test_extreme_oversold_scores_but_overbought_stoch_does_not():
    analyzer = TechnicalAnalyzer(None)
    df = analyzer._calculate_indicators(_market_frame())
    df.loc[df.index[-1], ['rsi', 'stoch_k', 'stoch_d']] = [10.0, 0.95, 0.90]
    scores = analyzer._calculate_scores(df, {'rsi': 1.0, 'stoch_rsi': 1.0})
    assert scores['details']['rsi'] == 1.5
    assert scores['details']['stoch_rsi'] == 0
