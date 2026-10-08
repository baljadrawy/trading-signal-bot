# MI Phase 1S CPU envelope: 600 % rate cap + 28 800 CPU-s fail-closed guard (design; NOT installed)

**Status (2026-10-08).** Designed and tested in isolation on `feature/mi-cpu-guard-20261008`, based on the
deployed runner `0f12d3a`.

- `research_exec` is **unchanged**. Nothing is wired into the runner, installed or activated.
- No slice exists, and no Phase 1S work ran.

**Owner decisions:**

- MI Phase 1S may use at most **6 logical CPUs (600 %)** in aggregate, child processes included.
- The cumulative budget stays **28 800 CPU-s**.
- Accounting and termination are fail-closed, including protection against guard failure.

## 1. Verified host facts (read-only, 2026-10-08 ~20:00Z)

| Item | Value |
|---|---|
| CPUs | 12 × Neoverse-N1 (KVM guest), 1 thread per core, 1 NUMA node (0–11); steal ≈ 0.23 vCPU (admission sample) |
| Delegation | root controllers: cpuset cpu io memory hugetlb pids rdma misc. **`user@1000`: cpu memory pids only** (no cpuset, no io) |
| Existing CPU caps | containers: hermes 4, analyzer 1.5, Collector 1.5, scanner 1, signal_engine 1 → **9 CPUs capped**; telegram, tracker, postgres and web are uncapped. tsbops.slice weight 1000. user / system / app slices are uncapped |
| Runner | `research.slice` (runtime, created at launch): CPUQuota 800 %, CPUWeight=idle, MemoryMax 12 G, swap 0. Profiles R1 400 / R2 600 / R3 800 %. Locks: heavy (R*), light (LIGHT). Watchdog poll 2 s. Currently absent (no jobs) |

**Consequences:**

- **cpuset is not delegated**, so the 6 CPUs **cannot be pinned or reserved** from the user manager. Exclusive CPUs
  would need root cpuset delegation, which is a separate approval.
- **600 % is a ceiling, not a reservation.** Combined with `CPUWeight=idle`, MI receives CPU only when Collector,
  Paper, Postgres, Hermes, web and monitoring do not need it.

## 2. Design

```
research.slice                (runner: 800 %, idle, swap 0)
 └─ research-mi.slice         CPUQuota=600 %  CPUWeight=idle  MemoryMax=10G  MemorySwapMax=0  TasksMax=1024
     ├─ mi-anchor-<c>         sleep; keeps the slice cgroup and its cumulative counter alive for the campaign
     └─ rj-<job> …            every MI job: --slice=research-mi.slice, BindsTo+Requisite+After the guard, RuntimeMaxSec
app.slice
 └─ mi-cpuguard-<c>           guard (outside the limited slice): CPUQuota 20 %, Restart=no,
                              CollectMode=inactive-or-failed, RuntimeMaxSec
```

**Rate (hard, kernel).** `research-mi.slice` `cpu.max = 600000 100000`. CFS bandwidth applies to the slice as a
whole, so every descendant (jobs, workers, children) is bounded together. No daemon is involved.

**Volume (fail closed).** The guard polls the slice's `cpu.stat usage_usec` every 1 s. This counter is hierarchical,
and it includes exited children while the anchor keeps the slice alive.

- The guard first **reserves** budget in an append-only, hash-chained, flock-serialized ledger capped at 28 800
  CPU-s. An open reservation counts as consumed.
- It **kills** the whole slice when used ≥ reservation − 12 CPU-s. The 12 CPU-s margin is two polls at 6 cores.
- It **charges** the measured final counter, or the full reservation if that counter is unreadable.

**Fail-closed rules:**

