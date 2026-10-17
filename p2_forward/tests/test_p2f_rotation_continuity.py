"""P2F rotation hand-off / sequence continuity repair (collector 1.5.0) - adversarial tests.

Defect (2026-10-07T00:10:10Z, boot b1b7edb6): a universe transition rotated both sockets; the old socket was closed
~1 ms after the replacement's first data message, so the cb99c05 `overlap` flag was effectively never true while the
replacement - which TRAILED the old socket - delivered older bookTicker updates. 20 consecutive older updates on
DOGE / ENA / PUMP were classified as an exchange-side reset: 3 x `seq_reset`, a latched DEGRADED incident.

Sections:
  A  StreamTrack.on_seq invariant (unit, deterministic)
  B  production incident replay at the callback level (deterministic; exact production timings and persisted values)
  C  the real rotate() hand-off on a lagging fake exchange (asyncio; outcome classes with wide timing margins)
  D  market component event-time guard
"""
import asyncio
import json
import math
import os
import pathlib
import tempfile
import time
import unittest
import zlib
from unittest import mock

from p2_forward import app as A, config as C, tracks as TK
from tests.test_p2cr_controls import prod_cont_cfg
from tests.test_regression_g2r import Conn, drain, gaps, lifes

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "rotation_incident_20261007.json").read_text())
S_NS = 1_000_000_000
CATCHUP = 30 * S_NS


def track(name="dogeusdt@bookTicker"):
    return TK.StreamTrack(name, "book", name.split("@")[0].upper(), 2, 2000, "conn0-book", 600_000, 120_000, 120_000)


