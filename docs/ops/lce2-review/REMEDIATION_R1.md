# LCE-2 review: remediation R1 (`lce-2.1`)

Independent review verdict on `b078767`: **REQUEST_CHANGES**. This is the author's response; it needs re-review.
Changed: `ops/ci/lce.py` (`RUNNER_VERSION = 'lce-2.1'`), `tests/test_lce_runner.py`, `docs/ops/CI_EFFICIENCY.md` §11.
Unchanged: the workflow pins (`REVIEWED_WORKFLOW_SHA256`, `REVIEWED_JOB_SHA256`), the four jobs, the DSN guard and
the disposable-PostgreSQL isolation, the scientific-data restrictions, and the MERGE_COMMIT fast-forward semantics.
LCE was **not executed**; all evidence below is offline.

## Finding 1: child processes after timeouts and interruptions. FIXED
Before:
- A step ran through `subprocess.run(timeout=…)`, which kills only `bash`; pytest, pip and `docker exec` children
  survived.
- Helper commands (docker, git) had no timeout.
- SIGTERM or SIGHUP ended Python without running the `finally` cleanup.

Now:
- **Steps and helper commands run in their own session and process group** (`run_group`, `start_new_session=True`).
- **On a timeout, an exception or an interruption the whole group is terminated** (`terminate_group`): SIGTERM to the
  group and its scope, then SIGKILL after 10 s. The group must be gone; otherwise `processes:<scope>` is a residue and
  the run fails. Processes left by a step that exited normally are terminated too, as GitHub does with orphans.
- **Helper commands are bounded at 600 s** (`run(timeout=CMD_TIMEOUT_S)`); a timeout is refused.
- **Interruptions are routed into cleanup.** `main()` turns SIGINT, SIGTERM and SIGHUP into `Interrupted` once; later
  signals are ignored, so cleanup and evidence finish. `go()` records `interrupted: …`, cleans up and returns FAIL;
  the exit code is 130.
- **Termination is reported** in the step record (`termination`: cause, signals, `group_gone`, errors), and step logs
  are redacted when evidence is written, so an interrupted step cannot leave an unredacted log.

Limit: a SIGKILL of the runner itself cannot be handled. Leftovers are then identifiable only by the run label and
the `lce-*-<run_id>*` scope names.

## Finding 2: cleanup verification and ownership. FIXED
- **Containers and networks are removed by ID only when they carry this run's label (`tsb.lce.run=<run_id>`) AND the
  exact name.** Nothing is selected by name alone, and nothing outside the run is listed for removal.
- **Only worktrees inside the run's own temporary directory** (from `git worktree list`, exact path containment, not a
  string prefix) are removed. The directory itself is removed only if it is the run's own `mkdtemp` directory
  (`lce-<sha8>-…` directly under the system temp directory); otherwise removal is refused and recorded.
- **Only this run's scopes** (`lce-*-<run_id>*`) are killed.
- **A verification that cannot run is a residue** (`unverifiable:<check>`), never read as "absent". The checks cover:
  name, run label, worktrees, scopes, directory and surviving processes.
- **Every cleanup action is attempted even if an earlier one fails.** Failures are recorded as `cleanup-error:…`, and
  any residue, error or surviving process means `verified: false` and verdict FAIL.

## Finding 3: host-side resource consumption. FIXED (limits confirmed only by the next run)
**Evaluation.** Before, only PostgreSQL was capped (2 CPUs, 1 GiB, 512 pids). The host-side processes were unbounded:
- pytest (one process per suite; no parallel plugin is pinned);
- subprocesses spawned by 15 test files;
- pip installs and venv creation;
- the psql shim.

On this host (12 cores, 23.4 GiB RAM, 4 GiB swap, shared with the Paper services, the shared PostgreSQL, the Collector
and research jobs) that risked CPU contention, swapping and, worst, an out-of-memory kill landing on a production
process. Measured per-step peaks do not exist yet; the old manifests record durations only.

