# PAPER-R2 — checkpoint T0 + 24 h and conditional continuation (2026-10-09)

**Additive record.** Read-only verification. **Nothing was executed against the running system.** No `/resume`, `/pause`,
`/recover_risk` or other Telegram command was sent. No container was restarted. No setting, database row, outbox event
or sealed evidence was changed. The baseline is `docs/ops/PAPER_R2_PRE_RECOVERY.md` @ `0bfcd9e` (unchanged).

| Item | Value |
|---|---|
| Epoch | PAPER-R2: owner `/resume` → B3 `2026-10-08\|f\|manual_resume\|30463`; recovery epoch 3 at `2026-10-08T10:43:22.323782Z`; **T0 = 2026-10-08T10:53:52Z** (query lower bound 10:48:57Z, as at T0 + 1 h) |
| Observation window | T0 → **2026-10-09T11:54Z** (25 h 0 min) |
| +24 h assessment | 2026-10-09 11:10–11:18Z |
| Conditional-continuation verification | 2026-10-09 11:24–11:26Z; closure re-verification 11:48–11:54Z (GRAMUSDT final outcome) |
| Status | **CONDITIONAL_CONTINUATION_CONFIRMED** (§8) |

## 1. Deployment and configuration fingerprints (unchanged from the baseline)

| Container | ID | Image | Config hash | Health | RestartCount | Running since (single boot) |
|---|---|---|---|---|---|---|
| scanner | `891c46fddcf5` | `63b38e7a659d` | `e99de276a5c29317` | healthy | 0 | 2026-09-30T06:50:17Z |
| analyzer | `938664984ac3` | `b9b13d957bf4` | `ea40e350ae005230` | healthy | 0 | 2026-10-01T21:54:13Z |
| signal_engine | `7c663dc07252` | `80096a981b2e` | `de89981aaa29f6e0` | healthy | 0 | 2026-10-01T21:55:37Z |
| telegram | `91680b909017` | `e5f3096b7a71` | `088a5a6850d6a0fd` | healthy | 0 | 2026-10-01T21:52:48Z |
| trade_tracker | `3f40e244b5c1` | `698d31730ec3` | `5592fe40f8fe9fc8` | healthy | 0 | 2026-10-01T21:51:23Z |

**Configuration:**
- **Compose:** blob `3ad35a87e56b2f4bd3e0fc3e2df761e49d1e838a`. `docker compose config --hash <svc>` equals the
  running label for all five services.
- **Risk environment** (tracker, telegram, scanner; identical digest across all three):
  - `PAPER_TRADING=true`;
  - `STOP_ON_CONSECUTIVE_LOSSES=7`;
  - `MAX_DAILY_LOSS_PERCENT=3`, `MAX_WEEKLY_LOSS_PERCENT=10`, `MAX_DRAWDOWN_PERCENT=15`;
  - `RISK_CANARY_MAX_OPEN_TRADES=2`;
  - `TRADE_AMOUNT_USDT=50`, `RISK_CAPITAL_USDT=500`;
  - `MAX_OPEN_TRADES` unset, so the effective cap is min(10, 2) = 2.
- **Tracker evidence-v2:** a single `boot_id 18bb0c7137d9` and `code_sha b8182f37…` throughout the window.

**Sealed evidence re-verified** (`sha256sum -c`, all OK; the SHA256SUMS file hashes are unchanged):

| Evidence directory | SHA256SUMS hash |
|---|---|
| `paper-r2-prerecovery-20261008T102546Z` | `78e8ae9c` |
| `paper-r2-gate-20261008T103309Z/phaseA` | `f273857c` |
| `paper-r2-gate-20261008T103309Z/phaseB` | `e4ed832f` |
| `paper-r2-gate-20261008T103309Z/phaseC` | `fb737c36` |
| `paper-r2-gate-20261008T103309Z/plus1h` | `6890c1d3` |
| `paper-halt-review-20261007T203557Z` | `f9b08d63` |

## 2. Stop conditions (baseline §5)

