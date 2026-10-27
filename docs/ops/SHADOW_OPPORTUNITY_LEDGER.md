# Shadow Opportunity Ledger

**Status:** design + pure implementation, synthetic tests only. **Not wired** into any runtime
service, no schema change, no admission decision changed. Activation needs separate
operational approval (see *Wiring plan*). Module: `shared/shadow_opportunity.py`; tests:
`tests/test_shadow_opportunity.py`.

## Purpose

Paper runs with a canary capacity of 2 concurrent positions, and 1 while any sizing multiplier
of 0.5 or less applies (`docs/ops/PAPER_ECONOMIC_OBSERVATION.md`, *Collection capacity in
observe mode*). One long-held position can take the only slot, and every candidate in the
meantime is refused. The ledger records **what capacity blocked**, so that question can be
measured rather than guessed.

A shadow opportunity is **never a trade**. It is never executed, never entered into the Paper
trade store, and **never counted as Paper performance**: no P&L, win rate, Profit Factor,
drawdown, loss streak or risk state.

## What is recorded, and what is not

Recorded only when a candidate passed every strategy/technical check and was refused **only** by
a Paper portfolio limit:

| Layer | Qualifying refusal codes | `refusal_class` |
|---|---|---|
| `telegram_delivery` (`telegram/main.py` `can_deliver_candidate`) | `portfolio_capacity_<n>/<cap>` with `n >= cap > 0` | `delivery_portfolio_capacity` |
| `tracker_admission` (`shared/risk_management.evaluate_new_trade`) | `max_open_trades`, and a sizing label used as the capacity-block reason (`drawdown_*`, `weekly_reduce/minimum`, `loss_streak_reduce/minimum`) | `max_open_trades` |
| `tracker_admission` | `gross_exposure_limit`, `symbol_concentration_limit`, `strategy_concentration_limit`, `regime_concentration_limit` | same as the code |

**Never recorded** (they stay real stops; `build_opportunity` raises `NotAnOpportunityError`):
economic halts (`daily_loss_limit`, `weekly_loss_limit`, `max_drawdown_limit`,
`loss_streak_halt`) whether enforced or not, technical halts (`invalid_risk_state`),
administrative stops (`manual_pause`, `trading_paused`, `risk_state_*`, `risk:<x>`,
free-text pauses), `observed:<x>` reasons (those trades were admitted), and anything else.
Classification reuses `shared.economic_halt_policy.classify_reason`, so it cannot drift from
the tracker.

## Labelling rules

- Opportunity row: `record_kind="shadow_opportunity"`, `executed=false`, `is_executed_trade=false`.
- Outcome row: `record_kind="shadow_outcome"`, `executed=false`, `is_executed_trade=false`.
- Every row has `schema_version=shadow-opp-v1`. Opportunity rows also carry the signal id,
  candidate id, symbol, trade type, timeframe, strategy version, `risk_policy_version`, refusal
  code/layer/class, `decision_ms` (data, ms) and `decision_minute_utc` (minute precision), the
  planned entry/stop/targets **as given**, and `cost_model_version` plus the full cost model.
- `opportunity_id` = SHA-256 of (signal id, candidate id, layer, decision ms). A duplicate is refused.
- Storage is append-only JSONL with a SHA-256 hash chain (`seq`, `prev_hash`, `body`,
  `entry_hash`; genesis is 64 zeros). `verify()` re-checks the chain **and** the labels of every
  row. An edit, deletion, reorder or relabel (for example `executed=true`) raises
  `LedgerTamperError`.
- The file name must start with `shadow_opportunity`, end with `.jsonl` and must not contain
  `trade`. The default is `shadow_opportunity_ledger.jsonl`. The evidence stream name reserved
  for wiring is `paper.shadow_opportunity.v1`.
- The reading API returns only `opportunities()` and `outcomes()`. `trades()` raises
  `NotATradeError`. `assert_not_shadow(row)` is the guard any executed-trade consumer can apply.

