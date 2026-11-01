# Portfolio Risk and Compounding — Ledger, Risk Budget and Sizing Contract

**Pack:** Consolidated Remediation & Design Pack, 2026-11-01 · **Work package:** WP1-D · **Remediation item:** R7 (equity ledger and realized-profit compounding)
**Branch:** `docs/wp0-wp1-remediation-design-20261101`, from `main` `46578aa` · **Nature:** documentation and design only.
**Change class of this document:** Documentation/design.

This document reconciles how capital, exposure, drawdown and position size work in the code that runs Paper today. It then specifies a reconciled portfolio ledger, a risk budget and a sizing contract. Under that contract realized **net** profit can be compounded into future sizing, and losses reduce sizing. Every risk percentage, slot count, threshold and cadence is left as an **OWNER DECISION REQUIRED** item, collected in [§6](#6-owner-decisions-required). Nothing here selects a parameter, activates a flag or claims profitability. Correct accounting and sizing do not create an edge. They only make an edge, or the lack of one, measurable in money terms.

## 0. Charter alignment (charter §7)

| Item | Statement |
|---|---|
| 1. Goal alignment | The work serves the charter §1 objective: "compound realized net trading profits into future position sizing; losses must also reduce sizing", without "external deposits, all-in exposure, or spending unrealized gains as free cash" ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §1, §3 D). Discovery stays separate from execution. The ledger never forces a trade, and an unused budget is not a reason to trade. |
| 2. Branch and runtime identity | Code was read at `bb7825f` (trade_tracker, telegram and `shared/`), the documented-deployed commit for those services. Every file cited in §1–§2 is byte-identical between `bb7825f` and `main` `46578aa` (`git diff --stat bb7825f 46578aa` over those paths is empty). SOURCE_VERIFIED. Whether the running images execute this source is NOT_VERIFIED (blocker: image filesystem access; `docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md:L332 @ 5d977f2`, RT-33). |
| 3. Scope | WP1-D, R7. It depends on R4 (stop-slippage accounting, see [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md)) and touches R6 (capacity rejections, see [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md)). **Excluded:** strategy choice (R8), geometry (R2), selection (R1), runtime health (R9), and any parameter value. |
| 4. Evidence classes | Charter §7.4 classes are used throughout. RUNTIME_VERIFIED appears only where the audit addendum is cited. |
| 5. Permission class | Read-only. Every proposed change in [§7](#7-proposed-changes) carries exactly one change class. A disabled flag never authorizes activation (charter §5 WP2). |
| 6. Deliverables and gate | Deliverables: §1–§2 reconciliation, §3–§5 target contract, §6 decisions, §7 changes, §8 tests, §9 acceptance. Gate: owner approval of the §6 decisions before any implementation that changes a strategy version. "No live allocation change" (charter §4, R7). |
| 7. Deviation check | See [§11](#11-deviation-check). No **DEVIATION ALERT** is raised by this design. One design option is excluded because it would treat unrealized gains as capital ([§4.3](#43-sizing-base-and-compounding-from-realized-net-profit)). |

**Citation convention.** `path:Lx-Ly @ commit`, followed by the evidence class. Unmerged material is cited by commit and never linked. Finding IDs use the `PR-` prefix:

| Range | Meaning |
|---|---|
| PR-01 … PR-24 | Reconciliation findings |
| PR-I1 … PR-I14 | Ledger invariants |
| PR-OD1 … PR-OD22 | Owner decisions |
| PR-C01 … PR-C16 | Proposed changes |
| PR-T01 … PR-T20 | Deterministic tests |

## 1. Summary of the existing implementation

| ID | Finding (short) | Class |
|---|---|---|
| PR-01 | No equity ledger exists. Equity is a transient number computed inside each admission check and never persisted. | SOURCE_VERIFIED |
| PR-02 | Capital is the constant `RISK_CAPITAL_USDT` 500. Profits never raise it and losses never lower it. | SOURCE_VERIFIED + RUNTIME_VERIFIED |
| PR-03 | Every position has the fixed notional `TRADE_AMOUNT_USDT` 50. Positions store no notional, quantity or cost basis. | SOURCE_VERIFIED + RUNTIME_VERIFIED |
| PR-04 | No compounding: realized profit never changes any future size. | SOURCE_VERIFIED |
| PR-05 | Losses reduce **capacity** (slots), never notional. `size_multiplier` is computed but never applied to a position. | SOURCE_VERIFIED |
| PR-06 | Realized P&L for risk is rebuilt from `trade_results.profit_usdt` (gross) minus a flat fee recomputed from current config. Stored `net_profit_usdt` and `cost_usdt` are ignored. | SOURCE_VERIFIED |
| PR-07 | Unrealized P&L marks 100% of the notional of every open position. It ignores partial exits already taken and their realized tranche P&L. | SOURCE_VERIFIED; impact INFERRED |
| PR-08 | The drawdown peak is a realized-only high-water mark. The current-equity side includes unrealized P&L. | SOURCE_VERIFIED |
| PR-09 | Daily and weekly loss add the **whole** unrealized P&L of open positions to that period's realized P&L, over a fixed 500 denominator. | SOURCE_VERIFIED |
| PR-10 | A recovery epoch restarts the realized-P&L and peak baseline of every risk metric, not only the loss streak. | SOURCE_VERIFIED mechanism; owner intent NOT_VERIFIED |
| PR-11 | Exposure caps are slot counts × 50 against the fixed 500, not market values or equity. | SOURCE_VERIFIED |
| PR-12 | Working (resting) paper entry orders reserve no capital and count toward no cap. | SOURCE_VERIFIED |
| PR-13 | The sizing-ladder thresholds are dataclass defaults that config cannot set. | SOURCE_VERIFIED |
| PR-14 | Capacity is enforced in three places with two different limits (10 versus min(10, canary)). | SOURCE_VERIFIED |
| PR-15 | Counters are mixed: `risk_management` wins/losses are gross, while `daily_pnl_percent` and the loss streak are net (CON-09). | SOURCE_VERIFIED |
| PR-16 | Costs are one flat round-trip charge per trade on the configured notional, whatever the legs. Stop exits carry extra modeled slippage, a double count (R4). | SOURCE_VERIFIED |
| PR-17 | Close accounting uses the notional configured **at close**, not the one at open. | SOURCE_VERIFIED |
| PR-18 | Quantities are never computed. Lot-size and step rounding are absent. Minimum notional falls back to a config constant on fetch failure. | SOURCE_VERIFIED |
| PR-19 | Results are written idempotently per `signal_id`, and lifecycle steps are serialized per trade inside one process. Some close paths run outside that per-trade lock. | SOURCE_VERIFIED; race impact INFERRED |
| PR-20 | A missing price fails closed as `invalid_risk_state`. There is no staleness bound on a price that is present. | SOURCE_VERIFIED |
| PR-21 | A BTC-beta-weighted exposure policy exists, disabled and outside the live path. | SOURCE_VERIFIED |
| PR-22 | There is no runtime mark-to-market equity series. The governed A29 endpoint is a daily mark-to-market net portfolio excess. | INFERRED (audit) + DOCUMENTED_ONLY |
| PR-23 | Day boundaries mix a UTC Python date with the database `CURRENT_DATE` and naive `TIMESTAMP` columns. | SOURCE_VERIFIED; DB time zone NOT_VERIFIED |
| PR-24 | A reusable Decimal cash/position ledger pattern exists on an unmerged benchmark branch. | SOURCE_VERIFIED (unmerged) |

## 2. Reconciliation of the existing implementation

All code citations in this section are `@ bb7825f`, unless marked otherwise, and SOURCE_VERIFIED. This means they were read in tracked source. That is not proof of runtime behaviour.

### 2.1 Data model: what is stored

- **PR-01 — no ledger table.** The schema has no cash, equity, balance or position-quantity table.
  - `active_trades` holds entry, three targets, stop, `remaining_fraction`, `realized_profit_percent`, `realized_profit_usdt` and `status` (`database/init.sql:L96-L122 @ bb7825f`).
  - `trade_target_fills` holds one row per target leg: `quantity_fraction`, `notional_usdt`, `gross_profit_usdt`, unique on `(active_trade_id, target_number)` (`database/init.sql:L124-L137 @ bb7825f`).
  - `trade_results` holds the gross `profit_usdt` (`DECIMAL(10,4)`) and `result` (`database/init.sql:L77-L92 @ bb7825f`). A38 added `cost_usdt`, `net_profit_usdt`, `economic_result` and `label_policy` (`database/migrations/010_a38_execution_integrity.sql:L23-L31 @ bb7825f`).
  - `paper_entry_orders` holds one durable order per signal, with status `working`, `filled` or `rejected`, and a limit price, but no quantity or notional (`database/migrations/010_a38_execution_integrity.sql:L37-L53 @ bb7825f`).
  - `risk_management` is one row per date with `wins`, `losses`, `consecutive_losses`, `daily_pnl_percent`, `is_trading_paused` and `pause_reason`. Its own comment says `consecutive_losses` is display-only and that the truth is rebuilt from `trade_results` (`database/init.sql:L164-L177 @ bb7825f`).
  - A repository-wide search for equity, ledger, balance or quantity outside research code finds only research scripts and the CPU-budget ledger (`git grep` at `bb7825f`).
  - Class: SOURCE_VERIFIED. The audit's inference "no mark-to-market equity curve at runtime" agrees (`docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md:L1241 @ 5d977f2`, ECO-07, INFERRED).
- **PR-03 — no per-position size.** `active_trades` has no notional, quantity or cost-basis column (`database/init.sql:L96-L122 @ bb7825f`). The admission insert writes none (`trade_tracker/main.py:L864-L884 @ bb7825f`). The notional exists only as the config constant, and as a copy in the optional evidence stream (`trade_tracker/main.py:L368-L381 @ bb7825f`). SOURCE_VERIFIED.

### 2.2 Capital, equity and P&L: how they are computed

`assess_new_trade_risk` (`trade_tracker/main.py:L922-L1006 @ bb7825f`) builds a `RiskSnapshot`, and `evaluate_new_trade` (`shared/risk_management.py:L63-L148 @ bb7825f`) evaluates it under `evaluate_with_policy` (`shared/economic_halt_policy.py:L178-L201 @ bb7825f`).

- **PR-02 — fixed capital.**
  - `capital_usdt = config.RISK_CAPITAL_USDT` (`trade_tracker/main.py:L977 @ bb7825f`). The default is 500 (`shared/config.py:L142 @ bb7825f`).
  - Equity is `capital + realized_total + unrealized` (`shared/risk_management.py:L78-L79 @ bb7825f`).
  - Every percentage divides by the constant capital (`shared/risk_management.py:L59-L60`, `L82-L93 @ bb7825f`).
  - Runtime value 500: RUNTIME_VERIFIED (`docs/audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md:L109 @ 5d977f2`, VER-17).
- **PR-06 — realized P&L basis.**
  - Realized P&L is the sum of `trade_results.profit_usdt` from `effective_risk_start()` onward, each row minus `fee_usdt = TRADE_AMOUNT_USDT × FEE_ROUNDTRIP_PCT / 100` (`trade_tracker/main.py:L928-L934`, `L947-L954 @ bb7825f`).
  - That fee is recomputed from the **current** config on every call. The stored A38 `net_profit_usdt` and `cost_usdt` are not read.
  - Consequence (INFERRED): a later change of `FEE_ROUNDTRIP_PCT` or `TRADE_AMOUNT_USDT` silently re-values every past trade inside the risk guard.
  - The loss-streak helper uses the same recomputation (`shared/risk_epoch.py:L104-L119 @ bb7825f`).
- **PR-07 — unrealized P&L ignores partial exits.**
  - The open-trade query reads only `symbol`, `entry_price`, `trade_type` and the regime key (`trade_tracker/main.py:L935-L941 @ bb7825f`).
  - Unrealized P&L is `(price / entry − 1) × TRADE_AMOUNT_USDT − fee_usdt` per open trade (`trade_tracker/main.py:L967-L974 @ bb7825f`).
  - After a T1 or T2 leg, though, `remaining_fraction` is below 1 and the leg's gross is held in `active_trades.realized_profit_usdt` (`trade_tracker/main.py:L1251-L1259 @ bb7825f`). It reaches `trade_results` only at the final close (`trade_tracker/main.py:L1325-L1332 @ bb7825f`; `shared/partial_exits.py:L47-L55 @ bb7825f`).
  - The snapshot therefore marks the sold tranche at the current price instead of its realized fill. For a position with fraction *f* already sold at target price *T*, the error is *f* × notional × (current − *T*) / entry. It is positive (overstated equity) when price is above *T*, and negative otherwise. INFERRED arithmetic. The realized magnitude is UNKNOWN (no data read).
- **PR-08 — mixed-basis drawdown.**
  - `peak` starts at `RISK_CAPITAL_USDT` and is updated only at closed-trade points: `max(peak, capital + cumulative_realized_net)` (`trade_tracker/main.py:L949`, `L955 @ bb7825f`).
  - Drawdown is `(peak − (capital + realized + unrealized)) / peak` (`shared/risk_management.py:L78-L81 @ bb7825f`).
  - The high-water mark never includes an open gain, while current equity includes open losses and open gains. SOURCE_VERIFIED.
- **PR-09 — period loss windows.**
  - Daily P&L is `(realized net closed today + total unrealized) / 500`. Weekly P&L is the same with the UTC Monday week start (`trade_tracker/main.py:L944-L962 @ bb7825f`; `shared/risk_management.py:L82-L85 @ bb7825f`).
  - A position opened weeks earlier contributes its whole open loss, or gain, to "today". An open gain can offset a realized loss in the daily and weekly checks. SOURCE_VERIFIED mechanism. Consequence INFERRED.
- **PR-10 — recovery epoch moves every baseline.**
  - `effective_risk_start()` is `max(LEARNING_CLEAN_START, newest recovery epoch)` (`shared/risk_epoch.py:L93-L101 @ bb7825f`). It was designed for the loss streak, and its docstring says the epoch "excludes the acknowledged losing tail from future counting" (`shared/risk_epoch.py:L1-L16 @ bb7825f`).
  - `assess_new_trade_risk` uses the same start for cumulative realized P&L, the peak, and the daily and weekly sums (`trade_tracker/main.py:L928-L934 @ bb7825f`). An acknowledged recovery therefore also resets drawdown to zero against a fresh 500 baseline.
  - The owner contract states "No resetting loss counters" (`docs/governance/OWNER_OPERATING_CONTRACT.md:L25 @ 46578aa`, §3, DOCUMENTED_ONLY). The epoch deletes no row.
  - Whether the owner intended the drawdown baseline to move with the streak epoch is NOT_VERIFIED (blocker: no recorded decision found). Owner decision PR-OD18.

### 2.3 Exposure and capacity

- **PR-11 — slot-count exposure.**
  - Post-trade exposures are `(open_count + 1) × trade_amount / capital` for gross, symbol, strategy and regime (`shared/risk_management.py:L86-L93 @ bb7825f`). The caps are 80/10/40/50% (`shared/config.py:L146-L149 @ bb7825f`; RUNTIME_VERIFIED, VER-17).
  - Exposure is never measured at market value or against equity.
  - "Strategy" is `signals.trade_type` and "regime" is `COALESCE(macro_snapshot->>'usdtd_trend', market_condition)` (`trade_tracker/main.py:L935-L941 @ bb7825f`; audit RSK-05 at `docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md:L855 @ 5d977f2`).
  - With 2 slots, the 40% and 50% caps cannot bind (`docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md:L854 @ 5d977f2`, RSK-04, INFERRED). The 10% symbol cap allows exactly one $50 position per symbol on $500.
- **PR-12 — no reserved capital.**
  - A resting paper order (`fill.action == 'wait'`) returns before the risk check (`trade_tracker/main.py:L806-L810` versus `L819-L821 @ bb7825f`).
  - The risk snapshot counts only `active_trades.status='open'` (`trade_tracker/main.py:L935-L941 @ bb7825f`).
  - Working orders therefore consume no capacity and no capital, and the risk check runs only when one becomes fillable. SOURCE_VERIFIED.
- **PR-14 — three capacity checks, two limits.**
  - The tracker pre-checks use `MAX_OPEN_TRADES` (default 10) (`trade_tracker/main.py:L708-L716`, `L752-L759 @ bb7825f`).
  - The risk gate uses `min(MAX_OPEN_TRADES, RISK_CANARY_MAX_OPEN_TRADES)` (`trade_tracker/main.py:L979 @ bb7825f`), and so does telegram delivery (`telegram/main.py:L364-L382 @ bb7825f`).
  - `enforce_max_open_trades` force-closes the most-losing positions only above `MAX_OPEN_TRADES`, labelling them by gross sign (`trade_tracker/main.py:L508-L556 @ bb7825f`).
  - Runtime: canary 2, `MAX_OPEN_TRADES` unset → 10, so the effective capacity is 2. RUNTIME_VERIFIED (`docs/audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md:L104 @ 5d977f2`, VER-12).
  - The code default for the canary is 1 (`shared/config.py:L150 @ bb7825f`).
- **PR-21 — correlated exposure is not live.**
  - `CorrelatedExposurePolicy` (A42-C2) caps BTC-beta-weighted long notional. It is defined with `enabled=False`, a 75 USDT cap and an unknown-beta assumption of 1.5 (`shared/signal_quality.py:L357-L386 @ bb7825f`).
  - Beta comes from aligned closed-bar log returns with at least 30 observations (`shared/signal_quality.py:L329-L345 @ bb7825f`).
  - The staged selection pipeline that would apply it is marked experimental, with the live path on `_fixed_candidate_key` (`shared/candidate_selection.py:L226-L236 @ bb7825f`).
  - None of these values is owner-approved for a target design.

### 2.4 Sizing, compounding and loss-driven reductions

- **PR-04 — no compounding.**
  - Every lifecycle computation uses `config.TRADE_AMOUNT_USDT`: target legs (`trade_tracker/main.py:L1207-L1211`, `L1229`, `L1249 @ bb7825f`), close aggregation (`trade_tracker/main.py:L1328-L1332 @ bb7825f`), wrapper closes (`trade_tracker/main.py:L1404-L1416 @ bb7825f`), the fee (`shared/fees.py:L20-L24 @ bb7825f`) and the barrier P&L (`shared/triple_barrier.py:L34`, `L269-L272 @ bb7825f`).
  - No code path reads realized P&L to set a future size. The audit agrees: "a fixed TRADE_AMOUNT_USDT of 50 … no risk-based or volatility sizing; the tracker never reads `signals.size_multiplier`" (`docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md:L832 @ 5d977f2`, EXE-12).
  - Runtime 50 is RUNTIME_VERIFIED (VER-17, addendum `:L109 @ 5d977f2`). The fixed $50 notional on a fixed $500 means realized profits are never reinvested. SOURCE_VERIFIED.
- **PR-05 — losses reduce capacity, not notional.**
  - `evaluate_new_trade` derives a multiplier: drawdown ≥ 5% → 0.5, ≥ 10% → 0.25; weekly ≤ −5% → 0.5, ≤ −7% → 0.1; loss streak ≥ 3 → 0.5, ≥ 5 → 0.1. The minimum of these is taken (`shared/risk_management.py:L95-L114 @ bb7825f`).
  - The multiplier is used only for `effective_max = max(1, floor(base_max × multiplier))` (`shared/risk_management.py:L116-L120 @ bb7825f`).
  - `size_multiplier` is returned in `RiskDecision` but has no reader in `trade_tracker/main.py` (`git grep size_multiplier` at `bb7825f` finds no use there). The policy module says so explicitly: multipliers "can still lower the capacity used by the max_open_trades check" (`shared/economic_halt_policy.py:L18-L20 @ bb7825f`).
  - With runtime capacity 2, any multiplier ≤ 0.5 gives one slot, and no multiplier gives zero (INFERRED arithmetic; audit RSK-03 at `docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md:L853 @ 5d977f2`, DOCUMENTED_ONLY).
  - Hard economic stops (daily −3%, weekly −10%, drawdown 15%, 7-loss streak) are observations, not blocks, in Paper observe mode (`shared/economic_halt_policy.py:L40-L60`, `L117-L125`, `L178-L201 @ bb7825f`). Observe mode is configured in telegram and trade_tracker: RUNTIME_VERIFIED (`docs/audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md:L96 @ 5d977f2`, VER-04). That it is the executing code path is NOT_VERIFIED (RT-33).
- **PR-13 — ladder thresholds are not configurable.**
  - `assess_new_trade_risk` passes only the capital, the notional, the slot limit, four exposure caps, three hard loss limits and the halt count (`trade_tracker/main.py:L976-L988 @ bb7825f`).
  - `drawdown_caution_pct`, `drawdown_warning_pct`, `weekly_reduce_pct`, `weekly_minimum_pct`, `loss_reduce_count` and `loss_minimum_count` keep their dataclass defaults (`shared/risk_management.py:L16-L23 @ bb7825f`).
  - `shared/risk_management.py` is hash-pinned in research and runtime contracts (`shared/economic_halt_policy.py:L10-L13 @ bb7825f`), so any change to it is a contract change.

### 2.5 Gross versus net, and cost accounting

- **PR-15 — mixed counter bases (CON-09).**
  - On a close, `risk_management.wins` or `losses` is incremented by the **gross** sign, `'WIN' if profit_usdt > 0` (`trade_tracker/main.py:L1371-L1379 @ bb7825f`). The legacy `result` column is gross by design (`shared/fees.py:L32-L41 @ bb7825f`).
  - The same row's `daily_pnl_percent` is the guard's **net** daily figure including unrealized P&L (`trade_tracker/main.py:L1059-L1074 @ bb7825f`).
  - The loss streak is net, `net >= 0` breaks it (`shared/risk_epoch.py:L64-L75 @ bb7825f`).
  - A trade with 0 < gross < cost therefore counts as a `wins` increment, an economic LOSS (`shared/fees.py:L44-L60 @ bb7825f`) and a streak loss, all at once.
  - The audit records the reporting split: /status gross, /stats net (`docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md:L1462 @ 5d977f2`, CON-09, CONTRADICTORY).
- **PR-16 — one flat cost per trade, plus a stop double count.**
  - `economic_close` charges `fee_usdt(notional)`, which is `TRADE_AMOUNT_USDT × FEE_ROUNDTRIP_PCT / 100`: $0.15 at runtime values, once per trade, whatever the number of legs (`shared/fees.py:L20-L24`, `L52-L60 @ bb7825f`).
  - The 0.3% is documented as 0.1% per side plus about 0.1% slippage (`shared/config.py:L89-L92 @ bb7825f`; `shared/signal_quality.py:L73-L76 @ bb7825f`).
  - Stop exits are additionally filled at `stop × (1 − STOP_SLIPPAGE)` (`shared/triple_barrier.py:L308-L322 @ bb7825f`).
  - The stored "gross" of a stop exit is thus already net of one modeled slippage, and a second one sits inside the flat cost. The audit flags this double count (`docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md:L1470 @ 5d977f2`, CON-17; HIS-31 at `:L1149`). It is R4.
  - Expiry exits carry no slippage (`docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md:L820 @ 5d977f2`, EXE-11).
  - Runtime cost values are 0.3 and 0.001: RUNTIME_VERIFIED (VER-19, addendum `:L111 @ 5d977f2`).
  - The charter's proposed research baseline is 0.40% all-in, with 0.60% stress, including 0.10% fee per side. Legacy runtime accounting must stay separate ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §3 C). DOCUMENTED_ONLY.
- **PR-17 — close uses the notional configured at close.** `aggregate_close` and `economic_close` take `config.TRADE_AMOUNT_USDT` at the moment of the close (`trade_tracker/main.py:L1328-L1332`, `L1350 @ bb7825f`). Because no per-position notional is stored (PR-03), a config change while positions are open would re-price their tranches on the new notional. SOURCE_VERIFIED mechanism; INFERRED consequence.
- **PR-18 — no quantity, step size or lot rounding.**
  - Paper P&L is percentage × notional throughout.
  - `get_min_notional` reads only the `NOTIONAL`/`MIN_NOTIONAL` filter, caches it per process, and on any error falls back to `MIN_ORDER_NOTIONAL_USDT`, default 5 (`trade_tracker/main.py:L1453-L1476 @ bb7825f`; `shared/config.py:L108 @ bb7825f`).
  - The minimum is used only to merge sub-minimum T1/T3 tranches into T2 (`shared/partial_exits.py:L14-L23 @ bb7825f`).
  - `LOT_SIZE` and step-size filters are not read anywhere in this path. SOURCE_VERIFIED.

### 2.6 Idempotency, ordering, prices and time

- **PR-19 — idempotency.**
  - `trade_results` inserts use `ON CONFLICT (signal_id) … DO NOTHING`, and counters and the `trade.closed` event are written only when a row was inserted (`trade_tracker/main.py:L1346-L1383 @ bb7825f`).
  - Target legs are unique per `(active_trade_id, target_number)` (`database/init.sql:L124-L137 @ bb7825f`).
  - WebSocket and REST evaluations are serialized by a per-trade `asyncio.Lock` with a fresh row read (`trade_tracker/main.py:L1173-L1186 @ bb7825f`).
  - The leg `UPDATE` of `active_trades` is not conditional on the previous `highest_target_hit`, though. It runs even when the leg insert hit the conflict (`trade_tracker/main.py:L1239-L1259 @ bb7825f`). Its protection is the lock plus the fresh read.
  - Candle-invalidation closes, blacklist closes and max-open closes call `close_trade` outside that lock (`trade_tracker/main.py:L1147-L1169`, `L485-L506`, `L508-L556 @ bb7825f`). They rely on the `_closing` set and the result-row conflict (`trade_tracker/main.py:L1313-L1316 @ bb7825f`).
  - All locks are in-process. INFERRED: safe with one tracker process. A second writer, or a double-booked leg on a lock bypass, is not excluded by schema.
- **PR-20 — prices.**
  - A missing price for any open position makes unrealized P&L NaN, and the decision becomes `invalid_risk_state`, a technical halt that persists a pause in both modes (`trade_tracker/main.py:L967-L972 @ bb7825f`; `shared/risk_management.py:L65-L76 @ bb7825f`; `shared/economic_halt_policy.py:L43-L44`, `L117-L121 @ bb7825f`).
  - Optional bounded retries do not reuse a cached value (`trade_tracker/main.py:L1012-L1038 @ bb7825f`).
  - A price that is present carries no `as_of`, so there is no staleness bound at the risk-snapshot level. SOURCE_VERIFIED.
- **PR-23 — time bases.**
  - The guard computes "today" and the week start in UTC in Python, and treats naive `exit_time` values as UTC (`trade_tracker/main.py:L944-L962 @ bb7825f`).
  - `trade_results.exit_time` is a naive `TIMESTAMP` written with `NOW()` (`database/init.sql:L83 @ bb7825f`; `trade_tracker/main.py:L1357 @ bb7825f`).
  - The `risk_management` row is keyed by the database's `CURRENT_DATE` (`trade_tracker/main.py:L1059-L1063`, `L1374-L1378 @ bb7825f`).
  - These agree only if the database session time zone is UTC. NOT_VERIFIED (blocker: database access is out of scope).

### 2.7 Measurement endpoint and reusable assets

- **PR-22 — no daily mark-to-market series.**
  - The governed claim is "the mean daily mark-to-market net excess over the observed 365-day window", tested with HAC (Bartlett, L = 7) (`docs/strategy/EVIDENCE_LADDER_PARAMETERS.md:L68`, `L76 @ 46578aa`, DOCUMENTED_ONLY). The charter preserves this endpoint ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §5 WP3).
  - Runtime measurement is trade-level only (ECO-07, INFERRED; PR-01). A governed portfolio endpoint therefore needs a ledger that produces one point-in-time equity value per UTC day.
  - ERG-01 notes that utilisation does not change a scale-free risk-adjusted ratio but fixes the economic size, at roughly n·μ/10 a year with 2 × $50 on $500 (`docs/research/evidence-resolution-20261031/POWER_AND_HORIZON_FEASIBILITY.md:L44 @ 0729a5f`, G4-12; RUNTIME_VERIFIED capacity, INFERRED arithmetic).
- **PR-24 — reusable ledger pattern (benchmark branch, unmerged).**
  - `research/design_a/ledger.py @ ebf8d8a` (branch `feature/design-a-v1`, not an ancestor of `46578aa`) implements:
    - an event-entry builder (`:L38-L44`);
    - fills that charge the fee once on quantity × execution price, with explicit residual dust (`:L142-L191`);
    - mark-to-market valuation as cash + position × mark, without a liquidation haircut (`:L196-L232`);
    - per-component cost totals for fee, spread and slippage (`:L235-L240`).
  - It is single-asset, all-in long/cash. Only the patterns transfer, not the sizing rule. Design A is a benchmark, not the mandate ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §2). SOURCE_VERIFIED (unmerged).
  - A second, merged asset is the A46 per-trade exit ledger in `shared/trade_geometry.py` (identical at `bb7825f` and `46578aa`). Its docstring describes "an exact per-leg cost ledger (fee per side on each leg's value, half-spread on market legs, stop slippage in the fill) next to the tracker's flat 0.3 % accounting" and says nothing in production imports it (`shared/trade_geometry.py:L8-L14 @ bb7825f`).
  - Its `ExecutionCosts`, `Leg`, `Ledger` and `exit_ledger` (`shared/trade_geometry.py:L66-L73`, `L231-L262 @ bb7825f`) are float-based and per trade, at a default notional of 50. They are a source of per-leg cost rules, not a portfolio ledger. SOURCE_VERIFIED.

