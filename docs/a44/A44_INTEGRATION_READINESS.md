# A44 — A38/A43 Integration Readiness & Strategy Continuation

## Scope

| Field | Value |
|---|---|
| Date | 2026-10-15 (UTC) |
| Production (verified read-only) | Paper images `p1d-59297305` (signal_engine `80096a98`, analyzer `b9b13d95`, tracker `698d3173`, telegram `e5f3096b`), schema **9**, Collector `p2f-160-1bfb5f6` (1.6.0). **Untouched** |
| Inputs, verified | A38 `fix/a38-paper-execution-integrity` @ `fb1d40e` (contains `2855a9a`, `d869ddc`). **Correction:** `98482f4` is the A38 *report* commit on `feature/mi-am4a-stage-b-prep-20261011`, not part of the A38 code branch. A42 @ `675f7d1`, A43 @ `7fd18fe`. All three merge-base at `59297305`; all unchanged and clean afterwards |
| Integration branch | `feature/a44-integration` (worktree `~/tsb-a44-worktree`): `fb1d40e` → merge `d200c93` (A43 + A42) → `01681fb` (wiring + migration 011) → `b8078d3` (tests + pipeline) → `2a40fff` (parity) → `eb68e42` (strict identity). Local only: not pushed, merged, built or deployed |
| Test infrastructure | throwaway PostgreSQL 16.15 (`721873c34ceb`, tmpfs, 127.0.0.1), removed afterwards; temporary detached tree `da256f7` (removed) |

---

## A44-A — Integration architecture

### A.1 Dependency map (integrated tree, file:line)

1. **Analyzer.**
   - Closed candles via `prepare_ohlcv` (close_time based).
   - In enforce mode, `technical_analyzer.py:55` adds a validated `candle_identity` block, or `candle_identity_error`.
   - `candle_bounds` (`shared/signal_identity.py:128`) **reuses** `evidence_v2.candle_pit`'s derivation and adds fail-closed validation: TF grid alignment, close = open + tf − 1. That keeps one derivation, with two consumers.
2. **Candidate retrieval** (`signal_engine/main.py`): unchanged (30 min freshness of rows, `ORDER BY symbol … LIMIT 200`).
3. **Identity and freshness.** `SetupIdentity.key` = (identity version, symbol, TF, candle open, setup type, direction, strategy version, setup policy). `freshness_at` (`signal_identity.py:186`) is the single freshness rule, used by both the engine and the tracker.
4. **Eligibility and failure safety.** `_integrity_state` (`signal_logic.py:360`) reads learned gates, open positions, cooldown and already-emitted setup keys through `guarded_read`. `cycle_gate` means no signal if any of them is unverified. The per-candidate integrity check (`:782`) runs **after** the unchanged production filters.
5. **Ranking:** unchanged, `min(eligible, key=self._fixed_candidate_key)` (`:827`).
6. **Persistence and publication.**
   - `_INSERT_ONCE_SQL` (`:254`): `ON CONFLICT (setup_key) DO NOTHING`.
   - `signal.ready` is enqueued in the same transaction only when a row was created; the loser reports duplicate vs conflict (`:968`).
   - `main.py:230` records `duplicate_setup_suppressed`.
7. **Tracker admission.** `integrity_admission_refusal` (`trade_tracker/main.py:670`, called at `:745`) refuses a signal whose candle has been superseded, or that has no stored identity. It goes through the existing entry-reject terminal path (`telegram_sent=false`).
8. **A38 durable entry orders and outbox:**
   - `_record_entry_order` (`:562`);
   - `reconcile_delivery_events` (`:629`): defer is not an attempt; genuine dead letters are alerted;
   - economic label (`:1237`);
   - `observed_price_v0` remains the default; `resting_limit_v1` is untouched.

   All unchanged.
