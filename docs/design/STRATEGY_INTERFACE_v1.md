# Strategy Interface v1: closure, identity and decision keys (WP-A01)

> **Status: EVIDENCE-BACKED PROPOSAL FOR OWNER REVIEW.** DG-69 approves WP-A01 for completion and review ([DECISIONS_AND_GATES.md](remediation-design-pack-20261101/DECISIONS_AND_GATES.md), DG-L03). This file fixes the WP2 interface baseline that the code tasks implement. It activates nothing, creates no boundary entry and chooses no parameter. The closure below comes from source-level call paths (section 3), not from file names. A correct identity is a precondition for attributing evidence, and it is never evidence of an edge (`TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md:L46 @ 46578aa`).

## Document control

| Field | Value |
|---|---|
| Task | WP-A01 ([IMPLEMENTATION_WORKPLAN.md](remediation-design-pack-20261101/IMPLEMENTATION_WORKPLAN.md) §4.1); sources R5.d, SE-37, SE-60, SE-72, R1.d, R1.e, WP-IR-01 … WP-IR-09 |
| Branch / code read | `feature/wp2-foundation-20261101` at `a03efdd`. For every service directory the code at `a03efdd` equals `main` `46578aa`: `git diff --stat 46578aa a03efdd` lists only new WP2 modules |
| Deployed commits | analyzer and signal_engine `ea8ae4f`; telegram and trade_tracker `bb7825f`, which equals `main` in their directories (BL-06 in [BASELINE_AND_EVIDENCE.md](remediation-design-pack-20261101/BASELINE_AND_EVIDENCE.md)). Differences are listed in §3.10 |
| Runtime configuration | `LIVE_LEARNING_MODE=true`, `SIGNAL_INTEGRITY_MODE` off, `LEARNING_GATES_ENABLED=false`, `T1_CAP_POLICY` unset, `PAPER_ECONOMIC_HALT_MODE=observe` (telegram and trade_tracker), `EVIDENCE_V2_ENABLED=true` except in the scanner. RUNTIME_VERIFIED for 2026-10-31 only, by citation: OF-02 in [OPPORTUNITY_FUNNEL.md](remediation-design-pack-20261101/OPPORTUNITY_FUNNEL.md) (`RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md:L93-112 @ 5d977f2`, VER-01 … VER-20); observe mode from [VERSION_BOUNDARY.md](../../deploy/VERSION_BOUNDARY.md) (VB-2026-10-27-01) |
| Code | Closure data: `DRAFT_MANIFESTS` in [shared/strategy_identity.py](../../shared/strategy_identity.py). Decision-key schema: `DRAFT_CURRENT_FAMILY_SCHEMA` in [shared/strategy_config_snapshot.py](../../shared/strategy_config_snapshot.py). Report: `drift_check.py strategy` in [ops/provenance/drift_check.py](../../ops/provenance/drift_check.py) |
| Template | [deploy/VERSION_BOUNDARY_TEMPLATE.md](../../deploy/VERSION_BOUNDARY_TEMPLATE.md) (SE-36, SE-72) |
| Related | [SETUP_KEY_PROPOSAL_SE84.md](SETUP_KEY_PROPOSAL_SE84.md) (DG-35 HOLD); [SIGNAL_INTEGRITY_MODE_DECOMPOSITION.md](SIGNAL_INTEGRITY_MODE_DECOMPOSITION.md) (WP-C01) |
| IDs | SI-01 onwards (findings of this file) |

### Anti-drift statement (charter §7)

1. **Goal alignment.** Traceability (charter §3 E): every decision must be attributable to the rules that made it, so that net economics can later be measured per version and never pooled across versions. Nothing here forces a trade, sets a quota or narrows the universe.
2. **Branch, SHA, runtime.** Source claims are SOURCE_VERIFIED at `a03efdd` (= `46578aa` for the services) and, where stated, at the deployed commits. Runtime values are RUNTIME_VERIFIED by citation for 2026-10-31. That the running images contain this source is DOCUMENTED_ONLY (RT-16, RT-17).
3. **Scope.** WP0–WP5: WP2 (DG-70, development-only). R5.d, R5.e (template), R1.d, R1.e, R2.c, R3.d (by reference). Excluded: the `setup_key` composition (DG-35 HOLD), any edit of the nine hash-pinned files (DG-71 HOLD), activation, deployment, protected data.
4. **Evidence classes** follow charter §7.4.
5. **Permission class.** Documentation, plus the closure data and a report-only drift_check section, both development-only.
6. **Deliverables.** This file, the boundary template, the closure data, the drift_check section and their tests (§12).
7. **DEVIATION ALERT.** None.

## 1. What this file fixes