### 2.8 Answers to the reconciliation questions

| Question | Answer | Evidence |
|---|---|---|
| Is there any equity ledger? | No. Equity is computed per admission and discarded (PR-01). | SOURCE_VERIFIED |
| What is capital computed from? | A constant (PR-02). Realized P&L comes from closed `trade_results` since the effective risk start, rebuilt gross minus a recomputed flat fee (PR-06). Unrealized P&L is full-notional on open positions (PR-07). | SOURCE_VERIFIED |
| Gross or net? | Risk metrics are net of the recomputed flat cost. Legacy counters and labels are gross (PR-15). | SOURCE_VERIFIED |
| Exposure from what? | Slot counts × fixed notional ÷ fixed capital. Open positions only; working orders are excluded (PR-11, PR-12). | SOURCE_VERIFIED |
| Drawdown from what? | A realized-only peak against an equity that includes unrealized P&L, re-based at each recovery epoch (PR-08, PR-10). | SOURCE_VERIFIED |
| Are realized profits reinvested? | Never. The fixed $50 notional means no compounding (PR-04). | SOURCE_VERIFIED + RUNTIME_VERIFIED |
| How do losses reduce exposure? | Through a capacity multiplier, from 2 to 1 slot at runtime capacity, never through notional. Hard stops are observed only in Paper observe (PR-05). | SOURCE_VERIFIED; executing path NOT_VERIFIED |

