# P2-D0 — Alpha research protocol and hypothesis pre-registration (v1)

**Status:** FROZEN 2026-10-05 on branch `feature/p2c-research-layer-20261004`. Protocol design only: no trial has
run, no strategy return has been computed, nothing was tuned, ranked or selected by outcome, no W3 outcome was
inspected. PAPER-R1 and the forward Collector are untouched; the learner stays stopped and walk-forward stays
disabled. Crypto (Binance spot) is the only market (P2G-ADR-01). Governance:
[ROADMAP_AND_RESEARCH_GOVERNANCE.md](ROADMAP_AND_RESEARCH_GOVERNANCE.md) (P2G-ADR-01…10); Trial Ledger:
[P2C_TRIAL_LEDGER.md](P2C_TRIAL_LEDGER.md); features: [P2C_FEATURE_REGISTRY.md](P2C_FEATURE_REGISTRY.md).

**The machine-readable registries are the source of truth**; this document explains them. Where the two differ, the
frozen JSON wins and the difference is a defect to be fixed in a new version.

| Frozen file (`p2_research/research/`) | SHA-256 |
|---|---|
| `hypotheses_v1.json` (H01–H07) | `c5df5bf438a03702cc4d3ad49eeada637c74dc2e61cbdcbfa6a7b5c26db933c0` |
| `benchmarks_v1.json` (5 benchmarks) | `757f77ebe70912b6e66143e4e14d2c16ea4ab5d2375d91ff9e2a001a417ab96c` |
| `protocol_v1.json` (sections 1, 3, 5–14 below) | `2843ba9d69691fe2889e4ad7cb6bc4c6dc5c931586764bd8eac822cccdc08f05` |
| `planned_trials_v1.json` (48 PLANNED trials) | `e95a39ce6a9815cc2a86dd096488e942ab0c8f252145b817e80a9d31cf53437e` |

`FROZEN_SHA256SUMS.json` holds these hashes; `p2_research.protocol.verify_frozen()` recomputes them (tested).
Bound inputs: feature registry `p2c-fs 1.0.0` (`feature_registry_v1.json` SHA `bcf38504…b81a`), hypothesis-family
overlay (`d163b3c9…ce91`), label set `p2c-ls 1.0.0`. Code: `p2_research/protocol.py` (stdlib; no `p2_forward`
import). Tests: `p2_research/tests/test_protocol_d0.py`.

```
python -m p2_research.protocol summary   # verified hashes + counts (read-only)
python -m p2_research.protocol plan      # regenerate the planned trials from the frozen registry (stdout)
```

## 1. Research questions

**Primary (verbatim):** "Can observable, point-in-time-safe market state identify crypto trading opportunities whose
expected net return remains positive after realistic execution costs and whose edge is sufficiently stable across
time, symbols and market regimes to justify forward testing?"

**Secondary:** which conditions create edge; when NOT to trade; whether the information is directional, liquidity,
volatility or regime information; incremental value over simple baselines; how much gross alpha survives execution.

## 2. Hypothesis registry (H01–H07)

Common to all hypotheses:

- **Direction: long-only spot.** Binance spot paper cannot short. A negative view means FLAT (cash); bearish
  information is usable only as a no-trade / de-risk input.
- **Decision cadence:** every decision time T of `grid-15m-plus390s-v1`. Per (trial, symbol) at most one open
  position; a new entry only when flat; time exit exactly at the trial horizon (no stop, no target: those are
  P2-RM / P2-X topics).
- **Horizons:** 4h and 24h. 1h is excluded from round 1 because the fixed 20 bps round trip plus spread is a large
  fraction of typical 1h moves, so 1h cells would add trials with little prior economic plausibility.
- **Labels:** gross `mkt.fwd_ret_{h}`; executable `exe.net_ret_{h}`; path `mkt.mfe_{h}`, `mkt.mae_{h}`,
  `mkt.max_dd_{h}`, `mkt.decline_{h}`; cost `exe.entry_spread_bps`, `exe.entry_delay_ms`, `exe.fee_bps_roundtrip`.
- **Outcome categories:** SUPPORTED / WEAK / INCONCLUSIVE / REJECTED (§10).
- **Predictive information vs executable edge.** Predictive information is a difference in the GROSS label
  distribution between signal and control. Executable edge is the same comparison on `exe.net_ret_{h}` (entry at the
  first ask after T, exit at the first bid after T+h, minus 2 × 10 bps, plus the slippage sensitivity). Information
  without an executable edge is WEAK at most.