| Point | Section |
|---|---|
| Decision-critical dependency inventory, by call path | §3 |
| Strategy-rule closure per family | §4 |
| `StrategyVersion` identity contract, `source_hash`, `inactive_hash`, `contract_hash` | §5 |
| `config_hash` semantics and keys, and how it differs from the evidence-v2 `config_hash` | §6 |
| Decision keys: candle key, `setup_key`, `decision_id`, `tie_break_key` | §7 |
| `total_score` | §8 |
| Rejection taxonomy v1 | §9 |
| SE-36 boundary-template fields; activation records for identity changes (SI-03) | §10 |
| Integration points and open owner decisions | §11 |

## 2. Classification rule

Every candidate dependency gets exactly one class. The class depends on the runtime-verified configuration in the document-control table.

| Class | Meaning | Effect on the identity |
|---|---|---|
| **ACTIVE** | On a call path that can change a `Candidate`, a rejection or a position action under the runtime-verified configuration | Feeds `source_hash` |
| **DORMANT** | Reachable only behind a flag that is off, or in a mode that is not used | Hashed separately into `inactive_hash`; never in the identity |
| **POTENTIAL** | On no call path of any service | Hashed separately into `inactive_hash`; never in the identity |
| **EXCLUDED (infrastructure)** | On a call path, but carries no decision rule: transport, persistence, logging, health, instrumentation, credentials | Not in the closure. Its content is covered by the runtime manifest and `code_sha` (SE-21, SE-24) |

Two refinements:
- **Regions.** A region (a function, class, assignment or string constant, resolved with `ast`) carries its own class. A DORMANT region inside an ACTIVE file does not change the file's class: the whole file is still hashed. Every declared region must resolve, whatever its class, or the hash refuses to compute (fail closed).
- **Scope.** A file's scope is `file` (all normalized bytes count) or `regions` (only its ACTIVE regions count). `regions` is used only where the decision rules are a small, enumerable part of a larger file (§4.2).

## 3. Decision-critical dependency inventory

Each entry point is traced through the imports and calls it actually reaches. Line numbers are at `a03efdd`. Stage IDs S0–S26 are those of OPPORTUNITY_FUNNEL.md §2, which gives the same paths at the deployed commits.

### 3.1 E1 Scanner: universe, pause gate, retention

- `scanner/main.py:L33-41` builds `BinanceScanner`, calls `scanner.scan()`, then `maintain_pipeline()` every cycle. **ACTIVE** (SOURCE_VERIFIED).
- `scanner/scanner_logic.py:L22-70` (scan), `L88-114` (initial filter), `L116-148` (BTC trend, via `shared.ohlcv.closed_klines` at L124), `L162-164` (pause gate via `shared.trading_state.get_pause_state`). **ACTIVE**; hash-pinned (WP-N02).
- `shared/trading_state.py:L21` `get_pause_state`: also read by the delivery gate (`telegram/main.py:L366`) and by admission (`trade_tracker/main.py:L942`). **ACTIVE**.
- `shared/maintenance.py:L5-13` `maintain_pipeline`: marks `analysis_results` rows expired and deletes `scan_candidates` older than 1 h (OF-04, OF-06). **ACTIVE**.
- `shared/ohlcv.py:L26` `closed_klines`, `L36` `prepare_ohlcv` (validation from L54; candle arithmetic through `shared.candle.candle_seconds`, L15 and L80). **ACTIVE**.

### 3.2 E2 Analyzer: history, indicators, regime, setup, levels

- `analyzer/main.py:L47-54` intake query (`LIMIT 50`, newest scan first); `L144-180` `analyze_symbol_all_timeframes`: per-timeframe analysis, one order-book fetch reused across timeframes (L158), upsert that resets `signal_generated` (L172; the same-bar re-fire mechanism, OF-16). **ACTIVE**.
- `analyzer/technical_analyzer.py:L40-122` `analyze`: candles through `prepare_ohlcv` (L135), indicators, `classify_regime` (L62), `_get_indicator_weights` (L64, database table `indicator_weights`), `_calculate_scores` (L65), `detect_trade_setup` only when `LIVE_LEARNING_MODE` (L69-74), `_calculate_levels` (L75). **ACTIVE**.
- Inside `_calculate_levels`: `shared.signal_stop.plan_signal_stop` (L436) and the W3 cap through `t1_cap_policy`, `resistance_for`, `capped_t1` (L466-469). **ACTIVE**.
- `analyzer/simple_entry.py` `detect_trade_setup`: entry predicates of both families. **ACTIVE** (`LIVE_LEARNING_MODE=true`); hash-pinned.
- `analyzer/orderbook_analyzer.py:L15-64` `OrderBookAnalyzer.analyze`: produces `valid` and `spread_pct`, which the spread gate reads (S16). **ACTIVE**.
- `shared/regime.py`, `shared/signal_stop.py`: **ACTIVE**; hash-pinned.
- `shared/t1_cap.py`: `legacy_window_resistance`, `resistance_for`, `capped_t1`, `t1_cap_policy` are **ACTIVE**. `independent_swing_resistance` is a **DORMANT** region (`T1_CAP_POLICY` unset, so `legacy_window_v1`; VER-05).

