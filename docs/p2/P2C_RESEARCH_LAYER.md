# P2-C — Deterministic, point-in-time-safe research & feature layer

**Status:** foundation, offline only. Branch `feature/p2c-research-layer-20261004` (base `3e58691`). Not merged, not
deployed. Nothing here feeds Paper, the collector, the learner or walk-forward. No strategy optimization, no W3
outcomes, no Paper outcomes.

Code: `p2_research/` (stdlib only; never imports `p2_forward`). Tests: `p2_research/tests/` (synthetic fixtures).
Feature table: [P2C_FEATURE_REGISTRY.md](P2C_FEATURE_REGISTRY.md) (generated). Raw schema: `p2_forward/p2_forward/SCHEMA.md` (v2, authoritative).

## 1. Pipeline

```
raw schema-v2 forward data (immutable, read-only; SEALED days only by default)
  └─ reader.py        normalized Bundle: compact per-stream tuples sorted by availability + quality metadata
      └─ features.py  PITView(bundle, T): only available_at_ms <= T is reachable; feature set v1 (40 features)
      └─ labels.py    forward labels, separate namespace (mkt.* / exe.*) and separate output file
          └─ builder.py  deterministic research dataset: features / labels / excluded + manifest + logical hash
              └─ offline evaluation (future, separately authorized; no feedback to Paper)
```

Data flows one way. Labels never reach the feature side (separate module, separate file, tests assert key sets
are disjoint). The builder writes only under `/home/tradmin/research-data/trading-signal-bot/p2c/` or a temp/scratch
directory, and refuses the collector dataset and the whole `.../p2/` tree.

## 2. Input contracts (per family)

Common to every record (SCHEMA §2): `schema="tsb.p2.forward"`, `schema_version=2`, `obs_id`, `boot_id` (run
identity → `runs/run-<boot>.json`), `collector_version`, `recv_ts_ns`, `observed_at_ms = recv_ts_ns // 1e6`
(when the collector knew it), `available_at_ms` (earliest PIT-safe use), `clock_suspect`, `recoverability`.
`exchange_event_time_ms` is never used for joins.

| Family | Source / schema | Event time | Observation / availability | Identity | Quality flags | PIT semantics |
|---|---|---|---|---|---|---|
| book (`bookTicker`) | `type=book`, payload `{u,s,b,B,a,A}` verbatim | none (spot bookTicker has no E) | `observed ≤ sample_ms`, available = observed | `bt\|SYM\|u\|c<cad>\|t<S>`; `exchange_seq=u` | `unchanged`, `clock_suspect`, tier/cadence, stale limits by tier | latest received at or before S (sample-and-hold); age `T − observed` must be within the tier limit |
| depth (`@depthN`) | `type=depth`, `{lastUpdateId,bids,asks}`, `depth_levels=N` | none | as book | `dp<N>\|SYM\|lastUpdateId\|c\|t` | as book; levels ≤ N | as book; aggregates use the first 10 levels so depth20 and depth10 are comparable |
| market (`!miniTicker@arr`) | `type=market`, list of miniTickers, `component_recv_ms`, `startup_complete` | max component `E` (not used) | newest component recv ≤ S | `mkt\|t<S>` | `startup_complete=false` for 60 s | usable only if `startup_complete` and `T − observed ≤ 70 s`; filtered to the universe known at T |
| candles 15m/1h/4h/1d | `type=candle`, kline array verbatim (REST) | close time | `available = max(close+1, observed)` | `SYM\|tf\|open_ms` (= P1 `candle_id`) | `RECOVERABLE_WHERE_ARCHIVE_AVAILABLE`; identical re-fetch = idempotent duplicate | only CLOSED candles with `available_at_ms ≤ T`; the latest closed candle must be available, else null |
| universe / tier epochs | `universe/universe-*.json` (SHA-checked) announced by lifecycle `universe_active` (ws_start), `universe_transition` (effective T), `day_checkpoint` | `effective_from_ms` | the announcing record's `available_at_ms` | `uni\|stamp\|tiers-v2` | trusted/applied, hysteresis | epoch used at T requires `effective_from ≤ T` **and** announcing record `available ≤ T` (no retrospective tier) |
| clock | `type=clock`, `serverTime` probes | serverTime | observed | `clk\|serverTime` | `clock_suspect` | exposed as `dq.clock_suspect`; timestamps never rewritten |
| health | `type=health` every 60 s / on change | — | observed | `hlth\|boot\|seq` | `state`, `streams_not_observing` | the **real-time** knowledge of an open gap (`dq.degraded_flag`) |
| gaps | `type=gap`, written when the gap **closes** | — | observed at close | `gap\|boot8\|seq\|key\|first\|last\|cause` | `cause`, `causes`, `day_split`, `open_at_stop`, recoverability | a gap is a feature input only when its record is available ≤ T (`dq.gap_known_1h`); post-hoc gap knowledge goes to the label-side `qa` field only |
| run boundaries / downtime | `runs/run-*.json`, `runs/downtime-*.json` (`from_ms`, `until_ms`=ws_start, cause), `control/stop-*.json` | — | file facts | `boot_id` | cause: first_run / clean_stop / stopped_* / crash_or_kill | rows in downtime are excluded (`in_downtime`); values from a previous run are never carried across a restart (`from_previous_run`) |
| certification / daily seals | `manifests/D.jsonl`, `days/D.json`, `seals/D.json` (+report) | — | — | segment path + SHA-256 | seal `result=PASS` | sealed days only by default (section 4) |

