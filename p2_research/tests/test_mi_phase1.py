"""MI-ML Phase 1: PIT boundary tests, K1 fold-calendar assertions, K5 derivation-map fixtures, contract integrity.

Synthetic / calendar-only. No real data, no outcomes, no W3, no Collector data; no simulation and no model fitting.
"""
import copy
import hashlib
import json
import math
import os
import re
import unittest
from unittest import mock

from p2_research.mi import contract as MC
from p2_research.mi import derive as DV
from p2_research.mi import folds as FD
from p2_research.mi import timeline as TL

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTRACT_SET_SHA256 = "fdf3366480976db6ada1ac90b62f6b6db1edc35a59d1f3527cfcd6fcbf28e157"
T = TL.ms(2024, 3, 5, 8)              # a 4h close


# ====================================================================== C1 / D14: PIT boundary tests (11)
class PITBoundary(unittest.TestCase):
    def test_01_availability_equal_to_issuance_admitted_one_ms_later_refused(self):
        issue = TL.t_issue(T, "4h")
        end_ok = issue - TL.DELTA_AVAIL_MS["4h"]                       # t_avail == t_issue
        self.assertTrue(TL.feature_admissible(end_ok, "4h", issue))
        self.assertFalse(TL.feature_admissible(end_ok + 1, "4h", issue))   # t_avail = t_issue + 1 ms
        self.assertTrue(TL.feature_admissible(T, "4h", issue))               # the decision bar itself
        self.assertFalse(TL.feature_admissible(T + TL.TF_MS["4h"], "4h", issue))

    def test_02_archive_us_and_rest_ms_close_map_to_one_canonical_end(self):
        op = T - TL.TF_MS["4h"]
        end = TL.canonical_end(op, "4h")
        self.assertEqual(TL.end_from_raw_close(end * 1000 - 1, "4h", "us"), end)
        self.assertEqual(TL.end_from_raw_close(end - 1, "4h", "ms"), end)
        with self.assertRaises(TL.PITViolation):
            TL.end_from_raw_close(end * 1000 - 2, "4h", "us")
        with self.assertRaises(TL.PITViolation):
            TL.canonical_end(op + 1, "4h")

    def test_03_t1_label_never_reads_decision_bar_or_pre_act_bars(self):
        w = TL.t1_window(T)
        self.assertEqual(w["t_issue"], T + 180_000)
        self.assertEqual(w["t_act"], T + 240_000)
        self.assertEqual(w["label_open_from"], T + 15 * TL.MIN)
        self.assertFalse(TL.t1_label_bar_ok(T - 15 * TL.MIN, T))            # inside the decision bar
        self.assertFalse(TL.t1_label_bar_ok(T, T))                          # opens before t_act
        self.assertTrue(TL.t1_label_bar_ok(T + 15 * TL.MIN, T))             # opens exactly at label start
        self.assertTrue(TL.t1_label_bar_ok(T + 15 * TL.MIN + 24 * TL.H - 15 * TL.MIN, T))
        self.assertFalse(TL.t1_label_bar_ok(T + 15 * TL.MIN + 24 * TL.H, T))
        self.assertIn("NOT an executable entry price", w["reference"])

    def test_04_t2_level_excludes_breakout_bar(self):
        ends = TL.t2_level_bar_ends(T)
        self.assertEqual(len(ends), 20)
        self.assertNotIn(T, ends)
        self.assertEqual(max(ends), T - TL.TF_MS["4h"])
        self.assertTrue(TL.feature_admissible(T, "4h", TL.t_issue(T, "4h")))   # breakout close is an input

    def test_05_t2_label_uses_closes_after_t_act_never_the_breakout_close(self):
        ends = TL.t2_label_close_ends(T)
        self.assertNotIn(T, ends)
        self.assertEqual(ends[0], T + TL.TF_MS["4h"])                        # t+1 closes after t_act
        self.assertGreater(ends[0], TL.t_act(T, "4h"))
        self.assertEqual(len(ends), 6)
        self.assertEqual(TL.t2_window(T)["label_end"], T + 24 * TL.H)

    def test_06_t3_issue_admits_day_d_refuses_d_plus_1(self):
        d = TL.ms(2024, 3, 5)
        w = TL.t3_window(d)
        self.assertEqual(w["t_issue"], d + TL.D + 360_000)                   # d+1 00:06
        self.assertTrue(TL.feature_admissible(d + TL.D, "1d", w["t_issue"]))
        self.assertFalse(TL.feature_admissible(d + 2 * TL.D, "1d", w["t_issue"]))
        self.assertEqual(w["label_end"], d + 8 * TL.D)

    def test_07_month_and_fold_refits_use_only_prior_data(self):
        m = TL.ms(2024, 4, 1)
        cut = TL.universe_cutoff(m)
        self.assertFalse(TL.feature_admissible(m, "1d", cut))                # the bar ending AT month start: not yet
        self.assertTrue(TL.feature_admissible(m - TL.D, "1d", cut))
        self.assertFalse(TL.feature_admissible(m, "4h", cut))

    def test_08_gap_is_null_and_late_bars_never_back_filled(self):
        issue = TL.t_issue(T, "4h")
        bars = [(T - TL.TF_MS["4h"], "4h", None), (T, "4h", issue + 1)]       # decision bar arrived late
        got = TL.admissible_bars(bars, issue)
        self.assertEqual([b[0] for b in got], [T - TL.TF_MS["4h"]])
        self.assertEqual(TL.admissible_bars([], issue), [])                  # gap -> nothing -> null feature

    def test_09_freeze_is_a_hard_failure_for_features_and_labels(self):
        f = TL.FREEZE_MS
        end_after = f - (f % TL.TF_MS["4h"]) + TL.TF_MS["4h"]
        with self.assertRaises(TL.FreezeViolation):
            TL.feature_admissible(end_after, "4h", end_after + TL.H)
        with self.assertRaises(TL.FreezeViolation):
            TL.t2_label_close_ends(end_after - 2 * TL.TF_MS["4h"])
        with self.assertRaises(TL.FreezeViolation):
            TL.t1_label_bar_ok(end_after - TL.TF_MS["15m"], end_after - 8 * TL.H)
        with self.assertRaises(TL.FreezeViolation):
            TL.t3_window(TL.ms(2026, 8, 15))
        self.assertEqual(TL.FREEZE_MS, TL.ms(2026, 8, 19, 9, 33, 46))

    def test_10_one_bar_shift_canary_changes_features(self):
        closes = [100.0, 101.0, 99.5, 102.0, 101.5]
        self.assertNotEqual(TL.last_close_return(closes), TL.last_close_return(closes[:-1]))

    def test_11_doubling_every_delta_changes_only_boundary_cases(self):
        bars = [(T - k * TL.TF_MS["15m"], "15m", None) for k in range(0, 40)] + [(T, "4h", None), (T - TL.TF_MS["4h"], "4h", None)]
        a = TL.admissible_bars(bars, TL.t_issue(T, "4h", 1), 1)
        b = TL.admissible_bars(bars, TL.t_issue(T, "4h", 2), 2)
        self.assertEqual(a, b)                                               # no boundary case on this grid
        self.assertEqual(TL.t1_window(T, scale=2)["label_open_from"], T + 15 * TL.MIN)
        d = TL.ms(2024, 3, 5)
        self.assertTrue(TL.feature_admissible(d + TL.D, "1d", TL.t3_window(d, scale=2)["t_issue"], 2))


