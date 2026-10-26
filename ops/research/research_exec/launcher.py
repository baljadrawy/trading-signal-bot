"""Launch a research job as two bounded, attributable systemd --user transient services.

  rj-<id>.service  in research.slice   the job (jobwrap -> your command), with the envelope:
                   CPUQuota, CPUWeight=idle, MemoryHigh/Max, TasksMax, OOMScoreAdjust=+500,
                   OOMPolicy=kill (memory.oom.group=1), KillMode=control-group, RuntimeMaxSec.
  rw-<id>.service  in app.slice        the watchdog: BindsTo= + After= the job, small envelope,
                   RuntimeMaxSec = job max + 15 min. Stops when the job stops.

research.slice gets RUNTIME-ONLY properties (CPUWeight=idle + an aggregate ceiling) via
`systemctl --user set-property --runtime`; they live under /run/user/<uid>/systemd/user.control
and vanish on user-manager restart. Revert: `systemctl --user revert research.slice`.
No root, no persistent unit files, no host-wide policy change.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time

from . import admission as adm
from .config import JOB_ID_RE, OWNER_RE
from .record import atomic_write_json, read_json, utc_now

PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(args, timeout=60, check=False):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"{shlex.join(args)} -> rc={r.returncode}: {r.stderr.strip()}")
    return r


def unit_names(job_id: str) -> tuple[str, str]:
    return f"rj-{job_id}.service", f"rw-{job_id}.service"


def active_state(unit: str) -> str:
    r = _run(["systemctl", "--user", "show", "-p", "ActiveState", "--value", unit])
    return r.stdout.strip()


def ensure_slice(cfg: dict) -> dict:
    s = cfg["slice"]
    args = ["systemctl", "--user", "set-property", "--runtime", s["name"],
            f"CPUQuota={s['cpu_quota_pct']}%", f"MemoryMax={s['memory_max']}",
            "MemorySwapMax=0",  # G6 step 1: research never uses host swap
            f"TasksMax={s['tasks_max']}", f"CPUWeight={s['cpu_weight']}"]
    r = _run(args)
    return {"cmd": args, "rc": r.returncode, "stderr": r.stderr.strip()}


def build_job_cmd(cfg, job_id, owner, profile, job_dir, lock, cmd, cwd, setenv, slice_name=None, extra_props=None):
    """slice_name / extra_props are only set for an opted-in MI campaign job; defaults keep the original argv."""
    rj, _ = unit_names(job_id)
    p = profile
    env = {
        "RESEARCH_JOB_ID": job_id, "RESEARCH_OWNER": owner, "RESEARCH_PROFILE": p["name"],
        "RESEARCH_WORKERS": str(p["workers"]), "RESEARCH_JOB_DIR": job_dir,
        "PYTHONPATH": PKG_ROOT, "PYTHONHASHSEED": "0", "PYTHONUNBUFFERED": "1",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    }
    for kv in setenv or []:
        k, _, v = kv.partition("=")
        env[k] = f"{PKG_ROOT}:{v}" if k == "PYTHONPATH" else v
    # No --collect on the job unit: a failed job (e.g. Result=oom-kill) stays loaded until the
    # watchdog has recorded its Result and run `reset-failed` (a successful one unloads itself).
    args = ["systemd-run", "--user", "--quiet", f"--unit={rj}", f"--slice={slice_name or cfg['slice']['name']}",
            f"--description=research job {job_id} owner={owner} profile={p['name']}",
            f"--working-directory={cwd}",
            "-p", f"CPUQuota={p['cpu_quota_pct']}%", "-p", "CPUWeight=idle",
            "-p", f"MemoryHigh={p['memory_high']}", "-p", f"MemoryMax={p['memory_max']}",
            "-p", "MemorySwapMax=0",  # G6 step 1: pressure stays inside the job cgroup, not on disk
            "-p", f"TasksMax={p['tasks_max']}", "-p", f"OOMScoreAdjust={p['oom_score_adj']}",
            "-p", "OOMPolicy=kill", "-p", "KillMode=control-group", "-p", "TimeoutStopSec=20",
            "-p", f"RuntimeMaxSec={p['max_runtime_s']}"]
    args += list(extra_props or [])
    for k, v in sorted(env.items()):
        args.append(f"--setenv={k}={v}")
    args += [cfg["python"], "-m", "research_exec", "_jobwrap", job_dir, lock, "--", *cmd]
    return args


def build_watchdog_cmd(cfg, job_id, owner, profile, job_dir, config_path):
    rj, rw = unit_names(job_id)
    args = ["systemd-run", "--user", "--quiet", f"--unit={rw}", "--collect",
            f"--description=research watchdog for {job_id} owner={owner}",
            "-p", f"BindsTo={rj}", "-p", f"After={rj}",
            "-p", "CPUQuota=20%", "-p", "MemoryMax=128M", "-p", "MemorySwapMax=0", "-p", "TasksMax=32",
            "-p", "TimeoutStopSec=30",
            "-p", f"RuntimeMaxSec={profile['max_runtime_s'] + 900}",
            f"--setenv=PYTHONPATH={PKG_ROOT}", f"--setenv=RESEARCH_JOB_ID={job_id}",
            f"--setenv=RESEARCH_OWNER={owner}",
            cfg["python"], "-m", "research_exec", "_watchdog", job_dir, rj]
    if config_path:
        args += ["--config", os.path.abspath(config_path)]
    return args


def launch(cfg, *, job_id, owner, profile, cmd, cwd=None, setenv=None, config_path=None,
           wait=False, steal_sample=None, log=print, mi_campaign=None) -> int:
    if not JOB_ID_RE.match(job_id):
        raise ValueError("job id must match [a-z0-9][a-z0-9-]{0,47}")
    if not OWNER_RE.match(owner or ""):
        raise ValueError("an owner tag is required (e.g. --owner agent:p2f-calib or --owner basim)")
    if not cmd:
        raise ValueError("no command given after --")
    rj, rw = unit_names(job_id)
    mi = None
    if mi_campaign is not None:                      # opt-in MI job: validated BEFORE anything is created
        from . import mi_campaign as MIC
        mi = MIC.job_extra(cfg, mi_campaign, profile)
    job_dir = os.path.join(cfg["state_dir"], "jobs", job_id)
    if os.path.exists(job_dir):
        raise FileExistsError(f"job dir exists: {job_dir} (job ids are single-use; pick a new id)")
    for u in (rj, rw):
        if active_state(u) not in ("inactive", ""):
            raise RuntimeError(f"unit {u} already loaded/active")
    os.makedirs(job_dir)
    cwd = os.path.abspath(cwd or os.getcwd())
    lock = adm.lock_path(cfg, profile.get("lock", "heavy"))
    launch_rec = {"job_id": job_id, "owner": owner, "profile": profile, "cmd": cmd, "cwd": cwd,
                  "units": {"job": rj, "watchdog": rw}, "lock": lock, "created_at": utc_now(),
                  "config_path": config_path, "launcher_pid": os.getpid()}
    if mi:
        launch_rec["mi"] = mi
    atomic_write_json(os.path.join(job_dir, "launch.json"), launch_rec)

    decision = adm.evaluate(cfg, profile, steal_sample=steal_sample, job_id=job_id)
    atomic_write_json(os.path.join(job_dir, "admission.json"), decision)
    if not decision["admit"]:
        log(f"ADMISSION REFUSED for {job_id}: {'; '.join(decision['reasons'])}")
        atomic_write_json(os.path.join(job_dir, "job_record.json"),
                          {"job_id": job_id, "owner": owner, "status": "refused",
                           "admission": {"admit": False, "reasons": decision["reasons"]}})
        return 3

    sl = ensure_slice(cfg)
    launch_rec["slice_runtime_props"] = sl
    jargs = build_job_cmd(cfg, job_id, owner, profile, job_dir, lock, cmd, cwd, setenv,
                          slice_name=mi["slice"] if mi else None, extra_props=mi["props"] if mi else None)
    wargs = build_watchdog_cmd(cfg, job_id, owner, profile, job_dir, config_path)
    launch_rec["systemd_run"] = {"job": jargs, "watchdog": wargs}
    r = _run(jargs)
    launch_rec["job_start_rc"] = r.returncode
    if r.returncode != 0:
        launch_rec["job_start_stderr"] = r.stderr.strip()
        atomic_write_json(os.path.join(job_dir, "launch.json"), launch_rec)
        log(f"job unit failed to start: {r.stderr.strip()}")
        return 4
    w = _run(wargs)
    launch_rec["watchdog_start_rc"] = w.returncode
    atomic_write_json(os.path.join(job_dir, "launch.json"), launch_rec)
    if w.returncode != 0:
        # fail closed: never leave research unsupervised
        _run(["systemctl", "--user", "stop", rj])
        log(f"watchdog failed to start ({w.stderr.strip()}); job stopped")
        return 5
    log(f"started {rj} + {rw}; job dir {job_dir}")
    if not wait:
        return 0
    return wait_for(job_id, cfg, profile["max_runtime_s"] + 900, log=log)


def wait_for(job_id, cfg, timeout_s, log=print) -> int:
    """Wait on unit STATE (never on process-name patterns), bounded, then print the record."""
    rj, rw = unit_names(job_id)
    job_dir = os.path.join(cfg["state_dir"], "jobs", job_id)
    deadline = time.monotonic() + timeout_s
    for u, extra in ((rj, 0), (rw, 60)):
        while active_state(u) in ("active", "activating", "deactivating", "reloading"):
            if time.monotonic() > deadline + extra:
                log(f"TIMEOUT waiting for {u}; leaving it to its RuntimeMaxSec bound")
                return 124
            time.sleep(1.0)
    deadline2 = time.monotonic() + 30
    rec = read_json(os.path.join(job_dir, "job_record.json"))
    while rec is None and time.monotonic() < deadline2:
        time.sleep(0.5)
        rec = read_json(os.path.join(job_dir, "job_record.json"))
    if rec is None:
        log("no job_record.json written")
        return 6
    log(f"job {job_id}: status={rec.get('status')} exit={rec.get('exit_code')} wall_s={rec.get('wall_s')} "
        f"frozen_s={rec.get('frozen_total_s')} cpu_s={rec.get('cpu_s_cgroup')} "
        f"peak_mem={rec.get('memory_peak_bytes')}")
    ec = rec.get("exit_code")
    return ec if isinstance(ec, int) else 7


def control(job_id: str, action: str) -> int:
    rj, rw = unit_names(job_id)
    if action == "status":
        for u in (rj, rw):
            r = _run(["systemctl", "--user", "show", "-p",
                      "ActiveState,SubState,FreezerState,Result,MainPID,ControlGroup", u])
            print(f"[{u}]\n{r.stdout.strip()}")
        return 0
    if action in ("freeze", "thaw"):
        return _run(["systemctl", "--user", action, rj]).returncode
    if action == "kill":
        _run(["systemctl", "--user", "kill", "--kill-whom=all", "--signal=SIGKILL", rj])
        return _run(["systemctl", "--user", "stop", rj]).returncode
    raise ValueError(action)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(1)
