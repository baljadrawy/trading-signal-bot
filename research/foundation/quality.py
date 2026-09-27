"""Fail-closed OHLCV quality checks; data is never repaired silently."""
from __future__ import annotations

import pandas as pd


TF_SECONDS = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


def validate_candles(df: pd.DataFrame, timeframe: str, *, min_rows: int = 200) -> dict:
    failures, warnings = [], []
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(df.columns))
    if missing:
        return {"status": "FAIL", "failures": [f"missing_columns:{','.join(missing)}"], "warnings": []}
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    if ts.isna().any(): failures.append("invalid_timestamp")
    if ts.duplicated().any(): failures.append("duplicate_candles")
    if not ts.is_monotonic_increasing: failures.append("non_monotonic_timestamps")
    numeric = df[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any(): failures.append("non_numeric_or_non_finite")
    if (numeric[["open", "high", "low", "close"]] <= 0).any().any(): failures.append("non_positive_price")
    if (numeric["volume"] < 0).any(): failures.append("impossible_volume")
    if ((numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)) |
            (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1))).any():
        failures.append("invalid_ohlc")
    if len(df) < min_rows: failures.append("insufficient_history")
    seconds = TF_SECONDS.get(timeframe)
    if seconds and len(ts) > 1 and not ts.isna().any():
        gaps = ts.diff().dropna().dt.total_seconds()
        if (gaps != seconds).any(): warnings.append("timeframe_gaps")
    return {"status": "FAIL" if failures else "WARN" if warnings else "PASS",
            "failures": failures, "warnings": warnings, "rows": len(df)}


def enforce_completed(df: pd.DataFrame, decision_time: str) -> pd.DataFrame:
    """Return only candles whose explicit close_time is at/before decision time."""
    if "close_time" not in df.columns:
        raise ValueError("close_time_required_for_completed_candle_contract")
    cutoff = pd.Timestamp(decision_time)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    close_time = pd.to_datetime(df["close_time"], utc=True, errors="raise")
    return df.loc[close_time <= cutoff].copy()