# ====================================================================== K1: fold-calendar assertions
class FoldCalendar(unittest.TestCase):
    def test_sixteen_quarterly_folds(self):
        fs = FD.folds()
        self.assertEqual(len(fs), 16)
        self.assertEqual(fs[0][0], TL.ms(2021, 1, 1))
        self.assertEqual(fs[-1][1], TL.ms(2025, 1, 1))

    def test_s_maj_all_tasks_pass_with_2018_start(self):
        for task, expect in (("T1", 1094.667), ("T2", 1094.833), ("T3", 1088.0)):
            rep = FD.assert_k1(task, "S-MAJ")
            self.assertEqual(len(rep["folds"]), 16)
            self.assertGreaterEqual(rep["min_train_span_days"], 730)
            self.assertAlmostEqual(rep["folds"][0]["train_span_days"], expect, places=2)
            self.assertGreater(rep["folds"][-1]["eval_censored"], 0)        # labels crossing the HLE are censored

    def test_old_2019_start_fails_closed(self):
        with mock.patch.dict(FD.TRAIN_START, {"S-MAJ": TL.ms(2019, 1, 1)}):
            for task in ("T1", "T2", "T3"):
                with self.assertRaises(FD.FoldAssertionError):
                    FD.assert_k1(task, "S-MAJ")

    def test_s_alt_exempt_from_span_but_boundaries_hold(self):
        for task, expect in (("T1", 729.667), ("T2", 729.833), ("T3", 723.0)):
            rep = FD.assert_k1(task, "S-ALT")
            self.assertAlmostEqual(rep["folds"][0]["train_span_days"], expect, places=2)

    def test_lookback_precondition(self):
        with mock.patch.object(FD, "SMAJ_FIRST_DATA", TL.ms(2017, 12, 1)):
            with self.assertRaises(FD.FoldAssertionError):
                FD.assert_k1("T1", "S-MAJ")

    def test_training_never_reaches_fold_and_hle_boundaries(self):
        for task in ("T1", "T2", "T3"):
            for F, _ in FD.folds():
                last = FD.last_eligible_training(task, F)
                self.assertLessEqual(TL.label_end(task, last), F)
                self.assertLessEqual(last, F - FD.EMBARGO_MS[task])
            hle = FD.last_eligible_training(task, FD.HLE_START)
            self.assertLessEqual(TL.label_end(task, hle), FD.HLE_START)


