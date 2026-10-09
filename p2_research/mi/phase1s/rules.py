"""Per-rep evaluation of the frozen rules (contract B1, B2, B3) and the five truth classes.

Exactness of short-circuits: p = max(p_boot, p_dm), so a candidate whose p_dm already exceeds the largest level used
(alpha_step) cannot be rejected under any variant; its bootstrap is skipped and its p recorded as None ('> alpha').
B3 on a candidate is evaluated only when it could change a decision (Holm rejection under some variant and B2 true).
Both short-circuits leave every recorded decision identical to the full computation (tested).
"""
from __future__ import annotations

import math

from . import gen as G
from . import params as PR
from . import stats as S

N_TASKS_BONFERRONI = 3


# ============================================================================ losses
def brier_bin(f, y):
    return [(a - b) * (a - b) for a, b in zip(f, y)]


def ll_bin(f, y):
    lg = math.log
    return [-lg(S.clip(a)) if b else -lg(1.0 - S.clip(a)) for a, b in zip(f, y)]


def brier_multi(F, y):
    return [sum(x * x for x in row) - 2.0 * row[k] + 1.0 for row, k in zip(F, y)]


def ll_multi(F, y):
    return [-math.log(S.clip(row[k])) for row, k in zip(F, y)]


def day_sums(rows, day, n_days):
    s = [0.0] * n_days
    for v, d in zip(rows, day):
        s[d] += v
    return s


