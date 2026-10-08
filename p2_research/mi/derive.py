"""MI-ML derivation map v1.0 -> v1.1 (contract MI-C v1.0, decision package K5). Pure function, stdlib only.

Input: one sealed Phase 1S output (canonical JSON bytes + its expected SHA-256) and the frozen v1.0 protocol.
Output: the calibration-dependent parameters (CDP) of MI-C v1.1, or a DerivationStop (fail closed, back to the owner).

UNRESOLVED (missing / incomplete / non-finite / hash or protocol mismatch / budget not enforced or breached / a gate
outside the ladder fails) -> DerivationStop. Resolved-infeasible (e.g. power never reaches 0.80) -> deterministic
DESCRIPTIVE_ONLY / INSUFFICIENT flags. Rational comparisons use exact integer arithmetic; the Wilson bound uses IEEE-754
double with a conservative tie rule (|UB - limit| <= 1e-12 counts as a failure).
"""
from __future__ import annotations

import hashlib
import json
import math

MAP_VERSION = "mi-derivation-map-1.0.0"
Z = 1.959963984540054
TIE = 1e-12
FAIL = "FAIL"


class DerivationStop(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code = code


def canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def wilson_upper(k: int, n: int) -> float:
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return min(1.0, c + h)


def _int(x, what):
    if not isinstance(x, int) or isinstance(x, bool) or x < 0:
        raise DerivationStop("UNRESOLVED_FIELD", what)
    return x


def _num(x, what):
    if not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x):
        raise DerivationStop("UNRESOLVED_FIELD", what)
    return float(x)


def null_pass(rec: dict, planned_n: int, cid: str, step: int, acc: dict) -> bool:
    k, n = _int(rec.get("fp_k"), f"{cid}.null.{step}.fp_k"), _int(rec.get("n"), f"{cid}.null.{step}.n")
    if n != planned_n or k > n:
        raise DerivationStop("INCOMPLETE_REPS", f"{cid} null step {step}: n={n} planned {planned_n}")
    point_ok = k * acc["null_fpr_point_den"] <= n * acc["null_fpr_point_num"]          # k/n <= 5/100
    ub_ok = wilson_upper(k, n) <= acc["null_fpr_wilson_ub_max"] - TIE
    return point_ok and ub_ok


def derive(output_bytes: bytes, expected_sha256: str, protocol: dict, contract_set_sha256: str,
           protocol_sha256: str) -> dict:
    try:
        return _derive(output_bytes, expected_sha256, protocol, contract_set_sha256, protocol_sha256)
    except DerivationStop:
        raise
    except (KeyError, TypeError, AttributeError, IndexError, ValueError, ZeroDivisionError) as e:
        raise DerivationStop("UNRESOLVED_FIELD", f"{type(e).__name__}: {e}")


