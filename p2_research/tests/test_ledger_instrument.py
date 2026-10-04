"""Trial Ledger (P2-C delta B) and canonical instrument identity (delta C)."""
import copy
import json
import os
import tempfile
import unittest

from p2_research import instrument as IN, ledger as LG, reader as RD, registry as RG

SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas",
                      "trial_ledger_v1.schema.json")


def spec(**over):
    s = {"hypothesis_id": "H-liquidity-stress-v1", "code_commit": "155df6f",
         "dataset": {"dataset_id": "p2-forward-continuous-v1", "dataset_hash": "a" * 64},
         "feature_set_version": "1.0.0", "label_set_version": "1.0.0", "universe_policy": "universe-asof-all-tiers-v1",
         "market": {"asset_class": "crypto", "venue": "binance", "product": "spot", "calendar_id": "crypto-24x7-utc"},
         "strategy_family": "filter-only", "parameter_spec": {"threshold": {"fixed": 2.0}},
         "transaction_cost_assumptions": {"fee_bps_per_side": 10.0, "slippage": "top-of-book"},
         "execution_assumptions": {"entry": "first book ask in (T, T+60s]"},
         "train_period": {"start": "2026-10-05T00:00:00Z", "end": "2026-10-20T00:00:00Z"},
         "validation_period": {"start": "2026-10-20T00:00:00Z", "end": "2026-10-27T00:00:00Z"},
         "holdout": {"w3": "sealed_forbidden", "forward": None},
         "metrics_requested": ["net_expectancy", "max_drawdown"], "parent_trial": None}
    s.update(over)
    return s


REJ = {"status": "rejected", "rejection_reason": "no post-cost edge", "metrics": {}, "evidence": {}, "notes": None}
ACC = {"status": "accepted", "rejection_reason": None, "metrics": {}, "evidence": {}, "notes": None}


