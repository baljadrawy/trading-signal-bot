"""Analyse the bounded v8 live validation: strict v8 classification of (a) the clean period and (b) each injected
negative control. Expected: (a) ok with real HEALTHCHECK stages recognised; (b) every injection detected."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "verifier"))
import verify_independent as VI
out = sys.argv[1]; tsv = sys.argv[2] if len(sys.argv) > 2 else "V8_cgroup.tsv"; inj_len = int(sys.argv[3]) if len(sys.argv) > 3 else 25_000
c = VI.read_cgroup(os.path.join(out, tsv))
hl = VI.read_healthcheck(os.path.join(out, "V8_healthcheck_log.jsonl"), os.path.join(out, "V8_healthcheck_config.json"))
run = json.load(open(os.path.join(out, "run.json")))
inj = [json.loads(l) for l in open(os.path.join(out, "injections.jsonl"))]
rows = [r for r in c["rows"] if "detail" in r]
samples = [{"t_ms": r["t_ms"], "procs": r["detail"]["procs"], "escaped": r["detail"]["escaped"]} for r in rows]
aux = [dict(o, src="follow") for r in rows for o in r["detail"].get("follow") or []]
cid = rows[0]["detail"]["cid"]
spec_cg = dict(VI.G3_SPEC["cgroup"], _scope_cgroup=f"docker-{cid}.scope", _cid=cid)
hcspec = VI.G3_SPEC["cgroup"]["process_roles"]["container_healthcheck"]
res = {"samples": len(samples), "has_detail": c["has_detail"], "max_interval_s": c["max_interval_s"], "cpu_max": c["cpu_max"],
       "memory_max": c["memory_max"], "pids_max": c["pids_max"], "healthcheck_config_matches_pin": hl["config"] == hcspec["docker_healthcheck"],
       "docker_runs": len(hl["runs"]), "docker_run_exit_codes": sorted({r[2] for r in hl["runs"]}), "cover": hl["cover"]}
t_start = run["container_start_ms"]; first_inj = min(i["t_ms"] for i in inj); last_inj = max(i["t_ms"] for i in inj)
segs = [("clean_before_injections", t_start + 150_000, first_inj - 1_000)] + \
       [(i["name"], i["t_ms"] - 500, i["t_ms"] + inj_len) for i in inj] + [("clean_after_injections", last_inj + 60_000, max(s["t_ms"] for s in samples))]
procs = {}
for s in samples + aux:
    for o in (s.get("procs") or [s]):
        if "pid" in o and o.get("cmdline"):
            procs.setdefault(int(o["pid"]), o["cmdline"][:90])
for name, lo, hi in segs:
    r = VI.classify_processes(samples, spec_cg, (lo, hi), hl["runs"], hl["cover"], aux, mode="strict")
    res[name] = {"window": [lo, hi], "ok": r["ok"], "role_samples": dict(r["role_samples"]), "hc_tiers": dict(r["tiers"]),
                 "unexpected": [[t, p, why, procs.get(p)] for t, p, why in r["unexpected"]][:6],
                 "unresolved": [[t, p, why, procs.get(p)] for t, p, why in r["unresolved"]][:6],
                 "role_failures": r["per_sample_failures"][:3]}
full = VI.classify_processes(samples, spec_cg, (t_start + 150_000, max(s["t_ms"] for s in samples)), hl["runs"], hl["cover"], aux, mode="strict")
stages = {}
for p, v in full["pid_verdicts"].items():
    if v[0] == "hc":
        stages[procs.get(p, "<no command recorded>")[:40]] = stages.get(procs.get(p, "<no command recorded>")[:40], 0) + 1
res["whole_run_hc_tiers"] = dict(full["tiers"]); res["whole_run_hc_stage_kinds"] = stages
res["whole_run_unexpected_reasons"] = sorted({u[2][:40] for u in full["unexpected"]})
json.dump(res, open(os.path.join(out, "analysis_v8_" + tsv.split("_")[0] + ".json"), "w"), indent=1)
for k, v in res.items():
    print(k, json.dumps(v)[:600])