### 3.3 E3 Selection and the LIMIT query

- `signal_engine/main.py:L26` `SELECTION_LIMIT = 200`; `L146-155` the candidate query (`ORDER BY symbol, total_score DESC LIMIT 200`, the R1 cut, OF-03); `L173-176` selector dispatch; `L181-186` decision reasons; `L220` `save_signal`; `L240-241` marks every row of the selected symbol `signal_generated=true`. **ACTIVE**.

### 3.4 E4 Signal gates, ranking and emission

- `signal_engine/signal_logic.py:L720-862` `find_best_signal_live`, selected because `LIVE_LEARNING_MODE=true` (`signal_engine/main.py:L173-174`). **ACTIVE**; hash-pinned. In order: the macro veto (L723), the integrity-mode switch (L731), the spread, stop-validity, open-trade and cooldown gates, ranking by `min(eligible, key=_fixed_candidate_key)` (L849; key at L288-294).
- `signal_engine/signal_logic.py:L456` `find_best_signal`, the legacy score selector with `optimizer_settings` thresholds (`_get_live_thresholds`, L304-308): **DORMANT** region (`LIVE_LEARNING_MODE=true`).
- `signal_engine/signal_logic.py:L742` learned-gate read and `L823` `shared.learning_governance.exploration_selected`: **DORMANT** (`LEARNING_GATES_ENABLED=false`, VER-03).
- `signal_engine/signal_logic.py:L731-737` enforce branch, `_integrity_state` (L374-416, the only caller of `shared.dependency_safety.guarded_read`/`cycle_gate`, L405-409), `integrity_check` and `identity_from_candidate`: **DORMANT** (integrity off, VER-02). `shared/signal_identity.py` stays **ACTIVE** as a file because `integrity_mode()` selects the path on every cycle and refuses an unknown value at start-up (`signal_engine/main.py:L101`, `trade_tracker/main.py:L77`); its `SetupIdentity`, `freshness_at` and `integrity_check` regions are DORMANT.
- `shared/signal_readiness.py`: `assert_signal_complete` (`signal_logic.py:L923`), `ready_payload` and the `signal.ready` enqueue (L1023). **ACTIVE**.

### 3.5 Macro context: verdict

**Verdict: ACTIVE for both `momentum_breakout` and `reversion_rsi_bb`.** SOURCE_VERIFIED from the call path alone:
1. `signal_engine/main.py:L108` creates `MacroContext`; `L173-174` calls `find_best_signal_live(results, macro_ctx)` whenever `LIVE_LEARNING_MODE` is true, which is the runtime value (VER-01).
2. `signal_engine/signal_logic.py:L723` calls `await macro.should_block_now()` before the per-row loop, with no flag around it. A block returns `None` for the whole cycle (L723-728), whatever the `trade_type`, so it can suppress a candidate of either family.
3. `shared/macro_context.py:L104-110` `should_block_now` refreshes (L96-98, L65-94) and blocks when the data are stale (`MACRO_MAX_STALE_HOURS`) or when `should_block` (L24-25) sees BTC `strong_bearish` or USDT.D `rising_fast`.
4. The family split is made in the analyzer (`trade_type`), and no later stage branches on it before the veto. Both families therefore share this dependency. Its presence in the import list was not used as evidence.

Exceptions: `macro_state_key` (L123-125) feeds only the learned-gate cell key, so that region is DORMANT. The veto exists only on the live path; under `LIVE_LEARNING_MODE=false` the module would leave the decision path, and that flag is a `config_hash` key (§6). At `ea8ae4f` the call is at `signal_engine/signal_logic.py:L722`, with an identical `shared/macro_context.py` blob. Its economic effect is UNKNOWN; the point-in-time limits are SE-06 and OF-12.

### 3.6 E5 Delivery (telegram)

- `telegram/main.py:L249-317` `handle_candidate_event`: readiness via `shared.signal_readiness.is_deliverable_for_event` (L264), then the pause and capacity gate `can_deliver_candidate` (L268, defined L364-382: pause, then `min(MAX_OPEN_TRADES, RISK_CANARY_MAX_OPEN_TRADES)`, L379). A refused candidate is acknowledged and lost (OF-10). `_candidate_failure` (L319) sets retry and dead-letter semantics; `send_signal_direct` (L354) and `mark_delivered` (L576) hand the signal to admission. **ACTIVE**, scope `regions`: the rest of the file is notification formatting and commands.
- `telegram/whitelist.py:L97-111` `ApprovalManager.process_signal` returns `'sent_direct'` unconditionally (L111). **ACTIVE**: removing that return would re-enable manual approval and change admissions. The code after it (L113-122) is unreachable.

### 3.7 E6 Admission, entry and capacity (trade_tracker)

