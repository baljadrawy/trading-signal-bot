# W3 contamination disclosure

## P2-G0 (2026-10-01) — W3 holdout guard

**Classification:** LIMITED SUMMARY-LEVEL CONTAMINATION.

- **What:** during the P2-DESIGN read-only discovery (2026-10-01), displaying the tail of
  `research/walk_forward_audit.log` unintentionally exposed one aggregate summary verdict line. It came from the
  automated walk-forward run of 2026-10-01 10:30 UTC.
- **Not done:** no individual trade rows were intentionally inspected. The verdict and its metrics are not
  reproduced in any P2 artifact. The log was not reopened in P2-G0.
- **Scope:** the whole W3 dataset is **not** considered opened. W3 remains SEALED.
- **Mitigation:** the automatic walk-forward access (user crontab line 2) was disabled in P2-G0 at 2026-10-01
  22:33:09Z, with its definition preserved.
- **Pre-existing:** the cron had been producing aggregate post-freeze summaries twice a day since the freeze. The
  last scheduled run was 2026-10-01 22:30 UTC, before the change; it was not triggered by P2-G0 and was not read.
- **Requirement:** every future report that evaluates W3 must carry this disclosure, together with the Research-1A
  disclosure.
