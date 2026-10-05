# P2-X0 — Execution & transaction-cost model foundation

**Status:** foundation, offline only. Branch `feature/p2x0-execution-cost-20261005` (base `6db8ba5`). Not merged,
not deployed. It feeds nothing: not Paper, not the Collector, not the learner and not walk-forward. It has no alpha,
no performance trials, no Paper outcomes and no W3. Execution quality is **not** price forecasting
(P2G-ADR-09). P2-X1 is not started.

- Code: `p2_research/execution/` (stdlib only; never imports `p2_forward`; reuses the P2-C sealed-day reader).
- Frozen contracts: `p2_research/execution/contracts/*.json` with `FROZEN_SHA256SUMS.json` (section 12).
- Tests: `p2_research/tests/test_execution.py`.
- Governance: [ROADMAP_AND_RESEARCH_GOVERNANCE.md](ROADMAP_AND_RESEARCH_GOVERNANCE.md) §6 (P2-X boundary). Raw
  schema: `p2_forward/p2_forward/SCHEMA.md` (v2).

```
sealed forward data (immutable, read-only)                       Execution Adapter (Binance spot today)
  └─ market_state.load_sealed   reader verification + book / depth LADDERS / control records (pruned to query times)
      └─ PITMarketView(state, horizon)   only available_at_ms <= t; refuses t > horizon
          └─ quality.classify    staleness + data quality (collector semantics), fail closed
              └─ model.estimate_leg / round_trip   touch, fees, slippage, latency  →  Canonical Execution Schema
                  └─ coverage    real-data structural validation (coverage only, no returns)
```

## 1. Frozen terminology (`terminology_v1.json`, X0-TERMS 1.0.0)

| Term | Definition |
|---|---|
| decision time `T` | when a (hypothetical) strategy decides; only state with `available_at_ms ≤ T` is decision information |
| decision price | the PIT book state at `T` (bid, ask, mid): a **reference**, not executable; nothing fills at it in v1 |
| execution time | `T + declared_latency_ms`; the fill uses only state with `available_at_ms ≤ T + latency` |
| mid | `(bid + ask) / 2`: analytical only; the basis of the bps decomposition |
| touch | buy at the **ask**, sell at the **bid** of the execution-time book (marketable, taker) |
| spread / normalized spread | `ask − bid` (price) / `(ask − bid) / mid × 1e4` (bps) |
| spread cost | `side × (touch − mid) / mid × 1e4` (half spread) |
| fill price | `touch × (1 + side × s)`, `s` from the declared slippage model; equal to the touch only when the model declares `s = 0` (X0-S0) |
| slippage | `side × (fill − touch) / touch × 1e4`: **beyond the executable reference**. Not market movement, not spread, not fees, not adverse selection |
| latency drift | `side × (mid_exec − mid_decision) / mid_decision × 1e4`: market movement, **not a cost** |
| fee | rate on executed notional from the versioned fee schedule; never folded into a price |
| total cost | `side × (fill × (1 + side × fee) − mid) / mid × 1e4` = spread cost + slippage + fee + interaction (exact) |
| gross return | round trip: `mid_exit / mid_entry − 1` at the two execution times |
| net return | round trip: `fill_exit (1 − fee) / (fill_entry (1 + fee)) − 1` |
| adverse selection | post-entry movement against the position: a separate future **label**, always UNAVAILABLE in X0 |
| market impact | refused in X0 (section 7): always UNAVAILABLE |

`side = +1` (buy) / `−1` (sell). Entry and exit are separate legs; the design is direction-aware, but only
`direction = long` is accepted (`UnsupportedDirection` otherwise). There is no shorting, futures or margin, and any
market other than Binance spot is refused (`instrument.require_supported_market`).

## 2. Cost decomposition

With fractions `h` (spread cost), `s` (slippage) and `f` (fee):

- buy: `total = (1 + h)(1 + s)(1 + f) − 1`;
- sell: `total = 1 − (1 − h)(1 − s)(1 − f)`;
- `interaction = total − h − s − f` (second order, reported).