- `trade_tracker/main.py:L705-905` `register_new_signals`: capacity pre-checks (L708-712, L752-756); the admission query with `READY_SQL_PREDICATE` and the same-candle guard `shared.candle.candle_interval_case_sql` (L718-727); entry through `shared.entry_execution.decide_long_entry` (L780) and `resolve_entry_fill` (L790, model `PAPER_ENTRY_FILL_MODEL`, validated at L78-79); `assess_new_trade_risk` (L819); bracket rebase `shared.execution.rebase_long_bracket` (L836); the loss-streak check under the admission lock (L853-855). **ACTIVE**.
- `trade_tracker/main.py:L761` `integrity_admission_refusal` (enforce only, using `shared.signal_identity.freshness_at`): **DORMANT** region.
- Capacity: `trade_tracker/main.py:L922-1006` `assess_new_trade_risk` builds the net-of-cost snapshot and calls `shared.economic_halt_policy.evaluate_with_policy` (L1006), which calls `shared.risk_management.evaluate_new_trade` (`shared/economic_halt_policy.py:L188`; definition `shared/risk_management.py:L63`). Observe mode re-derives an economic stop as allowed (`shared/economic_halt_policy.py:L193-201`). **ACTIVE**: `risk_management.py` (hash-pinned), `economic_halt_policy.py` and `shared/risk_epoch.py` (`effective_risk_start` L93, `loss_streak_halt_active` L122).
- `trade_tracker/main.py:L106-107` `close_blacklisted_trades` and `enforce_max_open_trades` run every loop and can close trades. **ACTIVE** regions.

### 3.8 E7 Exits, holding and costs

- `trade_tracker/main.py:L1130-1170` `track_open_trades` (REST backup prices, candle invalidation through `shared.signal_stop.candle_invalidated`, L1155); `L1189-1305` `evaluate_trade` (barrier config with `roundtrip_cost` from `FEE_ROUNDTRIP_PCT`, L1210; `shared.triple_barrier.step_barrier`, L1217; `shared.partial_exits.fills_between`, L1223); `L1307-1402` `close_trade_barrier` (`aggregate_close`, L1328; `shared.fees.economic_close`, L1350). **ACTIVE**.
- `trade_tracker/binance_price_stream.py:L122-148` `_handle` filters ticks (order by aggregate id, finite positive prices) before `handle_stream_price` evaluates open trades (`trade_tracker/main.py:L454-459`); started when `PRICE_STREAM_ENABLED` (L90-99). **ACTIVE**. `usable_price` (L1419-1428) gates REST prices. **ACTIVE** region.
- `shared/fees.py` `economic_close` and `fee_usdt` (cost booking, legacy cost model). **ACTIVE**.

### 3.9 Summary of the classification

| Class | Files (33 declared in `DRAFT_MANIFESTS`) |
|---|---|
| ACTIVE, hash-pinned v1 (8) | `analyzer/simple_entry.py`, `shared/regime.py`, `shared/signal_stop.py`, `shared/triple_barrier.py`, `shared/partial_exits.py`, `shared/risk_management.py`, `scanner/scanner_logic.py`, `signal_engine/signal_logic.py` |
| ACTIVE, named in SE-04 or WP-A01 (7) | `analyzer/technical_analyzer.py`, `shared/t1_cap.py`, `shared/signal_identity.py`, `signal_engine/main.py`, `trade_tracker/main.py`, `shared/fees.py`, `shared/macro_context.py` (verdict §3.5) |
| ACTIVE, added by this trace (15) | `scanner/main.py`, `shared/trading_state.py`, `shared/maintenance.py`, `shared/ohlcv.py`, `shared/candle.py`, `analyzer/main.py`, `analyzer/orderbook_analyzer.py`, `shared/signal_readiness.py`, `telegram/main.py` (scope `regions`), `telegram/whitelist.py`, `trade_tracker/binance_price_stream.py`, `shared/entry_execution.py`, `shared/execution.py`, `shared/economic_halt_policy.py`, `shared/risk_epoch.py` |
| DORMANT (3) | `shared/learning_governance.py` (gates off), `shared/dependency_safety.py` (integrity off), `research/continuous_learner.py` (the learner, which is stopped, is the only writer of `learned_gates`) |
| POTENTIAL (1) | `shared/strategy_math.py`: hash-pinned by the legacy contract, but imported only by the experimental `shared/trade_geometry.py:L27`, at `a03efdd` and at `ea8ae4f` (SI-01) |

Regions: 70 declared, all of which resolve on this tree (§12). Eight are DORMANT: `find_best_signal`, `independent_swing_resistance`, `macro_state_key`, `IDENTITY_VERSION`, `SetupIdentity`, `freshness_at`, `integrity_check` and `integrity_admission_refusal`. The other 62 are ACTIVE.

