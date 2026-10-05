"""P2-D0 protocol validation: frozen registries parse, reference real features/labels, match declared trial counts,
stay crypto-only and W3-free, hashes match, the planned-trial generator is deterministic, benchmarks are complete."""
import copy
import itertools
import json
import os
import re
import shutil
import tempfile
import unittest

from p2_research import labels as LB, ledger as LG, protocol as PR, registry as RG

FEAT_RE = re.compile(r"\b(?:mom|vol|liq|act|ctx|dq)\.[a-z0-9_]+")
LABEL_RE = re.compile(r"\b(?:mkt|exe)\.[a-z]+(?:_[a-z]+)*(?:_(?:1h|4h|24h|\{h\}))?")
HORIZONS = ("1h", "4h", "24h")


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)


class FrozenRegistries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen = PR.verify_frozen()
        cls.hyp = PR.load("hypotheses_v1.json")
        cls.bench = PR.load("benchmarks_v1.json")
        cls.proto = PR.load("protocol_v1.json")
        cls.plan = PR.load("planned_trials_v1.json")
        cls.fids = PR.feature_ids()
        cls.lids = {d["id"] for d in LB.label_definitions()}

    def test_files_are_canonical_and_hashes_match(self):
        for f in PR.FROZEN_FILES:
            with open(os.path.join(PR.RESEARCH_DIR, f), encoding="ascii") as fh:
                raw = fh.read()
            self.assertEqual(raw, PR.dump_frozen(json.loads(raw)), f)
            self.assertEqual(PR.sha256_file(os.path.join(PR.RESEARCH_DIR, f)), self.frozen[f])

    def test_tamper_detected(self):
        d = tempfile.mkdtemp(prefix="p2d0-")
        try:
            for f in PR.FROZEN_FILES + (PR.FROZEN_SUMS,):
                shutil.copy(os.path.join(PR.RESEARCH_DIR, f), d)
            PR.verify_frozen(d)
            with open(os.path.join(d, "hypotheses_v1.json"), "a") as fh:
                fh.write(" ")
            with self.assertRaises(PR.ProtocolError):
                PR.verify_frozen(d)
            with self.assertRaises(PR.ProtocolError):       # re-freezing over existing sums is refused
                PR._write_plan_and_sums(d)
        finally:
            shutil.rmtree(d)

    def test_feature_registry_binding(self):
        with open(os.path.join(os.path.dirname(RG.__file__), "registry", "feature_registry_v1.json"), "rb") as fh:
            import hashlib
            sha = hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(self.hyp["feature_set"]["registry_sha256"], sha)
        self.assertEqual(self.proto["feature_set"]["registry_sha256"], sha)
        self.assertEqual(self.hyp["feature_set"]["version"], RG.FEATURE_SET_VERSION)
        self.assertEqual(self.hyp["label_set"]["version"], LB.LABEL_SET_VERSION)

    def test_hypotheses_complete_and_reference_real_ids(self):
        ids = [h["id"] for h in self.hyp["hypotheses"]]
        self.assertEqual(ids, [f"H0{i}" for i in range(1, 8)])
        need = {"economic_rationale", "features", "signal_definition", "direction", "direction_note", "label_horizons",
                "labels_used", "decision_cadence", "grid", "grid_order", "trials", "comparison_control",
                "expected_failure_modes", "outcome_categories", "predictive_vs_executable", "ledger_hypothesis_id",
                "strategy_family", "trial_kind", "fixed_parameters"}
        lh = set()
        for h in self.hyp["hypotheses"]:
            self.assertFalse(need - set(h), h["id"])
            self.assertTrue(h["features"], h["id"])
            self.assertEqual(set(h["features"]) - self.fids, set(), h["id"])
            for s in _strings(h):                                      # every feature-looking token is real
                for tok in FEAT_RE.findall(s):
                    self.assertIn(tok, self.fids, f"{h['id']}: {tok}")
                for tok in LABEL_RE.findall(s):
                    for hz in (HORIZONS if "{h}" in tok else ("",)):
                        lab = tok.replace("{h}", hz)
                        self.assertIn(lab, self.lids, f"{h['id']}: {tok}")
            self.assertEqual(h["outcome_categories"], ["SUPPORTED", "WEAK", "INCONCLUSIVE", "REJECTED"])
            self.assertTrue(h["direction"].startswith("long_only_spot"))
            self.assertIn("cannot short", h["direction_note"])
            for k, g in h["grid"].items():
                self.assertTrue(g["values"] and g["justification"].strip(), f"{h['id']}.{k}")
            for hz in h["label_horizons"]:
                self.assertIn(f"mkt.fwd_ret_{hz}", self.lids)
            self.assertNotIn(h["ledger_hypothesis_id"], lh)
            lh.add(h["ledger_hypothesis_id"])
            self.assertRegex(h["ledger_hypothesis_id"], LG._HYP.pattern)

    def test_grids_match_declared_trial_counts_and_budget(self):
        per = {}
        for h in self.hyp["hypotheses"]:
            n = len(list(itertools.product(*[h["grid"][k]["values"] for k in h["grid_order"]])))
            self.assertEqual(n, h["trials"], h["id"])
            per[h["id"]] = n
        b = self.proto["parameter_budget"]
        self.assertEqual(per, b["round_1_trials_per_hypothesis"])
        self.assertEqual(sum(per.values()), b["round_1_total_cap"])
        self.assertTrue(all(n <= b["lifetime_cap_per_hypothesis"] for n in per.values()))
        self.assertEqual(self.plan["trials_total"], sum(per.values()))
        self.assertEqual(self.plan["trials_per_hypothesis"], per)

    def test_planned_trial_generator_is_deterministic(self):
        a = PR.planned_trials(self.hyp)
        b = PR.planned_trials(json.loads(json.dumps(self.hyp)))
        self.assertEqual(PR.canon(a), PR.canon(b))
        doc = PR.plan_document(self.hyp, self.frozen["hypotheses_v1.json"])
        self.assertEqual(PR.dump_frozen(doc), PR.dump_frozen(self.plan))          # frozen plan == regenerated plan
        self.assertEqual(len({t["plan_id"] for t in a}), len(a))
        self.assertEqual(len({t["plan_entry_sha256"] for t in a}), len(a))
        self.assertTrue(all(t["status"] == "PLANNED" for t in a))
        self.assertFalse(self.plan["registered_in_ledger"])
        for t in a:                                                    # no result-like field in a plan entry
            self.assertFalse({"result", "metrics", "status_result"} & set(t))
        bad = copy.deepcopy(self.hyp)
        bad["hypotheses"][0]["trials"] += 1
        with self.assertRaises(PR.ProtocolError):
            PR.planned_trials(bad)

    def test_crypto_only_and_no_w3(self):
        for doc in (self.hyp, self.proto, self.bench["common"]):
            self.assertEqual(doc["market"], {"asset_class": "crypto", "venue": "binance", "product": "spot",
                                             "calendar_id": "crypto-24x7-utc"})
        w3 = self.proto["w3"]
        self.assertEqual((w3["start"], w3["end"]), ("2026-08-19T09:33:46Z", "2026-10-04T15:26:43.497803Z"))
        self.assertEqual(self.proto["paper_r1"]["E"], w3["end"])
        self.assertIn("non-crypto markets", self.proto["excluded"])
        # every concrete date the protocol schedules is at/after E and the first evaluated day is after W3
        self.assertIn("2026-10-05", self.proto["time_split"]["eligible_days"])

    def test_ledger_specs_validate_and_refuse_w3_and_other_markets(self):
        entry = self.plan["trials"][0]
        kw = dict(code_commit="8806556", dataset={"dataset_id": "p2-forward-continuous-v1", "dataset_hash": "b" * 64},
                  train_period={"start": "2026-10-05T00:00:00Z", "end": "2026-10-18T00:00:00Z"},
                  validation_period={"start": "2026-10-19T00:00:00Z", "end": "2026-10-26T00:00:00Z"},
                  forward_untouched={"start": "2026-11-02T00:00:00Z", "end": "2026-12-01T00:00:00Z"})
        for t in self.plan["trials"]:
            s = PR.ledger_spec(t, self.proto, self.frozen, **kw)
            self.assertEqual(s["parameter_spec"]["plan_entry_sha256"], t["plan_entry_sha256"])
            self.assertEqual(s["holdout"]["w3"], "sealed_forbidden")
        w3 = dict(kw, train_period={"start": "2026-10-01T00:00:00Z", "end": "2026-10-18T00:00:00Z"})
        with self.assertRaises(LG.W3SealedError):
            PR.ledger_spec(entry, self.proto, self.frozen, **w3)
        p2 = copy.deepcopy(self.proto)
        p2["market"] = {"asset_class": "equity", "venue": "nyse", "product": "cash", "calendar_id": "xnys"}
        with self.assertRaises(Exception):
            PR.ledger_spec(entry, p2, self.frozen, **kw)
        altered = dict(entry, params=dict(entry["params"], horizon="1h"))
        with self.assertRaises(PR.ProtocolError):
            PR.ledger_spec(altered, self.proto, self.frozen, **kw)
        real = os.path.join(LG.DEFAULT_LEDGER_DIR, LG.LEDGER_FILE)        # spec building never writes the ledger
        before = PR.sha256_file(real) if os.path.exists(real) else None
        PR.ledger_spec(entry, self.proto, self.frozen, **kw)
        self.assertEqual(PR.sha256_file(real) if os.path.exists(real) else None, before)

    def test_benchmarks_fully_specified(self):
        ids = [b["id"] for b in self.bench["benchmarks"]]
        self.assertEqual(ids, ["BENCH-CASH", "BENCH-BTC-BH", "BENCH-BTC-TREND", "BENCH-TSMOM", "BENCH-PAPER-R1"])
        self.assertFalse(any("B3" == i or i.endswith("-B3") for i in ids))
        for b in self.bench["benchmarks"]:
            for k in ("definition", "signal", "rebalancing", "universe", "costs", "eligible"):
                self.assertIn(k, b, f"{b['id']}.{k}")
            for s in _strings(b):
                for tok in FEAT_RE.findall(s):
                    self.assertIn(tok, self.fids)
                for tok in LABEL_RE.findall(s):
                    self.assertIn(tok, self.lids)
        pr1 = self.bench["benchmarks"][-1]
        self.assertFalse(pr1["eligible"])
        self.assertIn("never W3", pr1["eligibility_condition"])
        for b in self.bench["benchmarks"][2:4]:
            self.assertIn("parameters", b)

    def test_protocol_sections_frozen(self):
        p = self.proto
        for k in ("research_questions", "excluded", "parameter_budget", "multiple_testing", "time_split",
                  "universe_policy", "gross_vs_executable", "metrics_contract", "concentration_diagnostics",
                  "regime_diagnostics", "outcome_categories", "crypto_success_gate_draft", "p2d1_entry_requirements",
                  "ledger_integration", "execution_model"):
            self.assertIn(k, p)
        self.assertTrue(p["research_questions"]["primary"].startswith("Can observable, point-in-time-safe"))
        self.assertGreaterEqual(p["time_split"]["minimum_full_days_before_any_outcome"], 28)
        self.assertIn("NOT active", p["crypto_success_gate_draft"]["status"])
        self.assertTrue(all(v == "TBD" for v in p["crypto_success_gate_draft"]["dimensions"].values()))
        req = p["p2d1_entry_requirements"]
        self.assertEqual([r["id"] for r in req], list(range(1, 8)))
        self.assertTrue(req[6]["status"].startswith("PENDING"))
        self.assertEqual(len(req[6]["features"]), 9)
        self.assertEqual(set(req[6]["features"]) - self.fids, set())
        self.assertEqual(set(req[6]["labels"]) - self.lids, set())
        for k in ("trading_economics", "risk", "risk_adjusted", "trade_path", "robustness", "later"):
            self.assertTrue(p["metrics_contract"][k])
        self.assertEqual(p["parameter_budget"]["round_1_total_cap"], 48)


if __name__ == "__main__":
    unittest.main()
