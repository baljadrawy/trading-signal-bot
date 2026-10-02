"""P2-B market-data guards: each test deliberately triggers a guard (stdlib unittest; pandas/pyarrow/ta parts skip
when those libraries are absent, e.g. outside the research venv). No network, no production access."""
import hashlib
import io
import json
import pathlib
import tempfile
import unittest
import urllib.error
import zipfile
from decimal import Decimal
from unittest import mock

from research.p2 import market_contract as M

try:
    import pandas as pd
    import pyarrow  # noqa: F401
    import ta  # noqa: F401
    HAVE_PD = True
except Exception:  # pragma: no cover
    HAVE_PD = False

F = M.FREEZE_MS


class TestFreezeBoundary(unittest.TestCase):
    def test_post_freeze_archives_are_refused(self):
        with self.assertRaises(M.FreezeViolation):
            M.archive_url("monthly", "BTCUSDT", "15m", "2026-08")
        with self.assertRaises(M.FreezeViolation):
            M.archive_url("daily", "BTCUSDT", "15m", "2026-08-19")
        self.assertIn("2026-08-18", M.archive_url("daily", "BTCUSDT", "15m", "2026-08-18"))
        self.assertIn("2026-07", M.archive_url("monthly", "BTCUSDT", "1d", "2026-07"))

    def test_plan_never_contains_post_freeze_archive(self):
        for tf in M.TIMEFRAMES:
            for kind, period in M.w2_requests("BTCUSDT", tf):
                if kind != "rest":
                    self.assertTrue(M.archive_is_pre_freeze(kind, period), (tf, kind, period))
        self.assertFalse(any(k == "rest" for k, _ in M.w2_requests("BTCUSDT", "1d")))   # 1d freeze-day candle never closed

    def test_last_admissible_open(self):
        for tf, ms in M.TF_MS.items():
            o = M.last_admissible_open_ms(tf)
            self.assertLess(o + ms - 1, F)               # closes before freeze
            self.assertGreaterEqual(o + ms + ms - 1, F)  # the next one would not

    def test_close_at_freeze_rejected(self):
        tf = "15m"; o = M.last_admissible_open_ms(tf) + M.TF_MS[tf]
        with self.assertRaises(M.FreezeViolation):
            M.assert_closed_before_freeze(F, F - 1, tf)
        with self.assertRaises(M.FreezeViolation):
            M.assert_closed_before_freeze(o + M.TF_MS[tf] - 1, o, tf)
        M.assert_closed_before_freeze(F - 1, F - 1 - 899_999, tf)

    def test_close_semantics(self):
        with self.assertRaises(ValueError):
            M.assert_closed_before_freeze(1000, 1000, "15m")             # close == open
        with self.assertRaises(ValueError):
            M.assert_closed_before_freeze(900_000 + 1000, 1000, "15m")    # close beyond candle


class TestAcquisitionGuards(unittest.TestCase):
    def test_source_gap_404_is_recorded_not_fabricated(self):
        from research.p2 import market_acquire as A
        def boom(url, headers=None, timeout=60):
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(A, "_get", boom):
            rec = A.fetch_archive(pathlib.Path(d), {"symbol": "NEWUSDT", "timeframe": "1d", "kind": "monthly", "period": "2026-06"})
            self.assertEqual(rec["status"], "SOURCE_UNAVAILABLE")
            self.assertEqual(list(pathlib.Path(d).rglob("*.zip")), [])

    def test_checksum_mismatch_rejected(self):
        from research.p2 import market_acquire as A
        def fake(url, headers=None, timeout=60):
            if url.endswith(".CHECKSUM"):
                return 200, ("0" * 64 + "  x.zip").encode(), {}
            return 200, b"not the archive", {}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(A, "_get", fake), mock.patch.object(A.time, "sleep"):
            rec = A.fetch_archive(pathlib.Path(d), {"symbol": "BTCUSDT", "timeframe": "1d", "kind": "monthly", "period": "2026-06"})
            self.assertEqual(rec["status"], "CHECKSUM_MISMATCH")
            self.assertEqual(list(pathlib.Path(d).rglob("*.zip")), [])

    def test_rest_post_freeze_row_aborts_and_writes_nothing(self):
        from research.p2 import market_acquire as A
        o = M.last_admissible_open_ms("15m")
        rows = [[o + 900_000, "1", "1", "1", "1", "1", o + 2 * 900_000 - 1, "1", 1, "0", "0", "0"]]   # closes after freeze
        with tempfile.TemporaryDirectory() as d, mock.patch.object(A, "_get", lambda *a, **k: (200, json.dumps(rows).encode(), {})):
            with self.assertRaises(M.FreezeViolation):
                A.fetch_rest(pathlib.Path(d), {"symbol": "BTCUSDT", "timeframe": "15m"}, o - 900_000, o, "freeze_day_partial")
            self.assertEqual(list(pathlib.Path(d).rglob("*.json")), [])

    def test_rest_endtime_beyond_admissible_refused(self):
        from research.p2 import market_acquire as A
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(M.FreezeViolation):
                A.fetch_rest(pathlib.Path(d), {"symbol": "BTCUSDT", "timeframe": "1h"}, 0, M.last_admissible_open_ms("1h") + 3_600_000, "x")


