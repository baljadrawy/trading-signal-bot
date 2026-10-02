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
| `universe/universe-<stamp>-<boot8>.json` | universe snapshot used by the run |
| `docs/SCHEMA-v2-<sha8>.md` | this document |
| `control/*.json` | out-of-band markers (disk hard stop, fatal); tiny, fsynced, 0444 |
| `quarantine/` | failed or salvaged segment originals (never deleted) |
| `health/collector_health.json` | **live** heartbeat only (overwritten every 10 s); history is in the `health` raw records |

`.partial` files are uncertified and never research data.

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

   | Stream | Limit |
   |---|---|
   | depth | 2 s (partial depth is pushed every 1 s; one missed push tolerated) |
   | Tier-0 book | 120 s; within it, `unchanged = true` means no top-of-book change was received |
   | Tier-1/2 book | none (event-driven; silence > 15 min is flagged `stale_suspect` in health) |
   | market | the newest component ≤ 10 s |

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
