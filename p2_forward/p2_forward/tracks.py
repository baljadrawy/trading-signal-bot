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

    # ---- messages ----
    def on_msg(self, recv_ns: int, data, seq: int) -> str | None:
        latest = self.values.latest
        if latest is not None and seq < latest[2]:
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

    def on_array(self, recv_ns: int, arr: list) -> str | None:
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
