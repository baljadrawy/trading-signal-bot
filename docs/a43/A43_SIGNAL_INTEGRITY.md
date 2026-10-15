# A43 — Signal Integrity & Candidate Selection Engineering

## Scope and provenance

| Field | Value |
|---|---|
| Date | 2026-10-15 (UTC) |
| Running Paper source | `59297305`. Verified by sha256 of the running files: signal_engine `signal_logic.py`, `main.py`, `shared/macro_context.py`; analyzer `main.py`, `technical_analyzer.py`, `simple_entry.py`; tracker `main.py`, `regime.py`, `triple_barrier.py`, `entry_execution.py`, `risk_management.py`. **All match.** The analyzer image ships no `shared/strategy_math.py` (production uses `_calculate_levels`) |
| Base | A42 `675f7d1` (ancestry: `59297305` → `8f8464f` → `a282437` → `675f7d1`). A42 is **not merged** into any production branch. The production checkout `~/trading-signal-bot` is at `63da7d3` with local changes; images, not that checkout, are the running code |
| Branch | `feature/a43-signal-integrity` (worktree `~/tsb-a43-worktree`). Code commit `247f38f`. Local only: not pushed, merged or deployed |
| Data read (read-only) | `signals` identity, bracket and timestamps; `active_trades` admission rows (signal_id, opened_at, status); `analysis_results` counts; signal_engine evidence-v2 truncation events. **No P&L or outcome column**, no protected P2 data, no backtest, no prospective run, no budget |
| Test infrastructure | throwaway PostgreSQL 16.15 container (`721873c34ceb`, tmpfs, `127.0.0.1:55433`), removed afterwards. Before-trees: `~/tsb-cr1-worktree` (develop `f973cac`, clean, unchanged) and a temporary `da256f7` worktree (removed) |

---

## A43-A — Decision path and defect verification

### A.1 How one setup travels (file:line at `59297305`)

1. **Analyzer** (`analyzer/main.py:162-171`):
   - each scan re-analyses the symbol on all TFs from closed candles (`prepare_ohlcv`, close_time based);
   - it **upserts** `analysis_results` with `signal_generated = false` (line 168);
   - while EVIDENCE_V2_ENABLED (on in production), `analysis_data.pit` holds `candle_open/close_time_ms`, `candle_id` and `candidate_id` (`shared/evidence_v2.py:101,108`).
2. **Candidate query** (`signal_engine/main.py:144-153`):
   - selects rows with `signal_generated = false`, `analyzed_at` within **30 min** (line 147), and no open trade;
   - `ORDER BY symbol, score DESC LIMIT 200` (line 152).
3. **Selector** `find_best_signal_live` (`signal_logic.py:629-739`):
   - macro gate (fails closed: `macro_context.py:104`);
   - learned-gate read (`:642`, only when enabled; **disabled in production**);
   - open symbols (`:648`) and cooldown (`:650` → `_get_symbol_cooldown_set` `:323`);
   - per-row filters in order: setup → order book / spread present → `spread > MAX_SPREAD_PCT` (`:671`) → `stop_valid is False` → open symbol → cooldown → throttle;
   - volume lookup (`:711`);
   - `min(eligible, key=_fixed_candidate_key)` (`:726`), where the key is `(spread, −volume, symbol, timeframe)` (`:246-252`).
4. **Persist** `save_signal`: `signals` row + `signal.ready` in one transaction. Then a **separate** statement sets `signal_generated = true` for the symbol (`main.py:218`, `:228`).
5. **Paper** (telegram `sent_direct` → `telegram_sent`), then tracker `register_new_signals` (`trade_tracker/main.py:570-601`). It admits signals:
   - from the last **2 h** (`V2_ADMISSION_WINDOW_SQL`, `:156`);
   - `DISTINCT ON (symbol)`;
   - with no open trade on the symbol;
   - with no trade on (symbol, timeframe) opened within one candle interval of **now** (`:592`).

### A.2 Verified defects

