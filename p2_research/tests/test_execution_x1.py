"""P2-X1 execution calibration & contract closure tests (synthetic data only; no real data, no W3, no Paper)."""
import copy
import gzip
import hashlib
import json
import os
import shutil
import tempfile
import unittest

from p2_research import builder as BD, instrument as IN, ledger as LG
from p2_research.execution import calibration as CAL, contracts as CT, contracts_v2 as CT2, join as J, model as M
from p2_research.execution import scenario_result as SR
from p2_research.execution.contracts import ContractError
from p2_research.execution.market_state import load_sealed
from p2_research.execution.schema import ASSUMED, DERIVED, ESTIMATED, MEASURED, UNAVAILABLE, check_quantity_tree
from p2_research.tests import common as C
from p2_research.tests.test_execution import BTC, T, grid_state

V2_CONTRACT_SET_SHA256 = "f20e22a5e79b2ab36caa180ca25d652e6e273c2ad72392ed860c2d7f72aa88d0"
V1_CONTRACT_SET_SHA256 = "3c554702948867fa26d4bba95b922f5e1db5902e42b088d9cdc49fdceefeec2f"
V1_FILES = {"terminology_v1.json": "067d55e7ef858d4bded731b8f7a151a496305be043125f2567e459c29bed8381",
            "fee_schedule_v1.json": "62b98d1142a564ad2cea0f7cf1043d21e49ca79f0887b1d76d45124e738e0b70",
            "models_v1.json": "f6c94cb51a37637895e935cb8cd9319ad021e39c2a685e43bd0ea8a85034d37c",
            "scenarios_v1.json": "7196da847be9e72d9164a347e6977f91a19da1439412bcdf0ddb12e6932e19c7",
            "result_schema_v1.json": "a1df0c6174cc9a61119e60c5dc44ee9911a0cfe4563c3b3d0e91a7cd2606b45b"}
P2D0_FROZEN_SHA256 = {"hypotheses_v1.json": "c5df5bf438a03702cc4d3ad49eeada637c74dc2e61cbdcbfa6a7b5c26db933c0",
                      "benchmarks_v1.json": "757f77ebe70912b6e66143e4e14d2c16ea4ab5d2375d91ff9e2a001a417ab96c",
                      "protocol_v1.json": "2843ba9d69691fe2889e4ad7cb6bc4c6dc5c931586764bd8eac822cccdc08f05",
                      "planned_trials_v1.json": "e95a39ce6a9815cc2a86dd096488e942ab0c8f252145b817e80a9d31cf53437e"}
SCEN = ("EXEC-IDEALIZED", "EXEC-BASE", "EXEC-STRESS")


def _sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