**SI-01 (SOURCE_VERIFIED).** The legacy research contract hashes `shared/strategy_math.py` (`research/foundation/contract.py:L68-71 @ 46578aa`), but no service imports it; the analyzer computes levels in `technical_analyzer._calculate_levels`. The v1 hash therefore covers one file that does not run and misses 22 that do. The v1 hash and `research_freeze.json` stay unchanged (DG-71 HOLD; SE-39).

**SI-02 (SOURCE_VERIFIED).** The delivery gate, the approval routing, the analyzer intake and upsert, the order-book spread input, the price-stream tick filter and the entry fill model all decide which candidates become trades or when exits fire. None is in the v1 hash, and none was in the SE-04 list.

### 3.10 Differences at the deployed commits

- **analyzer and signal_engine at `ea8ae4f`.** `shared/t1_cap.py` does not exist; the W3 rule is hard-coded in `analyzer/technical_analyzer.py:L409-411, L464-465 @ ea8ae4f` (20-bar window high, 0.99 fill). The selector, the macro call (`signal_engine/signal_logic.py:L722 @ ea8ae4f`) and the funnel stages are unchanged (OF-01). `shared/strategy_math.py` also differs between `ea8ae4f` and `main`, so the v1 hash of the deployed source differs from that of `main` (INFERRED from `git diff --stat ea8ae4f 46578aa`). An identity computed from `main` therefore does not describe the deployed analyzer and signal_engine (SOURCE_VERIFIED).
- **telegram and trade_tracker at `bb7825f`.** Their directories equal `main`; `shared/economic_halt_policy.py` exists there and not at `ea8ae4f` (SOURCE_VERIFIED, `git cat-file`).
- **Consequence.** A deployed-identity record must hash the closure at each service's deployed commit, per service. That is a read of committed source, and image parity remains R5.a (owner-gated).

### 3.11 Excluded infrastructure

| Module | On the path | Why it is excluded |
|---|---|---|
| `shared/config.py` | every service | Values, not rules: effective values belong to `config_hash` (§6), including code constants such as `CANDLES_TO_FETCH` |
| `shared/database.py`, `shared/logger.py`, `shared/alerts.py`, `shared/health.py`, `shared/schema.py`, `shared/retry_utils.py` | every service | Persistence, logging, alerting, health and retry plumbing |
| `shared/outbox.py`, `shared/outbox_watch.py`, `shared/delivery_policy.py` | signal, delivery, admission | Event transport, notification backoff and dead-letter watch. The decision-relevant acknowledgement semantics are in the `telegram/main.py` regions |
| `shared/evidence_v2.py`, `research/null_a/` | analyzer, signal_engine, tracker | Instrumentation; no decision reads its output (`analyzer/technical_analyzer.py:L44-45, L116-117`; the `_v2_*` helpers only record) |
| `shared/telegram_messages.py` | telegram | Message text |
| Exchange and HTTP clients | all | Input transport. The rules that accept or reject inputs (`prepare_ohlcv`, `usable_price`, the tick filter) are in the closure |

## 4. Strategy-rule closure per family

### 4.1 One closure, two identities

`momentum_breakout 1.0.0` and `reversion_rsi_bb 1.0.0` (SE-39) share one closure. The analyzer sets `trade_type` (momentum when the regime is bullish, reversion when it is sideways; S9). Every later stage, from the macro veto to the exit barrier, is common code. The split is an identity mapping, as SE-39 states. Each family's own predicates sit in `analyzer/simple_entry.py` and in the `trade_type`-dependent branches of `_calculate_levels`, which are in both closures. A future family with its own code gets its own closure.

### 4.2 Hash rules

- **`source_hash`** = sha256 over the canonical JSON of `{"scheme": "tsb-strategy-source/1", "files": [[path, digest], …]}` for the ACTIVE files, sorted by path. A `file`-scoped digest is sha256 of the normalized bytes (CR LF and lone CR become LF; Python reads source with universal newlines, so nothing else changes). A `regions`-scoped digest is sha256 over the canonical `[region_id, selector, sha256]` list of its ACTIVE regions.
- **`inactive_hash`** = the same construction over `[path, class, digest]` of the DORMANT and POTENTIAL files. Drift reports show it, but it never enters the identity. Activating a dormant path flips a `config_hash` key or changes the closure spec, so the activation is a version boundary in its own right (SE-38).
- **`closure_spec_hash`** = sha256 over the declared paths, region selectors, and any non-default class or scope. Editing the declaration is visible even when no source byte moves.
- **Fail closed.** A missing or undeclared file, a region that resolves to zero or several definitions, or a parse error refuses the hash.
- **Why `telegram/main.py` uses `regions` scope.** Most of its 1,265 lines format notifications and run commands. Hashing it whole would make each message edit an undeclared strategy change (SE-38 stop). Its five decision regions are enumerable (§3.6). `trade_tracker/main.py`, `signal_engine/main.py` and `analyzer/main.py` stay `file`-scoped, because most of each is decision code.
- **Backward compatibility.** For an all-ACTIVE, `file`-scoped manifest, the hashes equal those of the iteration-1 module (`9668485`). A test pins this (§12).

