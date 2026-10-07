"""Per-stream point-in-time sample-and-hold and stream state (G2-Repeat revision; F1, F2, F4, F19, F38, F40).

Sampling rule (SCHEMA.md "sample_semantics"): the value persisted for boundary S is the LATEST message received by
the collector at or before S, compared at nanosecond resolution (recv_ts_ns <= S * 10^6). A message received
after S (even by 1 ns) is never used for S.

Exact for any message rate, in O(boundaries) memory:
- `latest` is the newest message;
- when a message arrives at r, let B be the largest grid boundary strictly before r. If `latest.recv_ms <= B`, then
  `latest` is the newest message at or before B (and every boundary between latest.recv_ms and B), so `held` gets
  (B, latest);
- lookup(S): if latest.recv_ms <= S return latest; else return the first held entry with B >= S. Its value is
  re-checked to be <= S (no messages exist between it and B). Entries older than the hold window are pruned.
  If the proof is no longer available the result is EVICTED (made explicit as a `sampler_stall` gap, never
  guessed).
"""
from __future__ import annotations

import collections

NOT_YET_OBSERVING, SUBSCRIBING, OBSERVING, GAP_OPEN, DISCONNECTED, FAILED = (
    "NOT_YET_OBSERVING", "SUBSCRIBING", "OBSERVING", "GAP_OPEN", "DISCONNECTED", "FAILED")
DISCONNECT_CAUSES = ("ws_disconnect_reconnect", "banned_418")

OK, NONE, EVICTED = "ok", "none", "evicted"


