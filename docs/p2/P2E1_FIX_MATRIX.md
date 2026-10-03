# P2-E1 consolidated fix matrix (G2-Repeat revision)

Source of truth for the findings: evidence `p2e1-collector-bounded-20261002T114614Z/12_P2E1_CHECKPOINT.md`, and the
documents `07d`, `08`, `08b`, `08c` and `08d` in that directory.

**Column key:**
- **Req** (when the fix is required): R = before the G2 Repeat; G3 = before G3; C = before continuous mode;
  – = none.
- **Status:** PLANNED, then IMPLEMENTED and TESTED (updated after Phase D); DEFERRED; or NO_CHANGE.
- **Test:** `PF.*` = `tests/test_pending_fixes.py`, `RG.*` = `tests/test_regression_g2r.py`,
  `VI.*` = `tests/test_verify_independent.py`, `G0.*` = `tests/test_collector.py`.

Module abbreviations:

| Abbreviation | Module(s) |
|---|---|
| app | `p2_forward/app.py` |
| tracks | `p2_forward/tracks.py` (new: per-stream sampling and state machine) |
| tr | `p2_forward/transport.py` |
| wr | `p2_forward/writer.py` |
| gd | `p2_forward/guards.py` |
| rec | `p2_forward/record.py` |
| cfg | `p2_forward/config.py` |
| prov | `p2_forward/provenance.py` (new) |
| VI | `verifier/verify_independent.py` (new; imports nothing from `p2_forward`) |
| doc | `p2_forward/SCHEMA.md` (new; copied into the data directory) |

## Reliability series (F)

### Required before the G2 Repeat