9. **Telegram:** A38's `handle_candidate_event` (`telegram/main.py:248`), unchanged. Idempotent per signal; one signal per setup now means one notification per setup.
10. **Schema:** `001…009` (production) → `010_a38_execution_integrity.sql` → `011_a44_signal_setup_key.sql`. `REQUIRED_SCHEMA_VERSION = 11` (an "at least" check).

### A.2 Conflicts between A38 and A43

- **Git:** none. A43 added only new files; the merge was clean.
- **Semantic** (resolved, each tested):

| Issue | Resolution |
|---|---|
| Two insert implementations (A43 `idempotent_emission` vs the real `save_signal`) | A43 helper and proposal **removed**; `save_signal` is the only insert |
| A43 tracker guard (I-5) vs A38 admission | Uniqueness lives at the signal level (one setup → one signal → `active_trades.signal_id` unique). The tracker gains only a **freshness** check, reusing A38's terminal path, so no new outbox state |
| Identity dependent on optional instrumentation (`pit`) | The engine requires the analyzer's `candle_identity` (`allow_pit_fallback=False`) |
| A38 schema guard 10 vs A44 column | One guard, `REQUIRED_SCHEMA_VERSION = 11` |
| Refused superseded signals vs A38 reconciliation | Acked `terminal:ENTRY_REJECTED`. The outcome code is coarse; the reason is in the logs and in evidence `admission.decision` |

### A.3 Compatibility matrix

| Schema | Code | Result | Evidence |
|---|---|---|---|
| 9 | 59297305 (production) | runs | production |
| 10 | 59297305 | runs (pre-A38 tracker semantics) | `test_a39_review` mixed-version, A38 tree, BEFORE=59297305: 10/10 |
| 10 | A38 `fb1d40e` | runs | A38 full suite 1537 passed |
| 10 | integrated | **refuses to start** (schema 10 < 11) | by design: `require_schema` (`shared/schema.py`) |
| 11 | integrated `eb68e42`, mode off | runs; pre-A44 decisions | full suite 1627 passed, incl. develop before/after decision parity (600) and the 300-set live parity |
| 11 | integrated, mode enforce | runs | `test_a44_integration_db` 14/14, `test_a44_selection_pipeline` 7/7 |
| 11 | A38 `fb1d40e` | runs; inserts `setup_key` NULL | `test_a44_migration_db::test_old_and_a38_code…`: its own process with its own `shared/` |
| 11 | 59297305 | runs; inserts NULL | same test |
| Rollback integrated → A38 → 59297305 with schema 11 kept | keyed and unkeyed rows coexist; no dead letters | same test (2 trades opened, keyed row intact, 0 dead) |

**Limit of the evidence:** this is source-level, run with each tree's own Python code. **No container images were built or run** (no build was authorized). Image-level proof is the first step of a deployment approval.

---

## A44-B — Integrated engineering candidate

One flag, **`SIGNAL_INTEGRITY_MODE`**:
- `off` is the default: pre-A44 decisions, SQL text and analysis output.
- `enforce` turns on the A43 rules.
- An unknown value makes the analyzer, signal_engine and trade_tracker **refuse to start**.

Other flags, unchanged:
- `PAPER_ENTRY_FILL_MODEL=observed_price_v0`, the only active model;
- `resting_limit_v1` remains inactive;
- experimental rankers are not selectable by the engine (asserted);
- diagnostics recording is not wired.

| Kept from A38 | Kept from A43, now wired (enforce) | Still experimental, unwired |
|---|---|---|
| durable `paper_entry_orders`; defer ≠ attempt; alerted genuine dead letters; economic labels; fill-model guard | candle identity (analyzer); fail-closed safety reads; freshness; insert-once; tracker superseded-refusal | ranking v2 and `cost_per_risk_v1`; staged pipeline; diagnostics record; A42 signal quality, C1–C3; counterfactual replay |

The diff from `59297305` (code, schema, tests) is 21 files: +2414 / −93.

---

## A44-C — Migration and compatibility evidence (`tests/test_a44_migration_db.py`, 4/4)

