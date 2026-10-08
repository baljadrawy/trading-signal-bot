# P2F G3 Stage M: limit-aware monitor deployment record (2026-10-08)

**Verdict: PASS.** Only the monitor-limit change (Stage M of `P2F_G3_RESIZE_READINESS.md` §5) was deployed. Stage G
(the resize) was NOT performed. Nothing merged. Evidence: `/home/tradmin/backups/tsb-aiohttp-20260929T122701Z/g3-stage-m-20261008T003442Z/`.

| Item | Before | After |
|---|---|---|
| `~/ops/tsb-p2-forward/p2f_cont_monitor.py` | `4da51030…` (0ef8668) | `de83e506602cc7b2672d7c56e4ffbc2ab32e7f748ee23368aff36dcbf0eb16ed` (d556fd3 blob 211e027f) |
| `~/ops/tsb-p2-forward/p2f_monitor_bind.py` | `87da939b…` | `55f59381856fc75c28262af9ccfdbfa66a325199b77368e0452e5ef434973d09` (blob 89d54e5e) |
| `monitor/p2-forward-continuous-v1.binding.json` | `25c2f478…` (no limits) | `b54bce49…` (limits 50000 100000 / 402653184 / 0 / 64, cgroup+docker_hostconfig) |
| `…binding.json.history.jsonl` | `11b46ad5…` | `d39176e8…` (previous binding appended) |
| unit files | `8861897a…` / `9cebd793…` | unchanged |
| monitor unit | pid 3023036, inv d0e751da | pid 3363389, inv 2a3932e1, NRestarts 0 |

- Preconditions: 2026-10-07 day close, seal PASS (unexplained 0, clean_stop 13:27:19.657–13:28:15.844Z explicit),
  backup `SHA256SUMS` verified, restore-test PASS (01:17Z cron run).
- Window 01:46–01:47Z. Steps: read-only backup `~/ops/tsb-p2-forward/backup-pre-g3r-20261008T014624Z/`; install the
  two blobs (mode 0500, sha = git); runbook `systemctl --user restart`; `p2f_monitor_bind.py bind --reason "Stage M:
  limit-aware monitor …" --restart` (rc 0). The gate tool and `g3/` were not installed (not needed by the Stage M
  runtime; Stage G installs them per §5 Stage G or runs them from the branch).
- Validation: status `limits` == cgroup, expected_source binding, mismatch []; mem % and cpu_pct_of_quota match an
  independent cgroup calculation; severity WARNING (incident reason only `previous_run_stopped_failed`; intermittent
  `cpu_throttled_gt_10pct` as before); no new incident; G2 `admit --profile R1` ADMIT; G3 preflight `monitor` PASS.
- Collector 0488866e2e04 unchanged (RestartCount 0, HEALTHY, limits identical); Paper B3 unchanged (HALTED).
- Rollback: `rollback/rollback_stage_m.sh <backup dir>` in the evidence (exact 4 files + unit restart); old code was
  rehearsed read-only against both bindings.
