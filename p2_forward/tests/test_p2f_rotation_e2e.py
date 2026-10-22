"""P2F 1.5.0 rotation repair - end-to-end compatibility on a LAGGING fake exchange (accelerated calendar).

The full continuous collector runs ~100 s (2+ closed days, proactive rotations every 30 s, universe transitions with
add / re-tier / remove). Every replacement socket TRAILS the socket it replaces (exchange ids are time-based and
identical across sockets, so a trailing socket re-delivers OLDER ids). Then the UNCHANGED consumers read the result:
  * verifier/verify_continuous.py on every closed day (PASS, no unexplained boundary);
  * ops/p2f_seal_day.py --allow-test-calendar on a copy (PASS seals);
  * the P2-C reader (p2_research/reader.py, other branch; env P2C_READER_DIR) at record level: validate_record +
    control-record ingestion for every record, including the new lifecycle events;
  * ops/p2f_cont_monitor.py --once (reads health + incidents; never writes the dataset).
"""
import importlib.util
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from tests.test_g3_prereqs import FakeWS2
from tests.test_p2cr_continuous import UniverseShiftExchange, VC, lifecycle, run_continuous, setup_calendar
from tests.test_verify_independent import segs_of
from p2_forward import cal

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAG_S = 0.4
T0 = time.time() - 60                    # id origin: ids grow with exchange time and are identical across sockets


class LagWS2(FakeWS2):
    """FakeWS2 with exchange-time-based ids: u / lastUpdateId = base + 10 ms ticks of (now - lag); miniTicker E =
    now - lag. A socket with lag re-delivers ids the other socket already delivered."""

    def __init__(self, url, lag):
        super().__init__(url)
        self.lag = lag
        self.next_book = self.t + 0.03
        # miniTicker on a shared 1 s wall-clock grid; a lagged socket emits 0.2 s after an unlagged one, so during
        # every overlap its copy has an E 0.2 s OLDER than the copy just applied -> a stale component, whichever
        # socket trails. (A per-socket phase made each overlap all-stale or none: 10 of 36 overlaps had none.)
        self.next_mini = math.ceil(self.t) + (0.2 if lag > 0 else 0.0)

    @staticmethod
    def _id(s, t):
        return 1_000_000_000 + 10_000_000 * (sum(map(ord, s)) % 97) + int((t - T0) * 100)

    async def __anext__(self):
        import asyncio
        while True:
            if self.closed:
                raise StopAsyncIteration
            if self.pending:
                p = self.pending.pop(0)
                return p if not isinstance(p, dict) else self._m2(p)
            now = time.time(); te = now - self.lag
            if now >= self.next_book:
                self.next_book += 0.05
                for s in self.streams:
                    if s.endswith("@bookTicker"):
                        self.pending.append(self._m(s, {"u": self._id(s, te), "s": s.split("@")[0].upper(), "b": "1", "a": "2"}))
            elif now >= self.next_depth:
                self.next_depth += 1.0
                for s in self.streams:
                    if "@depth" in s:
                        n = int(s.split("@depth")[1])
                        self.pending.append(self._m(s, {"lastUpdateId": self._id(s, te), "bids": [["1", "1"]] * n,
                                                        "asks": [["2", "1"]] * n}))
            elif now >= self.next_mini:
                self.next_mini += 1.0
                if "!miniTicker@arr" in self.streams:
                    from tests.test_g3_prereqs import SYN
                    self.pending.append(self._m("!miniTicker@arr", [{"e": "24hrMiniTicker", "E": int(te * 1000) - 3,
                                                                     "s": x, "c": "1"} for x in SYN]))
            else:
                await asyncio.sleep(max(0.0, min(self.next_book, self.next_depth, self.next_mini) - now))

    def _m2(self, p):
        from unittest import mock
        from p2_forward import app as A
        return mock.Mock(type=A.aiohttp.WSMsgType.TEXT, data=json.dumps(p))


class LagExchange(UniverseShiftExchange):
    """Per connection (first stream of the URL): sockets alternate between lag 0 and lag LAG_S, so EVERY rotation's
    replacement trails or leads the socket it replaces (both directions are exercised)."""

    def __init__(self):
        super().__init__()
        self.n = {}

    def ws_connect(self, url, **kw):
        k = url.split("streams=")[1]
        self.n[k] = self.n.get(k, 0) + 1
        w = LagWS2(url, LAG_S if self.n[k] % 2 == 0 else 0.0)
        self.ws.append(w)
        return w


