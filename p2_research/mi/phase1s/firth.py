"""Firth (Jeffreys-penalised) logistic regression with a FIXED OFFSET. AM-4-A Stage A development code.

Model (offset-anchored binary surrogate, owner directive 2026-10-10):
    logit P(y = 1 | row) = offset_i + x_i . beta
The offset (for AM-4-A: logit of the frozen baseline forecast) has coefficient exactly 1 and is never estimated.
There is NO intercept and NO baseline coefficient in this model: ``beta`` has exactly as many entries as the design
has columns. FLIC is deliberately not implemented here (comparator only, separate approval required).

Estimator: maximiser of  l*(beta) = l(beta) + 0.5 * log det I(beta),  I = X^T W X,  W = diag(mu (1 - mu)).
Adjusted score (Firth 1993):  U*_j = sum_i (y_i - mu_i + h_i (1/2 - mu_i)) x_ij,  h_i = w_i x_i^T I^-1 x_i.
Optimisation: Fisher scoring with step-halving on l* (deterministic), Cholesky factorisation of I.

Convergence (both checks are reported; CONVERGED requires the gradient check):
    CONVERGED      max|U*| < tol_grad at the returned beta
    FP_FLOOR       (r3/r4) no acceptable step AND the Fisher-scoring quadratic gain proxy 0.5 U*^T I^-1 U* (equal to
                   the Newton decrement only if the penalised Hessian is -I) is <= the resolvable objective noise: the objective cannot register the
                   remaining improvement at double precision. A finite iterate, NOT a certified optimum
                   (tol_grad not met). The predicted gain and ls_tol are recorded on the result.
    ITER_CAP       max_iter reached without the gradient check
    DIVERGED       unpenalised comparator only: score below tol_grad with |beta| >= ML_SEPARATION_COEF (no MLE)
    NUMERICAL_FAIL singular / ill-conditioned information matrix, non-finite values, a stalled line search whose
                   predicted gain exceeds the resolvable noise, or cumulative objective drift (accepted noise-level
                   decreases summing to more than DRIFT_FACTOR * ls_tol below the best objective seen)
A finite iterate is never reported as converged unless the gradient check holds. Nothing here silently returns
zero coefficients: a NUMERICAL_FAIL result carries the last iterate and the reason, and callers must treat it as a
failed fit.

Standard library only. No randomness. Not wired into the Phase 1S engine.
"""
from __future__ import annotations

import math

EPS = 1e-12                  # probability clip for predictions (same value as the frozen stats.EPS)
TOL_GRAD = 1e-8
TOL_STEP = 1e-10
MAX_ITER = 100
MAX_HALVINGS = 20
PIVOT_REL = 1e-12            # Cholesky pivot below PIVOT_REL * max diagonal -> singular
FP_FLOOR_GRAD = 1e-6         # a stalled line search with max|U*| below this is FP_FLOOR, not NUMERICAL_FAIL
ML_SEPARATION_COEF = 30.0    # unpenalised diagnostic: |beta| beyond this is treated as divergence
MACHINE_EPS = 2.220446049250313e-16
LS_TOL_FACTOR = 4.0


def ls_tolerance(llp: float, n: int) -> float:
    """Scale-aware line-search acceptance tolerance (H5, 2026-10-10).

    The objective is a sum of n same-sign terms (log-probabilities) plus a small penalty. The floating-point forward
    error of such a sum is bounded by (n - 1) u sum|t_i| ~ n u |l| in the worst case and behaves like sqrt(n) u |l|
    for random rounding (u = MACHINE_EPS / 2). A trial step is accepted when it does not DECREASE the objective by more
    than 4 eps sqrt(n) (|l| + 1), i.e. by more than the resolvable rounding noise of comparing two evaluations. This
    is ~1e-13 relative: it conceals no material decrease (material decreases are >= 1e-6 in these problems) while
    not rejecting valid steps at large |l|, which an absolute 1e-12 did (n = 2e4, |l| = 1e4 gives ~1e-10 noise)."""
    return LS_TOL_FACTOR * MACHINE_EPS * math.sqrt(max(n, 1)) * (abs(llp) + 1.0)


