"""Post-decision labels. This module is intentionally separate from decision code."""
from __future__ import annotations

from typing import Iterable
import pandas as pd


def forward_labels(entry: float, future: pd.DataFrame,
                   bars: Iterable[int] = (1, 3, 6, 12, 24)) -> dict:
    if entry <= 0: raise ValueError("entry must be positive")
    output = {}
    for horizon in bars:
        if len(future) >= horizon:
            output[f"return_{horizon}bar"] = (float(future.iloc[horizon - 1]["close"]) / entry - 1) * 100
    return output


def forward_time_labels(entry: float, decision_time: str, future: pd.DataFrame,
                        hours: Iterable[int] = (1, 4, 12, 24, 72)) -> dict:
    if entry <= 0: raise ValueError("entry must be positive")
    if "close_time" not in future.columns: return {}
    decision = pd.Timestamp(decision_time)
    closes = pd.to_datetime(future["close_time"], utc=True)
    output = {}
    for horizon in hours:
        rows = future.loc[closes >= decision + pd.Timedelta(hours=horizon)]
        if not rows.empty:
            output[f"return_{horizon}h"] = (float(rows.iloc[0]["close"]) / entry - 1) * 100
    return output


def excursions(entry: float, future: pd.DataFrame, *, before_t1: float | None = None) -> dict:
    if entry <= 0 or future.empty:
        return {"mfe": None, "mae": None, "time_to_mfe": None, "time_to_mae": None,
                "mfe_before_t1": None, "mae_before_t1": None}
    highs = future["high"].astype(float); lows = future["low"].astype(float)
    hi_i, lo_i = highs.idxmax(), lows.idxmin()
    result = {"mfe": (float(highs.loc[hi_i]) / entry - 1) * 100,
              "mae": (float(lows.loc[lo_i]) / entry - 1) * 100,
              "time_to_mfe": str(future.loc[hi_i, "timestamp"]),
              "time_to_mae": str(future.loc[lo_i, "timestamp"]),
              "mfe_before_t1": None, "mae_before_t1": None}
    if before_t1 is not None:
        hits = future.index[highs >= before_t1]
        subset = future.loc[:hits[0]] if len(hits) else future
        result["mfe_before_t1"] = (float(subset["high"].max()) / entry - 1) * 100
        result["mae_before_t1"] = (float(subset["low"].min()) / entry - 1) * 100
    return result
