"""Offset conditional logit (T3 surrogate). AM-4-A Stage A development code.

Model (owner directive 2026-10-10, C1):
    P(y_i = k | b_i, c_i) = b_{i,k} exp(theta . c_{i,k}) / sum_j b_{i,j} exp(theta . c_{i,j})
i.e. a conditional logit whose linear predictor is  s_{i,k} = log b_{i,k} + theta . c_{i,k}  with the log-baseline
as a FIXED OFFSET (coefficient exactly 1, never estimated) and NO class-specific constants. All K alternatives are kept
on every day, including classes that never occur in the fitting draw.

Log-likelihood:  l(theta) = sum_i [ s_{i,y_i} - logsumexp_k s_{i,k} ]
Score:           U(theta) = sum_i [ c_{i,y_i} - sum_k p_{i,k} c_{i,k} ]
Information:     I(theta) = sum_i sum_k p_{i,k} (c_{i,k} - cbar_i)(c_{i,k} - cbar_i)^T  (= -Hessian; PSD)
Optimisation: Newton with deterministic step-halving on l, Cholesky of I. Status taxonomy and convergence rules are
the same as firth.py (CONVERGED requires max|U| < tol_grad). Maximum likelihood only (no penalty): the owner's
C1 decision; separation along a covariate direction is reported through ITER_CAP / coefficient growth.

Standard library only. No randomness. Not wired into the Phase 1S engine.
"""
from __future__ import annotations

import math

from .firth import (FP_FLOOR_GRAD, FitResult, SingularError, cholesky, chol_cond_estimate, chol_solve, inverse_diag,
                    ls_tolerance)

TOL_GRAD = 1e-8
TOL_STEP = 1e-10
MAX_ITER = 100
MAX_HALVINGS = 20


def _check(C: list, logb: list, y: list):
    if not C:
        raise ValueError("empty design")
    K = len(C[0])
    p = len(C[0][0])
    if len(logb) != len(C) or len(y) != len(C):
        raise ValueError("length mismatch between C, logb and y")
    for rows, lb, yy in zip(C, logb, y):
        if len(rows) != K or len(lb) != K or any(len(r) != p for r in rows):
            raise ValueError("ragged design: every day must have K alternatives with p covariates")
        if not (0 <= yy < K):
            raise ValueError("y outside 0..K-1")
        if any(not math.isfinite(v) for v in lb):
            raise ValueError("non-finite log-baseline offset")
    return K, p


def day_probs(rows: list, lb: list, theta: list) -> list:
    """Softmax over alternatives of (log b_k + theta . c_k), log-sum-exp stabilised. Sums to 1 up to rounding."""
    sc = [o + sum(t * v for t, v in zip(theta, r)) for o, r in zip(lb, rows)]
    m = max(sc)
    e = [math.exp(s - m) for s in sc]
    tot = sum(e)
    return [v / tot for v in e]


def loglik(C: list, logb: list, y: list, theta: list) -> float:
    tot = 0.0
    for rows, lb, yy in zip(C, logb, y):
        sc = [o + sum(t * v for t, v in zip(theta, r)) for o, r in zip(lb, rows)]
        m = max(sc)
        tot += sc[yy] - (m + math.log(sum(math.exp(s - m) for s in sc)))
    return tot


def score_info(C: list, logb: list, y: list, theta: list):
    """Returns (loglik, score U, information I) at theta in one pass."""
    K, p = len(C[0]), len(theta)
    ll = 0.0
    U = [0.0] * p
    I = [[0.0] * p for _ in range(p)]
    for rows, lb, yy in zip(C, logb, y):
        sc = [o + sum(t * v for t, v in zip(theta, r)) for o, r in zip(lb, rows)]
        m = max(sc)
        e = [math.exp(s - m) for s in sc]
        tot = sum(e)
        pr = [v / tot for v in e]
        ll += sc[yy] - (m + math.log(tot))
        mean = [sum(pr[k] * rows[k][a] for k in range(K)) for a in range(p)]
        for a in range(p):
            U[a] += rows[yy][a] - mean[a]
        for k in range(K):
            pk = pr[k]
            if pk:
                d = [rows[k][a] - mean[a] for a in range(p)]
                for a in range(p):
                    da = pk * d[a]
                    if da:
                        Ia = I[a]
                        for b in range(a, p):
                            Ia[b] += da * d[b]
    for a in range(p):
        for b in range(a):
            I[a][b] = I[b][a]
    return ll, U, I


