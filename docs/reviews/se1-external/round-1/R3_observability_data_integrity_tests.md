> **Coordinator note (not part of the review).** The report is stored verbatim except for three marked redactions. During its review, Reviewer 3 read the production evidence_v2 recorder stats and the line counts of one post-freeze daily event file. That fell outside the review package's scope, and the counts may be FORWARD_HOLDOUT-protected (OD-7). The coordinator removed those counts and reported the deviation to the owner. The unredacted original is kept locally and is not published.

REVIEWER 3 (model: Sonnet 5.5) — SE-1 observability, data integrity and test evidence

Scope: candidate 7ff582f, baseline ea8ae4f, tests from feature/wp2-foundation-20261101 at 0ddc324. Everything below was independently reproduced unless marked "developer-reported".

**A. Verdict: CONDITIONAL GO.**
- Nothing here blocks a bounded Paper observation window.
- The "bounded storage" and "every cycle valid" claims are weaker than the README states. Three conditions follow (B1, B2, B3). They are acceptance-criteria and documentation fixes. Only B2's code change is optional.

**B. Findings**

**B1 (MEDIUM): the daily cap is per process, not per UTC day.**
- Code: shared/funnel_hooks.py, `FunnelService._day_emitted`, `_roll_day`, `_series`. All three are in memory only.
- Reproduction: cap 5 and four process lifetimes in one UTC day gave 20 records. Each start has an empty series cache, so every open series is re-emitted.
- The old series are never closed. `repeat_count` and `last_seen` exist only on the closing event, so they are lost.
- Impact: the "worst case = cap × 1657 B" bound is really cap × (starts per day).
  - Compose uses `restart: unless-stopped`.
  - The per-cycle limit of 901 is the only other bound.
- Fix: say so in the owner's request, or seed the counter at start-up from the day's own JSONL file. That is a file read, not a database read.
- Blocks SE-1: no.

**B2 (MEDIUM): a dropped or failed emit loses the record for the whole life of its series.**
- Code: `publish` registers the series in `_series` before `_emit_record`. `_emit_record` ignores the return value of `_emit`.
- Reproduction: with the queue forced to 3 entries, 10 records were attempted and 3 reached the sink. Later identical cycles were treated as compacted repeats, so the other 7 were never re-emitted.
  - The cap counter had also been charged for all 10.
  - `not_recorded` read 8 and evidence_v2 `dropped` read 8, so the loss is visible.
- The docstring says a record held back "is not marked as emitted". That is true for the bounds only, not for failed emits.
- Fix: register the series only when the emit returned True. In any case, make `not_recorded == 0` a hard acceptance gate.
- Blocks SE-1: no.

**B3 (MEDIUM): `valid` is true for incomplete cycles.**
- Reproduction: `tap.abort(RuntimeError)` gives an envelope with `valid` true, `observation_complete` false and `integration_failures` set to `cycle_exception`.
- The code comment says this is intended. The non-live path (`gate_block = unobserved_legacy_score_path`) and `macro_block_cause_not_reproduced` also report `valid` true.
- The README gate "every funnel.cycle has valid true" would therefore pass on broken cycles.
- Fix: the gate must read `observation_complete == true`, `integration_failures == []` and no `notes.gate_block`.
- I could not confirm whether LIVE_LEARNING_MODE is true in production; that is set in an env file I may not read.
- Blocks SE-1: no.

**B4 (LOW): a backward clock step resets the cap.**
- Reproduction: cycles alternating between two UTC days with cap 5 gave 30 rejections. `_roll_day` resets on any change of day, including a regression.
- Fix: roll the counter only forward.

