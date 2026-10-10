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
        self.assertEqual(mods, ["__future__", "math"])
        # the harness never touches the frozen grid or the ceiling
        with open(os.path.join(PKG, "am4a_dev.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("trip_wire", src)
        self.assertNotIn("fire_count", src)


if __name__ == "__main__":
    unittest.main()
