# P2-E0: forward market-intelligence collector, design (`p2e-collector-design-v1`)

**Status:** DESIGN ONLY. Nothing here is deployed, scheduled or running.

- P2-E1 (implementation plus a bounded deployment) needs separate owner authorization.
- Trading stays PAPER_HALTED.
- W3 (≥ 2026-08-19T09:33:46Z) stays SEALED. The collector observes **public market facts from now on**; it never
  reads strategy outcomes.

**Evidence:** sizes, rates and consumers below were measured on 2026-10-02. See the P2-E0 evidence folder:
`01_binance_consumers.txt`, `02_bounded_sampling_sizes.json`, `03_trade_volume_basis.json`,
`04_storage_estimates.md`.

## 0. Why it exists
- **While halted, the scanner stops before any analysis.** The trading pipeline therefore records no market
  context (P2-DESIGN finding).
- **Some data can be recovered later from public archives:** candles, aggTrades, futures metrics, funding, and
  mark/index klines (data.binance.vision).
- **Some cannot:** best bid/ask, order-book depth, and the exact intraday state the bot would have seen. These are
  lost every day nobody records them.
- **Design priority:** capture the irreplaceable, keep the recoverable cheap, and never touch trading.

```
PUBLIC BINANCE (spot WS/REST, optional futures REST) ──▶ COLLECTOR ──▶ IMMUTABLE RAW SEGMENTS (append-only)
                                                                            │
                                         research (P2-C/D/F) reads later ◀──┘     trading never reads it (E1)
```

## 1. Architecture (decision)
| Option | Failure isolation | Complexity | Resources | Deploy / monitor | Upgrade risk |
|---|---|---|---|---|---|
| **A. One asyncio process with supervised tasks** | Task-level: the spot WS, REST scheduler, writer and optional derivatives each run as a supervised task; one failing task is restarted without killing the others | lowest | 1 container, ~0.3 CPU | one health file | one image |
| B. Spot plus derivatives processes | process-level for the optional module | medium | 2 containers | 2 health files | 2 images |
| C. Multiple specialized collectors | highest | highest | most | many | most |

**Recommendation: A.**
- At this scale (about 150 spot streams × 2 types plus REST every few minutes) a single process is enough, and its
  failure domain is the collector only.
- Derivatives are a **disabled-by-default task**. A futures endpoint outage marks only that task degraded. Option B
  can come later if derivatives grow.

**Tasks:**

| Task | Role |
|---|---|
| `universe` | daily tier snapshot |
| `ws_spot` | bookTicker and partial-depth streams, ≤ 2 connections |
| `rest_candles` | closed klines |
| `rest_market` | 60 s market mini-ticker |
| `clock` | 10 min skew probe |
| `writer` | bounded queue → segment files |
| `health` | 10 s heartbeat file |
| `derivs` | optional |

## 2. Data-source matrix
| Data | Transport | Spot endpoint / stream | Exchange time | Sequence | Recoverable later? | MVP |
|---|---|---|---|---|---|---|
| Closed candles 15m/1h/4h/1d | REST | `/api/v3/klines`, `endTime = last closed open` | open/close time | candle ID | **yes** (archives) | yes (cheap, timely, reconciles with archives) |
| Best bid/ask | WS | `<s>@bookTicker` | **none in spot payload** | `u` (update ID) | **no** | yes |
| Depth top-N | WS | `<s>@depth10@1000ms` / `<s>@depth20@1000ms` (exchange-made partial snapshots) | **none** | `lastUpdateId` | **no** | yes |
| Market 24h stats (breadth basis) | WS | `!miniTicker@arr` (1 s), persisted every 60 s | `E` | — | partly (24h stats derivable from candles) | yes |
| aggTrades | WS | `<s>@aggTrade` | `E`, `T` | `a` (agg ID) | **yes** (daily aggTrades archives) | **no**: backfill on demand under a freeze-style date guard |
| Funding / mark / index | REST (fapi) | `/fapi/v1/premiumIndex` (all symbols, weight 10) | `time` | — | mark/index klines and funding: yes | optional (Phase 2) |
| Open interest | REST (fapi) | `/fapi/v1/openInterest` | `time` | — | 5 min `metrics` archives: yes | optional (Phase 2) |
| Long/short and taker ratios | REST (fapi) | `/futures/data/*` (5 min) | `timestamp` | — | yes (`metrics` archives, 30-day REST window) | no (archive later) |
| Dominance | — | none on Binance | — | — | CMC 12-month window / CoinGecko | **no** (OPTIONAL per owner) |

