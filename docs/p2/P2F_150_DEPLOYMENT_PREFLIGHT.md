# P2F collector 1.5.0: controlled-deployment preflight (2026-10-07) — STOPPED before the window

Branch `ops/p2f-150-deploy-20261007` (from `fix/p2f-rotation-seq-continuity-20261007@cd2935e`). Not merged.
Evidence: `backups/tsb-aiohttp-20260929T122701Z/p2f-150-deploy-20261007T110514Z/`.

## 1. Result

The preflight **stopped before the operational window**. The running 1.4.0 collector (`81988f5d480d`, boot
`b1b7edb6`), its incidents and the monitor were not touched. No acknowledgement was written.

**STOP reason (absolute STOP rule: hash differs from the owner's expected value).** The deployment authorization
requires the new run to show `config_hash 270ee3b9…` with the unchanged config file. Under 1.5.0 the same file
(`configs/continuous-v1.json`, SHA-256 `ebe6be13…`, unchanged) yields the effective
`config_hash 7e95bb3035aca8f52e7b96aaae3d6ae97483090e0e3f5e5ef2777c2f66d74c79`:

- `config_hash()` is the SHA-256 of the full **effective** configuration (file + code defaults);
- 1.5.0 adds three defaulted keys (`ws_handoff_min_s` 2.0, `ws_handoff_timeout_s` 15.0, `seq_catchup_timeout_s` 30);
- 1.4.0 with the same file: `270ee3b9ed567f58…` (reproduced in the rollback image); 1.5.0: `7e95bb30…`.

The repair evidence stated that the config "loads unchanged" but did not disclose the effective-hash change. The
consumers checked do not compare `config_hash` across runs (verifier run-chain PASS with a 1.5.0 run record on a copy;
seal, monitor and P2-C reader unaffected), so the change looks benign, but it contradicts an explicit owner
verification criterion. An owner decision is required (for example: accept `7e95bb30…` as the 1.5.0 effective hash
of the unchanged file). Nothing in this branch changes the repair's logic or the config.

## 2. Preflight results (all PASS except the STOP above)

| Item | Result |
|---|---|
| Image | `tsb-p2-forward:p2f-150-cd2935e-20261007T1105Z`, id `sha256:69187360f144…`; `/app/p2_forward` byte-identical to git `cd2935e` (18 files); base and pip layers identical to the 1.4.0 image |
| Tests in the image | full suite 357/358 (only the known host-`/proc` artifact `ProcessRoles.test_unknown_process_persisting_is_a_violation`); new timer-coherence tests 9/9, 3 further identical runs |
| Deployed config | loads in 1.5.0 (`p2cr-collector-1.5.0`, handoff 2/15/30); effective hash differs (STOP) |
| Data compatibility (copy) | 1.5.0 offline start on a copy (loads dataset/incidents, salvages partials, fails closed without network as designed); run-chain PASS; re-seal of 2026-10-05 PASS; monitor `--once` read-only; P2-C reader 50,254 records OK |
| Isolation | rendered compose config differs only in `image` and `P2F_IMAGE_ID`; image chosen by `p2f_continuous_up.sh` argument (no `compose.yml` edit) |
| Rollback | 1.4.0 image present (`750ea690…`), offline `docker save` copy, gate dry-checks PASS |
| Timer coherence (15 s / 30 s) | COHERENT (section 3) |

## 3. Timer coherence (15 s hand-off vs 30 s catch-up)

`tests/test_p2f_rotation_timer_coherence.py` runs the real `rotate()`/`_handoff`/audit/`on_seq`/sampler code under
the production timers on a deterministic virtual clock. Covered orderings: lags 0–12 s (complete, no gaps), 14/20/29 s
(15 s timeout, WARNING, explicit `awaiting_post_reconnect_data` gaps, catch-up between 15 and 30 s, class proven, no
reset), 40 s and a foreign id space (visible `seq_reset` `catchup_timeout` at hw receipt + 30 s, DEGRADED, class
unresolved), old socket dying mid-hand-off, replacement disconnecting mid-hand-off, streams finishing at different
times, and the `ahead`/`resumed`/`quiet`/`no_old` classes. Invariants checked in every case: no pending stream
persists a pre-close value after the close; no persisted backwards `exchange_seq` without a `seq_reset` record; every
incomplete hand-off or `unresolved` class raises the WARNING incident.

Residuals (all conservative, none silent): a stream quiet before the close has a catch-up window shorter than the
audit (a 30–30+d s lag is reset visibly and may still be classed proven); a replacement reconnect or a second
rotation within 30 s yields a false-positive `unresolved` WARNING; `close_ns` relies on a non-stepping wall clock.

## 4. Monitor resource telemetry (mandatory G3 prerequisite)

`p2f_cont_monitor.py` hard-codes `MEM_LIMIT = 402653184`. Correct while the collector stays at 384 MiB. Before, or
atomically with, any memory-limit change (G3, 768 MiB), monitor resource reporting must use the collector's actual
limit (cgroup `memory.max`/`cpu.max` or the binding). Not changed here.
