# Market Context and Asset Selection

**Trading Signal Bot: read-only system audit of 2026-10-31.** This document covers how the tradable universe is built and narrowed, and how BTC, ETH, BTC.D, USDT.D and the per-symbol regime are computed. It also records which context inputs actually gate decisions and how stale or missing data are handled.

## Document control

| Field | Value |
|---|---|
| Package | `docs/audits/2026-10-31-trading-system-review/` |
| Repository | `baljadrawy/trading-signal-bot` (private GitHub) |
| Audit and runtime inspection date | 2026-10-31 (runtime samples at 13:59Z and 14:05Z) |
| Repository reference | `main` = `eba90ddf4ae60641f80627472098e34650915d28` (eba90dd), both at audit time and at publication time |
| Code read at the commits documented as deployed | <ul><li>analyzer and signal_engine: `ea8ae4f00e80c5c171536293d2df7472fa338c3e` (ea8ae4f)</li><li>telegram and trade_tracker: `bb7825f4744278095ef76a1d0f3b872e3043358f` (bb7825f)</li><li>collector: `72c0bee82b44bede5192373d18374724f11c6c3a` (72c0bee)</li><li>scanner: an assembled image whose blobs are listed in `deploy/baseline-2026-09-27/deployed_files.json` (8bfca77); its `shared/config.py` is blob c5c03b5c from 7bf6214</li></ul> |
| Repository documents read at | `ebf8d8ad2c71b1203565c10b98f22f32e0a81c05` (ebf8d8a, `feature/design-a-v1`). It equals main plus 13 Design A files, with no active-path difference. |
| Production checkout | `integration/research-pipeline` at `63da7d31daef2b952c695b256f81cf174b6451a8` (63da7d3), plus uncommitted edits. INFERRED not to be executed by any running service (RT-27). |
| Status | <ul><li>READ-ONLY, AS-IS audit; documentation-only publication.</li><li>**Not a profitability certification.** Nothing in this document supports a net-profitability claim.</li><li>No change was made to application code, configuration, database, containers, runtime or Paper Trading state.</li></ul> |
| Investigation sources | <ul><li>the universe and market-context investigation (primary)</li><li>the strategy and Paper-execution investigation</li><li>the indicator, calibration and learning investigation</li><li>the architecture investigation</li><li>sections 7–8 of the compiled audit</li></ul> |

## Evidence classes and tags

| Class | Meaning in this document |
|---|---|
| RUNTIME_VERIFIED | Observed directly on the production host during the 2026-10-31 read-only inspection: container and image metadata, Compose hashes, host git state. Point-in-time only; it says nothing about code behaviour inside images. |
| SOURCE_VERIFIED | Confirmed by reading code or tracked files at a named commit. Not proof of deployed behaviour: image content parity is only DOCUMENTED_ONLY (RT-16), and image filesystems were not read (RT-17). |
| DOCUMENTED_ONLY | Stated in repository documents, deploy records or the 2026-09-27 non-secret configuration snapshot; not verified at runtime. |
| HISTORICAL_REPORTED | A past result, metric or verdict from a study or report. Not recomputed, and never a current observation. |
| INFERRED | A reasoned conclusion from other evidence; not observed directly. |
| NOT_VERIFIED | Could not be verified: evidence was missing, or the access needed (database reads, `.env` values, image filesystems) was not authorized. |
| CONTRADICTORY | Two or more sources disagree. |

**Tags.**
- Each finding carries a tag such as `[UNI-01 · SOURCE_VERIFIED]`.
- Finding IDs and classes are shared by all seven package documents, so a finding has the same ID and class here, in the Arabic full audit and in the Reviewer Evidence Pack.
- A bare ID, for example `MKT-07`, is a cross-reference.

**Runtime verification.**
- A finding not tagged RUNTIME_VERIFIED was not runtime-verified, and no observation date applies.
- Code behaviour described below is at most SOURCE_VERIFIED at the commit (or, for the scanner, the blobs) documented as deployed; items tagged INFERRED are reasoned from that code. None was observed in a running container.

## Related package documents

- [README.md](README.md): package overview, scope, limitations and confidence.
- [FULL_SYSTEM_AUDIT_AR.md](FULL_SYSTEM_AUDIT_AR.md): the complete Arabic audit, carrying every finding.
- [RUNTIME_AND_PARITY.md](RUNTIME_AND_PARITY.md): containers, images, deployed versions, GitHub-to-runtime parity and architecture.
- [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md): strategy rules, indicators, calibration, Paper execution, risk controls and learning.
- [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md): historical versions, studies, cost assumptions and governance.
- [REVIEWER_EVIDENCE_PACK.md](REVIEWER_EVIDENCE_PACK.md): a self-contained English pack for independent reviewers.
- Governance basis: [OWNER_OPERATING_CONTRACT.md](../../governance/OWNER_OPERATING_CONTRACT.md) and [DEVELOPMENT_FIRST_POLICY.md](../../governance/DEVELOPMENT_FIRST_POLICY.md).
- Deploy record: [DEPLOYED.json](../../../deploy/DEPLOYED.json).

## Contents

