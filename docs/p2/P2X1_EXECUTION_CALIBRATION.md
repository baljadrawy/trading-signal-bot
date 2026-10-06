# P2-X1 — Execution calibration & contract closure

**Status:** offline research only. Branch `feature/p2x1-execution-calibration-20261006` (base `6d5aadb`, P2-X0).
Not merged, not deployed. Nothing here feeds Paper, the Collector, the learner or walk-forward. No alpha, no
strategy P&L, no P2-D trial or hypothesis was run or inspected, no PAPER-R1 data was read, no W3 data was used, no
active-day (2026-10-06) data was read. P2-RM0 is not started.

- Code: `p2_research/execution/{calibration,join,scenario_result,contracts_v2}.py` (stdlib only).
- Contracts: **new** frozen set `p2_research/execution/contracts_v2/` (X1, `FROZEN_SHA256SUMS.json`
  record_version 2). The P2-X0 set `contracts/` (v1) is byte-identical and still governs every v1 estimate.
- Tests: `p2_research/tests/test_execution_x1.py` (+ the unchanged X0 suite).
- Evidence: `/home/tradmin/backups/tsb-aiohttp-20260929T122701Z/p2x1-<UTC>/` (see section 18).
- Predeclaration: `contracts_v2/calibration_plan_v2.json` (notional set, buckets, windows, timestamps, classification
  rules) was committed and pushed in `2245a06` **before** any real-data run.

| # | Deliverable | Result |
|---|---|---|
| 1 | Re-verify P2-X0 | PASS: commits, 109/109 tests, v1 hashes, evidence seal, byte-identical rebuild, PIT poison test on real data |
| 2 | Fee contract | `X1-FEE-BINANCE-SPOT-GENERIC` 2.0.0: 10 bps taker, ASSUMED, generic public tier, no discounts; versioned substitution |
| 3 | Latency | order path UNAVAILABLE; network RTT to a public data endpoint MEASURED (lower bound only); 0/1/5 s kept as ASSUMED research sensitivities |
| 4 | Spread | by tier / liquidity / quote age / health; reconstruction exact at T, "latest persisted" off-grid |
| 5 | Quote / depth age | distributions + reconnect / gap proximity; every collector threshold OPERATIONAL_ONLY → POLICY (ASSUMED) |
| 6 | Displayed depth | 50 / 500 / 5,000 USDT predeclared; % sufficient / multi-level / refused by tier |
| 7 | Truth boundary | frozen statement (section 7) |
| 8 | Stress 0/5/10/25 | ASSUMED SENSITIVITY SCENARIOS; none empirically calibrated; kept (relabelled only) |
| 9 | Scenarios | IDEALIZED / BASE / STRESS 2.0.0 fully specified; arithmetic identical to v1 |
| 10 | Uncertainty | `scenario_set_result`: gross + three nets + per-component provenance, never collapsed |
| 11 | P2-C ↔ P2-X | 6 gaps closed in `p2c_join_v2.json` + adapter; no frozen output rewritten |
| 12 | Join determinism | 5,035 keys unique, 0 ambiguous, 0 PIT violations, 152 unmatched (all W3), byte-identical A/B |
| 13 | Reconciliation | design only (`reconciliation_design_v2.json`) |
| 14 | Success principle | contract + validator; gross > 0 alone never success |
| 15 | Tests | full suite pass (section 15); P2-D0 and P2-X0 v1 hashes unchanged |
| 16 | Ops | before / after identical (section 16) |
| 17 | Defects | 2 minor P2-X0 defects fixed with regression tests (section 17) |

## 1. Independent re-verification of P2-X0

- **Branch / commits:** `origin/feature/p2x0-execution-cost-20261005` = `6d5aadb`; `694e8b8` (code, contracts, tests)
  and `6d5aadb` (doc). `git diff 6db8ba5..6d5aadb` adds only `p2_research/execution/*`, its tests and the doc.
