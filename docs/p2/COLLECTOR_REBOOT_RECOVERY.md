# CHG-03: gated Collector recovery after a host reboot

**Status: DEVELOPED, NOT INSTALLED.** Owner approval of 2026-10-20 covers development and tests only. Installing or enabling anything below on the host is a separate owner approval (section 7). Docker `restart: "no"` is unchanged.

**Why.** On 2026-10-19 the host rebooted at about 15:05Z. The Collector stays down by design after a reboot (`restart: "no"`, owner decision D3), nobody was alerted, and the gap lasted 17 h 22 min until the manual CHG-02 recovery.

## 1. Components

| File | Role |
|---|---|
| `p2_forward/ops/p2f_reboot_recover.py` | One-shot orchestrator (`run`, read-only `status`, operator `reset`). Stdlib only |
| `p2_forward/ops/systemd/tsb-p2f-recover.service` | User unit, `Type=oneshot`, `WantedBy=default.target`, **no `Restart=`**. Runs once per user-manager start (lingering is enabled, so once per host boot) |
| `p2_forward/ops/p2f-recover.example.json` | Config template: expected image tag and ID, config/compose SHA-256, paths, thresholds, Paper container names, policy, alert settings |
| `p2_forward/tests/test_p2f_reboot_recover.py` | 62 deterministic tests: a fake host, fixture datasets, the real `RealHost` parsers fed with output captured on the production host, and a replay of the 2026-10-19 reboot |

## 2. State machine

```
lock ─busy─► LOCKED (75, nothing written)
 │
Docker ready? ─no, after docker_wait_s─► MANUAL docker_not_ready
 │
collector running? ─yes─► NOOP_ALREADY_RUNNING (0, nothing written)
 │
operator HOLD file (recovery/HOLD) present? ─yes─► MANUAL operator_hold
 │
storage + resources (dataset.json, disk ≥ 100 GB, memory ≥ 1 GB) ─fail─► MANUAL
 │
ledger gate: chain intact · no ATTEMPT for this host boot · failure circuit closed ·
             previous run never recovered before ─fail─► MANUAL
 │
classify previous run ─not eligible─► MANUAL not_auto_eligible:<class>
 │                    ─ORDERLY_REBOOT_UNCLEAN and policy off─► MANUAL unclean_stop_needs_operator_ack
 │
drift gates: image ID == pinned · config SHA-256 · compose SHA-256 · compose collector `restart` parsed == "no" ·
             existing container HostConfig.RestartPolicy == no/0 · dataset id ─fail─► MANUAL
 │
incident gate: p2f_ack_binding.gate() == {} (blocking CRITICAL never bypassed, never acknowledged) ─fail─► MANUAL
 │
preserve evidence (runbook set incl. the whole monitor dir; copy, verify each file by SHA-256) ─fail─► MANUAL
 │
ledger ATTEMPT bound to the SHA-256 of the evidence SHA256SUMS
 │
Paper snapshot · ledger ATTEMPT
 │
p2f_continuous_up.sh (the reviewed gated script; P2F_ACK_PREVIOUS only as below) ─rc≠0 or no "restart=no"─► FAILED
 │
verify (≤ health_wait_s): container running, image pinned, actual RestartPolicy no/0, new run ≠ previous,
        new run.previous_run == previous run, health.boot_id == new run, write_errors 0,
        writer alive and beat ≤ 5 s, certifier alive ─fail─► FAILED
 │
p2f_monitor_bind.py bind --restart ─rc≠0─► FAILED
 │
downtime record present · Paper snapshot unchanged ─fail─► FAILED
 ▼
RECOVERED (0)
```

Every outcome except LOCKED and NOOP writes `recovery/<UTC>-<boot8>/report.json`, appends a hash-chained ledger record and alerts the owner. RECOVERED sends an informational alert.

## 3. Classification of the previous run's end

