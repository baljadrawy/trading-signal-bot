"""Phase 1S driver: plan -> ladder -> final classes -> L2 -> canonical output (derivation-map input schema).

Never imports the MI CPU guard, the budget ledger or the MI trial ledger. The budget block is filled only from a
separately produced, read-only budget-evidence file at finalize time; without it enforcement_verified is false and
derive() stops with BUDGET_NOT_ENFORCED (by design).
"""
from __future__ import annotations

import copy
import hashlib
import math
import os
import re
import resource
import time

from ..derive import canon, null_pass, wilson_upper

from . import IMPL_VERSION
from . import gen as G
from . import l2 as L2
from . import params as PR
from . import release as RL
from . import rules as RU
from . import store as ST

LEDGER_ID = "f5983b83c32c4278996ec642d385977a"     # permanent MI CPU budget ledger (identity check only, never read)
REQUIRED_ENFORCEMENT = "cgroup_cpu_budget_guard_v1"
TASKS = ("T1", "T2", "T3")
KINDS = ("null", "skill", "miscal", "leak", "l2")
RERUN_MOD = 50                                       # protocol: 2 % of reps re-executed, must be bit-identical
MODES = ("offline-test", "pilot", "full")


class EngineError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code = code


class SoftCapStop(EngineError):
    pass


# ============================================================================ protocol / reps
def protocol_sha_of(protocol: dict) -> str:
    return hashlib.sha256(canon(protocol).encode()).hexdigest()


def miscal_variants(protocol: dict) -> list:
    return list(protocol["meta_acceptance"]["b3_power_variants"]) + list(protocol["miscal_reported_variants"])


def reps_for(mode: str, protocol: dict, test_reps: dict = None) -> dict:
    if mode == "full":
        r = protocol["reps"]
        l2 = protocol["l2"]["reps_null_per_cell"]
        if l2 * len(protocol["l2"]["cells"]) != r["l2_null"]:
            raise EngineError("PROTOCOL_L2_REPS", f"{l2} x {len(protocol['l2']['cells'])} != {r['l2_null']}")
        return {"null": r["null"], "skill": r["skill"], "miscal": r["miscal"], "leak": r["leak"], "l2": l2}
    if mode == "pilot":
        n = int(protocol["budget"]["pilot"]["reps_per_cell"])
        return {k: n for k in KINDS}
    if mode == "offline-test":
        if not test_reps or set(test_reps) != set(KINDS):
            raise EngineError("TEST_REPS", f"offline-test needs reps for {KINDS}")
        if sum(test_reps.values()) > 200:
            raise EngineError("TEST_REPS", "offline-test reps are capped (bounded development runs only)")
        return dict(test_reps)
    raise EngineError("MODE", mode)


def plan_doc(mode, protocol, cs, ps, reps, chunk, tree_sha) -> dict:
    return {"record": "tsb.mi.phase1s_plan", "v": 1, "mode": mode, "contract_set_sha256": cs, "protocol_sha256": ps,
            "code_tree_sha256": tree_sha, "impl_version": IMPL_VERSION, "generator_version": PR.GENERATOR_VERSION, "gen_params": PR.GEN,
            "methods": PR.METHODS, "reps": reps, "chunk": chunk,
            "ladder": "pilot_step0_only" if mode == "pilot" else "frozen_ladder",
            "seed_scheme": "sha256(contract_set_sha256|cell_id|kind|level|rep[|extra])[:16]; extra = boot|<step> | "
                           "train | eval; null data identical across ladder steps (common random numbers)"}


# ============================================================================ units
def unit_key(u: dict) -> str:
    return f"{u['task']}/{u['kind']}/s{u['step']}/c{u['cidx']:02d}/{u['level']}/{u['r0']:05d}-{u['r1']:05d}"


_KEY_RE = re.compile(r"^(T1|T2|T3|L2)/(null|skill|miscal|leak|l2)/s([012])/c(\d\d)/([A-Za-z0-9_.+\-]+)/"
                     r"(\d{5})-(\d{5})$")


