"""Rate, backoff, disk and clock guards (pure logic; time injectable for tests)."""
from __future__ import annotations

import collections
import random
import time


class RateGuard:
    """Own REST budget (sliding 60 s) + yielding to the IP-wide used weight reported by Binance.

    - own budget: never exceed `budget` weight per rolling minute;
    - observed IP weight >= defer: only urgent calls; >= pause: no REST for 60 s;
    - HTTP 429: no REST for max(300 s, 2 x Retry-After);
    - HTTP 418: BANNED -> all Binance activity stops for Retry-After + 600 s.
    """

    def __init__(self, budget=300, defer=2400, pause=3600, clock=time.monotonic):
        self.budget, self.defer, self.pause, self.clock = budget, defer, pause, clock
        self.window = collections.deque()
        self.observed = 0
        self.rest_blocked_until = 0.0
        self.banned_until = 0.0
        self.events = collections.Counter()
        self.ban_callbacks = []            # F23: called on 418 so every WS connection closes immediately

    def own_used(self) -> int:
        now = self.clock()
        while self.window and now - self.window[0][0] > 60:
            self.window.popleft()
        return sum(w for _, w in self.window)

    def allow(self, weight: int, urgent: bool = False) -> tuple:
        now = self.clock()
        if now < self.banned_until:
            return False, "banned_418"
        if now < self.rest_blocked_until:
            return False, "rest_blocked"
        if self.observed >= self.pause:
            self.rest_blocked_until = now + 60; self.events["pause_60pct"] += 1
            return False, "paused_ip_weight"
        if self.observed >= self.defer and not urgent:
            self.events["defer_40pct"] += 1
            return False, "deferred_ip_weight"
        if self.own_used() + weight > self.budget:
            self.events["own_budget"] += 1
            return False, "own_budget"
        self.window.append((now, weight))
        return True, "ok"

    def observe_header(self, used_weight) -> None:
        try:
            self.observed = int(used_weight)
        except (TypeError, ValueError):
            pass

    def on_429(self, retry_after) -> None:
        ra = _num(retry_after, 60)
        self.rest_blocked_until = self.clock() + max(300.0, 2 * ra); self.events["http_429"] += 1

    def on_418(self, retry_after) -> None:
        ra = _num(retry_after, 120)
        self.banned_until = self.clock() + ra + 600; self.events["http_418"] += 1
        for cb in list(self.ban_callbacks):
            cb()

    def banned(self) -> bool:
        return self.clock() < self.banned_until


def _num(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


class Backoff:
    """Exponential 1 s -> 60 s, +-30 % jitter; <= 10 attempts / 5 min; 5 consecutive failures -> 15 min cooldown."""

    def __init__(self, clock=time.monotonic, rng=random.random):
        self.clock, self.rng = clock, rng
        self.failures = 0
        self.attempts = collections.deque()

    def next_delay(self) -> float:
        now = self.clock()
        while self.attempts and now - self.attempts[0] > 300:
            self.attempts.popleft()
        if self.failures >= 5:
            base = 900.0
        else:
            base = min(60.0, 2.0 ** self.failures)
        delay = base * (0.7 + 0.6 * self.rng())
        if len(self.attempts) >= 10:
            delay = max(delay, 300 - (now - self.attempts[0]))
        return delay

    def attempt(self) -> None:
        self.attempts.append(self.clock())

    def failed(self) -> None:
        self.failures += 1

    def succeeded(self) -> None:
        self.failures = 0


class DiskGuard:
    """WARN when host free < warn_gb; HARD_STOP when free < stop_gb or collector dir >= dir_stop_gb. Never deletes."""

    def __init__(self, warn_gb=100, stop_gb=60, dir_stop_gb=150):
        self.warn, self.stop, self.dir_stop = warn_gb * 1e9, stop_gb * 1e9, dir_stop_gb * 1e9

    def state(self, free_bytes: float, dir_bytes: float) -> str:
        if free_bytes < self.stop or dir_bytes >= self.dir_stop:
            return "HARD_STOP"
        if free_bytes < self.warn:
            return "WARN"
        return "OK"


class ClockGuard:
    """Host-vs-exchange clock check (F5 / R17). Method `min_rtt_of_3_midpoint_v1`: of N probes (server, t0, t1)
    keep the minimum-RTT one; skew = server - (t0 + t1) / 2; uncertainty = rtt / 2 (the server stamp can lie
    anywhere inside the round trip). The state uses |skew| - uncertainty, so RTT asymmetry is never reported as
    host skew. Records are flagged clock_suspect only when CRITICAL; timestamps are never rewritten."""

    def __init__(self, warn_ms=500, crit_ms=2000, clock=time.monotonic):
        self.warn, self.crit, self.clock = warn_ms, crit_ms, clock
        self.last_skew_ms = None
        self.uncertainty_ms = None
        self.rtt_ms = None
        self.state = "UNKNOWN"
        self.last_ok_mono = None

    def update_samples(self, probes: list) -> str:
        good = [(s, t0, t1) for s, t0, t1 in probes if t1 >= t0]
        if not good:
            return self.state
        s, t0, t1 = min(good, key=lambda p: (p[2] - p[1], p[1]))
        self.rtt_ms = t1 - t0
        self.last_skew_ms = s - (t0 + t1) / 2.0
        self.uncertainty_ms = self.rtt_ms / 2.0
        excess = max(0.0, abs(self.last_skew_ms) - self.uncertainty_ms)
        self.state = "CRITICAL" if excess > self.crit else ("WARN" if excess > self.warn else "OK")
        self.last_ok_mono = self.clock()
        return self.state

    def update(self, server_ms: int, t0_ms: float, t1_ms: float) -> str:
        return self.update_samples([(server_ms, t0_ms, t1_ms)])

    def age_s(self):
        return None if self.last_ok_mono is None else self.clock() - self.last_ok_mono

    def suspect(self) -> bool:
        return self.state == "CRITICAL"
