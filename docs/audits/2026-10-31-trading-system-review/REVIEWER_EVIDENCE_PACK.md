# Reviewer Evidence Pack — Trading Signal Bot (audit 2026-10-31)

> **Status:** READ-ONLY, AS-IS audit of the live server and the repository, published as documentation only. This pack is **not a profitability certification**. No evidence reviewed supports a claim that any strategy of this system is net-profitable. Neither the audit nor this publication changed application code, configuration, the database, containers, deployments or Paper Trading state.

## Document control

| Field | Value |
|---|---|
| Package | `docs/audits/2026-10-31-trading-system-review/` |
| This document | `REVIEWER_EVIDENCE_PACK.md`, the self-contained English reviewer edition. Sections 1–8 cover objectives, architecture, runtime, rules, market context, universe, calibration and the entry/exit/risk model. Sections 9–15 cover costs, historical evidence, failed directions, limitations, governance, unverified claims and review questions. |
| Repository | `baljadrawy/trading-signal-bot` (private GitHub) |
| Audit and runtime inspection date | 2026-10-31; runtime samples at 13:59Z and 14:05Z (minute precision) |
| main at audit and publication time | `eba90ddf4ae60641f80627472098e34650915d28` (eba90dd) |
| Code read: analyzer, signal_engine | `ea8ae4f00e80c5c171536293d2df7472fa338c3e` (ea8ae4f), the commit documented as deployed |
| Code read: telegram, trade_tracker | `bb7825f4744278095ef76a1d0f3b872e3043358f` (bb7825f), the commit documented as deployed |
| Code read: forward collector | `72c0bee82b44bede5192373d18374724f11c6c3a` (72c0bee) |
| Code read: scanner | Assembled image. Its blobs are listed in `deploy/baseline-2026-09-27/deployed_files.json` at 8bfca77 (`8bfca778b42fa5c29993d5c57bf1674ae755522f`); `shared/config.py` is blob c5c03b5c from 7bf6214 (`7bf6214dee3f62b345c3152eb65d234094921bb5`) |
| Repository documents read at | `ebf8d8ad2c71b1203565c10b98f22f32e0a81c05` (ebf8d8a, `feature/design-a-v1`: main plus 13 Design A files, with no active-path difference) |
| Production checkout | `integration/research-pipeline` at `63da7d31daef2b952c695b256f81cf174b6451a8` (63da7d3), plus uncommitted edits |
| Historical audit artefact | `research/skill_application/out/REPORT.md` at `977746f1ac5dadfd308ba4ca6f8d35ed6856dbc4` (977746f) |
| Other commits cited | a4a7561 (`a4a7561e568e1e3ecd8b769566d59c1d4c9afd6d`, T1_CAP_POLICY); f3104c2 (`f3104c25e5e51ebf174a3ba58ee8642ca63515f3`, NaN-price fix); 59297305 (`59297305f9da51ecdde4cb02740b341bcf832ac5`, the commit A42/A45/A46/A47 analysed); 1bfb5f6 (`1bfb5f680ea42af8d4a5a7947d314f787066dc4b`, the collector commit named in one runbook) |
| Evidence base | Six read-only investigations, reconciled into one finding register: (1) runtime and parity; (2) universe and market context; (3) strategies and Paper execution; (4) indicators, calibration and learning; (5) architecture; (6) research history. Publication-stage read-only re-checks are listed in PD-05. |
| Status | READ-ONLY, AS-IS; documentation-only publication; not a profitability certification. No application, configuration, database, container, deployment or Paper Trading change. |

## Purpose and how to use this pack

This pack is written for an independent reviewer who reads only this file. Every essential fact is stated here: rules, thresholds, versions, runtime status and the evidence class of each claim. The companion documents carry longer narrative and are supplementary only:

- [README.md](README.md): package index and executive overview.
- [FULL_SYSTEM_AUDIT_AR.md](FULL_SYSTEM_AUDIT_AR.md): the complete audit in Arabic, with the same finding IDs and classes.
- Topic documents:
  - [RUNTIME_AND_PARITY.md](RUNTIME_AND_PARITY.md)
  - [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md)
  - [MARKET_CONTEXT_AND_ASSET_SELECTION.md](MARKET_CONTEXT_AND_ASSET_SELECTION.md)
  - [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md)

Three reading rules apply throughout:

1. **Observation is not code, and code is not deployment.**
   - A RUNTIME_VERIFIED claim is a point-in-time observation of container, image or Compose metadata on 2026-10-31.
   - A SOURCE_VERIFIED claim was read in source at a named commit.
   - That the running images contain that source is only DOCUMENTED_ONLY (RT-16), and image contents were not hashed (RT-17). No code behaviour in this pack is runtime-verified.
2. **History is not current operation.** HISTORICAL_REPORTED figures are past study results; they were not recomputed and are not current observations. Results after the 2026-08-19 research freeze are sealed and are not disclosed. The freeze is the FORWARD_HOLDOUT boundary recorded in `research/governance/research_freeze.json`.
3. **Unverified means unverified.** A value marked NOT VERIFIED could not be read. Usually this is because database reads, `.env` values or image filesystems were outside the authorized read-only scope.

## Evidence classes

| Class | Meaning in this pack |
|---|---|
| RUNTIME_VERIFIED | Directly observed on the production host during the 2026-10-31 read-only inspection: container and image metadata, the Compose service list and config hashes, and the git state of the host Compose file and production checkout. Point-in-time; it says nothing about code behaviour inside images. |
| SOURCE_VERIFIED | Confirmed by reading source code or tracked files at a named commit through git objects. Not proof of deployed behaviour, because image content parity is only DOCUMENTED_ONLY (RT-16, RT-17). |
| DOCUMENTED_ONLY | Stated in repository documents, deploy records or the 2026-09-27 non-secret config snapshot; not independently verified at runtime. |
| HISTORICAL_REPORTED | A past result, metric or verdict from a study, report or decision record. Not recomputed in this audit, and never a current operational observation. |
| INFERRED | A reasoned conclusion from other evidence; not directly observed. |
| NOT_VERIFIED | Could not be verified: the evidence is missing, or the access it needs was not authorized (database reads, `.env` values, image filesystems). |
| CONTRADICTORY | Two or more sources disagree. Contradictions are consolidated in part B. |

## Finding tags

Each finding carries a tag such as `[RT-09 · RUNTIME_VERIFIED]`: a stable finding ID followed by its evidence class. Every document in the package uses the same IDs, including the Arabic audit, so any claim can be cross-checked. Later mentions use the bare ID (for example RT-09).

| Prefix | Area | Prefix | Area |
|---|---|---|---|
| PD | scope and method | RSK | risk |
| RT | runtime and parity | LRN | learning and optimisation |
| ARC | architecture | UNI | universe |
| STR | strategies | MKT | market context |
| IND | indicators | HIS | history |
| CAL | configuration and calibration | ECO | economics |
| EXE | execution | GOV | governance |
| CON | contradictions | OQ | open questions |

Finding tables use the columns *tag | finding | source · symbol · commit | limitations*.

## Bottom line

- **Paper-only signal generator.** Five bot services were running and healthy at the inspection: scanner, analyzer, signal_engine, telegram and trade_tracker (RT-10, RT-43). The repository contains no order-placement code (ARC-11).
- **Which decision path runs is unverified.** The path is selected by LIVE_LEARNING_MODE, which is documented as true but was not verified at runtime (STR-01 to STR-04).
- **Strategy on the documented path:**
  - two long-only setups, a momentum breakout and an RSI/Bollinger reversion;
  - candidates are routed by a per-symbol regime classifier;
  - entries are vetoed by a BTC and USDT.D macro gate (STR-07 to STR-11).
- **Execution and cost model.** Execution is simulated on last-trade prices, not exchange fills (EXE-20). The modelled cost is a flat 0.30% round trip, about 0.40% on stop exits. That is below the 0.40% baseline of the owner-approved Design A cost model, except on stops (EXE-15).
- **The W3 T1-cap defect is in the documented-deployed analyzer source.** ea8ae4f hard-codes the legacy cap and, unlike main, has no T1_CAP_POLICY switch (STR-17, STR-21); image content is not verified (RT-17).
- **Evidence is negative or sealed.**
  - The pre-freeze historical Paper evidence is negative: gross PF 0.735 and net PF 0.598 on 2,518 trades (HIS-01, part B).
  - The current rules entered the code at the 2026-08-19 freeze, so all of their outcome evidence is sealed and none is accessible (STR-25).
- **Conclusion.** No evidence supports a net-profitability claim.

## Contents