**Decision on candles: A, capture all four timeframes directly.** ds-0928 and P2-B use direct exchange candles
per timeframe. Deriving 1h/4h/1d from 15m would add an aggregation rule that would have to be proven identical to
exchange semantics (sessions with no trades, `trade_count` and `quote_volume` sums). Direct capture costs about
0.8 MB/day and about 20 REST weight per minute, and stays byte-comparable with archives.

## 3. Universe tiers (deterministic, independent of trading)
- **Tier 0 (always):** BTCUSDT, ETHUSDT.
- **Tier 1 (market context):**
  - **Rule:** spot `USDT` pairs with status TRADING and 24h `quoteVolume ≥ 10,000,000` (the scanner's
    `MIN_VOLUME_USDT`).
  - **Excluded:** stablecoin-vs-USDT pairs (USDC, FDUSD, USD1, TUSD, EUR, …) and non-ASCII symbols.
  - **Cap:** top 150 by quote volume.
  - **Hysteresis:** a member stays for 7 days after falling below the threshold.
  - **Measured today:** 62 symbols at ≥ $10M (18 at ≥ $50M).
- **Tier 2 (microstructure focus):** the top 20 of Tier 1 by quote volume plus the top 10 by |24h change|, at most 30.
- **Refresh:** once per UTC day at 00:10, from one `ticker/24hr?type=MINI` call (weight 80). The snapshot is
  written as an immutable `universe/<date>.json` (rule version, inputs hash, members per tier), so any
  observation's tier membership can be reproduced.
- **No trading dependency.** A later, optional rule may add symbols seen in P1 `candidate.*` evidence (read-only
  file read), but MVP must not need it.

## 4. Sampling plan (persisted cadence; WS streams arrive faster and are sampled-and-held deterministically)
| Data | Tier 0 | Tier 2 | Tier 1 | Rationale |
|---|---|---|---|---|
| bookTicker (last state at each UTC boundary, plus its `u`) | 1 s | 2 s | 10 s | decisions use the spread at decision time; 1–10 s resolution suffices for 15m+ strategies |
| depth | depth20 every 1 s | depth10 every 5 s | depth10 every 60 s | imbalance / near-mid liquidity / slippage; top 10 covers ≈ 0.1–0.5 % from mid on liquid pairs |
| closed candles | after close + 5–60 s jitter | same | same | finality; REST `endTime` never returns an open candle |
| market miniTicker | — | — | all USDT pairs every 60 s | breadth, risk-on / risk-off |
| clock probe | every 10 min | | | skew vs exchange |
| premiumIndex (optional) | 60 s | 60 s | — | funding / mark / basis context |
| openInterest (optional) | 5 min | 5 min | — | matches the exchange 5-min statistics |

- **Sample-and-hold is deterministic:** at each cadence boundary the latest message received before the boundary
  is persisted, with its own `u` / `lastUpdateId`. Unchanged state is still written, with `unchanged=true`, so
  "no update" stays distinguishable from "not observed".

## 5. WebSocket / REST strategy
- **WS (spot `wss://stream.binance.com:9443/stream?streams=…`):** bookTicker and partial depth.
  - At most 2 connections and ≤ 300 streams each; the documented limit is 1,024 streams per connection.
  - Subscribe messages ≤ 4/s (limit 5).
  - Answer server pings within 60 s.
  - **Planned 24 h rotation:** open the replacement connection, wait until it delivers, then close the old one.
    Overlap is deduplicated by update ID, so there is no rotation gap.