| ID | Title | Module | Correction | Test |
|---|---|---|---|---|
| F1 | 8-message ring skips high-rate samples | tracks | Per stream: the `latest` message plus `held` boundary snapshots. When a message arrives at `r`, for the largest boundary `B < r`, if `latest.recv_ms ≤ B` then `held[B] = latest`. The lookup for `S` returns `latest` if `latest.recv_ms ≤ S`, else the first held entry with `B ≥ S`. The result is re-checked: `recv_ms ≤ S` or no value. This is exact for any burst size, with O(boundaries) memory bounded by the hold window | PF.burst_8 / 100, PF.delayed_sampler_and_boundary_edges, PF.high_rate_no_skips, RG.burst_1000_exact_boundary |
| F2 | gaps before first observation; wrong start; inflated duration | tracks | Explicit state machine. No gap before the first observation (startup excused until the deadline). A gap starts at the **first missing boundary** and ends at the last missing boundary; `missing_samples` and `duration_ms = last − first + cadence` | PF.never_observed_no_gap, PF.startup_transition…, PF.gap_start_end_and_count |
| F3 | gap cause uses any connection | tracks / app | Each stream is mapped to its own connection; the cause comes from that connection's state at boundary `S` | PF.gap_cause_uses_own_connection |
| F4 | low-rate book on a live connection treated as stale | tracks | Book on a **data-live** connection is persisted with `unchanged=true` (event-driven stream). Stale only beyond the per-tier limit (F40) | PF.low_rate_book… (Tier 0 ≤ 120 s), RG.tier1_low_rate_book_300s_unchanged |
| F5 | clock midpoint biased by asymmetric RTT | gd / app | Three probes; keep the minimum-RTT one; `uncertainty_ms = rtt/2`; state from `abs(skew) − uncertainty` | PF.clock_min_rtt_uncertainty, RG.clock_uncertainty_not_skew |
| F6 | `serverShutdown` rotation not idempotent | app | A per-connection `rotating` set; repeated events during a rotation are logged and ignored | RG.rotation_idempotent |
| F7 | untracked candle tasks at shutdown | app | All candle rounds and jobs are kept in a tracked set; cancelled and awaited at stop | RG.candle_tasks_tracked_and_cancelled |
| F8 | market component age / startup flag | app | Record-level `component_recv_ms` (per symbol), `startup_complete` (≥ 60 s after the market stream became ready), and components older than 24 h dropped and counted | PF.market_component_age_and_startup_flag, RG.market_component_24h_drop |
| F9 | DEGRADED during normal start | app | State is `STARTING` while every not-ready stream is inside its first-observation deadline | RG.health_starting_then_healthy |
| F19 | event-loop stall skips boundaries | app / tracks | The sampler processes **every** boundary from the last processed one up to `now − 1 ms` (`sample_until`). A boundary older than the hold window gets an explicit `sampler_stall` gap. `loop_lag_ms` is recorded | PF.sampler_stall_processes_every_boundary, RG.stall_beyond_hold_window_is_explicit_gap |
| F20 | handler exception kills the connection | tr / app | A per-message try/except calls `on_error` (counted, lifecycle, health reason). A catch-all in the run loop leads to reconnect with backoff. A burst of ≥ 50 handler errors within 60 s forces a reconnect | PF.handler_exception_does_not_kill_connection, RG.handler_exception_visible_in_health |
| F21 | crashed core task invisible | app | A supervisor wraps each required task: an exception leads to lifecycle `task_failed`, a health reason and a restart with backoff. More than 5 failures in 10 min leads to FAILED and a stop with a non-zero exit | RG.required_task_crash_supervised |
| F22 | SUBSCRIBE error hidden | tr / app | The ack `{"result":null,"id":n}` maps to the streams of that request. An error response leads to lifecycle `subscribe_failed`, the streams going to FAILED, and DEGRADED | PF.subscribe_error_is_reported, RG.subscribe_error_degrades_health |
| F23 | 418 leaves WebSockets open | gd / tr / app | `RateGuard.on_418` triggers the ban callbacks: every WS is closed immediately, run loops wait while banned, health is `BANNED_418`, and streams get a `banned_418` gap | RG.http_418_closes_all_ws |
| F26 | verifier: idempotent vs conflicting duplicates | VI | candle / universe: identical payload = IDEMPOTENT (allowed), different payload = CONFLICTING (fail). Any other type duplicated = fail | VI.repeated_candle_fetch_idempotent, VI.conflicting_candle_fails |
| F27 | verifier shares collector code | VI | A new standalone verifier using only the stdlib, with its own field list, `obs_id` formatter, SHA-256, cadence / boundary logic and gap reconciliation. A test asserts that it does not import `p2_forward` | VI.no_collector_imports |
| F28 | message-rate / loop-lag metrics | app | Health and health records carry `msgs_per_s` per connection (60 s window), `loop_lag_ms` (last and max over 60 s) and the sampler catch-up count | RG.metrics_present |
| F36 | health age from emit time | app | Per-stream `last_msg_age_ms` taken from the observation receive time | RG.health_age_from_observation |
| F37 | no SUBSCRIBE ack deadline | app | Ack deadline 10 s from send. On timeout: lifecycle `subscribe_timeout`, streams FAILED, the connection forced to reconnect, health reason | RG.subscribe_no_ack_timeout |
| F38 | no first-observation deadline | app / tracks | Deadline from WS start: 30 s for Tier-0 book, depth and market; 120 s for Tier-1/2 book. On expiry: lifecycle `never_ready` and a gap (`cause=never_ready`) from the first boundary at or after the deadline | RG.first_observation_absent_never_ready |
| F39 | expected vs subscribed vs observing | app | Health computes `expected` (config + universe), `acked` and `observing` sets; HEALTHY requires equality | RG.partial_subscription_not_healthy |
| F40 | socket / ping liveness instead of data liveness | tracks / app | A connection is data-live at `S` only if a data message arrived in `[S − 10 s, S]` and it was connected at `S`. Tier-0 book silent > 120 s is a stale gap; Tier-1/2 book silent > 15 min is `stale_suspect` in health | RG.ping_alive_data_stale, RG.tier0_book_silent_120s_gap |
| F41 | unknown event types / streams only counted | app | Separate counters `unknown_stream` / `unknown_event` / `malformed`; health `warnings` list; the gate requires 0 or an explanation | RG.unknown_stream_counted_and_warned |
| F43 | writer thread death invisible | wr / app | The writer catches failures per record (rejected and counted); a fatal error is recorded; beat plus durable-lag tracking. The supervisor detects a dead writer and then: marker file, stderr, FAILED, stop, exit code 3 | RG.writer_thread_death_detected, RG.writer_bad_record_rejected_not_fatal |
| F48 | per-task heartbeats | app | `beats[task]`; HEALTHY requires every required task's beat ≤ max(2 × period, 3 s) | RG.required_task_crash_supervised, RG.health_invariant_task_beats |
| F49 | market snapshot freshness | tracks | Market stale if the newest component is older than 10 s at `S`; this opens a market gap | RG.market_stale_gap |
| F50 | clock-probe freshness | app | Clock fresh only if the last successful probe is ≤ 1,200 s old; otherwise a health reason (DEGRADED) | RG.clock_stale_degrades |
| F51 | STOPPED despite writer timeout | app | `STOPPED` only if the writer thread has exited and 0 `.partial` files remain; otherwise `STOPPED_INCOMPLETE` and exit code 2 | RG.stopped_incomplete_on_writer_timeout |
| F52 | verifier misses an absent stream | VI | Expected streams from the run record (config + universe) compared with the observed streams; an absent stream fails | VI.absent_stream_fails |
| F53 | verifier completeness window | VI | The expected window is the full authorized window, `(ws_start, stop_requested)`. Startup is excused only before the first persisted sample and before the deadline | VI.full_window_missing_first_and_last_detected |
| F54 | no explicit HEALTHY definition | app | `health_eval()` implements the pass-3 invariant (tasks, writer, streams, sets, deadlines, disk, ban, clock, freshness of the health record itself) | RG.health_invariant_* |
| F55 | gap ID collision | rec / app | `gap_id = gap\|boot8\|seq\|key\|first\|last\|cause` (per-boot sequence). Lifecycle and health IDs also carry a per-boot sequence | RG.multiple_gap_ids_unique_and_all_persisted |

