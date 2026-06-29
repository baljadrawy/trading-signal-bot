"""Flight-recorder (EvidenceRecorder) — the isolation layer for the first live touch.

Mandatory properties (a monitoring system must never become a source of risk):
- disabled => true no-op
- any recorder failure is buried, never reaches the signal pipeline
- capture is non-blocking and within the p95 < 5ms budget
- bounded queue: overflow drops gracefully and is counted
- telemetry from day one (success rate, latency, queue depth, dropped)
"""
import sys, time, copy; sys.path.insert(0, '.')
import numpy as np
from research.null_a.recorder import EvidenceRecorder, maybe_capture, capture_signal
from research.null_a.sinks import NullSink, ListSink


class RaisingSink:
    def write(self, batch):
        raise IOError("disk full")


def _fields(i=0):
    return dict(signal_id=f"s{i}", timestamp=1750000000.0 + i, symbol="BTCUSDT",
                timeframe="15m", feature_vector={"rsi": 30.0}, confidence=0.8,
                signal_score=3.0, market_regime="bull", volatility=0.9, liquidity=0.8,
                ohlcv_window=np.zeros((50, 5)), entry_decision="long")


def test_recorder_disabled_is_true_noop():
    sink = ListSink()
    r = EvidenceRecorder(sink=sink, enabled=False)
    assert r.capture(**_fields()) is False
    r.flush_now()
    assert sink.records == []
    assert r.telemetry()["evidence_queue_depth"] == 0


def test_signal_pipeline_works_if_recorder_crashes():
    class Boom(EvidenceRecorder):
        def capture(self, **k):
            raise RuntimeError("boom")
    r = Boom(sink=NullSink(), enabled=True)

    def signal_pipeline():
        signal = "SIGNAL"
        maybe_capture(r, **_fields())     # must swallow the crash
        return signal

    assert signal_pipeline() == "SIGNAL"


def test_capture_latency_under_budget():
    r = EvidenceRecorder(sink=NullSink(), enabled=True, max_queue=200000)
    lat = []
    for i in range(2000):
        t = time.perf_counter()
        r.capture(**_fields(i))
        lat.append((time.perf_counter() - t) * 1000.0)
    p95 = float(np.percentile(lat, 95))
    assert p95 < 5.0, f"p95 latency {p95:.3f}ms exceeds 5ms budget"


def test_queue_overflow_drops_gracefully():
    r = EvidenceRecorder(sink=NullSink(), enabled=True, max_queue=10)
    for i in range(100):
        r.capture(**_fields(i))           # must never raise
    t = r.telemetry()
    assert t["evidence_queue_depth"] <= 10
    assert t["evidence_dropped_records"] >= 90


def test_batch_flush_and_telemetry():
    sink = ListSink()
    r = EvidenceRecorder(sink=sink, enabled=True, max_queue=1000, batch_size=50)
    for i in range(120):
        r.capture(**_fields(i))
    while r.telemetry()["evidence_queue_depth"] > 0:
        r.flush_now()
    assert len(sink.records) == 120
    assert r.telemetry()["evidence_capture_success_rate"] == 1.0
    assert r.telemetry()["evidence_capture_latency_ms_p95"] < 5.0


def test_flush_failure_does_not_raise():
    r = EvidenceRecorder(sink=RaisingSink(), enabled=True)
    r.capture(**_fields())
    r.flush_now()                         # must swallow the sink error
    assert r.telemetry()["evidence_flush_failures"] >= 1


def test_recorder_never_changes_signal_output():
    """THE critical guarantee (first touch on the live signal line): capturing evidence
    must never alter the signal object — recorder enabled, disabled, or sink crashing."""
    signal = {"symbol": "BTCUSDT", "timeframe": "15m", "trade_type": "momentum",
              "features": {"rsi": 28.0, "stoch": 0.7}, "score": 3.1,
              "macro_state": "usdtd_falling"}
    baseline = copy.deepcopy(signal)

    for rec in (EvidenceRecorder(sink=ListSink(), enabled=True),
                EvidenceRecorder(sink=ListSink(), enabled=False),
                EvidenceRecorder(sink=RaisingSink(), enabled=True)):
        out = capture_signal(rec, signal, source="live", model_version="v1")
        assert out is None                       # hook returns nothing
        assert signal == baseline                # signal object is byte-identical
        # captured copy must not alias the signal's mutable members
        if rec.enabled and rec._q:
            rec_features = rec._q[-1]["features"]
            rec_features["rsi"] = -999
            assert signal["features"]["rsi"] == 28.0


def test_phase_id_tags_records_and_telemetry(tmp_path):
    p = tmp_path / "_telemetry.json"
    sink = ListSink()
    r = EvidenceRecorder(sink=sink, enabled=True, telemetry_path=str(p), phase_id="PhaseA-R2")
    r.capture(**_fields())
    r.flush_now()
    assert sink.records[0]["phase_id"] == "PhaseA-R2"          # captured record tagged
    r.dump_telemetry()
    import json as _json
    snap = _json.loads(p.read_text())[-1]
    assert snap["phase_id"] == "PhaseA-R2"                     # telemetry snapshot tagged


def test_capture_signal_tags_source_and_deferred_ohlcv():
    sink = ListSink()
    r = EvidenceRecorder(sink=sink, enabled=True)
    sig = {"symbol": "ETHUSDT", "timeframe": "1d", "features": {"rsi": 30.0},
           "trade_type": "reversion", "macro_state": "usdtd_flat", "score": 2.5}
    capture_signal(r, sig, source="paper", model_version="sb-2026.06")
    r.flush_now()
    rec = sink.records[0]
    assert rec["source"] == "paper" and rec["ohlcv_status"] == "deferred"
    assert rec["model_version"] == "sb-2026.06" and "signal_id" in rec
    assert rec["symbol"] == "ETHUSDT"
