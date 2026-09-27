# Phase 1.6B historical macro acquisition

Phase 1.6B was retried with a CoinMarketCap credential. The credential is present
and valid, and both required endpoints exist: historical global metrics and
historical Tether quotes (CMC asset ID `825`). Both requests were rejected because
the credential plan permits only 12 months of historical access. At the check
time, the earliest permitted start was 2025-08-18, while the required research
range begins 2017-08-17. No credential value was printed or persisted.

The same-provider acquisition therefore requires either a CoinMarketCap plan
whose `CMC_PRO_API_KEY` can access the full required range for both endpoints, or
a paid-history-enabled CoinGecko credential covering both component series.
Twelve-month history is insufficient and was not ingested as partial Macro data.

No scraping, current macro value, BTC proxy, stablecoin proxy, provider mixing,
future interpolation, or strategy change was used. Consequently no macro RAW or
normalized layer exists, no new dataset was sealed, and technical replay remains
blocked by `MACRO_HISTORICAL_COVERAGE_ENTITLEMENT_REQUIRED`.

The existing dataset `ds-09284abbc6453ff59acd` remains immutable. Its manifest
SHA-256 before and after this attempt is
`a7c8eee1ecbd05eef3e28b1a40bd7199cc3fb9ac71ab3aac2c84ac0ca6a33b09`.
The knowledge cutoff remains `2026-08-19T09:33:46Z`; the forward holdout remains
`SEALED` with zero looks.
