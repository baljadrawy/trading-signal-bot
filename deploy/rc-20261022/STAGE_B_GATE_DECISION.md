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

## Runtime-safety validation (2026-10-22, owner request; read-only source and image inspection)

R-B3 is approved **for design only**. This section validates it against runtime behaviour. RC-B (`11e81d5d…`) differs from the running signal_engine in exactly 3 files. The running trade_tracker's `main.py`, `risk_epoch.py`, `trading_state.py` and `risk_management.py` equal the release source (md5), so the line numbers below hold for production.

| Aspect | Verdict | Evidence |
|---|---|---|
| Pending messages / delivery | SAFE | `save_signal` inserts the signal, upserts `risk_management.signals_sent` and enqueues `signal.ready` in **one transaction**. telegram claims `signal.ready`, checks the pause, marks the signal sent and enqueues `signal.delivered`; it never writes `active_trades`. The **only** INSERT into `active_trades` is in trade_tracker admission. Outbox leases are re-claimable after 300 s, and ack/defer/fail are owner-guarded. |
| Startup / reconnection / SIGTERM | SAFE | Startup is connect → `require_schema` → integrity mode → Binance client. Any failure exits before anything is emitted. There is no backfill: the loop reads only analysis rows from the last 30 min, and saves at most one signal per 60 s cycle. With no SIGTERM handler, `init: true` forwards the signal and Postgres rolls back any open transaction; at most buffered evidence is lost (RC-B forces a telemetry write only on a clean shutdown path). |
| Idempotency / duplicates | SAFE for positions; low risk for messages | A kill between commit and the `signal_generated` UPDATE can re-emit **one** duplicate signal row or Telegram message for a symbol. It cannot open a second position: the tracker takes one row per symbol, refuses when the symbol has an open trade, allows one trade per (symbol, timeframe) per candle, uses `ON CONFLICT(signal_id)`, and enforces `MAX_OPEN_TRADES`. `SIGNAL_INTEGRITY_MODE` is off, and the 2 h symbol cooldown is DB-backed. |
| Admission enforcement | SAFE | `assess_new_trade_risk` runs for every candidate. Pause is fail-closed (`get_pause_state`), the loss-streak halt is re-checked under `pg_advisory_xact_lock`, and `evaluate_new_trade` fails closed on non-finite values. |
| DB writes / side effects | SAFE | signal_engine writes `signals`, `risk_management.signals_sent` (date upsert of that column only), `outbox_events`, `analysis_results` and `service_heartbeats`. None of these is a halt or pause input. |
| Config / secrets | SAFE | The only addition is `EVIDENCE_TELEMETRY_MIN_INTERVAL_S` (default 0). The getenv dataclass ignores unknown variables, so a leftover variable is harmless after a rollback. A non-numeric value crashes RC-B at import, which fails safe. Cmd, user and workdir are identical. |
| Rollback | SAFE | No schema or DB change; the telemetry file format is unchanged. The production compose file pins `rel-ea8ae4f-r2`, so the deployment must change the `image:` line through a reviewed PR, and a plain `compose up` would revert to the running image. |
| Health / limits | SAFE | Healthcheck `python -m shared.health` every 60 s (max age 180 s). 512 MiB memory, 1.0 CPU, `unless-stopped`, read-only, `cap_drop ALL`, `init: true`. RC-B changes none of these. |

**Synthetic tests:** release-branch CI on `37a7c2c` passed the default suite and the disposable-PostgreSQL matrix (run 39742463015). In isolation, the RC-B image passed 35/35 recorder tests and the telemetry harness (`RELEASE_CANDIDATES.md` §4).

**Residual risks (none lets signal_engine bypass the halt):**
1. The live `risk_management` column default (`is_trading_paused DEFAULT false`) and the `UNIQUE(date)` constraint are taken from `database/init.sql` and unverified on the live DB. A **schema-only** read (`information_schema.columns` / `pg_constraint`, no row data and no outcome) would close this, but it needs owner approval.
2. One duplicate signal row or Telegram message is possible on a hard kill (no position impact).
3. Pre-existing, independent of signal_engine: the tracker re-checks the halt, but not the pause, under the advisory lock. The DB role is shared and over-privileged (A60; R-5 not applied), so the guarantee rests on code, not on DB permissions.

**Verdict:** proven from source. Recreating only signal_engine (RC-B, or a rollback) cannot bypass or alter Paper halt or pause enforcement. **Stage B remains NOT authorized for deployment.**
