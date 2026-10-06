"""P2-F0 adversarial validation: frozen contracts and bindings, statistics, the position rebuild, every integrity
refusal, verdict precedence, determinism, the forward rules and the anti-retroactivity mechanics.

Synthetic data only (``p2_research.falsification.synthetic``); no real dataset, ledger or network is touched."""
import ast
import copy
import json
import math
import os
import random
import re
import shutil
import tempfile
import unittest

from p2_research import ledger as LG, protocol as D0
from p2_research.falsification import battery as B, contracts as C, forward as FW, panel as PN, stats as S
from p2_research.falsification import synthetic as SY

PKG = os.path.dirname(os.path.abspath(C.__file__))
D0_SUMS = "2bedc3f5c3a4de4fde8d9c8518270f7cd0078033fd754c75c20297954e408573"
X1_SUMS = "3c554702948867fa26d4bba95b922f5e1db5902e42b088d9cdc49fdceefeec2f"
X2_SUMS = "f20e22a5e79b2ab36caa180ca25d652e6e273c2ad72392ed860c2d7f72aa88d0"
F0_V1_SUMS = "9f42105d2d408babdf8f7a96036dd1bdd46ee1ac858b23a7642a3ba1950398b6"
FAST = {"bootstrap": 99, "random_entry": 19, "time_shift": 19}
CAND = SY.CANDIDATE_PLAN


def _reg(cs, rd, pid, forward=None):
    return {"record": "tsb.p2f.candidate_registration", "trial_id": rd.trial_id(pid), "plan_id": pid,
            "f0_contract_set_sha256": cs.sha256, "p2d0_sums_sha256": D0_SUMS, "p2x_v2_sums_sha256": X2_SUMS,
            "considered_trials": rd.all_trial_ids() if forward is None else [rd.trial_id(pid)],
            "forward_registration": forward, "dataset": {"dataset_id": "synthetic", "dataset_hash": "ab" * 32}}


class Shared:
    cs = None
    rd = None

    @classmethod
    def get(cls):
        if cls.cs is None:
            cls.cs = C.default()
            cls.bat = cls.cs.battery(reps_profile=FAST)
            cls.rd = SY.Round(7, cls.cs.plan, mode="null", delta=(0.005 + 0.0026) / 1.354,
                              only=[CAND, "P2D-R1-H01-002", "P2D-R1-H01-008"])
            cls.ev = cls.rd.evidence(CAND, _reg(cls.cs, cls.rd, CAND))
        return cls


