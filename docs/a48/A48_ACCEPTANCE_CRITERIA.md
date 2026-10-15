# A48 — Acceptance Criteria

These criteria were declared **before** two runs:
- the expanded real-tracker parity run (Phase E);
- the final regression run.

They are committed ahead of both runs and must not be changed after any result is seen. A result that fails a criterion is reported as a failure.

**Evidence levels:**

| Level | Name | Established by A48? |
|---|---|---|
| 1 | Mathematical correctness | Yes, if the criteria hold |
| 2 | Paper-tracker fidelity | Yes, if the criteria hold |
| 3 | Exchange realism | **No.** It needs market-microstructure evidence and real execution evidence. |

## Scenario classification (Phase E)

Every Phase E scenario receives exactly one class.

| Class | Meaning |
|---|---|
| `SUPPORTED_MATCH` | The tracker supports the behaviour, and Mode 2 equals the real tracker on every compared field. |
| `SUPPORTED_MISMATCH` | The tracker supports the behaviour, but at least one field differs. **Acceptance requires zero.** |
| `UNSUPPORTED_BY_TRACKER` | The tracker has no such behaviour, so no matching behaviour is invented. |
| `NOT_APPLICABLE` | The scenario cannot arise for this tracker. |
| `TRACKER_UNSAFE_INPUT` | The real tracker accepts an input that Mode 2 rejects (fail closed). Reported as a finding. Production is not changed. |

## Criteria

**AC1 — Tracker fidelity.** For every supported scenario, Mode 2 (`tracker_event_v1`) equals the real tracker on the following fields:

| Field | Required agreement |
|---|---|
| Admission outcome (opened / rejected / not filled) | Exact |
| Entry fill price | Exact |
| Exit reason (`trade_results.notes`) | Exact |
| Every target-tranche row (target, fraction, price) | Exact |
| `profit_percent`, `profit_usdt` | Within 1e-4, the stored 4-decimal rounding |
| `target_reached`, `stop_hit` | Exact |
| Weighted `exit_price` | Within 1e-8 relative |
| A38 `cost_usdt`, `net_profit_usdt`, `economic_result` | Exact at stored precision |

The number of `SUPPORTED_MISMATCH` scenarios must be 0.

**AC2 — Accounting identities.** On every ledger built in the tests, the following must hold to ≤ 1e-9 USDT:
- execution-price P&L = gross price P&L − execution slippage;
- net = gross − (fees + spread + slippage);
- legacy net = net + rounding + fee-basis difference + spread − 0.1 % × notional.

In addition:
- the ledger's legacy net equals the database's `net_profit_usdt`;
- the slippage allowance never appears inside a realized-cost field.

**AC3 — Legacy preserved.**
- `replay_bracket` and `MODEL_VERSION` (`a42-cf-bar-v1`) are unchanged in source.
- All A42 and A47 tests pass without weakening any assertion. The only permitted change is an input whose processing time ran backwards, an impossible input, which A48 now reports as invalid. Its test must assert both the invalid report and the original intent.

**AC4 — Intrabar ambiguity represented.**
- When a bar's range contains both the standing stop and a target, Mode 3 (`ohlc_uncertainty_v1`) reports more than one scenario, or a non-degenerate interval.
- Mode 3 has no single-valued "expected" P&L field.

**AC5 — No silent optimistic stop execution.**
- Every Mode 3 stop exit in a bar whose low is below the stop level carries an interval whose worst end is below its best end.
- **Soundness check:** on every seeded synthetic case where A_OBS_IN_BAR and A_FIRST_OBS_AT_OPEN hold by construction, the Mode 2 outcome on the full observation stream lies inside the Mode 3 scenario set and conditional envelope computed from the bars alone. Pass rate required: 100 %.

**AC6 — No double counting.** With nonzero slippage and a nonzero allowance, `net_modeled_pnl` contains slippage exactly once, and the allowance appears only in `stress_net`.

**AC7 — No production-path change.**
- `git diff` against the A47 HEAD touches only:
  - `shared/execution_calibration.py`;
  - `shared/replay_execution.py`;
  - `tests/`;
  - `docs/`.
- No production module imports an experimental module (registry test).

**AC8 — Regression.**
- Default suite: 0 failed, and passes ≥ 915 plus the new tests.
- Disposable-database runs: 0 failed. These cover:
  - A38 lifecycle;
  - A44 integration and migration;
  - A39 review;
  - A47 parity;
  - A48 parity.

**AC9 — Determinism.**
- Identical inputs give identical outputs.
- The pure modes have no dependence on wall-clock time.