Missing raw observations are **never interpolated**: book/depth/market gaps are irreplaceable; candle gaps are
recoverable from an archive but P2-C does not fetch anything (no network).

## 3. PIT contract

- Decision grid `grid-15m-plus390s-v1`: `T = 15m boundary + 390 s` (≥ the 375 s candle fetch margin), so the
  just-closed 15m candle is normally available.
- Every feature value carries `feature_available_at` (max `available_at_ms` of its inputs). The builder raises
  `PITViolation` if any non-null value has `feature_available_at > T` or none at all.
- `PITView` is the only feature data path: every accessor refuses a time after `T` and returns only elements with
  `available_at_ms ≤ T`. Labels use the bundle directly and live in another module and file.
- Universe/tier: the epoch known at T (announcing record available ≤ T); a transition effective at T but announced
  200 ms later is invisible for that 200 ms.
- Gaps are known only after they close (SCHEMA §5). Real-time health is the PIT gap signal.
- Tests: future-perturbation (corrupt or delete everything available after T, including an off-grid T where the
  just-closed candle is not yet fetched: features unchanged; verified to FAIL when the candle availability check is
  removed), accessor refusal, "closed but not yet available" candle, universe as-of, builder PIT guard.

## 4. Schema reader (R13)

- Identification: `dataset.json` must be `tsb.p2.forward.dataset` v1, `schema_version ∈ {2}`, production calendar.
  Every record: `schema`, `schema_version` (int, ∈ {2}), `type` ∈ the 9 v2 types, required fields and types. Any
  older, newer or unknown version or type → `UnsupportedSchema`. New versions require a new reader branch.
- Record checks: `observed = recv//1e6`; `available = observed` (non-candles) or `max(close+1, observed)` (candles);
  sampled records `recv ≤ sample_ms`; depth `depth_levels`; market `component_recv_ms`; candle identity/alignment.
- Sealed-only by default: `seals/D.json` (`tsb.p2.forward.day_seal` v1, `result=PASS`, same dataset and day);
  `days/D.json` SHA = seal; `manifests/D.jsonl` SHA = seal; report SHA = seal; the day's segment set = day-close
  listing; no `.partial/.pending/.certifying` file; every segment's SHA-256 recomputed = manifest = sidecar;
  record count = manifest. Spillover: the next day's first hour, all certified and SHA-checked.
- Active day: only with `experimental_active_day=True`, single day, never on a sealed day; bundle
  `reproducible=False`; the builder writes it under `EXPERIMENTAL-nonreproducible/`, never with sealed days.