| # | Condition | Status at 11:24Z |
|---|---|---|
| 1 | Hard risk halt | **Not fired.** Latest B3 row `30480` (2026-10-09), not paused; 0 pause rows since T0; recovery epochs 3 |
| 2 | Admission rule violation | **None.** Max concurrency 2, 0 same-symbol overlaps, 0 duplicate admissions, no admission while halted |
| 3 | Accounting mismatch | **None.** 13 trades / 13 results, 1:1; fee 0.15 per trade; P&L reconciles (§5) |
| 4 | Unauthorised change to paper mode, risk env, Compose or images | **None** (§1) |
| 5 | Restart, unhealthy state, heartbeat beyond tolerance, DB errors | **None.** Heartbeats: analyzer 9 s, signal_engine 10 s, telegram 6 s, tracker 14 s, scanner 128 s (cycle 300 s; tolerance 900 s); 0 consecutive errors |
| 6 | Dead letters growing for any reason other than cap-full deferral | **Formally met** by 5 new `signal.delivered` dead letters (269 → 274). Reconciled in §3; covered by the owner-approved exception in §4. **No other new dead letters** |
| 7 | Host or provider stall > 60 s with trades open | **None.** Collector monitor: 1 444 samples, largest gap 61.3 s (normal cadence). One tracker WebSocket reconnect of about 60 s at 07:09Z with 2 trades open; no barrier was crossed in that minute (§6) |

## 3. Reconciliation of the five dead letters

**Sources:** `signals`, `outbox_events`, `active_trades`, `trade_results`, and tracker evidence-v2 (`entry.attempt`,
`delivery.consumed`, `admission.decision`, `entry.expired`, `trade.*`), plus tracker logs.

**Mechanism.** The tracker defers a delivered signal while it is not yet a trade and not terminal (`trade_tracker/main.py`, `RuntimeError('trade registration deferred')`, 300 s backoff). After 8 attempts (about 37 minutes) the outbox event is dead-lettered. Admission itself remains **poll-driven** for the 2-hour window (caveat C2).

| Signal | Symbol | Signal time | Limit (planned entry) | Observed at first attempt | Outbox event (attempts, retry window) | Outcome at final attempt (a8) | Final outcome | Trades / results |
|---|---|---|---|---|---|---|---|---|
| 15538 | ZECUSDT | 03:05:18 | 1212.05 | 1214.46 | 3600, 8/8, 03:05:27 → 03:41:58 | `AWAITING_FILL` | **NO_FILL**: `entry.expired` 05:05:44 (2 h window) | 0 / 0 |
| 15540 | RAYUSDT | 03:15:19 | 2.4579 | 2.4893 | 3605, 8/8, 03:15:33 → 03:52:19 | `AWAITING_FILL` | **ADMITTED** via the poll path: limit touched → `ENTRY_MARKET` fill 2.4554 (drift −0.10 %), `admission.decision OPENED` at 04:30:23 (trade 3673; risk `within_limits`; open count 1 → 2 = cap) | 1 / 1: result 3627, stop loss 04:39:36, net −0.7920 |
| 15548 | XAUTUSDT | 05:16:34 | 4178.96 | 4179.77 | 3627, 8/8, 05:16:45 → 05:53:02 | `AWAITING_FILL` | **NO_FILL**: `entry.expired` 07:17:05 | 0 / 0 |
| 15549 | INJUSDT | 05:31:36 | 7.096 | 7.097 | 3630, 8/8, 05:31:49 → 06:09:00 | `AWAITING_FILL` (a5–a6 were `CAPACITY`) | **NO_FILL**: `entry.expired` 07:31:48. Every limit touch (05:50:21–07:21:52) was refused by the risk guard with `max_open_trades` while NEAR and JUP held both slots; otherwise it awaited a fill | 0 / 0 |
| 15564 | GRAMUSDT | 09:53:09 | 1.436 | 1.457 | 3655, 8/8, 09:53:24 → 10:29:12 | `AWAITING_FILL` | **NO_FILL**: `entry.expired` at 11:53:13Z (2 h window closed 11:53:09Z). It awaited a fill throughout (last observed 1.449 vs limit 1.436 at 11:52:42; 0 refusals) | 0 / 0 |

