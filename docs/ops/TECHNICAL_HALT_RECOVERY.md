# Technical-halt recovery workflow (design and test only)

Status: **design + tests only.** Nothing in this change runs in production. `shared/halt_recovery.py`
is imported by no service; no runtime code path, schema, container or pause state is changed. Wiring
it into Telegram (section 4) needs a separate owner approval.

Files: `shared/halt_recovery.py` (pure, standard library only) and `tests/test_halt_recovery.py`.

---

## 1. Incident RCA, 2026-10-21

All times UTC, minute precision. No protected values (P&L, counts, drawdown, results) are used or
needed; the analysis rests on log message types, their timing and the code.

### 1.1 Confirmed

**Code chain** (read from `origin/main`):

1. `trade_tracker.main.get_current_price` fetches the price over REST (`aiohttp`, total timeout
   five seconds). Any exception is caught, logged as `خطأ في جلب سعر <symbol>`, and the function
   returns `None`.
2. `assess_new_trade_risk` loops over the open positions; on the first falsy price it sets
   `unrealized = float('nan')` ("Missing market state must fail closed") and stops the loop.
3. `shared.risk_management.evaluate_new_trade` runs its finite-input check **before** any other rule
   (including the administrative pause) and returns `RiskDecision(reason='invalid_risk_state')`.
4. `record_risk_decision` lists `invalid_risk_state` among its hard halts and upserts
   `risk_management` with `is_trading_paused = (existing OR new)` and
   `pause_reason = 'risk:invalid_risk_state'`. The OR-merge makes the halt **sticky**: a later clean
   decision never clears it; only the owner's `/resume` (`manual_resume`) does.
5. From then on `get_pause_state` returns `(True, 'risk:invalid_risk_state')`; once inputs are
   finite again, `evaluate_new_trade` returns that pause reason as the hard stop, and the scanner
   reports `التداول موقوف - السبب: risk:invalid_risk_state` every cycle.

**Log evidence** (message types and minutes only):

| time | service | observation |
|---|---|---|
| 2026-10-21 20:23Z | scanner | Binance request `TimeoutError` |
| 2026-10-21 20:23Z | collector | `data_stall_reconnect` |
| 2026-10-21 20:23Z | trade_tracker | one `خطأ في جلب سعر` price-fetch `TimeoutError`, then the first admission rejection with reason `invalid_risk_state` |
| from 2026-10-21 20:24Z | trade_tracker | every rejection carries the pause reason `risk:invalid_risk_state` |
| from 2026-10-21 20:24Z | scanner | `التداول موقوف - السبب: risk:invalid_risk_state` each cycle |

The switch from `invalid_risk_state` to the pause reason one minute later is itself informative:
because the finite-input check outranks the pause, the reason can only change once inputs are finite
again, i.e. prices were being fetched successfully by the next evaluation.

The fault-injection tests reproduce steps 1 to 5 on the **real** tracker functions with fakes
(`tests/test_halt_recovery.py::test_fault_a_*`, `test_fault_b_*`, `test_fault_c_*`).

### 1.2 Hypotheses

| id | hypothesis | status |
|---|---|---|
| H1 | The five-second REST timeout was too tight during a host-wide Binance connectivity blip. | **Corroborated**, not proven: same-minute scanner `TimeoutError` and collector `data_stall_reconnect`, and the reason flip at the next minute (above). |
| H2 | The tracker's WebSocket price stream (`trade_tracker/binance_price_stream.py`) may have held a usable recent price at that minute; admission does not consult it. | **Unverified.** No non-protected evidence of the stream's state at that minute was examined. |
| H3 | A non-finite stored trade result poisoned the realized totals. | **Not excluded** by non-protected evidence, but inconsistent with the same-minute timeout and with the reason flip to the pause reason (a stored NaN would keep `invalid_risk_state` on every later evaluation). |
| H4 | The post-close refresh path (`__POST_CLOSE_RISK_REFRESH__`) recorded the halt. | **Not observed**: the logged rejection is the admission path. |

### 1.3 Assessment

The halt behaved as designed: missing market state failed closed and stayed closed. The gap is
operational: nothing distinguishes a **technical** halt from a **risk-limit** halt, and there is no
evidence-gated procedure for the owner to resume after a technical one.

---

## 2. Workflow

```
pause row observed ──► alert ──► classify ──► fresh validity verification ──► independent safeguards
                                                                                     │
          existing /resume write ◄── confirm (step two) ◄── challenge (step one) ◄───┘
```

