# Signal-aware execution and stop architecture — 2026-08-18

## Scope

This policy applies to new paper trades created with
`exit_policy_version=partial_25_50_25_v1`. Existing open trades remain
`legacy_full`; their stop and accounting semantics are not changed mid-trade.

## Entry policy

- Reject when the observed price is at/below the greater of the hard stop and
  signal invalidation level.
- When price is at/below the planned entry but still valid, record a market
  paper fill at the better observed price.
- When price is above planned entry, wait at the planned limit instead of
  chasing. The 30-second backup checker reevaluates pending candidates.
- Momentum and reversion have separately labelled decisions so future
  execution-quality review can segment them.

No authenticated Binance order is placed. This remains paper execution.

## Initial stop policy

- Momentum thesis: prior breakout high. Candle invalidation is below that level.
- Reversion thesis: recent 20-bar structural low.
- Add a 0.25 ATR invalidation buffer and require at least one ATR of hard-stop
  noise distance.
- If the required structural risk exceeds the timeframe cap, reject the setup;
  never pull the stop inside thesis invalidation merely to satisfy a cap.

Timeframe caps remain: 15m 2%, 1h 4%, 4h 5%, 1d 3%.

## Two-layer stop handling

1. A closed candle on the signal timeframe below `stop_invalidation` invalidates
   the thesis. This avoids exiting on every transient wick.
2. The deeper precommitted hard stop is checked tick-by-tick over WebSocket.
   It always overrides candle confirmation and is never widened after entry.

After T1 the net-break-even stop overrides initial signal invalidation. After
T2 the stop is `max(T1, peak - 2.5%)`. T3 is terminal.

If an observed tick gaps below a stop, paper execution uses the worse observed
tick plus configured stop slippage. It does not assume an ideal fill at the
original stop.

## Price monitoring and recovery

- One Binance WebSocket connection dynamically subscribes to `aggTrade` for
  every open symbol.
- Aggregate trade ids reject duplicate/out-of-order messages.
- A bounded RAM queue and price cache keep network reads out of tick handling.
- Reconnect backoff is 5, 10, 20, 40, then 60 seconds.
- Outages under one minute are log-only. Longer outages and recovery emit
  Telegram events.
- REST checks every 30 seconds provide an independent fallback.
- On restart, open trades are reloaded from PostgreSQL, subscriptions are
  rebuilt, and Telegram receives a recovery count.

## Partial exits and accounting

Default distribution is T1 25%, T2 50%, T3 25%. Binance `MIN_NOTIONAL` is read
from `exchangeInfo` and cached. If T1 or T3 is below the minimum, its fraction
is merged into T2.

Every target tranche is recorded once in `trade_target_fills`. The active trade
stores remaining fraction and realized gross P&L. The terminal `trade_results`
row combines realized tranches with the remaining terminal fill. Round-trip
cost continues to be charged against the full original notional when reporting
net P&L.

## Safety invariants

- Hard stop has highest priority.
- Stops never move down after entry.
- Per-trade locks serialize WebSocket and REST evaluation.
- `_closing` prevents duplicate terminal processing.
- Database uniqueness prevents duplicate target fills and terminal results.
- No learned gate may modify stop placement; this policy is versioned and fixed
  for its canary cohort.
