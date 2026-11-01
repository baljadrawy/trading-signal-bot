# SIGNAL_INTEGRITY_MODE decomposition (WP-C01)

> **Status: Documentation/design only (WP-C01; R3.e).** This file describes what `SIGNAL_INTEGRITY_MODE=enforce` does today, one behaviour at a time, so the owner can declare one strategy-version boundary or several (R3 owner gates; SE-83; DG-38). It enables nothing, changes no code and chooses no option. The mode is **`off` at runtime** (RUNTIME_VERIFIED for 2026-10-31; `RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md:L94 @ 5d977f2`, VER-02). No statement here is a profitability claim: removing a duplicate or a stale decision corrects measurement and execution; it establishes nothing about net edge (`TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md:L46 @ 46578aa`).

## Document control

| Field | Value |
|---|---|
| Task | WP-C01 in [IMPLEMENTATION_WORKPLAN.md](remediation-design-pack-20261101/IMPLEMENTATION_WORKPLAN.md) §4.3; remediation sub-item R3.e in [REMEDIATION_REGISTER.md](remediation-design-pack-20261101/REMEDIATION_REGISTER.md) |
| Change class | Documentation/design |
| Gate | WP2-START (DG-70, approved development-only). Feeds the boundary choice of WP-G05, DG-38 (packaging, SE-83) and DG-68 (activation) in [DECISIONS_AND_GATES.md](remediation-design-pack-20261101/DECISIONS_AND_GATES.md) |
| Branch | `feature/wp2-foundation-20261101`, HEAD `a03efdd` |
| Code read | analyzer, signal_engine and shared at `ea8ae4f`; trade_tracker at `bb7825f`; every site also at HEAD `a03efdd` (section 2) |
| Behaviour IDs | EB-0 (prerequisite) and EB-1 to EB-4 (the four behaviours WP-C01 names). Findings are IM-01 onwards |
| Companion | [SETUP_KEY_PROPOSAL_SE84.md](SETUP_KEY_PROPOSAL_SE84.md) (the key composition, SE-84 / DG-35, on HOLD) |

### Anti-drift statement (charter §7)

1. **Goal alignment.** Each behaviour is judged by its effect on daily opportunity discovery, execution correctness and the integrity of per-setup measurement. Almost every effect below removes an emission or an admission. The one exception is EB-3's bounded retry, which can keep a cycle that today is lost to a transient read error. No behaviour creates a trade or a quota, so none conflicts with "discovery is not execution".
2. **Branch, SHA, runtime identity.** Source claims are SOURCE_VERIFIED at the named commits. That the running images hold this source is DOCUMENTED_ONLY (RT-16); image filesystems were not read (RT-17, NOT_VERIFIED).
3. **Scope.** R3 only: the enforce-mode switch. The `setup_key` composition is SE-84 and lives in the companion file.
4. **Evidence classes** follow charter §7.4. Every frequency statement in section 3 is INFERRED from source. No count was read, because counts come from post-freeze runtime tables, which are protected (DG-33).
5. **Permission class.** Read-only documentation (`git show` at the named commits).
6. **Deliverable and acceptance.** This file; acceptance is owner review (WP-C01).
7. **DEVIATION ALERT.** None.

### Source aliases

| Alias | Path @ commit |
|---|---|
| ADD | `docs/audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md @ 5d977f2` (not on this branch) |
| REP | `docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md @ 5d977f2` (not on this branch) |
| SL | `signal_engine/signal_logic.py` (pinned, see below) |
| SI | `shared/signal_identity.py` |
| TT | `trade_tracker/main.py` |

Code citations give the documented-deployed commit first and HEAD lines second when they differ.

## 1. The switch today

