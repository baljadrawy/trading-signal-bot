# tsb P2 forward raw data: schema v2 (`tsb.p2.forward`)

**Status:** authoritative for raw records with `schema_version = 2`, written by collector `p2e1-collector-1.1.0`
and later v2 writers.

- This file is copied, immutable, into every data directory as `docs/SCHEMA-v2-<sha8>.md`. Its SHA-256 is in each
  run record.
- Raw history is **never rewritten**. A new schema means a new `schema_version` written by a new writer, and
  readers branch per record.
- v1 data (the original diagnostic G2) stays v1. Its known defects are documented in the P2-E1 evidence (F1 / F2 /
  F55), and it is not acceptance data.

## 1. Layout (`<data>`)

| Path | Content |
|---|---|
| `raw/<type>/<YYYY-MM-DD>/<type>-<YYYYMMDDTHH>Z-<boot8>-<seq>.jsonl.gz` | certified segment (gzip JSONL, 0444) |
| `….sha256` | SHA-256 sidecar of the segment |
| `….idx` | one line per durable block `{blk, end_offset, records, durable_ts_ns}`; a storage fact, never a research join key |
| `manifests/<YYYY-MM-DD>.jsonl` | one line per certified segment: `segment`, `sha256`, `records`, `bytes`, `type`, `first_recv_ns`, `last_recv_ns`, `boot_id`, `run_record`, `idx_bytes` |
| `runs/run-<boot_id>.json` | **run record** (provenance, below; 0444) |
| `universe/universe-<stamp>-<boot8>.json` | immutable universe evaluation (tiers-v2, section 9a); `applied=true` for the universe actually used |
| `docs/SCHEMA-v2-<sha8>.md` | this document |
| `control/*.json` | out-of-band markers (disk hard stop, fatal); tiny, fsynced, 0444 |
| `quarantine/` | failed or salvaged segment originals (never deleted) |
| `health/collector_health.json` | **live** heartbeat only (overwritten every 10 s); history is in the `health` raw records |

`.partial` files are uncertified and never research data.

## 1a. Segment lifecycle and certification (G3-F3, collector ≥ 1.3.0)

File names are the authoritative, crash-safe state.

| State | Files | Owner |
|---|---|---|
| ACTIVE | `….jsonl.gz.partial` + `….idx.partial` | writer; durable within `flush_interval_s` |
| FINALIZED_PENDING_CERTIFICATION | `….jsonl.gz.pending` + `….idx.pending` | the writer closed and fsynced it and handed it off by atomic rename; never research data |
| CERTIFYING | `….jsonl.gz.certifying` + `….idx.pending` | the certifier (one at a time, throttled) |
| CERTIFIED | `….jsonl.gz` + `.sha256` + `.idx`, 0444, manifest entry | research data |
| FAILED | `quarantine/` + `quarantine_log.jsonl` | never deleted |

Certification, done by the certifier (`certifier-v1`), is unchanged in strength:
- full gzip / JSONL decode;
- per-record schema validation and in-segment duplicate check;
- record count equal to the `.idx` total;
- SHA-256 sidecar (temp file, then rename);
- atomic promotion and read-only permissions;
- an idempotent manifest entry with `certified_ms`, `certifier` and `recovered`.

The writer never decodes or hashes a finished segment, so the hot path is never blocked by certification.

**Crash recovery at startup** (deterministic):
- A `.partial` whose gzip stream is complete and matches its `.idx` becomes `.pending` (finalized, not handed off).
  Otherwise it is salvaged to a `-recovered-` segment and the original is quarantined.
- `.pending` and `.certifying` files are certified.
- A certified file without a manifest entry has its checksum re-verified against its sidecar and the entry is
  completed; on a mismatch it is quarantined.
- A second copy under an already-certified name is quarantined and never certified.

**Shutdown:** the active segments are finalized, then the certifier drains within `certify_shutdown_grace_s`.
Anything still uncertified gives `STOPPED_INCOMPLETE` (exit 2) and is preserved for recovery.

**Health:** writer and certifier health are separate.
- The writer heartbeat is the hot path only.
- The certifier has its own heartbeat (≤ `certifier_beat_limit_ms`), backlog limits (`certify_max_pending`,
  `certify_max_pending_age_s`) and failure counter.