### Deferred and closed items

| ID | Title | Req | Status |
|---|---|---|---|
| F10 | daily universe refresh / tier transitions | C | DEFERRED |
| F11 | rotation without overlap | – | NO_CHANGE (logged `overlap_ok`) |
| F12–F18 | expected / no issue | – | NO_CHANGE (G0) |
| F24 | proactive 24 h rotation | C | DEFERRED |
| F25 | universe-load failure leads to an ungraceful stop | G3 | DEFERRED (G2 Repeat is `tier0_only`: no REST universe load) |
| F29 | backup script: `.idx` files, partial-day guard, free-space check | C | DEFERRED (script not scheduled) |
| F30–F35 | no issue / non-blocking | – | NO_CHANGE |
| F42 | partial REST universe accepted | G3 | DEFERRED (not exercised by `tier0_only`) |
| F44 | fsync / write failure | – | NO_CHANGE (G0) |
| F45 | no external alert for health-writer failure | C | DEFERRED (alert for continuous mode) |
| F46 / F47 | queue metrics; per-boot counters | – | NO_CHANGE |

## Research-usability series (R)

### Required before the G2 Repeat

| ID | Title | Module | Correction | Test |
|---|---|---|---|---|
| R01 | provenance | prov / app | An immutable `runs/<boot_id>.json` written at start (0444, fsynced) holding: full effective config and hash, git commit, image tag and ID (build arguments or runtime environment), code SHA-256 per file, Python and package versions, schema, `SCHEMA.md` SHA-256, `sample_semantics`, cadences, tier rules / `RULE_VERSION`, universe, expected streams and endpoints, `depth_levels`, clock method, host label. Its SHA-256 and content are embedded in the `start` lifecycle record; manifest entries carry `boot_id` and `run_record` | RG.provenance_run_record_complete |
| R02 | historical health | app | A `health` raw record every 60 s and on every state change (state, reasons, warnings, stream summary, tasks, writer, queue, counters, clock, disk) | RG.historical_health_records |
| R03 | disk-stop invisible | wr / app | At HARD_STOP the writer refuses only market observations; control records (lifecycle, gap, health) are still written. Separately, a fsynced marker `control/disk_stop-<boot>-<ms>.json` plus a stderr line (not via the writer queue). Observing streams get a `disk_hard_stop` gap | RG.disk_stop_evidence |
| R06 | `SCHEMA.md` / PIT documentation | doc / prov | `SCHEMA.md` (v2) is packaged and copied into `<data>/docs/SCHEMA-v2-<sha8>.md` (0444). Its hash goes in the run record | RG.schema_doc_installed |
| R09 | explicit depth N | rec / app | Record-level `depth_levels` on every depth record; the verifier checks it equals the stream suffix and that the arrays have no more than that many levels | RG.depth_levels_explicit, VI.depth_levels_checked |
| R16 | `.idx` amplification | wr | Sync and write an index line only for segments with records in the current block; idle segments are durable at their last non-empty block and are closed with a final sync. Per-record durability within `flush_interval_s` is unchanged | RG.idle_segment_no_idx_lines |
| R17 | clock-method provenance | gd / app | Clock payload `method = "min_rtt_of_3_midpoint_v1"`, the probes, `uncertainty_ms`, `rtt_ms`; also in the run record | RG.clock_payload_method |