- **Part A (this part):**
  - [1. Objectives and constraints](#1-objectives-and-constraints)
  - [2. Implemented architecture](#2-implemented-architecture)
  - [3. Active runtime configuration and parity](#3-active-runtime-configuration-and-parity)
  - [4. Strategy families and precise rules](#4-strategy-families-and-precise-rules)
  - [5. Market-context implementation](#5-market-context-implementation)
  - [6. Asset-universe policy](#6-asset-universe-policy)
  - [7. Indicators and calibration, including learning and optimisation](#7-indicators-and-calibration-including-learning-and-optimisation)
  - [8. Entry, exit and risk model](#8-entry-exit-and-risk-model)
- **Part B:**
  - 9. Cost and execution assumptions
  - 10. Historical economic evidence
  - 11. Failed directions
  - 12. Statistical and methodological limitations
  - 13. Governance restrictions
  - 14. Unverified claims and contradictions
  - 15. Key questions for independent review

## 1. Objectives and constraints

### 1.1 Project objective and hard constraints

These facts are restated from the governance documents so that the pack stands alone. Part B (section 13) tags them; this section uses bare IDs.

- **Objective.** The project is research and development, PAPER_ONLY (GOV-01; [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md) §1).
  - The goal is to discover and independently validate an economically robust, net-profitable crypto strategy.
  - Maximising gross signals, apparent backtest returns or procedural activity is not the goal.
- **No live money.** Not allowed: live-money execution, credentials that enable it, and exchange order placement. PAPER_TRADING stays true, and the continuous learner stays stopped unless separately authorized (GOV-01).
- **Paper economic-loss policy (GOV-01; OOC §3, approved 2026-10-26).** Economic losses, loss streaks, drawdown or a low PF are observations to record and analyse, not automatic reasons to stop simulated collection. Loss counters are not reset, fills are not fabricated, prior outcomes are not changed and strategy versions are not silently mixed. Technical and data-integrity safeguards stay fail-closed.
- **Owner cost and reporting standard (ECO-09).**
  - Costs: conservative standard spot fees of 0.10% per side (0.20% round trip), plus spread, slippage and other realistic execution costs.
  - Reporting: gross and net results, turnover, drawdown, sample sizes, regimes, uncertainty and failure cases.
  - No profitability assertion without credible prospective, independent evidence.
- **Scientific governance (GOV-02).** The A29 Evidence Ladder is in force, with D1/D2 HOLD for governed confirmation:
  - a prospective horizon of up to 365 days;
  - at most 3 simultaneous candidates;
  - 20% of forward capacity reserved;
  - 5% familywise error control;
  - ENCOURAGING is non-confirmatory.
  - DFP §5 records the ladder as α = 1/240, final look only, FWER, ≤ 3 candidates and a 20% reserve, classed CONFIRMATORY-ONLY (D3) and not a development gate.

  Nothing has passed the ladder (GOV-03; [EVIDENCE_LADDER_PARAMETERS.md](../../strategy/EVIDENCE_LADDER_PARAMETERS.md) §4).
- **Protected data (GOV-04; [Development-First Policy](../../governance/DEVELOPMENT_FIRST_POLICY.md) §3).**
  - The FORWARD_HOLDOUT after the 2026-08-19 research freeze stays sealed. No protected outcome, count or timestamp is read (OD-7).
  - No production database read or write without owner approval.
  - No secrets in Git, logs, PRs or reports.
- **Production safety (GOV-05; [COMPOSE_OPERATIONS.md](../../ops/COMPOSE_OPERATIONS.md); absolute STOP rule).**
  - Class A read-only inspection is always allowed.
  - Class B single-service operations need explicit owner approval and a gated procedure.
  - Class C commands are forbidden in production.
- **Workflow (GOV-06; owner directive effective 2026-10-26, Continuous Development + PR-on-Demand, recorded in the [Development-First Policy](../../governance/DEVELOPMENT_FIRST_POLICY.md) header and OOC §2; see also [BRANCH_RELEASE_POLICY.md](../../ops/BRANCH_RELEASE_POLICY.md)).**
  - main is canonical; prefer main and at most one shared, short-lived integration branch.
  - Low-risk D0 development (docs, tests, synthetic research, tooling, default-off non-operational changes) may be integrated into main without a PR or repeated owner approval, provided CI is green, the change is reversible and it does not alter deployed runtime, risk controls, scientific admission, protected data or production configuration.
  - Live service deployments and restarts, database writes, Paper strategy or version changes, /resume, protected-holdout access and confirmatory admissions remain separately owner-gated.
  - Merging to main never triggers a production deployment.
  - Saved, Integrated, Deployed and Validated are reported separately.
  - Server parity is never claimed from GitHub alone.

### 1.2 Audit scope, method and process deviations

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [PD-01 · HISTORICAL_REPORTED] | Runtime inspection on 2026-10-31 started 13:59Z; the second health sample was taken at 14:05Z. `docs/ops/COMPOSE_OPERATIONS.md` was read first. Only Class A read-only commands were used: `docker ps`/`docker inspect` with selected fields, `docker image inspect`, Compose `config --hash` and `config --services`, and `ops/compose-safe logs --tail 20` run from a non-production worktree. Log output was machine-filtered to category counts; no log line was viewed or quoted. Ancestry was computed in the audit worktrees' shared git object store. | Investigation record (runtime and parity); compiled audit, scope section | As reported by the investigation agents on 2026-10-31; not re-run during publication. |
| [PD-02 · HISTORICAL_REPORTED] | Not accessed: the production database (no queries), `.env` contents or any environment value, `docker exec`, network fetches, image filesystems, Paper outcomes after 2026-08-19, sealed holdouts and protected evidence partitions. JSON/JSONL/CSV research data and root `*.txt` outputs were checked for existence only. Post-freeze sections were skipped: A42 §A.3 L61-66, §B.1 L107 and §A42-F L283; A45 §A45-C W1 L93. | Investigation records (compiled audit; research history) | Self-reported scope. This is why many effective values below are NOT VERIFIED. |
| [PD-03 · HISTORICAL_REPORTED] | Code was read with `git show` at the commits documented as deployed: analyzer and signal_engine at ea8ae4f; telegram and trade_tracker at bb7825f; collector at 72c0bee; scanner blobs from `deploy/baseline-2026-09-27/deployed_files.json` at 8bfca77, with `shared/config.py` blob c5c03b5c from 7bf6214. Repository documents were read at ebf8d8a (`feature/design-a-v1`). Configured values come from `deploy/baseline-2026-09-27/config/*.nonsecret.json` (2026-09-27). | Investigation records (universe, strategies, indicators, architecture); publication check | One investigation report labels ebf8d8a as "main". Publication check: eba90dd is an ancestor of ebf8d8a, and only the 13 Design A files differ (no active-path difference). |
| [PD-04 · HISTORICAL_REPORTED] | Process deviations disclosed by the investigation agents. All are outside the repository, with no production effect: (1) a temporary file holding `git ls-remote` output was written to the session scratchpad root instead of its audit folder; (2) a sub-agent wrote and ran a static helper script in the session scratchpad (`git show` plus regular expressions, no application import); (3) the `.env` modification time was read (metadata only, never content); (4) audit notes were written in the session scratchpad; (5) a permission rule blocked reading `.env.example`, so its values are cited via `docs/ops/ENV_EXAMPLE_REVIEW_2026-10-18.md`. | Investigation records | Disclosed for transparency; none touched production or the repository. |
| [PD-05 · SOURCE_VERIFIED] | Publication-stage re-checks (read-only git objects, no runtime access) were limited to resolving report inconsistencies or missing evidence: the legacy 1d score rule and the legacy order-book term (`signal_engine/signal_logic.py`); the capacity-multiplier wording (`shared/economic_halt_policy.py:18-20`); the source of the 15m fee-burden figure (`docs/strategy/S4_MECHANISM_COMPARISON.md:58`); path existence on main; full commit SHAs. | Git objects at ea8ae4f, bb7825f and eba90dd | No investigation was repeated. |

## 2. Implemented architecture

Findings in this section are SOURCE_VERIFIED at the commits documented as deployed (ea8ae4f for analyzer and signal_engine, bb7825f for telegram and trade_tracker, the assembled blobs for the scanner, and 72c0bee for the collector) unless their tag says otherwise (ARC-17 INFERRED; ARC-20, ARC-23 DOCUMENTED_ONLY). That the running images contain this code is DOCUMENTED_ONLY (RT-16), and image contents were not hashed (RT-17).

Data flow:
1. Binance REST feeds the **scanner**, which writes `scan_candidates`; the signal_engine's macro gate separately reads Binance 4h bars and CoinGecko `/api/v3/global` (MKT-03, MKT-06, MKT-07).
2. The **analyzer** writes `analysis_results`.
3. The **signal_engine** writes `signals` and an outbox `signal.ready` event in one transaction.
4. **telegram** polls the outbox and writes `signals.telegram_sent` plus a `signal.delivered` event.
5. The **trade_tracker** polls `signals`, writes `active_trades` and then `trade_results`, and records evidence as JSONL.

The forward collector is a separate project: it writes files only and is not on the trading path.

### 2.1 Pipeline, tables and the signal.ready contract

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [ARC-01 · SOURCE_VERIFIED] | Active pipeline: scanner → analyzer → signal_engine → `signal.ready` → telegram → trade_tracker (the CR-2 path described in CLAUDE.md). `signal.ready` is a row in the PostgreSQL `outbox_events` table, polled by telegram. There is no Redis and no LISTEN/NOTIFY. | Service entrypoints @ ea8ae4f / bb7825f | Runtime execution is presumed from the documented images (RT-16). |
| [ARC-02 · SOURCE_VERIFIED] | Tables written: (1) the scanner writes `scan_candidates` and `service_heartbeats`. (2) The analyzer upserts `analysis_results` per symbol and timeframe (`analyzer/main.py:165-174`) and sets `scan_candidates.analyzed`. (3) The signal_engine writes `signals` plus `outbox_events` (`signal.ready`) in one transaction, plus `risk_management.signals_sent`, `analysis_results` status, `macro_history` and heartbeats. (4) telegram writes `signals.telegram_sent` plus a `signal.delivered` event in one transaction, plus `risk_management`, `risk_recovery_events`, `approval_requests`, the symbol white/blacklists and heartbeats. (5) The trade_tracker writes `active_trades`, then `trade_results`, plus `paper_entry_orders`, `trade_target_fills`, `risk_management`, `signals` (`telegram_sent=false` on rejects, main.py:768, 804) and outbox events (`trade.*`, `risk.halted`, `risk.observed`, `price_stream.*`, `tracker.recovered`). The tracker admits trades by polling `signals`; `signal.delivered` is used only for reconciliation (main.py:646-679). | Service modules @ ea8ae4f / bb7825f | Table contents were not read (no database access). |
| [ARC-07 · SOURCE_VERIFIED] | `signal.ready` contract (`shared/signal_readiness.py`, `shared/outbox.py`): (1) the payload is {signal_id, decision_source, strategy_version}; (2) events are unique on (event_type, aggregate_type, aggregate_id); (3) they are dead-lettered after 8 attempts (migration 004); (4) `assert_signal_complete` fails closed; (5) a signal counts as ready if `decision_source='policy_ready' OR claude_approved IS TRUE` (`signal_readiness.py:26-33`). | `shared/signal_readiness.py:26-33` @ ea8ae4f | The legacy `claude_approved` branch remains (ARC-16). |

### 2.2 Market-data clients and services

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [ARC-03 · SOURCE_VERIFIED] | Market-data clients: (1) python-binance AsyncClient over REST (`scanner_logic.py:74-124`; `technical_analyzer.py:127-134`, 201 klines; `orderbook_analyzer.py:19`, 20-level book; `macro_context.py:53-63`). (2) CoinGecko `/api/v3/global` for USDT.D and BTC.D (`macro_context.py:28-33`, blocking urllib, no credential). (3) The tracker uses public REST `/api/v3/ticker/price` (main.py:1435), `/exchangeInfo` (1461) and `/klines` (1485), plus the Binance WebSocket aggTrade stream at stream.binance.com (`binance_price_stream.py:12, 94-107`). There is no fear-and-greed or CoinMarketCap client. | Listed files @ ea8ae4f / bb7825f | CoinGecko data are not point-in-time (STR-12). |
| [ARC-04 · SOURCE_VERIFIED] | Scanner: `scanner/main.py` loop (lines 24-64) and `scanner_logic.py`. Inputs are Binance, `symbol_blacklist` and `risk_management`; it writes `scan_candidates` and `service_heartbeats`. Cleanup expires `analysis_results` after 2 h and deletes `scan_candidates` after 1 h. Env files are the shared `.env` plus a second, exchange-specific env file (names only; contents not read); the image is `tsb-aiohttp-test-scanner:3.14.3-20260929T124120Z`. | Scanner blobs per `deployed_files.json` (8bfca77) | The scanner image is an assembled overlay (RT-39); its imports are NOT VERIFIED (RT-40). |
| [ARC-05 · SOURCE_VERIFIED] | Analyzer: `analyzer/main.py`; `technical_analyzer.TechnicalAnalyzer` (`_get_indicator_weights` lines 63 and 482-490, `detect_trade_setup` 68-73, `_calculate_levels`); `orderbook_analyzer.py`; `simple_entry.py`. Each loop reads up to 50 `scan_candidates`, plus Binance data and `indicator_weights`. It writes `analysis_results` and evidence JSONL. It requires schema 11, has no pause check and a 60 s timeout per symbol; a weight read error falls back to 1.0. Only 4 `analyzer/` files are copied into the image. | `analyzer/*` @ ea8ae4f | — |
| [ARC-06 · SOURCE_VERIFIED] | Signal engine: `signal_engine/main.py` (candidate query lines 146-155; live/legacy selector 173-176), `signal_logic.py` (gates 722-831; `save_signal` 911-1026), `macro_context.py`, `shared/signal_identity.py`, `shared/dependency_safety.py`. It reads `analysis_results` under 30 min old (`ORDER BY symbol, total_score DESC LIMIT 200`), plus `active_trades`, `signals`, `scan_candidates` and `macro_history`. It reads `learned_gates` only behind a flag, and `optimizer_settings` and `risk_management`/`trade_results` only on the legacy path. Gate order: macro, then order book/spread (fail-closed), invalid stop, open trade or cooldown, learned gates. There is no pause check. In off mode a cooldown read error becomes an empty set and fails open (`signal_logic.py:424-431`). In enforce mode, bounded retries block the cycle, freshness and duplicate checks apply, and a `setup_key` is required. | `signal_engine/*` @ ea8ae4f | Effective mode NOT VERIFIED (STR-04, STR-34). |
| [ARC-08 · SOURCE_VERIFIED] | Telegram (code bb7825f). (1) `signal_loop` (main.py:187-242) claims 5 events every 15 s with FOR UPDATE SKIP LOCKED and a 300 s lease (`shared/outbox.py:27-44`), including the legacy `signal.reviewed` event (main.py:210). (2) `handle_candidate_event` is at 249-294. (3) `can_deliver_candidate` (364-382): if paused, the candidate is refused and dropped (268-275); capacity is min(MAX_OPEN_TRADES=10, RISK_CANARY_MAX_OPEN_TRADES, default 1). (4) `mark_delivered` is at 576-583. (5) Lifecycle notices (449-539) are at-least-once with a 24 h TTL. (6) /pause, /resume and /recover_risk (852-933) are owner-only. (7) A transient error ends as `expired_undelivered` plus an alert. (8) PAPER_ECONOMIC_HALT_MODE only changes message text in telegram (736-749, 874-878, 472-473). (9) `optimizer_settings` are read only for the /status display. | `telegram/main.py` @ bb7825f | — |
| [ARC-09 · SOURCE_VERIFIED] | Trade tracker (code bb7825f): `main` 73-146; `register_new_signals` 705-904 (signals that are telegram_sent, ready and under 2 h old); `assess_new_trade_risk` 922-1006; `_risk_price` 1020-1038; `record_risk_decision` 1041-1093; `evaluate_trade` 1189-1304; `close_trade_barrier` 1307-1401; `binance_price_stream.py`. The WebSocket reconnects with 5–60 s backoff and a REST check runs every 30 s. The WebSocket price cache is not used for decisions. Writes are idempotent (ON CONFLICT). | `trade_tracker/main.py`, `binance_price_stream.py` @ bb7825f | — |
| [ARC-10 · SOURCE_VERIFIED] | Result recording: `close_trade_barrier` with `shared/triple_barrier.py`, `partial_exits.py`, `fees.py:41-74` and `evidence_v2.py:183-211`. It writes `trade_results` (gross `result` plus `economic_result`, `net_profit_usdt`, `cost_usdt`, `label_policy`), `trade_target_fills`, `risk_management` wins/losses and a `trade.closed` event. Writes are idempotent per signal_id. Evidence goes only to JSONL files under `data/evidence_v2/<service>/`. | Listed files @ bb7825f | Counters are gross (CON-09, part B). |

### 2.3 Structural safety: Paper-only, pause checks, market-data safety

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [ARC-11 · SOURCE_VERIFIED] | There is no order-placement code anywhere in the repository, so Paper-only is structural. PAPER_TRADING (code default true) only gates observe mode and labels. The anthropic package is imported only for exception types (`shared/retry_utils.py:33-40`). | Repository-wide code search @ ea8ae4f / bb7825f / main | Its runtime value is NOT VERIFIED (RT-31); it has no effect on order placement, because none exists. |
| [ARC-12 · SOURCE_VERIFIED] | Pause and halt checks. (1) The scanner's `get_pause_state()` (`scanner_logic.py:26-29`; `trading_state.py:21-47`) fails closed: only the latest `manual_resume` allows scanning. It is the only upstream B3 gate. (2) telegram refuses candidates while paused. (3) The trade_tracker applies its risk gate (RSK-01). (4) The analyzer and signal_engine have no pause check. | Scanner blobs (8bfca77); `telegram/main.py`, `trade_tracker/main.py` @ bb7825f; analyzer and signal_engine @ ea8ae4f | Current pause state NOT VERIFIED (RT-46). |
| [ARC-13 · SOURCE_VERIFIED] | Market-data safety: closed candles only; gaps, duplicates and NaN are rejected (`shared/ohlcv.py:26-83`). The last candle's age is checked only by the freshness rule in integrity enforce mode (`shared/signal_identity.py:186-200`). Stale macro data blocks signals (MACRO_MAX_STALE_HOURS=2). | `shared/ohlcv.py`, `shared/signal_identity.py` @ ea8ae4f | Enforce mode is off by default (STR-33). |

### 2.4 Research components and tests

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [ARC-14 · SOURCE_VERIFIED] | Research components. (1) The forward collector (`python -m p2_forward`, version 1.6.1) reads binance.vision WebSocket/REST data into files under `/data`. It uses no database, runs as the separate project `tsb-p2-forward` and is not on the trading path. Its health file must be at most 30 s old; incidents stay latched until an ack file is written; `previous_run_crash_or_kill` sets DEGRADED; config keys include `ws_session_end_events` and `conn_flapping_enabled`. (2) The learner writes `learned_gates`, `learned_gate_history` and `learning_runs` (Compose profile `learner`, build context "."). (3) The research runner is a systemd user job, not part of Compose. | `p2_forward/` @ 72c0bee; `research/continuous_learner.py` @ ea8ae4f | The collector is unhealthy at runtime and the cause is NOT VERIFIED (RT-45). |
| [ARC-15 · SOURCE_VERIFIED] | Tests by stage: <br>• Market data: `test_ohlcv`, `test_macro_context`. <br>• Scanner: `test_b3_fail_closed_callers` only. <br>• Analyzer: `test_indicators`, `test_orderbook_analyzer`, `test_simple_entry`, `test_regime`, `test_signal_stop`, `test_a43_signal_integrity`, `test_evidence_v2_pit`. <br>• Signal engine: `test_fixed_candidate_policy`, `test_live_spread_finite`, `test_signal_logic_hook`, `test_a44_selection_pipeline`, `test_decision_parity_before_after`. <br>• signal.ready: `test_cr1_signal_ready_contract` and `_e2e`, `test_p1r_cr2_contract` and `_e2e`, `test_outbox`. <br>• Telegram: `test_telegram_handlers` and `test_b3_telegram_gate` (both skip outside `/app`), `test_risk_recovery_command`, `test_paper_economic_alerts`, `test_telegram_messages`. <br>• Tracker: `test_binance_price_stream`, `test_risk_price_retry`, `test_paper_economic_observation`, `test_paper_observe_capacity`, `test_a49_*`, `test_risk_epoch_concurrency`, `test_a48_tracker_parity_db`. <br>• Result recording: `test_a38_lifecycle_db`, `test_fees`, `test_triple_barrier`, `test_partial_exits`, `test_evidence_v2_tracker_db`. <br>• Research: `p2_forward/tests` (about 27 files), `test_continuous_learner`. | `tests/`, `p2_forward/tests/` | Tests prove mechanics, not economics. Tests were not run in this audit. |

### 2.5 Retired, legacy and hazardous remnants

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [ARC-16 · SOURCE_VERIFIED] | claude_review has no Compose service and no import on the active path. Two passive dependencies remain: (1) telegram still claims the legacy `signal.reviewed` event (`telegram/main.py:210`); (2) `READY_SQL_PREDICATE` still accepts `claude_approved IS TRUE`. | `telegram/main.py` @ bb7825f; `shared/signal_readiness.py` @ ea8ae4f | — |
| [ARC-17 · INFERRED] | Neither passive dependency is live: the signal_engine emits only `signal.ready`, and the tracker's 2-hour admission window excludes old approved rows. | Reasoning from ARC-16 and ARC-09 | Not observed at runtime. |
| [ARC-18 · SOURCE_VERIFIED] | Hazard: the tracked `docker-compose.yml.bak` still defines claude_review. The file is also present in the production directory. | `docker-compose.yml.bak` (tracked) | — |
| [ARC-19 · SOURCE_VERIFIED] | Learner start paths: `--profile learner` builds from the production checkout (63da7d3 plus edits); `ops/compose-safe` refuses to start the learner. | `docker-compose.yml` (blob d1a4b197); `ops/compose-safe` @ main | — |
| [ARC-20 · DOCUMENTED_ONLY] | The signal_engine image contains the learner script, so the learner could be run via exec. | Deploy records | Image contents not hashed (RT-17). |
| [ARC-21 · SOURCE_VERIFIED] | Code not imported by any service: (1) `claude_review/`, `optimizer/` (Compose profile `disabled`), `colab/`, `monitor_canary.py` and most of `analyzer/`; (2) the shared modules candidate_selection, signal_selection, s3_shadow*, trade_geometry, strategy_math, t1_cap, execution_calibration, replay_execution, signal_quality, setup_diagnostics, counterfactual_barrier and candidate_diagnostics. | Import graph @ ea8ae4f / bb7825f | — |

### 2.6 Flags and code defaults

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [ARC-22 · SOURCE_VERIFIED] | Code defaults: <br>• SIGNAL_INTEGRITY_MODE: default off (`shared/config.py:118` at ea8ae4f); an unknown value refuses start. <br>• EVIDENCE_V2_ENABLED: "true" in Compose. <br>• LIVE_LEARNING_MODE: default false (`shared/config.py:74` at ea8ae4f). <br>• LEARNING_GATES_ENABLED: default false. <br>• LEARNING_CLEAN_START, LEARNING_CONFIDENCE_Z, LEARNING_EXPLORATION_RATE: env names set on signal_engine. <br>• SCAN_INTERVAL_SECONDS: 300. <br>• PAPER_ECONOMIC_HALT_MODE: default enforce (`shared/config.py:131` as read at bb7825f). <br>• PAPER_ENTRY_FILL_MODEL (`shared/config.py:112` at bb7825f): observed_price_v0 or resting_limit_v1; an unknown value refuses start. <br>• RISK_PRICE_FETCH_RETRIES: default 0 (:157 at bb7825f), backoff 0.5 (:158 at bb7825f). <br>Line numbers differ between ea8ae4f and bb7825f because `shared/config.py` gained 32 lines (RT-37). | `shared/config.py` @ ea8ae4f / bb7825f | Effective `.env` values NOT VERIFIED (RT-47). |
| [ARC-23 · DOCUMENTED_ONLY] | The 2026-09-27 non-secret baseline config snapshot records ENABLE_EVIDENCE_RECORDER true and LIVE_LEARNING_MODE true. | `deploy/baseline-2026-09-27/config/*.nonsecret.json` | The snapshot predates every current container start (2026-10-19 to 2026-10-27, RT-09). |

## 3. Active runtime configuration and parity

"Active" has five distinct senses in this section, and they are never merged:

| Sense | Meaning | Class |
|---|---|---|
| Observed running | A container is running at inspection time | RUNTIME_VERIFIED |
| Configured in Compose | A value set in Compose, confirmed by the config hash or Compose blob | RUNTIME_VERIFIED |
| Code default | The value in source at the deployed commit | SOURCE_VERIFIED |
| Documented setting | A value in the 2026-09-27 non-secret snapshot or in deploy records | DOCUMENTED_ONLY |
| Effective runtime value | A value set in `.env` or in the database | NOT_VERIFIED |

All runtime rows below were observed on 2026-10-31 with Class A read-only commands (PD-01).

### 3.1 Production checkout

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [RT-01 · RUNTIME_VERIFIED] | The production checkout (directory [REDACTED-HOST-PATH]) is on branch `integration/research-pipeline` with no upstream configured. HEAD is 63da7d3 (dated 2026-08-19, the research-freeze date), equal to the remote tip of that branch. | Host git state, read-only · runtime | Point-in-time. |
| [RT-02 · RUNTIME_VERIFIED] | 8 modified tracked files (+219/−204 changed lines): `analyzer/technical_analyzer.py` 146, `telegram/main.py` 104, `docker-compose.yml` 84, `trade_tracker/main.py` 30, `docs/canary_state.md` 29, `database/init.sql` 22, `.gitignore` 6, `shared/schema.py` 2. There are also 104 untracked entries (research data, scripts, docs). | Host git status/diff statistics · runtime | Untracked contents were not reviewed. |
| [RT-03 · RUNTIME_VERIFIED] | Blob identity. The checkout's `docker-compose.yml`, `database/init.sql` and `.gitignore` equal the blobs at main eba90dd; `init.sql` also equals ea8ae4f and bb7825f (blob 031b1c0). `technical_analyzer.py`, `shared/schema.py`, `telegram/main.py`, `trade_tracker/main.py` and `docs/canary_state.md` match none of HEAD, main, ea8ae4f or bb7825f: five files carry uncommitted edits that match no commit. | Host `git hash-object` compared with git objects | — |
| [RT-04 · RUNTIME_VERIFIED] | Relation to main: remote main = eba90dd (ls-remote); merge-base(63da7d3, eba90dd) = 63da7d3; ahead 0, behind 267. The checkout's own origin/main ref is stale at 0a396c2 (2026-06-28), and eba90dd is absent from its object store. The relation therefore cannot be derived from the checkout alone. | `git ls-remote`; merge-base in the audit's shared object store | — |
| [RT-05 · RUNTIME_VERIFIED] | The production checkout contains neither a `deploy/` nor an `ops/` directory. | Host directory listing · runtime | See CON-02 (part B). |
| [RT-06 · SOURCE_VERIFIED] | REQUIRED_SCHEMA_VERSION: 8 at 63da7d3; 9 in the checkout's uncommitted edits; 11 at ea8ae4f, bb7825f and main (migrations 001–011 present at ea8ae4f). The uncommitted edits include migration 009 (`risk_recovery_events`) and a `cmd_recover_risk` Telegram command, an older version of what later landed. | Git objects; host working-tree files | The checkout value was read from host files. |
| [RT-07 · SOURCE_VERIFIED] | The checkout differs from every deployed image's documented source in `analyzer/`, `signal_engine/`, `telegram/main.py` and `trade_tracker/`. Checkout ≠ main for `analyzer/main.py`, `technical_analyzer.py`, `signal_engine/main.py`, `signal_logic.py`, `telegram/main.py`, `trade_tracker/main.py` and `binance_price_stream.py`; `scanner/*.py` equal main and ea8ae4f. Only continuous_learner would build from the checkout. | File-hash comparison against git objects | — |
| [RT-08 · INFERRED] | The checkout's edit to `analyzer/technical_analyzer.py` (+7/−139 against 63da7d3) replaces inline indicator and level code with `shared/strategy_math` calls. By reading, it is functionally equivalent. It is not what runs: the image is documented as ea8ae4f content. | Reading of the diff | Equivalence not tested. |

### 3.2 Service and container inventory

[RT-09 · RUNTIME_VERIFIED] Container inventory (dates 2026, minute precision, restart count 0 for all). Source: host `docker ps`/`docker inspect` (Config.Image, Image Id, Created, State, StartedAt, RestartCount, Health, restart policy) · runtime 2026-10-31.

| Container (project) | State | Config.Image | Image Id | Created | Started | Health | Restart policy |
|---|---|---|---|---|---|---|---|
| trading_analyzer | running | `tsb-a561-analyzer:rel-ea8ae4f-r2` | 011f99ba451b | 10-16 22:19Z | 10-19 15:20Z | healthy | unless-stopped |
| trading_scanner | running | `tsb-aiohttp-test-scanner:3.14.3-20260929T124120Z` | 63b38e7a659d | 09-30 06:50Z | 10-19 15:20Z | healthy | unless-stopped |
| trading_signal_engine | running | `tsb-a561-signal_engine:rel-ea8ae4f-r2` | c5be4e34c064 | 10-16 22:50Z | 10-19 15:20Z | healthy | unless-stopped |
| trading_telegram | running | `tsb-obs-telegram:bb7825f-20261027-r2` | d665388a9092 | 10-27 11:51Z | 10-27 11:51Z | healthy | unless-stopped |
| trading_tracker | running | `tsb-obs-trade_tracker:bb7825f-20261027-r2` | 8e609ca84740 | 10-27 10:56Z | 10-27 10:56Z | healthy | unless-stopped |
| trading_continuous_learner | exited (143) | `trading-signal-bot-continuous_learner` | d1aa69bde63f | 08-17 17:49Z | 08-17 17:49Z, finished 08-17 21:03Z | unhealthy (left over from its last run) | unless-stopped |
| tsb-p2-forward-collector (project tsb-p2-forward) | running | `tsb-p2-forward:p2f-161-72c0bee-20261022T1558Z` | 89232400d528 | 10-22 17:45Z | 10-22 17:45Z | unhealthy | no |
| postgres (project shared-postgres) | running | `postgres:16.15-alpine3.24@sha256:721873c3…` | 721873c34ceb | 09-29 12:05Z | 10-19 15:20Z | healthy | unless-stopped |

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [RT-10 · RUNTIME_VERIFIED] | Running: analyzer, scanner, signal_engine, telegram, trade_tracker, the forward collector and postgres. Stopped but present: trading_continuous_learner (exited 143). No container: claude_review, redis, optimizer. | Host `docker ps -a` · runtime | Point-in-time. |
| [RT-11 · RUNTIME_VERIFIED] | continuous_learner stayed stopped through the 2026-10-19 restart of the other services. Its restart policy is unless-stopped. | Host `docker inspect` · runtime | — |
| [RT-12 · INFERRED] | Because the policy is unless-stopped, the learner staying stopped depends on three things: the manual-stop flag, the `learner` Compose profile and the operating procedure. | Reasoning from RT-11 and the Compose profile | Not a guarantee; see GOV-01 and GOV-05 (part B). |
| [RT-13 · RUNTIME_VERIFIED] | claude_review has no container and its service is removed from the Compose file. The image `trading-signal-bot-claude_review:latest` is still present locally. | Host `docker ps -a`, `docker image ls` · runtime | — |

### 3.3 Images and provenance

[RT-14 · RUNTIME_VERIFIED] Images (Id prefix, creation time UTC, source labels, matching deploy records). Source: host `docker image inspect` · runtime 2026-10-31.

| Image | Id | Created | Source labels | Matches records |
|---|---|---|---|---|
| `tsb-a561-analyzer:rel-ea8ae4f-r2` | 011f99ba451b | 10-16 18:46 | revision=unknown | a561 IMAGES.md, DEPLOYED.json |
| `tsb-a561-signal_engine:rel-ea8ae4f-r2` | c5be4e34c064 | 10-16 18:46 | revision=unknown | a561 IMAGES.md, DEPLOYED.json |
| `tsb-aiohttp-test-scanner:3.14.3-20260929T124120Z` | 63b38e7a659d | 09-29 12:41 | revision=unknown | aiohttp IMAGES.md, DEPLOYED.json |
| `tsb-obs-telegram:bb7825f-20261027-r2` | d665388a9092 | 10-27 07:40 | revision=bb7825f; base tsb-a561-telegram (51d62f4d) | paper-observe IMAGES.md, VERSION_BOUNDARY, DEPLOYED.json |
| `tsb-obs-trade_tracker:bb7825f-20261027-r2` | 8e609ca84740 | 10-27 07:40 | revision=bb7825f; base 2cf1dd52 | paper-observe IMAGES.md, VERSION_BOUNDARY, DEPLOYED.json |
| `tsb-p2-forward:p2f-161-72c0bee-20261022T1558Z` | 89232400d528 | 10-22 15:58 | no labels at all | Stage A record, DEPLOYED.json |
| `continuous_learner:latest` | d1aa69bde63f | 08-17 17:48 | revision=c4cae2b-dirty | DEPLOYED.json |

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [RT-15 · RUNTIME_VERIFIED] | Image labels name a source commit only for the two tsb-obs images (revision=bb7825f). The analyzer, signal_engine and scanner images carry revision=unknown; the collector image has no labels; the learner image is labelled c4cae2b-dirty. | Host `docker image inspect` (labels) · runtime | Labels are self-declared metadata. |
| [RT-16 · DOCUMENTED_ONLY] | Content parity between running images and documented commits is recorded only in deploy records: [DEPLOYED.json](../../../deploy/DEPLOYED.json), `deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json` and the IMAGES.md files. They record: analyzer 46/46 files and signal_engine 56/56 files equal to ea8ae4f; telegram 50/50 and trade_tracker 51/51 equal to bb7825f; the scanner as an assembled overlay in which 8 of 23 files differ from main. | Deploy records @ main | Not independently verified. |
| [RT-17 · NOT_VERIFIED] | Image filesystem content was not hashed: that needs an image filesystem read, which is not a Class A operation and was not authorized. **No code behaviour described in this pack is runtime-verified**; behaviour is SOURCE_VERIFIED at the documented commit only. | — | Authorization required (see the open questions in part B). |
| [RT-18 · RUNTIME_VERIFIED] | RepoDigests are only `<repo>@<Id>`: these are local images with no registry digest. | Host `docker image inspect` · runtime | No registry-backed provenance. |
| [RT-19 · RUNTIME_VERIFIED] | Rollback images present locally: tsb-a561-telegram (51d62f4d) and tsb-a561-trade_tracker (2cf1dd52), matching [VERSION_BOUNDARY.md](../../../deploy/VERSION_BOUNDARY.md); tsb-p1d-analyzer and tsb-p1d-signal_engine; tsb-aiohttp-rollback-scanner (9b0b53a6). | Host `docker image ls` · runtime | Presence only; not exercised. |
| [RT-20 · RUNTIME_VERIFIED] | For four containers the `com.docker.compose.image` label differs from the image Id: scanner b647a72a (the documented arm64 manifest digest); telegram ef66b10b, trade_tracker 37444d16 and collector cb3dd739. | Host `docker inspect` (labels) · runtime | — |
| [RT-21 · NOT_VERIFIED] | The telegram, trade_tracker and collector label digests are not documented anywhere. They are INFERRED to be platform-manifest digests. | — | Meaning unconfirmed. |

### 3.4 Compose configuration and config hashes

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [RT-22 · RUNTIME_VERIFIED] | Compose `config --services` lists analyzer, scanner, signal_engine, telegram and trade_tracker. | Host Compose (Class A) · runtime | The learner and optimizer are behind profiles. |
| [RT-23 · RUNTIME_VERIFIED] | For every running bot service, the current `config --hash`, the container label and the deploy record are identical: analyzer c69beccc, scanner e99de276, signal_engine 20dcae19, telegram 14b2baf7, trade_tracker 539e6347. The deploy records are the a561, aiohttp and paper-observe IMAGES.md files and DEPLOYED.json. | Host `config --hash`; container labels; deploy records | Hash prefixes only. |
| [RT-24 · RUNTIME_VERIFIED] | The host Compose file blob (`git hash-object`) d1a4b197 equals `eba90dd:docker-compose.yml`, the DEPLOYED.json `git_blob` and the VERSION_BOUNDARY stage-2 blob, and differs from the checkout HEAD blob e83a83fc. The "local modification" is therefore main's reviewed Compose file sitting on a stale branch. | Host file hash vs git objects · runtime | Blob-level parity only (CON-03, part B). |
| [RT-25 · RUNTIME_VERIFIED] | Compose changes against the checkout HEAD (names only): (1) claude_review removed; (2) continuous_learner gained `profiles`; (3) scanner `build` replaced by `image` plus `pull_policy`; (4) analyzer and signal_engine: the same, plus `volumes`, the CoinMarketCap and CoinGecko credential variables (set blank; no client uses them) and EVIDENCE_V2_ENABLED; (5) telegram and trade_tracker: the same, plus EVIDENCE_V2_ENABLED and PAPER_ECONOMIC_HALT_MODE (literal observe). | Host Compose file vs checkout HEAD (names only) | Values other than the literals named were not read. |
| [RT-26 · RUNTIME_VERIFIED] | No running service has `build:`. Mounts are logs, models and evidence data only; there are no source bind mounts. | Host `docker inspect` (Mounts) · runtime | — |
| [RT-27 · INFERRED] | Therefore the checkout's uncommitted code is not executed by any running service. | Reasoning from RT-26 | — |
| [RT-28 · RUNTIME_VERIFIED] | The scanner container was created with an additional override file kept in a host backup directory. The file exists but was not read. The plain-file render hash now equals the container's label. | Host `docker inspect` labels; config hash · runtime | Override content not read. |
| [RT-29 · RUNTIME_VERIFIED] | Collector: the host `compose.yml` blob 12052900 equals `eba90dd:p2_forward/compose.yml` and DEPLOYED.json. | Host file hash vs git objects · runtime | — |
| [RT-30 · NOT_VERIFIED] | The collector render hash was not computed, because it needs P2F_* environment values. | — | — |
| [RT-31 · NOT_VERIFIED] | PAPER_TRADING is not set in any service's Compose `environment:` block. Its runtime value (from `.env`, or the code default true) was not read. | Compose blob d1a4b197 | No order code exists either way (ARC-11). |

### 3.5 Parity verdict per service

Each cell names its own evidence class. "Integrated in main" is checked by git ancestry against eba90dd and is source-verified.

| Service | Documented commit | Integrated in main | In the deployed image | Configured-enabled | Observed executing | Operationally verified |
|---|---|---|---|---|---|---|
| analyzer | ea8ae4f | yes (ancestry) | DOCUMENTED_ONLY 46/46; label revision=unknown | yes (RUNTIME_VERIFIED) | running, healthy (RUNTIME_VERIFIED) | NOT_VERIFIED (needs an image filesystem read) |
| signal_engine | ea8ae4f | yes (ancestry) | DOCUMENTED_ONLY 56/56; label revision=unknown | yes (RUNTIME_VERIFIED) | running, healthy (RUNTIME_VERIFIED) | NOT_VERIFIED |
| scanner | assembled overlay (8 of 23 files differ from main) | n/a | DOCUMENTED_ONLY | yes (RUNTIME_VERIFIED) | running, healthy (RUNTIME_VERIFIED) | NOT_VERIFIED |
| telegram | bb7825f | yes (ancestry) | label revision=bb7825f (RUNTIME_VERIFIED); content DOCUMENTED_ONLY 50/50 | yes, observe (RUNTIME_VERIFIED) | process running (RUNTIME_VERIFIED); observe path NOT_VERIFIED | DOCUMENTED_ONLY: record says "Validated: NO" |
| trade_tracker | bb7825f | yes (ancestry) | label revision=bb7825f (RUNTIME_VERIFIED); content DOCUMENTED_ONLY 51/51 | yes, observe (RUNTIME_VERIFIED) | process running (RUNTIME_VERIFIED); observe path NOT_VERIFIED | DOCUMENTED_ONLY: record says "Validated: NO" |
| collector | 72c0bee | yes (ancestry) | DOCUMENTED_ONLY (image has no labels) | yes (RUNTIME_VERIFIED) | running, **unhealthy** (RUNTIME_VERIFIED) | NOT_VERIFIED (cause unknown) |
| continuous_learner | c4cae2b-dirty | yes for c4cae2b (ancestry); the image was built from a dirty tree | label c4cae2b-dirty (RUNTIME_VERIFIED) | excluded by profile | not executing (RUNTIME_VERIFIED) | n/a |
| production checkout (63da7d3 plus edits) | n/a | 63da7d3 is an ancestor of main | not the source of any running image (INFERRED, RT-27) | n/a | n/a | n/a |

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [RT-32 · RUNTIME_VERIFIED] | Configured-enabled and executing: (1) analyzer, signal_engine, scanner, telegram and trade_tracker are running and healthy; (2) telegram and trade_tracker are configured with PAPER_ECONOMIC_HALT_MODE=observe; (3) the collector is running; (4) the learner is not executing (excluded by profile). | Host `docker ps`; Compose render · runtime | — |
| [RT-33 · NOT_VERIFIED] | Two things need image filesystem access: whether the observe code path is the one executing in telegram and trade_tracker, and per-service operational verification in general. | — | Authorization required. |
| [RT-34 · DOCUMENTED_ONLY] | The paper-observe deployment record states "Validated: NO" for telegram and trade_tracker. | paper-observe IMAGES.md (deploy record) | — |
| [RT-35 · RUNTIME_VERIFIED] | Every DEPLOYED.json service entry (8 of 8) matches its live container on container ID, image Id, image ref, start time, restart count, state and config hash. DEPLOYED.json does not track health. | DEPLOYED.json vs host `docker inspect` · runtime | Container IDs are not reproduced here. |
| [RT-36 · DOCUMENTED_ONLY] | DEPLOYED.json `release_manifest` still points to the a561 manifest, while the paper-observe manifest lives only on the host. A plain deep check therefore reports drift for telegram, trade_tracker and the collector by design. This is known and documented. | DEPLOYED.json; paper-observe record | — |

### 3.6 Version drift between documented commits and main

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [RT-37 · SOURCE_VERIFIED] | **ea8ae4f → bb7825f** added T1_CAP_POLICY (`shared/t1_cap.py`, from a4a7561), `shared/economic_halt_policy.py` and the observe-aware `risk_epoch.operational_state`. It also changed `analyzer/main.py` (+2, the T1 startup check), `technical_analyzer.py` (17 lines), `signal_logic.py` (+1 `telemetry_min_interval` line), `shared/config.py` (+32) and `telegram_messages`. <br>**bb7825f → main:** for active code they are equal; only `docker-compose.yml` differs (6 lines). <br>**63da7d3 → ea8ae4f:** 42 files changed (about +7,500 lines) in active directories. For example, `shared/signal_readiness.py`, outbox_watch, signal_identity, signal_selection and risk_epoch are absent at 63da7d3. | `git diff` across 63da7d3, ea8ae4f, bb7825f, eba90dd | — |
| [RT-38 · INFERRED] | Running analyzer and signal_engine without economic_halt_policy, risk_epoch or t1_cap is harmless today, because neither service imports them. The T1-cap consequence is covered in STR-17. | Reasoning from the import graph | — |
| [RT-39 · DOCUMENTED_ONLY] | The scanner image is assembled from several older commits (`deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json:622-866`; `deploy/baseline-2026-09-27/deployed_files.json`). Its `main.py` (blob 3dc9cb1) and `scanner_logic.py` (blob fa03cc2a) are identical to ea8ae4f and main. Its shared config (c5c03b5c from 7bf6214), macro, outbox and schema files are older versions, and its schema guard requires v6. | Deploy records; blob comparison | Image contents not hashed (RT-17). |
| [RT-40 · NOT_VERIFIED] | The scanner's actual imports are unknown, because its base revision is unknown. | — | — |

### 3.7 Branch integration status

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [RT-41 · SOURCE_VERIFIED] | 141 remote heads; merge status is by ancestry against eba90dd. <br>**Merged:** integration/research-pipeline (equals the production HEAD), develop, dev; feature/a42 through a48, feature/s3-signal-selection, s3-shadow-sidecar, s3-shadow-evaluation; fix/a38-paper-execution-integrity, fix/a49-economic-label-on-a38, fix/b3-fail-closed-trading-state, fix/loss-streak-recovery-epoch, fix/t1-cap-policy-flag; feat/research-admission-budget and -probes, feat/throttle-decay; research/s4-mechanism-infra, research/s4-phase1-comparison, docs/strategy-lab-architecture. <br>**Not merged (commits outside main):** feature/design-a-v1 +5; integration/rnd +8; integration/paper-vb-a1 +5; integration/paper-observe-activation +3; integration/a49-candidate +9, a49-candidate-r2 +11, a50 +14, a51 +16, a52 +20, a53 +10; research/variant-ledger +10; feat/research-admission-shadow +3; feat/technical-halt-recovery +4; feat/s5-pwr-1-ladder-power +3; lab/l1-account-safeguards +6; lab/l1-parity-guards +8; release/rc-b-se-telemetry-on-ea8ae4f +1; refactor/strategy-math +1; safety/disable-auto-tune +1; fix/a49-nonfinite-economic-label +11; docs/profitability-roadmap +3; feature/p2a, p2b, p2c, p2cr, p2e1, p2f0, p2rm0, p2x0, p2x1 (+1 to +61); feature/g1g2 +3; feature/forward-instrumentation +1. | Remote heads; `git merge-base --is-ancestor` | — |
| [RT-42 · INFERRED] | The merge check uses ancestry only, so work integrated by squash or cherry-pick would still appear as not merged. | Method limitation | — |

### 3.8 Health observations

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [RT-43 · RUNTIME_VERIFIED] | Health at 13:59Z and 14:05Z: <br>• analyzer, scanner, signal_engine and telegram: healthy ×2, 0 restarts; the safe log check (tail 20) found 0 error/traceback, 0 connection-failure and 0 halt/pause/observe lines. <br>• trade_tracker: healthy ×2, 0 restarts; 0 error, connection or halt lines. <br>• collector: unhealthy ×2, 0 restarts. <br>• postgres: healthy ×2, 0 restarts. | Host `docker inspect` (Health); `ops/compose-safe` category counts · runtime | Only 20 log lines per service, as counts. |
| [RT-44 · NOT_VERIFIED] | trade_tracker has WARN-level log lines. They were not inspected, because their text matched protected patterns. | — | Their content is unknown. |
| [RT-45 · NOT_VERIFIED] | The cause of the collector's unhealthy status is unknown. Its logs were not checked: `ops/compose-safe` does not cover project tsb-p2-forward, and Health.Log is not an allowed field. | — | Contradicts the post-deploy record (CON-05, part B). |
| [RT-46 · NOT_VERIFIED] | PAPER_HALTED, pause and risk state; reading them requires database access. | — | Authorization required. |
| [RT-47 · NOT_VERIFIED] | Not read: (1) the runtime values of SIGNAL_INTEGRITY_MODE, LIVE_LEARNING_MODE, LEARNING_GATES_ENABLED, TIMEFRAMES, RISK_CANARY_MAX_OPEN_TRADES and PAPER_ENTRY_FILL_MODEL, all of which come from `.env`; (2) container state beyond what DEPLOYED.json records (that file was observed on 2026-10-27). | — | Authorization required. |

### 3.9 Active decision path and configuration precedence

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [STR-01 · SOURCE_VERIFIED] | Active-path switch: `signal_engine/main.py:173-176` calls `find_best_signal_live` when LIVE_LEARNING_MODE is set, and the legacy `find_best_signal` otherwise. The code default is false (`shared/config.py:74`). The flag selects rule-based setups and the `fixed_execution_quality_v1` selection policy; it runs no learning and reads no learner table, so its name is misleading. | `signal_engine/main.py`, `shared/config.py` @ ea8ae4f | — |
| [STR-02 · DOCUMENTED_ONLY] | LIVE_LEARNING_MODE=true in the 2026-09-27 non-secret config snapshot. | `deploy/baseline-2026-09-27/config/*.nonsecret.json` | Snapshot taken before every current container start (RT-09). |
| [STR-03 · INFERRED] | The live path is presumed active. The snapshot predates every current container start (2026-10-19 to 2026-10-27, RT-09), but the `.env` modification time (metadata only) predates the snapshot, so its values are plausibly still current. | Reasoning from STR-02 and `.env` metadata | Presumption, not observation. |
| [STR-04 · NOT_VERIFIED] | The actual runtime value of LIVE_LEARNING_MODE. Every live-path rule in sections 4–8 is conditional on it. | — | Authorization required. |
| [CAL-01 · SOURCE_VERIFIED] | Precedence: Compose `environment:` > `.env` (env_file) > dataclass default read at import. No strategy or universe variable is set in any Compose `environment:` block, so every strategy value comes from the unread `.env`. Hard-coded constants cannot be overridden. The only DB override is `optimizer_settings` min_score/min_tf, on the legacy path. `indicator_weights` have no env counterpart: they multiply score parts, with default 1.0. | `shared/config.py`; Compose blob d1a4b197; `signal_logic.py` @ ea8ae4f | — |
| [CAL-02 · DOCUMENTED_ONLY] | Configured values come from the committed resolved-config snapshot `deploy/baseline-2026-09-27/config/*.nonsecret.json` (2026-09-27), taken before every current container started (analyzer, scanner, signal_engine and postgres 2026-10-19; collector 2026-10-22; telegram and trade_tracker 2026-10-27; RT-09). `.env.example` values are cited via `docs/ops/ENV_EXAMPLE_REVIEW_2026-10-18.md`, which itself flags `.env.example` as misleading (line 20). | Snapshot files; review document | It may be stale. |
| [CAL-03 · NOT_VERIFIED] | No effective runtime value is verified: runtime-verified is "no" for every parameter. Every DB value (`optimizer_settings`, `indicator_weights`, `learned_gates`, `symbol_blacklist`) requires authorization. | — | Authorization required. |

### 3.10 Key flags: configured, documented and observed

The columns are:
- **Code default:** SOURCE_VERIFIED at the deployed commit.
- **Compose `environment:`:** blob d1a4b197, equal to the host file (RUNTIME_VERIFIED).
- **2026-09-27 snapshot:** DOCUMENTED_ONLY.
- **Runtime value:** NOT VERIFIED unless stated.

| Flag | Code default | Compose `environment:` | 2026-09-27 snapshot | Runtime value | Effect | IDs |
|---|---|---|---|---|---|---|
| LIVE_LEARNING_MODE | false | not set | true | NOT VERIFIED | Live selector (rule-based setups, `fixed_execution_quality_v1`) vs legacy selector; the macro gate runs only on the live path | STR-01 to STR-04, MKT-04 |
| SIGNAL_INTEGRITY_MODE | off; an unknown value refuses start | not set | — | NOT VERIFIED (likely off; documents say no enforce window was authorized, STR-34) | enforce adds candle identity, ≤ 1-bar freshness and an insert-once `setup_key` | STR-33, STR-34, RT-47 |
| LEARNING_GATES_ENABLED | false | not set; LEARNING_EXPLORATION_RATE has a Compose default of 0.10 | false | NOT VERIFIED | Enables `learned_gates` throttling | STR-18, STR-19, LRN-18 to LRN-20 |
| PAPER_ECONOMIC_HALT_MODE | enforce; an unknown value falls back to enforce | observe (telegram, trade_tracker) | — | Compose value RUNTIME_VERIFIED; executing code path NOT VERIFIED | observe records the economic checks instead of pausing | RT-25, RT-32, RT-33, RSK-01 |
| PAPER_TRADING | true | not set | — | NOT VERIFIED | Gates observe mode and labels only; no order code exists | RT-31, ARC-11 |
| PAPER_ENTRY_FILL_MODEL | observed_price_v0; an unknown value refuses start | not set | — | NOT VERIFIED | The alternative is resting_limit_v1 (off) | EXE-07, EXE-08 |
| RISK_CANARY_MAX_OPEN_TRADES | 1 | not set | 2 (also in `.env.example`) | NOT VERIFIED | Capacity = min(10, value) | EXE-02, EXE-03 |
| TIMEFRAMES | 15m,1h,4h,1d | not set | 15m,4h,1d | NOT VERIFIED | Candidate timeframes | STR-05, STR-06 |
| EVIDENCE_V2_ENABLED | — | "true" | — | Compose value RUNTIME_VERIFIED | Evidence JSONL recording | RT-25, ARC-22 |
| MAX_SPREAD_PCT | 0.15 | not set | 0.15 | NOT VERIFIED | Live spread gate | IND-03 |
| MIN_VOLUME_USDT | 10,000,000 | not set | 10M | NOT VERIFIED | Universe volume filter | UNI-09, UNI-10 |

## 4. Strategy families and precise rules

All rules below are SOURCE_VERIFIED at ea8ae4f for the analyzer and signal_engine, or bb7825f for the tracker, unless a block says otherwise. That the images run this code is DOCUMENTED_ONLY (RT-16, RT-17). Every live-path family is conditional on LIVE_LEARNING_MODE (STR-01 to STR-04). No family has accessible economic evidence that would support a profitability claim.

### 4.1 Status overview

| Family | Version identifier | Status | Activation evidence | IDs |
|---|---|---|---|---|
| momentum breakout | setup `momentum`; rules introduced at 63da7d3 | CURRENT-ACTIVE if LIVE_LEARNING_MODE is true | Flag documented true; runtime NOT VERIFIED | STR-07 |
| RSI/Bollinger reversion | setup `reversion`; rules introduced at 63da7d3 | CURRENT-ACTIVE if LIVE_LEARNING_MODE is true | as above | STR-08 |
| Regime routing | `shared/regime.py` introduced at 63da7d3 | ACTIVE on the live path | as above | STR-09, STR-10 |
| Macro gate | `shared/macro_context.py` blob 9099d1d1 | ACTIVE on the live path | as above | STR-11, STR-12 |
| Live ranking | A44 "production_parity" = `_fixed_candidate_key`; policy `fixed_execution_quality_v1` | ACTIVE on the live path | as above | STR-13 |
| T1 cap | hard-coded resistance × 0.99 at ea8ae4f, with no switch; the later T1_CAP_POLICY flag (a4a7561) defaults to `legacy_window_v1` and adds `independent_swing_v1` | legacy cap in the documented-deployed source (image content not verified, RT-17) | the missing switch is source-verified | STR-17, STR-21 |
| Legacy score path | `legacy_score_v1` | DISABLED as a decision path; the score is still computed | flag documented true | STR-14 to STR-16 |
| Learned gates | `learned_gates` rows; strategy_version default 'legacy' | DISABLED | flag documented false | STR-18, STR-19 |
| Earlier 15m/4h family | pre-63da7d3 | HISTORICAL | superseded | STR-20 |
| A42 C1 / C2 / C3 | `a42-sq-v1` | C1, C2 DORMANT; C3 PROPOSED | `enabled=False`; not imported | STR-26 to STR-29 |
| A44 rankers, S3 | `execution_quality_v2`, `cost_per_risk_v1`; `s3-sel-v1`, `s3-shadow-v1` | DORMANT | `S3Policy.enabled=False` | STR-30 to STR-32 |
| A43 signal integrity | SIGNAL_INTEGRITY_MODE=enforce | FLAGGED OFF | default off; not in Compose | STR-33, STR-34 |
| A45 H1–H3 | `a45-sd-v1` | DORMANT / RESEARCH | `enabled=False` | STR-35 |
| A46 G1–G3 | `a46-tg-v1` | DORMANT | unimportable in ea8ae4f images (inferred) | STR-36, STR-37 |
| S4 M1–M5 and Phase-1 H1–H3 | `s4-mech-v1` | RESEARCH-ONLY, NOT TESTED | refuses non-synthetic data | STR-38 |
| Design A | v1.0 (feature branch only) | RESEARCH-ONLY; evaluation not authorized | unmerged branch | STR-39 |
| Historical research families | various | HISTORICAL | — | STR-40 |

The runtime `strategy_version` / APP_VERSION emitted by the services is NOT VERIFIED. The code default is `sb-2026.06` (CAL-09, CAL-10).

### 4.2 Rules common to the live setups

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [STR-05 · SOURCE_VERIFIED] | Common rules: <br>• closed bars only; long-only; <br>• timeframes from `config.TIMEFRAMES` (code default 15m,1h,4h,1d; TIMEFRAMES_LL is defined but unused); <br>• universe = the scanner list (section 6); <br>• targets from `technical_analyzer._calculate_levels`: T1 +1R, T2 +1.8R, T3 +2.2R, with the W3 cap (STR-21); <br>• stops from `shared/signal_stop.py:plan_signal_stop`, rejected when risk exceeds the timeframe cap: 15m 2%, 1h 4%, 4h 5%, 1d 3%. | `simple_entry.py`, `technical_analyzer.py`, `signal_stop.py` @ ea8ae4f | — |
| [STR-06 · DOCUMENTED_ONLY] | Timeframes are 15m, 4h and 1d in the 2026-09-27 snapshot; the effective value is NOT VERIFIED. | Snapshot files | — |
| [STR-22 · INFERRED] | EMA200 is immature, because only 200 bars are fetched. | Reasoning from the fetch size | Affects only EMA200-based logic (`trend_ok`, legacy). |
| [STR-23 · DOCUMENTED_ONLY] | Calibration is hand-set: `docs/indicator_regime_execution_review_2026-08-19.md` calls the rules "operational starting points, not evidence of edge". | Review document @ ebf8d8a (= main) | — |
| [STR-24 · SOURCE_VERIFIED] | Evidence for the live rules is mechanics tests only: test_simple_entry 7, test_regime 2, test_signal_stop 4, test_indicators 7. | `tests/` | No economic validation. |
| [STR-25 · INFERRED] | No pre-freeze economic evidence exists for these exact rules. 63da7d3, which introduced them, is dated on the research-freeze date (2026-08-19) and precedes the recorded freeze boundary, so all their outcome evidence lies in the sealed FORWARD_HOLDOUT. | 63da7d3 commit date; `research/governance/research_freeze.json` | Current performance is unknown by governance. |

### 4.3 momentum: breakout continuation (live path)

[STR-07 · SOURCE_VERIFIED]
- **Identifier / version:** setup id `momentum`, name `close_above_ema20_ema50_breakout_with_volume`. Rules were introduced at 63da7d3, and selection uses `fixed_execution_quality_v1`. The runtime strategy_version is NOT VERIFIED.
- **Source:** `analyzer/simple_entry.py:detect_trade_setup` lines 28-44 @ ea8ae4f.
- **Status:** CURRENT-ACTIVE when LIVE_LEARNING_MODE is true. That flag is documented true, but its runtime value is NOT VERIFIED (STR-02 to STR-04).
- **Hypothesis:** breakouts continue in an up-trend.
- **Entry (all must hold):**
  - regime bullish (STR-09);
  - close > EMA20 > EMA50;
  - close > max(high of the prior 20 bars);
  - volume > 1.2 × mean(volume of the prior 20 bars).

  Planned entry is the last closed close.
- **Parameters:** MOM_BREAKOUT_N = 20 and MOM_VOL_MULT = 1.2. The snapshot has 20 and 1.2; effective values are NOT VERIFIED.
- **Stop:** invalidation = breakout level − 0.25·ATR14; stop = min(invalidation, entry − ATR14). The setup is rejected if risk exceeds 2/4/5/3% for 15m/1h/4h/1d.
- **Exit:**
  - targets T1 +1R (W3-capped), T2 +1.8R and T3 +2.2R;
  - partial exits of 25/50/25%;
  - net break-even after T1, a trailing stop after T2, and time stops (section 8).
- **Timeframes:** each timeframe is an independent candidate. The code default is 15m/1h/4h/1d; the snapshot has 15m/4h/1d.
- **Market-context dependencies:** a bullish per-symbol regime; the macro gate veto (STR-11); the scanner universe (section 6).
- **Indicators:** EMA20, EMA50, ATR14, the prior 20-bar high, and the prior 20-bar mean volume. The breakout and volume baselines exclude the current bar.
- **Validation evidence:** mechanics tests only (STR-24); no economic evidence (STR-25).
- **Weaknesses:**
  - the W3 cap pins T1 to the breakout bar's own wick (STR-21);
  - EMA200 is immature (STR-22);
  - a same-bar re-fire is possible after the cooldown (EXE-17);
  - calibration is hand-set (STR-23).

### 4.4 reversion: oversold bounce in a range (live path)

[STR-08 · SOURCE_VERIFIED]
- **Identifier / version:** setup id `reversion`, name `rsi_oversold_bounce_near_lower_bollinger`. Rules were introduced at 63da7d3.
- **Source:** `analyzer/simple_entry.py:54-58` @ ea8ae4f.
- **Status:** CURRENT-ACTIVE under the same flag as momentum (runtime NOT VERIFIED).
- **Hypothesis:** oversold bounces in a range.
- **Entry (all must hold):**
  - regime sideways (STR-09);
  - RSI14 < 35;
  - close > previous close;
  - close > open;
  - Bollinger %b (20, 2σ) ≤ 0.20.
- **Parameters:** REV_RSI 35 (snapshot). REV_BB_MAX_POSITION 0.20 (0.20 in `.env.example`, via the review document; 0.2 in the snapshot). Effective values are NOT VERIFIED.
- **Stop:** invalidation = min(low of the last 20 bars) − 0.25·ATR; stop = min(invalidation, entry − ATR). The same timeframe caps apply.
- **Exit:** identical target, partial, break-even, trailing and time-stop mechanics to momentum (section 8).
- **Timeframes:** as momentum.
- **Market-context dependencies:** a sideways per-symbol regime (ADX < 20 and the ATR% percentile ≤ 0.75); the macro gate veto.
- **Indicators:** RSI14, Bollinger(20, 2σ) %b, ATR, the 20-bar low.
- **Validation evidence:** mechanics tests only; no economic evidence (STR-24, STR-25).
- **Weaknesses:** the same W3 T1 cap, the same re-fire risk and the same hand-set calibration as momentum.

### 4.5 Regime routing (live path)

[STR-09 · SOURCE_VERIFIED] **Source:** `shared/regime.py:classify_regime`, lines 10-60. It was introduced at 63da7d3 and is byte-identical at ea8ae4f.
- **Rules**, applied to each symbol's own bars per timeframe:
  - **bullish:** ADX14 ≥ 25 AND the 5-bar EMA20 slope > 0 AND close > EMA20;
  - **bearish:** the mirror image;
  - **sideways:** ADX < 20 AND the 100-bar percentile of ATR/close ≤ 0.75;
  - **volatile:** everything else.
- **Routing:** momentum runs only in bullish, reversion only in sideways. Bearish and volatile produce no setup.
- **Configuration:** the rules are not env-settable and have no DB override.
- **Weaknesses:** the thresholds are hand-set (STR-23); there is no economic validation (STR-24, STR-25).

[STR-10 · DOCUMENTED_ONLY] "Validated" in the regime commit title means point-in-time and input validation, not economic validation.

### 4.6 Macro gate (live path)

[STR-11 · SOURCE_VERIFIED] **Source:** `shared/macro_context.py` lines 10-41 and 96-110. Its blob 9099d1d1 is identical at 63da7d3, ea8ae4f, bb7825f and main.
- **Block conditions.** The gate blocks **all** candidates in a cycle if any of these holds:
  - the BTC 4h change over 18 closed bars is ≤ −5% (strong_bear);
  - USDT.D minus its 3-day mean is ≥ +0.5 pp (rising_fast);
  - macro data are older than 2 h (fail-closed).
- **Mechanics:** a 1 h cache; FLAT_EPS 0.05 is hard-coded.
- **Settings:** USDTD_SPIKE_PP 0.5, MACRO_CACHE_HOURS 1, MACRO_MAX_STALE_HOURS 2. The snapshot values equal the code defaults; effective values are NOT VERIFIED.
- **Scope:** the live path only. ETH and BTC.D are stored but unused (section 5).

[STR-12 · INFERRED] The gate's CoinGecko input is not point-in-time, so the gate cannot be replayed historically. Its own value has never been tested.

### 4.7 Live ranking (live path)

[STR-13 · SOURCE_VERIFIED] **Source:** `signal_logic._fixed_candidate_key`, lines 287-293 (the A44 "production_parity" policy).
- **Sort key:** min(spread, −24h quote volume, symbol, timeframe).
- **Output:** one signal per ~60 s cycle. The key ranks execution quality, not signal strength.
- **Truncation:** `LIMIT 200` is applied after `ORDER BY symbol`, so the candidate set is truncated alphabetically.
- **Cooldown:** a 2 h symbol cooldown is hard-coded (`signal_logic.py:25`, COOLDOWN_SQL).

### 4.8 T1 cap and the W3 defect (live path)

[STR-17 · SOURCE_VERIFIED] T1_CAP_POLICY (commit a4a7561; default `legacy_window_v1`; `independent_swing_v1` = A46 G1) exists at bb7825f and on main, but not at ea8ae4f. The documented-deployed analyzer source (ea8ae4f) therefore hard-codes the T1 cap as resistance × 0.99 (`technical_analyzer.py:463-467`) and has no switch. That the running image contains this source is DOCUMENTED_ONLY, and image content is not verified (RT-16, RT-17).

[STR-21 · SOURCE_VERIFIED] **W3 defect.**
- **Mechanism:** T1 is capped at 0.99 × the 20-bar high, and that window includes the decision bar.
- **Consequences:** T1 can be pinned to the breakout bar's own wick, and it can sit below net break-even. It is not look-ahead.
- **Status:** confirmed in `docs/a45/A45_SETUP_RESEARCH.md:95`; not fixed at runtime (STR-17).
- **Affected-signal counts:** in A42 §B.3 L129-131 and A45 §A45-C (count withheld).

### 4.9 Legacy indicator-score path (inactive as a decision path)

[STR-14 · SOURCE_VERIFIED] **Score:** `legacy_score_v1`, computed by `technical_analyzer._calculate_scores` (lines 323-402 @ ea8ae4f).
- **Status:** disabled as a decision path, because `find_best_signal` runs only when LIVE_LEARNING_MODE is false. The score is still computed on every pass.
- **Score components:**
  - RSI < 30 → 1.5w; 30–40 → 1.0w; 40–50 → 0.3w;
  - Bollinger position ≤ 0.3 → w, ≤ 0.5 → w/2 (only when rsi_score ≥ 1);
  - StochRSI k < 0.2 and k > d → w;
  - RSI divergence → w;
  - Fibonacci within 1% → w, within 2% → w/2;
  - MACD, EMA cross, volume, OBV and btc_trend are fixed at 0.
- **Range:** maximum 5.5 when every w = 1.
- **Live path:** no confidence threshold.

[STR-15 · SOURCE_VERIFIED] **Legacy decision gate:** final = score + ob_score + btc_bonus + tf_bonus must reach min_score (`signal_logic.py:570-575` @ ea8ae4f; publication re-check).
- **min_score:** from `optimizer_settings` (seed 5.0), falling back to MIN_SCORE_TO_SIGNAL (code default 5; snapshot 7.0).
- **min_tf:** from `optimizer_settings`, falling back to MIN_TIMEFRAME_CONFIRMATIONS (code 2; snapshot 1).
- **Weights:** per market_condition, default 1.0.
- **Live DB values:** NOT VERIFIED.

[STR-16 · SOURCE_VERIFIED] **Legacy-only filters**, inactive on the live path:
- the 4h primary-timeframe ban (`signal_logic.py:631`); its code comment cites 275 post-rebuild trades from 2026-04-22 to 05-16;
- rejection of 1d bearish/sideways candidates whose raw total_score is ≥ 4.0 (around `:655`; the code comment cites a 2,433-trade sample with n = 251 for that cell);
- the stoch>0 gate (`:671`); its code comment records the 2026-06-23 audit (n = 2,518) as loss-reducing but still negative after fees;
- the bullish/volatile majority filters;
- `trend_ok` (EMA200);
- the BTC-crash pause (`_is_btc_crashing`);
- the BTC bonus and TF bonus;
- GLOBAL_LOSS_COOLDOWN_HOURS 6 (snapshot 0);
- MAX_SIGNALS_PER_DAY 5 (snapshot 0).

Narratives that describe these filters as live are contradicted by the code (CON-12, part B).

### 4.10 Learned gates (disabled)

[STR-18 · SOURCE_VERIFIED] **Rule** (`research/continuous_learner.py` plus the gate in `signal_logic`):
- cells are (trade_type, usdtd_trend, timeframe);
- the learner uses the newest 150 trades after 100 warm-up trades;
- net = profit% − 0.3;
- a cell is throttled if n ≥ 10 and mean + 1.96·sd/√n ≤ 0;
- a 10% hourly hash exploration still admits throttled candidates;
- LEARNING_GATES_ENABLED defaults to false.

Statistics and schema are in section 7.3.

[STR-19 · DOCUMENTED_ONLY] Learned gates are disabled. LEARNING_GATES_ENABLED is false in the snapshot, and the learner has been retired and stopped since 2026-08-17 (DEPLOYED.json; `docs/current_handoff_2026-08-17.md:13`). The runtime flag is NOT VERIFIED (LRN-20).

### 4.11 Earlier 15m/4h family (historical)

[STR-20 · SOURCE_VERIFIED] This family existed before 63da7d3 and is HISTORICAL. Its rules:
- regime from the EMA stack plus ATR > 1.5 × its average;
- reversion required close < 1.01 × BB_lower;
- StochRSI used K=14.

63da7d3 superseded it and changed StochRSI to 14/3/3. The pre-freeze historical evidence in part B refers to earlier versions, not to the current rules.

### 4.12 Dormant and proposed candidates (not on any running path)

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [STR-26 · SOURCE_VERIFIED] | A42 C1 cost-per-risk gate (`a42-sq-v1`): refuse if cost/R > 0.25, or if the T1→break-even path nets ≤ 0, at 20 bps. DORMANT: `enabled=False`, and no service imports it. | `shared/signal_quality.py` @ ea8ae4f / main | — |
| [STR-27 · DOCUMENTED_ONLY] | S5 ratings: C1 CURRENTLY_INADMISSIBLE; C2 DEFERRED. | `docs/strategy/S5_PWR_1_OWNER_DECISIONS.md` | — |
| [STR-28 · SOURCE_VERIFIED] | A42 C2 BTC-beta cap: the sum of abs(β) × notional must be ≤ 75 USDT, with β estimated from 96 bars; an unknown β counts as 1.5. Implemented as `shared/signal_quality.CorrelatedExposurePolicy(enabled=False)`, which no deployed entrypoint imports. DORMANT. | `shared/signal_quality.py` | No correlation control is active anywhere. |
| [STR-29 · DOCUMENTED_ONLY] | A42 C3 funding veto: veto momentum longs when perpetual funding is ≥ 0.03%/8h. PROPOSED, specification only; the data licence is on HOLD. | A42 specification | — |
| [STR-30 · SOURCE_VERIFIED] | A44 rankers (`shared/candidate_selection.py`: `execution_quality_v2`, `cost_per_risk_v1`) and S3 (`s3-sel-v1` plus `s3-shadow-v1`) are DORMANT. `S3Policy.enabled=False`; the sidecar runs only with `--enable` and has no Compose service. | `shared/candidate_selection.py`, S3 modules | — |
| [STR-31 · NOT_VERIFIED] | Whether the S3 shadow sidecar ever ran. | — | — |
| [STR-32 · HISTORICAL_REPORTED] | Synthetic tests show that ranking cannot change signal frequency (S3 selector work on 1,000 synthetic sets, `docs/s3/S3_SIGNAL_SELECTION.md` §3). | S3 document | Synthetic data only. |
| [STR-33 · SOURCE_VERIFIED] | A43 signal integrity is FLAGGED OFF. Enforce mode (SIGNAL_INTEGRITY_MODE=enforce) adds candle identity, ≤ 1-bar freshness and an insert-once `setup_key` (A44 signal identity eb68e42, migration 011). The default is off (`shared/config.py:118`), and Compose does not set the flag. | `shared/config.py`, `shared/signal_identity.py` @ ea8ae4f | — |
| [STR-34 · DOCUMENTED_ONLY] | The documents say no enforce window was authorized. The effective value is NOT VERIFIED (likely off). | A43/A44 documents | — |
| [STR-35 · SOURCE_VERIFIED] | A45 H1–H3 (`shared/setup_diagnostics.py`, `a45-sd-v1`, `enabled=False`). H1: momentum only if BTC's 3-day change is ≥ 0. H2: (close − prior 20-bar high)/ATR14 ≤ 0.75. H3: volume > 1.2 × the mean of the same 15m slot over 20 days, which needs about 1,921 bars when only 200 are fetched. DORMANT/RESEARCH, with 26 engineering tests. The A45 verdict is REVISE STRATEGY. | `shared/setup_diagnostics.py` | Not run on market data. |
| [STR-36 · SOURCE_VERIFIED] | A46 G1–G3 (`shared/trade_geometry.py`, `a46-tg-v1`). G1: an independent swing-high T1 cap (2-bar fractal; 1R if there is none). G2: the T1→break-even path must net ≥ 0. G3: entry = min(close, level + 0.75·ATR). DORMANT; imports `shared/strategy_math`; 27 synthetic tests. | `shared/trade_geometry.py` | — |
| [STR-37 · INFERRED] | `trade_geometry` cannot be imported in the ea8ae4f images, because `shared/strategy_math` is documented as absent there. | Reasoning from deploy records | Image contents not hashed. |

### 4.13 Research-only candidates

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [STR-38 · SOURCE_VERIFIED] | S4 mechanisms M1–M5 (`research/mechanisms`, `s4-mech-v1`): TSMOM long/cash, cross-sectional momentum, carry (not executable on Spot), a volatility overlay, and M5 = the current family. Phase-1 hypotheses: H1 is a 14-day TSMOM over a point-in-time top-20 universe; H2 is a cross-sectional top-5, weekly; H3 is the T1 cap policy (legacy vs independent swing). Status: RESEARCH-ONLY and NOT TESTED. `simulate.run` refuses to run without a DatasetPermission. | `research/mechanisms/simulate.py`; `tests/test_s4_mechanisms.py` @ main | No market evidence. |
| [STR-39 · SOURCE_VERIFIED] | Design A v1.0 (`research/design_a` and `docs/strategy/DESIGN_A_SPEC_v1.0.md`, only on `feature/design-a-v1` @ ebf8d8a): BTC/USDT goes LONG iff the latest completed Sunday daily close is above the SMA200 of 200 completed UTC daily closes; equality means FLAT. The decision is taken Monday 00:00 UTC plus 30 seconds, and the fill is at the Tuesday daily open, deferrable within 72 h with owner-approved weekly retries. The position is 100% BTC or 100% cash. Costs: 0.20%/side baseline (0.40% round trip = fee 0.10% + half-spread 0.05% + slippage 0.05%) and 0.30%/side stress (0.60% round trip). Status: RESEARCH-ONLY; 83 synthetic tests; profitability UNKNOWN; evaluation not authorized (owner decisions E1–E8 pending). | `feature/design-a-v1` @ ebf8d8a (unmerged) | Synthetic data only; outcome classification not defined. |

### 4.14 Historical research families

[STR-40 · DOCUMENTED_ONLY] Three historical families:
- **Cross-sectional momentum long/short** (`analyzer/MODEL_FROZEN_SPEC.md`): needs futures; cites an OOS Sharpe of 1.60 over one year, from a post-hoc grid (exploratory, HIS-07); 94% of its P&L came from the short leg, according to the S4 documents.
- **Funding carry:** NO-GO.
- **`analyzer/backtest_part*`** (SMC, ICT, Ichimoku and others): research-only, documented as having no edge.

Part B (sections 10–11) carries their historical results.

## 5. Market-context implementation

Code facts are SOURCE_VERIFIED at the deployed commits. The scanner blobs are equal to ea8ae4f and main for the logic shown. `shared/macro_context.py` is the same blob 9099d1d1 at 63da7d3, ea8ae4f, bb7825f and main. Whether the macro gate is active at runtime depends on LIVE_LEARNING_MODE, which is NOT VERIFIED (MKT-04).

### 5.1 Usage matrix

| Input | Provider and refresh | Formula / lookback | Stored in | Selection | Entry | Sizing | Exit | Status | IDs |
|---|---|---|---|---|---|---|---|---|---|
| BTCUSDT (scanner trend) | Binance klines, every scan (300 s), no cache | 10 closed 4h bars, Δ = (c₋₁ − c₀)/c₀ over 9 intervals = 36 h; > 3 strong_bull, > 1 bull, < −3 strong_bear, < −1 bear | `scan_candidates.data->>'btc_trend'` (1 h) | **yes**: strong_bear ⇒ 24h move must be ≥ 5% | no (legacy `_is_btc_crashing` only) | no | no | active unconditionally; fails open | MKT-01, MKT-02 |
| BTCUSDT (macro trend) | Binance 4h, at most hourly, lazily in cycles with candidates | limit 20, closed bars only, ≥ 18 required; Δ = c₋₁ vs c₋₁₈ (17 intervals = 68 h); ≤ −5 strong_bear, < −1 bear, > 5 strong_bull, > 1 bull | `macro_history.btc_trend`; `signals.macro_snapshot` | no | **yes**: strong_bear blocks the whole cycle | no | no | live path only | MKT-03, MKT-04 |
| ETHUSDT | as the macro BTC trend | same computation | `macro_history.eth_trend`; snapshot | no | no | no | no | information only | MKT-05 |
| BTC.D | CoinGecko `/api/v3/global`, at most hourly | raw market_cap_percentage.btc | `macro_history.btc_d`; snapshot | no | no | no | no | information only | MKT-06 |
| USDT.D | CoinGecko `/api/v3/global`, at most hourly | now − mean of up to 4 per-day last values since CURRENT_DATE − 3; ≥ 0.5 pp rising_fast, > 0.05 rising, < −0.05 falling, else flat | `macro_history.usdt_d`; snapshot (usdt_d, usdtd_3d_delta, usdtd_trend) | no | **yes**: rising_fast blocks the cycle | no | no | live path; also the tracker's regime-cap key | MKT-07, RSK-05 |
| BTC/ETH relative strength | — | not implemented | — | — | — | — | — | absent | MKT-08 |
| Per-symbol regime | own timeframe bars, every analysis | ADX14 / EMA20 slope / ATR% percentile (STR-09) | `analysis_results.analysis_data`; `signals.market_condition` | indirect (eligibility) | **yes** (routes setups) | no | indirect (trade type sets the stop structure) | active | MKT-09 |
| macro_state `usdtd_*` | every cycle | "usdtd_" + trend | `learned_gates.macro_state` (written only by the stopped learner) | no | inert (learned gates off) | no | no | exploration hash key only | MKT-10 |

### 5.2 Findings

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [MKT-01 · SOURCE_VERIFIED] | Scanner BTC trend (`scanner_logic._update_btc_trend`, lines 107-142): Binance klines on every scan (300 s), with no cache. It uses the last 10 closed 4h bars, Δ = (c₋₁ − c₀)/c₀ over 9 intervals = 36 h, with thresholds > 3 strong_bull, > 1 bull, < −3 strong_bear and < −1 bear. It is stored as `scan_candidates.data->>'btc_trend'` (kept 1 h). It is used for selection only: under strong_bear the 24h move must be ≥ 5%. It is not an entry input, except in the legacy `_is_btc_crashing`. It is active unconditionally. | Scanner blobs (`scanner_logic.py` blob fa03cc2a) | — |
| [MKT-02 · SOURCE_VERIFIED] | The scanner BTC trend fails open: an exception, or fewer than 10 bars, sets "neutral", which silently disables the stress filter (`scanner_logic.py:125-148`). | `scanner_logic.py` | — |
| [MKT-03 · SOURCE_VERIFIED] | Macro BTC trend (`macro_context._btc_eth_change`): Binance 4h bars, limit 20, closed bars only, at least 18 required. Δ = c₋₁ vs c₋₁₈ (17 intervals = 68 h), with thresholds ≤ −5 strong_bear, < −1 bear, > 5 strong_bull and > 1 bull. It is refreshed at most hourly (MACRO_CACHE_HOURS=1), lazily in cycles that have candidates, and stored in `macro_history.btc_trend` and `signals.macro_snapshot` (btc_change_pct, btc_trend). strong_bear blocks the whole cycle. | `shared/macro_context.py` (blob 9099d1d1) | Two BTC-trend definitions share labels (CON-27, part B). |
| [MKT-04 · DOCUMENTED_ONLY] | The macro gate is active only if LIVE_LEARNING_MODE=true (2026-09-27 snapshot). The runtime value is NOT VERIFIED (STR-04). | Snapshot files | — |
| [MKT-05 · SOURCE_VERIFIED] | ETHUSDT uses the same computation as the macro BTC trend and is stored in `macro_history.eth_trend` and the signal snapshot. `should_block` does not use it, so it is information only. | `shared/macro_context.py` | — |
| [MKT-06 · SOURCE_VERIFIED] | BTC.D: `_cg_global` reads CoinGecko `/api/v3/global` market_cap_percentage.btc (no credential) at most hourly, as a raw percentage. It is stored in `macro_history.btc_d` and the snapshot, for information only. | `shared/macro_context.py` | — |
| [MKT-07 · SOURCE_VERIFIED] | USDT.D: `_cg_global` .usdt, at most hourly. Δ = now − mean(`macro_history.usdt_d` where date ≥ CURRENT_DATE − 3), which is up to 4 per-day last values including today's previous refresh; with no rows, Δ = 0. Thresholds: ≥ 0.5 pp rising_fast, > 0.05 rising, < −0.05 falling, otherwise flat. It is stored in `macro_history.usdt_d` and the snapshot (usdt_d, usdtd_3d_delta, usdtd_trend). rising_fast blocks the cycle, and the value is also the tracker's regime-cap key (RSK-05). | `shared/macro_context.py`; `trade_tracker/main.py` | Docstring says "daily snapshot / 3-day average" (CON-28, part B). |
| [MKT-08 · SOURCE_VERIFIED] | BTC/ETH relative strength is not implemented anywhere. | Repository code | — |
| [MKT-09 · SOURCE_VERIFIED] | Per-symbol regime (`shared/regime.classify_regime` on each symbol's own timeframe bars, every analysis; rules in STR-09). It is stored in `analysis_results.analysis_data` (regime, market_condition) and `signals.market_condition`. It affects selection indirectly (eligibility) and gates entry: momentum only if bullish, reversion only if sideways (`simple_entry.detect_trade_setup`). It affects exits only indirectly (the trade type sets the stop structure) and has no sizing effect. | `shared/regime.py`; `analyzer/simple_entry.py` @ ea8ae4f | — |
| [MKT-10 · SOURCE_VERIFIED] | macro_state `usdtd_*`: `macro_state_key` builds "usdtd_" + trend every cycle. `learned_gates.macro_state` is written only by the stopped learner. With learned gates off, the key is used only for the exploration hash, so it is inert. | `signal_logic.py`; `research/continuous_learner.py` | — |
| [MKT-11 · SOURCE_VERIFIED] | Decision trace: (1) `signal_engine/main.py:main` builds `MacroContext(AsyncClient('',''))`. (2) With LIVE_LEARNING_MODE set, it calls `find_best_signal_live`. (3) That calls `macro.should_block_now()`, then `should_block(btc_trend, usdtd_trend)`. (4) A block returns None: no signal is emitted, and every candidate is marked `macro_block`. | `signal_engine/main.py`, `signal_logic.py`, `macro_context.py` @ ea8ae4f | Runtime firing frequency is unknown. |
| [MKT-12 · SOURCE_VERIFIED] | Downstream influence: sizing is fixed (TRADE_AMOUNT_USDT; the tracker never reads `size_multiplier`). A repository grep finds no macro, BTC or regime input in the tracker, the price stream, `triple_barrier`, `partial_exits`, `signal_stop` or `entry_execution`. `research/continuous_learner.py` also imports `should_block`, but that service is stopped (documented). | Repository grep @ bb7825f / ea8ae4f | — |
| [MKT-13 · SOURCE_VERIFIED] | Stale or unavailable data; the macro gate fails closed. Any CoinGecko, Binance or DB exception, or fewer than 18 closed bars, makes the refresh return False and keep the old state. The gate blocks once now − last_valid exceeds MACRO_MAX_STALE_HOURS (2 h), or when there is no valid snapshot. It retries 1 h after the last attempt, or every cycle while it has no state. CoinGecko is called with blocking urllib. | `shared/macro_context.py` | — |
| [MKT-14 · INFERRED] | Decisions can therefore use macro state up to 2 h old, built from closed 4h bars: about 6 h of signal age at worst. | Reasoning from MKT-13 | — |
| [MKT-15 · INFERRED] | Fail-open holes. (1) A missing usdt/btc key returns `.get(..., 0)` = 0.0 without an exception, so USDT.D reads "falling" (the gate passes) and the 0 is saved, polluting the next ~3 days' baseline. (2) An empty `macro_history` gives "flat". (3) Long idle periods skip refreshes. | Reasoning from the code paths | Not observed at runtime. |
| [MKT-16 · SOURCE_VERIFIED] | Other inputs fail closed. Exchange, ticker or blacklist read failures abort the scan, so there are no new candidates. Invalid, NaN or missing spread or order-book values are rejected. Missing volume ranks last. | Scanner blobs; `signal_logic.py` @ ea8ae4f | — |
| [MKT-17 · SOURCE_VERIFIED] | Active-state summary: the deployed code contains the macro gate, regime routing and the scanner BTC filter. BTC.D, ETH and BTC/ETH relative strength influence no decision, and no context input affects sizing or exits. | Code @ deployed commits | Code behaviour is SOURCE_VERIFIED only (RT-17); runtime firing is not verified. |

## 6. Asset-universe policy

The scanner's selection logic is SOURCE_VERIFIED on the scanner blobs, which equal ea8ae4f and main for `scanner_logic.py` (blob fa03cc2a); its shared config is blob c5c03b5c from 7bf6214. The engine and tracker rules are SOURCE_VERIFIED at ea8ae4f and bb7825f. Effective configured values are NOT VERIFIED.

### 6.1 Selection funnel

1. **Base universe:** Binance Spot, USDT quote, status TRADING, ASCII names, excluding only USDC/BUSD/TUSD pairs and the blacklist.
2. **Scanner filters:**
   - 24h quote volume ≥ 10,000,000 USDT;
   - absolute 24h price change ≥ 1%, or ≥ 5% when the scanner BTC trend is strong_bearish.
3. **History:** ≥ 200 bars per timeframe, with gap and duplicate checks.
4. **Analyzer intake:** 50 rows per loop.
5. **Setup routing:** regime-routed setups (section 4).
6. **Order book:** the order book must be valid, with a finite spread ≤ 0.15%.
7. **Selection query:** `ORDER BY symbol, total_score DESC LIMIT 200` over rows at most 30 min old with no open trade. This is an alphabetical truncation.
8. **Ranking:** min(spread, −volume, symbol, timeframe); one signal per ~60 s cycle.
9. **Capacity:** a 2 h symbol cooldown, one open trade per symbol, and at most 2 open positions as documented (RSK-02, RSK-03).

### 6.2 Findings

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [UNI-01 · SOURCE_VERIFIED] | Base universe (`scanner_logic._get_usdt_pairs`, `scanner_logic.py:72-81`; blob fa03cc2a, identical at ea8ae4f and main): Binance Spot exchangeInfo, quoteAsset == USDT, status == TRADING, ASCII symbol names. USDT quote only. | Scanner blobs | — |
| [UNI-02 · SOURCE_VERIFIED] | Stablecoin exclusion: only USDCUSDT, BUSDUSDT and TUSDUSDT are excluded. FDUSD, USDP, EUR, PAXG and similar pairs are not. | `scanner_logic.py` | — |
| [UNI-03 · INFERRED] | The 1% move filter usually removes the stable pairs that are not excluded. | Reasoning | Not measured. |
| [UNI-04 · SOURCE_VERIFIED] | No rule excludes leveraged ETF-style coins. | `scanner_logic.py` | — |
| [UNI-05 · SOURCE_VERIFIED] | Blacklist: `scan()` reads `SELECT symbol FROM symbol_blacklist` on every scan, before the filters, and a read failure aborts the scan. Manual controls are the Telegram commands /blacklist, /remove_blacklist and /remove_whitelist; the last one moves the symbol to the blacklist. | Scanner blobs; `telegram/main.py` @ bb7825f | — |
| [UNI-06 · NOT_VERIFIED] | Current blacklist contents; reading them needs database access, which was not authorized. | — | Authorization required. |
| [UNI-07 · DOCUMENTED_ONLY] | According to the documentation, the blacklist was emptied on 2026-05-17. | Repository documents | May have changed since. |
| [UNI-08 · SOURCE_VERIFIED] | Whitelist and approval are dead code: `telegram/whitelist.py` `ApprovalManager.process_signal` returns 'sent_direct' unconditionally (`whitelist.py:107-111`). | `telegram/whitelist.py` @ bb7825f | Contradicts the Telegram header (CON-30, part B). |
| [UNI-09 · SOURCE_VERIFIED] | Initial filters (`_passes_initial_filter`): (1) 24h quoteVolume ≥ MIN_VOLUME_USDT (default 10,000,000; `shared/config.py` c5c03b5:130; raised to 10M on 2026-04-27); (2) absolute priceChangePercent ≥ MIN_PRICE_CHANGE_PERCENT 1.0, hard-coded (:131); (3) when the scanner BTC trend is strong_bearish, the move must be ≥ 5%. | Scanner blobs; scanner `shared/config.py` | — |
| [UNI-10 · DOCUMENTED_ONLY] | The 2026-09-27 snapshot configures MIN_VOLUME_USDT 10M and SCAN_INTERVAL_SECONDS 300; effective values are NOT VERIFIED. | Snapshot files | — |
| [UNI-11 · SOURCE_VERIFIED] | No depth or size filter: walls and the bid/ask ratio feed only the unused score. There is no volatility minimum beyond the 1% move. The upper volatility bound is the stop-risk cap (15m 2%, 1h 4%, 4h 5%, 1d 3%), applied via `stop_valid=False` in `_calculate_levels`. | `technical_analyzer.py`, `orderbook_analyzer.py` @ ea8ae4f | Thin books can pass. |
| [UNI-12 · SOURCE_VERIFIED] | History and data quality: a timeframe is skipped if `len(df) < indicator_warmup_bars()` (= 200 = CANDLES_TO_FETCH; 201 klines are fetched, `technical_analyzer.py:127-134`), or if `validate_ohlcv` finds gaps or duplicates. | `technical_analyzer.py`, `shared/ohlcv.py` @ ea8ae4f | — |
| [UNI-13 · INFERRED] | Hence 1d needs at least 200 days of listing history, and 4h about 33 days. | Arithmetic from UNI-12 | — |
| [UNI-14 · SOURCE_VERIFIED] | Analyzer intake: 50 unanalysed rows per loop, newest first, at about 10 s per loop; rows are purged after 1 h. | `analyzer/main.py` @ ea8ae4f | — |
| [UNI-15 · INFERRED] | The 50-row intake is not a hard cap on coverage. | Reasoning from loop timing | Not measured. |
| [UNI-16 · SOURCE_VERIFIED] | Selection query: `signal_engine/main.py:146-155` runs `ORDER BY symbol, total_score DESC LIMIT 200` over rows ≤ 30 min old with no open trade, which is an alphabetical truncation. Not fixed (`signal_engine/main.py` around L153). | `signal_engine/main.py` @ ea8ae4f | — |
| [UNI-17 · INFERRED] | Truncation bites above about 66 symbols × 3 timeframes. How often that happens is NOT VERIFIED. | Arithmetic | Frequency requires runtime data. |
| [UNI-18 · SOURCE_VERIFIED] | Live-path ranking and caps: <br>• `_fixed_candidate_key` (STR-13); setup strength is unused. <br>• One signal per ~60 s cycle. <br>• MAX_SIGNALS_PER_DAY applies only on the legacy path (code 5, snapshot 0), so live mode has no daily cap. <br>• A 2 h symbol cooldown after any signal. <br>• One open trade per symbol: the engine excludes symbols with an open trade, and the tracker's 10% symbol cap of $500 allows one $50 trade. <br>• No correlation cap: A42 C2 is inactive (STR-28). | `signal_logic.py` @ ea8ae4f; `trade_tracker/main.py` @ bb7825f | — |
| [UNI-19 · INFERRED] | Verdict: the bot evaluates a restricted, dynamic subset, not all eligible spot pairs. <br>• Base universe: Binance Spot USDT pairs with ≥ 10M USDT 24h volume and a ≥ 1% 24h move (≥ 5% under BTC stress), minus the blacklist. <br>• Narrowed by: ≥ 200 bars per timeframe, regime-routed setups, spread ≤ 0.15%, the 200-row alphabetical cap, one signal per cycle and 2 open positions (documented capacity; code default 1, RSK-03). <br>• There is no BTC-only rule, so the design is multi-asset. <br>• Ranking by tightest relative spread, then volume, systematically favours the deepest majors (BTC/ETH-type) whenever they have a valid setup. | Synthesis of UNI-01 to UNI-18 | Coverage frequencies are not measured. |

## 7. Indicators and calibration, including learning and optimisation

Calibration classes follow the indicator investigation's codes:

| Code | Meaning |
|---|---|
| M | manual constant |
| RC | research-calibrated |
| AL | automatically learned |
| H | historical |
| CE | currently effective on the presumed live path |

Runtime-verified is **no** for every parameter (CAL-03).

### 7.1 Indicators and parameters

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [IND-01 · SOURCE_VERIFIED] | Indicator periods are plain constants (`shared/config.py:145-159`, no getenv; `technical_analyzer.py`): RSI 14; MACD 12/26/9; EMA 20/50/200; Bollinger 20, 2σ; ATR 14; StochRSI 14 / K 3 / D 3; ADX 14; volume MA 20. They are not env-settable and have no DB override; class M. RSI, EMA20/50, Bollinger and ATR feed the live triggers. | `shared/config.py` @ ea8ae4f | — |
| [IND-02 · SOURCE_VERIFIED] | Order-book analysis (`analyzer/orderbook_analyzer.py:19-110`, 20-level snapshot): a wall is ≥ 5 × the average level within 3%; bid/ask ratio thresholds are 1.5 / 1.2; a spread > 0.5% scores −0.2. The score is not part of the analyzer total_score, and the seeded `order_book` indicator weight is never read. It enters only the legacy decision sum (STR-15). On the live path the order book contributes only validity and spread. | `orderbook_analyzer.py`, `signal_logic.py:570-575` @ ea8ae4f (publication re-check) | — |
| [IND-03 · SOURCE_VERIFIED] | Spread gate: MAX_SPREAD_PCT 0.15 (`shared/config.py:165`) is a live gate in `find_best_signal_live`: the order book must be valid and spread_pct finite and ≤ 0.15. The legacy path has its own spread gate on MAX_SPREAD_PCT after the stoch>0 gate (around `signal_logic.py:675-680` at ea8ae4f); its code comment (2026-06-23 audit) calls it an execution-feasibility filter, not an edge filter. That comment belongs to the legacy gate, not to the live gate. | `signal_logic.py` @ ea8ae4f (legacy gate: publication re-check) | Effective value NOT VERIFIED. |
| [IND-04 · SOURCE_VERIFIED] | Multi-timeframe confirmation: none on the live path, where every timeframe is an independent candidate. The legacy `_get_live_thresholds` uses min_tf, which drops to 1 for a 1d bearish/sideways row scoring ≥ 3.0. MIN_TIMEFRAME_CONFIRMATIONS code default is 2 (snapshot 1); `optimizer_settings.min_timeframe_confirmations` seed is 2 (migration 003). Precedence is DB > env > default, legacy path only. | `signal_logic.py` @ ea8ae4f; migration 003 | — |
| [IND-05 · SOURCE_VERIFIED] | min_score (legacy only): `_get_live_thresholds` (`signal_logic.py:295-307`), which falls back to env on error (fail-open). MIN_SCORE_TO_SIGNAL: code default 5, `.env.example` 7, snapshot 7. `optimizer_settings.min_score_to_signal` seed 5.0. Precedence is DB > env > default. | `signal_logic.py` @ ea8ae4f | — |
| [IND-06 · DOCUMENTED_ONLY] | The documented DB value of min_score is 3.0 (`docs/claude/strategy-history.md:8`, set 2026-05-16). The live DB value is NOT VERIFIED. | `docs/claude/strategy-history.md` | Five different min_score values exist (CON-13, part B). |
| [IND-07 · SOURCE_VERIFIED] | `indicator_weights` are read through `_get_indicator_weights` (`technical_analyzer.py:482-490`) on every analysis; a missing row or read error gives 1.0. Class RC (code comments cite "240 / 262 trades") and AL (frozen optimizer output). | `technical_analyzer.py` @ ea8ae4f | Current weights NOT VERIFIED (LRN-20). |
| [IND-08 · SOURCE_VERIFIED] | Regime weights: none on the live path. `indicator_weights[market_condition]` exist only inside the legacy score. | `technical_analyzer.py` @ ea8ae4f | — |
| [IND-09 · SOURCE_VERIFIED] | Stop rule (`shared/signal_stop.py:16-46`, `plan_signal_stop`): stop = min(level − 0.25·ATR, entry − 1.0·ATR), where level = the prior 20-bar high (momentum) or the 20-bar low (reversion). A setup is rejected if risk > 2/4/5/3% for 15m/1h/4h/1d (`technical_analyzer.py:425`). `stop_valid=None` passes; only an explicit False is rejected (`signal_logic.py:784`). Not settable; the caps are class RC (the comment cites "2433 trades"). | `shared/signal_stop.py`, `technical_analyzer.py` @ ea8ae4f | — |
| [IND-10 · SOURCE_VERIFIED] | Targets (`technical_analyzer.py:454-467`): T1 1.0R, T2 1.8R, T3 2.2R. T1 is capped at 0.99 × the 20-bar high including the decision bar (W3). There is no minimum R:R and no emergency stop. T3 class RC (code comment "0/168 touched 3R", 2026-04-27); T1 and T2 class M. | `technical_analyzer.py` @ ea8ae4f | — |

**Parameter matrix.** Code defaults are SOURCE_VERIFIED; configured values are DOCUMENTED_ONLY; effective values are NOT VERIFIED unless the parameter is a hard-coded constant, in which case they equal the code subject to image parity (RT-16, RT-17).

| Parameter | Code default | Configured (`.env.example` / 2026-09-27 snapshot) | DB override | Effective | Class | IDs |
|---|---|---|---|---|---|---|
| Indicator periods | see IND-01 | not settable | none | = code | M; CE | IND-01 |
| TIMEFRAMES | 15m,1h,4h,1d | — / 15m,4h,1d | none | NOT VERIFIED | M; CE | STR-05, STR-06 |
| MOM_BREAKOUT_N / MOM_VOL_MULT | 20 / 1.2 | — / 20, 1.2 | none | NOT VERIFIED | M; CE | STR-07 |
| REV_RSI / REV_BB_MAX_POSITION | 35 / 0.20 | — and 0.20 / 35, 0.2 | none | NOT VERIFIED | M; CE | STR-08 |
| Regime thresholds | ADX 25/20; EMA20 5-bar slope; ATR% percentile ≤ 0.75 (100 bars) | not settable | none | = code | M; CE | STR-09 |
| USDTD_SPIKE_PP / MACRO_CACHE_HOURS / MACRO_MAX_STALE_HOURS | 0.5 / 1 / 2; FLAT_EPS 0.05 hard-coded | —, 1, 2 / 0.5, 1, 2 | none (`macro_history` holds data, not settings) | NOT VERIFIED | M; CE | STR-11 |
| MAX_SPREAD_PCT | 0.15 | — / 0.15 | none | NOT VERIFIED | M; CE | IND-03 |
| MIN_VOLUME_USDT / SCAN_INTERVAL_SECONDS | 10,000,000 / 300 | — and 300 / 10M, 300 | none | NOT VERIFIED | M (10M since 2026-04-27); CE | UNI-09, UNI-10 |
| Stop caps 15m/1h/4h/1d | 2/4/5/3% | not settable | none | = code | RC | IND-09 |
| T1/T2/T3 | 1.0/1.8/2.2R | not settable | none | = code | T3 RC; T1/T2 M | IND-10 |
| min_score (legacy) | 5 | 7 / 7 | `optimizer_settings` seed 5.0; documented 3.0 | legacy path only; NOT VERIFIED | RC; H | IND-05, IND-06 |
| min_tf (legacy) | 2 | — / 1 | `optimizer_settings` seed 2 | legacy path only; NOT VERIFIED | M/AL; H | IND-04 |
| indicator_weights | 1.0 per missing row | — | `indicator_weights` table | read every analysis; values NOT VERIFIED | RC; AL frozen | IND-07, LRN-16 |
| LEARNING_GATES_ENABLED / MIN_CELL_N / exploration | false / 10 / 0.10 (Compose default) | false / false; MIN_CELL_N 10 | `learned_gates` rows | inert while false; NOT VERIFIED | AL frozen | STR-18, LRN-18 |
| FEE_ROUNDTRIP_PCT / STOP_SLIPPAGE / TRADE_AMOUNT_USDT | 0.3 / 0.001 / 50 | — / 0.3, 0.001, 50 | none | NOT VERIFIED | M | EXE-12, EXE-13 |
| RISK_CANARY_MAX_OPEN_TRADES / MAX_OPEN_TRADES | 1 / 10 | `.env.example` 2 (RISK_CANARY); snapshot 2 and 10 | none | NOT VERIFIED | M | EXE-02, EXE-03, RSK-02 |

### 7.2 Calibration provenance, validation and version boundaries

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [CAL-04 · SOURCE_VERIFIED] | Parameter provenance is PARTIAL. It is spread across code comments with sample counts, `docs/claude/strategy-history.md` and commit messages. There is no parameter registry. | Code comments @ ea8ae4f; documents @ ebf8d8a | — |
| [CAL-05 · SOURCE_VERIFIED] | Calibration datasets are UNDOCUMENTED: code comments give trade counts only, with no window, symbol list, hash or cost model. | Code comments | — |
| [CAL-06 · INFERRED] | The calibration samples are in-sample bot history. | Reasoning from CAL-05 | — |
| [CAL-07 · SOURCE_VERIFIED] | Validation methodology is UNDOCUMENTED for deployed values. The A29–A34 governance documents and [EVIDENCE_LADDER_PARAMETERS.md](../../strategy/EVIDENCE_LADDER_PARAMETERS.md) are not linked to any deployed threshold. | Repository documents | — |
| [CAL-08 · DOCUMENTED_ONLY] | Version boundaries are documented for code and images: DEPLOYED.json; `deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json` (level L1, content-verified); and [VERSION_BOUNDARY.md](../../../deploy/VERSION_BOUNDARY.md), which records one boundary, VB-2026-10-27-01 (econ-enforce → econ-observe). | Deploy records | Image contents not hashed here (RT-17). |
| [CAL-09 · SOURCE_VERIFIED] | Version boundaries are weak for data. `learned_gates` rows carry strategy_version and learning_run_id, but `optimizer_settings` and `indicator_weights` have only updated_at / last_updated, so they have no lineage, history or rollback. APP_VERSION defaults to `sb-2026.06` (`shared/config.py:45`). | `database/init.sql`; `shared/config.py` @ ea8ae4f | — |
| [CAL-10 · NOT_VERIFIED] | The actual APP_VERSION / strategy_version emitted by the running services. | — | Authorization required (`.env`/DB). |

### 7.3 Learning and optimisation

The production `database/init.sql` is identical to main, so the schema facts hold for the production checkout. The contents of the learning tables were not read (LRN-20).

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [LRN-01 · SOURCE_VERIFIED] | Schemas: <br>• `learned_gates`: primary key (trade_type, macro_state, timeframe); columns n, wr, expectancy, weight, ci_low/ci_high, sample_start/sample_end, strategy_version (default 'legacy'), learning_run_id (foreign key, NOT VALID), updated_at. There is no expiry, TTL or active column. <br>• `learning_runs`: status (validating / applied / rejected / rolled_back), counts, parameters JSON, validation_errors. <br>• `learned_gate_history`: action (insert / update / expire / rollback), with old and new values as JSONB. <br>• `optimizer_settings` (key, value TEXT, updated_at): seeded with min_score_to_signal 5.0 and min_timeframe_confirmations 2, ON CONFLICT DO NOTHING. <br>• `indicator_weights`: indicator × condition, weight DEC(5,4) default 1.0, last_updated; seeded at `init.sql:219`. <br>• Migration 006 resets every gate to weight 1.0 with strategy_version `pre-statistical-reset`. | `database/init.sql`; migrations @ main / ea8ae4f | — |
| [LRN-02 · NOT_VERIFIED] | When migration 006 was applied. | — | Requires DB access. |
| [LRN-03 · SOURCE_VERIFIED] | continuous_learner (`research/continuous_learner.py`, identical at ea8ae4f and main): Compose `profiles: ["learner"]`, `restart: unless-stopped`, and a loop every LEARN_CRON_HOURS (12). Compose builds it from `signal_engine/Dockerfile` in the production working tree (63da7d3 plus local modifications), not from a pinned release image. | `docker-compose.yml` (blob d1a4b197); learner source | — |
| [LRN-04 · DOCUMENTED_ONLY] | DEPLOYED.json records the learner as exited: "stopped since 2026-08-17; must stay stopped". | [DEPLOYED.json](../../../deploy/DEPLOYED.json) | Consistent with RT-09 / RT-11. |
| [LRN-05 · INFERRED] | A learner restart would therefore run undeployed code. | Reasoning from LRN-03 and RT-07 | Hazard, not observed. |
| [LRN-06 · SOURCE_VERIFIED] | Learner data and target: <br>• Data: `trade_results` joined to `signals` where exit_time ≥ LEARNING_CLEAN_START (default 2026-07-20); the newest ROLL_N = 150 trades, after a warm-up of WARMUP_N = 100; macro_state from `macro_snapshot.usdtd_trend`. <br>• Target: per-cell net expectancy = profit_percent − 0.3. <br>• Writes: `learned_gates` (binary weight, 0 or 1), `learning_runs` and `learned_gate_history`. <br>• Clean-up: deletes throttled cells older than THROTTLE_STALE_DAYS = 14. | `research/continuous_learner.py` | Flat 0.3% cost. |
| [LRN-07 · SOURCE_VERIFIED] | Learner statistics and safeguards: <br>• A cell can be throttled only with n ≥ 10. <br>• The interval is a normal approximation, ± z·sd/√n with z = 1.96; a cell is throttled only when ci_high ≤ 0 (fail-open). <br>• There is no multiple-testing correction across up to 32 cells, and no dependence adjustment. <br>• Runtime exploration (`learning_governance.exploration_selected`) uses a blake2b hash of (symbol, type, macro state, timeframe) per UTC hour, at rate 0.10. <br>• `validate_cells` checks allowed keys, value ranges, weight ∈ {0, 1}, and that undersized cells cannot be throttled. <br>• An invalid batch is recorded as a rejected run; the apply is transactional. <br>• Rollback: `research/rollback_learned_gates.py RUN_ID` restores old_value from the history table. <br>• The code has no out-of-sample test, no holdout and no human approval. | `research/continuous_learner.py`; `learning_governance` | — |
| [LRN-08 · INFERRED] | Learner risks: <br>• A feedback loop and selection bias: it trains only on trades that passed its own gates, so throttled cells are re-sampled only via exploration or the 14-day deletion. <br>• Overlapping trades inflate the effective n. <br>• Heavy tails make the n = 10 normal interval anti-conservative. <br>• The cost model is a flat 0.3%. <br>• The runtime read does not filter on strategy_version. | Reasoning from LRN-06 and LRN-07 | — |
| [LRN-09 · SOURCE_VERIFIED] | optimizer (`optimizer/main.py`, `tuner.py`, `analyzer.py`, identical at ea8ae4f and main): disabled by Compose `profiles: ["disabled"]`; builds from the working tree; not among the DEPLOYED.json services. Data: the last 30 days of `signals` joined to `trade_results`, with signal_time ≥ 2026-04-22. It runs hourly and needs at least 10 trades. | `optimizer/*`; `docker-compose.yml` | — |
| [LRN-10 · DOCUMENTED_ONLY] | The Compose comment dates the optimizer disable to 2026-06-19. | `docker-compose.yml` comment | The date is from a comment, not a log. |
| [LRN-11 · SOURCE_VERIFIED] | `tuner.py` (writes `optimizer_settings`) uses gross win rate and average profit only: <br>• WR ≥ 55% and average profit ≥ 1.5% → min_score −0.5; <br>• WR < 30% → min_score +1.0 and min_tf +1; <br>• WR < 40% → min_score +0.5. <br>Bounds: min_score [1.5, 3.5], min_tf [1, 2]. No statistical test. | `optimizer/tuner.py` | The seed 5.0 lies outside the bounds (CON-13, part B). |
| [LRN-12 · SOURCE_VERIFIED] | `optimizer/analyzer.py` `update_indicator_weights` (writes `indicator_weights`): <br>• needs ≥ 20 samples per indicator × condition; <br>• weight = 1 + 0.5 × (mean PnL when the indicator is active − mean PnL when inactive), clamped to [0, 2.5]; <br>• an indicator that fired fewer than 20 times gets weight 0.0; <br>• rsi_divergence/sideways is pinned at 2.0. <br>It uses gross PnL, with no confidence interval and no out-of-sample test, and overwrites values in place with no history. | `optimizer/analyzer.py` | — |
| [LRN-13 · SOURCE_VERIFIED] | `colab/daily_training.py` (code from 2026-04-14, a manual notebook): needs ≥ 20 trades and ≥ 5 per condition; weight = clamp(1 + corr(indicator, win), 0.3, 2.0), written to `indicator_weights` through an external DB configuration; no significance test. HISTORICAL. | `colab/daily_training.py` | — |
| [LRN-14 · NOT_VERIFIED] | Whether `colab/daily_training.py` ever ran. | — | — |
| [LRN-15 · SOURCE_VERIFIED] | Components that are not learners: <br>• `strategy_performance_review.py`, an offline 5-fold walk-forward report; <br>• `research/null_a/*`, with no DB writes; <br>• `shared/execution_calibration.py`, research parity checks and a cost ledger, with no I/O and no runtime import. <br>The analyzer only reads weights. | Listed files | — |
| [LRN-16 · SOURCE_VERIFIED] | Runtime consumption: <br>• `indicator_weights` are read on every analysis, with no cache and no staleness check, and fully drive the legacy decision. On the live path they affect only ordering and truncation (`signal_engine/main.py:146-155`, `ORDER BY symbol, total_score DESC LIMIT 200`), plus the recorded score. <br>• `optimizer_settings` are read by `_get_live_thresholds` on the legacy path only, and displayed by telegram /status (`main.py:725-731` @ bb7825f). | `technical_analyzer.py`, `signal_engine/main.py` @ ea8ae4f; `telegram/main.py` @ bb7825f | — |
| [LRN-17 · INFERRED] | Stale, frozen learned weights therefore still steer today, marginally if the live path is active: they affect the ordering of timeframes within a symbol and the alphabetical truncation. | Reasoning from LRN-16 | Weight values NOT VERIFIED. |
| [LRN-18 · SOURCE_VERIFIED] | `learned_gates` are read through LEARNED_GATES_SQL in `find_best_signal_live` and on the enforce path (`signal_logic.py:27-28, 390-394, 741-743`; exploration 819-831), guarded by LEARNING_GATES_ENABLED. The query `WHERE macro_state=$1 AND n>=$2 AND weight<=0` has no filter on updated_at, strategy_version or run status. On a read error, enforce mode retries via `guarded_read` and then blocks the cycle; off mode aborts the cycle. | `signal_logic.py` @ ea8ae4f | — |
| [LRN-19 · INFERRED] | If LEARNING_GATES_ENABLED were ever set to true, throttles written on or before 2026-08-17 would apply immediately and indefinitely, because expiry exists only in the stopped learner. Exploration would still let about 10% through. | Reasoning from LRN-01 and LRN-18 | Depends on DB contents (LRN-20). |
| [LRN-20 · NOT_VERIFIED] | Not read: the contents of `learned_gates`, `indicator_weights` and `optimizer_settings`; whether any `learned_gates` rows exist; the runtime LEARNING_GATES_ENABLED value. | — | Authorization required. |

## 8. Entry, exit and risk model

The Paper lifecycle code is SOURCE_VERIFIED at ea8ae4f for signal generation and bb7825f for delivery, tracking and exits. The stop, target and exit `shared/*` modules are byte-identical at ea8ae4f and bb7825f. Execution is **simulated** (EXE-20). Costs are restated in part B §9.

### 8.1 Signal generation, delivery and admission

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [EXE-01 · SOURCE_VERIFIED] | Generation: the scanner writes `scan_candidates` every 300 s; the analyzer upserts `analysis_results` per (symbol, timeframe) and resets `signal_generated` on each pass. The signal_engine polls every 60 s and applies its gates in this order: <br>1. the macro gate; <br>2. a setup is present; <br>3. the order book is valid, with a finite spread ≤ 0.15%; <br>4. `stop_valid`; <br>5. no open trade, and a 2 h symbol cooldown that fails open on a DB error in off mode (`signal_logic.py:424-432`); <br>6. the learned gate (off); <br>7. rank; <br>8. one transaction inserting the `signals` row and the outbox `signal.ready` event. <br>The signal_engine has no pause check. | `signal_engine/main.py`, `signal_logic.py` @ ea8ae4f | — |
| [EXE-02 · SOURCE_VERIFIED] | Delivery: telegram `can_deliver_candidate` blocks on the pause (fail-closed) and on capacity min(10, RISK_CANARY_MAX_OPEN_TRADES), whose code default is 1. A refused candidate is acknowledged and lost. | `telegram/main.py` @ bb7825f | — |
| [EXE-03 · DOCUMENTED_ONLY] | RISK_CANARY_MAX_OPEN_TRADES is 2 in the snapshot and in `.env.example`. The effective value is NOT VERIFIED. | Snapshot; ENV_EXAMPLE review | Code default 1 vs documented 2 (CON-16, part B). |
| [EXE-04 · SOURCE_VERIFIED] | Admission: trade_tracker `register_new_signals` (`main.py:705-904`) keeps the latest signal per symbol within 2 h, with one open trade per symbol and one per (symbol, timeframe) per candle interval. The code has no flash/scalp/swing taxonomy (trade types are momentum and reversion), no one-per-kind rule, and no DB unique index enforcing one trade per symbol. | `trade_tracker/main.py` @ bb7825f | — |

### 8.2 Bars, freshness and entry

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [EXE-05 · SOURCE_VERIFIED] | Candle closure: `shared/ohlcv.py:closed_klines` keeps rows with close_time < now on the host clock. Breakout and volume baselines exclude the current bar. The order book is a single "now" snapshot, reused across timeframes. | `shared/ohlcv.py` @ ea8ae4f | — |
| [EXE-06 · INFERRED] | There is no exchange server-time sync, so host clock skew could admit a forming bar. | Reasoning from EXE-05 | Not observed. |
| [EXE-09 · SOURCE_VERIFIED] | Freshness in off mode: only two ages are checked, the 30-minute age of the analysis row and the 2 h signal window. Candle age is never checked, so a 1d bar can be about 24 h old at signal time. | `signal_engine/*` @ ea8ae4f | Enforce mode would add ≤ 1-bar freshness (STR-33). |
| [EXE-07 · SOURCE_VERIFIED] | Entry: the planned entry is the last closed close. At admission the tracker reads the REST ticker/price last trade, and `decide_long_entry` does one of three things: <br>• rejects if price ≤ max(stop, invalidation); <br>• fills at the observed price if price ≤ planned; <br>• otherwise waits (`limit_wait`, no chasing) until the 2 h window ends. <br>Fill model `observed_price_v0` is the code default; `resting_limit_v1` is off. `paper_entry_orders` rows are written but do not drive fills. `rebase_long_bracket` scales the stop and targets by fill/planned. Not modelled: bid/ask, latency, partial fills, tick/lot rounding, entry slippage. | `decide_long_entry`, `rebase_long_bracket` (tracker entry path) @ bb7825f | Optimistic touch fill (part B). |
| [EXE-08 · NOT_VERIFIED] | The effective PAPER_ENTRY_FILL_MODEL value (`.env`). | — | Authorization required. |

### 8.3 Stops, targets and time exits

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [EXE-10 · SOURCE_VERIFIED] | Stop management (`shared/triple_barrier.py`): <br>• before T1: the signal stop; <br>• after T1: a net break-even stop = min(T1, entry × 1.003/0.999) ≈ entry × 1.004 (`triple_barrier.py:92-96`), about +0.40%; <br>• after T2: a trailing stop = max(T1, peak × 0.975). <br>Stop fill = min(stop, observed tick) × 0.999, so a gap fills at the observed price −0.1%. Before T1, a closed bar at or below the invalidation level exits at the current price. There is no emergency stop. | `shared/triple_barrier.py` @ bb7825f (= ea8ae4f) | — |
| [EXE-11 · SOURCE_VERIFIED] | Targets and time exits: partial exits of 25/50/25% at T1/T2/T3 (`shared/partial_exits.py`), each filled exactly at the target price on a last-trade touch. Expiry by timeframe is in the table below. Expiry exits at the current price with no slippage. Forced closes happen on blacklisting and on max-open overflow (`enforce_max_open_trades`, `trade_tracker/main.py:508`). | `shared/partial_exits.py`, `trade_tracker/main.py` @ bb7825f (publication re-check for `:508`) | The label `T1_expired_24h` is hard-coded (CON-18, part B). |

| Timeframe | Maximum holding | Stalled after T1 | No T1 reached |
|---|---|---|---|
| 15m | 48 h | 24 h | 12 h |
| 4h | 96 h | 48 h | 24 h |
| 1d | 240 h | 120 h | 72 h |

### 8.4 Sizing, costs and P&L recording

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [EXE-12 · SOURCE_VERIFIED] | Sizing: a fixed TRADE_AMOUNT_USDT of 50 against a virtual capital of 500. There is no risk-based or volatility sizing; the tracker never reads `signals.size_multiplier`. R:R is geometric only, with no runtime R:R minimum and no cost gate. | `shared/config.py`, `trade_tracker/main.py` @ bb7825f | — |
| [EXE-13 · SOURCE_VERIFIED] | Cost constants: `shared/config.py:92` FEE_ROUNDTRIP_PCT=0.3 (described as 0.1%/side plus about 0.1% slippage); `:107` STOP_SLIPPAGE=0.001; `triple_barrier.ROUNDTRIP_COST_DEFAULT=0.003`; MIN_ORDER_NOTIONAL_USDT=5; MAX_SPREAD_PCT=0.15, used only as a selection filter. | `shared/config.py`, `shared/triple_barrier.py` | — |
| [EXE-14 · SOURCE_VERIFIED] | Cost application: `profit_percent` and `profit_usdt` are stored gross. `shared/fees.py:economic_close` (lines 41-74) charges cost_usdt = 50 × 0.3% = $0.15 flat per trade, whatever the legs, so net = gross − 0.15. Stop exits are additionally multiplied by 0.999, which A47 flags as double counting. The break-even level, risk snapshots, the learner and the Telegram reports all use 0.3. | `shared/fees.py` @ bb7825f | — |
| [EXE-15 · INFERRED] | Effective modelled cost: 0.30% round trip on target, expiry and invalidation exits, and about 0.40% on stop exits. There is no spread cost, because prices are last trades. This is below the 0.40% round-trip baseline of the owner-approved Design A cost model (STR-39), except on stops, and always below its 0.60% stress. | Reasoning from EXE-13 and EXE-14 | See part B §9. |
| [EXE-16 · SOURCE_VERIFIED] | Closure and P&L (`close_trade_barrier`, `trade_tracker/main.py:1307-1401`): <br>• gross% = Σ fraction_i·(T_i/entry − 1)·100 + remaining·(exit/entry − 1)·100; <br>• USDT = gross% × 50/100; <br>• the stored exit price is the weighted average; <br>• `result` is labelled on gross, `economic_result` on net; <br>• idempotent through ON CONFLICT (signal_id). | `trade_tracker/main.py` @ bb7825f | — |
| [EXE-17 · SOURCE_VERIFIED] | Rejected, stale and duplicate signals: <br>• an entry reject is terminal; <br>• a risk reject is retried each loop within 2 h; <br>• stale (> 2 h), blacklisted or rejected signals are acknowledged; <br>• a same-bar re-fire after the 2 h cooldown is possible for 4h/1d (A43 D1); <br>• the A43 and A38 integrity refusals apply only in enforce mode and are flagged off. <br>A38 parts active without a flag: economic labels, entry-order rows, delivery reconciliation and a 24 h notification TTL. | `trade_tracker/main.py` @ bb7825f; `signal_logic.py` @ ea8ae4f | Re-fire counts withheld (A42 §B.3, A43 §A.2). |

### 8.5 Price source and execution model

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [EXE-18 · SOURCE_VERIFIED] | Price source: the Binance WebSocket aggTrade stream (last trade) for symbols with open trades, plus a REST backup every 30 s. Reconnect uses 5–60 s backoff. The WebSocket cache is not used for decisions. | `binance_price_stream.py`, `trade_tracker/main.py` @ bb7825f | — |
| [EXE-19 · INFERRED] | When the price queue is full, the oldest tick is dropped, so barrier touches can be missed. | Reasoning from the queue design | Not observed. |
| [EXE-20 · DOCUMENTED_ONLY] | The execution model is SIMULATED on last-trade observations and has not been verified against exchange fills. A47 (`docs/a47/A47_EXECUTION_REALISM.md`) concludes "REVISE EXECUTION MODEL". A48 (`docs/a48/A48_REPLAY_FIDELITY.md:23`) establishes only level 1 (math) and level 2 (tracker parity: 6/6 in A47, 27/27 in A48); level 3, exchange realism, is not established. A42–A46 replay numbers that involve stops must not be reused. | A47 and A48 documents @ ebf8d8a (= main) | No exchange calibration exists. |

### 8.6 Risk controls and portfolio limits

| Tag | Finding | Source · symbol · commit | Limitations |
|---|---|---|---|
| [RSK-01 · SOURCE_VERIFIED] | Risk gate (`evaluate_with_policy`, via `assess_new_trade_risk` at `main.py:922-1006` and `record_risk_decision` at 1041-1093). <br>• Always blocking: invalid risk state, a persisted pause, and the exposure caps (gross 80%, symbol 10%, strategy 40%, regime 50%). <br>• Observe mode: the daily −3%, weekly −10%, drawdown 15% and 7-loss-streak checks are only recorded as `risk.observed` (`observed:<check>`). <br>• Enforce mode: the same checks write a `risk:` pause. <br>In observe mode, invalid_risk_state is the only check that still writes a pause. A NaN price gives invalid_risk_state. Observe requires PAPER_TRADING=true, and an unknown mode falls back to enforce (`shared/economic_halt_policy.py:89-98`). | `trade_tracker/main.py`, `shared/economic_halt_policy.py` @ bb7825f | Observe is configured (RT-32); the executing path is NOT VERIFIED (RT-33). |
| [RSK-02 · SOURCE_VERIFIED] | Capacity: min(MAX_OPEN_TRADES 10, RISK_CANARY_MAX_OPEN_TRADES), also bounded by floor(500 × 80% / 50) = 8. Economic-halt sizing multipliers (drawdown caution/warning, weekly reduce/minimum) do not change the notional, but they can lower the capacity used by the max_open_trades check (`shared/economic_halt_policy.py:18-20`). The tracker's open-trade capacity checks are at `trade_tracker/main.py:708-716` and `:752-756` (bb7825f). | `shared/economic_halt_policy.py`, `trade_tracker/main.py` @ bb7825f (publication re-check) | — |
| [RSK-03 · DOCUMENTED_ONLY] | Effective capacity is 2 open positions, or 1 when the sizing multiplier is ≤ 0.5 (as cited from `docs/ops/PAPER_ECONOMIC_OBSERVATION.md`). | Operations document | Effective flag values NOT VERIFIED. |
| [RSK-04 · INFERRED] | The strategy (40%) and regime (50%) caps correspond to 4 and 5 trades, so they never bind with 2 slots. | Arithmetic from RSK-01 and RSK-03 | — |
| [RSK-05 · SOURCE_VERIFIED] | The regime-cap key is `COALESCE(macro_snapshot->>'usdtd_trend', market_condition)`, which flows through `assess_new_trade_risk` → `regime_open_count` → `evaluate_new_trade` → regime_concentration_limit. Per `economic_halt_policy.PORTFOLIO_LIMITS`, this portfolio limit blocks even in observe mode. | `trade_tracker/main.py`, `shared/economic_halt_policy.py` @ bb7825f | — |
| [RSK-06 · INFERRED] | Capital utilisation is at most 20% (2 × $50 of $500 virtual capital). | Arithmetic from EXE-12 and RSK-03 | Depends on the documented capacity of 2 (RSK-03, NOT VERIFIED); with the code default of 1 it would be 10%; the arithmetic bound is 8 positions. |

## 9. Cost and execution assumptions

Every number in this section is a modelled assumption recorded in code or in a document. None is a measured execution cost, because the audit observed no exchange fill. The runtime cost code is SOURCE_VERIFIED only at the commits documented as deployed: image content parity is DOCUMENTED_ONLY (RT-16), and the image filesystems were not read (RT-17).

### 9.1 Runtime Paper cost model

The table restates EXE-13, EXE-14 and EXE-15, which are tagged earlier in this pack.
- **Commits:** code was read at ea8ae4f (analyzer, signal_engine) and bb7825f (telegram, trade_tracker). The shared stop, target and exit modules are byte-identical at both commits.
- **Observed:** n/a. **Runtime-verified:** no.

| Element | Value | Source · symbol | Class (ID) |
|---|---|---|---|
| Round-trip cost constant | `FEE_ROUNDTRIP_PCT=0.3`, which the code describes as 0.1%/side plus about 0.1% slippage | `shared/config.py:92` | SOURCE_VERIFIED (EXE-13) |
| Stop slippage | `STOP_SLIPPAGE=0.001` | `shared/config.py:107` | SOURCE_VERIFIED (EXE-13) |
| Barrier default | `ROUNDTRIP_COST_DEFAULT=0.003` | `shared/triple_barrier.py` | SOURCE_VERIFIED (EXE-13) |
| Minimum order notional | `MIN_ORDER_NOTIONAL_USDT=5` | listed with the cost constants | SOURCE_VERIFIED (EXE-13) |
| Spread | `MAX_SPREAD_PCT=0.15` is a selection filter only; no spread cost is charged | `shared/config.py:165`; `find_best_signal_live` | SOURCE_VERIFIED (EXE-13) |
| Stored P&L | `profit_percent` and `profit_usdt` are stored gross | `close_trade_barrier`, `trade_tracker/main.py:1307-1401` | SOURCE_VERIFIED (EXE-14) |
| Net charge | `cost_usdt` = 50 × 0.3% = $0.15 flat per trade, whatever the number of exit legs; net = gross − 0.15 | `shared/fees.py:economic_close`, lines 41-74 | SOURCE_VERIFIED (EXE-14) |
| Stop fills | Stop exits are also multiplied by 0.999, which A47 flags as double counting (CON-17, HIS-31) | `shared/triple_barrier.py` | SOURCE_VERIFIED (EXE-14) |
| Other users of 0.3 | The break-even level, risk snapshots, the learner and the Telegram reports all use 0.3 | several modules | SOURCE_VERIFIED (EXE-14) |
| Effective modelled cost | 0.30% round trip on target, expiry and invalidation exits; about 0.40% on stop exits; no spread cost, because prices are last trades | derived from the rows above | INFERRED (EXE-15) |

EXE-15 also gives the comparison that matters for any economic reading. The effective runtime cost is:
- below the 0.40% round-trip baseline of the owner-approved Design A cost model, except on stop exits;
- always below that model's 0.60% stress case (HIS-16, section 9.3).

### 9.2 Execution-model realism

EXE-20 (DOCUMENTED_ONLY, tagged earlier in this pack) classifies the Paper execution model as **simulated on last-trade observations and not verified against exchange fills**:
- A47 (`docs/a47/A47_EXECUTION_REALISM.md`) concluded "REVISE EXECUTION MODEL".
- A48 (`docs/a48/A48_REPLAY_FIDELITY.md:23`) establishes only level 1 (math) and level 2 (tracker parity: 6/6 in A47, 27/27 in A48). Level 3, exchange realism, is not established.
- A42–A46 replay numbers that involve stops must not be reused.

The simulated mechanics behind that classification are SOURCE_VERIFIED at bb7825f and are restated here from earlier sections.

**Entry (EXE-07).**
- The planned entry is the last closed close.
- At admission the tracker reads the REST ticker/price last trade. It then:
  - rejects the trade if price ≤ max(stop, invalidation);
  - fills at the observed price if price ≤ planned;
  - otherwise waits, without chasing, until the 2 h window ends.
- Fill model `observed_price_v0` is the code default and `resting_limit_v1` is off. The effective value is NOT VERIFIED (EXE-08).
- Not modelled: bid/ask, latency, partial fills, tick/lot rounding and entry slippage.

**Exits (EXE-10, EXE-11).**
- Targets fill exactly at the target price on a last-trade touch.
- Expiry exits at the current price with no slippage.
- Stop fill = min(stop, observed tick) × 0.999, so a gap fills at the observed price −0.1%.

**Price feed (EXE-18, EXE-19).**
- Prices come from the Binance WebSocket aggTrade stream for symbols with open trades, plus a REST check every 30 s.
- The WebSocket cache is not used for decisions.
- When the price queue is full, the oldest tick is dropped, so barrier touches can be missed (INFERRED).

**Known direction of bias (HIS-32, section 11).**
- The replay stop fill at the level and on gaps is optimistic.
- Same-bar stop-first is pessimistic by up to 3.5 pp.
- The Paper touch fill `observed_price_v0` is optimistic.

### 9.3 Research cost models

- [HIS-15 · SOURCE_VERIFIED] **S4 mechanism cost model** (M1–M5 and Phase-1 H1–H3).
  - Components: fee 0.10%/side; half-spread 0.01% for BTC/ETH and 0.04% for other symbols; slippage 0.05%/side; ×2 stress.
  - Planned data: 2019–2022, plus 2023-01 → 2026-08-18.
  - No trades have been run. The family is NOT TESTED, because the code refuses non-synthetic data.
  - Evidence: `docs/strategy/S4_MECHANISM_COMPARISON.md` §3; `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md` §4-6; `research/mechanisms/simulate.py`; `tests/test_s4_mechanisms.py`. Read at ebf8d8a; the content is identical on main.
  - Observed: n/a. Runtime-verified: no. Limitation: no market result exists.
- [HIS-16 · SOURCE_VERIFIED] **Design A v1.0 cost model.**
  - Baseline: 0.20%/side, i.e. 0.40% round trip (fee 0.10% + half-spread 0.05% + slippage 0.05%).
  - Stress: 0.30%/side, i.e. 0.60% round trip.
  - Synthetic data only; no performance was computed; 83 tests; profitability UNKNOWN. The outcome classification is "NOT DEFINED" (SPEC §17).
  - Evidence: `docs/strategy/DESIGN_A_SPEC_v1.0.md` §0, §10, §20 and `docs/strategy/DESIGN_A_V1_EVIDENCE.md`, on `feature/design-a-v1` @ ebf8d8a (not on main).
  - Observed: n/a. Runtime-verified: no.
  - Limitation: its 0.05% half-spread conflicts with the S4 value for BTC/ETH (0.01%) (CON-45).
- **Historical study costs** (restated; the rows are in section 10).
  - HIS-01 used 0.3% round trip on $50 notional, with no slippage term (RP L149).
  - HIS-08 used 0.3%.
  - HIS-09 to HIS-12 used 0.30% round trip including about 0.1% slippage, plus 0.1% stop slippage and a 0.15% spread cap (P4 L27-31).
  - HIS-03 to HIS-07 and HIS-14 do not state their costs.
  - The learner's target is profit% − 0.3 (LRN-06), and the walk-forward scripts use a flat 0.30% (HIS-38).
  - The A48 research ledger `a48-cost-v1` corrects the stop double count (HIS-17, HIS-31).

### 9.4 Owner cost and reporting standard

- [ECO-09 · DOCUMENTED_ONLY] The [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md) §1 sets these rules:
  - **Costs:** conservative standard spot fees of 0.10% per side (0.20% round trip), independent of account discounts, plus spread, slippage and other realistic execution costs.
  - **Reporting:** gross and net results, turnover, drawdown, sample sizes, regimes, uncertainty and failure cases.
  - **Claims:** no profitability may be asserted without credible prospective independent evidence.
  - Evidence: `docs/governance/OWNER_OPERATING_CONTRACT.md` §1 @ eba90dd, read at publication.
  - Observed: n/a. Runtime-verified: no. Limitation: this is a governance standard, not a measurement.

### 9.5 Comparison of the recorded cost models

| Model | Fee | Spread | Slippage | Stop treatment | Round trip as recorded | Status · class |
|---|---|---|---|---|---|---|
| Runtime Paper tracker (EXE-13, EXE-14, EXE-15) | inside `FEE_ROUNDTRIP_PCT` 0.3 (0.1%/side) | none charged (last-trade prices) | about 0.1% inside the 0.3 | extra × 0.999 on stop fills (double count) | 0.30% flat ($0.15 on $50); about 0.40% on stops | code SOURCE_VERIFIED; effective cost INFERRED; runtime NOT VERIFIED (RT-17) |
| Learner target (LRN-06) | flat 0.3 | — | — | — | 0.30% | SOURCE_VERIFIED; learner stopped |
| Walk-forward scripts (HIS-38) | flat 0.30% | — | — | — | 0.30% | SOURCE_VERIFIED; open defect |
| Pre-freeze Paper audit (HIS-01) | 0.3% round trip on $50 | — | no slippage term | — | 0.30% | HISTORICAL_REPORTED |
| Phase 3–9 studies (HIS-09 to HIS-12) | 0.30% round trip including about 0.1% slippage | 0.15% spread cap, used as a filter | about 0.1% | plus 0.1% stop slippage | 0.30%, plus 0.1% on stop exits | HISTORICAL_REPORTED |
| A48 research ledger `a48-cost-v1` (HIS-17, HIS-31) | — | — | — | stop double count corrected | not stated in the audit sources | research only |
| S4 mechanisms (HIS-15) | 0.10%/side | half-spread 0.01% BTC/ETH, 0.04% others | 0.05%/side | — | not stated as a total; ×2 stress | SOURCE_VERIFIED; NOT TESTED |
| Design A v1.0 (HIS-16) | 0.10%/side | half-spread 0.05% | 0.05%/side | — | 0.40% baseline; 0.60% stress (0.30%/side) | SOURCE_VERIFIED on the feature branch; synthetic only |
| Owner standard (ECO-09) | 0.10%/side (0.20% round trip) | plus spread | plus slippage | plus other realistic execution costs | 0.20% plus execution costs | DOCUMENTED_ONLY |

### 9.6 What the comparison shows

These points restate existing findings only.
- The runtime Paper cost is below the Design A baseline except on stops, and always below its stress case (EXE-15).
- Operational counters are gross (ECO-03). `risk_management` wins/losses and /status use gross labels, while /stats uses net labels (CON-09).
- `FEE_ROUNDTRIP_PCT` already includes slippage, and stop exits add `STOP_SLIPPAGE` again (CON-17, HIS-31).
- No runtime cost component represents the bid/ask spread (EXE-13).
- The research specifications disagree on the half-spread (CON-45).
- The owner standard asks for turnover, but no study reports turnover (HIS-19).

## 10. Historical economic evidence

Read this section under four constraints:
1. **Historical, not recomputed.** Every figure is HISTORICAL_REPORTED unless tagged otherwise. It comes from a past report or decision record and was not recomputed in this audit (PD-02).
2. **Not about the current rules.** No figure describes the current momentum and reversion rules. Those rules came in at 63da7d3, which is dated on the research-freeze date (2026-08-19) and precedes the recorded freeze boundary (FORWARD_HOLDOUT, recorded in `research/governance/research_freeze.json`). All their outcome evidence therefore lies in the sealed holdout (STR-25, GOV-04).
3. **Nothing post-freeze.** No post-freeze outcome, count or timestamp is reproduced. Counts whose data window was not verified to precede the freeze are withheld, and a pointer to the cited section is given instead.
4. **No profitability claim.** The Owner Operating Contract treats the headline Paper result as "historical review evidence, not a current profitability claim" (HIS-02).

**Traceability for every row in this section.**
- Documents were read at ebf8d8a; except for the Design A documents (HIS-16, HIS-43), which exist only on `feature/design-a-v1`, their content equals main eba90dd. The audit report is tracked at 977746f.
- Observed: n/a. Runtime-verified: no. Not recomputed.

**Abbreviations.**

| Abbreviation | Document |
|---|---|
| RP | [research/skill_application/out/REPORT.md](../../../research/skill_application/out/REPORT.md) |
| SH | `docs/claude/strategy-history.md` |
| DL | `DEV_LOG.md` |
| P1 | `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md` |
| RM | `docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md` |
| ELP | [docs/strategy/EVIDENCE_LADDER_PARAMETERS.md](../../strategy/EVIDENCE_LADDER_PARAMETERS.md) |
| P3–P9 | `docs/phaseN_*_2026-08-17.md` |
| A4x | `docs/a4x/A4x_*.md` |
| OOC | Owner Operating Contract |
| DFP | Development-First Policy |

### 10.1 Headline result: the pre-freeze Paper audit

- [HIS-01 · HISTORICAL_REPORTED] **Live Paper audit** (RP, commit 977746f, dated 2026-06-23, before the freeze).
  - **Sample:** 2,518 closed Paper trades from 2026-04-09 to 2026-06-21, 93% of them in April, on pre-freeze strategy versions (the 15m/4h score strategy).
  - **Costs:** 0.3% round trip on $50 notional, with no slippage term (RP L149).
  - **Results:**
    - gross PF 0.735 → net PF 0.598;
    - expectancy −$0.2147 gross → −$0.3647 net per trade;
    - maximum drawdown −$940 (L81);
    - purged walk-forward AUC 0.469 / 0.458;
    - permutation p = 1.0;
    - 0 of 35 filters survive FDR; the stoch gate and COMBO fail out of sample.
  - **Data:** the discovery partition, which is contaminated (`docs/research_temporal_governance.md` §Partitions).
  - **Verdict:** NO EDGE.
  - Evidence: RP L1-3, §1 L11, L81 and L149 @ 977746f. The report, its JSON outputs and its scripts are tracked (HIS-20).
  - Limitations: not recomputed; pre-freeze versions only, not the current rules; contaminated discovery data.
- [HIS-02 · DOCUMENTED_ONLY] The [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md) §4 (L32) calls the gross PF 0.735 on 2,518 Paper trades "historical review evidence, not a current profitability claim". SH L12 restates it.
  - Evidence: `docs/governance/OWNER_OPERATING_CONTRACT.md` §4 @ eba90dd; SH L12.
  - Limitation: a governance classification of existing evidence, not a new measurement.

### 10.2 Study register

The register numbers (#) follow the history investigation's register. Turnover is reported by no study (HIS-19).

| ID · class | # | Study · source | Costs | Data · contamination | Gross → net | WF / OOS | n | Verdict |
|---|---|---|---|---|---|---|---|---|
| [HIS-01 · HISTORICAL_REPORTED] | 1 | Live Paper audit, 15m/4h score strategy · RP §1-3 | 0.3% round trip, no slippage term | 2026-04-09 → 06-21; discovery partition, contaminated | PF 0.735 → 0.598; E −$0.2147 → −$0.3647; max DD −$940 | purged WF AUC 0.469 / 0.458; permutation p = 1.0; 0/35 filters survive FDR; stoch gate and COMBO fail OOS | 2,518 | NO EDGE |
| [HIS-03 · HISTORICAL_REPORTED] | 2 | Per-indicator subset · P1 L13 | not stated | to 06-07; overlaps #1 | gross PF 0.734; AUC ≈ 0.50 | — | 2,461 | negative |
| [HIS-04 · HISTORICAL_REPORTED] | 3 | A58 pre-freeze H0 · P1 L14 | not stated | 04-09 → 08-19; mixed versions | PF 0.729 → 0.593; day-clustered t = −2.69 | — | 3,401 | negative; session report not in the repository |
| [HIS-05 · HISTORICAL_REPORTED] | 4 | 9-year target/exit arms · SH L13; P1 L15 | not stated | 595 coins, 2017–2026, including delisted coins; research-exposed | every arm × year gross-negative | — | about 110k | "entry is the flaw" |
| [HIS-06 · HISTORICAL_REPORTED] | 5 | Daily ML, XGBoost on TA + Ichimoku + ICT features · SH L14; P1 L17 | not stated | not stated | edge only in coins under $1M; 6 months produced 99% of the net; −1.09%/yr | not stated | not stated | NO-GO |
| [HIS-07 · HISTORICAL_REPORTED] | 6 | Cross-sectional momentum long/short, weekly · P1 L16 | not stated | 250 coins, 2023–2025; post-hoc grid | cites an OOS Sharpe of 1.6 over one year from a post-hoc grid (exploratory); 94% of PnL from the short leg, which Spot cannot execute | 1 year | not stated | exploratory |
| [HIS-08 · HISTORICAL_REPORTED] | 7 | EMA/round-number filter · `research/entry_filter_causal_test_2026_05_20.md` L2, L55-67 | 0.3% | 37 symbols, Feb–May 2026 | net difference +1.06%, p = 0.018 | split halves p = 0.894 / 0.009 | 4,120 | NOT_PREDICTIVE |
| [HIS-09 · HISTORICAL_REPORTED] | 8 | Phase 3 entry hypotheses · P3 L10-44 | 0.30% round trip including about 0.1% slippage; plus 0.1% stop slippage; 0.15% spread cap (P4 L27-31) | clean Paper cohort sb-2026.08, 2026-07-20 → 08-17; the same sample is reused in #8–#11 (HIS-13) | momentum E +0.123% / PF 1.10; reversion −0.016% / 0.98; CIs contain 0; a "volatile" cell at +0.862% is post-hoc; raw-price mean reversion 0/135 | none | 162 / 144 | NO-GO |
| [HIS-10 · HISTORICAL_REPORTED] | 9 | Phase 5 expanding walk-forward · P5 L5-25 | as #8 | as #8 | OOS E +0.046%, PF 1.05, CI contains 0; learned gates equal the baseline | 5 folds, purge plus 48 h embargo; 2 of 5 positive | 185 | NO-GO |
| [HIS-11 · HISTORICAL_REPORTED] | 10 | Phase 6 portfolio · P6 L5-40 | as #8 | 25 exit days | E +0.056%, PF 1.06, MDD 3.56% (cash curve, not mark-to-market); PF 0.88 without the top 5 | none | 307 | "real risk 0" |
| [HIS-12 · HISTORICAL_REPORTED] | 11 | Phase 9 review · P9 L8-36 | as #8 | as #8 | E +0.362% / PF 1.45 → +0.062% / 1.06; drawdown 19.41 / 49.09 pp | WF +0.033%, 2 of 5 folds | 303 | unproven |
| [HIS-14 · HISTORICAL_REPORTED] | 12 | Canary Phase A-R2 · `docs/canary_state.md` L8-22, written 2026-09-27 at 970dda9 | not stated | to 2026-07-06; spans two policies | net PF 1.126, p = 0.65; negative without the top 3 | none | 88 | REFUTED |
| [HIS-15 · SOURCE_VERIFIED] | 13 | S4 M1–M5 / H1–H3 · `docs/strategy/S4_MECHANISM_COMPARISON.md` §3; P1 §4-6 | fee 0.10%/side; half-spread 0.01% BTC/ETH, 0.04% others; slippage 0.05%/side; ×2 stress | planned 2019–2022 plus 2023-01 → 2026-08-18 | none | — | 0 | NOT TESTED |
| [HIS-16 · SOURCE_VERIFIED] | 14 | Design A v1.0 · DESIGN_A_SPEC_v1.0 §0, §10, §20; DESIGN_A_V1_EVIDENCE (`feature/design-a-v1`) | 0.20%/side; stress 0.30%/side | synthetic only | none computed | — | 83 tests | profitability UNKNOWN |
| [HIS-17 · HISTORICAL_REPORTED] | 15 | A47/A48 replay calibration · A48 §A48-D/E | `a48-cost-v1` | synthetic | tracker parity 27/27; the legacy model is optimistic in 127/127 cells | — | — | READY FOR SCIENTIFIC DESIGN REVIEW |

Reading notes, which restate the register:
- Rows #8 to #11 use the same cohort; see HIS-13 below.
- The rows with net-positive real-data figures are #8 (momentum), #9, #10, #11 and #12; section 12 sets out why none of them establishes an edge (HIS-42).
- Rows #13 and #14 contain no market result.
- Row #15 is a calibration of the simulator, not a strategy result.

- [HIS-13 · INFERRED] Phases 3, 5, 6 and 9 reuse one sample, the 2026-07-20 → 08-17 clean Paper cohort.
  - Evidence: P3, P5, P6 and P9 all describe that cohort (history investigation, register rows 8–11).
  - Limitation: this is an inference from the documents' stated windows, not a check of their trade lists.

### 10.3 Engineering-only work

- [HIS-18 · HISTORICAL_REPORTED] The following is engineering work, none of it market evidence:
  - the S3 selector on 1,000 synthetic sets (`docs/s3/S3_SIGNAL_SELECTION.md` §3);
  - the P0R replay with metrics suppressed (`docs/phase2a_p0r_runtime_contract.md` §13-16);
  - data certification FAIL across 596 symbols (`docs/phase16_data_completion.md`).

### 10.4 Verification status of the historical evidence

- [HIS-19 · NOT_VERIFIED] No study reports turnover, so the owner standard's turnover requirement (ECO-09) cannot be checked for any of them.
- [HIS-20 · SOURCE_VERIFIED] Which claims are backed by tracked artefacts:
  - **Backed by tracked artefacts:**
    - HIS-01 (the report, its JSON outputs and its scripts);
    - HIS-15 (the code refuses non-synthetic data: `research/mechanisms/simulate.py`, `tests/test_s4_mechanisms.py`);
    - HIS-16 and HIS-17 (their tests are tracked);
    - the A42–A48 verdicts (each document's final section);
    - `research/governance/research_freeze.json`.
  - **Historical claims only:**
    - HIS-03 to HIS-07, and HIS-14;
    - Phases 3–9: the generators `research/{entry_hypothesis,walk_forward,portfolio,strategy_performance}_review.py` are tracked, but their outputs are not;
    - HIS-06 and HIS-08: scripts only;
    - legacy DEV_LOG results;
    - the A43 defect counts;
    - the A29–A41 packages, held only in local commit 54a6369 (ELP §1).
- [HIS-21 · NOT_VERIFIED] The A29–A41 packages and the A58 session report cannot be verified from the repository.

### 10.5 The production checkout's copy of the evidence

- [HIS-45 · RUNTIME_VERIFIED] Observed in the production checkout on 2026-10-31:
  - All 27 docs/research Markdown files there exist in main. Seven differ, including the phase3 review; `strategy-history` is identical.
  - The checkout lacks ea8ae4f, bb7825f and 54a6369, so the source documented as deployed cannot be reproduced there.
  - Evidence: host git state, Class A read-only (RT-01 to RT-05).
  - Limitation: whether the seven differing files change any conclusion was not assessed.

### 10.6 Version lineage and what it implies for the evidence

- [HIS-46 · INFERRED] The versions follow this lineage (a synthesis of STR-20, HIS-09, STR-25, RT-09 and CAL-08):
  1. the earlier 15m/4h family and the legacy score path, with optimizer/colab weights (2026-04 to 06);
  2. the clean Paper cohort sb-2026.08 (2026-07-20 → 08-17);
  3. the current momentum/reversion setups with regime routing, introduced at 63da7d3 (2026-08-19);
  4. release images built from ea8ae4f for analyzer and signal_engine (created 2026-10-16, running since 2026-10-19);
  5. release images built from bb7825f for telegram and trade_tracker in observe mode (created 2026-10-27; boundary VB-2026-10-27-01).
- What this implies, restated:
  - No study in section 10.2 evaluates the current rules (STR-25).
  - HIS-09 to HIS-14 predate the gap-through stop fix c4a623c (HIS-35).
  - HIS-09 to HIS-12 predate the 63da7d3 indicator changes (HIS-36).
  - A42, A45, A46 and A47 analysed 59297305, not the deployed ea8ae4f (CON-21).
- Detail: [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md).

## 11. Failed directions and known defects

### 11.1 Failed or inconclusive hypotheses

**Traceability for this subsection.**
- Documents were read at ebf8d8a (equal to main for these paths). Commit messages were read from git history.
- Observed: n/a. Runtime-verified: no. Not recomputed.

- [HIS-22 · HISTORICAL_REPORTED] **SMC.** The only record is two commit messages:
  - 518e286: "Part 35 SMC Advanced V3 — 0/4 features pass FDR";
  - 2ad42bd: "0/18 features survive".
  - Scripts: `analyzer/part35_smc_advanced_v3.py`, `analyzer/backtest_part37_smc_advanced_ohlc.py` and `research/skill_application/scripts/smc_backtest.py`.
  - There is no result document.
- [HIS-23 · NOT_VERIFIED] No committed record exists for:
  - the LuxAlgo-faithful SMC port;
  - the falling-wedge study;
  - a volume+RSI MTF result (`analyzer/backtest_volume_rsi_mtf.py` exists but has no result document);
  - a standalone Ichimoku study (Ichimoku appears only as ML features, SH L14).
- [HIS-24 · HISTORICAL_REPORTED] **Other failed directions.**
  - **Pre-freeze audit tests (RP §2, L128):** indicator AUC ≈ 0.50, the stoch gate, COMBO, the MR filter, Kelly sizing, regime exits and ATR exits all failed.
  - **The EMA/round-number filter** failed (HIS-08).
  - **Phases 3–6:** momentum/reversion entry, raw-price mean reversion, learned gates, regime selection and top-N robustness all failed. The verdicts are in the P3 decision section, the P5 results section and the P6 concentration-test section.
  - **The canary reversion edge** was refuted (`docs/canary_state.md` L14-19).
  - **The 9-year target policy** failed (SH L13).
  - **The aggregate live walk-forward edge** was a FAIL on 2026-06-23 (header of `research/walk_forward_audit.sh`).
  - **Weight tuning** is frozen (SH L8), and the DEV_LOG claim of its success is contradicted (CON-48).
- **Related historical families** (STR-40, restated):
  - Cross-sectional momentum long/short (`analyzer/MODEL_FROZEN_SPEC.md`) needs futures. It cites an OOS Sharpe of 1.6 over one year from a post-hoc grid (exploratory; recorded as 1.60 in the model specification), and 94% of its P&L came from the short leg.
  - Funding carry is NO-GO.
  - The `analyzer/backtest_part*` studies (SMC, ICT, Ichimoku and others) are research-only and documented as having no edge.
  - Daily ML is NO-GO (HIS-06).

### 11.2 Known defects affecting the evidence or the runtime

**Traceability for this table.**
- Code facts are SOURCE_VERIFIED at ea8ae4f (analyzer, signal_engine) or at bb7825f/main where stated. Documents were read at ebf8d8a.
- Observed: n/a. Runtime-verified: no for every row, because no code behaviour is runtime-verified (RT-17).
- Counts marked "withheld" are not reproduced, because their data window was not verified to precede the research freeze.

| ID · class | Defect | Described in | Fixed? Where | Limitations / links |
|---|---|---|---|---|
| [HIS-25 · SOURCE_VERIFIED] | 4h/1d same-candle re-fire: the cooldown is shorter than the bar, which inflates n | A42 §B.3 L123-127; A43 §A.2 L45 (counts withheld) | Fixed only under `SIGNAL_INTEGRITY_MODE=enforce`, default off: A44 signal identity plus insert-once (eb68e42, migration 011). A44 §A44-G says "not deployed". | runtime mode NOT VERIFIED (RT-47) |
| [HIS-26 · SOURCE_VERIFIED] | Duplicate trades for a small number of setups; superseded emissions | A43 §A.2 L46-47 (count withheld) | handled only in enforce mode | as HIS-25 |
| [HIS-27 · SOURCE_VERIFIED] | The cooldown fails open; NaN spread/volume | A43 §A.2 L48-50 | Partly fixed. The NaN-spread fix ddb6bcd (`finite_spread_pct`) is in ea8ae4f, but the off path still returns `set()` on a cooldown read error (`signal_logic.py:432`). | CON-32 |
| [HIS-28 · SOURCE_VERIFIED] | Alphabetical `LIMIT 200` and lexical tie-breaks: a selection bias | A43 §A.2 L51-52 | NOT fixed (`signal_engine/main.py` around L153) | how often truncation happens is NOT VERIFIED (UNI-17) |
| [HIS-29 · DOCUMENTED_ONLY] | Cost/R gate on a fixed $50 notional; no cost coverage in production | A42 §B.1 L109-113; S3 §1 row 4 | C1 (≤ 0.25R) is specified only; the S3 cap is disabled | STR-26, STR-27 |
| [HIS-30 · SOURCE_VERIFIED] | W3 T1 self-reference. The T1 cap uses a window that includes the breakout bar's own high. This is not look-ahead, but T1 can sit below net break-even. | A42 §B.3 L129-131; A45 §A45-C; A46 §A46-C (counts withheld) | Not fixed in runtime. G1 is dormant, the default is `legacy_window_v1` (`shared/config.py:124` at bb7825f and main), and a4a7561 is not in ea8ae4f. | STR-17, STR-21, CON-33 |
| [HIS-31 · SOURCE_VERIFIED] | Stop slippage is counted twice, so a stop exit costs about 0.4% (conservative) | A42 §B.3 L132; A47 §A47-E | corrected only in the research ledger `a48-cost-v1` | CON-17 |
| [HIS-32 · DOCUMENTED_ONLY] | Replay stop fill at the level and on gaps is optimistic; same-bar stop-first is pessimistic by up to 3.5 pp; the Paper touch fill `observed_price_v0` is optimistic | A47 §A47-C/F; A48 §A48-A #6-11 | A48 Modes 2/3 (92c0553) are research only; `resting_limit_v1` is inactive; A42–A46 stop-exit numbers must not be reused (RM §A47/A48) | CON-34; EXE-20 |
| [HIS-33 · SOURCE_VERIFIED] | The tracker booked NaN prices | A48 §Tracker input-safety | fixed by f3104c2 `usable_price()`, which is contained in the documented-deployed ea8ae4f | CON-31; runtime NOT VERIFIED (RT-17) |
| [HIS-34 · DOCUMENTED_ONLY] | Same-bar T3 checked before the stop; a time-stop mismatch; the entry priced at the close despite a 351.55 s mean delay; closed-candle look-ahead | P4 L10-14; `docs/code_indicator_review_plan.md` L29, L68-73 | addressed in `shared/triple_barrier.py` (605a962) and `shared/ohlcv.py` | — |
| [HIS-35 · DOCUMENTED_ONLY] | A gap-through stop filled at the stop price | `docs/signal_aware_execution_2026-08-18.md` L43-45 | fixed for the new cohort only (c4a623c) | HIS-09 to HIS-14 predate the fix |
| [HIS-36 · DOCUMENTED_ONLY] | StochRSI smoothing; RSI < 20 not scored; a silent `ta` fallback | `docs/code_indicator_review_plan.md` L46-49 | changed at 63da7d3 | HIS-09 to HIS-12 predate the change |
| [HIS-37 · DOCUMENTED_ONLY] | Data snooping: 40+ studies on overlapping history, post-hoc cells, the 24h absolute-move ≥ 1% universe filter, survivorship | A45 §A45-C W12/W14; P3 L30-31; P6 L48, L55; phase16 L16-18 | none; no multiple-testing correction across studies | HIS-42 |
| [HIS-38 · SOURCE_VERIFIED] | The walk-forward scripts have no freeze cutoff and use a flat 0.30% cost | `research/walk_forward_audit.sh`; `research/walk_forward_review.py#load_rows` | open | CON-35 |
| [HIS-39 · INFERRED] | A re-run of those walk-forward scripts would read the sealed W3 window | inferred from HIS-38 | — | no run was performed |
| [HIS-40 · DOCUMENTED_ONLY] | W3 summary-level exposure: a cron wrote post-freeze summaries until it was disabled on 2026-10-01 | `research/governance/W3_CONTAMINATION_DISCLOSURE.md` on the unmerged branch `docs/p2-g0-w3-holdout-guard-20261002` | the disclosure and its guard are unmerged | OQ-10 |
| [HIS-41 · DOCUMENTED_ONLY] | Tested code ≠ running image; git_dirty | phase2a §2, §5 | open | RT-16, RT-17 |

Detail: [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md) and [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md).

## 12. Statistical and methodological limitations

### 12.1 State of the evidence

- [HIS-42 · INFERRED] No real-data study shows net-positive, out-of-sample-robust performance. Every net-positive real-data figure is non-robust:

  | Figure | Weakness |
  |---|---|
  | Phase 3 momentum (HIS-09) and the Phase 5 OOS figure (HIS-10) | CIs contain 0 |
  | Phase 6 (HIS-11) | falls to PF 0.88 without its top 5 trades |
  | Phase 9 (HIS-12) | +0.062% net, walk-forward +0.033%, 2 of 5 folds positive (unproven) |
  | Canary (HIS-14) | p = 0.65; negative without its top 3 |

  - HIS-09 to HIS-12 reuse one cohort (HIS-13); the canary is an earlier sample spanning two policies.
  - Evidence: synthesis of the section 10 register (history investigation §6; compiled audit §12). Runtime-verified: no.
  - Limitation: an inference across documents; no study was re-run.
- [HIS-43 · DOCUMENTED_ONLY] S4 and Design A have no market evidence. The sources are P1 §5 and the Design A memo §1 (`docs/strategy/DESIGN_A_PROFITABILITY_DECISION_MEMO.md` on `feature/design-a-v1` @ ebf8d8a).
- [HIS-44 · NOT_VERIFIED] Other gaps:
  - A win-rate/payoff pair in A42 §A.3 L77 is itself marked "unverified". Its values are not reproduced here because the section adjoins post-freeze content.
  - The contamination registry has a gap for 2026-01 → 06 (P1 §4 L69).
  - Survivorship bias is not addressed.

### 12.2 Sampling, dependence and multiple testing

These points restate findings tagged earlier in this pack.
- **One cohort reused.** Phases 3, 5, 6 and 9 share the 2026-07-20 → 08-17 sample (HIS-13).
- **Snooping across studies.** There are 40+ studies on overlapping history, with post-hoc cells, the 24h absolute-move universe filter and survivorship, and no multiple-testing correction (HIS-37).
- **Learner statistics** (LRN-07, SOURCE_VERIFIED):
  - a cell can be throttled only with n ≥ 10;
  - the interval is a normal approximation, ± z·sd/√n with z = 1.96;
  - a cell is throttled only when ci_high ≤ 0, i.e. it fails open;
  - there is no multiple-testing correction across up to 32 cells and no dependence adjustment;
  - exploration runs at rate 0.10 via an hourly blake2b hash;
  - there is no out-of-sample test, no holdout and no human approval in the code.
- **Learner risks** (LRN-08, INFERRED):
  - a feedback loop and selection bias: the learner trains only on trades that passed its own gates, so throttled cells are re-sampled only through exploration or the 14-day deletion;
  - overlapping trades inflate the effective n;
  - heavy tails make the n = 10 normal interval anti-conservative;
  - it uses a flat 0.3% cost model;
  - the runtime read does not filter on strategy_version.
- **Optimiser statistics.**
  - The tuner adjusts min_score from the gross win rate and average profit, with no statistical test (LRN-11).
  - Indicator weights come from gross PnL differences, with no confidence interval and no out-of-sample test, and are overwritten in place with no history (LRN-12).

### 12.3 Calibration provenance and validation

These points restate findings tagged earlier in this pack.
- **CAL-05 (SOURCE_VERIFIED):** calibration datasets are undocumented. Code comments give trade counts only, with no window, symbol list, hash or cost model.
- **CAL-06 (INFERRED):** the calibration samples are in-sample bot history.
- **CAL-07 (SOURCE_VERIFIED):** the validation methodology is undocumented for deployed values. The A29–A34 governance documents and `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md` are not linked to any deployed threshold.
- **Related findings:**
  - parameter provenance is partial and there is no parameter registry (CAL-04);
  - the live rules are hand-set "operational starting points, not evidence of edge" (STR-23);
  - their only evidence is mechanics tests (STR-24).

### 12.4 Economic design limitations

**Traceability for this subsection.**
- Source: the compiled audit §14, which synthesises the runtime, strategy, universe, learning and history investigations.
- ECO-06 was re-checked at publication against `docs/strategy/S4_MECHANISM_COMPARISON.md:58`, `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md:18` and `:65`, and `docs/strategy/S5_PWR_1_OWNER_DECISIONS.md:29` (PD-05).
- Runtime-verified: no.

- [ECO-01 · INFERRED] The system is a signal generator with a Paper execution tracker, not a portfolio-growth or capital-allocation system. It has:
  - no portfolio construction;
  - no risk-based sizing;
  - no correlation control;
  - utilisation of at most 20% of the $500 virtual capital (2 × $50; RSK-06).
- [ECO-02 · INFERRED] Context indicators act only as vetoes (BTC, USDT.D) or are only collected (ETH, BTC.D). The value of the gate itself has never been verified. It cannot be replayed, because the CoinGecko data are not point-in-time.
- [ECO-03 · SOURCE_VERIFIED] Operational counters are gross (`risk_management` wins/losses, /status). The modelled cost (0.30% flat, about 0.40% on stops) is below the research cost baselines.
- [ECO-04 · INFERRED] Version contamination:
  - the current rules changed at the freeze, so all their evidence is in the sealed holdout;
  - earlier studies mixed several versions.
- [ECO-05 · DOCUMENTED_ONLY] Overfitting risk: weights and gates were fitted on the same sample, and 40+ studies ran on contaminated history.
- [ECO-06 · DOCUMENTED_ONLY] Fees and turnover:
  - with a historical gross PF below 1, any cost deepens the loss;
  - 15m fees are 0.22–0.43 R per trade (A46-C fee arithmetic as cited in `docs/strategy/S4_MECHANISM_COMPARISON.md:58` and `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md:18` and `:65`);
  - a T1 hit rate of at least 0.81–0.96 would be needed (`S4_PHASE1_SCIENTIFIC_COMPARISON.md:18`);
  - the same concern appears in `docs/strategy/S5_PWR_1_OWNER_DECISIONS.md:29` (publication re-check).
- [ECO-07 · INFERRED] Measurement is at trade level only; there is no mark-to-market equity curve at runtime.
- [ECO-08 · INFERRED] **A net-profitability claim is unsupported.**
  - No out-of-sample real-data evidence shows net profitability.
  - The current strategy's performance is unknown by governance, because its evidence is in the sealed holdout.

### 12.5 Execution and data-quality limitations

These points restate findings tagged earlier in this pack.
- **Execution.** The execution model is simulated on last trades, and level-3 exchange realism is not established (EXE-20). Its fills carry known optimistic and pessimistic biases (HIS-32).
- **Candle timing.**
  - Candle closure relies on the host clock, with no exchange time sync, so clock skew could admit a forming bar (EXE-05, EXE-06).
  - Candle age is never checked in off mode, so a 1d bar can be about 24 h old at signal time (EXE-09).
- **Macro input.**
  - The macro gate's CoinGecko input is not point-in-time and cannot be replayed (STR-12).
  - Its refresh has fail-open holes: a missing key reads as 0.0 and therefore "falling", and an empty history reads as "flat" (MKT-15).
- **Image parity.** Image content parity is documented only, so code-level conclusions may not describe the running images (RT-16, RT-17).
- **Version drift.** In the documented-deployed analyzer source (ea8ae4f) the T1 cap policy cannot be switched, because `T1_CAP_POLICY` is absent from that commit (STR-17); that the image contains this source is DOCUMENTED_ONLY (RT-16, RT-17).

## 13. Governance restrictions

The rules in this section are recorded in governance documents on main. They are DOCUMENTED_ONLY because they are rules, not observations.

**Sources** (all @ eba90dd):
- the [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md) (OOC);
- the [Development-First Policy](../../governance/DEVELOPMENT_FIRST_POLICY.md) (DFP);
- the [Compose operations runbook](../../ops/COMPOSE_OPERATIONS.md);
- the [branch and release policy](../../ops/BRANCH_RELEASE_POLICY.md);
- the [evidence-ladder parameters](../../strategy/EVIDENCE_LADDER_PARAMETERS.md) (ELP);
- `CLAUDE.md`.

The audit and this pack were produced under these restrictions: no database reads, no `.env` reads, no image filesystem reads, and no post-freeze outcomes (PD-02).

### 13.1 Mandate

- [GOV-01 · DOCUMENTED_ONLY] **PAPER_ONLY research and development** (OOC §1, §5):
  - no live-money execution, no credentials that would enable it, and no exchange order placement;
  - `PAPER_TRADING=true` stays set;
  - the continuous learner stays stopped unless separately authorized.
  - The goal is to discover and independently validate an economically robust net-profitable strategy. Gross signal counts and apparent backtest returns are not the goal.
  - Related structural fact: the repository contains no order-placement code (ARC-11).
  - **Paper economic-loss policy** (OOC §3, approved 2026-10-26):
    - economic losses, loss streaks, drawdown or low PF are observations to record and analyse, not automatic reasons to stop simulated collection;
    - no resetting loss counters, no fabricated fills, no changes to prior outcomes and no silent mixing of strategy versions;
    - technical and data-integrity safeguards stay fail-closed.

### 13.2 A29 Evidence Ladder and D1/D2 HOLD

- [GOV-02 · DOCUMENTED_ONLY] **The A29 Evidence Ladder remains in force**, with D1/D2 HOLD for governed confirmation (OOC §4). Its parameters:
  - a prospective horizon of up to 365 days;
  - at most 3 simultaneous candidates;
  - 20% of forward capacity reserved;
  - 5% familywise error control.
  - An ENCOURAGING result is non-confirmatory, and no technical shortcut may silently change these decisions.
  - DFP §5 records the ladder as α = 1/240, final look only, FWER control, at most 3 candidates and a 20% reserve.
  - It is classed CONFIRMATORY-ONLY (D3) and is not a development gate.
- [GOV-03 · DOCUMENTED_ONLY] **Nothing has passed the evidence ladder.**
  - ELP §4 L155 states: "None of these conditions can hold today".
  - The A33 validation was never run.
  - A34-B is REVISE.
  - The minimum detectable effect is about 16% optimistic (DR-7).
- **Scope note.** The HOLD scope itself is contradictory across documents (CON-36):
  - RM L23 and A42 say "D2–D5";
  - DFP §5 and S5_PWR_1 §Scope say "D1–D5";
  - OOC §4 says "D1/D2".

### 13.3 Holdout and data protection

- [GOV-04 · DOCUMENTED_ONLY] **The FORWARD_HOLDOUT after the 2026-08-19 research freeze stays sealed** (DFP §3). The boundary is recorded in `research/governance/research_freeze.json`.
  - No protected outcome, count or timestamp may be read (OD-7).
  - Unlocking the holdout is a one-way owner decision.
  - There is no production database read or write without owner approval.
  - There are no secrets in Git, logs, PRs or reports, and `.env` stays host-local.
  - The OOC adds that protected or sealed holdouts allow no unauthorized data reads, peeks, alpha consumption or changes to the prospective window.

### 13.4 Production operations safety

- [GOV-05 · DOCUMENTED_ONLY] **Production Compose safety** is governed by `docs/ops/COMPOSE_OPERATIONS.md` and `CLAUDE.md`. The host is shared, so operations run one service at a time.
  - **Class A** read-only inspection is always allowed: docker ps, inspect, logs and image inspect; Compose ps, logs, top and images; and `config --hash` / `config --services`.
  - **Class B** single-service operations need explicit owner approval and a gated procedure: restart, stop, recreate, deploy or rollback of one service, a writing exec, or starting the learner.
  - **Class C** commands are forbidden in production: a bare `up`, `up --build`, any build from the production checkout, `down`, `down -v`, `--remove-orphans`, any prune, pulling application images, bulk start/restart/rm, a `run` that mounts the production directory, and any change to more than one service.
  - **The absolute STOP rule** applies: anything unexpected means stop and return to the owner.
  - The `learner` profile is not an authorization boundary.

### 13.5 Workflow and reporting

- [GOV-06 · DOCUMENTED_ONLY] **Workflow**: the owner directive effective 2026-10-26, Continuous Development + PR-on-Demand (DFP header; OOC §2, §4, §5, §6):
  - main is canonical; prefer main and at most one shared, short-lived integration branch;
  - low-risk D0 development (docs, tests, synthetic research, tooling, default-off non-operational changes) may be integrated into main directly or by fast-forward/merge, without a PR or repeated owner approval, if:
    - CI is green;
    - the change is reversible;
    - it does not alter deployed runtime, risk controls, scientific admission, protected data or production configuration;
  - live service deployments and restarts, database writes, Paper strategy or version changes, /resume, protected-holdout access and confirmatory admissions remain separately owner-gated;
  - merging to main never triggers a production deployment, and a merged commit is not a deployment authorization;
  - Saved, Integrated, Deployed and Validated are reported separately, with deployed SHAs, image digests and post-deploy parity evidence;
  - server parity is never claimed from GitHub alone;
  - significant Paper strategy changes create explicit version boundaries, and prior outcomes are never retroactively attributed to a new version.
  - **Precedence:** an explicit later owner decision on the same subject outranks the consolidated contract, which outranks older conflicting workflow prose.
    - A workflow simplification does not implicitly repeal production safety, access restrictions, scientific protection or an operation-specific approval.
    - When records conflict, the narrower safety gate is followed.

### 13.6 Tracks on HOLD or not authorized

| ID · class | Track | Status | Governing documents | Pending |
|---|---|---|---|---|
| [GOV-07 · DOCUMENTED_ONLY] | A34-VS1 | HOLD, never run | RM §Ground rules, §S5; ELP §3 DR-6 | an approved run; OD-5 (S5_PWR_1 §2) |
| [GOV-08 · DOCUMENTED_ONLY] | MI Stage B | HOLD | RM §Ground rules; ELP §1 | Gate 1 on the local-only branch `feature/mi-am4a-stage-b-prep-20261011` @ 54a6369; OD-1 |
| [GOV-09 · DOCUMENTED_ONLY] | B2 | HOLD | RM; ELP §3 DR-13 | how "B2 gate v2" applies is undefined |
| [GOV-10 · DOCUMENTED_ONLY] | P2-D1 | HOLD | `docs/ops/COLLECTOR_NECESSITY_ASSESSMENT.md` §2, §4 | the owner re-opening the protocol |
| [GOV-11 · DOCUMENTED_ONLY] | Paper R2 | HOLD | RM; A42 §Unchanged | its governing document A37 exists only in 54a6369, so its content is NOT VERIFIED |
| [GOV-12 · DOCUMENTED_ONLY] | D1–D5 | HOLD; contradictory scope (CON-36) | RM L23; A42; DFP §5; S5_PWR_1 §Scope; OOC §4 | a DatasetPermission; the A18/A19 licence (no licence record in the repository) |
| [GOV-13 · DOCUMENTED_ONLY] | S4 backtests | NOT TESTED | RM §S4; P1 §6; DFP §5 | the family choice; a DatasetPermission; OD-DF-1/2; pre-registration |
| [GOV-14 · DOCUMENTED_ONLY] | P2-H1 / GS | HOLD | COLLECTOR_NECESSITY §2; A42 L219 | A22–A27 exist only in 54a6369; the envelope is UNVALIDATED (ELP DR-6) |
| [GOV-15 · DOCUMENTED_ONLY] | A42 C1–C3, A45 H1–H3, A46 G1–G3 | specified, not run | A42 §A42-E; A45 §A45-E/F; A46 §A46-E/F | owner activation; S5 rates C1 CURRENTLY_INADMISSIBLE and C2 DEFERRED (STR-27); the C3 data licence is on HOLD (STR-29) |
| [GOV-16 · DOCUMENTED_ONLY] | Design A | NOT AUTHORIZED for evaluation; branch `feature/design-a-v1` unmerged | DESIGN_A_SPEC §0, §19, §21; DESIGN_A_PROFITABILITY_DECISION_MEMO §3, §5 | owner decisions E1–E8; gates G0–G5 |

## 14. Unverified claims and contradictions

### 14.1 Findings that could not be verified (NOT_VERIFIED)

Every item below must be treated as unknown, not as its documented or code-default value. The IDs are tagged where the finding is first stated in this pack.

| ID | What is not verified | Why |
|---|---|---|
| RT-17 | Image filesystem content. As a result, no code behaviour in this package is runtime-verified: behaviour is SOURCE_VERIFIED at the documented commit only. | An image filesystem read is not a Class A operation and was not authorized. |
| RT-21 | What the telegram, trade_tracker and collector Compose image-label digests mean (INFERRED to be platform-manifest digests) | They are documented nowhere. |
| RT-30 | The collector's Compose render hash | Computing it needs P2F_* environment values. |
| RT-31 | The runtime value of PAPER_TRADING. It is not set in any Compose `environment:` block; the code default is true. | `.env` was not read. |
| RT-33 | Whether the observe code path is the one executing in telegram and trade_tracker; per-service operational verification in general | Needs image filesystem access. |
| RT-40 | The scanner's actual imports | The base revision of the assembled image is unknown. |
| RT-44 | The content of trade_tracker's WARN-level log lines | The text matched protected patterns, so it was not inspected. |
| RT-45 | The cause of the collector's unhealthy status | Project tsb-p2-forward is outside `ops/compose-safe` coverage, and Health.Log is not an allowed field. |
| RT-46 | PAPER_HALTED, pause and risk state | A database read was not authorized. |
| RT-47 | Runtime values of SIGNAL_INTEGRITY_MODE, LIVE_LEARNING_MODE, LEARNING_GATES_ENABLED, TIMEFRAMES, RISK_CANARY_MAX_OPEN_TRADES and PAPER_ENTRY_FILL_MODEL; container state beyond what DEPLOYED.json records (that file was observed on 2026-10-27) | `.env` was not read. |
| STR-04 | The runtime value of LIVE_LEARNING_MODE, which decides whether the live selector, the rule-based setups and the macro gate run at all | `.env` was not read; authorization is required. |
| STR-31 | Whether the S3 shadow sidecar ever ran | It has no Compose service and there is no runtime evidence. |
| CAL-03 | Every effective runtime parameter value; every DB value (optimizer_settings, indicator_weights, learned_gates, symbol_blacklist) | Neither `.env` nor the database was read. |
| CAL-10 | The APP_VERSION / strategy_version actually emitted (code default sb-2026.06) | The runtime value was not read. |
| EXE-08 | The effective PAPER_ENTRY_FILL_MODEL | `.env` was not read. |
| LRN-02 | When migration 006, which reset every gate to weight 1.0, was applied | The database was not read. |
| LRN-14 | Whether `colab/daily_training.py` ever ran | No record exists. |
| LRN-20 | The contents of learned_gates, indicator_weights and optimizer_settings; whether any learned_gates rows exist; the runtime LEARNING_GATES_ENABLED value | Neither the database nor `.env` was read. |
| UNI-06 | The current blacklist contents | A database read was not authorized. |
| HIS-19 | Turnover, for every study | No study reports it. |
| HIS-21 | The A29–A41 packages and the A58 session report | Not in the repository; A29–A41 exist only in local commit 54a6369. |
| HIS-23 | Records of the LuxAlgo-faithful SMC port, the falling-wedge study, a volume+RSI MTF result and a standalone Ichimoku study | There is no committed record. |
| HIS-44 | The A42 §A.3 L77 win-rate/payoff pair (marked "unverified" at its source; values not reproduced); the contamination-registry gap for 2026-01 → 06; survivorship bias | The section adjoins post-freeze content; the studies do not address survivorship. |

### 14.2 Documented values whose runtime value is not verified

These findings are DOCUMENTED_ONLY. They come from the 2026-09-27 non-secret config snapshot, from `.env.example` (via its review document) or from deploy records, all of which predate or sit beside the running containers (CAL-02).

| ID | Documented value | Effective value |
|---|---|---|
| STR-02 | LIVE_LEARNING_MODE=true (snapshot) | NOT VERIFIED (STR-04) |
| STR-06 | Timeframes 15m, 4h, 1d (snapshot; code default 15m,1h,4h,1d) | NOT VERIFIED |
| STR-19 | LEARNING_GATES_ENABLED false; learner stopped since 2026-08-17 | flag NOT VERIFIED (LRN-20); the learner container was observed exited (RT-10) |
| STR-34 | No SIGNAL_INTEGRITY_MODE enforce window was authorized (likely off) | NOT VERIFIED |
| EXE-03 | RISK_CANARY_MAX_OPEN_TRADES 2 (snapshot and `.env.example`; code default 1) | NOT VERIFIED |
| RSK-03 | Effective capacity of 2 open positions, or 1 when the sizing multiplier is ≤ 0.5 | NOT VERIFIED |
| UNI-07 | The blacklist was emptied on 2026-05-17 | NOT VERIFIED (UNI-06) |
| UNI-10 | MIN_VOLUME_USDT 10M; SCAN_INTERVAL_SECONDS 300 | NOT VERIFIED |
| IND-06 | min_score 3.0 in the DB (set 2026-05-16; legacy path only) | NOT VERIFIED |
| MKT-04 | The macro gate is active only with LIVE_LEARNING_MODE=true | NOT VERIFIED |
| ARC-23 | ENABLE_EVIDENCE_RECORDER true; LIVE_LEARNING_MODE true (snapshot) | NOT VERIFIED |
| LRN-04, LRN-10 | The learner is "stopped since 2026-08-17; must stay stopped" (DEPLOYED.json); the optimizer has been disabled since 2026-06-19 (Compose comment) | the learner container was observed exited and the optimizer has no container (RT-10, RT-11); the dates are documented only |
| RT-16 | Image content parity: analyzer 46/46, signal_engine 56/56, telegram 50/50, trade_tracker 51/51; the scanner overlay has 8 of 23 files that differ from main | NOT VERIFIED (RT-17) |

### 14.3 Main inferred conclusions (INFERRED)

These are reasoned conclusions, not observations. Each rests on the evidence cited where it is tagged.

| ID | Inference |
|---|---|
| RT-08 | The checkout's `technical_analyzer.py` edit is functionally equivalent by reading, and it is not what runs. |
| RT-12 | Whether the learner stays stopped depends on the manual-stop flag, the `learner` profile and the procedure, because its restart policy is unless-stopped. |
| RT-27 | No running service executes the checkout's uncommitted code: there is no `build:` and no source bind mount. |
| RT-38 | Running analyzer and signal_engine built from ea8ae4f, which lack economic_halt_policy, risk_epoch and t1_cap, is harmless today, because neither imports them. |
| RT-42 | A merge-status check by ancestry would miss work integrated by squash or cherry-pick. |
| ARC-17 | The claude_review passive dependencies (the signal.reviewed claim and claude_approved readiness) are not live. |
| STR-03 | The live path is presumed active, on the strength of the snapshot plus the `.env` modification time. |
| STR-12 | The macro gate cannot be replayed historically, because its CoinGecko input is not point-in-time. |
| STR-22 | EMA200 is immature, because only 200 bars are fetched. |
| STR-25 | No pre-freeze economic evidence exists for the current rules; all their outcome evidence is in the sealed FORWARD_HOLDOUT. |
| STR-37 | trade_geometry is unimportable in the ea8ae4f images. |
| CAL-06 | The calibration samples are in-sample bot history. |
| EXE-06 | Host clock skew could admit a forming bar. |
| EXE-15 | The effective modelled cost is 0.30%, or about 0.40% on stops: below the Design A baseline except on stops, and always below its stress case. |
| EXE-19 | Barrier touches can be missed when the price queue drops its oldest tick. |
| RSK-04 | The strategy and regime caps never bind with 2 slots. |
| RSK-06 | Capital utilisation is at most 20%. |
| LRN-05 | A learner restart would run undeployed code. |
| LRN-08 | The learner has a feedback loop, selection bias, an inflated effective n and an anti-conservative interval. |
| LRN-17 | Frozen weights still steer ordering and truncation, marginally if the live path is active. |
| LRN-19 | Enabling learned gates would immediately and indefinitely re-apply throttles written on or before 2026-08-17 (about 10% would still pass via exploration). |
| UNI-03 | The 1% move filter usually removes the stable pairs that are not explicitly excluded. |
| UNI-13 | 1d needs at least 200 days of listing history, and 4h about 33 days. |
| UNI-15 | The 50-row analyzer intake is not a hard cap on coverage. |
| UNI-17 | Alphabetical truncation bites above about 66 symbols × 3 timeframes; how often it happens is NOT VERIFIED. |
| UNI-19 | The bot evaluates a restricted, dynamic subset that favours the deepest majors. |
| MKT-14 | Macro state used in decisions can be up to about 6 h old in signal terms. |
| MKT-15 | The macro refresh has fail-open holes: a missing key reads as 0.0 and therefore "falling", and an empty history reads as "flat". |
| HIS-13 | Phases 3, 5, 6 and 9 reuse one sample. |
| HIS-39 | A walk-forward re-run would read the sealed window. |
| HIS-42 | No real-data study shows net-positive, out-of-sample-robust performance; every net-positive real-data figure (HIS-09, HIS-10, HIS-11, HIS-12, HIS-14) is non-robust. |
| HIS-46 | The version lineage runs from the earlier family to the current release images. |
| ECO-01, ECO-02, ECO-04, ECO-07, ECO-08 | The economic design limitations in section 12.4. |

### 14.4 Contradictions (CONTRADICTORY)

Each row records sources that disagree. No row is resolved by this pack. Unless noted, documents were read at ebf8d8a (equal to main for these paths) and code at the documented deployed commits. Runtime-verified: no, except where a row cites a runtime finding.

| ID · class | Contradiction | Sources | Area |
|---|---|---|---|
| [CON-01 · CONTRADICTORY] | `docs/ops/COMPOSE_OPERATIONS.md` §0 says telegram and trade_tracker run `tsb-a561-*:rel-ea8ae4f-r2`, "verified against the running containers". The observed images are `tsb-obs-*:bb7825f-20261027-r2`, which agrees with CLAUDE.md, DEPLOYED.json and the paper-observe record. The canonical runbook is stale, and its Class B image gate points to the aiohttp IMAGES.md, which now covers only the scanner. | runbook §0 vs RT-09 | runtime records |
| [CON-02 · CONTRADICTORY] | CLAUDE.md and the runbook treat `ops/compose-safe` as runnable from the production directory, but the production checkout has no `ops/` or `deploy/` directory. | CLAUDE.md; runbook vs RT-05 | runtime records |
| [CON-03 · CONTRADICTORY] | "Production docker-compose.yml = reviewed Git blob" holds at blob level only. The checkout is a non-main branch with no upstream, 267 commits behind main, and five files carry uncommitted edits that match no commit, so `git status` cannot show clean parity. | CLAUDE.md source-of-truth rule vs RT-01 to RT-04 | runtime parity |
| [CON-04 · CONTRADICTORY] | The paper-observe IMAGES.md says "RepoDigests is empty" and calls the Id a "config digest". The observed RepoDigests are `<repo>@<Id>`, and the aiohttp record calls the same kind of Id the "OCI index" (minor). | `deploy/paper-observe-bb7825f/IMAGES.md`; aiohttp IMAGES.md vs RT-18 | runtime records |
| [CON-05 · CONTRADICTORY] | The Stage A record documented the collector as HEALTHY after deployment; it is now unhealthy on two reads. DEPLOYED.json does not track health. | Stage A record vs RT-43 | runtime |
| [CON-06 · CONTRADICTORY] | The collector commit is 1bfb5f6 in `docs/ops/RUNTIME_TRACEABILITY.md` but 72c0bee in DEPLOYED.json and in the running image tag. | RUNTIME_TRACEABILITY.md vs DEPLOYED.json, RT-09 | runtime records |
| [CON-07 · CONTRADICTORY] | The docstrings of `shared/signal_identity.py` and `shared/dependency_safety.py` say "not wired" / "no production caller", but production services import both modules. | docstrings vs imports @ ea8ae4f | code documentation |
| [CON-08 · CONTRADICTORY] | `docs/claude/architecture.md:29` and `docs/claude/live-learning.md` show the learner and claude_review as active, and `CLAUDE.md:3` says the bot "learns continuously". Observed: the learner is stopped and claude_review is retired. | documents vs RT-10, RT-13 | documents vs runtime |
| [CON-09 · CONTRADICTORY] | The `risk_management` wins/losses counters and /status use gross labels, while /stats uses net labels. | telegram @ bb7825f; result recording (ARC-10) | reporting |
| [CON-10 · CONTRADICTORY] | The RISK_PRICE_FETCH_RETRIES commit message says an invalid value becomes 0, but a non-numeric value raises at import. | commit message vs `shared/config.py:157` @ bb7825f | code |
| [CON-11 · CONTRADICTORY] | `CLAUDE.md:46` (and the production copy, line 21) says live thresholds in the DB (optimizer_settings / indicator_weights) override `.env`. In code this holds only for two optimizer_settings keys, and only on the legacy path. | CLAUDE.md vs CAL-01 | configuration |
| [CON-12 · CONTRADICTORY] | The min_score, stoch>0 gate, 4h ban and multi-timeframe narratives are often described as live, but they belong to the legacy path only. 4h is not banned on the live path. | various documents and notes vs STR-15, STR-16 | strategy documentation |
| [CON-13 · CONTRADICTORY] | min_score is 5 in code, 7 in `.env.example` and the snapshot, 5.0 as the DB seed and 3.0 as the documented DB value, and the tuner bounds it to 1.5–3.5. The seed lies outside the tuner bounds. | IND-05, IND-06, LRN-11 | calibration |
| [CON-14 · CONTRADICTORY] | The maximum score is 5.5, but `analyzer/main.py:178` logs it as "/10". The legacy env min_score of 7 is unreachable when weights are 1.0. MACD, EMA, volume and OBV are computed but score 0. | STR-14 | calibration |
| [CON-15 · CONTRADICTORY] | TIMEFRAMES_LL is documented but nothing reads it. LEARNING_CLEAN_START and LEARNING_CONFIDENCE_Z are set on signal_engine, but nothing there reads them. | configuration vs code | configuration |
| [CON-16 · CONTRADICTORY] | RISK_CANARY_MAX_OPEN_TRADES defaults to 1 in code but is 2 in `.env.example` and the snapshot. | EXE-02, EXE-03 | configuration |
| [CON-17 · CONTRADICTORY] | FEE_ROUNDTRIP_PCT already includes slippage, and stop exits add STOP_SLIPPAGE again. `shared/execution_calibration.py:349-362` documents the double count. | EXE-13, EXE-14 | costs |
| [CON-18 · CONTRADICTORY] | The exit label `T1_expired_24h` is hard-coded, although the actual stalled-after-T1 time is 48 h for 4h and 120 h for 1d. | EXE-11 | execution |
| [CON-19 · CONTRADICTORY] | The learner builds from the production working tree while the other services run pinned release images. | LRN-03 vs RT-09 | runtime |
| [CON-20 · CONTRADICTORY] | The comment at `technical_analyzer.py:351-354` is valid only when w_rsi = 1.0. | STR-14 | code documentation |
| [CON-21 · CONTRADICTORY] | A42, A45, A46 and A47 analysed commit 59297305, but ea8ae4f is the deployed version. | A4x documents vs RT-16 | research |
| [CON-22 · CONTRADICTORY] | T1_CAP_POLICY is on main and bb7825f but absent from the documented-deployed analyzer source (ea8ae4f), so main does not describe the deployed T1 behaviour (image content parity is DOCUMENTED_ONLY, RT-16). | STR-17 | version drift |
| [CON-23 · CONTRADICTORY] | The S3 document says a NaN spread passes; ea8ae4f fixes that (`finite_spread_pct`). | `docs/s3/` vs code @ ea8ae4f | documents vs code |
| [CON-24 · CONTRADICTORY] | btc_bonus uses the symbol's own regime, not BTC's. | legacy selector @ ea8ae4f | code |
| [CON-25 · CONTRADICTORY] | The stoch>0 gate's calibration predates 63da7d3's StochRSI change from K=14 to 14/3/3. | STR-16, STR-20 | calibration |
| [CON-26 · CONTRADICTORY] | The telegram code comment (`main.py:725-731` at bb7825f) says the optimizer updates optimizer_settings automatically, but the optimizer is disabled. | LRN-09 | code documentation |
| [CON-27 · CONTRADICTORY] | Two BTC-trend definitions share the same labels: the scanner's 36 h with ±1/±3% and the macro's 68 h with ±1/±5%. The documents (A45 and the `_is_btc_crashing` docstring) say "40 h", and the macro comment says "~3 days (18×4h)". | MKT-01, MKT-03 | market context |
| [CON-28 · CONTRADICTORY] | The macro_context module docstring promises a "daily snapshot / 3-day average". In practice each hourly refresh overwrites that day's row, the mean spans D−3..D including today, and "today" is computed in UTC but compared with the DB's CURRENT_DATE, so a timezone mismatch is possible (INFERRED). | MKT-07 | market context |
| [CON-29 · CONTRADICTORY] | A comment in `signal_engine/main.py` says MacroContext "only calls public klines"; it also calls CoinGecko and the DB. | MKT-11, MKT-13 | code documentation |
| [CON-30 · CONTRADICTORY] | The Telegram header advertises whitelist approval, but that code path is dead. | UNI-08 | documents vs code |
| [CON-31 · CONTRADICTORY] | A48 §A48-H and the roadmap (RM L220) say the f3104c2 NaN-price fix is "awaiting deployment", but the documented-deployed ea8ae4f contains f3104c2 (RM L8). | HIS-33 | research records |
| [CON-32 · CONTRADICTORY] | On the cooldown fail-open, S3 §1 row 7 says "confirmed" while `tests/test_a43_signal_integrity.py:384` says "fixed". The off path still returns `set()` (`signal_logic.py:432`). | HIS-27 | research records |
| [CON-33 · CONTRADICTORY] | W3 severity: A42 labels it "[D/H]", while A45 calls it a "CONFIRMED IMPLEMENTATION DEFECT". | HIS-30 | research records |
| [CON-34 · CONTRADICTORY] | A47 §A47-F L81 reports "0 implementation defects", while A48 §A48-A items 1 and 5 list defects. | HIS-32 | research records |
| [CON-35 · CONTRADICTORY] | The walk-forward scripts use a flat 0.30% cost with no freeze cutoff, contrary to the `research/mechanisms/costs.py` docstring. | HIS-38 | research code |
| [CON-36 · CONTRADICTORY] | HOLD scope: RM L23 and A42 say "D2–D5", DFP §5 and S5_PWR_1 §Scope say "D1–D5", and the Owner Operating Contract §4 says "D1/D2". | GOV-02, GOV-12 | governance |
| [CON-37 · CONTRADICTORY] | P1 L13 cites strategy-history for "0.734 / 2,461", but SH L12 says 0.735 / 2,518. | HIS-01, HIS-03 | research records |
| [CON-38 · CONTRADICTORY] | `docs/lab/REVIEW_PACKAGE_R1_QUANT.md` L16 ("≈0.73 on 2,518 / 3,401") merges the REPORT.md set with the A58 set. | HIS-01, HIS-04 | research records |
| [CON-39 · CONTRADICTORY] | DEV_LOG L24 says COMBO "breaks even OOS"; RP L62 gives −$0.158. | HIS-01, HIS-24 | research records |
| [CON-40 · CONTRADICTORY] | DEV_LOG L67-68 raises min_score from 3 to 4, while SH L8 keeps 3.0. | IND-06 | calibration records |
| [CON-41 · CONTRADICTORY] | The baseline walk-forward figure is given as +0.017% (P3 L48), +0.046% (P5 L23) and +0.033% (P9 L25). | HIS-09, HIS-10, HIS-12 | research records |
| [CON-42 · CONTRADICTORY] | Trade counts: 307 (P6 L13) vs 303 (P9 L10); momentum n 162 (P3 L15) vs 163 (P6 L44). | HIS-09, HIS-11, HIS-12 | research records |
| [CON-43 · CONTRADICTORY] | phase16/16b say replay is "blocked"; phase2a §13-14 say replay was run and "RESUME PHASE 2A". | HIS-18 | research records |
| [CON-44 · CONTRADICTORY] | The minimum detectable effect is ≈ 3.5–5.0 in R1 §Context facts but ≈ 3.5–7.0 in DFP §7. | GOV-03 | governance / statistics |
| [CON-45 · CONTRADICTORY] | Half-spread is 0.05% in DESIGN_A_SPEC §2 F22 but 0.01% for BTC/ETH in P1 §4. The Design A memo flags this in §2.4. | HIS-15, HIS-16 | costs |
| [CON-46 · CONTRADICTORY] | W3 boundary: `≥ freeze` in `research/p2/SPEC.md` §1 (unmerged) vs `> freeze` in `research/data_governance/governance.py#partition_for`. | GOV-04 | governance |
| [CON-47 · CONTRADICTORY] | Overloaded identifiers: W3 (an A45 weakness vs the holdout window), D1, R2, S4 and Stage B each name more than one thing. | various documents | nomenclature |
| [CON-48 · CONTRADICTORY] | Weight tuning: DEV_LOG L70-72 claims that raising rsi_divergence from 0 to 2 gave a 60% win rate; RP L64 and L128 refute it. | HIS-24, LRN-12 | research records |

Detail by area: [RUNTIME_AND_PARITY.md](RUNTIME_AND_PARITY.md), [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md), [MARKET_CONTEXT_AND_ASSET_SELECTION.md](MARKET_CONTEXT_AND_ASSET_SELECTION.md) and [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md).

## 15. Key questions for independent review

### 15.1 Open questions recorded for the owner

These questions come from the completed audit. None of them is answered or acted on here.

- [OQ-01] Authorize narrow database reads?
  - Proposed scope: optimizer_settings (key, value, updated_at); indicator_weights (indicator, condition, weight, last_updated); the current pause state only.
  - Nothing would be read from the trade or learning tables, whose post-freeze counts and times are protected (OD-7).
- [OQ-02] Authorize reading non-secret `.env` flags through a redacted allow-list? The flags: LIVE_LEARNING_MODE, SIGNAL_INTEGRITY_MODE, LEARNING_GATES_ENABLED, TIMEFRAMES, RISK_CANARY_MAX_OPEN_TRADES, PAPER_TRADING and PAPER_ENTRY_FILL_MODEL.
- [OQ-03] Authorize image content verification, i.e. hashing the files inside the images? It is not a Class A operation.
- [OQ-04] The collector is unhealthy: should an operational investigation be opened?
- [OQ-05] The production checkout is a stale branch with local edits, and the learner would build from it: what is the decision?
- [OQ-06] Clarify the HOLD scope: D1/D2, or D1–D5?
- [OQ-07] Objective: "all eligible assets", or a restricted set? Is the capacity of 2 × $50 intended?
- [OQ-08] Paper accounting: keep the flat 0.30%, or adopt the 0.40% baseline / 0.60% stress?
- [OQ-09] Frozen weights: should their effect on candidate ordering and truncation remain?
- [OQ-10] Disclosure and licensing: what is the status of the unmerged W3 disclosure and of the A18/A19 licence decision record?

### 15.2 Questions for an independent reviewer

These questions add no new finding. Each rests only on the IDs it cites.

1. **Runtime parity.** What evidence would establish that the running analyzer, signal_engine and scanner images contain the code this package describes?
   - Their labels carry revision=unknown (RT-15).
   - Content parity is recorded only in deploy records (RT-16).
   - The image filesystems were not read (RT-17).
   - The matching config hashes and DEPLOYED.json entries (RT-23, RT-35) concern Compose configuration and container identity, not file content.
2. **Which decision path runs.** Does any record other than the 2026-09-27 snapshot establish whether the live selector, the rule-based setups and the macro gate are active (STR-01, STR-02, STR-03, STR-04, MKT-04)?
3. **Evidence for the current rules.** The current momentum/reversion rules came in at 63da7d3, which is dated on the research-freeze date (2026-08-19) and precedes the recorded freeze boundary. Is there any admissible outcome evidence for them outside the sealed FORWARD_HOLDOUT (STR-25, ECO-04, GOV-04, HIS-46)?
4. **Transferability of the pre-freeze negatives.** What do the negative pre-freeze results on earlier versions (HIS-01, HIS-04, HIS-05) say about the current rules? Consider the indicator and execution changes that came later (HIS-35, HIS-36), and that A42–A47 analysed 59297305 rather than the deployed ea8ae4f (CON-21).
5. **Cost adequacy.** Is a flat 0.30% round trip on gross P&L, about 0.40% on stops and with no spread component (EXE-13, EXE-14, EXE-15), adequate for an economic reading? Compare the owner standard (ECO-09), the Design A baseline and stress (HIS-16), and the documented double count and half-spread conflict (CON-17, CON-45).
6. **The W3 defect.** How material is the W3 T1 self-reference, given that the documented-deployed analyzer source (ea8ae4f) cannot switch its T1 policy (STR-17, RT-17, STR-21, HIS-30, CON-22, CON-33)?
7. **Selection bias.** How much does spread-first ranking combined with alphabetical `LIMIT 200` truncation determine which symbols can trade (STR-13, UNI-16, UNI-17, UNI-19, HIS-28)?
8. **Macro-gate reproducibility.** Can the macro gate's decisions be reproduced or evaluated? Its CoinGecko input is not point-in-time, its refresh has fail-open holes, and two BTC-trend definitions share the same labels (STR-12, MKT-13, MKT-14, MKT-15, ECO-02, CON-27, CON-28).
9. **Dormant learning state.** What would decide whether frozen indicator_weights, or learned_gates rows written on or before 2026-08-17, influence decisions if a flag or the path changes? The relevant table contents and flag values are unverified (LRN-16, LRN-17, LRN-18, LRN-19, LRN-20, CAL-09).
10. **Execution realism.** With only levels 1 and 2 established, last-trade touch fills, a stop double count and optimistic replay stop fills, can any Paper or replay result be informative about exchange-level outcomes (EXE-07, EXE-20, HIS-31, HIS-32)?
11. **Statistical robustness.** Do the Phase 3, 5, 6 and 9 results survive correction for the reuse of one cohort, post-hoc cells and the absence of multiple-testing control across 40+ studies (HIS-09, HIS-10, HIS-11, HIS-12, HIS-13, HIS-37, HIS-42)?
12. **Integrity fixes behind flags.** The re-fire and duplicate-trade fixes take effect only when SIGNAL_INTEGRITY_MODE=enforce, which is off by default and unverified at runtime. Is the evidence on whether they are active sufficient (HIS-25, HIS-26, STR-33, STR-34, EXE-17)?
13. **Production checkout drift.** Does the stale production checkout, with its uncommitted edits, pose a reproducibility or safety risk to any future learner start (RT-01 to RT-07, CON-03, CON-19, LRN-03, LRN-05)?
14. **HOLD scope and admissible work.** Given the contradictory HOLD scope and the HOLD-track table, which tracks could proceed without touching the sealed holdout, and under which owner decisions (CON-36, GOV-02, GOV-03, GOV-07 to GOV-16)?
15. **Capacity versus objective.** Is the implemented capacity consistent with the stated research objective and cost standard? Its documented capacity is 2 open positions of $50 (code default 1; effective value NOT VERIFIED, EXE-03) on a $500 virtual capital, at most 20% utilisation, with sizing multipliers that can lower it to 1 (RSK-02, RSK-03, RSK-06, ECO-01, ECO-09, OQ-07).

### 15.3 Closing statement

This pack documents a completed read-only, AS-IS audit; the runtime inspection took place on 2026-10-31.
- Producing it did not change application code, configuration, the database, any container, the runtime or the Paper Trading state.
- It ran no research, backtest, simulation, optimisation or learning, and it accessed no sealed holdout or protected dataset.
- **It is not a profitability certification.** No evidence in this pack supports a claim that any strategy is net-profitable. The historical real-data evidence is negative or inconclusive (HIS-01, HIS-42), and the current rules have no accessible economic evidence (STR-25).
