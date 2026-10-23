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
   `pause_reason = CASE WHEN EXCLUDED.is_trading_paused THEN EXCLUDED.pause_reason ELSE
   risk_management.pause_reason END`, i.e. `'risk:invalid_risk_state'`. The OR-merge makes the halt
   **sticky**: a later clean decision never clears it; only the owner's `/resume` (`manual_resume`)
   does. The same CASE also means **every later hard halt overwrites the reason** (see 1.4).
5. From then on `get_pause_state` returns `(True, 'risk:invalid_risk_state')`; whenever inputs are
   finite, `evaluate_new_trade` returns that pause reason as the hard stop, and the scanner
   reports `التداول موقوف - السبب: risk:invalid_risk_state` every cycle.

**Log evidence** (message types and minutes only):

| time | service | observation |
|---|---|---|
| 2026-10-21 20:23Z | scanner | Binance request `TimeoutError` |
| 2026-10-21 20:23Z | collector | `data_stall_reconnect` |
| 2026-10-21 20:23Z | trade_tracker | one `خطأ في جلب سعر` price-fetch `TimeoutError`, then the first admission rejection with reason `invalid_risk_state` |
| from 2026-10-21 20:24Z | trade_tracker | every rejection carries the pause reason `risk:invalid_risk_state` |
| from 2026-10-21 20:24Z | scanner | `التداول موقوف - السبب: risk:invalid_risk_state` each cycle |
| 2026-10-08 10:48Z to 2026-10-21 20:24Z | scanner | **no** pause line at all |
| 2026-10-21 20:24Z to 2026-10-23 11:00Z | scanner | 458 pause lines, every one with the identical reason `risk:invalid_risk_state` |

**Provenance of this halt** (non-protected evidence, minute precision). The scanner logs one pause
line on every paused cycle (`scanner/scanner_logic.py`, `التداول موقوف - السبب: <reason>`). It logged
none between 2026-10-08 10:48Z and 2026-10-21 20:24Z, so the system was unpaused when the timeout
occurred and the halt **originated** as `invalid_risk_state`, not as a relabel of an earlier risk-limit
or manual halt. Since 20:24Z all 458 pause lines through 2026-10-23 11:00Z carry the identical reason,
so no later hard halt overwrote it.

**Inference (not proven):** the switch from `invalid_risk_state` to the pause reason one minute later
means the next evaluation had finite inputs, because the finite-input check outranks the pause. That
holds either when every open position's price was fetched, **or** when no position was open at all
(an empty book fetches no price, so `unrealized` stays finite). The logs examined do not distinguish
the two, so the flip corroborates recovery of price fetching only together with an open book.

The fault-injection tests reproduce steps 1 to 5 on the **real** tracker functions with fakes
(`tests/test_halt_recovery.py::test_fault_a_*`, `test_fault_b_*`, `test_fault_c_*`, `test_fault_d_*`).

### 1.2 Hypotheses

| id | hypothesis | status |
|---|---|---|
| H1 | The five-second REST timeout was too tight during a host-wide Binance connectivity blip. | **Corroborated**, not proven: same-minute scanner `TimeoutError` and collector `data_stall_reconnect`; the reason flip at the next minute is consistent with it (see the inference above, including the empty-book alternative). |
| H2 | The tracker's WebSocket price stream (`trade_tracker/binance_price_stream.py`) may have held a usable recent price at that minute; admission does not consult it. | **Unverified.** No non-protected evidence of the stream's state at that minute was examined. |
| H3 | A non-finite stored trade result poisoned the realized totals. | **Not excluded** by non-protected evidence, but inconsistent with the same-minute timeout and with the reason flip to the pause reason (a stored NaN would keep `invalid_risk_state` on every later evaluation). |
| H4 | The post-close refresh path (`__POST_CLOSE_RISK_REFRESH__`) recorded the halt. | **Not observed**: the logged rejection is the admission path. |

### 1.3 Assessment

