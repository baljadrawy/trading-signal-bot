"""P2-F0 statistics core (stdlib only, deterministic given a seed).

Everything here works on small samples of DAY-CLUSTER series (the inference unit of P2-F0, see
docs/p2/P2F0_ADVERSARIAL_VALIDATION.md section 4). No function reads data or knows about strategies.

Conventions
  * one-sided tests of H0: mu <= 0 against H1: mu > 0 unless stated otherwise;
  * p-values are never rounded and never clipped to 0: a bootstrap / permutation p-value is (1 + #) / (1 + B);
  * every random draw goes through a ``random.Random`` built from an explicit integer seed.
"""
from __future__ import annotations

import math
import random
from statistics import NormalDist

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


class StatsError(ValueError):
    pass


# ---------------------------------------------------------------- basic moments
def mean(x):
    if not x:
        raise StatsError("mean of empty sample")
    return math.fsum(x) / len(x)


def var(x, ddof: int = 1):
    n = len(x)
    if n - ddof <= 0:
        raise StatsError("variance needs more observations")
    m = mean(x)
    return math.fsum((v - m) ** 2 for v in x) / (n - ddof)


def sd(x, ddof: int = 1):
    return math.sqrt(var(x, ddof))


def skew_kurt(x):
    """Sample skewness and (non-excess) kurtosis (population moments; used by the PSR only)."""
    n = len(x)
    m = mean(x)
    m2 = math.fsum((v - m) ** 2 for v in x) / n
    if m2 <= 0:
        return 0.0, 3.0
    m3 = math.fsum((v - m) ** 3 for v in x) / n
    m4 = math.fsum((v - m) ** 4 for v in x) / n
    return m3 / m2 ** 1.5, m4 / m2 ** 2


def quantile(x, q: float):
    """Type-7 (linear interpolation) quantile."""
    if not x:
        raise StatsError("quantile of empty sample")
    s = sorted(x)
    h = (len(s) - 1) * q
    lo = math.floor(h)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (h - lo) * (s[hi] - s[lo])


def autocorr(x, k: int):
    n = len(x)
    if k >= n:
        return 0.0
    m = mean(x)
    den = math.fsum((v - m) ** 2 for v in x)
    if den <= 0:
        return 0.0
    return math.fsum((x[i] - m) * (x[i + k] - m) for i in range(n - k)) / den


# ---------------------------------------------------------------- distributions
def norm_cdf(z):
    return _N.cdf(z)


def norm_ppf(p):
    return _N.inv_cdf(p)


def _betacf(a, b, x):
    """Continued fraction for the regularized incomplete beta (Lentz)."""
    tiny, eps = 1e-300, 3e-15
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


