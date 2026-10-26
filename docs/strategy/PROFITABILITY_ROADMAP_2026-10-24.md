# Strategic profitability review and prioritized roadmap (2026-10-24, revision 2)

**Status: PROPOSAL for owner review.** This document proposes; it authorizes nothing. It runs no research, admits no
candidate, spends no alpha, declares no Paper or shadow window and changes no runtime state. Every initiative that
touches data, Paper behaviour, production, prospective observation or confirmatory science stops at its named gate.

**No runtime effect. No runtime claim.** Written from repository files (worktree based on `main` `ef3d735`) and from
the owner's memory notes (historical record). No database, research-data directory, container or computation was used.

**Governance in force (unchanged):** `EXECUTION_MODE = PAPER_ONLY`; live trading and any automatic live transition
are forbidden (owner directive 2026-09-27). FORWARD_HOLDOUT (everything after the 2026-08-19 freeze instant) stays
sealed. No sealed outcome, count or timestamp was read or is quoted; the current strategy's performance is referred
to only qualitatively.

## 0. Evidence classes and completion states

Every claim and table row carries exactly one of four labels.

| Label | Class | Meaning |
|---|---|---|
| **[HR]** | HISTORICAL RECORD | From the owner's memory notes or older audits as recorded. **Not re-verified in this revision.** Numbers are quoted as recorded. |
| **[VRF]** | VERIFIED REPOSITORY FACT | Checked **now** (2026-10-24) in this worktree or via the GitHub PR list; the file/path is named. "(derived)" marks plain arithmetic on verified constants. |
| **[ASM]** | ASSUMPTION | A judgement, interpretation or modelling choice of this review. May be wrong; stated so it can be challenged. |
| **[PROP]** | PROPOSAL | Something this document recommends. Nothing is decided by writing it. |

Facts verified in this revision [VRF]:

| Fact | Path checked |
|---|---|
| Fee model: stored `profit_usdt`/`profit_percent` are **gross**; net = gross − `FEE_ROUNDTRIP_PCT` at display; A38 economic label `net_after_modeled_cost_v1`; non-finite gross refused | `shared/fees.py` |
| `FEE_ROUNDTRIP_PCT` default 0.3 (comment: 0.1 %/side fee + about 0.1 % slippage); `TRADE_AMOUNT_USDT` 50; `STOP_SLIPPAGE` 0.001; `MIN_ORDER_NOTIONAL_USDT` 5; `PAPER_TRADING` default true | `shared/config.py` |
| `PAPER_ENTRY_FILL_MODEL` default `observed_price_v0` (`resting_limit_v1` is an owner-gated contract change); `SIGNAL_INTEGRITY_MODE` default `off`; `T1_CAP_POLICY` default `legacy_window_v1` | `shared/config.py`, `shared/entry_execution.py` |
| Research cost model `s4-mech-v1`: fee 0.10 %/side, **refuses** any fee below it (no BNB/VIP discount); spread and slippage separate; cost = turnover × (fee + half-spread + slippage); tracker 0.30 % is reporting-only | `research/mechanisms/costs.py` |
| Declared tiers: half-spread 0.01 % BTC/ETH, 0.04 % other top-20 (stress ×2); slippage 0.05 %/side (stress 0.10 %); benchmarks BTC, ETH, equal-weight B&H, cash; HAC Bartlett lag 7; Romano–Wolf; DSR over all logged variants; five failure criteria; power table A3 | `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md` §4, App. A |
| Principle 5: negative results are evidence against the **tested implementations**, not proof that every alternative fails; cost baseline rule; evidence-class rule | `docs/governance/DEVELOPMENT_FIRST_POLICY.md` §1, §3 (still a Draft policy) |
| Freeze knowledge cutoff date 2026-08-19; holdout status field reads `SEALED` (look count not reproduced here) | `research/governance/research_freeze.json`, `holdout_status.json` |
| Contamination registry has 4 entries: 2017-08 → 2022, 2023 → 2025, 2026-07-01 → freeze, freeze → open; **2026-01 → 06 is not registered** | `research/governance/contamination_registry.jsonl` |
| `validation_usage.jsonl` exists (look ledger); `hypotheses.jsonl` is empty (no hypothesis registered) | `research/governance/` |
| Alpha per governed admission 1/240 (LATEST_DOCUMENTED); calibration level unvalidated (DR-2 unresolved) | `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md` |
| A46 minimum T1 for a net-non-negative T1 → break-even path 0.275 % at 0.30 % round trip | `docs/a46/A46_TRADE_GEOMETRY.md` |
| A48 tracker parity 27/27 exact | `docs/a48/A48_REPLAY_FIDELITY.md` |
| Lab benchmark: 8-year × 20-asset daily simulation 0.86 CPU-s, 15 MB | `docs/lab/STRATEGY_LAB_ARCHITECTURE.md` |
| Open Draft PRs: #3, #15–#19, #29, #36, #48, #56, #67, #78, #84–#91. Merged: #59 (T1 cap), #80 (admission I-1), #81 (flake fix), #83 | `gh pr list` / `gh pr view` |

Three completion states stay apart: **engineering complete** (code/tests/parity; says nothing about returns),
**scientific success** (a preregistered hypothesis passes its prospective test under governed alpha; exploratory or
synthetic success never counts), **financial profitability** (real net money; out of scope under PAPER_ONLY).

---

## 1. Definitions: net profitability and three performance notions

All definitions in §1 are **[PROP]** unless a row or bullet carries another label.

### 1.1 Net return per trade (Binance Spot, long-only)

Let M_e, M_x be mid prices at entry and exit decision, h the half-spread, q the slippage per side and f the fee rate.

- Effective prices: P_buy = M_e × (1 + h_e + q_e); P_sell = M_x × (1 − h_x − q_x).
- Fees: Binance charges f on each fill (buy fee in the received asset, sell fee in quote), so
  **r_net = (P_sell / P_buy) × (1 − f)² − 1 − c_round**, with f = 0.001 (0.10 %/side, no BNB/VIP discount) [VRF `costs.py`].
