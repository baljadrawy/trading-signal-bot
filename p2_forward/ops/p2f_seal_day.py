#!/usr/bin/env python3
"""Independent daily seal (P2-CR Package C) — HOST-SIDE job, outside the collector's cgroup; stdlib only.

  p2f_seal_day.py <dataset_dir> --day YYYY-MM-DD [--allow-test-calendar]

Seals ONE completed calendar day with the independent day verifier (verifier/verify_continuous.py):
  * preconditions (otherwise exit 3, nothing written): the collector closed the day (days/D.json) and the next day's
    first-hour spillover segments are final (no .partial/.pending/.certifying);
  * PASS  -> seals/D.json + seals/D.report.json (0444, never overwritten; an existing seal => exit 4);
  * FAIL  -> seals/D.FAILED-<ms>.report.json + incidents/external/seal-D-<ms>.json (CRITICAL; visible to the collector
    and to the observe-only monitor), exit 1. A failed day is never backed up as sealed.
Never deletes anything. Never touches the collector process or container.
"""
import argparse
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(HERE, "..", "verifier"), os.path.join(HERE, "verifier")):
    if os.path.exists(os.path.join(cand, "verify_continuous.py")):
        sys.path.insert(0, os.path.abspath(cand)); break
import verify_continuous as VC                                    # noqa: E402


def _w_ro(path, obj):
    if os.path.exists(path):
        raise FileExistsError(path)
    tmp = path + ".partial"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, sort_keys=True, indent=1, default=str); fh.write("\n"); fh.flush(); os.fsync(fh.fileno())
    os.rename(tmp, path); os.chmod(path, 0o444)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("--day", required=True)
    ap.add_argument("--allow-test-calendar", action="store_true")
    a = ap.parse_args(argv)
    base, day = a.base, a.day
    sd = os.path.join(base, "seals"); os.makedirs(sd, exist_ok=True)
    seal = os.path.join(sd, f"{day}.json")
    if os.path.exists(seal):
        print(json.dumps({"seal": "exists", "day": day})); return 4
    if not os.path.exists(os.path.join(base, "days", f"{day}.json")):
        print(json.dumps({"seal": "not_ready", "reason": "day_not_closed", "day": day})); return 3
    ds = json.load(open(os.path.join(base, "dataset.json"), encoding="utf-8"))
    cal = VC.Calendar(ds["calendar"])
    nxt = cal.day_key(cal.day_end(day))
    n_spill = min(24, max(1, -(-60_000 // cal.hour_ms)))
    hours = {cal.hour_key(cal.day_end(day) + i * cal.hour_ms) for i in range(n_spill)}
    raw = os.path.join(base, "raw")
    for t in os.listdir(raw):
        dd = os.path.join(raw, t, nxt)
        if os.path.isdir(dd):
            for f in os.listdir(dd):
                if any(f"-{h}Z-" in f for h in hours) and f.endswith((".partial", ".pending", ".certifying")):
                    print(json.dumps({"seal": "not_ready", "reason": "spillover_not_final", "file": f})); return 3
    t0 = time.time()
    rep = VC.verify_day(base, day, a.allow_test_calendar)
    rep["elapsed_s"] = round(time.time() - t0, 1)
    now = int(time.time() * 1000)
    if not rep["PASS"]:
        _w_ro(os.path.join(sd, f"{day}.FAILED-{now}.report.json"), rep)
        os.makedirs(os.path.join(base, "incidents", "external"), exist_ok=True)
        _w_ro(os.path.join(base, "incidents", "external", f"seal-{day}-{now}.json"),
              {"job": "daily_seal", "day": day, "result": "FAIL", "severity": "CRITICAL",
               "failures": dict(list(rep["failures"].items())[:20])})
        print(json.dumps({"seal": "FAIL", "day": day, "failures": rep["failures"]}, default=str)[:4000], file=sys.stderr)
        return 1
    rp = os.path.join(sd, f"{day}.report.json")
    _w_ro(rp, rep)
    info = rep["info"]
    _w_ro(seal, {"record": "tsb.p2.forward.day_seal", "record_version": 1, "day": day, "dataset_id": info.get("dataset_id"),
                 "result": "PASS", "sealed_ms": now, "calendar": info.get("calendar"),
                 "verifier": rep["verifier"], "verifier_sha256": rep["verifier_sha256"],
                 "verify_independent_sha256": rep["verify_independent_sha256"], "report_sha256": _sha(rp),
                 "day_close_sha256": (info.get("day_close") or {}).get("sha256"),
                 "manifest_sha256": _sha(os.path.join(base, "manifests", f"{day}.jsonl"))
                 if os.path.exists(os.path.join(base, "manifests", f"{day}.jsonl")) else None,
                 "files": info.get("files"), "totals": info.get("totals"), "downtime_ms": info.get("downtime_ms"),
                 "runs": [r["boot"] for r in info.get("runs", [])],
                 "universe_ids": sorted({e["universe_id"] for e in info.get("epochs", [])}),
                 "universe_files": sorted({e["universe_file"] for e in info.get("epochs", []) if e.get("universe_file")})})
    print(json.dumps({"seal": "PASS", "day": day, "files": info.get("files"), "elapsed_s": rep["elapsed_s"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
