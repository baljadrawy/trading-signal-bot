"""AM-4-A Stage A tests: deterministic engineering / mathematical verification of the offset surrogates.

Offline, bounded, development-only. No frozen 48-cell grid, no task-wide ceiling, no canary fire counting, no
Phase 1S engine, no ledgers. Every expected value comes from ``am4a_oracle`` (independently written formulas), from
closed forms, or from constructed cases whose answer is known by design.
"""
import copy
import hashlib
import json
import math
import os
import random
import re
import tempfile
import unittest

from p2_research.mi.phase1s import am4a_dev as DEV
from p2_research.mi.phase1s import clogit_offset as CL
from p2_research.mi.phase1s import firth as FI
from p2_research.mi.phase1s import gen as G
from p2_research.mi.phase1s import leakfeat as LF
from p2_research.tests import am4a_oracle as OR

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(ROOT, "p2_research", "mi", "phase1s")


def _small_binary(seed=11, n=24, p=2, scale=1.0):
    r = random.Random(seed)
    X = [[r.gauss(0, 1) * scale for _ in range(p)] for _ in range(n)]
    off = [r.gauss(0, 0.7) for _ in range(n)]
    y = [1 if r.random() < OR.mu_of(off[i] + 0.8 * X[i][0] - 0.4 * X[i][1]) else 0 for i in range(n)]
    return X, y, off


def _small_t3(seed=5, n=9, K=6, p=2):
    r = random.Random(seed)
    C = [[[r.gauss(0, 1) for _ in range(p)] for _ in range(K)] for _ in range(n)]
    lb = [[math.log(v / s) for v in row] for row, s in
          ((row, sum(row)) for row in ([r.random() + 0.05 for _ in range(K)] for _ in range(n)))]
    y = [r.randrange(K) for _ in range(n)]
    return C, lb, y


def _rel(a, b):
    return abs(a - b) / max(1.0, abs(a), abs(b))


# ====================================================================== 1-2: objective / score / Hessian vs oracle
class ObjectiveAndDerivatives(unittest.TestCase):
    def test_01_binary_objective_matches_oracle_and_closed_form(self):
        X, y, off = _small_binary()
        for beta in ([0.3, -0.2], [1.5, 0.7], [-2.0, 0.1]):
            ll, llp, mu, L = FI.penalised_loglik(X, y, beta, off)
            self.assertLess(_rel(ll, OR.logit_loglik(X, y, beta, off)), 1e-10)
            self.assertLess(_rel(llp, OR.firth_objective(X, y, beta, off)), 1e-10)
        # closed form: beta = 0, offset = 0 -> mu = 1/2, ll = n log 1/2, I = (1/4) X^T X
        n = len(X)
        ll, llp, mu, L = FI.penalised_loglik(X, y, [0.0, 0.0], None)
        self.assertAlmostEqual(ll, n * math.log(0.5), places=12)
        XtX = [[sum(r[a] * r[b] for r in X) for b in range(2)] for a in range(2)]
        self.assertAlmostEqual(llp - ll, 0.5 * math.log(OR.det([[0.25 * v for v in row] for row in XtX])), places=10)

    def test_02_binary_score_and_information_vs_finite_differences_of_oracle(self):
        X, y, off = _small_binary(seed=3, n=40, p=3)
        for beta in ([0.2, -0.3, 0.5], [1.1, 0.4, -0.9]):
            ll, llp, mu, L = FI.penalised_loglik(X, y, beta, off)
            U = FI.adjusted_score(X, y, mu, L, penalty=True)
            g = OR.numeric_grad(lambda b: OR.firth_objective(X, y, b, off), beta)
            for a, b in zip(U, g):
                self.assertLess(_rel(a, b), 1e-6)
            H = OR.numeric_hessian(lambda b: OR.logit_loglik(X, y, b, off), beta)
            I = FI.information(X, mu)
            for a in range(3):
                for b in range(3):
                    self.assertLess(_rel(I[a][b], -H[a][b]), 1e-5)

    def test_03_clogit_objective_score_information_vs_oracle(self):
        C, lb, y = _small_t3()
        for theta in ([0.3, -0.5], [1.2, 0.4]):
            ll, U, I = CL.score_info(C, lb, y, theta)
            self.assertLess(_rel(ll, OR.clogit_loglik(C, lb, y, theta)), 1e-10)
            self.assertLess(_rel(CL.loglik(C, lb, y, theta), ll), 1e-12)
            g = OR.numeric_grad(lambda t: OR.clogit_loglik(C, lb, y, t), theta)
            for a, b in zip(U, g):
                self.assertLess(_rel(a, b), 1e-6)
            H = OR.numeric_hessian(lambda t: OR.clogit_loglik(C, lb, y, t), theta)
            for a in range(2):
                for b in range(2):
                    self.assertLess(_rel(I[a][b], -H[a][b]), 1e-5)

    def test_04_worked_examples_solved_independently(self):
        # Firth, p = 1 with offset: root of the oracle's adjusted score (bisection) and the golden-section maximiser
        # of the oracle objective must both equal the implementation's fit.
        r = random.Random(7)
        X = [[r.gauss(0, 1)] for _ in range(12)]
        off = [r.gauss(0, 0.5) for _ in range(12)]
        y = [1 if r.random() < OR.mu_of(off[i] + 1.0 * X[i][0]) else 0 for i in range(12)]
        # tol_grad bounds the score, not beta: |beta_hat - root| <= tol_grad / I*. With the default 1e-8 and a
        # 12-point design (I* ~ 0.5) that is ~2e-8, so the worked example is run at tol_grad = 1e-12 (the solver
        # must reach the independent root when asked) and the default-tolerance fit is checked at 1e-6.
        fit = FI.firth_fit(X, y, off, tol_grad=1e-10)
        self.assertEqual(fit.status, "CONVERGED")
        root = OR.bisect_root(lambda b: OR.firth_adjusted_score_1d(X, y, [b], off), -8.0, 8.0)
        gold = OR.golden_max(lambda b: OR.firth_objective(X, y, [b], off), -8.0, 8.0)
        self.assertAlmostEqual(fit.beta[0], root, places=8)
        self.assertAlmostEqual(fit.beta[0], gold, places=6)
        self.assertAlmostEqual(FI.firth_fit(X, y, off).beta[0], root, places=6)
        # conditional logit, p = 1, K = 6: golden-section maximiser of the oracle log-likelihood
        C, lb, yy = _small_t3(seed=9, n=12, K=6, p=1)
        cf = CL.clogit_fit(C, lb, yy)
        self.assertEqual(cf.status, "CONVERGED")
        gold2 = OR.golden_max(lambda t: OR.clogit_loglik(C, lb, yy, [t]), -8.0, 8.0)
        self.assertAlmostEqual(cf.beta[0], gold2, places=6)


