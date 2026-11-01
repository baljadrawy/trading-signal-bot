# Side-by-side cost reporting (WP-E09) and counter basis (WP-E06)

> **Status: SPECIFICATION FOR OWNER REVIEW.** WP-E09 is Documentation/design. Its optional pure function, `side_by_side_report`, runs on synthetic trades only and no service calls it. WP-E06 is integrated into `trade_tracker/main.py` and `telegram/main.py` behind `PAPER_COUNTER_LABELS`, default `off`. At that default every message, log line and database call is byte-identical to `6ae70a2`. Nothing here is deployed or activated, and nothing here is a profitability claim.

## Document control

| Field | Value |
|---|---|
| Tasks | WP-E09 and WP-E06 in [IMPLEMENTATION_WORKPLAN.md](remediation-design-pack-20261101/IMPLEMENTATION_WORKPLAN.md) §4.5 |
| Remediation items | R4.c, R4.d and R7.f in [REMEDIATION_REGISTER.md](remediation-design-pack-20261101/REMEDIATION_REGISTER.md); PR-15, PR-C14 and PR-T17 in [PORTFOLIO_RISK_AND_COMPOUNDING.md](remediation-design-pack-20261101/PORTFOLIO_RISK_AND_COMPOUNDING.md); CON-09 |
| Owner question | OQ-08 / DG-37 in [DECISIONS_AND_GATES.md](remediation-design-pack-20261101/DECISIONS_AND_GATES.md): keep the flat 0.30%, or adopt 0.40% / 0.60% |
| Rule it implements | "Cost baseline 0.10 %/side, spread and slippage separate, tracker 0.30 % reported separately" (`docs/governance/DEVELOPMENT_FIRST_POLICY.md:L61 @ 6ae70a2`, DFP:L61) |
| Code | `shared/cost_label_policy.py` (`COUNTER_BASES`, `net_counter_strata`, `side_by_side_report`); `shared/cost_models.py` (the three models, unchanged) |
| Tests | [tests/test_counter_basis.py](../../tests/test_counter_basis.py) and [tests/test_cost_reporting_side_by_side.py](../../tests/test_cost_reporting_side_by_side.py): synthetic, no database, network or container |
| Branch | `feature/wp2-foundation-20261101`. Service sources are cited at `6ae70a2`, the commit before this change |

### Anti-drift statement (charter §7)

1. **Goal alignment.** Net economics is the objective (`docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md:L25 @ 6ae70a2`). A figure whose basis is unnamed cannot be read as net. This work names the basis; it changes no cost.
2. **Evidence classes** follow charter §7.4. Source claims are SOURCE_VERIFIED at `6ae70a2`. The research figures are DOCUMENTED_ONLY (proposed). Every output of `side_by_side_report` is synthetic evidence.
3. **Permission class.** Source integration behind a default-off flag, a pure function and synthetic tests. No database, service, network or protected data was touched.
4. **DEVIATION ALERT.** None.

## 1. Rules

1. **Every reported net figure names its `cost_model_id` and its `label_policy`.** A gross figure is tagged `gross_before_cost` and names neither. A plain count names neither.
2. **The runtime and research models are never pooled.** The runtime `legacy_tracker_v1` (0.30%) and the PROPOSED `research_baseline_v1` (0.40%) and `research_stress_v1` (0.60%) are reported in separate columns. No line, total or average combines two columns (DFP:L61; SE-45; `shared/cost_models.py` `aggregate` refuses a mix).
3. **Net counters are never pooled across label policies.** Rows booked under `net_after_modeled_cost_v1` and under `net_single_count_legacy_v1` are counted in separate strata (R4 test 4). `require_single_label_policy` refuses to report two policies as one figure.
4. **The research models are proposals.** Their status is `PROPOSED_NOT_ADOPTED`, and their `label_policy` is `UNSPECIFIED` in the registry: naming one is part of OQ-08 and SE-81. The report shows that value as it is and does not invent a name.
5. **Synthetic only.** A research-model view of Paper trades admitted after the freeze would read FORWARD_HOLDOUT outcomes; it is forbidden without an OD-7 unlock (STRATEGY_AND_EXECUTION_CONTRACT.md §C4, DOCUMENTED_ONLY). On recorded trades it is PR-C15, protected research. `side_by_side_report` refuses any `evidence_class` other than `synthetic`.
6. **History is never rewritten.** No stored column, counter or label changes. A research model is never retrofitted onto stored Paper rows (§C4).

## 2. The three cost models

