# tsb-p1bg nightly backup: INSTALLED HISTORICAL BASELINE

> **Installed historical baseline — nightly backup currently failing. R-1 repair not included.**

- `tsb-p1bg-backup.sh` here is the exact script installed on the production host at `~/ops/tsb-p1bg/tsb-p1bg-backup.sh`. It was imported verbatim in commit `83a3bff`: sha256 `bfc99a954fbfd0b592e092dacaf2f1f17a346dd9519f4bce49a89284a16011cd`, re-verified against the installed file on 2026-10-18.
- It runs from the user crontab at 04:53 Europe/Berlin and logs to `~/backups/tsb-p1bg/backup.log`. **It has failed every night since 2026-10-10.** The last good set is 2026-10-09; it is preserved at `~/backups/tsb-p1bg-preserved/20261009T025301Z`.
- **R-1, the reviewed repair, is NOT in this directory and is NOT installed.** Its sealed candidate, rollback copy and approval gates (G0–G3) live outside the repository (`~/ops/tsb-r1-backup-repair/`). Installing it needs separate owner approval.
- The A41 consistent-backup v2 (branch `fix/p1bg-consistent-backup-a41`, `5a6d72a`) is a different, unapproved design. It is also not included.
- This file records provenance only. **Do not install, schedule, repair or run anything from this directory.** Production backups are changed only through the R-1 gates.

Checks run for this record (2026-10-18): `bash -n` OK; `shellcheck` (all severities) produced 0 findings. The script was not executed.
