#!/usr/bin/env python3
"""Summaries for the P2-CR offline validations (stdlib). usage:
  v_analyze.py run <telemetry.jsonl> [<monitor_dir>]      latency / GC / CPU / memory / throttling summary
  v_analyze.py lifecycle <dataset_dir>                     lifecycle event counts and key payloads (continuous mode)"""
import glob
import gzip
import json
import os
import statistics
import sys


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None


def run(tel, mon=None):
    rows = [json.loads(l) for l in open(tel)]
    ll = [r.get("ll_max", 0) for r in rows]
    lat = [(r.get("ins") or {}).get("sampler_lateness_max_60s_ms") or 0 for r in rows]
    gcmax = max(((r.get("gc") or {}).get("max_ms") or 0) for r in rows) if rows else None
    out = {"seconds": len(rows), "loop_lag_max_ms": max(ll, default=None), "loop_lag_p99_per_s_ms": pct(ll, 0.99),
           "loop_lag_ge_200ms_seconds": sum(1 for x in ll if x >= 200), "sampler_lateness_max_ms": max(lat, default=None),
           "gc_pause_max_ms": gcmax, "health_states": {}}
    for r in rows:
        out["health_states"][r.get("health")] = out["health_states"].get(r.get("health"), 0) + 1
    if rows:
        last = rows[-1]
        out["writer_max_beat_gap_ms"] = (last.get("w") or {}).get("max_beat_gap_ms")
        out["writer_max_durable_lag_ms"] = (last.get("w") or {}).get("max_durable_lag_ms")
        out["certifier_max_ms"] = (last.get("cert") or {}).get("max_ms")
    if mon:
        s = [json.loads(l) for f in sorted(glob.glob(os.path.join(mon, "*", "samples.jsonl"))) for l in open(f)]
        cpu = [x["cpu_cores_60s"] for x in s if x.get("cpu_cores_60s") is not None]
        thr = [x["throttled_frac_60s"] for x in s if x.get("throttled_frac_60s") is not None]
        mem = [x["mem_pct_of_limit"] for x in s if x.get("alive")]
        out["monitor"] = {"samples": len(s), "cpu_cores_avg": round(statistics.mean(cpu), 3) if cpu else None,
                          "cpu_cores_max": max(cpu, default=None), "throttled_avg": round(statistics.mean(thr), 4) if thr else None,
                          "throttled_max": max(thr, default=None), "mem_pct_first": mem[0] if mem else None,
                          "mem_pct_last": mem[-1] if mem else None, "mem_pct_max": max(mem, default=None),
                          "severities": sorted({x.get("severity") for x in s}),
                          "alerts": [json.loads(l) for l in open(os.path.join(mon, "alerts.jsonl"))] if os.path.exists(os.path.join(mon, "alerts.jsonl")) else []}
    return out


def lifecycle(d):
    ev, keep = {}, {"universe_transition": [], "ws_rotation": [], "fail_closed_stop": [], "downtime": [], "day_closed": []}
    for f in sorted(glob.glob(os.path.join(d, "raw", "lifecycle", "*", "*.jsonl.gz"))):
        for line in gzip.open(f, "rt"):
            p = json.loads(line)["payload"]
            e = p.get("event")
            ev[e] = ev.get(e, 0) + 1
            if e in keep:
                keep[e].append({k: p.get(k) for k in ("reason", "overlap_ok", "added", "removed", "retiered", "cause",
                                                      "day", "segments", "effective_from_ms", "conn")})
    inc = json.load(open(os.path.join(d, "incidents", "state.json")))["incidents"] if os.path.exists(os.path.join(d, "incidents", "state.json")) else []
    return {"events": ev, "detail": keep, "incidents": [{k: i.get(k) for k in ("id", "key", "severity", "count", "active")} for i in inc],
            "days_closed": sorted(f[:-5] for f in os.listdir(os.path.join(d, "days"))) if os.path.isdir(os.path.join(d, "days")) else [],
            "quarantine": sorted(os.listdir(os.path.join(d, "quarantine"))) if os.path.isdir(os.path.join(d, "quarantine")) else [],
            "recovered_segments": len(glob.glob(os.path.join(d, "raw", "*", "*", "*-recovered-*.jsonl.gz")))}


if __name__ == "__main__":
    out = run(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None) if sys.argv[1] == "run" else lifecycle(sys.argv[2])
    print(json.dumps(out, default=str))
