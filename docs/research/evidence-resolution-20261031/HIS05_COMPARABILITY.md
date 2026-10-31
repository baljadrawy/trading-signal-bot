# HIS-05 comparability (ERG-01 workstream G1)

**Phase:** ERG-01 Evidence Resolution Gate. Documentation-only and read-only.
**Pinned tree:** `5d977f2` (= `main` `eba90dd` plus the 2026-10-31 audit package). Other commits were read with `git show`.
**Audit baseline:** HIS-05 as defined in [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](../../audits/2026-10-31-trading-system-review/RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md) (register row L204) and [REVIEWER_EVIDENCE_PACK.md](../../audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md) (L1030). That is the 2026-10-31 historical baseline. Everything below that cites code or documents was re-read for this workstream.

**Method and limits.**
- The study was read only through tracked code and Markdown, using `git show`, `git log`, `git grep` and `sed`.
- Nothing was executed. No result file, data directory or JSON output was opened.
- The study ran in 2026-06, before the 2026-08-19 research freeze (instant recorded in `research_freeze.json`). No protected content is involved.
- This document makes no profitability claim. Nothing in it authorises a test.

## 1. Bottom line

- **G1-01 · INFERRED.** HIS-05 is **MATERIALLY DIFFERENT** from the current momentum setup. Two reasons:
  - Its entry is the legacy five-indicator mean-reversion score. That score is restricted to bearish or sideways regimes and requires price below both the Bollinger middle and EMA20.
  - The current momentum setup is a bullish-regime breakout above the prior 20-bar high, with volume confirmation.
  - The two entry predicates are close to mutually exclusive by construction (section 6).
- **G1-02 · INFERRED.** HIS-05 is also **MATERIALLY DIFFERENT** from the proposed corrected 4h/1d momentum successor. That successor is a design concept only, and most of its predicates are not specified in the repository (section 5).
- **G1-03 · INFERRED.** HIS-05 is informative about one thing only: **exit geometry attached to the legacy mean-reversion entry**. Its arm A (1R / 1.8R / 2.2R with the same window-including T1 cap) shares the target ladder and the T1-cap formula with the current code. Even there it differs in stop rule, holding horizon, partial exits and fill order (section 6, rows E1–E8).
  - Its verdict "the flaw is in the entry, not the target" refers to the legacy score entry.
  - It cannot be read as evidence about momentum breakout entries, nor as evidence that the momentum family as a whole failed.
