"""AM-4-A Stage A development harness: bounded, development-only fixtures for the offset surrogates.

NOT an MI experiment, NOT a Phase 1S trial, NOT the exploratory pilot. It never reads the frozen 48-cell grid, never
computes a task-wide ceiling and never counts canary fires. It runs a small set of pre-specified synthetic
development fixtures (seed namespace ``am4a-dev``, disjoint from every Phase 1S / pilot namespace) and writes a
manifest with results, timings and hashes. Standard library only; nothing here reserves, spends or verifies CPU
budget, and nothing imports the engine, the guard, the ledgers or any database client.

Run (development only):  python3 -m <this package>.am4a_dev --out <dir>   (from the repository root)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import sys
import time

from . import clogit_offset as CL
from . import firth as FI
from . import gen as G
from . import leakfeat as LF

NAMESPACE = "am4a-dev"
HARNESS_VERSION = "am4a-stage-a-1.1.0"
_SEEN = set()


def seed_hex(test_id: str, case: str, rep: int, role: str = "") -> str:
    s = f"{NAMESPACE}|{test_id}|{case}|{rep}" + (f"|{role}" if role else "")
    h = hashlib.sha256(s.encode()).hexdigest()[:16]
    if h in _SEEN:
        raise ValueError(f"duplicate seed {h} for {s}")
    _SEEN.add(h)
    return h


def reset_seed_registry():
    _SEEN.clear()


def rng(hexseed: str):
    return G.rng_from(hexseed)


SUCCESS_STATUSES = ("CONVERGED",)


def fit_is_success(result) -> bool:
    """The only status that counts as a successful fit in Stage A reporting. FP_FLOOR, ITER_CAP, DIVERGED and
    NUMERICAL_FAIL are never success, whatever their coefficients look like."""
    return getattr(result, "status", None) in SUCCESS_STATUSES


def fit_record(result) -> dict:
    """Verbatim status propagation for evidence output."""
    return {"status": result.status, "success": fit_is_success(result), "iterations": result.iterations,
            "grad_norm": result.grad_norm, "message": result.message}


# ------------------------------------------------------------------ scores (harness-side; the oracle has its own)
def brier_bin(f: list, y: list) -> float:
    return sum((a - b) * (a - b) for a, b in zip(f, y)) / len(y)


def brier_multi(F: list, y: list) -> float:
    tot = 0.0
    for row, k in zip(F, y):
        tot += sum((v - (1.0 if j == k else 0.0)) ** 2 for j, v in enumerate(row))
    return tot / len(y)


def bss(brier_cand: float, brier_base: float) -> float:
    return 1.0 - brier_cand / brier_base if brier_base > 0 else 0.0


# ------------------------------------------------------------------ fixtures (frozen generators, read-only)
def binary_fixture(test_id: str, case: str, rep: int, n: int, pi: float, rho: float = 0.0, n_noise: int = 6):
    """A T2-type world (no incremental skill) with the AM-4-A leak feature; dev and eval draws are independent."""
    cell = {"task": "T2", "cell_id": f"dev|T2|n={n}|pi={pi}|rho={rho}", "n_events": n, "pi": pi, "rho": rho}
    out = {}
    for role in ("dev", "eval"):
        w = G.t2_world(cell, rng(seed_hex(test_id, case, rep, role)), None, n_noise=n_noise)
        x = LF.leak_feature_binary(rng(seed_hex(test_id, case, rep, role + "-leak")), w.y)
        out[role] = {"X": LF.binary_design(x, w.noise), "y": w.y, "offset": LF.binary_offset(w.b), "b": w.b}
    return out


def t3_fixture(test_id: str, case: str, rep: int, persistence: float, shape: str, days: int, n_noise: int = 6):
    cell = {"task": "T3", "cell_id": f"dev|T3|p={persistence}|{shape}|d={days}", "persistence": persistence,
            "shape": shape, "days": days}
    out = {}
    for role in ("dev", "eval"):
        m = G.t3_world(cell, rng(seed_hex(test_id, case, rep, role)), n_noise_sets=n_noise)
        x = LF.leak_feature_multi(rng(seed_hex(test_id, case, rep, role + "-leak")), m.y, LF.K_T3)
        out[role] = {"C": LF.t3_design(x, m.noise), "y": m.y, "logb": LF.t3_offset(m.b), "b": m.b, "lag": m.lag}
    return out


# ------------------------------------------------------------------ statistical development checks (bounded)
def check_binary_recovery(n: int = 20000, pi: float = 0.3) -> dict:
    """Offset Firth fit on a large dev draw: theta_x should be near 2 w_f = 4 (statistical observation, not a
    deterministic property). Reports SE-scaled deviation, calibration-in-the-large and Brier diagnostics."""
    t0 = time.process_time()
    fx = binary_fixture("S1", f"n{n}-pi{pi}", 0, n, pi)
    d, e = fx["dev"], fx["eval"]
    r = FI.firth_fit(d["X"], d["y"], d["offset"])
    se = FI.standard_errors(d["X"], r.beta, d["offset"]) if r.status == "CONVERGED" else None
    pe = FI.predict(e["X"], r.beta, e["offset"])
    bc, bb = brier_bin(pe, e["y"]), brier_bin(e["b"], e["y"])
    return {"fixture": "T2-type world, no skill, 6 noise features, w_f=2", "n": n, "pi": pi, "status": r.status,
            "iterations": r.iterations, "grad_norm": r.grad_norm, "theta": r.beta, "se": se,
            "theta_x_minus_4_over_se": (r.beta[0] - 4.0) / se[0] if se else None,
            "noise_coefs_over_se": [b / s for b, s in zip(r.beta[1:], se[1:])] if se else None,
            "eval_mean_mu_minus_mean_y": sum(pe) / len(pe) - sum(e["y"]) / len(e["y"]),
            "eval_brier_candidate": bc, "eval_brier_baseline": bb, "eval_bss": bss(bc, bb),
            "cpu_s": time.process_time() - t0}


def check_t3_recovery(days: int = 20000, persistence: float = 0.95, shape: str = "adjacent") -> dict:
    t0 = time.process_time()
    fx = t3_fixture("S2", f"d{days}-p{persistence}-{shape}", 0, persistence, shape, days)
    d, e = fx["dev"], fx["eval"]
    r = CL.clogit_fit(d["C"], d["logb"], d["y"])
    se = CL.standard_errors(d["C"], d["logb"], d["y"], r.beta) if r.status == "CONVERGED" else None
    pe = CL.predict(e["C"], e["logb"], r.beta)
    bc, bb = brier_multi(pe, e["y"]), brier_multi(e["b"], e["y"])
    return {"fixture": "T3 world (frozen generator), 6 AR noise sets, w_f=2", "days": days,
            "persistence": persistence, "shape": shape, "lag": d["lag"], "status": r.status,
            "iterations": r.iterations, "grad_norm": r.grad_norm, "theta": r.beta, "se": se,
            "theta_x_minus_2_over_se": (r.beta[0] - 2.0) / se[0] if se else None,
            "noise_coefs_over_se": [b / s for b, s in zip(r.beta[1:], se[1:])] if se else None,
            "eval_brier_candidate": bc, "eval_brier_baseline": bb, "eval_bss": bss(bc, bb),
            "cpu_s": time.process_time() - t0}


def check_t3_uniform_baseline(days: int = 3000) -> dict:
    """persistence 0.85 / uniform has no baseline lag (climatology): the offset is constant across alternatives and
    cancels; the model must stay identified and converge."""
    t0 = time.process_time()
    fx = t3_fixture("S3", f"d{days}-p0.85-uniform", 0, 0.85, "uniform", days)
    d = fx["dev"]
    const = all(max(r) - min(r) < 1e-15 for r in d["logb"])
    r = CL.clogit_fit(d["C"], d["logb"], d["y"])
    return {"days": days, "lag": d["lag"], "offset_constant_across_alternatives": const, "status": r.status,
            "iterations": r.iterations, "grad_norm": r.grad_norm, "theta": r.beta,
            "cond_estimate": r.cond_estimate, "cpu_s": time.process_time() - t0}


def run_stage_a(out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    reset_seed_registry()
    t0 = time.process_time()
    results = {"S1_binary_recovery": check_binary_recovery(), "S2_t3_recovery": check_t3_recovery(),
               "S3_t3_uniform_baseline": check_t3_uniform_baseline()}
    for v in results.values():
        v["success"] = v["status"] in SUCCESS_STATUSES
    manifest = {"record": "tsb.mi.am4a_stage_a_manifest", "harness_version": HARNESS_VERSION, "namespace": NAMESPACE,
                "offset_rule": "binary: logit(w.b) fixed, coefficient 1 (owner Option A / form E, 2026-10-10); "
                               "T3: log(b) fixed, coefficient 1; w.b_cal is never a candidate input",
                "non_success_checks": [k for k, v in results.items() if not v["success"]],
                "python": sys.version, "platform": platform.platform(), "w_f": LF.W_F,
                "tolerances": {"tol_grad": FI.TOL_GRAD, "tol_step": FI.TOL_STEP, "max_iter": FI.MAX_ITER,
                               "max_halvings": FI.MAX_HALVINGS, "pivot_rel": FI.PIVOT_REL, "eps": FI.EPS},
                "results": results, "cpu_s_total": time.process_time() - t0,
                "seeds_used": sorted(_SEEN)}
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    manifest["manifest_sha256"] = hashlib.sha256(body.encode()).hexdigest()
    with open(os.path.join(out_dir, "stage_a_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, sort_keys=True, indent=1)
    return manifest


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="AM-4-A Stage A development harness (bounded, offline, no MI budget)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    m = run_stage_a(a.out)
    print(json.dumps({k: (v if k != "results" else {kk: vv["status"] for kk, vv in v.items()})
                      for k, v in m.items() if k in ("results", "cpu_s_total", "manifest_sha256")}, indent=1))