# ============================================================================================ A: invariant (unit)
class SeqInvariant(unittest.TestCase):
    def test_trailing_epoch_copies_are_stale_never_regression_or_reset(self):
        t = track()
        for i in range(100):
            self.assertIn(t.on_seq(1000 + i, {}, 1000 + i, 1, CATCHUP)[0], (None, "first"))      # owner: epoch 1
        res = [t.on_seq(2000 + i, {}, 950 + i, 2, CATCHUP)[0] for i in range(150)]               # epoch 2 trails by 50
        self.assertEqual(res[:49], ["seq_stale"] * 49)                                           # 950..998 < 1099
        self.assertNotIn("seq_reset", res); self.assertNotIn("seq_regression", res)
        self.assertEqual(t.values.latest[2], 1099)                                              # never went backwards
        self.assertEqual(t.on_seq(5000, {}, 1100, 2, CATCHUP)[0], None)                          # caught up: accepted

    def test_more_than_20_stale_on_many_streams(self):
        for n in ("a@bookTicker", "b@bookTicker", "c@bookTicker"):
            t = track(n)
            t.on_seq(1, {}, 10_000, 1, CATCHUP)
            res = [t.on_seq(10 + i, {}, 9_000 + i, 2, CATCHUP)[0] for i in range(500)]
            self.assertEqual(set(res), {"seq_stale"}, n)

    def test_catch_up_reports_behind_run(self):
        t = track(); t.on_seq(1, {}, 100, 1, CATCHUP)
        for i in range(25):
            t.on_seq(10 + i * 1000, {}, 70 + i, 2, CATCHUP)
        res, info = t.on_seq(10 + 30 * 1000, {}, 100, 2, CATCHUP)                                # equal = caught up
        self.assertIsNone(res); self.assertTrue(info["caught_up"]); self.assertEqual(info["behind_n"], 25)

    def test_sole_owner_in_socket_regression_still_resets_after_20(self):
        t = track(); t.on_seq(1, {}, 1000, 1, CATCHUP)
        res = [t.on_seq(10 + i, {}, 5 + i, 1, CATCHUP) for i in range(20)]                      # same socket backwards
        self.assertEqual([r for r, _ in res[:19]], ["seq_regression"] * 19)
        self.assertTrue(res[0][1]["first_in_socket_regression"])
        self.assertEqual(res[19][0], "seq_reset"); self.assertEqual(res[19][1]["cause"], "in_socket_regression")
        self.assertEqual(t.values.latest[2], 24)                                                # new id space, visible

    def test_single_in_socket_glitch_is_regression_not_reset(self):
        t = track(); t.on_seq(1, {}, 1000, 1, CATCHUP)
        self.assertEqual(t.on_seq(2, {}, 990, 1, CATCHUP)[0], "seq_regression")
        self.assertIsNone(t.on_seq(3, {}, 1001, 1, CATCHUP)[0])
        self.assertEqual(t.values.latest[2], 1001)

    def test_replacement_that_never_catches_up_resets_after_window(self):
        t = track(); t.on_seq(1 * S_NS, {}, 5_000_000, 1, CATCHUP)                              # owner's last at 1 s
        res = [t.on_seq(2 * S_NS + i * S_NS // 10, {}, 100 + i, 2, CATCHUP)[0] for i in range(300)]   # 30 s of older
        self.assertEqual(set(res[:-1]), {"seq_stale"})
        late = t.on_seq(40 * S_NS, {}, 500, 2, CATCHUP)                                         # beyond the window
        self.assertEqual(late[0], "seq_reset"); self.assertEqual(late[1]["cause"], "catchup_timeout")
        self.assertEqual(t.values.latest[2], 500)

    def test_window_starts_at_the_later_of_behind_start_and_hw_receipt(self):
        t = track(); t.on_seq(100 * S_NS, {}, 1000, 1, CATCHUP)
        self.assertEqual(t.on_seq(101 * S_NS, {}, 10, 2, CATCHUP)[0], "seq_stale")
        self.assertEqual(t.on_seq(130 * S_NS, {}, 11, 2, CATCHUP)[0], "seq_stale")             # 29 s after start
        self.assertEqual(t.on_seq(131 * S_NS + 1, {}, 12, 2, CATCHUP)[0], "seq_reset")

    def test_owner_still_advancing_keeps_trailing_copies_stale(self):
        t = track()
        for i in range(60):                                                                     # 60 s overlap
            t.on_seq(i * S_NS, {}, 1000 + 10 * i, 1, CATCHUP)
            self.assertEqual(t.on_seq(i * S_NS + 1, {}, 995 + 10 * i - 10, 2, CATCHUP)[0] if i else "seq_stale",
                             "seq_stale")

    def test_reconnect_epoch_trailing_is_stale_within_window(self):
        t = track(); t.on_seq(1 * S_NS, {}, 2000, 1, CATCHUP)
        self.assertEqual(t.on_seq(9 * S_NS, {}, 1990, 3, CATCHUP)[0], "seq_stale")              # after a reconnect
        self.assertIsNone(t.on_seq(9 * S_NS + 5, {}, 2001, 3, CATCHUP)[0])

    def test_forward_jump_is_accepted(self):
        t = track(); t.on_seq(1, {}, 1000, 1, CATCHUP)
        self.assertIsNone(t.on_seq(2, {}, 10 ** 12, 1, CATCHUP)[0])                              # sparse ids: normal
        self.assertEqual(t.values.latest[2], 10 ** 12)

    def test_equal_seq_from_another_epoch_is_accepted_like_before(self):
        t = track(); t.on_seq(1, {}, 1000, 1, CATCHUP)
        self.assertIsNone(t.on_seq(5, {}, 1000, 2, CATCHUP)[0])
        self.assertEqual(t.values.latest[0], 5)

    def test_epoch_state_is_bounded(self):
        t = track()
        for e in range(1, 50):
            t.on_seq(e, {}, e, e, CATCHUP)
        self.assertLessEqual(len(t.seqc.eps), TK.SeqContinuity.MAX_EPOCHS)

    def test_bounded_mode_rule_unchanged(self):
        t = track(); t.on_msg(1_000, {}, 100)
        self.assertEqual([t.on_msg(2_000 + i, {}, 10 + i) for i in range(20)][-1], "seq_reset")


# ============================================================================================ B: incident replay
DOGE, ENA, PUMP, FIL = "dogeusdt@bookTicker", "enausdt@bookTicker", "pumpusdt@bookTicker", "filusdt@bookTicker"
D0 = FIX["day_start_ms"]
ROT0 = FIX["rotations"]["conn0-book"]
RESET = {r["stream"]: r for r in FIX["seq_reset"]}
UNI = {"tier0": ["BTCUSDT", "ETHUSDT"], "tier1": ["PUMPUSDT"], "tier2": ["DOGEUSDT", "ENAUSDT", "FILUSDT"]}


def spread(a_ns, b_ns, n):
    return [a_ns + (b_ns - a_ns) * (i + 1) // n for i in range(n)]


def incident_script(old_final, stale_before=20, fil=False):
    """The 2026-10-07 conn0-book rotation, reconstructed from the production records:
    old socket (epoch 'old') delivers up to `old_final` by old_last_msg_ms; the replacement connects at
    ws_connected_ms, is acked and delivers its first data message at new_first_msg_ms, then delivers OLDER updates:
    the `stale_before`-th older update after the old socket's close is exactly the production seq_reset value at its
    production receive time; then it continues past old_final up to the next persisted value at its receive time."""
    ev = []
    close_ns = ROT0["logged_ms"] * 1_000_000                                       # legacy: old closed here
    first_ns = ROT0["new_first_msg_ms"] * 1_000_000
    streams = [DOGE, ENA, PUMP] + ([FIL] if fil else [])
    for s in streams:
        if s == FIL:                                                              # retiered at the transition (2 -> 1)
            p = {"before": [D0 + 610_000, 5_000_000_000, D0 + 609_500], "after": [D0 + 620_000, 5_000_000_600, D0 + 619_000]}
            rst = {"seq": 5_000_000_200, "recv_ns": (D0 + 610_700) * 1_000_000}
        else:
            p, rst = FIX["persisted"][s], RESET[s]
        b_seq, b_recv = p["before"][1], p["before"][2]
        of = old_final[s]
        assert rst["seq"] < of < p["after"][1]
        ev.append((b_recv * 1_000_000, "msg", "old", s, b_seq))
        for i, t in enumerate(spread((D0 + 610_000) * 1_000_000 + 1, ROT0["old_last_msg_ms"] * 1_000_000, of - b_seq)):
            ev.append((t, "msg", "old", s, b_seq + 1 + i))
        lo = rst["seq"] - stale_before + 1                                        # the stale run after the close
        ev.append((first_ns + 100, "msg", "new", s, lo - 1))                       # inside the 1 ms legacy overlap
        for i, t in enumerate(spread(close_ns + 1000, rst["recv_ns"], stale_before)):
            ev.append((t if i < stale_before - 1 else rst["recv_ns"], "msg", "new", s, lo + i))
        a_seq, a_recv = p["after"][1], p["after"][2] * 1_000_000
        for i, t in enumerate(spread(rst["recv_ns"] + 1000, a_recv, a_seq - rst["seq"])):
            ev.append((t if i < a_seq - rst["seq"] - 1 else a_recv, "msg", "new", s, rst["seq"] + 1 + i))
    ev.append((ROT0["ws_connected_ms"] * 1_000_000, "connected", "new", None, None))
    ev.append((ROT0["subscribe_ack_ms"] * 1_000_000 - 1, "ack", "new", None, None))
    return sorted(ev, key=lambda e: (e[0], e[1] != "connected"))


class IncidentReplay(unittest.TestCase):
    """Deterministic callback-level replay. Old-final hypotheses span the feasible interval (the production old
    final was not recorded): just above the reset value (minimum lag), mid, and just below the next persisted value
    (maximum lag, up to ~230 stale updates per stream)."""
    FINALS = [{DOGE: RESET[DOGE]["seq"] + k, ENA: RESET[ENA]["seq"] + k, PUMP: RESET[PUMP]["seq"] + k,
               FIL: 5_000_000_200 + k} for k in (1, 30, 200)]

    def collector(self, d):
        c = A.Collector(prod_cont_cfg(d))
        c.universe = UNI; c.build_streams()
        return c

    def replay(self, d, script, legacy=False, transition_at=None, samples=()):
        clock = {"ms": D0}
        with mock.patch.object(A, "now_ms", lambda: clock["ms"]):
            c = self.collector(d)
            old, new = Conn("conn0-book", c._conn_streams()[0][1]), Conn("conn0-book", c._conn_streams()[0][1])
            c.conns = [old, Conn("conn1-depth", c._conn_streams()[1][1])]
            clock["ms"] = D0 - 11 * 3600_000
            c.on_state(old, "connected")
            legacy_tr = {}
            pend = sorted(samples)
            for t_ns, kind, who, s, seq in script:
                while pend and pend[0] * 1_000_000 < t_ns:
                    S = pend.pop(0); clock["ms"] = S + 5
                    if transition_at is not None and S == transition_at:
                        c.pending_transition = {"T": S, "universe": {**UNI, "tier1": ["PUMPUSDT", "FILUSDT"],
                                                                     "tier2": ["DOGEUSDT", "ENAUSDT"]},
                                                "meta": {"universe_id": "uni|test|tiers-v2", "file": "u.json",
                                                         "sha256": "0" * 64, "stamp": "x", "applied": True}}
                    c.sample(S)
                clock["ms"] = t_ns // 1_000_000
                conn = old if who == "old" else new
                if kind == "connected":
                    c.on_state(new, "connected")
                elif kind == "ack":
                    c.on_subscribe_result(new, {"id": 1, "result": None})
                elif legacy:                                                     # cb99c05 rule, production timing
                    tr = legacy_tr.setdefault(s, track(s))
                    r = tr.on_msg(t_ns, {}, seq, overlap=t_ns < ROT0["logged_ms"] * 1_000_000)
                    if r == "seq_reset":
                        c.stats.setdefault("legacy_resets", []).append((s, seq, t_ns))
                else:
                    c.on_message(conn, {"stream": s, "data": {"u": seq, "s": s.split("@")[0].upper()}}, t_ns)
            for S in pend:
                clock["ms"] = S + 5; c.sample(S)
        return c

    def test_fixture_reproduces_the_production_incident_under_the_old_rule(self):
        for fin in self.FINALS:
            with tempfile.TemporaryDirectory() as d:
                c = self.replay(d, incident_script(fin), legacy=True)
                got = [(s, q, t) for s, q, t in c.stats["legacy_resets"]]
                self.assertEqual(got, [(r["stream"], r["seq"], r["recv_ns"]) for r in FIX["seq_reset"]])

    def test_new_rule_no_reset_no_regression_same_persisted_values(self):
        samples = [D0 + 610_000, D0 + 612_000, D0 + 620_000]
        for fin in self.FINALS:
            with tempfile.TemporaryDirectory() as d:
                c = self.replay(d, incident_script(fin), samples=samples)
                self.assertEqual(c.stats.get("seq_reset", 0), 0, fin)
                self.assertEqual(c.stats["rejected"].get("seq_regression", 0), 0)
                self.assertGreaterEqual(c.stats["seq_stale"], 3 * 20)
                recs = drain(c)
                self.assertFalse(lifes(recs, "seq_reset"))
                got = {(r["endpoint"], r["sample_ms"]): r["exchange_seq"] for r in recs if r["type"] == "book"}
                for s in (DOGE, ENA, PUMP):                                       # identical to production output
                    p = FIX["persisted"][s]
                    self.assertEqual(got[(s, p["before"][0])], p["before"][1], s)
                    self.assertEqual(got[(s, p["after"][0])], p["after"][1], s)
                seqs = {}
                for r in sorted((r for r in recs if r["type"] == "book"), key=lambda r: r["sample_ms"]):
                    self.assertGreaterEqual(r["exchange_seq"], seqs.get(r["endpoint"], 0)); seqs[r["endpoint"]] = r["exchange_seq"]

    def test_varied_order_and_burst_sizes(self):
        for stale_before in (21, 40, 120):                       # more than 20 older updates after the close
            fin = {DOGE: RESET[DOGE]["seq"] + 50, ENA: RESET[ENA]["seq"] + 50, PUMP: RESET[PUMP]["seq"] + 50}
            sc = incident_script(fin, stale_before=stale_before)
            sc.sort(key=lambda e: (e[0], -zlib.crc32(str(e[3]).encode())))     # different interleaving across streams
            with tempfile.TemporaryDirectory() as d:
                c = self.replay(d, sc)
                self.assertEqual(c.stats.get("seq_reset", 0), 0)
                self.assertGreaterEqual(c.stats["seq_stale"], 3 * stale_before)

    def test_retiered_stream_keeps_continuity_across_transition(self):
        fin = dict(self.FINALS[1])
        with tempfile.TemporaryDirectory() as d:
            c = self.replay(d, incident_script(fin, fil=True), transition_at=D0 + 610_000,
                            samples=[D0 + 610_000, D0 + 620_000])
            self.assertEqual(c.tracks[FIL].tier, 1)
            old_ep = c.conns[0].p2f_epoch
            self.assertEqual(c.tracks[FIL].seqc.eps[old_ep].first, 5_000_000_000)   # state carried over the re-tier
            self.assertEqual(c.stats.get("seq_reset", 0), 0)
            self.assertEqual(c.stats["rejected"].get("seq_regression", 0), 0)

    def test_genuine_reset_inside_the_replay_is_still_detected(self):
        fin = dict(self.FINALS[0])
        sc = incident_script(fin)
        t_last = max(e[0] for e in sc)
        sc += [(t_last + i * S_NS // 2, "msg", "new", DOGE, 7 + i) for i in range(1, 80)]   # exchange id space restarts
        with tempfile.TemporaryDirectory() as d:
            c = self.replay(d, sc)
            self.assertEqual(c.stats.get("seq_reset", 0), 1)
            self.assertEqual(c.stats["seq_reset_causes"], {"in_socket_regression": 1})
            life = lifes(drain(c))
            reg = [p for p in life if p["event"] == "seq_regression"]
            self.assertEqual(len(reg), 1); self.assertEqual(reg[0]["stream"], DOGE)
            rs = [p for p in life if p["event"] == "seq_reset"]
            self.assertEqual(rs[0]["cause"], "in_socket_regression"); self.assertIn("epoch", rs[0])

    def test_reset_detail_reaches_the_incident(self):
        with tempfile.TemporaryDirectory() as d:
            c = A.Collector(prod_cont_cfg(d)); c.universe = UNI; c.build_streams()
            o = Conn("conn0-book", []); c.on_state(o, "connected")
            c.on_message(o, {"stream": DOGE, "data": {"u": 1000}}, 10)
            for i in range(20):
                c.on_message(o, {"stream": DOGE, "data": {"u": 5 + i}}, 20 + i)
            with mock.patch.object(c.writer, "status", lambda: {"beat_age_ms": 0, "durable_lag_ms": 0}):
                c._continuous_checks(A.now_ms())
            inc = [i for i in c.incidents.active() if i["key"] == "seq_reset"]
            self.assertEqual(len(inc), 1); self.assertEqual(inc[0]["severity"], "DEGRADED")
            self.assertEqual(inc[0]["last_detail"]["last"]["cause"], "in_socket_regression")


# ============================================================================================ C: real rotate()
class Feed:
    """Exchange side: every stream has update k at t0 + k * period (seq = base(stream) + k)."""

    def __init__(self, period=0.01):
        self.t0, self.period = time.time(), period

    def k_at(self, t):
        return math.floor((t - self.t0) / self.period)

    @staticmethod
    def seq(s, k):
        return 10_000_000 + 1_000_000 * (zlib.crc32(s.encode()) % 50) + k


class Msg:
    __slots__ = ("type", "data")

    def __init__(self, data):
        self.type, self.data = A.aiohttp.WSMsgType.TEXT, data


class LagWS:
    """One socket. A new subscription starts at the gateway's current (lagged) position; `offset` shifts the id space
    (an exchange-side reset seen only on this socket); `die_after` = server closes the socket."""

    def __init__(self, feed, url, lag=0.0, offset=0, die_after=None):
        self.feed, self.lag, self.offset = feed, lag, offset
        self.streams, self.pending, self.pos, self.closed, self.rr = [url.split("streams=")[1]], [], {}, False, 0
        self.die_at = time.time() + die_after if die_after else None

    async def __aenter__(self): return self
    async def __aexit__(self, *a): self.closed = True; return False

    async def send_str(self, s):
        m = json.loads(s); self.streams += m["params"]; self.pending.append({"result": None, "id": m["id"]})

    async def close(self): self.closed = True
    def __aiter__(self): return self

    @staticmethod
    def _txt(obj):
        return Msg(json.dumps(obj))

    async def __anext__(self):
        while True:
            if self.closed or (self.die_at is not None and time.time() >= self.die_at):
                self.closed = True
                raise StopAsyncIteration
            if self.pending:
                return self._txt(self.pending.pop(0))
            kmax = self.feed.k_at(time.time() - self.lag)
            names = [s for s in self.streams if "@" in s and not s.startswith("!")]
            for i in range(len(names)):
                s = names[(self.rr + i) % len(names)]
                p = self.pos.setdefault(s, kmax)
                if p <= kmax:
                    self.pos[s] = p + 1; self.rr = (self.rr + i + 1) % len(names)
                    f = "u" if s.endswith("@bookTicker") else "lastUpdateId"
                    return self._txt({"stream": s, "data": {f: Feed.seq(s, p) - self.offset, "b": "1", "a": "2"}})
            await asyncio.sleep(self.feed.period / 3)


class LagSession:
    """Per connection name: socket #1 = `first`, later sockets = `later` (kwargs for LagWS)."""

    def __init__(self, feed, first=None, later=None):
        self.feed, self.first, self.later, self.n = feed, first or {}, later or {}, {}

    def ws_connect(self, url, **kw):
        key = tuple(sorted(url.split("streams=")[1:]))
        self.n[key] = self.n.get(key, 0) + 1
        return LagWS(self.feed, url, **(self.first if self.n[key] == 1 else self.later))


HANDOFF = {"ws_handoff_min_s": 0.4, "ws_handoff_timeout_s": 2.5, "seq_catchup_timeout_s": 3}


def mk_live(d, sess, mode="continuous", **over):
    if mode == "continuous":
        cfg = prod_cont_cfg(d, **{**HANDOFF, **over}); C.validate(cfg)
    else:
        cfg = {**C.DEFAULTS, "data_dir": d, "enabled": True, "max_runtime_s": 60, **over}
    c = A.Collector(cfg)
    c.universe = UNI; c.build_streams(); c.session = sess
    return c


async def start_conns(c, names=("conn0-book",)):
    for name, streams in c._conn_streams():
        if name in names:
            w = c._new_conn(name, streams); w.task = asyncio.create_task(w.run()); c.conns.append(w)
    await asyncio.sleep(0.6)


async def finish(c, extra=()):
    if c.handoff_tasks:
        await asyncio.gather(*list(c.handoff_tasks), return_exceptions=True)
    for w in list(c.conns) + list(extra):
        await w.close()
    await asyncio.gather(*[w.task for w in list(c.conns) + list(extra)], return_exceptions=True)
    await asyncio.gather(*list(c.aux_tasks), return_exceptions=True)


class RealRotation(unittest.TestCase):
    def run_rot(self, first=None, later=None, mode="continuous", names=("conn0-book",), after=None, **over):
        async def go(d):
            c = mk_live(d, LagSession(Feed(), first, later), mode=mode, **over)
            await start_conns(c, names)
            olds = list(c.conns)
            evs = await asyncio.gather(*[c.rotate(o, "test_rotation") for o in olds])
            if after:
                await asyncio.sleep(after)
            await finish(c, olds)
            return c, olds, evs
        with tempfile.TemporaryDirectory() as d:
            c, olds, evs = asyncio.run(go(d))
            return c, olds, evs, drain(c)

    def test_trailing_replacement_hands_off_without_reset(self):
        c, olds, (ev,), recs = self.run_rot(later={"lag": 0.3})
        self.assertEqual(c.stats.get("seq_reset", 0), 0); self.assertEqual(c.stats["rejected"].get("seq_regression", 0), 0)
        self.assertGreaterEqual(c.stats["seq_stale"], 6 * 20)                    # > 20 older updates per stream
        self.assertTrue(ev["handoff"]["complete"], ev); self.assertEqual(ev["handoff"]["reason"], "caught_up")
        rot = lifes(recs, "ws_rotation")[0]
        self.assertEqual(rot["handoff"]["close_ms"], ev["handoff"]["close_ms"])
        self.assertFalse([k for k in rot["handoff"] if k.startswith("_")])
        self.assertEqual(ev["handoff"]["targets"], 6)
        h = lifes(recs, "ws_handoff")
        self.assertEqual(len(h), 1); h = h[0]
        self.assertEqual(h["audit_end"], "all_reached"); self.assertEqual(h["classes"], {"proven": 6})
        for s, x in h["streams"].items():
            self.assertLessEqual(x["new_first"], x["old_final"]); self.assertGreaterEqual(x["reach_seq"], x["old_final"])
            self.assertGreaterEqual(x["old_final"], x["target"])
        self.assertFalse(lifes(recs, "ws_disconnected")); self.assertTrue(olds[0]._closing)
        self.assertFalse(c.incidents.active())
        self.assertEqual(c.stats["handoff_classes"], {"proven": 6})

    def test_old_rule_counterfactual_resets_on_the_same_feed(self):
        c, _, _, recs = self.run_rot(later={"lag": 0.3}, mode="bounded", after=1.0)   # bounded: pre-1.5.0 rule
        self.assertGreaterEqual(c.stats.get("seq_reset", 0), 1)                  # the defect mechanism, reproduced

    def test_replacement_ahead_of_old(self):
        c, _, (ev,), recs = self.run_rot(first={"lag": 1.0}, later={"lag": 0.0})
        self.assertEqual(c.stats.get("seq_reset", 0), 0); self.assertTrue(ev["handoff"]["complete"])
        h = lifes(recs, "ws_handoff")[0]
        self.assertEqual(set(h["classes"]), {"ahead"})

    def test_both_connections_rotating_together(self):
        c, olds, evs, recs = self.run_rot(later={"lag": 0.3}, names=("conn0-book", "conn1-depth"))
        self.assertEqual(c.stats.get("seq_reset", 0), 0); self.assertEqual(c.stats["rejected"].get("seq_regression", 0), 0)
        self.assertTrue(all(e["handoff"]["complete"] for e in evs), evs)
        hs = {h["conn"]: h for h in lifes(recs, "ws_handoff")}
        self.assertEqual(hs["conn0-book"]["classes"], {"proven": 6}); self.assertEqual(hs["conn1-depth"]["classes"], {"proven": 6})

    def test_replacement_in_another_id_space_fails_closed_then_resets(self):
        c, olds, (ev,), recs = self.run_rot(later={"lag": 0.0, "offset": 5_000_000}, after=4.0)
        self.assertFalse(ev["handoff"]["complete"]); self.assertEqual(ev["handoff"]["reason"], "timeout")
        self.assertEqual(ev["handoff"]["pending"], 6)
        inc = {i["key"]: i for i in c.incidents.active()}
        self.assertEqual(inc["rotation_handoff_incomplete:conn0-book"]["severity"], "WARNING")
        self.assertEqual(c.stats["seq_reset_causes"], {"catchup_timeout": 6})     # genuine discontinuity: detected
        with mock.patch.object(c.writer, "status", lambda: {"beat_age_ms": 0, "durable_lag_ms": 0}):
            c._continuous_checks(A.now_ms())
        self.assertEqual({i["key"]: i["severity"] for i in c.incidents.active()}["seq_reset"], "DEGRADED")
        h = lifes(recs, "ws_handoff")[0]
        self.assertEqual(h["classes"], {"unresolved": 6})

    def test_incomplete_handoff_values_before_close_are_not_persisted(self):
        async def go(d):
            c = mk_live(d, LagSession(Feed(), {}, {"lag": 0.0, "offset": 5_000_000}))
            await start_conns(c)
            ev = await c.rotate(c.conns[0], "test_rotation")
            close_ms = ev["handoff"]["close_ms"]
            S = (close_ms // 2000 + 1) * 2000                                    # tier 0 and tier 2 boundary
            await asyncio.sleep(max(0.0, (S - A.now_ms()) / 1000) + 0.05)
            c.sample(S)
            await finish(c)
            return c, S
        with tempfile.TemporaryDirectory() as d:
            c, S = asyncio.run(go(d))
            recs = drain(c)
            self.assertFalse([r for r in recs if r["type"] == "book" and r["sample_ms"] == S])
            checked = [t for t in c.tracks.values() if t.kind == "book" and S % t.cadence == 0]
            self.assertGreaterEqual(len(checked), 5)
            for t in checked:
                self.assertEqual(t.gap["cause"] if t.gap else None, "awaiting_post_reconnect_data", t.name)

    def test_old_socket_server_closed_mid_handoff(self):
        c, olds, (ev,), recs = self.run_rot(first={"lag": 0.0, "die_after": 2.0}, later={"lag": 1.5})
        self.assertEqual(ev["handoff"]["reason"], "old_closed"); self.assertFalse(ev["handoff"]["complete"])
        self.assertTrue(lifes(recs, "ws_superseded_closed"))
        self.assertFalse(lifes(recs, "ws_disconnected"))                         # not a connection-down transition
        self.assertEqual(sum(1 for p in lifes(recs, "ws_connected") if p["conn"] == "conn0-book"), 2)  # old never reconnected
        self.assertEqual(c.stats.get("seq_reset", 0), 0)
        self.assertTrue(all(c.activity["conn0-book"].transitions[i][1] for i in range(len(c.activity["conn0-book"].transitions))))
        self.assertIn("rotation_handoff_incomplete:conn0-book", {i["key"] for i in c.incidents.active()})

    def test_reconnect_without_overlap_trailing_is_tolerated_and_gapped(self):
        async def go(d):
            c = mk_live(d, LagSession(Feed(), {"lag": 0.0, "die_after": 0.8}, {"lag": 0.4}))
            await start_conns(c)
            await asyncio.sleep(5.0)                                             # disconnect, backoff, reconnect
            await finish(c)
            return c
        with tempfile.TemporaryDirectory() as d:
            c = asyncio.run(go(d))
            recs = drain(c)
            self.assertTrue(lifes(recs, "ws_disconnected"))                      # a reconnect stays an explicit down
            self.assertEqual(len(lifes(recs, "ws_connected")), 2)
            self.assertEqual(c.stats.get("seq_reset", 0), 0)
            eps = [p["epoch"] for p in lifes(recs, "ws_connected")]
            self.assertEqual(len(set(eps)), len(eps))                            # every session is its own epoch

    def test_restart_fresh_collector_accepts_first_messages(self):
        with tempfile.TemporaryDirectory() as d:
            c2 = mk_live(d, None)
            o = Conn("conn0-book", []); c2.on_state(o, "connected")
            c2.on_message(o, {"stream": DOGE, "data": {"u": 5}}, 10)                # far below the previous run
            self.assertEqual(c2.tracks[DOGE].values.latest[2], 5)


# ============================================================================================ D: market guard
class MarketGuard(unittest.TestCase):
    def test_older_event_time_never_overwrites_newer_component(self):
        m = TK.MarketTrack(60000, "conn0-book", 10000, 30000, 120000, 86_400_000)
        m.on_array(1_000, [{"s": "BTCUSDT", "E": 500, "c": "2"}], stale_guard_ns=CATCHUP)
        m.on_array(2_000, [{"s": "BTCUSDT", "E": 400, "c": "1"}], stale_guard_ns=CATCHUP)       # trailing socket
        self.assertEqual(m.components["BTCUSDT"][1]["c"], "2"); self.assertEqual(m.stale_components, 1)
        m.on_array(3_000, [{"s": "BTCUSDT", "E": 600, "c": "3"}], stale_guard_ns=CATCHUP)
        self.assertEqual(m.components["BTCUSDT"][1]["c"], "3")
        m.on_array(3_000 + CATCHUP + 1, [{"s": "BTCUSDT", "E": 10, "c": "4"}], stale_guard_ns=CATCHUP)   # never stuck
        self.assertEqual(m.components["BTCUSDT"][1]["c"], "4")

    def test_bounded_mode_has_no_guard(self):
        m = TK.MarketTrack(60000, "conn0-book", 10000, 30000, 120000, 86_400_000)
        m.on_array(1_000, [{"s": "BTCUSDT", "E": 500, "c": "2"}])
        m.on_array(2_000, [{"s": "BTCUSDT", "E": 400, "c": "1"}])
        self.assertEqual(m.components["BTCUSDT"][1]["c"], "1")


class ConfigBounds(unittest.TestCase):
    def test_new_keys_validated_in_continuous_mode(self):
        with tempfile.TemporaryDirectory() as d:
            C.validate(prod_cont_cfg(d))
            for bad in ({"ws_handoff_min_s": -1}, {"ws_handoff_timeout_s": 1.0, "ws_handoff_min_s": 2.0},
                        {"ws_handoff_timeout_s": 61}, {"seq_catchup_timeout_s": 5}, {"seq_catchup_timeout_s": 301},
                        {"seq_catchup_timeout_s": 30.5}, {"ws_handoff_min_s": True}):
                with self.assertRaises(C.ConfigError, msg=str(bad)):
                    C.validate(prod_cont_cfg(d, **bad))

    def test_deployed_config_file_still_loads_with_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            json.dump({"enabled": True, "mode": "continuous", "profile": "recommended", "max_runtime_s": 0,
                       "data_dir": "/data", "dataset_id": "p2-forward-continuous-v1",
                       "host_label": "netcup-vps-arm64-shared-host"}, open(p, "w"))
            cfg = C.load(p)
            self.assertEqual((cfg["ws_handoff_min_s"], cfg["ws_handoff_timeout_s"], cfg["seq_catchup_timeout_s"]),
                             (2.0, 15.0, 30))


if __name__ == "__main__":
    unittest.main()
