# Strategy-improvement hypothesis register (Workstreams B/C)

**Status: DESIGN DOCUMENT (D0).** Written 2026-10-26 on `research/variant-ledger` (PR #94) after merging `origin/main`
(owner governance commits of 2026-10-26). It proposes falsifiable hypotheses and how each would be tested. It runs no
analysis, backtest or simulation, reads no database or research-data directory, registers **no** variant in the R2
ledger, writes nothing to `research/governance/hypotheses.jsonl` (still empty), spends no alpha and declares no Paper,
shadow or prospective window. **No runtime effect. No runtime claim.**

**No measured result exists for any hypothesis below. Every row reads "Measured result: NONE YET".**

## 0. Governance in force and sources

| Rule | Source |
|---|---|
| R&D / `PAPER_ONLY`; live money forbidden; `PAPER_TRADING=true` | `docs/governance/OWNER_OPERATING_CONTRACT.md` §1, §5 |
| Fees **0.10 % per side (0.20 % round trip)**, no BNB/VIP discount; spread and slippage modelled **separately**; tracker 0.30 % flat reported beside, never instead | contract §1; `research/mechanisms/costs.py` (via roadmap §1.3) |
| A29 Evidence Ladder in force; **D1/D2 HOLD** for governed confirmation; ≤ 365-day prospective horizon; ≤ 3 simultaneous candidates; 20 % forward capacity reserve; FWER 5 % (α = 1/240 per admission, 12 admissions); ENCOURAGING is non-confirmatory | contract §4; `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md`; memory `project_a29_architecture_2026_10_13.md` |
| FORWARD_HOLDOUT (after the 2026-08-19 freeze instant) **SEALED**; no outcome, count or timestamp reads | `DEVELOPMENT_FIRST_POLICY.md` §3; `research/governance/holdout_status.json` |
| D1 exploratory real-data work only on a dataset with a recorded `DatasetPermission`; **none exists today** (licence HOLD, OD-DF-1 proposed) | `DEVELOPMENT_FIRST_POLICY.md` §2, §7 |
| Negative results are evidence against the **tested implementations**, not proof that every alternative fails | policy §1 principle 5 |
| Ledger: only `SYNTHETIC` evidence registers without an owner `authorization_ref`; DSR uses N = every registered variant of a family, abandoned ones included | `docs/strategy/VARIANT_LEDGER.md`; `research/stats/variant_ledger.py` |

Sources read: the files above; `docs/a42/`–`docs/a48/`; `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md`,
`S5_PWR_1_OWNER_DECISIONS.md`, `STRATEGY_EVOLUTION_ROADMAP.md`; the profitability roadmap
`origin/docs/profitability-roadmap-20261024:docs/strategy/PROFITABILITY_ROADMAP_2026-10-24.md` (PR #91, **Draft, not
merged**); owner memory notes (historical record, **not re-verified**): A29, A45, A58, stop-policy validation
2026-08-20, T1-capture audit and 9-year target-policy replay 2026-06-24, ML daily edge 2026-06-25, SMC faithful test
and live-learning review 2026-07-06, canary close / OOS re-audit, learning audit 2026-07-14, indicator deep analysis
2026-06-07, A17.

**Evidence labels** (as in the roadmap): **[HR]** historical record (memory notes / older audits, not re-verified);
**[VRF]** repository fact checked in this worktree (path named); **[ASM]** assumption or judgement of this register.

## 1. Test stages, gates and families

| Stage | What | Gate | Ledger class |
|---|---|---|---|
| **S — synthetic engineering** | pure versioned module + tests on generated data: rule parity, no look-ahead, cost ledger, determinism, power simulation. Proves engineering only | **none** (D0, allowed now) | `SYNTHETIC` |
| **X — exploratory** | one logged look per variant on a licensed, permission-recorded dataset ending **before** the 2026-08-19 freeze instant; every variant registered before its result is read; family α = 0.05 split over the family; Romano–Wolf (Holm check); DSR with full N. Result label EXPLORATORY; can only nominate a candidate | **G-DATA**: owner `DatasetPermission` (OD-DF-1) + `authorization_ref` for non-synthetic ledger entries | non-synthetic, with `authorization_ref` |
| **C — preregistered confirmatory** | prospective paper/simulated observation on an owner-defined partition (never FORWARD_HOLDOUT), frozen spec hash, power table, final look (or preregistered group-sequential with non-binding futility), α = 1/240 from the program budget | **G-SCI**: scientific authorization + committed preregistration + prospective-partition record + alpha slot; requires the **D1/D2 HOLD** to be lifted by the owner | governed admission |

**G-OPS** (operational approval) is additionally required wherever a stage needs a Paper strategy version, a forward
observation capture or any deployment (contract §2, §4).

**Families** (ledger `family` identifiers; DSR deflates every variant against its family's N, abandoned ones included):

| Family id | Members | Note |
|---|---|---|
| `fam.s4-direction` | HR-04, HR-13 (+ existing S4 H2 XS, H3 baseline) | S4 exploratory budget 0.05/3; HR-13 is a registered variant of H1, no extra alpha share unless the owner enlarges the family |
| `fam.breakout-gates` | HR-03, HR-07 (+ A45 H2/H3, A42 C1 if ever run) | gates on the legacy 15m/4h breakout stream |
| `fam.geometry` | HR-05, HR-06 (+ A46 G1/G2) | at most one admission (A46-E) |
| `fam.new-information` | HR-01 | new data contract |
| `fam.daily-reversal` | HR-02 | must also register the documented historical trials as abandoned variants (§2, HR-02) |
| `fam.risk-overlay` | HR-08, HR-09 | risk endpoints (notion b); HR-09 is a risk-control validation, not an alpha claim |
| `fam.stop-policy` | HR-10, HR-11 | trade-level stops only |
| `fam.execution-cost` | HR-12 | |
| `fam.universe` | HR-14 | stratification applied to whichever candidate is tested |

**Primary metric convention.** Net expectancy after full costs: per trade r_net = (P_sell/P_buy)(1 − f)² − 1 with
f = 0.001, P including half-spread and slippage by liquidity tier (A: 0.01 % / 0.05 %; B: 0.04 % / 0.05 %; C: declared
in spec; stress ×1.5 and ×2 on spread and slippage, never on the fee) [VRF roadmap §1.3 / S4 §4]. Portfolio
strategies use mean daily net return (HAC Bartlett lag 7, stationary bootstrap). Secondary: PSR/DSR (risk-adjusted),
active net return vs BTC and equal-weight B&H where the strategy can hold the market, max drawdown, turnover, cost
drag, share of P&L from top-5 months / top coin. Gross results are reported, never claimed.

**Power reference** [VRF S4 App. A3 via roadmap §2.4, §4; HR A45-F, A42-E]: daily annualized Sharpe MDE ≈ 3.5 at
365 days, 1.76 at 4 years, 1.25 at 8 years (governed); S4 power for true SR 1.0 is ≈ 0.76 over 8 years and ≈ 0.13
over 1 year. Per-trade: N ≈ DEFF × ((z_α + z_β) σ/μ)² (≈ 1,240 trades at α 0.05, power 0.8, σ/μ 10, DEFF 2; about
double at α 1/240). A45 H2 iid MDE ≈ 0.12 %/setup, 0.2–0.4 % with day clustering; A42 C1 ≈ 0.13 %/trade iid × 2–3.

**Measurement preconditions (not hypotheses).** Any stage-C test on the Paper stream first needs: A43/A44 integrity
`enforce` (same-candle re-fires and duplicate executions = 0) [HR A43 D1–D3]; A48 replay mode with conservative stop
fills (legacy replay is optimistic on stops) [VRF `docs/a48/A48_REPLAY_FIDELITY.md`]; counterfactual outcomes for
non-selected candidates (forward capture, G-OPS). Measured result: NONE YET.

## 2. Hypotheses

### Area 1 — Signal quality / false-entry reduction

**HR-01 — Funding-crowding veto on momentum longs** (crosswalk: A42 C3, roadmap W7)

| Field | Content |
|---|---|
| Statement | Momentum long entries taken while the symbol's last **settled** USDⓈ-M perpetual funding rate is ≥ 0.03 %/8 h have lower mean net return than those taken below it; vetoing them raises net expectancy per trade and does not lower total net P&L per day. Falsified if the vetoed subset's net mean ≥ the kept subset's |
| Mechanism | crowded leveraged longs → long-squeeze risk for spot breakouts; information not contained in price indicators |
| Prior evidence | none internal [HR A42-E]. Price-only TA exhausted (AUC ≈ 0.50) [HR 2026-06-07]. Funding carry *mechanism* real but its trading test failed thresholds after costs [HR roadmap F10] |
| Why prior failures do not decide it | every prior failure used price/volume features only; funding was tested as a carry trade, never as an entry veto [ASM] |
| Primary metric | Δ = net mean (kept) − net mean (vetoed), per distinct setup, daily-aggregated paired difference; full costs |
| Test plan | S: veto module with last-settled-before-decision timestamp check and no-perpetual = no veto (recorded). X: on licensed pre-freeze funding + kline data. C: one admission only after X nominates it |
| Power | funding regimes persist for weeks → effective n ≈ number of episodes; likely underpowered within 365 days [HR A42-E] |
| Kill criterion | Δ ≤ 0 at X, or vetoes < 5 % of setups, or the effect vanishes after controlling for BTC 3-day return (pure beta timing) |
| Family / gate | `fam.new-information` / G-DATA (funding licence + new data contract), then G-SCI |
| Measured result | **NONE YET** |

**HR-02 — Daily "discount reversal" re-qualification under canonical costs on liquid tiers** (crosswalk: roadmap I1/I2, W6, R15)

| Field | Content |
|---|---|
| Statement | A pre-fixed daily rule (bullish internal CHoCH in discount, LuxAlgo-faithful parameters as already ported) has positive mean net return per trade under the canonical cost model on liquidity tiers A/B, in every calendar year of the exploratory window. Falsified by a non-positive mean or any negative year |
| Mechanism | two independent methods (XGBoost daily, faithful SMC) surfaced the same faint daily oversold/discount reversal [HR 2026-06-25, 2026-07-06] |
| Prior evidence | gross PF 1.06, n ≈ 3,157, net CI crosses 0 at 0.6 %; edge confined to small caps; 2026 significantly negative; top-5 % removal flips sign [HR 2026-07-06]. ML: positive only < 1M USDT/day, 6 months = 99 % of net [HR 2026-06-25] |
| Why prior failures may be implementation-specific | judged at 0.6 % round trip (≈ 1.6–1.9× canonical A/B cost) [VRF roadmap §2.2 (derived)]. **But** decay and illiquidity are not cost artefacts; this is the weakest "implementation-specific" case in the register [ASM] |
| Primary metric | mean net return per trade (tiers A/B), day-clustered; secondary vs EW B&H |
| Test plan | S: add synthetic tests to the existing untested research scripts (`research/skill_application/scripts/smc_backtest.py`, `ml_dataset.py` [VRF present]) and switch them to the canonical cost model. X: one look, liquid tiers only, logged. C: only if X passes all S4 failure criteria |
| Power | n ≈ 3,000 historical trades gives moderate power for ~0.3 %/trade; liquid subset is much smaller [ASM] |
| Kill criterion | any of: mean ≤ 0 on tiers A/B; 2025 or 2026 negative; top-1 % removal flips sign |
| Family / gate | `fam.daily-reversal`; the 14 SMC setups and the ML grid are registered as abandoned variants so DSR uses N ≥ 15 [ASM] / G-DATA |
| Measured result | **NONE YET** |

### Area 2 — Market regime classification

**HR-03 — BTC market-state gate for altcoin breakouts** (crosswalk: A45 H1)

| Field | Content |
|---|---|
| Statement | Momentum breakout setups admitted only when BTC's 3-day change (closed 4h candles) ≥ 0 have higher mean net return than the ungated stream; the removed subset has negative mean net return |
| Mechanism | ~80 % common component in crypto returns; momentum after down markets is weaker (Makarov–Schoar 2020; Cooper et al. 2004) [HR A45-B] |
| Prior evidence | decision-time frequency only: 30 % (15m) / 14 % (4h) of momentum setups occur with BTC 3-day < 0 [HR A45-C W6]. No outcome evidence. Contrary: momentum crashes occur in rebounds (Daniel–Moskowitz) |
| Why prior failures do not decide it | prior regime work used the symbol's own-TF ADX regime and a 20/50 MA gate (regime beta, F12), not market-wide state [ASM] |
| Primary metric | Δ net mean (kept − removed), day-clustered; secondary total net per day |
| Test plan | S: gate on synthetic frames, closed-candle-only check. X: licensed pre-freeze 15m/4h data with conservative A48 fills. C: **not recommended** |
| Power | gating variable is market-wide → effective n = number of BTC regime episodes; confirmatory test infeasible in 365 days [HR A45-F] |
| Kill criterion | removed subset mean net ≥ kept, or sign differs between 15m and 4h |
| Family / gate | `fam.breakout-gates` / G-DATA |
| Measured result | **NONE YET** |

**HR-04 — Daily time-series momentum long/cash on the liquid top-20** (crosswalk: S4 H1, roadmap W1/R1/R8, A45-G track 2)

| Field | Content |
|---|---|
| Statement | Holding each point-in-time top-20 coin only while its trailing 14-day return > 0 (else cash), 1/N risk budget, daily signal at 00:00 UTC executed at the next close, produces mean daily **active** net return vs equal-weight B&H > 0 (HAC lag 7) |
| Mechanism | time-series momentum at days–weeks in liquid large caps (Liu–Tsyvinski 2021; Moskowitz–Ooi–Pedersen 2012) [HR A45-B, verified there 2026-10-15] |
| Prior evidence | **no internal evidence either way** [VRF roadmap §2.5 item 2]. Contrary literature: Grobys–Sapkota 2019 (no significant momentum), Hudson–Urquhart 2021 (no OOS predictability for BTC) [HR A45-B]. Internal relative: 20/50 MA uptrend = regime beta [HR] |
| Why prior failures do not decide it | all internal failures are 15m/4h/1h indicator, breakout or reversion entries with fixed-bracket exits; none tested a daily long/cash allocation with literature-fixed parameters under canonical cost [VRF roadmap §2.5] |
| Primary metric | mean daily active net return vs EW B&H (notion c, S4 §4 draft); secondary absolute net return (a), PSR/DSR (b), MDD vs B&H. The R1 preregistration must name one primary notion; roadmap W1 expects (b) as best case — owner choice before any data |
| Test plan | S: allocation module, PIT universe builder, turnover × per-side cost ledger, synthetic parity tests. X: one logged look 2023-01-01 → 2026-08-18 after a 2019–2022 spec sanity pass (no tuning) [VRF S4 §4]. C: single admission under the Evidence Ladder |
| Power | for true SR 1.0: ≈ 0.76 over 8 years (exploratory), ≈ 0.13 over 1 year → a forward year cannot confirm a realistic effect (OD-DF-2) [VRF S4 A3] |
| Kill criterion | S4 failure criteria: HAC t ≤ 0; cost drag > 50 % of gross; MDD worse than EW B&H without Sharpe gain; > 50 % of P&L from 5 months or 1 coin; sign reverses under ×2 cost stress |
| Family / gate | `fam.s4-direction` / G-DATA, then G-SCI (+ OD-DF-2 validation design) |
| Measured result | **NONE YET** |

### Area 3 — Entry / exit timing

**HR-05 — Geometry v2: volatility-consistent entry + independent-resistance T1** (crosswalk: A46 G3 + G1, replaces a separate A45 H2)

| Field | Content |
|---|---|
| Statement | For momentum setups, resting the entry limit at min(close, L + 0.75 ATR) (so R = 1 ATR) and capping T1 only at a confirmed prior swing high raises mean net return per **signal** (unfilled = 0, counted) versus the production bracket |
| Mechanism | about one third of breakouts close > 0.75 ATR past the level and buy extension with a wider stop; the T1 cap self-references the breakout bar (confirmed defect W3) [HR A45-C W2/W3, A46-C] |
| Prior evidence | geometry only, no outcomes: ext > 0.75 ATR in 33.5 % (15m) / 35.9 % (4h); 90/223 4h momentum T1s capped [HR A42-B, A45]. Exit-geometry redesigns of the old mean-reversion entry all failed [HR roadmap F3] |
| Why prior failures do not decide it | F3 changed exits of an entry with AUC ≈ 0.50 and a different (reversion) family; HR-05 changes entry *price* of the breakout family and fixes a defect never corrected in any tested version [ASM] |
| Primary metric | net mean per signal (fills + non-fills), paired against baseline on the same setups, daily-aggregated; non-fill rate and post-non-fill drift reported |
| Test plan | S: done in part (A46 `a46-tg-v1`, 27 tests) [VRF `docs/a46`]; add A48 conservative fills. X: licensed 15m/4h history with A48 Mode 3 intervals. C: at most one geometry admission (A46-E) |
| Power | MDE ≈ 0.2–0.4 %/setup under day clustering; A48 interval widths (tenths of a pp) may exceed the effect [HR A45-F, A48-H]; S5-PWR-1: MDE ≤ 0.2 % only if DEFF ≤ 2.09 [VRF `S5_PWR_1_OWNER_DECISIONS.md`] |
| Kill criterion | Δ ≤ 0 at the conservative fill end, or sign reversal between 15m and 4h, or non-fill bias explains the difference |
| Family / gate | `fam.geometry` / G-DATA; C needs G-OPS (A44 enforce, forward capture) and G-SCI |
| Measured result | **NONE YET** |

**HR-06 — Trend-consistent exit for breakout entries** (new; relates to roadmap F3)

| Field | Content |
|---|---|
| Statement | Replacing the 25/50/25 T1/T2/T3 ladder and post-T1 break-even move with a single chandelier trail (3 × ATR14 from the highest close, initial stop unchanged) raises mean net return per trade of momentum breakouts |
| Mechanism | a persistence (breakout) entry earns from the right tail; the fixed ladder caps it at 2.2R and the T1→break-even path nets ≈ 0 (needs 81–96 % T1 hits if winners stop at T1) [HR A46-C] |
| Prior evidence | partial-TP-at-T1 was worse than riding to T2/T3 on the old entry [HR 2026-06-24]; no trailing-only test on the breakout family. Literature on trend exits is not internal evidence [ASM] |
| Why prior failures do not decide it | all exit variants tested were on mean-reversion entries whose premise is a bounce, not persistence [HR 2026-06-24] |
| Primary metric | net mean per trade, paired on identical entries; secondary right-tail share (top-1 % removal), holding time |
| Test plan | S: exit module + parity on synthetic paths through the A48 replay. X: licensed history, same entries as baseline. C: only as the single `fam.geometry` admission if it beats HR-05 at X |
| Power | per-trade paired design; heavy tails (power-law variances, Grobys–Shahzad) inflate σ [HR A45-B] [ASM] |
| Kill criterion | Δ ≤ 0; or positive only via the top 1 % of trades; or worse under conservative stop fills |
| Family / gate | `fam.geometry` / G-DATA |
| Measured result | **NONE YET** |

### Area 4 — Risk / reward distribution

**HR-07 — Cost-coverage floor (costs ≤ 0.25 R and T1→break-even path net ≥ 0)** (crosswalk: A42 C1, A46 G2)

| Field | Content |
|---|---|
| Statement | Refusing brackets whose full round-trip cost exceeds 0.25 R, or whose T1→break-even path is net-negative, raises **total net P&L per day** of the stream (not necessarily per-trade mean) |
| Mechanism | 20 bps exceeds R on thin 15m stops; ≈ 15 % of 15m T1s lie below net break-even ("gross win, net loss") [HR A42-B] |
| Prior evidence | geometry counts only; A42 proves analytically that under fixed notional and non-positive gross R-expectancy such a gate **lowers** mean net per trade and only cuts cost [VRF `tests/test_a42_signal_quality.py::test_cost_gate_can_lower_mean_net_return_under_fixed_notional`] |
| Why prior failures do not decide it | never tested; sign is theoretically ambiguous, so the hypothesis is stated on the daily total, where cost removal can dominate [ASM] |
| Primary metric | mean daily total net P&L (paired gated vs ungated); per-trade mean reported |
| Test plan | S: done in part (`CostCoveragePolicy`) [HR A42-D]. X: licensed history with A48 fills. C: **not recommended** (effect below MDE, sign ambiguous) [HR A42-E] |
| Power | ≈ 0.13 %/trade iid, × 2–3 for dependence; plausible effect below it [HR A42-E] |
| Kill criterion | daily total net not higher, or improvement disappears at 30 bps cost |
| Family / gate | `fam.breakout-gates` / G-DATA |
| Measured result | **NONE YET** |

### Area 5 — Position sizing and trade frequency

**HR-08 — Volatility-targeted sizing overlay** (crosswalk: roadmap W3/R18, S4 H1 vol-scaled variant)

| Field | Content |
|---|---|
| Statement | Scaling each position to a fixed volatility budget (20-day realized vol, target = universe median) instead of fixed notional raises PSR of daily net returns and lowers max drawdown, without lowering mean daily net return by more than 0.02 %/day, for the HR-04 portfolio (and, separately, the legacy stream with fixed-risk sizing) |
| Mechanism | momentum risk is predictable; volatility scaling roughly doubled Sharpe in equities (Barroso–Santa-Clara 2015; Moreira–Muir) [HR A45-B]. Contra: Cederburg et al. 2020 real-time failure [VRF roadmap W3] |
| Prior evidence | none internal. Fixed $50 notional makes per-trade risk vary ≈ 10× across TFs [HR A42-B] |
| Why prior failures do not decide it | every internal test used fixed notional [HR] |
| Primary metric | PSR / DSR of daily net returns (notion b) and MDD; non-inferiority on mean daily net (margin −0.02 %/day [ASM]) |
| Test plan | S: sizing module, turnover from rescaling costed at per-side cost, synthetic tests. X: as a registered variant alongside HR-04. C: only with HR-04 (not separately admitted) |
| Power | variance/drawdown endpoints need fewer days than mean endpoints, but heavy tails make variance metrics unreliable [HR A45-B #7] |
| Kill criterion | PSR not higher; or MDD not lower; or non-inferiority fails; or rescaling turnover cost > 25 % of the risk gain [ASM] |
| Family / gate | `fam.risk-overlay` / G-DATA |
| Measured result | **NONE YET** |

**HR-09 — BTC-beta-weighted correlated-exposure cap** (crosswalk: A42 C2, roadmap W4)

| Field | Content |
|---|---|
| Statement | Refusing new long exposure when Σ\|β_BTC\| × notional (96 closed bars, unknown β = 1.5) would exceed 75 USDT reduces daily net-return variance by ≥ 20 % and passes non-inferiority on mean net (margin −0.05 %/day) |
| Mechanism | two concurrent high-beta altcoin longs ≈ one leveraged BTC bet [HR A42-B.4] |
| Prior evidence | none outcome-based; logic built [HR A42-D] |
| Why prior failures do not decide it | never tested; it is a risk control, not an edge claim |
| Primary metric | variance and MDD reduction of daily net returns, paired with the uncapped counterfactual; mean net non-inferiority |
| Test plan | S: done in part. X: licensed history incl. the two-slot admission chain. C: risk-control validation (no alpha slot per A42-E; owner confirms) |
| Power | variance endpoint; moderate [ASM] |
| Kill criterion | variance reduction < 20 % or non-inferiority fails [HR A42-E] |
| Family / gate | `fam.risk-overlay` / G-DATA; production recording needs G-OPS |
| Measured result | **NONE YET** |

### Area 6 — Stop-loss / exit-policy robustness (trade-level stops, not the portfolio economic halt)

Prior record [HR stop-policy validation 2026-08-20]: STOP-A (stop = min(structural invalidation, entry − 1 ATR))
was best of five policies on 335,612 replayed rows (8 majors, 2017–2026-05), paired block bootstrap significant,
8/10 years and 100 % of rolling windows; **worst on the reversion branch** (paired CI entirely negative, n = 362);
the portfolio-level reversal was confined to 2017-08 → 2018-03 by the absorbing loss-streak halt and is a risk-engine
finding, not a stop finding. Verdict WEAKLY_SUPPORTED, no change. Those replays priced stops at the level (optimistic
per A47/A48). The loss-streak halt itself is out of scope here (contract §3).

**HR-10 — Reversion-branch stop cap**

| Field | Content |
|---|---|
| Statement | For reversion entries only, a hard 1.0 × ATR stop cap (STOP-B) gives higher mean net return per trade than STOP-A, in a window disjoint from the 2026-08-20 study and under A48 conservative stop fills |
| Mechanism | reversion stops anchor at the 20-bar low including the decision bar; a wide structural stop under a bounce premise risks more than the bounce pays [ASM] |
| Prior evidence | STOP-A worst on reversion, paired CI negative, n = 362 [HR 2026-08-20]; research-exposed window, optimistic stop fills |
| Why prior result is not final | single exposed dataset (8 majors), level-priced stops; never replicated [HR] |
| Primary metric | paired net mean per trade (STOP-B − STOP-A), reversion branch, day-clustered |
| Test plan | S: policy switch + A48 Mode 3 parity tests. X: licensed data **excluding** the 8 majors × 2017–2026-05 already studied, or flagged as a replication on the same data if no other exists. C: not recommended (reversion is ≈ 8 % of distinct brackets [HR A42-B]) |
| Power | low: reversion n small; ~3,340 trades needed for 80 % power for the earlier reversion effect size [HR canary close] |
| Kill criterion | Δ ≤ 0 under conservative fills, or sign flips between 15m and 4h |
| Family / gate | `fam.stop-policy` / G-DATA |
| Measured result | **NONE YET** |

**HR-11 — No-progress time stop**

| Field | Content |
|---|---|
| Statement | Exiting a trade that has not reached +0.5 R within 1/3 of its TF expiry raises net return per unit of capital-time (net % ÷ position-days) without lowering mean net per trade |
| Mechanism | STOP-A's gain came with 1.6–2× longer capital-at-risk duration [HR 2026-08-20]; stalled breakouts are failed persistence [ASM] |
| Prior evidence | none direct; production already has a T1-stall expiry (e.g. 4h 48 h) [VRF A45-A / A46-B tables] |
| Why prior failures do not decide it | not tested |
| Primary metric | net % per position-day (paired); mean net per trade non-inferiority (margin −0.05 %) [ASM] |
| Test plan | S: exit rule in the replay with synthetic paths. X: licensed history. C: not recommended standalone |
| Power | paired per-trade; moderate [ASM] |
| Kill criterion | non-inferiority fails, or capital-time gain < 10 % [ASM] |
| Family / gate | `fam.stop-policy` / G-DATA |
| Measured result | **NONE YET** |

### Area 7 — Fees, spread, slippage, turnover

**HR-12 — Resting-limit (maker-style) entry execution** (crosswalk: `resting_limit_v1`, roadmap W5/R19)

| Field | Content |
|---|---|
| Statement | Entering via a resting limit at the planned price (no chase) instead of `observed_price_v0` lowers realized per-trade entry cost by at least half the half-spread plus slippage, and the net effect including non-fill opportunity cost and adverse selection is ≥ 0. The fee stays 0.10 %/side (no maker discount assumed) |
| Mechanism | spread capture; avoids paying slippage on entry |
| Prior evidence | none; `resting_limit_v1` disabled, owner-gated [VRF roadmap §0, `shared/config.py`] |
| Why prior failures do not decide it | every result in the record used touch/observed fills [VRF A47-A] |
| Primary metric | net mean per **signal** (fills and non-fills), non-fill rate, post-non-fill drift, per tier |
| Test plan | S: exchange-rule rounding (A47 `exchange_rules`), synthetic queue scenarios. X: **impossible on klines alone** (no queue/book history). C: forward paper capture only (G-OPS + G-SCI) |
| Power | cost difference is small (≈ 0.05–0.10 %/trade) and adverse selection is the unknown [ASM] |
| Kill criterion | net per signal < baseline, or non-fill rate > 40 % with positive post-non-fill drift [ASM] |
| Family / gate | `fam.execution-cost` / G-OPS + G-SCI |
| Measured result | **NONE YET** |

**HR-13 — No-trade band for the daily TSMOM allocation** (variant of HR-04)

| Field | Content |
|---|---|
| Statement | Requiring the 14-day return to exceed +1 % to enter and fall below −1 % to exit (hysteresis), with all else as HR-04, lowers turnover by ≥ 30 % and raises mean daily net return relative to HR-04 |
| Mechanism | high-turnover anomalies lose most of their profit to costs; buy/hold spreads help (Novy-Marx–Velikov 2016) [HR A45-B #24] |
| Prior evidence | none internal |
| Why prior failures do not decide it | not tested; band width fixed before data, not tuned [ASM] |
| Primary metric | mean daily net return difference vs HR-04 (paired days); turnover and cost drag |
| Test plan | S: band logic + turnover ledger. X: registered variant in the same look as HR-04. C: only if the owner names it the HR-04 primary before data |
| Power | paired-day design on the same universe; difference likely small [ASM] |
| Kill criterion | turnover reduction < 30 % or net difference ≤ 0 |
| Family / gate | `fam.s4-direction` (counts in DSR N; no extra alpha share) / G-DATA |
| Measured result | **NONE YET** |

### Area 8 — Stability across assets and regimes

**HR-14 — Liquidity-tier restriction improves net and stability**

| Field | Content |
|---|---|
| Statement | For any candidate above, restricting the universe to tiers A/B (BTC, ETH, other top-20 by 30-day median quote volume) gives (i) mean net return ≥ the ≥ 10 M USDT universe and (ii) a positive sign in ≥ 2 of 3 BTC regimes (up / down / range by BTC 50-day return terciles, fixed before data) and in ≥ 60 % of coins with ≥ 30 trades |
| Mechanism | momentum strongest in the most liquid coins; daily reversal dominates illiquid coins (Zaremba et al. 2021; Begušić–Kostanjčar 2019) [HR A45-B #9/#10]; lower and measurable costs |
| Prior evidence | **contrary**: the two daily positives lived only in illiquid coins [HR 2026-06-25, 2026-07-06]; cross-sectional long leg weak [HR 2026-06-07] |
| Why prior failures do not decide it | those were reversion/ML signals, where the literature predicts illiquid concentration; HR-14 is stated for momentum-type candidates [ASM] |
| Primary metric | net mean per trade/day by tier; sign stability by regime and coin |
| Test plan | S: PIT tier classifier with delisted coins kept. X: stratified report inside each candidate's look (no extra look). C: stability is a precondition for any admission, not a separate admission |
| Power | per-stratum n shrinks; report CIs, no per-stratum claims [ASM] |
| Kill criterion | tier A/B mean below the broad universe, or positive in < 2 regimes |
| Family / gate | `fam.universe` / G-DATA |
| Measured result | **NONE YET** |

## 3. Ranking by expected contribution to credible net-profitability evidence

Roadmap rubric (§7.1): IV information value, P probability of delivering credible evidence of **either** sign,
T time-to-evidence after the gate, C engineering complexity; Score = IV × P × T − C. **All scores [ASM].**

| Rank | ID | IV | P | T | C | Score | One-line reason |
|---|---|---|---|---|---|---|---|
| 1 | HR-04 | 5 | 4 | 3 | 2 | 58 | only direction with supportive crypto literature at its horizon and no internal evidence either way; A45-G track 2 |
| 2 | HR-08 | 4 | 4 | 3 | 1 | 47 | same look as HR-04; variance endpoints are better powered than mean endpoints |
| 3 | HR-14 | 3 | 4 | 3 | 1 | 35 | stratification inside existing looks; guards against the illiquid-only failure pattern |
| 4 | HR-13 | 3 | 4 | 3 | 1 | 35 | cost drag is the binding obstacle (O1); cheap paired variant |
| 5 | HR-09 | 2 | 4 | 3 | 1 | 23 | risk control on the actual Paper stream; no alpha needed |
| 6 | HR-03 | 2 | 3 | 3 | 1 | 17 | literature-backed but market-wide variable → not confirmable |
| 7 | HR-07 | 2 | 3 | 3 | 1 | 17 | sign ambiguous under fixed notional |
| 8 | HR-02 | 2 | 3 | 3 | 2 | 16 | prior decay and illiquidity are not cost artefacts |
| 9 | HR-06 | 2 | 3 | 3 | 2 | 16 | entry has no demonstrated gross edge |
| 10 | HR-05 | 3 | 3 | 2 | 3 | 15 | fixes a confirmed defect, but replay-interval width may exceed the effect |
| 11 | HR-01 | 4 | 2 | 2 | 3 | 13 | new information, blocked by licence and data contract |
| 12 | HR-10 | 1 | 3 | 3 | 1 | 8 | small branch, replication only |
| 13 | HR-11 | 1 | 3 | 3 | 1 | 8 | capital-efficiency, second order |
| 14 | HR-12 | 3 | 3 | 1 | 3 | 6 | needs forward capture; no historical test possible |

Rank sets priority, not authorization. Dependencies: every stage X needs a `DatasetPermission` (none exists);
HR-04/08/13/14 need the R1 preregistration accepted first; HR-05/06/07/03/10/11 on the legacy stream need A48
conservative fills; at most three simultaneous stage-C candidates and one per family (`fam.geometry` explicitly).

## 4. Safe next work (stage S only, D0)

1. Pure modules + synthetic tests for HR-04/HR-08/HR-13/HR-14 (allocation, sizing, band, PIT tiers, turnover ledger),
   reusing `research/mechanisms/costs.py`; register synthetic variants only (`SYNTHETIC`).
2. Synthetic power simulations per hypothesis with heavy-tailed, day-clustered returns to replace the [ASM] power notes.
3. Exit-rule modules for HR-06/HR-11 on the A48 replay, with parity tests.
4. A preregistration template per family that records family N, including the historical abandoned trials (HR-02).

## 5. What this register does not claim

- **No profitability is claimed** for any hypothesis, strategy version or the current Paper strategy. Every
  "Measured result" is NONE YET. Synthetic or exploratory success would not be profitability evidence either.
- Historical rows are quoted from memory notes and older audits as recorded and were **not re-verified**.
- **D1/D2 remain on HOLD** for governed confirmation; no stage-C test can start until the owner lifts it and grants
  the scientific authorization, preregistration, prospective-partition record and alpha slot.
- **The sealed FORWARD_HOLDOUT is untouched**: no outcome, count or timestamp after the 2026-08-19 freeze instant was read,
  used or quoted. No dataset permission, alpha, look, Paper window or ledger entry was created.
- Prior negative results are evidence against the tested implementations only; they are not proof that the
  hypotheses above will fail, and the expected outcome for most of them remains a null or inconclusive result.
