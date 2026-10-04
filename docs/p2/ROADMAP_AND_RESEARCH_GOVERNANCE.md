# Roadmap and research governance (P2-C delta)

**Status:** owner-approved 2026-10-04 (recorded on branch `feature/p2c-research-layer-20261004`). The canonical
owner decision register is `docs/product/DECISION_LOG.md` on unmerged PR #3 (`d41f317`, last entry ADR-011). That
file is NOT edited here. The entries below are numbered **P2G-ADR-01 … 10** and are proposed for verbatim
transcription into DECISION_LOG as ADR-012 … ADR-021 when PR #3 lands. Until then this document is the reference.

Nothing in this document authorizes a deployment, a merge, a Paper or collector change, live trading or any later
roadmap stage. Each stage is gated separately by the owner.

| ID | Date | Decision | Status | Implementation gate |
|---|---|---|---|---|
| P2G-ADR-01 | 2026-10-04 | **Market scope.** Crypto is the ONLY market authorized for implementation, research execution and Paper. No US equities, futures, forex or other market implementation is authorized. | Approved | Code refuses any other market (`p2_research/instrument.py`: `SUPPORTED_MARKETS` = crypto Binance spot only; the Trial Ledger refuses other markets). |
| P2G-ADR-02 | 2026-10-04 | **Multi-asset principle.** Avoid unnecessary crypto/Binance coupling in the core research architecture where cheap and clean. Architectural readiness only: does NOT authorize equity feeds, broker integration, corporate-action pipelines, futures or forex adapters, or stock-specific production development. | Approved principle | Readiness limited to a canonical instrument identity (§3); no adapter for any other market. |
| P2G-ADR-03 | 2026-10-04 | **Expansion gate.** Multi-asset expansion only AFTER the Crypto system demonstrates an acceptable forward edge under an explicit Crypto Success Gate. US equities are the preferred first expansion candidate after that gate, subject to future owner review. | Approved | Crypto Success Gate criteria to be predeclared and owner-approved before use. |
| P2G-ADR-04 | 2026-10-04 | **Roadmap sequence** (§1). The roadmap does NOT itself authorize later stages; each is separately gated. | Approved direction | Per-stage owner approval. |
| P2G-ADR-05 | 2026-10-04 | **Research philosophy.** The objective is NOT to maximize backtest return or Sharpe through unrestricted parameter search. Research follows Hypothesis → Trial → Evidence → Robustness → Forward Validation, not Indicator search → best backtest → deployment. Strategy research starts from documented hypotheses. | Approved | Every trial is registered in the Trial Ledger before it runs (`H-…` hypothesis id mandatory; failed trials persist). |
| P2G-ADR-06 | 2026-10-04 | **Market adapter boundary (future).** Market Adapter → Canonical Market Schema → P2-C Features → Strategy/Alpha → Portfolio & Risk → Execution Adapter. Binance-specific acquisition belongs outside the market-neutral research core where practical. The running Collector is out of scope and untouched. | Approved direction (design only) | No collector change; see §3. |
| P2G-ADR-07 | 2026-10-04 | **Benchmark contract** (§4). Document only; exact definitions frozen before comparative testing. No W3. | Approved (document only) | Freeze definitions in a later, separately approved step. |
| P2G-ADR-08 | 2026-10-04 | **Evaluation contract** (§5). Document only; no performance is calculated now. | Approved (document only) | Applied by P2-D/P2-F only after separate approval. |
| P2G-ADR-09 | 2026-10-04 | **P2-X / P2-RM boundaries** (§6, §7). Execution quality is not price forecasting; portfolio-risk research is distinct from the protective Risk Engine, whose circuit breakers stay unchanged. | Approved (boundary only) | Nothing implemented or changed now. |
| P2G-ADR-10 | 2026-10-04 | **PAPER-R1 identifier gaps.** The 5 documented gaps (P2C_RESEARCH_LAYER §8) remain documentation; a future change proposal may be written; no production instrumentation change. | Approved | Separate owner approval for any instrumentation change. |

## 1. Roadmap sequence (P2G-ADR-04)

P2-C Data & Feature Foundation → P2-D Hypothesis/Alpha Research → P2-X Execution & Cost Model → P2-RM Portfolio &
Risk Research → P2-F Adversarial Validation → P3 Candidate Selection/Readiness → Shadow → Paper Candidate →
Edge/Drift Monitoring → ML Enhancement → Live Readiness → Crypto Success Gate → P4 Multi-Asset Expansion →
controlled Capital Scaling.

The roadmap does NOT itself authorize later stages; each is separately gated. Current position: P2-C (offline
foundation on an unmerged branch); P2-C1 (first real sealed day) pending; P2-D not started.

## 2. Research philosophy (P2G-ADR-05)

- Objective: NOT maximum backtest return or Sharpe through unrestricted parameter search.
- Process: **Hypothesis → Trial → Evidence → Robustness → Forward Validation.** Rejected: Indicator search → best
  backtest → deployment.
