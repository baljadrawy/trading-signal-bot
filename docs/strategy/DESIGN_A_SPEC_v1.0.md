# Design A v1.0: BTC/USDT weekly SMA200 long/cash

**Status:** Saved on the development branch `feature/design-a-v1` for independent review only.
- Not Integrated, Deployed or Validated, in the terms of `OWNER_OPERATING_CONTRACT.md` §2.
- D0 work only (specification, an inactive offline package and synthetic tests), with no runtime effect.
- The handoff records the commit and the push.

**Package:** `research/design_a/` (`VERSION = "design-a-v1.0"`). It is research only and never imported by production.

**Base:** `origin/main` at `eba90dd`.

**Owner decisions (2026-10-31).** Both are binding:
- weekly retries of transitions that did not execute (F10), recorded in §2;
- the minimal durable candle-integrity mechanism for offline replay and resume (§5), proposed in R14 and implemented in R15.

**Owner brief:** "Trading Signal Bot — Design A v1.0: Specification, Minimal Implementation & Synthetic Validation" (2026-10-30). It is cited below as *the brief* (§n = brief section n).

**Labels.** Each normative statement carries one label. They follow the brief's Phase B categories:

| Label | Meaning |
|---|---|
| **FROZEN** | Fixed by the brief; implemented exactly where v1.0 implements it (benchmarks, metrics, diagnostics and the adapter are not implemented). Where only part of a statement is fixed, the rest is labelled separately. |
| **APPROVED** (path) | A pre-existing, owner-approved repository rule, cited by path. |
| **PROPOSED** | Proposed but **unapproved**. It is either:<br>• *implemented, provisional*: a convention the code cannot work without. It lives in a named place and is tested; an owner decision confirms or replaces it;<br>• *definition only*: prepared for a later, approved evaluation and not implemented. |
| **OPEN** | Requires an owner decision (§19 item n). |

Known modelling limitations are listed in §20.

A29–A34 are not in this worktree: they live at local commit `54a6369`, held under OD-1/OD-2. They are cited only through repository documents that quote them, and nothing here infers their content.

**"D1" has three meanings in this repository.** They are kept apart here:
- **class D1** of `docs/governance/DEVELOPMENT_FIRST_POLICY.md` §2 (historical evaluation on real data);
- the A29 **"D1/D2 HOLD"** for governed confirmation (`OWNER_OPERATING_CONTRACT.md` §4);
- the review-log IDs, which are X1–X16 and R1–R15 (§23).

---

## 0. Status and authorization

**Authorized now (class D0):**
- this specification;
- the isolated, offline package `research/design_a/`;
- synthetic-only tests;
- a commit and push of the development branch for review.

Sources: `DEVELOPMENT_FIRST_POLICY.md` §2 row D0; the brief §13–§15.

**Not authorized, and not done:**
- historical evaluation or any backtest on real data (class D1);
- any real dataset, exchange APIs, the network, databases, protected data;
- Paper or live trading, production or UAT changes, deployment, a scheduler;
- integration into the scanner, signal engine, Telegram or tracker;
- merge, a new PR, an LCE run, any claim that CI passed;
- changes to PR #96 or to the LCE review branch;
- S5 admission;
- computing any benchmark or metric (§14, §15);
- an outcome classification procedure (§17).

These follow from the brief §3, §13 and §14. The brief's "Not authorized: Merge to main" prevails over the general D0 merge allowance in `DEVELOPMENT_FIRST_POLICY.md`: it is the later explicit owner decision (`OWNER_OPERATING_CONTRACT.md` §5).

**Evidence class.** Everything v1.0 can produce is `SYNTHETIC` (`state.EVIDENCE_CLASS`). A synthetic result is never evidence of an edge (APPROVED, `DEVELOPMENT_FIRST_POLICY.md` §3). Passing software tests is not profitability (FROZEN, the brief).

---

## 1. Economic hypothesis

**H-A (FROZEN, the brief §9).**
- The strategy attempts to reduce exposure during sustained BTC bear-market regimes, while participating in upward trends.
- It is not assumed to predict short-term returns.
- Its value must be demonstrated **after costs** and **relative to passive exposure**.
- Drawdown reduction alone does not prove timing skill.

**Comparison (FROZEN, the brief §10).**
- The primary comparison is Design A against **B1**: buy-and-hold with comparable acquisition costs.
- B2 and B3 are descriptive diagnostics, never an independent proof of market-timing skill.

*Commentary, not a rule.* A rule that is sometimes in cash tends to lower drawdown and volatility mechanically. `docs/strategy/S4_MECHANISM_COMPARISON.md` says the same of long-only trend rules: they are "mostly timed beta, so [the] baseline must be buy-and-hold … not cash".

**Hypothesis source: OPEN (§19 item 2); nothing is declared in code.**
- **The requirement is APPROVED** (`docs/research_temporal_governance.md`): every hypothesis declares `PRE_EXISTING`, `DISCOVERY_DERIVED` or `EXTERNAL_THEORY`.
- **The evidence the owner needs:**
  - a 200-day average trend filter is widely published prior knowledge;
  - this repository's own earlier research used a BTC EMA200 regime filter: BTC > EMA50 and BTC > EMA200, translated from the Arabic of `analyzer/MODEL_FROZEN_SPEC.md`, computed in `analyzer/momentum_ls.py`, `analyzer/indep_verify.py` and `analyzer/momentum_stress.py`;
  - `research/governance/pre_existing_knowledge.json` has no matching entry (a count-only search);
  - `research/governance/hypotheses.jsonl` is empty.
- **The choice is not made here.** Whichever source is chosen, Design A cannot be presented as a new, independent discovery.

---

## 2. Strategy rules

The rule text is **FROZEN** (the brief §4–§8). Readings the brief leaves open are labelled where they occur.

**Market**
- **F1.** BTC/USDT spot, with one reference venue reached through an exchange-agnostic data adapter. v1.0 ships no adapter; its fixtures are fabricated in code.
- **F2.** No derivatives, leverage, shorts, margin, market making or cross-sectional rotation.

**Signal**
- **F3.** The SMA of 200 completed UTC daily closes, with a window that includes the latest completed Sunday candle.
  - That the 200 candles must be **consecutive** calendar days is PROPOSED (implemented, provisional; OPEN §19 item 16).
  - Its consequence is in §8.
- **F4.** The arithmetic mean of those 200 closes (FROZEN). That the comparison is computed exactly, without division (`200 × close_Sunday > Σ closes`), is PROPOSED with the `Decimal` realisation (§10). The SMA is also reported, and it is exact because 1/200 terminates in decimal.
- **F5.** `LONG` if the Sunday close is greater than SMA200, and `FLAT` otherwise. **Equality is FLAT.**
- **F6.** No hysteresis band, discretionary override or additional indicator.

**Decision schedule**
- **F7.** Decisions are taken at **Monday 00:00 UTC plus 30 seconds** (`DECISION_OFFSET_SECONDS = 30`).
  - At any other instant, `decide()` returns `NO_SIGNAL`, which changes nothing.
  - A `NO_SIGNAL` dated at a decision instant is refused.
  - That `NO_SIGNAL` is a value, not an exception, is PROPOSED (implemented, provisional).
- **F8.** Future observations are never used. Only completed candles enter a snapshot (§3, §5).

**Position**
- **F9.** The target exposure is 100 % BTC when `LONG` and cash when `FLAT`. The portfolio starts in cash.
- **F10.** "Do not rebalance when the target state is unchanged. Execute only genuine state transitions."
  - **Owner decision, 2026-10-31 (APPROVED, binding):** at each valid weekly decision, a new pending transition opens whenever the newly computed target **differs from the actual tradable position**, even if the target is unchanged from the previous week. That covers an earlier order that:
    - expired without execution;
    - was rejected by the minimum-order rules;
    - or otherwise did not execute.
  - **Limits:**
    - no retry between weekly decisions;
    - no rebalance of a correctly positioned portfolio;
    - no duplicate of an executed order;
    - the minimum-order rules always apply;
    - if the signal changes before a retry, the latest valid signal governs;
    - a skipped decision (missing or invalid signal data) creates no order.
  - **Implementation:** `state.required_action`. The ledger marks such a transition `PENDING_* (RETRY)`, or `PENDING_* (NEW_TARGET)` when the target changed.
- **F11.** Residual balances, dust included, are preserved and never rounded to zero.
- **F12.** No fill is fabricated to force an exact allocation.

**Warm-up and data**
- **F13.** 200 valid completed daily candles are required before the first actionable decision.
- **F14.** Missing, duplicate, incomplete and inconsistent candles are handled explicitly.
  - Never repairing, forward-filling or interpolating is APPROVED (`docs/research_temporal_governance.md`).

**Execution timing (FROZEN research assumption, the brief §5)**
- **F15.** A decision creates a pending target transition, not an immediate portfolio change.
- **F16.** The execution reference is the **open** of the Tuesday 00:00 UTC daily candle.
  - The brief calls the roughly 24-hour delay "a deliberate, conservative research-model assumption".
  - The opening print is a benchmark reference, not a guaranteed executable quote. Half-spread and slippage are applied.
  - **Two timestamps are kept apart.** The reference price carries the open's timestamp, Tuesday 00:00 UTC (`reference_time`, the event time). The model only learns it when the complete Tuesday candle becomes available, Wednesday 00:00 UTC under §5 (`at`, the booking time).
  - An `EXECUTED` entry is a **modelled** execution at that reference price. It is not a claim that a live order could have filled at the opening print. No change to the reference-price convention without owner approval.