- Determinism: sampled streams are sorted by `(sample_ms, cadence, available, seq)`, identical duplicates dropped
  and counted, conflicting duplicates (same stream and boundary, different content) → `AmbiguityError`; candles:
  identical re-fetch keeps the earliest availability, different content → `AmbiguityError`; control records are
  deduplicated by `obs_id` on canonical content. Out-of-order input gives an identical bundle (tested).
- Multi-run: run chain from `runs/`, downtime intervals explicit (never stitched), unknown `boot_id` → fail;
  epochs from `universe_active`, `universe_transition` and `day_checkpoint`, each universe file SHA-checked.

## 5. Quality semantics

Exposed, never hidden: reader counters (duplicates dropped, out-of-order resolved, `clock_suspect` per type,
`unchanged`, gap causes, `day_split`, non-HEALTHY health records, downtime ms, epochs, transitions) in the
manifest; per-row `dq.*` features; per-feature null reasons (`feature_null_reasons`) with manifest totals;
`qa.posthoc_gap_at_decision` on the label side (gap covering T but recorded after T). Rows are only excluded for
structural reasons (`in_downtime`, `no_universe_epoch_known`), listed in `excluded.jsonl.gz`.

## 6. Labels (label set `p2c-ls` 1.0.0)

Anchor `A` = first 15m boundary strictly after T; `p0` = open of the 15m bar at A. Horizons 1h / 4h / 24h.

| Label | Definition |
|---|---|
| `mkt.fwd_ret_h` | ln(close of last bar in [A, A+h) / p0) |
| `mkt.mfe_h` / `mkt.mae_h` | max(high) / p0 − 1 ; min(low) / p0 − 1 over [A, A+h) |
| `mkt.max_dd_h` | max over i ≤ j of (H_i − L_j)/H_i on 15m bars (intra-bar order unknown → conservative) |
| `mkt.decline_h` | 1 if `mae_h ≤ −{1.5 %, 3 %, 6 %}` (predeclared, not tuned) |
| `exe.entry_ask`, `exe.entry_delay_ms`, `exe.entry_spread_bps` | first book sample observed in (T, T+60 s] |
| `exe.fee_bps_roundtrip` | 2 × 10 bps (assumption) |
| `exe.net_ret_h` | ln(bid of first book in (T+h, T+h+60 s] / entry ask) − fees (top of book only, no depth slippage) |
| `exe.paper_outcome` | declared, always null: `paper_r1_linkage_not_authorized` |

Null with a reason when any forward bar is missing, the anchor bar is missing, or the window is beyond the loaded
range (`coverage_end` = end of the last loaded day). Market labels use recoverable candles; execution labels use the
irreplaceable book and are null rather than bridged.

## 7. Dataset manifest (`tsb.p2c.research_dataset` v1)

Inputs: dataset ID, explicit sealed days, feature-set version, label-set version, universe policy
(`universe-asof-all-tiers-v1`), code commit. Manifest: package/reader versions, `code_commit`, `code_tree_sha256`;
source (dataset ID, `dataset.json` SHA, days, mode, `reproducible`, schema versions consumed, seal/day-close/manifest
SHAs per day, every segment path + SHA + records, run-record SHAs, universe-file SHAs); feature set (ID, version,
registry SHA, grid); label set (ID, version, horizons, thresholds, fee, definitions SHA); row count, excluded count
and reasons, symbols, time range, quality summary, file SHAs (uncompressed), `logical_hash`, `build_timestamp_utc`.
`logical_hash = sha256(canonical manifest without build_timestamp_utc and output_dir)`. Content files are canonical
JSONL, gzip `mtime=0`, so identical inputs give byte-identical files. Output dir `<root>/<dataset_id>/<fs>-<ls>/<hash16>/`
is written atomically (temp dir + rename); an existing dir with a different hash is refused.

## 8. PAPER-R1 linkage plan (design only; no production change)

