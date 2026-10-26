# Paper economic-loss observation (`PAPER_ECONOMIC_HALT_MODE`)

Status: **implemented and tested in isolation, default OFF (`enforce`)**. Merging this code
changes no runtime behaviour. Activation is a separate, owner-authorized operation.

## Decision reference

- Owner decision 2026-10-26, *Paper economic-loss observation*
  (`docs/governance/DEVELOPMENT_FIRST_POLICY.md`, header block) and
  `docs/governance/OWNER_OPERATING_CONTRACT.md` section 3: during R&D, negative P&L, loss
  streaks, drawdown or low PF are **observations**, not automatic reasons to stop simulated
  Paper collection; technical/administrative safeguards stay fail-closed; history and
  counters are never reset or rewritten; changes need isolated PAPER_ONLY implementation,
  tests and an explicit strategy-version (prospective-window) boundary.
- The decision authorizes development only. It does **not** authorize `/resume`, clearing an
  existing halt or pause, live deployment/restart, learner activation or real money.

## Where it lives

| Piece | File |
|---|---|
| Classification + mode resolution + policy wrapper (single source of truth) | `shared/economic_halt_policy.py` |
| Setting (`PAPER_ECONOMIC_HALT_MODE`) and derived `ECONOMIC_HALT_MODE` / `RISK_POLICY_VERSION` | `shared/config.py` |
| Admission, locked re-check, pause persistence, evidence | `trade_tracker/main.py` |
| Operator state `LOSS_STREAK_OBSERVED` | `shared/risk_epoch.py` (`operational_state`) |
| `/status`, `/resume` texts | `shared/telegram_messages.py`, `telegram/main.py` |
| Alert delivery (`risk.observed` outbox notice) | `trade_tracker/main.py` (`_enqueue_observation_alert`), `shared/telegram_messages.py`, `telegram/main.py` |
| Tests | `tests/test_paper_economic_observation.py`, `tests/test_paper_economic_alerts.py`, `tests/test_paper_observe_capacity.py` |

`shared/risk_management.py` (`evaluate_new_trade`) is **byte-identical**: its hash is pinned in
`research/governance/contracts/*`, and it remains the only implementation of the risk
arithmetic. The policy module wraps it.

## Classification

| Class | Reasons | enforce | Paper observe |
|---|---|---|---|
| Economic hard stop | `daily_loss_limit`, `weekly_loss_limit`, `max_drawdown_limit`, `loss_streak_halt` | blocks + persists pause (`risk:<reason>`) + `risk.halted` outbox | **does not block**; recorded as observation; no pause row, no `risk.halted`; one `risk.observed` notice per transition |
| Technical hard stop | `invalid_risk_state` (any non-finite/invalid input, e.g. missing price) | blocks + persists pause | blocks + persists pause (unchanged) |
| Administrative / state integrity | any persisted pause: `manual_pause`, `trading_paused`, `risk_state_missing`, `risk_state_inconsistent`, `risk:<x>` rows, operator reasons | blocks | blocks (unchanged) |
| Portfolio construction | `gross_exposure_limit`, `symbol_concentration_limit`, `strategy_concentration_limit`, `regime_concentration_limit`, `max_open_trades` | blocks | blocks (unchanged) |
| Sizing | `drawdown_caution/warning`, `weekly_reduce/minimum`, `loss_streak_reduce/minimum` | multiplier + capacity | **unchanged** (multiplier + capacity) |

Sizing is sizing, not stopping, and is deliberately unchanged in both modes. Note that the
multiplier still lowers `max_positions`, so in observe mode a deep loss streak (>= 5) limits
capacity to one open position (the capacity block is labelled with the sizing reason, e.g.
`loss_streak_minimum`, exactly as today). With the runtime canary capacity of 2 this throttles
collection to one open position; see *Collection capacity in observe mode*.

## Behaviour per mode

**enforce (default).** Every legacy `RiskDecision` field is identical to the pre-change code
(tested on a 22-scenario table). Additive labels only: `economic_flags` (every breached
economic hard limit, legacy precedence order), `observed_economic_stop=None`,
`risk_policy_version="econ-enforce-v1"`. `record_risk_decision` persists the legacy set
(economic + `invalid_risk_state`). The locked loss-streak re-check blocks as before.

**observe (Paper only).** `evaluate_new_trade` runs unchanged. If, and only if, the binding
legacy stop is economic, the decision is re-derived with the four economic hard thresholds made
unreachable (sizing thresholds untouched):

- no other stop applies: `allowed=True`, `reason="observed:<stop>"`;
- a technical/admin/portfolio stop applies: blocked with that reason;
- always: `observed_economic_stop=<stop>`, `economic_flags`, `risk_policy_version="econ-observe-v1"`.

