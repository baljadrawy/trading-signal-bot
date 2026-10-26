# L1: original-stop recovery decision and production-parity test specification

Status: **specification only.** No shared module was changed. Implementing it is gated on review of `ARCHITECTURE_ALIGNMENT.md` and this document.

## 1. Recovering the original stop trigger: approach A vs. approach B

Production books a stop exit as `exit_price = round(min(effective_stop, observed) × (1 − stop_slippage), 8)` (`triple_barrier._stop_result` → `modeled_stop_exit`). The lab needs the **unslipped trigger price** so that it can apply its own cost model once.

**B (reverse transformation, `ref = exit_price / (1 − stop_slippage)`): REJECTED.** Exact recovery cannot be proven:

1. **Rounding loss.** `exit_price` is rounded to 8 decimals, so the inverse is ambiguous by up to 0.5e-8 / (1 − s). Relative to price this is negligible for BTC, but about **4 bps for a 1.2e-5-priced asset**. It is not exact, and it can flip boundary comparisons.
2. **Source ambiguity.** `min(effective_stop, observed)` loses **which** side won: an at-stop fill versus a gap-through. That distinction matters for slippage-asymmetry analysis and for R6 sensitivity.
3. **Reason-conditional.** Expiry and T3 exits are not slipped (`exit_price = close` or `target_3`). Inverting needs `exit_reason` and the exact `stop_slippage` of the policy that produced the trade. Both are policy-specific assumptions.
4. **Float provenance.** `stop_slippage` comes from a float config value. The inverse is only as exact as that value's float representation.

**A (minimal explicit shared interface): RECOMMENDED**, subject to approval of a shared change:

- Append two **optional, defaulted** fields to `TripleBarrierResult`:
  - `trigger_price: float | None = None`: the unslipped trigger (target price, `min(effective_stop, observed)`, or the expiry close);
  - `trigger_kind: str | None = None`: one of `target`, `stop_at_level`, `stop_gap_through`, `expiry`.
- They are set inside `_stop_result`, `_expiry_result` and the T3 branch. Positional construction stays valid, because the fields are appended last with defaults.
- **Production ignores them.** All existing fields stay byte-identical (gate P6a below). No formula changes. `trade_tracker` code is untouched.

## 2. Production-parity tests

| # | Test | Input | Pass criterion |
|---|---|---|---|
| P1 | Decision parity | seeded synthetic poll paths (≥ 10,000) × brackets × `15m` / `4h` / `1d` timeframes, through the lab adapter and through production `step_barrier` + `fills_between` | identical sequences of (`highest_target`, exit reason, `stop_hit`, close index) |
| P2 | Break-even and trailing boundaries | price exactly at T1, at the break-even stop, at `peak × (1 − 2.5 %)`, one tick either side, a gap through each | identical decisions; no Decimal↔float conversion flips a comparison |
| P3 | Tranche parity | notionals around `minNotional` (4.99, 5, 5.01, 20, 500 USDT) | identical `target_distribution` fractions and merges |
| P4 | Gross P&L parity | the P1 paths, zero lab costs (test-only path) | lab gross per unit notional = production gross % / 100, within 1e-8 |
| P5 | Shared-module pins | git blob hashes of `triple_barrier.py`, `partial_exits.py`, `entry_execution.py`, `execution.py`, `research/mechanisms/costs.py` asserted in a lab test | a change to a pinned module fails the lab test until it is re-reviewed |
| P6a | Additive-interface identity (only if A is approved) | the P1 corpus through `step_barrier` before and after the change | every pre-existing `TripleBarrierResult` field identical; tracker test suites green |
| P6b | Production isolation | import graph and production suites | no production module imports `lab`; production CI unchanged |
| P7 | Trigger correctness (A) | the P1 and P2 corpora | `trigger_price` = `min(effective_stop, observed)` for stops, the target for targets, the close for expiry; `trigger_kind` is correct |