| Guard | Rule |
|---|---|
| G1 | budget kill at reservation − margin |
| G2 | unreadable / missing / non-monotonic / negative counter, or poll gap > 3 s → kill |
| G3 | jobs `BindsTo` + `Requisite` the guard. The guard is `CollectMode=inactive-or-failed`, so a dead guard is unloaded and no job start can resurrect it. A job never starts without a live guard |
| G4 | charge measured, or the full reservation; over-reservation is surfaced |
| G5 | reservations under the cap; open reservations consumed; tamper / truncation / double-charge → LedgerTamper; crash recovery charges the full reservation |
| G6 | RuntimeMaxSec on guard, anchor and jobs, plus a max-polls safeguard. **Wall-clock time never proves the cap; charging is by measured CPU** |

**Contention.**

- MI campaigns take the runner's **heavy lock**, so they are mutually exclusive with G5 and F0 v3 runner jobs.
- G6 production changes are manual and are not scheduled during a campaign.
- The runner admission gates (Collector, monitor, steal, PSI, memory, disk, protected windows) and the freeze
  watchdog apply per job, unchanged.
- research.slice's 800 % still bounds MI 600 % plus any LIGHT job of ≤ 200 %.

## 3. Test evidence

**Offline:** `tests/test_mi_cpuguard.py` → **21 / 21 OK** (`EVIDENCE_offline_20261008.txt`). The runner's existing
suites (admission / logic, launcher swap, detpool) still pass.

| Guard | Tests |
|---|---|
| G1 | kill before the reservation at the worst-case 6-cores-per-poll rate; 300 randomized rate / latency cases never exceed the reservation; margin = 12 |
| G2 | read fault → kill + full charge; non-monotonic; guard gap; baseline unreadable; kill error still charged; the cpu.stat parser fails closed (empty, missing key, non-int, negative, absent file) |
| G3 | job and anchor bound to the guard; guard outside the slice; Restart=no; CollectMode; slice CPUQuota 600 %, idle, swap 0 |
| G4 | DONE charges measured; over-reservation surfaced and STOP |
| G5 | cap and open reservations; crash recovery charges in full; tamper and truncation detected; double / unknown charge refused; **8 concurrent processes → exactly 5 reservations of 5 000 granted** |
| G6 | the wall-clock kill still charges measured CPU; RuntimeMaxSec rendered everywhere |
| G7 | the fault-injection suite above, plus the real-kernel tests below |

**Real kernel (opt-in):** `tests/test_mi_cpuguard_integration.py` with `MI_CPUGUARD_INTEGRATION=1`.

- Run 2026-10-08 20:04Z, after the runner admission gate admitted (no reasons), outside protected windows.
- Private throwaway slices `migt*` (not research.slice), CPUWeight=idle.
- About 13 CPU-s in total. No units left over. Collector and monitor unchanged.
- Result: **4 / 4 OK** (`EVIDENCE_integration_20261008T2004Z.txt`).

| Test | Result |
|---|---|
| I1 | 9 busy children under a 600 % slice → **5.71 cores** measured (≤ 6.00); `cpu.max = 600000 100000` |
| I2 | guard with a 4.0 CPU-s reservation and 2.0 limit on a 200 % slice killed at 2.04 CPU-s, **charged 2.05 ≤ 4.0** from the cgroup counter; the job is inactive |
| I3 | SIGKILL of the guard → the bound job stopped. A job started afterwards was **refused** (rc 1); the guard was not resurrected |
| I4 | the slice counter vanished → kill, and **full reservation charged** (3.0, `full_reservation_unreadable`) |

**I3 defect found and fixed.** The first run showed that `BindsTo=` also pulls a *start* of a loaded-but-dead
transient guard, so a new job silently resurrected it. The fix is `CollectMode=inactive-or-failed` on the guard;
after it, I3 passes.

## 4. Remaining blockers before Phase 1S

1. **Runner integration (not done; needs approval).** Required changes:
   - a slice parameter and the `job_props` in `launcher.build_job_cmd`;
   - a campaign wrapper: reserve → guard → anchor → jobs → charge;
   - output of `enforcement = cgroup_cpu_budget_guard_v1, enforcement_verified = true` only after these tests pass
     inside the integrated runner;
   - deployment as a G2-class runner change with backup and rollback.