def predict(C: list, logb: list, theta: list) -> list:
    return [day_probs(rows, lb, theta) for rows, lb in zip(C, logb)]


def clogit_fit(C: list, logb: list, y: list, max_iter: int = MAX_ITER, tol_grad: float = TOL_GRAD,
               tol_step: float = TOL_STEP, max_halvings: int = MAX_HALVINGS, theta0=None, ls_tol=None) -> FitResult:
    """C[i][k]: covariate vector of alternative k on day i (no constants, no baseline column);
    logb[i][k]: fixed offset log b_{i,k}; y[i]: realised class.
    ls_tol: None -> scale-aware acceptance tolerance (firth.ls_tolerance with n = number of days); float -> absolute."""
    K, p = _check(C, logb, y)
    n = len(C)
    theta = list(theta0) if theta0 is not None else [0.0] * p
    trace = []
    halvings_total = 0
    step_norm = float("nan")
    ll, U, I = score_info(C, logb, y, theta)
    for it in range(max_iter):
        gnorm = max(abs(u) for u in U)
        trace.append(ll)
        if not math.isfinite(ll) or not math.isfinite(gnorm):
            return FitResult(beta=theta, status="NUMERICAL_FAIL", iterations=it, loglik=ll, loglik_pen=None,
                             grad_norm=None, step_norm=step_norm, halvings_total=halvings_total, cond_estimate=None,
                             trace=trace, message="non-finite log-likelihood or score")
        try:
            L = cholesky(I)
        except SingularError as e:
            return FitResult(beta=theta, status="NUMERICAL_FAIL", iterations=it, loglik=ll, loglik_pen=None,
                             grad_norm=gnorm, step_norm=step_norm, halvings_total=halvings_total,
                             cond_estimate=None, trace=trace, message=str(e))
        if gnorm < tol_grad:
            return FitResult(beta=theta, status="CONVERGED", iterations=it, loglik=ll, loglik_pen=None,
                             grad_norm=gnorm, step_norm=step_norm, halvings_total=halvings_total,
                             cond_estimate=chol_cond_estimate(L), trace=trace, message="gradient below tol_grad")
        delta = chol_solve(L, U)
        t = 1.0
        accepted = False
        tol_ls = ls_tolerance(ll, n) if ls_tol is None else float(ls_tol)
        for h in range(max_halvings + 1):
            cand = [b + t * d for b, d in zip(theta, delta)]
            ll2, U2, I2 = score_info(C, logb, y, cand)
            if math.isfinite(ll2) and ll2 >= ll - tol_ls:
                accepted = True
                break
            t *= 0.5
            halvings_total += 1
        if not accepted:
            status = "FP_FLOOR" if gnorm < FP_FLOOR_GRAD else "NUMERICAL_FAIL"
            return FitResult(beta=theta, status=status, iterations=it + 1, loglik=ll, loglik_pen=None,
                             grad_norm=gnorm, step_norm=step_norm, halvings_total=halvings_total,
                             cond_estimate=chol_cond_estimate(L), trace=trace,
                             message=("line search at floating-point floor; gradient %.3e above tol_grad" % gnorm)
                             if status == "FP_FLOOR" else "line search stalled with gradient above tol_grad")
        step_norm = max(abs(t * d) for d in delta)
        theta, ll, U, I = cand, ll2, U2, I2
        if step_norm < tol_step:
            gnorm = max(abs(u) for u in U)
            if gnorm < tol_grad:
                trace.append(ll)
                try:
                    ce = chol_cond_estimate(cholesky(I))
                except SingularError:
                    ce = None
                return FitResult(beta=theta, status="CONVERGED", iterations=it + 1, loglik=ll, loglik_pen=None,
                                 grad_norm=gnorm, step_norm=step_norm, halvings_total=halvings_total,
                                 cond_estimate=ce, trace=trace,
                                 message="step below tol_step and gradient below tol_grad")
    gnorm = max(abs(u) for u in U)
    trace.append(ll)
    try:
        ce = chol_cond_estimate(cholesky(I))
    except SingularError:
        ce = None
    return FitResult(beta=theta, status="ITER_CAP", iterations=max_iter, loglik=ll, loglik_pen=None,
                     grad_norm=gnorm, step_norm=step_norm, halvings_total=halvings_total, cond_estimate=ce,
                     trace=trace, message="max_iter reached")


def standard_errors(C: list, logb: list, y: list, theta: list) -> list:
    _, _, I = score_info(C, logb, y, theta)
    return [math.sqrt(v) for v in inverse_diag(cholesky(I))]
