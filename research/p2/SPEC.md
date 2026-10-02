# P2 canonical research dataset: specification (P2-A, contract `p2a-contract-v1`)

**Purpose:** data engineering and methodological correctness for historical and forward market intelligence.
This is not a profitability study. No win rate, profit factor, expectancy, ranking or feature/outcome association
is computed anywhere in P2-A.

- Code: `research/p2/contract.py` (constants, identities, schemas), `validate.py` (fail-closed validators),
  `extract.py` (W1/W2 extraction), `ds_coverage.py` (certified-candle coverage index).
- Tests: `tests/test_p2a_canonical.py`.

## 1. Governance boundary
| Window | Definition (authoritative decision time) | Status |
|---|---|---|
| W1 | `< 2026-06-01T00:00:00Z` | certified candles: ds-09284abbc6453ff59acd (through 2026-05-31) |
| W2 | `2026-06-01T00:00:00Z ≤ t < 2026-08-19T09:33:46Z` | market data incomplete; certified in P2-B |
| W3 | `≥ 2026-08-19T09:33:46Z` (freeze git `63da7d3`) | **SEALED.** It never enters canonical analytical data; see `research/governance/w3_holdout_guard.json` |

**Exclusion happens at extraction (in SQL).** A decision is included only if its decision time **and every linked
lifecycle event time** are strictly before the freeze. The linked events are the trade open, the trade exit,
every target fill, and the approval request and response.
- Any null or unknowable time is **quarantined**: counts and signal IDs only, no values.
- A trade without a result row has an unknown exit time, so whether its outcome lies in W3 cannot be determined.
  The whole decision is quarantined.
- Daily tables (`risk_management`, `macro_history`) keep only dates `< 2026-08-19`, because the freeze day
  straddles the boundary.

## 2. Authoritative timestamps per source
| Source table | Decision time | Event time | Trade / result time | Creation time | W3 rule used |
|---|---|---|---|---|---|
| signals | `signal_time` (DB insert wall clock) | — | — | `signal_time` | decision < freeze and all linked times < freeze |
| active_trades | via signal | `opened_at` (paper fill) | `opened_at` | — | via decision |
| trade_results | via signal | — | `exit_time` | — | via decision |
| trade_target_fills | via trade | `filled_at` | `filled_at` | — | via decision |
| approval_requests | via signal | `requested_at`, `responded_at` | — | `requested_at` | via decision |
| outbox_events | via aggregate | `available_at`, `processed_at` | — | `created_at` | all < freeze and aggregate belongs to an included decision |
| risk_management | — | `date` (end-of-day, last write wins) | — | — | date < 2026-08-19 |
| macro_history | — | `date` / `updated_at` (daily, last write wins) | — | — | date < 2026-08-19 and updated_at < freeze |
| analysis_results | — | `analyzed_at`, `decision_at` | — | — | both < freeze; latest state only, not decision history |
| risk_recovery_events | — | `epoch_started_at` (timestamptz) | — | — | all are W3 and excluded |

All naive timestamps are UTC: the PostgreSQL TimeZone and the containers are verified UTC.

## 3. Canonical entities (schemas in `contract.SCHEMAS`; column order is part of the contract)
- **decision:** one strategy decision (signal). Holds identity, window, decision time, strategy and decision
  source, planned geometry (STORED_SNAPSHOT), the inferred decision candle with ambiguity flag (INFERRED), and
  snapshot availability. `risk_context_pit` = MISSING (not collected before P1).
- **decision_market_context:** long format (decision_uid, namespace, feature_name, value_json) with provenance,
  `observed_at_ms`, `available_at_ms`, `pit_safe` and `feature_version`.
  - P2-A content is stored runtime snapshots only (`features_snapshot`, `score_details`, `macro_snapshot`,
    `signals.volume_usdt`).
  - Rebuilt features (P2-C) are added with `REBUILT_*` provenance and a new `feature_version`; they never overwrite
    stored values.
- **market_outcome:** what price did after the decision, independent of entry. **Empty in P2-A**
  (W1: AWAITING_P2D; W2: AWAITING_P2B, then P2D).
  - It has no columns shared with execution_outcome.
  - Its labels are always computed from certified candles and never from fills.
