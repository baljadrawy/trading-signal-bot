# Baseline and Evidence Reconciliation (WP0)

> **Reconciliation 2026-11-01 (WP2).** Documentation only, on branch `feature/wp2-foundation-20261101` from `5cd1a61`. No finding, class or verdict changes. What changed:
> - **Pack state.** Anti-drift item 6 no longer says this file stays uncommitted. The pack is committed and pushed at `5cd1a61` on `docs/wp0-wp1-remediation-design-20261101` (not merged into `main`).
> - **BL-13.** It now states that ERG-01 is committed and pushed at `0729a5f` on `docs/evidence-resolution-20261031`. ERG-01's own README still calls its files uncommitted; that README is stale, and the verdict is unaffected.
> - **BL-14.** It now names the missing `docs/` prefix in charter §9 as a charter path issue. The charter is not edited (`CH:L69`).
> - **Section 9 (process deviations).** It is a historical snapshot of the WP0 phase and is kept as written.
> - **Line citations.** Line numbers of pack documents in citations refer to the files as committed at `5cd1a61`. They are not renumbered.

> **Status: documentation only (charter §5, WP0).** This file reconciles the current default branch with the 2026-10-31 audit and the ERG-01 package. It is not a new audit. Everything here was read from local git objects with `git log`, `git diff`, `git show`, `git merge-base` and `grep`. No backtest, simulation, replay, test, repository script, container, database, log or protected-data read was performed. Nothing here authorizes a merge, deployment, strategy activation or research run. Correcting an implementation defect is never evidence of profitability.

## Document control

| Field | Value |
|---|---|
| Pack | Consolidated Remediation and Design Pack, `docs/design/remediation-design-pack-20261101/` |
| This file | `BASELINE_AND_EVIDENCE.md` (WP0, finding prefix BL-) |
| Companion | [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md) (the deduplicated R1–R9 tracker) |
| Working branch | `docs/wp0-wp1-remediation-design-20261101`, created from `main` |
| Current `main` | `46578aa1ad500456271557be0031d1ca1d826c1b` (46578aa), 2026-11-01 |
| Audit baseline | `5d977f2f851b952f6fd0de026d9222d2ef092f41` (5d977f2), branch `docs/trading-system-audit-20261031`, not merged |
| ERG-01 package | `0729a5fc99ded3c9eb517c4251670dcbb2b2d6e8` (0729a5f), branch `docs/evidence-resolution-20261031`, not merged |
| Common base | `eba90dd` (`main` at audit time) |
| Documented-deployed code | analyzer and signal_engine `ea8ae4f`; telegram and trade_tracker `bb7825f`; collector `72c0bee`; scanner an assembled overlay |
| Governing documents | [charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md), [CLAUDE.md](../../../CLAUDE.md), [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md), [Development-First Policy](../../governance/DEVELOPMENT_FIRST_POLICY.md), [Evidence Ladder parameters](../../strategy/EVIDENCE_LADDER_PARAMETERS.md) |

### Anti-drift statement (charter §7)