- **Reference cell `H01-REF` = `mom.mom_norm_15m_16 >= 1.0`.** It is predeclared before any outcome as the centre of
  the H01 grid (a one-sigma, volatility-scaled 4h move). It is NOT the best H01 cell and is never replaced by one.
  H02, H04, H05 and H06 use it as their fixed base, so their incremental tests do not depend on H01 outcomes.

| ID (ledger id) | Hypothesis, signal (deterministic) | Features | Grid (→ trials) | Control |
|---|---|---|---|---|
| **H01** `H-P2D-H01-tsmom-v1` | Time-series momentum. LONG if z_L ≥ θ. z_4h = `mom.mom_norm_15m_16`; z_1d = `mom.ret_1d_1` / (`vol.rv_1h_24`·√24) | `mom.mom_norm_15m_16`, `mom.ret_1d_1`, `vol.rv_1h_24` | lookback {4h, 1d} × θ {0.5, 1.0} × h {4h, 24h} → **8** | unconditional long, same rows; benchmarks |
| **H02** `H-P2D-H02-mom-liquidity-v1` | H01-REF AND confirmation: `liq.spread_norm_1h <= 1.0` or `liq.depth_imbalance_10 >= 0` (one at a time) | `mom.mom_norm_15m_16`, `liq.spread_norm_1h`, `liq.depth_imbalance_10` | confirmation {2} × h {2} → **4** | H01-REF alone (incremental) + random removal at the same pass rate |
| **H03** `H-P2D-H03-vol-expansion-v1` | compressed_prev = `vol.vol_ratio_15m_16_96` at T−15m ≤ c. Information mode: forward range (`mkt.mfe_{h}` − `mkt.mae_{h}`), no trade. Directional mode: LONG if compressed_prev AND `vol.range_expansion_15m_16 >= 2.0` AND `mom.body_ratio_15m > 0` | `vol.vol_ratio_15m_16_96`, `vol.range_expansion_15m_16`, `mom.body_ratio_15m` | mode {information, directional} × c {0.6, 0.8} × h {2} → **8** | non-compressed rows (information); the same expansion up-bar WITHOUT compression (high volatility alone is not a signal) |
| **H04** `H-P2D-H04-regime-v1` | Five rule-based regimes, first match wins: liquidity_stress (market median `liq.spread_norm_1h` ≥ 1.5) → elevated_vol (`ctx.btc_rv_1h_24` ≥ 1.5 × its trailing 7-day median) → trending_up / trending_down (broad: `ctx.universe_ret_24h_median` sign AND `ctx.breadth_24h` ≥ 0.6 / ≤ 0.4; btc: BTCUSDT-row `mom.mom_norm_15m_16` ≥ 0.5 / ≤ −0.5) → neutral. Application regime_only = LONG all eligible symbols in trending_up; h01ref_gated = H01-REF only in trending_up | `ctx.universe_ret_24h_median`, `ctx.breadth_24h`, `ctx.btc_rv_1h_24`, `liq.spread_norm_1h`, `mom.mom_norm_15m_16` | trend_definition {broad, btc} × application {2} × h {2} → **8** | unconditional long (regime_only); ungated H01-REF (gated) |
| **H05** `H-P2D-H05-rel-volume-v1` | H01-REF AND `act.rel_volume_15m_96 >= v` | `mom.mom_norm_15m_16`, `act.rel_volume_15m_96` | v {1.5, 3.0} × h {2} → **4** | H01-REF alone + random removal |
| **H06** `H-P2D-H06-no-trade-filter-v1` | REMOVE an entry if any rule holds. Standard: stale, degraded or clock-suspect data; a known gap in the last 1h; reconnect < 15 min; `liq.spread_norm_1h` ≥ 3; `liq.liq_change_15m` ≤ ln 0.5; `vol.range_expansion_15m_16` ≥ 5; spread null. Strict: reconnect < 1h; spread_norm ≥ 2; liq_change ≤ ln 0.7; range_expansion ≥ 3; `liq.depth_concentration_10` ≥ 0.5. Null filter input → remove (fail closed) | the `dq.*` features `stale_flag`, `degraded_flag`, `clock_suspect`, `gap_known_1h` and `reconnect_age_s`; the `liq.*` features `spread_bps`, `spread_norm_1h`, `liq_change_15m` and `depth_concentration_10`; `vol.range_expansion_15m_16`; `mom.mom_norm_15m_16` | strictness {2} × base {H01-REF, all eligible rows} × h {2} → **8** | unfiltered base; REMOVED vs KEPT outcomes; random removal at the same rate |
| **H07** `H-P2D-H07-cond-reversion-v1` | LONG if `mom.mom_norm_15m_16 <= −θ` AND condition (none, or `ctx.universe_ret_24h_median >= 0`). Never combined with momentum in round 1 | `mom.mom_norm_15m_16`, `ctx.universe_ret_24h_median` | θ {1.5, 2.5} × condition {2} × h {2} → **8** | unconditional long; the condition=none cell |