1. [Scope and provenance](#1-scope-and-provenance)
2. [Universe and scanner selection](#2-universe-and-scanner-selection)
3. [Analyzer intake, selection query, ranking and eligibility](#3-analyzer-intake-selection-query-ranking-and-eligibility)
4. [Capacity and portfolio constraints that limit coverage](#4-capacity-and-portfolio-constraints-that-limit-coverage)
5. [Coverage verdict](#5-coverage-verdict)
6. [Market-context usage matrix](#6-market-context-usage-matrix)
7. [Roles of BTC, ETH, BTC.D, USDT.D and the regime](#7-roles-of-btc-eth-btcd-usdtd-and-the-regime)
8. [Actual decision gates and the decision trace](#8-actual-decision-gates-and-the-decision-trace)
9. [Data sources, refresh, staleness and failure behaviour](#9-data-sources-refresh-staleness-and-failure-behaviour)
10. [Collected but unused components and active-state summary](#10-collected-but-unused-components-and-active-state-summary)
11. [Contradictions](#11-contradictions)
12. [Not verified in this area and open question](#12-not-verified-in-this-area-and-open-question)

## 1. Scope and provenance

This document covers:
- the asset universe and scanner selection;
- the roles of BTC and ETH, and the BTC.D and USDT.D calculations;
- regime classification;
- the decision gates that context inputs actually drive;
- ranking and eligibility;
- data sources, refresh and failure behaviour;
- context components that are collected but unused.

Strategy entry and exit rules, indicator calibration and Paper execution are covered in [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md). Runtime inventory and parity are covered in [RUNTIME_AND_PARITY.md](RUNTIME_AND_PARITY.md).

### 1.1 Code versions read

- [PD-03 · HISTORICAL_REPORTED] Code was read with `git show` at the commits documented as deployed: analyzer and signal_engine at ea8ae4f, telegram and trade_tracker at bb7825f.
  - One investigation report calls the review worktree ebf8d8a "main". ebf8d8a equals main eba90dd everywhere except 13 Design A files, so its comparisons also hold for main.
  - On the universe and macro paths, main differs from ea8ae4f only by the T1-cap flag code (RT-37).
- [RT-39 · DOCUMENTED_ONLY] The scanner image is assembled from several older commits (`deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json:622-866`; `deploy/baseline-2026-09-27/deployed_files.json`). The investigation read the exact blobs listed for it:
  - `scanner/scanner_logic.py` is blob fa03cc2a, the same blob at ea8ae4f and at main;
  - `scanner/main.py` is blob 3dc9cb1, equal to the ea8ae4f content;
  - `shared/config.py` is blob c5c03b5c, from 7bf6214.

  The scanner's shared macro, outbox and schema files are older versions, and its schema guard requires v6. Blob equality with ea8ae4f and main was checked by git-object comparison; that the running image contains exactly these blobs is only documented.
- [STR-11 · SOURCE_VERIFIED] `shared/macro_context.py` (blob 9099d1d1) is identical at 63da7d3, ea8ae4f, bb7825f and main. The macro gate it implements is described in full in section 8.
- [STR-09 · SOURCE_VERIFIED] The per-symbol regime routing is unchanged since its introduction: `shared/regime.py:classify_regime` (lines 10-60) and `analyzer/simple_entry.py` were introduced at 63da7d3 and are byte-identical at ea8ae4f.
- [RT-16 · DOCUMENTED_ONLY] Deploy records state that the analyzer image matches ea8ae4f on 46/46 files and the signal_engine image on 56/56. The production checkout's local edits are therefore documented as not being in the running images.
- [RT-24 · RUNTIME_VERIFIED] The host Compose file blob d1a4b197 equals `eba90dd:docker-compose.yml` and the DEPLOYED.json `git_blob` (observed 2026-10-31).
- [RT-17 · NOT_VERIFIED] Image filesystems were not read. No code behaviour in this document is runtime-verified.

### 1.2 Configuration sources and precedence

- [CAL-01 · SOURCE_VERIFIED] Configuration precedence, highest first:
  1. Compose `environment:`;
  2. `.env` (env_file);
  3. the dataclass default read at import.

  No universe or strategy variable is set in any Compose `environment:` block, so every configurable value comes from the unread `.env`. Hard-coded constants cannot be overridden. The only database override is `optimizer_settings` min_score/min_tf, and only on the legacy path.
- [CAL-02 · DOCUMENTED_ONLY] Configured values cited here come from:
  - the committed resolved-configuration snapshot `deploy/baseline-2026-09-27/config/trading_*.nonsecret.json` (2026-09-27). It predates every current container start: 2026-10-19 for analyzer, scanner, signal_engine and postgres; 2026-10-22 for the collector; 2026-10-27 for telegram and trade_tracker (RT-09);
  - `docs/ops/PAPER_ECONOMIC_OBSERVATION.md`;
  - for `.env.example` values, `docs/ops/ENV_EXAMPLE_REVIEW_2026-10-18.md`, which itself flags `.env.example` as misleading (line 20).
- [STR-03 · INFERRED] The snapshot predates every current container start (2026-10-19 to 2026-10-27, RT-09), but the `.env` modification time, read as metadata only, predates the snapshot. The snapshot values are therefore plausibly still current.
- [CAL-03 · NOT_VERIFIED] No effective runtime value is verified, and every database value (including `symbol_blacklist`) requires an authorization that was not granted.

### 1.3 Not read in this area

| Not read | Reason |
|---|---|
| `.env` | Only its modification time was read, as metadata. |
| `.env.example` | A permission rule blocked the read (PD-04). |
| Production database | No `symbol_blacklist`, `macro_history`, `scan_candidates`, `analysis_results` or `signals` rows were read (PD-02). |
| Other excluded material | Image filesystems; raw log lines; Paper outcomes after the 2026-08-19 research freeze (FORWARD_HOLDOUT boundary recorded in `research/governance/research_freeze.json`); sealed holdouts. |

## 2. Universe and scanner selection

### 2.1 Selection funnel

The scanner rebuilds the universe on every scan, and each later stage narrows it further:

1. **Exchange listing** (scanner, every scan). Binance Spot pairs quoted in USDT, with status TRADING and ASCII names (UNI-01).
2. **Fixed exclusions.** Three stable pairs are excluded (UNI-02). There is no rule for leveraged ETF-style coins (UNI-04).
3. **Blacklist.** Read from the database before the filters (UNI-05).
4. **Initial filters.** 24h quote volume ≥ 10M USDT and |24h move| ≥ 1%. The move threshold rises to ≥ 5% while the scanner BTC trend is strong_bearish (UNI-09, MKT-01).
5. **Analyzer eligibility, per timeframe.**
   - At least 200 closed bars, and no gaps or duplicates (UNI-12).
   - Regime routing: a momentum setup only when the symbol is bullish, a reversion setup only when it is sideways (STR-09).
6. **Signal-engine gates.**
   - The macro gate, which applies to the whole cycle (STR-11).
   - A valid order book with a finite spread ≤ 0.15% (IND-03).
   - Stop risk within the timeframe cap (UNI-11).
   - No open trade, and a 2 h symbol cooldown (UNI-18).
7. **Selection and ranking.**
   - Only rows ≤ 30 min old, through `ORDER BY symbol, total_score DESC LIMIT 200` (UNI-16).
   - Ranking by spread, then volume, then symbol, then timeframe, with one signal per ~60 s cycle (STR-13).
8. **Delivery and admission.**
   - The Telegram pause and capacity check (EXE-02).
   - Tracker admission, one trade per symbol (EXE-04).
   - Portfolio caps (RSK-01 to RSK-05).

[ARC-12 · SOURCE_VERIFIED] The scanner checks the B3 pause before scanning.
- `get_pause_state()` (`scanner/scanner_logic.py:26-29`; `shared/trading_state.py:21-47`) fails closed, and only the latest `manual_resume` allows scanning.
- It is the only pause check upstream of Telegram; the analyzer and signal_engine have none.

[ARC-04 · SOURCE_VERIFIED] Scanner housekeeping:
- The loop in `scanner/main.py` (lines 24-64) reads Binance, `symbol_blacklist` and `risk_management`, and writes `scan_candidates` and `service_heartbeats`.
- Cleanup expires `analysis_results` after 2 h and deletes `scan_candidates` after 1 h.
- The container reads the shared `.env` plus a second, exchange-specific env file (names only; contents not read); its image is `tsb-aiohttp-test-scanner:3.14.3-20260929T124120Z`.

### 2.2 Table A: universe and selection controls (complete)

"Configured" gives the 2026-09-27 snapshot value and, where cited, the `.env.example` value (via the review document). "Effective" states the class of the value in words. **No effective value is runtime-verified (CAL-03).**

| ID · class | Item | Code (file:function) | Code default | Configured | Effective | Limitations |
|---|---|---|---|---|---|---|
| [UNI-01 · SOURCE_VERIFIED] | Exchange, status, quote | `scanner/scanner_logic.py:_get_usdt_pairs` (lines 72-81; blob fa03cc2a, = ea8ae4f = main): Binance Spot exchangeInfo, `quoteAsset == 'USDT'`, `status == 'TRADING'`, ASCII symbol names | constant | — | USDT-quoted Spot pairs only (SOURCE_VERIFIED) | Scanner image content documented only (RT-39) |
| [UNI-02 · SOURCE_VERIFIED] [UNI-03 · INFERRED] | Stablecoin pairs | same function: only USDCUSDT, BUSDUSDT and TUSDUSDT are excluded | constant | — | FDUSD, USDP, EUR, PAXG and similar pairs are **not** excluded (SOURCE_VERIFIED); the 1% move filter usually removes them (INFERRED) | No general rule for pegged assets |
| [UNI-04 · SOURCE_VERIFIED] | Leveraged ETF-style coins | none | — | — | No exclusion rule (SOURCE_VERIFIED) | — |
| [UNI-05 · SOURCE_VERIFIED] [UNI-06 · NOT_VERIFIED] [UNI-07 · DOCUMENTED_ONLY] | Blacklist | `scan()`: `SELECT symbol FROM symbol_blacklist` on every scan, before the filters; a read failure aborts the scan | database table | Contents NOT VERIFIED; documented as emptied on 2026-05-17 | Blacklisted symbols are excluded at source | Database read not authorized |
| [UNI-08 · SOURCE_VERIFIED] | Whitelist / approval | `telegram/whitelist.py` `ApprovalManager.process_signal` returns `'sent_direct'` unconditionally (lines 107-111 @ bb7825f) | database table | — | No effect: dead code (SOURCE_VERIFIED) | Telegram header still advertises approval (CON-30) |
| [UNI-09 · SOURCE_VERIFIED] [UNI-10 · DOCUMENTED_ONLY] | 24h quote volume | `_passes_initial_filter`: `quoteVolume ≥ MIN_VOLUME_USDT` (`shared/config.py` blob c5c03b5, line 130) | 10,000,000; raised to 10M on 2026-04-27 | Snapshot 10M | 10M as documented; runtime value NOT VERIFIED | — |
| [UNI-09 · SOURCE_VERIFIED] | 24h price move | `abs(priceChangePercent) ≥ MIN_PRICE_CHANGE_PERCENT` (`shared/config.py` blob c5c03b5, line 131) | 1.0, hard-coded | — (not settable) | 1% (SOURCE_VERIFIED) | Also listed among the snooping/survivorship concerns (HIS-37) |
| [UNI-09 · SOURCE_VERIFIED] [MKT-01 · SOURCE_VERIFIED] | BTC stress rule | Scanner `btc_trend == 'strong_bearish'` ⇒ the absolute 24h move must be ≥ 5% | constant | — | Applied while the scanner BTC trend is strong_bearish (SOURCE_VERIFIED) | Fails open to "neutral" on error (MKT-02). The scanner filter compares `btc_trend == 'strong_bearish'` (UNI-09); the threshold list uses the shorthand strong_bear (MKT-01); the investigation reports use both spellings. |
| [UNI-10 · DOCUMENTED_ONLY] | Scan interval | `SCAN_INTERVAL_SECONDS` | 300 | `.env.example` 300; snapshot 300 | 300 s as documented; runtime value NOT VERIFIED | — |
| [IND-03 · SOURCE_VERIFIED] | Spread | `signal_engine/signal_logic.py:find_best_signal_live` @ ea8ae4f: order book valid and a finite `spread_pct ≤ MAX_SPREAD_PCT` (`shared/config.py:165`); top-of-book spread from a 20-level snapshot fetched once per symbol | 0.15 | Snapshot 0.15 | 0.15% as documented; runtime value NOT VERIFIED | One order-book snapshot is reused across timeframes (EXE-05). The legacy path has its own `MAX_SPREAD_PCT` gate after the stoch>0 gate (around `signal_logic.py:675-680` @ ea8ae4f); that legacy gate's code comment (2026-06-23 audit) calls it an execution-feasibility filter, not an edge filter |
| [UNI-11 · SOURCE_VERIFIED] | Depth / size | none; walls and the bid/ask ratio feed only the unused score (IND-02) | — | — | No depth filter (SOURCE_VERIFIED) | — |
| [UNI-11 · SOURCE_VERIFIED] | Volatility | No minimum beyond the 1% move. The upper bound is the stop-risk cap (15m 2%, 1h 4%, 4h 5%, 1d 3%) in `_calculate_levels`, which sets `stop_valid=False` | constant | — | As code (SOURCE_VERIFIED) | — |
| [UNI-12 · SOURCE_VERIFIED] [UNI-13 · INFERRED] | History and missing data | A timeframe is skipped if `len(df) < indicator_warmup_bars()` (= 200 = `CANDLES_TO_FETCH`; 201 klines are fetched, `analyzer/technical_analyzer.py:127-134`), or if `validate_ohlcv` finds gaps or duplicates | constant | — | 1d needs ≥ 200 days of listing history; 4h about 33 days (INFERRED) | Recently listed symbols are therefore absent from the longer timeframes (INFERRED) |
| [STR-05 · SOURCE_VERIFIED] [STR-06 · DOCUMENTED_ONLY] | Timeframes | `config.TIMEFRAMES` (`shared/config.py:36`); `TIMEFRAMES_LL` is defined but unused | 15m, 1h, 4h, 1d | Snapshot 15m, 4h, 1d | NOT VERIFIED (documented 15m, 4h, 1d) | `TIMEFRAMES_LL` documented but unread (CON-15) |
| [UNI-14 · SOURCE_VERIFIED] [UNI-15 · INFERRED] | Analyzer intake | `analyzer/main.py`: 50 unanalysed rows per loop, newest first, about 10 s per loop; rows purged after 1 h | constant | — | Not a hard cap (INFERRED) | — |
| [UNI-16 · SOURCE_VERIFIED] [UNI-17 · INFERRED] | Selection rows | `signal_engine/main.py:146-155` @ ea8ae4f: `ORDER BY symbol, total_score DESC LIMIT 200` over rows ≤ 30 min old with no open trade | constant | — | Alphabetical truncation above about 66 symbols × 3 timeframes (INFERRED); frequency NOT VERIFIED | Not fixed (HIS-28) |
| [STR-13 · SOURCE_VERIFIED] | Final ranking | `signal_logic._fixed_candidate_key` (lines 287-293): min(spread, −24h quote volume, symbol, timeframe); one signal per cycle of about 60 s; setup strength unused | constant | — | As code (SOURCE_VERIFIED) | Ranks execution quality, not signal strength |
| [UNI-18 · SOURCE_VERIFIED] [STR-16 · SOURCE_VERIFIED] | Daily cap | `MAX_SIGNALS_PER_DAY`, legacy path only | 5 | Snapshot 0 | No daily cap in live mode (SOURCE_VERIFIED) | — |
| [UNI-18 · SOURCE_VERIFIED] | Symbol cooldown | 2 h after any signal (`COOLDOWN_SQL`; `signal_engine/signal_logic.py:25`) | constant | — | As code (SOURCE_VERIFIED) | In off mode a cooldown read error fails open (EXE-01, HIS-27) |
| [RSK-02 · SOURCE_VERIFIED] [RSK-03 · DOCUMENTED_ONLY] | Total open positions | `trade_tracker/main.py:assess_new_trade_risk` @ bb7825f: min(`MAX_OPEN_TRADES`, `RISK_CANARY_MAX_OPEN_TRADES`), also bounded by floor(500 × 80% / 50) = 8 | 10 / 1 | 10 / 2 | **2**, or 1 when the sizing multiplier ≤ 0.5 (DOCUMENTED_ONLY); runtime value NOT VERIFIED | Code default 1 vs documented 2 (CON-16) |
| [EXE-04 · SOURCE_VERIFIED] [UNI-18 · SOURCE_VERIFIED] | Per symbol | The engine excludes any symbol with an open trade; the tracker's 10% symbol cap of $500 allows one $50 trade | — | 10% | **1 per symbol** (SOURCE_VERIFIED) | No one-per-kind rule (types are momentum/reversion); no database unique index |
| [RSK-04 · INFERRED] [RSK-05 · SOURCE_VERIFIED] | Strategy and regime caps | 40% / 50% ⇒ 4 / 5 trades; the regime key is the USDT.D trend | 40 / 50 | 40 / 50 | Never binding with 2 slots (INFERRED) | — |
| [STR-28 · SOURCE_VERIFIED] | Correlation (A42 C2) | `shared/signal_quality.CorrelatedExposurePolicy(enabled=False)`, not imported by any deployed entrypoint | — | — | **Not active** (SOURCE_VERIFIED) | — |
| [UNI-05 · SOURCE_VERIFIED] | Manual controls | Telegram `/blacklist`, `/remove_blacklist`, `/remove_whitelist` (the last moves the symbol to the blacklist) | — | — | Available to the owner (SOURCE_VERIFIED) | Effect depends on the unverified blacklist contents (UNI-06). Blacklisting a symbol also force-closes its open Paper trade in the tracker (EXE-11); `/remove_whitelist` therefore triggers this too |

**Evidence notes for Table A.**

| Rows | Commit or blob read |
|---|---|
| Scanner rows (exchange, stablecoins, blacklist, volume, move, BTC stress, scan interval) | `scanner/scanner_logic.py` blob fa03cc2a and `shared/config.py` blob c5c03b5c (7bf6214) |
| Analyzer rows (history, intake) | ea8ae4f |
| Signal-engine rows (spread, selection rows, ranking, daily cap, cooldown, correlation) | ea8ae4f |
| Telegram rows (whitelist, manual controls) | bb7825f |
| Tracker rows (total positions, per symbol, strategy and regime caps) | bb7825f |

- **Runtime verification:** none of the rows (RT-17). The scanner image content is documented only (RT-39).
- **Configured values:** from the 2026-09-27 snapshot (CAL-02).

## 3. Analyzer intake, selection query, ranking and eligibility

### 3.1 Analyzer intake and per-timeframe eligibility

[UNI-14 · SOURCE_VERIFIED] Intake.
- `analyzer/main.py` (ea8ae4f) takes 50 unanalysed `scan_candidates` rows per loop, newest first, at about 10 s per loop.
- Candidate rows are purged after 1 h.
- Evidence: `analyzer/main.py` · loop query · ea8ae4f · runtime-verified no.

[UNI-15 · INFERRED] At that rate, the 50-row intake is not a hard cap on coverage.

For each timeframe, the analyzer:
1. drops the candidate if fewer than 200 closed bars are available, or if `validate_ohlcv` finds gaps or duplicates (UNI-12);
2. classifies the symbol's own regime (STR-09);
3. evaluates only the setup that regime allows: momentum when bullish, reversion when sideways, and none when bearish or volatile.

The order-book score and the legacy indicator score are also computed. Neither is a live decision criterion, although `total_score` still orders timeframes within a symbol in the selection query (section 3.3; section 10).

### 3.2 Signal-engine gates, in order

[EXE-01 · SOURCE_VERIFIED] signal_engine polls every ~60 s (code read at ea8ae4f) and applies these gates in order:
1. The macro gate, applied to the whole cycle (STR-11, section 8).
2. A setup is present.
3. The order book is valid, with a finite spread ≤ 0.15% (IND-03).
4. `stop_valid`, i.e. the stop risk is within its timeframe cap (UNI-11).
5. No open trade for the symbol, and a 2 h symbol cooldown. In off mode, a cooldown read error yields an empty set and fails open (`signal_logic.py:424-432`).
6. The learned gate, which is off.
7. Ranking (STR-13).
8. One transaction that inserts the `signals` row and the outbox `signal.ready` event.

signal_engine has no pause check.

### 3.3 Selection query and truncation

[UNI-16 · SOURCE_VERIFIED] The candidate query (`signal_engine/main.py:146-155` @ ea8ae4f):
- reads `analysis_results` rows at most 30 min old, for symbols without an open trade;
- orders them by `ORDER BY symbol, total_score DESC LIMIT 200`.

Effects:
- Because the sort is by symbol first, `total_score` only orders timeframes within a symbol. That score still carries the frozen `indicator_weights` (LRN-16).
- The 200-row limit truncates the candidate set alphabetically.

[UNI-17 · INFERRED] Truncation bites above about 66 symbols × 3 timeframes (about 200 rows). How often it happens is NOT VERIFIED, because no `analysis_results` rows were read.

[HIS-28 · SOURCE_VERIFIED] The alphabetical `LIMIT 200` and the lexical tie-breaks are a recorded selection-bias defect (A43 §A.2 L51-52). It is not fixed (`signal_engine/main.py` around L153).

### 3.4 Ranking

[STR-13 · SOURCE_VERIFIED] Live ranking uses `signal_logic._fixed_candidate_key` (lines 287-293), the A44 "production_parity" policy.
- **Sort key:** min(spread, −24h quote volume, symbol, timeframe). The tightest relative spread wins first, then the highest 24h quote volume, then the symbol name (a lexical tie-break), then the timeframe.
- **Rate:** one signal is emitted per ~60 s cycle.
- **What it measures:** execution quality, not signal strength; the setup's strength plays no part.
- **Cooldown:** a 2 h symbol cooldown is hard-coded (`signal_logic.py:25`, `COOLDOWN_SQL`).
- **Evidence:** `signal_engine/signal_logic.py` · `_fixed_candidate_key` · ea8ae4f · runtime-verified no.

### 3.5 Caps, cooldown and legacy-only limits

[UNI-18 · SOURCE_VERIFIED] Live-path caps:
- The setup strength is unused in ranking (STR-13).
- One signal per cycle of about 60 s.
- `MAX_SIGNALS_PER_DAY` applies to the legacy path only (code 5, snapshot 0), so live mode has no daily cap.
- A 2 h symbol cooldown follows any signal.
- One open trade per symbol: the engine excludes symbols with an open trade, and the tracker's 10% symbol cap of $500 allows one $50 trade.
- No correlation cap; A42 C2 is inactive (STR-28).

[STR-16 · SOURCE_VERIFIED] Legacy-only filters are inactive on the live path:
- the 4h primary-timeframe ban (`signal_logic.py:631`; its code comment cites 275 post-rebuild trades from 2026-04-22 to 05-16);
- the 1d bearish/sideways raw-score rule (around :655);
- the stoch>0 gate (:671; its code comment records the 2026-06-23 audit, n = 2,518, as loss-reducing but still negative after fees);
- the bullish/volatile majority filters and `trend_ok` (EMA200);
- the BTC-crash pause `_is_btc_crashing`, the BTC bonus and the TF bonus;
- `GLOBAL_LOSS_COOLDOWN_HOURS` 6 (snapshot 0) and `MAX_SIGNALS_PER_DAY` 5 (snapshot 0).

Statements that describe these filters as live are contradicted by the code (CON-12).

## 4. Capacity and portfolio constraints that limit coverage

Coverage is limited by the scanner and engine filters, and also by delivery and admission capacity downstream.

| ID · class | Constraint | Source · symbol · commit | Limitations |
|---|---|---|---|
| [EXE-02 · SOURCE_VERIFIED] | Telegram `can_deliver_candidate` blocks while paused (fails closed) and above capacity min(10, `RISK_CANARY_MAX_OPEN_TRADES`), whose code default is 1. A refused candidate is acknowledged and **lost**, not queued. | `telegram/main.py:364-382` (paused branch 268-275) · bb7825f | Runtime capacity value NOT VERIFIED |
| [EXE-03 · DOCUMENTED_ONLY] | `RISK_CANARY_MAX_OPEN_TRADES` is 2 in the 2026-09-27 snapshot and in `.env.example`. | Snapshot; `docs/ops/ENV_EXAMPLE_REVIEW_2026-10-18.md` | Effective value NOT VERIFIED; code default 1 vs documented 2 (CON-16) |
| [EXE-04 · SOURCE_VERIFIED] | Tracker admission keeps the latest signal per symbol within 2 h, one open trade per symbol, and one per (symbol, timeframe) per candle interval. There is no flash/scalp/swing taxonomy (trade types are momentum and reversion), no one-per-kind rule, and no database unique index enforcing one trade per symbol. | `trade_tracker/main.py:register_new_signals` (705-904) · bb7825f | — |
| [RSK-01 · SOURCE_VERIFIED] | Always blocking: invalid risk state, a persisted pause, and the exposure caps (gross 80%, symbol 10%, strategy 40%, regime 50%). In observe mode the daily −3%, weekly −10%, drawdown 15% and 7-loss-streak checks are only recorded as `risk.observed`. | `evaluate_with_policy` via `assess_new_trade_risk` (922-1006) and `record_risk_decision` (1041-1093) · bb7825f | Pause and risk state NOT VERIFIED (RT-46) |
| [RSK-02 · SOURCE_VERIFIED] | Capacity = min(`MAX_OPEN_TRADES` 10, `RISK_CANARY_MAX_OPEN_TRADES`), also bounded by floor(500 × 80% / 50) = 8. Economic-halt sizing multipliers (drawdown caution/warning, weekly reduce/minimum) do not change the notional, but can lower the capacity used by the `max_open_trades` check. | `trade_tracker/main.py:assess_new_trade_risk`; capacity checks at `trade_tracker/main.py:708-716` and `:752-756`; `shared/economic_halt_policy.py:18-20` · bb7825f | Multiplier state NOT VERIFIED |
| [RSK-03 · DOCUMENTED_ONLY] | Effective capacity is **2 open positions**, or 1 when the sizing multiplier is ≤ 0.5. | as cited from `docs/ops/PAPER_ECONOMIC_OBSERVATION.md` | Runtime value NOT VERIFIED |
| [RSK-04 · INFERRED] | The strategy (40%) and regime (50%) caps correspond to 4 and 5 trades and never bind with 2 slots. | derived from RSK-01 and RSK-03 | — |
| [RSK-05 · SOURCE_VERIFIED] | The regime-cap key is `COALESCE(macro_snapshot->>'usdtd_trend', market_condition)` (`assess_new_trade_risk` → `regime_open_count` → `evaluate_new_trade` `regime_concentration_limit`). Per `economic_halt_policy.PORTFOLIO_LIMITS`, this portfolio limit blocks even in observe mode. | `trade_tracker/main.py`; `shared/economic_halt_policy.py` · bb7825f | Never binding with 2 slots (RSK-04) |
| [RSK-06 · INFERRED] | Capital utilisation is at most 20% (2 × $50 of the $500 virtual capital). | derived from RSK-03 and the fixed $50 notional (EXE-12) | — |

Sizing is a fixed `TRADE_AMOUNT_USDT` of $50 (EXE-12); no context input changes it (MKT-12).

## 5. Coverage verdict

[UNI-19 · INFERRED] The bot evaluates a restricted, dynamic subset of eligible spot pairs, not all of them.
- **Base universe:** Binance Spot USDT pairs with ≥ 10M USDT 24h quote volume and a ≥ 1% 24h move (≥ 5% under BTC stress), minus the blacklist.
- **Narrowed by:** the steps in the table below.
- **Multi-asset by design:** there is no BTC-only rule.
- **Bias towards majors:** ranking by tightest relative spread, then volume, systematically favours the deepest majors (BTC/ETH-type) whenever they have a valid setup.

| Narrowing step | Effect on coverage | ID |
|---|---|---|
| ≥ 200 closed bars per timeframe | Recently listed symbols drop out of the longer timeframes | UNI-12, UNI-13 |
| Regime-routed setups | Bearish and volatile symbols produce no candidate | STR-09, MKT-09 |
| Spread ≤ 0.15% | Wide-spread symbols are removed | IND-03 |
| Stop-risk cap per timeframe | Very volatile setups are rejected | UNI-11 |
| 200-row alphabetical cap | Symbols late in the alphabet can be cut | UNI-16, UNI-17 |
| One signal per ~60 s cycle | At most one new candidate per cycle | STR-13 |
| 2 h cooldown, one trade per symbol | Repeat candidates on a symbol are excluded | UNI-18, EXE-04 |
| Capacity of 2 open positions | Candidates refused at capacity are lost | RSK-03, EXE-02 |

**Combined capacity effect (INFERRED from RSK-03, EXE-02 and EXE-04):** at most two Paper positions are open at a time, on two different symbols. A candidate refused at capacity is acknowledged and lost, not queued.

Limitations of this verdict:
- Every threshold's effective value is NOT VERIFIED (CAL-03).
- How often the 200-row truncation binds is NOT VERIFIED (UNI-17).
- [HIS-37 · DOCUMENTED_ONLY] The |24h| ≥ 1% universe filter is itself listed among the data-snooping and survivorship concerns: A45 §A45-C W12/W14, P3 L30-31, P6 L48 and L55, and phase16 L16-18.
- Whether the restricted universe and the 2 × $50 capacity are intended is an open owner question (OQ-07, section 12).

## 6. Market-context usage matrix

### 6.1 Table B: every context input and where it acts (complete)

Index notation in the formulas: `c[0]` is the oldest close in the window and `c[-1]` the newest.

| ID · class | Input | Collected / provider | Refresh | Formula and lookback | DB storage | Selection | Entry | Sizing | Exit | Info-only | Active |
|---|---|---|---|---|---|---|---|---|---|---|---|
| [MKT-01 · SOURCE_VERIFIED] | BTCUSDT (scanner) | `scanner_logic._update_btc_trend`; Binance klines | Every scan (300 s), no cache | Last 10 closed 4h bars: Δ = (c[-1] − c[0]) / c[0] over 9 intervals = 36 h; > 3 strong_bull, > 1 bull, < −3 strong_bear, < −1 bear | `scan_candidates.data->>'btc_trend'` (kept 1 h) | **Yes**: strong_bear ⇒ absolute 24h move ≥ 5% | No (only the legacy `_is_btc_crashing`) | No | No | No | **Yes**, unconditional |
| [MKT-03 · SOURCE_VERIFIED] [MKT-04 · DOCUMENTED_ONLY] | BTCUSDT (macro) | `macro_context._btc_eth_change`; Binance | At most hourly (`MACRO_CACHE_HOURS=1`), refreshed lazily in cycles that have candidates | 4h bars, limit 20, closed only, ≥ 18 required; Δ = c[-1] vs c[-18] (17 intervals = 68 h); ≤ −5 strong_bear, < −1 bear, > 5 strong_bull, > 1 bull | `macro_history.btc_trend`; `signals.macro_snapshot` (btc_change_pct, btc_trend) | No | **Yes**: strong_bear ⇒ the whole cycle is blocked | No | No | No | DOCUMENTED_ONLY (needs `LIVE_LEARNING_MODE=true`) |
| [MKT-05 · SOURCE_VERIFIED] | ETHUSDT | Same as the macro BTC trend | Same | Same | `macro_history.eth_trend`; snapshot | No | No (not used in `should_block`) | No | No | **Yes** | Stored only |
| [MKT-06 · SOURCE_VERIFIED] | BTC.D | `_cg_global`: CoinGecko `/api/v3/global` `market_cap_percentage.btc`, no credential | At most hourly | Raw percentage | `macro_history.btc_d`; snapshot | No | No | No | No | **Yes** | Stored only |
| [MKT-07 · SOURCE_VERIFIED] [RSK-05 · SOURCE_VERIFIED] | USDT.D | `_cg_global` `.usdt` | At most hourly | Δ = now − mean(`macro_history.usdt_d` where date ≥ `CURRENT_DATE − 3`): up to 4 per-day last values, including today's previous refresh (no rows ⇒ Δ = 0); ≥ 0.5 pp rising_fast; > 0.05 rising; < −0.05 falling; else flat | `macro_history.usdt_d`; snapshot (usdt_d, usdtd_3d_delta, usdtd_trend) | No | **Yes**: rising_fast ⇒ the cycle is blocked; also the tracker's regime-cap key (never binding) | No | No | No | DOCUMENTED_ONLY (needs `LIVE_LEARNING_MODE=true`) |
| [MKT-08 · SOURCE_VERIFIED] | BTC/ETH relative strength | — | — | Not implemented | — | — | — | — | — | — | **Absent** |
| [MKT-09 · SOURCE_VERIFIED] [STR-09 · SOURCE_VERIFIED] | Asset regime (per symbol) | `shared/regime.classify_regime`, on each symbol's own timeframe bars | Every analysis | Bullish/bearish: ADX14 ≥ 25 plus the sign of the 5-bar EMA20 slope plus close vs EMA20; sideways: ADX < 20 and the 100-bar ATR% percentile ≤ 0.75; otherwise volatile | `analysis_results.analysis_data` (regime, market_condition); `signals.market_condition` | Indirect (eligibility) | **Yes**: momentum only if bullish, reversion only if sideways (`simple_entry.detect_trade_setup`) | No | Indirect (trade_type sets the stop structure) | No | **Yes** (code) |
| [MKT-10 · SOURCE_VERIFIED] | macro_state `usdtd_*` | `macro_state_key` | Every cycle | "usdtd_" + trend | `learned_gates.macro_state` (written only by the stopped learner) | No | Learned gates OFF (documented); used only as the exploration key | No | No | In effect | Inert |

### 6.2 Evidence and activation notes

- **Commits:**
  - the scanner row uses `scanner/scanner_logic.py` blob fa03cc2a;
  - the macro rows use `shared/macro_context.py` blob 9099d1d1, identical at 63da7d3, ea8ae4f, bb7825f and main;
  - the regime row uses `shared/regime.py` from 63da7d3, byte-identical at ea8ae4f;
  - the regime-cap use of USDT.D is in `trade_tracker/main.py` at bb7825f.

  Runtime-verified: no (RT-17).
- **Activation:**
  - The scanner BTC filter acts whatever the configuration. The per-symbol regime is computed on every analysis, but its setup routing gates entry only on the live path, i.e. when `LIVE_LEARNING_MODE` is set (STR-01, STR-04).
  - The macro rows act only on the live path, i.e. only when `LIVE_LEARNING_MODE` is set. That flag is documented as true in the 2026-09-27 snapshot (STR-02); its runtime value is NOT VERIFIED (STR-04).
- **Sizing:** no context input has any effect on sizing (MKT-12).
- **Exits:** context reaches exits only indirectly, through the stop structure that the trade type implies (MKT-09).

## 7. Roles of BTC, ETH, BTC.D, USDT.D and the regime

### 7.1 BTC in the scanner (selection only)

[MKT-01 · SOURCE_VERIFIED] The scanner trend selects only; it plays no part in entry.
- **Function:** `scanner_logic._update_btc_trend` (lines 107-142) reads Binance klines on every scan (300 s), with no cache.
- **Computation:** the change across the last 10 closed 4h bars, 9 intervals = 36 h.
  - Labels: > 3 strong_bull, > 1 bull, < −3 strong_bear, < −1 bear.
- **Storage:** `scan_candidates.data->>'btc_trend'`, kept 1 h.
- **Use:**
  - Selection only: strong_bear raises the absolute 24h move filter from 1% to 5%.
  - Not an entry input, except in the legacy `_is_btc_crashing` (inactive on the live path, STR-16).
- **Activation:** unconditional.
- **Label spelling:** The scanner filter compares `btc_trend == 'strong_bearish'` (UNI-09); the threshold list uses the shorthand strong_bear (MKT-01); the investigation reports use both spellings.

[MKT-02 · SOURCE_VERIFIED] The scanner BTC trend **fails open**.
- An exception, or fewer than 10 bars, sets the label to "neutral" (`scanner_logic.py:125-148`).
- This silently disables the stress filter.

### 7.2 BTC in the macro gate (entry veto)

[MKT-03 · SOURCE_VERIFIED] The macro trend vetoes entry.
- **Function:** `macro_context._btc_eth_change`.
- **Bars:** Binance 4h bars, limit 20, closed bars only, with at least 18 required.
- **Computation:** Δ = c[-1] vs c[-18], i.e. 17 intervals = 68 h.
  - Labels: ≤ −5 strong_bear, < −1 bear, > 5 strong_bull, > 1 bull.
- **Refresh:** at most hourly (`MACRO_CACHE_HOURS=1`), lazily, in cycles that have candidates.
- **Storage:** `macro_history.btc_trend` and `signals.macro_snapshot` (btc_change_pct, btc_trend).
- **Use:** strong_bear blocks the whole cycle.

[MKT-04 · DOCUMENTED_ONLY] The macro gate is active only if `LIVE_LEARNING_MODE=true` (2026-09-27 snapshot). The runtime value is NOT VERIFIED (STR-04).

| Property | Scanner BTC trend (MKT-01) | Macro BTC trend (MKT-03) |
|---|---|---|
| Function and code | `scanner_logic._update_btc_trend`, blob fa03cc2a | `macro_context._btc_eth_change`, blob 9099d1d1 |
| Bars | Last 10 closed 4h bars | 4h, limit 20, closed only, ≥ 18 required |
| Window | 9 intervals = 36 h | 17 intervals = 68 h |
| Change | (c[-1] − c[0]) / c[0] | c[-1] vs c[-18] |
| Thresholds | > 3 strong_bull; > 1 bull; < −3 strong_bear; < −1 bear | > 5 strong_bull; > 1 bull; ≤ −5 strong_bear; < −1 bear |
| Refresh | Every scan (300 s), no cache | At most hourly, lazily in cycles with candidates |
| Stored in | `scan_candidates.data->>'btc_trend'` (1 h) | `macro_history.btc_trend`; `signals.macro_snapshot` |
| Decision use | Selection: strong_bear ⇒ absolute 24h move ≥ 5% | Entry: strong_bear blocks the whole cycle |
| Failure mode | Fails open to "neutral" (MKT-02) | Fails closed after 2 h of staleness (MKT-13) |
| Activation | Unconditional | Live path only (MKT-04) |

The two definitions share the same labels but differ in window and thresholds. A45 and the `_is_btc_crashing` docstring describe the BTC trend as "40 h", while the macro comment says "~3 days (18×4h)" (CON-27).

### 7.3 ETH (collected, not used)

[MKT-05 · SOURCE_VERIFIED] ETHUSDT is collected but unused.
- **Computation:** the same as the macro BTC trend.
- **Storage:** `macro_history.eth_trend` and the signal snapshot.
- **Use:** none. `should_block` does not read it, so it is information only.

### 7.4 BTC dominance (collected, not used)

[MKT-06 · SOURCE_VERIFIED] BTC.D is collected but unused.
- **Source:** `_cg_global` reads CoinGecko `/api/v3/global` `market_cap_percentage.btc`, with no credential, at most hourly.
- **Value:** stored as a raw percentage in `macro_history.btc_d` and the snapshot.
- **Use:** none. It is information only.

### 7.5 USDT dominance (entry veto and regime-cap key)

[MKT-07 · SOURCE_VERIFIED] The full USDT.D calculation, in `shared/macro_context.py`:
1. **Read.** `_cg_global` takes the `.usdt` market-cap percentage from CoinGecko `/api/v3/global`, at most hourly.
2. **Store.** The value goes into `macro_history.usdt_d`. Each hourly refresh overwrites that day's row (CON-28).
3. **Baseline.** The mean of `macro_history.usdt_d` over rows with date ≥ `CURRENT_DATE − 3`: up to 4 per-day last values (D−3 to D), including today's previous refresh.
4. **Change.** Δ = current value − baseline. With no rows, Δ = 0.
5. **Classify.**
   - Δ ≥ 0.5 pp (`USDTD_SPIKE_PP` 0.5, snapshot 0.5) → rising_fast.
   - Δ > 0.05 → rising.
   - Δ < −0.05 → falling.
   - Otherwise flat. The 0.05 band is the hard-coded `FLAT_EPS` (STR-11).
6. **Snapshot.** `usdt_d`, `usdtd_3d_delta` and `usdtd_trend` are written to `signals.macro_snapshot`.
7. **Uses.**
   - rising_fast blocks the whole cycle through `should_block` (live path only, MKT-04).
   - `usdtd_trend` is the tracker's regime-cap key (RSK-05). That cap never binds with 2 slots (RSK-04).
   - "usdtd_" + trend is the `macro_state` key (MKT-10).

Data-quality caveats specific to USDT.D:
- A missing key is saved as 0.0 and pollutes the next ~3 days' baseline (MKT-15).
- An empty history reads "flat" (MKT-15).
- "Today" is computed in UTC but compared with the database's `CURRENT_DATE`, so a timezone mismatch is possible (CON-28).
- The CoinGecko input is not point-in-time (STR-12).

### 7.6 BTC/ETH relative strength

[MKT-08 · SOURCE_VERIFIED] BTC/ETH relative strength is not implemented anywhere. No code computes it, stores it or uses it.

### 7.7 Per-symbol regime

[MKT-09 · SOURCE_VERIFIED] The per-symbol regime is computed by `shared/regime.classify_regime` on each symbol's own timeframe bars, at every analysis.
- **Rules:** as in STR-09 below.
- **Indicator periods:** ADX14, EMA20 and ATR14 (IND-01).
- **Storage:** `analysis_results.analysis_data` (regime, market_condition) and `signals.market_condition`.
- **Effect on selection:** indirect, through eligibility.
- **Effect on entry:** it routes setups on the live path (STR-01, STR-04). Momentum is allowed only when bullish and reversion only when sideways (`simple_entry.detect_trade_setup`).
- **Effect on exits:** only indirect. The trade type sets the stop structure: stop = min(level − 0.25·ATR, entry − 1.0·ATR), where the level is the prior 20-bar high for momentum or the 20-bar low for reversion (IND-09).
- **Effect on sizing:** none.
- **Regime cap:** `market_condition` is also the fallback key when the snapshot lacks `usdtd_trend` (RSK-05).

[STR-09 · SOURCE_VERIFIED] The regime rules (`shared/regime.py:classify_regime`, lines 10-60):

| Regime | Rule | Setup produced |
|---|---|---|
| Bullish | ADX14 ≥ 25 AND 5-bar EMA20 slope > 0 AND close > EMA20 | Momentum |
| Bearish | The mirror image of bullish | None |
| Sideways | ADX < 20 AND the 100-bar percentile of ATR/close ≤ 0.75 | Reversion |
| Volatile | Everything else | None |

The rules are not env-settable. "Validated" in the commit title means point-in-time and input validation, not economic validation (STR-10).

### 7.8 macro_state

[MKT-10 · SOURCE_VERIFIED] `macro_state` is inert while learned gates are off.
- `macro_state_key` builds "usdtd_" + trend on every cycle.
- `learned_gates.macro_state` is written only by the stopped learner.
- With learned gates off, the key is used only for the exploration hash.

## 8. Actual decision gates and the decision trace

### 8.1 Which selector runs

- [STR-01 · SOURCE_VERIFIED] `signal_engine/main.py:173-176` selects the decision path.
  - It calls `find_best_signal_live` when `LIVE_LEARNING_MODE` is set, otherwise the legacy `find_best_signal`. The code default is false (`shared/config.py:74` at ea8ae4f).
  - The flag selects the rule-based setups and the `fixed_execution_quality_v1` selection policy.
  - Despite its name, it runs no learning and reads no learner table.
- [STR-02 · DOCUMENTED_ONLY] The 2026-09-27 snapshot records `LIVE_LEARNING_MODE=true`.
  - The live path is therefore presumed active (STR-03).
- [STR-04 · NOT_VERIFIED] The runtime value of `LIVE_LEARNING_MODE` was not read.
  - If it were false, the legacy `find_best_signal` would select instead (STR-01).
  - In that case the macro gate would not run (MKT-04).

### 8.2 Decision trace on the live path

[MKT-11 · SOURCE_VERIFIED] (code at ea8ae4f)
1. `signal_engine/main.py:main` builds `MacroContext(AsyncClient('',''))`, a Binance client constructed with empty credential strings.
2. With `LIVE_LEARNING_MODE` set, it calls `find_best_signal_live`.
3. That calls `macro.should_block_now()`, which in turn calls `should_block(btc_trend, usdtd_trend)`.
4. A block returns `None`: no signal is emitted, and every candidate is marked `macro_block`.

### 8.3 The macro gate

[STR-11 · SOURCE_VERIFIED] The macro gate is in `shared/macro_context.py`, lines 10-41 and 96-110.

It blocks **all** candidates in a cycle if any one of these holds:
1. the BTC 4h change over 18 closed bars is ≤ −5% (strong_bear);
2. USDT.D minus its 3-day mean is ≥ +0.5 pp (rising_fast);
3. the macro data are older than 2 h, or there is no valid snapshot. This condition fails closed.

Other properties:
- a 1 h cache;
- `FLAT_EPS` 0.05, hard-coded.

Parameter values:

| Parameter | Code default | `.env.example` | Snapshot |
|---|---|---|---|
| `USDTD_SPIKE_PP` | 0.5 | not listed | 0.5 |
| `MACRO_CACHE_HOURS` | 1 | 1 | 1 |
| `MACRO_MAX_STALE_HOURS` | 2 | 2 | 2 |

- The gate acts on the live path only.
- Its effective parameter values are NOT VERIFIED (CAL-03).
- It is a cycle-level veto. It never ranks or sizes.

[STR-12 · INFERRED] The macro gate's CoinGecko input is not point-in-time, so the gate cannot be replayed historically.

[ECO-02 · INFERRED] Context indicators act only as vetoes (BTC, USDT.D) or are only collected (ETH, BTC.D). The value of the gate itself has never been verified, and it cannot be replayed.

### 8.4 Complete gate map

| # | Gate | Stage · code | Condition | Effect | Failure mode | Activation | IDs |
|---|---|---|---|---|---|---|---|
| 1 | B3 pause | Scanner `get_pause_state()` | Paused unless the latest record is `manual_resume` | No scan | Fails closed | Always | ARC-12 |
| 2 | Universe filters | Scanner `_get_usdt_pairs`, `_passes_initial_filter`, `scan()` | USDT, TRADING, ASCII; stable trio out; blacklist; volume ≥ 10M; move ≥ 1% | Symbol is not a candidate | Read failures abort the scan (fail-closed) | Always | UNI-01 to UNI-09, MKT-16 |
| 3 | BTC stress | Scanner `_update_btc_trend` | strong_bear ⇒ move ≥ 5% | Fewer candidates | Fails open to "neutral" | Always | MKT-01, MKT-02 |
| 4 | History and data quality | Analyzer `indicator_warmup_bars()`, `validate_ohlcv` | < 200 closed bars, gaps or duplicates | Timeframe skipped | Fails closed | Always | UNI-12 |
| 5 | Regime routing | Analyzer `classify_regime`, `detect_trade_setup` | Bullish → momentum; sideways → reversion | No setup otherwise | — | Computed always; gates entry only on the live path (STR-01, STR-04) | STR-09, MKT-09 |
| 6 | Macro gate | Engine `should_block_now()` / `should_block()` | BTC strong_bear, USDT.D rising_fast, or data older than 2 h | Whole cycle blocked | Staleness fails closed; missing-key and empty-history holes fail open | Live path only | STR-11, MKT-11, MKT-13, MKT-15 |
| 7 | Order book and spread | Engine `find_best_signal_live` | Valid book, finite spread ≤ 0.15% | Candidate rejected | Fails closed | Live path | IND-03, MKT-16 |
| 8 | Stop validity | Analyzer `_calculate_levels`; engine `stop_valid` check | Risk > 2/4/5/3% for 15m/1h/4h/1d | Candidate rejected | `stop_valid=None` passes; only an explicit False rejects (IND-09) | Live path | UNI-11 |
| 9 | Open trade and cooldown | Engine `COOLDOWN_SQL` | Open trade, or less than 2 h since the last signal | Symbol excluded | A cooldown read error fails open in off mode | Live path | UNI-18, EXE-01 |
| 10 | Learned gate | Engine `LEARNED_GATES_SQL` | Throttled cell | Candidate excluded | — | Off (`LEARNING_GATES_ENABLED` false, documented) | STR-19, MKT-10 |
| 11 | Selection and ranking | Engine query; `_fixed_candidate_key` | LIMIT 200 sorted by symbol; min(spread, −volume, symbol, timeframe) | One signal per cycle | — | Live path | UNI-16, STR-13 |
| 12 | Delivery | Telegram `can_deliver_candidate` | Paused, or capacity full | Refused and lost | Fails closed on pause | Always | EXE-02 |
| 13 | Admission and portfolio | Tracker `register_new_signals`, `assess_new_trade_risk` | One per symbol; exposure caps; invalid risk state; persisted pause | Trade not opened | Observe mode only records the loss checks | Always | EXE-04, RSK-01, RSK-05 |

Code commits:
- scanner gates: the scanner blobs (RT-39);
- analyzer and engine gates: ea8ae4f;
- Telegram and tracker gates: bb7825f.

Runtime-verified: no.

### 8.5 Influence on entry, exit, sizing and risk

[MKT-12 · SOURCE_VERIFIED] Downstream influence of context inputs:
- **Sizing** is fixed by `TRADE_AMOUNT_USDT`; the tracker never reads `size_multiplier`.
- **Exits** take no macro, BTC or regime input: none in the tracker, the price stream, `triple_barrier`, `partial_exits`, `signal_stop` or `entry_execution` (repository grep).
- **Learner:** `research/continuous_learner.py` also imports `should_block`, but that service is stopped (documented).

| Input | Selection | Entry | Sizing | Exit | Risk / portfolio |
|---|---|---|---|---|---|
| Scanner BTC trend | Stress filter (≥ 5% move) | No | No | No | No |
| Macro BTC trend | No | Cycle veto (strong_bear) | No | No | No |
| USDT.D | No | Cycle veto (rising_fast) | No | No | Regime-cap key, never binding (RSK-05, RSK-04) |
| ETH trend | No | No | No | No | No |
| BTC.D | No | No | No | No | No |
| Per-symbol regime | Indirect (eligibility) | Setup routing | No | Indirect (stop structure) | Fallback regime-cap key (RSK-05) |
| macro_state | No | No (exploration key only) | No | No | No |

### 8.6 Integrity mode

[STR-33 · SOURCE_VERIFIED] A43 signal integrity is flagged off.
- In enforce mode (`SIGNAL_INTEGRITY_MODE=enforce`) it provides candle identity, ≤ 1-bar freshness and an insert-once `setup_key`. It comes from the A44 signal identity work: commit eb68e42, migration 011.
- The default is off (`shared/config.py:118` at ea8ae4f) and Compose does not set the mode.
- In enforce mode, the freshness rule (`shared/signal_identity.py:186-200`) would add the only last-candle age check (ARC-13).

[STR-34 · DOCUMENTED_ONLY] The documents say that no enforce window was authorized. The effective value is NOT VERIFIED (likely off).

## 9. Data sources, refresh, staleness and failure behaviour

### 9.1 Data sources

[ARC-03 · SOURCE_VERIFIED] Market-data clients:
- **Binance REST** through python-binance AsyncClient:
  - scanner: `scanner_logic.py:74-124`;
  - analyzer: `technical_analyzer.py:127-134` (201 klines) and `orderbook_analyzer.py:19` (20-level order book);
  - macro context: `macro_context.py:53-63`.
- **CoinGecko** `/api/v3/global` for USDT.D and BTC.D (`macro_context.py:28-33`), called with blocking urllib and no credential.
- **Tracker** (entry admission and open-trade tracking): public REST `ticker/price`, `exchangeInfo` and `klines`, plus the Binance WebSocket aggTrade stream for symbols with open trades.
- **Absent:** there is no fear-and-greed or CoinMarketCap client. The CoinMarketCap and CoinGecko credential variables are set blank in Compose (RT-25).

### 9.2 Refresh cadence

| Input | Refresh | Cache | Staleness or failure rule | IDs |
|---|---|---|---|---|
| Exchange listing, 24h statistics (`quoteVolume`, `priceChangePercent`), blacklist | Every scan (300 s) | None | A read failure aborts the scan | UNI-01, UNI-05, UNI-09, MKT-16 |
| Scanner BTC trend | Every scan | None | An error gives "neutral" (fails open) | MKT-01, MKT-02 |
| Klines for analysis | Each analysis (201 fetched, closed bars only) | — | Gaps, duplicates and NaN are rejected; the last candle's age is not checked in off mode | ARC-13, EXE-09 |
| Order book | One 20-level snapshot per symbol, reused across timeframes | — | Invalid, NaN or missing values are rejected | EXE-05, MKT-16 |
| Macro BTC and ETH (Binance); BTC.D and USDT.D (CoinGecko) | At most hourly, lazily in cycles with candidates | 1 h | Blocks when the last valid snapshot is more than 2 h old or absent | MKT-13 |
| Candidate rows | `analysis_results` expire after 2 h; `scan_candidates` are deleted after 1 h; the engine reads rows ≤ 30 min old | — | — | ARC-04, UNI-16 |

### 9.3 Failure and staleness behaviour

[MKT-13 · SOURCE_VERIFIED] The macro gate fails closed (`shared/macro_context.py` blob 9099d1d1).
- **Refresh failure:** any CoinGecko, Binance or database exception, or fewer than 18 closed bars, makes the refresh return False. The old state is kept.
- **Blocking:** the gate blocks once now − last_valid exceeds `MACRO_MAX_STALE_HOURS` (2 h), or when no valid snapshot exists.
- **Retry:** 1 h after the last attempt, or on every cycle while there is no state.
- **CoinGecko client:** called with blocking urllib.
- Runtime-verified: no.

[MKT-14 · INFERRED] Decisions can therefore use macro state up to 2 h old, built from closed 4h bars. That is about 6 h of signal age at worst.

[MKT-15 · INFERRED] There are fail-open holes:
- **Missing key:** a missing `usdt` or `btc` key returns `.get(..., 0)` = 0.0 without an exception.
  - USDT.D then reads "falling", so the gate passes.
  - The 0 is saved, polluting the next ~3 days' baseline.
- **Empty history:** an empty `macro_history` gives "flat".
- **Idle periods:** long idle periods skip refreshes.

[MKT-16 · SOURCE_VERIFIED] Other inputs fail closed:
- exchange, ticker or blacklist read failures abort the scan, so no new candidates are produced;
- invalid, NaN or missing spread or order-book values are rejected;
- missing volume ranks last.

The scanner BTC trend is the exception: it fails open to "neutral" (MKT-02).

[ARC-13 · SOURCE_VERIFIED] Market-data safety:
- Only closed candles are used. Gaps, duplicates and NaN are rejected (`shared/ohlcv.py:26-83`).
- The only age check on the last candle is the freshness rule of integrity enforce mode (`shared/signal_identity.py:186-200`).
- Stale macro data block signals (`MACRO_MAX_STALE_HOURS=2`).

[EXE-09 · SOURCE_VERIFIED] Freshness in off mode:
- Only two ages are checked: the 30-minute age of the analysis row and the 2 h signal window.
- Candle age is never checked, so a 1d bar can be about 24 h old at signal time.

[EXE-05 · SOURCE_VERIFIED] Candle closure and order-book timing:
- `shared/ohlcv.py:closed_klines` keeps rows with `close_time < now` on the host clock.
- Breakout and volume baselines exclude the current bar.
- The order book is a single "now" snapshot, reused across timeframes.

[EXE-06 · INFERRED] There is no exchange server-time synchronisation, so host clock skew could admit a forming bar.

### 9.4 Data-quality limits (summary)

1. **Not point-in-time.** CoinGecko global data cannot be replayed, so the macro gate cannot be evaluated historically (STR-12). Its value has never been verified (ECO-02).
2. **Day-row overwrite.** Each hourly refresh overwrites the current day's `macro_history` row, while the docstring promises a daily snapshot (CON-28).
3. **Window includes today.** The "3-day" mean spans D−3 to D, including today's previous refresh (MKT-07, CON-28).
4. **Timezone.** "Today" is computed in UTC but compared with the database's `CURRENT_DATE`. A mismatch is possible (INFERRED; CON-28).
5. **Persisted zeros.** A missing key is stored as 0.0 and biases about three days of the USDT.D baseline (MKT-15).
6. **Skipped refreshes.** Refresh is lazy, in cycles with candidates, so idle periods leave gaps (MKT-15).
7. **Blocking HTTP client.** CoinGecko is read with blocking urllib (MKT-13).
8. **Candle age and clock.** A 1d bar can be about 24 h old at signal time (EXE-09). Closure depends on the host clock (EXE-05, EXE-06).
9. **One order-book snapshot** is reused across timeframes (EXE-05).

## 10. Collected but unused components and active-state summary

| ID · class | Component | Collected or computed | Used in any decision? | Source · commit |
|---|---|---|---|---|
| [MKT-05 · SOURCE_VERIFIED] | ETH 4h trend | Yes: `macro_history.eth_trend`, snapshot | No (`should_block` ignores it) | `shared/macro_context.py` blob 9099d1d1 |
| [MKT-06 · SOURCE_VERIFIED] | BTC dominance | Yes: `macro_history.btc_d`, snapshot | No | `shared/macro_context.py` blob 9099d1d1 |
| [MKT-08 · SOURCE_VERIFIED] | BTC/ETH relative strength | Not implemented | No | — |
| [IND-02 · SOURCE_VERIFIED] | Order-book score | Yes: `analyzer/orderbook_analyzer.py:19-110`, 20-level snapshot; wall ≥ 5 × the average level within 3%; bid/ask ratio thresholds 1.5 / 1.2; spread > 0.5% → −0.2 | Not part of the analyzer `total_score`. The seeded `order_book` indicator weight is never read. It enters only the legacy decision sum (`final = score + ob_score + btc_bonus + tf_bonus`). On the live path the order book contributes only validity and spread. | ea8ae4f |
| [STR-14 · SOURCE_VERIFIED] | Legacy indicator score `legacy_score_v1` | Yes, on every pass (`technical_analyzer._calculate_scores`, lines 323-402); MACD, EMA cross, volume, OBV and `btc_trend` are computed but fixed at 0 | Not a decision path on the live path, but `total_score` still orders timeframes within a symbol in the selection query (UNI-16, LRN-16); maximum 5.5 when every weight is 1 | ea8ae4f |
| [MKT-10 · SOURCE_VERIFIED] | `macro_state` (`usdtd_*`) | Yes, every cycle | Exploration hash key only, while learned gates are off | ea8ae4f |

[MKT-17 · SOURCE_VERIFIED] Active-state summary:

| Element | Status |
|---|---|
| Macro gate, regime routing, scanner BTC filter | Present in the deployed code |
| BTC.D, ETH and BTC/ETH relative strength | Influence no decision |
| Any context input | No effect on sizing or exits |

The status is qualified by flags and documentation:
- The macro gate is active only if `LIVE_LEARNING_MODE=true`. That is documented as of 2026-09-27; the runtime value is NOT VERIFIED (MKT-04, STR-04).
- `SIGNAL_INTEGRITY_MODE` defaults to off and is not set in Compose. Its effective value is NOT VERIFIED (likely off; STR-33, STR-34).

Context inputs only veto or are only collected (ECO-02). The architecture therefore uses market context as a filter on entry. It does not use context for sizing or exits. Its only portfolio-level use is the USDT.D regime-cap key, which never binds with 2 slots (RSK-05, RSK-04).

## 11. Contradictions

- [CON-27 · CONTRADICTORY] Two BTC-trend definitions share the same labels.
  - **The definitions:** the scanner uses 36 h with ±1/±3% thresholds; the macro gate uses 68 h with ±1/±5% (section 7.2).
  - **The documents:** A45 and the `_is_btc_crashing` docstring describe the BTC trend as "40 h", while the macro comment says "~3 days (18×4h)".
- [CON-28 · CONTRADICTORY] The `macro_context` module docstring promises a "daily snapshot / 3-day average". In practice:
  - each hourly refresh overwrites that day's row;
  - the mean spans D−3 to D, including today;
  - "today" is computed in UTC but compared with the database's `CURRENT_DATE`, so a timezone mismatch is possible (INFERRED).
- [CON-29 · CONTRADICTORY] A comment in `signal_engine/main.py` says `MacroContext` "only calls public klines". It also calls CoinGecko and the database.
- [CON-30 · CONTRADICTORY] The Telegram header advertises whitelist approval, but that code path is dead (UNI-08).

Related contradictions recorded in other package documents:

| ID | Contradiction |
|---|---|
| CON-12 | Legacy filters, including the 4h ban, are described as live. |
| CON-15 | `TIMEFRAMES_LL` is documented but unread. |
| CON-16 | `RISK_CANARY_MAX_OPEN_TRADES` defaults to 1 in code but is documented as 2. |
| CON-24 | The legacy `btc_bonus` uses the symbol's own regime, not BTC's. |

## 12. Not verified in this area and open question

The following were **NOT VERIFIED**:

| IDs | What is not verified | Reason |
|---|---|---|
| UNI-06 | Current `symbol_blacklist` contents (documented as emptied on 2026-05-17, UNI-07) | Database read not authorized |
| UNI-17 | How often the alphabetical `LIMIT 200` truncation binds | No `analysis_results` rows read |
| STR-04, MKT-04 | The runtime value of `LIVE_LEARNING_MODE`, and therefore whether the macro gate and the rule-based setups are the active decision path | `.env` not read |
| STR-34 | The effective `SIGNAL_INTEGRITY_MODE` | `.env` not read |
| EXE-03, RSK-03 | The effective `RISK_CANARY_MAX_OPEN_TRADES` and capacity | `.env` not read |
| CAL-03 | The effective values of `MIN_VOLUME_USDT`, `SCAN_INTERVAL_SECONDS`, `MAX_SPREAD_PCT`, `TIMEFRAMES`, `USDTD_SPIKE_PP`, `MACRO_CACHE_HOURS` and `MACRO_MAX_STALE_HOURS` | `.env` not read |
| RT-17, RT-39 | That the running scanner, analyzer and signal_engine images contain the code read | Image filesystems not read |
| RT-46 | Pause and risk state | Requires a database read |
| — | No `macro_history`, `scan_candidates` or `signals` rows were read, so no context value actually used at runtime is known (PD-02) | Database read not authorized |

[OQ-07] Objective: should the bot cover "all eligible assets", or a restricted set? Is the 2 × $50 capacity intended?

Related owner questions in the other documents:

| ID | Question |
|---|---|
| OQ-01 | Narrow database reads, including the pause state |
| OQ-02 | A redacted allow-list of `.env` flags, including `LIVE_LEARNING_MODE`, `TIMEFRAMES` and `RISK_CANARY_MAX_OPEN_TRADES` |
| OQ-09 | Whether the frozen weights should keep affecting candidate ordering and truncation |

This document records findings only. It makes no change and gives no recommendation, and it is not a profitability certification.
