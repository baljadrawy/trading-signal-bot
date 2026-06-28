"""Canary telemetry exposure + the monitor's PASS/FAIL decision logic.

The decision of what counts as success/failure/rollback is codified here BEFORE any live
run, so 48h of numbers are read against a written contract, not interpreted on the fly.
"""
import sys, json; sys.path.insert(0, '.')
from research.null_a.recorder import EvidenceRecorder
from research.null_a.sinks import NullSink
import monitor_canary as mc


def _cap(r, sym="BTCUSDT", tf="1h", src="live"):
    return r.capture(signal_id="x", timestamp=1.0, symbol=sym, timeframe=tf, source=src, features={})


# ---------------- telemetry exposure ----------------
def test_dump_telemetry_writes_json(tmp_path):
    p = tmp_path / "_telemetry.json"
    r = EvidenceRecorder(sink=NullSink(), enabled=True, telemetry_path=str(p))
    _cap(r)
    r.dump_telemetry()
    data = json.loads(p.read_text())
    assert data["evidence_captured_total"] == 1
    assert "evidence_capture_latency_ms_p95" in data
    assert "evidence_write_success_rate" in data


# ---------------- decision logic ----------------
def _green():
    return {"evidence_capture_latency_ms_p95": 0.003, "evidence_dropped_records": 0,
            "evidence_write_success_rate": 1.0, "evidence_pending_records_on_shutdown": 0,
            "evidence_filtered_records": 14, "evidence_captured_total": 5}


def test_evaluate_canary_pass():
    v = mc.evaluate_canary(_green())
    assert v["status"] == "PASS" and v["health"] == "GREEN"
    assert v["rollback_recommended"] is False and v["reasons"] == []


def test_evaluate_canary_fail_dropped_triggers_rollback():
    tel = _green(); tel["evidence_dropped_records"] = 3
    v = mc.evaluate_canary(tel)
    assert v["status"] == "FAIL" and v["health"] == "RED"
    assert v["rollback_recommended"] is True
    assert any("dropped" in r for r in v["reasons"])


def test_evaluate_canary_fail_success_rate_triggers_rollback():
    tel = _green(); tel["evidence_write_success_rate"] = 0.98
    v = mc.evaluate_canary(tel)
    assert v["status"] == "FAIL" and v["rollback_recommended"] is True


def test_evaluate_canary_latency_fail_without_rollback():
    tel = _green(); tel["evidence_capture_latency_ms_p95"] = 2.0
    v = mc.evaluate_canary(tel)
    assert v["status"] == "FAIL" and v["health"] == "RED"
    assert v["rollback_recommended"] is False        # latency miss is not an immediate-rollback trigger


def test_evaluate_canary_pending_fail_without_rollback():
    tel = _green(); tel["evidence_pending_records_on_shutdown"] = 5
    v = mc.evaluate_canary(tel)
    assert v["status"] == "FAIL" and v["rollback_recommended"] is False
