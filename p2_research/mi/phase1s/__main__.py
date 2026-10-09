"""CLI (run as a module from the repository root: python3 -m <mi package>.phase1s): {run,finalize,project,plan-info,tree-hash} --out DIR ...

The sandbox is installed before the engine is imported. `pilot` and `full` additionally require: running inside
research-mi.slice, --expect-tree-sha256 equal to the running code tree, and --impl-commit. Nothing here opens,
reserves, charges or reads the MI CPU budget ledger or the MI trial ledger.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import sandbox as SB

MAX_WORKERS = 6     # research-mi.slice CPUQuota=600 %


def _args(argv):
    ap = argparse.ArgumentParser(prog="phase1s")
    ap.add_argument("command", choices=["run", "finalize", "project", "plan-info", "tree-hash"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=["offline-test", "pilot", "full"], default="offline-test")
    ap.add_argument("--tasks", default="T3,T2,T1,L2")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--chunk", type=int, default=None)
    ap.add_argument("--campaign", default="offline")
    ap.add_argument("--cpu-soft-cap-s", type=float, default=None)
    ap.add_argument("--expect-tree-sha256", default=None)
    ap.add_argument("--impl-commit", default=None)
    ap.add_argument("--test-protocol", default=None, help="offline-test only: scaled protocol JSON")
    ap.add_argument("--test-reps", default=None, help="offline-test only: JSON reps per kind")
    ap.add_argument("--budget-evidence", default=None, help="finalize: operator-produced budget evidence JSON")
    ap.add_argument("--available-cpu-s", type=float, default=None, help="project: owner-confirmed available budget")
    ap.add_argument("--allow-recompute-missing", action="store_true")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = _args(argv if argv is not None else sys.argv[1:])
    workers = a.workers if a.workers is not None else int(os.environ.get("RESEARCH_WORKERS", "1"))
    workers = max(1, min(MAX_WORKERS, workers))
    extra = [p for p in (a.test_protocol, a.budget_evidence) if p]
    if workers > 1 and a.command == "run":
        import multiprocessing.pool  # noqa: F401  (pre-imported: it loads subprocess / socket modules at import)
    os.makedirs(a.out, exist_ok=True)
    SB.install(a.out, extra_read=extra, allow_fork=(workers > 1 and a.command == "run"))
    from . import engine as EN
    from . import release as RL
    from ..derive import canon

    def emit(obj):
        sys.stdout.write(json.dumps(obj, sort_keys=True, indent=1) + "\n")

    protocol, cs, ps = RL.frozen_inputs()
    tree = RL.code_tree_sha256()
    if a.command == "tree-hash":
        emit({"code_tree_sha256": tree, "files": RL.tree_files(), "contract_set_sha256": cs, "protocol_sha256": ps})
        return 0
    if a.mode in ("pilot", "full"):
        if a.test_protocol or a.test_reps:
            raise SystemExit("test overrides are refused in pilot / full")
        if a.command == "run":
            SB.require_mi_slice()
            if a.expect_tree_sha256 != tree:
                raise SystemExit(f"CODE_TREE_MISMATCH: running {tree}, expected {a.expect_tree_sha256}")
            if not (a.impl_commit and RL.HEX40.match(a.impl_commit)):
                raise SystemExit("--impl-commit <40-hex> required")
    else:
        if not (a.test_protocol and a.test_reps):
            raise SystemExit("offline-test needs --test-protocol and --test-reps")
        with open(a.test_protocol, encoding="utf-8") as fh:
            protocol = json.load(fh)
        ps = EN.protocol_sha_of(protocol)
    if a.command == "plan-info":
        emit(plan_info(EN, protocol, cs, a.mode))
        return 0
    reps = EN.reps_for(a.mode, protocol, json.loads(a.test_reps) if a.test_reps else None)
    chunk = a.chunk or (5 if a.mode == "pilot" else 50)
    soft = a.cpu_soft_cap_s if a.cpu_soft_cap_s is not None else (1500.0 if a.mode == "pilot" else None)
    eng = EN.Engine(a.out, protocol, cs, ps, a.mode, reps, chunk=chunk, tree_sha=tree, workers=workers,
                    campaign=a.campaign, cpu_soft_cap_s=soft, allow_recompute_missing=a.allow_recompute_missing)
    eng.impl_commit = a.impl_commit
    eng.open()
    if a.command == "run":
        tasks = [t.strip() for t in a.tasks.split(",") if t.strip()]
        if not set(tasks) <= {"T1", "T2", "T3", "L2"}:
            raise SystemExit(f"unknown task in {tasks}")
        status = "DONE"
        try:
            steps = eng.run(tasks) if a.mode != "pilot" else eng.run(pilot_order(tasks))
        except EN.SoftCapStop as e:
            status, steps = f"SOFT_CAP_STOP ({e})", None
        SB.check()
        rep = eng.cpu_report()
        name = "pilot_report.json" if a.mode == "pilot" else "cpu_report.json"
        body = {"status": status, "final_steps": steps, "cpu": rep, "impl_commit": a.impl_commit,
                "code_tree_sha256": tree, "campaign": a.campaign}
        if a.mode == "pilot":
            body["projection"] = EN.project(rep, protocol, a.available_cpu_s)
            body["rerun"] = {"checked": sum(r["rerun"]["checked"] for r in eng.results.values()),
                             "mismatch": sum(r["rerun"]["mismatch"] for r in eng.results.values())}
        from . import store as ST
        ST.atomic_write(os.path.join(a.out, name), (json.dumps(body, sort_keys=True, indent=1) + "\n").encode())
        eng.journal.append("report_written", file=name, status=status)
        emit({"status": status, "final_steps": steps, "report": name})
        return 0 if status == "DONE" else 3
    if a.command == "finalize":
        ev = None
        if a.budget_evidence:
            with open(a.budget_evidence, encoding="utf-8") as fh:
                ev = json.load(fh)
        out = eng.assemble(ev)
        out["meta"]["impl_commit"] = a.impl_commit
        data = canon(out).encode()
        from . import store as ST
        ST.atomic_write(os.path.join(a.out, "output.json"), data)
        sha = ST.sha_bytes(data)
        ST.atomic_write(os.path.join(a.out, "output.sha256"), (sha + "  output.json\n").encode())
        eng.journal.append("finalized", output_sha256=sha, status=out["status"],
                           enforcement_verified=out["budget"]["enforcement_verified"])
        SB.check()
        emit({"output_sha256": sha, "status": out["status"], "final_step": out["final_step"],
              "enforcement_verified": out["budget"]["enforcement_verified"]})
        return 0
    if a.command == "project":
        emit(EN.project(eng.cpu_report(), protocol, a.available_cpu_s))
        return 0
    return 2


def pilot_order(tasks):
    return [t for t in ("T3", "T2", "T1", "L2") if t in tasks]


def plan_info(EN, protocol, cs, mode):
    from . import gen as G
    reps = EN.reps_for(mode, protocol) if mode != "offline-test" else None
    if reps is None:
        return {"error": "plan-info is for pilot / full"}
    seeds, n = set(), 0
    per = {}
    for c in protocol["cells"]:
        kinds = [("null", "-")] + [("skill", lv) for lv in protocol["skill_levels"]] + \
                [("miscal", v) for v in EN.miscal_variants(protocol)] + [("leak", "-")]
        if c["cell_id"] in protocol["l2"]["cells"]:
            kinds.append(("l2", "-"))
        for kind, lv in kinds:
            for r in range(reps[kind]):
                seeds.add(G.seed_hex(cs, c["cell_id"], kind, lv, r))
                n += 1
            per[f"{c['task']}|{kind}"] = per.get(f"{c['task']}|{kind}", 0) + reps[kind]
    null_grid = sum(reps["null"] for _ in protocol["cells"])
    return {"mode": mode, "reps_step0_total": n, "reps_per_task_kind": per, "seed_collisions": n - len(seeds),
            "extra_per_ladder_step_null_grid": null_grid, "worst_case_total": n + 2 * null_grid}


if __name__ == "__main__":
    sys.exit(main())
