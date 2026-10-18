# `deploy/DEPLOYED.json`: observed runtime baseline (schema `tsb-deployed/1`)

`DEPLOYED.json` records **what was observed running**, with complete immutable identifiers.
- It is **not** a deployment intent, and **not** a claim of clean-build reproducibility.
- It is validated, and compared with the server, by `ops/provenance/drift_check.py`. That tool is read-only and never remediates.

## Fields (every service)

| Field | Meaning |
|---|---|
| `container`, `compose_project`, `compose_service` | Runtime identity. `compose_project` is a key of `compose_projects`, or `external` |
| `expected_state` | `running`, or `not_running` (the learner) |
| `observed` | `container_id` (64-hex), `image_id` (`sha256:` + 64-hex), `image_ref`, `state`, `started_at`, `restart_count`, `config_hash` (Compose label, 64-hex, when present). **Observed with Class A `docker inspect` templates; no environment values** |
| `provenance` | `source_kind`: `commit` (with `source_commit`, full 40-hex), `assembled`, `upstream` or `retired`; `evidence` is the repository paths that support it |
| `archives` | Image archives: `set_path`, `file`, `sha256`, `role`. References only; the archives are on-host and never in Git |
| `reproducibility.level` | `L0-artifact`, `L1-content-verified`, `L2-canonical-rebuild`, `external-upstream` or `none` |
| `reproducibility.canonical_rebuild` | Must be `false` unless the level is L2 **and** `rebuild_evidence` exists. **No service qualifies today** (policy section 4 item 5) |
| `safety.paper_trading_required` | D8 checks that `PAPER_TRADING` is `true` on this container |
| `render_hash_service` / `render_hash_note` | Whether D4 compares `ops/compose-safe render-hash` with the label, and why not when it doesn't |

The top level also carries:
- `schema`, `observed_at`, `observed_by`;
- `repository_head`: the `main` commit when observed;
- `compose_projects`: repository path, production path, compose git blob;
- `learner_service`;
- `host_definitions`;
- `release_manifest`: for D2;
- `evidence`.

Key names that suggest secrets (password, token, api_key, private, …) are rejected by validation.

## Drift detector

```
python3 ops/provenance/drift_check.py validate                 # schema only
python3 ops/provenance/drift_check.py check  [--json REPORT]   # metadata checks (seconds)
python3 ops/provenance/drift_check.py check --deep             # adds D2 image content (docker save; ~45 s today)
python3 ops/provenance/drift_check.py observe                  # current observations, for reviewing a baseline update
```

| Check | What it compares | Tool |
|---|---|---|
| B0 | Manifest valid; observed at most 30 days ago; compose blobs equal the repository files; evidence paths exist | — |
| D1 | Container ID and image ID equal the baseline; a container expected `running` is running | `docker inspect --format` |
| D2 | Image `/app` files and installed packages equal the release manifest (`--deep` only) | `runtime_manifest.py verify` |
| D3 | Production compose files equal the baseline blobs | file hash |
| D4 | Render hash equals the container label and the baseline | `ops/compose-safe render-hash` |
| D5 | Collector compose, configuration, systemd units and cron equal the templates | `ops/host/render.py compare` |
| D6 | Start time and restart count unchanged | `docker inspect --format` |
| D7 | The learner is not running | `docker inspect --format` |
| D8 | `PAPER_TRADING` is `true`. Only this one entry is extracted, inside Docker's template, and its value is never printed | `docker inspect --format` |

**Statuses and exit code** (worst wins):

| Status | Exit code |
|---|---|
| `SAFETY` | 3 |
| `DRIFT` | 1 |
| `UNKNOWN` | 2 (evidence unavailable, schema invalid or baseline stale; **never treated as a pass**) |
| `MATCH` | 0 |

`NOT_RUN` (D2 without `--deep`) and `NOT_APPLICABLE` are always printed.

**Coverage summary.** Every `check` run prints, and the `--json` report contains, a `COVERAGE` line with the count of each status (`MATCH`, `DRIFT`, `UNKNOWN`, `SAFETY`, `NOT_RUN`, `NOT_APPLICABLE`) and a verification scope:

| Scope | When |
|---|---|
| `FULL` | Only with `--deep` and no `UNKNOWN` or `NOT_RUN` result |
| `METADATA_ONLY` | Image content not verified. The overall line says "image content NOT verified" |
| `INCOMPLETE` | Some required evidence was unavailable |

The required check families are B0, D1, D3–D8, plus D2 with `--deep`. A required family that produces no result is recorded as `UNKNOWN`, so a partial run can never present as a complete pass. Exit-code precedence is unchanged.

**Measured on 2026-10-18:**
- metadata check: 2.7 s, exit 0;
- `--deep`: 44 s, exit 0.

**Not scheduled.** Running it from cron or wiring alerts needs separate owner approval.

## Handling of observations and reports (internal infrastructure metadata)

`observe` output and `--json` reports contain internal infrastructure metadata: immutable container and image identifiers, host paths, start times, restart counts, config hashes and check results. Both carry a `_notice` field saying so.
- **Never** secrets or environment dumps. Only the single `PAPER_TRADING` flag is compared, inside Docker's template, and its value is never written. Tests enforce this.
- **Authorized operational workflows only.** Do not paste them into public issues or chats, and do not upload them to public services or pastebins.
- **Never commit generated observations automatically.** The baseline `DEPLOYED.json` changes only through a reviewed PR (below).
- Files written with `--json` or `observe --out` are created with mode **0600**, and an existing file is tightened to 0600 too. Keep them in a private directory, for example under `umask 077`. Plain `observe` prints to the terminal; prefer `--out` for anything you keep.

## Updating the baseline

Only through a reviewed PR, after an approved deployment or rollback:
1. Run `observe` and review the differences.
2. Update `observed` and the provenance or evidence references.
3. Run `validate`, then `check` (expect MATCH).
4. The previous baseline stays in Git history.
