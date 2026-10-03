"""G3-F4: certification in a separate worker PROCESS (own interpreter, own GIL and GC), same container cgroup.

The filesystem lifecycle (.pending -> .certifying -> certified) stays the authoritative, crash-safe handoff; the
worker reuses writer.certify() unchanged. Shared state with the collector: a few multiprocessing Values only
(heartbeat, busy-since, counters). The collector never certifies; it supervises (status/health/restart/drain).
"""
from __future__ import annotations

import multiprocessing as mp
import os
import signal
import time

CTX = mp.get_context("spawn")                      # no fork of a threaded process; child imports cleanly


def _worker(base, boot_id, rr, beat, busy, failures, promoted, last_ms, max_ms, stop, nudge, slow_s, crash, ready, err):
    # G3-F4-D1: SIGTERM must NOT be ignored (multiprocessing's exit handling terminates leftover children with
    # SIGTERM then joins; an ignoring child hangs the parent forever). Graceful shutdown = the stop event (drain).
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        _loop(base, boot_id, rr, beat, busy, failures, promoted, last_ms, max_ms, stop, nudge, slow_s, crash, ready)
    except BaseException:                                         # never silent: traceback to the parent
        import traceback
        err.value = traceback.format_exc().encode()[-4000:]
        raise


def _loop(base, boot_id, rr, beat, busy, failures, promoted, last_ms, max_ms, stop, nudge, slow_s, crash, ready):
    from . import writer as W
    stats = W.new_stats()
    parent = os.getppid()
    def hb():
        beat.value = time.time_ns()
    hb(); ready.value = 1                                         # explicit readiness after initialization
    while not stop.is_set():
        if os.getppid() != parent:                                # parent died: exit (filesystem state recovers)
            return
        hb()
        st = W.scan_lifecycle(base)
        for p in sorted(st["pending"] + st["certifying"]):
            cp = p if p.endswith(W.CERTIFYING) else p[: -len(W.PENDING)] + W.CERTIFYING
            try:
                if p.endswith(W.PENDING):
                    os.rename(p, cp)
                busy.value = time.time_ns()
                if crash.value:
                    os._exit(3)                                   # test: abrupt certifier death mid-certification
                if slow_s.value:
                    end = time.monotonic() + slow_s.value
                    while time.monotonic() < end:
                        hb(); time.sleep(0.2)
                    slow_s.value = 0.0
                run_record = rr.value.decode() or None
                W.certify(base, cp, stats, boot_id, run_record, progress=hb, throttle=True)
            except OSError as e:
                stats["certification_failures"] += 1
                stats["last_certify_error"] = f"{type(e).__name__}: {e}"[:200]
            finally:
                busy.value = 0
            failures.value = stats["certification_failures"]; promoted.value = stats["segments_promoted"]
            last_ms.value = stats.get("certify_last_ms") or 0; max_ms.value = stats.get("certify_max_ms") or 0
            hb()
        nudge.wait(1.0); nudge.clear()