- **Tests:** baseline run of the unchanged X0 tree: **109 / 109 passed** (390 s, 470 MB peak, envelope).
- **Contract hashes:** the five v1 files and `FROZEN_SHA256SUMS.json` (`3c554702…eec2f`) recomputed equal to the
  P2-X0 document; now pinned by `TestContractsV2.test_v2_frozen_and_v1_untouched`.
- **P2-D0 frozen specs:** the four `p2_research/research/*_v1.json` hashes unchanged (tested twice).
- **Evidence seal:** `p2x0-20261005T215124Z/SHA256SUMS` hash `832d3ec6be1a…c4b8`; `sha256sum -c` 37 / 37 OK, read-only.
- **Deterministic rebuild:** the X0 coverage tool (worktree at `6d5aadb`) on the sealed-day **backup** of 2026-10-04
  reproduced logical hash `f313ac70…61e8` and byte-identical `estimates.jsonl.gz`, `coverage.json`, `manifest.json`
  (58 s, 147 MB).
- **PIT rules:** in addition to the synthetic X0 tests, a new **real-data poison test**: for 22 sampled post-W3
  decision times and every symbol known at T, all estimates (3 scenarios × 2 sides × v1 and v2 contracts) were
  recomputed on a copy of the real pruned state where every book / depth record available after T + 5 s was
  replaced by absurd prices / crossed ladders, plus a DEGRADED health record listing every stream, a rotation, a
  covering gap and a clock-suspect record at T + 5 s + 1 ms: **10,224 estimates compared, 0 differences**
  (`pit_poison_real.json`).
- **Scenarios:** IDEALIZED (0 ms, touch), BASE (1 s, depth walk), STRESS (5 s, walk + 10 bps) as documented.
- **No assumption was promoted to MEASURED.** Fee, latency and the S1 values stay ASSUMED.
- **Overclaims found (documentation only, v1 not edited):** P2-X0 §16 says the clock-probe RTT "supports the 1 s
  latency declaration" and `X0-LAT-1S` calls it "one REST round trip". The probe is a **public market-data**
  endpoint (`data-api.binance.vision /api/v3/time`), not order entry; it bounds nothing end-to-end. Superseded by
  the v2 wording (section 3).

## 2. Fee contract (`fee_schedule_v2.json`)

| Field | Value |
|---|---|
| id / version / version_date | `X1-FEE-BINANCE-SPOT-GENERIC` / 2.0.0 / 2026-10-06 |
| venue / market type | binance / spot |
| maker / taker | taker 10 bps (used); maker 10 bps (unused: maker orders refused) |
| account scope | `GENERIC_PUBLIC_STANDARD_TIER` (regular user, VIP 0) — **not** the owner's fee |
| verification | `UNVERIFIED_ASSUMPTION`; provenance **ASSUMED**; `evidence` null |
| effective_from | 2026-10-06T00:00Z = research adoption date, **not** a venue date |
| discounts | none (no BNB, VIP, promotion, rebate, zero-fee pair) |

`contracts_v2.validate_fee_schedule` refuses an unevidenced discount, an unverified `ACCOUNT_SPECIFIC` entry,
`MEASURED` without realized commissions, a verified status without evidence, and any unverified entry not marked
ASSUMED. **Substitution:** a verified account fee is added as a new schedule (`add_fee_schedule`,
`<id>@<version>`), e.g. `VERIFIED_ACCOUNT_RECORD` (owner-supplied statement) or `VERIFIED_REALIZED_COMMISSIONS`
(only then MEASURED). Estimates name `fee_schedule id@version`; old estimates keep their ids (tested: substitution
changes fee, provenance and id; the original estimate is byte-identical). Same rate as v1 and P2-C / P2-D0.

## 3. Latency decomposition