- Hard reasons: `certifier_dead`, `certifier_stale`, `certifier_backlog`, `certification_failed`,
  `certifier_restarted_10min`. A dead certifier is restarted at most 3 times, after which the collector fails
  (exit 4).

## 2. Common record fields (every type)

| Field | Meaning |
|---|---|
| `schema`, `schema_version` | `"tsb.p2.forward"`, `2` |
| `obs_id` | identity (section 4) |
| `type` | `book`, `depth`, `market`, `candle`, `clock`, `universe`, `gap`, `lifecycle` or `health` |
| `symbol` | exchange symbol, or null |
| `tier` | 0 / 1 / 2 or null; `cadence_ms` = sampling cadence or null |
| `sample_ms` | sample boundary (book / depth / market), else null |
| `source` | `binance_spot_public` |
| `transport` | `ws`, `rest` or `internal` |
| `endpoint` | stream name, REST path, or `collector` |
| `exchange_event_time_ms` | exchange-provided time, **never synthesized**. Always null for book / depth (Binance spot `bookTicker` and partial depth carry no event time). Market: max `E` among components. Candle: close time. Clock: `serverTime` |
| `exchange_seq` | book `u`, depth `lastUpdateId`, else null |
| `recv_ts_ns` | host wall-clock time when the collector processed the message (ns). Market: the newest component used. If the host wall clock steps **backwards**, a message's `recv_ts_ns` is clamped to the stream's previous value, so the order is never inverted and the clamp only ever moves a time later (PIT-safe). It is counted as `recv_clock_regression`; steps over 1 s produce a `wall_clock_step` lifecycle record and a health reason |
| `queued_ts_ns` | time the record entered the writer queue |
| `blk` | durable block number within the segment |
| `observed_at_ms` | `recv_ts_ns // 1e6`: when the collector knew it |
| `available_at_ms` | earliest time the fact is usable without look-ahead (section 5). Equals `observed_at_ms` except candles: `max(close_time + 1, observed_at_ms)` |
| `unchanged` | book / depth: same `exchange_seq` as the previously persisted sample of the stream (no new update was used) |
| `clock_suspect` | clock CRITICAL at emission (timestamps are never rewritten) |
| `recoverability` | `IRREPLACEABLE_FORWARD_OBSERVATION` (book, depth, market and their gaps) or `RECOVERABLE_WHERE_ARCHIVE_AVAILABLE` (candles and their gaps). Never "fully recoverable" |
| `collector_version`, `boot_id` | writer version and boot; `boot_id` resolves to `runs/run-<boot_id>.json` |
| `payload` | exchange message **verbatim** (book / depth / candle / clock), or the collector-defined payload (market list, gap, lifecycle, health) |

Record-level v2 additions:
- `depth_levels` on every depth record: the explicit N of the `@depthN` stream; the arrays have ≤ N levels.
- `component_recv_ms` on every market record: `{symbol: recv_ms}` for each component.
- `startup_complete` on every market record: false until 60 s after the first `!miniTicker@arr` message, because
  early arrays carry only changed symbols.

## 3. Sampling semantics (book, depth, market)

`sample_semantics = "latest_received_at_or_before_sample_ms"`.

- The value stored for boundary `S` is the latest message the collector **received** at or before `S`, compared
  at nanosecond resolution: `recv_ts_ns ≤ S × 10^6`, which implies `observed_at_ms ≤ S` (sample-and-hold).
- It is **not**:
  - the exchange state exactly at `S`;
  - an OHLC;
  - an event at `S`.
- `S − observed_at_ms` is the age of the held value.
- A message received after `S` is **never** used for `S`. This holds for any message rate and any event-loop delay:
  boundaries are resolved from receive times, not wake-up times.
- Every boundary from the stream's first observation to the stop is either **one persisted record** or **inside
  exactly one gap record**. Boundaries before the stream's first observation are startup only while they fall
  before the first-observation deadline; after the deadline they are a `never_ready` gap.

**Freshness.** A held value is persisted only if, at `S`:
1. the stream's **own** connection was up and **data-live**: a data message within the last 10 s **and** after
   the connection's most recent (re)connect. WebSocket ping / pong never counts. A value received before the most
   recent reconnect is not persisted (`awaiting_post_reconnect_data`);
