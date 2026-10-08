#!/usr/bin/env python3
"""G6 step 3: monitor swap isolation (MemorySwapMax=0) - READ-ONLY preflight and verification. Stdlib only.

This tool never changes anything. It only reads systemctl --user show, unit / drop-in files, the unit's cgroup
files, the monitor status.json and `docker inspect` of the bound Collector.

  preflight --out PRE.json            capture identity + check every precondition (exit 0 = GO, 1 = NO-GO)
  verify --pre PRE.json --out POST.json
                                      after the owner-approved apply: check the change took effect and nothing else
                                      moved (exit 0 = PASS, 1 = FAIL -> rollback triggers, see G6_STEP3 doc)
  verify-rollback --pre PRE.json --out RB.json
                                      after the rollback commands: definition back to preflight, no restart
  commands                            print the exact apply / rollback commands (text only)

The apply itself is ONE owner-approved command (live, no restart):
  systemctl --user set-property tsb-p2f-monitor.service MemorySwapMax=0
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time

UNIT = "tsb-p2f-monitor.service"
HOME = os.path.expanduser("~")
UNIT_FILE = os.path.join(HOME, ".config/systemd/user", UNIT)
UNIT_SHA256 = "8861897a7f9e2cb6e973f1b89a5b8c4f6972ef13692f9064d91507f7a2bb785f"   # G4 2526338, installed == repo
DROPIN_DIRS = (os.path.join(HOME, ".config/systemd/user", UNIT + ".d"),
               os.path.join(HOME, ".config/systemd/user.control", UNIT + ".d"),
               f"/run/user/{os.getuid()}/systemd/user.control/{UNIT}.d",
               f"/run/user/{os.getuid()}/systemd/user/{UNIT}.d")
EXPECTED_DROPIN = os.path.join(HOME, ".config/systemd/user.control", UNIT + ".d", "50-MemorySwapMax.conf")
STATUS = os.path.join(HOME, "ops/tsb-p2-forward/monitor/p2-forward-continuous-v1/status.json")
BINDING = os.path.join(HOME, "ops/tsb-p2-forward/monitor/p2-forward-continuous-v1.binding.json")
CGROOT = "/sys/fs/cgroup"
PROPS = ("ActiveState", "SubState", "MainPID", "InvocationID", "NRestarts", "ActiveEnterTimestampMonotonic",
         "MemoryMax", "MemoryHigh", "MemorySwapMax", "CPUWeight", "TasksMax", "OOMScoreAdjust", "DropInPaths",
         "FragmentPath", "ControlGroup")
BASE = {"MemoryMax": "268435456", "MemoryHigh": "201326592", "CPUWeight": "1000", "TasksMax": "32",
        "OOMScoreAdjust": "100"}
CG_BASE = {"memory.max": "268435456", "memory.high": "201326592"}
IDENTITY = ("MainPID", "InvocationID", "NRestarts", "ActiveEnterTimestampMonotonic")
OK_SEVERITIES = ("INFO", "WARNING")
MAX_STATUS_AGE_S = 180
APPLY_CMD = f"systemctl --user set-property {UNIT} MemorySwapMax=0"
ROLLBACK_CMDS = (f"systemctl --user set-property {UNIT} MemorySwapMax=infinity",
                 f"rm -f {EXPECTED_DROPIN}",
                 f"rmdir --ignore-fail-on-non-empty {os.path.dirname(EXPECTED_DROPIN)}",
                 "systemctl --user daemon-reload")


# ------------------------------------------------------------------ pure rules (unit-tested)
def parse_dropin(text: str) -> dict:
    """{section: {key: value}} of a systemd drop-in, comments / blank lines ignored, last assignment wins."""
    out, sec = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("[") and line.endswith("]"):
            sec = line[1:-1]
            out.setdefault(sec, {})
            continue
        if "=" in line and sec is not None:
            k, v = line.split("=", 1)
            out[sec][k.strip()] = v.strip()
    return out


def dropin_is_exactly_swap0(text: str) -> bool:
    return parse_dropin(text) == {"Service": {"MemorySwapMax": "0"}}


def window_problems(now_utc: dt.datetime, rotation_ms=None) -> list:
    """Protected windows (same as G2/G5): hh:12-25 seal/backup minutes, 23:50-00:45 day close, 01:10-01:45 nightly
    seal + backups, and +-30 min around the next universe rotation."""
    r = []
    m, hm = now_utc.minute, now_utc.hour * 60 + now_utc.minute
    if 12 <= m <= 25:
        r.append("protected_window hh:12-25")
    if hm >= 23 * 60 + 50 or hm <= 45:
        r.append("protected_window 23:50-00:45")
    if 70 <= hm <= 105:
        r.append("protected_window 01:10-01:45")
    if isinstance(rotation_ms, (int, float)):
        if abs(now_utc.timestamp() * 1000 - rotation_ms) <= 30 * 60 * 1000:
            r.append("rotation_within_30min")
    return r


def monitor_trust_problems(status: dict, unit: dict, now: float) -> list:
    """Mirror of the G2 admission trust rule (research_exec.hostsignals.monitor_problems) on our snapshot."""
    r = []
    if not status.get("readable"):
        return ["monitor_status_unreadable"]
    if status.get("severity") not in OK_SEVERITIES:
        r.append(f"monitor_severity={status.get('severity')}")
    age = status.get("age_s")
    if age is None or age > MAX_STATUS_AGE_S:
        r.append(f"monitor_stale age_s={age}")
    w = status.get("writer") or {}
    if w.get("supervisor") != "systemd-user" or w.get("unit") != UNIT:
        r.append("monitor_unsupervised")
    if unit.get("ActiveState") != "active":
        r.append(f"unit_state={unit.get('ActiveState')}/{unit.get('SubState')}")
    elif str(w.get("pid")) != unit.get("MainPID") or w.get("invocation_id") != unit.get("InvocationID"):
        r.append("monitor_writer_not_unit_main")
    return r


def preflight_problems(s: dict) -> list:
    r = []
    u = s["unit"]
    if s["unit_file_sha256"] != UNIT_SHA256:
        r.append("unit_file_changed")
    if u.get("DropInPaths", "") != "":
        r.append(f"unexpected_dropins={u.get('DropInPaths')}")
    if any(s["dropin_files"].values()):
        r.append(f"dropin_files_present={sorted(k for k, v in s['dropin_files'].items() if v)}")
    for k, v in BASE.items():
        if u.get(k) != v:
            r.append(f"property {k}={u.get(k)} expected {v}")
    if u.get("MemorySwapMax") != "infinity":
        r.append(f"MemorySwapMax={u.get('MemorySwapMax')} (already applied or drifted)")
    cg = s["cgroup"]
    for k, v in CG_BASE.items():
        if cg.get(k) != v:
            r.append(f"cgroup {k}={cg.get(k)} expected {v}")
    if cg.get("memory.swap.max") != "max":
        r.append(f"cgroup memory.swap.max={cg.get('memory.swap.max')}")
    if cg.get("memory.swap.current") not in ("0", None):
        r.append(f"monitor_swap_in_use={cg.get('memory.swap.current')} (allowed but recorded; review)")
    r += monitor_trust_problems(s["status"], u, s["t"])
    if s["research_units"]:
        r.append(f"research_units_loaded={s['research_units']} (a monitor hiccup would freeze them)")
    c = s["collector"]
    if not (c.get("running") and c.get("health") == "healthy" and c.get("id") == c.get("bound_cid")):
        r.append(f"collector_not_healthy_or_not_bound={c}")
    r += window_problems(dt.datetime.fromtimestamp(s["t"], dt.timezone.utc), s["status"].get("next_refresh_ms"))
    return r


def verify_problems(pre: dict, post: dict) -> list:
    r = []
    pu, qu = pre["unit"], post["unit"]
    for k in IDENTITY:
        if pu.get(k) != qu.get(k):
            r.append(f"identity_changed {k}: {pu.get(k)} -> {qu.get(k)} (restart happened)")
    if qu.get("MemorySwapMax") != "0":
        r.append(f"MemorySwapMax={qu.get('MemorySwapMax')} expected 0")
    if post["cgroup"].get("memory.swap.max") != "0":
        r.append(f"cgroup memory.swap.max={post['cgroup'].get('memory.swap.max')} expected 0")
    for k, v in BASE.items():
        if qu.get(k) != v:
            r.append(f"property {k} changed to {qu.get(k)}")
    for k, v in CG_BASE.items():
        if post["cgroup"].get(k) != v:
            r.append(f"cgroup {k} changed to {post['cgroup'].get(k)}")
    if post["unit_file_sha256"] != UNIT_SHA256:
        r.append("unit_file_changed")
    files = {p: t for p, t in post["dropin_files"].items() if t is not None}
    if list(files) != [EXPECTED_DROPIN]:
        r.append(f"dropin_set={sorted(files)} expected only {EXPECTED_DROPIN}")
    elif not dropin_is_exactly_swap0(files[EXPECTED_DROPIN]):
        r.append("dropin_content_not_exactly_MemorySwapMax=0")
    pe, qe = pre["cgroup"].get("memory.events", {}), post["cgroup"].get("memory.events", {})
    for k in ("max", "oom", "oom_kill", "oom_group_kill"):
        if qe.get(k, 0) > pe.get(k, 0):
            r.append(f"memory.events {k} {pe.get(k, 0)} -> {qe.get(k, 0)}")
    r += monitor_trust_problems(post["status"], qu, post["t"])
    if post["status"].get("t_ms") is not None and post["status"].get("t_ms") == pre["status"].get("t_ms"):
        r.append("status_not_rewritten_since_preflight (wait >= 60 s and verify again)")
    c0, c1 = pre["collector"], post["collector"]
    if c0.get("id") != c1.get("id") or c0.get("started_at") != c1.get("started_at") or \
            c1.get("restart_count") != c0.get("restart_count") or c1.get("health") != "healthy":
        r.append(f"collector_changed {c0} -> {c1}")
    return r


def rollback_problems(pre: dict, post: dict) -> list:
    """After the rollback commands: back to the preflight definition, monitor never restarted."""
    r = []
    pu, qu = pre["unit"], post["unit"]
    for k in IDENTITY:
        if pu.get(k) != qu.get(k):
            r.append(f"identity_changed {k}: {pu.get(k)} -> {qu.get(k)}")
    if qu.get("MemorySwapMax") != "infinity":
        r.append(f"MemorySwapMax={qu.get('MemorySwapMax')} expected infinity")
    if post["cgroup"].get("memory.swap.max") != "max":
        r.append(f"cgroup memory.swap.max={post['cgroup'].get('memory.swap.max')} expected max")
    if qu.get("DropInPaths", "") != "" or any(t is not None for t in post["dropin_files"].values()):
        r.append("dropins_remain")
    for k, v in BASE.items():
        if qu.get(k) != v:
            r.append(f"property {k} changed to {qu.get(k)}")
    if post["unit_file_sha256"] != UNIT_SHA256:
        r.append("unit_file_changed")
    r += monitor_trust_problems(post["status"], qu, post["t"])
    return r


# ------------------------------------------------------------------ read-only collection
def _run(args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def unit_show() -> dict:
    r = _run(["systemctl", "--user", "show", UNIT, "-p", ",".join(PROPS)])
    return dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)


def cgroup_snapshot(control_group: str) -> dict:
    d = CGROOT + control_group
    out = {}
    for f in ("memory.max", "memory.high", "memory.swap.max", "memory.swap.current", "memory.current"):
        t = _read(os.path.join(d, f))
        out[f] = None if t is None else t.strip()
    ev = _read(os.path.join(d, "memory.events")) or ""
    out["memory.events"] = {k: int(v) for k, v in (l.split() for l in ev.splitlines() if len(l.split()) == 2)}
    return out


def status_snapshot(now: float) -> dict:
    try:
        st = os.stat(STATUS)
        s = json.loads(_read(STATUS))
    except Exception as exc:
        return {"readable": False, "error": f"{type(exc).__name__}: {exc}"}
    ages = [now - st.st_mtime]
    if isinstance(s.get("t_ms"), (int, float)):
        ages.append(now - s["t_ms"] / 1000.0)
    w = s.get("monitor") if isinstance(s.get("monitor"), dict) else {}
    return {"readable": True, "severity": s.get("severity"), "t_ms": s.get("t_ms"), "age_s": round(max(ages), 1),
            "writer": {k: w.get(k) for k in ("supervisor", "unit", "pid", "invocation_id", "cid")},
            "next_refresh_ms": (s.get("universe_epoch") or {}).get("next_refresh_ms")}


def research_units() -> list:
    r = _run(["systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", "rj-*", "rw-*"])
    return sorted(l.split()[0] for l in r.stdout.splitlines() if l.strip())


def collector_snapshot() -> dict:
    try:
        b = json.loads(_read(BINDING))
    except Exception:
        b = {}
    name = b.get("container_name", "tsb-p2-forward-collector")
    r = _run(["docker", "inspect", "-f",
              "{{.Id}}|{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.State.StartedAt}}|"
              "{{.RestartCount}}", name])
    parts = r.stdout.strip().split("|") if r.returncode == 0 else []
    if len(parts) != 5:
        return {"bound_cid": b.get("cid"), "error": r.stderr.strip()[:200]}
    return {"bound_cid": b.get("cid"), "id": parts[0], "running": parts[1] == "true", "health": parts[2],
            "started_at": parts[3], "restart_count": parts[4]}


def snapshot() -> dict:
    now = time.time()
    u = unit_show()
    raw = _read(UNIT_FILE)
    files = {}
    for d in DROPIN_DIRS:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            files[os.path.join(d, n)] = _read(os.path.join(d, n))
    return {"record": "tsb.g6s3.monitor_swap_snapshot", "t": now,
            "t_utc": dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "unit": u, "unit_file_sha256": hashlib.sha256(raw.encode()).hexdigest() if raw is not None else None,
            "dropin_files": files, "cgroup": cgroup_snapshot(u.get("ControlGroup", "")),
            "status": status_snapshot(now), "research_units": research_units(), "collector": collector_snapshot()}


def _write(path, obj):
    with open(path, "x", encoding="utf-8") as fh:          # never overwrite evidence
        json.dump(obj, fh, indent=1, sort_keys=True)
        fh.write("\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preflight")
    p.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--pre", required=True)
    v.add_argument("--out", required=True)
    rb = sub.add_parser("verify-rollback")
    rb.add_argument("--pre", required=True)
    rb.add_argument("--out", required=True)
    sub.add_parser("commands")
    a = ap.parse_args(argv)
    if a.cmd == "commands":
        print("APPLY (owner-approved, live, no restart):\n  " + APPLY_CMD)
        print("ROLLBACK (in order):\n  " + "\n  ".join(ROLLBACK_CMDS))
        return 0
    s = snapshot()
    if a.cmd == "preflight":
        s["problems"] = preflight_problems(s)
        s["verdict"] = "GO" if not s["problems"] else "NO-GO"
    else:
        with open(a.pre, "r", encoding="utf-8") as fh:
            pre = json.load(fh)
        s["pre_t_utc"] = pre.get("t_utc")
        s["problems"] = (verify_problems if a.cmd == "verify" else rollback_problems)(pre, s)
        s["verdict"] = "PASS" if not s["problems"] else "FAIL"
    _write(a.out, s)
    print(json.dumps({"verdict": s["verdict"], "problems": s["problems"], "out": a.out}, indent=1))
    return 0 if s["verdict"] in ("GO", "PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
