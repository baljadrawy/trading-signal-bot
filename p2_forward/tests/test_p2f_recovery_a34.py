"""P2F 1.6.0 (A34): bounded connection recovery, generation ownership and connection incidents.

Transport tests use REAL aiohttp 3.14.3 client sockets against local loopback servers (127.0.0.1 only) whose peers
misbehave deterministically; the original defect is reproduced against the DEPLOYED transport (cd2935e, extracted
read-only with git archive) and shown fixed in the current one, in the same scenario. App-level tests use the existing
fake-connection collector (tests.test_regression_g2r.mk)."""
import asyncio
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest

import aiohttp
from aiohttp import web

from p2_forward import app as A, transport as T
from p2_forward.incidents import IncidentLog
from tests.test_regression_g2r import mk, lifes, drain

DEPLOYED = "cd2935e"
_SAVED = {}


def setUpModule():
    _SAVED["fixed"] = T._check_url                          # tests patch the allow-list for loopback; restore after


def tearDownModule():
    T._check_url = _SAVED["fixed"]
    mod = sys.modules.get("p2f_cd2935e.transport")
    if mod is not None and "old" in _SAVED:
        mod._check_url = _SAVED["old"]
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_deployed_transport():
    """The cd2935e transport module, imported under a separate package name (no clash with p2_forward)."""
    d = tempfile.mkdtemp(prefix="a34-cd2935e-")
    blob = subprocess.run(["git", "-C", REPO, "archive", DEPLOYED, "p2_forward/p2_forward"], check=True,
                          capture_output=True).stdout
    p = os.path.join(d, "s.tar")
    with open(p, "wb") as fh:
        fh.write(blob)
    with tarfile.open(p) as t:
        t.extractall(d, filter="data")
    os.rename(os.path.join(d, "p2_forward", "p2_forward"), os.path.join(d, "p2f_cd2935e"))
    sys.path.insert(0, d)
    import importlib
    mod = importlib.import_module("p2f_cd2935e.transport")
    _SAVED.setdefault("old", mod._check_url)
    assert importlib.import_module("p2f_cd2935e.config").VERSION == "p2cr-collector-1.5.0"
    return mod


class Peer:
    """Loopback WebSocket peer. Per-connection behaviour from `modes` (the last mode repeats):
      normal        : acks SUBSCRIBE, streams frames, answers CLOSE
      ignore_close  : streams frames forever and never answers CLOSE (A33 D1 / 2026-10-10 signature)
      silent        : sends `burst` frames, then nothing; socket stays open; CLOSE never answered
      no_ack        : like normal but never acknowledges SUBSCRIBE
    """

    def __init__(self, modes, streams=("btcusdt@bookTicker", "ethusdt@bookTicker"), period=0.1, burst=5):
        self.modes, self.streams, self.period, self.burst = list(modes), list(streams), period, burst
        self.n_conn, self.subs, self.sent = 0, [], []
        self.stop = asyncio.Event()

    async def handler(self, request):
        i = self.n_conn
        self.n_conn += 1
        mode = self.modes[min(i, len(self.modes) - 1)]
        ws = web.WebSocketResponse(autoclose=(mode in ("normal", "no_ack")), autoping=True)
        await ws.prepare(request)
        sent = 0
        u = [1000 * (i + 1)]

        async def pump():
            nonlocal sent
            while not self.stop.is_set():
                if mode == "silent" and sent >= self.burst:
                    await asyncio.sleep(0.05); continue
                for s in self.streams:
                    u[0] += 1
                    try:
                        await ws.send_str(json.dumps({"stream": s, "data": {"u": u[0], "s": s.split("@")[0].upper()}}))
                    except (ConnectionResetError, RuntimeError, aiohttp.ClientError):
                        return
                sent += 1
                await asyncio.sleep(self.period)
        task = asyncio.create_task(pump())
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    m = json.loads(msg.data)
                    self.subs.append((i, m.get("id"), list(m.get("params", []))))
                    if mode != "no_ack":
                        await ws.send_str(json.dumps({"result": None, "id": m["id"]}))
            if mode in ("normal", "no_ack"):
                return ws
            await self.stop.wait()                             # CLOSE received (or socket gone): never answered
        finally:
            task.cancel()
            self.sent.append(sent)
        return ws

    async def __aenter__(self):
        app = web.Application()
        app.router.add_get("/stream", self.handler)
        self.runner = web.AppRunner(app, shutdown_timeout=0.5)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        self.base = f"ws://127.0.0.1:{self.site._server.sockets[0].getsockname()[1]}/stream"
        return self

    async def __aexit__(self, *a):
        self.stop.set()
        try:
            await self.runner.cleanup()
        except Exception:                                      # noqa: BLE001 - already cleaned up by the test
            pass