2. **Activation (not done; needs approval):** creating `research-mi.slice` at runtime, and the guard / anchor units.
3. **Phase 1S compute authorization (B3).**
4. **No reserved CPUs.** Exclusive CPUs would need root cpuset delegation (separate approval). Without it, MI gets
   *up to* 6 CPUs, at idle priority.
5. **Guard-delay bound.** The margin assumes the guard polls within 3 s; longer gaps kill. A whole-VM pause stops
   both the guard and the jobs, so nothing accrues unmeasured.

---

## 5. Runner integration (development only, 2026-10-08) — opt-in, disabled by default

### What changed in `research_exec`

| File | Change |
|---|---|
| `config.py` | New `mi` section, `enabled: false`. Hard owner ceilings: `MI_MAX_QUOTA_PCT = 600` and `MI_MAX_CAP_CPU_S = 28 800`; config may lower them, never raise them. |
| `mi_campaign.py` (new) | Campaign lifecycle: `open` / `job` / `close` / `recover` / `status` |
| `launcher.py` | `build_job_cmd(..., slice_name=None, extra_props=None)` and `launch(..., mi_campaign=None)`. With the defaults, argv is **byte-identical** to the baseline `0f12d3a`, which a test proves. |
| `__main__.py` | `run --mi-campaign C` and `mi {open,close,recover,status}` |

**Opt-in requires all three:**

1. a `--config` file with `mi.enabled = true`;
2. an open, ready campaign;
3. `--mi-campaign` on every job.

Anything else refuses **before any side effect**, and no job directory is created.

### Campaign rules

**Open:**

- Refused when the ledger fails verification, the id is reused, **another campaign is open**, or the reservation
  exceeds what remains.
- Sequence: ensure research.slice and research-mi.slice (600 %) → start the guard (app.slice, Restart=no,
  CollectMode) → start the anchor (BindsTo / Requisite guard) → wait for the guard's ready file. The guard reserves
  and takes its baseline only after the slice cgroup exists.
- Any failed step aborts: the guard is stopped, and on SIGTERM it kills the slice and charges.

**Jobs:**

- A job joins only if the campaign is open, the guard is active with the recorded InvocationID, and the profile
  quota is ≤ the slice quota (R3 at 800 % is refused).
- Jobs run in research-mi.slice, BindsTo / Requisite / After the guard. The runner's admission gates, heavy lock and
  freeze watchdog apply unchanged.

**Close:** writes a close request. The guard ends with DONE once only the anchor remains (`pids.current ≤ 1`),
charges the measured CPU and exits. Close is idempotent.

**Recover:**

- Refused while the guard is alive.
- An open reservation is charged **in full**.
- Idempotent.
- A corrupted ledger refuses everything (STOP for the owner).

**Single campaign:** all campaigns share one slice counter, so only one may be open at a time. This prevents
double-charging and cross-kills.

### Offline integration evidence (no systemd unit, no real cgroup, no heavy compute)

`tests/test_mi_integration.py` uses a FakeHost:

- it runs the **real guard** (`python -m mi_cpuguard.guard_main`) as a subprocess against fake cgroup files;
- it applies BindsTo / Requisite / CollectMode semantics;
- a `systemctl` shim on the guard's PATH records its kill calls and never reaches systemd.

Results: **21 / 21 OK**, stable across 3 runs. Full discovery: **80 tests, OK, 9 skipped** (the opt-in real-systemd
suites: 4 MI and 5 pre-existing) in `EVIDENCE_integration_offline_20261008.txt`.