1. **Immediate alert.** The pipeline liveness monitor (PR #87) reports `BLOCKED_RISK_CONTROL`; the
   message is extended with the halt class from `classify_halt` and the fixed text from
   `technical_halt_alert(pause_reason, since)` (English plus short Arabic; start time at minute
   precision; no values).
2. **Classification** (`classify_halt`, exact strings only):
   - `TECHNICAL`: `invalid_risk_state` / `risk:invalid_risk_state`, `risk_state_missing`,
     `risk_state_inconsistent`.
   - `RISK_LIMIT`: `daily_loss_limit`, `weekly_loss_limit`, `max_drawdown_limit`, `loss_streak_halt`
     (bare or `risk:`-prefixed).
   - `MANUAL`: `manual_pause`.
   - `UNKNOWN`: anything else, including `trading_paused`, `manual_resume`, case or whitespace
     variants. Never eligible.
   Only `TECHNICAL` can proceed. `RISK_LIMIT` and `MANUAL` keep the existing `/recover_risk` and
   `/resume` governance unchanged.
3. **Fresh validity verification** (`FreshRiskCheck`, computed now by the future caller):
   finite inputs; full price coverage (`prices_obtained == prices_requested`; a flat book needs none);
   evaluated within the age bound (default `max_age_s=120`, not in the future); a minimum number of
   consecutive clean checks (default three).
4. **Independent safeguards:**
   - a fresh `evaluate_new_trade` on the snapshot with the administrative pause **masked**
     (`mask_administrative_pause`), so an independent daily/weekly/drawdown/loss-streak halt is
     visible instead of hidden behind the existing pause. Its reason must be in a fixed allowlist of
     non-halt reasons (clean pass, size reductions, per-trade capacity refusals, none of which
     `record_risk_decision` ever persists as a pause). A risk-limit reason blocks; a pause reason
     echoed back blocks as `pause_not_masked`; anything unrecognised blocks.
   - `loss_streak_halt_active` from `shared.risk_epoch.loss_streak_state()` must be `False`.
   `assess_technical_resume` returns `Assessment(eligible, halt_class, blockers, ...)` with fixed
   blocker codes: `not_technical_halt`, `clock_invalid`, `check_malformed`, `check_stale`,
   `check_from_future`, `inputs_non_finite`, `price_coverage_incomplete`, `fresh_evaluation_invalid`,
   `pause_not_masked`, `independent_risk_halt_active`, `unrecognised_decision_reason`,
   `loss_streak_halt_active`, `insufficient_clean_checks`.
5. **Explicit two-step owner approval:**
   - step one, `issue_resume_challenge(assessment, pause_row_id, now, ttl_s=300)`: refuses unless
     eligible; binds a 128-bit random single-use nonce to the pause row id and a digest of the
     assessment (class, reason, eligibility, blockers, fresh decision reason; no timestamps).
   - step two, `verify_resume_confirmation(challenge, given_nonce, current_pause_row_id,
     current_assessment, now, used_nonces)`: the caller recomputes a **new** fresh check first. Fixed
     result codes: `confirmed`, `malformed_request`, `challenge_from_future`, `challenge_expired`,
     `nonce_replayed`, `nonce_mismatch` (constant-time compare), `pause_row_changed`,
     `no_longer_eligible`, `assessment_changed`. On `confirmed` the nonce is recorded as used.
   Note: `risk_management` is upserted per date, so a same-day change of reason keeps the row id;
   the digest binds the reason, so such a change still refuses as `assessment_changed`.
6. **Existing `/resume` write.** On `confirmed`, the caller runs the unchanged `cmd_resume` statement.
   The module never writes pause state and never resumes.

---

## 3. Deliberately NOT changed

- `invalid_risk_state` stays a sticky hard halt (OR-merge upsert); pinned by
  `test_fault_c_hard_halt_set_includes_invalid_risk_state` and
  `test_fault_c_upsert_keeps_or_merge_so_halt_is_sticky`.
- No automatic resume of any kind; the module has no I/O and nothing imports it
  (`test_nothing_imports_the_module_at_runtime`).
- No downgrade of a halt class, no reclassification of a risk-limit halt as technical, no softer
  handling of `UNKNOWN`.
- Missing or non-finite market state still yields NaN and `invalid_risk_state`.
- `trade_tracker/main.py`, `shared/risk_management.py`, `shared/trading_state.py`,
  `shared/risk_epoch.py`, `telegram/main.py`: untouched.

---

## 4. Wiring plan (later; separate owner approval required)

- **Telegram handlers** (owner-restricted, like `cmd_resume`):
  - `/resume_technical`: read `get_pause_state` and the latest decision row id; compute the fresh
    check; `assess_technical_resume`; if eligible, `issue_resume_challenge` and reply with the
    nonce, the class and the expiry minute; otherwise reply with the blocker codes only.
  - `/confirm_resume <nonce>`: recompute a fresh check, re-read the pause row id,
    `verify_resume_confirmation`; on `confirmed` run the existing `cmd_resume` statement and its
    loss-streak follow-up message unchanged.
  - Challenge and used-nonce store kept in process memory (lost on restart, which only forces a new
    challenge: fail-closed).
- **Where the fresh check is computed:** a read-only helper in the tracker that reuses
  `assess_new_trade_risk`'s snapshot construction with the pause masked, counts requested vs usable
  prices, and records consecutive clean results across N spaced evaluations. It must not call
  `record_risk_decision`.
- **Audit logging:** one log line per challenge issue and per confirmation attempt with the result
  code, halt class, chat identity and minute; never values or the nonce itself.
- **Test plan for the wiring:** handler tests with fakes for every result code; a fake-DB test that
  `/confirm_resume` writes exactly the existing `manual_resume` statement once and nothing on any
  refusal; a race test where the reason changes between challenge and confirm; restart test
  (challenge lost, refusal); tracker test that the fresh-check helper never writes `risk_management`;
  regression run of `tests/test_risk_recovery_command.py`, `tests/test_risk_epoch.py`,
  `tests/test_a49_risk_guard_nonfinite.py` and this suite.

---

## 5. Optional future hardening (each needs separate approval; each stays fail-closed)

- **Bounded retry on the price fetch** before returning `None`: a small fixed number of retries with
  a short total budget inside one evaluation; if all fail, NaN and `invalid_risk_state` exactly as
  now.
- **Fresh WebSocket price with an age bound:** use `BinancePriceStream`'s cached price for a symbol
  only when it is finite, positive and younger than a strict bound; otherwise fall back to REST, and
  if that fails, NaN as now. Would address H2 if it is confirmed.
- Neither idea clears a halt; both only reduce how often a transient blip causes one.
