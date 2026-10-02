# P2-E1 G3 acceptance specification `g3-recommended-6h-v1` (pinned BEFORE the run)

**Machine-readable source:**
- `p2_forward/verifier/verify_independent.py` constant `G3_SPEC`;
- exported, byte-identical, as `p2_forward/verifier/specs/g3-recommended-6h-v1.json` (a test enforces equality).

**Evaluation:**
```
verify_independent.py <dataset> --acceptance g3 \
    --expect-image-id <id> --expect-commit <sha> \
    --resources-tsv G3_resources.tsv --monitor-log G3_monitor.log
```

Thresholds are fixed here and are NOT derived from G3 results.

## Scope (P2-E0 recommended profile, owner decision D1)

| Item | Pinned value |
|---|---|
| Duration | real 21,600 s (6 h), self-stop on `max_runtime`; tolerance ±5 s |
| Universe | rule `tiers-v2`, evaluated once at start from `exchangeInfo?permissions=SPOT` (all statuses) and `ticker/24hr?type=MINI` |
| Tier 0 | BTCUSDT, ETHUSDT |
| Tier 1 | quote volume ≥ $10M; Tier 1 + Tier 2 ≤ 150; non-empty |
| Tier 2 | top 20 by volume + top 10 movers, ≤ 30 |
| Hysteresis | none expected (fresh dataset, no prior universe); any prior is a failure |
| Universe load | ≤ 2 failed attempts (F25 allows 3); `startup_failed` is forbidden |
| Universe history | the active universe is **independently reconstructed** by the verifier from the persisted per-candidate raw inputs (eligibility, exclusion reason, rank, tiers, hysteresis); `universe_active.effective_from_ms = ws_start`; file SHA-256 = record = lifecycle |
| Expected streams | for every Tier 0/1/2 symbol: `<s>@bookTicker` + `<s>@depthN`, plus `!miniTicker@arr`. Each must be present, acknowledged (URL or SUBSCRIBE ack) and observed. An absent stream fails |
| Cadence (ms) | Tier 0 book 1,000 / depth 1,000; Tier 2 book 2,000 / depth 5,000; Tier 1 book 10,000 / depth 60,000; market 60,000; clock 600,000 |
| Depth N | Tier 0: 20; Tier 1: 10; Tier 2: 10 (explicit `depth_levels`) |
| Candles | 15m / 1h / 4h / 1d for every universe symbol. One budget-spread catch-up round (300 s), then boundary rounds at B + 5–15 s (120 s / 300 s spread) |
| Clock | min-RTT of 3 probes every 600 s; spacing ≤ 1,200 s; first probe ≤ 120 s; `abs(skew) − uncertainty ≤ 500 ms` |
| Startup | boundaries before a stream's first message are excused only before the first-observation deadline (Tier-0 book, depth, market: 30 s; Tier-1/2 book: 120 s, measured from WS start). STARTING health is allowed only in the first 150 s; `never_ready` is forbidden |
| Gaps | every non-persisted boundary after readiness lies in exactly one unique gap record. Allowed causes: `ws_disconnect_reconnect`, `conn_data_stale`, `stale_stream`, `awaiting_post_reconnect_data`. Per stream, outside the controlled reconnect: ≤ max(2, 0.5 % of expected boundaries); each gap ≤ 120 s. Unexplained misses: 0 |
| Candle gaps | only `candle_fetch_interrupted_at_stop` / `candle_not_fetched_at_stop` (candles whose round was still running at the stop); any fetch failure fails |
| PIT | `recv_ts_ns ≤ sample_ms·10⁶` for every sampled record. Independent ages: depth ≤ 2 s, Tier-0 book ≤ 120 s, market newest component ≤ 10 s. No persisted sample while its connection was down. No persisted value received before its connection's most recent (re)connect |
| Health | records ≤ 75 s apart; ≥ 1 HEALTHY; non-HEALTHY records (excluding STARTING ≤ 150 s and STOPPING) ≤ 10 %, and only DEGRADED with network reasons (`stale:`, `conn_not_data_live:`, `gap_open:` / `gap_short:` with an allowed cause, `not_acked:`) |
| Forbidden lifecycle | `fatal`, `task_failed`, `handler_exception`, `subscribe_failed`, `subscribe_timeout`, `never_ready`, `ws_task_dead`, `binance_ban_418`, `disk_hard_stop`, `seq_reset`, `wall_clock_step`, `candle_exception`, `startup_failed`, `universe_refresh` |
| Zero counters | malformed, unknown stream / event, handler errors, `seq_regression`, `seq_reset`, write errors, quarantined segments, duplicates, `recv_clock_regression`, wall-clock steps, task failures, subscribe failed / timeout, `never_ready`, drops, emit failures, writer rejections, rejected records |
| Provenance | run record with commit, image tag, image ID and build time (none `unknown`); image ID and commit equal the expected values; `SCHEMA-v2` installed with matching SHA-256; control-sequence numbers contiguous |
| Certification | every segment certified (SHA-256 = sidecar = manifest); 0444; `.idx` counts match; 0 `.partial`; 0 quarantine; final `control/stop-*.json` = STOPPED, exit 0, 0 partials |
| Queue / drops | 0 drops (queue 50,000 against about 40 records/s) |
| REST | own budget 300 weight/min with 20 reserved for urgent calls (clock, universe); IP weight seen ≤ 2,400; 0 × HTTP 429 / 418. Own-budget deferrals are allowed (that is the limiter working) only if every expected candle is still present |
| Resources | container exit 0, no OOM, 0 restarts; memory peak ≤ 345 MiB (90 % of 384); PIDs ≤ 64. CPU is capped at 0.5 by the container and reported; a starved event loop shows up as forbidden `sampler_stall` gaps |
| Storage | measured and projected to MB/day; **report only**, compared with the P2-E0 design band ±50 % (122–446 MB/day) |

