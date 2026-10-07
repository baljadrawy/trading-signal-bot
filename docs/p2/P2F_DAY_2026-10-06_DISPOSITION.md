# P2F dataset `p2-forward-continuous-v1`: disposition of calendar day 2026-10-06

**Status:** owner-approved disposition, recorded 2026-10-07 (P2F 1.5.0 controlled-deployment window).
**Nature:** a NON-MUTATING record. It changes no lifecycle artifact, no seal, no incident record and no data. It is
stored in this repository and as a read-only file in the deployment evidence
(`backups/tsb-aiohttp-20260929T122701Z/p2f-150-deploy-20261007T110514Z/disposition/`), never inside `seals/`.

## 1. The failed lifecycle stands (immutable)

| Artifact (dataset-relative) | SHA-256 |
|---|---|
| `seals/2026-10-06.FAILED-1791335968422.report.json` (seal job 2026-10-07 01:17–01:19:28Z, verifier `verify-continuous-v1` 824b002d…) | `1a20663fc38b6eb8c91f072a57dad08b72741a550fa0fa0a3de07d49e1be3c41` |
| `incidents/external/seal-2026-10-06-1791335968422.json` (`result: FAIL`, `HEALTH_HISTORY_HOLE: 1`, CRITICAL) | `27f13a5944fbed734603703ac0cbc99c2987c30a735083b3a4e2d06309ddf135` |
| `days/2026-10-06.json` (day close: 186 segments, 289,814,334 bytes) | `1e0c7608bb1c0a0266a118144ab8483a86167732d8b6e3e7f9d52eedd076ae1d` |

- The original FAILED seal remains immutable. It is not re-sealed, edited, exempted, converted to PASS or
  superseded by this note.
- There is no `seals/2026-10-06.json`, no sealed-day backup and no restore-test for this day, and none will be
  produced under the current protocol (the seal job's FAILED-* guard prevents a retry, by design).

## 2. What failed, and why it is real

- The single failing check is `HEALTH_HISTORY_HOLE`: boot `6fd4edbc`, health records 11:19:33.621Z → 11:21:48.813Z
  (`1791285573621 → 1791285708813`), a gap of **135.192 s against a 75 s limit** (60 s record interval + 15 s).
- The hole is real. It coincides with the collector writer stall that preceded the fail-closed termination of run
  `6fd4edbc`: the next health record (11:21:48.813Z) is already DEGRADED (`writer_stale`), the CRITICAL
  `failclosed:writer_stalled` incident opened at 11:22:05.357Z (beat age 100,741 ms), and the run stopped at
  11:23:02.862Z.

## 3. What the investigation found for the rest of the day

- Every other check of the day's seal report was clean: `unexplained` 0, `downtime_crash` 0, candles
  `unexplained_missing` 0, persisted 2,285,320, gap-covered 5,628, startup-excused 117; manifest and day-close
  checksums matched (`seq-reset-investigation-20261007T081541Z/06_lifecycle_2026-10-06_verification.txt`).
- The known outage is explicitly represented: downtime `stopped_failed` from 11:23:02.862Z to 12:26:33.664Z
  (3,810,802 ms), previous boot `6fd4edbc`, next boot `b1b7edb6`.
- These findings describe the day; they do **not** override the failed lifecycle.

## 4. Disposition

1. 2026-10-06 is **NOT Alpha-eligible** under the current protocol (`P2D_ALPHA_RESEARCH_PROTOCOL.md`, "Eligible
   days": a seal result of PASS that the reader accepts in sealed mode; this day's seal result is FAIL). It is a
   skipped day and must be listed as such.
2. This disposition does not convert, exempt or reinterpret the failed seal. The `HEALTH_HISTORY_HOLE` result is the
   historical truth of the day.
3. Any future reviewed re-seal or disposition framework (for example a verifier exception class) is **prospective**:
   it must be reviewed and approved separately, and it must preserve this result, the FAILED report and the
   external incident unchanged. It may add records; it may not replace these.
4. The CRITICAL incident `inc-1791335970908-b1b7edb6-3` (`external:seal-2026-10-06-1791335968422.json`) is to be
   acknowledged by reference to this disposition, only inside the controlled 1.5.0 deployment window, after the clean
   stop and before the start (hash-bound ack via `p2f_incident_ack.sh`, owner approval B). As of this record it is
   NOT yet acknowledged (the 2026-10-07 deployment preflight stopped before the window). The acknowledgement closes
   reviewed operational state; it does not rewrite history.
