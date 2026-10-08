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
