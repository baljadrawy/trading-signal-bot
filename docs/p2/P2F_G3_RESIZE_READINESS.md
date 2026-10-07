# P2F G3: collector resize readiness (0.5 CPU / 384 MiB → 1.5 CPU / 768 MiB)

**Status:** readiness only, 2026-10-07. Nothing here has been executed against production. The collector, its
limits, the deployed `compose.yml`, the monitor unit and its deployed files are unchanged. Execution is a later,
owner-authorized Class B stage.

**Main blocker:** the production validation of collector 1.5.0 is still pending. That validation, including the
first real rotation (expected at the 00:10Z universe transition on 2026-10-08), belongs to another agent and is
authoritative. G3 must not start until that validation is complete and accepted by the owner.

**Why the first attempt failed** (`g3-collector-resize-20261006T232823Z`): its waiter watched only lifecycle files.
A `seq_reset` DEGRADED incident and an unhealthy collector were surfaced by the coordinator, not by the tooling.
This readiness package fixes three things:
- the gate checks live health, incidents and monitor state, not lifecycle files alone;
- the waiter stops on any new incident or alert;
- the monitor reads the real memory limit instead of the hard-coded 384 MiB.

Files (branch `feature/g3-readiness-20261007`):

| File | Role |
|---|---|
| `p2_forward/ops/p2f_g3_preflight.py` | read-only fail-closed gate (`check`) and bounded waiter (`watch`) |
| `p2_forward/ops/g3/expect-g3-collector-150.json` | the gate's expectations: identity, pinned hashes, disposition, rollback artifacts |
| `p2_forward/ops/g3/compose-g3-resize.diff` | the 3-line compose change (prepared, NOT applied) |
| `p2_forward/ops/p2f_cont_monitor.py` | limits derived from the cgroup; `status.json` gains `limits` |
| `p2_forward/ops/p2f_monitor_bind.py` | records and cross-checks limits at bind time |
| `p2_forward/tests/test_g3_resize_readiness.py` | 63 tests: gate fixtures for each failure, fake cgroup trees, waiter |

## 1. The G3 precondition gate (`p2f_g3_preflight.py check`)

- Exit codes:
  - `0` only if all 10 checks PASS;
  - `1` if any check FAILs;
  - `2` on a usage or expectation-file error.
- Any exception, missing file, unparsable value or uncertain schedule counts as a FAIL of that check. The gate is
  fail-closed.
- It writes only the `--json` file you pass. That file must be outside the dataset, the monitor output and the ops
  directory.
- Docker calls are Class A only: `inspect` and `image inspect`.
- It sets `dont_write_bytecode`, so it leaves no `__pycache__` in the ops directory.

