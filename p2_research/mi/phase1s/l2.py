"""Layer L2 (model-fit check): logistic surrogates fitted on an independent synthetic dev draw of the cell and
evaluated on the HLE draw, under the null (noise features carry no information). Protocol l2: null FPR point <= 7.5 %.

c1 = baseline index + 6 noise features (7 features, as T1 M1), c2 = baseline index + the first 2 noise features.
T3 uses a conditional logit: score_k = alpha_k + beta log b_k + sum_j gamma_j x_jk (alpha_0 = 0).
"""
from __future__ import annotations

import math

from . import gen as G
from . import params as PR
from . import rules as RU
from . import stats as S


def _rows(w, n_feat):
    return [[1.0, w.qb[i]] + [w.noise[j][i] for j in range(n_feat)] for i in range(len(w.y))]


def _predict(beta, X):
    return [S.sigmoid(sum(b * x for b, x in zip(beta, row))) for row in X]


def _clogit_fit(Xs, y, max_iter=50, tol=1e-9):
    """Xs[i][k] = feature vector (length p) of class k on day i (alpha dummies included). Newton-Raphson."""
    p = len(Xs[0][0])
    th = [0.0] * p
    for _ in range(max_iter):
        g = [0.0] * p
        H = [[0.0] * p for _ in range(p)]
        for rows, k in zip(Xs, y):
            sc = [sum(t * x for t, x in zip(th, r)) for r in rows]
            mx = max(sc)
            e = [math.exp(s - mx) for s in sc]
            tot = sum(e)
            pr = [v / tot for v in e]
            mean = [sum(pr[c] * rows[c][a] for c in range(6)) for a in range(p)]
            for a in range(p):
                g[a] += rows[k][a] - mean[a]
            for c in range(6):
                rc, pc = rows[c], pr[c]
                for a in range(p):
                    da = pc * (rc[a] - mean[a])
                    if da:
                        Ha = H[a]
                        for b_ in range(a, p):
                            Ha[b_] += da * (rc[b_] - mean[b_])
        for a in range(p):
            for b_ in range(a):
                H[a][b_] = H[b_][a]
        try:
            step = S._solve(H, g)
        except ArithmeticError:
            return th, False
        th = [t + s for t, s in zip(th, step)]
        if max(abs(s) for s in step) < tol:
            return th, True
    return th, False


def _t3_X(m, n_feat):
    out = []
    for i in range(m.n_days):
        rows = []
        for k in range(6):
            dummies = [1.0 if k == c else 0.0 for c in range(1, 6)]
            rows.append(dummies + [math.log(S.clip(m.b[i][k]))] + [m.noise[j][k][i] for j in range(n_feat)])
        out.append(rows)
    return out


def _clogit_predict(th, Xs):
    F = []
    for rows in Xs:
        sc = [sum(t * x for t, x in zip(th, r)) for r in rows]
        mx = max(sc)
        e = [math.exp(s - mx) for s in sc]
        tot = sum(e)
        F.append([v / tot for v in e])
    return F


def run_l2(cell, protocol, rng_train, rng_eval, boot_rng, step):
    sp = RU.step_params(protocol, cell["task"], step)
    if cell["task"] == "T3":
        n1, n2 = PR.GEN["l2_t3_noise_features_c1"], PR.GEN["l2_t3_noise_features_c2"]
        tr = G.t3_world(cell, rng_train, n_noise_sets=n1, noise_ar=float(cell["persistence"]))
        ev = G.t3_world(cell, rng_eval, n_noise_sets=n1, noise_ar=float(cell["persistence"]))
        Xtr, Xev = _t3_X(tr, n1), _t3_X(ev, n1)
        th1, ok1 = _clogit_fit(Xtr, tr.y)
        Xtr2 = [[r[:6 + n2] for r in rows] for rows in Xtr]
        Xev2 = [[r[:6 + n2] for r in rows] for rows in Xev]
        th2, ok2 = _clogit_fit(Xtr2, tr.y)
        F1, F2 = _clogit_predict(th1, Xev), _clogit_predict(th2, Xev2)
        cands = [RU._multi_cand(F1, ev, sp["L"]), RU._multi_cand(F2, ev, sp["L"])]
        r = RU.apply_rule(RU._ctx(ev), RU.brier_multi(ev.b, ev.y), RU.ll_multi(ev.b, ev.y), cands, sp, boot_rng)
    else:
        n1, n2 = PR.GEN["l2_noise_features_c1"], PR.GEN["l2_noise_features_c2"]
        tr = G.binary_world(cell, rng_train, None, n_noise=n1)
        ev = G.binary_world(cell, rng_eval, None, n_noise=n1)
        Xtr, Xev = _rows(tr, n1), _rows(ev, n1)
        b1, ok1 = S.logistic_fit(Xtr, tr.y)
        b2, ok2 = S.logistic_fit([r[:2 + n2] for r in Xtr], tr.y)
        f1, f2 = _predict(b1, Xev), _predict(b2, [r[:2 + n2] for r in Xev])
        cands = [RU._bin_cand(f1, ev, sp["L"]), RU._bin_cand(f2, ev, sp["L"])]
        r = RU.apply_rule(RU._ctx(ev), RU.brier_bin(ev.b, ev.y), RU.ll_bin(ev.b, ev.y), cands, sp, boot_rng)
    # a non-converged surrogate fit is recorded; its forecasts are still evaluated (no silent drop of the rep)
    return {"fp": int(any(r["pass"])), "fp_alt": int(any(r["pass_alt"])), "converged": int(ok1 and ok2)}