| # | Defect | Evidence | Root cause |
|---|---|---|---|
| D1 | **Same-candle re-emission** | 4h: 167 setups emitted more than once (352 of 414 rows). 1d: 4 setups → 23 rows. 15m: 0. **Exact identity confirms it**: among rows carrying `candidate_id` (from id 15440), 4h has 29 rows for 17 candles, 12 repeats, max 3 per candle. A42's bracket proxy agrees with exact identity **with 0 mismatches either way** | The upsert resets `signal_generated` on every scan (step 1). The only re-emission guard is the 2 h wall-clock cooldown, shorter than a 4h/1d candle |
| D2 | **Duplicate execution of one setup** | **4 setups traded twice** (ADA, NEAR, ORCA, POL; all 4h): 4 of 52 fixed-policy 4h trades. 1d: 0. 15m: 0 | The tracker guard (`:592`) is anchored to the previous `opened_at`, not to the candle. All 4 second opens happened **4h00m–4h01m** after the first, as soon as the window lapsed, while a same-candle signal was still inside its 2 h admission window |
| D3 | **Stale, superseded signals** | From exact candle timestamps: **15m 4/247 and 4h 3/29 signals were emitted after a newer candle had already closed** (4h max 244.6 min after close). The median 4h age is 123 min, which is the cooldown re-fire | Rows up to 30 min old are eligible, with no check against the candle's own age |
| D4 | **Cooldown fails open** | `signal_logic.py:339-341` returns `set()` on any exception. Demonstrated on the real code: with the cooldown query timing out, `find_best_signal_live` emits a signal (`test_production_cooldown_fails_open_on_db_error`) | Exception swallowed and converted into "no cooldown" |
| D5 | **NaN spread passes the filter** | `float('nan') > 0.15` is False, so a NaN spread is eligible. Demonstrated on real code. **Latent**: not observed in data | No finiteness check |
| D6 | **NaN volume makes selection order-dependent** | `−nan` in the key breaks tuple ordering, so `min` keeps whichever came first. Demonstrated on the real `_fixed_candidate_key`. **Latent** | `or 0.0` does not catch NaN |
| D7 | **Alphabetical truncation** | `ORDER BY symbol … LIMIT 200` keeps the first ~67 symbols. In the evidence-v2 window (2026-10-01 → 10-15): **0 truncated cycles**; eligible rows reached exactly 200 once. Now: 155 rows / 56 symbols. **Latent, at the boundary** | Order chosen for convenience, not for the objective |
| D8 | **Alphabetical and lexical tie-breaks** | Equal spread and volume → the earliest symbol wins (300/300 synthetic tie groups). Multi-TF rows of one symbol share spread and volume, so `'15m' < '1d' < '4h'` decides | The key ends in `(symbol, timeframe)` strings |

**Not defects, verified:**
- the legacy DB thresholds (`min_score` 3.0, `min_tf` 2), the BTC-crash check and the global / inter-signal cooldowns are **inert** in live mode (only the legacy `find_best_signal` calls them);
- selection is invariant to input row order, except under NaN (D6), because the key includes (symbol, timeframe), which is unique per row.

### A.3 Failure behaviour of each read today

| Read | Code | On error today | Effect |
|---|---|---|---|
| Candidate rows | `main.py:144` | raises → cycle aborted, backoff | safe (no signal) |
| Macro | `macro_context.py:104` | stale/unavailable → block | **fail-closed (correct)** |
| Learned gates (disabled) | `:642` | raises → abort | safe |
| Open positions | `:648` | raises → abort | safe, but by accident |
| Cooldown | `:323` | **`set()`** | **fail-open (D4)** |
| Volume | `:711` / `:782` | `None` → ranks last | degrades ranking only |
| Malformed spread string | `:671` | `float()` raises → whole cycle aborted | one bad row blocks all candidates |
| `signal_generated` update | `main.py:228` | after commit; failure → cycle error | the signal persists; the next guard is the cooldown (which fails open) |

---

## A43-B — Signal identity and idempotency

**Implementation:**
- **`shared/signal_identity.py`** (`a43-sid-v1`):
  - `SetupIdentity.key` = sha256 of (identity version, symbol, timeframe, **candle open ms**, trade type, direction, strategy version, setup policy).
  - Bracket prices are excluded from the key, so the same candle always means the same setup. They are hashed separately (`bracket_hash`), so a recomputed, different bracket is a **conflict**, not a new signal.
  - Timestamps fail closed: missing, malformed (bool, non-digit), misaligned to the TF grid, or close ≠ open + tf − 1.
  - `freshness`: admissible from candle end until the next candle closes; otherwise `superseded_by_newer_candle` or `decision_before_candle_close`.