- **One setting, read by each service on its own.** `integrity_mode(cfg)` returns `off` or `enforce` and raises on any other value (SOURCE_VERIFIED; `SI:L24-33 @ ea8ae4f`). The default is `off` (SOURCE_VERIFIED; `shared/config.py:L118 @ ea8ae4f`, L120 at HEAD). An unknown value refuses to start the analyzer (`analyzer/main.py:L29 @ ea8ae4f`, L30 at HEAD), the signal engine (`signal_engine/main.py:L102 @ ea8ae4f`, same at HEAD) and the tracker (`TT:L77 @ bb7825f`, same at HEAD) (SOURCE_VERIFIED).
- **Runtime.** The variable is unset, so `off`, in every service (RUNTIME_VERIFIED; ADD:L94, VER-02). The audit lists the A43/A44 integrity behaviours as flagged off (SOURCE_VERIFIED; REP:L600 STR-33, REP:L837 EXE-17).
- **The five places that test for `enforce`** (SOURCE_VERIFIED):

| Site | `@ ea8ae4f` / `@ bb7825f` | HEAD `a03efdd` | Behaviour |
|---|---|---|---|
| Analyzer candle-identity stamp | `analyzer/technical_analyzer.py:L53` | L54 | EB-0 |
| Signal engine, safety reads and decision time | `SL:L730` | L731 | EB-3, then EB-1 and EB-2 |
| Signal engine, per-candidate identity verdict | `SL:L803` | L804 | EB-1, EB-2 |
| Signal engine, keyed insert | `SL:L969-970` | L970-971 | EB-1 |
| Tracker admission | `TT:L761 @ bb7825f` | L761 | EB-4 |

- **Which files are hash-pinned.** The research contract hashes nine files, and `signal_engine/signal_logic.py` is one of them (SOURCE_VERIFIED; `research/foundation/contract.py:L69-72 @ 46578aa`; WP-N02). `shared/signal_identity.py`, `shared/dependency_safety.py`, `shared/config.py`, `analyzer/technical_analyzer.py`, `signal_engine/main.py` and `trade_tracker/main.py` are not on that list (SOURCE_VERIFIED, same lines). A byte change to a pinned file changes `current_contract()` even when behaviour is identical, so any hook inside it waits for owner decision WP-OD-01 (DG-71, on HOLD). Section 5 uses this to say which behaviours can be integrated without WP-OD-01.
- **Blob identity between the documented commits and HEAD** (SOURCE_VERIFIED; `git rev-parse <commit>:<path>`): `shared/signal_identity.py`, `shared/dependency_safety.py`, `signal_engine/main.py` and `trade_tracker/main.py` are byte-identical. `signal_engine/signal_logic.py` gains one evidence-recorder argument at L57 at HEAD, so every later line moves down by one. `analyzer/technical_analyzer.py` moves by one line around the stamp.

## 2. Cited-line verification

Each line range that WP-C01 cites was read with `git show <commit>:<path>` (SOURCE_VERIFIED).

| Cited | What the lines hold | Result | HEAD `a03efdd` |
|---|---|---|---|
| `SL:L261-263 @ ea8ae4f` | Inside `_INSERT_ONCE_SQL` (L255-265): L261 ends the column list with `setup_key`, L262 is the 18-value `VALUES` list, L263 is `ON CONFLICT (setup_key) WHERE setup_key IS NOT NULL DO NOTHING` | VERIFIED | L262-264 (statement L256-266) |
| `SL:L730-737 @ ea8ae4f` | `enforce = integrity_mode(config) == 'enforce'`; in enforce, `_integrity_state(...)`, return when it is `None`, unpack (throttled, open symbols, cooldown, emitted keys), capture `decision_ms` | VERIFIED | L731-738 |
| `SL:L803-818 @ ea8ae4f` | The enforce branch per candidate: `integrity_check(...)` with `strategy_version=config.APP_VERSION` and the emitted keys; a rejection with the first reason; the identity rebuilt; the `setup_identity` block (version, key, bracket hash, candle open and close) | VERIFIED | L804-819 |
| `SI:L186-200 @ ea8ae4f` | `freshness_at`: the bound check, the unknown-timeframe rejection, age = decision − (close + 1), `decision_before_candle_close`, `superseded_by_newer_candle`, admissible | VERIFIED | identical blob |
| `TT:L700-702 @ bb7825f` | Inside `integrity_admission_refusal` (L687-702): admission time, `freshness_at(...)` on the stored close, the refusal string | VERIFIED. These are the freshness lines only; the identity-missing refusal is L698-699 | identical blob |
| fail-closed cooldown read (no line given in WP-C01) | Enforce: `_cooldown_symbols` (`SL:L369-371`) read through `guarded_read` and `cycle_gate` (`SL:L404-413`). Off: `_get_symbol_cooldown_set` (`SL:L417-431`), which returns an empty set on error at L431 | cited here | L370-372, L405-414, L418-432 |