**B5 (LOW): the stage order in the funnel is not the order the code evaluates.**
- Both the module docstring and the README say "pinned gate order".
- `GATE_ORDER` is F4, F2, F5, F7. The real order in `signal_logic.find_best_signal_live` is F4 no-setup, F2 book and spread, F5 stop, F7 open trade, and then F4 cooldown, integrity and learned gate.
- Cooldown and learned-gate drops are counted as F4 drops even though those symbols passed F2, F5 and F7 first.
- Conservation still holds, but per-stage yields are not a sequential filter.
- Labels are per symbol, last label wins. A symbol with several timeframes loses its non-final rejection reasons. The developer acknowledges this limit (BLOCKED-WP-OD-01).

**B6 (LOW): `F4.unattributed` is hard to diagnose.**
- The envelope carries only a count. The label text sits in `detail.legacy_reason` of a record that compaction or the cap can suppress.
- The heartbeat `funnel` health does not carry the count.
- The bucket mixes three causes: missing label, unknown label, and exploration on a symbol that never reached ranking.
- Fix: add a bounded per-label count to the envelope.

**B7 (LOW): a macro-veto flap burns the cap.**
- Reproduction: with 190 symbols and the veto flipping every cycle, 10 cycles gave 1909 events, about 190 per flip.
- Cause: a veto cycle sees none of the F4 series, so it closes them all. The next cycle reopens them.
- Series closures also count against the cap.

**B8 (LOW): test gaps.**
- *Close events and the cap.*
  - Mutant M8 (the series-close loop no longer calls `_take`) passed 151 of 151 tests.
  - The cap test uses identical cycles, so nothing ever closes.
- *Fixtures.*
  - `analysis_row` returns `analysis_data` as a dict, but asyncpg returns the JSONB column as a string. I fed string rows on 3 seeds: parity and conservation held.
  - `_engine_env` forces `SIGNAL_INTEGRITY_MODE=off`. The enforce-mode labels (freshness, identity, duplicate setup, unverified safety state) are tested only as a direct label table.
- *Missing tests.* There is none for a restart, clock skew, or a full queue with funnel on (the existing broken-store test only makes `emit` raise).
- *Strategy-id test.* `test_strategy_ids_are_the_declared_family_ids` imports `shared/strategy_identity.py`, which is not in the 7ff582f tree. That check cannot run on the release.

**B9 (INFO): idle cycles leave no trace.**
- With no fresh rows there is no envelope and no `funnel` key in the heartbeat.
- Silence therefore cannot be told apart from a dead tap. The README already treats "no candidate cycles" as insufficient evidence.

**C. Claim verification**

| Claim | Status |
|---|---|
| Decisions, statements and signals are identical with recording on and off | VERIFIED |
| Off-mode equals the ea8ae4f main.py (25 seeds) | VERIFIED |
| No extra database statement | VERIFIED |
| Parity is independent | PARTLY: only main.py differs between the trees (shared/ and signal_logic are the same in both), which is correct for a main.py change |
| Conservation | VERIFIED but partly tautological: the counts and the records come from the same drop lists, and the cross-checks are the independent ranking observation (`gate_count_mismatch`, `rank_mismatch`) and the chain link |
| Taxonomy v1.1 is additive; unknown labels become `F4.unattributed` without invalidating the cycle | VERIFIED |
| Cap resets at the UTC day boundary | VERIFIED (unit test; the boundary is by decision time) |
| Cap is a daily bound across restarts | REFUTED (B1) |
| Envelopes bypass the cap | VERIFIED, bounded to at most 1440 a day by the 60 s sleep and the error backoff of 60 s or more |
| Series-close events count against the cap | VERIFIED in code (not covered by tests, B8) |
| Records are compacted, with the series cache bounded at 50000 entries | VERIFIED |
| "A held-back record is not marked as emitted" | REFUTED for failed emits (B2) |
| Storage is about 36 MB a day at cap 20000 | VERIFIED by sizes: my fixture gave 1680 B per rejection and 2321 B per envelope (README: 2006 B) |
| Latency is 75 to 175 ms a cycle | VERIFIED: 230 symbols × 3 timeframes, 40 to 140 ms synchronous in the event loop; p99 emit 0.16 ms |
| Drops and errors stay observable | VERIFIED: `not_recorded` in the heartbeat, `dropped` and `errors` in the evidence_v2 health |
| Funnel drops cannot be told apart from drops of other event types | Not separable by type; only by subtraction |
| "Every funnel.cycle valid" is a sufficient acceptance gate | REFUTED (B3) |

