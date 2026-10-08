# G6 step 3 — monitor swap isolation (`MemorySwapMax=0`): prepared, NOT applied

**Status (2026-10-08 ~17:20Z):** preparation only.

- No systemd configuration was modified, the monitor was not restarted, and no cgroup was changed.
- Branch `feature/g6s3-monitor-swap-isolation-20261008`, based on G4 `2526338`, where the monitor unit is tracked.
- Evidence: `/home/tradmin/backups/tsb-aiohttp-20260929T122701Z/g6s3-prep-20261008T171949Z/`, sealed read-only.
  `SHA256SUMS` = `e3d0a7d9…cec8a`.

## 1. Verified current state (read-only)

| Item | Value |
|---|---|
| Unit | `tsb-p2f-monitor.service` (systemd 255, user manager, linger), `Slice=tsbops.slice`, `Type=notify`, `WatchdogSec=120`, `Restart=on-failure` |
| Unit file | `~/.config/systemd/user/tsb-p2f-monitor.service`, sha256 `8861897a…b785f`, **byte-identical** to `p2_forward/ops/systemd/tsb-p2f-monitor.service` @ `2526338` |
| `tsbops.slice` | byte-identical to the repo (`9cebd793…`): CPUWeight 1000, MemoryMax 512M, TasksMax 64; no swap setting |
| Drop-ins | **none**: `DropInPaths` is empty; no `~/.config/systemd/user/*.d`, no `~/.config/systemd/user.control`, nothing for this unit in `/run/user/1000/systemd/user.control` |
| Properties | MemoryHigh 201326592 (192M), MemoryMax 268435456 (256M), **MemorySwapMax infinity**, CPUWeight 1000, TasksMax 32, OOMScoreAdjust 100, OOMPolicy continue |
| cgroup | `memory.high` 201326592, `memory.max` 268435456, **`memory.swap.max` max**, `memory.swap.current` 0, `memory.current` ≈ 13 MiB, `memory.peak` 18.9 MiB; memory.events all 0 |
| Delegation | `memory` is in `cgroup.subtree_control` of `user@1000.service` and `tsbops.slice`. G6 step 1 proved the user manager writes `memory.swap.max=0`: a probe unit read 0. |
| Identity | MainPID 3551927, InvocationID `28260c0e…dd37dc`, NRestarts 0, active since 2026-10-08T08:28:33Z |
| Existing rollback mechanism | none specific: no drop-ins exist. The unit file is restorable from git (`2526338`); a G4 backup also exists (`backup-pre-g4-20261006T222430Z`). |

## 2. Proposed change (the smallest possible)

The change is one command, applied **live with no restart**. It is persistent across user-manager restarts.

```
systemctl --user set-property tsb-p2f-monitor.service MemorySwapMax=0
```

- systemd writes `~/.config/systemd/user.control/tsb-p2f-monitor.service.d/50-MemorySwapMax.conf`
  (`[Service] MemorySwapMax=0`) and writes `memory.swap.max=0` into the running unit's cgroup.
  - MainPID and InvocationID do not change.
  - No `daemon-reload` is needed.
- The reviewed reference copy is `p2_forward/ops/systemd/tsb-p2f-monitor.service.d/50-MemorySwapMax.conf`. It is
  **not** to be copied into `~/.config/systemd/user/`: verification compares the systemd-written file against it
  semantically.
- **Unchanged:** the base unit file, MemoryHigh, MemoryMax, CPU, tasks, OOM and restart policy, and `tsbops.slice`.
  Also unchanged: Collector, Paper, PostgreSQL, Hermes and the research runner.

**Why not edit the unit file, or add a `~/.config/systemd/user/…d/` drop-in?** That route needs a `daemon-reload`
plus a restart, or a second runtime command, to take effect. A restart changes the PID and InvocationID. The G2
trust rule then refuses admission, and the G2 watchdog **freezes** any running research job until the new instance
writes status (≤ about 60 s). It would also put a gap in the monitor samples that the G3 24 h comparison reads.

## 3. Expected impact

- **Monitor interruption:** **none expected.** The process keeps running, and the status cadence (about 60 s) is
  unaffected.
- **Memory:** with swap 0, the monitor's 18.9 MiB peak against MemoryHigh 192M / MemoryMax 256M leaves 10×
  headroom. Swap use is 0 today, so nothing has to be swapped back in.
- **Admission gate (G2):** no change. The trust rule checks `writer.pid` / `invocation_id` against the unit, and
  both stay the same. If a restart happened unexpectedly, the gate would fail closed until the next status write.
  That is safe, but it is a rollback trigger.
- **Protected windows** (the tool enforces them):
  - hh:12–25;
  - 23:50–00:45;
  - 01:10–01:45;
  - ±30 min around the universe rotation (next: 2026-10-09T00:10Z).
- **Additional scheduling rules (owner):**
  - **after** the G3 24 h comparison has been produced (≥ 2026-10-09T08:29Z);
  - **not** during a G5 run;
  - no research units loaded.
- **Proposed slot:** 2026-10-09 between hh:26 and hh:11, e.g. 09:30–10:10Z, or after the G5 window if G5 runs.

