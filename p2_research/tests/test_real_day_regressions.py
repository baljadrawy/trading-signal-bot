"""Regressions found on the first real sealed collector day (P2-C1, 2026-10-04).

R1 (reader defect, midnight boundary / universe transition): the collector's daily universe refresh runs at day start
+ 600 s, so the accepted transition of day D+1 is announced inside D's spill-over hour (real data: effective
2026-10-05T00:10:10Z, file ``universe/universe-20261005T001004...json``). The reader turned every epoch announced in
the loaded segments into an epoch and opened its universe file, although an epoch effective (or announced) at or after
the range end can never be the epoch known at any decision time of the range. Consequences on real data: the build of
D depended on a D+1 (active-day, unsealed) artifact, the build from the sealed-day backup failed
(``UNIVERSE_FILE_MISSING_OR_SHA_MISMATCH``; the backup scope, like the day verifier, only holds D's universe
artifacts), and the manifest reported a universe transition for a day that had none. Fix: such epochs are ignored
(counted as ``universe_epochs_beyond_range_ignored``) and their artifacts are never opened.
"""
import gzip
import os
import shutil
import unittest

from p2_research import builder as BD, reader as RD
from p2_research.tests import common as C
from p2_research.tests.synth import Synth, ms

COMMIT = "e" * 40
H = 3_600_000
SPILL_EFF = C.D2_MS + 610_000                     # like the real collector: refresh at day start + 600 s, + 10 s


def spill_transition_spec():
    t0 = {"BTCUSDT": 0, "ETHUSDT": 0, "AAAUSDT": 1, "BBBUSDT": 1, "CCCUSDT": 2, "DDDUSDT": 2, "EEEUSDT": 2}
    return {
        "dataset_id": "synthetic-spill-transition",
        "runs": [{"boot": "c3" * 16, "ws": C.D1_MS + 14 * H, "stop": None}],      # partial first day, like 2026-10-04
        "span_end": C.D2_MS + H + 600_000,
        "epochs": [{"effective_ms": C.D1_MS, "stamp": "20261005T000000000000Z", "tiers": t0},
                   {"effective_ms": SPILL_EFF, "stamp": "20261006T001000000000Z", "tiers": dict(t0, DDDUSDT=1),
                    "announce_delay_ms": 5}],
        "gaps": [], "candle_misses": [],
        "close_days": [C.D1], "seal_days": [C.D1],
    }


def _content(path):
    out = {}
    for n in ("features.jsonl.gz", "labels.jsonl.gz", "excluded.jsonl.gz"):
        with open(os.path.join(path, n), "rb") as fh:
            out[n] = fh.read()
    return out


class SpillHourUniverseTransition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = C.scratch("spill-transition")
        cls.full = os.path.join(root, "full")
        Synth(cls.full, spill_transition_spec()).generate()
        cls.spill_uid = "uni|20261006T001000000000Z|tiers-v2"
        cls.spill_file = "universe/universe-20261006T001000000000Z-c3c3c3c3.json"
        assert os.path.exists(os.path.join(cls.full, cls.spill_file))
        # the sealed-day backup scope: D's files + spill-over, but only the universe artifacts D needs
        cls.backup = os.path.join(root, "backup")
        shutil.copytree(cls.full, cls.backup)
        os.remove(os.path.join(cls.backup, cls.spill_file))

    def test_fixture_announces_next_day_transition_in_spill_hour(self):
        B = RD.load_days(self.full, [C.D1])
        ann = [x for x in B.lifecycle if x[1] == "universe_transition"]
        self.assertEqual(len(ann), 1)
        self.assertTrue(C.D2_MS <= ann[0][0] < C.D2_MS + H)                 # announced in the spill-over hour

    def test_reader_ignores_epochs_beyond_range(self):
        for base in (self.full, self.backup):
            with self.subTest(base=os.path.basename(base)):
                B = RD.load_days(base, [C.D1])
                self.assertTrue(all(max(e["effective_from_ms"], e["available_at_ms"]) < B.range_end_ms
                                    for e in B.epochs))
                self.assertNotIn(self.spill_uid, {e["universe_id"] for e in B.epochs})
                self.assertNotIn(self.spill_file, B.provenance["universe_files"])
                self.assertEqual(B.quality["universe_transitions"], 0)
                # the D+1 transition and the D+1 day_checkpoint (effective at the range end)
                self.assertEqual(B.quality["universe_epochs_beyond_range_ignored"], 2)

    def test_build_from_backup_scope_equals_full_dataset(self):
        ref = None
        for base in (self.full, self.backup):
            for streaming in (False, True):
                with self.subTest(base=os.path.basename(base), streaming=streaming):
                    m = BD.build(base, [C.D1], C.scratch(f"spill-{os.path.basename(base)}-{int(streaming)}"),
                                 code_commit=COMMIT, build_ts="X", streaming=streaming)
                    m.pop("build_execution", None)
                    content = _content(m.pop("output_dir"))
                    self.assertGreater(m["row_count"], 0)
                    if ref is None:
                        ref = (m, content)
                    self.assertEqual(m, ref[0])                              # same logical hash
                    self.assertEqual(content, ref[1])                        # byte-identical gzip content
        self.assertEqual([e["universe_id"] for e in ref[0]["quality_summary"]["epochs"]],
                         ["uni|20261005T000000000000Z|tiers-v2"])
        self.assertEqual(ref[0]["quality_summary"]["reader"]["universe_epochs_beyond_range_ignored"], 2)
        rows = gzip.decompress(ref[1]["features.jsonl.gz"]).decode().splitlines()
        self.assertTrue(all('"universe_id":"uni|20261005T000000000000Z|tiers-v2"' in r for r in rows))


if __name__ == "__main__":
    unittest.main()
