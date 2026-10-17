"""P2-E1 G0 tests (stdlib unittest; synthetic fixtures / scratch dirs only; no network)."""
import asyncio
import collections
import gzip
import json
import os
import pathlib
import queue
import re
import tempfile
import time
import unittest
from unittest import mock

from p2_forward import config as C, record as R, writer as Wm, guards as G, universe as U, transport as T, app as A, verify as V
from p2_forward.derivs import DerivativesCollector, DerivativesDisabled

PKG = pathlib.Path(__file__).resolve().parents[1] / "p2_forward"


def rec(i=1, typ="book", sym="BTCUSDT", ex=None, recv=None, sample=None):
    recv = recv or time.time_ns()
    sample = sample if sample is not None else recv // 1_000_000 + 1
    return R.make(type=typ, obs_id=R.book_id(sym, i, 1000, sample), symbol=sym, payload={"u": i, "b": "1", "a": "2"},
                  boot_id="b" * 32, endpoint="btcusdt@bookTicker", transport="ws", recv_ts_ns=recv, exchange_seq=i,
                  exchange_event_time_ms=ex, tier=0, cadence_ms=1000, sample_ms=sample)


def run_writer(d, recs, boot="a" * 32):
    st = Wm.new_stats(); q = queue.Queue()
    w = Wm.SegmentWriter(d, boot, q, st, flush_interval_s=0.05)
    for r in recs: q.put(r)
    w.start(); time.sleep(0.3); w.stop(); w.join(10)
    return st