| Component | Class | Evidence (eligible sealed data) |
|---|---|---|
| exchange event → collector receive (feed) | DERIVED (miniTicker only) | `observed − E` p50 176 ms, p99 1.7 s (skew not removed, batching); book / depth: no event time → UNAVAILABLE |
| signal decision | UNAVAILABLE | no strategy evaluated; Paper timing not read |
| application processing | UNAVAILABLE | no order path |
| order creation | UNAVAILABLE | no order code, no credentials |
| network to order entry | UNAVAILABLE | proxy **MEASURED**: public REST `/api/v3/time` round trip, 194 checks × 3 probes: min-of-3 250.7–295.5 ms (p50 262); warm probes median ≈ 263 ms; first probe after ≈ 10 min idle median ≈ 1.04 s, max 2.6 s |
| exchange matching + ack | UNAVAILABLE | no order |
| fill report | UNAVAILABLE | no fills |
| host clock offset | DERIVED | skew −22.9…−2.3 ms, uncertainty 125–148 ms |
| **end-to-end decision → fill** | **ASSUMED** | the scenario value |

**Decision:** 0 / 1 / 5 s is kept as a **small research sensitivity framework** (`X1-LAT-*`, class
`RESEARCH_SENSITIVITY_SCENARIO`, ASSUMED, "not an observed order latency"). It is defensible only as that: 1 s lies
above the warm public RTT and near the cold-request RTT, and on the 1 s sample grid; nothing proves it end to end.
No grid was added. **Resolution limit:** latency is visible only at the stream cadence (book T0 1 s / T2 2 s / T1
10 s; depth 1 / 5 / 60 s). Tier-1 book at T + 1 s equals the T record in 873 / 875 cases; Tier-1 depth at T + 1 s
and T + 5 s is the T snapshot in 875 / 875.

## 4. Spread (observed, not a future cost)

Window: W3 end (15:26:43.498Z on 2026-10-04) → 2026-10-06T00:00Z, sealed days only. 130 decision times, 5,035
instrument-times (T0 260, T1 875, T2 3,900), × 3 execution timestamps. No join to returns.

| spread bps at T + 1 s | n | p50 | p90 | p99 | max |
|---|---|---|---|---|---|
| Tier 0 (BTC, ETH) | 260 | 0.0012 | 0.037 | 0.037 | 0.037 |
| Tier 1 | 875 | 2.97 | 5.67 | 23.2 | 23.3 |
| Tier 2 | 3,900 | 1.98 | 8.40 | 22.8 | 32.6 |

All persisted boundaries (population A): T0 234,371 / T1 78,888 / T2 1,757,752 records, p50 0.037 / 2.97 /
1.98 bps, p99.9 0.037 / 23.3 / 28.2, max 3.9 / 23.3 / 64.5 bps; 0 crossed or non-positive books.
By liquidity state (displayed top-10 notional, both sides) Tier 2: `<50k` p50 1.96 / p99 25.0; `50k–500k` 1.96 /
11.8; `500k–5M` 3.64 / 22.8 bps (a symbol-mix effect: not a monotone liquidity relation). By quote age Tier 2:
≤1 s p50 1.80, 1–10 s 1.98, 10–60 s 5.35 bps (older quotes belong to quieter, wider symbols). By health: no
material difference (not-HEALTHY n = 6 / 18 / 90). Full tables: `calibration.json`.

**Reconstruction reliability:** book state at the timestamps: T0 258 VALID + 2 DEGRADED, T1 869 + 6, T2 3,870 + 30
at every latency, **0 INVALID**; all DEGRADED = one decision time with collector health DEGRADED. At T (on the
grid) **100 % confirmed exact** (latest received quote). Off-grid: T0 100 % (1 s cadence), T2 24 % / 25 % and T1
1 % / 4 % at +1 s / +5 s confirmed exact; the rest are "latest persisted only" with an unobserved window of 1 s
(T2) or 1–5 s (T1). Depth: 1 INVALID (T2, stream not observing) at T and T + 1 s.

## 5. Quote age, depth age and thresholds

| age (ms) | T0 book | T1 book | T2 book | T0 depth | T1 depth | T2 depth |
|---|---|---|---|---|---|---|
| boundaries p50 / p99.9 / max | 75 / 2,201 / 7,200 | 678 / 26,254 / 81,761 | 355 / 36,287 / 116,244 | 847 / 902 / 1,994 | 499 / 3,785 / 7,414 | 570 / 6,481 / 14,956 |
| at T + 1 s p50 / p99 / max | 70 / 1,093 / 1,213 | 1,588 / 13,856 / 28,966 | 1,241 / 13,320 / 73,737 | 847 / 852 / 852 | 31,499 / 33,503 / 36,501 | 1,570 / 3,482 / 11,954 |

