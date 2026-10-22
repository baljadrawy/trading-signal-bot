# Stage B: approval request for the Class B pre-gate database read

**Status: request only. No database query has been run.**

## Why a read is needed

`docs/ops/COMPOSE_OPERATIONS.md` (Class B, gate 2) requires the Paper halt state to be verified **from the database**
before any recreate, and re-verified afterwards. The halt state cannot be stated from documents. The note of
2026-10-20 says the loss-streak halt is not stored: `shared/risk_epoch.py` recomputes it from `trade_results` at every
admission. Only the administrative pause (`risk_management`) is stored.

Stage B recreates **signal_engine only**. It does not touch the risk tables, trade_tracker or admission code. The read
has one purpose: to prove that the operational risk state is **the same before and after** the recreate, and that
nothing has to be held while the recreate happens.

## Disclosure (OD-7)

The halt boolean is a function of the tail of net results in `trade_results`. After the freeze, those are the
**sealed holdout outcomes**. Even a boolean-only read therefore discloses about **one bit** about sealed outcomes:
whether the effective tail streak is ≥ `STOP_ON_CONSECUTIVE_LOSSES`. The open-position count used to tell
`LOSS_STREAK_HALTED` from `LOSS_STREAK_RECOVERY_REQUIRED` would disclose more, so it is **not requested**. No row,
amount, count, timestamp or symbol is read or printed.

## Exact request (choose one)

**R-B1 (recommended): production logic, two booleans only.** It is one read-only process in the existing trade_tracker
container, with the same code and configuration that admission uses:

```bash
docker exec trading_tracker python -c "
import asyncio
from shared.database import Database
from shared import risk_epoch as R
from shared.trading_state import get_pause_state
async def m():
    await Database.connect()
    try:
        halt = await R.loss_streak_halt_active()
        paused, _ = await get_pause_state()
        print('halt_active=' + str(halt) + ' admin_paused=' + str(paused))
    finally:
        await Database.disconnect()
asyncio.run(m())"
```

- It prints exactly two booleans.
- It writes nothing and takes no advisory lock: `loss_streak_halt_active` is the unlocked telemetry path.
- It is run twice: before the recreate, and after the post-checks pass. Both outputs must be identical.
- Names were verified against the running trade_tracker image `2cf1dd52…` by reading code: `Database.connect` / `Database.disconnect`, `risk_epoch.loss_streak_halt_active`, `trading_state.get_pause_state`. `get_pause_state` fails closed: a missing risk row reads as paused.

**R-B2: psql, pause flag only (no outcome bit).** This reads only the administrative pause. The halt bit is then
**not** verified, and the gate is satisfied only if you explicitly accept that the halt state, which Stage B cannot
change, is recorded as "not read (OD-7)".

```sql
BEGIN TRANSACTION READ ONLY; SET LOCAL statement_timeout = '5s';
SELECT COALESCE((
  SELECT NOT (is_trading_paused IS FALSE AND pause_reason = 'manual_resume'
              AND NOT (date IS NULL OR date > CURRENT_DATE))
  FROM risk_management
  WHERE is_trading_paused = true OR pause_reason = 'manual_resume'
  ORDER BY date DESC NULLS FIRST, id DESC LIMIT 1), true) AS admin_paused;
COMMIT;
```
It returns one boolean with the exact `get_pause_state` semantics. The only "not paused" outcome is a valid-dated
`manual_resume` row with `is_trading_paused = false`. Everything else is paused (fail-closed), including no row, a
future or NULL date, a NULL flag, or a paused row marked `manual_resume`. It selects none of the outcome columns
(`wins`, `losses`, `consecutive_losses`, `daily_pnl_percent`) that `risk_management` also contains.

**R-B3: gate amendment.** You declare that for signal_engine-only changes that touch no risk table and no admission
code, gate 2 is satisfied without a database read. This changes the operating policy and needs your written decision.

## What approval must name

- the option (R-B1, R-B2 or R-B3);
- that it is allowed twice (pre and post) for Stage B only;
- that the result may be recorded in the Stage B evidence folder (mode 700) and in the final report as booleans only.