2. the value's age is within its limit:

   | Stream | Limit (`stale_ms`, G3-F1) |
   |---|---|
   | Tier-0 depth20 (cadence 1 s) | 2 s: pushes every ~1 s (G2R inter-arrival 971–1,039 ms); one missed push tolerated |
   | Tier-2 depth10 (cadence 5 s) | 15 s = 3 × cadence |
   | Tier-1 depth10 (cadence 60 s) | 180 s = 3 × cadence |
   | Tier-0 book | 120 s; within it, `unchanged = true` means no top-of-book change was received |
   | Tier-1/2 book | 600 s: a dead-stream bound for an event-driven stream; health warns at 120 s (`stale_suspect`) |
   | market | the newest component ≤ 10 s |

   A held value within its limit is persisted with its **original** `recv_ts_ns` / `observed_at_ms`, never
   re-stamped, so its age (`sample_ms − observed_at_ms`) stays measurable. Health reports a per-stream
   `freshness`:

   | Freshness | Meaning |
   |---|---|
   | `fresh` | age ≤ cadence |
   | `aging` | cadence < age ≤ limit |
   | `stale` | age > limit |
   | `disconnected` | the stream's connection is down |
   | `reconnecting` | no data since the latest connect |
   | `not_ready` | no observation yet |

   A stale required stream is a hard health reason, so HEALTHY is impossible. A dead stream cannot hide behind
   other traffic on its shared connection, because freshness is per stream.

3. writes are not stopped by the disk guard.

Otherwise the boundary is missing, and a gap records it.

**`unchanged`.**
- `unchanged = true` means no newer update was received; it is not a staleness flag.
- Depth `lastUpdateId` changes on any book change, including changes beyond level N, so `unchanged = false` with
  identical top-N arrays is legitimate.
- Book `u` and depth `lastUpdateId` share the same order-book update-ID space per symbol, so they can be ordered
  against each other. Nothing is atomic across streams.

## 4. Identities (`obs_id`)

| Type | Format |
|---|---|
| book | `bt\|SYMBOL\|u\|c<cadence>\|t<sample_ms>` |
| depth | `dp<N>\|SYMBOL\|lastUpdateId\|c<cadence>\|t<sample_ms>` |
| market | `mkt\|t<sample_ms>` |
| candle | `SYMBOL\|tf\|open_ms` (= P1 `candle_id`; an identical re-fetch is an IDEMPOTENT duplicate) |
| clock | `clk\|serverTime` |
| universe | `uni\|stamp\|rule_version` |
| gap | `gap\|<boot8>\|<seq>\|<stream_key>\|<first_missing_ms>\|<last_missing_ms>\|<cause>` |
| lifecycle | `life\|<boot_id>\|<seq>\|<event>` |
| health | `hlth\|<boot_id>\|<seq>` |

`seq` is a per-boot sequence shared by gap, lifecycle and health records, so control records never collide.
In v1, gap IDs collided and records were lost (F55).

## 5. Point-in-time (PIT) join rule

To know what was knowable at time `T`, take records with `available_at_ms ≤ T`, and the latest per stream (apply
the age limits above).
- book / depth / market: `available = observed ≤ sample_ms`, so `sample_ms ≤ T` is also PIT-safe.
- candles: `available > close_time`, so a candle is never usable before it closed and was received.
- **Never** join on `exchange_event_time_ms`, gap end times or `.idx` `durable_ts_ns`.
- A gap record is written when the gap **closes**. Whether a gap was open at `T` is known in real time only from
  `health` records (`streams_not_observing`). Research using gap records knows the gap's extent only after it
  closed; label such use accordingly.

## 6. Gap records (`type = gap`)

| Field | Meaning |
|---|---|
| `stream_key` | `book\|SYM`, `depth\|SYM`, `market\|ALL`, `candle\|tf\|SYM`, `backpressure\|<type>` or `crash\|<type>` |
| `stream` | stream name |
| `first_missing_ms` / `last_missing_ms` | first and last missing boundary (inclusive) |
| `missing_samples` | `(last − first) / cadence + 1` |
| `duration_ms` | `last − first + cadence`; also `start_ms = first` and `end_ms = last + cadence` |
| `cadence_ms` | the stream's cadence |
| `cause` | the first cause |
| `causes` | all causes seen during the gap |
| `open_at_stop` | the gap was still open when the run stopped |

**Causes:**

