# Canary Runbook — Evidence Flight Recorder

The operational contract for first-enabling the evidence recorder on the live (paper)
signal engine. Written BEFORE activation so success/failure is defined in advance, not
improvised after seeing numbers. Branch: `integration/research-pipeline`.

## Prerequisites (verify once, before Phase A)
- Image built from `integration/research-pipeline` (NOT `main`).
- `signal_engine` image includes `research/null_a/` (Dockerfile COPY). Without it the
  recorder silently degrades to a no-op and collects ZERO evidence — a false "success".
  Verify: `docker compose exec signal_engine python -c "import research.null_a.recorder"`.
- Full test suite green (61 passed): `research/skill_application/.venv/bin/python -m pytest tests/ -q`.
- Telemetry is exposed by the flusher to `${EVIDENCE_DIR}/_telemetry.json` (default
  `data/evidence/_telemetry.json`) as a ring buffer of the last `EVIDENCE_TELEMETRY_HISTORY`
  (default 500) snapshots, read by `monitor_canary.py`. The monitor evaluates the WORST case
  across the window, so a one-cycle spike (e.g. a transient dropped/latency blip) is not lost
  between reads.

---

# Phase A — BTCUSDT / 1h

## Activation
```
ENABLE_EVIDENCE_RECORDER=true
EVIDENCE_FILTER_SYMBOLS=BTCUSDT
EVIDENCE_FILTER_TIMEFRAMES=1h
EVIDENCE_FILTER_SOURCES=live,paper
EVIDENCE_FILTER_MAX_SIGNALS_PER_HOUR=20
```
Apply to `.env`, then: `docker compose up -d --build signal_engine`.

## Observation Window
24–48h.

## Monitor
```
watch -n 30 research/skill_application/.venv/bin/python monitor_canary.py
```

## Success Criteria (ALL must hold)
```
evidence_capture_latency_ms_p95 < 1ms
evidence_dropped_records == 0
evidence_write_success_rate > 99.9%
evidence_pending_records_on_shutdown == 0
signal_hash_before == signal_hash_after   # structurally guaranteed (test_recorder_never_changes_signal_output)
```
`evidence_filtered_records` should be > 0 and consistent with BTCUSDT/1h traffic (proves the
filter scopes correctly, not a full run). `signal_hash` identity is guaranteed by the
non-mutation test; the monitor verifies the runtime telemetry metrics.

## Expand Criteria → Phase B
All Phase-A success criteria held for the full window AND `CANARY_HEALTH=GREEN`.
```
EVIDENCE_FILTER_SYMBOLS=BTCUSDT,ETHUSDT
EVIDENCE_FILTER_TIMEFRAMES=1h,4h
```
Then run a full paper week before Phase C (whole universe).

## Immediate Rollback Triggers (any one)
```
evidence_dropped_records > 0
evidence_write_success_rate < 99.9%
signal output mismatch (signals changed by the recorder)
unexpected signal frequency change
signal_engine startup failure
```

## Rollback (immediate, ~1 min, no code change)
```
ENABLE_EVIDENCE_RECORDER=false
docker compose restart signal_engine
```
The recorder is off-by-default and fully isolated; rollback is a flag flip + restart. No DB
migration, no state to unwind. Captured evidence in `data/evidence/` is harmless to keep.

---

## After Phase C
Only once real evidence has accumulated across a paper week at full scope do we build
**PR #4** (wire the health monitor + conditional Null-A to the collected evidence). Building
PR #4 earlier means building a monitor on synthetic/thin data — explicitly deferred.
