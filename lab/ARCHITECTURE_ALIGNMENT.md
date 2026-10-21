# L1 architecture alignment: reuse shared execution, cost and exit-policy logic

**Owner direction (2026-10-21):**
- Reuse the existing shared execution, cost and exit-policy logic. Do not duplicate formulas or behaviour in the lab.
- Do not connect the lab to production, change running Paper behaviour, or broadly refactor production.
- Keep exit policies strategy-specific and versioned.
- Keep account ledgers and risk controls independent.

**Status: PROPOSAL, documentation only.** The code in this PR is unchanged. Shared-component work waits for an explicit review of the architecture impact and of the regression gates below.

Basis: code reading of `main` @ `3bd79a4` (`shared/triple_barrier.py`, `shared/partial_exits.py`, `shared/entry_execution.py`, `shared/execution.py`, `shared/fees.py`, `shared/config.py`, `trade_tracker/main.py` `evaluate_trade` path, `research/mechanisms/costs.py`) and `lab/account.py`.

## 1. Compatibility findings (VERIFIED from code)

| Area | Production (Paper tracker) | `lab/account.py` (this PR) | Compatible? |
|---|---|---|---|
| Exit decision engine | `step_barrier()` in `shared/triple_barrier.py`, called per poll with `high = low = close = current_price` and `stop_observation_price = current_price` | own `on_price()` | **No**: duplicated, reduced behaviour |
| T1 → break-even | after T1 the stop becomes `net_break_even_stop() = min(T1, entry × (1 + roundtrip_cost) / (1 − stop_slippage))`; production uses `roundtrip_cost = 0.003`, `stop_slippage = 0.001` | missing | **No** |
| T2 → trailing | after T2: `max(T1, peak × (1 − 2.5 %))`; peak is persisted | missing | **No** |
| T3 | full remaining exit at T3 | last target | partly |
| Priority within a bar | the stop at the start of a bar is checked before that bar's targets (conservative), then the dynamic stop | stop first, then targets | similar, but not identical |
| Expiry | timeframe policy `timeframe_v1`: 15m 48 h / 24 h after T1 / 12 h without T1; 4h 96 / 48 / 24; 1d 240 / 120 / 72 (`expiry_policy_for_timeframe`) | a single `expiry_ts` | **No** |
| Tranches | `partial_25_50_25_v1`: 25 / 50 / 25, edge tranches below `minNotional` merged into T2 (`partial_exits.target_distribution` / `fills_between`); `legacy_full` = no partials | fractions of the original quantity, predeclared | equivalent at 500 USDT (tranches ≥ 125 > 5); must reuse for parity |
| Entry policy and fill | `decide_long_entry()` (reject / market / limit_wait) + `resolve_entry_fill()` (`observed_price_v0` or `resting_limit_v1`); `rebase_long_bracket()` moves the bracket to the fill | none (caller supplies the price) | **gap** |
| Stop fill | `modeled_stop_exit`: fill = min(stop, observed) × (1 − 0.1 %) | executed = observed × (1 − half_spread − slippage) | different models |
| Target fill | exact target price, no slippage | observed price moved by costs | different |
| Fees | flat **0.30 % round-trip label** on the fixed 50 USDT notional at close (`shared/fees.economic_close`); a reporting convention | 0.10 %/side on executed notional | **must differ** (owner lab cost policy) |
| Research cost model | `research/mechanisms/costs.py` `CostModel` (`s4-mech-v1`): 0.10 %/side fee floor, explicit half-spread and slippage, refuses discounts | own `ExecutionCosts` | duplicated: reuse `CostModel` |
| Money arithmetic | float, fixed `TRADE_AMOUNT_USDT = 50`, gross % × notional | Decimal, per-account sizing | must stay lab-specific |

## 2. Reusable pure components (no I/O, no config globals)

1. **Exit-policy state machine:** `TripleBarrierConfig`, `TripleBarrierState`, `step_barrier`, `effective_stop`, `net_break_even_stop`, `expiry_policy_for_timeframe`. Only the **decision** outputs are used: target transitions, exit reason, exit trigger, `stop_hit`. The P&L fields (`profit_pct`, `profit_usdt`, float, fixed amount) are **ignored** by the lab.
2. **Tranche plan:** `partial_exits.target_distribution` / `fills_between`, for fractions only. `gross_usdt` is ignored.
3. **Entry policy:** `decide_long_entry`, `resolve_entry_fill` (with a named fill model) and `rebase_long_bracket`.
4. **Cost rates:** `research.mechanisms.costs.CostModel`. The lab adds its own floor rule on top (half-spread > 0, slippage ≥ 0.05 %).

## 3. Interfaces and versioning (proposal)

