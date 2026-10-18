# A42 — Trading Strategy & Signal Quality Development

| Field | Value |
|---|---|
| Date | 2026-10-14/15 (UTC) |
| Source analysed | running Paper code `59297305` (read in `~/tsb-a38-base`) |
| Branch | `feature/a42-signal-quality` (worktree `~/tsb-a42-worktree`, from `59297305`). Local only: not pushed, not merged, not deployed |
| Code commits | `8f8464f` (diagnostics), `a282437` (counterfactual replay) |
| Data read | **Read-only.** Running-container env (selected keys only); `signals` table **bracket geometry only** (entry, stop, targets, timeframe, type). **No outcome table joined, no protected P2 data, no backtest, no prospective trial, no budget spent** |

Five levels of claim are kept apart throughout:
1. **engineering correctness** (tests);
2. **economic plausibility** (arithmetic on geometry and costs);
3. **historical exploratory evidence** (research-exposed; never confirmation);
4. **prospective confirmation** (Evidence Ladder only);
5. **deployment readiness** (owner).

A passing test suite here is evidence of level 1 only.

---

## A42-A — Strategy Architecture & Decision Map

### A.1 Source-to-decision map (live path, `LIVE_LEARNING_MODE=true`)

| # | Stage | Source | Rule in force | Production value |
|---|---|---|---|---|
| 1 | Universe | `scanner` | Binance Spot symbols with 24 h volume ≥ `MIN_VOLUME_USDT` | 10 M USDT; scan every 300 s |
| 2 | Candles | `analyzer/technical_analyzer.py` | closed bars only; ≥ `indicator_warmup_bars()` history | TF `15m,4h,1d` (container env) |
| 3 | Indicators | `shared/strategy_math.calculate_production_indicators` | RSI14, MACD, EMA20/50/200, BB, ATR14, ADX14, StochRSI, OBV, volume ratio | config defaults |
| 4 | Regime | `shared/regime.classify_regime` | bullish: ADX ≥ 25, EMA20 slope > 0, close > EMA20. bearish: mirror. sideways: ADX < 20 and ATR% percentile ≤ 0.75. Else volatile | fixed |
| 5 | Setup | `analyzer/simple_entry.detect_trade_setup` | **momentum** (only when bullish): close > EMA20 > EMA50, close > prior 20-bar high, volume > 1.2 × 20-bar mean. **reversion** (only when sideways): RSI < 35, close > previous close and > open, BB position ≤ 0.20 | `MOM_BREAKOUT_N` 20, `MOM_VOL_MULT` 1.2, `REV_RSI` 35, `REV_BB_MAX_POSITION` 0.20 |
| 6 | Stop | `shared/signal_stop.plan_signal_stop` | thesis level (momentum: breakout level; reversion: 20-bar low) − 0.25 ATR, and at least 1 ATR below entry. Rejected if risk > TF cap | caps 15m 2 %, 4h 5 %, 1d 3 % |
| 7 | Targets | `technical_analyzer._calculate_levels` | T1 = 1R, T2 = 1.8R, T3 = 2.2R. **T1 capped at 0.99 × 20-bar high** when that lies between entry and 1R | fixed |
| 8 | Score | `_calculate_scores` | computed and stored. **Not used by the live selector** | — |
| 9 | Candidate query | `signal_engine/main.py` | `analysis_results` rows < 30 min old, no open trade, `ORDER BY symbol, score DESC LIMIT 200` | — |
| 10 | Macro block | `MacroContext.should_block_now` | BTC strong_bearish or USDT.D rising_fast → no signal | — |
| 11 | Per-candidate filters | `find_best_signal_live` | needs a setup; a valid order book with spread ≤ `MAX_SPREAD_PCT`; `stop_valid`; no open trade on the symbol; symbol not in 2 h cooldown; learned-gate throttle | spread 0.15 %; **`LEARNING_GATES_ENABLED=false`** (no throttle) |
| 12 | Selection | `_fixed_candidate_key` | **one** candidate per cycle: lowest spread, then highest volume, then symbol, then TF | `selection_policy=fixed_execution_quality_v1` |
| 13 | Persist and publish | `save_signal` | `signals` row + `signal.ready` in one transaction | `strategy_version` sb-2026.08 |
| 14 | Admission | `trade_tracker` | 2 h admission window; capacity; exposure ≤ 80 % of 500; one per symbol; halt after a 7-loss streak | `RISK_CANARY_MAX_OPEN_TRADES` 2, $50 fixed notional |
| 15 | Entry | `shared/entry_execution.decide_long_entry` | reject if price ≤ max(stop, invalidation); market if ≤ planned entry; else limit at planned entry (no chase) | Paper fill model `observed_price_v0` |
| 16 | Exits | `shared/triple_barrier.step_barrier` + `partial_exits` | stop checked first each bar. Tranches 25/50/25 at T1/T2/T3. After T1 the stop moves to the **net break-even** = min(T1, entry × 1.003 / 0.999); after T2 it trails 2.5 % (floored at T1) | expiry by TF: 15m 48/24/12 h, 4h 96/48/24 h, 1d 240/120/72 h |
| 17 | Accounting | `shared/fees.py` | gross stored; net = gross − `FEE_ROUNDTRIP_PCT` | 0.3 (0.2 fee + 0.1 slippage); stop fills × (1 − 0.001) |

