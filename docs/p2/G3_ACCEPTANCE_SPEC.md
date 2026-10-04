# P2-E1 G3 acceptance specification `g3-recommended-6h-v8`: ACCEPTED (owner, 2026-10-04) as the current forward-collector acceptance specification

v8 acceptance always uses the STRICT classifier with live v8 identity evidence. The `historical` classifier mode
(schedule / no-log / truncated-parent tiers) was used ONLY to resolve G3V7-F1 for the completed G3-v7 run and is
never an acceptance rule. v6 and v7 remain historical specifications, byte-for-byte; their results are not
rewritten. G3-v7 remains formally FAIL under v7.

v8 = **v7 unchanged** except the cgroup process-set criterion (test-enforced: only `name` and the new `cgroup` keys
differ; every v7 cgroup key is unchanged). The v7 file is byte-identical (`9dfe911d…`).

**New pinned requirements (`cgroup.process_roles`, `require_process_detail`, `require_healthcheck_log`,
`require_healthcheck_config`, `escape_check`):**
- **collector:** exactly `python -m p2_forward`, container PID 1.
- **certifier / tracker:** the multiprocessing spawn / resource-tracker commands, parent = the collector; exactly 1
  certifier after startup; at most 1 tracker.
- **`container_healthcheck`:** exactly the pinned Docker HEALTHCHECK (`Config.Healthcheck` equal to the image's,
  interval 30 s, timeout 5 s). Its stages `runc init`, `/bin/sh -c <cmd>` (including its pre-exec fork) and
  `python -c <probe>` are each accepted only if ALL hold:
  - exact command;
  - own cgroup = the container scope;
  - no known wrong parent (shim / shell / this container's runc only; the probe's parent must be the shell; the probe
    has no children);
  - inside a run window of Docker's own health log;
  - lifetime ≤ 7 s;
  - consecutive executions ≥ 27.5 s apart;
  - ≤ 1 probe and ≤ 8 processes per execution.
- **Partial transients:** accepted only with recorded ancestry inside a run whose chain is exactly identified, or (gone
  before any read) PID-adjacent to such a chain.
- **Failure codes:** anything else → `ACC_CGROUP_PROCESS_SET`. Escape of a collector descendant → `ACC_PROCESS_ESCAPE`.
  Missing identity / log / config → `ACC_CGROUP_PROCESS_EVIDENCE_MISSING` / `ACC_HEALTHCHECK_LOG_INCOMPLETE` /
  `ACC_HEALTHCHECK_CONFIG_NOT_SPEC`.
- **Evaluation:** add `--healthcheck-log G3_healthcheck_log.jsonl --healthcheck-config G3_healthcheck_config.json`.
  `--acceptance g3v7` keeps evaluating v7 unchanged.

---

# Superseded proposal / G3-v7 run spec: `g3-recommended-6h-v7` (unchanged)

v7 (G3-F4) = **v6 unchanged** plus requirements for the process-isolated certifier and the observability added
for G3-F4. No v6 value is altered or relaxed: a test enforces v7 ⊇ v6, and the v6 file is byte-identical with
SHA-256 `20c95733…`.

| Item (v7 additions) | Pinned requirement |
|---|---|
| Certifier architecture | run config `certifier_mode = process` and `certifier_ready_timeout_s = 10`, else `ACC_CERTIFIER_ARCHITECTURE_NOT_SPEC` |
| Readiness / death semantics | readiness = the worker itself publishes its first heartbeat; health shows `certifier_not_ready` as STARTING ≤ 10 s, then hard. Worker death → `certifier_dead` lifecycle (forbidden, as in v6) and `certifier_restarted_10min` (hard). `certifier_restarts` = 0 and `certification_failures` = 0 (v6 zero counters, now mirrored from the worker) |
| One cgroup, 0.5 CPU total | gate-monitor cgroup TSV (`--cgroup-tsv`, host sampled ≤ 20 s apart): `cpu.max = 50000 100000`, `memory.max = 402653184`, `pids.max = 64`. Between startup and the stop request, every sample shows exactly 1 collector + 1 certifier (resource tracker allowed, nothing else) in the container's own scope, with one certifier PID for the whole run |
| Instrumentation present | stop counters and every post-startup health record carry `instrumentation` with sampler lateness max/counts (≥ 100/200/500/1000/2000 ms), loop-pause max/counts and GC pause max / count ≥ 100 ms |
| Report-only (no new threshold) | cgroup throttled periods/time, average CPU, independently recomputed sampler-lateness distribution (verifier, from records), the collector's loop/GC values |
| Per-segment provenance (all specs with certifier metadata) | manifest `run_record` = the run's record file, except entries recovered or finalized before the run record existed (`MANIFEST_RUN_RECORD_MISMATCH`) |