Boundary ages are **censored** by the collector's persistence limits (a value older than its limit becomes a gap),
so they cannot validate those limits. Proximity (60 s windows, predeclared; small n): within 60 s after a
connection event book ages are lower (T2 p99 9.2 s vs 12.7 s steady) but depth ages higher (T0 p99 1.9 s vs 0.85 s;
T2 3.8 s vs 2.5 s); gap-adjacent ages are higher (T2 book p99 23.7 s vs 12.7 s; T2 depth 13.0 s vs 2.5 s). Connection events in the window: 3 connects, 2 disconnects, 1 rotation per connection; gaps:
book 107, depth 205, market 1 (by cause in `calibration.json`).

**Threshold classification** (predeclared rule): every collector threshold — book T0 120 s, T1/T2 120 s suspect,
600 s dead, depth 2 s / 15 s / 180 s, confirmation 3 × cadence — is **OPERATIONAL_ONLY** (persistence / health /
dead-stream bounds with no execution-quality rationale). None is a defensible research threshold; P2-X uses them as
**POLICY (ASSUMED)**. Notably the 180 s Tier-1 depth limit admits a 30–41 s old snapshot at every timestamp; as an
execution-quality threshold it would be insufficiently supported. No new threshold was introduced.

## 6. Displayed depth (predeclared 50 / 500 / 5,000 USDT; EXEC-BASE timestamp T + 1 s)

| Tier, side | 50: sufficient / multi-level / refused | 500 | 5,000 |
|---|---|---|---|
| T0 buy | 100 % / 0.4 % / 0 | 100 % / 1.9 % / 0 | 99.6 % / 5.0 % / 0.4 % |
| T0 sell | 100 % / 0.4 % / 0 | 100 % / 1.5 % / 0 | 100 % / 3.8 % / 0 |
| T1 buy | 100 % / 5.3 % / 0 | 100 % / 16.5 % / 0 | 100 % / 62.3 % / 0 |
| T1 sell | 100 % / 5.1 % / 0 | 100 % / 19.3 % / 0 | 100 % / 64.7 % / 0 |
| T2 buy | 99.97 % / 11.2 % / 0.03 % | 99.74 % / 35.1 % / 0.26 % | 88.2 % / 66.1 % / 11.8 % |
| T2 sell | 99.97 % / 10.7 % / 0.03 % | 99.59 % / 33.7 % / 0.41 % | 88.8 % / 63.7 % / 11.2 % |

"multi-level" is a share of all timestamps; refusals are `notional_exceeds_displayed_depth` or `depth_state_invalid`
(UNAVAILABLE, never extrapolated). T1 depth is 30–41 s old; its level 1 crosses the newer book touch at T + 1 s in
33.9 % (buy) / 31.3 % (sell) of Tier-1 cases (T0 10.0 / 8.1 %, T2 6.5 / 6.3 %): those walks are ladder-shape
estimates (`depth_book_inconsistent`).

Displayed-depth walk slippage at T + 1 s (ESTIMATED, supported walks only, so conditional on sufficient depth;
p50 / p99 bps, buy): 50 USDT T0 0 / 0, T1 0 / 3.6, T2 0 / 3.8; 500 USDT T1 0 / 5.1, T2 0 / 8.0; 5,000 USDT T0 0 /
0.41, T1 0.92 / 8.7, T2 1.25 / 12.4 (sell side similar). A lower bound on displayed-liquidity consumption, not
impact or realized slippage.

## 7. Slippage truth boundary (frozen in `terminology_v2.json`)

| Item | Available? |
|---|---|
| exchange event time on book / depth | no (null in 100 %; only market, candle, clock carry one) |
| price levels | top 20 (T0) / 10 (T1, T2) of sampled snapshots |
| trades / prints / aggTrades | no record type exists |
| queue position, hidden / iceberg liquidity | no |
| submitted orders, acknowledgements, fills, partial fills, commissions | no (no order is ever sent) |

