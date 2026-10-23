# Governance audit log

Append-only. Each entry records an incident or an exceptional, owner-authorized access to operational or protected
state. It records **what was accessed, under which authorization and what was disclosed**. It never contains protected
values: no P&L, trade results, loss counts, drawdown values, holdout data or secrets. Times are UTC, minute precision.
Correct an entry by adding a new one that references it; never rewrite an old entry. Entry IDs use the **incident date**
(`AUD-<incident date>-<n>`); the date the entry was opened is recorded inside it.

Where an entry needs more detail than a public file may hold, the detail lives in the host record named in the entry
(mode 700, never committed).

---

## AUD-2026-10-21-01 — Paper trading halted by a technical fail-closed risk state

| Field | Value |
|---|---|
| Opened | 2026-10-23, after an owner-authorized root-cause investigation |
| Status | **OPEN.** The halt is preserved. No `/resume` was issued. |
| Halt start | 2026-10-21 about 20:23–20:24Z |
| Classification | **TECHNICAL** (fail-closed `invalid_risk_state`), not an outcome-derived risk limit |
| Evidence basis | Non-protected container logs (message types and times only) plus source code. No protected read was needed to classify it (see **Provenance** below). |
| Host record | `~/ops/tsb-governance/AUD-2026-10-21-01.md` (mode 700) |

**Confirmed chain.**
1. About 20:23Z there was a host-wide Binance connectivity blip. In the same minute:
   - the scanner logged a scan-cycle `TimeoutError`;
   - the Collector's connections logged `data_stall_reconnect`.
2. The tracker logged one price-fetch `TimeoutError`. `get_current_price` returns `None` on any exception. `assess_new_trade_risk` then sets the unrealized value to NaN, as designed: missing market state fails closed.
3. `evaluate_new_trade` refused the trade with `invalid_risk_state`. This is the first such rejection in the tracker log, on the admission path.
4. `record_risk_decision` treats `invalid_risk_state` as a hard halt and writes the administrative pause. The pause is sticky (an OR-merge) until an owner `/resume`.
5. From 20:24Z the scanner logged the pause, with reason category `invalid_risk_state`, on every cycle.

**Provenance: why the current reason proves a technical origin.** A new hard-halt reason *overwrites* `pause_reason`
(`record_risk_decision` upsert), so the current reason alone would not exclude an earlier risk-limit or manual pause
relabelled by a later timeout. Two non-protected facts exclude it here:
- the scanner logs a pause line on **every** paused cycle; its last pause line before the incident was on 2026-10-08
  10:48Z, and none appears between then and 2026-10-21 20:24Z: the system was **not paused** when the timeout occurred,
  so the halt **originated** as `invalid_risk_state`;
- all 458 pause lines from 2026-10-21 20:24Z to 2026-10-23 11:00Z carry the identical reason: no later hard halt
  overwrote it.
The A4 pre-halt rejection categories were per-trade admission refusals logged while the system was unpaused, not
pause reasons.

**Accesses under this incident.**

| # | When | What | Authorization | Disclosed |
|---|---|---|---|---|
| A1 | 2026-10-22, about 20:52Z | A `READ ONLY` read of boolean flags of the single active pause row: row exists, paused, date valid, resume marker | Owner, "Critical Recovery, Backup Repair and Safe Development" (flag only) | the four booleans |
| A2 | 2026-10-22 to 2026-10-23 | Scanner, tracker and telegram container logs around the halt; error types and times, with digits masked | Owner, "Authorized Pause Root-Cause Investigation", Phase 1 (non-protected) | message types, times, the reason category `invalid_risk_state` |
| A3 | — | Phase 2: a single-field `pause_reason` read | Authorized by the owner, **NOT USED** (Phase 1 was sufficient) | none |
| A4 | 2026-10-23, approximately 00:25Z | Tracker log message-type extraction for 20:15–20:40Z on 10-21; symbols and digits removed | Phase 1 (non-protected) | Types and minute counts. **Incidental:** the reason category of rejections logged *before* the halt was visible (a category, no values). It was not analyzed further and is recorded only in the host record. |
| A5 | 2026-10-23 | One CLI run of the pipeline-liveness monitor (PR #87) by its reviewer, over the last hour of 4 containers' logs | Review of PR #87 (read-only) | state codes only |
| A6 | 2026-10-23 | Dump TOC of an existing backup set, object-type counts only (schema metadata, no data) | Owner decision 1 (backup recovery) | object-type counts |
| A7 | 2026-10-23, approximately 10:30Z | Scanner log: pause-line presence before the incident and reason identity since (booleans and counts of pause lines only) | Owner, "Controlled Backup Recovery and Safe Integration", B (non-protected) | last pause line before the incident (date and minute), the line count, "reason identical" |
| A8 | 2026-10-23, approximately 10:33Z | P1-BG v3 supervised run: the full production dump was restored into a disposable `--network none` container and compared table-by-table; the container was removed | Owner, same message, A (backup repair) | table count, data-table count, server version, PASS (no row counts) |
| A9 | 2026-10-23, approximately 13:20Z | Tracker log: presence and minute range of open-position tracking cycles and price-fetch error count since 2026-10-22; a synthetic risk evaluation of the deployed code with live public prices and a fake database (synthetic trades only) | Owner, "Post-Recovery Validation and Governance Continuation" (non-protected) | tracking cycles present until 2026-10-22 05:15Z then none (inferred: no open position to track), 0 price-fetch errors, synthetic decision reasons |

**Not done.**
- No `trade_results`, P&L, loss-streak or drawdown values were read.
- No historical pause rows were read.
- No holdout data was accessed.
- No database writes were made.
- The pause was not changed.
- No risk control was changed.
- Nothing was deployed or restarted.

**Next owner decisions.**
- Whether and when to `/resume`, after a fresh risk-state validity check.
- The technical-halt recovery workflow: `docs/ops/TECHNICAL_HALT_RECOVERY.md`, a design and tests on a separate Draft PR.