class TrialLedger(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="p2c-ledger-")
        self.L = LG.Ledger(self.dir)

    def _lines(self):
        with open(self.L.path) as fh:
            return fh.read().splitlines()

    def _rewrite(self, lines):
        with open(self.L.path, "w") as fh:
            fh.write("\n".join(lines) + "\n")

    def test_failed_trials_persist_and_are_counted(self):
        a = self.L.create_trial(spec(), now="2026-10-05T00:00:00Z")
        self.L.record_result(a, REJ, now="2026-10-05T01:00:00Z")
        b = self.L.create_trial(spec(parent_trial=a, parameter_spec={"threshold": {"fixed": 3.0}}))
        self.L.record_result(b, ACC)
        t = self.L.trials()
        self.assertEqual(t[a]["result"]["status"], "rejected")
        self.assertEqual(self.L.trial_counts()["H-liquidity-stress-v1"],
                         {"trials": 2, "pending": 0, "accepted": 1, "rejected": 1, "inconclusive": 0})
        self.assertTrue(self.L.verify()["ok"])

    def test_success_cannot_overwrite_failure(self):
        a = self.L.create_trial(spec())
        self.L.record_result(a, REJ)
        with self.assertRaises(LG.ResultConflict):
            self.L.record_result(a, ACC)
        self.assertEqual(self.L.trials()[a]["result"]["status"], "rejected")
        # an appended forged second result is detected
        lines = self._lines()
        ev = json.loads(lines[-1])
        ev.update(seq=len(lines), prev_hash=ev["event_hash"], payload=ACC)
        ev["event_hash"] = LG._event_hash(ev)
        self._rewrite(lines + [LG.canon(ev)])
        r = self.L.verify()
        self.assertFalse(r["ok"])
        self.assertTrue(any("second result" in e for e in r["errors"]))

    def test_no_update_or_delete_api(self):
        for name in ("update", "delete", "remove", "edit", "overwrite", "set_result"):
            self.assertFalse(any(name in m for m in dir(LG.Ledger)), name)

    def test_tamper_detection(self):
        a = self.L.create_trial(spec())
        self.L.record_result(a, REJ)
        self.L.create_trial(spec(hypothesis_id="H-other"))
        good = self._lines()
        # 1) edit a recorded result in place
        bad = list(good)
        bad[1] = bad[1].replace('"rejected"', '"accepted"').replace('"no post-cost edge"', 'null')
        self._rewrite(bad)
        self.assertFalse(self.L.verify()["ok"])
        # 2) rehash the edited event: the chain to the next event breaks
        ev = json.loads(good[1])
        ev["payload"] = ACC
        ev["event_hash"] = LG._event_hash(ev)
        self._rewrite([good[0], LG.canon(ev), good[2]])
        self.assertTrue(any("chain" in e for e in self.L.verify()["errors"]))
        # 3) delete a line
        self._rewrite([good[0], good[2]])
        self.assertFalse(self.L.verify()["ok"])
        # 4) truncate the newest event: detected against a recorded head
        self._rewrite(good)
        head = self.L.head()
        self._rewrite(good[:2])
        self.assertTrue(self.L.verify()["ok"])
        self.assertFalse(self.L.verify(expected_head=head)["ok"])
        # appending to a tampered ledger is refused
        self._rewrite(bad)
        with self.assertRaises(LG.LedgerTamper):
            self.L.create_trial(spec(hypothesis_id="H-new"))

    def test_w3_overlap_refused(self):
        for over in ({"train_period": {"start": "2026-09-01T00:00:00Z", "end": "2026-09-10T00:00:00Z"}},
                     {"train_period": {"start": "2026-08-01T00:00:00Z", "end": "2026-08-19T09:33:47Z"},
                      "validation_period": {"start": "2026-10-05T00:00:00Z", "end": "2026-10-06T00:00:00Z"}},
                     {"validation_period": {"start": "2026-10-04T15:26:43.497Z", "end": "2026-10-27T00:00:00Z"},
                      "train_period": {"start": "2026-08-01T00:00:00Z", "end": "2026-08-02T00:00:00Z"}},
                     {"holdout": {"w3": "sealed_forbidden", "x": {"start": "2026-08-20T00:00:00Z",
                                                                   "end": "2026-08-21T00:00:00Z"}}},
                     {"holdout": {"w3": "used"}}, {"holdout": {}}):
            with self.subTest(over=over), self.assertRaises(LG.W3SealedError):
                self.L.create_trial(spec(**over))
        # boundaries are half-open: ending exactly at W3 start / starting exactly at E is allowed
        self.L.create_trial(spec(train_period={"start": "2026-08-01T00:00:00Z", "end": "2026-08-19T09:33:46Z"},
                                 validation_period={"start": "2026-10-04T15:26:43.497803Z", "end": "2026-10-06T00:00:00Z"}))
        self.assertEqual(self.L.verify()["events"], 1)

    def test_deterministic_ids(self):
        other = LG.Ledger(tempfile.mkdtemp(prefix="p2c-ledger-"))
        ids = [L.create_trial(spec(), now=f"2026-10-0{i + 5}T00:00:00Z") for i, L in enumerate((self.L, other))]
        self.assertEqual(ids[0], ids[1])                      # same history + spec -> same id (timestamp not in id)
        again = self.L.create_trial(spec())                   # identical spec re-run -> new, distinct id
        self.assertNotEqual(again, ids[0])
        self.assertEqual(again, other.create_trial(spec()))
        key_order = dict(reversed(list(spec().items())))      # key order does not matter
        self.assertEqual(LG.trial_id_for(LG._sha(LG.canon(LG.validate_spec(key_order))), 0), ids[0])

    def test_spec_validation(self):
        bad = [spec(hypothesis_id="momentum"), spec(code_commit="HEAD"), spec(metrics_requested=[]),
               spec(market={"asset_class": "equity", "venue": "nasdaq", "product": "cash"}),
               spec(validation_period={"start": "2026-10-10T00:00:00Z", "end": "2026-10-27T00:00:00Z"}),
               spec(parent_trial="TR-" + "0" * 24)]
        s = spec()
        del s["strategy_family"]
        bad.append(s)
        for b in bad:
            with self.subTest(b=b.get("hypothesis_id")), self.assertRaises(LG.SpecError):
                self.L.create_trial(b)
        with self.assertRaises(LG.LedgerError):
            self.L.record_result(self.L.create_trial(spec()), dict(REJ, rejection_reason=" "))
        self.assertTrue(self.L.verify()["ok"])

    def test_ledger_location_rules(self):
        self.assertEqual(LG.DEFAULT_LEDGER_DIR, "/home/tradmin/research-data/trading-signal-bot/p2c/ledger")
        with self.assertRaises(LG.LedgerError):
            LG.Ledger("/home/tradmin/research-data/trading-signal-bot/p2/forward-continuous-v1/ledger")

    def test_schema_matches_code(self):
        with open(SCHEMA) as fh:
            sc = json.load(fh)
        self.assertEqual(set(sc["$defs"]["spec"]["required"]), set(LG.SPEC_FIELDS))
        self.assertEqual(set(sc["$defs"]["result"]["required"]), set(LG.RESULT_FIELDS))
        self.assertEqual(sc["$defs"]["result"]["properties"]["status"]["enum"], list(LG.STATUSES))
        self.assertEqual(sc["properties"]["ledger"]["const"], LG.LEDGER_RECORD)


