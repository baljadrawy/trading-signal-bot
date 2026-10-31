# Design A v1.0: synthetic validation evidence

**What this is.** Sanitized evidence for the independent review of `feature/design-a-v1`. It is software evidence only. Passing tests is not evidence of profitability (the owner brief), and no market data was used.

**Code under test:** the tree of the commit that carries this revision of the document. It follows `fc4bc00` and adds the owner-approved weekly retries (2026-10-31). The previous revision covered `0aaf2e1`.

**Base:** `origin/main` at `eba90dd`.

**Specification:** `docs/strategy/DESIGN_A_SPEC_v1.0.md`.

## Scope check

12 files, all under the paths below. No file outside them was modified:
- `research/design_a/`: `__init__.py`, `state.py`, `timing.py`, `decision.py`, `ledger.py`
- `tests/`: `design_a_synthetic.py`, `test_design_a_timing.py`, `test_design_a_decision.py`, `test_design_a_ledger.py`, `test_design_a_isolation.py`
- `docs/strategy/DESIGN_A_SPEC_v1.0.md`, `docs/strategy/DESIGN_A_V1_EVIDENCE.md`

Nothing changed under `.github/`, `deploy/`, `shared/`, `docs/governance/`, `docs/ops/` or any runtime service directory. No Dockerfile or compose file changed. No `conftest.py`, `pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini` or `research/__init__.py` was added.

## Commands and results

**Design A suite:**
```
cd <worktree> && umask 022 && PYTHONDONTWRITEBYTECODE=1 <venv>/bin/python -m pytest -q -p no:cacheprovider -rs \
  tests/test_design_a_timing.py tests/test_design_a_decision.py tests/test_design_a_ledger.py tests/test_design_a_isolation.py
```

| Check | Environment | Result |
|---|---|---|
| Design A suite | the project venv (`research/skill_application/.venv`): Python 3.12.3, pytest 9.1.1 | 71 passed, 0 failed, 0 skipped |
| Design A suite | a venv with the pinned CI test set (`.github/ci/requirements-test.txt`): Python 3.12.3, pytest 9.1.1 | 71 passed, 0 failed, 0 skipped |
| Existing tests that walk `research/` or `tests/` | the project venv | 263 passed |
| `ops/provenance/protected_scan.py --base origin/main --head <commit>` | system Python | SCAN CLEAN |
| Key-pattern search of the diff (cloud keys, Git hosting keys, private keys, database URLs) | — | no match |

- **Per test file:** timing 13, decision 13, ledger 39, isolation 6.
- **Owner decision 2026-10-31 (weekly retries): ten regression items, all passing.**
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
- **The existing tests** are the repository's literal and isolation guards: `test_a42_signal_quality.py`, `test_s5_pwr1_ladder_power.py`, `test_s5_pwr1_remediation.py`, `test_s4_mechanisms.py`, `test_a43_signal_integrity.py`, `test_a45_setup_diagnostics.py`, `test_a46_trade_geometry.py` and `test_a47_execution_realism.py`.
- **No caches:** no test run wrote bytecode or cache files into the worktree.

## Determinism and reproducibility

- **Digest:** replays are compared by sha256 of the canonical record (`research.data_governance.governance.canonical_hash`).
- **Process independence:** for both the clean and the rough scenario, the digest is identical:
  - in-process;
  - in fresh interpreters with `PYTHONHASHSEED` 0 and 4242;
  - under a hostile ambient decimal context: precision 3, lower-case exponents, and a `DefaultContext` with `Emax = 3`.
- **Cadence independence:** daily, weekly and every-third-day snapshot cadences give the same digest. This was checked on three data cases that never deliver a candle late:
  - the clean path;
  - permanent losses that force a Thursday fill, a minimum-order rejection and dust;
  - permanent losses that force an expiry.
- **Interrupted replays** resumed from the saved state give the same digest as uninterrupted ones.

## Breakage check (mutation testing)

Method:
1. Each safeguard below was broken by one source edit.
2. The Design A suite was run against the broken code.
3. The original file was restored, and its sha256 verified.

**Result: 44 of 44 breakages caught.**

`decision.py`:
- equality counts as LONG
- warm-up after decisions

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

## Reviews

There were three reviewer rounds in the same session:
- the code and tests against the brief;
- the specification against the brief and the cited repository files;
- a focused re-review of the fixes.

They are a quality check, **not** independent approval. The rounds found no BLOCKER after the first. Every BLOCKER or MAJOR finding was resolved. Findings and resolutions are listed in the specification, §23 (X1–X16, R1–R13).

## Not uploaded or not done, and why

| Item | Reason |
|---|---|
| CI | Pushes to `feature/*` trigger no workflow, and GitHub Actions is billing-blocked. No CI result is claimed. |
| LCE | Not authorized for this work; not run. |
| The breakage-check script | A local scratch tool that rewrites package files in place, so it does not belong in the repository. The list above is the reviewable record. |
| Revision detection across replay calls | Not implemented: a known limitation, pinned by a test. A minimal durable mechanism is proposed in the specification, §5, for owner approval. |
| Reviewer transcripts | Session-local. Their findings and resolutions are summarized in the specification, §23. |
| A29–A34 texts | Not in this repository (commit `54a6369`, OD-1/OD-2), so "consistent with A29" could not be checked. |
| Market data, protected data, telemetry, runtime logs | None were used, so none exist to upload. |