class SingularError(ArithmeticError):
    pass


DRIFT_FACTOR = 10.0          # cumulative objective drift beyond DRIFT_FACTOR * ls_tol below the best seen -> stall


class FitResult:
    __slots__ = ("beta", "status", "iterations", "loglik", "loglik_pen", "grad_norm", "step_norm",
                 "halvings_total", "cond_estimate", "trace", "message", "predicted_gain", "ls_tol_used",
                 "best_objective")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


# ------------------------------------------------------------------ stable scalar helpers
def sigmoid(t: float) -> float:
    if t >= 0:
        return 1.0 / (1.0 + math.exp(-t))
    e = math.exp(t)
    return e / (1.0 + e)


def log_sigmoid(t: float) -> float:
    """log(sigmoid(t)) without overflow or cancellation."""
    if t >= 0:
        return -math.log1p(math.exp(-t))
    return t - math.log1p(math.exp(t))


def clip_prob(p: float) -> float:
    return EPS if p < EPS else (1.0 - EPS if p > 1.0 - EPS else p)


# ------------------------------------------------------------------ dense symmetric positive-definite algebra
def cholesky(A: list) -> list:
    """Lower-triangular L with A = L L^T. Raises SingularError on a non-positive or ill-conditioned pivot."""
    n = len(A)
    maxdiag = max(abs(A[i][i]) for i in range(n)) if n else 0.0
    if not math.isfinite(maxdiag) or maxdiag <= 0.0:
        raise SingularError("information matrix has a non-positive or non-finite diagonal")
    L = [[0.0] * n for _ in range(n)]
    for j in range(n):
        s = A[j][j] - sum(L[j][k] * L[j][k] for k in range(j))
        if not math.isfinite(s) or s <= PIVOT_REL * maxdiag:
            raise SingularError(f"singular or ill-conditioned information matrix at pivot {j} (value {s!r})")
        d = math.sqrt(s)
        L[j][j] = d
        for i in range(j + 1, n):
            L[i][j] = (A[i][j] - sum(L[i][k] * L[j][k] for k in range(j))) / d
    return L


def chol_logdet(L: list) -> float:
    return 2.0 * sum(math.log(L[i][i]) for i in range(len(L)))


def chol_forward(L: list, b: list) -> list:
    n = len(b)
    v = [0.0] * n
    for i in range(n):
        v[i] = (b[i] - sum(L[i][k] * v[k] for k in range(i))) / L[i][i]
    return v


def chol_solve(L: list, b: list) -> list:
    """Solve (L L^T) x = b."""
    n = len(b)
    v = chol_forward(L, b)
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (v[i] - sum(L[k][i] * x[k] for k in range(i + 1, n))) / L[i][i]
    return x


def chol_quadratic(L: list, x: list) -> float:
    """x^T (L L^T)^-1 x = ||L^-1 x||^2."""
    v = chol_forward(L, x)
    return sum(t * t for t in v)


def chol_cond_estimate(L: list) -> float:
    d = [L[i][i] for i in range(len(L))]
    return (max(d) / min(d)) ** 2 if d else float("nan")


def inverse_diag(L: list) -> list:
    """Diagonal of (L L^T)^-1 (for standard errors)."""
    n = len(L)
    out = []
    for j in range(n):
        e = [1.0 if i == j else 0.0 for i in range(n)]
        out.append(chol_solve(L, e)[j])
    return out


# ------------------------------------------------------------------ model pieces
def _linear(X: list, beta: list, offset) -> list:
    if offset is None:
        return [sum(b * v for b, v in zip(beta, row)) for row in X]
    return [o + sum(b * v for b, v in zip(beta, row)) for o, row in zip(offset, X)]