- **F17.** A pending transition executes only at a reference strictly after the decision.
- **F18.** If the scheduled candle is unavailable, execution defers to the next available completed daily candle within **three calendar days** of the decision timestamp.
  - **Reading (PROPOSED, implemented, provisional; OPEN §19 item 11):** the window is measured on the reference **open**, as `decided_at < open_time ≤ decided_at + 72 h`. It covers the Tuesday, Wednesday and Thursday opens.
- **F19.** After expiry, the transition is cancelled and the cancellation recorded. Holdings are kept, no missing price is synthesized, and nothing is executed retroactively.
- **F20.** If the required Sunday candle is unavailable, the weekly decision is skipped and holdings are kept.
- **F21.** Event time and data-availability time are distinct, and publication timestamps are never invented (§5).

**Costs (FROZEN, the brief §6; §10)**
- **F22.** Fee 0.10 % per side in both scenarios. Half-spread 0.05 % baseline, 0.10 % stress. Slippage 0.05 % baseline, 0.10 % stress.
- **F23.** Costs arise only when a trade executes: never per candle, never twice.
- **F24.** `P_buy = P × (1 + hs + sl)`; `P_sell = P × (1 − hs − sl)`.
- **F25.** `BTC_bought = Cash / (P_buy × (1 + fee))`; `Cash_after = Cash − BTC_bought × P_buy × (1 + fee)`.
- **F26.** `Cash_received = BTC_sold × P_sell × (1 − fee)`.
- **F27.** The fee is quote currency, charged on top of the buy notional.
- **F28.** Accounting is deterministic and conserves assets within the fee model.
  - "Deterministic arithmetic appropriate for financial accounting" is FROZEN.
  - Its realisation in `Decimal` is PROPOSED (§10).

**Portfolio and interface**
- **F29.** The following are modelled separately: actual cash, actual BTC, target state, pending transition, execution status, cost components, residual balances, portfolio equity and the ledger.
- **F30.** A buy that fails the configured minimum notional or quantity:
  - does not execute;
  - preserves cash;
  - records the reason;
  - never becomes a smaller invented fill.
- **F31.** Sell dust stays in the ledger and keeps being marked to market. Residual exposure is reported during FLAT periods.
- **F32.** Minimum-order rules are explicit configurable inputs. No exchange values are hard-coded.
- **F33.** The brief prefers a pure `decide(state, snapshot) -> decision`, which is implemented.
  - Signal, timing/validation and execution/accounting live in separate modules, with no generic framework.
  - The strategy is inactive and isolated, with no integration anywhere (FROZEN).
- **F34.** The primary configuration is weekly SMA200 (`decision.SMA_WINDOW = 200`, a constant).
  - The four pre-registered diagnostics (§18) are not implemented.
  - No parameter search, optimisation or adaptive tuning.

---

## 3. Data contract

The candle shape and the refusal set are PROPOSED (implemented, provisional; OPEN §19 item 16). The brief defines no candle fields.

**`Candle(open_time, open, high, low, close)`.** It is the UTC daily candle of the interval `[open_time, open_time + 1 day)`.

| Field | Rule |
|---|---|
| `open_time` | a `datetime` whose `tzinfo` is `datetime.timezone.utc`, exactly 00:00 UTC. Another UTC-equivalent `tzinfo`, such as `ZoneInfo("UTC")`, is refused. |
| `open`, `high`, `low`, `close` | `Decimal`, finite, strictly positive; `low ≤ open ≤ high` and `low ≤ close ≤ high` |

- **No end stamp.** The contract has none. An adapter maps any venue convention, Binance's `open + 1 day − 1 ms` for instance, to the UTC open day.
- **No volume.** No v1.0 rule uses volume.

**`Snapshot(as_of, candles, permission)`** holds the completed daily candles available at `as_of`, oldest first. Its constructor refuses:
- a **future** candle (`open_time ≥ as_of`);
- an **incomplete** candle, still open at `as_of`;
- a duplicate or unordered `open_time`: no valid interpretation exists, so nothing is chosen;
- any permission other than the synthetic one.

The first two implement the brief's test 6: "Rejection of future and incomplete candles". Because of them, no snapshot object can carry a later observation, not even an unused one.

**Permission** (APPROVED gate `research/mechanisms/simulate.py` `DatasetPermission`; `DEVELOPMENT_FIRST_POLICY.md` §2 row D1).
- Only the synthetic permission itself is accepted: exact type and value (`SYNTHETIC`). Every other permission is refused, including one whose self-declared `allows()` is true, or a subclass.
- The permission is a declaration, so v1.0 adds a mechanical guard (PROPOSED, implemented): a synthetic snapshot must be dated before 2009-01-03, Bitcoin's first block.
  - This blocks data carrying real BTC dates (2009 onward, including the forward holdout).
  - It is **an additional safeguard, not proof of synthetic provenance**: real prices re-dated before 2009 would pass.
  - Provenance rests on the permission declaration and on review. The permission check itself is unchanged.

**Adapter.** FROZEN F1 requires an exchange-agnostic data adapter; v1.0 ships none. That the package consumes `Snapshot` objects only, and never reads files, databases, environment variables or the network, is PROPOSED (implemented).

**Forward-holdout partition guard: not implemented.**
- It would have to choose the partition key, which is OPEN (§19 item 7).
- It would add nothing while only synthetic data is accepted.
- It is required before any real-data use.
- `FORWARD_HOLDOUT` stays sealed: v1.0 accepts only the synthetic permission, and only snapshots dated before 2009-01-03.

---

## 4. UTC timestamp semantics and the weekly calendar

| Instant | Definition | Label | Code |
|---|---|---|---|
| Decision instant | Monday 00:00 UTC plus 30 seconds (weekday 0, hour 0, minute 0, second 30, microsecond 0) | FROZEN | `state.is_decision_instant` (also exported by `timing`) |
| Latest completed Sunday | the candle opening one day before the decision date | FROZEN | `timing.latest_sunday_open` |
| Scheduled reference | the candle opening on the Tuesday 00:00 UTC after the decision; its open | FROZEN | `timing.scheduled_reference_open` |
| Signal window | the 200 **consecutive** daily candles ending with that Sunday | PROPOSED (§19 item 16) | `timing.signal_window` |
| Deferral window | reference opens with `decided_at < open_time ≤ decided_at + 72 h`: Tuesday, Wednesday, Thursday | PROPOSED (§19 item 11) | `PendingTransition`, `ledger.execute_pending` |
| Next decision instant | the first decision instant strictly after a given instant | PROPOSED (replay check) | `timing.next_decision_instant` |

The Monday candle opens 30 seconds before the decision, so it can never be a reference (F17).

---

## 5. Data-availability assumptions

**Event time versus availability time (FROZEN F21).**
- A candle's event interval is `[open_time, open_time + 1 day)`, and a fill's event time is the reference candle's `open_time`.
- Availability time is when a consumer could first observe the completed candle. No publication timestamp exists in v1.0, and none is invented.

**v1.0 rule (PROPOSED, implemented, provisional; OPEN §19 item 1).** A candle is available from the end of its UTC day (`state.available_from(open_time) = open_time + 1 day`). That assumes publication within the frozen 30-second decision offset. Consequences:
- **Visibility.** The Sunday candle is visible at the Monday decision instant.
  - Any availability model with a latency of 30 seconds or more would make every Sunday unavailable at the decision. Every week would then be `SKIP_MISSING_SUNDAY`, unless the policy also says what happens to a late Sunday: skip, or a delayed decision.
  - A per-candle availability stamp would also change the `Candle` contract.
- **Booking.** A fill is known when its reference candle completes.
  - The ledger books it then (`at` = the end of the reference day), and records its event time separately (`reference_time`).
  - A missing reference and an expiry are booked when the candle was due.
  - For data that never arrive late, the ledger therefore does not depend on how often a caller checks. Daily, weekly and every-third-day checks give the same digest on the clean path, a Thursday fill with a rejection and dust, and an expiry.
  - `replay` refuses a candle that changes between the snapshots of one call (revised data). Across calls and restorations, the integrity mechanism below refuses it.
- **Late data.** A candle recorded missing is never used afterwards, even if it turns up later.
  - Without availability stamps, a sparse check cannot tell a late-arriving candle from a timely one.
  - Data that change between snapshots can therefore change results. This is an availability-policy question.
- **Single source.** The rule is defined once, in `state.available_from`. `timing.is_available`, `timing.is_overdue` and the `Snapshot` constructor apply it.

**Candle integrity across replay calls and restorations.** This is the owner-approved mechanism (2026-10-31). It is implemented in `state.py` and `ledger.py`, with the window check in `decision.decide`. It needs no database, service or new storage: the evidence lives in the existing state and ledger.

*Evidence.* No candle history is stored twice.
- **Fingerprint** (`state.candle_fingerprint`): the repository's `canonical_hash` (sha256 of sorted-key JSON) of:
  - the open time, in ISO 8601 UTC;
  - the normalised text of `open`, `high`, `low` and `close`.

  Equal numbers give equal fingerprints, so trailing zeros are not a revision. Any other change is.
- **Index** (`State.consumed`): one `(open time, fingerprint)` pair per candle that a decision window or an execution attempt has read, in strictly increasing order. Overlapping windows share entries: the 540-day fixture ends with 536.
- **Ledger cross-references:**
  - each `DECIDE_*` entry carries `window_digest`, the `canonical_hash` of its 200 window fingerprints, oldest first;
  - each `EXECUTED` and `REJECTED_MIN_ORDER` entry carries `reference_fingerprint`;
  - no other entry may carry either.
- **Digest.** All three are part of `state_record`, so they are in the canonical state digest.