`record_risk_decision` still writes `daily_pnl_percent` and `consecutive_losses` to today's
`risk_management` row exactly as now, but only `invalid_risk_state` sets
`is_trading_paused=true`. The economic state is recorded as an append-only evidence event
`risk.observed` (emitted on change of observed state), as a tracker log warning, and as one
operator notification per transition (`risk.observed` outbox event, see *Alert delivery* below). The locked re-check
(`_loss_streak_under_lock`) does not block; an admitted trade's `admission.decision` carries
`observed_under_admission_lock: "loss_streak_halt"`.

`/status` shows `LOSS_STREAK_OBSERVED` with "observed (Paper observe mode, not blocking)"
instead of "halt active" (an administrative pause still shows as paused and outranks it);
`/resume` reports the streak the same way. `/recover_risk` is unchanged.

**Mode resolution.** `observe` is honoured only when `PAPER_TRADING` is true. `observe` without
Paper, or any unknown value, resolves to `enforce` with a one-time warning (the restrictive
direction). Research runners (`research/p0r.py`, `research/foundation/runner.py`) call
`evaluate_new_trade` directly and are unaffected by the flag.

## Collection capacity in observe mode

Runtime configuration (container env, non-secret, as read for owner item 3):
`RISK_CANARY_MAX_OPEN_TRADES=2`, `MAX_OPEN_TRADES` unset (default 10), `TRADE_AMOUNT_USDT=50`,
`RISK_CAPITAL_USDT=500`, `MAX_GROSS_EXPOSURE_PERCENT=80`, `MAX_SYMBOL_EXPOSURE_PERCENT=10`,
`STOP_ON_CONSECUTIVE_LOSSES=7`.

- Trade notional is always `TRADE_AMOUNT_USDT`: the tracker never reads `size_multiplier`, so a
  minimum-notional floor cannot turn sizing into a stop.
- `base_max = min(min(MAX_OPEN_TRADES, CANARY) = 2, floor(500 * 0.8 / 50) = 8) = 2`;
  `effective_max = max(1, floor(base_max * multiplier))`, so capacity is 2 at multiplier 1.0 and
  **1** at any multiplier <= 0.5 (drawdown caution/warning, weekly reduce/minimum, loss streak
  reduce/minimum). It is never below 1.

Regression tests (`tests/test_paper_observe_capacity.py`, limits built by the tracker itself from
this configuration; a 160-state grid spanning every economic hard stop and every sizing label):

| Book | Result in observe mode |
|---|---|
| flat (`open_count=0`), any economic stop and any multiplier | **admitted**; capacity 1 or 2, never 0 -- collection never stops |
| one open position on another symbol, multiplier <= 0.5 | blocked by a sizing-labelled capacity block (`drawdown_*`, `weekly_*`, `loss_streak_*`; the `max_open_trades` class) -- **throttling 2 -> 1, not stopping** |
| one open position on another symbol, multiplier 1.0 | admitted (capacity 2) |
| two open positions | blocked (capacity 2) |
| one open position on the **same** symbol | blocked `symbol_concentration_limit` (10% cap = exactly one 50 USDT position per symbol) |

A long-held position can occupy the only slot while a multiplier <= 0.5 applies (for example a
loss streak of 5 or more), so collection then waits for that position to close. That is a
portfolio-capacity question for the owner (canary capacity / sizing policy); it is deliberately
not changed here, and it behaves identically in enforce mode.

## Alert delivery (observe mode only)

Owner contract section 3 requires economic observations to be recorded, **alerted on** and
analysed. In observe mode `record_risk_decision` enqueues one outbox event `risk.observed`
(aggregate type `risk_observation`) inside its existing transaction, exactly like `risk.halted`,
whenever the observed economic state changes:

| Transition | Meaning | Telegram text (fixed, codes only) |
|---|---|---|
| `observed` | no economic stop -> one or more | `economic stop observed: <codes> — Paper observe mode, collection continues` (+ Arabic line) |
| `changed` | the set of breached codes changed (e.g. drawdown joins a loss streak) | same, with the new code list |
| `cleared` | all economic stops cleared | `economic stop observation cleared — Paper observe mode, collection continues` (+ Arabic line) |

- **State compared:** the tuple of breached economic hard-stop codes (`economic_flags`, legacy
  order: `daily_loss_limit`, `weekly_loss_limit`, `max_drawdown_limit`, `loss_streak_halt`). It
  is computed from the decision values, so it is independent of an administrative pause.