# ====================================================================== K5: derivation-map fixtures
def _proto():
    with open(os.path.join(MC.SET_DIR, "mi_phase1s_protocol_v1_0.json"), encoding="utf-8") as fh:
        return json.load(fh)


SET_SHA, PROTO_SHA = "s" * 64, "p" * 64


def make_output(proto, *, fp=None, power=None, final=None, mutate=None):
    """A synthetic, well-formed Phase 1S output. fp(cell, step) -> fp_k; power(cell, level) -> pass_k."""
    reps = proto["reps"]
    fp = fp or (lambda c, s: 30)
    power = power or (lambda c, lvl: 190)
    final = final or {"T1": 0, "T2": 0, "T3": 0}
    cells = {}
    for c in proto["cells"]:
        steps = range(0, final[c["task"]] + 1)
        cells[c["cell_id"]] = {
            "null": {str(s): {"fp_k": fp(c, s), "n": reps["null"], "b3_reject_k": 40} for s in steps},
            "skill": {lvl: {"pass_k": power(c, lvl), "n": reps["skill"], "max_bss": 0.01 + float(lvl)} for lvl in proto["skill_levels"]},
            "miscal": {v: {"reject_k": 190, "n": reps["miscal"]} for v in proto["meta_acceptance"]["b3_power_variants"]},
            "leak": {"fire_k": 99, "n": reps["leak"]}}
    out = {"record": "tsb.mi.phase1s_output", "record_version": 1, "status": "COMPLETE", "contract_set_sha256": SET_SHA,
           "protocol_sha256": PROTO_SHA, "budget": {"enforcement": "cgroup_cpu_budget_guard_v1", "enforcement_verified": True,
                                                   "cap_cpu_s": 28800, "cumulative_cpu_s": 20000.0, "breach": False},
           "final_step": final, "l2": {"null_fp_k": 30, "n": reps["l2_null"]}, "cells": cells}
    if mutate:
        mutate(out)
    b = DV.canon(out).encode()
    return b, hashlib.sha256(b).hexdigest()