*Checks.* Each refuses with `DesignAError`. None repairs anything, and none turns a refusal into a skip.
1. **Before processing.** Before `decide` or `execute_pending` processes a snapshot, every consumed candle in the snapshot's coverage (below) must be present and identical (`state.check_consumed`, called from `check_inputs`).
2. **When evidence is added** (`state.merge_consumed`), a fingerprint that differs from the indexed one is refused. This catches, for example, a hand-built decision whose window contradicts the index.
3. **At the start of every `replay` call and on every restoration** (`state.verify_integrity`), every window digest and reference fingerprint must match the index, and the index may hold nothing else.
4. **On restoration** (`ledger.state_from_record`, which restores a state from `state_record` output, for example after JSON serialisation), three kinds of record are refused:
   - a malformed record;
   - a non-canonical one, which the restored state would not reproduce exactly: an unknown key, another spelling of an instant, a JSON number where text is expected;
   - one that fails check 3.

*Coverage and missing candles.* Missing data is never treated as matching.

| A candle that is … | … and missing from a snapshot | Result |
|---|---|---|
| consumed | between the snapshot's first candle and its `as_of` | refused: "previously consumed candle … is missing" |
| consumed | before the snapshot's first candle, but inside the window the decision at that snapshot reads | refused in the same way: `decide` extends the coverage to its window |
| consumed | before both | not re-checked by that snapshot: nothing it can decide or execute reads the candle. A source that keeps a shorter history still works, provided it covers each decision's window. |
| consumed, but complete only after the snapshot's `as_of` | — | not expected in that snapshot |
| never consumed | anywhere | the existing missing-data rules (§6–§8): warm-up, a gap or missing-Sunday skip, deferral, expiry. It becomes evidence only once a window or an execution attempt reads it. |

- **Revision.** A revised consumed candle inside the coverage is refused: "candle … differs from the one consumed earlier".
- **A candle lost after use.** A consumed candle that is lost later is therefore refused wherever the coverage includes it, not treated as a gap. The 28–29-week skip of §8 applies only to a candle that was never consumed.
- **No partial results.** `replay` refuses the whole call, so it returns no state from it.

*Determinism.*
- **Context independence.** Fingerprints use the fixed `EXACT` context and `state.text`, so neither the ambient decimal context nor the hash seed matters. The index is sorted.
- **Cadence.** Daily, weekly and every-third-day cadences consume the same candles, so they still give the same digest.
- **Process boundary.** A state saved by one interpreter resumes to the uninterrupted digest when it is restored by another interpreter, with a different hash seed and a hostile decimal context (tested).

*What the checks do not establish.*
- **Consistency, not authenticity.** sha256 detects any difference between the data a call receives and the data consumed earlier, and between the index and the ledger. But nothing is keyed or signed, and nothing is anchored outside the record. So:
  - whoever can edit a saved record and the snapshots can rewrite the fingerprints, the index and the window digests to match altered candles, and every check would pass;
  - a history forged consistently from the start is undetectable.

  Authenticity against coordinated tampering would need a keyed MAC, a signature or an external anchor. That is new infrastructure, outside v1.0.
- **Only consumed candles are evidence.** This is a known limitation, pinned by `test_known_limitation_unconsumed_candles_are_checked_within_one_call_only`.
  - **Which candles.** Some are delivered before a cut but not yet read by a decision or an execution attempt:
    - every candle before the first actionable decision;
    - afterwards, the candles after the Sunday of the latest actionable decision, apart from reference candles already used. Skipped decisions read nothing.
  - **Detection.** Such a candle is checked for revision only within one call.
  - **Effect.** If it is revised after the cut, its first use takes the revised value. An uninterrupted replay over the same snapshots would have refused it.
  - **Fix.** Recording every delivered candle's fingerprint would close this. That would extend the approved mechanism, so it is left to the owner.
- **Not authorization.** The checks compare only data already admitted under the permission (§3), and the permission check runs first. Passing them never authorizes access to any historical, real or protected data. v1.0 still accepts only the synthetic permission.
- **No provenance.** A matching fingerprint says nothing about where a candle came from (§3).

**Policy (FROZEN requirement, the brief §5).** "If the data are unavailable at the scheduled decision time, the data-availability policy must be explicitly specified before historical evaluation." That covers which dataset, licence record, freeze and availability model would ever feed `decide()`. It is OPEN (§19 item 1).

---

## 6. Warm-up

- **WARMUP (FROZEN F13 for the 200-candle requirement; the classification is PROPOSED, §19 item 16).**
  - The **initial** decisions are `WARMUP` while history has not yet reached 200 days:
    - either there are no candles;
    - or every missing window day precedes the earliest candle.
  - 199 completed candles ending on Sunday give `WARMUP`. 200 give a valid SMA.
- **After the first actionable decision.** The same shortfall is `SKIP_INVALID_DATA` (reason `INSUFFICIENT_HISTORY`), because warm-up is only the initial state (the brief §7).
- **Gaps.** A missing day after history has started is a gap, `SKIP_INVALID_DATA` (`GAP_IN_WINDOW`), even when fewer than 200 candles exist.
- **Effect.** Warm-up keeps the portfolio in cash: no target, no pending transition.
- **Influence of older candles.** No close before the window start enters the SMA. Earlier candles matter only for snapshot validity and for telling warm-up from a gap.
- **Order of checks** (PROPOSED):
  1. no candles at all gives warm-up, or `SKIP_INVALID_DATA` (`INSUFFICIENT_HISTORY`) after a decision;
  2. then a missing Sunday gives `SKIP_MISSING_SUNDAY`;
  3. then a gap or late start inside the window gives the result above.

  Before all three, the owner-approved integrity checks (§5) refuse a consumed candle that is revised, or missing within the coverage. So these steps only ever meet missing candles that were never consumed.

---

## 7. Execution delay and pending transitions

**Lifecycle.** FROZEN F15–F19, except where marked **P** (PROPOSED, implemented, provisional; OPEN §19 item 11).

1. **`apply_decision(state, decision)`** records the decision.
   - It opens `PendingTransition(side, decided_at, next_open = Tuesday 00:00 UTC)` whenever the target differs from the actual tradable position (F10, owner decision), with reason `NEW_TARGET` or `RETRY`. Otherwise it records `NO_CHANGE` (`ALREADY_AT_TARGET`).
   - Balances never change here.
   - The status becomes `PENDING`, and the entry records `expires_at = decided_at + 72 h` (the 72 h reading is **P**).
2. **`execute_pending(state, snapshot)`** works through the candidate references in order: Tuesday, then Wednesday, then Thursday (**P**).
   - **The candidate is available:** fill at its open with the §10 formulas and the §11 rules. Record `EXECUTED` or `REJECTED_MIN_ORDER`, booked at the end of the reference day (**P**).
   - **The candidate is due but absent:** record `MISSING_MARKET_DATA` (booked when it was due, **P**), set the status to `DEFERRED`, and move to the next day.
   - **No candidate remains within the window:** record `EXPIRED`, booked when the Thursday candle was due (Friday 00:00 UTC, **P**), with `expires_at`. Clear the pending transition.
   - **The candidate is not yet due:** nothing is recorded; the transition waits.
3. **Once `EXECUTED` or `EXPIRED`,** `state.pending` is `None`. So it is after `REJECTED_MIN_ORDER` (reject-ends is **P**, §11). One decision gives at most one fill.

**Never** (FROZEN):
- execute at a price not in the snapshot;
- execute at a candle opening at or before the decision;
- use a reference candle opening more than three calendar days after the decision;
- execute twice for one decision;
- change holdings on a decision.

**P consequences:**
- **Thursday fills.** A fill at the Thursday open becomes known only on Friday, after `expires_at`. The reference is inside the window in event time; the booking is not (§23 X9).
- **No retroactive use.** A candle recorded missing is never used later.
- **No retry inside the window.** `REJECTED_MIN_ORDER` ends the transition, and minimum-order failure does not defer.
- **After expiry or rejection (owner decision, F10).** The next valid weekly decision retries if its target still differs from the actual tradable position.
  - The retry follows the original schedule: the Tuesday reference, the 72 h window, the same costs and minimums.
  - It changes no balance until a modelled fill.
  - A skipped decision does not retry. A changed signal replaces the retry.
  - A balance that the minimum notional blocks is retried, and may be rejected again, at each valid weekly decision. Each attempt is recorded.
- **Resolution timing.** A pending transition resolves by Friday 00:00 UTC at the latest. With only weekly snapshots, it resolves at the next Monday snapshot, before that decision. `apply_decision` refuses while one is unresolved.

---

## 8. Missing-data behaviour

At the decision instant:

| Situation | Result | Holdings | Label |
|---|---|---|---|
| Not the decision instant | `NO_SIGNAL` (not recorded) | unchanged | FROZEN schedule; value form PROPOSED |
| No history, or history starts inside the window without a hole, before any actionable decision | `WARMUP` (`INSUFFICIENT_HISTORY`) | unchanged (cash) | FROZEN F13; classification PROPOSED |
| The same shortfall after an actionable decision | `SKIP_INVALID_DATA` (`INSUFFICIENT_HISTORY`) | unchanged | PROPOSED |
| Sunday candle unavailable | `SKIP_MISSING_SUNDAY` (`SUNDAY_CANDLE_UNAVAILABLE`) | unchanged | FROZEN F20 |
| A day missing inside the window after history started | `SKIP_INVALID_DATA` (`GAP_IN_WINDOW`) | unchanged | FROZEN F14; rule PROPOSED |
| Future or incomplete candle, duplicate or unordered time, malformed candle, non-synthetic permission | refused at construction (exception) | unchanged | FROZEN F8/F14; refusal set PROPOSED |
| A consumed candle revised, or missing within the coverage (§5) | refused (exception), before any rule above | unchanged | owner-approved (2026-10-31) |

