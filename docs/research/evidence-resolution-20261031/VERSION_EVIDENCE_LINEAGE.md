# Version and evidence lineage (ERG-01 workstream G2)

**Phase:** ERG-01 Evidence Resolution Gate. Documentation-only and read-only.
**Pinned tree:** `5d977f2` (= `main` `eba90dd` plus the 2026-10-31 audit package). Other commits were read with `git show`, `git log` and `git diff --stat`.
**Audit baseline.** The following findings are defined in [REVIEWER_EVIDENCE_PACK.md](../../audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md) and [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](../../audits/2026-10-31-trading-system-review/RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md), and are treated as the 2026-10-31 historical baseline:
- HIS-01: pre-freeze live Paper audit;
- HIS-09: Phase 3 entry hypotheses;
- HIS-14: canary Phase A-R2;
- STR-25: current rules introduced at the freeze;
- HIS-46: the audit's inferred lineage.

**Method and limits.**
- Only code, specs, Markdown and governance or configuration text were read.
- Nothing was executed, and no data artefact or JSON result dump was opened.
- Every evaluation window discussed here ends on or before 2026-08-17, before the 2026-08-19 research freeze (instant recorded in `research_freeze.json`).
- No FORWARD_HOLDOUT outcome, count or timestamp is read or reproduced.
- No profitability claim is made.

## 1. Bottom line

- **G2-01 · INFERRED.** None of HIS-01, HIS-09 or HIS-14 can be attributed to the exact strategy now on the live path: analyzer and signal_engine at `ea8ae4f`, tracker at `bb7825f`.
  - The momentum and reversion predicates, the regime classifier, the indicator definitions and the per-timeframe expiry all changed at `63da7d3`, dated 2026-08-19 (section 2, SOURCE_VERIFIED).
  - All three evaluation windows close earlier: HIS-01 by 06-21, HIS-14 by 07-06, HIS-09 by 08-17.
  - All three also predate the signal-aware stops and partial exits added at `c4a623c` on 2026-08-18.
  - This confirms STR-25 and turns the date-based part of HIS-36 into a source-level fact.
