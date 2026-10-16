# A46 — Trade Geometry Audit, Economics and Engineering

**Verified state:**
- Production Paper images `p1d-59297305`, schema 9, Collector `p2f-160-1bfb5f6` (1.6.0).
- The running analyzer files **and** the running tracker files (`main.py`, `triple_barrier`, `partial_exits`, `fees`, `entry_execution`, `execution`, `signal_stop`, `config`) are sha256-equal to `59297305`. Production therefore runs the **pre-A38** tracker.
- Tracker cost settings are code defaults (0.3 % round trip, 0.1 % stop slippage, $50, min notional 5).
- A44/A45 are not deployed.

**Branch:** `feature/a46-trade-geometry` from `f95e01d`:
- `3cbe7a9`: engine + tests;
- `77421ba`: A38 parity;
- this report + `docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md`.

Local only. The A38–A45 branches are unchanged.

---

## A46-A — Strategy Evolution Roadmap

`docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md`: S1–S6, each with objective, evidence, open questions, deliverables, dependencies, entry/exit, gates, risks, approvals, what is independent and what is on HOLD. A42–A45 are mapped as completed foundation. The A44 image-validation dependency sits on the critical path. No dates, no profit targets.

---

## A46-B — Trade-geometry audit (production `59297305`)

| Step | Source (`@59297305`) | Rule | Units / rounding / boundaries |
|---|---|---|---|
| Candle eligibility | `shared/ohlcv.prepare_ohlcv`, `closed_klines` | only candles with `close_time < now`; last 200 kept; gaps, duplicates, order, non-finite and impossible OHLC rejected | — |
| Entry (intended) | `technical_analyzer.py:393,459` | entry = last closed **close** | price; `round(·, 8)` |
| ATR | `_calculate_indicators` | ATR14 (`ta`, Wilder) of the closed frame | price |
| Momentum reference | `simple_entry.py:28` / `technical_analyzer.py:421` | level L = max(high of the **prior** 20 bars) | excludes the decision bar |
| Reversion reference | `technical_analyzer.py:421` | structure S = min(low of the last 20 bars) | **includes** the decision bar |
| Stop anchor | `signal_stop.py:37–38` | invalidation = ref − 0.25 ATR; stop = min(invalidation, entry − 1 ATR) | so R = max(ext + 0.25, 1) ATR for momentum (ext = (close − L)/ATR); for reversion R = max((close − S) + 0.25 ATR, 1 ATR) |
| Stop limits | `signal_stop.py:45`, `technical_analyzer.py:414` | reject if R/entry > cap (15m 2 %, 4h 5 %, 1d 3 %), `structural_risk_exceeds_cap` | the TF cap applies before any target |
| Targets | `technical_analyzer.py:443` | T1 = 1R, T2 = 1.8R, T3 = 2.2R | `round(·, 8)` |
| T1 cap | `technical_analyzer.py:453` | if 1R > H > entry (H = max(high of the last 20 bars, **including the decision bar**)) and 0.99 H > entry → T1 = 0.99 H | **binds only if R > 1/0.99 − 1 = 1.0101 %**; T2/T3 are never capped |
| Persisted | `signals` (numeric 20,8) + `features_snapshot` (stop_policy, stop_invalidation, stop_risk_pct) | as computed | — |
| Entry execution | tracker `main.py:623` → `decide_long_entry` | reject if price ≤ max(stop, invalidation); market if ≤ planned; otherwise wait (no chase, 2 h window) | — |
| Fill rebase | `main.py:663` → `rebase_long_bracket` | all levels × (fill / planned) | preserves % geometry; `round(·, 8)` |
| Partial exits | `main.py:709,955`, `partial_exits.target_distribution` | 25/50/25 at T1/T2/T3; a tranche < min notional merges into T2 ($50: none; $10: {0, 1.0, 0}) | fraction of notional |
| Break-even | `triple_barrier.py:92`, `main.py:942` | after T1: stop = min(T1, entry × 1.003 / 0.999) | uses the **0.3 %** tracker cost |
| Trailing | `triple_barrier.py:114` | after T2: max(T1, peak × (1 − 2.5 %)) | — |
| Expiry | `triple_barrier.py:38` | 15m 48/24/12 h, 4h 96/48/24 h, 1d 240/120/72 h (max / T1-stall / no-T1) | — |
| Invalidation | `main.py:890` `candle_invalidated` | before T1, a post-entry closed candle ≤ invalidation exits | — |
| Stop fill | `triple_barrier.py:308` | stop × (1 − 0.001); a gap fills at the observed price × (1 − 0.001) | — |
| Accounting | `main.py:1060` `aggregate_close`; `fees.py:12,18` | gross % stored; net = gross − 0.3 % of $50 (reports) | P&L rounded to 4 dp |
| A38 / A44 (not in production) | `fees.economic_close` | net = round(gross, 4) − 0.15 USDT; WIN / LOSS / BREAKEVEN label stored | asserted equal to the ledger's flat net (`test_27`) |