Each JSON entry also records the economic rationale, the per-parameter economic justification, the fixed
parameters with their reasons, the expected failure modes, the hypothesis-family overlay and the trial kind:
directional, incremental filter, information + directional, conditioning or removal filter.

**Total: 7 hypotheses, 48 planned round-1 trials** (8 + 4 + 8 + 8 + 4 + 8 + 8). Benchmark evaluations are counted
separately.

## 3. Excluded

ML, DL, RL, LLM trading decisions; news, social and on-chain data; unrestricted indicator generation; genetic or
Bayesian optimization; automated strategy mutation; large grids; feeding all 40 features into any optimizer;
combining hypotheses in round 1; shorting; non-crypto markets.

## 4. Baselines (frozen, `benchmarks_v1.json`)

Common rules: same execution model and cost cascade, same universe policy and the same evaluation windows as the
compared trials; never W3, never pre-E. The daily decision time is 00:06:30Z. Each benchmark evaluation is a ledger
trial under `H-P2D-BENCH-v1`; it is never selected and never counted in a hypothesis cap.

- **BENCH-CASH:** no position; return 0, cost 0, drawdown 0.
- **BENCH-BTC-BH:** buy BTCUSDT at the first eligible decision of the window at the ask and sell at the last
  eligible decision at the bid, paying one round trip of fees. It is a market reference for windows of at least one
  day, not a hurdle for short-horizon trials.
- **BENCH-BTC-TREND:** at the daily decision, go LONG BTCUSDT for 24h if the BTCUSDT `mom.ret_1d_1 > 0`, else FLAT.
  Labels: `mkt.fwd_ret_24h` and `exe.net_ret_24h`.
- **BENCH-TSMOM** (minimal multi-asset time-series momentum; it is not "B3", which is the production risk breaker):
  at the daily decision, go LONG equal-weight every eligible universe symbol with `mom.ret_1d_1 > 0`, FLAT the rest,
  and hold 24h. It is long/flat because spot cannot short.
- **BENCH-PAPER-R1:** realized PAPER-R1 (`PAPER-R1-20261004T152643Z`) forward outcomes from E onward, under its own
  governance, as forward evidence only. It is **not eligible now**: `exe.paper_outcome` is null
  (`paper_r1_linkage_not_authorized`). It becomes usable only through a separately authorized, predeclared linkage,
  and never with W3 data.

## 5. Parameter budget

- Round 1 trial caps: H01 8, H02 4, H03 8, H04 8, H05 4, H06 8, H07 8. The total cap is 48, equal to the plan.
- Each hypothesis has a lifetime cap of 24 trials across all rounds. Reaching it closes the hypothesis unless the
  owner approves a new version.
- The grids are frozen. A new value or grid needs a new recorded research round: a new plan file with its own hash,
  `parent_trial` links in the ledger and owner approval. Its trials are counted in addition to the earlier ones.
- Plateaus are preferred over a single optimum. A cell counts only if its grid neighbours have the same sign.
- Every evaluation that computes any outcome goes through the ledger, including smoke runs.

## 6. Multiple testing

- Counts reported: total trials, trials per hypothesis, related variants (same hypothesis and base), rejected
  trials, failed or aborted trials (pending trials count too) and benchmark evaluations (separately).
- Round 1 applies a Holm correction across each hypothesis' trials (family-wise α = 0.05, one-sided, positive
  effect). The global count over all 48 trials is reported next to it.