class TestFrozenContracts(unittest.TestCase):
    def test_f0_frozen_and_dependencies_unchanged(self):
        cs = C.default()
        self.assertEqual((cs.version, len(cs.sha256)), (2, 64))
        self.assertEqual(cs.dependencies, {"p2d0": D0_SUMS, "p2x_v1": X1_SUMS, "p2x_v2": X2_SUMS})
        self.assertEqual(C.verify(C.CONTRACT_DIR), F0_V1_SUMS)          # superseded v1 kept byte-identical
        self.assertEqual(cs.protocol["supersedes"]["contract_set_sha256"], F0_V1_SUMS)
        self.assertEqual(C.default(1).protocol["inference"].get("combine_version", 1), 1)
        self.assertEqual(cs.protocol["inference"]["combine_version"], 2)
        D0.verify_frozen()

    def test_versions_and_v2_governs(self):
        vs = C.versions()
        self.assertEqual([v["version"] for v in vs], ["1.0.0", "2.0.0"])
        self.assertTrue(all(v["frozen_at_ledger_seq"] == -1 for v in vs))
        self.assertEqual(C.applicable_version(vs, None)["version"], "2.0.0")
        self.assertEqual(C.applicable_version(vs, 0)["version"], "2.0.0")

    def test_tamper_and_file_set_refused(self):
        tmp = tempfile.mkdtemp(prefix="p2f0-t-")
        try:
            d = os.path.join(tmp, "c")
            shutil.copytree(C.CONTRACT_DIR, d)
            C.verify(d)
            p = os.path.join(d, "f0_protocol_v1.json")
            with open(p, "a") as fh:
                fh.write(" ")
            with self.assertRaises(C.ContractError):
                C.verify(d)
            shutil.rmtree(d)
            shutil.copytree(C.CONTRACT_DIR, d)
            os.remove(os.path.join(d, "f0_forward_v1.json"))
            with self.assertRaises((C.ContractError, OSError)):
                C.verify(d)
            with self.assertRaises(C.ContractError):
                C.freeze(C.CONTRACT_DIR)              # already frozen: a change needs a new version
            with self.assertRaises(C.ContractError):
                C.freeze(C.CONTRACT_DIR_V2)
        finally:
            shutil.rmtree(tmp, True)

    def test_thresholds_marked_proposed_and_taxonomy_never_proves(self):
        p = C.default().protocol
        self.assertEqual(p["activation"]["thresholds_status"], "PROPOSED_NOT_OWNER_APPROVED")
        for word in ("PROVEN", "CONFIRMED", "VALIDATED", "SUCCESS"):
            self.assertNotIn(word, p["verdicts"]["in_sample"] + p["verdicts"]["forward"])
        self.assertEqual(set(B.VERDICT_OF.values()), set(p["verdicts"]["in_sample"]))

    def test_package_is_stdlib_only_and_never_imports_p2_forward(self):
        allowed = {"__future__", "argparse", "bisect", "datetime", "hashlib", "json", "math", "os", "random",
                   "statistics", "sys", "time", "unittest"}
        for f in sorted(os.listdir(PKG)):
            if not f.endswith(".py"):
                continue
            with open(os.path.join(PKG, f), encoding="utf-8") as fh:
                src = fh.read()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module.split(".")[0]]
                for n in names:
                    self.assertIn(n, allowed, f"{f} imports {n}")
            self.assertIsNone(re.search(r"(^|\n)\s*(import|from)\s+p2_forward", src), f)
            self.assertNotIn("psycopg", src)
            self.assertNotIn("/home/tradmin/research-data/trading-signal-bot/p2/forward-continuous-v1/segments", src)