class TestCalibrationTool(unittest.TestCase):
    def test_plan_is_predeclared_and_fixed(self):
        plan, sha = CAL.load_plan()
        self.assertEqual(plan["notional_set_quote"], [50.0, 500.0, 5000.0])
        self.assertEqual(plan["execution_timestamps"]["latencies_ms"], [0, 1000, 5000])
        self.assertEqual(plan["id"], "X1-CALIBRATION-PLAN")
        self.assertEqual(sha, _sha(CAL.PLAN_FILE))

    def test_percentiles_and_buckets(self):
        p = CAL.pctl([5, 1, 4, 2, 3], [0.5, 0.99, 0.2])
        self.assertEqual((p["n"], p["min"], p["max"], p["p50"], p["p99"], p["p20"]), (5, 1, 5, 3, 5, 1))
        self.assertEqual(CAL.pctl([], [0.5]), {"n": 0})
        b, lab = [1000, 10000], ["a", "b", "c"]
        self.assertEqual([CAL.bucket(v, b, lab) for v in (0, 1000, 1001, 10000, 10001)], ["a", "a", "b", "b", "c"])
        self.assertEqual([CAL.liq_bucket(v, [10.0], ["lo", "hi"]) for v in (9.9, 10.0)], ["lo", "hi"])

    def test_observer_never_changes_state(self):
        base = C.base_dataset()
        times = [C.D1_MS + 9 * 3_600_000 + k * 900_000 + 390_000 for k in range(4)]
        qts = sorted({t + L for t in times for L in (0, 1000, 5000)})
        seen = []
        a = load_sealed(base, [C.D1], query_times=qts)
        b = load_sealed(base, [C.D1], query_times=qts, observer=seen.append)
        self.assertGreater(len(seen), 0)
        inst = IN.binance_spot_instrument("BTCUSDT")
        for t in times:
            for sc in ("EXEC-IDEALIZED", "EXEC-BASE", "EXEC-STRESS"):
                for side in ("buy", "sell"):
                    self.assertEqual(M.estimate_leg(a, inst, side, 50.0, t, sc), M.estimate_leg(b, inst, side, 50.0, t, sc))

    def test_calibration_deterministic_windowed_and_guarded(self):
        base = C.base_dataset()
        o1, o2 = C.scratch("x1-cal-1"), C.scratch("x1-cal-2")
        m1 = CAL.run(base, [C.D1], o1, "f" * 40)
        m2 = CAL.run(base, [C.D1], o2, "f" * 40)
        self.assertEqual(m1["logical_hash"], m2["logical_hash"])
        for f in ("exec_points.jsonl.gz", "calibration.json", "manifest.json"):
            self.assertEqual(_sha(os.path.join(o1, f)), _sha(os.path.join(o2, f)), f)
        self.assertGreaterEqual(m1["decision_time_range"][0], CAL.W3_END_MS)
        self.assertLess(m1["decision_time_range"][1] + 5000, m1["window_ms"][1])
        self.assertEqual(m1["plan"]["sha256"], _sha(CAL.PLAN_FILE))
        cal = _load(os.path.join(o1, "calibration.json"))
        tb = cal["truth_boundary_field_audit"]
        self.assertEqual(tb["trade_or_aggtrade_records"], [])
        self.assertNotIn("book", tb["exchange_event_time_present_by_type"])
        pb = cal["population_b_execution_timestamps"]
        self.assertIn("walk.t0.L1000.buy.50", pb["aggregates"])
        self.assertTrue(all(k.split(".")[-1] in ("50", "500", "5000") for k in pb["aggregates"] if k.startswith("walk.")))
        for f in ("exec_points.jsonl.gz", "calibration.json"):                   # no return / P&L field anywhere
            with open(os.path.join(o1, f), "rb") as fh:
                raw = fh.read()
            if f.endswith(".gz"):
                import gzip
                raw = gzip.decompress(raw)
            for bad in (b"return", b"pnl", b"net_ret", b"fwd_ret", b"label"):
                self.assertNotIn(bad, raw.lower(), f"{f}: {bad}")
        with self.assertRaises(SystemExit):
            CAL.run(base, [C.D1], os.path.join(base, "out"), "f" * 40)
        with self.assertRaises(SystemExit):
            CAL.run(base, [C.D1], os.path.join(CAL.FORBIDDEN_ROOT, "x1"), "f" * 40)



def _dump(o, p):
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(o, fh, indent=1)


def _leaves(o, path=""):
    if isinstance(o, dict) and set(o) == {"value", "provenance", "reason"}:
        yield path, o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from _leaves(v, f"{path}.{k}" if path else k)


def _generic_fee(**over):
    e = {"venue": "binance", "market_type": "spot", "liquidity_role": "taker", "rate_bps": 10.0,
         "account_scope": "GENERIC_PUBLIC_STANDARD_TIER", "verification_status": "UNVERIFIED_ASSUMPTION",
         "provenance": "ASSUMED", "effective_from": "2026-10-06T00:00:00Z", "effective_basis": "x", "discounts": [],
         "evidence": None}
    e.update(over)
    return {"contract": "tsb.p2x.fee_schedule", "contract_version": 2, "id": "TEST-FEE", "version": "9.0.0",
            "version_date": "2026-10-06", "entries": [e]}


