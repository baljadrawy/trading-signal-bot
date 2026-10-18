"""G2-Repeat regression suite (P2-E1). Synthetic data / scratch dirs / fake sessions only: no network.

Each test names the finding(s) it guards (see docs/p2/P2E1_FIX_MATRIX.md).
"""
import asyncio
import contextlib
import glob
import gzip
import io
import json
import os
import pathlib
import queue
import stat
import tempfile
import time
import unittest
from unittest import mock

from p2_forward import app as A, config as C, provenance as P, record as R, universe as U, writer as Wm, transport as T
from p2_forward.guards import RateGuard

BOOK, DEPTH, EBOOK, EDEPTH = "btcusdt@bookTicker", "btcusdt@depth20", "ethusdt@bookTicker", "ethusdt@depth20"


class Conn:
    def __init__(self, name, streams, connected=True):
        self.name, self.streams, self.connected, self.reconnects = name, streams, connected, 0
        self.forced = 0
        self.sub_requests = {}
        self._closing = False

    async def force_reconnect(self, reason=""):
        self.forced += 1

    async def suspend(self):
        pass


def mk(d, universe=None, **over):
    cfg = {**C.DEFAULTS, "data_dir": d, "enabled": True, "max_runtime_s": 60, **over}
    c = A.Collector(cfg)
    c.universe = universe or U.tier0_only(cfg)
    c.build_streams(); c.started_ms = A.now_ms()
    c.conns = [Conn(n, s) for n, s in c._conn_streams()]
    return c


def drain(c):
    return [c.q.get_nowait() for _ in range(c.q.qsize())]


def book(c, u, recv_ms, sym="btcusdt"):
    c.on_message(None, {"stream": f"{sym}@bookTicker", "data": {"u": u, "s": sym.upper()}}, int(recv_ms) * 1_000_000)


def depth(c, u, recv_ms, sym="btcusdt", n=20):
    c.on_message(None, {"stream": f"{sym}@depth{n}", "data": {"lastUpdateId": u, "bids": [["1", "1"]], "asks": [["2", "1"]]}},
                 int(recv_ms) * 1_000_000)


def mini(c, recv_ms, syms=("BTCUSDT", "ETHUSDT")):
    c.on_message(None, {"stream": "!miniTicker@arr", "data": [{"s": s, "E": recv_ms - 5, "c": "1"} for s in syms]},
                 int(recv_ms) * 1_000_000)


def gaps(recs):
    return [r["payload"] for r in recs if r["type"] == "gap"]


def lifes(recs, ev=None):
    return [r["payload"] for r in recs if r["type"] == "lifecycle" and (ev is None or r["payload"]["event"] == ev)]