## Outcome model

`resolve_outcome(record, path, bar_timeframe=...)` replays a later price path. The path is
`(t, high, low, close)` or `(t, open, high, low, close)` and must start at or after the decision.

- Supported trade types (`momentum`, `reversion`) reuse the frozen A42 bar replay,
  `shared.counterfactual_barrier.replay_bracket` (`outcome_model="a42-cf-bar-v1"`). It applies
  the same entry rules (`decide_long_entry`), the triple barrier, partial exits, break-even
  moves and per-timeframe expiry as Paper. The approximations it declares (bars, not polls;
  stop checked before targets; a limit fills only on a strict trade-through; a gap fills at the
  open) are conservative compared with the poll-based tracker (A47/A48).
- Any other trade type uses `outcome_model="approx"`: fill at the planned entry, stop checked
  before target_1, a full exit at target_1, a stop fill at `min(stop, open) x (1 - stop
  slippage)`, no partials and no expiry.
- If the path has no open column, `open_source="prev_close"` (the previous close, clamped to the
  bar's range).
- Costs come from `shared.signal_quality.CostModel`: 0.10 %/side fee (0.20 % round trip), plus
  declared entry/exit slippage, plus the observed spread when `include_spread` is set (the
  spread is then required, never assumed). Stop fills also take a 0.1 % stop slippage. A test
  pins the round trip equal to `research/mechanisms/costs.CostModel`. `research/` itself is not
  imported, because it is not part of the runtime image.

## Analysis guidance

- **Selection effects.** Blocked signals are **not a random sample**. They cluster in time
  (while a position is open, often during drawdown or a loss streak when capacity is 1), in
  regimes and in symbols (concentration limits). Their outcomes are also correlated with the
  open position that blocked them. Never treat them as an unbiased estimate of strategy edge,
  and never treat them as what Paper "would have earned".
- **Always report separately.** `aggregate(shadow_outcomes, executed_trades)` returns `shadow`
  and `executed` side by side, with `pooled: null`. Mixed inputs raise `MixedPopulationError`,
  and `merge_populations` always raises.
- Report counts by status (`not_filled`, `rejected`, `open_at_end`) and by `outcome_model`.
  Report `approx` outcomes apart from replay outcomes.
- Shadow results may inform an **owner capacity/sizing decision**. Under the A29 evidence
  ladder they are not confirmatory evidence for a strategy claim.

## Wiring plan (later; needs explicit operational approval)

1. **Tracker hook.** This is the primary source. Put it in `trade_tracker/main.py` right after the
   risk admission decision (`evaluate_with_policy` result) when `allowed` is false and
   `classify_capacity_refusal(reason, "tracker_admission")` succeeds. It runs after the
   decision, is fire-and-forget, and its exceptions are swallowed and counted (the
   `evidence_v2.hook_error` pattern), so it can never change admission.
2. **Delivery hook.** Put it in `telegram/main.py` where `can_deliver_candidate` returns
   `portfolio_capacity_<n>/<cap>`, with layer `telegram_delivery`. Deduplicate against the
   tracker layer by `candidate_id` during analysis, not at write time.
3. **Sink.** Either an evidence-v2 stream `paper.shadow_opportunity.v1` or a dedicated
   `shadow_opportunity_ledger.jsonl` on a volume separate from Paper data. No DB table and no
   schema change in the first step.
4. **Outcome resolution.** Run it offline or in a research job over closed bars after expiry.
   Never run it in the tracker loop.
5. **Isolation.** The module is registered in `tests/experimental_modules.py` because its
   outcome resolver imports the experimental A42 replay. Before wiring, split the
   record-building and ledger part (dependencies: `economic_halt_policy` and `evidence_v2`
   only) into a wired module. The resolver stays experimental and runs offline.
6. **Approvals.** Owner operational approval for the deploy (a runtime change on the shared
   host), a backup/rollback plan for the new file, and a review of the hook diff showing that
   no admission branch changed.