class Engine:
    def __init__(self, out_dir, protocol, cs, ps, mode, reps, chunk=50, tree_sha=None, workers=1,
                 campaign="offline", cpu_soft_cap_s=None, allow_recompute_missing=False, log=None):
        if mode not in MODES:
            raise EngineError("MODE", mode)
        from . import EXPECTED_CONTRACT_SET_SHA256, EXPECTED_PROTOCOL_SHA256
        if mode in ("pilot", "full"):
            frozen, fcs, fps = RL.frozen_inputs()
            if (cs, ps) != (EXPECTED_CONTRACT_SET_SHA256, EXPECTED_PROTOCOL_SHA256) or canon(protocol) != canon(frozen):
                raise EngineError("NOT_FROZEN_PROTOCOL", "pilot / full run only the frozen v1.0 protocol")
            if PR.GEN != PR.DEFAULT_GEN:
                raise EngineError("GEN_PARAMS_MUTATED", "generator parameters differ from the code-tree defaults")
        elif ps == EXPECTED_PROTOCOL_SHA256:
            raise EngineError("TEST_ON_FROZEN_HASH", "offline-test outputs must carry a test protocol hash")
        if mode == "offline-test" and "_test_days" in protocol:
            PR.GEN["days"] = int(protocol["_test_days"])
        self.out = os.path.abspath(out_dir)
        self.P, self.cs, self.ps, self.mode, self.reps = protocol, cs, ps, mode, reps
        self.chunk = int(chunk)
        self.tree = tree_sha or RL.code_tree_sha256()
        self.workers = max(1, int(workers))
        self.campaign = campaign
        self.soft_cap = cpu_soft_cap_s
        self.allow_recompute_missing = allow_recompute_missing
        self.log = log or (lambda *a: None)
        self.cells = {c["cell_id"]: c for c in protocol["cells"]}
        self.cidx = {c["cell_id"]: i for i, c in enumerate(protocol["cells"])}
        self.plan = plan_doc(mode, protocol, cs, ps, reps, self.chunk, self.tree)
        self.plan_sha = ST.sha_bytes(canon(self.plan).encode())
        self.results = {}          # key -> results
        self.cpu = {}              # key -> cpu section
        self.cpu_spent = 0.0       # worker CPU of shards computed in this process
        self.t0_cpu = time.process_time()
        self.journal = None
        self.impl_commit = None

    # ------------------------------------------------------------------ paths / open / reconcile
    def restore(self):
        """Undo an offline-test day scaling (tests run several engines in one process)."""
        PR.GEN["days"] = PR.DEFAULT_GEN["days"]

    def _path(self, key):
        return os.path.join(self.out, "shards", key + ".json")

    def open(self):
        os.makedirs(os.path.join(self.out, "shards"), exist_ok=True)
        pp = os.path.join(self.out, "plan.json")
        pb = canon(self.plan).encode()
        if os.path.exists(pp):
            with open(pp, "rb") as fh:
                if fh.read() != pb:
                    raise EngineError("PLAN_MISMATCH", "output dir belongs to a different plan / implementation")
        else:
            ST.atomic_write(pp, pb)
        self.journal = ST.Journal(os.path.join(self.out, "journal.jsonl"))
        self.journal.append("open", campaign=self.campaign, mode=self.mode, plan_sha256=self.plan_sha,
                            code_tree_sha256=self.tree, pid=os.getpid(), impl_commit=self.impl_commit)
        self._reconcile()
        return self

    def _unit_from_key(self, key):
        m = _KEY_RE.match(key)
        if not m:
            return None
        task, kind, step, ci, level, r0, r1 = m.groups()
        ci, r0, r1 = int(ci), int(r0), int(r1)
        if ci >= len(self.P["cells"]):
            return None
        cid = self.P["cells"][ci]["cell_id"]
        u = {"task": task, "kind": kind, "step": int(step), "cidx": ci, "cell_id": cid, "level": level,
             "r0": r0, "r1": r1}
        n = self.reps[kind]
        if r0 % self.chunk or r1 != min(r0 + self.chunk, n) or r0 >= n or unit_key(u) != key:
            return None
        return u

    def _seeds(self, u):
        return [G.seed_hex(self.cs, u["cell_id"], u["kind"], u["level"], r) for r in range(u["r0"], u["r1"])]

    def _reconcile(self):
        root = os.path.join(self.out, "shards")
        on_disk = {}
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, root)
                if f.endswith(".tmp"):
                    os.remove(full)
                    self.journal.append("tmp_discarded", path=rel)
                    continue
                if not f.endswith(".json"):
                    raise ST.StoreError("UNEXPECTED_FILE", rel)
                on_disk[rel[:-5]] = full
        committed = self.journal.committed()
        for key, fsha in sorted(committed.items()):
            u = self._unit_from_key(key)
            if u is None:
                raise ST.StoreError("JOURNAL_UNKNOWN_KEY", key)
            if key not in on_disk:
                if not self.allow_recompute_missing:
                    raise ST.StoreError("MISSING_SHARD", key)
                self.journal.append("shard_void", key=key, reason="missing", file_sha256=fsha)
                continue
            doc = ST.read_shard(on_disk[key], key, self.plan_sha, u, self._seeds(u))
            if doc["_file_sha256"] != fsha:
                raise ST.StoreError("SHARD_CHANGED", key)
            self.results[key], self.cpu[key] = doc["results"], doc["cpu"]
        for key in sorted(set(on_disk) - set(self.results)):
            if key in committed and self.allow_recompute_missing:
                continue
            u = self._unit_from_key(key)
            if u is None:
                raise ST.StoreError("UNEXPECTED_SHARD", key)
            doc = ST.read_shard(on_disk[key], key, self.plan_sha, u, self._seeds(u))
            self.journal.append("shard_adopted", key=key, file_sha256=doc["_file_sha256"], campaign=self.campaign)
            self.results[key], self.cpu[key] = doc["results"], doc["cpu"]

    # ------------------------------------------------------------------ unit lists
    def task_cells(self, task):
        return [c for c in self.P["cells"] if c["task"] == task]

    def _units(self, task_label, kind, step, cells, levels):
        out = []
        n = self.reps[kind]
        for c in cells:
            for lv in levels:
                for r0 in range(0, n, self.chunk):
                    out.append({"task": task_label, "kind": kind, "step": step, "cidx": self.cidx[c["cell_id"]],
                                "cell_id": c["cell_id"], "level": lv, "r0": r0, "r1": min(r0 + self.chunk, n)})
        return out

    def null_units(self, task, step):
        return self._units(task, "null", step, self.task_cells(task), ["-"])

    def final_units(self, task, step):
        cells = self.task_cells(task)
        return (self._units(task, "skill", step, cells, list(self.P["skill_levels"]))
                + self._units(task, "miscal", step, cells, miscal_variants(self.P))
                + self._units(task, "leak", step, cells, ["-"]))

    def l2_units(self, steps):
        out = []
        for cid in self.P["l2"]["cells"]:
            c = self.cells[cid]
            out += self._units("L2", "l2", steps[c["task"]], [c], ["-"])
        return out

    # ------------------------------------------------------------------ execution
    def ensure(self, units, compute=True):
        todo = [u for u in units if unit_key(u) not in self.results]
        if not todo:
            return
        if not compute:
            raise EngineError("INCOMPLETE", f"{len(todo)} shards missing, e.g. {unit_key(todo[0])}")
        _W.update(protocol=self.P, cs=self.cs, cells=self.cells)
        from . import sandbox as SB
        if self.workers == 1:
            it = map(compute_unit, todo)
            pool = None
        else:
            import multiprocessing as mp
            pool = mp.get_context("fork").Pool(self.workers)
            it = pool.imap_unordered(compute_unit, todo, chunksize=1)
        try:
            for res in it:
                self._commit(res)
                SB.check()
                if self.soft_cap is not None and self.cpu_used() >= self.soft_cap:
                    self.journal.append("soft_cap_stop", cpu_used=round(self.cpu_used(), 3), cap=self.soft_cap)
                    raise SoftCapStop("SOFT_CAP", f"{self.cpu_used():.1f} >= {self.soft_cap}")
        finally:
            if pool is not None:
                pool.terminate()
                pool.join()

    def cpu_used(self):
        return self.cpu_spent + (time.process_time() - self.t0_cpu)

    def _commit(self, res):
        u = res["unit"]
        key = unit_key(u)
        data = ST.shard_doc(key, self.plan_sha, u, res["results"], res["cpu"])
        ST.atomic_write(self._path(key), data)
        self.journal.append("shard_commit", key=key, file_sha256=ST.sha_bytes(data), campaign=self.campaign,
                            cpu_s=res["cpu"]["unit_s"], rerun_checked=res["results"]["rerun"]["checked"],
                            rerun_mismatch=res["results"]["rerun"]["mismatch"])
        self.results[key], self.cpu[key] = res["results"], res["cpu"]
        self.cpu_spent += res["cpu"]["unit_s"] + res["cpu"]["rerun_s"]
        if res["results"]["rerun"]["mismatch"]:
            self.journal.append("repro_mismatch", key=key)
            raise EngineError("REPRO_MISMATCH", key)

    # ------------------------------------------------------------------ aggregation
    def reps_of(self, units):
        out = []
        for u in units:
            out += self.results[unit_key(u)]["reps"]
        return out

    def null_agg(self, task, step):
        agg = {}
        for c in self.task_cells(task):
            rr = self.reps_of(self._units(task, "null", step, [c], ["-"]))
            agg[c["cell_id"]] = {"fp_k": sum(r[2] for r in rr), "n": len(rr), "b3_reject_k": sum(r[4] for r in rr),
                                 "_fp_alt_k": sum(r[3] for r in rr)}
        return agg

    def ladder(self, task, compute=True):
        """Frozen ladder. Returns (final_step, history). final_step = 2 when every step fails (FAIL)."""
        acc = self.P["meta_acceptance"]
        hist = []
        for st in self.P["ladder"]["steps"]:
            k = st["k"]
            self.ensure(self.null_units(task, k), compute)
            agg = self.null_agg(task, k)
            bad = [c["cell_id"] for c in self.task_cells(task) if not c["stress"]
                   and not null_pass(agg[c["cell_id"]], self.reps["null"], c["cell_id"], k, acc)]
            hist.append({"step": k, "pass": not bad, "failing_nonstress": bad})
            if not bad:
                return k, hist, True
        return 2, hist, False

    def run(self, tasks):
        """Execute the requested tasks in order (subset of T1, T2, T3, L2). Resumable and idempotent."""
        if self.mode == "pilot":
            self.ensure(self.pilot_units(tasks))
            self.journal.append("run_done", tasks=list(tasks), cpu_used=round(self.cpu_used(), 3))
            return {t: 0 for t in tasks if t in TASKS}
        steps = {}
        for t in tasks:
            if t == "L2":
                for need in {self.cells[c]["task"] for c in self.P["l2"]["cells"]}:
                    if need not in steps:
                        steps[need] = self._final_step(need, compute=False)
                self.ensure(self.l2_units(steps))
                continue
            steps[t], hist, ok = self.ladder(t)
            self.journal.append("ladder", task=t, final_step=steps[t], passed=ok, history=hist)
            self.ensure(self.final_units(t, steps[t]))
        self.journal.append("run_done", tasks=list(tasks), cpu_used=round(self.cpu_used(), 3))
        return steps

    def pilot_units(self, tasks):
        """Pilot (step 0 only), stratified: every chunk-0 unit of every task|kind precedes any chunk-1 unit, so a
        soft-cap stop still leaves a measurement in every cost stratum."""
        units = []
        for t in TASKS:
            if t in tasks:
                units += self.null_units(t, 0) + self.final_units(t, 0)
        if "L2" in tasks:
            units += self.l2_units({t: 0 for t in TASKS})
        order = {k: i for i, k in enumerate(KINDS)}
        return sorted(units, key=lambda u: (u["r0"], order[u["kind"]], u["task"], u["cidx"], u["level"]))

    def _final_step(self, task, compute):
        if self.mode == "pilot":
            return 0
        return self.ladder(task, compute)[0]

    # ------------------------------------------------------------------ output
    def assemble(self, budget_evidence=None) -> dict:
        """Canonical tsb.mi.phase1s_output v1 (derivation-map input schema) + meta + diagnostics. No compute."""
        if self.mode == "pilot":
            raise EngineError("PILOT_NOT_DERIVABLE", "pilot output is a cost report, never a derive() input")
        acc = self.P["meta_acceptance"]
        cells_out, diag, final_step, ladder_hist = {}, {"cells": {}, "tasks": {}}, {}, {}
        for task in TASKS:
            k, hist, ok = self.ladder(task, compute=False)
            final_step[task], ladder_hist[task] = k, {"history": hist, "passed": ok}
            self.ensure(self.final_units(task, k), compute=False)
        for task in TASKS:
            ceiling = None
            for c in self.task_cells(task):
                if c["stress"]:
                    continue
                for lv in self.P["skill_levels"]:
                    rr = self.reps_of(self._units(task, "skill", final_step[task], [c], [lv]))
                    mx = max(r[4] for r in rr)
                    ceiling = mx if ceiling is None else max(ceiling, mx)
            diag["tasks"][task] = {"trip_wire_ceiling_bss": ceiling, "ladder": ladder_hist[task]}
            for c in self.task_cells(task):
                cid = c["cell_id"]
                co = {"null": {}, "skill": {}, "miscal": {}, "leak": {}}
                dg = {"null_fp_alt_k": {}, "skill_pass_alt_k": {}, "skill_mean_bss": {}, "null_wilson_ub": {}}
                for st in self.P["ladder"]["steps"]:
                    s = st["k"]
                    if s > final_step[task]:
                        break
                    a = self.null_agg(task, s)[cid]
                    co["null"][str(s)] = {"fp_k": a["fp_k"], "n": a["n"], "b3_reject_k": a["b3_reject_k"]}
                    dg["null_fp_alt_k"][str(s)] = a["_fp_alt_k"]
                    dg["null_wilson_ub"][str(s)] = wilson_upper(a["fp_k"], a["n"])
                fs = final_step[task]
                for lv in self.P["skill_levels"]:
                    rr = self.reps_of(self._units(task, "skill", fs, [c], [lv]))
                    co["skill"][lv] = {"pass_k": sum(r[2] for r in rr), "n": len(rr), "max_bss": max(r[4] for r in rr)}
                    dg["skill_pass_alt_k"][lv] = sum(r[3] for r in rr)
                    dg["skill_mean_bss"][lv] = sum(r[4] for r in rr) / len(rr)
                for v in miscal_variants(self.P):
                    rr = self.reps_of(self._units(task, "miscal", fs, [c], [v]))
                    co["miscal"][v] = {"reject_k": sum(r[2] for r in rr), "n": len(rr)}
                rr = self.reps_of(self._units(task, "leak", fs, [c], ["-"]))
                co["leak"] = {"fire_k": fire_count([r[2] for r in rr], ceiling), "n": len(rr)}
                dg["leak_min_bss"] = min(r[2] for r in rr)
                cells_out[cid], diag["cells"][cid] = co, dg
        self.ensure(self.l2_units(final_step), compute=False)
        rr = self.reps_of(self.l2_units(final_step))
        l2 = {"null_fp_k": sum(r[2] for r in rr), "n": len(rr)}
        diag["l2"] = {"null_fp_alt_k": sum(r[3] for r in rr), "nonconverged": sum(1 - r[4] for r in rr),
                      "steps": {cid: final_step[self.cells[cid]["task"]] for cid in self.P["l2"]["cells"]}}
        used = sorted(k for k in self.results if self._in_final_plan(k, final_step))
        rerun_checked = sum(self.results[k]["rerun"]["checked"] for k in used)
        rerun_mm = sum(self.results[k]["rerun"]["mismatch"] for k in used)
        seeds = hashlib.sha256()
        for k in used:
            for r in self.results[k]["reps"]:
                seeds.update(f"{k}:{r[0]}:{r[1]}\n".encode())
        res_digest = hashlib.sha256("".join(f"{k}\t{ST.results_sha(self.results[k])}\n" for k in used).encode())
        budget, bnote = budget_block(self.mode, budget_evidence, self.journal.campaigns() if self.journal else set())
        complete = rerun_mm == 0
        out = {"record": "tsb.mi.phase1s_output", "record_version": 1,
               "status": "COMPLETE" if complete else "INCOMPLETE",
               "contract_set_sha256": self.cs, "protocol_sha256": self.ps, "budget": budget,
               "final_step": final_step, "l2": l2, "cells": cells_out,
               "meta": {"mode": self.mode, "impl_version": IMPL_VERSION, "generator_version": PR.GENERATOR_VERSION,
                        "code_tree_sha256": self.tree, "plan_sha256": self.plan_sha, "reps": self.reps,
                        "methods": PR.METHODS, "gen_params": PR.GEN, "seed_scheme": self.plan["seed_scheme"],
                        "seeds_sha256": seeds.hexdigest(), "results_sha256": res_digest.hexdigest(),
                        "shards": len(used), "rerun": {"checked": rerun_checked, "mismatch": rerun_mm},
                        "budget_note": bnote, "acceptance": acc},
               "diagnostics": diag}
        return out

    def _in_final_plan(self, key, final_step):
        u = self._unit_from_key(key)
        if u is None:
            return False
        if u["kind"] == "null":
            return u["step"] <= final_step[u["task"]]
        if u["kind"] == "l2":
            return u["step"] == final_step[self.cells[u["cell_id"]]["task"]]
        return u["step"] == final_step[u["task"]]

    # ------------------------------------------------------------------ CPU report (non-deterministic; never hashed)
    def cpu_report(self) -> dict:
        strata, cells = {}, {}
        rerun = 0.0
        for key, cpu in self.cpu.items():
            u = self._unit_from_key(key)
            task = self.cells[u["cell_id"]]["task"]
            sk = f"{task}|{u['kind']}"
            strata.setdefault(sk, []).extend(cpu["per_rep"])
            cells.setdefault(f"{u['cell_id']}|{u['kind']}|{u['level']}", []).extend(cpu["per_rep"])
            rerun += cpu["rerun_s"]
        ru_s, ru_c = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
        return {"record": "tsb.mi.phase1s_cpu_report", "v": 1, "mode": self.mode, "plan_sha256": self.plan_sha,
                "per_task_kind": {k: _desc(v) for k, v in sorted(strata.items())},
                "per_case": {k: _desc(v) for k, v in sorted(cells.items())},
                "rerun_cpu_s": rerun,
                "process": {"self_user_s": ru_s.ru_utime, "self_sys_s": ru_s.ru_stime,
                            "children_user_s": ru_c.ru_utime, "children_sys_s": ru_c.ru_stime,
                            "parent_cpu_s": time.process_time()},
                "note": "in-process attribution only; the authoritative charge is the cgroup usage measured by the "
                        "MI CPU guard"}