- Additive approximation: r_net ≈ r_gross(mid) − 2f − (h_e + h_x) − (q_e + q_x) − c_round.
- c_round: residual from rounding quantity down to the lot step and price to the tick; unsold dust valued at zero;
  any order below the minimum notional (repo default 5 USDT [VRF `shared/config.py`]) is a non-trade, not a trade.
- Stop exits: fill at the stop × (1 − 0.001) in the tracker [VRF `STOP_SLIPPAGE`]; a gap through the stop fills at
  the first traded price beyond it (replay stop fills are optimistic otherwise [HR A47]).
- Partial fills: return on the filled quantity; the unfilled remainder earns 0. Failed fills (resting orders that never
  fill) are logged as intents with outcome "no fill" and included in non-fill-bias analysis, never dropped [PROP].
- Not applicable / not counted: funding (spot, no leverage); borrow; withdrawal and deposit fees (positions stay on
  the exchange); taxes; interest on idle cash (0, conservative) [ASM].

### 1.2 Net return per period (portfolio)

R_t = Σ_i w_{i,t−1} × r_{i,t} − Σ_i |Δw_{i,t}| × (f + h_i + q_i) − c_round,t, i.e. cost = turnover × per-side
cost, with a full entry plus a full exit = turnover 2.0 [VRF `costs.py`]. Per-trade figures on a fixed notional are
converted to portfolio returns with the declared capital and position count.

### 1.3 Cost tiers (conservative range)

| Liquidity tier (trailing 30-day median quote volume) | Half-spread h | Slippage q / side | Round trip base | Round trip stress | Class |
|---|---|---|---|---|---|
| A: BTC, ETH | 0.01 % | 0.05 % | 0.32 % | 0.44 % (h, q ×2) | [VRF S4 §4] (derived) |
| B: other top-20 | 0.04 % | 0.05 % | 0.38 % | 0.56 % | [VRF S4 §4] (derived) |
| C: rank 21–100 | 0.05–0.15 % | 0.10–0.30 % | 0.50–1.10 % | ×2 on h, q | [ASM] |
| D: below about 5M USDT/day | excluded from primary analyses | — | — | — | [ASM] (micro-cap positives did not survive [HR 2026-06-25]) |

The fee is never stressed downward. For orders above about 0.1 % of daily volume, add square-root impact
q = k × σ_daily × √(order / ADV) with k declared in the spec [ASM]; at 50 USDT this is negligible [ASM]. The tracker
label (flat 0.30 % round trip) is reported beside, never instead of, this model [VRF `shared/fees.py`, `costs.py`].
Every reported result carries ×1.5 and ×2 sensitivity on h and q, flagged "fragile" if the sign changes [PROP].

### 1.4 Three performance notions with distinct acceptance criteria [PROP]

| Notion | Question | Acceptance (all at the preregistered alpha) |
|---|---|---|
| **(a) Absolute net return** | Does it make money after costs? | mean net return per trade and per day > 0 with one-sided lower confidence bound > 0 (HAC Bartlett lag 7 on daily returns, or day-clustered per-trade), confirmed by a stationary bootstrap (mean block 20 d); total net over the window > 0; sign holds under ×1.5 and ×2 cost stress; removing the top 1 % of trades keeps the sign; ≤ 50 % of net P&L from 5 months or 1 coin |
| **(b) Risk-adjusted net return** | Is the return worth its risk, given how many variants were tried? | annualized net Sharpe with Probabilistic Sharpe vs 0 ≥ 1 − α **and** Deflated Sharpe ≥ 0.95 with N = every logged variant of the family (incl. abandoned ones) and the series' skew/kurtosis; Sortino, Calmar, max drawdown and its duration reported; max drawdown within the preregistered limit and not worse than the benchmark's unless the Sharpe gain is itself significant |
| **(c) Relative to buy-and-hold** | Does it beat simply holding? | daily active net return a_t = R_t − B_t > 0 with HAC lower bound > 0, vs (i) BTC B&H and (ii) the equal-weight B&H of the same point-in-time universe, same period; **benchmark costs** at the same tier model on the benchmark's own turnover (BTC: one entry and one exit; EW: monthly rebalance turnover); Romano–Wolf over hypotheses × benchmarks (Holm as check); information ratio and beta to BTC reported |

Interpretation rules [ASM]: (a) without (c) in a rising window is market beta, not edge. (b) without (a) is
impossible by construction. A long/cash strategy may legitimately aim at (b) relative to B&H (lower drawdown at
similar return) without (c); the preregistration must name **one primary notion**; the others are secondary and
reported, never claimed.

---

## 2. What has been demonstrated about net profitability

**Summary [ASM, from HR rows below]:** for every **tested implementation** in the record, net profitability under the
canonical cost model was **not demonstrated**; for the legacy 15m/4h/1d indicator family, gross results were negative
in three independent routes, so net is negative under any non-negative cost. This is a failure to demonstrate for
those implementations, parameter spaces and windows; it is **not** proof that no profitable strategy exists (§2.5).
The current strategy version's performance is unknown by design (sealed). Engineering correctness is well
demonstrated and is not evidence of an edge.

### 2.1 Gross vs net by evidence stream (pre-freeze, unsealed)

