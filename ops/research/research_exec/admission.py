"""Admission control: decide whether a research job may START now.

All checks are read-only. The decision and every input are returned (and written to the job
record by the launcher) so refusals are auditable. The heavy-job lock is checked here as a
fast pre-check; the authoritative flock is taken by jobwrap inside the job unit.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import os

from . import hostsignals as hs


def lock_path(cfg: dict, lock_name: str) -> str:
    return os.path.join(cfg["state_dir"], f"{lock_name}.lock")


def lock_is_free(path: str) -> bool:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    finally:
        os.close(fd)


def evaluate(cfg: dict, profile: dict, *, now_utc: dt.datetime | None = None,
             steal_sample: dict | None = None, out_dir_for_disk: str | None = None) -> dict:
    """Return {"admit": bool, "reasons": [...], "inputs": {...}}. Never raises on probe errors:
    an unreadable input is itself a refusal reason (fail-closed)."""
    a = cfg["admission"]
    reasons, inputs = [], {}

    # 1. Collector health (direct file).
    if a.get("require_health", True):
        h = hs.read_health(cfg["health_path"])
        inputs["health"] = h
        if h.get("state") != "HEALTHY":
            reasons.append(f"collector_state={h.get('state')}")
        age = h.get("health_age_s")
        if age is None or age > a["health_age_s_max"]:
            reasons.append(f"health_stale age_s={age}")
        dl = h.get("durable_lag_ms")
        if dl is None or dl > a["durable_lag_ms_max"]:
            reasons.append(f"durable_lag_ms={dl}>{a['durable_lag_ms_max']}")
        ba = h.get("beat_age_ms")
        if ba is None or ba > a["beat_age_ms_max"]:
            reasons.append(f"beat_age_ms={ba}>{a['beat_age_ms_max']}")

    # 2. Independent monitor (severity; known WARNING incidents allowed).
    if a.get("require_monitor_fresh", True):
        m = hs.read_monitor(cfg["monitor_status_path"])
        inputs["monitor"] = m
        if m.get("severity") in a["monitor_bad_severities"] or m.get("severity") == "UNREADABLE":
            reasons.append(f"monitor_severity={m.get('severity')}")
        if m.get("age_s") is None or m["age_s"] > a["monitor_status_age_s_max"]:
            reasons.append(f"monitor_stale age_s={m.get('age_s')}")

    # 3. Protected window.
    inside, name = hs.in_protected_window(cfg["windows_utc"], now_utc)
    inputs["window"] = name
    if inside:
        reasons.append(f"protected_window={name}")

    # 4. Lock (fast pre-check).
    lp = lock_path(cfg, profile.get("lock", "heavy"))
    free = lock_is_free(lp)
    inputs["lock"] = {"path": lp, "free": free}
    if not free:
        reasons.append(f"lock_held={profile.get('lock', 'heavy')}")

    # 5. Host pressure: PSI, memory, disk, steal (sampled last: it sleeps).
    psi_cpu, psi_mem = hs.read_psi("cpu"), hs.read_psi("memory")
    inputs["psi_cpu"], inputs["psi_mem"] = psi_cpu, psi_mem
    if psi_cpu.get("some_avg60", 0.0) > a["psi_cpu_some_avg60_max"]:
        reasons.append(f"psi_cpu_some_avg60={psi_cpu.get('some_avg60')}")
    if psi_mem.get("some_avg60", 0.0) > a["psi_mem_some_avg60_max"]:
        reasons.append(f"psi_mem_some_avg60={psi_mem.get('some_avg60')}")
    memavail = hs.mem_available_gib()
    need = profile["memory_max"] / 1024 ** 3 + a["memavail_margin_gib"]
    inputs["mem_available_gib"] = round(memavail, 2)
    if memavail < need:
        reasons.append(f"mem_available_gib={memavail:.1f}<{need:.1f}")
    dpath = out_dir_for_disk or cfg["state_dir"]
    try:
        free_gb = hs.disk_free_gb(dpath)
    except OSError:
        free_gb = 0.0
    inputs["disk_free_gb"] = round(free_gb, 1)
    if free_gb < a["disk_free_gb_min"]:
        reasons.append(f"disk_free_gb={free_gb:.0f}<{a['disk_free_gb_min']}")
    st = steal_sample if steal_sample is not None else hs.sample_steal(a["sample_s"])
    inputs["steal"] = st
    if st["steal_ratio"] > a["steal_ratio_max"] and st["busy_vcpu"] + st["steal_vcpu"] > 0.5:
        # ratio is meaningless on a near-idle host; require some demand before judging it
        reasons.append(f"steal_ratio={st['steal_ratio']:.2f}>{a['steal_ratio_max']}")
    if st["steal_vcpu"] > a["steal_vcpu_max"]:
        reasons.append(f"steal_vcpu={st['steal_vcpu']:.2f}>{a['steal_vcpu_max']}")

    return {"admit": not reasons, "reasons": reasons, "inputs": inputs,
            "evaluated_at": (now_utc or dt.datetime.now(dt.timezone.utc)).isoformat()}
