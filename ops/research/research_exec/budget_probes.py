"""Real-host probes for research_exec.budget (admission controller I-1b). Read-only, standard library only.

Every probe returns None when it cannot tell (budget refuses on None). Paths and commands are injectable so the probes
are testable against a fake /proc and /sys tree. NOT imported by admission, launcher or jobwrap: wiring is phase I-2
(shadow mode), enforcement needs owner approval.

  is_unit_active(unit)        systemctl --user is-active  -> True / False / None
  pid_start_ticks(pid)        field 22 of /proc/<pid>/stat (start time in clock ticks; defeats PID reuse)
  boot_id()                   /proc/sys/kernel/random/boot_id
  lab_slice_pct()             CPUQuotaPerSecUSec of tsblab.slice (0 when not loaded / no quota)
  marker_procs_outside_slice  own-uid processes with RESEARCH_JOB_ID in their environment whose cgroup is not under
                              research.slice (or research-mi.slice)
  slice_quota_pct()           CPUQuotaPerSecUSec of research.slice as a percentage (None = unlimited / unreadable)
  live_job_units()            loaded, active rj-*.service user units
"""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import time
from typing import Callable, Optional

from . import budget as B

SystemctlRunner = Callable[[list], Optional[str]]


def _systemctl(args: list) -> Optional[str]:
    try:
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode in (0, 3, 4) else None      # is-active: 3 = inactive, 4 = no such unit


def is_unit_active(unit: str, run: SystemctlRunner = _systemctl) -> Optional[bool]:
    out = run(["is-active", unit])
    if out is None:
        return None
    s = out.strip().splitlines()[0] if out.strip() else ""
    if s in ("active", "activating", "deactivating", "reloading", "refreshing"):
        return True
    if s in ("inactive", "failed", "dead"):
        return False
    return None                                                  # unknown state: refuse


def pid_start_ticks(pid: int, proc: str = "/proc") -> Optional[int]:
    try:
        with open(os.path.join(proc, str(int(pid)), "stat")) as fh:
            raw = fh.read()
    except (OSError, ValueError):
        return None
    try:                                                         # comm may contain spaces/parens: split after last ')'
        rest = raw[raw.rindex(")") + 2:].split()
        return int(rest[19])                                     # field 22 overall = index 19 after pid and comm
    except (ValueError, IndexError):
        return None


def boot_id(path: str = "/proc/sys/kernel/random/boot_id") -> str:
    with open(path) as fh:
        return fh.read().strip()


def _quota_pct(value: Optional[str]) -> Optional[int]:
    """CPUQuotaPerSecUSec=1.5s -> 150 ; 800ms -> 80 ; infinity -> None."""
    if value is None:
        return None
    v = value.strip()
    if v in ("", "infinity"):
        return None
    m = re.fullmatch(r"([\d.]+)(us|ms|s|min)", v)
    if not m:
        return None
    sec = float(m.group(1)) * {"us": 1e-6, "ms": 1e-3, "s": 1.0, "min": 60.0}[m.group(2)]
    return int(round(sec * 100))


def _show(unit: str, prop: str, run: SystemctlRunner) -> Optional[dict]:
    out = run(["show", "-p", f"LoadState,ActiveState,{prop}", unit])
    if out is None:
        return None
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l)


def slice_quota_pct(name: str = "research.slice", run: SystemctlRunner = _systemctl) -> Optional[int]:
    p = _show(name, "CPUQuotaPerSecUSec", run)
    return None if p is None else _quota_pct(p.get("CPUQuotaPerSecUSec"))


def lab_slice_pct(name: str = "tsblab.slice", run: SystemctlRunner = _systemctl) -> Optional[int]:
    p = _show(name, "CPUQuotaPerSecUSec", run)
    if p is None:
        return None
    if p.get("LoadState") != "loaded" or p.get("ActiveState") != "active":
        return 0                                                 # no active lab slice
    q = _quota_pct(p.get("CPUQuotaPerSecUSec"))
    return q if q is not None else None                          # an active lab slice without a quota is not safe


def marker_procs_outside_slice(proc: str = "/proc", uid: Optional[int] = None,
                               allowed=("/research.slice/", "/research-mi.slice/")) -> Optional[list]:
    """Own-uid processes carrying the runner's job marker outside the research slices. None if /proc is unreadable."""
    uid = os.getuid() if uid is None else uid
    hits = []
    try:
        entries = [e for e in os.listdir(proc) if e.isdigit()]
    except OSError:
        return None
    for e in entries:
        base = os.path.join(proc, e)
        try:
            if os.stat(base).st_uid != uid:
                continue
            with open(os.path.join(base, "environ"), "rb") as fh:
                env = fh.read().split(b"\0")
            if not any(x.startswith(b"RESEARCH_JOB_ID=") for x in env):
                continue
            with open(os.path.join(base, "cgroup")) as fh:
                cg = fh.read().strip().splitlines()[-1].split(":", 2)[-1]
        except OSError:
            continue                                             # process exited meanwhile / not ours
        if not any(a in cg + "/" for a in allowed):
            hits.append({"pid": int(e), "cgroup": cg})
    return hits


def live_job_units(run: SystemctlRunner = _systemctl) -> Optional[list]:
    out = run(["list-units", "--all", "--no-legend", "--plain", "rj-*.service"])
    if out is None:
        return None
    units = []
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 3 and f[0].startswith("rj-") and f[2] in ("active", "activating", "deactivating"):
            units.append(f[0])
    return units


def host_probes() -> B.Probes:
    return B.Probes(is_unit_active=is_unit_active, pid_start_ticks=pid_start_ticks, boot_id=boot_id,
                    wall_utc=lambda: dt.datetime.now(dt.timezone.utc), mono_s=time.monotonic,
                    lab_slice_pct=lab_slice_pct, marker_procs_outside_slice=marker_procs_outside_slice,
                    slice_quota_pct=slice_quota_pct, live_job_units=live_job_units)
