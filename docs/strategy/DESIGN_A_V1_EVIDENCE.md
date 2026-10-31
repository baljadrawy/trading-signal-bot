# Design A v1.0: synthetic validation evidence

**What this is.** Sanitized evidence for the independent review of `feature/design-a-v1`. It is software evidence only. Passing tests is not evidence of profitability (the owner brief), and no market data was used.

**Code under test:** the tree of the commit that carries this revision of the document.
- It follows `d6bc9ca` (durable candle integrity).
- It adds the focused performance remediation of that mechanism (specification §5 "Cost of the checks", §23 R16) and a read-only decision memo, `docs/strategy/DESIGN_A_PROFITABILITY_DECISION_MEMO.md`.
- Earlier revisions of this record covered `0aaf2e1`, `4a4f40f` and `d6bc9ca`.

**Base:** `origin/main` at `eba90dd`.

**Specification:** `docs/strategy/DESIGN_A_SPEC_v1.0.md`. Integrity is in §5; the review log for this round is §23, R15.

## Scope check

13 files, all under the paths below. No file outside them was modified:
- `research/design_a/`: `__init__.py`, `state.py`, `timing.py`, `decision.py`, `ledger.py`
- `tests/`: `design_a_synthetic.py`, `test_design_a_timing.py`, `test_design_a_decision.py`, `test_design_a_ledger.py`, `test_design_a_isolation.py`
- `docs/strategy/DESIGN_A_SPEC_v1.0.md`, `docs/strategy/DESIGN_A_V1_EVIDENCE.md`, `docs/strategy/DESIGN_A_PROFITABILITY_DECISION_MEMO.md`

This revision changes 6 of them and adds 1:
- changed: `state.py`, `decision.py`, `ledger.py`, `test_design_a_ledger.py`, the specification and this record;
- added: the decision memo;
- no new dependency or import (the isolation allow-list is unchanged).

Nothing changed under `.github/`, `deploy/`, `shared/`, `docs/governance/`, `docs/ops/` or any runtime service directory. No Dockerfile or compose file changed. No `conftest.py`, `pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini` or `research/__init__.py` was added. The integrity evidence lives in the existing `State` and ledger: no database, service, storage system or other infrastructure.

## Commands and results

**Design A suite:**
```
cd <worktree> && umask 022 && PYTHONDONTWRITEBYTECODE=1 <venv>/bin/python -m pytest -q -p no:cacheprovider -rs \
  tests/test_design_a_timing.py tests/test_design_a_decision.py tests/test_design_a_ledger.py tests/test_design_a_isolation.py
```

| Check | Environment | Result |
|---|---|---|
| Design A suite | the project venv (`research/skill_application/.venv`): Python 3.12.3, pytest 9.1.1 | 83 passed, 0 failed, 0 skipped |
| Design A suite | a venv with the pinned CI test set (`.github/ci/requirements-test.txt`: all 64 pins at their pinned versions, plus one unpinned package, `nvidia-nccl-cu12`, that Design A does not import): Python 3.12.3, pytest 9.1.1 | 83 passed, 0 failed, 0 skipped |
| Existing tests that walk `research/` or `tests/` | the project venv | 263 passed |
| `ops/provenance/protected_scan.py --base origin/main --head <commit>` | system Python | SCAN CLEAN |
| Key-pattern search of the branch diff's added lines (cloud, Git hosting, chat and API keys; private keys; database URLs) | — | no match |

- **Per test file:** timing 13, decision 13, ledger 51, isolation 6.
- **Runtime of the suite:** 17–18 s, against 29.8 s for the 81 tests of `d6bc9ca`, measured back to back under the same conditions (and 6.7 s for the 71 tests of `4a4f40f`, before integrity existed).
- **Owner decision 2026-10-31 (weekly retries): ten regression items, all still passing.**
  1. An expired SELL is retried at the next FLAT decision (baseline and stress).
  2. A rejected SELL is retried only at the next valid weekly decision, and minimums still apply.
  3. An expired BUY is retried at the next LONG decision (baseline and stress).
  4. An executed BUY is not duplicated.
  5. An executed SELL is not duplicated.
  6. Missing Sunday data triggers no retry.
  7. A retry keeps the original schedule, costs and 72 h expiry.
  8. A retry moves no balance until a fill.
  9. Replay and resume stay deterministic, including a cut inside a retry window.
  10. Dust below the tradable minimums creates no repeated orders.

  A changed signal also replaces a pending retry.
