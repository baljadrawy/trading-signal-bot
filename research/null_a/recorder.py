"""EvidenceRecorder — a fail-safe, non-blocking flight recorder.

Phase 1 (this module): capture signal evidence into a BOUNDED in-memory queue and flush
it asynchronously in batches via an injected sink. It must be:
  - a true no-op when disabled,
  - non-blocking and within a p95 < 5ms capture budget,
  - bounded in memory (overflow drops gracefully, counted),
  - impossible to crash the caller (every failure is buried).
It does NOT touch trading decisions, the DB, the health monitor, or RESEARCH_MODE.
"""
import logging
import time
from collections import deque

logger = logging.getLogger("evidence_recorder")


class RateLimiter:
    """Sliding 1-hour window. max_per_hour <= 0 => unlimited. Clock injectable for tests."""
    def __init__(self, max_per_hour: int = 0, clock=time.monotonic):
        self.max = max_per_hour
        self.clock = clock
        self._events = deque()

    def allow(self) -> bool:
        if self.max <= 0:
            return True
        now = self.clock()
        cutoff = now - 3600.0
        while self._events and self._events[0] < cutoff:
            self._events.popleft()
        if len(self._events) >= self.max:
            return False
        self._events.append(now)
        return True


class CaptureFilter:
    """Simple capture rules layer: symbol/timeframe/source allow-lists (empty = allow all)
    + a per-hour rate cap so a scanner burst can never turn the recorder into a load source."""
    def __init__(self, symbols=None, timeframes=None, sources=None,
                 max_per_hour: int = 0, clock=time.monotonic):
        self.symbols = set(symbols) if symbols else None
        self.timeframes = set(timeframes) if timeframes else None
        self.sources = set(sources) if sources else None
        self.rate = RateLimiter(max_per_hour, clock)

    def allow(self, symbol, timeframe, source) -> bool:
        if self.symbols is not None and symbol not in self.symbols:
            return False
        if self.timeframes is not None and timeframe not in self.timeframes:
            return False
        if self.sources is not None and source not in self.sources:
            return False
        return self.rate.allow()


