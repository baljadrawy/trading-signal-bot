# A48 — Replay Fidelity & Cost Accounting Correction

## Verified starting state

| Item | Verified value |
|---|---|
| Production trading source | `59297305`; the tracker's `main.py` and `binance_price_stream.py`, and every `shared/*.py`, are sha256-equal to that checkout |
| Production schema | 9 (read-only query) |
| Collector | `p2f-160-1bfb5f6`; all 5 trading services up and untouched |
| A47 HEAD | `430e9fa`, clean; descends from A46 `c64c77e` |
| Default suite at the A47 HEAD | **915 passed, 0 failed, 799 skipped** (re-run here) |

**Branch:** `feature/a48-replay-fidelity` (worktree `~/tsb-a48-worktree`), created from `430e9fa`. Nothing was pushed, merged or deployed.

**Commits:**

| Commit | Content |
|---|---|
| `a7b21da` | Acceptance criteria, committed **before** the parity and regression runs |
| `92c0553` | Code and pure tests |
| this commit | Parity suite, report and roadmap |

**Evidence levels.** A48 claims **level 1** (mathematical correctness) and **level 2** (Paper-tracker fidelity) only. **Level 3 (exchange realism) is not established.** Nothing here estimates market frequencies or strategy profitability.

## A48-A — Replay fidelity audit

Every discrepancy below was re-derived from the source, not taken from A47.
- **Tracker path:** `trade_tracker/main.py` (A44 tree). Its execution logic is identical to production `59297305`; only the A38 economic-label columns differ.
- **Exit engine:** `shared/triple_barrier.py`, byte-equal to production.

Each entry has a minimal reproduction in `tests/test_a48_replay_fidelity.py`, cited after the description.

### Defects in the A47 tracker model (fixed in Mode 2)

1. **Admission boundary.**
   - **Source:** `register_new_signals` filters on `signal_time > NOW() - INTERVAL '2 hours'`, so it admits only while elapsed time is under 2 h.
   - **Defect:** A47 admitted at exactly 2 h (`>` instead of `>=`).
   - **Repro:** `test_a7`.
   - **Bias:** measure-zero boundary, so negligible.
   - **Status:** *implementation defect*, fixed.
2. **Candle-invalidation exit not modelled.**
   - **Source:** `track_open_trades`. This runs on the REST path only, while `highest_target_hit == 0`. If the last *closed* signal-timeframe candle closed after entry and at or below `stop_invalidation`, it calls `close_trade` at the **current price**. That bypasses `step_barrier`, so **no stop slippage** is applied.
   - **When it is always active:** `stop_invalidation` defaults to the rebased stop, so the check is always armed.
   - **A47 gap:** A47 disabled the path in its parity test and did not model it.
   - **Repro:** `test_a8`; the real tracker in `invalidation_*`.
   - **Bias:** it can exit earlier than a stop would. Through a gap, it books the observed price, not price × 0.999, so it is 0.1 % *better* than the same gap booked as a stop.
   - **Status:** *tracker behaviour*, now modelled.
3. **Stream deduplication not modelled.**
   - **Source:** `BinancePriceStream._handle` drops any aggTrade whose id is not greater than the last id seen. Duplicates *and* out-of-order stream events are therefore dropped, not reordered. An older tick that crossed the stop is ignored (DB scenario `ws_older_stop_crossing_ignored`).
   - **Repro:** `test_a9` runs the real class.
   - **Status:** *tracker behaviour*, now modelled.
4. **Entry is REST-only.**
   - **Source:** `register_new_signals` uses `get_current_price`. Stream ticks before the fill cannot fill.
   - **Repro:** `test_a12`.
   - **Status:** modelled.
5. **Entry price stored at 8 decimals.**
   - **Source:** `rebase_long_bracket` rounds the stored entry to 8 dp, and all P&L uses the stored value.
   - **Defect:** A47 reported the raw observation.
   - **How it was found:** this was the **only** mismatch in the first parity run (`price_rounding_exact_levels`).
   - **Status:** *implementation defect*, fixed. The raw observation is kept in `diagnostics`.
   - **Subtlety:** the tracker rebases `stop_invalidation` with the **raw** fill, and the model mirrors that.

