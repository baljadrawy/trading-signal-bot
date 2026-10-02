"""Raw record contract: deterministic identities, construction and validation (stdlib only).

Raw facts only: `payload` is the exchange message verbatim. Nothing derived (spread, imbalance, ...) is stored.
Exchange time is NEVER synthesized: when a payload has no exchange timestamp the field stays None.
"""
from __future__ import annotations

import time

from .config import SCHEMA, SCHEMA_VERSION, VERSION

FUTURE_TOLERANCE_MS = 5_000          # exchange time later than receive + tolerance => reject (quarantine)
TYPES = {"book", "depth", "candle", "market", "clock", "universe", "gap", "lifecycle"}
REQUIRED = ("schema", "schema_version", "obs_id", "type", "symbol", "source", "transport", "endpoint",
            "exchange_event_time_ms", "exchange_seq", "recv_ts_ns", "observed_at_ms", "available_at_ms",
            "collector_version", "boot_id")


# ---- identities (no file offsets, no process identity) -------------------------------------------------------
def candle_id(symbol: str, tf: str, open_ms: int) -> str:
    return f"{symbol}|{tf}|{int(open_ms)}"                     # identical to P1 Evidence V2 candle_id


def book_id(symbol: str, update_id: int, cadence_ms: int, sample_ms: int) -> str:
    return f"bt|{symbol}|{int(update_id)}|c{int(cadence_ms)}|t{int(sample_ms)}"


def depth_id(levels: int, symbol: str, last_update_id: int, cadence_ms: int, sample_ms: int) -> str:
    return f"dp{int(levels)}|{symbol}|{int(last_update_id)}|c{int(cadence_ms)}|t{int(sample_ms)}"


def market_id(sample_ms: int) -> str:
    return f"mkt|t{int(sample_ms)}"


def clock_id(server_ms: int) -> str:
    return f"clk|{int(server_ms)}"


def universe_id(stamp: str, rule_version: str) -> str:
    return f"uni|{stamp}|{rule_version}"


def gap_id(stream_key: str, start_ms: int, cause: str) -> str:
    return f"gap|{stream_key}|{int(start_ms)}|{cause}"


def lifecycle_id(boot_id: str, event: str) -> str:
    return f"life|{boot_id}|{event}"


# ---- construction --------------------------------------------------------------------------------------------
def make(*, type: str, obs_id: str, symbol: str | None, payload, boot_id: str, endpoint: str, transport: str,
         recv_ts_ns: int, exchange_event_time_ms: int | None = None, exchange_seq: int | None = None,
         tier: int | None = None, cadence_ms: int | None = None, sample_ms: int | None = None,
         available_at_ms: int | None = None, unchanged: bool = False, clock_suspect: bool = False,
         recoverability: str | None = None) -> dict:
    observed = recv_ts_ns // 1_000_000
    return {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "obs_id": obs_id, "type": type, "symbol": symbol,
        "tier": tier, "cadence_ms": cadence_ms, "sample_ms": sample_ms, "source": "binance_spot_public",
        "transport": transport, "endpoint": endpoint, "exchange_event_time_ms": exchange_event_time_ms,
        "exchange_seq": exchange_seq, "recv_ts_ns": int(recv_ts_ns), "queued_ts_ns": None, "blk": None,
        "observed_at_ms": observed, "available_at_ms": int(available_at_ms if available_at_ms is not None else observed),
        "unchanged": bool(unchanged), "clock_suspect": bool(clock_suspect), "recoverability": recoverability,
        "collector_version": VERSION, "boot_id": boot_id, "payload": payload,
    }


def validate(rec: dict, now_ns: int | None = None) -> list:
    """Return a list of problems (empty = valid). Never raises on malformed input."""
    errs = []
    if not isinstance(rec, dict):
        return ["not_object"]
    for k in REQUIRED:
        if k not in rec:
            errs.append(f"missing:{k}")
    if errs:
        return errs
    if rec["schema"] != SCHEMA or rec["schema_version"] != SCHEMA_VERSION:
        errs.append("schema_mismatch")
    if rec["type"] not in TYPES:
        errs.append("bad_type")
    if not isinstance(rec["recv_ts_ns"], int) or rec["recv_ts_ns"] <= 0:
        errs.append("bad_recv_ts")
        return errs
    now_ns = now_ns or time.time_ns()
    if rec["recv_ts_ns"] > now_ns + 1_000_000_000:
        errs.append("recv_in_future")
    ex = rec["exchange_event_time_ms"]
    if ex is not None and (not isinstance(ex, int) or ex > rec["recv_ts_ns"] // 1_000_000 + FUTURE_TOLERANCE_MS):
        errs.append("exchange_time_in_future")
    if rec["type"] in ("book", "depth") and ex is not None:
        errs.append("book_depth_have_no_exchange_time")           # spot bookTicker / partial depth carry no E
    if rec["available_at_ms"] < rec["observed_at_ms"] and rec["type"] != "candle":
        errs.append("available_before_observed")
    if rec["type"] == "candle":
        p = rec["payload"]
        if not (isinstance(p, list) and len(p) >= 7 and rec["available_at_ms"] > int(p[6])):
            errs.append("candle_not_closed_at_availability")
    return errs
