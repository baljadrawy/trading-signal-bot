# Design A v1.0: synthetic validation evidence

**What this is.** Sanitized evidence for the independent review of `feature/design-a-v1`. It is software evidence only. Passing tests is not evidence of profitability (the owner brief), and no market data was used.

**Code under test:** the tree of the commit that carries this revision of the document.
- It follows `4a4f40f` (weekly retries).
- It adds the owner-approved durable candle integrity for offline replay and resume (2026-10-31; specification §5).
- Earlier revisions of this record covered `0aaf2e1` and `4a4f40f`.

**Base:** `origin/main` at `eba90dd`.

**Specification:** `docs/strategy/DESIGN_A_SPEC_v1.0.md`. Integrity is in §5; the review log for this round is §23, R15.

## Scope check

12 files, all under the paths below. No file outside them was modified:
- `research/design_a/`: `__init__.py`, `state.py`, `timing.py`, `decision.py`, `ledger.py`
- `tests/`: `design_a_synthetic.py`, `test_design_a_timing.py`, `test_design_a_decision.py`, `test_design_a_ledger.py`, `test_design_a_isolation.py`
- `docs/strategy/DESIGN_A_SPEC_v1.0.md`, `docs/strategy/DESIGN_A_V1_EVIDENCE.md`

This revision changes 8 of them and adds or removes none:
- `state.py`, `decision.py`, `ledger.py`;
- `design_a_synthetic.py`, `test_design_a_ledger.py`;
- `test_design_a_isolation.py`, whose only change admits the stdlib module `functools`;
- the specification and this record.

Nothing changed under `.github/`, `deploy/`, `shared/`, `docs/governance/`, `docs/ops/` or any runtime service directory. No Dockerfile or compose file changed. No `conftest.py`, `pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini` or `research/__init__.py` was added. The integrity evidence lives in the existing `State` and ledger: no database, service, storage system or other infrastructure.

## Commands and results

**Design A suite:**
```
cd <worktree> && umask 022 && PYTHONDONTWRITEBYTECODE=1 <venv>/bin/python -m pytest -q -p no:cacheprovider -rs \
  tests/test_design_a_timing.py tests/test_design_a_decision.py tests/test_design_a_ledger.py tests/test_design_a_isolation.py
```

| Check | Environment | Result |
|---|---|---|
| Design A suite | the project venv (`research/skill_application/.venv`): Python 3.12.3, pytest 9.1.1 | 81 passed, 0 failed, 0 skipped |
| Design A suite | a venv with the pinned CI test set (`.github/ci/requirements-test.txt`: all 64 pins at their pinned versions, plus one unpinned package, `nvidia-nccl-cu12`, that Design A does not import): Python 3.12.3, pytest 9.1.1 | 81 passed, 0 failed, 0 skipped |
| Existing tests that walk `research/` or `tests/` | the project venv | 263 passed |
| `ops/provenance/protected_scan.py --base origin/main --head <commit>` | system Python | SCAN CLEAN |
| Key-pattern search of the branch diff's added lines (cloud, Git hosting, chat and API keys; private keys; database URLs) | — | no match |

- **Per test file:** timing 13, decision 13, ledger 49, isolation 6.
- **Runtime of the suite:** about 29 s, against 6.7 s for the 71 tests of `4a4f40f`, measured back to back under the same conditions. The same 71 tests take about 20 s on this tree, because every replay now fingerprints and checks candles; the 10 new tests take the rest. See the resource measurement below.
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
     - 13 tampered or malformed records;
     - 3 consistent but non-canonical records;
     - a tampered state in memory;
     - a forged decision window.
  7. **Deterministic digests across process restarts and hash seeds:** `test_replay_is_deterministic`, now including the restored scenario, and the cross-process test.
  8. **Interrupted versus uninterrupted replay:** `test_an_interrupted_replay_resumes_to_the_same_ledger` and the restored variants above.
  9. **Weekly retries:** `test_restoration_inside_a_retry_window_resumes_identically`, plus the retry-window cut of the interrupted-replay test.
  10. **Remaining known limitation:** `test_known_limitation_unconsumed_candles_are_checked_within_one_call_only`. A candle that was delivered but not yet consumed before a cut is checked within one call only (specification §5).
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

## Integrity resource measurement

**Method.** A scratch probe, not committed, run on fabricated data only, with no returns or equity computed. "Checks off" replaces `check_consumed` and `verify_integrity` with no-ops. "All off" also drops the fingerprints and the index. The 2,900-day history is a seeded stdlib walk dated 2001–2008: a size test near the limit of the pre-2009 guard, not a backtest.