class TestStats(unittest.TestCase):
    def test_t_and_beta(self):
        self.assertAlmostEqual(S.t_sf(2.0, 10), 0.036694, places=5)
        self.assertAlmostEqual(S.t_sf(-1.0, 5), 1 - 0.181609, places=5)
        self.assertAlmostEqual(S.betainc(2, 3, 0.4), 0.5248, places=4)

    def test_holm_bh(self):
        h = S.holm({"a": 0.01, "b": 0.04, "c": 0.03})
        self.assertAlmostEqual(h["a"], 0.03)
        self.assertAlmostEqual(h["c"], 0.06)
        self.assertAlmostEqual(h["b"], 0.06)
        b = S.bh({"a": 0.01, "b": 0.04, "c": 0.03})
        self.assertAlmostEqual(b["a"], 0.03)
        self.assertAlmostEqual(b["b"], 0.04)

    def test_dependence_and_bootstrap_deterministic(self):
        rng = random.Random(1)
        x, prev = [], 0.0
        for _ in range(200):
            prev = 0.6 * prev + rng.gauss(0, 1)
            x.append(prev)
        self.assertLess(S.n_eff(x, 5), 120)
        iid = [random.Random(2).gauss(0, 1) for _ in range(5)]
        self.assertLessEqual(S.n_eff(iid, 3), 5)
        a = S.stationary_indices(30, 3, random.Random(5))
        self.assertEqual(a, S.stationary_indices(30, 3, random.Random(5)))
        r1 = S.core_test(x[:20], 3, 3, 199, 9)
        self.assertEqual(r1, S.core_test(x[:20], 3, 3, 199, 9))
        self.assertGreaterEqual(r1["p"], max(r1["p_boot"], r1["p_hac_t"]) - 1e-15)

    def test_alpha_series_is_ols_alpha(self):
        rng = random.Random(3)
        m = [rng.gauss(0, 0.02) for _ in range(20)]
        p = [0.001 + 1.3 * v + rng.gauss(0, 0.005) for v in m]
        a, beta = S.alpha_series(p, m)
        o = S.ols_alpha(p, [m], 2)
        self.assertAlmostEqual(S.mean(a), o["alpha"], places=12)
        self.assertAlmostEqual(beta, o["betas"][0], places=10)

    def test_multiplicity_and_spending(self):
        self.assertAlmostEqual(S.obf_spent(0.05, 1.0), 0.05, places=12)
        inc = S.obf_increments(0.05, [0.25, 0.5, 0.75, 1.0])
        self.assertAlmostEqual(sum(inc), 0.05, places=12)
        self.assertLess(inc[0], inc[-1])
        x = [0.01 * math.sin(i) + 0.002 for i in range(30)]
        self.assertGreater(S.deflated_sharpe(x, 1)["dsr"], S.deflated_sharpe(x, 48)["dsr"])
        self.assertEqual(S.effective_trials(48, 1.0), 1.0)
        self.assertEqual(S.effective_trials(48, 0.0), 48.0)
        rng = random.Random(4)
        series = {f"t{i}": [rng.gauss(0.0, 1) for _ in range(20)] for i in range(5)}
        series["t0"] = [v + 0.8 for v in series["t0"]]
        adj = S.romano_wolf(series, 2, 2, 199, 1)
        raw = S.nw_t_test(series["t0"], 2)["p"]
        self.assertGreaterEqual(adj["t0"], raw * 0.5)
        self.assertLessEqual(min(adj.values()), 1.0)

    def test_v2_inference_components(self):
        x = [0.01, -0.02, 0.03, 0.0, 0.02, 0.01, -0.01, 0.04, 0.0, 0.01, 0.02, -0.03, 0.01]
        self.assertEqual(S.block_length(13, 3), 3)
        self.assertEqual(S.block_length(28, 3), 4)
        self.assertEqual(S.block_length(65, 3), 5)
        self.assertIsNone(S.batch_means_p(x, 3, df_loss=2))           # 4 batches < df_loss + 3
        pb = S.batch_means_p(x, 3)
        bm = [sum(x[1 + 3 * i:4 + 3 * i]) / 3 for i in range(4)]
        t = S.mean(bm) / (S.sd(bm) / 2.0)
        self.assertAlmostEqual(pb, S.t_sf(t, 3), places=12)
        self.assertEqual(S.fixedb_hac_p(x, 3), S.fixedb_hac_p(list(x), 3))
        r = S.core_test_v2(x, 3, 199, 1)
        self.assertEqual(r["p"], max(r["p_boot"], r["p_batch"], r["p_fixedb"]))
        rng = random.Random(8)
        hits = sum(S.fixedb_hac_p([rng.gauss(0, 1) for _ in range(14)], 3) <= 0.05 for _ in range(400))
        self.assertLess(hits / 400, 0.09)                              # roughly nominal under iid

    def test_joint_tail(self):
        ref = [[float(i), float(-i)] for i in range(100)]
        pj, per = S.joint_tail_p([-5.0, 50.0], ref, [-1, -1])
        self.assertLess(pj, 0.05)
        self.assertGreater(per[1], 0.4)


class TestPanel(unittest.TestCase):
    def test_position_rule_enter_only_when_flat(self):
        H = PN.HORIZON_MS["24h"]
        st = 6 * 3600 * 1000
        rows = [{"sym": "BTCUSDT", "t_ms": i * st, "elig": 1, "sig": 1} for i in range(9)]
        pos = PN.build_positions(PN.by_symbol(rows), PN.signal_flags(rows), H)
        self.assertEqual([p["t_ms"] for p in pos], [0, 4 * st, 8 * st])     # re-entry exactly at t + h
        lag = PN.lag_flags(PN.by_symbol(rows), {("BTCUSDT", 0): 1}, 1)
        self.assertEqual(lag, {("BTCUSDT", st): 1})
        ts, tix = PN.time_index(rows)
        sh = PN.shifted_flags({("BTCUSDT", 0): 1}, ts, tix, 3, {("BTCUSDT", r["t_ms"]) for r in rows})
        self.assertEqual(sh, {("BTCUSDT", 3 * st): 1})

    def test_cluster_and_portfolio(self):
        pos = [{"day": 1, "net_base": 0.01}, {"day": 1, "net_base": 0.03}, {"day": 3, "net_base": None}]
        cl, nn = PN.cluster_series(pos, "net_base")
        self.assertEqual((cl, nn), ([(1, 0.02)], 1))
        self.assertEqual(PN.portfolio_series(pos, "net_base", [1, 2, 3]), [0.02, 0.0, 0.0])

    def test_neighbours_from_frozen_plan(self):
        plan = D0.load("planned_trials_v1.json")
        self.assertEqual(B.neighbours(plan, CAND), ["P2D-R1-H01-002", "P2D-R1-H01-003", "P2D-R1-H01-008"])


class TestIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = Shared.get()

    def run_ev(self, ev, ctx=None):
        return self.S.bat.evaluate(ev, ctx or {})

    def assertInvalid(self, ev, test):
        r = self.run_ev(ev)
        self.assertEqual(r["verdict"], "INVALID_EVIDENCE", r["reasons"])
        self.assertEqual(r["tests"][test]["status"], "FAIL")

    def test_clean_evidence_passes_integrity(self):
        r = self.run_ev(copy.deepcopy(self.S.ev))
        for k, t in r["tests"].items():
            if k.startswith("I"):
                self.assertIn(t["status"], ("PASS", "NOT_APPLICABLE"), k)
        self.assertEqual(r["profile"], "calibration")
        self.assertGreater(r["info"]["purged_label_tail_rows"], 0)          # 24h rows of the last day
        self.assertNotEqual(r["verdict"], "INVALID_EVIDENCE")

    def test_schema_refusals(self):
        ev = copy.deepcopy(self.S.ev)
        ev["risk_inputs"] = {"exposure": 1}
        self.assertInvalid(ev, "I01_schema")
        ev = copy.deepcopy(self.S.ev)
        ev["candidate"]["kind"] = "information"
        self.assertInvalid(ev, "I01_schema")
        ev = copy.deepcopy(self.S.ev)
        ev["candidate"]["direction"] = "short"
        self.assertInvalid(ev, "I01_schema")

    def test_dataset_binding(self):
        ev = copy.deepcopy(self.S.ev)
        ev["dataset"] = {"dataset_id": "synthetic", "dataset_hash": "cd" * 32}
        self.assertInvalid(ev, "I02_binding")
        ev = copy.deepcopy(self.S.ev)
        ev["registration"]["dataset"] = None
        self.assertInvalid(ev, "I02_binding")

    def test_binding(self):
        ev = copy.deepcopy(self.S.ev)
        ev["registration"]["f0_contract_set_sha256"] = "0" * 64
        self.assertInvalid(ev, "I02_binding")
        ev = copy.deepcopy(self.S.ev)
        ev["candidate"]["plan_entry_sha256"] = "1" * 64
        self.assertInvalid(ev, "I02_binding")
        ev = copy.deepcopy(self.S.ev)
        ev["registration"]["considered_trials"] = []
        self.assertInvalid(ev, "I02_binding")

    def test_w3_microsecond_boundary(self):
        w3e_floor = int(LG.W3_END.timestamp() * 1000)               # ...43.497 < .497803: inside W3
        ev = copy.deepcopy(self.S.ev)
        ev["rows"][0]["t_ms"] = w3e_floor
        self.assertEqual(self.run_ev(ev)["tests"]["I03_w3"]["status"], "FAIL")
        ev["rows"][0]["t_ms"] = w3e_floor + 1
        ev["rows"][0]["label_end_ms"] = w3e_floor + 1 + PN.HORIZON_MS["24h"] + 1000
        self.assertEqual(self.run_ev(ev)["tests"]["I03_w3"]["status"], "PASS")

    def test_window_must_equal_frozen_layout(self):
        ev = copy.deepcopy(self.S.ev)
        ev["window"]["validation_days"] = list(range(15, 25))
        ev["window"]["day_start_ms"] = {k: v for k, v in ev["window"]["day_start_ms"].items() if int(k) < 25}
        ev["rows"] = [r for r in ev["rows"] if r["day"] < 25]
        self.assertInvalid(ev, "I04_window")
        ev = copy.deepcopy(self.S.ev)
        ev["rows"][0]["day"] = 29
        self.assertInvalid(ev, "I04_window")

    def test_pit(self):
        ev = copy.deepcopy(self.S.ev)
        ev["rows"][3]["feat_avail_ms"] = ev["rows"][3]["t_ms"] + 1
        self.assertInvalid(ev, "I05_pit")
        ev = copy.deepcopy(self.S.ev)
        ev["rows"][3]["entry_ms"] = ev["rows"][3]["t_ms"]
        self.assertInvalid(ev, "I05_pit")

    def test_duplicates_and_grid(self):
        ev = copy.deepcopy(self.S.ev)
        ev["rows"].append(dict(ev["rows"][5]))
        self.assertInvalid(ev, "I06_unique_grid")
        ev = copy.deepcopy(self.S.ev)
        ev["rows"][5]["t_ms"] += 1000
        ev["rows"][5]["entry_ms"] += 1000
        ev["rows"][5]["label_end_ms"] += 1000
        self.assertInvalid(ev, "I06_unique_grid")

    def test_claimed_positions_must_match_rebuild(self):
        ev = copy.deepcopy(self.S.ev)
        ev["claimed_positions"] = [[r["sym"], r["t_ms"]] for r in ev["rows"] if r["sig"]]
        self.assertInvalid(ev, "I07_positions_match")

    def test_mixed_quote_currency_fails_closed(self):
        ev = copy.deepcopy(self.S.ev)
        for r in ev["rows"]:
            if r["sym"] == "SYNB00USDT":
                r["sym"] = "SYNB00USDC"
        self.assertInvalid(ev, "I08_quote_currency")

    def test_signal_on_non_evaluable_row(self):
        ev = copy.deepcopy(self.S.ev)
        r = next(r for r in ev["rows"] if r["sig"])
        r["elig"] = 0
        self.assertInvalid(ev, "I09_signal_eligible")

    def test_implausible_leak_flagged(self):
        rd = SY.Round(11, self.S.cs.plan, mode="lookahead_hidden", only=[CAND])
        ev = rd.evidence(CAND, _reg(self.S.cs, rd, CAND))
        r = self.run_ev(ev)
        self.assertEqual(r["verdict"], "INVALID_EVIDENCE")
        self.assertEqual(r["tests"]["I10_implausible"]["status"], "FAIL")


