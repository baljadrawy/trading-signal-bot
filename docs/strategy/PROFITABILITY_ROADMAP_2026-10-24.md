# Strategic profitability review and prioritized roadmap (2026-10-24)

**Status: PROPOSAL for owner review.** This document proposes; it authorizes nothing. It runs no research, admits no
candidate, spends no alpha, declares no Paper window and changes no runtime state. Every initiative below that touches
data, Paper behaviour, production or confirmatory science stops at its named authorization gate.

**No runtime effect. No runtime claim.** Written from repository documents and code at `main` `ef3d735`, and from
the owner's memory notes (summaries of research already reported to the owner).

**Governance in force (unchanged by this document):** `EXECUTION_MODE = PAPER_ONLY`; live trading and any automatic
live transition are forbidden (owner directive 2026-09-27, four conditions). FORWARD_HOLDOUT (everything after the
2026-08-19 freeze instant, `docs/research_temporal_governance.md`) stays sealed. No sealed outcome, count or timestamp
was read or is quoted here; the current strategy's performance is referred to only qualitatively ("not accessible by
design").

## 0. How to read the evidence labels

| Label | Meaning |
|---|---|
| **[REPO]** | Checked in this worktree (documents or code at `ef3d735`). |
| **[HR]** | Historical record from the owner's memory notes, **not re-verified** in this task. Numbers are quoted as recorded. |
| **[INF]** | Inferred by this review from the above (reasoning, arithmetic or literature already cited in the repository). |
| **[PROP]** | A proposal of this document; nothing is decided by writing it. |

Three completion states are kept strictly apart throughout:

| State | Meaning | Who can declare it |
|---|---|---|
| **Engineering complete** | Code, tests, parity, CI, deployment mechanics work as specified. Says nothing about returns. | Reviewer + owner (merge/deploy) |
| **Scientific success** | A **pre-registered** hypothesis passes its **prospective** test under the Evidence Ladder (or an owner-approved successor design). Exploratory or synthetic success never counts. | Owner, per protocol |
| **Financial profitability** | Real net money after real costs. **Out of scope** under PAPER_ONLY; would require all four owner conditions (predeclared criteria, independent forward validation, verified execution and safety controls, explicit final approval) plus the data-licence question (A18/A19) to be resolved. | Owner only, separately |

---

## 1. What has actually been demonstrated about NET profitability?

**Short answer: no net profitability has been demonstrated anywhere in the project, under any cost assumption, for
any strategy family that is executable on Binance Spot long-only. The legacy 15m/4h/1d indicator family is losing
before costs (gross profit factor about 0.73 to 0.81 across independent measurements). The current strategy version's
performance is unknown by design (sealed holdout). Engineering correctness has been demonstrated extensively, and it
is not evidence of an edge.**

### 1.1 Cost basis used in this review

| Component | Value | Source |
|---|---|---|
| Exchange fee | 0.10 % per side, 0.20 % round trip, no BNB/VIP discount | owner baseline [REPO `DEVELOPMENT_FIRST_POLICY.md` §3; `research/mechanisms/costs.py` refuses discounts] |
| Spread | separate; declared half-spread tiers 0.01 % (BTC/ETH), 0.04 % (other top-20), stress ×2 | S4 pre-registration draft [REPO `S4_PHASE1_SCIENTIFIC_COMPARISON.md` §4] |
| Slippage | separate; 0.05 % per side, stress 0.10 % | same |
| Realistic total, liquid top-20 | about **0.32 % to 0.38 % round trip** (0.16–0.19 % per side) | [INF] arithmetic of the three rows above |
| Tracker accounting label | flat 0.30 % round trip (`FEE_ROUNDTRIP_PCT=0.3`), plus stop fills × (1 − 0.1 %) | [REPO `shared/config.py`, `shared/fees.py`]; reported beside, never instead of, the canonical model |
| Many 2026-05..07 backtests | 0.6 % round trip | [HR]; harsher than the canonical model, see §1.4 |

Stored `profit_usdt` / `profit_percent` are **gross** on a fixed 50 USDT notional; net is derived at display time
(`shared/fees.py`), and only the A38 tracker writes stored net labels (`label_policy = net_after_modeled_cost_v1`)
[REPO; HR A58]. Any figure taken directly from stored P&L is therefore gross.

### 1.2 Gross vs net, in-sample vs forward, by evidence stream

| Stream | Sample (as recorded) | Gross | Net | In-sample / forward | Class | Source |
|---|---|---|---|---|---|---|
| Pre-freeze live Paper, all versions (H0) | 3,401 trades, 2026-04-09 → 08-19 | PF 0.729, total negative | PF 0.593 at tracker cost; net WR 31.3 % vs break-even WR 43.5 %; day-clustered net t = −2.69 | forward Paper (unsealed, mixed versions) | operational/observational | [HR A58] |
| Same, cost share | — | costs ≈ 10.8 % of absolute gross | losses come mostly from **gross** geometry/entry, not fees | — | — | [HR A58] |
| Live DB audit | 2,518 trades, 93 % in April 2026 | PF 0.735 | net −0.365 USDT/trade at 0.3 % | forward Paper, one regime-month dominates | observational | [HR audit 2026-06-23] |
| Per-indicator analysis | 2,461 trades | PF 0.734; every indicator AUC 0.487–0.511; score **inverted** (higher score = worse) | negative | same data | observational | [HR 2026-06-07] |
| 3-year historical replay of the indicators | 287 symbols, 1h/4h/1d, 2023–2025 | gross PF about 0.75–0.79 per standalone indicator, stable every year; 0 of 43 configs net PF > 1 | net PF about 0.42–0.47 at 0.6 % | historical, research-exposed | exploratory | [HR 2026-06-07] |
| 9-year target-policy replay | 301 symbols, 2017–2026, about 110k trades per arm | PF 0.806 (current 1R target); **every arm × every year negative** | all arms negative | historical, research-exposed; optimistic intrabar assumption | exploratory | [HR 2026-06-24] |
| Live-learning cohort | 479 trades, 2026-06-26 → 07-14 | PF 0.587 as recorded; **after measurement correction about break-even** (de-duplicated, stop-modelled) | negative at every fee level | forward Paper | observational, measurement-defective | [HR learning audit 2026-07-14] |
| Reversion sub-cohort (the one "positive" claim) | in-sample n = 88 positive, not significant; OOS n = 96 | — | OOS significantly **negative** (p ≈ 0.0001); the claim inverted out of sample | forward Paper, OOS split | observational | [HR canary close + OOS re-audit] |
| Current strategy (signal-aware stops + regime routing, live from about the freeze instant) | sealed | not accessible | not accessible | sealed FORWARD_HOLDOUT | — | [HR Research-1A; REPO governance] |
| R2 Paper window (2026-10) | sealed period | not quoted | not quoted | sealed; operations evidence only (A17 F4) | operational | [HR A37/A17] |

