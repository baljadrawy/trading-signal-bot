# Strategies, Indicators, Calibration, Execution and Learning

*Trading Signal Bot: 2026-10-31 trading-system review. English topic document.*

## 0. Document control and how to read this document

| Item | Value |
|---|---|
| Document | `docs/audits/2026-10-31-trading-system-review/STRATEGIES_INDICATORS_CALIBRATION.md` |
| Package overview | [README.md](README.md) |
| Repository | `baljadrawy/trading-signal-bot` (private GitHub) |
| Audit and runtime inspection date | 2026-10-31 (runtime samples at 13:59Z and 14:05Z) |
| Repository reference | main = `eba90ddf4ae60641f80627472098e34650915d28` (eba90dd), at audit time and at publication time |
| Code read at (commits documented as deployed) | analyzer and signal_engine `ea8ae4f00e80c5c171536293d2df7472fa338c3e` (ea8ae4f); telegram and trade_tracker `bb7825f4744278095ef76a1d0f3b872e3043358f` (bb7825f); collector `72c0bee82b44bede5192373d18374724f11c6c3a` (72c0bee); scanner: assembled image whose blobs are listed in `deploy/baseline-2026-09-27/deployed_files.json` (8bfca77), with `shared/config.py` blob c5c03b5c from 7bf6214 |
| Repository documents read at | `ebf8d8ad2c71b1203565c10b98f22f32e0a81c05` (ebf8d8a, `feature/design-a-v1`, which is main plus 13 Design A files and has no active-path difference) |
| Production checkout | `integration/research-pipeline` at `63da7d31daef2b952c695b256f81cf174b6451a8` (63da7d3) plus uncommitted edits; not the source of any running image |
| Historical audit artefact | `research/skill_application/out/REPORT.md` at `977746f1ac5dadfd308ba4ca6f8d35ed6856dbc4` |
| Configured values | the committed non-secret snapshot `deploy/baseline-2026-09-27/config/*.nonsecret.json` (2026-09-27), taken before every current container start (analyzer, scanner, signal_engine and postgres 2026-10-19; collector 2026-10-22; telegram and trade_tracker 2026-10-27; RT-09) |
| Scope of this document | finding prefixes STR, IND, CAL, EXE, RSK and LRN, plus the contradictions CON-09, CON-11 to CON-18 and CON-20 to CON-26 |

**Status.** This is a READ-ONLY, AS-IS audit record, published as documentation only. No application code, configuration, database, container, deployment or Paper Trading state was changed, and no research, backtest, simulation, optimisation or learning run was executed to produce it. This document is **not a profitability certification**. No evidence in this audit supports a net-profitability claim for any strategy, filter or parameter described here.

**Related documents.**

- [README.md](README.md): package overview, key findings, overall confidence.
- [FULL_SYSTEM_AUDIT_AR.md](FULL_SYSTEM_AUDIT_AR.md): the complete Arabic audit (all findings).
- [RUNTIME_AND_PARITY.md](RUNTIME_AND_PARITY.md): containers, images, Compose hashes, GitHub-to-runtime parity, architecture.
- [MARKET_CONTEXT_AND_ASSET_SELECTION.md](MARKET_CONTEXT_AND_ASSET_SELECTION.md): universe, scanner selection, BTC/ETH/BTC.D/USDT.D.
- [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md): historical versions, studies, costs, governance.
- [REVIEWER_EVIDENCE_PACK.md](REVIEWER_EVIDENCE_PACK.md): self-contained English pack for independent reviewers.
- Governance: [OWNER_OPERATING_CONTRACT.md](../../governance/OWNER_OPERATING_CONTRACT.md), [EVIDENCE_LADDER_PARAMETERS.md](../../strategy/EVIDENCE_LADDER_PARAMETERS.md); historical artefact [REPORT.md](../../../research/skill_application/out/REPORT.md).

### Evidence classes

| Class | Meaning in this document |
|---|---|
| RUNTIME_VERIFIED | Directly observed on the production host during the 2026-10-31 read-only inspection (container and image metadata, Compose service list and config hashes, host Compose file and checkout git state). Point-in-time; says nothing about code behaviour inside images. |
| SOURCE_VERIFIED | Confirmed by reading source code or tracked files at a named commit. Not proof of deployed behaviour. |
| DOCUMENTED_ONLY | Stated in repository documents, deploy records or the 2026-09-27 non-secret config snapshot; not independently verified at runtime. |
| HISTORICAL_REPORTED | A past result, metric or verdict from a study, report or decision record; not recomputed in this audit; never a current operational observation. |
| INFERRED | A reasoned conclusion from other evidence; not directly observed. |
| NOT_VERIFIED | Could not be verified: evidence is missing, or the required access (database reads, `.env` values, image filesystems) was not authorized. |
| CONTRADICTORY | Two or more sources disagree. |

### Tags and standard limitations

- Each finding starts with a tag such as `[STR-07 · SOURCE_VERIFIED]`: the finding ID from the package register and its evidence class. A bare ID (for example STR-07, or RT-16 for a finding held in another document) is a cross-reference.
- Evidence lines use the pattern *source · symbol or key · commit · observed date · runtime-verified · limitations*.
- Four limitations recur and are abbreviated:
  - **L-IMG**: behaviour is SOURCE_VERIFIED at the commit documented as deployed. That the running image contains this code is DOCUMENTED_ONLY (RT-16: manifests record analyzer 46/46 and signal_engine 56/56 files equal to ea8ae4f, telegram 50/50 and trade_tracker 51/51 equal to bb7825f), and image content was NOT VERIFIED (RT-17). No code behaviour in this document is runtime-verified.
  - **L-ENV**: the value comes from the unread `.env` (via `env_file`). The 2026-09-27 snapshot value is DOCUMENTED_ONLY, and the effective runtime value is NOT VERIFIED (CAL-03).
  - **L-DB**: database contents were not read. Any table value is NOT VERIFIED (CAL-03, LRN-20).
  - **L-T1**: main and bb7825f contain `T1_CAP_POLICY`, but the documented-deployed analyzer source (ea8ae4f) does not (STR-17; image content NOT VERIFIED, RT-17). Main therefore does not describe the T1 behaviour of the documented-deployed source.
- "CURRENT-ACTIVE" below means active on the live path. The live path is presumed to be the running path (STR-03), but this is NOT VERIFIED (STR-04).

### Contents

