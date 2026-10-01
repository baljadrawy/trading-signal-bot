# Evidence v2 — operations, data quality, storage, deployment and rollback (P1-R)

Forward instrumentation is **OFF by default** (`EVIDENCE_V2_ENABLED=false`). This document describes how it is
observed, stored, deployed and rolled back. Nothing here is authorized by merging the code: every deployment
and enabling step needs separate owner approval. Development and production share one host
(`docs/product/SINGLE_HOST_SAFETY.md` on the governance branch, PR #3).

## Health (no silent failures)
The recorder's health is visible in three places, **only while ON**:
- `service_heartbeats.metadata.evidence_v2` (analyzer, signal_engine, trade_tracker, telegram) holds:
  `queue_depth`, `dropped`, `errors`, `hook_errors`, `flush_failures`, `last_flush_ok_at`, `last_error` and `seq`.
  The key is absent when OFF, so heartbeat metadata is unchanged. If initialization fails, it shows `init_error`.
- `data/evidence_v2/<service>/_recorder_stats.json`, replaced atomically after every flush (default every 2 s),
  including emit latency p50/p95/p99.
- `recorder.stats` events in the stream every 10 minutes, so the offline tool sees drops and errors.

Recorder failures never change a decision and never mark a service unhealthy: they are counted and logged as
warnings. Tested failure modes: recorder unavailable (init error), unwritable or missing destination, disk full
(sink raises), malformed/unserializable payload, exception inside a hook, duplicate events.

```sql
SELECT service_name, metadata->'evidence_v2' FROM service_heartbeats ORDER BY 1;
```

## Data-quality procedure (offline, outcome-blind)
```bash
python -m research.evidence_v2.reconcile --dir data/evidence_v2 --json /tmp/ev2_report.json
```
Exit code 0 = clean, 1 = warnings, 2 = critical. The report includes `outcome_codes` (the outcome matrix) and
`trade_lifecycle.dead_letters` (`explained` / `unexplained`).

| Finding | Action |
|---|---|
| `pit_violation`, `stale_macro_used`, `conflicting_event_id`, `malformed_line`, `invalid_record` (critical) | Stop using the affected window for research; inspect `code_sha` and `config_hash` of the events. |
| `sequence_gap_lost_events`, `recorder_dropped`, `recorder_flush_failures`, `recorder_stale_flush` | Check disk space, permissions, `queue_depth` and `last_error`; exclude the lost interval. |
| `unexplained_dead_letter` | A runtime `signal.delivered` dead letter with no observed admission/entry outcome. Compare with DB state. |
| `expiry_without_observed_attempt` (info) | Window closed for a signal this process never attempted (e.g. restart mid-window). |
| `missing_delivery_stage`, `missing_admission_stage`, `incomplete_trade_lifecycle` | Compare with DB state before treating the data as missing. |
| `*_without_*_event` (info right after enabling) | Expected for entities created before recording started. |

The tool never reads profit, result or exit-price fields. The sealed holdout stays sealed.

## Evidence storage
| Topic | Design |
|---|---|
| Layout | `data/evidence_v2/<service>/events-YYYY-MM-DD.jsonl` (UTC day) + `_recorder_stats.json`; one writer per file. |
| Expected growth | Measured on the real hooks: `candidate.analyzed` ≈ 2.4 KB, `candidate.evaluated` ≈ 1.7 KB per candidate state; signal/delivery/tracker events ≈ 1–2 KB. Candidate events are emitted only on a decision-state change (one per closed candle per symbol/timeframe). With August-2026 volumes (≈108 symbols, 47.6 signals/day avg, peak 215; 12 trades/day): **≈ 15–50 MB/day while trading is active** (lower bound ≈30 actively analysed symbols, upper bound all symbols on 15m/4h/1d), **≈ 1–3 MB/day while halted** (cycle transitions and stats only). Upper bound ≈ 18 GB/year uncompressed; JSONL compresses roughly 10×. Host free disk at review: 517 GB. |
| Retention | Evidence is a research asset: keep all files. Never edit in place. Compressing closed days (gzip, keep the original until the archive is verified) is an operational task for the deployment package. |
| Permissions | Containers run as uid 1000. The host directory must exist and be owned by `1000:1000` **before** a service mounts it — if Docker creates the bind-mount directory it is root-owned and every flush fails (visible as `flush_failures`). |
| Atomic writes | Events: append + flush + fsync per batch (`EVIDENCE_V2_FSYNC`, default on). Stats: write-temp + `os.replace` (atomic). |
| Corruption | A crash can leave at most a truncated last line; consumers skip it and the tool reports `malformed_line`. Files are never rewritten. |
| Disk full | Writes fail; events stay queued (bounded by `EVIDENCE_V2_MAX_QUEUE`, default 10,000 ≈ 17–25 MB RAM), then are dropped and counted; the loss is a visible `seq` gap. Decisions are unaffected. Flushing resumes by itself once space is freed. |
| Rotation | Daily by file name (UTC). No size-based rotation inside a day. |
| Backup | **Inside the backup boundary.** Before the recorder is enabled in production, `data/evidence_v2/` must be in the verified local backup set (and `trading_signals`, which today has no recurring backup). Off-host backup remains an owner-deferred decision (required before paper resume). |

## Deployment model (later package; NOT part of P1-R)
Production runs pinned, file-only overlay images (`deploy/cr2-signal-ready/IMAGES.md`, D3B-1 analyzer). P1-R is
deployable the same way; it adds no third-party package and no migration. A separate, owner-approved package:
1. **Overlays per service**, each built FROM the exact running image and replacing only the P1-R files listed in
   the P1-R evidence (`overlay_assessment`). Build every overlay against that service's **own** `/app` (analyzer
   and signal_engine carry older `shared/trading_state.py` / `shared/schema.py`; they are not touched).
   Acceptance gates as in CR-2: exact base-layer prefix, identical image config, only intended files, identical
   Python/stdlib/packages, all other `/app` files byte-identical.
2. **A reviewed Compose PR** that pins the four overlays, adds the `./data/evidence_v2` bind mount to analyzer,
   signal_engine, trade_tracker and telegram, and sets `EVIDENCE_V2_ENABLED: "false"` explicitly per service
   (no `.env` edit). Merging is not deploying.
3. **Host preparation** (owner-approved): `data/evidence_v2` created and owned by `1000:1000`; included in the
   local restic set; restore verified.
4. **Gated Class B rollout**, one service at a time, recorder OFF: trade_tracker → telegram → analyzer →
   signal_engine. Verify health ×2, image identity, `/app` parity, heartbeats, no `pit`/`identity` keys written,
   PAPER_HALTED and exact B3.
5. **Enabling is a separate owner decision**: flip `EVIDENCE_V2_ENABLED: "true"` per service through a reviewed
   Compose change, one service at a time; verify the heartbeat `evidence_v2` block, the stats files and a first
   reconcile report (exit 0/1). Paper trading stays halted unless separately authorized.

## Rollback
- **Recording only:** set `EVIDENCE_V2_ENABLED: "false"` for the service (reviewed Compose change) and recreate
  it. Every hook becomes a no-op; files already written stay as evidence; `pit`/`identity` stop being written.
- **Code:** re-pin the previous image of the service (CR-2 / D3B-1 images) and recreate only that service.
  `analysis_data.pit` and `features_snapshot.identity` are additive JSON that the previous code ignores. There is
  no schema change and no migration, so nothing is reverted in the database.