- **`shared/idempotent_emission.py`** (`a43-ie-v1`): `INSERT … ON CONFLICT (setup_key) WHERE setup_key IS NOT NULL DO NOTHING RETURNING id`. `signal.ready` is published inside the **same** transaction, only when a row was created. The loser reports `duplicate` (same bracket) or `conflict`.
- **`docs/a43/proposed_011_signal_setup_key.sql`**: a nullable `setup_key` column + a partial unique index. It is **deliberately not in `database/migrations/`**, so `migrate.py` cannot apply it. Locking: metadata-only ADD COLUMN plus a millisecond index build on ~16k rows. No backfill: historical duplicates remain as evidence. Old images insert NULL and are unaffected, so image rollback stays safe.

**Concurrency model:** the unique index is the single primitive.
- **Concurrent workers:** they serialise on the index entry; exactly one commits a row and its event.
- **Restarts:** the key lives in the DB.
- **Delayed data:** `freshness` rejects superseded candles.
- **Version changes:** the strategy version is part of the key, so there are no cross-version collisions.

The 2 h cooldown is no longer the duplicate guard; it can remain as an independent symbol-level throttle.

**Requirements coverage:**
- (1)–(3) same candle once; later candles and distinct setups unaffected;
- (4) restart;
- (5) concurrency;
- (6) delayed data;
- (7) malformed timestamps;
- (8) idempotent persistence;
- (9) version separation;
- (10) production unchanged.

All are tested (A43-F).

**Integration requirements** (each needs owner approval):
- **I-1.** The analyzer writes `candle_open/close_time_ms` **unconditionally**, not only under EVIDENCE_V2_ENABLED. Otherwise every candidate fails identity, fail-closed.
- **I-2.** Apply migration 011 (fresh verified backup first).
- **I-3.** `save_signal` uses `insert_signal_once`.
- **I-4.** `find_best_signal_live` applies `freshness`.
- **I-5.** The tracker guard keys on `setup_key` (or candle) instead of `opened_at`. With I-3 the duplicate signal no longer exists, so this is defence in depth.

---

## A43-C — Failure safety

**`shared/dependency_safety.py`** (`a43-ds-v1`) classifies every read the selector makes:
- **SAFETY:** candidate rows, open positions, cooldown, emitted setups, learned gates when enabled, macro.
- **RANKING:** volume.
- **DIAGNOSTIC:** truncation measurement.

`guarded_read`:
- applies a per-attempt timeout, at most 5 attempts (default 2), and a total time budget;
- retries only `timeout` / `connection` errors; `query` errors are permanent;
- never raises for a dependency failure; returns a classified outcome.

`cycle_gate`: any failed **SAFETY** read means **no new exposure this cycle**, with the explicit reason `safety_state_unverified:<deps>`. A RANKING failure degrades ranking and records it; a DIAGNOSTIC failure is ignored. Events are compact and versioned.

**What it does not do:**
- it is not a blanket fail-closed rule (volume and diagnostics do not block);
- it does not loop unbounded;
- it does not restart or touch any other service.

**Integration requirement I-6:** route the cooldown and open-position reads through `guarded_read` + `cycle_gate` (owner approval).

---

## A43-D — Candidate selection integrity

**`shared/candidate_selection.py`** (`a43-cs-v1`):
- **Stated objective:** "minimise the execution-cost proxy (spread), then maximise liquidity". This is unchanged and **not** claimed to be economically predictive. The legacy score is not used.
- `eligibility_reasons`: production order, with all reasons kept; `reasons[0]` = the production decision.
- **Rankers:**
  - `production_parity`: the exact `_fixed_candidate_key`, including the NaN quirk;
  - `execution_quality_v2` (**experimental**): finite non-negative spread; valid liquidity before missing (NaN, None or negative → missing); then liquidity descending; then a sha256 tie-break of the candidate identity. No alphabetical or lexical-TF preference.
- `bounded_universe`: considers every fresh row up to a cap (default 2000, O(n log n)). Above the cap it drops by hash order, never alphabetically, and reports each dropped row.
- `production_query_window` reproduces the SQL window, for comparison.

