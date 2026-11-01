REVIEWER 1 (model: Fable 5.1) — SE-1 signal logic and behavioural parity

Scope checked: `git diff ea8ae4f 7ff582f` = six files (verified). The six files are byte-identical between 7ff582f and the feature-branch HEAD, and `signal_logic.py`, `config.py`, `evidence_v2.py`, `health.py`, `macro_context.py`, `database.py`, `signal_identity.py` are identical to ea8ae4f (cmp, independently verified). Tests were run in my scratch directory against `git archive` exports of both commits, with both interpreters (Python 3.12.3).

**A. Verdict: CONDITIONAL GO** (R1 scope). I found no path by which `FUNNEL_RECORDING=on`, `FUNNEL_MAX_RECORDS_PER_DAY=20000`, `SELECTION_POLICY` unset changes a candidate, signal, SQL statement text/order/transaction or downstream message relative to ea8ae4f. Conditions are non-blocking hygiene items.

**B. Findings**

R1-01 MEDIUM — A selection-changing path ships inside an observe-only release. `signal_engine/main.py:34-35,162-177`; `shared/selection_policy.py`. `rank_then_limit_v1` replaces the `LIMIT 200` query with a full read of the WHERE set plus Python ranking, reachable by env alone (`SELECTION_POLICY`, `SELECTION_VERSION`, `SELECTION_SCORE_KEY`). Fail-closed when undeclared and inert when unset (verified by the developer's tests and my runs). Impact: an R1.c selection boundary becomes an env edit away in production. Minimum action: the SE-1 Compose change and the version-boundary record must state the three `SELECTION_*` keys are absent/forbidden. Blocks: no.

R1-02 LOW — Hook calls in `main.py` have no call-site guard; safety rests on each hook's own try/except (`main.py:184-189,204-205,212-214,270-273,299-301,307-308`). `tap.health()` (`funnel_hooks.py:230-233,800-801`), `tap.note()` (999-1001) and `tap.start_decision()` (881-883) have no guard at all, though their bodies are trivial dict operations. Counterexample (my test): a raise injected into `FunnelService.health` leaves the DB trace identical but turns the cycle's heartbeat into `mark_failure` with backoff. Same pattern as the existing `_v2_truncation`/`_v2_cycle`. Minimum action: wrap the hook call groups in `try/except Exception` or document the reliance. Blocks: no.

R1-03 LOW — `from shared.funnel_hooks import SignalEngineTap` runs after `Database.connect`/`mark_started` (`main.py:123-126`); only the flag parsing refuses before I/O (`main.py:104-106`). An import failure of the overlay copy would crash after connecting. Minimum action: import before `Database.connect`. Blocks: no.

R1-04 LOW (evidence gap, closed by me) — The developer's 25-seed parity runs force `SIGNAL_INTEGRITY_MODE=off` (`tests/test_funnel_records.py:437`); the enforce labels (`duplicate_setup`, `freshness:*`, `identity:*`, `safety_state_unverified:*`) were covered only by a synthetic label table. I ran 25 enforce-mode seeds with duplicate, stale and identity-missing rows: trace/saved/heartbeat identical off vs on, every cycle `valid`, `unattributed=0`, all label families exercised. No defect.

R1-05 LOW — `mark_success` statement text is unchanged but its `$2::jsonb` bind value now carries `funnel` and different evidence_v2 queue gauges (`shared/health.py:32-41`; `main.py:273,301`). Documented in the README; not a decision input. Blocks: no.

R1-06 INFO — `test_strategy_ids_are_the_declared_family_ids` (`tests/test_funnel_records.py:68`) imports `shared/strategy_identity.py`, absent from 7ff582f; against the export it fails with ModuleNotFoundError. "151 passed" reproduces only with it deselected. Blocks: no.

**C. Claim verification**

- Candidate query, `LIMIT 200` and ordering byte-identical: VERIFIED. AST extraction: one `LIMIT 200` literal in each tree, sha256 `4d3cf4b5…` equal; `_ELIGIBLE_WHERE`, count, cut and both UPDATE literals unchanged. The truncation f-string changed form (`LIMIT 500` → `LIMIT {_TRUNCATION_LIST_ROWS}`) with identical rendered text.
- Zero additional DB statements with funnel on: VERIFIED. No `Database` use in `SignalEngineTap` (only `ScannerTap`, `funnel_hooks.py:540-545`, not wired here); equal call counts in all developer seeds and my 25 enforce + boundary runs.
- Signals, statement text/count/order and messages identical off/on and vs ea8ae4f: VERIFIED (harness trace equality including args and order; before-tree parity 25 seeds; the emission path `save_signal` lives in pinned, identical `signal_logic.py`).
- Decisions unchanged with broken store/recorder: VERIFIED and extended (raises injected into `candidate_fields`, `engine_label_code`, `_symbol_identities`, `_macro_cause`, `_decision`, `FunnelCycle.count` → parity held).
- Every live-selector label mapped; unknown counted once as `F4.unattributed` without invalidating: VERIFIED. All literal labels of `signal_logic.py:757-826`, the dynamic `stop_rejected:*` reasons found in `shared/signal_stop.py` and `trade_geometry.py`, `freshness:*`, `identity:*`, and the real `cycle_gate().reason` map. The only unmapped string, `freshness:timeframe_unknown`, is unreachable (identity check raises first, `signal_identity.py:99,262`).
- Conservation: VERIFIED for the legacy cut (count/list split handled, `funnel_hooks.py:836-857`), a symbol straddling the 200 boundary, exactly 200 rows under macro block, the non-live path, and abort→clean cycle. `analysis_results` is upserted on `(symbol, timeframe)` (`analyzer/main.py:167-173`), so duplicate subject keys do not arise.
- Shared mutable state untouched: VERIFIED. The tap reads `results`, `decisions`, `macro.state()`/`data_is_fresh()` (pure, `macro_context.py:100-122`); the `_fixed_candidate_key` wrapper returns the original key and dedups by `id()` (`funnel_hooks.py:793-798,803-812`); no new clock reads beyond `cycle_started_ms`.
- `config_hash` unchanged: VERIFIED (flags are environment reads, not Config fields).
- `code_sha` changes and nothing reads it: VERIFIED (writers only: `evidence_v2.py:175`, `signal_logic.py:215`; setup identity uses `APP_VERSION`).
- 75–175 ms latency: NOT VERIFIED (not measured).
- "151 passed": VERIFIED under both interpreters with the test of R1-06 deselected.
- Image identity, hashes, overlay ownership: NOT APPLICABLE (R2).

**D. Residual risks**
- Funnel events share the 10000-deep evidence_v2 queue; saturation drops other evidence types (never decisions).
- Attribution is per-symbol last label (OF-08); per-timeframe reasons are lost by design.
- Legacy-cut positions come from separate statements; approximate under concurrent analyzer writes (flagged `cut_count_inconsistent` when detectable).
- No SE-1 entry exists yet in `deploy/VERSION_BOUNDARY.md`; `code_sha` stamped in saved signals changes at activation.
- R1-01 dormant path.

**E. Minimal remediation (SE-1 safety only)**
1. State in the Compose change and the version-boundary record that `SELECTION_POLICY`, `SELECTION_VERSION`, `SELECTION_SCORE_KEY` are absent (R1-01).
2. Optional before build: call-site guards for `tap.health/note/start_decision`, and import `funnel_hooks` before `Database.connect` (R1-02, R1-03).
3. Deselect or guard the `strategy_identity` test when evidence is run against the release export (R1-06).
None of these blocks SE-1 on R1 grounds.