| Requirement | Tests |
|---|---|
| 1 Opt-in, default off | disabled everywhere; MI job refused before any job directory exists |
| 2 Non-MI preserved | `build_job_cmd` / `build_watchdog_cmd` for R1 / R2 / R3 / LIGHT are identical to the baseline launcher from git `0f12d3a`; pre-existing suites 29 / 29 |
| 3 600 % for all children | slice command CPUQuota=600 %; the MI cgroup is research.slice/research-mi.slice; job argv uses the MI slice plus guard bindings; quota 700, cap 30 000, a non-research slice or a margin below two polls are refused; an 800 % profile is refused |
| 4 Budget across retries / crashes | open → burn 2.5 → close charges 2.5; budget kill charges ≤ 5.0 for a 5.0 reservation (kill sent to research-mi.slice); id reuse refused; a crashed reservation stays consumed until recover charges it in full; recover is idempotent; a new campaign fits only within what remains |
| 5 Fail closed | guard SIGKILL → bound jobs stop, new jobs refused (Requisite) and `job_extra` refused; counter corruption → kill and full charge; mismatched InvocationID refused; corrupted ledger → open refused with no unit started, recover refused; ledger corrupted mid-campaign → guard kills and exits 4 (STOP) |
| 6 Kill scope | `valid_kill_target` accepts only `research-*.slice` whose parent is research.slice; rejects research.slice itself, Collector / docker scopes, the monitor, tsbops / app / user slices, system.slice paths, `..` traversal and shell metacharacters; the guard refuses such a target before reserving; kills always go to `systemctl --user` |
| 7 Rollback / idempotency / interrupted | failed guard start aborts with no reservation and the id stays used; failed anchor aborts and nothing is left open; close is idempotent; recover is refused while the guard is alive and is clean after close; an interrupted campaign is recovered at its full reservation, then a new campaign opens; one campaign at a time |

**Host kill-scope check** (read-only, `EVIDENCE_kill_scope_hostcheck_20261008.txt`):

- Collector, scanner, analyzer, signal_engine, telegram, tracker, postgres and hermes all run in
  `/system.slice/docker-*.scope`. That is the **system** manager, which `systemctl --user` cannot address.
- The monitor runs in `user@1000.service/tsbops.slice`, a sibling of research.slice, not a descendant.
- The MI slice would be `user@1000.service/research.slice/research-mi.slice`.
- Stopping or killing it therefore cannot reach any of them.

## 6. Deployment and rollback plan (NOT executed; each step needs owner approval)

**D0. Preconditions:**

- owner approval;
- outside protected windows; not during the G3 comparison, G5, F0 v3 or any G6 change;
- no `rj-*` / `rw-*` units loaded; heavy and light locks free.

**D1. Backup.** Tar `~/ops/research-runner` with SHA-256, following the G6 step 1 pattern.

**D2. Deploy (inert).**

- Copy, byte-identical to this commit: `research_exec/{config,launcher,__main__,mi_campaign}.py`, `mi_cpuguard/`,
  and the tests.
- Verify the SHA-256 of every file against git.

**D3. Verify (still inert).**

- Run offline discovery from the deployed tree.
- `research-run profiles` shows `mi.enabled = false`.
- A dry `research-run admit --profile R1` admits.
- The non-MI argv test passes.
- **No unit is started.**

**D4. Activation (separate approval).**

1. Write `mi-phase1s.json` with `{"mi": {"enabled": true}}`.
2. Run the opt-in real-kernel tests (`MI_CPUGUARD_INTEGRATION=1`, about 13 CPU-s).
3. Run a **tiny real campaign smoke test**: open with a reservation of about 30 CPU-s → one LIGHT synthetic job →
   close → ledger charge equals the cgroup delta. The integrated open / close sequence has so far been tested only
   against FakeHost.

**D5. Phase 1S** runs only with its own compute GO, using `research-run mi open --campaign … --config
mi-phase1s.json`.

**Rollback:**

- **Configuration level (instant):** keep or return `mi.enabled = false`. The integration is inert and non-MI
  behaviour is identical.
- **Code level:** restore the D1 tar and verify its hashes.
- **Running campaign:** `research-run mi close`. If it is stuck, `systemctl --user stop mi-cpuguard-<c>.service`
  makes the guard kill the slice and charge; then `research-run mi recover` if a reservation is still open.
- The MI state directory (`~/.local/state/research-runner/mi/`, which holds the ledger) is **never deleted**; it is
  the budget audit trail.

## 7. Remaining risks

