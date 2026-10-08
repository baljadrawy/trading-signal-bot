#!/usr/bin/env python3
"""G3 Stage G: 24 h before/after resize comparison. READ-ONLY, single foreground pass, stdlib only. owner=agent:g3-stage-g

  timeout 600 nice -n 19 python3 -B g3_24h_compare.py --anchors <ev>/observe/anchors.json --out <file.json> \
      [--hours 24] [--sampler <ev>/observe/sampler_pre.jsonl --sampler <ev>/observe/sampler_w2.jsonl]

Sources (nothing else is read; nothing is written except --out, which must be outside the dataset/monitor/ops dirs):
  1. the monitor's 60 s samples  <monitor_out>/<YYYY-MM-DD>/samples.jsonl  (throttled_frac_60s, cpu_cores_60s,
     cpu_pct_of_quota, mem_pct_of_limit, mem_anon, mem_current, loop_lag_max_60s_ms, sampler_lateness_max_60s_ms,
     writer.beat_age_ms / durable_lag_ms, health_state, severity) for [stop-H, stop) and [start, start+H);
  2. cgroup counters: the OLD container's cumulative cpu.stat / memory.events captured in anchors.json just before
     the gated stop (its scope no longer exists), and the NEW container's live cpu.stat / memory.events now, minus
     the values captured right after its start (anchors.json);
  3. host steal: /proc/stat now minus the /proc/stat anchor taken at the new start (aggregate steal ratio of the
     after window) and the since-boot steal ratio at the stop anchor (the only aggregate available for "before":
     no existing source records per-minute steal history);
  4. optional --sampler files (the evidence 60 s samplers, which DO record per-minute steal): throttling, lateness
     and memory events are banded by host steal ratio (<0.2, 0.2-0.3, 0.3-0.4, >0.4) only where steal was measured.
Interpretation rule (P2F_G3_RESIZE_READINESS.md s.5 step 10): throttling is quota-local; steal is hypervisor time.
Never attribute a lateness change to the resize unless it holds within the same steal band.
Acceptance (S2): hourly throttling <= 10 % over 24 h, beat_age < 3 s, durable_lag < 5 s, 0 DEGRADED.
"""
import argparse, datetime as dt, json, os, statistics, sys, time

sys.dont_write_bytecode = True
MON = "/home/tradmin/ops/tsb-p2-forward/monitor/p2-forward-continuous-v1"
CG = "/sys/fs/cgroup/system.slice"
GUARD = ("/home/tradmin/research-data/trading-signal-bot/p2/forward-continuous-v1", "/home/tradmin/ops/tsb-p2-forward")
BANDS = ((0.0, 0.2, "<0.2"), (0.2, 0.3, "0.2-0.3"), (0.3, 0.4, "0.3-0.4"), (0.4, 1.01, ">0.4"))
H = 3_600_000


def utc(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def kv(p):
    out = {}
    with open(p) as fh:
        for line in fh:
            a = line.split()
            if len(a) == 2 and a[1].lstrip("-").isdigit():
                out[a[0]] = int(a[1])
    return out


def proc_stat():
    f = [int(x) for x in open("/proc/stat").readline().split()[1:]]
    return {"steal": f[7], "busy": f[0] + f[1] + f[2] + f[5] + f[6]}


def q(xs, p):
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]


def samples(lo, hi):
    out, d = [], dt.datetime.fromtimestamp(lo / 1000, dt.timezone.utc).date()
    end = dt.datetime.fromtimestamp(hi / 1000, dt.timezone.utc).date()
    while d <= end:
        p = os.path.join(MON, d.isoformat(), "samples.jsonl")
        if os.path.exists(p):
            with open(p) as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(r.get("t_ms"), int) and lo <= r["t_ms"] < hi:
                        out.append(r)
        d += dt.timedelta(days=1)
    return out


