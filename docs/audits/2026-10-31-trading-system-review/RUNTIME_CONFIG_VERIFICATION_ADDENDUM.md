# Runtime Configuration Verification — Addendum to the 2026-10-31 Audit

> **Status: new, owner-authorized READ-ONLY observations. They add to the published audit package; they do not replace any part of it.**
> - The seven original documents of this package are unchanged. Where this addendum resolves or contradicts an original finding, it cites that finding's ID.
> - No file, setting, database record, container or Paper Trading state was changed.
> - This addendum is not a profitability certification.

## 1. Scope and exact authorization

**Authorized by the owner on 2026-10-31.** A narrowly scoped, read-only verification of:
- non-secret runtime configuration;
- non-protected database settings;
- runtime flags, indicator weights and calibration precedence;
- non-sensitive pause and risk-control status.

The results are compared with the published audit.

**Not authorized, and not done:**
- modifying files, settings, database records or application state;
- restarts or deployments;
- activating trading, learning or optimization;
- backtests or simulations;
- reading sealed holdouts, protected research outcomes, trade-level records or post-freeze Paper results;
- printing credentials or raw environment dumps;
- running application code.

**Access methods used:**

| Method | Classification | How it was constrained |
|---|---|---|
| `docker ps` and `docker inspect` | Class A in `docs/ops/COMPOSE_OPERATIONS.md` | The container environment never reached the terminal. It was piped through an exact-name allow-list filter; keys matching credential or connection patterns were never printed, and any value not shaped like a plain configuration value would have been withheld. |
| Database reads | Narrowly scoped `SELECT` statements | One `BEGIN TRANSACTION READ ONLY` session, confirmed `transaction_read_only = on`, ended with `ROLLBACK`. Explicit columns only, row limits, no `SELECT *`. Schema metadata (`information_schema.columns`) was read first, and outcome-derived columns were excluded. |
| Collector health | Health metadata only | Read the `state` field and file age of the collector's health file, plus incident severities and reason identifiers. Counters, streams, universe and dataset content were not read. |
| Source code | Read-only `git show` at the documented-deployed commits | Used to interpret the observed values. No application code was executed. |

**Tables:**
- **Not queried:** trade results, signals, research outcomes, forward holdouts, protected partitions, `learning_runs`.
- **Columns deliberately excluded:**

  | Table | Columns not read |
  |---|---|
  | `indicator_weights` | `total_signals`, `successful_signals`, `success_rate` |
  | `learned_gates` | `n`, `wr`, `expectancy`, `ci_low`, `ci_high`, `sample_start`, `sample_end` |
  | `risk_management` | `signals_sent`, `wins`, `losses`, `consecutive_losses`, `daily_pnl_percent`, and every date |
  | `symbol_blacklist` | `reason` |

## 2. Observation date and source versions

**Observation window.** 2026-10-31, about 19:23Z to 20:30Z. This is about five hours after the original runtime samples at 13:59Z and 14:05Z.

**Container identity re-checked.** It is unchanged from the audit (`RT-09`): the same images, start times and restart counts (0).

| Container | Image Id | Started |
|---|---|---|
| trading_analyzer | 011f99ba451b | 2026-10-19 15:20Z |
| trading_scanner | 63b38e7a659d | 2026-10-19 15:20Z |
| trading_signal_engine | c5be4e34c064 | 2026-10-19 15:20Z |
| trading_telegram | d665388a9092 | 2026-10-27 11:51Z |
| trading_tracker | 8e609ca84740 | 2026-10-27 10:56Z |
| trading_continuous_learner | — | Exited (143), unchanged |

**Compose file.** The host Compose file is still blob `d1a4b197`, equal to `main` `eba90dd` (`RT-24`).

**Source used to interpret values:**
- `shared/config.py` at `ea8ae4f` (analyzer, signal_engine) and at `bb7825f` (telegram, trade_tracker);
- the scanner configuration blob `c5c03b5c`;
- `shared/trading_state.py`, identical at `ea8ae4f` and `bb7825f`;
- `shared/triple_barrier.py` at `bb7825f`;
- `p2_forward/Dockerfile` at `72c0bee`.