1. **The integrated sequence is proven only offline.** The guard primitives (I1–I4) were proven on the real kernel;
   the integrated open / close / SIGTERM path awaits the D4 smoke test.
2. **Stray daemonized processes** in the slice block DONE. Close then times out, the operator stops the guard, and
   the slice is killed and charged (fail-safe, not silent).
3. **Ledger deletion** by an operator would reset the budget. Mitigation: anchor the ledger head hash in the
   Phase 1S evidence and output; the derivation map refuses unverified enforcement.
4. **No reserved CPUs** (no cpuset delegation). MI gets up to 6 CPUs at idle priority; research.slice's 800 % still
   allows a concurrent LIGHT job of ≤ 200 %.
5. **The guard's SIGTERM charge path** relies on systemd's default TimeoutStopSec of 90 s; the guard reacts within
   one poll (1 s).

---

## 8. Budget-ledger reset protection (2026-10-08; development only)

**Threat.** Deleting, truncating, rolling back, replaying or forking the ledger, or running older code against it,
must never free CPU budget or silently restart at zero.

### Mechanism

- **Ledger identity.** Event 0 is `genesis`, carrying a random `ledger_id` and `epoch`. Every line is hash-chained
  (`seq`, `prev`, `hash`).
- **Two independent checkpoints.**
  - `state_dir/mi/budget.checkpoint.json`;
  - `~/.config/research-runner/mi/budget.anchor.json`, which is outside both the runner state dir and the code
    tree. A config that puts it inside the state dir is refused.

  Each checkpoint is self-hashed and records ledger_id, epoch, seq, head, the totals, open reservations and **every
  campaign id ever used**. Both are written atomically (tmp → fsync → rename → directory fsync).
- **Every mutation** (reserve, charge or recover, under one flock) first verifies the chain and every checkpoint:
  - each checkpoint is present and its self-hash is valid;
  - it has the same ledger_id;
  - its (seq, head) is a prefix of the ledger;
  - the ledger is at most **one** event ahead. That one-event case is an interrupted checkpoint write, so the
    checkpoints are rolled forward.

  Then the event is appended with fsync, and both checkpoints are rewritten.
- **`state()` is strict and read-only.** It never initializes and never rolls forward.

**Refusal codes.** Each one fails closed: campaign open refuses, guard reserve / charge refuses (the guard STOPs),
and `job_extra` refuses.

| Code | Meaning |
|---|---|
| `NO_GENESIS` | no ledger and no checkpoint |
| `LEDGER_MISSING` | the ledger is gone but a checkpoint exists |
| `TORN_TAIL` | interrupted line |
| `LEDGER_CORRUPT` | broken chain, empty file or unknown event |
| `TRUNCATED_OR_ROLLED_BACK` | the ledger is shorter than a checkpoint |
| `FORK_OR_REPLAY` | a different hash at the checkpointed seq |
| `LEDGER_ID_MISMATCH` | foreign ledger |
| `CHECKPOINT_MISSING` / `CHECKPOINT_CORRUPT` | checkpoint absent, or a bad self-hash |
| `CHECKPOINT_STALE` | the ledger is more than one event ahead |

**Durable campaign identity.**

- A campaign record binds `ledger_id`, `epoch` and the seq at open.
- Every MI job re-checks that its campaign is an open reservation **of the current ledger**.
- Campaign ids are single-use across the whole lineage, including after carry-forward.
- Only one campaign may be open, enforced inside the ledger lock. `mi open` also holds a non-blocking open lock.

**Genesis vs recovery.**

- `research-run mi init --approve-genesis` creates the **first-ever** ledger only. It refuses when any ledger,
  checkpoint, `*.bak` copy or campaign record exists (`NOT_FIRST_GENESIS`). Genesis is part of activation, not of
  deployment.
- `research-run mi ledger-check` is read-only. It prints the status and a one-time owner **approval token** per
  recovery action. The token is bound to the exact ledger bytes, the best checkpoint head and the set of broken
  checkpoints, so any change after the check invalidates it.