- **Owner approval 2026-10-31 (durable candle integrity): the mandatory tests, all passing.** All are in `tests/test_design_a_ledger.py`:
  1. **Identical candles across separate calls:** `test_identical_candles_resume_across_calls_and_restoration`, both in memory and after a JSON round trip.
  2. **Revised candles across separate calls:** `test_a_revised_consumed_candle_is_refused_across_calls`, covering items 2–4 of the owner's list:
     - a revised window candle, both an old window day that no later decision reads and one that the next decision reads again;
     - a revised Sunday candle used by a decision;
     - a revised reference candle used by an execution.

     Each case runs in memory and after restoration, in a call that ends before the next decision, so the refusal comes before anything is processed. Trailing zeros are not a revision.
  3. **Missing previously consumed candle:** `test_a_missing_consumed_candle_is_refused_never_assumed`. Each case is refused, never assumed to match:
     - a candle inside the snapshot;
     - a history cut short inside the next decision's window;
     - the reference candle within one call;
     - the rough fixture's former day-330 outage.

     A history that drops only consumed days no later window reads still resumes identically.
  4. **Missing candles that were never consumed:** `test_a_missing_unconsumed_candle_follows_the_missing_data_rules`. After restoration they follow the existing rules: a window gap skips, a due reference defers to Wednesday. The rough fixture's day-352 outage is still a gap.
  5. **Serialisation and restoration followed by resume:** the restored cases above, the restored scenario, and `test_a_state_saved_by_one_process_resumes_in_another`.
  6. **Tampered or malformed integrity metadata:** `test_tampered_or_malformed_integrity_metadata_is_refused`. It covers:
     - 14 tampered or malformed records, among them an index whose days were re-labelled so that each window slice keeps its fingerprint sequence;
     - 3 consistent but non-canonical records;
     - a tampered state in memory;
     - a forged decision window.
  7. **Deterministic digests across process restarts and hash seeds:** `test_replay_is_deterministic`, now including the restored scenario, and the cross-process test.
  8. **Interrupted versus uninterrupted replay:** `test_an_interrupted_replay_resumes_to_the_same_ledger` and the restored variants above.
  9. **Weekly retries:** `test_restoration_inside_a_retry_window_resumes_identically`, plus the retry-window cut of the interrupted-replay test.
  10. **Where checks enter (R16):** `test_fingerprints_and_index_entries_are_checked_where_they_enter` (format, merges, ordering, conversion of plain tuples) and `test_the_replay_record_vouches_only_for_the_same_candle_and_fingerprint` (the per-call record never vouches for another candle object or fingerprint).
  11. **Remaining known limitation:** `test_known_limitation_unconsumed_candles_are_checked_within_one_call_only`. A candle that was delivered but not yet consumed before a cut is checked within one call only (specification §5).
- **Effect on existing tests.** No established assertion was changed, relaxed or removed.
  - **Unchanged.** 30 of the 33 earlier ledger test functions are byte-identical. The timing and decision test files are unchanged, and the isolation test changed only its stdlib allow-list.
  - **Changed, apart from docstrings:**
    - The `signal()` helper gives hand-built decisions the window fingerprints of a flat synthetic history, the same for every decision. The new `Decision` contract requires them.
    - Two tests gained assertions. The determinism test also checks the restored scenario. The construction test refuses a decision without its window fingerprints, and a warm-up that carries them.
    - The old known-limitation test keeps its body verbatim, under a new name and docstring, because the limitation it pins is now narrower.

  **The rough fixture.** Its gap outage moved from day 330 to day 352, because earlier decisions had consumed day 330, which the integrity rule now refuses. Both outcomes are tested.
- **The existing tests** are the repository's literal and isolation guards: `test_a42_signal_quality.py`, `test_s5_pwr1_ladder_power.py`, `test_s5_pwr1_remediation.py`, `test_s4_mechanisms.py`, `test_a43_signal_integrity.py`, `test_a45_setup_diagnostics.py`, `test_a46_trade_geometry.py` and `test_a47_execution_realism.py`.
- **No caches.** No test run of this revision wrote bytecode or cache files into the worktree; `git status --ignored` was checked after the runs. Two ignored bytecode files from an exploratory import on 2026-10-30, before the first commit, were found at the start of this round and removed.

## Determinism and reproducibility

