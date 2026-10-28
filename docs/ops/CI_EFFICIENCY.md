# CI efficiency: GitHub Actions consumption audit and changes (Workstream C, 2026-10-24)

Branch `ci/actions-efficiency` (from `origin/main` at `ef3d735`). Draft for owner review; not pushed by the agent.
Nothing in this document changed billing, spending limits, branch protection, rulesets, repository settings or
secrets, and no workflow run was triggered, re-run or cancelled. All GitHub data below came from read-only GET calls.

## 1. Method

- Runs: `GET /repos/baljadrawy/trading-signal-bot/actions/runs?created=2026-10-01..2026-10-24` (paginated):
  **337 runs**. The first run in the window was created on 2026-10-15; nothing ran on 2026-10-01..14.
- Jobs: `GET .../actions/runs/{id}/attempts/{n}/jobs` for every attempt `n = 1..run_attempt` (761 job records).
- Billable minutes per job = `ceil((completed_at - started_at) / 60 s)` (GitHub rounds each Linux job up to the
  whole minute). Jobs that never started (no runner and no steps) are 0. That covers the 72 jobs refused for
  billing on 2026-10-23/24 and 2 jobs cancelled before start on 2026-10-16.
- Cross-check: `GET .../actions/runs/{id}/timing` for 25 sampled runs returned `billable.UBUNTU.total_ms = 0`
  for every run with jobs, so it cannot confirm anything. The per-job method is the only one available.
- Changed files per run: a mirror clone in the scratchpad. For pull_request runs: merge-base of (base branch tip
  at run creation, head SHA) to head. For push runs: the previous push on the same branch to head (first parent
  when that was not an ancestor). 328 of 337 runs resolved; the other 9 (3 missing SHAs, 6 zero-job runs) are
  treated as "must run" in every replay.
- Savings are estimated by **replaying the October runs** against each rule, using the same ceil-per-job billing.
  A skipped job is still charged 1 minute, because the job starts, runs the detection step and reports.

## 2. Audit results

### 2.1 Runs by workflow and event