- **9 → 10 → 11**:
  - uses a runner that mirrors `migrate.py`: one transaction per file, the sha256 ledger, refusal on checksum mismatch. `migrate.py` itself is hard-wired to `docker exec postgres` (production) and was **not** run.
  - **20,002 seeded rows**: signals (including a deliberate duplicate pair), trades, results, outbox. The fingerprint of every schema-9 column was **identical** after 10 and after 11.
- **Re-run:** every migration is a no-op (`=`); the 011 body re-executes idempotently. A tampered checksum is refused.
- **Migration 011 itself:**
  - nullable `text`, no FK, partial unique index `WHERE setup_key IS NOT NULL`;
  - 0 rows backfilled; historical duplicates kept;
  - duration **13 ms** on 20,002 signals (production has ~16k).
- **Lock behaviour:** behind an open writer transaction, 011 fails after the 5 s `lock_timeout` (`LockNotAvailableError`) and rolls back atomically (no column, ledger still at 10), then succeeds once the writer ends.
- **Unique semantics:** NULLs never collide; a second identical key gets `UniqueViolationError`.
- **Rollback limitation:** none needed at the schema level. Old code ignores the column. Dropping it (`DROP INDEX; DROP COLUMN`) would lose only identities written by the integrated code.

---

## A44-D — End-to-end and regression evidence

### Exact counts

| Run (same throwaway cluster, same env) | A38 `fb1d40e` | A44 `eb68e42` |
|---|---|---|
| Full suite: 5 DSNs, `P1_BEFORE_TREE`=develop `f973cac`, A44 tree vars | **1537 passed / 1 failed / 3 skipped** | **1627 passed / 1 failed / 3 skipped** |
| `test_p1fix_evidence_reliability.py`, BEFORE = pre-fix `da256f7` | 18 / 0 / 0 | 18 / 0 / 0 |
| `test_a39_review.py` mixed-version, BEFORE = pre-A38 `59297305` | 10 / 0 / 0 | 10 / 0 / 0 |
| Default (no DSNs) | — | 838 / 0 / 793 |

**Difference:** +90 = A42 35 + A43 30 + A44 25 (14 integration, 4 migration, 7 pipeline).

**The 1 failure is identical on both trees:** `test_more_than_200_expired_no_starvation_bounded_and_dedup`. That suite needs its BEFORE tree to be the pre-fix `da256f7`, while the full suite needs develop, and it passes 18/18 with its own tree (the A43 finding).

**The 3 skips** run only inside the production telegram image (missing proof: image-level, under deployment approval).

**No assertion was weakened.** Two isolation tests were rewritten for the new design: wired modules must be imported by exactly the five production files, and experimental modules by none.

### Scenarios covered (`tests/test_a44_integration_db.py`, enforce, real PostgreSQL 16.15)

| Requirement | Test |
|---|---|
| Same-candle repeated scans, **after cooldown expiry** | `test_same_candle_repeated_scans…` (cooldown, then `duplicate_setup`) |
| New candle and distinct setups | `test_new_candle_and_distinct_setups…` (4 keys, 4 signals) |
| Concurrent workers + restart | `test_concurrent_workers_and_restart…` (1 created, 1 duplicate, restarted engine rejects) |
| Bracket conflict on one candle | `test_conflicting_bracket…` |
| Missing / malformed / evidence-only / early / stale identity | `test_stale_and_unidentified…` (5 reasons) |
| DB timeout on cooldown, open positions or emitted keys | `test_database_failure_on_a_safety_read…` ×3 (2 bounded attempts, no signal, then recovery) |
| Event-publication failure → rollback → retry once | `test_publication_failure_rolls_back…` |
| Lifecycle: delivery replay, concurrent admission, durable order, T1 partial, break-even, economic label | `test_lifecycle_open_partial_break_even_and_accounting` |
| Tracker refuses a superseded setup (the ADA/NEAR/ORCA/POL case) | `test_tracker_refuses_a_setup_superseded…` → `terminal:ENTRY_REJECTED`, no entry order |
| Mixed cutover: old-engine signal, new tracker | `test_tracker_refuses_signals_without_setup_identity…` |
| Real analyzer output (fake Binance) → engine | `test_real_analyzer_output_flows…` (momentum; exact candle; open candle dropped) |
| Off-mode parity | `test_off_mode_keeps_the_pre_a44_behaviour` |

