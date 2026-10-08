# P2F collector 1.5.0: production deployment record (2026-10-07/08)

Evidence: `backups/tsb-aiohttp-20260929T122701Z/p2f-150-deploy-20261007T110514Z-addendum-20261007T131522Z/` (the
sealed preflight directory next to it is unchanged). Not merged.

| Step | Record |
|---|---|
| Owner decision | effective `config_hash` `7e95bb30…` accepted for the byte-identical `continuous-v1.json` |
| Gated clean stop | requested 2026-10-07T13:27:19.657Z; stop marker `STOPPED`, exit 0, partials 0 (1.4.0 `81988f5d480d`, boot `b1b7edb6`) |
| Acks (while stopped) | `inc-1791335970908-b1b7edb6-3` (seal CRITICAL, ref = 10-06 disposition) binding `d15939bf…`; `inc-1791331810668-b1b7edb6-2` (`seq_reset`, false positive of the old rotation design, loss-freedom not provable) binding `dd08096f…`; both `valid`, gate passes |
| Gated start | `p2f_continuous_up.sh` 13:28:06Z (first attempt refused by compose before creating anything: a relative config path is parsed as a named volume; retried with the absolute path used by the previous container); container `0488866e2e04`, image `sha256:69187360…`, boot `acae43bf`, HEALTHY at 13:28:39Z |
| Identity / limits / isolation | cpu.max `50000 100000`, memory.max `402653184`, pids 64; `docker inspect` diff = id, image, compose image/config-hash labels, Pid/StartedAt, bind ORDER only |
| Run chain | `verify_continuous.py --run-chain` PASS; downtime `clean_stop` 13:27:19.657 → 13:28:15.844Z linked to `b1b7edb6` |
| Collection gap | book last 13:27:19 / first 13:28:18 (58 boundaries); depth 13:27:19 / 13:28:19; market 13:27:00 / 13:29:00 |
| G4 rebind / G2 | monitor re-bound (pid 3023036, cid `0488866e2e04`, WARNING `previous_run_stopped_failed`); `research-run admit --profile R1` ADMIT |
| First rotation | 2026-10-08 00:10:09Z universe transition (+hemi, +met): both hand-offs `caught_up` at 2.041 s, complete, 0 pending; `ws_handoff` classes conn1 {proven 71, resumed 1}, conn0 {proven 58, resumed 14}, 0 unresolved; epochs 2→3 and 1→4; `seq_stale` 798, `seq_reset` 0, `seq_regression` 0, catch-ups 234 (max 92 ms); 5 explicit one-sample gaps (pre-existing M3 / data-stale at the replacement connect); no new incident |