## 4. Deterministic procedure (all checks read-only; the tool never mutates)

`p2_forward/ops/g6s3_monitor_swap.py` (stdlib only):

1. `python3 g6s3_monitor_swap.py preflight --out <EV>/pre.json`. It must print **GO**. It checks:
   - unit file hash and no drop-ins;
   - base property and cgroup values, with swap still `infinity` / `max`;
   - the monitor trusted per the G2 rule (fresh ≤ 180 s, INFO / WARNING, writer = unit MainPID + InvocationID);
   - 0 `rj-*` / `rw-*` units;
   - Collector running, healthy, and equal to the bound cid;
   - protected windows and rotation.
2. Owner-approved apply: the single command in §2.
3. Wait ≥ 60 s, then run `python3 g6s3_monitor_swap.py verify --pre <EV>/pre.json --out <EV>/post1.json`. Repeat
   ≥ 60 s later (`post2.json`). Both must print **PASS**. They check:
   - property `MemorySwapMax=0` **and** cgroup `memory.swap.max=0`;
   - MainPID, InvocationID, NRestarts and ActiveEnterTimestampMonotonic **unchanged**;
   - MemoryMax / MemoryHigh (property and cgroup) unchanged, and the unit file unchanged;
   - exactly one drop-in, at the expected path, semantically `[Service] MemorySwapMax=0` only;
   - memory.events max / oom / oom_kill not increased;
   - the status rewritten since the preflight and still trusted;
   - the Collector's id, StartedAt and RestartCount unchanged, and healthy.
4. `research-run admit --profile R1` (dry) must still admit, with no monitor reasons.
5. Seal the evidence directory. Make a GitHub checkpoint recording Saved / Deployed / Validated separately.

**Evidence of preparation (sealed):**

- `preflight.json` at 17:19:50Z: **NO-GO with exactly one reason, `protected_window hh:12-25`.** This was the
  intended guard, since the run fell in the seal minutes. Every other precondition passed: unit hash, no drop-ins,
  swap infinity / max, monitor fresh (23 s), writer = unit, 0 research units, Collector `ce4e6b6656a5` healthy with
  0 restarts.
- `tests.txt`: `test_g6s3_monitor_swap` 17/17 and `test_g4_monitor_supervision` 10/10 pass.
- After the preparation, `unit_after_prep.txt` shows MainPID 3551927, NRestarts 0, MemorySwapMax infinity. The same
  12 containers are running.

## 5. Rollback

**Triggers** (any one):

- verify FAIL;
- the monitor restarted or became inactive;
- status stale > 180 s or severity outside INFO / WARNING;
- `memory.events` max / oom / oom_kill increase;
- G2 dry admission refuses on a monitor reason;
- any unexpected change elsewhere (STOP rule).

**Exact commands** (in order; live, no restart):

```
systemctl --user set-property tsb-p2f-monitor.service MemorySwapMax=infinity
rm -f /home/tradmin/.config/systemd/user.control/tsb-p2f-monitor.service.d/50-MemorySwapMax.conf
rmdir --ignore-fail-on-non-empty /home/tradmin/.config/systemd/user.control/tsb-p2f-monitor.service.d
systemctl --user daemon-reload
python3 g6s3_monitor_swap.py verify-rollback --pre <EV>/pre.json --out <EV>/rollback.json   # must PASS
```

`verify-rollback` checks: MemorySwapMax infinity, cgroup `memory.swap.max` max, no drop-ins, unchanged identity,
base properties, and a trusted monitor.

`daemon-reload` reloads definitions only: it restarts no unit, and research runtime properties persist under
`/run/user/1000/systemd/user.control`. If the monitor had actually restarted, restarting it again is **not** part
of the rollback: STOP and return to the owner.

## 6. Residual risks

1. **The live re-realization of the memory controller rewrites `memory.max` and `memory.high` with the same
   values.** This is harmless, and verify checks it.
2. **The drop-in path and filename are systemd 255's documented `set-property` behaviour, not proven on this host.**
   A probe would have meant creating a unit, which this stage forbade. If the path differs, verify fails closed: no
   restart, the doc is corrected, and the owner decides.
3. **Delegation failure.** If `set-property` errors (memory not delegated), nothing changes: STOP. This is unlikely,
   since the G6 step 1 probe already wrote `swap.max=0` in this tree.
4. **OOM arrives sooner.** With swap 0, an anon blow-up beyond 256M OOM-kills the monitor instead of swapping. The
   peak is 7 % of the limit, `OOMPolicy=continue` and `Restart=on-failure` apply, and research fails closed. This is
   the intended trade.
5. **Git drift.** The active drop-in lives under `user.control`, outside the tracked unit directory. The reference
   copy is in git, and verify enforces the match.
6. **Swap oversubscription is not solved by this step.** That is Hermes and Paper (G6 steps 5–7b); this step only
   removes the monitor's ability to page out.

## 7. Recommendation

**GO, for a separate owner approval.** The preparation is complete, the change is a single live and reversible
command, and the tests and preflight are clean apart from the time-of-day guard. Conditions:

- apply after the G3 24 h comparison;
- not during G5;
- in a minute window that is not protected;
- with a fresh preflight printing GO immediately beforehand.