**Evaluation (v7):**
```
verify_independent.py <dataset> --acceptance g3 \
    --expect-image-id <id> --expect-commit <sha> \
    --resources-tsv G3_resources.tsv --monitor-log G3_monitor.log --cgroup-tsv G3_cgroup.tsv
```

- Machine-readable source: `G3_SPEC` (built from `G3_SPEC_V6`), exported as
  `p2_forward/verifier/specs/g3-recommended-6h-v7.json`.

---

# Superseded: `g3-recommended-6h-v6` (pinned BEFORE the G3-v6 run; file unaltered)

v6 supersedes the unused v5 after the G3-F3 bounded review: certifier max pending 24 (> 2 × 9 record types), the stop marker's counters taken after the shutdown drain, mandatory certification metadata, orphan-sidecar and durable-block checks. v5 (G3-F3) added certifier and writer criteria; all v4 thresholds are unchanged (v4 file unaltered).

| Item (v5) | Pinned value |
|---|---|
| Writer hot path | heartbeat gap ≤ 5,000 ms (collector-measured maximum over the whole run); enqueue → fsync latency ≤ 10,000 ms (collector maximum **and** independent verifier measurement from `.idx` durable timestamps) |
| Certifier | policy equals the spec: max pending 24, oldest pending ≤ 900 s, heartbeat ≤ 10 s, shutdown grace 300 s. No `certifier_dead` lifecycle record; certification failures = 0; restarts = 0; health peak pending and age within the limits; no `.pending`, `.certifying` or temp sidecar left; certification metadata valid |
| Forbidden health reasons | every internal reason, including `writer_stale`, `writer_not_durable` and all `certifier_*` |

v4 adds the per-tier freshness thresholds (G3-F1, owner decision Option a). v3 remains unaltered in
`specs/g3-recommended-6h-v3.json`; its run was stopped as diagnostic only.

v3 supersedes v1 and v2 after the bounded pre-G3 review and its confirmation pass. Neither earlier version was
used for a run.