- **`lab/exit_adapter.py` (new, lab-only):**
  - builds a `TripleBarrierConfig` from the strategy spec;
  - calls `step_barrier` with explicit parameters, **never** from `shared.config`;
  - turns each decision into lab exit instructions: tranche fractions via `fills_between`, and the terminal exit with its trigger price.
  - It never copies a formula.
- **Exit trigger price:**
  - targets use the target price;
  - stops use `min(effective_stop, observed)`;
  - expiry uses the observed close.
- **One cost application:** lab costs (`CostModel` + fee) are applied once, on top of the trigger price. Production's stop-slippage multiplier is used only inside `net_break_even_stop` to place the break-even level, never to book money.
- **Getting the stop trigger:**
  - (a) Preferred, needs a separate approved shared change: expose `stop_reference` on `TripleBarrierResult` additively.
  - (b) Lab-only, no shared change: invert the fill, `reference = exit_price / (1 − stop_slippage)`, with a tolerance test (`exit_price` is rounded to 8 dp).
- **Versioned identifiers, recorded in every strategy registration and in each position:**
  - `exit_policy_id`: for example `tb1:partial_25_50_25_v1:timeframe_v1:be_cost=0.003/0.001:trail=2.5`;
  - `entry_fill_model` ∈ `FILL_MODELS`;
  - `cost_model_id`: for example `s4-mech-v1:<tier>`;
  - `shared_blob_pins`: the git blob hashes of the shared modules used.
- A change to any of these is a **new strategy version**: new account, no reuse.
- **Strategy-specific policies:** any parameter the shared state machine already exposes (targets, stop, expiry hours, trail %, break-even cost basis) can be set per spec. A policy that needs **new** behaviour is a new, separately reviewed module. It is never a silent edit of `triple_barrier.py`.

## 4. Production-parity tests (gates before any implementation is accepted)

| # | Test | Passes when |
|---|---|---|
| P1 | Decision parity: seeded synthetic paths × brackets × timeframes, run through the adapter and through production's `step_barrier` + `fills_between` sequence | identical target transitions, exit reason, trigger price and timing |
| P2 | Break-even and trailing boundaries: price exactly at T1, at the break-even stop, at `peak × (1 − 2.5 %)`, a gap through a stop | identical decisions; Decimal↔float conversion never flips a comparison |
| P3 | Tranche parity, including `minNotional` merges (small notional fixtures) | identical fractions |
| P4 | Gross-P&L parity: lab gross before costs vs production gross % × notional | equal within 1e-8 per unit notional |
| P5 | Shared-module pins: blob hashes of the shared modules asserted in a lab test | any change to a shared module forces a review |
| P6 | Production identity: no production module imports `lab`, and the production test suites are unchanged | byte-identical behaviour, `main` CI green |
| P7 | Stop-reference inversion (option b) | `|ref − min(stop, observed)| ≤ 1e-8 × price` |

## 5. Lab-specific accounting responsibilities (stay in `lab/account.py`)

- Cash, reservations, the exposure cap (cost basis + reservations), position limits and sizing.
- Per-tranche booking at the trigger price with `CostModel` costs and the 0.10 %/side fee, in Decimal.
- Idempotency, transactions, the hash-chained ledger, ledger-cash reconciliation and daily snapshots.
- R9 suspension, the integrity block and owner review.
- Recording `exit_policy_id`, `cost_model_id` and `entry_fill_model` per position.

## 6. Behaviour that must NOT be shared

- The tracker's DB, outbox, Telegram and evidence side effects (`evaluate_trade` / `close_trade_barrier`).
- Global risk: the B3 loss-streak breaker, `risk_epoch` and `risk_management` limits based on a 500 USDT capital.
- `shared.config` globals (`TRADE_AMOUNT_USDT`, `FEE_ROUNDTRIP_PCT`, `STOP_SLIPPAGE`), which are passed explicitly instead.
- Production money and labels: the float gross P&L on a fixed 50 USDT, and the flat 0.30 % `economic_close` label. It may be **reported** next to lab results (`tracker_flat_cost`), never booked.

## 7. Remaining scientific limitations

- Decisions are poll-based (a single observed price per check) as in production. Bar replays use the conservative stop-first ordering and still miss intrabar paths.
- Full fills only. Target fills at the exact limit price are optimistic for queue position.
- The break-even level depends on the declared cost basis. Production parity (`0.003 / 0.001`) and the lab's cost model differ, and the choice is part of `exit_policy_id`.
- No partial fills, lot or tick sizes, or depth impact. The R6 sensitivity tests are still required.

## 8. Not done in this PR

No shared-code change, no adapter implementation and no new behaviour. `lab/account.py` stays as it is until this alignment is reviewed.
