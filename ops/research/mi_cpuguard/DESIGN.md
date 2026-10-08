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