Every component is a separate field with its own provenance. Nothing is hidden inside an adjusted price: the fill
moves only by the declared slippage; fees are a separate rate. Future optional components (e.g. a borrow fee or an
impact term) would be new fields, and `interaction` keeps the sum exact. Tested on both sides and all scenarios.

## 3. Provenance classes

| Class | Used for |
|---|---|
| MEASURED | book bid / ask / quantities, depth levels, timestamps |
| DERIVED | mid, spread, spread cost, ages, latency drift, gross return |
| ESTIMATED | X0-S2 displayed-depth-walk slippage |
| ASSUMED | the fee schedule, X0-S0 / X0-S1 slippage, latency |
| UNAVAILABLE | null value plus a reason, never 0 |

A composite takes the **weakest** class of its parts. Any UNAVAILABLE part makes it UNAVAILABLE. Because the fee is
ASSUMED, every total cost in v1 is ASSUMED, and is never shown as measured.

## 4. PIT rule

- Decision reference: `PITMarketView(state, T)`. Execution state: `PITMarketView(state, T + latency)`.
- Every accessor refuses `t > horizon` (`PITViolation`). Every returned element is re-checked for
  `available_at_ms ≤ t`, so a faulty adapter cannot leak a future record (tested with a deliberately leaky source).
- "Latest at t" = the maximum `(available_at_ms, sample_ms)` with `available_at_ms ≤ t` (the same rule as P2-C).
  Because `observed ≤ sample_ms` (sample-and-hold), a record of a boundary `S ≥ t` whose quote was received at
  `observed ≤ t` is the true latest quote at `t`. Quotes superseded inside a sampling interval were never persisted
  and are never reconstructed.
- No future quotes, extrema, snapshots, health, lifecycle or gap records. Gap records are written when the gap
  closes. They are used only when `available_at_ms ≤ t` (an informational flag), and post hoc only in the
  coverage QA, never in an estimate.
- Tests inject future book and depth records (at absurd prices), a future health DEGRADED record, a future rotation
  and a future gap: the estimate is byte-identical, including `estimate_id`. They also cover direct future access
  refused, latency (a quote available at `T + 900` is used at `T + 1 s`, one at `T + 1001` is not) and W3 refusal.
- W3 = [2026-08-19T09:33:46Z, 2026-10-04T15:26:43.497803Z) is refused (`W3SealedError`, microsecond exact) for both
  the decision and the execution time. The real-data grid starts after it.

## 5. Entry and exit

- **Entry:** marketable BUY at the contemporaneous ask (execution-time book).
- **Exit:** marketable SELL at the contemporaneous bid.
- `round_trip(entry, exit)` requires the same instrument and scenario, and an exit strictly after the entry.
- Liquidity role: always taker. Maker / limit orders are refused because queue position cannot be observed.

## 6. Fee schedule contract (`fee_schedule_v1.json`, X0-FEE-BINANCE-SPOT-STD 1.0.0)

Fields: venue, market type, liquidity role, `rate_bps`, effective date / basis, tier, source, provenance and
assumption status.

The value is a frozen research **ASSUMPTION**: Binance spot regular user (VIP 0) standard rate, **10 bps taker**
(10 bps maker, unused), from public fee-schedule knowledge. It has no BNB discount, no promotion and no rebate. It
was never read from an account or credentials. `effective_from` is the research adoption date, not a venue date.

**Reconciliation:** identical to `labels.FEE_BPS_PER_SIDE = 10` (P2-C `exe.fee_bps_roundtrip = 2 × 10`, pinned by a
test; the label set is unchanged) and to the P2-D0 2 × 10 bps. A different rate, tier or discount is a new
**version**. Estimates carry the fee schedule id and version and the contract-set hash. The tests show a v2 schedule
changes the estimate and its id while the v1 estimate stays identical, and that a conflicting re-use of a version is
refused.

## 7. Slippage

