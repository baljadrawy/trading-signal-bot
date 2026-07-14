# Measurement-Layer Fix — Design Spec

**Date:** 2026-07-15
**Branch:** `fix/measurement-layer-2026-07-15`
**Status:** Approved (design), pending implementation plan
**Scope owner:** Basim (paper-trading only — `PAPER_TRADING=true`, never change)

## Problem

The 2026-07-14 falsify-first audit (36 agents) of the live-learning cohort (479 closed
paper trades, 2026-06-26→07-14) found the recorded trade data is not a faithful record of
tradeable outcomes, so every metric the learner computes — gross/net, per-cell, aggregate —
is corrupted. Two root-cause defects in the recording pipeline are in scope here:

### Defect 1 — Pseudo-replication (same setup counted many times)
The scanner/signal_engine re-emits the **same** `(symbol, timeframe)` setup every scan
(~every 2h) because a 1d/4h candle persists across scans. Each emission is a **new
`signals` row** with a fresh `id`. `trade_tracker.register_new_signals()` already blocks a
new trade while one is **open** for the symbol (lines 183–186), but a fast trade closes
within minutes (the 4.8-min poll floor), freeing the symbol so the **next identical signal
re-registers**.

Evidence — HMSTRUSDT 1d @ entry `0.00025680`, 2026-07-04: signal_ids 13242, 13245, 13246,
13248, 13251, 13254, 13256, 13257, 13258, 13259, 13261, 13262 — **12 distinct signal rows
~2h apart**, each opening and closing at **+6.60%** within ~10 min. Economically this is
**one** position captured 12×. The same mechanism multiplied losses on 07-05 (entry
0.00033850: −1.21, −7.03, −7.39, −11.99…).

Impact: ~31% of cohort rows are clones by `(symbol, timeframe, entry_price)`, ~64% by
`(symbol, day)`. Collapsing `(symbol, entry)` drops N 479→369 and gross −$200→−$42.
Effective sample size ≈ ⅓ of nominal, so every WR / expectancy / CI / t-test is on
non-independent duplicates.

### Defect 2 — Stop overshoot (losses booked at poll price, not the stop)
In `trade_tracker.evaluate_trade()`, when `current_price <= eff_stop` (lines 302–317) the
exit is booked at the polled `current_price`, which can be far below the stop after a gap
(MANTA −33.8% on a −5% stop; ALLO −23.8% on a −3% stop). Meanwhile **wins are booked at
the clean target level** (line 296 uses `cfg.target_3`, not `current_price`). This
asymmetry — idealized capped wins vs unbounded overshoot losses — inflates the loss tail:
186/193 stop-hits filled worse than the stated stop; 32 catastrophic (<−8%) trades =
−$240 alone exceed the entire net loss.

## Non-goals (explicitly deferred)
- Fee-blind gate (`THROTTLE_EXPECTANCY=0` on gross expectancy) — separate later change.
- Neutralize/revert commit `4f84717` (momentum→reversion flip) — separate later change.
- Suppressing duplicate signal emission / Telegram spam at `signal_engine` — optional
  upstream tightening, deferred (the trade-level guard already cleans what the learner
  consumes).
- No real-money execution. No auto-deploy.

## Design

Two localized code fixes in `trade_tracker/main.py` + one offline validation oracle.
All changes are behind explicit rebuild/deploy — running containers are unaffected until
`docker compose build/up` is run by the user.

### Fix 1 — Duplicate guard (one trade per (symbol, timeframe) per candle period)
In `register_new_signals()`, add a guard: do **not** register a new trade for
`(symbol, timeframe)` if a trade (open **or** closed) for the same `(symbol, timeframe)`
was opened within the last candle period (a **rolling cooldown**, not boundary-aligned —
chosen for simplicity; it yields at most one trade per symbol+tf per candle-length).

- `candle_seconds`: `15m`=900, `4h`=14400, `1d`=86400. A small helper maps timeframe→seconds.
- Guard predicate: block if there exists an `active_trades` row (any status) for the same
  `(symbol, timeframe)` with `opened_at > NOW() - candle_seconds(timeframe)`.
- Note: `active_trades` rows persist with `status='closed'` after close (not deleted), and
  carry `timeframe` and `opened_at`, so this predicate sees the fast-closed duplicates.
- Implemented as an added `NOT EXISTS` clause in the `register_new_signals` SELECT (or an
  equivalent per-row check), consistent with the existing `NOT EXISTS` guards.
- Result: HMSTR 07-04 → 1 trade instead of 12; a genuinely new setup on the next candle
  (>24h later for 1d) is still allowed.

### Fix 2 — Model stop fill at the stop level
In the `current_price <= eff_stop` branch, book the exit at the stop, not the overshoot:

```python
STOP_SLIPPAGE = 0.001  # 0.1%, configurable
fill_price = eff_stop * (1 - STOP_SLIPPAGE)
profit_pct = ((fill_price - entry) / entry) * 100
exit_price = fill_price
```

- Restores win/loss symmetry (wins already booked at target level).
- Applies to the dynamic-stop branch only. Time-based exits (24h / expiry) and the
  `MAX_OPEN_TRADES` forced close remain at market `current_price` (correct — they are
  genuine market exits, not stop fills).
- `STOP_SLIPPAGE` default 0.1% (approved). Slippage is subtracted so the fill is slightly
  worse than the stop (realistic), never better.

### Validation oracle (offline, non-destructive)
A script under `research/` run in `research/skill_application/.venv` that re-prices the
existing recorded trades with the same two rules and reports before/after on the 479-cohort:
- **Dedup:** collapse `(symbol, timeframe, candle-bar)` to the first trade.
- **Stop re-pricing:** for `stop_hit` trades, recompute profit at the stop level
  (approximate `eff_stop`: `stop_loss` for `target_reached=0`, break-even=entry for
  `target_reached≥1`) with the same 0.1% slippage.
- Output: corrected N, WR, gross, net@0.6%, per trade_type, per cell — the "true" picture,
  and the expected values used to anchor the unit tests.
- Reads the DB read-only; writes nothing to DB.

## Testing (TDD)
Unit tests in `tests/` following existing patterns, run via
`research/skill_application/.venv/bin/python -m pytest tests/ -q`:
- **Duplicate guard:** 12 identical `(symbol, tf, entry)` signals within one candle → 1
  registered trade; a signal after the candle window → allowed.
- **Stop pricing:** a poll `current_price` 20% below the stop → exit booked at
  `stop*(1−slippage)`, not at −20%; win/target path unchanged; time-exit path unchanged.
- Tests written before the implementation edits (red → green).

## Rollout
- All work on `fix/measurement-layer-2026-07-15`.
- No container rebuild/deploy in this task. After tests pass and the oracle confirms the
  impact, deployment (`docker compose build trade_tracker && up -d`) is a separate,
  explicit, user-authorized step.
- The freeze and paused review-cron stay as they are.

## Success criteria
- Unit tests pass (red→green).
- Oracle reproduces the audit's dedup/stop-repricing impact numbers.
- Diff limited to `trade_tracker/main.py`, new test file(s), and the oracle script — no
  unrelated changes.