- Reserved for later: the Deflated Sharpe Ratio (N = all ledger trials), PBO (CSCV over the frozen grid), and
  parameter and temporal stability.
- Trials are never deleted (the ledger is append-only, one result per trial).
- The ledger head is anchored in every sealed evidence package.

## 7. Time-split policy

- **Ordering:** chronological only, no shuffling.
- **Eligible days:** UTC days from 2026-10-05 onward with a seal result of PASS that the reader accepts in sealed
  mode. 2026-10-04 (partial; its first hour is before E) is used only as feature warm-up and is never evaluated. A day
  with downtime stays eligible; its downtime rows are excluded and the day is flagged. Days are indexed in date
  order; skipped days are listed.
- **Minimum before any outcome: 28 full eligible sealed days.**
  - Two 7-day validation folds cover the weekly cycle (weekend liquidity) twice out of sample.
  - The first 13-day training window covers almost two weeks and the 7-day H04 volatility reference.
  - A 24h horizon allows at most one non-overlapping position per symbol per day, and crypto symbols are strongly
    correlated, so the effective sample is far smaller than the row count. With fewer days, every result would be
    INCONCLUSIVE by construction.
  - This is a minimum for any result to mean something, not a claim that 28 days is enough, and it is not a
    performance threshold. Round 1 is expected to be mostly INCONCLUSIVE.
- **Round 1 layout (eligible-day indices):**

  | Fold | Train | Embargo | Validate |
  |---|---|---|---|
  | 1 | days 1–13 | day 14 | days 15–21 |
  | 2 | days 1–20 | day 21 | days 22–28 |

  Days 29 and later are the **forward-untouched** window: no round-1 outcome reads them.
- **Embargo and purging:** a 1 full UTC day embargo, plus purging. A training row is dropped when its longest label
  window (T + 15 min anchor + 24h + 60 s) ends after the training end. The embargo is at least the longest label
  horizon (24h).
- **Evaluation:** expanding windows; classification uses validation folds only, and training results are reported
  for stability.
- **Later rounds** extend the expanding window by new 7-day folds and declare their own forward-untouched window
  before any outcome is computed.
- **Forward window:** opened only for a one-shot confirmatory check of frozen candidates, in a separately approved
  step.
- **W3** is always excluded; the ledger refuses any overlap.
- **PAPER-R1** is never used for iterative tuning.

## 8. Universe policy

- **Universe:** `universe-asof-all-tiers-v1`, the universe and tier epoch known at T (`ctx.tier`). Symbols that later
  leave the universe keep their past rows (no survivorship), and no symbol is backfilled.
- **Tiers:** 0, 1 and 2 are all eligible; every result is stratified by tier.
- **Liquidity:** no liquidity pre-filter (liquidity filtering is hypothesis H06).
- **Evaluability:** a row is evaluable for a trial only if every feature the trial uses is non-null. Rows with
  `insufficient_history` are counted by reason, never filled.
- **Exclusion reasons:** `in_downtime`, `no_universe_epoch_known`, `beyond_observed_data`, `pre_E_or_warm_up_day`,
  `day_not_sealed_PASS`, `feature_null:<reason>`, `regime_null` (H04) and `position_open`.
- **Null labels:** a position with a null label stays in the trade count. The null share is reported per arm and
  flagged if treatment and control differ. Selecting on label availability would be look-ahead.

## 9. Gross vs executable

The returns are built up in this order:

1. Gross edge: `mkt.fwd_ret_{h}`.
2. Spread: entry at the ask, exit at the bid (`exe.net_ret_{h}` + fees).
3. Fees: 2 × 10 bps.
4. Slippage assumption: a sensitivity of +0 / +5 / +10 bps per side, reported and not tuned.
5. Turnover: positions per day × round-trip cost.
6. Net result.

The execution model is top of book only: no depth walk, no latency model and no partial fills (P2-C O4). P2-D may
measure gross information first, but nothing is called economically successful before costs. P2-X (execution
quality) stays a separate stage.

## 10. Metrics contract and outcome categories

- **Trading economics:** trades, net and gross expectancy, profit factor, win rate, average win and average loss,
  payoff ratio, turnover.
- **Risk:** max drawdown, downside deviation, worst day and worst week, time under water, tail losses (p5 and p1),
  loss-streak distribution.