| Cause | Meaning |
|---|---|
| `never_ready` | no first observation by the deadline (30 s Tier-0 book / depth / market; 120 s Tier-1/2 book, from WS start) |
| `ws_disconnect_reconnect` | the stream's own connection was down |
| `conn_data_stale` | connection up but no data messages for 10 s |
| `stale_stream` | stream's own value older than its limit |
| `sampler_stall` | the boundary was processed more than 2 s late (event-loop stall), or the hold window was exceeded so the PIT value could not be proven (never guessed) |
| `awaiting_post_reconnect_data` | the connection was back, but no value had yet been received since the reconnect |
| `banned_418` | Binance ban; all activity stopped |
| `disk_hard_stop` | observations refused by the disk guard |
| `backpressure_or_rejected` | queue shed or record rejected |
| `candle_fetch_failed:<status>` / `candle_unexpected_response` / `candle_exception` | candle not fetched |
| `candle_fetch_interrupted_at_stop` / `candle_not_fetched_at_stop` | the run stopped before the candle was fetched (recoverable) |
| `candle_not_listed_yet` | klines returned `[]` and the symbol's first-ever candle (`first_open_ms`, in the gap) opens later: nothing exists to capture |
| `crash_recovery` | interval lost to a crash, from the `.partial` salvage |

Book, depth and market gaps are **irreplaceable**: never bridged or interpolated.

## 7. Health semantics

`health` raw records are written every 60 s and on every state change. The payload holds:
- `state`, `reasons`, `startup_reasons`, `warnings`;
- `streams_by_state`, `streams_not_observing`;
- `tasks` (beat ages), `task_failures`, `writer` (alive, beat, durable lag);
- queue, loop lag, counters, clock, disk.

**States:**

| State | Meaning |
|---|---|
| `HEALTHY` | **all** of the following hold: |
| | - every required task (sampler, candles, clock, disk, health, watchdog) is alive with its beat ≤ max(2 × period, 3 s), plus 30 s of scheduling slack for candles and clock; no task failure in the last 10 min; |
| | - the writer thread is alive, its beat is ≤ 5 s old, durable lag ≤ 10 s, with no write errors and no rejected records; |
| | - every expected stream is acknowledged (or subscribed via URL), observed, fresh, on a data-live connection, with no gap older than 3 × cadence; |
| | - expected = acknowledged = observing; |
| | - not at disk hard stop and not banned; |
| | - the clock probe is ≤ 1,200 s old and `abs(skew) − uncertainty ≤ 500 ms`; |
| | - no handler exception in the last 10 min and no open queue drops; |
| | - no wall-clock step in the last 10 min, no `seq_reset`, no quarantined segment, no failed emit. Warnings (not hard): malformed, unknown stream or event, `seq_regression`, `recv_clock_regression` |
| `STARTING` | only startup reasons, each inside its deadline |
| (`awaiting_post_reconnect:<stream>`) | hard reason: the stream has received nothing since its connection's most recent (re)connect, so it is not yet observing again |
| `DEGRADED` | any hard reason (listed) |
| `DEGRADED_DISK` | disk hard stop |
| `BANNED_418` | Binance ban |
| `STOPPING` | stop in progress |
| `STOPPED` | the writer finished and 0 `.partial` files remain |
| `STOPPED_INCOMPLETE` | the stop did not complete cleanly (exit code 2) |
| `FAILED` | writer dead (exit 3) or a task failed repeatedly (exit 4) |

**Final stop state.** Written out-of-band to `control/stop-<boot8>.json` after the writer has finished: state,
exit code, reason, `writer_finished`, leftover partials, counters. The `stop` lifecycle record carries the full
counters as well.

**Sequence resets.** A per-stream `u` / `lastUpdateId` that goes backwards is rejected (`seq_regression`, a
warning). After 20 consecutive regressions the new sequence is accepted as an exchange-side reset: lifecycle
`seq_reset` plus a hard health reason.

**Sequence continuity across sockets (collector ≥ 1.5.0, continuous mode; bounded mode keeps the rule above).**
- Each WebSocket session is a socket epoch (`ws_connected.epoch`). An older id from a socket whose own order is
  intact is a `seq_stale` copy:
  - it is discarded and counted, and is neither a regression nor persisted;
  - it is tolerated for `seq_catchup_timeout_s` (30 s) after the later of its behind-run start and the receipt of
    the accepted value.