- **execution_outcome:** delivery, admission path, approval, entered or not, paper fill, fill latency, fill versus
  planned in basis points, NO_FILL status (NOT_COLLECTED before P1). `execution_provenance = PAPER_MODEL`.
- **trade_lifecycle** / **trade_target_fill:** entry through exit, as recorded by the paper tracker.
  - `pnl_basis = AS_STORED_BASIS_UNVERIFIED_PAPER_MODEL`.
  - Target fills are booked at the exact target price (`fill_price_basis`).
  - None of this is real exchange execution. `LIVE_EXECUTION` is reserved and never used.
- **risk_context:** per-day risk rows, **NOT_POINT_IN_TIME_SAFE** (end-of-day state). Point-in-time risk state
  exists only from P1 (`risk.state` / `admission.decision` evidence).
- **provenance:** source registry: backup set and checksum, ds-0928 manifest checksum, extraction code checksum,
  and per-source authoritative column and W3 rule.

## 4. Identity contract
- Historical: `decision_uid = "dec_" + sha256("tsb.p2.decision|v1|sig|<signal_id>|<symbol>|<timeframe>|<signal_time text as stored>")[:24]`.
  It does not depend on row order or the extraction run; verified by two independent restores and extractions.
- `decision_key = sig:<signal_id>`. Forward candidates without a signal row use `cand:<candidate_id>`.
- `candle_id = SYMBOL|timeframe|open_time_ms`, the same as P1 Evidence V2. Historical rows carry
  `inferred_candle_id`; `observed_candle_id` is filled only from P1 `identity` / `pit`.
- Trades: `active_trade_id`. Results: `trade_result_id`. Fills: `fill_id`. Signals have at most one trade and one
  result (unique indexes, verified).

## 5. Timestamp / point-in-time contract
| Field | Meaning |
|---|---|
| `event_time` | When the market or lifecycle fact happened (exchange candle close, fill, exit) |
| `observed_at` | When our process had the value in hand. Unknown for stored snapshots, so left empty rather than invented |
| `ingested_at` | When the research layer wrote it (manifest `created_utc`) |
| `decision_time` | `signals.signal_time` historically; Evidence V2 `event_time_ms` going forward |
| `candle_open_time` / `candle_close_time` | Binance kline; `close = open + tf − 1 ms`; only closed candles are usable |
| `available_at` | Earliest time the value could legitimately have been known to the strategy |

- **PIT join rule:** `available_at <= decision_time`. Matching calendar dates is never enough.
- Stored snapshots: `available_at = decision_time`, an upper bound, because they were computed at or before
  analysis.
- Macro snapshot: `available_at = decision_time − macro_age`.
- `macro_history` (daily, last write wins) is **never** used as point-in-time context.
- **Inferred decision candle:** the last tf candle with `close < signal_time`.
  - It is ambiguous when a tf boundary lies in `(signal_time − 30 min, signal_time]`, because the signal engine
    accepts analyses up to 30 minutes old. This holds for current code; for the W1 era it is an ASSUMPTION and
    is flagged.
  - 15m is always ambiguous.
  - Disambiguation (P2-C): `planned_entry` equals the close of the decision candle (current code), so it should be
    matched against certified candles.

## 6. Provenance contract
- **Values:** `OBSERVED`, `STORED_SNAPSHOT`, `REBUILT_CERTIFIED`, `REBUILT_UNCERTIFIED`, `INFERRED`, `APPROXIMATE`,
  `MISSING`, `NOT_POINT_IN_TIME_SAFE`.
- **Execution:** `PAPER_MODEL` (all history) versus `LIVE_EXECUTION` (reserved).
- **Missingness reasons:** `NOT_COLLECTED`, `NOT_APPLICABLE`, `CANNOT_RECONSTRUCT`, `AWAITING_P2B`, `AWAITING_P2C`,
  `AWAITING_P2D`.
- Every dataset manifest records: dataset ID, created UTC, code identity, source backup, freeze, window policy,
  rows, time range, symbols, timeframes, schema version, provenance counts, and file sha256 plus content sha256.