| Class | Evidence | Automatic? |
|---|---|---|
| `CLEAN_STOP_AT_SHUTDOWN` | stop marker `state=STOPPED` whose `ts_ms` lies within [−2 min, +10 min] of the previous boot's end, with both orderly-shutdown records | **yes**: the start gate needs no acknowledgement (only reachable with G-A2/G-A3, see §6) |
| `CLEAN_STOP_BEFORE_SHUTDOWN` | any other clean stop: a deliberate operator stop | never: an operator's stop is not undone automatically |
| `FAILED_STOP` | stop marker with another state (fail-closed, exit 6) | never |
| `ORDERLY_REBOOT_UNCLEAN_STOP` | no marker; the run started before this host boot (kernel `btime`); its **last health state is `STOPPING`** (written only when the stop event fires) and that write lies within [−60 s, +5 min] of the previous boot's last user-journal entry; and **both** independent records show an orderly shutdown: the previous boot's user manager logged `Reached target shutdown.target`, **and** wtmp (or `wtmp.1` after rotation) has a `shutdown system down` record starting within 5 min of that journal end and ending within 15 min of the current kernel boot time | **only** with policy `auto_ack_previous_on_orderly_reboot: true` (default **false**) |
| `UNCLEAN_REBOOT_UNVERIFIED` | as above, but no orderly-shutdown evidence (power loss, crash) or no health evidence | never |
| `COLLECTOR_CRASH_SAME_BOOT` | no marker; the run started during the current host boot | never |
| `COLLECTOR_DIED_BEFORE_SHUTDOWN` | last health state is not `STOPPING` (a crash, OOM or SIGKILL leaves the last periodic state; health is written every 10 s), or `STOPPING` more than 60 s before the shutdown | never |
| `UNKNOWN` / `NO_PREVIOUS_RUN` | lineage mismatch, ledger inconsistency, missing records | never |

**Host evidence (verified read-only on the production host, systemd 255.4-1ubuntu8.18, 2026-10-20):**
- `journalctl --user --list-boots -o json` returns a JSON array of `{index, boot_id, first_entry, last_entry}` with timestamps in microseconds and 32-hex boot ids. The previous boot is chosen as the latest boot that **ended before the kernel boot time**, not by `index` (the user journal may not list the current boot yet).
- The current boot is identified by `/proc/sys/kernel/random/boot_id` (dashes removed), and its start by `/proc/stat` `btime`. The user journal's first entry is 28 s later.
- `last -x --time-format iso shutdown` prints `shutdown system down <kernel> <ISO start> - <ISO end>`. A power loss leaves no such record.
- On the real host the parser yields: previous boot `07f9c3c2…`, ended 2026-10-19T15:04:52.437Z, `journal_shutdown_target=true`, `wtmp_shutdown=true` (15:04:53 → 15:20:18 local+2). Current boot `71a4d947…`, btime 15:20:16Z.
- **Any** missing, unparsable or inconsistent evidence fails closed: `previous=None` or `orderly=False` gives `UNCLEAN_REBOOT_UNVERIFIED` (MANUAL), and an unreadable procfs gives `current_boot_unverifiable` (MANUAL).

The previous run is always read from the dataset (`runs/`, cross-checked with `p2f_ack_binding.latest_run`). `P2F_ACK_PREVIOUS` is derived from it, never hard-coded, and is passed only in the policy-enabled orderly case. `p2f_continuous_up.sh` re-checks it.

## 4. Failure, loop and alert behaviour

- **No loops.** systemd never retries the unit. The ledger allows at most **one ATTEMPT per host boot**. After `max_consecutive_failures` (2) FAILED outcomes in a row, every later boot is MANUAL until an operator runs `p2f_reboot_recover.py reset --by ... --reason ...`.
- **After a FAILED start the collector is not stopped or restarted.** It stays in whatever state the gated script left it in (it is itself fail-closed), and the owner is alerted.
- **Alerts.** Telegram through the bot's existing channel. The token is read from the bot `.env` at send time and never written to reports, logs or the ledger (tested); this is the same pattern as the A56.6 soak monitor. A failed send is logged to `recovery/alert_errors.log` without the URL.
- **Not alerted:** a recovery unit that never runs at all (for example if the user manager does not start).

## 5. What it never does

It never:
- acknowledges an incident;
- changes a restart policy, Compose, systemd, cron or configuration;
- calls `docker start` or `docker run`;
- touches Paper containers, other than inspecting them;
- queries a database;
- reads trading outcomes;
- writes into the dataset (tested on seals, days, control, incidents, quarantine and dataset.json);
- backfills data;
- deletes anything.

## 6. Governance: the runbook acknowledgement, and why G-A was withdrawn

