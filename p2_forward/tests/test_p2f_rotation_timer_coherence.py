"""P2F 1.5.0 timer coherence (deployment preflight 2026-10-07): the REAL rotate() / _handoff / _handoff_audit /
on_seq / sampler code under the PRODUCTION timers (ws_handoff_min_s 2, ws_handoff_timeout_s 15, seq_catchup_timeout_s
30), driven by a deterministic VIRTUAL clock. No logic of the repair is changed or mocked: only time.time_ns and
asyncio.sleep are replaced by the virtual clock, and the WebSocket sessions are scripted (exchange updates per stream at
fixed times, each socket delivering them with its own gateway lag).

Question answered: can any ordering of {frozen targets at +2 s, hand-off deadline at 15 s, old-socket close, the 30 s
catch-up window anchored at max(behind-run start, hw receipt), seq_stale, catchup_timeout -> seq_reset,
rotation_handoff_incomplete + explicit gaps, genuine seq_reset} produce contradictory continuity semantics, silently
persist an unproven interval, or misclassify a genuine discontinuity?

Invariants checked in EVERY scenario (check_invariants):
  I1 every stream of the hand-off gets exactly one class in ws_handoff, from the closed set;
  I2 ws_rotation.handoff.complete == (no pending stream and reason in {caught_up, old_closed});
  I3 an incomplete hand-off (reason != stopping) and every `unresolved` class raise the WARNING incident
     rotation_handoff_incomplete:<conn> (explicit, latched);
  I4 for every PENDING stream no sample after the close is persisted from a value received before the close
     (it is an explicit awaiting_post_reconnect_data / stale gap until an accepted post-close value exists);
  I5 persisted exchange_seq per stream never decreases, unless a seq_reset lifecycle for that stream precedes it
     (a backwards step is never silent);
  I6 seq_reset lifecycle count == stats seq_reset; every one carries a cause; any seq_reset raises the DEGRADED
     incident at the next continuous check;
  I7 a replacement that trails is seq_stale (never seq_regression) while its own order is intact.
"""
import asyncio
import heapq
import math
import tempfile
import unittest
from unittest import mock

from p2_forward import app as A, config as C
from tests.test_p2cr_controls import prod_cont_cfg
from tests.test_regression_g2r import lifes

UNI = {"tier0": ["BTCUSDT", "ETHUSDT"], "tier1": ["PUMPUSDT"], "tier2": ["DOGEUSDT", "ENAUSDT", "FILUSDT"]}
S = 1_000_000_000
REAL_SLEEP = asyncio.sleep
CLASSES = {"proven", "ahead", "resumed", "quiet", "unresolved", "no_old"}


class VClock:
    """Virtual wall clock. Events (exchange deliveries, socket deaths, sampler boundaries) run in time order whenever
    the single collector sleeper (the hand-off loop, then the audit loop) advances time, or when the test advances it."""

    def __init__(self, t0_ns):
        self.t, self.q, self.n = t0_ns, [], 0

    def time_ns(self):
        return self.t

    def at(self, t_ns, fn):
        heapq.heappush(self.q, (int(t_ns), self.n, fn)); self.n += 1

    def run_until(self, t_ns):
        while self.q and self.q[0][0] <= t_ns:
            t, _, fn = heapq.heappop(self.q)
            self.t = max(self.t, t)
            fn()
        self.t = max(self.t, int(t_ns))

    def run_until_set(self, ev, limit_ns):
        while not ev.is_set() and self.q and self.q[0][0] <= limit_ns:
            t, _, fn = heapq.heappop(self.q)
            self.t = max(self.t, t)
            fn()

    async def sleep(self, d):
        self.run_until(self.t + int(d * S))
        await REAL_SLEEP(0)