- **REST:** candles, universe, clock, optional derivatives. Each call carries its own weight budget (§12).
- **Archives (data.binance.vision):** reconciliation and backfill of recoverable data (candles, aggTrades,
  metrics), reusing the P2-B checksum-verified acquirer.

## 6. Timestamp contract (extends P2-A; all UTC epoch milliseconds, plus ns where measured)
| Field | Meaning |
|---|---|
| `exchange_event_time_ms` | exchange `E` / `time` / candle close. **null when the stream has none** (spot bookTicker, partial depth); never filled with local time |
| `exchange_trade_time_ms` | `T` where present |
| `recv_ts_ns` | collector receive time (monotonic-anchored wall clock) |
| `ingested_ts_ns` | enqueued to the writer |
| `durable_ts_ns` | per flush block, in the segment index (the fsync time of the block containing the record) |
| `observed_at_ms` | = `recv_ts_ns / 1e6` |
| `available_at_ms` | = `observed_at_ms` (what a process on this host could know); for REST candles `max(close_time+1, observed_at)` |

- **Point-in-time rule for research:** `available_at_ms <= decision_time_ms`, using the same host clock as the P1
  Evidence V2 `event_time_ms`.

## 7. Clock quality
- **Host:** systemd-timesyncd active, `NTPSynchronized=yes` (measured). Measured skew vs Binance server time: about
  10 ms median.
- **Probe:** `/api/v3/time` (weight 1) every 10 min, `skew = server − (t0+t1)/2`, with RTT recorded.
- **Thresholds:**
  - warning: |skew| > 250 ms, or RTT > 1 s;
  - critical: |skew| > 1,000 ms. The interval is marked `clock_suspect=true` on every record; nothing is dropped
    or corrected.
- Research treats `clock_suspect` intervals as not point-in-time-safe for intervals under 5 s.

## 8. Identity contract (deterministic, independent of files and processes)
| Stream | `obs_id` |
|---|---|
| candle | `SYMBOL\|tf\|open_ms` (identical to P1 `candle_id`) |
| bookTicker | `bt\|SYMBOL\|u\|cadence_ms` (the cadence allows the same `u` to be persisted at a different tier cadence) |
| depth | `dp{N}\|SYMBOL\|lastUpdateId\|cadence_ms` |
| miniTicker | `mt\|SYMBOL\|E` |
| premiumIndex | `pi\|SYMBOL\|time` |
| openInterest | `oi\|SYMBOL\|time` |
| funding | `fr\|SYMBOL\|fundingTime` |
| clock probe | `clk\|serverTime` |
| universe | `uni\|date\|rule_version` |

- `collector_instance` and `boot_id` are provenance, **not identity**. Duplicates across restarts or WS rotation are
  removed by `obs_id` at certification. The first copy is kept; the duplicate count is recorded.

## 9. Order-book strategy (decision)
- **Use exchange-provided partial snapshots (`depth10/20@1000ms`) and do not reconstruct books from diff-depth.**
- **Why:**
  - Research needs top-N liquidity, imbalance and slippage estimates at decision times sampled every 1–60 s.
  - Partial streams are exchange-consistent snapshots identified by `lastUpdateId`.
  - Local reconstruction (stream buffer → REST snapshot → align `lastUpdateId` → apply buffered events → enforce
    `U <= last+1 <= u` → resync after a gap) adds failure modes and CPU. Its result would also need its own
    proof of correctness.
- **Validity checks per snapshot:**
  - `lastUpdateId` strictly increases per symbol, or the record is a duplicate;
  - bids descending, asks ascending;
  - best bid < best ask.
  - A violation goes to quarantine with a reason. No reconstructed book is ever claimed.