def loglik(X: list, y: list, beta: list, offset=None) -> float:
    """Unpenalised Bernoulli log-likelihood, computed with stable log-sigmoid terms."""
    tot = 0.0
    for eta, yy in zip(_linear(X, beta, offset), y):
        tot += log_sigmoid(eta) if yy else log_sigmoid(-eta)
    return tot


def information(X: list, mu: list) -> list:
    p = len(X[0])
    I = [[0.0] * p for _ in range(p)]
    for row, m in zip(X, mu):
        w = m * (1.0 - m)
        for a in range(p):
            wa = w * row[a]
            if wa:
                Ia = I[a]
                for b in range(a, p):
                    Ia[b] += wa * row[b]
    for a in range(p):
        for b in range(a):
            I[a][b] = I[b][a]
    return I


def penalised_loglik(X: list, y: list, beta: list, offset=None, penalty: bool = True):
    """Returns (loglik, loglik_pen, mu, L) where L is the Cholesky factor of I(beta). Raises SingularError."""
    eta = _linear(X, beta, offset)
    mu = [sigmoid(t) for t in eta]
    ll = 0.0
    for t, yy in zip(eta, y):
        ll += log_sigmoid(t) if yy else log_sigmoid(-t)
    if not math.isfinite(ll):
        raise SingularError("non-finite log-likelihood")
    L = cholesky(information(X, mu))
    llp = ll + (0.5 * chol_logdet(L) if penalty else 0.0)
    return ll, llp, mu, L


def adjusted_score(X: list, y: list, mu: list, L: list, penalty: bool = True) -> list:
    p = len(X[0])
    U = [0.0] * p
    for row, yy, m in zip(X, y, mu):
        r = yy - m
        if penalty:
            h = m * (1.0 - m) * chol_quadratic(L, row)
            r += h * (0.5 - m)
        for a in range(p):
            U[a] += r * row[a]
    return U


def predict(X: list, beta: list, offset=None) -> list:
    """Clipped probabilities in [EPS, 1 - EPS]; always finite."""
    return [clip_prob(sigmoid(t)) for t in _linear(X, beta, offset)]


