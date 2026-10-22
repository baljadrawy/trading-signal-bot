"""Admission control: decide whether a research job may START now.

All checks are read-only. The decision and every input are returned (and written to the job
record by the launcher) so refusals are auditable. The heavy-job lock is checked here as a
fast pre-check; the authoritative flock is taken by jobwrap inside the job unit.
"""
from __future__ import annotations

import copy
import datetime as dt
import fcntl
import os

from . import hostsignals as hs

# Required probes: no fail-closed return value exists for them, so an exception aborts the shadow computation.
_STRICT_PROBES = ("pid_start_ticks", "boot_id", "wall_utc", "mono_s")


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


def budget_shadow(cfg: dict, profile: dict, job_id: str | None = None, probes=None) -> dict:
    """Phase I-2 (shadow only): the aggregate-budget decision `budget.check` WOULD make, computed on a reconciled
    COPY of budget.json. Read-only: no reservation, no lock, no state write, no directory creation. Never raises;
    any probe or state error is recorded in `probe_errors` and makes the shadow decision refuse (fail closed).
    The result is informational: `evaluate` never lets it change the real `admit` / `reasons`."""
    out = {"admit": False, "reasons": [], "capacity_pct": None, "held_pct": None, "probe_errors": []}
    errs = out["probe_errors"]
    try:
        from . import budget as B
        bcfg = {**B.DEFAULTS, **(cfg.get("budget") or {})}
        if probes is None:
            from . import budget_probes as BP
            probes = BP.host_probes()

        def _guard(name, fn):
            def call(*a):
                try:
                    return fn(*a)
                except Exception as e:  # noqa: BLE001 - shadow must never raise
                    errs.append(f"{name}: {type(e).__name__}: {e}")
                    if name in _STRICT_PROBES:
                        raise
                    return None                    # None = "cannot tell": budget refuses on it
            return call

        safe = copy.copy(probes)
        for name in ("is_unit_active", "pid_start_ticks", "boot_id", "wall_utc", "mono_s", "lab_slice_pct",
                     "marker_procs_outside_slice", "slice_quota_pct", "live_job_units"):
            setattr(safe, name, _guard(name, getattr(probes, name)))
        path = os.path.join(bcfg.get("state_dir") or cfg["state_dir"], "budget.json")
        try:
            st = B.load(path)                      # plain read; budget.json is only ever replaced atomically
        except B.BudgetStateError as e:
            out["reasons"] = [f"budget_state_unreadable: {e}"]
            return out
        st, rec_reasons, _reclaimed = B.reconcile(copy.deepcopy(st), safe, bcfg)
        req = B.Request(job_id=job_id or "?", unit=f"rj-{job_id or '?'}.service",
                        profile=str(profile.get("name", "?")), pct=int(profile["cpu_quota_pct"]),
                        pid=os.getpid(), max_runtime_s=int(profile.get("max_runtime_s", 0)))
        d = B.check(st, req, safe, bcfg)
        out.update(reasons=rec_reasons + d.reasons, capacity_pct=d.capacity_pct, held_pct=d.held_pct)
    except Exception as e:  # noqa: BLE001 - shadow must never raise
        if not errs or not errs[-1].endswith(str(e)):
            errs.append(f"shadow: {type(e).__name__}: {e}")
    if errs and "probe_error" not in out["reasons"]:
        out["reasons"].append("probe_error")
    out["admit"] = not out["reasons"]
    return out


def evaluate(cfg: dict, profile: dict, *, now_utc: dt.datetime | None = None,
             steal_sample: dict | None = None, out_dir_for_disk: str | None = None,
             job_id: str | None = None, budget_probes=None) -> dict:
    """Return {"admit": bool, "reasons": [...], "inputs": {...}}. Never raises on probe errors:
    an unreadable input is itself a refusal reason (fail-closed).

    With config `budget.shadow` true (default False) the decision also carries `budget_shadow` (see
    `budget_shadow`); it never changes `admit` or `reasons`. With it off the output is unchanged."""
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

    # 2. Independent monitor (G4): fresh, allow-listed severity (known WARNING incidents allowed), written by
    #    the configured supervised unit, and that unit is active with the writer as its main process.
    if a.get("require_monitor_fresh", True):
        m = hs.read_monitor(cfg["monitor_status_path"])
        unit = cfg.get("monitor_unit") if a.get("require_monitor_supervised", True) else None
        us = hs.unit_state(unit) if unit and a.get("verify_monitor_unit", True) else None
        inputs["monitor"] = dict(m, unit_state=us)
        reasons += hs.monitor_problems(m, ok_severities=a["monitor_ok_severities"],
                                       max_age_s=a["monitor_status_age_s_max"], monitor_unit=unit, unit=us)

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

    decision = {"admit": not reasons, "reasons": reasons, "inputs": inputs,
                "evaluated_at": (now_utc or dt.datetime.now(dt.timezone.utc)).isoformat()}
    if (cfg.get("budget") or {}).get("shadow") is True:
        decision["budget_shadow"] = budget_shadow(cfg, profile, job_id, budget_probes)
    return decision