- `seq_reset` (lifecycle `cause`) is one of:
  - `in_socket_regression`: the same socket went backwards 20 times in a row;
  - `catchup_timeout`: a socket stayed behind beyond that window.
- Rotations hand off per stream. See `docs/p2/P2F_ROTATION_SEQ_CONTINUITY.md` for:
  - lifecycle `ws_handoff` (old final sequence and catch-up point per stream);
  - lifecycle `ws_superseded_closed`;
  - lifecycle `seq_regression`;
  - the `rotation_handoff_incomplete:<conn>` WARNING incident.
- **Bounded connection recovery (collector ≥ 1.6.0).** Every session end is bounded and never waits on the peer:
  - Order: graceful close for at most `ws_close_grace_s` (3 s), then the TCP transport is aborted, then the session task is cancelled. Each later step allows `ws_abort_wait_s` (2 s), so the hard bound is 7 s.
  - The bound applies to forced reconnects (data stall, subscribe timeout, handler-error burst), the 418 suspend, rotation close and shutdown.
  - Each end is recorded as lifecycle `conn_recovery`, with `{conn, reason, outcome, gen, ms}`. `outcome` is one of `graceful`, `aborted`, `abort_unavailable`, `cancelled`, `wedged`, `no_session` or `interrupted`.
  - **Wedged:** a session still alive after all three steps is `wedged`. The connection object is retired (lifecycle `ws_conn_replaced`) and the `conn_recovery_failed:<conn>` CRITICAL latched incident is raised.
  - **Generation ownership:** a retired object, or a message from an obsolete session generation, is never delivered. Such messages are counted in health `ws[].stale_dropped`.
  - **Health `ws[]`** also carries `gen`, `recovering`, `wedged`, `last_recovery` and `outage_ms`.
- **Connection incidents (collector ≥ 1.6.0, continuous mode).** The outage clock starts at the connection's last data message, so a socket that is up but silent counts as an outage.
  - `conn_outage:<conn>`: DEGRADED, state-like. Opened once when the connection is not data-live for `conn_outage_incident_s` (60 s), with lifecycle `conn_outage_open`. Resolved when it is data-live again, with lifecycle `conn_outage_resolved` carrying `{start_ms, duration_ms, recovery_failed}`. There are no per-tick updates.
  - `conn_recovery_failed:<conn>`: CRITICAL, **latched** (needs an operator acknowledgement). Raised once per outage at `conn_recovery_fail_s` (600 s), or for a wedged session.
  - `observation_loss:tier0`: WARNING, **latched**. Raised when a gap of `tier0_loss_incident_s` (60 s) or longer closes on a tier-0 bookTicker or depth stream, or on `!miniTicker@arr`, during running operation (irreplaceable gaps only; candle gaps are recoverable). It is not raised for gaps already explained by a stop or writer incident (`open_at_stop`, `never_ready`, `backpressure_or_rejected`, `disk_hard_stop`). The gap record itself is unchanged.
  - Transient per-stream staleness on a data-live connection raises no incident; its gap record and health reason are unchanged.
  - These are additive control-payload changes (lifecycle events, health fields, incident keys). Record envelopes and sampled-record semantics are unchanged, so `schema_version` stays 2, as for collector 1.1.0–1.5.0.
