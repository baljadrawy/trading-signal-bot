"""Deterministic normalization and strictly backward-looking market context."""
from __future__ import annotations

from pathlib import Path
import zipfile

import pandas as pd


KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trade_count", "taker_buy_base", "taker_buy_quote", "ignore",
]
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _timestamp_unit(value: int) -> str:
    return "us" if abs(value) >= 10**15 else "ms"


def normalize_binance_klines(path: Path, *, symbol: str, timeframe: str) -> pd.DataFrame:
    """Read a Binance Vision CSV/ZIP without mutating the source."""
    path = Path(path)
    if timeframe not in TF_MS:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.endswith(".csv")]
            if len(names) != 1:
                raise ValueError("expected exactly one CSV in Binance archive")
            with archive.open(names[0]) as handle:
                df = pd.read_csv(handle, header=None, names=KLINE_COLUMNS)
    else:
        df = pd.read_csv(path, header=None, names=KLINE_COLUMNS)
    if df.empty:
        raise ValueError("empty kline file")
    unit = _timestamp_unit(int(df.iloc[0]["open_time"]))
    for col in ("open", "high", "low", "close", "volume", "quote_volume"):
        df[col] = pd.to_numeric(df[col], errors="raise")
    df["open_time"] = pd.to_datetime(df["open_time"], unit=unit, utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit=unit, utc=True)
    df.insert(0, "symbol", symbol.upper())
    df.insert(1, "timeframe", timeframe)
    return df[["symbol", "timeframe", "open_time", "close_time", "open", "high",
               "low", "close", "volume", "quote_volume", "trade_count"]]


def add_point_in_time_24h(df: pd.DataFrame, *, timeframe: str) -> pd.DataFrame:
    """Add rolling 24h values using only candles closed at each row's close_time."""
    periods = 86_400_000 // TF_MS[timeframe]
    if periods < 1:
        raise ValueError("timeframe exceeds 24h")
    out = df.copy()
    out["rolling_24h_quote_volume"] = out["quote_volume"].rolling(periods, min_periods=periods).sum()
    out["price_change_24h_pct"] = (out["close"] / out["close"].shift(periods) - 1.0) * 100.0
    if "trade_count" in out:
        out["rolling_24h_trade_count"] = out["trade_count"].rolling(periods, min_periods=periods).sum()
    returns = out["close"].pct_change(fill_method=None)
    out["realized_volatility_pct"] = returns.rolling(periods, min_periods=periods).std() * (periods ** 0.5) * 100.0
    return out


def asof_macro(decisions: pd.DataFrame, macro: pd.DataFrame, *, max_age: pd.Timedelta) -> pd.DataFrame:
    """Backward as-of join; future macro observations can never satisfy a decision."""
    left = decisions.sort_values("decision_time").copy()
    right = macro.sort_values("macro_source_time").copy()
    joined = pd.merge_asof(left, right, left_on="decision_time", right_on="macro_source_time",
                           direction="backward", allow_exact_matches=True)
    joined["macro_age"] = joined["decision_time"] - joined["macro_source_time"]
    joined["macro_status"] = "PASS"
    joined.loc[joined["macro_source_time"].isna(), "macro_status"] = "MACRO_DATA_UNAVAILABLE"
    joined.loc[joined["macro_age"] > max_age, "macro_status"] = "MACRO_STALE"
    return joined


def derive_usdt_d(usdt_market_cap: pd.DataFrame, total_market_cap: pd.DataFrame) -> pd.DataFrame:
    """Derive daily dominance from same-time, point-in-time market-cap observations."""
    left = usdt_market_cap.rename(columns={"timestamp": "macro_source_time",
                                           "market_cap": "usdt_market_cap"}).copy()
    right = total_market_cap.rename(columns={"timestamp": "macro_source_time",
                                             "market_cap": "total_market_cap"}).copy()
    merged = left.merge(right, on="macro_source_time", how="inner", validate="one_to_one")
    if (merged[["usdt_market_cap", "total_market_cap"]] <= 0).any().any():
        raise ValueError("market caps must be positive")
    merged["usdt_d_value"] = merged["usdt_market_cap"] / merged["total_market_cap"] * 100.0
    return merged.sort_values("macro_source_time").reset_index(drop=True)
