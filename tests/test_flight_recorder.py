"""Flight-recorder (EvidenceRecorder) — the isolation layer for the first live touch.

Mandatory properties (a monitoring system must never become a source of risk):
- disabled => true no-op
- any recorder failure is buried, never reaches the signal pipeline
- capture is non-blocking and within the p95 < 5ms budget
- bounded queue: overflow drops gracefully and is counted
- telemetry from day one (success rate, latency, queue depth, dropped)
"""
import sys, time; sys.path.insert(0, '.')
import numpy as np
from research.null_a.recorder import EvidenceRecorder, maybe_capture


def _fields(i=0):
    return dict(signal_id=f"s{i}", timestamp=1750000000.0 + i, symbol="BTCUSDT",
                timeframe="15m", feature_vector={"rsi": 30.0}, confidence=0.8,
                signal_score=3.0, market_regime="bull", volatility=0.9, liquidity=0.8,
                ohlcv_window=np.zeros((50, 5)), entry_decision="long")


def test_recorder_disabled_is_true_noop():
    sink_calls = []
    r = EvidenceRecorder(sink=lambda b: sink_calls.append(b), enabled=False)
    assert r.capture(**_fields()) is False
    r.flush_now()
    assert sink_calls == []
    assert r.telemetry()["evidence_queue_depth"] == 0


def test_signal_pipeline_works_if_recorder_crashes():
    class Boom(EvidenceRecorder):
        def capture(self, **k):
            raise RuntimeError("boom")
    r = Boom(sink=lambda b: None, enabled=True)

    def signal_pipeline():
        signal = "SIGNAL"
        maybe_capture(r, **_fields())     # must swallow the crash
        return signal

    assert signal_pipeline() == "SIGNAL"


def test_capture_latency_under_budget():
    r = EvidenceRecorder(sink=lambda b: None, enabled=True, max_queue=200000)
    lat = []
    for i in range(2000):
        t = time.perf_counter()
        r.capture(**_fields(i))
        lat.append((time.perf_counter() - t) * 1000.0)
    p95 = float(np.percentile(lat, 95))
    assert p95 < 5.0, f"p95 latency {p95:.3f}ms exceeds 5ms budget"


def test_queue_overflow_drops_gracefully():
    r = EvidenceRecorder(sink=lambda b: None, enabled=True, max_queue=10)
    for i in range(100):
        r.capture(**_fields(i))           # must never raise
    t = r.telemetry()
    assert t["evidence_queue_depth"] <= 10
    assert t["evidence_dropped_records"] >= 90


def test_batch_flush_and_telemetry():
    got = []
    r = EvidenceRecorder(sink=lambda b: got.extend(b), enabled=True,
                         max_queue=1000, batch_size=50)
    for i in range(120):
        r.capture(**_fields(i))
    while r.telemetry()["evidence_queue_depth"] > 0:
        r.flush_now()
    assert len(got) == 120
    assert r.telemetry()["evidence_capture_success_rate"] == 1.0
    assert r.telemetry()["evidence_capture_latency_ms_p95"] < 5.0


def test_flush_failure_does_not_raise():
    def bad_sink(batch):
        raise IOError("disk full")
    r = EvidenceRecorder(sink=bad_sink, enabled=True)
    r.capture(**_fields())
    r.flush_now()                         # must swallow the sink error
    assert r.telemetry()["evidence_flush_failures"] >= 1
