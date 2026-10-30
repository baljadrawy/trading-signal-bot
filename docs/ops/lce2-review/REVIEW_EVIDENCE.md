# LCE-2 independent-review evidence

**Status: AUTHOR-PRODUCED.** The session that wrote the runner assembled this package. Verify every claim against
the sources here and in the repository. Packaging is not independent evidence. LCE was **not** executed to build
this package.

Purpose: let an independent reviewer decide whether `lce-2` may stand in for the four `tests.yml` jobs
(owner contract §9; `docs/ops/CI_EFFICIENCY.md` §10–§11). The first intended use is PR #96 at `33347be`.

## 1. Runner identity and source
| Item | Value |
|---|---|
| Runner | `ops/ci/lce.py` at `f3ade07cd2370d7821638d6fdf3a2d4121e8f241`, blob `c19f1a170ce3…`, sha256 `780f98d983dbae95b02948becdfdf3d69877ffecce7c20468df3976afa36f20d`, 632 lines, `RUNNER_VERSION = 'lce-2'` (L37) |
| Tests | `tests/test_lce_runner.py` at `f3ade07`, blob `7682dfeb09df…`: 22 test functions, 46 cases |
| Lineage | `64bcf47` (`lce-1`, on GitHub) → `cbe6b43` (hardening) → `f3ade07` (pytest-step detection fix). `cbe6b43` and `f3ade07` are **local only**; no GitHub branch contains them. See `git show 64bcf47 cbe6b43 f3ade07` and `git diff 64bcf47 f3ade07 -- ops/ci/lce.py tests/test_lce_runner.py docs/ops/CI_EFFICIENCY.md` |
| Not in PR #96 | `33347be` does not contain `cbe6b43` or `f3ade07`. The runner is run from its own checkout against a target SHA |

## 2. CI workflow equivalence (pins)
- `REVIEWED_WORKFLOW_SHA256 = f30ffb0c…` (L47). `tests.yml` at `33347be` hashes to exactly this value, and its blob
  is identical at `d1184c8`, `f3ade07` and `33347be`. A changed workflow is refused (L109–118, `check_pins`).
- `JOB_HASHES` pin each of the four jobs separately (L41–44).
- `check_uses` (L121) accepts only the actions and services the runner emulates.
- Tests (all pass, `docs/ops/lce2-review/test_lce_runner_synthetic.txt`):
  - `test_reviewed_workflow_file_pin_equals_tests_yml`
  - `test_reviewed_pins_equal_the_current_workflow_jobs`
  - `test_unsupported_workflow_change_is_refused`
  - `test_every_action_and_service_used_by_the_workflow_is_supported`
  - `test_every_expression_the_runner_evaluates_is_supported`
  - `test_expression_semantics_and_fail_closed`

## 3. The four jobs
Taken from the `lce-2` run on `f3ade07` (`docs/ops/lce2-review/evidence_runs.json`, run `lce-20261028T2220Z`).

| Job (`tests.yml`) | Steps executed | Steps emulated (GitHub actions) | Result |
|---|---|---|---|
| `unit`, default suite (no database) | runner image id; pinned install; `pytest tests` | checkout as a clean detached worktree; setup-python as a fresh venv (3.12.3); cache restore as the persistent LCE home | PASS: 1841 passed, 852 skipped, 46 subtests |
| `database`, disposable-PostgreSQL matrix | pinned install; reference trees; `build_schema_template.sh`; full suite with databases; `test_p1fix` on the pre-fix tree; A39 mixed-version suite | same as `unit`; the PostgreSQL service is a disposable container | PASS: 2683 + 18 + 10 passed |
| `collector`, `p2_forward/tests` | change scope; presence check; the collector's exact pinned install; collector tests | checkout, setup-python | PASS: 466 passed |
| `parity-inventory` | legacy-gap inventory; `test_parity_inventory.py` | checkout, setup-python | PASS: 21 passed |

`actions/cache/save` is skipped by its own `if:` condition, as on GitHub. The verdict is fail-closed:
`assess_job` (L193) and `decide_verdict` (L209); refusals or residuals mean FAIL.

## 4. Dependency and environment parity
- **Pinned test set:** `.github/ci/requirements-test.txt` (64 packages). The workflow's own `pip install -r` runs
  every time, and its sha256 (`e9a67dc2…`) is recorded per job.
- **Collector set:** `p2_forward/requirements.txt`, installed with `--no-deps --only-binary`.
- **Python:** 3.12.3 on the host vs the latest 3.12 patch on GitHub (deviation PY_PATCH).
- **Architecture:** aarch64 host vs x86_64 runner (ARCH).
- **PostgreSQL:** the local image `sha256:721873c3…` (Alpine 3.24, arm64) for the workflow tag
  `postgres:16.15-alpine`. The same minor version is enforced (PG_IMAGE). It is the same image as the shared
  production PostgreSQL, but a separate disposable container (§6).
- The environment is built from scratch, not inherited (`step_env`, L169; `test_step_environment_inherits_nothing_from_the_caller`).

