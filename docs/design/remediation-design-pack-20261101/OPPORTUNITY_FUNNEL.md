# Opportunity Funnel: Current State and Target Design (WP1-A)

> **Reconciliation 2026-11-01 (WP2).** Documentation only, on branch `feature/wp2-foundation-20261101` from `5cd1a61`. This file now uses the canonical interfaces of [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md) section 8 (WP-IR-01 to WP-IR-09). No definition is new, no option is chosen and no decision is recorded. What changed:
> - **Stage naming (F0–F8) and records.** `stage` is F0–F7, the stage at which a record is counted. F8 is the per-cycle `DecisionRecord` of `decision_type` `opportunity_rank` (WP-IR-01, WP-IR-08): see the section 7 diagram, F8 and section 8.1.
> - **`RejectionRecord` fields (section 8.1).** `sub_stage` is a closed enumeration, no longer "null otherwise". Times are integer UTC epoch milliseconds. `cycle_id` is the `decision_id` of the cycle record. `strategy_version` is derived from the five identity fields. A strategy's own code goes in `detail.strategy_code` (WP-IR-01, WP-IR-08, WP-IR-09).
> - **Reason codes (section 8.2).** Codes are written `F<n>.<reason>`, and the prefix always equals `stage`. The taxonomy v1 additions are listed. The alignment table now maps each strategy-contract name onto one canonical code and moves the strategy stage names into `sub_stage`.
> - **`regime_veto` (F3, F4 and section 8.2).** `F3.regime_veto:<series>` is reserved for a declared context-series veto. A strategy's own regime routing is `F4.regime_not_accepted`. Before, the taxonomy listed `regime_veto` under F3 while the alignment table filed it under F4.
> - **`risk_plan` (F5, F6).** It belongs to the `Candidate`. `Opportunity.risk_plan` is a read-only alias with the same hash (WP-IR-02).
> - **Capacity (F6, F7, OF-OD-15, section 12).** There is one capacity authority, the F7 check. `F6.rank_below_cap` stays separate from `F7.capacity_full`, and F6 never reads portfolio state. Today's cut is recorded in shadow only, as `F6.legacy_alphabetical_cut` (WP-IR-03, WP-IR-04).
> - **F7 codes, cost models and strategy identity.** The F7 codes follow WP-IR-05. The F5 cost model is named by `cost_model_id` (`research_baseline_v1`, `research_stress_v1` or `legacy_tracker_v1`; WP-IR-07). The `setup_key` and `strategy_version` identifier use the five `StrategyVersion` identity fields; `lineage` is excluded (WP-IR-09).
> - **Line citations.** Line numbers of pack documents (for example `OPPORTUNITY_FUNNEL.md L402`) refer to the files as committed at `5cd1a61`. They are not renumbered.

**Consolidated Remediation & Design Pack, work package WP1-A.** This document traces how an exchange universe becomes, or fails to become, an executable opportunity. Part A records the current funnel exactly as the documented-deployed source implements it, including every point where a candidate is dropped without a durable explanation. Part B specifies a target funnel that removes those defects, using the shared interface glossary of this pack.

## Document control

| Field | Value |
|---|---|
| Work package | WP1-A (integrated design), in parallel with WP0 |
| Remediation items | R1, R3 and R6 (primary); R5 and R9 (supporting); R7 by handoff |
| Branch and base | `docs/wp0-wp1-remediation-design-20261101`, from `main` = `46578aa` |
| Code read | analyzer and signal_engine at `ea8ae4f`; telegram and trade_tracker at `bb7825f`; scanner blobs listed in `deploy/baseline-2026-09-27/deployed_files.json` (`scanner/scanner_logic.py` blob `fa03cc2a`, `scanner/main.py` blob `3dc9cb1`, `shared/config.py` blob `c5c03b5c`); `main` = `46578aa` for comparison |
| Status | **Documentation/design only.** No code, configuration, database, container or Paper state was read beyond tracked files, and nothing was changed. No test, script, backtest, simulation or replay was run. |
| Not a profitability statement | Nothing here supports a claim of net edge. Correcting a funnel defect changes which candidates are considered; it does not establish that any of them is profitable. |

### Anti-drift statement (charter §7)

1. **Goal alignment.** The funnel serves active daily opportunity discovery, net-of-cost profitability and safe realized-profit compounding (`CHARTER:L7-10`). **Daily discovery is not daily execution.** The target funnel has no minimum trade frequency, no daily quota and no forced trade. A cycle that ends with zero opportunities is a valid, recorded outcome.
2. **Branch, SHA and runtime confidence.** Base `46578aa`. The funnel files of `46578aa` and the documented-deployed commits are compared in OF-01. Runtime identity: configuration values are RUNTIME_VERIFIED only where the audit addendum observed them; image content is DOCUMENTED_ONLY (`MCAS:L92-94`).
3. **Scope.** WP1-A; R1, R3, R6 in full; R5 and R9 only where they touch the funnel. **Excluded:** trade geometry and exits (R2, R4; see [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md)), capital, sizing and portfolio limits (R7; see [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md)), strategy hypotheses (R8).
4. **Evidence classes.** As in the pack brief: SOURCE_VERIFIED, RUNTIME_VERIFIED (only by citing the audit or its addendum), DOCUMENTED_ONLY, HISTORICAL_REPORTED, INFERRED, NOT_VERIFIED, CONTRADICTORY.
5. **Permission class of this document.** Read-only documentation. Each proposed change carries exactly one change class in Part B; none implies another.
6. **Deliverables and gates.** This specification, its target change register (section 9) and its owner decisions (section 10). Implementation follows [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md) and the gates of [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md).
7. **DEVIATION ALERT check.** See section 12. No conflict with the charter was found that stops this work.

### Source aliases

Every factual claim below cites `path:Lx-Ly @ commit` and an evidence class. To keep citations readable, these aliases stand for full paths:

| Alias | Full path and commit |
|---|---|
| `MCAS` | `docs/audits/2026-10-31-trading-system-review/MARKET_CONTEXT_AND_ASSET_SELECTION.md @ 5d977f2` (not on this branch) |
| `RCVA` | `docs/audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md @ 5d977f2` (not on this branch) |
| `DIA` | `docs/research/evidence-resolution-20261031/DEFECT_IMPACT_ASSESSMENT.md @ 0729a5f` (not on this branch) |
| `CHARTER` | `docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md @ 46578aa`, on this branch as [the charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) |
| `DFP` | `docs/governance/DEVELOPMENT_FIRST_POLICY.md @ 46578aa`, on this branch as [the development-first policy](../../governance/DEVELOPMENT_FIRST_POLICY.md) |

Audit finding IDs (UNI-, MKT-, STR-, EXE-, RSK-, HIS-, ARC-, IND-, CON-, OQ-) and runtime IDs (VER-) are quoted with the class the audit gives them. ERG-01 findings carry the prefix G3-. New findings of this document are numbered OF-01 onwards (current state), OF-T01 onwards (target changes) and OF-OD-01 onwards (owner decisions).

### Related pack documents

| Document | Relation to this one |
|---|---|
| [BASELINE_AND_EVIDENCE.md](BASELINE_AND_EVIDENCE.md) | Baseline SHA comparison and evidence inventory that this document relies on |
| [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md) | Owns R1–R9 and their sub-item numbering; OF-T items map onto it |
| [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md) | Owns each strategy's setup, score definition, geometry, exits, costs and `StrategyVersion` |
| [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md) | Owns `RiskBudget`, `SizingDecision`, `LedgerEntry`, capacity and admission limits (stage F7 hands off to it) |
| [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md) | Sequences the OF-T changes into WP2 work. Its section 8 (WP-IR-01 to WP-IR-09) fixes the canonical interface names that this document follows |
| [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md) | Collects the owner decisions listed in section 10 |

## Contents