# ====================================================================== 3-4: fixed offsets, normalisation
class OffsetsAndNormalisation(unittest.TestCase):
    def test_05_offset_coefficient_is_exactly_one_and_not_estimated(self):
        X, y, off = _small_binary(seed=21, n=30)
        f = FI.firth_fit(X, y, off)
        self.assertEqual(len(f.beta), 2)                      # no intercept, no baseline coefficient
        # shifting every offset by c shifts every logit by exactly c at fixed beta
        p1 = FI.predict(X, f.beta, off)
        p2 = FI.predict(X, f.beta, [o + 0.37 for o in off])
        for a, b in zip(p1, p2):
            self.assertAlmostEqual(math.log(b / (1 - b)) - math.log(a / (1 - a)), 0.37, places=9)
        # a different offset changes the fit: the offset is used, not absorbed by any free parameter
        f2 = FI.firth_fit(X, y, [2.0 * o for o in off])
        self.assertNotAlmostEqual(f.beta[0], f2.beta[0], places=6)
        # T3: no class constants, theta has exactly p entries; doubling log b changes the fit
        C, lb, yy = _small_t3(seed=4, n=14)
        c1 = CL.clogit_fit(C, lb, yy)
        c2 = CL.clogit_fit(C, [[2 * v for v in row] for row in lb], yy)
        self.assertEqual(len(c1.beta), 2)
        self.assertNotAlmostEqual(c1.beta[0], c2.beta[0], places=6)

    def test_06_probabilities_normalise_and_stay_in_bounds(self):
        C, lb, yy = _small_t3(seed=2, n=20)
        for row in CL.predict(C, lb, [0.7, -1.3]):
            self.assertEqual(len(row), 6)
            self.assertAlmostEqual(sum(row), 1.0, places=12)
            self.assertTrue(all(v > 0 for v in row))
        X, y, off = _small_binary(seed=8)
        for v in FI.predict(X, [40.0, -40.0], [o * 50 for o in off]):
            self.assertTrue(FI.EPS <= v <= 1 - FI.EPS)
            self.assertTrue(math.isfinite(v))


# ====================================================================== 5-6: T3 uniform baseline, missing class
class T3Behaviour(unittest.TestCase):
    def test_07_uniform_baseline_cell_is_identified_and_converges(self):
        DEV.reset_seed_registry()
        fx = DEV.t3_fixture("T07", "p0.85-uniform", 0, 0.85, "uniform", 400)
        d = fx["dev"]
        self.assertIsNone(d["lag"])                                            # climatology baseline (frozen design)
        self.assertTrue(all(max(r) - min(r) < 1e-15 for r in d["logb"]))     # offset constant across alternatives
        ll, U, I = CL.score_info(d["C"], d["logb"], d["y"], [0.0] * 7)
        L = FI.cholesky(I)                                                     # identified at theta = 0
        self.assertTrue(math.isfinite(FI.chol_cond_estimate(L)))
        fit = CL.clogit_fit(d["C"], d["logb"], d["y"])
        self.assertEqual(fit.status, "CONVERGED")
        self.assertTrue(all(math.isfinite(t) for t in fit.beta))

    def test_08_missing_class_keeps_all_six_alternatives_and_converges(self):
        r = random.Random(31)
        n, K = 300, 6
        y = [r.randrange(K - 1) for _ in range(n)]                             # class 5 never occurs in the dev draw
        self.assertNotIn(5, y)
        x = [[2.0 * (1.0 if k == yy else 0.0) + r.gauss(0, 1) for k in range(K)] for yy in y]
        z = [[[r.gauss(0, 1) for _ in range(n)] for _ in range(K)]]
        C = LF.t3_design(x, z)
        lb = [[math.log(1.0 / K)] * K for _ in range(n)]
        fit = CL.clogit_fit(C, lb, y)
        self.assertEqual(fit.status, "CONVERGED")
        self.assertEqual(len(fit.beta), 2)
        # an evaluation day where class 5 is the truth still gets a positive, finite probability for class 5
        xe = [[2.0 * (1.0 if k == 5 else 0.0) + r.gauss(0, 1) for k in range(K)]]
        Ce = LF.t3_design(xe, [[[r.gauss(0, 1)] for _ in range(K)]])
        pe = CL.predict(Ce, [[math.log(1.0 / K)] * K], fit.beta)[0]
        self.assertEqual(len(pe), 6)
        self.assertGreater(pe[5], 0.0)
        self.assertAlmostEqual(sum(pe), 1.0, places=12)