## 3. Target: the reconciled portfolio ledger

### 3.1 Design principles

1. **Event-sourced and append-only.**
   - Every balance change is a `LedgerEntry` derived from one domain event (`OrderIntent`, `Fill`, a mark, a reservation). State is the deterministic fold of entries.
   - Corrections are new entries that reference the corrected one. History is never rewritten, as the owner contract §3 L25 requires (`docs/governance/OWNER_OPERATING_CONTRACT.md:L25 @ 46578aa`, DOCUMENTED_ONLY).
2. **Exact arithmetic.** Use `Decimal` in the quote currency (USDT), with declared quantization per field, as the Design A pattern does (PR-24). No float.
3. **Positions carry their own size.**
   - A `Position` stores quantity, average entry price and cost basis at fill time.
   - No calculation reads a global notional after admission. This removes PR-03 and PR-17.
4. **Cash is cash.**
   - Only realized events (fills, fees) move `cash_free`. Marks never do.
   - Unrealized gains are never available cash and never sizing capital (charter §1, §3 D).
5. **One cost booking per leg per cost model.**
   - A cost is either in the modeled fill price or in an explicit fee entry, never both. This is the R4 boundary, see [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md).
   - Legacy and research cost models are separate ledgers over the same reference events, never mixed in one ledger.