**Evidence classes.** The classes are those of the package [README.md](README.md).

| What | Class | Why |
|---|---|---|
| Values read from container metadata or the database | `RUNTIME_VERIFIED` | Point-in-time observations |
| Their effect on decisions | `SOURCE_VERIFIED` | Read at the documented commits |
| Image content parity | `DOCUMENTED_ONLY` | Unchanged from `RT-16` and `RT-17`, so effects remain inferences about the running processes |

## 3. Effective runtime flag matrix

**How the values were read.** "Effective" means the value present in the container environment (`Config.Env`) at observation. When a key is absent, the code default applies.

**Sources:**
- **Compose literal:** written in the Compose `environment:` block.
- **Compose interpolation:** `${VAR:-default}` in the Compose file.
- **`.env`:** delivered through `env_file`. This covers any key present in the container but not set in Compose.
- **Code default:** the key is absent.

The same values were observed in all five bot services unless stated otherwise.

| ID · class | Setting | Effective value | Source | Services | Agrees with the audit? |
|---|---|---|---|---|---|
| VER-01 · RUNTIME_VERIFIED | `LIVE_LEARNING_MODE` | `true` | `.env` | all five, and the stopped learner | Yes. Resolves `STR-04`, confirms `STR-02` and `STR-03`. |
| VER-02 · RUNTIME_VERIFIED | `SIGNAL_INTEGRITY_MODE` | unset → code default `off` | code default (`shared/config.py:118` @ ea8ae4f) | all | Yes. Resolves `STR-34`'s NOT VERIFIED. |
| VER-03 · RUNTIME_VERIFIED | `LEARNING_GATES_ENABLED` | `false` | `.env` | all five (unset in the learner container) | Yes. Resolves part of `LRN-20` and `STR-19`. |
| VER-04 · RUNTIME_VERIFIED | `PAPER_ECONOMIC_HALT_MODE` | `observe` in telegram and trade_tracker; unset elsewhere | Compose literal | telegram, trade_tracker | Yes (`RT-32`). The ea8ae4f services have no such setting. |
| VER-05 · RUNTIME_VERIFIED | `T1_CAP_POLICY` | unset everywhere | — | — | Consistent with `STR-17`. The key exists only in bb7825f code, where it would default to `legacy_window_v1`. The analyzer (ea8ae4f) has no such setting, and its T1 cap is hard-coded. |
| VER-06 · RUNTIME_VERIFIED | `TIMEFRAMES` | `15m,4h,1d` (`TIMEFRAME=4h`) | `.env` | all | Yes. Resolves `STR-06`. 1h is not analysed. |
| VER-07 · RUNTIME_VERIFIED | `SCAN_INTERVAL_SECONDS` | `300` | `.env` | all | Yes (`UNI-10`) |
| VER-08 · RUNTIME_VERIFIED | `MIN_VOLUME_USDT` | `10000000` | `.env` | all | Yes (`UNI-10`) |
| VER-09 · RUNTIME_VERIFIED | `MAX_SPREAD_PCT` | unset → code default `0.15` | code default (`shared/config.py:165` @ ea8ae4f) | all | Yes (`IND-03`) |
| VER-10 · RUNTIME_VERIFIED | `PAPER_TRADING` | `true` | `.env` | all | Resolves `RT-31` |
| VER-11 · RUNTIME_VERIFIED | `PAPER_ENTRY_FILL_MODEL` | unset → code default `observed_price_v0` | code default (`shared/config.py:112` @ bb7825f) | trade_tracker | Resolves `EXE-08` |
| VER-12 · RUNTIME_VERIFIED | `RISK_CANARY_MAX_OPEN_TRADES` / `MAX_OPEN_TRADES` | `2` / unset → `10` | `.env` / code default | all | Resolves `EXE-03` and `CON-16`: effective capacity min(10, 2) = 2 |
| VER-13 · RUNTIME_VERIFIED | `APP_VERSION` | `sb-2026.08` | Compose interpolation `${APP_VERSION:-sb-2026.08}` | all | Resolves `CAL-10`. Whether `.env` sets it or the Compose default applies is not distinguishable, since both give the same value. |
| VER-14 · RUNTIME_VERIFIED | `LEARN_CRON_HOURS` | `24` | `.env` | all five and the stopped learner | **New.** The audit states the code default of 12 h (`LRN-03`); the configured value is 24 h. See §9. |
| VER-15 · RUNTIME_VERIFIED | `LEARNING_CLEAN_START` / `LEARNING_CONFIDENCE_Z` / `LEARNING_EXPLORATION_RATE` | 2026-07-20 at midnight UTC / `1.96` / `0.10` | Compose interpolation (signal_engine, learner) | signal_engine, learner | Yes. They equal the code defaults (`LRN-06`, `LRN-07`). |
| VER-16 · RUNTIME_VERIFIED | Legacy-path settings `MIN_SCORE_TO_SIGNAL` / `MIN_TIMEFRAME_CONFIRMATIONS` / `MAX_SIGNALS_PER_DAY` / `GLOBAL_LOSS_COOLDOWN_HOURS` | `7` / `1` / `0` / `0` | `.env` | all | Yes. They equal the 2026-09-27 snapshot (`IND-04`, `IND-05`, `STR-16`). |
| VER-17 · RUNTIME_VERIFIED | Risk settings `TRADE_AMOUNT_USDT`, `RISK_CAPITAL_USDT`, `MAX_DAILY_LOSS_PERCENT`, `MAX_WEEKLY_LOSS_PERCENT`, `MAX_DRAWDOWN_PERCENT`, `MAX_GROSS_EXPOSURE_PERCENT`, `MAX_SYMBOL_EXPOSURE_PERCENT`, `MAX_STRATEGY_EXPOSURE_PERCENT`, `MAX_REGIME_EXPOSURE_PERCENT`, `STOP_ON_CONSECUTIVE_LOSSES` | 50, 500, 3, 10, 15, 80, 10, 40, 50, 7 | `.env` (set explicitly; all equal the code defaults) | all | Yes (`EXE-12`, `RSK-01`) |
| VER-18 · RUNTIME_VERIFIED | Strategy parameters `MOM_BREAKOUT_N`, `MOM_VOL_MULT`, `REV_RSI`, `REV_BB_MAX_POSITION`, `USDTD_SPIKE_PP`, `MACRO_CACHE_HOURS`, `MACRO_MAX_STALE_HOURS` | unset → 20, 1.2, 35, 0.20, 0.5, 1, 2 | code defaults (`shared/config.py:76-82` @ ea8ae4f) | all | Yes (`STR-07`, `STR-08`, `STR-11`). The live setups run on code defaults. |
| VER-19 · RUNTIME_VERIFIED | Cost settings `FEE_ROUNDTRIP_PCT`, `STOP_SLIPPAGE` | unset → 0.3, 0.001 | code defaults | all | Yes (`EXE-13`) |
| VER-20 · RUNTIME_VERIFIED | Evidence settings `ENABLE_EVIDENCE_RECORDER`, `EVIDENCE_V2_ENABLED`, `EVIDENCE_PHASE_ID` | `true`; `true` (Compose literal; unset, and therefore false, in the scanner); `PhaseB-FixedPolicy-20260817` | `.env` / Compose literal / `.env` | as stated | Yes (`ARC-22`, `ARC-23`). The phase label is new information. |

