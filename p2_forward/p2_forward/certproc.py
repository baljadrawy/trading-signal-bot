"""G3-F4: certification in a separate worker PROCESS (own interpreter, own GIL and GC), same container cgroup.

The filesystem lifecycle (.pending -> .certifying -> certified) stays the authoritative, crash-safe handoff; the
worker reuses writer.certify() unchanged. Shared state with the collector is LOCK-FREE (review F1): plain shared
memory values (no multiprocessing locks, conditions or events) plus a one-way non-blocking wake-up pipe, so a worker
that dies at ANY instant (crash, SIGKILL, OOM kill) can never leave a lock or condition that blocks the collector's
event loop or writer thread. The collector never certifies; it supervises (status/health/restart/drain).

Counters (failures, quarantines, promotions) are mirrored to the collector as DELTAS and survive worker restarts;
a (re)started worker completes any manifest entry its predecessor left missing before it reports ready.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import signal
import time

CTX = mp.get_context("spawn")                      # no fork of a threaded process; child imports cleanly


def _rv(typecode, value=0):
    return CTX.Value(typecode, value, lock=False)  # raw shared memory: nothing a dying child could hold


def read(v):
    """Consistent read of a raw shared value or char array (re-read until two reads agree; never blocks)."""
    a = v.value
    for _ in range(5):
        b = v.value
        if a == b:
            return a
        a = b
    return a


def _wait(conn, timeout) -> bool:
    """Child: sleep until a wake-up byte or the timeout (poll: no select() fd limit). False = EOF = parent gone."""
    if conn.poll(timeout):
        try:
            return bool(os.read(conn.fileno(), 4096))
        except OSError:
            return False
    return True


def _worker(base, boot_id, ppid, rr, beat, busy, failures, quarantined, promoted, last_ms, max_ms, stop, wake, slow_s,
            crash, ready, err, inject):
    # G3-F4-D1: SIGTERM must NOT be ignored (multiprocessing's exit handling terminates leftover children with
    # SIGTERM then joins; an ignoring child hangs the parent forever). Graceful shutdown = the stop flag (drain).
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        if inject[0] == 1:                                        # test: exception before readiness
            raise RuntimeError("injected init failure")
        if inject[0] == 2:                                        # test: exit before readiness
            os._exit(7)
        if inject[0] == 3:                                        # test: slow initialization (alive, not ready)
            time.sleep(2.0)
        _loop(base, boot_id, ppid, rr, beat, busy, failures, quarantined, promoted, last_ms, max_ms, stop, wake,
              slow_s, crash, ready, inject)
    except BaseException:                                         # never silent: traceback to the parent
        import traceback
        err.value = traceback.format_exc().encode()[-4000:]
        raise


def _loop(base, boot_id, ppid, rr, beat, busy, failures, quarantined, promoted, last_ms, max_ms, stop, wake, slow_s,
          crash, ready, inject):
    from . import writer as W
    stats = W.new_stats()

    def hb():
        beat.value = time.time_ns()

    def publish():
        failures.value = stats["certification_failures"]; quarantined.value = stats["segments_quarantined"]
        promoted.value = stats["segments_promoted"]
        last_ms.value = stats.get("certify_last_ms") or 0; max_ms.value = stats.get("certify_max_ms") or 0

    def run_record():
        return read(rr).decode() or None

    if os.getppid() != ppid:                                      # parent gone before we started
        return
    W.complete_manifests(base, boot_id, stats, run_record())      # predecessor died after promotion: finish it
    publish()
    hb(); ready.value = 1                                         # explicit readiness after initialization
    while not stop.value:
        if os.getppid() != ppid:                                  # parent died: exit (filesystem state recovers)
            return
        hb()
        st = W.scan_lifecycle(base)
        for p in sorted(st["pending"] + st["certifying"]):
            if os.getppid() != ppid:
                return
            cp = p if p.endswith(W.CERTIFYING) else p[: -len(W.PENDING)] + W.CERTIFYING
            try:
                if p.endswith(W.PENDING):
                    os.rename(p, cp)
                busy.value = time.time_ns()
                if crash.value:
                    os._exit(3)                                   # test: abrupt certifier death mid-certification
                if inject[1]:                                     # test: CPU-heavy pure-Python work (GIL proof)
                    end = time.monotonic() + inject[1] / 1000.0; x = 0
                    while time.monotonic() < end:
                        for i in range(20000):
                            x += i * i
                        hb()
                if slow_s.value:
                    end = time.monotonic() + slow_s.value
                    while time.monotonic() < end:
                        hb(); time.sleep(0.2)
                    slow_s.value = 0.0
                W.certify(base, cp, stats, boot_id, run_record(), progress=hb, throttle=True)
            except OSError as e:
                stats["certification_failures"] += 1
                stats["last_certify_error"] = f"{type(e).__name__}: {e}"[:200]
            finally:
                busy.value = 0
            publish()
            hb()
        if not _wait(wake, 1.0):
            return                                                # wake pipe EOF: the parent is gone


class ProcessCertifier:
    """Same interface as writer.Certifier (thread), backed by a spawned worker process."""

    def __init__(self, base: str, boot_id: str, stats: dict, run_record_ref):
        self.base, self.boot_id, self.stats, self.run_record_ref = base, boot_id, stats, run_record_ref
        self._beat, self._busy = _rv("q", 0), _rv("q", 0)             # beat 0 until the CHILD publishes one
        self._fail, self._quar, self._prom = _rv("q", 0), _rv("q", 0), _rv("q", 0)
        self._last, self._max = _rv("q", 0), _rv("q", 0)
        self._seen = {"fail": 0, "quar": 0, "prom": 0}                 # child counters already mirrored (deltas)
        self._rr = CTX.Array("c", 1024, lock=False)
        self._ready, self._err = _rv("b", 0), CTX.Array("c", 4096, lock=False)
        self.inject = CTX.Array("q", [0, 0], lock=False)              # tests only: [init_mode, burn_ms]
        self._stop = _rv("b", 0)
        self._wake_r, self._wake_w = CTX.Pipe(duplex=False)
        os.set_blocking(self._wake_w.fileno(), False)                 # a wake-up never blocks the caller
        self.slow_s, self.crash = _rv("d", 0.0), _rv("b", 0)
        self.proc = CTX.Process(target=_worker, name="segment-certifier",
                                args=(base, boot_id, os.getpid(), self._rr, self._beat, self._busy, self._fail,
                                      self._quar, self._prom, self._last, self._max, self._stop, self._wake_r,
                                      self.slow_s, self.crash, self._ready, self._err, self.inject),
                                daemon=True)
        self.slow_test_hook = None                                 # (thread-mode API compatibility; unused)

    def _poke(self) -> None:
        """Non-blocking wake-up: a full pipe (dead or busy worker) or a closed pipe is ignored, never waited on."""
        try:
            os.write(self._wake_w.fileno(), b"\0")
        except (BlockingIOError, BrokenPipeError, OSError):
            pass

    # ---- thread-like API used by SegmentWriter / Collector ----
    def start(self):
        self._set_rr(); self.start_mono = time.monotonic(); self.proc.start()

    @property
    def ready(self) -> bool:
        return bool(read(self._ready))

    def wait_ready(self, timeout_s: float) -> bool:
        """Bounded readiness: True only when the child itself signalled ready."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            if read(self._ready):
                return True
            if self.proc.exitcode is not None:
                return False
            time.sleep(0.02)
        return bool(read(self._ready))

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
        return read(self._beat)

    @property
    def busy_since_ns(self):
        return read(self._busy) or None

    def _set_rr(self):
        """Publish the run-record path (written only when it changes; the child reads it consistently)."""
        r = (self.run_record_ref() or "").encode()[:1023]
        if read(self._rr) != r:
            self._rr.value = r

    def set_run_record(self) -> None:
        """Called as soon as the run record exists, before any segment that should carry it can be certified."""
        self._set_rr(); self._poke()

    def _sync_stats(self):
        """Mirror the child's counters into the collector's stats as deltas (correct across restarts)."""
        for key, v, stat in (("fail", self._fail, "certification_failures"), ("quar", self._quar, "segments_quarantined"),
                             ("prom", self._prom, "segments_promoted_by_certifier")):
            cur = read(v)
            if cur > self._seen[key]:
                self.stats[stat] = self.stats.get(stat, 0) + cur - self._seen[key]
                self._seen[key] = cur
        mx = read(self._max)
        if mx:
            self.stats["certify_max_ms"] = max(self.stats.get("certify_max_ms") or 0, mx)
            self.stats["certify_last_ms"] = read(self._last)

    def submit(self, path: str) -> None:
        self._set_rr(); self._poke()

    def pending(self) -> list:
        from . import writer as W
        st = W.scan_lifecycle(self.base)
        return st["pending"] + st["certifying"]

    def status(self) -> dict:
        self._sync_stats()
        now = time.time_ns()
        beat = read(self._beat)
        age = None if not beat else (now - beat) // 1_000_000
        try:
            pend = self.pending()
        except OSError:
            return {"alive": self.is_alive(), "fatal": self.fatal, "beat_age_ms": age, "ready": self.ready,
                    "pending": None, "oldest_pending_age_ms": None, "scan_error": True, "busy_ms": None,
                    "last_ms": None, "max_ms": None, "failures": self.stats["certification_failures"],
                    "certified": read(self._prom), "pid": self.proc.pid, "mode": "process"}
        ages = []
        for p in pend:
            try:
                ages.append((now - os.stat(p).st_mtime_ns) // 1_000_000)
            except OSError:
                pass
        b = self.busy_since_ns
        return {"alive": self.is_alive(), "fatal": self.fatal, "beat_age_ms": age, "ready": self.ready,
                "pending": len(pend), "oldest_pending_age_ms": max(ages, default=0),
                "busy_ms": None if b is None else (now - b) // 1_000_000, "last_ms": read(self._last) or None,
                "max_ms": read(self._max) or None, "failures": self.stats["certification_failures"],
                "certified": read(self._prom), "pid": self.proc.pid, "mode": "process"}

    def drain(self, timeout_s: float) -> bool:
        """Shutdown: True only if the worker certified everything, then exited CLEANLY (exit code 0) with nothing
        pending. Bounded by timeout_s whatever the worker does (alive, stuck, or dead at any instant). A worker that
        died abnormally can never yield True (it may have died between promotion and the manifest append)."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end and self.is_alive():
            if not self.pending() and self.busy_since_ns is None:
                break
            self._poke(); time.sleep(0.2)
        self._stop.value = 1; self._poke()
        self.proc.join(max(0.0, end - time.monotonic()))
        self._sync_stats()
        if self.is_alive() or self.proc.exitcode != 0:
            return False
        return not self.pending()

    def stop(self) -> None:
        self._stop.value = 1; self._poke()

    def join(self, timeout=None) -> None:
        self.proc.join(timeout)