# ====================================================================== 7-10: separation, singularity, caps
class SeparationAndFailures(unittest.TestCase):
    def _separable(self):
        X = [[float(i) - 9.5] for i in range(20)]
        y = [1 if i >= 10 else 0 for i in range(20)]
        return X, y

    def test_09_complete_separation_firth_finite_ml_flagged(self):
        X, y = self._separable()
        f = FI.firth_fit(X, y, None)
        self.assertEqual(f.status, "CONVERGED")
        self.assertTrue(all(math.isfinite(b) and abs(b) < 20 for b in f.beta))
        d = FI.ml_separation_diagnostic(X, y, None)
        self.assertTrue(d["separation_detected"])
        # Heinze 2006: under separation the likelihood meets convergence criteria while estimates diverge; the
        # unpenalised comparator must therefore report DIVERGED (finite iterate, no MLE), never CONVERGED
        self.assertEqual(d["ml_status"], "DIVERGED")
        self.assertGreaterEqual(d["ml_max_abs_coef"], FI.ML_SEPARATION_COEF)

    def test_10_near_separation_converges_finite(self):
        X, y = self._separable()
        y = list(y); y[10], y[9] = 0, 1                                        # one overlapping pair
        f = FI.firth_fit(X, y, None)
        self.assertEqual(f.status, "CONVERGED")
        self.assertTrue(all(math.isfinite(b) for b in f.beta))
        self.assertTrue(math.isfinite(f.cond_estimate))

    def test_11_singular_information_detected(self):
        X, y, off = _small_binary(seed=12, n=30)
        Xdup = [r + [r[0]] for r in X]                                         # duplicate column
        f = FI.firth_fit(Xdup, y, off)
        self.assertEqual(f.status, "NUMERICAL_FAIL")
        self.assertIn("singular", f.message)
        Xzero = [r + [0.0] for r in X]                                         # zero column
        self.assertEqual(FI.firth_fit(Xzero, y, off).status, "NUMERICAL_FAIL")
        C, lb, yy = _small_t3(seed=6, n=12)
        Cc = [[r + [1.0] for r in rows] for rows in C]                         # alternative-constant covariate
        self.assertEqual(CL.clogit_fit(Cc, lb, yy).status, "NUMERICAL_FAIL")

    def test_12_iteration_cap_is_classified_not_converged(self):
        X, y, off = _small_binary(seed=15, n=40)
        f = FI.firth_fit(X, y, off, max_iter=1)
        self.assertEqual(f.status, "ITER_CAP")
        C, lb, yy = _small_t3(seed=16, n=20)
        self.assertEqual(CL.clogit_fit(C, lb, yy, max_iter=1).status, "ITER_CAP")


# ====================================================================== 11-12: monotonicity, overflow
class NumericalBehaviour(unittest.TestCase):
    def test_13_line_search_is_monotone(self):
        X, y, off = _small_binary(seed=17, n=50, p=3, scale=3.0)
        f = FI.firth_fit(X, y, off)
        self.assertEqual(f.status, "CONVERGED")
        for a, b in zip(f.trace, f.trace[1:]):
            self.assertGreaterEqual(b, a - 1e-12)
        C, lb, yy = _small_t3(seed=18, n=25)
        c = CL.clogit_fit(C, lb, yy)
        for a, b in zip(c.trace, c.trace[1:]):
            self.assertGreaterEqual(b, a - 1e-12)

    def test_14_overflow_and_underflow_are_handled(self):
        X, y, off = _small_binary(seed=19, n=30)
        big = [o * 400 for o in off]                                           # |offset| up to ~1000
        ll, llp, mu, L = FI.penalised_loglik(X, y, [0.1, -0.1], big)
        self.assertTrue(math.isfinite(ll))
        self.assertTrue(all(0.0 <= m <= 1.0 for m in mu))
        for v in FI.predict(X, [800.0, -800.0], big):
            self.assertTrue(FI.EPS <= v <= 1 - FI.EPS)
        self.assertAlmostEqual(FI.log_sigmoid(800.0), 0.0, places=15)
        self.assertAlmostEqual(FI.log_sigmoid(-800.0), -800.0, places=9)
        C, lb, yy = _small_t3(seed=20, n=10)
        lbb = [[v * 300 for v in row] for row in lb]
        for row in CL.predict(C, lbb, [500.0, -500.0]):
            self.assertAlmostEqual(sum(row), 1.0, places=12)
            self.assertTrue(all(math.isfinite(v) for v in row))


# ====================================================================== 13-14: replay, seeds
class ReplayAndSeeds(unittest.TestCase):
    def test_15_byte_identical_replay_of_a_fixture(self):
        def run():
            DEV.reset_seed_registry()
            fx = DEV.binary_fixture("T15", "replay", 0, 300, 0.3)
            f = FI.firth_fit(fx["dev"]["X"], fx["dev"]["y"], fx["dev"]["offset"])
            return json.dumps({"beta": f.beta, "status": f.status, "pred": FI.predict(fx["eval"]["X"], f.beta,
                                                                                      fx["eval"]["offset"])[:50]},
                              sort_keys=True)
        a, b = run(), run()
        self.assertEqual(hashlib.sha256(a.encode()).hexdigest(), hashlib.sha256(b.encode()).hexdigest())

    def test_16_seed_namespace_is_separate_and_duplicates_are_detected(self):
        DEV.reset_seed_registry()
        s = DEV.seed_hex("T16", "case", 0, "dev")
        self.assertEqual(len(s), 16)
        self.assertNotEqual(s, G.seed_hex("fdf33664", "T16", "case", "0", 0, "dev"))
        self.assertNotEqual(DEV.seed_hex("T16", "case", 0, "eval"), s)
        with self.assertRaises(ValueError):
            DEV.seed_hex("T16", "case", 0, "dev")
        # leak noise streams differ between dev and eval roles
        DEV.reset_seed_registry()
        fx = DEV.binary_fixture("T16", "roles", 0, 50, 0.3)
        self.assertNotEqual([r[0] for r in fx["dev"]["X"]], [r[0] for r in fx["eval"]["X"]])


