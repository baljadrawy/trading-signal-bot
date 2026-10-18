"""P2-CR continuous mode, offline end-to-end on an ACCELERATED calendar (1 calendar hour = 2 s, 1 day = 48 s):
daily universe refresh with tier transitions (F10 / R05), proactive rotation (F24), day checkpoints and gap split,
day close, restart into the same logical dataset with explicit downtime (CR-R07), persistent incidents, and the
independent day verifier (verify_continuous) on every closed day, plus its tamper detection."""
import asyncio
import contextlib
import datetime as dt
import gzip
import importlib.util
import io
import json
import os
import pathlib
import shutil
import tempfile
import time
import unittest
from unittest import mock

from p2_forward import app as A, cal, config as C, writer as W
from tests.test_g3_prereqs import FakeExchange, exchange_info, tickers, TEST_CFG
from tests.test_verify_independent import ENV, FakeResp, segs_of, recertify

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("verify_continuous", ROOT / "verifier" / "verify_continuous.py")
VC = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(VC)
HOUR_MS = 2000


def setup_calendar(hours_before_day_end=10):
    h = time.time_ns() // 1_000_000 // HOUR_MS
    cal.configure(HOUR_MS, h - (24 - hours_before_day_end), dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc))


class UniverseShiftExchange(FakeExchange):
    """Evaluation 1 = baseline; 2+: A15 becomes liquid (added to Tier 2, A03 re-tiered 2 -> 1);
    3+: A05 stops trading (removed; never silently)."""

    def __init__(self):
        super().__init__()
        self.evals = 0

    def get(self, url, params=None, timeout=None):
        if url.endswith("/exchangeInfo"):
            self.evals += 1
            ei = exchange_info()
            if self.evals >= 3:
                for x in ei["symbols"]:
                    if x["symbol"] == "A05USDT":
                        x["status"] = "BREAK"
            self.gets.append(url)
            return FakeResp(ei)
        if url.endswith("/ticker/24hr"):
            tk = tickers()
            if self.evals >= 2:
                for x in tk:
                    if x["symbol"] == "A15USDT":
                        x["quoteVolume"] = "8.85e9"
            self.gets.append(url)
            return FakeResp(tk)
        return super().get(url, params, timeout)


def cont_cfg(d, **over):
    return {**C.DEFAULTS, **TEST_CFG, "enabled": True, "mode": "continuous", "max_runtime_s": 0, "dataset_id": "test-ds",
            "data_dir": d, "flush_interval_s": 0.2, "health_interval_s": 1.0, "health_record_interval_s": 2,
            "host_label": "e2e", "cadence_ms": {**C.DEFAULTS["cadence_ms"], "t2_book": 1000, "t2_depth": 2000,
                                                 "t1_book": 2000, "t1_depth": 4000, "market": 2000},
            "candle_timeframes": ["15m"], "disk_warn_free_gb": 0.02, "disk_stop_free_gb": 0.01,
            "universe_retry_backoff_s": [0.05], "universe_refresh_at_s": 4, "universe_transition_delay_s": 2,
            "day_close_after_s": 4, "ws_rotation_s": 30, **over}


def run_continuous(d, seconds, sess=None, **over):
    cfg = cont_cfg(d, **over); C.validate(cfg)
    c = A.Collector(cfg)
    s = sess or UniverseShiftExchange()
    c.session_factory = lambda: s

    async def main():
        asyncio.get_running_loop().call_later(seconds, c._signal_stop)
        return await c.run()
    with mock.patch.dict(os.environ, ENV), contextlib.redirect_stderr(io.StringIO()):
        code = asyncio.run(main())
    return c, code, s


def lifecycle(d, event=None):
    out = []
    for s in segs_of(d, "lifecycle"):
        for line in gzip.open(s, "rt"):
            r = json.loads(line)
            if event is None or r["payload"].get("event") == event:
                out.append(r)
    return sorted(out, key=lambda r: r["recv_ts_ns"])


class ContinuousEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = os.path.join(cls.tmp.name, "data")
        setup_calendar()
        cls.cal = cal.params()
        cls.c1, cls.code1, cls.sess = run_continuous(cls.base, 98)        # crosses 2 day boundaries
        cls.c2, cls.code2, _ = run_continuous(cls.base, 40, sess=cls.sess)  # restart into the same dataset
        cls.days = sorted(f[:-5] for f in os.listdir(os.path.join(cls.base, "days")))
        cls.reports = {d: VC.verify_day(cls.base, d, allow_test_calendar=True) for d in cls.days}

    @classmethod
    def tearDownClass(cls):
        cal.reset()
        cls.tmp.cleanup()

    def copy(self):
        d = tempfile.mkdtemp(dir=self.tmp.name); dst = os.path.join(d, "data"); shutil.copytree(self.base, dst)
        return dst

    def test_runs_stopped_cleanly(self):
        self.assertEqual((self.code1, self.code2), (0, 0))
        self.assertEqual((self.c1.state, self.c2.state), ("STOPPED", "STOPPED"))

    def test_every_closed_day_verifies_independently(self):
        self.assertGreaterEqual(len(self.days), 3, self.days)
        for d, r in self.reports.items():
            self.assertTrue(r["PASS"], json.dumps({"day": d, "f": r["failures"], "ex": r["examples"]}, default=str)[:3000])
            self.assertEqual(r["info"]["totals"].get("unexplained", 0), 0)
            self.assertGreater(r["info"]["totals"]["persisted"], 0)

    def test_universe_transitions_add_retier_remove(self):
        tr = [r["payload"] for r in lifecycle(self.base, "universe_transition")]
        self.assertGreaterEqual(len(tr), 2, tr)
        self.assertIn("a15usdt@bookTicker", tr[0]["added"])
        self.assertIn("A03USDT", {x["symbol"] for x in tr[0]["retiered"]})
        self.assertTrue(any("a05usdt@bookTicker" in t["removed"] for t in tr[1:]))
        kinds = {e["kind"] for r in self.reports.values() for e in r["info"]["epochs"]}
        self.assertIn("transition", kinds)
        for t in tr:                                             # disjoint per-connection lists, within budget
            names = [n for ss in t["conns"].values() for n in ss]
            self.assertEqual(len(names), len(set(names)))

    def test_proactive_rotation_and_universe_rotation_recorded(self):
        rot = [r["payload"] for r in lifecycle(self.base, "ws_rotation")]
        self.assertTrue(any(p["reason"] == "proactive_lifetime" for p in rot), rot[:3])
        self.assertTrue(any(p["reason"] == "universe_transition" for p in rot))
        self.assertTrue(all(p["overlap_ok"] for p in rot), rot)

    def test_restart_is_explicit_downtime_not_stitched(self):
        dts = sorted(pathlib.Path(self.base, "runs").glob("downtime-*.json"))
        self.assertEqual(len(dts), 2)
        causes = sorted(json.loads(p.read_text())["cause"] for p in dts)
        self.assertEqual(causes, ["clean_stop", "first_run"])
        r = VC.run_chain(self.base, VC.VI.Report())
        self.assertEqual([x["boot_id"] for x in r], [self.c1.boot_id, self.c2.boot_id])
        rs = [r for r in self.reports.values() if len(r["info"]["runs"]) == 2]
        self.assertTrue(rs, "a day containing both runs was verified")
        self.assertGreater(rs[0]["info"]["downtime_ms"].get("clean_stop", 0), 0)
        iv = [i for i in rs[0]["info"]["downtime_intervals"] if i["cause"] == "clean_stop"]
        self.assertEqual(len(iv), 1); self.assertEqual(iv[0]["next_boot"], self.c2.boot_id)

    def test_closed_days_leave_hot_paths(self):
        opened = W.open_days(self.base)
        self.assertFalse(set(opened) & set(self.days))
        st = W.scan_lifecycle(self.base)
        self.assertTrue(all(pathlib.Path(p).parent.name in opened for v in st.values() for p in v))

    def test_day_checkpoints_and_dataset_identity(self):
        cps = [r["payload"] for r in lifecycle(self.base, "day_checkpoint")]
        self.assertGreaterEqual(len(cps), 3)
        self.assertTrue(all(p["calendar"] == self.cal for p in cps))
        ds = json.loads(pathlib.Path(self.base, "dataset.json").read_text())
        self.assertEqual((ds["dataset_id"], ds["calendar"]), ("test-ds", self.cal))

    def test_incident_state_persisted_and_no_critical(self):
        st = json.loads(pathlib.Path(self.base, "incidents", "state.json").read_text())
        self.assertFalse([i for i in st["incidents"] if i["severity"] == "CRITICAL"], st)

    def test_tamper_dropped_observation_is_unexplained(self):
        d = self.copy()
        day = self.days[1]
        seg = [s for s in segs_of(d, "book") if f"/{day}/" in str(s)][3]
        def drop(ls):
            return [x for i, x in enumerate(ls) if i != 5]
        recertify(d, seg, drop)
        rel = os.path.relpath(seg, d)
        mp = pathlib.Path(d, "manifests", f"{day}.jsonl")                # keep manifest + day close consistent
        os.chmod(mp, 0o644)
        ents = [json.loads(l) for l in mp.read_text().splitlines()]
        for e in ents:
            if e["segment"] == rel:
                e["sha256"] = VC.VI.sha256(str(seg)); e["records"] -= 1
        mp.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in ents))
        r = VC.verify_day(d, day, allow_test_calendar=True)
        self.assertFalse(r["PASS"])
        self.assertTrue({"UNEXPLAINED_MISS", "DAY_CLOSE_LISTING_MISMATCH", "DAY_CLOSE_MANIFEST_SHA_MISMATCH"} &
                        set(r["failures"]), r["failures"])

    def test_tamper_missing_downtime_record_fails(self):
        d = self.copy()
        p = pathlib.Path(d, "runs", f"downtime-{self.c2.boot_id}.json")
        os.chmod(p.parent, 0o755); os.chmod(p, 0o644); p.unlink()
        rs = [day for day, r in self.reports.items() if len(r["info"]["runs"]) == 2]
        r = VC.verify_day(d, rs[0], allow_test_calendar=True)
        self.assertFalse(r["PASS"])
        self.assertIn("DOWNTIME_RECORD_MISSING", r["failures"])

    def test_production_calendar_required_by_default(self):
        r = VC.verify_day(self.base, self.days[0])
        self.assertIn("NON_PRODUCTION_CALENDAR", r["failures"])


if __name__ == "__main__":
    unittest.main()