class DerivationMap(unittest.TestCase):
    def setUp(self):
        self.p = _proto()

    def run_map(self, b, h):
        return DV.derive(b, h, self.p, SET_SHA, PROTO_SHA)

    def stop(self, code, **kw):
        b, h = make_output(self.p, **kw)
        with self.assertRaises(DV.DerivationStop) as cm:
            self.run_map(b, h)
        self.assertEqual(cm.exception.code, code, str(cm.exception))

    def test_pass_all_tasks_step0(self):
        r = self.run_map(*make_output(self.p))
        for t in ("T1", "T2", "T3"):
            self.assertEqual(r["tasks"][t]["ladder_step"], 0)
            self.assertEqual(r["tasks"][t]["alpha"], 0.05)
            self.assertEqual(r["tasks"][t]["status"], "INFERENTIAL")
        self.assertEqual(r["tasks"]["T1"]["block_mean_days"], 5)
        self.assertEqual(r["tasks"]["T3"]["block_mean_days"], 28)
        self.assertEqual(r["tasks"]["T1"]["n_star_positives"], 62)
        self.assertEqual(r["tasks"]["T2"]["n_star_positives"], 45)
        self.assertEqual(r["tasks"]["T2"]["breakout_count_threshold"], 150)
        self.assertEqual(r["tasks"]["T2"]["b2_check"], "CONSERVATIVE_VERIFIED")
        self.assertEqual(r["tasks"]["T3"]["n_star_days"], 517)
        self.assertAlmostEqual(r["tasks"]["T1"]["trip_wire_ceiling_bss"], 0.06)
        self.assertEqual(r["tasks"]["T1"]["exclusions"], [])

    def test_deterministic(self):
        b, h = make_output(self.p)
        self.assertEqual(DV.canon(self.run_map(b, h)), DV.canon(self.run_map(b, h)))

    def test_ladder_step1_and_step2(self):
        f1 = lambda c, s: 60 if (c["task"] == "T1" and s == 0) else 30
        r = self.run_map(*make_output(self.p, fp=f1, final={"T1": 1, "T2": 0, "T3": 0}))
        self.assertEqual((r["tasks"]["T1"]["ladder_step"], r["tasks"]["T1"]["block_mean_days"], r["tasks"]["T1"]["alpha"]), (1, 10, 0.05))
        f2 = lambda c, s: 60 if (c["task"] == "T1" and s < 2) else 30
        r = self.run_map(*make_output(self.p, fp=f2, final={"T1": 2, "T2": 0, "T3": 0}))
        self.assertEqual((r["tasks"]["T1"]["ladder_step"], r["tasks"]["T1"]["block_mean_days"], r["tasks"]["T1"]["alpha"]), (2, 10, 0.025))

    def test_ladder_fail_is_descriptive_and_failing_cells_preserved(self):
        bad = "T1|pi=0.05|phi=0|rho=0|brk=0"
        f = lambda c, s: 80 if c["cell_id"] == bad else 30
        r = self.run_map(*make_output(self.p, fp=f, final={"T1": 2, "T2": 0, "T3": 0}))
        self.assertEqual(r["tasks"]["T1"]["ladder_step"], DV.FAIL)
        self.assertEqual(r["tasks"]["T1"]["status"], "DESCRIPTIVE_ONLY")
        self.assertEqual(r["tasks"]["T1"]["failing_nonstress_cells"], [bad])

    def test_failing_stress_cell_becomes_exclusion_only(self):
        st = "T1|pi=0.05|phi=0.95|rho=0.5|brk=1"
        r = self.run_map(*make_output(self.p, fp=lambda c, s: 90 if c["cell_id"] == st else 30))
        self.assertEqual(r["tasks"]["T1"]["exclusions"], [st])
        self.assertEqual(r["tasks"]["T1"]["status"], "INFERENTIAL")

    def test_exact_point_boundary_and_wilson_tie(self):
        acc = self.p["meta_acceptance"]
        self.assertTrue(DV.null_pass({"fp_k": 50, "n": 1000}, 1000, "c", 0, acc))     # 5.0 % exactly passes
        self.assertFalse(DV.null_pass({"fp_k": 51, "n": 1000}, 1000, "c", 0, acc))
        with mock.patch.object(DV, "wilson_upper", return_value=0.07):
            self.assertFalse(DV.null_pass({"fp_k": 30, "n": 1000}, 1000, "c", 0, acc))  # tie -> conservative fail

    def test_upward_closed_n_star_and_infeasible(self):
        pw = lambda c, lvl: 190 if (c["task"] != "T1" or c["positives"] >= 310) else 100
        self.assertEqual(self.run_map(*make_output(self.p, power=pw))["tasks"]["T1"]["n_star_positives"], 310)
        pw2 = lambda c, lvl: 100 if (c["task"] == "T1" and c["positives"] == 1241 and c["rho"] == 0.5) else (
            190 if (c["task"] != "T1" or c["positives"] >= 310) else 100)
        r = self.run_map(*make_output(self.p, power=pw2))
        self.assertIsNone(r["tasks"]["T1"]["n_star_positives"])
        self.assertEqual(r["tasks"]["T1"]["status"], "INSUFFICIENT_ALWAYS")
        r = self.run_map(*make_output(self.p, power=lambda c, lvl: 100 if c["task"] == "T2" else 190))
        self.assertEqual(r["tasks"]["T2"]["status"], "DESCRIPTIVE_ONLY")

    def test_b2_reference_not_conservative_stops(self):
        pw = lambda c, lvl: 100 if (c["task"] == "T2" and c["pi"] == 0.2 and c["n_events"] == 150) else 190
        self.stop("B2_REFERENCE_NOT_CONSERVATIVE", power=pw)

    def test_b2_threshold_beyond_grid_is_descriptive(self):
        pw = lambda c, lvl: (190 if c["positives"] >= 750 else 100) if c["task"] == "T2" else 190
        r = self.run_map(*make_output(self.p, power=pw))
        self.assertEqual(r["tasks"]["T2"]["n_star_positives"], 750)
        self.assertEqual(r["tasks"]["T2"]["breakout_count_threshold"], 2500)
        self.assertEqual((r["tasks"]["T2"]["status"], r["tasks"]["T2"]["b2_check"]), ("DESCRIPTIVE_ONLY", "THRESHOLD_BEYOND_GRID"))

    def test_t3_fallbacks(self):
        r = self.run_map(*make_output(self.p, power=lambda c, lvl: 90 if c["task"] == "T3" else 190))
        self.assertEqual(r["tasks"]["T3"]["status"], "DESCRIPTIVE_ONLY")
        r = self.run_map(*make_output(self.p, power=lambda c, lvl: 150 if c["task"] == "T3" else 190))
        self.assertEqual(r["tasks"]["T3"]["status"], "INSUFFICIENT_ALWAYS")

    # ---- every STOP precondition
    def test_stop_hash_and_parse(self):
        b, h = make_output(self.p)
        with self.assertRaises(DV.DerivationStop) as cm:
            self.run_map(b, "0" * 64)
        self.assertEqual(cm.exception.code, "HASH_MISMATCH")
        with self.assertRaises(DV.DerivationStop) as cm:
            self.run_map(b"{not json", hashlib.sha256(b"{not json").hexdigest())
        self.assertEqual(cm.exception.code, "UNPARSEABLE")

    def test_stop_record_status_protocol(self):
        self.stop("WRONG_RECORD", mutate=lambda o: o.update(record="x"))
        self.stop("INCOMPLETE_STATUS", mutate=lambda o: o.update(status="INCOMPLETE"))
        self.stop("PROTOCOL_MISMATCH", mutate=lambda o: o.update(protocol_sha256="q" * 64))

    def test_stop_budget(self):
        self.stop("BUDGET_NOT_ENFORCED", mutate=lambda o: o["budget"].update(enforcement="wall_clock_only"))
        self.stop("BUDGET_NOT_ENFORCED", mutate=lambda o: o["budget"].update(enforcement_verified=False))
        self.stop("BUDGET_BREACH", mutate=lambda o: o["budget"].update(cumulative_cpu_s=28800.5))
        self.stop("BUDGET_BREACH", mutate=lambda o: o["budget"].update(breach=True))
        self.stop("UNRESOLVED_FIELD", mutate=lambda o: o["budget"].update(cumulative_cpu_s=None))

    def test_stop_grid_reps_fields(self):
        self.stop("INCOMPLETE_GRID", mutate=lambda o: o["cells"].pop("T3|persistence=0.85|shape=uniform"))
        self.stop("INCOMPLETE_GRID", mutate=lambda o: o["cells"].update({"T9|x": {}}))
        self.stop("INCOMPLETE_REPS", mutate=lambda o: o["cells"]["T1|pi=0.01|phi=0|rho=0|brk=0"]["null"]["0"].update(n=999))
        self.stop("UNRESOLVED_FIELD", mutate=lambda o: o["cells"]["T2|n=400|pi=0.3|rho=0"]["skill"]["0.05"].update(max_bss="nan"))
        self.stop("UNRESOLVED_FIELD", mutate=lambda o: o["cells"]["T2|n=400|pi=0.3|rho=0"]["skill"].pop("0.02"))
        self.stop("UNRESOLVED_FIELD", mutate=lambda o: o["cells"]["T1|pi=0.01|phi=0|rho=0|brk=0"]["null"]["0"].update(fp_k=True))
        self.stop("INCOMPLETE_REPS", mutate=lambda o: o["l2"].update(n=799))

    def test_stop_ladder_and_final_step(self):
        f1 = lambda c, s: 60 if (c["task"] == "T1" and s == 0) else 30
        self.stop("UNRESOLVED_LADDER", fp=f1)                                 # step 1 needed but never run
        self.stop("FINAL_STEP_MISMATCH", mutate=lambda o: o["final_step"].update(T2=1) or
                  [cell["null"].update({"1": dict(cell["null"]["0"])}) for cid, cell in o["cells"].items() if cid.startswith("T2")])

    def test_stop_gates_outside_ladder(self):
        self.stop("L2_MODEL_FIT_INFLATION", mutate=lambda o: o["l2"].update(null_fp_k=61))
        self.stop("LEAK_CANARY_WEAK", mutate=lambda o: o["cells"]["T3|persistence=0.99|shape=adjacent"]["leak"].update(fire_k=94))
        self.stop("B3_SIZE_FAIL", mutate=lambda o: o["cells"]["T1|pi=0.2|phi=0|rho=0|brk=0"]["null"]["0"].update(b3_reject_k=71))
        self.stop("B3_POWER_FAIL", mutate=lambda o: o["cells"]["T2|n=150|pi=0.5|rho=0"]["miscal"]["slope_0.7"].update(reject_k=159))


