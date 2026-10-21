# L1 lab account module: notes for the independent architecture review

**Scope.** `lab/account.py` is a pure, in-memory reference implementation of the owner-approved account rules (`docs/lab/STRATEGY_LAB_ARCHITECTURE.md` §2.2, R0–R10). It is **not** wired to any service, image, database or schedule. Merging it is gated on the independent architecture review (review package R2); activation needs separate approvals (lab DB, `LAB_MODE` engine, strategy specs).

## Invariants and where they are enforced and tested

| # | Invariant | Enforcement | Tests (`tests/test_lab_account.py`) |
|---|---|---|---|
| I1 | cash = initial + realized P&L − open cost basis | `integrity_problems` (`cash_identity`) | ledger/cost tests, randomized run |
| I2 | cash recomputed from ledger events = cash | `ledger_cash` (`ledger_cash_mismatch`) | `test_rehashed_ledger_edit_detected_by_cash_reconciliation` |
| I3 | hash chain intact | `verify_ledger` (`ledger_chain`) | `test_ledger_chain_and_cash_reconciliation` |
| I4 | cash ≥ 0; reservations ≤ cash (no leverage/borrowing) | `_decide` sizing + invariants | `test_no_leverage_order_limited_by_cash` |
| I5 | exposure (cost basis + reservations) ≤ 2,500; mark value never counts | `exposure`, `_decide` | `test_exposure_cap_*`, `test_cap_counts_pending_*` |
| I6 | ≤ 5 positions incl. pending; one per symbol incl. pending | `_decide`, invariants | `test_max_five_*`, `test_one_position_per_symbol_*` |
| I7 | each intent / fill / exit books at most once; conflicting replay refused | `decisions` / `fills` / `exits` maps | `test_idempotent_intent_fill_and_exit` |
| I8 | an operation is all-or-nothing (state and ledger) | `_txn` rollback | `test_failure_mid_transaction_leaves_nothing` |
| I9 | fee 0.10 %/side on executed notional; spread + slippage against the order; below-model costs refused | `ExecutionCosts`, `fill_*` | `test_target_order_and_fee_booking`, `test_sell_fee_*`, `test_costs_below_model_refused` |
| I10 | R9: 30 % drawdown or equity < 2,000 → `SUSPENDED_REVIEW`; 8 losses → alert only; integrity failure → `BLOCKED_INTEGRITY` immediately | `_risk_triggers`, `_after`, `_enter` | the five R9 tests |
| I11 | in every non-active state, predeclared exits still execute; nothing force-closed; pending entries released | `on_price`, `fill_exit`, `_enter` | drawdown, integrity and close tests |
| I12 | no automatic resumption, reset, top-up or reopen | only `owner_review`; `Lab.open_account` once | `test_no_automatic_resumption_*`, `test_no_topup_reset_or_reopen` |
| I13 | accounts independent (no shared state, no netting) | separate `Account` objects | `test_independent_accounts_same_symbol`, randomized run |
| I14 | not imported by production; no image copies `lab/` | — | `test_module_is_not_imported_by_production_code` |

Mutation check: 13/13 hand-written mutants killed. The list is in the PR description.

## Known limits (deliberate, for the reviewer to accept or reject)

1. Full fills only. No partial fills, queue position, depth impact, lot or tick sizes. The sensitivity tests (R6) belong in the engine and reporting layer.
2. Long-only spot. Exit plan = stop, ordered targets as fractions of the original quantity, expiry. Gap moves execute at the observed price, minus costs.
3. The self-check after every operation re-verifies the whole chain, O(n) per operation. A persistent engine should verify incrementally and run a periodic full audit.
4. Money is rounded to 1e-8 USDT and quantity to 1e-12, rounding down. A round-trip residual below 1e-6 USDT is accepted in the cost identity test.
5. **PROP:** after an owner resume, drawdown is re-measured from the review point, and the 2,000 trigger re-arms on the next crossing.
6. In-memory only. Persistence (the `tsb_lab` schema), transactions across processes, and crash recovery from the DB are later steps.

## Architecture alignment (owner direction 2026-10-21)

See `lab/ARCHITECTURE_ALIGNMENT.md`. The current exit plan and cost arithmetic in `lab/account.py` duplicate, and only partly match, the shared production components:
- missing T1 break-even, T2 trailing and timeframe expiry;
- no entry policy;
- a separate cost class.

They are to be replaced by an adapter over the shared pure components. That replacement is **not implemented yet**: it is gated on review of the alignment and of the parity tests P1–P7.

## Questions for the reviewer

1. Should `BLOCKED_INTEGRITY` keep executing predeclared exits on a ledger that just failed an invariant, or freeze everything pending review? The current choice follows the owner rule that open positions keep their risk handling.
2. Is releasing pending (unfilled) entry orders on entering any non-active state the right reading of "suspend new trading"?
3. Is the re-arm rule (limit 5) acceptable, or must the owner set an explicit new baseline at each resume?
4. Must the cost floor (half-spread > 0, slippage ≥ 0.05 %) be per-symbol tiers (a48-cost-v1) rather than one floor?
5. Which persistence design keeps I7/I8 under concurrency: one DB transaction per operation with unique keys on intent, order and exit ids, or something else?
6. Is the adapter boundary in `ARCHITECTURE_ALIGNMENT.md` §3 correct? Only `step_barrier` decisions and `fills_between` fractions are taken from production, and money is booked by the lab with `CostModel` once.
7. For the stop trigger: should production's `TripleBarrierResult` gain an additive `stop_reference` field (a shared change with its own regression gate), or should the lab invert the modelled stop fill?
8. Are the parity tests P1–P7 sufficient, and is pinning shared-module blob hashes in a lab test an acceptable change-control mechanism?
9. Which break-even cost basis should lab strategies declare by default: production parity (`0.003 / 0.001`) or the lab cost model?