- **Dedup / restart safety (no schema change):** the baseline is the newest persisted
  `risk.observed` outbox row; the new row's `aggregate_id` is that row's `id` (0 for the first
  ever). The existing `UNIQUE(event_type, aggregate_type, aggregate_id)` + `ON CONFLICT DO
  NOTHING` therefore makes each transition one row: repeated identical decisions (every admission,
  every post-close refresh) enqueue nothing; a restarted tracker reads the same rows and does not
  re-alert; two concurrent writers that read the same predecessor collapse to one row. Expired or
  dead-lettered notices stay in the table and remain a valid baseline.
- **Technical halt:** `invalid_risk_state` never computes the economic values, so it is treated
  as *unknown*, not as *cleared*: no observation event (the technical halt keeps its
  `risk.halted` notice and pause).
- **Message content:** codes only. `shared/telegram_messages.risk_observed_message` builds the
  text from the code list alone; unknown codes become `unknown_economic_stop`; the payload carries
  no P&L, counts or drawdown values. Consumed by `telegram/main.py` (`LIFECYCLE_EVENT_TYPES`),
  with the same TTL/defer/dead-letter semantics as the other lifecycle notices.
- **Flapping:** a value oscillating around a threshold (for example drawdown including unrealized
  P&L) produces one notice per real crossing; there is no hysteresis. A notice is never repeated
  without a state change.
- **enforce:** the block is skipped before any statement is issued: no extra query, no event.

## Evidence / version boundary

- Every `admission.decision` payload carries `risk_policy_version`; every risk-bearing payload
  (`risk_decision`, `risk.state`, `trade.opened`) carries it too. It is payload only: dedup
  state and event identities are unchanged.
- `APP_VERSION` / `strategy_version` semantics are unchanged. `PAPER_ECONOMIC_HALT_MODE` is a
  `Config` field, so it is part of the evidence `config_hash` (adding the field moves the hash
  once, as any new config field does).
- `active_trades` has no risk-policy column (adding one needs a schema change, out of scope).
  Trades are separated by the evidence label and the recorded activation boundary.
- **Activation is a new prospective-window boundary.** Trades admitted under
  `econ-observe-v1` must not be pooled with `econ-enforce-v1` trades without stratification.

## What is NOT changed

- Trade-level stop-loss execution, targets, expiry, entry fills (no exit/stop code touched).
- Technical fail-closed safeguards: non-finite inputs, missing prices, missing/inconsistent
  risk state, database failures (still raise), manual pause, signal integrity, duplicates.
- Portfolio construction limits and sizing multipliers.
- Historical records: no reset, rewrite or deletion of `trade_results`, `risk_management`,
  `risk_recovery_events` or counters; the streak is still computed from closed trades.
- An existing persisted pause (including a `risk:loss_streak_halt` row written before
  activation) stays an administrative pause: activation does **not** clear it. Clearing it is
  a separate owner `/resume` decision after verifying the actual halt cause.

## Activation procedure (owner-authorized only)

1. Owner authorizes activation explicitly (Paper strategy/window change + Class B deploy).
2. Verify the actual current halt/pause cause from authoritative DB evidence (read-only).
3. Push the exact candidate commit; record its SHA.
4. Set `PAPER_ECONOMIC_HALT_MODE=observe` in the production environment for `trade_tracker`
   and `telegram` (both read it). Confirm `PAPER_TRADING=true`.
5. Class B redeploy of the affected services, one at a time, from images built from that exact
   commit (`docs/ops/COMPOSE_OPERATIONS.md`): `trade_tracker`, then `telegram`. Capture identity
   before/after, image digests and runtime file hashes. If single-file overlays are used, the
   overlay set must include the new `shared/economic_halt_policy.py` and the changed
   `shared/config.py`, `shared/risk_epoch.py`, `shared/telegram_messages.py` and service
   `main.py` files, or the service will fail to import. `risk.observed` notices enqueued before
   `telegram` runs the new code stay pending and are delivered once it does (or are acked
   `notification_expired` after `NOTIFICATION_TTL_HOURS`; the row still serves as dedup baseline).
6. Smoke checks: tracker log has no "ignored: PAPER_TRADING" warning; `/status` renders;
   first `admission.decision` / `risk.state` evidence shows `risk_policy_version=econ-observe-v1`.
7. Record the prospective-window boundary: UTC activation time, commit SHA, image digests,
   `RISK_POLICY_VERSION=econ-observe-v1`.
8. Any persisted pause is a separate owner decision (`/resume`), not part of activation.

## Rollback

Set `PAPER_ECONOMIC_HALT_MODE=enforce` (or remove it) and Class B redeploy the same services.
No data migration is involved. Behaviour returns to the legacy halts on the next evaluation:
an economic breach then blocks and persists a pause again. Record the rollback time as a
window boundary (`econ-enforce-v1`).