- `research-run mi ledger-recover --recover-action A --approve TOKEN` supports these actions:

| Action | Behaviour |
|---|---|
| `rebuild-checkpoints` | intact ledger; any surviving checkpoint must be a prefix; survivors are preserved as `*.corrupt-*.bak`; a `checkpoint_rebuilt` event is appended |
| `torn-tail` | only the trailing partial line is removed; the original is preserved as `*.torn-*.bak`; the removed bytes' hash is recorded |
| `restore-backup --backup F` | accepted only if the backup contains the checkpointed head of this ledger (never an older or foreign copy); the replaced file is preserved |
| `carry-forward` | **destructive recovery**: a new epoch whose `carry_forward` event charges **max(best checkpoint committed, owner-declared)** and carries every used campaign id. With no surviving checkpoint the owner **must** declare prior consumption (fail-closed choice: the full cap). The old ledger is moved to `*.superseded-*.bak`, never deleted |

- No action ever reduces recorded consumption.

**Code rollback.** The previous ledger module (`edc2b6d`) **refuses** a genesis-format ledger (unknown event
`genesis`), so rolling the code back cannot reuse or reset the budget; MI simply cannot run. The pre-integration
runner `0f12d3a` has no MI code at all. In both cases the ledger files are untouched.

### Offline evidence

Full discovery: **105 tests, OK, 9 skipped** (the opt-in real-systemd suites), stable over 2 runs; see
`EVIDENCE_ledger_integrity_20261008.txt`.

| Suite | Tests |
|---|---|
| `test_mi_ledger_integrity.py` | **25 / 25** (0 skipped) |
| `test_mi_integration.py` | 21 / 21, re-run on the strict ledger |
| `test_mi_cpuguard.py` | 21 / 21 |
| Pre-existing runner suites | 29 / 29 |

| Requirement | Evidence (`test_mi_ledger_integrity`) |
|---|---|
| Genesis | first-ever only; refused without the flag, twice, after ledger loss, while the anchor survives, or with campaign records present; no silent initialization by `state` / `reserve` / `open` |
| Deletion | ledger deleted → `LEDGER_MISSING`; state-dir wipe → caught by the external anchor |
| Truncation / rollback | last event dropped → `TRUNCATED_OR_ROLLED_BACK`; empty file → `LEDGER_CORRUPT`; old copy restored, even together with the old state-dir checkpoint → caught |
| Replay / fork | re-chained ledger with altered charges → `FORK_OR_REPLAY`; foreign ledger → `LEDGER_ID_MISMATCH` |
| Code rollback | the old ledger module from `edc2b6d` refuses both `state` and `reserve` |
| Checkpoints | corrupt JSON / edited value without the hash → `CORRUPT`; forged head with a recomputed self-hash → `FORK_OR_REPLAY`; anchor missing → `MISSING`; rebuild needs a token, preserves survivors and keeps charges; rebuild refused if a survivor contradicts the ledger |
| Interrupted writes | torn tail refused, then repaired with a token (original preserved, charges kept); a crash between ledger append and checkpoint write → rolled forward by the next mutation; two unreconciled events → `STALE`; a crash between the two checkpoint writes → OK and re-synced; a failed atomic write leaves the previous checkpoint intact and no temp file |
| Concurrency | 8 processes reserving at once → exactly 1 succeeds (single open); a concurrent `mi open` → refused "in progress" before any side effect |
| Destructive recovery | carry-forward needs a token, keeps max(checkpoint, declared) = 180 when 50 is declared, starts epoch 1, old ids stay used, and nothing is deleted; total loss needs a declaration (the full cap exhausts the budget); restore-backup refuses an older backup and accepts the current one; tokens are bound to the exact state |
| Opt-in / non-MI | CLI refuses `open` before genesis; `init` needs `--approve-genesis` and works only once; MI is disabled by default; non-MI argv is byte-identical to `0f12d3a` (integration suite) |

### Residual risk (documented, not solvable locally)

The only reset path left is the simultaneous deletion of the ledger, **both** checkpoints, all `*.bak` copies and
all campaign records in two independent directory trees, followed by an owner-approved `init --approve-genesis`.

