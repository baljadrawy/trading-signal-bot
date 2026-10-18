"""Independent verification of a forward data directory (stdlib only; read-only).

python3 -m p2_forward.verify <data_dir> [--since-ms N] [--until-ms N] [--json out.json]
Checks: certified segment checksums (sidecar + manifest), read-only mode, full decode, per-record schema,
duplicate obs_id across ALL segments, timestamp semantics, per-stream sampling coverage, leftover partials.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import os
import stat
import sys

from . import record as R
from .writer import sha256_file


def verify(base: str, since_ms: int | None = None, until_ms: int | None = None) -> dict:
    rep = {"segments": 0, "records": 0, "checksum_mismatch": [], "manifest_mismatch": [], "not_read_only": [],
           "decode_errors": [], "invalid_records": collections.Counter(), "duplicate_obs_ids": 0,
           "by_type": collections.Counter(), "by_type_symbol": collections.Counter(), "bytes_by_type": collections.Counter(),
           "semantic_violations": collections.Counter(), "leftover_partials": [], "quarantine_files": 0,
           "gaps": [], "clock": [], "lifecycle": [], "unchanged_ratio": {}, "coverage": {}, "recv_range_ms": [None, None]}
    manifest = {}
    mdir = os.path.join(base, "manifests")
    for f in sorted(os.listdir(mdir)) if os.path.isdir(mdir) else []:
        with open(os.path.join(mdir, f), encoding="utf-8") as fh:
            for line in fh:
                e = json.loads(line); manifest[e["segment"]] = e
    seen = set()
    samples = collections.defaultdict(list)
    unchanged = collections.Counter(); total_samp = collections.Counter()
    for root, _, files in os.walk(os.path.join(base, "raw")):
        for f in sorted(files):
            p = os.path.join(root, f); rel = os.path.relpath(p, base)
            if f.endswith(".partial"):
                rep["leftover_partials"].append(rel); continue
            if not f.endswith(".jsonl.gz"):
                continue
            rep["segments"] += 1
            digest = sha256_file(p)
            side = None
            if os.path.exists(p + ".sha256"):
                with open(p + ".sha256", encoding="utf-8") as fh:
                    side = fh.read().split()[0]
            if side != digest:
                rep["checksum_mismatch"].append(rel)
            if manifest.get(rel, {}).get("sha256") != digest:
                rep["manifest_mismatch"].append(rel)
            if os.stat(p).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
                rep["not_read_only"].append(rel)
            typ = f.split("-", 1)[0]
            rep["bytes_by_type"][typ] += os.path.getsize(p)
            try:
                with gzip.open(p, "rt", encoding="utf-8") as fh:
                    for line in fh:
                        rec = json.loads(line)
                        errs = R.validate(rec)
                        if errs:
                            rep["invalid_records"][errs[0]] += 1; continue
                        m = rec["recv_ts_ns"] // 1_000_000
                        if since_ms and m < since_ms or until_ms and m > until_ms:
                            continue
                        rep["records"] += 1
                        lo, hi = rep["recv_range_ms"]
                        rep["recv_range_ms"] = [m if lo is None else min(lo, m), m if hi is None else max(hi, m)]
                        if rec["obs_id"] in seen:
                            rep["duplicate_obs_ids"] += 1
                        seen.add(rec["obs_id"])
                        t = rec["type"]; rep["by_type"][t] += 1
                        if rec.get("symbol"):
                            rep["by_type_symbol"][f"{t}|{rec['symbol']}"] += 1
                        if t in ("book", "depth"):
                            if rec["exchange_event_time_ms"] is not None:
                                rep["semantic_violations"]["book_depth_exchange_time_not_null"] += 1
                            if rec["available_at_ms"] != rec["observed_at_ms"]:
                                rep["semantic_violations"]["available_ne_observed"] += 1
                            if rec["sample_ms"] is None or rec["observed_at_ms"] > rec["sample_ms"]:
                                rep["semantic_violations"]["observed_after_sample"] += 1
                            k = f"{t}|{rec['symbol']}|c{rec['cadence_ms']}"
                            samples[k].append(rec["sample_ms"]); total_samp[k] += 1
                            unchanged[k] += 1 if rec["unchanged"] else 0
                        if t == "candle" and not (rec["available_at_ms"] > int(rec["payload"][6]) >= int(rec["payload"][0])):
                            rep["semantic_violations"]["candle_availability"] += 1
                        if t == "gap":
                            rep["gaps"].append(rec["payload"] | {"recoverability": rec["recoverability"]})
                        if t == "clock":
                            rep["clock"].append(rec["payload"])
                        if t == "lifecycle":
                            rep["lifecycle"].append({"event": rec["payload"].get("event"), "ms": m})
            except (OSError, EOFError, ValueError) as e:
                rep["decode_errors"].append(f"{rel}:{type(e).__name__}")
    for k, xs in samples.items():
        xs.sort(); cad = int(k.rsplit("|c", 1)[1])
        expected = (xs[-1] - xs[0]) // cad + 1 if xs else 0
        missing = sum(max(0, (b - a) // cad - 1) for a, b in zip(xs, xs[1:]))
        rep["coverage"][k] = {"samples": len(xs), "expected_between_first_last": expected, "missing": missing,
                              "coverage": round(len(xs) / expected, 6) if expected else None,
                              "first_ms": xs[0], "last_ms": xs[-1]}
        rep["unchanged_ratio"][k] = round(unchanged[k] / total_samp[k], 4)
    qd = os.path.join(base, "quarantine")
    rep["quarantine_files"] = len(os.listdir(qd)) if os.path.isdir(qd) else 0
    for k in ("by_type", "by_type_symbol", "bytes_by_type", "invalid_records", "semantic_violations"):
        rep[k] = dict(rep[k])
    rep["PASS"] = not (rep["checksum_mismatch"] or rep["manifest_mismatch"] or rep["not_read_only"] or rep["decode_errors"]
                       or rep["invalid_records"] or rep["duplicate_obs_ids"] or rep["semantic_violations"] or rep["leftover_partials"])
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir"); ap.add_argument("--since-ms", type=int); ap.add_argument("--until-ms", type=int)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    rep = verify(a.data_dir, a.since_ms, a.until_ms)
    out = json.dumps(rep, indent=1, sort_keys=True, default=str)
    if a.json:
        open(a.json, "w", encoding="utf-8").write(out + "\n")
    summary = {k: rep[k] for k in ("PASS", "segments", "records", "duplicate_obs_ids", "by_type", "semantic_violations",
                                   "invalid_records", "leftover_partials", "quarantine_files")}
    summary["checksum_problems"] = len(rep["checksum_mismatch"]) + len(rep["manifest_mismatch"])
    print(json.dumps(summary, sort_keys=True, default=str))
    return 0 if rep["PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
