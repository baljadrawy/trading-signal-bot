import gzip
import json
import os
import random
import unittest

from p2_research import reader as RD
from p2_research.tests import common as C
from p2_research.tests.synth import refresh_hashes, seal_day, close_day


def _segs(base, type_, day):
    d = os.path.join(base, "raw", type_, day)
    return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".jsonl.gz")]


def _read(p):
    with gzip.open(p, "rt") as fh:
        return [json.loads(x) for x in fh if x.strip()]


def _write(p, recs, raw_lines=None):
    os.chmod(p, 0o644)
    with gzip.open(p, "wt") as fh:
        for x in (raw_lines if raw_lines is not None else [json.dumps(r) for r in recs]):
            fh.write(x + "\n")


class SealedLoading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = RD.load_days(C.base_dataset(), [C.D1, C.D2])

    def test_sealed_days_listed(self):
        self.assertEqual(RD.sealed_days(C.base_dataset()), [C.D1, C.D2])

    def test_provenance_and_mode(self):
        B = self.B
        self.assertEqual(B.mode, "sealed")
        self.assertTrue(B.reproducible)
        self.assertEqual(sorted(B.provenance["days"]), [C.D1, C.D2])
        self.assertTrue(all(len(s["sha256"]) == 64 for s in B.provenance["segments"]))
        self.assertTrue(any(s["spill"] for s in B.provenance["segments"]))
        self.assertEqual(B.provenance["schema_versions"], [2])

    def test_quality_metadata_preserved(self):
        q = self.B.quality
        self.assertEqual(q["gap_day_split"], 1)
        self.assertEqual(q["gap_cause.ws_disconnect_reconnect"], 2)
        self.assertEqual(q["gap_cause.stale_stream"], 1)
        self.assertEqual(q["gap_cause.candle_fetch_failed:500"], 1)
        self.assertGreater(q["clock_suspect.book"], 0)
        self.assertGreater(q["health_not_healthy_records"], 0)
        self.assertEqual(q["universe_transitions"], 1)
        rec = [g for g in self.B.gaps if g["day_split"]][0]
        self.assertEqual(rec["recoverability"], "IRREPLACEABLE_FORWARD_OBSERVATION")
        self.assertEqual(rec["last_missing_ms"] + rec["cadence_ms"], C.D2_MS)

    def test_runs_and_downtime(self):
        B = self.B
        self.assertEqual(len(B.runs), 2)
        self.assertTrue(B.runs[0]["clean_stop"])
        self.assertEqual(B.runs[1]["downtime_cause"], "clean_stop")
        causes = [d["cause"] for d in B.downtime]
        self.assertEqual(causes, ["first_run", "clean_stop"])
        self.assertIsNone(B.run_at(C.D1_MS + 20 * 3_600_000 + 300_000))       # between the runs: downtime
        self.assertEqual(B.run_at(C.D1_MS + 21 * 3_600_000)["boot8"], "b2b2b2b2")

    def test_idempotent_candle_duplicates_across_runs(self):
        self.assertEqual(self.B.quality["duplicates_dropped.candle"], 7)       # 4h catch-up re-fetched by run 2

    def test_spillover_single_day(self):
        B1 = RD.load_days(C.base_dataset(), [C.D1])
        last15 = C.D2_MS - 900_000
        c = B1.candles[("BTCUSDT", "15m")][last15]
        self.assertGreaterEqual(c[8], C.D2_MS)                                # fetched in the spill hour
        self.assertEqual(B1.quality["gap_day_split"], 1)                      # D1 part of the gap, written at D2 00:00
        self.assertEqual(B1.coverage_end_ms, C.D2_MS)

    def test_sampled_streams_sorted_by_availability(self):
        for s, lst in self.B.book.items():
            self.assertTrue(all(a[0] <= b[0] for a, b in zip(lst, lst[1:])), s)


class SealGate(unittest.TestCase):
    def test_active_day_rejected_and_experimental_flag(self):
        base = C.new_dataset("unsealed", seal_days=[C.D1], close_days=[C.D1])
        with self.assertRaises(RD.NotSealed):
            RD.load_days(base, [C.D2])
        with self.assertRaises(RD.NotSealed):
            RD.load_days(base, [C.D1, C.D2])                                 # never mixed
        B = RD.load_days(base, [C.D2], experimental_active_day=True)
        self.assertFalse(B.reproducible)
        self.assertEqual(B.mode, "experimental_active_day")
        with self.assertRaises(RD.ReaderError):
            RD.load_days(base, [C.D1], experimental_active_day=True)          # flag on a sealed day
        with self.assertRaises(RD.ReaderError):
            RD.load_days(base, [C.D1, C.D2], experimental_active_day=True)
        self.assertEqual(RD.load_days(base, [C.D1]).mode, "sealed")           # sealed day accepted

    def test_failed_seal_rejected(self):
        base = C.copy_dataset("failseal")
        os.chmod(os.path.join(base, "seals", f"{C.D2}.json"), 0o644)
        seal_day(base, C.D2, result="FAIL")
        with self.assertRaises(RD.NotSealed):
            RD.load_days(base, [C.D2])

    def test_segment_tamper_detected(self):
        base = C.copy_dataset("tamper")
        p = _segs(base, "book", C.D2)[3]
        recs = _read(p)
        recs[0]["payload"]["b"] = "1.0"
        _write(p, recs)
        with self.assertRaises(RD.IntegrityError) as cm:
            RD.load_days(base, [C.D2])
        self.assertEqual(cm.exception.code, "SEGMENT_SHA_NE_MANIFEST")

    def test_manifest_rewrite_without_reseal_detected(self):
        base = C.copy_dataset("reman")
        p = _segs(base, "book", C.D2)[3]
        recs = _read(p)
        recs[0]["payload"]["b"] = "1.0"
        _write(p, recs)
        seals = os.path.join(base, "seals")
        os.rename(seals, seals + ".x")                                        # refresh manifests/day-close only
        refresh_hashes(base)
        os.rename(seals + ".x", seals)
        with self.assertRaises(RD.IntegrityError) as cm:
            RD.load_days(base, [C.D2])
        self.assertIn(cm.exception.code, ("MANIFEST_SHA_MISMATCH", "DAY_CLOSE_SHA_MISMATCH"))

    def test_uncertified_file_in_sealed_day(self):
        base = C.copy_dataset("partial")
        p = _segs(base, "book", C.D2)[0]
        with open(p.replace(".jsonl.gz", "-x.jsonl.gz.partial"), "wb") as fh:
            fh.write(b"x")
        with self.assertRaises(RD.IntegrityError):
            RD.load_days(base, [C.D2])


