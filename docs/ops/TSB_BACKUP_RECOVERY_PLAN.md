# Trading bot backup: diagnosis and recovery plan (R1, 2026-10-18)

**Status: PLAN.** Nothing in this document has been executed except the read-only checks marked *verified*. No backup was repaired, scheduled, moved, deleted or restored. Every action in section 5 needs the separate owner approval listed in section 7.

## 1. Scope

The trading bot's own data:
- the PostgreSQL database `trading_signals` in the shared cluster (container `postgres`);
- the evidence files `data/evidence_v2` (and the older `data/evidence`) in the production checkout.

Not in scope:
- other projects' databases;
- the research collector dataset (it has its own sealed-day backup);
- protected research outcomes. Those are never read by any step in this plan.

**Coverage today (verified 2026-10-18):**

| Mechanism | Covers `trading_signals`? | Off-host? | State |
|---|---|---|---|
| `ops/tsb-p1bg/tsb-p1bg-backup.sh` v1 (cron 04:53 local) | Yes: DB dump plus `evidence_v2` archive | No | **Failing since 2026-10-10** (one earlier failure on 10-07) |
| shared-postgres `backup-run.sh` (cron 03:23) | **No**: the shared-postgres compose file states `trading_signals` is out of scope; it dumps cluster roles and other projects' databases | Yes (rclone) | OK on 2026-10-18 |
| Manual A56 recovery dumps (2026-10-16) | Yes | No | Checksums verified |
| Local restic repository `~/backups/tsb-restic` (Phase 0, 2026-09-27) | Snapshot of that date | No | Not inspected here (needs its key) |

## 2. Diagnosis (evidence: `~/backups/tsb-p1bg/backup.log`, the installed script)

- **Symptom:** every night since 2026-10-10 logs `FAIL set=<ts>: evidence archive failed`.
- **Immediate cause:** `tar` reports `evidence_v2/<service>: file changed as we read it` for `analyzer` (all 10 failing nights) and also `signal_engine` (10-12 to 10-15, 10-17, 10-18).
  - Those services append to their evidence files continuously.
  - `tar` therefore exits non-zero.
  - v1 treats any non-zero exit as a failure (`tar … || fail`), which is **correct fail-closed behaviour**. Accepting tar exit 1 wholesale was rejected in R-1.
- **Why it got worse:** the failures follow evidence growth. The size of the evidence archive in the last successful set was 8.1 MB on 10-09; the failed attempts' archives grew from 11.6 MB on 10-10 to 34.3 MB on 10-18. A larger archive takes longer, so a write during the read becomes near-certain.
- **Consequence:**
  - v1 dumps the database **first**: `pg_dump`, then a `pg_restore --list` table-of-contents check, then a check that `signals` table data is present.
  - It archives the evidence only after that.
  - A tar failure therefore aborts the whole set before checksums and promotion.
  - The night's valid-looking DB dump is left in an unpromoted `.incomplete-<ts>` folder with a `FAILED` marker, outside the set model.
  - Retention runs only after a successful promotion, so **no existing set has been deleted by the failures.**
- **Not the cause:** database access, disk space, locking and the dump itself. The DB dumps and their table-of-contents files exist for every failed night.

## 3. Existing recovery points (read-only verification, 2026-10-18)

| Recovery point | Content | Verification today |
|---|---|---|
| `~/backups/tsb-p1bg/sets/20261002T025301Z` … `20261009T025301Z` (7 sets) | DB dump plus evidence archive, sealed | `sha256sum -c SHA256SUMS` **7/7 OK**; `tar -tzf` evidence archive **7/7 readable** |
| `~/backups/tsb-p1bg-preserved/20261009T025301Z` | Byte copy of the 10-09 set, kept outside retention | `SHA256SUMS` OK |
| `~/backups/tsb-a565-recovery-20261016T210334Z` | Newest sealed DB dump (A56.5), restore-verified at the time | `SHA256SUMS` 5/5 OK |
| `~/backups/tsb-a562-recovery-20261016T200812Z` | DB dump (A56.2) | `SHA256SUMS` 5/5 OK |
| `~/backups/tsb-a565-evidence-20261016T210429Z`, `tsb-a564-evidence-20261016T204403Z` | Evidence copies | 158/158 and 157/157 OK |
| `~/backups/tsb-p1bg/.incomplete-20261007…` and `-20261010…` … `-20261018…` (10 folders) | DB dump (2.56–2.79 MB) with a non-empty table of contents; evidence archive from a moving source | **Unsealed:** no `SHA256SUMS`, not promoted, and the evidence archive is not a consistent snapshot. Possible DB recovery points only, after the checks in section 5 (step 2) |
| Image archives (release, rollback, scanner overlay) | See `deploy/a561-rel-ea8ae4f/ARCHIVE_REFERENCES.json` | Release 8/8, rollback 4/4 and 2/2 OK |

**Every recovery point above is on this host only.**

## 4. Consistency boundary (what one restore point means)