**Inert in live mode** (they exist only in the legacy `find_best_signal`):
- the DB thresholds `min_score_to_signal` 3.0 and `min_timeframe_confirmations` 2;
- the BTC-crash check;
- the global-loss and inter-signal cooldowns.

The CLAUDE.md rule "DB thresholds override `.env`" is true, but it does not reach the live path.

### A.2 Frozen vs safely improvable

| Frozen (must not change without owner and scientific authorization) | Safely improvable now (local, disabled, versioned) |
|---|---|
| Steps 2–7 and 10–17 as listed; selection key; exit rules; costs as booked; `strategy_version`; P2 / A34-VS1 / MI contracts; Paper R2 configuration | Pure diagnostics computed *beside* the decision (provenance, cost and geometry reports); shadow policies that never block; synthetic fixtures; config validation; specifications and harnesses |

### A.3 Historical vs Paper vs prospective

| Aspect | Historical review (Phase 5/6, research-exposed) | Paper R2 (A37, diagnostic) | Prospective (Ladder) |
|---|---|---|---|
| Capacity | 10 × $50 assumed | 2 open trades | per protocol |
| Fills | close-based | `observed_price_v0`: resting limits fill at the observed price, mean ≈ 13 bps optimistic (A37/A38) | must use a pre-registered fill model |
| Costs | 0.3 % | 0.3 % booked; A37 shows 20 and 30 bps | 20 bps baseline, operational separately |
| Selection | all trades | 1 signal per cycle, capacity-refused 39/182 | as frozen |

**Reported baseline, checked against the repo record** (`docs/phase6_portfolio_review_2026-08-17.md`):

| Metric | Directive said | Repo record |
|---|---|---|
| Clean trades | ~320 | **307** |
| E / PF per trade | PF ~1.057 | +0.056 % / 1.06 |
| Return | +1.72 % | +1.72 % (on $500) |
| Sharpe / Sortino | 1.36 | 1.36 / 2.45, over **25 exit days** |
| Max drawdown | — | 3.56 % |
| WR 27.19 % / payoff 2.83 | as stated | **not found in the repo docs; unverified** |

**Fragility** (same record): removing the best 5 trades gives PF 0.88; removing the best symbol gives E −0.037 %.

Phase 5 walk-forward: 185 OOS trades, E +0.046 %, PF 1.05, only 2 of 5 folds positive. This is **not a reliable forward edge**, consistent with the directive.

---

## A42-B — Signal Quality & Economic Weakness Assessment

Each finding is tagged: **[O]** observed (geometry or code fact), **[D]** implementation defect, **[H]** hypothesis, **[U]** unresolved. Nothing below infers causation from aggregate Paper P&L.

### B.1 Entry economics: the cost-coverage question, answered before building a gate