- **G1-04 · CONTRADICTORY.** The documented study parameters conflict across sources:
  - universe 595 vs 301 symbols;
  - "including delisted" is not supported by the engine;
  - "about 110k trades" is given as a total in one source and per arm in another;
  - "every arm × year gross-negative" (the audit's wording) does not match the engine, whose per-year table is printed net of a 0.6% charge (section 3.8).

## 2. Artefact inventory

| Artefact | Location | What it is | Class |
|---|---|---|---|
| Engine | `research/skill_application/scripts/target_policy_bt.py` (358 lines). The only commit is `4e3eb0a`, dated 2026-09-27 ("preserve research scripts", a bulk add); the file is unchanged at `5d977f2` | The vectorised 4-arm target-policy backtest | SOURCE_VERIFIED |
| Data downloader | `research/skill_application/scripts/dl_history.py:L2-4, L11-14 @ 4e3eb0a` | Monthly Binance spot klines, 1h/4h/1d | SOURCE_VERIFIED |
| Outputs | `out/target_policy_result.txt` and `out/target_policy_stats.json`, written by the engine (`target_policy_bt.py:L351-358 @ 4e3eb0a`) | Never tracked. `research/skill_application/out/` is ignored (`.gitignore:L62 @ 5d977f2`), and `git log --all -- '*target_policy*'` shows only the script | NOT_VERIFIED (absent) |
| Symbol list | `data/bt_symbols.txt`, read by `dl_history.py:L13 @ 4e3eb0a` | Untracked (`.gitignore:L57 @ 5d977f2`); no ref contains it | NOT_VERIFIED (absent) |
| Summary 1 | `docs/claude/strategy-history.md:L13 @ 5d977f2`, first added at `3aed157` (2026-06-26) | One-line summary: 595 coins × 9 years including delisted; 110k trades; mean-anchored worse than 1R; GROSS negative; every arm × every year negative; "the flaw is in the entry, not the target" | HISTORICAL_REPORTED |
| Summary 2 | `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md:L15 @ 5d977f2` (`f6dcae1`, 2026-10-20) | Cites summary 1; labels the result "REPORTED" and the history "research-exposed" | HISTORICAL_REPORTED |
| Summary 3 | `docs/strategy/PROFITABILITY_ROADMAP_2026-10-24.md:L67, L128 @ 4993b7d` and `L124, L188 @ a38ac44` (branch `docs/profitability-roadmap-20261024`; not in `5d977f2`) | "301 symbols, 2017–2026, about 110k trades per arm \| PF 0.806 (current 1R target); every arm × every year negative", tagged `[HR 2026-06-24]`. L21 defines `[HR]` as the owner's memory notes, "not re-verified". `a38ac44` adds "optimistic intrabar fills" | HISTORICAL_REPORTED |
| Summary 4 | `docs/audits/2026-10-11/A18_BINANCE_HISTORY_AND_CONFIRMATION_REDESIGN.md:L171 @ 8a90d4b` (branch, not in `5d977f2`) | "S03 9-year target-policy backtest, 2017–2026-06, 301 symbols" | HISTORICAL_REPORTED |
| Context mention | `docs/superpowers/specs/2026-06-25-live-learning-collector-design.md:L11 @ 44151ff` | "backtest 595 coins × 9 years + adversarial audit", in the same sentence as the 6-month regime-exposure finding of the daily ML study | HISTORICAL_REPORTED |

**G1-05 · NOT_VERIFIED.** Several items exist in no tracked file at any ref searched:
- the run date;
- the exact code version that was run;
- the symbol list;
- per-arm trade counts and per-arm, per-year results.

Blocker: the outputs and symbol list were never committed, and the engine was committed about three months after the study. That the committed engine equals the version run in 2026-06 is INFERRED from its content (four arms, 1h/4h/1d, 2017-08 → 2026-06, which matches the summaries), not verified.

## 3. Study reconstruction (from the tracked engine)

All citations in this section are `research/skill_application/scripts/target_policy_bt.py @ 4e3eb0a · SOURCE_VERIFIED` unless stated otherwise. They describe the tracked code, not a verified run.

### 3.1 Purpose and hypothesis
- **Question (L3-5).** Does anchoring T1 to a measured reversion level (Bollinger middle or EMA20) raise the T1 hit rate and the net result versus the current 1R target, in the down-market, on full history?
- **Method.** One shared entry scope keeps the comparison fair across arms.
- **Validation gate (L13-14).** Arm A runs on its natural scope, and its T1 reach is compared with the live bot's (about 25% in the down-market). The gate expects net < 0.
- **Claim of fidelity (L5).** The engine says it reproduces the live bot's logic exactly: closed candles, with windows that include the decision candle.
- The hypothesis concerns **targets**. The entry is held fixed by design.

### 3.2 Entry predicate and signal conditions
- **Regime (`regime_array`, L75-84).** The docstring says it matches `_detect_market_condition`.
  - bullish if close > EMA20 > EMA50 > EMA200;
  - bearish if the reverse holds;
  - `volatile` overrides both when ATR14 > 1.5 × its average;
  - otherwise sideways.
- **Score.** The five legacy indicators, weighted by regime (L32-34). In the bearish weights StochRSI has 0.2332 and the others 1. In the sideways weights Bollinger has 0, StochRSI 1.4176 and divergence 2. Components (`score_array`, L125-156):
  - **RSI14:** [20, 30) scores 1.5w, [30, 40) 1.0w, [40, 50) 0.3w; below 20 scores 0.
  - **Bollinger(20, 2):** only when the RSI component ≥ 1.0; position ≤ 0.3 scores w, ≤ 0.5 scores 0.5w.
  - **StochRSI:** k < 0.2 and k > d scores w; k ≥ 0.9 scores 0.3w.
  - **Bullish RSI divergence** scores w.
  - **Fibonacci proximity** to the 50-bar range.
- **Candidates (L224-227).** The score is 0 in bullish and volatile regimes. A candidate needs `down = bearish | sideways` and score ≥ `MIN_SCORE` = 3.0 (L27). The first 210 bars and the last bar are excluded.
- **Comparison scope (L273-294).** Adds two more conditions:
  - `bb_mid > entry` and `EMA20 > entry` (L279), i.e. price below both means;
  - a fixed cooldown of ceil(48 h / bar hours) bars (L228).
  - In addition, an entry is kept only if **all four** arms yield a valid T1 above entry (L280-285).
- **Validation scope (L259-271).** Arm A only, on natural candidates, with no overlap between trades.
- **Entry and stop (`levels`, L234-240).**
  - Entry is the decision-bar close.
  - Stop = max(entry − 1.5 × ATR, 20-bar low × 0.99). If that is not below entry, the stop is entry × 0.97.
  - The stop distance is capped by `MAX_SL` (L25): 1h 4%, 4h 5%, 1d 3%.

### 3.3 Timeframes
- `TFS = ["1h", "4h", "1d"]` (L23). There is no 15m.
- `research/skill_application/scripts/b2_oos.py:L3 @ 4e3eb0a · SOURCE_VERIFIED` records that no 15m history existed for this store.

### 3.4 Universe and eligibility
- **Symbols (L309-310).** Every directory under the local `bt_data` store that holds at least one zip.
- **Series minimum (L52).** A (symbol, timeframe) series needs at least 270 rows.
- **Filters.** There is no volume, liquidity, spread, listing-age or point-in-time universe filter. Volume is loaded but never used in the predicate (L125-156, L218-294).
- **Delisted coins.** There is no explicit handling. `dl_history.py:L4 @ 4e3eb0a` writes `.404` markers for months with no archive, so a symbol whose archive stops early is simply truncated.
- **G1-06 · NOT_VERIFIED.** Whether "including delisted" holds for this run cannot be checked. A18 infers delistings from file presence in the store (`A18_…:L60 @ 8a90d4b · HISTORICAL_REPORTED`), but the study's own symbol list is untracked.

### 3.5 Historical period
- **Downloads.** 2017-08 → 2026-06 monthly archives (`dl_history.py:L2, L11-12 @ 4e3eb0a · SOURCE_VERIFIED`). A18 describes the store as 2017-08 → 2026-05 (`A18_…:L48 @ 8a90d4b · HISTORICAL_REPORTED`).
- **Bucketing.** Years are assigned by the entry bar's year (L221, L286).
- **Exposure.** The window is research-exposed history (`S4_PHASE1_SCIENTIFIC_COMPARISON.md:L15 @ 5d977f2 · HISTORICAL_REPORTED`). It is not untouched data.

### 3.6 Cost assumptions
- **Flat charges.** `FEES = {gross: 0.0, net03: 0.3, net06: 0.6}` (L28), in percent of entry, subtracted once per trade (L186-192).
- **Labelling.** The 0.6% level is labelled "realistic incl slippage" (L324).
- **What is not modelled.** There is no separate fee, spread or slippage model, and stops fill exactly at the stop price (L159-175).
- **Interpretation (INFERRED).** The study is not cost-free:
  - `net03` is close to the current flat 0.30%;
  - `gross` is a pure zero-cost arm.

### 3.7 Exit variants (arms)
The arms are defined at L7-11 and L242-255. All four share the same entry and the same stop.

| Arm | T1 | T2 | T3 |
|---|---|---|---|
| A, "1R (base)" | 1R, capped at 0.99 × the 20-bar high **including the decision bar** when that high lies between entry and 1R (L246; the rolling high at L231-232) | 1.8R | 2.2R |
| B, bb_mid | Bollinger middle | upper band | upper band + 1 ATR |
| C, ema20 | EMA20 | upper band | upper band + 1 ATR |
| D, 0.5R (control) | 0.5R | 1.0R | 1.8R |

T2 and T3 are forced to be at least 0.1% above the previous target (L254).

**Exit mechanics (`simulate`, L159-175).**
- The whole position exits at a single price. There is no partial take-profit.
- After T1 the stop moves to entry (zero-cost break-even).
- After T2 the stop trails at max(T1, peak × (1 − 2.5%)).
- Reaching T3 closes the position at T3.
- Time limits: exit at the close after 24 h if only T1 has been hit, and after 48 h in every case. With 1d bars, 48 h is **two bars**.
- Within a bar, targets are evaluated from the high before the low is tested against the updated stop. A bar that touches both T1 and the original stop therefore exits at break-even, not at the stop. This is the "optimistic intrabar fills" that `PROFITABILITY_ROADMAP_2026-10-24.md:L124 @ a38ac44 · HISTORICAL_REPORTED` records.

**G1-07 · NOT_VERIFIED.** The roadmap groups "wide R:R" and "partial TP" arms with this family (`L128 @ 4993b7d`; `L188 @ a38ac44`). Neither appears in the tracked engine. If they were run, it was with other code; separate earlier wide-R:R and stop-policy scripts exist under `analyzer/backtest_part*`, but they are not the 9-year engine.

### 3.8 Reported outcomes and their evidence class

| Reported statement | Source | Class | Observation |
|---|---|---|---|
| Mean-anchored T1 (arms B and C) worse than 1R | `docs/claude/strategy-history.md:L13 @ 5d977f2` | HISTORICAL_REPORTED | No tracked output supports or refutes it |
| GROSS negative | same | HISTORICAL_REPORTED | The engine prints gross as an all-years aggregate per arm only (L324-328) |
| Every arm × every year negative | same; `PROFITABILITY_ROADMAP_2026-10-24.md:L67 @ 4993b7d` | HISTORICAL_REPORTED | The engine's per-year table is net of 0.6% (L330-339; `metrics` defaults to `net06`, L195) |
| PF 0.806 for arm A (the current 1R target) | `PROFITABILITY_ROADMAP_2026-10-24.md:L67 @ 4993b7d`; `L124 @ a38ac44` (gross column) | HISTORICAL_REPORTED, tagged `[HR 2026-06-24]`, "not re-verified" (L21) | Not in `5d977f2`; no tracked output |
| About 110k trades | strategy-history L13 ("110k trades"); roadmap L67 ("about 110k trades per arm") | HISTORICAL_REPORTED | Total vs per arm is ambiguous |
| "The flaw is in the entry, not the target" | strategy-history L13 | HISTORICAL_REPORTED | A conclusion about the legacy score entry under these exit arms |

- **G1-08 · INFERRED.** The audit paraphrase "every arm × year **gross**-negative" (HIS-05) is stronger than the tracked engine supports.
  - The engine prints per-year results only net of 0.6%. At that charge, a gross-positive cell can still print negative.
  - Per-year gross sums exist only in the untracked stats JSON (L353-357).
  - The strategy-history sentence lists "GROSS negative" and "every arm × every year negative" as separate clauses.
  - The most economical reading: the aggregate is gross-negative, and every arm-year is negative at net 0.6%. Per-year gross negativity is NOT_VERIFIED.
- **G1-04 detail · CONTRADICTORY.** Universe size is reported three ways:
  - 595 coins: strategy-history L13; S4 Phase 1 L15; `44151ff` L11;
  - 301 symbols: A18 L171 @ `8a90d4b`; roadmap L67 @ `4993b7d`;
  - 598: `b1_oos_collect.py:L3 @ 4e3eb0a`, a later script that reuses the engine.
  - The 595 figure coincides with the daily ML study's universe ("S04 ML daily study, 595 symbols", A18 L172 @ `8a90d4b`). The 44151ff sentence joins both studies. INFERRED: "595" may have been carried over from the ML study. NOT_VERIFIED which count the run used, because the engine prints its symbol count only at run time (L312).

**Overall class of HIS-05.** HISTORICAL_REPORTED.
- The engine is SOURCE_VERIFIED as committed code.
- No result is backed by a tracked artefact, which is consistent with the audit's HIS-20, where HIS-05 is listed among historical claims only.
- Nothing was recomputed here.

## 4. Current momentum setup (documented-deployed source)

All rows are SOURCE_VERIFIED at the named commit. That the running images contain this code is DOCUMENTED_ONLY (audit RT-16, RT-17).

| Element | Rule | Citation |
|---|---|---|
| Activation | Setup detection runs only if `LIVE_LEARNING_MODE`; params `MOM_BREAKOUT_N=20`, `MOM_VOL_MULT=1.2` | `analyzer/technical_analyzer.py:L68-73 @ ea8ae4f`; `shared/config.py:L76-77 @ ea8ae4f` |
| Regime | `classify_regime` on the same timeframe frame: bullish if ADX ≥ 25, EMA20 5-bar slope > 0 and close > EMA20; sideways if ADX < 20 and not high-vol (ATR% percentile over 100 bars > 0.75); else bearish (mirror) or volatile | `shared/regime.py:L10-13, L41-60 @ ea8ae4f` (unchanged since `63da7d3`) |
| Momentum predicate | regime in (None, bullish) AND close > EMA20 > EMA50 AND close > prior 20-bar high (decision bar excluded) AND volume > 1.2 × prior-20 mean | `analyzer/simple_entry.py:L28-42 @ ea8ae4f` |
| Timeframes | code default `15m,1h,4h,1d`; runtime `15m,4h,1d` | `shared/config.py:L36 @ ea8ae4f`; audit VER-06 (RUNTIME_VERIFIED, [addendum](../../audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md) L98) |
| Universe | Binance USDT pairs with status TRADING, excluding three stablecoin pairs and non-ASCII names; 24 h quote volume ≥ 10M USDT; abs 24 h change ≥ 1%; stricter 5% when BTC 4h trend is strong_bearish | `scanner/scanner_logic.py:L74-81, L96-109 @ ea8ae4f`; `shared/config.py:L162-163 @ ea8ae4f` |
| Selection gates | macro block (BTC 3-day ≤ −5% or USDT.D rising fast); spread ≤ 0.15%; valid stop; no open trade; symbol cooldown; one signal per cycle | `signal_engine/signal_logic.py:L719-861 @ ea8ae4f`; `shared/macro_context.py:L24-25, L37 @ ea8ae4f`; `shared/config.py:L165 @ ea8ae4f` |
| Stop | thesis level = breakout level; stop = min(level − 0.25 ATR, entry − 1.0 ATR); rejected if risk exceeds the per-timeframe cap (1d 3%, 4h 5%, 15m 2%) | `shared/signal_stop.py:L31-45 @ ea8ae4f`; `analyzer/technical_analyzer.py:L425-443 @ ea8ae4f` |
| Targets | T1 1R, T2 1.8R, T3 2.2R; T1 capped at 0.99 × the 20-bar high including the decision bar (W3); no `T1_CAP_POLICY` switch | `analyzer/technical_analyzer.py:L409-411, L454-467 @ ea8ae4f` |
| Exits | stop checked first at bar start; after T1 a cost-adjusted break-even stop; after T2 a 2.5% trail floored at T1; T3 closes the remainder; per-timeframe expiry (max / T1-stall / no-T1 hours): 15m 48/24/12, 4h 96/48/24, 1d 240/120/72; stop fill × (1 − 0.1%) | `shared/triple_barrier.py:L30-42, L92-121, L197-263, L320 @ bb7825f` |
| Partial exits | 25/50/25 at T1/T2/T3 | `shared/partial_exits.py:L18 @ bb7825f`; `trade_tracker/main.py:L883 @ bb7825f` |
| Costs | flat 0.30% round trip on $50, plus 0.1% stop slippage | `shared/config.py:L90 @ ea8ae4f`; `shared/triple_barrier.py:L35-36 @ bb7825f`; audit VER-19 (RUNTIME_VERIFIED, addendum L111) |

`simple_entry.py`, `regime.py`, `signal_stop.py` and `triple_barrier.py` are byte-identical from `63da7d3` to the deployed commits (`git diff --stat` is empty) · SOURCE_VERIFIED.

## 5. The corrected 4h/1d momentum successor (design concept)

The ERG brief describes the successor as a concept: breakout continuation on 4h/1d, corrected exit geometry, corrected asset selection and a frozen version identity. A repository search on `5d977f2`, `eba90dd` and the branch tips found **no document that specifies such a successor** (G1-09 · NOT_VERIFIED; blocker: no specification exists). What does exist:

| Piece | What it says or does | Citation | Class |
|---|---|---|---|
| A46 G1 T1 cap | Cap T1 only at the nearest confirmed swing high above entry among bars closed before the decision bar (high above two highs on each side), keeping the 0.99 rule; none means T1 = 1R. May be proposed as a declared correction "without a performance claim"; activation on HOLD | `docs/a46/A46_TRADE_GEOMETRY.md:L123, L158, L177 @ eba90dd` | DOCUMENTED_ONLY |
| `T1_CAP_POLICY` | `legacy_window_v1` (default) or `independent_swing_v1`; switching is "an owner-approved, declared strategy-version boundary"; absent from the deployed analyzer `ea8ae4f`; runtime unset | `shared/t1_cap.py:L22-24 @ eba90dd`; `shared/config.py:L121-124 @ eba90dd`; audit VER-05 (RUNTIME_VERIFIED, addendum L97) | SOURCE_VERIFIED (dormant) |
| A46 geometry v2 | "G3 entry + G1 targets" as the one future geometry candidate | `docs/a46/A46_TRADE_GEOMETRY.md:L157 @ eba90dd` | DOCUMENTED_ONLY |
| A45 H1–H3 gates | market state, extension cap, slot volume; modules with `enabled=False` | `shared/setup_diagnostics.py @ eba90dd`; `docs/a45/A45_SETUP_RESEARCH.md:L138-152 @ eba90dd` | SOURCE_VERIFIED (dormant) |
| A45 W3 fix, alternative form | "cap T1 by the prior 20 bars only, excluding the current bar", as a new strategy version | `docs/a45/A45_SETUP_RESEARCH.md:L191 @ eba90dd` | DOCUMENTED_ONLY |
| A45 track 2 | A **1d time-series-momentum** spec on a liquid large-cap subset with **no** intraday breakout trigger | `docs/a45/A45_SETUP_RESEARCH.md:L192 @ eba90dd` | DOCUMENTED_ONLY |
| S4 Phase 1 | Ranks "existing 15m/4h strategy + corrected T1" as "BASELINE ARM ONLY"; H3 compares legacy vs independent-swing caps; its point-in-time top-20 universe is defined for H1/H2, not for the breakout setup | `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md:L65, L71, L76 @ 5d977f2` | DOCUMENTED_ONLY |

- **G1-10 · CONTRADICTORY.** Two different W3 corrections are documented:
  - A45 L191: prior 20 bars, excluding the current bar;
  - A46 G1: confirmed swing high, which is the one implemented as `independent_swing_v1`.
  - A successor would have to declare which one it uses.
- **NOT specified anywhere (G1-09 · NOT_VERIFIED):**
  - a 4h/1d-only breakout continuation setup, or a decision to drop 15m;
  - an asset-selection change for the momentum setup;
  - successor stops, expiry or partial-exit rules;
  - a frozen successor version identity.
- For those predicates, the successor column in section 6 records "not specified".

## 6. Predicate-by-predicate comparison

**Column sources.**
- **Study:** `research/skill_application/scripts/target_policy_bt.py @ 4e3eb0a` (section 3).
- **Current momentum:** `ea8ae4f` (analyzer, signal_engine) and `bb7825f` (tracker) (section 4).
- **Successor:** the ERG brief's concept plus the pieces in section 5. "Not specified" means NOT_VERIFIED: no specification exists.

The last column compares the study with the current momentum setup. Its class is INFERRED from the SOURCE_VERIFIED rows beside it.

### 6.1 Entry, universe and sample

| # | Predicate | HIS-05 study | Current momentum | Successor concept | Study vs current |
|---|---|---|---|---|---|
| N1 | Direction | long only | long only | long (concept) | same |
| N2 | Regime classifier | EMA20 > EMA50 > EMA200 stack; volatile if ATR14 > 1.5 × average (legacy detector) | ADX(14), EMA20 5-bar slope, ATR% percentile (`classify_regime`) | not specified | different classifier |
| N3 | Regimes admitted | bearish or sideways only (score is 0 in bullish and volatile) | bullish only (or no regime) | not specified | opposite by intent |
| N4 | Trigger | weighted five-indicator score ≥ 3.0 | close > prior 20-bar high | breakout continuation (concept) | different |
| N5 | Price vs trend | below Bollinger middle **and** below EMA20 (comparison scope) | close > EMA20 > EMA50 | not specified | **mutually exclusive on the same bar** (close < EMA20 vs close > EMA20) |
| N6 | Oscillators | RSI14 bands, Bollinger position, StochRSI including the k ≥ 0.9 branch, RSI divergence, Fibonacci | none (ADX enters only via the regime) | not specified | different |
| N7 | Volume | not used | > 1.2 × prior-20 mean | not specified | different |
| N8 | Bar windows | closed bars; the 20-bar windows include the decision bar | closed bars; breakout reference excludes the decision bar; the T1-cap window includes it | the A46 G1 cap uses only bars closed before the decision bar | partially overlapping |
| N9 | Timeframes | 1h, 4h, 1d | runtime 15m, 4h, 1d | 4h, 1d | overlap on 4h and 1d only |
| N10 | Universe | every symbol in the local store with ≥ 270 rows; no liquidity or listing filter; count disputed (595 / 301) | live USDT TRADING pairs; 24 h quote volume ≥ 10M; abs change ≥ 1% | "corrected asset selection": not specified | different |
| N11 | Spread / order book | none | spread ≤ 0.15% | not specified | different |
| N12 | Macro gate | none | BTC 3-day and USDT.D block; BTC 4h strictness in the scanner | not specified (A45 H1 dormant) | different |
| N13 | Overlap and capacity | fixed cooldown of ceil(48 h / bar) bars; trades may overlap across symbols and timeframes; no capacity limit | one signal per cycle; one open trade per symbol; symbol cooldown; capacity 2 × $50 (audit runtime addendum) | not specified | different |
| N14 | Data window | 2017-08 → 2026-05/06, research-exposed history | outcomes from 2026-08-19 on, sealed FORWARD_HOLDOUT | no data | disjoint windows |

### 6.2 Exits and costs

| # | Predicate | HIS-05 study | Current momentum | Successor concept | Study vs current |
|---|---|---|---|---|---|
| E1 | Initial stop | max(entry − 1.5 ATR, 20-bar low × 0.99), else entry × 0.97; distance **capped** at 4 / 5 / 3% (1h / 4h / 1d) | min(breakout level − 0.25 ATR, entry − 1.0 ATR); trade **rejected** if risk > 2 / 5 / 3% (15m / 4h / 1d) | not specified | different |
| E2 | T1 | arm A: 1R, capped at 0.99 × the 20-bar high including the decision bar; arms B–D replace it | 1R with the same cap formula (W3) | independent swing cap (A46 G1) or prior-20 excluding the current bar (A45); not chosen | same formula for arm A; different trigger context (see G1-11) |
| E3 | T2, T3 | arm A: 1.8R, 2.2R | 1.8R, 2.2R | not specified | same for arm A |
| E4 | Stop after T1 | entry (zero-cost break-even) | cost-adjusted break-even min(T1, entry × 1.003 / 0.999) | not specified | similar, not identical |
| E5 | Stop after T2 | trail 2.5% under the peak, floored at T1 | same | not specified | same |
| E6 | Position handling | whole position exits at one price | partial 25/50/25 at T1 / T2 / T3 | not specified | different |
| E7 | Time limits | 24 h after a T1-only hit, 48 h maximum, for every timeframe (on 1d, two bars); no no-T1 expiry | per timeframe (max / T1-stall / no-T1 hours): 4h 96 / 48 / 24; 1d 240 / 120 / 72; 15m 48 / 24 / 12 | not specified | different, most strongly on 1d |
| E8 | Fill order | targets from the bar high first, then the low against the updated stop (optimistic); stops fill exactly | the stop in force at bar start is checked first; stop fill × (1 − 0.1%); live tracking polls the ticker | S4 H3 names A48 interval fills (`S4_PHASE1…:L76`) | different |
| C1 | Costs | three flat levels per trade: 0%, 0.3%, 0.6% | flat 0.30% round trip plus 0.1% stop slippage | S4 cost model for H1/H2: 0.10%/side, tiered half-spread, 0.05% slippage (`S4_PHASE1…:L78-82`) | `net03` is close to the current flat charge but omits stop slippage |

## 7. Comparability classification

| Block | Study vs current momentum | Study vs successor concept | Justification |
|---|---|---|---|
| Entry (N1–N8) | **MATERIALLY DIFFERENT** | **MATERIALLY DIFFERENT** | Only direction is shared. The study's comparison scope requires close < EMA20 and the momentum setup requires close > EMA20, so no headline-scope entry can satisfy the momentum predicate on the same bar. |
| Timeframes (N9) | PARTIALLY OVERLAPPING | PARTIALLY OVERLAPPING | 4h and 1d are common; 1h (study) and 15m (current) are not. |
| Universe and selection (N10–N13) | **MATERIALLY DIFFERENT** | NOT VERIFIED | There is no liquidity, spread, macro or capacity filter in the study. The successor's asset selection is unspecified. |
| Exit geometry (E1–E8) | PARTIALLY OVERLAPPING (arm A only) | NOT VERIFIED | Arm A shares the target ladder, the T1-cap formula and the T2 trail. It differs in stop rule, partial exits, time limits and fill order. The successor's geometry is not chosen (G1-10). |
| Costs (C1) | PARTIALLY OVERLAPPING | NOT VERIFIED | `net03` ≈ the current flat 0.30%, without stop slippage. |
| Data window (N14) | disjoint (not a predicate mismatch) | not applicable | Research-exposed 2017–2026 history vs a sealed forward window. |
| **Overall** | **MATERIALLY DIFFERENT** (G1-01) | **MATERIALLY DIFFERENT** (G1-02) | The entry is the component the study itself names as "the flaw", and it is the component that differs most. |

**G1-11 · INFERRED.** Even where the arm A formula equals the current code (E2), the T1 cap is triggered by different conditions.
- After a momentum breakout, the 20-bar high including the decision bar is usually that bar's own high. The cap therefore often fires just above entry; that is the W3 defect (`docs/a45/A45_SETUP_RESEARCH.md:L95 @ eba90dd` · DOCUMENTED_ONLY).
- For the study's below-the-means entries, the 20-bar high usually lies well above entry, so the same formula rarely binds.
- The same formula therefore cannot be assumed to produce the same exit distribution.

**Side note, not part of the brief's question (INFERRED).** The study is conceptually closer to the current **reversion** setup (`analyzer/simple_entry.py:L54-65 @ ea8ae4f`, a long oversold bounce in a sideways regime) than to momentum. Even so, the regime classifier, predicates, stop and exits all differ, so this is not a basis for transfer either.

## 8. What HIS-05 can and cannot support

**It can support, as HISTORICAL_REPORTED and not recomputed:**
- The legacy five-indicator mean-reversion score entry, taken in bearish or sideways regimes below both means on 1h/4h/1d over 2017–2026, was reported negative under four target geometries.
- For that entry, moving T1 to the means or closer (0.5R) did not rescue it.
- Weakly and conditionally on that entry: the 1R / 1.8R / 2.2R ladder with the window-including T1 cap is not by itself a source of edge.

**It cannot support:**
- **Any statement about breakout momentum entries.** The study contains none (N3–N7).
- **A conclusion that the momentum family failed.** One negative study of a different entry family is not evidence about another family. Nor is the current momentum implementation's own sealed outcome. Its status remains "no accessible economic evidence" (STR-25).
- **Inference about the current exit stack.** That stack has partial exits, per-timeframe expiry, stop-first ordering, and stop slippage (E1, E4, E6–E8).
- **Inference about the current universe or the successor's corrected asset selection** (N10–N13).
- **Confirmatory use either way.** The history is research-exposed (`S4_PHASE1_SCIENTIFIC_COMPARISON.md:L15 @ 5d977f2`). The run has no tracked outputs (G1-05) and its intrabar order is optimistic (E8).

**Where to look instead.** Earlier momentum-family evidence on other implementations is mapped in [VERSION_EVIDENCE_LINEAGE.md](VERSION_EVIDENCE_LINEAGE.md): Phase 3 momentum on the pre-`63da7d3` predicates (HIS-09). None of it evaluates the current rules.

## 9. Findings register (G1)

| ID | Class | Finding |
|---|---|---|
| G1-01 | INFERRED | HIS-05 vs current momentum: MATERIALLY DIFFERENT (sections 6–7). |
| G1-02 | INFERRED | HIS-05 vs the corrected 4h/1d successor concept: MATERIALLY DIFFERENT; most successor predicates are unspecified. |
| G1-03 | INFERRED | HIS-05 informs only exit geometry attached to the legacy mean-reversion entry; its verdict "entry is the flaw" concerns that entry. |
| G1-04 | CONTRADICTORY | The universe (595 / 301 / 598), "including delisted", trade count (total vs per arm) and gross-vs-net per-year wording conflict across sources. |
| G1-05 | NOT_VERIFIED | Run date, code version run, symbol list, per-arm counts and per-year results are not in any tracked file. Blocker: outputs and symbol list are untracked; the engine was committed on 2026-09-27. |
| G1-06 | NOT_VERIFIED | Delisted-coin coverage of this run; the engine has no explicit delisting logic. |
| G1-07 | NOT_VERIFIED | The "wide R:R" and "partial TP" arms attributed to this family are not in the engine. |
| G1-08 | INFERRED | "Every arm × year gross-negative" overstates the engine's text output, whose per-year table is net of 0.6%. |
| G1-09 | NOT_VERIFIED | No document specifies a corrected 4h/1d momentum successor (setup, universe, stops, expiry, version identity). |
| G1-10 | CONTRADICTORY | Two different W3 corrections are documented (A45 L191 vs A46 G1 / `independent_swing_v1`). |
| G1-11 | INFERRED | The arm A T1-cap formula equals the current one, but it is triggered by different conditions after a breakout entry. |

**Inconsistencies found.**
1. G1-04: three universe sizes, plus an unsupported "including delisted".
2. G1-08: the audit's "gross-negative every arm × year" wording.
3. G1-10: two W3 fixes.
4. The engine's L5 claim to replicate "the live bot exactly" refers to the 2026-06 legacy bot. Its regime detector and score are those of the legacy path (`analyzer/technical_analyzer.py:L289-306 @ 605a962` · SOURCE_VERIFIED), not the current `classify_regime` and `detect_trade_setup` path.