@unittest.skipUnless(HAVE_PD, "pandas/pyarrow/ta not available (run in the research venv)")
class TestNormalization(unittest.TestCase):
    def _df(self, opens, tf="15m", close_off=None, price=1.0):
        from research.p2.market_normalize import BASE_COLS
        tfms = M.TF_MS[tf]
        rows = [{"symbol": "XUSDT", "timeframe": tf, "open_time": pd.Timestamp(o, unit="ms", tz="UTC"),
                 "close_time": pd.Timestamp(o * 1000 + (close_off if close_off is not None else tfms * 1000 - 1), unit="us", tz="UTC"),
                 "open": price, "high": price * 1.01, "low": price * 0.99, "close": price, "volume": 1.0,
                 "quote_volume": price, "trade_count": 3} for o in opens]
        return pd.DataFrame(rows)[BASE_COLS]

    def test_post_freeze_candle_is_hard_failure(self):
        from research.p2.market_normalize import normalize_series
        o = M.last_admissible_open_ms("15m")
        with self.assertRaises(M.FreezeViolation):
            normalize_series([(self._df([o, o + 900_000]), "x", "h")], "XUSDT", "15m")

    def test_duplicates_quarantined_not_repaired(self):
        from research.p2.market_normalize import normalize_series
        base = 1_780_000_200_000 // 900_000 * 900_000
        a = self._df([base, base + 900_000]); b = self._df([base + 900_000], price=2.0)   # conflicting duplicate
        clean, q, ql = normalize_series([(a, "x", "h1"), (b, "y", "h2")], "XUSDT", "15m")
        self.assertEqual(len(clean), 1)
        self.assertEqual(sum(1 for r in q if r["reason"] == "EXCLUDE_CONFLICTING_DUPLICATE"), 2)
        same = self._df([base + 900_000])
        clean2, q2, _ = normalize_series([(a, "x", "h1"), (same, "y", "h2")], "XUSDT", "15m")
        self.assertEqual(len(clean2), 2)
        self.assertEqual([r["reason"] for r in q2], ["EXCLUDE_IDENTICAL_DUPLICATE"])

    def test_interval_misaligned_and_gaps(self):
        from research.p2.market_normalize import normalize_series
        base = 1_780_000_200_000 // 900_000 * 900_000
        clean, q, ql = normalize_series([(self._df([base, base + 1000, base + 3 * 900_000]), "x", "h")], "XUSDT", "15m")
        self.assertIn("EXCLUDE_MISALIGNED_OPEN", {r["reason"] for r in q})
        self.assertEqual(ql["gaps"][0]["missing_bars"], 2)                       # gap recorded, not synthesized
        self.assertEqual(len(clean), 2)

    def test_invalid_close_time_quarantined(self):
        from research.p2.market_normalize import normalize_series
        base = 1_780_000_200_000 // 900_000 * 900_000
        _, q, _ = normalize_series([(self._df([base], close_off=900_000 * 1000 + 5), "x", "h")], "XUSDT", "15m")
        self.assertEqual(q[0]["reason"], "EXCLUDE_INVALID_CLOSE_TIME")

    def test_normalization_deterministic_and_order_independent(self):
        from research.p2.market_normalize import normalize_series, table_bytes, content_hash
        base = 1_780_000_200_000 // 900_000 * 900_000
        a, b = self._df([base, base + 900_000]), self._df([base + 2 * 900_000])
        c1, _, _ = normalize_series([(a, "x", "h1"), (b, "y", "h2")], "XUSDT", "15m")
        c2, _, _ = normalize_series([(b, "y", "h2"), (a, "x", "h1")], "XUSDT", "15m")
        self.assertEqual(table_bytes(c1), table_bytes(c2))
        self.assertEqual(content_hash(c1), content_hash(c2))

    def test_checksum_failure_stops_normalization(self):
        from research.p2 import market_normalize as N
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d); rel = "binance_vision/spot/monthly/klines/X/1d/X-1d-2026-06.zip"
            p = d / "raw" / rel; p.parent.mkdir(parents=True)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z: z.writestr("X-1d-2026-06.csv", "1780272000000000,1,1,1,1,1,1780358399999999,1,1,0,0,0\n")
            p.write_bytes(buf.getvalue())
            p.with_name(p.name + ".CHECKSUM").write_text(hashlib.sha256(b"other").hexdigest() + "  X-1d-2026-06.zip\n")
            log = d / "log.jsonl"
            log.write_text(json.dumps({"status": "UPSTREAM_VERIFIED", "path": rel, "symbol": "X", "timeframe": "1d",
                                       "kind": "monthly", "local_sha256": hashlib.sha256(buf.getvalue()).hexdigest()}) + "\n")
            with self.assertRaises(SystemExit):
                N.main(["--raw", str(d / "raw"), "--log", str(log), "--out", str(d / "out")])