6. **Fail closed on uncertainty.**
   - An unreconciled ledger, a stale or missing mark, or a duplicate-conflicting event is a technical halt reason for new admissions, never an economic observation.
   - This keeps the owner contract's rule that technical safeguards stay fail-closed (`docs/governance/OWNER_OPERATING_CONTRACT.md:L26 @ 46578aa`, DOCUMENTED_ONLY).
7. **Deterministic decisions.** `SizingDecision = size(ledger_state_hash, RiskBudget, Opportunity.risk_plan, MarketSnapshot)`, recorded as a `DecisionRecord` with all input hashes (charter §3 E).
8. **Legacy tables remain the legacy record.**
   - The ledger is additive. `trade_results`, `active_trades` and `risk_management` keep their meaning, so history stays interpretable.
   - The ledger reconciles to them (PR-I13). It does not replace them silently.

### 3.2 Entities (shared glossary)

| Entity | Key fields in this contract |
|---|---|
| `LedgerEntry` | Identity and ordering: `entry_id`, `ledger_id`, `sequence` (gap-free), `event_id` (idempotency key), `event_type`, `as_of` (UTC, tz-aware), `cost_model_version`, `strategy_id`/`strategy_version`, `position_id`/`intent_id`. Balance deltas: `Δcash_free`, `Δreserved`, `Δcommitted_cost`, `Δrealized_gross`, `Δfees`. Leg detail: `qty`, `ref_price`, `fill_price`, `fee_rate`, `fee_amount`, `fee_asset`, attribution (`spread_cost`, `slippage_cost`; balance-neutral). Integrity: `prev_state_hash`, `state_hash`, `corrects_entry_id` (corrections only). |
| `Position` | `position_id`, `symbol`, `strategy_id`, `strategy_version`, `regime_label`, `opened_at`, `qty_open`, `avg_entry_price`, `cost_basis`, `qty_exited`, `legs[]`, `stop_level`, `stop_fill_model`, `targets[]`, `holding_policy`, `state` (`pending` → `open` → `partially_exited` → `closed`), `risk_at_stop`, `last_mark` (`price`, `as_of`, `source`). |
| `RiskBudget` | `budget_version`. Portfolio and per-trade limits: `sizing_base_rule`, `per_trade_risk` or `per_trade_notional_fraction`, `portfolio_heat_cap`. Exposure caps: `gross_cap`, `symbol_cap`, `strategy_cap`, `regime_cap`, `cluster_cap`, `max_positions`, `cash_reserve`, `liquidity_cap`. Controls: `drawdown_ladder[]`, `loss_streak_ladder[]`, `period_loss_limits`, `mark_max_age`, `mode` (`enforce`/`observe` for economic limits only). All values come from §6 owner decisions. |
| `SizingDecision` | Inputs: `decision_id`, `opportunity_ref`, `ledger_state_hash`, `budget_version`, `sizing_base` and its components, `ladder_multiplier` with reasons. Sizing: `raw_size`, then the constraint stages with the binding constraint named (risk, notional cap, heat, cash, liquidity, min-notional, step size), `final_qty`, `final_notional`, `expected_entry_cost`. Outcome: `outcome` (`size` / `reject` with `RejectionRecord` reason code). |

### 3.3 Ledger state and event effects

The state consists of `net_contributions` (genesis plus explicit deposits minus withdrawals), `cash_free`, `reserved`, `committed_cost` (Σ open `qty_open × avg_entry_price`, fees excluded), `realized_gross` and `fees` (all exchange fees paid, entry and exit).

| Event | Δcash_free | Δreserved | Δcommitted_cost | Δrealized_gross | Δfees | Precondition |
|---|---|---|---|---|---|---|
| `GENESIS(a)` | +a | 0 | 0 | 0 | 0 | First entry of a ledger only; `net_contributions` += a |
| `RESERVE(intent, r)` | −r | +r | 0 | 0 | 0 | `cash_free ≥ r`; one active reservation per intent |
| `RELEASE(intent)` | +r_left | −r_left | 0 | 0 | 0 | Reject, cancel or expiry; releases exactly the unconsumed remainder |
| `ENTRY_FILL(intent, q, p, f)` | +c − q·p − f | −c | +q·p | 0 | +f | c = consumed reservation; `cash_free` stays ≥ 0 |
| `EXIT_FILL(position, leg, q, p, f)` | +q·p − f | 0 | −q·avg | +q·(p − avg) | +f | `q ≤ qty_open`; leg id unique per position |
| `MARK(symbol, price, as_of, source)` | 0 | 0 | 0 | 0 | 0 | Updates `last_mark` only |
| `COST_ATTRIBUTION(leg, parts)` | 0 | 0 | 0 | 0 | 0 | Decomposes `ref_price − fill_price`; never books |
| `CORRECTION(of, deltas)` | per deltas | per deltas | per deltas | per deltas | per deltas | Owner-approved only; references the original; never automatic |

Derived quantities:

- realized net: `realized_net = realized_gross − fees`;
- book equity at cost: `E_cost = cash_free + reserved + committed_cost`;
- unrealized: `unrealized = Σ qty_open × (mark − avg_entry_price)`, before any haircut;
- mark-to-market equity: `E_mtm = cash_free + reserved + Σ qty_open × mark = E_cost + unrealized`.

Under the legacy cost model the per-leg fee is zero. One cost entry equal to `notional × FEE_ROUNDTRIP_PCT / 100` is booked at the final close, which reproduces `shared/fees.py:L52-L60 @ bb7825f`. That is the only purpose of the legacy model: reconciling with stored history (PR-I13).

### 3.4 Reconciliation invariants (checked after every transition)