| workflow | event | runs | billable min |
|---|---|---:|---:|
| tests | pull_request | 108 | 1,782 |
| tests | push | 65 (main 38, develop 21, integration/** 6) | 932 (main 806, develop 79, integration 47) |
| tests | workflow_dispatch | 2 | 14 |
| r14-build-readiness | pull_request | 81 | 69 |
| r14-lock-review | pull_request | 77 | 65 |
| r14-* manual (4 workflows) | workflow_dispatch | 4 | 8 |
| **total** | | **337** | **2,870** |

These counts match the owner's preliminary figures (108 / 65 / 81 / 77). "Manual 6" is 4 r14 runs plus 2 `tests`
dispatches. The total of **2,870 billable minutes** is 1.1 % above the owner's ~2,838 for October. Raw job wall
time is 2,424 min, so rounding up per job adds 446 min (16 %). On 3,000 included minutes shared across repositories,
this repository alone used about 96 %. Every job from 2026-10-23 on was refused (0 min).

### 2.2 By job (all events)

| workflow / job | jobs started | billable | avg min | p95 min | share |
|---|---:|---:|---:|---:|---:|
| tests / P2 forward collector suite (p2_forward/tests) | 132 | 1,463 | 10.55 | 11.75 | 51.0 % |
| tests / disposable-PostgreSQL matrix | 153 | 710 | 4.14 | 4.82 | 24.7 % |
| tests / default suite (no database) | 153 | 448 | 2.27 | 2.70 | 15.6 % |
| tests / R1.4 static parity inventory | 107 | 107 | 0.20 | 0.27 | 3.7 % |
| r14-build-readiness / preflight | 69 | 69 | 0.20 | 0.25 | 2.4 % |
| r14-lock-review / verify | 65 | 65 | 0.20 | 0.27 | 2.3 % |
| r14 manual jobs (8) | 8 | 8 | 0.3 | | 0.3 % |

Per event: the collector suite costs 973 min on PRs and 490 on pushes, the PostgreSQL matrix 450 / 251 (+9 manual), and
the default suite 286 / 157 (+5 manual). Longest October jobs: default 3.1 min, PostgreSQL 5.8, collector 11.8.
No job ran away.

Where the time goes inside jobs (successful runs, average):

- collector: `pytest` 656 s; the install takes only 7 s.
- PostgreSQL: full suite 168 s, `pip install` 42 s, service container 16 s, A39 9 s, p1fix 5 s, schema build 4 s,
  reference worktrees 2 s.
- default: `pytest` 81 s, `pip install` 42 s, setup-python 9 s. That 9 s includes restoring the 646 MB pip
  cache, which was already enabled. The install still took 42 s.

All runners are `ubuntu-24.04`, the standard 2-vCPU Linux runner for private repositories and the cheapest
hosted runner. ARM and larger runners would cost more per minute. There is no matrix: "disposable-PostgreSQL
matrix" is a single job.

### 2.3 Retries, cancellations, failures

- Retries (`run_attempt > 1`): 3 runs (two pull_request, one push to main). Re-attempts cost **81 min** (2.8 %).
  Each one re-ran the whole `tests` set (about 20 min) and was a manual re-run.
- Cancelled runs: 29, **133 min**. Of these, 11 were superseded PR pushes (94 min). 17 were develop merge trains on
  2026-10-16/18, mostly cancelled before any job started (39 min for develop and main). 1 was a main push (15 min).
- Failed runs: 43, of which 36 are billing refusals at 0 min. The 7 billed failures cost 86 min, including the
  third attempt of a retried run.

### 2.4 Duplicate or unnecessary execution

| pattern | October finding | billable affected |
|---|---|---:|
| same head SHA tested by both push and pull_request | **0 SHAs**. integration/** pushes never coincided with a PR head | 0 |
| same SHA tested by several PR runs (excluding retries) | 0 | 0 |
| push to main re-tests a tree already tested by a successful PR run (merge commit whose second parent is the PR head, tested against the same main tip) | 21 of 38 main pushes | 435 |
| doc-only PRs (every changed path is `docs/**.md`) still run every suite | 24 PR runs | 355 (collector 194, PostgreSQL 91, default 56, parity 14) |
| collector suite on diffs touching no collector input (conservative input set, §3 C2) | 44 of 100 PR/integration collector jobs | 442 (398 after keeping 1 min per job) |
| r14-lock-review on diffs touching none of its inputs | 57 of 65 started | 57 |
| r14-build-readiness on diffs touching none of its inputs | 57 of 69 started | 57 |
| the r14 pytest files and `tests/test_parity_inventory.py` also run in the required default suite | every PR to main | (duplicated test work; jobs are under 1 min) |
| the PostgreSQL job re-runs every non-database test that the default suite already ran (`pytest tests` with DSNs set) | every run | about 80 s per job (206 min if removed) |

PR churn: 108 PR runs over 57 PR branches (up to 7 per branch). `cancel-in-progress` was already active for PRs,
so superseded pushes were cut short. Their residual cost is the 94 min above.

### 2.5 Biggest cost drivers

1. **Collector suite runtime**: 656 s of `pytest` on every PR and every push, whatever changed. It is 51 % of all minutes.
2. **Post-merge pushes to main**: 806 min (28 %). 21 of 38 re-tested a tree that the PR had already tested green.
3. **The PostgreSQL job runs the full suite**, which repeats the default suite's non-DB tests, plus 42 s of `pip install`.
4. **Per-job rounding**: the four 0.2-min jobs (parity, preflight, verify) bill 1 min each, 241 min in total for
   about 50 min of work.

### 2.6 Workflow definitions (origin/main `ef3d735`)

- `tests.yml`: push to `integration/**`, `develop`, `main`; pull_request to `develop`, `main`; workflow_dispatch.
  No path filters. `permissions: contents: read`. Concurrency `tests-${{ github.ref }}` with
  `cancel-in-progress: true`. Each PR (`refs/pull/N/merge`) and each branch had its own group, **so pushes to
  main were also cancellable.** Four jobs, no `needs`:
  - `unit`: setup-python 3.12 with `cache: pip`; `pip install -r .github/ci/requirements-test.txt` (65 pins);
    `pytest tests`. Timeout 30.
  - `database`: `postgres:16.15-alpine` service, `fetch-depth: 0`, the same pip install, read-only worktrees of
    `f973cac`, `da256f7`, `5929730` and the a38 branch, `build_schema_template.sh`, full `pytest tests` with DSNs,
    then the p1fix and A39 steps. Timeout 45.
  - `collector`: `fetch-depth: 0` (archives `cd2935e`), presence check, setup-python with no cache,
    `pip install --no-deps --only-binary` of `p2_forward/requirements.txt` plus the pytest pin,
    `pytest tests` in `p2_forward`. Timeout 40.
  - `parity-inventory`: static inventory assertion plus `tests/test_parity_inventory.py`. Timeout 5.
- `r14-build-readiness.yml` and `r14-lock-review.yml`: pull_request to `main` plus manual. No path filters and no
  concurrency. Each installs pytest and runs one test file. Timeout 5.
- `r14-analyzer-isolated-install`, `r14-analyzer-ta-wheel-diagnostic`, `r14-disposable-lock-candidates`
  (5-service matrix), `r14-ta-cross-run-provenance` (2-attempt matrix), `r14-ta-wheel-reproducibility`: manual only,
  with timeouts of 15 to 20 min. Their total cost is negligible (8 min).
- Branch protection: `GET .../branches/main/protection` returns "Branch not protected" and `GET .../rulesets`
  returns `[]`. The three required checks are recorded in `docs/ops/BRANCH_RELEASE_POLICY.md` section 8 and are
  treated as required here. Their names are preserved exactly.

## 3. Changes on this branch

| id | change | October replay saving | estimated range |
|---|---|---:|---:|
| C1 | `tests.yml` concurrency: main runs get a unique group (the run id) and `cancel-in-progress: false`, so they are never cancelled or replaced while pending. PRs, develop and integration branches still cancel superseded runs | -6 (one main run cancelled at 15 min would have finished at about 21) | 0 to -21 per extra superseded main merge |
| C2 | collector job: a change-scope step skips the suite's work when nothing it depends on changed | 398 (13.9 %) | 300-450 (10-16 %) |
| C3 | r14-lock-review and r14-build-readiness: pull_request `paths:` filters on their inputs, plus per-PR concurrency | 114 (4.0 %) | 90-120 (3-4 %) |
| C4 | default and PostgreSQL jobs: cached virtualenv of the pinned test set instead of the pip download cache; **restored on every event, saved only from a push to main on a miss** (rev 2) | **revised after measurement (§8): about 90; low confidence** | **30-160 (1-5.6 %)** |
| C5 | timeouts 30/45/40 → 15/20/25 (default/PostgreSQL/collector), still 2-5x the October maximum | 0 (no runaway in October) | caps a hung job at 15-25 min |
| T | `tests/test_ci_workflows.py`: offline guards (§5) | n/a | n/a |

**Implemented total (revised 2026-10-24 after the GitHub measurements in §8): about 410-720 min of 2,870 (14-25 %), central estimate about 590 (about 20 %).** C2, the collector skip, carries most of it and was demonstrated on GitHub. C4 is small and uncertain. The first estimate (24-27 %) assumed a 25-45 s cache saving on every job; measured hits save 25-40 s, misses cost extra, and per-minute rounding converts only part of a sub-minute saving into billed minutes.

### C2 details: change detection inside the required collector job

- The job, its id `collector` and its check name `P2 forward collector suite (p2_forward/tests)` are unchanged.
  It has no job-level `if:`, so it always runs and reports a status on every PR.
- The new step `change scope (collector inputs)` runs `.github/ci/change_scope.py collector`. The existing
  presence check now also needs `run=true` from it. When the scope says no, the step summary records
  "no collector input changed" and the job succeeds without running pytest.
- **The suite runs if any changed path matches** `p2_forward/`, `.github/` (both workflows and `.github/ci`, the
  script included), `tests/`, `shared/`, any `requirements*` / `constraints*` / `*.lock`, any `conftest.py`, or
  root `pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini` or `.python-version`. Pytest looks in parent
  directories for its rootdir configuration, which is why the root files are on the list.
- **It always runs fully for** pushes to `main` or `develop`, `workflow_dispatch`, an unreachable head, a missing
  `origin/main` (no merge-base), an empty diff, any git error, and any script output other than exactly `run=false`.
- The diff is the PR's own changes (`base...head`, from the event's base and head SHAs) or, for a push to a
  non-protected branch, the **branch's complete change since its merge-base with `origin/main`**. It uses
  `--no-renames`, so a file renamed out of `p2_forward/` still counts as a `p2_forward/` change.
- **Correction (rev 2, found in the GitHub scenario runs, §8):** the first version diffed a push from
  `event.before`. When concurrency cancels the run of the previous push, a later docs-only push would then skip a
  collector change that no run ever tested. A regression test now pins the merge-base semantics.
- The PR diff covers the PR's own changes, while the tests run on GitHub's merge commit. The merged tree's
  collector code equals `main`'s plus the PR's changes, and `main`'s collector code is fully tested on every
  `main` push.
- Why the input set is sound: `p2_forward/tests` imports only `p2_forward/` (package, `ops/`, `verifier/`,
  `tests/`). It reads git history only at the fixed commit `cd2935e`, and installs `p2_forward/requirements.txt`
  plus the pytest pin from `.github/ci/requirements-test.txt`. `tests/` and `shared/` are not dependencies.
  They are on the list only because the owner's conservative rule names them.
- Main is not covered by the skip. After any merge, the full collector suite still runs on `main`.

### C3 details

These workflows are not required checks. Their pytest files also run in the required default suite on every PR.
The paths are `.github/**`, `ops/provenance/**`, `tests/test_r14_*`, `**/conftest.py`, `**/requirements*`,
`**/constraints*`, `**/*.lock`, `**/pytest.ini`, `**/pyproject.toml`, `**/setup.cfg` and `**/tox.ini`.
build-readiness also has `<service>/Dockerfile*` for the five services, because `build_preflight.check` reads each
service's `Dockerfile` and `requirements.lock`. GitHub caveat: when a PR changes more than 300 files, a path filter
may not trigger. That is acceptable for non-required checks, and `workflow_dispatch` remains.

### C4 details

The key is `ci-venv-v1-<os>-<arch>-<ImageOS>-<ImageVersion>-py<exact version>-<hash of requirements-test.txt>`.
The image id is read in a shell step because runner environment variables are not in the `env` expression context.
`pip install -r` still runs against the restored virtualenv: a no-op when every exact pin is satisfied, a full
install on a miss. Each new runner image or requirements change causes one miss per cache scope. The
`pip cache` option of setup-python was removed, because restoring both caches would add time. The estimate
assumes restore plus the no-op install saves 25-45 s against the measured 42 s install plus 9 s cache restore.
Restoring a virtualenv (probably larger than 646 MB) has **not been measured**.

## 4. Evaluated but not implemented (owner decisions)

| option | October replay | why not implemented |
|---|---:|---|
| narrow the collector inputs to `p2_forward/`, `.github/`, requirements, conftest and pytest config (drop `tests/` and `shared/`) | +187 (585 instead of 398) | the owner's conservative rule names `tests/` and `shared/` |
| also skip the collector work on main/develop pushes when no collector input changed | +210 | removes post-merge verification on main and the detection of runner-image drift |
| skip a main push run when its tree was already tested green by the PR (21 of 38 in October) | up to 435 | needs API reads inside the job and drops the main-branch evidence the policy relies on |
| PostgreSQL job runs only the tests that need a database, instead of the full suite again | about 206 | changes the composition of a required gate; non-DB tests would no longer run with DSNs set |
| skip the default and PostgreSQL work on `docs/**.md`-only PRs | about 147 | `tests/test_s5_pwr1_remediation.py` reads `docs/strategy/*.md`; other tests scan the tree. A safe rule needs a per-file reference check |
| merge the 0.2-min jobs (parity inventory, r14 preflight, r14 verify) into one job | up to about 100 after C3 | parity in a required job would make it blocking; separate check names would disappear |
| skip duplicate push+PR runs on integration branches | 0 | no duplicate SHA occurred in October |
| pytest-xdist or splitting the collector suite | unknown | split jobs bill more (per-job rounding). xdist adds a dependency outside the collector pin set; timing not measured |
| not running CI on Draft PRs | not measured | 14 of 71 PRs since 2026-10-15 are drafts; the owner uses draft CI as evidence |

## 5. The 40 % target

40 % of 2,870 is 1,148 min. The conservative set implemented here reaches **about 24-27 %** on the October mix
(682-786 min), or 20-30 % for other mixes. **40 % is not reached** without at least one of the §4 owner
decisions. For example, adding narrow collector inputs (+187) and skipping the collector on main when unaffected
(+210) gives 1,079-1,183 min (38-41 %). Adding the PostgreSQL non-DB de-duplication (+206) instead of the main
skip gives 1,075-1,179 min (37-41 %). Each of these trades verification for minutes and is the owner's choice.
Fewer pushes per PR (108 runs over 57 branches) and fewer manual re-runs (81 min) also lower consumption,
without any CI change.

## 6. Risks

- C2: a future collector test that starts importing code outside `p2_forward/` would not trigger the suite on a
  PR that changes only that code. Mitigation: main always runs the full suite, and `tests/` / `shared/` are
  already inputs. Anyone adding such a dependency must extend `SCOPES["collector"]` (a test pins the decision logic).
- C1: a merge train on `main` now tests every merge commit (about 21 min each) instead of only the newest.
- C4: a corrupted or stale virtualenv cache. The key covers runner image, arch, exact Python and the requirements
  hash. `pip install -r` re-verifies the pins, and bumping `v1` in the key discards all entries. It is in its own
  commit (`ci: cache the pinned test virtualenv ...`) so it can be dropped independently.
- C5: an abnormally slow runner could hit the tighter timeouts (collector 25 min against an 11.8 min maximum).
- C3: the 300-file path-filter limit described above.
- C4 (rev 2): a pull-request run never writes a cache entry. It restores `main`'s entry, so until the first `main`
  push after the merge saves one, PR jobs miss and pay the uncached install (about 60 s against the old 36-46 s
  pip-cached install). Every runner image version gets its own entry, and one run was observed with jobs on two
  image versions, so expect one miss per image rollout on `main`. Entries are about 617 MiB, and the repository
  cache is limited to 10 GB with LRU eviction.
- **Required checks are not enforced by GitHub today.** `main` has no branch protection or ruleset, so the three
  required checks exist only in `BRANCH_RELEASE_POLICY.md` and can be bypassed by merging. Enforcement needs the
  separate, owner-approved PR #90. Independently of protection, a PR can edit its own workflow or
  `change_scope.py`, and its run uses the PR's version. Review of any `.github/` change is the control.
- Pre-existing flaky test (not caused by this PR): `tests/test_evidence_v2_pit.py::test_pit_block_is_purely_additive`
  builds klines anchored to the wall clock, so a run that crosses a 15-minute boundary compares different windows.
  It failed once in the scenario runs (06:15Z boundary) and passed on re-running only the failed job. Fixing it
  (a frozen clock) belongs in a separate test PR.

## 7. Validation done and not possible

Done (offline):
- `yaml.safe_load` on all 8 workflows passes. `actionlint` 1.7.12 (via `actionlint-py`) reports no findings,
  with shellcheck not installed.
- `tests/test_ci_workflows.py` (32 tests in rev 2) checks that:
  - the three required names each exist exactly once;
  - required jobs have no job-level `if`/`needs`;
  - `tests.yml` has pull_request and push triggers and no workflow path filters;
  - concurrency never cancels main;
  - every job in every workflow has a timeout;
  - the collector job keeps the full pytest command behind the fail-safe scope step;
  - the r14 filters include their inputs and the virtualenv key covers Python, image and requirements;
  - `change_scope.py` decides correctly on pure path lists and end to end on a temporary git repo: PR doc-only
    skips, collector change runs, rename out of the component runs, and main, develop, manual, new-branch,
    unknown-commit, empty-diff and force-push cases all run.
- Mutation checks confirmed that the guards fail when: `cancel-in-progress: true` is restored, a required name is
  renamed, a timeout is removed, a job-level `if` is added, or a workflow path filter is added to `tests.yml`.
- Local default suite (no database) on this branch: 1,358 passed, 848 skipped, 1 failed. The failure is
  `test_aiohttp_314_compat::test_version`, environmental: the local virtualenv has aiohttp 3.13.5, CI pins 3.14.3.

**Could not be verified when first written (Actions billing-blocked since 2026-10-23). §8 records what has since been measured on GitHub:**
- **None of the workflow changes has run on GitHub.** That covers whether
  `github.event.pull_request.base.sha`/`head.sha` are present in the `fetch-depth: 0` checkout, as expected, and
  the step output wiring.
- The virtualenv cache: entry size, restore time, and the real saving per job.
- The concurrency expressions' live behaviour: a main push not cancelled, superseded PR runs cancelled.
- Path-filter behaviour of the r14 workflows on real PRs.
- That a skipped collector run satisfies the required check in the PR UI. It should, since the job concludes
  `success`, but this is unobserved. Branch protection is not readable as enabled (§2.6).

Suggested first check once billing is restored: one doc-only PR (expect collector `success` in about 1 min with the
skip summary line), one PR touching `p2_forward/` (expect the full suite), then the merge push to main (expect the
full suite, not cancelled). Compare the default and PostgreSQL job durations with §2.2.

## 8. Measured verification on GitHub (2026-10-24, billing restored)

**Method:** read-only API reads of job and step timings and job logs. Scenario runs used a scratch branch,
`integration/ci-scenarios-92`, which is never merged. Every billed figure below rounds each job up to the minute.

| run | event / change | collector decision | jobs (conclusion, duration) | billable |
|---|---|---|---|---:|
| 40047646992 (PR #92 head `0d19140`) | pull_request, `.github/` changed | RUN (`.github/ci/change_scope.py` matches `^\.github/`) | default success 178 s, PostgreSQL success 296 s, collector success 701 s, parity success 12 s | 21 |
| 40068345141 (scratch, new branch at `0d19140`) | push, new branch | RUN (fail-safe: no usable `before`) | default 158 s, PostgreSQL 299 s, collector 710 s, parity 12 s; both caches **miss** and saved | 21 |
| 40069182684 (scratch, docs-only commit) | push, one file under `docs/` | **SKIP**: collector job success in **7 s** | default 125 s; PostgreSQL 298 s **failure** (pre-existing clock flake, §6) then re-run of the failed job only: success 247 s; parity 9 s; both caches **hit** | 10 (+5 re-run) |
| 40069915688 (scratch, collector probe A) | push | n/a: **cancelled** when B was pushed | parity success 10 s; default, PostgreSQL and collector **cancelled** after about 90 s | 7 |
| 40069968792 (scratch, collector probe B) | push, `p2_forward/` file changed | **RUN** (matches `^p2_forward/`) | default 110 s, PostgreSQL 246 s, collector 699 s, parity 12 s, all success; caches **hit** | 20 |

**Every required job reported a conclusion in every scenario.** A skipped collector reports `success`.

**Environment setup per job (measured, step level):**

| case | steps | seconds |
|---|---|---:|
| old pip cache (6 `main` runs before this PR) | setup-python 7-12 + `pip install` 36-46 | 45-56 |
| virtualenv cache hit | setup-python about 0 + restore 10-18 (one outlier at 57) + no-op install 2-5 + post 0-1 | 13-24 typical, 60 worst seen |
| virtualenv cache miss (first version, PR scope saved) | install 57-60 + save 11 | 68-71 |
| virtualenv cache miss (rev 2, PR: no save) | install 57-60 | 57-60 |

**Observed savings against a full run (21-22 billable min on main before this PR):**
- a docs-only change costs **10 min**, about 52 % less;
- a collector change with cache hits costs **20 min**, 1-2 min less.

These are single observations, not an average. The October-wide saving in §3 remains an estimate.

**Rev 2 PR run** (run 40071011034, head `0351e9c`):
- all four jobs succeeded and the collector ran;
- the cache was restored from this PR's earlier entry, and **`actions/cache/save` was skipped**, as designed;
- restore took 17 s in PostgreSQL and **57 s** in default. One restore of the about 617 MiB entry was as slow as the old install.

**C4 revert criterion.** C4 is in separate commits and can be dropped without touching C1–C3. Over the first 20 default and PostgreSQL jobs after the merge, compute the mean setup time: restore plus install, plus save where one happens. If it is not at least 15 s below the old 45–56 s, revert C4 to `setup-python` `cache: pip`. Measured so far, hits average about 26 s, about 20 s better than before. That is a modest saving, not yet a proven one.

**Not verifiable without merging or changing `main`:**
- live `main` behaviour (never cancelled, full collector run);
- `main`'s cache save;
- the r14 path filters skipping on a real PR, since any PR against `main` carries this PR's own `.github/` changes.

These are covered by the offline tests (`tests/test_ci_workflows.py`). Check them on the first PRs after the merge.

**Concurrency semantics:**
- **observed:** the cancellation of a superseded non-`main` run;
- **static, by test:** `main`'s unique group with `cancel-in-progress: false`.

## 9. Independent audit, 2026-10-24: P2 findings and dispositions

The external audit of head `ff8e8da` returned **PASS**, with no P0 or P1 findings and five non-blocking P2 findings. This revision changes only what those findings require.

| id | finding | disposition |
|---|---|---|
| P2-1 | The PR title and description stated 24–27 % as if it were a saving | **Fixed** (PR metadata). The figure is an **estimate**, 14–25 % with a central value of about 20 % (§3). It is not a measured monthly saving. The only measured savings are the single-run observations in §8. |
| P2-2 | Unused `ZERO` regex in `.github/ci/change_scope.py` (left over from the old `event.before` logic) | **Fixed**: removed. No behaviour change. The tests are unchanged and pass. |
| P2-3 | Self-referential PR workflow: a pull-request run executes the PR's own `tests.yml` and `change_scope.py`, so a PR can weaken or skip its own checks | **Accepted, documented.** Branch protection (#90) does not remove it. With a single account, CODEOWNERS cannot enforce a second reviewer. Controls: (1) review of every `.github/` diff before merge (§8 of `BRANCH_RELEASE_POLICY.md`); (2) after a merge, every `main` push runs `main`'s workflow in full, with no skip on protected refs. |
| P2-4 | Cache-save race: two `main` pushes that both miss the same key may both try `actions/cache/save` | **Accepted, documented.** The entries are identical, because the key covers image, arch, exact Python and the requirements hash. The second save cannot reserve an existing key. `actions/cache/save` reports that as a warning and does not fail the job (to be confirmed on the first concurrent `main` pushes, P2-5). The cost is one redundant upload attempt, about 11 s. There is no correctness impact. |
| P2-5 | Post-merge verification is still outstanding | **Plan (owner, after merge):** |

**P2-5 checks, after merge:**
1. **First `main` push:**
   - the full collector suite runs, `RUN (push to protected branch)`;
   - the run is not cancelled;
   - the venv cache is saved once.
2. **First docs-only PR:**
   - the collector reports success in about 10 s, with the skip summary;
   - the cache is restored from `main`'s scope, and save is `skipped`;
   - the r14 workflows do not start.
3. **First PR touching `p2_forward/`:** the collector suite runs in full.
4. **Superseded PR push:** the earlier run is cancelled.
5. **Revert test for C4 (§8), over the first 20 default and PostgreSQL jobs:** if the mean setup time is not at least 15 s below 45–56 s, revert C4 to `setup-python` `cache: pip`.
6. **Measured saving:** compare November's billable minutes per run type (docs-only, collector-change, `main` push) against §2. Only then can a measured monthly saving be stated.

## 10. Read-only review under the cost-governance directive (2026-10-28; nothing implemented)

Directive: `docs/governance/OWNER_OPERATING_CONTRACT.md` §8. Data: read-only `GET .../actions/runs` from 2026-10-24.
No workflow, trigger, setting, billing or protection was changed and no run was triggered for this review.

### 10.1 Observations

- 65 runs since 2026-10-24: `tests` push 26, `tests` pull_request 25, `r14-build-readiness` 7, `r14-lock-review` 7.
- 45 distinct SHAs ran `tests`; 5 ran more than once: 3 as push + push (the same SHA pushed to `integration/**` and
  then fast-forwarded into `main`), 1 as pull_request + push + push, 1 as pull_request + push.
- Since 2026-10-27 about 17:00Z every job is refused before start (billing); those runs bill 0 minutes but give no
  evidence, so the dependent gates are on HOLD (Retry Guard `ea2e9f4`).
- October baseline (§2): `main` push runs were 806 of 2,870 billable minutes (28 %); pull_request runs 1,782 (62 %).

### 10.2 Opportunities (each needs a documented impact assessment and owner approval before any change)

| id | opportunity | expected effect | main risk / cost |
|---|---|---|---|
| O1 | Skip the `main` push re-run when the exact SHA already passed all required checks on `integration/**` (check-runs of app 15368 on that SHA) | up to the `main` push share (about 28 % in October) | removes the post-integration safety net; the C2 rule "main always runs the full collector suite" would change |
| O2 | Avoid pull_request + push double runs for `integration/**` heads (PR-on-demand already; or no pull_request trigger when the head is an integration branch) | most of the 62 % pull_request share for PR-based work | a PR's merge-commit test differs from the head test when `main` moved; must stay for on-demand PRs |
| O3 | Fold the 0.2-minute `parity-inventory` job into the default job and merge the two 0.2-minute r14 PR workflows (per-job 1-minute rounding) | about 107 + 65 min per October-like month | changes required check names (branch-protection proposal, `tests/test_ci_workflows.py`) |
| O4 | Docs-only change scope for the default and PostgreSQL jobs | small | many tests read documentation; needs a tested path map; low priority |
| O5 | Local CI-equivalent evidence (LCE), below | lets D0 work proceed when Actions is unavailable or not worth the cost | substitution of a mandatory gate needs owner approval |

### 10.3 Proposal O5: local CI-equivalent evidence (LCE) — NOT APPROVED, not in force

- Runner: a script (to be written and reviewed) that checks out the exact SHA in a clean throwaway `git worktree`,
  builds a virtualenv from `.github/ci/requirements-test.txt` (hash recorded), and runs the same commands as the
  `tests.yml` jobs: default suite, database suite (schema template from `.github/ci/build_schema_template.sh` and the
  same reference trees), collector suite and parity inventory.
- Evidence (SHA-bound): `~/ops/ci-evidence/<sha>/` with the commands, interpreter version, requirements hash,
  pass/fail/skip counts, full logs and their sha256; summarised in the commit or review note.
- Environment parity matters: run with `umask 022` (the hosted runner's default) and the collector suite from
  `p2_forward/`, as `tests.yml` does. A trial run on 2026-10-28 under `umask 077` failed one collector test
  (`test_p2f_ack_recovery`, file mode 0o400 instead of 0o444) that passes under `umask 022`.
- Disposable PostgreSQL: this host has no PostgreSQL binaries outside containers. Options for owner decision:
  (a) a throwaway container from the already-present `postgres:16.15-alpine3.24` image (no pull), `--rm`, no mount of
  any production path, port bound to 127.0.0.1, CPU and memory caps, removed after the run; (b) PostgreSQL 16 client
  and server packages on the host (system change). Never the shared production `postgres`.
- Substitution rule: LCE may stand in for a named GitHub-hosted check only after owner approval of that substitution;
  the reviewer accepts it on the evidence (or re-runs it). Until approved, BRANCH_RELEASE_POLICY §3 and the required
  checks apply unchanged.
