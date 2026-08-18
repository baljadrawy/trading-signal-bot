# Telegram trade lifecycle — 2026-08-18

## Message semantics

- A **candidate** is an analyzed setup. It is not an open trade.
- Whitelisted candidates pass silently to the portfolio risk guard.
- A Telegram **opened** message is emitted only after an `active_trades` row is
  committed. It includes the fill price, size, stop, targets, timeframe, and
  paper/live mode.
- Target notifications describe the protection change at T1 and T2. T3 emits
  only the close notification to avoid duplicate messages.
- A **closed** message is emitted only after `trade_results` is committed. It
  reports entry, exit, reason, duration, gross P&L, estimated round-trip cost,
  and net P&L.

## Delivery guarantees

Trade Tracker writes `trade.opened`, `trade.target_hit`, and `trade.closed` to
the transactional outbox in the same database transaction as the lifecycle
change. Telegram claims and acknowledges each event. The existing outbox unique
key makes these messages idempotent across service retries.

This applies to lifecycle events created after deployment. Historical closed
trades are not replayed automatically.

An automatic hard-risk transition also writes `risk.halted`. Telegram reports
the trigger and current daily, weekly, drawdown, and loss-streak measurements.
The event is created only on the running-to-halted transition, so repeated risk
checks do not spam the operator; a later resume and new halt creates a new event.

## Pause semantics

`/pause` blocks scanning/admission of new trades but does not stop monitoring or
closing existing positions. The explicit pause survives UTC date rollover until
`/resume` writes an explicit resume marker. `/status` and `/daily` use this
persistent state rather than only today's risk row.

## Operator checks

- `/status`: persistent operating state, reason, actual open trades/capacity.
- `/daily`: candidates, risk-guard handoffs, actual opens/closes, and net P&L.
- `/trades`: current positions and recent net results.
- `/signals`: recent candidates; the heading explicitly says they are not open
  trades.