## 4. Database configuration findings

All database values below are `RUNTIME_VERIFIED`. They were read under the constraints in §1.

**VER-21 · RUNTIME_VERIFIED — `optimizer_settings` (2 rows).**

| Key | Value | Updated |
|---|---|---|
| `min_score_to_signal` | `3.0` | 2026-04-25 |
| `min_timeframe_confirmations` | `2` | 2026-06-07 |

- **Precedence.** On the legacy path only, the DB overrides `.env` (`CAL-01`, `IND-04`, `IND-05`). The legacy path would use `min_score` 3.0 instead of the env value 7, and `min_tf` 2 instead of the env value 1.
- **No live-path effect.** These values do not affect the live path, which is the active one (VER-01).
- **Audit findings.** This confirms the documented DB value 3.0 (`IND-06`), against the `CON-40` alternative of 4.

**VER-22 · RUNTIME_VERIFIED — `indicator_weights` (44 rows: 11 indicators × 4 market conditions).** Configuration columns only.

- **Summary:** 19 weights equal 1.0 and 18 equal 0. The minimum is 0 and the maximum 2.0.
- **Update dates:** last updates fall between 2026-04-22 and 2026-06-19, the date the optimizer was disabled (`LRN-10`). No update after that date.

| Indicator | bearish | bullish | sideways | volatile |
|---|---|---|---|---|
| bollinger | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| btc_trend | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| ema_cross | 0.0000 | 0.0000 | 0.0000 | 1.0000 |
| fibonacci | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| macd | 1.7650 | 0.0000 | 0.0000 | 1.0000 |
| obv | 1.2538 | 0.0000 | 0.0000 | 1.0000 |
| order_book | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| rsi | 1.0000 | 1.0000 | 1.0000 | 0.8490 |
| rsi_divergence | 1.0000 | 1.0000 | 2.0000 | 1.0000 |
| stoch_rsi | 0.2332 | 0.0000 | 1.4176 | 0.0000 |
| volume | 0.4135 | 0.0000 | 0.0000 | 1.0000 |

