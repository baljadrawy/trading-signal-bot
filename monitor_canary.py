#!/usr/bin/env python
"""Canary monitor — reads the evidence recorder's telemetry JSON and reports a PASS/FAIL
verdict against the Phase-A contract (docs/canary_runbook.md). Decoupled from the running
container: the flusher writes ${EVIDENCE_DIR}/_telemetry.json; this reads it.

    watch -n 30 research/skill_application/.venv/bin/python monitor_canary.py
"""
import json
import os
import sys

# Phase-A thresholds (must match docs/canary_runbook.md)
LATENCY_P95_MAX_MS = 1.0
WRITE_SUCCESS_MIN = 0.999


def evaluate_canary(data) -> dict:
    """Pure decision logic over a WINDOW of telemetry snapshots (or a single one), so a
    short spike anywhere in the retained history is caught — not just the latest reading.
    Worst-case per metric: max latency/dropped/pending, min write-success-rate.
    status PASS/FAIL, health GREEN/RED, and whether an IMMEDIATE rollback trigger
    (dropped / write-success) fired (vs a non-rollback criteria miss)."""
    history = data if isinstance(data, list) else [data]
    history = [s for s in history if isinstance(s, dict)]
    if not history:
        return {"status": "UNKNOWN", "health": "GREY", "reasons": ["no telemetry"],
                "rollback_recommended": False}
    reasons = []
    rollback = False

    p95 = max((s.get("evidence_capture_latency_ms_p95") or 0.0) for s in history)
    if p95 >= LATENCY_P95_MAX_MS:
        reasons.append(f"latency p95 {p95}ms >= {LATENCY_P95_MAX_MS}ms (window max)")

    dropped = max((s.get("evidence_dropped_records") or 0) for s in history)
    if dropped > 0:
        reasons.append(f"dropped_records {dropped} > 0 (window max)")
        rollback = True

    wsr = min((s.get("evidence_write_success_rate", 1.0)) for s in history)
    if wsr < WRITE_SUCCESS_MIN:
        reasons.append(f"write_success_rate {wsr * 100:.2f}% < {WRITE_SUCCESS_MIN * 100:.1f}% (window min)")
        rollback = True

    pending = max((s.get("evidence_pending_records_on_shutdown") or 0) for s in history)
    if pending > 0:
        reasons.append(f"pending_on_shutdown {pending} > 0 (window max)")

    status = "PASS" if not reasons else "FAIL"
    return {
        "status": status,
        "health": "GREEN" if status == "PASS" else "RED",
        "reasons": reasons,
        "rollback_recommended": rollback,
        "window": len(history),
    }


def _telemetry_path() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    return os.path.join(os.getenv("EVIDENCE_DIR", "data/evidence"), "_telemetry.json")


def main() -> int:
    path = _telemetry_path()
    if not os.path.exists(path):
        print("STATUS: UNKNOWN")
        print(f"reason: no telemetry yet at {path} (recorder off, or no flush cycle elapsed)")
        print("CANARY_HEALTH=GREY")
        return 0
    try:
        data = json.load(open(path))
    except Exception as e:
        print(f"STATUS: UNKNOWN\nreason: unreadable telemetry ({e})\nCANARY_HEALTH=GREY")
        return 0

    history = data if isinstance(data, list) else [data]
    latest = history[-1] if history else {}
    v = evaluate_canary(data)
    print(f"STATUS: {v['status']}   (window: {v.get('window', 1)} snapshots)")
    print(f"p95_latency: {latest.get('evidence_capture_latency_ms_p95')}ms")
    print(f"dropped: {latest.get('evidence_dropped_records')}")
    print(f"success_rate: {latest.get('evidence_write_success_rate', 1.0) * 100:.1f}%")
    print(f"pending_shutdown: {latest.get('evidence_pending_records_on_shutdown')}")
    print(f"filtered: {latest.get('evidence_filtered_records')}")
    print()
    print(f"CANARY_HEALTH={v['health']}")
    if v["status"] == "FAIL":
        print("reason: " + "; ".join(v["reasons"]))
        print(f"rollback_recommended={'true' if v['rollback_recommended'] else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
