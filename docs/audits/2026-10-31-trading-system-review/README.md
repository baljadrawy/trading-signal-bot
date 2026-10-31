# Trading System Review — Audit Package, 2026-10-31

> **Status: documentation of a completed READ-ONLY, AS-IS audit.**
> - The audit changed nothing, and neither did this publication: no application code, configuration, database, server, container or Paper Trading state.
> - This package is **not a profitability certification**. It approves no strategy, and **no evidence in it supports a net-profitability claim**.
> - It records what was observed, what was read in code or documents, and what remains unverified.

## Document control

| Item | Value |
|---|---|
| Package | `docs/audits/2026-10-31-trading-system-review/` |
| Repository | `baljadrawy/trading-signal-bot` (private) |
| Audit date | 2026-10-31 |
| Runtime inspection | 2026-10-31. Read-only samples at 13:59Z and 14:05Z |
| Repository reference (`main`) | `eba90ddf4ae60641f80627472098e34650915d28` (eba90dd), at audit time and at publication time |
| Code read at the commits documented as deployed | analyzer, signal_engine: `ea8ae4f00e80c5c171536293d2df7472fa338c3e`; telegram, trade_tracker: `bb7825f4744278095ef76a1d0f3b872e3043358f`; forward collector: `72c0bee82b44bede5192373d18374724f11c6c3a`; scanner: assembled image (blob list in `deploy/baseline-2026-09-27/deployed_files.json` at `8bfca778b42fa5c29993d5c57bf1674ae755522f`; `shared/config.py` blob c5c03b5c from `7bf6214dee3f62b345c3152eb65d234094921bb5`) |
| Repository documents read at | `ebf8d8ad2c71b1203565c10b98f22f32e0a81c05` (`feature/design-a-v1`: main plus 13 Design A files, no active-path difference) |
| Production checkout observed | `integration/research-pipeline` at `63da7d31daef2b952c695b256f81cf174b6451a8`, plus uncommitted edits |
| Historical audit artefact | [`research/skill_application/out/REPORT.md`](../../../research/skill_application/out/REPORT.md) at `977746f1ac5dadfd308ba4ca6f8d35ed6856dbc4` |
| Publication | Documentation-only commit on branch `docs/trading-system-audit-20261031`, based on `main` eba90dd. No pull request, no merge, no deployment. The push is for review only. |

## Purpose

This package publishes the full findings of the 2026-10-31 read-only audit of the Trading Signal Bot, in a form that independent reviewers can check. The audit covered:

- the live server: containers, images, Compose configuration and health;
- the GitHub repository: code at the commits documented as deployed, deploy records and research documentation;
- the parity between the two.

For each area, every finding states what was actually observed, what was only read in source code or documents, what was inferred, what comes from historical reports, and what could not be verified.

## Scope and limitations

**Covered.** The audit covered these areas:
- the runtime inventory, and the provenance of each deployed image;
- GitHub-to-runtime parity, and which components are active or inactive;
- architecture and data flow;
- scanner and asset selection;
- analyzer indicators;
- the signal-engine gates;
- BTC, ETH, BTC.D and USDT.D;
- entry, exit and trade tracking;
- stops, targets and partial exits;
- sizing and portfolio risk;
- effective calibration and thresholds, and the precedence of DB overrides;
- learning and optimisation;
- historical versions, research findings and failed hypotheses;
- economic limitations;
- governance and protected boundaries;
- unverified assumptions and contradictions.

**Not accessed, by design and governance.** The audit did not touch any of the following:
- the production database;
- `.env` contents or any environment value;
- `docker exec` and image filesystems;
- network fetches;
- Paper outcomes after the 2026-08-19 research freeze, sealed holdouts and protected evidence partitions.

Research data files were checked for existence only. Only Class A read-only Docker and Compose commands were used.