def betainc(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    bt = math.exp(lbt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_sf(t, df):
    """P(T > t) for Student t with ``df`` degrees of freedom (df may be non-integer, >= 1)."""
    if df <= 0:
        raise StatsError("df must be positive")
    x = df / (df + t * t)
    tail = 0.5 * betainc(df / 2.0, 0.5, x)
    return tail if t > 0 else 1.0 - tail


# ---------------------------------------------------------------- dependence
def bartlett_lrv(x, lag: int):
    """Newey-West (Bartlett kernel) long-run variance of x (demeaned), ``lag`` >= 0."""
    n = len(x)
    m = mean(x)
    e = [v - m for v in x]
    g0 = math.fsum(v * v for v in e) / n
    s = g0
    for k in range(1, min(lag, n - 1) + 1):
        gk = math.fsum(e[i] * e[i + k] for i in range(n - k)) / n
        s += 2.0 * (1.0 - k / (lag + 1.0)) * gk
    return max(s, 0.0)


def n_eff(x, lag: int):
    """Effective sample size n * gamma0 / LRV (Bartlett), clipped to [1, n]. Positive autocorrelation lowers it;
    negative autocorrelation is NOT allowed to raise it above n (conservative)."""
    n = len(x)
    if n < 2:
        return float(n)
    g0 = var(x, ddof=0)
    lrv = bartlett_lrv(x, lag)
    if g0 <= 0 or lrv <= 0:
        return float(n)
    return max(1.0, min(float(n), n * g0 / lrv))


def nw_t_test(x, lag: int):
    """One-sided HAC t-test of mean > 0. SE from the Bartlett LRV with the small-sample factor n/(n-1); the
    reference distribution is Student t with df = max(1, n_eff - 1) (fewer effective observations -> fatter tails).
    Returns dict(mean, se, t, df, p)."""
    n = len(x)
    if n < 3:
        raise StatsError("nw_t_test needs >= 3 observations")
    m = mean(x)
    lrv = bartlett_lrv(x, lag) * n / (n - 1.0)
    lrv = max(lrv, var(x) * 1e-12)
    se = math.sqrt(lrv / n)
    if se <= 0:
        return {"mean": m, "se": 0.0, "t": math.inf if m > 0 else -math.inf, "df": n - 1.0,
                "p": 0.0 if m > 0 else 1.0}
    t = m / se
    df = max(1.0, n_eff(x, lag) - 1.0)
    return {"mean": m, "se": se, "t": t, "df": df, "p": t_sf(t, df)}


# ---------------------------------------------------------------- bootstrap
def stationary_indices(n: int, mean_block: float, rng: random.Random):
    """One Politis-Romano stationary-bootstrap resample of range(n) (circular, geometric block lengths with mean
    ``mean_block``). ``mean_block`` <= 1 degenerates to the iid bootstrap."""
    if n <= 0:
        return []
    p = 1.0 / mean_block if mean_block > 1 else 1.0
    out = []
    i = rng.randrange(n)
    for _ in range(n):
        out.append(i)
        if rng.random() < p:
            i = rng.randrange(n)
        else:
            i = (i + 1) % n
    return out


def bootstrap_mean_p(x, mean_block: float, reps: int, seed: int):
    """Stationary-bootstrap one-sided p-value for mean > 0 (null-centred: P*(m* - m >= m)), plus a percentile CI
    of the mean (two-sided 90 %, i.e. one-sided 95 % bounds). Returns dict(mean, p, lo95, hi95, reps)."""
    n = len(x)
    if n < 3:
        raise StatsError("bootstrap needs >= 3 observations")
    m = mean(x)
    rng = random.Random(seed)
    ms = []
    hits = 0
    for _ in range(reps):
        idx = stationary_indices(n, mean_block, rng)
        mb = math.fsum(x[i] for i in idx) / n
        ms.append(mb)
        if mb - m >= m:
            hits += 1
    return {"mean": m, "p": (1 + hits) / (1 + reps), "lo95": quantile(ms, 0.05), "hi95": quantile(ms, 0.95),
            "reps": reps}


def core_test(x, mean_block: float, lag: int, reps: int, seed: int):
    """The P2-F0 primary one-sided test of mean > 0 on a day-cluster series: the LARGER (more conservative) of
    the stationary-bootstrap p and the HAC-t p. Each is known to be anti-conservative at small n on its own
    (synthetic calibration, section 9 of the design document); taking the maximum is never less conservative
    than either valid test."""
    b = bootstrap_mean_p(x, mean_block, reps, seed)
    t = nw_t_test(x, lag)
    return {"mean": b["mean"], "p": max(b["p"], t["p"]), "p_boot": b["p"], "p_hac_t": t["p"], "t": t["t"],
            "df": t["df"], "se": t["se"], "lo95": min(b["lo95"], b["mean"] - _t_q95(t["df"]) * t["se"]),
            "hi95": max(b["hi95"], b["mean"] + _t_q95(t["df"]) * t["se"]), "n": len(x),
            "n_eff": n_eff(x, lag)}


def _t_q95(df):
    """Upper 95 % quantile of Student t (bisection on t_sf)."""
    lo, hi = 0.0, 100.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if t_sf(mid, df) > 0.05:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------- regression (attribution)
def _solve(a, b):
    """Gaussian elimination with partial pivoting for a small dense system."""
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-18:
            raise StatsError("singular design (factor without variation)")
        m[c], m[piv] = m[piv], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def ols_alpha(y, factors, lag: int):
    """OLS y = alpha + sum b_k f_k + e with a Newey-West (Bartlett) HAC standard error for alpha.
    Returns dict(alpha, betas, se_alpha, t_alpha, df, p_alpha (one-sided alpha > 0), r2, n)."""
    n = len(y)
    k = len(factors)
    if n < k + 3:
        raise StatsError("too few observations for the regression")
    X = [[1.0] + [f[i] for f in factors] for i in range(n)]
    p = k + 1
    xtx = [[math.fsum(X[i][a] * X[i][b] for i in range(n)) for b in range(p)] for a in range(p)]
    xty = [math.fsum(X[i][a] * y[i] for i in range(n)) for a in range(p)]
    beta = _solve(xtx, xty)
    e = [y[i] - math.fsum(beta[j] * X[i][j] for j in range(p)) for i in range(n)]
    # (X'X)^-1 first row via solving with unit vector
    inv_rows = [_solve(xtx, [1.0 if r == c else 0.0 for r in range(p)]) for c in range(p)]
    # HAC meat S = sum_l w_l sum_i (x_i e_i)(x_{i-l} e_{i-l})'
    g = [[X[i][a] * e[i] for a in range(p)] for i in range(n)]
    S = [[math.fsum(g[i][a] * g[i][b] for i in range(n)) for b in range(p)] for a in range(p)]
    for l in range(1, min(lag, n - 1) + 1):
        w = 1.0 - l / (lag + 1.0)
        for a in range(p):
            for b in range(p):
                c = math.fsum(g[i][a] * g[i - l][b] + g[i - l][a] * g[i][b] for i in range(l, n))
                S[a][b] += w * c
    r0 = inv_rows[0]                                         # first row of (X'X)^-1 (symmetric)
    v_alpha = math.fsum(r0[a] * S[a][b] * r0[b] for a in range(p) for b in range(p)) * n / max(1, n - p)
    se = math.sqrt(max(v_alpha, 0.0))
    ybar = mean(y)
    sst = math.fsum((v - ybar) ** 2 for v in y)
    sse = math.fsum(v * v for v in e)
    df = max(1.0, n - p)
    t = beta[0] / se if se > 0 else (math.inf if beta[0] > 0 else -math.inf)
    return {"alpha": beta[0], "betas": beta[1:], "se_alpha": se, "t_alpha": t, "df": df,
            "p_alpha": t_sf(t, df) if math.isfinite(t) else (0.0 if t > 0 else 1.0),
            "r2": 1.0 - sse / sst if sst > 0 else 0.0, "n": n}


# ---------------------------------------------------------------- multiplicity
def holm(pvals: dict):
    """Holm step-down adjusted p-values for {name: p}."""
    items = sorted(pvals.items(), key=lambda kv: (kv[1], kv[0]))
    m = len(items)
    out, run = {}, 0.0
    for i, (k, p) in enumerate(items):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = run
    return out


def bh(pvals: dict):
    """Benjamini-Hochberg adjusted p-values (FDR; reported only, never a gate in P2-F0)."""
    items = sorted(pvals.items(), key=lambda kv: (kv[1], kv[0]))
    m = len(items)
    out, run = {}, 1.0
    for i in range(m - 1, -1, -1):
        k, p = items[i]
        run = min(run, p * m / (i + 1))
        out[k] = min(1.0, run)
    return out


def romano_wolf(series: dict, mean_block: float, lag: int, reps: int, seed: int):
    """Romano-Wolf step-down (studentized max-t, stationary bootstrap with COMMON indices across trials, so the
    cross-trial dependence is kept). All series must be aligned on the same days. Returns adjusted p per trial."""
    names = sorted(series)
    if not names:
        return {}
    n = len(series[names[0]])
    if any(len(series[k]) != n for k in names):
        raise StatsError("romano_wolf: series must be aligned (same days)")
    stat, se = {}, {}
    for k in names:
        r = nw_t_test(series[k], lag)
        stat[k], se[k] = r["t"], r["se"] if r["se"] > 0 else 1e-12
    mu = {k: mean(series[k]) for k in names}
    rng = random.Random(seed)
    boot = []                                                # per rep: {name: centred t*}
    for _ in range(reps):
        idx = stationary_indices(n, mean_block, rng)
        boot.append({k: (math.fsum(series[k][i] for i in idx) / n - mu[k]) / se[k] for k in names})
    order = sorted(names, key=lambda k: (-stat[k], k))
    adj, run = {}, 0.0
    for j, k in enumerate(order):
        rest = order[j:]
        hits = sum(1 for b in boot if max(b[r] for r in rest) >= stat[k])
        p = (1 + hits) / (1 + reps)
        run = max(run, p)
        adj[k] = run
    return adj


def effective_trials(n_total: int, mean_abs_corr: float):
    """Effective number of independent trials, 1 + (N - 1)(1 - |rho_bar|): N counts EVERY ledger trial (pending,
    aborted and failed included); only evaluated trials enter rho_bar, unevaluated trials are treated as
    uncorrelated (the conservative direction for the deflated Sharpe)."""
    rho = min(1.0, max(0.0, mean_abs_corr))
    return max(1.0, 1.0 + (n_total - 1) * (1.0 - rho))


def expected_max_sr(n_trials: float, sr_var: float):
    """Bailey & Lopez de Prado expected maximum Sharpe of N independent null trials with variance ``sr_var``."""
    if n_trials <= 1:
        return 0.0
    a = norm_ppf(1.0 - 1.0 / n_trials)
    b = norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(sr_var) * ((1.0 - EULER_GAMMA) * a + EULER_GAMMA * b)


def psr(x, sr_ref: float):
    """Probabilistic Sharpe ratio P(SR > sr_ref) of a (non-annualized) series, with skew/kurtosis correction."""
    n = len(x)
    s = sd(x)
    if s <= 0 or n < 3:
        return 0.0
    sr = mean(x) / s
    g3, g4 = skew_kurt(x)
    den = 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr * sr
    den = math.sqrt(max(den, 1e-12))
    return norm_cdf((sr - sr_ref) * math.sqrt(n - 1.0) / den)


def deflated_sharpe(x, n_trials_eff: float):
    """DSR = PSR against the expected maximum Sharpe of ``n_trials_eff`` null trials. The cross-trial Sharpe
    variance is the NULL sampling variance 1/(n-1) (pre-registered; an empirical variance over correlated trials
    would understate the hurdle)."""
    n = len(x)
    sr0 = expected_max_sr(n_trials_eff, 1.0 / max(1, n - 1))
    return {"dsr": psr(x, sr0), "sr_hurdle": sr0, "sr": mean(x) / sd(x) if sd(x) > 0 else 0.0,
            "n_trials_eff": n_trials_eff}


# ---------------------------------------------------------------- sequential (forward) monitoring
def obf_spent(alpha: float, frac: float):
    """Lan-DeMets O'Brien-Fleming-type cumulative one-sided alpha spent at information fraction ``frac``."""
    if frac <= 0:
        return 0.0
    frac = min(1.0, frac)
    return 2.0 - 2.0 * norm_cdf(norm_ppf(1.0 - alpha / 2.0) / math.sqrt(frac))


def obf_increments(alpha: float, fracs):
    """Nominal per-look levels as increments of the spending function (Bonferroni on increments: conservative)."""
    out, prev = [], 0.0
    for f in fracs:
        cur = obf_spent(alpha, f)
        out.append(max(0.0, cur - prev))
        prev = cur
    return out


# ---------------------------------------------------------------- primary estimand: net alpha
def alpha_series(p, m):
    """Market-adjusted day series a_d = p_d - beta_hat * m_d (beta by OLS with intercept); mean(a) = OLS alpha."""
    n = len(p)
    mm, mp = mean(m), mean(p)
    vm = math.fsum((v - mm) ** 2 for v in m)
    beta = math.fsum((m[i] - mm) * (p[i] - mp) for i in range(n)) / vm if vm > 0 else 0.0
    return [p[i] - beta * m[i] for i in range(n)], beta


def alpha_test(p, m, mean_block: float, lag: int, reps: int, seed: int):
    """One-sided test of net alpha > 0: the conservative core test on a_d with one extra degree of freedom spent on
    beta (the HAC-t df is reduced by one)."""
    a, beta = alpha_series(p, m)
    b = bootstrap_mean_p(a, mean_block, reps, seed)
    t = nw_t_test(a, lag)
    df = max(1.0, t["df"] - 1.0)
    pt = t_sf(t["t"], df) if math.isfinite(t["t"]) else (0.0 if t["t"] > 0 else 1.0)
    q = _t_q95(df)
    return {"alpha": b["mean"], "beta": beta, "p": max(b["p"], pt), "p_boot": b["p"], "p_hac_t": pt, "t": t["t"],
            "df": df, "se": t["se"], "lo95": min(b["lo95"], b["mean"] - q * t["se"]),
            "hi95": max(b["hi95"], b["mean"] + q * t["se"]), "n": len(a), "n_eff": n_eff(a, lag), "series": a}


def joint_tail_p(obs: list, ref: list, adverse: list):
    """Westfall-Young style joint p for several fragility statistics. ``obs`` = observed values (None = skipped),
    ``ref`` = list of reference vectors, ``adverse`` = +1 if a HIGH value is adverse, -1 if LOW. Returns
    (p_joint, per-statistic p). The per-statistic p is the reference tail at or beyond the observation; the joint p is
    the reference share whose own minimum tail p is at or below the observed minimum."""
    R = len(ref)
    idx = [j for j, o in enumerate(obs) if o is not None]
    if not idx or R < 20:
        return None, {}
    per = {}
    for j in idx:
        per[j] = (1 + sum(1 for r in ref if adverse[j] * (r[j] - obs[j]) >= 0)) / (1 + R)
    pmin = min(per.values())
    # tail p of each reference sample (rank within the reference itself)
    cols = {j: sorted(adverse[j] * r[j] for r in ref) for j in idx}
    import bisect
    hits = 0
    for r in ref:
        pm = 1.0
        for j in idx:
            v = adverse[j] * r[j]
            ge = R - bisect.bisect_left(cols[j], v)          # reference values >= v (incl. itself)
            pm = min(pm, ge / (1 + R))
        if pm <= pmin:
            hits += 1
    return (1 + hits) / (1 + R), per


# ---------------------------------------------------------------- inference v2 (F0 contract set v2)
# v1 = max(stationary bootstrap, HAC-t with Student df) was measured anti-conservative at n ~ 14 (study C1 of the v1
# plan: 8.6 % iid, 9.3 % AR(0.3), 14 % AR(0.5) at nominal 5 %). v2 adds two small-sample-honest tests and keeps the max.
def block_length(n: int, horizon_block: int) -> int:
    """v2 block length: max(horizon block, ceil(n^(1/3)))."""
    return max(int(horizon_block), math.ceil(n ** (1.0 / 3.0) - 1e-12))


def batch_means_p(x, L: int, df_loss: int = 0):
    """Non-overlapping batch means of length L (the oldest n mod L days dropped), one-sided t-test of mean > 0 with
    k - 1 - df_loss degrees of freedom. None when fewer than df_loss + 3 batches exist."""
    n = len(x)
    k = n // L
    if k < df_loss + 3:
        return None
    y = x[n - k * L:]
    bm = [math.fsum(y[i * L:(i + 1) * L]) / L for i in range(k)]
    m = mean(bm)
    s = sd(bm)
    if s <= 0:
        return 0.0 if m > 0 else 1.0
    return t_sf(m / (s / math.sqrt(k)), k - 1 - df_loss)


_FIXEDB = {}


def fixedb_hac_p(x, lag: int, sims: int = 4999):
    """HAC t of mean > 0 referred to its own simulated null distribution under iid N(0, 1) at the same n and lag
    (fixed-b idea: the small-sample bias of the Bartlett LRV is reproduced in the reference). Deterministic."""
    import bisect
    n = len(x)
    key = (n, lag, sims)
    if key not in _FIXEDB:
        rng = random.Random(f"p2f0|fixedb|{n}|{lag}|{sims}")
        _FIXEDB[key] = sorted(nw_t_test([rng.gauss(0.0, 1.0) for _ in range(n)], lag)["t"] for _ in range(sims))
    ref = _FIXEDB[key]
    t = nw_t_test(x, lag)["t"]
    return (1 + len(ref) - bisect.bisect_left(ref, t)) / (1 + len(ref))


def core_test_v2(x, L: int, reps: int, seed: int, df_loss: int = 0):
    b = bootstrap_mean_p(x, L, reps, seed)
    t = nw_t_test(x, L)
    pb = batch_means_p(x, L, df_loss)
    pf = fixedb_hac_p(x, L)
    p = max(b["p"], pf, 1.0 if pb is None else pb)
    q = _t_q95(max(1.0, t["df"] - df_loss))
    return {"mean": b["mean"], "p": p, "p_boot": b["p"], "p_batch": pb, "p_fixedb": pf, "t": t["t"],
            "df": t["df"], "se": t["se"], "lo95": min(b["lo95"], b["mean"] - q * t["se"]),
            "hi95": max(b["hi95"], b["mean"] + q * t["se"]), "n": len(x), "n_eff": n_eff(x, L), "block": L,
            "method": "v2"}


def alpha_test_v2(p, m, L: int, reps: int, seed: int):
    a, beta = alpha_series(p, m)
    r = core_test_v2(a, L, reps, seed, df_loss=1)
    r.update({"alpha": r["mean"], "beta": beta, "series": a})
    return r
