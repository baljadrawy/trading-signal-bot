"""P2F obs: ws_session_end classification (transport) and reconnect-flapping episodes (detector + app wiring).
Both features are off by default; nothing here changes reconnection behaviour or health thresholds."""
import asyncio
import json
import tempfile
import unittest
from unittest import mock

from p2_forward import config as C, transport as T, flapping as F, incidents as I
from tests.test_collector import mk_collector, textmsg

WS = T.aiohttp.WSMsgType
ALLOWED = {"conn", "gen", "connected", "duration_ms", "initiator", "kind", "close_code", "exc_type", "handshake_status"}


class FakeWS:
    def __init__(self, msgs, close_code=None, hang=False):
        self.msgs, self.close_code, self.hang, self.closed = list(msgs), close_code, hang, False
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def send_str(self, s): pass
    async def close(self): self.closed = True
    def __aiter__(self): return self
    async def __anext__(self):
        await asyncio.sleep(0)
        if self.msgs:
            return self.msgs.pop(0)
        if self.hang:
            await asyncio.sleep(3600)
        raise StopAsyncIteration


def run_session(connect, prep=None, cancel_after=None, cb_raises=False):
    async def go():
        ends = []
        def cb(conn, info):
            ends.append(info)
            if cb_raises:
                raise RuntimeError("observer failure")
        c = T.WSConnection("conn0-book", ["btcusdt@bookTicker"], mock.Mock(ws_connect=connect),
                           lambda *a: None, lambda *a: None, lambda *a: None, on_session_end=cb)
        if prep:
            prep(c)
        if cancel_after is None:
            res = await c._session_once()
        else:
            t = asyncio.create_task(c._session_once()); await asyncio.sleep(cancel_after); t.cancel()
            try:
                res = await t
            except asyncio.CancelledError:
                res = "cancelled"
        return res, ends
    return asyncio.run(go())


class SessionEndClassification(unittest.TestCase):
    def check(self, ends, **want):
        self.assertEqual(len(ends), 1)
        e = ends[0]
        self.assertTrue(set(e) <= ALLOWED, set(e) - ALLOWED)            # metadata only, no payload fields
        for k, v in want.items():
            self.assertEqual(e[k], v, (k, e))
        return e

    def test_remote_close_with_code(self):
        res, ends = run_session(lambda u, **k: FakeWS([textmsg({"stream": "x", "data": {"secret": 1}})], close_code=1008))
        self.assertEqual(res, ("ended", None))
        e = self.check(ends, kind="remote_close", close_code=1008, initiator="remote", connected=True)
        self.assertGreaterEqual(e["duration_ms"], 0)
        self.assertNotIn("secret", json.dumps(e))

    def test_missing_close_code(self):
        _, ends = run_session(lambda u, **k: FakeWS([], close_code=None))
        self.check(ends, kind="stream_ended", close_code=None, initiator="remote")

    def test_ping_timeout(self):
        err = mock.Mock(type=WS.ERROR, data=T.aiohttp.ServerTimeoutError("No PONG received after 15.0 seconds"))
        _, ends = run_session(lambda u, **k: FakeWS([err], close_code=1006))
        self.check(ends, kind="ping_timeout", exc_type="ServerTimeoutError", close_code=1006, initiator="remote")

    def test_other_transport_error_message(self):
        err = mock.Mock(type=WS.ERROR, data=ConnectionResetError("reset"))
        _, ends = run_session(lambda u, **k: FakeWS([err]))
        self.check(ends, kind="transport_error", exc_type="ConnectionResetError", initiator="unknown")

    def test_connect_transport_failure(self):
        def boom(u, **k): raise T.aiohttp.ClientConnectionError("down")
        res, ends = run_session(boom)
        self.assertEqual(res, ("ended", None))
        self.check(ends, kind="transport_failure", exc_type="ClientConnectionError", connected=False, duration_ms=None)

    def test_connect_timeout(self):
        def slow(u, **k): raise asyncio.TimeoutError()
        _, ends = run_session(slow)
        self.check(ends, kind="timeout", exc_type="TimeoutError", connected=False)

    def test_handshake_rejected_429(self):
        def rej(u, **k): raise T.aiohttp.WSServerHandshakeError(mock.Mock(real_url="u"), (), status=429)
        _, ends = run_session(rej)
        self.check(ends, kind="handshake_rejected", handshake_status=429, connected=False)

    def test_local_cancel_propagates_and_is_recorded(self):
        res, ends = run_session(lambda u, **k: FakeWS([], hang=True), cancel_after=0.05)
        self.assertEqual(res, "cancelled")
        self.check(ends, kind="local_cancel", initiator="local", connected=True)

    def test_local_end_is_not_reported_as_remote(self):
        _, ends = run_session(lambda u, **k: FakeWS([], close_code=1000), prep=lambda c: setattr(c, "_closing", True))
        self.check(ends, kind="local_end", initiator="local", close_code=1000)

    def test_observer_failure_never_breaks_the_session(self):
        res, ends = run_session(lambda u, **k: FakeWS([], close_code=1001), cb_raises=True)
        self.assertEqual(res, ("ended", None)); self.assertEqual(len(ends), 1)

    def test_without_observer_behaviour_is_unchanged(self):
        async def go():
            c = T.WSConnection("c", ["s"], mock.Mock(ws_connect=lambda u, **k: FakeWS([], close_code=1008)),
                               lambda *a: None, lambda *a: None, lambda *a: None)
            return await c._session_once(), c.connected
        self.assertEqual(asyncio.run(go()), (("ended", None), False))