**Intended vs persisted vs executed:**
- persisted = intended (same rounding);
- executed = persisted × (fill / planned), with stops subject to slippage and gaps;
- targets fill at the exact target (Paper);
- no tick or lot rounding in Paper (an execution-realism gap; `quantize` is provided for diagnostics).

---

## A46-C — Economic geometry assessment

**Exact per-leg model:**
- fees: 0.10 % per side on each leg's value;
- half-spread on market legs (entry, stops);
- stop slippage in the fill;
- targets as resting limits.

| R (stop) | stop path | T1→BE | T2→T1 floor | T3 | min T1 for T1 path ≥ 0 | p(T1) needed* | p(T3) needed* |
|---|---|---|---|---|---|---|---|
| 0.30 % | −0.60 % | +0.03 % | +0.20 % | +0.31 % | 0.275 % | 0.96 | 0.66 |
| 0.92 % (15m median) | −1.22 % | +0.26 % | +1.06 % | +1.36 % | 0.275 % | 0.83 | 0.47 |
| 2.93 % (4h median) | −3.22 % | +0.76 % | +3.87 % | +4.78 % | 0.275 % | 0.81 | 0.40 |

\* Two-path break-even probability (that path vs the stop path). These are lower bounds on demands, not forecasts.

**Sensitivity:**

| Cost assumption | min T1 for T1 path ≥ 0 | R = 0.30 % T1 path | R = 0.92 % p(T1) |
|---|---|---|---|
| 20 bps + 5 bp half-spread | 0.319 % | net-negative | 0.86 |
| 30 bps | 0.376 % | net-negative | 0.90 |

**Findings:**
1. **A gross winner can be a net loser.** The T1→BE path is net-negative whenever T1 < 0.275 % (20 bps) / 0.376 % (30 bps). `test_13`, `test_c1`.
2. **The break-even stop is calibrated to the tracker's 0.3 %.** After T1, the 75 % remainder exits at about +0.30 % gross. Under the 20 bps baseline this over-covers; under 30 bps the T1 path nets only 0.25·T1 − 0.075 %.
3. **Payoff asymmetry.** The stop path loses R + 0.1 % slippage + costs. The T1 path wins little, so profitability rests on reaching T2/T3. Even with every winner reaching T3, the required hit rate is 40–66 %; for T1-only winners it is 81–96 %.
4. **Cost accounting.**
   - Per-leg costs total about 0.2 % for the 20 bps baseline (`test_27`: fee = 0.1 % × (notional + Σ exit values)).
   - The tracker's flat 0.3 % is about 0.1 pp more conservative.
   - Spread and slippage reduce net monotonically (`test_17_18`).
