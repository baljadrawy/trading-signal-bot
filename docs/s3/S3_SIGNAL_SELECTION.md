# S3 — Signal Selection Quality: audit and first development slice

**Baseline.**
- Audited tree: `integration/a49-candidate-r2` @ `79295f3` (A38–A48 + #29). For every function below, it is identical to production `59297305` except A44's integrity wiring, which is OFF by default.
- Production runs `LIVE_LEARNING_MODE=true`, `LEARNING_GATES_ENABLED=false` and `GLOBAL_LOSS_COOLDOWN_HOURS=0`. `SIGNAL_INTEGRITY_MODE` does not exist at `59297305`.
- **The operational selector is `SignalEngine.find_best_signal_live`.**

**Evidence class: engineering.** No outcome data, protected window or experiment was used. Nothing here is evidence of profitability.

## 1. End-to-end decision path (audit)

| # | Stage | Where | Inputs → outputs | Effective configuration | Findings |
|---|---|---|---|---|---|
| 1 | Universe | `scanner/scanner_logic.py` `BinanceScanner.scan` / `_passes_initial_filter` → `scan_candidates` | 24h tickers → candidates with `volume_usdt` and `btc_trend` | scanner thresholds | Volume is a 24h snapshot. Its age is never checked downstream (see 5) |
| 2 | Market data and freshness | `analyzer/technical_analyzer.py` `analyze` / `_get_candles` → `prepare_ohlcv` | klines → closed-candle frame. The current candle is dropped by `close_time`; duplicates and gaps are rejected | `CANDLES_TO_FETCH` | Correct closed-candle handling. **Candle freshness is not checked in production.** A 1d setup from a candle that closed up to 24 h ago is still offered while its analysis row is < 30 min old (A43, stale signals). A44's `freshness_at` exists, but only in `enforce` |
| 3 | Candidate generation | `analyzer/simple_entry.py` `detect_trade_setup` (only when `LIVE_LEARNING_MODE`) | last closed bar → `trade_type` ∈ {momentum, reversion} + reason + features | `MOM_BREAKOUT_N`, `MOM_VOL_MULT`, `REV_RSI`, `REV_BB_MAX_POSITION` | Regime-conditioned: momentum only when `bullish`, reversion only when `sideways` (`classify_regime`) |
| 4 | Levels and stop | `technical_analyzer._calculate_levels` → `signal_stop.plan_signal_stop` | ATR / structure / breakout → entry, stop (capped per TF 2/5/4/3 %), T1/T2/T3 = 1.0/1.8/2.2 R, T1 resistance cap | TF caps hard-coded | **No cost coverage.** T1 = 1 R can be smaller than the round-trip cost (20 bps + spread), so a setup can be net-negative even when T1 is hit (A46: T1 → break-even path needs about 0.275 % at 20 bps). The T1 resistance cap can put T1 below 1 R (A45 W3) |
| 5 | Order book | `analyzer/orderbook_analyzer.py`, fetched **once per symbol** and reused for every timeframe (`analyzer/main.py` `analyze_symbol_all_timeframes`) | spread %, validity | — | A symbol's timeframes share one spread and one volume value, so the ranking can never separate them except by the string tie-break (see 7) |
| 6 | Quality and confidence | `technical_analyzer._calculate_scores` → `total_score` | indicator buckets → 0–10 | `indicator_weights` (DB) | **Not used by the live selector.** Historical research found AUC ≈ 0.50, with the order even inverted. It must not become a ranking input without validated evidence |
| 7 | Eligibility, live | `signal_engine/signal_logic.py` `find_best_signal_live` | `analysis_results` rows → eligible list | `MAX_SPREAD_PCT` 0.15 | Gates in order: macro block (fails **closed** on stale macro), `trade_type`, order book valid, spread ≤ limit, `stop_valid is False` → reject, open position, symbol cooldown, learned gate (disabled in production). **Confirmed defects:** (a) **a NaN spread passes**, because `float(nan) > 0.15` is False (A43-D; `tests/test_a43_signal_integrity.py::test_nan_spread_passes_production_filter`); negative spreads pass too; (b) `stop_valid` **None passes** (legacy rows); (c) in production (`off`), the symbol-cooldown read **fails open** on a DB error (`_get_symbol_cooldown_set` returns ∅; A43); (d) the live mode **bypasses** the legacy gates: score / TF-confirmation thresholds (`_get_live_thresholds`), the 30-min inter-signal burst cooldown (`_is_inter_signal_cooldown`) and the global loss cooldown (0 in production anyway) |
| 8 | Dedup and identity | symbol cooldown 2 h (`COOLDOWN_SQL`); A44 `setup_key` insert-once only in `enforce` | — | `SIGNAL_INTEGRITY_MODE` off | Production has no setup identity: same-candle re-emission and duplicate executions are possible (A43) |
| 9 | Ranking and selection | `SignalEngine._fixed_candidate_key` = `(spread, −volume, symbol, timeframe)`; `min(eligible)`; 1 signal per 60 s cycle | eligible → best | — | **Confirmed design defect:** the rank rewards spread and liquidity only. Setup quality, risk geometry and cost/R are ignored, so a 0.30 % stop with T1 netting ≈ +0.005 % beats a 3 % stop whenever its spread is a hair tighter. **Tie-break by timeframe string:** `'15m' < '1d' < '4h'`, so a symbol's 15m setup always beats its 1d/4h setup, because spread and volume are shared (row 5). `min()` over a NaN key depends on input order (A43). Missing volume ranks as 0 |
| 10 | Universe cap | `signal_engine/main.py`: `ORDER BY symbol, total_score DESC LIMIT 200` | — | — | **Confirmed:** truncation is **alphabetical**, so late-alphabet symbols are cut first once more than 200 fresh rows exist. `_v2_truncation` only records it |
| 11 | Persistence and downstream | `save_signal`: `assert_signal_complete` → INSERT + `signal.ready` in one transaction; `analysis_results.signal_generated=true` for the symbol | → telegram (B3 / pause gate) → tracker `register_new_signals` (2 h window, risk guard, fill model) | — | Clean transactional handoff. Coupling: the selector emits at most one signal per cycle, and the tracker's admission (capacity, risk, entry policy) is the next gate. The `features_snapshot` stored with each signal carries the execution features, which audits rely on |

**Hypotheses, not confirmed:**
- A tighter-spread bias may systematically favour large caps, which could correlate with weaker reversion setups.
- The 1d/15m mix chosen by the string tie-break may be skewing the Paper evidence.

Both need outcome data and are not examined here.

## 2. S3 design (`shared/signal_selection.py`, `s3-sel-v1`)

**Approach:** compose reviewed parts. From A43/A44 `candidate_selection`: normalisation, a bounded universe, a hash tie-break. From A42 `signal_quality`: geometry, the cost model, the cost-coverage policy. Then add only what the audit found missing.

| Stage | Rule | Reason codes |
|---|---|---|
| 0 Universe | bounded, hash order, never alphabetical; every dropped row reported | universe record |
| 1 Data quality (**before any scoring**) | known `trade_type`; all levels finite > 0 and strictly ordered `stop < entry < T1 < T2 < T3` (the tracker's rebase rule); `stop_valid is True`; order book valid; spread finite, ≥ 0, ≤ production limit; liquidity known. All failing reasons are reported, not just the first | `no_trade_setup`, `unknown_trade_type`, `bracket_missing`, `bracket_non_finite`, `bracket_not_ordered`, `stop_not_validated`, `stop_rejected:*`, `order_book_unavailable`, `spread_invalid`, `spread_exceeds_limit`, `liquidity_unknown` |
| 2 State | open position, cooldown, learned throttle (**no exploration**, so no adaptive learning), already-emitted setup key | `open_trade_exists`, `symbol_cooldown`, `learned_gate_throttled`, `setup_already_emitted` |
| 3 Integrity (optional) | A44 identity and freshness, exactly as in live `enforce` (`allow_pit_fallback=False`) | `integrity:*`, `integrity_inputs_missing` |
| 4 Economics (execution feasibility) | cost = 20 bps fee (no BNB discount) + observed spread + **declared** slippage (default 0). The T1-then-break-even path must net > 0, and cost ≤ 0.25 R | `t1_path_net_non_positive`, `cost_over_risk_exceeds_cap`, `cost_unavailable` |
| 5 Dedupe | one per symbol, one per setup key; the best-ranked is kept | `duplicate_symbol_lower_rank`, `duplicate_setup_key` |
| 6 Ranking | lexicographic, **no weights**: cost/R ↑, spread ↑, liquidity ↓, stable hash, content digest | rank |
| 7 Selection | top-1 (the production capacity rule), or an explicit **NO_TRADE** | `selected`, `not_selected_capacity`; `no_trade_reason` ∈ {`empty_universe`, `no_eligible_candidate`} |

**Why rank by cost/R.** This is an engineering argument, not a performance claim:
1. All candidates exit under the same frozen R-multiple rules.
2. No validated information separates the gross edge of eligible setups; the score is uninformative.
3. Under that stated *no-information* assumption, net expectancy in R = (unknown common gross term) − cost/R.
4. The candidate losing the smallest share of its risk unit to modelled costs therefore dominates.

It also makes strategies and timeframes comparable in one unit, without assuming that raw scores are comparable.

**Separation of concerns.**
- **Technical setup quality:** stages 1–3 are binary eligibility, because no validated cardinal quality score exists.
- **Execution feasibility:** stage 4, together with the spread and liquidity gates, is kept separate and is reported per candidate (`cost_pct`, `cost_over_risk`, `net_t1_path_pct`, `net_stop_pct`, `risk_pct`, `spread_pct`, `liquidity_usdt`).

**Thresholds:**

| Threshold | Basis |
|---|---|
| `max_spread_pct` = 0.15 | the existing production limit |
| "T1 path net > 0" | arithmetic |
| `max_cost_over_risk` = 0.25 | A42-C1's first-principles cap; **EXPERIMENTAL**, not validated |

None was fitted to outcomes.

**Audit record.** `S3Decision.to_dict()` is a JSON-serialisable record containing the version, the policy, an order-independent input digest, the universe, reason counts and every candidate's stage, reasons, rank and metrics.

**Deterministic and pure:** no I/O, clock, randomness or config import (tested).

## 3. What this slice changes

**Production behaviour: nothing.**
- The module is not imported by any service (isolation registry and source test).
- `signal_logic.py` is untouched.
- No configuration default changed.
- `S3Policy.enabled` and `ENABLED` are `False`.

**Offline harness:** `compare_with_production(sets)` places the exact live-key replica beside the S3 decision. It describes *selector behaviour only*, never outcomes.

On 1000 seeded synthetic sets, the fixture is adversarial by design: many NaN spreads, missing volumes, unvalidated stops and tight stops. Its counts are **not market frequencies**:

| Measure | Value |
|---|---|
| Production would trade | 568 |
| S3 would trade | 142 |
| Same pick | 98 |
| S3 declines where production trades | 426 |

Production picks that S3 refuses, by reason:

| Reason | Count |
|---|---|
| `stop_not_validated` | 180 |
| `liquidity_unknown` | 178 |
| `spread_invalid` | 147 |
| `cost_over_risk_exceeds_cap` | 90 |
| `t1_path_net_non_positive` | 69 |

**Activation consequence.** S3's eligible set is a strict subset of production's (tested), so activating it would **lower signal frequency** and change Paper evidence. That makes it a strategy-behaviour change, requiring owner approval and a declared new Paper window. It is not part of this slice.

## 4. Next slices (each needs review; activation needs the owner)

1. **Shadow wiring:** behind a new flag `S3_SELECTION_MODE=off|shadow`, defaulting to `off`, the engine computes `select_s3` beside the live pick and records only the decision record. It emits nothing and makes no decision change.
2. **Fix the confirmed live defects as declared corrections:**
   - reject a non-finite or negative spread;
   - replace the alphabetical `LIMIT 200` with `bounded_universe`;
   - use an explicit timeframe policy instead of the string tie-break.

   Each changes behaviour, so each needs owner approval and a new Paper window.
3. **Measure, only with authorisation:** real candidate-set rates of each rejection reason, from recorded decision records rather than outcomes.
