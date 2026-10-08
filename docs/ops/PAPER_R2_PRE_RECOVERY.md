# PAPER-R2 — final pre-recovery verification (2026-10-08)

**Status:** read-only verification. **Nothing was executed.** No `/recover_risk`, `/resume`, `/pause` or other
Telegram command was sent. B3, risk settings, code, Compose and the Collector are unchanged.

## Verdict
**GO, conditional.** No technical or safety-critical blocker remains. Recovery may proceed only when:
1. the owner records decisions D-P1 to D-P5 (§6);
2. the fresh pre-command checks in §5.1 pass at command time.

## 1. Verified current state (2026-10-08 10:20–10:30Z; evidence `paper-r2-prerecovery-*`)

| Check | Result | Baseline / reference |
|---|---|---|
| B3 | `2026-10-07\|t\|risk:loss_streak_halt\|30459` | halt review (sealed `f9b08d63…`) |
| Recovery epochs | 2; latest `2026-10-04T15:26:43.497803Z` | PAPER-R1 recovery |
| Open trades | 0 → runbook Case B (needs owner acknowledgement) | — |
| Containers | scanner `891c46fddcf5`, analyzer `938664984ac3`, signal_engine `7c663dc07252`, telegram `91680b909017`, tracker `3f40e244b5c1`; all healthy, RestartCount 0 | `paper-resume-prep-20261004T144030Z/01_prod_pre.txt` |
| Image IDs | `63b38e7a…`, `b9b13d95…`, `80096a98…`, `e5f3096b…`, `698d3173…` | MATCH `IMAGES.md` (P1-D: develop `59297305`; scanner: aiohttp 3.14.3) |
| Compose | blob `3ad35a87…`; all five `config --hash` values equal the running containers' config-hash labels | MATCH |
| Env | `.env` + `.env.binance` digests equal the CR-2 baseline (`env_unchanged=yes`) | MATCH |
| Heartbeats | analyzer 10 s, signal_engine 10 s, telegram 3 s, tracker 21 s, scanner 290 s (tolerance 900); all with 0 errors | within tolerance |
| Halt effectiveness | since 2026-10-07T00:24:47Z: 0 signals, 0 trades opened, 0 results, 0 new risk rows. Last trade id 3663 opened 00:18:43 | effective |

### Code identity: production checkout vs running code (resolved)
- The running `trade_tracker/main.py`, `telegram/main.py`, `shared/risk_epoch.py` and `shared/triple_barrier.py` are
  **byte-identical** to git `59297305`.
- The production checkout `/home/tradmin/trading-signal-bot` sits on branch `integration/research-pipeline` @ `63da7d3`
  with uncommitted changes. `59297305` is not an ancestor of it, and its app files differ.
- No container bind-mounts code from that checkout. The mounts are only logs, models and the evidence directories.
  Runtime code comes solely from the pinned images, and Compose (blob `3ad35a87`) and env match the baseline.
- **Not a blocker.** It is a standing hazard: any build from the production checkout (Class C, forbidden) would ship
  the wrong code. Rollback stays image-ID based.

## 2. Risk controls (verified)
- **Container env (tracker, telegram, scanner):** `PAPER_TRADING=true`, `STOP_ON_CONSECUTIVE_LOSSES=7`,
  `MAX_DAILY_LOSS_PERCENT=3`, `MAX_WEEKLY_LOSS_PERCENT=10`, `MAX_DRAWDOWN_PERCENT=15`,
  `RISK_CANARY_MAX_OPEN_TRADES=2`, `TRADE_AMOUNT_USDT=50`, `RISK_CAPITAL_USDT=500`.
- **Effective open cap:** `MAX_OPEN_TRADES` is not set, so the code default of 10 applies, and
  min(10, 2) = **2**. Observed maximum concurrency was 2.
- **Fees:** net = `profit_usdt − 50×0.3/100` (0.15 USDT) on every trade (`shared/risk_epoch.py`, hash matches).
- **Loss streak:** a trailing run of net < 0, ordered by `exit_time, id`, from the effective epoch. It fired at 7/7.
- **Soft reduce:** at 3 losses (×0.5 → cap 1) and 5 losses (×0.1). It resets on a net-non-negative close.
- **No DB override:** the live `optimizer_settings` hold only signal-side keys.
- **Recorder:** `EVIDENCE_V2_ENABLED=true`. That is the baseline state at PAPER-R1, and the env digests are unchanged.

## 3. October 6 stall implications
- **What happened:** Paper failed closed. Price fetches timed out, the WS outage lasted 87 s and one cycle errored.
  No trade in the loss tail was affected, and every container has had a single boot.
- **Residual risk:** during a provider stall, open-trade stops are evaluated late. The paper fill is then
  min(stop, observed) × 0.999, so the accounting stays honest but the result is worse. This is not safety-critical
  in Paper (no funds).