> "P2-X reconstructs touch (top-of-book) and displayed-book-consumption scenarios from sampled public market data,
> but it cannot measure actual market impact, realized slippage, fill probability, queue position or realized
> execution cost: no order is ever submitted, so there are no acknowledgements, fills, partial fills or
> commissions, and the data carry no trade prints and no exchange event time on book or depth."

## 8. Stress values 0 / 5 / 10 / 25 bps per side

0 = PURE_SENSITIVITY (zero point); 5 and 10 = POLICY_OR_LITERATURE_INSPIRED (P2-D0 §9 values, themselves unfitted);
25 = PURE_SENSITIVITY. **None is EMPIRICALLY_CALIBRATED** (needs realized fills). 10 bps is not "realistic". They are
kept as bounded ASSUMED sensitivity scenarios (useful to bracket quotes superseded inside a sampling interval,
replenishment and impact, which the walk cannot see); no value changed, so v2 only relabels.

## 9. Scenarios 2.0.0 (`scenarios_v2.json`)

| | EXEC-IDEALIZED | EXEC-BASE | EXEC-STRESS |
|---|---|---|---|
| purpose | lower-bound reference, never realistic | primary future scenario; unmeasured parts ASSUMED | sensitivity test, not a prediction |
| latency | 0 ms (ASSUMED) | 1 s (ASSUMED) | 5 s (ASSUMED) |
| reference price | decision mid; touch at T | decision mid; touch at T + 1 s | decision mid; touch at T + 5 s |
| spread | observed at T | observed at T + 1 s | observed at T + 5 s |
| fee | 10 bps taker ASSUMED | same | same |
| depth | not used (may "fill" above displayed depth) | walk at T + 1 s | walk at T + 5 s |
| slippage | 0 (ASSUMED) | walk (ESTIMATED) | walk + 10 bps (ASSUMED) |
| stale | X1-STALE-POLICY (POLICY) | same + depth rules | same |
| refusal | book INVALID → UNAVAILABLE | + depth INVALID / insufficient → UNAVAILABLE, no fallback | as BASE |
| total-cost provenance | ASSUMED | ASSUMED | ASSUMED |

v2 arithmetic is identical to v1 (tested leaf by leaf); only versions, contract hash and estimate ids differ.

## 10. Keeping uncertainty visible (`result_schema_v2.json`, `scenario_result.py`)

`tsb.p2x.scenario_set_result`: gross (decision mid → decision mid, DERIVED) plus, for each of the three scenarios,
net return, both legs' spread / fee / slippage / interaction / total cost and latency drift as Quantities with
provenance, cost provenance, data-quality state and coverage (AVAILABLE / REFUSED + reasons), and a
`component_provenance` matrix. A record with a top-level net / price / cost, a missing scenario or a non-null
UNAVAILABLE is refused.

## 11. P2-C ↔ P2-X contract closure (`p2c_join_v2.json`, `join.py`)

| Gap | Home | Resolution |
|---|---|---|
| F1 no `instrument_id` in P2-C rows | canonical instrument identity | adapter derives `binance_spot_instrument(symbol)`; P2-C frozen rows unchanged |
| F2 no P2-C row reference | execution request | `p2c_row_ref` {dataset logical hash, feature set id / version / registry SHA, row_id} on every request and joined record |
| F3 dataset identity names differ | manifest metadata | `dataset_sha256 ≡ dataset_json_sha256`, same dataset id, equal per-day seal SHA, else refused |
| F4 no per-field knowledge time | execution result | `leg_field_knowledge_time` (STATIC / DECISION / EXECUTION / UNAVAILABLE_BY_DESIGN / REFERENCE); joined record splits decision vs label side; unmapped field refused |
| F5 tier semantics | research dataset + execution result | request `decision_epoch_tier` (P2-C, known at T); leg tier → `label_side.execution_record_tier` |
| F6 exit definitions differ | execution request + manifest | `exit_definition` per request; `x1.*` vs P2-C `exe.*` declared distinct; mixing refused without a predeclared mapping |

