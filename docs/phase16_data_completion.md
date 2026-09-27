# Phase 1.6 data completion

Dataset `ds-09284abbc6453ff59acd` supersedes the Phase 1.5 raw index without
altering it. The knowledge cutoff remains `2026-08-19T09:33:46Z`; historical
content ends at 2026-05-31 and the forward holdout remains sealed with zero looks.

Binance Vision monthly archives and official checksum sidecars were retained for
15m. The legacy 1h/4h/1d archives were independently matched to newly retained
official sidecars. All 99,196 archives matched upstream SHA-256.

The normalized snapshot contains 596 symbols and 94,270,170 rows across 15m,
1h, 4h, and 1d. It preserves gaps and contains no synthetic candles. Invalid raw
rows are excluded only through versioned deterministic rules with reason counts in
`normalized/quality.json`; RAW is unchanged.

The universe includes all 596 archive-observed symbols and 177 inferred historical
delistings. First/last archive evidence is not represented as an authoritative
announcement. Survivorship status is `MATERIAL_SURVIVORSHIP_LIMITATION`.

Execution is `TIER_3_DOCUMENTED_CONSERVATIVE_PROXY`. It uses only contemporaneous
rolling quote volume, trade count, and realized volatility, rejects outcome fields,
and is not called calibrated. Any later Phase 2 use requires cost/slippage stress.

Historical USDT dominance remains unavailable. CoinGecko's historical global
market-cap endpoint and CoinMarketCap's historical global metrics require paid
authenticated access not configured in this repository. No BTC proxy, current
value, forward interpolation, or unverified scrape was substituted. Consequently
the final v2 certificate is `FAIL`, replay is `BLOCKED_MACRO_DATA_UNAVAILABLE`, and
Phase 2 is not authorized.