### Deferred and closed items

| ID | Title | Req | Status |
|---|---|---|---|
| R04 | universe ranking inputs / exclusions | G3 | DEFERRED |
| R05 | tier-transition semantics | C | DEFERRED (document with F10) |
| R07 | unchanged vs stale | (R02 + R06) | covered by R02 and `SCHEMA.md` |
| R08 | PIT join rules | (R06) | documented in `SCHEMA.md` |
| R10–R12 | cross-stream IDs, latency, candles | (R06) | documented in `SCHEMA.md` |
| R13 | schema evolution | C | the policy is stated in `SCHEMA.md` now; full v2 reader support before continuous mode |
| R14 | missing-data taxonomy | – | via R02, R03 and `SCHEMA.md` |
| R15 | contamination | – | NO_ISSUE |
| R18 | host label | – | via R01 (`host_label`) |

## Test-fixture corrections (stated openly, with the assertions unchanged)

1. **`PF.test_clock_min_rtt_uncertainty`.** The tuples `(server, 0, rtt)` contradict the documented `(server, t0, t1)`
   semantics: the arithmetic gives a skew of +970, not −30. Fixture corrected to `t0 = 1000`, `t1 = 1000 + rtt`.
   The same assertions are kept (skew −30, uncertainty 130, OK).
2. **`PF.test_low_rate_book_live_connection_is_unchanged_not_gap`.** Written before pass 3. As written, the
   connection has no data at all for 300 s and the stream is Tier-0 book, which requires a stale gap after 120 s
   under F40. Fixture changes:
   - feed `!miniTicker@arr` every second, as conn0 does in production (data liveness);
   - keep the Tier-0 window ≤ 120 s.
   A separate Tier-1 300 s test keeps the original 300 s intent (RG.tier1_low_rate_book_300s_unchanged).
3. **`PF.test_gap_start_end_and_count`.** The fixture placed the last depth message 1.1 s before the first
   asserted missing boundary. G2 evidence (`00_depth_push_jitter.txt`) shows depth push inter-arrival of
   971–1,039 ms, so a 1-push tolerance is required to avoid false gaps.
   - Fixture change: the message moves from `S−100` to `S−1001`, so the boundary `S+1000` is beyond the 2 s
     tolerance.
   - The assertions are unchanged: first `S+1000`, last `S+7000`, 7 missing.
   - A no-false-gap jitter test is added (RG.depth_jitter_1039ms_no_gap).