**Strategy decision parity:**
- develop before/after (600 cases);
- live selector vs the parity selector, 300 sets;
- **enforce vs off on the real selector, 200 sets: identical picks** whenever all candidates are fresh and new (integrity removes, it never re-ranks).

**Not proven:** container images; the production config combined with real Binance data; production DB timings under load.

---

## A44-E — Candidate-ranking research specification (unexecuted, no alpha, no registration)

**Interface (built, experimental).** `run_pipeline`:
- stages: eligibility → risk constraints → execution feasibility → **one** named ranker → top-1 → `explain()`, with one stage record per candidate;
- `ACTIVE_RANKER = production_parity`;
- alternatives are single-criterion and lexicographic with a hash tie-break, so they have **no weights to tune**:
  - `execution_quality_v2` (A43);
  - `cost_per_risk_v1`: the lowest (20 bps + spread) / stop distance, the A42-B cost burden.

**Key property** (proven on 500 synthetic sets): with stages 1–3 fixed, every ranker selects a candidate in **exactly the same cycles**. A ranking change cannot change signal frequency; it only changes *which* setup takes the slot. Any frequency change must come from eligibility, and is evaluated as a gate (A42 C1), not as ranking.

| Element | Specification |
|---|---|
| Universe | every cycle with **≥ 2 ranked candidates** after stages 1–3, on the enforce-mode stream (one signal per setup, fresh). In synthetic sets this is 101 of 259 selecting cycles; the real rate must be measured from evidence before any power claim |
| Baseline | `production_parity` (live) |
| Alternative | `cost_per_risk_v1`, fixed: 20 bps + observed spread, stop distance from the frozen bracket. **One** alternative (`execution_quality_v2` differs in only ~4 % of contested synthetic cycles, too small to test) |
| Estimand | mean over contested cycles of [net return of the alternative's pick − net return of the baseline's pick], each priced by the same frozen exit rules, 20 bps baseline cost, and operational slippage reported separately |
| Rejected / unfilled | the baseline pick has a real Paper outcome. The alternative's pick usually does not, so it needs a forward counterfactual (`counterfactual_barrier`, `a42-cf-bar-v1`). An unfilled counterfactual counts as 0 return, never dropped; rejection at entry follows the frozen `decide_long_entry` |
| Counterfactual status | engineering diagnostic only. **Not verified economic evidence** until its bar-vs-tick approximation is calibrated against tracker polls on the same trades (the unbiasedness of paired differences must be shown first) |
| Dependence | simultaneous candidates share BTC beta; the paired difference within a cycle removes the common market move. Cycles overlap through open positions, so inference uses daily aggregation with a HAC/block variance (A30/A32 machinery) |
| Capacity | 2 slots; a different pick changes later availability. The primary estimand is per contested cycle (local); portfolio effects are secondary and descriptive only |
| Regime sensitivity | report by macro state and TF; no regime selection after the fact |
| Multiple testing | one admission at α = 1/240 in the FWER ledger; no additional alternatives without a new admission |
| Provenance | setup key, candle identity, ranker version, stage records (`explain()`), and code/config hashes per cycle |
| Leakage | ranker inputs are spread and bracket at decision time only; no outcome, no learned field; the hash tie-break comes from the identity only |
| Power | unknown until the real contested-cycle rate is measured. With A31's finding (forward mean differences of plausible size are undetectable within 365 days at α 1/240), the **expected verdict is underpowered**. Admission is not recommended until a pre-registered power calculation on the measured rate shows MDE ≤ a plausible effect |
| What would distinguish "better ranking" from "frequency change" | identical selection cycles (guaranteed by construction and asserted), a positive paired difference within contested cycles, stability across macro states, and no deterioration in non-contested cycles (where both rankers must agree exactly) |
| Prospective requirements | ≤ 365 days, final look only, enforce-mode stream declared as its own window, counterfactual calibration completed first |