### Replay vs tracker: intentional model differences

| # | Discrepancy | Source | Repro | Mechanism / bias | Disappears when |
|---|---|---|---|---|---|
| 6 | **Stop overshoot** | `step_barrier`: `min(stop, stop_observation_price)`. Tracker passes the poll price; replay passes `None` (level) | `test_a1`, `test_f5` | Replay fills at the level, tracker at the first poll beyond it. **Replay optimistic by exactly overshoot × 0.999** | The observation lands exactly on the level |
| 7 | **Gap at bar open** | Replay: `gap = b.open` | `test_a5` | Replay fills at the open; tracker at its first observation, which is ≤ open. Replay optimistic or equal | The first observation is the open |
| 8 | **Entry on touch** | `observed_price_v0` vs replay `b.low < planned` | `test_a3` | Tracker fills on a touch at the observed price; replay needs a strict trade-through. Direction depends on the path | — |
| 9 | **Expiry timing** | wall-clock `hours_open` | `test_a4` | Tracker expires at the first poll after the deadline, at that price; replay at the bar close | The poll falls on the bar close |
| 10 | **Arrival order** | no reordering; REST has no sequence id | `test_a6` | Older REST observations are applied as current. Diagnostic only | Observations arrive in order |
| 11 | **Stop-first in shared bars** | `step_barrier` step 1 | grid flips | When a target touch and the stop share one bar, replay books the **original stop**. The tracker may have seen the target first. **Here the replay is pessimistic** (up to +3.5 pp gross for the tracker, synthetic) | The bars are finer than the poll gaps |
| 12 | **Partial-exit accounting** | `fills_between` / `aggregate_close` | `test_f4`, DB | Identical functions in both. **No discrepancy.** | — |
| 13 | **Flat 0.30 %** | `config.FEE_ROUNDTRIP_PCT` | `test_d2` | Equals 0.2 % fee + 0.1 % slippage allowance. With stop fills × (1 − 0.1 %), slippage is charged twice on stop exits. Conservative; unchanged | Target-only exits (allowance is a pure cushion) |

### Tracker input-safety finding

| Class | Finding |
|---|---|
| **TRACKER_UNSAFE_INPUT** (finding only; production unchanged) | A **NaN** price reaching an expiry poll is booked. The real tracker writes a `trade_results` row with **NaN** P&L, `economic_result = BREAKEVEN` (`test_nan_price_is_unsafe_input_for_the_tracker`). |

- **How NaN gets in:** `get_current_price` only checks for a falsy value. The stream checks `price <= 0`, which NaN passes.
- **Practical reach:** Binance does not send NaN, so this is unreachable under valid exchange data.
- **Model behaviour:** Mode 2 refuses non-finite input (fails closed).
- **Next step:** a one-line production guard is recommended for owner review. It is **not** applied here.

## A48-B — Versioned replay execution layer (`shared/replay_execution.py`, `a48-rx-v1`)

| Mode | Model version | Input | Stop fill | Role |
|---|---|---|---|---|
| `legacy_bar_v1` | `a42-cf-bar-v1` (**unchanged source**) | OHLC | level, or the bar open on a gap, × (1 − s) | regression comparison only |
| `tracker_event_v1` | `a48-tev-v1` | ordered `Poll`s | first observed price at or below the stop × (1 − s) | Paper-tracker reference, **not exchange truth** |
| `ohlc_uncertainty_v1` | `a48-ohlc-v1` | OHLC | interval [bar low, min(stop, open)] × (1 − s), **conditional** | research default for bar data |

`replay(mode, …)` dispatches and fails closed on unknown modes. `resting_limit_v1` is not a replay mode. No mode can be activated in production, because the isolation registry includes `replay_execution`.

**Mode 2** extends A47's `tracker_poll_model` rather than duplicating it. A `Poll` carries:
- `t_ms`: processing time, the tracker's clock;
- `source`: REST, websocket or restart;
- optionally `agg_id`, `observed_ms` (diagnostics only) and the last closed candle.

