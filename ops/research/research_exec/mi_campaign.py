"""MI campaign lifecycle on top of the runner (opt-in; disabled by default). Uses mi_cpuguard for the guard and ledger.

  open    reserve-by-guard: ensure research.slice + research-mi.slice (CPUQuota<=600 %), start the guard unit
          (app.slice, Restart=no, CollectMode=inactive-or-failed), start the anchor (BindsTo/Requisite guard),
          wait for the guard's ready file (it reserved budget and took the baseline).
  job     extra slice + properties for an MI job: --slice=research-mi.slice, BindsTo/Requisite/After the guard;
          refused unless the campaign is ready and the guard unit is active with the recorded InvocationID.
  close   write the close request; the guard charges the measured counter and exits; wait (bounded).
  recover a crashed campaign (guard gone, reservation open) is charged its FULL reservation; idempotent.
  status  ledger state (read-only).
Kill scope: the guard may only kill an MI child slice of research.slice (guard_main.valid_kill_target); Collector,
Paper, Postgres and other containers run under the SYSTEM manager and are not addressable by `systemctl --user`.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import re
import shlex
import subprocess
import time

from . import config as C
from .record import atomic_write_json, read_json, utc_now

PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMPAIGN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


class MIError(RuntimeError):
    pass


def _run(args, timeout=60):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


# ------------------------------------------------------------------ config / paths
def mi_cfg(cfg: dict) -> dict:
    m = cfg.get("mi") or {}
    if not m.get("enabled"):
        raise MIError("MI integration is disabled (config mi.enabled is false); nothing was started")
    from mi_cpuguard.guard_main import KILL_UNIT_RE
    if not KILL_UNIT_RE.match(m["slice"]):
        raise MIError(f"MI slice must be a research-*.slice child of research.slice, got {m['slice']!r}")
    if m["cpu_quota_pct"] > C.MI_MAX_QUOTA_PCT or m["cpu_quota_pct"] <= 0:
        raise MIError(f"MI cpu_quota_pct {m['cpu_quota_pct']} exceeds the owner ceiling {C.MI_MAX_QUOTA_PCT}")
    if m["cap_cpu_s"] > C.MI_MAX_CAP_CPU_S or m["cap_cpu_s"] <= 0:
        raise MIError(f"MI cap_cpu_s {m['cap_cpu_s']} exceeds the owner ceiling {C.MI_MAX_CAP_CPU_S}")
    if m["margin_cpu_s"] < m["cpu_quota_pct"] / 100 * m["poll_s"] * 2:
        raise MIError("MI margin below two polls at the slice quota")
    return m


def paths(cfg: dict, campaign: str | None = None) -> dict:
    base = os.path.join(cfg["state_dir"], "mi")
    out = {"base": base, "ledger": os.path.join(base, "budget.jsonl"),
           "checkpoint": os.path.join(base, "budget.checkpoint.json"),
           "anchor": os.path.join(cfg["mi"]["anchor_dir"], "budget.anchor.json"),
           "open_lock": os.path.join(base, "open.lock"), "campaigns": os.path.join(base, "campaigns")}
    if os.path.realpath(os.path.dirname(out["anchor"])) == os.path.realpath(base):
        raise MIError("mi.anchor_dir must be independent of the runner state dir")
    if campaign:
        d = os.path.join(base, "campaigns", campaign)
        out.update(dir=d, campaign=os.path.join(d, "campaign.json"), ready=os.path.join(d, "ready.json"),
                   close=os.path.join(d, "close.request"), guard_log=os.path.join(d, "guard.log"))
    return out


def slice_cgroup_dir(cfg: dict) -> str:
    m = cfg["mi"]
    root = m["cgroup_root"].format(uid=os.getuid())
    return os.path.join(root, cfg["slice"]["name"], m["slice"])


def guard_unit(campaign: str) -> str:
    return f"mi-cpuguard-{campaign}.service"


def anchor_unit(campaign: str) -> str:
    return f"mi-anchor-{campaign}.service"


def _check_campaign(campaign: str):
    if not CAMPAIGN_RE.match(campaign or ""):
        raise MIError("campaign id must match [a-z0-9][a-z0-9-]{0,31}")


def _ledger(cfg):
    from mi_cpuguard import ledger as L
    p = paths(cfg)
    return L.BudgetLedger(p["ledger"], cap_cpu_s=mi_cfg(cfg)["cap_cpu_s"], checkpoints=[p["checkpoint"], p["anchor"]],
                          single_open=True)


@contextlib.contextmanager
def _open_lock(cfg):
    p = paths(cfg)
    os.makedirs(p["base"], exist_ok=True)
    fd = os.open(p["open_lock"], os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MIError("another `mi open` is in progress (open lock held)")
        yield
    finally:
        os.close(fd)


def init_ledger(cfg, *, approve_genesis: bool, by: str) -> dict:
    """FIRST-EVER genesis only (explicit owner flag). Refuses if any ledger, checkpoint, *.bak or campaign exists."""
    mi_cfg(cfg)
    if not approve_genesis:
        raise MIError("genesis needs explicit owner approval (--approve-genesis)")
    p = paths(cfg)
    if os.path.isdir(p["campaigns"]) and os.listdir(p["campaigns"]):
        raise MIError("NOT_FIRST_GENESIS: campaign records exist; the ledger was lost, not never created "
                      "(use ledger-check and an owner-approved recovery)")
    ev = _ledger(cfg).init_genesis(created_by=by)
    return {"genesis": ev, "ledger": p["ledger"], "checkpoints": [p["checkpoint"], p["anchor"]]}


def ledger_check(cfg) -> dict:
    from mi_cpuguard import ledger as L
    return L.diagnose(_ledger(cfg))


def ledger_recover(cfg, action: str, *, approve: str, by: str, backup: str | None = None,
                   declared_consumed_cpu_s: float | None = None, declared_campaigns=()) -> dict:
    from mi_cpuguard import ledger as L
    led = _ledger(cfg)
    st = None
    try:
        st = led.state()
    except L.LedgerError:
        pass
    if st and st["open_reservations"] and action != "rebuild-checkpoints":
        raise MIError("ledger has an open campaign; close / recover it first")
    return L.recover_ledger(led, action, approve=approve, by=by, backup_path=backup,
                            declared_consumed_cpu_s=declared_consumed_cpu_s, declared_campaigns=declared_campaigns)


def unit_show(unit: str, props="ActiveState,InvocationID,MainPID", run=_run) -> dict:
    r = run(["systemctl", "--user", "show", "-p", props, unit])
    return dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)


# ------------------------------------------------------------------ commands (rendered; executed via `run`)
def mi_slice_cmd(cfg) -> list:
    m = mi_cfg(cfg)
    return ["systemctl", "--user", "set-property", "--runtime", m["slice"], f"CPUQuota={m['cpu_quota_pct']}%",
            f"CPUWeight={m['cpu_weight']}", f"MemoryMax={m['memory_max']}", "MemorySwapMax=0",
            f"TasksMax={m['tasks_max']}"]


def guard_cmd(cfg, campaign: str, reservation_cpu_s: float) -> list:
    m, p = mi_cfg(cfg), paths(cfg, campaign)
    args = ["--campaign", campaign, "--reservation-cpu-s", repr(float(reservation_cpu_s)), "--ledger", p["ledger"],
            "--checkpoint", p["checkpoint"], "--checkpoint", p["anchor"], "--cap-cpu-s", str(float(m["cap_cpu_s"])),
            "--cgroup-dir", slice_cgroup_dir(cfg), "--kill-unit", m["slice"], "--ready-file", p["ready"],
            "--close-file", p["close"], "--wait-cgroup-s", str(m["wait_cgroup_s"]),
            "--margin-cpu-s", str(m["margin_cpu_s"]), "--poll-s", str(m["poll_s"]), "--max-gap-s", str(m["max_gap_s"])]
    return ["systemd-run", "--user", "--quiet", f"--unit={guard_unit(campaign)}", "--slice=app.slice",
            f"--setenv=PYTHONPATH={PKG_ROOT}", f"--description=MI cpu guard {campaign}",
            "-p", f"CPUQuota={m['guard_cpu_quota_pct']}%", "-p", f"MemoryMax={m['guard_memory_max']}",
            "-p", "MemorySwapMax=0", "-p", "Restart=no", "-p", "CollectMode=inactive-or-failed",
            "-p", f"RuntimeMaxSec={m['guard_runtime_max_s']}", "-p", f"StandardOutput=append:{p['guard_log']}",
            "-p", f"StandardError=append:{p['guard_log']}",
            cfg["python"], "-m", "mi_cpuguard.guard_main", *args]


def anchor_cmd(cfg, campaign: str) -> list:
    m, g = mi_cfg(cfg), guard_unit(campaign)
    return ["systemd-run", "--user", "--quiet", f"--unit={anchor_unit(campaign)}", f"--slice={m['slice']}",
            "--collect", f"--description=MI slice anchor {campaign}",
            "-p", f"BindsTo={g}", "-p", f"Requisite={g}", "-p", f"After={g}", "-p", "MemorySwapMax=0",
            "-p", f"RuntimeMaxSec={m['guard_runtime_max_s']}", "/bin/sleep", "infinity"]


# ------------------------------------------------------------------ lifecycle
def open_campaign(cfg, campaign: str, reservation_cpu_s: float, *, run=_run, sleep=time.sleep,
                  clock=time.monotonic, ensure_parent=None) -> dict:
    mi_cfg(cfg)
    with _open_lock(cfg):
        return _open_campaign(cfg, campaign, reservation_cpu_s, run=run, sleep=sleep, clock=clock,
                              ensure_parent=ensure_parent)


def _open_campaign(cfg, campaign, reservation_cpu_s, *, run, sleep, clock, ensure_parent) -> dict:
    m = mi_cfg(cfg)
    _check_campaign(campaign)
    p = paths(cfg, campaign)
    led = _ledger(cfg)
    st = led.state()           # strict: missing / truncated / forked / stale / corrupt ledger or checkpoint -> refuse
    if os.path.exists(p["campaign"]) or campaign in st["campaigns"]:
        raise MIError(f"campaign {campaign} already exists (ids are single-use; use recover / close)")
    if st["open_reservations"]:
        # one campaign at a time: all campaigns share the one slice counter (a second guard would double-charge
        # and its kill would hit the other campaign); a crashed one must be recovered first
        raise MIError(f"another campaign is open: {sorted(st['open_reservations'])} (close or recover it first)")
    if not 0 < reservation_cpu_s <= st["remaining_cpu_s"]:
        raise MIError(f"reservation {reservation_cpu_s} not within remaining budget {st['remaining_cpu_s']}")
    if reservation_cpu_s <= m["margin_cpu_s"]:
        raise MIError("reservation must exceed the safety margin")
    if unit_show(guard_unit(campaign), run=run).get("ActiveState") not in ("inactive", "", None):
        raise MIError(f"{guard_unit(campaign)} is already loaded")
    os.makedirs(p["dir"])
    rec = {"campaign": campaign, "reservation_cpu_s": reservation_cpu_s, "created_at": utc_now(),
           "ledger_id": st["ledger_id"], "ledger_epoch": st["epoch"], "ledger_seq_at_open": st["seq"],
           "slice": m["slice"], "cgroup_dir": slice_cgroup_dir(cfg), "guard_unit": guard_unit(campaign),
           "anchor_unit": anchor_unit(campaign), "status": "opening"}
    atomic_write_json(p["campaign"], rec)
    if ensure_parent:
        ensure_parent(cfg)                             # research.slice runtime properties (launcher.ensure_slice)
    steps = [("mi_slice", mi_slice_cmd(cfg)), ("guard", guard_cmd(cfg, campaign, reservation_cpu_s)),
             ("anchor", anchor_cmd(cfg, campaign))]
    for name, cmd in steps:
        r = run(cmd)
        if r.returncode != 0:
            _abort(cfg, campaign, rec, f"{name} failed: {r.stderr.strip()}", run=run)
            raise MIError(f"campaign {campaign}: {name} failed ({r.stderr.strip()}); aborted")
    t_end = clock() + m["ready_timeout_s"]
    while read_json(p["ready"]) is None:
        if clock() > t_end:
            _abort(cfg, campaign, rec, "guard not ready in time", run=run)
            raise MIError(f"campaign {campaign}: guard not ready; aborted")
        sleep(0.2)
    ready = read_json(p["ready"])
    rec.update(status="open", ready=ready)
    atomic_write_json(p["campaign"], rec)
    return rec


def _abort(cfg, campaign, rec, reason, *, run=_run):
    """Stop guard (anchor + jobs follow via BindsTo). A guard that already reserved charges on SIGTERM; if it could
    not, the reservation stays open and counts as consumed until `recover`."""
    run(["systemctl", "--user", "stop", guard_unit(campaign)])
    run(["systemctl", "--user", "stop", anchor_unit(campaign)])
    rec.update(status="aborted", abort_reason=reason, aborted_at=utc_now())
    atomic_write_json(paths(cfg, campaign)["campaign"], rec)


def job_extra(cfg, campaign: str, profile: dict, *, run=_run) -> dict:
    m = mi_cfg(cfg)
    _check_campaign(campaign)
    p = paths(cfg, campaign)
    rec, ready = read_json(p["campaign"]), read_json(p["ready"])
    if not rec or rec.get("status") != "open" or not ready:
        raise MIError(f"campaign {campaign} is not open and ready")
    st = _ledger(cfg).state()                          # strict integrity check before every MI job
    if st["ledger_id"] != rec.get("ledger_id") or campaign not in st["open_reservations"]:
        raise MIError(f"campaign {campaign} is not an open reservation of the current ledger (fail closed)")
    if profile["cpu_quota_pct"] > m["cpu_quota_pct"]:
        raise MIError(f"profile {profile['name']} quota {profile['cpu_quota_pct']} % exceeds the MI slice quota")
    u = unit_show(guard_unit(campaign), run=run)
    if u.get("ActiveState") != "active" or not ready.get("invocation_id") or \
            u.get("InvocationID") != ready.get("invocation_id"):
        raise MIError(f"guard for {campaign} is not the live, recorded instance (fail closed)")
    g = guard_unit(campaign)
    return {"slice": m["slice"], "props": ["-p", f"BindsTo={g}", "-p", f"Requisite={g}", "-p", f"After={g}"],
            "campaign": campaign}


def close_campaign(cfg, campaign: str, *, run=_run, sleep=time.sleep, clock=time.monotonic) -> dict:
    m = mi_cfg(cfg)
    _check_campaign(campaign)
    p = paths(cfg, campaign)
    rec = read_json(p["campaign"])
    if not rec:
        raise MIError(f"unknown campaign {campaign}")
    st = _ledger(cfg).state()
    if rec.get("status") == "closed" and campaign not in st["open_reservations"]:
        return rec                                      # idempotent
    with open(p["close"], "w", encoding="utf-8") as fh:
        fh.write(utc_now() + "\n")
    t_end = clock() + m["close_timeout_s"]
    while unit_show(guard_unit(campaign), run=run).get("ActiveState") in ("active", "activating", "deactivating"):
        if clock() > t_end:
            raise MIError(f"guard for {campaign} did not finish within {m['close_timeout_s']} s (jobs still running?)")
        sleep(0.5)
    st = _ledger(cfg).state()
    if campaign in st["open_reservations"]:
        rec.update(status="needs_recover")
        atomic_write_json(p["campaign"], rec)
        raise MIError(f"campaign {campaign}: guard exited without charging; run `research-run mi recover`")
    run(["systemctl", "--user", "stop", anchor_unit(campaign)])
    rec.update(status="closed", closed_at=utc_now())
    atomic_write_json(p["campaign"], rec)
    return rec


def recover_campaign(cfg, campaign: str, *, run=_run) -> dict:
    mi_cfg(cfg)
    _check_campaign(campaign)
    p = paths(cfg, campaign)
    if unit_show(guard_unit(campaign), run=run).get("ActiveState") in ("active", "activating", "deactivating"):
        raise MIError(f"guard for {campaign} is still running; recover refused")
    led = _ledger(cfg)
    st = led.state()
    rec = read_json(p["campaign"]) or {"campaign": campaign}
    if campaign in st["open_reservations"]:
        ev = led.recover(campaign)
        rec.update(status="recovered", recovered_at=utc_now(), charged_cpu_s=ev["actual_cpu_s"])
    else:
        rec.setdefault("status", "no_open_reservation")
    run(["systemctl", "--user", "stop", anchor_unit(campaign)])
    if os.path.isdir(p["dir"]):
        atomic_write_json(p["campaign"], rec)
    return rec


def status(cfg) -> dict:
    mi_cfg(cfg)
    return _ledger(cfg).state()


def describe(cmd) -> str:
    return shlex.join(cmd)