| | 540-day fixture | 2,900-day fabricated history |
|---|---|---|
| Consumed-index entries | 536 | 2,895 |
| Index memory (217 bytes per entry) | 114 KiB | 614 KiB |
| Index share of the JSON record (about 100 bytes per entry) | 52 of 78 KiB | 280 of 449 KiB |
| Ledger entries / actionable decisions | 132 / 49 | 822 / 386 |
| Replay, daily snapshots: integrity on / checks off / all off | 0.42 / 0.31 / 0.16 s | 14.9 / 7.3 / 3.3 s |
| Replay, weekly snapshots: integrity on / checks off / all off | 0.27 / 0.24 / 0.10 s | 7.2 / 5.1 / 1.4 s |
| `verify_integrity`, per call | 15.7 ms | 144 ms |
| `check_consumed`, last snapshot | 0.84 ms | 7.6 ms |
| `state_from_record`, per restoration | 22–34 ms | 180–200 ms |

**Findings:**
- **Memory is linear.** The index has one entry per consumed day; overlapping windows share entries, and each decision and fill adds one 64-character value to the ledger.
- **The fingerprint cache is bounded.** Its cap is 65,536 entries, at about 240 bytes each plus the candle it keeps alive. That is about 33 MB at the cap; the fixture uses 536 entries.
- **Each check is linear in its inputs.**
  - A snapshot check is linear in the snapshot and the index.
  - `verify_integrity` is linear in the number of decisions.
  - With full-history snapshots the replay was already quadratic in the history length, because every snapshot carries the whole history. The checks keep that order and add a constant factor.
- **Two patterns are quadratic over a whole run.** Both have the order of existing code, with larger constants:
  1. **Resuming after every single snapshot,** because `verify_integrity` runs at every call. For the fixture that is 3.07 s for 540 calls, against 0.42 s in one call.
  2. **Re-validating the whole index in every `State` construction,** as the constructor already does for the ledger. Under cProfile, which inflates many small calls, it takes about 30 % of a clean replay. With the `Decision` window check, the character-level fingerprint checks take about 45 %, and `check_consumed` about 27 %.
- **Not optimised,** as instructed. Options if a reviewer wants them:
  - validate fingerprints once, where they enter (merge, restoration), rather than in every construction;
  - use a faster fingerprint check;
  - verify once per restoration rather than per call;
  - bisect the sorted index to the coverage start.

## Breakage check (mutation testing)

Method:
1. Each safeguard below was broken by one source edit.
2. The Design A suite was run against the broken code, in a scratch copy of the tree.
3. The original file was restored, and its sha256 verified.

**Result on the final tree: 58 of 58 breakages caught.**

**This revision adds 14 of them** (listed below with the rest):
- 8 for the integrity mechanism, written with it;
- 6 more for checks those 8 did not target: the window coverage that `decide` gained later in the round; the reference fingerprints; the order of the index; the window length; the availability clause; verification on restoration.

The one stale anchor, for "NO_CHANGE drops the target", was updated to the new code. Before it was fixed, the script stopped before changing any file.

Earlier runs in this round, which shaped the tests:
- **On the code before the last fixes: 51 of 52 caught.** The survivor, "restore skips canonical check", showed that no test reached `state_from_record`'s round-trip check. Non-canonical records are now tested.
- **A later run: "consumed conflict ignored" survived** a reworked revision test. The next decision's merge refused the same revision with the same message, which masked the check. The test now delivers the revision in a call that ends before the next decision, and includes a window day that no later decision reads.

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

## Reviews

The earlier rounds had three reviewer passes in the same session:
- the code and tests against the brief;
- the specification against the brief and the cited repository files;
- a focused re-review of the fixes.

This round was self-reviewed in the same session. None of this is independent approval. Every BLOCKER or MAJOR finding was resolved. Findings and resolutions are listed in the specification, §23 (X1–X16, R1–R15).

## Not uploaded or not done, and why

| Item | Reason |
|---|---|
| CI | Pushes to `feature/*` trigger no workflow, and GitHub Actions is billing-blocked. No CI result is claimed. |
| LCE | Not authorized for this work; not run. |
| The breakage-check script and the resource probe | Local scratch tools. The breakage check rewrites package files in place, so it does not belong in the repository. The lists and tables above are the reviewable record. |
| Revision detection for candles delivered but not yet consumed, across a cut | Not implemented: outside the approved mechanism, which covers consumed candles. A known limitation, pinned by a test and described in the specification, §5. |
| Authenticity of saved records (keyed MAC, signature, external anchor) | Not implemented: new infrastructure, outside v1.0 (specification §5). |
| Reviewer transcripts | Session-local. Their findings and resolutions are summarized in the specification, §23. |
| A29–A34 texts | Not in this repository (commit `54a6369`, OD-1/OD-2), so "consistent with A29" could not be checked. |
| Market data, protected data, telemetry, runtime logs | None were used, so none exist to upload. |