def summarize(rs):
    g = lambda k: [r.get(k) for r in rs]
    w = lambda k: [(r.get("writer") or {}).get(k) for r in rs]
    thr = [x for x in g("throttled_frac_60s") if isinstance(x, (int, float))]
    return {"n": len(rs), "throttled_frac_mean": round(statistics.fmean(thr), 4) if thr else None,
            "throttled_frac_p95": q(thr, .95), "frac_minutes_throttled_gt_10pct": round(sum(x > .1 for x in thr) / len(thr), 4) if thr else None,
            "cpu_cores_mean": round(statistics.fmean([x for x in g("cpu_cores_60s") if isinstance(x, (int, float))] or [0]), 4),
            "cpu_pct_of_quota_p95": q(g("cpu_pct_of_quota"), .95), "mem_pct_of_limit_max": q(g("mem_pct_of_limit"), 1),
            "mem_anon_max": q(g("mem_anon"), 1), "loop_lag_p95_ms": q(g("loop_lag_max_60s_ms"), .95),
            "loop_lag_max_ms": q(g("loop_lag_max_60s_ms"), 1), "sampler_lateness_p95_ms": q(g("sampler_lateness_max_60s_ms"), .95),
            "sampler_lateness_max_ms": q(g("sampler_lateness_max_60s_ms"), 1), "beat_age_max_ms": q(w("beat_age_ms"), 1),
            "durable_lag_max_ms": q(w("durable_lag_ms"), 1),
            "not_healthy_samples": sum(r.get("health_state") != "HEALTHY" for r in rs),
            "severity_counts": {s: sum(r.get("severity") == s for r in rs) for s in sorted({r.get("severity") for r in rs}, key=str)}}


def hourly(rs, t0):
    out = []
    for i in range(0, 48):
        part = [r for r in rs if t0 + i * H <= r["t_ms"] < t0 + (i + 1) * H]
        if part:
            s = summarize(part)
            out.append({"hour_from": utc(t0 + i * H), "n": s["n"], "throttled_frac_mean": s["throttled_frac_mean"],
                        "loop_lag_p95_ms": s["loop_lag_p95_ms"], "beat_age_max_ms": s["beat_age_max_ms"],
                        "durable_lag_max_ms": s["durable_lag_max_ms"], "not_healthy": s["not_healthy_samples"]})
    return out