# ------------------------------------------------------------------------------------------------ sampling (F1/F19)
class Sampling(unittest.TestCase):
    def test_burst_1000_exact_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 5000; S_ns = S * 1_000_000
            for i in range(1000):                         # 1000 msgs from S-0.5 ms to S+0.4995 ms (ns resolution)
                c.on_message(None, {"stream": BOOK, "data": {"u": i + 1}}, S_ns - 500_000 + i * 1000)
            c.sample(S)
            bt = [r for r in drain(c) if r["type"] == "book"][0]
            self.assertEqual(bt["exchange_seq"], 501)    # last message with recv_ns <= S exactly
            self.assertLessEqual(bt["recv_ts_ns"], S_ns)

    def test_stall_beyond_hold_window_is_explicit_gap(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d, sample_hold_window_s=10); S = (A.now_ms() // 1000) * 1000 - 100_000
            depth(c, 1, S - 10); mini(c, S - 10); c.sample(S)
            for k in range(1, 31):                        # 30 s of updates, sampler stalled the whole time
                depth(c, 1 + k, S + k * 1000 - 5); mini(c, S + k * 1000 - 5)
            n = c.sample_until(S + 30_000)
            self.assertEqual(n, 30)
            recs = drain(c)
            got = sorted(r["sample_ms"] for r in recs if r["type"] == "depth" and r["symbol"] == "BTCUSDT")
            depth(c, 40, S + 30_500); c.sample(S + 31_000)
            g = [x for x in gaps(recs + drain(c)) if x["stream_key"] == "depth|BTCUSDT"]
            self.assertEqual(len(g), 1); self.assertEqual(g[0]["cause"], "sampler_stall")
            missing = set(range(g[0]["first_missing_ms"], g[0]["last_missing_ms"] + 1, 1000))
            accounted = set(got) | missing
            self.assertEqual(accounted, set(range(S, S + 30_001, 1000)))     # every boundary: record XOR gap
            self.assertFalse(set(got) & missing)

    def test_depth_jitter_1039ms_no_gap(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 200_000
            t, u = S - 990, 0
            for s in range(S, S + 120_000, 1000):
                while t <= s:
                    u += 1; depth(c, u, t); mini(c, t)
                    t += 1039 if (u % 3 == 0) else 971                  # measured G2 range 971..1039 ms
                c.sample(s)
            self.assertFalse(gaps(drain(c)))


# ------------------------------------------------------------------------------------------------ state machine
class StateMachine(unittest.TestCase):
    def test_first_observation_absent_never_ready(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 100_000; c.ws_start_ms = S - 1
            for k in range(0, 60):
                depth(c, k + 1, S + k * 1000 - 5); mini(c, S + k * 1000 - 5); book(c, k + 1, S + k * 1000 - 5)
                c.sample(S + k * 1000)
            c.watchdog_once()
            recs = drain(c)
            self.assertTrue([x for x in lifes(recs, "never_ready") if x["stream"] == EDEPTH])
            self.assertEqual(c.stream_state[EDEPTH]["state"], "FAILED")
            depth(c, 1, S + 60_500, sym="ethusdt"); c.sample_until(S + 61_000)
            g = [x for x in gaps(drain(c)) if x["stream_key"] == "depth|ETHUSDT"][0]
            self.assertEqual(g["cause"], "never_ready")
            self.assertEqual(g["first_missing_ms"], S + 30_000)            # first boundary >= ws_start + 30 s
            self.assertEqual(g["last_missing_ms"], S + 60_000)

    def test_never_observed_within_deadline_is_silent_startup(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000; c.ws_start_ms = S
            for k in range(1, 20):
                c.sample(S + k * 1000 - 30_000)
            self.assertFalse(gaps(drain(c)))
            self.assertEqual(c.stream_state[BOOK]["state"], "NOT_YET_OBSERVING")


# ------------------------------------------------------------------------------------------------ liveness (F40/F49)
class Liveness(unittest.TestCase):
    def test_ping_alive_data_stale(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 100_000
            book(c, 1, S - 10); mini(c, S - 10); c.sample(S)
            for k in range(1, 16):                    # socket "connected" (pings would be answered) but NO data
                c.sample(S + k * 1000)
            book(c, 2, S + 15_500); c.sample(S + 16_000)
            g = [x for x in gaps(drain(c)) if x["stream_key"] == "book|BTCUSDT"][0]
            self.assertEqual(g["cause"], "conn_data_stale")
            self.assertEqual(g["first_missing_ms"], S + 10_000)            # last data S-10: not in [S, S+10 s]
            self.assertEqual(g["last_missing_ms"], S + 15_000)

    def test_health_not_healthy_when_socket_up_but_data_stale(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                self.assertEqual(c.health_eval()[0], "HEALTHY", c.health_eval())
                c.activity["conn0-book"].first_in_sec.clear()          # no data messages for > 10 s
                st, hard, _, _ = c.health_eval()
                self.assertEqual(st, "DEGRADED"); self.assertIn("conn_not_data_live:conn0-book", hard)
            finally:
                stop_writer(c)

    def test_tier0_book_silent_120s_gap(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 300_000
            book(c, 1, S - 10)
            for k in range(0, 126):
                mini(c, S + k * 1000 - 5); c.sample(S + k * 1000)
            book(c, 2, S + 126_000 - 50); mini(c, S + 126_000 - 5); c.sample(S + 126_000)
            recs = drain(c)
            g = [x for x in gaps(recs) if x["stream_key"] == "book|BTCUSDT"][0]
            self.assertEqual(g["cause"], "stale_stream")
            self.assertEqual(g["first_missing_ms"], S + 120_000)          # age 120 010 ms > 120 000
            self.assertEqual(g["last_missing_ms"], S + 125_000)
            bt = [r for r in recs if r["type"] == "book"]
            self.assertEqual(len(bt), 120 + 1)

    def test_tier1_low_rate_book_300s_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {**C.DEFAULTS}
            uni = {**U.tier0_only(cfg), "tier1": ["ADAUSDT"]}
            c = mk(d, universe=uni); S = (A.now_ms() // 60_000) * 60_000 - 600_000
            book(c, 1, S - 10, sym="adausdt")
            for k in range(0, 301):
                mini(c, S + k * 1000 - 5); c.sample(S + k * 1000)
            recs = drain(c)
            bt = [r for r in recs if r["type"] == "book" and r["symbol"] == "ADAUSDT"]
            self.assertEqual(len(bt), 31); self.assertTrue(all(r["unchanged"] for r in bt[1:]))
            self.assertFalse([x for x in gaps(recs) if x["stream_key"] == "book|ADAUSDT"])

    def test_market_stale_gap(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d, cadence_ms={**C.DEFAULTS["cadence_ms"], "market": 2000}); S = (A.now_ms() // 2000) * 2000 - 100_000
            for k in range(0, 10):
                mini(c, S + k * 1000 - 5); book(c, k + 1, S + k * 1000 - 5); c.sample(S + k * 1000)
            for k in range(10, 30):                     # miniTicker silent 20 s; book traffic keeps conn0 data-live
                book(c, k + 1, S + k * 1000 - 5); c.sample(S + k * 1000)
            mini(c, S + 30_000 - 5); c.sample(S + 30_000)
            g = [x for x in gaps(drain(c)) if x["stream_key"] == "market|ALL"][0]
            self.assertEqual(g["cause"], "stale_stream")
            self.assertEqual(g["first_missing_ms"], S + 20_000)            # newest component S+9 s, age > 10 s
            self.assertEqual(g["last_missing_ms"], S + 28_000)

    def test_market_component_24h_drop(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d, cadence_ms={**C.DEFAULTS["cadence_ms"], "market": 2000}); S = (A.now_ms() // 2000) * 2000 - 10_000
            c.on_message(None, {"stream": "!miniTicker@arr", "data": [{"s": "OLDUSDT", "E": 1}]}, (S - 90_000_000) * 10**6)
            mini(c, S - 100); book(c, 1, S - 100)
            c.sample(S)
            m = [r for r in drain(c) if r["type"] == "market"][0]
            self.assertNotIn("OLDUSDT", m["component_recv_ms"]); self.assertEqual(c.stats["market_component_expired"], 1)


# ------------------------------------------------------------------------------------------------ subscription (F22/F37/F39)
class Subscription(unittest.TestCase):
    def test_subscribe_no_ack_timeout(self):
        async def go(d):
            c = mk(d); m = A.now_ms()
            conn = c.conns[0]
            conn.sub_requests = {1: {"streams": [EBOOK, "!miniTicker@arr"], "sent_ms": m - 11_000, "resolved": False}}
            c.on_sub_sent(conn, 1, [EBOOK, "!miniTicker@arr"], m - 11_000)
            c.watchdog_once(); await asyncio.sleep(0.01)
            return c, conn
        with tempfile.TemporaryDirectory() as d:
            c, conn = asyncio.run(go(d))
            recs = drain(c)
            self.assertTrue(lifes(recs, "subscribe_timeout"))
            self.assertEqual(c.stream_state[EBOOK]["state"], "FAILED"); self.assertEqual(conn.forced, 1)

    def test_subscribe_error_degrades_health(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                got = capture(c)
                conn = c.conns[1]
                conn.sub_requests = {1: {"streams": [EDEPTH], "sent_ms": A.now_ms(), "resolved": False}}
                c.on_subscribe_result(conn, {"error": {"code": 2, "msg": "Invalid request"}, "id": 1})
                st, hard, _, _ = c.health_eval()
                self.assertEqual(st, "DEGRADED"); self.assertTrue(any(h.startswith(f"stream_failed:{EDEPTH}") for h in hard))
                self.assertTrue(lifes(got, "subscribe_failed"))
            finally:
                stop_writer(c)

    def test_partial_subscription_not_healthy(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                c.tracks[EDEPTH].sub = "SENT"                      # ack never arrived; data does
                st, hard, _, _ = c.health_eval()
                self.assertEqual(st, "DEGRADED"); self.assertTrue(any(h.startswith("not_acked:") for h in hard))
            finally:
                stop_writer(c)

    def test_wsconnection_routes_ack_and_error(self):
        from tests.test_collector import FakeWS, textmsg
        got, msgs = [], []
        async def go():
            ws = FakeWS([textmsg({"result": None, "id": 1}), textmsg({"error": {"code": 2}, "id": 2}),
                         textmsg({"stream": BOOK, "data": {"u": 1}})])
            c = T.WSConnection("c0", [BOOK, EBOOK], mock.Mock(ws_connect=lambda url, **kw: ws),
                               lambda cn, o, r: msgs.append(o), lambda *a: None, lambda *a: None,
                               on_sub_result=lambda cn, o: got.append(o))
            c.backoff.next_delay = lambda: 5.0
            t = asyncio.create_task(c.run()); await asyncio.sleep(0.7); await c.close(); t.cancel()
            return c
        c = asyncio.run(go())
        self.assertEqual([g["id"] for g in got], [1, 2]); self.assertEqual(len(msgs), 1)
        self.assertEqual(c.sub_requests[1]["streams"], [EBOOK])


# ------------------------------------------------------------------------------------------------ failures (F20/F21/F23/F43/F51)
class Failures(unittest.TestCase):
    def test_handler_exception_visible_in_health(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                got = capture(c)
                c.on_handler_error(c.conns[0], KeyError("x"))
                st, hard, _, _ = c.health_eval()
                self.assertEqual(st, "DEGRADED"); self.assertIn("handler_exceptions_10min", hard)
                self.assertTrue(lifes(got, "handler_exception"))
            finally:
                stop_writer(c)

    def test_required_task_crash_supervised(self):
        async def go(d):
            c = mk(d); c.task_restart_delay_s = 0.01
            calls = {"n": 0}
            async def boom():
                calls["n"] += 1; c.beats["disk"] = time.monotonic(); raise RuntimeError("disk task crashed")
            await asyncio.wait_for(c.supervise("disk", boom), timeout=5)
            return c, calls["n"]
        with tempfile.TemporaryDirectory() as d:
            c, n = asyncio.run(go(d))
            recs = drain(c)
            self.assertEqual(n, 6)                                   # restarted after each failure until > 5
            self.assertEqual(len(lifes(recs, "task_failed")), 6)
            self.assertEqual(c.exit_code, A.EXIT_TASK); self.assertTrue(c.stop_event.is_set())
            self.assertEqual(c.state, "FAILED"); self.assertTrue(glob.glob(os.path.join(d, "control", "fatal-*.json")))

    def test_task_exiting_unexpectedly_is_a_failure(self):
        async def go(d):
            c = mk(d); c.task_restart_delay_s = 0.01
            async def quiet():
                return None
            t = asyncio.create_task(c.supervise("clock", quiet)); await asyncio.sleep(0.05); c.stop_event.set()
            await asyncio.wait_for(t, 2)
            return c
        with tempfile.TemporaryDirectory() as d:
            c = asyncio.run(go(d))
            self.assertTrue([x for x in lifes(drain(c), "task_failed") if x["error"] == "exited_unexpectedly"])

    def test_writer_thread_death_detected(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d, flush_interval_s=0.02)
            import threading
            with mock.patch.object(c.writer, "_sync_all", side_effect=RuntimeError("boom")), \
                    mock.patch.object(threading, "excepthook", lambda a: None):
                c.writer.start(); c.writer.join(5)
            self.assertFalse(c.writer.is_alive()); self.assertIn("RuntimeError", c.writer.fatal)
            c.ws_start_ms = A.now_ms(); c.state = "RUNNING"
            with contextlib.redirect_stderr(io.StringIO()):
                c.watchdog_once()
            self.assertEqual(c.exit_code, A.EXIT_WRITER); self.assertEqual(c.health()["state"], "FAILED")
            self.assertTrue(glob.glob(os.path.join(d, "control", "fatal-*.json")))

    def test_writer_bad_record_rejected_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d, flush_interval_s=0.05); c.writer.start()
            r = R.make(type="lifecycle", obs_id="life|x|1|e", symbol=None, payload={"bad": {1, 2}}, boot_id="x",
                       endpoint="collector", transport="internal", recv_ts_ns=time.time_ns())
            c.q.put(r); time.sleep(0.3)
            self.assertTrue(c.writer.is_alive()); self.assertEqual(c.stats["writer_rejected"]["TypeError"], 1)
            stop_writer(c)

    def test_stopped_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(c.finalize_stop(), "STOPPED_INCOMPLETE")        # writer never finished
            self.assertEqual(c.exit_code, A.EXIT_INCOMPLETE)
            c2 = mk(d, flush_interval_s=0.02); c2.writer.start(); c2.writer.stop(); c2.writer.join(5)
            self.assertEqual(c2.finalize_stop(), "STOPPED")
            c3 = mk(d, flush_interval_s=0.02); c3.writer.start(); c3.writer.stop(); c3.writer.join(5)
            p = pathlib.Path(d, "raw", "book", "x.jsonl.gz.partial"); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(c3.finalize_stop(), "STOPPED_INCOMPLETE")

    def test_http_418_closes_all_ws(self):
        class SlowWS:
            def __init__(self): self.closed = False
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def send_str(self, s): pass
            async def close(self): self.closed = True
            def __aiter__(self): return self
            async def __anext__(self):
                while not self.closed:
                    await asyncio.sleep(0.01)
                raise StopAsyncIteration
        class Resp:
            status, headers = 418, {"Retry-After": "60"}
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def read(self): return b"{}"
        async def go(d):
            c = mk(d)
            sockets, calls = [], {"n": 0}
            def connect(url, **kw):
                calls["n"] += 1; w = SlowWS(); sockets.append(w); return w
            c.session = mock.Mock(ws_connect=connect, get=lambda *a, **k: Resp())
            c.conns = []; c.state = "RUNNING"
            await c.start_ws(); await asyncio.sleep(1.2)
            before = calls["n"]
            rest = T.RestClient(c.session, c.rate, c.stats)
            status = (await rest.get("/api/v3/time"))[0]
            await asyncio.sleep(0.3)
            closed = all(w.closed for w in sockets)
            after = calls["n"]
            st = c.health_eval()[0]
            for x in c.conns:
                await x.close()
            for x in c.conns:
                x.task.cancel()
            return status, closed, before, after, st, c
        with tempfile.TemporaryDirectory() as d:
            status, closed, before, after, st, c = asyncio.run(go(d))
            self.assertEqual(status, 418); self.assertTrue(closed)
            self.assertEqual(before, 2); self.assertEqual(after, 2)       # no reconnect while banned
            self.assertEqual(st, "BANNED_418")
            self.assertTrue(lifes(drain(c), "binance_ban_418"))
            S = (A.now_ms() // 1000) * 1000
            c.tracks[BOOK].values.push((S * 10**6 - 5, {"u": 1}, 1)); c.tracks[BOOK].ready_ms = S - 1
            c.ban_since_ms = S - 1000
            c.sample(S)
            self.assertEqual(c.tracks[BOOK].gap["cause"], "banned_418")


# ------------------------------------------------------------------------------------------------ identities (F55)
class Identities(unittest.TestCase):
    def test_multiple_gap_ids_unique_and_all_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d, flush_interval_s=0.05)
            S = (A.now_ms() // 1000) * 1000 - 100_000
            depth(c, 1, S - 10); mini(c, S - 10); c.sample(S)
            for start in (S + 10_000, S + 30_000, S + 50_000):           # three stale gaps, same stream + cause
                for k in range(start - 9000, start + 5000, 1000):
                    mini(c, k - 5)
                    if k < start - 2000 or k >= start + 4000:
                        depth(c, 1, k - 5)
                    c.sample(k)
            for _ in range(2):                                           # two identical candle failures
                c.simple_gap("candle|15m|BTCUSDT", S, S, 900_000, "candle_fetch_failed:500", A.RECOVERABLE)
            recs = drain(c)
            g = [r for r in recs if r["type"] == "gap"]
            self.assertGreaterEqual(len(g), 5)
            self.assertEqual(len({r["obs_id"] for r in g}), len(g))
            for r in recs:
                c.q.put(r)
            c.writer.start(); time.sleep(0.4); stop_writer(c)
            self.assertEqual(c.stats["written"]["gap"], len(g)); self.assertEqual(c.stats["duplicates_dropped"], 0)

    def test_lifecycle_same_event_same_ms_unique(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d)
            with mock.patch.object(A.time, "time_ns", return_value=time.time_ns()):
                for _ in range(3):
                    c.lifecycle("subscribe_failed", {"x": 1})
            ids = [r["obs_id"] for r in drain(c)]
            self.assertEqual(len(set(ids)), 3)


# ------------------------------------------------------------------------------------------------ health (F9/F28/F36/F48/F50/F54, R02)
def healthy_collector(d, **over):
    """A collector in RUNNING state with every invariant satisfied, using real-time synthetic data."""
    c = mk(d, flush_interval_s=0.05, **over)
    c.writer.start()
    if hasattr(c.writer.certifier, "wait_ready"):                    # G3-F4: HEALTHY requires REAL certifier readiness;
        assert c.writer.certifier.wait_ready(20), "certifier not ready"   # cold image imports can take > 1 s
    m = A.now_ms()
    c.state = "RUNNING"; c.ws_start_ms = m - 60_000; c.started_mono = time.monotonic() - 120
    for n in A.TASK_PERIOD_S:
        c.beats[n] = time.monotonic()
    c.clock.update_samples([(m, m - 10, m + 10)])
    for conn in c.conns:
        c.activity[conn.name].transitions.append((m - 59_000, True))
    for t in c.all_tracks():
        t.sub = "ACKED"
    for sym in ("btcusdt", "ethusdt"):
        book(c, 1, m - 100, sym); depth(c, 1, m - 100, sym)
    mini(c, m - 100)
    time.sleep(0.15)
    return c


def stop_writer(c):
    c.writer.stop(); c.writer.join(5)


def capture(c):
    """Records emitted by a collector whose writer thread is running (the writer drains c.q concurrently)."""
    got = []
    orig = c.enq.put
    def put(rec, prio):
        got.append(rec); return orig(rec, prio)
    c.enq.put = put
    return got


class Health(unittest.TestCase):
    def test_health_invariant_healthy_and_starting(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                st, hard, startup, warn = c.health_eval()
                self.assertEqual((st, hard, startup), ("HEALTHY", [], []))
            finally:
                stop_writer(c)
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); c.state = "RUNNING"; c.ws_start_ms = A.now_ms(); c.writer.start()
            try:
                st, hard, startup, _ = c.health_eval()
                self.assertEqual(st, "STARTING", (hard, startup)); self.assertFalse(hard)      # F9: not DEGRADED
            finally:
                stop_writer(c)

    def test_health_invariant_task_beats(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                c.beats["sampler"] = time.monotonic() - 10
                st, hard, _, _ = c.health_eval()
                self.assertEqual(st, "DEGRADED"); self.assertIn("task_stale:sampler", hard)
            finally:
                stop_writer(c)

    def test_clock_stale_degrades(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                c.clock.last_ok_mono = time.monotonic() - 1300
                self.assertIn("clock_stale", c.health_eval()[1])
            finally:
                stop_writer(c)

    def test_health_age_from_observation(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                m = A.now_ms()
                c.tracks[EBOOK].values.push(((m - 5000) * 10**6, {"u": 9}, 9))
                h = c.health()
                self.assertGreaterEqual(h["streams"][EBOOK]["last_msg_age_ms"], 5000)
            finally:
                stop_writer(c)

    def test_metrics_present(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                h = c.health()
                self.assertIn("msgs_per_s", h["ws"][0]); self.assertIn("max_60s", h["loop_lag_ms"])
                self.assertIn("catchup_boundaries", h)
            finally:
                stop_writer(c)

    def test_historical_health_records(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                got = capture(c)
                c.write_health(); c.write_health()
                hs = [r for r in got if r["type"] == "health"]
                self.assertEqual(len(hs), 1)                         # second call within 60 s: no new record
                self.assertEqual(hs[0]["payload"]["state"], "HEALTHY")
                c.beats["sampler"] = time.monotonic() - 10; c.write_health()      # state change => record
                hs = [r for r in got if r["type"] == "health"]
                self.assertEqual(len(hs), 2); self.assertEqual(hs[1]["payload"]["state"], "DEGRADED")
                self.assertIn("task_stale:sampler", hs[1]["payload"]["reasons"])
            finally:
                stop_writer(c)

    def test_unknown_stream_counted_and_warned(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d)
            try:
                c.on_message(None, {"stream": "xyzusdt@bookTicker", "data": {"u": 1}}, time.time_ns())
                c.on_message(None, {"e": "somethingNew"}, time.time_ns())
                _, _, _, warn = c.health_eval()
                self.assertIn("unknown_stream:1", warn); self.assertIn("unknown_event:1", warn)
            finally:
                stop_writer(c)


# ------------------------------------------------------------------------------------------------ clock (F5/R17)
class Clock(unittest.TestCase):
    def test_clock_uncertainty_not_skew(self):
        from p2_forward.guards import ClockGuard
        c = ClockGuard(500, 2000)
        c.update_samples([(10_900, 10_000, 11_000), (11_950, 11_000, 12_100)])   # stamp late in a 1 s round trip
        self.assertEqual(c.state, "OK"); self.assertAlmostEqual(c.uncertainty_ms, 500.0)
        c.update_samples([(13_200, 10_000, 10_200)])                              # |skew| 3100 - 100 => CRITICAL
        self.assertEqual(c.state, "CRITICAL")

    def test_clock_payload_method(self):
        class Rest:
            weight_used_total = 0
            async def get(self, path, params=None, urgent=False):
                t0 = time.time() * 1000; t1 = t0 + 20
                return 200, {"serverTime": int(t0 + 10)}, time.time_ns(), t0, t1
        async def go(d):
            c = mk(d); c.rest = Rest(); c.cfg["clock_probes"] = 3
            with mock.patch.object(A.Collector, "_sleep", new=lambda self, s: asyncio.sleep(0)):
                t = asyncio.create_task(c.clock_task()); await asyncio.sleep(0.05); c.stop_event.set(); await t
            return c
        with tempfile.TemporaryDirectory() as d:
            c = asyncio.run(go(d))
            ck = [r for r in drain(c) if r["type"] == "clock"][0]["payload"]
            self.assertEqual(ck["method"], "min_rtt_of_3_midpoint_v1"); self.assertEqual(len(ck["probes"]), 3)
            self.assertAlmostEqual(ck["uncertainty_ms"], 10.0, places=3)


# ------------------------------------------------------------------------------------------------ R01/R03/R06/R09/R16, F6, F7
class Research(unittest.TestCase):
    def test_provenance_run_record_complete(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"P2F_GIT_COMMIT": "abc123",
                                                                                "P2F_IMAGE_TAG": "tsb-p2-forward:test",
                                                                                "P2F_BUILD_TIME": "2026-10-02T00:00:00Z",
                                                                                "P2F_IMAGE_ID": "sha256:feed"}):
            c = mk(d)
            rec, rel, sha = P.write_run_record(c)
            path = os.path.join(d, rel)
            self.assertFalse(os.stat(path).st_mode & 0o222)
            self.assertEqual(Wm.sha256_file(path), sha)
            self.assertEqual(rec["build"]["git_commit"], "abc123"); self.assertEqual(rec["build"]["image_id_runtime_claim"], "sha256:feed")
            for k in ("code", "runtime", "config", "semantics", "sampling_profile", "universe", "endpoints",
                      "expected_streams", "schema_doc", "host_label"):
                self.assertIn(k, rec)
            self.assertIn("app.py", rec["code"]["files"]); self.assertEqual(rec["semantics"]["clock_method"], C.CLOCK_METHOD)
            self.assertEqual({e["stream"] for e in rec["expected_streams"]}, {BOOK, DEPTH, EBOOK, EDEPTH, "!miniTicker@arr"})
            self.assertEqual([e["depth_levels"] for e in rec["expected_streams"] if e["kind"] == "depth"], [20, 20])

    def test_schema_doc_installed(self):
        with tempfile.TemporaryDirectory() as d:
            info = P.install_schema_doc(d)
            p = os.path.join(d, info["file"])
            self.assertFalse(os.stat(p).st_mode & 0o222); self.assertEqual(Wm.sha256_file(p), info["sha256"])
            self.assertEqual(P.install_schema_doc(d), info)                     # idempotent
            os.chmod(p, 0o644); open(p, "a").write("tamper"); os.chmod(p, 0o444)
            with self.assertRaises(RuntimeError):
                P.install_schema_doc(d)

    def test_depth_levels_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000 - 5000
            depth(c, 1, S - 10); c.sample(S)
            r = [x for x in drain(c) if x["type"] == "depth"][0]
            self.assertEqual(r["depth_levels"], 20)
            bad = dict(r); bad.pop("depth_levels")
            self.assertIn("depth_levels_missing", R.validate(bad))

    def test_disk_stop_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d, flush_interval_s=0.05); c.writer.start()
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                c.disk_hard_stop()
            self.assertIn("disk_hard_stop", err.getvalue())
            markers = glob.glob(os.path.join(d, "control", "disk_stop-*.json"))
            self.assertEqual(len(markers), 1); self.assertFalse(os.stat(markers[0]).st_mode & 0o222)
            S = (A.now_ms() // 1000) * 1000 - 5000
            book(c, 1, S - 10); mini(c, S - 10); c.sample(S); c.sample(S + 1000)
            c.write_health(record=True)
            book(c, 2, S + 1500); mini(c, S + 1500)
            g = c.tracks[BOOK].close_gap(); c.gap_record(g, A.IRREPLACEABLE)
            time.sleep(0.3); stop_writer(c)
            w = c.stats["written"]
            self.assertEqual(w.get("book", 0), 0); self.assertGreaterEqual(w["lifecycle"], 1)
            self.assertEqual(w["health"], 1); self.assertEqual(w["gap"], 1)
            self.assertEqual(g["cause"], "disk_hard_stop")

    def test_idle_segment_no_idx_lines(self):
        with tempfile.TemporaryDirectory() as d:
            st = Wm.new_stats(); q = queue.Queue(); w = Wm.SegmentWriter(d, "f" * 32, q, st, flush_interval_s=0.05)
            mk_rec = lambda t, i: R.make(type=t, obs_id=f"{t}-{i}", symbol=None, payload={}, boot_id="f" * 32,
                                         endpoint="collector", transport="internal", recv_ts_ns=time.time_ns())
            q.put(mk_rec("lifecycle", 0)); w.start()
            for i in range(20):
                q.put(mk_rec("health", i)); time.sleep(0.03)
            time.sleep(0.2)
            life_idx = glob.glob(os.path.join(d, "raw", "lifecycle", "*", "*.idx.partial"))[0]
            lines_open = len(open(life_idx).read().splitlines())
            w.stop(); w.join(5)
            self.assertEqual(lines_open, 1)                          # idle segment: no new index lines (R16)
            hidx = glob.glob(os.path.join(d, "raw", "health", "*", "*.idx"))[0]
            self.assertGreater(len(open(hidx).read().splitlines()), 3)
            for p in glob.glob(os.path.join(d, "raw", "*", "*", "*.idx")):
                recs = sum(json.loads(l)["records"] for l in open(p))
                seg = p[:-4] + ".jsonl.gz"
                self.assertEqual(recs, len(gzip.open(seg, "rt").read().splitlines()))

    def test_rotation_idempotent(self):
        async def go(d):
            c = mk(d); c.rotating.add("conn0-book")
            c.on_shutdown_event(c.conns[0], {"stream": "!serverShutdown"}, time.time_ns())
            return c
        with tempfile.TemporaryDirectory() as d:
            c = asyncio.run(go(d))
            self.assertFalse(c.aux_tasks)
            self.assertTrue(lifes(drain(c), "server_shutdown_event")[0]["already_rotating"])

    def test_candle_tasks_tracked_and_cancelled(self):
        class SlowRest:
            weight_used_total = 0
            async def get(self, *a, **k):
                await asyncio.sleep(30); return "network_error", None, None, None, None
        async def go(d):
            c = mk(d, candle_timeframes=["15m", "1h"]); c.rest = SlowRest()
            with mock.patch.object(A.Collector, "_sleep", new=lambda self, s: asyncio.sleep(0)):
                t = asyncio.create_task(c.candle_task()); await asyncio.sleep(0.05)
                n = len(c.candle_tasks)
                c.stop_event.set(); t.cancel()
                for x in list(c.candle_tasks):
                    x.cancel()
                await asyncio.gather(t, *c.candle_tasks, return_exceptions=True)
            return n, c
        with tempfile.TemporaryDirectory() as d:
            n, c = asyncio.run(go(d))
            self.assertGreater(n, 0); self.assertFalse(c.candle_tasks)


if __name__ == "__main__":
    unittest.main()