Mode 2 reports these impossible sequences rather than repairing them:
- processing time running backwards;
- an observation after its processing time;
- a websocket tick without an id;
- an incomplete candle, or one from the future;
- an unknown source;
- non-finite values.

It counts, without changing any decision:
- stale observations (> 60 s);
- out-of-order observations;
- missing prices;
- dropped stream ticks;
- restarts.

**Mode 3** enumerates feasible paths without assuming an intrabar order:
- **Waypoint search.** Each bar is explored as moves between turning points: the bar extremes plus the bracket levels inside the bar's range. This search found a path that both extreme orders (O-L-H-C and O-H-L-C) miss: T1, then back to break-even *above* the bar low (`test_c8`). That was a real miss in the first draft, surfaced by the soundness check.
- **Path-order and fill-price uncertainty are separate.** Each scenario's `path` lists the waypoint sequence for the bars whose path changed the outcome. Each terminal leg carries a `(worst, best)` fill interval, and each scenario a gross interval.
- **Entry-fill regions.** A limit entry that fills inside its bar can do so anywhere in [max(low, rejection), plan]. Every level is rebased by fill / plan, so reachability changes only at breakpoints, which are enumerated; each region is evaluated along its own path.
- **Fill timing.** Both ends of the fill-time range inside the bar are evaluated.
- **Expiry.** Within the deadline bar the exit price is the bar's [low, high] interval.
- **Invalidation.** It is modelled only from signal-timeframe bars. Otherwise the result is `INSUFFICIENT_INFORMATION`.
- **No point estimate.** There is no single "expected" P&L field. The worst end is labelled `conditional_stress_gross_pct`.
- **Assumptions are named and attached to every scenario** (`ASSUMPTIONS`):

| Assumption | Meaning |
|---|---|
| A_FIRST_OBS_AT_OPEN | the first entry observation is the first bar's open |
| A_OBS_IN_BAR | at least one observation falls inside the crossing bar; **without it no bound exists**, and the bar low is never treated as an unconditional bound |
| A_LEVEL_WAYPOINTS | the waypoint search spans every intrabar outcome |
| A_TARGET_TOUCH | a target fills when the bar high reaches it |
| A_EXPIRY_IN_BAR | an expiry inside a bar exits within that bar's [low, high] |
| A_FILL_TIME_IN_BAR | a limit fill can happen at any time inside its bar |

**Statuses:** `DETERMINED`, `FILL_PRICE_UNCERTAIN`, `PATH_AMBIGUOUS`, `INSUFFICIENT_INFORMATION`, plus `rejected`, `not_filled` and `invalid`. `INSUFFICIENT_INFORMATION` is returned when:
- the bars end before the exit;
- the entry-fill breakpoints exceed the cap (32);
- the branch or state cap is exceeded;
- invalidation is requested on non-signal-timeframe bars.

## A48-C — Cost accounting reconciliation (`a48-cost-v1`, `execution_calibration.cost_ledger`)

**Convention:**
- Each leg has a *reference* price (observed or level) and an *execution* price (after modelled deterioration).
- **Slippage is a realized cost exactly once, inside the execution price.**
- The 0.1 % allowance is a **stress adjustment**, never a realized cost.

**Fields:**

| # | Field | Definition |
|---|---|---|
| 1 | `gross_price_pnl_usdt` | Σ q·ref − Q·ref_entry |
| 2 | `explicit_fees_usdt` | 0.10 %/side × **executed** notional of every leg (no BNB discount) |
| 3 | `spread_cost_usdt` | half-spread × taker-leg notional (0 when not modelled) |
| 4 | `execution_slippage_usdt` | Σ q·(ref − exec) |
| 5 | `total_modeled_costs_usdt` | 2 + 3 + 4 |
| 6 | `net_modeled_pnl_usdt` | 1 − 5 |
| 7 | `stress_allowance_usdt` and `stress_net_usdt` | the 0.1 % allowance and net − allowance |
| 8 | `legacy_tracker_net_usdt` and `legacy_economic_result` | A38 `economic_close`, reproduced exactly |