class TestContractsV2(unittest.TestCase):
    def test_v2_frozen_and_v1_untouched(self):
        C2 = CT2.ContractSetV2()
        for f in CT2.FILES:
            self.assertEqual(_sha(os.path.join(CT2.CONTRACT_DIR, f)), C2.sums[f], f)
        self.assertEqual(C2.sha256, _sha(os.path.join(CT2.CONTRACT_DIR, CT2.SUMS_FILE)))
        self.assertEqual(C2.sha256, V2_CONTRACT_SET_SHA256)                       # X1 set frozen
        C1 = CT.ContractSet()
        self.assertEqual(C1.sha256, V1_CONTRACT_SET_SHA256)                       # P2-X0 v1 byte-identical
        for f, h in V1_FILES.items():
            self.assertEqual(_sha(os.path.join(CT.CONTRACT_DIR, f)), h, f)
        self.assertNotEqual(C1.sha256, C2.sha256)
        rd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research")
        for f, h in P2D0_FROZEN_SHA256.items():                                   # P2-D0 frozen specs untouched
            self.assertEqual(_sha(os.path.join(rd, f)), h, f)

    def test_v2_tamper_and_file_set_refused(self):
        tmp = tempfile.mkdtemp(prefix="p2x1-ct-")
        try:
            d = os.path.join(tmp, "c")
            shutil.copytree(CT2.CONTRACT_DIR, d)
            p = os.path.join(d, "scenarios_v2.json")
            doc = _load(p)
            doc["scenarios"][1]["latency_model"] = "X1-LAT-5S"
            _dump(doc, p)
            with self.assertRaises(ContractError):
                CT2.ContractSetV2(d)
            shutil.rmtree(d)
            shutil.copytree(CT2.CONTRACT_DIR, d)
            sums = _load(os.path.join(d, CT2.SUMS_FILE))
            del sums["files"]["reconciliation_design_v2.json"]
            _dump(sums, os.path.join(d, CT2.SUMS_FILE))
            with self.assertRaises(ContractError):
                CT2.ContractSetV2(d)
        finally:
            shutil.rmtree(tmp, True)

    def test_v2_arithmetic_identical_to_v1_ids_differ(self):
        S, C2 = grid_state(), CT2.ContractSetV2()
        for sc in SCEN:
            for side in ("buy", "sell"):
                for notional in (5.0, 50.0):
                    a = M.estimate_leg(S, BTC, side, notional, T, sc)
                    b = M.estimate_leg(S, BTC, side, notional, T, sc, contracts=C2)
                    la, lb = dict(_leaves(a)), dict(_leaves(b))
                    self.assertEqual(set(la), set(lb))
                    for k in la:
                        self.assertEqual((la[k]["value"], la[k]["provenance"]), (lb[k]["value"], lb[k]["provenance"]), k)
                    self.assertEqual(a["data_quality"], b["data_quality"])
                    self.assertEqual((a["scenario"]["version"], b["scenario"]["version"]), ("1.0.0", "2.0.0"))
                    self.assertEqual(b["models"]["fee_schedule"], {"id": "X1-FEE-BINANCE-SPOT-GENERIC", "version": "2.0.0"})
                    self.assertNotEqual(a["estimate_id"], b["estimate_id"])
                    self.assertNotEqual(a["contract_set_sha256"], b["contract_set_sha256"])
                    self.assertEqual(b["fee_bps"]["provenance"], ASSUMED)
                    self.assertNotEqual(b["total_cost_bps"]["provenance"], MEASURED)

    def test_fee_contract_validation_and_substitution(self):
        CT2.validate_fee_schedule(_generic_fee())
        bad = [_generic_fee(discounts=[{"kind": "BNB", "bps": 2.5}]),                       # unevidenced discount
               _generic_fee(account_scope="ACCOUNT_SPECIFIC"),                                # unverified account fee
               _generic_fee(provenance="MEASURED"),                                           # unverified MEASURED
               _generic_fee(verification_status="VERIFIED_ACCOUNT_RECORD"),                    # verified without evidence
               _generic_fee(verification_status="VERIFIED_ACCOUNT_RECORD", evidence="stmt", provenance="MEASURED"),
               _generic_fee(rate_bps=-1.0), _generic_fee(account_scope="VIP9")]
        for doc in bad:
            with self.assertRaises(ContractError):
                CT2.validate_fee_schedule(doc)
        no_ver = _generic_fee()
        del no_ver["version_date"]
        with self.assertRaises(ContractError):
            CT2.validate_fee_schedule(no_ver)
        C2 = CT2.ContractSetV2()
        gen = C2.fee_schedule("X1-FEE-BINANCE-SPOT-GENERIC")
        self.assertEqual([(e["liquidity_role"], e["rate_bps"], e["provenance"], e["account_scope"], e["discounts"])
                          for e in gen["entries"]],
                         [("taker", 10.0, "ASSUMED", "GENERIC_PUBLIC_STANDARD_TIER", []),
                          ("maker", 10.0, "ASSUMED", "GENERIC_PUBLIC_STANDARD_TIER", [])])
        S = grid_state()
        old = M.estimate_leg(S, BTC, "buy", 50.0, T, "EXEC-BASE", contracts=C2)
        acct = _generic_fee(account_scope="ACCOUNT_SPECIFIC", verification_status="VERIFIED_REALIZED_COMMISSIONS",
                            provenance="MEASURED", evidence="fills-ledger-sha256:abc", rate_bps=7.5,
                            discounts=[{"kind": "BNB", "evidence": "commission asset BNB on realized fills"}])
        acct["id"], acct["version"] = "X1-FEE-BINANCE-SPOT-ACCOUNT", "1.0.0"
        C2.add_fee_schedule(acct)
        new = M.estimate_leg(S, BTC, "buy", 50.0, T, "EXEC-BASE", contracts=C2,
                             fee_schedule_id="X1-FEE-BINANCE-SPOT-ACCOUNT@1.0.0")
        self.assertEqual((new["fee_bps"]["value"], new["fee_bps"]["provenance"]), (7.5, MEASURED))
        self.assertNotEqual(new["estimate_id"], old["estimate_id"])
        self.assertEqual(M.estimate_leg(S, BTC, "buy", 50.0, T, "EXEC-BASE", contracts=C2), old)   # history intact
        clash = copy.deepcopy(acct)
        clash["entries"][0]["rate_bps"] = 1.0
        with self.assertRaises(ContractError):
            C2.add_fee_schedule(clash)

    def test_classifications_are_honest(self):
        C2 = CT2.ContractSetV2()
        for lid in ("X1-LAT-0", "X1-LAT-1S", "X1-LAT-5S"):
            m = C2.model(lid, "latency_models")
            self.assertEqual((m["provenance"], m["classification"]), (ASSUMED, "RESEARCH_SENSITIVITY_SCENARIO"))
        self.assertEqual([C2.model(x)["latency_ms"] for x in ("X1-LAT-0", "X1-LAT-1S", "X1-LAT-5S")], [0, 1000, 5000])
        stress = {m: C2.model(m) for m in ("X1-S1-ZERO", "X1-S1-LOW", "X1-S1-MODERATE", "X1-S1-SEVERE")}
        self.assertEqual([stress[m]["bps_per_side"] for m in sorted(stress, key=lambda k: stress[k]["bps_per_side"])],
                         [0.0, 5.0, 10.0, 25.0])
        for m in stress.values():
            self.assertEqual(m["provenance"], ASSUMED)
            self.assertNotEqual(m["classification"], "EMPIRICALLY_CALIBRATED")
        self.assertEqual(C2.model("X1-S2-DEPTHWALK")["provenance"], ESTIMATED)
        st = C2.model("X1-STALE-POLICY", "stale_policies")
        self.assertEqual(st["provenance"], ASSUMED)
        self.assertTrue(all(x["class"] != "DEFENSIBLE_RESEARCH_THRESHOLD" for x in st["threshold_classification"]))
        comps = {c["component"].split(" ")[0]: c for c in C2.docs["models_v2.json"]["latency_decomposition"]["components"]}
        self.assertEqual(comps["end_to_end_decision_to_fill"]["class"], ASSUMED)
        for k in ("signal_decision", "application_processing", "order_creation", "network_to_order_entry",
                  "exchange_matching_and_ack", "fill_report"):
            self.assertEqual(comps[k]["class"], UNAVAILABLE, k)
        self.assertEqual(comps["network_to_order_entry"]["proxy"]["class"], MEASURED)
        tb = C2.docs["terminology_v2.json"]["truth_boundary"]["statement"]
        self.assertIn("cannot measure actual market impact", tb)
        self.assertIn("realized slippage", tb)

    def test_scenarios_v2_fully_specified(self):
        C2 = CT2.ContractSetV2()
        purposes = {"EXEC-IDEALIZED": "LOWER_BOUND_REFERENCE", "EXEC-BASE": "PRIMARY_FUTURE_SCENARIO",
                    "EXEC-STRESS": "SENSITIVITY_TEST"}
        self.assertEqual(sorted(C2.scenarios), sorted(SCEN))
        for sid, p in purposes.items():
            sc = C2.scenario(sid)
            self.assertEqual((sc["version"], sc["purpose"]), ("2.0.0", p))
            self.assertEqual(sorted(sc["spec"]), sorted(["latency", "reference_price", "spread", "fee", "depth_treatment",
                                                         "slippage", "stale_policy", "failure_refusal", "provenance"]))
            self.assertEqual(sc["fee_schedule"], "X1-FEE-BINANCE-SPOT-GENERIC")


