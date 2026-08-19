# Indicator, regime, and execution correction — 2026-08-19

## Implemented

- Core indicators use one explicit `ta` implementation; the incompatible and silently-falling-back `pandas_ta` dependency was removed.
- StochRSI uses the canonical 14/3/3 configuration and RSI scoring includes the deeply oversold band.
- Market regime is point-in-time and uses ADX strength, EMA20 direction/slope, and normalized ATR percentile.
- Momentum entries are admitted only in bullish regimes. Mean reversion is admitted only in sideways regimes.
- Bollinger entry distance is normalized to band position instead of multiplying a price by a fixed percentage.
- Order-book failures are explicit (`valid=false`, `spread_pct=null`) and live selection rejects missing or excessive spread.
- Macro inputs fail closed when unavailable or older than `MACRO_MAX_STALE_HOURS`; errors are exposed in the snapshot.
- New trades receive timeframe-specific expiry policy `timeframe_v1`. Existing open trades retain legacy 48/24/24-hour semantics.

## Timeframe expiry v1 (new trades only)

| Timeframe | Maximum | Stalled after T1 | No T1 |
|---|---:|---:|---:|
| 15m | 48h | 24h | 12h |
| 4h | 96h | 48h | 24h |
| 1d | 240h | 120h | 72h |

These are operational starting points, not evidence of edge. Evaluate them only on clean forward samples, net of fees and slippage, segmented by strategy, timeframe, regime, macro state, and symbol.

## Measurement constraints

- Do not infer causal edge from the existing selected-signal history.
- Compare each strategy/regime route against a frozen baseline using temporal walk-forward splits.
- Primary metrics: net expectancy, profit factor, maximum drawdown, sample size, and confidence interval.
- Keep learning gates disabled until the clean forward sample is sufficient and the governance validator accepts the result.