**Consequences:**
- Effective runtime values held in `.env` or the database (thresholds, flags, weights, blacklist, pause state) are **NOT VERIFIED**.
- Code behaviour is **SOURCE_VERIFIED** at the commits documented as deployed. It is not runtime-verified, because image content parity is only documented (`RT-16`, `RT-17`).
- Historical figures are reproduced as reported. They were not recomputed.

**Redactions applied in this package:**
- Host filesystem paths, network details and every credential.
- The exact research-freeze instant.
- Counts whose data window could not be verified to precede the freeze. These are replaced by pointers to the cited section ("count withheld").

Raw logs, environment dumps, database rows and protected research artefacts are not included.

## Evidence classes

| Class | Meaning |
|---|---|
| `RUNTIME_VERIFIED` | Observed directly on the production host during the 2026-10-31 read-only inspection: container and image metadata, Compose services and config hashes, and the git state of the host Compose file and checkout. Point-in-time only; says nothing about code behaviour inside the images. |
| `SOURCE_VERIFIED` | Confirmed by reading source code or tracked files at a named commit. **Not** proof of deployed behaviour. |
| `DOCUMENTED_ONLY` | Stated in repository documents, deploy records or the 2026-09-27 non-secret configuration snapshot; not independently verified at runtime. |
| `HISTORICAL_REPORTED` | A past result, metric or verdict from a study, report or decision record; not recomputed; never a current operational observation. |
| `INFERRED` | A reasoned conclusion from other evidence; not directly observed. |
| `NOT_VERIFIED` | Could not be verified, because evidence is missing or the access needed (database reads, `.env` values, image filesystems) was not authorized. |
| `CONTRADICTORY` | Two or more sources disagree. |

Every finding carries a tag such as `[RT-09 · RUNTIME_VERIFIED]`. The same ID and class are used in every document of the package, so the Arabic audit and the English documents can be cross-checked mechanically.

| Prefix | Area | Detailed in |
|---|---|---|
| PD | Audit scope, method, process deviations | [RUNTIME_AND_PARITY.md](RUNTIME_AND_PARITY.md) |
| RT | Runtime inventory, provenance, parity, health | [RUNTIME_AND_PARITY.md](RUNTIME_AND_PARITY.md) |
| ARC | Architecture and activation status | [RUNTIME_AND_PARITY.md](RUNTIME_AND_PARITY.md) |
| STR | Strategy families and rules | [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md) |
| IND, CAL | Indicators; configuration precedence, calibration provenance, version boundaries | [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md) |
| EXE, RSK | Paper execution lifecycle, costs, risk controls | [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md) |
| LRN | Learning and optimisation | [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md) |
| UNI, MKT | Asset universe and selection; market context | [MARKET_CONTEXT_AND_ASSET_SELECTION.md](MARKET_CONTEXT_AND_ASSET_SELECTION.md) |
| HIS, ECO, GOV | Research history and economic evidence; economic limitations; governance | [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md) |
| CON | Contradictions between sources | each topic document; all of them in the Arabic audit and the pack |
| OQ | Open questions for the owner | the Arabic audit §19 and the pack §15 |

## Package contents

| Document | Language | Content |
|---|---|---|
| [README.md](README.md) | English | This overview: scope, classes, key findings, confidence, validation and publication record |
| [FULL_SYSTEM_AUDIT_AR.md](FULL_SYSTEM_AUDIT_AR.md) | Arabic, with English technical identifiers | The complete, detailed audit: every finding of the six investigations, all 336 classified findings and 10 open questions |
| [RUNTIME_AND_PARITY.md](RUNTIME_AND_PARITY.md) | English | Service and container inventory, deployed versions, source commits, image provenance, activation status, configuration precedence, observed drift, architecture, evidence limitations |
| [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md) | English | Strategy cards with source, version, status, rules, parameters, defaults vs effective values, DB overrides, calibration provenance, validation evidence and weaknesses; indicator matrix; Paper execution; risk; learning |
| [MARKET_CONTEXT_AND_ASSET_SELECTION.md](MARKET_CONTEXT_AND_ASSET_SELECTION.md) | English | Universe and scanner selection, BTC/ETH roles, BTC.D/USDT.D calculations, data sources and refresh, regime, decision gates, ranking, data-quality limits, collected-but-unused inputs |
| [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md) | English | Historical versions, study register, Paper and walk-forward evidence, cost assumptions, failed hypotheses, defects, contamination risks, A29 Evidence Ladder and D1/D2 HOLD, limits on profitability claims |
| [REVIEWER_EVIDENCE_PACK.md](REVIEWER_EVIDENCE_PACK.md) | English | Self-contained reviewer pack in 15 sections covering every finding ID, with key questions for independent review |

