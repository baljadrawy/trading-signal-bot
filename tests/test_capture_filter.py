"""Capture filter — a simple rules layer so the first enable can't silently become a
full run. Distinct from technical drops: filtered = intentional exclusion.
"""
import sys; sys.path.insert(0, '.')
from research.null_a.recorder import EvidenceRecorder, CaptureFilter
from research.null_a.sinks import NullSink


def _cap(rec, symbol="BTCUSDT", tf="1h", source="live"):
    return rec.capture(signal_id="x", timestamp=1.0, symbol=symbol,
                       timeframe=tf, source=source, features={})


def test_no_filter_captures_all():
    r = EvidenceRecorder(sink=NullSink(), enabled=True)        # no filter
    assert _cap(r, "DOGEUSDT", "15m", "paper") is True


def test_symbol_filter_blocks_non_canary():
    r = EvidenceRecorder(sink=NullSink(), enabled=True,
                         capture_filter=CaptureFilter(symbols=["BTCUSDT"]))
    assert _cap(r, symbol="ETHUSDT") is False
    assert _cap(r, symbol="BTCUSDT") is True
    assert r.telemetry()["evidence_filtered_records"] == 1


def test_timeframe_filter_blocks_non_canary():
    r = EvidenceRecorder(sink=NullSink(), enabled=True,
                         capture_filter=CaptureFilter(timeframes=["1h"]))
    assert _cap(r, tf="4h") is False
    assert _cap(r, tf="1h") is True


def test_source_filter_works():
    r = EvidenceRecorder(sink=NullSink(), enabled=True,
                         capture_filter=CaptureFilter(sources=["live"]))
    assert _cap(r, source="paper") is False
    assert _cap(r, source="live") is True


def test_rate_limit_caps_capture_volume():
    frozen = lambda: 1000.0                                     # freeze time within the hour
    r = EvidenceRecorder(sink=NullSink(), enabled=True,
                         capture_filter=CaptureFilter(max_per_hour=5, clock=frozen))
    captured = sum(1 for _ in range(20) if _cap(r))
    assert captured == 5
    assert r.telemetry()["evidence_filtered_records"] == 15


def test_filtered_distinct_from_dropped():
    r = EvidenceRecorder(sink=NullSink(), enabled=True,
                         capture_filter=CaptureFilter(symbols=["BTCUSDT"]))
    _cap(r, symbol="XRPUSDT")                                   # intentional exclusion
    t = r.telemetry()
    assert t["evidence_filtered_records"] == 1
    assert t["evidence_dropped_records"] == 0                   # not a technical failure
