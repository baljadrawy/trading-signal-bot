"""Per-day streaming build == in-memory build (P2-C delta E), on a 3-day synthetic range with cross-midnight
downtime, a restart, a gap that opens on day 2 and closes on day 3 (post-hoc flag), a universe transition, a missing
candle and trailing rows after the collector stopped (``beyond_observed_data``)."""
import gzip
import os
import unittest

from p2_research import builder as BD, stream as ST
from p2_research.tests import common as C
from p2_research.tests.synth import ms

D3 = "2026-10-07"
D1_MS, D2_MS, D3_MS = C.D1_MS, C.D2_MS, ms("2026-10-07T00:00:00Z")
H = 3_600_000
COMMIT = "f" * 40


def three_day_spec(**over):
    t0 = {"BTCUSDT": 0, "ETHUSDT": 0, "AAAUSDT": 1, "BBBUSDT": 1, "CCCUSDT": 2, "DDDUSDT": 2, "EEEUSDT": 2}
    t1 = dict(t0, CCCUSDT=1, NEWUSDT=2)
    spec = {
        "dataset_id": "synthetic-3day",
        "runs": [{"boot": "a1" * 16, "ws": D1_MS + 30_000, "stop": D1_MS + 23 * H},          # stops before midnight
                 {"boot": "b2" * 16, "ws": D2_MS + H + 600_000, "stop": D3_MS + 20 * H}],    # resumes after midnight
        "span_end": D3_MS + 20 * H,
        "epochs": [{"effective_ms": D1_MS, "stamp": "20261005T000000000000Z", "tiers": t0},
                   {"effective_ms": D2_MS + 6 * H, "stamp": "20261006T055000000000Z", "tiers": t1,
                    "announce_delay_ms": 200}],
        "gaps": [{"stream": "book", "symbol": "DDDUSDT", "g0": D3_MS - 2 * H, "g1": D3_MS + 2 * H,
                  "cause": "ws_disconnect_reconnect"},
                 {"stream": "depth", "symbol": "AAAUSDT", "g0": D3_MS + 10 * H, "g1": D3_MS + 10 * H + 1_800_000,
                  "cause": "stale_stream"}],
        "candle_misses": [{"symbol": "EEEUSDT", "tf": "15m", "open_ms": D3_MS + 12 * H}],
        "clock_suspect_window": [D2_MS + 14 * H, D2_MS + 14 * H + 1_200_000],
        "close_days": [C.D1, C.D2, D3],
        "seal_days": [C.D1, C.D2, D3],
    }
    spec.update(over)
    return spec


def _content(path):
    out = {}
    for n in ("features.jsonl.gz", "labels.jsonl.gz", "excluded.jsonl.gz"):
        with open(os.path.join(path, n), "rb") as fh:
            z = fh.read()
        out[n] = (z, gzip.decompress(z))
    return out


class Streaming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from p2_research.tests.synth import Synth
        cls.base = os.path.join(C.scratch("stream3"), "ds")
        Synth(cls.base, three_day_spec()).generate()

    def _pair(self, days, tag):
        m1 = BD.build(self.base, days, C.scratch(f"mem-{tag}"), code_commit=COMMIT, build_ts="X")
        m2 = BD.build(self.base, days, C.scratch(f"str-{tag}"), code_commit=COMMIT, build_ts="X", streaming=True)
        return m1, m2

    def test_streaming_equals_in_memory(self):
        for days in ([C.D1, C.D2, D3], [C.D2, D3], [C.D1, C.D2], [D3], [C.D2]):
            with self.subTest(days=days):
                m1, m2 = self._pair(days, "-".join(d[-2:] for d in days))
                ex = m2.pop("build_execution")
                self.assertEqual(ex["days"], len(days))
                c1, c2 = _content(m1.pop("output_dir")), _content(m2.pop("output_dir"))
                self.assertEqual(m1, m2)                                   # same manifest => same logical hash
                for n in c1:
                    self.assertEqual(c1[n][1], c2[n][1], n)                # identical uncompressed content
                    self.assertEqual(c1[n][0], c2[n][0], n)                # and identical gzip bytes

    def test_fixture_exercises_boundary_semantics(self):
        m, _ = self._pair([C.D1, C.D2, D3], "sem")
        q = m["quality_summary"]
        self.assertIn("in_downtime", m["excluded_by_reason"])              # downtime across midnight D1->D2
        self.assertIn("beyond_observed_data", m["excluded_by_reason"])     # collector stopped on D3
        self.assertGreater(q["rows_posthoc_gap_at_decision"], 0)           # gap opened D2, closed D3
        self.assertEqual(len(m["source"]["run_records"]), 2)               # restart
        self.assertTrue(any(e["kind"] == "transition" for e in q["epochs"]))
        self.assertGreater(q["feature_nulls"].get("mom.dist_high_15m_96:insufficient_history", 0), 0)  # warm-up kept

    def test_warmup_crosses_day_boundary(self):
        """Day-3 features need day-2 candles (24-25 h warm-up): a D2-D3 build has fewer warm-up nulls than D3 alone,
        and streaming reproduces that exactly (no silent discard of the carried history)."""
        a, b = self._pair([D3], "w3")
        c, d = self._pair([C.D2, D3], "w23")
        e, _ = self._pair([C.D2], "w2")
        k = "mom.dist_high_15m_96:insufficient_history"
        n = lambda m: m["quality_summary"]["feature_nulls"].get(k, 0)
        self.assertEqual((n(a), n(c)), (n(b), n(d)))
        self.assertGreater(n(a), 0)                           # D3 alone: early rows lack 24 h of history
        self.assertLess(n(c) - n(e), n(a))                     # D3 rows inside a D2-D3 build use D2 history

    def test_bounded_window(self):
        one = BD.build(self.base, [C.D2], C.scratch("bw1"), code_commit=COMMIT, build_ts="X", streaming=True,
                       write=False)["build_execution"]["peak_window_sampled_records"]
        three = BD.build(self.base, [C.D1, C.D2, D3], C.scratch("bw3"), code_commit=COMMIT, build_ts="X",
                         streaming=True, write=False)["build_execution"]["peak_window_sampled_records"]
        self.assertLessEqual(three, one * 1.25)             # window = 1 day + 1 h spill + 2 h carry, not the range

    def test_deterministic_and_refuses_active_day(self):
        a = BD.build(self.base, [C.D1, C.D2, D3], C.scratch("det"), code_commit=COMMIT, streaming=True, write=False)
        b = BD.build(self.base, [C.D1, C.D2, D3], C.scratch("det"), code_commit=COMMIT, streaming=True, write=False)
        self.assertEqual(a["logical_hash"], b["logical_hash"])
        with self.assertRaises(BD.BuildError):
            BD.build(self.base, [C.D1], C.scratch("act"), code_commit=COMMIT, streaming=True,
                     experimental_active_day=True)

    def test_carry_covers_feature_lookback(self):
        self.assertGreaterEqual(ST.CARRY_MS, ST.FEATURE_SAMPLED_LOOKBACK_MS + 900_000)


if __name__ == "__main__":
    unittest.main()