The runbook (`docs/p2/CONTINUOUS_OPERATIONS.md` §7, on the held branch `feature/mi-am4a-stage-b-prep-20261011`, not on `main`) requires `P2F_ACK_PREVIOUS` after an unclean stop: the operator confirms that the evidence was preserved. **That confirmation is not automated by default** (G-B stays off).

**G-A (a system unit `After=docker.service` that stops the collector at shutdown) was withdrawn in review.** Read-only facts from the host:

| Fact | Value |
|---|---|
| Docker daemon | `live-restore: true`, cgroup driver `systemd`, cgroup v2 |
| `docker.service` | `TimeoutStopSec=90s`, `KillMode=process` |
| Container scope `docker-<id>.scope` | `TimeoutStopSec=90s`, `KillMode=control-group`, `KillSignal=SIGTERM`, `FinalKillSignal=SIGKILL`, `DefaultDependencies=no`, no `Before=`/`Conflicts=`, member of `system.slice` |
| Container | `StopTimeout=450` (compose `stop_grace_period`), `RestartPolicy=no/0` |
| System default | `DefaultTimeoutStopSec=90s`; `reboot.target` `JobTimeoutSec=30min` |

**Consequence (INFERRED from systemd semantics; the system journal of the shutdown is not readable by `tradmin`, so it is not directly verified):**
- With live-restore, stopping `docker.service` does not stop containers.
- The container's scope is stopped as part of the shutdown transaction (`system.slice`). It is not ordered against any unit, so it runs **in parallel** with any `After=docker.service` unit.
- `KillMode=control-group` sends SIGTERM to every process in the container at once, then SIGKILL after 90 s. The collector's drain needs up to 450 s (certify grace 300 s plus close).
- An `ExecStop` that calls `p2f_continuous_stop.sh` therefore cannot guarantee a drain before the SIGKILL.
- This matches 2026-10-19: health stopped 2–3 s after shutdown began (15:04:55Z), there was no stop marker, and the exit was 255.

**Designs that could make an orderly shutdown clean (each needs root and a separate owner decision; none is implemented):**
- **G-A2:** after every collector start, a root helper writes a runtime drop-in `/run/systemd/system/docker-<id>.scope.d/` with `Before=<stop unit>` and `TimeoutStopSec=480`, then runs `daemon-reload`. Scoped to this one container. It needs a narrow sudo rule and must track each new container ID.
- **G-A3:** a logind *delay* inhibitor held by a small helper that runs the gated stop on `PrepareForShutdown`. Needs `InhibitDelayMaxSec ≥ 480` in `logind.conf` (host-wide, though it only delays shutdowns while the lock is held). It does not cover shutdowns that bypass logind.
- **Not recommended:** a prefix drop-in `docker-.scope.d/` or a higher `DefaultTimeoutStopSec`. Both change shutdown behaviour for **every** container and service on the shared host (wishlist, xsch, postgres).

**G-B** (`policy.auto_ack_previous_on_orderly_reboot: true`) remains the only option without root. It is limited to the `ORDERLY_REBOOT_UNCLEAN_STOP` class (two independent orderly-shutdown records, plus every other gate). **It stays disabled** until the owner decides.

Without any of these, the unit still adds value: it recovers clean stops, and in every other case it alerts the owner within minutes of the boot instead of leaving the gap unnoticed.

## 6a. G-B readiness review (2026-10-20, read-only)

**Replay of the real 2026-10-19 reboot.** The input was a temporary copy of the CHG-02 pre-recovery evidence plus run record `2cfb872f`, with the real host's boot evidence. Result: `ORDERLY_REBOOT_UNCLEAN_STOP`.
- Last health was `STOPPING` at 15:04:55.681Z, 3.2 s after the previous boot's last user-journal entry (15:04:52.437Z).
- The journal shows `shutdown.target`, and wtmp shows `shutdown system down 17:04:53 → 17:20:18` (+02:00).
- The incident gate was `{}`.
- With G-B on, the derived acknowledgement would be `2cfb872f`, the value the owner approved manually in CHG-02. With G-B off it is MANUAL. Both are covered by tests.

**Evidence availability after a reboot** (VERIFIED):
- The journal is persistent (`/var/log/journal`, 91 MB, default limits) and keeps boots back to June.
- wtmp rotates monthly only above 1 MB (now 105 KB, `rotate 1`); the parser falls back to `wtmp.1`.
- Both sources are written by systemd itself at shutdown (user manager, `systemd-update-utmp`). A power loss writes neither.