### 7.1 Collector field audit

This audit is from the real sealed day 2026-10-04 (section 16): every record of the 83 certified segments was
validated and audited.

| Item | Recorded? | Notes |
|---|---|---|
| bid / ask + quantities | yes (bookTicker `b B a A`, verbatim strings) | event-driven top of book; sample-and-hold per boundary |
| depth levels + quantities | yes (`@depth20` Tier 0, `@depth10` Tier 1/2; `depth_levels` = N) | snapshot of the top N levels only |
| imbalance | derivable (book quantities; depth sums) | not an execution input in X0 |
| timestamps | `recv_ts_ns` → `observed_at_ms` = `available_at_ms`; `sample_ms`; `queued_ts_ns` | book / depth carry **no** exchange event time (null by design) |
| update IDs | book `u`, depth `lastUpdateId` (same ID space per symbol) | used to order depth vs book (`depth_minus_book_seq`) |
| trade prints | **no** (aggTrades / trades are not captured) | no realized-trade check, no volume-at-price |
| volume | 24 h rolling `q` (miniTicker) and candle volume | not an execution input |
| cadence by tier | run record: book T0 1 s / T1 10 s / T2 2 s; depth T0 1 s (20 levels) / T1 60 s (10) / T2 5 s (10) | all depth records had the full N levels on both sides |
| stale flags | `unchanged`, `clock_suspect`, stale limits in the run record | section 9 |
| gaps | gap records (written at close), health `streams_not_observing` (real time) | section 10 |

### 7.2 Models (`models_v1.json`)

| Model | Definition | Provenance |
|---|---|---|
| **X0-S0** | touch only, `s = 0` | ASSUMED |
| **X0-S1** | fixed stress per side: ZERO 0 / LOW 5 / MODERATE 10 / SEVERE 25 bps | ASSUMED |
| **X0-S2** | displayed-depth walk of the PIT depth snapshot for `order_notional` | ESTIMATED |

- **S1 justification:** fixed before any real-data inspection and never tuned. 5 and 10 bps are exactly the P2-D0
  protocol sensitivity (+0 / +5 / +10, §9), so P2-D stays comparable. 25 bps (2.5 × the fee unit) is a severe
  bound for quotes held over the slowest sampled cadences (Tier-1 book 10 s, Tier-1 depth 60 s) or books thinner
  than the order.
- **S2 walk:**
  - BUY spends `order_notional` across asks ascending; SELL sells `order_notional / L1_bid` base across bids
    descending.
  - `s = side × (vwap − L1) / L1` is relative to the snapshot's **own** level 1, so book/depth timing differences
    never enter `s`. The fill is then `book_touch × (1 + side × s)`.
  - S2 is UNAVAILABLE for:
    - no or invalid depth state;
    - an invalid ladder (non-monotone, non-positive price, negative quantity, empty side);
    - a crossed snapshot;
    - an order larger than the displayed notional of the side (**never extrapolated**).
  - Reported per estimate: `depth_levels`, `n_side`, `levels_used`, `displayed_notional`, `vwap`, `depth_l1`, and the
    depth-vs-book L1 difference and update-ID difference. Flags: `depth_incomplete` (fewer levels than
    subscribed) and `depth_book_inconsistent` (the depth L1 crosses the book touch).

### 7.3 Refusals and limitations

- **Market impact precision is refused.** There are no trade prints, no queue position and no hidden or iceberg
  liquidity. The depth is a **sampled** snapshot: Tier 0 every 1 s with 20 levels, Tier 2 every 5 s with 10,
  Tier 1 every 60 s with 10. A walk is a lower bound on the cost of consuming displayed liquidity at the snapshot
  instant, not an impact estimate.
- **Not modeled:** partial fills, fill probability, maker / limit orders, and liquidity replenishment between
  samples.
- Intermediate quotes inside a sampling interval are never observed.
- Book and depth are separate streams (nothing is atomic across streams).

## 8. Order notional

