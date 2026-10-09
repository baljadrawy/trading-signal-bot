"""Deterministic synthetic generators for Phase 1S (protocol 'generators', 'truth_classes'). Stdlib only.

Seeds: sha256(contract_set_sha256 | cell_id | kind | level | rep [| extra]) -> first 8 bytes -> random.Random.

Probit latent framework (T1 / T2): y = 1[mu_y + s_b + s_x + z > 0] with z ~ N(0,1) margins independent of the
signals, so every forecast built here is EXACTLY calibrated given its information set:
  truth     Phi(mu_y + s_b + s_x)
  baseline  Phi((mu_f + s_b) / sqrt(1 + tau_x^2))                      (strongest baseline; knows s_b)
  skill     Phi((mu_f + s_b + s_k) / sqrt(1 + tau_u^2)), tau_k^2 = kappa tau_x^2, kappa tuned analytically so that the
            expected BSS against the baseline equals the skill level
  null      Phi(baseline index + sd * E), E an independent unit-variance noise process with the cell's dependence
T3 (6-state Markov chain): the baseline knows the state l days late (calibrated P^(7+l) row), the skill candidate
knows the current state on a random fraction w of days (calibrated mixture, expected BSS = w x BSS_full).
"""
from __future__ import annotations

import functools
import hashlib
import math
import random

from . import params as PR
from . import stats as S

_SQ2 = math.sqrt(2.0)
_INV = S._N.inv_cdf
_TWO53 = 2.0 ** -53


# ============================================================================ seeds
def seed_hex(contract_sha: str, cell_id: str, kind: str, level: str, rep: int, extra: str = "") -> str:
    s = f"{contract_sha}|{cell_id}|{kind}|{level}|{rep}" + (f"|{extra}" if extra else "")
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def rng_from(hexseed: str) -> random.Random:
    return random.Random(int(hexseed, 16))


def normals(rng: random.Random, n: int) -> list:
    g = rng.getrandbits
    return [_INV((g(53) + 0.5) * _TWO53) for _ in range(n)]


def ar1(rng: random.Random, T: int, phi: float) -> list:
    e = normals(rng, T)
    if phi == 0:
        return e
    c = math.sqrt(1.0 - phi * phi)
    x = [0.0] * T
    x[0] = e[0]
    for t in range(1, T):
        x[t] = phi * x[t - 1] + c * e[t]
    return x


def factor_series(rng: random.Random, S_: int, T: int, phi: float, rho: float) -> list:
    """S_ unit-variance AR(phi) series sharing one common AR(phi) factor with loading rho (variance share)."""
    if rho == 0:
        return [ar1(rng, T, phi) for _ in range(S_)]
    f = ar1(rng, T, phi)
    a, b = math.sqrt(rho), math.sqrt(1.0 - rho)
    return [[a * fi + b * ui for fi, ui in zip(f, ar1(rng, T, phi))] for _ in range(S_)]


# ============================================================================ analytic calibration
def _e_phi_sq(m: float, v: float, n: int = 2000, lim: float = 10.0) -> float:
    """E[Phi(m + sqrt(v) Z)^2], Simpson's rule on [-lim, lim]."""
    h = 2 * lim / n
    sv = math.sqrt(v)
    tot = 0.0
    for i in range(n + 1):
        z = -lim + i * h
        w = 1 if i in (0, n) else (4 if i % 2 else 2)
        f = S.ncdf(m + sv * z)
        tot += w * f * f * math.exp(-0.5 * z * z)
    return tot * h / 3 / math.sqrt(2 * math.pi)


def _brier_cal(m: float, v: float) -> float:
    """Expected Brier score of the calibrated forecast Phi(V), V ~ N(m, v): E[f] - E[f^2]."""
    return S.ncdf(m / math.sqrt(1 + v)) - _e_phi_sq(m, v)


@functools.lru_cache(maxsize=None)
def binary_design(pi: float, brk: int = 0) -> dict:
    tb, tx = PR.GEN["tau_b"], PR.GEN["tau_x"]
    tot = math.sqrt(1 + tb * tb + tx * tx)
    mu_y = S.nppf(pi) * tot
    mu_f = S.nppf(pi / 2) * tot if (brk and PR.GEN["t1_break_mode"] == "dev_calibrated") else mu_y
    br_b = _brier_cal(mu_y / math.sqrt(1 + tx * tx), tb * tb / (1 + tx * tx))
    return {"mu_y": mu_y, "mu_f": mu_f, "brier_b": br_b, "tau_b": tb, "tau_x": tx}