| Stream | Sample (as recorded) | Gross | Net | Kind | Power / limits | Class |
|---|---|---|---|---|---|---|
| Pre-freeze live Paper, all versions | 3,401 trades, 2026-04 → 08-19 | PF 0.729 | PF 0.593 at tracker cost; net WR 31.3 % vs break-even 43.5 %; day-clustered net t = −2.69 | forward Paper, mixed versions | large n; version mix; cost ≈ 10.8 % of absolute gross, so losses are mostly gross geometry/entry | [HR A58] |
| Live DB audit | 2,518 trades, 93 % in April 2026 | PF 0.735 | net PF 0.598, −0.365 USDT/trade at 0.3 % | forward Paper | one regime-month dominates | [HR 2026-06-23; also VRF as quoted in S4 §1] |
| Per-indicator analysis | 2,461 trades | PF 0.734; AUC 0.487–0.511; score inverted | negative | forward Paper | tests linear/threshold use of 15m/4h indicators only | [HR 2026-06-07] |
| 3-year replay of indicators | 287 symbols, 2023–2025 | PF ≈ 0.75–0.79, stable yearly | 0/43 configs net PF > 1 at 0.6 % | historical, research-exposed | cost harsher than canonical; tested configs only | [HR 2026-06-07] |
| 9-year target-policy replay | 301 symbols, 2017–2026 | PF 0.806; every arm × year negative | negative | historical, research-exposed | optimistic intrabar fills; exit-geometry variants of one entry family | [HR 2026-06-24] |
| Live-learning cohort | 479 trades, 2026-06/07 | about break-even gross after measurement correction | negative at every fee level | forward Paper | measurement-defective (clones, stop-fill asymmetry) | [HR 2026-07-14] |
| Reversion sub-cohort | in-sample n = 88 (n.s.); OOS n = 96 | — | OOS significantly negative | forward Paper | small n; post-hoc split | [HR canary close/OOS re-audit] |
| Current strategy (post-freeze) | sealed | not accessible | not accessible | sealed FORWARD_HOLDOUT | not assessed by design | [VRF holdout status SEALED] |

### 2.2 Exploratory positives that did not survive

| Thread | What looked positive | Why not demonstrated (scope) | Class |
|---|---|---|---|
| Daily ML (XGBoost, 595 symbols) | positive net in 6 walk-forward years at 0.6 % | only in < 1M USDT micro-caps; concentrated in 6 months; decaying; liquid tiers negative in 2026 | [HR 2026-06-25] |
| Faithful LuxAlgo SMC, daily CHoCH-in-discount | gross PF 1.06, n ≈ 3,157 | net CI crosses 0; liquid tier negative; 2026 negative | [HR 2026-07-06] |
| SMC demand-zone, tight stop / far target | large-n positive net | fat-tail dependent (top 5 % removal flips sign); decayed | [HR 2026-07-06] |
| Cross-sectional momentum L/S | strong OOS 2025 in a post-hoc grid | 94 % of P&L in the short leg (not executable on Spot) | [HR 2026-06-07] |
| Funding carry | gross funding mechanism real | failed all 4 preregistered thresholds after costs; needs derivatives | [HR 2026-07-29] |
| 20/50 MA uptrend | large headline mean | regime beta; as a gate it worsened live results | [HR 2026-08-12] |
| Stop policy STOP-A | significant paired advantage in isolation | reverses under the full risk-halt chain; n < 100 | [HR 2026-08-20] |

Most 2026-05..07 replays used 0.6 % round trip, about 1.6–1.9× the canonical tier A/B cost [VRF (derived) from §1.3
vs HR]. Lower costs cannot turn the tested gross-negative family net-positive (arithmetic), but the two daily threads above were judged under a harsher cost
than canonical; any re-qualification is exploratory only and logged as variants (R15) [ASM].

### 2.3 Engineering correctness (demonstrated, not an edge)

Tracker parity 27/27 [VRF A48]; cost ledger reconciles the 0.30 % label [HR A48]; economic net labels with
non-finite refusal [VRF `shared/fees.py`]; signal integrity and T1 correction built behind default-off flags [VRF
`shared/config.py`]; about 1,200+ default tests green at recent merges [HR].

### 2.4 Power of the negative evidence

- **Strong for large effects in what was tested [ASM]:** gross PF ≈ 0.73–0.81 replicated across live Paper and two
  replays on different data; a hidden net edge in **those** configurations would need an implausibly large
  measurement error.
- **Weak for small effects [VRF S4 App. A3; HR A17]:** 365 days of daily data gives an annualized-Sharpe MDE of
  about 3.5 (governed, LRV 1) or 3.0 (exploratory); realistic edges (SR ≈ 0.5–1.5) are below what any single
  window in the record could detect.
- **Not deflatable [HR A19]:** the legacy search (50 backtest parts, hourly optimizer, many audits) has no valid
  variant count, so historical positives cannot be credibly deflated and historical negatives are also not a
  calibrated test of every neighbour configuration.

### 2.5 What the evidence does NOT show

1. It does **not** show that no profitable Spot strategy exists, nor that technical or price-based information is
   useless in general. It shows that the specific implementations, parameter grids, horizons, universes and windows
   in §2.1–2.2 did not demonstrate net profitability [VRF principle 5, `DEVELOPMENT_FIRST_POLICY.md`].
2. It does **not** test daily/weekly trend or allocation strategies with literature-fixed parameters (W1–W3) under the
   canonical cost model; those have no internal evidence either way [ASM].
3. It does **not** cover maker/limit execution, size-dependent costs, non-price information (order flow, on-chain,
   listings), other venues, or short exposure [ASM].
4. It does **not** exclude small edges (SR well below 2): the record lacks the power to detect them (§2.4).
5. It does **not** say anything about the post-freeze strategy version (sealed) [VRF].
6. Measurement defects (pseudo-replication, stop-fill asymmetry) inflated recorded loss magnitudes in some streams
   [HR 2026-07-14]; magnitudes are uncertain even where signs replicate.
7. It does **not** show that the legacy family is worthless as a **baseline arm** or as infrastructure test load.

---

## 3. Directions by status (scoped to tested implementations)

### 3.1 Not supported as tested — no further profitability allocation recommended for these implementations