5. **C1 (self-referential T1 cap):**
   - **Source:** the analyzer's 20-bar window includes the decision bar. For momentum the breakout bar is by construction the window high whenever the cap can bind.
   - **Information:** available at decision time (it is the closed bar's own high), so this is **not** look-ahead.
   - **Effect:** T1 ∈ (entry, entry + R − ≈1 %); it never falls at or below entry (`test_12`: production T1 > entry on 120 frame×TF cases) but can sit just above it. With the high within ≈1.29 % of entry, T1 is **below net break-even** (`test_c1`).
   - **Scope:** it binds only when R > 1.0101 %, so rarely on 15m and often on 4h/1d (A42: 90/223 4h vs 27/799 15m).
   - **Reversion:** the decision bar is near the lows, so caps come from prior bars and the same defect does not apply (`test_21`).
   - **Classification:** an implementation defect relative to the rule's stated purpose (cap at recent resistance), with an economic weakness as its consequence.
6. **C2 (extension and stop):**
   - **The 0.75 ATR boundary** is where ref − 0.25 ATR = entry − 1 ATR. Beyond it, risk grows one-for-one with extension (`test_03`: R_atr = ext + 0.25).
   - **Targets scale with R**, so late entries get proportionally farther targets. Payoff ratios stay constant in R; costs fall in R units; the required move grows in ATR units.
   - **Stop caps** do not distort the structural stop. They **reject** when the structural risk exceeds the TF cap (`test_08_11`).
   - A late entry can still have acceptable R-geometry. Whether it *performs* worse is the A45 H2 hypothesis, untested.

---

## A46-D — Geometry engineering

**`shared/trade_geometry.py` (`a46-tg-v1`).** Pure, versioned, and production imports none of it (`test_30`). It reuses rather than duplicates:
- the baseline bracket comes from `strategy_math.calculate_signal_levels`, equal to the analyzer's `_calculate_levels` on **360 random frame × TF × setup cases** (`test_29`);
- gross P&L comes from the tracker's `fills_between` / `aggregate_close` / break-even rule;
- it matches the A42 counterfactual replay on the stop and T1→BE paths (`test_02`, `test_16`);
- it matches A38 `economic_close` on every path (`test_27`).

**New pieces:**
- references and T1-cap provenance;
- the per-leg ledger;
- break-even requirements;
- diagnostics and flags;
- strict `GeometryError`;
- a Decimal tick helper.

**Alternatives (disabled, versioned):**

| | Version | Rule | Decision-time inputs | Structural effect | Failure modes | Frequency |
|---|---|---|---|---|---|---|
| **G1** | `a46-g1-independent-resistance-v1` | cap T1 only at the **nearest confirmed swing high above entry** among bars closed before the decision bar (high > two highs on each side), using the production 0.99 rule; none → T1 = 1R | prior closed bars | removes the self-reference. For a fresh 20-bar breakout there is usually **no** independent resistance above entry inside the frame, so T1 = 1R (`test_05`) | ignores older resistance beyond 200 bars; fractal choice is a definition, not fitted | none (targets only) |
| **G2** | `a46-g2-cost-feasible-target-v1` | a bracket is feasible only if the **T1→break-even path** is net ≥ 0 under 25/50/25 and the stated costs (not "the whole position exits at T1") | bracket + cost model | rejects T1 < ≈0.275 % (20 bps) | ignores that T2/T3 paths may compensate; a gate, so it changes frequency | removes brackets with tiny capped T1 or thin R |
| **G3** | `a46-g3-volatility-consistent-entry-v1` | momentum: planned entry = min(close, L + 0.75 ATR), so the production stop gives exactly R = 1 ATR; the tracker's existing no-chase rule rests a limit there; stop, caps, multiples and cap rule unchanged | L, ATR, close | ≈1/3 of momentum setups (A45: ext > 0.75 ATR) get a lower planned entry and a tighter, consistent R | unfilled limits (the momentum continues without us); adverse selection of fills | lower fills; unknown without price paths |

**Tests:**
- `tests/test_a46_trade_geometry.py`: **27 tests covering the 30 required scenarios** plus the C1 property.
- `tests/experimental_modules.py`: one registry of declared experimental modules for isolation tests.

**Regressions (default suite):**

| Tree | Passed | Failed | Skipped |
|---|---|---|---|
| A45 base `f95e01d` | 864 | 0 | 793 |
| **A46** | **891** | **0** | 793 |

- **Skips:** DSN-gated DB and parity suites, unchanged. A46 changes no DB or production path, so A44's full DB matrix still stands (1627 / 1 env-mapped / 3).
- **Coverage limitations:**
  - no real price paths, so fill rates under G3 are unknown;
  - no tick/lot data;
  - the bar replay is a synthetic approximation of the poll-based tracker (calibration pending).

---

## A46-E — Scientific boundary assessment

| | Objective defect? | Changes behaviour? | New hypothesis? | Needs admission? | Leak-free evaluation? | 365-day power | Overlap |
|---|---|---|---|---|---|---|---|
| G1 | **yes** (W3 vs the rule's intent) | yes (targets only, on capped brackets) | no edge claim needed for a correction | **no**, if deployed as a declared correction with no performance claim; any claim that it *improves* returns needs an admission | yes (pure geometry) | effect limited to paths ending between a capped T1 and 1R, mostly 4h/1d → **inadequate** for a confirmatory test | none |
| G2 | no | yes (gate) | yes | yes, if used | needs counterfactual outcomes | small affected share → **inadequate** | partly A42 C1 |
| G3 | no | yes (entry price, fills) | yes | yes | needs price paths for fills → counterfactual replay calibrated | per-setup variable; A45-F estimated MDE 0.2–0.4 %/setup → **probably inadequate** | **same mechanism as A45 H2.** Test at most one of H2/G3 |

**Coherence:** G1 and G3 are coupled through T1 (the entry change moves the cap window), and G2 is an invariant check. Running three admissions would triple the FWER cost for overlapping mechanisms.

**Recommendation:**
- **One** future geometry candidate: *geometry v2* = G3 entry + G1 targets, with G2 recorded as a diagnostic, not a gate. It is evaluated against the production baseline, **instead of** a separate H2.
- G1 alone may be proposed as a declared correction (version boundary) without a performance claim.

---

## A46-F — Next development decision: **ENGINEERING CONTINUE**

**Evidence:**
- **Completed:** S1 for the active geometry. The S2 engine has baseline parity, an exact cost ledger, versioned alternatives and 30 scenarios.
- **The scientific route is blocked** by two verified prerequisites:
  1. A44 image validation and the enforce window (owner);
  2. calibration of the counterfactual replay against the poll-based tracker. Without it, G3's fills and G1's target changes cannot be evaluated free of model bias.
- Prospective power for any geometry refinement is likely inadequate. No admission is proposed now.

**Recommended next actions (in order):**
1. **Engineering (authorised locally): counterfactual calibration harness.** Feed identical synthetic tick or poll paths to the real tracker evaluation (`evaluate_trade` / `step_barrier` with the poll cadence) and to `replay_bracket` on aggregated bars. Measure the bias of exit reason and net % per path class. This is the S5 prerequisite and needs no data.
2. **Owner decisions:**
   - (a) A44 image build and validation (S6);
   - (b) whether G1 should be prepared as a declared correction version;
   - (c) whether the future single admission should be *geometry v2* or a new S4 family.
3. **Remains on HOLD:** all governed experiments, activation of G1–G3 or H1–H3, and production changes.

**Unresolved risks:**
- the counterfactual model's bias is unknown;
- the T2/T3 reach probabilities that dominate expectancy are unmeasured (protected outcomes);
- tick/lot rounding is not modelled in Paper.
