"""Read-only host and Collector probes. Nothing here writes outside the job directory."""
from __future__ import annotations

import datetime as dt
import json
import os
import time

CLK_TCK = os.sysconf("SC_CLK_TCK")


# ---------------------------------------------------------------- Collector health
def read_health(path: str, now: float | None = None) -> dict:
    """Return a flat view of the Collector health file. Never raises; errors become state=UNREADABLE."""
    now = time.time() if now is None else now
    try:
        with open(path, "r", encoding="utf-8") as fh:
            h = json.load(fh)
    except Exception as exc:  # missing, partial write, permission
        return {"state": "UNREADABLE", "error": f"{type(exc).__name__}: {exc}", "path": path}
    w = h.get("writer") or {}
    inst = h.get("instrumentation") or {}
    ts_ms = h.get("ts_ms")
    age = (now - ts_ms / 1000.0) if isinstance(ts_ms, (int, float)) else None
    return {
        "state": h.get("state"),
        "health_age_s": age,
        "durable_lag_ms": w.get("durable_lag_ms"),
        "beat_age_ms": w.get("beat_age_ms"),
        "writer_alive": w.get("alive"),
        "loop_lag_max_60s_ms": inst.get("loop_lag_max_60s_ms"),
        "path": path,
    }


def read_monitor(path: str, now: float | None = None) -> dict:
    """Flat view of the monitor status. age_s is the OLDER of file mtime and the content timestamp t_ms, so
    neither a touched file nor a copied old document looks fresh. Never raises (UNREADABLE instead)."""
    now = time.time() if now is None else now
    try:
        st = os.stat(path)
        with open(path, "r", encoding="utf-8") as fh:
            s = json.load(fh)
    except Exception as exc:
        return {"severity": "UNREADABLE", "error": f"{type(exc).__name__}: {exc}", "age_s": None}
    ages = [now - st.st_mtime]
    t_ms = s.get("t_ms")
    if isinstance(t_ms, (int, float)):
        ages.append(now - t_ms / 1000.0)
    w = s.get("monitor") if isinstance(s.get("monitor"), dict) else {}
    return {"severity": s.get("severity"), "severity_reasons": s.get("severity_reasons"),
            "age_s": max(ages), "t_ms": t_ms,
            "writer": {k: w.get(k) for k in ("supervisor", "unit", "pid", "invocation_id", "cid")}}


def unit_state(unit: str) -> dict:
    """systemctl --user show (read-only) for the monitor unit. {} when systemctl is unavailable."""
    import subprocess
    try:
        r = subprocess.run(["systemctl", "--user", "show", "-p", "ActiveState,SubState,MainPID,InvocationID", unit],
                           capture_output=True, text=True, timeout=10)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    return dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)


def monitor_problems(m: dict, *, ok_severities, max_age_s, monitor_unit: str | None,
                     unit: dict | None = None) -> list[str]:
    """Pure trust rule shared by admission and watchdog (empty list = trusted and clean).

    Fail closed on: unreadable / missing, stale (dead, hung or crash-looping monitor), any severity outside the
    allow-list, a writer that is not the configured systemd unit (legacy or manual monitor), and - when the
    unit state is supplied - an inactive unit or a writer pid/invocation that is not the unit's current one."""
    r = []
    sev = m.get("severity")
    if sev == "UNREADABLE":
        r.append("monitor_unreadable")
    elif sev not in ok_severities:
        r.append(f"monitor_severity={sev}")
    age = m.get("age_s")
    if age is None or age > max_age_s:
        r.append(f"monitor_stale age_s={None if age is None else round(age, 1)}")
    if monitor_unit and sev != "UNREADABLE":
        w = m.get("writer") or {}
        if w.get("supervisor") != "systemd-user" or w.get("unit") != monitor_unit:
            r.append(f"monitor_unsupervised writer={w.get('supervisor')}/{w.get('unit')}")
        if unit is not None:
            if unit.get("ActiveState") != "active":
                r.append(f"monitor_unit_state={unit.get('ActiveState')}/{unit.get('SubState')}")
            elif str(w.get("pid")) != unit.get("MainPID") or w.get("invocation_id") != unit.get("InvocationID"):
                r.append(f"monitor_writer_not_unit_main writer_pid={w.get('pid')} main_pid={unit.get('MainPID')}")
    return r