| Check | Passes only if | Source of truth |
|---|---|---|
| `identity` | <ul><li>container Id equals the expected cid, it is running, and RestartCount is 0;</li><li>`Config.Image` equals the 1.5.0 tag, `Image` equals `sha256:69187360…`, and the tag still resolves to that id;</li><li>`/data` is the dataset, mounted rw, and `/config/collector.json` is the config, mounted ro;</li><li>the config file's sha256 is `ebe6be13…`;</li><li>health and run-record `config_hash` both equal `7e95bb30…`;</li><li>the run-record build claim and tag match, and git is `cd2935e`;</li><li>`collector_version` is ≥ 1.5.0 (health and run record);</li><li>the cgroup still shows the before-state (`cpu.max 50000 100000`, `memory.max 402653184`, `memory.swap.max 0`, `pids.max 64`);</li><li>the scope runs `python -m p2_forward`, and its `/data` has the dataset's inode.</li></ul> | `docker inspect`, `docker image inspect`, `runs/run-<boot>.json`, health, `/sys/fs/cgroup/system.slice/docker-<id>.scope/`, `/proc/<pid>/root/data` |
| `health` | <ul><li>state is HEALTHY and the health file is ≤ 30 s old;</li><li>OR every hard reason is in an owner-signed classification list (schema `p2f-g3-hard-reason-classification-v1`, `signed_by`/`signed_at`, entries `{reason, evidence}`, optional pinned sha). The default is no list, so any hard reason FAILs.</li></ul> | `health/collector_health.json` |
| `incidents` | <ul><li>no active, unacked DEGRADED/CRITICAL incident;</li><li>no unknown severity;</li><li>no active `seq_reset*`, `rotation_handoff_incomplete*` or `rotation_overlap_failed*` incident in the current boot, even at WARNING;</li><li>`p2f_ack_binding.gate()` returns `{}`. This is the same module and function as the start gate of `p2f_continuous_up.sh`, so the post-resize start cannot be refused mid-change.</li></ul> | `incidents/state.json`, `incidents/ack/` |
| `rotation` | <ul><li>the current run is ≥ 1.5.0;</li><li>health `counters.handoffs` ≥ 1, `handoff_classes.unresolved` is 0, and `seq_reset` is 0 with no causes;</li><li>every `health.rotation.events[]` has `overlap_ok`, `handoff.complete` and a reason of `caught_up` or `old_closed`;</li><li>the finalized lifecycle segments of the current boot hold ≥ 1 `ws_handoff`, all complete, with an empty `unresolved`;</li><li>there is no lifecycle `seq_reset`;</li><li>the lifecycle count is ≤ the health counter.</li></ul> | health counters and `rotation.events`; `raw/lifecycle/<day>/*-<boot8>-*.jsonl.gz` (the open `.partial` is excluded) |
| `day_lifecycle` | <ul><li>yesterday is closed;</li><li>every closed day before today has one of:<ul><li>`seals/D.json` with result PASS and a matching report sha, plus a backup whose `BACKUP.json` seal sha matches and whose `SHA256SUMS` is present, plus a `restore_test PASS` line with `unexplained 0`;</li><li>OR an owner disposition (2026-10-06: the doc sha `629c58b9…` and the pinned FAILED report, external incident and day-close shas; no PASS seal next to it).</li></ul></li><li>no seal `.partial`.</li></ul> | `days/`, `seals/`, `/home/tradmin/backups/tsb-p2-forward/<ds>/D/`, `logs/daily_seal_backup.log`, `p2f-150-deploy-…/disposition/2026-10-06_DISPOSITION.md` |
| `monitor` | <ul><li>the unit is active/running;</li><li>`status.json` is ≤ 120 s old, taking the older of mtime and `t_ms`;</li><li>the writer is `systemd-user`/`tsb-p2f-monitor.service`, with pid and invocation equal to the unit's MainPID/InvocationID;</li><li>binding cid, status cid, expected cid and live cid are all equal, and `binding_check` is proven;</li><li>severity is INFO or WARNING;</li><li>`code_sha256` equals the reviewed limit-aware monitor;</li><li>`status.json.limits` equals the live cgroup (the monitor-limit change must be deployed first).</li></ul> | `systemctl --user show`, `<monitor out>/status.json`, the binding file |
| `run_chain` | `verify_continuous.py <dataset> --run-chain` returns PASS, rc 0, with no failures, and its last run is the running boot (no stop marker). | the deployed verifier, writing JSON to a private tmp directory |
| `windows` | <ul><li>the whole operation interval `[now, now + 25 min]` stays out of every protected window:<ul><li>±30 min of every scheduled rotation: the proactive one (each connection's last up + `rotation_after_s`, from `connection_age_s`), the next universe refresh/transition (`universe_epoch.next_refresh_ms`) and any pending transition;</li><li>:12–:25 of every hour;</li><li>23:30–00:00Z;</li><li>01:10–01:45Z;</li><li>after 00:00Z until yesterday's seal, backup and restore-test are complete;</li></ul></li><li>a degraded universe refresh (30-min retries) counts as an uncertain schedule and FAILs.</li></ul> | wall clock and health |
| `rollback` | <ul><li>the 1.5.0 tag resolves to the expected id;</li><li>the 1.4.0 tag resolves to `750ea690…`;</li><li>the rollback tar's `.sha256` and content sha both equal `64bccaff…`;</li><li>the deployed `compose.yml` is still the pre-G3 version (`700fe7df…`, cpus 0.5, mem 384m, memswap 384m, pids 64);</li><li>the read-only backup `compose.pre-g3.yml` has that same sha.</li></ul> | `docker image inspect`, the tar and its sidecar, the compose files |
| `host` | MemAvailable ≥ 4 GiB. Swap totals and memory PSI are reported but not judged. | `/proc/meminfo`, `/proc/pressure/memory` |

The 2026-10-07T20:58Z shadow run (read-only, real state) gave verdict **FAIL** on four checks:

| Check | Problem | Why that is correct |
|---|---|---|
| `rotation` | `handoffs=0` | no 1.5.0 rotation has been observed yet |
| `monitor` | not limit-aware | the monitor change is not deployed |
| `windows` | overlaps 21:12–21:25 | the operation interval would cross the hourly seal/backup window |
| `rollback` | `compose.pre-g3.yml` absent | it is created in G3 step 1 |

`identity`, `health`, `incidents`, `day_lifecycle`, `run_chain` and `host` all passed. `incidents` passed with one
unacked WARNING, `previous_run_stopped_failed`. `day_lifecycle` showed 10-04 and 10-05 sealed, backed up and
restore-tested, and 10-06 as disposition FAILED.

**Known source weakness.** Restore-test has no durable record. `p2f_backup.py restore-test` only prints. The gate
therefore reads the PASS line from the cron log, and fails closed if that line is absent. A durable
`restore-test` record file is recommended as a separate change.

## 2. Bounded G3 waiter (`p2f_g3_preflight.py watch`)

**Baseline.** At start the waiter records:
- the health boot;
- the set of incident ids, with severity, active, acked and count;
- the `alerts.jsonl` byte offset;
- the monitor severity;
- `seq_reset` and the unresolved hand-off count;
- the `seals/`, `days/` and `incidents/external/` listings.

**STOP (exit 3) at the first poll that shows any of:**
- a boot change, or health not HEALTHY, or health older than 60 s;
- a new incident id, or a known DEGRADED/CRITICAL incident that recurs or reopens unacked;
- a new `alerts.jsonl` line that is not INFO/WARNING, or any `monitor_exit` / `monitor_yield` line;
- a monitor severity of DEGRADED or worse, or a monitor status older than 180 s;
- a `seq_reset` or unresolved count above the baseline;
- a new FAILED seal report, or a new external incident file;
- any unreadable input.

**Other exits.**
- `--until pass` exits 0 at the first poll where the full `check` passes. Use it to wait for a window.
- `--until never` only watches.
- `--max-s` is mandatory, at most 6 h. When the deadline comes the waiter exits 4, a failure, at the last poll that
  fits before the deadline. It never extends the deadline.

**Bounds and attribution.** The waiter never uses `pgrep`/`pkill`, never signals anything and writes only `--jsonl`.
Run it under `timeout`, or as `systemd-run --user --unit=g3-waiter-<ts> -p RuntimeMaxSec=<max+60>` with an owner
tag. Wait on its PID or unit state, never on its name.

**Phases.** A G3 run uses the waiter twice. The waiter is never running across the stop and start, because the boot
change would be an expected STOP.
- **W1** runs from the PASS preflight to the stop decision, using `--until pass` or a short watch.
- **W2** runs after the rebind, with a new baseline on the new boot, for 60 min with `--until never`.

A bounded 70 s live shadow logged baseline → 3 polls → `timeout` (rc 4), and no stray process remained.

## 3. Monitor memory and CPU limits from runtime state

**Change.** `MEM_LIMIT = 402653184` is removed. Each sample reads `cpu.max`, `memory.max`, `memory.swap.max` and
`pids.max` from `/sys/fs/cgroup/system.slice/docker-<id>.scope/`. This is Docker-free, so the monitor stays
observe-only. No manually synchronized constant remains.

**Parsing.**
- `"max"` gives a `None` value plus the problem `<file>_unlimited`.
- A missing file gives `<file>_unreadable`.
- Garbage gives `<file>_malformed`.
- `memory.swap.max 0` is valid and means no swap.

**Effect on the memory thresholds.**
- `mem_pct_of_limit` = anon (or current) / the observed `memory.max`.
- When the limit is unknown or unlimited, the percentage is `None` and the monitor raises the WARNING
  `memory_limit_unknown`. It never compares against a guess.
- The 75 % and 90 % thresholds are unchanged, but they now apply to the real limit.

**Expectation.** `p2f_monitor_bind.py bind` validates that the cgroup equals what `docker inspect` HostConfig
implies (NanoCpus × period, Memory, MemorySwap − Memory, PidsLimit) and records those values as `limits` in the
binding. It refuses to bind on a mismatch. Without binding limits, as with the current production binding, the
monitor uses its own first observation as the expectation. Either way, a difference raises the WARNING
`limit_mismatch:<file>`, so a `docker update` behind the binding is visible. Mismatches are WARNINGs, not
DEGRADED, so they never freeze research by themselves.

**CPU.** The throttling fraction and `cpu_cores_60s` never assumed 0.5. The new fields `cpu_quota_cores` and
`cpu_pct_of_quota` are derived from `cpu.max`.

**Compatibility.** Every change is additive:
- `status.json` gains `limits`;
- samples gain `mem_limit_bytes`, `cpu_quota_cores`, `cpu_pct_of_quota` and `swap_current`;
- `monitor.binding.limits` is new.

G2 `hostsignals.read_monitor` / `monitor_problems` still parse the new status: a test runs them against
a `--once` output. The old monitor ignores the extra binding key, because `load_binding` checks only
schema, cid and name. The bounded-G3 `verify_independent` spec still pins 0.5 CPU / 384 MiB on purpose. That spec
is the frozen P2-E1 acceptance spec, not the continuous verifier. It is neither changed nor used by seals or the
run chain.

**Shadow against the real collector cgroup.** The shadow runs read the real cgroup read-only. They wrote only to
the scratchpad, never to the production monitor directory, and they ran beside the production writer, never as a
second writer on its directory.
- `--once` with no binding: limits `50000 100000` / `402653184` / `0` / `64`, `mem_pct_of_limit` 49.7, matching
  production's 49.7.
- `--once` with a binding that records the current limits: `expected_source` binding, mismatch `[]`.
- `--once` with a synthetic 1.5/768 binding: `limit_mismatch:cpu.max` and `limit_mismatch:memory.max`, at WARNING.
- A 70 s loop: `cpu_cores_60s` 0.228 against production's 0.229, `cpu_pct_of_quota` 45.6, throttled 3.3 %.

**Finding (G4, not changed).** `monitors_on()` treats a wrapper whose argv contains the script, such as
`timeout … python3 p2f_cont_monitor.py --out X`, as a foreign writer on X, so `--once` exits 75. The production
unit is unaffected. For bounded manual runs, wrap the command as `timeout N bash -c 'exec python3 …'`.

## 4. Tests (lightweight, `nice -n 19`, outside :12–:25)

| Suite | Result | Notes |
|---|---|---|
| `tests.test_g3_resize_readiness` | 63 OK, < 1 s | <ul><li>gate fixtures for each failure mode of every check;</li><li>fake cgroup trees: current and target limits, max, missing, malformed, changed, binding match and mismatch;</li><li>G2 parser compatibility;</li><li>waiter: timeout, new incident, alert line, health, external file, `until pass`, mandatory deadline.</li></ul> |
| `tests.test_g4_monitor_supervision` | 10 OK | |
| `tests.test_p2cr_controls`, `tests.test_p2f_rotation_e2e` | 39 OK, 1 skipped (117 s) | run with the research venv, which has aiohttp 3.13.5; the image's 3.14.3 is not used here |

## 5. G3 execution procedure (later, owner-authorized Class B stage)

### Preconditions

- The owner has accepted the 1.5.0 first-rotation validation produced by the other agent.
- The owner authorizes M and G separately.
- `CLAUDE.md`'s absolute STOP rule applies: any unexpected hash, identity or gate result means STOP and return to the
  owner.

### Stage M: deploy the monitor-limit change BEFORE the resize

M runs as its own window, at least a few hours before G. It is never part of the same window.

**Why before, and not atomically.**
- The new monitor reads the limit from the cgroup, so it is correct both at 384 MiB and at 768 MiB. Nothing needs to
  be synchronized.
- Deploying it after the resize would leave the old monitor computing percentages against 384 MiB while the
  container has 768 MiB. Anon above 345 MiB would then give a false CRITICAL `memory_ge_90pct`, and G2 would refuse
  admission.
- Deploying it in the same window combines two changes in one step, which would confound attribution if either
  fails.
- Running it first at 0.5/384 gives a production parity check (the same percentages as the old monitor) before
  anything else changes.

**Steps.**
1. Outside every window, copy the deployed `p2f_cont_monitor.py` and `p2f_monitor_bind.py` to
   `~/ops/tsb-p2-forward/backup-pre-g3r-<UTC>/`, write `SHA256SUMS` and run `chmod a-w`.
2. Install the reviewed blobs from the commit with `git show <commit>:p2_forward/ops/<f>`, mode `0500`, and verify
   their sha against git. Also install `p2f_g3_preflight.py` and `g3/`. The unit file is unchanged.
3. Run `./p2f_monitor_bind.py bind --reason "G3 readiness: limit-aware monitor <evidence>" --restart`. The monitor gap
   is about 10–20 s.
4. Verify:
   - `status.json.limits` shows `50000 100000` / `402653184`, `expected_source` binding and mismatch `[]`;
   - the severity and its reasons are the same as before;
   - `code_sha256` equals the pinned value;
   - the G2 dry admission (as in `p2f-150 …addendum/window/08_g2_admission.txt`) admits.
5. Rollback: restore the backup files and run `systemctl --user restart tsb-p2f-monitor.service`. The extra binding
   key is harmless.

### Stage G: the resize

Window: the gate decides. Candidates are 02:30–03:00Z or 03:30–04:00Z after yesterday's seal, backup and
restore-test are done, kept ±30 min away from the proactive rotation. That rotation is now due at about 12:28Z on
10-08; if the 00:10Z transition rotates both connections, it moves to about 23:10Z.

1. **Read-only production checks** (PAPER/B3 snapshot, owner procedure; G3 does not touch them). Then:
   ```
   cd ~/ops/tsb-p2-forward
   cp -p compose.yml compose.pre-g3.yml && chmod 0444 compose.pre-g3.yml   # sha 700fe7df…
   cp compose.yml compose.g3-staged.yml && chmod 0644 compose.g3-staged.yml
   patch --no-backup-if-mismatch compose.g3-staged.yml < g3/compose-g3-resize.diff   # the reviewed diff
   chmod 0444 compose.g3-staged.yml && sha256sum compose.pre-g3.yml compose.g3-staged.yml
   ```
   The staged file's sha must be `06f32bc51974cdfcd7d84f2c184ef100bba7c9ecdb3889252841b6cfb67602c5`, and
   `diff compose.yml compose.g3-staged.yml` must show exactly 3 lines (`g3/compose-g3-resize.diff`):
   ```
   -    cpus: 0.5          +    cpus: 1.5
   -    mem_limit: 384m    +    mem_limit: 768m
   -    memswap_limit: 384m+    memswap_limit: 768m
   ```
2. **Preflight:**
   ```
   python3 -B p2f_g3_preflight.py check --expect g3/expect-g3-collector-150.json --json <ev>/preflight.json
   ```
   It must exit 0. Then run W1 (`watch --until pass --max-s 1800`). Re-run `check` immediately before step 3.
3. **Gated clean stop:**
   ```
   ./p2f_continuous_stop.sh /home/tradmin/research-data/trading-signal-bot/p2/forward-continuous-v1 compose.yml
   ```
   Expect the stop marker `STOPPED`, exit 0, partials 0 and a drain ≤ 450 s. Preserve evidence as in
   CONTINUOUS_OPERATIONS §7: copy `incidents/`, `control/`, `health/`, the monitor directory, inspect output and logs.
4. **Swap in the compose file while stopped:**
   ```
   install -m 0444 compose.g3-staged.yml compose.yml
   ```
   Then confirm the sha is `06f32bc5…`.
5. **Start with the same 1.5.0 image:**
   ```
   ./p2f_continuous_up.sh tsb-p2-forward:p2f-150-cd2935e-20261007T1105Z sha256:69187360f144ec208c18bb261b7831bdb47952a5a9397f580fee4a703c56c45c /home/tradmin/research-data/trading-signal-bot/p2/forward-continuous-v1 /home/tradmin/ops/tsb-p2-forward/configs/continuous-v1.json compose.yml
   ```
   - The config path must be ABSOLUTE: a relative path failed on 2026-10-07 13:27Z.
   - After a clean stop there is no `P2F_ACK_PREVIOUS`.
   - Expect "incident gate: no blocking CRITICAL incident", "previous run acae43bf: STOPPED cleanly" and `UP OK`.
6. **Verify:**
   - `cpu.max` = `150000 100000`, `memory.max` = `805306368`, `memory.swap.max` = `0`, `pids.max` = `64`;
   - inspect shows NanoCpus 1500000000, Memory and MemorySwap 805306368, PidsLimit 64, restart `no`, Image
     `69187360…`, RestartCount 0;
   - identity: a new cid and boot, `config_hash` `7e95bb30…`, version 1.5.0, `previous_run` acae43bf;
   - health HEALTHY, writer `beat_age_ms` < 3000, `durable_lag_ms` < 5000, new segments;
   - `runs/downtime-<new>.json` has cause `clean_stop`;
   - `verify_continuous.py --run-chain` PASS, with the last run being the new boot;
   - no new incident id.
7. **G4 rebind:**
   ```
   ./p2f_monitor_bind.py bind --reason "G3 resize 1.5/768m <ev>" --restart
   ```
   The binding's `limits` must be `150000 100000` / `805306368`, the status must show expected_source binding with
   mismatch `[]` and no `limit_*` reason, and the status cid must be the new cid.
8. **G2 admission:** the same dry admission must admit. Update the expect file with the new cid and the new
   `limits_before`, with an owner review, before any later gate run.
9. **W2:** 60 min of `watch --until never`, using a new baseline. Any STOP goes to the owner.
10. **Throttling comparison** (read-only, 24 h before and 24 h after; separate from provider steal):
    - Use the monitor's `samples.jsonl` (`throttled_frac_60s`, `cpu_cores_60s`, `cpu_pct_of_quota`) and cgroup
      `cpu.stat` deltas (`nr_throttled/nr_periods`, `throttled_usec`).
    - Use the health instrumentation (`sampler_lateness`, `loop_lag`, `gc_pause` max and counts).
    - Sample `/proc/stat` steal every 60 s, as G2 `hostsignals.steal_between` does, aligned to the same minutes.
    - Throttling is quota-local (CPU-time against `cpu.max`). Steal is hypervisor time and does not count toward the
      quota, but it slows wall-clock progress. Therefore report throttling per hour, and report lateness and lag
      separately within host steal-ratio bands (< 0.2, 0.2–0.3, 0.3–0.4, > 0.4).
    - Never attribute a lateness change to the resize unless it holds within the same steal band.
    - Acceptance (S2): hourly throttling ≤ 10 % over 24 h, beat_age < 3 s, durable_lag < 5 s, 0 DEGRADED.

### Rollback

**When:** a step-6 or step-7 failure, a new attributable DEGRADED/CRITICAL incident, an OOM, or a criterion breach.

**Steps:**
1. Stop with `p2f_continuous_stop.sh`.
2. Run `install -m 0444 compose.pre-g3.yml compose.yml` (sha `700fe7df…`).
3. Run `p2f_continuous_up.sh` with the same 1.5.0 tag and id, and the absolute config path. Add
   `P2F_ACK_PREVIOUS=<boot8>` only if the stop was not clean. Any new CRITICAL needs its own reviewed bound ack first.
4. Run `p2f_monitor_bind.py bind --reason "G3 rollback <ev>" --restart`.
5. Verify `cpu.max` `50000 100000` and `memory.max` `402653184`.

A defect in 1.5.0 itself is out of scope here. It follows `p2f-150-deploy…/rollback/ROLLBACK_READINESS.txt`: the
1.4.0 image `750ea690…`, with the tar `64bccaff…` if the tag is missing.

### cpu.weight 500 and oom_score_adj −500: not part of G3

These are separate later steps. Bundle them into the next already-planned recreate (S5 principle), each with its own
owner approval, for three reasons:
- G3 must change only the quota and limit, so that the 24 h throttling comparison is attributable.
- The runc 1.5.1 mapping from shares to weight must be verified by reading the `cpu.weight` file
  (GOVERNANCE_MODEL).
- OOM ordering matters more now that the host has swap (section 6), and it deserves its own measurement.

## 6. Swap baseline (read-only, 2026-10-07T20:40Z)

**Current facts.**
- `/proc/swaps`: `/swapfile`, a 4,194,300 KiB file, priority −2, 0 used. `free`: Swap 4.0 Gi, 0 used. SwapFree
  equals SwapTotal.
- `vm.swappiness` = 10 (`/etc/sysctl.d/99-swappiness.conf`). `/etc/fstab` has `/swapfile none swap sw 0 0`.

**Provenance.** The swap was added after both governance reviews:
- `/swapfile` birth, mtime and ctime are 2026-10-07T20:29:56.6Z. The fstab mtime and the sysctl file are from the
  same second.
- The journal shows `sudo … tradmin … COMMAND=/usr/bin/bash /home/tradmin/swap-4g.sh` at 20:29:56Z.
- `swapfile.swap` became active at 20:29:57Z.
- The capacity review closed at 2026-10-06T20:50Z and the governance review at 21:04Z. Both said "no swap", which
  was true at that time.
- The script's own comment explains the history. It replaces a 12 GiB `/swapfile` created 2026-06-30 (swapon only,
  never in fstab), which vanished at the 2026-09-27 reboot.