| ID | Invariant |
|---|---|
| PR-I1 | **Accounting identity**, exact in `Decimal`: `cash_free + reserved + committed_cost = net_contributions + realized_gross − fees`. |
| PR-I2 | **Spot, long-only, unleveraged:** `cash_free ≥ 0`, `reserved ≥ 0`, every `qty_open ≥ 0`, `committed_cost ≥ 0`. With PR-I1, gross exposure at cost ≤ `E_cost`. |
| PR-I3 | **Reservation conservation:** `reserved = Σ` active reservations. Each reservation ends exactly once, consumed by fills or released. |
| PR-I4 | **Quantity conservation:** per position, `Σ entry qty − Σ exit qty = qty_open`. Exit legs never exceed the filled quantity. |
| PR-I5 | **Cost-basis consistency:** the running `committed_cost` equals `Σ qty_open × avg_entry_price` recomputed from positions. |
| PR-I6 | **No orphan P&L:** `realized_gross` and `fees` equal the sums of their per-position leg values. Every fee belongs to one leg or one legacy close. |
| PR-I7 | **Idempotency:** `event_id` is unique per ledger. A repeated `event_id` with an identical payload is a recorded no-op. A repeated `event_id` with a different payload is a technical halt (`ledger_event_conflict`). |
| PR-I8 | **Replay determinism:** the fold of the entry log reproduces the maintained state and its `state_hash` exactly. The hash chain (`prev_state_hash`) is unbroken. |
| PR-I9 | **Marks never move cash:** no `MARK` sequence changes `cash_free`, `reserved`, `committed_cost`, `realized_gross`, `fees` or the sizing base computed under rule (a) of §4.3. |
| PR-I10 | **Unrealized gains are never capital:** the sizing base is ≤ `E_cost` under every option allowed in §4.3. |
| PR-I11 | **Single booking:** per leg and cost model, a cost component appears either in `fill_price` or as `fee_amount`, never both. Attribution entries are balance-neutral. |
| PR-I12 | **Append-only:** no update or delete of entries. A correction carries `corrects_entry_id` and an approval reference. |
| PR-I13 | **Legacy reconciliation:** for each position closed under the legacy cost model, ledger realized net equals the stored `trade_results.net_profit_usdt` within the declared quantization. A mismatch is a technical halt (`ledger_mismatch`) plus a discrepancy record, never a silent adjustment. |
| PR-I14 | **Time:** every entry has a tz-aware UTC `as_of` and a strictly increasing `sequence`. Day and week boundaries are UTC. Naive timestamps are rejected. |

### 3.5 Mark-to-market: source, staleness and the daily series

- **Mark record.** Every mark carries `price`, `as_of` (exchange event time where available, else receipt time, labelled as such) and `source` (stream or REST). Marks come from a `MarketSnapshot` and never from a fill.
- **Staleness.** A mark is `FRESH` when `now − as_of ≤ mark_max_age`, otherwise `STALE`. If any open position's mark is `STALE` or missing:
  - `E_mtm`, unrealized P&L, drawdown and heat are `UNKNOWN`;
  - new admissions are refused with the technical reason `mark_stale`.

  This extends the existing NaN → `invalid_risk_state` behaviour (PR-20) with an explicit age bound. Exit management of open positions is unaffected; it is governed by [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md). The value of `mark_max_age` is PR-OD4.
- **Price basis (PR-OD3).** Options are last trade, best bid, or mid.
  - Best bid is the conservative liquidation value for a long book.
  - Last trade matches today's tracker inputs.
  - Mid ignores the half-spread a long exit pays.
- **Haircut (PR-OD5).** Options are none, as in Design A (PR-24), or the modeled exit cost of the active cost model.
  - A haircut lowers `E_mtm` and therefore the drawdown and heat inputs.
  - It never changes `cash_free`.
- **Daily series for the A29 endpoint (PR-22, PR-OD6).**
  - One `E_mtm` value per UTC day, built from point-in-time marks at the day boundary. Options for the mark: the closed 1d candle close, or the last fresh stream mark before the boundary.
  - The series is the input to the daily mark-to-market net excess. Its benchmark leg belongs to [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md) and WP3, not to this document.
  - A day with any `STALE` mark is recorded as `UNKNOWN` and never interpolated.

### 3.6 Fees and modeled costs per leg

- **Recorded per leg:** `ref_price` (limit, stop level, target or decision price), `fill_price` (modeled), `fee_rate`, `fee_amount`, `fee_asset` and `cost_model_version`.
- **Attribution.** `slippage_cost = qty × |ref_price − fill_price|` in the adverse direction, with spread attribution where a spread is observed. It is attribution only (PR-I11).
- **Cost models are versioned inputs, not ledger code:**
  - `legacy_tracker_30bps`: a flat round trip at the close, only for reconciliation (§3.3);
  - the charter's proposed research baseline, 0.40% all-in round trip;
  - its 0.60% stress case.

  Both research models include the 0.10% fee per side and charge it per leg on the leg notional (charter §3 C, DOCUMENTED_ONLY; owner contract §1 `docs/governance/OWNER_OPERATING_CONTRACT.md:L10 @ 46578aa`, DOCUMENTED_ONLY). The existing `CostModel` (`shared/signal_quality.py:L45-L76 @ bb7825f`) already separates fee, entry and exit slippage, stop slippage and spread, and and the A46 `exit_ledger` (PR-24) already books fee per side on each leg's value with stop slippage in the fill. Either can be the source of the per-leg rates; neither is a portfolio ledger.
- **Stop exits (R4).** Under a research model, stop slippage lives only in the stop `fill_price`, and the fee is the per-side rate. The legacy 0.3% flat charge is never added on top. The defect and its geometry consequences are owned by [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md) and [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md) (R4). The ledger only guarantees single booking.
- **Which model the Paper ledger books (PR-OD7)** is a strategy-version property. Shadow ledgers under the other models are pure folds over the same event stream (PR-T15).
- **Fee asset (PR-OD8).** Spot venues can charge the fee in the received asset or in a third asset. For an exchange-agnostic design, the convention must be fixed per venue. The Paper default is quote currency, as all current Paper accounting assumes (PR-16).

## 4. Risk budget, sizing and drawdown controls

### 4.1 Exposure measures

Each measure is computed post-trade (including the candidate) and reported at cost and at mark. Which basis binds is PR-OD10.

| Measure | Definition | Today (PR-11) |
|---|---|---|
| Gross | `(committed + reserved + candidate) / E_ref`. E_ref is the sizing base or `E_mtm` (PR-OD10). | slots × 50 / 500 |
| Per symbol | Same, restricted to one symbol. One open position per symbol remains a separate rule (`trade_tracker/main.py:L730-L733 @ bb7825f`). | slots × 50 / 500 |
| Per strategy | Keyed by `StrategyVersion.strategy_id`, not `signals.trade_type`. | `trade_type` slots |
| Per regime | Keyed by the `RegimeContext` label recorded at admission. The source and staleness come from [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md). | USDT.D trend key (RSK-05) |
| Correlated cluster | Beta-weighted or cluster-summed notional. The source is PR-OD11. | Disabled policy (PR-21) |
| Portfolio heat | `Σ risk_at_stop / E_ref`, where `risk_at_stop = qty_open × (avg_entry − modeled stop fill) + modeled exit cost`, floored at 0. Gap risk beyond the modeled stop fill is not covered and must be stated with the number. | none |
| Reserved | Working intents at their reservation amount (PR-12 remediation). | none |

- **Correlation and beta source (PR-OD11).** Options:
  1. BTC beta from aligned closed-bar log returns, reusing `beta_and_correlation` (`shared/signal_quality.py:L329-L345 @ bb7825f`), with an owner-set window, timeframe and unknown-beta fallback;
  2. static clusters, for example by sector or base-asset family, from a versioned mapping;
  3. none, relying on per-symbol and gross caps.

  Trade-offs:
  - Estimated betas are noisy on short windows and regime-dependent, and they need closed-bar point-in-time data.
  - Static clusters are reproducible but coarse.
  - With "none", concentration in high-beta majors goes unmeasured. The audit notes that ranking favours the deepest majors (`docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md:L701 @ 5d977f2`, UNI-19, INFERRED).

  Any cap value is PR-OD12. The existing 75 USDT default is not approved policy.

### 4.2 Risk budget

A `RiskBudget` is versioned (`budget_version`) and immutable for the duration of a strategy-version window. It contains:

- the sizing base rule (PR-OD9);
- the per-trade risk or notional rule (PR-OD13, PR-OD14);
- portfolio heat (PR-OD15);
- exposure caps (PR-OD10, PR-OD12);
- maximum positions (PR-OD16);
- the cash reserve (PR-OD17);
- the liquidity cap (PR-OD19);
- the minimum-order handling, sourced from `MarketSnapshot` `exchangeInfo` filters (`NOTIONAL`/`MIN_NOTIONAL` and `LOT_SIZE` step, addressing PR-18);
- the drawdown and loss-streak ladders (PR-OD20, PR-OD21);
- the period-loss windows (PR-OD22).

**"Reserve" has two meanings.**
- The charter §3 D *cash reserve* is unallocated capital.
- The A29 *20% reserve* is 20% of slot-days for reserve candidates, not capital (`docs/strategy/EVIDENCE_LADDER_PARAMETERS.md:L71 @ 46578aa`, DOCUMENTED_ONLY).

This document uses "cash reserve" only for the first. Slot-day reservation stays with WP3 ([DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md)).

### 4.3 Sizing base and compounding from realized net profit

The sizing base `B` is the only capital figure that sizes new positions. It is computed from the ledger and recorded in each `SizingDecision`.

| Option (PR-OD9) | Definition | Compounds | Effect of losses | Trade-off |
|---|---|---|---|---|
| (a) Book at cost | `B = E_cost = net_contributions + realized_net` | Realized net gains, after settlement | Realized losses at once. Open losses are not counted until realized. | Simple, mark-independent and fully reproducible. It lags open drawdowns. |
| (b) Conservative | `B = min(E_cost, E_mtm)` | Realized net gains, after settlement | Realized losses and open losses at once | Satisfies "losses reduce sizing" fastest. Sizing becomes mark-dependent: a stale mark blocks sizing, and recoverable open losses shrink size. |
| ~~(x) Mark-to-market~~ | ~~`B = E_mtm`~~ | — | — | **Excluded:** it lets unrealized gains raise capacity, contrary to charter §1, §3 D and §7.7. |

**Settlement of gains (PR-OD9, second part).** A realized net gain enters `B` only when three conditions hold:

1. the position is fully closed, so all legs are booked;
2. its close reconciles (PR-I13, or the research-model equivalent);
3. the settlement point has passed.

Options for the settlement point:
- S1 at the close;
- S2 at the next UTC day boundary;
- S3 at a weekly step;
- S4 after a fixed number of further closes.

Trade-offs:
- S1 is the most responsive and the most path-dependent.
- S2 and S3 make `B` piecewise constant, which simplifies reproducibility and the daily A29 series.
- S4 adds sample-based damping.

Realized **losses** reduce `B` at once under every option. This asymmetry is the conservative default, and the owner may make the rule symmetric explicitly.

**Compounding caps (PR-OD9, third part).** Options, which can be combined:
- C-1, a maximum relative step-up of `B` per settlement step;
- C-2, an absolute per-position notional ceiling from liquidity (PR-OD19);
- C-3, a ceiling on `B` itself, so that gains above it stay as unallocated cash.

None is set here.

**What never feeds `B`:**
- unrealized gains;
- external deposits, because compounding does not mean deposits (charter §1). A deposit is an explicit `net_contributions` event, and returns are reported contribution-adjusted;
- reversals of past losses;
- any correction without an owner-approved reference (PR-I12).

### 4.4 Position sizing methods (PR-OD13)

Notation: `B` is the sizing base, `s` the relative per-unit loss at the modeled stop fill including exit cost, and `m` the venue minimum notional.

| Method | Size rule | Compounds | Risk at stop | Trade-off |
|---|---|---|---|---|
| M1 Fixed notional (legacy) | `notional = N` | No | Varies with `s` | Today's behaviour (PR-04). Kept as the reproducible legacy mode and benchmark. It does not meet the charter's compounding objective. |
| M2 Fixed fraction | `notional = φ · B` | Yes | Varies with `s` | Simple. Loss at stop differs across setups with different stop distances. |
| M3 Risk per trade | `notional = ρ · B / s`, capped at `κ · B` | Yes | ≈ `ρ · B`, below gaps | Matches "risk-based sizing" (charter §3 D) and equalises planned loss. Tight stops inflate notional, so the cap `κ`, heat and liquidity limits are mandatory. Stop gaps exceed `ρ`. It depends on correct geometry (R2) and a correct stop-fill model (R4). |
| M4 Volatility-scaled | `notional = (σ* / σ_asset) · B` | Yes | Varies | Needs a point-in-time volatility estimator. It adds an estimator with its own parameters, which would be untuned and unregistered. |

**Feasibility algebra under M3** (identities, not proposals):
- the minimum notional binds when `ρ · B / s < m`, that is when `ρ < m · s / B`;
- the notional cap binds when `s < ρ / κ`.

Under both M2 and M3 a small `B` makes the 25/50/25 tranches fall below `m` more often, and the existing merge rule then changes the exit profile (`shared/partial_exits.py:L14-L23 @ bb7825f`). A sizing change can therefore alter exit behaviour, which is a further reason it is a strategy-version boundary.

**Constraint stages** (order fixed and recorded; the first binding stage is named in the `SizingDecision`):

1. raw size by method;
2. × ladder multiplier (§4.6);
3. per-position notional cap;
4. heat cap;
5. exposure caps (§4.1);
6. available cash: `cash_free − cash reserve`;
7. liquidity cap;
8. round **down** to the venue step size;
9. if the result is below `m`, reject with `below_min_notional`. It is never rounded up.

The residual goes back to cash. A rejection is recorded as a `RejectionRecord`, never a silent drop ([OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md)).

### 4.5 Drawdown controls from an equity high-water mark

| Element | Options | Decision |
|---|---|---|
| High-water mark basis | H-1, `E_mtm` at every fresh valuation. H-2, the daily `E_mtm` series of §3.5. H-3, `E_cost`, which is close to today's realized-only peak (PR-08). | PR-OD20 |
| Drawdown | `DD = 1 − E_mtm / H` (H-1 and H-2), or `1 − E_cost / H` (H-3). It is computed only from `FRESH` marks; otherwise it is `UNKNOWN` and the technical refusal applies (§3.5). | follows the basis |
| Ladder | Thresholds mapped to multipliers on size, on slots, or on both (§4.6). The legacy 5/10/15% and 0.5/0.25 values are the starting record, not a proposal (PR-05). | PR-OD20 |
| Pause | At a maximum DD, no new admissions. Enforce or observe follows the owner's Paper policy (`docs/governance/DEVELOPMENT_FIRST_POLICY.md:L15 @ 46578aa`, DOCUMENTED_ONLY). | PR-OD20 |
| Kill switch | Technical, always blocking: `ledger_mismatch`, `ledger_event_conflict`, `mark_stale`, a broken hash chain, an unreconciled restart. Economic: owner-defined, and never automatic liquidation of swing or position holdings unless their own exit policy says so. | PR-OD20 (economic part) |
| Re-basing | Whether a recovery acknowledgement moves H (PR-10). Options: R-a, H is continuous and never re-based; R-b, H is re-based at an owner-acknowledged epoch, recorded as a ledger event with an approval reference. | PR-OD18 |

### 4.6 Loss-driven size reductions (de-risking ladders)

Under §4.3 a realized loss already shrinks `B`, so every size falls proportionally. A ladder adds a further, convex reduction. The owner must choose whether that double effect is intended (PR-OD21).

| Option | Mechanism | Recovery rule | Trade-off |
|---|---|---|---|
| L-0 None | The `B` reduction only | — | Purely proportional, with no extra convexity. |
| L-1 Capacity only (legacy) | Slots `max(1, floor(slots × m))` | Immediate, when the trigger clears | Today's behaviour (PR-05). With few slots it is coarse: 2 → 1. Notional is unchanged. |
| L-2 Size multiplier | Size × `m(DD, streak, period loss)`, minimum of triggers | Immediate, or with hysteresis | Smooth. Needs thresholds and multipliers. |
| L-3 Risk-fraction steps | `ρ` lowered stepwise (M3 only) | Step up only after a new H, or after k net-winning closes | Explicit risk control. Recovery can be slow. |
| L-4 Continuous | Size ∝ `(E/H)^k` | Automatic as E recovers | No cliffs. The exponent is an untested parameter. |

**Common rules for every option:**
- Every trigger uses net figures from the ledger (PR-15 remediation).
- The loss streak keeps today's net semantics, where `net ≥ 0` breaks it (`shared/risk_epoch.py:L64-L75 @ bb7825f`).
- The multiplier and its reasons are recorded in the `SizingDecision`.
- A ladder never stops exits, and never force-closes a position outside its own exit policy.

### 4.7 Interaction with Paper observe policy and the A29 endpoint

- **Paper observe.** The owner-approved Paper policy makes economic outcomes observations, while technical safeguards stay fail-closed (`docs/governance/OWNER_OPERATING_CONTRACT.md:L24-L26 @ 46578aa`, DOCUMENTED_ONLY). The target keeps that split:
  - ledger-integrity and mark-staleness reasons are **technical**;
  - drawdown and period-loss pauses are **economic**, and their enforce or observe mode is set by the owner;
  - ladders are **sizing**, as already classified (`shared/economic_halt_policy.py:L18-L20`, `L56-L60 @ bb7825f`).
- **A29.** A sizing policy changes the daily portfolio excess series. The sizing method, `B` rule, settlement, caps and ladders are therefore part of the `StrategyVersion` contract hash. They are fixed before a governed window and never changed inside one ([DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md), WP3).
- **Power.** Compounding scales P&L. It does not raise the power of a scale-free test (G4-12, PR-22), and it is no evidence of an edge.

## 5. Deterministic decision flow

`decide(state, snapshot)` for one `Opportunity`. Each step either passes or emits a `RejectionRecord` with a reason code.

1. **Verify the ledger.** PR-I1 to PR-I14 hold, the hash chain is intact, and reconciliation is current. Otherwise reject with a technical reason.
2. **Value.** Collect marks for all open positions. Any `STALE` mark rejects with `mark_stale`, technical. Compute `E_cost`, `E_mtm`, H, DD, heat, exposures, the period P&L (UTC windows) and the streak.
3. **Apply economic controls.** Evaluate the pause and halt rules under the owner's mode. In observe mode, record `observed:<rule>` exactly as today (`shared/economic_halt_policy.py:L178-L201 @ bb7825f`).
4. **Size.** Compute `B` by rule and settlement, the ladder multiplier, and the method's raw size. Apply the constraint stages of §4.4.
5. **Reserve.** On success, emit `RESERVE(intent, r)` with `r` = notional at limit + entry fee + an owner-set buffer (PR-OD17), and record the `SizingDecision` and `DecisionRecord` with the input hashes.
6. **Settle.** Fills, legs, releases and marks are applied as ledger events (§3.3). Each transition re-checks the invariants.

**Legacy mode.**
- `RiskBudget` mode `legacy_v1` reproduces `evaluate_new_trade` exactly, with M1, L-1, capital 500 and slot exposure.
- It must produce byte-identical `RiskDecision` legacy fields on golden fixtures (PR-T09), so that the ledger can run in shadow beside the legacy guard with no decision change.

## 6. Owner decisions required

None of the following has an approved value. Every row is **OWNER DECISION REQUIRED**. The record of decisions lives in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md).

