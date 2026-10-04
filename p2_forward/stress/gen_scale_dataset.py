#!/usr/bin/env python3
"""V2 (CR-B02) synthetic continuous dataset: N closed calendar days (production calendar) of tiny but structurally
complete segments (9 types x 24 hourly segments x {.jsonl.gz, .sha256, .idx}), day manifests, day-close records,
one earlier cleanly stopped run (run record + downtime + stop marker) and dataset.json. Synthetic only: no market
data, never mixed with any real dataset. ~650 files per day => 365 days ~ 237k files.

  gen_scale_dataset.py <out_dir> <days> [<last_day YYYY-MM-DD>]
"""
import datetime as dt
import gzip
import hashlib
import json
import os
import sys

TYPES = ("book", "candle", "clock", "depth", "gap", "health", "lifecycle", "market", "universe")
CAL = {"hour_ms": 3_600_000, "epoch_hour": 0, "base": "1970-01-01T00:00:00+00:00"}


def wro(p, data: bytes):
    with open(p, "wb") as fh:
        fh.write(data)
    os.chmod(p, 0o444)


def main():
    out, n = sys.argv[1], int(sys.argv[2])
    last = dt.date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else dt.date.today() - dt.timedelta(days=1)
    boot = "5ca1e" + "0" * 27
    for d in ("raw", "manifests", "days", "runs", "control", "universe", "quarantine", "health", "docs"):
        os.makedirs(os.path.join(out, d), exist_ok=True)
    nfiles = 0
    for k in range(n):
        day = (last - dt.timedelta(days=n - 1 - k)).isoformat()
        files, man = [], []
        for t in TYPES:
            dd = os.path.join(out, "raw", t, day); os.makedirs(dd, exist_ok=True)
            for h in range(24 if t != "universe" else 1):
                hk = day.replace("-", "") + f"T{h:02d}"
                name = f"{t}-{hk}Z-{boot[:8]}-{k * 24 + h + 1:04d}.jsonl.gz"
                data = gzip.compress(json.dumps({"synthetic": True, "type": t, "hour": hk}).encode() + b"\n", mtime=0)
                dig = hashlib.sha256(data).hexdigest()
                p = os.path.join(dd, name)
                wro(p, data)
                wro(p + ".sha256", f"{dig}  {name}\n".encode())
                wro(p[:-9] + ".idx", json.dumps({"blk": 0, "end_offset": len(data), "records": 1, "durable_ts_ns": 1}).encode() + b"\n")
                rel = f"raw/{t}/{day}/{name}"
                for q in (p, p + ".sha256", p[:-9] + ".idx"):
                    files.append({"path": os.path.relpath(q, out), "bytes": os.path.getsize(q)})
                man.append({"segment": rel, "sha256": dig, "records": 1, "bytes": len(data), "type": t, "boot": boot[:8],
                            "boot_id": boot, "run_record": f"runs/run-{boot}.json", "certifier": "certifier-v1",
                            "recovered": False, "certified_ms": 1, "first_recv_ns": 1, "last_recv_ns": 1, "idx_bytes": 1})
                nfiles += 3
        mp = os.path.join(out, "manifests", f"{day}.jsonl")
        mdata = "".join(json.dumps(e, sort_keys=True) + "\n" for e in man).encode()
        with open(mp, "wb") as fh:
            fh.write(mdata)
        rec = {"record": "tsb.p2.forward.day_close", "record_version": 1, "day": day, "closed_ms": 1, "calendar": CAL,
               "segments": len(man), "files": sorted(files, key=lambda f: f["path"]),
               "bytes_total": sum(f["bytes"] for f in files), "manifest_file": f"manifests/{day}.jsonl",
               "manifest_sha256": hashlib.sha256(mdata).hexdigest(), "boots": [boot[:8]], "synthetic": True}
        wro(os.path.join(out, "days", f"{day}.json"), json.dumps(rec, sort_keys=True).encode())
    t0 = int(dt.datetime.combine(last - dt.timedelta(days=n - 1), dt.time(), dt.timezone.utc).timestamp() * 1000)
    t1 = int(dt.datetime.combine(last, dt.time(23, 59), dt.timezone.utc).timestamp() * 1000)
    wro(os.path.join(out, "runs", f"run-{boot}.json"), json.dumps({"record": "tsb.p2.forward.run", "boot_id": boot, "created_ms": t0,
                                                                     "mode": "continuous", "synthetic": True, "config": {}}).encode())
    wro(os.path.join(out, "runs", f"downtime-{boot}.json"), json.dumps({"record": "tsb.p2.forward.downtime", "boot_id": boot,
                                                                          "cause": "first_run", "previous_run": None, "until_ms": t0}).encode())
    wro(os.path.join(out, "control", f"stop-{boot[:8]}.json"), json.dumps({"event": "final_stop_state", "boot_id": boot, "state": "STOPPED",
                                                                             "exit_code": 0, "reason": "signal", "ws_start_ms": t0,
                                                                             "stop_requested_ms": t1, "last_boundary_ms": t1 - 1000}).encode())
    wro(os.path.join(out, "dataset.json"), json.dumps({"record": "tsb.p2.forward.dataset", "record_version": 1, "dataset_id": "v2-scale",
                                                       "created_ms": t0, "calendar": CAL, "schema": "tsb.p2.forward",
                                                       "schema_version": 2, "synthetic_history": True}).encode())
    print(json.dumps({"out": out, "days": n, "first": (last - dt.timedelta(days=n - 1)).isoformat(), "last": last.isoformat(),
                      "raw_files": nfiles}))


if __name__ == "__main__":
    main()