**Update dates by condition:**
- **bullish:** 2026-05-23, except fibonacci and rsi_divergence (2026-04-27).
- **sideways:** 2026-06-19.
- **bearish and volatile:** 2026-04-22, except fibonacci and rsi_divergence (2026-04-27).

**Points of note:**
- `rsi_divergence` / sideways is 2.0, consistent with the pinned value in `LRN-12`.
- The `order_book` weight is 1.0 everywhere but is never read (`IND-02`).
- The bollinger weight is 0 in three of four conditions.
- MACD, EMA cross, volume, OBV and btc_trend are scored as 0 in the deployed source regardless of weight (`STR-14`). Their stored weights therefore matter only for the indicators that are actually scored: RSI, Bollinger, StochRSI, RSI divergence and Fibonacci.

**VER-23 · RUNTIME_VERIFIED — `learned_gates` (18 rows).** Configuration metadata only.
- **Throttled cells:** exactly 1 cell has weight ≤ 0: `momentum` / `usdtd_flat` / `15m`, `strategy_version` `sb-2026.08`, `learning_run_id` 9.
- **Unthrottled cells:** 9 further cells are `sb-2026.08` (run 9) with weight 1, so 10 cells carry that version in all. Eight cells carry `strategy_version` `pre-statistical-reset`, with no run id and weight 1.0.
- **Dates:** every row was last updated on 2026-08-17. That is the learner's last run, before the research freeze.
- **Application:** with `LEARNING_GATES_ENABLED=false` (VER-03), no gate is applied.

**VER-24 · RUNTIME_VERIFIED — `symbol_blacklist` and `symbol_whitelist`.** Both hold 0 rows.
- This resolves `UNI-06` (blacklist contents) and agrees with `UNI-07` (emptied 2026-05-17).
- No symbol is currently excluded by the blacklist.

**VER-25 · RUNTIME_VERIFIED — pause decision row.** The latest pause/resume decision row was read with the same predicate as `get_pause_state()` (`shared/trading_state.py:21-48`).

| Field | Value |
|---|---|
| `is_trading_paused` | false |
| reason category | `manual_resume` |
| `date_invalid` | false |

By the code's logic this returns "not paused", so the scanner's fail-closed pause gate (`ARC-12`) admits scanning. This resolves the pause part of `RT-46`.