class TestVerdicts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = Shared.get()

    def test_deterministic(self):
        a = self.S.bat.evaluate(copy.deepcopy(self.S.ev), {})
        b = self.S.bat.evaluate(copy.deepcopy(self.S.ev), {})
        self.assertEqual(a["verdict_id"], b["verdict_id"])
        rows = copy.deepcopy(self.S.ev)
        random.Random(1).shuffle(rows["rows"])
        c = self.S.bat.evaluate(rows, {})
        self.assertEqual(a["verdict"], c["verdict"])
        self.assertEqual(a["info"]["alpha"]["alpha"], c["info"]["alpha"]["alpha"])

    def test_precedence(self):
        bat = self.S.bat
        T = {"x": {"status": "FAIL", "effect_if_not_pass": "provisional"},
             "y": {"status": "UNDETERMINABLE", "effect_if_not_pass": "fragile"},
             "z": {"status": "FAIL", "effect_if_not_pass": "insufficient"}}
        self.assertEqual(bat._finish({}, {}, T, {})["verdict"], "FRAGILE")
        T["w"] = {"status": "FAIL", "effect_if_not_pass": "reject"}
        self.assertEqual(bat._finish({}, {}, T, {})["verdict"], "REJECTED")
        T["v"] = {"status": "FAIL", "effect_if_not_pass": "min_n"}
        self.assertEqual(bat._finish({}, {}, T, {})["verdict"], "INSUFFICIENT_EVIDENCE")
        T["u"] = {"status": "FAIL", "effect_if_not_pass": "invalid"}
        self.assertEqual(bat._finish({}, {}, T, {})["verdict"], "INVALID_EVIDENCE")
        self.assertEqual(bat._finish({}, {}, {"a": {"status": "PASS", "effect_if_not_pass": "reject"}}, {})["verdict"],
                         "PROVISIONAL")

    def test_min_n_refusal_computes_nothing(self):
        rd = SY.Round(12, self.S.cs.plan, mode="small_n", only=[CAND])
        r = self.S.bat.evaluate(rd.evidence(CAND, _reg(self.S.cs, rd, CAND)), {})
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(r["tests"]["N01_min_n"]["status"], "FAIL")
        self.assertNotIn("alpha", r["info"])

    def test_fee_blind_and_relative_trap_rejected(self):
        ev = copy.deepcopy(self.S.ev)
        for r in ev["rows"]:
            for k in ("net_idealized", "net_base", "net_stress"):
                if r[k] is not None:
                    r[k] -= 0.03                               # costs far above the gross edge
        res = self.S.bat.evaluate(ev, {})
        self.assertEqual(res["verdict"], "REJECTED")
        self.assertEqual(res["tests"]["A01_net_alpha_positive"]["status"], "FAIL")

    def test_screen_needs_the_round(self):
        r = self.S.bat.evaluate(copy.deepcopy(self.S.ev), {})
        self.assertIn(r["tests"]["S02_selection_screen"]["status"], ("UNDETERMINABLE",))
        self.assertNotIn(r["verdict"], ("FORWARD_CONFIRMATION_REQUIRED", "PROVISIONAL"))

    def test_round_context_and_plateau_inputs(self):
        sums = [B.core_summary(self.S.bat, self.S.rd.evidence(c["plan_id"], _reg(self.S.cs, self.S.rd, c["plan_id"])))
                for c in self.S.rd.cells]
        ctx = B.round_context(sums, total_trials=48, exclude=self.S.rd.trial_id(CAND))
        self.assertNotIn(self.S.rd.trial_id(CAND), ctx["round_series"])
        self.assertEqual(set(ctx["neighbour_info_effects"]), {c["plan_id"] for c in self.S.rd.cells})
        r = self.S.bat.evaluate(copy.deepcopy(self.S.ev), ctx)
        self.assertIn(r["tests"]["R08_plateau"]["status"], ("UNDETERMINABLE",))      # H01-003 has no result
        self.assertIn(r["tests"]["M02_deflated_sharpe"]["status"], ("PASS", "FAIL"))


