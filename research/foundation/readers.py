"""Read-only logical candle readers selected from immutable manifests."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

import pandas as pd


ADAPTER_VERSION = "normalized-parquet-1.0.0"
REQUIRED = frozenset({"symbol", "timeframe", "open_time", "close_time",
                      "open", "high", "low", "close", "volume",
                      "quote_volume", "trade_count"})
HISTORICAL_END = pd.Timestamp("2026-05-31T23:59:59.999999Z")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class NormalizedParquetReader:
    root: Path
    manifest: dict

    @classmethod
    def open(cls, root: Path) -> "NormalizedParquetReader":
        root = Path(root).resolve()
        manifest = json.loads((root / "manifest.json").read_text())
        if "normalized_files" not in manifest.get("identity", {}):
            raise ValueError("normalized_files manifest field required")
        return cls(root, manifest)

    @property
    def dataset_id(self) -> str:
        return self.manifest["dataset_id"]

    def descriptors(self, *, symbol: str | None = None,
                    timeframe: str | None = None) -> list[dict]:
        rows = self.manifest["identity"]["normalized_files"]
        return [row for row in rows
                if (symbol is None or row["symbol"] == symbol)
                and (timeframe is None or row["timeframe"] == timeframe)]

    def read(self, symbol: str, timeframe: str, *, verify_hash: bool = False,
             columns: Iterable[str] | None = None) -> pd.DataFrame:
        matches = self.descriptors(symbol=symbol, timeframe=timeframe)
        if len(matches) != 1:
            raise FileNotFoundError(f"dataset candle file not unique: {symbol}/{timeframe}")
        item = matches[0]
        path = self.root / "normalized" / item["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        if verify_hash and _sha256(path) != item["sha256"]:
            raise ValueError(f"normalized checksum mismatch: {item['path']}")
        frame = pd.read_parquet(path, columns=list(columns) if columns else None)
        missing = REQUIRED - set(frame.columns)
        if missing:
            raise ValueError(f"DATASET_FIELD_UNAVAILABLE:{sorted(missing)}")
        frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
        frame["close_time"] = pd.to_datetime(frame["close_time"], utc=True)
        frame = frame.sort_values("open_time", kind="stable").reset_index(drop=True)
        if frame["open_time"].duplicated().any() or not frame["open_time"].is_monotonic_increasing:
            raise ValueError("invalid candle ordering")
        if (frame["close_time"] > HISTORICAL_END).any():
            raise ValueError("historical cutoff exceeded")
        # Logical compatibility with the legacy runner; no data is rewritten.
        frame["timestamp"] = frame["open_time"]
        return frame

    def liquidity_asof(self, symbol: str, decision_time: str | pd.Timestamp) -> dict:
        frame = self.read(symbol, "15m")
        required = {"rolling_24h_quote_volume", "price_change_24h_pct",
                    "rolling_24h_trade_count", "realized_volatility_pct"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"DATASET_FIELD_UNAVAILABLE:{sorted(missing)}")
        t = pd.Timestamp(decision_time)
        if t.tzinfo is None: t = t.tz_localize("UTC")
        rows = frame[frame["close_time"] <= t]
        if rows.empty:
            raise ValueError("historical liquidity unavailable")
        row = rows.iloc[-1]
        return {key: float(row[key]) for key in sorted(required)} | {
            "macro_source_time": None,
            "liquidity_source_time": pd.Timestamp(row["close_time"]).isoformat(),
        }


def open_reader(root: Path):
    manifest = json.loads((Path(root) / "manifest.json").read_text())
    identity = manifest.get("identity", {})
    if "normalized_files" in identity:
        return NormalizedParquetReader.open(root)
    raise ValueError("unsupported immutable dataset manifest")