@unittest.skipUnless(HAVE_PD, "pandas/pyarrow/ta not available (run in the research venv)")
class TestCoverageGuards(unittest.TestCase):
    def test_pit_guard_fails_on_future_candle(self):
        from research.p2.market_coverage import pit_guard
        with self.assertRaises(SystemExit):
            pit_guard(1000, 1000)
        pit_guard(999, 1000)

    def test_ambiguity_never_resolved_without_unique_runtime_match(self):
        from research.p2.market_coverage import resolve_candle
        closes = {1: 10.0, 2: 11.0}
        self.assertEqual(resolve_candle([1, 2], {1: True, 2: True}, closes.get, Decimal("11"), True),
                         (2, "RESOLVED_BY_ENTRY_EQUALS_CLOSE"))
        self.assertEqual(resolve_candle([1, 2], {1: True, 2: True}, closes.get, Decimal("12"), True)[0], None)
        same = {1: 10.0, 2: 10.0}
        self.assertEqual(resolve_candle([1, 2], {1: True, 2: True}, same.get, Decimal("10"), True),
                         (None, "AMBIGUOUS_2_MATCHES"))
        self.assertEqual(resolve_candle([1], {1: True}, closes.get, Decimal("99"), False),
                         (1, "UNAMBIGUOUS_ENTRY_MISMATCH"))

    def test_seam_contiguous_gap_and_duplicate(self):
        import pyarrow as pa, pyarrow.parquet as pq
        from research.p2.market_coverage import seam
        from research.p2.market_normalize import BASE_COLS
        def write(path, opens):
            df = TestNormalization()._df(opens, tf="1d")
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pandas(df[BASE_COLS], preserve_index=False), path)
        day = 86_400_000; last = M.W2_START_MS - day
        for b_first, expect in ((M.W2_START_MS, "SEAM_CONTIGUOUS"), (M.W2_START_MS + day, "SEAM_GAP"), (last, "SEAM_FAIL")):
            with tempfile.TemporaryDirectory() as d:
                d = pathlib.Path(d)
                write(d / "ds/normalized/1d/X.parquet", [last - day, last])
                write(d / "b/1d/X.parquet", [b_first, b_first + day])
                self.assertEqual(seam(d / "b", d / "ds", "X", "1d", {})["status"], expect, b_first)


if __name__ == "__main__":
    unittest.main()