The register's HEAD column for the enforce path (`L731-738, L804-819`) agrees with this table (REMEDIATION_REGISTER.md R3 "Current location"). The audit cites the off-mode `return set()` as `signal_logic.py:432` (REP:L1145, HIS-27), which is the HEAD layout; at `ea8ae4f` the line is L431. Both are correct for their commits.

## 3. The behaviours, one at a time

Each entry gives: what the code does (SOURCE_VERIFIED), whether its sites are in a pinned file, what it depends on, and what it would change in Paper if enabled. The frequency statements are **qualitative and INFERRED**. They give a direction where the source fixes one, and say so where it does not. No count is given or implied.

### EB-0 · Analyzer candle-identity stamp (prerequisite)

WP-C01 does not list this behaviour, but EB-1, EB-2 and EB-4 cannot work without it.
- **Code.** In enforce mode the analyzer adds a `candle_identity` block (exchange open and close ms of the last closed bar) to every analysis row, or `candle_identity: None` with `candle_identity_error` when the bounds cannot be derived or fail validation (SOURCE_VERIFIED; `analyzer/technical_analyzer.py:L50-58 @ ea8ae4f`, L51-59 at HEAD; validation `SI:L128-157 @ ea8ae4f`).
- **The engine never falls back to instrumentation.** It calls `identity_from_candidate(..., allow_pit_fallback=False)`, so a row without the block is rejected as `identity:candle_identity_missing` (SOURCE_VERIFIED; `SI:L107-115 @ ea8ae4f`; `SL:L804-806, L813-814 @ ea8ae4f`).
- **Pinned?** No (`analyzer/technical_analyzer.py`, `shared/signal_identity.py`).
- **Paper effect if enabled.** None by itself. Rows whose bounds cannot be derived become ineligible once EB-1 is on (INFERRED).

### EB-1 · Insert-once identity (signal engine)

- **Key.** `SetupIdentity.key = "sk_" + sha256([identity_version, symbol, timeframe, candle_open_ms, trade_type, direction, strategy_version, setup_policy])[:40]` (SOURCE_VERIFIED; `SI:L64-88 @ ea8ae4f`). The engine passes `strategy_version=config.APP_VERSION` (SOURCE_VERIFIED; `SL:L385, L805, L813 @ ea8ae4f`), so the key changes whenever the release label changes (IM-04).
- **Emitted-key pre-read.** Before the candidate loop, `_integrity_state` computes the key of every row and reads which of them already exist in `signals` (`EMITTED_SETUPS_SQL`) as a SAFETY read (SOURCE_VERIFIED; `SL:L29, L379-388, L399-402 @ ea8ae4f`).
- **Per-candidate verdict, before ranking.** `integrity_check` rejects an unidentifiable row (`identity:<error>`) and an already-emitted key (`duplicate_setup`); the engine records the first reason and skips the row (SOURCE_VERIFIED; `SI:L253-266 @ ea8ae4f`; `SL:L803-812 @ ea8ae4f`). The surviving candidate carries `setup_identity` = version, key, bracket hash, candle open and close (`SL:L813-818 @ ea8ae4f`).
- **Keyed insert.** `save_signal` refuses a winner without `setup_identity` (`setup_identity_required`) and inserts with `ON CONFLICT (setup_key) ... DO NOTHING` (SOURCE_VERIFIED; `SL:L968-988 @ ea8ae4f`; the statement is `SL:L255-265`). When the unique index rejects the row, the stored bracket hash decides `duplicate` or `conflict`, nothing is published, and the engine closes the cycle as `duplicate_setup_suppressed` and sleeps (SOURCE_VERIFIED; `SL:L989-996 @ ea8ae4f`; `signal_engine/main.py:L227-236 @ ea8ae4f`).
- **Schema.** A nullable `signals.setup_key` with a partial unique index; rows from off mode keep `NULL` and are never constrained (SOURCE_VERIFIED; `database/migrations/011_a44_signal_setup_key.sql:L1-18` at HEAD; the off-mode insert omits the column, `SL:L998-1014 @ ea8ae4f`).
- **Pinned?** Every engine site is in `signal_engine/signal_logic.py`, which is **pinned**. The key formula and `integrity_check` are in `shared/signal_identity.py`, which is not. `signal_engine/main.py` is not.
- **Depends on.** EB-0; migration 011; EB-3 (the emitted-key read sits in the same safety gate).
- **Paper effect if enabled (INFERRED).**
  - It removes the repeat emission of one 4h or 1d bar after each 2 h cooldown (R3; OF-16 in [OPPORTUNITY_FUNNEL.md](remediation-design-pack-20261101/OPPORTUNITY_FUNNEL.md)), so fewer signal rows per setup.
  - 15m is not affected in practice: the 2 h symbol cooldown outlasts a 15m bar, so a 15m bar is already superseded when the symbol is next eligible.
  - Second-order effect, direction not fixed by source: a suppressed duplicate no longer takes the single slot per cycle and no longer restarts the symbol's 2 h cooldown. Another candidate can therefore be emitted in its place. Whether total signal count falls or holds cannot be read from source; counting it needs DG-33.
  - Rows without a valid candle identity drop out (via EB-0).

