"""Regression tests for the Phase-E adversarial review findings (B1, M1-M6, m1, m3, m5, N1)."""
import asyncio
import contextlib
import copy
import gzip
import io
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from p2_forward import app as A, config as C, transport as T, guards as G
from tests.test_regression_g2r import mk, book, depth, mini, gaps, lifes, drain, healthy_collector, stop_writer
from tests.test_verify_independent import VI, segs_of, recertify, run_e2e

BOOK = "btcusdt@bookTicker"


def test_spec():
    s = copy.deepcopy(VI.G2R_SPEC)
    s.update(name="e2e-test-spec", max_runtime_s=8, health_record_interval_s=2, candle_timeframes=["15m"], runtime_tolerance_s=2)
    s["cadence_ms"]["market"] = 2000
    s["clock_max_excess_ms"] = 500
    return s


class ReviewCollector(unittest.TestCase):
    def test_M2_data_stall_forces_reconnect(self):
        async def go(d):
            c = mk(d); m = A.now_ms()
            c.activity["conn1-depth"].transitions.append((m - 20_000, True))
            c.activity["conn1-depth"].data(m - 20_000)
            c.watchdog_once(); await asyncio.sleep(0.01)
            c.watchdog_once(); await asyncio.sleep(0.01)              # not repeated within 30 s
            return c
        with tempfile.TemporaryDirectory() as d:
            c = asyncio.run(go(d))
            self.assertEqual(c.conns[1].forced, 1); self.assertEqual(c.conns[0].forced, 0)
            self.assertEqual(len(lifes(drain(c), "data_stall_reconnect")), 1)

    def test_M3_value_from_before_reconnect_is_not_live(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 100_000
            a = c.activity["conn0-book"]
            a.transitions.append((S - 60_000, True))
            book(c, 1, S - 1100); mini(c, S - 10); c.sample(S)
            a.transitions.append((S + 300, False)); a.transitions.append((S + 1500, True))
            c.sample(S + 1000)                                         # down
            c.sample(S + 2000)                                         # up, but no data since reconnect
            mini(c, S + 2100); c.sample(S + 3000)                      # data-live again, book value pre-reconnect
            book(c, 2, S + 3200); c.sample(S + 4000)
            recs = drain(c)
            g = [x for x in gaps(recs) if x["stream_key"] == "book|BTCUSDT"][0]
            self.assertEqual((g["first_missing_ms"], g["last_missing_ms"]), (S + 1000, S + 3000))
            self.assertEqual(g["causes"], sorted(["ws_disconnect_reconnect", "conn_data_stale", "awaiting_post_reconnect_data"]))
            bt = [r["sample_ms"] for r in recs if r["type"] == "book" and r["symbol"] == "BTCUSDT"]
            self.assertEqual(bt, [S, S + 4000])

    def test_M4_clock_probes_never_open_breaker_and_failed_round_visible(self):
        async def go():
            from p2_forward.writer import new_stats
            def boom(*a, **k): raise T.aiohttp.ClientConnectionError("x")
            rc = T.RestClient(mock.Mock(get=boom), G.RateGuard(), new_stats())
            return [(await rc.get("/api/v3/time"))[0] for _ in range(6)]
        self.assertEqual(asyncio.run(go()), ["network_error"] * 6)
        class Rest:
            weight_used_total = 0
            async def get(self, *a, **k): return "network_error", None, None, None, None
        async def go2(d):
            c = mk(d); c.rest = Rest()
            with mock.patch.object(A.Collector, "_sleep", new=lambda self, s: asyncio.sleep(0)):
                t = asyncio.create_task(c.clock_task()); await asyncio.sleep(0.02); c.stop_event.set(); await t
            return c
        with tempfile.TemporaryDirectory() as d:
            c = asyncio.run(go2(d))
            self.assertTrue(lifes(drain(c), "clock_round_failed"))

    def test_NB1_open_short_gap_named_with_cause(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                c.tracks["ethusdt@depth20"].missing((A.now_ms() // 1000) * 1000, "stale_stream")
                st, hard, _, _ = c.health_eval()
                self.assertEqual(st, "DEGRADED"); self.assertIn("gap_short:ethusdt@depth20:stale_stream", hard)
                self.assertNotIn("expected_ne_observing", hard)
            finally:
                stop_writer(c)

    def test_M5_task_failure_is_a_hard_health_reason(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                c.task_fail_ms.append(A.now_ms())
                st, hard, _, _ = c.health_eval()
                self.assertEqual(st, "DEGRADED"); self.assertIn("task_failed_10min", hard)
            finally:
                stop_writer(c)

    def test_m5_persistent_seq_regression_resets_visibly(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 10_000
            book(c, 1000, S - 900)
            for i in range(20):
                book(c, 5 + i, S - 800 + i)
            self.assertEqual(c.stats["rejected"]["seq_regression"], 19); self.assertEqual(c.stats["seq_reset"], 1)
            c.sample(S)
            recs = drain(c)
            self.assertEqual([r["exchange_seq"] for r in recs if r["type"] == "book"], [24])
            self.assertTrue(lifes(recs, "seq_reset"))

    def test_m3_wall_clock_step_detected(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); c.wall_offset -= 5.0
            c.watchdog_once()
            self.assertEqual(c.stats["wall_clock_steps"], 1)
            self.assertTrue(lifes(drain(c), "wall_clock_step"))

    def test_m4_late_boundary_attributed_to_sampler(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 30_000
            depth(c, 1, S - 10); mini(c, S - 10); c.sample(S)
            c.sample_until(S + 3000, live=True)                       # processed ~27 s late
            depth(c, 2, S + 3500); mini(c, S + 3500); c.sample(S + 4000)
            g = [x for x in gaps(drain(c)) if x["stream_key"] == "depth|BTCUSDT"][0]
            self.assertEqual(g["cause"], "sampler_stall")


class ReviewVerifier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shutil
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = os.path.join(cls.tmp.name, "data"); os.makedirs(cls.base)
        cls.col, cls.code, cls.sess = run_e2e(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def copy(self):
        import shutil
        d = tempfile.mkdtemp(dir=self.tmp.name)
        dst = os.path.join(d, "data"); shutil.copytree(self.base, dst)
        return dst

    def test_B1_acceptance_pass_with_spec_and_markers(self):
        r = VI.verify(self.base, spec=test_spec(), expect_image="sha256:e2e", expect_commit="e2etest")
        self.assertTrue(r["PASS"], r["failures"]); self.assertTrue(r["acceptance"])
        fin = [v for k, v in r["control_markers_data"].items() if k.startswith("stop-")][0]
        self.assertEqual((fin["state"], fin["exit_code"]), ("STOPPED", 0))
        self.assertTrue(any(g["cause"] == "candle_not_fetched_at_stop" for g in r["gaps"]))   # m1: no silent candle loss

    def test_B1_pinned_spec_cannot_be_loosened_by_run_config(self):
        r = VI.verify(self.base, spec=VI.G2R_SPEC)
        self.assertFalse(r["acceptance"])
        for k in ("ACC_CADENCE_NOT_SPEC", "ACC_RUNTIME_OR_STOP_REASON", "ACC_RUNTIME_OR_HEALTH_INTERVAL_NOT_SPEC"):
            self.assertIn(k, r["failures"])

    def test_B1_identity_mismatch_and_signal_stop_fail(self):
        r = VI.verify(self.base, spec=test_spec(), expect_image="sha256:other")
        self.assertIn("ACC_IMAGE_ID_MISMATCH", r["failures"])
        d = self.copy()
        life = segs_of(d, "lifecycle")[0]
        def sig(ls):
            for x in ls:
                if x["payload"].get("event") == "stop":
                    x["payload"]["reason"] = "signal"
            return ls
        recertify(d, life, sig)
        self.assertIn("ACC_RUNTIME_OR_STOP_REASON", VI.verify(d, spec=test_spec())["failures"])

    def test_B1_forbidden_lifecycle_and_degraded_health_fail(self):
        d = self.copy()
        hseg = segs_of(d, "health")[0]
        def degrade(ls):
            for x in ls[1:-1]:
                x["payload"]["state"] = "DEGRADED"; x["payload"]["reasons"] = ["task_stale:sampler"]
            return ls
        recertify(d, hseg, degrade)
        f = VI.verify(d, spec=test_spec())["failures"]
        self.assertIn("ACC_HEALTH_STATE_FORBIDDEN", f); self.assertIn("ACC_HEALTH_BUDGET_EXCEEDED", f)

    def test_NB1_short_network_gap_health_is_acceptable_but_internal_cause_is_not(self):
        d = self.copy()
        hseg = segs_of(d, "health")[0]
        def short(cause):
            def f(ls):
                x = ls[2]; x["payload"]["state"] = "DEGRADED"
                x["payload"]["reasons"] = [f"gap_short:ethusdt@depth20:{cause}"]
                return ls
            return f
        recertify(d, hseg, short("stale_stream"))
        self.assertNotIn("ACC_HEALTH_STATE_FORBIDDEN", VI.verify(d, spec=test_spec())["failures"])
        d2 = self.copy()
        recertify(d2, segs_of(d2, "health")[0], short("sampler_stall"))
        self.assertIn("ACC_HEALTH_STATE_FORBIDDEN", VI.verify(d2, spec=test_spec())["failures"])

    def test_M1_first_message_inside_boundary_ms_is_excused(self):
        d = self.copy()
        bsegs = segs_of(d, "book")
        recs = sorted((json.loads(l) for s in bsegs for l in gzip.open(s, "rt")), key=lambda r: r["sample_ms"])
        b0 = [r for r in recs if r["endpoint"] == BOOK][0]["sample_ms"]
        for s in bsegs:
            recertify(d, s, lambda ls: [x for x in ls if not (x["endpoint"] == BOOK and x["sample_ms"] == b0)])
        life = segs_of(d, "lifecycle")[0]
        def ready_at(ns):
            def f(ls):
                for x in ls:
                    if x["payload"].get("event") == "stream_ready" and x["payload"]["stream"] == BOOK:
                        x["payload"]["ready_ns"] = ns; x["payload"]["ready_ms"] = ns // 1_000_000
                return ls
            return f
        d2 = self.copy(); [recertify(d2, s, lambda ls: [x for x in ls if not (x["endpoint"] == BOOK and x["sample_ms"] == b0)]) for s in segs_of(d2, "book")]
        recertify(d, life, ready_at(b0 * 1_000_000 + 300_000))             # first msg 0.3 ms after b0: excused
        r = VI.verify(d)
        self.assertNotIn("UNEXPLAINED_MISS", r["failures"], r["failures"])
        recertify(d2, segs_of(d2, "lifecycle")[0], ready_at(b0 * 1_000_000 - 1))   # first msg before b0: a real miss
        self.assertIn("UNEXPLAINED_MISS", VI.verify(d2)["failures"])

    def test_M6_independent_freshness_and_symbol(self):
        d = self.copy()
        seg = segs_of(d, "depth")[0]
        def old(ls):
            x = ls[4]; x["recv_ts_ns"] = (x["sample_ms"] - 3000) * 1_000_000
            x["observed_at_ms"] = x["available_at_ms"] = x["sample_ms"] - 3000
            return ls
        recertify(d, seg, old)
        self.assertIn("STALE_VALUE_PERSISTED", VI.verify(d)["failures"])
        d2 = self.copy()
        bseg = segs_of(d2, "book")[0]
        def wrong(ls):
            ls[3]["payload"]["s"] = "XRPUSDT"; return ls
        recertify(d2, bseg, wrong)
        self.assertIn("PAYLOAD_SYMBOL_MISMATCH", VI.verify(d2)["failures"])

    def test_m1_lost_control_record_detected(self):
        d = self.copy()
        hseg = segs_of(d, "health")[0]
        recertify(d, hseg, lambda ls: ls[:2] + ls[3:])
        self.assertIn("CONTROL_SEQ_NOT_CONTIGUOUS", VI.verify(d)["failures"])


if __name__ == "__main__":
    unittest.main()