Procedural control:

- after every campaign close, record `ledger_id`, epoch, seq, head and committed in the GitHub evidence checkpoint;
- before any genesis, the owner confirms that GitHub holds no prior lineage;
- the Phase 1S output and derivation map bind the ledger head.

### Backup procedure (preserves the audit trail)

1. Take a backup only when `mi status` shows **no open reservation**, and never during a campaign.
2. Tar **both** `~/.local/state/research-runner/mi/` and `~/.config/research-runner/mi/`, record the SHA-256, and
   store the archive outside both trees.
3. Record `mi ledger-check` (ledger_id, seq, head, committed) next to the archive.
4. **Never copy files back by hand**; the checkpoints would report a rollback anyway. Restoring is only
   `mi ledger-recover --recover-action restore-backup --backup <ledger.jsonl> --approve <token>`, which refuses any
   backup older than the surviving checkpoints.

### Rollback procedures

| Level | Procedure |
|---|---|
| Config | Set `mi.enabled = false` (the default). MI is inert, and the ledger and checkpoints are untouched |
| Code (runner) | Restore the pre-deployment runner tar. **Never** touch `state_dir/mi` or `~/.config/research-runner/mi`; they are outside the code tree by design |
| Code rollback to `edc2b6d` | Not permitted after genesis (it refuses the ledger: fail-closed). Roll back only to `0f12d3a` (no MI) or forward |
| Running campaign | `mi close`; if stuck, stop the guard unit, which kills the slice and charges; then `mi recover` |
| Ledger damage | `mi ledger-check`, then the owner-approved `mi ledger-recover`. **Never** delete or re-initialize |

### Updated deployment plan (still NOT executed)

- **D2 (inert)** adds `mi_cpuguard/ledger.py` and the new tests.
- **D3** additionally verifies that `research-run mi ledger-check` reports `NO_GENESIS` (no ledger exists) and that
  **no** MI file exists in either directory.
- **Genesis (`mi init --approve-genesis`) moves to D4 activation**, with separate owner approval.

---

## 9. Inert deployment record — D1–D3 (2026-10-08 22:43–22:47Z, owner-authorized)

**Preconditions (all passed).**

- Time 22:44Z: outside every protected window.
- Deployed runner tree byte-identical to `0f12d3a` (13 files).
- Heavy and light locks free; 0 `rj-*` / `rw-*` / `mi-*` units; research.slice inactive.
- Dry admission R1: admit = true, reasons [].
- 12 containers running with 0 restarts; Collector `ce4e6b6656a5` healthy.
- Monitor MainPID 3551927, NRestarts 0, status fresh.

**D1 — backup.**

- Location: `/home/tradmin/backups/research-runner-backup-pre-micpu-20261008T224516Z/`.
- Contents: `research-runner.tar` (SHA-256 `5e093f27…6cb40b95`), `FILES.sha256` (13 files), `ROLLBACK.md`.
- Restore-verified by extracting and running `sha256sum -c`. Sealed read-only.

**D2 — deploy (inert).** 9 files, written byte-for-byte from `git show 1eac499:…` (not the working copy):

- `research_exec/{config,launcher,__main__,mi_campaign}.py`;
- `mi_cpuguard/{__init__,ledger,guard,guard_main,units}.py`.

The whole deployed tree (19 files) equals `1eac499`. Tests are not deployed, per convention.

**D3 — verification.**

- **Offline suite on a copy of the deployed bytes:** 105 tests, OK. 11 skipped: 9 opt-in real-systemd tests, and 2
  git-dependent tests that were run separately.
- **Non-MI equivalence on the deployed launcher:** job and watchdog argv identical to `0f12d3a` for R1, R2, R3 and
  LIGHT.