| `cost_model_id` | Round trip | Booking | Status | Source |
|---|---|---|---|---|
| `legacy_tracker_v1` | 0.3% flat on the configured notional, once per trade, plus `STOP_SLIPPAGE` 0.001 inside every stop fill | flat per trade plus stop fill in price; slippage is a declared double count (R4) | `LEGACY_RUNTIME_RULE`; the runtime values 0.3 and 0.001 are RUNTIME_VERIFIED (VER-19) | `shared/cost_models.py`, `shared/fees.py:L20-24, L52-60 @ 6ae70a2` (SOURCE_VERIFIED) |
| `research_baseline_v1` | 0.40% all-in: 0.10% fee per side on each leg's executed notional, plus 0.10% spread and slippage per side inside the price of taker legs | per leg | `PROPOSED_NOT_ADOPTED` | `CH:L25` (DOCUMENTED_ONLY, proposed); SE-44 to SE-46 |
| `research_stress_v1` | 0.60% all-in: the same fee, plus 0.20% spread and slippage per side | per leg | `PROPOSED_NOT_ADOPTED` | `CH:L25` (DOCUMENTED_ONLY, proposed) |

The split between spread and slippage inside the research figures is UNSPECIFIED (SE-81). These numbers are reproduced from their sources; none is chosen here.

## 3. Basis vocabulary (WP-E06)

| Tag | Meaning |
|---|---|
| `gross_before_cost` | the sign or sum of the stored gross `profit_usdt`, with no cost. For a stop exit this gross already contains one stop slippage (PR-16) |
| `net_stored` | the economic fields stored on the row (`cost_usdt`, `net_profit_usdt`, `economic_result`) under the row's own `label_policy` (A38) |
| `net_stored_else_recomputed` | the stored `economic_result` when present, otherwise derived at read time from the stored gross and the current flat cost (`shared/fees.py:L63-74 @ 6ae70a2`, `economic_result_sql`) |
| `net_recomputed_flat` | stored gross minus the flat cost of the current configuration, recomputed at read time. It ignores the stored `label_policy` |
| `count_no_pnl_basis` | a count with no P&L meaning |

A rendered tag is `[basis · cost_model_id · label_policy]`, for example `[net_recomputed_flat · legacy_tracker_v1 · net_after_modeled_cost_v1]`. `per_row_label_policy` means each counted row names its own policy, so the figure can pool policies. That is why the stratified net counters (§4) are shown beside it.

## 4. Current surfaces and their basis (CON-09)

SOURCE_VERIFIED at `6ae70a2`; registered in `COUNTER_BASES`.

| Surface | Figure | Basis | `label_policy` | Location |
|---|---|---|---|---|
| tracker: `trade_results.result` | WIN when gross > 0 | gross | — | `trade_tracker/main.py:L1525 @ 6ae70a2` |
| tracker: economic fields | `economic_result` and net | net_stored | per row | `trade_tracker/main.py:L1502-1528 @ 6ae70a2` |
| tracker: `risk_management.wins` / `losses` | +1 by gross sign | gross | — | `trade_tracker/main.py:L1532-1540 @ 6ae70a2` |
| tracker: `daily_pnl_percent`, loss streak | net, including unrealized P&L | net_recomputed_flat | `net_after_modeled_cost_v1` | `trade_tracker/main.py:L1086-1104, L1209-1222 @ 6ae70a2` |
| tracker: `trade.closed` evidence | `result_label` gross, `net_profit_usdt` recomputed | gross; net_recomputed_flat | — ; legacy | `trade_tracker/main.py:L446-447 @ 6ae70a2` |
| telegram `/status` | closes won / lost today | gross | — | `telegram/main.py:L790-791 @ 6ae70a2` |
| telegram `/stats` | wins, losses, breakeven | net_stored_else_recomputed | per row (pooled) | `telegram/main.py:L960-966, L981-983 @ 6ae70a2` |
| telegram `/stats` | legacy gross split | gross | — | `telegram/main.py:L967-968, L984-985 @ 6ae70a2` |
| telegram `/stats` | average net %, total net USDT | net_recomputed_flat | legacy | `telegram/main.py:L975-977, L986-987 @ 6ae70a2` |
| telegram `/trades` | per-trade net | net_recomputed_flat | legacy | `telegram/main.py:L1022-1032 @ 6ae70a2` |
| telegram `/performance` | wins, losses, win rate | net_stored_else_recomputed | per row (pooled) | `telegram/main.py:L1136-1146 @ 6ae70a2` |
| telegram `/daily` | wins / losses | gross | — | `telegram/main.py:L1244-1245, L1264 @ 6ae70a2` |
| telegram `/daily` | net after cost | net_recomputed_flat | legacy | `telegram/main.py:L1218-1224, L1265 @ 6ae70a2` |
| closed notification | gross line, net line | gross; net_recomputed_flat | — ; legacy | `shared/telegram_messages.py:L120-148 @ 6ae70a2` |