def banded(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    rows = [r for r in rows if r.get("event") == "sample" and r.get("d")]
    out = {}
    for lo, hi, name in BANDS:
        b = [r["d"] for r in rows if lo <= r["d"]["steal_ratio"] < hi]
        if b:
            tf = [x["throttled_frac"] for x in b if x["throttled_frac"] is not None]
            out[name] = {"minutes": len(b), "throttled_frac_mean": round(statistics.fmean(tf), 4) if tf else None,
                         "cpu_cores_mean": round(statistics.fmean(x["cpu_cores"] for x in b), 4),
                         "mem_events_max": sum(x["mem_events_max"] for x in b), "mem_events_oom": sum(x["mem_events_oom"] for x in b)}
    return {"file": path, "minutes": len(rows), "cpu_max": (rows[-1]["cg"] or {}).get("cpu_max") if rows else None,
            "steal_ratio_mean": round(statistics.fmean(r["d"]["steal_ratio"] for r in rows), 4) if rows else None, "bands": out}


def delta(a, b, keys):
    return {k: (b.get(k) or 0) - (a.get(k) or 0) for k in keys}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchors", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--sampler", action="append", default=[])
    a = ap.parse_args()
    rp = os.path.realpath(a.out)
    if any(rp.startswith(os.path.realpath(g) + os.sep) for g in GUARD):
        sys.exit("REFUSED: --out must be outside the dataset / ops directories")
    an = json.load(open(a.anchors))
    now = time.time_ns() // 1_000_000
    stop, hw = an["stop_requested_ms"], int(a.hours * H)
    start = an.get("monitor_after_from_ms", an["new_start_ms"])   # after-window begins at the monitor rebind
    before, after = samples(stop - hw, stop), samples(start, min(start + hw, now))
    res = {"schema": "g3-24h-compare-v1", "evaluated_utc": utc(now), "hours": a.hours,
           "windows": {"before": [utc(stop - hw), utc(stop)], "after": [utc(start), utc(min(start + hw, now))]},
           "after_window_complete": now >= start + hw,
           "monitor_samples": {"before": summarize(before), "after": summarize(after)},
           "hourly": {"before": hourly(before, stop - hw), "after": hourly(after, start)}}
    ck = ("usage_usec", "nr_periods", "nr_throttled", "throttled_usec")
    ek = ("high", "max", "oom", "oom_kill")
    old_a, old_b = an["old_cg_at_old_start_or_t0"], an["old_cg_before_stop"]
    od = delta(old_a["cpu.stat"], old_b["cpu.stat"], ck)
    scope = os.path.join(CG, f"docker-{an['new_cid']}.scope")
    cg = {"before_old_container": {"from": old_a["utc"], "to": old_b["utc"], "cpu.stat": od,
                                   "throttled_frac": round(od["nr_throttled"] / od["nr_periods"], 4) if od["nr_periods"] else None,
                                   "memory.events": delta(old_a["memory.events"], old_b["memory.events"], ek)}}
    if os.path.isdir(scope):
        live_c, live_e = kv(os.path.join(scope, "cpu.stat")), kv(os.path.join(scope, "memory.events"))
        nd = delta(an["new_cg_after_start"]["cpu.stat"], live_c, ck)
        cg["after_new_container"] = {"from": an["new_cg_after_start"]["utc"], "to": utc(now), "cpu.stat": nd,
                                     "throttled_frac": round(nd["nr_throttled"] / nd["nr_periods"], 4) if nd["nr_periods"] else None,
                                     "memory.events": delta(an["new_cg_after_start"]["memory.events"], live_e, ek),
                                     "cpu.max": open(os.path.join(scope, "cpu.max")).read().strip(),
                                     "memory.max": open(os.path.join(scope, "memory.max")).read().strip()}
    else:
        cg["after_new_container"] = {"problem": f"scope of {an['new_cid'][:12]} not found (collector recreated or stopped?)"}
    res["cgroup_counters"] = cg
    ps, pa, pb = proc_stat(), an["proc_stat_at_new_start"], an["proc_stat_at_stop"]
    ds, db = ps["steal"] - pa["steal"], ps["busy"] - pa["busy"]
    res["host_steal"] = {"after_window_aggregate_ratio": round(ds / (ds + db), 4) if ds + db else None,
                         "since_boot_ratio_at_stop": round(pb["steal"] / (pb["steal"] + pb["busy"]), 4),
                         "note": "no existing source records per-minute steal over 24 h; banding only from --sampler files"}
    res["steal_banded_samplers"] = [banded(p) for p in a.sampler if os.path.exists(p)]
    af = res["monitor_samples"]["after"]
    hr = res["hourly"]["after"]
    res["S2_after"] = {"hourly_throttling_le_10pct": all((h["throttled_frac_mean"] or 0) <= .10 for h in hr) if hr else None,
                       "beat_age_lt_3s": (af["beat_age_max_ms"] or 0) < 3000, "durable_lag_lt_5s": (af["durable_lag_max_ms"] or 0) < 5000,
                       "zero_degraded": not any(k in ("DEGRADED", "CRITICAL") for k in af["severity_counts"]),
                       "window_complete": res["after_window_complete"]}
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    b4, aft = res["monitor_samples"]["before"], af
    print(f"windows before {res['windows']['before']} after {res['windows']['after']} complete={res['after_window_complete']}")
    for k in ("n", "throttled_frac_mean", "frac_minutes_throttled_gt_10pct", "cpu_cores_mean", "cpu_pct_of_quota_p95",
              "mem_pct_of_limit_max", "loop_lag_p95_ms", "sampler_lateness_p95_ms", "beat_age_max_ms", "durable_lag_max_ms",
              "not_healthy_samples", "severity_counts"):
        print(f"  {k:34} before {b4[k]!s:>14}   after {aft[k]!s:>14}")
    print("cgroup", json.dumps(cg, sort_keys=True))
    print("steal", json.dumps(res["host_steal"]))
    print("S2_after", json.dumps(res["S2_after"]))
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