**The 200-row limit:**
- **Deterministic:** the same data gives the same cut.
- **Biased:** it is alphabetical. With 361 rows, only symbols < `S067USDT` survive, and a best-spread `ZZZUSDT` is never seen by production but is selected by the bounded universe.
- **Currently latent:** 0 truncated cycles in the recorded window.

**Stability:**
- Under row order: invariant, except NaN (D6), for both rankers (10 shuffles × 2).
- Under query-plan changes: the in-database order matters only through the LIMIT cut, and that order is fully specified, so the only exposure is D7.
- Ties: production is alphabetical; v2 picks the alphabetically first in 0.15–0.35 of 4-way ties (≈ 1/4), and spreads TF choices across 15m/1d/4h.

**Integration requirements:**
- **I-7:** replace the SQL `ORDER BY symbol … LIMIT 200` with `bounded_universe` (no behaviour change below 200 rows).
- **I-8:** adopt `reject_non_finite_spread` and NaN-safe liquidity. These change eligibility only for invalid inputs.
- **I-9:** switching the ranker to v2 changes which candidate wins ties, i.e. which signals are emitted. That is a **strategy change**: it needs scientific registration, not just an engineering approval.

---

## A43-E — Signal diagnostics

**`shared/candidate_diagnostics.py`:** schema `tsb.a43.candidate_diag` v1 with **30 whitelisted fields**:
- setup key, identity error, strategy version, symbol, TF, candle open, setup type;
- eligibility and reasons;
- spread and liquidity;
- bracket; risk and T1 %; cost and cost/R; net path payoffs; ATR normalisation; quality flags;
- duplicate flag, age in bars, freshness;
- rank, ranker, selected flag, selection reason;
- correlated-exposure context.

**Serialization:**
- canonical one-line JSON with sorted keys, `allow_nan=False`, under 2 KB;
- deterministic bytes; a validator rejects unknown or missing fields, and inconsistent eligibility;
- nothing from config, env or the order book except the spread, so no secrets.

**Not connected to the evidence stream.** Shadow recording remains unapproved (integration I-10).

---

## A43-F — Integration and regression evidence

| Environment | Tree | Passed | Failed | Skipped |
|---|---|---|---|---|
| Default (no DSNs) | A42 `675f7d1` | 786 | 0 | 747 |
| Default (no DSNs) | **A43 `247f38f`** | **816** | **0** | 752 (747 + 5 new DSN-gated) |
| Full: 5 DSNs on a throwaway PG + `P1_BEFORE_TREE`=develop `f973cac` | base `59297305` | 1494 | 1 | 3 |
| Full (same) | **A43 `247f38f`** | **1564** | 1 | 3 |
| `test_p1fix_evidence_reliability.py` with `P1_BEFORE_TREE`=pre-fix `da256f7` | A43 | **18** | 0 | 0 |

**Skip analysis:**
- 696 skips need `P1_BEFORE_TREE`, and 47 need the DB DSNs. **Both are now executed safely.**
- The remaining **3 skips** run only inside the production telegram image ("main.py is not the Telegram service"). This is a documented blocker: running them would require executing inside a protected service container, which is not done.

**The single failure** (`test_more_than_200_expired_no_starvation_bounded_and_dedup`):
- It is **identical on base `59297305`**, so it is pre-existing.
- It is an environment mapping issue: the test reuses `P1_BEFORE_TREE` as the *pre-fix P1* tree (it needs `V2_EXPIRED_SQL`), while the rest of the suite wants develop `f973cac`.
- With its intended tree, it passes 18/18. **No test was weakened.**

The only test edit is that A42's isolation test now excludes the declared A43 experimental modules; the A43 isolation test checks them by import pattern.

**Parity:**
- The real `find_best_signal_live`, with fake DB reads and volumes, and `select(production_parity)` agree on **300/300** random candidate sets: missing setups, invalid order books, spreads over the limit, stop rejections, open symbols, cooldown, missing volumes, multi-TF.
- The develop before/after decision-parity suite (600 cases) passes.
- Production code is unchanged: the diff from `59297305` adds only new files plus the A42 test edit.