**Interpretation [INF].** Three independent routes (live Paper, a 3-year replay, a 9-year replay on different data)
converge on a gross profit factor of roughly 0.73–0.81 for the legacy family. A gross-negative entry cannot be made
net-positive by any cost reduction; the cost model only changes how negative it is. The measurement defects found on
2026-07-14 (pseudo-replication, stop-fill asymmetry, fee-blind learner gate) inflated the recorded loss magnitude but
did not create the sign: the corrected forward view is about break-even **gross**, which is still negative net.

### 1.3 Exploratory positives that did not survive

| Thread | What looked positive | Why it is not demonstrated profitability | Source |
|---|---|---|---|
| Daily ML (XGBoost, 595 symbols incl. delisted) | positive net in all 6 walk-forward years at 0.6 %; shuffle control clean | positive **only in < 1M USDT micro-caps**; 6 months = 99 % of net; decaying about −1.1 %/yr; liquid tiers negative in 2026 | [HR 2026-06-25] |
| Faithful LuxAlgo SMC, daily CHoCH-in-discount | the only gross PF > 1 setup (1.06), n ≈ 3,157 | CI crosses 0 net; liquid > 5M USDT negative; 2026 significantly negative; leans on few winners | [HR 2026-07-06] |
| SMC demand-zone entry, tight stop / far target | large-n positive net | fat-tail lottery: excluding top 5 % trades turns it negative; decayed in 2025–2026; exits at supply (SMC as taught) are net negative | [HR 2026-07-06] |
| Cross-sectional momentum long/short | strong OOS 2025 in a post-hoc grid | 94 % of P&L in the **short** leg (not executable on Spot); high window variance; time-concentrated | [HR 2026-06-07] |
| Funding carry (spot long / perp short) | gross funding about +8.8 %/yr mechanism | fails all 4 pre-registered thresholds after costs; edge mostly 2021; uncontained liquidation tail; needs derivatives | [HR 2026-07-29] |
| 20/50 MA uptrend | huge headline mean | regime beta: strongly negative in 2018, 2022, 2025, 2026; as a gate on live trades it made results worse | [HR 2026-08-12] |
| Stop policy STOP-A | best per-trade in isolation, significant paired advantage | reverses to worst once the full production risk-halt chain is modelled (n < 100, underpowered) | [HR 2026-08-20] |

### 1.4 What the older 0.6 % cost assumption does and does not change

Most 2026-05..07 replays used 0.6 % round trip, roughly 0.25 percentage points per trade harsher than the canonical
0.32–0.38 % for liquid pairs [INF]. This does **not** rescue the legacy family (gross-negative). It does mean the two
daily "whispers" (daily ML on liquid tiers, daily CHoCH-in-discount) were judged under a cost about 1.6–1.9× the
canonical one. They remain research-exposed, decayed in the most recent years, and illiquid-concentrated, so a
re-qualification under the canonical cost would be **exploratory only** (§2, row W6) and could never confirm.

### 1.5 Engineering correctness that IS demonstrated (and is not an edge)

| Item | Status | Source |
|---|---|---|
| Replay vs real tracker parity, `tracker_event_v1` | 27/27 deterministic scenarios exact | [REPO `docs/a48/A48_REPLAY_FIDELITY.md`] |
| Cost ledger `a48-cost-v1` (fee 0.10 %/side, spread separate, slippage once) reconciles the legacy 0.30 % label term by term | done | [REPO A48] |
| Economic net labels at close, NaN/non-finite P&L refused | done (A38, A49) | [REPO `shared/fees.py`] |
| Signal integrity (setup key, insert-once, stale refusal) | built behind `SIGNAL_INTEGRITY_MODE`, default `off` in production | [REPO `shared/config.py`] |
| T1 cap correction | built behind `T1_CAP_POLICY`, default `legacy_window_v1` (byte-identical) | [REPO `shared/config.py`] |
| Test suites, CI | about 1,200+ default tests green at recent merges | [HR] |

**Bottom line for question 1.** Gross vs net: gross negative for the tested family, so net is negative under every
cost model. In-sample vs forward: forward Paper reproduces the historical gross-negative signature. Engineering vs
edge: engineering quality is high and improving; no edge exists in the record. Financial profitability: not
applicable (PAPER_ONLY) and not in prospect for the tested family.

---

## 2. Strategies and directions: failed / inconclusive / warrant investigation

Confidence is the confidence in the **verdict** for the tested implementation (principle 5 of the Development-First
policy: negative results are evidence against the tested implementations, not proof that every alternative fails).

### 2.1 Failed (do not reinvest)

| # | Direction (as tested) | Evidence | Confidence |
|---|---|---|---|
| F1 | 15m/4h/1h mean-reversion indicator scoring (RSI, Bollinger, Stoch-RSI, divergence, Fibonacci, order book) | live AUC ≈ 0.50; gross PF ≈ 0.73 live, ≈ 0.77–0.81 in 3-yr and 9-yr replays; every year negative [HR 06-07, 06-23, 06-24] | **High** |
| F2 | Indicator weight tuning, min-score thresholds | 48 weight sets flat; score inverted; live max score below thresholds tested [HR 05-25, 07-29] | High |
| F3 | Target/exit geometry redesign of F1 (mean-anchored T1, 0.5R, wide R:R, partial TP at T1) | every arm × year negative; partial TP net negative at every fraction [HR 06-24] | High |
| F4 | Momentum arm of the live-learning engine (15m/4h) | significantly negative net, forward [HR 07-06, 07-14] | High |
| F5 | Momentum → reversion preference flip (4f84717) | refuted out of sample; neutralized 2026-07-29 [HR] | High |
| F6 | SMC/ICT (crude features, faithful LuxAlgo port, demand→supply round trip) | 0/14 setups significant net; demand→supply significantly negative [HR 07-06; tr-ict research] | High |
| F7 | Market structure + falling wedge | random-entry null not rejected on any asset; survivorship mirage removed [HR 06-28] | High (low n, underpowered) |
| F8 | Volume + RSI multi-timeframe (user strategy) | negative per trade, CI crosses 0 only on the daily exit arm [HR 05-30] | Medium-high |
| F9 | ML on stored score details | purged walk-forward AUC < 0.5 [HR 06-23] | High |
| F10 | Funding carry (delta-neutral) | NO-GO on all pre-registered thresholds [HR 07-29] | Medium-high (mechanism real, post-cost edge absent) |
| F11 | Pairs / cointegration | fee-fragile, sign flips on removing 4 of 357, needs shorting [HR 07-29] | Medium |
| F12 | 20/50 MA uptrend as edge or as gate | regime beta; gate worsens live results [HR 08-12] | Medium-high |
| F13 | Learner as an edge source (`learned_gates`) | separates "very bad" from "bad", never from profitable; throttling benefit not significant [HR 07-14] | High |