So a trade with 0 < gross < cost is a gross win in `/status` and `/daily`, an economic loss in `/stats` and a streak loss in the risk guard (PR-15). Under `net_single_count_legacy_v1` the stored net and the recomputed net also differ, and `/stats` pools both policies.

## 5. What `PAPER_COUNTER_LABELS=on` changes

- **telegram:** every figure in §4 carries its tag. `/status`, `/stats` and `/daily` add one net-counter line per `label_policy` beside the legacy counters, from one extra read (`net_counter_sql`): `trade_results` grouped by `label_policy` and economic label. The closed notification adds its basis lines and the row's stored net with its own policy. Nothing is written.
- **tracker:** each recorded close logs one line: the legacy gross increment with its tag and, beside it, the net label stored on the same row. Database writes and outbox events are unchanged.
- **Removing the tags and the added lines gives back the legacy text exactly.** The tests check this property for every report.
- An empty or unknown value refuses to start both services (fail-closed).

No net column is added. The net counters are counted from the economic fields every row already stores. A stored per-day net counter would be a new column in the WP-E03 migration and its release under WP-G08 or WP-G28.

## 6. The side-by-side report (WP-E09)

`side_by_side_report(trades, *, legacy, evidence_class)`:

- **Input.** `trades` maps a position id to its `shared.cost_models.Leg` list. `legacy` is a bound `legacy_tracker_v1`; its values (fee, slippage, configured notional) are required inputs with no default. `evidence_class` must be `synthetic`.
- **Booking.** Each trade is booked once under each model through `CostBook`, which refuses a double booking of any leg.
- **Output.** A `gross` block tagged `gross_before_cost`, plus one column per `cost_model_id`. Each column carries its `label_policy`, `model_status`, `round_trip_pct` and `content_hash`; its fees, explicit and in-price costs and net; its net win, loss and breakeven counts; and its per-trade figures. There is no cross-column total. `pooled` is `false` and `not_profitability_evidence` is `true`.
- **Gross.** The report's gross is the reference gross (Σ sell q·ref − Σ buy q·ref), the same in every column. It differs from the tracker's stored gross on a stop exit, which already contains one stop slippage.

Worked synthetic example (`tests/test_cost_reporting_side_by_side.py`; quantity 1 at entry 100, configured notional 100). This is synthetic evidence, not a result:

| Trade | Gross | `legacy_tracker_v1` net | `research_baseline_v1` net | `research_stress_v1` net |
|---|---|---|---|---|
| stop exit at 97 | −3 | −3.397 | −3.394003 | −3.591006 |
| two maker targets, 102 and 104 | +3 | +2.70 | +2.696900 | +2.596800 |
| time exit at 100.2 | +0.2 | −0.10 | −0.2003998 | −0.4005996 |

The legacy stop row shows the R4 double count: slippage inside the fill and again inside the flat 0.3%. The last row is CON-09: a gross win that is a net loss under every model.

## 7. Gates

| Step | Gate |
|---|---|
| Turn `PAPER_COUNTER_LABELS` on in Paper | The R4 gates WP-G07 and WP-G08, then owner Class B approval for each service under COMPOSE_OPERATIONS.md. The flag changes report text and adds one read; it changes no decision or stored value |
| Store a net counter column | The WP-E03 migration, released under WP-G08 (R4.f) or WP-G28 |
| Book a research model in Paper accounting | OQ-08 / DG-37, WP-G07: a strategy-version and measurement boundary (SE-68) |
| Run the side-by-side report on recorded Paper trades | PR-C15 protected research: OD-DF-1, and OD-7 for any trade after the freeze |
| Name a research `label_policy` | OQ-08, SE-81 |

## 8. Open questions for the owner

1. OQ-08: which model the Paper ledger books. Until then, reports keep the legacy model and show the research models only beside it, on synthetic trades.
2. The `label_policy` names of the two research models.
3. Whether `/stats` and `/performance` should keep pooling label policies once a second policy is active, or show only the stratified counters. That change would alter visible text, so it needs its own flag and approval.