**A43 tests (35):** `test_a43_signal_integrity.py` 30, and `test_a43_db_idempotency.py` 5 (real PostgreSQL 16.15: migration applied twice; old-image inserts; duplicate, conflict and version; a **12-connection race → exactly 1 signal + 1 `signal.ready`**; winner rollback, then a later create; restart).

| Scenario | Test |
|---|---|
| 1, 2 Same 4h / 1d candle | `test_same_candle_evaluated_repeatedly[4h/1d]` (72 h of 60 s cycles: production re-emits; A43 once per candle, never superseded); `test_15m_has_no_repeat…` |
| 3 New candle, same bracket | `test_new_candle_with_identical_bracket_is_a_new_setup` |
| 4 Distinct setups on one candle | `test_distinct_setups_on_one_candle_do_not_block_each_other` |
| 5 Restart | `test_restart_before_reevaluation…`, DB `test_restart_and_winner_rollback` |
| 6 Concurrent workers | `test_concurrent_selection_workers_claim_once`, DB `test_concurrent_workers…` |
| 7 Cooldown timeout | `test_production_cooldown_fails_open_on_db_error` (current), `test_guarded_reads_block…` (A43) |
| 8 Open-position timeout | `test_production_open_position_error_aborts_cycle`, `test_guarded_reads_block…` |
| 9 Missing timestamp | `test_missing_or_malformed_candle_timestamp_fails_closed` (6 cases) |
| 10 Stale data | `test_stale_market_data_and_the_observed_244_minute_case` |
| 11, 15 > 200 rows; best beyond 200 | `test_universe_larger_than_200_truncates_alphabetically_in_production` |
| 12 Reordered inputs | `test_selection_is_invariant_to_input_order` |
| 13 Equal spread and liquidity | `test_equal_spread_and_liquidity_ties` |
| 14 Invalid liquidity | `test_invalid_or_missing_liquidity` (+ the D6 production demonstration); `test_nan_spread_passes_production_filter` |
| 16 Duplicate persistence | `test_duplicate_persistence_attempt_and_bracket_conflict`, DB `test_duplicate_and_conflict…` |
| 17 Correlated exposure | `test_diagnostic_record_serialization_and_exposure_context` |
| 18 Diagnostic serialization | same |
| 19 Strategy-version change | `test_strategy_version_change_creates_a_new_identity`, DB version case |
| 20 Live decision-path parity | `test_live_decision_path_parity` (300 sets) + the before/after suite |

These synthetic tests demonstrate engineering properties only, **not profitability**.

---

## A43-G — Next development decision

### **READY FOR SEPARATE INTEGRATION APPROVAL**, for the integrity subset only

**Ready** (engineering-complete, tested, behaviour-preserving for valid inputs):

| Item | Behaviour change | Approvals needed |
|---|---|---|
| I-1 Unconditional candle timestamps (analyzer) | none to decisions | code review + analyzer deployment (Class B) |
| I-2 Migration 011 | none (NULL-compatible) | migration approval + fresh verified backup |
| I-3, I-4 Idempotent `save_signal` + freshness | **removes** same-candle re-emissions and superseded signals (D1–D3) | signal_engine deployment (Class B) |
| I-5 Tracker candle-keyed guard | removes D2 even without I-3 | tracker deployment; **coordinate with the pending A38** (same file) |
| I-6 Guarded cooldown / open-position reads | blocks new exposure while safety state is unknown (D4) | signal_engine deployment |
| I-7, I-8 Bounded universe + invalid-value rejection | none below 200 rows; affects only invalid rows | signal_engine deployment |

**Scientific note:** I-3 to I-8 change **signal counts** (fewer duplicates and stale signals). The Paper stream before and after integration must be declared as **separate windows**, never pooled. Any active or planned protocol on this stream needs that declaration. The scientific HOLDs are unaffected.

**Experimental (not ready; strategy change):**
- I-9, the `execution_quality_v2` ranker;
- I-10, diagnostic shadow recording;
- the A42 C1–C3 candidates.

**Not claimed:**
- The duplicate issue is **not resolved in production**: nothing is wired or deployed.
- No improvement in returns is claimed. The expected effect is integrity: one signal per setup, no superseded entries, no unverified-state exposure, and no alphabetical bias.