| # | Direction (as tested) | Evidence | Confidence in the verdict for this implementation | Class |
|---|---|---|---|---|
| F1 | 15m/4h/1h indicator scoring (RSI, Bollinger, Stoch-RSI, divergence, Fibonacci, order book) | AUC ≈ 0.50; gross PF ≈ 0.73 live, 0.77–0.81 replays | High | [HR] |
| F2 | Weight tuning, min-score thresholds of F1 | 48 weight sets flat; score inverted | High | [HR] |
| F3 | Exit geometry redesign of F1 (mean-anchored T1, 0.5R, wide R:R, partial TP) | every arm × year negative | High | [HR] |
| F4 | Momentum arm of the live learner (15m/4h) | significantly negative net, forward | High | [HR] |
| F5 | Momentum → reversion preference flip | refuted OOS | High | [HR] |
| F6 | SMC/ICT as ported (14 setups, demand → supply) | 0/14 significant net | High for these 14 | [HR] |
| F7 | Market structure + falling wedge | random-entry null not rejected | Low n, underpowered | [HR] |
| F8 | Volume + RSI MTF (owner strategy) | negative per trade | Medium-high | [HR] |
| F9 | ML on stored score details | purged AUC < 0.5 | High for these features | [HR] |
| F10 | Funding carry | failed preregistered thresholds | Medium-high (mechanism real) | [HR] |
| F11 | Pairs/cointegration | fee-fragile; needs shorting | Medium | [HR] |
| F12 | 20/50 MA uptrend as edge or gate | regime beta | Medium-high | [HR] |
| F13 | Learner as an edge source | separates very bad from bad, not from profitable | High | [HR] |

### 3.2 Inconclusive

| # | Direction | Why inconclusive | Class |
|---|---|---|---|
| I1 | Daily ML "accumulation at discount" | research-exposed; illiquid; decaying | [HR] |
| I2 | Daily CHoCH-in-discount | judged at 0.6 %; 2026 negative | [HR] |
| I3 | Cross-sectional momentum | short leg not executable on Spot | [HR] |
| I4 | Stoch > 0 gate, spread gate | loss reducers; not significant | [HR] |
| I5 | STOP-A | portfolio-level n < 100 | [HR] |
| I6 | Current strategy | sealed | [VRF] |

### 3.3 Warrant investigation (mechanism-first, low prior; exploratory before any claim)

| # | Direction | Mechanism / literature | Expected best case | Main risk | Class |
|---|---|---|---|---|---|
| W1 | Daily TSMOM long/cash, top-20, 14-day lookback, ± vol scaling | Liu–Tsyvinski 2021; Kim–Tse–Wald 2016 | notion (b) vs B&H: timed beta, lower drawdown | Huang et al. 2020; crashes | [VRF S4 §2–§4] / expectation [ASM] |
| W2 | XS momentum long-only top-5 weekly | relative under-reaction | small tilt over EW B&H | turnover cost | [VRF S4] / [ASM] |
| W3 | Volatility-managed exposure overlay | Moreira–Muir; Cederburg 2020 contra | notion (b): variance/drawdown | real-time failure | [VRF S4] / [ASM] |
| W4 | BTC-beta exposure cap | common BTC factor | risk reduction | none economic | [HR A42] |
| W5 | Execution-cost reduction (`resting_limit_v1`, cost gate, spread gate) | spread capture | lower drag; no gross edge | adverse selection; non-fill bias | [VRF config] / [ASM] |
| W6 | Re-qualification of I1/I2 under canonical cost | daily horizon amortizes cost | probably still decayed | forking paths | [ASM] |
| W7 | Funding/crowding veto on longs | crowded longs mean-revert | small, episodic | data licence | [HR A42] |
| W8 | Non-price information (listings, on-chain, order-flow) | new information | unknown | data, licence, capacity | [HR] |

Further 15m/4h refinements (H2 cap, G3 offset, ranking v2) are second-order gates on an entry with no demonstrated
gross edge; documented effects sit at or below the prospective MDE [HR A45; VRF `S5_PWR_1_OWNER_DECISIONS.md`].
Recommendation: keep that family as the **baseline arm** only [PROP].

---

## 4. Obstacles to credible evidence of an edge

| # | Obstacle | Evidence | Consequence | Class |
|---|---|---|---|---|
| O1 | Cost wall at short horizons | min T1 0.275 % at 0.30 % round trip; 15m fee burden 0.22–0.43 R | short-horizon entries need large gross edge | [VRF A46] / [HR A42] |
| O2 | T1-capture geometry | T1-only path needs 81–96 % hits | ladder incoherent at small R | [HR A46/A45] |
| O3 | No measurable information in the tested entries | AUC ≈ 0.50 | geometry/selection cannot amplify a signal indistinguishable from zero **in those entries** | [HR] |
| O4 | Power / MDE | SR MDE ≈ 3.5 at 365 d, 1.76 at 4 y, 1.25 at 8 y (governed, LRV 1) | one-year confirmation infeasible for realistic SR | [VRF S4 A3] |
| O5 | Multiple testing, adaptive search | no valid N for legacy search | historical significance not deflatable | [HR A19] |
| O6 | Holdout scarcity | pre-freeze history research-exposed; FORWARD_HOLDOUT sealed | history can qualify or falsify, not confirm | [VRF registry] / [HR A18] |
| O7 | Data licence | Binance Vision terms; inquiry drafted, not sent | exploratory dataset use blocked | [HR A18/A22] |
| O8 | Regime non-stationarity, decay | positives decayed 2025–2026 | per-year and remove-top-N robustness required | [HR] |
| O9 | Execution realism | Paper fills at observed price; no queue/partials | small effects inside model error | [VRF config `observed_price_v0`] / [HR A47] |
| O10 | Measurement defects | clones, same-candle re-fires; fixed only under `enforce` (off) | Paper n overstated | [VRF config] / [HR A43] |
| O11 | Spot long-only | literature factors mostly L/S | opportunity set ≈ beta + timing | [ASM] |
| O12 | Cross-asset dependence | large common BTC component | effective n ≪ trade count | [HR A45] |