## 5. StrategyVersion identity contract

- **Identity = five fields** (WP-IR-09): `strategy_id`, `version` (`MAJOR.MINOR.PATCH`, SE-38), `source_hash` (§4.2), `config_hash` (§6), `contract_hash`.
- **`lineage`** is metadata: a tuple of ancestor identities, never a claim of inherited evidence (SE-39). It is excluded from equality, from the identity hash, from `setup_key` and from any record identifier. Changing it alone changes nothing (WP-IT-09).
- **`contract_hash`** = sha256 over the canonical `StrategyContract` descriptor (SE-37). Required keys: `input_spec`, `output_schema_versions`, `regime_providers`, `cost_model_id`, `fill_model_id`, `holding_policy`, `failure_criteria`. Values are the owner's declaration; this file chooses none.
- **`identity_hash`** = sha256 over the canonical five fields. `identifier` = `strategy_id/version/` plus the first 16 hex characters of `identity_hash`.
- **Undeclared change.** A hash that moves while `version` stays the same is a stop condition (SE-38; charter §6). `shared/strategy_version_boundary.py` classifies it `UNDECLARED_CHANGE`; `drift_check.py strategy` reports it in S2.
- **Canonical JSON.** Sorted keys, compact separators, ASCII, and no NaN or infinity. This is the research contract's form (`research/foundation/contract.py:L106-111 @ 46578aa`), applied strictly.

## 6. config_hash

### 6.1 Semantics, and how it differs from the evidence-v2 config_hash

| | Strategy `config_hash` (this interface) | Evidence-v2 `config_hash` (envelope) |
|---|---|---|
| Code | `shared/strategy_config_snapshot.py` | `shared/evidence_v2.py:L151-168` (`strategy_config_snapshot`, `compute_config_hash`) |
| Keys | A declared schema of decision keys; every key is required, an undeclared key is refused | Every upper-case attribute of the process config object, minus secret-looking names, process-local fields and `EVIDENCE*` |
| Values | The effective values the caller supplies, including database-held inputs | The config object's attributes only; database-held thresholds are not seen |
| Serialization | Strict ASCII canonical JSON; the schema hash is part of the hash | Canonical JSON with `ensure_ascii=False` and a string fallback for unknown types |
| Meaning | Changes when, and only when, a decision input of the strategy changes | Changes on any configuration change of that process |

They are reported side by side and never substituted for each other. The evidence hash catches configuration drift; the strategy hash attributes decisions.

### 6.2 Key rule and keys

A key enters `config_hash` when an ACTIVE path reads it under the runtime configuration, or when it switches between an ACTIVE and a DORMANT path. Keys read only on DORMANT paths join the schema of the version that activates that path.

| Group | Keys | Class |
|---|---|---|
| Path switches | `LIVE_LEARNING_MODE` (the **selection policy** switch: `fixed_execution_quality_v1` versus `legacy_score_v1`, `analyzer/technical_analyzer.py:L97-98`), `SIGNAL_INTEGRITY_MODE`, `T1_CAP_POLICY`, `LEARNING_GATES_ENABLED`, `PRICE_STREAM_ENABLED`, `PAPER_ENTRY_FILL_MODEL` | ACTIVE |
| Universe and candles | `TIMEFRAMES`, `MIN_VOLUME_USDT`, `MIN_PRICE_CHANGE_PERCENT` (code constant), `CANDLES_TO_FETCH` (code constant) | ACTIVE |
| Indicators (code constants) | `RSI_PERIOD`, `MACD_FAST`, `MACD_SLOW`, `MACD_SIGNAL`, `EMA_SHORT`, `EMA_MEDIUM`, `EMA_LONG`, `BB_PERIOD`, `BB_STD`, `ATR_PERIOD`, `STOCH_RSI_WINDOW`, `STOCH_K`, `STOCH_D` | ACTIVE |
| Entry predicates | `MOM_BREAKOUT_N`, `MOM_VOL_MULT`, `REV_RSI`, `REV_BB_MAX_POSITION` | ACTIVE |
| Gates | `MAX_SPREAD_PCT`, `USDTD_SPIKE_PP`, `MACRO_CACHE_HOURS`, `MACRO_MAX_STALE_HOURS` | ACTIVE |
| Legacy cost terms (cost model `legacy_tracker_v1`, WP-IR-07) | `FEE_ROUNDTRIP_PCT` (exit barrier, `trade_tracker/main.py:L1210`; booking), `STOP_SLIPPAGE` | ACTIVE |
| Database-held, **legacy path** | `indicator_weights` → `DB_INDICATOR_WEIGHTS`: they only order the candidate query through `total_score` (§8; OF-20). `symbol_blacklist` → `DB_SYMBOL_BLACKLIST` (scanner, admission, blacklist closes) | ACTIVE |
| Database-held, **legacy path, DORMANT** | `optimizer_settings` (legacy selector thresholds), `learned_gates` | not hashed until activated |
| DORMANT-path keys | `APP_VERSION` (enters only the enforce-mode A44 key; otherwise a label), `MIN_SCORE_TO_SIGNAL`, `MIN_TIMEFRAME_CONFIRMATIONS`, `MAX_SIGNALS_PER_DAY`, `GLOBAL_LOSS_COOLDOWN_HOURS`, `LEARNING_EXPLORATION_RATE`, `MIN_CELL_N` | not hashed until activated |
| Portfolio and risk policy | `MAX_OPEN_TRADES`, `RISK_CANARY_MAX_OPEN_TRADES`, `TRADE_AMOUNT_USDT`, `RISK_CAPITAL_USDT`, the `MAX_*_PERCENT` limits, `STOP_ON_CONSECUTIVE_LOSSES`, `PAPER_ECONOMIC_HALT_MODE`, `RISK_POLICY_VERSION`, `LEARNING_CLEAN_START` | the separate risk-policy identity (VB-2026-10-27-01), not the strategy hash |
| Excluded | cadence (`SCAN_INTERVAL_SECONDS`, price-stream refresh and backup intervals, risk price retries), evidence settings, notification settings, approval settings (approval is disabled, §3.6), credentials | — |