### 2.2 Inconclusive (evidence weak, exposed or not executable)

| # | Direction | What is known | Why inconclusive | Confidence in "no tradeable edge as tested" |
|---|---|---|---|---|
| I1 | Daily ML "accumulation at discount" | real historical signal 2021–2024; illiquid only; decaying [HR 06-25] | research-exposed; capacity; decay | Medium-high |
| I2 | Daily CHoCH-in-discount (SMC) | only gross PF > 1 setup; fee-fragile [HR 07-06] | judged at 0.6 %; 2026 negative | Medium |
| I3 | Cross-sectional momentum long/short | real factor-like behaviour, regime-conditional [HR 06-07] | short leg not executable on Spot | Medium (for Spot long-only: high) |
| I4 | Stoch > 0 gate, spread gate | loss reducers, not edges [HR 06-23] | effect small, not significant | High that it is not an edge |
| I5 | STOP-A stop policy | isolated advantage, portfolio-level reversal [HR 08-20] | n < 100 at portfolio level | Medium |
| I6 | Current strategy (signal-aware stops + regime routing) | sealed | not accessible; mechanism test fails (A46 cost/R arithmetic) [REPO S5-PWR-1 register] | Not assessed (by design) |

### 2.3 Warrant investigation (mechanism-first, low prior, exploratory before any claim)

| # | Direction | Mechanism argument | Expected outcome [INF] | Main risk | Evidence route | Source |
|---|---|---|---|---|---|---|
| W1 | **Daily TSMOM long/cash, liquid top-20, literature-fixed 14-day lookback, ± volatility scaling** | trend-chasing/under-reaction at 1–2 weeks (Liu–Tsyvinski 2021; Dobrynskaya) | at best a **risk-adjusted improvement over buy-and-hold** (timed beta), not alpha | Huang et al. 2020 challenge; crashes; one-coin dominance | licence-cleared pre-freeze qualification, then prospective forward | [REPO S4 Phase 1, rank 1] |
| W2 | Cross-sectional momentum, long-only top-k weekly | relative under-reaction | weak (long-only ≈ market beta plus small tilt) | turnover cost; short leg missing | as W1 | [REPO S4 Phase 1, rank 2] |
| W3 | Volatility-managed market exposure (overlay) | Moreira–Muir; contested real-time (Cederburg 2020) | risk endpoint (drawdown/variance), no alpha | real-time failure | variance/non-inferiority endpoint | [REPO S4 M4] |
| W4 | Correlated-exposure (BTC-beta) cap | ~80 % common BTC component (Makarov–Schoar) | risk reduction | none economic | risk endpoint | [REPO A42 C2] |
| W5 | Execution-cost reduction: resting limit entries (`resting_limit_v1`), cost-coverage gate, spread gate | spread capture; avoid cost-dominated setups | lowers cost drag; cannot create gross edge | adverse selection; non-fill bias | shadow measurement of fill and non-fill rates | [REPO A38, A42 C1, S3] |
| W6 | Re-qualification of I1/I2 daily threads under the canonical cost model | daily horizon amortizes costs | probably still decayed/illiquid | research-exposed; garden of forking paths | exploratory only, logged as variants | [INF] |
| W7 | Funding/crowding **veto** as a filter on long entries (not carry) | crowded longs mean-revert | small, episode-bound n | licence; data contract | deferred | [REPO A42 C3] |
| W8 | New information sources (listings/events, on-chain, order-flow imbalance) | non-price information | unknown; data-heavy | licence, cost, capacity | literature + data-contract first | [HR 05-25 recommendation] |

**Not recommended as a profitability direction:** further refinement of the 15m/4h family (H2 extension cap, G3
entry offset, ranking v2). These are second-order gates on a gross-negative entry; their documented effect sizes sit
at or below the prospective MDE [REPO A45-G, S5-PWR-1 register]. Keep that family as the **baseline arm** only.

---

## 3. The most significant obstacles to a genuine edge

