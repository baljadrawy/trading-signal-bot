"""Collector configuration: defaults, validation, and hard safety boundaries (P2-E1).

The collector reads PUBLIC market data only. Hosts and paths are allow-listed here and enforced again by the HTTP
client. Derivatives and aggTrades are not authorized in E1: enabling either fails validation.
"""
from __future__ import annotations

import hashlib
import json

VERSION = "p2e1-collector-1.3.0"
SCHEMA = "tsb.p2.forward"
SCHEMA_VERSION = 2                                          # v2: G2-Repeat revision (see SCHEMA.md)
SAMPLE_SEMANTICS = "latest_received_at_or_before_sample_ms"
CLOCK_METHOD = "min_rtt_of_3_midpoint_v1"

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
    "host_label": "unlabelled",              # non-confidential host label persisted in the run record (R18)
    "sample_hold_window_s": 120,             # boundary snapshots kept per stream for stall catch-up (F19)
    "subscribe_ack_timeout_s": 10,           # SUBSCRIBE acknowledgement deadline (F37)
    "first_obs_deadline_s": {"t0_book": 30, "depth": 30, "market": 30, "t12_book": 120},   # from WS start (F38)
    "depth_stale_ms": 2000,                  # Tier-0 depth (= depth_stale_ms_by_tier.t0); G2R-validated
    "depth_stale_ms_by_tier": {"t0": 2000, "t1": 180_000, "t2": 15_000},   # G3-F1: 3 x cadence for Tier 1/2
    "book_t12_dead_ms": 600_000,             # G3-F1: Tier-1/2 bookTicker silent beyond this = stale (dead stream)
    "book_t0_stale_ms": 120_000,             # Tier-0 book silent beyond this on a data-live connection = stale gap (F40)
    "book_stale_suspect_ms": 120_000,        # Tier-1/2 book silent beyond this = health warning stale_suspect
    "market_stale_ms": 10_000,               # newest market component older than this at S = market gap (F49)
    "conn_data_live_ms": 10_000,             # connection data-live window (F40)
    "market_startup_ms": 60_000,             # market snapshot startup_complete after this (F8)
    "market_component_max_age_ms": 86_400_000,
    "clock_probes": 3,                       # min-RTT of N probes (F5)
    "health_record_interval_s": 60,          # historical health raw records (R02)
    "universe_load_attempts": 3,             # F25: bounded initial universe load, then fail closed
    "universe_retry_backoff_s": [5, 15],     # F25: sleep before attempt 2, 3 (last value repeats)
    "universe_min_usdt_trading": 350,        # F42: fewer TRADING USDT symbols = partial (live ~500 seen in G2R market data)
    "universe_min_ticker_coverage": 0.99,    # F42: share of TRADING USDT symbols with a valid 24h ticker
    "universe_max_invalid_fraction": 0.005,  # F42: invalid numeric tickers tolerated
    "universe_max_tier1_change": 0.5,
    "universe_max_liquid_missing": 3,        # F42: liquid USDT tickers absent from exchangeInfo tolerated (delisting
                                             # / permission edge cases); a partial exchangeInfo misses far more        # F42: refresh changing Tier 1/2 membership by more = suspicious
    "reconnect_test_at_s": 0,                # > 0: ONE predeclared controlled reconnect (G3) at ws_start + this
    "reconnect_test_conn": "conn0-book",
    "rest_urgent_reserve": 20,
    "certify_shutdown_grace_s": 300,         # G3-F3: bounded wait for the certifier to drain at shutdown
    "certify_max_pending": 24,               # G3-F3: > 2 x the 9 record types (one hour may finalize 9 at once)
    "certify_max_pending_age_s": 900,        # G3-F3: oldest pending segment older than this = DEGRADED
    "certifier_beat_limit_ms": 10_000,       # G3-F3: certifier heartbeat (beats every <=1 s idle, every 500 lines busy)               # own-budget weight reserved for urgent calls (clock, universe)
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
    for k, v in cfg["cadence_ms"].items():                  # the sample grid is 1000 ms (tracks.Held)
        if not (isinstance(v, int) and v > 0 and v % 1000 == 0):
            raise ConfigError(f"cadence {k} must be a positive multiple of 1000 ms")
    for k in ("sample_hold_window_s", "subscribe_ack_timeout_s", "depth_stale_ms", "book_t0_stale_ms",
              "book_stale_suspect_ms", "market_stale_ms", "conn_data_live_ms", "market_startup_ms",
              "market_component_max_age_ms", "clock_probes", "health_record_interval_s"):
        if not (isinstance(cfg[k], (int, float)) and cfg[k] > 0):
            raise ConfigError(f"{k} must be > 0")
    d = cfg["depth_stale_ms_by_tier"]
    if set(d) != {"t0", "t1", "t2"} or any(not (isinstance(v, int) and v >= 1000) for v in d.values()) \
            or d["t0"] != cfg["depth_stale_ms"]:
        raise ConfigError("depth_stale_ms_by_tier must define t0/t1/t2 >= 1000 ms with t0 == depth_stale_ms")
    if not (cfg["book_stale_suspect_ms"] < cfg["book_t12_dead_ms"]):
        raise ConfigError("book_stale_suspect_ms must be below book_t12_dead_ms")
    if cfg["rotation_test_at_s"] > 0 and cfg["reconnect_test_at_s"] > 0:
        raise ConfigError("only one controlled connection test per run (rotation OR reconnect)")
    if cfg["reconnect_test_conn"] not in ("conn0-book", "conn1-depth"):
        raise ConfigError("reconnect_test_conn must be conn0-book or conn1-depth")
    if not (1 <= cfg["universe_load_attempts"] <= 5) or not cfg["universe_retry_backoff_s"]:
        raise ConfigError("universe_load_attempts must be 1..5 with a backoff list")
    if not (0 <= cfg["rest_urgent_reserve"] < cfg["rest_budget_weight_per_min"]):
        raise ConfigError("rest_urgent_reserve out of range")
    if set(cfg["first_obs_deadline_s"]) != {"t0_book", "depth", "market", "t12_book"} or \
            not all(isinstance(v, (int, float)) and v > 0 for v in cfg["first_obs_deadline_s"].values()):
        raise ConfigError("first_obs_deadline_s must define positive t0_book/depth/market/t12_book")


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