## 5. Merge commit versus fast-forward (deviation MERGE_COMMIT, L85–88)
- A `pull_request` run on GitHub tests a merge commit; LCE tests the exact SHA (push semantics).
- **Evidence for `33347be` is valid only for integrating that exact SHA by fast-forward.**
- For PR #96: `33347be`'s only parent is the base `d1184c8`. A GitHub "Create a merge commit" therefore produces a
  new SHA, whose tree equals `33347be`'s tree; it needs its own LCE run under the runner's rule. Squash and rebase
  also produce new SHAs.
- Whether tree identity is enough is the reviewer's decision; the runner does not assume it.

## 6. Test isolation and data-safety boundaries (source references in `ops/ci/lce.py`)
| Control | Where | Test |
|---|---|---|
| Dedicated `--internal` bridge network per run, labelled `tsb.lce=1` | `start_postgres`, L349 | `test_isolation_accepts_the_private_internal_network` |
| Container: `--pull never`, `no-new-privileges`, `--pids-limit 512`, `--tmpfs` data directory, no published port, no mount, no other network | L12, L360–361; `check_isolation`, L126–141 | `test_isolation_failures_are_refused` |
| Database connection strings may target only the disposable server | `check_dsn_targets`, L144 | `test_dsn_guard_refuses_anything_but_the_disposable_server`, `test_dsn_guard_accepts_the_disposable_server` |
| Throw-away values are redacted from logs and evidence | `secrets_of`, L153; `redact`, L163 | `test_throwaway_values_are_redacted` |
| No production target in the source | — | `test_runner_source_never_targets_production` |
| Verified cleanup of containers, networks, worktrees and directories; a leftover makes the run FAIL | `cleanup`, L523–556; `go`, L571–589 | `test_cleanup_is_verified`, `test_cleanup_detects_a_leftover_worktree` |
| Only real pytest invocations count as test steps | `PYTEST_RUN`, L57 | `test_pytest_step_detection_ignores_installs` |

The isolation facts recorded by the `f3ade07` run: `internal: true`, `published_ports: 0`, `mounts: 0`, cleanup
`verified: true`, residuals empty.

**Not isolated:** the run shares the host's Docker daemon, CPU and memory with production. No production database,
volume, network or credential is used.

## 7. Evidence history (`docs/ops/lce2-review/evidence_runs.json`: sanitized summaries, no logs)
| Runner | Runs | Verdict | Note |
|---|---|---|---|
| `lce-1`, sha256 `ff977459…` | `d1184c8`, `ea2e9f4`, `d77166d`, `4ac0c42` | 4 × PASS | Default bridge network and published port; cleanup not verified; superseded |
| intermediate (`cbe6b43`), `159ec8f2…` | `cbe6b43`, `ea2e9f4`, `d77166d`, `4ac0c42` | **4 × FAIL** | A false collector FAIL: the install step's `pytest==` pin was counted as a test step. Fixed in `f3ade07` (L57) |
| `lce-2` (`f3ade07`), `780f98d9…` | `f3ade07`, `b30fb66`, `33c7b68`, `4ac0c42` | 4 × PASS | Cleanup verified on every run |

There is no run on `33347be`.

## 8. Remaining deviations and risks
- **Requires verification:** ARCH, PY_PATCH, HOST_OS, PG_IMAGE (L62–76). PR #96 changes only stdlib Python, tests
  and docs, none of which depends on compiled wheels; the reviewer still decides acceptance per changed component.
- **Not reproduced:** MERGE_COMMIT (§5).
- **Equivalence is not universal:** the runner records `equivalence_scope: not universal: see deviations` (L282).
- **Reviewer access:** `cbe6b43` and `f3ade07` are not on GitHub. Pushing them needs owner authorization. After
  PR #96 merges, the local `integration/paper-vb-a1` (`f3ade07`) is no longer a descendant of the remote branch
  and needs rebasing first.
- **Shared host** (§6), and the run takes about 20 minutes of host CPU.

## 9. Minimum gate for PR #96 (proposed)
1. An independent review of this runner and its equivalence: §§2–8, and a re-run of the 46 synthetic tests.
2. Owner approval of LCE substitution for the four `tests.yml` checks (`CI_EFFICIENCY.md` §10 substitution rule).
3. One `lce-2` run on `33347be` covering all four jobs: verdict PASS, cleanup verified, manifest and checksums kept.
4. Integration that keeps the evidence valid: a fast-forward of `33347be` if the target branch is still at `d1184c8`
   (GitHub then records PR #96 as merged); otherwise an LCE run on the actual merge result.
5. The other PR #96 gates: the independent verdict recorded on the PR; Ready-for-review; explicit merge
   authorization.

## 10. Not uploaded (host only)
- The raw LCE manifests (`~/ops/ci-evidence/<sha>/<run>/manifest.json`) carry second-precision run times and host
  paths, which the repository's protected scan blocks. `evidence_runs.json` gives their content without those
  fields, plus each original's sha256.
- Step logs (`*-stepNN.log`): full test output, which is large and adds nothing beyond the counts. Available on request.