- **Unresolved and outside Paper:** provider/hypervisor stalls can recur, and there is no time-stamped host
  telemetry. Both are tracked under G5/G6 and S7. **No unresolved safety-critical Paper issue.**

## 4. Documented caveats (confirmed, no history changed)
- **C1 — gross/net.** The trade WIN/LOSS label and `risk_management.wins/losses` use gross P&L; all risk decisions
  use net. In PAPER-R1, 3 "WIN" break-even trades were net losses. PAPER-R2 reports must use the **net** fields.
- **C2 — dead letters vs polling.** A `signal.delivered` dead letter does not make a signal inadmissible. Admission is
  poll-driven (2 h window, with dedup per symbol/timeframe/candle and no same-symbol overlap). Dead letters total 269
  (245 + 24). **No replay**, and no history is changed.

## 5. PAPER-R2 epoch definition
**Purpose:** operational observation of the unchanged system. It is not Alpha evidence, it involves no strategy
tuning, and it does not count toward any live-trading criterion (PAPER_ONLY).

**Configuration:** exactly as verified in §1–2. Nothing changes at recovery.

**Metrics (read-only, at checkpoints):**
- B3 state and admissions;
- rejections by reason;
- open count (≤ 2);
- per-trade fee (= 0.15);
- trade → result pairing (1:1);
- consecutive net losses;
- daily, weekly and drawdown %;
- dead-letter count, split into cap-full deferral vs other;
- heartbeat ages and errors;
- container RestartCount and health;
- host stalls (from the collector monitor).

**Stop conditions:** each requires owner review. There is no automatic recovery.
1. Any hard risk halt fires: loss streak 7, daily 3 %, weekly 10 % or drawdown 15 %. Stay halted.
2. Any admission rule violation: more than 2 open, a same-symbol overlap, an admission while halted or paused, or a
   duplicate signal admitted twice.
3. Any accounting mismatch: fee ≠ 0.15, a trade without a result or the reverse, or a non-reconciling fill.
4. Any change to `PAPER_TRADING`, `EXECUTION_MODE`, risk env, Compose blob or image IDs that is not part of an
   authorised release.
5. A container restart, an unhealthy state, or a heartbeat beyond tolerance for more than 2 consecutive checks;
   DB errors.
6. Dead letters growing for any reason other than cap-full deferral.
7. A host/provider stall over 60 s while trades are open. Review and record; do not halt automatically.

**Checkpoints:** +1 h, +24 h and +72 h after `/resume`, as read-only snapshots, each reusing the PAPER-R1 snapshot
tooling.

### 5.1 Owner-only recovery runbook (PREPARED, NOT EXECUTED)
**A. Fresh pre-command checks.** Run immediately before; all are read-only.
1. B3 = `2026-10-07|t|risk:loss_streak_halt|30459` (no change).
2. `select count(*) from active_trades where status='open'` = 0.
3. The five container IDs, image IDs and config-hash labels equal §1; all healthy; RestartCount 0.
4. Compose blob `3ad35a87…`; `env_unchanged=yes`.
5. Heartbeats within tolerance.
6. Not within ±30 min of a planned infrastructure change.

**B. Owner actions** (Telegram, owner account only, private chat with @Jadrawybot):
1. `/recover_risk <explicit reason>`. Example reason: "Reviewed PAPER-R1 halt (paper-halt-review-20261007T203557Z): halt
   correct, no defect; caveats C1/C2 accepted; PAPER-R2 observation epoch."
   - Expect a reply that confirms a new recovery epoch.
   - If **no reply**, do not retry. Run the read-only routing check first (lesson from 2026-10-04: wrong bot/chat).
2. After the read-only check in C1–C2 passes: `/resume`. Expect the resume reply.

**C. Immediate post-recovery verification** (read-only):
1. `risk_recovery_events` count = 3, the latest epoch timestamp is the DB `NOW()` of the command, and
   `open_positions_at_recovery` = 0.
2. After `/resume`: B3 shows the new row (`…|f|manual_resume|<id>`).
3. Containers unchanged.
4. First admissions within the rules (≤ 2 open, fee 0.15).

**D. Contingency:**
- Unexpected reply or state → stop and do not re-issue. Report.
- After `/recover_risk`, if anything is off before `/resume`: do not resume. The admin pause is still set, so no
  trades are admitted.
- After `/resume`, if a stop condition fires: the owner sends `/pause`. That is an owner action, and the risk
  breakers continue to work regardless.

## 6. Owner decisions required before step B
- D-P1 resume (yes/no);
- D-P2 accept caveat C1 (or fix before resume);
- D-P3 accept caveat C2 with no replay (or schedule the expiry state);
- D-P4 accept the §5 epoch definition and stop conditions;
- D-P5 post-stall control re-validation (optional; not required by this verification).