def expected_bss(pi: float, kappa: float) -> float:
    d = binary_design(pi)
    tb, tx = d["tau_b"], d["tau_x"]
    tu2 = (1 - kappa) * tx * tx
    br_c = _brier_cal(d["mu_y"] / math.sqrt(1 + tu2), (tb * tb + kappa * tx * tx) / (1 + tu2))
    return 1 - br_c / d["brier_b"]


@functools.lru_cache(maxsize=None)
def kappa_for(pi: float, level: str) -> float:
    target = float(level)
    if expected_bss(pi, 1.0) < target:
        raise ValueError(f"skill level {level} unattainable at pi={pi} (tau_x too small)")
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if expected_bss(pi, mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ============================================================================ binary worlds (T1 / T2)
class Binary:
    """A simulated binary world: rows ordered by day, `day[i]`, `cnt[d]`, outcomes `y`, baseline index `qb`."""
    __slots__ = ("n_days", "day", "cnt", "y", "qb", "b", "b_cal", "sk", "su", "noise", "pi", "kind_meta")


def _t1_layout(T: int, S_: int, spd: int):
    day = [t // spd for t in range(T) for _ in range(S_)]
    return day


def _overlap(eps: list, H: int, T: int) -> list:
    """z_t = sum_{j<H} eps_{t+j} / sqrt(H) (overlapping 24h labels on the 4h grid)."""
    c = 1.0 / math.sqrt(H)
    s = sum(eps[:H])
    out = [0.0] * T
    for t in range(T):
        out[t] = s * c
        s += eps[t + H] - eps[t] if t + H < len(eps) else -eps[t]
    return out


def t1_world(cell: dict, rng: random.Random, kappa=None, n_noise: int = 0, extra_noise_feats: int = 0) -> Binary:
    """T1: 2 series x 6 decisions/day x 517 days; latent AR(phi), common factor rho, 6x overlapping labels."""
    g = PR.GEN
    S_, spd, days, H = g["t1_series"], g["t1_steps_per_day"], g["days"], g["t1_overlap"]
    T = spd * days
    phi, rho, pi, brk = float(cell["phi"]), float(cell["rho"]), float(cell["pi"]), int(cell["break"])
    d = binary_design(pi, brk)
    tb, tx = d["tau_b"], d["tau_x"]
    xb = factor_series(rng, S_, T, phi, rho)
    if kappa is None:
        xx = factor_series(rng, S_, T, phi, rho)
        xk = None
    else:
        xk = factor_series(rng, S_, T, phi, rho)
        xx = factor_series(rng, S_, T, phi, rho)
    # outcome shocks: common factor rho across series, iid over time, H-step overlap
    if rho == 0:
        eps = [normals(rng, T + H) for _ in range(S_)]
    else:
        gco = normals(rng, T + H)
        a, b = math.sqrt(rho), math.sqrt(1 - rho)
        eps = [[a * u + b * v for u, v in zip(gco, normals(rng, T + H))] for _ in range(S_)]
    z = [_overlap(e, H, T) for e in eps]
    noise = [factor_series(rng, S_, T, phi, rho) for _ in range(n_noise)]
    w = Binary()
    w.n_days, w.pi = days, pi
    w.day = _t1_layout(T, S_, spd)
    w.cnt = [S_ * spd] * days
    sf = 1.0 / math.sqrt(1 + tx * tx)
    mu_y, mu_f = d["mu_y"], d["mu_f"]
    y, qb, sk_l, su_l = [], [], [], []
    if kappa is not None:
        tk, tu = math.sqrt(kappa) * tx, math.sqrt(1 - kappa) * tx
    for t in range(T):
        for s in range(S_):
            sb = tb * xb[s][t]
            if kappa is None:
                sx = tx * xx[s][t]
            else:
                skv, suv = tk * xk[s][t], tu * xx[s][t]
                sx = skv + suv
                sk_l.append(skv)
                su_l.append(suv)
            y.append(1 if mu_y + sb + sx + z[s][t] > 0 else 0)
            qb.append(sb)
    w.y = y
    w.qb = [(mu_f + v) * sf for v in qb]
    w.b = [S.ncdf(v) for v in w.qb]
    w.b_cal = w.b if mu_f == mu_y else [S.ncdf((mu_y + v) * sf) for v in qb]
    w.sk, w.su = (sk_l, su_l) if kappa is not None else (None, None)
    w.noise = [[v for t in range(T) for v in (ns[s][t] for s in range(S_))] for ns in noise]
    w.kind_meta = {"mu_f": mu_f, "mu_y": mu_y, "sb_raw": qb}
    return w


def t2_world(cell: dict, rng: random.Random, kappa=None, n_noise: int = 0) -> Binary:
    """T2: n_events breakout events over 517 days, day-clustered with loading rho (signals and outcome shocks)."""
    g = PR.GEN
    days, n = g["days"], int(cell["n_events"])
    rho, pi = float(cell["rho"]), float(cell["pi"])
    d = binary_design(pi, 0)
    tb, tx = d["tau_b"], d["tau_x"]
    ev_day = sorted(int(rng.random() * days) for _ in range(n))
    a, b = math.sqrt(rho), math.sqrt(1 - rho)

    def clustered():
        if rho == 0:
            return normals(rng, n)
        f = normals(rng, days)
        u = normals(rng, n)
        return [a * f[ev_day[i]] + b * u[i] for i in range(n)]

    xb = clustered()
    xk = clustered() if kappa is not None else None
    xx = clustered()
    zz = clustered()
    noise = [clustered() for _ in range(n_noise)]
    w = Binary()
    w.n_days, w.pi = days, pi
    w.day = ev_day
    cnt = [0] * days
    for dd in ev_day:
        cnt[dd] += 1
    w.cnt = cnt
    sf = 1.0 / math.sqrt(1 + tx * tx)
    mu = d["mu_y"]
    sb = [tb * v for v in xb]
    if kappa is None:
        sx = [tx * v for v in xx]
        w.sk = w.su = None
    else:
        tk, tu = math.sqrt(kappa) * tx, math.sqrt(1 - kappa) * tx
        w.sk = [tk * v for v in xk]
        w.su = [tu * v for v in xx]
        sx = [p + q for p, q in zip(w.sk, w.su)]
    w.y = [1 if mu + sb[i] + sx[i] + zz[i] > 0 else 0 for i in range(n)]
    w.qb = [(mu + v) * sf for v in sb]
    w.b = [S.ncdf(v) for v in w.qb]
    w.b_cal = w.b
    w.noise = noise
    w.kind_meta = {"mu_f": mu, "mu_y": mu, "sb_raw": sb}
    return w


def binary_world(cell, rng, kappa=None, n_noise=0):
    return t1_world(cell, rng, kappa, n_noise) if cell["task"] == "T1" else t2_world(cell, rng, kappa, n_noise)


def skill_forecast(w: Binary, pi: float, kappa: float) -> list:
    tx = PR.GEN["tau_x"]
    sf = 1.0 / math.sqrt(1 + (1 - kappa) * tx * tx)
    mu_f = w.kind_meta["mu_f"]
    return [S.ncdf((mu_f + sb + sk) * sf) for sb, sk in zip(w.kind_meta["sb_raw"], w.sk)]


def null_forecast(w: Binary, noise: list, sd: float) -> list:
    return [S.ncdf(q + sd * e) for q, e in zip(w.qb, noise)]


# ============================================================================ T3: 6-state Markov chain
# state = trend (0 down, 1 range, 2 up) x 2 + vol (0 low, 1 high)
def _neighbours(i: int) -> list:
    tr, vo = divmod(i, 2)
    out = [tr * 2 + (1 - vo)]
    for dt in (-1, 1):
        if 0 <= tr + dt <= 2:
            out.append((tr + dt) * 2 + vo)
    return sorted(out)


def transition(p: float, shape: str) -> list:
    P = [[0.0] * 6 for _ in range(6)]
    for i in range(6):
        P[i][i] = p
        nb = [j for j in range(6) if j != i] if shape == "uniform" else _neighbours(i)
        for j in nb:
            P[i][j] = (1 - p) / len(nb)
    return P


def _mm(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(6)) for j in range(6)] for i in range(6)]