- **G2-02 · CONTRADICTORY.** Version labels do not identify implementations.
  - `APP_VERSION` defaults to `sb-2026.06` in `shared/config.py` but to `sb-2026.08` in Compose and the Dockerfiles, and the runtime value is `sb-2026.08` (audit VER-13).
  - `sb-2026.08` was introduced on 2026-08-17, two days **before** the entry rules changed. It therefore labels both the pre-`63da7d3` code (the HIS-09 cohort's tail) and the deployed post-`63da7d3` code.
  - The runtime `EVIDENCE_PHASE_ID` `PhaseB-FixedPolicy-20260817` (audit VER-20) was likewise named on 2026-08-17. It is not set anywhere in tracked code or Compose.
- **G2-03 · CONTRADICTORY.** The "clean Paper cohort `sb-2026.08`" (HIS-09, HIS-46) is a date cohort, not a version cohort.
  - The review script selects trades by exit time ≥ `LEARNING_CLEAN_START` (2026-07-20) and has no version filter.
  - The `strategy_version` column and the `sb-2026.08` default were added on 2026-08-17, and older signals were back-filled as `legacy`.
  - Contemporary documents say only the last seven trades carried `sb-2026.08`.
- **G2-04 · CONTRADICTORY.** HIS-01's "15m/4h" strategy label and its "2026-04-09 → 06-21" window are not stated in `REPORT.md` itself.
  - The window comes from a later document.
  - The timeframe label conflicts with the code default at the time (`15m,1h,4h,1d`).
  - HIS-01's sample also spans at least six entry-rule commits.
- **G2-05 · SOURCE_VERIFIED.** STR-25's inputs check out in the repository:
  - `63da7d3` is dated 2026-08-19;
  - `research_freeze.json` records `freeze_git_sha` = `63da7d3` and `freeze_git_dirty` = true;
  - `63da7d3` is an ancestor of `ea8ae4f`, which is an ancestor of `bb7825f`;
  - the entry modules are byte-identical from `63da7d3` to `ea8ae4f`.
  - STR-25's conclusion (no accessible pre-freeze economic evidence for the exact rules) stands as INFERRED.

## 2. Timeline: entry-rule, exit-rule and label commits

Every row is SOURCE_VERIFIED from `git log --date=short` on `eba90dd` for `analyzer/technical_analyzer.py`, `analyzer/simple_entry.py`, `shared/regime.py`, `shared/signal_stop.py` and the named files. Dates are commit dates.

| Date | Commit | Change | Relevance |
|---|---|---|---|
| 2026-04-05 → 05-17 | `cea52e6`, `2d11780`, `ad1654b`, `42b0ba7`, `2e695e1`, `4651e1e`, `39ab985`, `19a992c`, `ba2345b` | Legacy indicator-score path: multi-timeframe confirmation, score rebuild, RSI / Bollinger / StochRSI scoring edits, per-timeframe SL cap | Six of these change scoring or stop rules **inside** the HIS-01 window |
| 2026-05-16 | `fc8dd27` | `shared/triple_barrier.py` added | Exit engine for later cohorts |
| 2026-06-23 | `977746f` | HIS-01 report committed | End of HIS-01 |
| 2026-06-25 | `d922cfc`, `1680889`, `7099d89` | `analyzer/simple_entry.py` added (`detect_trade_type`, blob `7755075`); `trade_type` attached in live-learning mode | First momentum / reversion predicates |
| 2026-06-28 | `7b45a8f` | `APP_VERSION` added to `shared/config.py`, default `sb-2026.06` | First version label |
| 2026-06-30 | `4f84717` | Selection preference flipped from momentum to reversion | The canary's "two policies" (HIS-14) |
| 2026-07-29 | `cdd3450` | Trade-type preference neutralised | Inside the HIS-09 window |
| 2026-08-17 | `14fc775` | Compose `APP_VERSION` default `sb-2026.08`; `LEARNING_CLEAN_START` = 2026-07-20; migration 005 adds `signals.strategy_version` and back-fills `legacy` | Label created at the end of the HIS-09 window |
| 2026-08-17 | `605a962`, `7bf6214` | Phase 3–9 reports and review scripts; canary policy frozen and learned gates contained | HIS-09 to HIS-12 written |
| 2026-08-18 | `c4a623c` | `shared/signal_stop.py` and `shared/partial_exits.py` added (signal-aware stops, realtime tracking) | After every evaluated window |
| 2026-08-19 | `63da7d3` | Regime routing (`shared/regime.py`, new); `detect_trade_setup` (blob `61ca698`) with regime gates; reversion adds close > open and Bollinger position ≤ 0.20; indicator changes; per-timeframe expiry in `triple_barrier.py` | **Current rules.** Freeze-date commit |
| 2026-09-27 → 10-15 | `2edca45`, `c324d0b`, `01681fb` | Evidence and integrity instrumentation in the analyzer | Changes no predicate (see G2-06) |
| 2026-10-20 | `a4a7561` | `T1_CAP_POLICY` switch, default `legacy_window_v1` | Not in the deployed analyzer `ea8ae4f` |

Supporting SOURCE_VERIFIED checks:
- The blob of `analyzer/simple_entry.py` is `7755075` at `7099d89`, `605a962`, `c4a623c` and `63da7d3~1`.
- It is `61ca698` at `63da7d3` and `ea8ae4f`.
- `git diff --stat 63da7d3 ea8ae4f` is empty for `analyzer/simple_entry.py`, `shared/regime.py`, `shared/signal_stop.py` and `shared/triple_barrier.py`.
- `git diff --stat 63da7d3 bb7825f -- shared/triple_barrier.py` is empty.

- **G2-06 · SOURCE_VERIFIED.** The deployed path is not identical to `63da7d3` outside the entry modules. Between `63da7d3` and the deployed commits:
  - `signal_engine/signal_logic.py` gained 388 lines and lost 38 (`git diff --shortstat 63da7d3 ea8ae4f`);
  - `trade_tracker/main.py` gained 688 and lost 56 (`63da7d3` → `bb7825f`);
  - `analyzer/technical_analyzer.py` gained 21 lines: `evidence_v2` point-in-time stamps and A44 candle-identity fields. Their own comments say no decision reads them, and the identity fields appear only in `SIGNAL_INTEGRITY_MODE=enforce`. Read from `git diff 63da7d3 ea8ae4f`; that they do not change decisions is INFERRED from the diff.
  - Even evidence generated right after `63da7d3`, which is sealed in any case, would not be exactly the deployed selection and tracking stack. INFERRED.

## 3. Version-to-evidence matrix

### 3.1 Identity, timeframes and rules

| Item | Implementation identity | Timeframes | Entry rules | Exit rules |
|---|---|---|---|---|
| **HIS-01** pre-freeze live Paper audit | **No version label.** `REPORT.md` names no commit, version or `APP_VERSION` (`research/skill_application/out/REPORT.md @ 977746f` · SOURCE_VERIFIED), and `APP_VERSION` did not exist before `7b45a8f` (2026-06-28). This is the legacy indicator-score path, changed by six rule commits inside the window (section 2) | **NOT_VERIFIED.** Code default `15m,1h,4h,1d`, main `TIMEFRAME` 4h (`shared/config.py:L32-36 @ 977746f` · SOURCE_VERIFIED). 4h was banned as the main timeframe from 2026-05-16 (`docs/claude/strategy-history.md:L9 @ 5d977f2` · DOCUMENTED_ONLY). "15m/4h" appears only in later summaries | Legacy mean-reversion score: five indicators, `min_score` 3.0 held in DB settings (`strategy-history.md:L5-8` · DOCUMENTED_ONLY); per-commit rules SOURCE_VERIFIED only as the commit list | Dynamic stop from 2026-05-16 (break-even after T1, 2.5% trail after T2) (`strategy-history.md:L9` · DOCUMENTED_ONLY). Exits before 05-16: NOT_VERIFIED |
| **HIS-14** canary Phase A / A-R2 | `EVIDENCE_PHASE_ID=PhaseA-R2` (`docs/canary_state.md:L31-34 @ 5d977f2` · DOCUMENTED_ONLY). `APP_VERSION` emitted then: NOT_VERIFIED (code default `sb-2026.06`). The canary text says its branch was "NOT merged to main" (L6), yet the flip commit `4f84717` is an ancestor of `eba90dd` (SOURCE_VERIFIED) | Evidence-recorder filter `15m,4h,1d` (L31 · DOCUMENTED_ONLY). Analyzer `TIMEFRAMES` then: NOT_VERIFIED | `detect_trade_type`, blob `7755075` (SOURCE_VERIFIED). Momentum: close > EMA20 > EMA50, close > prior 20-bar high, volume > 1.2 × mean. Reversion: RSI < 35, close > previous close, close < 1.01 × lower band. **No regime gate.** Selection preference flipped momentum → reversion on 06-29 (`4f84717`; canary L95), and learned gates kept adapting (L79-83) | Legacy ATR/support stop (`analyzer/technical_analyzer.py:L400-403 @ 605a962`; identity at the canary dates INFERRED). No per-timeframe expiry; no `partial_exits.py` (both added later · SOURCE_VERIFIED) |
| **HIS-09** Phase 3 (cohort reused by HIS-10 to HIS-12) | The review script prints the runtime `config.APP_VERSION` as "Strategy version" and does not filter on it (`research/strategy_performance_review.py:L111-117, L182-187, L196 @ 605a962` · SOURCE_VERIFIED). Phase 9 calls the run "release `sb-2026.08`" (`docs/phase9_strategy_review_2026-08-17.md:L3-4 @ 5d977f2` · DOCUMENTED_ONLY). Phase 3 never names a version (0 matches) | **NOT_VERIFIED.** Phase 3 states none, Compose sets none at `605a962`, and `.env` was not read | Same blob `7755075` as HIS-14 (SOURCE_VERIFIED); regime from the legacy detector (`technical_analyzer.py:L289-306 @ 605a962`); no regime gate. Trade-type preference neutralised 07-29 (`cdd3450`); learned gates contained 08-17 (`7bf6214`) | Legacy stop as above; whole-position or other exit details: NOT_VERIFIED. The gap-through stop fill was fixed only for the next cohort (`c4a623c`; HIS-35 · DOCUMENTED_ONLY) |
| **Current deployed** (STR-25) | analyzer and signal_engine `rel-ea8ae4f-r2`; telegram and trade_tracker `bb7825f-20261027-r2` (`deploy/DEPLOYED.json:L67, L77-78, L249, L302, L356 @ eba90dd` · DOCUMENTED_ONLY). Runtime `APP_VERSION` `sb-2026.08` (VER-13) vs code default `sb-2026.06` (`shared/config.py:L45 @ ea8ae4f`). Runtime `EVIDENCE_PHASE_ID` `PhaseB-FixedPolicy-20260817` (VER-20). The only boundary record, VB-2026-10-27-01, is a risk-policy boundary (`deploy/VERSION_BOUNDARY.md:L7-11, L24-27 @ eba90dd`) | runtime `15m,4h,1d` (VER-06 · RUNTIME_VERIFIED) | `detect_trade_setup`, blob `61ca698`, regime-gated by `classify_regime` (`analyzer/simple_entry.py @ ea8ae4f` · SOURCE_VERIFIED) | `shared/signal_stop.py`; T1 1R with W3 cap, T2 1.8R, T3 2.2R; per-timeframe expiry; partial 25/50/25 (`shared/triple_barrier.py`, `shared/partial_exits.py @ bb7825f` · SOURCE_VERIFIED) |

Audit VER-06, VER-13 and VER-20 are RUNTIME_VERIFIED rows of [RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md](../../audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md) (L98, L105, L112).

### 3.2 Windows, samples, gross and net, costs, overlap and attribution

| Item | Evaluation window | Sample | Gross vs net definition | Costs | Overlap | Attributable to deployed? |
|---|---|---|---|---|---|---|
| **HIS-01** | 2026-04-09 → 06-21 per `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md:L12 @ 5d977f2` (DOCUMENTED_ONLY); **not stated in `REPORT.md`** | 2,518 closed trades (`REPORT.md:L3 @ 977746f`); 93% in April (L22) · HISTORICAL_REPORTED | Gross = the tracker's per-trade USD result without fees; net = gross − $0.15, i.e. 0.3% of $50 (`research/skill_application/scripts/lib.py:L6, L10, L21-23, L35 @ 977746f` · SOURCE_VERIFIED) | 0.3% round trip on $50, no slippage term (`REPORT.md:L149`) | Contains the HIS-03 subset (2,461 trades to 06-07); lies inside the A58 window (HIS-04, 04-09 → 08-19). No date overlap with HIS-14 or HIS-09 | **No** (G2-01) |
| **HIS-14** | closed 2026-07-06 after 7.35 days (`canary_state.md:L8`), i.e. from about 06-29 (INFERRED) | 178 evidence records; Layer 2 is 88 reversion trades (L8, L14) · HISTORICAL_REPORTED | NOT_VERIFIED: "PF_net" is used without a stated cost or gross definition | ns (not stated) | Inside the HIS-04 window. The canary's own comparator, a "same-week 257-trade live review" (L18), overlaps it. Phase A was written into the file on 2026-09-27 (`970dda9`), after the fact | **No** |
| **HIS-09** (and HIS-10 to HIS-12) | exit time ≥ 2026-07-20 (`LEARNING_CLEAN_START`), run on 2026-08-17 with no explicit upper bound (`strategy_performance_review.py:L186-187 @ 605a962` · SOURCE_VERIFIED) | momentum 162 / reversion 144 (`docs/phase3_entry_hypothesis_review_2026-08-17.md:L15-16`); Phase 6: 307 and momentum 163 (`phase6…:L13, L44`); Phase 9: 303 (`phase9…:L10-11`); Phase 5: 185 OOS (`phase5…:L23`) · HISTORICAL_REPORTED; the mismatches are audit CON-42 | Gross = the tracker's `profit_percent`, so stop-fill slippage sits inside the fill price (INFERRED from `phase4…:L27`). Net = gross − 0.30 percentage points (`strategy_performance_review.py:L46, L182, L196` · SOURCE_VERIFIED) | 0.30% round trip including about 0.1% slippage; +0.1% stop fill; 0.15% spread cap (`docs/phase4_exit_execution_review_2026-08-17.md:L27-31` · DOCUMENTED_ONLY) | Phases 3, 5, 6 and 9 reuse one cohort (HIS-13); inside the HIS-04 window | **No** |
| **Current deployed** | from 2026-08-19 on: FORWARD_HOLDOUT, sealed | count withheld (sealed; not read) | Gross = the tracker result; net = gross − 0.3% × $50 (`trade_tracker/main.py:L947-953 @ bb7825f` · SOURCE_VERIFIED) | 0.30% round trip + 0.1% stop slippage (VER-19 · RUNTIME_VERIFIED) | — | Only sealed evidence could be attributable, and it was not accessed |

## 4. Overlap between samples

The overlaps below are INFERRED from the documented windows; no trade identifiers were read.

| Pair | Overlap | Basis |
|---|---|---|
| HIS-01 vs HIS-03 | HIS-03 (2,461 trades to 06-07) is a subset of the same database | `S4_PHASE1_SCIENTIFIC_COMPARISON.md:L13` |
| HIS-01, HIS-14, HIS-09 vs HIS-04 (A58, 3,401 trades, 04-09 → 08-19) | HIS-04's window contains all three | `S4_PHASE1_SCIENTIFIC_COMPARISON.md:L14`; the A58 session report is not in the repository (HIS-21) |
| HIS-01 vs HIS-14 vs HIS-09 | Disjoint by date: to 06-21; about 06-29 → 07-06; from 07-20 | windows in section 3.2 |
| HIS-09 vs HIS-10, HIS-11, HIS-12 | The same cohort, reused (HIS-13) | all use `LEARNING_CLEAN_START` |
| HIS-14 vs its "257-trade live review" | Same week | `canary_state.md:L18` |
| Any of them vs the current deployed rules | None. All end before `63da7d3` (2026-08-19) | section 2 |

**G2-07 · INFERRED.** Because HIS-01, HIS-14 and HIS-09 do not overlap by date, they are three looks at different periods. They also cover different implementations:
- HIS-01: the legacy score path;
- HIS-14 and HIS-09: the June predicates (blob `7755075`) under different selection policies.

They are not independent replications of one strategy. Pooling them would mix versions, as A58 / HIS-04 already does.

## 5. Can any result be attributed to the deployed strategy?

**G2-08 · INFERRED.** No. Each of the following is SOURCE_VERIFIED unless marked:
1. **Entry predicates differ.** Pre-`63da7d3` momentum has no regime gate, and pre-`63da7d3` reversion uses close < 1.01 × lower band without the close > open and Bollinger-position rules (blob `7755075` vs `61ca698`).
2. **The regime classifier differs.** Legacy EMA-stack / ATR detector vs `classify_regime` (ADX, EMA slope, ATR percentile). A regime-segmented historical cell, such as the Phase 3 "volatile" cell, does not map onto a current regime.
3. **Indicator definitions differ.** At `63da7d3`, StochRSI becomes `STOCH_RSI_WINDOW` with K = 3, the RSI band becomes 0 ≤ RSI < 30, and the `stoch_k ≥ 0.9` branch is removed (HIS-36 · DOCUMENTED_ONLY; the RSI band, the `STOCH_RSI_WINDOW` parameter and the removed branch are SOURCE_VERIFIED in `git show 63da7d3 -- analyzer/technical_analyzer.py shared/config.py`).
4. **Exits differ.** Signal-aware stops and partial exits (`c4a623c`, 08-18) and per-timeframe expiry (`63da7d3`) are newer than every evaluated window. So is the gap-through stop fix (HIS-35).
5. **Selection and tracking changed after `63da7d3`** (G2-06).
6. **The labels do not separate any of this** (G2-02, G2-03). An evidence row tagged `sb-2026.08` or `PhaseB-FixedPolicy-20260817` cannot, by label alone, be assigned to pre- or post-`63da7d3` rules. An attribution would need the commit or image identity at signal time, which no tracked record provides for these windows. NOT_VERIFIED.

Consequence: the economic status of the deployed strategy remains "no accessible evidence" (STR-25). Negative or inconclusive results on earlier implementations are not evidence about it, and they are not evidence about the momentum or reversion families as a whole.

## 6. Findings by evidence class

### SOURCE_VERIFIED
- **G2-05.** The STR-25 inputs:
  - `63da7d3` is dated 2026-08-19;
  - `freeze_git_sha` = `63da7d3` and `freeze_git_dirty` = true (`research/governance/research_freeze.json:L6-7 @ eba90dd`; the file was added at `b1c804d` on 2026-09-27);
  - ancestry runs `63da7d3` → `ea8ae4f` → `bb7825f` → `eba90dd`;
  - the entry and exit modules are byte-identical from `63da7d3` to the deployed commits.
- **G2-06.** Selection (`signal_logic.py`) and tracking (`trade_tracker/main.py`) changed materially between `63da7d3` and the deployed commits.
- **G2-09.** The entry-rule timeline (section 2):
  - `simple_entry.py` was introduced on 2026-06-25 (`d922cfc`);
  - its predicates are unchanged (blob `7755075`) until `63da7d3`;
  - `signal_stop.py` and `partial_exits.py` were added at `c4a623c` (2026-08-18);
  - per-timeframe expiry was added at `63da7d3`.
- **G2-10.** The Phase 3 review defines gross as the tracker's `profit_percent` and net as gross − `FEE_ROUNDTRIP_PCT`, with no version filter. HIS-01 defines net as the gross USD result − $0.15.

### HISTORICAL_REPORTED
- **G2-11.** The reported results (not recomputed here):
  - HIS-01: 2,518 trades, PF 0.735 → 0.598 (`REPORT.md:L3, L11 @ 977746f`);
  - HIS-09: momentum 162 at PF 1.10 and reversion 144 at PF 0.98, both NO-GO (`phase3…:L13-16`);
  - HIS-14: 88 reversion trades, net PF 1.126, p = 0.65, REFUTED (`canary_state.md:L14-19`).

### INFERRED
- **G2-01.** No item is attributable to the deployed strategy.
- **G2-07.** The three samples are non-overlapping but cover different implementations.
- **G2-08.** Labels cannot attribute evidence.
- **G2-12.** The freeze record is retrospective and does not pin a reproducible tree.
  - It was committed on 2026-09-27, recording a freeze dated 2026-08-19.
  - `freeze_git_dirty` = true means the frozen working tree differed from `63da7d3` in some uncommitted way.
  - So "the rules at the freeze" equals `63da7d3` only up to that uncommitted difference. Its content is NOT_VERIFIED.

### CONTRADICTORY
- **G2-02.** `APP_VERSION` is `sb-2026.06` in `shared/config.py:L45` (`7b45a8f` → `eba90dd`) but `sb-2026.08` in Compose and the Dockerfiles. The latter comes from `docker-compose.yml:L21 @ 14fc775` and `analyzer/Dockerfile:L5 @ ea8ae4f`, and is the runtime value (VER-13). `sb-2026.08` spans the `63da7d3` rule change.
- **G2-03.** "Clean cohort `sb-2026.08`" (HIS-09, HIS-46) vs a date-only filter. The label was added on 08-17 with a `legacy` back-fill (`database/migrations/005_learning_governance.sql:L2, L12 @ 14fc775`). Only the last seven trades are described as `sb-2026.08` (`docs/current_handoff_2026-08-17.md:L30`; `docs/loss_streak_remediation_2026-08-17.md:L6`).
- **G2-04.** The HIS-01 label "15m/4h" and its window are not in `REPORT.md`. The timeframe label conflicts with the `15m,1h,4h,1d` default at `977746f`.
- **G2-13.** The canary branch is described as "NOT merged to main" (`canary_state.md:L6`), but `4f84717` is an ancestor of `eba90dd`.
- **G2-14.** The phase label `PhaseB-FixedPolicy-20260817` appears only as an instruction in 08-17 documents (`current_handoff_2026-08-17.md:L89`; `loss_streak_remediation_2026-08-17.md:L25`). It is active at runtime (VER-20) under rules introduced two days later, and no tracked code or Compose file sets it.
- **Also, from the audit (not new):** CON-41 and CON-42 on the cohort's baseline figures and counts (303 / 306 / 307; 162 / 163).

### NOT_VERIFIED

| Item | Blocker |
|---|---|
| Timeframes actually analysed during the HIS-01, HIS-14 and HIS-09 windows | Not stated in the reports; Compose does not set `TIMEFRAMES`; `.env` is not a tracked file and was not read |
| Version or commit actually running in each window | No tracked deployment record for 2026-04 → 08 was identified in this workstream; labels are insufficient (G2-02) |
| Exit rules for HIS-01 before 2026-05-16, and whole-position vs partial handling for HIS-09 / HIS-14 | Tracker code at each date would need line-by-line reading; only module presence was checked |
| HIS-14 cost and gross definition | Not stated in `canary_state.md` |
| Content of the dirty tree at the freeze (G2-12) | Not recorded in any tracked file |
| Any outcome of the current rules | Sealed FORWARD_HOLDOUT (OD-7); not accessed by design |

## 7. Reconciliation with the audit baseline

| Audit finding | Status after G2 |
|---|---|
| HIS-46 (lineage, INFERRED) | Confirmed in order. Two refinements: the "clean cohort `sb-2026.08`" is a date cohort (G2-03); `sb-2026.08` also labels the deployed rules (G2-02). |
| HIS-36 (indicator changes at `63da7d3`; HIS-09 to HIS-12 "appear to predate") | Predating is now SOURCE_VERIFIED: `605a962` precedes `63da7d3`, and blob `7755075` was in force until `63da7d3~1`. |
| HIS-35 (gap-through stop fix `c4a623c`) | `c4a623c` (2026-08-18) is an ancestor of `63da7d3` and later than every evaluated window · SOURCE_VERIFIED. |
| STR-25 (INFERRED) | Inputs SOURCE_VERIFIED (G2-05); conclusion unchanged. |
| CAL-10 / VER-13 | Runtime `sb-2026.08` vs code default `sb-2026.06` is a real divergence, and neither value identifies the rules (G2-02). |
| HIS-01 (HISTORICAL_REPORTED) | Figures as reported. The "15m/4h" label and the window are documented outside the report (G2-04). |