| ID | Decision | Options | Main trade-offs | Blocks |
|---|---|---|---|---|
| PR-OD1 | Ledger genesis for Paper | (i) New genesis at the first ledger version boundary. (ii) Genesis at `LEARNING_CLEAN_START` with legacy history folded under the legacy cost model. (iii) Separate ledgers per strategy sleeve. | (ii) gives continuity but imports mixed-version history (ECO-04, `docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md:L1232 @ 5d977f2`, INFERRED). (i) is clean but has no history. (iii) isolates attribution but fragments capital. | PR-C05 |
| PR-OD2 | Genesis capital amount | Keep the virtual 500, or another virtual amount | Scale only. No effect on scale-free metrics (G4-12). It interacts with min notional (§4.4). | PR-C05 |
| PR-OD3 | Mark price basis | Last trade, best bid, or mid | Conservatism versus parity with current tracker inputs | PR-C06 |
| PR-OD4 | Mark staleness bound `mark_max_age` | A fixed age, a per-timeframe age, or stream-health-coupled | Too short gives technical refusals. Too long gives decisions on old prices. | PR-C06 |
| PR-OD5 | Valuation haircut | None, or the modeled exit cost | Conservatism of DD and heat versus comparability with Design A | PR-C06 |
| PR-OD6 | Daily mark for the A29 series | Closed 1d candle close, or the last fresh mark before the UTC boundary | Reproducibility versus timeliness. It must match the WP3 endpoint definition. | PR-C12 |
| PR-OD7 | Cost model booked by the Paper ledger | Legacy 0.3% flat (reconciliation only), the research baseline 0.40%, or the stress 0.60% | Booking a research model changes admission inputs, so it is a version boundary. Legacy keeps parity with history. | PR-C07 |
| PR-OD8 | Fee asset convention per venue | Quote currency, base asset, or third asset | Exchange-agnostic correctness versus simplicity | PR-C02 |
| PR-OD9 | Sizing base rule, gain settlement and compounding caps | Rule (a) or (b); settlement S1–S4; caps C-1, C-2, C-3 | §4.3 | PR-C08 |
| PR-OD10 | Exposure denominator and basis | `B`, `E_cost` or `E_mtm`; at cost or at mark | Stability versus responsiveness to open moves | PR-C09 |
| PR-OD11 | Correlation or beta source | BTC beta (window, timeframe, fallback), static clusters, or none | §4.1 | PR-C10 |
| PR-OD12 | Exposure cap values: gross, symbol, strategy, regime, cluster | Keep the legacy 80/10/40/50 as a record, or set new values | Legacy values are fractions of a fixed 500 (PR-11). Under a moving base their meaning changes. | PR-C09, PR-C10 |
| PR-OD13 | Sizing method | M1, M2, M3 or M4 | §4.4 | PR-C08 |
| PR-OD14 | Per-trade value: `N`, `φ`, `ρ` with `κ`, or `σ*` | Any value, by method | Higher compounds faster with deeper drawdowns. Lower makes min notional bind (§4.4 algebra). | PR-C08 |
| PR-OD15 | Portfolio heat cap | A value, or none | Bounds the simultaneous loss at stops. It does not bound gaps. | PR-C09 |
| PR-OD16 | Maximum positions (slots) | Keep the runtime 2, or another count | Concurrency versus concentration. It interacts with the A29 candidate and slot design (≤ 3 candidates, `docs/governance/OWNER_OPERATING_CONTRACT.md:L35 @ 46578aa`, DOCUMENTED_ONLY). | PR-C09 |
| PR-OD17 | Cash reserve and reservation buffer | A fraction of `B` held unallocated, and a buffer on reservations | Idle capital versus fill and fee shortfall | PR-C11 |
| PR-OD18 | Recovery epoch and drawdown baseline | R-a continuous H, or R-b re-base at an acknowledged epoch | R-a honours "no resetting" (owner contract L25) but may keep size reduced for long. R-b restores size after a manual acknowledgement. | PR-C13 |
| PR-OD19 | Liquidity capacity | A cap as a fraction of 24h quote volume, a depth-based cap, or none | Realism for larger `B`. It needs point-in-time liquidity data. | PR-C08 |
| PR-OD20 | Drawdown basis, ladder, pause and economic kill switch | H-1, H-2 or H-3; thresholds and multipliers; enforce or observe | §4.5 | PR-C13 |
| PR-OD21 | Loss de-risking ladder | L-0 to L-4; triggers; recovery rule | §4.6 | PR-C13 |
| PR-OD22 | Period-loss windows | Today's realized-today plus all unrealized (PR-09), or realized-in-period plus the change in unrealized over the period | Comparability with history versus correctness of attribution | PR-C13 |

## 7. Proposed changes

Each change carries exactly one change class. All link to R7. Secondary links are given in brackets. Sub-item numbering is owned by [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md), and sequencing by [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md). Activation of any default-off code is a separate change (PR-C16) and is never implied (charter §5 WP2).

| ID | Change | Change class | R-item | Depends on | Tests | Acceptance |
|---|---|---|---|---|---|---|
| PR-C01 | This contract: ledger, risk budget and sizing design, and the decisions table | Documentation/design | R7 | — | Self-check | Pack review. Every §6 row is recorded in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md). |
| PR-C02 | A pure ledger library (`Decimal`, event fold, invariants PR-I1 to PR-I14, state hash). No I/O. Not imported by any service. | Safe development-only correction (default-off, no runtime effect) | R7 | PR-OD8 for the fee asset (quote-only until decided) | PR-T01 to PR-T08, PR-T11, PR-T16 | All invariant property tests pass on synthetic events. There is no import from a runtime service (import-graph test). |
| PR-C03 | A legacy-mode adapter: maps synthetic `active_trades`, `trade_target_fills` and `trade_results` row fixtures into ledger events under `legacy_tracker_30bps`, and reconciles them (PR-I13). | Safe development-only correction (default-off, no runtime effect) | R7 [R5] | PR-C02 | PR-T09, PR-T10, PR-T17 | Fixture reconciliation is exact within quantization. Each PR-07 and PR-17 divergence is reproduced as a named discrepancy. |
| PR-C04 | An additive schema migration: ledger entry table (append-only, unique `event_id`, gap-free `sequence`), and per-position `qty`, `avg_entry_price` and `cost_basis` columns, NULL on history. Authored and tested only on a disposable database. | Safe development-only correction (default-off, no runtime effect) | R7 | PR-C02 | PR-T18 | The migration is idempotent and backward compatible: pre-change code runs against it, as with A38 (`database/migrations/010_a38_execution_integrity.sql:L1-L5 @ bb7825f`). |
| PR-C05 | A shadow ledger writer in the tracker behind a default-off flag. It writes entries from existing lifecycle events and changes no decision. | Safe development-only correction (default-off, no runtime effect) | R7 [R5] | PR-C03, PR-C04, PR-OD1, PR-OD2 | PR-T02, PR-T04, PR-T09, PR-T19 | With the flag off, behaviour is byte-identical. With the flag on in tests, admission decisions are unchanged on fixtures. |
| PR-C06 | Mark records with `as_of` and `source`, and the `mark_stale` technical refusal | Strategy-version-changing correction | R7 [R9] | PR-OD3, PR-OD4, PR-OD5 | PR-T08 | No admission on a stale mark. The reason is recorded. Exit management is untouched. |
| PR-C07 | Risk inputs from the ledger: stored per-position costs instead of recomputed flat fees (PR-06), partial-exit-aware unrealized P&L (PR-07), per-position notional at close (PR-17), UTC-explicit windows (PR-23) | Strategy-version-changing correction | R7 [R4] | PR-C05, PR-OD7, PR-OD22 | PR-T10, PR-T15, PR-T16 | Fixture decisions differ from legacy only where PR-06, PR-07, PR-17 or PR-23 predicts, and each difference is explained. |
| PR-C08 | A sizing engine producing `SizingDecision` (method, `B` rule, settlement, caps, constraint stages, step rounding, min-notional rejection) | Strategy-version-changing correction | R7 | PR-C02, PR-OD9, PR-OD13, PR-OD14, PR-OD19 | PR-T06, PR-T07, PR-T11, PR-T12, PR-T20 | `B` never includes unrealized gains. Gains enter only after settlement, losses at once. The binding stage is always named. |
| PR-C09 | Exposure, heat and slot caps on ledger values (gross, symbol, strategy by `strategy_id`, regime) | Strategy-version-changing correction | R7 [R6] | PR-C08, PR-OD10, PR-OD12, PR-OD15, PR-OD16 | PR-T13 | Post-trade caps hold under every synthetic sequence. Legacy mode reproduces slot exposure. |
| PR-C10 | Correlated-cluster exposure on the chosen source | Strategy-version-changing correction | R7 | PR-OD11, PR-OD12 | PR-T14 | Unknown or NaN beta follows the fail-closed rule. The mapping and window are versioned in the budget hash. |
| PR-C11 | Reservation of capital for working entry intents, with release on fill, reject or expiry (PR-12) | Strategy-version-changing correction | R7 [R6] | PR-C02, PR-OD17 | PR-T03, PR-T05 | `reserved` equals the active intents. A working order can no longer exceed available cash or capacity. |
| PR-C12 | A daily `E_mtm` snapshot series (UTC) for the governed endpoint, computed from the shadow ledger | Safe development-only correction (default-off, no runtime effect) | R7 [R8] | PR-C05, PR-OD6, WP3 endpoint decision | PR-T16, PR-T19 | One value per UTC day, or `UNKNOWN`. Reproducible from the entry log and marks. |
| PR-C13 | Drawdown from the chosen high-water mark, de-risking ladder on size, period-loss windows, recovery-epoch handling | Strategy-version-changing correction | R7 | PR-C07, PR-OD18, PR-OD20, PR-OD21, PR-OD22 | PR-T12 | Ladder monotonicity holds. Recovery follows the chosen rule. The epoch handling is explicit and recorded as an event. |
| PR-C14 | Net-labelled counters next to legacy gross counters, with the basis and cost model in every report field (CON-09, PR-15) | Safe development-only correction (default-off, no runtime effect) | R7 | — | PR-T17 | Every counter names its basis. Legacy gross columns are unchanged and labelled. |
| PR-C15 | Shadow valuation under the research cost models (0.40% and 0.60%) from the same events, never booked into the Paper ledger | Protected research or simulation | R7 [R4, R8] | PR-C02; permission under OD-DF-1 for any protected data | PR-T15 on synthetic events only | Runs only after authorization. Results are reported as research, not as Paper accounting. |
| PR-C16 | Activation on Paper runtime of any of PR-C05 to PR-C14 (flag change, migration apply, image deploy) | Production/runtime change | R7 [R9] | Owner approval, version boundary record, deployment gate | Post-deploy reconciliation (PR-I13) | Approved per item. Rollback defined. No live allocation change (charter §4 R7). |