class ProcessCertifier:
    """Same interface as writer.Certifier (thread), backed by a spawned worker process."""

    def __init__(self, base: str, boot_id: str, stats: dict, run_record_ref):
        self.base, self.boot_id, self.stats, self.run_record_ref = base, boot_id, stats, run_record_ref
        V = CTX.Value
        self._beat, self._busy = V("q", 0), V("q", 0)             # beat 0 until the CHILD publishes one
        self._fail, self._prom, self._last, self._max = V("q", 0), V("q", 0), V("q", 0), V("q", 0)
        self._rr = CTX.Array("c", 1024)
        self._ready, self._err = V("b", 0), CTX.Array("c", 4096)
        self._stop, self._nudge = CTX.Event(), CTX.Event()
        self.slow_s, self.crash = V("d", 0.0), V("b", 0)
        self.proc = CTX.Process(target=_worker, name="segment-certifier",
                                args=(base, boot_id, self._rr, self._beat, self._busy, self._fail, self._prom,
                                      self._last, self._max, self._stop, self._nudge, self.slow_s, self.crash,
                                      self._ready, self._err),
                                daemon=True)
        self.slow_test_hook = None                                 # (thread-mode API compatibility; unused)

    # ---- thread-like API used by SegmentWriter / Collector ----
    def start(self):
        self._set_rr(); self.start_mono = time.monotonic(); self.proc.start()

    @property
    def ready(self) -> bool:
        return bool(self._ready.value)

    def wait_ready(self, timeout_s: float) -> bool:
        """Bounded readiness: True only when the child itself signalled ready."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            if self._ready.value:
                return True
            if self.proc.exitcode is not None:
                return False
            time.sleep(0.02)
        return bool(self._ready.value)

    @property
    def ident(self):
        return self.proc.pid

    def is_alive(self) -> bool:
        return self.proc.is_alive()

    @property
    def fatal(self):
        c = self.proc.exitcode
        if c in (None, 0):
            return None
        tb = self._err.value.decode(errors="replace")
        return f"certifier_process_exitcode={c}" + (f" | {tb[-500:]}" if tb else "")

    @property
    def beat_ns(self):
        return self._beat.value

    @property
    def busy_since_ns(self):
        return self._busy.value or None

    def _set_rr(self):
        r = (self.run_record_ref() or "").encode()[:1023]
        self._rr.value = r

    def _sync_stats(self):
        self.stats["certification_failures"] = max(self.stats["certification_failures"], self._fail.value)
        if self._max.value:
            self.stats["certify_max_ms"] = max(self.stats.get("certify_max_ms") or 0, self._max.value)
            self.stats["certify_last_ms"] = self._last.value
        self.stats["segments_promoted_by_certifier"] = self._prom.value

    def submit(self, path: str) -> None:
        self._set_rr(); self._nudge.set()

    def pending(self) -> list:
        from . import writer as W
        st = W.scan_lifecycle(self.base)
        return st["pending"] + st["certifying"]

    def status(self) -> dict:
        self._sync_stats()
        now = time.time_ns()
        try:
            pend = self.pending()
        except OSError:
            return {"alive": self.is_alive(), "fatal": self.fatal, "beat_age_ms": None if not self._beat.value else (now - self._beat.value) // 1_000_000, "ready": self.ready,
                    "pending": None, "oldest_pending_age_ms": None, "scan_error": True, "busy_ms": None,
                    "last_ms": None, "max_ms": None, "failures": self.stats["certification_failures"],
                    "certified": self._prom.value, "pid": self.proc.pid, "mode": "process"}
        ages = []
        for p in pend:
            try:
                ages.append((now - os.stat(p).st_mtime_ns) // 1_000_000)
            except OSError:
                pass
        b = self.busy_since_ns
        return {"alive": self.is_alive(), "fatal": self.fatal, "beat_age_ms": None if not self._beat.value else (now - self._beat.value) // 1_000_000, "ready": self.ready,
                "pending": len(pend), "oldest_pending_age_ms": max(ages, default=0),
                "busy_ms": None if b is None else (now - b) // 1_000_000, "last_ms": self._last.value or None,
                "max_ms": self._max.value or None, "failures": self.stats["certification_failures"],
                "certified": self._prom.value, "pid": self.proc.pid, "mode": "process"}

    def drain(self, timeout_s: float) -> bool:
        """Shutdown: True only if the worker certified everything, then exited (joined) with nothing pending."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end and self.is_alive():
            if not self.pending() and self.busy_since_ns is None:
                break
            self._nudge.set(); time.sleep(0.2)
        self._stop.set(); self._nudge.set()
        self.proc.join(max(0.0, end - time.monotonic()))
        self._sync_stats()
        if self.is_alive():
            return False
        return not self.pending()

    def stop(self) -> None:
        self._stop.set(); self._nudge.set()

    def join(self, timeout=None) -> None:
        self.proc.join(timeout)