## 7. Validators and tests (fail closed; violations carry identities only, never values)
Each check below is covered by both a synthetic negative fixture and a run over the built dataset:
- W3 leakage in every time column, window label and risk date;
- window assignment;
- duplicate or non-deterministic identity;
- inferred candle not closed or misaligned, a wrong ambiguity flag, and inference not labelled INFERRED;
- a feature available after the decision, and a pit-safe feature without `available_at`;
- an outcome-like name in the feature layer;
- daily macro last-of-day values in context;
- execution used as a market label, or a non-paper execution provenance;
- missing required columns, which raise.

## 8. W2 reconstruction validation set (specification for P2-B/C; not executed in P2-A)
- **Reference:** W2 decisions with a stored `features_snapshot` (1,393 in dataset `p2a-4821…`), compared feature by
  feature with values rebuilt from P2-B certified candles, using the analyzer's own formulas and parameters at
  the decision's code version.
- **Deterministic sample:** all W2 decisions, or, if compute-bound, the ones whose `sha256(decision_uid)` ends in
  `0`–`7` (about 50%), stratified so every (timeframe × trade_type) cell keeps at least 30 decisions or all of
  them.
- **Timestamp matching:**
  1. Rebuild at the inferred candle.
  2. If the decision is ambiguous, also rebuild at the alternative candle.
  3. Choose the candle whose close equals `planned_entry` within 1e-9 relative tolerance. If neither or both
     match, mark it `UNRESOLVED`; never guess.
- **Tolerances:**
  - Absolute or relative 1e-6 for price-derived values (`dist_ema*`, `bb_pos`, `atr_pct`, `roc10`).
  - 1e-4 relative for recursive indicators (RSI, MACD, ADX, MFI, CCI, StochRSI, OBV), because they depend on the
    warm-up length. The rebuild must use exactly the analyzer's 200-bar window.
  - `volume_ratio`, `cmf20`: 1e-6 relative.
  - Book-derived values (`spread_pct`, `bid_ask_ratio`, `ob_score`) are **excluded**: they are CANNOT_RECONSTRUCT.
- **Missing data:** a decision with any gap or duplicate in its 200-bar window is `INSUFFICIENT_DATA`. It is
  excluded from pass/fail and counted.
- **Pass thresholds:**
  - At least 99.0% of compared (decision, feature) pairs within tolerance for every feature.
  - At least 98% of decisions resolved to a single candle.
  - 0 PIT violations.
  - On failure, P2-C feature reconstruction for W1 may not be trusted until the cause is explained.

## 9. P1 forward compatibility (no change to P1)
| P1 Evidence V2 / DB | Canonical |
|---|---|
| `candidate_id` (`cand_…`) | decision.candidate_id; `decision_key = cand:<id>` for candidates without a signal |
| `candle_id` (pit / identity) | decision.observed_candle_id (an OBSERVED anchor; no inference needed) |
| `signals.features_snapshot.identity` (code_sha, config_hash, weights_hash) | provenance plus decision attributes (P2-C adds columns under a new contract version) |
| `analysis_data.pit.*_ms` (candle open/close, klines_fetched, orderbook_fetched, analyzed) | context `observed_at_ms` / `available_at_ms` (OBSERVED) |
| `candidate.evaluated` (selected or rejected) | decision rows for rejected candidates (historically NOT_COLLECTED) |
| `signal.ready` → `delivery.*` → `entry.attempt` / `admission.decision` / `entry.expired` (NO_FILL) | execution_outcome (admission, no_fill_status) |
| `trade.opened` / `target_hit` / `closed` (active_trade_id, trade_result_id) | trade_lifecycle / trade_target_fill |
| `risk.state` / `admission.decision` risk snapshot | risk_context (point-in-time safe from P1 on) |

## 10. Backup classification
| Class | Content | Treatment |
|---|---|---|
| Irreplaceable | the P1-BG `trading_signals` dumps; Evidence V2 JSONL; future P2-E forward raw market data | backed up (P1-BG; P2-E to be decided) |
| Certified source | ds-0928 (and the P2-B extension) | read-only, manifest plus sha256 per file; re-verified (2,384 files, 0 mismatches) |
| Reproducible | the entire `p2/` store (raw, canonical, derived, manifests, quarantine) | **not** added to P1-BG; rebuilt from the backup set, ds-0928 and this code (determinism verified) |

## P2-B extension
See `MARKET_SPEC.md`: certified W2 spot candles (dataset `p2b-53de1a98c2792cd74206`), seam with ds-0928, W2
decision coverage and stored-snapshot parity.