Canonical identity (crypto / Binance spot only): asset_class, venue, product, instrument_id, symbol, base / quote /
settlement currency, calendar `crypto-24x7-utc` (UTC, continuous sessions).

## 12. Join determinism on real data (P2-D1 dataset `10cbae45…`)

The adapter verified the P2-C manifest logical hash and the features-file SHA, read only key / PIT columns plus
`liq.spread_bps` and `dq.book_age_s` (same-state check), never opened `labels.jsonl.gz`, and kept no value of W3
rows.

| Check | Result |
|---|---|
| join key | (instrument_id, decision_time_ms) |
| P2-C rows / unique row ids / duplicate keys | 5,187 / 5,187 / 0 |
| unmatched | 152, all `decision_time_inside_w3_refused` (2026-10-04 14:36:30–15:21:30Z, 4 × 38) |
| matched keys / joined records | 5,035 / 30,210 (3 scenarios × 2 sides) |
| ambiguous | 0 (keys and estimates per key / scenario / side) |
| PIT violations | 0 |
| reverse (P2-X-native universe vs P2-C) | 0 / 0 |
| tier | P2-C tier = P2-X epoch tier at T 5,035 / 5,035; execution record tier never different |
| same-state | spread equal 5,035, book age equal 5,035 |
| fill coverage | IDEALIZED, STRESS 5,035 / 5,035; BASE 5,034 (1 depth not observing, both sides) |
| determinism | sources A (backups) and B (live sealed files): identical logical hash and bytes (section 18) |

## 13. PAPER-R1 reconciliation and actual-fill path (design only)

`reconciliation_design_v2.json`: per Paper trade (a) Paper assumed fill (ASSUMED), (b) P2-X references under the
three scenarios at the Paper `event_time_ms` with obs ids, (c) a future real fill (UNAVAILABLE). Joins via
candidate_id → signal_id → tracker events and an as-of market join with the host clock offset. The actual-fill path
lists the fields needed to move toward MEASURED: client order id and timestamps (with clock offset), request sent,
exchange order id, transactTime / ack, status transitions, fills (trade id, price, qty, commission and asset,
isMaker), executed / cumulative quote qty, partial fills, rejection reasons, collector obs ids at send and ack. No
live trading, no test orders, no credentials; any implementation needs separate owner authorization.

## 14. Economic success principle (no thresholds, nothing computed)

Gross > 0 alone is never success. A future evaluation reports gross, the three nets, cost-to-gross ratio per
scenario, turnover sensitivity and execution coverage / refusal rate per scenario; a success claim must cite the
BASE and STRESS nets with coverage (`validate_evaluation_report`). IDEALIZED alone never supports success. Criteria
are predeclared separately, never chosen on outcomes.

## 15. Tests

`test_execution_x1.py` (contracts v2 frozen and v1 / P2-D0 untouched; tamper and file-set refusal; v2 = v1
arithmetic, ids differ; fee validation and versioned substitution; honest classifications; scenario specs; three-net
result, refusal never zero, collapse refused; success principle; join closure, determinism, labels never needed,
identity fail-closed, W3 partition, unmapped field refused; calibration plan, percentiles, observer neutrality,
determinism and guards; two defect regressions). **Full suite: 130 / 130 passed** (109 X0 + 21 X1; 436 s, 499 MB
peak, envelope). Defect tests failed before the fixes and pass after.

## 16. Operations (read-only, before and after)

Collector `013c738f91b9` running / healthy, restarts 0, health HEALTHY, 0 active incidents (one DEGRADED
`universe_refresh_failed` on 2026-10-06 00:10–04:40Z, pre-existing and resolved before this work), monitor
INFO, durable lag 1,066 ms before / 0 ms after, `gaps_closed_total` 391 before and after (no gap during the work),
collector memory 331 MiB of 384 MiB both times, CPU 27–29 %; Paper B3 `2026-10-04|f|manual_resume|29573` before and
after; learner exited (7 weeks); walk-forward cron lines 0; `p2c/ledger` absent. Snapshots 07:06Z and 07:50Z.
Resources per run: section 18. No operation degraded; nothing was restarted, paused or changed.

