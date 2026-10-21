"""P2F obs: reconnect-flapping detector (pure, bounded state, no I/O).

`conn_recovery_failed` only measures a CONTINUOUS outage (its clock resets whenever data resumes), so a run of
short sessions that each deliver some data never reaches it (2026-10-21 13:34Z-16:42Z: 193 + 58 disconnects,
no CRITICAL). This detector counts ended sessions per connection in a sliding window and reports one episode at a
time: OPEN when the window count reaches `max_events`, CLEAR after `clear_s` without any ended session (and the
window count below the threshold). The threshold is a candidate for evaluation, not an approved production value.
"""
from __future__ import annotations

import collections


class FlapDetector:
    def __init__(self, window_s: float, max_events: int, clear_s: float):
        if window_s <= 0 or max_events < 2 or clear_s <= 0:
            raise ValueError("window_s > 0, max_events >= 2 and clear_s > 0 required")
        self.window_ms, self.max_events, self.clear_ms = int(window_s * 1000), int(max_events), int(clear_s * 1000)
        self._events = {}           # conn -> deque of end times (ms), bounded by max_events
        self.open = {}              # conn -> {"since_ms", "events"} while an episode is open

    def _window(self, conn: str, m: int):
        q = self._events.setdefault(conn, collections.deque(maxlen=self.max_events))
        while q and m - q[0] > self.window_ms:
            q.popleft()
        return q

    def record(self, conn: str, m: int):
        """One ended session at time m. Returns ("open", detail) once per episode, else None."""
        q = self._window(conn, m)
        q.append(m)
        ep = self.open.get(conn)
        if ep is not None:
            ep["events"] += 1; ep["last_ms"] = m
            return None
        if len(q) >= self.max_events:
            self.open[conn] = {"since_ms": q[0], "last_ms": m, "events": len(q)}
            return "open", {"conn": conn, "events_in_window": len(q), "window_s": self.window_ms // 1000,
                            "first_ms": q[0]}
        return None

    def tick(self, conn: str, m: int):
        """Periodic check. Returns ("clear", detail) once when an open episode has been quiet for clear_s."""
        ep = self.open.get(conn)
        if ep is None:
            return None
        q = self._window(conn, m)
        if m - ep["last_ms"] >= self.clear_ms and len(q) < self.max_events:
            del self.open[conn]
            return "clear", {"conn": conn, "episode_events": ep["events"], "since_ms": ep["since_ms"],
                             "last_ms": ep["last_ms"], "duration_ms": ep["last_ms"] - ep["since_ms"]}
        return None
