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


class EvidenceRecorder:
    def __init__(self, sink, enabled: bool = False, max_queue: int = 10000,
                 batch_size: int = 100, flush_interval_s: float = 5.0):
        self.sink = sink
        self.enabled = enabled
        self.max_queue = max_queue
        self.batch_size = batch_size
        self.flush_interval_s = flush_interval_s
        self._q = deque()
        self._lat = deque(maxlen=2000)        # recent capture latencies (ms)
        self.captured = 0
        self.dropped = 0
        self.flushed = 0
        self.capture_errors = 0
        self.flush_failures = 0

    # ---- hot path: must be fast and never raise on the caller's behalf ----
    def capture(self, **fields) -> bool:
        if not self.enabled:
            return False
        t0 = time.perf_counter()
        ok = False
        try:
            if len(self._q) >= self.max_queue:
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
    def flush_now(self) -> int:
        batch = []
        while self._q and len(batch) < self.batch_size:
            batch.append(self._q.popleft())
        if not batch:
            return 0
        try:
            self.sink.write(batch)
            self.flushed += len(batch)
            return len(batch)
        except Exception:
            self.flush_failures += 1
            logger.warning("evidence flush failed (batch dropped)", exc_info=True)
            return 0

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
                while self._q:                     # drain fully on shutdown (not one batch)
                    if self.flush_now() == 0:
                        break
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
