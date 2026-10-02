"""Prepared during G2 (read-only phase). EXPECTED TO FAIL on 7a3cafe; must PASS after fixes F1-F9.

Interface expected after the fixes:
- Collector.stream_state[stream_name]["state"] in {"NOT_YET_OBSERVING","OBSERVING","GAP_OPEN","DISCONNECTED"};
- lifecycle event "stream_ready" on first observation; gap payload has first_missing_ms, last_missing_ms,
  missing_samples; gap cause uses the stream's own connection;
- book streams on a live connection persist the last value with unchanged=True (no stale gap).
"""
import tempfile
import time
import unittest

from p2_forward import app as A, config as C, universe as U

BOOK, DEPTH = "btcusdt@bookTicker", "btcusdt@depth20"


class Conn:
    def __init__(self, name, streams, connected=True):
        self.name, self.streams, self.connected = name, streams, connected


def mk(d):
    cfg = {**C.DEFAULTS, "data_dir": d, "enabled": True, "max_runtime_s": 60}
    c = A.Collector(cfg); c.universe = U.tier0_only(cfg); c.build_streams(); c.started_ms = A.now_ms()
    c.conns = [Conn("conn0-book", [n for n in c.streams if "book" in n]), Conn("conn1-depth", [n for n in c.streams if "depth" in n])]
    return c


def drain(c):
    return [c.q.get_nowait() for _ in range(c.q.qsize())]


def book(c, u, recv_ms, sym="btcusdt"):
    c.on_message(None, {"stream": f"{sym}@bookTicker", "data": {"u": u, "s": sym.upper()}}, int(recv_ms * 1_000_000))


def depth(c, u, recv_ms, sym="btcusdt", n=20):
    c.on_message(None, {"stream": f"{sym}@depth{n}", "data": {"lastUpdateId": u, "bids": [], "asks": []}}, int(recv_ms * 1_000_000))


