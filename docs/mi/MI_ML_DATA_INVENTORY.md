# Market Intelligence ML — reusable data and infrastructure inventory (read-only, 2026-10-08)

**How this was produced.** Only manifests, certificates, coverage indexes and code were read. No candle values,
outcome labels, strategy outcomes or W3 content were opened, and no production data or Collector file was touched.

## 1. Historical market data (candidates for MI)

| Dataset | Location | Content | Coverage | Integrity / status | MI use |
|---|---|---|---|---|---|
| **ds-09284abbc6453ff59acd** ("ds-0928", W1) | `~/research-data/trading-signal-bot/snapshots/ds-09284abbc6453ff59acd/` (5.7 GB) | Binance **spot USDT** OHLCV, 15m / 1h / 4h / 1d, 596 symbols; base columns + rolling-24h columns | BTC / ETH 2017-08-17 → **2026-05-31**. Rows: 15m 71.3 M, 1h 17.8 M, 4h 4.46 M, 1d 0.74 M. 1d listing years: 2017 6, 2018 16, 2019 65, 2020 106, 2021 123, then 41–100 per year. Median 1195 daily bars per symbol | Upstream checksums verified; normalized PASS; determinism PASS; leakage PASS. Files: 1499 PASS / 885 WARN; gap files 15m 377, 1h 377, 4h 112, 1d 17. Certificate **status FAIL**, critical `HISTORICAL_USDT_DOMINANCE_MISSING`; `MATERIAL_SURVIVORSHIP_LIMITATION`; universe `PARTIALLY_POINT_IN_TIME_CONTROLLED` (596 inferred listings, 177 inferred delistings, 0 known); `MACRO_DATA_UNAVAILABLE`; `eligible_for_phase2 = false` | **Primary** development / validation source. The FAIL concerns dominance and macro, which MI does not use; accepting this needs owner decision MI-D3 |
| **p2b-53de1a98c2792cd74206** (W2) | `~/research-data/trading-signal-bot/p2/normalized/p2b-53de…/` (44 MB) | Same schema, 15m / 1h / 4h / 1d, **139 symbols**, 1 354 266 candles | 2025-11-01 → 2026-08-19T09:29:59Z, close < freeze | W3_PROOF PASS (0 post-freeze rows); 10 953 archives re-verified; 834 REST-validated; 237 SOURCE_UNAVAILABLE; 0 internal gaps; REST-vs-archive 17009/17010 match; seams 508 contiguous, 48 single-source | Candidate **final historical test** (W2). The universe is **decision-selected**: the symbols the bot signalled, plus BTC / ETH. It is not a PIT universe (see §4) |
| p2a-4821487044281371e146 | `~/research-data/trading-signal-bot/p2/canonical/…` | Strategy decisions, stored runtime snapshots, execution / trade lifecycle (W1 12 905 / W2 1 456 decisions) | 2026-04-08 → 2026-08-19 | 0 validation violations; W3 excluded at extraction | **Not an MI input** (strategy outcomes; MI-ADR-03). The schema can be reused |
| ds-d82b982e7221e2dcc7b7 | `~/research-data/trading-signal-bot/ds-d82b…` | Superseded by ds-0928 | — | superseded | none |
| p2-forward-continuous-v1 | `~/research-data/trading-signal-bot/p2/forward-continuous-v1/` (1.2 GB, live Collector tree) | Book / depth / closed klines / universe tiers, Tier 0–2 | 2026-10-04 (partly inside W3) → now. Sealed: 10-05, 10-07; 10-06 FAILED (health hole) | Collector-owned; the Ledger refuses to live there | **Reserved** for a future prospective shadow protocol (MI-ADR-03 / 06); never written to |

**Not available locally (each would need an explicit acquisition decision, MI-D9):**

- full-universe W2 archives (for a PIT W2 universe);
- historical BTC.D / ETH.D / USDT.D (none PIT);
- funding / mark / open-interest (public archives exist);
- aggTrades;
- historical order-book depth (not recoverable).

The production `macro_history` table is daily, last-write-wins and not PIT, so it is excluded.

## 2. Reusable features (P2-C registry `p2c-fs 1.0.0`, 40 features)

| Family | Historically computable from candles? | Notes |
|---|---|---|
| `mom.*` (10), `vol.*` (5), `act.*` (3) | **yes**: same formulas on ds-0928 / p2b candles | Must be re-implemented as `REBUILT_*` with a new feature version; formulas unchanged |
| `ctx.btc_ret_1h_1`, `ctx.btc_rv_1h_24` | yes | Identical to mom / vol on BTCUSDT rows |
| `ctx.breadth_24h`, `ctx.universe_ret_24h_median`, `ctx.universe_disp_24h`, `ctx.xs_rank_ret_24h` | **approximate only**: the registry uses miniTicker rolling 24 h; historically a 1h-candle rolling-24h analogue over a PIT universe | Defined as new historical variants; survivorship-sensitive |
| `ctx.tier` | no (forward universe epochs) | Replaced by a PIT liquidity rank built from candles (MI-D4) |
| `liq.*` (7), `dq.*` (8) | **no**: book / depth / Collector lifecycle are forward-only | Excluded from historical MI. P2-D H04's `liquidity_stress` regime branch therefore cannot be reproduced historically |