**Limit (smallest safe).** Each `run:` step runs in a transient user scope with these limits, the same mechanism and
property names as the existing research runner (`ops/research/mi_cpuguard`):

| Property | Value | Why |
|---|---|---|
| `CPUQuota` | 200 % | at most 2 cores; with PostgreSQL that is at most about 4 of 12 |
| `CPUWeight` | `idle` | yields to the other user workloads |
| `MemoryMax` | 4G | a runaway test is OOM-killed inside its own scope, not on the host |
| `MemorySwapMax` | 0 | no swapping that slows production |
| `TasksMax` | 512 | caps runaway process creation |

So one LCE run uses at most about 4 cores, 5 GiB and 1024 tasks.

- **Enforcement is verified in preflight.** A probe inside a limited scope must read back the kernel values
  (`cpu.max 200000 100000`, `memory.max 4294967296`, `memory.swap.max 0`, `pids.max 512`); otherwise the run is
  refused. The user manager on this host delegates `cpu memory pids` (cgroup v2, systemd 255).
- **Peak memory, CPU time and peak tasks are recorded for every step**, so the first `lce-2.1` run gives the evidence
  to confirm or adjust these values. Any change needs owner approval.
- **New deviation `HOST_LIMITS`** (portable-with-record): a limit can only slow a step or kill it (FAIL), never pass
  it.
- **Risks:**
  - Under the 2-core cap the Collector job, about 12 minutes uncapped against a 25-minute job timeout, may run
    longer; a timeout is a fail-closed FAIL.
  - Disk I/O is not limited, because the `io` controller is not delegated to the user manager.

## Finding 4: synthetic negative tests. ADDED
In `tests/test_lce_runner.py`: real short-lived processes for the process cases (no Docker, no systemd), fakes for the
rest.
- **Process groups:**
  - a timeout kills the whole group;
  - SIGTERM is escalated to SIGKILL and the scope is signalled;
  - an interruption kills the group before it propagates;
  - leftovers of a finished step are terminated;
  - a helper-command timeout is refused.
- **Host limits:**
  - the scope command carries the limits and only the step environment;
  - the limits stay bounded for a shared host;
  - unenforced limits are refused (5 cases).
- **Cleanup:**
  - only this run's resources are removed;
  - a failed check is a residue;
  - no directory outside the run's base is removed;
  - worktree ownership is exact;
  - a leftover scope is a residue and is killed;
  - surviving step processes fail the run.
- **Run level:**
  - an interrupted run still cleans up and fails;
  - logs are redacted even after an interrupted step.

**Results.**
- **Tests:** 66 passed with PyYAML. In the pinned CI test set: 61 passed and 5 skipped (the YAML-dependent pin checks
  skip there, as on GitHub). Together with `tests/test_ci_workflows.py`: 98 passed.
- **Breakage check:** 8 of 8 deliberate breakages of the new safeguards are caught. They removed, in turn:
  - the process group;
  - the SIGKILL escalation;
  - the interruption handling;
  - "unverifiable is a residue";
  - the ownership label;
  - the base guard;
  - the limit check;
  - surviving-process residues.
- **No leftovers:** the unmodified suite leaves 0 processes behind.

## Finding 5: preserved properties. VERIFIED
- The workflow file pin and the four job pins are unchanged, and their tests pass.
- `JOBS` is unchanged.
- The source guard still passes: no production target, no `-p`/`-v`, no `os.environ`.
- The DSN guard and the isolation checks are unchanged.
- MERGE_COMMIT is unchanged: evidence remains valid only for a fast-forward of the exact SHA.

## Still open for the reviewer
- Whether the `STEP_LIMITS` values are acceptable before measurement.
- The four `requires-verification` deviations (unchanged).
- Owner approval of substitution, then one `lce-2.1` run on the target SHA (for PR #96: `33347be`).
