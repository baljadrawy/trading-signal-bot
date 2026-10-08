"""Fail-closed cumulative CPU guard (G1, G2, G4, G6 helpers). Pure logic with injected I/O so every fault is testable.

The guard watches ONE cgroup counter (the MI slice's cpu.stat usage_usec, which includes every descendant, live or
exited, while the slice exists). It never runs inside that slice.

Decisions per poll:
  * reading missing / unparseable / negative / decreasing          -> KILL (G2, fail closed)
  * gap since the last good poll > max_gap_s (guard starved/paused) -> KILL (G2)
  * used >= reservation - margin                                   -> KILL (G1)
  * jobs finished (done() true)                                    -> charge actual (G4)
After any KILL the final counter is read once more: readable -> charge it; unreadable -> charge the FULL reservation
and STOP (G4). The guard never re-starts anything and never raises the reservation.
"""
from __future__ import annotations

import os
import subprocess
import time

from . import MARGIN_CPU_S, MAX_POLL_GAP_S, POLL_S, SLICE


class GuardFault(Exception):
    pass


def read_usage_usec(cgroup_dir: str) -> int:
    """cpu.stat usage_usec of a cgroup; raises GuardFault on any problem (never returns a stale value)."""
    try:
        with open(os.path.join(cgroup_dir, "cpu.stat"), encoding="ascii") as fh:
            for line in fh:
                k, _, v = line.partition(" ")
                if k == "usage_usec":
                    u = int(v)
                    if u < 0:
                        raise GuardFault("negative usage")
                    return u
    except GuardFault:
        raise
    except Exception as e:
        raise GuardFault(f"cpu.stat unreadable: {type(e).__name__}: {e}")
    raise GuardFault("usage_usec missing")


def systemd_kill(unit: str = SLICE):
    """Real kill path: SIGKILL every process of the unit/slice, then stop it. Used only when explicitly wired."""
    subprocess.run(["systemctl", "--user", "kill", "--kill-whom=all", "--signal=SIGKILL", unit],
                   capture_output=True, timeout=20)
    subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True, timeout=30)


class Guard:
    def __init__(self, *, reader, killer, ledger, campaign: str, reservation_cpu_s: float,
                 margin_cpu_s: float = MARGIN_CPU_S, poll_s: float = POLL_S, max_gap_s: float = MAX_POLL_GAP_S,
                 clock=time.monotonic, sleep=time.sleep, done=lambda: False, log=lambda *a: None):
        if margin_cpu_s >= reservation_cpu_s:
            raise ValueError("reservation must exceed the safety margin")
        self.reader, self.killer, self.ledger = reader, killer, ledger
        self.campaign, self.reservation = campaign, float(reservation_cpu_s)
        self.limit = self.reservation - margin_cpu_s
        self.poll_s, self.max_gap_s, self.clock, self.sleep, self.done, self.log = poll_s, max_gap_s, clock, sleep, done, log
        self.baseline = self.last = self.last_t = None
        self.outcome = None
        self.stop_requested = None          # set from a signal handler (SIGTERM/SIGINT) -> KILL + charge

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        """Reserve first (G5), then take the baseline; a baseline fault cancels by charging nothing but the reserve."""
        self.ledger.reserve(self.campaign, self.reservation)
        try:
            self.baseline = self.last = self.reader()
        except Exception as e:
            self._finish("KILL", f"baseline_unreadable: {e}")
            return False
        self.last_t = self.clock()
        return True

    def used_cpu_s(self, u: int) -> float:
        return (u - self.baseline) / 1e6

    def step(self) -> str:
        """One poll. Returns CONTINUE, KILL or DONE (and finalizes on KILL / DONE)."""
        if self.stop_requested:
            return self._finish("KILL", f"stop_requested: {self.stop_requested}")
        now = self.clock()
        if now - self.last_t > self.max_gap_s:
            return self._finish("KILL", f"guard_gap {now - self.last_t:.2f}s > {self.max_gap_s}s")
        try:
            u = self.reader()
        except Exception as e:
            return self._finish("KILL", f"read_fault: {e}")
        if not isinstance(u, int) or isinstance(u, bool) or u < self.last:
            return self._finish("KILL", f"non_monotonic or invalid reading {u!r} < {self.last}")
        self.last, self.last_t = u, now
        used = self.used_cpu_s(u)
        if used >= self.limit:
            return self._finish("KILL", f"budget: used {used:.3f} >= limit {self.limit:.3f} CPU-s")
        if self.done():
            return self._finish("DONE", "jobs finished")
        return "CONTINUE"

    def run(self, max_polls: int | None = None) -> dict:
        n = 0
        while True:
            r = self.step()
            if r != "CONTINUE":
                return self.outcome
            n += 1
            if max_polls is not None and n >= max_polls:
                self._finish("KILL", "max_polls (wall-clock safeguard)")
                return self.outcome
            self.sleep(self.poll_s)

    # ------------------------------------------------------------------ finalize + charge (G4)
    def _finish(self, verdict: str, reason: str) -> str:
        if verdict == "KILL":
            try:
                self.killer()
            except Exception as e:                     # the kill itself failing is reported; budget still charged
                reason += f"; kill_error {type(e).__name__}: {e}"
        try:
            final = self.reader()
            if self.baseline is None or final < self.last:
                raise GuardFault("final reading unusable")
            actual, basis = self.used_cpu_s(final), "cgroup_usage_usec"
        except Exception:
            actual, basis = self.reservation, "full_reservation_unreadable"
        if basis == "cgroup_usage_usec" and actual > self.reservation:
            basis = "cgroup_usage_usec_OVER_RESERVATION"       # must never happen; surfaced, charged as measured
        self.ledger.charge(self.campaign, actual, basis)
        self.outcome = {"verdict": verdict, "reason": reason, "charged_cpu_s": actual, "basis": basis,
                        "reservation_cpu_s": self.reservation, "limit_cpu_s": self.limit,
                        "stop_campaign": verdict == "KILL" or basis != "cgroup_usage_usec"}
        self.log(self.outcome)
        return verdict
