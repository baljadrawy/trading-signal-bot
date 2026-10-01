# Evidence v2 — event schema and lineage (P1 forward instrumentation)

The recorder is `shared/evidence_v2.py`. Forward instrumentation is controlled by ONE dedicated toggle,
`EVIDENCE_V2_ENABLED`, default **OFF** (owner decision, P1-R). OFF means: no recorder, no evidence files, no
outcome memory, no extra database reads, and **no P1 persistence** — `analysis_results.analysis_data.pit` and
`signals.features_snapshot.identity` are not written. Decisions are identical OFF and ON (tested against develop).
It writes only to `EVIDENCE_V2_DIR` (default `data/evidence_v2`). The v1 recorder (`research/null_a/`, files in
`data/evidence/`) is unchanged and independent.

## Three different things (do not confuse them)
| Kind | Where | Example | Meaning |
|---|---|---|---|
| **Runtime outbox event** | `outbox_events` (PostgreSQL) | `signal.ready`, `signal.delivered`, `trade.opened` | Drives the services. Claimed, acked, retried, dead-lettered. Unchanged by P1. |
| **Evidence event** | `data/evidence_v2/<service>/events-*.jsonl` | `signal.ready`, `delivery.consumed`, `entry.expired` | An append-only, point-in-time *record* of what a service saw and decided. Never read by any service. |
| **Decision record** | the runtime rows themselves | `signals.decision_source='policy_ready'`, `active_trades` | The authoritative state. P1 adds only the JSON keys above, and only while ON. |

The evidence event `signal.ready` records that the signal row (decision_source `policy_ready`) **and** the
runtime outbox event `signal.ready` were committed in one transaction (emitted after the commit). There is no
`signal.created` in the CR-2 contract, so no evidence event uses that name.

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
- **Persisted with the data (only while `EVIDENCE_V2_ENABLED` is ON):**
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
| signal_engine | `cycle.outcome` | stream | outcome (idle_no_fresh_analysis / macro_blocked / no_eligible_candidate / signal_ready / signal_refused), truncated | counts, decision histogram, full macro snapshot and freshness, duration |
| signal_engine | `signal.ready` | signal_id, candidate_id, candle_id | none (entity) | `outcome_code=POLICY_READY`, `decision_source`, `runtime_outbox_event`, geometry, identity, pit |
| signal_engine | `signal.refused` | candidate_id, candle_id, symbol, timeframe | outcome, reason (`incomplete_signal`) | `outcome_code=INCOMPLETE_SIGNAL`, error, geometry, pit (no row and no runtime event were written) |
| telegram | `delivery.sent` / `delivery.approval_requested` / `delivery.refused` / `delivery.skipped` | signal_id, candidate_id, symbol, timeframe | outcome, reason (readiness-based: `not_ready`, `legacy_not_approved`, `already_sent`, `signal_missing`, or the pause reason) | outbox event id, `claimed_event_type` (`signal.ready` or legacy `signal.reviewed`), `outcome_code` |
| trade_tracker | `admission.capacity` | stream | blocked | open_count, max_open_trades |
| trade_tracker | `entry.attempt` | signal_id, candidate_id, symbol, timeframe | action (market/limit_wait/reject), reason | `outcome_code` (ENTRY_MARKET / AWAITING_FILL / ENTRY_REJECTED), planned entry, observed price, stop, invalidation, order price |
| trade_tracker | `admission.decision` | as above | outcome (admitted, risk_rejected, no_price, bracket_invalid, halt_under_admission_lock, already_registered), reason | `outcome_code`, risk decision, **risk epoch start**, risk snapshot, limits |
| trade_tracker | `delivery.consumed` | signal_id, outbox_event_id | kind (opened / terminal / deferred), outcome_code, attempts | what happened to one claimed runtime `signal.delivered` event: OPENED; the named terminal condition (ENTRY_REJECTED / NOT_READY / STALE / BLACKLISTED / REJECTED); or a deferral with the last observed outcome and `final_attempt` (true when the runtime will dead-letter it) |
| trade_tracker | `entry.expired` | signal_id, candidate_id, symbol, timeframe | outcome_code | terminal record when a sent, ready signal leaves the 2-hour admission window without a trade: **NO_FILL** after a limit wait, EXPIRED after another deferral, BLACKLISTED/REJECTED, or EXPIRED_UNOBSERVED (no attempt seen by this process) |
| trade_tracker | `trade.opened` | + active_trade_id | none (entity) | fill, planned entry, drift, bracket, expiry policy, risk decision, epoch and snapshot |
| trade_tracker | `trade.target_hit` | active_trade_id, signal_id, target | none (entity) | fill price, fraction, notional, gross contribution, effective stop after |
| trade_tracker | `trade.closed` | active_trade_id, signal_id, trade_result_id | none (entity) | exit reason, trigger and weighted exit, gross and net PnL, holding hours, target reached, stop hit |
| trade_tracker | `risk.state` / `risk.transition` | stream | allowed, reason, paused / halted | risk decision, epoch, snapshot, limits |
| all | `recorder.started` / `recorder.stats` / `recorder.stopping` | service | boot | identity, strategy config (non-secret), recorder settings and health |