- **Escalation:** if a later study needs full depth or tick-level book events, a separate design adds diff-depth
  with the full synchronization protocol above and sequence proofs, for a few Tier-0 symbols only.

## 10. Gap detection and recovery
- **Per stream key `(type, symbol)`:** expected cadence, last receive, last sequence, reconnect count, gap count,
  missing duration, recovery method.
- **A gap record is written to the `gaps` stream** when any of these happens:
  - receive age > 3× cadence (bookTicker on illiquid symbols uses 60 s);
  - a WS disconnect;
  - a sequence regression;
  - a backpressure drop;
  - a clock-critical interval;
  - a write failure.

| Class | Data | Recovery |
|---|---|---|
| recoverable | candles, aggTrades, futures metrics, funding, mark/index | REST re-fetch (candles: next cycle) or archive backfill; the gap record is closed with `recovered_by` |
| partially recoverable | miniTicker / breadth | rebuilt from candles at candle granularity (labelled derived) |
| irrecoverable | bookTicker, depth | none: the gap stays open with its exact duration; **never bridged or interpolated** |

## 11. Raw record schema (JSONL, one object per line, `schema = tsb.p2.forward`, `schema_version = 1`)
```json
{"schema":"tsb.p2.forward","schema_version":1,"obs_id":"dp10|BTCUSDT|91234567890|5000","type":"depth10",
 "symbol":"BTCUSDT","tier":2,"cadence_ms":5000,"source":"binance_spot","transport":"ws",
 "endpoint":"btcusdt@depth10@1000ms","exchange_event_time_ms":null,"exchange_seq":91234567890,
 "recv_ts_ns":1790000000123456789,"ingested_ts_ns":1790000000123500000,"unchanged":false,
 "clock_suspect":false,"collector_version":"p2e1-x.y.z","boot_id":"…","payload":{…raw exchange fields verbatim…}}
```
- **Raw only.** `payload` is the exchange message verbatim. Derived values (spread, imbalance, basis, volatility,
  breadth) are **never** stored in raw; they are computed later under a versioned `feature_version`.

## 12. Storage, rotation and the write transaction
- **Root:** `~/research-data/trading-signal-bot/p2/forward/` with `raw/`, `index/`, `universe/`, `gaps/`,
  `health/`, `quarantine/`, `manifests/`.
- **Segment path:** `raw/<type>/<YYYY-MM-DD>/<type>-<YYYYMMDDTHH>Z-<boot8>-<seq>.jsonl.gz`.
  - Hourly rotation per type, not per symbol: about 8 types × 24 files per day. No tiny files.
- **Lifecycle:**
  1. **Active:** `…jsonl.gz.partial`. A gzip stream with `Z_SYNC_FLUSH` plus `fsync` every 2 s writes a block
     record (offset, `durable_ts_ns`) to `index/…idx.partial`.
  2. **Close at the hour boundary, or on graceful shutdown:** final gzip trailer, then `fsync`.
  3. **Validate:** full gzip decode; every line parses; schema check; per-key ordering; duplicate count.
  4. **Checksum:** SHA-256 into a sidecar `.sha256` and the daily manifest.
  5. **Promote atomically:** `rename()` to the final name, then `chmod 0444`.
- **Crash recovery at start:**
  - Each `*.partial` is decoded up to the last sync-flush block.
  - Its valid lines are re-emitted into a new segment named `…-recovered-…`.
  - A gap record (`cause=crash`) is written.
  - The original `.partial` moves to `quarantine/` and is never deleted.
  - **Only promoted segments with a matching `.sha256` count as data.**
- **Daily certification at 01:00 UTC for day D−1:** a manifest of all segments (SHA-256, counts per type and
  symbol, duplicates removed, gaps, `clock_suspect` intervals). The day is then immutable.
- **Format:** gzip JSONL using the standard library only. No pandas or pyarrow in the collector; Parquet
  conversion is a separate, reproducible research step.