### EB-2 · One-bar freshness bound

- **Rule.** `freshness_at(timeframe, close_ms, decision_ms, max_age_bars=1.0)`: age = decision − (close + 1). A negative age rejects as `decision_before_candle_close`; an age of at least one bar rejects as `superseded_by_newer_candle`; an unknown timeframe rejects (SOURCE_VERIFIED; `SI:L186-200 @ ea8ae4f`). The bound must lie in (0, 1] bar.
- **Two application sites, both at one bar.**
  - Signal engine, before emission: `integrity_check` → `freshness` (`SI:L176-183, L262-263 @ ea8ae4f`), called at `SL:L804-806 @ ea8ae4f` with no `max_age_bars`, so one bar. Decision time is taken once per cycle (`SL:L737, L364-367 @ ea8ae4f`).
  - Tracker, at admission: EB-4 (`TT:L700-702 @ bb7825f`), also with the default of one bar.
- **Not separable at the engine today.** Identity, freshness and the duplicate check are one `integrity_check` call (IM-02).
- **Pinned?** The rule is in `shared/signal_identity.py` (not pinned). The engine call site is pinned. The tracker call site is not.
- **Depends on.** EB-0 for the close time at the engine; EB-1's stored `setup_identity.candle_close_time_ms` at the tracker.
- **Paper effect if enabled (INFERRED).**
  - Freshly analysed rows always refer to a bar less than one bar old, so the engine-side rule bites only when a row has aged past the rest of its bar's life by decision time.
  - Rows qualify for up to 30 minutes after analysis (`signal_engine/main.py:L146-149 @ ea8ae4f`), which is longer than a 15m bar. The reduction is therefore expected to concentrate on 15m and on periods of analyzer delay. For 4h and 1d it can bite only in the first 30 minutes after a close, on rows not yet re-analysed.
  - It also rejects a decision taken before the bar's close, which can happen only if host clocks disagree.
  - Direction: fewer signals. Size: unknown.
- The bound itself is open owner decision OF-OD-12 (DG-27); the A44 rule is the reference implementation (OF F4).

### EB-3 · Fail-closed safety reads, including the cooldown read

- **Off mode today.**
  - The cooldown read `_get_symbol_cooldown_set` returns an empty set on any error, so cooled-down symbols become eligible (SOURCE_VERIFIED; `SL:L417-431, L746 @ ea8ae4f`; REP:L1145 HIS-27; OF-15).
  - The open-positions read is unguarded (`SL:L745 @ ea8ae4f`). An error ends the cycle through the main loop's exception handler, which counts the error and backs off (SOURCE_VERIFIED; `signal_engine/main.py:L262-277 @ ea8ae4f`).
  - The learned-gate read runs only while `LEARNING_GATES_ENABLED` is true (`SL:L741-743 @ ea8ae4f`), and it is false at runtime (RUNTIME_VERIFIED; ADD:L95, VER-03).