- `order_notional` is an **input** (quote currency) on every estimate and is never optimized.
- The coverage run uses 50 USDT, the current Paper stake, for the canonical estimates. Depth-walk coverage is
  reported for 10, 50, 100, 250, 500, 1,000, 5,000 and 10,000 USDT.
- No sizing optimization: that is P2-RM.

## 9. Quote staleness (X0-STALE-COLLECTOR 1.0.0)

The thresholds are the collector's **own** semantics, read from the run record of the boot that wrote the record
(`semantics.stale_ms`; the cadence comes from the record). They are not derived from any return.

| Stream | TOO_STALE (→ INVALID) | DEGRADED | VALID |
|---|---|---|---|
| book T0 | age > `book_t0` (120 s) | — (soft = hard) | age ≤ 120 s |
| book T1/T2 | age > `book_t12_dead` (600 s) | age > `book_t12_suspect` (120 s) | age ≤ 120 s |
| depth | age > `depth_by_tier[t]` (2 s / 180 s / 15 s) | age > cadence (collector "aging") | age ≤ cadence ("fresh") |
| confirmation (both) | gap > 3 × cadence → MISSING (the collector HEALTHY rule) | gap > cadence | otherwise |

- Book soft limit: bookTicker is event-driven, so an age within 120 s means "no top-of-book change", not staleness
  (SCHEMA §3).
- `quote_age_ms` = `t − observed_at_ms`. `confirmation_gap_ms` = `t −` the latest persisted boundary `≤ t`.
- Both ages and the decision-book age are emitted on every estimate.

## 10. Data quality (X0-DQ 1.0.0): fail closed

- **INVALID** (execution price UNAVAILABLE, never a favorable or fallback fill):
  - no book;
  - downtime (no run);
  - record from a previous run;
  - too stale;
  - stream missing (confirmation);
  - stream not observing (latest health, no newer record);
  - crossed or locked book;
  - non-positive price.
- **DEGRADED** (estimate produced, flagged):
  - age or confirmation in the soft band;
  - collector not HEALTHY;
  - stream recovered after not observing;
  - no health record in the run;
  - quote observed before the latest connection event of its connection (reconnect, rotation, stall);
  - clock suspect.
- **Informational** flags: `gap_known_1h`, `depth_incomplete`, `depth_book_inconsistent`, `unchanged`.
- Depth rules gate X0-S2 only.
- **Load level:**
  - conflicting duplicates fail the load (`AmbiguityError`);
  - unsealed days are refused;
  - segment SHA / sidecar / manifest / count are verified (reader functions).

## 11. Adverse selection

Post-entry price movement is a separate future research **label**. The schema holds `adverse_selection_bps`
(always UNAVAILABLE, reason `future_research_label_not_computed_in_x0`) distinct from `slippage_bps` and
`latency_drift_bps`.

## 12. Determinism and versioning

- `estimate_id` = SHA-256 of the canonical JSON (sorted keys, 12 significant digits, no NaN) without the id.
- Each estimate carries:
  - the execution, latency, slippage, fee, stale and DQ model ids and versions, and the scenario id and version;
  - `contract_set_sha256` (the SHA-256 of `FROZEN_SHA256SUMS.json`);
  - market-data source: dataset id, `dataset.json` SHA, days, seal SHA per day, reader and loader versions;
  - instrument identity, notional and currency, direction, side and leg, decision and execution times;
  - the collector `obs_id` of the decision book, execution book and depth used.
- Loading refuses any contract file whose hash differs from the recorded sum. A changed model needs a new version
  and a re-frozen sum, which changes `contract_set_sha256` and every `estimate_id` (tested). Old research is never
  silently rewritten.
- Coverage outputs: canonical JSONL, gzip `mtime=0`, and a manifest whose `logical_hash` excludes nothing
  time-dependent. A rebuild (and a rebuild from the sealed-day backup) gives the identical hash and bytes.