## Phase E: independent adversarial diff review (commit `2a7f4a2`) and resolutions

A read-only reviewer agent (separate context) reviewed the diff and found that the revision was **not yet
acceptable**: one blocker and six majors. Per Phase E, nothing was built or deployed; all findings are resolved in
the follow-up commit.

| ID | Severity | Finding (short) | Resolution | Test |
|---|---|---|---|---|
| B1 | BLOCKER | the verifier's PASS was not an acceptance verdict: the run's own config was trusted; no runtime, stop-reason, gap-budget, health-budget or alert checks | the verifier now has a pinned, predeclared acceptance spec `G2R_SPEC` (`--acceptance g2r`) covering: streams, cadences, depth N, deadlines, stale limits; runtime 7,200 ± 5 s with reason `max_runtime`; gap budget (≤ 0.5 % per stream, longest ≤ 120 s, allowed causes only); health budget (≤ 10 % non-HEALTHY, only network reasons); forbidden lifecycle alerts; zero error counters; clock excess ≤ 500 ms; final STOPPED marker; expected image ID and commit | `RV.test_B1_*` |
| M1 | MAJOR | startup-excuse off-by-one when the first message lands in `[b, b+1 ms)` | `stream_ready.ready_ns`; the verifier excuses at ns resolution, using the claim to tighten only | `RV.test_M1_*` |
| M2 | MAJOR | no reconnect when data stops (half-open socket) | the watchdog forces a reconnect after 15 s with no data on a connected connection (lifecycle `data_stall_reconnect`); WS heartbeat 30 s | `RC.test_M2_*` |
| M3 | MAJOR | data-live window and held values spanned reconnects (stale persisted as live) | data liveness requires data after the most recent connect; a value from before the reconnect gives `awaiting_post_reconnect_data` | `RC.test_M3_*` |
| M4 | MAJOR | clock-record count had no slack; the breaker doubled the loss | clock probes are exempt from the breaker; a failed round is lifecycle `clock_round_failed` with a retry after 30 s; the verifier checks spacing ≤ 1,200 s instead of a count | `RC.test_M4_*` |
| M5 | MAJOR | a task failure was not a health reason | `task_failed_10min` hard reason; the acceptance spec forbids `task_failed` | `RC.test_M5_*` |
| M6 | MAJOR | the verifier reused the collector's freshness judgement | independent age checks (depth 2 s, Tier-0 book 120 s, market 10 s), the book payload symbol, and Tier-0 symbols in the market after startup | `RV.test_M6_*` |
| m1 | MINOR | control or candle losses only counted; candle exceptions swallowed; pending candles at stop silent | per-boot control-sequence contiguity check; `emit_failed` hard reason; candle exception and stop gaps | `RV.test_m1_*`, `RV.test_B1_acceptance_pass…` |
| m2 | MINOR | health hole at stop | a health record is written as soon as the stop begins | e2e |
| m3 | MINOR | recv clamp and wall-clock steps invisible | counters persisted; `wall_clock_step` lifecycle and health reason; documented in `SCHEMA.md` | `RC.test_m3_*` |
| m4 | MINOR | stall causes mislabelled | a boundary processed more than 2 s late gets `sampler_stall` | `RC.test_m4_*` |
| m5 | MINOR | a sequence regression was rejected permanently | reset after 20 consecutive regressions, with lifecycle `seq_reset` and a hard reason | `RC.test_m5_*` |
| m6 | MINOR | quarantine not a health reason; clock future-time rejection; WS handshake 418/429; market expired recount | each fixed | G0 adjusted, plus the above |
| N1 | NOTE | provenance / identity depends on the gate | `ops/p2f_gate_up.sh` checks the image ID before and after start; `--build-arg` for commit, tag and time; `control/stop-*.json` | gate evidence |
| N2 | NOTE | doc beat limit; rotation vs watchdog restart race; negative-RTT probe | `SCHEMA.md` corrected; the watchdog skips rotating connections; the verifier uses the same `t1 ≥ t0` probe filter | – |