class Probe:
    def __init__(self):
        self.msgs, self.states, self.recov, self.acks = [], [], [], []

    def kw(self):
        return dict(on_message=lambda c, o, r: self.msgs.append((c.gen if hasattr(c, "gen") else None, o)),
                    on_shutdown=lambda *a: None, on_state=lambda c, s: self.states.append((time.monotonic(), s)),
                    on_sub_result=lambda c, o: self.acks.append(o))


def conn(T_, session, peer, probe, **kw):
    T_._check_url = lambda u: None                            # test only: loopback instead of the allow-listed host
    extra = {"on_recovery": lambda c, r: probe.recov.append(r), "close_grace_s": 1.0, "abort_wait_s": 1.0}
    if T_ is not T:
        extra = {}
    k = probe.kw()
    return T_.WSConnection("conn0-book", list(peer.streams), session, k["on_message"], k["on_shutdown"],
                           k["on_state"], base=peer.base, on_sub_result=k["on_sub_result"], **extra, **kw)


async def wait_for(pred, timeout):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        await asyncio.sleep(0.02)
    return pred()


class BeforeAfter(unittest.TestCase):
    """The same scenario against the deployed (cd2935e) and the fixed transport."""

    @classmethod
    def setUpClass(cls):
        cls.OLD = load_deployed_transport()

    async def _scenario(self, T_):
        probe = Probe()
        async with Peer(["ignore_close", "normal"]) as peer, aiohttp.ClientSession() as s:
            c = conn(T_, s, peer, probe)
            run = asyncio.create_task(c.run())
            await wait_for(lambda: len(probe.msgs) > 5, 5)
            t0 = time.monotonic()
            f = asyncio.create_task(c.force_reconnect("data_stall"))
            recovered = await wait_for(lambda: peer.n_conn >= 2 and len([x for x in probe.states if x[1] == "connected"]) >= 2
                                       and any(g == 2 for g, _ in probe.msgs if g is not None), 12)
            out = {"recovered": recovered, "secs": time.monotonic() - t0, "connected": c.connected,
                   "n_conn": peer.n_conn, "states": [x[1] for x in probe.states]}
            peer.stop.set()
            if T_ is T:
                await asyncio.wait_for(c.close(), 10)
            for t in (run, f):
                t.cancel()
            await asyncio.gather(run, f, return_exceptions=True)
            return out

    def test_deployed_transport_stays_stuck(self):
        out = asyncio.run(self._scenario(self.OLD))
        self.assertFalse(out["recovered"], out)
        self.assertTrue(out["connected"], out)                 # still "connected" after 12 s, no reconnect
        self.assertEqual(out["n_conn"], 1, out)

    def test_fixed_transport_recovers_within_bound(self):
        out = asyncio.run(self._scenario(T))
        self.assertTrue(out["recovered"], out)
        self.assertLess(out["secs"], 1.0 + 1.0 + 3.0 + 1.5, out)   # grace + abort wait + max first backoff + margin
        self.assertEqual(out["states"][:3], ["connected", "disconnected", "connected"], out)