- **Database:** one `pg_dump --format=custom` is a single consistent snapshot of `trading_signals`. It covers no other database and no roles; the cluster roles are in the shared-postgres backup.
- **Evidence:** the files are append-only JSONL. The R-1 candidate copies them consistently by cutting each file at its last newline and re-checking that prefix. That is consistent **per file**, not across files.
- **There is no atomic point across the DB and the evidence** (also recorded in A56.4). A restore pairs a DB dump with the evidence copy from the same run, and accepts a skew of seconds. The restore test (section 6) must measure and record that skew. It never "repairs" one side to match the other.
- **Secrets, `.env` and image archives** are separate recovery inputs and are not in the p1bg set.

## 5. Recovery plan (prioritized; each step needs its own approval)

| # | Step | Action class | Acceptance criterion |
|---|---|---|---|
| 1 | Keep every existing set, preserved copy, `.incomplete-*` folder and A56 dump **untouched**; record their hashes in an inventory outside the backup folders | Read-only plus one new file | Inventory lists each item with its sha256. Nothing under `~/backups` changes |
| 2 | Qualify the newest `.incomplete-*` DB dump (10-18) as a DB-only recovery point: hash it, then run `pg_restore --list` with an isolated client (not in the production `postgres` container) | Isolated | Table of contents readable; `schema_migrations` entries for 010 and 011 present; recorded as "DB-only, unsealed" |
| 3 | Install R-1, the reviewed repair, through its existing gates: G0 read-only preflight; G1 install with rollback ready; G2 one supervised run outside 03:00–05:00; G3 the next scheduled run logs `OK set=` | Production change (backup script) | G2 and G3 `OK set=`; `verify` passes; rollback copy `bfc99a95…` ready |
| 4 | Watch retention after R-1: KEEP=7 then removes the oldest v1 sets one per successful night. The 10-09 set is preserved outside retention | Observation | Preserved copy still verifies; the number of sets never drops below 7 verified ones |
| 5 | Add failure alerting for the nightly backup (today it only writes to its log) | Code or ops change | A failed run produces an owner alert the same morning |
| 6 | Off-host copy (section 8) | External transfer | Encrypted copy verified off-host; key not stored with the copy |
| 7 | Isolated restore test from the off-host copy (section 6) | Isolated | All checks in section 6 pass |
| 8 | Schedule decision (CP-9, 05:23 local, proposed in the R-1 evidence) | Cron change | Separate decision after step 3 |

## 6. Isolated restore test (design only)

**Isolation:**
- a throwaway `postgres:16.15-alpine3.24` container with a unique name, a scratch volume, **no published ports** and **no shared networks** (not `shared_db_net`);
- created and removed only with owner approval;
- never the production `postgres` container or cluster.

**Inputs:** one sealed set (or the A56.5 dump) plus its evidence archive, copied read-only into a scratch directory.

**Checks** (structural only; **no query on outcome or holdout tables**):
1. `sha256sum -c SHA256SUMS` passes on the copy.
2. `pg_restore` into an empty database exits 0, with no errors in its log.
3. `schema_migrations` has the expected rows, including 010 and 011 with their recorded checksums. `REQUIRED_SCHEMA_VERSION` from `shared/schema.py` matches.
4. The table list equals the dump's table of contents. Object counts (tables, indexes, constraints) are recorded. Row contents are not read.
5. The evidence archive extracts. The per-file sizes and hashes match its listing. Event contents are not read.
6. The skew between dump time and evidence cut is recorded (section 4).
7. Teardown: the container, volume and scratch copy are removed, and the removal is verified.

**Pass:** checks 1–5 succeed, and checks 6–7 are recorded.

## 7. Operations that need separate owner approval

1. Writing the hash inventory file (step 1).
2. Any `pg_restore --list` or restore, in an isolated container only (steps 2 and 7).
3. R-1 G1 install, G2 supervised run and G3 acceptance (step 3).
4. Any cron or schedule change, including CP-9 and removal of the expired A56 soak line.
5. Backup failure alerting (step 5).
6. Any off-host transfer, and the choice of destination and encryption key custody (step 6).
7. Deleting or moving anything under `~/backups`. **Never part of this plan.**
8. Any read of the production database, even read-only, beyond what the existing operations policy allows.

## 8. Off-host storage requirements

- **Encryption:** encrypted before it leaves the host (for example a restic repository). The key is held by the owner outside this host and is never in Git or on the destination.
- **Destination:** owner decision. An rclone `gdrive` remote is already configured on this host for shared-postgres. Reusing it is possible but needs a decision on sharing credentials and quota with another project.
- **Contents:**
  - the sealed p1bg sets;
  - the A56 dumps and evidence copies;
  - the release and rollback image archives;
  - a `git bundle` of the repository.
  - **Not** `.env` or other secrets. Those go to the owner's own secret store.
- **Integrity:** verify after upload (`restic check --read-data-subset` or equivalent). Do a periodic restore test (section 6) **from the off-host copy**.
- **Retention:** at least the newest 7 daily sets, plus each release's archives until two later releases exist.
