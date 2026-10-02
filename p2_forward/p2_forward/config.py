"""Collector configuration: defaults, validation, and hard safety boundaries (P2-E1).

The collector reads PUBLIC market data only. Hosts and paths are allow-listed here and enforced again by the HTTP
client. Derivatives and aggTrades are not authorized in E1: enabling either fails validation.
"""
from __future__ import annotations

import hashlib
import json

VERSION = "p2e1-collector-1.0.0"
SCHEMA = "tsb.p2.forward"
SCHEMA_VERSION = 1

WS_BASE = "wss://data-stream.binance.vision/stream"        # market-data-only WS endpoint (official)
REST_BASE = "https://data-api.binance.vision"               # market-data-only REST endpoint (official)
ALLOWED_HOSTS = frozenset({"data-stream.binance.vision", "data-api.binance.vision"})
ALLOWED_REST_PATHS = {                                       # path -> request weight (official docs, 2026-10-02)
    "/api/v3/klines": 2,
    "/api/v3/time": 1,
    "/api/v3/exchangeInfo": 20,
    "/api/v3/ticker/24hr": 80,                              # all symbols, type=MINI
}

DEFAULTS = {
    "enabled": False,
    "profile": "tier0_only",                 # tier0_only | recommended
    "max_runtime_s": 0,                       # > 0 required: E1 is bounded only
    "data_dir": "/data",
    "tier0": ["BTCUSDT", "ETHUSDT"],
    "tier1_min_quote_volume": 10_000_000,
    "tier1_max": 150,
    "tier1_hysteresis_days": 7,
    "tier2_top_volume": 20,
    "tier2_top_movers": 10,
    "tier2_max": 30,
    "stable_bases": ["USDC", "FDUSD", "USD1", "TUSD", "USDP", "DAI", "EUR", "AEUR", "EURI", "PYUSD", "BUSD",
                     "USDE", "XUSD", "BFUSD", "RLUSD", "USDS", "GBP", "TRY", "BRL", "U"],
    "cadence_ms": {"t0_book": 1000, "t0_depth": 1000, "t2_book": 2000, "t2_depth": 5000,
                   "t1_book": 10000, "t1_depth": 60000, "market": 60000, "clock": 600000},
    "depth_levels": {"t0": 20, "t1": 10, "t2": 10},
    "candle_timeframes": ["15m", "1h", "4h", "1d"],
    "rest_budget_weight_per_min": 300,
    "rest_defer_used_weight": 2400,          # 40 % of 6000
    "rest_pause_used_weight": 3600,          # 60 % of 6000
    "queue_max": 50_000,
    "flush_interval_s": 2.0,
    "health_interval_s": 10.0,
    "disk_warn_free_gb": 100,
    "disk_stop_free_gb": 60,
    "dir_stop_gb": 150,
    "clock_warn_ms": 500,
    "clock_crit_ms": 2000,
    "ws_rotation_s": 23 * 3600,
    "rotation_test_at_s": 0,                 # > 0: one controlled overlap rollover of connection 0 (G3)
    "derivatives_enabled": False,
    "aggtrades_enabled": False,
}


class ConfigError(ValueError):
    pass


def load(path: str | None) -> dict:
    cfg = dict(DEFAULTS)
    if path:
        with open(path, encoding="utf-8") as fh:
            user = json.load(fh)
        unknown = set(user) - set(DEFAULTS)
        if unknown:
            raise ConfigError(f"unknown config keys: {sorted(unknown)}")
        cfg.update(user)
    validate(cfg)
    return cfg


def validate(cfg: dict) -> None:
    if cfg["derivatives_enabled"]:
        raise ConfigError("derivatives capture is not authorized (P2-E1, owner D3)")
    if cfg["aggtrades_enabled"]:
        raise ConfigError("aggTrades capture is not authorized (P2-E1, owner D2)")
    if cfg["profile"] not in ("tier0_only", "recommended"):
        raise ConfigError("profile must be tier0_only or recommended")
    if cfg["enabled"] and not (0 < cfg["max_runtime_s"] <= 8 * 3600):
        raise ConfigError("E1 is bounded: max_runtime_s must be in (0, 28800] when enabled")
    if cfg["queue_max"] <= 0 or cfg["rest_budget_weight_per_min"] > 300:
        raise ConfigError("queue/budget out of authorized range")
    if not (cfg["disk_stop_free_gb"] < cfg["disk_warn_free_gb"]):
        raise ConfigError("disk thresholds inconsistent")


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
