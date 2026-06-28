"""Resilience hardening: the flight recorder must not LIE — no silent data loss, a
bounded graceful shutdown that drains remaining records, retry+backoff on transient sink
failures, honest pending-on-shutdown count, and an absolute evidence path at boot.
"""
import sys, os; sys.path.insert(0, '.')
from research.null_a.recorder import EvidenceRecorder
from research.null_a.sinks import JsonlSink, ListSink


class FlakySink:
    """Fails the first `fail_times` write calls, then succeeds."""
    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0
        self.records = []

    def write(self, batch):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise IOError("transient")
        self.records.extend(batch)


class DeadSink:
    def write(self, batch):
        raise IOError("permanent")


def _f(i=0):
    return dict(signal_id=f"s{i}", timestamp=1750000000.0 + i, symbol="BTCUSDT",
                features={"rsi": 30.0})


def test_shutdown_flushes_remaining_records():
    sink = ListSink()
    r = EvidenceRecorder(sink=sink, enabled=True, batch_size=50)
    for i in range(120):
        r.capture(**_f(i))
    pending = r.shutdown(timeout_ms=2000)
    assert pending == 0
    assert len(sink.records) == 120
    assert r.telemetry()["evidence_pending_records_on_shutdown"] == 0


def test_shutdown_with_retry_recovers():
    sink = FlakySink(fail_times=2)              # first 2 batch writes fail, then succeed
    r = EvidenceRecorder(sink=sink, enabled=True, batch_size=50,
                         flush_retry_count=3, flush_backoff_ms=1)
    for i in range(40):
        r.capture(**_f(i))
    pending = r.shutdown(timeout_ms=2000)
    assert pending == 0 and len(sink.records) == 40


def test_no_data_loss_on_persistent_failure():
    r = EvidenceRecorder(sink=DeadSink(), enabled=True, batch_size=50,
                         flush_retry_count=2, flush_backoff_ms=1)
    for i in range(30):
        r.capture(**_f(i))
    assert r.flush_now() == 0                   # write fails after retries
    assert r.telemetry()["evidence_queue_depth"] == 30   # NOT lost (peek-not-pop)
    pending = r.shutdown(timeout_ms=200)
    assert pending == 30                        # honestly reported, bounded by timeout


def test_flush_duration_and_success_rate_tracked():
    sink = ListSink()
    r = EvidenceRecorder(sink=sink, enabled=True, batch_size=10)
    for i in range(30):
        r.capture(**_f(i))
    while r.telemetry()["evidence_queue_depth"] > 0:
        r.flush_now()
    t = r.telemetry()
    assert t["evidence_write_success_rate"] == 1.0
    assert t["evidence_flush_duration_ms"] >= 0.0


def test_relative_path_normalized_to_absolute():
    s = JsonlSink("data/evidence")
    assert os.path.isabs(s.directory)
