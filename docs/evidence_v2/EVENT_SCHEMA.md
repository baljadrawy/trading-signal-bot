# Evidence v2 — event schema and lineage (P1 forward instrumentation)

The recorder is `shared/evidence_v2.py`. It is off unless `EVIDENCE_V2_ENABLED=true`, and it writes only to
`EVIDENCE_V2_DIR` (default `data/evidence_v2`). The v1 recorder (`research/null_a/`, files in `data/evidence/`)
is unchanged and independent.

## Files
One directory per service and one file per UTC day. Each file has a single writer.
- `<dir>/<service>/events-YYYY-MM-DD.jsonl`: append-only JSON Lines, fsynced per batch. Each record is serialized
  when it is emitted, so a later mutation by the caller cannot change it.
- `<dir>/<service>/_recorder_stats.json`: the latest recorder health, replaced atomically after every flush.

## Envelope (every record, `schema="tsb.evidence"`, `schema_version=2`)
| Field | Meaning |
|---|---|
| `event_id` | Idempotency key: `evt_` + sha256(schema, version, service, type, subject, discriminator)[:32]. The same fact always gets the same id. For stream events (`transition=true`) the discriminator also includes `event_time_ms`. |
| `event_type`, `service` | See the catalog below. |
| `boot_id`, `seq` | Random per process start, plus a monotonic counter. A dropped event still uses up its number, so any gap in `seq` within one boot means a lost event. |
| `event_time_ms` | UTC epoch milliseconds of the decision or event, from the host clock. |
| `recorded_at_ms` | UTC epoch milliseconds when the event was captured. |
| `restated` | `true` the first time a state key is emitted in a boot. After a restart the current state is restated once; it is not a new decision. |
| `strategy_version` | `APP_VERSION`, the same value as `signals.strategy_version`. |
| `code_sha` | sha256 over (relative path + file sha256) of every `*.py` the process runs, excluding mounted data, logs, models and tests. It identifies overlays independently of build arguments. |
| `config_hash` | sha256 of the non-secret strategy configuration. Secret-like names, connection fields, per-process fields and recorder settings are excluded, so enabling the recorder never changes it. |
| `build_revision`, `phase_id` | `BUILD_REVISION` build argument, and `EVIDENCE_PHASE_ID`. |
| `subject`, `state`, `payload` | Identity, the decision state that dedup is applied to, and the details. |

**Decision-state changes only.** An event carrying a `dedup_key` is written only when its `state` differs
from the last state recorded for that key. Identical re-evaluations increment `suppressed_repeats`.

## Identities (P1-A)
- `candle_id` = `SYMBOL|timeframe|open_time_ms`. It uses the Binance kline open time of the **last closed**
  candle, in UTC. Candles still open at fetch time are dropped by `shared/ohlcv.py`.
- `candidate_id` = `cand_` + sha256(`candidate|v1|<candle_id>|<trade_type or ->|<strategy_version>`)[:24].
  - The same candle re-analysed gives the same id.
  - A new candle, a different setup or a different strategy version gives a new id.
- **Persisted with the data:**
  - `analysis_results.analysis_data.pit` holds the candle times, fetch and analysis times, `candle_id`,
    `candidate_id`, `strategy_version`, and the analyzer's `code_sha`, `config_hash` and `weights_hash`
    (the DB indicator weights actually used).
  - `signals.features_snapshot.identity` holds the same identity plus the signal engine's own
    `code_sha` and `config_hash` (`identity_version=1`). This is the lineage anchor inside the database.

## Event catalog
| Service | event_type | subject | state (dedup) | key payload |
|---|---|---|---|---|
| analyzer | `candidate.analyzed` | candidate_id, candle_id, symbol, timeframe | setup, stop validity, entry, stop | geometry, setup, order book, raw features, regime, pit (candle open/close, klines fetched, analyzed, order book fetched) |
| signal_engine | `candidate.evaluated` | candidate_id, candle_id, symbol, timeframe | decision (selected/rejected), reason | geometry (also for rejected candidates), order book, macro state and freshness, pit, `selection` (rank, rank key, eligible count), `identity_status` |
| signal_engine | `selection.truncation` | stream | truncated, digest of truncated rows | returned, eligible_total, truncated_count, truncated_rows (≤500) |
| signal_engine | `cycle.outcome` | stream | outcome (idle_no_fresh_analysis / macro_blocked / no_eligible_candidate / signal_created), truncated | counts, decision histogram, full macro snapshot and freshness, duration |
| signal_engine | `signal.created` | signal_id, candidate_id, candle_id | none (entity) | geometry, identity, pit |
| telegram | `delivery.sent` / `delivery.approval_requested` / `delivery.refused` / `delivery.skipped` | signal_id, candidate_id, symbol, timeframe | outcome, reason (for example `risk:loss_streak_halt`, `portfolio_capacity_2/2`, `already_sent`) | outbox event id |
| telegram | `control.command` | command | command, outcome | streak, recovery or pause details (no chat identifiers) |
| trade_tracker | `admission.capacity` | stream | blocked | open_count, max_open_trades |
| trade_tracker | `entry.attempt` | signal_id, candidate_id, symbol, timeframe | action (market/limit_wait/reject), reason | planned entry, observed price, stop, invalidation, order price |
| trade_tracker | `admission.decision` | as above | outcome (admitted, risk_rejected, no_price, bracket_invalid, halt_under_admission_lock, already_registered), reason | risk decision, **risk epoch start**, risk snapshot, limits |
| trade_tracker | `trade.opened` | + active_trade_id | none (entity) | fill, planned entry, drift, bracket, expiry policy, risk decision, epoch and snapshot |
| trade_tracker | `trade.target_hit` | active_trade_id, signal_id, target | none (entity) | fill price, fraction, notional, gross contribution, effective stop after |
| trade_tracker | `trade.closed` | active_trade_id, signal_id, trade_result_id | none (entity) | exit reason, trigger and weighted exit, gross and net PnL, holding hours, target reached, stop hit |
| trade_tracker | `risk.state` / `risk.transition` | stream | allowed, reason, paused / halted | risk decision, epoch, snapshot, limits |
| all | `recorder.started` / `recorder.stats` / `recorder.stopping` | service | boot | identity, strategy config (non-secret), recorder settings and health |

## Lineage
```
candle (exchange) -> candidate.analyzed -> candidate.evaluated -> signal.created (signal_id)
    -> delivery.* (telegram) -> entry.attempt / admission.decision -> trade.opened (active_trade_id)
    -> trade.target_hit* -> trade.closed (trade_result_id)
```
The join keys are `candidate_id`, `signal_id` and `active_trade_id`. The same keys exist in the database:
`analysis_data.pit`, `signals.features_snapshot.identity`, `active_trades.signal_id` and `trade_results.signal_id`.

## Point-in-time rules (tested)
- Candle close < klines fetched ≤ analyzed ≤ decision.
- Order book fetched ≤ decision.
- Macro valid-at ≤ decision.
- No event before `trade.closed` contains an outcome field.