Binding pair [ASM]: O3 for the tested entries (needs a different mechanism, not more engineering) and O4 (needs a
multi-year design, OD-DF-2). Sample-size rule for per-trade endpoints [ASM, standard normal approximation]:
N ≈ DEFF × ((z_α + z_power) × σ/μ)²; at α = 0.05, power 0.8, σ/μ = 10, DEFF 2 this is about 1,240 trades; at the
ladder's α = 1/240 roughly double. Illustrative, not a protocol.

---

## 5. Holdout integrity and multiple-testing controls (binding on every item below) [PROP]

1. **No item reads sealed or forward-holdout periods.** FORWARD_HOLDOUT (after the 2026-08-19 freeze instant;
   status `SEALED` [VRF]) is not read, queried, summarized or used for tuning, selection or "sanity checks" by any
   initiative. All exploratory work ends strictly before the freeze instant [VRF S4 §4 data rule].
2. **Prospective data is a separate, owner-defined partition.** Any forward shadow necessarily consumes post-freeze
   market data. Before it starts, the owner records how its prospective window relates to FORWARD_HOLDOUT (e.g. a new
   prospective partition beginning at authorization, with the existing sealed interval untouched and its outcomes
   still unread). Without that record, no forward item starts.
3. **Exploratory never touches holdout and never spends confirmatory alpha.** Exploratory results can only admit a
   candidate to a preregistered prospective test; they are labelled EXPLORATORY and never reported as profitability.
4. **Variant / alpha ledger.** Every run appends dataset hash, config hash, git SHA, cost label and variant ID
   **before** results are read (R2); `validation_usage.jsonl` records one look per hypothesis [VRF file exists].
   - Exploratory family: family-wise α = 0.05 split across the family (S4 uses 0.05/3 for H1–H3), Romano–Wolf
     stepdown (Holm check), Deflated Sharpe with N = all logged variants including abandoned ones [VRF S4 §4, A5].
   - Governed admissions: fixed α = 1/240 per admission from a fixed program budget; one final look (or a
     preregistered group-sequential rule with non-binding futility); no re-use of a spent look [VRF
     `EVIDENCE_LADDER_PARAMETERS.md`; calibration level still unvalidated, DR-2].
5. **Exposure registry.** Any interval used for research is registered before use; the 2026-01 → 06 gap is closed
   first (R4) [VRF gap].

## 6. Prospective-research admission rule [PROP]

No prospective shadow or forward research item (R14 forward shadow, R16 integrity-window outcome analysis, R19
resting-limit research, R21 selection shadow, any lab Mode 2/3 run) may start until **both** are recorded:

- **Explicit scientific authorization** by the owner for that item; and
- **Preregistration** committed with hash: frozen spec (code SHA, universe, signal, sizing, cost model and tier
  table), hypotheses, primary notion (a/b/c) and secondary metrics, minimum sample size from a power calculation,
  stopping rule (final look or group-sequential with non-binding futility), the multiple-testing budget and alpha
  drawn from the ledger, the prospective-partition record (§5.2), and failure criteria.

Shadow trading is **paper/simulated only**: intents and simulated fills are recorded; no exchange order, signing key
or live path is created, consistent with PAPER_ONLY [VRF `PAPER_TRADING` default true]. Building shadow software and
testing it on synthetic data is development, not shadow trading, and does not start any window.

---

## 7. Ranking rubric and ranked initiatives

### 7.1 Rubric [PROP; all scores ASM]

Ranked by expected contribution to **credible profitability evidence**, not by engineering complexity.

- **IV — information value (1–5):** how much the item changes what can credibly be claimed about net profitability,
  including by making evidence admissible (a valid negative counts).
- **P — probability of success (1–5):** probability the item delivers its intended evidence or control, conditional
  on its listed dependencies. Success = credible evidence delivered, of either sign.
- **T — time-to-evidence (1–5):** 5 = within about 2 weeks after its gate; 3 = 1–3 months; 1 = more than a year.
- **C — engineering complexity (1–5):** cost term only.
- **Score = IV × P × T − C.**

Calendar note [ASM]: forward days cannot be recovered, which the score does not capture. The owner may choose to
authorize R14 early as an explicit override; it would still require §6 in full.

P0 safety/continuity items (§8.1) are an unranked precondition track. Pure platform/ops items (admission budget,
retention, CI, dashboard, docs) are unranked (§8.4).

### 7.2 Scores and order

