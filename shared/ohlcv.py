"""Canonical Binance OHLCV preparation and validation.

Live consumers must only see complete, ordered UTC candles.  Invalid market data is
rejected instead of being repaired silently because fabricated bars can create a
signal that never existed at the exchange.
"""
from __future__ import annotations

import time
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from shared.candle import candle_seconds


KLINE_COLUMNS = (
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_base",
    "taker_buy_quote", "ignore",
)
NUMERIC_COLUMNS = ("open", "high", "low", "close", "volume", "quote_volume")


def closed_klines(
    klines: Iterable[Sequence], *, now_ms: int | None = None, limit: int | None = None
) -> list[Sequence]:
    """Return candles whose exchange close timestamp is strictly in the past."""
    cutoff = int(time.time() * 1000) if now_ms is None else int(now_ms)
    rows = [row for row in klines if len(row) > 6 and int(row[6]) < cutoff]
    rows.sort(key=lambda row: int(row[0]))
    return rows[-limit:] if limit is not None else rows


def prepare_ohlcv(
    klines: Iterable[Sequence], timeframe: str, *, now_ms: int | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Build and validate the canonical OHLCV frame from Binance kline rows."""
    rows = closed_klines(klines, now_ms=now_ms, limit=limit)
    df = pd.DataFrame(rows, columns=KLINE_COLUMNS)
    if df.empty:
        return df.set_index(pd.DatetimeIndex([], name="open_time", tz="UTC"))

    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    validate_ohlcv(df, timeframe)
    return df


def validate_ohlcv(df: pd.DataFrame, timeframe: str) -> None:
    """Raise ValueError when a frame is unsafe for indicator computation."""
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"OHLCV columns missing: {sorted(missing)}")
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
        raise ValueError("OHLCV index must be a timezone-aware DatetimeIndex")
    if not df.index.is_monotonic_increasing:
        raise ValueError("OHLCV timestamps are not sorted")
    if df.index.has_duplicates:
        raise ValueError("OHLCV contains duplicate timestamps")

    values = df[list(required)].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("OHLCV contains non-finite values")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (df["volume"] < 0).any():
        raise ValueError("OHLCV volume cannot be negative")
    if (df["high"] < df[["open", "low", "close"]].max(axis=1)).any():
        raise ValueError("OHLCV high is below another price")
    if (df["low"] > df[["open", "high", "close"]].min(axis=1)).any():
        raise ValueError("OHLCV low is above another price")

    if len(df) > 1:
        expected = pd.Timedelta(seconds=candle_seconds(timeframe))
        gaps = df.index.to_series().diff().iloc[1:]
        if not (gaps == expected).all():
            raise ValueError(f"OHLCV has missing or irregular {timeframe} candles")
