"""Run provenance (R01 / R06 / R17 / R18): an immutable run record that makes a dataset interpretable years later
without runtime memory. Written once at start: `runs/run-<boot_id>.json` (0444, fsynced) + SCHEMA.md copy.

Identity sources: git commit / image tag / build time are baked into the image at build time (ENV from build
args); the image ID is passed at run time (P2F_IMAGE_ID) and verified by the gate script against the container's
actual image before the run is accepted. Code identity is self-measured (SHA-256 of every packaged source file).
"""
from __future__ import annotations

import hashlib
import importlib.metadata as md
import json
import os
import platform
import sys
import time

from . import config as C
from . import universe as U

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DOC = os.path.join(PKG_DIR, "SCHEMA.md")
PACKAGES = ("aiohttp", "aiohappyeyeballs", "aiosignal", "attrs", "frozenlist", "idna", "multidict", "propcache",
            "yarl", "typing_extensions")


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def code_identity() -> dict:
    files = {f: _sha(os.path.join(PKG_DIR, f)) for f in sorted(os.listdir(PKG_DIR))
             if f.endswith(".py") or f == "SCHEMA.md"}
    combined = hashlib.sha256("".join(f"{k}:{v}\n" for k, v in files.items()).encode()).hexdigest()
    return {"files": files, "combined_sha256": combined}


def packages() -> dict:
    out = {}
    for p in PACKAGES:
        try:
            out[p] = md.version(p)
        except md.PackageNotFoundError:
            out[p] = None
    return out


def _atomic_ro(path: str, data: bytes) -> None:
    tmp = path + ".partial"
    with open(tmp, "wb") as fh:
        fh.write(data); fh.flush(); os.fsync(fh.fileno())
    os.rename(tmp, path); os.chmod(path, 0o444)
    fd = os.open(os.path.dirname(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def install_schema_doc(base: str) -> dict:
    """Copy SCHEMA.md into <data>/docs/SCHEMA-v<schema>-<sha8>.md (immutable; never overwritten)."""
    sha = _sha(SCHEMA_DOC)
    d = os.path.join(base, "docs"); os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"SCHEMA-v{C.SCHEMA_VERSION}-{sha[:8]}.md")
    if not os.path.exists(path):
        with open(SCHEMA_DOC, "rb") as fh:
            _atomic_ro(path, fh.read())
    elif _sha(path) != sha:
        raise RuntimeError(f"existing schema doc {path} does not match the packaged SCHEMA.md")
    return {"file": os.path.relpath(path, base), "sha256": sha}


def build_run_record(col) -> dict:
    cfg = col.cfg
    return {
        "record": "tsb.p2.forward.run", "record_version": 1,
        "schema": C.SCHEMA, "schema_version": C.SCHEMA_VERSION, "collector_version": C.VERSION,
        "boot_id": col.boot_id, "created_ms": time.time_ns() // 1_000_000, "host_label": cfg["host_label"],
        "build": {"git_commit": os.environ.get("P2F_GIT_COMMIT", "unknown"),
                  "image_tag": os.environ.get("P2F_IMAGE_TAG", "unknown"),
                  "build_time": os.environ.get("P2F_BUILD_TIME", "unknown"),
                  "image_id_runtime_claim": os.environ.get("P2F_IMAGE_ID", "unknown")},
        "code": code_identity(),
        "runtime": {"python": sys.version.split()[0], "implementation": platform.python_implementation(),
                    "machine": platform.machine(), "packages": packages()},
        "config": cfg, "config_hash": col.config_hash,
        "semantics": {"sample_semantics": C.SAMPLE_SEMANTICS, "clock_method": C.CLOCK_METHOD,
                      "sample_grid_ms": 1000, "hold_window_ms": int(cfg["sample_hold_window_s"] * 1000),
                      "stale_ms": {"depth": cfg["depth_stale_ms"], "depth_by_tier": cfg["depth_stale_ms_by_tier"],
                                   "book_t12_dead": cfg["book_t12_dead_ms"], "book_t0": cfg["book_t0_stale_ms"],
                                   "book_t12_suspect": cfg["book_stale_suspect_ms"], "market": cfg["market_stale_ms"]},
                      "conn_data_live_ms": cfg["conn_data_live_ms"], "first_obs_deadline_s": cfg["first_obs_deadline_s"],
                      "subscribe_ack_timeout_s": cfg["subscribe_ack_timeout_s"],
                      "health_record_interval_s": cfg["health_record_interval_s"],
                      "controlled_reconnect": {"at_s": cfg["reconnect_test_at_s"], "conn": cfg["reconnect_test_conn"],
                                               "trigger": "internal scheduled force_reconnect at ws_start + at_s"},
                      "universe_policy": {"attempts": cfg["universe_load_attempts"],
                                          "backoff_s": cfg["universe_retry_backoff_s"],
                                          "min_usdt_trading": cfg["universe_min_usdt_trading"],
                                          "min_ticker_coverage": cfg["universe_min_ticker_coverage"],
                                          "max_invalid_fraction": cfg["universe_max_invalid_fraction"],
                                          "max_tier1_change": cfg["universe_max_tier1_change"],
                                          "initial_failure": "fail_closed", "refresh_failure": "keep_previous_degraded"}},
        "sampling_profile": {"profile": cfg["profile"], "cadence_ms": cfg["cadence_ms"], "depth_levels": cfg["depth_levels"],
                             "candle_timeframes": cfg["candle_timeframes"]},
        "universe": {"rule_version": U.RULE_VERSION, **(col.universe_meta or {}),
                     # tiers only; the full per-candidate evaluation (R04) is the universe artifact + raw record
                     "snapshot": None if col.universe is None else
                     {k: col.universe.get(k) for k in ("rule_version", "tier0", "tier1", "tier2", "hysteresis_members",
                                                        "eligible_count", "candidate_count", "inputs_sha256",
                                                        "thresholds", "prior_universe_id")}},
        "startup_failure": col.startup_failure,
        "endpoints": {"ws": C.WS_BASE, "rest": C.REST_BASE, "rest_paths": C.ALLOWED_REST_PATHS},
        "expected_streams": col.expected_streams(),
        "schema_doc": install_schema_doc(col.base),
    }


def write_run_record(col) -> tuple:
    rec = build_run_record(col)
    d = os.path.join(col.base, "runs"); os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"run-{col.boot_id}.json")
    data = (json.dumps(rec, sort_keys=True, indent=1, default=str) + "\n").encode("utf-8")
    _atomic_ro(path, data)
    return rec, os.path.relpath(path, col.base), hashlib.sha256(data).hexdigest()