- Strategy research starts from documented hypotheses (`H-<name>`), each with a predeclared feature subset taken from
  the hypothesis families in [P2C_FEATURE_REGISTRY.md](P2C_FEATURE_REGISTRY.md). **Feature availability does not imply
  feature selection**; feeding all 40 features into optimization or ML is not allowed.
- Every trial, including failed and abandoned ones, is registered in the append-only Trial Ledger
  ([P2C_TRIAL_LEDGER.md](P2C_TRIAL_LEDGER.md)) so the number of trials per hypothesis is known for Deflated Sharpe /
  PBO. The ledger refuses any period overlapping W3.

## 3. Market adapter boundary and multi-asset readiness (P2G-ADR-02, -06)

```
Market Adapter  →  Canonical Market Schema  →  P2-C Features  →  Strategy/Alpha  →  Portfolio & Risk  →  Execution Adapter
(Binance today:     (instrument identity,       (feature set      (P2-D, hypothesis  (P2-RM)            (P2-X; Paper today)
 collector + P2-C    calendar, PIT records)      p2c-fs 1.0.0)     driven)
 reader)
```

- Today the "Market Adapter" is the running collector (out of scope, untouched) plus the P2-C schema-v2 reader. The
  reader is deliberately Binance-schema specific: it is the adapter, not the core.
- Canonical identity added in `p2_research/instrument.py`: market = (asset_class, venue, product, calendar_id);
  instrument = market + instrument_id (`crypto:binance:spot:BTCUSDT`) + symbol + base/quote/settlement currency.
  The only calendar is `crypto-24x7-utc` (continuous, UTC day boundary = the collector's day seal unit).
- Coupling review of `p2_research` (delta C):
  | Location | Coupling | Decision |
  |---|---|---|
  | `reader.py` (schema v2, bookTicker/depth/miniTicker/kline payloads, tiers) | Binance collector schema | adapter layer by design; stays |
  | `builder.check_versions` | market | now asserts the market is authorized (`require_supported_market(BINANCE_SPOT)`) |
  | decision grid, `DAY_MS` day boundaries | 24/7 UTC calendar | named as `crypto-24x7-utc`; a session calendar would need a new grid (not built) |
  | `features.btc_context` (`BTCUSDT`), `ctx.*` universe features | crypto market context | part of the crypto feature set, not the core; stays |
  | `labels.FEE_BPS_PER_SIDE = 10` | Binance spot taker fee assumption | an execution assumption; moves to P2-X cost model later; recorded per trial in the ledger |
  | `ledger.py` | none (market validated through `instrument`) | market-neutral |
- Not built (and not authorized): equity/futures/forex adapters, session or holiday calendars, corporate actions,
  broker integration.

## 4. Benchmark contract (document only; P2G-ADR-07)

Comparisons, when later authorized, must include: (1) cash / no-trade; (2) BTC buy-and-hold where meaningful;
(3) a simple BTC trend rule; (4) simple time-series momentum; (5) the current PAPER-R1 strategy. Exact definitions
(signal, rebalancing, costs, universe, period) must be frozen and recorded before any comparative test. No W3 data.

## 5. Evaluation contract (document only; P2G-ADR-08)

- Return: net P&L, expectancy, profit factor, risk-adjusted return.
- Risk: max drawdown, downside, worst periods, time under water, tails.
- Trade economics: win rate, payoff ratio, MAE, MFE, turnover, transaction costs, cost-to-gross-edge.
- Robustness: OOS, regime stability, parameter sensitivity, symbol concentration, Deflated Sharpe, PBO.
- Forward: Paper, Shadow, backtest-to-forward degradation.

No performance is calculated now.

## 6. P2-X boundary (P2G-ADR-09)

decision price → executable price → fill → spread → slippage → fees → net realized edge. Execution quality is not
price forecasting and is evaluated separately. P2-C execution labels (`exe.*`) remain **top-of-book approximations**
(first book observation after T, no depth walk, no latency model, fixed 10 bps/side fee) and are marked as such in
P2C_RESEARCH_LAYER §6 and O4.

## 7. P2-RM boundary (P2G-ADR-09)

Distinct from the existing protective Risk Engine (B3, consecutive-loss / daily / weekly / drawdown breakers), whose
circuit breakers stay unchanged. Later research topics: position sizing, volatility-aware sizing, portfolio heat,
correlated exposure, market/BTC beta, concentration, liquidity-adjusted sizing, drawdown-state de-risking. Nothing is
implemented or changed now.

## 8. PAPER-R1 identifier gaps (P2G-ADR-10)

The five gaps in P2C_RESEARCH_LAYER §8 (no feature-row hash on Paper decisions; no collector observation reference
for the Paper entry price; bot klines vs collector candles; no per-event clock alignment; Paper outcomes must stay
outside W3 and enter only via a predeclared evaluation) remain documentation. **Future change proposal (not
authorized):** add to the evidence-v2 `signal.ready` / `trade.opened` events a `p2c_row_ref` = (`feature_set`
version, `registry_sha256`, `row_id`), the collector book `obs_id` + `sample_ms` used for the entry, and the host
clock offset; implementation only with a separate owner approval, a reviewed branch and the Class B procedure.
