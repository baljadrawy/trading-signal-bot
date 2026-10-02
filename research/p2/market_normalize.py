"""P2-B normalizer: raw Binance archives/REST -> per (symbol, timeframe) Parquet, ds-0928-compatible, freeze-guarded.

Reuses ds-0928 semantics (research.data_governance.market.normalize_binance_klines; build_normalized exclusion
rules). Base columns are identical to ds-0928; two provenance columns are appended. Never repairs data: invalid or
duplicate rows are quarantined with a reason; any candle with close_time >= freeze is a HARD FAILURE (never an
exclusion), because no planned source can legitimately contain one.

  <venv-python> -m research.p2.market_normalize --raw <raw dir> --log acquisition.jsonl --out <staging dir>
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import pathlib
import re
import sys
from collections import defaultdict

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from research.data_governance.market import normalize_binance_klines
from . import market_contract as M

NORMALIZER_VERSION = "p2b-normalizer-1.0.0 (ds-0928 ohlcv_normalizer 1.1.0 semantics)"
BASE_COLS = ["symbol", "timeframe", "open_time", "close_time", "open", "high", "low", "close", "volume",
             "quote_volume", "trade_count"]
PROV_COLS = ["source_kind", "source_sha256"]
CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64})\s+")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_rest(path: pathlib.Path, symbol: str, timeframe: str) -> pd.DataFrame:
    rows = json.loads(path.read_bytes())
    if not rows:
        return pd.DataFrame(columns=BASE_COLS)
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "close_time",
                                     "quote_volume", "trade_count", "tb", "tq", "ig"])
    unit = "us" if int(df.iloc[0]["open_time"]) >= 10**15 else "ms"
    for c in ("open", "high", "low", "close", "volume", "quote_volume"):
        df[c] = pd.to_numeric(df[c], errors="raise")
    df["open_time"] = pd.to_datetime(df["open_time"], unit=unit, utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit=unit, utc=True)
    df["trade_count"] = df["trade_count"].astype("int64")
    df.insert(0, "symbol", symbol); df.insert(1, "timeframe", timeframe)
    return df[BASE_COLS]


def _ms(series) -> pd.Series:
    return series.astype("datetime64[us, UTC]").astype("int64") // 1000


def normalize_series(frames: list, symbol: str, timeframe: str) -> tuple:
    """frames: list of (df, source_kind, source_sha256). Returns (clean_df, quarantine_rows, quality)."""
    df = pd.concat([f.assign(source_kind=k, source_sha256=h) for f, k, h in frames], ignore_index=True)
    df["open_time"] = df["open_time"].astype("datetime64[us, UTC]")
    df["close_time"] = df["close_time"].astype("datetime64[us, UTC]")
    df["trade_count"] = df["trade_count"].astype("int64")
    df = df.sort_values(["open_time", "source_kind"], kind="mergesort").reset_index(drop=True)
    o_ms, c_ms = _ms(df["open_time"]), _ms(df["close_time"])
    if (c_ms >= M.FREEZE_MS).any():                     # HARD FAIL: never an exclusion
        raise M.FreezeViolation(f"{symbol}|{timeframe}: {int((c_ms >= M.FREEZE_MS).sum())} candle(s) close at/after freeze")
    tf = M.TF_MS[timeframe]
    q = []
    reasons = {
        "EXCLUDE_MISALIGNED_OPEN": (o_ms % tf) != 0,
        "EXCLUDE_NON_POSITIVE_PRICE": (df[["open", "high", "low", "close"]] <= 0).any(axis=1),
        "EXCLUDE_NEGATIVE_VOLUME": (df[["volume", "quote_volume"]] < 0).any(axis=1) | (df["trade_count"] < 0),
        "EXCLUDE_INVALID_OHLC": (df["high"] < df[["open", "close", "low"]].max(axis=1)) |
                                (df["low"] > df[["open", "close", "high"]].min(axis=1)),
        "EXCLUDE_INVALID_CLOSE_TIME": (c_ms <= o_ms) | (c_ms >= o_ms + tf),
    }
    dup = df["open_time"].duplicated(keep=False)
    ident_drop = pd.Series(False, index=df.index); conflict = pd.Series(False, index=df.index)
    if dup.any():
        cmp = ["open_time", "open", "high", "low", "close", "volume", "quote_volume", "trade_count"]
        for _, g in df.loc[dup].groupby("open_time", sort=False):
            if len(g[cmp].drop_duplicates()) == 1:
                ident_drop.loc[g.index[1:]] = True     # same candle from two sources (e.g. REST overlap): keep first
            else:
                conflict.loc[g.index] = True
    reasons["EXCLUDE_IDENTICAL_DUPLICATE"] = ident_drop
    reasons["EXCLUDE_CONFLICTING_DUPLICATE"] = conflict
    bad = pd.Series(False, index=df.index)
    for r, m in reasons.items():
        for i in df.index[m]:
            q.append({"candle_id": M.CANDLE_KEY_FMT.format(symbol=symbol, timeframe=timeframe, open_ms=int(o_ms[i])),
                      "reason": r, "source_kind": df.at[i, "source_kind"], "source_sha256": df.at[i, "source_sha256"]})
        bad |= m
    clean = df.loc[~bad].reset_index(drop=True)
    if not clean["open_time"].is_monotonic_increasing or clean["open_time"].duplicated().any():
        raise ValueError(f"{symbol}|{timeframe}: non-monotonic after quarantine")
    gaps = []
    om = _ms(clean["open_time"]).tolist()
    for a, b in zip(om, om[1:]):
        if b - a != tf:
            gaps.append({"after_open_ms": a, "next_open_ms": b, "missing_bars": (b - a) // tf - 1})
    quality = {"symbol": symbol, "timeframe": timeframe, "rows": len(clean), "quarantined": len(q),
               "first_open_ms": om[0] if om else None, "last_open_ms": om[-1] if om else None,
               "last_close_ms": int(_ms(clean["close_time"]).iloc[-1]) if om else None,
               "gaps": gaps, "sources": sorted(set(clean["source_kind"]))}
    return clean, q, quality


def table_bytes(df: pd.DataFrame) -> bytes:
    t = pa.Table.from_pandas(df[BASE_COLS + PROV_COLS], preserve_index=False)
    t = t.replace_schema_metadata(None)                  # no pandas metadata: content-only, deterministic
    buf = io.BytesIO()
    pq.write_table(t, buf, compression="zstd", compression_level=3, use_dictionary=False,
                   write_statistics=True, data_page_version="1.0")
    return buf.getvalue()


def content_hash(df: pd.DataFrame) -> str:
    """Serialization-independent row hash (repr of exact values, fixed order)."""
    h = hashlib.sha256()
    for row in df[BASE_COLS + PROV_COLS].itertuples(index=False):
        h.update(repr(tuple(int(x.value // 1000) if isinstance(x, pd.Timestamp) else x for x in row)).encode())
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    raw, out = pathlib.Path(a.raw), pathlib.Path(a.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit("refusing: output not empty")
    recs = [json.loads(l) for l in open(a.log, encoding="utf-8")]
    by_key = defaultdict(list)
    integrity = {"archive_rechecked": 0, "archive_checksum_fail": 0, "rest_files": 0}
    for r in recs:
        if r["status"] == "UPSTREAM_VERIFIED":
            p = raw / r["path"]
            body = p.read_bytes()
            m = CHECKSUM_RE.match(p.with_name(p.name + ".CHECKSUM").read_text().strip())
            integrity["archive_rechecked"] += 1
            if not m or _sha(body) != m.group(1).lower() or _sha(body) != r["local_sha256"]:
                integrity["archive_checksum_fail"] += 1
                raise SystemExit(f"CHECKSUM FAILURE {r['path']}")
            by_key[(r["symbol"], r["timeframe"])].append(("vision_" + r["kind"], p, r["local_sha256"]))
        elif r["status"] == "REST_VALIDATED_NO_UPSTREAM_CHECKSUM" and r["purpose"] == "freeze_day_partial":
            p = raw / r["path"]
            if _sha(p.read_bytes()) != r["local_sha256"]:
                raise SystemExit(f"LOCAL CHECKSUM FAILURE {r['path']}")
            integrity["rest_files"] += 1
            by_key[(r["symbol"], r["timeframe"])].append(("rest_freeze_day", p, r["local_sha256"]))
    files, quality, quarantine = {}, [], []
    for (sym, tf) in sorted(by_key):
        frames = []
        for kind, p, h in sorted(by_key[(sym, tf)], key=lambda x: str(x[1])):
            df = read_rest(p, sym, tf) if kind == "rest_freeze_day" else normalize_binance_klines(p, symbol=sym, timeframe=tf)
            if len(df):
                frames.append((df[BASE_COLS], kind, h))
        if not frames:
            continue
        clean, q, ql = normalize_series(frames, sym, tf)
        quarantine += q; quality.append(ql)
        body = table_bytes(clean)
        rel = f"{tf}/{sym}.parquet"
        (out / tf).mkdir(parents=True, exist_ok=True)
        (out / rel).write_bytes(body)
        files[rel] = {"symbol": sym, "timeframe": tf, "rows": len(clean), "bytes": len(body), "sha256": _sha(body),
                      "content_sha256": content_hash(clean), "first_open_ms": ql["first_open_ms"],
                      "last_close_ms": ql["last_close_ms"]}
    summary = {"normalizer": NORMALIZER_VERSION, "integrity": integrity, "files": files,
               "quality": quality, "quarantine": quarantine,
               "content_identity": _sha("".join(f"{k}:{v['content_sha256']}\n" for k, v in sorted(files.items())).encode())}
    (out / "_normalize_summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"files": len(files), "rows": sum(v["rows"] for v in files.values()), "quarantined": len(quarantine),
                      "content_identity": summary["content_identity"], "integrity": integrity}, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
