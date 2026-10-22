"""Aggregate research CPU budget: reservations as leases (design: docs/ops/RESEARCH_ADMISSION_CONTROLLER_DESIGN.md,
plan: docs/ops/RESEARCH_ADMISSION_CONTROLLER_IMPLEMENTATION_PLAN.md, phase I-1).

Pure logic with injected probes, so every hardening rule is testable without systemd. NOT wired into admission or
the launcher yet: phase I-2 calls `check` in shadow mode only, enforcement (I-4) needs owner approval.

Every decision fails closed: an unreadable state file, an unknown unit state or an unreadable probe refuses; nothing
is repaired or reclaimed silently. Standard library only.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

SCHEMA = 1
DEFAULTS = {"r1_pct": 400, "r2_pct": 500, "lab_pct": 100, "grace_s": 120, "expiry_extra_s": 600, "clock_step_s": 60,
            "enforce_slice": False}


class BudgetStateError(Exception):
    """The state file exists but cannot be trusted (corrupt, wrong schema or wrong types)."""


@dataclass
class Probes:
    is_unit_active: Callable[[str], Optional[bool]]          # None = cannot tell (refuse)
    pid_start_ticks: Callable[[int], Optional[int]]          # None = no such pid
    boot_id: Callable[[], str]
    wall_utc: Callable[[], dt.datetime]
    mono_s: Callable[[], float]
    lab_slice_pct: Callable[[], Optional[int]]               # 0 = no lab slice, None = unreadable (refuse)
    marker_procs_outside_slice: Callable[[], Optional[list]]  # [] = clean, None = unreadable (refuse)
    slice_quota_pct: Callable[[], Optional[int]] = lambda: None
    live_job_units: Callable[[], Optional[list]] = lambda: None


@dataclass
class Request:
    job_id: str
    unit: str
    profile: str
    pct: int
    pid: int                     # owner of the lease: the reserving launcher until jobwrap calls bind()
    max_runtime_s: int


@dataclass
class Decision:
    admit: bool
    reasons: list = field(default_factory=list)
    capacity_pct: Optional[int] = None
    held_pct: Optional[int] = None
    reclaimed: list = field(default_factory=list)
    lease: Optional[dict] = None


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat()


def _parse(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


def empty_state() -> dict:
    return {"schema": SCHEMA, "leases": [], "last_wall_utc": None, "last_mono_s": None, "last_boot_id": None}


_LEASE_TYPES = {"job_id": str, "unit": str, "profile": str, "pct": int, "boot_id": str, "pid": int,
                "pid_start_ticks": int, "admitted_utc": str, "expires_utc": str, "mono_admitted": (int, float)}


def load(path: str) -> dict:
    """Missing file = empty state. Anything else that is not a valid state raises BudgetStateError (never repaired)."""
    try:
        with open(path, encoding="utf-8") as fh:
            st = json.load(fh)
    except FileNotFoundError:
        return empty_state()
    except (OSError, ValueError) as e:
        raise BudgetStateError(f"budget state unreadable: {type(e).__name__}") from e
    if not isinstance(st, dict) or st.get("schema") != SCHEMA or not isinstance(st.get("leases"), list):
        raise BudgetStateError("budget state has an unknown schema")
    for ls in st["leases"]:
        if not isinstance(ls, dict) or any(not isinstance(ls.get(k), t) or isinstance(ls.get(k), bool)
                                           for k, t in _LEASE_TYPES.items()):
            raise BudgetStateError("budget state has a malformed lease")
    return st


def save(path: str, st: dict) -> None:
    """tmp + fsync + rename + directory fsync: a crash leaves either the old or the new state, never a torn file."""
    d = os.path.dirname(os.path.abspath(path))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def capacity(st: dict, probes: Probes, cfg: dict, requesting_profile: Optional[str] = None):
    """Budget B for the current mode: R2 mode while an R2 lease is held or requested (A2), minus the lab share (A4)."""
    reasons = []
    r2 = requesting_profile == "R2" or any(ls["profile"] == "R2" for ls in st["leases"])
    b = cfg["r2_pct"] if r2 else cfg["r1_pct"]
    lab = probes.lab_slice_pct()
    if lab is None:
        reasons.append("lab_probe_unreadable")
    elif lab > 0:
        b -= cfg["lab_pct"]
    return b, reasons


def reconcile(st: dict, probes: Probes, cfg: dict):
    """Re-evaluate every lease against the live system. Returns (new_state, refusal_reasons, reclaimed_job_ids)."""
    reasons, reclaimed, keep = [], [], []
    now_w, now_m, boot = probes.wall_utc(), probes.mono_s(), probes.boot_id()
    if st.get("last_boot_id") == boot and st.get("last_wall_utc") is not None and st.get("last_mono_s") is not None:
        step = (now_w - _parse(st["last_wall_utc"])).total_seconds() - (now_m - st["last_mono_s"])
        if abs(step) > cfg["clock_step_s"]:
            reasons.append(f"clock_step_detected step_s={round(step)}")    # refuse now; re-anchored below
    for ls in st["leases"]:
        if ls["boot_id"] != boot:                                  # lease of an earlier boot
            if probes.is_unit_active(ls["unit"]) is False:
                reclaimed.append(ls["job_id"]); continue
            reasons.append(f"previous_boot_lease_unit_state_unclear job={ls['job_id']}"); keep.append(ls); continue
        active = probes.is_unit_active(ls["unit"])
        if active is None:
            reasons.append(f"unit_state_unknown job={ls['job_id']}"); keep.append(ls); continue
        if active:
            if now_w > _parse(ls["expires_utc"]):
                reasons.append(f"lease_expired_unit_active job={ls['job_id']}")
            keep.append(ls); continue
        ticks = probes.pid_start_ticks(ls["pid"])
        if ticks is not None and ticks == ls["pid_start_ticks"]:
            reasons.append(f"unit_gone_process_alive job={ls['job_id']}"); keep.append(ls); continue
        if now_m - ls["mono_admitted"] < cfg["grace_s"]:
            keep.append(ls); continue                              # crash suspected, still within grace: held
        reclaimed.append(ls["job_id"])
    new = dict(st, leases=keep, last_wall_utc=_iso(now_w), last_mono_s=now_m, last_boot_id=boot)
    return new, reasons, reclaimed


def check(st: dict, req: Request, probes: Probes, cfg: dict) -> Decision:
    """Admission decision on an already reconciled state (no mutation)."""
    b, reasons = capacity(st, probes, cfg, requesting_profile=req.profile)
    held = sum(ls["pct"] for ls in st["leases"])
    if any(ls["job_id"] == req.job_id for ls in st["leases"]):
        reasons.append(f"duplicate_job_id job={req.job_id}")
    mk = probes.marker_procs_outside_slice()
    if mk is None:
        reasons.append("marker_probe_unreadable")
    elif mk:
        reasons.append(f"marker_process_outside_slice n={len(mk)}")
    if held + req.pct > b:
        reasons.append(f"budget_exceeded held={held} requested={req.pct} capacity={b}")
    return Decision(admit=not reasons, reasons=reasons, capacity_pct=b, held_pct=held)


@contextlib.contextmanager
def _locked(state_dir: str):
    os.makedirs(state_dir, exist_ok=True)
    fd = os.open(os.path.join(state_dir, "budget.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def reserve(state_dir: str, req: Request, probes: Probes, cfg: dict) -> Decision:
    """One read-check-write under the exclusive budget lock. A refusal never adds a lease; a reconciliation that
    reclaimed leases is still persisted. A corrupt state refuses and leaves the file untouched."""
    cfg = {**DEFAULTS, **(cfg or {})}
    path = os.path.join(state_dir, "budget.json")
    with _locked(state_dir):
        try:
            st = load(path)
        except BudgetStateError as e:
            return Decision(admit=False, reasons=[f"budget_state_unreadable: {e}"])
        st, rec_reasons, reclaimed = reconcile(st, probes, cfg)
        d = check(st, req, probes, cfg)
        d.reasons = rec_reasons + d.reasons
        d.admit, d.reclaimed = not d.reasons, reclaimed
        if d.admit:
            ticks = probes.pid_start_ticks(req.pid)
            if ticks is None:
                d.admit, d.reasons = False, [f"job_pid_not_found pid={req.pid}"]
            else:
                now = probes.wall_utc()
                lease = {"job_id": req.job_id, "unit": req.unit, "profile": req.profile, "pct": int(req.pct),
                         "boot_id": probes.boot_id(), "pid": int(req.pid), "pid_start_ticks": int(ticks),
                         "admitted_utc": _iso(now),
                         "expires_utc": _iso(now + dt.timedelta(seconds=req.max_runtime_s + cfg["expiry_extra_s"])),
                         "mono_admitted": probes.mono_s()}
                st["leases"].append(lease)
                d.lease = lease
        save(path, st)
        return d


def bind(state_dir: str, job_id: str, pid: int, probes: Probes) -> bool:
    """Re-point a lease from the reserving process (the launcher) to the job's own process (jobwrap), so that
    crash detection follows the job, not the short-lived launcher. False if the lease or the pid does not exist."""
    path = os.path.join(state_dir, "budget.json")
    with _locked(state_dir):
        st = load(path)
        ticks = probes.pid_start_ticks(pid)
        for ls in st["leases"]:
            if ls["job_id"] == job_id and ticks is not None:
                ls["pid"], ls["pid_start_ticks"] = int(pid), int(ticks)
                save(path, st)
                return True
        return False


def release(state_dir: str, job_id: str) -> bool:
    """Idempotent: True if a lease was removed, False if there was none. A corrupt state raises (never rewritten)."""
    path = os.path.join(state_dir, "budget.json")
    with _locked(state_dir):
        st = load(path)
        n = len(st["leases"])
        st["leases"] = [ls for ls in st["leases"] if ls["job_id"] != job_id]
        if len(st["leases"]) == n:
            return False
        save(path, st)
        return True


def readback(st: dict, probes: Probes, cfg: dict) -> list:
    """Accounting drift (after start): live job units must equal the leases; with A3 enabled the slice quota must
    equal the budget of the current mode. Returns refusal reasons ([] = consistent)."""
    cfg = {**DEFAULTS, **(cfg or {})}
    reasons = []
    live = probes.live_job_units()
    if live is None:
        reasons.append("live_units_unreadable")
    elif sorted(live) != sorted(ls["unit"] for ls in st["leases"]):
        reasons.append("accounting_drift units_vs_leases")
    if cfg["enforce_slice"]:
        b, r = capacity(st, probes, cfg)
        reasons += r
        q = probes.slice_quota_pct()
        if q is None or q != b:
            reasons.append(f"slice_quota_mismatch quota={q} capacity={b}")
    return reasons