class SchemaVersions(unittest.TestCase):
    def _mutate_one(self, name, fn):
        base = C.copy_dataset(name)
        p = _segs(base, "book", C.D2)[2]
        recs = _read(p)
        fn(recs[5])
        _write(p, recs)
        refresh_hashes(base)
        return base

    def test_dataset_future_version_rejected(self):
        base = C.copy_dataset("dsv3")
        dp = os.path.join(base, "dataset.json")
        with open(dp) as fh:
            d = json.load(fh)
        d["schema_version"] = 3
        with open(dp, "w") as fh:
            json.dump(d, fh)
        with self.assertRaises(RD.UnsupportedSchema):
            RD.load_days(base, [C.D2])

    def test_record_future_and_old_versions_rejected(self):
        for name, v in (("rv3", 3), ("rv1", 1), ("rvstr", "2")):
            base = self._mutate_one(name, lambda r, v=v: r.__setitem__("schema_version", v))
            with self.assertRaises(RD.UnsupportedSchema, msg=name):
                RD.load_days(base, [C.D2])

    def test_unknown_type_and_schema_name_rejected(self):
        base = self._mutate_one("utype", lambda r: r.__setitem__("type", "trade"))
        with self.assertRaises(RD.UnsupportedSchema):
            RD.load_days(base, [C.D2])
        base = self._mutate_one("uname", lambda r: r.__setitem__("schema", "tsb.p2.other"))
        with self.assertRaises(RD.UnsupportedSchema):
            RD.load_days(base, [C.D2])

    def test_pit_violating_record_rejected(self):
        base = self._mutate_one("obsafter", lambda r: r.__setitem__("sample_ms", r["observed_at_ms"] - 1))
        with self.assertRaises(RD.IntegrityError):
            RD.load_days(base, [C.D2])


class DuplicatesAndOrder(unittest.TestCase):
    def test_duplicates_and_shuffle_give_identical_bundle(self):
        ref = RD.load_days(C.base_dataset(), [C.D2])
        base = C.copy_dataset("dupshuf")
        rng = random.Random(7)
        for t in ("book", "depth", "market", "candle", "lifecycle", "gap", "health"):
            for p in _segs(base, t, C.D2):
                with gzip.open(p, "rt") as fh:
                    lines = [x.rstrip("\n") for x in fh if x.strip()]
                lines = lines + lines[: max(1, len(lines) // 10)]             # identical duplicates
                rng.shuffle(lines)                                            # out-of-order input
                _write(p, None, raw_lines=lines)
        refresh_hashes(base)
        B = RD.load_days(base, [C.D2])
        self.assertEqual(dict(B.book), dict(ref.book))
        self.assertEqual(dict(B.depth), dict(ref.depth))
        self.assertEqual(B.market, ref.market)
        self.assertEqual(dict(B.candles), dict(ref.candles))
        self.assertEqual(B.gaps, ref.gaps)
        self.assertEqual(B.lifecycle, ref.lifecycle)
        self.assertGreater(B.quality["duplicates_dropped.book"], 0)
        self.assertGreater(B.quality["duplicates_dropped.lifecycle"], 0)

    def test_conflicting_duplicate_fails_closed(self):
        base = C.copy_dataset("conflict")
        p = _segs(base, "book", C.D2)[1]
        recs = _read(p)
        x = json.loads(json.dumps(recs[0]))
        x["payload"]["b"] = str(float(x["payload"]["b"]) * 0.99)
        _write(p, recs + [x])
        refresh_hashes(base)
        with self.assertRaises(RD.AmbiguityError):
            RD.load_days(base, [C.D2])

    def test_conflicting_candle_fails_closed(self):
        base = C.copy_dataset("conflictc")
        p = _segs(base, "candle", C.D2)[1]
        recs = _read(p)
        x = json.loads(json.dumps(recs[0]))
        x["payload"][4] = str(float(x["payload"][4]) * 1.01)
        _write(p, recs + [x])
        refresh_hashes(base)
        with self.assertRaises(RD.AmbiguityError):
            RD.load_days(base, [C.D2])


if __name__ == "__main__":
    unittest.main()