- **Enforce mode.** `_integrity_state` runs four SAFETY reads through `guarded_read` and combines them with `cycle_gate`: learned gates (no read while disabled), open positions, the symbol cooldown and the emitted setups. Any failed SAFETY read means no candidate this cycle, and every row's decision is set to `safety_state_unverified:<names>` (SOURCE_VERIFIED; `SL:L373-415 @ ea8ae4f`; `shared/dependency_safety.py:L35-44, L125-139 @ ea8ae4f`). The cooldown read `_cooldown_symbols` itself raises on error (`SL:L369-371 @ ea8ae4f`).
- **Retry and time limits.** `guarded_read` uses a per-attempt limit of 2.0 s, at most 2 attempts, a 0.2 s backoff and a 5 s budget. It retries only timeouts and connection errors (SOURCE_VERIFIED; `shared/dependency_safety.py:L75-109 @ ea8ae4f`). These values are reproduced from code, not proposed.
- **Not cooldown-only.** The behaviour that WP-C01 calls "the fail-closed cooldown read" is one gate over four reads (IM-03).
- **Pinned?** Yes. Both the off-mode fail-open and the enforce gate are in `signal_engine/signal_logic.py`. The read classification and the retry bounds are in `shared/dependency_safety.py`, which is not pinned. Making the off path fail closed is the WP-B10 hook, which the workplan already places under WP-OD-01.
- **Depends on.** Nothing, except that the emitted-setups read exists only for EB-1.
- **Paper effect if enabled (INFERRED).**
  - No change while every read succeeds.
  - During a cooldown read failure, today's path can emit signals for symbols that should still be cooling down; enforce emits nothing in that cycle.
  - For an open-positions failure the outcome is the same as today: no signal. But enforce retries a transient connection error or timeout once, which can save a cycle that today is lost, and its 2.0 s per-attempt limit can fail a slow read that today's path would wait for.
  - Net: an effect only during database faults, with mixed direction.

### EB-4 · Tracker integrity refusal

- **Code.** `integrity_admission_refusal(sig)` refuses with `integrity:setup_identity_missing` when the stored `features_snapshot.setup_identity` has no key or no integer close time. Otherwise it applies `freshness_at` at admission time (SOURCE_VERIFIED; `TT:L687-702 @ bb7825f`; freshness at L700-702). It runs only in enforce mode, after the capacity check and before entry. A refusal is terminal: `telegram_sent` is set to false and a research event `integrity_rejected` is written (SOURCE_VERIFIED; `TT:L751-769 @ bb7825f`).
- **The key is opaque to the tracker.** Only its presence is tested (`TT:L698 @ bb7825f`), so the tracker accepts any key format. This matters for SE-84.
- **Pinned?** No (`trade_tracker/main.py`, `shared/signal_identity.py`).
- **Depends on.** EB-1 at the engine. With the engine in off mode every delivered signal lacks `setup_identity`, so every admission would be refused (section 4).
- **Paper effect if enabled (INFERRED).**
  - Signal count unchanged. Admissions: fewer.
  - It refuses delivered signals whose bar has been superseded by admission time. That concerns signals that wait inside the 2 h admission window: limit-entry waits, risk-reject retries, or a full portfolio, where `register_new_signals` returns before its loop (`TT:L708-715 @ bb7825f`).
  - A 15m signal emitted late in its bar is refused unless admitted within the minutes left; a 4h signal emitted late in its bar likewise. A 1d signal rarely is, within a 2 h window.
  - At the moment of switching on, signals emitted unkeyed before the switch and still inside the 2 h window are refused.
  - A refused signal row still counts for the 2 h symbol cooldown, which reads every `signals` row (`SL:L25-26 @ ea8ae4f`). The refusal therefore does not free the symbol for a new signal (IM-05).

## 4. Cross-service coupling

