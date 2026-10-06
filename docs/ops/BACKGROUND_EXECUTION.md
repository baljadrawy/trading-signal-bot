# Background execution on the shared host: bounded, attributable, auditable

**Status:** governance (G1, 2026-10-06). It applies to every agent and human who starts background work on `89.58.35.49`, in any repository. It sits beside [COMPOSE_OPERATIONS.md](COMPOSE_OPERATIONS.md). Where the two overlap, the stricter rule wins. The absolute STOP rule in `CLAUDE.md` still applies.

**Why this exists.** On 2026-10-06 two problems were found. First, wait loops of the form `until ! pgrep -f <pattern>` had run for about 14 h. The loop's own command line contains the pattern, so the loop matches itself and never ends. Second, four multiprocessing helpers had been orphaned for about 3 days, inside the same tmux scope as the P2 monitor. The helpers ignored SIGTERM, so only SIGKILL removed them. This document captures the resulting rules in the repository, so they no longer depend on anyone's conversational memory.

## 1. Waiting: identity and state only, always bounded
- **Never** poll with `pgrep -f`, `pkill -f`, `ps | grep` loops, or log-text waits that may never appear.
- Wait on one of these:
  - a **PID**: `timeout 600 bash -c 'while kill -0 "$PID" 2>/dev/null; do sleep 2; done'`
  - a **unit state**: `systemctl --user is-active -q <unit>`
  - a **completion file** written atomically by the worker.
- Every wait has a `timeout <N>` and an explicit failure path. A timeout is reported as a failure. Never silently extend it.
- Read-only assessments and sampling have a fixed time budget, about 15–20 min. Anything longer must be justified up front. Never wait just to accumulate more samples.

## 2. Every background process is attributable
- When you start it, record the **PID or unit name**, an **owner tag** (for example `agent:<task>` or `basim`), the purpose and the **maximum lifetime**.
- Prefer `systemd-run --user --unit=<name> -p RuntimeMaxSec=<s> --description="... owner=<tag>"`. A bare `&` or `nohup` is not attributable.
- Never start a background process inside a tmux or agent scope that hosts a production observer, such as the P2 monitor. Use a transient unit instead.

## 3. Every background process has a bounded lifetime
- Bound it with `RuntimeMaxSec=` or `timeout <N>`, or tie it to a parent unit (`BindsTo=`). Nothing may run "until someone notices".
- Multiprocessing must fail rather than hang when a worker dies. Use `concurrent.futures.ProcessPoolExecutor`, which raises `BrokenProcessPool`, not `multiprocessing.Pool`. Run inside a unit with `KillMode=control-group`, so stopping the unit kills every helper, including `resource_tracker`, which ignores SIGTERM.

## 4. Research, simulation and calibration go through the execution layer
- Batch research runs **only** via `ops/research/bin/research-run`. See [RESEARCH_EXECUTION_LAYER.md](RESEARCH_EXECUTION_LAYER.md). The deployed copy is `~/ops/research-runner/bin/research-run`.
- The layer provides:
  - admission control: Collector healthy, outside protected windows, low steal and PSI, and a single heavy-job lock;
  - a capped, freezable, OOM-preferred unit in `research.slice`;
  - a watchdog that freezes the job on Collector degradation;
  - per-job measurement.
- The default envelope is R1 (4 workers / 400 %). R2 needs `--allow-elevated` and R3 needs `--attended`. Both are owner-approved ramp steps (G5).
- Do not run ad-hoc `systemd-run` scopes, and do not run uncapped `python` research in an agent shell. The only exceptions are unit tests that last under 2 minutes.

## 5. Hand-back accounting (mandatory before reporting "done")
- List everything you started: PIDs, units, cron lines and files outside the evidence directory.
- Confirm that each one has ended or been removed. Do this with a one-shot check, such as `kill -0`, `systemctl --user is-active` or a `/proc/<pid>` existence check. Never use a polling loop for this.
- Put that list, with the final state of each item, in the report and in the evidence directory (`PROCESS_ACCOUNTING.txt`). "Zero left running" must be a verified statement.

## 6. Orphans
1. **Do not trust PIDs from an old report.** Re-establish identity from current state:
   - `/proc/<pid>/{cmdline,cwd,status,cgroup,fd,environ}` and the start time (`/proc/<pid>/stat` field 22 plus `btime`);
   - the parent chain, the session and process group, and any children;
   - the peers of every pipe, socket and shm fd, found by scanning `/proc/*/fd` for the same inode.
2. **Prove it has no dependents.** No production process (the Collector, the monitor, Paper, or a running research job) may share its pipes, sockets, shm or session.
3. **Kill only exact, verified PIDs.**
   - Re-verify the start time and command line immediately before signalling.
   - Send SIGTERM first. Check `SigIgn` in `/proc/<pid>/status`; multiprocessing helpers often ignore SIGTERM. Then use SIGKILL, after another identity check.
   - **Never** kill a tmux session or scope, a process group you did not create, or anything matched by name.
4. If any check is uncertain, **report** the orphan for an owner decision and leave it running.
5. Record the investigation and its disposition in evidence.

## 7. Cron and other persistent hooks
- Do not remove a cron line because of its name or age. First prove what it reads and writes, what alerts it sends, and that nothing depends on it now.
- To change the crontab:
  1. Back up `crontab -l` to evidence.
  2. Apply the change via stdin (`crontab - < file`), because a crontab FILE path must be at most 99 characters.
  3. Verify that the diff is exactly the intended lines.
  4. Record the rollback (`crontab - < backup`).

## 8. Host pitfalls
- `grep` is a ugrep shell function on this host. Use `/usr/bin/grep` in scripts.
- Never print plain `docker compose config`, because it decrypts secrets. Redact secrets in all evidence.
- User systemd units get only the `cpu memory pids` controllers. IO limits, `ionice -c3` and `io.weight` are no-ops for user units. Plan IO with that in mind.