| # | Obstacle | Evidence | Consequence |
|---|---|---|---|
| O1 | **Cost wall vs move size at short horizons** | A46: 15m fee burden 0.22–0.43 R per trade; minimum T1 for a net-non-negative T1→break-even path 0.275 % (20 bps), 0.319 % (+5 bps spread), 0.376 % (30 bps); after T1, about 75 % of exits are at net break-even [REPO A46; HR A42] | at 15m an entry needs a very large gross edge just to pay costs; the daily and weekly horizons amortize costs over larger moves |
| O2 | **T1-capture geometry** | T1-only path needs 81–96 % hit rates; T3 path 40–66 %; legacy bearish T1-touch about 25 %; T1 cap self-referential for momentum (uses the breakout bar's high) [REPO A46; HR 06-24, A45 W3] | the 25/50/25 + break-even ladder is economically incoherent at small R; fixing it is a correction, not an edge |
| O3 | **No information in the tested entries** | AUC ≈ 0.50 for every indicator; gross-negative entries [HR] | geometry, selection and learning cannot amplify a zero signal |
| O4 | **Statistical power / MDE for forward confirmation** | 365-day daily-HAC annualized Sharpe MDE ≈ 3.5–7.0 (dependence 1–3); A17: 120-day contract feasible only for in-sample SR ≥ ~8.7; per-trade MDE 0.40 R at N = 100 (σ = 1 R), 0.1 R needs ≈ 1,600–4,900 trades [REPO S4 Phase 1 A3, `research/power`; HR A17, post-A56] | **no realistic strategy (SR well below 2) can be confirmed in one 365-day window**; this binds every family equally |
| O5 | **Multiple testing and adaptive search** | 50 backtest parts, hourly optimizer, many audits; "no valid N" for the legacy search [HR A19] | historical significance claims cannot be deflated honestly; only prospective tests with fixed alpha are clean |
| O6 | **Holdout scarcity and exposure** | every pre-W3 interval known-exposed for directional families; only prospective days from 2026-10-06 qualify as untouched; FORWARD_HOLDOUT sealed [HR A18, A19] | history can qualify or falsify, never confirm; forward time is the scarcest resource in the project |
| O7 | **Data licence** | Binance Vision terms (CC BY-NC-SA, §4.2 no live proprietary trading execution) published after our downloads; licence inquiry drafted, not sent [HR A18, A19, A22] | D1 exploratory research is blocked (no dataset has a `DatasetPermission`); any future live use needs counsel |
| O8 | **Regime non-stationarity and decay** | every exploratory positive decayed in 2025–2026; edges concentrated in a few months; 2021 regime beta [HR] | require per-year and remove-top-N robustness; expect decay haircuts; prefer mechanisms with economic rationale |
| O9 | **Execution realism** | replay stop fills optimistic by overshoot; Paper fills at observed price, no queue/partial fills, no tick/lot rounding; level-3 calibration (real cadence, queue, spread) not established [REPO A47, A48] | counterfactual numbers that involve stop exits are optimistic; small effects are inside model error |
| O10 | **Measurement-layer defects** | pseudo-replication (~31 % clones), same-candle re-fires, duplicate executions; fixed only under `SIGNAL_INTEGRITY_MODE=enforce`, which is off [HR 07-14, A43; REPO config] | Paper counts overstate independent n until enforce runs |
| O11 | **Spot long-only constraint** | most published crypto factor returns are long/short; internal XS momentum 94 % short leg [HR] | the executable opportunity set is mostly market beta plus timing |
| O12 | **Cross-asset dependence** | ~80 % common component in crypto returns (Makarov–Schoar) [REPO A45-B] | many simultaneous positions are one bet; effective n ≪ trade count |

**The binding pair [INF]:** O3 (no information in what has been tested) and O4 (no feasible confirmation design for
realistic effect sizes). Every other obstacle is secondary to these two. Engineering cannot fix O3; only a different
mechanism can. O4 is a design decision (OD-DF-2) and a calendar constraint: forward evidence accrues at one day per
day, so starting pre-registered forward observation early is the single most time-sensitive action available.

### 3.1 Illustrative sample-size arithmetic (no data used)

One-sided test, α = 0.05, power 0.8 (z sum ≈ 2.49); per-trade net return mean μ, standard deviation σ, design
effect DEFF (clustering of simultaneous/correlated trades):

N_required ≈ DEFF × (2.49 × σ / μ)²

| σ / μ (per trade) | DEFF 1 | DEFF 2 | DEFF 4 |
|---|---|---|---|
| 5 (e.g. μ = 0.4 %, σ = 2 %) | 155 | 310 | 620 |
| 10 (μ = 0.2 %, σ = 2 %) | 620 | 1,240 | 2,480 |
| 20 (μ = 0.15 %, σ = 3 %) | 2,480 | 4,960 | 9,920 |

At the Evidence Ladder's α = 1/240 the multiplier rises from 2.49 to about 3.48, roughly doubling N [INF from
`research/power` scenarios]. At one to five independent signals per day, a realistic edge (σ/μ ≥ 10) needs
**one to several years** of forward data. This arithmetic is illustrative and is not a protocol.

---

## 4. Engineering tasks that directly improve research, signal quality, execution quality and risk-adjusted performance