## 13. Storage budget (compressed; measured basis)
| Profile (Tier 1 = 100) | MB/day | GB/30 d | GB/90 d | GB/year |
|---|---|---|---|---|
| Minimal: candles + bookTicker + market mini | 80 | 2.4 | 7.2 | 29 |
| **Recommended:** + bounded depth + light derivatives | **267** | **8.0** | **24** | **98** |
| High-resolution: + depth20 @1 s for Tier 2 + aggTrades | 1,143 | 34 | 103 | 417 |

- For Tier 1 = 62 or 150, the recommended profile is 245 or 297 MB/day.
- Host free disk is 516 GB. P2-E1 must re-measure these figures, with an acceptance band of ±50%.

## 14. Rate-budget model
- **Shared IP consumers (measured inventory):** only the trading services. Hermes uses BSC RPC, not the exchange;
  tr-ict isn't running.

| Consumer | Calls |
|---|---|
| scanner | exchangeInfo, `ticker` (all), BTC klines every 300 s |
| analyzer | klines (4 TF × 201) plus `depth(20)` per candidate |
| signal_engine | BTC/ETH 4h klines hourly, CoinGecko |
| tracker | WS aggTrade for open trades, `ticker/price` every 30 s |
| telegram | ad-hoc `ticker/price` |

- **Observed:** P2-B peaked at 334 per minute; my sampling peaked at 189. The limit is 6,000 per minute (spot) and
  2,400 per minute (futures, a separate budget).
- **Collector REST budget:**
  - hard cap **300 weight/min** (5%);
  - expected steady state about 20–40 per minute;
  - the 00:00 UTC four-timeframe candle burst is spread over 5 minutes with jitter, at most about 240 per minute.
- **Yield rule:** before every REST call, read the last seen `x-mbx-used-weight-1m`.
  - At ≥ 2,400 (40%), defer non-urgent calls.
  - At ≥ 3,600 (60%), pause REST for 60 s.
  - On HTTP 429, honour `Retry-After` × 2 and stop REST for at least 5 min.
  - On HTTP 418, stop **all** collector traffic (REST and WS) for `Retry-After` plus 10 min, and raise a critical
    alert.
  - A circuit breaker opens after 3 consecutive failures per endpoint (10 min).
- **WS budget:**
  - ≤ 2 connections;
  - reconnect backoff 1 s → 60 s exponential with ±30% jitter;
  - at most 10 connection attempts per 5 min (the IP limit is 300);
  - after 5 consecutive failures, stay disconnected 15 min with the gap recorded.
- **Futures (optional):** at most 60 per minute of the separate 2,400 budget.

## 15. Resource limits for P2-E1
| Resource | Limit |
|---|---|
| CPU | `--cpus 0.5` |
| Memory | `--memory 384m --memory-swap 384m` |
| Processes | `--pids-limit 64` |
| Filesystem | `--read-only` rootfs; tmpfs `/tmp` 16 MB |
| Logs | json-file 10 MB × 3 |
| Network | dedicated bridge `tsb-p2-collector-net`, no published ports, no production networks |

- **Disk guard (fail closed, checked every 60 s):**
  - stop writing and enter `DEGRADED_DISK` when host free space is < **60 GB**, or `forward/` exceeds its quota
    (default **150 GB**);
  - warning at < 100 GB free, or at 80% of quota.
  - The collector never deletes data to make room.

## 16. Backpressure
- **Queues:** one bounded writer queue (default 50,000 records, about 25 MB) plus per-stream latest-state slots.
  Sample-and-hold means slow writing never multiplies memory.
- **Overflow:**
  - the newest records are dropped and counted as `dropped{type}`;
  - a gap record `cause=backpressure` is written;
  - after 60 s of sustained overflow, depth for Tier 1 is shed first, then Tier 2;
  - Tier 0 and candles are kept until last.
- **Integrity:** drops are always explicit, and a dropped observation is never reported as captured.

## 17. Health and alerts
- **Heartbeat:** `forward/health/collector_health.json`, written atomically every 10 s. It is not P1
  `service_heartbeats` and needs no database.