**What every case confirms:**
1. The deferral is genuinely `AWAITING_FILL`, a momentum limit set below the observed price, and was still awaiting a
   fill when the outbox retry budget ran out.
2. No unauthorised trade was opened. The only admission (RAY) went through the normal risk decision, within the cap.
3. No duplicate trade or result exists; the database holds 0 duplicates.
4. No valid filled trade was lost. The one fill (RAY) was registered and closed with exactly one result.
5. The later poll-path admission (RAY) reconciles. Its `signal.delivered` event stays dead, as caveat C2 provides;
   there is no replay.
6. No risk limit or position cap was breached.
7. The final outcomes are classified from authoritative records: **4 NO_FILL** (ZEC, XAUT, INJ, GRAM) and **1 admitted** (RAY). None is pending.

## 4. Owner-approved exception: scope and limits

- **Scope:** the owner approved continuation with an exception to stop condition 6 for **exactly these five dead
  letters**: outbox events 3600, 3605, 3627, 3630, 3655 (signals 15538, 15540, 15548, 15549, 15564).
- **Justification:**
  - Each is a verified `AWAITING_FILL` limit-entry deferral exhausting the outbox retry budget inside the 2-hour
    admission window.
  - This is the same mechanism as PAPER-R1's 24 "deferral exhaustion" dead letters (halt review `f9b08d63`), covered by
    caveat C2.
  - None involved a safety, admission, cap or accounting failure.
- **Not covered:**
  - **Any future dead letter**, including further `AWAITING_FILL` cases, which stays subject to stop condition 6 and
    owner review.
  - Resolved: GRAMUSDT ended as a `NO_FILL` expiry (11:53:13Z), inside the exception's terms.
- **Unchanged:** the baseline stop-condition wording. Any change to it is a separate owner decision.

## 5. Operational and risk metrics (T0 → 11:24Z)

**Signals:**
- 33 generated (30 momentum, 3 reversion; all 15m, `policy_ready`, `sb-2026.08`); 17 sent, 16 not sent.
- **All 16 unsent signals arrived while 2 trades were open** (cap full).
- Of the 17 sent: 13 opened, 4 expired `NO_FILL` (GRAMUSDT at 11:53:13Z, after the 11:24Z metrics snapshot).
- Upstream, the signal engine logged 240 macro blocks.

**Pipeline:**
- Scanner: 293 cycles, median interval 302 s (max 310 s), 50.5 eligible symbols per cycle.
- Outbox since T0, completed: `signal.ready` 33, `trade.opened` 13, `trade.closed` 13, `trade.target_hit` 9,
  `signal.delivered` 12; plus 5 dead (§3). Processing took 7–11 s typically, at most 15 s.

**Trades:**
- 13 opened and 13 closed, 0 open; one trade and one result per signal; max concurrency 2; 0 same-symbol overlaps.
- **Stop fills:** 5 stop exits sit 0.10–0.12 % below the stop (MINA −0.19 %, where the observed price was already below
  it). Consistent with min(stop, observed) × 0.999.

**P&L (net is authoritative):**

| Metric | Value |
|---|---|
| Gross | −0.3616 USDT |
| Fees | 1.95 USDT (13 × 0.15) |
| **Net** | **−2.3116 USDT** (−0.46 % of 500) |
| Net wins / losses | 6 / 7 |
| Profit factor | 0.51 net (0.91 gross) |
| Unrealised | 0 |
| Daily net | 10-08 −2.6343 (−0.5269 %); 10-09 +0.3227 (+0.0645 %). Equal to `risk_management.daily_pnl_percent` |

**Risk:**
- **Net streak sequence:** LLLWLWWWLLWWL; current 1 of 7.
- **Soft reduce:** to cap 1 at 10-08 12:00:25, reset at 14:41:41.
- **Cap refusal:** `max_open_trades` (first at 10-09 05:50:21).

| Limit | Peak value | Threshold |
|---|---|---|
| Drawdown | 0.551 % | 15 % |
| Weekly | −0.399 % | 10 % |
| Exposure | 20 % of capital (2 × 50 USDT) | — |

**Resources:**
- Host load 0.53; swap 0; CPU / memory pressure ≈ 0.
- Paper containers: < 1 % CPU and < 160 MiB each.
- Collector `ce4e6b6656a5` and monitor: healthy, 0 restarts.