class EvidenceRecorder:
    def __init__(self, sink, enabled: bool = False, max_queue: int = 10000,
                 batch_size: int = 100, flush_interval_s: float = 5.0,
                 flush_retry_count: int = 3, flush_backoff_ms: float = 50.0,
                 shutdown_flush_timeout_ms: float = 2000.0, capture_filter=None):
        self.sink = sink
        self.enabled = enabled
        self.capture_filter = capture_filter
        self.filtered = 0                      # intentional exclusions (NOT technical drops)
        self.max_queue = max_queue
        self.batch_size = batch_size
        self.flush_interval_s = flush_interval_s
        self.flush_retry_count = flush_retry_count
        self.flush_backoff_ms = flush_backoff_ms
        self.shutdown_flush_timeout_ms = shutdown_flush_timeout_ms
        self._q = deque()
        self._lat = deque(maxlen=2000)        # recent capture latencies (ms)
        self.captured = 0
        self.dropped = 0
        self.flushed = 0
        self.capture_errors = 0
        self.flush_failures = 0               # individual write attempt failures
        self.batches_attempted = 0
        self.batches_succeeded = 0
        self.last_flush_ms = 0.0
        self.pending_on_shutdown = 0

    # ---- hot path: must be fast and never raise on the caller's behalf ----
    def capture(self, **fields) -> bool:
        if not self.enabled:
            return False
        t0 = time.perf_counter()
        ok = False
        try:
            if self.capture_filter is not None and not self.capture_filter.allow(
                    fields.get("symbol"), fields.get("timeframe"), fields.get("source")):
                self.filtered += 1            # intentional exclusion, not a failure
            elif len(self._q) >= self.max_queue:
                self.dropped += 1
            else:
                fields["_captured_at"] = time.time()
                self._q.append(fields)
                self.captured += 1
                ok = True
        except Exception:
            self.capture_errors += 1
            logger.warning("evidence capture internal error", exc_info=True)
        finally:
            self._lat.append((time.perf_counter() - t0) * 1000.0)
        return ok

    def should_flush(self) -> bool:
        return len(self._q) >= self.batch_size

    # ---- async-friendly batch flush (off the hot path) ----
    def _write_with_retry(self, batch) -> bool:
        """Write a batch, retrying transient sink failures with short backoff. Records
        flush duration. Returns True iff the batch was persisted."""
        self.batches_attempted += 1
        attempts = self.flush_retry_count + 1
        t0 = time.perf_counter()
        ok = False
        for a in range(attempts):
            try:
                self.sink.write(batch)
                self.batches_succeeded += 1
                ok = True
                break
            except Exception:
                self.flush_failures += 1
                logger.warning("evidence flush attempt %d/%d failed", a + 1, attempts, exc_info=True)
                if a < attempts - 1 and self.flush_backoff_ms > 0:
                    time.sleep(self.flush_backoff_ms / 1000.0)
        self.last_flush_ms = (time.perf_counter() - t0) * 1000.0
        return ok

    def flush_now(self) -> int:
        if not self._q:
            return 0
        # PEEK (do not pop) so a failed write never loses records — they stay queued.
        import itertools
        n = min(self.batch_size, len(self._q))
        batch = list(itertools.islice(self._q, 0, n))
        if self._write_with_retry(batch):
            for _ in range(n):
                self._q.popleft()
            self.flushed += n
            return n
        return 0      # persistent failure: batch remains in the queue for a later attempt

    def shutdown(self, timeout_ms: float = None) -> int:
        """Drain remaining records within a deadline. Returns the count still pending
        (records that could not be flushed in time). Never hangs, never raises."""
        deadline = time.monotonic() + (timeout_ms or self.shutdown_flush_timeout_ms) / 1000.0
        try:
            while self._q and time.monotonic() < deadline:
                if self.flush_now() == 0:        # persistent failure within this attempt
                    if time.monotonic() >= deadline:
                        break
        except Exception:
            logger.warning("evidence shutdown flush error", exc_info=True)
        self.pending_on_shutdown = len(self._q)
        return self.pending_on_shutdown

    async def run_flusher(self):
        """Background loop: flush on the time trigger. Buries all errors."""
        import asyncio
        while True:
            try:
                await asyncio.sleep(self.flush_interval_s)
                while self._q:
                    if self.flush_now() == 0 and self._q:
                        break
            except asyncio.CancelledError:
                self.shutdown()                    # bounded drain of remaining records
                raise
            except Exception:
                logger.warning("evidence flusher loop error", exc_info=True)

    def telemetry(self) -> dict:
        attempts = self.captured + self.dropped + self.capture_errors
        p95 = 0.0
        if self._lat:
            s = sorted(self._lat)
            p95 = s[min(len(s) - 1, int(0.95 * len(s)))]
        return {
            "evidence_capture_success_rate": (self.captured / attempts) if attempts else 1.0,
            "evidence_capture_latency_ms_p95": float(p95),
            "evidence_queue_depth": len(self._q),
            "evidence_dropped_records": self.dropped,
            "evidence_flush_failures": self.flush_failures,
            "evidence_captured_total": self.captured,
            "evidence_flushed_total": self.flushed,
            "evidence_write_success_rate": (self.batches_succeeded / self.batches_attempted)
            if self.batches_attempted else 1.0,
            "evidence_flush_duration_ms": float(self.last_flush_ms),
            "evidence_pending_records_on_shutdown": self.pending_on_shutdown,
            "evidence_filtered_records": self.filtered,
        }


def maybe_capture(recorder, **fields) -> None:
    """Fail-safe wrapper for the signal hot path. NEVER raises into the caller."""
    if recorder is None or not getattr(recorder, "enabled", False):
        return
    try:
        recorder.capture(**fields)
    except Exception:
        logger.warning("Evidence capture failed", exc_info=True)


def capture_signal(recorder, signal: dict, source: str, model_version: str,
                   decision: str = "signal_generated") -> None:
    """Build evidence fields from a signal dict and capture them. Guarantees: it READS
    the signal (never mutates it) and NEVER raises into the caller. OHLCV is deferred
    (window not in scope at the hook) and explicitly tagged ohlcv_status='deferred'."""
    if recorder is None or not getattr(recorder, "enabled", False):
        return
    try:
        from uuid import uuid4
        maybe_capture(
            recorder,
            timestamp=time.time(),
            signal_id=uuid4().hex,
            source=source,
            symbol=signal.get("symbol"),
            timeframe=signal.get("timeframe"),
            features=dict(signal.get("features") or {}),
            confidence=signal.get("score"),
            signal_score=signal.get("total_score", signal.get("score")),
            market_regime=signal.get("macro_state") or signal.get("market_condition"),
            trade_type=signal.get("trade_type"),
            entry_decision=decision,
            model_version=model_version,
            ohlcv_status="deferred",
        )
    except Exception:
        logger.warning("capture_signal failed", exc_info=True)