The schema in code lists names only (`DRAFT_CURRENT_FAMILY_SCHEMA`, `current-families-decision-keys/proposal-1`). Reading the effective database values is a protected-data read that needs owner permission (`CH:L21`); nothing here performs it.

## 7. Decision keys

| Key | Definition | Where | Status |
|---|---|---|---|
| Candle key | `"ck_"` + first 40 hex of sha256(canonical `[CANDLE_KEY_VERSION, symbol, timeframe, bar_close_ms]`) | `shared/signal_integrity_v2.py` `candle_key` | Implemented (WP-C02 groundwork); the evidence-v2 `candle_id` (`shared/evidence_v2.py:L101`) is a separate, older key |
| `setup_key` | Not decided here. Today's A44 key (`shared/signal_identity.py` `SetupIdentity.key`; enforce only) includes `APP_VERSION`; the candidate compositions SK-A, SK-B and SK-C are in [SETUP_KEY_PROPOSAL_SE84.md](SETUP_KEY_PROPOSAL_SE84.md) | — | **DG-35 / SE-84 HOLD** |
| `decision_id` | sha256 over canonical (`decision_type`, the five identity fields, input hashes, input facts, `bar_close_time_ms`, cost-model, fill-model and selection-version ids, parent decision ids). Wall-clock times and runtime identifiers are excluded, so a replay gives the same id (SE-51, SE-55) | `shared/decision_metadata.py` | Implemented, not emitted |
| `tie_break_key` | sha256(canonical `[selection_version, setup_key]`); never a symbol name or timeframe string (R1.d; OPPORTUNITY_FUNNEL.md F6) | specification | Waits for the `setup_key` decision |

## 8. total_score

`total_score` is a fixed, data-mined input: weighted indicator points from the frozen `indicator_weights` table (`analyzer/technical_analyzer.py:L64-65`; 44 values, RUNTIME_VERIFIED by citation, VER-22). It has **no decision role in any new version** (R1.e; OQ-09). In `1.0.0` it is still read, by one place only: the `ORDER BY symbol, total_score DESC` of the candidate query (`signal_engine/main.py:L146-155`), which decides which rows of the boundary symbol survive the `LIMIT 200` cut (OF-20). No gate reads it on the live path. It is recorded as an input, and its weights enter `config_hash` as `DB_INDICATOR_WEIGHTS`, marked legacy path.

## 9. Rejection taxonomy v1

Taxonomy v1 is `of-taxonomy-v1` in [shared/funnel_records.py](../../shared/funnel_records.py): stages `F0`–`F7`, the closed sub-stage map (`strategy.input`, `strategy.regime`, `strategy.entry` and `shared.identity` at F4; `strategy.geometry` at F5; `shared.sizing`, `shared.order_intent` and `shared.admission` at F7), and `REASON_CODES`, which is OPPORTUNITY_FUNNEL.md §8.2 plus the WP-IR-01 additions (`F4.regime_not_accepted`, `F4.bar_before_version_activation`, `F5.t1_not_cost_feasible`, `F6.legacy_alphabetical_cut` and the F7 ledger and limit codes). A strategy reports its own drops under the `strategy.*` sub-stages. A rank loss is never a capacity drop (WP-IR-04).

## 10. Version-boundary template (SE-36) and activation records

[deploy/VERSION_BOUNDARY_TEMPLATE.md](../../deploy/VERSION_BOUNDARY_TEMPLATE.md) holds the strategy-boundary fields: `boundary_id`, `entry_kind`, `strategy_id`, version before and after, the three hashes before and after, `closure_spec_hash`, `fill_model_id`, `cost_model_id`, the activation minute, the admission-authority service, image identifiers, the no-re-fire rule and the stratification rule. `shared/strategy_version_boundary.py` drafts these fields from two identity manifests and leaves the activation fields PENDING. No entry is created; [VERSION_BOUNDARY.md](../../deploy/VERSION_BOUNDARY.md) is not edited.