**D. Residual risks**

- *Queue crowding.* The queue is the shared 10000-entry one, and funnel events do not bypass it.
  - [REDACTED BY COORDINATOR: two lines quoting production evidence_v2 counts from the recorder stats file and a post-freeze daily event file]
  - The flusher drains 500 events every 2 s.
  - A worst-case 901-record burst fits easily. Crowding needs a prolonged sink stall.
  - The daily cap limits funnel inflow to about 21,400 events a day (cap plus 1440 envelopes).
- *Cap likely never reached.* [REDACTED BY COORDINATOR: production-derived count] suggests roughly 10k funnel events a day or fewer, with closures included. At 20000 the cap is probably never hit in the window, so its runtime behaviour stays untested. This is my estimate, not a measurement.
- *Cut counts.* They come from separate statements (count and offset list), so rows analysed between them are mis-ranked. The check only catches `total < returned + listed`.
- *Clock.* The cap day uses the cycle start, while the file day uses `recorded_at_ms`. They differ by at most a few hundred milliseconds around midnight.
- *Pre-existing tuning.* Funnel adds about 30% to the event count (1440 envelopes a day against [REDACTED BY COORDINATOR: production-derived count]) and no fsync tuning.
- *What a 24-hour window cannot establish.*
  - Rare labels such as `open_trade_exists`, learned-gate or stop variants.
  - Cap behaviour and restart behaviour.
  - Queue saturation.
  - Count accuracy against ground truth. The only independent references are the existing `cycle.outcome` decision histogram and the `decision_reason` column the engine writes. They share the same labels, so they are a consistency check, not truth.
- It does support: no refusal, no restart, health twice, zero drops and errors, envelope sizes, disk growth, and one UTC midnight crossing.

**E. Minimal remediation (SE-1 safety)**

1. Rewrite the acceptance gates, with no code change:
   - `valid`, `observation_complete`, `integration_failures == []` and no `gate_block` on every envelope;
   - `not_recorded`, `records_overflow`, `unattributed`, evidence_v2 `dropped` and `errors` equal to 0 or explained;
   - envelope count against expected cycles;
   - reconcile F-stage reason counts with the `cycle.outcome` decision histogram;
   - treat an idle window as inconclusive.
2. Tell the owner that 20000 is a per-process-day bound (B1).
3. Recommended and cheap:
   - register a series only after a successful emit (B2);
   - roll the day forward only (B4);
   - add a per-label unattributed count to the envelope (B6);
   - add a test for the cap on close events (B8).

**Test runs (all against `git archive` exports)**
- 7ff582f tree + feature tests at 0ddc324 (test files last changed in 13704d4), with `WP2_BEFORE_TREE` set to a `git archive` export of ea8ae4f.
- Scanner, analyzer and strategy-id cases excluded: 151 passed, 1 failed (`test_strategy_ids_are_the_declared_family_ids`, module absent from the release).
- Also excluding the `unknown_flag` and strategy-id cases: 150 passed in both the local venv and the CI-pinned venv.
- Whole file: 187 passed and 37 failed. The failures are the scanner, analyzer and strategy-id tests plus the scanner and analyzer parameters of `test_unknown_flag_refuses_before_any_io`. None of those services is in this release.
- Mutants (each run against the 7ff582f tree with the feature tests):
  - caught: day never rolls, cap ignored, tap reorders results, extra database read, stage-count off-by-one, unattributed zeroed, cap off-by-one;
  - missed: M8.
- Scripts and exports are in the r3 scratch directory.