---

## A44-F — Deployment readiness (documentation only; nothing executed)

**Prerequisites:**
- a **fresh, verified recovery point** taken in the deployment window: dump + restore + table hashes (A41 method), not mere file existence;
- image archives of the running images;
- owner approval for each step;
- the A38 deployment and A44 decided together, or A38 first (schema 10) and A44 later (schema 11). The two migrations are independent and ordered.

**Sequence** (each a Class B single-service step with identity capture, 2 fresh health checks, PAPER_HALTED/B3 gates):
1. Build the candidate images from `eb68e42` (a separate approval), and verify image-level parity with the 3 telegram-image-only tests.
2. Recovery point (above).
3. `migrate.py`: 010 then 011. The old images keep running (matrix rows "10/11 + 59297305").
4. tracker → telegram → signal_engine → analyzer on the integrated images, **all with `SIGNAL_INTEGRITY_MODE=off`**. Behaviour equals A38. Smoke: one candidate ready → delivered → opened or terminal.
5. **Enforce activation, a declared Paper-window boundary:**
   - set `enforce` on the analyzer first, wait one 4h candle (identity present on rows);
   - then signal_engine;
   - then the tracker, once no unkeyed signal is younger than 2 h. Otherwise in-flight legacy signals are refused (fail-closed, tested).
6. **Health checks:**
   - no `safety_state_unverified` storms;
   - `duplicate_setup_suppressed` rare;
   - signals per setup = 1 (`count(*) = count(DISTINCT setup_key)`);
   - dead letters only genuine.

**Rollback:**
- **Flag:** `off`, a restart only.
- **Images:** integrated → A38 → 59297305, schema 11 kept (tested source-level).
- **No schema rollback is needed.**

**Rollback triggers:**
- any unexpected identity change;
- dead letters rising;
- zero signals for more than one 4h candle in enforce;
- any duplicate key error surfacing in logs;
- a failed gate. Per CLAUDE.md, stop and return to the owner.

**Evidence separation:** pre-deployment Paper, A38-off, and enforce are three windows. Never pool them; each change is declared.

**Separate owner approvals:**
1. image build;
2. recovery point;
3. migrations 010/011;
4. each service recreate;
5. the enforce activation (a scientific window boundary);
6. later, any ranker or gate experiment (an alpha admission).

---

## A44-G — Recommendation

### **READY FOR SEPARATE DEPLOYMENT APPROVAL**, for the integrated engineering candidate `eb68e42` with `SIGNAL_INTEGRITY_MODE=off` by default. Enforce activation is a separate, declared step.

**Completed and verified:**
- A38 and A43 coexist without loss of A38 behaviour (A38's own suites pass unchanged on the integrated tree).
- Identity and duplicate prevention work end to end in isolation.
- Migrations 9 → 10 → 11 are tested, including rollback-compatibility.
- Accounting is unchanged and exercised.
- Production ranking parity holds (off and enforce).
- Experimental ranking is not reachable.
- Production is untouched; HOLDs are unchanged; no budget spent.

**Unverified assumptions:**
- image-level behaviour (no images built);
- the 3 telegram-image-only tests;
- production config and data interaction;
- production DB lock contention at migration time (lock-timeout fail-fast is proven);
- real contested-cycle rates for the ranking spec.

**Not claimed:** any profitability improvement. The engineering result is integrity: one signal per setup, no superseded admissions, and no exposure on unverified state.