**Orderly reboots that would still be MANUAL (fail-safe, accepted):**
- The previous boot's journal tail or wtmp record is unreadable or rotated away.
- A boot so slow (e.g. fsck) that utmp is written more than 15 min after `btime`.
- A shutdown where the collector's stop signal comes more than 60 s before the user manager's end.
- Any clean operator stop before the reboot (intentional).
- A second recovery attempt on the same boot, or an open failure circuit.
- Docker not ready within 10 min, or disk/memory below threshold.
- Drift of image, config or compose, or an actual restart policy other than `no`.
- A blocking CRITICAL incident.

**A derived `P2F_ACK_PREVIOUS` cannot bypass anything.** It is computed only after classification and passed only to `p2f_continuous_up.sh`, which runs **after** the drift, incident and evidence gates. Each of those raises before the start. The script itself re-checks the incident gate, the image and the previous run. The ATTEMPT ledger record carries the SHA-256 of the preserved evidence list. Tests cover a blocking CRITICAL, a missing evidence source, a copy mismatch and image drift under G-B: the start is never called.

**G-A2 / G-A3 (brief).** Their real advantage over G-B is data integrity: a full drain (certified segments, a clean marker) instead of a SIGKILL 90 s into the drain, and no acknowledgement at all. G-A2 (a per-container runtime scope drop-in) needs a root helper or a narrow sudo rule run at every collector start. G-A3 (a logind delay inhibitor) needs a host-wide `logind.conf` change. Neither is implemented: neither is safer to *recover* with than G-B, and both add root-level moving parts on a shared host. Recommended as a later integrity improvement.

**Optional system-journal confirmation (root; not run).** This is the only inference left open in §6. The command reads the 2026-10-19 shutdown of the old container's scope:

```bash
sudo journalctl -b -1 --no-pager -o short-iso-precise \
  -u 'docker-a2e2f3a6eeac*.scope' -u docker.service --since '2026-10-19 17:04:40' --until '2026-10-19 17:07:30'
```

- **Privilege:** root, or membership of `systemd-journal`/`adm` (read-only). Run it by the owner; do not change any group.
- **Expected if the inference holds:** `Stopping docker-a2e2….scope`, then about 90 s later `State 'stop-sigterm' timed out. Killing.` / `Failed with result 'timeout'`.

### Decision matrix (with G-B **off**, the default, and with G-B **on**)