- **Session-end metadata and reconnect flapping (collector ≥ 1.6.1). Both are off by default; with both off the dataset is identical to 1.6.0.**
  - `ws_session_end_events` (config, default `false`): every ended WebSocket session writes one lifecycle `ws_session_end` with metadata only (never payloads): `{conn, gen, connected, duration_ms, kind, initiator, close_code, exc_type, handshake_status}`.
  - `kind` is one of `remote_close`, `abnormal_end` (close code 1006, set locally, never received), `stream_ended` (iterator ended without a code), `local_end` (our bounded end, rotation or shutdown), `local_cancel`, `ping_timeout`, `transport_error`, `handshake_rejected`, `timeout`, `transport_failure`, `unexpected`, `closed` (a CLOSING/CLOSED message type; aiohttp 3.14 ends the iterator before delivering these) or `unknown` (no classified path ran).
  - `initiator` is `remote` only with positive evidence (a peer close code other than 1006, or a missing PONG), `local` for our own ends, otherwise `unknown`.
  - `conn_flapping_enabled` (config, default `false`): `conn_flapping:<conn>` WARNING, state-like, not latched. It opens when `conn_flapping_max` (10) sessions of one connection end within `conn_flapping_window_s` (1800 s), with lifecycle `conn_flapping_open` `{conn, events_in_window, window_s, first_ms}`.
  - The episode resolves after `conn_flapping_clear_s` (1800 s) without an ended session, once the window count is below the threshold. It resolves with lifecycle `conn_flapping_resolved` `{conn, episode_events, since_ms, last_ms, duration_ms}`.
  - An episode left open by an earlier boot is resolved at the next watchdog tick (lifecycle `conn_flapping_resolved` with `previous_boot: true`). A 1.6.0 collector does not resolve it, so after a rollback it stays a WARNING until it is acknowledged.
  - Every ended session counts, including planned rotations (`local_end`, about one per connection per 23 h) and failed connects. A continuous outage stays below the default threshold (backoff 2–32 s, then 15 min cooldown: at most about 8 attempts per 30 min); `conn_recovery_failed` covers it.
  - The threshold is a candidate value, not an approved production value.
  - A 1.6.0 collector refuses a config file that contains these keys (`unknown config keys`). A rollback to 1.6.0 must restore the previous config file.
  - These are additive control-payload changes. `schema_version` stays 2.
- **Optional live-health views (development candidate after 1.6.1; not released, not deployed; `VERSION` unchanged).**
  Both are off by default. The keys are not part of `DEFAULTS`: an absent key, or one set to exactly its default, is
  dropped from the effective config, so `config_hash`, the run record and the health file are byte-identical to 1.6.1.
  Neither view changes `health` raw records, gap records, gap accounting, sealing or the verifiers. Raw records always
  carry the unfiltered `state` / `reasons` / `warnings`. Code: `healthview.py`.
  - `health_state_split` (default `false`): the live `health/collector_health.json` gains `integrity_state` and
    `coverage_state` (`OK` / `WARNING` / `STARTING` / `DEGRADED`, or `NOT_EVALUATED` in stop / failure states).
    `state` and every existing key are unchanged.
    - Integrity covers writer, certifier, disk hard stop, write errors, rejected records, quarantine, failed emits,
      `seq_reset`, queue drops and incidents of severity DEGRADED or CRITICAL. Duplicate obs_ids dropped by the writer
      give WARNING.
    - Coverage covers stream freshness, gaps, acknowledgements and connection data-liveness.
    - Tasks, clock, ban, handler exceptions and universe refresh are neither. An unknown reason counts as integrity.
  - `health_coverage_tiering` (default `false`): in the live file only, a DEGRADED evaluation whose only hard reasons
    are `stale:` / `gap_short:` / `gap_open:` with gap cause `stale_stream` becomes `state` HEALTHY plus the warning
    `coverage:streams_stale:<n>` (and `coverage_tolerated:<reason>` per moved reason). This needs:
    - fewer than `health_coverage_max_streams` (K) affected Tier-1/2 book or depth streams;
    - each of them affected for less than `health_coverage_max_age_s` (T) seconds. The age is the longest of the
      episode age, the open-gap extent and the time past the stream's stale bound.
    - Everything else stays DEGRADED immediately: Tier 0, `!miniTicker@arr`, any other gap cause, age at or above T,
      a connection not data-live, a stream not ready, failed or awaiting post-reconnect data, and every integrity or
      operational reason.
    - Clearing needs 2 consecutive clean evaluations. Until then the stream keeps its episode age and counts toward K.
      A stream that was not tolerable during its episode keeps the file DEGRADED (`coverage_clearing:<stream>`).
    - The unfiltered state is in the file as `coverage_policy.raw_state`. The `health` record cadence follows the
      unfiltered state.
    - K = 2 and T = 120 s are **candidate placeholders that need owner approval**. Nothing enables tiering.
  - A 1.6.1 collector refuses a config file that contains these keys (`unknown config keys`). A rollback must restore
    the previous config file.

**Clock records** are exempt from the "exchange time in the future" rejection, because `serverTime` ahead of the
host is exactly what they measure. Clock probes never trip the REST circuit breaker. A failed round is visible as
lifecycle `clock_round_failed` and is retried after 30 s.

## 8. Missing-data taxonomy

