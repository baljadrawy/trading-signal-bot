# P2-B certified W2 market data: specification (`p2b-market-v1`)

**Scope:** public Binance **spot** OHLCV for the W2 window `[2026-06-01T00:00:00Z, freeze)`, where the freeze is
`2026-08-19T09:33:46Z` (git `63da7d3`). This is market-data certification only: no strategy evaluation, no outcome
labels, W3 SEALED.

## Hard boundary (fail closed)
- **A candle is admissible only if `close_time < freeze`.** This is enforced in four independent places:
  1. Planning: `market_contract.archive_url` refuses any archive able to contain a post-freeze candle.
  2. REST acquisition: `endTime = last admissible open`, and the response is validated before it is written.
  3. Normalization: a post-freeze candle is a `FreezeViolation`, a hard failure, never an exclusion.
  4. Independent verification: `market_verify` scans raw, normalized, coverage and parity outputs.
- **Never acquired:** the 2026-08 monthly archive, the 2026-08-19 daily archive, and the 2026-08-19 1d candle
  (it never closed before the freeze).
- **Freeze day 2026-08-19:** REST `/api/v3/klines` (public, no key) is called with `startTime = 00:00` and
  `endTime` = last admissible open (15m: 09:15, 1h: 08:00, 4h: 04:00). Binance publishes no upstream checksum
  for REST, so the source is cross-validated against the checksummed 2026-08-18 daily archive for the same
  candles.
- **Outcome horizons that cross the freeze** are `RIGHT_CENSORED_BY_HOLDOUT`. No post-freeze candle is ever
  fetched to complete them.

## Sources and provenance
| Source | Use | Integrity |
|---|---|---|
| `data.binance.vision/data/spot/monthly/klines` | 2026-06 and 2026-07; lookback months for symbols absent from ds-0928 | upstream `.CHECKSUM` (SHA-256) required; re-verified at normalization |
| `data.binance.vision/data/spot/daily/klines` | 2026-08-01 to 2026-08-18 | same |
| `api.binance.com/api/v3/klines` | partial 2026-08-19 (and the 08-18 cross-check) | local SHA-256 plus field-level cross-check vs archive |
| ds-0928 (certified) | all history ≤ 2026-05-31 (lookback, seam) | per-file SHA-256 re-verified, not redownloaded |

- **Per artifact, the acquisition log records:** source, URL (no secrets), retrieval UTC, upstream SHA-256, local
  SHA-256, bytes, symbol, timeframe, period and status.
- **Statuses:** `UPSTREAM_VERIFIED`, `REST_VALIDATED_NO_UPSTREAM_CHECKSUM`, `SOURCE_UNAVAILABLE` (HTTP 404/400:
  not listed or delisted, never fabricated), `CHECKSUM_MISMATCH`, `DOWNLOAD_ERROR`.

## Request set (computed before any download; `market_plan`)
- **Universe:** the symbols of P2-A W2 decisions, plus W1 decisions whose label horizon runs past ds-0928, plus
  BTCUSDT and ETHUSDT (market context).
- **Timeframes:** all four (15m, 1h, 4h, 1d) per symbol, because the analyzer evaluates every timeframe per symbol
  (higher-timeframe context).
- **Lookback:** taken from ds-0928 when the symbol exists there. Monthly archives are planned only for symbols
  absent from ds-0928, back to `first decision candle − 202 bars`.

## Normalization (`market_normalize`; ds-0928 semantics)
- **Parser:** `research.data_governance.market.normalize_binance_klines`, which auto-detects ms or µs; the archives
  are µs from 2025.
- **Columns:** the base columns are identical to ds-0928 (`symbol, timeframe, open_time, close_time, open, high,
  low, close, volume, quote_volume, trade_count`) plus `source_kind, source_sha256`. No derived or future fields.
  The ds-0928 15m rolling-24h columns are not reproduced; they are P2-C features.
- **Close-time precision follows the source:** archive candles have `close = open + tf − 1 µs`; REST candles have
  `open + tf − 1 ms`.
- **Quarantine, never repair:** misaligned open, non-positive price, negative volume or trade count, invalid OHLC,
  close time outside the candle, conflicting duplicates (identical duplicates keep one), non-monotonic order.
  Gaps are recorded and never synthesized.
- **Deterministic:** stable sort, Parquet with no pandas metadata, a fixed codec, and a per-file content hash that
  is independent of serialization.

## Seam with ds-0928
Checked per (symbol, timeframe):
- schema type equality;
- no duplicate candle identity;
- monotonic order;
- step = exactly 1 bar from the last ds-0928 candle (2026-05-31) to the first P2-B candle (`SEAM_CONTIGUOUS`);
- otherwise `SEAM_DS_ENDS_EARLY` (the ds series stopped earlier) or `SEAM_GAP`;
- close-time and trade-count semantics are recorded.

## W2 decision coverage (`market_coverage`)
- **Classes:** `COMPLETE`, `FEATURE_READY_OUTCOME_CENSORED`, `INSUFFICIENT_LOOKBACK` (fewer than 200 closed bars),
  `SOURCE_GAP` (decision candle missing where acquisition was unavailable), `SYMBOL_UNAVAILABLE`, `AMBIGUOUS`,
  `OTHER` (e.g. an exchange gap at the decision, or missing horizon candles).
- **Higher-timeframe context:** the last closed candle of every timeframe at decision time exists.
- **Horizon:** the timeframe_v1 maximum hold (15m 48 h, 4h 96 h, 1d 240 h; 1h default 48 h). It is censored if it
  reaches the freeze.
- **Ambiguity:** decided only by runtime semantics. In every W2 analyzer version, `entry = round(close of the last
  closed candle, 8)`. A candidate is chosen only if exactly one candidate's close equals `planned_entry`;
  otherwise the decision stays `AMBIGUOUS`. Parity or outcome is never used.

## Stored-snapshot parity (reconstruction fidelity only)
- **Code:** `_calculate_indicators` and `_raw_features`, executed verbatim from git `977746f`. These methods are
  identical through `c4a623c`; `63da7d3` went live at the freeze. `ta` 0.11.0 is used: pandas_ta is absent from
  every analyzer image, so production used the `ta` fallback. Config uses the default periods (no environment
  override in the analyzer).
- **Inputs:** the last 200 closed candles ending at the resolved decision candle. A hard PIT guard requires every
  input candle to close before the decision time.
- **Sample:** all W2 decisions with a stored `features_snapshot`, so selection is deterministic and outcome-free.
  Stratification is reported by timeframe, W2 third, symbol and stored ATR% tercile.
- **Classes:** `EXACT`, `WITHIN_TOLERANCE` (1e-6 for price-derived features, 1e-4 relative for recursive ones),
  `VERSION_DIFFERENCE`, `INSUFFICIENT_HISTORY`, `SOURCE_DIFFERENCE`, `TIMESTAMP_ALIGNMENT_ERROR`, `UNKNOWN`.
- No tuning; outcome fields are never read.
