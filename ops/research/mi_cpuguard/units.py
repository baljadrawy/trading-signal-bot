"""Rendered systemd --user commands for the MI CPU envelope (G3, G6). Pure functions: nothing is executed here.

Topology (verified 2026-10-08): 12 vCPU Neoverse-N1, 1 NUMA node, no SMT; user@1000 is delegated cpu/memory/pids
only (no cpuset, no io), so CPU *pinning* is impossible without root and the quota is a ceiling, not a reservation.

  research.slice            (runner: CPUQuota=800 %, CPUWeight=idle, MemorySwapMax=0)
   └─ research-mi.slice     (MI: CPUQuota=600 %, CPUWeight=idle, MemorySwapMax=0)   <- kernel rate cap, all descendants
       ├─ mi-anchor-<c>     sleep; keeps the slice cgroup (and its cumulative usage counter) alive for the campaign
       └─ rj-<job>          every MI job: BindsTo + Requisite + After the guard; RuntimeMaxSec
  app.slice
   └─ mi-cpuguard-<c>       the guard (outside the slice it limits); RuntimeMaxSec; Restart=no
"""
from __future__ import annotations

from . import QUOTA_PCT, SLICE


def slice_cmd(memory_max: str = "10G", tasks_max: int = 1024) -> list:
    return ["systemctl", "--user", "set-property", "--runtime", SLICE, f"CPUQuota={QUOTA_PCT}%", "CPUWeight=idle",
            f"MemoryMax={memory_max}", "MemorySwapMax=0", f"TasksMax={tasks_max}"]


def guard_unit(campaign: str) -> str:
    return f"mi-cpuguard-{campaign}.service"


def guard_cmd(campaign: str, python: str, args: list, runtime_max_s: int) -> list:
    return ["systemd-run", "--user", "--quiet", f"--unit={guard_unit(campaign)}", "--slice=app.slice",
            "-p", "CPUQuota=20%", "-p", "MemoryMax=64M", "-p", "MemorySwapMax=0", "-p", "Restart=no",
            # CollectMode: a dead guard is unloaded at once, so a BindsTo/Requisite job can never (re)start it
            # (integration finding I3: BindsTo= also pulls a start of a loaded-but-dead transient guard).
            "-p", "CollectMode=inactive-or-failed",
            "-p", f"RuntimeMaxSec={runtime_max_s}", python, "-m", "mi_cpuguard.guard_main", *args]


def anchor_cmd(campaign: str, runtime_max_s: int) -> list:
    g = guard_unit(campaign)
    return ["systemd-run", "--user", "--quiet", f"--unit=mi-anchor-{campaign}.service", f"--slice={SLICE}",
            "-p", f"BindsTo={g}", "-p", f"After={g}", "-p", f"Requisite={g}", "-p", "MemorySwapMax=0",
            "-p", f"RuntimeMaxSec={runtime_max_s}", "/bin/sleep", "infinity"]


def job_props(campaign: str, runtime_max_s: int) -> list:
    """Extra -p properties a future, approved runner integration would add to every MI job unit."""
    g = guard_unit(campaign)
    return [f"--slice={SLICE}", "-p", f"BindsTo={g}", "-p", f"Requisite={g}", "-p", f"After={g}",
            "-p", "MemorySwapMax=0", "-p", f"RuntimeMaxSec={runtime_max_s}"]