## Key findings

1. [RT-10 · RUNTIME_VERIFIED] **Runtime.** analyzer, scanner, signal_engine, telegram and trade_tracker are running and healthy, with 0 restarts. The forward collector is running but unhealthy on two reads; the cause is NOT VERIFIED (`RT-45`). `continuous_learner` has been stopped (exited) since 2026-08-17. claude_review, redis and the optimizer have no container (`RT-09`, `RT-43`).
2. [RT-35 · RUNTIME_VERIFIED] **Deploy records match the live containers.** All 8 `DEPLOYED.json` entries match on container ID, image Id, image ref, start time, restart count, state and config hash. Two further checks agree (`RT-23`, `RT-24`):
   - the Compose config hashes equal the deploy records;
   - the host Compose blob equals `main`.
3. [RT-16 · DOCUMENTED_ONLY] **Image content parity is documented only.** The file-level match between running images and their documented commits exists only in deploy records. Image labels name a source commit only for the two tsb-obs images (`RT-15`). The images are local, with no registry digest (`RT-18`). No code behaviour is runtime-verified (`RT-17`).
4. [RT-04 · RUNTIME_VERIFIED] **Production checkout.** It is the stale branch `integration/research-pipeline` at 63da7d3, 267 commits behind `main`. Five files carry uncommitted edits that match no commit (`RT-03`), and there is no `deploy/` or `ops/` directory (`RT-05`). No running service executes that code (`RT-27`, inferred), but the learner would build from it if restarted (`LRN-03`, `CON-19`).
5. [STR-01 · SOURCE_VERIFIED] **Active decision path.** The flag `LIVE_LEARNING_MODE` selects rule-based setups. Its value is `true` only in a 2026-09-27 snapshot (`STR-02`), so the live path is presumed active (`STR-03`) and the runtime value is NOT VERIFIED (`STR-04`). On that path the rules are:
   - long-only momentum breakout (`STR-07`) and RSI/Bollinger reversion (`STR-08`);
   - per-symbol regime routing (`STR-09`);
   - a macro veto (`STR-11`);
   - ranking by execution quality (`STR-13`).

   The rules are hand-set (`STR-23`) and tested for mechanics only (`STR-24`). No accessible economic evidence exists for these exact rules (`STR-25`, inferred).
6. [STR-17 · SOURCE_VERIFIED] **T1 cap.** `T1_CAP_POLICY` is absent from the analyzer source documented as deployed (ea8ae4f). That source still carries the W3 defect: T1 is capped using a window that includes the decision bar (`STR-21`). Image content itself is not verified (`RT-17`).
7. [UNI-19 · INFERRED] **Coverage.** The bot evaluates a restricted, dynamic subset of Binance Spot USDT pairs, not all eligible assets:
   - candidates are truncated alphabetically (`LIMIT 200` after `ORDER BY symbol`, `UNI-16`);
   - documented capacity is 2 open positions of $50 on $500 of virtual capital (`RSK-03`, `RSK-06`).
8. [MKT-17 · SOURCE_VERIFIED] **Market context.**
   - Only the BTC trend (two different definitions, `CON-27`) and USDT.D take part in decisions, as entry vetoes or selection filters.
   - ETH and BTC.D are stored only. BTC/ETH relative strength is not implemented.
   - No context input affects sizing or exits.
   - The macro gate has fail-open holes (`MKT-15`).
