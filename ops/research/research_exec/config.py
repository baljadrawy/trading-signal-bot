"""Profiles, thresholds and config loading.

Every value here can be overridden by a JSON config file (``--config``). Tests inject fake
health paths, windows and thresholds that way; the real Collector files are never modified.
"""
from __future__ import annotations

import copy
import json
import os
import re

HOME = os.path.expanduser("~")

# Resource envelopes. R1 is the unattended default. R2/R3 need explicit opt-in (G5 ramp).
# cpu_quota_pct is the systemd CPUQuota (100 = one vCPU). Memory in bytes.
GIB = 1024 ** 3
PROFILES = {
    "R1": {"workers": 4, "cpu_quota_pct": 400, "memory_high": 8 * GIB, "memory_max": 10 * GIB,
           "tasks_max": 512, "oom_score_adj": 500, "max_runtime_s": 12 * 3600, "opt_in": None,
           "lock": "heavy"},
    "R2": {"workers": 6, "cpu_quota_pct": 600, "memory_high": 8 * GIB, "memory_max": 10 * GIB,
           "tasks_max": 512, "oom_score_adj": 500, "max_runtime_s": 12 * 3600,
           "opt_in": "allow_elevated", "lock": "heavy"},
    "R3": {"workers": 8, "cpu_quota_pct": 800, "memory_high": 8 * GIB, "memory_max": 10 * GIB,
           "tasks_max": 512, "oom_score_adj": 500, "max_runtime_s": 6 * 3600,
           "opt_in": "attended", "lock": "heavy"},
    # Light: unit tests / short joins. Separate lock so it does not block a heavy job slot,
    # but still admitted, capped and watched.
    "LIGHT": {"workers": 2, "cpu_quota_pct": 200, "memory_high": 2 * GIB, "memory_max": 3 * GIB,
              "tasks_max": 256, "oom_score_adj": 500, "max_runtime_s": 2 * 3600, "opt_in": None,
              "lock": "light"},
}

# Aggregate runtime ceiling applied to research.slice (never above R3 + watchdog headroom).
SLICE = {"name": "research.slice", "cpu_quota_pct": 800, "memory_max": 12 * GIB,
         "tasks_max": 1024, "cpu_weight": "idle"}

DEFAULTS = {
    "health_path": "/home/tradmin/research-data/trading-signal-bot/p2/forward-continuous-v1/health/collector_health.json",
    "monitor_status_path": "/home/tradmin/ops/tsb-p2-forward/monitor/p2-forward-continuous-v1/status.json",
    # G4: the monitor is the supervised systemd user service below. Its status.json names its writer
    # (supervisor/unit/pid/invocation); a status written by anything else is not trusted (fail closed).
    "monitor_unit": "tsb-p2f-monitor.service",
    "state_dir": os.path.join(HOME, ".local/state/research-runner"),
    "python": "/usr/bin/python3",
    # Protected windows (UTC). hourly: [start_min, end_min) ; daily: ["HH:MM","HH:MM") may wrap midnight.
    "windows_utc": [
        {"name": "hourly-seal", "hourly": [12, 25]},
        {"name": "day-close", "daily": ["23:50", "00:45"]},
        {"name": "nightly-seal-backups", "daily": ["01:10", "01:45"]},
    ],
    "admission": {
        "require_health": True,
        "health_age_s_max": 30,
        "durable_lag_ms_max": 5000,
        "beat_age_ms_max": 3000,
        "require_monitor_fresh": True,
        "monitor_status_age_s_max": 180,
        # allow-list (G4): anything else - DEGRADED, CRITICAL, STOPPED, missing, unknown - refuses
        "monitor_ok_severities": ["INFO", "WARNING"],
        "require_monitor_supervised": True,   # status.json written by the configured systemd unit
        "verify_monitor_unit": True,          # + unit active and its MainPID/InvocationID == the status writer
        "sample_s": 5.0,
        "steal_ratio_max": 0.40,
        "steal_vcpu_max": 1.0,
        "psi_cpu_some_avg60_max": 10.0,
        "psi_mem_some_avg60_max": 0.10,
        "memavail_margin_gib": 6.0,
        "disk_free_gb_min": 150.0,
    },
    "watchdog": {
        "interval_s": 2.0,
        "health_age_s_freeze": 30,
        "durable_lag_ms_freeze": 5000,
        "beat_age_ms_freeze": 3000,
        "loop_lag_ms_freeze": 5000,
        "monitor_ok_severities": ["INFO", "WARNING"],
        "monitor_status_age_s_freeze": 180,   # G4: a dead/hung/crash-looping monitor freezes research
        "steal_window_s": 5.0,
        "steal_vcpu_freeze": 2.0,
        "psi_mem_some_avg10_freeze": 1.0,
        "resume_clean_s": 120.0,
        "max_frozen_s": 4200.0,          # > longest protected window (55 min)
        "kill_memavail_gib": 3.0,
        "kill_psi_mem_full_avg10": 10.0,
        "pause_file": None,               # operator: touch this file to freeze research manually
        "sample_every_s": 30.0,           # telemetry 'sample' event in watchdog.jsonl
    },
}

JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:-]{0,63}$")


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    cfg["profiles"] = copy.deepcopy(PROFILES)
    cfg["slice"] = copy.deepcopy(SLICE)
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            over = json.load(fh)
        cfg = _merge(cfg, over)
    cfg["state_dir"] = os.path.expanduser(cfg["state_dir"])
    return cfg


def resolve_profile(cfg: dict, name: str, *, workers: int | None, allow_elevated: bool,
                    attended: bool, max_runtime_s: int | None) -> dict:
    """Return the effective envelope. Workers/runtime may only be LOWERED below the profile."""
    if name not in cfg["profiles"]:
        raise ValueError(f"unknown profile {name!r}; known: {sorted(cfg['profiles'])}")
    p = dict(cfg["profiles"][name])
    p["name"] = name
    need = p.get("opt_in")
    if need == "allow_elevated" and not (allow_elevated or attended):
        raise PermissionError(f"profile {name} requires --allow-elevated (G5 ramp, owner-approved)")
    if need == "attended" and not attended:
        raise PermissionError(f"profile {name} requires --attended (operator present)")
    if workers is not None:
        if workers < 1 or workers > p["workers"]:
            raise ValueError(f"workers must be 1..{p['workers']} for profile {name}")
        p["workers"] = workers
    if max_runtime_s is not None:
        if max_runtime_s < 1 or max_runtime_s > p["max_runtime_s"]:
            raise ValueError(f"max runtime must be 1..{p['max_runtime_s']} s for profile {name}")
        p["max_runtime_s"] = int(max_runtime_s)
    return p
