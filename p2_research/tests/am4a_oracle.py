"""Independent mathematical oracle for the AM-4-A Stage A solvers.

Rules (owner directive 2026-10-10 §8): this module imports NOTHING from p2_research.mi. Every quantity is computed
from independently written formulas: naive logistic likelihood with max-shifted log1p, Fisher information via explicit
loops, determinants by cofactor (Laplace) expansion, softmax by direct exponentiation (small examples only),
expanded-form Brier scores, central finite differences, and one-dimensional root finding / golden-section search for
worked examples. It is intentionally slow and simple; it is only used on small inputs.
"""
from __future__ import annotations

import math


# ------------------------------------------------------------------ logistic pieces (independent formulas)
def log1pexp(t: float) -> float:
    """log(1 + e^t) = max(t, 0) + log1p(e^{-|t|})."""
    return max(t, 0.0) + math.log1p(math.exp(-abs(t)))


def mu_of(eta: float) -> float:
    # direct formula with an overflow guard, deliberately different from a sigmoid helper
    if eta > 700:
        return 1.0
    if eta < -700:
        return 0.0
    z = math.exp(eta)
    return z / (1.0 + z)


def logit_loglik(X, y, beta, offset=None):
    tot = 0.0
    for i, row in enumerate(X):
        eta = (offset[i] if offset is not None else 0.0) + sum(b * v for b, v in zip(beta, row))
        tot += y[i] * eta - log1pexp(eta)
    return tot


def fisher_info(X, y, beta, offset=None):
    p = len(X[0])
    I = [[0.0] * p for _ in range(p)]
    for i, row in enumerate(X):
        eta = (offset[i] if offset is not None else 0.0) + sum(b * v for b, v in zip(beta, row))
        m = mu_of(eta)
        w = m * (1 - m)
        for a in range(p):
            for b in range(p):
                I[a][b] += w * row[a] * row[b]
    return I


def det(A):
    """Determinant by cofactor expansion (small matrices only)."""
    n = len(A)
    if n == 1:
        return A[0][0]
    if n == 2:
        return A[0][0] * A[1][1] - A[0][1] * A[1][0]
    tot = 0.0
    for j in range(n):
        minor = [row[:j] + row[j + 1:] for row in A[1:]]
        tot += ((-1) ** j) * A[0][j] * det(minor)
    return tot


def inverse_cofactor(A):
    """Matrix inverse by the adjugate / cofactor formula (small matrices only; independent of any factorisation)."""
    n = len(A)
    d = det(A)
    if d == 0:
        raise ZeroDivisionError("singular")
    inv = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            minor = [row[:i] + row[i + 1:] for k, row in enumerate(A) if k != j]
            cof = ((-1) ** (i + j)) * (det(minor) if n > 1 else 1.0)
            inv[i][j] = cof / d
    return inv


def firth_objective(X, y, beta, offset=None):
    return logit_loglik(X, y, beta, offset) + 0.5 * math.log(det(fisher_info(X, y, beta, offset)))


def firth_adjusted_score_1d(X, y, beta, offset=None):
    """Scalar design (p = 1): U* = sum (y - mu + h (1/2 - mu)) x with h = w x^2 / I."""
    I = fisher_info(X, y, beta, offset)[0][0]
    tot = 0.0
    for i, row in enumerate(X):
        x = row[0]
        eta = (offset[i] if offset is not None else 0.0) + beta[0] * x
        m = mu_of(eta)
        h = m * (1 - m) * x * x / I
        tot += (y[i] - m + h * (0.5 - m)) * x
    return tot


# ------------------------------------------------------------------ conditional logit pieces
def clogit_probs(rows, lb, theta):
    e = [math.exp(o + sum(t * v for t, v in zip(theta, r))) for o, r in zip(lb, rows)]
    s = sum(e)
    return [v / s for v in e]


def clogit_loglik(C, logb, y, theta):
    tot = 0.0
    for rows, lb, yy in zip(C, logb, y):
        pr = clogit_probs(rows, lb, theta)
        tot += math.log(pr[yy])
    return tot


# ------------------------------------------------------------------ Brier (expanded forms)
def brier_bin_expanded(f, y):
    return sum((fi - yi) ** 2 for fi, yi in zip(f, y)) / len(y)


def brier_multi_expanded(F, y):
    tot = 0.0
    for row, k in zip(F, y):
        for j, v in enumerate(row):
            tot += (v - (1 if j == k else 0)) ** 2
    return tot / len(y)


# ------------------------------------------------------------------ numerical differentiation / 1-D optimisation
def numeric_grad(f, beta, h=1e-5):
    g = []
    for j in range(len(beta)):
        bp = list(beta); bm = list(beta)
        bp[j] += h; bm[j] -= h
        g.append((f(bp) - f(bm)) / (2 * h))
    return g


def numeric_hessian(f, beta, h=1e-4):
    p = len(beta)
    H = [[0.0] * p for _ in range(p)]
    f0 = f(beta)
    for a in range(p):
        for b in range(p):
            bpp = list(beta); bpm = list(beta); bmp = list(beta); bmm = list(beta)
            bpp[a] += h; bpp[b] += h
            bpm[a] += h; bpm[b] -= h
            bmp[a] -= h; bmp[b] += h
            bmm[a] -= h; bmm[b] -= h
            H[a][b] = (f(bpp) - f(bpm) - f(bmp) + f(bmm)) / (4 * h * h)
    return H


def bisect_root(g, lo, hi, iters=200):
    glo = g(lo)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        gm = g(mid)
        if (gm > 0) == (glo > 0):
            lo, glo = mid, gm
        else:
            hi = mid
    return 0.5 * (lo + hi)


def golden_max(f, lo, hi, iters=300):
    r = (math.sqrt(5) - 1) / 2
    a, b = lo, hi
    c, d = b - r * (b - a), a + r * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(iters):
        if fc < fd:
            a, c, fc = c, d, fd
            d = a + r * (b - a); fd = f(d)
        else:
            b, d, fd = d, c, fc
            c = b - r * (b - a); fc = f(c)
    return 0.5 * (a + b)