def fire_count(bss: list, ceiling) -> int:
    """A7 trip-wire canary (OD-4): fires when the realised BSS is strictly above the task ceiling."""
    return sum(1 for b in bss if ceiling is not None and b > ceiling)


def _desc(v):
    n = len(v)
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "sum": sum(v), "mean": m, "sd": sd, "max": max(v)}


# ============================================================================ budget block
def budget_block(mode, evidence, campaigns_used):
    cap = 28800
    if mode == "offline-test" or evidence is None:
        enf = "none_offline_test" if mode == "offline-test" else REQUIRED_ENFORCEMENT
        return ({"enforcement": enf, "enforcement_verified": False, "cap_cpu_s": cap, "cumulative_cpu_s": None,
                 "breach": False}, "no budget evidence: enforcement NOT verified (derive stops BUDGET_NOT_ENFORCED)")
    ok, why = validate_evidence(evidence, campaigns_used)
    cum = evidence.get("ledger_cumulative_charged_cpu_s")
    return ({"enforcement": REQUIRED_ENFORCEMENT, "enforcement_verified": ok, "cap_cpu_s": cap,
             "cumulative_cpu_s": cum if isinstance(cum, (int, float)) else None,
             "breach": not (isinstance(cum, (int, float)) and cum <= cap)}, why)


