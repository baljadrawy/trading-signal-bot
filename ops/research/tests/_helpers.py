"""Shared test helpers: fake Collector health/monitor files and an isolated config.

Nothing here touches the real Collector files: every path points into a temp directory.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MIB = 1024 ** 2


def write_health(path, state="HEALTHY", durable_lag_ms=100, beat_age_ms=50, ts_ms=None,
                 loop_lag_ms=100):
    doc = {"state": state, "ts_ms": int(time.time() * 1000) if ts_ms is None else ts_ms,
           "writer": {"alive": True, "durable_lag_ms": durable_lag_ms, "beat_age_ms": beat_age_ms},
           "instrumentation": {"loop_lag_max_60s_ms": loop_lag_ms}}
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(doc, fh)
    os.replace(tmp, path)


TEST_MONITOR_UNIT = "test-p2f-monitor.service"


def write_monitor(path, severity="WARNING", t_ms=None, supervisor="systemd-user", unit=TEST_MONITOR_UNIT,
                  pid=4242, invocation_id="inv-test"):
    """Fake G4 monitor status (writer identity block included unless supervisor is None)."""
    doc = {"severity": severity, "severity_reasons": ["incident:test"],
           "t_ms": int(time.time() * 1000) if t_ms is None else t_ms}
    if supervisor is not None:
        doc["monitor"] = {"supervisor": supervisor, "unit": unit, "pid": pid, "invocation_id": invocation_id,
                          "cid": "ab" * 32}
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(doc, fh)
    os.replace(tmp, path)


def make_env(base_dir=None, **over):
    """Create a temp dir with fake health/monitor files and a config JSON. Returns dict."""
    d = tempfile.mkdtemp(prefix="rexec-", dir=base_dir)
    health, monitor = os.path.join(d, "collector_health.json"), os.path.join(d, "status.json")
    write_health(health)
    write_monitor(monitor)
    cfg = {
        "health_path": health, "monitor_status_path": monitor, "monitor_unit": TEST_MONITOR_UNIT,
        "state_dir": os.path.join(d, "state"), "windows_utc": [],
        "admission": {"verify_monitor_unit": False, "sample_s": 0.3, "psi_cpu_some_avg60_max": 100.0,
                      "psi_mem_some_avg60_max": 100.0, "memavail_margin_gib": 0.0,
                      "disk_free_gb_min": 0.0, "steal_ratio_max": 1.0, "steal_vcpu_max": 100.0},
        "watchdog": {"monitor_status_age_s_freeze": 3600, "interval_s": 0.5, "steal_vcpu_freeze": 100.0, "psi_mem_some_avg10_freeze": 100.0,
                     "kill_psi_mem_full_avg10": 100.0, "kill_memavail_gib": 0.5,
                     "resume_clean_s": 2.0, "max_frozen_s": 120.0},
        "slice": {"name": "research.slice"},
        "profiles": {"TINT": {"workers": 2, "cpu_quota_pct": 200, "memory_high": 1024 * MIB,
                              "memory_max": 1536 * MIB, "tasks_max": 64, "oom_score_adj": 500,
                              "max_runtime_s": 300, "opt_in": None, "lock": "test-heavy"},
                     "TOOM": {"workers": 1, "cpu_quota_pct": 100, "memory_high": 128 * MIB,
                              "memory_max": 128 * MIB, "tasks_max": 32, "oom_score_adj": 500,
                              "max_runtime_s": 120, "opt_in": None, "lock": "test-oom"}},
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    cpath = os.path.join(d, "config.json")
    with open(cpath, "w") as fh:
        json.dump(cfg, fh, indent=2)
    return {"dir": d, "health": health, "monitor": monitor, "config": cpath}


def wait_until(pred, timeout_s, interval=0.2, what="condition"):
    """Bounded wait on a state predicate (never on process-name patterns)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(interval)
    raise TimeoutError(f"timed out after {timeout_s}s waiting for {what}")
