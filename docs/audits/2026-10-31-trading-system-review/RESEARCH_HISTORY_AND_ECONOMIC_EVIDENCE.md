# Research History and Economic Evidence

Part of the 2026-10-31 trading-system review package: see [README.md](README.md). Companion documents: [FULL_SYSTEM_AUDIT_AR.md](FULL_SYSTEM_AUDIT_AR.md) (the complete Arabic audit), [RUNTIME_AND_PARITY.md](RUNTIME_AND_PARITY.md), [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md), [MARKET_CONTEXT_AND_ASSET_SELECTION.md](MARKET_CONTEXT_AND_ASSET_SELECTION.md) and [REVIEWER_EVIDENCE_PACK.md](REVIEWER_EVIDENCE_PACK.md).

This document records what the repository's research history, decision records and committed reports say about the economic performance of the Trading Signal Bot's strategies. It covers:

- which studies were run, and with which costs;
- which hypotheses failed;
- which defects bias the evidence;
- how the cost assumptions differ;
- how contaminated the data are;
- which governance rules limit what may be claimed;
- which records contradict each other.

It reproduces findings with their citations. It does not re-run, recompute or extend any study. It makes no recommendation to change code, configuration, runtime or strategy.

## Document control

| Field | Value |
|---|---|
| Repository | `baljadrawy/trading-signal-bot` (private GitHub repository) |
| Audit date | 2026-10-31. Runtime samples were taken at 13:59Z and 14:05Z. This document relies almost entirely on repository documents and git objects, not on runtime observation. |
| Repository reference | `main` = `eba90ddf4ae60641f80627472098e34650915d28` (eba90dd), at audit time and at publication time |
| Documents read at | `ebf8d8ad2c71b1203565c10b98f22f32e0a81c05` (ebf8d8a, branch `feature/design-a-v1`). This is main plus 13 Design A files, with no difference in active-path directories. |
| Code read at (commits documented as deployed) | analyzer and signal_engine: `ea8ae4f00e80c5c171536293d2df7472fa338c3e` (ea8ae4f)<br>telegram and trade_tracker: `bb7825f4744278095ef76a1d0f3b872e3043358f` (bb7825f)<br>collector: `72c0bee82b44bede5192373d18374724f11c6c3a` (72c0bee)<br>scanner: an assembled image. Its blobs are listed in `deploy/baseline-2026-09-27/deployed_files.json` at 8bfca77; its `shared/config.py` is blob c5c03b5c from 7bf6214. |
| Production checkout | `integration/research-pipeline` at `63da7d31daef2b952c695b256f81cf174b6451a8` (63da7d3), plus uncommitted edits |
| Headline historical artefact | [`research/skill_application/out/REPORT.md`](../../../research/skill_application/out/REPORT.md) at `977746f1ac5dadfd308ba4ca6f8d35ed6856dbc4` (977746f) |
| Status | READ-ONLY, AS-IS audit; documentation-only publication. **This is not a profitability certification.** Neither the audit nor this publication changed application code, configuration, database, container, runtime or Paper Trading state. |

## Evidence classes and tags

| Class | Meaning in this document |
|---|---|
| `RUNTIME_VERIFIED` | Directly observed on the production host during the 2026-10-31 read-only inspection. It is a point-in-time observation and says nothing about code behaviour inside images. |
| `SOURCE_VERIFIED` | Confirmed by reading source code or tracked files at a named commit. It does not prove deployed behaviour, because image content parity is only documented (RT-16, RT-17). |
| `DOCUMENTED_ONLY` | Stated in repository documents, deploy records or the 2026-09-27 non-secret config snapshot. Not independently verified. |
| `HISTORICAL_REPORTED` | A past result, metric or verdict from a study, report or decision record. It was not recomputed in this audit and is never a current operational observation. |
| `INFERRED` | A conclusion reasoned from other evidence; not directly observed. |
| `NOT_VERIFIED` | Could not be verified, either because evidence is missing or because the required access was not authorized (database reads, `.env` values, image filesystems). |
| `CONTRADICTORY` | Two or more sources disagree. |

Each finding carries a tag such as `[HIS-01 · HISTORICAL_REPORTED]`: the finding ID followed by its evidence class. Tags come from the package's reconciled finding register, and later mentions use the bare ID.

IDs with other prefixes are defined elsewhere:
- **RT, ARC, PD** — [RUNTIME_AND_PARITY.md](RUNTIME_AND_PARITY.md).
- **STR, IND, CAL, EXE, RSK, LRN** — [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md).
- **UNI, MKT** — [MARKET_CONTEXT_AND_ASSET_SELECTION.md](MARKET_CONTEXT_AND_ASSET_SELECTION.md).

Every ID also appears in [FULL_SYSTEM_AUDIT_AR.md](FULL_SYSTEM_AUDIT_AR.md) and [REVIEWER_EVIDENCE_PACK.md](REVIEWER_EVIDENCE_PACK.md).

## Protected-data statement

- **Nothing was recomputed.** Figures are reproduced from committed reports, decision records and commit messages, each with its citation.
- **No data files were opened.** No research data file (JSON, JSONL, CSV) and none of the root `*.txt` outputs were opened; they were checked for existence only.
- **No post-freeze data.** No Paper outcome, trade count or timestamp from after the research freeze is reported.
  - The boundary is the 2026-08-19 research freeze (the FORWARD_HOLDOUT boundary recorded in `research/governance/research_freeze.json`).
  - Its exact instant is deliberately not restated.
- **Counts withheld.** Where a source cites a count whose data window was not verified to lie entirely before the freeze, this document writes "count withheld" and points to the cited section instead of the number.
- **No protected material.** No sealed holdout, protected evidence partition, restricted trade-level evidence, database row, log line or credential was accessed, and none is reproduced.

## Contents

