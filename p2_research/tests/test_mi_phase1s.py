"""MI Phase 1S implementation tests (offline, bounded, synthetic only).

No real data, no W3, no Collector, no databases, no ledgers: every engine run uses a TEST-SCALED copy of the protocol
(its own hash, so its outputs can never pass derive() against the frozen protocol) in temporary directories. Small
fixtures verify formulas, determinism, integrity and fail-closed behaviour; they are NOT evidence of full-scale
statistical calibration.
"""
import ast
import copy
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from p2_research.mi import contract as MC
from p2_research.mi import derive as DV
from p2_research.mi.phase1s import engine as EN
from p2_research.mi.phase1s import gen as G
from p2_research.mi.phase1s import params as PR
from p2_research.mi.phase1s import release as RL
from p2_research.mi.phase1s import rules as RU
from p2_research.mi.phase1s import stats as S
from p2_research.mi.phase1s import store as ST

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(ROOT, "p2_research", "mi", "phase1s")
CS = "fdf3366480976db6ada1ac90b62f6b6db1edc35a59d1f3527cfcd6fcbf28e157"
PS = "412cb6062ea5b4f4c9b8bd9fa34cf0d449b4f8abcab4c173858791a9f9464202"
TREPS = {"null": 3, "skill": 2, "miscal": 2, "leak": 2, "l2": 1}
LEGIT_STOPS = {"LEAK_CANARY_WEAK", "B3_SIZE_FAIL", "B3_POWER_FAIL", "B2_REFERENCE_NOT_CONSERVATIVE",
               "L2_MODEL_FIT_INFLATION"}


def rb(path):
    with open(path, "rb") as fh:
        return fh.read()


def rt(path):
    with open(path) as fh:
        return fh.read()


def wb(path, data):
    with open(path, "wb") as fh:
        fh.write(data)