def validate_evidence(ev, campaigns_used):
    """Structural check of an operator-produced budget-evidence record (it never reads the live ledger)."""
    if not isinstance(ev, dict) or ev.get("record") != "tsb.mi.budget_evidence" or ev.get("v") != 1:
        return False, "evidence: wrong record"
    if ev.get("ledger_id") != LEDGER_ID or ev.get("cap_cpu_s") != 28800:
        return False, "evidence: ledger identity / cap mismatch"
    if ev.get("open_reservations") != 0:
        return False, "evidence: open reservations remain"
    camps = ev.get("campaigns")
    if not isinstance(camps, list) or not camps:
        return False, "evidence: no campaigns"
    names = set()
    for c in camps:
        if c.get("state") != "DONE" or c.get("measured") is not True or not isinstance(c.get("charged_cpu_s"),
                                                                                       (int, float)):
            return False, f"evidence: campaign {c.get('campaign')} not DONE with a measured charge"
        names.add(c.get("campaign"))
    missing = set(campaigns_used) - names
    if missing:
        return False, f"evidence: shards computed under campaigns without evidence: {sorted(missing)}"
    if not RL.HEX64.match(str(ev.get("ledger_head_sha256", ""))):
        return False, "evidence: ledger head missing"
    return True, "evidence verified structurally (owner review of the sealed evidence still required)"


