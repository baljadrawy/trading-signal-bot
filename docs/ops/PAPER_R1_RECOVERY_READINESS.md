# PAPER-R1 recovery readiness (2026-10-08)

Status: read-only assessment. **No command was sent; B3, risk settings, strategy and code are unchanged.**
Recovery (`/recover_risk`, `/resume`) remains an owner action and is not authorised by this document.

Inputs: the sealed halt review (`paper-halt-review-20261007T203557Z`, SHA256SUMS `f9b08d63…`); the approved
loss-streak recovery runbook (Arabic, PAPER-R1 governance); the PAPER_ONLY owner directive (2026-09-27); and a
read-only check on 2026-10-08 (B3, open trades, recovery epochs, container state).

## 1. Current operational state (measured 2026-10-08 ~10:10Z)
- B3 = `2026-10-07|t|risk:loss_streak_halt|30459` (halted since 2026-10-07T00:24:47Z).
- Open trades: **0**. Recovery epochs: 2, latest `2026-10-04T15:26:43.497803Z`.
- Paper containers (scanner, analyzer, signal_engine, telegram, tracker) are up and healthy, with RestartCount 0.
- Running tracker code = `tsb-p1d-src` @ `59297305` (image `698d3173…`), **not** the production checkout's working tree.
- Collector has no data path into Paper (confirmed twice).

Because 0 trades are open, the halt is the runbook's **Case B**. It cannot self-clear. It needs `/recover_risk <reason>`
from the owner's account (opens epoch 3), followed by `/resume` because the admin pause is also set (`t`).

## 2. Halt correctness (from the review; facts)
The 7-net-loss breaker fired exactly at its threshold (7/7). It used correct inputs, counted from epoch 2, and fired in
the same second as the 7th close (trades 3612–3618, all net and gross losses). The other checks also passed:
- Admission: 31/31 trades within the rules.
- Concurrency: at most 2 trades open.
- Soft reduce: engaged at 3 losses and at 5 losses as designed.
- Fees: 0.15 USDT on every trade.
- Fills: reconcile.

No causal software, accounting or risk-control defect was found. n = 31; no Alpha conclusion.

## 3. Findings and their classification

| # | Finding | Effect | Class |
|---|---|---|---|
| F1 | **Gross/net inconsistency.** The trade WIN/LOSS label and `risk_management.wins/losses` use GROSS `profit_usdt > 0`; the loss streak and risk limits use NET (−0.15). 3 break-even trades labelled "WIN" were net losses. | Reports and Telegram summaries overstate wins. Risk decisions are unaffected because they use net. | Owner decision: accept as a documented caveat **or** fix before resume (recommended fix: label and counters on net, gross kept as a separate field). Not safety-critical. |
| F2 | **Dead-letter vs polling admission.** `signal.delivered` events dead-letter after 8 failures, but admission is poll-driven over a 2 h window. A dead-lettered signal can still be admitted (seen once: 15510 ENA). | Audit contradiction ("dead" yet traded). No double admission: there is a dedup per symbol/timeframe/candle and no same-symbol overlap. Entries fill at the current price with stops and targets rescaled, so a stale signal is re-priced but up to 2 h old. | Owner decision on semantics. Prior note: introduce an explicit CAP_REJECTED/EXPIRED state instead of dead letters. Either document "dead letter ≠ inadmissible" or fix. Optional for safety. |
| F3 | **Dead-letter backlog** 269 = 245 historical + 24 post-epoch (deferral exhaustion while the cap was full). | No replay occurred. Replay remains forbidden. | Owner decision: keep as is (no replay) — recommended. |
| F4 | Break-even stop is capped at T1, so a "break_even" exit can be net-negative. | By design. Contributes to F1 labels. | Optional (document). |
| F5 | The size multiplier reduces open slots only; the stake stays 50 USDT. | Soft reduce lowers concurrency, not exposure per trade. | Optional (document; no change without a separate risk review). |
| F6 | Host and provider stalls (2026-10-06 09:04Z and 11:20Z). | Paper failed closed (price timeouts, 87 s WS outage). No tail trade was affected. | Optional: re-validate controls after the stall. The provider risk persists. |
| F7 | Running code identity differs from the production checkout working tree. | Provenance risk for any future change or rollback. | **Mandatory to record** the deployed identity (`59297305`, image `698d3173…`) in the new epoch's record. |

## 4. Risk controls and governance (unchanged, verified)
- PAPER mode; `STOP_ON_CONSECUTIVE_LOSSES` 7; daily 3 %, weekly 10 %, drawdown 15 %.
- Effective max open 2; stake 50 USDT; soft reduce at 3 and 5 losses.
- B3 fail-closed; the recovery epoch is DB-timestamped under the same advisory lock as position opening.
- PAPER_ONLY: live trading is forbidden and there is no automatic transition. A successful Paper period does not
  authorise live trading, which needs all four conditions (predeclared criteria, independent forward validation,
  verified controls, explicit owner approval).

## 5. Mandatory vs optional before any resume
**Mandatory (gate):**
1. Owner decision to resume, with an explicit investigation-based reason for `/recover_risk` (runbook step 1).
2. Immediately before the command: re-verify 0 open trades, B3 unchanged, containers healthy, and the deployed code
   identity (F7).
3. A pre-declared purpose and stop conditions for the new epoch (PAPER-R2). It is forward operational observation
   only, not Alpha evidence. Existing limits apply unchanged.
4. Explicit dispositions for F1 (accept or fix) and F2/F3 (semantics, no replay). Each may be "accept and document",
   but it must be decided, not left implicit.
5. Post-resume verification plan, reusing the PAPER-R1 plan (`paper-resume-prep-20261004T144030Z/09_…`):
   epoch 3 row, B3 `manual_resume`, first admissions within rules.

**Optional improvements (no resume dependency):** fix F1 labels; CAP_REJECTED/EXPIRED state for F2; document
F4/F5; re-validate controls after the stall (F6). Any code change needs its own reviewed PR and gated deploy, and is
better done before the resume than mid-epoch.

## 6. Recovery prerequisites and owner decisions (exact)
- D-P1: Resume Paper at all? (yes / stay halted)
- D-P2: F1 — accept the gross label as a caveat, or fix to net before resume?
- D-P3: F2/F3 — accept "dead letter ≠ inadmissible" semantics, or schedule the expiry-state change; confirm no replay.
- D-P4: PAPER-R2 epoch purpose and stop conditions (default: current limits, observation only).
- D-P5: Optional post-stall control re-validation, yes or no.
- Then, owner-only sequence (from the runbook): `/recover_risk <reason>` → `/resume` → read-only post-resume verification.

## Verdict
**PAPER RECOVERY READINESS: READY FOR OWNER DECISION.** There is no technical blocker. The halt was correct and
no causal defect exists. The mandatory items are owner decisions plus pre-command verification; no code fix is
strictly required.