class FlapDetectorTests(unittest.TestCase):
    MIN = 60_000

    def test_repeated_short_disconnects_open_one_episode(self):
        fd = F.FlapDetector(1800, 10, 1800); opens = []
        for i in range(25):                                   # one ended session every ~50 s
            ev = fd.record("conn0-book", i * 50_000)
            if ev: opens.append(ev)
        self.assertEqual(len(opens), 1); self.assertEqual(opens[0][0], "open")
        self.assertEqual(opens[0][1]["events_in_window"], 10); self.assertEqual(fd.open["conn0-book"]["events"], 25)

    def test_below_threshold_and_spread_out_never_open(self):
        fd = F.FlapDetector(1800, 10, 1800)
        self.assertFalse([1 for i in range(9) if fd.record("c", i * self.MIN)])
        fd2 = F.FlapDetector(1800, 10, 1800)
        self.assertFalse([1 for i in range(40) if fd2.record("c", i * 12 * self.MIN)])   # 10 in 2 h: not flapping

    def test_clear_after_quiet_period_then_new_episode(self):
        fd = F.FlapDetector(1800, 10, 1800)
        for i in range(10): fd.record("c", i * self.MIN)
        self.assertIsNone(fd.tick("c", 20 * self.MIN))                        # quiet only 11 min
        clr = fd.tick("c", 40 * self.MIN)
        self.assertEqual(clr[0], "clear"); self.assertEqual(clr[1]["episode_events"], 10)
        self.assertIsNone(fd.tick("c", 41 * self.MIN))                        # cleared once
        opens = [fd.record("c", (100 + i) * self.MIN) for i in range(10)]
        self.assertEqual(sum(1 for o in opens if o), 1)                       # a later episode opens again

    def test_long_recovery_episode_single_open_bounded_state(self):
        fd = F.FlapDetector(1800, 10, 1800); opens = 0
        for i in range(10_000):                               # ~5.8 days of 50 s sessions
            if fd.record("c", i * 50_000): opens += 1
            self.assertLessEqual(len(fd._events["c"]), 10)
        self.assertEqual(opens, 1); self.assertIsNone(fd.tick("c", 10_000 * 50_000))

    def test_connections_are_independent(self):
        fd = F.FlapDetector(1800, 10, 1800)
        for i in range(10): fd.record("a", i * self.MIN)
        self.assertNotIn("b", fd.open); self.assertIn("a", fd.open)

    def test_invalid_parameters_refused(self):
        for args in ((0, 10, 1), (1800, 1, 1), (1800, 10, 0)):
            with self.assertRaises(ValueError):
                F.FlapDetector(*args)


class AppWiring(unittest.TestCase):
    def test_defaults_off(self):
        for k in ("ws_session_end_events", "conn_flapping_enabled"):
            self.assertIs(C.DEFAULTS[k], False)
        with tempfile.TemporaryDirectory() as d:
            c = mk_collector(d)
            self.assertFalse(c._obs_enabled())
            self.assertIsNone(c._new_conn("conn0-book", ["btcusdt@bookTicker"]).on_session_end)

    def test_config_validation(self):
        base = {**C.DEFAULTS, "enabled": True, "max_runtime_s": 60}
        for bad in ({"ws_session_end_events": "yes"}, {"conn_flapping_max": 1}, {"conn_flapping_window_s": 0}):
            with self.assertRaises(C.ConfigError):
                C.validate({**base, **bad})

    def test_enabled_events_and_flapping_incident_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk_collector(d, ws_session_end_events=True, conn_flapping_enabled=True)
            c.incidents = I.IncidentLog(d, c.boot_id)
            conn = mock.Mock(); conn.name = "conn0-book"
            info = {"conn": "conn0-book", "gen": 3, "connected": True, "duration_ms": 47_000,
                    "initiator": "remote", "kind": "remote_close", "close_code": 1001, "exc_type": None,
                    "handshake_status": None}
            t = {"m": 1_000_000}
            with mock.patch("p2_forward.app.now_ms", lambda: t["m"]):
                for i in range(15):
                    t["m"] += 50_000; c.on_session_end(conn, dict(info))
                recs = []
                while not c.q.empty():
                    recs.append(c.q.get_nowait())
                ends = [r for r in recs if r.get("type") == "lifecycle" and r["payload"]["event"] == "ws_session_end"]
                self.assertEqual(len(ends), 15)
                self.assertTrue(set(ends[0]["payload"]) <= ALLOWED | {"event"})
                act = [i for i in c.incidents.active() if i["key"] == "conn_flapping:conn0-book"]
                self.assertEqual(len(act), 1); self.assertEqual(act[0]["severity"], "WARNING")
                self.assertFalse(act[0]["latched"]); self.assertEqual(act[0]["count"], 1)    # deduplicated
                t["m"] += 31 * 60_000; c._flap_tick(t["m"])
                self.assertFalse([i for i in c.incidents.active() if i["key"] == "conn_flapping:conn0-book"])


if __name__ == "__main__":
    unittest.main()