class TestScenarioResult(unittest.TestCase):
    def _legs(self, notional=50.0, S=None):
        S = S or grid_state()
        C2 = CT2.ContractSetV2()
        ent = {sc: M.estimate_leg(S, BTC, "buy", notional, T, sc, contracts=C2) for sc in SCEN}
        ext = {sc: M.estimate_leg(S, BTC, "sell", notional, T + 60_000, sc, contracts=C2) for sc in SCEN}
        return ent, ext

    def test_three_nets_gross_and_provenance(self):
        ent, ext = self._legs(5.0)
        r = SR.build(ent, ext, p2c_row_ref={"row_id": "BTCUSDT|1"})
        check_quantity_tree(r)
        self.assertEqual(r["gross_return"]["provenance"], DERIVED)
        self.assertAlmostEqual(r["gross_return"]["value"], 0.0, places=12)
        nets = {sc: r["scenarios"][sc]["net_return"]["value"] for sc in SCEN}
        self.assertTrue(all(v is not None for v in nets.values()))
        self.assertGreater(nets["EXEC-IDEALIZED"], nets["EXEC-STRESS"])           # stress adds 2 x 10 bps
        self.assertEqual(r["component_provenance"]["fee_bps"], {sc: ASSUMED for sc in SCEN})
        self.assertEqual(r["component_provenance"]["slippage_bps"]["EXEC-BASE"], ESTIMATED)
        self.assertEqual(r, SR.build(ent, ext, p2c_row_ref={"row_id": "BTCUSDT|1"}))
        for k in SR.FORBIDDEN_TOP:
            self.assertNotIn(k, r)

    def test_refusal_is_visible_never_zero(self):
        ent, ext = self._legs(1e9)                                                # far beyond displayed depth
        r = SR.build(ent, ext)
        self.assertEqual(r["scenarios"]["EXEC-IDEALIZED"]["coverage"]["state"], "AVAILABLE")
        for sc in ("EXEC-BASE", "EXEC-STRESS"):
            s = r["scenarios"][sc]
            self.assertEqual(s["coverage"]["state"], "REFUSED")
            self.assertIsNone(s["net_return"]["value"])
            self.assertEqual(s["net_return"]["provenance"], UNAVAILABLE)
            self.assertIn("notional_exceeds_displayed_depth", s["coverage"]["entry_reason"])

    def test_collapse_and_missing_scenario_refused(self):
        ent, ext = self._legs(5.0)
        with self.assertRaises(SR.ResultSchemaError):
            SR.build({k: v for k, v in ent.items() if k != "EXEC-STRESS"}, ext)
        r = SR.build(ent, ext)
        bad = dict(r, net_return={"value": 0.01, "provenance": "ASSUMED", "reason": None})
        with self.assertRaises(SR.ResultSchemaError):
            SR.validate_scenario_set(bad)
        bad = copy.deepcopy(r)
        del bad["scenarios"]["EXEC-BASE"]
        with self.assertRaises(SR.ResultSchemaError):
            SR.validate_scenario_set(bad)
        bad = copy.deepcopy(r)
        bad["scenarios"]["EXEC-BASE"]["net_return"] = {"value": 0.0, "provenance": "UNAVAILABLE", "reason": "x"}
        with self.assertRaises(SR.ResultSchemaError):
            SR.validate_scenario_set(bad)

    def test_economic_success_principle(self):
        per = {sc: {} for sc in SCEN}
        cov = {sc: {"available": 1, "refused": 0, "refusal_rate": 0.0, "refusal_reasons": {}} for sc in SCEN}
        rep = {"gross": {}, "net": per, "cost_to_gross_ratio": per, "turnover_sensitivity": per,
               "execution_coverage": cov, "component_provenance": {}}
        SR.validate_evaluation_report(rep)
        for drop in SR.REPORT_REQUIRED:
            with self.assertRaises(SR.ResultSchemaError):
                SR.validate_evaluation_report({k: v for k, v in rep.items() if k != drop})
        with self.assertRaises(SR.ResultSchemaError):
            SR.validate_evaluation_report(dict(rep, economic_success=True, success_basis=["gross"]))
        with self.assertRaises(SR.ResultSchemaError):
            SR.validate_evaluation_report(dict(rep, economic_success=True, success_basis=["net.EXEC-IDEALIZED"]))
        with self.assertRaises(SR.ResultSchemaError):
            SR.validate_evaluation_report(dict(rep, net={"EXEC-BASE": {}}))
        SR.validate_evaluation_report(dict(rep, economic_success=True,
                                           success_basis=["net.EXEC-BASE", "net.EXEC-STRESS", "coverage"]))


class TestJoinContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = C.base_dataset()
        m = BD.build(cls.base, [C.D1], C.scratch("x1-p2c"), code_commit="testcommit", build_ts="2026-01-01T00:00:00Z")
        cls.p2c = m["output_dir"]
        cls.o1 = C.scratch("x1-join-1")
        cls.m1 = J.run(cls.p2c, cls.base, [C.D1], cls.o1, "f" * 40)
        cls.rep = _load(os.path.join(cls.o1, "join_report.json"))

    def test_join_structural_closure(self):
        r = self.rep
        self.assertTrue(r["join_key_unique_in_p2c"])
        self.assertEqual(r["join_key"], ["instrument_id", "decision_time_ms"])
        self.assertEqual(r["pit_violations_total"], 0)
        self.assertEqual(r["ambiguous"], {"duplicate_join_key_in_p2c": 0,
                                          "join_keys_with_more_than_one_estimate_per_scenario_side": 0})
        self.assertEqual(r["unmatched_p2c_rows"], {})
        self.assertEqual(r["counts"]["reverse"]["p2x_native_without_p2c_row"], 0)
        self.assertEqual(r["counts"]["reverse"]["p2c_row_without_p2x_native_key"], 0)
        self.assertNotIn("spread.MISMATCH", r["same_state_consistency"])
        self.assertNotIn("book_age.MISMATCH", r["same_state_consistency"])
        self.assertEqual(r["counts"]["matched"]["joined_records"], 6 * r["counts"]["matched"]["join_keys"])
        kt = CT2.ContractSetV2().knowledge_time
        with gzip.open(os.path.join(self.o1, "joined.jsonl.gz"), "rt") as fh:
            for i, line in enumerate(fh):
                j = json.loads(line)
                self.assertTrue(j["join_key"]["instrument_id"].startswith("crypto:binance:spot:"))
                self.assertEqual(set(j["p2c_row_ref"]), {"dataset_logical_hash", "feature_set", "row_id"})
                for p in j["decision_side"]:
                    self.assertIn(kt[p], ("STATIC", "DECISION"), p)
                for p in j["label_side"]:
                    self.assertIn(kt.get(p, "EXECUTION"), ("EXECUTION", "UNAVAILABLE_BY_DESIGN"), p)
                self.assertGreaterEqual(j["knowledge_time_ms"]["label_side"], j["knowledge_time_ms"]["decision_side"])
                if i > 400:
                    break

    def test_join_deterministic_and_labels_never_needed(self):
        tmp = tempfile.mkdtemp(prefix="p2x1-p2c-")
        try:
            d = os.path.join(tmp, "p2c")
            shutil.copytree(self.p2c, d)
            os.remove(os.path.join(d, "labels.jsonl.gz"))                       # the adapter never opens labels
            o2 = C.scratch("x1-join-2")
            m2 = J.run(d, self.base, [C.D1], o2, "f" * 40)
            self.assertEqual(m2["logical_hash"], self.m1["logical_hash"])
            for f in ("joined.jsonl.gz", "join_report.json", "manifest.json"):
                self.assertEqual(_sha(os.path.join(self.o1, f)), _sha(os.path.join(o2, f)), f)
            man = _load(os.path.join(d, "manifest.json"))
            man["row_count"] += 1                                                 # tampered P2-C manifest
            _dump(man, os.path.join(d, "manifest.json"))
            with self.assertRaises(J.JoinError):
                J.read_p2c(d)
        finally:
            shutil.rmtree(tmp, True)
        with self.assertRaises(SystemExit):
            J.run(self.p2c, self.base, [C.D1], os.path.join(self.base, "out"), "f" * 40)

    def test_identity_mapping_fails_closed(self):
        man, _ = J.read_p2c(self.p2c)
        ident = J.p2c_identity(man)
        meta = {"dataset_id": ident["dataset_id"], "dataset_sha256": ident["dataset_json_sha256"], "days": [C.D1],
                "seal_sha256": {C.D1: ident["seal_sha256"][C.D1]}}
        self.assertEqual(J.check_identity(ident, meta)["days"], [C.D1])
        for bad in (dict(meta, dataset_sha256="0" * 64), dict(meta, seal_sha256={C.D1: "0" * 64}),
                    dict(meta, days=[C.D2], seal_sha256={C.D2: "x"}), dict(meta, dataset_id="other")):
            with self.assertRaises(J.JoinError):
                J.check_identity(ident, bad)

    def test_partition_refuses_w3_and_out_of_range(self):
        w3 = int(LG.W3_END.timestamp() * 1000) - 60_000
        rows = [{"row_id": "BTCUSDT|a", "symbol": "BTCUSDT", "decision_time_ms": w3},
                {"row_id": "BTCUSDT|b", "symbol": "BTCUSDT", "decision_time_ms": C.D1_MS + 390_000},
                {"row_id": "BTCUSDT|b2", "symbol": "BTCUSDT", "decision_time_ms": C.D1_MS + 390_000},
                {"row_id": "BTCUSDT|c", "symbol": "BTCUSDT", "decision_time_ms": C.D2_MS - 2_000}]
        keyed, unmatched, dup = J.partition(rows, [0, 1000, 5000], [C.D1])
        self.assertEqual(dict(unmatched), {"decision_time_inside_w3_refused": 1, "execution_time_beyond_sealed_range": 1})
        self.assertEqual((len(keyed), dup), (1, 1))
        self.assertEqual(list(keyed), [("crypto:binance:spot:BTCUSDT", C.D1_MS + 390_000)])

    def test_unmapped_leg_field_refused(self):
        C2 = CT2.ContractSetV2()
        leg = M.estimate_leg(grid_state(), BTC, "buy", 50.0, T, "EXEC-BASE", contracts=C2)
        dec, lab, ref = J.split_by_knowledge_time(C2, leg)
        self.assertEqual(set(ref), {"estimate_id"})
        self.assertIn("decision_mid", dec)
        self.assertIn("fill", lab)
        self.assertNotIn("fill", dec)
        with self.assertRaises(J.JoinError):
            J.split_by_knowledge_time(C2, dict(leg, new_unclassified_field=1))
        leg0 = M.estimate_leg(grid_state(), BTC, "buy", 50.0, T, "EXEC-IDEALIZED", contracts=C2)
        self.assertIsNone(J.split_by_knowledge_time(C2, leg0)[1]["data_quality.depth"])


if __name__ == "__main__":
    unittest.main()


class TestX1DefectRegressions(unittest.TestCase):
    """P2-X1 defects found while re-verifying P2-X0 (docs/p2/P2X1_EXECUTION_CALIBRATION.md, Defects)."""

    def test_d1_unknown_update_id_order_is_not_book_newer(self):
        from p2_research.execution import coverage as CV
        self.assertEqual(CV.seq_order(None, 5), "unknown")                       # D-X1-1: was counted as book_newer
        self.assertEqual(CV.seq_order(7, None), "unknown")
        self.assertEqual(CV.seq_order(7, 5), "depth_newer")
        self.assertEqual(CV.seq_order(5, 5), "same")
        self.assertEqual(CV.seq_order(4, 5), "book_newer")

    def test_d2_every_x0_test_class_runs_as_a_script(self):
        import ast
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_execution.py")
        with open(p, encoding="utf-8") as fh:
            body = ast.parse(fh.read()).body
        guard = [i for i, n in enumerate(body) if isinstance(n, ast.If) and "__main__" in ast.unparse(n.test)]
        self.assertEqual(guard, [len(body) - 1])                                  # D-X1-2: a class followed the guard