| Contract file | SHA-256 |
|---|---|
| terminology_v1.json | `067d55e7ef858d4bded731b8f7a151a496305be043125f2567e459c29bed8381` |
| fee_schedule_v1.json | `62b98d1142a564ad2cea0f7cf1043d21e49ca79f0887b1d76d45124e738e0b70` |
| models_v1.json | `f6c94cb51a37637895e935cb8cd9319ad021e39c2a685e43bd0ea8a85034d37c` |
| scenarios_v1.json | `7196da847be9e72d9164a347e6977f91a19da1439412bcdf0ddb12e6932e19c7` |
| result_schema_v1.json | `a1df0c6174cc9a61119e60c5dc44ee9911a0cfe4563c3b3d0e91a7cd2606b45b` |

`FROZEN_SHA256SUMS.json` (`contract_set_sha256`): `3c554702948867fa26d4bba95b922f5e1db5902e42b088d9cdc49fdceefeec2f`.

## 13. Frozen scenarios (`scenarios_v1.json`)

| Scenario | Latency | Slippage | Fee | Use |
|---|---|---|---|---|
| **EXEC-IDEALIZED** | X0-LAT-0 (0 ms) | X0-S0 | 10 bps taker | lower bound: touch + fees |
| **EXEC-BASE** | X0-LAT-1S (1 s) | X0-S2 depth walk | 10 bps taker | best defensible current model; UNAVAILABLE where the depth cannot support it (no fallback) |
| **EXEC-STRESS** | X0-LAT-5S (5 s) | X0-S2 + X0-S1-MODERATE (10 bps) | 10 bps taker | adverse but plausible |

- **Latency justification:** about one REST round trip from this host (collector clock probes: RTT/2 ≈ 130 ms),
  rounded up to the 1 s sample grid. 5 s is a stress value. Both are ASSUMED.
- Latency changes **which state** is met (`latency_drift_bps`, market movement). It is not a cost.
- X0-S1 values are a sensitivity table, not extra scenarios.

## 14. Canonical result schema (`result_schema_v1.json`)

- **Leg:**
  - times: decision time, execution time and latency;
  - identity: instrument, tier, direction, side, leg, liquidity role and order notional;
  - prices: decision bid / ask / mid, then bid, ask, mid, touch and fill at execution;
  - costs: spread, `spread_bps`, spread cost, fee, slippage, interaction, total cost and latency drift;
  - always UNAVAILABLE in X0: adverse selection, market impact, and gross / net return (`leg_only`);
  - quality: market-data ages, data-quality state and flags (book, depth, decision book);
  - provenance and lineage: cost provenance, model versions, the contract-set hash, market data, depth walk and
    source references.
- **Round trip:** both leg ids, gross and net return, both leg costs, cost provenance and the worst quality state.
- Every numeric field is a Quantity `{value, provenance, reason}`; UNAVAILABLE is `null` plus a reason, never 0
  (tested over every field of every scenario).

## 15. Tests (`test_execution.py`)

- buy at ask / sell at bid; exact spread decomposition (both sides, 3 scenarios);
- fees (ASSUMED, reconciled with P2-C); zero-slippage baseline; explicit stress (S1 set, STRESS = walk + 10 bps);
- stale (TOO_STALE → UNAVAILABLE; soft band → DEGRADED); missing (gap, downtime, previous run);
- gap / DQ failures: not observing, recovered, not HEALTHY, crossed, rotation, clock, known gap;
- future-data injection is byte-identical; a leaky source is caught; latency semantics; W3 refused (end exclusive);
- depth walk by hand (levels, VWAP, exceed → UNAVAILABLE, sell side, invalid / crossed ladder); notional is an input;
- deterministic rebuild under shuffled input; fee-version change; model-version change and tamper refusal;
- no `p2_forward`, DB, network or Paper references; P2-D0 frozen hashes unchanged;
- the sealed adapter on the synthetic dataset: pruned == full, unsealed refused; the coverage tool is
  byte-deterministic and refuses the dataset or collector tree as output.