- **Digest:** replays are compared by sha256 of the canonical record (`research.data_governance.governance.canonical_hash`). The integrity index and the ledger's fingerprints are part of that record.
- **Process independence:** for the clean, rough and restored scenarios, the digest is identical:
  - in-process;
  - in fresh interpreters with `PYTHONHASHSEED` 0 and 4242;
  - under a hostile ambient decimal context: precision 3, lower-case exponents, and a `DefaultContext` with `Emax = 3`.
- **A real process boundary:** a state saved as JSON by one interpreter (hash seed 0) and restored by another (hash seed 4242, hostile decimal context) resumes to the uninterrupted digest.
- **Cadence independence:** daily, weekly and every-third-day snapshot cadences give the same digest. This was checked on three data cases that never deliver a candle late:
  - the clean path;
  - permanent losses that force a Thursday fill, a minimum-order rejection and dust;
  - permanent losses that force an expiry.
- **Interrupted replays** resumed from the saved state, in memory or after a JSON round trip, give the same digest as uninterrupted ones.

## Performance: before and after (R16)

**Method.** One harness ran on fabricated data only, computing no returns or equity:
- **Trees.** The `d6bc9ca` tree and this tree, interleaved over two rounds, A B A B, to cancel load drift on the shared host. Earlier separate runs showed that drift.
- **Fixtures.** Identical for both trees; each figure is a median.
- **Long history.** The 2,900-day history is a seeded walk dated 2001–2008: a size test, not a backtest.
- **Digests.** Every fixture's final-state digest was identical in both trees.

| Case | `d6bc9ca` | this tree | speed-up |
|---|---|---|---|
| clean daily replay (540 snapshots) | 0.470 s | 0.260 s | 1.81× |
| rough daily replay | 0.477 s | 0.268 s | 1.78× |
| clean weekly replay | 0.303 s | 0.164 s | 1.85× |
| clean, resumed after every snapshot (540 calls) | 3.728 s | 1.405 s | 2.65× |
| clean, cut at 300, JSON restore, resume | 0.546 s | 0.290 s | 1.88× |
| 2,900-day daily replay | 14.83 s | 7.16 s | 2.07× |
| 2,900-day weekly replay | 7.01 s | 3.00 s | 2.33× |
| `verify_integrity`, clean / 2,900-day final state | 16.3 / 134.5 ms | 6.6 / 43.4 ms | 2.5× / 3.1× |
| `state_from_record`, clean / 2,900-day | 26.5 / 218.8 ms | 20.6 / 113.1 ms | 1.3× / 1.9× |
| Design A suite | 29.8 s (81 tests) | 17–18 s (83 tests) | — |

**Bottlenecks measured on `d6bc9ca`, and what changed.** The shares are instrumented, of the clean daily replay.

| Bottleneck | Share | Change | Safeguard kept |
|---|---|---|---|
| repeated consumed-candle comparisons in `check_consumed` | 30 % | `replay` keeps a per-call record of confirmed (candle object, fingerprint) pairs; the same object under the same fingerprint is not hashed again. The availability rule is applied once per call | presence is checked at every snapshot; every new call starts empty; the public functions always check in full |
| full index re-validation in every `State` construction | 25 % | the index is a validated `ConsumedIndex`, checked in full when built; merges check what they add | restoration and any plain tuple are checked in full |
| fingerprint-format checks (character loops) | part of the above, and 8.5 % in `Decision` | a C-level `str.strip` check, proved equal to the old check on 200,015 adversarial strings | the same accepted set |
| per-decision cross-verification in `verify_integrity` | dominant when resuming per snapshot | each window is one slice of the sorted index, hashed whole | still comprehensive at every call and every restoration |

After the change, the shares are:
- `check_consumed`: 22 %;
- `merge_consumed`: 8 %;
- `State.__post_init__`: 1 %.

**Memory.** Unchanged:
- **Index.** One entry per consumed day, about 217 bytes in memory and 100 in JSON: 536 entries for the fixture, 2,895 for the 2,900-day history.
- **Fingerprint cache.** Bounded at 65,536 entries, about 33 MB at the cap.
- **The per-call record.** Holds at most one entry per consumed day and is freed when the call returns.

**Remaining performance risks:**
- **Full-history daily replays still cost about twice an integrity-free replay.** Every snapshot is still checked for presence against the whole covered index (2,900 days: 7.2 s).
- **Resuming after every single snapshot is still quadratic over a whole run.** Each `replay` call verifies in full, by design. A caller feeding snapshots within one process should pass a generator to one call.
- **Larger, non-synthetic workloads were not measured.**
- **Not done** (each would be a further change, not demonstrated as needed):
  - bisecting the index to the coverage start (it helps only shorter-history sources);
  - avoiding the per-merge sort.