```json
{"ts_ms":…,"version":"…","boot_id":"…","state":"OK|DEGRADED|DEGRADED_DISK|BACKOFF|STOPPED",
 "ws":[{"conn":0,"connected":true,"streams":300,"reconnects_24h":1,"last_msg_age_ms":120}],
 "last_obs_age_ms":{"bookTicker":800,"depth10":2100,"candle_15m":64000,"miniTicker":31000},
 "last_durable_write_ms":…,"queue_depth":12,"dropped_24h":{"depth10":0},"gaps_open":0,"gaps_24h":2,
 "disk_free_gb":512.3,"forward_gb":3.1,"universe":{"date":"…","t0":2,"t1":62,"t2":30},
 "rest_weight_1m_own":18,"exchange_used_weight_1m_seen":140,"clock_skew_ms":10}
```

- **Container healthcheck:** the heartbeat age must be < 60 s.

| Alert | Warning | Critical |
|---|---|---|
| stale stream (Tier 0 bookTicker / depth) | > 15 s | > 120 s |
| reconnects | > 6 per hour | > 20 per hour, or backoff ≥ 15 min |
| sequence regression / validity failure | any (quarantined) | > 1% of a stream per hour |
| write failure | any retried | not durable for > 60 s |
| disk | < 100 GB free, or 80% of quota | < 60 GB free (collector halts writes) |
| checksum / validation failure at promotion | any (to quarantine) | > 1 per day |
| clock skew | > 250 ms | > 1,000 ms |
| exchange weight seen | > 2,400 | 429 / 418 received |
| queue overflow | any drop | sustained > 60 s |

Delivery (e.g. a Telegram ops message) is **not** part of E1. The health file is the contract.

## 18. Backup and retention
- **Separate job, `tsb-p2-forward-backup`.** P1-BG is not extended, so it stays small, fast and DB-focused.
  - **Schedule:** daily at 05:23 Europe/Berlin, clear of all existing jobs, after day D−1 is certified.
  - **Steps:** verify every SHA-256 in day D−1's manifest; copy the promoted segments into
    `~/backups/tsb-p2-forward/<date>/`; verify the copy.
  - **Locking:** `flock`.
  - **Restore test:** one random day per week.
  - **Volume:** about 0.25–0.3 GB per day. Keep 30 days of local copies.
- **Limit:** a same-disk copy protects against deletion and corruption, not host loss. **Off-host copies are
  required for real protection** and are part of the deferred DR decision.
- **Retention (proposed; nothing is deleted without owner approval):**

| Data | Local retention | Why |
|---|---|---|
| bookTicker and depth raw | ≥ 365 days at the recommended profile (≈ 100 GB); review at 6 months | irreplaceable |
| candles, derivatives, universe, gaps, health, manifests | indefinite | small; recoverable data kept for audit |
| daily certified aggregates (P2-C) | indefinite | reproducible, but cheap |

## 19. Canonical P2 integration (the collector never needs to know about decisions)
- **Join rule:** for a decision (P1 `candidate.evaluated` / `signal.ready` `event_time_ms`, or historical
  `signal_time`), take the **latest** observation with `available_at_ms <= decision_time_ms`, subject to these
  maximum ages:

| Observation | Maximum age |
|---|---|
| bookTicker | 3× tier cadence (Tier 0: 3 s; Tier 2: 6 s; Tier 1: 30 s) |
| depth | 3× cadence |
| closed candle | the last closed candle with `close_time < decision`; must equal the P1 `candle_id` when present |
| miniTicker | 120 s |
| premiumIndex | 120 s |
| openInterest | 10 min |
| funding | last settled `fundingTime ≤ decision`; the predicted rate comes only from a premiumIndex observation already available |