## 7. Actions that require separate owner authorisation
`/recover_risk <reason>`, `/resume`, `/pause`, any C1/C2 code fix (PR + gated deploy), any Compose/env/image change,
any dead-letter replay (recommended: never), and any change to risk limits.

## 8. Execution record

**Owner decisions:** the owner approved D-P1 through D-P5. Approved decisions:
- D-P1: observation only.
- D-P2: C1 accepted; evaluate on net.
- D-P3: C2 accepted; no replay.
- D-P4: §5 stop conditions and checkpoints adopted.
- D-P5: no heavy tests.

### Phase A — pre-recovery gate: GO (2026-10-08T10:32:29Z)
- **B3:** `2026-10-07|t|risk:loss_streak_halt|30459`. 2 recovery epochs; 0 open trades.
- **Since halt:** 0 admissions, signals or results.
- **Containers:** the five containers, images and config hashes equal the §1 baseline; heartbeats fresh.
- **Code and config:** code matches `59297305`; compose blob `3ad35a87`; `env_unchanged=yes`; risk env unchanged.
- **Telegram:** chat sha8 `61cbda04` (private); bot token sha8 `91aca75b` (@Jadrawybot).
- **Collector:** HEALTHY.

### Owner action
The owner personally sent `/recover_risk <reason>` to @Jadrawybot and received a successful reply. The agent
sent no command.

### Phase B — recovery verification: VERIFIED (2026-10-08T10:45:35Z)
- **Recovery events:** 3 (previously 2). Exactly one row was created after Phase A.
  - id 3, `epoch_started_at` 2026-10-08T10:43:22.323782Z (DB time, after Phase A).
  - Values: `halt_reason=loss_streak_halt`, `open_positions_at_recovery=0`, `consecutive_losses_before=7`.
  - The actor, `acknowledged_by` sha8 `61cbda04`, is the owner.
  - The reason cites PAPER-R2 and the halt review.
- **Effective state:** the loss-streak breaker is cleared by the new epoch (0 closes since epoch 3). The admin pause
  is **still active**: the latest decision row 30459 has `is_trading_paused=true`, and no new `risk_management` row
  exists. B3 therefore still reads the historical row `2026-10-07|t|risk:loss_streak_halt|30459`. That is expected
  until `/resume`, and matches the PAPER-R1 pattern.
- **Admissions:** 0 open trades. Since the halt and since the recovery: 0 trades, 0 signals, 0 results. There was no
  automatic resume.
- **Runtime:** the five containers are unchanged (IDs, images, config-hash labels), all healthy, RestartCount 0.
  Heartbeats ≤ 99 s with 0 errors.
- **Config:** compose blob `3ad35a87`; `env_unchanged=yes`; `PAPER_TRADING=true`; loss streak 7; limits 3/10/15 %;
  open cap 2; stake 50; fee 0.15. Telegram logs since 10:30Z show no error or unauthorised lines.
- **Collector:** `ce4e6b6656a5` HEALTHY with 0 restarts. No conflicting maintenance window.
- **`/resume` validity:** per the runbook, `/recover_risk` lifts the risk breaker and `/resume` lifts the separate
  admin pause. The pause is the only remaining gate.

**Next owner action:** `/resume` in the private chat with @Jadrawybot. Then run the §5.1 C read-only checks and the
+1 h, +24 h and +72 h checkpoints.

### Owner action
The owner personally sent `/resume` to @Jadrawybot and received a successful reply. The agent sent no command.

### Phase C — immediate post-resume verification: PASS (immediate operational); 2026-10-08T10:53:52Z
- **Effective B3:** `2026-10-08|f|manual_resume|30463`.
  - `risk_management` row 30463 holds `is_trading_paused=false` and `pause_reason=manual_resume`, and it is the only
    row after 30459. Ids 30460–30462 are absent: these are sequence gaps (consumed ids with no committed rows). No
    rows were deleted, and the gap has no state effect.
  - Historical halt row 30459 is preserved.
  - Recovery epochs remain exactly **3** (latest id 3). No extra recovery or resume event occurred.
- **Resume timestamp (T0):** `risk_management` has no time column, `track_commit_timestamp` is off, and neither an
  outbox event nor a telegram log line records the resume. T0 is therefore **bounded**:
  - after 10:48:57Z (the scanner still logged "paused: risk:loss_streak_halt");
  - at or before 10:53:52Z (row 30463 present);
  - corroborated by the scanner cycle at 10:53:57Z, which ran unpaused (18 coins eligible).

  T0 for checkpoints = **10:53:52Z** (conservative upper bound). Phase B at 10:45:35Z had confirmed no row then.