## 5. Effective indicator weights and calibration precedence

| Parameter | Code default | Effective runtime value | DB override | Final decision impact (live path active) | Verified? |
|---|---|---|---|---|---|
| Indicator periods (RSI 14, EMA 20/50/200, BB 20/2σ, ATR 14, StochRSI 14/3/3, ADX 14) | constants | = code | none | **Analyzer indicators**; feed the live triggers | `SOURCE_VERIFIED` (not settable) |
| `MOM_BREAKOUT_N` / `MOM_VOL_MULT` | 20 / 1.2 | 20 / 1.2 (default) | none | **Strategy selection** (momentum entry) | env `RUNTIME_VERIFIED`; effect `SOURCE_VERIFIED` |
| `REV_RSI` / `REV_BB_MAX_POSITION` | 35 / 0.20 | 35 / 0.20 (default) | none | **Strategy selection** (reversion entry) | same as above |
| Regime thresholds (ADX 25/20, ATR% rank 0.75) | constants | = code | none | **Strategy selection** (routing) | `SOURCE_VERIFIED` |
| `USDTD_SPIKE_PP` / `MACRO_MAX_STALE_HOURS` / `MACRO_CACHE_HOURS` | 0.5 / 2 / 1 | defaults | none | **Signal acceptance** (macro veto) | env `RUNTIME_VERIFIED`; effect `SOURCE_VERIFIED` |
| `MAX_SPREAD_PCT` | 0.15 | 0.15 (default) | none | **Signal acceptance** (live spread gate) | same as above |
| `MIN_VOLUME_USDT`, 1% move (constant), `SCAN_INTERVAL_SECONDS` | 10M / 1.0 / 300 | 10M / 1.0 / 300 | none | **Scanner eligibility** | same as above |
| `TIMEFRAMES` | 15m,1h,4h,1d | 15m,4h,1d | none | **Analyzer coverage**; 1h excluded | `RUNTIME_VERIFIED` |
| `indicator_weights` | 1.0 when missing | 44 frozen values (VER-22) | is the DB source | **Ranking only, marginally.** They set `total_score`, which orders timeframes within a symbol in `ORDER BY symbol, total_score DESC LIMIT 200` and decides which rows survive that limit; no live gate uses them (`LRN-16`, `LRN-17`) | values `RUNTIME_VERIFIED`; effect `SOURCE_VERIFIED` |
| `min_score_to_signal` | 5 | env 7 | **3.0** (DB > env, legacy only) | **None on the live path.** The legacy selector is dormant. | `RUNTIME_VERIFIED` |
| `min_timeframe_confirmations` | 2 | env 1 | **2** (DB > env, legacy only) | **None on the live path** | `RUNTIME_VERIFIED` |
| `MAX_SIGNALS_PER_DAY` / `GLOBAL_LOSS_COOLDOWN_HOURS` | 5 / 6 | 0 / 0 | none | **None on the live path** | `RUNTIME_VERIFIED` |
| Stop rule (level − 0.25·ATR vs entry − ATR; caps 2/4/5/3%) | constants | = code | none | **Stop-loss** | `SOURCE_VERIFIED` |
| Targets T1 1R (W3 cap), T2 1.8R, T3 2.2R; `T1_CAP_POLICY` | constants; no switch in ea8ae4f | unset (no effect on ea8ae4f) | none | **Take-profit**; W3 cap remains in the documented-deployed source (`STR-17`, `STR-21`) | `SOURCE_VERIFIED`; env `RUNTIME_VERIFIED` |
| Time stops | 15m 48/24/12 h; 4h 96/48/24 h; 1d 240/120/72 h; other timeframes 48/24/24 h | = code | none | **Exit.** 1h would use the fallback, but 1h is not analysed. | `SOURCE_VERIFIED` (`triple_barrier.py:31-49` @ bb7825f) |
| `TRADE_AMOUNT_USDT` / `RISK_CAPITAL_USDT` | 50 / 500 | 50 / 500 | none | **Position sizing** (fixed notional) | `RUNTIME_VERIFIED` |
| `RISK_CANARY_MAX_OPEN_TRADES` / `MAX_OPEN_TRADES` | 1 / 10 | 2 / 10 | none | **Risk limits** (capacity 2) | `RUNTIME_VERIFIED` |
| Loss and exposure limits | 3 / 10 / 15 / 80 / 10 / 40 / 50 / 7 | same | none | **Risk limits.** In observe mode the four economic checks are recorded only; exposure caps and `invalid_risk_state` block (`RSK-01`). | `RUNTIME_VERIFIED` (values); `SOURCE_VERIFIED` (effect) |
| `FEE_ROUNDTRIP_PCT` / `STOP_SLIPPAGE` | 0.3 / 0.001 | defaults | none | **P&L accounting** (flat 0.30%, about 0.40% on stops; `EXE-15`) | env `RUNTIME_VERIFIED` |
| `LEARNING_GATES_ENABLED` and `learned_gates` | false | false | 18 rows, 1 throttled | **Learning gates: none applied** | `RUNTIME_VERIFIED` |