# ====================================================================== contract integrity, genesis, isolation
class ContractIntegrity(unittest.TestCase):
    def test_frozen_set_verifies_and_hash_is_pinned(self):
        rep = MC.verify()
        self.assertEqual(rep["contract_set_sha256"], CONTRACT_SET_SHA256)

    def test_protocol_grid_shape(self):
        p = _proto()
        by = {t: [c for c in p["cells"] if c["task"] == t] for t in ("T1", "T2", "T3")}
        self.assertEqual((len(by["T1"]), len(by["T2"]), len(by["T3"])), (24, 18, 6))
        self.assertEqual(sum(c["stress"] for c in p["cells"]), 11)
        self.assertEqual(sorted({c["positives"] for c in by["T1"]}), [62, 310, 1241])
        self.assertEqual(p["budget"]["cap_cpu_s"], 28800)
        self.assertEqual(p["budget"]["required_enforcement"], "cgroup_cpu_budget_guard_v1")
        self.assertIn("independently of wall-clock", p["budget"]["principle"])
        self.assertEqual(p["reps"]["null"], 1000)

    def test_contract_core_values(self):
        c = MC.load("mi_contract_v1_0.json")
        self.assertEqual(c["segments"]["development"]["S-MAJ"][0], "2018-01-01")
        self.assertEqual(c["segments"]["folds"]["n"], 16)
        self.assertEqual(c["universe"]["inferential"], "S-MAJ = BTCUSDT, ETHUSDT")
        self.assertIn("REFERENCE price, not an executable entry price", c["tasks"]["T1"]["reference"])
        self.assertEqual(c["utility"]["label"], "REFERENCE_PRICE_COUNTERFACTUAL")
        self.assertEqual(c["pit"]["delta_avail_s"], {"15m": 120, "1h": 120, "4h": 120, "1d": 300})

    def test_ledger_genesis_record(self):
        g = json.load(open(os.path.join(ROOT, "p2_research", "mi", "ledger_genesis_v1_0.json"), encoding="utf-8"))
        body = {k: v for k, v in g.items() if k != "genesis_id"}
        self.assertEqual(g["genesis_id"], hashlib.sha256(DV.canon(body).encode()).hexdigest())
        self.assertEqual(g["contract_set_sha256"], CONTRACT_SET_SHA256)
        self.assertEqual(g["head"], {"seq": -1, "event_hash": "0" * 64})
        self.assertFalse(g["ledger_dir"].startswith("/home/tradmin/research-data/trading-signal-bot/p2/"))

    def test_mi_is_never_imported_outside_research(self):
        pat = re.compile(r"(p2_research\.mi|from \.mi\b|from \. import mi\b)")
        skip = {os.path.join(ROOT, "p2_research", "mi"), os.path.join(ROOT, "p2_research", "tests")}
        for dp, dns, fs in os.walk(ROOT):
            dns[:] = [d for d in dns if d not in (".git", "__pycache__", ".venv", "venv", "node_modules")]
            if dp in skip:
                continue
            for f in fs:
                if f.endswith(".py"):
                    with open(os.path.join(dp, f), encoding="utf-8", errors="ignore") as fh:
                        self.assertIsNone(pat.search(fh.read()), os.path.join(dp, f))


if __name__ == "__main__":
    unittest.main()