## 16. Real-data structural validation (sealed 2026-10-04)

This section measures **coverage only**. It contains no returns and no profitability, and it does not inspect W3.

- **Eligible days:**
  - 2026-10-04: sealed PASS and backed up.
  - 2026-10-05: **not used**. It was not yet closed or sealed at run time; `seals/2026-10-05.json` was absent.
- **Decision grid:** the P2-C grid `grid-15m-plus390s-v1` strictly after the W3 end. 62 grid points of the day lie
  at or before the W3 end, which includes the pre-start downtime; they are excluded before loading. 34 decision times remain (15:36:30Z–23:51:30Z).
  The universe known at T has 38 symbols (T0 2, T1 6, T2 30).
- **Estimates:** 1,292 instrument-times × 3 scenarios × 2 legs = 7,752 estimates at a 50 USDT notional.
- **Run (`coverage`) under the envelope:**
  - `systemd-run --scope CPUQuota=100% MemoryMax=2G`, `nice 15`, `ionice -c3`, `prlimit --as=2 GiB`;
  - about 61 s wall / 61 s CPU / 147 MB peak RSS;
  - output 1.2 MB.
- **Determinism:** a rebuild from the **sealed-day backup** is byte-identical (logical hash
  `f313ac707546c9722a139fec5deb7dfd1fcd28d2a9b38b6fc1e6784072d261e8`).

| Question | Answer (2026-10-04, after W3) |
|---|---|
| Can bid/ask be reconstructed at decision times? | **Yes.** 1,292 / 1,292 instrument-times have a PIT book state (0 INVALID). Confirmation gap 0 ms (every grid T falls on a persisted boundary). |
| How often is executable state available? | EXEC-IDEALIZED 2,584 / 2,584 legs; EXEC-STRESS 2,584 / 2,584; EXEC-BASE **2,582 / 2,584**. The 2 BASE refusals: at 21:21:30Z the collector health was DEGRADED and listed GLMRUSDT depth as not observing → depth INVALID → X0-S2 UNAVAILABLE (fail closed, no fallback). |
| Quote age by tier (book, at T: p50 / p90 / p99 / max) | T0 0.08 / 0.54 / 2.7 / 2.7 s; T1 0.6 / 3.8 / 12.9 / 18.8 s; T2 0.5 / 3.6 / 18.6 / 72.7 s (all within the 120 s soft limit). Over all records, `sample − observed` reaches 98.7 s (T2), consistent with P2-C1. |
| Depth age by tier (at T) | T0 about 0.85 s; T2 0.6 / 0.9 / 2.4 / 11.0 s; **T1 about 30.5 s** (60 s cadence; the +390 s grid offset lands mid-interval). |
| How often stale or missing? | Book: 0 TOO_STALE, 0 MISSING, **38 DEGRADED** (2.9 %). All DEGRADED come from the one T with collector health DEGRADED. Depth: 1 INVALID (stream not observing), 2 age DEGRADED (T2). |
| MEASURED / DERIVED / ESTIMATED / ASSUMED / UNAVAILABLE | MEASURED: bid, ask, touch (all legs). DERIVED: mid, spread, spread cost, latency drift. ESTIMATED: BASE slippage and fill (depth walk). ASSUMED: fee (every leg), IDEALIZED / STRESS slippage and fill, latency, **every total cost** (because of the fee). UNAVAILABLE: adverse selection, market impact, leg gross/net return (by design), and the 2 BASE refusals. |
| Can 50 USDT be evaluated against displayed depth? | **Yes.** BASE timing (T + 1 s): T0 68/68, T1 204/204, T2 1,019/1,020. 1 level suffices in T0 100 %, T1 94–98 %, T2 89–90 %. The walk stays inside displayed depth up to 1,000 USDT in 98.8–99.6 % of T2 cases; at 10,000 USDT, T2 drops to about 80 % (`notional_exceeds_displayed_depth` → UNAVAILABLE, never extrapolated). |
| Latency semantics on real data | The execution book differs from the decision book in 17 % of BASE (1 s) and 80 % of STRESS (5 s) legs, and 0 % at 0 ms. The difference is reported as `latency_drift_bps`, not as cost. |
| Real-time vs post-hoc gaps (QA) | 0 decision instants fell inside a later-known gap. The day had 14 gaps (book `awaiting_post_reconnect_data` 4 in the spill-over rotation hour; depth `stale_stream` 8 and `conn_data_stale` 2). The synthetic fixture exercises the case (a gap boundary is classified INVALID in real time). |