## Breakage check (mutation testing)

Method:
1. Each safeguard below was broken by one source edit.
2. The Design A suite was run against the broken code, in a scratch copy of the tree.
3. The original file was restored, and its sha256 verified.

**Result on this tree: 65 of 65 breakages caught.**

**This revision:**
- **7 new mutants** for the new code paths:
  - the window end check;
  - the fingerprint format;
  - the per-call record's identity condition;
  - its fingerprint condition;
  - the merge's check of added pairs;
  - the `State` index validation;
  - the merge's sort.
- **7 re-pointed anchors.** The mutants for the merge conflict, the window digest, unused index entries, the decision window, reference fingerprints, index order and the availability clause now point at the reshaped code, with unchanged meaning.

All 65 were caught. The run's inputs were byte-identical to this tree's code and tests.

**Earlier rounds** (`d6bc9ca` and before) are recorded in that revision of this file: 58 of 58, after two survivors found by earlier runs had led to new tests.

`decision.py`:
- equality counts as LONG
- warm-up after decisions
- decision window coverage ignored

`timing.py`:
- missing Sunday ignored
- gap treated as warm-up
- Monday open eligible
- gap anywhere in history skips

`ledger.py`:
- four-day deferral window
- Thursday never tried
- late candle used retroactively
- spread charged twice
- fee on reference notional
- minimum-order check removed
- dust deleted on sell
- ambient decimal context in fills
- time-travel guard removed
- pending check before decision allowed
- skipped decision instant passes
- missing data booked at check time
- forged NO_SIGNAL accepted
- residual keyed to position only
- NO_CHANGE drops the target
- skip does not advance the decision clock
- revised candle accepted
- resume into the past accepted
- warm-up after a decision accepted
- retry not marked
- replay skips integrity verification
- restore skips canonical check
- restore skips integrity verification

`state.py`:
- candle available at its open
- decision offset 0 s
- always rebalance
- no retry after a failed transition
- permission gate disabled
- context-dependent Decimal text
- contexts inherit defaults
- incomplete candle accepted
- pending/status invariant removed
- position ignores min_qty
- fee of 1 or more accepted
- action type unchecked
- decision may contradict F5
- permission checked loosely
- post-2009 synthetic data accepted
- ledger order unchecked
- ledger balances unchecked
- entry amounts unchecked
- consumed conflict ignored
- missing consumed candle ignored
- merge ignores conflicts
- window digest unchecked
- extra index entries allowed
- fingerprint ignores values
- reference fingerprint unchecked
- consumed order unchecked
- decision window length unchecked
- unavailable consumed candles required
- fingerprint format unchecked
- window end unchecked
- record vouches for any candle
- record ignores the fingerprint
- merge skips checking added pairs
- State skips index validation
- merge leaves the index unsorted

## Reviews

The earlier rounds had three reviewer passes in the same session:
- the code and tests against the brief;
- the specification against the brief and the cited repository files;
- a focused re-review of the fixes.

This round was self-reviewed in the same session. None of this is independent approval. Every BLOCKER or MAJOR finding was resolved. Findings and resolutions are listed in the specification, §23 (X1–X16, R1–R16).

## Not uploaded or not done, and why

| Item | Reason |
|---|---|
| CI | Pushes to `feature/*` trigger no workflow, and GitHub Actions is billing-blocked. No CI result is claimed. |
| LCE | Not authorized for this work; not run. |
| The breakage-check script and the benchmark harness | Local scratch tools. The breakage check rewrites package files in place, so it does not belong in the repository. The lists and tables above are the reviewable record. |
| Revision detection for candles delivered but not yet consumed, across a cut | Not implemented: outside the approved mechanism, which covers consumed candles. A known limitation, pinned by a test and described in the specification, §5. |
| Authenticity of saved records (keyed MAC, signature, external anchor) | Not implemented: new infrastructure, outside v1.0 (specification §5). |
| Reviewer transcripts | Session-local. Their findings and resolutions are summarized in the specification, §23. |
| A29–A34 texts | Not in this repository (commit `54a6369`, OD-1/OD-2), so "consistent with A29" could not be checked. |
| Market data, protected data, telemetry, runtime logs | None were used, so none exist to upload. |
