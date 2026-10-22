# Research admission controller: implementation plan

**Status: plan only.** This turns `RESEARCH_ADMISSION_CONTROLLER_DESIGN.md` (rules A1–A6 and the hardening table)
into code changes, tests and a rollout. Nothing is implemented. The host change to the `research.slice` quota (A3) and
enforcement both need separate owner approval. No governed research is run by any step here.

## 1. Where it plugs in (current code, `main` `0abb22d`)

| Step today | File | Change |
|---|---|---|
| `admission.evaluate(cfg, profile, …)` returns `{admit, reasons, inputs}` and never raises | `research_exec/admission.py` | Add check 7, **budget**: `budget.check(cfg, profile, job_id)` returns its reasons. It stays pure and read-only (no reservation inside `evaluate`). |
| `launcher` calls `evaluate`, writes `admission.json`, then `systemd-run --user --slice=…` | `research_exec/launcher.py` | Between the decision and `systemd-run`: `budget.reserve(...)` under the budget lock. On a `systemd-run` failure: `budget.release(job_id)`. After start: `budget.readback(...)` (A3 accounting drift). |
| `jobwrap` holds the profile `flock` for the job's life | `research_exec/jobwrap.py` | At exit (normal or signal): `budget.release(job_id)`. A crash is covered by reconciliation, not by `jobwrap`. |
| `research-run status` | `research_exec/__main__.py` | Prints leases and runs `budget.reconcile(dry_run=True)` |
| Profiles R1/R2/R3/LIGHT | `research_exec/config.py` | Add `"budget": {"r1_pct": 400, "r2_pct": 500, "lab_pct": 100, "grace_s": 120, "expiry_extra_s": 600, "clock_step_s": 60, "state_dir": …}`. After #71 is installed, R2 = 500 already. |

## 2. New module `research_exec/budget.py`

It is pure logic with injected probes, so every hardening rule is unit-testable without systemd:

```
Probes(is_unit_active(unit)->bool|None, pid_start_ticks(pid)->int|None, boot_id()->str,
       wall_utc()->datetime, mono_s()->float, slice_quota_pct()->int|None, lab_slice_pct()->int|None,
       marker_procs_outside_slice()->list)
Lease = {job_id, unit, profile, pct, boot_id, pid, pid_start_ticks, admitted_utc, expires_utc, mono_admitted}
state budget.json = {schema: 1, mode: "R1"|"R2", leases: [...], last_wall_utc, last_mono_s}
```

| Function | Rules | Behaviour |
|---|---|---|
| `load()` | fail closed | A missing file means an empty state. A corrupt file, an unknown schema or a bad type **refuses** (`budget_state_unreadable`); it is never repaired silently. |
| `capacity(state, probes)` | A1, A2, A4 | B = 400 (R1) or 500 (R2 mode); minus 100 while `tsblab.slice` is present. An unreadable lab probe refuses. |
| `reconcile(state, probes)` | crash, stale, clock | A lease is reclaimed only if the unit is inactive, **and** the pid is gone or its start ticks changed, **and** it is past `grace_s`. A unit that is gone while processes remain refuses. An expired lease with an active unit refuses. A wall step larger than `clock_step_s` (wall vs monotonic) refuses until consistent. Another boot's leases are reclaimed only if their units are inactive. |
| `check(...)` | A1, duplicates, overlap | `held + pct > B` refuses; LIGHT draws from the same B. A duplicate active `job_id` refuses. Marker processes outside the slice refuse. |
| `reserve(...)` | concurrency | Exclusive `flock(budget.lock)`, then `load`, `reconcile`, `check`, append the lease, then tmp + `fsync` + `rename` + directory `fsync`. Returns the lease or the refusal reasons. |
| `release(job_id)` | | Under the lock. Idempotent; a missing lease is not an error. Mode drops back to R1 when no R2 lease is left (A2). |
| `readback(...)` | A3, accounting drift | The slice quota must equal B, and the live `rj-*` units must equal the active leases. A mismatch refuses further admissions and reports. |

LIGHT under a held budget: **queue** (the owner decision recommended in the design) is implemented as a bounded wait in
the launcher, using the existing `--wait` semantics with a timeout. It is not implemented inside `budget.py`.

## 3. Tests

**Unit tests**: `ops/research/tests/test_budget.py`, fakes only. They map 1:1 to the design:

| Design item | Test |
|---|---|
| Two parallel admissions racing for the last budget | two processes `reserve` concurrently through a real `flock` on tmpfs; exactly one succeeds |
| SIGKILL after admission | a lease with a dead pid and an inactive unit is kept before the grace and reclaimed after it |
| PID reuse | the same pid with different start ticks counts as dead |
| Duplicate `job_id` | refused |
| Expired lease with an active unit | refused, not reclaimed |
| Marker process outside the slice | refused |
| Lab container without `cgroup_parent` | probe hit, refused |
| Corrupt `budget.json` | refused, file untouched |
| §4.1 LIGHT vs R2 / R1 | 200 + 500 > 500 refused; 200 + 400 > 400 refused |
| §4.5 R2 mode returns to R1 | after the last R2 release |
| §4.6 lab present | B − 100 |
| Clock step | wall +120 s against monotonic: refused, then OK after reconcile |
| Atomicity | a crash injected between the tmp write and the rename leaves the old state valid |

**Integration tests** (non-production `systemd --user` units, the existing `test_integration_systemd.py` pattern, opt-in
marker): slice read-back mismatch (§4.3); CPU-burn throttled at B (§4.4), with host PSI recorded before and after;
a crash leaving an orphaned lease, then reclaim.

## 4. Rollout

| Phase | What | Production effect | Approval |
|---|---|---|---|
| I-1 | `budget.py` and unit tests, Draft PR | none | review |
| I-2 | Shadow mode: `evaluate` computes the budget decision and writes it to `admission.json` as `budget_shadow`, but does not refuse | none: decisions are logged only | review, then install approval |
| I-3 | Integration tests on non-production units | none (user units, test slice) | owner (host test units) |
| I-4 | Enforce A1/A2/A4/A5 and the hardening rules | jobs can be refused or queued | owner |
| I-5 | A3: set the `research.slice` CPUQuota to B from the mode | host change | owner, separately |

Each phase is independently revertible by reinstalling the previous runner files (sha256-recorded backups, as in
Stage C of `deploy/rc-20261022/RELEASE_CANDIDATES.md`).

## 5. Open points

- A job started outside the runner bypasses all of this; that is a policy rule (design §3).
- The 10 vCPU project ceiling needs a parent slice for all project containers (S3, deferred).
- LIGHT queue timeout value: proposed 30 min; owner decision.
