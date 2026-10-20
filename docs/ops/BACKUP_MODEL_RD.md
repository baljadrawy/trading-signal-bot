# Backup model for the R&D stage (proposal, 2026-10-20)

**Status: PROPOSED (OD-DF-4).** Nothing here repairs, disables, replaces, schedules, runs, transfers or deletes any backup. Every step in section 5 needs its own owner approval. Facts below are read-only observations (file metadata, checksums, script source, logs) of 2026-10-20; no backup content, key or other project's data was read.

## 1. What exists (reconciled)

| Mechanism | Covers | Where | Encryption | State | Restore proven? |
|---|---|---|---|---|---|
| **xsch backup** (`~/twitter-scheduler/scripts/backup-run.sh`, 03:17 local, owned by the twitter-scheduler project) | `trading_signals` (full `pg_dump`, role `trading_signal_bot`) + `xsch` + cluster globals | restic repository `~/backups/restic`, **on this host**; no off-host step | restic; key file on the same host | **working**: nightly since 2026-08-04, last success 2026-10-19 01:17Z; 26 tables with data checked per run; retention 7 daily / 4 weekly / 12 monthly; weekly `restic check` on 20 % of data | **no** for `trading_signals` (the monthly restore test restores `xsch` only) |
| p1bg v1 (`ops/tsb-p1bg`, 04:53 local) | `trading_signals` + `evidence_v2` | `~/backups/tsb-p1bg`, local | none | **failing** every night since 2026-10-10 (tar reads appended evidence files; fail-closed is correct). Sealed sets 2026-10-02 … 10-09 verify. Each night leaves a `.incomplete-*` folder (DB dump + inconsistent evidence archive) | sets restored in A41/A56 rehearsals (REPORTED) |
| shared-postgres pipeline (03:23 local) | `wishlist` + globals; **excludes `trading_signals`** | restic over rclone to Google Drive, **off-host** | restic | working | yes, for `wishlist` |
| A56.5 / A56.2 manual recovery points | `trading_signals` dump (2026-10-16) and `evidence_v2` copies | local | none | checksums OK 2026-10-20 | restored at the time (REPORTED) |
| Collector sealed-day backups | sealed collector days | local | none | working (sealed days only) | per-day restore test |
| Release/rollback image archives | bot images (not the running collector 1.6.0) | local | none | checksums OK 2026-10-20 | — |

**Corrections to earlier records.** `TSB_BACKUP_RECOVERY_PLAN.md` and `PORTABILITY_AND_DR.md` (D-01, D-02) described `trading_signals` as having no working scheduled backup. It has one, owned by another project, local only and never restore-tested for this database. Nothing of this bot is off-host.

**Latent conflict.** If a p1bg v1 night ever succeeds, its `KEEP=7` retention deletes the oldest sealed set (2026-10-02) automatically. That contradicts R1.3 owner decision 2 (deletion only through a named, approved step). It is unlikely while the tar race persists, but not impossible.

## 2. What each data class actually needs

| Data | Replaceable? | Need |
|---|---|---|
| Source code, docs, tests | yes (GitHub, private repo) | none beyond GitHub |
| `trading_signals` database (Paper trades, signals, evidence of the sealed holdout) | **no** | ongoing protection + off-host copy + a tested restore |
| `evidence_v2` JSONL (decision records) | **no** | protection at least at each release; ongoing protection is a decision (section 4) |
| Collector sealed days | **no** (forward data) | preserve; off-host is a research-governance decision (R-01) |
| Release and rollback images | rebuildable only approximately (no canonical builds) | keep archives; off-host at release time |
| `.env` and keys | owner-held | owner's secret store, never in a backup set |

## 3. Proposed model

1. **Release recovery (R1.3, unchanged).** A certified recovery set (DB dump, evidence snapshot, image archives, manifest) for every owner-authorized container change.
2. **Ongoing database protection: one mechanism, not two new ones.** Choose one of:
   - **2a (recommended):** add `trading_signals` to the shared-postgres pipeline, which is already off-host, encrypted, uses a least-privilege role (`shared_pg_backup` already has `CONNECT` on `trading_signals`) and has a proven off-host restore pattern. Then remove it from the xsch backup as that project's own change.
   - **2b:** formally adopt the existing xsch-bundled dump (no change). Accept that it is local only, owned by another project and depends on the superuser role. Applying least-privilege roles (R-5) would break it.
3. **Evidence between releases.** Either accept the window (the risk is a loss of decision records since the last release) or take on-demand snapshots before and after any research window. **No periodic bot-owned schedule is added by this proposal.**
4. **Retire p1bg v1** only after 2a or 2b is in place: disable its single cron line and keep every set and `.incomplete-*` folder (deletion stays a separate, named approval).
5. **Off-host for release sets**, encrypted, key held by the owner.

## 4. Accepted development-stage risks (to record if approved)

| Risk | With this model |
|---|---|
| Host loss | DB recoverable from off-host (2a) to ≤ 24 h; evidence and collector data lost back to the last off-host release set |
| Evidence between releases | lost back to the last release set unless on-demand snapshots are taken |
| Restore never proven for `trading_signals` from the nightly mechanism | closed only by an isolated restore test (step 6 below) |

## 5. Transition plan (each step a separate owner approval)

| # | Step | Class | Rollback |
|---|---|---|---|
| 1 | Write a hash inventory of all existing bot recovery sets (one new file outside `~/backups`) | new file | delete the inventory file |
| 2 | Choose 2a or 2b | decision | — |
| 3 (2a) | Add `trading_signals:shared_pg_backup` to `BACKUP_DATABASES` in the shared-postgres repository (PR there); one supervised run; isolated restore test from Google Drive | other project + off-host transfer | remove the line; **the uploaded snapshots are not undone by removing it** |
| 4 (2a) | Remove `trading_signals` from the xsch backup (twitter-scheduler project's change) | other project | re-add |
| 5 | Disable the p1bg v1 cron line only; keep all files | cron | restore the saved crontab |
| 6 | Isolated restore test of the chosen nightly `trading_signals` copy (throwaway container, no shared network, structural checks only, no outcome reads) | isolated restore | teardown |
| 7 | Encrypted off-host copy of the current release recovery set and image archives | off-host transfer | not reversible |
| 8 | Evidence policy: accept the window, or on-demand snapshots | decision | — |