# ====================================================================== 15: Brier, feature construction, isolation
class ScoresFeaturesIsolation(unittest.TestCase):
    def test_17_brier_arithmetic_matches_oracle_and_ranges(self):
        r = random.Random(23)
        f = [r.random() for _ in range(40)]
        y = [r.randrange(2) for _ in range(40)]
        self.assertAlmostEqual(DEV.brier_bin(f, y), OR.brier_bin_expanded(f, y), places=14)
        F = []
        for _ in range(30):
            v = [r.random() for _ in range(6)]; s = sum(v); F.append([x / s for x in v])
        yy = [r.randrange(6) for _ in range(30)]
        self.assertAlmostEqual(DEV.brier_multi(F, yy), OR.brier_multi_expanded(F, yy), places=14)
        self.assertTrue(0.0 <= DEV.brier_multi(F, yy) <= 2.0)
        self.assertEqual(DEV.bss(0.5, 1.0), 0.5)
        self.assertEqual(DEV.bss(0.5, 0.0), 0.0)

    def test_18_leak_feature_construction(self):
        rr = G.rng_from("0123456789abcdef")
        y = [1, 0, 1, 1, 0] * 200
        x = LF.leak_feature_binary(rr, y)
        m1 = sum(v for v, yy in zip(x, y) if yy) / sum(y)
        m0 = sum(v for v, yy in zip(x, y) if not yy) / (len(y) - sum(y))
        self.assertAlmostEqual(m1, 2.0, delta=0.15)
        self.assertAlmostEqual(m0, -2.0, delta=0.15)
        self.assertEqual(LF.W_F, 2.0)
        rows = LF.leak_feature_multi(G.rng_from("fedcba9876543210"), [3] * 500)
        self.assertTrue(all(len(r) == 6 for r in rows))
        self.assertAlmostEqual(sum(r[3] for r in rows) / 500, 2.0, delta=0.15)
        self.assertAlmostEqual(sum(r[0] for r in rows) / 500, 0.0, delta=0.15)

    def test_19_stage_a_modules_are_unwired_and_import_only_allowed_modules(self):
        pat = re.compile(r"from \. import (engine|rules|l2|sandbox|store|release|__main__)|import (engine|rules)\b")
        for f in ("firth.py", "clogit_offset.py", "leakfeat.py", "am4a_dev.py"):
            with open(os.path.join(PKG, f), encoding="utf-8") as fh:
                src = fh.read()
            self.assertIsNone(pat.search(src), f)
            self.assertNotIn("subprocess", src)
            self.assertNotIn("sqlite", src)
        import ast
        with open(os.path.join(ROOT, "p2_research", "tests", "am4a_oracle.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        mods = sorted({n.names[0].name if isinstance(n, ast.Import) else n.module
                       for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))})
        self.assertEqual(mods, ["__future__", "decimal", "math"])
        # the harness never touches the frozen grid or the ceiling
        with open(os.path.join(PKG, "am4a_dev.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("trip_wire", src)
        self.assertNotIn("fire_count", src)


# ====================================================================== Hardening r2 (owner directive 2026-10-10): H1-H5
class HardeningR2(unittest.TestCase):
    def _fixture(self, seed=41, n=1000, p=2):
        r = random.Random(seed)
        X = [[r.gauss(0, 1) for _ in range(p)] for _ in range(n)]
        off = [r.gauss(0, 0.7) for _ in range(n)]
        y = [1 if r.random() < OR.mu_of(off[i] + 0.8 * X[i][0] - 0.4 * X[i][1]) else 0 for i in range(n)]
        return X, y, off

    def test_h1_fp_floor_is_reached_disclosed_and_never_counted_as_success(self):
        # Natural fixture: the strict acceptance rule (ls_tol = 0.0, accept only non-decreasing trial objectives)
        # with a gradient tolerance below the floating-point floor. No internal state is manipulated.
        X, y, off = self._fixture()
        r = FI.firth_fit(X, y, off, tol_grad=1e-14, ls_tol=0.0)
        self.assertEqual(r.status, "FP_FLOOR")
        self.assertNotEqual(r.status, "CONVERGED")
        self.assertTrue(all(math.isfinite(b) for b in r.beta))
        self.assertTrue(math.isfinite(r.loglik_pen) and math.isfinite(r.grad_norm))
        self.assertLess(r.grad_norm, FI.FP_FLOOR_GRAD)
        self.assertGreaterEqual(r.grad_norm, 1e-14)
        self.assertIn("resolution floor", r.message)
        self.assertIn("%.3e" % r.grad_norm, r.message)                      # termination reason discloses the gradient
        self.assertLessEqual(r.predicted_gain, FI.ls_tolerance(r.loglik_pen, len(X)))   # r3: gain below intrinsic noise
        self.assertEqual(r.ls_tol_used, 0.0)                                 # strict acceptance override recorded
        # propagation boundary: the harness never counts it as success and records the status verbatim
        self.assertFalse(DEV.fit_is_success(r))
        rec = DEV.fit_record(r)
        self.assertEqual((rec["status"], rec["success"]), ("FP_FLOOR", False))
        self.assertEqual(rec["message"], r.message)
        self.assertEqual(DEV.SUCCESS_STATUSES, ("CONVERGED",))
        # the same fixture under the scale-aware default rule converges: the floor is a property of the strict rule,
        # not a defect of the optimum
        r2 = FI.firth_fit(X, y, off, tol_grad=1e-14)
        self.assertEqual(r2.status, "CONVERGED")
        self.assertLess(max(abs(a - b) for a, b in zip(r.beta, r2.beta)), 1e-6)

    def test_h2_inverse_diag_and_standard_errors_vs_independent_inverse(self):
        A = [[4.0, 1.0, 0.5], [1.0, 3.0, 0.2], [0.5, 0.2, 2.0]]
        L = FI.cholesky(A)
        inv = OR.inverse_cofactor(A)
        for a, b in zip(FI.inverse_diag(L), [inv[i][i] for i in range(3)]):
            self.assertLess(abs(a - b), 1e-12)
            self.assertGreater(a, 0.0)
        # 2x2 closed form: inverse diag of [[a,b],[b,c]] = (c, a) / (ac - b^2)
        L2 = FI.cholesky([[5.0, 2.0], [2.0, 3.0]])
        d = FI.inverse_diag(L2)
        self.assertAlmostEqual(d[0], 3.0 / 11.0, places=14)
        self.assertAlmostEqual(d[1], 5.0 / 11.0, places=14)
        # standard errors vs sqrt(diag(I^-1)) with I from the oracle's own information and cofactor inverse
        X, y, off = _small_binary(seed=33, n=60, p=3)
        beta = [0.4, -0.2, 0.1]
        se = FI.standard_errors(X, beta, off)
        Iinv = OR.inverse_cofactor(OR.fisher_info(X, y, beta, off))
        for a, j in zip(se, range(3)):
            self.assertLess(abs(a - math.sqrt(Iinv[j][j])) / a, 1e-10)
            self.assertTrue(math.isfinite(a) and a > 0)
        # parameter ordering: permuting the columns permutes the SEs
        Xp = [[r[2], r[0], r[1]] for r in X]
        sep = FI.standard_errors(Xp, [beta[2], beta[0], beta[1]], off)
        self.assertAlmostEqual(sep[0], se[2], places=12)
        self.assertAlmostEqual(sep[1], se[0], places=12)
        self.assertAlmostEqual(sep[2], se[1], places=12)
        # non-positive-definite and near-singular matrices are refused, never silently inverted
        with self.assertRaises(FI.SingularError):
            FI.cholesky([[1.0, 2.0], [2.0, 1.0]])
        with self.assertRaises(FI.SingularError):
            FI.cholesky([[1.0, 1.0], [1.0, 1.0 + 1e-14]])
        with self.assertRaises(FI.SingularError):
            FI.standard_errors([r + [r[0]] for r in X], beta + [0.0], off)

    def test_h3_line_search_singular_branch_rejects_trial_without_corrupting_iterate(self):
        X, y, off = _small_binary(seed=27, n=40, p=2)
        calls = {"n": 0}

        def inject_once(Xa, ya, b, o, pen):                      # documented fault-injection seam
            calls["n"] += 1
            if calls["n"] == 2:                                   # the first TRIAL point (call 1 is the start point)
                raise FI.SingularError("injected singular information at trial point")
            return FI.penalised_loglik(Xa, ya, b, o, pen)

        r = FI.firth_fit(X, y, off, objective=inject_once)
        ref = FI.firth_fit(X, y, off)
        self.assertEqual(r.status, "CONVERGED")
        self.assertGreaterEqual(r.halvings_total, 1)              # the invalid full step was rejected and halved
        self.assertLess(max(abs(a - b) for a, b in zip(r.beta, ref.beta)), 1e-7)
        for a, b in zip(r.trace, r.trace[1:]):                   # no invalid trial entered the accepted trace
            self.assertGreaterEqual(b, a - FI.ls_tolerance(a, len(X)))

        def always_fail_trials(Xa, ya, b, o, pen):
            calls["m"] = calls.get("m", 0) + 1
            if calls["m"] > 1:
                raise FI.SingularError("injected: every trial point singular")
            return FI.penalised_loglik(Xa, ya, b, o, pen)

        r3 = FI.firth_fit(X, y, off, objective=always_fail_trials)
        self.assertEqual(r3.status, "NUMERICAL_FAIL")             # large gradient + no valid step: never CONVERGED
        self.assertEqual(r3.beta, [0.0, 0.0])                     # the last valid iterate (the start) is untouched
        self.assertEqual(r3.halvings_total, FI.MAX_HALVINGS + 1)
        self.assertIn("stalled", r3.message)
        self.assertFalse(DEV.fit_is_success(r3))

    def test_h4_offset_clipping_policy_and_non_finite_rejection(self):
        e = FI.EPS
        lo, hi = math.log(e / (1 - e)), math.log((1 - e) / e)
        cases = [(0.0, lo), (1e-13, lo), (e, lo), (2e-12, math.log(2e-12 / (1 - 2e-12))),
                 (1 - 2e-12, math.log((1 - 2e-12) / 2e-12)), (1 - e, hi), (1.0, hi), (1.5, hi)]
        for p, expect in cases:
            v = LF.logit_clipped(p)
            self.assertTrue(math.isfinite(v), p)
            # Disclosed numerical property: near the UPPER boundary the logit inherits the cancellation error of
            # 1 - p, bounded by u / (1 - p) (u = 1.1e-16), i.e. up to ~5.5e-5 at p = 1 - 2e-12; it is a property of the
            # double representation of p itself, not of the clipping policy. Near the lower boundary there is no
            # cancellation (1e-9 tolerance). T1/T2 baselines (pi <= 0.5) never approach the upper boundary.
            self.assertAlmostEqual(v, expect, delta=1e-4 if p > 0.5 else 1e-9)
        self.assertAlmostEqual(LF.log_clipped(0.0), math.log(e), places=12)
        self.assertAlmostEqual(LF.log_clipped(1.5), math.log(1 - e), places=12)
        self.assertEqual(LF.log_clipped(0.3), math.log(0.3))
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                LF.logit_clipped(bad)
            with self.assertRaises(ValueError):
                LF.log_clipped(bad)
            with self.assertRaises(ValueError):
                LF.binary_offset([0.2, bad])
        # clipped offsets still enter with coefficient exactly 1 and are never fitted
        X, y, off0 = _small_binary(seed=29, n=30)
        off = LF.binary_offset([0.0, 1.0] + [0.3] * 28)                   # both boundaries clipped
        f = FI.firth_fit(X, y, off)
        self.assertEqual(len(f.beta), 2)
        p1 = FI.predict(X, f.beta, off)
        p2 = FI.predict(X, f.beta, [o + 0.25 for o in off])
        # rows 0 and 1 carry boundary offsets (+-27.6): their predictions are clipped to [EPS, 1 - EPS], so the
        # exact-shift identity cannot hold there (disclosed safeguard); every interior row shifts by exactly 0.25
        for i in (0, 1):
            self.assertTrue(FI.EPS <= p1[i] <= 1 - FI.EPS and FI.EPS <= p2[i] <= 1 - FI.EPS)
        for a, b in list(zip(p1, p2))[2:]:
            self.assertAlmostEqual(math.log(b / (1 - b)) - math.log(a / (1 - a)), 0.25, places=8)

    def test_h5_scale_aware_acceptance_never_accepts_material_decreases(self):
        # tolerance values: tiny at small n, still tiny relative to the objective at large n
        self.assertLess(FI.ls_tolerance(-15.0, 24), 1e-13)
        self.assertLess(FI.ls_tolerance(-2300.0, 4000), 2e-10)
        self.assertLess(FI.ls_tolerance(-1e4, 20000), 1e-8)
        self.assertGreater(FI.ls_tolerance(-2300.0, 4000), 1e-12)        # looser than the old absolute rule there
        X, y, off = _small_binary(seed=35, n=40, p=2)
        calls = {"n": 0}

        def decreasing_trials(Xa, ya, b, o, pen):
            # every trial objective is reported 1e-6 BELOW the current (start) objective: a material decrease
            calls["n"] += 1
            ll, llp, mu, L = FI.penalised_loglik(Xa, ya, b, o, pen)
            if calls["n"] == 1:
                calls["llp0"] = llp
                return ll, llp, mu, L
            return ll, calls["llp0"] - 1e-6, mu, L

        r = FI.firth_fit(X, y, off, objective=decreasing_trials)
        self.assertEqual(r.status, "NUMERICAL_FAIL")             # material decreases are never accepted
        self.assertNotEqual(r.status, "CONVERGED")
        self.assertEqual(r.beta, [0.0, 0.0])
        # large magnitude: a 4000-row fit converges with zero halvings under the scale-aware rule
        Xb, yb, offb = self._fixture(seed=43, n=4000, p=3)
        rb = FI.firth_fit(Xb, yb, offb)
        self.assertEqual(rb.status, "CONVERGED")
        self.assertEqual(rb.halvings_total, 0)
        for a, b in zip(rb.trace, rb.trace[1:]):
            self.assertGreaterEqual(b, a - FI.ls_tolerance(a, 4000))
        # the strict rule on the same problem does not produce false convergence either
        rs = FI.firth_fit(Xb, yb, offb, ls_tol=0.0)
        self.assertIn(rs.status, ("CONVERGED", "FP_FLOOR", "ITER_CAP"))
        if rs.status == "CONVERGED":
            self.assertLess(rs.grad_norm, FI.TOL_GRAD)
        # conditional logit uses the same scale-aware rule
        C, lb, yy = _small_t3(seed=37, n=30)
        c = CL.clogit_fit(C, lb, yy)
        self.assertEqual(c.status, "CONVERGED")
        for a, b in zip(c.trace, c.trace[1:]):
            self.assertGreaterEqual(b, a - FI.ls_tolerance(a, 30))


# ====================================================================== Numerical audit r3 (owner directive): H5 and FP_FLOOR
class NumericalAuditR3(unittest.TestCase):
    """High-precision (decimal, 50 digits) verification of the acceptance rule and of the FP_FLOOR classification on
    constructed cases only (no frozen cell)."""

    @classmethod
    def setUpClass(cls):
        r = random.Random(41)
        n = 1000
        cls.X = [[r.gauss(0, 1) for _ in range(2)] for _ in range(n)]
        cls.off = [r.gauss(0, 0.7) for _ in range(n)]
        cls.y = [1 if r.random() < OR.mu_of(cls.off[i] + 0.8 * cls.X[i][0] - 0.4 * cls.X[i][1]) else 0 for i in range(n)]
        cls.floor = FI.firth_fit(cls.X, cls.y, cls.off, tol_grad=1e-14, ls_tol=0.0)

    def test_r3_01_decimal_oracle_selfcheck_and_float_error_magnitude(self):
        self.assertLess(float(OR.dec_selfcheck()), 1e-45)
        X, y, off = _small_binary(seed=3, n=40, p=2)
        for beta in ([0.2, -0.3], [1.1, 0.4]):
            f = FI.penalised_loglik(X, y, beta, off)[1]
            d = OR.dec_firth_objective(X, y, beta, off)
            self.assertLess(abs(float(OR.D(f) - d)), 1e-13)             # small n: error well below 1e-13
        f = FI.penalised_loglik(self.X, self.y, self.floor.beta, self.off)[1]
        d = OR.dec_firth_objective(self.X, self.y, self.floor.beta, self.off)
        err = abs(float(OR.D(f) - d))
        self.assertLess(err, FI.ls_tolerance(f, len(self.X)))              # n = 1000: within the scale-aware tolerance
        self.assertGreater(err, 1e-15)                                    # and genuinely non-zero (float noise exists)

    def test_r3_02_fp_floor_root_cause_true_ascent_below_float_resolution(self):
        r = self.floor
        self.assertEqual(r.status, "FP_FLOOR")
        self.assertLessEqual(r.predicted_gain, FI.ls_tolerance(r.loglik_pen, len(self.X)))
        self.assertLess(r.cond_estimate, 2.0)                             # not ill-conditioning
        self.assertAlmostEqual(r.grad_norm, 2.6880850551025404e-07, delta=1e-12)   # r2 regression anchor
        self.assertEqual((r.iterations, r.halvings_total), (8, 49))
        ll, llp, mu, L = FI.penalised_loglik(self.X, self.y, r.beta, self.off)
        U = FI.adjusted_score(self.X, self.y, mu, L)
        delta = FI.chol_solve(L, U)
        self.assertGreater(sum(u * d for u, d in zip(U, delta)), 0.0)    # Fisher step is an ascent direction
        d0 = OR.dec_firth_objective(self.X, self.y, r.beta, self.off)
        # both signs of a near-zero TRUE change, resolved only by the high-precision oracle:
        plus = [b + d for b, d in zip(r.beta, delta)]                     # along the ascent direction
        minus = [b - d for b, d in zip(r.beta, delta)]                    # against it
        dplus = float(OR.dec_firth_objective(self.X, self.y, plus, self.off) - d0)
        dminus = float(OR.dec_firth_objective(self.X, self.y, minus, self.off) - d0)
        self.assertGreater(dplus, 0.0)
        self.assertLess(dminus, 0.0)
        self.assertLess(abs(dplus), 1e-14)                                # true gain ~ predicted 4e-16, unresolvable
        fplus = FI.penalised_loglik(self.X, self.y, plus, self.off)[1] - llp
        self.assertLess(abs(fplus), FI.ls_tolerance(llp, len(self.X)))                         # float change is within the noise band
        self.assertLess(fplus, 0.0)                                       # and here float reports a (false) decrease
        self.assertFalse(DEV.fit_is_success(r))
        rec = DEV.fit_record(r)
        self.assertEqual((rec["status"], rec["success"]), ("FP_FLOOR", False))
        self.assertEqual(rec["predicted_gain"], r.predicted_gain)

    def test_r3_03_stalled_search_with_resolvable_gain_is_numerical_fail(self):
        X, y, off = _small_binary(seed=35, n=40, p=2)
        calls = {"n": 0}

        def decreasing_trials(Xa, ya, b, o, pen):
            calls["n"] += 1
            ll, llp, mu, L = FI.penalised_loglik(Xa, ya, b, o, pen)
            if calls["n"] == 1:
                calls["llp0"] = llp
                return ll, llp, mu, L
            return ll, calls["llp0"] - 1e-6, mu, L

        r = FI.firth_fit(X, y, off, objective=decreasing_trials)
        self.assertEqual(r.status, "NUMERICAL_FAIL")
        self.assertIn("line search stalled", r.message)
        self.assertGreater(r.predicted_gain, r.ls_tol_used)               # gain was resolvable: not a floor
        self.assertEqual(r.beta, [0.0, 0.0])

    def test_r3_04_cumulative_drift_is_detected_not_accumulated(self):
        X, y, off = _small_binary(seed=36, n=40, p=2)
        state = {"n": 0}

        def drifting_trials(Xa, ya, b, o, pen):
            # every trial objective is reported 0.9 * ls_tol BELOW the previous accepted value: each step is
            # individually within the noise band, so it is accepted; the drift guard must stop the accumulation
            state["n"] += 1
            ll, llp, mu, L = FI.penalised_loglik(Xa, ya, b, o, pen)
            if state["n"] == 1:
                state["last"] = llp
                return ll, llp, mu, L
            fake = state["last"] - 0.9 * FI.ls_tolerance(state["last"], len(Xa))
            state["last"] = fake
            return ll, fake, mu, L

        r = FI.firth_fit(X, y, off, objective=drifting_trials, tol_grad=0.0)
        self.assertEqual(r.status, "NUMERICAL_FAIL")
        self.assertIn("cumulative objective drift", r.message)
        self.assertLessEqual(r.iterations, int(FI.DRIFT_FACTOR / 0.9) + 2)
        self.assertGreater(r.best_objective - r.loglik_pen, FI.DRIFT_FACTOR * r.ls_tol_used)
        self.assertFalse(DEV.fit_is_success(r))

    def test_r3_05_genuine_improvements_accepted_and_valid(self):
        X, y, off = self._fixture4000()
        r = FI.firth_fit(X, y, off)
        self.assertEqual(r.status, "CONVERGED")
        self.assertEqual(r.halvings_total, 0)
        self.assertGreater(r.predicted_gain, 0.0)
        self.assertEqual(r.best_objective, max(r.trace))
        for a, b in zip(r.trace, r.trace[1:]):
            self.assertGreaterEqual(b, a - FI.ls_tolerance(a, len(X)))
        for v in FI.predict(X, r.beta, off):
            self.assertTrue(FI.EPS <= v <= 1 - FI.EPS)
        # large-magnitude objective: float error vs decimal is within the scale-aware tolerance (checked on the
        # first 400 rows only, to bound oracle cost)
        Xs, ys, offs = X[:400], y[:400], off[:400]
        f = FI.penalised_loglik(Xs, ys, r.beta, offs)[1]
        self.assertLess(abs(float(OR.D(f) - OR.dec_firth_objective(Xs, ys, r.beta, offs))),
                        FI.ls_tolerance(f, 400))

    def _fixture4000(self):
        r = random.Random(43)
        n = 4000
        X = [[r.gauss(0, 1) for _ in range(3)] for _ in range(n)]
        off = [r.gauss(0, 0.7) for _ in range(n)]
        y = [1 if r.random() < OR.mu_of(off[i] + 0.8 * X[i][0] - 0.4 * X[i][1]) else 0 for i in range(n)]
        return X, y, off

    def test_r3_06_same_policy_in_conditional_logit_with_decimal_check(self):
        rr = random.Random(45)
        n, K, p = 600, 6, 2
        C = [[[rr.gauss(0, 1) for _ in range(p)] for _ in range(K)] for _ in range(n)]
        lb = [[math.log(1.0 / K)] * K for _ in range(n)]
        yy = [rr.randrange(K) for _ in range(n)]
        c = CL.clogit_fit(C, lb, yy)
        self.assertEqual(c.status, "CONVERGED")
        self.assertGreater(c.predicted_gain, 0.0)
        self.assertEqual(c.best_objective, max(c.trace))
        f = CL.loglik(C, lb, yy, c.beta)
        self.assertLess(abs(float(OR.D(f) - OR.dec_clogit_loglik(C, lb, yy, c.beta))), FI.ls_tolerance(f, n))
        s = CL.clogit_fit(C, lb, yy, tol_grad=1e-15, ls_tol=0.0)      # strict rule, sub-floor tolerance
        self.assertIn(s.status, ("CONVERGED", "FP_FLOOR", "ITER_CAP"))
        if s.status == "FP_FLOOR":
            self.assertLessEqual(s.predicted_gain, FI.ls_tolerance(s.loglik, n))
        self.assertNotEqual(s.status, "NUMERICAL_FAIL")

    def test_r3_07_fp_floor_fixture_replays_byte_identically(self):
        again = FI.firth_fit(self.X, self.y, self.off, tol_grad=1e-14, ls_tol=0.0)
        self.assertEqual(json.dumps(again.as_dict(), sort_keys=True), json.dumps(self.floor.as_dict(), sort_keys=True))


# ====================================================================== r4: arithmetic reconciliation of the FP_FLOOR evidence
class ReconciliationR4(unittest.TestCase):
    """Independent re-derivation of the A10 §13.3 quantities (owner directive r4). Corrects the r3 ratio claim."""

    @classmethod
    def setUpClass(cls):
        NumericalAuditR3.setUpClass()
        cls.X, cls.y, cls.off, cls.floor = NumericalAuditR3.X, NumericalAuditR3.y, NumericalAuditR3.off, NumericalAuditR3.floor

    def test_r4_01_gain_indicator_identity_and_corrected_ratios(self):
        r = self.floor
        ll, llp, mu, L = FI.penalised_loglik(self.X, self.y, r.beta, self.off)
        U = FI.adjusted_score(self.X, self.y, mu, L)
        delta = FI.chol_solve(L, U)
        first_order = sum(u * d for u, d in zip(U, delta))               # U*^T I^-1 U* (first-order term)
        proxy = 0.5 * first_order                                        # the recorded indicator
        self.assertAlmostEqual(r.predicted_gain, proxy, delta=1e-30)
        self.assertAlmostEqual(proxy, 2.2206467205789227e-16, delta=1e-28)   # r3 reported the first-order 4.4e-16
        ulp = math.ulp(llp)
        self.assertAlmostEqual(ulp, 1.1368683772161603e-13, delta=1e-25)
        self.assertAlmostEqual(ulp / proxy, 512.0, delta=1.0)             # corrected ratio (r3 claimed ~3000)
        self.assertAlmostEqual(FI.MACHINE_EPS * abs(llp) / first_order, 288.0, delta=1.0)   # eps|l| vs first-order
        # Fisher-scoring proxy vs the Newton decrement of the PENALISED objective (finite-difference Hessian of U*)
        h = 1e-5

        def Us(b):
            _, _, m, Lb = FI.penalised_loglik(self.X, self.y, b, self.off)
            return FI.adjusted_score(self.X, self.y, m, Lb)

        H = [[0.0] * 2 for _ in range(2)]
        for j in range(2):
            bp, bm = list(r.beta), list(r.beta)
            bp[j] += h
            bm[j] -= h
            Up, Um = Us(bp), Us(bm)
            for i in range(2):
                H[i][j] = (Up[i] - Um[i]) / (2 * h)
        det = H[0][0] * H[1][1] - H[0][1] * H[1][0]
        dn = [-(H[1][1] * U[0] - H[0][1] * U[1]) / det, -(-H[1][0] * U[0] + H[0][0] * U[1]) / det]
        newton_dec = 0.5 * sum(u * v for u, v in zip(U, dn))
        self.assertLess(abs(newton_dec - proxy) / proxy, 0.01)          # equal within 1 % on this fixture only
        # the true (decimal) change along the Fisher step matches the proxy's order and is positive
        d0 = OR.dec_firth_objective(self.X, self.y, r.beta, self.off)
        cand = [b + d for b, d in zip(r.beta, delta)]
        true_change = float(OR.dec_firth_objective(self.X, self.y, cand, self.off) - d0)
        self.assertGreater(true_change, 0.0)
        self.assertLess(abs(true_change - proxy) / proxy, 0.01)
        # float error of the objective at the stall point: ~8 ulp, below the acceptance tolerance in force
        err = abs(float(OR.D(llp) - d0))
        self.assertLess(err, 10 * ulp)
        self.assertLess(err, FI.ls_tolerance(llp, len(self.X)))

    def test_r4_02_eps_definition_and_tolerance_in_unit_roundoff_terms(self):
        self.assertEqual(FI.MACHINE_EPS, 2.0 ** -52)                     # machine epsilon; unit roundoff u = eps / 2
        u = FI.MACHINE_EPS / 2
        n, l = 1000, -576.345250375706
        self.assertAlmostEqual(FI.ls_tolerance(l, n) / (8 * u * math.sqrt(n) * (abs(l) + 1)), 1.0, places=12)
        self.assertLess(FI.ls_tolerance(l, n), (n - 1) * u * abs(l))     # below the deterministic worst-case bound


if __name__ == "__main__":
    unittest.main()