- Neither this workstream nor G3 touched swap.

**Per-cgroup swap ceilings.**

| Scope | `memory.swap.max` |
|---|---|
| collector | `0` (`memswap_limit = mem_limit`): it can never swap |
| `trading_*`, postgres, jadrawy | equal to their memory limit (Docker's 2× default) |
| hermes | 4 GiB |
| wishlist-app, xsch-app, xsch-caddy | `max` |
| the monitor user unit | `max` |

**Implications.**
- `memswap_limit 768m` in the G3 diff keeps `memory.swap.max 0`. The collector stays fail-fast inside its own limit
  and is never slowed down by swap-in of its own anon pages.
- Host pressure now degrades by swapping other workloads (latency and shared-disk IO; the io controller is not
  delegated) instead of an immediate OOM. Earlier capacity and OOM reasoning that assumed no swap is stale.
- G5/G6 must MEASURE rather than assume:
  - `/proc/vmstat` `pswpin`/`pswpout` deltas;
  - memory PSI `some`/`full`;
  - per-cgroup `memory.swap.current` and `memory.swap.events`;
  - the collector's `memory.events` (`high`, `max`, `oom`);
  - disk latency during swap activity.
- Admission rules such as "PSI memory some avg60 = 0" remain valid and measurable.

## 7. Remaining blockers before G3 can be authorized

1. The 1.5.0 production validation, owned by the other agent, is still pending. It includes the first real rotation
   at 00:10Z on 10-08, or the proactive one at about 12:28Z if the transition does not rotate. Its result, and the
   owner's acceptance of it, come first. Nothing here implies that 1.5.0 has passed. The gate checks `rotation` for
   itself.
2. The 2026-10-07 day lifecycle (seal, backup and restore-test, from about 00:17Z or 01:17Z on 10-08) must complete,
   or receive an owner disposition.
3. Stage M (the monitor-limit deploy) needs owner authorization and must run before G.
4. Owner review of this branch (gate, monitor, bind) and of the expect file. The expect file pins the cid, the image,
   `config_hash` 7e95bb30, the disposition and the rollback artifacts.
5. Owner decisions:
   - whether any hard health reason should ever be classified (the default is no list);
   - whether the unacked WARNING `previous_run_stopped_failed` is acceptable. The gate allows it.