# ============================================================================ worker
_W = {}


def _one(u, cell, rep):
    P, cs = _W["protocol"], _W["cs"]
    cid, kind, lvl, step = u["cell_id"], u["kind"], u["level"], u["step"]
    sh = G.seed_hex(cs, cid, kind, lvl, rep)
    rng = G.rng_from(sh)
    if kind == "null":
        r = RU.run_null(cell, P, rng, G.rng_from(G.seed_hex(cs, cid, kind, lvl, rep, f"boot|{step}")), step)
        return [rep, sh, r["fp"], r["fp_alt"], r["b3_reject"], r["p"][0], r["p"][1]]
    if kind == "skill":
        r = RU.run_skill(cell, P, rng, G.rng_from(G.seed_hex(cs, cid, kind, lvl, rep, f"boot|{step}")), step, lvl)
        return [rep, sh, r["pass"], r["pass_alt"], r["bss"], r["p"]]
    if kind == "miscal":
        return [rep, sh, RU.run_miscal(cell, P, rng, lvl, step)["reject"]]
    if kind == "leak":
        return [rep, sh, RU.run_leak(cell, P, rng)["bss"]]
    if kind == "l2":
        r = L2.run_l2(cell, P, G.rng_from(G.seed_hex(cs, cid, kind, lvl, rep, "train")),
                      G.rng_from(G.seed_hex(cs, cid, kind, lvl, rep, "eval")),
                      G.rng_from(G.seed_hex(cs, cid, kind, lvl, rep, f"boot|{step}")), step)
        return [rep, sh, r["fp"], r["fp_alt"], r["converged"]]
    raise EngineError("KIND", kind)