class Exchange:
    """Stream s has update k at t0 + phase(s) + k * period, seq = base(s) + k; `quiet` = {stream: [(from_ns, to_ns)]}
    intervals without updates (to_ns None = forever)."""

    def __init__(self, t0, streams, period=0.1, quiet=None):
        self.t0, self.period, self.quiet = t0, period, quiet or {}
        self.phase = {s: int(i * 0.013 * S) for i, s in enumerate(streams)}
        self.base = {s: 10_000_000 * (i + 1) for i, s in enumerate(streams)}

    def updates(self, s, lo_ns, hi_ns):
        p = int(self.period * S)
        k = max(0, math.ceil((lo_ns - self.t0 - self.phase[s]) / p))
        while True:
            t = self.t0 + self.phase[s] + k * p
            if t > hi_ns:
                return
            if not any(a <= t and (b is None or t < b) for a, b in self.quiet.get(s, ())):
                yield t, self.base[s] + k
            k += 1


class VConn:
    """A scripted WebSocket session object with the attributes the collector uses. Deliveries are clock events."""

    def __init__(self, c, clk, ex, name, streams, lag=0.0, offset=0, horizon_ns=0):
        self.c, self.clk, self.ex = c, clk, ex
        self.name, self.streams = name, list(streams)
        self.connected, self._closing, self.reconnects, self.sub_requests = False, False, 0, {}
        self.first_msg, self.last_msg_ns, self.task = asyncio.Event(), None, None
        self.lag, self.offset, self.horizon = lag, offset, horizon_ns
        self._park = asyncio.Event()

    def lag_of(self, s):
        return self.lag.get(s, self.lag.get("*", 0.0)) if isinstance(self.lag, dict) else self.lag

    def connect(self, deliver_from_ns=None):
        self.connected = True
        self.c.on_state(self, "connected")
        start = self.clk.t if deliver_from_ns is None else deliver_from_ns
        for s in self.streams:
            if "@" not in s or s.startswith("!"):
                continue
            L = int(self.lag_of(s) * S)
            for t, seq in self.ex.updates(s, start - L, self.horizon):     # gateway position = now - lag
                self.clk.at(max(t + L, start), lambda s=s, seq=seq, sess=self.session: self._deliver(sess, s, seq))
        self.session = getattr(self, "session", 0) + 1

    session = 0

    def _deliver(self, sess, s, seq):
        if self._closing or not self.connected or sess != self.session - 1:
            return
        self.last_msg_ns = self.clk.t
        self.first_msg.set()
        self.c.on_message(self, {"stream": s, "data": {"u": seq - self.offset}}, self.clk.t)

    def die(self):                                   # the server closes this socket
        if not self.connected:
            return
        self.connected = False
        self.session += 1                            # in-flight deliveries of the dead session are dropped
        if not self._closing:
            self.c.on_state(self, "disconnected")

    async def close(self):
        # aiohttp's close awaits the close handshake: the collector's close_ns (time.time_ns() after `await old.close()`)
        # is strictly later than any message the old socket delivered. Model that with 1 ms of virtual time (without
        # it, a delivery at the very same virtual ns as close_ns would be a tie the real clock cannot produce).
        self._closing = True; self.connected = False
        self.clk.run_until(self.clk.t + 1_000_000)

    async def run(self):                             # replacement: connect, deliver until the first data message
        self.clk.run_until(self.clk.t + int(1.0 * S))                    # connect + SUBSCRIBE ~1 s (production ~1.04 s)
        self.connect(deliver_from_ns=self.clk.t + int(0.5 * S))         # first data ~0.5 s after connect
        self.clk.run_until_set(self.first_msg, self.clk.t + int(120 * S))
        await self._park.wait()


