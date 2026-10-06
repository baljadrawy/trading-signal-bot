#!/usr/bin/env python3
"""Explicit, validated collector binding for the supervised P2 monitor (G4). HOST side, stdlib only.

  p2f_monitor_bind.py show  [--binding FILE] [--name NAME] [--dataset DIR]
      Read-only. Compare the binding file with `docker inspect NAME` (Class A) and the Docker-free proof.
      Exit 0 = binding matches the running collector; 3 = mismatch / stale; 4 = no running collector.
  p2f_monitor_bind.py bind  --reason TEXT [--binding FILE] [--name NAME] [--dataset DIR] [--restart] [--unit UNIT]
      Resolve NAME -> full id with `docker inspect` (read-only), validate it, write the binding atomically (the
      previous binding is appended to <binding>.history.jsonl), and with --restart restart ONLY the monitor unit
      and wait (bounded) until status.json is written by the new process against the new id.

Validation before a binding is written (all must hold, otherwise nothing is written, exit 3):
  - the container named NAME is running, its compose labels are project=tsb-p2-forward / service=collector;
  - it mounts --dataset read-write at /data;
  - Docker-free cross-check: /sys/fs/cgroup/system.slice/docker-<id>.scope contains `python -m p2_forward` whose
    /data is the same device+inode as --dataset.
This tool never starts, stops or recreates the collector and never touches the dataset. The monitor itself never
calls Docker: re-binding is always this explicit, attributable step (G3 recreates the collector with a new id).
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p2f_cont_monitor as M  # noqa: E402  (shared Docker-free helpers)

DEF_NAME = "tsb-p2-forward-collector"
DEF_DATASET = "/home/tradmin/research-data/trading-signal-bot/p2/forward-continuous-v1"
DEF_BINDING = "/home/tradmin/ops/tsb-p2-forward/monitor/p2-forward-continuous-v1.binding.json"
DEF_OUT = "/home/tradmin/ops/tsb-p2-forward/monitor/p2-forward-continuous-v1"
DEF_UNIT = "tsb-p2f-monitor.service"
PROJECT, SERVICE = "tsb-p2-forward", "collector"


def inspect(name):
    r = subprocess.run(["docker", "inspect", "--type", "container", name], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return None
    d = json.loads(r.stdout)[0]
    lab = (d.get("Config") or {}).get("Labels") or {}
    return {"cid": d["Id"], "name": d["Name"].lstrip("/"), "running": d["State"]["Running"],
            "started_at": d["State"]["StartedAt"], "image": d["Config"]["Image"],
            "compose_project": lab.get("com.docker.compose.project"),
            "compose_service": lab.get("com.docker.compose.service"),
            "mounts": [(m.get("Source"), m.get("Destination"), m.get("RW")) for m in d.get("Mounts") or []]}


def validate(c, dataset):
    bad = []
    if not c:
        return ["container_not_found"]
    if not c["running"]:
        bad.append("not_running")
    if (c["compose_project"], c["compose_service"]) != (PROJECT, SERVICE):
        bad.append(f"compose_labels={c['compose_project']}/{c['compose_service']}")
    if not any(os.path.realpath(s or "") == os.path.realpath(dataset) and d == "/data" and rw for s, d, rw in c["mounts"]):
        bad.append("dataset_not_mounted_rw_at_/data")
    pid, ok = M.collector_in_scope(f"{M.CGROOT}/docker-{c['cid']}.scope", dataset, "python -m p2_forward")
    if pid is None:
        bad.append("no_collector_process_in_scope")
    elif not ok:
        bad.append("scope_collector_data_is_not_dataset")
    return bad


def show(a):
    b = M.jrd(a.binding)
    c = inspect(a.name)
    out = {"binding": b, "live": c, "live_validation": validate(c, a.dataset) if c else ["container_not_found"]}
    st = M.jrd(os.path.join(a.out, "status.json")) or {}
    out["status_monitor"] = st.get("monitor")
    out["status_age_s"] = round(time.time() - st["t_ms"] / 1000, 1) if st.get("t_ms") else None
    print(json.dumps(out, indent=1, sort_keys=True, default=str))
    if not c or not c["running"]:
        return 4
    return 0 if b and b.get("cid") == c["cid"] and not out["live_validation"] else 3


def bind(a):
    c = inspect(a.name)
    bad = validate(c, a.dataset)
    if bad:
        print(json.dumps({"refused": bad, "live": c}, indent=1, default=str), file=sys.stderr)
        return 3
    new = {"schema": M.BINDING_SCHEMA, "container_name": c["name"], "cid": c["cid"], "dataset": a.dataset,
           "image": c["image"], "compose_project": c["compose_project"], "compose_service": c["compose_service"],
           "container_started_at": c["started_at"],
           "bound_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "bound_by": os.environ.get("USER", "?"), "reason": a.reason}
    old = M.jrd(a.binding)
    if old:
        with open(a.binding + ".history.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"replaced_at": new["bound_at"], "binding": old}, sort_keys=True) + "\n")
    tmp = a.binding + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(new, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, a.binding)
    print(f"bound {c['name']} -> {c['cid'][:12]} (previous {(old or {}).get('cid', '-')[:12]})")
    if not a.restart:
        return 0
    t0 = int(time.time() * 1000)
    r = subprocess.run(["systemctl", "--user", "restart", a.unit], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"restart failed: {r.stderr.strip()}", file=sys.stderr)
        return 5
    deadline = time.time() + 150
    while time.time() < deadline:
        st = M.jrd(os.path.join(a.out, "status.json")) or {}
        mon = st.get("monitor") or {}
        if (st.get("t_ms") or 0) > t0 and mon.get("cid") == c["cid"]:
            print(f"monitor re-bound: pid={mon.get('pid')} unit={mon.get('unit')} severity={st.get('severity')} "
                  f"binding_check={mon.get('binding_check')}")
            return 0
        time.sleep(2)
    print("timed out waiting for a fresh status.json from the re-bound monitor", file=sys.stderr)
    return 6


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["show", "bind"])
    ap.add_argument("--binding", default=DEF_BINDING)
    ap.add_argument("--name", default=DEF_NAME)
    ap.add_argument("--dataset", default=DEF_DATASET)
    ap.add_argument("--out", default=DEF_OUT)
    ap.add_argument("--unit", default=DEF_UNIT)
    ap.add_argument("--reason")
    ap.add_argument("--restart", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "bind" and not a.reason:
        ap.error("bind needs --reason")
    return show(a) if a.cmd == "show" else bind(a)


if __name__ == "__main__":
    sys.exit(main())