**Consequence of the consecutive-window rule (disclosed; OPEN §19 item 16).**
- One permanently lost daily candle blocks **every** weekly decision whose 200-day window contains it. That is 28 or 29 consecutive decisions (about 200 days), with holdings frozen throughout. A test pins this.
- This applies to a candle lost before any decision consumed it. A candle lost **after** a decision consumed it is refused instead (§5).
- The brief requires "200 valid, completed daily candles"; it does not say "consecutive".
- **Alternatives for the owner:**
  - the 200 most recent available closes, so the window spans more than 200 days;
  - a bounded gap tolerance;
  - the current strict rule.

At execution:

| Situation | Ledger | Holdings |
|---|---|---|
| Scheduled Tuesday candle available | `EXECUTED` at the Tuesday open | changed by the fill |
| Tuesday due and absent; a later candle within the window available | `MISSING_MARKET_DATA` (Tuesday), then `EXECUTED` at that candle's open | changed by the fill |
| No candle within the window | `MISSING_MARKET_DATA` for each due day, then `EXPIRED` | unchanged |

---

## 9. State machine

**State (FROZEN F29; `state.State`, a frozen dataclass).**

| Field | Meaning |
|---|---|
| `cash`, `btc` | actual balances |
| `costs`, `rules` | the `CostSpec` and `MinOrderRules` inputs |
| `target` | the latest decided target (the intended state); `None` before the first actionable decision |
| `pending` | the `PendingTransition` or `None` |
| `execution_status` | `PENDING` or `DEFERRED` while pending; otherwise the outcome of the latest transition: `EXECUTED`, `EXPIRED` or `REJECTED_MIN_ORDER` |
| `last_decision_at` | the decision clock; refuses a repeated or older decision |
| `ledger` | append-only tuple of `LedgerEntry`; each entry carries the balances after it |
| `consumed` | the integrity index (§5): one `(open time, fingerprint)` pair per candle read by a decision window or an execution attempt |

- **Invariants** (constructor):
  - a pending transition exists exactly while the status is `PENDING` or `DEFERRED`;
  - it belongs to the last decision and to its target;
  - the ledger holds only `LedgerEntry` objects;
  - `consumed` holds `(00:00 UTC open time, sha256)` pairs in strictly increasing order.
- **More invariants:**
  - ledger entries are numbered 0, 1, … in time order;
  - the last entry carries the current balances;
  - every entry's prices, quantities and costs are valid `Decimal`s, and its `window_digest` and `reference_fingerprint`, when present, are sha256 values;
  - the window digests and reference fingerprints agree with `consumed`. The constructor does not check this, because it would rehash every window. `verify_integrity` checks it at every `replay` call and every restoration (§5).
- **Immutability.** Operations never mutate a `State`. They return one: for `NO_SIGNAL` the same object, otherwise a new one.
- **Serialisation.** `state_record` is the canonical, JSON-ready description. `state_from_record` restores exactly that record, or refuses it (§5).

**Actual position (PROPOSED, implemented, provisional).**
- It is `LONG` iff the BTC balance, rounded down to `qty_step`, is positive and at least `min_qty`; otherwise `FLAT`.
- From the frozen start in cash it is unambiguous. After a buy, only cash too small for one more step remains. After a sell, only BTC below one step remains. A test checks both on every fill of both replays.
- A state holding both a tradable BTC balance and buyable cash can only be constructed directly. It is outside the v1.0 contract: it is classified by its BTC, and no rebalance is defined for it.

**The brief's required states and events (§7):**

| Brief | Implementation |
|---|---|
| Initial warm-up | `WARMUP` |
| No signal | `NO_SIGNAL` |
| LONG target / FLAT target | `DECIDE_LONG` / `DECIDE_FLAT`; `state.target` |
| Pending buy / pending sell | `PENDING_BUY` / `PENDING_SELL`; `state.pending`; status `PENDING` |
| Executed transition | `EXECUTED`; status `EXECUTED` |
| Skipped decision | `SKIP_MISSING_SUNDAY`, `SKIP_INVALID_DATA` |
| Expired transition | `EXPIRED`; status `EXPIRED` |
| Rejected order (minimum order) | `REJECTED_MIN_ORDER`; status `REJECTED_MIN_ORDER` |
| Missing market data | `MISSING_MARKET_DATA`; status `DEFERRED` |
| Residual BTC dust | `RESIDUAL_DUST`; `valuation().residual_btc` |
| (no genuine transition) | `NO_CHANGE` |

**Reason codes:**

| Event | Reason | Meaning |
|---|---|---|
| `NO_SIGNAL` | `NOT_DECISION_INSTANT` | not Monday 00:00 UTC plus 30 seconds |
| `WARMUP`, `SKIP_INVALID_DATA` | `INSUFFICIENT_HISTORY` | history shorter than the window |
| `SKIP_MISSING_SUNDAY` | `SUNDAY_CANDLE_UNAVAILABLE` | the Sunday candle is absent |
| `SKIP_INVALID_DATA` | `GAP_IN_WINDOW` | a window day is absent |
| `NO_CHANGE` | `ALREADY_AT_TARGET` | the actual tradable position already matches the target |
| `PENDING_BUY`, `PENDING_SELL` | `NEW_TARGET`, `RETRY` | the target changed / the target is unchanged, but the earlier transition did not execute |
| `MISSING_MARKET_DATA` | `REFERENCE_CANDLE_UNAVAILABLE` | a reference candle was due and absent |
| `EXPIRED` | `NO_REFERENCE_WITHIN_THREE_DAYS` | no reference within the window |
| `REJECTED_MIN_ORDER` | `ZERO_QUANTITY`, `BELOW_MIN_QTY`, `BELOW_MIN_NOTIONAL` | the failing minimum |
| `RESIDUAL_DUST` | `BELOW_QTY_STEP` | BTC below one quantity step remains after a sell |

**Transitions:**

| From | Trigger | To | Ledger |
|---|---|---|---|
| any | `NO_SIGNAL` | same | nothing |
| no pending | `WARMUP` or `SKIP_*` | same (target kept) | the decision event |
| no pending | `DECIDE_*`, target equal to the actual position | target updated | decision event, `NO_CHANGE` (`ALREADY_AT_TARGET`) |
| actual FLAT | `DECIDE_LONG` | pending BUY | `DECIDE_LONG`, `PENDING_BUY` (`NEW_TARGET` or `RETRY`) |
| actual LONG | `DECIDE_FLAT` | pending SELL | `DECIDE_FLAT`, `PENDING_SELL` (`NEW_TARGET` or `RETRY`) |
| pending | candidate available, minimums met | LONG / FLAT (+dust) | `EXECUTED` (+`RESIDUAL_DUST`) |
| pending | candidate available, minimums not met | unchanged | `REJECTED_MIN_ORDER` |
| pending | candidate due and absent, window left | pending (`DEFERRED`) | `MISSING_MARKET_DATA` |
| pending | candidate due and absent, no window left | unchanged | `MISSING_MARKET_DATA`, `EXPIRED` |
| pending | candidate not yet due | pending | nothing |

**Invalid transitions** are refused with `TransitionError`. Negative tests cover each of these:
- `execute_pending` with no pending transition (including a second fill for one decision);
- `execute_pending` at or before the decision;
- `execute_pending` with a snapshot older than the last ledger entry;
- `apply_decision` while a pending transition is unresolved;
- the same or an older decision, including a warm-up or skip applied twice;
- a decision older than the last ledger entry;
- a decision computed for a different target or position;
- a decision at a non-decision instant;
- a `NO_SIGNAL` dated at a decision instant;
- a `WARMUP` after an actionable decision.

Some decisions cannot even be constructed:
- a `DECIDE_*` decision whose target contradicts F5;
- one that lacks the Sunday close and SMA;
- one that lacks the fingerprints of its 200 window candles. No other decision may carry any.

`replay` also refuses:
- snapshots out of order;
- a first snapshot that is not later than the state's ledger;
- a candle revised between snapshots;
- any snapshot sequence that skips a decision instant. This avoids silently "staying in cash" when a caller's snapshots miss the exact instant;
- a state whose integrity index disagrees with its ledger;
- a snapshot that revises a consumed candle, or omits one within its coverage (§5).

Within one call, the decision-instant check runs from the first snapshot. When resuming, it runs from the state's last decision. A state that has taken no decision yet carries no clock, so resuming it is the same as starting fresh.

---

## 10. Cost model

**Rates (FROZEN F22): `state.CostSpec(fee, half_spread, slippage, label)`, with no defaults.** `fee` must be below 1, and so must `hs + sl`.

| Scenario | fee | half_spread (hs) | slippage (sl) | per side | round trip |
|---|---|---|---|---|---|
| `BASELINE` | 0.001 | 0.0005 | 0.0005 | 0.20 % | about 0.40 % |
| `STRESS` | 0.001 | 0.001 | 0.001 | 0.30 % | about 0.60 % |

**Fee floor (APPROVED, `OWNER_OPERATING_CONTRACT.md` §1; `research/mechanisms/costs.py`).**
- The 0.10 % per-side floor is checked exactly against `costs.BASELINE_FEE_PER_SIDE`, raising `costs.CostModelError`.
- The `float`-based `CostModel` is not constructed: converting a `Decimal` just below the floor to `float` can round it up and hide it.

**Formulas (FROZEN F24–F26), with `P` the reference open.**

```
buy:   P_buy = P × (1 + hs + sl)
       q = floor_step( Cash / (P_buy × (1 + fee)) )
       notional = q × P_buy
       fee_paid = notional × fee
       Cash_after = Cash − notional − fee_paid
       BTC_after = BTC + q
sell:  P_sell = P × (1 − hs − sl)
       q = floor_step( BTC )
       notional = q × P_sell
       fee_paid = notional × fee
       Cash_after = Cash + notional − fee_paid
       BTC_after = BTC − q
```