## 6. Actual strategy activation status

**VER-26 · INFERRED** (from `RUNTIME_VERIFIED` flags and `SOURCE_VERIFIED` code).

**Active decision path:**
- `LIVE_LEARNING_MODE=true` in signal_engine, so `find_best_signal_live` is the selector (`STR-01`).
- The two long-only setups, momentum breakout and RSI/Bollinger reversion, therefore decide entries:
  - they run with code-default parameters (VER-18);
  - they are routed by the per-symbol regime;
  - they are vetoed by the macro gate;
  - they are ranked by execution quality.
- They run on 15m, 4h and 1d.

**Dormant parts.** These have no effect on decisions:
- the legacy score selector and its DB thresholds (VER-21);
- the A43 integrity checks (VER-02);
- the learned gates (VER-03).

**Caveat.** "Active" refers to the configuration and the source documented as deployed. That the images contain that source is still `DOCUMENTED_ONLY` (`RT-16`, `RT-17`).

## 7. Pause and risk status

**VER-25 (repeated).**
- **Trading is not paused:** the latest decision row is a valid `manual_resume`.
- **Observe mode:** economic-loss checks are configured as observe-only in telegram and trade_tracker (VER-04).
- **Withheld:** risk counters and daily P&L were not read (§1).

**VER-27 · RUNTIME_VERIFIED — forward collector health.** Health metadata only.
- **Docker health:** `unhealthy`, with a failing streak of 7,864 consecutive checks at a 30 s interval. That is about 65 hours, so it has been failing continuously since about 2026-10-29. Every recent check exited 1 with empty output.
- **Health check definition:** the check (`p2_forward/Dockerfile:16-17` @ 72c0bee) passes only when the health file is less than 30 s old **and** its state is HEALTHY, STARTING, DISABLED, STOPPING or STOPPED.
- **Health file:** fresh (age about 3 s), with `state` = `DEGRADED`. The container reports unhealthy because of the DEGRADED state, not because of a stale file.
- **Incidents:** 5 latched active incidents: 3 at WARNING and 2 at CRITICAL.
  - One WARNING incident's key is `previous_run_stopped_failed`.
  - The other four incident keys and the two reason strings contain non-identifier text that may name market streams, so they are withheld.
- **Scope of this finding:**
  - The collector is a separate research project, not on the trading path (`ARC-14`).
  - It updates `RT-45` (the cause was unknown) and `CON-05`.
  - The operational root cause of the CRITICAL incidents is still NOT VERIFIED.

## 8. Remaining uncertainties

**VER-28 · NOT_VERIFIED.**

1. **Image content parity** (`RT-17`) remains unverified. A comparison is technically feasible without executing application code, accessing credentials or starting containers:
   - `deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json` holds 238 per-file sha256 fields;
   - `docker cp <container>:<path> -` streams files from a running container's filesystem as a tar, which can be hashed against the manifest.

   It was **not performed**, because `docker cp` is not a listed Class A command. It needs a separate owner decision.