- An observation older than its limit becomes `MISSING_STALE`, never a forward-filled value.
- **Output:** `decision_market_context` rows with `provenance=OBSERVED`, `source=forward.<type>`, `observed_at_ms`,
  `available_at_ms`, and a `feature_version` for derived features. Keys are the P1 `candidate_id` /
  `signal_id` / `candle_id`.
- **No look-ahead:**
  - candles are fetched only when closed (`endTime = last closed open`), and joins require `close < decision`;
  - book state is joined only with `available_at ≤ decision`, so a post-decision book can never qualify;
  - funding / OI updates later than the decision cannot qualify;
  - no end-of-day value exists in the collector (`macro_history`-style daily last-write is not reproduced);
  - raw data is immutable, and derived features are versioned separately.

## 20. Security
- **Required credentials: none.** Spot and futures market data are public.
- **No** exchange key, funded key, trading key, Telegram token, PostgreSQL credentials or production `.env`.
- No Docker socket. Configuration is a read-only file of non-secret parameters.
- A future provider that needs a key (e.g. CoinGecko demo or CMC) goes through separate secret management with
  explicit authorization.

## 21. Failure isolation (why trading cannot be stopped by the collector)
| Collector failure | Effect on trading | Why |
|---|---|---|
| Binance disconnect | none | separate WS connections; trading has its own |
| corrupted segment | none | trading never reads `forward/`; the segment goes to quarantine |
| queue full | none | bounded memory under a container memory limit |
| crash / restart | none | separate container and compose project; no shared process, DB, network or volume |
| derivatives outage | none | optional task, marked degraded |
| rate-limit pressure | none (by design) | 5% cap plus yielding at 40% / 60% of the shared IP budget; stops entirely on 418 |
| **disk exhaustion (shared host)** | **possible**, so it is guarded | fail-closed halt at < 60 GB free or 150 GB quota, warning at < 100 GB; log size capped |

## 22. Deployment packaging (for P2-E1; not executed)
- **Image:** `tsb-p2-collector:<ver>`, from a pinned `python:3.12-slim` digest plus `aiohttp==3.14.3` (the version
  already reviewed for production).
  - Code from a reviewed PR; image digest recorded.
  - Runs as non-root uid 1000.
- **Compose:** a separate project and file, `/home/tradmin/ops/tsb-p2-collector/compose.yml`
  (`-p tsb-p2-collector`), **never** the production compose.
  - Mount: `forward/` read-write, nothing else.
  - Config file read-only. `COLLECTOR_ENABLED=false` by default.
  - Resource limits as in §15. Healthcheck on the heartbeat age.
  - `restart: unless-stopped` only after continuous mode is authorized.

## 23. Rollback (P2-E1)
1. `docker compose -p tsb-p2-collector -f /home/tradmin/ops/tsb-p2-collector/compose.yml stop collector`. This is
   a graceful shutdown that closes and promotes active segments.
2. `… rm -f collector`, and remove only that project's network if needed.
3. Keep every promoted segment, manifest, gap record and quarantine file. Delete no observations.
4. Production services, the production compose, PostgreSQL and the P1-BG schedule are not touched.
5. Verify with the production snapshot: identical containers, B3 / PAPER_HALTED unchanged.

## 24. P2-E1 test plan (synthetic / local fixtures for destructive cases; no production)
| Area | Tests |
|---|---|
| Schema and identity | schema validation; deterministic `obs_id`; duplicate messages deduplicated by `obs_id` |
| Time | timestamp ordering; null exchange time is never back-filled; clock-skew warning/critical marking |
| Transport | reconnect with backoff and jitter; WS gap → gap record; 24 h rotation overlap with no gap; REST failure → circuit breaker |
| Order data | `lastUpdateId` regression → quarantine; invalid book → quarantine |
| Capacity | queue overflow → explicit drops and shedding order; disk-write failure (EIO / ENOSPC) → DEGRADED, no false durability |
| Files | crash mid-segment → partial recovery plus gap record; checksum mismatch at promotion → quarantine |
| Rate limits | throttling (429 / 418 / high used-weight) → yield / stop |
| Lifecycle | graceful shutdown promotes segments; restart resumes |
| Safety | disk guard halts at the threshold; **no-trading-authority test** (see below) |