## Justified non-zero tolerances

- **Runtime ±5 s.** Stop-processing jitter; the G2 Repeat measured +1 ms.
- **Gap budget max(2, 0.5 %) per stream, each gap ≤ 120 s.**
  - Exchange or network delivery hiccups (a depth push delayed by more than 2 s, a dropped TCP session) are real
    events outside the collector's control.
  - Correctness is that they are recorded exactly: 0 unexplained boundaries, unique IDs, allowed causes. The budget
    only bounds how much loss an acceptance run may contain.
  - The same rule was pinned for the G2 Repeat before that run.
- **Health ≤ 10 % non-HEALTHY.** The only permitted reasons are network-attributable; any internal reason fails.
- **Controlled reconnect** (below):
  - disconnect detection ≤ 5 s;
  - reconnect ≤ 60 s (backoff 1.4–2.6 s plus handshake; covers up to about 3 failed attempts);
  - recovery of every stream ≤ 180 s after the reconnect. Tier-1/2 bookTicker is event-driven: a quiet symbol's
    first post-reconnect update can legitimately take long, and 180 s exceeds the 120 s first-observation deadline.
- **Universe attempts ≤ 2 failed.** F25 allows 3 attempts before failing closed.
- **Memory ≤ 345 MiB.** A 10 % margin under the hard 384 MiB container limit.
- **Clock excess ≤ 500 ms.** The WARN threshold; the G2 Repeat measured 0.

## Controlled reconnect procedure (exactly one; predeclared)

- **Configuration** (`configs/g3-recommended-6h.json`): `reconnect_test_at_s = 10800`,
  `reconnect_test_conn = "conn0-book"`, `rotation_test_at_s = 0` (the two tests are mutually exclusive).
- **Trigger:** internal, by the collector itself. At `ws_start + 10,800 s` the task `reconnect_test_task` writes
  lifecycle `controlled_reconnect_test` (conn, `trigger_ms`, `planned_ms`), then closes the conn0 socket
  (`force_reconnect`). No external action touches the running collector; production is not involved.
- **conn0** carries every bookTicker stream (Tier 0/1/2) and `!miniTicker@arr`: one URL stream plus SUBSCRIBE
  chunks.

**Required evidence** (checked by `check_reconnect`):
1. `ws_disconnected` (conn0) within 5 s of the trigger; a DEGRADED health record between the disconnect and full
   recovery (health is written immediately on every connection transition).
2. `ws_connected` within 60 s.
3. The SUBSCRIBE set after the reconnect equals the initial set, and every stream is acknowledged after the
   reconnect.
4. For every conn0 stream:
   - the first persisted sample after the disconnect has a value received after the reconnect, never a
     pre-disconnect value;
   - the outage and pre-data boundaries are gaps with allowed causes;
   - full recovery within 180 s.
5. The first HEALTHY record after the disconnect is not earlier than full recovery of every conn0 stream.
6. Exactly one `controlled_reconnect_recovered` lifecycle record (from the collector).

Gaps that start in the window from the trigger to recovery + 180 s are judged by these rules instead of the
background gap budget.

## Stop conditions during G3
- **Self-stop** at 21,600 s.
- **External backstop:** the monitor sends `docker stop` at 22,200 s. If it fires, the stop reason is `signal`,
  which fails acceptance.
- **Collector-internal fail-closed stops:**
  - writer dead (exit 3);
  - repeated task failure (exit 4);
  - no trustworthy initial universe (exit 5);
  - disk hard stop: observations refused, a correctness failure for acceptance.
- **Any material correctness failure:** STOP, report, and do not continue counting the same run after a fix.