- **Risk-adjusted:** Sharpe, Sortino and Calmar, only where meaningful: at least 7 daily returns, Calmar only with a
  non-zero drawdown, annualized by √365.
- **Trade path:** MAE, MFE.
- **Robustness:** by time fold, symbol, tier and regime; parameter-neighbour sensitivity; P&L concentration; cost
  sensitivity.
- **Later:** DSR and PBO.
- **Information trials:** mean difference vs control, day-block bootstrap confidence interval, event count.
- **No single-metric ranking.**

| Category | Definition |
|---|---|
| SUPPORTED | Executable mean difference vs control > 0 with Holm-adjusted one-sided p < 0.05 (stationary bootstrap over day blocks) on the pooled validation folds. Also required: the same sign in every validation fold, the plateau holds and no concentration flag. |
| WEAK | The gross information effect passes the SUPPORTED test but the executable effect does not; or the executable effect is significant but a fold, plateau or concentration condition fails. |
| INCONCLUSIVE | Fewer than the minimum days, too few positions for the bootstrap, or confidence intervals that neither support nor reject. |
| REJECTED | The upper 95% bound of the GROSS mean difference is below the 20 bps round-trip fee, or the effect is significantly negative. |

The numeric concentration limits are **TBD** and must be owner-approved before the first outcome evaluation.

## 11. Concentration and regime diagnostics

- **Concentration:** % of profit from the top symbol and from the top 3, best-day and best-week share, single-regime
  share, and extreme-trade share (top 1% of |P&L|).
- **Regimes:** market direction (H04 broad and btc), volatility (BTC realized volatility vs its 7-day reference),
  liquidity (market `spread_norm`), symbol and tier, and time period (fold, week, UTC hour).

## 12. Draft Crypto Success Gate (design only, NOT active)

Evidence dimensions: robust research evidence, realistic costs, adversarial validation (P2-F), Shadow results, Paper
forward results, drawdown, execution quality (P2-X), edge stability (time, symbol, regime) and sample size. **All
thresholds are TBD** and must be owner-approved later. Nothing here activates a gate.

## 13. P2-D1 entry requirements

1. P2-D0 committed. **Met** by this commit.
2. Ledger head anchored. **Met** in the P2-D0 evidence: the ledger is empty, `seq = -1`, with the genesis hash.
3. Benchmarks frozen. **Met.**
4. Budgets frozen (budget section and `planned_trials_v1.json`). **Met.**
5. Metrics frozen. **Met.**
6. Time and universe policies frozen. **Met.**
7. A full eligible sealed day (2026-10-05) exercises the 9 features that need at least 24h of history and the 24h
   labels successfully, validated read-only. **PENDING:** 2026-10-05 seals around 2026-10-06 01:17Z.
   - **Features:** `act.rel_volume_15m_96`, `ctx.btc_rv_1h_24`, `mom.dist_high_15m_96`, `mom.dist_low_15m_96`,
     `mom.ret_1d_1`, `mom.trend_eff_1h_24`, `vol.atr_norm_1h_14`, `vol.rv_1h_24` and `vol.vol_ratio_15m_16_96`.
   - **Labels:** `mkt.fwd_ret_24h`, `mkt.mfe_24h`, `mkt.mae_24h`, `mkt.max_dd_24h`, `mkt.decline_24h` and
     `exe.net_ret_24h`.
   - **Validation scope:** counts, null reasons, PIT audit and rebuild hash only. No outcome distribution may be
     inspected, and no synthetic data may substitute for this gate.

## 14. Trial Ledger integration

**Decision:** the planned trials are frozen now (`planned_trials_v1.json`, hashed) and registered in the ledger
(`ledger.create_trial`) at the start of P2-D1, before any outcome is computed.

- **Why not register now:** a ledger spec needs a code commit, a dataset hash and train/validation periods, and none
  of these exist before the data gate. Placeholders would put fake dataset hashes into an immutable record.
- **How the plan stays bound:** the plan is immutable now through its hash. `protocol.ledger_spec()` builds each spec
  by binding `plan_id`, `plan_entry_sha256` and the four registry hashes into `parameter_spec`. It validates the spec
  through `ledger.validate_spec`, which refuses W3 and any non-crypto market, and it never writes.
- **Ledger now:** untouched, with no trial registered. Its empty head is anchored in the evidence.
