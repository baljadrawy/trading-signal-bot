# A47 — Execution Realism & Replay Calibration

**Verified:**
- production Paper `p1d-59297305` (analyzer and tracker sha256-equal to `59297305`; the tracker is pre-A38), schema 9, Collector `p2f-160-1bfb5f6`;
- A46 `c64c77e` contains `3cbe7a9` / `77421ba` and is clean.

**Branch:** `feature/a47-execution-realism` from `c64c77e`, code commit `b94c59f`. Local only; production untouched.

**Evidence levels.** Level 1 (mathematical correctness) and level 2 (agreement with the Paper tracker) are shown here. **Level 3 (real-world execution validity) is not established.**

## A47-A — Execution architecture and assumptions

| Aspect | Production `59297305` | A44 (integrated, undeployed) | A42 replay (research) | A46 ledger (research) | Exchange-realistic (A47 research) |
|---|---|---|---|---|---|
| Clock | tracker wall clock at poll / stream time | same | bar open times | none | — |
| Entry rule | `decide_long_entry` at the observed price: reject ≤ max(stop, invalidation); market if ≤ planned; else wait (2 h window) | same + durable `paper_entry_orders` | first bar open; resting limit fills only on a **strict trade-through**, at the limit | entry = planned | BUY LIMIT rounded **down** to tick |
| Entry fill | **at the observed price** (touch fills) | `observed_price_v0` (`resting_limit_v1` disabled) | at the limit | — | qty floored to step; budget < $50 |
| Quantity | notional $50, no qty / lot | same | notional | notional | `LOT_SIZE` / `MARKET_LOT_SIZE` / `NOTIONAL` validated |
| Exits | `step_barrier` per poll with high = low = close = price, `stop_observation_price = price` | same | `step_barrier` per bar (H/L/C), stop before targets; `stop_observation_price` only for an open below the stop | canonical paths | SELL targets rounded **up**, stops **down** |
| Stop fill | **first observed price beyond the stop** × (1 − 0.1 %) | same | **the stop level** × (1 − 0.1 %), unless it gapped at the open | level × (1 − s) | — |
| Partials | 25/50/25, min-notional merge | same | same | same | tranche floor + remainder + dust check |
| Costs | gross stored; reports net = gross − 0.3 % flat | + stored A38 economic label (same flat) | gross; net = gross − CostModel | per-leg: 0.1 % per side on each leg's value + half-spread on market legs + stop slippage in the fill | — |
| Tick / lot | none (prices `round(·, 8)`) | none | none | `quantize` helper | `exchange_rules` |
| Restart | state re-read from DB on every evaluation | + durable orders, outbox defer | stateless | — | — |
| Event order | **arrival order; no event-time reordering** | same | time-sorted bars | — | — |

## A47-B — Event-level calibration harness

**`shared/execution_calibration.py`** (`a47-cal-v1`):
- `tracker_poll_model` transcribes `register_new_signals` + `evaluate_trade` and calls the production functions;
- `bars_from_polls` + `replay_bracket` run the same events through the A42 replay;
- `calibrate` classifies each difference with **classes declared in the module before any comparison**.

**Agreement with the actual tracker:**
- `tests/test_a47_tracker_parity_db.py` drives the **real** `register_new_signals` and `evaluate_trade_safely` (A44 tree, disposable PostgreSQL 16.15), with `opened_at` shifted per poll.
- Result: **6/6 paths are identical** to the poll model in fill price, exit reason, gross %, gross USDT and target reached. The paths: stop at the level, stop overshoot, T1 → break-even, T3, trailing, no-T1 expiry.

## A47-C — Intrabar ambiguity

- OHLC hides the order of events inside a bar. `ordering_interval` evaluates every bar both **stop-first** (O→L→H→C) and **target-first** (O→H→L→C) through the tracker model and reports both outcomes. The **research default is the worse net**.
- `ambiguous_bars` counts bars whose range contains both the stop and a target.
- The replay already orders stop-first, but prices the stop **at the level**. Its result therefore lies **between** the conservative and favourable bounds (`test_07_10`), so it is not the conservative bound.
- No tick sequence is inferred from OHLC; favourable orderings are never used.

## A47-D — Exchange-rule validator

**`shared/exchange_rules.py`** (`a47-xr-v1`) implements the official filter formulas quoted in the module:
- PRICE_FILTER;
- LOT_SIZE;
- MARKET_LOT_SIZE (MARKET only);
- MIN_NOTIONAL / NOTIONAL (with the apply-to-market flags).

