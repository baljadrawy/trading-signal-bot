# CHG-03: gated Collector recovery after a host reboot

**Status: DEVELOPED, NOT INSTALLED.** Owner approval of 2026-10-20 covers development and tests only. Installing or enabling anything below on the host is a separate owner approval (section 7). Docker `restart: "no"` is unchanged.

**Why.** On 2026-10-19 the host rebooted at about 15:05Z. The Collector stays down by design after a reboot (`restart: "no"`, owner decision D3), nobody was alerted, and the gap lasted 17 h 22 min until the manual CHG-02 recovery.

## 1. Components

| File | Role |
|---|---|
| `p2_forward/ops/p2f_reboot_recover.py` | One-shot orchestrator (`run`, read-only `status`, operator `reset`). Stdlib only |
| `p2_forward/ops/systemd/tsb-p2f-recover.service` | User unit, `Type=oneshot`, `WantedBy=default.target`, **no `Restart=`**. Runs once per user-manager start (lingering is enabled, so once per host boot) |
| `p2_forward/ops/p2f-recover.example.json` | Config template: expected image tag and ID, config/compose SHA-256, paths, thresholds, Paper container names, policy, alert settings |
| `p2_forward/ops/systemd/tsb-p2f-shutdown-stop.service` | **Option G-A** (section 6): system unit for a clean Collector stop during an orderly shutdown |
| `p2_forward/tests/test_p2f_reboot_recover.py` | 30 deterministic tests on a fake host and fixture datasets |

## 2. State machine

```
lock ─busy─► LOCKED (75, nothing written)
 │
Docker ready? ─no, after docker_wait_s─► MANUAL docker_not_ready
 │
collector running? ─yes─► NOOP_ALREADY_RUNNING (0, nothing written)
 │
storage + resources (dataset.json, disk ≥ 100 GB, memory ≥ 1 GB) ─fail─► MANUAL
 │
ledger gate: chain intact · no ATTEMPT for this host boot · failure circuit closed ·
             previous run never recovered before ─fail─► MANUAL
 │
classify previous run ─not eligible─► MANUAL not_auto_eligible:<class>
 │                    ─ORDERLY_REBOOT_UNCLEAN and policy off─► MANUAL unclean_stop_needs_operator_ack
 │
drift gates: image ID == pinned · config SHA-256 · compose SHA-256 · compose restart "no" · dataset id ─fail─► MANUAL
 │
incident gate: p2f_ack_binding.gate() == {} (blocking CRITICAL never bypassed, never acknowledged) ─fail─► MANUAL
 │
preserve evidence (copy, verify each file by SHA-256) ─fail─► MANUAL
 │
Paper snapshot · ledger ATTEMPT
 │
p2f_continuous_up.sh (the reviewed gated script; P2F_ACK_PREVIOUS only as below) ─rc≠0─► FAILED
 │
verify (≤ health_wait_s): container running, image pinned, restart "no", new run ≠ previous,
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
| `CLEAN_STOP` | stop marker `state=STOPPED` for the latest run | **yes**: the start gate needs no acknowledgement |
| `FAILED_STOP` | stop marker with another state (fail-closed, exit 6) | never |
| `ORDERLY_REBOOT_UNCLEAN_STOP` | no marker; the run started before this host boot; its last health write lies within [−10 min, +5 min] of the previous boot's last journal entry; and that boot's user manager reached `shutdown.target` | **only** with policy `auto_ack_previous_on_orderly_reboot: true` (default **false**) |
| `UNCLEAN_REBOOT_UNVERIFIED` | as above, but no orderly-shutdown evidence (power loss, crash) or no health evidence | never |
| `COLLECTOR_CRASH_SAME_BOOT` | no marker; the run started during the current host boot | never |
| `COLLECTOR_DIED_BEFORE_SHUTDOWN` | the last health write is more than 10 min before the previous boot ended | never |
| `UNKNOWN` / `NO_PREVIOUS_RUN` | lineage mismatch, ledger inconsistency, missing records | never |

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

## 6. Governance: the runbook acknowledgement

The runbook (`docs/p2/CONTINUOUS_OPERATIONS.md` §7, on the held branch `feature/mi-am4a-stage-b-prep-20261011`, not on `main`) requires `P2F_ACK_PREVIOUS` after an unclean stop: the operator confirms that the evidence was preserved. **That confirmation is not automated by default.** Two options, each a separate owner decision:

| | G-A (recommended): clean stop at orderly shutdown | G-B: narrow pre-authorization |
|---|---|---|
| Mechanism | system unit `tsb-p2f-shutdown-stop.service`, `After=docker.service`: at shutdown its `ExecStop` runs `p2f_continuous_stop.sh` before Docker stops, so the collector drains and writes a STOPPED marker | set `policy.auto_ack_previous_on_orderly_reboot: true` |
| Effect after an orderly reboot | `CLEAN_STOP`: no acknowledgement needed, the existing gate is unchanged | `ORDERLY_REBOOT_UNCLEAN_STOP` is started with a derived `P2F_ACK_PREVIOUS`, after evidence preservation and every gate |
| Governance change | none to the acknowledgement rule | the runbook's operator confirmation is satisfied automatically, only for that class |
| Needs | root to install a system unit; the shutdown waits up to 480 s for the drain | config change only |
| Caveats | `systemctl stop` of this unit stops the collector; a power loss still ends uncleanly (then MANUAL) | relies on journal evidence of an orderly shutdown |

**Inferred cause of the unclean stop on 2026-10-19:** an orderly shutdown with a Docker stop deadline shorter than the collector's 450 s drain (exit 255, no stop marker). G-A addresses exactly that.

Without either option, the unit still adds value: it recovers clean stops, and in every other case it alerts the owner within minutes of the boot instead of leaving the gap unnoticed.

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

# 5. optional, only with the G-A decision (root)
sudo install -m 0644 p2_forward/ops/systemd/tsb-p2f-shutdown-stop.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tsb-p2f-shutdown-stop.service    # ExecStart=/bin/true: does not touch the collector
```

Then add the new unit templates to `ops/host/INSTALL_MAP.tsv` (reviewed PR) so `render.py compare` covers them. Acceptance happens at the next real reboot (planned or not): the report, the ledger and the alert are reviewed. **Do not reboot the host only to test this.**

## 8. Rollback

```bash
systemctl --user disable tsb-p2f-recover.service
rm ~/.config/systemd/user/tsb-p2f-recover.service && systemctl --user daemon-reload
# keep ~/ops/tsb-p2-forward/recovery/ (ledger and reports are evidence)
# G-A: `disable` only. `systemctl stop` / `disable --now` would run ExecStop and stop the collector
sudo systemctl disable tsb-p2f-shutdown-stop.service
```

Nothing in the dataset needs rolling back, because the orchestrator never writes there.

## 9. Residual risks

- A power loss, a crash, or a reboot without G-A/G-B still needs a person; the alert shortens detection, not recovery.
- Alerts depend on Telegram and the bot `.env`; a failed send is only logged locally.
- The unit runs at user-manager start. If lingering were disabled, it would run only at login.
- A health state of DEGRADED from latched historical incidents is accepted by verification: the criteria are writer, certifier and lineage, not a clean state. Latched incidents are never acknowledged automatically.
- The orderly-shutdown signal comes from the user journal. If journal retention removes the previous boot, the class is `UNCLEAN_REBOOT_UNVERIFIED` (MANUAL), which fails safe.