The setting is read separately by the analyzer, the signal engine and the tracker. No site checks that the other services agree (SOURCE_VERIFIED by reading the five sites in section 1; IM-01). The combinations behave as follows (INFERRED from the code paths cited in section 3):

| Analyzer | Engine | Tracker | Result |
|---|---|---|---|
| off | off | off | today's behaviour (VER-02) |
| enforce | enforce | enforce | A44 as designed: EB-0 to EB-4 together |
| off | enforce | any | every candidate is rejected `identity:candle_identity_missing`: no signals |
| any | off | enforce | every delivered signal is refused `integrity:setup_identity_missing`: no admissions |
| enforce | enforce | off | keyed, fresh emission, but admission without the freshness re-check: a superseded bar can still be admitted inside the 2 h window (the R3.b gap) |
| enforce | off | off | rows carry an extra `candle_identity` field that no off-mode decision reads (`save_signal` copies named fields only, `SL:L941-963 @ ea8ae4f`) |

**Consequence.** Today's code supports exactly one coherent boundary: all three services in enforce at once, with migration 011 applied. Every partial combination either blocks the flow or leaves the R3.b gap. Several boundaries therefore need new sub-flags, and section 5 states where each would have to live.

## 5. Boundary options for the owner

This section chooses nothing. Packaging is DG-38 (SE-83); activation is DG-68, through WP-G05; the cooldown question once `setup_key` exists is DG-28 (OF-OD-13); the freshness bound is DG-27 (OF-OD-12). Each option below is a **Strategy-version-changing correction** when activated (charter §5 WP2, `TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md:L51 @ 46578aa`). The code needed to prepare a split is a **Safe development-only correction**, with defaults that reproduce `off` byte for byte.

### 5.1 Can each behaviour be integrated without WP-OD-01?

