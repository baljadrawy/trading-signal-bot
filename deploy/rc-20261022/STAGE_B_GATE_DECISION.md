# Stage B: Class B gate 2 without reading sealed outcomes (R-B3 evaluation)

**Status: design decision for the owner. Stage B stays on HOLD.** No database was read. No Paper container was
touched.

## Question

`COMPOSE_OPERATIONS.md` gate 2 requires the PAPER_HALTED/B3 state to be verified from the database before and after
a Class B step. For Paper, the loss-streak halt is computed from `trade_results`, which after the freeze are the sealed
holdout (OD-7), so even a boolean read discloses about one bit. Can a **signal_engine-only** deployment satisfy the
*purpose* of gate 2 without reading that state?

## Purpose of gate 2

A Class B step must not change, or act during an unknown change of, the risk posture: the hard loss-streak halt, the
administrative pause and B3. For a deployment, that means **the risk state after the step equals the state before**,
and the step must not open a path that bypasses it.

## Proof for RC-B (`sha256:11e81d5d…`) vs running signal_engine (`sha256:c5be4e34…`)

| # | Claim | Evidence |
|---|---|---|
| P1 | The halt and pause are **decided at admission in trade_tracker**, from `trade_results`, `risk_recovery_events` (`shared/risk_epoch.py`) and `risk_management` via `get_pause_state` (`shared/trading_state.py`). signal_engine is not on that path. | code: `risk_epoch.loss_streak_halt_active`, `trading_state.get_pause_state`; trade_tracker `main.py` admission |
| P2 | signal_engine never writes `trade_results`, `risk_recovery_events` or `active_trades`. | `validation/halt_invariance_inventory.py` on both images: the only halt-table write is the next row |
| P3 | Its only halt-table write, `INSERT INTO risk_management (date, signals_sent) … ON CONFLICT (date) DO UPDATE SET signals_sent = signals_sent + 1`, cannot change the pause decision. `get_pause_state` only considers rows with `is_trading_paused = true OR pause_reason = 'manual_resume'`. A new row takes the defaults (`false`, NULL) and is never selected; an existing row only has its counter changed. | the SQL above; `get_pause_state` source (verified in the running image) |
| P4 | RC-B's halt-relevant code is **identical** to the running image: same write set, and no import of `risk_epoch` / `trading_state` in either. | inventory comparison: `writes+imports identical: True`. `signal_logic.py` differs only in the one telemetry keyword line (#74). A mutation (an injected `UPDATE risk_management SET is_trading_paused …`) is detected. |
| P5 | Any signal emitted around the recreate still has to pass trade_tracker admission, which is unchanged. The halt therefore remains enforced, fail-closed, whatever its value. | trade_tracker container not in scope; identity checked before and after |

**Conclusion: R-B3 is safe for RC-B.** The deployment cannot change, bypass or depend on the halt state differently
from today, so the purpose of gate 2 is met by **proof of invariance** instead of **observation of state**. No safety
invariant is weakened: the halt keeps being enforced exactly where it is enforced today.

## Conditions (all required; otherwise the full gate 2 applies)

1. The target is **signal_engine only**. trade_tracker, telegram, analyzer, scanner and postgres keep their identity
   (container ID, image, StartedAt, RestartCount), checked before and after.
2. `halt_invariance_inventory.py` gives identical writes+imports for candidate vs running. The diff of the candidate is
   limited to the approved files (RC-B: 3 files, see `RELEASE_CANDIDATES.md` §3).
3. The other gate-2 items are verified without outcome data:
   - learner stopped (container absent/stopped, Class A);
   - `PAPER_TRADING=true` via `ops/provenance/drift_check.py` D8 (the value is compared in memory, never printed).
4. No trade_tracker log line about risk-guard decisions is read or reported (it would disclose the halt bit).
5. The owner records the amendment in writing (this file + the Stage B approval). It is scoped to "signal_engine
   changes whose halt inventory is unchanged".

## Non-leaking alternative if R-B3 is not accepted

**R-B2** (`STAGE_B_DB_READ_REQUEST.md`): read only the administrative pause flag, which carries no outcome information,
and record the halt bit as "not read (OD-7)". This is weaker than R-B3: it observes one input but cannot prove the
others unchanged. R-B3's invariance proof is the stronger guarantee.

## Owner decision needed

Accept R-B3 for RC-B with the conditions above, then a separate Stage B deployment approval. Until both are given,
Stage B stays on HOLD.
