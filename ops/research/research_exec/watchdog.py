"""Protection watchdog (main process of rw-<id>.service).

Lifetime is tied to the job unit three ways: systemd BindsTo=/After= the job unit (stopped
when the job stops), its own loop exits as soon as the job unit is inactive, and its own
RuntimeMaxSec is a hard upper bound. If it ever has to exit while the job is still active
(e.g. it was stopped by hand) it STOPS the job: research never runs unsupervised.

Per tick: read Collector health + monitor + steal + PSI + MemAvailable + windows + pause file.
  any freeze trigger  -> systemctl --user freeze <job>   (paused, not destroyed)
  clean for resume_clean_s while frozen -> thaw
  frozen longer than max_frozen_s, or memory danger -> group kill (SIGKILL whole cgroup), stop
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from . import hostsignals as hs
from .record import append_jsonl, atomic_write_json, read_json, utc_now


def sysctl_user(*args, timeout=20) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                          timeout=timeout)


def unit_props(unit: str) -> dict:
    r = sysctl_user("show", "-p",
                    "LoadState,ActiveState,SubState,FreezerState,ControlGroup,MainPID,Result", unit)
    return dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)


def freeze_triggers(cfg: dict, health: dict, monitor: dict | None, steal_vcpu: float | None,
                    psi_mem: dict, window: str | None, pause_file_present: bool) -> list[str]:
    """Pure function: list of reasons to be frozen right now (empty = clean)."""
    w = cfg["watchdog"]
    r = []
    if health.get("state") != "HEALTHY":
        r.append(f"collector_state={health.get('state')}")
    age = health.get("health_age_s")
    if age is None or age > w["health_age_s_freeze"]:
        r.append(f"health_stale age_s={None if age is None else round(age, 1)}")
    dl = health.get("durable_lag_ms")
    if dl is None or dl > w["durable_lag_ms_freeze"]:
        r.append(f"durable_lag_ms={dl}")
    ba = health.get("beat_age_ms")
    if ba is None or ba > w["beat_age_ms_freeze"]:
        r.append(f"beat_age_ms={ba}")
    ll = health.get("loop_lag_max_60s_ms")
    if ll is not None and ll > w["loop_lag_ms_freeze"]:
        r.append(f"loop_lag_ms={ll}")
    if monitor and monitor.get("severity") in w["monitor_bad_severities"]:
        r.append(f"monitor_severity={monitor.get('severity')}")
    if steal_vcpu is not None and steal_vcpu > w["steal_vcpu_freeze"]:
        r.append(f"steal_vcpu={steal_vcpu:.2f}")
    if psi_mem.get("some_avg10", 0.0) > w["psi_mem_some_avg10_freeze"]:
        r.append(f"psi_mem_some_avg10={psi_mem.get('some_avg10')}")
    if window:
        r.append(f"protected_window={window}")
    if pause_file_present:
        r.append("operator_pause_file")
    return r


def kill_triggers(cfg: dict, memavail_gib: float, psi_mem: dict, frozen_for_s: float) -> list[str]:
    w = cfg["watchdog"]
    r = []
    if memavail_gib < w["kill_memavail_gib"]:
        r.append(f"mem_available_gib={memavail_gib:.2f}<{w['kill_memavail_gib']}")
    if psi_mem.get("full_avg10", 0.0) > w["kill_psi_mem_full_avg10"]:
        r.append(f"psi_mem_full_avg10={psi_mem.get('full_avg10')}")
    if frozen_for_s > w["max_frozen_s"]:
        r.append(f"frozen_for_s={frozen_for_s:.0f}>{w['max_frozen_s']}")
    return r


class Watchdog:
    def __init__(self, cfg: dict, job_dir: str, unit: str):
        self.cfg, self.job_dir, self.unit = cfg, job_dir, unit
        self.events = os.path.join(job_dir, "watchdog.jsonl")
        self.frozen_since = None      # monotonic
        self.clean_since = None
        self.periods = []             # [{start, end, seconds, reasons}]
        self.kills = []
        self.last_cg = {}
        self.max_mem_current = 0
        self.cg_dir = None
        self.stop_requested = False
        self.ticks = 0
        self.steal_hist = []          # [(cpu_ticks)]
        self.started_at = utc_now()
        self.t_start = time.monotonic()
        self.next_sample = self.t_start
        self.last_steal = None

    def log(self, kind, **kw):
        append_jsonl(self.events, {"ts": utc_now(), "event": kind, **kw})

    def _steal_vcpu(self):
        now = hs.read_cpu_ticks()
        self.steal_hist.append(now)
        win = self.cfg["watchdog"]["steal_window_s"]
        while len(self.steal_hist) > 2 and now["t"] - self.steal_hist[1]["t"] >= win:
            self.steal_hist.pop(0)
        if len(self.steal_hist) < 2 or now["t"] - self.steal_hist[0]["t"] < win * 0.8:
            return None
        return hs.steal_between(self.steal_hist[0], now)["steal_vcpu"]

    def _sample_cgroup(self):
        if self.cg_dir:
            cg = hs.cgroup_stats(self.cg_dir)
            if cg.get("cpu_usage_usec") is not None:
                self.last_cg = cg
                self.max_mem_current = max(self.max_mem_current, cg.get("memory_current") or 0)

    def freeze(self, reasons):
        r = sysctl_user("freeze", self.unit)
        self.frozen_since = time.monotonic()
        self.periods.append({"start": utc_now(), "end": None, "seconds": None, "reasons": reasons,
                             "_t0": self.frozen_since})
        self.log("freeze", reasons=reasons, rc=r.returncode, stderr=r.stderr.strip()[:300])

    def thaw(self, why):
        r = sysctl_user("thaw", self.unit)
        p = self.periods[-1]
        p["end"], p["seconds"] = utc_now(), round(time.monotonic() - p.pop("_t0"), 3)
        self.frozen_since = None
        self.log("thaw", why=why, rc=r.returncode, frozen_s=p["seconds"])

    def group_kill(self, reasons):
        self._sample_cgroup()
        r1 = sysctl_user("kill", "--kill-whom=all", "--signal=SIGKILL", self.unit)
        # --no-block: stopping the job also stops this watchdog (BindsTo); never wait on ourselves.
        r2 = sysctl_user("stop", "--no-block", self.unit)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if unit_props(self.unit).get("ActiveState") in ("inactive", "failed", ""):
                break
            time.sleep(0.3)
        self.kills.append({"at": utc_now(), "reasons": reasons})
        if self.periods and self.periods[-1]["end"] is None:
            p = self.periods[-1]
            p["end"], p["seconds"] = utc_now(), round(time.monotonic() - p.pop("_t0"), 3)
        self.frozen_since = None
        self.log("group_kill", reasons=reasons, kill_rc=r1.returncode, stop_rc=r2.returncode)

    def run(self) -> int:
        w = self.cfg["watchdog"]
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stop_requested", True))
        props = unit_props(self.unit)
        self.cg_dir = "/sys/fs/cgroup" + props.get("ControlGroup", "") if props.get("ControlGroup") else None
        self.log("start", unit=self.unit, props=props, pid=os.getpid(),
                 cfg_watchdog=w, health_path=self.cfg["health_path"])
        while True:
            props = unit_props(self.unit)
            active = props.get("ActiveState") in ("active", "activating", "reloading")
            if not active:
                break
            if self.stop_requested:
                # Being stopped while the job is still active -> fail closed: stop the job.
                self.group_kill(["watchdog_stopping_while_job_active"])
                break
            self.ticks += 1
            self._sample_cgroup()
            health = hs.read_health(self.cfg["health_path"])
            mon = hs.read_monitor(self.cfg["monitor_status_path"]) \
                if self.cfg["admission"].get("require_monitor_fresh", True) else None
            psi_mem = hs.read_psi("memory")
            window = hs.in_protected_window(self.cfg["windows_utc"])[1]
            pf = w.get("pause_file")
            self.last_steal = self._steal_vcpu()
            reasons = freeze_triggers(self.cfg, health, mon, self.last_steal, psi_mem, window,
                                      bool(pf and os.path.exists(pf)))
            frozen_for = (time.monotonic() - self.frozen_since) if self.frozen_since else 0.0
            memavail = hs.mem_available_gib()
            if time.monotonic() >= self.next_sample:
                # low-rate telemetry for capacity work (G5): Collector + host + job, every N s
                self.next_sample = time.monotonic() + w.get("sample_every_s", 30.0)
                self.log("sample", durable_lag_ms=health.get("durable_lag_ms"),
                         beat_age_ms=health.get("beat_age_ms"),
                         loop_lag_max_60s_ms=health.get("loop_lag_max_60s_ms"),
                         collector_state=health.get("state"), steal_vcpu=self.last_steal,
                         psi_mem_some_avg10=psi_mem.get("some_avg10"),
                         psi_cpu_some_avg10=hs.read_psi("cpu").get("some_avg10"),
                         mem_available_gib=round(memavail, 2),
                         job_cpu_usage_usec=self.last_cg.get("cpu_usage_usec"),
                         job_memory_current=self.last_cg.get("memory_current"),
                         job_nr_throttled=self.last_cg.get("nr_throttled"),
                         frozen=self.frozen_since is not None)
            kr = kill_triggers(self.cfg, memavail, psi_mem, frozen_for)
            if kr:
                self.group_kill(kr)
                break
            if reasons:
                self.clean_since = None
                if self.frozen_since is None:
                    self.freeze(reasons)
                elif props.get("FreezerState") != "frozen":
                    # someone thawed it by hand while still degraded: re-freeze
                    sysctl_user("freeze", self.unit)
                    self.log("refreeze", reasons=reasons)
            elif self.frozen_since is not None:
                self.clean_since = self.clean_since or time.monotonic()
                if time.monotonic() - self.clean_since >= w["resume_clean_s"]:
                    self.thaw("clean_for_resume_window")
                    self.clean_since = None
            # interruptible sleep
            end = time.monotonic() + w["interval_s"]
            while time.monotonic() < end and not self.stop_requested:
                time.sleep(min(0.2, end - time.monotonic()) if end > time.monotonic() else 0)
        return self.finish()

    def finish(self) -> int:
        if self.periods and self.periods[-1]["end"] is None:
            p = self.periods[-1]
            p["end"], p["seconds"] = utc_now(), round(time.monotonic() - p.pop("_t0"), 3)
        props = unit_props(self.unit)
        if props.get("ActiveState") == "failed":
            sysctl_user("reset-failed", self.unit)     # recorded below; do not leave it loaded
        summary = {"started_at": self.started_at, "ended_at": utc_now(), "ticks": self.ticks,
                   "lifetime_s": round(time.monotonic() - self.t_start, 3),
                   "freeze_periods": self.periods,
                   "frozen_total_s": round(sum(p["seconds"] or 0 for p in self.periods), 3),
                   "group_kills": self.kills, "last_cgroup_sample": self.last_cg,
                   "max_memory_current_sampled": self.max_mem_current,
                   "job_unit_final": {k: props.get(k) for k in ("LoadState", "ActiveState", "Result")}}
        atomic_write_json(os.path.join(self.job_dir, "watchdog_summary.json"), summary)
        build_job_record(self.job_dir)
        self.log("exit", job_state=props.get("ActiveState"), result=props.get("Result"))
        return 0


def _status(jw: dict, wd: dict) -> str:
    if jw.get("status") in ("finished", "lock_busy"):
        return jw["status"]
    if wd.get("group_kills"):
        return "killed"                      # watchdog escalation
    result = (wd.get("job_unit_final") or {}).get("Result")
    if result == "oom-kill":
        return "oom-killed"                  # kernel cgroup OOM, whole group killed
    if result == "timeout":
        return "timeout"                     # RuntimeMaxSec reached
    return "terminated" if wd else "unknown"


def build_job_record(job_dir: str) -> dict:
    """Merge launcher, jobwrap and watchdog records into job_record.json (idempotent)."""
    launch = read_json(os.path.join(job_dir, "launch.json")) or {}
    adm = read_json(os.path.join(job_dir, "admission.json")) or {}
    jw = read_json(os.path.join(job_dir, "jobwrap.json")) or {}
    wd = read_json(os.path.join(job_dir, "watchdog_summary.json")) or {}
    cg = jw.get("cgroup_at_exit") or wd.get("last_cgroup_sample") or {}
    frozen = wd.get("frozen_total_s", 0.0) or 0.0
    wall = jw.get("wall_s")
    wall_src = "jobwrap"
    if wall is None and wd.get("lifetime_s") is not None:
        wall, wall_src = wd["lifetime_s"], "watchdog_lifetime_approx"
    cpu_s = (cg.get("cpu_usage_usec") or 0) / 1e6
    rec = {
        "job_id": launch.get("job_id"), "owner": launch.get("owner"), "profile": launch.get("profile"),
        "units": launch.get("units"), "cmd": launch.get("cmd"),
        "admission": {"admit": adm.get("admit"), "reasons": adm.get("reasons")},
        "status": _status(jw, wd),
        "exit_code": jw.get("exit_code") if jw.get("status") in ("finished", "lock_busy") else None,
        "job_unit_final": wd.get("job_unit_final"),
        "wall_s": wall,
        "wall_s_source": wall_src,
        "frozen_total_s": frozen,
        "active_wall_s": round(wall - frozen, 3) if wall is not None else None,
        "cpu_s_cgroup": round(cpu_s, 3),
        "cpu_s_rusage": (round(jw["rusage_children"]["utime_s"] + jw["rusage_children"]["stime_s"], 3)
                         if jw.get("rusage_children") else None),
        "cpu_parallelism": round(cpu_s / (wall - frozen), 3) if wall and wall - frozen > 0 else None,
        "memory_peak_bytes": cg.get("memory_peak") or wd.get("max_memory_current_sampled"),
        "pids_peak": cg.get("pids_peak"),
        "throttled_usec": cg.get("throttled_usec"),
        "mem_events": cg.get("mem_events"),
        "freeze_periods": wd.get("freeze_periods"),
        "group_kills": wd.get("group_kills"),
        "measurement_source": "jobwrap_at_exit" if jw.get("cgroup_at_exit") else "watchdog_last_sample",
    }
    atomic_write_json(os.path.join(job_dir, "job_record.json"), rec)
    return rec


def main(cfg: dict, job_dir: str, unit: str) -> int:
    return Watchdog(cfg, job_dir, unit).run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(1)
