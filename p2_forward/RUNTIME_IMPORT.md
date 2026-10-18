# P2 forward collector 1.6.0: runtime source import (narrow)

This directory is a **narrow import of exactly what runs in production**. It is **not** a merge of the historical collector branches. Every file's source commit, git blob and SHA-256 are in `PROVENANCE.json`. Where a file has a running counterpart, its byte equality with that counterpart is recorded too.

## What runs, and where it comes from

| Running component | Imported files | Source commit | Running equality (2026-10-18) |
|---|---|---|---|
| Collector image `tsb-p2-forward:p2f-160-1bfb5f6-20261014T0652Z` (`sha256:324d52c9b37a…`, baked `P2F_GIT_COMMIT=1bfb5f6…`) | `p2_forward/**` (18), `Dockerfile`, `requirements.txt` | `1bfb5f6` (collector 1.6.0, A34/A35) | 18/18 image files identical |
| Host scripts in `~/ops/tsb-p2-forward` (flattened install of `ops/`) | `ops/*.py`, `ops/*.sh` (13) | 11 from `1bfb5f6`; `p2f_cont_monitor.py` and `p2f_monitor_bind.py` from `d556fd3` (G3 limit-aware monitor, deployed at G3 Stage M, branch `ops/g3-stage-m-20261008`) | 13/13 identical |
| Day verifier used by the daily seal and backup job | `verifier/verify_continuous.py`, `verifier/verify_independent.py` | `1bfb5f6` | 2/2 identical |
| Monitor systemd user units | `ops/systemd/tsb-p2f-monitor.service`, `ops/systemd/tsbops.slice` | `1bfb5f6` | 2/2 identical with `~/.config/systemd/user/` |
| Collector Compose project | `compose.yml` | Deployed bytes = `1bfb5f6:p2_forward/compose.yml` plus the reviewed G3 diff `ops/g3-stage-g-20261008:p2_forward/ops/g3/compose-g3-resize.diff` (1.5 CPU / 768 MB) | identical with `~/ops/tsb-p2-forward/compose.yml` |

The two source lines split at `cd2935e`. Their changes are path-disjoint: `1bfb5f6` changed only collector code and its tests, and the G3 line changed only the monitor scripts and G3 tooling. That is why this combined tree equals the runtime.

## Tests and test-only fixtures
- `tests/**` comes from `1bfb5f6`, the collector 1.6.0 suite.
- `verifier/specs/*.json` comes from `1bfb5f6`. These are historical G3 acceptance specs and are **test fixtures only**. `test_g3_prereqs` checks that the v6 and v7 spec files are unaltered. The specs contain no market data, research outcome or holdout material, and they are not used at runtime.
- `test_p2f_recovery_a34`'s before/after tests archive the pre-fix tree `cd2935e` from git history. CI therefore uses `fetch-depth: 0`, and that commit must stay reachable. It is on several preserved remote branches; an annotated tag is proposed but not created.
- `test_p2f_rotation_e2e` skips one case unless `P2C_READER_DIR` is set (an external reader). That is expected.

## Deliberately NOT imported
- **1.6.1 health/ack split** (`f366431`) and the **A41 ack-check fix** (`f1b52a2`): not installed, so not running.
- **G3 one-time tooling** `ops/p2f_g3_preflight.py`, `ops/g3/*`, and its test `test_g3_resize_readiness.py`: not installed on the host. The test needs the preflight module.
- `test_p2f_rotation_timer_coherence.py` (from the 1.5.0 line): not part of the 1.6.0 suite.
- `stress/` (load harness), the historical `configs/*.json` (G1/G2/G3), and the P2 design and operation docs (`docs/p2/*`): not running. They stay in history.
- The running collector configuration `continuous-v1.json` is versioned as a host template by the operational-definitions PR (`ops/host/`).

## History and governance
- Full history stays on `origin/fix/p2f-recovery-hardening-a34` (`1bfb5f6`) and `origin/ops/g3-stage-m-20261008` (`c11f906`).
- Draft PRs #18 and #19 (P2-E0 design, P2-E1 collector) are **not** merged or closed by this import; their review status is unchanged.
- No tag was created or moved.

## Local verification (2026-10-18, Python 3.12, the exact `requirements.txt` set installed with `--no-deps`)
`python -m pytest -q -p no:cacheprovider -rs tests` on this tree: **369 passed, 1 skipped** (`P2C_READER_DIR`), **0 failed**. CI runs the same suite in the `collector` job.

## Post-import test corrections
One test-only correction after the import (`tests/test_p2cr_crash.py`: deterministic crash interval). See `TEST_CORRECTIONS.md`. Runtime files are unchanged, and `PROVENANCE.json` still records the imported blobs.
