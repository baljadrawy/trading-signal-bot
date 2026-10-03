"""Stress-run analysis (host, stdlib). Inputs: one run dir (data/ + out/). Output: out/analysis.json + summary text.

Sampler lateness is EXACT from persisted records: per 1 s boundary, lateness = max(queued_ts - sample_ms) over the
records sampled at that boundary (live sampling path); sampler_stall gaps (>2 s, never persisted) are counted
separately. Correlation windows use the host lifecycle poller (100 ms), host cgroup samples (1 s) and in-process
telemetry (1 s): reported as temporal overlap, never as causation.
"""
import collections
import glob
import gzip
import json
import os
import statistics
import sys

TH = (100, 200, 500, 1000, 2000)


def pct(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * p / 100
    f = int(k)
    return s[f] if f + 1 >= len(s) else round(s[f] + (s[f + 1] - s[f]) * (k - f), 1)


def dist(xs):
    return {"n": len(xs), "p50": pct(xs, 50), "p95": pct(xs, 95), "p99": pct(xs, 99), "p999": pct(xs, 99.9),
            "max": max(xs) if xs else None, "mean": round(statistics.fmean(xs), 1) if xs else None,
            "ge": {str(t): sum(1 for x in xs if x >= t) for t in TH}}


def load_jsonl(p):
    out = []
    if os.path.exists(p):
        with open(p) as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def main(run):
    data, out = os.path.join(run, "data"), os.path.join(run, "out")
    # ---- persisted records (collector's own types only; injected zl* load excluded) ----
    per_boundary = collections.defaultdict(int)
    stalls, gaps_by_cause = [], collections.Counter()
    pit_viol, records = 0, collections.Counter()
    life = []
    for f in sorted(glob.glob(os.path.join(data, "raw", "*", "*", "*.jsonl.gz"))):
        typ = os.path.basename(os.path.dirname(os.path.dirname(f)))
        if typ.startswith("zl"):
            continue
        with gzip.open(f, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                records[r["type"]] += 1
                sm = r.get("sample_ms")
                if r["type"] in ("book", "depth", "market") and sm is not None:
                    lat = r["queued_ts_ns"] // 1_000_000 - sm
                    if lat > per_boundary[sm]:
                        per_boundary[sm] = lat
                    per_boundary.setdefault(sm, lat)
                    if r.get("recv_ts_ns") is not None and r["recv_ts_ns"] > sm * 1_000_000:
                        pit_viol += 1
                elif r["type"] == "gap":
                    p = r["payload"]
                    gaps_by_cause[p.get("cause")] += 1
                    if p.get("cause") == "sampler_stall":
                        stalls.append(p)
                elif r["type"] == "lifecycle":
                    life.append(r["payload"] | {"_ts": r["recv_ts_ns"] // 1_000_000})
    lats = [per_boundary[k] for k in sorted(per_boundary)]
    lat_series = sorted(per_boundary.items())
    # ---- stop / counters ----
    stop = {}
    for f in glob.glob(os.path.join(data, "control", "stop-*.json")):
        stop = json.load(open(f))
    hx = json.load(open(os.path.join(out, "harness_exit.json"))) if os.path.exists(os.path.join(out, "harness_exit.json")) else {}
    ctr = stop.get("counters") or hx.get("counters") or {}
    # ---- telemetry ----
    tel = load_jsonl(os.path.join(out, "telemetry.jsonl"))
    ll_events = [e for t in tel for e in t.get("ll_ge", [])]
    gc_events = [e for t in tel for e in t.get("gc", {}).get("ge20", [])]
    last = tel[-1] if tel else {}
    # ---- cgroup ----
    cg = []
    p = os.path.join(out, "cgroup.tsv")
    if os.path.exists(p):
        with open(p) as fh:
            hdr = fh.readline().strip().split("\t")
            for line in fh:
                v = line.strip().split("\t")
                if len(v) == len(hdr) and v[1] not in ("None", ""):
                    cg.append({k: (int(x) if x.lstrip("-").isdigit() else x) for k, x in zip(hdr, v)})
    cgs = {}
    if len(cg) >= 2:
        a, b = cg[0], cg[-1]
        el = (b["t_ms"] - a["t_ms"]) / 1000
        cgs = {"window_s": round(el, 1), "cpu_usage_s": round((b["usage_usec"] - a["usage_usec"]) / 1e6, 1),
               "avg_cpu_cores": round((b["usage_usec"] - a["usage_usec"]) / 1e6 / el, 3),
               "nr_periods": b["nr_periods"] - a["nr_periods"], "nr_throttled": b["nr_throttled"] - a["nr_throttled"],
               "throttled_s": round((b["throttled_usec"] - a["throttled_usec"]) / 1e6, 2),
               "throttled_period_fraction": round((b["nr_throttled"] - a["nr_throttled"]) / max(1, b["nr_periods"] - a["nr_periods"]), 4),
               "mem_peak_mib": round(max(int(x["mem_peak"]) for x in cg if str(x["mem_peak"]).isdigit()) / 2**20, 1),
               "mem_current_max_mib": round(max(int(x["mem_current"]) for x in cg) / 2**20, 1),
               "pids_max": max(int(x["pids_current"]) for x in cg)}
        per_s = []
        for x, y in zip(cg, cg[1:]):
            dt_ = (y["t_ms"] - x["t_ms"]) / 1000
            if dt_ > 0:
                per_s.append({"t_ms": y["t_ms"], "cpu": (y["usage_usec"] - x["usage_usec"]) / 1e6 / dt_,
                              "thr_ms": (y["throttled_usec"] - x["throttled_usec"]) / 1000,
                              "thr_n": y["nr_throttled"] - x["nr_throttled"], "per": y["nr_periods"] - x["nr_periods"]})
        cgs["cpu_1s"] = dist([round(s["cpu"] * 1000) for s in per_s])          # milli-cores per 1 s window
        cgs["throttled_ms_per_1s"] = dist([round(s["thr_ms"]) for s in per_s])
    else:
        per_s = []
    # ---- certification timeline (host poller) ----
    lc = load_jsonl(os.path.join(out, "lifecycle.jsonl"))
    st = collections.defaultdict(dict)
    for e in lc:
        st[e["seg"]].setdefault(e["state"], e["t_ms"])
    certs = []
    for seg, s in st.items():
        if "certifying" in s and "certified" in s:
            certs.append({"seg": seg, "start": s["certifying"], "end": s["certified"], "dur_ms": s["certified"] - s["certifying"],
                          "queued_ms": s["certifying"] - s.get("pending", s["certifying"]), "load": seg.startswith("zl")})
    inj = load_jsonl(os.path.join(out, "inject.jsonl"))
    cycles = []
    for i in inj:
        b = i["t_ms"]
        cs = [c for c in certs if c["load"] and f"-C{i['cycle']:04d}" in c["seg"]]
        if cs:
            cycles.append({"cycle": i["cycle"], "mult": i["mult"], "inject_ms": b,
                           "certify_all_s": round((max(c["end"] for c in cs) - b) / 1000, 1),
                           "busy_s": round(sum(c["dur_ms"] for c in cs) / 1000, 1), "segments": len(cs),
                           "max_segment_s": round(max(c["dur_ms"] for c in cs) / 1000, 1)})
    # backlog over time from the poller: count segments pending/certifying at each 1 s
    events = []
    for seg, s in st.items():
        a_ = s.get("pending", s.get("certifying"))
        b_ = s.get("certified")
        if a_ is not None:
            events.append((a_, b_))
    t0 = min((a_ for a_, _ in events), default=0)
    t1 = max((b_ or a_ for a_, b_ in events), default=0)
    backlog_peak, oldest_age_max = 0, 0
    for t in range(t0, t1 + 1, 1000):
        open_ = [a_ for a_, b_ in events if a_ <= t and (b_ is None or b_ > t)]
        backlog_peak = max(backlog_peak, len(open_))
        if open_:
            oldest_age_max = max(oldest_age_max, t - min(open_))
    # ---- correlation of every boundary with lateness >= 100 ms ----
    corr = []
    for sm, lat in lat_series:
        if lat < 100:
            continue
        w0, w1 = sm, sm + lat
        busy = [c["seg"] for c in certs if c["start"] <= w1 and c["end"] >= w0]
        thr = sum(s["thr_ms"] for s in per_s if w0 - 1000 <= s["t_ms"] <= w1 + 1000)
        gcs = [g for g in gc_events if w0 - 200 <= g[2] <= w1 + 200]
        lls = [e for e in ll_events if w0 - 200 <= e[0] <= w1 + 1200]
        rot = [c["seg"] for c in certs if not c["load"] and abs(c.get("start", 0) - sm) < 5000]
        cand = [x for x in life if x.get("_ts") and w0 - 15000 <= x["_ts"] <= w1 + 1000 and "candle" in json.dumps(x)[:200]]
        corr.append({"sample_ms": sm, "lateness_ms": lat, "certifying": busy[:6], "cg_throttled_ms_pm1s": round(thr),
                     "gc_ge20ms": gcs, "loop_lag_ge50": lls[:5], "own_rotation_certs": rot[:3], "candle_lifecycle": len(cand)})
    res = {
        "run": os.path.basename(run),
        "records": dict(records),
        "sampler": {"boundaries_with_records": len(lats), "first_ms": lat_series[0][0] if lat_series else None,
                    "last_ms": lat_series[-1][0] if lat_series else None, "lateness_ms": dist(lats),
                    "sampler_stall_gaps": len(stalls), "stall_examples": stalls[:5],
                    "collector_counter_ge": (last.get("ins") or {}).get("sampler_lateness_counts_ge"),
                    "collector_max_ms": (last.get("ins") or {}).get("sampler_lateness_max_ms")},
        "gaps_by_cause": dict(gaps_by_cause), "pit_recv_after_sample": pit_viol,
        "event_loop": {"loop_lag_max_ms": (last.get("ins") or {}).get("loop_lag_max_ms"),
                       "loop_lag_counts_ge": (last.get("ins") or {}).get("loop_lag_counts_ge"),
                       "ticks_ge50": len(ll_events), "top": sorted(ll_events, key=lambda e: -e[1])[:10]},
        "gc": {"collector_gc_pause_max_ms": (last.get("ins") or {}).get("gc_pause_max_ms"),
               "collector_gc_ge100": (last.get("ins") or {}).get("gc_pauses_ge_100ms"),
               "harness_count_by_gen": (last.get("gc") or {}).get("count"), "harness_total_ms": (last.get("gc") or {}).get("total_ms"),
               "harness_max_ms": (last.get("gc") or {}).get("max_ms"), "ge20_events": len(gc_events),
               "ge100": [g for g in gc_events if g[1] >= 100]},
        "writer": {"max_beat_gap_ms": ctr.get("writer_max_beat_gap_ms"), "max_durable_lag_ms": ctr.get("writer_max_durable_lag_ms"),
                   "queue_peak": (last or {}).get("q_peak"), "dropped": ctr.get("dropped"), "write_errors": ctr.get("write_errors"),
                   "duplicates_dropped": ctr.get("duplicates_dropped")},
        "certifier": {"certify_max_ms_collector": ctr.get("certify_max_ms"), "failures": ctr.get("certification_failures"),
                      "restarts": ctr.get("certifier_restarts"), "segments_finalized": ctr.get("segments_finalized"),
                      "certified_poller": len(certs), "load_certified": sum(1 for c in certs if c["load"]),
                      "own_certified": sum(1 for c in certs if not c["load"]),
                      "segment_dur_ms_load": dist([c["dur_ms"] for c in certs if c["load"]]),
                      "segment_dur_ms_own": dist([c["dur_ms"] for c in certs if not c["load"]]),
                      "per_cycle": cycles, "backlog_peak_segments": backlog_peak, "oldest_pending_age_max_ms": oldest_age_max,
                      "uncertified_at_end": [s for s, v in st.items() if "certified" not in v and "pending" in v][:10]},
        "cgroup": cgs,
        "stop": {k: stop.get(k) for k in ("state", "exit_code", "reason", "writer_finished", "writer_alive", "partials")},
        "health_states_1s": collections.Counter(t.get("health") for t in tel),
        "correlation_ge100ms": corr,
    }
    with open(os.path.join(out, "analysis.json"), "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    return res


if __name__ == "__main__":
    r = main(sys.argv[1])
    print(json.dumps({k: r[k] for k in ("sampler", "event_loop", "gc", "writer", "cgroup", "stop")}, indent=1, default=str)[:6000])
