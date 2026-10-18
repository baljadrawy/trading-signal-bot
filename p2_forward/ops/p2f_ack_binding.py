#!/usr/bin/env python3
"""Hash-bound operator acknowledgement of a P2 forward-collector incident (HOST side, stdlib only).

Why (2026-10-06 fail-closed recovery deadlock): the start gate refused while incidents/state.json had an active
CRITICAL incident with ack=None, but state.json's ack is written only by a RUNNING collector (IncidentLog.poll_acks
merges incidents/ack/<id>.json). After a fail-closed stop nothing merges the ack, so the documented recovery path could
never pass. The gate now accepts, for an active CRITICAL incident whose state ack is still None, ONLY an ack file that is
bound to exactly that incident record, dataset and run lineage. The collector's own merge path is unchanged: after the
start it merges the same file (it reads only "by" and "ref") and records the ack in state.json + events.jsonl.

Ack record (incidents/ack/<id>.json, written once, 0444, never overwritten):
  record / record_version          "tsb.p2.forward.incident_ack" / 2
  by, ref, reason                  operator, evidence reference, review reason (non-empty; by <= 80, ref <= 200 chars
                                   so the collector's merge never truncates them)
  ts_ms                            acknowledgement time (must be after the incident's last occurrence)
  dataset_id                       dataset.json dataset_id
  incident                         id, key, severity, boot8, first_ms, last_ms, count (copied from state.json)
  incident_sha256                  sha256 of the canonical JSON of the FULL incident record in state.json
  lineage                          latest run boot_id + sha256 of its immutable run record at ack time
  binding_sha256                   sha256 of the canonical JSON of all fields above

The binding is an integrity / anti-mistake check (stale, wrong-incident, reused, edited or malformed acks), not an
authentication against someone who can already write the dataset (who could edit state.json itself).

CLI:
  p2f_ack_binding.py ack  <dataset_dir> <incident_id> <by> <reference> <reason>   write one bound ack
  p2f_ack_binding.py gate <dataset_dir>                                             exit 0 iff no blocking CRITICAL
  p2f_ack_binding.py check <dataset_dir> <incident_id>                              validate one ack file
"""
import hashlib
import json
import os
import sys
import time