def test_protocol(reps=TREPS, days=30, B=29):
    P = copy.deepcopy(MC.protocol())
    P["_test_days"] = days
    P["bootstrap_resamples_synthetic"] = B
    for c in P["cells"]:
        if c["task"] == "T2":
            c["n_events"] = max(20, c["n_events"] // 10)
        if c["task"] == "T3":
            c["days"] = days
    P["reps"] = {"null": reps["null"], "skill": reps["skill"], "miscal": reps["miscal"], "leak": reps["leak"],
                 "l2_null": 4 * reps["l2"]}
    P["l2"]["reps_null_per_cell"] = reps["l2"]
    P["record"] = "tsb.mi.phase1s_protocol.TEST_SCALED"
    return P


def cli(args, out, proto=None, reps=TREPS, extra_env=None, check=True):
    env = dict(os.environ, PYTHONPATH=ROOT, PYTHONDONTWRITEBYTECODE="1")
    env.pop("RESEARCH_WORKERS", None)
    env.update(extra_env or {})
    cmd = [sys.executable, "-m", "p2_research.mi.phase1s"] + args + ["--out", out]
    if proto:
        cmd += ["--test-protocol", proto, "--test-reps", json.dumps(reps)]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    if check and r.returncode != 0:
        raise AssertionError(f"cli {args} rc={r.returncode}\n{r.stdout[-2000:]}\n{r.stderr[-3000:]}")
    return r


# ====================================================================== A. frozen inputs and identity
class Frozen(unittest.TestCase):
    def test_frozen_hashes_verify(self):
        P, cs, ps = RL.frozen_inputs()
        self.assertEqual((cs, ps), (CS, PS))
        self.assertEqual(MC.verify()["contract_set_sha256"], CS)
        self.assertEqual(len(P["cells"]), 48)

    def test_protocol_hash_mismatch_stops(self):
        with mock.patch.object(MC, "protocol_sha256", return_value="0" * 64):
            with self.assertRaises(RL.FrozenError):
                RL.frozen_inputs()
        with mock.patch.object(MC, "contract_set_sha256", return_value="1" * 64):
            with self.assertRaises(RL.FrozenError):
                RL.frozen_inputs()

    def test_code_tree_hash_is_stable_and_covers_only_package_sources(self):
        a, b = RL.code_tree_sha256(), RL.code_tree_sha256()
        self.assertEqual(a, b)
        self.assertRegex(a, r"^[0-9a-f]{64}$")
        files = RL.tree_files()
        self.assertTrue({"engine.py", "gen.py", "stats.py", "rules.py", "sandbox.py", "store.py", "l2.py",
                         "params.py", "release.py", "__init__.py", "__main__.py"} <= set(files))
        self.assertTrue(all(f.endswith(".py") for f in files))

    def test_frozen_protocol_figures(self):
        P = MC.protocol()
        stress = sum(c["stress"] for c in P["cells"])
        by = {t: sum(1 for c in P["cells"] if c["task"] == t) for t in ("T1", "T2", "T3")}
        self.assertEqual((by, stress), ({"T1": 24, "T2": 18, "T3": 6}, 11))
        plan = EN.planned_full_reps(P)
        self.assertEqual(sum(plan.values()), 120800)
        self.assertEqual(sum(v for k, v in plan.items() if k.endswith("|null")), 48000)
        self.assertEqual(EN.reps_for("pilot", P), {k: 10 for k in EN.KINDS})
        self.assertEqual(EN.miscal_variants(P), ["slope_0.7", "slope_1.4", "int_+0.3", "int_-0.3"])


# ====================================================================== B. statistics
class Stats(unittest.TestCase):
    def test_normal_reference_values(self):
        self.assertAlmostEqual(S.ncdf(1.959963984540054), 0.975, places=12)
        self.assertAlmostEqual(S.nppf(0.95), 1.6448536269514722, places=12)

    def test_student_t_reference_values(self):
        self.assertAlmostEqual(S.t_sf(1.0, 1), 0.25, places=12)                       # Cauchy
        for t in (0.3, 1.5, 4.0):
            self.assertAlmostEqual(S.t_sf(t, 2), 0.5 * (1 - t / math.sqrt(t * t + 2)), places=12)
        self.assertAlmostEqual(S.t_sf(1.812461123, 10), 0.05, places=8)
        self.assertAlmostEqual(S.t_sf(-1.812461123, 10), 0.95, places=8)
        self.assertAlmostEqual(S.t_sf(2.0, 10 ** 6), 1 - S.ncdf(2.0), places=6)
        self.assertAlmostEqual(S.t_ppf975(10), 2.228138852, places=7)
        self.assertAlmostEqual(S.t_ppf975(17), 2.109815578, places=7)

    def test_wilson_is_the_frozen_implementation(self):
        self.assertIs(S.wilson_upper, DV.wilson_upper)
        self.assertEqual(S.Z95, DV.Z)

    def test_holm(self):
        self.assertEqual(S.holm([0.01, 0.04], 0.05), [True, True])
        self.assertEqual(S.holm([0.03, 0.04], 0.05), [False, False])
        self.assertEqual(S.holm([0.04, 0.02], 0.05), [True, True])
        self.assertEqual(S.holm([0.02, None], 0.05), [True, False])
        self.assertEqual(S.holm([0.03, None], 0.05), [False, False])
        self.assertEqual(S.holm([None, None], 0.05), [False, False])
        self.assertEqual(S.holm([0.025, 0.05], 0.05), [True, True])          # ties at the boundary reject

    def test_bootstrap_bounds_direction_and_plan_invariance(self):
        rng = random.Random(7)
        n = 60
        pos = [[1.0 + 0.1 * rng.random() for _ in range(n)]]
        cnt = [1] * n
        B = 99
        self.assertAlmostEqual(S.sb_pvalues(pos, cnt, 5, B, random.Random(1))[0], 1 / (B + 1))
        neg = [[-v for v in pos[0]]]
        self.assertGreater(S.sb_pvalues(neg, cnt, 5, B, random.Random(1))[0], 0.95)
        two = [[rng.gauss(0, 1) for _ in range(n)], [rng.gauss(0.2, 1) for _ in range(n)]]
        both = S.sb_pvalues(two, cnt, 5, B, random.Random(3))
        only1 = S.sb_pvalues(two, cnt, 5, B, random.Random(3), which=[1])
        self.assertIsNone(only1[0])
        self.assertEqual(both[1], only1[1])
        for p in both:
            self.assertTrue(1 / (B + 1) <= p <= 1)

    def test_bootstrap_size_on_iid_null_is_plausible(self):
        rng = random.Random(11)
        rej = 0
        R = 200
        for r in range(R):
            x = [[rng.gauss(0, 1) for _ in range(40)]]
            rej += S.sb_pvalues(x, [1] * 40, 1, 99, random.Random(r))[0] <= 0.05
        self.assertTrue(0.01 <= rej / R <= 0.12, rej)

    def test_dm_ewc_matches_hand_computation_and_size(self):
        x = [0.5, -0.2, 0.9, 0.1, -0.4, 0.3, 0.7, -0.1]
        n, nu = len(x), 2
        th = sum(x) / n
        u = [v - th for v in x]
        lam = [math.sqrt(2 / n) * sum(math.cos(math.pi * j * (d + 0.5) / n) * u[d] for d in range(n))
               for j in (1, 2)]
        om = sum(v * v for v in lam) / nu
        t = th / math.sqrt(om / n)
        p, tt = S.dm_ewc_pvalue(x, [1] * n, nu)
        self.assertAlmostEqual(tt, t, places=12)
        self.assertAlmostEqual(p, S.t_sf(t, nu), places=12)
        rng = random.Random(5)
        R, rej = 300, 0
        for _ in range(R):
            y = [rng.gauss(0, 1) for _ in range(120)]
            rej += S.dm_ewc_pvalue(y, [1] * 120, 8)[0] <= 0.05
        self.assertTrue(0.02 <= rej / R <= 0.09, rej)
        self.assertLess(S.dm_ewc_pvalue([1 + 0.01 * i for i in range(50)], [1] * 50, 4)[0], 0.01)
        self.assertEqual(S.ewc_nu(517, 5.0), 77)
        self.assertEqual(S.ewc_nu(517, 56.0), 6)
        self.assertEqual(S.ewc_nu(40, 56.0), 2)

    def test_logistic_and_calibration_fits_agree_and_recover_truth(self):
        rng = random.Random(3)
        n = 4000
        L = [rng.gauss(0, 1.2) for _ in range(n)]
        y = [1 if rng.random() < S.sigmoid(0.3 + 0.8 * l) else 0 for l in L]
        beta, ok = S.logistic_fit([[1.0, l] for l in L], y)
        a, b, vaa, vbb, ok2 = S._fit_cal2(L, y, list(range(n)), n)
        self.assertTrue(ok and ok2)
        self.assertAlmostEqual(beta[0], a, places=8)
        self.assertAlmostEqual(beta[1], b, places=8)
        self.assertLess(abs(a - 0.3), 0.15)
        self.assertLess(abs(b - 0.8), 0.15)
        self.assertGreater(vbb, 0)

    def test_b3_accepts_calibrated_rejects_miscalibrated_and_handles_degenerate(self):
        rng = random.Random(9)
        n = 6000
        f = [S.sigmoid(rng.gauss(-1, 1)) for _ in range(n)]
        y = [1 if rng.random() < v else 0 for v in f]
        cl = list(range(n))
        self.assertFalse(S.b3_test(f, y, cl, n)["reject"])
        f07 = [S.sigmoid(S.logit(v) / 0.7) for v in f]          # true calibration slope 0.7
        r = S.b3_test(f07, y, cl, n)
        self.assertTrue(r["reject"])
        self.assertAlmostEqual(r["slope"], 0.7, delta=0.08)
        fint = [S.sigmoid(S.logit(v) - 0.3) for v in f]          # true intercept +0.3
        r = S.b3_test(fint, y, cl, n)
        self.assertTrue(r["reject"])
        self.assertAlmostEqual(r["intercept"], 0.3, delta=0.08)
        # pooled one-vs-rest forecasts summing to one: CITL and intercept CIs collapse to their targets -> accepted
        F = [[0.5, 0.3, 0.2]] * 300
        yy = [0] * 150 + [1] * 90 + [2] * 60
        ff, ys, cc = [], [], []
        for i, (row, k) in enumerate(zip(F, yy)):
            for c in range(3):
                ff.append(row[c]); ys.append(1 if c == k else 0); cc.append(i)
        r = S.b3_test(ff, ys, cc, 300)
        self.assertTrue(r["citl_ok"])
        self.assertAlmostEqual(r["oe"], 1.0, places=12)

    def test_citl_zero_events_rejects(self):
        self.assertTrue(S.b3_test([0.1] * 50, [0] * 50, list(range(50)), 50)["reject"])


# ====================================================================== C. generators
class Generators(unittest.TestCase):
    def test_seed_scheme_is_deterministic_and_distinct(self):
        a = G.seed_hex(CS, "T1|x", "null", "-", 0)
        self.assertEqual(a, G.seed_hex(CS, "T1|x", "null", "-", 0))
        self.assertEqual(a, hashlib.sha256(f"{CS}|T1|x|null|-|0".encode()).hexdigest()[:16])
        self.assertNotEqual(a, G.seed_hex(CS, "T1|x", "null", "-", 1))
        self.assertNotEqual(a, G.seed_hex(CS, "T1|x", "skill", "-", 0))
        self.assertNotEqual(a, G.seed_hex(CS, "T1|x", "null", "-", 0, "boot|0"))
        self.assertEqual(G.normals(G.rng_from(a), 5), G.normals(G.rng_from(a), 5))

    def test_full_plan_has_no_seed_collisions(self):
        out = tempfile.mkdtemp()
        try:
            r = json.loads(cli(["plan-info", "--mode", "full"], out).stdout)
        finally:
            shutil.rmtree(out)
        self.assertEqual(r["reps_step0_total"], 120800)
        self.assertEqual(r["seed_collisions"], 0)
        self.assertEqual(r["worst_case_total"], 216800)

    def test_ar1_and_overlap_dependence(self):
        rng = random.Random(1)
        x = G.ar1(rng, 20000, 0.95)
        m = sum(x) / len(x)
        r1 = sum((x[i] - m) * (x[i + 1] - m) for i in range(len(x) - 1)) / sum((v - m) ** 2 for v in x)
        self.assertAlmostEqual(r1, 0.95, delta=0.02)
        e = G.normals(random.Random(2), 30006)
        z = G._overlap(e, 6, 30000)
        self.assertAlmostEqual(z[3], sum(e[3:9]) / math.sqrt(6), places=12)
        v = sum(a * a for a in z) / len(z)
        c1 = sum(z[i] * z[i + 1] for i in range(len(z) - 1)) / (len(z) - 1)
        c6 = sum(z[i] * z[i + 6] for i in range(len(z) - 6)) / (len(z) - 6)
        self.assertAlmostEqual(v, 1.0, delta=0.05)
        self.assertAlmostEqual(c1, 5 / 6, delta=0.05)
        self.assertAlmostEqual(c6, 0.0, delta=0.05)

    def test_skill_tuning_hits_expected_bss(self):
        for pi in (0.01, 0.05, 0.2, 0.3, 0.5):
            for lv in ("0.01", "0.02", "0.05"):
                self.assertAlmostEqual(G.expected_bss(pi, G.kappa_for(pi, lv)), float(lv), places=9)
        with mock.patch.dict(PR.GEN, {"tau_x": 0.05}):
            G.binary_design.cache_clear(); G.kappa_for.cache_clear()
            try:
                with self.assertRaises(ValueError):
                    G.kappa_for(0.01, "0.05")
            finally:
                pass
        G.binary_design.cache_clear(); G.kappa_for.cache_clear()

    def test_binary_worlds_base_rate_and_calibration(self):
        P = MC.protocol()
        cells = {c["cell_id"]: c for c in P["cells"]}
        c = cells["T2|n=1500|pi=0.3|rho=0"]
        ys, bs, bins = [], [], [[0, 0.0, 0] for _ in range(5)]
        for rep in range(4):
            w = G.t2_world(c, random.Random(rep))
            ys += w.y
            bs += w.b
            for y, b in zip(w.y, w.b):
                k = min(4, int(b * 5))
                bins[k][0] += y; bins[k][1] += b; bins[k][2] += 1
        self.assertAlmostEqual(sum(ys) / len(ys), 0.3, delta=0.03)
        self.assertAlmostEqual(sum(bs) / len(bs), 0.3, delta=0.02)
        for ky, kb, n in bins:
            if n > 300:
                self.assertAlmostEqual(ky / n, kb / n, delta=0.06)
        w = G.t1_world(cells["T1|pi=0.2|phi=0|rho=0|brk=1"], random.Random(1))
        self.assertEqual(len(w.y), 6204)
        self.assertAlmostEqual(sum(w.y) / len(w.y), 0.2, delta=0.04)
        self.assertAlmostEqual(sum(w.b) / len(w.b), 0.1, delta=0.02)        # OD-2: dev-calibrated forecasts
        self.assertAlmostEqual(sum(w.b_cal) / len(w.b_cal), 0.2, delta=0.02)
        self.assertEqual(w.cnt, [12] * 517)

    def test_t3_chain_design(self):
        for p in (0.85, 0.95, 0.99):
            for sh in ("uniform", "adjacent"):
                P = G.transition(p, sh)
                for row in P:
                    self.assertAlmostEqual(sum(row), 1.0, places=12)
                st = G.stationary(P)
                nxt = [sum(st[i] * P[i][j] for i in range(6)) for j in range(6)]
                for a, b in zip(st, nxt):
                    self.assertAlmostEqual(a, b, places=10)
                self.assertTrue(G.t3_w(p, sh, "0.05") <= 1)
        self.assertEqual(G._neighbours(0), [1, 2])
        self.assertEqual(G._neighbours(3), [1, 2, 5])
        lags = {(p, sh): G.t3_design(p, sh)["lag"] for p in (0.85, 0.95, 0.99) for sh in ("uniform", "adjacent")}
        self.assertEqual(lags, {(0.85, "uniform"): None, (0.85, "adjacent"): 10, (0.95, "uniform"): 2,
                                (0.95, "adjacent"): 2, (0.99, "uniform"): 1, (0.99, "adjacent"): 1})


# ====================================================================== D. rules
class Rules(unittest.TestCase):
    def test_step_params(self):
        P = MC.protocol()
        self.assertEqual(RU.step_params(P, "T1", 0)["L"], 5.0)
        self.assertEqual(RU.step_params(P, "T1", 1)["L"], 10.0)
        self.assertEqual(RU.step_params(P, "T3", 2)["L"], 56.0)
        sp = RU.step_params(P, "T2", 2)
        self.assertEqual((sp["alpha"], sp["alpha_alt"], sp["B"]), (0.025, 0.025, 999))
        self.assertAlmostEqual(sp["alpha_primary"], 0.025 / 3)

    def test_miscal_transform(self):
        self.assertAlmostEqual(RU.miscal_transform(0.2, "slope_0.7"), S.sigmoid(S.logit(0.2) / 0.7))
        self.assertAlmostEqual(RU.miscal_transform(0.2, "int_+0.3"), S.sigmoid(S.logit(0.2) - 0.3))
        self.assertAlmostEqual(RU.miscal_transform(0.2, "int_-0.3"), S.sigmoid(S.logit(0.2) + 0.3))
        with self.assertRaises(ValueError):
            RU.miscal_transform(0.2, "shift_1")

    def test_short_circuits_are_exact(self):
        """Skipping bootstraps (p_dm > alpha) and B3 (no Holm rejection) never changes a decision."""
        rng = random.Random(4)
        sp = {"alpha": 0.05, "alpha_primary": 0.05 / 3, "alpha_alt": 0.05, "L": 3.0, "B": 49}
        for trial in range(25):
            n = 40
            day = list(range(n))
            ctx = {"day": day, "cnt": [1] * n, "n_days": n}
            y = [rng.random() < 0.3 for _ in range(n)]
            br_b = [rng.random() for _ in range(n)]
            ll_b = [rng.random() for _ in range(n)]
            cands = []
            for j in range(2):
                sh = rng.choice([-0.3, 0.0, 0.3])
                cands.append({"br": [v - sh * rng.random() for v in br_b], "ll": [v - sh for v in ll_b],
                              "b3": (lambda r=rng.random() < 0.3: r)})
            fast = RU.apply_rule(ctx, br_b, ll_b, cands, sp, random.Random(trial))
            # full computation
            dsum = [[a - b for a, b in zip(br_b, c["br"])] for c in cands]
            pb = S.sb_pvalues(dsum, [1] * n, 3.0, 49, random.Random(trial))
            pdm = [S.dm_ewc_pvalue(d, [1] * n, S.ewc_nu(n, 3.0))[0] for d in dsum]
            p = [max(a, b) for a, b in zip(pb, pdm)]
            b2 = [sum(a - b for a, b in zip(ll_b, c["ll"])) > 0 for c in cands]
            b3 = [c["b3"]() for c in cands]
            for alpha, key in ((sp["alpha_primary"], "pass"), (sp["alpha_alt"], "pass_alt")):
                h = S.holm(p, alpha)
                self.assertEqual(fast[key], [h[j] and b2[j] and not b3[j] for j in range(2)])

    def test_truth_classes_smoke_on_real_cells(self):
        P = MC.protocol()
        cells = {c["cell_id"]: c for c in P["cells"]}
        c = cells["T2|n=150|pi=0.5|rho=0"]
        r = RU.run_null(c, P, random.Random(1), random.Random(2), 0)
        self.assertEqual(set(r), {"fp", "fp_alt", "b3_reject", "p", "pdm"})
        m = RU.run_miscal(c, P, random.Random(3), "slope_0.7", 0)
        self.assertIn(m["reject"], (0, 1))
        lk = RU.run_leak(c, P, random.Random(4))
        self.assertGreater(lk["bss"], 0.2)                      # leak weight 2 -> large realised BSS
        t3 = cells["T3|persistence=0.95|shape=adjacent"]
        self.assertGreater(RU.run_leak(t3, P, random.Random(5))["bss"], 0.2)


# ====================================================================== E. engine (offline-test runs)
class EngineRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="mi-p1s-test-")
        cls.proto = os.path.join(cls.tmp, "proto.json")
        cls.P = test_protocol()
        with open(cls.proto, "w") as fh:
            json.dump(cls.P, fh)
        cls.ps = EN.protocol_sha_of(cls.P)
        cls.a = os.path.join(cls.tmp, "a")
        cls.b = os.path.join(cls.tmp, "b")
        common = ["--mode", "offline-test", "--chunk", "2"]
        cls.ra = cli(["run"] + common, cls.a, cls.proto)
        cli(["finalize"] + common, cls.a, cls.proto)
        cls.rb = cli(["run"] + common + ["--workers", "2"], cls.b, cls.proto)
        cli(["finalize"] + common, cls.b, cls.proto)
        with open(os.path.join(cls.a, "output.json"), "rb") as fh:
            cls.out_a = fh.read()
        with open(os.path.join(cls.b, "output.json"), "rb") as fh:
            cls.out_b = fh.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_byte_identical_rerun_serial_vs_fork_pool(self):
        self.assertEqual(self.out_a, self.out_b)
        with open(os.path.join(self.a, "output.sha256")) as fh:
            self.assertEqual(fh.read().split()[0], hashlib.sha256(self.out_a).hexdigest())

    def test_output_schema_and_metadata(self):
        o = json.loads(self.out_a)
        self.assertEqual((o["record"], o["record_version"], o["status"]), ("tsb.mi.phase1s_output", 1, "COMPLETE"))
        self.assertEqual(o["contract_set_sha256"], CS)
        self.assertEqual(o["protocol_sha256"], self.ps)
        self.assertNotEqual(o["protocol_sha256"], PS)
        self.assertEqual(set(o["cells"]), {c["cell_id"] for c in self.P["cells"]})
        self.assertEqual(o["budget"]["enforcement_verified"], False)
        self.assertEqual(o["budget"]["enforcement"], "none_offline_test")
        m = o["meta"]
        for k in ("code_tree_sha256", "plan_sha256", "seeds_sha256", "results_sha256", "methods", "gen_params",
                  "generator_version", "impl_version", "reps", "rerun"):
            self.assertIn(k, m)
        self.assertEqual(m["code_tree_sha256"], RL.code_tree_sha256())
        self.assertEqual(m["rerun"]["mismatch"], 0)
        for cid, co in o["cells"].items():
            fs = o["final_step"][cid.split("|")[0]]
            self.assertEqual(sorted(co["null"]), [str(k) for k in range(fs + 1)])
            self.assertEqual(sorted(co["skill"]), sorted(self.P["skill_levels"]))
            self.assertEqual(set(co["miscal"]), set(EN.miscal_variants(self.P)))
            for rec in co["null"].values():
                self.assertEqual(rec["n"], TREPS["null"])
            self.assertEqual(co["leak"]["n"], TREPS["leak"])
        self.assertEqual(o["l2"]["n"], 4 * TREPS["l2"])

    def test_derive_round_trip(self):
        sha = hashlib.sha256(self.out_a).hexdigest()
        with self.assertRaises(DV.DerivationStop) as cm:
            DV.derive(self.out_a, sha, self.P, CS, self.ps)
        self.assertEqual(cm.exception.code, "BUDGET_NOT_ENFORCED")          # fail closed without real evidence
        with self.assertRaises(DV.DerivationStop) as cm:
            DV.derive(self.out_a, sha, MC.protocol(), CS, PS)
        self.assertEqual(cm.exception.code, "PROTOCOL_MISMATCH")            # test output never meets the frozen one
        # TEST FIXTURE ONLY: replace the budget block in memory to exercise the remaining schema; this is not, and
        # is never written as, evidence of guard enforcement.
        o = json.loads(self.out_a)
        o["budget"] = {"enforcement": "cgroup_cpu_budget_guard_v1", "enforcement_verified": True,
                       "cap_cpu_s": 28800, "cumulative_cpu_s": 1.0, "breach": False}
        b = DV.canon(o).encode()
        try:
            res = DV.derive(b, hashlib.sha256(b).hexdigest(), self.P, CS, self.ps)
            self.assertEqual(set(res["tasks"]), {"T1", "T2", "T3"})
        except DV.DerivationStop as e:
            self.assertIn(e.code, LEGIT_STOPS)
        # with the leak canary forced to fire, the schema is accepted further (B3 / power gates)
        for co in o["cells"].values():
            co["leak"]["fire_k"] = co["leak"]["n"]
        b = DV.canon(o).encode()
        try:
            DV.derive(b, hashlib.sha256(b).hexdigest(), self.P, CS, self.ps)
        except DV.DerivationStop as e:
            self.assertIn(e.code, LEGIT_STOPS)

    def test_resume_is_idempotent(self):
        jp = os.path.join(self.a, "journal.jsonl")
        n0 = len(rt(jp).splitlines())
        cli(["run", "--mode", "offline-test", "--chunk", "2"], self.a, self.proto)
        evs = [json.loads(l)["ev"] for l in rt(jp).splitlines()[n0:]]
        self.assertNotIn("shard_commit", evs)
        self.assertIn("run_done", evs)
        cli(["finalize", "--mode", "offline-test", "--chunk", "2"], self.a, self.proto)
        with open(os.path.join(self.a, "output.json"), "rb") as fh:
            self.assertEqual(fh.read(), self.out_a)

    def test_cpu_report_written(self):
        with open(os.path.join(self.a, "cpu_report.json")) as fh:
            rep = json.load(fh)["cpu"]
        self.assertIn("T1|null", rep["per_task_kind"])
        self.assertIn("T3|l2", rep["per_task_kind"])
        self.assertGreater(rep["per_task_kind"]["T1|null"]["n"], 0)
        self.assertTrue(any(k.startswith("T2|n=150|pi=0.2|rho=0|skill|") for k in rep["per_case"]))
        self.assertIn("children_user_s", rep["process"])

    def test_incompatible_resume_refused(self):
        r = cli(["run", "--mode", "offline-test", "--chunk", "3"], self.a, self.proto, check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("PLAN_MISMATCH", r.stderr)


class EngineIntegrity(unittest.TestCase):
    """In-process engine on one task (T3, cheap) of the scaled protocol; failure paths of the checkpoint store."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mi-p1s-int-")
        self.P = test_protocol(days=30, B=19)
        self.ps = EN.protocol_sha_of(self.P)
        self.engines = []

    def tearDown(self):
        for e in self.engines:
            e.restore()
        self.assertEqual(PR.GEN, PR.DEFAULT_GEN)
        shutil.rmtree(self.tmp)

    def eng(self, out="o", **kw):
        e = EN.Engine(os.path.join(self.tmp, out), self.P, CS, self.ps, "offline-test", dict(TREPS), chunk=2, **kw)
        self.engines.append(e)
        return e.open()

    def test_t3_run_then_tamper_paths(self):
        e = self.eng()
        e.run(["T3"])
        keys = sorted(e.results)
        self.assertTrue(keys)
        # corrupted shard -> refuse
        k0 = keys[0]
        p0 = os.path.join(self.tmp, "o", "shards", k0 + ".json")
        good = rb(p0)
        doc = json.loads(good)
        doc["results"]["reps"][0][2] = doc["results"]["reps"][0][2] + 1           # silent result edit
        wb(p0, DV.canon(doc).encode())
        with self.assertRaises(ST.StoreError) as cm:
            self.eng()
        self.assertEqual(cm.exception.code, "SHARD_SELF_HASH")
        wb(p0, good[:-7])                                              # torn / truncated file
        with self.assertRaises(ST.StoreError) as cm:
            self.eng()
        self.assertEqual(cm.exception.code, "SHARD_UNREADABLE")
        wb(p0, good)
        # deleted committed shard -> MISSING_SHARD; explicit recompute is journaled and identical
        os.remove(p0)
        with self.assertRaises(ST.StoreError) as cm:
            self.eng()
        self.assertEqual(cm.exception.code, "MISSING_SHARD")
        e2 = self.eng(allow_recompute_missing=True)
        e2.run(["T3"])
        self.assertEqual(json.loads(rb(p0))["results"], json.loads(good)["results"])
        evs = [x["ev"] for x in e2.journal.events]
        self.assertIn("shard_void", evs)
        # stale tmp -> discarded; unexpected file -> refused
        wb(p0 + ".tmp", b"partial")
        e3 = self.eng()
        self.assertFalse(os.path.exists(p0 + ".tmp"))
        self.assertIn("tmp_discarded", [x["ev"] for x in e3.journal.events])
        junk = os.path.join(self.tmp, "o", "shards", "junk.txt")
        wb(junk, b"x")
        with self.assertRaises(ST.StoreError) as cm:
            self.eng()
        self.assertEqual(cm.exception.code, "UNEXPECTED_FILE")
        os.remove(junk)
        # journal tamper -> refused
        jp = os.path.join(self.tmp, "o", "journal.jsonl")
        lines = rb(jp).split(b"\n")
        lines[1] = lines[1].replace(b'"ev":"', b'"ev":"x', 1)
        wb(jp, b"\n".join(lines))
        with self.assertRaises(ST.StoreError) as cm:
            self.eng()
        self.assertIn(cm.exception.code, {"JOURNAL_HASH", "JOURNAL_CHAIN"})

    def test_orphan_shard_adopted_not_recomputed(self):
        e = self.eng("src")
        e.run(["T3"])
        e2 = self.eng("dst")
        # copy one shard without its journal line (crash after rename, before the journal append)
        k = sorted(e.results)[0]
        src = os.path.join(self.tmp, "src", "shards", k + ".json")
        dst = os.path.join(self.tmp, "dst", "shards", k + ".json")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)
        e3 = self.eng("dst")
        self.assertIn(k, e3.results)
        self.assertIn("shard_adopted", [x["ev"] for x in e3.journal.events])
        n_commit = sum(1 for x in e3.journal.events if x["ev"] == "shard_commit")
        e3.run(["T3"])
        commits = [x["key"] for x in e3.journal.events if x["ev"] == "shard_commit"]
        self.assertNotIn(k, commits[n_commit:])

    def test_shard_with_wrong_seeds_or_reps_refused(self):
        e = self.eng()
        e.run(["T3"])
        k = sorted(e.results)[0]
        u = e._unit_from_key(k)
        bad = copy.deepcopy(e.results[k])
        bad["reps"][0][1] = "0" * 16
        data = ST.shard_doc(k, e.plan_sha, u, bad, e.cpu[k])
        p = os.path.join(self.tmp, "x", "shards", k + ".json")
        os.makedirs(os.path.dirname(p))
        wb(p, data)
        with self.assertRaises(ST.StoreError) as cm:
            self.eng("x")
        self.assertEqual(cm.exception.code, "SHARD_SEEDS")
        bad = copy.deepcopy(e.results[k])
        bad["reps"] = bad["reps"][:1]
        wb(p, ST.shard_doc(k, e.plan_sha, u, bad, e.cpu[k]))
        with self.assertRaises(ST.StoreError) as cm:
            self.eng("x")
        self.assertEqual(cm.exception.code, "SHARD_REP_SET")

    def test_ladder_transitions(self):
        """Fabricated null results: step 0 fails, step 1 passes -> final 1; all fail -> 2 / FAIL."""
        e = self.eng()
        n = TREPS["null"]
        P = self.P

        def fill(task, step, fp_fail):
            for u in e.null_units(task, step):
                c = e.cells[u["cell_id"]]
                fp = 1 if (fp_fail and not c["stress"]) else 0
                e.results[EN.unit_key(u)] = {"reps": [[r, "x", fp, fp, 0, None, None] for r in range(u["r0"], u["r1"])],
                                             "rerun": {"checked": 0, "mismatch": 0}}
        acc = dict(P["meta_acceptance"])
        with mock.patch.dict(e.P["meta_acceptance"], {"null_fpr_wilson_ub_max": 1.0}):
            fill("T3", 0, True); fill("T3", 1, False)
            k, hist, ok = e.ladder("T3", compute=False)
            self.assertEqual((k, ok, [h["pass"] for h in hist]), (1, True, [False, True]))
            fill("T3", 1, True); fill("T3", 2, True)
            k, hist, ok = e.ladder("T3", compute=False)
            self.assertEqual((k, ok, len(hist)), (2, False, 3))
        self.assertEqual(P["meta_acceptance"], acc)

    def test_leak_fire_is_strictly_above_ceiling(self):
        self.assertEqual(EN.fire_count([0.2, 0.21, 0.5, 0.1], 0.2), 2)
        self.assertEqual(EN.fire_count([0.2], None), 0)

    def test_mode_guards(self):
        with self.assertRaises(EN.EngineError) as cm:
            EN.Engine(self.tmp, self.P, CS, self.ps, "pilot", EN.reps_for("pilot", MC.protocol()))
        self.assertEqual(cm.exception.code, "NOT_FROZEN_PROTOCOL")
        with self.assertRaises(EN.EngineError) as cm:
            EN.Engine(self.tmp, MC.protocol(), CS, PS, "offline-test", dict(TREPS))
        self.assertEqual(cm.exception.code, "TEST_ON_FROZEN_HASH")
        with self.assertRaises(EN.EngineError):
            EN.reps_for("offline-test", self.P, {"null": 500, "skill": 1, "miscal": 1, "leak": 1, "l2": 1})
        with mock.patch.dict(PR.GEN, {"null_noise_sd": 0.2}):
            with self.assertRaises(EN.EngineError) as cm:
                EN.Engine(self.tmp, MC.protocol(), CS, PS, "full", EN.reps_for("full", MC.protocol()))
            self.assertEqual(cm.exception.code, "GEN_PARAMS_MUTATED")
        e = EN.Engine(os.path.join(self.tmp, "f"), MC.protocol(), CS, PS, "full", EN.reps_for("full", MC.protocol()))
        e.restore()
        self.assertEqual(e.reps, {"null": 1000, "skill": 200, "miscal": 200, "leak": 100, "l2": 200})

    def test_pilot_plan_is_exact_and_stratified(self):
        P = MC.protocol()
        e = EN.Engine(os.path.join(self.tmp, "p"), P, CS, PS, "pilot", EN.reps_for("pilot", P), chunk=5)
        e.restore()
        units = e.pilot_units(["T3", "T2", "T1", "L2"])
        n = sum(u["r1"] - u["r0"] for u in units)
        self.assertEqual(n, 4320 + 40)
        self.assertTrue(all(u["step"] == 0 for u in units))
        first = [u for u in units if u["r0"] == 0]
        self.assertEqual(units[:len(first)], first)
        strata = {(e.cells[u["cell_id"]]["task"], u["kind"]) for u in first}
        self.assertEqual(len(strata), 3 * 4 + 3)          # every task x {null, skill, miscal, leak} + L2 in T1/T2/T3
        self.assertEqual(len({EN.unit_key(u) for u in units}), len(units))

    def test_budget_evidence_validation(self):
        ev = {"record": "tsb.mi.budget_evidence", "v": 1, "ledger_id": EN.LEDGER_ID, "cap_cpu_s": 28800,
              "open_reservations": 0, "ledger_head_sha256": "a" * 64, "ledger_cumulative_charged_cpu_s": 5000.0,
              "campaigns": [{"campaign": "p1s-t3", "state": "DONE", "measured": True, "charged_cpu_s": 900.0}]}
        ok, _ = EN.validate_evidence(ev, {"p1s-t3"})
        self.assertTrue(ok)
        b, _ = EN.budget_block("full", ev, {"p1s-t3"})
        self.assertEqual((b["enforcement_verified"], b["breach"], b["cumulative_cpu_s"]), (True, False, 5000.0))
        for mut in ({"ledger_id": "x"}, {"cap_cpu_s": 28733}, {"open_reservations": 1}, {"campaigns": []},
                    {"ledger_head_sha256": "zz"}, {"record": "other"}):
            self.assertFalse(EN.validate_evidence({**ev, **mut}, {"p1s-t3"})[0], mut)
        bad = copy.deepcopy(ev)
        bad["campaigns"][0]["state"] = "KILLED"
        self.assertFalse(EN.validate_evidence(bad, {"p1s-t3"})[0])
        self.assertFalse(EN.validate_evidence(ev, {"p1s-t3", "offline"})[0])      # shards from an uncovered campaign
        b, _ = EN.budget_block("full", {**ev, "ledger_cumulative_charged_cpu_s": 30000.0}, {"p1s-t3"})
        self.assertTrue(b["breach"])
        b, note = EN.budget_block("full", None, set())
        self.assertFalse(b["enforcement_verified"])
        self.assertIsNone(b["cumulative_cpu_s"])


# ====================================================================== F. CPU projection
class Projection(unittest.TestCase):
    def test_projection_arithmetic(self):
        P = MC.protocol()
        plan = EN.planned_full_reps(P)
        rep = {"per_task_kind": {k: {"n": 100, "mean": 0.1, "sd": 0.0, "sum": 10.0, "max": 0.1} for k in plan}}
        pr = EN.project(rep, P, available_cpu_s=24060)
        rr = 1.02
        base = 120800 * 0.1 * rr
        reserve = 48000 * 0.1 * rr
        self.assertAlmostEqual(pr["P_point"], base * 1.25 + reserve, places=6)
        self.assertAlmostEqual(pr["P_upper"], pr["P_point"], places=6)
        self.assertAlmostEqual(pr["worst_case_two_extra_steps_point"], base * 1.25 + 2 * reserve, places=6)
        self.assertEqual(pr["verdict"], "FITS")
        rep2 = {"per_task_kind": {k: {"n": 100, "mean": 0.2, "sd": 0.0} for k in plan}}
        self.assertEqual(EN.project(rep2, P, 24060)["verdict"], "EXCEEDS_STOP_TO_OWNER")
        del rep2["per_task_kind"]["T1|l2"]
        self.assertEqual(EN.project(rep2, P)["verdict"], "INCOMPLETE_PILOT")
        self.assertEqual(EN.project(rep, P)["verdict"], "NEEDS_AVAILABLE_BUDGET")


# ====================================================================== G. sandbox (subprocess) and static checks
SANDBOX_PROBE = r'''
import json, os, sys
from p2_research.mi.phase1s import sandbox as SB
out = sys.argv[1]
SB.install(out, allow_fork=False)
res = {}
def probe(name, fn):
    try:
        fn(); res[name] = "allowed"
    except SB.SandboxViolation as e:
        res[name] = "denied"
    except Exception as e:
        res[name] = "error:" + type(e).__name__
H = os.path.expanduser("~")
probe("read_research_data", lambda: open(os.path.join(H, "research-data", "x.parquet")))
probe("read_backups", lambda: open(os.path.join(H, "backups", "x")))
probe("read_budget_ledger", lambda: open(os.path.join(H, ".local", "state", "research-runner", "mi", "budget.jsonl")))
probe("read_anchor", lambda: open(os.path.join(H, ".config", "research-runner", "mi", "budget.anchor.json")))
probe("read_etc", lambda: open("/etc/hostname"))
probe("listdir_home", lambda: os.listdir(H))
probe("write_tmp", lambda: open("/tmp/mi-p1s-sandbox-probe", "w"))
probe("docker_sock", lambda: open("/var/run/docker.sock", "rb"))
probe("popen", lambda: __import__("subprocess").Popen(["true"]))
probe("os_system", lambda: os.system("true"))
probe("socket", lambda: __import__("socket").socket())
probe("import_sqlite3", lambda: __import__("sqlite3"))
probe("import_reader", lambda: __import__("p2_research.reader"))
probe("import_guard", lambda: __import__("mi_cpuguard"))
probe("fork", lambda: os.fork())
probe("read_contract", lambda: open(os.path.join(os.path.dirname(SB.__file__), "..", "contracts_v1_0",
                                                "mi_phase1s_protocol_v1_0.json")).read())
probe("write_out", lambda: open(os.path.join(out, "ok.txt"), "w").write("x"))
probe("mi_slice", SB.require_mi_slice)
try:
    try:
        open("/etc/passwd")
    except Exception:
        pass                    # a library swallowing the violation
    SB.check(); res["swallowed"] = "not_detected"
except SB.SandboxViolation:
    res["swallowed"] = "detected"
print(json.dumps(res))
'''


class Sandbox(unittest.TestCase):
    def test_fail_closed_probe(self):
        out = tempfile.mkdtemp(prefix="mi-p1s-sbx-")
        try:
            env = dict(os.environ, PYTHONPATH=ROOT)
            r = subprocess.run([sys.executable, "-c", SANDBOX_PROBE, out], cwd=ROOT, env=env, capture_output=True,
                               text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            res = json.loads(r.stdout.strip().splitlines()[-1])
        finally:
            shutil.rmtree(out)
        for k in ("read_research_data", "read_backups", "read_budget_ledger", "read_anchor", "read_etc",
                  "listdir_home", "write_tmp", "docker_sock", "popen", "os_system", "socket", "import_sqlite3",
                  "import_reader", "import_guard", "fork", "mi_slice"):
            self.assertEqual(res[k], "denied", k)
        self.assertEqual(res["read_contract"], "allowed")
        self.assertEqual(res["write_out"], "allowed")
        self.assertEqual(res["swallowed"], "detected")
        self.assertFalse(os.path.exists("/tmp/mi-p1s-sandbox-probe"))

    def test_cli_pilot_and_full_refuse_outside_mi_slice(self):
        out = tempfile.mkdtemp(prefix="mi-p1s-cli-")
        try:
            tree = RL.code_tree_sha256()
            for mode in ("pilot", "full"):
                r = cli(["run", "--mode", mode, "--expect-tree-sha256", tree, "--impl-commit", "a" * 40], out,
                        check=False)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("NOT_IN_MI_SLICE", r.stderr)
            r = cli(["run", "--mode", "pilot"], out, proto=os.path.join(out, "p.json"), check=False)
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse(os.path.exists(os.path.join(out, "shards")))
        finally:
            shutil.rmtree(out)


FORBIDDEN_IMPORTS = ("p2_research.reader", "p2_research.stream", "p2_research.ledger", "p2_research.execution",
                     "p2_forward", "mi_cpuguard", "research_exec", "sqlite3", "socket", "subprocess", "psycopg",
                     "psycopg2", "asyncpg", "ctypes", "urllib", "http", "requests", "docker")


class Static(unittest.TestCase):
    def test_package_imports_nothing_forbidden(self):
        for f in RL.tree_files():
            with open(os.path.join(PKG, f)) as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                for n in names:
                    for bad in FORBIDDEN_IMPORTS:
                        self.assertFalse(n == bad or n.startswith(bad + "."), f"{f} imports {n}")

    def test_no_ledger_or_data_paths_outside_the_sandbox_deny_list(self):
        for f in RL.tree_files():
            if f == "sandbox.py":
                continue
            with open(os.path.join(PKG, f)) as fh:
                src = fh.read()
            for needle in ("budget.jsonl", "budget.anchor", "research-data", "backups", "mi/ledger", "W3",
                           "docker.sock", "postgres"):
                self.assertNotIn(needle, src, f"{f} mentions {needle}")


if __name__ == "__main__":
    unittest.main()