class InstrumentIdentity(unittest.TestCase):
    def test_binance_spot_identity(self):
        i = IN.binance_spot_instrument("BTCUSDT")
        self.assertEqual((i.instrument_id, i.base_currency, i.quote_currency, i.settlement_currency, i.calendar_id),
                         ("crypto:binance:spot:BTCUSDT", "BTC", "USDT", "USDT", "crypto-24x7-utc"))
        self.assertEqual(IN.binance_spot_instrument("ETHFDUSD").quote_currency, "FDUSD")
        for bad in ("btcusdt", "USDT", "FOOXYZ", "", None):
            with self.assertRaises(ValueError):
                IN.binance_spot_instrument(bad)

    def test_only_crypto_is_authorized(self):
        self.assertEqual(list(IN.SUPPORTED_MARKETS), ["crypto:binance:spot"])
        for m in ({"asset_class": "equity", "venue": "nyse", "product": "cash"},
                  {"asset_class": "crypto", "venue": "binance", "product": "futures"},
                  {"asset_class": "fx", "venue": "x", "product": "spot"}, {"venue": "binance"}):
            with self.assertRaises(IN.UnsupportedMarket):
                IN.require_supported_market(m)

    def test_calendar_matches_reader(self):
        cal = IN.calendar_for(IN.BINANCE_SPOT)
        self.assertEqual(cal.dataset_calendar, RD.PRODUCTION_CALENDAR)
        self.assertEqual((cal.day_ms, cal.sessions, cal.timezone), (RD.DAY_MS, "continuous", "UTC"))

    def test_research_core_does_not_import_collector(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for f in os.listdir(here):
            if f.endswith(".py"):
                with open(os.path.join(here, f)) as fh:
                    self.assertNotIn("p2_forward", "\n".join(x for x in fh if x.lstrip().startswith(("import", "from"))), f)

    def test_copy_safety(self):
        s = spec()
        LG.validate_spec(s)
        self.assertEqual(s, spec())                          # validation does not mutate the caller's spec
        self.assertEqual(copy.deepcopy(s), s)


class HypothesisFamilies(unittest.TestCase):
    def test_overlay_does_not_change_registry(self):
        d = RG.families_doc()                                  # asserts: every feature in exactly one family
        self.assertEqual(RG.registry_sha256(), "bcf38504ae746027df0932b2a501dadf74af061b4b64a28de06d4831d71db81a")
        self.assertEqual(d["registry_sha256"], RG.registry_sha256())
        self.assertEqual(d["statement"], "Feature availability does not imply feature selection.")
        self.assertEqual({f["status"] for f in RG.FEATURES}, {"experimental"})
        self.assertEqual(sum(len(v["features"]) for v in d["families"].values()), 40)
        with open(RG.FAMILIES_PATH) as fh:
            self.assertEqual(json.load(fh), json.loads(json.dumps(d)))
        self.assertNotIn("hypothesis", RG.registry_json())


if __name__ == "__main__":
    unittest.main()
