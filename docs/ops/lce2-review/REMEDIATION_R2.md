# LCE-2 review: remediation R2 (`lce-2.2`)

Re-review R2 of `631ce6f`: **REQUEST_CHANGES (targeted)**; the architecture is provisionally accepted. This is the
author's response and needs independent re-review.

Changed: `ops/ci/lce.py` (`RUNNER_VERSION = 'lce-2.2'`), `tests/test_lce_runner.py`, this document,
`docs/ops/CI_EFFICIENCY.md` (status), `docs/ops/lce2-review/README.md`. Unchanged: the four jobs, the workflow
pins, the isolation and DSN guards, the MERGE_COMMIT semantics, and PR #96. LCE was **not** executed; everything
below is offline evidence.

## 1. `kill_scope()`: absent scope vs real failure. FIXED
- `systemctl --user kill` exit 0 → `signalled`.
- Non-zero exit → `scope_state()` asks `systemctl --user show --property=LoadState,ActiveState`:
  - `LoadState=not-found` → `absent`, which is not an error;
  - `ActiveState=inactive` → `inactive`, which is not an error;
  - anything else (for example `active`) → `Refused`;
  - a failing `show` → `Refused`.
- A `Refused` from the scope signal is recorded in the termination record (`errors`).
- `termination_ok()` counts a step's processes as gone only if the group is gone **and** no scope signal failed;
  otherwise `processes:<scope>` is a residue and the run fails.
- Tests:
  - `test_kill_scope_accepts_an_absent_scope` (3 cases);
  - `test_kill_scope_failure_raises` (2 cases);
  - `test_a_scope_signal_error_counts_as_surviving_processes`.

## 2. Cleanup command failures. FIXED; ownership unchanged
Every command's result is now checked, and each failure is recorded as `cleanup-error:<what>`, which makes the
verdict FAIL:

| Action | Failure handling |
|---|---|
| `docker rm -f <id>` | recorded if the ID is still owned afterwards |
| `docker network rm <id>` | 5 tries, then recorded if still owned |
| `git worktree remove --force <wt>` | recorded if the worktree is still registered |
| `git worktree prune` | always recorded |
| the scope listing and each scope kill | recorded; a failed listing also yields `unverifiable:scopes` |

- A resource that is already gone (for example a container removed by `--rm` in the meantime) is not a failure.
- Ownership is unchanged:
  - IDs come only from a lookup by **this run's label and the exact name**;
  - worktrees are selected only by exact containment in the run's own temporary directory;
  - scopes only by `lce-*-<run_id>*`.
- Tests:
  - `test_failed_container_removal_is_recorded_while_it_still_exists`;
  - `test_failed_removal_of_an_already_absent_resource_is_not_an_error`;
  - `test_failed_network_removal_is_retried_then_recorded`;
  - `test_failed_worktree_commands_are_recorded_and_ownership_stays_exact` (removes only `<base>/ws`, never a
    `<base>-other` sibling or the repository);
  - `test_a_failed_scope_listing_or_kill_is_recorded`.

## 3. Process group and systemd scope: what is guaranteed, and what is not
**What holds** (from how these mechanisms are documented to work; not exercised by the synthetic tests):
- **Every descendant starts inside the limited scope.** `systemd-run --user --scope` asks the user manager to create a
  transient scope containing systemd-run's own PID, then execs the command in place, so no extra process remains.
  Child processes are born in their parent's cgroup, so every descendant starts inside the scope.
- **The limits apply to the scope as a whole.** CPU, memory, swap and tasks are cgroup limits on the scope; they bound
  the sum of all processes in it, not each process separately.
- **Two complementary ways to terminate:**
  - `killpg` reaches every member of the step's process group, even without systemd;
  - `systemctl --user kill` reaches every process in the scope's cgroup (all processes by default), including ones
    that called `setsid()` and left the process group.

**What is not guaranteed (remaining limits):**
1. **Leaving the cgroup.** A process can leave the scope only by migrating itself to another cgroup it may write to.
   In the user's delegated subtree that includes starting a new unit through the user manager (`systemd-run --user`)
   or writing `cgroup.procs`. Mitigations:
   - the step environment has no `XDG_RUNTIME_DIR` and no session bus address (`env -u`), so `systemctl --user` and
     `systemd-run --user` cannot find the manager unless a step sets the variable itself;
   - no test uses `systemd-run`, `systemctl` or `cgroup.procs`.

   This is a mitigation, not a guarantee.
2. **Processes created by the Docker daemon.** These include `docker exec` in the psql shim and any container a step
   starts. They run under dockerd (`system.slice`), outside the scope and its limits. The shim's `psql` runs in the
   disposable PostgreSQL container, which has its own caps and is removed at cleanup. No test starts Docker for real
   (the only `docker` call, in `test_compose_safe.py`, uses a fake binary).
3. **A SIGKILL of the runner** skips all cleanup. The scope keeps its limits until its processes exit; the leftovers
   are identifiable by the run label and the `lce-*-<run_id>*` names.
4. **Process-group number reuse.** After a step's process group is empty, its number could in principle be reused
   before the runner checks it. `terminate_group` signals the group only while it is in use (on a timeout the leader
   is still running), so the window is negligible but not zero.

## 4. Negative tests
- **12 new tests**, 78 in total. Without PyYAML (the pinned CI set), the 5 workflow-parsing tests skip as before.
- **Breakage check:** 6 of 6 deliberate breakages of the R2 fixes are caught:
  - `kill_scope` ignoring failures;
  - an absent scope treated as a failure;
  - a container removal failure ignored;
  - a worktree removal failure ignored;
  - a prune failure ignored;
  - scope-signal errors ignored.
- **No leftovers:** the unmodified suite leaves 0 processes behind.

## 5. Are the cgroup limit checks sufficient?
- **Preflight (unchanged).** A probe started with the same `STEP_LIMITS` reads the kernel's values back:
  `cpu.max 200000 100000`, `memory.max 4294967296`, `memory.swap.max 0`, `pids.max 512`. The run is refused otherwise.
  This proves the limits are **configured** on this host at run time.
- **New per step.** While a step runs, its own scope cgroup's limit files are read back once (`read_scope_limits`) and
  checked. A mismatch makes `limits:<scope>` a residue and fails the run. Every step's manifest records
  `limits_verified` as one of:
  - `True`;
  - `False` (the run fails);
  - `None`: the step finished before its first sample, under 2 s, so its limits were not read back. The preflight
    probe is the evidence for those steps.
- **Not claimed.** The synthetic tests check the logic only: the scope command, the read-back parsing, refusal,
  termination and recording. They do **not** validate that the limits work at run time: CPU throttling, an
  out-of-memory kill confined to the scope, or the task cap under real load.
  - The preflight read-back on the first authorized `lce-2.2` run is the first runtime evidence that they are
    configured.
  - Effectiveness under load has not been exercised. It would need a separately authorized, bounded stress check
    inside a limited scope.