- [1. Active decision path and rules common to the live setups](#1-active-decision-path-and-rules-common-to-the-live-setups)
- [2. Strategy inventory](#2-strategy-inventory)
- [3. Strategy cards](#3-strategy-cards)
- [4. Indicator and calibration matrix](#4-indicator-and-calibration-matrix)
- [5. Configuration precedence and database overrides](#5-configuration-precedence-and-database-overrides)
- [6. Calibration provenance, validation methodology and version boundaries](#6-calibration-provenance-validation-methodology-and-version-boundaries)
- [7. Paper execution lifecycle](#7-paper-execution-lifecycle)
- [8. Risk controls and portfolio limits](#8-risk-controls-and-portfolio-limits)
- [9. Learning and optimisation](#9-learning-and-optimisation)
- [10. Contradictions in this area](#10-contradictions-in-this-area)
- [11. Not verified in this area and related open questions](#11-not-verified-in-this-area-and-related-open-questions)

## 1. Active decision path and rules common to the live setups

### 1.1 Which selector runs

- [STR-01 · SOURCE_VERIFIED] `signal_engine/main.py:173-176` calls `find_best_signal_live` when `LIVE_LEARNING_MODE` is set, and the legacy `find_best_signal` otherwise. The code default is false (`shared/config.py:74` at ea8ae4f). The flag name is misleading: it runs no learning and reads no learner table. It selects the rule-based setups (STR-07, STR-08) together with the `fixed_execution_quality_v1` selection policy (STR-13).
  *Evidence:* `signal_engine/main.py:173-176`, `shared/config.py:74` · `LIVE_LEARNING_MODE`, `find_best_signal_live`, `find_best_signal` · ea8ae4f · observed n/a · runtime-verified: no · limits: L-IMG.
- [STR-02 · DOCUMENTED_ONLY] The 2026-09-27 non-secret config snapshot records `LIVE_LEARNING_MODE=true`.
  *Evidence:* `deploy/baseline-2026-09-27/config/*.nonsecret.json` · `LIVE_LEARNING_MODE` · documents at ebf8d8a · observed n/a · runtime-verified: no · limits: the snapshot predates every current container start (2026-10-19 to 2026-10-27, RT-09).
- [STR-03 · INFERRED] The live path is presumed active. The snapshot predates every current container start (2026-10-19 to 2026-10-27, RT-09), but the `.env` modification time (read as metadata only) predates the snapshot, so the snapshot values are plausibly still current.
  *Evidence:* snapshot date versus `.env` modification time · n/a · observed 2026-10-31 (metadata only) · runtime-verified: no · limits: `.env` content was never read.
- [STR-04 · NOT_VERIFIED] The actual runtime value of `LIVE_LEARNING_MODE`. Verifying it requires authorization, either a redacted `.env` allow-list (OQ-02) or a container environment read.
  *Evidence:* none available · limits: every statement in this document about "the live path" is conditional on this flag.

### 1.2 Rules common to the live setups

- [STR-05 · SOURCE_VERIFIED] The following apply to both live setups (momentum and reversion):
  - **Bars:** closed bars only; long-only.
  - **Timeframes:** taken from `config.TIMEFRAMES`, code default `15m,1h,4h,1d`. `TIMEFRAMES_LL` is defined but nothing reads it (CON-15).
  - **Universe:** the scanner list (UNI-01, UNI-05, UNI-08, UNI-09; detail in [MARKET_CONTEXT_AND_ASSET_SELECTION.md](MARKET_CONTEXT_AND_ASSET_SELECTION.md)):
    - Binance Spot USDT pairs with status TRADING;
    - 24h quote volume ≥ 10M;
    - absolute 24h change ≥ 1%, raised to ≥ 5% when the scanner BTC trend is strong_bearish (BTC down more than 3% over the last 10 closed 4h bars);
    - minus `symbol_blacklist`. The whitelist and approval path is dead code.
  - **Targets:** set by `technical_analyzer._calculate_levels`: T1 = +1R, T2 = +1.8R, T3 = +2.2R, with the W3 cap on T1 (STR-21).
  - **Stops:** set by `shared/signal_stop.py:plan_signal_stop`. A setup is rejected when its stop risk exceeds the timeframe cap: 15m 2%, 1h 4%, 4h 5%, 1d 3%.
  *Evidence:* `shared/config.py`, `analyzer/simple_entry.py`, `analyzer/technical_analyzer.py`, `shared/signal_stop.py` · `TIMEFRAMES`, `_calculate_levels`, `plan_signal_stop` · ea8ae4f · observed n/a · runtime-verified: no · limits: L-IMG, L-ENV for `TIMEFRAMES`, L-T1.
- [STR-06 · DOCUMENTED_ONLY] The 2026-09-27 snapshot sets timeframes 15m, 4h, 1d. The effective value is NOT VERIFIED.
  *Evidence:* `deploy/baseline-2026-09-27/config/*.nonsecret.json` · `TIMEFRAMES` · documents at ebf8d8a · runtime-verified: no · limits: L-ENV.
- [STR-23 · DOCUMENTED_ONLY] The live rules are hand-set. `docs/indicator_regime_execution_review_2026-08-19.md` calls them "operational starting points, not evidence of edge".
  *Evidence:* that review document · documents at ebf8d8a · runtime-verified: no · limits: documents are not calibration evidence.
- [STR-24 · SOURCE_VERIFIED] The only evidence for the live rules is mechanics tests: `test_simple_entry` (7 tests), `test_regime` (2), `test_signal_stop` (4), `test_indicators` (7). None of them is an economic test.
  *Evidence:* `tests/` · test files named above · ebf8d8a tree · runtime-verified: no · limits: tests check mechanics only.
- [STR-25 · INFERRED] No pre-freeze economic evidence exists for these exact rules. Commit 63da7d3, which introduced them, is dated on the research-freeze date (2026-08-19) and precedes the recorded freeze boundary (FORWARD_HOLDOUT boundary recorded in `research/governance/research_freeze.json`). All outcome evidence for the current rules therefore lies in the sealed FORWARD_HOLDOUT, which this audit did not read.
  *Evidence:* commit date of 63da7d3 versus the recorded freeze boundary · runtime-verified: no · limits: no post-freeze outcome, count or timestamp was read or is reported here.

## 2. Strategy inventory

Every strategy, gate or selection family found in the audited code and documents. Rule content is SOURCE_VERIFIED at the cited commit unless the class says otherwise; activation status carries its own evidence class.

The strategy_version / APP_VERSION actually emitted by the running services is NOT VERIFIED (CAL-10). The code default APP_VERSION is `sb-2026.06` (CAL-09).

| ID · class | Family | Status | Strategy / version identifier | Source file | Activation evidence |
|---|---|---|---|---|---|
| [STR-07 · SOURCE_VERIFIED] | Momentum breakout setup | CURRENT-ACTIVE on the live path | setup id `momentum` (`close_above_ema20_ema50_breakout_with_volume`); selection policy `fixed_execution_quality_v1`; rules introduced at 63da7d3 | `analyzer/simple_entry.py:28-44` (ea8ae4f) | STR-01 switch (SOURCE_VERIFIED, default false); STR-02 snapshot true (DOCUMENTED_ONLY); STR-03 presumed (INFERRED); STR-04 runtime NOT VERIFIED |
| [STR-08 · SOURCE_VERIFIED] | RSI / Bollinger reversion setup | CURRENT-ACTIVE on the live path | setup id `reversion` (`rsi_oversold_bounce_near_lower_bollinger`); `fixed_execution_quality_v1`; 63da7d3 | `analyzer/simple_entry.py:54-58` (ea8ae4f) | as STR-07 |
| [STR-09 · SOURCE_VERIFIED] | Per-symbol regime routing | CURRENT-ACTIVE: computed on every analysis; gates the live setups | no separate identifier; part of the 63da7d3 rule set | `shared/regime.py:10-60` (63da7d3, byte-identical at ea8ae4f) | live-path dependence as STR-01 to STR-04 |
| [STR-11 · SOURCE_VERIFIED] | Macro gate (BTC and USDT.D veto) | CURRENT-ACTIVE on the live path | no separate identifier; `shared/macro_context.py` blob 9099d1d1 | `shared/macro_context.py:10-41, 96-110` | MKT-04 (DOCUMENTED_ONLY: active only if LIVE_LEARNING_MODE=true) |
| [STR-13 · SOURCE_VERIFIED] | Live candidate ranking | CURRENT-ACTIVE on the live path | `fixed_execution_quality_v1`; A44 "production_parity" | `signal_engine/signal_logic.py:287-293` | as STR-07 |
| [STR-14 · SOURCE_VERIFIED] | Legacy indicator score | DISABLED as a decision path; still computed on every pass | `legacy_score_v1` | `analyzer/technical_analyzer.py:323-402` | STR-01: the legacy selector runs only when LIVE_LEARNING_MODE is false |
| [STR-15 · SOURCE_VERIFIED] | Legacy decision gate | INACTIVE (legacy path only) | gate of `legacy_score_v1` | `signal_engine/signal_logic.py:570-575` | STR-01 |
| [STR-16 · SOURCE_VERIFIED] | Legacy-only filters (4h ban, 1d raw-score rule, stoch>0, majority filters, trend_ok, BTC-crash pause, bonuses, daily caps) | INACTIVE (legacy path only) | none | `signal_engine/signal_logic.py:631`, around `:655`, `:671` | STR-01 |
| [STR-17 · SOURCE_VERIFIED] | T1 cap policy | Documented-deployed analyzer source (ea8ae4f): hard-coded legacy cap; policy flag absent | `legacy_window_v1` / `independent_swing_v1` (`T1_CAP_POLICY`, commit a4a7561) | `analyzer/technical_analyzer.py:463-467` (ea8ae4f); `shared/t1_cap.py` (bb7825f, main) | flag present at bb7825f and main, absent at ea8ae4f |
| [STR-18 · SOURCE_VERIFIED] | Learned gates (throttle cells) | DISABLED | `learned_gates` rows carry `strategy_version` (default `legacy`) and `learning_run_id` | `research/continuous_learner.py`; `signal_engine/signal_logic.py:27-28, 741-743` | STR-19 (DOCUMENTED_ONLY: flag false in snapshot; learner stopped since 2026-08-17) |
| [STR-20 · SOURCE_VERIFIED] | Earlier 15m/4h momentum and reversion family | HISTORICAL, superseded at 63da7d3 | pre-63da7d3 rules | code before 63da7d3 | not applicable |
| [STR-26 · SOURCE_VERIFIED] | A42 C1 cost-per-risk gate | DORMANT | `a42-sq-v1` | `shared/signal_quality.py` | `enabled=False`; imported by no service |
| [STR-28 · SOURCE_VERIFIED] | A42 C2 BTC-beta (correlation) cap | DORMANT | `CorrelatedExposurePolicy` in the same module; separate version identifier not stated in the sources | `shared/signal_quality.py` | `enabled=False`; not imported by any deployed entrypoint |
| [STR-29 · DOCUMENTED_ONLY] | A42 C3 funding veto | PROPOSED, specification only | not stated | specification only (no code) | data licence on HOLD |
| [STR-30 · SOURCE_VERIFIED] | A44 rankers and the S3 selector/shadow | DORMANT | `execution_quality_v2`, `cost_per_risk_v1`; `s3-sel-v1`, `s3-shadow-v1` | `shared/candidate_selection.py`; S3 policy and sidecar | `S3Policy.enabled=False`; sidecar only with `--enable`; no Compose service; STR-31 NOT VERIFIED whether it ever ran |
| [STR-33 · SOURCE_VERIFIED] | A43 signal integrity | FLAGGED OFF | `SIGNAL_INTEGRITY_MODE` (`off` / `enforce`) | `shared/signal_identity.py`; `shared/config.py:118` (ea8ae4f) | default off; not set in Compose; STR-34 (DOCUMENTED_ONLY: no enforce window authorized) |
| [STR-35 · SOURCE_VERIFIED] | A45 setup diagnostics H1 to H3 | DORMANT / RESEARCH | `a45-sd-v1` | `shared/setup_diagnostics.py` | `enabled=False` |
| [STR-36 · SOURCE_VERIFIED] | A46 trade geometry G1 to G3 | DORMANT | `a46-tg-v1` | `shared/trade_geometry.py` | imported by no service; STR-37 (INFERRED: unimportable in the ea8ae4f images) |
| [STR-38 · SOURCE_VERIFIED] | S4 mechanisms M1 to M5 and Phase-1 H1 to H3 | RESEARCH-ONLY, NOT TESTED | `s4-mech-v1` | `research/mechanisms/` | `simulate.run` refuses without a `DatasetPermission` |
| [STR-39 · SOURCE_VERIFIED] | Design A v1.0 (BTC weekly SMA200 long/cash) | RESEARCH-ONLY; evaluation not authorized | Design A v1.0 | `research/design_a/` on `feature/design-a-v1` at ebf8d8a (not on main) | no service; branch unmerged |
| [STR-40 · DOCUMENTED_ONLY] | Historical research families (cross-sectional momentum long/short, funding carry, SMC/ICT/Ichimoku and others) | HISTORICAL | not applicable | `analyzer/MODEL_FROZEN_SPEC.md`; `analyzer/backtest_part*` | research-only; not imported by any service |

## 3. Strategy cards

Each card uses the same seventeen fields. "Not applicable" means the field does not exist for that family. NOT VERIFIED means the value exists but could not be checked.

### 3.1 Momentum breakout setup (STR-07)

[STR-07 · SOURCE_VERIFIED] The live momentum setup: a long-only breakout entry in a bullish regime, with stops, targets and exits shared with the reversion setup.

| Field | Value |
|---|---|
| Source file | Entry: `analyzer/simple_entry.py` lines 28-44. Stop: `shared/signal_stop.py:16-46`. Targets: `analyzer/technical_analyzer.py:454-467`. All at ea8ae4f. Exits: `shared/triple_barrier.py`, `shared/partial_exits.py` in the tracker at bb7825f. |
| Function/class | `detect_trade_setup`; `plan_signal_stop`; `TechnicalAnalyzer._calculate_levels`; selection via `signal_logic.find_best_signal_live` and `_fixed_candidate_key` |
| Strategy/version identifier | Setup id `momentum`, name `close_above_ema20_ema50_breakout_with_volume`. Selection policy `fixed_execution_quality_v1`. Rules introduced at 63da7d3 (2026-08-19). Runtime strategy_version is NOT VERIFIED (CAL-10). |
| Status | CURRENT-ACTIVE only when `LIVE_LEARNING_MODE=true`. Switch: SOURCE_VERIFIED, default false (STR-01). Snapshot true: DOCUMENTED_ONLY (STR-02). Presumed active: INFERRED (STR-03). Runtime value NOT VERIFIED (STR-04). |
| Hypothesis | Breakouts continue in an up-trend. |
| Entry logic | All of the following must hold:<br>• regime is bullish (STR-09);<br>• close > EMA20 > EMA50;<br>• close > max(high of the prior 20 bars);<br>• volume > 1.2 × mean(volume of the prior 20 bars).<br>Closed bars only; the breakout and volume baselines exclude the current bar (EXE-05). The candidate must then pass the signal-engine gates in order (EXE-01): macro gate; order book valid with a finite spread ≤ 0.15%; `stop_valid`; no open trade and the 2 h symbol cooldown; learned gate (off); ranking by `_fixed_candidate_key`; one signal per cycle of about 60 s. Planned entry is the last closed close; the tracker fills at the observed last-trade price only if it is ≤ planned, otherwise it waits up to 2 h (EXE-07). |
| Exit logic | Invalidation = breakout level − 0.25·ATR14; stop = min(invalidation, entry − ATR14). The setup is rejected if stop risk exceeds the timeframe cap (15m 2%, 1h 4%, 4h 5%, 1d 3%). Targets T1 = +1R, capped at 0.99 × the 20-bar high including the decision bar (W3, STR-21); T2 = +1.8R; T3 = +2.2R. Partial exits 25/50/25 at T1/T2/T3; after T1 a net break-even stop at about entry × 1.004; after T2 a trailing stop max(T1, peak × 0.975); stop fill min(stop, observed tick) × 0.999. Before T1, a closed bar at or below the invalidation level exits at the current price. Time stops (maximum / stalled after T1 / no T1): 15m 48/24/12 h, 4h 96/48/24 h, 1d 240/120/72 h. No emergency stop (EXE-10, EXE-11). |
| Timeframes | `config.TIMEFRAMES`: code default 15m,1h,4h,1d; snapshot 15m,4h,1d (DOCUMENTED_ONLY, STR-06); effective NOT VERIFIED. Every timeframe is an independent candidate; there is no multi-timeframe confirmation on the live path (IND-04). |
| Market-context dependencies | The per-symbol regime must be bullish (STR-09). The macro gate can block the whole cycle: BTC ≤ −5% over 18 closed 4h bars, USDT.D ≥ +0.5 pp above its 3-day mean, or macro data older than 2 h (STR-11). The scanner universe filter tightens to an absolute 24h move ≥ 5% when the scanner BTC trend is strong_bearish (MKT-01). Context has no effect on sizing or exits (MKT-12). |
| Indicators | EMA20, EMA50, 20-bar high, 20-bar mean volume, ATR14 (IND-01). Via the regime: ADX14, the EMA20 5-bar slope, and the 100-bar ATR/close percentile. |
| Thresholds | MOM_BREAKOUT_N = 20; MOM_VOL_MULT = 1.2; stop buffer 0.25·ATR14; ATR stop multiple 1.0; timeframe risk caps 2/4/5/3%; targets 1.0/1.8/2.2R; T1 cap factor 0.99; spread ≤ 0.15%. |
| Weights | None on the live path (no score threshold). `indicator_weights` affect only the recorded total_score, which orders candidates within a symbol before the LIMIT 200 truncation (LRN-16, LRN-17). |
| Default vs effective runtime value | Code defaults 20 and 1.2; snapshot 20 and 1.2 (DOCUMENTED_ONLY). Effective value NOT VERIFIED (L-ENV). Hard-coded parts (stop buffer, caps, target multiples) equal the code, subject to L-IMG. |
| DB overrides | None (CAL-01). |
| Calibration provenance | Hand-set, "operational starting points, not evidence of edge" (STR-23); class M (manual). T3 = 2.2R is class RC (code comment "0/168 touched 3R", 2026-04-27). The stop caps are class RC (code comment cites "2433 trades"). |
| Validation evidence | Mechanics tests only (STR-24). No pre-freeze economic evidence for these exact rules (STR-25). |
| Scientific weaknesses | W3: the cap pins T1 to the breakout bar's own wick (STR-21). EMA200 is immature (STR-22). A same-bar re-fire after the 2 h cooldown is possible on 4h/1d (EXE-17). Candle age is never checked (EXE-09). One order-book snapshot is reused across timeframes (EXE-05). The macro input cannot be replayed (STR-12). Execution is simulated on last trades (EXE-20). Modelled costs are below the research baselines (EXE-15). |

[STR-22 · INFERRED] EMA200 values are immature because only 200 bars are fetched; this is listed by the strategy investigation as a limitation of the momentum setup.
*Evidence:* `analyzer/technical_analyzer.py` (200 closed bars per timeframe; UNI-12) · EMA200 · ea8ae4f · runtime-verified: no · limits: inference from the fetch size.

*Evidence (card):* `analyzer/simple_entry.py:28-44`, `shared/signal_stop.py:16-46`, `analyzer/technical_analyzer.py:454-467` · `detect_trade_setup`, `plan_signal_stop`, `_calculate_levels` · ea8ae4f (exits bb7825f) · observed n/a · runtime-verified: no · limits: L-IMG, L-ENV, L-T1.

### 3.2 RSI / Bollinger reversion setup (STR-08)

[STR-08 · SOURCE_VERIFIED] The live reversion setup: a long-only oversold-bounce entry in a sideways regime. Stops, targets and exits are the same as the momentum setup, except for the invalidation level.

| Field | Value |
|---|---|
| Source file | Entry: `analyzer/simple_entry.py:54-58` (ea8ae4f). Stop: `shared/signal_stop.py:16-46`. Targets: `analyzer/technical_analyzer.py:454-467`. Exits: tracker at bb7825f. |
| Function/class | `detect_trade_setup`; `plan_signal_stop`; `TechnicalAnalyzer._calculate_levels` |
| Strategy/version identifier | Setup id `reversion`, name `rsi_oversold_bounce_near_lower_bollinger`. Selection policy `fixed_execution_quality_v1`. Rules introduced at 63da7d3. Runtime strategy_version is NOT VERIFIED (CAL-10). |
| Status | Same activation evidence as STR-07: CURRENT-ACTIVE only when `LIVE_LEARNING_MODE=true` (STR-01 to STR-04). |
| Hypothesis | Oversold bounces in a range. |
| Entry logic | All of the following must hold:<br>• regime is sideways (STR-09);<br>• RSI14 < 35;<br>• close > previous close;<br>• close > open;<br>• Bollinger %b (20, 2σ) ≤ 0.20.<br>Closed bars only; then the same ordered signal-engine gates, ranking and tracker entry rules as STR-07 (EXE-01, EXE-07). |
| Exit logic | Invalidation = min(low of the last 20 bars) − 0.25·ATR; stop = min(invalidation, entry − ATR). Timeframe risk caps, targets, the W3 T1 cap, partial exits, break-even, trailing stop, invalidation exit and time stops are identical to STR-07 (EXE-10, EXE-11). |
| Timeframes | As STR-07 (code default 15m,1h,4h,1d; snapshot 15m,4h,1d; effective NOT VERIFIED). |
| Market-context dependencies | The per-symbol regime must be sideways (STR-09). The macro gate and the scanner BTC filter apply as in STR-07. No effect on sizing or exits. |
| Indicators | RSI14, Bollinger(20, 2σ) %b, ATR14, the 20-bar low; via the regime: ADX14 and the 100-bar ATR/close percentile. |
| Thresholds | REV_RSI = 35; REV_BB_MAX_POSITION = 0.20; stop buffer 0.25·ATR; ATR multiple 1.0; caps 2/4/5/3%; targets 1.0/1.8/2.2R; T1 cap factor 0.99. |
| Weights | None on the live path (as STR-07). |
| Default vs effective runtime value | Code defaults 35 and 0.20. `.env.example` sets REV_BB_MAX_POSITION 0.20, cited via `docs/ops/ENV_EXAMPLE_REVIEW_2026-10-18.md`. Snapshot 35 and 0.2 (DOCUMENTED_ONLY). Effective NOT VERIFIED (L-ENV). |
| DB overrides | None (CAL-01). |
| Calibration provenance | Hand-set (STR-23); class M. Target and stop-cap provenance as STR-07. |
| Validation evidence | Mechanics tests only (STR-24); no pre-freeze economic evidence for these exact rules (STR-25). |
| Scientific weaknesses | The same T1 cap and W3 behaviour as STR-07 (STR-21); same-bar re-fire (EXE-17); candle age unchecked (EXE-09); last-trade simulated execution (EXE-20); costs below the research baselines (EXE-15). |

*Evidence (card):* `analyzer/simple_entry.py:54-58`, `shared/signal_stop.py:16-46` · `detect_trade_setup` · ea8ae4f · observed n/a · runtime-verified: no · limits: L-IMG, L-ENV, L-T1.

### 3.3 Per-symbol regime routing (STR-09, STR-10)

[STR-09 · SOURCE_VERIFIED] `shared/regime.py:classify_regime` (lines 10-60) classifies each symbol's own bars and decides which live setup, if any, may fire. It was introduced at 63da7d3 and is byte-identical at ea8ae4f.

| Field | Value |
|---|---|
| Source file | `shared/regime.py:10-60` (63da7d3; byte-identical at ea8ae4f); called from `analyzer/simple_entry.py:detect_trade_setup` |
| Function/class | `classify_regime` |
| Strategy/version identifier | No separate identifier; part of the 63da7d3 rule set. |
| Status | CURRENT-ACTIVE. It is computed on every analysis and stored in `analysis_results.analysis_data` (regime, market_condition). Its decision effect on the live setups depends on the live path (STR-01 to STR-04). |
| Hypothesis | Not a standalone hypothesis. It routes trend-following entries to trending markets and mean-reversion entries to ranges. |
| Entry logic | • bullish = ADX14 ≥ 25 AND 5-bar EMA20 slope > 0 AND close > EMA20<br>• bearish = the mirror image (ADX14 ≥ 25, negative slope, close < EMA20)<br>• sideways = ADX14 < 20 AND the 100-bar percentile of ATR/close ≤ 0.75<br>• volatile = everything else<br>Momentum fires only if bullish and reversion only if sideways. Bearish and volatile produce no setup. By construction, ADX between 20 and 25, or ADX below 20 with an ATR/close percentile above 0.75, falls into volatile. |
| Exit logic | None directly. The trade type it selects sets the invalidation level (prior 20-bar high for momentum, 20-bar low for reversion) and therefore the stop structure (MKT-09). |
| Timeframes | Each symbol's own bars on each candidate timeframe. |
| Market-context dependencies | None. No BTC or dominance input; it is per-symbol only. |
| Indicators | ADX14; EMA20 and its 5-bar slope; close versus EMA20; ATR14/close percentile over 100 bars. |
| Thresholds | ADX 25 (trend) and 20 (range); slope sign over 5 bars; ATR/close percentile ≤ 0.75 over 100 bars. |
| Weights | None. |
| Default vs effective runtime value | Hard-coded and not env-settable; effective equals the code, subject to L-IMG. |
| DB overrides | None. |
| Calibration provenance | Class M; no calibration dataset is documented (CAL-05). |
| Validation evidence | `test_regime` (2 tests); no economic validation (STR-10). |
| Scientific weaknesses | No economic validation. The definition changed at 63da7d3 from the earlier EMA-stack and ATR rule (STR-20), so studies that predate 63da7d3 did not test it. |

[STR-10 · DOCUMENTED_ONLY] "Validated" in the title of the regime commit means point-in-time and input validation, not economic validation.
*Evidence (card):* `shared/regime.py:10-60` · `classify_regime` · 63da7d3 / ea8ae4f · observed n/a · runtime-verified: no · limits: L-IMG.

### 3.4 Macro gate (STR-11, STR-12)

[STR-11 · SOURCE_VERIFIED] A cycle-wide veto on all live candidates, driven by BTC and USDT.D. The full derivation of its inputs is in [MARKET_CONTEXT_AND_ASSET_SELECTION.md](MARKET_CONTEXT_AND_ASSET_SELECTION.md) (MKT-03, MKT-07, MKT-11, MKT-13 to MKT-15).

| Field | Value |
|---|---|
| Source file | `shared/macro_context.py` lines 10-41 and 96-110. Blob 9099d1d1 is identical at 63da7d3, ea8ae4f, bb7825f and main. Called from `signal_engine/signal_logic.py:find_best_signal_live`. |
| Function/class | `MacroContext`; `should_block_now`; `should_block(btc_trend, usdtd_trend)`; inputs `_btc_eth_change` (Binance) and `_cg_global` (CoinGecko `/api/v3/global`) |
| Strategy/version identifier | No separate identifier; part of the 63da7d3 rule set. |
| Status | CURRENT-ACTIVE on the live path only. The gate is active only if LIVE_LEARNING_MODE=true (MKT-04, DOCUMENTED_ONLY); runtime NOT VERIFIED (STR-04). |
| Hypothesis | Not stated in the audit sources. It acts as a risk-off veto on all long entries. |
| Entry logic | All candidates in a cycle are blocked if any of these hold:<br>• the BTC 4h change over 18 closed bars is ≤ −5% (strong_bear);<br>• USDT.D minus its 3-day mean is ≥ +0.5 pp (rising_fast);<br>• macro data are older than 2 h (fail-closed).<br>A block returns no signal, and every candidate is marked `macro_block` (MKT-11). |
| Exit logic | None: no macro input reaches the tracker or exits (MKT-12). |
| Timeframes | BTC uses 4h bars: Δ = c₋₁ versus c₋₁₈, 17 intervals = 68 h. USDT.D is refreshed at most hourly against its 3-day mean. The gate applies to candidates on every timeframe. |
| Market-context dependencies | BTCUSDT (Binance klines), USDT.D (CoinGecko), the `macro_history` table. |
| Indicators | BTC percentage change over 18 closed 4h bars; the USDT.D delta versus its 3-day mean. |
| Thresholds | BTC labels: ≤ −5 strong_bear, < −1 bear, > 1 bull, > 5 strong_bull. USDT.D labels: ≥ 0.5 pp rising_fast, > 0.05 rising, < −0.05 falling, else flat. Settings: USDTD_SPIKE_PP 0.5; FLAT_EPS 0.05 (hard-coded); MACRO_CACHE_HOURS 1; MACRO_MAX_STALE_HOURS 2. |
| Weights | None. |
| Default vs effective runtime value | Code defaults 0.5, 1, 2; snapshot 0.5, 1, 2 (DOCUMENTED_ONLY); effective NOT VERIFIED (L-ENV). FLAT_EPS equals the code (L-IMG). |
| DB overrides | None; `macro_history` holds data, not settings. |
| Calibration provenance | Class M; no calibration dataset or validation methodology documented (CAL-05, CAL-07). |
| Validation evidence | `test_macro_context` (mechanics only). No economic validation of the gate itself. |
| Scientific weaknesses | The input is not point-in-time (STR-12). Fail-open holes: a missing key reads as 0.0 ("falling"), and an empty history reads "flat" (MKT-15). Decisions can use state up to 2 h old, about 6 h of signal age at worst (MKT-14). Two BTC-trend definitions share labels (CON-27). The docstring's "daily snapshot" does not match the hourly overwrite (CON-28). |

[STR-12 · INFERRED] The CoinGecko input is not point-in-time, so the gate cannot be replayed historically. Its value as a filter has therefore never been measured.
*Evidence (card):* `shared/macro_context.py:10-41, 96-110` · `should_block`, `_btc_eth_change`, `_cg_global` · blob 9099d1d1 (63da7d3, ea8ae4f, bb7825f, main) · runtime-verified: no · limits: L-IMG, L-ENV.

### 3.5 Live candidate ranking (STR-13)

[STR-13 · SOURCE_VERIFIED] On the live path, candidates are not ranked by setup strength. They are ordered by an execution-quality key, and only one is emitted per cycle.

| Field | Value |
|---|---|
| Source file | `signal_engine/signal_logic.py:287-293` (`_fixed_candidate_key`); candidate query `signal_engine/main.py:146-155`; cooldown `signal_engine/signal_logic.py:25` (`COOLDOWN_SQL`). All at ea8ae4f. |
| Function/class | `_fixed_candidate_key`; `find_best_signal_live` |
| Strategy/version identifier | `fixed_execution_quality_v1`; equal to the A44 "production_parity" policy. |
| Status | CURRENT-ACTIVE on the live path (STR-01 to STR-04). |
| Hypothesis | Not applicable. It orders by execution quality, not by a signal-strength hypothesis. |
| Entry logic | The candidate set is analysis rows ≤ 30 min old with no open trade, read with `ORDER BY symbol, total_score DESC LIMIT 200`. LIMIT 200 is applied after ordering by symbol, so the set is truncated alphabetically (UNI-16). Survivors of the gates are sorted by min(spread, −24h quote volume, symbol, timeframe): tightest relative spread first, then highest 24h quote volume, then symbol, then timeframe. One signal is emitted per cycle of about 60 s. A 2 h symbol cooldown follows any signal. |
| Exit logic | Not applicable. |
| Timeframes | All candidate timeframes compete in one ranking. |
| Market-context dependencies | None. |
| Indicators | `spread_pct` from the 20-level order book; 24h quote volume. |
| Thresholds | One signal per cycle; LIMIT 200; 30 min row age; 2 h cooldown (hard-coded). |
| Weights | `indicator_weights` shape total_score, which orders timeframes within a symbol before truncation (LRN-16). |
| Default vs effective runtime value | Hard-coded; effective equals the code, subject to L-IMG. |
| DB overrides | None. |
| Calibration provenance | Class M. |
| Validation evidence | `test_fixed_candidate_policy`, `test_a44_selection_pipeline`, `test_decision_parity_before_after`. Synthetic tests show that ranking cannot change signal frequency (STR-32). |
| Scientific weaknesses | It ranks execution quality, not signal strength. Alphabetical truncation and lexical tie-breaks create a selection bias (HIS-28). It systematically favours the deepest majors when they have a valid setup (UNI-19). |

*Evidence (card):* `signal_engine/signal_logic.py:25, 287-293`, `signal_engine/main.py:146-155` · `_fixed_candidate_key`, `COOLDOWN_SQL` · ea8ae4f · runtime-verified: no · limits: L-IMG.

### 3.6 Legacy indicator score, decision gate and filters (STR-14, STR-15, STR-16)

[STR-14 · SOURCE_VERIFIED] `legacy_score_v1` (`analyzer/technical_analyzer.py:_calculate_scores`, lines 323-402 at ea8ae4f) is disabled as a decision path: the legacy `find_best_signal` runs only when `LIVE_LEARNING_MODE` is false. The score is still computed on every pass.

Components:
- RSI: < 30 → 1.5w; 30–40 → 1.0w; 40–50 → 0.3w.
- BB position: ≤ 0.3 → w; ≤ 0.5 → w/2 (only when rsi_score ≥ 1).
- StochRSI: k < 0.2 and k > d → w.
- RSI divergence → w.
- Fibonacci: within 1% → w; within 2% → w/2.
- MACD, EMA cross, volume, OBV and btc_trend: fixed at 0.

The maximum score is 5.5 when every w = 1. There is no confidence threshold on the live path.

[STR-15 · SOURCE_VERIFIED] The legacy decision gate is final = score + ob_score + btc_bonus + tf_bonus, which must reach min_score (`signal_engine/signal_logic.py:570-575` at ea8ae4f; publication re-check).
- min_score comes from `optimizer_settings` (seed 5.0) and falls back to `MIN_SCORE_TO_SIGNAL` (code default 5; snapshot 7.0).
- min_tf comes from `optimizer_settings` and falls back to `MIN_TIMEFRAME_CONFIRMATIONS` (code 2; snapshot 1).
- Weights are per `market_condition`, default 1.0.
- Live DB values are NOT VERIFIED (L-DB).

[STR-16 · SOURCE_VERIFIED] Legacy-only filters, inactive on the live path:
- the 4h primary-timeframe ban (`signal_logic.py:631`);
- rejection of 1d bearish/sideways candidates whose raw total_score is ≥ 4.0 (around `:655`; the code comment cites a 2,433-trade sample with n = 251 for that cell);
- the stoch>0 gate (`:671`);
- the bullish/volatile majority filters;
- `trend_ok` (EMA200);
- the BTC-crash pause (`_is_btc_crashing`);
- the BTC bonus and the TF bonus;
- `GLOBAL_LOSS_COOLDOWN_HOURS` 6 (snapshot 0);
- `MAX_SIGNALS_PER_DAY` 5 (snapshot 0).

| Field | Value |
|---|---|
| Source file | Score: `analyzer/technical_analyzer.py:323-402`; weights `:482-490`. Decision: `signal_engine/signal_logic.py` (legacy `find_best_signal`): thresholds `:295-307`, final sum `:570-575`, filters `:631`, around `:655` and `:671`. All at ea8ae4f. |
| Function/class | `_calculate_scores`; `_get_indicator_weights`; `find_best_signal`; `_get_live_thresholds`; `_is_btc_crashing` |
| Strategy/version identifier | `legacy_score_v1` |
| Status | DISABLED as a decision path (STR-01); the score is computed on every analysis pass and recorded. Optimizer compose-disabled (LRN-09, LRN-10). |
| Hypothesis | Not stated in the audit sources; implicit indicator-confluence scoring. |
| Entry logic | Score components (STR-14); then gate final ≥ min_score with multi-timeframe confirmation min_tf (IND-04); then the legacy filters (STR-16). |
| Exit logic | The same tracker exits as the live setups (EXE-10, EXE-11); no legacy-specific exit. |
| Timeframes | Snapshot 15m/4h/1d; a primary ("top") timeframe per symbol, with 4h banned as primary. |
| Market-context dependencies | `btc_bonus`, which uses the symbol's own regime, not BTC's (CON-24); the BTC-crash pause; `market_condition` selects the weight set. |
| Indicators | RSI14, Bollinger position, StochRSI k/d, RSI divergence, Fibonacci proximity, order-book score (IND-02). MACD, EMA cross, volume and OBV are computed but score 0. |
| Thresholds | RSI bands 30/40/50; BB 0.3/0.5; StochRSI 0.2; Fibonacci 1%/2%; min_score (IND-05, IND-06); min_tf (IND-04); 1d raw total_score 4.0; stoch>0; cooldown 6 h; 5 signals per day. |
| Weights | `indicator_weights` per (indicator, market_condition), 1.0 on a missing row or read error (IND-07). The seeded `order_book` weight is never read (IND-02). |
| Default vs effective runtime value | min_score: code 5, `.env.example` 7, snapshot 7.0, DB seed 5.0, documented DB value 3.0 (IND-06). min_tf: code 2, snapshot 1, seed 2. Effective NOT VERIFIED (L-ENV, L-DB). |
| DB overrides | `optimizer_settings.min_score_to_signal` and `optimizer_settings.min_timeframe_confirmations` (DB > env > default, legacy path only; CAL-01); `indicator_weights`. |
| Calibration provenance | • min_score: class RC, set to 3.0 on 2026-05-16 (`docs/claude/strategy-history.md:8`).<br>• Weights: class RC/AL; code comments cite "240 / 262 trades"; frozen optimizer output (LRN-12) and the colab notebook (LRN-13).<br>• 1d raw-score rule: code comment cites 2,433 trades, n = 251 for the cell.<br>• 4h primary ban: code comment cites 275 post-rebuild trades from 2026-04-22 to 2026-05-16. This is SOURCE_VERIFIED by the publication re-check of the code comment.<br>• stoch>0 gate: its code comment records that the 2026-06-23 full-database audit (n = 2,518) found it loss-reducing but still negative after fees. SOURCE_VERIFIED by the same re-check. |
| Validation evidence | Pre-freeze Paper evidence for the score strategy: 2,518 trades, 2026-04-09 to 06-21, gross PF 0.735, net PF 0.598, verdict NO EDGE. This is HISTORICAL_REPORTED (HIS-01; [REPORT.md](../../../research/skill_application/out/REPORT.md) at 977746f). The stoch gate and COMBO fail out of sample (HIS-01). |
| Scientific weaknesses | • Often described as live (CON-12).<br>• Conflicting min_score values (CON-13).<br>• A "/10" log label, and an env min_score of 7 that is unreachable with weights of 1.0 (CON-14).<br>• A comment that holds only when w_rsi = 1.0 (CON-20).<br>• `btc_bonus` uses the symbol's own regime (CON-24).<br>• The stoch>0 calibration predates the StochRSI change (CON-25).<br>• Weights were tuned on gross PnL with no statistics (LRN-11, LRN-12). |

*Evidence (card):* `analyzer/technical_analyzer.py:323-402, 482-490`, `signal_engine/signal_logic.py:295-307, 570-575, 631, 655, 671` · `_calculate_scores`, `find_best_signal`, `_get_live_thresholds` · ea8ae4f · runtime-verified: no · limits: L-IMG, L-ENV, L-DB.

### 3.7 T1 cap policy and the W3 defect (STR-17, STR-21)

[STR-17 · SOURCE_VERIFIED] `T1_CAP_POLICY` (commit a4a7561) exists at bb7825f and main but not at ea8ae4f. Its default is `legacy_window_v1`; `independent_swing_v1` is A46 G1. In the documented-deployed source (ea8ae4f) the T1 cap is therefore hard-coded as resistance × 0.99 (`analyzer/technical_analyzer.py:463-467`) and cannot be switched; whether the running image contains that code is NOT VERIFIED (RT-17).

[STR-21 · SOURCE_VERIFIED] The W3 defect:
- T1 is capped at 0.99 × the 20-bar high, and that window includes the decision bar.
- T1 can therefore be pinned to the breakout bar's own wick, and can sit below net break-even.
- It is not look-ahead.
- A45 confirmed it (`docs/a45/A45_SETUP_RESEARCH.md:95`).
- It is not fixed at runtime (STR-17).
- Affected-signal counts are in A42 §B.3 L129-131 and A45 §A45-C (count withheld).

| Field | Value |
|---|---|
| Source file | Running behaviour: `analyzer/technical_analyzer.py:463-467` at ea8ae4f (hard-coded `resistance * 0.99`). Policy code: `shared/t1_cap.py` and `T1_CAP_POLICY` in `shared/config.py:124` (default `legacy_window_v1`) at bb7825f and main, from commit a4a7561. The `t1_cap_policy()` startup check in `analyzer/main.py` exists only at bb7825f and main. |
| Function/class | `TechnicalAnalyzer._calculate_levels`; `t1_cap_policy()` (bb7825f and main only) |
| Strategy/version identifier | `legacy_window_v1` (the hard-coded behaviour of the documented-deployed source ea8ae4f, and the flag default at bb7825f/main); `independent_swing_v1` (A46 G1; absent from ea8ae4f) |
| Status | Documented-deployed source (ea8ae4f): legacy cap, not switchable (STR-17; RT-17). Defect not fixed in that source (STR-21). |
| Hypothesis | Not applicable (target geometry). |
| Entry logic | Not applicable. |
| Exit logic | T1 = entry + 1R, capped at 0.99 × the highest high of the 20-bar window that includes the decision bar. Only T1 is reported as capped; T2 = +1.8R and T3 = +2.2R (IND-10). |
| Timeframes | All. |
| Market-context dependencies | None. |
| Indicators | The 20-bar high ("resistance"). |
| Thresholds | Cap factor 0.99; 20-bar window including the decision bar. |
| Weights | None. |
| Default vs effective runtime value | ea8ae4f source: hard-coded (L-IMG). bb7825f/main: `T1_CAP_POLICY` default `legacy_window_v1`, which is absent from the documented-deployed analyzer source. |
| DB overrides | None. |
| Calibration provenance | Class M. |
| Validation evidence | Defect confirmed by A45 (`docs/a45/A45_SETUP_RESEARCH.md:95`). G1 has 27 synthetic tests (STR-36). Counts are withheld; see A42 §B.3 L129-131 and A45 §A45-C. |
| Scientific weaknesses | T1 can sit below net break-even. Main and bb7825f do not describe the T1 behaviour of the documented-deployed source (CON-22). The defect's severity labels differ between A42 and A45 (CON-33, held in [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md)). |

*Evidence (card):* `analyzer/technical_analyzer.py:463-467` (ea8ae4f); `shared/t1_cap.py`, `shared/config.py:124` (bb7825f, main) · `_calculate_levels`, `T1_CAP_POLICY` · runtime-verified: no · limits: L-IMG, L-T1.

### 3.8 Learned gates (STR-18, STR-19)

[STR-18 · SOURCE_VERIFIED] The learned-gate rule: `research/continuous_learner.py` writes the gates, and `signal_logic` applies them.
- Cells are (trade_type, usdtd_trend, timeframe).
- The learner uses the newest 150 trades after 100 warm-up trades.
- Net = profit% − 0.3.
- A cell is throttled if n ≥ 10 and mean + 1.96·sd/√n ≤ 0.
- A 10% hourly hash exploration still admits throttled candidates.
- `LEARNING_GATES_ENABLED` defaults to false.

Details are in section 9 (LRN-06, LRN-07, LRN-18, LRN-19).

[STR-19 · DOCUMENTED_ONLY] Learned gates are disabled: `LEARNING_GATES_ENABLED` is false in the snapshot, and the learner has been retired and stopped since 2026-08-17 (DEPLOYED.json; `docs/current_handoff_2026-08-17.md:13`).

| Field | Value |
|---|---|
| Source file | Writer `research/continuous_learner.py`. Reader `signal_engine/signal_logic.py:27-28, 390-394, 741-743` (`LEARNED_GATES_SQL`); exploration `:819-831`. |
| Function/class | `find_best_signal_live` (and the enforce path); `learning_governance.exploration_selected`; learner `validate_cells` |
| Strategy/version identifier | Rows carry `strategy_version` (default `legacy`) and `learning_run_id`. Migration 006 marks `pre-statistical-reset`. |
| Status | DISABLED: flag default false (SOURCE_VERIFIED); false in the snapshot and learner stopped (STR-19). Runtime flag NOT VERIFIED (LRN-20). |
| Hypothesis | Cells with significantly negative net expectancy should be throttled. |
| Entry logic | A candidate in a cell with n ≥ 10 and weight ≤ 0 is blocked, unless the 10% hourly hash exploration selects it. |
| Exit logic | None. |
| Timeframes | Per cell (one cell dimension is the timeframe). |
| Market-context dependencies | macro_state = "usdtd_" + the USDT.D trend (MKT-10). |
| Indicators | None. The cells are outcome statistics. |
| Thresholds | MIN_CELL_N 10; z = 1.96; ROLL_N 150; WARMUP_N 100; cost 0.3; exploration rate 0.10; THROTTLE_STALE_DAYS 14. |
| Weights | Binary gate weight, 0 or 1. |
| Default vs effective runtime value | Flag code default false; snapshot false; Compose default exploration rate 0.10; effective NOT VERIFIED (L-ENV). |
| DB overrides | The `learned_gates` table (contents NOT VERIFIED, L-DB). |
| Calibration provenance | Class AL, frozen since 2026-08-17. |
| Validation evidence | `test_continuous_learner` (mechanics). Phase 5 historically found learned gates equal to the baseline (HIS-10, HISTORICAL_REPORTED). |
| Scientific weaknesses | No multiple-testing correction; the throttle fails open; a feedback loop (LRN-07, LRN-08). If the flag is enabled, stale throttles apply indefinitely, with no expiry or strategy_version filter (LRN-19). |

*Evidence (card):* `research/continuous_learner.py`, `signal_engine/signal_logic.py:27-28, 390-394, 741-743, 819-831` · `LEARNED_GATES_SQL`, `LEARNING_GATES_ENABLED` · ea8ae4f (identical at main) · runtime-verified: no · limits: L-IMG, L-ENV, L-DB.

### 3.9 Earlier 15m/4h momentum and reversion family (STR-20)

[STR-20 · SOURCE_VERIFIED] This family is HISTORICAL; 63da7d3 superseded its rules, together with the StochRSI change to 14/3/3. Its rules:
- the regime came from the EMA stack plus ATR > 1.5 × its average;
- reversion required close < 1.01 × BB_lower;
- StochRSI used K=14.

| Field | Value |
|---|---|
| Source file | Code before 63da7d3. The investigation did not record exact file:line for this family. |
| Function/class | Not recorded by the investigation. |
| Strategy/version identifier | Pre-63da7d3 rules. The Phase 3 to 9 studies predate the 63da7d3 change (HIS-36), so they evaluated pre-63da7d3 rules (lineage HIS-46, INFERRED). |
| Status | HISTORICAL; not in any running image. |
| Hypothesis | Momentum continuation and mean reversion on 15m/4h (family name). |
| Entry logic | Regime: EMA stack plus ATR > 1.5 × its average. Reversion: close < 1.01 × BB_lower. StochRSI K=14. Other details: NOT VERIFIED (not recorded). |
| Exit logic | NOT VERIFIED (not recorded for this family). |
| Timeframes | 15m and 4h (family name). |
| Market-context dependencies | NOT VERIFIED (not recorded). |
| Indicators | EMA stack, ATR, Bollinger lower band, StochRSI (K=14). |
| Thresholds | ATR > 1.5 × average; close < 1.01 × BB_lower. |
| Weights | Not applicable / NOT VERIFIED. |
| Default vs effective runtime value | Not applicable (historical). |
| DB overrides | Not applicable. |
| Calibration provenance | Not documented. |
| Validation evidence | The historical cohort studies are summarised in [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md) (HIS-09 to HIS-13: confidence intervals contain 0; NO-GO; HISTORICAL_REPORTED). |
| Scientific weaknesses | StochRSI smoothing, unscored RSI < 20 and a silent `ta` fallback were changed only at 63da7d3 (HIS-36). |

### 3.10 A42 signal-quality gates C1, C2, C3 (STR-26 to STR-29)

[STR-26 · SOURCE_VERIFIED] The A42 C1 cost-per-risk gate (`shared/signal_quality.py`, `a42-sq-v1`):
- It refuses a candidate if cost/R > 0.25, or if the T1→break-even path nets ≤ 0, evaluated at 20 bps.
- It is DORMANT: `enabled=False`, and no service imports it.

[STR-27 · DOCUMENTED_ONLY] `docs/strategy/S5_PWR_1_OWNER_DECISIONS.md` rates C1 CURRENTLY_INADMISSIBLE and C2 DEFERRED.

[STR-28 · SOURCE_VERIFIED] The A42 C2 BTC-beta cap:
- Rule: Σ|β|·notional ≤ 75 USDT, with β from 96 bars and an unknown β set to 1.5.
- Implemented as `shared/signal_quality.CorrelatedExposurePolicy(enabled=False)`.
- No deployed entrypoint imports it. It is DORMANT.

[STR-29 · DOCUMENTED_ONLY] The A42 C3 funding veto:
- Rule: veto momentum longs when perpetual funding ≥ 0.03%/8h.
- It is PROPOSED, as a specification only.
- Its data licence is on HOLD.

| Field | C1 cost-per-risk | C2 BTC-beta cap | C3 funding veto |
|---|---|---|---|
| Source file | `shared/signal_quality.py` | `shared/signal_quality.py` | specification only (A42 §A42-E) |
| Function/class | C1 policy in `signal_quality` | `CorrelatedExposurePolicy` | none |
| Strategy/version identifier | `a42-sq-v1` | same module (identifier not stated) | not stated |
| Status | DORMANT (`enabled=False`, not imported); S5 CURRENTLY_INADMISSIBLE | DORMANT (`enabled=False`, not imported); S5 DEFERRED | PROPOSED; licence HOLD |
| Hypothesis | Trades whose costs consume too much of the risk unit, or whose T1→break-even path loses money, should be refused | BTC-correlated exposure should be capped | Momentum longs during high funding should be vetoed |
| Entry logic | refuse if cost/R > 0.25 or T1→break-even net ≤ 0 | refuse if Σ abs(β)·notional > 75 USDT | veto if funding ≥ 0.03%/8h |
| Exit logic | not applicable | not applicable | not applicable |
| Timeframes | all | β from 96 bars | not stated |
| Market-context dependencies | none | BTC beta | perpetual funding data (licence HOLD) |
| Indicators | cost/R | β | funding rate |
| Thresholds | 0.25 R; 20 bps | 75 USDT; 96 bars; unknown β = 1.5 | 0.03%/8h |
| Weights | none | none | none |
| Default vs effective runtime value | disabled in code; not on the runtime path | disabled in code; not on the runtime path | not implemented |
| DB overrides | none | none | none |
| Calibration provenance | A42 design; no dataset recorded | A42 design | A42 design |
| Validation evidence | specified, not run (GOV-15) | specified, not run (GOV-15) | specified, not run (GOV-15) |
| Scientific weaknesses | No cost coverage in production (HIS-29); evaluated at 20 bps, whereas the runtime model uses 0.30% (EXE-13) | not tested | depends on unlicensed data |

### 3.11 A44 rankers and the S3 selector (STR-30 to STR-32)

[STR-30 · SOURCE_VERIFIED] The A44 rankers and the S3 selector are DORMANT:
- A44 rankers in `shared/candidate_selection.py`: `execution_quality_v2` and `cost_per_risk_v1`.
- S3: `s3-sel-v1` plus `s3-shadow-v1`. `S3Policy.enabled=False`.
- The S3 sidecar runs only with `--enable` and has no Compose service.

[STR-31 · NOT_VERIFIED] Whether the S3 shadow sidecar ever ran.

[STR-32 · HISTORICAL_REPORTED] Synthetic tests show that ranking cannot change signal frequency. The S3 selector was exercised on 1,000 synthetic sets (`docs/s3/S3_SIGNAL_SELECTION.md` §3).

| Field | Value |
|---|---|
| Source file | `shared/candidate_selection.py` (A44 rankers). The investigation did not record the exact file of the S3 policy and sidecar code; the shared modules `signal_selection` and `s3_shadow*` are among those that no service imports (ARC-21). |
| Function/class | `execution_quality_v2`, `cost_per_risk_v1` rankers; `S3Policy` |
| Strategy/version identifier | `execution_quality_v2`, `cost_per_risk_v1`, `s3-sel-v1`, `s3-shadow-v1` |
| Status | DORMANT; S3 shadow run history NOT VERIFIED (STR-31) |
| Hypothesis | A better ranking of candidates improves the selected signals |
| Entry logic | Alternative ranking keys; not on the runtime path |
| Exit logic | Not applicable |
| Timeframes | All |
| Market-context dependencies | None recorded |
| Indicators | Execution quality and cost per risk |
| Thresholds | Not recorded in the audit sources |
| Weights | Not recorded |
| Default vs effective runtime value | Disabled; the live ranking is STR-13 |
| DB overrides | None |
| Calibration provenance | Engineering design (A44, S3) |
| Validation evidence | Synthetic only (STR-32); `test_a44_selection_pipeline` |
| Scientific weaknesses | The S3 document says a NaN spread passes, but ea8ae4f fixes that (CON-23). Ranking cannot raise signal frequency (STR-32). |

### 3.12 A43 signal integrity (STR-33, STR-34)

[STR-33 · SOURCE_VERIFIED] A43 signal integrity is FLAGGED OFF:
- With `SIGNAL_INTEGRITY_MODE=enforce` it provides candle identity, ≤ 1-bar freshness and an insert-once `setup_key`; this relies on the A44 signal identity (eb68e42, migration 011).
- The default is off (`shared/config.py:118` at ea8ae4f), and Compose does not set it.

[STR-34 · DOCUMENTED_ONLY] The documents say that no enforce window was authorized. The effective value is NOT VERIFIED; it is likely off.

| Field | Value |
|---|---|
| Source file | `shared/signal_identity.py` (freshness rule at lines 186-200); `shared/config.py:118` (ea8ae4f); migration 011 |
| Function/class | Integrity checks in `signal_identity`; the enforce path in `signal_logic` |
| Strategy/version identifier | `SIGNAL_INTEGRITY_MODE` = `off` or `enforce` (an unknown value refuses to start; ARC-22) |
| Status | FLAGGED OFF (default off; not set in Compose); effective value NOT VERIFIED (L-ENV) |
| Hypothesis | Not applicable (data integrity) |
| Entry logic | In enforce mode, bounded retries block the cycle, freshness and duplicate checks apply, and a `setup_key` is required (ARC-06). |
| Exit logic | Not applicable |
| Timeframes | All |
| Market-context dependencies | None |
| Indicators | None |
| Thresholds | Freshness ≤ 1 bar; insert-once per `setup_key` |
| Weights | None |
| Default vs effective runtime value | Default off; effective NOT VERIFIED |
| DB overrides | None |
| Calibration provenance | Not applicable |
| Validation evidence | `test_a43_signal_integrity` |
| Scientific weaknesses | With integrity off, a same-bar re-fire after the 2 h cooldown is possible (EXE-17), duplicate trades can occur (HIS-26), and candle age is never checked (EXE-09). |

### 3.13 A45 setup diagnostics H1 to H3 (STR-35)

[STR-35 · SOURCE_VERIFIED] A45 H1–H3 (`shared/setup_diagnostics.py`, `a45-sd-v1`, `enabled=False`) are DORMANT/RESEARCH, with 26 engineering tests. The A45 verdict is REVISE STRATEGY. The three hypotheses:
- H1: momentum only if BTC's 3-day change ≥ 0.
- H2: (close − prior 20-bar high)/ATR14 ≤ 0.75.
- H3: volume > 1.2 × the mean of the same 15m slot over 20 days. This needs about 1,921 bars; only 200 are fetched.

| Field | Value |
|---|---|
| Source file | `shared/setup_diagnostics.py` |
| Function/class | Setup-diagnostic policy (`enabled=False`) |
| Strategy/version identifier | `a45-sd-v1` |
| Status | DORMANT / RESEARCH; not imported by any service (ARC-21) |
| Hypothesis | H1 BTC-trend filter; H2 no chasing of extended breakouts; H3 time-of-day-adjusted volume |
| Entry logic | H1, H2 and H3 as listed above |
| Exit logic | Not applicable |
| Timeframes | H3 is 15m-specific |
| Market-context dependencies | H1 uses the BTC 3-day change |
| Indicators | BTC 3-day change; ATR14; prior 20-bar high; slot-mean volume |
| Thresholds | 0 (H1); 0.75 ATR (H2); 1.2 × 20-day slot mean (H3) |
| Weights | None |
| Default vs effective runtime value | Disabled |
| DB overrides | None |
| Calibration provenance | A45 research design |
| Validation evidence | 26 engineering tests; no economic test; specified, not run (GOV-15) |
| Scientific weaknesses | H3 cannot run on the 200-bar fetch (it needs about 1,921 bars) |

### 3.14 A46 trade geometry G1 to G3 (STR-36, STR-37)

[STR-36 · SOURCE_VERIFIED] A46 G1–G3 (`shared/trade_geometry.py`, `a46-tg-v1`) are DORMANT, with 27 synthetic tests. The module imports `shared/strategy_math`.
- G1: an independent swing-high T1 cap (2-bar fractal; 1R if none).
- G2: the T1→break-even path must net ≥ 0.
- G3: entry = min(close, level + 0.75·ATR).

[STR-37 · INFERRED] `trade_geometry` is unimportable in the ea8ae4f images, because `shared/strategy_math` is documented as absent there.

| Field | Value |
|---|---|
| Source file | `shared/trade_geometry.py` (imports `shared/strategy_math`); G1 is selectable through `T1_CAP_POLICY=independent_swing_v1` only at bb7825f and main (STR-17) |
| Function/class | Trade-geometry policies G1, G2, G3 |
| Strategy/version identifier | `a46-tg-v1`; G1 = `independent_swing_v1` |
| Status | DORMANT; no service imports it (ARC-21); unimportable in the ea8ae4f images (STR-37) |
| Hypothesis | Better target, break-even and entry geometry improves net outcomes |
| Entry logic | G3: entry = min(close, level + 0.75·ATR) |
| Exit logic | G1: T1 at an independent swing high (2-bar fractal), else 1R. G2: require the T1→break-even path to net ≥ 0. |
| Timeframes | All |
| Market-context dependencies | None recorded |
| Indicators | Swing-high fractals; ATR |
| Thresholds | 2-bar fractal; 0.75·ATR; net ≥ 0 |
| Weights | None |
| Default vs effective runtime value | Not on the runtime path |
| DB overrides | None |
| Calibration provenance | A46 research design |
| Validation evidence | 27 synthetic tests; specified, not run (GOV-15) |
| Scientific weaknesses | No market test. 15m fees are 0.22–0.43 R per trade (A46-C fee arithmetic, ECO-06). |

### 3.15 S4 mechanisms M1 to M5 and Phase-1 hypotheses (STR-38)

[STR-38 · SOURCE_VERIFIED] S4 M1–M5 (`research/mechanisms`, `s4-mech-v1`) are RESEARCH-ONLY and NOT TESTED; `simulate.run` refuses without a `DatasetPermission` (`research/mechanisms/simulate.py`; `tests/test_s4_mechanisms.py`).
- The mechanisms, in the order the source lists them: TSMOM long/cash, cross-sectional momentum, carry (not executable on Spot), volatility overlay, and M5 = the current family.
- Phase-1 hypotheses:
  - H1: 14-day TSMOM over a point-in-time top-20 universe;
  - H2: cross-sectional top-5, weekly;
  - H3: T1 cap policy, legacy versus independent swing.

| Field | Value |
|---|---|
| Source file | `research/mechanisms/` (`simulate.py`); tests `tests/test_s4_mechanisms.py`; documents `docs/strategy/S4_MECHANISM_COMPARISON.md`, `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md` |
| Function/class | `simulate.run` (refuses without a `DatasetPermission`) |
| Strategy/version identifier | `s4-mech-v1` |
| Status | RESEARCH-ONLY, NOT TESTED; S4 backtests are on HOLD pending owner decisions (GOV-13) |
| Hypothesis | Mechanism families with economic rationale (time-series momentum, cross-sectional momentum, carry, volatility overlay) versus the current family (M5) |
| Entry logic | H1: 14-day TSMOM on a point-in-time top-20 universe. H2: cross-sectional top-5, weekly rebalance. Others not recorded in the audit sources. |
| Exit logic | H3 compares T1 cap policies. Other exits not recorded. |
| Timeframes | H1 14-day lookback; H2 weekly |
| Market-context dependencies | Point-in-time universe (H1) |
| Indicators | Returns over the lookback |
| Thresholds | 14 days; top-20; top-5 |
| Weights | Not applicable |
| Default vs effective runtime value | Not deployed; not applicable |
| DB overrides | None |
| Calibration provenance | Design only. Planned data: 2019–2022 plus 2023-01 → 2026-08-18. Cost model: fee 0.10%/side; half-spread 0.01% for BTC/ETH and 0.04% for others; slippage 0.05%/side; ×2 stress (HIS-15). |
| Validation evidence | None on market data: 0 trades run (HIS-15). Code refuses non-synthetic data. |
| Scientific weaknesses | Carry is not executable on Spot. No market evidence (HIS-43). The half-spread assumption differs from Design A (CON-45). |

### 3.16 Design A v1.0 (STR-39)

[STR-39 · SOURCE_VERIFIED] Design A v1.0 exists only on `feature/design-a-v1` at ebf8d8a: `research/design_a` and `docs/strategy/DESIGN_A_SPEC_v1.0.md`.
- Rule: BTC/USDT goes LONG iff the latest completed Sunday daily close > the SMA200 of 200 completed UTC daily closes; equality means FLAT.
- Timing: decided Monday 00:00 UTC plus 30 seconds; filled at the Tuesday daily open; deferrable within 72 h, with owner-approved weekly retries.
- Position: 100% BTC or 100% cash.
- Costs: 0.20%/side baseline (0.40% round trip: fee 0.10% + half-spread 0.05% + slippage 0.05%) and 0.30%/side stress (0.60% round trip).
- Status: RESEARCH-ONLY; 83 synthetic tests; profitability UNKNOWN; evaluation not authorized (owner decisions E1–E8 pending).

| Field | Value |
|---|---|
| Source file | `research/design_a/` (`state.py`, `timing.py`, `decision.py`, `ledger.py`) and `docs/strategy/DESIGN_A_SPEC_v1.0.md`, both on `feature/design-a-v1` at ebf8d8a (not on main) |
| Function/class | Decision and ledger logic in `decision.py` and `ledger.py`; the investigation did not record function-level detail |
| Strategy/version identifier | Design A v1.0 |
| Status | RESEARCH-ONLY; branch unmerged; evaluation not authorized (GOV-16); no service runs it |
| Hypothesis | Long-only trend exposure on BTC/USDT while the weekly-sampled daily close is above its 200-day average (as specified). Profitability UNKNOWN. |
| Entry logic | LONG iff the latest completed Sunday daily close > SMA200(200 completed UTC daily closes). Decision: Monday 00:00 UTC plus 30 seconds. Execution reference: the Tuesday daily open. A pending transition may be deferred within 72 h (owner-approved weekly retries). |
| Exit logic | FLAT when the Sunday close ≤ SMA200 (equality FLAT); 100% cash. |
| Timeframes | Daily closes, weekly decisions |
| Market-context dependencies | BTC/USDT only |
| Indicators | SMA200 of daily closes |
| Thresholds | 200 daily closes; strict inequality for LONG |
| Weights | None |
| Default vs effective runtime value | Not deployed; not applicable |
| DB overrides | None |
| Calibration provenance | Frozen specification. The cost baseline 0.40% round trip and stress 0.60% round trip are the owner-approved Design A cost model used as a reference in EXE-15. |
| Validation evidence | 83 synthetic tests; no performance computed; outcome classification "NOT DEFINED" (HIS-16) |
| Scientific weaknesses | No market evidence (HIS-43). The half-spread of 0.05% conflicts with the 0.01% used for BTC/ETH in the S4 model (CON-45). The first evaluation is gated by owner decisions E1–E8. |

### 3.17 Historical research families (STR-40)

[STR-40 · DOCUMENTED_ONLY] Historical research families, none imported by any service:
- Cross-sectional momentum long/short (`analyzer/MODEL_FROZEN_SPEC.md`): needs futures; cites an OOS Sharpe of 1.60; 94% of its P&L came from the short leg, according to the S4 documents.
- Funding carry: NO-GO.
- `analyzer/backtest_part*` (SMC, ICT, Ichimoku and others): research-only, documented as having no edge.

| Field | Value |
|---|---|
| Source file | `analyzer/MODEL_FROZEN_SPEC.md`; `analyzer/backtest_part*`; research scripts (see HIS-22 to HIS-24) |
| Function/class | Research scripts only |
| Strategy/version identifier | Not applicable |
| Status | HISTORICAL; not imported by any service |
| Hypothesis | Cross-sectional momentum; funding carry; SMC/ICT/Ichimoku structures |
| Entry logic | Not recorded in detail in the audit sources |
| Exit logic | Not recorded |
| Timeframes | Cross-sectional momentum is weekly (HIS-07) |
| Market-context dependencies | Futures and short selling for the long/short family |
| Indicators | Family-specific; not recorded |
| Thresholds | Not recorded |
| Weights | Not applicable |
| Default vs effective runtime value | Not applicable |
| DB overrides | Not applicable |
| Calibration provenance | Post-hoc grid for cross-sectional momentum (HIS-07) |
| Validation evidence | HISTORICAL_REPORTED results in [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md) (HIS-05 to HIS-07, HIS-22 to HIS-24) |
| Scientific weaknesses | The short leg is not executable on Spot; the evidence is a single out-of-sample year (HIS-07); there are no result documents for several SMC studies (HIS-22, HIS-23) |

## 4. Indicator and calibration matrix

**Calibration classes.**

| Code | Meaning |
|---|---|
| M | Manual constant |
| RC | Research-calibrated: a code comment or document cites a sample |
| AL | Automatically learned (optimizer, colab notebook or learner output; frozen) |
| H | Historical or legacy-only |
| CE | Currently effective on the presumed live path |

**Columns.**
- "Configured" lists the value in Compose `environment:` / `.env.example` / the 2026-09-27 snapshot, in that order; "–" means not set.
- `.env.example` values are cited via `docs/ops/ENV_EXAMPLE_REVIEW_2026-10-18.md`, because reading the file was blocked by a permission rule.
- Runtime-verified is "no" for every row (CAL-03). "= code" values are still subject to L-IMG.

| ID · class | Parameter | Code default (file:function) | Configured (Compose / .env.example / snapshot) | DB override | Effective | Runtime-verified | Class |
|---|---|---|---|---|---|---|---|
| [IND-01 · SOURCE_VERIFIED] | Indicator periods: RSI 14; MACD 12/26/9; EMA 20/50/200; Bollinger 20, 2σ; ATR 14; StochRSI 14 / K 3 / D 3; ADX 14; volume MA 20 | `shared/config.py:145-159`, plain constants (no getenv); `analyzer/technical_analyzer.py` | not env-settable | none | = code | no | M; CE (RSI, EMA20/50, Bollinger and ATR feed the live triggers) |
| STR-05, STR-06 | Timeframes | `shared/config.py:36` → 15m,1h,4h,1d | – / – / 15m,4h,1d | none | NOT VERIFIED (snapshot 15m,4h,1d) | no | M, CE |
| STR-07 | Momentum / breakout / volume trigger | `analyzer/simple_entry.py:28-44`: bullish regime; close > EMA20 > EMA50; close > prior 20-bar high; volume > 1.2 × prior-20 mean | MOM_BREAKOUT_N, MOM_VOL_MULT: – / – / 20, 1.2 | none | NOT VERIFIED (snapshot 20, 1.2) | no | M, CE |
| STR-08 | Mean-reversion trigger | `analyzer/simple_entry.py:54-58`: sideways regime; RSI < 35; close > previous close; close > open; BB position ≤ 0.20 | REV_RSI – / – / 35; REV_BB_MAX_POSITION – / 0.20 / 0.2 | none | NOT VERIFIED (snapshot 35, 0.2) | no | M, CE |
| STR-09 | Regime classifier | `shared/regime.py:10-60`: ADX ≥ 25 trend, < 20 range; EMA20 5-bar slope; ATR% rank over 100 bars ≤ 0.75 | not settable | none | = code | no | M, CE |
| [IND-08 · SOURCE_VERIFIED] | Regime weights | none on the live path; `indicator_weights[market_condition]` exist only inside the legacy score | – | see the score row | – | no | AL / H |
| STR-11 | Macro gate | `shared/macro_context.py:10-41, 96-110`: BTC 18×4h change ≤ −5%; USDT.D minus 3-day mean ≥ 0.5 pp; data stale > 2 h blocks (fail-closed); 1 h cache; FLAT_EPS 0.05 hard-coded | USDTD_SPIKE_PP, MACRO_CACHE_HOURS, MACRO_MAX_STALE_HOURS: – / –, 1, 2 / 0.5, 1, 2 | reads `macro_history` (data, not settings) | NOT VERIFIED (snapshot 0.5, 1, 2) | no | M, CE |
| [IND-03 · SOURCE_VERIFIED] | Spread gate | `shared/config.py:165` `MAX_SPREAD_PCT` 0.15, a live gate in `find_best_signal_live` (order book valid and finite `spread_pct` ≤ 0.15). Live gate: no provenance recorded. The legacy path has its own MAX_SPREAD_PCT gate after the stoch>0 gate (around `signal_logic.py:675-680` at ea8ae4f); its code comment (2026-06-23 audit) calls it an execution-feasibility filter, not an edge filter (publication re-check) | – / – / 0.15 | none | NOT VERIFIED (snapshot 0.15) | no | M, CE |
| [IND-02 · SOURCE_VERIFIED] | Order-book score | `analyzer/orderbook_analyzer.py:19-110` (20-level snapshot): wall ≥ 5 × the average level within 3%; bid/ask ratio thresholds 1.5 / 1.2; spread > 0.5% → −0.2 | – | `order_book` indicator weight seeded but never read | not part of the analyzer total_score; enters only the legacy decision sum (STR-15); on the live path the order book contributes only validity and spread | no | H (computed, unused on the live path) |
| UNI-09, UNI-10 | Liquidity / universe (scanner) | `scanner_logic.py:72-81` (scanner): USDT quote, TRADING, ASCII names, stablecoin pairs excluded; 24h quote volume ≥ `MIN_VOLUME_USDT` 10,000,000 (`shared/config.py` c5c03b5:130); absolute 24h change ≥ 1.0%, a constant (:131); scanner BTC 4h trend over 10 bars ±1/±3%, strong bearish requires ≥ 5% (:107-142); no depth filter | MIN_VOLUME_USDT – / – / 10M; SCAN_INTERVAL_SECONDS – / 300 / 300 | `symbol_blacklist` removed from the universe on every scan (contents NOT VERIFIED) | NOT VERIFIED (snapshot 10M) | no | M (10M raised on 2026-04-27), CE |
| [IND-04 · SOURCE_VERIFIED] | Multi-timeframe confirmation | live: none (every timeframe is an independent candidate); legacy `_get_live_thresholds` min_tf, which drops to 1 for a 1d bearish/sideways row scoring ≥ 3.0 | MIN_TIMEFRAME_CONFIRMATIONS – / – / 1 (code default 2) | `optimizer_settings.min_timeframe_confirmations`, DB > env > default; seed 2 (migration 003) | live: not applicable; legacy: NOT VERIFIED | no | M / AL, H |
| [IND-05 · SOURCE_VERIFIED] | min_score | live: none; legacy `_get_live_thresholds` (`signal_engine/signal_logic.py:295-307`), which falls back to env on error (fail-open) | MIN_SCORE_TO_SIGNAL – / 7 / 7 (code default 5) | `optimizer_settings.min_score_to_signal`, DB > env > default; seed 5.0 | live: not applicable; legacy: NOT VERIFIED | no | RC, H |
| [IND-06 · DOCUMENTED_ONLY] | min_score documented DB value | `docs/claude/strategy-history.md:8`: 3.0, set on 2026-05-16; contested: DEV_LOG L67-68 raises min_score from 3 to 4 while strategy-history keeps 3.0 (CON-40) | – | documented 3.0 | live DB value NOT VERIFIED | no | RC |
| STR-14, [IND-07 · SOURCE_VERIFIED] | Score ("confidence") and indicator weights | `_calculate_scores` (`technical_analyzer.py:323-402`): RSI < 30 → 1.5w, 30–40 → 1.0w, 40–50 → 0.3w; BB ≤ 0.3 → w, ≤ 0.5 → w/2 (only when rsi_score ≥ 1); StochRSI k < 0.2 and k > d → w; RSI divergence → w; Fibonacci within 1% → w, within 2% → w/2; MACD, EMA cross, volume, OBV, btc_trend fixed at 0; maximum 5.5 with every w = 1; no confidence threshold on the live path | – | `indicator_weights` via `_get_indicator_weights` (`:482-490`); a missing row or read error gives 1.0 | NOT VERIFIED (L-DB) | no | RC (code comments "240 / 262 trades"), AL (frozen) |
| STR-16 | Legacy-only filters | `signal_engine/signal_logic.py`: 4h primary ban `:631`; 1d bearish/sideways rejected at raw total_score ≥ 4.0 (around `:655`); stoch > 0 gate `:671`; BTC bonus and TF bonus; GLOBAL_LOSS_COOLDOWN_HOURS 6; MAX_SIGNALS_PER_DAY 5 | snapshot: cooldown 0, max per day 0 | partly via `optimizer_settings` | dormant if the live path is active (INFERRED) | no | H |
| STR-18, LRN-18 | Learned-gate threshold | `signal_engine/signal_logic.py:27-28` and `:741-743`: throttle a cell when n ≥ `MIN_CELL_N` 10 and weight ≤ 0; 10% hourly exploration (`:819-831`) | LEARNING_GATES_ENABLED – / false / false (code false); LEARNING_EXPLORATION_RATE Compose default 0.10; MIN_CELL_N snapshot 10 | `learned_gates` (NOT VERIFIED, L-DB) | inert while the flag is false (DOCUMENTED_ONLY; `docs/current_handoff_2026-08-17.md:13`) | no | AL (frozen) |
| STR-13 | Live cooldown and ranking | `signal_engine/signal_logic.py:25`: 2 h symbol cooldown, hard-coded; ranking min(spread, −volume, symbol, timeframe) (`:287-293`); one signal per 60 s | – | – | = code | no | M, CE |
| [IND-09 · SOURCE_VERIFIED] | Stop | `shared/signal_stop.py:16-46`: stop = min(level − 0.25·ATR, entry − 1.0·ATR), level = prior 20-bar high (momentum) or 20-bar low (reversion); reject if risk > 2/4/5/3% for 15m/1h/4h/1d (`technical_analyzer.py:425`); `stop_valid=None` passes, only an explicit False is rejected (`signal_logic.py:784`) | not settable | none | = code | no | M; caps RC (comment cites "2433 trades") |
| [IND-10 · SOURCE_VERIFIED] | Targets | `analyzer/technical_analyzer.py:454-467`: T1 1.0R, T2 1.8R, T3 2.2R; T1 capped at 0.99 × the 20-bar high including the decision bar (W3); no minimum R:R; no emergency stop | – | none | = code (L-T1) | no | T3 RC (code comment "0/168 touched 3R", 2026-04-27); T1, T2 M |
| EXE-10, EXE-11, EXE-13 | Exit management (tracker, bb7825f) | partial exits 25/50/25; break-even after T1 ≈ entry × 1.004 (`shared/triple_barrier.py:92-96`); trailing after T2 = max(T1, peak × 0.975); time stops 15m 48/24/12 h, 4h 96/48/24 h, 1d 240/120/72 h; STOP_SLIPPAGE 0.001; FEE_ROUNDTRIP_PCT 0.3 | snapshot 0.001 / 0.3; TRADE_AMOUNT_USDT 50 | none | NOT VERIFIED (snapshot) | no | M |

*Evidence (matrix):* the files and lines in each row · ea8ae4f for analyzer and signal_engine code, bb7825f for tracker code, scanner blobs per RT-39 · observed n/a · runtime-verified: no · limits: L-IMG, L-ENV, L-DB, L-T1.

## 5. Configuration precedence and database overrides

[CAL-01 · SOURCE_VERIFIED] Configuration precedence:

1. Compose `environment:`
2. `.env` (via `env_file`)
3. the dataclass default read at import

Notes:
- No strategy or universe variable is set in any Compose `environment:` block, so every strategy value comes from the unread `.env`.
- Hard-coded constants cannot be overridden.
- The only database override is `optimizer_settings` min_score/min_tf, on the legacy path, with DB > env > default.
- `indicator_weights` have no env counterpart; they multiply score parts, with a default of 1.0.

| Value family | Where it can be set | Precedence | Applies on the live path? |
|---|---|---|---|
| Indicator periods, regime, stop rule, targets, cooldown, ranking, FLAT_EPS | hard-coded constants | code only | yes (= code, L-IMG) |
| MOM_*, REV_*, MAX_SPREAD_PCT, macro settings, TIMEFRAMES, MIN_VOLUME_USDT, fees, slippage, TRADE_AMOUNT_USDT, flags | `.env` via `env_file`, else the dataclass default | Compose `environment:` > `.env` > default (no strategy key is set in Compose) | yes (values NOT VERIFIED) |
| `PAPER_ECONOMIC_HALT_MODE=observe` (telegram, trade_tracker) and `EVIDENCE_V2_ENABLED` | literal values in Compose `environment:` | Compose wins | yes |
| `LEARNING_*` | Compose defaults | effective value NOT VERIFIED; `LEARNING_CLEAN_START` and `LEARNING_CONFIDENCE_Z` are unread (CON-15) | exploration is inert while learned gates are off |
| min_score, min_tf | `optimizer_settings` (DB), then env, then default | DB > env > default | no (legacy path only) |
| `indicator_weights` | DB only (default 1.0) | DB, else 1.0 | only ordering and truncation (LRN-16) |
| `learned_gates` | DB only (written by the stopped learner) | read only when `LEARNING_GATES_ENABLED` is true | no (flag false per snapshot) |

*Evidence:* `shared/config.py` (dataclass defaults), `docker-compose.yml` blob d1a4b197 (= main, RT-24), `signal_engine/signal_logic.py:295-307` · ea8ae4f · runtime-verified: no · limits: L-ENV, L-DB.

[CAL-02 · DOCUMENTED_ONLY] Configured values come from the committed resolved-config snapshot `deploy/baseline-2026-09-27/config/*.nonsecret.json` (2026-09-27). It was taken before every current container start (analyzer, scanner, signal_engine and postgres 2026-10-19; collector 2026-10-22; telegram and trade_tracker 2026-10-27; RT-09). `.env.example` values are cited via `docs/ops/ENV_EXAMPLE_REVIEW_2026-10-18.md`, which itself flags `.env.example` as misleading (line 20).
*Evidence:* snapshot files and review document · documents at ebf8d8a · runtime-verified: no · limits: a point-in-time snapshot taken before the current containers started; non-secret values only.

[CAL-03 · NOT_VERIFIED] No effective runtime value is verified: runtime-verified is "no" for every parameter in section 4. Every database value requires authorization: `optimizer_settings`, `indicator_weights`, `learned_gates` and `symbol_blacklist` (OQ-01, OQ-02).
*Evidence:* none (access not authorized) · limits: all "effective" columns are snapshot or code values only.

The repository's entry-point statement that live DB thresholds override `.env` is recorded as CON-11 (section 10).

## 6. Calibration provenance, validation methodology and version boundaries

[CAL-04 · SOURCE_VERIFIED] Parameter provenance is PARTIAL. It is spread across code comments with sample counts, `docs/claude/strategy-history.md` and commit messages. There is no parameter registry.

[CAL-05 · SOURCE_VERIFIED] Calibration datasets are UNDOCUMENTED. Code comments give trade counts only, with no window, symbol list, hash or cost model.

[CAL-06 · INFERRED] The calibration samples are in-sample bot history.

[CAL-07 · SOURCE_VERIFIED] Validation methodology is UNDOCUMENTED for deployed values. The A29–A34 governance documents and [EVIDENCE_LADDER_PARAMETERS.md](../../strategy/EVIDENCE_LADDER_PARAMETERS.md) are not linked to any deployed threshold.

| Parameter group | Value(s) | Provenance recorded | Class | Dataset documented? |
|---|---|---|---|---|
| Indicator periods (IND-01) | RSI 14, MACD 12/26/9, EMA 20/50/200, BB 20/2σ, ATR 14, StochRSI 14/3/3, ADX 14, volume MA 20 | none (plain constants) | M | no |
| Momentum trigger (STR-07) | 20 bars; 1.2 × volume | hand-set; "operational starting points, not evidence of edge" (STR-23) | M | no |
| Reversion trigger (STR-08) | RSI 35; %b 0.20 | hand-set (STR-23) | M | no |
| Regime (STR-09) | ADX 25 / 20; percentile 0.75; 5-bar slope; 100-bar window | none | M | no |
| Macro gate (STR-11) | −5% over 18 × 4h; +0.5 pp; 2 h; 1 h cache; FLAT_EPS 0.05 | none | M | no |
| Spread gate (IND-03) | 0.15% | Live gate: no provenance recorded. The legacy path has its own MAX_SPREAD_PCT gate after the stoch>0 gate (around `signal_logic.py:675-680` at ea8ae4f); its code comment (2026-06-23 audit) calls it an execution-feasibility filter, not an edge filter (publication re-check) | M | no |
| Stop timeframe caps (IND-09) | 2/4/5/3% | code comment cites "2433 trades" | RC | count only |
| T3 target (IND-10) | 2.2R | code comment "0/168 touched 3R" (2026-04-27) | RC | count only |
| T1, T2 targets (IND-10) | 1.0R, 1.8R | none | M | no |
| Universe volume floor (UNI-09) | 10M USDT | raised on 2026-04-27 | M | no |
| min_score (IND-05, IND-06) | documented DB value 3.0 | `docs/claude/strategy-history.md:8`, set on 2026-05-16; contested: DEV_LOG L67-68 raises min_score from 3 to 4 while strategy-history keeps 3.0 (CON-40) | RC | no |
| Legacy 1d raw-score rule (STR-16) | 4.0 | code comment: 2,433 trades, n = 251 for the cell | RC | count only |
| Legacy 4h primary ban (STR-16) | ban | code comment: 275 post-rebuild trades, 2026-04-22 to 2026-05-16 (SOURCE_VERIFIED, publication re-check) | RC | count and window only |
| `indicator_weights` (IND-07) | per indicator × condition | code comments "240 / 262 trades"; optimizer gross rules (LRN-12); colab correlation (LRN-13) | RC / AL | no |
| Learned gates (STR-18) | binary per cell | learner output, frozen since 2026-08-17; window starts at `LEARNING_CLEAN_START` 2026-07-20 (LRN-06) | AL | rule in code; data not read |
| Cost constants (EXE-13) | FEE_ROUNDTRIP_PCT 0.3; STOP_SLIPPAGE 0.001 | config description "0.1%/side + ~0.1% slippage" | M | no |

*Evidence:* code comments and documents cited in the rows · ea8ae4f / ebf8d8a · runtime-verified: no · limits: comments are not calibration records. No window, symbol list, hash or cost model is attached to any count (CAL-05).

[CAL-08 · DOCUMENTED_ONLY] Version boundaries are documented for code and images. The records are DEPLOYED.json, `deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json` (level L1, content-verified) and [VERSION_BOUNDARY.md](../../../deploy/VERSION_BOUNDARY.md). The latter holds one boundary, VB-2026-10-27-01: econ-enforce → econ-observe.
*Evidence:* [DEPLOYED.json](../../../deploy/DEPLOYED.json), the runtime manifest and the version-boundary record · main eba90dd · runtime-verified: the DEPLOYED.json entries match the live containers (RT-35), but image content parity remains DOCUMENTED_ONLY (RT-16).

[CAL-09 · SOURCE_VERIFIED] Version boundaries are weak for data:
- `learned_gates` rows carry `strategy_version` and `learning_run_id`.
- `optimizer_settings` and `indicator_weights` have only `updated_at` / `last_updated`, so they have no lineage, no history and no rollback.
- `APP_VERSION` defaults to `sb-2026.06` (`shared/config.py:45`).
*Evidence:* `database/init.sql` (identical in production and main), `shared/config.py:45` · ea8ae4f · runtime-verified: no · limits: L-DB.

[CAL-10 · NOT_VERIFIED] The actual `APP_VERSION` / `strategy_version` emitted by the running services.
*Evidence:* would require `.env` or database access (not authorized) · limits: version attribution of any runtime signal is unverified.

## 7. Paper execution lifecycle

All lifecycle statements are SOURCE_VERIFIED at ea8ae4f (analyzer, signal_engine), at the scanner blobs listed in `deploy/baseline-2026-09-27/deployed_files.json` (scanner_logic.py fa03cc2a, equal to ea8ae4f; shared/config.py c5c03b5c from 7bf6214; RT-39), or at bb7825f (telegram, trade_tracker). L-IMG applies throughout. The flow is scanner → analyzer → signal_engine → outbox `signal.ready` → telegram → trade_tracker; see ARC-01 and ARC-02 in [RUNTIME_AND_PARITY.md](RUNTIME_AND_PARITY.md).

### 7.1 Generation and the ordered signal-engine gates

[EXE-01 · SOURCE_VERIFIED] Generation:
- The scanner writes `scan_candidates` every 300 s.
- The analyzer upserts `analysis_results` per (symbol, timeframe) and resets `signal_generated` on each pass.
- `signal_engine` polls every 60 s and applies, in order:
  1. the macro gate (STR-11);
  2. setup present (STR-07 or STR-08);
  3. order book valid, with a finite spread ≤ 0.15% (IND-03);
  4. `stop_valid` (IND-09);
  5. no open trade, and the 2 h symbol cooldown. The cooldown fails open on a DB error in off mode: a read error becomes an empty set (`signal_logic.py:424-432`);
  6. the learned gate (off; STR-19);
  7. rank (STR-13);
  8. one transaction that inserts the `signals` row and the outbox `signal.ready` event.
- `signal_engine` has no pause check.

*Evidence:* `signal_engine/main.py`, `signal_engine/signal_logic.py:424-432, 722-831` · `find_best_signal_live`, `save_signal` · ea8ae4f · runtime-verified: no · limits: L-IMG.

### 7.2 Delivery

[EXE-02 · SOURCE_VERIFIED] Telegram's `can_deliver_candidate` (`telegram/main.py:364-382`) blocks on the pause (fails closed). It also enforces capacity min(10, `RISK_CANARY_MAX_OPEN_TRADES`), whose code default is 1. A refused candidate is acknowledged and lost.
*Evidence:* `telegram/main.py:249-294, 364-382` · `handle_candidate_event`, `can_deliver_candidate` · bb7825f · runtime-verified: no · limits: L-IMG.

[EXE-03 · DOCUMENTED_ONLY] `RISK_CANARY_MAX_OPEN_TRADES` is 2 in the snapshot and in `.env.example`. The effective value is NOT VERIFIED (CON-16).
*Evidence:* snapshot; `docs/ops/ENV_EXAMPLE_REVIEW_2026-10-18.md` · limits: L-ENV.

### 7.3 Admission

[EXE-04 · SOURCE_VERIFIED] `trade_tracker` `register_new_signals` (`main.py:705-904`):
- It keeps the latest signal per symbol within 2 h.
- It allows one open trade per symbol, and one per (symbol, timeframe) per candle interval.
- It admits only signals that are `telegram_sent`, ready and under 2 h old. `signal.delivered` is used only for reconciliation.
- There is no flash/scalp/swing taxonomy in this code: trade types are momentum and reversion.
- There is no one-per-kind rule, and no DB unique index enforces one trade per symbol.
*Evidence:* `trade_tracker/main.py:646-679, 705-904` · `register_new_signals` · bb7825f · runtime-verified: no · limits: L-IMG.

### 7.4 Candle closure and look-ahead

[EXE-05 · SOURCE_VERIFIED] Candle closure and look-ahead:
- `shared/ohlcv.py:closed_klines` keeps rows with `close_time` < now on the host clock.
- Gaps, duplicates and NaN are rejected (`shared/ohlcv.py:26-83`).
- The breakout and volume baselines exclude the current bar.
- The order book is a single "now" snapshot reused across timeframes.
*Evidence:* `shared/ohlcv.py:26-83` · `closed_klines`, `validate_ohlcv` · ea8ae4f · runtime-verified: no · limits: L-IMG.

[EXE-06 · INFERRED] There is no exchange server-time sync, so host clock skew could admit a forming bar.

### 7.5 Entry

[EXE-07 · SOURCE_VERIFIED] The entry rules:
- The planned entry is the last closed close.
- At admission the tracker reads the REST `ticker/price` last trade.
- `decide_long_entry` rejects if price ≤ max(stop, invalidation).
- It fills at the observed price if that price is ≤ planned.
- Otherwise it waits (`limit_wait`, no chasing) until the 2 h window ends.

Implementation details:
- Fill model `observed_price_v0` is the code default; `resting_limit_v1` is off.
- `paper_entry_orders` rows are written but do not drive fills.
- `rebase_long_bracket` scales the stop and targets by fill/planned.

Not modelled: bid/ask, latency, partial fills, tick/lot rounding, entry slippage.
*Evidence:* `trade_tracker/main.py` (admission path; public REST `/api/v3/ticker/price`, line 1435), entry execution helpers · `decide_long_entry`, `rebase_long_bracket` · bb7825f · runtime-verified: no · limits: L-IMG; the fill is simulated (EXE-20).

[EXE-08 · NOT_VERIFIED] The effective `PAPER_ENTRY_FILL_MODEL` value (`.env`). The code accepts `observed_price_v0` or `resting_limit_v1` and refuses to start on an unknown value (`shared/config.py:112` at bb7825f).

### 7.6 Freshness

[EXE-09 · SOURCE_VERIFIED] In off mode only two ages are checked: the 30-minute age of the analysis row and the 2 h signal window. Candle age is never checked, so a 1d bar can be about 24 h old at signal time. The ≤ 1-bar freshness rule exists only in integrity enforce mode (STR-33).
*Evidence:* `signal_engine/main.py:146-155` (30-minute row filter), `shared/signal_identity.py:186-200` (enforce only) · ea8ae4f · runtime-verified: no · limits: L-IMG, L-ENV.

### 7.7 Stop management

[EXE-10 · SOURCE_VERIFIED] Stop management in `shared/triple_barrier.py`, by stage:
- **Before T1:** the signal stop applies (IND-09).
- **After T1:** a net break-even stop = min(T1, entry × 1.003/0.999) ≈ entry × 1.004 (`triple_barrier.py:92-96`), about +0.40%; when W3 caps T1 below that level the stop equals T1.
- **After T2:** a trailing stop = max(T1, peak × 0.975).
- **Stop fill:** min(stop, observed tick) × 0.999, so a gap fills at the observed price −0.1%.
- **Invalidation exit:** before T1, a closed bar at or below the invalidation level exits at the current price.
- **Emergency stop:** none.

*Evidence:* `shared/triple_barrier.py:92-96`, `trade_tracker/main.py:1189-1304` (`evaluate_trade`) · bb7825f (the stop, target and exit `shared/*` modules are byte-identical to ea8ae4f) · runtime-verified: no · limits: L-IMG; fills are simulated (EXE-20).

### 7.8 Targets and time exits

[EXE-11 · SOURCE_VERIFIED] Targets and time exits:
- Partial exits of 25/50/25% at T1/T2/T3 (`shared/partial_exits.py`), each filled exactly at the target price on a last-trade touch.
- Expiry exits at the current price, with no slippage.
- Forced closes on blacklist, and on max-open overflow (`enforce_max_open_trades`, `trade_tracker/main.py:508`).

| Timeframe | Maximum holding | Stalled after T1 | No T1 reached |
|---|---|---|---|
| 15m | 48 h | 24 h | 12 h |
| 4h | 96 h | 48 h | 24 h |
| 1d | 240 h | 120 h | 72 h |

The sources give time stops for 15m, 4h and 1d only; values for 1h (in the code-default TIMEFRAMES) are NOT VERIFIED.

The exit label `T1_expired_24h` is hard-coded regardless of timeframe (CON-18).
*Evidence:* `shared/partial_exits.py`, `shared/triple_barrier.py`, `trade_tracker/main.py:508` · bb7825f · runtime-verified: no · limits: L-IMG; the touch fill is optimistic (HIS-32).

### 7.9 Sizing and R:R

[EXE-12 · SOURCE_VERIFIED] Sizing is a fixed `TRADE_AMOUNT_USDT` of 50 against a virtual capital of 500.
- There is no risk-based or volatility sizing; the tracker never reads `signals.size_multiplier`.
- R:R is geometric only: there is no runtime R:R minimum and no cost gate.
*Evidence:* `shared/config.py` (`TRADE_AMOUNT_USDT`), tracker admission path · bb7825f · runtime-verified: no · limits: L-IMG, L-ENV (snapshot value 50).

### 7.10 Costs

[EXE-13 · SOURCE_VERIFIED] Cost constants:

| Constant | Value |
|---|---|
| `FEE_ROUNDTRIP_PCT` (`shared/config.py:92`) | 0.3, described as 0.1%/side plus about 0.1% slippage |
| `STOP_SLIPPAGE` (`:107`) | 0.001 |
| `triple_barrier.ROUNDTRIP_COST_DEFAULT` | 0.003 |
| `MIN_ORDER_NOTIONAL_USDT` | 5 |
| `MAX_SPREAD_PCT` | 0.15, used only as a selection filter |

[EXE-14 · SOURCE_VERIFIED] How costs are applied:
- `profit_percent` and `profit_usdt` are stored gross.
- `shared/fees.py:economic_close` (lines 41-74) charges cost_usdt = 50 × 0.3% = $0.15 flat per trade, whatever the legs. Net = gross − 0.15.
- Stop exits are additionally multiplied by 0.999, which A47 flags as double counting (CON-17).
- The break-even level, risk snapshots, the learner and the Telegram reports all use 0.3.

[EXE-15 · INFERRED] The effective modelled cost:
- It is 0.30% round trip on target, expiry and invalidation exits, and about 0.40% on stop exits.
- There is no spread cost, because prices are last trades.
- It is below the 0.40% round-trip baseline of the owner-approved Design A cost model (STR-39) except on stops, and always below that model's 0.60% stress.

| Cost model | Round-trip level | Components | Where | Class |
|---|---|---|---|---|
| Runtime Paper accounting | 0.30% flat ($0.15 on $50) on target, expiry and invalidation exits; about 0.40% on stop exits | FEE_ROUNDTRIP_PCT 0.3 (fee plus slippage as described); STOP_SLIPPAGE 0.001 on stops; no spread | `shared/config.py:92, 107`; `shared/fees.py:41-74` | constants SOURCE_VERIFIED (EXE-13, EXE-14); effective level INFERRED (EXE-15) |
| Design A v1.0 cost model (owner-approved specification) | 0.40% baseline; 0.60% stress | fee 0.10%/side + half-spread 0.05% + slippage 0.05%; stress 0.30%/side | `docs/strategy/DESIGN_A_SPEC_v1.0.md` on `feature/design-a-v1` | SOURCE_VERIFIED (STR-39) |
| S4 mechanism cost model | not stated as one figure in the sources | fee 0.10%/side; half-spread 0.01% BTC/ETH, 0.04% others; slippage 0.05%/side; ×2 stress | `docs/strategy/S4_MECHANISM_COMPARISON.md` §3 | SOURCE_VERIFIED (HIS-15) |
| Owner Operating Contract standard | 0.20% fees round trip, plus spread, slippage and other realistic costs | 0.10% per side fees | [OWNER_OPERATING_CONTRACT.md](../../governance/OWNER_OPERATING_CONTRACT.md) §1 | DOCUMENTED_ONLY (ECO-09) |

*Evidence:* `shared/config.py:92, 107`, `shared/fees.py:41-74`, `shared/triple_barrier.py` · bb7825f / ea8ae4f · runtime-verified: no · limits: L-IMG, L-ENV (snapshot 0.3 and 0.001). The comparison is arithmetic on documented models, not a measured cost.

### 7.11 Closure and P&L

[EXE-16 · SOURCE_VERIFIED] Closure (`close_trade_barrier`, `trade_tracker/main.py:1307-1401`):
- gross% = Σ fraction_i·(T_i/entry − 1)·100 + remaining·(exit/entry − 1)·100.
- USDT = gross% × 50/100.
- The stored exit price is the weighted average.
- `result` is labelled on gross; `economic_result` is labelled on net (net_profit_usdt, cost_usdt, label_policy).
- Idempotent through ON CONFLICT (signal_id).
*Evidence:* `trade_tracker/main.py:1307-1401`, `shared/fees.py:41-74` · bb7825f · runtime-verified: no · limits: L-IMG; gross versus net counters differ (CON-09).

### 7.12 Rejected, stale and duplicate signals

[EXE-17 · SOURCE_VERIFIED] Rejected, stale and duplicate signals:
- An entry reject is terminal.
- A risk reject is retried each loop within 2 h.
- Stale (> 2 h), blacklisted or rejected signals are acknowledged.
- A same-bar re-fire after the 2 h cooldown is possible for 4h/1d (A43 D1).
- The A43 and A38 integrity refusals apply only in enforce mode, which is flagged off (STR-33).
- A38 parts active without a flag: economic labels, entry-order rows, delivery reconciliation, and a 24 h notification TTL.
*Evidence:* `trade_tracker/main.py:705-904`, `telegram/main.py:449-539` · bb7825f · runtime-verified: no · limits: L-IMG, L-ENV; re-fire counts withheld (HIS-25).

### 7.13 Price source

[EXE-18 · SOURCE_VERIFIED] Price source:
- The Binance WebSocket aggTrade stream (last trade) covers symbols with open trades, plus a REST backup every 30 s (`binance_price_stream.py`).
- Reconnects use a 5–60 s backoff.
- The WebSocket cache is not used for decisions.

[EXE-19 · INFERRED] When the price queue is full the oldest tick is dropped, so barrier touches can be missed.
*Evidence:* `trade_tracker/binance_price_stream.py:12, 94-107` · bb7825f · runtime-verified: no · limits: L-IMG.

### 7.14 Execution-model classification

[EXE-20 · DOCUMENTED_ONLY] The execution model is SIMULATED on last-trade observations and has not been verified against exchange fills.
- A47 (`docs/a47/A47_EXECUTION_REALISM.md`) concludes "REVISE EXECUTION MODEL".
- A48 (`docs/a48/A48_REPLAY_FIDELITY.md:23`) establishes only level 1 (math) and level 2 (tracker parity: 6/6 in A47, 27/27 in A48). Level 3, exchange realism, is not established.
- A42–A46 replay numbers that involve stops must not be reused.
*Evidence:* A47 and A48 documents · documents at ebf8d8a · runtime-verified: no · limits: there is no order-placement code, so Paper-only is structural (ARC-11).

## 8. Risk controls and portfolio limits

[RSK-01 · SOURCE_VERIFIED] The risk gate is `evaluate_with_policy`, reached via `assess_new_trade_risk` (`trade_tracker/main.py:922-1006`) and `record_risk_decision` (`:1041-1093`).
- **Always blocking:** an invalid risk state, a persisted pause, and the exposure caps (gross 80%, symbol 10%, strategy 40%, regime 50%).
- **Observe mode:** the daily −3%, weekly −10%, drawdown 15% and 7-loss-streak checks are recorded only, as `risk.observed` (`observed:<check>`).
- **Enforce mode:** the same checks write a `risk:` pause.
- A NaN price gives `invalid_risk_state`.
- Observe requires `PAPER_TRADING=true`; an unknown mode falls back to enforce (`shared/economic_halt_policy.py:89-98`). The code default mode is enforce (`shared/config.py:131` at bb7825f).

| Control | Threshold | Enforce mode | Observe mode | Always blocking |
|---|---|---|---|---|
| Invalid risk state (for example a NaN price) | not applicable | pause | pause | yes |
| Persisted pause | not applicable | blocks | blocks | yes |
| Gross exposure cap | 80% | blocks | blocks | yes |
| Symbol exposure cap | 10% | blocks | blocks | yes |
| Strategy exposure cap | 40% | blocks | blocks | yes |
| Regime exposure cap (key: USDT.D trend, RSK-05) | 50% | blocks | blocks (PORTFOLIO_LIMITS) | yes |
| Daily loss | −3% | `risk:` pause | recorded as `risk.observed` | no |
| Weekly loss | −10% | `risk:` pause | recorded | no |
| Drawdown | 15% | `risk:` pause | recorded | no |
| Loss streak (B3) | 7 losses | `risk:` pause | recorded | no |
| Capacity (RSK-02) | min(10, RISK_CANARY_MAX_OPEN_TRADES); floor(500 × 80% / 50) = 8 | blocks | blocks | yes |

The deployed configuration for telegram and trade_tracker is `PAPER_ECONOMIC_HALT_MODE=observe`, set in Compose (RT-32). Whether the observe path is the one executing is NOT VERIFIED (RT-33), and the current pause state is NOT VERIFIED (RT-46). The paper-observe deployment record states "Validated: NO" for telegram and trade_tracker (RT-34); in telegram the mode only changes message text (ARC-08).
*Evidence:* `trade_tracker/main.py:922-1006, 1041-1093`, `shared/economic_halt_policy.py:89-98`, `shared/config.py:131` (bb7825f; line numbers differ at ea8ae4f, RT-37) · bb7825f · runtime-verified: no · limits: L-IMG, L-DB.

[RSK-02 · SOURCE_VERIFIED] Capacity is min(`MAX_OPEN_TRADES` 10, `RISK_CANARY_MAX_OPEN_TRADES`), and is also bounded by floor(500 × 80% / 50) = 8. The economic-halt sizing multipliers (drawdown caution/warning, weekly reduce/minimum) do not change the notional, but they can lower the capacity used by the max_open_trades check (`shared/economic_halt_policy.py:18-20`).
*Evidence:* `trade_tracker/main.py:708-716, 752-756`, `shared/economic_halt_policy.py:18-20` · bb7825f (publication re-check) · runtime-verified: no · limits: L-ENV.

[RSK-03 · DOCUMENTED_ONLY] Effective capacity is 2 open positions, or 1 when the sizing multiplier is ≤ 0.5. This is as cited from `docs/ops/PAPER_ECONOMIC_OBSERVATION.md`.
*Evidence:* that document (cited by the universe investigation) · limits: depends on the NOT VERIFIED `RISK_CANARY_MAX_OPEN_TRADES` value (EXE-03).

[RSK-04 · INFERRED] The strategy (40%) and regime (50%) caps correspond to 4 and 5 trades, so they never bind with 2 slots.

[RSK-05 · SOURCE_VERIFIED] The regime-cap key is COALESCE(macro_snapshot->>'usdtd_trend', market_condition). It feeds `assess_new_trade_risk` → `regime_open_count` → `evaluate_new_trade` and its `regime_concentration_limit`. Per `economic_halt_policy.PORTFOLIO_LIMITS`, this portfolio limit blocks even in observe mode.
*Evidence:* `trade_tracker/main.py:922-1006`, `shared/economic_halt_policy.py` · bb7825f · runtime-verified: no · limits: L-IMG.

[RSK-06 · INFERRED] Capital utilisation is at most 20%: 2 × $50 of the $500 virtual capital.

## 9. Learning and optimisation

| System | Enabled? | Data and target | Statistics and safeguards | Effect now |
|---|---|---|---|---|
| `continuous_learner` (LRN-03 to LRN-08) | No. Stopped since 2026-08-17 (DOCUMENTED_ONLY, LRN-04); it would build from the production working tree (LRN-03) | the newest 150 trades after `LEARNING_CLEAN_START` (2026-07-20); per-cell net expectancy = profit% − 0.3 | n ≥ 10; normal interval with z = 1.96; no multiple-testing correction; 10% exploration; rollback script | none while the flag is false. If enabled, throttles written on or before 2026-08-17 would apply immediately and indefinitely (LRN-19) |
| optimizer (LRN-09 to LRN-12) | No. Compose profile `disabled`, dated 2026-06-19 by a Compose comment (LRN-10) | gross win rate and average profit; indicator weights | no statistical test; weight 0 for any indicator that fired fewer than 20 times; overwrites without history | its frozen weights are read on every analysis (LRN-16) |
| `colab/daily_training.py` (LRN-13, LRN-14) | Historical; whether it ever ran is NOT VERIFIED | correlation of each indicator with a win | no significance test | none beyond the weights it may have written |

### 9.1 Schemas

[LRN-01 · SOURCE_VERIFIED] Learning-related schemas. The production `database/init.sql` is identical to main.

| Table | Contents |
|---|---|
| `learned_gates` | Primary key (trade_type, macro_state, timeframe). Columns: n, wr, expectancy, weight, ci_low/ci_high, sample_start/sample_end, strategy_version (default `'legacy'`), learning_run_id (foreign key, NOT VALID), updated_at. No expiry, TTL or active column. |
| `learning_runs` | status (validating / applied / rejected / rolled_back), counts, parameters JSON, validation_errors |
| `learned_gate_history` | action (insert / update / expire / rollback) with old and new values as JSONB |
| `optimizer_settings` | (key, value TEXT, updated_at). Seeds min_score_to_signal 5.0 and min_timeframe_confirmations 2, with ON CONFLICT DO NOTHING. |
| `indicator_weights` | indicator × condition; weight DEC(5,4), default 1.0; last_updated; seeded at `init.sql:219` |

Migration 006 resets every gate to weight 1.0, with strategy_version `pre-statistical-reset`.
*Evidence:* `database/init.sql`, migrations · ea8ae4f (production file identical to main, RT-03) · runtime-verified: no · limits: L-DB (no row was read).

[LRN-02 · NOT_VERIFIED] When migration 006 was applied.

### 9.2 continuous_learner

[LRN-03 · SOURCE_VERIFIED] `continuous_learner` (`research/continuous_learner.py`, identical at ea8ae4f and main):
- Compose profile `["learner"]`, restart `unless-stopped`, a loop every `LEARN_CRON_HOURS` (12).
- Compose builds it from `signal_engine/Dockerfile` in the production working tree (63da7d3 plus local modifications), not from a pinned release image.
*Evidence:* `docker-compose.yml` blob d1a4b197, `research/continuous_learner.py` · ea8ae4f / main · runtime-verified: the container state is observed in RT-10 and RT-11; the build path is from the Compose source.

[LRN-04 · DOCUMENTED_ONLY] DEPLOYED.json records the learner as exited: "stopped since 2026-08-17; must stay stopped".

[LRN-05 · INFERRED] A learner restart would therefore run undeployed code.

[LRN-06 · SOURCE_VERIFIED] Learner data and target:
- **Data:** trade_results joined to signals where exit_time ≥ `LEARNING_CLEAN_START` (default 2026-07-20). It uses the newest `ROLL_N` = 150 trades after a warm-up of `WARMUP_N` = 100.
- **macro_state:** taken from `macro_snapshot.usdtd_trend`.
- **Target:** per-cell net expectancy = profit_percent − 0.3.
- **Writes:** `learned_gates` (binary weight, 0 or 1), `learning_runs` and `learned_gate_history`.
- **Deletes:** throttled cells older than `THROTTLE_STALE_DAYS` = 14.

[LRN-07 · SOURCE_VERIFIED] Learner statistics and safeguards:
- A cell can be throttled only with n ≥ 10.
- The interval is a normal approximation, ± z·sd/√n with z = 1.96. A cell is throttled only when ci_high ≤ 0, so the rule fails open.
- There is no multiple-testing correction across up to 32 cells, and no dependence adjustment.
- Runtime exploration (`learning_governance.exploration_selected`) uses a blake2b hash of (symbol, type, macro state, timeframe) per UTC hour, at rate 0.10.
- `validate_cells` checks allowed keys, value ranges, weight ∈ {0, 1}, and that undersized cells cannot be throttled.
- An invalid batch is recorded as a rejected run; the apply is transactional.
- Rollback: `research/rollback_learned_gates.py RUN_ID` restores old_value from the history table.
- There is no out-of-sample test, no holdout and no human approval in code.
*Evidence:* `research/continuous_learner.py`, `research/rollback_learned_gates.py` · ea8ae4f / main · runtime-verified: no · limits: L-IMG, L-DB.

[LRN-08 · INFERRED] Learner risks:
- A feedback loop and selection bias: it trains only on trades that passed its own gates, so throttled cells are re-sampled only via exploration or the 14-day deletion.
- Overlapping trades inflate the effective n.
- Heavy tails make the n = 10 normal interval anti-conservative.
- The cost model is a flat 0.3%.
- The runtime read does not filter on strategy_version.

### 9.3 optimizer

[LRN-09 · SOURCE_VERIFIED] The optimizer (`optimizer/main.py`, `tuner.py`, `analyzer.py`, identical at ea8ae4f and main):
- It is disabled by the Compose profile `["disabled"]`, builds from the working tree, and is not among the DEPLOYED.json services.
- Its data are the last 30 days of signals joined to trade_results, with signal_time ≥ 2026-04-22.
- It runs hourly and needs at least 10 trades.

[LRN-10 · DOCUMENTED_ONLY] The Compose comment dates the optimizer disable to 2026-06-19.

[LRN-11 · SOURCE_VERIFIED] `tuner.py` writes `optimizer_settings` using gross win rate and average profit only. It applies no statistical test.

| Condition | Adjustment |
|---|---|
| WR ≥ 55% and average profit ≥ 1.5% | min_score −0.5 |
| WR < 30% | min_score +1.0 and min_tf +1 |
| WR < 40% | min_score +0.5 |
| Bounds | min_score [1.5, 3.5]; min_tf [1, 2] |

[LRN-12 · SOURCE_VERIFIED] `optimizer/analyzer.py:update_indicator_weights` writes `indicator_weights`:
- It needs ≥ 20 samples per indicator × condition.
- weight = 1 + 0.5 × (mean PnL when the indicator is active − mean PnL when inactive), clamped to [0, 2.5].
- An indicator that fired fewer than 20 times gets weight 0.0.
- `rsi_divergence`/sideways is pinned at 2.0.
- It uses gross PnL, no confidence interval and no out-of-sample test, and overwrites values in place with no history.
*Evidence:* `optimizer/tuner.py`, `optimizer/analyzer.py` · ea8ae4f / main · runtime-verified: no · limits: not running; its past outputs in the DB are NOT VERIFIED (LRN-20).

### 9.4 colab notebook

[LRN-13 · SOURCE_VERIFIED] `colab/daily_training.py` (code from 2026-04-14; a manual notebook):
- It needs ≥ 20 trades and ≥ 5 per condition.
- weight = clamp(1 + corr(indicator, win), 0.3, 2.0), written to `indicator_weights` through an external DB configuration.
- It applies no significance test. HISTORICAL.

[LRN-14 · NOT_VERIFIED] Whether `colab/daily_training.py` ever ran.

### 9.5 Components that are not learners

[LRN-15 · SOURCE_VERIFIED] Components that are not learners:
- `strategy_performance_review.py`: an offline 5-fold walk-forward report.
- `research/null_a/*`: no DB writes.
- `shared/execution_calibration.py`: research parity checks and a cost ledger, with no I/O and no runtime import.
- The analyzer only reads weights.

### 9.6 Runtime consumption of learned and optimised values

[LRN-16 · SOURCE_VERIFIED] `indicator_weights`:
- Read on every analysis, with no cache and no staleness check.
- They fully drive the legacy decision.
- On the live path they affect only ordering and truncation (`signal_engine/main.py:146-155`, `ORDER BY symbol, total_score DESC LIMIT 200`) plus the recorded score.

`optimizer_settings`:
- Read by `_get_live_thresholds` on the legacy path only.
- Displayed by telegram `/status` (`telegram/main.py:725-731` at bb7825f).

*Evidence:* `analyzer/technical_analyzer.py:482-490`, `signal_engine/main.py:146-155`, `telegram/main.py:725-731` · ea8ae4f / bb7825f · runtime-verified: no · limits: L-IMG, L-DB.

[LRN-17 · INFERRED] Stale, frozen learned weights still steer today. If the live path is active the effect is marginal: they order timeframes within a symbol and influence the alphabetical truncation.

[LRN-18 · SOURCE_VERIFIED] `learned_gates` access:
- Read through `LEARNED_GATES_SQL` in `find_best_signal_live` and the enforce path (`signal_logic.py:27-28, 390-394, 741-743`; exploration `819-831`), guarded by `LEARNING_GATES_ENABLED`.
- The query `WHERE macro_state=$1 AND n>=$2 AND weight<=0` has no filter on updated_at, strategy_version or run status.
- On a read error, enforce mode retries via `guarded_read` and then blocks the cycle; off mode aborts the cycle.
*Evidence:* `signal_engine/signal_logic.py:27-28, 390-394, 741-743, 819-831` · ea8ae4f · runtime-verified: no · limits: L-IMG, L-ENV, L-DB.

[LRN-19 · INFERRED] If `LEARNING_GATES_ENABLED` were ever set to true, throttles written on or before 2026-08-17 would apply immediately and indefinitely, because expiry exists only in the stopped learner. Exploration would still let about 10% through.

### 9.7 Not verified in learning

[LRN-20 · NOT_VERIFIED] The contents of `learned_gates`, `indicator_weights` and `optimizer_settings`, whether any `learned_gates` rows exist, and the runtime `LEARNING_GATES_ENABLED` value (OQ-01, OQ-02).

## 10. Contradictions in this area

Each entry records where repository sources disagree with each other or with the code read at the documented commits. Contradictions about runtime, the market context and research history are held in the other topic documents (CON-01 to CON-08, CON-10, CON-19, CON-27 to CON-48).

- [CON-09 · CONTRADICTORY] Two outcome views use different bases:
  - the `risk_management` wins/losses counters and `/status` use gross labels;
  - `/stats` uses net labels.
  Operational counters therefore present gross outcomes (ECO-03).
  *Evidence:* `trade_tracker/main.py` result recording, `telegram/main.py` reports · bb7825f · limits: code reading only.
- [CON-11 · CONTRADICTORY] CLAUDE.md:46, and the production copy at line 21, say that live thresholds in the DB (`optimizer_settings` / `indicator_weights`) override `.env`. In code this holds only for two `optimizer_settings` keys, and only on the legacy path (CAL-01).
  *Evidence:* `CLAUDE.md`, `signal_engine/signal_logic.py:295-307` · main / ea8ae4f.
- [CON-12 · CONTRADICTORY] Some documents describe the min_score, stoch>0 gate, 4h ban and multi-timeframe narratives as live. They belong to the legacy path only (STR-14 to STR-16, IND-04), and 4h is not banned on the live path.
  *Evidence:* `signal_engine/signal_logic.py:631, 671`, `signal_engine/main.py:173-176` · ea8ae4f.
- [CON-13 · CONTRADICTORY] min_score has five different values:

  | Source | Value |
  |---|---|
  | code default | 5 |
  | `.env.example` and the snapshot | 7 |
  | DB seed | 5.0 |
  | documented DB value | 3.0 |
  | tuner bounds | 1.5–3.5 |

  The seed lies outside the tuner bounds.
  *Evidence:* `shared/config.py`, `database/init.sql`, `docs/claude/strategy-history.md:8`, `optimizer/tuner.py` · ea8ae4f / main.
- [CON-14 · CONTRADICTORY] The score scale is inconsistent:
  - the maximum score is 5.5, but `analyzer/main.py:178` logs it as "/10";
  - the legacy env min_score of 7 is unreachable when weights are 1.0;
  - MACD, EMA, volume and OBV are computed but score 0.
  *Evidence:* `analyzer/technical_analyzer.py:323-402`, `analyzer/main.py:178` · ea8ae4f.
- [CON-15 · CONTRADICTORY] Some configuration names are set or documented but never read:
  - `TIMEFRAMES_LL` is documented, but nothing reads it;
  - `LEARNING_CLEAN_START` and `LEARNING_CONFIDENCE_Z` are set on signal_engine, but nothing there reads them.
  *Evidence:* `shared/config.py`, Compose `environment:` for signal_engine · ea8ae4f / blob d1a4b197.
- [CON-16 · CONTRADICTORY] `RISK_CANARY_MAX_OPEN_TRADES` defaults to 1 in code but is 2 in `.env.example` and the snapshot. The effective value is NOT VERIFIED (EXE-03).
  *Evidence:* `shared/config.py`; snapshot; `docs/ops/ENV_EXAMPLE_REVIEW_2026-10-18.md`.
- [CON-17 · CONTRADICTORY] Slippage is counted twice on stop exits:
  - `FEE_ROUNDTRIP_PCT` already includes slippage;
  - stop exits add `STOP_SLIPPAGE` again (EXE-14);
  - `shared/execution_calibration.py:349-362` documents the double count.
  *Evidence:* `shared/config.py:92, 107`, `shared/triple_barrier.py`, `shared/execution_calibration.py:349-362` · ea8ae4f / bb7825f.
- [CON-18 · CONTRADICTORY] The exit label `T1_expired_24h` is hard-coded, although the actual stalled-after-T1 time is 48 h for 4h and 120 h for 1d (EXE-11).
  *Evidence:* `shared/triple_barrier.py` · bb7825f.
- [CON-20 · CONTRADICTORY] The comment at `analyzer/technical_analyzer.py:351-354` is valid only when w_rsi = 1.0.
  *Evidence:* `analyzer/technical_analyzer.py:351-354` · ea8ae4f.
- [CON-21 · CONTRADICTORY] A42, A45, A46 and A47 analysed commit 59297305, but ea8ae4f is the version deployed, so their code-level findings were made on a different commit from the one documented as running.
  *Evidence:* the A42 to A47 documents; DEPLOYED.json · documents at ebf8d8a.
- [CON-22 · CONTRADICTORY] `T1_CAP_POLICY` is on main and bb7825f but absent from the documented-deployed analyzer source (ea8ae4f; image content NOT VERIFIED, RT-17). Main therefore does not describe that source's T1 behaviour (STR-17).
  *Evidence:* `shared/t1_cap.py`, `shared/config.py:124` (bb7825f, main) versus `analyzer/technical_analyzer.py:463-467` (ea8ae4f).
- [CON-23 · CONTRADICTORY] The S3 document says that a NaN spread passes; ea8ae4f fixes that (`finite_spread_pct`).
  *Evidence:* `docs/s3/S3_SIGNAL_SELECTION.md`; `signal_engine/signal_logic.py` · ea8ae4f.
- [CON-24 · CONTRADICTORY] `btc_bonus` uses the symbol's own regime, not BTC's, despite its name (legacy path).
  *Evidence:* `signal_engine/signal_logic.py` (legacy scoring) · ea8ae4f.
- [CON-25 · CONTRADICTORY] The calibration of the stoch>0 gate predates 63da7d3's change of StochRSI from K=14 to 14/3/3.
  *Evidence:* `signal_engine/signal_logic.py:671` comment; 63da7d3 · ea8ae4f.
- [CON-26 · CONTRADICTORY] The telegram code comment at `telegram/main.py:725-731` (bb7825f) says the optimizer updates `optimizer_settings` automatically, but the optimizer is disabled (LRN-09).
  *Evidence:* `telegram/main.py:725-731` · bb7825f.

## 11. Not verified in this area and related open questions

**Findings whose class is NOT_VERIFIED:**

| ID | What is not verified |
|---|---|
| STR-04 | runtime `LIVE_LEARNING_MODE` |
| STR-31 | whether the S3 shadow sidecar ever ran |
| CAL-03 | every effective runtime parameter value and every database value |
| CAL-10 | runtime `APP_VERSION` / strategy_version |
| EXE-08 | `PAPER_ENTRY_FILL_MODEL` |
| LRN-02 | migration 006 timing |
| LRN-14 | whether the colab notebook ran |
| LRN-20 | contents of `learned_gates`, `indicator_weights`, `optimizer_settings`, and the runtime `LEARNING_GATES_ENABLED` |

**Values marked NOT VERIFIED inside other findings:**
- STR-06: timeframes.
- STR-15, IND-04, IND-05: legacy thresholds in the DB.
- STR-34: `SIGNAL_INTEGRITY_MODE`.
- IND-06: the live min_score.
- EXE-03: `RISK_CANARY_MAX_OPEN_TRADES`.
- Every "effective" cell in section 4.

**Related findings held in other documents:**
- RT-16 and RT-17: image content parity.
- RT-31: `PAPER_TRADING`.
- RT-46: pause and risk state.
- RT-47: flags from `.env`.
- UNI-06: blacklist contents.

**Open questions for the owner that bear on this area:**

- [OQ-01] Authorize narrow database reads? Proposed scope: `optimizer_settings` (key, value, updated_at); `indicator_weights` (indicator, condition, weight, last_updated); the current pause state only. Nothing from trade or learning tables, whose post-freeze counts and times are protected (OD-7).
- [OQ-02] Authorize reading non-secret `.env` flags through a redacted allow-list: `LIVE_LEARNING_MODE`, `SIGNAL_INTEGRITY_MODE`, `LEARNING_GATES_ENABLED`, `TIMEFRAMES`, `RISK_CANARY_MAX_OPEN_TRADES`, `PAPER_TRADING`, `PAPER_ENTRY_FILL_MODEL`?
- [OQ-08] Paper accounting: keep the flat 0.30%, or adopt the 0.40% baseline / 0.60% stress?
- [OQ-09] Frozen weights: should their effect on candidate ordering and truncation remain?

This document records findings and open questions only. It makes no recommendation to change code, configuration, runtime state or strategy, and it is not a profitability certification.