RECORD = "tsb.p2.forward.incident_ack"
VERSION = 2
MAX_ACK_BYTES = 65536
FUTURE_SKEW_MS = 300_000
INC_FIELDS = ("id", "key", "severity", "boot8", "first_ms", "last_ms", "count")
LIMITS = {"by": 80, "ref": 200, "reason": 1000}


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sha(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def file_sha(p: str) -> str:
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load_state(data: str) -> dict:
    with open(os.path.join(data, "incidents", "state.json"), encoding="utf-8") as fh:
        return json.load(fh)


def dataset_id(data: str):
    p = os.path.join(data, "dataset.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)["dataset_id"]


def latest_run(data: str):
    """Most recent run record (same ordering as the collector: created_ms, boot_id). None if no run exists."""
    d, best = os.path.join(data, "runs"), None
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not (f.startswith("run-") and f.endswith(".json")):
            continue
        p = os.path.join(d, f)
        with open(p, encoding="utf-8") as fh:
            r = json.load(fh)
        key = (r["created_ms"], r["boot_id"])
        if best is None or key > best[0]:
            best = (key, p, r["boot_id"])
    if best is None:
        return None
    return {"boot_id": best[2], "run_record_sha256": file_sha(best[1])}


def ack_path(data: str, iid: str) -> str:
    return os.path.join(data, "incidents", "ack", f"{iid}.json")


def build(data: str, inc: dict, by: str, ref: str, reason: str, ts_ms: int) -> dict:
    body = {"record": RECORD, "record_version": VERSION, "by": by, "ref": ref, "reason": reason, "ts_ms": ts_ms,
            "dataset_id": dataset_id(data), "incident": {k: inc.get(k) for k in INC_FIELDS},
            "incident_sha256": sha(inc), "lineage": latest_run(data)}
    return {**body, "binding_sha256": sha(body)}


def _text_problems(a: dict) -> list:
    out = []
    for k, lim in LIMITS.items():
        v = a.get(k)
        if not isinstance(v, str) or not v.strip():
            out.append(f"{k}_missing")
        elif len(v) > lim:
            out.append(f"{k}_too_long")
    return out


def validate(data: str, inc: dict, now=None) -> list:
    """Problems with incidents/ack/<inc id>.json as an acknowledgement of exactly this incident record ([] = valid)."""
    p = ack_path(data, inc["id"])
    if os.path.islink(p):
        return ["ack_is_symlink"]
    if not os.path.exists(p):
        return ["no_ack"]
    if not os.path.isfile(p):
        return ["ack_not_regular_file"]
    if os.path.getsize(p) > MAX_ACK_BYTES:
        return ["ack_too_large"]
    try:
        with open(p, encoding="utf-8") as fh:
            a = json.load(fh)
    except (OSError, ValueError) as e:
        return [f"ack_malformed:{type(e).__name__}"]
    if not isinstance(a, dict):
        return ["ack_not_object"]
    if a.get("record") != RECORD or a.get("record_version") != VERSION:
        return ["ack_unbound_or_wrong_version"]                       # legacy {by, ref, ts_ms} acks are not bindings
    out = _text_problems(a)
    body = {k: v for k, v in a.items() if k != "binding_sha256"}
    if a.get("binding_sha256") != sha(body):
        out.append("binding_hash_mismatch")
    bi = a.get("incident") if isinstance(a.get("incident"), dict) else {}
    if bi.get("id") != inc["id"]:
        out.append("wrong_incident_id")
    for k in INC_FIELDS[1:]:
        if bi.get(k) != inc.get(k):
            out.append(f"incident_{k}_mismatch")
    if a.get("incident_sha256") != sha(inc):
        out.append("incident_record_changed_since_ack")
    if a.get("dataset_id") != dataset_id(data):
        out.append("dataset_id_mismatch")
    if a.get("lineage") != latest_run(data):
        out.append("run_lineage_mismatch")
    ts = a.get("ts_ms")
    if not isinstance(ts, int) or isinstance(ts, bool):
        out.append("ts_ms_invalid")
    else:
        last = inc.get("last_ms") if isinstance(inc.get("last_ms"), int) else inc.get("first_ms")
        if not isinstance(last, int) or ts <= last:
            out.append("ack_not_after_incident")
        if ts > (now if now is not None else now_ms()) + FUTURE_SKEW_MS:
            out.append("ack_in_future")
    return out


def gate(data: str, now=None) -> dict:
    """Blocking CRITICAL incidents: active, state ack None and no VALID bound ack file. {id: [problems]}."""
    p = os.path.join(data, "incidents", "state.json")
    if not os.path.exists(p):
        return {}
    blocking = {}
    for inc in load_state(data)["incidents"]:
        if inc["active"] and inc["ack"] is None and inc["severity"] == "CRITICAL":
            probs = validate(data, inc, now)
            if probs:
                blocking[inc["id"]] = probs
    return blocking


def write_ack(data: str, iid: str, by: str, ref: str, reason: str) -> dict:
    st = load_state(data)
    inc = [i for i in st["incidents"] if i["id"] == iid]
    assert inc, f"unknown incident {iid}"
    inc = inc[0]
    assert inc["ack"] is None, f"already acknowledged in state.json: {inc['ack']}"
    assert inc["active"], "incident is not active (nothing to acknowledge)"
    p = ack_path(data, iid)
    if os.path.lexists(p):
        raise AssertionError(f"ack file already exists ({'valid' if not validate(data, inc) else validate(data, inc)}); "
                             "never overwritten - escalate to the owner")
    a = build(data, inc, by, ref, reason, now_ms())
    probs = _text_problems(a)
    assert not probs, f"invalid ack fields: {probs}"
    assert a["lineage"] is not None, "dataset has no run record"
    tmp = f"{p}.{os.getpid()}.tmp"                                    # not *.json: the collector's poll ignores it
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(a, sort_keys=True, indent=1) + "\n")
            fh.flush(); os.fsync(fh.fileno())
        os.link(tmp, p)                                               # atomic and never overwrites
    finally:
        os.unlink(tmp)
    dfd = os.open(os.path.dirname(p), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    probs = validate(data, inc)
    assert not probs, f"written ack does not validate: {probs}"
    return a


def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "ack" and len(argv) == 7:
            a = write_ack(*argv[2:7])
            print("ACK", a["incident"]["id"], a["incident"]["key"], a["incident"]["severity"],
                  f"boot8={a['incident']['boot8']} first_ms={a['incident']['first_ms']} ts_ms={a['ts_ms']}",
                  f"lineage={a['lineage']['boot_id'][:8]} binding_sha256={a['binding_sha256']}")
            return 0
        if cmd == "gate" and len(argv) == 3:
            b = gate(argv[2])
            if b:
                print(f"unacknowledged CRITICAL incidents: {json.dumps(dict(list(b.items())[:5]), sort_keys=True)} "
                      "(p2f_incident_ack.sh after review)")
                return 1
            print("incident gate: no blocking CRITICAL incident")
            return 0
        if cmd == "check" and len(argv) == 4:
            inc = [i for i in load_state(argv[2])["incidents"] if i["id"] == argv[3]]
            probs = validate(argv[2], inc[0]) if inc else ["unknown_incident"]
            print(json.dumps({"id": argv[3], "valid": not probs, "problems": probs}))
            return 0 if not probs else 1
    except (AssertionError, OSError, ValueError, KeyError, TypeError) as e:
        print(f"REFUSED: {type(e).__name__}: {e}")
        return 2
    print(__doc__.split("CLI:")[1], file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