Existing P1 evidence v2 (`shared/evidence_v2.py`): `candle_id = SYMBOL|tf|open_ms` (identical to the collector
candle `obs_id`), `candidate_id = cand_ + sha256(candidate|v1|candle_id|trade_type|strategy_version)[:24]`, events with
`event_time_ms`, `boot_id`, `seq`, `code_sha`, `config_hash`. Events: analyzer `candidate.analyzed` (candle open/close,
`klines_fetched_at_ms`); signal_engine `candidate.evaluated`, `signal.ready`, `signal.refused`, `selection.truncation`,
`cycle.outcome`; trade_tracker `delivery.consumed`, `admission.decision`, `admission.capacity`, `entry.attempt`,
`entry.expired`, `trade.opened`, `trade.target_hit`, `trade.closed`, `risk.state`, `risk.transition`. Tracker subjects
carry `signal_id` + `candidate_id` (from `features_snapshot.identity`).

Join keys: signal/decision ↔ market state via `candle_id` (exact) and decision `event_time_ms` (as-of join on
`available_at_ms ≤ event_time_ms`); decision ↔ P2-C row via (symbol, nearest grid T ≤ event_time) or a future
event-time row; decision ↔ execution/result via `candidate_id` → `signal_id` → tracker events.
Gaps for a future, separately authorized instrumentation change: (1) no feature-snapshot ID/hash linking a Paper
decision to the exact P2-C feature row and registry version; (2) no reference to the collector observation (book
`obs_id`/`sample_ms`) used for the Paper entry price; (3) signal-engine decisions use the bot's own klines, not
collector candles (equality only via `candle_id` + values check); (4) clock alignment between Paper hosts' wall clock
and collector `recv_ts_ns` is not recorded per event; (5) Paper outcome rows must stay outside W3 and enter only
via a predeclared evaluation. Until then `exe.paper_outcome` stays null.

## 9. Resource envelope

Single-host safety: every P2-C job runs under `systemd-run --user --scope -p CPUQuota=100% -p MemoryMax=2G`,
`nice -n 15`, `ionice -c3`, `prlimit --as=2 GiB`, on bounded ranges, after checking collector health and Paper
heartbeats. Benchmark (synthetic, 1 day, 37 symbols, production cadences, 2.25 M sampled records): see the evidence
directory; first measurement 76.6 s CPU, 1.17 GB peak RSS for 3,552 rows. The reader keeps a day in memory: a
multi-day build at production cadence needs ~1.1 GB per day and does not fit 2 GB beyond one day (open item O1).
Tests: 45+ unit tests, ~3 min on one niced core.

## 10. Rejected alternatives

- Importing `p2_forward` for parsing: rejected (verifier-style independence; a collector bug must not hide in research).
- pandas/numpy/parquet: rejected (dependency policy; stdlib JSONL+gzip is enough at this scale).
- Interpolating or forward-filling book/depth across gaps or restarts: rejected (irreplaceable data; fail closed).
- Using gap records as real-time features: rejected (written at close → look-ahead); health records instead.
- Decisions at the exact candle close: rejected (the candle is not yet fetched; would force nulls or leakage).
- Labels from book mid paths: rejected for market labels (irreplaceable gaps); kept only for execution labels.
- Tuning decline thresholds or features on data: rejected (no outcome-driven choices in P2-C).

## 11. Limitations and open questions

- O1 memory: in-memory bundle ~1.1 GB per production day; multi-day builds need per-day streaming of sampled
  streams (planned) before any range > 1 day under the 2 GB cap.
- O2 no real sealed day existed when this foundation was built; only synthetic validation plus a read-only
  experimental diagnostic of the active day (evidence).
- O3 history: rolling features need up to 24 h (15m×96) / 25 h of candles; early rows of a dataset are null by design.
- O4 execution labels are top-of-book only (no depth walk, no latency model beyond the next observation).
- O5 synthetic fixtures model the collector layout from SCHEMA.md and the verifiers; real-data parity must be
  re-checked on the first sealed days (field shapes, day_checkpoint/transition payloads).
- O6 the collector's first hour (14:25–15:26Z on 2026-10-04) predates E (PAPER-R1); it is market data, not W3
  outcomes, but any evaluation must still avoid choosing anything on pre-E data.
- Q1 should the decision grid be per timeframe (1h/4h) for slower strategies? Q2 tier-1 book cadence (10 s) makes
  `spread_norm_1h` noisier for tier 1; acceptable for `experimental` status.