**After the +24 h snapshot (verified at 11:53:53Z):**
- 2 new signals: 15565 ZECUSDT at 11:48:24 (limit) and 15566 QNTUSDT at 11:49:24.
- 2 trades opened: 3677 QNTUSDT (market, 11:49:34) and 3678 ZECUSDT (limit filled, 11:51:08).
- Both are paper trades. Open count is 2, exactly the cap. No same-symbol overlap and no duplicates.
- Both `signal.delivered` events completed. Dead letters are still 274; **no new dead letters**.
- These trades are not part of the metrics above; T0 + 72 h covers them.

**Sample:** sufficient for operational verification only. 13 trades give no basis for performance conclusions; R2 is
operational observation, not alpha evidence.

## 6. Known transient issues (non-blocking)

**Tracker:**
- 2 REST price-fetch `TimeoutError`s for NEARUSDT (10-09 09:20:28 and 09:26:40) while it was open. Its stop fill was
  −0.12 % versus the stop, so there was no material lateness.
- 1 invalidation-candle `TimeoutError` (10-08 11:00:09, already known from T0 + 1 h).

**Tracker WebSocket reconnects** (about 60 s each):

| Time | Open trades | Effect |
|---|---|---|
| 10-08 12:01:02 → 12:02:03 | 0 | — |
| 10-09 07:09:00 → 07:10:00 | 2 (NEAR, JUP) | No target or stop crossed in that minute |

**Collector monitor (outside Paper):** 10 short `DEGRADED` episodes since T0 (`incident:previous_run_stopped_failed`),
each recovering in about 1 minute. The last was 10-09 04:54:51Z; the Collector never restarted. Nothing links them to
Paper, whose footprint is negligible. Referred to the G3 24-hour comparison.

**Caveat C1 is visible:** trade 3623 (CRCLBUSDT) is labelled a gross "WIN" with net −0.0393, so `risk_management`
win/loss counts use gross labels. Net figures are authoritative.

## 7. Correction to the T0 + 1 h evidence

- The sealed file `paper-r2-gate-20261008T103309Z/plus1h/trades_detail.txt` records `concurrency_max|3`. That value is
  an **artefact of its query**, which counted the trade under evaluation twice.
- Recomputed with an interval sweep, the actual maximum concurrency in the +1 h window, and across the whole of R2, is
  **2**. The cap was never exceeded.
- The T0 + 1 h section of the baseline document already states 2.
- The sealed evidence is **left unchanged**; this record is the erratum.

## 8. Conditional continuation

**CONDITIONAL_CONTINUATION_CONFIRMED** (2026-10-09T11:26Z; re-confirmed at closure, 11:54Z). The owner's conditions:

| Condition | Result |
|---|---|
| All five cases reconcile as `AWAITING_FILL` deferrals | ✔ (§3) |
| No other unexplained dead letters | ✔ |
| No safety breach | ✔ |
| Identity, configuration and risk controls unchanged | ✔ |
| All other stop conditions satisfied | ✔ (§2) |

**Continuation means the already-running system is left unchanged.** No command, restart, setting change or new
recovery epoch was made.

## 9. Next checkpoint

**T0 + 72 h at 2026-10-11T10:53:52Z.** Read-only. Scope:
- stability;
- stop conditions 1–7;
- **every** new dead letter, by cause (not covered by §4);
- net P&L and risk;
- transient errors and Collector-monitor episodes;
- continuation recommendation.

## 10. Prepared, not executed (needs separate authorisation)

**Evidence seal:**
- **Proposed directory:** `/home/tradmin/backups/tsb-aiohttp-20260929T122701Z/paper-r2-gate-20261008T103309Z/plus24h/`.
- **Contents:** the read-only query outputs, the five-case evidence-v2 extracts, container and config fingerprints, and
  the monitor summary.
- **Seal:** `SHA256SUMS`, then `chmod a-w`.
- **Status:** not created.

**Git:** this file is committed and pushed on `docs/paper-r2-prerecovery-20261008` (owner-authorised 2026-10-09).