**Machine-readable source:**
- `p2_forward/verifier/verify_independent.py` constant `G3_SPEC`;
- exported, byte-identical, as `p2_forward/verifier/specs/g3-recommended-6h-v6.json` (a test enforces equality).

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
| Universe load | ≤ 2 failed attempts (F25 allows 3); `startup_failed` is forbidden. Sanity checks require: ≥ 350 TRADING USDT symbols; ≥ 99 % ticker coverage; ≤ 0.5 % invalid numerics; at most 3 liquid USDT tickers missing from `exchangeInfo` (delisting / permission edge cases; a partial response misses far more); Tier 0 TRADING with a valid ticker |
| Universe history | the raw `exchangeInfo` and ticker bodies are persisted (gzip, 0444, SHA-256 chain body → file → record). The verifier **rebuilds the candidate list from the raw bodies**, recomputes `inputs_sha256`, the counts, eligibility, exclusion reason, rank, tiers and hysteresis (loading the prior artifact if any), and checks PIT: source receive time and `evaluated_ms` ≤ `effective_from_ms = ws_start` |
| Expected streams | for every Tier 0/1/2 symbol: `<s>@bookTicker` + `<s>@depthN`, plus `!miniTicker@arr`. Each must be present, acknowledged (URL or SUBSCRIBE ack) and observed. An absent stream fails |
| Cadence (ms) | Tier 0 book 1,000 / depth 1,000; Tier 2 book 2,000 / depth 5,000; Tier 1 book 10,000 / depth 60,000; market 60,000; clock 600,000 |
| Depth N | Tier 0: 20; Tier 1: 10; Tier 2: 10 (explicit `depth_levels`) |
| Candles | 15m / 1h / 4h / 1d for every universe symbol. One budget-spread catch-up round (300 s), then boundary rounds at B + 5–15 s (120 s / 300 s spread) |
| Clock | min-RTT of 3 probes every 600 s; spacing ≤ 1,200 s; first probe ≤ 120 s; `abs(skew) − uncertainty ≤ 500 ms` |
| Startup | boundaries before a stream's first message are excused only before the first-observation deadline (Tier-0 book, depth, market: 30 s; Tier-1/2 book: 120 s, measured from WS start). STARTING health is allowed only in the first 150 s; `never_ready` is forbidden |
| Gaps | every non-persisted boundary after readiness lies in exactly one unique gap record. Allowed causes: `ws_disconnect_reconnect`, `conn_data_stale`, `stale_stream`, `awaiting_post_reconnect_data`. Per stream, outside the controlled reconnect: ≤ max(2, 0.5 % of expected boundaries); each gap ≤ 120 s. Unexplained misses: 0 |
| Candle gaps | only `candle_fetch_interrupted_at_stop` / `candle_not_fetched_at_stop` (round still running at the stop) and `candle_not_listed_yet`. The last is a new listing: klines returned `[]` and the symbol's first-ever candle opens after that window, with the evidence (`first_open_ms`) in the gap. The first-candle probe retries until the job deadline. Any fetch failure fails |
| Freshness (v4) | depth: Tier 0 2 s, Tier 2 15 s, Tier 1 180 s; book: Tier 0 120 s, Tier 1/2 600 s (hard); market newest component 10 s. Pinned in the spec; the verifier takes them from the spec itself, fails closed if a spec lacks them, and also requires the run's config to be equal. Time with a `stale_stream` reason is charged to the health time budget. Calibration and justification are in `P2E1_FIX_MATRIX.md` §G3 |
| PIT | `recv_ts_ns ≤ sample_ms·10⁶` for every sampled record. Independent ages checked against the pinned limits above. No persisted sample while its connection was down. No persisted value received before its connection's most recent (re)connect |
| Health | records ≤ 75 s apart; ≥ 1 HEALTHY. Non-HEALTHY **time** ≤ 5 % of the run, excluding the first 150 s, the reconnect window, and time whose only reasons are `gap_short:` / `gap_open:` with an allowed cause. Those gaps are already bounded per stream by the gap budget and are not charged twice. Records are not counted because they bunch around blips. Only DEGRADED with network reasons is allowed (`stale:`, `conn_not_data_live:`, `gap_open:` / `gap_short:` with an allowed cause, `not_acked:`, `awaiting_post_reconnect:`). **General rule:** a HEALTHY record never falls inside any open gap of any stream, from first missing boundary + 2 s (the sampler-stall bound) until the closing sample |
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
- **Health ≤ 5 % non-HEALTHY time** (gap-only time excluded; see above). The only permitted reasons are
  network-attributable; any internal reason fails.
- **≤ 3 liquid tickers missing from `exchangeInfo`.** A truncated or filtered response would miss tens to
  hundreds; delisted pairs or permission-set edge cases account for a handful. If more are missing, the start
  fails closed (exit 5). That is a startup stop, not a data result.
- **IP weight ≤ 2,400** is an IP-wide safety bound (shared host IP), not only the collector's share. Exceeding it
  fails the run, as a conservative choice.
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
     pre-disconnect value. For the market snapshot this applies to its newest component; older components are
     sample-and-hold state by design;
   - the outage and pre-data boundaries are gaps with allowed causes;
   - full recovery within 180 s.
5. No HEALTHY record before the reconnect. After it, health stays DEGRADED (`awaiting_post_reconnect:<stream>`) until every stream has received data since the reconnect, and no HEALTHY record may fall inside any open gap (general rule).
6. Exactly one `controlled_reconnect_recovered` lifecycle record (from the collector).

Only gaps of **conn0** streams lying **entirely** inside the window from the trigger to recovery + 180 s are judged
by these rules instead of the background gap budget. Gaps of other connections, or extending beyond the window,
are judged normally.

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