**[O] Geometry.** Signals under `fixed_execution_quality_v1`: 1,321 rows, 2026-08-18 → 10-14, of which **1,117 are distinct brackets**. Stats on distinct brackets:

| TF / type | n | median stop distance R | T1 below 1R (resistance-capped) | T1 < 0.30 % | T1 < net break-even (0.40 %) | 20 bps > R | 20 bps > ¼R |
|---|---|---|---|---|---|---|---|
| 15m momentum | 799 | 0.92 % | 27 | 85 | 124 | 30 | 322 |
| 15m reversion | 85 | 0.86 % | 0 | 6 | 12 | 2 | 40 |
| 4h momentum | 223 | 2.93 % | **90** | 20 | 27 | 0 | 9 |
| 4h reversion | 6 | 2.52 % | 0 | 0 | 0 | 0 | 0 |
| 1d momentum | 4 | 1.83 % | 0 | 0 | 0 | 0 | 0 |

Smallest 15m stop: **0.066 %**, i.e. a 20 bps round trip ≈ 3R.

**[O] What the exit rules imply.** Cross-checked to the tracker in tests:
- After T1, 75 % of the position exits at the net break-even ≈ entry × 1.004. With the stop slippage, and with 0.3 % booked, that leg nets about 0. The T1 path's net is therefore ≈ 0.25 × T1 % − 0.075 % (30 bps accounting), or ≈ T1 % − 0.375 % when T1 is below the break-even level.
- At the median 15m geometry (R 0.92 %, T1 0.875 %), the two-path model needs a **T1 touch rate ≈ 90 %** to break even: (stop vs T1 → break-even). Net profitability comes from reaching **T2/T3**.

So the size of T1 relative to cost is decision-relevant only for the ~15 % of 15m brackets whose T1 lies below the break-even level. There, a "T1 WIN" is a **gross win and a net loss**, which is the mechanism behind A37's 7/89 economic relabels.

**[O] Fixed notional changes the sign of the gate's effect.** Sizing is a fixed $50, not fixed-risk. Per-trade net % ≈ R % × E[R-multiple] − cost.
- If the gross R-expectancy is ≤ 0, as every prior study found, **removing small-R trades does not raise mean net % per trade. It lowers it**, because large-R trades lose more per trade. The gate only cuts turnover and total cost.
- Only a **positive** gross R-expectancy makes a cost/R gate improve mean net. This is demonstrated in `test_cost_gate_can_lower_mean_net_return_under_fixed_notional`.

**Therefore a cost-coverage gate is not assumed beneficial.** It is specified (C1) as a hypothesis whose sign is unknown.

### B.2 Selection

- **[O]** The live selector ignores score and confirmations. Among eligible candidates it takes the tightest spread. With the universe ≥ 10 M USDT, spreads differ by a few bps, while cost/R differs about 10× across candidates (0.07 R on 4h vs 0.22 R median on 15m). The ranking optimises a second-order cost and ignores the first-order one.
- **[O]** `ORDER BY symbol … LIMIT 200` truncates **alphabetically** when > 200 rows are eligible. Evidence v2 records truncation; the frequency is not assessed here **[U]**.
- **[H]** Under capacity contention (39/182 refused in R2), the choice of which candidate takes a slot may matter more than any gate.

### B.3 Implementation defects relevant to evidence validity

1. **[D] Same-bar re-firing.**
   - **Observed:** **185/414 4h signals and 19/23 1d signals are exact repeats** of an already-emitted bracket (same symbol, entry, stop, T1). **15m: 0.**
   - **Cause:** the symbol cooldown is 2 h of wall-clock time (`_get_symbol_cooldown_set`), but a 4h/1d closed bar stays current for 4–24 h, so the same setup is re-emitted after every cooldown.
   - **Effect:** pseudo-replication at the signal layer still exists under the fixed policy. Whether the tracker admits the repeats was not checked, because that needs outcome and lifecycle data. Any per-signal statistic over 4h/1d inflates the effective n.
   - **Pure fix:** `signal_fingerprint` / `split_duplicates` (closed-bar identity).