**Identities (tested to ≤ 1e-9 USDT):**
- `execution_price_pnl = gross − slippage`, which equals the tracker's stored gross;
- `legacy_net = net_modeled + legacy_rounding + (fees − 0.2 %·N) + spread − 0.1 %·N`.

**Double counting:**
- `double_counted_slippage_usdt` exists **only** in the legacy convention.
- On a 96.0 overshoot fill, slippage counts once as realized (0.048 USDT inside the price), and the legacy flat convention charges another 0.05.

**Quantities:**
- **Unsold quantity** (dust or rejected tranches) is reported as inventory marked at the last reference price, **not** as a cost.
- **Overselling** raises an error.

**Legacy compatibility:** the ledger's legacy fields equal the database's `cost_usdt`, `net_profit_usdt` and `economic_result` on every closed parity scenario. Its fee and gross values equal the A46 per-leg ledger. Historical and production labels are untouched.

## A48-D — Expanded real-tracker parity (`tests/test_a48_tracker_parity_db.py`)

**Method:**
- The **real** code paths are driven on a disposable PostgreSQL 16.15 instance (image `721873c34ceb`, tmpfs, bound to 127.0.0.1, removed afterwards):
  - `track_open_trades`;
  - the main-loop delivery section, including `register_new_signals`;
  - a real `BinancePriceStream._handle` feeding `handle_stream_price`;
  - restarts (a fresh stream instance and cleared module state).
- The tracker's clock is moved by shifting `signal_time` and `opened_at`.
- Every AC1 field is compared:
  - admission outcome and terminality;
  - entry fill;
  - every tranche row;
  - reason;
  - gross % and gross USDT;
  - `target_reached` and `stop_hit`;
  - weighted exit;
  - the A38 label.

**Result: 27 / 27 supported scenarios are `SUPPORTED_MATCH`; `SUPPORTED_MISMATCH` = 0.**

| Group | Scenarios |
|---|---|
| Entry | market fill · rejected below stop · touch at the limit · skipped by a gap · admission expiry · restart before entry |
| Stops | exact · overshoot · large gap · repeated observations · missing prices skipped |
| Targets | T1 → break-even · T1/T2/T3 progression · T1 + T2 in one poll → trailing · T1 + T2 + T3 in one poll |
| Expiry | no-T1 · T1 · delayed processing |
| Stream | duplicate and older ids dropped · older stop-crossing tick ignored · restart after a partial exit |
| Invalidation | REST candle close · not checked on the stream · through a gap (no slippage) · candle before entry ignored |
| Other | momentum setup · price rounding at exact rebased levels · min-notional merge into T2 (remaining 0) |

**Classified, not matched:**

| Scenario | Class | Reason |
|---|---|---|
| exchange partial fills | `UNSUPPORTED_BY_TRACKER` | full-size fills only |
| quantity step rounding | `UNSUPPORTED_BY_TRACKER` | notional positions; covered by `exchange_rules` |
| session or trading-hour limits | `NOT_APPLICABLE` | none exist; the only `weekday` use is weekly risk |
| NaN price | `TRACKER_UNSAFE_INPUT` | see A48-A |

**Transparency on the run history:**
- **First run:** exactly one mismatch, defect A-5 (`price_rounding_exact_levels`, fill reported raw rather than at 8 dp). It was fixed in Mode 2's implementation, not in the comparison.
- **Fixture corrections:** three prices were corrected so each scenario reaches the exit its name declares:
  - momentum stop 96.4 → 95.9;
  - min-notional trailing exit 101.8 → 101.4;
  - the rounding fixture's break-even poll was computed from the stored entry.

  These changes touched the scenario-semantics pin, not the parity comparison, and parity held both before and after each correction.
- **A47's 6 parity paths** still pass.

## A48-E — Synthetic bias assessment (`replay_execution.bias_grid`)

**Setup:**
- 135 deterministic rows: stop distance {1, 2, 4} % × poll interval {1, 5, 30, 60, 300} s × gap {0, 0.25, 1} % × state {0: full position, 1: after T1 (0.75 remaining), 2: after T2 (0.25 remaining)}.
- **Declared synthetic speed:** 0.01 %/s, with the first post-crossing poll mid-interval. **This is not a market estimate.**
- **Comparison:** tracker-equivalent (Mode 2) vs legacy (Mode 1) on the same path.
- **Units:** bps of the stop level, percentage points (pp) of notional, USDT on 50 USDT notional.

