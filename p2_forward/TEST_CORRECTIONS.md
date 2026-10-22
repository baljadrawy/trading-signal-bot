# Post-import test corrections

The runtime source in this directory is imported byte-for-byte (`PROVENANCE.json`). This file lists the only **test** changes made after the import, so that the import stays auditable. No runtime file, host script, verifier, unit, compose file or configuration has changed.

## 1. `tests/test_p2cr_crash.py`: deterministic crash interval (2026-10-18)

| | Blob |
|---|---|
| Imported from `1bfb5f6` (recorded in `PROVENANCE.json`) | `9da705da1508f4cf76846324616b45218bc216a8` |
| After this correction | see `git log -- p2_forward/tests/test_p2cr_crash.py` |

**Symptom.** `CrashRestart.test_crashed_day_verifies_with_explicit_crash_downtime` failed on the GitHub x86 runner (2 of 2 runs, `downtime_crash` = 0) and had passed on the arm64 host.

**Root cause, verified.** It is a timing dependence in the test, not a collector or verifier defect.
- The verifier counts crash downtime per stream, at sample boundaries in `[last persisted sample + cadence, successor ws_start)`, and only those not accounted by an epoch.
- The imported test started the successor as soon as the killed process had exited. The interval therefore contained a boundary only if the kill's phase within the 1000 ms sample grid, plus the restart-to-ws_start latency, crossed the next grid boundary.
- Two diagnostic replays of the unchanged scenario **on the arm64 host** reproduced both outcomes:

| Kill phase in the 1000 ms grid | Successor ws_start after kill | Sum | `downtime_crash` | Day verification |
|---|---|---|---|---|
| 294 ms | 643 ms | 937 ms (< 1000) | **0** (the boundary was correctly counted as the successor's `startup_excused`) | PASS, unexplained 0 |
| 448 ms | 673 ms | 1121 ms (> 1000) | **29** (one per stream) | PASS, unexplained 0 |

So the failure is a race present on every architecture. It only showed up more often on the runner where it was observed.

**Correction (test-only).**
- After the SIGKILL, the test computes the next boundary of the minimum configured cadence after the moment the killed process is known dead. The config requires every cadence to be a positive multiple of 1000 ms.
- It starts the successor only after the wall clock has passed that boundary.
- Every persisted sample of the killed run is at or before that moment. So for a stream on the minimum cadence, `crash_end` ≤ the boundary < the successor's `ws_start`. The crash interval therefore always spans at least one sample boundary, which is the scenario this test exists to verify.
- A new assertion checks that precondition from the verifier's own run data: the successor's `lo` (its `ws_start`) is after the boundary.

**All original assertions are unchanged:**
- the kill happened mid-write;
- recovery is fail-closed and the run stopped cleanly;
- the downtime record says `crash_or_kill`, names the killed boot and has `clean_stop` false;
- `run_chain` has no failures;
- there is no 1970 gap;
- every day passes independent verification;
- `downtime_crash` > 0;
- `unexplained` = 0.

No downtime is fabricated, nothing is skipped or excluded, and the verifier is not bypassed.

## 2. `tests/test_p2f_rotation_e2e.py`: deterministic stale market copies (2026-10-22)

**Symptom.** `LaggingRotationEndToEnd.test_no_reset_no_regression_but_stale_copies_seen` failed about 1 run in 10, on `main` and on feature branches alike (A/B, 10 runs each, 2026-10-21). The failing assertion was `market_component_stale > 0`; the other assertions in the test passed.

**Cause (measured).** The fake exchange gave each socket its own phase for the market-array (miniTicker) stream: its creation time + 0.1 s, then every 1 s. A copy from the lagging socket is stale only when it arrives within 0.4 s (the lag) after the other socket's copy. The phase difference is fixed for each overlapping socket pair, so a whole overlap yields either a stale component on every tick or on none.

Per-overlap instrumentation (12 runs, 36 market-connection overlaps of 2.5–3 s each) recorded stale counts per overlap in {0, 32, 64, 96}, i.e. whole ticks of 32 symbols. **10 of 36 overlaps had 0**, and one run had 0 in all three overlaps; that run is the test failure. The collector was correct; the test's stimulus was random.

**Correction (test-only).** Every socket emits the miniTicker on a shared 1 s wall-clock grid, and a lagged socket emits 0.2 s after an unlagged one. During an overlap the lagged copy's `E` is therefore 0.2 s older than the copy just applied, and it arrives within the stale guard (`seq_catchup_timeout_s`). This holds in both directions (the replacement trailing or leading). The same instrumentation (12 runs, 36 overlaps): **0 of 36 overlaps with 0**, at least 2 stale ticks per overlap.

**All original assertions are unchanged.** No collector file changes. Book and depth stimuli are unchanged.