The halt behaved as designed: missing market state failed closed and stayed closed. The gap is
operational: nothing distinguishes a **technical** halt from a **risk-limit** halt, and there is no
evidence-gated procedure for the owner to resume after a technical one.

### 1.4 Relabelling: why the current reason is not enough

`record_risk_decision` writes `pause_reason = EXCLUDED.pause_reason` whenever the new decision is a
hard halt, and `evaluate_new_trade` checks finite inputs **before** the pause. So while **any** halt is
active (a risk limit such as `daily_loss_limit` or `loss_streak_halt`, or `manual_pause` written by
`/pause`), one later price timeout produces `invalid_risk_state` and rewrites the row's reason to
`risk:invalid_risk_state`; on a later date the upsert inserts a newer row with that reason, which
`get_pause_state` then reports. No `risk.halted` event marks the relabel, because the tracker only
enqueues one on the running-to-halted transition. Pinned on the real functions by
`test_fault_d_relabel_on_real_path_emits_no_outbox_event` and in the model test
`test_fault_c_or_merge_semantics_model`.

Consequence for the design: a `risk:invalid_risk_state` label alone does **not** prove that a halt
began technically. Eligibility is decided on **provenance**, the history of pause reasons since the
last `manual_resume` (section 2, step 2).

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
   **Provenance** (required inputs `reasons_since_last_resume`, `history_complete`): the caller passes
   every pause reason observed since the last `manual_resume`, oldest first, and whether its source
   covers that whole interval. Eligible only if `history_complete is True`, the sequence is a non-empty
   list or tuple of strings ending at the current reason, and **every** entry classifies `TECHNICAL`.
   Otherwise `halt_history_incomplete` or `halt_provenance_not_technical`. Consecutive repeats are
   collapsed and the resulting transition sequence is bound into the assessment digest.
3. **Fresh validity verification** (`FreshRiskCheck`, computed now by the future caller):
   finite inputs; price coverage with `prices_requested == open_count` and
   `prices_obtained == prices_requested` (`open_count` is a required field, so a flat book is eligible
   only when the caller explicitly asserts `open_count == 0`); evaluated within the age bound
   (default `max_age_s=120`, not in the future); `clean_check_times`, the timestamps of the
   consecutive clean checks ending with this one: at least `min_clean_checks` (default three),
   strictly increasing with at least `min_check_spacing_s` (default 20) between neighbours, the last
   equal to `evaluated_at`, and the oldest no more than `max_check_window_s` (default 900) old. The
   module verifies count, order, spacing and window; that each listed check was clean by these same
   criteria is the caller's attestation.
4. **Independent safeguards:**
   - a fresh `evaluate_new_trade` on the snapshot with the administrative pause **masked**
     (`mask_administrative_pause`), so an independent daily/weekly/drawdown/loss-streak halt is
     visible instead of hidden behind the existing pause. Its reason must be in a fixed allowlist of
     non-halt reasons (clean pass, size reductions, per-trade capacity refusals, none of which
     `record_risk_decision` ever persists as a pause). A risk-limit reason blocks; a pause reason
     echoed back blocks as `pause_not_masked`; anything unrecognised blocks.
   - `loss_streak_halt_active` from `shared.risk_epoch.loss_streak_state()` must be `False`.
   `assess_technical_resume` returns `Assessment(eligible, halt_class, blockers, ...)` with fixed
   blocker codes: `not_technical_halt`, `halt_history_incomplete`, `halt_provenance_not_technical`,
   `clock_invalid`, `check_malformed`, `check_stale`, `check_from_future`, `inputs_non_finite`,
   `price_coverage_incomplete`, `fresh_evaluation_invalid`, `pause_not_masked`,
   `independent_risk_halt_active`, `unrecognised_decision_reason`, `loss_streak_halt_active`,
   `insufficient_clean_checks`, `clean_checks_invalid`, `clean_checks_outside_window`.
