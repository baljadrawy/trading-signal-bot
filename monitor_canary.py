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


def evaluate_canary(tel: dict) -> dict:
    """Pure decision logic. status PASS/FAIL, health GREEN/RED, and whether an IMMEDIATE
    rollback trigger (dropped / write-success) fired (vs a non-rollback criteria miss)."""
    reasons = []
    rollback = False

    p95 = tel.get("evidence_capture_latency_ms_p95")
    if p95 is None or p95 >= LATENCY_P95_MAX_MS:
        reasons.append(f"latency p95 {p95}ms >= {LATENCY_P95_MAX_MS}ms")

    dropped = tel.get("evidence_dropped_records", 0)
    if dropped and dropped > 0:
        reasons.append(f"dropped_records {dropped} > 0")
        rollback = True

    wsr = tel.get("evidence_write_success_rate", 1.0)
    if wsr < WRITE_SUCCESS_MIN:
        reasons.append(f"write_success_rate {wsr * 100:.2f}% < {WRITE_SUCCESS_MIN * 100:.1f}%")
        rollback = True

    pending = tel.get("evidence_pending_records_on_shutdown", 0)
    if pending and pending > 0:
        reasons.append(f"pending_on_shutdown {pending} > 0")

    status = "PASS" if not reasons else "FAIL"
    return {
        "status": status,
        "health": "GREEN" if status == "PASS" else "RED",
        "reasons": reasons,
        "rollback_recommended": rollback,
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
        tel = json.load(open(path))
    except Exception as e:
        print(f"STATUS: UNKNOWN\nreason: unreadable telemetry ({e})\nCANARY_HEALTH=GREY")
        return 0

    v = evaluate_canary(tel)
    print(f"STATUS: {v['status']}")
    print(f"p95_latency: {tel.get('evidence_capture_latency_ms_p95')}ms")
    print(f"dropped: {tel.get('evidence_dropped_records')}")
    print(f"success_rate: {tel.get('evidence_write_success_rate', 1.0) * 100:.1f}%")
    print(f"pending_shutdown: {tel.get('evidence_pending_records_on_shutdown')}")
    print(f"filtered: {tel.get('evidence_filtered_records')}")
    print()
    print(f"CANARY_HEALTH={v['health']}")
    if v["status"] == "FAIL":
        print("reason: " + "; ".join(v["reasons"]))
        print(f"rollback_recommended={'true' if v['rollback_recommended'] else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