- **Hard breakers:** none active. Epoch 3 has no closes, so the streak is 0. No daily, weekly or drawdown halt.
- **Trades:** 0 open, 0 admitted since the recovery, 0 results, 0 signals yet.
  - **The admission path after resume is not yet observed.** It is not claimed as passed.
  - 0 trades without a result in PAPER-R1/R2. Dead letters total 269, with 0 new since recovery and no replay.
- **Runtime:** the five containers are unchanged (IDs, images, config-hash labels), healthy, RestartCount 0.
  Heartbeats ≤ 296 s (scanner tolerance 900) with 0 errors. 0 error-like log lines since 10:40Z in any service.
- **Config:** compose blob `3ad35a87`; `env_unchanged=yes`; `PAPER_TRADING=true`.
  - Unchanged limits: loss streak 7; daily 3 %, weekly 10 %, drawdown 15 %; open cap 2; stake 50; fee 0.15.
  - No live capability.
  - Collector `ce4e6b6656a5` HEALTHY and independent of Paper.
- **Caveats in force:** C1 (gross labels; evaluate on net) and C2 (dead letter ≠ inadmissible; no replay).

### PAPER-R2 checkpoints
These are read-only, run independently later. No waiters or scheduled jobs exist.

| Checkpoint | Time (UTC) | Scope |
|---|---|---|
| T0 + 1 h | 2026-10-08T11:54Z | B3 state; health and restarts; first admissions vs rules (≤ 2 open, no same-symbol, valid signal and risk decision); fee 0.15; trade↔result 1:1 |
| T0 + 24 h | 2026-10-09T10:54Z | stability; net P&L (not gross labels); dead letters by cause; risk events; §5 stop conditions |
| T0 + 72 h | 2026-10-11T10:54Z | stability assessment; continuation recommendation (observation only; no strategy tuning) |

If any hard breaker fires, Paper stays halted. There is no automatic recovery; the owner decides.

### Checkpoint T0 + 1 h: PASS (2026-10-08T12:04:57Z; coverage 10:48:57Z → 12:04:57Z)
- **State:** B3 `2026-10-08|f|manual_resume|30463`, with no new `risk_management` row. Recovery epochs remain 3. No
  recovery, resume or pause transitions, and no breaker fired. 0 open trades.
- **Verification levels:**

  | Level | Status | Evidence |
  |---|---|---|
  | Scanner operational | ✔ | 16 cycles, 0 "paused" messages after 10:53Z, 16–19 eligible symbols per cycle |
  | Signal pipeline | ✔ | 3 signals (15532 MINA, 15533 ORCA, 15534 PUMP, all 15m, `telegram_sent`); outbox `signal.ready` 3 and `signal.delivered` 3, all completed |
  | Admission path | **observed ✔** | 3 trades (3664–3666) opened 20 s after their signals; all after T0; maximum concurrency 2 (ORCA and PUMP, 11:50–11:59); no same-symbol overlap |
  | Full lifecycle | **observed ✔** | 3 `trade.opened` and 3 `trade.closed` completed; 3 results (3619–3621), one per trade, 0 duplicates |

- **Accounting (net is authoritative):**

  | Result | Symbol | Gross USDT | Net USDT | Exit (UTC) | Exit type |
  |---|---|---|---|---|---|
  | 3619 | MINA | −0.9891 | −1.1391 | 11:18:01 | stop |
  | 3620 | PUMP | −0.7107 | −0.8607 | 11:59:01 | stop |
  | 3621 | ORCA | −0.6049 | −0.7549 | 12:00:25 | non-stop, 0.67 h (expiry policy) |

  - Totals: gross −2.3047, fees 0.45 (0.15 × 3), net **−2.7547**.
  - Epoch-3 streak: **3 consecutive net losses** (limit 7). The soft-reduce threshold (≥ 3) is now reached, by design
    (cap 1 for new admissions).
  - Daily net ≈ −0.55 % of 500 (limit 3 %). No weekly or drawdown breach.
- **Controls:** `PAPER_TRADING=true`, loss streak 7, 3/10/15 %, cap 2, stake 50, fee 0.15. Compose `3ad35a87`;
  `env_unchanged=yes`.
- **Dead letters:** 269 total, **0 new** since T0; no replay; no dead-letter→poll admission.
- **Runtime:** the five containers are unchanged (IDs, images, config hashes), healthy, RestartCount 0; heartbeats
  ≤ 35 s, 0 errors.
  - 0 error-like log lines, except one tracker WARNING at 11:00:09: "invalidation-candle check for MINAUSDT/15m:
    TimeoutError". It was transient and non-fatal; MINA later exited by stop.
  - Collector `ce4e6b6656a5` HEALTHY with 0 restarts.
- **Stop conditions:** none breached.
- **Follow-ups for T0 + 24 h:** soft-reduce behaviour at cap 1; recurrence of the invalidation-check timeout;
  C1 gross labels (all three are LOSS by both gross and net here).
