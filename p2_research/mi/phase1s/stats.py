"""Phase 1S statistics, stdlib only: normal / Student-t, stationary bootstrap, EWC Diebold-Mariano, Holm,
cluster-robust logistic regression and the B3 Cox / calibration-in-the-large test.

All randomness comes from an explicitly passed random.Random; nothing here reads files or the clock.
"""
from __future__ import annotations

import math
from statistics import NormalDist

from ..derive import Z as Z95, wilson_upper  # noqa: F401  (re-exported, frozen)

_N = NormalDist()
_SQRT1_2 = 0.7071067811865476
EPS = 1e-12


def ncdf(x: float) -> float:
    return 0.5 * math.erfc(-x * _SQRT1_2)


def nppf(p: float) -> float:
    return _N.inv_cdf(p)


def clip(p: float) -> float:
    return EPS if p < EPS else (1.0 - EPS if p > 1.0 - EPS else p)


def logit(p: float) -> float:
    p = clip(p)
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


# ============================================================================ Student-t (regularised incomplete beta)
def _betacf(a: float, b: float, x: float) -> float:
    fpmin = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > fpmin else fpmin)
    h = d
    for m in range(1, 500):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > fpmin else fpmin)
        c = 1.0 + aa / c
        c = c if abs(c) > fpmin else fpmin
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > fpmin else fpmin)
        c = 1.0 + aa / c
        c = c if abs(c) > fpmin else fpmin
        de = d * c
        h *= de
        if abs(de - 1.0) < 3e-16:
            return h
    raise ArithmeticError("betacf did not converge")


def betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1.0 - x) / b


def t_sf(t: float, nu: float) -> float:
    """P(T_nu >= t)."""
    tail = 0.5 * betainc(nu / 2.0, 0.5, nu / (nu + t * t))
    return tail if t > 0 else 1.0 - tail


# ============================================================================ B1: stationary bootstrap
def sb_pvalues(day_sums: list, day_cnt: list, mean_block: float, B: int, rng, which=None) -> list:
    """One-sided stationary-bootstrap p-values for H0: E[d] <= 0, one per series in day_sums (shared block plan).

    day_sums[j][d] = sum of the loss differential of series j on day d, day_cnt[d] = rows on day d. The statistic is
    the ratio sum / count (the row mean). `which` limits the series accumulated (decisions for the others are not
    needed); the block plan, and therefore every computed p-value, is independent of `which`.
    """
    n = len(day_cnt)
    which = list(range(len(day_sums))) if which is None else list(which)
    pc = [0.0] * (2 * n + 1)
    for i in range(2 * n):
        pc[i + 1] = pc[i] + day_cnt[i % n]
    ps, theta = {}, {}
    tot_c = pc[n]
    for j in which:
        s = day_sums[j]
        p = [0.0] * (2 * n + 1)
        for i in range(2 * n):
            p[i + 1] = p[i] + s[i % n]
        ps[j] = p
        theta[j] = p[n] / tot_c if tot_c > 0 else 0.0
    count = {j: 0 for j in which}
    rnd = rng.random
    if mean_block <= 1.0:
        inv = None
    else:
        inv = 1.0 / math.log(1.0 - 1.0 / mean_block)
    log = math.log
    for _ in range(B):
        left = n
        acc = {j: 0.0 for j in which}
        cc = 0.0
        while left > 0:
            st = int(rnd() * n)
            ln = 1 if inv is None else 1 + int(log(1.0 - rnd()) * inv)
            if ln > left:
                ln = left
            e = st + ln
            cc += pc[e] - pc[st]
            for j in which:
                p = ps[j]
                acc[j] += p[e] - p[st]
            left -= ln
        for j in which:
            th = acc[j] / cc if cc > 0 else 0.0
            if th - theta[j] >= theta[j]:
                count[j] += 1
    return [((1 + count[j]) / (B + 1)) if j in count else None for j in range(len(day_sums))]


# ============================================================================ B1: Diebold-Mariano, EWC fixed-b
_COS = {}