2. **[D] Cooldown fails open.** On a DB exception, `_get_symbol_cooldown_set` returns an empty set, so there is no cooldown. Low practical risk, because other steps would also fail, but it is the opposite of the project's fail-closed rule.
3. **[D/H] Momentum T1 cap uses the breakout bar's own high.**
   - **Observed:** for momentum, "resistance" = max(high of the last 20 bars **including the breakout bar**). This capped **90/223 distinct 4h momentum T1s** below 1R.
   - **The design question [H]:** the level was just broken, so it is not resistance. Changing it alters frozen targets, so it is recorded, not changed; prior research found target geometry is not the main defect.
4. **[O] Inconsistent cost layers (documented, not changed).** Fees are 0.3 % (including 0.1 % slippage), stop fills have an extra 0.1 %, and the break-even stop uses 0.3 %/0.1 %. A stop exit is therefore charged ≈ 0.4 %. The new `CostModel` separates the exchange fee, slippage and spread, and keeps the strategy's break-even constants apart in `StrategyBracketRules`.

### B.4 Market conditions and portfolio behaviour

- **[O]** Momentum is emitted only in `bullish` and reversion only in `sideways`. Most signals (1,026 of 1,117 distinct brackets) are momentum, so the strategy is effectively a **long-only breakout book conditioned on bullish ADX regimes**.
- **[H]** The two concurrent slots hold long spot altcoins with typical BTC beta ≈ 1–1.5. The portfolio is close to one leveraged BTC-beta bet. Correlated exposure is not capped; only one position per symbol is enforced.
- **[U]** A real-data verification of the BTC-beta / correlation estimates is outside A42; it requires market data the directive does not authorise analysing for outcomes.

---

## A42-C — Prioritized Development Backlog

Ranking: decision value per unit risk, favouring items that need no protected experiment.

| # | Item | Mechanism | Area | Complexity | Uncertainty | Overfit risk | Data / compute | Impact | Contract-compatible | No protected experiment needed |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Closed-bar dedup** of 4h/1d re-fires (fingerprint) | removes pseudo-replication | evidence validity | low | low | none | none | high (validity) | needs owner: production change | ✅ helper done; wiring is a production change |
| 2 | Cost/geometry **shadow report** on every candidate (`assess_candidate`) | explainability, provenance | diagnostics | low | low | none | none | medium | yes (additive) | ✅ module done; recording in production is a deployment |
| 3 | **Counterfactual tracker for unselected candidates** (shadow barrier replay on forward bars) | makes selection and gate candidates evaluable | evaluation infrastructure | medium | medium | none | low | high (enables C1/C2) | yes (shadow) | ✅ **replay library built** (`a42-cf-bar-v1`); the forward-bar feed and running it are an experiment |
| 4 | C2 beta-weighted exposure cap (shadow) | variance reduction | portfolio | low | medium | low | BTC closes | medium (risk) | yes | ✅ logic done |
| 5 | C1 cost/R gate or cost-aware rank (shadow) | cost burden per unit risk | entry economics | low | high (sign unknown) | medium | none | uncertain | yes | ✅ logic done |
| 6 | Fail-closed cooldown | safety | engineering | trivial | low | none | none | low | owner (production) | ✅ |
| 7 | Candidate truncation: deterministic, not alphabetical | universe fairness | selection | low | low | low | none | low/medium | owner | ✅ |
| 8 | C3 funding-crowding veto | crowding / leverage mechanism (new information) | signal mechanism | medium | high | medium | funding history (licence check) | potentially material | new contract | spec only |
| 9 | Momentum T1 cap redesign | target geometry | exits | low | high | high | — | low (prior evidence) | changes frozen strategy | ❌ deferred |

---

## A42-D — Safe Engineering Implementation

**Commit `8f8464f`** on `feature/a42-signal-quality` (local only).