1. [Scope and evidence handling](#1-scope-and-evidence-handling)
2. [Historical strategy versions and lineage](#2-historical-strategy-versions-and-lineage)
3. [Headline historical evidence: the pre-freeze live Paper audit](#3-headline-historical-evidence-the-pre-freeze-live-paper-audit)
4. [Research register](#4-research-register)
5. [Verified versus historical claims](#5-verified-versus-historical-claims)
6. [Failed and inconclusive hypotheses](#6-failed-and-inconclusive-hypotheses)
7. [Known defects affecting the evidence](#7-known-defects-affecting-the-evidence)
8. [Paper evidence and walk-forward findings](#8-paper-evidence-and-walk-forward-findings)
9. [Cost assumptions compared](#9-cost-assumptions-compared)
10. [Contamination risks](#10-contamination-risks)
11. [Economic limitations](#11-economic-limitations)
12. [Governance and protected boundaries](#12-governance-and-protected-boundaries)
13. [Limits on profitability claims](#13-limits-on-profitability-claims)
14. [Contradictions](#14-contradictions)
15. [Not verified in this area and open questions](#15-not-verified-in-this-area-and-open-questions)

## 1. Scope and evidence handling

**What was read.**
- Repository documents, committed reports, decision records and commit messages at ebf8d8a, whose tree equals main eba90dd except for the 13 Design A files.
- The governance documents: the [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md), the [Development-First policy](../../governance/DEVELOPMENT_FIRST_POLICY.md) and the [Evidence Ladder parameters](../../strategy/EVIDENCE_LADDER_PARAMETERS.md).
- The first 16 lines of `research/skill_application/out/REPORT.md`, read directly by the history investigation.

Nothing was recomputed.

**Existence-only checks.** These were checked for existence only, not opened:
- JSON, JSONL and CSV research data files;
- the root `*.txt` outputs;
- the contents of the held local commit 54a6369, which holds the A29–A41 packages;
- `docs/ops/PAPER_ECONOMIC_OBSERVATION.md`.

**Skipped post-freeze sections.** The investigation deliberately skipped these sections because they concern post-freeze material (PD-02):
- A42 §A.3 L61-66;
- A42 §B.1 L107;
- A42 §A42-F L283;
- A45 §A45-C W1 L93.

**Citation keys used below.**

| Key | Repository path |
|---|---|
| RP | `research/skill_application/out/REPORT.md` (commit 977746f, 2026-06-23) |
| SH | `docs/claude/strategy-history.md` |
| DL | `DEV_LOG.md` |
| P1 | `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md` |
| RM | `docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md` |
| ELP | `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md` |
| P3 … P9 | `docs/phaseN_*_2026-08-17.md` (N = 3 … 9) |
| A42 … A48 | `docs/a4N/A4N_*.md`, for example `docs/a47/A47_EXECUTION_REALISM.md` and `docs/a48/A48_REPLAY_FIDELITY.md` |
| OOC | `docs/governance/OWNER_OPERATING_CONTRACT.md` |
| DFP | `docs/governance/DEVELOPMENT_FIRST_POLICY.md` |

"L" followed by a number is a line reference in the named document. "ns" means "not stated by the source".

## 2. Historical strategy versions and lineage

[HIS-46 · INFERRED] The version lineage below is a synthesis of STR-20, HIS-09, STR-25, RT-09 and CAL-08. The ordering is inferred from those findings, not taken from a single authoritative record.

| Stage | Period | Identifier or commit | What characterises it | Related IDs |
|---|---|---|---|---|
| Earlier 15m/4h family and legacy score path | 2026-04 to 2026-06 | `legacy_score_v1`; rules before 63da7d3; optimizer and colab weights | Indicator score with `min_score`, `indicator_weights` and multi-timeframe confirmation. The optimizer was active until its Compose disable, which a Compose comment dates to 2026-06-19. | STR-20, HIS-01 (data 2026-04-09 → 06-21), LRN-09, LRN-10 |
| Clean Paper cohort | 2026-07-20 → 2026-08-17 | `sb-2026.08` | Clean Paper sample used by Phases 3, 5, 6 and 9 | HIS-09 to HIS-13 |
| Current setups | from 2026-08-19 | commit 63da7d3 | Regime routing (`shared/regime.py:classify_regime`) plus the `momentum` and `reversion` setups (`analyzer/simple_entry.py`) | STR-25; setup rules STR-07 to STR-09 |
| Release images: analyzer and signal_engine | images created 2026-10-16; containers running since 2026-10-19 | code ea8ae4f; tags `tsb-a561-*:rel-ea8ae4f-r2` | Released analyzer and signal_engine; `T1_CAP_POLICY` is absent from the documented-deployed source (ea8ae4f; RT-17) | RT-09 (runtime), STR-17 |
| Release images: telegram and trade_tracker | images created 2026-10-27 | code bb7825f; tags `tsb-obs-*:bb7825f-20261027-r2` | Economic halts configured in observe mode; version boundary VB-2026-10-27-01 | RT-09, CAL-08 |

[STR-20 · SOURCE_VERIFIED] The earlier 15m/4h momentum and reversion family existed before 63da7d3 and is historical only. Its rules were:
- regime derived from the EMA stack plus ATR > 1.5 × its average;
- reversion entry required close < 1.01 × BB_lower;
- StochRSI used K = 14.

Commit 63da7d3 superseded these rules and changed StochRSI to 14/3/3.

Evidence: code before 63da7d3. Runtime-verified: no. Limitation: historical code, not deployed.

[STR-25 · INFERRED] No pre-freeze economic evidence exists for the exact rules now in the code. Commit 63da7d3, which introduced them, is dated on the research-freeze date (2026-08-19) and precedes the recorded freeze boundary. All their outcome evidence therefore lies in the sealed FORWARD_HOLDOUT.

Limitation: this is inferred from commit dates and the freeze record. No outcomes were read.

[CAL-08 · DOCUMENTED_ONLY] Version boundaries are documented for code and images in three files:
- [`deploy/DEPLOYED.json`](../../../deploy/DEPLOYED.json);
- `deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json` (level L1, content-verified);
- [`deploy/VERSION_BOUNDARY.md`](../../../deploy/VERSION_BOUNDARY.md), which records one boundary, VB-2026-10-27-01 (econ-enforce → econ-observe).

Data have no comparable boundary:
- `optimizer_settings` and `indicator_weights` carry only update times (CAL-09);
- the actual `APP_VERSION` / `strategy_version` emitted at runtime is NOT VERIFIED (CAL-10). The code default is `sb-2026.06`.

[HIS-45 · RUNTIME_VERIFIED] The production checkout cannot reproduce the source documented as deployed:
- all 27 docs/research Markdown files in the checkout exist in main;
- seven of them differ, including the phase3 review, while `docs/claude/strategy-history.md` is identical;
- the checkout lacks commits ea8ae4f, bb7825f and 54a6369.

Evidence: host git state, observed 2026-10-31 (Class A, read-only). Limitation: document parity rests on file comparison only.

## 3. Headline historical evidence: the pre-freeze live Paper audit

[HIS-01 · HISTORICAL_REPORTED] The only large, fully tracked real-data evaluation is the live Paper audit in [`research/skill_application/out/REPORT.md`](../../../research/skill_application/out/REPORT.md). It was committed at 977746f on 2026-06-23, before the freeze. It evaluated the 15m/4h indicator-score strategy (pre-freeze strategy versions) and found no edge.

| Item | Reported value | Citation |
|---|---|---|
| Closed Paper trades | 2,518 | RP L1-3 |
| Period | 2026-04-09 → 2026-06-21, with 93% of trades in April | RP; P1 §1 L12 ("pre-freeze strategy versions") |
| Strategy | 15m/4h indicator-score strategy (pre-freeze versions) | RP §1 |
| Cost model | 0.3% round trip on $50 notional, with no slippage term | RP L149 |
| Profit factor, gross → net | 0.735 → 0.598 | RP §1 L11 ("PF_gross = 0.735") |
| Expectancy per trade, gross → net | −$0.2147 → −$0.3647 (also cited rounded as −$0.215 → −$0.365) | RP §1 L11 |
| Maximum drawdown | −$940 | RP L81 |
| Purged walk-forward AUC | 0.469 / 0.458 | RP §1-3 |
| Permutation test | p = 1.0 | RP §1-3 |
| Filters surviving FDR | 0 of 35 | RP §1-3 |
| Stoch gate and COMBO filter | both fail out of sample | RP §1-3 |
| Data partition | discovery partition, contaminated | `docs/research_temporal_governance.md` §Partitions |
| Verdict | NO EDGE | RP |

**Evidence.** The report, its JSON outputs and its scripts are tracked in Git at 977746f. The history investigation read RP lines 1-16 directly; the other cited RP lines (L62, L64, L81, L128, L149) are reproduced as cited. Runtime-verified: no.

**Limitations.**
- The figures were not recomputed.
- The data are the contaminated discovery partition.
- Several pre-freeze strategy versions are mixed.
- The cost model has no slippage term.
- The study describes an earlier strategy, not the current rules (STR-25).

[HIS-02 · DOCUMENTED_ONLY] The [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md) §4 (L32) states: "The earlier gross PF 0.735 on 2,518 Paper trades is historical review evidence, not a current profitability claim." `docs/claude/strategy-history.md` L12 restates it.

Evidence: governance document at eba90dd. Documentation only.

## 4. Research register

The table lists the studies and tracks in the history investigation's register; further directions are in section 6 (HIS-22 to HIS-24), and the repository records 40+ studies overall (HIS-37).
- "ns" means not stated by the source; "RT" in the costs column means round trip.
- No study reports turnover (HIS-19).
- HIS-01 is detailed in section 3; HIS-13 (sample reuse) is discussed in section 8.
- The "Gross → net" column reproduces each source's figures as reported.

| ID · class | Study · citation | Costs | Data · contamination | Gross → net (as reported) | Walk-forward / OOS | n | Verdict |
|---|---|---|---|---|---|---|---|
| HIS-01 (section 3) | Live Paper audit, 15m/4h score strategy · RP §1-3 | 0.3% RT | 2026-04-09 → 06-21; discovery partition, contaminated | PF 0.735 → 0.598; E −$0.215 → −$0.365; max DD −$940 | purged WF AUC 0.469 / 0.458; permutation p = 1.0; 0/35 filters survive FDR | 2,518 | NO EDGE |
| [HIS-03 · HISTORICAL_REPORTED] | Per-indicator subset · P1 L13 | ns | to 2026-06-07; overlaps HIS-01 | gross PF 0.734; AUC ≈ 0.50 | — | 2,461 | negative (see CON-37 on the cited figures) |
| [HIS-04 · HISTORICAL_REPORTED] | A58 pre-freeze H0 · P1 L14 | ns | 2026-04-09 → 08-19; mixed versions | PF 0.729 → 0.593; day-clustered t = −2.69 | — | 3,401 | negative; the session report is not in the repository |
| [HIS-05 · HISTORICAL_REPORTED] | 9-year target/exit arms · SH L13; P1 L15 | ns | 595 coins, 2017–2026, including delisted coins; research-exposed | every arm × year gross-negative | — | about 110k | "entry is the flaw" |
| [HIS-06 · HISTORICAL_REPORTED] | Daily ML: XGBoost on TA + Ichimoku + ICT features · SH L14; P1 L17 | ns | ns | edge only in coins under $1M; 6 months produced 99% of the net; −1.09%/yr | ns | ns | NO-GO |
| [HIS-07 · HISTORICAL_REPORTED] | Cross-sectional momentum, long/short, weekly · P1 L16 | ns | 250 coins, 2023–2025; post-hoc grid | OOS-2025 Sharpe 1.6; 94% of PnL from the short leg, which is not executable on Spot | 1 year | ns | exploratory |
| [HIS-08 · HISTORICAL_REPORTED] | EMA/round-number filter · `research/entry_filter_causal_test_2026_05_20.md` L2, L55-67 | 0.3% | 37 symbols, Feb–May 2026 | net difference +1.06%, p = 0.018 | split halves p = 0.894 / 0.009 | 4,120 | NOT_PREDICTIVE |
| [HIS-09 · HISTORICAL_REPORTED] | Phase 3 entry hypotheses · P3 L10-44 | 0.30% RT including about 0.1% slippage; +0.1% stop slippage; 0.15% spread cap (P4 L27-31) | clean Paper cohort `sb-2026.08`, 2026-07-20 → 08-17; the same sample is reused (HIS-13) | momentum E +0.123% / PF 1.10; reversion −0.016% / PF 0.98; CIs contain 0; a "volatile" cell at +0.862% is post-hoc; raw-price mean reversion 0/135 | none | 162 / 144 | NO-GO |
| [HIS-10 · HISTORICAL_REPORTED] | Phase 5 expanding walk-forward · P5 L5-25 | as HIS-09 | as HIS-09 | OOS E +0.046%, PF 1.05, CI contains 0; learned gates equal the baseline | 5 folds, purge plus 48 h embargo; 2 of 5 positive | 185 | NO-GO |
| [HIS-11 · HISTORICAL_REPORTED] | Phase 6 portfolio · P6 L5-40 | as HIS-09 | 25 exit days | E +0.056%, PF 1.06, MDD 3.56% (cash curve, not mark-to-market); PF 0.88 without the top 5 trades | none | 307 | "real risk 0" |
| [HIS-12 · HISTORICAL_REPORTED] | Phase 9 review · P9 L8-36 | as HIS-09 | as HIS-09 | E +0.362% / PF 1.45 → +0.062% / PF 1.06; drawdown 19.41 / 49.09 pp | walk-forward +0.033%, 2 of 5 folds | 303 | unproven |
| [HIS-14 · HISTORICAL_REPORTED] | Canary Phase A-R2 · `docs/canary_state.md` L8-22 (written 2026-09-27 at 970dda9) | ns | to 2026-07-06; spans two policies | net PF 1.126, p = 0.65; negative without the top 3 trades | none | 88 | REFUTED |
| [HIS-15 · SOURCE_VERIFIED] | S4 mechanisms M1–M5 and hypotheses H1–H3 · `docs/strategy/S4_MECHANISM_COMPARISON.md` §3; P1 §4-6 | fee 0.10%/side; half-spread 0.01% for BTC/ETH and 0.04% for others; slippage 0.05%/side; ×2 stress | planned: 2019–2022 plus 2023-01 → 2026-08-18 | none | — | 0 | NOT TESTED (the code refuses non-synthetic data) |
| [HIS-16 · SOURCE_VERIFIED] | Design A v1.0, BTC weekly SMA200 · `DESIGN_A_SPEC_v1.0.md` §0, §10, §20 and `DESIGN_A_V1_EVIDENCE.md`, both under `docs/strategy/` on `feature/design-a-v1` @ ebf8d8a | 0.20%/side; stress 0.30%/side | synthetic data only | none computed | — | 83 tests | profitability UNKNOWN; outcome classification "NOT DEFINED" (SPEC §17) |
| [HIS-17 · HISTORICAL_REPORTED] | A47/A48 replay calibration · A48 §A48-D/E | cost ledger `a48-cost-v1` | synthetic | tracker parity 27/27; the legacy model is optimistic in 127/127 cells | — | — | READY FOR SCIENTIFIC DESIGN REVIEW (tests tracked) |
| [HIS-18 · HISTORICAL_REPORTED] | Engineering-only work · `docs/s3/S3_SIGNAL_SELECTION.md` §3; `docs/phase2a_p0r_runtime_contract.md` §13-16; `docs/phase16_data_completion.md` | — | synthetic data or infrastructure | S3 selector on 1,000 synthetic sets; P0R replay with metrics suppressed; data certification FAIL across 596 symbols | — | — | none of it is market evidence |

[STR-38 · SOURCE_VERIFIED] The S4 track (HIS-15) is defined in `research/mechanisms` (`s4-mech-v1`).

Mechanisms M1–M5:
- TSMOM long/cash;
- cross-sectional momentum;
- carry, which is not executable on Spot;
- a volatility overlay;
- M5, the current family.

Phase-1 hypotheses:
- H1: 14-day TSMOM over a point-in-time top-20 universe;
- H2: cross-sectional top-5, weekly;
- H3: T1 cap policy, legacy versus independent swing.

The track is RESEARCH-ONLY and NOT TESTED: `simulate.run` refuses to run without a `DatasetPermission` (`research/mechanisms/simulate.py`; `tests/test_s4_mechanisms.py`).

Evidence: code at eba90dd; synthetic tests only. Runtime-verified: no. No market evidence exists (HIS-43).

## 5. Verified versus historical claims

[HIS-20 · SOURCE_VERIFIED] The history investigation separated claims backed by tracked artefacts from historical claims that cannot be reproduced from tracked outputs.

| Backed by tracked artefacts (verified as committed) | Historical claims only |
|---|---|
| HIS-01: RP, its JSON outputs under `research/skill_application/out/` and its scripts are tracked | HIS-03, HIS-04, HIS-05, HIS-07 and HIS-14 |
| HIS-15: the code refuses non-synthetic data (`research/mechanisms/simulate.py`; `tests/test_s4_mechanisms.py`) | Phases 3, 5, 6 and 9 (HIS-09 to HIS-12): the generators `research/{entry_hypothesis,walk_forward,portfolio,strategy_performance}_review.py` are tracked, but their outputs are not |
| HIS-16 and HIS-17: their tests are tracked | HIS-06 and HIS-08: scripts only |
| The A42–A48 verdicts, taken from each document's final section | Legacy results recorded in DEV_LOG |
| `research/governance/research_freeze.json` (the freeze record) is tracked | The A43 defect counts |
| — | The A29–A41 packages, which exist only in the held local commit 54a6369 (ELP §1) |

Evidence: git objects at ebf8d8a (= eba90dd outside the Design A files). Limitation: "tracked" means the artefact exists in Git, not that its numbers were recomputed.

[HIS-19 · NOT_VERIFIED] No study reports turnover. Turnover, which the owner's reporting standard requires (ECO-09), therefore cannot be stated for any historical result.

[HIS-21 · NOT_VERIFIED] Two sources cannot be verified from the repository:
- The A29–A41 packages exist only in the held local commit 54a6369.
- The A58 session report is not committed, so HIS-04 remains a historical claim.

## 6. Failed and inconclusive hypotheses

[HIS-22 · HISTORICAL_REPORTED] Smart Money Concepts (SMC). The evidence is commit messages only:
- 518e286: "Part 35 SMC Advanced V3 — 0/4 features pass FDR";
- 2ad42bd: "0/18 features survive".

The scripts are `analyzer/part35_smc_advanced_v3.py`, `analyzer/backtest_part37_smc_advanced_ohlc.py` and `research/skill_application/scripts/smc_backtest.py`. There is no result document.

[HIS-23 · NOT_VERIFIED] No committed record exists for these studies:
- the LuxAlgo-faithful SMC port (a git grep over the HEAD md/py/sh/txt files finds none);
- the falling-wedge study (no committed file mentions it);
- a volume + RSI multi-timeframe result (`analyzer/backtest_volume_rsi_mtf.py` exists but has no result document);
- a standalone Ichimoku study (Ichimoku appears only as ML features, SH L14).

[HIS-24 · HISTORICAL_REPORTED] The repository records these other failed directions:
- **Pre-freeze audit tests.** Indicator AUC ≈ 0.50, the stoch gate, COMBO, the mean-reversion filter, Kelly sizing, regime exits and ATR exits all failed (RP §2, L128; the artefact is tracked).
- **EMA/round-number filter.** It failed (HIS-08; `research/entry_filter_causal_test_2026_05_20.md` L2).
- **Phases 3–6.** Momentum and reversion entries, raw-price mean reversion, learned gates, regime selection and top-N robustness all failed. The failures are recorded in the P3 decision section, the P5 results section and the P6 concentration-test section.
- **Canary reversion edge.** It was refuted (`docs/canary_state.md` L14-19; HIS-14).
- **9-year target policy.** It failed (SH L13; HIS-05).
- **Aggregate live walk-forward edge.** It was recorded as a FAIL on 2026-06-23 in the header of `research/walk_forward_audit.sh`.
- **Weight tuning.** It is frozen (SH L8). The DEV_LOG claim of a 60% win rate is contradicted (CON-48).
- **Daily ML and cross-sectional momentum.** Daily ML is NO-GO (HIS-06). Cross-sectional momentum depends on an unexecutable short leg (HIS-07).

[STR-40 · DOCUMENTED_ONLY] Research families outside the current code path:
- **Cross-sectional momentum long/short** (`analyzer/MODEL_FROZEN_SPEC.md`). It needs futures and cites an OOS Sharpe of 1.60. According to the S4 documents, 94% of its P&L came from the short leg.
- **Funding carry.** NO-GO.
- **`analyzer/backtest_part*` scripts** (SMC, ICT, Ichimoku and others). Research-only, documented as having no edge.

| Direction | Outcome | Evidence class (ID) |
|---|---|---|
| 15m/4h indicator-score strategy (live Paper) | NO EDGE; gross PF 0.735 | HISTORICAL_REPORTED (HIS-01) |
| Per-indicator predictive power | AUC ≈ 0.50 | HISTORICAL_REPORTED (HIS-03, HIS-24) |
| Target/exit redesign over 9 years | every arm × year gross-negative | HISTORICAL_REPORTED (HIS-05) |
| Daily ML (TA + Ichimoku + ICT) | NO-GO | HISTORICAL_REPORTED (HIS-06) |
| Cross-sectional momentum long/short | exploratory; needs the short leg | HISTORICAL_REPORTED (HIS-07), DOCUMENTED_ONLY (STR-40) |
| EMA/round-number filter | NOT_PREDICTIVE | HISTORICAL_REPORTED (HIS-08) |
| Phase 3–9 entry, gate and portfolio hypotheses | NO-GO / unproven | HISTORICAL_REPORTED (HIS-09 to HIS-12) |
| Canary reversion edge | REFUTED | HISTORICAL_REPORTED (HIS-14) |
| SMC variants | 0/4 and 0/18 features survive | HISTORICAL_REPORTED (HIS-22) |
| LuxAlgo SMC, falling wedge, volume + RSI MTF, standalone Ichimoku | no committed record | NOT_VERIFIED (HIS-23) |
| Funding carry | NO-GO | DOCUMENTED_ONLY (STR-40) |

## 7. Known defects affecting the evidence

These defects matter for one of two reasons: they bias or invalidate parts of the historical evidence, or they remain in the code documented as deployed. Code facts are SOURCE_VERIFIED at the stated commit. Whether any fix is active at runtime is NOT VERIFIED: image content was not hashed (RT-17), and flag-dependent fixes additionally depend on unread `.env` values (RT-47).

| ID · class | Defect | Where described | Fixed? Where | Notes |
|---|---|---|---|---|
| [HIS-25 · SOURCE_VERIFIED] | 4h/1d same-candle re-fire. The 2 h cooldown is shorter than the bar, so one bar can produce several signals and the sample size n is inflated. | A42 §B.3 L123-127; A43 §A.2 L45 (counts withheld) | A44 signal identity plus insert-once (eb68e42, migration 011). It is active only under `SIGNAL_INTEGRITY_MODE=enforce`, whose default is off. A44 §A44-G says "not deployed". | Runtime state NOT VERIFIED; see EXE-17 |
| [HIS-26 · SOURCE_VERIFIED] | Duplicate trades for a small number of setups; superseded emissions | A43 §A.2 L46-47 (count withheld) | Handled only in enforce mode | The counts are historical claims |
| [HIS-27 · SOURCE_VERIFIED] | The cooldown fails open; NaN spread/volume | A43 §A.2 L48-50 | Partially fixed. The NaN-spread fix ddb6bcd (`finite_spread_pct`) is in ea8ae4f, but in off mode a cooldown read error still returns `set()` (`signal_logic.py:432`). | See CON-32 |
| [HIS-28 · SOURCE_VERIFIED] | Alphabetical `LIMIT 200` and lexical tie-breaks (selection bias) | A43 §A.2 L51-52 | NOT fixed (`signal_engine/main.py`, around L153) | Same mechanism as UNI-16 |
| [HIS-29 · DOCUMENTED_ONLY] | A cost/R gate on a fixed $50 notional, and no cost coverage in production | A42 §B.1 L109-113; the S3 selection document §1 row 4 | Not fixed: C1 (≤ 0.25R) is specified only (STR-26), and the S3 cap is disabled | — |
| [HIS-30 · SOURCE_VERIFIED] | W3 T1 self-reference. The T1 cap uses the breakout bar's own high. This is not look-ahead, but T1 can sit below net break-even. | A42 §B.3 L129-131; A45 §A45-C; A46 §A46-C (counts withheld) | NOT fixed in runtime. G1 is dormant, the default is `legacy_window_v1` (`shared/config.py:124` at bb7825f and main), and a4a7561 is not in ea8ae4f. | STR-17, STR-21; see CON-33 |
| [HIS-31 · SOURCE_VERIFIED] | Stop slippage counted twice, so a stop exit costs about 0.4% (conservative) | A42 §B.3 L132; A47 §A47-E | Corrected only in the research ledger `a48-cost-v1` | See CON-17 |
| [HIS-32 · DOCUMENTED_ONLY] | The replay stop fill (at the level, and on gaps) is optimistic. Same-bar stop-first is pessimistic by up to 3.5 pp. The Paper touch fill `observed_price_v0` is optimistic. | A47 §A47-C/F; A48 §A48-A #6-11 | A48 Modes 2/3 (92c0553) are research only; `resting_limit_v1` is inactive; A42–A46 stop-exit numbers must not be reused (RM §A47/A48) | See CON-34 |
| [HIS-33 · SOURCE_VERIFIED] | The tracker booked NaN prices | A48 §Tracker input-safety | Fixed by f3104c2 `usable_price()`, which is contained in the documented-deployed ea8ae4f | Runtime state NOT VERIFIED (RT-17); see CON-31 |
| [HIS-34 · DOCUMENTED_ONLY] | Same-bar T3 checked before the stop; a time-stop mismatch; the entry priced at the close despite a 351.55 s mean delay; closed-candle look-ahead | P4 L10-14; `docs/code_indicator_review_plan.md` L29, L68-73 | Addressed in `shared/triple_barrier.py` (605a962) and `shared/ohlcv.py` | — |
| [HIS-35 · DOCUMENTED_ONLY] | A gap-through stop filled at the stop price | `docs/signal_aware_execution_2026-08-18.md` L43-45 | Fixed for the new cohort only (c4a623c) | The HIS-09 to HIS-14 studies predate the fix |
| [HIS-36 · DOCUMENTED_ONLY] | StochRSI smoothing; RSI < 20 not scored; a silent `ta` fallback | `docs/code_indicator_review_plan.md` L46-49 | Changed at 63da7d3 | The HIS-09 to HIS-12 studies appear to predate the change (inferred from dates) |
| [HIS-37 · DOCUMENTED_ONLY] | Data snooping: 40+ studies on overlapping history; post-hoc cells; a universe filter on the absolute 24h move ≥ 1%; survivorship | A45 §A45-C W12/W14; P3 L30-31; P6 L48, L55; phase16 L16-18 | Not fixed: there is no multiple-testing correction across studies | See section 10 |
| [HIS-38 · SOURCE_VERIFIED] | The walk-forward scripts have no freeze cutoff and use a flat 0.30% cost | `research/walk_forward_audit.sh`; `research/walk_forward_review.py#load_rows` | Open | See CON-35 |
| [HIS-39 · INFERRED] | Consequence of HIS-38: a re-run of those scripts would read the sealed W3 window | — | — | Inference from the code; not exercised |
| [HIS-40 · DOCUMENTED_ONLY] | W3 summary-level exposure: a cron wrote post-freeze summaries until it was disabled on 2026-10-01 | `research/governance/W3_CONTAMINATION_DISCLOSURE.md` on the unmerged branch `docs/p2-g0-w3-holdout-guard-20261002` | The disclosure and its guard are unmerged | See OQ-10 |
| [HIS-41 · DOCUMENTED_ONLY] | Tested code ≠ running image; `git_dirty` | phase2a §2, §5 | Open | See RT-16, RT-17 |

## 8. Paper evidence and walk-forward findings

All Paper evidence reproduced here predates the 2026-08-19 research freeze. Post-freeze Paper outcomes are sealed (GOV-04) and are not reported.

**Pre-freeze live Paper (2026-04-09 → 06-21).** HIS-01 is the only large tracked Paper evaluation. Its results show no predictive signal and no edge:
- gross PF 0.735, losing before fees;
- net PF 0.598;
- purged walk-forward AUC 0.469 / 0.458;
- a permutation p of 1.0.

Two further studies point the same way: the per-indicator subset (HIS-03), and the A58 H0 test over 2026-04-09 → 08-19 (HIS-04, day-clustered t = −2.69).

**Clean cohort `sb-2026.08` (2026-07-20 → 08-17).** Four phase studies used this cohort. All figures are as reported.

| Study | Sample | Reported result | Robustness checks | Verdict |
|---|---|---|---|---|
| Phase 3 (HIS-09) | 162 momentum / 144 reversion trades | momentum E +0.123% / PF 1.10; reversion −0.016% / PF 0.98; CIs contain 0 | the best "volatile" cell (+0.862%) was found post hoc; raw-price mean reversion 0/135 | NO-GO |
| Phase 5 (HIS-10) | 185 trades | OOS E +0.046%, PF 1.05, CI contains 0 | expanding walk-forward, 5 folds with purge and a 48 h embargo, only 2 of 5 positive; learned gates no better than the baseline | NO-GO |
| Phase 6 (HIS-11) | 307 trades, 25 exit days | E +0.056%, PF 1.06; MDD 3.56% on a cash curve, not mark-to-market | PF 0.88 without the top 5 trades | "real risk 0" |
| Phase 9 (HIS-12) | 303 trades | E +0.362% / PF 1.45 → +0.062% / PF 1.06; drawdown 19.41 / 49.09 pp | walk-forward +0.033%, 2 of 5 folds | unproven |

[HIS-13 · INFERRED] Phases 3, 5, 6 and 9 reuse one sample, the 2026-07-20 → 08-17 clean Paper cohort. Their results are therefore not independent confirmations of each other. The documents also disagree on the cohort's trade counts and on its baseline walk-forward figure (CON-41, CON-42).

**Canary (to 2026-07-06).** HIS-14: 88 trades spanning two policies; net PF 1.126 with p = 0.65, negative once the top 3 trades are removed; REFUTED.

**Aggregate walk-forward.** The aggregate live walk-forward edge was recorded as a FAIL on 2026-06-23 (HIS-24). The walk-forward scripts have no freeze cutoff (HIS-38), and a re-run would read the sealed window (HIS-39).

**Execution caveats.**
- These studies predate the gap-through stop fix (HIS-35).
- Phases 3, 5, 6 and 9 also appear to predate the StochRSI/RSI scoring changes of 63da7d3 (HIS-36; inferred from dates).
- Replay stop-exit numbers from A42–A46 must not be reused (HIS-32).
- The Paper fill model is optimistic, and level-3 exchange realism is not established (EXE-20).

**Bottom line.** Every net-positive real-data figure is non-robust (HIS-42):
- Phase 3 momentum and the Phase 5 OOS figure (HIS-09, HIS-10): confidence intervals contain 0;
- Phase 6 (HIS-11): PF 0.88 without its top 5 trades;
- Phase 9 (HIS-12): +0.062% net, walk-forward +0.033%, 2 of 5 folds positive (unproven);
- canary (HIS-14): p = 0.65, negative without its top 3 trades.

HIS-09 to HIS-12 reuse one cohort (HIS-13); the canary is an earlier sample spanning two policies.

None of this evidence concerns the rules now in the code (STR-25).

## 9. Cost assumptions compared

[EXE-13 · SOURCE_VERIFIED] Runtime cost constants in the code documented as deployed:

| Constant | Value | Note |
|---|---|---|
| `FEE_ROUNDTRIP_PCT` (`shared/config.py:92`) | 0.3 | described as 0.1%/side plus about 0.1% slippage |
| `STOP_SLIPPAGE` (`shared/config.py:107`) | 0.001 | — |
| `triple_barrier.ROUNDTRIP_COST_DEFAULT` | 0.003 | — |
| `MIN_ORDER_NOTIONAL_USDT` | 5 | — |
| `MAX_SPREAD_PCT` | 0.15 | used only as a selection filter |

Evidence: code at ea8ae4f / bb7825f. Limitation: the runtime values are NOT VERIFIED, because image content parity is only documented (RT-16, RT-17).

[EXE-14 · SOURCE_VERIFIED] How the runtime applies these costs:
- `profit_percent` and `profit_usdt` are stored gross.
- `shared/fees.py:economic_close` (lines 41-74) charges `cost_usdt` = 50 × 0.3% = $0.15 flat per trade, whatever the legs, so net = gross − 0.15.
- Stop exits are additionally multiplied by 0.999; A47 flags this as double counting.
- The break-even level, the risk snapshots, the learner and the Telegram reports all use 0.3.

[EXE-15 · INFERRED] The effective modelled cost is:
- 0.30% round trip on target, expiry and invalidation exits;
- about 0.40% on stop exits;
- no spread cost, because prices are last trades.

That is below the 0.40% round-trip baseline of the owner-approved Design A cost model (STR-39), except on stops, and always below its 0.60% stress level.

[STR-39 · SOURCE_VERIFIED] Design A v1.0 (`research/design_a` and `docs/strategy/DESIGN_A_SPEC_v1.0.md`) exists only on `feature/design-a-v1` @ ebf8d8a.

| Element | Specification |
|---|---|
| Asset and signal | BTC/USDT goes LONG iff the latest completed Sunday daily close > SMA200 of 200 completed UTC daily closes; equality means FLAT |
| Decision timing | Monday 00:00 UTC plus 30 seconds |
| Execution | filled at the Tuesday daily open; deferrable within 72 h, with owner-approved weekly retries |
| Position | 100% BTC or 100% cash |
| Baseline cost | 0.20%/side (0.40% round trip): fee 0.10% + half-spread 0.05% + slippage 0.05% |
| Stress cost | 0.30%/side (0.60% round trip) |
| Status | RESEARCH-ONLY; 83 synthetic tests; profitability UNKNOWN; evaluation not authorized (owner decisions E1–E8 pending) |

| Cost model | Fee | Spread | Slippage | Total as stated | Stress | Where used | IDs |
|---|---|---|---|---|---|---|---|
| Runtime Paper accounting | 0.3% round trip flat via `FEE_ROUNDTRIP_PCT` (fee plus about 0.1% slippage) | none (last-trade prices) | `STOP_SLIPPAGE` 0.1% extra on stop exits | about 0.30%; about 0.40% on stops | none | tracker, `economic_close`, risk snapshots, Telegram reports | EXE-13, EXE-14, EXE-15, CON-17 |
| Learner target | 0.3% subtracted from profit% | none | none | 0.3% | none | `continuous_learner` (stopped) | LRN-06 |
| Pre-freeze live Paper audit | 0.3% round trip on $50 | none | no slippage term | 0.3% | none | HIS-01 (RP L149) | HIS-01 |
| Phase 3, 5, 6 and 9 studies | 0.30% round trip, including about 0.1% slippage | 0.15% spread cap (a filter) | +0.1% on stops | 0.30% (+0.1% on stops) | none | HIS-09 to HIS-12 (P4 L27-31) | HIS-09 |
| EMA/round-number filter study | 0.3% | — | — | 0.3% | — | HIS-08 | HIS-08 |
| Walk-forward scripts | flat 0.30% | — | — | 0.30% | — | `research/walk_forward_audit.sh`, `research/walk_forward_review.py` | HIS-38, CON-35 |
| A48 research ledger | `a48-cost-v1`, which corrects the stop double count | — | — | per ledger | — | A47/A48 research only | HIS-17, HIS-31 |
| A42 C1 gate (dormant) | evaluated at 20 bps (as specified) | — | — | — | — | specification only | STR-26, HIS-29 |
| S4 mechanism model | 0.10%/side | half-spread 0.01% for BTC/ETH, 0.04% for others | 0.05%/side | components only (no total stated) | ×2 | S4 (not run) | HIS-15 |
| Design A v1.0 model | 0.10%/side | half-spread 0.05% | 0.05%/side | 0.40% (0.20%/side) | 0.60% (0.30%/side) | Design A (synthetic only) | STR-39, HIS-16 |
| Owner standard | 0.10%/side (0.20% round trip) | plus spread | plus slippage and other realistic execution costs | 0.20% in fees, plus execution costs | — | Owner Operating Contract §1 | ECO-09 |

[ECO-09 · DOCUMENTED_ONLY] The owner's cost and reporting standard ([Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md) §1) requires:
- conservative standard spot fees of 0.10% per side (0.20% round trip), independent of account discounts;
- plus spread, slippage and other realistic execution costs;
- gross and net results, turnover, drawdown, sample sizes, regimes, uncertainty and failure cases.

It also rules out any assertion of profitability without credible prospective independent evidence.

[CON-45 · CONTRADICTORY] The half-spread assumptions disagree:
- 0.05% in `DESIGN_A_SPEC_v1.0.md` §2 F22;
- 0.01% for BTC/ETH in P1 §4.

The Design A profitability memo flags the difference in its §2.4. Both Design A documents are under `docs/strategy/` on `feature/design-a-v1`.

Related findings:
- the runtime counters are gross and the runtime cost sits below the research baselines (ECO-03);
- the 15m fee burden (ECO-06) is in section 11;
- the stop-slippage double count is CON-17;
- whether Paper accounting should keep the flat 0.30% is open question OQ-08.

## 10. Contamination risks

| Risk | What the record shows | IDs |
|---|---|---|
| Discovery-partition contamination | HIS-01's data are the contaminated discovery partition (`docs/research_temporal_governance.md` §Partitions) | HIS-01 |
| Sample reuse | Phases 3, 5, 6 and 9 reuse one cohort | HIS-13 |
| Data snooping | 40+ studies on overlapping history; post-hoc cells; a universe filter on the absolute 24h move ≥ 1%; survivorship; no multiple-testing correction | HIS-37 |
| Registry gap | the contamination registry has a gap for 2026-01 → 06 (P1 §4 L69) | HIS-44 |
| Survivorship | not addressed | HIS-44, HIS-37 |
| Walk-forward scripts | no freeze cutoff; a re-run would read the sealed window | HIS-38, HIS-39 |
| Summary-level exposure of the sealed window | a cron wrote post-freeze summaries until 2026-10-01; the disclosure is unmerged | HIS-40 |
| Version mixing | the current rules changed at the freeze; A58 mixes versions; the canary spans two policies | ECO-04, HIS-04, HIS-14 |
| Code/image mismatch | tested code ≠ running image | HIS-41 |
| In-sample fitting | weights and gates were fitted on the same sample | ECO-05 |
| Boundary definition | the W3 boundary is `≥ freeze` in one document and `> freeze` in another | CON-46 |
| Identifier overloading | W3, D1, R2, S4 and Stage B each name more than one thing | CON-47 |

[ECO-04 · INFERRED] Version contamination. The current rules changed at the freeze, so all their evidence is in the sealed holdout. Earlier studies mixed several versions.

[CON-46 · CONTRADICTORY] The W3 boundary is defined two ways:
- `≥ freeze` in `research/p2/SPEC.md` §1, which is unmerged;
- `> freeze` in `research/data_governance/governance.py#partition_for`.

[CON-47 · CONTRADICTORY] Several identifiers are overloaded: W3, D1, R2, S4 and Stage B each name more than one thing. In this package "W3" means either:
- the A45 weakness, i.e. the T1 self-reference (STR-21, HIS-30); or
- the sealed holdout window after the freeze (HIS-39, HIS-40).

Context identifies which. Likewise, the D1/D2 HOLD of the Owner Operating Contract (GOV-02) is distinct from the A43 "D1" re-fire defect (EXE-17).

## 11. Economic limitations

These limitations describe what the system and its evidence can and cannot show economically. Most are inferences drawn from the findings cited in each entry.

[ECO-01 · INFERRED] **Not a capital-allocation system.** The system is a signal generator with a Paper execution tracker, not a portfolio-growth or capital-allocation system. It has:
- no portfolio construction;
- no risk-based sizing;
- no correlation control;
- utilisation of at most 20% of the $500 virtual capital (2 × $50; RSK-06).

[ECO-02 · INFERRED] **Context inputs only veto.** BTC and USDT.D act only as vetoes; ETH and BTC.D are only collected. The value of the gate itself has never been verified. It cannot be replayed, because the CoinGecko data are not point-in-time (STR-12).

[ECO-03 · SOURCE_VERIFIED] **Gross counters, low modelled cost.** The operational counters are gross: risk_management wins/losses and /status (CON-09). The modelled cost is 0.30% flat, about 0.40% on stops, which is below the research cost baselines in section 9.

[ECO-04 · INFERRED] **Version contamination.** See section 10: the current rules changed at the freeze, and earlier studies mixed several versions.

[ECO-05 · DOCUMENTED_ONLY] **Overfitting risk.** Weights and gates were fitted on the same sample, and 40+ studies ran on contaminated history (HIS-37; LRN-08).

[ECO-06 · DOCUMENTED_ONLY] **Fees and turnover.** With a historical gross PF below 1, any cost deepens the loss.
- 15m fees are 0.22–0.43 R per trade. This is the A46-C fee arithmetic, as cited in `docs/strategy/S4_MECHANISM_COMPARISON.md:58` and `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md:18` and `:65`.
- A T1 hit rate of at least 0.81–0.96 would be needed (`S4_PHASE1_SCIENTIFIC_COMPARISON.md:18`).
- The same 15m fee concern appears in `docs/strategy/S5_PWR_1_OWNER_DECISIONS.md:29` (publication re-check search).

The source location of the fee figure was confirmed by a publication-stage read-only check (PD-05).

[ECO-07 · INFERRED] **Trade-level measurement only.** There is no mark-to-market equity curve at runtime. Drawdown figures such as HIS-11's 3.56% come from a cash curve.

[ECO-08 · INFERRED] **No supported net-profitability claim.** No out-of-sample real-data evidence shows net profitability. The current strategy's performance is unknown by governance, because its outcomes lie in the sealed holdout (STR-25, GOV-04).

## 12. Governance and protected boundaries

These rules come from the governance documents on main. They limit what any study, review or claim may do. The audit and this publication operated inside them: read-only inspection, no database reads, no `.env` values, no holdout access.

[GOV-01 · DOCUMENTED_ONLY] **PAPER_ONLY research and development** ([Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md) §1, §3, §5):
- no live-money execution;
- no credentials enabling it;
- no exchange order placement;
- `PAPER_TRADING=true` stays set;
- the continuous learner stays stopped unless separately authorized.

Paper economic-loss policy (OOC §3, approved 2026-10-26):
- economic losses, loss streaks, drawdown or a low profit factor are observations to record and analyse, not automatic reasons to stop simulated collection;
- no resetting of loss counters, no fabricated fills, no changes to prior outcomes and no silent mixing of strategy versions;
- technical and data-integrity safeguards stay fail-closed.

[GOV-02 · DOCUMENTED_ONLY] **A29 Evidence Ladder with D1/D2 HOLD** (OOC §4). The ladder remains in force with D1/D2 HOLD for governed confirmation:
- a prospective horizon of up to 365 days;
- at most 3 simultaneous candidates;
- 20% of forward capacity reserved;
- 5% familywise error control.

ENCOURAGING is non-confirmatory, and no technical shortcut may silently change these decisions.

The [Development-First policy](../../governance/DEVELOPMENT_FIRST_POLICY.md) §5 records the ladder as α = 1/240, final look only, FWER, ≤ 3 candidates and a 20% reserve. It classes the ladder as CONFIRMATORY-ONLY (D3) and states that it is not a development gate.

[GOV-03 · DOCUMENTED_ONLY] **Nothing has passed the evidence ladder.** The [Evidence Ladder parameters](../../strategy/EVIDENCE_LADDER_PARAMETERS.md) state at §4 L155: "None of these conditions can hold today". In addition:
- the A33 validation was never run;
- A34-B is REVISE;
- the MDE is about 16% optimistic (DR-7).

[GOV-04 · DOCUMENTED_ONLY] **Sealed holdout and data protection** ([Development-First policy](../../governance/DEVELOPMENT_FIRST_POLICY.md) §3):
- The FORWARD_HOLDOUT after the 2026-08-19 research freeze stays sealed: no protected outcome, count or timestamp reads (OD-7).
- Unlocking the holdout is a one-way owner decision.
- There is no production database read or write without owner approval.
- No secrets go into Git, logs, pull requests or reports.

[GOV-05 · DOCUMENTED_ONLY] **Production Compose safety** ([COMPOSE_OPERATIONS.md](../../ops/COMPOSE_OPERATIONS.md); CLAUDE.md; OOC §5):
- Class A read-only inspection is always allowed.
- Class B single-service operations (restart, stop, recreate, deploy, rollback, a writing `exec`, running the learner) need explicit owner approval and a gated procedure.
- Class C commands are forbidden in production: bare `up`, `up --build`, any build from the production checkout, `down`, `prune`, and any change touching more than one service.
- The absolute STOP rule applies: anything unexpected means stop and return to the owner.

[GOV-06 · DOCUMENTED_ONLY] **Workflow**: the owner directive effective 2026-10-26, Continuous Development + PR-on-Demand (DFP header; OOC §2; see also [BRANCH_RELEASE_POLICY.md](../../ops/BRANCH_RELEASE_POLICY.md)):
- `main` is canonical. Prefer main and at most one shared, short-lived integration branch.
- Low-risk D0 development may be integrated into main directly, or by fast-forward or merge, without a PR or repeated owner approval. D0 covers docs, tests, synthetic research, tooling and default-off non-operational changes. The conditions are:
  - CI is green;
  - the change is reversible;
  - it does not alter deployed runtime, risk controls, scientific admission, protected data or production configuration.
- These remain separately owner-gated:
  - live service deployments and restarts;
  - database writes;
  - Paper strategy or version changes;
  - `/resume`;
  - protected-holdout access;
  - confirmatory admissions.
- Merging to main never triggers a production deployment.
- Saved, Integrated, Deployed and Validated are reported separately.
- Server parity is never claimed from GitHub alone.

**HOLD and gated research tracks**

| ID · class | Track | Status | Governing documents | Pending |
|---|---|---|---|---|
| [GOV-07 · DOCUMENTED_ONLY] | A34-VS1 | HOLD, never run | RM §Ground rules, §S5; ELP §3 DR-6 | an approved run; OD-5 (S5_PWR_1 §2) |
| [GOV-08 · DOCUMENTED_ONLY] | MI Stage B | HOLD | RM §Ground rules; ELP §1 | Gate 1, held on the local-only branch `feature/mi-am4a-stage-b-prep-20261011` at 54a6369; OD-1 |
| [GOV-09 · DOCUMENTED_ONLY] | B2 | HOLD | RM; ELP §3 DR-13 | how "B2 gate v2" applies is undefined |
| [GOV-10 · DOCUMENTED_ONLY] | P2-D1 | HOLD | `docs/ops/COLLECTOR_NECESSITY_ASSESSMENT.md` §2, §4 | the owner re-opening the protocol |
| [GOV-11 · DOCUMENTED_ONLY] | Paper R2 | HOLD | RM; A42 §Unchanged | its governing document A37 exists only in 54a6369, so its content is NOT VERIFIED |
| [GOV-12 · DOCUMENTED_ONLY] | D1–D5 | HOLD; the scope is contradictory (CON-36) | RM L23; A42; DFP §5; S5_PWR_1 §Scope; OOC §4 | a DatasetPermission; the A18/A19 licence (no licence record in the repository) |
| [GOV-13 · DOCUMENTED_ONLY] | S4 backtests | NOT TESTED | RM §S4; P1 §6; DFP §5 | family choice; a DatasetPermission; OD-DF-1/2; pre-registration |
| [GOV-14 · DOCUMENTED_ONLY] | P2-H1 / GS | HOLD | COLLECTOR_NECESSITY §2; A42 L219 | A22–A27 exist only in 54a6369; the envelope is UNVALIDATED (ELP DR-6) |
| [GOV-15 · DOCUMENTED_ONLY] | A42 C1–C3, A45 H1–H3, A46 G1–G3 | specified, not run | A42 §A42-E; A45 §A45-E/F; A46 §A46-E/F | owner activation |
| [GOV-16 · DOCUMENTED_ONLY] | Design A | NOT AUTHORIZED for evaluation; branch `feature/design-a-v1` unmerged | DESIGN_A_SPEC §0, §19, §21; DESIGN_A_PROFITABILITY_DECISION_MEMO §3, §5 (both on `feature/design-a-v1`) | owner decisions E1–E8; gates G0–G5 |

## 13. Limits on profitability claims

**Statement.** No evidence in the repository or in this audit supports a claim that any strategy of the Trading Signal Bot is net-profitable. This document is not a profitability certification, and nothing in it should be read as one. The rules now in the code have no accessible economic evidence: their outcomes lie in the sealed FORWARD_HOLDOUT (STR-25).

[HIS-42 · INFERRED] No real-data study shows net-positive, out-of-sample-robust performance. Every net-positive real-data figure is non-robust:

| Figure | Weakness |
|---|---|
| Phase 3 momentum and the Phase 5 OOS figure (HIS-09, HIS-10) | confidence intervals contain 0 |
| Phase 6 (HIS-11) | PF falls to 0.88 without its top 5 trades |
| Phase 9 (HIS-12) | +0.062% net, walk-forward +0.033%, 2 of 5 folds positive (unproven) |
| Canary (HIS-14) | p = 0.65; negative without its top 3 trades |

HIS-09 to HIS-12 reuse one cohort (HIS-13); the canary is an earlier sample spanning two policies.

[HIS-43 · DOCUMENTED_ONLY] Neither S4 nor Design A has market evidence (P1 §5; Design A memo §1). Both have synthetic tests only (HIS-15, HIS-16).

[HIS-44 · NOT_VERIFIED] Other gaps:
- A win-rate/payoff pair in A42 §A.3 L77 is itself marked "unverified". Its values are not reproduced here because the section adjoins post-freeze content.
- The contamination registry has a gap for 2026-01 → 06 (P1 §4 L69).
- Survivorship bias is not addressed.

[ECO-08 · INFERRED] A net-profitability claim is unsupported (section 11).

**What the governance records require before any profitability claim:**
- credible prospective independent evidence (Owner Operating Contract §1);
- a governed confirmation under the A29 Evidence Ladder, which is currently on D1/D2 HOLD (GOV-02);
- conditions that, by the ladder's own record, cannot currently be met: "None of these conditions can hold today" (GOV-03);
- every result carries its evidence class (engineering, synthetic, exploratory, prospective, confirmatory), and synthetic or exploratory success is never reported as profitability (DFP §3).

Historical negative results are evidence against the tested implementations, not proof that every alternative must fail (DFP §1, principle 5).

Gross and net results, turnover, drawdown, sample sizes, regimes, uncertainty and failure cases must all be reported (ECO-09). Turnover is reported by no historical study (HIS-19).

## 14. Contradictions

| ID · class | Contradiction | Sources |
|---|---|---|
| [CON-31 · CONTRADICTORY] | A48 §A48-H and RM L220 say the f3104c2 NaN-price fix is "awaiting deployment", but the documented-deployed ea8ae4f contains f3104c2 (RM L8) | A48; RM; git ancestry (HIS-33) |
| [CON-32 · CONTRADICTORY] | Cooldown fail-open: the S3 selection document §1 row 7 says "confirmed", while `tests/test_a43_signal_integrity.py:384` says "fixed"; the off path still returns `set()` (`signal_logic.py:432`) | S3 document; test file; code (HIS-27) |
| [CON-33 · CONTRADICTORY] | W3 severity: A42 labels it "[D/H]", while A45 calls it a "CONFIRMED IMPLEMENTATION DEFECT" | A42; A45 (HIS-30) |
| [CON-34 · CONTRADICTORY] | A47 §A47-F L81 reports "0 implementation defects", while A48 §A48-A items 1 and 5 list defects | A47; A48 (HIS-32) |
| [CON-35 · CONTRADICTORY] | The walk-forward scripts use a flat 0.30% cost with no freeze cutoff, contrary to the `research/mechanisms/costs.py` docstring | scripts; costs.py (HIS-38) |
| [CON-36 · CONTRADICTORY] | HOLD scope: RM L23 and A42 say "D2–D5"; DFP §5 and S5_PWR_1 §Scope say "D1–D5"; the Owner Operating Contract §4 says "D1/D2" | RM; A42; DFP; S5_PWR_1; OOC (GOV-12) |
| [CON-37 · CONTRADICTORY] | P1 L13 cites strategy-history for "0.734 / 2,461", but SH L12 says 0.735 / 2,518 | P1; SH (HIS-03, HIS-01) |
| [CON-38 · CONTRADICTORY] | `docs/lab/REVIEW_PACKAGE_R1_QUANT.md` L16 ("≈0.73 on 2,518 / 3,401") merges the REPORT.md set with the A58 set | review package; RP; P1 (HIS-01, HIS-04) |
| [CON-39 · CONTRADICTORY] | DEV_LOG L24 says COMBO "breaks even OOS"; RP L62 gives −$0.158 | DL; RP |
| [CON-40 · CONTRADICTORY] | DEV_LOG L67-68 raises min_score from 3 to 4, while SH L8 keeps 3.0 | DL; SH (IND-06) |
| [CON-41 · CONTRADICTORY] | The baseline walk-forward figure is +0.017% (P3 L48), +0.046% (P5 L23) or +0.033% (P9 L25) | P3; P5; P9 |
| [CON-42 · CONTRADICTORY] | Trade counts: 307 (P6 L13) vs 303 (P9 L10); momentum n 162 (P3 L15) vs 163 (P6 L44) | P3; P6; P9 |
| [CON-43 · CONTRADICTORY] | phase16/16b say replay is "blocked"; phase2a §13-14 say replay was run and "RESUME PHASE 2A" | phase16; phase2a |
| [CON-44 · CONTRADICTORY] | MDE ≈ 3.5–5.0 (R1 §Context facts) vs ≈ 3.5–7.0 (DFP §7) | R1 §Context facts; DFP §7 |
| [CON-45 · CONTRADICTORY] | Half-spread 0.05% (DESIGN_A_SPEC §2 F22) vs 0.01% for BTC/ETH (P1 §4); the Design A memo flags this in §2.4 | Design A spec and memo; P1 (section 9) |
| [CON-46 · CONTRADICTORY] | W3 boundary: `≥ freeze` (`research/p2/SPEC.md` §1, unmerged) vs `> freeze` (`research/data_governance/governance.py#partition_for`) | SPEC; governance.py (section 10) |
| [CON-47 · CONTRADICTORY] | Overloaded identifiers: W3, D1, R2, S4 and Stage B each name more than one thing | many (section 10) |
| [CON-48 · CONTRADICTORY] | Weight tuning: DEV_LOG L70-72 claims that raising rsi_divergence from 0 to 2 gave a 60% win rate; RP L64 and L128 refute it | DL; RP (HIS-24) |

## 15. Not verified in this area and open questions

**Not verified in this area:**
- HIS-19: turnover is not reported by any study.
- HIS-21: the A29–A41 packages and the A58 session report.
- HIS-23: the LuxAlgo SMC port, the falling-wedge study, a volume + RSI multi-timeframe result and a standalone Ichimoku study.
- HIS-44: the "unverified" win-rate/payoff pair in A42 §A.3; the contamination-registry gap; survivorship.
- GOV-11: the content of A37; GOV-12: the A18/A19 licence record.
- Runtime state of the fixes behind flags: HIS-25 and HIS-26 depend on `SIGNAL_INTEGRITY_MODE` (STR-33, STR-34, RT-47).
- CAL-10: the actual `APP_VERSION` / `strategy_version` at runtime.
- Runtime state of f3104c2 in the running images (HIS-33, RT-17), of G1 / the T1 cap (STR-17) and of `resting_limit_v1` (EXE-08). Level-3 exchange realism is not established (EXE-20).
- Withheld counts: STR-21, HIS-25, HIS-26 and HIS-30 point to their cited sections instead of reproducing the counts.
- The economic performance of the current rules (STR-25, ECO-08): unknown by governance, because the evidence is sealed.

**Open questions for the owner relevant to this area:**
- [OQ-06] Clarify the HOLD scope: D1/D2 or D1–D5? See CON-36.
- [OQ-08] Paper accounting: keep the flat 0.30%, or adopt the 0.40% baseline / 0.60% stress? See section 9.
- [OQ-10] Disclosure and licensing: what is the status of the unmerged W3 disclosure (HIS-40) and of the A18/A19 licence decision record (GOV-12)?

The complete list of open questions is in [REVIEWER_EVIDENCE_PACK.md](REVIEWER_EVIDENCE_PACK.md) and [FULL_SYSTEM_AUDIT_AR.md](FULL_SYSTEM_AUDIT_AR.md).