`RV` / `RC` = `tests/test_review_fixes.py`. Two G0 tests were moved off the newly exempted clock type and
`/api/v3/time` path, with the same assertions on a generic type and path.

### Phase E confirmation pass (commit `94434e3`)

The reviewer confirmed that the B1 false-PASS hole and M1–M6, m1–m6 and N2 are **CLOSED**; N1 is procedural. No
silent loss or false PASS was found in the new mechanisms. It found two issues created by the acceptance spec
itself:

| ID | Severity | Finding | Resolution | Test |
|---|---|---|---|---|
| NB1 | BLOCKER | a short legitimate gap showed as health reason `expected_ne_observing`, which the spec did not allow; this would spuriously fail a correct run | health now names every open gap as `gap_short:` / `gap_open:<stream>:<cause>`; acceptance allows these only for allowed network causes | `RV.test_NB1_*`, `RC.test_NB1_*` |
| NB2 | MAJOR | a 0.5 % gap budget meant zero tolerance for market (about 120 boundaries) | declared floor: allowance per stream = max(2, 0.5 % of expected boundaries) | – (spec constant) |
| D | NOTE | a single candle 5xx failed with no retry | 5xx and malformed responses are retried until the round deadline | – |
| B | NOTE | an external monitor stop before the self-stop would give reason `signal` | monitor deadline set to 7,500 s (self-stop at 7,200 s) | gate evidence |

## Pre-G3 closure (after G2 Repeat owner acceptance)

| ID | Resolution | Tests |
|---|---|---|
| R04 | CLOSED: universe `tiers-v2` with a per-candidate evaluation; raw REST bodies persisted; effective-from lifecycle; the verifier rebuilds candidates from the raw bodies and recomputes tiers, ranks, reasons, hysteresis and PIT | `test_g3_prereqs`: UniverseR04, G3EndToEnd, `PreG3ReviewVerifier.test_M2*` |
| F25 | CLOSED: bounded attempts with backoff; fail closed (`startup_failed`, FAILED, writer stop, exit 5, even after SIGTERM) | StartupF25, `test_m1*` |
| F42 | CLOSED: sanity checks (malformed, missing, empty, partial including reverse completeness, duplicate, invalid, inconsistent, Tier 0); deterministic refresh policy (keep previous, DEGRADED) | SanityF42, `test_M3*` |