| Situation | Representation |
|---|---|
| no exchange update | `unchanged = true` (book / depth) |
| not yet observing (startup) | before the first record, within the deadline (lifecycle `stream_ready`) |
| never observed | `never_ready` gap plus a lifecycle record |
| disconnected / stale / stall / ban / disk / backpressure | gap cause (section 6) |
| writer failure | quarantine log plus health / lifecycle plus `control/fatal-*.json` |
| corrupt segment | quarantine plus a verifier failure |

## 9. Run record (`runs/run-<boot_id>.json`)

The start lifecycle record embeds the full run record and its SHA-256. It holds:
- `build`: git commit, image tag, build time, and the image ID claimed at runtime (verified by the gate script);
- `code`: SHA-256 per packaged file and a combined value;
- `runtime`: Python and package versions;
- the full effective `config` and `config_hash`;
- `semantics`: sample semantics, clock method, stale limits, deadlines;
- `sampling_profile`: cadences, `depth_levels`, candle timeframes;
- `universe`: rule version and snapshot;
- `endpoints`;
- `expected_streams` (stream, kind, symbol, tier, cadence, depth N, connection);
- `schema_doc` (file, SHA-256);
- `host_label`.

## 9a. Universe evaluation (`tiers-v2`, R04 / F25 / F42)

Every evaluation is an immutable artifact `universe/universe-<stamp>-<boot8>.json`. It is also written as a raw
`universe` record whose payload equals the file plus `file` and `sha256`. Its `universe_id` is
`uni|<stamp>|tiers-v2`. Fields:
- `tier0`, `tier1`, `tier2`, `hysteresis_members`, `eligible_count`, `candidate_count`, `inputs_sha256`;
- `thresholds`, including the stablecoin and fiat bases;
- `ranking` rule, `prior_universe_id`, `validation` statistics;
- `source`: for `exchangeInfo` (`permissions=SPOT`, **all statuses**) and `ticker/24hr?type=MINI`, the REST path,
  params, `recv_ns`, SHA-256 of the raw body, `raw_file` (`universe/raw-<stamp>-<boot8>-<k>.json.gz`, 0444),
  `raw_file_sha256` and `body_bytes`. The raw bodies are kept so the evaluation can be re-derived exactly;
- `evaluated_ms`, `applied`, `trusted`.

**`candidates`** is one entry per candidate, sorted by symbol: every USDT-quoted symbol in `exchangeInfo` (any
status), plus USDT tickers absent from `exchangeInfo`, plus Tier 0. Each entry holds:
- `symbol`, `status`, `base`, `in_exchangeinfo`, `in_ticker`;
- `quote_volume_raw`, `open_raw`, `last_raw` (verbatim strings), `quote_volume`, `change`;
- `eligible`;
- `excluded_reason`: one of `not_in_exchangeinfo_spot`, `status_<X>`, `stable_or_fiat_base`,
  `non_ascii_or_non_alnum`, `no_ticker`, `invalid_ticker`, `below_min_quote_volume`, `rank_cut`,
  `tier0_not_trading`, or null;
- `volume_rank` (among eligible symbols), `tier`, `hysteresis_reason`.

**Rules:**
- **Eligible** means TRADING, a non-stable base, an ASCII alphanumeric symbol and a valid ticker.
- **Tier 1** is the eligible symbols with quote volume ≥ the threshold, top `tier1_max` by quote volume
  (descending, ties by symbol ascending), plus hysteresis members: prior Tier 1/2 members still eligible, from the
  newest trusted applied universe in the same data directory within `tier1_hysteresis_days`.
- **Tier 2** is the top `tier2_top_volume` of that set by volume, plus the top `tier2_top_movers` by
  `|last/open − 1|`, capped at `tier2_max`. Tier 2 members are removed from Tier 1.

`inputs_sha256 = sha256(json.dumps([[symbol, status, base, quoteVolume_raw, openPrice_raw, lastPrice_raw], …]))`
over all candidates in symbol order. `change` is stored unrounded and used for ranking.

**Effective from.** The lifecycle record `universe_active` carries `universe_id`, `file`, `sha256` and
`effective_from_ms = ws_start_ms`. This answers "which symbols were eligible at T and exactly why" from the data
directory alone. The candidate set is what the exchange reported at evaluation time; delisted symbols are never
reconstructed from today's exchange data.