def compute_unit(u):
    cell = _W["cells"][u["cell_id"]]
    reps, cpu = [], []
    for rep in range(u["r0"], u["r1"]):
        t0 = time.process_time()
        reps.append(_one(u, cell, rep))
        cpu.append(round(time.process_time() - t0, 6))
    checked = mism = 0
    t0 = time.process_time()
    for rec in reps:
        if int(rec[1], 16) % RERUN_MOD == 0:
            checked += 1
            if _one(u, cell, rec[0]) != rec:
                mism += 1
    rerun_s = round(time.process_time() - t0, 6)
    return {"unit": u, "results": {"reps": reps, "rerun": {"checked": checked, "mismatch": mism}},
            "cpu": {"per_rep": cpu, "unit_s": round(sum(cpu), 6), "rerun_s": rerun_s}}


# ============================================================================ pilot projection
def planned_full_reps(protocol) -> dict:
    """Step-0 planned reps per task|kind of the frozen full run (+ one extra null grid = the protocol reserve)."""
    r = protocol["reps"]
    nv = len(miscal_variants(protocol))
    out = {}
    for t in TASKS:
        nc = sum(1 for c in protocol["cells"] if c["task"] == t)
        out[f"{t}|null"] = nc * r["null"]
        out[f"{t}|skill"] = nc * len(protocol["skill_levels"]) * r["skill"]
        out[f"{t}|miscal"] = nc * nv * r["miscal"]
        out[f"{t}|leak"] = nc * r["leak"]
    per = protocol["l2"]["reps_null_per_cell"]
    for cid in protocol["l2"]["cells"]:
        t = next(c["task"] for c in protocol["cells"] if c["cell_id"] == cid)
        out[f"{t}|l2"] = out.get(f"{t}|l2", 0) + per
    return out