- **Rounding to the quantity step is PROPOSED** (part of the minimum-order inputs, §11). It is not in the brief's closed form. It leaves a small residual cash after a buy (0.000997998 in the example below), which the closed form would not.
- **Reported components.** Each fill also reports `spread_cost = q × P × hs` and `slippage_cost = q × P × sl`. They are inside the execution price, never charged again, so `notional = q × P ± (spread_cost + slippage_cost)`.

**Arithmetic (FROZEN: deterministic. PROPOSED, implemented, provisional, §19 item 13: realised in `Decimal`).**
- **Fixed contexts.** All arithmetic runs in two fully specified contexts (`state.EXACT`, `state.FLOOR`): precision 28, explicit exponent range, `capitals`, `clamp` and traps. It never uses the caller's ambient context.
- **What EXACT refuses.** Under `EXACT`, any operation whose exact result needs more than 28 significant digits is refused with `DesignAError`, not rounded. Dropping trailing zeros preserves the value and is allowed.
- **The one floor.** The single inexact step, the affordable buy quantity, rounds toward zero in `FLOOR`.
- **Serialisation.** Decimals are serialised with `state.text`, so a digest does not depend on any context setting.
- **No cash rounding.** Cash is never quantised.

**Conservation (FROZEN F28).** These hold on every fill of both replays:
- **Buy:** `Cash_before = Cash_after + notional + fee_paid` and `BTC_after − BTC_before = q`.
- **Sell:** `Cash_after − Cash_before = notional − fee_paid` and `BTC_before − BTC_after = q`.
- **All other events:** every non-fill entry leaves both balances unchanged.

**Worked synthetic example** (baseline; `qty_step = 0.00001`; cash 1000; buy at `P = 100`, sell at `P = 110`):

| Case | Leg | Execution price | Quantity | Notional | Fee | Cash after the buy / cash received from the sell |
|---|---|---|---|---|---|---|
| Baseline | buy | 100.1 | 9.98002 | 999.000002 | 0.999000002 | 0.000997998 |
| Baseline | sell | 109.89 | 9.98002 | 1096.7043978 | 1.0967043978 | 1095.6076934022 |
| Stress | buy | 100.2 | 9.97006 | 999.000012 | 0.999000012 | 0.000987988 |
| Stress | sell | 109.78 | 9.97006 | — | — | 1093.4186736132 |

These are fabricated numbers.

**No double counting (FROZEN F23).**
- hs and sl enter only through the execution price.
- The fee is applied once per executed leg.
- Nothing is charged on `NO_CHANGE`, `MISSING_MARKET_DATA`, `EXPIRED`, `REJECTED_MIN_ORDER`, warm-up, skips or marking.

**Fee asset (FROZEN F27; documented as the brief §6 requires).**
- The fee is quote currency:
  - added to the buy notional;
  - deducted from the sell proceeds.
- Its base is the hs/sl-adjusted executed notional, as the brief's formulas fix it.
- A venue that deducts the buy fee from the received BTC is a modelling difference (§20), not a change of the approved costs.

**Reconciliation with repository conventions** (documentation only; the approved costs are unchanged):
- **Paper tracker.** It books a flat 0.30 % round trip (`shared/config.py` `FEE_ROUNDTRIP_PCT`; `shared/fees.py`). That is a reporting label beside research costs, never instead of them (APPROVED, `DEVELOPMENT_FIRST_POLICY.md` §3). Design A does not use it.
- **`a48-cost-v1`** (`docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md`, "Cost convention"):
  - **Same:** fees at 0.10 % per side on executed notional; slippage realised once inside the execution price.
  - **Spread:** reported separately, so the term-by-term mapping holds: `fees ↔ fee`, `spread ↔ spread_cost`, `execution slippage ↔ slippage_cost`.
  - **Stress:** Design A's stress uses the fixed 0.10 % levels the brief sets.
- **`research/mechanisms/costs.CostModel`.** It charges `turnover × (fee + hs + sl)`, a first-order version of the same rates. Design A uses only its fee floor and error class.

---

## 11. Minimum-order handling

**Inputs (FROZEN F32): `state.MinOrderRules(min_notional, min_qty, qty_step)`, all `Decimal` and required.**
- `min_notional ≥ 0` and `min_qty ≥ 0`; zero means no minimum.
- `qty_step > 0`. The quantity step is PROPOSED: the brief names only minimum notional and quantity.
- No venue value appears anywhere in the package. The real venue filters are OPEN (§19 item 10).

**Buy (FROZEN F30).**
- The buy is rejected if `q = 0`, `q < min_qty` or `q × P_buy < min_notional`.
- The minimum notional is compared at the execution price, which is PROPOSED.
- A rejection records `REJECTED_MIN_ORDER` with the reason, the quantity and the prices.
- Cash is unchanged. Nothing is charged, and no smaller fill is invented.

**Sell (PROPOSED, implemented, provisional; the brief specifies only the dust rule).**
- `q = floor_step(BTC)`, under the same three checks at `P_sell`.
- **On a failure:**
  - BTC is unchanged and `REJECTED_MIN_ORDER` is recorded;
  - the target is `FLAT` while the actual position stays `LONG`;
  - `valuation` reports the unsold BTC as residual exposure.
- **Otherwise:** exactly `q` is sold, and the remainder is dust (§12).

**Rejection ends the transition** (PROPOSED; OPEN §19 item 10).
- There is no retry inside the window.
- The next valid weekly decision retries while the target still differs from the actual position (F10, owner decision). The minimums apply to every attempt.

---

## 12. Dust and residual exposure

- **Dust is never removed** (FROZEN F11, F31). It stays in `state.btc` and is never deleted, rounded to zero or sold synthetically.
- **When dust arises.** From the frozen start in cash with fixed rules, BTC is always zero or a multiple of `qty_step`, so no dust arises. Dust needs a carried-over balance or a change of rules. The tests (brief items 19–20) and the rough scenario use such non-clean starts.
- **Recording at the sell.** A sell that leaves dust appends `RESIDUAL_DUST`, with `quantity` (the dust) and `mark_price`.
  - The mark is the reference candle's close: the latest close known when the fill is booked.
  - That is a booking-time mark, later than the fill's event time (the open). Under the event-time basis of §13 it must not be read as an event-time valuation.
- **Ongoing reporting.**
  - Every later entry carries the balances.
  - `valuation(state, mark)` reports `residual_btc`: any BTC held unless the strategy is LONG in both intention and fact. A FLAT target or a FLAT position therefore never hides BTC.
  - `residual_value` is that BTC marked to market.
  - `residual_cash` is cash not deployed while the target is LONG.
- **No top-ups.** v1.0 never buys to top up dust (F12). A later buy adds to it.

---

## 13. Portfolio valuation

- **Equity.** `valuation(state, mark).equity = cash + btc × mark`, with dust included.
  - Marking dust to market is FROZEN.
  - Equity at an explicit mark is PROPOSED.
- **The mark source.**
  - `ledger.mark_price(snapshot)` takes the close of the latest available daily candle.
  - No liquidation haircut is applied, and no staleness bound exists.
  - All of this is PROPOSED (§19 item 12).
- **Side effects.** Marking never changes a balance and never creates a cost (F23).
- **Time basis.** Equity series, returns, drawdown and time in market for a later evaluation should use **event time** (`reference_time` of fills), not booking time (`at`). This is PROPOSED (OPEN §19 item 17).
  - v1.0 produces no equity series. A caller-side mark series is required before any evaluation.

---

## 14. Benchmarks B0–B5 (documented; never computed in v1.0)

**FROZEN** (the brief §10):
- the six IDs, their names and their roles;
- the primary comparison against B1;
- B2 and B3 as descriptive only;
- no execution in this sprint.

The operational definitions are PROPOSED (definition only; OPEN §19 item 8). Nothing in `research/design_a` computes a benchmark.

| ID | Name and role (FROZEN) | Proposed operational definition (PROPOSED) |
|---|---|---|
| B0 | Cash | 100 % quote cash; zero return; no cost |
| B1 | BTC buy-and-hold with comparable acquisition costs; **primary comparison** | one buy at the execution reference (Tuesday open) following Design A's first actionable decision, whether that decision is LONG or FLAT, with the same `CostSpec`, `MinOrderRules` and buy formula; held to the end; valued at the same mark; a terminal sale, if reported, uses the sell formula and is reported separately |
| B2 | Ex-post volatility-matched BTC; descriptive only | a constant BTC fraction chosen after the fact to match Design A's realised volatility; hindsight by construction |
| B3 | Lagged rolling 90-day exposure-matched BTC; descriptive only; shows whether the apparent benefit comes from lower exposure | at each decision instant, BTC exposure equal to Design A's time in market over the previous 90 days (lagged), rebalanced weekly with §10 costs |
| B4 | SMA200 at daily decision frequency; robustness only | the same rule decided every day at 00:00 UTC plus 30 seconds on the just-completed close, executed at the open of the following day: the same one-day lag as Design A |
| B5 | SMA200 at monthly decision frequency; robustness only | the same rule at the first decision instant of each calendar month, with Design A's execution |

---

## 15. Evaluation metrics (definitions only; no calculation is authorized)

The **list** is FROZEN (the brief §11). Each formula is PROPOSED (definition only), and the rows marked OPEN need a decision first.
- **Time basis.** Time-based metrics use event time (§13; OPEN §19 item 17).
- **Gross and net** are always reported together (APPROVED, `OWNER_OPERATING_CONTRACT.md` §1).