**Field audit facts** (all records of the day + spill-over):

- **Record counts:** book 669,785, depth 308,160, market 634, candle 2,283, health 646, lifecycle 476, gap 14,
  clock 64.
- **Not captured:** no trade or aggTrade record type exists.
- **Event times:** book and depth `exchange_event_time_ms` are null everywhere; only market, candle and clock carry
  one.
- **Unchanged books:** T2 16.8 %, T0 2.7 %, T1 1.5 %.
- **Clock-probe RTT** (58 probes): 251–271 ms (p50 261). This supports the 1 s latency declaration.
- **Market snapshot:** miniTicker components can be very old (they contain only changed symbols; p99 748 s over all
  symbols). Not an execution input.

**What limits a more realistic impact model:**

- No trade prints: no realized-fill or volume-at-price check.
- Depth is a sampled top-N snapshot: T1 snapshots are about 30 s old at the grid offset (60 s cadence), and in 27 % of T1 BASE legs
  (108 of 2,040 T2, 7 of 136 T0) the depth L1 already crosses the newer book touch (`depth_book_inconsistent`).
  The walk is therefore taken relative to the snapshot's own L1 and is a shape estimate, not a contemporaneous
  ladder.
- 10 levels (T1/T2) cap the walkable notional.
- No queue, hidden liquidity or replenishment information.
- No exchange event time for book and depth.
- One partial sealed day (8.4 h after W3, 38 symbols) is a structural check, not a statistical sample.

## 17. PAPER-R1 reconciliation (documentation only; future, separately authorized)

- **The comparison:** per Paper trade,
  - (a) the Paper **assumed fill** (`trade.opened` entry price);
  - (b) the **P2-X reconstructed reference** for the same instrument at the Paper decision `event_time_ms`
    (EXEC-IDEALIZED / BASE / STRESS from the collector book and depth, `obs_id` recorded);
  - (c) a **future real fill**, only if live trading were ever authorized (not now).
- **Join keys:** P2C_RESEARCH_LAYER §8 (`candidate_id` → `signal_id` → tracker events; an as-of join on
  `available_at_ms ≤ event_time_ms`).
- **Prerequisites:**
  - the instrumentation gaps of P2G-ADR-10 (collector `obs_id` for the Paper entry price, host clock offset);
  - Paper outcomes outside W3 and only through a predeclared evaluation.
- Nothing in X0 reads Paper data, the Paper fill price or its outcomes. No Paper change.

## 18. Dead-letter design note (documentation only; not implemented)

PAPER-R1 currently records cap-full expired signals as dead letters: 19 deferrals, beside 245 historical, 264 in
total. A future, separately authorized change should evaluate an explicit operational state `CAP_REJECTED` /
`EXPIRED` for a signal refused because the position cap was full, instead of a dead letter. It would be a terminal
state with the cap snapshot and expiry time, auditable and excluded from the replay tooling. Dead letters would
then mean delivery or processing failures only. No dead letter is replayed, deleted or modified, and nothing is
implemented here.

## 19. Open items

- O-X1 the fee is ASSUMED: verification needs a public fee-schedule snapshot (no credentials) recorded as a new
  version.
- O-X2 the S2 walk is a displayed-depth lower bound: calibration needs real fills (section 17).
- O-X3 latency is ASSUMED: Paper / host decision-to-order latency is not instrumented.
- O-X4 adverse-selection labels (post-entry movement) are a separate future label set.