# ------------------------------------------------------------------ fitting
def firth_fit(X: list, y: list, offset=None, penalty: bool = True, max_iter: int = MAX_ITER,
              tol_grad: float = TOL_GRAD, tol_step: float = TOL_STEP, max_halvings: int = MAX_HALVINGS,
              beta0=None, ls_tol=None, objective=None) -> FitResult:
    """Fisher scoring with deterministic step-halving on the (penalised) log-likelihood.

    X: list of rows (no intercept column is added; the caller decides the design). y: 0/1 ints.
    offset: list of fixed linear-predictor offsets (coefficient 1) or None.
    ls_tol: None -> scale-aware tolerance ls_tolerance(llp, n) (default); a float -> absolute tolerance (0.0 = strict,
            accept only non-decreasing trial objectives; used by the FP_FLOOR hardening test).
    objective: None -> penalised_loglik. A callable with the same signature is a documented FAULT-INJECTION SEAM for
            the hardening tests of the line-search failure branches; the development harness never sets it.
    """
    obj = penalised_loglik if objective is None else objective
    if not X or any(len(r) != len(X[0]) for r in X):
        raise ValueError("X must be a non-empty rectangular list of rows")
    if len(y) != len(X) or (offset is not None and len(offset) != len(X)):
        raise ValueError("y / offset length mismatch")
    if any(yy not in (0, 1) for yy in y):
        raise ValueError("y must be 0/1")
    p = len(X[0])
    beta = list(beta0) if beta0 is not None else [0.0] * p
    trace = []
    halvings_total = 0
    step_norm = float("nan")
    n = len(X)
    try:
        ll, llp, mu, L = obj(X, y, beta, offset, penalty)
    except SingularError as e:
        return FitResult(beta=beta, status="NUMERICAL_FAIL", iterations=0, loglik=None, loglik_pen=None,
                         grad_norm=None, step_norm=None, halvings_total=0, cond_estimate=None, trace=trace,
                         message=str(e))
    best = llp
    pred_gain = None
    tol_ls = None
    for it in range(max_iter):
        U = adjusted_score(X, y, mu, L, penalty)
        gnorm = max(abs(u) for u in U)
        trace.append(llp)
        if not math.isfinite(gnorm):
            return FitResult(beta=beta, status="NUMERICAL_FAIL", iterations=it, loglik=ll, loglik_pen=llp,
                             grad_norm=None, step_norm=step_norm, halvings_total=halvings_total,
                             cond_estimate=chol_cond_estimate(L), trace=trace, message="non-finite score", predicted_gain=pred_gain, ls_tol_used=tol_ls, best_objective=best)
        if gnorm < tol_grad:
            # Unpenalised comparator only: under (quasi-)complete separation the score vanishes while the
            # coefficients diverge (no MLE exists). A finite iterate with huge coefficients is NOT an optimum.
            if not penalty and max(abs(b) for b in beta) >= ML_SEPARATION_COEF:
                return FitResult(beta=beta, status="DIVERGED", iterations=it, loglik=ll, loglik_pen=llp,
                                 grad_norm=gnorm, step_norm=step_norm, halvings_total=halvings_total,
                                 cond_estimate=chol_cond_estimate(L), trace=trace,
                                 message="score below tol_grad but coefficients diverged (separation; no MLE)", predicted_gain=pred_gain, ls_tol_used=tol_ls, best_objective=best)
            return FitResult(beta=beta, status="CONVERGED", iterations=it, loglik=ll, loglik_pen=llp,
                             grad_norm=gnorm, step_norm=step_norm, halvings_total=halvings_total,
                             cond_estimate=chol_cond_estimate(L), trace=trace, message="gradient below tol_grad", predicted_gain=pred_gain, ls_tol_used=tol_ls, best_objective=best)
        delta = chol_solve(L, U)
        # Fisher-scoring quadratic gain proxy 0.5 * U*^T I^-1 U* (r4 wording): I is the EXPECTED information of the
        # unpenalised likelihood, U* the penalised score. It equals the Newton decrement of l* only when the penalised
        # Hessian equals -I; it is > 0 because I is PD, which makes delta an ascent direction of l* for small t but
        # does not by itself guarantee that the full step improves l*.
        pred_gain = 0.5 * sum(u * d for u, d in zip(U, delta))
        t = 1.0
        accepted = False
        tol_ls = ls_tolerance(llp, n) if ls_tol is None else float(ls_tol)
        for h in range(max_halvings + 1):
            cand = [b + t * d for b, d in zip(beta, delta)]
            try:
                ll2, llp2, mu2, L2 = obj(X, y, cand, offset, penalty)
            except SingularError:
                # invalid trial point (singular information or non-finite objective): the trial is rejected,
                # the last valid iterate (beta, ll, llp, mu, L) is untouched, and the step is halved
                t *= 0.5
                halvings_total += 1
                continue
            if llp2 >= llp - tol_ls:
                accepted = True
                break
            t *= 0.5
            halvings_total += 1
        if not accepted:
            # No acceptable step found (r3 classification, cause-based rather than name-based):
            #  FP_FLOOR      the quadratic gain proxy 0.5 U*^T I^-1 U* (see above) is at or below the resolvable
            #                objective noise ls_tol: the objective cannot register the remaining improvement at
            #                double precision. A finite iterate, NOT a certified optimum (tol_grad not met).
            #  NUMERICAL_FAIL the predicted ascent is resolvable yet no trial step increased the objective:
            #                a deficient direction, a defective objective, or a cumulative-drift state.
            noise = ls_tolerance(llp, n)                                  # intrinsic resolution noise
            floor = pred_gain <= noise
            status = "FP_FLOOR" if floor else "NUMERICAL_FAIL"
            return FitResult(beta=beta, status=status, iterations=it + 1, loglik=ll, loglik_pen=llp,
                             grad_norm=gnorm, step_norm=step_norm, halvings_total=halvings_total,
                             cond_estimate=chol_cond_estimate(L), trace=trace, predicted_gain=pred_gain,
                             ls_tol_used=tol_ls, best_objective=best,
                             message=("objective resolution floor: predicted gain %.3e <= resolvable noise %.3e (acceptance tol %.3e); "
                                      "gradient %.3e above tol_grad" % (pred_gain, noise, tol_ls, gnorm)) if floor else
                             ("line search stalled: predicted gain %.3e exceeds resolvable noise %.3e but no trial "
                              "step increased the objective (acceptance tol %.3e); gradient %.3e" % (pred_gain, noise, tol_ls, gnorm)))
        step_norm = max(abs(t * d) for d in delta)
        beta, ll, llp, mu, L = cand, ll2, llp2, mu2, L2
        if llp > best:
            best = llp
        elif best - llp > DRIFT_FACTOR * tol_ls:
            # accepted noise-level decreases must never accumulate into a material deterioration
            return FitResult(beta=beta, status="NUMERICAL_FAIL", iterations=it + 1, loglik=ll, loglik_pen=llp,
                             grad_norm=gnorm, step_norm=step_norm, halvings_total=halvings_total,
                             cond_estimate=chol_cond_estimate(L), trace=trace + [llp], predicted_gain=pred_gain,
                             ls_tol_used=tol_ls, best_objective=best,
                             message="cumulative objective drift: current %.12g below best %.12g by more than %g x "
                                     "ls_tol (%.3e)" % (llp, best, DRIFT_FACTOR, tol_ls))
        if step_norm < tol_step:
            # tiny step: re-evaluate the gradient; converged only if it passes the gradient check, otherwise keep
            # iterating (the loop ends by the gradient check, FP_FLOOR, NUMERICAL_FAIL or ITER_CAP)
            U = adjusted_score(X, y, mu, L, penalty)
            gnorm = max(abs(u) for u in U)
            if gnorm < tol_grad:
                trace.append(llp)
                return FitResult(beta=beta, status="CONVERGED", iterations=it + 1, loglik=ll, loglik_pen=llp,
                                 grad_norm=gnorm, step_norm=step_norm, halvings_total=halvings_total,
                                 cond_estimate=chol_cond_estimate(L), trace=trace,
                                 message="step below tol_step and gradient below tol_grad", predicted_gain=pred_gain, ls_tol_used=tol_ls, best_objective=best)
    U = adjusted_score(X, y, mu, L, penalty)
    gnorm = max(abs(u) for u in U)
    trace.append(llp)
    return FitResult(beta=beta, status="ITER_CAP", iterations=max_iter, loglik=ll, loglik_pen=llp, grad_norm=gnorm,
                     step_norm=step_norm, halvings_total=halvings_total, cond_estimate=chol_cond_estimate(L),
                     trace=trace, message="max_iter reached", predicted_gain=pred_gain, ls_tol_used=tol_ls, best_objective=best)


def standard_errors(X: list, beta: list, offset=None) -> list:
    """Model-based SEs from I(beta)^-1 (no small-sample correction). Raises SingularError."""
    mu = [sigmoid(t) for t in _linear(X, beta, offset)]
    L = cholesky(information(X, mu))
    return [math.sqrt(v) for v in inverse_diag(L)]


def ml_separation_diagnostic(X: list, y: list, offset=None, max_iter: int = 25) -> dict:
    """Unpenalised comparator: reports whether maximum likelihood shows signs of (quasi-)complete separation.
    Informational only; never used for the primary fit."""
    r = firth_fit(X, y, offset, penalty=False, max_iter=max_iter)
    big = max(abs(b) for b in r.beta) if r.beta else 0.0
    mu = predict(X, r.beta, offset)
    perfect = all(abs(m - yy) < 1e-6 for m, yy in zip(mu, y))
    flag = r.status == "DIVERGED" or (r.status != "CONVERGED" and big >= ML_SEPARATION_COEF) or perfect
    return {"ml_status": r.status, "ml_max_abs_coef": big, "ml_perfect_prediction": perfect,
            "separation_detected": bool(flag)}