class TestForwardAndVersions(unittest.TestCase):
    def test_forward_length_and_harm(self):
        fwd = C.default().forward
        x = [0.004 + 0.01 * math.sin(i * 1.7) for i in range(13)]
        L = FW.forward_length(x, fwd, 3)
        self.assertGreaterEqual(L["n_days"], fwd["min_days"])
        self.assertLessEqual(L["n_days"], fwd["max_days"])
        with self.assertRaises(FW.ForwardError):
            FW.forward_length([-v for v in x], fwd, 3)
        bad = [-0.03 + 0.002 * math.sin(i) for i in range(14)]
        self.assertTrue(FW.harm_check(bad, 28, fwd, 3, 3, 199, 1)["stop"])
        good = [0.01 + 0.01 * math.sin(i) for i in range(14)]
        self.assertFalse(FW.harm_check(good, 28, fwd, 3, 3, 199, 1)["stop"])

    def test_forward_verdict_mapping(self):
        fwd = C.default().forward
        rec = {"verdict": "PROVISIONAL", "window": {"kind": "forward"}, "info": {"alpha": {"alpha": 0.001}}}
        rec["info"]["core"] = {"mean": 0.001}
        self.assertEqual(FW.forward_verdict(rec, 0.01, fwd)["verdict"], "FORWARD_DECAYED")
        rec["info"]["core"] = {"mean": 0.008}
        self.assertEqual(FW.forward_verdict(rec, 0.01, fwd)["verdict"], "FORWARD_CONSISTENT")
        self.assertEqual(FW.forward_verdict(rec, 0.01, fwd, harm_stopped=True)["verdict"], "FORWARD_REJECTED")
        rec["verdict"] = "FRAGILE"
        self.assertEqual(FW.forward_verdict(rec, 0.01, fwd)["verdict"], "FORWARD_INSUFFICIENT")
        with self.assertRaises(FW.ForwardError):
            FW.forward_verdict({"verdict": "PROVISIONAL", "window": {"kind": "in_sample"}}, 0.01, fwd)

    def test_applicable_version_never_retroactive(self):
        vs = [{"version": "1.0.0", "contract_set_sha256": "a", "frozen_at_ledger_seq": -1},
              {"version": "2.0.0", "contract_set_sha256": "b", "frozen_at_ledger_seq": 40}]
        self.assertEqual(C.applicable_version(vs, 10)["version"], "1.0.0")
        self.assertEqual(C.applicable_version(vs, 41)["version"], "2.0.0")
        self.assertEqual(C.applicable_version(vs, None)["version"], "2.0.0")
        with self.assertRaises(C.ContractError):
            C.applicable_version(vs[1:], 10)
        self.assertEqual(C.governing_verdict(["PROVISIONAL", "FRAGILE"]), "FRAGILE")
        with self.assertRaises(C.ContractError):
            C.governing_verdict(["PROVEN"])

    def test_registration_binds_ledger_and_counts_hidden_siblings(self):
        cs = C.default()
        tmp = tempfile.mkdtemp(prefix="p2f0-led-")
        try:
            proto, frozen = D0.load("protocol_v1.json"), D0.verify_frozen()
            ids = []
            for pid in ("P2D-R1-H01-004", "P2D-R1-H01-002"):
                e = next(t for t in cs.plan["trials"] if t["plan_id"] == pid)
                spec = D0.ledger_spec(e, proto, frozen, code_commit="a65bbfb",
                                      dataset={"dataset_id": "synthetic", "dataset_hash": "0" * 64},
                                      train_period={"start": "2026-10-05T00:00:00Z", "end": "2026-10-18T00:00:00Z"},
                                      validation_period={"start": "2026-10-19T00:00:00Z",
                                                         "end": "2026-11-02T00:00:00Z"})
                ids.append(LG.Ledger(tmp).create_trial(spec, now="2026-11-02T01:00:00.000000Z"))
            head = LG.Ledger(tmp).head()
            ds = {"dataset_id": "synthetic", "dataset_hash": "0" * 64}
            with self.assertRaises(C.ContractError):
                C.registration(cs, trial_id=ids[0], plan_id="P2D-R1-H01-004", considered_trials=ids,
                               code_commit="a65bbfb", ledger_anchor=head, selection_rule="lowest S02 p")
            reg = C.registration(cs, trial_id=ids[0], plan_id="P2D-R1-H01-004", considered_trials=[ids[0]],
                                 code_commit="a65bbfb", ledger_anchor=head, selection_rule="lowest S02 p",
                                 now="2026-11-02T02:00:00Z", dataset=ds)
            rep = C.check_registration_against_ledger(reg, tmp)
            self.assertFalse(rep["ok"])
            self.assertTrue(any("missing from considered_trials" in e for e in rep["errors"]))
            reg = C.registration(cs, trial_id=ids[0], plan_id="P2D-R1-H01-004", considered_trials=ids,
                                 code_commit="a65bbfb", ledger_anchor=head, selection_rule="lowest S02 p",
                                 now="2026-11-02T02:00:00Z", dataset=ds)
            rep = C.check_registration_against_ledger(reg, tmp)
            self.assertTrue(rep["ok"], rep["errors"])
            bad = C.registration(cs, trial_id=ids[0], plan_id="P2D-R1-H01-004", considered_trials=ids,
                                 code_commit="a65bbfb", ledger_anchor=head, selection_rule="lowest S02 p",
                                 now="2026-11-02T02:00:00Z", dataset={"dataset_id": "x", "dataset_hash": "1" * 64})
            self.assertTrue(any("dataset" in e for e in C.check_registration_against_ledger(bad, tmp)["errors"]))
            self.assertEqual(rep["total_trials_excluding_benchmarks"], 2)
            self.assertIsNone(C.first_result_seq(tmp, ids))
            with self.assertRaises(C.ContractError):
                C.registration(cs, trial_id=ids[0], plan_id="P2D-R1-H99-001", considered_trials=ids,
                               code_commit="a65bbfb", ledger_anchor=head, selection_rule="x", dataset=ds)
        finally:
            shutil.rmtree(tmp, True)


if __name__ == "__main__":
    unittest.main()