| File | Content | Why it is safe |
|---|---|---|
| `shared/signal_quality.py` (new, `a42-sq-v1`) | `CostModel` (20 bps baseline, separate slippage/spread, a tracker-accounting preset); `StrategyBracketRules` (mirror of the tracker constants); `bracket_geometry`; `path_payoffs` (stop / T1→BE / T2 with a T1 floor / T3); `required_win_rate`; `assess_candidate` (canonical input sha256, flags, explanation); `CostCoveragePolicy` (C1); `cost_aware_rank_key`; `beta_and_correlation`; `CorrelatedExposurePolicy` (C2); `signal_fingerprint` / `split_duplicates`; `signal_staleness`; `bar_gaps`; `validate_policies` | Pure, no I/O, no config reads. **Imported by no production module** (asserted by a test). Every policy is `enabled=False`; `PolicyDecision.allow` is always True when disabled. No production file changed |
| `shared/counterfactual_barrier.py` (new, `a42-cf-bar-v1`) | `replay_bracket`: the frozen entry decision → proportional rebase → `step_barrier` per closed bar → `fills_between` / `aggregate_close`, net of the `CostModel`. Declared approximations: bar-level conservative order; a gap fills at the open; a resting limit fills only on a strict trade-through (removes A37's optimistic touch fill); a bar that both trades through and invalidates is treated as no fill. Look-ahead, gap and malformed-bar inputs → `invalid` | Pure; no production caller (asserted). Running it on real forward bars is a prospective experiment and is **not done** |
| `tests/a42_synthetic.py` | deterministic fixtures: strong trend, sideways, volatility spike, correlated pair | test-only |
| `tests/test_a42_signal_quality.py` | 24 tests | test-only |
| `tests/test_a42_counterfactual.py` | 11 tests: stop / T1→BE / T3 parity with the payoff model; touch vs trade-through; invalidated while waiting; 2 h window; reject at open; gap through stop; rebase; 12 h no-T1 expiry; input validation; spread charging | test-only |

**Decision-changing?** No. Production behaviour is byte-identical: the diff from `59297305` adds only new files (two modules, three test files, this report).

**Scenario coverage** (all through real production pure functions where one exists):

| Scenario | Test | Property shown |
|---|---|---|
| Strong trend | `test_strong_trend_…` | bullish regime → momentum; stop ≥ 1 ATR; net stop < 0 < net T3 |
| Sideways | `test_sideways_never_emits_momentum` | sideways regime; no momentum |
| Sudden reversal | `test_sudden_reversal_exits_at_modeled_stop` | stop fill = stop × 0.999 |
| Volatility spike | `test_volatility_spike_…` | `volatile` → no setup |
| Low liquidity / spread widening | `test_low_liquidity_and_spread_widening_…` | cost/R monotone in spread; a missing spread fails closed |
| Delayed signal | `test_delayed_and_look_ahead_signals` | stale > 1 bar; decision before bar close rejected |
| Missing data | `test_missing_data_is_detected_not_repaired` | gaps and non-monotone times detected; NaN ATR → no economics |
| Correlated simultaneous signals | `test_correlated_simultaneous_signals_hit_the_beta_cap` | β ≈ 1.5 recovered; cap blocks the second high-β position; unknown β fails closed; disabled never blocks |
| Entry rejected | `test_entry_rejected_…` | reject through invalidation; limit_wait when price ran |
| Gap through stop | `test_gap_through_stop_…` | actual loss > modeled stop path (the model is a lower bound) |
| Fees exceeding gross | `test_fees_exceeding_gross_win_is_flagged` | gross WIN, net loss; flags; required rate = None |
| Duplicate signal | `test_duplicate_signal_from_the_same_closed_bar` | same-bar repeat removed |
| Expired signal | `test_expired_signal_closes_on_timeframe_policy` | 4h no-T1 expiry at 24 h |

**Further tests:**
- **Tracker parity:** the T1→BE path matches the tracker for T1 above and below the break-even level; the stop and T3 paths match `step_barrier` / `fills_between`.
- **Determinism and provenance**, config validation, cost presets = tracker config, and the fixed-notional gate caveat.

**Regression counts** (scratch venv, `pytest tests`):

| Tree | Passed | Skipped | Subtests | Failed |
|---|---|---|---|---|
| base `59297305` | 751 | 747 | 46 | 0 |
| `8f8464f` | 775 | 747 | 46 | 0 |
| branch head (with the counterfactual replay) | **786** | 747 | 46 | **0** |

The skips are DB- and parity-gated suites (DSN not set) and are identical on both trees. The A42 files alone: 35/35 (24 + 11).

---

## A42-E — Candidate Research Specifications (3, materially distinct; none run)

Common to all three:

| Element | Specification |
|---|---|
| Unit | one admitted (or counterfactual) trade on the frozen stream |
| Cost | baseline **20 bps** round trip (`CostModel()`); operational slippage and spread reported as a separate column, never folded into the estimand |
| Net excess return | per-trade net % of notional minus the paired control arm's net % on the **same** signal stream and timestamps |
| Provenance | `assess_candidate` report + input sha256 + policy version on every row |
| Data | only prospective bars after registration. **Historical research-exposed data is not confirmation** and was not used to choose any parameter. The geometry counts in B.1 were inspected **without outcomes**; the parameters below are fixed from first principles, and that exposure is declared |
| Dependence | trades overlap in time and share BTC beta, so inference is on **daily-aggregated** paired differences with the A30/A32 envelope-calibrated GS machinery (HAC/block variance). Skew and heavy tails use the A27/A28 batch rules |
| Multiple testing | each candidate is one admission at **α = 1/240** within the FWER 5 % / 12-admission ledger; ≤ 3 simultaneous; 20 % capacity reserve |
| Horizon | ≤ 365 days, final look only (A31) |
| Stop conditions | protocol breach, data gap > 24 h, fill-model change, or any production change to the stream → invalidate the window (declared, never pooled) |

### C1 — Cost-per-risk gate / cost-aware ranking (entry economics)

| Element | Specification |
|---|---|
| Rationale | cost consumes 0.07 R (4h) to > 1 R (thin 15m stops); the selector ranks by spread, a second-order term |
| Inputs | entry, stop, targets, ATR, spread at selection |
| Exact rule | `CostCoveragePolicy(max_cost_over_risk=0.25, require_t1_path_net_positive=True)`. Variant C1-rank: `cost_aware_rank_key` replaces `_fixed_candidate_key`, applied only under contention |
| Pre-fixed parameters | 0.25 R (cost ≤ a quarter of the loss leg), 20 bps; **not tuned** |
| Trade-off | fewer, wider-stop trades; larger per-trade variance |
| Failure regimes | if the gross R-expectancy is ≤ 0 (all prior evidence), **mean net per trade falls** (B.1) while total cost falls |
| Cost sensitivity | the effect scales with cost; under 30 bps more trades are gated |
| Falsification | the gated arm's daily paired net difference ≤ 0 at the final look, or its CI excludes the MDE |
| Leakage risks | spread snapshot timing (must be the pre-decision book); ATR from closed bars only |
| Required evidence | a counterfactual tracker (backlog #3) so excluded and non-selected trades have outcomes |
| Power | iid MDE for a difference in means ≈ 3.48·σ·√(1/n₁+1/n₂). With an assumed σ ≈ 1.5 %/trade and the observed rate annualised (~2,300 flagged vs ~4,700 unflagged distinct brackets a year), that is ≈ **0.13 %/trade iid, before a design effect of 2–3× for dependence**. The plausible effect is below this |
| Ladder eligibility | **eligible in form, but not recommended for admission**: the expected effect is below the MDE, and the sign is theoretically ambiguous |

### C2 — BTC-beta-weighted correlated-exposure cap (portfolio risk)

| Element | Specification |
|---|---|
| Rationale | 2 slots of long high-beta altcoins ≈ one leveraged BTC bet |
| Inputs | closed-bar log returns of the asset and BTCUSDT on the signal's TF, the last 96 bars (pre-fixed) |
| Exact rule | `CorrelatedExposurePolicy(max_beta_weighted_notional_usdt=75, unknown_beta=1.5)`: Σ\|β\|·notional, including the candidate, must be ≤ 75 USDT; otherwise refuse |
| Pre-fixed parameters | 75 = 1.5 × one $50 β = 1 position; unknown β = 1.5 (fail-closed); 96 bars, min 30 |
| Trade-off | fewer concurrent positions in high-β alts; lower capacity use |
| Failure regimes | in broad rallies the cap forgoes winners; if β estimates are unstable the cap acts as random throttling |
| Cost sensitivity | none directly (it is not a cost rule) |
| Estimand | **not an edge claim.** The primary outcome is the reduction in daily portfolio net-return variance and max drawdown, paired with the uncapped counterfactual; the secondary is mean net (non-inferiority, margin −0.05 %/day) |
| Falsification | variance reduction < 20 %, or non-inferiority fails |
| Leakage | β must use bars closed before the decision |
| Ladder eligibility | **risk-control validation, not an alpha admission**: it does not consume an alpha slot or the A34-VS1 budget. It needs the counterfactual tracker and an owner decision to record shadow verdicts in production |

### C3 — Perpetual-funding crowding veto (new information; mechanism change)

| Element | Specification |
|---|---|
| Rationale | prior work exhausted price-only TA (no post-fee edge). Crowded leveraged longs (high positive funding) are a different mechanism, implying long-squeeze risk for spot breakouts |
| Inputs | Binance USDⓈ-M funding rate for the symbol's perpetual. Use the **last settled** rate before decision time (not the predicted rate, to avoid ambiguity). No perpetual → no veto (recorded) |
| Exact rule | veto a momentum long when the last settled funding is ≥ 0.03 % per 8 h (3× the 0.01 % baseline) |
| Pre-fixed parameters | 0.03 %, last settled only; reversion is unaffected |
| Trade-off | removes breakouts during leverage euphoria, which may be the strongest trends |
| Failure regimes | funding regimes persist for weeks, so few vetoes and a wide CI; the effect may be pure BTC-beta timing |
| Cost sensitivity | low (it removes trades) |
| Falsification | the vetoed subset's counterfactual paired net ≥ the kept subset's at the final look |
| Leakage | funding settlement timestamps (8 h) vs the decision; delistings; symbols without perpetuals (selection bias) |
| Data / licence | funding history is public API data, but **licence terms must be checked** (A18/A19 HOLD on Vision NC terms). It is a new data source, so it needs a new contract |
| Ladder eligibility | candidate for **one** admission after licence clearance and a frozen spec; **not now** |

---

## A42-F — Next Scientific Decision

### **ENGINEERING CONTINUE**

**Reasons:**
1. **Evidence validity comes first.** 4h/1d signals re-fire from the same closed bar (185/414, 19/23). Any prospective statistic on this stream is pseudo-replicated until closed-bar dedup is in production. That is an owner-approved production change, not authorized here.
2. **Candidates are not yet evaluable.** C1 and C2 both require outcomes for non-selected or refused candidates. The replay library now exists, but it has no authorized forward-bar feed or recording path, and its bar-level approximation has not been calibrated against tracker polls.
3. **Power.** C1's plausible effect is below its MDE, and its sign is theoretically ambiguous under fixed notional with no gross edge. Admitting it would waste ladder alpha. C2 is a risk-control validation, not an edge claim. C3 needs a licence decision and a new data contract.
4. **Nothing indicates a forward edge.** The historical baseline is fragile (top-5 removal → PF 0.88), and Paper R2 is net-negative. Medium term, the evidence points toward **REVISE STRATEGY via new information (C3-type mechanisms)**, not more price indicators.

**Next authorized engineering (local; no boundary crossed):**
- a calibration harness comparing `replay_bracket` with the tracker on synthetic poll paths, to quantify the bar-vs-tick approximation;
- closed-bar dedup and fail-closed cooldown patches on a separate branch for owner review.

**Owner decisions requested:**
- (a) whether to schedule the dedup and cooldown fixes as a Paper production change after A38;
- (b) whether shadow-only recording of `assess_candidate` / C2 verdicts may be added to the evidence stream;
- (c) the licence check for funding data (C3).

**Unchanged:**
- A34-VS1, P2-D1, B2, MI Stage B, Paper R2, D2–D5: HOLD.
- No alpha or slots spent; no backtest; no prospective trial; no protected outcome read; no production change; nothing pushed or merged.