- **Code rollback:** the `edc2b6d` ledger code refuses the new format.
- **`mi.enabled` default:** false. `mi ledger-check` with the deployed config is refused ("MI integration is
  disabled").
- **Read-only diagnostic** with an ephemeral, uninstalled config: `NO_GENESIS`, both checkpoints missing. Neither MI
  directory exists afterwards.
- **No genesis, no campaign state.**
- **Dry admission:** admit = true, reasons [].
- **Units and processes:** 0 MI / research units; research.slice and research-mi.slice inactive; 0 guard processes.
- **Services:** all 12 containers identical to the pre-deploy snapshot (ID, StartedAt, RestartCount, health).
  Monitor identical (MainPID, NRestarts, InvocationID). Collector HEALTHY.
- **Evidence:** `/home/tradmin/backups/micpu-inert-deploy-20261008T2245Z/` (sealed, `SHA256SUMS`).

**Status:**

| | |
|---|---|
| Saved | `feature/mi-cpu-guard-20261008` |
| Merged | no |
| Deployed | **inert** (MI disabled) |
| Operationally validated | inert verification only. Activation (D4: genesis, real-kernel smoke test) is **not** done and needs separate owner approval |

---

## 10. D4 limited activation — STOPPED at the real-kernel tests (2026-10-08 22:51–22:53Z)

**Preconditions passed:**

- outside protected windows;
- deployed tree equals `1eac499` (19 files);
- both locks free; 0 units;
- admission (LIGHT) admits with no reasons;
- no MI lineage anywhere (both MI directories absent; no `budget.*` file outside worktrees);
- 12 containers and the monitor snapshotted.

**Genesis (first-ever):**

| | |
|---|---|
| ledger_id | **`f5983b83c32c4278996ec642d385977a`** |
| epoch | 0 |
| cap | 28 800 CPU-s |
| genesis hash | `370cc53029fc6329…` |
| config | dedicated `~/.config/research-runner/mi-d4.json` |
| checkpoints | `~/.local/state/research-runner/mi/budget.checkpoint.json` and `~/.config/research-runner/mi/budget.anchor.json` |

**Real-kernel tests (`MI_CPUGUARD_INTEGRATION=1`, wall time 6.3 s):**

| Test | Result |
|---|---|
| I1 | PASS: 9 children → 5.72 cores, under the 600 % cap |
| I3 | PASS: a job stops with its guard, and no start is possible without a guard |
| **I2, I4** | **ERROR**: the test file still builds a throwaway ledger with the pre-hardening API (no genesis, no checkpoints). The hardened ledger correctly refused it with `NO_GENESIS` (fail closed). The opt-in file was never run offline, so the gap went unseen. A product defect has **not** been shown; a stale test has |

**Absolute STOP rule applied.**

- No test patch, no smoke campaign.
- The tests' consumption was accounted in the permanent ledger as reserve + charge `d4-realkernel-tests`, charging the **full 30 CPU-s reservation** as an upper bound. I1 measured 9.43 CPU-s; the ceiling over all four tests is about 20 CPU-s.
- Ledger: seq 2, charged 30.0, **remaining 28 770.0**, no open reservation.

**Return to disabled:**

- `mi-d4.json` now has `enabled: false`.
- 0 MI / test units; research-mi.slice inactive; 0 guard processes.
- 12 containers and the monitor **identical** to the pre-D4 snapshot; Collector HEALTHY.

**Deviation:** right after genesis, the ledger file was mistakenly set read-only (0444). It was restored to 0664
within 10 s, before any further write. Content hash `e27b0fa5…` at seq 0 was unchanged, and `ledger-check` then
reported OK.

**Evidence:** `/home/tradmin/backups/micpu-d4-activation-20261008T2252Z/` (sealed, `SHA256SUMS` `921a5ba7…`). It holds
read-only copies of the ledger, both checkpoints and the final config.

**To finish D4 (owner approval needed):**

1. Update I2 / I4 to use a temporary genesis ledger with two checkpoints. This is a test-only change; deployed code
   is unchanged.
2. Re-run the 4 real-kernel tests, accounted in the ledger.
3. Run the one ≤ 30 CPU-s LIGHT smoke campaign.
4. Disable MI again.