| Metric | Proposed definition | Open points |
|---|---|---|
| Net terminal wealth | final net equity ÷ initial cash | mark convention |
| Net CAGR | terminal wealth^(365 / calendar days) − 1 | day-count convention |
| Maximum drawdown | largest peak-to-trough decline of the equity series | sampling frequency (§19 item 8) |
| Net Sharpe ratio | mean ÷ standard deviation of periodic net returns, annualised | frequency and annualisation (§19 item 7) |
| Sortino ratio | as Sharpe, with downside deviation | target return (§19 item 8) |
| Calmar ratio | net CAGR ÷ maximum drawdown | window (§19 item 8) |
| Net certainty equivalent | CRRA, **γ = 2 primary** (FROZEN); γ = 1 and γ = 4 descriptive only (FROZEN); γ never chosen by performance (FROZEN); the identical estimator for Design A and B1 (FROZEN) | **OPEN (§19 item 4):** utility estimator, aggregation horizon, annualisation, treatment of zero or near-total losses, paired comparison method |
| CE differential vs B1 | CE(Design A) − CE(B1) at the same γ and estimator | as above |
| Time in market | share of calendar days with the actual position LONG, in event time | §19 item 17 |
| Number of transitions | count of `EXECUTED` entries | — |
| Completed round trips | executed buy followed by executed sell | — |
| Turnover and transaction costs | Σ executed notional; Σ `fee`, `spread_cost`, `slippage_cost` | — |
| Net and gross profit factor | Σ winning ÷ │Σ losing│ round-trip P&L; **descriptive only, never a gate** (FROZEN) | — |
| Return concentration by calendar year | each year's share of total net log return | — |
| Leave-one-year-out | headline metrics recomputed without each calendar year | fold unit and aggregation (§19 item 6) |
| Block-bootstrap sensitivity | resampled headline metrics; owner-**proposed** sensitivity block lengths 20, 60 and 120 days; sensitivity only, not calibrated intervals (FROZEN) | scheme, replications, seed (§19 item 5) |
| Cost scenarios | every metric under BASELINE and STRESS (FROZEN) | — |

---

## 16. Statistical limitations

- **Effective sample.** It is the number of independent trend episodes, not days (`docs/strategy/S4_MECHANISM_COMPARISON.md`: "Effective sample ≈ number of independent trend episodes"). A multi-year BTC history has few of them.
- **Dependence.** Daily observations are not independent trading opportunities. Positions last weeks to months, and returns are serially dependent and clustered.
- **Bootstrap.** Block bootstrap is a sensitivity diagnostic and cannot create episodes the sample lacks. No claim is made that its intervals understate or overstate uncertainty (FROZEN, the brief §11).
- **Direction of error.**
  - The brief calls the Tuesday-open delay "a deliberate, conservative research-model assumption".
  - Its direction of error against live execution has not been measured, and neither has that of the cost levels or the availability rule.
- **Power and the governed endpoint.**
  - Insufficient power is not evidence of no edge, and power at target is not evidence of an edge (`EVIDENCE_LADDER_PARAMETERS.md` §4).
  - The governed endpoint is documented as a daily HAC z (`EVIDENCE_LADDER_PARAMETERS.md` §2, "citations, not adoption").
  - No mapping has been defined from Design A's equity series (decided weekly, marked daily) to that endpoint. The excess definition (versus cash or B1) and the episode-count power are open (§19 items 7, 14).
- **Exposure.**
  - "All available historical periods are contaminated to some degree and therefore are not an untouched test" (`docs/research_temporal_governance.md`, "Partitions").
  - This repository's own research has already used a BTC EMA200 regime filter (§1). BTC 200-day-average regime behaviour is research-exposed here.
- **Multiplicity.**
  - The pre-registered set is 5 configurations × 2 cost scenarios × 3 γ values × 3 block lengths.
  - The primary is declared in advance. Diagnostics are reported, never selected (§18).
  - Any evaluation must report all of them, with no best-of selection.
- **Concentration.** One asset, one venue, long-only: results are dominated by a handful of regimes and by the start and end dates.

---

## 17. Exploratory outcome classification

**Status: NOT DEFINED. OPEN (§19 item 3).** v1.0 implements no classifier and no threshold. No result may be labelled until the owner approves a procedure.

**FROZEN requirements** (the brief §11):
- **Categories.** Three non-confirmatory categories: `ENCOURAGING`, `INCONCLUSIVE`, `NOT ENCOURAGING`.
- **What the labels do not authorize:** production, Paper trading, protected-data access, or prospective confirmation.
- **Before any historical evaluation,** the procedure must be:
  - fully specified;
  - mutually exclusive;
  - reproducible;
  - frozen;
  - consistent with A29.
- **Thresholds.** No arbitrary turnover, annual-concentration or leave-one-year-out rejection thresholds.
- **Profit factor** is descriptive, never an acceptance gate.

**PROPOSED for the owner's decision (not adopted):**
- that the categories also be jointly exhaustive;
- that every threshold have a written source not derived from research-exposed or protected outcomes.

**Consistency with A29 (flagged).**
- **What the repository says.**
  - `OWNER_OPERATING_CONTRACT.md` §4: "A29 Evidence Ladder remains in force with D1/D2 HOLD for governed confirmation … ENCOURAGING is non-confirmatory".
  - `EVIDENCE_LADDER_PARAMETERS.md` §2 documents `ENCOURAGING` as a **prospective** final-look status at `z ≥ 0.8416`, citing A31 §2, A32 §5 and A33 §6.
- **What exists nowhere.** `INCONCLUSIVE` and `NOT ENCOURAGING` are defined nowhere in this repository.
- **What the procedure must settle.** An exploratory historical `ENCOURAGING` must not be confused with the prospective status. The procedure must say whether it reuses the name with a qualifier or uses different wording.
- **Checking is blocked.** Checking "consistent with A29" needs either the A29–A34 texts (commit `54a6369`, OD-1/OD-2) or an owner ruling. The author cannot verify it (§19 item 3).

---

## 18. Parameter discipline

**Primary (FROZEN):**
- weekly SMA200, equality FLAT;
- Tuesday-open reference, three-day deferral;
- BASELINE and STRESS costs.

The window is a module constant (`decision.SMA_WINDOW = 200`).

**Pre-registered diagnostics (FROZEN as configurations for a future approved evaluation; not implemented, not run):**

| ID | Configuration (FROZEN) | Reading (PROPOSED) |
|---|---|---|
| D-W160 | weekly SMA160 | 160 completed daily closes, decided weekly |
| D-W240 | weekly SMA240 | 240 completed daily closes, decided weekly |
| D-D200 | daily SMA200 | corresponds to B4 |
| D-M200 | monthly SMA200 | corresponds to B5 |

That makes five configurations, including the primary. The rules (FROZEN):
- no parameter search, additional indicators, optimisation or adaptive tuning;
- no selection of the best diagnostic;
- no change to the primary after observing results.

This follows `research/mechanisms/signals.py`: parameters are declared from literature or a frozen spec, never tuned.

---

## 19. Scientific decisions: status and effect on v1.0

The first draft listed 16 open decisions; independent review added a 17th. Each is classed as one of three:
- **A.** Approved and implementable. The brief fixes it, so it is implemented.
- **B.** Unresolved, but independent of the v1.0 code. Nothing in v1.0 depends on it; it gates later work.
- **C.** Blocks a specific behaviour. The behaviour is either implemented provisionally in the named places, labelled and tested, or left unimplemented.

None is approved by this document.

| # | Decision | Class | Effect on v1.0 |
|---|---|---|---|
| 1 | Data-availability and dataset policy, including a late Sunday at the decision instant | **C** | The provisional rule is in `state.available_from`; the brief requires a policy before historical evaluation. There is no dataset, adapter or licence record, and real data is refused. |
| 2 | Hypothesis source (PRE_EXISTING / DISCOVERY_DERIVED / EXTERNAL_THEORY), registry record, ID, family | **B** | Nothing declared in code; evidence in §1 |
| 3 | Exploratory outcome classification procedure, and how "consistent with A29" is checked | **B** | No classifier. Needs the A29 texts or an owner ruling (§17). Blocks labelling any evaluation. |
| 4 | Certainty-equivalent estimator (utility form, aggregation horizon, annualisation, zero or near-total losses, paired comparison) | **B** | Nothing computed |
| 5 | Bootstrap scheme, replications, seed | **B** | Nothing computed |
| 6 | Leave-one-year-out fold unit and aggregation | **B** | Nothing computed |
| 7 | Weekly and partition conventions | **A**: the Sunday-close / Monday-decision / Tuesday-open calendar. **C**: the partition key for a holdout guard. **B**: annualisation and the mapping to the daily HAC endpoint. | The holdout guard is **not implemented** (it would decide the key). |
| 8 | Benchmark and drawdown definitions | **B** | Proposed definitions only (§14, §15) |
| 9 | Cost tiers and fee base | **A**: rates, formulas, fee base on the adjusted notional, half-spread on both legs, fixed-level stress. **B**: whether the levels are measured venue tiers (`EVIDENCE_LADDER_PARAMETERS.md` §1.1 U4, on the provenance of A30 figures). | No realism claim |
| 10 | Minimum-order rules | **A**: buy rejection; configurable inputs. **C**: the quantity step, the check set (minimum notional at the execution price), sell-side rejection, reject-and-end vs retry. **B**: the venue's actual values. | Provisional in `ledger._fill`, `ledger._min_order_failure`, `state.floor_to_step`, `state.actual_position` |
| 11 | Pending-transition semantics and the F10 reading | **A** for the F10 reading (owner decision 2026-10-31: weekly retries, `state.required_action`). **C** for the rest | Provisional in `state.actual_position`, `ledger.apply_decision`, `ledger.execute_pending`, covering:<br>• the window measured on reference opens, as 72 h; the calendar-date readings Tue–Thu or Mon–Wed are the alternatives (X9);<br>• booking upon completion, so a Thursday fill is known after `expires_at` (X9, X10);<br>• one `MISSING_MARKET_DATA` per due day;<br>• expiry once Thursday is overdue;<br>• no retroactive use;<br>• no retry after rejection. |
| 12 | Dust valuation and mark source | **A**: dust kept and marked to market; quote-currency fee. **C**: the mark (latest completed close, no haircut, no staleness bound). | Provisional in `ledger.mark_price`, `ledger.valuation` |
| 13 | Arithmetic convention | **C**: `Decimal` itself (the brief fixes only "deterministic arithmetic appropriate for financial accounting"), the contexts, exact-or-refuse, the floor for the buy division, no cash quantisation. **B**: tolerances against float ledgers. | Provisional in `state.EXACT`, `state.FLOOR`, `state.arithmetic`, `state.text`, `state.floor_to_step` |
| 14 | Power and confirmatory path | **B** | Nothing computed |
| 15 | Evidence-class crosswalk | **B** | v1.0 emits `SYNTHETIC` only |
| 16 | Candle-validation contract and window rule | **C** | Provisional in the `Candle` and `Snapshot` constructors, `timing.signal_window` and `decision.decide`, covering:<br>• the candle shape;<br>• the refusal set;<br>• 200 **consecutive** days, so one candle lost before any decision consumed it blocks 28 or 29 decisions (§8). One lost after it was consumed is refused under the owner-approved integrity rule (§5), which is not part of this item;<br>• initial-only warm-up. |
| 17 | Time basis for metrics and records (event time vs booking time) | **B** | The ledger records both (`reference_time`, `at`, `expires_at`). Nothing computed. |

