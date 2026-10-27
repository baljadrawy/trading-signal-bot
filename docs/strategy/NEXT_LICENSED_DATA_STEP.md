# HR-04 / HR-08 (+ HR-13): next step on licensed historical data

**Status: PLAN (D0). Nothing in this file has been run on real data.** Written 2026-10-26 on `research/variant-ledger`
(PR #94). It describes the stage-X (exploratory) step that would follow the synthetic engineering stage S, and the
gates that must be passed first. It authorizes nothing, reads no data, registers no non-synthetic variant, spends no
alpha and opens no window.

- **No profitability is claimed** for HR-04, HR-08, HR-13 or any strategy. The synthetic tests listed in §1 prove
  engineering properties only; they are not evidence about any market.
- **D1/D2 remain on HOLD** for governed confirmation (`docs/governance/OWNER_OPERATING_CONTRACT.md` §4). Even a
  favourable exploratory result would only nominate a candidate; it would never be a confirmation.
- The sealed FORWARD_HOLDOUT (after the 2026-08-19 freeze instant) stays sealed. This step never reads it.

## 1. Where stage S stands (synthetic only)

| Item | Path |
|---|---|
| Module `hr04-tsmom-v1`: HR-04 long/cash, HR-13 band, HR-08 inverse-vol sizing, turnover ledger, EW buy-and-hold benchmark, net via the s4-mech-v1 cost model | `research/strategies/daily_tsmom.py` |
| Synthetic tests: no look-ahead (future-perturbation property test), constant-signal entry-cost-only, turnover counts, band lowers turnover, inverse-vol weights ≤ 1 and favour low vol, parity with `research/mechanisms/simulate.run`, driftless martingale gives no significant net PSR/DSR, injected trend detected in gross, synthetic variants in a temp `VariantLedger` | `tests/test_hr04_daily_tsmom.py` |
| Cost model (reused, not rewritten): 0.10 %/side fee floor, half-spread and slippage per side, discounts refused | `research/mechanisms/costs.py` |
| PSR / DSR, Romano–Wolf / Holm, alpha budgets, variant ledger | `research/stats/` (`docs/strategy/VARIANT_LEDGER.md`) |

Timing used by the presets: decision at the daily close t from closes ≤ t, **executed at close t + 1** (HR-04
register: "executed at the next close", `execution_lag=1`). `execution_lag=0` (trade at the signal close, ≈ the t + 1
open on a 24/7 venue) is an optimistic sensitivity only.

**Done since (D0, synthetic, 2026-10-27):** items 1–3 below and a labelled result summary are implemented and
tested on synthetic panels only: `research/strategies/pit_universe.py` (`hr04-pit-v1`: PIT top-N by trailing quote
volume from data ≤ t, ragged panel with listings/delistings, delisting = forced exit at the last close with full
costs, optional −100 % stress haircut, monthly-rebalanced PIT EW benchmark with its own turnover costs),
`research/stats/inference.py` (Newey–West HAC, register lag 7, lag 0 = classical SE; seeded Politis–Romano
stationary bootstrap CIs for mean and Sharpe), `research/strategies/result_summary.py` (`hr04-summary-v1`: per-day
and per-trade net expectancy, turnover, MDD, PSR/DSR with the full family N, HAC t, bootstrap CIs, active vs
benchmark; refuses any label other than SYNTHETIC without a non-synthetic `DatasetPermission` and an
`authorization_ref`; CONFIRMATORY always refused). Tests: `tests/test_hr04_pit_inference.py`. The event-sourced
`research/data_governance/universe.py` (datetime listing states) was not reused directly; an adapter from its events
to `AssetSeries` first/last days is a later step. Items 4–5 remain open.

**Engineering still needed before any data (D0, synthetic, no gate):**

1. Time-varying point-in-time universe in the accountant (assets entering/leaving the top 20; a forced exit when an
   asset leaves the universe or is delisted, costed like any trade; no price before listing). The current module
   needs aligned series for a fixed universe. Reuse `research/data_governance/universe.py` (event-sourced PIT
   universe) after checking its fit.
2. Newey–West HAC t (Bartlett, lag 7) and a stationary bootstrap for the paired active-return endpoint; reuse the
   HAC logic of `research/power/ladder_power.py` only as a reference (that package is not imported from outside).
3. Benchmark convention fixed in code: the S4 draft names an EW B&H **with monthly rebalance** of the same PIT
   universe, plus BTC B&H, ETH B&H and cash. The current benchmark never rebalances (fixed universe).
4. Per-tier cost declaration (half-spread 0.01 % BTC/ETH, 0.04 % other top 20; slippage 0.05 %/side; ×2 stress) as
   `CostModel` instances with labels, and the tracker 0.30 % flat label reported beside.
5. A preregistration file template (§4) and synthetic power simulation with heavy-tailed, day-clustered returns.

## 2. Data requirements

| Requirement | Specification |
|---|---|
| Source | Binance Spot daily klines, USDT quote pairs (same venue as the bot). Content-addressed snapshot (`research/data_governance`) with a verified data-quality certificate |
| Fields | per symbol and UTC day: open time, open, high, low, close, base volume, quote volume, number of trades; listing and delisting events; symbol status history |
| Assets | every USDT pair that was ever in the point-in-time top 20 by trailing 30-day median (or sum, fixed before data) quote volume among pairs listed ≥ 90 days; stablecoins, leveraged, wrapped and fiat-pegged coins excluded by a list frozen before data |
| Period | **strictly before the sealed holdout boundary, the 2026-08-19 freeze instant**: specification sanity 2019-01-01 → 2022-12-31 (no tuning), one logged look 2023-01-01 → 2026-08-18 (S4 draft §4). No bar that closes at or after the freeze instant is loaded, not even for warm-up |
| Survivorship bias | the universe is rebuilt at each rebalance date from data available on that date; **delisted symbols are kept** until their last traded day and exited at their last available close with full costs (a stress variant marks the exit at −100 % of the position for symbols delisted without a final tradable price); no "current top 20" lists |
| Data quality | gaps, zero-volume days and price anomalies flagged and handled by a rule frozen before data; dropped symbol-days are counted and reported |
| Contamination | every period is research-exposed (`research/governance/contamination_registry.jsonl`); results are exploratory qualification only |

## 3. Licence status: NOT CLEARED

- LIC-1 draft for this step: `docs/strategy/LIC-1_DATA_LICENCE_INQUIRY.md` (2026-10-27, **not sent**; reuses A22 §4).
- Binance Vision terms: **licence HOLD** (A18/A19). The licence inquiry is drafted and **not sent** (profitability
  roadmap O7, `PROFITABILITY_ROADMAP_2026-10-24.md`, PR #91 — **Draft, not merged**).
- The roadmap's owner decision **RD-5: "Send LIC-1; decide dataset permission (OD-DF-1)"**, with roadmap item R9
  ("Licence inquiry + `DatasetPermission` + certified pre-freeze dataset") and entry condition EQ-1 ("≥ 1
  `DatasetPermission` with licence basis; snapshot verify PASS").
- `docs/governance/DEVELOPMENT_FIRST_POLICY.md` §2 (D1) and §7 **OD-DF-1** (proposed): exploratory real-data work only
  on a dataset with a recorded permission. **Today no dataset has one.**
- Code gate: `research/mechanisms/simulate.DatasetPermission`; `daily_tsmom.run_tsmom` and `run_buy_and_hold` refuse
  any input without the synthetic marker or a licence-cleared, holdout-excluding permission record.

## 4. Preregistration fields to freeze before any data is touched

The preregistration is committed (git SHA recorded) and accepted by the owner (RD-2) **before** the dataset is opened.

| Field | Content to freeze |
|---|---|
| Hypotheses | HR-04 primary statement; HR-08 and HR-13 as registered variants (`docs/strategy/HYPOTHESIS_REGISTER.md`) |
| Primary endpoint | one notion named by the owner before data: mean daily **active** net return of HR-04 vs EW B&H (notion c, S4 draft) or PSR/DSR of daily net returns (notion b); the other notions are secondary |
| Universe rule | PIT top 20 by trailing 30-day quote volume, listed ≥ 90 days, exclusion list, rebalance frequency (monthly), delisting handling (§2) |
| Parameters | lookback 14 days; band ±1 % (HR-13); vol window 20 days, target = universe median, cap 2 × (1/N) (cap is [ASM], must be frozen); `execution_lag=1`; rebalance policy (`daily` or `on_signal_change`); warm-up and start index; all from the register, none tuned |
| Code | module version `hr04-tsmom-v1` plus the code SHA and each variant's `config_hash()` |
| Cost model | `s4-mech-v1` (`research/mechanisms/costs.py`): fee 0.10 %/side, declared half-spread and slippage per tier, ×2 stress; tracker 0.30 % flat reported beside |
| Metrics | net expectancy (mean daily net return) and gross; active net vs EW B&H (plus BTC, ETH B&H); PSR and **DSR with N = every variant registered in the family, abandoned ones included**; maximum drawdown and duration vs B&H; turnover and cost drag; share of P&L from top-5 months / top-1 coin |
| Inference | Newey–West HAC t (Bartlett, lag 7) + stationary bootstrap (mean block 20 days) for the primary; Romano–Wolf step-down over the family (Holm as a check) |
| Family and alpha | `fam.s4-direction` (HR-04, HR-13, with S4 H2/H3) and `fam.risk-overlay` (HR-08), as in the register §1. Exploratory budget from `research/stats/alpha_budget.py`: `exploratory_family_budget(family)` = 0.05 split equally over the family size (S4: 0.05/3). Exploratory alpha never admits a confirmation and never draws on the governed 1/240 budget |
| Ledger | every variant registered in a `VariantLedger` with its non-synthetic evidence class **and** `authorization_ref` (owner record) **before** its result is read; the ledger `head()` recorded in the preregistration; one result per variant |
| Looks | exactly one logged look per variant for 2023-01-01 → 2026-08-18 (`research/governance/validation_usage.jsonl`); the 2019–2022 pass checks specification only and changes nothing |
| Stopping / kill criteria | S4 failure criteria, any one rejects the direction: HAC t ≤ 0; cost drag > 50 % of gross; MDD worse than EW B&H without a Sharpe gain; > 50 % of P&L from 5 months or 1 coin; sign reverses under ×2 cost stress. HR-08: PSR not higher, MDD not lower, non-inferiority on mean daily net fails (margin −0.02 %/day [ASM]), or rescaling cost > 25 % of the risk gain. HR-13: turnover reduction < 30 % or paired net difference ≤ 0. Technical stop: any data-quality certificate failure, permission mismatch or bar at/after the freeze instant aborts the run with no result recorded except the abort |
| Power | outcome-free table (S4 A3): about 0.76 for a true annualized SR of 1.0 over 8 years at 0.05/3; an inconclusive result is the expected outcome for realistic effects |
| Reporting | gross and net, turnover, drawdown, sample sizes, regimes, uncertainty and failure cases; every variant, including failures and abandoned ones |

## 5. Compute estimate

Pure-Python, single core: the synthetic suite runs 5 assets × 750 days per variant in about 0.05 s. A real look of
20 assets × about 2,800 days (2019–2026) per variant is about 0.5–2 s; HR-04, HR-08, HR-13 and cost-stress arms
(≈ 10 runs) plus a 1,000-resample Romano–Wolf / stationary bootstrap over ≈ 5 series is a few CPU-minutes, well under
1 GB RAM. It runs through `~/ops/research-runner` (CPU and memory caps), never on the production containers or DB.

## 6. Authorization gates (in order; each is a separate owner decision)

1. **Data permission (G-DATA):** licence cleared (LIC-1 sent and answered; RD-5 / OD-DF-1 decided) and a recorded
   `DatasetPermission` for a certified snapshot that ends before the 2026-08-19 freeze instant and excludes every
   protected holdout. Without it, work stays synthetic.
2. **Preregistration accepted (RD-2)** with all §4 fields frozen and the ledger head recorded, before any data read.
3. **Scientific authorization for the exploratory run:** names the dataset permission, the preregistration SHA, the
   families, the exploratory alpha split and the single look. The result is labelled EXPLORATORY and can only
   nominate a candidate.
4. **Separately, for any confirmatory test (G-SCI):** the owner lifts the **D1/D2 HOLD**, decides the validation
   design (OD-DF-2 / RD-4), grants a scientific authorization, a committed confirmatory preregistration, a
   prospective-partition record (never FORWARD_HOLDOUT) and an alpha slot (1/240 from the governed budget). Any Paper
   or forward capture additionally needs operational approval (G-OPS).

Until gates 1–3 are passed, only the D0 engineering items of §1 may proceed.