| Scenario | Class / gate | G-B off | G-B on |
|---|---|---|---|
| Orderly reboot, collector killed during drain (today's normal case, e.g. 2026-10-19) | `ORDERLY_REBOOT_UNCLEAN_STOP` | MANUAL + alert | **automatic** |
| Orderly reboot with a clean stop at shutdown (only with G-A2/G-A3) | `CLEAN_STOP_AT_SHUTDOWN` | automatic | automatic |
| Operator stopped the collector before the reboot | `CLEAN_STOP_BEFORE_SHUTDOWN` | MANUAL | MANUAL |
| Fail-closed stop before the reboot | `FAILED_STOP` | MANUAL | MANUAL |
| Power loss / hard reset / shutdown evidence missing | `UNCLEAN_REBOOT_UNVERIFIED` | MANUAL | MANUAL |
| Collector crashed (OOM, SIGKILL) before the shutdown | `COLLECTOR_DIED_BEFORE_SHUTDOWN` | MANUAL | MANUAL |
| Collector crashed during the current boot | `COLLECTOR_CRASH_SAME_BOOT` | MANUAL | MANUAL |
| Blocking CRITICAL incident | incident gate | MANUAL | MANUAL |
| Image / config / compose / restart-policy drift | drift gates | MANUAL | MANUAL |
| Missing or mismatching evidence copy | evidence gate | MANUAL | MANUAL |
| Disk < 100 GB, memory < 1 GB, Docker not ready in 10 min | resource gates | MANUAL | MANUAL |
| Second attempt on the same boot; 2 consecutive failures | ledger | MANUAL | MANUAL |
| Operator `recovery/HOLD` file | hold | MANUAL | MANUAL |
| Start refused, exit after start, unhealthy, monitor re-bind fails, Paper changed | post-start | FAILED + alert (collector left as is) | same |
| Collector already running | — | no-op | no-op |

## 7. Production activation (each step needs the owner's approval; not done)

Run from a clean checkout of the merged `main` commit:

```bash
# 1. install the orchestrator (verify it equals main)
install -m 0755 p2_forward/ops/p2f_reboot_recover.py ~/ops/tsb-p2-forward/p2f_reboot_recover.py
sha256sum p2_forward/ops/p2f_reboot_recover.py ~/ops/tsb-p2-forward/p2f_reboot_recover.py

# 2. config: copy the template, fill the two hashes from the reviewed installed files
#    (ops/host/render.py compare must report IDENTICAL first)
install -m 0600 p2_forward/ops/p2f-recover.example.json ~/ops/tsb-p2-forward/recover.json
sha256sum ~/ops/tsb-p2-forward/configs/continuous-v1.json ~/ops/tsb-p2-forward/compose.yml   # edit recover.json

# 3. dry checks while the collector runs (read-only / no-op)
python3 ~/ops/tsb-p2-forward/p2f_reboot_recover.py status --config ~/ops/tsb-p2-forward/recover.json
#    expect: collector running; drift PASS; incidents PASS; storage PASS; ledger PASS
python3 ~/ops/tsb-p2-forward/p2f_reboot_recover.py run --config ~/ops/tsb-p2-forward/recover.json
#    expect: NOOP_ALREADY_RUNNING, exit 0 (creates only recovery/.recover.lock)

# 4. install and enable the user unit; do not start it
install -m 0644 p2_forward/ops/systemd/tsb-p2f-recover.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable tsb-p2f-recover.service
systemctl --user is-enabled tsb-p2f-recover.service          # enabled

# 5. G-B, ONLY with its own separate owner approval (after steps 1-4 are accepted)
#    edit ~/ops/tsb-p2-forward/recover.json: "policy": {"auto_ack_previous_on_orderly_reboot": true}
python3 ~/ops/tsb-p2-forward/p2f_reboot_recover.py status --config ~/ops/tsb-p2-forward/recover.json   # still no-op
```

**INSTALL_MAP.** `ops/host/render.py compare` reports `MISSING` for any mapped file that is not installed, and exits 1. That exit is the drift gate run before every host operation. Adding the recovery unit to `ops/host/INSTALL_MAP.tsv` **before** it is installed would break that gate, and `render.py` has no "planned" kind. Rule: add the templates (`ops/host/systemd/tsb-p2f-recover.service.tmpl` and the `recover.json` template) to `INSTALL_MAP.tsv` **in the same approved activation change**, then run `render.py compare` right after step 4; it must report IDENTICAL. Acceptance happens at the next real reboot (planned or not): the report, the ledger and the alert are reviewed. **Do not reboot the host only to test this.**

## 8. Rollback

```bash
systemctl --user disable tsb-p2f-recover.service
rm ~/.config/systemd/user/tsb-p2f-recover.service && systemctl --user daemon-reload
# G-B only: set "auto_ack_previous_on_orderly_reboot": false in recover.json (takes effect at the next boot)
# suspend automatic recovery without uninstalling: touch ~/ops/tsb-p2-forward/recovery/HOLD
# keep ~/ops/tsb-p2-forward/recovery/ (ledger and reports are evidence)
# revert the INSTALL_MAP.tsv entries added by the activation change (reviewed PR), then render.py compare
```

Nothing in the dataset needs rolling back, because the orchestrator never writes there.

## 9. Residual risks

- With G-B off, **every** host reboot today ends in MANUAL: on this host an orderly shutdown also kills the collector uncleanly (section 6). The value until G-A2/G-A3/G-B is decided is detection (an alert within minutes), not recovery.
- A power loss or a crash always needs a person.
- Alerts depend on Telegram and the bot `.env`; a failed send is only logged locally.
- The unit runs at user-manager start. If lingering were disabled, it would run only at login.
- A health state of DEGRADED from latched historical incidents is accepted by verification: the criteria are writer, certifier and lineage, not a clean state. Latched incidents are never acknowledged automatically.
- The orderly-shutdown evidence needs both the user journal (persistent: `/var/log/journal` exists) and wtmp (`/var/log/wtmp`). If either is rotated away or unreadable, the class is `UNCLEAN_REBOOT_UNVERIFIED` (MANUAL), which fails safe.
- The compose check is a line-based parser of the collector service block, not a YAML parser. Anything it does not recognise refuses. The authoritative check is the container's actual `HostConfig.RestartPolicy`, both before and after the start.