**Recommended gates (PROPOSED; the owner decides):**
- **Before any real-data use at all:** items 1 and 7 (the partition guard).
- **Before any historical evaluation:** every class B and C part above. The class-B part of item 9 is needed only for a statement about cost realism.

---

## 20. Known modelling limitations

- **Reference price, not a fill.** Depth, queue position, partial fills and latency are not modelled. The hs and sl fractions are constants, not measurements.
- **Availability** is assumed within the 30-second offset (§5). Late-arriving data cannot be distinguished from timely data without availability stamps.
- **Daily grid only.** The path between the Sunday close and the Tuesday open is not modelled.
- **One venue, one pair, USDT quote.** Stablecoin risk, outages, custody and the USDT/USD basis are ignored.
- **No cash yield, taxes, deposits or withdrawals.**
- **Fee asset.**
  - Fees are modelled in quote currency.
  - A venue that deducts the buy fee in BTC would change the bought quantity slightly.
- **Minimum-order rejection or expiry ends the transition.** It is retried only at the next valid weekly decision (F10, owner decision), so exposure can differ from the target for up to a week per failed attempt. A position blocked by the minimum notional can be rejected again each week.
- **Mixed states.** A state holding both tradable BTC and buyable cash is outside the contract (§9). It is unreachable from the frozen start in cash.
- **Dust** can accumulate after rule changes. It is reported, never consolidated.
- **Decimal range.** Values needing more than 28 significant digits are refused (§10).
- **Integrity is consistency, not authenticity** (§5). Unkeyed sha256 fingerprints reveal inconsistent data. They do not reveal coordinated tampering with a saved record and its snapshots, or a history forged from the start. Across calls, only consumed candles are evidence.
- **Integrity cost.** Measured in the evidence record; not optimised.
  - The index grows by one entry per consumed day: about 217 bytes in memory and 100 in JSON.
  - Each snapshot check is linear in the snapshot and the index.
  - `verify_integrity` is linear in the number of decisions, and it runs at every `replay` call. So resuming after every single snapshot is quadratic in the length of the history: 3.1 s for the 540 snapshots of the clean fixture, against 0.4 s in one call.
  - Every `State` construction re-validates the whole index, as it does the ledger. That is the largest integrity cost of a replay.
- **Synthetic fixtures.** They are seeded stdlib random walks dated 2001–2002, before Bitcoin existed. They test arithmetic and state transitions, nothing economic.

---

## 21. Governance and authorization boundaries

- **Evidence rules.** The A29 Evidence Ladder remains in force, with D1/D2 HOLD for governed confirmation (APPROVED, `OWNER_OPERATING_CONTRACT.md` §4; the brief §14). Nothing in v1.0 approaches an admission.
- **OD-7** (`docs/strategy/S5_PWR_1_OWNER_DECISIONS.md`): no access to sealed-stream counts or timestamps. Protected outcomes stay closed (`DEVELOPMENT_FIRST_POLICY.md` §3). v1.0 reads no evidence, telemetry, data directory or database.
- **Sealed holdout.** `FORWARD_HOLDOUT` stays sealed. v1.0 accepts only the synthetic permission, and only snapshots dated before 2009-01-03 (§3). So data carrying real or post-freeze dates cannot enter. That is a safeguard, not proof of provenance: re-dated data would pass.
- **Integrity is not authorization.** The candle-integrity checks (§5) keep data that has already been admitted under the synthetic permission consistent across calls. Passing them authorizes access to nothing: no historical, real or protected data. They change no permission, holdout or protected-data control, and they run only after the permission check.
- **Authorized now (class D0):** this specification, the package, the synthetic tests, and a commit and push of `feature/design-a-v1` for review. A push authorizes review only.
- **Not authorized:**
  - real-data evaluation (class D1), and recording a dataset permission;
  - writing to governance JSON or JSONL files;
  - any Paper change, S5 admission, production or UAT operation, or live trading;
  - a merge, a new PR, an LCE run, any claim that CI passed;
  - changes to PR #96 or to the LCE review branch;
  - Docker, Compose, databases, the network or exchange APIs;
  - modifying `.github/`, `CLAUDE.md`, `deploy/`, `docs/governance/`, `docs/ops/`, any runtime service directory or `shared/`.
- **Runtime isolation.** Tests enforce both of these:
  - No code or configuration outside `research/`, `tests/` and `docs/` refers to the package. That covers modules, scripts with or without an extension, Dockerfiles, compose files, the scheduler and systemd templates, and the JSON records under `deploy/` and `ops/`, plus the research files that images copy. Data and result directories, data formats, binaries and files over 2 MB are never read.
  - No Dockerfile copies `research/` as a whole, the repository root, or anything named `design_a`. Images copy named files or directories: `shared/`, their own directory, and for `signal_engine` a few named research files and `research/null_a/`.
- **Precedence.** A later explicit owner decision overrides `OWNER_OPERATING_CONTRACT.md`, which overrides older prose. On a conflict, the narrower safety gate wins (`OWNER_OPERATING_CONTRACT.md` §5).

---

## 22. Implementation map, reuse and evidence

**Package** (`research/design_a/`). It uses only the standard library plus three existing research modules, each used for one purpose:
- `research.mechanisms.simulate.DatasetPermission`: the permission gate;
- `research.mechanisms.costs.BASELINE_FEE_PER_SIDE` and `CostModelError`: the fee floor;
- `research.data_governance.governance.canonical_hash`: the repository's sha256 convention. That module also contains file-writing helpers; only `canonical_hash` is imported.

There is no I/O, `shared.*` import, pandas or numpy. No `research/__init__.py`, `conftest.py`, `pytest.ini`, `pyproject.toml`, `setup.cfg` or `tox.ini` is added.

| Module | Contents |
|---|---|
| `__init__.py` | docstring (research only, never imported by production); `VERSION` |
| `state.py` | `Candle`, `Snapshot`, `CostSpec` (+ `BASELINE`, `STRESS`), `MinOrderRules`, `PendingTransition`, `Decision`, `LedgerEntry`, `State`; enums `Target`, `Side`, `Event`, `ExecutionStatus`; validators and invariants; `EXACT`/`FLOOR`, `arithmetic`, `text`; `is_decision_instant`, `available_from`; `floor_to_step`, `actual_position`, `required_action`; `EVIDENCE_CLASS`, `SYNTHETIC_BEFORE`, `SMA_WINDOW = 200`; candle integrity (§5): `candle_fingerprint`, `window_days`, `merge_consumed`, `check_consumed`, `verify_integrity` |
| `timing.py` | `next_decision_instant`, `is_available`, `is_overdue`, `available`, `latest_sunday_open`, `scheduled_reference_open`, `signal_window` |
| `decision.py` | `decide(state, snapshot)`; re-exports `SMA_WINDOW` |
| `ledger.py` | `apply_decision`, `execute_pending`, `valuation`, `mark_price`, `cost_totals`, `replay`, `state_record`, `state_from_record`, `digest` |

**Why existing components were not reused for the rest** (the brief §2, §3):

| Component | Reason |
|---|---|
| `research/mechanisms/simulate.run` (the S4 daily accountant) | float arithmetic, trades at the close, weight-based turnover; no pending transition, deferral, expiry, minimum order or dust |
| `research/mechanisms/costs.CostModel` | float rates on turnover; only its fee floor and error class fit |
| `shared/exchange_rules.py` (A47 order-filter validator) | Binance-specific filter set with price ticks and bracket-order rounding; Design A needs venue-agnostic configurable minimums (F32). It lives in `shared/`, which every runtime image copies, so coupling a frozen research package to it would let production edits change research results. |
| The Paper tracker's ledger | production code coupled to the database and the 0.30 % flat label |

**Tests.** The fixtures are synthetic: `tests/design_a_synthetic.py` builds seeded stdlib walks dated 2001–2002. It has two replay scenarios:
- **clean:** five fills;
- **rough:** late data (temporary outages), a carried 1E-7 dust balance, and a minimum quantity that rejects a buy. It reaches every recorded event type.
  - Its gap outage hides day 352, which no decision has consumed, on day 357.
  - It previously hid day 330, which earlier decisions had consumed. The integrity rule refuses that (§5), and a test pins the refusal.

