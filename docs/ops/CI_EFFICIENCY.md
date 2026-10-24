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
| C4 | default and PostgreSQL jobs: cached virtualenv of the pinned test set instead of the pip download cache | 226 (7.9 %) at 35 s saved per job | 170-274 (5.9-9.5 %) for 25-45 s |
| C5 | timeouts 30/45/40 → 15/20/25 (default/PostgreSQL/collector), still 2-5x the October maximum | 0 (no runaway in October) | caps a hung job at 15-25 min |
| T | `tests/test_ci_workflows.py`: offline guards (§5) | n/a | n/a |

**Implemented total: 682-786 min of 2,870 (about 24-27 %). Allowing for a different PR mix, 20-30 %.**

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
- **It always runs fully for** pushes to `main` or `develop`, `workflow_dispatch`, a missing or all-zero `before`
  (a new branch), an unreachable commit, a force push (before is not an ancestor), an empty diff, any git error,
  and any script output other than exactly `run=false`.
- The diff is the PR's own changes (`base...head`, from the event's base and head SHAs) or `before..after` for a
  non-protected push. It uses `--no-renames`, so a file renamed out of `p2_forward/` still counts as a
  `p2_forward/` change.
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

## 7. Validation done and not possible

Done (offline):
- `yaml.safe_load` on all 8 workflows passes. `actionlint` 1.7.12 (via `actionlint-py`) reports no findings,
  with shellcheck not installed.
- `tests/test_ci_workflows.py` (30 tests) checks that:
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

**Could not be verified, because Actions is billing-blocked since 2026-10-23:**
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