1. **Goal alignment.** The work serves active daily opportunity discovery, net-of-cost profitability measurement and safe compounding of realized net profit (`CH:L8`). Discovery is not execution; nothing here forces a trade.
2. **Branch, SHA and runtime identity.** Baseline `main` = 46578aa. Runtime identity confidence is stated per layer in [section 5](#5-runtime-identity-confidence). No runtime claim is made for any moment after the 2026-10-31 observations.
3. **Scope.** WP0 only. R1–R9 are carried in [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md). Exclusion: no generic re-audit (`CH:L16`, `CH:L49`).
4. **Evidence class.** Every finding carries one class from charter §7.4 (`CH:L64`).
5. **Permission class.** Read-only documentation. No change of any other class is made.
6. **Deliverable and acceptance.** This file; acceptance is a clean pack self-check. No owner gate applies to writing it. It was committed and pushed at `5cd1a61` on `docs/wp0-wp1-remediation-design-20261101` (not merged into `main`).
7. **DEVIATION ALERT.** None raised; see [section 8](#8-deviation-alert-check).

### Source aliases

Each alias names a file at a fixed commit. A citation `ALIAS:Lx-Ly` therefore means `path:Lx-Ly @ commit` as listed here. Unmerged material does not exist on this branch and is never linked.

| Alias | Path @ commit |
|---|---|
| CH | `docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md @ 46578aa` |
| OOC | `docs/governance/OWNER_OPERATING_CONTRACT.md @ 46578aa` (last changed `c3bb74c`) |
| DFP | `docs/governance/DEVELOPMENT_FIRST_POLICY.md @ 46578aa` (last changed `37fbaec`) |
| ELP | `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md @ 46578aa` (last changed `1432a90`) |
| AUD | `docs/audits/2026-10-31-trading-system-review/README.md @ 5d977f2` |
| REP | `docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md @ 5d977f2` (defines the audit IDs) |
| ADD | `docs/audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md @ 5d977f2` (VER-01 … VER-31) |
| ERG | `docs/research/evidence-resolution-20261031/README.md @ 0729a5f` |
| G1 | `docs/research/evidence-resolution-20261031/HIS05_COMPARABILITY.md @ 0729a5f` |
| G2 | `docs/research/evidence-resolution-20261031/VERSION_EVIDENCE_LINEAGE.md @ 0729a5f` |
| G3 | `docs/research/evidence-resolution-20261031/DEFECT_IMPACT_ASSESSMENT.md @ 0729a5f` |
| G4 | `docs/research/evidence-resolution-20261031/POWER_AND_HORIZON_FEASIBILITY.md @ 0729a5f` |
| G5 | `docs/research/evidence-resolution-20261031/CANDIDATE_DECISION_MATRIX.md @ 0729a5f` |

Audit IDs (RT-, ARC-, STR-, UNI-, EXE-, RSK-, LRN-, HIS-, ECO-, GOV-, CON-, OQ-) and their classes are those defined in REP. VER-xx IDs are defined in ADD. G1–G5 IDs are defined in the ERG-01 files. They are cited, never re-derived.

## Contents

- [1. Baseline commits and ancestry](#1-baseline-commits-and-ancestry)
- [2. What changed on main since the audit](#2-what-changed-on-main-since-the-audit)
- [3. Branch inventory relevant to R1 to R9](#3-branch-inventory-relevant-to-r1-to-r9)
- [4. Evidence inventory and permitted use](#4-evidence-inventory-and-permitted-use)
- [5. Runtime identity confidence](#5-runtime-identity-confidence)
- [6. What is not re-audited and why](#6-what-is-not-re-audited-and-why)
- [7. Inconsistencies and notes](#7-inconsistencies-and-notes)
- [8. DEVIATION ALERT check](#8-deviation-alert-check)
- [9. Process deviations disclosed](#9-process-deviations-disclosed)

## 1. Baseline commits and ancestry

**BL-01 · SOURCE_VERIFIED.** The local remote-tracking ref `origin/main` resolves to `46578aa`, committed 2026-11-01. It is a single commit (PR #97) whose only parent is `eba90dd` (`git log --format='%H %P' eba90dd..46578aa`). Its message reads "owner-approved master direction and mandatory Claude task alignment".

**BL-02 · SOURCE_VERIFIED.** Both packages branch from `eba90dd` and neither is on `main`:

| Commit | Role | Date | Parent | Ancestor of 46578aa? |
|---|---|---|---|---|
| `eba90dd` | `main` at audit and ERG-01 time (AUD:L16; ERG:L42) | 2026-10-27 | `26eb4e8` | yes |
| `2ebdc2a` | audit package, 7 documents | 2026-10-31 | `eba90dd` | no |
| `5d977f2` | audit addendum (VER-01 … VER-31); 8 documents in total | 2026-10-31 | `2ebdc2a` | no |
| `0729a5f` | ERG-01 package, 7 documents | 2026-10-31 | `5d977f2` | no |
| `46578aa` | current `main`: charter and CLAUDE.md | 2026-11-01 | `eba90dd` | itself |

`git merge-base 5d977f2 46578aa` and `git merge-base 0729a5f 46578aa` both return `eba90dd`. `git merge-base --is-ancestor` is false for `5d977f2` and for `0729a5f` against `46578aa`. The audit commit is an ancestor of the ERG-01 commit. The remote branches `docs/trading-system-audit-20261031` (tip `5d977f2`) and `docs/evidence-resolution-20261031` (tip `0729a5f`) carry them.

**BL-03 · SOURCE_VERIFIED.** The research freeze facts are taken as given by the brief and as verified by ERG-01: the freeze is dated 2026-08-19, its recorded `freeze_git_sha` is `63da7d3` and the tree was dirty (ERG:L49, L53). `research/governance/research_freeze.json` was not opened in this phase. The current momentum and reversion rules are the frozen contract (G2:L21-25).

## 2. What changed on main since the audit

**BL-04 · SOURCE_VERIFIED.** `git diff --stat eba90dd 46578aa` lists exactly two files, 82 insertions and 0 deletions:

| File | Change | Content |
|---|---|---|
| `docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md` | new, 80 lines | the owner-approved charter (`CH:L1-80`) |
| `CLAUDE.md` | +2 lines | the "MASTER DIRECTION — OWNER APPROVED 2026-11-01" paragraph (`CLAUDE.md:L9 @ 46578aa`) and a blank line |

This matches the expectation (charter plus CLAUDE.md only, PR #97).

**BL-05 · SOURCE_VERIFIED.** `git diff --quiet eba90dd 46578aa` over `deploy`, `docker-compose.yml`, `ops`, `shared`, `analyzer`, `signal_engine`, `scanner`, `telegram`, `trade_tracker`, `research`, `database`, `p2_forward` and `tests` reports no difference.
- Consequence (INFERRED from the empty diff): every SOURCE_VERIFIED statement that the audit or ERG-01 made about `main` at `eba90dd` holds at `46578aa` with the same line numbers. Examples are UNI-16 (`signal_engine/main.py:146-155`), HIS-30 (`shared/config.py:124`) and G3-04 (`shared/config.py:92, 107`).
- The audit package (8 files) and the ERG-01 package (7 files) are absent from `main` (`git diff --stat 5d977f2 46578aa` deletes them; BL-02).

**BL-06 · SOURCE_VERIFIED.** The documented-deployed commits differ from `main` as follows:

| Comparison | Result | Consequence |
|---|---|---|
| `bb7825f` → `46578aa` | no change in any active code directory. Only `CLAUDE.md`, `deploy/DEPLOYED.json`, `deploy/VERSION_BOUNDARY.md`, `deploy/paper-observe-bb7825f/*`, `docker-compose.yml` (6 lines) and the charter differ | for telegram and trade_tracker, `main` source equals the documented-deployed source |
| `ea8ae4f` → `46578aa`, active directories | 12 files, +581 / −42: `analyzer/main.py`, `analyzer/technical_analyzer.py`, `shared/config.py` (+32), `shared/economic_halt_policy.py` (new), `shared/risk_epoch.py`, `shared/strategy_math.py`, `shared/t1_cap.py` (new), `shared/telegram_messages.py`, `shared/trade_geometry.py`, `signal_engine/signal_logic.py` (+1), `telegram/main.py`, `trade_tracker/main.py` | for analyzer and signal_engine, `main` is **not** the documented-deployed source; the T1 cap switch exists only on `main` (CON-22, REP:L1475) |

The one-line `signal_logic.py` change is a telemetry argument at L57 (`git diff ea8ae4f 46578aa -- signal_engine/signal_logic.py`). It shifts every later line by one: `_fixed_candidate_key` is L287-293 at `ea8ae4f` and L288-294 at `46578aa`. `shared/config.py` keys also shift: `FEE_ROUNDTRIP_PCT` L90 → L92 (G3:L316), `SIGNAL_INTEGRITY_MODE` L118 → L120, `RISK_CAPITAL_USDT` L129 → L142 and `MAX_OPEN_TRADES` L139 → L159 (`git show <commit>:shared/config.py`). Every runtime-behaviour statement for analyzer and signal_engine must therefore cite `ea8ae4f`, as the register does.

**BL-07 · SOURCE_VERIFIED.** Current SHAs of the governing files, with their last-change commits as seen from `46578aa`:

| File | Last change | Blob |
|---|---|---|
| charter | `46578aa` (2026-11-01) | `436b841c` |
| `CLAUDE.md` | `46578aa` (2026-11-01) | `582a2ff7` |
| Owner Operating Contract | `c3bb74c` (2026-10-26) | `d4412346` |
| Development-First Policy | `37fbaec` (2026-10-26) | `e8b43d85` |
| Evidence Ladder parameters | `1432a90` (2026-10-20) | `5c1f2930` |
| `docs/ops/COMPOSE_OPERATIONS.md` | `23d1d88` (2026-10-20) | `acf182d7` |
| `docs/ops/BACKUP_MODEL_RD.md` | `6f74c06` (2026-10-20) | `8e7bd163` |
| `deploy/DEPLOYED.json`, `deploy/VERSION_BOUNDARY.md` | `eba90dd` (2026-10-27) | `7cb252cf`, `fd952614` |
| `docker-compose.yml` | `26eb4e8` (2026-10-27) | `d1a4b197` |

The governance files the charter names (`CH:L77`) are unchanged since ERG-01 read them (ERG:L46-48).

## 3. Branch inventory relevant to R1 to R9

**BL-08 · SOURCE_VERIFIED.** The clone holds 143 remote heads plus the `origin/HEAD` symbolic ref. The audit counted 141 heads at `eba90dd` (RT-41, REP:L350); the two extra heads are the audit and ERG-01 branches (BL-02). Merge status below is ancestry only (`git merge-base --is-ancestor <tip> <commit>`). Work integrated by squash or cherry-pick would still show as not merged (RT-42, REP:L351). "+N" is `git rev-list --count 46578aa..<tip>`.

| Branch | Tip (date) | In `46578aa` | In `ea8ae4f` / `bb7825f` | Relevant content | R-items |
|---|---|---|---|---|---|
| `fix/t1-cap-policy-flag` | `a4a7561` (10-20) | merged | no / yes | `T1_CAP_POLICY` switch, default `legacy_window_v1` | R2 |
| `feature/a42-signal-quality` | `675f7d1` (10-15) | merged | yes / yes | C1 cost-per-risk and C2 beta cap, both dormant (STR-26, STR-28) | R2, R6, R7 |
| `feature/a43-signal-integrity` | `7fd18fe` (10-15) | merged | yes / yes | signal identity, freshness rule, `bounded_universe` | R1, R3, R6 |
| `feature/a44-integration` | `b5d09bd` (10-16) | merged | yes / yes | `SIGNAL_INTEGRITY_MODE=enforce` wiring, migration 011 | R3 |
| `feature/a45-setup-research` | `db0e6ed` (10-15) | merged | yes / yes | H1–H3 dormant; W3 classified as a defect | R2, R8 |
| `feature/a46-trade-geometry` | `ab3dda4` (10-15) | merged | yes / yes | G1–G3 geometry, dormant | R2 |
| `feature/a47-execution-realism`, `feature/a48-replay-fidelity` | `b20030f`, `cac9367` (10-15) | merged | yes / yes | stop double count documented; research ledger `a48-cost-v1` | R4 |
| `feature/s3-signal-selection`, `s3-shadow-sidecar`, `s3-shadow-evaluation` | `6523f21`, `2e056b2`, `ab17601` (10-16) | merged | yes / yes | dormant selector and shadow tools (STR-30) | R1, R6 |
| `fix/a38-paper-execution-integrity` | `ce40aa2` (10-16) | merged | yes / yes | economic labels, entry-order rows | R4, R6, R7 |
| `research/s4-mechanism-infra`, `research/s4-phase1-comparison` | `4bf9483`, `f6dcae1` (10-20) | merged | no / yes | S4 research code; refuses non-synthetic data | R8 |
| `integration/research-pipeline` | `63da7d3` (08-19) | merged | yes / yes | the production checkout's branch (RT-01) | R5, R9 |
| `feature/design-a-v1` | `ebf8d8a` (10-31) | **not merged** (+5) | no / no | Design A spec and offline package; a benchmark only (`CH:L15`) | R8 |
| `integration/rnd` | `33c7b68` (10-28) | **not merged** (+8) | no / no | shadow opportunity ledger (`1dc9ac5`, "not wired"); collector health and backup changes, default off; A45-G synthetic net evaluation | R6, R7, R8, R9 |
| `safety/disable-auto-tune` | `3d1857d` (06-28) | **not merged** (+1) | no / no | optimizer auto-tune behind `ENABLE_AUTO_TUNE`, default off | R9 |
| `refactor/strategy-math` | `6d6790f` (09-27) | **not merged** (+1) | no / no | analyzer routed through `shared/strategy_math`; same intent as the checkout edit in RT-08, equality NOT_VERIFIED | R5 |
| `lab/l1-account-safeguards`, `lab/l1-parity-guards` | `c42e6ea`, `9bb8363` (10-22) | **not merged** (+6, +8) | no / no | pure per-strategy Paper account with a hash-chained ledger (`lab/account.py`, imported by nothing) | R7, R5 |
| `research/variant-ledger` | `4ac0c42` (10-27) | **not merged** (+10) | no / no | variant and alpha ledger, synthetic only; licence drafts marked "not sent" | R8 |
| `feat/technical-halt-recovery` | `5019663` (10-26) | **not merged** (+4) | no / no | design-and-test-only halt recovery | R9 |
| `integration/paper-observe-activation` | `ea2e9f4` (10-27) | **not merged** (+3) | no / no | includes `d1c24bd` "never admit on a fill price older than a risk-price retry" | R6, R7 |
| `integration/paper-vb-a1` | `d1184c8` (10-28) | **not merged** (+5) | no / no | VERSION_BOUNDARY amendments A1 (`4ba6cad`) and A2 (`d1184c8`) | R5 |
| `remediation/od7-review` | `33347be` (10-29) | **not merged** (+6) | no / no | contains `integration/paper-vb-a1` plus an OD-7 liveness, contamination-disclosure and VERSION_BOUNDARY-redaction commit; **not listed in RT-41** | R5, R9 |
| `review/lce-2` | `fd66219` (10-30) | **not merged** (+10) | no / no | local CI-equivalent runner; **not listed in RT-41** | test infrastructure |
| `fix/a49-nonfinite-economic-label` | `79295f3` (10-15) | **not merged** (+11) | no / no | non-finite P&L not labelled break-even | R4, R7 |
| `docs/p2-g0-w3-holdout-guard-20261002` | `407dcd2` (10-02) | **not merged** (+1) | no / no | W3 holdout guard and contamination disclosure (HIS-40) | R5, R8 |
| `docs/profitability-roadmap-20261024` | `d28322a` (10-26) | **not merged** (+3) | no / no | roadmap revisions | R8 |
| `feature/forward-instrumentation` | `23dea90` (09-27) | **not merged** (+1) | no / no | same change as `2edca45`, which is in `ea8ae4f` (G3:L148): an RT-42 case | R1 |

**BL-09 · SOURCE_VERIFIED.** Commit `54a6369`, which holds the A29–A34 originals (ELP:L19), exists only on the local branch `feature/mi-am4a-stage-b-prep-20261011`. `git branch -r --contains 54a6369` returns nothing. It was not read.

**BL-10 · SOURCE_VERIFIED.** For `integration/paper-vb-a1` and `remediation/od7-review` only commit subjects and file lists were read. Their VERSION_BOUNDARY amendments concern the first admissions under `econ-observe-v1`, which fall after the freeze. Their content may carry protected identifiers (OD-7) and is NOT_VERIFIED here.

## 4. Evidence inventory and permitted use

Use rule: each source is valid evidence **within its stated scope only**. A RUNTIME_VERIFIED value is a point-in-time observation; it does not establish code behaviour (ADD:L73-77). A SOURCE_VERIFIED reading at a commit does not establish what an image contains (RT-16, RT-17; REP:L292-293). A HISTORICAL_REPORTED result is not attributable to the deployed rules (G2-01, G2:L21-25).

| Source | Path @ commit | Scope | Classes inside | Permitted use | Not permitted |
|---|---|---|---|---|---|
| Audit README | AUD | index, scope, classes, key findings, 336 classified findings, OQ-01 … OQ-10 | all | locating findings; scope of the audit | treating it as a profitability certification (AUD:L3-6) |
| Reviewer evidence pack | REP | canonical English definition of every audit ID and class | all | the authoritative source for audit IDs; runtime facts as of 2026-10-31 13:59Z and 14:05Z (REP:L12) | runtime claims after that date; code behaviour inside images |
| Full audit (Arabic) | `docs/audits/2026-10-31-trading-system-review/FULL_SYSTEM_AUDIT_AR.md @ 5d977f2` | same findings, same IDs | all | cross-check only | a second source of truth that overrides REP |
| Topic documents | `RUNTIME_AND_PARITY.md`, `STRATEGIES_INDICATORS_CALIBRATION.md`, `MARKET_CONTEXT_AND_ASSET_SELECTION.md`, `RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md`, all `@ 5d977f2` | narrative for RT/ARC, STR/IND/CAL/EXE/RSK/LRN, UNI/MKT, HIS/ECO/GOV | all | context for register items | — |
| Runtime addendum | ADD | owner-authorized read-only environment, database-configuration and collector-health reads, 2026-10-31 about 19:23Z to 20:30Z (ADD:L8-49) | RUNTIME_VERIFIED (values), SOURCE_VERIFIED (effects), DOCUMENTED_ONLY (image parity) | effective flags VER-01 … VER-20, DB settings VER-21 … VER-25, collector health VER-27 | any trade-level or outcome inference; it read none (ADD:L36-45) |
| ERG-01 index | ERG | five workstreams, consistency check, ordered owner decisions | INFERRED, SOURCE_VERIFIED, NOT_VERIFIED | the **INCONCLUSIVE** verdict and its reasons (ERG:L97, L119-121) | candidate selection, pre-registration or testing (ERG:L5, L205) |
| G1 | G1 | HIS-05 comparability | INFERRED, CONTRADICTORY, NOT_VERIFIED | HIS-05 is MATERIALLY DIFFERENT from current momentum (G1:L15) | transferring HIS-05 as proof of failure of current momentum (`CH:L18`) |
| G2 | G2 | version and evidence lineage | INFERRED, SOURCE_VERIFIED, CONTRADICTORY | no historical result is attributable to the deployed rules (G2:L21) | pooling HIS-01, HIS-09, HIS-14 with any current version |
| G3 | G3 | defect mechanics: W3, alphabetical cut, re-fire, stop double count | MECHANICALLY INFERRED / UNKNOWN on the G3 scale (G3:L12) | mechanisms, affected versions, version-identity rules (G3:L22-30, L277, L287-293) | any realized-impact estimate (none exists, G3:L110, L204) |
| G4 | G4 | power and horizon | INFERRED, ILLUSTRATIVE | 365-day MDE SR 3.48–7.00; horizon binding (G4:L36, L38) | treating the figures as observed variances or Sharpe ratios (ERG:L115) |
| G5 | G5 | B, C and D comparison | INFERRED | B vs C INCONCLUSIVE; D (pause) not dominated (G5:L373-374, L380) | choosing a winner |
| Owner decision brief | `docs/research/evidence-resolution-20261031/FINAL_OWNER_DECISION_BRIEF_AR.md @ 0729a5f` | Arabic synthesis | as ERG | owner reading | new findings |
| Charter | CH | binding direction; R1–R9 and WP0–WP5 | DOCUMENTED_ONLY (policy) | scope, gates, acceptance (`CH:L33-57`) | authorizing protected research, activation, merge or deployment (`CH:L80`) |
| CLAUDE.md | `CLAUDE.md @ 46578aa` | entry point, operational safety, documented pins | DOCUMENTED_ONLY | pins (L42), Class A/B/C (L36-40), learner rule (L41) | the claim at L48 that DB thresholds override `.env` (true only on the legacy path, CON-11) |
| Owner Operating Contract | OOC | PAPER_ONLY, cost standard, A29 HOLD, version boundaries | DOCUMENTED_ONLY | fee 0.10% per side plus spread and slippage (OOC:L10); boundaries (OOC:L36) | — |
| Development-First Policy | DFP | activity classes, rules, OD-DF-1 … 4 | DOCUMENTED_ONLY | geometry, selection and integrity changes are version boundaries (DFP:L63) | treating OD-DF-1/2 as decided (DFP:L109-114) |
| Evidence Ladder parameters | ELP | citation index of A29–A34 parameters | DOCUMENTED_ONLY | parameters and their discrepancy register (ELP:L66-108) | adopting a value because it is written there (ELP:L13) |
| Runbook | `docs/ops/COMPOSE_OPERATIONS.md @ 46578aa` | production command policy | DOCUMENTED_ONLY | Class A/B/C, STOP rule | its image-pin paragraph (L40-48), which is stale (CON-01) |
| Backup model | `docs/ops/BACKUP_MODEL_RD.md @ 46578aa` | read-only backup observations of 2026-10-20; a proposal (OD-DF-4) | DOCUMENTED_ONLY | backup state as of 2026-10-20 (L3-18) | current backup state (not re-observed) |
| Deploy records | `deploy/DEPLOYED.json`, `deploy/VERSION_BOUNDARY.md`, `deploy/paper-observe-bb7825f/IMAGES.md`, `deploy/a561-rel-ea8ae4f/*`, all `@ 46578aa` | recorded images, commits, config hashes, one version boundary | DOCUMENTED_ONLY | documented image identity; boundary rules (VERSION_BOUNDARY.md:L3-5) | proof of current runtime |
| Research records | `docs/a42/` … `docs/a48/`, `docs/s3/`, `docs/strategy/*` on `main` | defect discussions, dormant designs | DOCUMENTED_ONLY, HISTORICAL_REPORTED | mechanisms and designs, as cited by G3 at `eba90dd` (same blobs at `46578aa`, BL-05) | counts whose window is not shown to precede the freeze (G3:L37) |
| Historical Paper audit | `research/skill_application/out/REPORT.md @ 977746f` | HIS-01 | HISTORICAL_REPORTED | context: gross PF 0.735, net PF 0.598 on 2,518 pre-freeze trades (REP:L1003) | attribution to the current strategy (G2-01) |

## 5. Runtime identity confidence

The layers below are kept apart, as the audit does (REP:L37-44). A higher layer never inherits the class of a lower one.

| Layer | What is known | Class | As of | Source |
|---|---|---|---|---|
| Source at the documented commits | rules and code paths of every service | SOURCE_VERIFIED | commit-fixed | REP §2–§8; G3 |
| Documented image identity | analyzer and signal_engine `tsb-a561-*:rel-ea8ae4f-r2`; telegram and trade_tracker `tsb-obs-*:bb7825f-20261027-r2` (observe mode); scanner `tsb-aiohttp-test-scanner:3.14.3-…` overlay; collector `p2f-161-72c0bee`; learner built from the production checkout | DOCUMENTED_ONLY | records of 2026-10-27 | `CLAUDE.md:L42 @ 46578aa`; `docker-compose.yml:L39, L70, L108, L149, L249 @ 46578aa`; `deploy/DEPLOYED.json:L35 @ 46578aa` (`observed_at` 2026-10-27) |
| Container identity, image Id, start time, restart count, config hash | equal to DEPLOYED.json for 8 of 8 entries; unchanged between the 14:05Z sample and the addendum window | RUNTIME_VERIFIED | 2026-10-31 only | RT-35 (REP:L334); RT-23 (REP:L304); ADD:L51-60 |
| Image labels | `revision=bb7825f` only on the two `tsb-obs` images; `revision=unknown` on analyzer, signal_engine and scanner; collector unlabelled; learner `c4cae2b-dirty` | RUNTIME_VERIFIED | 2026-10-31 | RT-15 (REP:L291) |
| Image **content** parity | analyzer 46/46 and signal_engine 56/56 files equal `ea8ae4f`; telegram 50/50 and trade_tracker 51/51 equal `bb7825f`; scanner assembled, 8 of 23 files differ from `main`. Recorded at deploy time only. The paper-observe content check (`drift_check.py check --deep` = MATCH 46, verification FULL) is recorded, but its manifest is kept on the host, not in Git | **DOCUMENTED_ONLY** | deploy records of 2026-10-16 and 2026-10-27 | RT-16, RT-17 (REP:L292-293); `deploy/paper-observe-bb7825f/IMAGES.md:L35-37, L49-57 @ 46578aa`; VER-28 item 1 (ADD:L247-251) |
| Effective environment values | live path on (`LIVE_LEARNING_MODE=true`), integrity mode off, learned gates off, observe mode in telegram and tracker, capacity 2 × $50 of `RISK_CAPITAL_USDT` 500, `FEE_ROUNDTRIP_PCT` 0.3 flat plus `STOP_SLIPPAGE` 0.001, `TIMEFRAMES` 15m,4h,1d, `APP_VERSION` `sb-2026.08` | RUNTIME_VERIFIED | 2026-10-31, about 19:23Z to 20:30Z | VER-01 … VER-20 (ADD:L93-112) |
| Database configuration | 44 frozen indicator weights; one throttled learned-gate cell (gates off); blacklist and whitelist empty; not paused (latest row a valid `manual_resume`) | RUNTIME_VERIFIED | same window | VER-21 … VER-25 (ADD:L118-177) |
| Forward collector | Docker `unhealthy` for about 65 hours; health file fresh with state DEGRADED; 5 latched incidents (3 WARNING, 2 CRITICAL); root cause NOT_VERIFIED | RUNTIME_VERIFIED | same window | VER-27 (ADD:L231-241) |
| Host Compose file | blob `d1a4b197`, equal to `main` | RUNTIME_VERIFIED at 2026-10-31; SOURCE_VERIFIED now for `46578aa` | 2026-10-31 / now | ADD:L62; RT-24 (REP:L305); BL-07 |
| Production checkout | `integration/research-pipeline` at `63da7d3` plus uncommitted edits in 5 files matching no commit; no `deploy/` or `ops/` directory | RUNTIME_VERIFIED | 2026-10-31 | RT-01 … RT-05 (REP:L244-248) |
| Anything after the addendum window | — | **NOT_VERIFIED** | — | this phase made no runtime observation; a recreate could pick up different `.env` values (ADD:L257) |

**BL-11 · INFERRED.** Runtime identity confidence for the register:
- **Which source each service is documented to run** is consistent across every tracked record (CLAUDE.md, Compose pins, DEPLOYED.json, VERSION_BOUNDARY). It is DOCUMENTED_ONLY, and no tracked record contradicts it.
- **That the images contain that source** rests on deploy-time verification records only and was not re-verified by the audit (RT-17). Every statement about runtime *behaviour* in [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md) is therefore SOURCE_VERIFIED at `ea8ae4f` or `bb7825f`, not RUNTIME_VERIFIED.
- **Runtime values** are RUNTIME_VERIFIED for 2026-10-31 only.
- **Main is not the deployed source** for analyzer and signal_engine (BL-06). A claim derived from `main` about the running analyzer is invalid (CON-22, G3-11).

**BL-12 · NOT_VERIFIED (lineage gap).** The deploy record written on 2026-10-27 states that the technical pause of 2026-10-21 was in force and was deliberately not cleared (`deploy/VERSION_BOUNDARY.md:L29-31 @ 46578aa`; `deploy/paper-observe-bb7825f/IMAGES.md:L7 @ 46578aa`). On 2026-10-31 the latest pause row was a valid `manual_resume` (VER-25, ADD:L169-177). No tracked file on `main` records when or by whom that resume happened. The two amendments that may describe the first `econ-observe-v1` admissions exist only on unmerged branches (BL-10). `config_hash_after` and `code_sha_after` are still PENDING on `main` (`deploy/VERSION_BOUNDARY.md:L22-23 @ 46578aa`). This affects lineage (R5), not any current trading decision.

## 6. What is not re-audited and why

The charter forbids a generic re-audit (`CH:L16`, `CH:L49`). The brief forbids runtime, database, log, data and protected access. The following are **accepted as published**, within their stated scope:

| Area | Not repeated | Why it is safe to rely on | Where it is used |
|---|---|---|---|
| Runtime inventory, parity, health | container, image, Compose and health inspection | the code, deploy and Compose paths are unchanged on `main` since the audit (BL-05); the addendum re-checked identity five hours after the audit (ADD:L51) | R5, R9 |
| Effective configuration and DB settings | environment and database reads | VER-01 … VER-25 are RUNTIME_VERIFIED for 2026-10-31; no later observation is claimed | R1–R7 |
| Strategy rules, indicators, regime, macro gate, universe, execution lifecycle, risk | rule-by-rule re-reading | the audit read them at the documented commits; they are unchanged on `main` (BL-05) | R1–R4, R6, R7 |
| Research history and economic evidence (HIS-, ECO-) | re-reading of studies and figures | HISTORICAL_REPORTED by definition; attribution limits fixed by G2 | R8 |
| Defect mechanics (G3) | re-derivation | G3 is the source; this phase re-checked only the code **locations** at `46578aa` and the deployed commits | R1–R4 |
| Power and horizon arithmetic (G4) | recomputation | G4 figures are ILLUSTRATIVE governance arithmetic | R8 |
| Image content | hashing | needs an owner decision (OQ-03; VER-28 item 1) | R5 |
| Protected material | FORWARD_HOLDOUT outcomes, counts and timestamps; `evidence_v2` JSONL including `selection.truncation` records; research JSON outputs; the contamination registry | sealed or out of scope (DFP:L57-58; G3:L196) | R1, R3, R6 |
| Unmerged branch contents | full reading | only subjects and file lists were read where content may be protected (BL-10) | R5 |

**What this phase did re-check** (all SOURCE_VERIFIED): the `main` delta (BL-04, BL-05); deployed-commit deltas (BL-06); branch ancestry (BL-08); governance SHAs (BL-07); and, for the register, the R1–R4, R6 and R7 code sites at `ea8ae4f`, `bb7825f` and `46578aa`. The register adds three code-reading observations that the audit did not state in this form: per-symbol collapse of DB decision reasons (R6), the tracker's wall-clock admission guard (R3) and the unrealized-mark rule for partially exited trades (R7). Each is labelled with its class there.

## 7. Inconsistencies and notes

| ID | Observation | Class |
|---|---|---|
| BL-13 | ERG-01's README says its seven files "sit uncommitted" and that its branch "has no remote-tracking ref" (ERG:L44, L217). ERG-01 is committed and pushed: the files are at `0729a5f` on `docs/evidence-resolution-20261031`, and `origin/docs/evidence-resolution-20261031` points to it. The README text predates the commit and is stale; the verdict is unaffected | CONTRADICTORY |
| BL-14 | Charter path issue: the charter's §9 source anchors write `governance/…` and `strategy/…` without the `docs/` prefix (`CH:L77`). The files are at `docs/governance/` and `docs/strategy/`. The pack cites the full paths; the charter is not edited here, because it is not silently rewritten (`CH:L69`) | SOURCE_VERIFIED |
| BL-15 | RT-41's list of unmerged branches omits `remediation/od7-review` (+6) and `review/lce-2` (+10), both created before the audit (BL-08). RT-41 is therefore incomplete as an inventory; no audit conclusion depends on those branches | SOURCE_VERIFIED |
| BL-16 | The audit read repository documents at `ebf8d8a` (`feature/design-a-v1`, `main` plus 13 Design A files; AUD:L18). Design A citations (STR-39, HIS-16) therefore refer to a branch that is still unmerged (BL-08) | SOURCE_VERIFIED |
| BL-17 | The canonical runbook still states that telegram and trade_tracker run the `tsb-a561` images "verified against the running containers" (`docs/ops/COMPOSE_OPERATIONS.md:L40-42 @ 46578aa`), against CLAUDE.md:L42 and the observed `tsb-obs` images (CON-01). Carried as R9.c | CONTRADICTORY |
| BL-18 | `CLAUDE.md:L48 @ 46578aa` says DB thresholds override `.env`. That holds only for two `optimizer_settings` keys on the dormant legacy path (CON-11; VER-21, ADD:L118-127). It also conflicts in practice with the rule that no production database read happens without owner approval (DFP:L58). Carried as R9.c | CONTRADICTORY |
| BL-19 | The HOLD scope differs between OOC (D1/D2, OOC:L35) and DFP (D1–D5, DFP:L85); the charter follows OOC (`CH:L52`). This is the pre-existing CON-36 (REP:L1489), an open owner question (OQ-06), not a new deviation | CONTRADICTORY |

## 8. DEVIATION ALERT check

The charter was compared with OOC, DFP, ELP and the ERG-01 verdict on objective, cost baseline, version boundaries, the A29 endpoint, HOLDs and authorization.
- No conflict was found that would change the objective, transfer another strategy's result, add unregistered tuning, force trades, mandate BTC-only, treat unrealized gains as cash or bypass A29 (`CH:L67`).
- The charter's research cost baseline (0.40% round trip, stress 0.60%, including 0.10% fee per side, `CH:L25`) is consistent with OOC:L10 and with DFP:L61, which keeps the tracker's 0.30% reported separately.
- CON-36 (BL-19) is pre-existing and is recorded, not resolved.

**No DEVIATION ALERT is raised.**

## 9. Process deviations disclosed

- **Network.** One `git ls-remote --heads origin main` was run by mistake while listing refs, contrary to the brief's no-network rule. It returned the same SHA as the local `origin/main` (`46578aa`). It is not used as evidence; BL-01 rests on local objects only.
- **Scratch copies.** For line lookup, `git show` output of three unmerged documents (REP, G3, G2) was written to session scratch files outside the repository. They were not committed.
- **Self-check.** The mandated self-check imports the module-level regular expressions of `ops/provenance/protected_scan.py`; no other repository code was loaded and no test was run.
- **Data artefacts.** `deploy/DEPLOYED.json` was read only by searching key/value lines for image references, commits and `observed_at`. No research output, JSONL, CSV or evidence file was opened.