class Scenario:
    """One rotation of conn0-book at T_ROT under the production timers. Returns everything the assertions need."""

    def __init__(self, new_lag=0.3, old_lag=0.0, offset=0, quiet=None, old_dies_after=None, new_dies_after=None,
                 new_reconnect_after=None, extra_s=60.0):
        self.kw = dict(new_lag=new_lag, old_lag=old_lag, offset=offset, quiet=quiet or {}, old_dies_after=old_dies_after,
                       new_dies_after=new_dies_after, new_reconnect_after=new_reconnect_after, extra_s=extra_s)

    def run(self):
        k = self.kw
        with tempfile.TemporaryDirectory() as d:
            cfg = prod_cont_cfg(d); C.validate(cfg)
            assert (cfg["ws_handoff_min_s"], cfg["ws_handoff_timeout_s"], cfg["seq_catchup_timeout_s"]) == (2.0, 15.0, 30)
            c = A.Collector(cfg); c.universe = UNI; c.build_streams()
            t0 = (A.now_ms() // 86_400_000) * 86_400_000 * 1_000_000 + 12 * 3600 * S        # noon, no day boundary
            clk = VClock(t0)
            name, streams = c._conn_streams()[0]
            books = [s for s in streams if s.endswith("@bookTicker")]
            quiet = {books[i] if isinstance(i, int) else i: [(t0 + int(a * S), None if b is None else t0 + int(b * S))
                                                             for a, b in v] for i, v in k["quiet"].items()}
            ex = Exchange(t0, books, quiet=quiet)
            horizon = t0 + int((60 + 200 + k["extra_s"]) * S)
            T_ROT = t0 + 60 * S
            out = {"samples": {}, "recs": [], "c": c, "books": books, "t0": t0}

            def sample(s_ms):
                c.sample(s_ms)
                for tr in c.tracks.values():
                    if tr.kind == "book" and s_ms % tr.cadence == 0:
                        out["samples"].setdefault(tr.name, []).append(
                            (s_ms, "persisted" if tr.last_persisted_sample_ms == s_ms else (tr.gap or {}).get("cause")))
                out["recs"] += [c.q.get_nowait() for _ in range(c.q.qsize())]

            for s_ms in range((t0 + 50 * S) // 1_000_000, horizon // 1_000_000, 1000):
                clk.at(s_ms * 1_000_000 + 200_000_000, lambda s_ms=s_ms: sample(s_ms))

            lag_new = k["new_lag"]
            replacement = {}

            def new_conn(nm, st):
                w = VConn(c, clk, ex, nm, st, lag=lag_new, offset=k["offset"], horizon_ns=horizon)
                replacement["w"] = w
                if k["new_dies_after"] is not None:                   # relative to the replacement's first message
                    async def arm():
                        await w.first_msg.wait()
                        clk.at(clk.t + int(k["new_dies_after"] * S), w.die)
                        if k["new_reconnect_after"] is not None:
                            clk.at(clk.t + int(k["new_reconnect_after"] * S), lambda: w.connect())
                    asyncio.ensure_future(arm())
                return w

            async def go():
                with mock.patch("time.time_ns", clk.time_ns), mock.patch("asyncio.sleep", clk.sleep):
                    old = VConn(c, clk, ex, name, streams, lag=k["old_lag"], horizon_ns=horizon)
                    clk.run_until(t0 + int(1 * S)); old.connect(); c.conns.append(old)
                    clk.run_until(T_ROT)
                    if k["old_dies_after"] is not None:               # relative to the replacement's first message
                        async def arm_old():
                            while "w" not in replacement:
                                await REAL_SLEEP(0)
                            await replacement["w"].first_msg.wait()
                            clk.at(clk.t + int(k["old_dies_after"] * S), old.die)
                        asyncio.ensure_future(arm_old())
                    with mock.patch.object(c, "_new_conn", new_conn):
                        ev = await c.rotate(old, "test_rotation")
                    if c.handoff_tasks:
                        await asyncio.gather(*list(c.handoff_tasks))
                    clk.run_until(clk.t + int(k["extra_s"] * S))
                    with mock.patch.object(c.writer, "status", lambda: {"beat_age_ms": 0, "durable_lag_ms": 0}):
                        c._continuous_checks(A.now_ms())
                    replacement["w"]._park.set()
                    await REAL_SLEEP(0)
                    out["recs"] += [c.q.get_nowait() for _ in range(c.q.qsize())]
                    return ev, old
            out["ev"], out["old"] = asyncio.run(go())
            out["new"] = replacement["w"]
            return out


def by(recs, ev):
    return lifes(recs, ev)


class TimerCoherence(unittest.TestCase):
    def check_invariants(self, o, expect_reset=False):
        c, recs, ev = o["c"], o["recs"], o["ev"]
        h = ev["handoff"]
        hs = by(recs, "ws_handoff")
        self.assertEqual(len(hs), 1, "exactly one post-close audit")
        hh = hs[0]
        # I1
        self.assertEqual(set(hh["streams"]), set(s for s in o["books"]))
        for s, x in hh["streams"].items():
            self.assertIn(x["class"], CLASSES, s)
        self.assertEqual(sum(hh["classes"].values()), len(hh["streams"]))
        # I2
        self.assertEqual(h["complete"], h["pending"] == 0 and h["reason"] in ("caught_up", "old_closed"))
        # I3
        keys = {i["key"]: i for i in c.incidents.active()}
        if not h["complete"] or hh["classes"].get("unresolved"):
            self.assertEqual(keys["rotation_handoff_incomplete:conn0-book"]["severity"], "WARNING")
        else:
            self.assertNotIn("rotation_handoff_incomplete:conn0-book", keys)
        # I4
        close_ms = h["close_ms"]
        books = {r["endpoint"]: [] for r in recs if r["type"] == "book"}
        for r in recs:
            if r["type"] == "book":
                books[r["endpoint"]].append(r)
        for s in h["pending_streams"]:
            for r in books.get(s, []):
                if r["sample_ms"] > close_ms:
                    self.assertGreaterEqual(r["recv_ts_ns"] // 1_000_000, close_ms,
                                            f"{s}: pre-close value persisted after an incomplete hand-off")
        # I5 / I6
        resets = by(recs, "seq_reset")
        self.assertEqual(len(resets), c.stats.get("seq_reset", 0))
        for r in resets:
            self.assertIn(r["cause"], ("catchup_timeout", "in_socket_regression"))
        reset_ms = {}
        for r in recs:
            if r["type"] == "lifecycle" and r["payload"]["event"] == "seq_reset":
                reset_ms.setdefault(r["payload"]["stream"], []).append(r["observed_at_ms"])
        for s, rs in books.items():
            rs.sort(key=lambda r: r["sample_ms"])
            for a, b in zip(rs, rs[1:]):
                if b["exchange_seq"] < a["exchange_seq"]:
                    self.assertTrue(any(a["sample_ms"] <= t <= b["sample_ms"] + 1000 for t in reset_ms.get(s, [])),
                                    f"{s}: silent backwards step {a['exchange_seq']} -> {b['exchange_seq']}")
        if resets:
            self.assertEqual(keys["seq_reset"]["severity"], "DEGRADED")
        self.assertEqual(bool(resets), expect_reset)
        # I7
        self.assertEqual(c.stats["rejected"].get("seq_regression", 0), 0)
        return h, hh

    def gaps_between(self, o, s, lo_ms, hi_ms):
        return [(t, why) for t, why in o["samples"][s] if lo_ms < t < hi_ms]

    # ------------------------------------------------------------------ hand-off completes inside 15 s
    def test_small_and_moderate_lags_complete_without_reset_or_gap(self):
        for lag in (0.0, 0.3, 5.0, 12.0):
            with self.subTest(lag=lag):
                o = Scenario(new_lag=lag).run()
                h, hh = self.check_invariants(o)
                self.assertEqual(h["reason"], "caught_up"); self.assertTrue(h["complete"])
                self.assertGreaterEqual(h["duration_ms"], 2000)                 # never before the frozen-target point
                self.assertLess(h["duration_ms"], 2000 + lag * 1000 + 600)      # done as soon as targets are reached
                self.assertEqual(set(hh["classes"]), {"proven"})
                self.assertEqual(hh["audit_end"], "all_reached")
                for s, x in hh["streams"].items():
                    self.assertLessEqual(x["reach_ms"] - hh["close_ms"], lag * 1000 + 300)
                self.assertEqual(o["c"].stats.get("seq_reset", 0), 0)
                if lag:
                    self.assertGreater(o["c"].stats.get("seq_stale", 0), 0)    # trailing copies: stale, not resets
                for s in o["books"]:                                           # no gap at all around the rotation
                    self.assertFalse([x for x in self.gaps_between(o, s, h["close_ms"] - 1000, h["close_ms"] + 40000)
                                      if x[1] != "persisted"], s)

    # ------------------------------------------------------------------ 15 s deadline, catch-up between 15 and 30 s
    def test_timeout_then_catch_up_between_15_and_30_s_is_explicit_gap_then_proven(self):
        for lag in (14.0, 20.0, 29.0):
            with self.subTest(lag=lag):
                o = Scenario(new_lag=lag).run()
                h, hh = self.check_invariants(o)
                self.assertEqual(h["reason"], "timeout"); self.assertFalse(h["complete"])
                self.assertTrue(15000 <= h["duration_ms"] < 15200)
                self.assertEqual(h["pending"], 6)
                self.assertEqual(o["c"].stats.get("seq_reset", 0), 0)             # within the window: no reset
                self.assertEqual(set(hh["classes"]), {"proven"}); self.assertEqual(hh["audit_end"], "all_reached")
                for s, x in hh["streams"].items():
                    self.assertTrue(x["await"])
                    self.assertGreater(x["reach_ms"], hh["close_ms"])
                    self.assertLessEqual(x["reach_ms"] - hh["close_ms"], lag * 1000 + 300)
                    after = self.gaps_between(o, s, hh["close_ms"], x["reach_ms"])
                    self.assertTrue(after and all(w == "awaiting_post_reconnect_data" for _, w in after), (s, after))
                    later = self.gaps_between(o, s, x["reach_ms"] + 1000, x["reach_ms"] + 20000)
                    self.assertTrue(later and all(w == "persisted" for _, w in later), (s, later))
                    self.assertIsNone(o["c"].tracks[s].await_after_ns)          # cleared by the accepted catch-up

    # ------------------------------------------------------------------ never catches up: visible discontinuity
    def test_lag_beyond_30_s_after_close_is_a_visible_reset_never_silent(self):
        o = Scenario(new_lag=40.0, extra_s=80.0).run()
        h, hh = self.check_invariants(o, expect_reset=True)
        self.assertEqual(h["reason"], "timeout")
        self.assertEqual(o["c"].stats["seq_reset_causes"], {"catchup_timeout": 6})
        for r in o["recs"]:                                                    # anchored at hw receipt (<= close) + 30 s
            if r["type"] == "lifecycle" and r["payload"]["event"] == "seq_reset":
                p = r["payload"]
                self.assertLessEqual(p["hw_recv_ms"], hh["close_ms"])
                self.assertTrue(p["hw_recv_ms"] + 30000 < r["observed_at_ms"] <= p["hw_recv_ms"] + 30000 + 300, p)
        self.assertEqual(set(hh["classes"]), {"unresolved"})
        for s in o["books"]:
            g = self.gaps_between(o, s, hh["close_ms"], hh["close_ms"] + 29000)
            self.assertTrue(g and all(w == "awaiting_post_reconnect_data" for _, w in g), (s, g))

    def test_genuine_id_space_reset_on_the_replacement_is_detected(self):
        o = Scenario(new_lag=0.0, offset=5_000_000).run()
        h, hh = self.check_invariants(o, expect_reset=True)
        self.assertEqual(h["reason"], "timeout"); self.assertEqual(h["pending"], 6)
        self.assertEqual(o["c"].stats["seq_reset_causes"], {"catchup_timeout": 6})
        rs = by(o["recs"], "seq_reset")
        for r in rs:                                                           # detected ~hw receipt + 30 s, not later
            self.assertLessEqual(r["hw_recv_ms"], hh["close_ms"])
        self.assertEqual(set(hh["classes"]), {"unresolved"})

    # ------------------------------------------------------------------ socket deaths during the hand-off
    def test_old_socket_dies_mid_handoff_replacement_still_stale_after_close(self):
        o = Scenario(new_lag=8.0, old_dies_after=5.0).run()
        h, hh = self.check_invariants(o)
        self.assertEqual(h["reason"], "old_closed"); self.assertFalse(h["complete"])
        self.assertTrue(by(o["recs"], "ws_superseded_closed")); self.assertFalse(by(o["recs"], "ws_disconnected"))
        self.assertTrue(all(up for _, up in o["c"].activity["conn0-book"].transitions))   # never a down transition
        self.assertEqual(o["c"].stats.get("seq_reset", 0), 0)
        self.assertEqual(set(hh["classes"]), {"proven"})
        for s, x in hh["streams"].items():
            g = self.gaps_between(o, s, hh["close_ms"], x["reach_ms"])
            self.assertTrue(g and all(w == "awaiting_post_reconnect_data" for _, w in g), (s, g))

    def test_replacement_disconnects_mid_handoff_is_explicit_down_and_conservative_audit(self):
        o = Scenario(new_lag=5.0, new_dies_after=3.0, new_reconnect_after=6.0).run()
        h, hh = self.check_invariants(o)
        self.assertEqual(h["reason"], "new_disconnected"); self.assertFalse(h["complete"])
        self.assertTrue(by(o["recs"], "ws_disconnected"))                     # an explicit connection-down event
        self.assertEqual(o["c"].stats.get("seq_reset", 0), 0)                  # the reconnected session's copies: stale
        self.assertEqual(set(hh["classes"]), {"unresolved"})                   # epoch-bound proof: conservative WARNING
        for s in o["books"]:
            g = self.gaps_between(o, s, hh["close_ms"], hh["close_ms"] + 2500)
            self.assertTrue(g and all(w in ("ws_disconnect_reconnect", "awaiting_post_reconnect_data") for _, w in g),
                            (s, g))

    # ------------------------------------------------------------------ streams finishing at different times
    def test_streams_finish_at_different_times_only_late_ones_are_gapped(self):
        lags = {"*": 0.3}
        o0 = Scenario().run()
        b = o0["books"]
        lags.update({b[1]: 5.0, b[2]: 10.0, b[3]: 14.0, b[4]: 20.0})
        o = Scenario(new_lag=lags).run()
        h, hh = self.check_invariants(o)
        self.assertEqual(h["reason"], "timeout"); self.assertEqual(sorted(h["pending_streams"]), sorted([b[3], b[4]]))
        self.assertEqual(o["c"].stats.get("seq_reset", 0), 0)
        self.assertEqual(set(hh["classes"]), {"proven"})
        for s in b:
            g = self.gaps_between(o, s, hh["close_ms"], hh["streams"][s]["reach_ms"])
            if s in (b[3], b[4]):
                self.assertTrue(g and all(w == "awaiting_post_reconnect_data" for _, w in g), (s, g))
            else:
                self.assertTrue(all(w == "persisted" for _, w in g), (s, g))

    # ------------------------------------------------------------------ classes ahead / resumed / quiet / no_old
    def test_ahead_resumed_quiet_and_no_old_classes(self):
        quiet = {1: [(50.0, 69.0)], 2: [(50.0, None)], 3: [(0.0, None)]}       # rel. to t0; rotation at 60 s
        o = Scenario(new_lag=0.0, old_lag=3.0, quiet=quiet).run()
        h, hh = self.check_invariants(o)
        self.assertEqual(h["reason"], "caught_up")
        b = o["books"]
        cls = {s: x["class"] for s, x in hh["streams"].items()}
        self.assertEqual(cls[b[0]], "ahead"); self.assertEqual(cls[b[1]], "resumed")
        self.assertEqual(cls[b[2]], "quiet"); self.assertEqual(cls[b[3]], "no_old")
        self.assertEqual(o["c"].stats.get("seq_reset", 0), 0)

    # ------------------------------------------------------------------ boundary: window shorter than the audit
    def test_quiet_before_close_and_lag_just_over_30_s_is_visible_reset_then_proven(self):
        """Documented edge: for a stream whose last old-socket update arrived d s before the close, the catch-up
        window ends at hw receipt + 30 s, d s before the audit deadline. A replacement lagging 30..30+d s is then
        reset VISIBLY (DEGRADED, lifecycle) and may still reach the old final before the audit ends (class proven).
        Both records are true and the DEGRADED one dominates health: conservative, never silent continuity."""
        o0 = Scenario().run(); b = o0["books"]
        o = Scenario(new_lag={"*": 20.0, b[0]: 33.0}, quiet={0: [(70.0, None)]}, extra_s=80.0).run()
        h, hh = self.check_invariants(o, expect_reset=True)
        self.assertEqual(o["c"].stats["seq_reset_causes"], {"catchup_timeout": 1})
        self.assertEqual(by(o["recs"], "seq_reset")[0]["stream"], b[0])
        self.assertEqual(hh["streams"][b[0]]["class"], "proven")
        self.assertEqual({i["key"]: i["severity"] for i in o["c"].incidents.active()}["seq_reset"], "DEGRADED")


if __name__ == "__main__":
    unittest.main()