def project(cpu_report: dict, protocol: dict, available_cpu_s=None) -> dict:
    """Protocol projection P = sum(cpu/rep x planned) x 1.25 + one full null-grid re-run reserve (x 1.02 re-run
    check). Reports point and an upper estimate (per-stratum mean + 1.96 SE); both are pilot-sample estimates."""
    plan = planned_full_reps(protocol)
    st = cpu_report["per_task_kind"]
    missing = sorted(k for k in plan if k not in st)
    if missing:
        return {"verdict": "INCOMPLETE_PILOT", "missing_strata": missing}
    rerun = 1.0 + 1.0 / RERUN_MOD
    rows, P_pt, P_up, res_pt, res_up = {}, 0.0, 0.0, 0.0, 0.0
    for k, n in sorted(plan.items()):
        d = st[k]
        se = d["sd"] / math.sqrt(d["n"]) if d["n"] > 1 else d["mean"]
        pt, up = d["mean"] * n * rerun, (d["mean"] + 1.96 * se) * n * rerun
        rows[k] = {"planned_reps": n, "cpu_per_rep_mean": d["mean"], "cpu_per_rep_se": se, "pilot_n": d["n"],
                   "cpu_point": pt, "cpu_upper": up}
        P_pt += pt
        P_up += up
        if k.endswith("|null"):
            res_pt += pt
            res_up += up
    proj = {"per_stratum": rows, "base_point": P_pt, "base_upper": P_up,
            "P_point": P_pt * 1.25 + res_pt, "P_upper": P_up * 1.25 + res_up,
            "worst_case_two_extra_steps_point": P_pt * 1.25 + 2 * res_pt,
            "worst_case_two_extra_steps_upper": P_up * 1.25 + 2 * res_up,
            "formula": protocol["budget"]["pilot"]["projection"]}
    if available_cpu_s is not None:
        proj["available_cpu_s"] = available_cpu_s
        proj["verdict"] = ("FITS" if proj["P_upper"] <= available_cpu_s else
                           ("FITS_POINT_ONLY" if proj["P_point"] <= available_cpu_s else "EXCEEDS_STOP_TO_OWNER"))
    else:
        proj["verdict"] = "NEEDS_AVAILABLE_BUDGET"
    return proj


def copy_protocol(protocol):
    return copy.deepcopy(protocol)