def _mpow(P, k):
    R = [[1.0 if i == j else 0.0 for j in range(6)] for i in range(6)]
    Q = [r[:] for r in P]
    while k:
        if k & 1:
            R = _mm(R, Q)
        Q = _mm(Q, Q)
        k >>= 1
    return R


def stationary(P) -> list:
    v = [1 / 6] * 6
    for _ in range(20000):
        nv = [sum(v[i] * P[i][j] for i in range(6)) for j in range(6)]
        if max(abs(a - b) for a, b in zip(nv, v)) < 1e-15:
            return nv
        v = nv
    return v


def _q(rows, pst):
    return sum(pst[s] * sum(x * x for x in rows[s]) for s in range(6))


@functools.lru_cache(maxsize=None)
def t3_design(persistence: float, shape: str) -> dict:
    """Baseline lag l: smallest l in 1..lag_max with full-information expected BSS >= target; else climatology."""
    P = transition(persistence, shape)
    pst = stationary(P)
    P7 = _mpow(P, 7)
    q_full = _q(P7, pst)
    br_full = 1 - q_full
    lag, Pb, br_b = None, None, None
    for l in range(1, PR.GEN["t3_lag_max"] + 1):
        Pl = _mpow(P, 7 + l)
        br = 1 - _q(Pl, pst)
        if 1 - br_full / br >= PR.GEN["t3_baseline_bss_target"]:
            lag, Pb, br_b = l, Pl, br
            break
    if lag is None:
        Pb = [pst[:] for _ in range(6)]
        br_b = 1 - sum(x * x for x in pst)
    return {"P": P, "pst": pst, "P7": P7, "Pb": Pb, "lag": lag, "bss_full": 1 - br_full / br_b}