## 8. Deterministic tests (synthetic events only)

Every test uses generated or hand-written synthetic events and fixtures, with fixed seeds. None reads production, holdout or protected data, and none needs the network. Property-based tests run as deterministic seeded generators. The suite runs under the local CI-equivalent; this document runs nothing.

| ID | Test | Asserts |
|---|---|---|
| PR-T01 | **Invariant property test.** Random valid sequences of `GENESIS`, `RESERVE`, `RELEASE`, `ENTRY_FILL` (full and partial), `EXIT_FILL` (1–3 legs) and `MARK` | PR-I1 to PR-I6 and PR-I14 hold exactly after **every** transition. Invalid events (overdraw, over-exit, naive time) are refused with a named reason and leave the state unchanged. |
| PR-T02 | **Idempotency.** Each event of a sequence is applied 1–3 times, in random duplicate positions | The final state and hash equal the single-application result. Duplicates are recorded as no-ops. The same `event_id` with a different payload raises `ledger_event_conflict` (PR-I7). |
| PR-T03 | **Replay determinism.** Fold the entry log from empty and compare it with the incrementally maintained state | The states and `state_hash` are identical, and the hash chain verifies (PR-I8). |
| PR-T04 | **Crash and restart.** Truncate the log at every prefix, then re-apply the full event stream | Exactly-once outcome. No reservation, fee or leg is lost or doubled. |
| PR-T05 | **No double booking on legs.** 25/50/25 exits with merged sub-minimum tranches | Σ leg quantities = filled quantity. Fees are charged per leg on the leg notional (research model) or once at close (legacy model), never both (PR-I11). |
| PR-T06 | **Unrealized never capital.** Hold the realized events fixed and vary the mark paths arbitrarily | `cash_free` and `B` under rule (a) are invariant. Under rule (b), `B ≤ E_cost` always, and `B` never rises above `E_cost` on a mark increase (PR-I9, PR-I10). |
| PR-T07 | **Compounding from realized net only.** Sequences of net wins and losses under S1–S4 and caps C-1 to C-3 | A gain raises `B` only at its settlement point and only by its net amount (after all fees). A loss lowers `B` at the close. The caps are never exceeded. External deposits never change performance-adjusted `B`. |
| PR-T08 | **Stale or missing mark fails closed.** Marks older than the bound, missing, NaN, ∞ or ≤ 0 | Admission is refused with `mark_stale` or `invalid_risk_state`. No NaN reaches the ledger. Exits are not blocked. |
| PR-T09 | **Legacy parity (golden fixtures).** Synthetic `RiskSnapshot` and `RiskLimits` grids through legacy mode | `legacy_fields` are byte-identical to `evaluate_new_trade` at `bb7825f` (`shared/economic_halt_policy.py:L137-L142 @ bb7825f` defines the comparison). The hash of `shared/risk_management.py` is unchanged. |
| PR-T10 | **Partial-exit-aware unrealized.** A position after T1 and T2 legs, with prices above and below the target | The ledger's unrealized P&L marks only `qty_open`. The legacy formula's divergence equals the PR-07 expression exactly. |
| PR-T11 | **Quantization and step size.** Random step sizes, min notionals and prices | The size is rounded down, never above the budget. Below minimum gives `below_min_notional`. The residual stays in `cash_free`. |
| PR-T12 | **Ladder monotonicity and recovery.** DD, streak and period-loss grids for L-1 to L-4 | The multiplier is non-increasing in each trigger. The recovery rule is applied as specified. Hysteresis prevents oscillation on a boundary-straddling path. |
| PR-T13 | **Exposure caps post-trade.** Sequences that approach each cap, at cost and at mark | No admission leaves a cap breached. Rejections name the cap. Reserved intents count. |
| PR-T14 | **Correlation fallback.** Betas that are unknown, NaN, negative, or computed from fewer observations than required | The documented conservative rule is applied, NaN is refused, and the decision records the source version. |
| PR-T15 | **Cost-model separation.** One synthetic event stream folded under legacy, baseline and stress models | Three consistent ledgers. Stop slippage appears once per model (R4). The ledgers differ only by the declared cost terms. |
| PR-T16 | **UTC windows.** Events straddling UTC day and week boundaries, plus inputs with non-UTC offsets | Day and week attribution is by UTC. Naive timestamps are refused. The daily `E_mtm` series has one value per UTC day, or `UNKNOWN`. |
| PR-T17 | **Counter basis.** Trades with 0 < gross < cost, gross = cost, and gross < 0 | Gross counters, net counters and the streak are each labelled and consistent with `shared/fees.py:L44-L60 @ bb7825f`. CON-09 combinations are reproduced and labelled. |
| PR-T18 | **Migration safety (disposable database only).** Apply twice, roll back application code, then insert a duplicate `event_id` | Idempotent. Pre-change code is unaffected. The unique constraint rejects the duplicate. |
| PR-T19 | **Shadow non-interference.** The tracker admission path on fixtures, with the shadow writer off and on | Admission decisions, `trade_results` rows and outbox events are identical. Only ledger rows are added. |
| PR-T20 | **SizingDecision determinism.** The same inputs in a different process order or with a different dict ordering | Identical `SizingDecision` and `DecisionRecord` hashes. The binding constraint is named. |

## 9. Acceptance criteria and closure proof for R7

R7 can be marked FIXED in [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md) only when all of the following hold:

1. Every §6 decision is recorded with date and approver in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md), or explicitly deferred.
2. PR-C02 to PR-C05 are merged by the owner's integration route with PR-T01 to PR-T11 and PR-T15 to PR-T20 green. No self-approval.
3. After an authorized activation (PR-C16), shadow reconciliation (PR-I13) holds for every close over a declared observation period, with zero unexplained mismatches. Each explained mismatch traces to PR-06, PR-07 or PR-17.
4. Any decision-changing change (PR-C06 to PR-C11, PR-C13) is introduced only at a declared `StrategyVersion` boundary with a new contract hash, never inside a governed window.
5. The closure proof cites commits, test runs and reconciliation evidence by reference.

None of these criteria is a profitability criterion. Closing R7 establishes measurability, not an edge.

## 10. NOT VERIFIED items and blockers

| Item | Blocker |
|---|---|
| The running trade_tracker and telegram images execute the cited `bb7825f` source, including the observe path (RT-33) | Image filesystem access not authorized |
| The database session time zone is UTC, so the Python UTC day, naive `exit_time` and `CURRENT_DATE` agree (PR-23) | Database access out of scope |
| Realized magnitude of the PR-07 unrealized mis-mark, the PR-09 period attribution and PR-16 (R4) on past Paper decisions | Needs production data. Protected; permission required. |
| Whether any recovery epoch has been recorded, and whether the owner intended it to re-base drawdown (PR-10) | Database access out of scope; no recorded decision found in governance documents |
| Whether a second tracker process or writer ever existed, which would affect PR-19 | Runtime process history not in scope |
| The effective minimum-notional source per symbol (exchange filter or the fallback 5) for past admissions (PR-18) | Runtime logs out of scope |

## 11. Deviation check

**No DEVIATION ALERT is raised.** The checks against charter §7.7:

- **Objective.** Unchanged. Compounding is only from realized net profit, and losses reduce size (§4.3, §4.6).
- **Transferring results.** None. No result from another strategy is cited as evidence for or against any sizing method.
- **Unregistered tuning.** None. No parameter is chosen, and every value is in §6.
- **Forced trades and BTC-only.** No forced trades: an unused budget never triggers admission. No BTC-only scope. A BTC beta, if chosen, is a risk input only.
- **Unrealized gains as cash.** Prevented by PR-I9 and PR-I10. Option (x) is excluded in §4.3.
- **A29.** Not bypassed. Sizing policy is part of the version contract, and the endpoint stays with WP3 (§4.7).

**Two governance tensions in the existing implementation are reported as findings, not deviations:**

- **PR-10.** A recovery epoch re-bases drawdown, read against `docs/governance/OWNER_OPERATING_CONTRACT.md:L25 @ 46578aa`. It is routed to PR-OD18.
- **PR-15.** Mixed gross and net counters (CON-09). It is routed to PR-C14.

## 12. Cross-references

- [BASELINE_AND_EVIDENCE.md](BASELINE_AND_EVIDENCE.md): commit baseline and runtime-identity confidence used in §0.
- [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md): R7 status, its sub-items, and the R4 dependency.
- [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md): `Opportunity.risk_plan`, capacity rejections and `RejectionRecord` reason codes consumed by §4.4 and §5; its stage F7 hands each ranked `Opportunity` to the `RiskBudget` and `SizingDecision` defined here, including minimum-order feasibility (§4.4, constraint stages 8–9).
- [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md): stop and target geometry (R2), fills, the cost model and the stop-slippage correction (R4), on which `s`, `risk_at_stop` and per-leg costs depend.
- [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md): branch sequencing of PR-C02 to PR-C16.
- [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md): records for PR-OD1 to PR-OD22, WP3 endpoint and slot decisions.
- Governance: [charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md), [owner operating contract](../../governance/OWNER_OPERATING_CONTRACT.md), [development-first policy](../../governance/DEVELOPMENT_FIRST_POLICY.md), [evidence ladder parameters](../../strategy/EVIDENCE_LADDER_PARAMETERS.md).