## Lineage
```
candle (exchange) -> candidate.analyzed -> candidate.evaluated -> signal.ready (signal_id)   [or signal.refused]
    -> delivery.* (telegram) -> entry.attempt / admission.decision / delivery.consumed
    -> trade.opened (active_trade_id) -> trade.target_hit* -> trade.closed (trade_result_id)
                              \-> entry.expired (NO_FILL / EXPIRED / ...) when no trade within the window
```
The join keys are `candidate_id`, `signal_id` and `active_trade_id`. The same keys exist in the database:
`analysis_data.pit`, `signals.features_snapshot.identity`, `active_trades.signal_id` and `trade_results.signal_id`.

## Point-in-time rules (tested)
- Candle close < klines fetched ≤ analyzed ≤ decision.
- Order book fetched ≤ decision.
- Macro valid-at ≤ decision.
- No event before `trade.closed` contains an outcome field.

## Outcome vocabulary (P1-R)
Every outcome-bearing event carries `payload.outcome_code` from one shared list (`evidence_v2.OUTCOME_CODES`).
The detailed lowercase `reason` stays as it was; the code is the cross-service key. Classifiers are pure
functions of what the runtime already decided — they never decide.

| Code | Where | Meaning |
|---|---|---|
| POLICY_READY | signal.ready | signal persisted ready (`policy_ready`) with the runtime `signal.ready` event |
| INCOMPLETE_SIGNAL | signal.refused | `assert_signal_complete` refused it; nothing written |
| DELIVERED / AWAITING_APPROVAL | delivery.sent / delivery.approval_requested | passed to the risk guard / owner approval requested |
| B3_BLOCKED | delivery.refused, admission.decision | loss-streak circuit breaker (`risk:loss_streak_halt` pause or `loss_streak_halt`) |
| PAUSED | delivery.refused, admission.decision | any other pause, including fail-closed missing/inconsistent risk state |
| CAPACITY | delivery.refused, admission.decision | portfolio / open-trade capacity |
| RISK_REJECTED | admission.decision | other risk-guard hard stops |
| NOT_READY | delivery.skipped, delivery.consumed | not deliverable/trackable under the readiness contract |
| DUPLICATE | delivery.skipped, admission.decision | already sent / already registered |
| SIGNAL_MISSING | delivery.skipped, delivery.consumed | event for a signal row that does not exist |
| STALE / BLACKLISTED / REJECTED / ENTRY_REJECTED | delivery.consumed, entry.expired | the named terminal condition of `DELIVERY_TERMINAL_SQL` |
| ENTRY_MARKET / AWAITING_FILL / NO_PRICE / BRACKET_INVALID | entry.attempt, admission.decision, delivery.consumed | non-terminal entry/admission states |
| NO_FILL | entry.expired (and `resolved_code` on a STALE delivery.consumed) | the admission window closed while the limit order was unfilled |
| EXPIRED / EXPIRED_UNOBSERVED | entry.expired | window closed after another deferral / with no attempt seen by this process |
| OPENED | admission.decision, delivery.consumed | paper trade registered |
| DEFERRED_UNOBSERVED / UNKNOWN | delivery.consumed | deferral with no observed outcome yet / unrecognized value |

**Dead letters.** The runtime outbox semantics are unchanged: a delivery event deferred until `attempts >=
max_attempts` still becomes `dead`. The evidence marks that last deferral `final_attempt=true` with the outcome
code that explains it (for example AWAITING_FILL, later NO_FILL). The reconcile tool reports
`unexplained_dead_letter` only when no outcome was observed. Historical dead letters are not reinterpreted.

## Timestamp semantics (point in time)
| Stage | Field | Clock | Meaning |
|---|---|---|---|
| Market input | `pit.candle_open_time_ms` / `candle_close_time_ms` | Binance kline | the last **closed** candle (open candles are dropped by `shared/ohlcv.py`) |
| Market input | `pit.klines_fetched_at_ms`, `pit.orderbook_fetched_at_ms` | analyzer host | when the data was in hand |
| Analysis | `pit.analyzed_at_ms` = `candidate.analyzed.event_time_ms` | analyzer host | indicators computed from closed candles only |
| Signal decision | `candidate.evaluated.event_time_ms` = macro `decision_at_ms` | signal_engine host | selection/rejection; macro `valid_at <= decision` |
| Readiness | `signal.ready.event_time_ms` | signal_engine host | decision time; emitted after the commit |
| Telegram handling | `delivery.*.event_time_ms` | telegram host | when the candidate event was gated |
| Tracker outcome | `entry.attempt`, `admission.decision`, `delivery.consumed`, `entry.expired` | tracker host | each attempt / classification as it happened |
No pre-outcome event contains a profit, result or exit field (tested); outcomes appear only in `trade.closed`.