**Decision SI-03: an activation record is required for any change of the identity tuple, a label-only change included.** Finding SK-09 of [SETUP_KEY_PROPOSAL_SE84.md](SETUP_KEY_PROPOSAL_SE84.md) shows that under composition SK-A the identity is part of `setup_key` (as in `setup_key_v2`, `shared/signal_integrity_v2.py`), so a version bump with identical hashes re-keys every setup; under SK-B it turns in-flight bars into conflicts. Without an activation minute, a bar already evaluated under the old key could be evaluated again under the new one, which is the re-fire SE-36 forbids. The rule is therefore:
- `activation_record_required` is true whenever any of the five identity fields changes: `DECLARED_CHANGE`, `UNDECLARED_CHANGE` and `LABEL_ONLY`. The draft entry then carries `activation_utc_minute` (PENDING until an owner-approved activation) and the no-re-fire rule. A label-only change gets `entry_kind = identity_rekey`; a rule change gets `strategy_boundary`.
- `boundary_required` keeps its SE-38 meaning, a strategy-version boundary for outcome stratification. It stays `NO` for a label-only change, because no rule changed.
- A `lineage`-only change moves nothing (WP-IR-09), so it needs no record.

Justification: the rule is safe under every SE-84 composition while DG-35 is on HOLD. Under SK-A the key re-keys, and under SK-B emission changes for in-flight bars. Under a composition that keeps the version out of the key, the record identifier and `identity_hash` still change on every record, so attribution needs the minute anyway. The cost is one boundary record per label change. The enforce-mode behaviours that consume the key are decomposed in [SIGNAL_INTEGRITY_MODE_DECOMPOSITION.md](SIGNAL_INTEGRITY_MODE_DECOMPOSITION.md) (WP-C01).

## 11. Integration points and open decisions

| Item | Where | Default behaviour | Proof | Gate |
|---|---|---|---|---|
| Strategy-identity report | `ops/provenance/drift_check.py` modes `strategy` and `check --strategy-identity` | Report-only; without the flag `check`, `validate` and `observe` do not import `shared/`, and their output, JSON and exit code are unchanged | `tests/test_drift_check_strategy_identity.py`; `tests/test_drift_check.py` green | Done (development) |
| Identity on records | the signal path after `save_signal` (`signal_engine/main.py:L220`), the analyzer upsert (`analyzer/main.py:L167-175`) and the admission decision (`trade_tracker/main.py:L819-821`), calling the existing `shared.evidence_v2.emit` with a `DecisionMetadata` payload | Off behind a new `EVIDENCE_V2_*` flag. That prefix is excluded from the evidence `config_hash` (`shared/evidence_v2.py:L159-162`), so the default leaves record bytes unchanged | a parity test that compares evidence records with the flag off against today's records | Service-integration agents; activation WP-G19 |
| Per-candidate records inside `find_best_signal_live` | `signal_engine/signal_logic.py` (hash-pinned) | — | — | **DG-71 HOLD** (WP-OD-01): wrap from `signal_engine/main.py` only |
| Evidence-v2 payload registration (WP-A05) | none needed: `shared/evidence_v2.py` has no payload registry, and `emit` takes any event type | — | — | Proposal only; `shared/evidence_v2.py` is unchanged |
| `setup_key` | [SETUP_KEY_PROPOSAL_SE84.md](SETUP_KEY_PROPOSAL_SE84.md) | — | — | **DG-35 HOLD** |
| Closure acceptance | this file, §3 and §4 | — | — | Owner review (DG-69) |

Owner questions raised here: (1) accept the closure, including the 15 added files and `telegram/main.py` in `regions` scope; (2) confirm that portfolio and risk keys form a separate risk-policy identity rather than part of the strategy `config_hash`; (3) authorize a deployed-commit identity per service (§3.10), which reads committed source only.

## 12. Verification

- `tests/test_wp2_strategy_identity.py`: closure classification and scope, backward-compatible hashes pinned to the iteration-1 values, inactive hashing, regions scope, cross-schema comparison, and resolution of all 70 regions on this tree (it reads only the declared source files).
- `tests/test_drift_check_strategy_identity.py`: the existing modes load no `shared/` module; `check` output, JSON and exit code are unchanged without the flag; S1 drift on ACTIVE and DORMANT files; S2 boundary classification; refused inputs.
- Regression: `tests/test_drift_check.py`, `tests/test_a4*.py`, `tests/test_s3_*.py`.
- `research/governance/research_freeze.json` keeps git blob `62b2059b`; `research/foundation/contract.py` and the nine pinned files are unchanged.