def ewc_nu(n_days: int, mean_block: float) -> int:
    return max(2, int(3 * n_days // (4 * mean_block)))


def _cos_table(n: int, nu: int):
    key = (n, nu)
    if key not in _COS:
        f = math.sqrt(2.0 / n)
        _COS[key] = [[f * math.cos(math.pi * j * (d + 0.5) / n) for d in range(n)] for j in range(1, nu + 1)]
    return _COS[key]


def dm_ewc_pvalue(day_sum: list, day_cnt: list, nu: int) -> tuple:
    """One-sided DM p-value for H0: E[d] <= 0. Returns (p, t)."""
    n = len(day_cnt)
    tc = sum(day_cnt)
    if tc <= 0:
        return 1.0, 0.0
    theta = sum(day_sum) / tc
    cbar = tc / n
    u = [(day_sum[d] - theta * day_cnt[d]) / cbar for d in range(n)]
    om = 0.0
    for row in _cos_table(n, nu):
        lam = 0.0
        for a, b in zip(row, u):
            lam += a * b
        om += lam * lam
    om /= nu
    if om <= 0.0:
        return (0.0 if theta > 0 else 1.0), (math.inf if theta > 0 else 0.0)
    t = theta / math.sqrt(om / n)
    return t_sf(t, nu), t


# ============================================================================ multiplicity
def holm(pvals: list, alpha: float) -> list:
    """Holm step-down. A None p-value means 'known to exceed alpha' (exact for threshold decisions)."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: (math.inf if pvals[i] is None else pvals[i], i))
    rej = [False] * m
    for r, i in enumerate(order):
        p = pvals[i]
        if p is not None and p <= alpha / (m - r):
            rej[i] = True
        else:
            break
    return rej


# ============================================================================ logistic regression, cluster-robust
def _solve(A: list, b: list) -> list:
    """Gaussian elimination with partial pivoting (small dense systems)."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-300:
            raise ArithmeticError("singular")
        M[c], M[piv] = M[piv], M[c]
        pv = M[c][c]
        for r in range(c + 1, n):
            f = M[r][c] / pv
            if f:
                Mr, Mc = M[r], M[c]
                for k in range(c, n + 1):
                    Mr[k] -= f * Mc[k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = M[r][n] - sum(M[r][k] * x[k] for k in range(r + 1, n))
        x[r] = s / M[r][r]
    return x


def _inv(A: list) -> list:
    n = len(A)
    cols = [_solve(A, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    return [[cols[j][i] for j in range(n)] for i in range(n)]


def logistic_fit(X: list, y: list, offset=None, beta0=None, max_iter: int = 50, tol: float = 1e-10):
    """Newton-Raphson logistic regression. X: list of rows (each a list of p regressors incl. intercept).
    Returns (beta, converged)."""
    p = len(X[0])
    beta = list(beta0) if beta0 is not None else [0.0] * p
    for _ in range(max_iter):
        g = [0.0] * p
        H = [[0.0] * p for _ in range(p)]
        for i, xi in enumerate(X):
            eta = (offset[i] if offset is not None else 0.0)
            for k in range(p):
                eta += beta[k] * xi[k]
            mu = sigmoid(eta)
            r = y[i] - mu
            w = mu * (1.0 - mu)
            for k in range(p):
                xk = xi[k]
                g[k] += r * xk
                wk = w * xk
                Hk = H[k]
                for l in range(k, p):
                    Hk[l] += wk * xi[l]
        for k in range(p):
            for l in range(k):
                H[k][l] = H[l][k]
        try:
            step = _solve(H, g)
        except ArithmeticError:
            return beta, False
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < tol:
            return beta, True
    return beta, False


def _fit_cal2(L: list, y: list, cl: list, G: int, max_iter: int = 50, tol: float = 1e-10):
    """y ~ a + b L, cluster-robust covariance. Returns (a, b, Vaa, Vbb, converged)."""
    a, b = 0.0, 1.0
    n = len(L)
    conv = False
    for _ in range(max_iter):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for i in range(n):
            li = L[i]
            mu = sigmoid(a + b * li)
            r = y[i] - mu
            w = mu * (1.0 - mu)
            g0 += r
            g1 += r * li
            h00 += w
            wl = w * li
            h01 += wl
            h11 += wl * li
        det = h00 * h11 - h01 * h01
        if det <= 1e-300:
            return a, b, math.inf, math.inf, False
        da = (h11 * g0 - h01 * g1) / det
        db = (h00 * g1 - h01 * g0) / det
        a += da
        b += db
        if abs(da) < tol and abs(db) < tol:
            conv = True
            break
    # sandwich at the final estimate
    s0 = [0.0] * G
    s1 = [0.0] * G
    h00 = h01 = h11 = 0.0
    for i in range(n):
        li = L[i]
        mu = sigmoid(a + b * li)
        r = y[i] - mu
        w = mu * (1.0 - mu)
        c = cl[i]
        s0[c] += r
        s1[c] += r * li
        h00 += w
        wl = w * li
        h01 += wl
        h11 += wl * li
    det = h00 * h11 - h01 * h01
    if det <= 1e-300:
        return a, b, math.inf, math.inf, False
    i00, i01, i11 = h11 / det, -h01 / det, h00 / det
    m00 = m01 = m11 = 0.0
    for c in range(G):
        u0, u1 = s0[c], s1[c]
        m00 += u0 * u0
        m01 += u0 * u1
        m11 += u1 * u1
    adj = G / (G - 1.0) if G > 1 else 1.0
    m00, m01, m11 = m00 * adj, m01 * adj, m11 * adj
    # V = I M I (2x2 symmetric)
    t00 = i00 * m00 + i01 * m01
    t01 = i00 * m01 + i01 * m11
    t10 = i01 * m00 + i11 * m01
    t11 = i01 * m01 + i11 * m11
    vaa = t00 * i00 + t01 * i01
    vbb = t10 * i01 + t11 * i11
    return a, b, vaa, vbb, conv


def _fit_offset(L: list, y: list, cl: list, G: int, max_iter: int = 50, tol: float = 1e-10):
    """y ~ a + offset(L), cluster-robust variance of a. Returns (a, Va, converged)."""
    a = 0.0
    n = len(L)
    conv = False
    for _ in range(max_iter):
        g = h = 0.0
        for i in range(n):
            mu = sigmoid(a + L[i])
            g += y[i] - mu
            h += mu * (1.0 - mu)
        if h <= 1e-300:
            return a, math.inf, False
        da = g / h
        a += da
        if abs(da) < tol:
            conv = True
            break
    s = [0.0] * G
    h = 0.0
    for i in range(n):
        mu = sigmoid(a + L[i])
        s[cl[i]] += y[i] - mu
        h += mu * (1.0 - mu)
    adj = G / (G - 1.0) if G > 1 else 1.0
    meat = sum(u * u for u in s) * adj
    return a, meat / (h * h), conv


def citl(f: list, y: list, cl: list, G: int) -> tuple:
    """Calibration-in-the-large O/E with a cluster-robust 95 % CI on the log scale. Returns (ratio, se_log)."""
    O = float(sum(y))
    E = float(sum(f))
    if O <= 0 or E <= 0:
        return 0.0, math.inf
    R = O / E
    res = [0.0] * G
    for i in range(len(f)):
        res[cl[i]] += y[i] - R * f[i]
    adj = G / (G - 1.0) if G > 1 else 1.0
    var_R = sum(u * u for u in res) * adj / (E * E)
    return R, math.sqrt(var_R) / R


_TPPF = {}
DEGEN_TOL = 1e-9


def t_ppf975(nu: int) -> float:
    """Two-sided 95 % Student-t critical value (bisection on t_sf), cached."""
    if nu not in _TPPF:
        lo, hi = 0.0, 1000.0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if t_sf(mid, nu) > 0.025:
                lo = mid
            else:
                hi = mid
        _TPPF[nu] = 0.5 * (lo + hi)
    return _TPPF[nu]


def b3_test(f: list, y: list, cl: list, G: int, z: float = Z95) -> dict:
    """Contract B3: Cox slope CI contains 1, intercept CI contains 0, calibration-in-the-large CI contains 1.
    `z` is the critical value (callers pass t_{G-1, 0.975} for time-block clusters). A CI that collapses to a point
    (structural zero variance, e.g. pooled one-vs-rest forecasts summing to one) contains the target iff the point
    is within DEGEN_TOL of it. Non-convergence or a non-finite fit counts as a rejection (fail closed)."""
    L = [logit(v) for v in f]
    a, b, vaa, vbb, c1 = _fit_cal2(L, y, cl, G)
    a0, va0, c2 = _fit_offset(L, y, cl, G)
    R, se_lr = citl(f, y, cl, G)
    slope_ok = c1 and math.isfinite(vbb) and abs(b - 1.0) <= z * math.sqrt(max(vbb, 0.0)) + DEGEN_TOL
    int_ok = c2 and math.isfinite(va0) and abs(a0) <= z * math.sqrt(max(va0, 0.0)) + DEGEN_TOL
    citl_ok = R > 0 and math.isfinite(se_lr) and abs(math.log(R)) <= z * se_lr + DEGEN_TOL
    return {"reject": not (slope_ok and int_ok and citl_ok), "slope": b, "intercept": a0, "oe": R,
            "slope_ok": slope_ok, "int_ok": int_ok, "citl_ok": citl_ok, "converged": c1 and c2}
