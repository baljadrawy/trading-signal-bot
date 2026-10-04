"""DIAGNOSTIC replay (read-only) of the v8 process-role classifier over the PRESERVED G3-v7 evidence.
Sources: G3_cgroup.tsv (monitor, 5 s, pids), observer/threads.jsonl (250 ms, process names), observer/
cgroup_identity.jsonl (30 s, command lines), healthcheck_evidence/other_processes.jsonl (100 ms from 00:28Z: command,
ppid, exe, cgroup, parent command), healthcheck_evidence/docker_health_log.jsonl (Docker's own runs from 00:25Z).
Never alters the historical v7 result."""
import collections, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "verifier"))
import verify_independent as VI

def main(ev, out):
    r7 = json.load(open(os.path.join(ev, "31_g3_verify_independent.json")))
    ws, stop = r7["window"]["ws_start_ms"], r7["window"]["stop_requested_ms"]
    window = (ws + 1000 * VI.G3_SPEC["health"]["startup_s"], stop)
    samples = []
    for line in list(open(os.path.join(ev, "G3_cgroup.tsv")))[1:]:
        c = line.rstrip("\n").split("\t")
        if len(c) >= 8:
            samples.append({"t_ms": int(c[0]) // 1_000_000, "procs": [{"pid": int(p.split("=")[0])} for p in c[7].split(",") if "=" in p], "escaped": []})
    aux = []
    for line in open(os.path.join(ev, "observer", "threads.jsonl")):
        d = json.loads(line)
        for k, (comm, _) in d["p"].items():
            pid, tid = k.split("/")
            if pid == tid:
                aux.append({"t_ms": d["t_ms"], "pid": int(pid), "comm": comm, "src": "threads"})
    for line in open(os.path.join(ev, "observer", "cgroup_identity.jsonl")):
        d = json.loads(line)
        for p in d["procs"]:
            ns = str(p.get("ns_pid") or "").split()
            aux.append({"t_ms": d["t_ms"], "pid": p["host_pid"], "cmdline": p["cmdline"], "cgroup": p["cgroup"],
                        "nspid": int(ns[-1]) if ns else None, "src": "identity"})
    for line in open(os.path.join(ev, "healthcheck_evidence", "other_processes.jsonl")):
        x = json.loads(line)
        for t in (x["first_seen_ms"], x["last_seen_ms"]):
            aux.append({"t_ms": t, "pid": x["pid"], "ppid": x["ppid"], "cmdline": x["cmdline"], "cgroup": x["cgroup"],
                        "parent_cmdline": x["parent_cmdline"], "src": "hc_tracker"})
    runs = []
    for line in open(os.path.join(ev, "healthcheck_evidence", "docker_health_log.jsonl")):
        e = json.loads(line); runs.append((VI._iso_ms(e["Start"]), VI._iso_ms(e["End"]), e["ExitCode"]))
    runs.sort()
    cover = [(runs[0][0], runs[-1][1] + 30_000)] if runs else []
    cid = [l for l in open(os.path.join(ev, "observer", "cgroup_identity.jsonl"))][0]
    cid = json.loads(cid)["cgroup_dir"].split("docker-")[1].split(".scope")[0]
    spec_cg = dict(VI.G3_SPEC["cgroup"], _scope_cgroup=f"docker-{cid}.scope", _cid=cid)
    rep = {"window": window, "samples_total": len(samples), "samples_in_window": sum(1 for s in samples if window[0] <= s["t_ms"] <= window[1]),
           "health_log_runs": len(runs), "health_log_cover": cover}
    for mode in ("strict", "historical"):
        res = VI.classify_processes(samples, spec_cg, window, runs, cover, aux, mode=mode)
        other_entries = sum(1 for s in samples if window[0] <= s["t_ms"] <= window[1] for o in s["procs"]
                            if res["pid_verdicts"].get(o["pid"], ("",))[0] != "role")
        rep[mode] = {"ok": res["ok"], "role_samples": dict(res["role_samples"]), "hc_tiers": dict(res["tiers"]),
                     "non_role_entries_in_window": other_entries, "unexpected": res["unexpected"], "unresolved": res["unresolved"],
                     "unexpected_pids": res["unexpected_pids"], "unresolved_pids": res["unresolved_pids"],
                     "per_sample_failures": res["per_sample_failures"][:10], "collector_pid": res["collector_pid"],
                     "instances": res["instances"]}
        if mode == "historical":
            seen_only = {p: v for p, v in res["pid_verdicts"].items() if v[0] != "role"
                         and p not in {o["pid"] for s in samples for o in s["procs"]}}
            rep["observer_only_processes"] = dict(collections.Counter(v[0] + ":" + v[1] for v in seen_only.values()))
            rep["observer_only_unexpected"] = {p: v for p, v in seen_only.items() if v[0] != "hc"}
    json.dump(rep, open(out, "w"), indent=1, default=str)
    return rep

if __name__ == "__main__":
    r = main(sys.argv[1], sys.argv[2])
    for m in ("strict", "historical"):
        x = r[m]; print(m, "ok", x["ok"], "roles", x["role_samples"], "tiers", x["hc_tiers"], "non-role entries", x["non_role_entries_in_window"],
                        "unexpected", len(x["unexpected"]), "unresolved", len(x["unresolved"]), "per-sample failures", len(x["per_sample_failures"]))
    print("samples", r["samples_total"], "in window", r["samples_in_window"], "health runs", r["health_log_runs"], "cover", r["health_log_cover"])
    print("observer-only processes:", r["observer_only_processes"]); print("observer-only unexpected/unresolved:", r["observer_only_unexpected"])