Permanent losses of candles are used for the cadence-independence cases. A restored variant of the clean scenario is also replayed: interrupted at snapshot 300, serialised to JSON, restored and resumed.

| File | Brief items |
|---|---|
| `tests/test_design_a_timing.py` | 4, 5, 6, 23, 24 (window level), permission refusal (subclass included), the pre-2009 guard |
| `tests/test_design_a_decision.py` | 1, 2, 3, 4, 5, 8, gap skip, initial-only warm-up, genuine transitions, precision refusal, purity |
| `tests/test_design_a_ledger.py` | 7, 9, 10, 11–22, 24 (interrupted replays), Thursday reference, F10 after expiry, cadence independence (three data cases, three cadences), skipped-instant, revised-candle and backward-resume refusals, gap-skip duration, invalid transitions and values. Candle integrity (§5): identical candles across calls and restoration; revised window day, decision Sunday and execution reference, both in memory and after restoration; a missing consumed candle (inside the span, a history cut short inside the window, the former rough outage); missing unconsumed candles (gap, deferral); tampered, malformed and non-canonical records; restoration inside a retry window; a real process boundary; the remaining known limitation (unconsumed candles) |
| `tests/test_design_a_isolation.py` | 25: import allow-list (AST); fresh-interpreter module check; a full replay with sockets disabled; no runtime file refers to the package; the Dockerfile parser; no Dockerfile copies the package |

**Determinism (item 22).** Each scenario, the restored one included, is replayed in this process and in fresh interpreters with other `PYTHONHASHSEED` values and a hostile ambient decimal context: precision 3, lower-case exponents, and a `DefaultContext` with `Emax = 3`. All must give the same sha256. In addition, one interpreter saves a state and another, with another hash seed and a hostile context, restores it and resumes it to the uninterrupted digest.

**Command:**
```
cd <worktree> && umask 022 && PYTHONDONTWRITEBYTECODE=1 <venv>/bin/python -m pytest -q -p no:cacheprovider -rs \
  tests/test_design_a_timing.py tests/test_design_a_decision.py tests/test_design_a_ledger.py tests/test_design_a_isolation.py
```

The evidence (SHA, interpreter, counts, breakage check) is reported with the handoff.

---

## 23. Review log

**X. First draft checked against the brief** (before any code). The status column says whether the brief settles the row or the owner must decide.

| ID | Draft said | Brief says | Resolution | Status |
|---|---|---|---|---|
| X1 | Benchmark definitions "FROZEN" | names and roles only (§10) | definitions PROPOSED (§14) | settled |
| X2 | Metric formulas "FROZEN" | "prepare definitions only"; "do not silently freeze an unapproved rule" | list FROZEN; formulas PROPOSED (§15) | settled |
| X3 | CE defined via periodic returns, while called open | five estimator choices to be specified; the identical estimator for A and B1; γ never chosen by performance | only the frozen parts are stated (§15) | owner (item 4) |
| X4 | Bootstrap lengths "frozen" | "proposed sensitivity block lengths" | owner-proposed (§15) | settled |
| X5 | Classification extras as frozen; two brief clauses omitted | five requirements, the label limits, no arbitrary thresholds | §17 restated; extras PROPOSED | owner (item 3) |
| X6 | Calendar listed as open | FROZEN (§4–§5) | item 7 class A | settled |
| X7 | Fee base, both-leg spread, fixed stress, quote-currency fee listed as open | fixed by the formulas and the table (§6) | item 9 class A | settled |
| X8 | F10 "relative to the actual position" as frozen, with a mis-described alternative | "Do not rebalance when the target state is unchanged. Execute only genuine state transitions." | **Two coherent readings.** (a) Literal, implemented: trade only on a change of target, and only if the position differs. (b) Retry: trade whenever the position differs from the target, so a weekly retry follows `EXPIRED` or `REJECTED_MIN_ORDER`. They differ only after an expiry or a rejection, or from a non-clean start. | decided by the owner, 2026-10-31: reading (b), weekly retries |
| X9 | Deferral window `open_time ≤ expires_at` as settled | "within three calendar days of the decision timestamp" | **Implemented:** on reference opens, as 72 h (Tue, Wed, Thu). **Alternatives:** on completion, which drops Thursday, since a Thursday fill is known only on Friday; or by calendar date (Mon–Wed). | owner (item 11) |
| X10 | Booking at completion as settled | Tuesday open is the reference; "next available **completed** daily candle" | event time recorded; booking upon completion | owner (items 1, 11) |
| X11 | Non-decision instants raise | "No signal" is a required state | `NO_SIGNAL` value; a forged one at a decision instant is refused | owner (minor) |
| X12 | A holdout guard keyed on `close_time` | partition key undecided | not implemented | owner (item 7) |
| X13 | Incomplete in-window candles skipped; duplicates skipped | handle explicitly; test 6 "rejection of future and incomplete candles" | future, incomplete, duplicate and unordered candles refused at construction; gaps skip | owner (item 16) |
| X14 | Hypothesis wording incomplete; an invented hypothesis ID | §9 wording | wording restored; no ID; no source constant | owner (item 2) |
| X15 | Delivery "Saved only" | "push the development branch" | committed and pushed for review | settled |
| X16 | Availability policy open, with no stated deadline | "specified before historical evaluation" | provisional synthetic rule | owner (item 1) |

**R. Independent review (two same-session reviewers, code and specification) and resolutions.** These reviewers are not independent of the author in the governance sense: their review is a quality check, not approval.

| ID | Finding | Resolution |
|---|---|---|
| R1 | `replay` silently recorded nothing when no snapshot fell exactly on a decision instant | a skipped decision instant is refused (tested for midnight and one-minute offsets, and for a resumed replay) |
| R2 | The digest depended on the ambient decimal context (`capitals`, `DefaultContext`) | fully specified contexts; `state.text` serialisation; hostile-context subprocess test |
| R3 | The ledger depended on the check cadence, because booking happened when the caller looked | outcomes are booked when known under the availability rule; a cadence-independence test |
| R4 | A forged `NO_SIGNAL`, out-of-order decisions, missing cross-field invariants, untyped `Decision` fields, fee ≥ 1 | all refused, with negative tests |
| R5 | Mutation survivors: Thursday reference, a skip applied twice, `NO_CHANGE` target, `min_qty`, a gap before the window | a test for each |
| R6 | The replay covered only 7 event types | the rough scenario reaches all 13 recorded types |
| R7 | The isolation scans were too narrow | every runtime file outside `research/`, `tests/`, `docs/`; continued and JSON `COPY` forms |
| R8 | The spec attributed `ENCOURAGING` to A29 | cited to `OWNER_OPERATING_CONTRACT.md` §4 and A31–A33 via `EVIDENCE_LADDER_PARAMETERS.md` §2 |
| R9 | A "FROZEN" calendar table held provisional rows | the table is split by label (§4); "Never" is stated in event time (§7) |
| R10 | `HYPOTHESIS_SOURCE` fixed in code and hashed, yet classed independent; DISCOVERY_DERIVED omitted | constant removed; the three options and the evidence are in §1 |
| R11 | The consequence of one lost candle (28–29 frozen weeks) was undisclosed | disclosed (§8), tested, alternatives listed |
| R12 | Further labels, citations and wording | relabelled (Decimal, the candle shape, `qty_step`, the window and deferral readings); "triage" replaced by the governance quote; multiplicity, prior exposure, the event-time basis (item 17), reason codes and the reuse rationale added |
| R13 | Second round, no BLOCKER or MAJOR. Findings:<br>• hand-made decisions could contradict F5 or warm up late;<br>• revised candles were silently accepted;<br>• the cadence claim was unqualified;<br>• the isolation scan was narrower than stated;<br>• the F10 consequence was unquantified;<br>• FROZEN labels covered PROPOSED clauses;<br>• the permission gate could be bypassed by a subclass;<br>• resume guards had gaps;<br>• ledger invariants were missing;<br>• documentation had drifted. | Resolutions:<br>• F5-consistent decisions and initial-only warm-up are enforced;<br>• revised candles and backward resumes are refused;<br>• the claim is qualified and tested on three data cases;<br>• the scan covers code and configuration but never reads data;<br>• the F10 consequence is quantified (§7, §20);<br>• labels are fixed (§2–§3, §7);<br>• the gate is exact, with a pre-2009 guard;<br>• ledger invariants are added;<br>• the documentation is corrected. |
| R14 | Owner decision and focused remediation (2026-10-31) | Weekly retries implemented in `state.required_action`, marked `RETRY`, with ten regression tests (baseline and stress). Documented: the reference timestamp versus availability; that revision detection is per replay call, with a proposed durable mechanism; that the pre-2009 guard is a safeguard, not proof of provenance. |
| R15 | Owner-approved replay/resume integrity remediation (2026-10-31). Findings during the round:<br>• the day-330 gap outage of the rough fixture hid a candle that earlier decisions had consumed;<br>• a resumed snapshot starting inside the next decision's window turned missing consumed candles into an `INSUFFICIENT_HISTORY` skip;<br>• the breakage check showed that no test reached the canonical round-trip check of `state_from_record`;<br>• the old known-limitation test was about to be removed, although its case, a revision of a delivered but unconsumed candle across a cut, is still undetected. | Resolutions:<br>• the durable mechanism is implemented (§5): fingerprints, the compact index, ledger cross-references, checks before processing, `verify_integrity`, `state_from_record`. The known-limitation test, with its assertions unchanged, now pins the narrower remaining limitation: unconsumed candles (§5);<br>• the outage moved to day 352, which no decision had consumed (still a gap, tested); the former day-330 outage is refused (tested);<br>• `decide` extends the coverage to its window, so such a snapshot is refused (tested);<br>• non-canonical records are tested;<br>• the costs are measured, not optimised (§20). |
