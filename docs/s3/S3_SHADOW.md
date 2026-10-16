# S3 shadow evaluation (`s3-shadow-v1`): architecture, contracts, real-data assessment

## Architecture and isolation

- **Authority.** The operational selector, `SignalEngine.find_best_signal_live`, remains the **sole** decision-maker.
- **What the shadow does.** `shared/s3_shadow.py` only describes what S3 (`s3-sel-v1`) would choose from the *same* input snapshot.
- **What it never does.** It never emits, suppresses, delays or duplicates a signal.
- **Isolation, enforced by tests:**
  - **Disabled by default:** `ShadowConfig(enabled=False)` returns `DISABLED` without evaluating anything.
  - **No production import:** registry and source tests; a mutation that imports it into `analyzer/main.py` fails the test.
  - **No side effects:** the input snapshot and the operational pick are unchanged.
  - **Failures become records:** `run_shadow_safely` never raises. Exceptions return `ERROR`, an exceeded time budget returns `TIMEOUT` (the result is discarded), and oversized input returns `INVALID_INPUT`. The worker thread cannot be killed, so `max_candidates` bounds the work instead.
- **Future wiring (a separate, reviewed slice):** the call would run strictly *after* the operational decision and publication, and would write only the record.

## Contracts

| # | Contract | Field(s) |
|---|---|---|
| 1 | Input snapshot identity and timing | `snapshot_id`: an order-independent sha256 of the rows, liquidity, state sets, decision time and source; `decision_ms`; `source` ∈ engine_cycle / offline_extract / synthetic |
| 2 | Current-selector result | `operational`: `selector_id` = `live_fixed_execution_quality_v1`, and a pick or `null` (NO_TRADE). `replica`: the exact production-parity key (`a43-cs-v1/production_parity`) and `matches_operational`, so live-code drift is detected rather than assumed away |
| 3 | S3 result | `s3`: outcome, pick, `no_trade_reason`, `reason_counts`, eligible count, universe |
| 4 | Agreement classification | `AGREE_SELECT`, `AGREE_NO_TRADE`, `DIFFERENT_PICK`, `S3_NO_TRADE_ONLY`, `S3_ONLY`. S3_ONLY is impossible while S3 ⊆ production eligibility, so it sets `invariant_violation` |
| 5 | Rejection reasons | `candidates[]`: stage, reason codes (`signal_selection.REASON_CODES`) and metrics per candidate, in canonical order |
| 6 | Modelled costs | `costs`: fee 0.20 % round trip (0.10 %/side, no BNB discount), the observed spread, and baseline slippage labelled as an `assumption`. `sensitivity[]` holds one S3 run per declared slippage scenario (default 0 / 0.05 / 0.10 / 0.20 % round trip), **each labelled as an assumption** |
| 7 | Versions | `version` = `s3-shadow-v1`, `s3_version`, `policy` and `policy_id` (sha256 of the policy) |
| 8 | Audit digest | `audit_digest`: sha256 of the record excluding the timing fields. Identical input gives an identical digest |
| 9 | Errors and observability | `status`; `error` (type plus a truncated message only); `elapsed_ms`; `summarize()` counts statuses and classifications |

**Known production quirk that the record exposes.** With a NaN spread, the production key's `min()` depends on input order, and a **NaN-spread candidate can be selected**. The replica reproduces this. S3 rejects NaN and is order-invariant (tested).

## Real-data assessment (2026-10-16)

**Data classification:**

| Data | Class | Decision |
|---|---|---|
| `analysis_results` (the current candidate snapshot, upserted per symbol/timeframe, plus the engine's own `decision_reason`) and `scan_candidates.volume_usdt` | **operational diagnostic**; no outcomes. A43 read it read-only | used through **one** read-only extract containing only the selector fields; kept in the scratchpad, not committed |
| Evidence V2 files and forward-collector data | **protected / prospective** (sealed-holdout governance, `docs/evidence_v2/OPERATIONS.md`) | not accessed |
| `signals` / `trade_results` history | **protected** (post-freeze history is the sealed holdout) | not accessed |

### Results

**A. Engine-equivalent snapshot** (the current fresh window, 146 rows; 2 open-trade symbols excluded as the engine does):
- **0 eligible** for either selector, so the classification is **AGREE_NO_TRADE** at every slippage scenario.
- S3 reasons: 143 `no_trade_setup`, 3 `stop_rejected`.

**B. Live-decision parity** (the replica versus the engine's own recorded decisions):
- **52/52 symbols** agree.
- 6 per-row differences appear in 3 symbols. They are an **audit-field artifact**: the engine keys `last_decisions` per *symbol* and writes one reason to all of that symbol's timeframe rows, so a timeframe without a setup inherits a sibling's `stop_rejected`. This is an observability defect in `analysis_results.decision_reason`, not a selection difference.

**C. The 28 rows carrying a setup**, analysed 2026-06-26 → 2026-10-16. This is a per-row diagnostic only, **not** a cycle comparison.
- **S3 first reasons:**
  - 19 `stop_rejected:structural_risk_exceeds_cap`;
  - 7 `stop_not_validated`;
  - 2 `bracket_not_ordered`.
- **Liquidity:** known for only 3 of 28 rows.
- **Composition:** 23 are 1d, 3 are 4h, 2 are 15m; 25 are momentum, 3 reversion. No symbol has more than one setup timeframe.
- **Geometry-only cost/R** (n = 26 with a valid bracket, rejected rows included):

  | Slippage (assumption) | Median cost/R | Rows with cost/R > 0.25 | Rows with T1 path net ≤ 0 |
  |---|---|---|---|
  | 0 % | 0.035 | 1 | 1 |
  | 0.05 % | 0.041 | 2 | 1 |
  | 0.10 % | 0.048 | 2 | 1 |
  | 0.20 % | 0.061 | 2 | 1 |

**Conclusion: a real-data selector comparison is NOT yet possible.**
- **Why:** the current operational window contains no eligible candidate, and the eligible history that would be needed lives in protected tables.
- **What it needs:** a meaningful agreement measurement requires shadow records accumulated across many live cycles, which means shadow wiring with owner approval. Repeated read-only snapshots would amount to a forward capture, which is also an owner decision.
- **No synthetic number is presented as real evidence.**