class Schema(unittest.TestCase):
    def test_valid_and_missing_field(self):
        r = rec(); self.assertEqual(R.validate(r), [])
        bad = dict(r); bad.pop("obs_id"); self.assertIn("missing:obs_id", R.validate(bad))
        self.assertEqual(R.validate("x"), ["not_object"])

    def test_deterministic_ids(self):
        self.assertEqual(R.candle_id("BTCUSDT", "15m", 1), "BTCUSDT|15m|1")
        self.assertEqual(R.book_id("X", 5, 1000, 7), R.book_id("X", 5, 1000, 7))
        self.assertNotEqual(R.book_id("X", 5, 1000, 7), R.book_id("X", 5, 1000, 8))
        self.assertEqual(R.depth_id(10, "X", 9, 5000, 10000), "dp10|X|9|c5000|t10000")

    def test_missing_exchange_time_is_null_and_never_synthesized(self):
        r = rec(); self.assertIsNone(r["exchange_event_time_ms"])
        self.assertIn("book_depth_have_no_exchange_time", R.validate(rec(ex=r["recv_ts_ns"] // 1_000_000)))

    def test_future_timestamp_rejected(self):
        # G2-Repeat: clock records are exempt (serverTime ahead of the host IS the measurement, review m6);
        # the generic future-time rejection is exercised on a non-clock record.
        r = rec(typ="lifecycle"); r["exchange_event_time_ms"] = r["observed_at_ms"] + 60_000
        self.assertIn("exchange_time_in_future", R.validate(r))
        r2 = rec(); r2["recv_ts_ns"] = time.time_ns() + 10 * 10**9
        self.assertIn("recv_in_future", R.validate(r2))


class Writer(unittest.TestCase):
    def test_promotion_checksum_readonly_manifest_and_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            r1, r2 = rec(1), rec(2)
            st = run_writer(d, [r1, r2, dict(r1)])
            self.assertEqual(st["duplicates_dropped"], 1)
            v = V.verify(d)
            self.assertTrue(v["PASS"], v); self.assertEqual(v["records"], 2)
            seg = next(pathlib.Path(d, "raw").rglob("*.jsonl.gz"))
            self.assertFalse(os.stat(seg).st_mode & 0o222)
            self.assertTrue(pathlib.Path(str(seg) + ".sha256").exists())
            blks = [json.loads(l)["blk"] for l in gzip.open(seg, "rt")]
            self.assertEqual(blks, sorted(blks))                          # ordering preserved

    def test_disk_hard_stop_drops_and_counts(self):
        with tempfile.TemporaryDirectory() as d:
            st = Wm.new_stats(); q = queue.Queue(); w = Wm.SegmentWriter(d, "c" * 32, q, st, 0.05)
            w.stop_writes.set(); q.put(rec(1)); w.start(); time.sleep(0.2); w.stop(); w.join(5)
            self.assertEqual(st["dropped"]["book"], 1); self.assertEqual(list(pathlib.Path(d, "raw").rglob("*.gz")), [])

    def test_write_failure_quarantines_not_certifies(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(Wm._Segment, "write", side_effect=OSError("EIO")):
            st = run_writer(d, [rec(1)])
            self.assertEqual(st["write_errors"], 1); self.assertEqual(st["segments_quarantined"], 1)
            self.assertEqual(list(pathlib.Path(d, "raw").rglob("*.jsonl.gz")), [])

    def test_partial_salvage_and_crash_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            st = Wm.new_stats()
            seg = Wm._Segment(d, "book", "20261002T10", "dddddddd", 1)
            for i in range(5): seg.write(rec(i + 1))
            seg.sync(); seg.gz.write(b'{"truncated"')                       # crash mid-line, no close
            seg.fh.flush(); seg.fh.close()
            self.assertEqual(len(Wm.salvage_partial(seg.partial)), 5)
            gaps = Wm.recover_partials(d, "e" * 32, st)
            self.assertEqual(gaps[0]["salvaged"], 5)
            self.assertTrue(any("recovered" in str(p) for p in pathlib.Path(d, "raw").rglob("*.jsonl.gz")))
            self.assertTrue(any(p.name.endswith(".orig") for p in pathlib.Path(d, "quarantine").iterdir()))
            self.assertTrue(V.verify(d)["PASS"])

    def test_checksum_mismatch_detected(self):
        with tempfile.TemporaryDirectory() as d:
            run_writer(d, [rec(1)])
            seg = next(pathlib.Path(d, "raw").rglob("*.jsonl.gz"))
            os.chmod(seg, 0o644); seg.write_bytes(gzip.compress(b"{}\n")); os.chmod(seg, 0o444)
            v = V.verify(d); self.assertFalse(v["PASS"]); self.assertTrue(v["checksum_mismatch"])

    def test_restart_distinct_segments_and_cross_boot_duplicates_visible(self):
        with tempfile.TemporaryDirectory() as d:
            r = rec(1); run_writer(d, [r], boot="1" * 32); run_writer(d, [dict(r)], boot="2" * 32)
            self.assertEqual(len(list(pathlib.Path(d, "raw").rglob("*.jsonl.gz"))), 2)
            self.assertEqual(V.verify(d)["duplicate_obs_ids"], 1)


class Guards(unittest.TestCase):
    def test_rate_budget_429_418(self):
        t = [0.0]; g = G.RateGuard(budget=10, clock=lambda: t[0])
        self.assertTrue(g.allow(8)[0]); self.assertEqual(g.allow(8), (False, "own_budget"))
        t[0] = 61; self.assertTrue(g.allow(8)[0])
        g.observe_header("2500"); self.assertEqual(g.allow(1), (False, "deferred_ip_weight")); self.assertTrue(g.allow(1, urgent=True)[0])
        g.observe_header("3700"); self.assertEqual(g.allow(1, urgent=True), (False, "paused_ip_weight"))
        g2 = G.RateGuard(clock=lambda: t[0]); g2.on_429("10"); self.assertEqual(g2.allow(1)[1], "rest_blocked")
        t[0] += 299; self.assertFalse(g2.allow(1)[0]); t[0] += 2; self.assertTrue(g2.allow(1)[0])
        g3 = G.RateGuard(clock=lambda: t[0]); g3.on_418("120"); self.assertTrue(g3.banned()); self.assertEqual(g3.allow(1)[1], "banned_418")

    def test_backoff_jitter_cap_and_cooldown(self):
        b = G.Backoff(clock=lambda: 0.0, rng=lambda: 0.5)
        for _ in range(3): b.failed()
        self.assertAlmostEqual(b.next_delay(), 8.0)
        for _ in range(2): b.failed()
        self.assertGreaterEqual(b.next_delay(), 900 * 0.7)
        b2 = G.Backoff(clock=lambda: 0.0, rng=lambda: 0.0)
        for _ in range(10): b2.attempt()
        self.assertGreaterEqual(b2.next_delay(), 299)

    def test_disk_states(self):
        g = G.DiskGuard(100, 60, 150)
        self.assertEqual(g.state(200e9, 1e9), "OK"); self.assertEqual(g.state(90e9, 1e9), "WARN")
        self.assertEqual(g.state(50e9, 1e9), "HARD_STOP"); self.assertEqual(g.state(200e9, 150e9), "HARD_STOP")

    def test_clock_skew(self):
        c = G.ClockGuard(500, 2000)
        self.assertEqual(c.update(1000, 990, 1010), "OK"); self.assertEqual(c.update(1700, 990, 1010), "WARN")
        self.assertEqual(c.update(5000, 990, 1010), "CRITICAL"); self.assertTrue(c.suspect())


class ConfigAndAuthority(unittest.TestCase):
    def test_config_boundaries(self):
        for bad in ({"derivatives_enabled": True}, {"aggtrades_enabled": True}, {"enabled": True, "max_runtime_s": 0},
                    {"enabled": True, "max_runtime_s": 9 * 3600}, {"rest_budget_weight_per_min": 301}):
            with self.assertRaises(C.ConfigError, msg=bad):
                C.validate({**C.DEFAULTS, **bad})
        with self.assertRaises(DerivativesDisabled):
            DerivativesCollector({"derivatives_enabled": True})

    def test_endpoint_allowlist(self):
        for url in ("https://api.binance.com/api/v3/klines", "https://data-api.binance.vision/api/v3/order",
                    "https://data-api.binance.vision/api/v3/account", "wss://stream.binance.com:9443/stream",
                    "https://fapi.binance.com/fapi/v1/premiumIndex", "https://api.telegram.org/bot/sendMessage"):
            with self.assertRaises(T.EndpointNotAllowed, msg=url):
                T._check_url(url)
        T._check_url("https://data-api.binance.vision/api/v3/klines"); T._check_url("wss://data-stream.binance.vision/stream?streams=x")

    def test_no_trading_authority_static(self):
        forbidden = [r"\.(post|put|delete|patch)\(\s*(url|self\.base|f?['\"]http)", r"method\s*=\s*['\"](POST|PUT|DELETE|PATCH)", r"api\.binance\.com", r"fapi\.", r"sapi", r"/api/v3/order",
                     r"/api/v3/account", r"listenKey", r"userDataStream", r"X-MBX-APIKEY", r"signature", r"api[_-]?key",
                     r"secret", r"asyncpg", r"psycopg", r"sqlalchemy", r"import binance", r"from binance", r"telegram",
                     r"docker\.sock", r"POSTGRES", r"DATABASE_URL", r"\.env\b", r"subprocess", r"os\.system"]
        hits = []
        for f in PKG.glob("*.py"):
            src = f.read_text()
            for pat in forbidden:
                for m in re.finditer(pat, src, flags=re.IGNORECASE):
                    line = src[:m.start()].count("\n") + 1
                    text = src.splitlines()[line - 1]
                    if "forbidden" in text or text.strip().startswith(("#", '"""')) or "No API key" in text or "not authorized" in text:
                        continue
                    hits.append(f"{f.name}:{line}:{pat}")
        self.assertEqual(hits, [])
        calls = set()
        for f in PKG.glob("*.py"):
            calls |= set(re.findall(r"session\.([a-zA-Z_]+)\(", f.read_text()))
        self.assertTrue(calls <= {"get", "ws_connect"}, calls)          # only GET + market WS anywhere
        self.assertEqual(set(C.ALLOWED_REST_PATHS), {"/api/v3/klines", "/api/v3/time", "/api/v3/exchangeInfo", "/api/v3/ticker/24hr"})
        self.assertEqual(C.ALLOWED_HOSTS, {"data-stream.binance.vision", "data-api.binance.vision"})


class Universe(unittest.TestCase):
    def test_tiers_deterministic_and_stablecoins_excluded(self):
        cfg = {**C.DEFAULTS, "tier2_top_volume": 2, "tier2_top_movers": 1}
        ei = {"symbols": [{"symbol": s, "status": "TRADING", "quoteAsset": "USDT", "baseAsset": s[:-4]} for s in
                          ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "USDCUSDT", "DOGEUSDT", "ADAUSDT")]}
        tk = [{"symbol": s, "quoteVolume": str(v), "openPrice": "1", "lastPrice": str(p)} for s, v, p in
              (("BTCUSDT", 9e9, 1), ("ETHUSDT", 8e9, 1), ("SOLUSDT", 5e8, 1.01), ("XRPUSDT", 4e8, 1.0), ("USDCUSDT", 9e9, 1),
               ("DOGEUSDT", 3e7, 1.5), ("ADAUSDT", 5e6, 2))]
        u1, u2 = U.compute(cfg, ei, tk), U.compute(cfg, ei, list(reversed(tk)))
        self.assertEqual(u1, u2); self.assertNotIn("USDCUSDT", u1["tier1"] + u1["tier2"])
        self.assertEqual(u1["tier2"], ["DOGEUSDT", "SOLUSDT", "XRPUSDT"]); self.assertNotIn("ADAUSDT", u1["tier1"] + u1["tier2"])
        u3 = U.compute(cfg, ei, tk, prior_tier1={"ADAUSDT"}); self.assertIn("ADAUSDT", u3["hysteresis_members"])


class _Conn:
    """Synthetic connected connection (G2-Repeat: sampling requires the stream's OWN connection to be up, F3/F40)."""
    def __init__(self, name, streams): self.name, self.streams, self.connected, self.reconnects = name, streams, True, 0


def mk_collector(d, **over):
    cfg = {**C.DEFAULTS, "data_dir": d, "enabled": True, "max_runtime_s": 60, **over}
    c = A.Collector(cfg); c.universe = U.tier0_only(cfg); c.build_streams(); c.started_ms = A.now_ms()
    c.conns = [_Conn(n, s) for n, s in c._conn_streams()]
    return c


class Sampling(unittest.TestCase):
    def test_pit_sample_ignores_post_boundary_message_and_unchanged_flag(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk_collector(d); t = (A.now_ms() // 1000) * 1000
            c.on_message(None, {"stream": "btcusdt@bookTicker", "data": {"u": 1, "s": "BTCUSDT"}}, (t - 100) * 10**6)
            c.on_message(None, {"stream": "btcusdt@bookTicker", "data": {"u": 2, "s": "BTCUSDT"}}, (t + 5) * 10**6)
            c.sample(t)
            got = [c.q.get_nowait() for _ in range(c.q.qsize())]
            bt = [r for r in got if r["type"] == "book"][0]
            self.assertEqual(bt["exchange_seq"], 1); self.assertLessEqual(bt["observed_at_ms"], t)
            c.sample(t + 1000); bt2 = [c.q.get_nowait() for _ in range(c.q.qsize())][0]
            self.assertEqual(bt2["exchange_seq"], 2)

    def test_malformed_and_sequence_regression(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk_collector(d); n = time.time_ns()
            c.on_message(None, None, n); c.on_message(None, {"stream": "btcusdt@bookTicker", "data": {"x": 1}}, n)
            c.on_message(None, {"stream": "btcusdt@bookTicker", "data": {"u": 5}}, n)
            c.on_message(None, {"stream": "btcusdt@bookTicker", "data": {"u": 4}}, n)
            self.assertEqual(c.stats["malformed"], 2); self.assertEqual(c.stats["rejected"]["seq_regression"], 1)

    def test_stale_stream_opens_and_closes_gap(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk_collector(d); t = (A.now_ms() // 1000) * 1000
            c.on_message(None, {"stream": "btcusdt@depth20", "data": {"lastUpdateId": 1, "bids": [], "asks": []}}, (t - 10_000) * 10**6)
            c.sample(t); self.assertEqual(c.stream_state["btcusdt@depth20"]["state"], "GAP_OPEN")
            c.on_message(None, {"stream": "btcusdt@depth20", "data": {"lastUpdateId": 2, "bids": [], "asks": []}}, (t + 500) * 10**6)
            c.sample(t + 1000); self.assertEqual(c.stream_state["btcusdt@depth20"]["state"], "OBSERVING")
            gaps = [r for r in [c.q.get_nowait() for _ in range(c.q.qsize())] if r["type"] == "gap"]
            self.assertEqual(gaps[0]["recoverability"], A.IRREPLACEABLE)

    def test_queue_overflow_and_shedding_priority(self):
        st = Wm.new_stats(); q = queue.Queue(maxsize=100); e = A.Enqueuer(q, 100, st)
        for _ in range(65): q.put_nowait(1)
        self.assertFalse(e.put(rec(typ="depth"), 3)); self.assertTrue(e.put(rec(), 0))
        for _ in range(15): q.put_nowait(1)
        self.assertFalse(e.put(rec(), 2)); self.assertTrue(e.put(rec(), 1))
        while q.qsize() < 96: q.put_nowait(1)
        self.assertFalse(e.put(rec(), 1)); self.assertTrue(e.put(rec(), 0))
        while not q.full(): q.put_nowait(1)
        self.assertFalse(e.put(rec(), 0))
        self.assertGreaterEqual(sum(st["dropped"].values()), 4)
        self.assertTrue(e.closed_drop_intervals(force=True))

    def test_clock_suspect_marking(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk_collector(d); c.clock.update(10_000, 0, 10)
            c.emit("book", rec(), tier=0); self.assertTrue(c.q.get_nowait()["clock_suspect"])


class FakeWS:
    def __init__(self, msgs): self.msgs, self.closed = list(msgs), False
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def send_str(self, s): pass
    async def close(self): self.closed = True
    def __aiter__(self): return self
    async def __anext__(self):
        if not self.msgs: raise StopAsyncIteration
        await asyncio.sleep(0)
        return self.msgs.pop(0)


def textmsg(obj):
    return mock.Mock(type=T.aiohttp.WSMsgType.TEXT, data=json.dumps(obj))


class Transport(unittest.TestCase):
    def test_reconnect_shutdown_event_and_rollover(self):
        async def go():
            seen, states, shut = [], [], []
            calls = {"n": 0}
            def connect(url, **kw):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise T.aiohttp.ClientConnectionError("boom")
                return FakeWS([textmsg({"stream": "btcusdt@bookTicker", "data": {"u": 1}}),
                               textmsg({"stream": "!serverShutdown", "data": {"e": "serverShutdown", "E": 1}})])
            sess = mock.Mock(ws_connect=connect)
            b = G.Backoff(rng=lambda: 0.0); b.next_delay = lambda: 0.0
            c = T.WSConnection("c0", ["btcusdt@bookTicker"], sess, lambda cn, o, r: seen.append(o),
                               lambda cn, o, r: shut.append(o), lambda cn, s: states.append(s), backoff=b)
            task = asyncio.create_task(c.run()); await asyncio.sleep(0.05); await c.close(); task.cancel()
            return seen, states, shut, c
        seen, states, shut, c = asyncio.run(go())
        self.assertIn("connect_failed", states); self.assertIn("connected", states)
        self.assertTrue(seen and shut); self.assertGreaterEqual(c.reconnects, 1)

    def test_rotation_overlap(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                c = mk_collector(d)
                c.session = mock.Mock(ws_connect=lambda url, **kw: FakeWS([textmsg({"stream": "btcusdt@bookTicker", "data": {"u": 9}})] * 1))
                old = T.WSConnection("conn0-book", ["btcusdt@bookTicker"], c.session, c.on_message, c.on_shutdown_event, c.on_state)
                c.conns = [old]
                ev = await c.rotate(old, "test")
                return ev, c, old
        ev, c, old = asyncio.run(go())
        self.assertTrue(ev["overlap_ok"]); self.assertIsNot(c.conns[0], old); self.assertTrue(old._closing)

    def test_rest_failure_circuit_429_418(self):
        class Resp:
            def __init__(self, status, headers=None, body=b"{}"): self.status, self.headers, self._b = status, headers or {}, body
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def read(self): return self._b
        async def go():
            st = Wm.new_stats(); g = G.RateGuard()
            def boom(*a, **k): raise T.aiohttp.ClientConnectionError("x")
            rc = T.RestClient(mock.Mock(get=boom), g, st)
            r = [ (await rc.get("/api/v3/klines"))[0] for _ in range(4)]   # /api/v3/time is breaker-exempt (M4)
            g2 = G.RateGuard(); rc2 = T.RestClient(mock.Mock(get=lambda *a, **k: Resp(429, {"Retry-After": "10"})), g2, st)
            a = (await rc2.get("/api/v3/time"))[0]; b = (await rc2.get("/api/v3/time"))[0]
            g3 = G.RateGuard(); rc3 = T.RestClient(mock.Mock(get=lambda *a, **k: Resp(418, {"Retry-After": "60"})), g3, st)
            c1 = (await rc3.get("/api/v3/time"))[0]; c2 = (await rc3.get("/api/v3/time"))[0]
            rc4 = T.RestClient(mock.Mock(get=lambda *a, **k: Resp(200, {"x-mbx-used-weight-1m": "12"}, b"not json")), G.RateGuard(), st)
            m = (await rc4.get("/api/v3/time"))[0]
            return r, a, b, c1, c2, g3, m, st
        r, a, b, c1, c2, g3, m, st = asyncio.run(go())
        self.assertEqual(r[:3], ["network_error"] * 3); self.assertEqual(r[3], "circuit_open")
        self.assertEqual((a, b), (429, "rest_blocked")); self.assertEqual((c1, c2), (418, "banned_418")); self.assertTrue(g3.banned())
        self.assertEqual(m, "malformed")


class Lifecycle(unittest.TestCase):
    def test_graceful_shutdown_promotes_everything(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk_collector(d); c.writer.start()
            c.lifecycle("start", {}); c.emit("book", rec(), tier=0)
            time.sleep(0.2); c.writer.stop(); c.writer.join(10)
            v = V.verify(d); self.assertTrue(v["PASS"]); self.assertEqual(v["leftover_partials"], [])
            self.assertEqual(v["by_type"].get("lifecycle"), 1)

    def test_disabled_mode_writes_health_only(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {**C.DEFAULTS, "data_dir": d, "health_interval_s": 0.05}
            async def go():
                t = asyncio.create_task(A.disabled_loop(cfg)); await asyncio.sleep(0.2); t.cancel()
            try:
                asyncio.run(go())
            except asyncio.CancelledError:
                pass
            h = json.load(open(os.path.join(d, "health", "collector_health.json")))
            self.assertEqual(h["state"], "DISABLED"); self.assertFalse(os.path.exists(os.path.join(d, "raw")))


if __name__ == "__main__":
    unittest.main()