- [Part A. Current funnel](#part-a-current-funnel)
  - [1. Code identity](#1-code-identity)
  - [2. Stage-by-stage trace](#2-stage-by-stage-trace)
  - [3. Silent-drop and weak-record register](#3-silent-drop-and-weak-record-register)
  - [4. Failure semantics today](#4-failure-semantics-today)
  - [5. Existing building blocks that are not wired in](#5-existing-building-blocks-that-are-not-wired-in)
- [Part B. Target funnel](#part-b-target-funnel)
  - [6. Binding design principles](#6-binding-design-principles)
  - [7. Target stages F0 to F8](#7-target-stages-f0-to-f8)
  - [8. Observability: RejectionRecord, reason codes, counters, sampling](#8-observability-rejectionrecord-reason-codes-counters-sampling)
  - [9. Target change register](#9-target-change-register)
  - [10. Owner decisions](#10-owner-decisions)
  - [11. Not verified](#11-not-verified)
  - [12. Consistency notes and deviation check](#12-consistency-notes-and-deviation-check)

---

# Part A. Current funnel

## 1. Code identity

**OF-01 (SOURCE_VERIFIED).** The funnel logic is unchanged between the documented-deployed commits and `main` `46578aa`, so every current-state defect below is still present on `main`.
- Identical blobs at the deployed commit and at `46578aa`: `scanner/scanner_logic.py` (`fa03cc2a`, also the blob listed for the scanner image in `deploy/baseline-2026-09-27/deployed_files.json:L283-291 @ 46578aa`), `scanner/main.py` (`3dc9cb1`), `signal_engine/main.py` (`2e0e89f`), `shared/candidate_selection.py` (`bb7d713`), `trade_tracker/main.py` (`4f98455`) and `telegram/main.py` (`7004e3c`). Read with `git rev-parse <commit>:<path>`.
- Files that differ: `analyzer/main.py` and `analyzer/technical_analyzer.py` (the T1-cap policy switch), `shared/config.py` (new keys) and `signal_engine/signal_logic.py` (one evidence-recorder argument). None of these differences touches intake, eligibility, gating, ranking or truncation (`git diff ea8ae4f 46578aa`, read-only). This agrees with the audit's statement that `main` differs on the universe and macro paths only by the T1-cap flag code (`MCAS:L83`; RT-37, SOURCE_VERIFIED).
- That the running images contain this source is DOCUMENTED_ONLY (RT-16) and image filesystems were not read (RT-17, NOT_VERIFIED) (`MCAS:L84-94`).

**OF-02 (RUNTIME_VERIFIED, by citation).** The runtime configuration that selects the funnel path, as observed on 2026-10-31:

| Setting | Effective value | Effect on the funnel | Citation |
|---|---|---|---|
| `LIVE_LEARNING_MODE` | `true` | `find_best_signal_live` is the selector; regime-routed setups and the macro gate are active | `RCVA:L93` (VER-01) |
| `SIGNAL_INTEGRITY_MODE` | unset, so `off` | no candle identity, no freshness rule, no insert-once `setup_key` | `RCVA:L94` (VER-02) |
| `LEARNING_GATES_ENABLED` | `false` | learned-gate filter inactive | `RCVA:L95` (VER-03) |
| `TIMEFRAMES` | `15m,4h,1d` | three rows per symbol at most; 1h not analysed | `RCVA:L98` (VER-06) |
| `SCAN_INTERVAL_SECONDS` | `300` | scanner cadence | `RCVA:L99` (VER-07) |
| `MIN_VOLUME_USDT` | `10000000` | 24 h quote-volume floor | `RCVA:L100` (VER-08) |
| `MAX_SPREAD_PCT` | unset, so `0.15` | live spread gate | `RCVA:L101` (VER-09) |
| `RISK_CANARY_MAX_OPEN_TRADES` / `MAX_OPEN_TRADES` | `2` / unset, so `10` | delivery and admission capacity min(10, 2) = 2 | `RCVA:L104` (VER-12) |
| `TRADE_AMOUNT_USDT` / `RISK_CAPITAL_USDT` | `50` / `500` | fixed notional; capacity is 2 × $50 of $500 | `RCVA:L109` (VER-17) |
| `USDTD_SPIKE_PP` / `MACRO_CACHE_HOURS` / `MACRO_MAX_STALE_HOURS` | unset, so `0.5` / `1` / `2` | macro veto parameters | `RCVA:L110` (VER-18) |
| `EVIDENCE_V2_ENABLED` | `true` (Compose literal) except in the scanner, where it is unset and therefore `false` | the only per-candidate decision trail is the research evidence stream, and the scanner writes none | `RCVA:L112` (VER-20) |
| `symbol_blacklist` | 0 rows | no symbol is excluded by the blacklist | `RCVA:L165-167` (VER-24) |
| pause decision row | not paused (`manual_resume`) | the scanner's fail-closed pause gate admits scanning | `RCVA:L169-177` (VER-25) |

## 2. Stage-by-stage trace

The current funnel runs as four loosely coupled loops that communicate through database tables: the scanner (every 300 s), the analyzer (about every 10 s while work exists), the signal engine (about every 60 s) and the delivery and admission services. Each row below is one stage, in data-flow order. "Record" says whether a candidate dropped at that stage leaves a durable, per-candidate reason.

### 2.1 Scanner (universe and initial filters)

| # | Stage | Rule, threshold or cap | Source | Record of a drop |
|---|---|---|---|---|
| S0 | Pause gate | No scan unless the latest pause decision is a valid `manual_resume`; fails closed | `scanner/scanner_logic.py:L25-29 @ ea8ae4f` (blob `fa03cc2a`); ARC-12 SOURCE_VERIFIED (`MCAS:L146-148`) | Log line only |
| S1 | BTC trend refresh | Last 10 closed 4h BTCUSDT bars (11 fetched); change over 9 intervals (36 h); > 3 strong_bullish, > 1 bullish, < −3 strong_bearish, < −1 bearish; **fewer than 10 bars or any exception gives "neutral"** | `scanner/scanner_logic.py:L116-148 @ ea8ae4f`; MKT-01, MKT-02 SOURCE_VERIFIED (`MCAS:L327`, `MCAS:L366-368`) | Log line only |
| S2 | Exchange listing | Binance Spot `exchangeInfo`: `quoteAsset == 'USDT'`, `status == 'TRADING'`, ASCII name, minus USDCUSDT, BUSDUSDT, TUSDUSDT. No rule for other pegged assets or leveraged ETF-style coins; the venue's price, quantity and notional filters are not read | `scanner/scanner_logic.py:L72-81 @ ea8ae4f`; UNI-01, UNI-02, UNI-04 SOURCE_VERIFIED (`MCAS:L161-163`) | None |
| S3 | Blacklist | `SELECT symbol FROM symbol_blacklist` on every scan; a read failure aborts the scan. Currently 0 rows (VER-24) | `scanner/scanner_logic.py:L38-44 @ ea8ae4f`; UNI-05 SOURCE_VERIFIED (`MCAS:L164`) | Count in a log line |
| S4 | 24 h tickers | One bulk 24 h ticker read; a symbol absent from the ticker map is skipped | `scanner/scanner_logic.py:L46-53, L83-86 @ ea8ae4f` | None |
| S5 | Initial filter | `quoteVolume ≥ MIN_VOLUME_USDT` (10M, VER-08); `abs(priceChangePercent) ≥ 1.0` (hard-coded); `lastPrice > 0`; if the S1 label is `strong_bearish`, the move must be ≥ 5; a parse error rejects | `scanner/scanner_logic.py:L88-114 @ ea8ae4f`; `shared/config.py:L130-131 @ c5c03b5c` (scanner blob); UNI-09 SOURCE_VERIFIED (`MCAS:L166-168`) | None |
| S6 | Persist candidates | One `scan_candidates` row per passing symbol per scan, carrying the S1 label; rows older than 1 h are deleted whether or not they were analysed | `scanner/scanner_logic.py:L150-160 @ ea8ae4f`; `shared/maintenance.py:L12-13 @ ea8ae4f`; ARC-04 SOURCE_VERIFIED (`MCAS:L150-152`) | Deletion count in the heartbeat only |

### 2.2 Analyzer (history, regime, setup)

| # | Stage | Rule, threshold or cap | Source | Record of a drop |
|---|---|---|---|---|
| S7 | Intake | 50 unanalysed rows per loop, **newest scan first**; 30 s sleep when idle, 10 s after work; 60 s timeout per symbol | `analyzer/main.py:L47-82 @ ea8ae4f`; UNI-14 SOURCE_VERIFIED, UNI-15 INFERRED (`MCAS:L175`) | Timeout: log line only |
| S8 | Candles and history | 201 klines fetched; only bars with exchange `close_time` before the host clock are kept (last 200); gaps, duplicates, impossible bars and NaN reject; fewer than `indicator_warmup_bars()` = 200 bars returns `None` | `analyzer/technical_analyzer.py:L24-33, L47-48, L124-137 @ ea8ae4f`; `shared/ohlcv.py:L26-33 @ ea8ae4f`; UNI-12 SOURCE_VERIFIED, UNI-13 INFERRED (`MCAS:L173`) | **None**: the timeframe is skipped silently (`analyzer/main.py:L150-152 @ ea8ae4f`) |
| S9 | Regime and setup | `classify_regime` on the symbol's own bars; momentum only when bullish, reversion only when sideways; bearish and volatile produce no setup. A row is still written when there is no setup | `analyzer/technical_analyzer.py:L61-73 @ ea8ae4f`; STR-09, MKT-09 SOURCE_VERIFIED (`MCAS:L333`, `MCAS:L452-459`) | `trade_type = null` in the row |
| S10 | Levels and stop validity | Stop cap per timeframe 15m 2%, 1h 4%, 4h 5%, 1d 3% (other 4%); a momentum or reversion setup gets `stop_valid` from `plan_signal_stop` | `analyzer/technical_analyzer.py:L404-447 @ ea8ae4f`; UNI-11 SOURCE_VERIFIED (`MCAS:L172`) | `stop_valid`, `stop_reject_reason` in the row |
| S11 | Order book | One 20-level snapshot per symbol, fetched with the first successful timeframe and reused for the others | `analyzer/main.py:L154-159 @ ea8ae4f`; EXE-05 SOURCE_VERIFIED (`MCAS:L630-633`) | — |
| S12 | Upsert | `analysis_results` keeps **one row per (symbol, timeframe)**; each re-analysis overwrites it and resets `signal_generated = false` and `processing_status = 'pending'`. Rows not used within 2 h are marked `expired` | `analyzer/main.py:L165-174 @ ea8ae4f`; `shared/maintenance.py:L6-11 @ ea8ae4f` | Overwritten on the next scan |

### 2.3 Signal engine (selection, gates, ranking)

| # | Stage | Rule, threshold or cap | Source | Record of a drop |
|---|---|---|---|---|
| S13 | Selection query | Rows with `signal_generated = false`, `analyzed_at` within **30 minutes**, symbol without an open trade; `ORDER BY symbol, total_score DESC` **`LIMIT 200`** | `signal_engine/main.py:L146-155 @ ea8ae4f` (`SELECTION_LIMIT` at L26-30); UNI-16 SOURCE_VERIFIED, UNI-17 INFERRED (`MCAS:L176`) | **None in the decision path** for rows beyond the limit (OF-03) |
| S14 | Macro gate (cycle-wide) | Blocks every candidate in the cycle if macro BTC is `strong_bearish` (4h, ≥ 18 closed bars, change ≤ −5 over 17 intervals, 68 h), USDT.D is `rising_fast` (≥ 0.5 pp above its 3-day mean), or the last valid macro refresh is older than 2 h or absent | `shared/macro_context.py:L24-25, L96-110 @ ea8ae4f`; `signal_engine/signal_logic.py:L722-727 @ ea8ae4f`; STR-11, MKT-03, MKT-13 SOURCE_VERIFIED (`MCAS:L494-515`, `MCAS:L598-603`) | `decision_reason = 'macro_block'` per symbol |
| S15 | No setup | Row without `trade_type` | `signal_engine/signal_logic.py:L755-759 @ ea8ae4f` | `no_trade_setup` (set only if no other reason exists for the symbol) |
| S16 | Order book and spread | Book must be valid with a spread; spread must be finite and non-negative; spread ≤ `MAX_SPREAD_PCT` 0.15 (VER-09) | `signal_engine/signal_logic.py:L760-780 @ ea8ae4f`; IND-03 SOURCE_VERIFIED (`MCAS:L170`) | `order_book_unavailable`, `spread_invalid`, `spread_exceeds_limit` |
| S17 | Stop validity | Only an explicit `stop_valid = False` rejects; a missing value passes | `signal_engine/signal_logic.py:L781-791 @ ea8ae4f` | `stop_rejected:<reason>` |
| S18 | Open trade and cooldown | Symbol with an open trade, or with any `signals` row in the last 2 h (`COOLDOWN_SQL`). In off mode a cooldown read error returns an empty set (fails open) | `signal_engine/signal_logic.py:L25-26, L417-431, L745-746, L792-801 @ ea8ae4f`; UNI-18, EXE-01 SOURCE_VERIFIED; HIS-27 SOURCE_VERIFIED | `open_trade_exists`, `symbol_cooldown` |
| S19 | Integrity (enforce only) | Candle identity, ≤ 1-bar freshness, emitted-`setup_key` check. **Off at runtime** (VER-02) | `signal_engine/signal_logic.py:L730-737, L803-818 @ ea8ae4f`; `shared/signal_identity.py:L186-200 @ ea8ae4f`; STR-33 SOURCE_VERIFIED | — (inactive) |
| S20 | Learned gate | Throttled (trade type, timeframe) cells; **off at runtime** (VER-03) | `signal_engine/signal_logic.py:L819-831 @ ea8ae4f` | — (inactive) |
| S21 | Ranking | `min` over (spread, −24 h quote volume, symbol, timeframe); the volume is the latest scanner row's value, and a missing value ranks last. Exactly one winner per cycle; setup strength plays no part | `signal_engine/signal_logic.py:L287-293, L832, L848, L891-909 @ ea8ae4f`; STR-13 SOURCE_VERIFIED (`MCAS:L177`) | Losers: `not_selected_capacity` (OF-07) |
| S22 | Emit | `signals` row and `signal.ready` outbox event in one transaction; then **every** `analysis_results` row of that symbol is set `signal_generated = true`; the loop sleeps 60 s | `signal_engine/main.py:L218-260 @ ea8ae4f`; `signal_engine/signal_logic.py:L911-990 @ ea8ae4f` | — |

### 2.4 Delivery and admission

| # | Stage | Rule, threshold or cap | Source | Record of a drop |
|---|---|---|---|---|
| S23 | Delivery gate | Refuses while paused, or when open trades ≥ min(`MAX_OPEN_TRADES`, `RISK_CANARY_MAX_OPEN_TRADES`) = 2 (VER-12). **A refused candidate is acknowledged and lost**, not queued | `telegram/main.py:L264-275, L364-382 @ bb7825f`; EXE-02 SOURCE_VERIFIED (`MCAS:L280`) | Log line; `delivery.refused` research event |
| S24 | Admission query | Delivered signals of the last 2 h with no trade, `DISTINCT ON (symbol)` keeping the latest per symbol; no open trade on the symbol; no trade on the same (symbol, timeframe) within one candle interval; not blacklisted; processed in **symbol order** | `trade_tracker/main.py:L718-751 @ bb7825f`; EXE-04 SOURCE_VERIFIED (`MCAS:L282`) | Superseded signals: none |
| S25 | Entry, fill and risk | No price: skip and retry; entry reject: terminal; limit wait: retry until the 2 h window ends; risk reject: retried each loop within 2 h; portfolio capacity min(10, 2) inside `assess_new_trade_risk` | `trade_tracker/main.py:L752-834, L979 @ bb7825f`; EXE-17, RSK-01, RSK-02 SOURCE_VERIFIED | Research admission events; risk decision record |
| S26 | Venue order floor | `get_min_notional` reads the venue's notional filter once per process, falls back to a configured value on any error, and only **records** the value on the trade; it is not an admission gate | `trade_tracker/main.py:L812, L1453-1477 @ bb7825f` | — |

Portfolio limits beyond capacity (exposure caps, loss checks in observe mode) are described in [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md) and are not repeated here (RSK-01 to RSK-06, `MCAS:L274-290`).

## 3. Silent-drop and weak-record register

A drop is **silent** when a candidate leaves the funnel without a durable, per-candidate reason that a reviewer could later read. A record is **weak** when it exists but is overwritten, keyed too coarsely, expires quickly or is mislabelled. How often each drop occurs is not known: every count would come from post-freeze runtime tables or evidence streams, which are protected (`DIA:L196`, `DIA:L201`; `DFP:L57`). The impact of every item below is therefore UNKNOWN in frequency and economics unless stated.

| ID | Drop point | Mechanism | Durable record? | Class | Item |
|---|---|---|---|---|---|
| OF-03 | **Alphabetical `LIMIT 200`** (S13) | The query sorts by symbol before the limit. With 3 timeframes, once more than 200 rows qualify, the first 66 symbols in sort order keep every row, the 67th keeps 2, and every later symbol is cut, before any setup, spread or cooldown filter is applied. Truncated rows are not in `results`, so they are not even marked `evaluated` and stay `pending` | No, in the decision path. The research stream records a truncation event only when its state changes, listing at most 500 cut rows (`signal_engine/main.py:L39-65 @ ea8ae4f`) | SOURCE_VERIFIED mechanism (`signal_engine/main.py:L146-155, L179-186 @ ea8ae4f`); INFERRED arithmetic (`DIA:L181-190`); frequency NOT_VERIFIED (UNI-17) | R1 |
| OF-04 | **Analyzer 50-row intake** (S7) | Newest-first intake of 50 rows per loop. If the backlog ever exceeds what the analyzer clears within 1 h, the oldest unanalysed rows are deleted by retention (S6) with no reason. UNI-15 (INFERRED) judges that, at the coded loop rate, the intake is not a hard cap on coverage | No | SOURCE_VERIFIED rules (`analyzer/main.py:L47-54 @ ea8ae4f`; `shared/maintenance.py:L12-13 @ ea8ae4f`); INFERRED reachability | R6 |
| OF-05 | **Skipped timeframe** (S8) | Insufficient history, a data-quality rejection, a fetch error or a per-symbol timeout make the analyzer skip the timeframe without writing a row | Log line only | SOURCE_VERIFIED (`analyzer/main.py:L73-76, L150-152, L180-181 @ ea8ae4f`; `analyzer/technical_analyzer.py:L47-48, L120-122 @ ea8ae4f`) | R6 |
| OF-06 | **30-minute window** (S13) | Rows older than 30 minutes are never evaluated. Conversely, a symbol that has left the scanner list keeps competing for up to 30 minutes, which can push the qualifying count above the scanner list size | Rows are marked `expired` only after 2 h | SOURCE_VERIFIED (`signal_engine/main.py:L149 @ ea8ae4f`); INFERRED interaction (`DIA:L184`) | R1, R6 |
| OF-07 | **One signal per cycle** (S21) | Exactly one winner per cycle of about 60 s. Eligible losers are labelled `not_selected_capacity`, although no capacity check was made: they lost a rank, and they compete again next cycle while their row is fresh | Mislabelled | SOURCE_VERIFIED (`signal_engine/signal_logic.py:L848-854 @ ea8ae4f`; `signal_engine/main.py:L260 @ ea8ae4f`) | R6 |
| OF-08 | **Per-symbol decision reasons** (S14 to S21) | `last_decisions` is keyed by symbol only. A symbol's 15m, 4h and 1d rows overwrite each other's reasons, and the engine writes one reason to all of that symbol's rows. Reasons are overwritten every cycle and the row is marked `expired` after 2 h | Weak | SOURCE_VERIFIED (`signal_engine/signal_logic.py:L757-853 @ ea8ae4f`; `signal_engine/main.py:L178-186 @ ea8ae4f`; `shared/maintenance.py:L6-11 @ ea8ae4f`) | R6 |
| OF-09 | **2 h symbol cooldown** (S18) | Any `signals` row in the last 2 h blocks the symbol, whether or not the signal was delivered or admitted. A signal refused at S23 therefore also blocks its symbol for 2 h. After the emit, all of the symbol's rows are set `signal_generated = true` until the next re-analysis | Reason `symbol_cooldown` (weak, OF-08) | SOURCE_VERIFIED (`signal_engine/signal_logic.py:L25-26 @ ea8ae4f`; `signal_engine/main.py:L238-245 @ ea8ae4f`); INFERRED interaction | R6 |
| OF-10 | **Capacity refusal** (S23) | With 2 open trades, the delivery gate acknowledges the `signal.ready` event and drops it. Nothing is queued | Log line and a research event | SOURCE_VERIFIED (`telegram/main.py:L268-275, L364-382 @ bb7825f`); capacity RUNTIME_VERIFIED (VER-12) | R6, R7 |
| OF-11 | **Admission supersession and order** (S24) | `DISTINCT ON (symbol)` keeps only the latest pending signal per symbol; older ones leave no record. Signals are processed in symbol order, so when two are pending and one slot is free, the alphabetically earlier symbol is admitted | No (supersession) | SOURCE_VERIFIED (`trade_tracker/main.py:L720, L748, L751-759 @ bb7825f`); INFERRED effect | R1, R6 |
| OF-12 | **Stale-macro block** (S14) | A refresh happens at most hourly and only in cycles that have rows; it is skipped while the engine is idle. If the last valid refresh is older than 2 h, or none exists, the whole cycle is blocked. Staleness is measured from the time of the refresh, not from the close of the 4h bars it used, so a decision can rest on bars about 6 h old | `macro_block` per symbol (weak, OF-08) | SOURCE_VERIFIED (`shared/macro_context.py:L90-110 @ ea8ae4f`; `signal_engine/main.py:L160-168 @ ea8ae4f`; MKT-13); INFERRED age (MKT-14, `MCAS:L605`) | R6, R9 |
| OF-13 | **Scanner BTC fail-open** (S1, S5) | An exception or fewer than 10 bars sets the label to `neutral`, silently disabling the 5% stress rule | Log line only | SOURCE_VERIFIED (`scanner/scanner_logic.py:L125-127, L146-148 @ ea8ae4f`; MKT-02) | R6 |
| OF-14 | **Macro missing-key fail-open** (S14) | A missing `usdt` or `btc` field reads as 0.0 without an exception; USDT.D then reads as falling and the 0 is stored, biasing about three days of baseline | No | SOURCE_VERIFIED (`shared/macro_context.py:L28-33 @ ea8ae4f`); INFERRED consequence (MKT-15, `MCAS:L607-612`) | R6 |
| OF-15 | **Cooldown read fail-open** (S18) | In off mode a database error in the cooldown read yields an empty set, so cooled-down symbols become eligible | Log line only | SOURCE_VERIFIED (`signal_engine/signal_logic.py:L429-431 @ ea8ae4f`; HIS-27) | R3, R6 |
| OF-16 | **Same-bar re-fire** (S12, S18) | The upsert resets `signal_generated` on every scan. A closed 4h or 1d bar stays the latest bar for 4 h or 24 h, so the same setup can be emitted again after each 2 h cooldown. The tracker's per-candle guard (S24) only prevents a second trade, not a second signal | Duplicate signals look like new ones | SOURCE_VERIFIED (`analyzer/main.py:L165-174 @ ea8ae4f`; `signal_engine/signal_logic.py:L25-26 @ ea8ae4f`; `DIA:L225-237`; HIS-25) | R3 |
| OF-17 | **No decision-bar age bound** (S8 to S21) | In off mode only the 30-minute row age and the 2 h signal window are checked. The closed bar itself is never aged, so a 1d decision can rest on a bar about 24 h old; candle closure depends on the host clock | — | SOURCE_VERIFIED (EXE-09, EXE-05, `MCAS:L626-633`); INFERRED clock risk (EXE-06, `MCAS:L635`) | R6 |
| OF-18 | **Venue order filters unused** (S2, S26) | The scanner reads `exchangeInfo` but none of its order filters; the tracker reads the notional floor only to record it, caches it for the process lifetime and falls back to a configured value on error | — | SOURCE_VERIFIED (`scanner/scanner_logic.py:L72-81 @ ea8ae4f`; `trade_tracker/main.py:L812, L1453-1477 @ bb7825f`) | R6, R7 |
| OF-19 | **Two BTC trend definitions** (S1, S14) | The scanner uses 36 h with ±1/±3; the macro gate uses 68 h with ±1/±5. They share labels; documents describe the trend as "40 h" or "about 3 days" | — | CONTRADICTORY (CON-27, `MCAS:L396`) | R6 |
| OF-20 | **Inactive score decides the cut** (S13) | `total_score` (frozen `indicator_weights`, 44 values) orders a symbol's rows and therefore decides which rows of the boundary symbol survive the cut, though no live gate reads it | — | SOURCE_VERIFIED effect; values RUNTIME_VERIFIED (`RCVA:L191`, VER-22); owner question OQ-09 (`MCAS:L719`) | R1 |
| OF-21 | **Lexical timeframe tie-break** (S21) | One order-book snapshot serves all of a symbol's timeframes, so spread and volume tie; the string order `'15m' < '1d' < '4h'` then picks the timeframe | — | SOURCE_VERIFIED (`signal_engine/signal_logic.py:L287-293 @ ea8ae4f`); INFERRED (`DIA:L188`) | R1 |

**OF-22 (INFERRED).** The universe is multi-asset by design: no rule restricts trading to BTC. The ranking key (tightest relative spread, then the highest 24 h quote volume) favours the deepest majors whenever they have a valid setup (UNI-19, `MCAS:L294-298`). The 1% minimum 24 h move is itself listed among the data-snooping and survivorship concerns (HIS-37 DOCUMENTED_ONLY, `MCAS:L316`).

## 4. Failure semantics today

| Input or check | On error or missing data | Class |
|---|---|---|
| Pause state (S0, S23) | Fails closed: no scan, no delivery | SOURCE_VERIFIED (ARC-12, EXE-02) |
| Exchange listing, tickers, blacklist (S2 to S4) | Fails closed: the scan aborts | SOURCE_VERIFIED (MKT-16, `MCAS:L614-619`) |
| Scanner BTC trend (S1) | **Fails open** to `neutral` | SOURCE_VERIFIED (OF-13) |
| Candles (S8) | Fails closed per timeframe, silently | SOURCE_VERIFIED (OF-05) |
| Macro staleness (S14) | Fails closed for the whole cycle | SOURCE_VERIFIED (OF-12) |
| Macro missing field, empty history (S14) | **Fails open** | INFERRED (OF-14) |
| Order book and spread (S16) | Fails closed per candidate | SOURCE_VERIFIED |
| Stop validity (S17) | Missing value **passes**; only an explicit False rejects | SOURCE_VERIFIED (`signal_engine/signal_logic.py:L781-784 @ ea8ae4f`; gate map `MCAS:L532`) |
| Cooldown read, off mode (S18) | **Fails open** | SOURCE_VERIFIED (OF-15) |
| 24 h volume for ranking (S21) | Missing value ranks last | SOURCE_VERIFIED (`signal_engine/signal_logic.py:L292, L909 @ ea8ae4f`) |
| Venue notional floor (S26) | Falls back to a configured value | SOURCE_VERIFIED (OF-18) |

The pattern is inconsistent: the most consequential safety inputs fail closed, but three context or state reads fail open with no durable record. In each case the target funnel (section 7) makes the semantics explicit and records the outcome.

## 5. Existing building blocks that are not wired in

**OF-23 (SOURCE_VERIFIED).** `shared/candidate_selection.py` at `ea8ae4f` (identical at `46578aa`, OF-01) already separates eligibility from ranking and has no production caller (STR-30):
- `bounded_universe` drops above a cap by hash order, never alphabetically, and returns the dropped (symbol, timeframe) pairs (`shared/candidate_selection.py:L201-223 @ ea8ae4f`);
- `execution_quality_v2` keeps the current objective but replaces the lexical tie-break with a hash of a versioned identity (`shared/candidate_selection.py:L133-143 @ ea8ae4f`);
- a staged pipeline returns one `StageRecord` per input candidate with its stage, reasons and rank (`shared/candidate_selection.py:L226-276 @ ea8ae4f`).

One property conflicts with the target principle of section 6: `bounded_universe` drops **before** ranking. It is acceptable only as a resource guard that never binds in normal operation (section 7, F6).

**OF-24 (SOURCE_VERIFIED).** `shared/signal_identity.py` at `ea8ae4f` defines a setup key over identity version, symbol, timeframe, candle open time, trade type, direction, strategy version and setup policy, and a freshness rule that rejects a decision made before the candle closed or one bar or more after it (`shared/signal_identity.py:L62-88, L186-200 @ ea8ae4f`). It acts only in enforce mode, which is off (VER-02). Its `strategy_version` is `APP_VERSION` (`signal_engine/signal_logic.py:L385, L805 @ ea8ae4f`), a label (`sb-2026.08`, VER-13, `RCVA:L105`) rather than a content hash. ERG-01 shows that the frozen contract hash does not register a change of the selection cut or of the integrity mode (`DIA:L272-277`, G3-08), so neither identifier alone is a sufficient version boundary.

**OF-25 (SOURCE_VERIFIED; contents of the records NOT_VERIFIED).** The research evidence stream emits one event per candidate decision **state change** and counts suppressed repeats and queue-full drops (`shared/evidence_v2.py:L268-325 @ ea8ae4f`; `signal_engine/signal_logic.py:L120-179 @ ea8ae4f`). It is useful for diagnosis but is not a decision record: it is off in the scanner (VER-20), it never sees rows cut by `LIMIT 200` except through the capped truncation event, and its records written after the freeze are protected forward material that this phase may not read (`DIA:L196`).

---

# Part B. Target funnel

## 6. Binding design principles

These principles bind every stage in section 7. Each derives from the charter or the development-first policy; none chooses a threshold.

| # | Principle | Basis |
|---|---|---|
| P1 | **Discovery is not execution.** The funnel scans the whole eligible universe every cycle. It has no minimum trade frequency, no daily quota and no forced trade; zero opportunities is a normal, recorded outcome | `CHARTER:L7-10` (objective and non-goals) |
| P2 | **No silent drop.** Every candidate that leaves the funnel produces a `RejectionRecord` with a stage and a reason code. Counters are complete, and a conservation check proves it every cycle (section 8) | `CHARTER:L21` (funnel A); R6 (`CHARTER:L41`) |
| P3 | **Rank before any cap.** No candidate is truncated before a complete ranking. A cap, if any, applies to a fully ranked list, and every item it removes is recorded with its rank | R1 (`CHARTER:L36`) |
| P4 | **Point-in-time and closed-candle only.** Every input carries `as_of`; decisions use closed bars only, within a freshness bound on the decision bar; staleness is measured from data time, not from fetch time | `CHARTER:L29` (traceability); `CHARTER:L57` (no stale or incomplete-bar decisions) |
| P5 | **Idempotent setups.** One `setup_key` per symbol, strategy, timeframe and bar close; a repeat evaluation of the same bar cannot create a second signal | R3 (`CHARTER:L38`) |
| P6 | **Deterministic decisions.** `decide(state, snapshot)` returns the same ranked list for the same inputs, whatever their order; ties break on a versioned hash, never on symbol name or timeframe string | `CHARTER:L29`; OF-21 |
| P7 | **Exchange-agnostic.** Venue specifics stay inside a market-data adapter; downstream stages see only glossary entities | `CHARTER:L7-10` |
| P8 | **No BTC-only restriction.** BTC context may inform a strategy only through `RegimeContext` as that strategy's contract declares; it never narrows the universe to BTC. BTC SMA200 appears only as a benchmark or candidate hypothesis | `CHARTER:L10`; `CHARTER:L15` |
| P9 | **Explicit failure semantics.** Each input that gates a decision declares fail-closed or fail-open behaviour, and both outcomes are recorded | OF-13 to OF-15 |
| P10 | **Version boundaries.** Any change that alters which candidates are eligible, ranked, emitted or admitted is a new `StrategyVersion` boundary, and a disabled flag does not authorise activation | `DFP:L63`; `CHARTER:L51`; `DIA:L287` (G3-09) |
| P11 | **Owner-set thresholds.** Every numeric threshold is an owner decision (section 10). Until a decision is recorded, the current value and behaviour are retained and nothing new is activated | Pack brief; `DFP:L104` |
| P12 | **Protected counts stay protected.** Rejection records produced by Paper after the research freeze are forward-window material; reading their counts needs owner permission. Engineering verification uses synthetic fixtures | `CHARTER:L21`; `DFP:L57`; `DIA:L196` |

## 7. Target stages F0 to F8

Data flow, with the glossary entity each stage emits:

```text
F0 MarketSnapshot ─► F1 EligibilityResult ─► F2 liquidity/spread/volatility ─► F3 RegimeContext
      │                     │                          │                              │
      └──────────── RejectionRecord at every stage (F0–F7), counters per cycle ───────┘
F4 CandleSet → Candidate(setup_key, risk_plan) ─► F5 execution feasibility ─► F6 Opportunity(candidate, score, rank, tie_break_key)
      ─► F7 portfolio handoff (single capacity authority, RiskBudget, SizingDecision) ─► OrderIntent → Fill
F8 DecisionRecord: one per decision; per cycle, one opportunity_rank record with all inputs and hashes
```

`RejectionRecord.stage` takes the values F0 to F7 only. F8 is not a rejection stage: it is the per-cycle `DecisionRecord` (WP-IR-01, WP-IR-08). F2a and F2b below are parts of stage F2: their records carry `stage` F2 and an `F2.` code, wherever the check runs.

Each stage below states its rules, its reason codes (section 8.2 lists them all), its failure semantics, and its link to the change register (section 9).

### F0. MarketSnapshot (point-in-time feed)

- **Output.** One `MarketSnapshot` per cycle: venue, `source`, `as_of`, the universe (symbol, base and quote asset, venue status, order filters), 24 h statistics, the measured offset between host and venue clocks, and a content hash.
- **Rules.**
  - `as_of` is venue time where the venue provides it; otherwise host time, with the measured clock offset recorded. This closes the clock-skew gap of EXE-06.
  - A snapshot older than the snapshot staleness bound is not used. The cycle produces no candidates and one cycle-level `RejectionRecord` (`F0.snapshot_stale`).
  - A snapshot that is partial (for example, tickers present but the listing missing) is rejected as a whole (`F0.snapshot_incomplete`), as today's scan aborts on read failures (MKT-16).
  - The adapter alone knows venue field names. On Binance Spot, these are the `exchangeInfo` symbol status and its price, quantity and notional filters, and the 24 h ticker.
- **Failure semantics.** Fail-closed for the cycle, recorded.
- **Changes.** OF-T03 (adapter and capture), OF-T13 (hash in `DecisionRecord`).

### F1. Market eligibility and tradability

- **Output.** One `EligibilityResult` per symbol in the snapshot: `eligible` and the full list of `reason_codes[]`. Every rule is evaluated, so a symbol that fails two rules shows both.
- **Rules.** Each rule's threshold or list is an owner decision; this design fixes only the rule set and its recording.

| Rule | Reason code | Current behaviour | Owner decision |
|---|---|---|---|
| Venue status allows spot trading | `F1.status_not_trading` | `status == 'TRADING'` (UNI-01) | — |
| Quote asset in the approved set | `F1.quote_not_approved` | USDT only (UNI-01) | OF-OD-02 |
| Stablecoin or pegged base asset | `F1.stable_or_pegged` | Three named pairs only (UNI-02) | OF-OD-03 |
| Leveraged or ETF-style product | `F1.leveraged_product` | No rule (UNI-04) | OF-OD-04 |
| Order filters present and parseable (tick size, step size, notional floor) | `F1.filters_missing` | Not read at scan; recorded only at admission (OF-18) | — |
| Minimum order feasible: the smallest order the `RiskBudget` allows, rounded to step size, clears the notional floor | `F1.min_order_infeasible` | Not checked (OF-18) | Handoff to [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md) |
| Listing age and history sufficiency for at least one strategy and timeframe | `F1.listing_age_insufficient` | Analyzer warm-up of 200 bars, recorded nowhere (OF-05) | OF-OD-05 |
| Owner exclusion list | `F1.owner_excluded` | `symbol_blacklist`, empty (VER-24) | — |
| Symbol name supported by the adapter | `F1.symbol_unsupported` | ASCII filter (UNI-01) | — |

- **Failure semantics.** A missing or unparseable rule input makes the symbol ineligible (fail-closed) with the rule's reason code. The eligibility of a symbol never depends on BTC context; any BTC-conditioned rule moves to F3 (OF-T06).
- **Changes.** OF-T04.

### F2. Liquidity, spread and volatility

F2 runs in two places. **F2a** applies universe-level checks to every eligible symbol before candles are fetched. **F2b** applies order-level checks to each candidate at decision time, inside F5, from a fresh order book.

| Check | Where | Reason code | Current behaviour | Owner decision |
|---|---|---|---|---|
| 24 h quote volume floor | F2a | `F2.volume_below_floor` | ≥ 10M USDT (VER-08) | OF-OD-06 |
| Minimum 24 h movement | F2a | `F2.move_below_floor` | ≥ 1%, hard-coded, raised to 5% under scanner BTC stress (UNI-09); itself a snooping concern (HIS-37) | OF-OD-08 |
| Book freshness: book age at decision within a bound | F2b | `F2.book_stale` | One snapshot reused across timeframes; age not checked (EXE-05) | OF-OD-07 |
| Relative spread from that fresh book | F2b | `F2.spread_invalid`, `F2.spread_above_limit` | ≤ 0.15% (VER-09) | OF-OD-07 |
| Depth: buy-side notional within a stated distance of mid, as a multiple of the planned order notional | F2b | `F2.depth_insufficient` | No depth filter (UNI-11) | OF-OD-06 |
| Volatility upper bound | F5 | `F5.stop_risk_above_cap` | Stop-risk cap per timeframe (UNI-11); owned by the strategy contract | Strategy contract |

- **Failure semantics.** Fail-closed per symbol or candidate, recorded. A missing 24 h volume never ranks a candidate (today it ranks last, `signal_engine/signal_logic.py:L292 @ ea8ae4f`); it rejects it as `F2.volume_missing`.
- **Changes.** OF-T05.

### F3. Market and BTC regime context

- **Output.** One `RegimeContext` per cycle: each declared context series, its label, the `as_of` of the last closed bar it used, `staleness` = decision time − `as_of`, the refresh time, and a validity flag.
- **Single BTC trend.** Exactly one BTC trend definition exists in the target funnel, with one label set, one window, one threshold set and closed bars only. The current pair of definitions (36 h at ±1/±3 and 68 h at ±1/±5, OF-19) collapses into the one the owner selects (OF-OD-09). The scanner's stress rule, which today hides a BTC dependence inside universe selection, becomes either a declared regime rule or is removed (OF-OD-09).
- **Role is per strategy.** Each strategy contract declares how it uses each series: veto, filter, ranking feature or none (see [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md)). The funnel applies a veto only to the strategies that declare it, not to the whole cycle. Such a declared context-series veto is recorded as `F3.regime_veto:<series>`. The per-symbol regime (`classify_regime`, STR-09) is a strategy routing rule and travels in `Candidate.features`. A candidate whose regime label its strategy does not accept is recorded at F4 as `F4.regime_not_accepted`, with `sub_stage` `strategy.regime`, and never as a veto (WP-IR-01).
- **Staleness.** Staleness is measured from bar time (P4), so a refresh of old bars cannot look fresh (fixes OF-12). Refresh is independent of whether the engine has rows, so idle periods do not skip refreshes (MKT-15).
- **Failure semantics, explicit.** For each series and each strategy that uses it, the contract records one of:
  - **fail-closed**: no new entries for that strategy while the series is stale or invalid; one cycle-level `RejectionRecord` per affected strategy (`F3.regime_stale`, `F3.regime_unavailable`);
  - **fail-open**: proceed with `regime_unknown` set in the candidate's features, and record `F3.regime_unknown_used` for every candidate so admitted.

  The choice is OF-OD-10. For any series that gates entry, the charter's engineering criterion of no stale decisions (`CHARTER:L57`) constrains that choice. A missing field is never read as zero (fixes OF-14), and the scanner's `neutral` fallback disappears (fixes OF-13).
- **USDT.D and other non-point-in-time inputs.** CoinGecko global data cannot be replayed (STR-12, `MCAS:L517`), and the gate's value has never been verified (ECO-02, `MCAS:L519`). Whether such an input may veto entries is OF-OD-11.
- **Changes.** OF-T06, OF-T07.

### F4. Candle sets and candidate generation per strategy

- **CandleSet.** For each eligible symbol and each timeframe that some strategy uses: closed bars only, `last_close_time`, and `completeness` (no gaps, duplicates, impossible bars or NaN, as `shared/ohlcv.py` already enforces, ARC-13). A bar is closed when its venue close time is earlier than venue-synchronised decision time (F0), not the raw host clock (fixes the EXE-06 risk).
- **Warm-up.** Each strategy contract states its warm-up bars per timeframe. A symbol below it gets `F4.history_insufficient` for that strategy and timeframe instead of today's silent skip (OF-05).
- **Strategy input guards.** A strategy's own input guards file their records at F4 with `sub_stage` `strategy.input` (WP-IR-01):
  - incomplete candles give `F4.data_quality`;
  - too few bars give `F4.history_insufficient`;
  - a regime input past the strategy's declared bound gives `F4.regime_stale`. This is the candidate-scope record; the cycle-level record stays `F3.regime_stale`.

  The strategy's own code is kept verbatim in `detail.strategy_code`.
- **Freshness bound on the decision bar.** A candidate is admissible only if decision time − (`last_close_time` + 1 ms) is non-negative and below the bound for its timeframe. The bound is OF-OD-12; the A44 rule (`shared/signal_identity.py:L186-200 @ ea8ae4f`) uses one bar and is the reference implementation. Rejections are `F4.bar_not_closed` and `F4.bar_stale`. This closes OF-17, under which a 1d decision can rest on a bar about 24 h old.
- **Candidate generation.** Every strategy whose contract admits the symbol, timeframe and regime evaluates its own setup. One `Candidate` exists per (symbol, `strategy_id`, timeframe, `bar_close_time`), carrying `strategy_version`, `setup_key`, `features` and its `risk_plan`. The `risk_plan` is produced once by the strategy's `evaluate` and then frozen (WP-IR-02). There is no symbol-level overwrite (fixes OF-08). A strategy that finds no setup records `F4.no_setup`, with `sub_stage` `strategy.entry`.
- **`setup_key`.** `setup_key` = hash of (identity version, venue, symbol, `strategy_id`, `StrategyVersion` identifier, timeframe, `bar_close_time`, direction `long`).
  - The `StrategyVersion` identifier is derived from the five identity fields: `strategy_id`, `version`, `source_hash`, `config_hash` and `contract_hash` (glossary; WP-IR-09). `lineage` is recorded metadata and never enters the identifier or the key. A release label such as `APP_VERSION` is not enough on its own. Neither the label nor the frozen contract hash detects a selection or integrity-mode change (OF-24, G3-08).
  - Bracket prices are not part of the key. A bracket hash is stored beside it, so a recomputation of the same bar with a different bracket is detected as a conflict, as the A44 design does (`shared/signal_identity.py:L62-88 @ ea8ae4f`).
  - Emission is insert-once under a unique constraint. A repeat evaluation of the same bar yields `F4.duplicate_setup`; a different bracket yields `F4.setup_conflict`. Neither creates a signal (fixes OF-16, R3). Both records carry `sub_stage` `shared.identity`. So does `F4.bar_before_version_activation`, for a bar that closed before the activation minute of the version evaluating it (SE-36).
- **Cooldown.** The 2 h wall-clock cooldown stops serving as a duplicate guard, which the `setup_key` takes over. Whether a per-symbol or per-strategy cooldown remains as a risk rule is OF-OD-13; if it remains, its read fails closed and is recorded (fixes OF-15).
- **Changes.** OF-T08, OF-T09.

### F5. Candidate execution feasibility

- **Rules.**
  - The F2b checks run on a fresh book (book age, spread, depth).
  - F5 reads the `Candidate`'s own `risk_plan`, the same frozen object that F7 sizing later reads through the Opportunity (WP-IR-02).
  - A stop plan must be present and valid. A **missing** `stop_valid` rejects as `F5.stop_missing`; today it passes (section 4).
  - The stop-risk cap is the strategy's volatility bound (`F5.stop_risk_above_cap`).
  - A bracket that breaks the ordering `stop < entry < T1 < T2 < T3` after rounding is `F5.bracket_invalid`.
  - A T1 below the active cost model's net break-even is `F5.t1_not_cost_feasible`. This code is used only if the owner chooses "reject" under SE-80, and it is distinct from `F5.cost_above_budget`.
  - Geometry records that a strategy's `evaluate` returns carry `sub_stage` `strategy.geometry`, with the strategy's own code in `detail.strategy_code` (WP-IR-01).
  - `expected_cost` is computed under a named cost model and recorded on the candidate. The model is named by `cost_model_id` (WP-IR-07). The research models are `research_baseline_v1`, the charter's proposed 0.40% all-in round trip, and `research_stress_v1`, its 0.60% stress case. Both are kept separate from the legacy runtime accounting `legacy_tracker_v1` (`CHARTER:L25`); see [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md). Which model a Paper feasibility check uses is open (DECISIONS_AND_GATES.md section 5, item 5).
  - A candidate whose expected cost exceeds the strategy's cost budget is rejected as `F5.cost_above_budget`. The budget belongs to the strategy contract.
- **Failure semantics.** Fail-closed per candidate, recorded.
- **Changes.** OF-T05, OF-T11.

### F6. Ranking into Opportunities

- **Score.** Each strategy contract defines its `score`: its inputs, direction and units. The funnel does not invent one. The current key is an execution-quality ordering in which setup strength plays no part (STR-13). The frozen `total_score` decides nothing in the target (OF-20; OQ-09). The ranking objective, and how candidates of different strategies compare, is OF-OD-14. One of the options there is separate per-strategy lists, with allocation across strategies left to [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md).
- **Complete ranking.** Every candidate that passed F5 is ranked. Nothing is truncated before ranking: no `LIMIT`, no alphabetical order and no intake cap decides which candidates are seen (fixes OF-03, OF-04, OF-06).
- **Total order.** Candidates sort by (`score` in the contract's direction, then `tie_break_key` ascending). `tie_break_key` is a hash of (selection version, `setup_key`). It is never the symbol name or the timeframe string (fixes OF-21), and the order does not depend on input order (P6).
- **Resource guard.** If an upper bound on rows is needed for memory or time, it must:
  - be sized so that it does not bind in normal operation;
  - when it binds, drop by deterministic hash, never by name;
  - emit `F6.resource_cap` for every dropped candidate;
  - flag the cycle as `ranking_incomplete` in the `DecisionRecord`;
  - raise an operational alert.

  A43's `bounded_universe` already drops by hash and returns every dropped pair, so it can serve the second and third conditions (OF-23).
- **Caps after ranking.** A maximum number of Opportunities per cycle (OF-OD-15) applies only to the complete ranked list. Each candidate below the cap gets `F6.rank_below_cap` with its rank, the offer cap and the selection version in `detail`. That code replaces today's mislabelled `not_selected_capacity` (OF-07).
- **F6 never reads portfolio state.** The offer count is a constant of the selection version (OF-OD-15). A refusal for lack of capacity is never an F6 record: it is `F7.capacity_full`, issued by the single capacity authority at F7 (WP-IR-03, WP-IR-04).
- **Today's cut, in shadow only.** While the legacy query is in force, the shadow recorder files every row cut by the alphabetical `LIMIT 200` as `F6.legacy_alphabetical_cut`, with its position in name order and the limit 200. The code is retired when the new selection is activated (R1.c, WP-G01), and no target selection version ever uses it (WP-IR-04).
- **Output.** An `Opportunity` holds its `Candidate` by reference, plus `score`, `rank`, `tie_break_key` and `expected_cost`, in rank order. The `risk_plan` belongs to the Candidate (WP-IR-02). `Opportunity.risk_plan` is a read-only alias of `Opportunity.candidate.risk_plan`, never a recomputed or edited copy, so both have the same `risk_plan_hash`.
- **Changes.** OF-T10, OF-T11.

### F7. Portfolio constraints (handoff)

The funnel ends at a ranked list of Opportunities. Admission, sizing and portfolio limits belong to [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md): `RiskBudget`, `SizingDecision`, `LedgerEntry`, capacity, exposure, correlation, drawdown and the minimum-order check. This document fixes only the interface.

- **One capacity authority** (WP-IR-03). Capacity is decided once per Opportunity, by the F7 capacity check inside the portfolio `decide(state, snapshot)` (PORTFOLIO_RISK_AND_COMPOUNDING.md §5). It runs in the admission-authority service, which the boundary record names as trade_tracker (`deploy/VERSION_BOUNDARY.md:L12 @ 46578aa`). It either admits or refuses with `F7.capacity_full`. The other sites change role:
  - the delivery gate makes no capacity decision; in shadow it is a recorded mirror of the authority;
  - the tracker pre-check becomes a configuration ceiling checked at start;
  - research `REJECT_MAX_TRADES` maps to `F7.capacity_full`.
- **Order.** Opportunities are offered in rank order, not symbol order (fixes OF-11).
- **Every refusal is recorded.** Each refusal returns a `RejectionRecord` at stage F7 with a reason code from section 8.2, for example `F7.capacity_full` or `F7.min_notional_infeasible`. The acknowledge-and-lose path disappears (fixes OF-10). The F7 codes and their `sub_stage` values follow WP-IR-05 (section 8.2).
- **Refusal semantics are explicit** (OF-OD-16): either drop with a record, or hold in a bounded queue whose time limit does not exceed the F4 freshness bound and re-validate every check before admission. A held item is never admitted on stale inputs.
- **Cooldown.** Whether a refused Opportunity starts any cooldown is declared, not incidental (fixes OF-09).
- **Idempotent admission.** Admission keys on `setup_key`. Supersession of an older pending Opportunity for the same symbol is recorded as `F7.superseded`, not lost.
- **No forced fill.** An empty portfolio is never a reason to admit a lower-ranked or failed candidate (P1).
- **Governance.** Changing Paper admission outside its runbook is listed as forbidden under current governance (`DFP:L104`), so OF-T12 needs an owner decision and a runbook before any activation.
- **Changes.** OF-T12.

### F8. DecisionRecord

One `DecisionRecord` of `decision_type` `opportunity_rank` per cycle (WP-IR-08). It is one of the per-decision records of SE-51 in [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md) §E2, carried in the evidence v2 envelope; no second record type exists. It holds the cycle id and decision time, and the hashes of the `MarketSnapshot`, `RegimeContext`, `StrategyVersion` set and configuration. It also holds the candidate-set hash, the ranked list with keys, the selected Opportunities, the per-stage counters, the conservation result and any `ranking_incomplete` flag. Its `decision_id` is the `cycle_id` of every `RejectionRecord` of that cycle. Re-evaluating `decide(state, snapshot)` on the recorded inputs, in a test, must reproduce the cycle record, every per-decision record and the chain exactly (`CHARTER:L29`). Changes: OF-T13.

## 8. Observability: RejectionRecord, reason codes, counters, sampling

### 8.1 RejectionRecord schema

This is the one `RejectionRecord` schema of the pack (WP-IR-01). [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md) §B3 uses it and does not define a second shape. All times are integer UTC epoch milliseconds. Subject fields are nullable by scope.

| Field | Type | Meaning |
|---|---|---|
| `record_id` | string | Deterministic hash of (`cycle_id`, `stage`, `scope`, subject key, `reason_code`): the identity of the drop |
| `cycle_id` | string | The `decision_id` of the cycle's `DecisionRecord` of `decision_type` `opportunity_rank` (F8; WP-IR-08) |
| `stage` | enum `F0`…`F7` | The stage at which the record is counted for conservation (section 8.3) |
| `sub_stage` | closed enum or null | `strategy.input`, `strategy.regime`, `strategy.entry` or `strategy.geometry` for a record that a strategy's `evaluate` returns. `shared.identity`, `shared.sizing`, `shared.order_intent` or `shared.admission` for a shared producer. Null for a funnel rule (section 8.2) |
| `scope` | enum `cycle`, `symbol`, `candidate`, `opportunity` | A cycle-level record (for example `F0.snapshot_stale`) covers every subject of that cycle and states their number |
| `reason_code` | closed enum, taxonomy v1 (section 8.2) | One code per record, written `F<n>.<reason>`, with its prefix equal to `stage`. A symbol failing several F1 rules gets one record per code |
| `symbol` | string or null | Null only for cycle scope |
| `timeframe` | string or null | Null above F4 |
| `strategy_id` | string or null | Null at F0 to F2a |
| `strategy_version` | string or null | The `StrategyVersion` identifier, derived from the five identity fields with `lineage` excluded (WP-IR-09), when a strategy is involved |
| `setup_key` | string or null | From F4 onwards |
| `bar_close_time` | integer (UTC epoch ms) or null | From F4 onwards |
| `as_of` | integer (UTC epoch ms) | Data time of the input that caused the drop (snapshot, bar, book or regime) |
| `decision_time` | integer (UTC epoch ms) | Venue-synchronised time of the decision |
| `rule_ref` | string | Identifier of the rule and of its owner-decided threshold version |
| `detail` | bounded object | The observed value or values compared with the rule, for example a spread and its limit. A strategy's own code is kept verbatim in `detail.strategy_code`; it is never rewritten and never used as the aggregation key |
| `rank` | integer or null | Set for `F6.rank_below_cap`, `F6.resource_cap` and F7 refusals |
| `snapshot_hash`, `config_hash` | string | Links the record to its inputs |

A record is append-only and never overwritten, unlike today's `decision_reason` column (OF-08). The `DecisionRecord` of `decision_type` `rejection` that carries a record holds both the record's `record_id`, the identity of the drop, and its own `decision_id`, the identity of the computation (WP-IR-08).

### 8.2 Reason-code taxonomy

This is **taxonomy v1**, one closed enumeration (WP-IR-01). Each code is written `F<n>.<reason>`, and its prefix always equals the record's `stage`. The table lists the reason part of each code by stage. Codes marked † are the taxonomy v1 additions of WP-IR-01, WP-IR-04 and WP-IR-05, recorded by WP-A01. The right-hand column maps today's labels, so that a parity test can show the shadow recorder reproduces current decisions before any behaviour changes.

| Stage | Codes | Today's label or behaviour |
|---|---|---|
| F0 | `snapshot_stale`, `snapshot_incomplete`, `clock_offset_exceeded` | Scan aborts; log only |
| F1 | `status_not_trading`, `quote_not_approved`, `stable_or_pegged`, `leveraged_product`, `filters_missing`, `min_order_infeasible`, `listing_age_insufficient`, `owner_excluded`, `symbol_unsupported` | Silent list filter (S2, S3) |
| F2 | `volume_below_floor`, `volume_missing`, `move_below_floor`, `book_stale`, `spread_invalid`, `spread_above_limit`, `depth_insufficient`, `book_unavailable` | S5 silent; `order_book_unavailable`, `spread_invalid`, `spread_exceeds_limit` |
| F3 | `regime_stale`, `regime_unavailable`, `regime_veto:<series>` (a declared context-series veto only), `regime_unknown_used` | `macro_block` for the whole cycle |
| F4 | `history_insufficient`, `data_quality`, `bar_not_closed`, `bar_stale`, `no_setup`, `duplicate_setup`, `setup_conflict`, `cooldown_active`, `state_read_failed`, `regime_stale`†, `regime_not_accepted`†, `bar_before_version_activation`† | Silent skip; `no_trade_setup`; `symbol_cooldown`; enforce-mode integrity reasons |
| F5 | `stop_missing`, `stop_invalid:<reason>`, `stop_risk_above_cap`, `cost_above_budget`, `bracket_invalid`, `t1_not_cost_feasible`† | `stop_rejected:<reason>`; missing value passes |
| F6 | `rank_below_cap`, `resource_cap`, `legacy_alphabetical_cut`† (shadow record of today's cut only) | `not_selected_capacity` and the evidence decision `rejected_fixed_policy_rank`, both `F6.rank_below_cap` with offer cap 1; truncated rows unrecorded, `F6.legacy_alphabetical_cut` in shadow |
| F7 | `paused`, `capacity_full`, `exposure_gross`†, `exposure_symbol`, `exposure_strategy`, `exposure_regime`, `exposure_correlation`, `heat_cap`†, `risk_state_invalid`, `mark_stale`†, `ledger_mismatch`†, `ledger_event_conflict`†, `economic_limit:<rule>`†, `min_notional_infeasible`, `no_price`, `entry_rejected`, `entry_wait_expired`, `superseded`, `already_registered` | `portfolio_capacity_<n>/<m>` acknowledged and lost; tracker admission reasons in research events only |

**F7 and sizing codes** (WP-IR-05). One code exists per cause:
- **Minimum order.** `F1.min_order_infeasible` is the universe pre-check: the smallest order the `RiskBudget` allows cannot clear the venue floor. `F7.min_notional_infeasible` covers two cases:
  - a sized quantity, rounded down to the step, is below the venue minimum (`sub_stage` `shared.sizing`; PR's `below_min_notional`);
  - an `OrderIntent` fails re-validation (`shared.order_intent`; SE's `below_exchange_minimum`).
- **Technical reasons.** `F7.risk_state_invalid` covers invalid or non-finite risk inputs. The legacy string `invalid_risk_state` stays byte-identical in the legacy `RiskDecision` and is kept in `detail.legacy_reason`. `F7.mark_stale`, `F7.ledger_mismatch` and `F7.ledger_event_conflict` are the technical refusals of PORTFOLIO_RISK_AND_COMPOUNDING.md §3.4–§3.5. All four carry `sub_stage` `shared.admission`.
- **Economic limits.** `F7.economic_limit:<rule>` applies in enforce mode only. The rule is one of `daily_loss_limit`, `weekly_loss_limit`, `max_drawdown_limit` and `loss_streak_halt`. In observe mode there is no `RejectionRecord`, only the `DecisionRecord` annotation `observed:<rule>`.
- **Exposure and heat.** `F7.exposure_gross` maps today's `gross_exposure_limit`. `F7.exposure_symbol`, `F7.exposure_strategy` and `F7.exposure_regime` map the `*_concentration_limit` reasons. `F7.exposure_correlation` is the correlated-cluster cap; `cluster_cap` stays the `RiskBudget` field name, not a code. `F7.heat_cap` (`shared.sizing`) means the portfolio heat cap leaves no feasible size.
- **Capacity and pause.** `F7.capacity_full` (WP-IR-03) and `F7.paused` carry `sub_stage` `shared.admission`. A legacy ladder reason that labels a capacity refusal is kept in `detail` (WP-IR-04).

New codes may be added only with a version bump of the taxonomy; a code is never reused with a different meaning.

**Alignment with the strategy contract and the shared producers.** [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md) has each strategy's `evaluate` return either a `Candidate` or a `RejectionRecord`. Its stage names (`strategy.input`, `strategy.regime`, `strategy.entry`, `strategy.geometry`) go in `sub_stage`. Its own codes, such as `incomplete_candles`, go verbatim in `detail.strategy_code`. The `reason_code` is always the one canonical funnel code below. A reason is therefore never rewritten, and each drop has exactly one aggregation key (WP-IR-01). In the canonical mapping each `sub_stage` value appears at one stage only:

| `sub_stage` | Funnel stage | Canonical `reason_code` ← strategy, shared or research name |
|---|---|---|
| `strategy.input` | F4 | `F4.data_quality` ← `incomplete_candles`, research `REJECT_DATA_QUALITY`; `F4.history_insufficient` ← `insufficient_history`, research `NOT_ELIGIBLE_INSUFFICIENT_HISTORY`; `F4.regime_stale` ← `stale_regime`, candidate scope only, while the cycle-level record stays `F3.regime_stale` |
| `strategy.regime` | F4 | `F4.regime_not_accepted` ← the strategy's own regime routing, research `REJECT_REGIME`. `F3.regime_veto:<series>` stays reserved for a declared context-series veto |
| `strategy.entry` | F4 | `F4.no_setup` ← research `REJECT_ENTRY`; legacy label `no_trade_setup` |
| `strategy.geometry` | F5 | `F5.stop_risk_above_cap` ← `structural_risk_exceeds_cap`, research `REJECT_STOP_DISTANCE`, legacy label `stop_rejected:<reason>`; `F5.bracket_invalid` ← `invalid_geometry`; `F5.t1_not_cost_feasible` ← `t1_not_cost_feasible`, only if SE-80 chooses "reject"; `F5.stop_missing` ← a missing stop plan |
| `shared.identity` | F4 | `F4.duplicate_setup` ← `duplicate_setup_key` (a different bracket on the same key is `F4.setup_conflict`); `F4.bar_before_version_activation` ← `bar_before_version_activation` (SE-36) |
| `shared.order_intent` | F7 | `F7.entry_rejected` ← `signal_invalidated_before_fill`, with `detail.rule` keeping the SE name; `F7.entry_wait_expired` ← the transition to `EXPIRED_UNFILLED`; `F7.min_notional_infeasible` ← `below_exchange_minimum` |
| `shared.sizing` | F7 | `F7.min_notional_infeasible` ← PR `below_min_notional`; `F7.heat_cap` |
| `shared.admission` | F7 | `F7.capacity_full`, also for today's `delivery.refused` with `portfolio_capacity_<n>/<m>` and for research `REJECT_MAX_TRADES`; `F7.paused`; `F7.risk_state_invalid`; `F7.mark_stale`; `F7.ledger_mismatch`; `F7.ledger_event_conflict`; `F7.economic_limit:<rule>` ← research `REJECT_DAILY_RISK`, `REJECT_WEEKLY_RISK`, `REJECT_DRAWDOWN`; the exposure codes. The research catch-all `REJECT_PORTFOLIO_CAP` is split by its `detail.reason` |

Research `REJECT_RANK_CAPACITY` is not reused. It conflates a rank loss with capacity, as OF-07 does, and it maps to `F6.rank_below_cap` (WP-IR-04). The tracker pre-check stop maps to `F7.capacity_full`, with `detail.check` naming the tracker pre-check.

### 8.3 Counters and the conservation check

For every cycle and stage, counters record the inputs `in`, those passed, and those rejected per reason code. The `DecisionRecord` carries them.
- **Per-stage conservation:** `in = passed + Σ rejected`. A stage whose input splits into several subjects (one symbol into several strategy × timeframe candidates) states its expansion count explicitly.
- **Ranking conservation:** `ranked = Opportunities offered + rank_below_cap + resource_cap`. In the shadow record of today's funnel only, `F6.legacy_alphabetical_cut` is also an F6 outcome.
- **One stage per record.** Each record is counted under its own `stage` only (WP-IR-01).
- **Handoff conservation:** `Opportunities offered = admitted + Σ F7 refusals + held`.
- **Violation.** A violated equation marks the cycle invalid for evidence purposes and raises an operational alert. It does not silently pass.

### 8.4 Sampling and retention policy

- **Counters are never sampled.**
- **Per-candidate records (F4 to F7)** are written in full for every rejection.
- **Universe-level records (F0 to F2a)** concern every listed symbol on every scan. They may be compacted into one record per (symbol, reason code) state change only if the counters stay complete and each compacted series carries `first_seen`, `last_seen` and `repeat_count`. Compaction therefore shortens storage but hides no drop. Today's research stream suppresses repeats in the same way but caps its truncation list at 500 rows (OF-25); the target has no such cap.
- **Retention** must outlive the evaluation window of any `StrategyVersion` whose evidence the records support. Today's 1 h and 2 h retention (`shared/maintenance.py:L6-13 @ ea8ae4f`) is too short for that. The duration and storage budget are OF-OD-18.
- **Access.** Records and counters written by Paper after the research freeze are protected forward material (P12). Operational health may expose liveness and the pass or fail state of the conservation check without counts. Any read of counts or records for analysis is a protected-data action requiring owner permission.

## 9. Target change register

Every change carries exactly one change class. "Safe development-only correction" means default-off, with no runtime effect: with the flag off, outputs must be byte-identical to current behaviour. A safe development-only correction does not authorise its own activation. Activation of any item is OF-T15, a separate production/runtime change (`CHARTER:L51`; `DFP:L104`). Sub-item numbering under R1–R9 belongs to [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md); sequencing belongs to [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md).

### 9.1 Summary

| ID | Change | Change class | Item | Fixes | Owner decisions |
|---|---|---|---|---|---|
| OF-T01 | `RejectionRecord` writer, reason taxonomy, counters and conservation check, run in shadow beside the current funnel | Safe development-only correction (default-off, no runtime effect) | R6 | OF-03 to OF-11 (visibility only) | OF-OD-18 |
| OF-T02 | Per-(symbol, strategy, timeframe, bar) decision keys in place of per-symbol `last_decisions`, recorded only | Safe development-only correction (default-off, no runtime effect) | R6 | OF-08 | — |
| OF-T03 | Exchange-agnostic `MarketSnapshot` adapter with `as_of`, `source`, clock offset and content hash, captured in shadow | Safe development-only correction (default-off, no runtime effect) | R6, R5 | OF-17 (clock), OF-18 (data only) | — |
| OF-T04 | `EligibilityResult` rule set of F1, including venue filters and minimum-order feasibility | Strategy-version-changing correction | R6 | OF-05, OF-18 | OF-OD-01 to OF-OD-05 |
| OF-T05 | F2 liquidity, fresh-book spread, depth and movement checks; F5 feasibility including `stop_missing` | Strategy-version-changing correction | R6 | EXE-05 (book age), section 4 stop row | OF-OD-06 to OF-OD-08 |
| OF-T06 | Single BTC trend in `RegimeContext`, bar-time staleness, per-strategy roles; scanner stress rule moved or removed | Strategy-version-changing correction | R6, R9 | OF-12, OF-19 | OF-OD-09 to OF-OD-11 |
| OF-T07 | Removal of the three fail-open paths: scanner `neutral`, macro missing field read as zero, cooldown read error | Strategy-version-changing correction | R6, R3 | OF-13, OF-14, OF-15 | OF-OD-10 |
| OF-T08 | Venue-synchronised closed-bar rule and freshness bound on the decision bar | Strategy-version-changing correction | R6, R3 | OF-17 | OF-OD-12 |
| OF-T09 | `setup_key` derived from `StrategyVersion`, insert-once emission, conflict detection; cooldown no longer used as a duplicate guard | Strategy-version-changing correction | R3 | OF-16 | OF-OD-13 |
| OF-T10 | Removal of `ORDER BY symbol … LIMIT 200`; complete ranking; hash tie-break; caps only after ranking; resource guard with records | Strategy-version-changing correction | R1 | OF-03, OF-04, OF-06, OF-21 | OF-OD-15 |
| OF-T11 | Score per strategy contract; frozen `total_score` removed from ordering; `expected_cost` on every candidate | Strategy-version-changing correction | R1 | OF-20, STR-13 objective gap | OF-OD-14 |
| OF-T12 | F7 interface: rank-order offering, recorded refusals, explicit refusal semantics, declared cooldown effect, `setup_key` admission | Strategy-version-changing correction | R6, R7 | OF-09, OF-10, OF-11 | OF-OD-16 |
| OF-T13 | Per-cycle `DecisionRecord` (`decision_type` `opportunity_rank`, WP-IR-08) with input hashes, and deterministic `decide(state, snapshot)` | Safe development-only correction (default-off, no runtime effect) | R6, R5 | traceability | — |
| OF-T14 | Measurement of how often each drop occurred (truncation frequency, refusals, stale blocks) on recorded runtime or historical data | Protected research or simulation | R1, R6 | UNI-17 and section 11 unknowns | OF-OD-17 |
| OF-T15 | Activation in Paper of any change above, as a declared window | Production/runtime change | per item | — | per item, plus window declaration |

### 9.2 Tests and acceptance criteria

All tests below run on synthetic fixtures with injected clocks. None reads production data, runtime evidence or holdouts. Each Strategy-version-changing item also needs a **parity test**: with its flag off, outputs equal the current funnel's outputs on the same fixtures.

**OF-T01.** Tests: a synthetic cycle in which every stage rejects at least one subject, checked for one record per rejection and for exact conservation; a fixture with more than 700 fresh rows (above the current 200 + 500 visibility) in which every cut row appears; a broken writer that must not alter decisions. Acceptance: (a) conservation holds on every fixture; (b) no rejection in the fixture lacks a record; (c) decision outputs are byte-identical with the writer on and off.

**OF-T02.** Tests: one symbol with three timeframes and three different rejection reasons. Acceptance: three distinct records; no reason is overwritten.

**OF-T03.** Tests: adapter fixtures for listing, filters and 24 h statistics; stale and partial snapshots; clock offset injected on both sides of its bound; identical inputs hashed twice. Acceptance: a stale or partial snapshot never reaches F1; identical inputs give identical hashes; no venue field name appears outside the adapter.

**OF-T04.** Tests: one symbol per F1 rule failing alone, and one failing several; a notional floor above the smallest allowed order; a missing filter. Acceptance: every symbol gets an `EligibilityResult` listing all of its failed rules; a missing input is ineligible, never eligible; no rule reads BTC context.

**OF-T05.** Tests: book age on both sides of its bound; NaN, negative and missing spreads; depth just above and below its multiple; a missing `stop_valid`. Acceptance: each failure gives its own code; a missing stop rejects; the spread used is from a book within its age bound.

**OF-T06.** Tests: regime bars that are fresh by refresh time but stale by bar time; an idle engine; one strategy declaring a veto and another declaring none. Acceptance: exactly one BTC trend function exists; staleness is computed from bar time; a veto applies only to the strategies declaring it; the universe is the same whatever the BTC label.

**OF-T07.** Tests: kline fetch error for BTC; payload missing the dominance field; cooldown read raising. Acceptance: no path yields `neutral`, a zero or an empty cooldown set by default; each yields its declared fail-closed or fail-open outcome plus a record.

**OF-T08.** Tests: a bar closing 1 ms after decision time; a bar exactly at the freshness bound; host clock ahead of and behind venue time. Acceptance: no forming bar and no bar beyond the bound produces a candidate.

**OF-T09.** Tests: the same closed 4h and 1d bar re-analysed on every scan for its whole life, across a process restart; the same bar with a different bracket; a changed `StrategyVersion`. Acceptance: exactly one emission per `setup_key` (the R3 regression); a conflicting bracket is recorded and not emitted; a new version gives a new key.

**OF-T10.** Tests: 300 symbols × 3 timeframes, with the best candidate's symbol last in name order (the R1 regression); random permutations of the input; ties on score; a resource guard forced to bind. Acceptance: the best candidate is selected whatever its name; the output does not change under permutation; ties resolve on `tie_break_key`; every guard drop and every below-cap item has a record with its rank.

**OF-T11.** Tests: two candidates whose current execution-quality order and contract score order differ; candidates of two strategies. Acceptance: the order follows the contract score; `total_score` has no effect on order; the cross-strategy rule is the one OF-OD-14 records.

**OF-T12.** Tests: three Opportunities and one free slot; a refusal with a bounded hold that expires; two pending Opportunities on one symbol. Acceptance: admission follows rank; every refusal has a record; a held item is re-validated or dropped with a record; supersession is recorded; refusal starts a cooldown only if declared.

**OF-T13.** Tests: re-evaluate recorded synthetic inputs. Acceptance: an identical `opportunity_rank` cycle record, including the ranked list and counters, and identical per-decision records, identifiers and chain (WP-IR-08).

**OF-T14.** Not designed here beyond its gate. It may run only after the owner grants the data permission (OD-DF-1, `DFP:L113`) and under a preregistered protocol. A finding of frequent truncation would describe evidence validity, not profitability (`DIA:L206-215`).

## 10. Owner decisions

Each item below is **OWNER DECISION REQUIRED**. The options are not ranked, and no threshold is proposed. **Until a decision is recorded in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md), the current value and behaviour stay in force and nothing new is activated** (P11). Any decision that changes eligibility, ranking, emission or admission opens a new `StrategyVersion` (P10).

| ID | Question | Options and trade-offs |
|---|---|---|
| OF-OD-01 | Universe scope (OQ-07, `MCAS:L711`) | (a) Every pair that passes F1 and F2: the widest discovery, but more records and more compute, more small-cap exposure, and more multiple-testing burden for any later evaluation. (b) A predeclared fixed list: stable and comparable evidence, but it may miss opportunities and invites hindsight in choosing the list. (c) A liquidity-ranked set chosen **after** a complete ranking, with records: bounded work, but the cut must be recorded and must not be alphabetical |
| OF-OD-02 | Quote assets | (a) USDT only (current). (b) USDT plus named stable quotes: more pairs, but the same base asset can appear twice, so F7 needs a base-asset exposure rule. (c) Per venue, set in the adapter: exchange-agnostic, but harder to compare across venues |
| OF-OD-03 | Stablecoin and pegged-asset rule | (a) A named list: explicit, but it goes stale (today only three pairs, UNI-02). (b) A rule, such as a venue category or a price band around a peg: general, but it can misclassify. (c) Both, with the list overriding |
| OF-OD-04 | Leveraged or ETF-style products | (a) Exclude using venue metadata where it exists. (b) Exclude by a name pattern: simple, but brittle. (c) Allow: wider universe, but these products embed leverage, so the owner must state whether that is compatible with an unleveraged system (`CHARTER:L8`) |
| OF-OD-05 | Listing age and history sufficiency | (a) Strategy warm-up only (current: 200 closed bars per timeframe, so about 200 days for 1d, UNI-13). (b) Warm-up plus a minimum listing age: avoids the most erratic new listings, but adds a survivorship-style filter. (c) Per-strategy history rules set in each contract |
| OF-OD-06 | Liquidity and depth | (a) Keep the 24 h quote-volume floor alone (10M today, VER-08). (b) A floor scaled to the planned order notional: ties liquidity to size, so growth by compounding tightens it automatically. (c) A depth requirement (distance from mid and a multiple of order notional): closest to executable size, but it needs a fresh book per candidate and a defined depth source |
| OF-OD-07 | Spread limit and book freshness | (a) Keep one fixed spread limit (0.15% today, VER-09). (b) A per-strategy limit derived from its cost budget: consistent with the cost model, but it needs a cost model for each strategy first. (c) Tiers by liquidity. In every option, the maximum book age is a separate value to set |
| OF-OD-08 | Minimum 24 h movement (1% today, 5% under scanner BTC stress) | (a) Keep: fewer idle symbols, but it is a recorded snooping concern (HIS-37). (b) Remove: a cleaner universe, with more candidates per cycle. (c) Replace with a volatility band declared in each strategy contract |
| OF-OD-09 | The single BTC trend, and the scanner stress rule | Definition: (a) the macro definition (68 h, ±1/±5); (b) the scanner definition (36 h, ±1/±3); (c) a new definition preregistered in a strategy contract. Stress rule: keep it as a declared F3 rule for the strategies that opt in, or remove it. BTC SMA200 may appear only as a benchmark or as a candidate hypothesis, never as a default gate (`CHARTER:L15`) |
| OF-OD-10 | Failure semantics per context series and per state read | (a) Fail-closed for every input that gates entry: no stale decisions, but discovery pauses during data outages. (b) Fail-open with a recorded `regime_unknown` flag: discovery continues, but decisions rest on unknown context. (c) Set per series and strategy in each contract. The charter's criterion of no stale decisions applies to entry-gating inputs (`CHARTER:L57`) |
| OF-OD-11 | USDT.D veto (not point-in-time; never validated) | (a) Keep it as a veto for the strategies that declare it. (b) Demote it to a recorded feature. (c) Replace it with a point-in-time source before any veto use. Options (a) and (c) need a declared staleness rule |
| OF-OD-12 | Freshness bound on the decision bar | (a) One bar (the A44 reference): for 1d, a 24 h-old bar can still decide. (b) A fraction of a bar per timeframe: fresher decisions, but late detections are lost. (c) A fixed duration across timeframes: simple, but it treats 15m and 1d alike |
| OF-OD-13 | Cooldown once `setup_key` exists | (a) None: `setup_key` alone prevents duplicates. (b) A per-symbol cooldown as a risk rule: limits repeated exposure to one coin, but blocks distinct setups. (c) A per-strategy cooldown |
| OF-OD-14 | Ranking objective and cross-strategy comparison | (a) Execution quality (current: spread, then volume). (b) Each contract's own score, with separate per-strategy lists and allocation across strategies in [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md). (c) A common unit for all strategies, such as expected cost in R. No option is preferred here, and none implies a profitable strategy |
| OF-OD-15 | Opportunities offered per cycle | (a) One (current): entries are spaced out, but good candidates wait. (b) Every ranked Opportunity up to free capacity: no waiting, but entries cluster in time; a code comment records that the legacy inter-signal cooldown was added after a burst of entries within about half an hour (`signal_engine/signal_logic.py:L433-438 @ ea8ae4f`; DOCUMENTED_ONLY). (c) A fixed number per cycle. Canonical reading of option (b) (WP-IR-04): F6 never reads portfolio state; it offers every ranked Opportunity, and the F7 capacity authority refuses the excess with `F7.capacity_full`, each record carrying its rank |
| OF-OD-16 | Refusal semantics at F7 | (a) Drop with a record: simple, and no stale admission. (b) A bounded hold, re-validated, with a time limit no longer than the freshness bound: fewer lost opportunities, at the cost of more state and recovery logic |
| OF-OD-17 | Permission to measure drop frequencies (OF-T14) | (a) None: frequencies stay NOT_VERIFIED. (b) Licence-cleared data entirely outside every holdout, under OD-DF-1 (`DFP:L113`). (c) Named runtime tables before the freeze only, if any exist. Each option is a protected-data decision |
| OF-OD-18 | Retention, compaction and read access for `RejectionRecord` | Retention duration; whether universe-level compaction (section 8.4) is allowed; storage budget; and who may read counts (P12) |

## 11. Not verified

| What | Status and blocker |
|---|---|
| How often `LIMIT 200` binds (UNI-17) and how often any drop in section 3 occurs | NOT_VERIFIED. No pre-freeze measurement exists in a tracked document; the runtime records are protected forward material (`DIA:L196-204`) |
| Whether the analyzer backlog has ever exceeded what is cleared within 1 h (OF-04) | NOT_VERIFIED. It needs runtime tables or logs. In the tracked schema `scan_candidates` has only a serial key (`database/init.sql:L209-216 @ ea8ae4f`), so `ON CONFLICT DO NOTHING` never fires and each scan adds one row per passing symbol; the runtime schema was not read |
| Database collation that orders `symbol` | NOT_VERIFIED (`DIA:L189`) |
| That running images contain the code read | DOCUMENTED_ONLY; image filesystems not read (RT-16, RT-17) |
| Whether research truncation events exist for any pre-freeze period | NOT_VERIFIED; reading them needs owner permission |
| Venue filter semantics on venues other than Binance Spot | NOT_VERIFIED; no other adapter exists |

## 12. Consistency notes and deviation check

**No DEVIATION ALERT.** The design keeps the charter objective and its non-goals (`CHARTER:L7-10`):
- it forces no trades;
- it places no BTC-only restriction;
- it treats BTC SMA200 only as a benchmark or candidate;
- it chooses no threshold, risk percentage or position count;
- it accesses no protected data;
- it leaves the approved A29 endpoint untouched;
- it claims no profitability.

**Governance note, not a deviation.** OF-T12 changes Paper admission behaviour. The development-first approval matrix lists "changing Paper admission … outside its runbook" as forbidden under current governance (`DFP:L104`). OF-T12 therefore stays a design until the owner decides it and a runbook exists.

**Inconsistencies found in the current state** (all SOURCE_VERIFIED unless stated):
- Rank losers are labelled `not_selected_capacity` although no capacity check was made (OF-07). Their target code is `F6.rank_below_cap` (WP-IR-04).
- The code compares `'strong_bearish'`; audit tables use the shorthand `strong_bear` (`MCAS:L168`; DOCUMENTED_ONLY).
- Capacity is checked in three places with different inputs:
  - the delivery gate uses min(10, 2);
  - the tracker loop uses `MAX_OPEN_TRADES` = 10;
  - the risk policy uses min(10, 2).

  The effective limit is 2 (VER-12), but the duplication is a parity risk for F7 (`telegram/main.py:L379 @ bb7825f`; `trade_tracker/main.py:L708-716, L979 @ bb7825f`). A zero limit also means different things. It means "unlimited" at the delivery gate and the tracker pre-check, which check only a limit above zero (`telegram/main.py:L380 @ bb7825f`; `trade_tracker/main.py:L708, L752 @ bb7825f`). The risk policy refuses it as `invalid_risk_state` (`shared/risk_management.py:L71-76 @ bb7825f`). This list describes today. The target has one capacity authority at F7, where an invalid limit always refuses with `F7.risk_state_invalid` (WP-IR-03; section 7, F7).
- The A44 setup key uses a release label as its strategy version. The frozen contract hash does not register a change of the selection cut or of the integrity mode (OF-24; `DIA:L272-277`). The target's `StrategyVersion` needs both content hashes and declared boundaries.

**Cross-document dependencies.**
- The score definition, warm-up, stop-risk cap, cost budget and context roles come from [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md).
- The minimum-order check, capacity, exposure and refusal handling come from [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md).
- The R-item sub-numbering comes from [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md).
- The owner decisions are collected in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md).
- If any of these documents settles a point differently, that document governs its own domain, and this one must be aligned to it.
- Interface names follow the canonical choices WP-IR-01 to WP-IR-09 of [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md) section 8, applied here on 2026-11-01 (WP2).