## 17. Defects

| ID | Defect | Fix |
|---|---|---|
| D-X1-1 | `coverage.py` counted an unknown depth / book update-id order as `book_newer` (latent: real ids are always integers, so the X0 evidence is unaffected) | `seq_order()` returns `unknown`; regression test failed first, passes after |
| D-X1-2 | `test_execution.TestCoverageTool` was defined after the `__main__` guard (skipped when the file is run as a script; discovery unaffected) | guard moved to the end; AST regression test |

## 18. Evidence and hashes

Code commit for all evidence runs: `25146fd`. Sources: A = the two sealed-day backups, B = the live dataset's sealed
files for the same 802 paths (all byte-identical to A; the active 2026-10-06 manifest replaced by the sealed
snapshot from the 2026-10-05 backup, so no active-day file was read).

| Run | Logical hash | A = B | wall / CPU / peak RSS |
|---|---|---|---|
| calibration | `a2083f9f3f32fa4b2551c5b56965900166c2871b612401f9fa9e4f0b77270546` | byte-identical | 245 s / 245 s / 570 MB |
| join | `1b07e21fd5f90db8e227f014d6350940cc316bc19d038d398db9ee2af7b230e5` | byte-identical | 218 s / 219 s / 227 MB |
| PIT poison (A) | 10,224 compared, 0 differences | – | 199 s / 199 s / 193 MB |
| X0 rebuild (A, `6d5aadb`) | `f313ac70…61e8` = P2-X0 evidence | byte-identical to X0 evidence | 58 s / 57 s / 147 MB |

All runs under `systemd-run --user --scope CPUQuota=100% MemoryMax=2G`, `nice 15`, `ionice -c3`,
`prlimit --as=2 GiB`, at most two concurrently.

| v2 contract file | SHA-256 |
|---|---|
| calibration_plan_v2.json | `d02ad543cfca69b21cbbef11424e987debfff6c3492b37196442bd4a784a2195` |
| terminology_v2.json | `e12eb4c94488f77b17b1a2a3661be34c25c7987469787775a76a367717d56017` |
| fee_schedule_v2.json | `99cdac8567cdafe2f136947bdaa95a498628e0502024706b90cd99e83cf8f71f` |
| models_v2.json | `e134367dd586ea677f3c00a2cc890250a4f93ac6111d898a9032f1bb0161cb4e` |
| scenarios_v2.json | `526c7efdeaee647a5d8816e79f306fb799c671ba7f0a4b554c09ea90b4b38add` |
| result_schema_v2.json | `312e9e50afa33e8a539e539aed0f6c8e75c6310526cc84fc89e9c1316b5376ba` |
| p2c_join_v2.json | `96e662cb0e9c8dd0c2a51048731fe4e15d959ab0302d3900d58629c4ddc300b4` |
| reconciliation_design_v2.json | `ea2172622b95090209f2102141680a67bd8c2a811d636f4ddd7f57a6ae636516` |

v2 `FROZEN_SHA256SUMS.json`: `f20e22a5e79b2ab36caa180ca25d652e6e273c2ad72392ed860c2d7f72aa88d0`; v1 unchanged
`3c554702948867fa26d4bba95b922f5e1db5902e42b088d9cdc49fdceefeec2f`.

## 19. Limitations and open items

- 1.4 eligible days (8.4 h of 2026-10-04 + 2026-10-05), 39 symbols: structural calibration, not a statistical
  sample; tier statistics mix few symbols (T0 = 2).
- Fee, latency and every total cost remain ASSUMED; realized cost, impact and fill probability remain UNAVAILABLE
  until a separately authorized real-fill path exists.
- Tier-1 depth (60 s cadence) makes BASE / STRESS walks for Tier 1 ladder-shape estimates; a future collector or
  research version could only change this with owner approval.
- Two descriptive outputs (RTT by probe position, walk-slippage percentiles) were added to the calibration tool
  after the first run; no plan parameter changed.