def load_reader():
    d = os.environ.get("P2C_READER_DIR")
    if not d or not os.path.exists(os.path.join(d, "reader.py")):
        return None
    spec = importlib.util.spec_from_file_location("p2c_reader", os.path.join(d, "reader.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


class LaggingRotationEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = os.path.join(cls.tmp.name, "data")
        setup_calendar()
        cls.c, cls.code, cls.sess = run_continuous(cls.base, 100, sess=LagExchange())
        cls.days = sorted(f[:-5] for f in os.listdir(os.path.join(cls.base, "days")))
        cls.reports = {d: VC.verify_day(cls.base, d, allow_test_calendar=True) for d in cls.days}

    @classmethod
    def tearDownClass(cls):
        cal.reset()
        cls.tmp.cleanup()

    def test_clean_stop_and_rotations_with_lag(self):
        self.assertEqual(self.code, 0)
        rot = [r["payload"] for r in lifecycle(self.base, "ws_rotation")]
        self.assertTrue(any(p["reason"] == "universe_transition" for p in rot))
        self.assertTrue(any(p["reason"] == "proactive_lifetime" for p in rot))
        self.assertTrue(all(p["overlap_ok"] for p in rot))
        done = [p for p in rot if "handoff" in p and p["handoff"]["reason"] != "stopping"]
        self.assertTrue(done and all(p["handoff"]["complete"] for p in done), [p.get("handoff") for p in rot])

    def test_no_reset_no_regression_but_stale_copies_seen(self):
        cnt = self.c.counters()
        self.assertEqual(cnt["seq_reset"], 0); self.assertEqual(cnt["seq_regression"], 0)
        self.assertGreater(cnt["seq_stale"], 0)                                   # the replacement really trailed
        self.assertGreater(cnt["market_component_stale"], 0)
        self.assertFalse(lifecycle(self.base, "seq_reset"))

    def test_handoff_audit_records_old_final_and_reach(self):
        hs = [r["payload"] for r in lifecycle(self.base, "ws_handoff")]
        self.assertTrue(hs)
        full = [h for h in hs if h["audit_end"] == "all_reached"]
        self.assertTrue(full)
        for h in full:
            self.assertFalse(h["unresolved"])
            for s, x in h["streams"].items():
                if x["class"] in ("proven", "ahead", "resumed"):
                    self.assertGreaterEqual(x["reach_seq"], x["old_final"], (h["conn"], s))
        self.assertIn("proven", {k for h in hs for k in h["classes"]})

    def test_every_closed_day_verifies_with_the_unchanged_verifier(self):
        self.assertGreaterEqual(len(self.days), 2, self.days)
        for d, r in self.reports.items():
            self.assertTrue(r["PASS"], json.dumps({"day": d, "f": r["failures"], "ex": r["examples"]}, default=str)[:3000])
            self.assertEqual(r["info"]["totals"].get("unexplained", 0), 0)

    def test_incidents_no_seq_reset_no_critical(self):
        st = json.loads(pathlib.Path(self.base, "incidents", "state.json").read_text())
        keys = {i["key"] for i in st["incidents"]}
        self.assertNotIn("seq_reset", keys)
        self.assertFalse([k for k in keys if k.startswith("rotation_")], keys)
        self.assertFalse([i for i in st["incidents"] if i["severity"] == "CRITICAL"])

    def test_seal_job_passes_on_a_copy(self):
        d = tempfile.mkdtemp(dir=self.tmp.name); dst = os.path.join(d, "data"); shutil.copytree(self.base, dst)
        for day in self.days:
            r = subprocess.run([sys.executable, str(ROOT / "ops" / "p2f_seal_day.py"), dst, "--day", day,
                                "--allow-test-calendar"], capture_output=True, text=True, timeout=300)
            if r.returncode == 3:                                                   # last day: spillover not final
                continue
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(json.loads(pathlib.Path(dst, "seals", f"{day}.json").read_text())["result"], "PASS")

    def test_p2c_reader_accepts_every_record(self):
        RD = load_reader()
        if RD is None:
            self.skipTest("P2C_READER_DIR not set")
        import gzip
        B = RD.Bundle(); B.range_start_ms, B.range_end_ms = 0, 1 << 62
        n, ctrl = 0, []
        for t in ("book", "depth", "market", "gap", "lifecycle", "health", "clock", "universe"):
            for seg in segs_of(self.base, t):
                for line in gzip.open(seg, "rt"):
                    r = json.loads(line); RD.validate_record(r); n += 1
                    if t in ("gap", "lifecycle", "health", "clock"):
                        ctrl.append(r)
        ctrl.sort(key=lambda r: (r["available_at_ms"], r["obs_id"]))
        RD.process_control(B, ctrl, {self.c.boot_id[:8]})
        ev = {e for _, e, _, _ in B.lifecycle}
        self.assertTrue({"ws_handoff", "ws_rotation"} <= ev, ev)
        self.assertGreater(n, 1000)

    def test_monitor_once_reads_the_dataset_read_only(self):
        out = tempfile.mkdtemp(dir=self.tmp.name)
        before = sorted((p, os.path.getmtime(os.path.join(r, p))) for r, _, fs in os.walk(self.base) for p in fs)
        r = subprocess.run([sys.executable, str(ROOT / "ops" / "p2f_cont_monitor.py"), "--dataset", self.base,
                            "--cid", "0" * 64, "--out", out, "--once"], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        st = json.load(open(os.path.join(out, "status.json")))
        self.assertNotIn("incident:seq_reset", st.get("severity_reasons", []))
        after = sorted((p, os.path.getmtime(os.path.join(r_, p))) for r_, _, fs in os.walk(self.base) for p in fs)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