class BoundedRecovery(unittest.TestCase):
    def run_(self, coro):
        return asyncio.run(coro)

    def test_ignore_close_peer_is_aborted_and_resubscribed(self):
        async def go():
            probe = Probe()
            async with Peer(["ignore_close", "normal"]) as peer, aiohttp.ClientSession() as s:
                c = conn(T, s, peer, probe)
                run = asyncio.create_task(c.run())
                await wait_for(lambda: len(probe.acks) >= 1, 5)
                res = await c.force_reconnect("data_stall")
                await wait_for(lambda: len(probe.acks) >= 2 and any(g == 2 for g, _ in probe.msgs), 8)
                out = (res, list(peer.subs), c.gen, list(probe.acks))
                await c.close(); await asyncio.gather(run, return_exceptions=True)
                return out
        res, subs, gen, acks = self.run_(go())
        self.assertEqual(res["outcome"], "aborted")
        self.assertLess(res["ms"], 1000 + 1000 + 300)
        self.assertEqual(gen, 2)
        self.assertEqual([x[0] for x in subs], [0, 1])          # SUBSCRIBE re-sent on the new session
        self.assertEqual(subs[0][2], subs[1][2])               # same stream list restored
        self.assertEqual(len(acks), 2)

    def test_open_but_silent_connection_recovers(self):
        async def go():
            probe = Probe()
            async with Peer(["silent", "normal"], burst=3) as peer, aiohttp.ClientSession() as s:
                c = conn(T, s, peer, probe)
                run = asyncio.create_task(c.run())
                await wait_for(lambda: len(probe.msgs) >= 6, 5)
                n_before = len(probe.msgs)
                await asyncio.sleep(0.5)
                stalled = len(probe.msgs) == n_before
                res = await c.force_reconnect("data_stall")
                ok = await wait_for(lambda: any(g == 2 for g, _ in probe.msgs), 8)
                await c.close(); await asyncio.gather(run, return_exceptions=True)
                return stalled, res, ok
        stalled, res, ok = self.run_(go())
        self.assertTrue(stalled)
        self.assertIn(res["outcome"], ("aborted", "graceful"))
        self.assertLess(res["ms"], 2300)                        # aiohttp's own close wait would be 10 s
        self.assertTrue(ok)

    def test_simultaneous_btc_eth_interruption_one_recovery_restores_both(self):
        async def go():
            probe = Probe()
            async with Peer(["silent", "normal"], burst=2) as peer, aiohttp.ClientSession() as s:
                c = conn(T, s, peer, probe)
                run = asyncio.create_task(c.run())
                await wait_for(lambda: len(probe.msgs) >= 4, 5)
                await c.force_reconnect("data_stall")
                await wait_for(lambda: {o["stream"] for g, o in probe.msgs if g == 2 and "stream" in o} ==
                               {"btcusdt@bookTicker", "ethusdt@bookTicker"}, 8)
                g2 = {o["stream"] for g, o in probe.msgs if g == 2 and "stream" in o}
                await c.close(); await asyncio.gather(run, return_exceptions=True)
                return g2, peer.n_conn
        g2, n = self.run_(go())
        self.assertEqual(g2, {"btcusdt@bookTicker", "ethusdt@bookTicker"})
        self.assertEqual(n, 2)

    def test_rapid_and_overlapping_requests_share_one_termination(self):
        async def go():
            probe = Probe()
            async with Peer(["ignore_close", "normal"]) as peer, aiohttp.ClientSession() as s:
                c = conn(T, s, peer, probe)
                run = asyncio.create_task(c.run())
                await wait_for(lambda: len(probe.msgs) > 3, 5)
                first = asyncio.create_task(c.force_reconnect("data_stall"))
                await asyncio.sleep(0.2)                         # a second request while the first is in progress
                rest = await asyncio.gather(*[c.force_reconnect("burst") for _ in range(9)])
                r1 = await first
                await wait_for(lambda: peer.n_conn >= 2 and any(g == 2 for g, _ in probe.msgs), 8)
                await asyncio.sleep(0.5)
                out = (r1, rest, peer.n_conn, len(c.recoveries))
                await c.close(); await asyncio.gather(run, return_exceptions=True)
                return out
        r1, rest, n_conn, n_rec = self.run_(go())
        self.assertNotIn("deduplicated", r1)
        self.assertTrue(all(r.get("deduplicated") and r["gen"] == r1["gen"] for r in rest))
        self.assertEqual(n_conn, 2)                             # exactly one replacement session
        self.assertEqual(n_rec, 1)

    def test_obsolete_generation_and_retired_object_never_deliver(self):
        async def go():
            probe = Probe()
            async with Peer(["normal"]) as peer, aiohttp.ClientSession() as s:
                c = conn(T, s, peer, probe)
                run = asyncio.create_task(c.run())
                await wait_for(lambda: len(probe.msgs) > 2, 5)
                await c.force_reconnect("test")
                await wait_for(lambda: c.gen == 2 and c.connected, 8)
                n = len(probe.msgs)
                raw = json.dumps({"stream": "btcusdt@bookTicker", "data": {"u": 1, "s": "BTCUSDT"}})
                c._handle_text(raw, 1)                           # delayed callback from session 1
                late = len(probe.msgs) - n
                await c.close(); await asyncio.gather(run, return_exceptions=True)
                c.retire(); c._handle_text(raw, c.gen)
                return late, c.stale_dropped
        late, dropped = self.run_(go())
        self.assertEqual(late, 0)                               # the delayed session-1 message was not delivered
        self.assertGreaterEqual(dropped, 2)                     # ... nor anything from the retired object

    def test_subscription_ack_missing_is_visible_not_assumed(self):
        async def go():
            probe = Probe()
            async with Peer(["normal", "no_ack"], streams=["btcusdt@bookTicker", "ethusdt@bookTicker",
                                                            "bnbusdt@bookTicker"]) as peer, aiohttp.ClientSession() as s:
                c = conn(T, s, peer, probe)
                run = asyncio.create_task(c.run())
                await wait_for(lambda: len(probe.acks) >= 1, 5)
                await c.force_reconnect("test")
                await wait_for(lambda: len(peer.subs) >= 2, 8)
                await asyncio.sleep(1.0)
                pending = [r for r in c.sub_requests.values() if not r["resolved"]]
                out = (len(probe.acks), pending, peer.subs)
                await c.close(); await asyncio.gather(run, return_exceptions=True)
                return out
        n_acks, pending, subs = self.run_(go())
        self.assertEqual(n_acks, 1)                             # the second session's SUBSCRIBE was never acked
        self.assertEqual(len(pending), 1)                        # left unresolved for the app's ack-timeout path
        self.assertEqual(subs[1][2], subs[0][2])

    def test_repeated_recovery_failure_uses_backoff_not_a_tight_loop(self):
        async def go():
            probe = Probe()
            async with Peer(["normal"]) as peer, aiohttp.ClientSession() as s:
                c = conn(T, s, peer, probe)
                run = asyncio.create_task(c.run())
                await wait_for(lambda: c.connected, 5)
                await peer.runner.cleanup()                      # the exchange stops accepting connections
                await c.force_reconnect("data_stall")
                t0 = time.monotonic()
                await asyncio.sleep(5.0)
                fails = [x for x in probe.states if x[0] >= t0 and x[1] == "connect_failed"]
                await asyncio.wait_for(c.close(), 5); await asyncio.gather(run, return_exceptions=True)
                return len(fails), c.connected
        n_fail, connected = self.run_(go())
        self.assertFalse(connected)
        self.assertLessEqual(n_fail, 3)                         # Backoff: ~2 s, ~4 s, ... (no restart loop)

    def test_clean_shutdown_is_bounded_against_a_stuck_peer(self):
        async def go():
            probe = Probe()
            async with Peer(["ignore_close"]) as peer, aiohttp.ClientSession() as s:
                c = conn(T, s, peer, probe)
                run = asyncio.create_task(c.run())
                await wait_for(lambda: len(probe.msgs) > 3, 5)
                t0 = time.monotonic()
                res = await c.close()
                await asyncio.wait_for(asyncio.gather(run, return_exceptions=True), 3)
                return res, time.monotonic() - t0, run.done(), c.connected
        res, secs, done, connected = self.run_(go())
        self.assertLess(secs, 1.0 + 1.0 + 1.0 + 1.0)
        self.assertTrue(done)
        self.assertFalse(connected)
        self.assertEqual(res["reason"], "close")

    def test_outer_cancellation_cleans_up_the_session(self):
        async def go():
            probe = Probe()
            async with Peer(["ignore_close"]) as peer, aiohttp.ClientSession() as s:
                c = conn(T, s, peer, probe)
                run = asyncio.create_task(c.run())
                await wait_for(lambda: len(probe.msgs) > 3, 5)
                sess = c._session
                run.cancel()
                await asyncio.gather(run, return_exceptions=True)
                await asyncio.sleep(0.1)
                return sess.done(), c.connected
        sess_done, connected = self.run_(go())
        self.assertTrue(sess_done)
        self.assertFalse(connected)

    def test_wedged_session_is_reported_within_the_hard_bound(self):
        class Wedge:                                             # pathological: swallows cancellation until released
            closed = False
            release = False
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def send_str(self, s): pass
            async def close(self): self.closed = True
            def __aiter__(self): return self
            async def __anext__(self):
                while True:
                    try:
                        await asyncio.sleep(3600)
                    except asyncio.CancelledError:
                        if Wedge.release:
                            raise
                        continue

        class Sess:
            def ws_connect(self, url, **kw): return Wedge()

        async def go():
            probe = Probe()
            T._check_url = lambda u: None
            c = T.WSConnection("conn0-book", ["btcusdt@bookTicker"], Sess(), *(probe.kw()[k] for k in
                               ("on_message", "on_shutdown", "on_state")), base="ws://x/stream",
                               on_recovery=lambda cc, r: probe.recov.append(r), close_grace_s=0.3, abort_wait_s=0.3)
            run = asyncio.create_task(c.run())
            await wait_for(lambda: c.connected, 2)
            t0 = time.monotonic()
            res = await c.force_reconnect("data_stall")
            secs = time.monotonic() - t0
            c.retire()
            Wedge.release = True
            run.cancel()
            await asyncio.wait_for(asyncio.gather(run, return_exceptions=True), 3)
            return res, secs, c.wedged, probe.recov, run
        res, secs, wedged, recov, run = asyncio.run(go())
        self.assertTrue(run.done())
        self.assertEqual(res["outcome"], "wedged")
        self.assertLess(secs, 0.3 + 0.3 + 0.3 + 0.3)
        self.assertTrue(wedged)
        self.assertEqual(recov[-1]["outcome"], "wedged")


