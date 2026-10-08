# P2-RM0 — D-RM0-2 dimensional-integrity repair (RM0-UNITS 1.1.0)

**Status:** code complete and tested on an isolated branch. Not merged, not deployed. RM0 overall stays **not closed**
until the owner reviews this repair.

## History (preserved, not reinterpreted)
1. The original P2-RM0 run **STOPPED** on 2026-10-06. The stop was operationally valid: a collector stall occurred
   during the run. The sealed evidence (`p2rm0-20261006T082727Z`, code `9c7b750`, logical hash `9ff677e8…788b`)
   is unchanged.
2. An independent closure review (`p2rm0-closure-review-20261006T102809Z`) found **D-RM0-2**: portfolios with more
   than one quote currency fail open.
   - `exposure.gross` was refused, but the raw cross-currency total still fed heat, concentration, weights,
     covariance, BTC aggregates, liquidity aggregates and risk contribution as **VALID**, and research flags fired
     on those values.
3. The root-cause and aggregation-path audit is in `p2rm0-repair-closure-20261006T112651Z`.
4. This repair was owner-authorised on 2026-10-08. **No heavy real-data run was used.** All real RM0 v1 snapshots are
   single-quote USDT, so the sealed results are unaffected and are not rewritten.

## Units (frozen in `p2_research/risk/contracts_rm0_v1_1/units_v1.json`; FROZEN_SHA256SUMS sha `76f9da93907752ca…`)
| Quantity | Unit |
|---|---|
| price | quote currency per one base-asset unit (per instrument) |
| quantity | base asset units |
| notional, fee | the instrument's quote currency |
| returns, σ, ρ, β | unitless (per instrument or pair) |
| shares, weights, heat | unitless ratio, defined only over positions sharing one quote currency (heat additionally requires that currency to equal the capital currency) |

## Rule (fail-closed)
- **Mixed currencies:** a cross-position monetary or notional-weighted aggregate is VALID only if every position it
  aggregates has the same canonical quote currency. Otherwise it is `UNAVAILABLE` with reason
  `mixed_quote_currencies_no_fx_conversion`.
- **Capital mismatch:** a single-quote book in another currency than the capital gets `exposure_heat` and
  `vol_heat` `UNAVAILABLE` (`capital_currency_mismatch_no_fx_conversion`), and
  `exceeds_hypothetical_capital = null`.
- **No assumptions:** no case folding, no stablecoin aliasing, no epsilon, and no FX conversion (extension point only).
- **Unchanged:** per-instrument and unitless values; the `by_quote_currency` and `by_symbol` partitions; unweighted
  correlation; counts; regime; drawdown.
- **Flags:** they no longer fire on refused values. Only `RM0-S-MIXED-QUOTE-CURRENCIES` and the per-instrument
  flags remain.
- **Independent reference** (`reference.py`): implements the same refusal by its own logic.
- **Contract provenance:** the base contract set `9d9faaf6…` stays byte-identical. Snapshots add
  `contracts.rm0_units_amendment_sha256`.

## Tests
- `p2_research/tests/test_risk_units_drm02.py`: 11 tests.
  - The BTCUSDT 5000 + ETHBTC 0.5 demo; three quotes; a vanishing second quote; distinct stablecoins.
  - Mixed tier/venue buckets.
  - A single BTC-quoted book with USDT capital (refused) and with BTC capital (valid); a flat book.
  - The reference refuses mixed quotes independently.
  - The frozen amendment, with the base set unchanged.
  - **USDT-only P0–P7 outputs byte-identical to `9c7b750`** apart from the `contracts` block and `snapshot_id`.
- **Fail-before:** on `9c7b750`: 7 failures, 2 errors.
- **After:** `test_risk_rm0` + the new tests pass 64/64.

## Known limitation (unchanged)
L-RM0-1: universe and regime medians do not carry per-symbol STALE state. Values are correct; this is labelling only.
It is deferred to a predeclared later version.

## Acceptance review of `5f22431` (2026-10-08, read-only): CONDITIONAL
**Passed:**
- **Nulls stay null.** `V.mv`/`na` and `check_tree` enforce null ⇔ UNAVAILABLE with a reason; canonical JSON keeps
  `null`; `reference.compare` treats null ≠ number as a difference. No `or 0` style coercion exists in `risk/`.
- **Unknown is not safe.** `exceeds_hypothetical_capital` is `null`, not `false`; threshold flags skip null values;
  no downstream consumer derives pass/fail from refused values.
- **Single-quote compatibility.** USDT-only P0–P7 are byte-identical to `9c7b750`, excluding the contracts block
  and `snapshot_id`.
- **The reference is independent.** It uses its own quote-set rule over its own tuples, not `snapshot.py` code.
- **Frozen material is unchanged.** RM0 base set (0 files changed), P2-D0 and P2-X contract sets are untouched, and
  the RM0 v1 evidence seal still verifies.

**Gaps (each a small correction; neither affects any USDT-only or sealed result):**
1. **`exposure.by_tier` is exported without a unit** (`snapshot.py`, `_exposure`, the `by_tier` line). In a
   mixed portfolio each tier bucket can be single-quote and therefore VALID, but the buckets are in different
   currencies with no unit label. Example: tier0 = 5000 USDT and tier1 = 0.5 BTC, both VALID. A consumer that sums
   tiers would silently mix units.
   - Smallest fix: when the portfolio is mixed, refuse `by_tier` gross/net with `mixed_quote_currencies_no_fx_conversion`.
     `by_quote_currency` remains the valid partition, and `by_symbol` stays (the unit is the position's
     `quote_currency`).
   - Add one test assertion.
2. **Real-data validation does not pass quote currencies to the independent reference** (`realdata.py:129`). It
   calls `REF.metrics` with `(symbol, signed_notional)` pairs, so the reference cannot apply its own currency rule.
   A mixed real-data portfolio would show a spurious disagreement. That is fail-loud, not silent.
   - Fix: pass `(symbol, signed_notional, quote_currency)` there and in `tests/test_risk_rm0.py:630`.

**Recommendation:** apply corrections 1–2 as one small commit with a test, then re-review the diff only. Accept after.

### Acceptance gaps corrected (owner-authorised, 2026-10-08)
1. **Tier breakdown:** `snapshot.py` `_exposure`. When the portfolio is mixed, `by_tier` gross/net are refused with
   `mixed_quote_currencies_no_fx_conversion`. Counts are kept. `by_quote_currency` stays the valid partition.
   Single-quote tier breakdowns are unchanged.
2. **Reference inputs:** `realdata.py:129` and `tests/test_risk_rm0.py:630` now pass
   `(symbol, signed_notional, quote_currency)`, so the independent reference applies its own currency rule.

**Tests:**
- Focused (`test_risk_units_drm02`): 13/13. New assertions cover mixed tiers refused, single-quote tiers valid, and
  the reference receiving currency metadata with agreement on null.
- RM0 suite: 66/66, including USDT-only P0–P7 byte-identical to `9c7b750`.
- Frozen contracts and evidence are untouched.