**Results:**
- **Inside Mode 3:** 135/135 tracker outcomes lie inside the conditional envelope.
- **Same exit reason (127 rows):** legacy is optimistic in **127/127**.
  - Fill difference = −(speed × ½ poll + gap) × 0.999, essentially independent of stop distance.
  - Gross difference scales with the remaining fraction.
  - Example, gap 0, full position: −0.50 bps / −0.005 pp at 1 s; −15.3 bps / −0.150 pp at 30 s; −30.6 bps / −0.300 pp at 60 s; −153 bps / −1.50 pp at 300 s.
  - Largest same-reason gross difference: 2.49 pp (300 s, 1 % gap).
- **Different exit reason (8 rows, all 300 s polling):** a target touch and the stop share a 15-minute bar, and legacy books the original stop or break-even (stop-first). The tracker is then usually *better*, by up to +3.5 pp; one row is −0.35 pp. **Bias direction is therefore not uniform.**
- **Economic-label differences (24 rows):** mostly break-even exits after T1 with a gap, which legacy labels WIN and the tracker LOSS. In one trailing case the reverse holds.
- **Exit timing:** the tracker exits ½ poll interval after the crossing. Legacy resolves at the bar close and has no intrabar timestamp.

Detailed rows at 2 % stop distance:

| poll | gap | state (rem) | reasons T/L | fill diff bps | gross diff pp | net diff USDT | label T/L | M3 envelope pp |
|---|---|---|---|---|---|---|---|---|
| 1 s | 0 % | 0 (1.0) | stop/stop | −0.51 | −0.0050 | −0.0025 | LOSS/LOSS | [−2.103, −2.098] |
| 30 s | 0 % | 0 (1.0) | stop/stop | −15.29 | −0.1498 | −0.0749 | LOSS/LOSS | [−2.248, −2.098] |
| 30 s | 1 % | 1 (0.75) | BE/BE | −114.83 | −0.8646 | −0.4319 | LOSS/WIN | [−0.240, 0.625] |
| 60 s | 0.25 % | 1 (0.75) | BE/BE | −54.83 | −0.4128 | −0.2062 | LOSS/WIN | [0.212, 0.625] |
| 300 s | 0 % | 2 (0.25) | trail/trail | −147.49 | −0.3746 | −0.1871 | WIN/WIN | [0.325, 2.375] |
| 300 s | 1 % | 1 (0.75) | BE/**stop** | −10.31 | **+0.8469** | +0.4230 | LOSS/LOSS | [−2.201, 0.625] |

**Limitations:**
- Synthetic paths with one speed only.
- No order-book data, queueing or partial fills.
- The real tracker's poll cadence (REST every 30 s, plus a stream of variable latency) is **not measured**.
- These rows say how the *models* differ, not how often anything happens.
- **Correcting the replay's optimism demonstrates nothing about any strategy's profitability.**

## A48-F — Regression evidence

**Acceptance criteria:** `docs/a48/A48_ACCEPTANCE_CRITERIA.md`, committed at `a7b21da` before the runs.

**Runs:**

| Run | Passed | Failed | Skipped |
|---|---|---|---|
| Default suite (final tree) | **958** | 0 | 828 |
| Disposable-DB suites: A38 lifecycle, A44 integration, A44 migration, A39 review, A47 parity, A48 parity | 79 | 0 | 2 |
| A39 review with `P1_BEFORE_TREE=~/tsb-a38-base` (clears both skips) | 10/10 | 0 | 0 |
| A48 pure tests | 43/43 | 0 | 0 |
| A42 + A47 pure tests | pass, unchanged except the permitted A47 input | 0 | — |

**Properties (fixed seeds):**
- **Soundness (AC5):** 0 misses across 900 exploratory cases and the tested 2 × 40.
- **Widening, 15 m → 1 h:** 151/151 in exploration plus the tested subset.
- Determinism, no wall-clock imports, and quantity conservation.

**Bugs found and fixed by these checks before acceptance:**
1. The two-extreme-order assumption was false (A_LEVEL_WAYPOINTS replaces it).
2. In-bar entry-fill interiors were missing (breakpoint regions added).
3. The invalidation-first branch at the bar open was missing.
4. A rebased stop was misread as a gap because of 8-dp rounding.
5. The synthetic generator landed a poll exactly on the level.

**AC status:**

| Criterion | Status |
|---|---|
| AC1 | met: 27/27 match, 0 mismatches |
| AC2 | met |
| AC3 | met: `counterfactual_barrier.py` is untouched; the A47 test change is the permitted impossible input |
| AC4 | met |
| AC5 | met |
| AC6 | met |
| AC7 | met: see the diff list in the appendix |
| AC8 | met: default 958 / 0 / 828; DB 81 / 0 / 0 |
| AC9 | met |

**Coverage gaps:** no real market data; no measured poll cadence or latency; no exchange partial fills or queueing; no live filter values; spread is a parameter, not a measurement.

## A48-G — Roadmap update

`docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md` has an A48 progress-log section and an updated S5 prerequisite.

## A48-H — Decision: **READY FOR SCIENTIFIC DESIGN REVIEW**

**Evidence:**
- All pre-declared acceptance criteria are met.
- **Tracker fidelity (level 2)** is exact on 27/27 supported real-tracker scenarios, with 0 unexplained differences.
- **The legacy replay's stop optimism is eliminated from the research default:**
  - Mode 2 reproduces the tracker exactly when observations are available.
  - Mode 3 never reports the optimistic level fill as the result. Its intervals are conditional, its assumptions named, and it says `INSUFFICIENT_INFORMATION` rather than inventing precision.
- **Costs are separated without double counting**, and legacy labels are reproduced exactly.

**What the design review must decide.** These are not engineering defects:
1. **Which input route for counterfactuals:**
   - Mode 2 needs recorded observation streams for non-selected candidates, which requires owner approval of a forward capture;
   - Mode 3 on bars yields conditional intervals whose width, often several tenths of a percentage point per trade, may exceed the drafted effect sizes. Those effect sizes are already at or below their MDE (A42/A44/A45/A46).
2. **Whether A_OBS_IN_BAR may be assumed** without a measured poll cadence. Level 3 needs that measurement.
3. **How to treat the conditional stress end** in any protocol. It must never be presented as an expected value.

**Not recommended:** no new admission, no activation, and no change to production accounting. The FWER budget, α = 1/240 and the 365-day horizon are unchanged.

**Owner items surfaced:**
- the NaN guard (latent production defect);
- the forward observation capture needed for level 3.

## Appendix — final regression and diff

**Default suite** (`python -m pytest -q tests`, final tree): **958 passed, 0 failed, 828 skipped**, 46 subtests passed.
- The A47 baseline was 915 / 0 / 799.
- **+43** are the A48 pure tests.
- **+29** skips are the DSN-gated module `test_a48_tracker_parity_db.py`: its 27 scenarios, the scenario-semantics pin and the NaN probe.

**Disposable-DB run** (A38 lifecycle, A44 integration, A44 migration, A39 review with `P1_BEFORE_TREE=~/tsb-a38-base`, A47 parity, A48 parity): **81 passed, 0 failed, 0 skipped**.

**Diff against the A47 HEAD `430e9fa`** (AC7): only these files:
- `shared/execution_calibration.py`;
- `shared/replay_execution.py` (new);
- `tests/experimental_modules.py`;
- `tests/test_a47_execution_realism.py` (the permitted impossible-input re-expression);
- `tests/test_a48_replay_fidelity.py`;
- `tests/test_a48_tracker_parity_db.py`;
- `docs/a48/*`;
- `docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md`.

No production module, migration, compose file or image was touched. `shared/counterfactual_barrier.py` is unchanged.

**Cleanup:** the test container `tsb-a48-testpg` was removed and its password file deleted. All 5 production trading services and the collector remained up and untouched throughout.
