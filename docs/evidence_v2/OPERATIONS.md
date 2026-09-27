# Evidence v2 — operations, data quality, recovery, deployment and rollback

## Health (no silent failures)
The recorder's health is visible in three places:
- `service_heartbeats.metadata.evidence_v2` (analyzer, signal_engine, trade_tracker, telegram) holds:
  `queue_depth`, `dropped`, `errors`, `hook_errors`, `flush_failures`, `last_flush_ok_at`, `last_error` and `seq`.
  The key appears only when v2 is enabled, so the metadata is unchanged when it is off. If initialization
  fails, the key shows `init_error`.
- `data/evidence_v2/<service>/_recorder_stats.json` is refreshed after every flush (default every 2 s).
  It also holds emit latency p50/p95/p99.
- `recorder.stats` events are written into the stream every 10 minutes, so the offline tool sees drops and errors.

Recorder failures never change a decision or mark a service unhealthy. They are counted and logged as
warnings, rate-bound by the flush interval.

```sql
SELECT service_name, metadata->'evidence_v2' FROM service_heartbeats ORDER BY 1;
```

## Data-quality procedure (daily, offline, outcome-blind)
```bash
python -m research.evidence_v2.reconcile --dir data/evidence_v2 --json /tmp/ev2_report.json
```
Exit code 0 means clean, 1 means warnings, 2 means critical.

| Finding | Action |
|---|---|
| `pit_violation`, `stale_macro_used`, `conflicting_event_id`, `malformed_line`, `invalid_record` (critical) | Stop using the affected window for research. Open an incident and inspect `code_sha` and `config_hash` of the events. |
| `sequence_gap_lost_events`, `recorder_dropped`, `recorder_flush_failures`, `recorder_stale_flush` | Check disk space and permissions, `queue_depth` and `last_error`. The lost interval is excluded from datasets. |
| `missing_delivery_stage`, `missing_admission_stage`, `incomplete_trade_lifecycle` | Compare with DB state (`signals.telegram_sent`, `active_trades.status`) before treating the data as missing. |
| `*_without_*_event` (info in the first window after enabling) | Expected for entities created before recording started. |

The tool never reads profit, result or exit-price fields. The sealed holdout stays sealed.

## Recovery procedures
- **Disk full or permission error.**
  1. Events stay queued (bounded by `EVIDENCE_V2_MAX_QUEUE`, default 10,000, about 17 MB), then are dropped
     and counted.
  2. Fix the host directory (`chown 1000:1000 data/evidence_v2`, free space). Flushing resumes by itself.
  3. The lost range is visible as a `seq` gap.
- **Restart.** A restart gets a new `boot_id`. The current states are re-stated once (`restated=true`), and
  duplicates share `event_id` and are collapsed by the tool.
- **Queue saturation.** Raise `EVIDENCE_V2_MAX_QUEUE` only after fixing the sink. Never block decisions.
- **Corrupt line.** Leave the file untouched and report it (`malformed_line`). Consumers skip the line.
- **Retention.** Files are append-only daily JSONL of about 25–40 MB/day expected. Include
  `data/evidence_v2/` in the restic backup set. Never edit files in place; archive by day.

## Deployment plan (owner approval required; not performed in P1)
**Prerequisites:** the trading halt is unchanged, the B3 overlay images are recorded as the rollback anchor,
the branch is reviewed, and the test report passes.
1. On the host: `mkdir -p data/evidence_v2 && chown 1000:1000 data/evidence_v2` (next to `data/evidence`).
2. Merge the reviewed branch through the normal review. Build images for **analyzer, signal_engine,
   trade_tracker and telegram** with `BUILD_REVISION=$(git rev-parse HEAD)`. Scanner and claude_review are
   untouched and are **not** rebuilt, because the claude_review image contains unmatched files.
3. Deploy with `EVIDENCE_V2_ENABLED` unset (off):
   - one service at a time, with `docker compose up -d --no-deps --no-build <svc>`;
   - never a bare `up`, which would start `continuous_learner`;
   - the compose change adds only the `./data/evidence_v2` bind mount.
4. Verify:
   - heartbeats are fresh;
   - no errors;
   - analysis rows now contain `pit`;
   - the signal parity checks from the test report still hold on the new images.
5. Enable: set `EVIDENCE_V2_ENABLED=true` in `.env` and recreate the four services one by one.
6. Verify the heartbeat `evidence_v2` block, the stats files and the first reconciliation report (exit 0/1).

## Rollback
- **Recording only:** set `EVIDENCE_V2_ENABLED=false` and recreate the affected service. Every hook becomes
  a no-op, and files already written stay as evidence.
- **Code:** redeploy the previous image IDs (baseline manifest or the B3 rollback anchors).
  - The `analysis_data.pit` and `features_snapshot.identity` keys are additive JSON. Old code ignores them.
  - There is no DB schema change and no migration, so there is nothing to revert in the database.