2. **Collector incidents.** The keys of four of the five active incidents, and the root cause of the two CRITICAL incidents.
3. **Learned-gate sample sizes.** Whether the single throttled learned-gate cell meets the runtime query's `n >= MIN_CELL_N` filter. `n` was deliberately not read.
4. **Migration 006.** Its exact application date. Rows labelled `pre-statistical-reset` carry `updated_at` 2026-08-17.
5. **`APP_VERSION` source.** Whether `.env` sets it or the Compose default applies; both give `sb-2026.08`.
6. **Observe code path.** Whether the observe path is actually executed inside telegram and trade_tracker; this depends on image parity.
7. **`.env` changes after creation.** If `.env` was edited after the containers were created, the running processes still hold the values listed here, because they were captured at creation. A future recreate could pick up different values.

## 9. Contradictions with the original audit

**VER-29 · CONTRADICTORY.**
- **`LEARN_CRON_HOURS`.** The audit (`LRN-03`) gives the learner loop as every 12 h, which is the code default. The runtime configuration, including the stopped learner's own environment, sets 24 h. A learner restart would therefore loop every 24 h, not 12 h.
- **`min_score_to_signal` date.** The documented DB value of 3.0 is cited as "set 2026-05-16" (`IND-06`, from `docs/claude/strategy-history.md:8`). The row's `updated_at` is 2026-04-25. The value agrees; the date does not.

**VER-30 · RUNTIME_VERIFIED — values the audit could not verify, now observed.**

| Original ID | Now observed |
|---|---|
| `STR-04` | live path flag `true` |
| `STR-34` | integrity mode off |
| `EXE-03`, `CON-16` | capacity 2 |
| `EXE-08` | fill model `observed_price_v0` |
| `CAL-10` | `APP_VERSION` `sb-2026.08` |
| `RT-31` | `PAPER_TRADING` `true` |
| `UNI-06` | blacklist empty |
| `RT-46` | not paused |
| `LRN-20` | learned gates disabled; 18 rows, 1 throttled |
| `IND-06` | DB `min_score` 3.0 |

All of these agree with the audit's documented or inferred expectations.

**No observation contradicts** the audit's description of the active strategy, its parameters or its risk limits.

## 10. Implications for independent reviewers

**VER-31 · INFERRED.**

1. **The live configuration matches the published rules.** The configuration is the live momentum and reversion path, on code-default parameters and the 15m/4h/1d timeframes. Reviewers can evaluate the rules in [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md) as the configured behaviour. The image-parity caveat still applies.
2. **Legacy thresholds do not drive current decisions.** These are the DB `min_score` 3.0 and `min_tf` 2, and the env `min_score` 7, together with the "4h ban" and stoch>0 narratives. Analyses that attribute current outcomes to them would be mis-specified.
3. **Frozen weights reach decisions only through ranking.** The `indicator_weights` (last updated 2026-06-19, many at 0) influence the live path only through ordering and the `LIMIT 200` truncation. Any study of selection bias should treat them as a fixed, data-mined input.
4. **A dormant switch would change behaviour immediately.** Learned gates are off but non-expiring, with one throttled 15m momentum cell. Setting a single flag would change behaviour with no version boundary (`LRN-19`).
5. **Capacity and costs are now runtime-verified.** Capacity is 2 positions of $50 on $500, so utilisation is at most 20%. The costs are the flat 0.30% model. Any economic interpretation of Paper results must use these settings, together with the owner's cost standard (`ECO-09`).
6. **The degraded collector may limit forward evidence.** The collector has been DEGRADED with CRITICAL incidents since about 2026-10-29. Any forward-data analysis covering that period should first check data completeness. That check is an operational question, not a trading-path issue.
7. **None of this is economic evidence.** No result in this addendum bears on profitability, and no profitability claim is supported.