9. [EXE-20 · DOCUMENTED_ONLY] **Execution realism.** Fills are simulated on last-trade prices. Exchange realism (level 3) is not established. There is no order-placement code anywhere, so Paper-only is structural (`ARC-11`).
10. [EXE-15 · INFERRED] **Costs.**
    - The modelled cost is 0.30% round trip, flat, deducted from gross P&L; stop exits cost about 0.40% because slippage is counted twice (`CON-17`).
    - This is below the 0.40% / 0.60% research baseline except on stops.
    - Operational counters are gross (`ECO-03`).
11. [LRN-19 · INFERRED] **Learning.**
    - The learner is stopped.
    - Learned gates are off by flag but have no expiry or version filter (`LRN-18`). Re-enabling them would re-apply throttles from before 2026-08-17 indefinitely.
    - Frozen `indicator_weights` are still read on every analysis and marginally affect ordering and truncation (`LRN-16`, `LRN-17`).
12. [CAL-04 · SOURCE_VERIFIED] **Calibration provenance.**
    - Provenance is partial.
    - Calibration datasets and the validation methodology are undocumented (`CAL-05`, `CAL-07`).
    - Data held in the DB has no version lineage (`CAL-09`).
13. [HIS-01 · HISTORICAL_REPORTED] **Historical evidence is negative.**
    - The pre-freeze Paper audit of 2,518 trades found gross PF 0.735 and net PF 0.598, with no edge.
    - Every later net-positive real-data figure is non-robust: its confidence interval contains zero, it collapses without the top trades, or too few walk-forward folds are positive. Four of the five come from one reused cohort (`HIS-42`, `HIS-13`).
    - Nothing has passed the A29 Evidence Ladder (`GOV-03`).
14. [GOV-02 · DOCUMENTED_ONLY] **Governance.** The following constraints remain binding:
    - PAPER_ONLY (`GOV-01`);
    - the A29 Evidence Ladder with D1/D2 HOLD;
    - the sealed FORWARD_HOLDOUT (`GOV-04`);
    - the HOLD tracks (`GOV-07`–`GOV-16`).
15. [CON-11 · CONTRADICTORY] **Contradictions.** 48 are recorded. Examples:
    - "DB overrides `.env`" holds for only two legacy keys;
    - documents describe legacy gates as live (`CON-12`);
    - the runbook's image list is stale (`CON-01`);
    - the HOLD scope is stated in three ways (`CON-36`).

**Not verified (selection).**
- Effective `.env` flags (`RT-47`).
- Database contents, including the blacklist (`CAL-03`, `LRN-20`, `UNI-06`).
- Pause and risk state (`RT-46`).
- Image filesystem content (`RT-17`).
- The collector's unhealthy cause (`RT-45`).

## Overall confidence

| Area | Confidence | Basis |
|---|---|---|
| Container, image, Compose-hash and deploy-record inventory | High (point-in-time) | `RUNTIME_VERIFIED` on 2026-10-31 |
| Code behaviour of the running services | Medium | `SOURCE_VERIFIED` at the documented commits; image content parity `DOCUMENTED_ONLY` |
| Effective runtime configuration and DB-held parameters | Low: NOT VERIFIED | `.env` and database not read (authorization required) |
| Historical economic evidence | Medium, as a faithful record of past reports | `HISTORICAL_REPORTED`; not recomputed; uniformly negative or inconclusive |
| Current strategy performance | Unknown by governance | All outcome evidence for the current rules lies in the sealed holdout |

## Open questions for the owner