class AppIncidents(unittest.TestCase):
    def _mk(self, d):
        c = mk(d)
        c.incidents = IncidentLog(d, c.boot_id)
        c.ws_start_ms = A.now_ms() - 3_600_000
        return c

    def test_connection_outage_one_incident_resolved_on_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            c = self._mk(d); m = A.now_ms(); a = c.activity["conn0-book"]
            a.transitions.append((m - 200_000, True)); a.data(m - 120_000)
            c.activity["conn1-depth"].transitions.append((m - 200_000, True)); c.activity["conn1-depth"].data(m - 50)
            for k in range(5):
                c._conn_incidents(m + k * 1000)
            act = [i for i in c.incidents.active() if i["key"] == "conn_outage:conn0-book"]
            self.assertEqual(len(act), 1); self.assertEqual(act[0]["count"], 1)   # opened once, no per-tick updates
            self.assertEqual(act[0]["severity"], "DEGRADED"); self.assertFalse(act[0]["latched"])
            self.assertFalse([i for i in c.incidents.active() if i["key"].endswith("conn1-depth")])
            a.data(m + 10_000)
            c._conn_incidents(m + 10_500)
            self.assertFalse([i for i in c.incidents.active() if i["key"] == "conn_outage:conn0-book"])
            ev = [json.loads(l) for l in open(os.path.join(d, "incidents", "events.jsonl"))]
            self.assertEqual([e["event"] for e in ev if e["key"] == "conn_outage:conn0-book"], ["open", "resolve"])
            self.assertEqual(len(lifes(drain(c), "conn_outage_resolved")), 1)

    def test_failed_recovery_latches_critical_once(self):
        with tempfile.TemporaryDirectory() as d:
            c = self._mk(d); m = A.now_ms(); a = c.activity["conn0-book"]
            a.transitions.append((m - 900_000, True)); a.data(m - 700_000)
            for k in range(3):
                c._conn_incidents(m + k * 1000)
            crit = [i for i in c.incidents.active() if i["key"] == "conn_recovery_failed:conn0-book"]
            self.assertEqual(len(crit), 1); self.assertTrue(crit[0]["latched"]); self.assertEqual(crit[0]["count"], 1)
            self.assertEqual(crit[0]["severity"], "CRITICAL")
            a.data(m + 5000); c._conn_incidents(m + 5100)
            self.assertTrue([i for i in c.incidents.active() if i["key"] == "conn_recovery_failed:conn0-book"])
            self.assertFalse([i for i in c.incidents.active() if i["key"] == "conn_outage:conn0-book"])

    def test_transient_stream_staleness_on_a_live_connection_raises_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            c = self._mk(d); m = A.now_ms()
            for n in ("conn0-book", "conn1-depth"):
                c.activity[n].transitions.append((m - 100_000, True)); c.activity[n].data(m - 100)
            c._conn_incidents(m)
            self.assertEqual(c.incidents.active(), [])

    def test_tier0_observation_loss_latched_warning_and_gap_record_kept(self):
        with tempfile.TemporaryDirectory() as d:
            c = self._mk(d)
            base = {"first_missing_ms": 0, "last_missing_ms": 0, "missing_samples": 708, "cadence_ms": 1000,
                    "cause": "conn_data_stale", "causes": ["conn_data_stale"], "open_at_stop": False,
                    "start_ms": 1_000_000, "end_ms": 1_708_000}
            c.gap_record({**base, "stream_key": "book|BTCUSDT", "stream": "btcusdt@bookTicker", "duration_ms": 708_000},
                         A.IRREPLACEABLE)
            c.gap_record({**base, "stream_key": "book|GLMRUSDT", "stream": "glmrusdt@bookTicker", "duration_ms": 900_000},
                         A.IRREPLACEABLE)
            c.gap_record({**base, "stream_key": "depth|ETHUSDT", "stream": "ethusdt@depth20", "duration_ms": 3_000},
                         A.IRREPLACEABLE)
            loss = [i for i in c.incidents.active() if i["key"] == "observation_loss:tier0"]
            self.assertEqual(len(loss), 1); self.assertEqual(loss[0]["count"], 1)
            self.assertTrue(loss[0]["latched"]); self.assertEqual(loss[0]["severity"], "WARNING")
            self.assertEqual(c.gap_count, 3)                    # every gap record is still emitted

    def test_wedged_recovery_retires_and_replaces_the_connection(self):
        async def go(d):
            c = self._mk(d)
            old = T.WSConnection("conn0-book", list(c.conns[0].streams), None, c.on_message, c.on_shutdown_event,
                                 c.on_state)
            c.conns[0] = old
            orig = c._new_conn

            def fake_new(name, streams):
                n = orig(name, streams)
                async def idle():
                    await asyncio.sleep(0)
                n.run = idle
                return n
            c._new_conn = fake_new
            c.on_conn_recovery(old, {"reason": "data_stall", "outcome": "wedged", "gen": 3, "ms": 7000})
            await asyncio.sleep(0.01)
            return c, old
        with tempfile.TemporaryDirectory() as d:
            c, old = asyncio.run(go(d))
            self.assertTrue(old.retired)
            self.assertIsNot(c.conns[0], old)
            crit = [i for i in c.incidents.active() if i["key"] == "conn_recovery_failed:conn0-book"]
            self.assertEqual(len(crit), 1)
            evs = [r["payload"]["event"] for r in drain(c) if r.get("type") == "lifecycle"]
            self.assertIn("conn_recovery", evs); self.assertIn("ws_conn_replaced", evs)


if __name__ == "__main__":
    unittest.main()