| Rank | ID (old ID) | Initiative | IV | P | T | C | Score | Class |
|---|---|---|---|---|---|---|---|---|
| 1 | R1 (P1a-2) | Freeze W1/W2 preregistration (spec, variants, notion, costs, failure criteria) | 4 | 5 | 5 | 1 | 99 | [PROP] |
| 2 | R2 (P1b-2) | Variant/alpha ledger + DSR/PSR, Romano–Wolf utilities | 4 | 5 | 5 | 2 | 98 | [PROP] |
| 3 | R3 (P0-7) | Holdout-seal integrity check (status, look count, no post-freeze mounts) | 3 | 5 | 5 | 1 | 74 | [PROP] |
| 4 | R4 (P1b-3) | Close the 2026-01 → 06 exposure-registry gap | 3 | 5 | 5 | 1 | 74 | [PROP] |
| 5 | R5 (P1b-1) | Validation design for realistic effects (OD-DF-2) incl. §5–§6 rules | 4 | 4 | 4 | 2 | 62 | [PROP] |
| 6 | R6 (P1b-5) | Mandatory admissibility/power screen per candidate (`research/power`) | 3 | 5 | 4 | 1 | 59 | [PROP] |
| 7 | R7 (P1b-7 + E13) | Evidence-class and cost-label enforcement in every report | 2 | 5 | 5 | 1 | 49 | [PROP] |
| 8 | R8 (P1a-3) | One exploratory qualification run per frozen spec (W1, W2) | 4 | 4 | 3 | 3 | 45 | [PROP] |
| 9 | R9 (P1a-1) | Licence inquiry + `DatasetPermission` + certified pre-freeze dataset | 5 | 3 | 3 | 2 | 43 | [PROP] |
| 10 | R10 (P1a-5) | Cost-model calibration (measured tiers, ×1.5/×2 sensitivity) | 3 | 4 | 3 | 2 | 34 | [PROP] |
| 11 | R11 (P1b-4) | Independent critical-value validation (minimal scope) | 3 | 4 | 3 | 3 | 33 | [PROP] |
| 12 | R12 (P2-3) | Streaming research loader | 2 | 4 | 4 | 3 | 29 | [PROP] |
| 13 | R13 (P2-4) | Content-addressed results registry | 2 | 4 | 3 | 2 | 22 | [PROP] |
| 14 | R14 (P1a-4) | Forward **paper** shadow of frozen specs | 5 | 4 | 1 | 3 | 17 | [PROP] |
| 15 | R15 (W6) | Re-qualification of I1/I2 under canonical cost (exploratory) | 2 | 3 | 3 | 2 | 16 | [PROP] |
| 16 | R16 (P1a-7) | Paper baseline integrity-enforce window | 2 | 4 | 2 | 2 | 14 | [PROP] |
| 17 | R17 (P2-1) | Lab engine (`LAB_MODE`, accounts, `tsb_lab`; #67, #78) | 3 | 3 | 2 | 5 | 13 | [PROP] |
| 18 | R18 (P1a-10) | Risk overlays W3/W4 as lab modules | 2 | 3 | 2 | 2 | 10 | [PROP] |
| 19 | R19 (P1a-6) | Resting-limit execution research | 2 | 3 | 2 | 3 | 9 | [PROP] |
| 20 | R20 (P1a-8) | T1-cap correction version | 1 | 4 | 2 | 1 | 7 | [PROP] |
| 21 | R21 (P1a-9) | S3 selection shadow | 1 | 3 | 2 | 2 | 4 | [PROP] |

Rank sets priority; execution order still respects dependencies (e.g. R8 needs R9, R1, R2, R12) [ASM].
The former P1a-11 ("retire the 15m/4h family") is a resource decision, not an evidence item; it moves to RD-6.

---

## 8. Roadmap (reordered by rank)

"D0" = safe development under the Development-First policy (code, tests, synthetic data, docs, Draft PRs) — **only
if the owner merges `DEVELOPMENT_FIRST_POLICY.md`** [VRF: still Draft]; until then existing records govern.

### 8.1 Precondition track P0 — safety and continuity (unranked; runs in parallel)

| ID | Initiative | Acceptance | Gate | Class |
|---|---|---|---|---|
| P0-1 | Repair nightly bot backup; off-host encrypted copy | 7 consecutive successful nightly runs; restore drill PASS | owner (Class B; off-host) | [PROP]; failing since 2026-10-10 [HR] |
| P0-2 | Pipeline-liveness monitor (#87) | alert within 2 scanner cycles in synthetic test; 0 false alerts over 7 days | owner | [PROP]; Draft [VRF] |
| P0-3 | Technical-halt recovery (#89) + audit log (#88) | tests cover technical-halt class; risk controls byte-identical | owner | [PROP]; Draft [VRF] |
| P0-4 | Least-privilege roles (#36) + credential rotation plan | role suites pass on schema-11 test DB; runbook reviewed | owner (after P0-1) | [PROP]; Draft [VRF] |
| P0-5 | PAPER_ONLY invariant tests + branch protection (#90) | CI fails on any live path or `PAPER_TRADING` default change | owner | [PROP]; Draft [VRF] |
| P0-6 | Dependency locks (#86) | lock per service; differences listed | owner | [PROP]; Draft [VRF] |

### 8.2 Tier A — ranks 1–8 (highest evidence contribution)

All rows **[PROP]**.

| Rank | ID | Contribution | Dependencies | Acceptance criteria | Gate | Notion |
|---|---|---|---|---|---|---|
| 1 | R1 | immutable spec before any data | none to draft | spec hash committed; all variants enumerated; primary notion named; costs per §1.3; S4 failure criteria fixed | **owner accepts preregistration** | names one of (a)/(b)/(c) |
| 2 | R2 | honest deflation; look accounting | none (D0) | 0 orphan runs in an audit of runs vs ledger; DSR/PSR/Romano–Wolf reproduce published examples in tests | D0; owner makes mandatory | (b) via DSR |
| 3 | R3 | protects untouched evidence | none (D0) | automated check: status SEALED, look count unchanged, no research/lab mount of post-freeze paths | D0 build; owner install | — |
| 4 | R4 | correct exposure class for 2026-01 → 06 | none | registry entry with source records | owner (governance record) | — |
| 5 | R5 | makes confirmation possible in principle | R2 | horizon, fixed alpha, look rule, endpoint per notion, prospective-partition rule, power ≥ 0.8 table at the declared effect range | **owner** | all three, per §1.4 |
| 6 | R6 | stops alpha spent on underpowered tests | R5 | screen attached to every admission request; underpowered → not admitted | D0; owner decides | — |
| 7 | R7 | prevents exploratory or gross figures read as net profitability | none (D0) | generator refuses output without class label and cost label; tests | D0 | — |
| 8 | R8 | first credible exploratory read on W1/W2 | R9, R1, R2, R12, R4 | exactly one run per spec; all variants logged; ends before the freeze instant; PM-1 evaluated | **owner (dataset use)**; never confirmatory | (c) primary, (a)(b) reported |

### 8.3 Tier B/C — ranks 9–21

All rows **[PROP]**; contributions as in §7.2.

| Rank | ID | Dependencies | Acceptance criteria | Gate | Notion |
|---|---|---|---|---|---|
| 9 | R9 | owner sends LIC-1 | `DatasetPermission` recorded; content-addressed snapshot ending before the freeze; PIT universe incl. delisted | **owner** | — |
| 10 | R10 | source decision (public snapshots vs collector data) | measured tiers on ≥ 30 days; sensitivity on every result | owner ruling if collector data | (a) cost input |
| 11 | R11 | R5 | test size within declared tolerance under AR(0.3) and skewed returns, independent harness, one immutable run | owner (compute) | — |
| 12 | R12 | none (D0) | peak RSS ≤ 4 GiB on a synthetic 9-year, 600-symbol table; byte-identical to in-memory path on fixtures | D0 | — |
| 13 | R13 | R2 | rerun with same inputs gives byte-identical artifacts | D0 | — |
| 14 | R14 | R1, R5, §6 in full, minimal shadow logger or lab Mode 2 | intents logged daily with decision-time inputs, hash-chained; ≥ 99 % daily completeness; paper/simulated only | **owner: scientific authorization + preregistration + partition record** | per R1 |
| 15 | R15 | R9, R2 | runs logged as variants; labelled EXPLORATORY; liquid tiers only | owner (dataset use) | (a)(c) |
| 16 | R16 | A44 image validation; fresh recovery point | re-fire and duplicate execution rate 0 (non-outcome counters); any outcome analysis requires §6 | owner (declared Paper window) | — |
| 17 | R17 | architecture review | production outputs byte-identical with `LAB_MODE` unset; isolation tests pass | owner (merge, DB, deploy separate) | — |
| 18 | R18 | R17 | variance / drawdown endpoint spec frozen; synthetic tests | D0 build; owner activation | (b) |
| 19 | R19 | R14 or Paper shadow under §6 | non-fill rate and post-fill drift per tier with CIs | owner + §6 | (a) cost |
| 20 | R20 | R16 boundary | flag switch recorded as a version boundary | owner | — |
| 21 | R21 | sidecar approval + §6 | shadow selection decisions recorded ≥ 30 days; no P&L | owner + §6 | — |

### 8.4 Unranked platform and ops

Admission budget shadow mode (#85; I-1 #80 merged [VRF]) — owner install; evidence/outbox retention (DB-5); CI
hardening (DB suite in CI; #81 flake fix merged [VRF]; target 20 consecutive green runs); Telegram dashboard (A59,
read-only role, no holdout data); documentation consolidation; runtime ↔ GitHub parity (#56). Collector: minimal
upkeep until a research use is declared [PROP].

---

## 9. Measurable milestones

### 9.1 Profitability milestones (each requires the previous ones)

| ID | Milestone | Notion tested | Measurable criterion | Class |
|---|---|---|---|---|
| PM-0 | Spec frozen | none | R1 hash committed before any data access; variants enumerated; primary notion named | governance |
| PM-1 | Exploratory qualification pass | **(c) primary**; (a), (b) secondary | on the licence-cleared pre-freeze dataset: active net return vs EW B&H > 0 with HAC t ≥ 2 (lag 7) and bootstrap 95 % CI excluding 0; DSR ≥ 0.95 with N = all logged variants; (a) mean net > 0 under ×2 cost stress; none of the five S4 failure criteria triggered | **exploratory** — never confirmation |
| PM-2 | Prospective authorization | none | owner scientific authorization + preregistration hash + prospective-partition record (§5–§6) | governance |
| PM-3 | Forward sample sufficiency | none | preregistered forward sample reaches its precomputed N or horizon (R5 power table) | prospective observation |
| PM-4a | Forward absolute net | **(a)** | §1.4(a) at the preregistered alpha on the forward sample | prospective |
| PM-4b | Forward risk-adjusted | **(b)** | §1.4(b): PSR ≥ 1 − α, DSR ≥ 0.95 with full variant count; drawdown within limit | prospective |
| PM-4c | Forward vs buy-and-hold | **(c)** | §1.4(c) vs BTC and EW B&H, benchmark costs included, Romano–Wolf | prospective |
| PM-5 | Scientific success | the preregistered primary notion only | the governed admission ends supported at the final look; secondary notions reported, not claimed | **confirmatory** |
| PM-6 | Financial profitability | — | not a roadmap milestone; needs the four owner conditions, licence clearance and an explicit owner decision | **out of scope (PAPER_ONLY)** |

### 9.2 Evidence-quality milestones

All rows **[PROP]**.

| ID | Criterion |
|---|---|
| EQ-1 | ≥ 1 `DatasetPermission` with licence basis; snapshot verify PASS |
| EQ-2 | Registry covers every researched interval; 2026-01 → 06 gap closed |
| EQ-3 | 100 % of research runs in the ledger before results are read (0 orphans) |
| EQ-4 | 100 % of reports carry class and cost labels |
| EQ-5 | Measured cost tiers; ×1.5/×2 sensitivity and "fragile" flag on every result |
| EQ-6 | Tracker parity 27/27 on every replay change |
| EQ-7 | Under integrity enforce: same-candle re-fires = 0, duplicate executions = 0 |
| EQ-8 | Independent size check within tolerance at the declared alpha |
| EQ-9 | Seal status and look count unchanged at every milestone review |

### 9.3 Reliability milestones

RM-1 backups (7 consecutive nightly, off-host copy, restore drill ≤ 30 days old); RM-2 liveness (≤ 2 cycles in
synthetic test; 0 undetected idle periods > 1 hour over 30 days); RM-3 0 lost signals; RM-4 no superuser service
role, 0 credential literals at HEAD; RM-5 technical halts recoverable with recorded actor; RM-6 20 consecutive green
CI runs; RM-7 collector daily seals complete, reboot recovery documented [all PROP].

---

## 10. Resource allocation [ASM estimate / PROP]

| Area | Estimated 2026-08-19 → 10-24 [ASM] | Proposed next 4–6 weeks [PROP] | Steady state [PROP] |
|---|---|---|---|
| Evidence controls + validation design (R1–R7, R11) | 30–35 % (mostly A17–A34 statistics) | 30 % | 20 % |
| Profitability research (R8–R10, R14–R15, R18–R19) | 10–15 % | 25 % | 40 % |
| Operational reliability (P0) | 35–40 % | 30 % (front-loaded) | 15 % |
| Platform (R12–R13, R17, §8.4) | 15–20 % | 15 % | 25 % |

Pause further development of the confirmatory-statistics line (A34-VS1) until a candidate passes PM-1, using the
simple stack in §5.4 meanwhile [PROP].

## 11. Safe work that can start now (D0; no data, no window, no authorization)

1. Draft R1 preregistration files from S4 §4 — **for owner acceptance; not frozen until accepted**.
2. R2 ledger, DSR/PSR, Romano–Wolf utilities with synthetic tests.
3. R3 seal check code; R7 label enforcement; R12 loader; R13 registry.
4. R5 OD-DF-2 draft with `research/power` tables (outcome-free).
5. Shadow-logger and lab pure-module code with **synthetic** tests only — this starts **no** shadow window (§6).
6. Cost-calibration code on synthetic book data (R10 code only).
7. Review fixes on Drafts #36, #67, #78, #85–#90.

Not D0: any DB read, dataset use, Paper flag or window, shadow window, merge, host install, collector action or use
of post-freeze data.

## 12. Owner decisions needed (recommended order)

| # | Decision | Unblocks | Recommendation [PROP] |
|---|---|---|---|
| RD-1 | Merge or amend `DEVELOPMENT_FIRST_POLICY.md` | §11 at full speed | merge, with amendments as desired |
| RD-2 | Accept (or amend) R1 preregistration | R8, R14 | accept before any data is touched |
| RD-3 | Make the R2 ledger and R6 screen mandatory | all research | yes |
| RD-4 | Validation design OD-DF-2 incl. prospective-partition rule (R5) | R11, R14, PM-2 | multi-year, fixed alpha, final look or non-binding futility |
| RD-5 | Send LIC-1; decide dataset permission (OD-DF-1) | R8, R9, R15 | send now |
| RD-6 | Stop profitability allocation to further 15m/4h refinements; keep as baseline arm | frees capacity | yes — scoped to those implementations, reversible on new evidence |
| RD-7 | Scientific authorization for R14 (only after RD-2, RD-4 and §6 are complete) | forward clock | decide explicitly; early authorization is an override of the rank order (§7.1) |
| RD-8 | Backup model and off-host copy | P0-1 | approve |
| RD-9 | Least-privilege rollout and rotation plan | P0-4 | approve; schedule after P0-1 |
| RD-10 | Paper baseline integrity window and T1 correction version | R16, R20 | owner's call |
| RD-11 | Collector purpose (upkeep vs declared research use) | R10 source | minimal upkeep unless declared |
| RD-12 | Lab architecture approval and `tsb_lab` creation | R17 | after isolation tests |
| RD-13 | Resource allocation (§10) | all | adopt for 4–6 weeks, then review |

## 13. Scientific authorization gate

This document does **not**: authorize any dataset use, backtest, simulation, research job or confirmatory
experiment; freeze any preregistration; declare any Paper or shadow window; admit any candidate; change any HOLD
(A34-VS1, MI Stage B, B2, P2-D1, Paper R2, D1–D5) or owner decision OD-1..OD-7; read, quote or rely on any
sealed-holdout outcome; or propose, enable or prepare live trading.

## Appendix A. Sources

Repository, checked in this revision [VRF]: the files listed in §0. Repository documents cited but **not**
re-checked line by line in this revision (treated as [HR] where quoted): `docs/a42/`–`docs/a47/` beyond the A46
line cited, `docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md`, `S4_MECHANISM_COMPARISON.md`, lab §11 isolation tests.

Owner memory notes (historical record, not re-verified): edge leaderboard; research conclusion 2026-05-25; indicator
deep analysis 2026-06-07; live-DB audit 2026-06-23; T1-capture audit and 9-year replay 2026-06-24; ML daily edge
2026-06-25; falling wedge 2026-06-28; SMC faithful test and live-learning review 2026-07-06; canary close and OOS
re-audit; learning audit 2026-07-14 (with 07-29 and 08-12 updates); stop-policy validation 2026-08-20; A17–A34;
A37–A49; A58; post-A56 critical path; ops assessment 2026-10-22.

## Changelog (revision 2, owner corrections)

| # | Correction | Where addressed |
|---|---|---|
| 1 | Failure to demonstrate for tested implementations ≠ proof no profitable strategy exists; reworded "no edge", "dead", "do not reinvest"; power and limits; "does NOT show" | §2 summary, §2.4, **§2.5**, §3.1 heading and confidence column, §3.3 note, §4 O3, RD-6 |
| 2 | Four evidence classes [HR]/[VRF]/[ASM]/[PROP] on every row; key repository facts re-verified with paths | §0 (label table + verified-facts table), class columns throughout, Appendix A |
| 3 | Precise net-profitability definition with formula, fees 0.10 %/side, spread, slippage tiers, rounding, partial/failed fills, n/a items | **§1.1–§1.3** |
| 4 | Three notions (absolute, risk-adjusted, relative to B&H) with distinct acceptance criteria; milestones name their notion | **§1.4**, §9.1 (PM-1, PM-4a/b/c, PM-5), notion column in §8.2–§8.3 |
| 5 | Every prospective shadow/forward item needs scientific authorization + preregistration; shadow paper/simulated only | **§6**, R14/R16/R19/R21 gates, PM-2, RD-7, §11 item 5 |
| 6 | Sealed holdout integrity and multiple-testing controls explicit (no holdout reads; prospective partition; ledger; DSR; family-wise and per-admission alpha) | **§5**, R2–R4, EQ-3, EQ-9 |
| 7 | Re-ranked by contribution to credible profitability evidence with an explicit rubric and score table; roadmap reordered | **§7**, §8.2–§8.3 |