| ID | Question | Detail |
|---|---|---|
| [OQ-01] | Narrow database reads | `optimizer_settings`, `indicator_weights`, pause state only |
| [OQ-02] | Redacted `.env` flag allow-list | — |
| [OQ-03] | Image content verification | — |
| [OQ-04] | Investigation of the unhealthy collector | — |
| [OQ-05] | Decision on the stale production checkout | — |
| [OQ-06] | HOLD scope | D1/D2 or D1–D5 |
| [OQ-07] | Universe objective | Is the 2 × $50 capacity intended? |
| [OQ-08] | Paper cost accounting | — |
| [OQ-09] | Effect of frozen weights | — |
| [OQ-10] | Status of the W3 disclosure and of the A18/A19 licence record | — |

Full wording is in [FULL_SYSTEM_AUDIT_AR.md](FULL_SYSTEM_AUDIT_AR.md) §19 and [REVIEWER_EVIDENCE_PACK.md](REVIEWER_EVIDENCE_PACK.md) §15.

## Validation performed for this publication

Validation covered documentation only. Nothing was recomputed, and no runtime, database or `.env` access took place.

- **Reconciliation.** The six investigation reports and the compiled audit were reconciled into one register of 336 classified findings and 10 open questions. Every document uses the same IDs and classes.
- **Publication re-checks.** A few read-only re-checks of git objects were made to resolve inconsistencies between reports or to fill missing evidence. They are listed in `PD-05`.
- **Tags and classes (automated).**
  - Every `[ID · CLASS]` tag in all seven documents matches the register.
  - The Arabic audit and the Reviewer Evidence Pack each carry all 346 IDs.
  - Each topic document carries every ID in its scope.
- **Independent review.** Six fresh reviewers compared the documents with the original investigation reports. Their areas were runtime and parity, strategies and calibration, market context and universe, research history and governance, the reviewer pack, and security and privacy.
  - Corrections made:
    - factual precision;
    - evidence-class wording, so that source code is never presented as running behaviour;
    - omissions and Arabic translation;
    - removal of a detail from which the protected freeze time could be derived.
  - The pack reviewer cross-checked 103 numeric findings against the Arabic audit. All 103 agreed. The evidence classes were identical for all 346 IDs.
- **Arabic–English agreement (automated).** Every technical identifier in the pack also appears in the Arabic audit (528 of 528). Values were compared per finding; the remaining differences are formatting or section numbering only.
- **Source coverage (automated).** 511 technical identifiers from the investigation reports were checked against the package. The 12 that are absent were all excluded deliberately:
  - credential variable names;
  - host and session paths;
  - quoted variable names restated in words.
- **Links.** Every relative link and in-document anchor resolves. There are no external links.
- **Security and privacy.** The following checks found nothing:
  - the repository's blocking-scan patterns, applied strictly without its allow-list exceptions;
  - redaction checks for host paths, IP addresses, personal names, e-mail addresses, database identifiers, connection strings, 64-hex identifiers, invisible direction characters and Arabic-Indic digits.

  `ops/provenance/protected_scan.py` was also run against the publication commit and reported `SCAN CLEAN`. The repository identifier `baljadrawy/trading-signal-bot` is kept, because the package must name its repository.

## Publication record and governance basis

- **Governing documents.** The documentation was published under the owner's 2026-10-31 authorization, following:
  - [OWNER_OPERATING_CONTRACT.md](../../governance/OWNER_OPERATING_CONTRACT.md);
  - [DEVELOPMENT_FIRST_POLICY.md](../../governance/DEVELOPMENT_FIRST_POLICY.md);
  - [BRANCH_RELEASE_POLICY.md](../../ops/BRANCH_RELEASE_POLICY.md).
- **What the push is.** It is a documentation-only (D0) change on a short-lived `docs/*` branch created from `main`. It is for review only.
  - **Saved:** pushed to that branch.
  - **Integrated:** no (not merged to `main`).
  - **Deployed:** not applicable.
  - **Validated:** as documentation, only (see above).
- **What it does not authorize.** It does not authorize a merge, deployment, restart, database access, research run or Paper change.
- **Process deviations of the audit itself** are disclosed in `PD-04`; publication-stage re-checks in `PD-05`.