5. **Explicit two-step owner approval:**
   - step one, `issue_resume_challenge(assessment, pause_row_id, now, ttl_s=300)`: refuses unless
     eligible and refuses a naive clock; binds a 128-bit random single-use nonce to the pause row id
     and a digest of the assessment (class, reason, eligibility, blockers, fresh decision reason,
     halt provenance, history completeness; no timestamps). The `nonce_bytes` parameter is a
     test-only injection point.
   - step two, `verify_resume_confirmation(challenge, given_nonce, current_pause_row_id,
     current_assessment, now, used_nonces)`: the caller recomputes a **new** fresh check first. Fixed
     result codes: `confirmed`, `malformed_request`, `challenge_from_future`, `challenge_expired`,
     `nonce_replayed`, `nonce_mismatch` (constant-time compare), `pause_row_changed`,
     `no_longer_eligible`, `assessment_changed`. On `confirmed` the nonce is recorded as used. A
     hand-built or corrupted challenge (naive `issued_at`/`expires_at`, non-string or short nonce,
     non-integer row id) or an assessment that cannot be digested returns `malformed_request`; the
     function never raises on such input.
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
- No downgrade of a halt class and no softer handling of `UNKNOWN`. Note the qualification: the
  **runtime** can and does relabel a risk-limit or manual halt as `risk:invalid_risk_state` (1.4);
  this change does not alter that runtime behaviour. It makes the module refuse to rely on the label:
  a relabelled halt is ineligible through its provenance (`halt_provenance_not_technical`), and a halt
  whose history cannot be shown complete is ineligible (`halt_history_incomplete`).
- Missing or non-finite market state still yields NaN and `invalid_risk_state`.
- `trade_tracker/main.py`, `shared/risk_management.py`, `shared/trading_state.py`,
  `shared/risk_epoch.py`, `telegram/main.py`: untouched.

---

## 4. Wiring plan (later; separate owner approval required)

- **Telegram handlers** (owner-restricted, like `cmd_resume`):
  - `/resume_technical`: read `get_pause_state` and the latest decision row id; collect the pause
    history since the last resume (below); compute the fresh check; `assess_technical_resume`; if eligible, `issue_resume_challenge` and reply with the
    nonce, the class and the expiry minute; otherwise reply with the blocker codes only.
  - `/confirm_resume <nonce>`: recompute a fresh check, re-read the pause row id,
    `verify_resume_confirmation`; on `confirmed` run the existing `cmd_resume` statement and its
    loss-streak follow-up message unchanged.
  - Challenge and used-nonce store kept in process memory (lost on restart, which only forces a new
    challenge: fail-closed).
- **Where the provenance comes from** (both non-protected; the caller reads reasons only):
  - Scanner log: `scanner/scanner_logic.py` logs `⏸️ التداول موقوف - السبب: <reason>` on **every**
    paused cycle, with the exact `get_pause_state` reason (or `غير محدد` if empty, which classifies
    `UNKNOWN` and blocks). The caller collects these lines since the last `manual_resume`.
  - `risk.halted` outbox event: `trade_tracker.main.record_risk_decision` enqueues it only on a
    running-to-halted transition of a tracker hard halt; its payload `reason` is the bare reason
    (classified like the prefixed one). It is **not** emitted for `/pause` (`cmd_pause` writes the row
    and logs nothing), nor for a relabel while already paused, so it can confirm the origin of a
    tracker halt but never prove the absence of a later overwrite. Its other payload fields are
    protected values and must not be read for this purpose.
  - `history_complete` may be `True` only if the scanner log covers the whole interval since the
    last resume with no gap longer than one scan cycle. Residual risk, stated plainly: the log is a
    per-cycle sample, so a `/pause` immediately overwritten by a timeout within one cycle would not
    appear; the owner, who issued any `/pause`, must not approve a technical resume after one.
- **Where the fresh check is computed:** a read-only helper in the tracker that reuses
  `assess_new_trade_risk`'s snapshot construction with the pause masked, counts requested vs usable
  prices against the open-position count, and records the timestamps of consecutive clean results
  across N spaced evaluations (passed as `clean_check_times`). It must not call
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