def _derive(output_bytes: bytes, expected_sha256: str, protocol: dict, contract_set_sha256: str,
            protocol_sha256: str) -> dict:
    # ---------------------------------------------------------- preconditions (fail closed)
    if hashlib.sha256(output_bytes).hexdigest() != expected_sha256:
        raise DerivationStop("HASH_MISMATCH")
    try:
        out = json.loads(output_bytes)
    except Exception as e:
        raise DerivationStop("UNPARSEABLE", str(e))
    if out.get("record") != "tsb.mi.phase1s_output" or out.get("record_version") != 1:
        raise DerivationStop("WRONG_RECORD")
    if out.get("status") != "COMPLETE":
        raise DerivationStop("INCOMPLETE_STATUS", str(out.get("status")))
    if out.get("contract_set_sha256") != contract_set_sha256 or out.get("protocol_sha256") != protocol_sha256:
        raise DerivationStop("PROTOCOL_MISMATCH")
    bud, req = out.get("budget") or {}, protocol["budget"]
    if bud.get("enforcement") != req["required_enforcement"] or bud.get("enforcement_verified") is not True:
        raise DerivationStop("BUDGET_NOT_ENFORCED")
    cum = _num(bud.get("cumulative_cpu_s"), "budget.cumulative_cpu_s")
    if bud.get("breach") is not False or cum > req["cap_cpu_s"] or bud.get("cap_cpu_s") != req["cap_cpu_s"]:
        raise DerivationStop("BUDGET_BREACH")
    acc, reps = protocol["meta_acceptance"], protocol["reps"]
    cells_out = out.get("cells")
    if not isinstance(cells_out, dict):
        raise DerivationStop("UNRESOLVED_FIELD", "cells")
    planned = {c["cell_id"]: c for c in protocol["cells"]}
    if set(cells_out) != set(planned):
        raise DerivationStop("INCOMPLETE_GRID", f"missing {sorted(set(planned) - set(cells_out))[:3]} "
                                                f"extra {sorted(set(cells_out) - set(planned))[:3]}")
    l2 = out.get("l2") or {}
    lk, ln = _int(l2.get("null_fp_k"), "l2.null_fp_k"), _int(l2.get("n"), "l2.n")
    if ln != reps["l2_null"] or lk > ln:
        raise DerivationStop("INCOMPLETE_REPS", "l2")
    if lk * 1000 > ln * acc["l2_null_fpr_point_max_permille"]:
        raise DerivationStop("L2_MODEL_FIT_INFLATION", f"{lk}/{ln}")

    res = {"record": "tsb.mi.contract_v1_1_cdp", "map_version": MAP_VERSION, "input_sha256": expected_sha256,
           "contract_set_sha256": contract_set_sha256, "tasks": {}}
    final_steps = out.get("final_step") or {}
    for task in ("T1", "T2", "T3"):
        tcells = [c for c in protocol["cells"] if c["task"] == task]
        nonstress = [c for c in tcells if not c["stress"]]
        # ------------------------------------------------------ ladder step (whole grid re-run per step)
        k_task = FAIL
        for step in protocol["ladder"]["steps"]:
            s = str(step["k"])
            for c in tcells:
                if s not in (cells_out[c["cell_id"]].get("null") or {}):
                    raise DerivationStop("UNRESOLVED_LADDER", f"{task} step {s} missing for {c['cell_id']}")
            if all(null_pass(cells_out[c["cell_id"]]["null"][s], reps["null"], c["cell_id"], step["k"], acc)
                   for c in nonstress):
                k_task = step["k"]
                break
            # all cells must still be well-formed at this step
            for c in tcells:
                null_pass(cells_out[c["cell_id"]]["null"][s], reps["null"], c["cell_id"], step["k"], acc)
        run_step = 2 if k_task == FAIL else k_task
        if final_steps.get(task) != run_step:
            raise DerivationStop("FINAL_STEP_MISMATCH", f"{task}: output {final_steps.get(task)} derived {run_step}")
        rs = str(run_step)
        lad = protocol["ladder"]["steps"][run_step]
        t = {"ladder_step": k_task, "block_mean_days": protocol["ladder"]["block_mean_days"][task] * lad["block_factor"],
             "alpha": lad["alpha"], "status": "INFERENTIAL"}
        # ------------------------------------------------------ gates outside the ladder -> STOP
        for c in tcells:
            co = cells_out[c["cell_id"]]
            leak = co.get("leak") or {}
            fk, fn = _int(leak.get("fire_k"), f"{c['cell_id']}.leak"), _int(leak.get("n"), f"{c['cell_id']}.leak.n")
            if fn != reps["leak"] or fk > fn:
                raise DerivationStop("INCOMPLETE_REPS", f"{c['cell_id']} leak")
            if fk * 100 < fn * acc["leak_fire_min_pct"]:
                raise DerivationStop("LEAK_CANARY_WEAK", c["cell_id"])
            if c["stress"]:
                continue
            nr = co["null"][rs]
            bk = _int(nr.get("b3_reject_k"), f"{c['cell_id']}.b3_reject_k")
            if bk * 100 > nr["n"] * acc["b3_size_max_pct"]:
                raise DerivationStop("B3_SIZE_FAIL", c["cell_id"])
            for v in acc["b3_power_variants"]:
                m = (co.get("miscal") or {}).get(v) or {}
                mk, mn = _int(m.get("reject_k"), f"{c['cell_id']}.miscal.{v}"), _int(m.get("n"), "miscal.n")
                if mn != reps["miscal"] or mk > mn:
                    raise DerivationStop("INCOMPLETE_REPS", f"{c['cell_id']} miscal {v}")
                if mk * 100 < mn * acc["b3_power_min_pct"]:
                    raise DerivationStop("B3_POWER_FAIL", f"{c['cell_id']} {v}")
        # ------------------------------------------------------ skill: power at BSS_min, trip-wire ceiling
        bmin = protocol["bss_min"][task]

        def power_ok(c):
            sk = ((cells_out[c["cell_id"]].get("skill") or {}).get(bmin)) or {}
            pk, pn = _int(sk.get("pass_k"), f"{c['cell_id']}.skill.{bmin}"), _int(sk.get("n"), "skill.n")
            if pn != reps["skill"] or pk > pn:
                raise DerivationStop("INCOMPLETE_REPS", f"{c['cell_id']} skill {bmin}")
            return pk * 100 >= pn * acc["power_min_pct"]

        ceiling = None
        for c in nonstress:
            for lvl in protocol["skill_levels"]:
                sk = ((cells_out[c["cell_id"]].get("skill") or {}).get(lvl)) or {}
                mx = _num(sk.get("max_bss"), f"{c['cell_id']}.skill.{lvl}.max_bss")
                ceiling = mx if ceiling is None else max(ceiling, mx)
        t["trip_wire_ceiling_bss"] = ceiling
        # ------------------------------------------------------ minimum evidence n* (upward-closed rule)
        if task in ("T1", "T2"):
            ref = [c for c in nonstress if not c.get("verification")]
            pw = {c["cell_id"]: power_ok(c) for c in nonstress}
            nstar = None
            for cnt in sorted({c["positives"] for c in ref}):
                sup = [c for c in ref if c["positives"] >= cnt]
                if sup and all(pw[c["cell_id"]] for c in sup):
                    nstar = cnt
                    break
            t["n_star_positives"] = nstar
            if nstar is None:
                t["status"] = "INSUFFICIENT_ALWAYS" if task == "T1" else "DESCRIPTIVE_ONLY"
            if task == "T2" and nstar is not None:
                base = protocol["t2_reference_base_rate"]
                thr = -(-nstar * base["den"] // base["num"])            # ceil(n* / 0.3) in exact integers
                t["breakout_count_threshold"] = thr
                above = [c for c in nonstress if c["n_events"] >= thr]
                if not above:
                    t["status"] = "DESCRIPTIVE_ONLY"
                    t["b2_check"] = "THRESHOLD_BEYOND_GRID"
                else:
                    bad = [c["cell_id"] for c in above if not pw[c["cell_id"]]]
                    if bad:
                        raise DerivationStop("B2_REFERENCE_NOT_CONSERVATIVE", ",".join(bad))
                    t["b2_check"] = "CONSERVATIVE_VERIFIED"
        else:
            refc = [c for c in nonstress if c["persistence"] == protocol["t3_reference_persistence"]]
            ref_ok_half = all(
                _int(cells_out[c["cell_id"]]["skill"][bmin]["pass_k"], "t3.ref") * 100
                >= reps["skill"] * acc["t3_fallback_power_pct"] for c in refc) if refc else False
            if not refc:
                raise DerivationStop("UNRESOLVED_FIELD", "T3 reference cell")
            if not ref_ok_half:
                t["status"] = "DESCRIPTIVE_ONLY"
            elif all(power_ok(c) for c in nonstress):
                t["n_star_days"] = protocol["t3_design_days"]
            else:
                t["status"] = "INSUFFICIENT_ALWAYS"
        if k_task == FAIL:
            t["status"] = "DESCRIPTIVE_ONLY"
        # ------------------------------------------------------ applicability exclusions (failing stress cells)
        t["exclusions"] = [c["cell_id"] for c in tcells if c["stress"]
                           and not null_pass(cells_out[c["cell_id"]]["null"][rs], reps["null"], c["cell_id"],
                                             run_step, acc)]
        t["failing_nonstress_cells"] = [c["cell_id"] for c in nonstress
                                        if not null_pass(cells_out[c["cell_id"]]["null"][rs], reps["null"],
                                                         c["cell_id"], run_step, acc)]
        res["tasks"][task] = t
    return res