# ---------------------------------------------------------------- CPU / steal
def read_cpu_ticks(stat_path: str = "/proc/stat") -> dict:
    with open(stat_path, "r") as fh:
        for line in fh:
            if line.startswith("cpu "):
                f = [int(x) for x in line.split()[1:]]
                f += [0] * (10 - len(f))
                user, nice, system, idle, iowait, irq, softirq, steal = f[:8]
                # guest/guest_nice are already included in user/nice
                return {"busy": user + nice + system + irq + softirq, "idle": idle + iowait,
                        "steal": steal, "t": time.monotonic()}
    raise RuntimeError("no aggregate cpu line in /proc/stat")


def steal_between(a: dict, b: dict) -> dict:
    dt_s = max(b["t"] - a["t"], 1e-6)
    d_steal = max(b["steal"] - a["steal"], 0)
    d_busy = max(b["busy"] - a["busy"], 0)
    denom = d_busy + d_steal
    return {"interval_s": dt_s,
            "steal_vcpu": d_steal / CLK_TCK / dt_s,
            "busy_vcpu": d_busy / CLK_TCK / dt_s,
            "steal_ratio": (d_steal / denom) if denom else 0.0}


def sample_steal(seconds: float) -> dict:
    a = read_cpu_ticks()
    time.sleep(max(seconds, 0.2))
    return steal_between(a, read_cpu_ticks())


# ---------------------------------------------------------------- PSI / memory / disk
def read_psi(resource: str, base: str = "/proc/pressure") -> dict:
    out = {}
    try:
        with open(os.path.join(base, resource), "r") as fh:
            for line in fh:
                parts = line.split()
                kind = parts[0]
                for kv in parts[1:]:
                    k, v = kv.split("=")
                    if k.startswith("avg"):
                        out[f"{kind}_{k}"] = float(v)
    except FileNotFoundError:
        pass
    return out


def mem_available_gib(path: str = "/proc/meminfo") -> float:
    with open(path, "r") as fh:
        for line in fh:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / (1024 ** 2)
    raise RuntimeError("MemAvailable not found")


def disk_free_gb(path: str) -> float:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / 1e9


# ---------------------------------------------------------------- protected windows
def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def in_protected_window(windows: list, now_utc: dt.datetime | None = None):
    """Return (True, name) if now is inside any window. Ranges are half-open [start, end)."""
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    minute_of_day = now_utc.hour * 60 + now_utc.minute
    for w in windows or []:
        name = w.get("name", "window")
        if "hourly" in w:
            s, e = w["hourly"]
            if s <= now_utc.minute < e:
                return True, name
        elif "daily" in w:
            s, e = _hm(w["daily"][0]), _hm(w["daily"][1])
            inside = (s <= minute_of_day < e) if s <= e else (minute_of_day >= s or minute_of_day < e)
            if inside:
                return True, name
    return False, None


# ---------------------------------------------------------------- cgroup of a unit
def cgroup_stats(cg_dir: str) -> dict:
    """Read accounting files of a cgroup directory (absolute /sys/fs/cgroup/... path)."""
    out = {}

    def _kv(name):
        try:
            with open(os.path.join(cg_dir, name)) as fh:
                return {l.split()[0]: int(l.split()[1]) for l in fh if l.strip()}
        except (FileNotFoundError, ProcessLookupError, OSError):
            return None

    def _one(name):
        try:
            with open(os.path.join(cg_dir, name)) as fh:
                return fh.read().strip()
        except (FileNotFoundError, OSError):
            return None

    cpu = _kv("cpu.stat")
    if cpu:
        out["cpu_usage_usec"] = cpu.get("usage_usec")
        out["cpu_user_usec"] = cpu.get("user_usec")
        out["cpu_system_usec"] = cpu.get("system_usec")
        out["nr_throttled"] = cpu.get("nr_throttled")
        out["throttled_usec"] = cpu.get("throttled_usec")
    ev = _kv("memory.events")
    if ev:
        out["mem_events"] = ev
    for f, k in (("memory.peak", "memory_peak"), ("memory.current", "memory_current"),
                 ("pids.peak", "pids_peak"), ("pids.current", "pids_current")):
        v = _one(f)
        if v is not None and v.isdigit():
            out[k] = int(v)
    for f in ("cpu.max", "memory.max", "memory.high", "pids.max", "memory.oom.group", "cpu.idle"):
        v = _one(f)
        if v is not None:
            out[f] = v
    events = _one("cgroup.events")
    if events:
        out["cgroup_events"] = dict(l.split() for l in events.splitlines() if l.strip())
    return out


def own_cgroup_dir() -> str | None:
    try:
        with open("/proc/self/cgroup") as fh:
            for line in fh:
                if line.startswith("0::"):
                    return "/sys/fs/cgroup" + line.strip()[3:]
    except OSError:
        pass
    return None
