"""Build deterministic per-symbol Parquet files from verified Binance archives."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd

from .market import TF_MS, add_point_in_time_24h, normalize_binance_klines


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archives(raw_old: Path, raw_15m: Path, symbol: str, timeframe: str) -> list[Path]:
    root = raw_15m if timeframe == "15m" else raw_old
    return sorted((root / symbol / timeframe).glob(f"{symbol}-{timeframe}-????-??.zip"))


def normalize_one(raw_old: Path, raw_15m: Path, output: Path, symbol: str,
                  timeframe: str, historical_end: pd.Timestamp) -> dict:
    sources = archives(raw_old, raw_15m, symbol, timeframe)
    if not sources:
        return {"symbol": symbol, "timeframe": timeframe, "status": "FAIL",
                "failures": ["EXCLUDE_NO_OHLCV"], "warnings": [], "rows": 0}
    try:
        frames = [normalize_binance_klines(p, symbol=symbol, timeframe=timeframe) for p in sources]
        df = pd.concat(frames, ignore_index=True).sort_values("open_time", kind="mergesort").reset_index(drop=True)
    except Exception as exc:
        return {"symbol": symbol, "timeframe": timeframe, "status": "FAIL",
                "failures": ["EXCLUDE_CORRUPT_DATA"], "warnings": [], "rows": 0, "detail": repr(exc)}
    failures, warnings = [], []
    exclusions: dict[str, int] = {}
    beyond = df["close_time"] > historical_end
    if beyond.any(): exclusions["EXCLUDE_AFTER_HISTORICAL_CUTOFF"] = int(beyond.sum())
    duplicate_any = df["open_time"].duplicated(keep=False)
    identical_duplicate_drop = pd.Series(False, index=df.index)
    conflicting_duplicate = pd.Series(False, index=df.index)
    if duplicate_any.any():
        compare = ["open_time", "close_time", "open", "high", "low", "close", "volume", "quote_volume", "trade_count"]
        for _, group in df.loc[duplicate_any].groupby("open_time", sort=False):
            if len(group[compare].drop_duplicates()) == 1:
                identical_duplicate_drop.loc[group.index[1:]] = True
            else:
                conflicting_duplicate.loc[group.index] = True
        if identical_duplicate_drop.any():
            exclusions["EXCLUDE_IDENTICAL_DUPLICATE"] = int(identical_duplicate_drop.sum())
        if conflicting_duplicate.any():
            exclusions["EXCLUDE_CONFLICTING_DUPLICATE"] = int(conflicting_duplicate.sum())
    if not df["open_time"].is_monotonic_increasing: failures.append("NON_MONOTONIC_TIMESTAMPS")
    non_positive = (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    negative_volume = (df[["volume", "quote_volume"]] < 0).any(axis=1)
    invalid_ohlc = ((df["high"] < df[["open", "close", "low"]].max(axis=1)) |
                    (df["low"] > df[["open", "close", "high"]].min(axis=1)))
    expected = pd.Timedelta(milliseconds=TF_MS[timeframe])
    gaps = df["open_time"].diff().dropna()
    gap_count = int((gaps != expected).sum())
    if gap_count: warnings.append("TIMEFRAME_GAPS_PRESERVED")
    # Binance close_time is inclusive (next-open minus one ms/us). Ensure it is inside its candle.
    bad_close = (df["close_time"] <= df["open_time"]) | (df["close_time"] > df["open_time"] + expected)
    row_masks = {"EXCLUDE_NON_POSITIVE_PRICE": non_positive, "EXCLUDE_NEGATIVE_VOLUME": negative_volume,
                 "EXCLUDE_INVALID_OHLC": invalid_ohlc, "EXCLUDE_INVALID_CLOSE_TIME": bad_close}
    for reason, mask in row_masks.items():
        if mask.any(): exclusions[reason] = int(mask.sum())
    excluded = beyond | identical_duplicate_drop | conflicting_duplicate
    for mask in row_masks.values(): excluded |= mask
    if excluded.any():
        warnings.append("INVALID_SOURCE_ROWS_EXCLUDED_AND_RECORDED")
        df = df.loc[~excluded].reset_index(drop=True)
    if df.empty: failures.append("NO_VALID_ROWS_AFTER_EXCLUSIONS")
    if failures:
        return {"symbol": symbol, "timeframe": timeframe, "status": "FAIL",
                "failures": failures, "warnings": warnings, "rows": len(df), "gap_count": gap_count,
                "excluded_rows": exclusions}
    if timeframe == "15m":
        df = add_point_in_time_24h(df, timeframe=timeframe)
    target = output / timeframe / f"{symbol}.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".parquet.part")
    df.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(target)
    return {"symbol": symbol, "timeframe": timeframe,
            "status": "WARN" if warnings else "PASS", "failures": [], "warnings": warnings,
            "rows": len(df), "gap_count": gap_count, "first_open": df.iloc[0].open_time.isoformat(),
            "last_close": df.iloc[-1].close_time.isoformat(), "file": str(target.relative_to(output)),
            "sha256": file_sha256(target), "bytes": target.stat().st_size,
            "excluded_rows": exclusions}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--raw-old", type=Path, required=True)
    p.add_argument("--raw-15m", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--historical-end", default="2026-05-31T23:59:59.999999Z")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--resume", action="store_true")
    a = p.parse_args(argv)
    if a.output.exists(): raise FileExistsError(f"immutable output exists: {a.output}")
    temp = a.output.with_name(a.output.name + ".building")
    previous = []
    if a.resume:
        if not (temp / "quality.json").is_file(): raise FileNotFoundError("resume quality.json missing")
        previous = json.loads((temp / "quality.json").read_text())
    else:
        if temp.exists(): shutil.rmtree(temp)
        temp.mkdir(parents=True)
    symbols = sorted({p.parent.parent.name for p in a.raw_old.glob("*/1h/*.zip")})
    all_jobs = [(s, tf) for s in symbols for tf in ("15m", "1h", "4h", "1d")]
    retry = {(r["symbol"], r["timeframe"]) for r in previous if r["status"] == "FAIL"}
    jobs = [job for job in all_jobs if not a.resume or job in retry]
    results = [r for r in previous if r["status"] != "FAIL"]
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = [pool.submit(normalize_one, a.raw_old, a.raw_15m, temp, s, tf,
                               pd.Timestamp(a.historical_end)) for s, tf in jobs]
        for n, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            if n % 100 == 0: print(f"normalized={n}/{len(jobs)}", flush=True)
    results.sort(key=lambda x: (x["symbol"], x["timeframe"]))
    (temp / "quality.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    if any(x["status"] == "FAIL" for x in results):
        print("normalization contains FAIL records; output retained as .building for audit")
        return 2
    temp.replace(a.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