class PendingSampling(unittest.TestCase):
    def _burst(self, n):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 5000
            book(c, 1, S - 500)
            for i in range(n):
                book(c, 2 + i, S + 1 + i * 0.01)                    # n messages after the boundary, before wake-up
            c.sample(S)
            bt = [r for r in drain(c) if r["type"] == "book"]
            self.assertEqual(len(bt), 1); self.assertEqual(bt[0]["exchange_seq"], 1)
            self.assertLessEqual(bt[0]["observed_at_ms"], S)

    def test_burst_8(self): self._burst(8)
    def test_burst_100(self): self._burst(100)

    def test_delayed_sampler_and_boundary_edges(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 5000
            book(c, 1, S - 1); book(c, 2, S); book(c, 3, S + 1)
            c.sample(S)                                              # sampler woke 900 ms late is equivalent
            self.assertEqual([r["exchange_seq"] for r in drain(c) if r["type"] == "book"], [2])

    def test_high_rate_no_skips(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S0 = (A.now_ms() // 1000) * 1000 - 70_000; u = 0
            for s in range(60):
                for k in range(1000):
                    u += 1; book(c, u, S0 + s * 1000 + k * 0.999)
                depth(c, s + 1, S0 + s * 1000 + 10)
                c.sample(S0 + (s + 1) * 1000)
            recs = drain(c)
            self.assertEqual(len([r for r in recs if r["type"] == "book"]), 60)
            self.assertEqual([r for r in recs if r["type"] == "gap"], [])


class PendingGapStateMachine(unittest.TestCase):
    def test_never_observed_no_gap(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000
            for k in range(10): c.sample(S - 10_000 + k * 1000)
            self.assertEqual([r for r in drain(c) if r["type"] == "gap"], [])
            self.assertEqual(c.stream_state[BOOK]["state"], "NOT_YET_OBSERVING")

    def test_startup_transition_emits_stream_ready_no_gap(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 10_000
            c.sample(S); depth(c, 1, S + 300); c.sample(S + 1000)
            recs = drain(c)
            self.assertFalse([r for r in recs if r["type"] == "gap"])
            self.assertTrue(any(r["type"] == "lifecycle" and r["payload"]["event"] == "stream_ready" for r in recs))
            self.assertEqual(c.stream_state[DEPTH]["state"], "OBSERVING")

    def test_gap_start_end_and_count(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 30_000
            depth(c, 1, S - 100); c.sample(S)                         # last persisted sample S
            for k in range(1, 8): c.sample(S + k * 1000)               # silence > 5 s while connected -> stale gap
            depth(c, 2, S + 7_500); c.sample(S + 8000)
            g = [r for r in drain(c) if r["type"] == "gap"][0]["payload"]
            self.assertEqual(g["first_missing_ms"], S + 1000)
            self.assertEqual(g["last_missing_ms"], S + 7000)
            self.assertEqual(g["missing_samples"], 7)

    def test_low_rate_book_live_connection_is_unchanged_not_gap(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 400_000
            book(c, 1, S - 10)
            for k in range(300): c.sample(S + k * 1000)
            recs = drain(c)
            bt = [r for r in recs if r["type"] == "book"]
            self.assertEqual(len(bt), 300); self.assertTrue(all(r["unchanged"] for r in bt[1:]))
            self.assertFalse([r for r in recs if r["type"] == "gap"])

    def test_gap_cause_uses_own_connection(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 30_000
            depth(c, 1, S - 100); book(c, 1, S - 100); c.sample(S)
            c.conns[1].connected = False                              # depth connection down, book connection up
            for k in range(1, 4): c.sample(S + k * 1000)
            c.conns[1].connected = True; depth(c, 2, S + 3_500); c.sample(S + 4000)
            g = [r for r in drain(c) if r["type"] == "gap"][0]["payload"]
            self.assertEqual(g["stream_key"], "depth|BTCUSDT"); self.assertIn("reconnect", g["cause"])


class PendingClockAndMarket(unittest.TestCase):
    def test_clock_min_rtt_uncertainty(self):
        from p2_forward.guards import ClockGuard
        c = ClockGuard(500, 2000)
        c.update_samples([(1370, 0, 1020), (1100, 0, 260), (1200, 0, 700)])   # (server, t0, t1)
        self.assertAlmostEqual(c.last_skew_ms, -30.0); self.assertAlmostEqual(c.uncertainty_ms, 130.0)
        self.assertEqual(c.state, "OK")

    def test_market_component_age_and_startup_flag(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 60_000) * 60_000 - 120_000; c.ready_ms = S - 1000
            c.on_message(None, {"stream": "!miniTicker@arr", "data": [{"s": "BTCUSDT", "E": S - 50}]}, (S - 40) * 10**6)
            c.sample(S)
            m = [r for r in drain(c) if r["type"] == "market"][0]
            self.assertIn("component_recv_ms", m); self.assertFalse(m["startup_complete"])


if __name__ == "__main__":
    unittest.main()


class PendingPass2(unittest.TestCase):
    """F19 sampler stall, F20 handler exception, F22 subscribe error, F23 418 closes WS (expected to FAIL now)."""

    def test_sampler_stall_processes_every_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 20_000
            depth(c, 1, S - 10); c.sample(S)
            for k in range(1, 4): depth(c, 1 + k, S + k * 1000 - 5)
            c.sample_until(S + 3000)                      # loop stalled: boundaries S+1000..S+3000 processed at once
            seqs = [r["exchange_seq"] for r in drain(c) if r["type"] == "depth"]
            self.assertEqual(seqs, [1, 2, 3, 4])

    def test_handler_exception_does_not_kill_connection(self):
        import asyncio
        from unittest import mock
        from p2_forward import transport as T
        from tests.test_collector import FakeWS, textmsg
        async def go():
            calls = {"n": 0}
            def boom(*a): raise KeyError("unexpected shape")
            def connect(url, **kw):
                calls["n"] += 1
                return FakeWS([textmsg({"stream": "x", "data": {}})])
            c = T.WSConnection("c0", ["x"], mock.Mock(ws_connect=connect), boom, lambda *a: None, lambda *a: None)
            c.backoff.next_delay = lambda: 0.0
            t = asyncio.create_task(c.run()); await asyncio.sleep(0.05); await c.close(); t.cancel()
            return calls["n"], c
        n, c = asyncio.run(go())
        self.assertGreaterEqual(n, 2)                    # reconnected instead of dying silently

    def test_subscribe_error_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d)
            c.on_subscribe_result(c.conns[0], {"error": {"code": 2, "msg": "Invalid request"}, "id": 1})
            recs = drain(c)
            self.assertTrue(any(r["type"] == "lifecycle" and r["payload"]["event"] == "subscribe_failed" for r in recs))
            self.assertEqual(c.health()["state"] if c.state == "RUNNING" else "DEGRADED", "DEGRADED")
