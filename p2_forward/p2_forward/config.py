"""Collector configuration: defaults, validation, and hard safety boundaries (P2-E1; P2-CR continuous mode).

The collector reads PUBLIC market data only. Hosts and paths are allow-listed here and enforced again by the HTTP
client. Derivatives and aggTrades are not authorized in E1: enabling either fails validation.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import cal

VERSION = "p2cr-collector-1.6.1"                  # 1.6.1: session-end metadata + flapping (off by default); 1.6.0: A34
                                                  # 1.5.0: rotation hand-off / sequence continuity
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
    "mode": "bounded",                       # P2-CR: bounded (validation gates) | continuous (explicit, never implied)
    "profile": "tier0_only",                 # tier0_only | recommended
    "max_runtime_s": 0,                       # bounded: (0, 28800] required; continuous: exactly 0 (no hidden limit)
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
    "universe_max_tier1_change": 0.5,        # F42: refresh changing Tier 1/2 membership by more = suspicious
    "universe_max_liquid_missing": 3,        # F42: liquid USDT tickers absent from exchangeInfo tolerated (delisting
                                             # / permission edge cases); a partial exchangeInfo misses far more
    "reconnect_test_at_s": 0,                # > 0: ONE predeclared controlled reconnect (G3) at ws_start + this
    "reconnect_test_conn": "conn0-book",
    "rest_urgent_reserve": 20,               # own-budget weight reserved for urgent calls (clock, universe)
    "certifier_mode": "process",             # G3-F4: certification in a separate worker process (same cgroup)
    "certifier_ready_timeout_s": 10,         # G3-F4-D1: child must publish readiness within this, else unhealthy
    "certify_shutdown_grace_s": 300,         # G3-F3: bounded wait for the certifier to drain at shutdown
    "certify_max_pending": 24,               # G3-F3: > 2 x the 9 record types (one hour may finalize 9 at once)
    "certify_max_pending_age_s": 900,        # G3-F3: oldest pending segment older than this = DEGRADED
    "certifier_beat_limit_ms": 10_000,       # G3-F3: certifier heartbeat (beats every <=1 s idle, every 500 lines busy)
    "derivatives_enabled": False,
    "aggtrades_enabled": False,
    # ---- P2-CR continuous mode (inactive in bounded mode; bounded behaviour is unchanged) ----
    "dataset_id": None,                      # continuous: identity of the ONE logical dataset (dataset.json)
    "universe_refresh_at_s": 600,            # F10: daily refresh at calendar day start + this
    "universe_transition_delay_s": 5,        # F10: accepted refresh takes effect at the boundary >= now + this
    "day_close_after_s": 600,                # day D closed (no further writes expected) at >= D end + this
    "fc_quarantine_per_24h": 2,              # fail-closed stop at this many quarantines in 24 h
    "fc_cert_failures_per_24h": 2,           # fail-closed stop at this many certification failures in 24 h
    "fc_http429_per_24h": 2,                 # fail-closed stop at this many HTTP 429 in 24 h (first = incident)
    "fc_clock_critical_s": 3600,             # fail-closed stop when clock CRITICAL persists this long
    "fc_writer_stall_s": 60,                 # fail-closed stop: writer heartbeat stale this long
    "fc_durable_lag_s": 60,                  # fail-closed stop: not durable this long
    "process_check_interval_s": 5,           # in-container process-role self-check period (continuous)
    "process_violation_checks": 2,           # consecutive sightings of an unknown process => fail-closed stop
    # ---- P2F rotation / sequence continuity (collector >= 1.5.0; continuous mode only) ----
    "ws_handoff_min_s": 2.0,                 # rotation: minimum overlap after the replacement's first data message
    "ws_handoff_timeout_s": 15.0,            # rotation: bounded wait for per-stream catch-up, then fail closed
    "seq_catchup_timeout_s": 30,             # a socket may trail the accepted sequence this long, then seq_reset
    # ---- P2F 1.6.0 bounded recovery / connection incidents (A34) ----
    "ws_close_grace_s": 3.0,                 # session end: graceful close budget, then the transport is aborted
    "ws_abort_wait_s": 2.0,                  # session end: wait after abort, then after cancel (hard bound 7 s)
    "conn_outage_incident_s": 60,            # connection not data-live this long -> conn_outage incident (DEGRADED)
    "conn_recovery_fail_s": 600,             # outage this long, or a wedged session -> conn_recovery_failed (CRITICAL)
    "ws_session_end_events": False,          # P2F obs: lifecycle ws_session_end per ended session (off by default)
    "conn_flapping_enabled": False,          # P2F obs: conn_flapping:<conn> WARNING episodes (off by default)
    "conn_flapping_window_s": 1800,          # candidate (10 ended sessions in 30 min): to be evaluated, not approved
    "conn_flapping_max": 10,
    "conn_flapping_clear_s": 1800,           # episode clears after this long without an ended session
    "tier0_loss_incident_s": 60,             # a tier-0 / market gap this long -> observation_loss:tier0 (WARNING)
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


DATASET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate(cfg: dict) -> None:
    if not isinstance(cfg["enabled"], bool):
        raise ConfigError("enabled must be a JSON boolean")
    for k in ("ws_session_end_events", "conn_flapping_enabled"):          # P2F obs flags
        if not isinstance(cfg.get(k, False), bool):
            raise ConfigError(f"{k} must be a JSON boolean")
    for k in ("conn_flapping_window_s", "conn_flapping_clear_s"):
        v = cfg.get(k, 1)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            raise ConfigError(f"{k} must be a positive number")
    v = cfg.get("conn_flapping_max", 2)
    if isinstance(v, bool) or not isinstance(v, int) or v < 2:
        raise ConfigError("conn_flapping_max must be an integer >= 2")
    if cfg["mode"] not in ("bounded", "continuous"):
        raise ConfigError("mode must be bounded or continuous")
    if not _is_int(cfg["max_runtime_s"]):
        raise ConfigError("max_runtime_s must be an integer")
    if cfg["derivatives_enabled"]:
        raise ConfigError("derivatives capture is not authorized (P2-E1, owner D3)")
    if cfg["aggtrades_enabled"]:
        raise ConfigError("aggTrades capture is not authorized (P2-E1, owner D2)")
    if cfg["profile"] not in ("tier0_only", "recommended"):
        raise ConfigError("profile must be tier0_only or recommended")
    if cfg["enabled"] and cfg["mode"] == "bounded" and not (0 < cfg["max_runtime_s"] <= 8 * 3600):
        raise ConfigError("E1 is bounded: max_runtime_s must be in (0, 28800] when enabled")
    if cfg["mode"] == "continuous":
        _validate_continuous(cfg)
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
    if cfg["certifier_mode"] not in ("process", "thread"):
        raise ConfigError("certifier_mode must be process or thread")
    if not (isinstance(cfg["certifier_ready_timeout_s"], (int, float)) and 0 < cfg["certifier_ready_timeout_s"] <= 120):
        raise ConfigError("certifier_ready_timeout_s must be in (0, 120]")
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


def _validate_continuous(cfg: dict) -> None:
    """Continuous mode is explicit: it needs mode=continuous AND max_runtime_s == 0 AND a dataset identity, and it
    excludes every gate-only test action. Nothing here can be reached by omitting or mistyping a bounded key."""
    if cfg["max_runtime_s"] != 0:
        raise ConfigError("continuous mode has no runtime limit: max_runtime_s must be exactly 0")
    if not (isinstance(cfg["dataset_id"], str) and DATASET_ID_RE.match(cfg["dataset_id"])):
        raise ConfigError("continuous mode requires dataset_id matching ^[a-z0-9][a-z0-9-]{2,63}$")
    if cfg["rotation_test_at_s"] or cfg["reconnect_test_at_s"]:
        raise ConfigError("gate-only controlled connection tests are not allowed in continuous mode")
    if cfg["certifier_mode"] != "process":
        raise ConfigError("continuous mode requires certifier_mode=process")
    h = cal.hour_ms() // 1000                                    # 3600 s (production calendar)
    if not (_is_int(cfg["ws_rotation_s"]) and h <= cfg["ws_rotation_s"] <= 23 * h):
        raise ConfigError("ws_rotation_s must be an integer in [1 h, 23 h] (F24: before the 24 h exchange limit)")
    if not (_is_int(cfg["universe_refresh_at_s"]) and 0 <= cfg["universe_refresh_at_s"] <= 6 * h):
        raise ConfigError("universe_refresh_at_s must be an integer in [0, 6 h]")
    if not (_is_int(cfg["universe_transition_delay_s"]) and 2 <= cfg["universe_transition_delay_s"] <= 60):
        raise ConfigError("universe_transition_delay_s must be an integer in [2, 60]")
    if not (_is_int(cfg["day_close_after_s"]) and min(60, h) <= cfg["day_close_after_s"] <= 6 * h):
        raise ConfigError("day_close_after_s must be an integer in [60 s, 6 h]")
    for k in ("fc_quarantine_per_24h", "fc_cert_failures_per_24h", "fc_http429_per_24h", "process_violation_checks"):
        if not (_is_int(cfg[k]) and 1 <= cfg[k] <= 100):
            raise ConfigError(f"{k} must be an integer in [1, 100]")
    for k in ("fc_clock_critical_s", "fc_writer_stall_s", "fc_durable_lag_s", "process_check_interval_s"):
        if not (_is_int(cfg[k]) and 1 <= cfg[k] <= 86400):
            raise ConfigError(f"{k} must be an integer in [1, 86400]")
    if cfg["fc_writer_stall_s"] * 1000 <= 5000 or cfg["fc_durable_lag_s"] * 1000 <= 10_000:
        raise ConfigError("fail-closed writer limits must exceed the DEGRADED limits (5 s / 10 s)")
    mn, to, cu = cfg["ws_handoff_min_s"], cfg["ws_handoff_timeout_s"], cfg["seq_catchup_timeout_s"]
    if not (isinstance(mn, (int, float)) and not isinstance(mn, bool) and 0 <= mn <= 10):
        raise ConfigError("ws_handoff_min_s must be a number in [0, 10]")
    if not (isinstance(to, (int, float)) and not isinstance(to, bool) and mn < to <= 60):
        raise ConfigError("ws_handoff_timeout_s must be a number in (ws_handoff_min_s, 60]")
    if not (_is_int(cu) and to <= cu <= 300):
        raise ConfigError("seq_catchup_timeout_s must be an integer in [ws_handoff_timeout_s, 300]")
    for k in ("ws_close_grace_s", "ws_abort_wait_s"):
        v = cfg[k]
        if not (isinstance(v, (int, float)) and not isinstance(v, bool) and 0.1 <= v <= 30):
            raise ConfigError(f"{k} must be a number in [0.1, 30]")
    o, f, t0 = cfg["conn_outage_incident_s"], cfg["conn_recovery_fail_s"], cfg["tier0_loss_incident_s"]
    if not (_is_int(o) and 15 <= o <= 3600 and _is_int(f) and o < f <= 86400 and _is_int(t0) and 5 <= t0 <= 3600):
        raise ConfigError("conn_outage_incident_s in [15, 3600] < conn_recovery_fail_s <= 86400; "
                          "tier0_loss_incident_s in [5, 3600] (integers)")


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