| # | Task | Improves | Why it matters for profitability research | State |
|---|---|---|---|---|
| E1 | Certified, licence-cleared, point-in-time, delisted-inclusive pre-freeze dataset (content-addressed snapshot, `DatasetPermission`) | research | unblocks every exploratory qualification; fixes the leveraged-product survivorship gap | blocked on OD-DF-1 + licence |
| E2 | Lab engine (`LAB_MODE`), per-strategy virtual accounts, target-position order path, `tsb_lab` DB | research, risk-adjusted | the only way to run ≤ 3–5 daily strategies forward in Paper without touching production; R0–R10 owner-decided | design approved in part; #67/#78 Draft |
| E3 | Shadow intents (Mode 2) for pre-registered daily strategies | research | starts the forward clock with zero P&L risk and zero production change | not started |
| E4 | Cost-model calibration: measured spread/depth tiers replacing declared tiers; ×1.5/×2 sensitivity on every result (lab rule R6) | execution, research | small effects live inside cost-model error (O9) | `a48-cost-v1` exists; tiers assumed |
| E5 | Resting-limit entry model (`resting_limit_v1`) with non-fill and adverse-selection measurement in shadow | execution | spread and slippage are roughly 40–50 % of the canonical round trip for alts; this is the only cost lever left after the fixed 0.20 % fee | built (A38), not activated |
| E6 | `SIGNAL_INTEGRITY_MODE=enforce` for the Paper baseline | signal quality | removes same-candle re-fires and duplicates; makes the baseline arm's n honest | built (A44), off |
| E7 | `T1_CAP_POLICY=independent_swing_v1` as a declared correction version | signal quality | removes a self-referential cap (W3) | built (#59 merged), default legacy |
| E8 | S3 selection in shadow (cost coverage, finite-spread guard, de-dup per setup key) | signal quality | prevents cost-negative T1 paths being selected | built, unwired |
| E9 | Variant/trial ledger with logged N per family; Deflated Sharpe and Romano–Wolf over the logged family | research | makes multiple-testing correction possible (O5) | partial (registries exist) |
| E10 | Per-candidate power/admissibility screen before any admission (`research/power`) | research | stops alpha being spent on underpowered tests | exists (S5-PWR-1) |
| E11 | Memory-bounded / streaming research loader (the naive table was ~10–13 GB) | research | makes multi-year daily and intraday qualification runnable on this host | open (A23/A26) |
| E12 | BTC-beta exposure cap and volatility targeting as risk modules in the lab path | risk-adjusted | reduces drawdown of beta-heavy long-only strategies (W3/W4) | specs only |
| E13 | Net-label consistency: one cost model in every report and learner (`a48-cost-v1` primary, tracker 0.30 % beside) | research hygiene | prevents gross/net confusion that already mis-stated results by ~60 % once | partial |

---

## 5. Low strategic value activities currently consuming effort

Estimated from the record [INF]; not a judgement on the quality of the work, which is high.

| # | Activity | Why the strategic value is low now | Recommendation |
|---|---|---|---|
| L1 | Successive refinements of confirmatory statistics without an admissible candidate (A25–A34 econ-rejection bound, HAC/skew remediation, envelope calibration, reserve rules) | no candidate exists to confirm; each cycle found new failure modes in synthetic worlds | **pause** after recording the current state; resume only when a candidate passes exploratory qualification. Use a simple conservative test set (Bonferroni/Holm + HAC t + stationary bootstrap + DSR with logged N) in the interim |
| L2 | Second-order refinements of the 15m/4h family (H2, G3, ranking v2, C1 gate) | cannot create an edge on a gross-negative entry; effects ≤ MDE | stop as profitability work; keep only corrections (E6, E7) |
| L3 | Release ceremony for changes with no profitability or safety impact (multi-stage soaks, per-PR provenance packets) | effort spent on mechanics of an edgeless strategy | keep for deployable service code and safety; simplify for docs/research (as `DEVELOPMENT_FIRST_POLICY.md` §4 proposes) |
| L4 | Collector feature hardening beyond minimal upkeep (flapping detectors, per-stream classifications) | collector data sits in the sealed holdout partition and has no admitted research use yet | **minimal upkeep only** until a research use is declared (cost calibration E4 is the strongest candidate, needs an owner ruling) |
| L5 | Monitoring Paper P&L of the legacy family for edge signals | sealed by design; known no-edge family; operations evidence only (A17 F4) | monitor liveness and integrity, not P&L |
| L6 | New indicators, timeframes or parameter sweeps on price-only directional TA | 40+ studies negative | stop |
| L7 | Repeated read-only audits that restate the same no-edge verdict | marginal information | one consolidated verdict (this document + A58) is enough until new evidence |

---

## 6. Infrastructure, data, compute and methods that could accelerate credible progress

| # | Accelerator | Effect | Dependency |
|---|---|---|---|
| X1 | **Send the licence inquiry (LIC-1)** and record a decision on dataset permission | unblocks all D1 exploratory work in one step | owner action |
| X2 | **Pre-registered forward shadow from day one** for 2–3 daily candidates (W1, W2, W3 overlay) | forward time is the binding resource; each day not observed is lost permanently | lab Mode 2 (E3) or a minimal standalone shadow logger |
| X3 | Validation design for realistic effects (OD-DF-2): long licence-cleared history for qualification, plus a multi-year prospective window with fixed alpha and non-binding futility | turns "never confirmable" into "confirmable for annualized SR ≈ 1.8 in about 4 years, ≈ 1.25 in about 8 years" (S4 Phase 1 A3, governed critical value, LRV 1; LRV 2 raises these by ~1.4×). Realistic SR ≈ 1 remains very hard to confirm; that is a fact to plan around, not a reason to loosen alpha | owner decision |
| X4 | Daily-horizon focus | daily runs cost about 1 CPU-second per 8-year × 20-asset simulation (measured, synthetic) | none; compute is not the constraint |
| X5 | Measured cost data (public REST book snapshots for the lab universe, or collector-derived tiers) | shrinks cost-model error on small effects | owner ruling if collector (holdout partition) data is used |
| X6 | Streaming loader + research admission budget (#80, #85) | safe multi-worker qualification on the shared host | review, then install approval |
| X7 | Simple, well-understood inference stack (HAC t, stationary bootstrap, Romano–Wolf, DSR with logged N, PBO/CSCV) | credible results without new methodology research | none (literature in S4 Phase 1) |
| X8 | Point-in-time universe service shared by research and lab | consistent survivorship handling across replay, shadow and forward | E1 |

Compute is **not** a bottleneck for daily strategies [REPO lab architecture §10: 0.86 CPU-s / 15 MB for an 8-year,
20-asset daily simulation]. The bottlenecks are data permission, forward calendar time and governance decisions.

---

## 7. Resource allocation recommendation

### 7.1 Current allocation (estimated from the record, 2026-08-19 → 2026-10-24) [INF]

| Area | Approx. share |
|---|---|
| Scientific validation methodology (A17–A34, ladder, power) | 30–35 % |
| Operational reliability (collector, backups, releases, soaks, incidents) | 35–40 % |
| Platform (CI, lab design, runner, release tooling) | 15–20 % |
| Profitability research (new mechanisms, signal/execution quality) | 10–15 % |

### 7.2 Recommended allocation [PROP]

| Area | Next 4–6 weeks | Steady state after P0 closes | What it buys |
|---|---|---|---|
| **Profitability research** (mechanism specs, licensed exploratory qualification, forward shadow, cost/execution research) | 35 % | 45 % | the only route to O3 |
| **Scientific validation** (pre-registration, OD-DF-2 design, variant ledger, independent check of critical values) | 20 % | 20 % | credible claims; avoids spending alpha badly |
| **Operational reliability** (backups off-host, liveness, halt recovery, least privilege, minimal collector upkeep) | 30 % (P0 front-loaded) | 15 % | continuity and safety; protects evidence |
| **Platform** (lab engine, streaming loader, admission budget, CI) | 15 % | 20 % | enables forward multi-strategy Paper |

The shift is from validation methodology and operations toward mechanism research and forward observation, with
reliability work concentrated in P0 and then reduced to upkeep.

---

## 8. Roadmap

Each initiative lists: **contribution** (what it changes), **dependencies**, **acceptance** (measurable),
**evidence** (what proves acceptance), **gate** (who/what approves). "D0" means safe development under the standing
Development-First authorization (code, tests, synthetic data, docs, Draft PRs) — **if the owner merges
`DEVELOPMENT_FIRST_POLICY.md`; until then existing records govern**.

### P0 — Safety and continuity

| ID | Initiative | Contribution | Dependencies | Acceptance criteria | Required evidence | Gate |
|---|---|---|---|---|---|---|
| P0-1 | Repair the nightly bot backup and add an off-host encrypted copy (CP-6 after CP-7 key escrow) | protects evidence, DB and recovery points; last good p1bg set predates 2026-10-10 [HR] | OD-DF-4 backup model; R1.3 | 7 consecutive successful nightly runs; one off-host copy verified by restore; one restore drill of `trading_signals` and evidence to a disposable instance | run logs, SHA256SUMS, restore-test transcript | owner (Class B host change; off-host transfer) |
| P0-2 | Pipeline-liveness monitor (#87) | detects an idle pipeline that healthchecks miss [HR ops 10-22] | review | alert within 2 scanner cycles of zero-candidate operation in a synthetic test; zero false alerts over a 7-day observation | test report; alert log | owner (merge, then install) |
| P0-3 | Technical-halt recovery workflow (#89) + append-only audit log (#88) | separates technical halts from outcome halts without reading protected outcomes; actor recorded on pause/resume (SEC-5) | review | recovery path covers the technical halt class in tests; risk controls byte-identical; every pause/resume has an actor | tests, mutation results | owner (merge; activation separate) |
| P0-4 | Least-privilege DB roles for schema 11 (#36) and a credential rotation plan (SEC-1/SEC-3) | removes the shared superuser role and the committed credential literal risk | P0-1 (fresh verified backup); inventory of all clients on the shared cluster | role suites pass on schema 11 test DB; every service starts under its own role in a disposable stack; rotation runbook reviewed | test logs; runbook | owner (Class B rollout; history rewrite is a separate decision) |
| P0-5 | PAPER_ONLY invariants as tests and branch protection (#90) | guarantees no live path appears by accident | review | a CI test fails if any live execution path, exchange signing or `PAPER_TRADING=false` default appears; main protected | CI run; branch settings | owner |
| P0-6 | Dependency locks (#86) | reproducible images; removes version drift between services | review | lock files for every service; image rebuild reproduces the running dependency set or lists each difference | diff report | owner (merge; builds separate) |
| P0-7 | Holdout seal integrity check | protects the only untouched forward evidence | none (D0) | automated check: seal SEALED, look count unchanged, no lab/research mount of post-freeze paths | check output in CI or ops | D0 to build; owner to install |

### P1a — Profitability research and signal/execution quality

| ID | Initiative | Contribution | Dependencies | Acceptance criteria | Required evidence | Gate |
|---|---|---|---|---|---|---|
| P1a-1 | **Dataset permission + certified pre-freeze dataset** (E1) | unblocks all exploratory qualification | X1 licence inquiry; OD-DF-1 | `DatasetPermission` recorded; content-addressed snapshot ending before the freeze; PIT universe incl. delisted; survivorship gaps listed | permission record; dataset manifest hash; verify-dataset PASS | **owner** (licence + permission) |
| P1a-2 | **Freeze the W1/W2 pre-registration** (TSMOM long/cash 14-day ± vol scaling; XS long-only top-5 weekly; benchmarks; canonical costs; failure criteria) | converts the S4 Phase 1 draft into an immutable spec before any data is touched | P1a-1 can run in parallel; spec must be frozen first | spec committed with hash; every variant enumerated; failure criteria fixed; cost stress ×2 declared | committed spec + hash | **owner** (accept pre-registration) |
| P1a-3 | One exploratory qualification run per frozen spec | first credible read on W1/W2 under canonical costs | P1a-1, P1a-2, P2-3 | runs exactly once per spec; all variants logged; report states class EXPLORATORY; predeclared failure criteria evaluated | run manifest, variant ledger, report | owner (dataset use); results never confirmatory |
| P1a-4 | Forward **shadow** of the frozen specs (no P&L, intents only) | starts forward clock immediately (X2) | P1a-2; a minimal shadow logger or lab Mode 2 | intents logged daily with decision-time inputs, hash-chained; ≥ 99 % daily completeness; no post-freeze data used for anything but the forward record | shadow ledger; completeness report | owner (declare shadow window) |
| P1a-5 | Cost-model calibration (E4) | measured spread/depth tiers for the lab universe | source decision (public snapshots vs collector data) | tiers measured on ≥ 30 days; ×1.5/×2 sensitivity attached to every result; discount fees refused | calibration report | owner ruling if collector data used; D0 for code |
| P1a-6 | Resting-limit entry research (E5) in shadow | quantifies spread capture vs non-fill/adverse selection | P1a-4 or Paper shadow | non-fill rate and post-fill drift measured per tier with CIs; net cost saving vs market entry estimated | shadow report | owner (activation = new strategy version) |
| P1a-7 | Paper baseline integrity: `SIGNAL_INTEGRITY_MODE=enforce` as a declared window (E6) | honest baseline n; removes duplicates | A44 image validation; fresh recovery point | re-fire and duplicate execution rate 0 in the window; no lost signals | integrity counters (non-outcome) | owner (declared Paper window) |
| P1a-8 | T1 cap correction version (E7) | removes self-referential T1 cap | P1a-7 window boundary | flag switch recorded as a version boundary; byte-identity at default retained | version record | owner (flag switch) |
| P1a-9 | Selection shadow S3 (E8) | cost-aware selection data without behaviour change | sidecar approval | shadow decisions recorded for ≥ 30 days; agreement/disagreement with live selector reported (no P&L) | shadow records | owner (shadow wiring) |
| P1a-10 | Risk overlays W3/W4 as lab modules | lower drawdown of beta-heavy candidates | P2-1 | variance / max-drawdown endpoint spec frozen; synthetic tests | spec + tests | D0 to build; owner to activate |
| P1a-11 | Formal decision: retire the 15m/4h family as a profitability candidate, keep as baseline arm | stops L2 effort | none | owner decision recorded | decision note | **owner** |

### P1b — Scientific evidence and validation

| ID | Initiative | Contribution | Dependencies | Acceptance criteria | Required evidence | Gate |
|---|---|---|---|---|---|---|
| P1b-1 | **Validation design for realistic effects (OD-DF-2)** | makes confirmation feasible in principle for SR ≈ 1.5–2 over multi-year windows (§6 X3) | none to draft | design states horizon (multi-year), fixed alpha, final-look or group-sequential rule with non-binding futility, endpoint (daily net active return vs B&H, HAC), and a power table showing ≥ 0.8 at the declared effect range | design doc + `research/power` output | **owner** |
| P1b-2 | Variant/trial ledger and multiplicity reporting (E9) | honest deflation of every result | none (D0) | every run appends variant, dataset hash, config hash, git SHA before results are read; DSR and Romano–Wolf computed over logged N | ledger + tests | D0; owner to make mandatory |
| P1b-3 | Close the contamination-registry gap (2026-01..06 researched but unregistered) | correct exposure classification | none | registry entry added with source records | registry diff | owner (governance record) |
| P1b-4 | Independent validation of critical values (OD-5) — **minimal scope** | needed before any admission | P1b-1 | the chosen test set's size verified at the declared alpha under AR(0.3) and skewed returns in an independent harness; one run, results immutable | validation report | owner (compute approval) |
| P1b-5 | Per-candidate admissibility screen before admission (E10) | prevents underpowered admissions | P1b-1 | screen output attached to every admission request; underpowered → not admitted | screen report | D0; owner decides admission |
| P1b-6 | A48 replay design review (input route, A_OBS_IN_BAR, conditional intervals) | resolves counterfactual-evaluation policy | none | three decisions recorded | decision note | owner |
| P1b-7 | Evidence-class label enforced in every report | prevents exploratory success being read as profitability | none (D0) | report generator refuses output without class label; tests | tests | D0 |
| P1b-8 | First governed admission (only if a candidate passes P1a-3 and P1b-5) | the first possible scientific success | P1a-3, P1b-1, P1b-4, P1b-5 | admission spec frozen with alpha, horizon, endpoint, stop rules | admission record | **owner — scientific authorization gate** |

### P2 — Performance and research infrastructure

| ID | Initiative | Contribution | Dependencies | Acceptance criteria | Required evidence | Gate |
|---|---|---|---|---|---|---|
| P2-1 | Lab engine `LAB_MODE` + accounts + target-position path + `tsb_lab` (E2; #67, #78) | multi-strategy forward Paper without production change | architecture review; isolation tests (lab §11.3) | production tracker outputs byte-identical with `LAB_MODE` unset; accounting invariants and RLS isolation tests pass on a disposable cluster | test reports | owner (merge; DB creation; deploy separate) |
| P2-2 | Research admission budget (#80, #85) | safe concurrency on the shared host | review | I-1/I-2 tests pass; shadow decisions logged for 14 days with no unexplained refusal | logs | owner (install, enforce) |
| P2-3 | Streaming / month-chunked research loader (E11) | multi-year runs within memory budget | none (D0) | peak RSS ≤ 4 GiB on a synthetic 9-year, 600-symbol daily+4h table; outputs byte-identical to the in-memory path on small fixtures | benchmark + parity tests | D0 |
| P2-4 | Content-addressed results and experiment registry (lab G5) | reproducibility | P1b-2 | rerun with same inputs gives byte-identical artifacts | reproducibility test | D0 |
| P2-5 | Evidence/outbox retention policy (DB-5) and telemetry write reduction applied | disk and backup stability | P0-1 | retention documented; no unbounded growth over 30 days | growth metrics | owner (install) |
| P2-6 | CI hardening: flaky collector e2e tests fixed (#81), DB suite in CI | trustworthy green | review | 20 consecutive green runs on main | CI history | owner (merge) |

### P3 — Noncritical platform

| ID | Initiative | Contribution | Dependencies | Acceptance criteria | Required evidence | Gate |
|---|---|---|---|---|---|---|
| P3-1 | Telegram-gated dashboard (A59) | convenience | P0-4 read-only role; loopback binding | read-only role only; no holdout data displayed | security review | owner |
| P3-2 | Documentation consolidation (stale headers, Git guide conflicts) | lower onboarding cost | none (D0) | conflicts listed in the reconciliation register resolved | docs PR | owner (merge) |
| P3-3 | Collector feature work beyond upkeep | low until a research use is declared | P1a-5 decision | — | — | owner |
| P3-4 | Runtime ↔ GitHub parity automation (#56) | drift visibility | none | parity report generated on demand | report | owner |

---

## 9. Measurable milestones

### 9.1 Profitability milestones (scientific → financial; each later milestone requires the earlier ones)

| ID | Milestone | Measurable criterion | Class |
|---|---|---|---|
| PM-0 | Mechanism spec frozen | P1a-2 spec hash committed before any data access; every variant enumerated | engineering/governance |
| PM-1 | Exploratory qualification pass | on the licence-cleared pre-freeze dataset: mean daily **net active** return vs equal-weight B&H > 0 with HAC t ≥ 2 (Bartlett lag 7) **and** stationary-bootstrap 95 % CI excluding 0; DSR > 0.95 with N = all logged variants; none of the 5 predeclared failure criteria triggered (incl. sign stable under ×2 cost stress, ≤ 50 % P&L from 5 months or 1 coin) | **exploratory** (never confirmation) |
| PM-2 | Forward observation sufficiency | pre-registered forward sample reaches its pre-computed N: for per-trade endpoints N ≥ DEFF × (z × σ/μ)² with σ, μ_MDE and DEFF declared in the spec (§3.1); for daily portfolio endpoints, the horizon from the OD-DF-2 power table | prospective observation |
| PM-3 | Forward net expectancy | on that pre-registered forward sample: **net expectancy per trade (or per day) after 0.20 % fees + modelled spread and slippage (`a48-cost-v1`) with a one-sided lower confidence bound > 0 at the declared alpha**, robust to ×1.5 cost stress and to removing the top 1 % of trades; DEFF-adjusted or day-clustered inference | prospective observation; becomes **scientific success** only under PM-4 |
| PM-4 | Scientific success | the governed admission (P1b-8) ends PROSPECTIVELY_SUPPORTED (or the OD-DF-2 successor equivalent) at the final look | **confirmatory** |
| PM-5 | Financial profitability | not a roadmap milestone. Requires the four owner conditions, licence clearance for any Vision-qualified strategy, and an explicit owner decision | **out of scope (PAPER_ONLY)** |

### 9.2 Evidence-quality milestones

| ID | Milestone | Measurable criterion |
|---|---|---|
| EQ-1 | Dataset permission | ≥ 1 `DatasetPermission` recorded with licence basis; snapshot verify PASS |
| EQ-2 | Exposure registry complete | contamination registry covers every researched interval; 2026-01..06 gap closed |
| EQ-3 | Variant accounting | 100 % of research runs in the ledger before results are read (audit of runs vs ledger = 0 orphans) |
| EQ-4 | Evidence-class labels | 100 % of reports carry a class label; generator refuses unlabeled output |
| EQ-5 | Cost-model calibration | measured spread tiers for the lab universe; every result carries ×1.5/×2 sensitivity and a "fragile" flag on sign change |
| EQ-6 | Replay fidelity maintained | `tracker_event_v1` parity 27/27 on every change; Mode 3 assumptions named in every use |
| EQ-7 | Honest Paper n | under integrity enforce: same-candle re-fire rate = 0, duplicate executions = 0 (non-outcome counters) |
| EQ-8 | Critical values validated | independent size check within declared tolerance at the declared alpha (P1b-4) |
| EQ-9 | Holdout integrity | seal state and look count unchanged at every milestone review |

### 9.3 Reliability milestones

| ID | Milestone | Measurable criterion |
|---|---|---|
| RM-1 | Backups | 7 consecutive successful nightly bot backups; off-host copy exists; restore drill PASS within 30 days |
| RM-2 | Liveness | idle-pipeline alert fires in ≤ 2 cycles in a synthetic test; 0 undetected idle periods > 1 hour over 30 days |
| RM-3 | Signal delivery | 0 lost signals; genuine dead letters alerted within 1 hour |
| RM-4 | Least privilege | no service uses a superuser role; 0 credential literals in tracked files at HEAD |
| RM-5 | Halt handling | technical halts recoverable via the reviewed workflow with recorded actor; outcome halts unchanged |
| RM-6 | CI | 20 consecutive green runs on main; flaky tests quarantined with issues |
| RM-7 | Collector (upkeep only) | daily seals complete; reboot recovery documented; no research job blocked > 24 h by collector state without an alert |

---

## 10. Safe work that can start immediately (no scientific authorization)

All of the following are **D0** (code, tests, synthetic data, docs, Draft PRs) and touch no data, Paper behaviour,
holdout or production:

1. Draft the immutable W1/W2 pre-registration file (P1a-2) from S4 Phase 1 §4, with variant enumeration and hash —
   **for owner acceptance; not frozen until accepted**.
2. Minimal forward **shadow logger** design and synthetic tests (P1a-4), standalone or as lab Mode 2.
3. Lab engine pure modules and tests (P2-1 parts): accounting invariants, reservations, R9 states, target-position path,
   production byte-identity tests.
4. Streaming research loader with synthetic benchmarks (P2-3).
5. Variant/trial ledger, DSR and Romano–Wolf utilities with synthetic tests (P1b-2).
6. Evidence-class label enforcement in report generators (P1b-7).
7. Cost-model calibration code and sensitivity harness on synthetic book data (P1a-5 code only).
8. OD-DF-2 design draft with `research/power` tables (P1b-1 draft).
9. PAPER_ONLY invariant tests and holdout-seal check (P0-5, P0-7).
10. Review fixes on existing Drafts: #87 liveness, #89 halt recovery, #88 audit log, #86 locks, #36 roles, #85 admission
    shadow, #67/#78 lab guards.

Not D0 (needs the owner even though "small"): any DB read, any dataset use, any Paper flag or window, any merge,
any install on the host, any collector action, any use of post-freeze data.

## 11. Owner decisions needed (in recommended order)

| # | Decision | Unblocks | Recommendation [PROP] |
|---|---|---|---|
| RD-1 | Merge or amend `DEVELOPMENT_FIRST_POLICY.md` (D0 standing authorization) | §10 safe work at full speed | merge (with amendments as desired) |
| RD-2 | Send the licence inquiry (LIC-1) and decide dataset permission (OD-DF-1) | P1a-1, P1a-3, all exploratory research | send now; decide on reply or on counsel |
| RD-3 | Accept (or amend) the W1/W2 pre-registration | P1a-3, P1a-4 | accept before any data is touched |
| RD-4 | Declare a forward **shadow** window for the frozen specs | starts the forward clock (X2) | declare as soon as RD-3 is accepted |
| RD-5 | Validation design for realistic effects (OD-DF-2) | P1b-4, P1b-8 | multi-year prospective, fixed alpha, non-binding futility; historical = qualification only |
| RD-6 | Retire the 15m/4h family as a profitability candidate; keep as baseline arm | stops L2 | yes |
| RD-7 | Pause further confirmatory-statistics development (A34-VS1 line) until a candidate passes PM-1 | frees capacity (L1) | yes; keep records immutable |
| RD-8 | Backup model (OD-DF-4) and off-host copy | P0-1 | approve |
| RD-9 | Least-privilege rollout and credential rotation plan | P0-4 | approve plan; schedule after P0-1 |
| RD-10 | Paper baseline: integrity enforce window and T1 correction version; resume or keep the current administrative pause | P1a-7, P1a-8 | owner's call; neither affects profitability research |
| RD-11 | Collector purpose: minimal upkeep vs declared research use (e.g. cost calibration from holdout-partition data) | P1a-5 source, L4 | minimal upkeep unless a use is declared |
| RD-12 | Lab architecture final approval and `tsb_lab` creation | P2-1, lab Mode 3 | approve after isolation tests |
| RD-13 | Resource allocation (§7.2) | all | adopt for the next 4–6 weeks, then review |

## 12. Scientific authorization gate

This document stops here. It does **not**:
- authorize any dataset use, backtest, simulation, research job or confirmatory experiment;
- freeze any pre-registration, declare any Paper or shadow window, or admit any candidate;
- change any HOLD (A34-VS1, MI Stage B, B2, P2-D1, Paper R2, D1–D5) or any owner decision OD-1..OD-7;
- read, quote or rely on any sealed-holdout outcome;
- propose, enable or prepare live trading.

Every item above marked owner, RD-* or "gate" requires an explicit owner decision recorded in the normal way.

## Appendix A. Source map

Repository (`main` `ef3d735`): `docs/governance/DEVELOPMENT_FIRST_POLICY.md`; `docs/lab/STRATEGY_LAB_ARCHITECTURE.md`;
`docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md`, `S4_MECHANISM_COMPARISON.md`, `S4_PHASE1_SCIENTIFIC_COMPARISON.md`,
`S5_PWR_1_OWNER_DECISIONS.md`, `EVIDENCE_LADDER_PARAMETERS.md`; `docs/a45/`, `docs/a46/`, `docs/a47/`, `docs/a48/`;
`docs/ops/RESEARCH_ADMISSION_CONTROLLER_IMPLEMENTATION_PLAN.md`; `docs/edge_research_foundation.md`;
`shared/fees.py`; `shared/config.py`; `research/power/`; `research/mechanisms/`; open Draft PRs #3, #15–#19, #29,
#36, #48, #56, #67, #78, #84–#90.

Owner memory notes (historical record, not re-verified): edge leaderboard; research conclusion 2026-05-25; indicator
deep analysis 2026-06-07; cycle 19 verdict 2026-06-12; live-DB audit 2026-06-23; T1-capture audit 2026-06-24;
target-policy 9-year backtest 2026-06-24; ML daily edge 2026-06-25; falling wedge 2026-06-28; live-learning review
and SMC faithful test 2026-07-06; canary close and OOS re-audit; learning deep audit 2026-07-14 with 07-29 and
08-12 updates (funding carry, 20/50 MA); stop-policy validation 2026-08-20; Research-1A/1B 2026-09-27; governance
PAPER_ONLY; A17–A34; A37–A49; S3 selection; A58 profitability; A60 audit; post-A56 critical path; Paper performance
audit 2026-10-20; Development-First phase; lab alignment; release RC, Stage A and ops assessment 2026-10-22.