class Held:
    """Latest-at-or-before-S lookup over a message sequence (see module doc). Items are tuples whose [0] is recv_ns;
    grid / hold / boundaries are given in ms and compared in ns."""

    def __init__(self, grid_ms: int, hold_ms: int):
        self.grid, self.hold = grid_ms * 1_000_000, hold_ms * 1_000_000
        self.latest = None
        self.first_ns = None
        self.held = collections.deque()          # (B_ns, item), B strictly increasing

    def push(self, item) -> None:
        r = item[0]
        if self.latest is not None:
            b = ((r - 1) // self.grid) * self.grid
            if self.latest[0] <= b and (not self.held or self.held[-1][0] < b):
                self.held.append((b, self.latest))
            while self.held and self.held[0][0] < r - self.hold:
                self.held.popleft()
        else:
            self.first_ns = r
        self.latest = item

    def at_or_before(self, s_ms: int):
        """(item, OK) | (None, NONE) when nothing was received at or before S | (None, EVICTED) when the proof
        for S is older than the hold window."""
        s = s_ms * 1_000_000
        if self.latest is None or s < self.first_ns:
            return None, NONE
        if self.latest[0] <= s:
            return self.latest, OK
        for b, it in self.held:
            if b >= s:
                return (it, OK) if it[0] <= s else (None, EVICTED)
        return None, EVICTED


class EpochSeq:
    """What ONE socket epoch (one WebSocket session) delivered for one stream: first / last sequence and receive time
    (accepted OR discarded messages), the current run of messages behind the accepted value, and divergence."""
    __slots__ = ("first", "first_ns", "last", "last_ns", "behind_since_ns", "behind_n", "diverged", "regress_n",
                 "stale_n")

    def __init__(self, seq: int, recv_ns: int):
        self.first, self.first_ns, self.last, self.last_ns = seq, recv_ns, None, None
        self.behind_since_ns, self.behind_n, self.diverged, self.regress_n, self.stale_n = None, 0, False, 0, 0


class SeqContinuity:
    """Per-stream sequence continuity across socket epochs (P2F rotation repair, collector >= 1.5.0, continuous mode).

    Binance semantics: bookTicker `u` and partial-depth `lastUpdateId` are per-symbol order-book update ids. They are
    monotonic but SPARSE (not every id is pushed), so a forward jump is normal and carries no gap information. ONE
    WebSocket session delivers a stream in exchange order (one TCP stream), but two sessions (rotation overlap,
    reconnect) have NO mutual ordering: a replacement session served by a slower gateway can trail the one it replaces.

    Invariant (replaces "20 consecutive older updates on the stream"):
      - accept a message iff its seq >= the accepted latest (hw); any epoch may advance hw;
      - seq < hw from an epoch whose OWN order is intact (seq >= that epoch's previous seq) is a STALE copy (overlap or
        catch-up duplicate): discarded, never a regression, never persisted. It is tolerated only within a bounded
        catch-up window: recv <= max(start of this epoch's behind-run, receive time of hw) + catchup. Beyond that the
        replacement did not reach the id space it replaces -> `seq_reset` (cause `catchup_timeout`): a genuine
        discontinuity, accepted VISIBLY (lifecycle + DEGRADED latched incident), never silent;
      - seq < the SAME epoch's previous seq is a genuine in-socket regression (`seq_regression`); after 20 of them in a
        row the new id space is accepted as an exchange-side reset (`seq_reset`, cause `in_socket_regression`, m5).
    `watch` (set by a rotation hand-off): first message of epoch `ep` reaching `target` (the old epoch's final seq)."""
    MAX_EPOCHS = 4

    def __init__(self):
        self.eps = {}                             # epoch -> EpochSeq
        self.watch = None                         # {"ep", "target", "hit": (seq, recv_ns) | None}

    def ep(self, epoch: int, seq: int, recv_ns: int) -> EpochSeq:
        st = self.eps.get(epoch)
        if st is None:
            st = self.eps[epoch] = EpochSeq(seq, recv_ns)
            if len(self.eps) > self.MAX_EPOCHS:   # bounded: drop the epoch that delivered least recently
                old = min((e for e in self.eps if e != epoch), key=lambda e: self.eps[e].last_ns or 0)
                del self.eps[old]
        return st


class StreamTrack:
    """bookTicker / partial-depth stream: held values + subscription + gap state."""

    def __init__(self, name: str, kind: str, symbol: str, tier: int, cadence: int, conn: str, stale_ms: int,
                 deadline_rel_ms: int, hold_ms: int, levels: int | None = None):
        self.name, self.kind, self.symbol, self.tier, self.cadence = name, kind, symbol, tier, cadence
        self.conn, self.stale_ms, self.deadline_rel_ms, self.levels = conn, stale_ms, deadline_rel_ms, levels
        self.key = f"{kind}|{symbol}"
        self.values = Held(1000, hold_ms)        # item = (recv_ns, data, seq)
        self.sub = "PENDING"                      # PENDING | SENT | ACKED | URL | FAILED | TIMEOUT
        self.sub_sent_ms = self.ack_ms = None
        self.ready_ms = None                      # receive time of the first valid observation
        self.first_sample_ms = None
        self.last_persisted_seq = None
        self.last_persisted_sample_ms = None
        self.gap = None                           # open gap: first/last missing boundary, count, causes
        self.never_ready_reported = False
        self.msgs = 0
        self.regress_run = 0
        self.seqc = SeqContinuity()               # continuous mode (on_seq); unused by the bounded path (on_msg)
        self.await_after_ns = None                # fail-closed hand-off: values received before this are not live

    # ---- messages ----
    def on_seq(self, recv_ns: int, data, seq: int, epoch: int, catchup_ns: int, reset_after: int = 20):
        """Continuous mode: epoch-aware sequence continuity (see SeqContinuity). Returns (result, info) where result
        is None | "first" (accepted), "seq_stale" (overlap / catch-up duplicate, discarded), "seq_regression"
        (in-socket regression, discarded) or "seq_reset" (accepted visibly); info is a dict for telemetry or None."""
        sc = self.seqc
        st = sc.ep(epoch, seq, recv_ns)
        latest = self.values.latest
        prev = st.last
        if latest is None or seq >= latest[2]:
            info = None
            if st.behind_n:
                info = {"caught_up": True, "behind_n": st.behind_n, "behind_ms": (recv_ns - st.behind_since_ns) // 1_000_000}
            st.behind_since_ns, st.behind_n, st.diverged, st.regress_n = None, 0, False, 0
            st.last, st.last_ns = seq, recv_ns
            self._watch(epoch, seq, recv_ns)
            if self.await_after_ns is not None and recv_ns >= self.await_after_ns:
                self.await_after_ns = None
            return self._accept(recv_ns, data, seq), info
        hw, hw_ns = latest[2], latest[0]
        st.last, st.last_ns = seq, recv_ns
        self._watch(epoch, seq, recv_ns)
        if st.behind_since_ns is None:
            st.behind_since_ns = recv_ns
        st.behind_n += 1
        info = None
        if prev is not None and seq < prev and not st.diverged:   # the SAME socket went backwards
            st.diverged = True
            info = {"first_in_socket_regression": True, "prev_seq": prev, "hw": hw}
        if st.diverged:
            st.regress_n += 1
            if st.regress_n < reset_after:
                return "seq_regression", info
            cause = "in_socket_regression"
        else:
            st.stale_n += 1
            if recv_ns <= max(st.behind_since_ns, hw_ns) + catchup_ns:
                return "seq_stale", None
            cause = "catchup_timeout"
        info = {"cause": cause, "hw": hw, "hw_recv_ns": hw_ns, "behind_n": st.behind_n,
                "behind_ms": (recv_ns - st.behind_since_ns) // 1_000_000, "regress_n": st.regress_n}
        st.behind_since_ns, st.behind_n, st.diverged, st.regress_n = None, 0, False, 0
        self.values.push((max(recv_ns, hw_ns), data, seq))     # the new id space, accepted visibly (m5)
        self.msgs += 1
        return "seq_reset", info

    def _watch(self, epoch: int, seq: int, recv_ns: int) -> None:
        w = self.seqc.watch
        if w is not None and w["hit"] is None and epoch == w["ep"] and seq >= w["target"]:
            w["hit"] = (seq, recv_ns)

    def _accept(self, recv_ns: int, data, seq: int):
        latest = self.values.latest
        if latest is not None and recv_ns < latest[0]:
            recv_ns = latest[0]                   # wall-clock step back: never reorder (counted by the caller)
        self.values.push((recv_ns, data, seq))
        self.msgs += 1
        if self.ready_ms is None:
            self.ready_ms = recv_ns // 1_000_000
            self.ready_ns = recv_ns
            return "first"
        return None

    def on_msg(self, recv_ns: int, data, seq: int, overlap: bool = False) -> str | None:
        """Bounded mode (and the pre-1.5.0 rule kept for it): 20 consecutive older messages = reset."""
        latest = self.values.latest
        if latest is not None and seq < latest[2]:
            if overlap:                           # P2-CR: rotation overlap (two sockets, one stream): an older copy is
                return "seq_regression"           # ignored and never counted towards an exchange-side reset
            self.regress_run += 1
            if self.regress_run < 20:
                return "seq_regression"
            self.regress_run = 0                  # persistent regression = exchange-side reset: accept, made visible
            self.values.push((max(recv_ns, latest[0]), data, seq))
            self.msgs += 1
            return "seq_reset"
        self.regress_run = 0
        if latest is not None and recv_ns < latest[0]:
            recv_ns = latest[0]                   # wall-clock step back: never reorder (counted by the caller)
        self.values.push((recv_ns, data, seq))
        self.msgs += 1
        if self.ready_ms is None:
            self.ready_ms = recv_ns // 1_000_000
            self.ready_ns = recv_ns
            return "first"
        return None

    ready_ns = None

    def last_recv_ms(self):
        return None if self.values.latest is None else self.values.latest[0] // 1_000_000

    # ---- state ----
    def state(self) -> str:
        if self.sub in ("FAILED", "TIMEOUT") or (self.ready_ms is None and self.never_ready_reported):
            return FAILED
        if self.ready_ms is None:
            return SUBSCRIBING if self.sub == "SENT" else NOT_YET_OBSERVING
        if self.gap is not None:
            return DISCONNECTED if self.gap["cause"] in DISCONNECT_CAUSES else GAP_OPEN
        return OBSERVING

    def missing(self, s: int, cause: str) -> None:
        g = self.gap
        if g is None:
            self.gap = {"first": s, "last": s, "n": 1, "cause": cause, "causes": {cause}}
        else:
            g["last"] = s; g["n"] += 1; g["causes"].add(cause)

    def close_gap(self, open_at_stop: bool = False) -> dict | None:
        g, self.gap = self.gap, None
        if g is None:
            return None
        return {"stream_key": self.key, "stream": self.name, "first_missing_ms": g["first"], "last_missing_ms": g["last"],
                "missing_samples": g["n"], "cadence_ms": self.cadence,
                "duration_ms": g["last"] - g["first"] + self.cadence, "cause": g["cause"],
                "causes": sorted(g["causes"]), "open_at_stop": open_at_stop,
                "start_ms": g["first"], "end_ms": g["last"] + self.cadence}


class MarketTrack(StreamTrack):
    """`!miniTicker@arr`: per-symbol component state; held snapshots at market-cadence boundaries."""

    def __init__(self, cadence: int, conn: str, stale_ms: int, deadline_rel_ms: int, hold_ms: int, max_age_ms: int):
        super().__init__("!miniTicker@arr", "market", "ALL", None, cadence, conn, stale_ms, deadline_rel_ms, hold_ms)
        self.key = "market|ALL"
        self.components = {}                      # symbol -> (recv_ns, obj)
        self.snap = Held(cadence, max(hold_ms, 3 * cadence))   # item = (newest_recv_ns, snapshot dict | None=current)
        self.max_age_ms = max_age_ms
        self.newest = None                        # newest component recv_ns
        self.stale_components = 0                 # continuous: older-E copies not applied (trailing socket)

    def on_array(self, recv_ns: int, arr: list, stale_guard_ns: int | None = None) -> str | None:
        """stale_guard_ns (continuous mode, collector >= 1.5.0): a component whose event time `E` is OLDER than the
        held component's is a copy from a trailing socket (rotation overlap / catch-up) and never overwrites the newer
        one, unless the held component is older than the guard window (then the older E is accepted: never stuck)."""
        r = recv_ns if self.newest is None else max(recv_ns, self.newest)
        sn = self.snap
        if sn.latest is not None:
            b = ((r - 1) // sn.grid) * sn.grid
            if sn.latest[0] <= b and (not sn.held or sn.held[-1][0] < b):
                sn.held.append((b, (sn.latest[0], dict(self.components))))   # state as of the boundary
            while sn.held and sn.held[0][0] < r - sn.hold:
                sn.held.popleft()
        n = 0
        for t in arr:
            s = t.get("s") if isinstance(t, dict) else None
            if isinstance(s, str) and s.endswith("USDT"):
                if stale_guard_ns is not None:
                    cur = self.components.get(s)
                    e_new, e_cur = t.get("E"), (cur[1].get("E") if cur is not None else None)
                    if isinstance(e_new, int) and isinstance(e_cur, int) and e_new < e_cur and r - cur[0] <= stale_guard_ns:
                        self.stale_components += 1
                        continue
                self.components[s] = (r, t); n += 1
        if not n:
            return None
        if sn.latest is None:
            sn.first_ns = r
        sn.latest = (r, None)
        self.newest = r
        self.msgs += 1
        if self.ready_ms is None:
            self.ready_ms = r // 1_000_000
            self.ready_ns = r
            return "first"
        return None

    def components_at(self, s_ms: int):
        sn, s = self.snap, s_ms * 1_000_000
        if sn.latest is None or s < sn.first_ns:
            return None, NONE
        if sn.latest[0] <= s:
            return self.components, OK
        for b, (newest, comp) in sn.held:
            if b >= s:
                return (comp, OK) if newest <= s else (None, EVICTED)
        return None, EVICTED

    def last_recv_ms(self):
        return None if self.newest is None else self.newest // 1_000_000