**Existing labels** (`p2_research/labels.py`): `mkt.fwd_ret / mfe / mae / max_dd / decline_{1h,4h,24h}`.

- `DECLINE_THRESHOLD` = 1.5 % / 3 % / 6 %, "predeclared, NOT tuned".
- They are built on forward book data. MI re-implements the MAE-based decline label on certified candles.

## 3. Reusable research infrastructure

| Component | Where | Reuse |
|---|---|---|
| Trial Ledger (append-only, hash-chained, W3-period refusal, `H-…` ids, forbidden-root guard) | `p2_research/ledger.py` (this branch, unmerged) | Separate instance for MI (`H-MI-T1…T3`), dir outside the Collector tree |
| P2-A / P2-B contracts, freeze guard, normalizer | `research/p2/*` on `d517c6a` / `3335228` (unmerged) | Freeze constants and the "post-freeze candle = hard failure" rule; P2-B acquisition code for any approved new archive |
| Instrument identity | `p2_research/instrument.py` | Canonical ids, crypto-only refusal |
| P2-F0 statistics | `p2_research/falsification/` (Wilson, stationary / block bootstrap, HAC, Holm, Romano-Wolf, PSR / DSR) | Inference utilities; the Alpha verdict battery is not an MI gate |
| P2-X cost model | `p2_research/execution/` (v2 `f20e22a5…`) | Utility diagnostics only. Historically only fee + proxy are possible (impact UNAVAILABLE, ds-0928 spread proxy TIER_3 uncalibrated) |
| Research runner | `~/ops/research-runner` (R1 / R2 / R3 / LIGHT; swap 0) | All MI compute |

**Environment gap.** System `python3` has **no pyarrow** (checked 2026-10-08), so the Parquet stores cannot be read
without a new isolated environment (pyarrow, numpy, pandas, scikit-learn; optionally lightgbm). That is owner
decision MI-D8.

## 4. Data-quality assessment for MI

| Risk | Finding | Mitigation proposed |
|---|---|---|
| Survivorship | ds-0928 is archive-presence based: 177 inferred delistings included, 0 known delistings, `MATERIAL_SURVIVORSHIP_LIMITATION` | PIT liquidity universe built from candles available at T. Delisted symbols kept while present. Results reported separately for BTC / ETH (no survivorship) and the alt universe |
| Universe selection (W2) | p2b covers only bot-signalled symbols plus BTC / ETH, so it is selection-biased | W2 test on BTC / ETH plus the PIT top-N chosen with data < 2026-06-01; any missing archives acquired under the P2-B guard (MI-D9). Otherwise the W2 test is BTC / ETH only |
| Timestamp integrity | Archive close = open + tf − 1 µs (REST: −1 ms); 2025+ archives are µs (auto-detected) | Decision time = bar close; a feature uses only bars with close < T; a label uses bars with open ≥ T |
| Missing data | 377 / 596 symbols have 15m / 1h gaps; 1d 17 | Never synthesize. A label whose horizon overlaps a gap is censored and counted. A feature window containing a gap is null with a reason (P2-C convention) |
| Availability-time leakage | Candles are available after close (archives later; REST at close). Dominance / macro is not PIT | Candle-only features; no macro; synthetic leak tests (one-bar-shift canary as in F0 R09) |
| Episode independence | Cross-symbol outcomes on one day share the BTC factor; overlapping horizons | Day clusters; effective episodes reported; block bootstrap by day; purge + embargo (spec §6) |
| W3 | Sealed: no MI access | Ledger period refusal; builder refuses any candle with close ≥ 2026-08-19T09:33:46Z |

## 5. Prior exploration disclosure (for MI-ADR-03 / 08)

These are recorded in project memory and summarized here, not re-run:

- 2026-06 XGBoost daily study: 595 symbols, ds-0928 lineage, TA + Ichimoku + ICT with triple-barrier labels.
  Verdict NO-GO: positive only on micro-caps, regime beta, decay.
- 9-year target-policy backtests: 301 symbols, 2017–2026.
- Edge scans, SMC and falling-wedge tests.
- The June live-learning system.

Triple-barrier and stop-hit labels are closely related to downside events. **W1 market outcomes, and W2 up to
about 2026-06-25, have therefore been looked at.** No historical period is pristine. MI historical results are
development evidence; confirmation can only come from prospective shadow data or from a separately authorized W3
opening protocol.