PERCENT_PRICE\* and MAX_NUM_ORDERS need live reference data and are out of scope. Fixtures are versioned and **illustrative**, not live values.

**Rounding rule:** never make an order better for us.
- BUY entry down to tick;
- SELL targets up;
- SELL stop down;
- quantity down.

Any adjustment larger than 10 % of the risk distance is **rejected** (`rounding_material:*`), never silently applied.

**Tranches:** floored to the step; the last open tranche takes the remainder; a sub-minimum tranche merges into T2 (the production rule); unsellable remainders are reported as **dust**.

## A47-E — Cost and fill reconciliation

**The tracker's flat 0.3 %** = 0.2 % fee + 0.1 % slippage allowance (per the `config.py` comment). This is an intentional allowance. **But** every stop exit is *also* filled at stop × (1 − 0.1 %), so on stop exits slippage is **counted twice**. `tracker_cost_decomposition`: double-counted ≈ 0.098 % on a full stop exit at 0.98 × entry.

Targets fill exactly at the target, so the allowance is a pure cushion there.

**Classification:** MODEL ASSUMPTION (conservative), **not changed** (production accounting needs separate approval). `detect_cost_overlap` flags such overlaps in any cost composition. The A46 per-leg ledger charges fees only, with slippage in the fill: no overlap.

**Cost scenarios** (fee-only, normal and wide spread, adverse slippage, multi-leg, min-notional, dust, rejection) are covered by tests. A38 `economic_close` labels reconcile with the ledger's flat net on every path (A46 `test_27`, A47 `test_36_37`).

## A47-F — Regression and calibration evidence

**Calibration metrics** (deterministic scenarios):
- **decision and exit parity with the real tracker:** 6/6;
- **unambiguous canonical paths (tracker poll model vs replay):** MATCH 4/4 (T3, T1 → break-even, stop at the level, T2 → trailing), plus reversion MATCH;
- **ambiguous OHLC cases:** reported as intervals;
- **unexplained (IMPLEMENTATION_DEFECT) discrepancies: 0.**

**Classified discrepancies:**

| Discrepancy | Class | Size / direction |
|---|---|---|
| **Stop overshoot** | MODEL_ASSUMPTION_DIFFERENCE | the replay prices at the level, the tracker at the first poll beyond it. The replay is **optimistic by exactly overshoot × 0.999 pp** (tested at 0.1 / 0.5 / 1.0) |
| **Entry on touch** | MODEL_ASSUMPTION_DIFFERENCE | the tracker fills at the observed price; the replay requires a strict trade-through |
| **Expiry** | MODEL_ASSUMPTION_DIFFERENCE | poll time and price vs bar-end close (example diff −0.1 pp) |
| **Intrabar gap** | MODEL_ASSUMPTION_DIFFERENCE | first poll vs bar open |
| **Out-of-order events** | MODEL_ASSUMPTION_DIFFERENCE | the tracker processes them in arrival order |
| **Delayed events** | (behaviour, not a model gap) | the tracker uses processing time: the same price delayed 30 h → expiry |

Duplicate events are idempotent. Results are deterministic across repeated runs.

**Tests:**

| Run | Passed | Failed | Skipped | Note |
|---|---|---|---|---|
| Default suite | **915** | 0 | 799 | 891 + 24 new; the +6 skips are the DSN-gated parity tests |
| Disposable-DB run | **6/6 parity + 43** | 0 | 3 | A38 lifecycle, A44 integration and migration, A39 review. The 3 skips need before-tree variables (their full matrix ran in A44) |

**Coverage limitations:** synthetic events only; no real tick or order-book data; illustrative filters; the tracker's price stream / REST cadence is not modelled.

## A47-H — Decision: **REVISE EXECUTION MODEL**

**The replay is not ready for scientific design.** Its stop pricing is systematically optimistic relative to the tracker whenever monitoring is discrete. That bias directly affects every counterfactual candidate (A45 H2, A46 G1–G3, A44 ranking).

**Next actionable step (local engineering):**
- add a versioned replay stop-fill policy that reports an **interval** per bar (fill ∈ [min(stop, bar low), stop]), with the conservative end as the research default;
- record poll cadence as an explicit assumption;
- re-run this calibration with the declared acceptance criteria unchanged.

**Market data:** real calibration (level 3) would need a forward capture of tracker polls alongside OHLC under an owner-approved Paper window.