## 3. Failure and boundary tests (lab adapter)

| # | Case | Expected |
|---|---|---|
| F1 | Invalid bracket (`validate()` message) | intent rejected, ledger records the reason, no reservation |
| F2 | Non-finite or zero observed price | refused before `step_barrier`; no state change |
| F3 | Same tick hits the stop and T1 | stop wins (production priority); no tranche booked |
| F4 | One tick through T1, T2 and T3 | tranches T1 + T2 + T3 booked once each; the position closes |
| F5 | Replay of the same tick or exit id | idempotent (I7); no double booking |
| F6 | Account `SUSPENDED_REVIEW` or `BLOCKED_INTEGRITY` with an open position | adapter exits still execute (I11) |
| F7 | `exit_policy_id` or pinned blob mismatch at load | the position refuses to evaluate and is reported; no silent fallback |
| F8 | Expiry at exactly the policy hour boundary | identical to production `hours_open >=` semantics |
| F9 | Decimal ↔ float round trip at the 8-decimal boundary | documented tolerance; comparisons use production float semantics |
| F10 | Clock or ordering: polls out of order | refused (monotonic `ts` required) |

## 4. Remaining limitations (unchanged by A)

Poll-based decisions, full fills, optimistic target fills, and a break-even level that depends on the declared cost basis. See `ARCHITECTURE_ALIGNMENT.md` §7.

## 5. Evaluation of interface A (owner-approved direction for isolated planning, 2026-10-22)

| Requirement | Finding (`main` @ `5ce3ca3`) | Gate |
|---|---|---|
| Backward-compatible defaults | `TripleBarrierResult` is built at 4 sites in `triple_barrier.py`; `_stop_result` constructs it positionally. New fields **appended last with defaults** keep every call valid | P6a; a compile-time test constructs it with the old positional arity |
| Serialization compatibility | no `asdict` / JSON / `__dict__` / pickle use of `TripleBarrierResult` in production or tests. The tracker reads attributes only. Dataclass `__eq__` would include the new fields; no production equality use was found | P6a compares only the pre-existing fields; grep gate in CI for new `asdict(result` uses |
| Decision parity, Paper unchanged | fields are set where the result is built; no decision or formula changes; `trade_tracker` untouched | P1, P2, P6a, plus the tracker suites |
| No duplicate fee booking | the lab books money **only** from `trigger_price` (or the tranche target price) with `CostModel` + fee **once**, and never from `exit_price` | new L-test: round-trip cost = fees + implicit costs exactly, for stop, target and expiry exits; mutant "book from exit_price" must fail |
| Gaps | `trigger_kind = stop_gap_through` when `observed < effective_stop`, else `stop_at_level`; `trigger_price = min(effective_stop, observed)` | P7 + F3 |
| Partial fills | tranche exits stay `fills_between` at the target price (`trigger_kind = target`); order-level partial fills are **not** modelled (stated limitation, R6 sensitivity) | P3, F4 |
| Rounding | `trigger_price` is the unrounded float (no 8-dp loss); the lab converts it to Decimal once at the adapter boundary; production `exit_price` keeps its rounding | F9; property test: `round(trigger × (1 − s), 8) == exit_price` for stops |
| Stop triggers | break-even and trailing stops use the same path (`effective_stop`); `trigger_kind` records which reason applied in `exit_reason` | P2, P7 |
| Failure | invalid bracket, non-finite price, replay, policy-pin mismatch | F1, F2, F5, F7 |
| Concurrency | the adapter and `Account` are pure and not thread-safe by design; the engine must serialize per account (one lock or one task per account). Test: N concurrent tick streams through the engine lock produce a ledger identical to sequential replay; two accounts on the same symbol never share state | new C1 / C2 tests |

**Status:** design and test specification only. No shared-module change. The change to `triple_barrier.py` needs its own PR with P1–P7, F1–F10 and C1–C2 green, plus the independent architecture review.