- **No-trading-authority test:**
  - the image contains no DB driver or credentials;
  - the network cannot reach the production network or postgres;
  - the code has no Telegram / order / signal path, enforced by a static grep test plus a network-isolation test;
  - nothing is mounted except `forward/`.

## 25. Bounded deployment gates (P2-E1)
| Gate | Action | Pass condition |
|---|---|---|
| G0 | reviewed PR; image build in isolation; digest; dependency check | tests green |
| G1 | deploy with `COLLECTOR_ENABLED=false` | isolation verified (networks, mounts, no secrets, limits); production snapshot identical |
| G2 | bounded capture **Tier 0 only, 2 h**; then stop | segments promoted, checksums OK, `u` / `lastUpdateId` monotonic, timestamps sane, gaps explained |
| G3 | bounded capture **recommended profile, 6 h** incl. a 15m/1h/4h close and a forced reconnect; then stop | measured MB/day, weight/min, CPU / memory within ±50% of this design; 0 unexplained gaps; production unaffected |
| G4 | review package to owner (raw inspection, budgets, alerts) | **owner authorizes continuous mode** separately; backup job installed before continuous mode |

## 26. Assumptions to re-verify at G0 (from Binance public documentation, not measured in E0)
- **Spot WS limits:** 1,024 streams per connection; 5 incoming messages per second; 300 connection attempts per
  5 min per IP; 24 h connection lifetime; server ping every 20 s with a pong required within 60 s.
- **Payload fields:** spot `@bookTicker` and partial `@depthN` payloads carry no event time (`E`).
  `!miniTicker@arr` carries `E`.
- **Budget accounting:** REST weights for `klines` (2), `depth` (≤ 100 → 5), `ticker/24hr?type=MINI` (all → 80),
  `time` (1), and fapi `premiumIndex` all (10). E1 re-reads `exchangeInfo` and measures the weight headers.

## 27. Owner decisions (only those that genuinely need the owner)
| # | Decision | Recommendation |
|---|---|---|
| D1 | Capture profile / local disk budget | **Recommended profile** (≈ 0.25–0.30 GB/day, ≈ 100 GB/year) with a 150 GB `forward/` quota and the 60 GB free-disk floor; review at 6 months |
| D2 | Store high-volume aggTrades forward? | **No.** They are fully recoverable from public daily aggTrades archives and can be backfilled on demand for the dates a study needs; that saves ≈ 120 MB/day |
| D3 | Derivatives in MVP or Phase 2? | **Phase 2** (disabled task in E1). Funding, mark/index and OI/ratios are recoverable from archives; only the live premiumIndex snapshot is unique, and it is low value for 15m+ decisions |
| D4 | Off-host copy for irreplaceable forward data | **Yes, together with the deferred DR decision.** About 8 GB/month compressed; a same-host copy is not protection against host loss |
| D5 | Local retention for bookTicker/depth raw | **Keep ≥ 1 year, nothing auto-deleted**; any future pruning only by explicit owner decision |

## Security: process-observability trust boundary (P2-E1 closure, 2026-10-04)
- **Scope of the v8 process-role check:** detects unexpected processes and escapes in the collector container's cgroup.
- **NON-BLOCKING TRUST-BOUNDARY LIMITATION:** anyone with Docker / container exec authority (privileged
  administrative access) can run the exact pinned HEALTHCHECK command during a legitimate Docker HEALTHCHECK window.
  If only one copy is sampled, it is indistinguishable from Docker's own probe.
- **Mitigation lives outside this mechanism:** restrict Docker-socket / exec access on the host. To be carried into
  the host-access document (`SINGLE_HOST_SAFETY.md`, absent on this branch).
- **Status:** continuous collector operation is NOT authorized; the collector remains STOPPED.