**Sanity checks (F42).** A response is never authoritative unless all of these hold:
- well-formed, with the required fields;
- non-empty, with no duplicate symbols;
- symbol, quote and base consistent;
- at least `universe_min_usdt_trading` TRADING USDT symbols;
- ticker coverage of those symbols at least `universe_min_ticker_coverage`;
- invalid numeric fraction at most `universe_max_invalid_fraction`;
- Tier 1/2 membership change against the prior universe at most `universe_max_tier1_change`;
- at most `universe_max_liquid_missing` (3) USDT tickers with quote volume ≥ the Tier-1 minimum are missing from
  `exchangeInfo`, so `exchangeInfo` is not partial;
- Tier 0 is TRADING with a valid ticker.

**Initial load (F25).** At most `universe_load_attempts` attempts, with `universe_retry_backoff_s`. Each failure is
a lifecycle `universe_attempt_failed` with its problems. If every attempt fails, the collector **fails closed**:
- lifecycle `startup_failed` and `control/fatal-*.json`;
- health FAILED, no WebSocket opened;
- graceful writer stop, final `control/stop-*.json`, exit code 5.

There is no fallback to an unknown or partial universe.

**Refresh (F42).** Refresh is deterministic but not scheduled in E1; daily refresh and re-subscription are F10.
- A trustworthy result is persisted with `applied=false` until F10 exists.
- A failed or suspicious result never replaces the active universe: the previous one is kept, and the collector
  is DEGRADED (`universe_refresh_failed`) until a refresh succeeds.

`tiers-v1` data (the original G2 and the G2 Repeat) predates this section: tiers only, no candidates.

## 9b. Controlled reconnect test (G3)

`reconnect_test_at_s > 0` schedules exactly ONE internal, predeclared `force_reconnect` of `reconnect_test_conn` at
`ws_start + reconnect_test_at_s`. It is recorded as lifecycle `controlled_reconnect_test`. The socket closes and the
normal path must recover:
- `ws_disconnected` lifecycle and an immediate health record;
- backoff, then `ws_connected`;
- the URL stream plus re-sent SUBSCRIBE requests, with `subscribe_ack`.

Until a stream receives a value **after** the reconnect, its boundaries are gaps (`ws_disconnect_reconnect`, then
`awaiting_post_reconnect_data` / `conn_data_stale`). Pre-reconnect values are never persisted after the reconnect.
Health returns to HEALTHY only when every stream observes again. Lifecycle `controlled_reconnect_recovered` records
the time all streams of the connection have a post-reconnect persisted sample.

A rotation test and a reconnect test are mutually exclusive in one run.

## 10. Clock records

- **Method:** `min_rtt_of_3_midpoint_v1`. Three `/api/v3/time` probes; the minimum-RTT probe is kept.
- `skew_ms = serverTime − (t0 + t1)/2`; `uncertainty_ms = rtt/2`.
- State thresholds apply to `abs(skew) − uncertainty`.
- RTT asymmetry of the market-data endpoint is uncertainty, **not** host skew.
- The payload includes every probe.

## 10a. Verification contract (independent verifier, `verifier/verify_independent.py`)

**Expected boundaries per stream.** Every cadence multiple `b` with `ws_start_ms < b < stop_requested_ms`. Each
one must be one of:
- persisted;
- inside a gap;
- startup-excused, only if `b` precedes the first-observation deadline, the receive time of the first persisted
  value, **and** the claimed `stream_ready.ready_ns` (ns resolution).

**Expected candles.** For each timeframe and symbol:
- the catch-up candle, if `ws_start + 375 s < stop`;
- every candle whose close boundary `B` satisfies `ws_start < B` and `B + 375 s < stop`.

Each must be present or gap-covered. Fetches run at `B + 5–15 s`, with jobs spread over ≤ 300 s.

**Clock records** are at most 1,200 s apart, from `ws_start` to stop, with the first within 120 s.

**Health records** are at most `interval + 15 s` apart, from start to stop.

**Control-record sequence numbers** (gap, lifecycle and health share one counter) must be contiguous `1..N`.

**Acceptance** (`--acceptance g2r`) is a pinned, predeclared specification inside the verifier that the run's
configuration cannot loosen.

## 11. Schema evolution policy

- A record's meaning is fixed by its `schema_version` plus this document.
- New fields or new semantics require a new `schema_version`, a new versioned copy of this document, and a writer
  version bump.
- Readers must branch per version.
- Derived datasets must record the schema versions they consumed.
- Raw segments are immutable and never migrated in place.