**Bounded pre-G3 review** (independent reviewer). It found B1 (HEALTHY before every stream observed again after a
reconnect), B2 (a new listing's candle), M1 (reconnect exemption too broad), M2 (raw inputs not persisted), M3
(partial `exchangeInfo`), and m1–m3, m5–m7. All are fixed with tests, and the spec is re-pinned as
`g3-recommended-6h-v2`.

## G3 diagnostic stop (2026-10-03) and resolutions

| ID | Finding | Resolution | Tests |
|---|---|---|---|
| G3-F1 | Depth staleness of 2 s (calibrated on BTC/ETH only) misclassified quiet Tier-1/2 depth books as missing: 19 gaps in 211 s; G3 could not pass. Tier-1/2 bookTicker had no hard bound (only a 15 min warning), so a dead book stream could hide behind its live shared connection | Per-tier `depth_stale_ms_by_tier` = {t0: 2 s, t1: 180 s, t2: 15 s}; Tier-1/2 book `book_t12_dead_ms` = 600 s (hard); freshness vocabulary in health; persisted values keep their original timestamps; pinned in spec v4 and applied by the verifier from the pinned spec | `tests/test_g3_f1.py` |
| G3-F2 | Verifier CLI `--json` crashed on a `None` key (exclusion reason) | `str_keys()` export, and `"selected"` replaces the `None` reason key | `test_cli_json_export_with_none_key` (real CLI subprocess) |

**Calibration** (diagnostic 211 s run plus G2R; persisted sample ages are censored at the old 2 s limit):

| Stream | Cadence | Observed | Threshold | Justification |
|---|---|---|---|---|
| Tier-0 depth20 | 1 s | G2R inter-arrival 971–1,039 ms; diagnostic age p99 849 ms | 2 s (unchanged) | validated by G2R; one missed push |
| Tier-2 depth10 | 5 s | age p50 548, p99 1,619, max 1,866 ms (persisted); ≈ 0.9 pushes/s per stream; ~1.4 % of Tier-1/2 boundaries > 2 s | 15 s | P2-E0 "depth: 3 × cadence"; a value no older than 3 sampling periods; a dead stream is detected within 15 s |
| Tier-1 depth10 | 60 s | age p50 503, p99 1,731, max 1,890 ms (persisted) | 180 s | 3 × cadence; detects a dead stream within 3 min at 60 s resolution |
| Tier-1/2 bookTicker | 10 s / 2 s | Tier-1 p99 19.8 s, max 40.7 s; Tier-2 max 26.2 s | 600 s (hard) | event-driven; about 15 × the observed maximum; closes the dead-book-behind-live-connection path |

**Censoring note (review F2).** The 19 diagnostic depth gaps were all 1–2 boundaries long: 12 × 5 s and 1 × 10 s
on Tier 2; 5 × 60 s and 1 × 120 s on Tier 1. Each closed at the next boundary or the one after, so the true
silences were below 2 s + one cadence (Tier 2 < 7 s, Tier 1 < 122 s), within 15 s and 180 s. The thresholds come
from the deterministic 3 × cadence rule, not from fitting this data. Tier 0 deliberately keeps the G2R-validated
2 s, which is stricter than 3 s.

**Review notes:**
- F1: the verifier now takes the freshness limits from the pinned spec and fails closed if a spec lacks them.
- F3: `stale_stream` time is charged to the health time budget.
- F6–F8: accepted notes.
- F9: the F40 row's '15 min `stale_suspect`' is superseded; the warning is now at 120 s, with a hard 600 s bound.

## G3-F3: synchronous hourly certification blocks the writer hot path

- **Finding:** in the G3-v4 run (diagnostic, NOT ACCEPTED), `writer_stale` occurred 5 times, once at each UTC hour,
  with the writer heartbeat 7.6–14.4 s old.
- **Cause:** `_promote` (full decode, validation, SHA-256, rename) ran inside the writer thread. At recommended-profile
  segment sizes (≤ 72,360 records / 6.3 MB) this blocked the hot path beyond the 5 s liveness and 10 s durability
  invariants.
- **Resolution (owner decision: architectural, thresholds unchanged):**
  - The writer only finalizes the segment and hands it off durably (atomic rename to `.pending`).
  - One serialized, throttled `Certifier` thread with its own heartbeat performs the unchanged certification
    (`.pending` → `.certifying` → certified).
  - Filesystem state is authoritative for crash recovery.
  - Bounded backlog with health reasons.
  - Writer and certifier health are separate.
  - The shutdown drain is bounded by a grace period, else `STOPPED_INCOMPLETE`.
  - The verifier understands the lifecycle and independently measures enqueue → fsync latency from the `.idx`
    files.
  - Spec `g3-recommended-6h-v5` adds certifier and writer criteria; v4 is unaltered.
- **Tests:** `tests/test_g3_f3.py` (12).

**G3-F3 bounded review (f2dc2ff)** — no hot-path blocking. It found 9 issues: F1 (shutdown success before the
manifest append), F2/F4/F5 (crash-order strandings), F3 (torn manifest), F6 (a failure during the drain could
still report success), F7 (backlog limit 8 below the 9 record types), F8/F9/F10 and F11 (stop grace). All are fixed
with regression tests (`tests/test_g3_f3.py::ReviewFindings`); the spec is re-pinned as v6.