def b3_clusters(day, n_days, block_days):
    """OD-5: B3 clusters = contiguous blocks of block_days days (the step's mean block length, rounded)."""
    lb = max(1, int(round(block_days)))
    G_ = -(-n_days // lb)
    return [d // lb for d in day], G_, S.t_ppf975(G_ - 1) if G_ > 1 else math.inf


def b3_bin(f, y, day, n_days, block_days):
    cl, G_, crit = b3_clusters(day, n_days, block_days)
    return S.b3_test(f, y, cl, G_, crit)


def b3_multi(F, y, n_days, block_days):
    ff, yy, days = [], [], []
    for i, (row, k) in enumerate(zip(F, y)):
        for c in range(6):
            ff.append(row[c])
            yy.append(1 if c == k else 0)
            days.append(i)
    cl, G_, crit = b3_clusters(days, n_days, block_days)
    return S.b3_test(ff, yy, cl, G_, crit)


# ============================================================================ step parameters
def step_params(protocol: dict, task: str, step: int) -> dict:
    st = protocol["ladder"]["steps"][step]
    if st["k"] != step:
        raise ValueError("ladder step order")
    L = protocol["ladder"]["block_mean_days"][task] * st["block_factor"]
    return {"alpha": float(st["alpha"]), "L": float(L), "B": int(protocol["bootstrap_resamples_synthetic"]),
            "alpha_primary": float(st["alpha"]) / N_TASKS_BONFERRONI, "alpha_alt": float(st["alpha"])}


# ============================================================================ the rule
def apply_rule(ctx: dict, br_b, ll_b, cands: list, sp: dict, boot_rng) -> dict:
    """ctx: day, cnt, n_days; cands: [{'br','ll','b3': callable -> bool reject}]. Returns per-candidate decisions."""
    day, cnt, nd = ctx["day"], ctx["cnt"], ctx["n_days"]
    m = len(cands)
    dsum, pdm, b2 = [], [], []
    nu = S.ewc_nu(nd, sp["L"])
    for c in cands:
        dd = [a - b for a, b in zip(br_b, c["br"])]
        ds = day_sums(dd, day, nd)
        dsum.append(ds)
        pdm.append(S.dm_ewc_pvalue(ds, cnt, nu)[0])
        b2.append(sum(a - b for a, b in zip(ll_b, c["ll"])) > 0)
    need = [j for j in range(m) if pdm[j] <= sp["alpha_alt"]]
    pb = [None] * m
    if need:
        pb = S.sb_pvalues(dsum, cnt, sp["L"], sp["B"], boot_rng, which=need)
    p = [max(pdm[j], pb[j]) if j in need else None for j in range(m)]
    h_pri = S.holm(p, sp["alpha_primary"])
    h_alt = S.holm(p, sp["alpha_alt"])
    b3r = [None] * m
    for j in range(m):
        if h_alt[j] and b2[j]:
            b3r[j] = bool(cands[j]["b3"]())
    pas = [bool(h_pri[j] and b2[j] and b3r[j] is False) for j in range(m)]
    pas_alt = [bool(h_alt[j] and b2[j] and b3r[j] is False) for j in range(m)]
    return {"pass": pas, "pass_alt": pas_alt, "p": p, "pdm": pdm, "pboot": pb, "b2": b2, "b3_reject": b3r, "nu": nu}


def _bin_cand(f, w, L):
    return {"br": brier_bin(f, w.y), "ll": ll_bin(f, w.y),
            "b3": lambda: b3_bin(f, w.y, w.day, w.n_days, L)["reject"]}


def _multi_cand(F, m, L):
    return {"br": brier_multi(F, m.y), "ll": ll_multi(F, m.y), "b3": lambda: b3_multi(F, m.y, m.n_days, L)["reject"]}


def _ctx(w):
    return {"day": w.day, "cnt": w.cnt, "n_days": w.n_days}


def _bss(br_c, br_b):
    sb = sum(br_b)
    return 1.0 - sum(br_c) / sb if sb > 0 else 0.0


# ============================================================================ truth classes
def run_null(cell, protocol, rng, boot_rng, step):
    sp = step_params(protocol, cell["task"], step)
    if cell["task"] == "T3":
        m = G.t3_world(cell, rng, n_noise_sets=2)
        sd = PR.GEN["t3_null_noise_sd"]
        cands = [_multi_cand(G.t3_null(m, m.noise[j], sd), m, sp["L"]) for j in range(2)]
        r = apply_rule(_ctx(m), brier_multi(m.b, m.y), ll_multi(m.b, m.y), cands, sp, boot_rng)
        b3s = b3_multi(m.b, m.y, m.n_days, sp["L"])["reject"]
    else:
        w = G.binary_world(cell, rng, None, n_noise=2)
        sd = PR.GEN["null_noise_sd"]
        cands = [_bin_cand(G.null_forecast(w, w.noise[j], sd), w, sp["L"]) for j in range(2)]
        r = apply_rule(_ctx(w), brier_bin(w.b, w.y), ll_bin(w.b, w.y), cands, sp, boot_rng)
        b3s = b3_bin(w.b_cal, w.y, w.day, w.n_days, sp["L"])["reject"]
    return {"fp": int(any(r["pass"])), "fp_alt": int(any(r["pass_alt"])), "b3_reject": int(b3s),
            "p": r["p"], "pdm": r["pdm"]}


def _skill_world(cell, rng, level, n_noise):
    if cell["task"] == "T3":
        m = G.t3_world(cell, rng, n_noise_sets=n_noise)
        F = G.t3_skill(m, rng, G.t3_w(float(cell["persistence"]), cell["shape"], level))
        return m, F
    kappa = G.kappa_for(float(cell["pi"]), level)
    w = G.binary_world(cell, rng, kappa, n_noise=n_noise)
    return w, G.skill_forecast(w, float(cell["pi"]), kappa)


def run_skill(cell, protocol, rng, boot_rng, step, level):
    sp = step_params(protocol, cell["task"], step)
    w, c1 = _skill_world(cell, rng, level, 1)
    if cell["task"] == "T3":
        c2 = G.t3_null(w, w.noise[0], PR.GEN["t3_null_noise_sd"])
        cands = [_multi_cand(c1, w, sp["L"]), _multi_cand(c2, w, sp["L"])]
        br_b, ll_b = brier_multi(w.b, w.y), ll_multi(w.b, w.y)
    else:
        c2 = G.null_forecast(w, w.noise[0], PR.GEN["null_noise_sd"])
        cands = [_bin_cand(c1, w, sp["L"]), _bin_cand(c2, w, sp["L"])]
        br_b, ll_b = brier_bin(w.b, w.y), ll_bin(w.b, w.y)
    r = apply_rule(_ctx(w), br_b, ll_b, cands, sp, boot_rng)
    return {"pass": int(r["pass"][0]), "pass_alt": int(r["pass_alt"][0]), "bss": _bss(cands[0]["br"], br_b),
            "p": r["p"][0]}


def miscal_transform(f: float, variant: str) -> float:
    kind, val = variant.split("_", 1)
    v = float(val)
    if kind == "slope":
        return S.sigmoid(S.logit(f) / v)
    if kind == "int":
        return S.sigmoid(S.logit(f) - v)
    raise ValueError(variant)


def run_miscal(cell, protocol, rng, variant, step):
    L = step_params(protocol, cell["task"], step)["L"]
    level = protocol["bss_min"][cell["task"]]
    w, c = _skill_world(cell, rng, level, 0)
    if cell["task"] == "T3":
        F = [[miscal_transform(x, variant) for x in row] for row in c]
        rej = b3_multi(F, w.y, w.n_days, L)["reject"]
    else:
        f = [miscal_transform(x, variant) for x in c]
        rej = b3_bin(f, w.y, w.day, w.n_days, L)["reject"]
    return {"reject": int(rej)}


def run_leak(cell, protocol, rng):
    level = protocol["bss_min"][cell["task"]]
    wt = PR.GEN["leak_weight"]
    w, c = _skill_world(cell, rng, level, 0)
    if cell["task"] == "T3":
        F = []
        for row, k in zip(c, w.y):
            v = [math.log(S.clip(x)) + (wt if j == k else 0.0) for j, x in enumerate(row)]
            mx = max(v)
            e = [math.exp(x - mx) for x in v]
            s = sum(e)
            F.append([x / s for x in e])
        return {"bss": _bss(brier_multi(F, w.y), brier_multi(w.b, w.y))}
    f = [S.sigmoid(S.logit(x) + wt * (2 * yy - 1)) for x, yy in zip(c, w.y)]
    return {"bss": _bss(brier_bin(f, w.y), brier_bin(w.b, w.y))}