def t3_w(persistence: float, shape: str, level: str) -> float:
    d = t3_design(persistence, shape)
    w = float(level) / d["bss_full"]
    if w > 1:
        raise ValueError(f"T3 skill level {level} unattainable (bss_full {d['bss_full']:.4f})")
    return w


class Multi:
    __slots__ = ("n_days", "day", "cnt", "y", "b", "full", "state", "noise", "lag")


def t3_world(cell: dict, rng: random.Random, n_noise_sets: int = 0, noise_ar: float = None) -> Multi:
    p, shape, days = float(cell["persistence"]), cell["shape"], int(cell["days"])
    d = t3_design(p, shape)
    lag = d["lag"] or 0
    P, pst = d["P"], d["pst"]
    total = lag + days + 7
    cum = [[sum(P[i][:j + 1]) for j in range(6)] for i in range(6)]
    cst = [sum(pst[:j + 1]) for j in range(6)]

    def draw(cdf):
        u = rng.random()
        for j in range(6):
            if u < cdf[j]:
                return j
        return 5

    st = [draw(cst)]
    for _ in range(total - 1):
        st.append(draw(cum[st[-1]]))
    m = Multi()
    m.n_days, m.lag = days, d["lag"]
    m.day = list(range(days))
    m.cnt = [1] * days
    m.state = [st[lag + i] for i in range(days)]
    m.y = [st[lag + i + 7] for i in range(days)]
    if d["lag"] is None:
        m.b = [d["Pb"][0][:] for _ in range(days)]
    else:
        m.b = [d["Pb"][st[i]][:] for i in range(days)]
    m.full = [d["P7"][s][:] for s in m.state]
    ar = p if noise_ar is None else noise_ar
    m.noise = [[ar1(rng, days, ar) for _ in range(6)] for _ in range(n_noise_sets)]
    return m


def t3_skill(m: Multi, rng: random.Random, w: float) -> list:
    return [m.full[i] if rng.random() < w else m.b[i] for i in range(m.n_days)]


def t3_null(m: Multi, noise6: list, sd: float) -> list:
    out = []
    for i in range(m.n_days):
        v = [m.b[i][k] * math.exp(sd * noise6[k][i]) for k in range(6)]
        s = sum(v)
        out.append([x / s for x in v])
    return out