| Behaviour | Where the deciding code lives | Pinned? | Change possible without WP-OD-01 |
|---|---|---|---|
| EB-0 candle-identity stamp | `analyzer/technical_analyzer.py:L50-58 @ ea8ae4f` | no | yes: a sub-flag in the analyzer |
| EB-1 insert-once identity | engine sites `SL:L379-402, L803-818, L968-996 @ ea8ae4f`; key and verdict `SI:L64-88, L253-266 @ ea8ae4f` | engine sites **yes**; key and verdict no | enabling it as it is needs no code change. Changing what the key contains can be done inside `shared/signal_identity.py` (gated by SE-84 / DG-35, on HOLD). Any change at the engine sites (for example, passing a `StrategyVersion` instead of `APP_VERSION`) needs WP-OD-01 |
| EB-2 freshness bound | rule `SI:L186-200 @ ea8ae4f`; engine call `SL:L804-806`; tracker call `TT:L700-702 @ bb7825f` | rule no; engine call **yes**; tracker call no | the bound and a switch inside `integrity_check` can live in `shared/signal_identity.py`; the tracker side in `trade_tracker/main.py`. Applying freshness at the engine outside enforce mode needs WP-OD-01 |
| EB-3 fail-closed safety reads | `SL:L369-431, L730-747 @ ea8ae4f`; retry bounds `shared/dependency_safety.py:L75-109` | **yes** | no: the off-path fail-open (`SL:L431`) and the enforce gate are both in the pinned file (WP-B10's pinned hook). Only the retry bounds and read classification are outside it |
| EB-4 tracker refusal | `TT:L687-702, L761-769 @ bb7825f` | no | yes: a sub-flag in `trade_tracker/main.py`, with the rule from `shared/signal_identity.py` |

### 5.2 Splits the code allows

| Option | What would be switched | What is needed first | Pinned-file gate |
|---|---|---|---|
| S1 · one bundled boundary | `SIGNAL_INTEGRITY_MODE=enforce` in the analyzer, signal engine and tracker together | no code; migration 011 present; one VERSION_BOUNDARY entry; a Class B operation for each of the three services | none. The key stays the A44 key with `APP_VERSION` (IM-04), so R3.d stays open until SE-84 is decided |
| S2 · admission freshness first | EB-4's freshness part alone, before any engine change | a tracker sub-flag, plus a stored bar close time for off-mode signals. Today the only such value is the instrumentation block `features_snapshot.identity.candle_close_time_ms`, written while evidence v2 is on (`SL:L204-224, L964-967 @ ea8ae4f`), and A44 deliberately refuses to rely on instrumentation (`SI:L107-114 @ ea8ae4f`). Using it would reverse that design choice, which needs its own decision | none |
| S3 · identity with fail-closed reads, without freshness | EB-0, EB-1 and EB-3; EB-2 off | a switch inside `integrity_check` (shared) and an analyzer stamp; the tracker refusal limited to identity-missing, or off | none, because EB-3 comes with enforce through the pinned gate at `SL:L730-737` |
| S4 · fail-closed reads alone | EB-3 without identity | the off path's cooldown handling changed | **WP-OD-01** (WP-B10) |
| S5 · engine freshness alone | EB-2 at the engine without EB-1 and EB-3 | a non-enforce call site at the engine | **WP-OD-01** |

**What never splits without new code.** EB-1 and EB-3 at the engine; EB-1 and EB-2 at the engine (one call, IM-02); EB-4's identity-missing refusal and EB-1 (the refusal needs the key EB-1 writes).

## 6. Relation to other tasks

- **WP-B10** owns the fail-open reads (OF-T07, R3.c); its cooldown hook is the pinned part of EB-3.
- **WP-B11** owns the freshness bound (OF-T08, OF-OD-12); EB-2 is its reference.
- **WP-C02 and SE-84** own the key content (R3.d); see [SETUP_KEY_PROPOSAL_SE84.md](SETUP_KEY_PROPOSAL_SE84.md).
- **WP-C04** owns admission by key (R3.b), which EB-4 does not provide: EB-4 checks freshness and key presence, not key uniqueness.
- **WP-C05** owns the no-re-fire rule across a version boundary (SE-36), which the A44 key lacks (IM-04).
- **WP-G05** is the gated activation of R3.a and R3.b; this file is the boundary input it names.

## 7. Findings

| ID | Finding | Class |
|---|---|---|
| IM-01 | One setting, read independently by three services; no site checks that they agree. Two partial combinations block all signals or all admissions (section 4) | SOURCE_VERIFIED (sites); INFERRED (combinations) |
| IM-02 | At the engine, identity, freshness and the duplicate check are one `integrity_check` call (`SI:L253-266 @ ea8ae4f`); there is no separate switch for any of them | SOURCE_VERIFIED |
| IM-03 | The "fail-closed cooldown read" is one cycle gate over four SAFETY reads: learned gates, open positions, cooldown and emitted setups (`SL:L404-413 @ ea8ae4f`) | SOURCE_VERIFIED |
| IM-04 | The enforce key includes `APP_VERSION` (`SL:L805, L813 @ ea8ae4f`; `SI:L86-88`). A change of release label alone re-keys every bar, and A44 has no activation-minute rule, so a label change during a bar's life can re-emit it. This is the hazard SE-36 names | SOURCE_VERIFIED (key); INFERRED (re-emission) |
| IM-05 | The tracker refusal is terminal, and the refused row still holds the symbol's 2 h cooldown | SOURCE_VERIFIED |
| IM-06 | Both freshness sites use the default bound of one bar; no setting changes it (`SL:L804-806 @ ea8ae4f`; `TT:L701 @ bb7825f`) | SOURCE_VERIFIED |
| IM-07 | Enforce adds a 2.0 s per-attempt limit and one retry to reads that off mode performs unbounded and once; its effect on cycle outcomes during database faults is mixed in direction | SOURCE_VERIFIED (bounds); INFERRED (effect) |

## 8. NOT VERIFIED

| Item | Blocker |
|---|---|
| How often each behaviour would remove a signal or an admission | Counting needs post-freeze runtime tables or evidence streams, which are protected (DG-33) |
| Whether enforce mode was ever on at runtime before 2026-10-31, and so whether any persisted `signals` row carries an A44 key | VER-02 is one observation; reading the database is outside this task |
| That the running images hold the source read here | Image filesystems were not read (RT-17) |
| Whether migration 011 is applied on the runtime database | Not read in this task; reading it is a database operation |
