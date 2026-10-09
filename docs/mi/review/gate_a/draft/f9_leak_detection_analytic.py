"""DRAFT — NOT APPROVED — NOT FROZEN — NOT EXECUTABLE. Gate A review analysis only (F9): deterministic quadrature,
no sampling, no seeds, no trial records, no runner, no MI CPU budget. Reproduce: python3 <this file> from the repo root.

Method: exact per-row Brier moments of calibrated probit-latent forecasts (frozen generator parameters), integrated by
25-node trapezoid quadrature on +-5 sd (validated: reproduces the analytic skill levels to 5 decimals; 41 nodes gives
identical results to 4 decimals). Realised BSS sd by the delta method; ceiling = exact maximum of independent normals.
Assumptions (all stated in A6): iid rows (deff shown as a variance multiplier); normal approximation of realised BSS;
only no-break non-stress cells (T1 12, T2 15); T3, stress and break cells not computed."""
import math, sys
sys.path.insert(0, '.')
from p2_research.mi.phase1s import gen as G, stats as S
from math import comb
tb, tx = 0.6, 0.6
K = 25
zs = [-5 + 10 * i / (K - 1) for i in range(K)]
w = [math.exp(-z * z / 2) for z in zs]; sw = sum(w); w = [x / sw for x in w]
def moments(pi, kappa, lam):
    d = G.binary_design(pi); mu = d['mu_y']
    tu2 = (1 - kappa) * tx * tx; sk = math.sqrt(kappa) * tx; sl = math.sqrt(lam)
    acc = [0.0] * 6      # E[Bb],E[Bf],E[Bb^2],E[Bf^2],E[BbBf]
    for i, z1 in enumerate(zs):
        u1 = tb * z1; b = S.ncdf((mu + u1) / math.sqrt(1 + tx * tx))
        for j, z2 in enumerate(zs):
            u2 = sk * z2
            for k, z3 in enumerate(zs if lam > 0 else [0.0]):
                wt = w[i] * w[j] * (w[k] if lam > 0 else 1.0)
                f = S.ncdf((mu + u1 + u2 + sl * z3) / math.sqrt(1 + tu2 - lam))
                p = f                                           # calibrated: P(y=1 | info) = f
                bb1, bb0 = (1 - b) ** 2, b * b; ff1, ff0 = (1 - f) ** 2, f * f
                acc[0] += wt * (p * bb1 + (1 - p) * bb0); acc[1] += wt * (p * ff1 + (1 - p) * ff0)
                acc[2] += wt * (p * bb1 ** 2 + (1 - p) * bb0 ** 2); acc[3] += wt * (p * ff1 ** 2 + (1 - p) * ff0 ** 2)
                acc[4] += wt * (p * bb1 * ff1 + (1 - p) * bb0 * ff0)
    return acc
def bss_mean_sd(pi, kappa, lam, n, deff=1.0):
    B, C, B2, C2, BC = moments(pi, kappa, lam)[:5]
    vB, vC, cBC = B2 - B * B, C2 - C * C, BC - B * C
    var = (vC / B ** 2 + C * C * vB / B ** 4 - 2 * C * cBC / B ** 3) * deff / n
    return 1 - C / B, math.sqrt(max(var, 0))
def ceiling_cdf(x, comps):          # comps: list of (mean, sd, count)
    lp = 0.0
    for m, s, c in comps:
        lp += c * math.log(max(S.ncdf((x - m) / s), 1e-300))
    return math.exp(lp)
def p_fire_ge95(p):
    return sum(comb(100, k) * p ** k * (1 - p) ** (100 - k) for k in range(95, 101))
def task(cells, lam_list, deff):
    comps = []
    for pi, n, cnt in cells:
        for lv in ('0.01', '0.02', '0.05'):
            m, s = bss_mean_sd(pi, G.kappa_for(pi, lv), 0.0, n, deff); comps.append((m, s, 200 * cnt))
    xs = [i / 2000 for i in range(0, 1201)]
    F = [ceiling_cdf(x, comps) for x in xs]
    dens = [F[i + 1] - F[i] for i in range(len(F) - 1)]
    med = next(x for x, f in zip(xs, F) if f >= 0.5)
    out = {'ceiling_median': med}
    for lam in lam_list:
        leak = [(pi, n) + bss_mean_sd(pi, G.kappa_for(pi, '0.02'), lam, n, deff) for pi, n, _ in cells]
        pall = 0.0; pworst = 1.0
        for i, dp in enumerate(dens):
            c = 0.5 * (xs[i] + xs[i + 1]); prod = 1.0
            for pi, n, lm, ls in leak:
                prod *= p_fire_ge95(1 - S.ncdf((c - lm) / ls))
            pall += dp * prod
        weakest = min(leak, key=lambda r: r[2] - 1.645 * r[3])
        out[lam] = (round(pall, 4), 'weakest pi=%s n=%s leakBSS=%.3f sd=%.3f' % (weakest[0], weakest[1], weakest[2], weakest[3]))
    return out
T1 = [(0.01, 6204, 4), (0.05, 6204, 4), (0.2, 6204, 4)]            # 12 no-break non-stress cells (iid approx)
T2 = [(pi, n, 2 if not (n == 1500) else 1) for n in (150, 400, 1500) for pi in (0.2, 0.3, 0.5)]   # 15 non-stress
lams = (0.36, 0.6, 1.0)
for deff in (1.0, 3.0):
    print('deff', deff, 'T1', task(T1, lams, deff))
    print('deff', deff, 'T2', task(T2, lams, deff))
