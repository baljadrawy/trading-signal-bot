# setup_key composition proposal (SE-84 / DG-35)

> **Status: PROPOSAL FOR OWNER REVIEW. DG-35 / SE-84 is on HOLD.** The owner's iteration-2 decision allows a final proposal and synthetic conflict cases only: no activation and no integration. Nothing in this file is wired into a service, and the recommendation in section 7 is for review only. The decision itself stays with the owner (section 8). No statement here is a profitability claim: a correct key removes duplicate signals from measurement and execution, and establishes nothing about net edge (`TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md:L46 @ 46578aa`).

## Document control

| Field | Value |
|---|---|
| Decision | SE-84 in [STRATEGY_AND_EXECUTION_CONTRACT.md](remediation-design-pack-20261101/STRATEGY_AND_EXECUTION_CONTRACT.md) Part F; DG-35 in [DECISIONS_AND_GATES.md](remediation-design-pack-20261101/DECISIONS_AND_GATES.md) §1.1 |
| Remediation item | R3.d in [REMEDIATION_REGISTER.md](remediation-design-pack-20261101/REMEDIATION_REGISTER.md); OF-T09 in [OPPORTUNITY_FUNNEL.md](remediation-design-pack-20261101/OPPORTUNITY_FUNNEL.md) |
| Tasks it gates | WP-C02, and through it WP-C03, WP-C04, WP-C05 and WP-B05's `tie_break_key` ([IMPLEMENTATION_WORKPLAN.md](remediation-design-pack-20261101/IMPLEMENTATION_WORKPLAN.md) §4.3, §6). Activation is WP-G05 under DG-68 |
| Change class | This file: Documentation/design. Its tests: synthetic test code with no runtime effect |
| Evidence | [tests/test_setup_key_proposal.py](../../tests/test_setup_key_proposal.py): 102 synthetic cases, all passing (section 9) |
| Read with | [SIGNAL_INTEGRITY_MODE_DECOMPOSITION.md](SIGNAL_INTEGRITY_MODE_DECOMPOSITION.md) (WP-C01). The WP-A01 interface specification, `docs/design/STRATEGY_INTERFACE_v1.md`, written in parallel, refers to this file for the key |
| Branch | `feature/wp2-foundation-20261101`, HEAD `a03efdd`. Code read at `ea8ae4f` (signal_engine, shared), `bb7825f` (trade_tracker) and `a03efdd` (iteration-1 modules) |
| IDs | SK-A, SK-B, SK-C (compositions); SK-01 onwards (findings) |

### Anti-drift statement (charter §7)

1. **Goal alignment.** One emission per setup per closed bar is the charter's engineering criterion "no duplicate candle signal" (`TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md:L57 @ 46578aa`) and the R3 row's "idempotent symbol, strategy and candle key" (`L38`). The key only removes repeats. It creates no trade and no quota.
2. **Branch, SHA, runtime.** Source claims are SOURCE_VERIFIED at the named commits. The integrity mode is `off` at runtime, so no key of any kind is computed there today (RUNTIME_VERIFIED; `RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md:L94 @ 5d977f2`, VER-02).
3. **Scope.** SE-84 only. The enforce-mode split is WP-C01; the freshness bound is OF-OD-12; the cooldown is OF-OD-13.
4. **Evidence classes** follow charter §7.4.
5. **Permission class.** Documentation and synthetic tests. No database, service, network or protected data was touched.
6. **Deliverables.** This proposal, its tests and the owner question.
7. **DEVIATION ALERT.** None.

## 1. What the key has to satisfy

Requirements already written into the pack (SOURCE_VERIFIED by reading the named sections on this branch):

| # | Requirement | Where |
|---|---|---|
| Q1 | One `setup_key` per symbol, strategy, timeframe and bar close; a repeat evaluation of the same bar cannot create a second signal | OPPORTUNITY_FUNNEL.md §6 P5; charter R3 row |
| Q2 | Bracket prices are not in the key; a bracket hash is stored beside it, so a recomputed, different bracket on the same bar is a conflict (`F4.setup_conflict`), and an identical one is a duplicate (`F4.duplicate_setup`) | OPPORTUNITY_FUNNEL.md F4 "`setup_key`" |
| Q3 | The strategy identity is the five `StrategyVersion` fields; `lineage` never enters the identifier or the key | WP-IR-09; R3.d; OPPORTUNITY_FUNNEL.md F4 |
| Q4 | A release label such as `APP_VERSION` is not enough | OPPORTUNITY_FUNNEL.md F4; R3.d |
| Q5 | No re-fire across a version boundary: a new version evaluates only bars that close at or after its activation minute; an earlier bar is `F4.bar_before_version_activation` | SE-36; WP-C05 |
| Q6 | Admission keys on `setup_key` (at most one trade per key) | OPPORTUNITY_FUNNEL.md F7 "Idempotent admission"; R3.b; WP-C04 |
| Q7 | `tie_break_key` is a hash of (selection version, `setup_key`) | OPPORTUNITY_FUNNEL.md F6 "Total order"; WP-B05 |

Three pack texts already assume one of the two SE-84 options. They are listed here because choosing the other option means editing them (SK-01):
- WP-IT-09 (IMPLEMENTATION_WORKPLAN.md, WP-IR-09): "changing any of the five fields changes both" the identity hash and `setup_key`.
- OF-T09 acceptance (OPPORTUNITY_FUNNEL.md §9.2): "a new version gives a new key".
- R3 acceptance (REMEDIATION_REGISTER.md R3): "a version-identity test shows that changing `strategy_version` changes the key".

## 2. The keys that exist today

**A44 key, the only one that can run in a service** (SOURCE_VERIFIED; `shared/signal_identity.py:L64-88 @ ea8ae4f`):
- `"sk_" + sha256([identity_version, symbol, timeframe, candle_open_ms, trade_type, direction, strategy_version, setup_policy])[:40]`, with `strategy_version = config.APP_VERSION` passed by the engine (`signal_engine/signal_logic.py:L385, L805, L813 @ ea8ae4f`).
- It has no venue, no strategy identity beyond `trade_type`, and no symbol validation beyond "non-empty string" (`shared/signal_identity.py:L94-98 @ ea8ae4f`). Case variants of one symbol therefore get different keys (test `test_a44_key_is_case_sensitive_today`).
- It is computed only in enforce mode, which is off at runtime. Off-mode rows are inserted without the column, so migration 011 leaves them `NULL` (SOURCE_VERIFIED; `signal_engine/signal_logic.py:L998-1014 @ ea8ae4f`; `database/migrations/011_a44_signal_setup_key.sql:L5-9` at HEAD). Whether any persisted row carries an A44 key is NOT_VERIFIED (section 10).

**Iteration-1 rule-aware key, dormant** (SOURCE_VERIFIED; `shared/signal_integrity_v2.py @ a03efdd`):
- `setup_key_v2` = `"sk2_" + sha256([wp2-sid-v2, venue, symbol, strategy_id, strategy_version, rule_hash, timeframe, bar_close_ms, direction])[:40]` (L193-238).
- Every input is validated, and anything else raises `IntegrityInputError`: an uppercase symbol, a lowercase venue name, a semantic version, a 64-character lowercase hex `rule_hash`, a timeframe in A44's `TIMEFRAME_MS`, and the direction `long` (L72-75, L146-160, L203-225).
- The version-free candle key `"ck_"` (L146-188), the insert-once claim functions (L243-340) and the SE-36 rule `version_boundary_reason` (L386-394) sit beside it.
- `rule_hash` is meant to be `StrategyVersion.identity_hash`, the canonical hash of the five identity fields with `lineage` excluded (SOURCE_VERIFIED; `shared/strategy_identity.py:L374-410 @ a03efdd`).

## 3. Candidate compositions

| ID | Key over | Payload compared on a repeat | Code |
|---|---|---|---|
| **SK-A** · version in the key | venue, symbol, `strategy_id`, `strategy_version`, `rule_hash`, timeframe, bar close, direction | the bracket hash | the iteration-1 `setup_key_v2`, used unchanged (`sk2_`) |
| **SK-B** · version excluded, with a boundary rule | venue, symbol, `strategy_id`, timeframe, bar close, direction | hash of (`strategy_version`, `rule_hash`, bracket) | does not exist; `key_b` and `payload_b` are proposal helpers defined only in the test file (`skb_`, identity version `se84-sid-b1`) |
| **SK-C** · hybrid | SK-A as the identity key, plus a second insert-once guard on the SK-B key | as SK-A for identity; any second version on a bar is refused by the guard | not built; it would need a second unique index |

Both SK-A and SK-B use the SE-36 activation-minute rule (`version_boundary_reason`) as a mandatory step before the claim. The tests model this as one F4 identity stage: key and payload first, so malformed input fails closed; then the boundary rule; then insert-once (`f4_identity` in the test file).

**Reading of "lineage-level uniqueness" in SE-84.** Under SK-B the uniqueness scope is the `strategy_id`, which stays stable across versions. It is not the `lineage` field, which stays outside every key under WP-IR-09 (INFERRED; consistency note SK-07).

**Considered and set aside:**
- A candle-only key without `strategy_id` would make two strategies on one bar conflict, against OF F4's "one `Candidate` per (symbol, `strategy_id`, timeframe, `bar_close_time`)".
- Keeping the A44 key fails Q3 and Q4.

## 4. Semantics, case by case

Each row names the test that pins it; "rule" means the SE-36 activation-minute rule. The functions used are SOURCE_VERIFIED at `a03efdd`; the outcomes are the behaviour of synthetic inputs in the new test file, so they are INFERRED as statements about any future service path.

| Case | SK-A (version in key) | SK-B (version excluded) | Test |
|---|---|---|---|
| Same bar, same version, same bracket, re-analysed for the bar's life with a restart | one emission, then `F4.duplicate_setup` | same | `test_same_bar_same_setup_is_a_duplicate` |
| Same bar, same version, different bracket | `F4.setup_conflict`; the first payload is kept | same | `test_same_key_different_payload_is_a_conflict` |
| Same bar under a new version (MAJOR rule change, label-only bump, or a hash change under the same label), **rule off** | new key, so a second **emission** | same key, different payload: `F4.setup_conflict`, even with an identical bracket | `test_version_bump_on_the_same_bar_without_the_boundary_rule` |
| `lineage` changed only | same key, `F4.duplicate_setup` | same | `test_lineage_only_change_is_the_same_setup` |
| Any of the five identity fields changed | key changes | key changes only for `strategy_id`; the payload changes for every field | `test_each_identity_field_reaches_the_key_or_the_payload` |
| 15m, 1h, 4h and 1d bars sharing one close millisecond | four keys | four keys | `test_timeframes_sharing_a_close_are_separate_keys` |
| Timeframe outside `TIMEFRAME_MS` (`1w`, `4H`, `5m`) | refused, fail closed | same | `test_unsupported_timeframe_fails_closed` |
| Direction | `long` only; a second direction would be a separate key | same | `test_direction_is_long_only_and_keyed` |
| Non-canonical symbol or venue (case, blanks, separators) | refused, never normalised inside the key | same | `test_non_canonical_symbol_is_refused_not_normalised`, `test_non_canonical_venue_is_refused_not_normalised` |
| Case and blank variants after explicit upstream normalisation | one key; separator variants still refused | same | `test_explicit_upstream_normalisation_gives_one_key` |
| Two venues | never merged | same | `test_distinct_venues_are_never_merged` |
| `rule_hash` missing or invalid (`None`, empty, uppercase, 63 or 65 characters, non-hex, a release label, a number) | refused, nothing claimed | refused, though it is not keyed: the helper validates it and the payload needs it | `test_missing_or_invalid_rule_hash_fails_closed` |
| `strategy_version` missing or not semantic | refused | refused | `test_missing_or_invalid_strategy_version_fails_closed` |
| **Boundary crossing**: an old version emitted a bar, then the new version re-evaluates it | rule on: `F4.bar_before_version_activation`. Rule off: re-emission | rule on: `F4.bar_before_version_activation`. Rule off: `F4.setup_conflict` | `test_boundary_crossing_refire_of_an_emitted_bar` |
| Boundary crossing on a bar the old version evaluated **without** emitting | rule off: emission (the new version acts on a bar the old one decided) | **same**: there is no key to collide with | `test_boundary_rule_is_needed_even_when_the_version_is_not_keyed` |
| Activation minute recorded **earlier** than the real one | the pre-activation bar is re-emitted | `F4.setup_conflict` | `test_misrecorded_activation_minute` |
| Activation minute recorded **later** than the real one | more bars rejected, never a re-fire (the safe side) | same | `test_misrecorded_activation_minute` |
| Rollback to the previous version, recorded as a new activation | rule on: rejected; rule off: re-emission | rule on: rejected; rule off: conflict | `test_rollback_is_a_new_activation` |
| Dead zone after activation | at most one bar per timeframe: a 1d bar closed before activation cannot be used, and no 1d setup is possible until the next daily close | same | `test_boundary_dead_zone_lasts_at_most_one_bar` |
| Switch from the A44 key, or from unkeyed off-mode rows | no match with any `sk_` key or `NULL` row: guarded only by the rule | same | `test_identity_scheme_switch_is_a_rekey_boundary` |
| Within one version, against the A44 emission ledger | identical claim outcomes | not tested (the payload differs by design) | `test_composition_a_statuses_equal_the_a44_ledger_within_one_version` |

**What follows from the table.**
- **SK-02.** The boundary rule is required under **both** compositions. SK-B blocks the re-emission of an already **emitted** bar by construction, but not a new version acting on a bar the old version evaluated without emitting. Only the rule stops that (INFERRED; shown by synthetic test, not runtime evidence).
- **SK-03.** The cases that separate the two compositions are those where the rule fails or is absent: a mis-recorded activation minute, or a rollback recorded without one. There, SK-B degrades to a recorded conflict, and SK-A to a second emission (INFERRED; shown by synthetic test).
- **SK-04.** Under SK-B, every second version on a bar is a conflict. A side-by-side shadow evaluation of two versions on the same bars cannot share one emission store under SK-B; each evaluation stream would need its own ledger. Per-version attribution must come from the stored record, never from the key (INFERRED from the key definition).

**Admission by key (Q6).** Under SK-A, a key admits at most one trade per version. A cross-version re-emission that slipped past the rule would therefore be a new key at admission too. Under SK-B one key, and so at most one trade, covers every version on that bar (INFERRED; R3.b model `test_admission_by_key_admits_at_most_once_whatever_happened_first` in `tests/test_wp2_signal_integrity.py` applies unchanged to either key).

## 5. Compatibility with the A44 key and the persisted signals

| Aspect | SK-A | SK-B | Basis |
|---|---|---|---|
| Key namespace | `sk2_` + 40 hex | `skb_` + 40 hex | disjoint from A44's `sk_`, so no key of one scheme can equal a key of another; all fit the `TEXT` column (`test_key_namespaces_are_disjoint_from_a44`) |
| Schema | migration 011 is enough: nullable `setup_key TEXT`, partial unique index, `NULL` never constrained | same | SOURCE_VERIFIED; `database/migrations/011_a44_signal_setup_key.sql:L15-18` at HEAD |
| Old rows | A44-keyed and unkeyed rows never match: switching to SK-A is a re-key, guarded by the rule only | same | `test_identity_scheme_switch_is_a_rekey_boundary` |
| Stored comparison value | the engine compares `features_snapshot.setup_identity.bracket_hash` on a unique-index hit (`signal_engine/signal_logic.py:L266-269, L989-996 @ ea8ae4f`). SK-A keeps that meaning: a bracket hash | the stored value would have to cover the rule identity. Reusing the name `bracket_hash` for that would mislead; a new field means a change at the pinned conflict site | SOURCE_VERIFIED (sites); INFERRED (consequence) |
| Tracker | `integrity_admission_refusal` tests only that a key is present (`trade_tracker/main.py:L698 @ bb7825f`): compatible | compatible | SOURCE_VERIFIED |
| `signals.strategy_version` column | holds `APP_VERSION` today (`signal_engine/signal_logic.py:L988 @ ea8ae4f`). The key carries the version, but the column does not until that pinned line changes | attribution depends on a stored identifier, because the key carries none | SOURCE_VERIFIED (column); INFERRED (need) |
| A44 bar reference | A44 hashes the bar's open ms, both proposals its close ms; `CandleRef.from_setup_identity` maps one to the other exactly | same | SOURCE_VERIFIED; `shared/signal_integrity_v2.py:L167-170 @ a03efdd`; `tests/test_wp2_signal_integrity.py::test_candle_bounds_match_a44` |
| Symbol case | A44 accepts any case and keys case variants apart; both proposals refuse a non-canonical symbol and expect the F0 adapter to supply the venue's own form | same | `test_a44_key_is_case_sensitive_today`; `test_explicit_upstream_normalisation_gives_one_key` |

## 6. Migration and rollback

**Common to both.**
- **No schema migration for the key itself** (section 5). SK-C alone would need a second unique index, and so a new migration numbered after the ledger's planned `012` (IMPLEMENTATION_WORKPLAN.md WP-E03).
- **Switching on is a strategy-version boundary.** SE-38 lists the identity key among MAJOR changes, so the first activation of either key needs a `VERSION_BOUNDARY` entry with its activation minute ([VERSION_BOUNDARY.md](../../deploy/VERSION_BOUNDARY.md); SE-36). Bars that closed before that minute are rejected, which gives the dead zone of section 4: at most one bar per timeframe.
- **The activation minute must reach the identity stage.** No such input exists in the A44 path today. `version_boundary_reason` refuses a missing or non-minute value with `ValueError` (SOURCE_VERIFIED; `shared/signal_integrity_v2.py:L386-394 @ a03efdd`), so a missing input fails closed. A minute recorded too early is the one input error that lets a pre-activation bar through (`test_misrecorded_activation_minute`). Deriving the minute from the activating service, rather than typing it into the record, removes that error mode; the boundary template belongs to WP-A01.
- **History is never rewritten.** No backfill: old rows keep their A44 key or `NULL` (migration 011's own policy, `011_a44_signal_setup_key.sql:L5-7`).

**Rollback.**
- **To the previous strategy version, with the new key kept.** This is a new activation with its own minute. The rule then rejects the bars the rolled-back version emitted (`test_rollback_is_a_new_activation`). Without the rule, SK-A re-emits and SK-B records a conflict.
- **Back to A44 code** (enforce mode with the `sk_` key). A44 has no activation-minute rule, and its emitted-key pre-read sees only `sk_` keys (`signal_engine/signal_logic.py:L379-402 @ ea8ae4f`). A bar emitted under the new key and still inside its bar can therefore be emitted once more under the A44 key once the 2 h symbol cooldown has passed. That holds for SK-A and SK-B alike (INFERRED). With the tracker in enforce mode, admission freshness refuses it once its bar is superseded. The rollback record should name this exposure.
- **Back to off mode.** Identity, freshness and insert-once all stop, so today's re-fire returns (R3).
- **Changing composition later.** SK-B to SK-A, or the reverse, re-keys every setup: one more boundary. SK-A to SK-C only adds a guard, and every SK-A key stays valid.

**Integration path, once DG-35 is decided (none of this is done now).**
- The key can live in `shared/signal_identity.py` under a new identity version, which `parse_integrity_settings` already parses as `SIGNAL_IDENTITY_VERSION`, with the A44 key as default (`shared/signal_integrity_v2.py:L443-477 @ a03efdd`). The default then stays byte-identical to today.
- The engine call sites pass `config.APP_VERSION` (`signal_engine/signal_logic.py:L385, L805, L813 @ ea8ae4f`) and are in a **pinned** file. There are two routes, both still subject to DG-35: resolve the `StrategyVersion` from the candidate inside `shared/signal_identity.py`, which leaves the pinned call byte-identical; or change the call sites, which needs WP-OD-01 (DG-71, on HOLD).

## 7. Recommendation (for review only; nothing is activated)

**Recommended for review: SK-A, the strategy version in the key, with the SE-36 activation-minute rule mandatory and fail-closed.** The key is built only from canonical venue and symbol values, which are refused otherwise, and `rule_hash` is `StrategyVersion.identity_hash`.

Reasons, each traceable to section 4 or 5:
1. **It is what the pack already specifies.** OF F4, R3.d, WP-C02's "Done" line (the key "is derived from the five identity fields and the bar close time"), WP-IT-09, OF-T09 and the R3 acceptance test all assume the version is in the key (SK-01). SK-B would need those texts edited first.
2. **It already exists and is tested.** `setup_key_v2` is iteration-1 code, used here unchanged; its pinned value still holds (`test_composition_a_is_the_iteration1_key_unchanged`). SK-B needs a new key function.
3. **It keeps the stored comparison's meaning.** On a unique-index hit the engine compares a bracket hash; SK-A keeps that meaning. SK-B changes what the stored value means, at a pinned site (section 5).
4. **It keeps versions separately attributable,** and it lets two versions be evaluated side by side on the same bars in one store. Under SK-B the second version on any bar is always a conflict (SK-04).
5. **SK-B's extra protection does not remove the need for the rule.** The rule is mandatory under both (SK-02). SK-B's advantage is limited to the cases where the rule is mis-recorded or absent (SK-03). That input-integrity risk is better closed at its source: record the activation minute from the activating service, and refuse to start when it is missing.
6. **SK-A leaves SK-C open.** A version-free guard can be added later without re-keying anything. Moving from SK-B to SK-A later would re-key every setup.

**What SK-A does not give.** It does not protect by construction when the boundary rule is mis-configured: in that case the bar is emitted twice. If the owner weighs that risk above per-version identity and attribution, the options are SK-B or SK-C.

**Condition attached to SK-A (SK-09).** Under SK-A, any change of `identity_hash` re-keys every setup, a label-only version bump included. The iteration-1 version-boundary report classifies a label-only bump as `LABEL_ONLY` with `boundary_required: NO` and drafts no entry (SOURCE_VERIFIED; `shared/strategy_version_boundary.py:L12-16, L109-118 @ a03efdd`). Under SK-A such a bump would still need an activation minute. Under SK-B it would turn in-flight bars into conflicts, which also changes emission. Either way, the report and the WP-A01 boundary template should treat any `identity_hash` change as needing an activation minute.

## 8. Owner question (DG-35 / SE-84)

> **Which composition defines `setup_key` for the new identity version?**
> - **(A)** The strategy version in the key (`setup_key_v2`), with the mandatory SE-36 activation-minute rule: per-version uniqueness and attribution; the re-fire guard is the rule alone.
> - **(B)** The strategy version excluded, uniqueness per `strategy_id`, with the same mandatory rule: cross-version re-emission of an emitted bar becomes a recorded conflict by construction; per-version attribution comes only from the stored record; shared-store side-by-side evaluation is not possible; the pack texts of SK-01 must be edited.
> - **(C)** (A) plus a version-free emission guard (a second unique index): both properties, at the cost of a second constraint and a new migration.

Deciding DG-35 unlocks the completion of WP-C02, and through it WP-C03, WP-C04, WP-C05 and the `tie_break_key` of WP-B05. It does not activate anything. Activation stays WP-G05 under DG-68, and its packaging is DG-38, prepared by [SIGNAL_INTEGRITY_MODE_DECOMPOSITION.md](SIGNAL_INTEGRITY_MODE_DECOMPOSITION.md).

## 9. Test evidence

[tests/test_setup_key_proposal.py](../../tests/test_setup_key_proposal.py) uses `shared/signal_integrity_v2.py` unchanged. SK-B exists only as proposal helpers inside that file (`key_b`, `payload_b`, `canonical_symbol`, `canonical_venue`, and the stage model `f4_identity`). Run with the minimal environment, no database or network: **102 passed.** The iteration-1 regression files `tests/test_wp2_signal_integrity.py` and `tests/test_a43_signal_integrity.py` stay green (169 passed).

| Required case | Tests | Cases |
|---|---|---|
| Same bar, same setup: duplicate | `test_same_bar_same_setup_is_a_duplicate` | 4 |
| Same key, different payload: conflict | `test_same_key_different_payload_is_a_conflict` | 2 |
| Version bump on the same bar | `test_version_bump_on_the_same_bar_without_the_boundary_rule`, `test_lineage_only_change_is_the_same_setup`, `test_each_identity_field_reaches_the_key_or_the_payload` | 13 |
| Timeframe and direction separation | `test_timeframes_sharing_a_close_are_separate_keys`, `test_unsupported_timeframe_fails_closed`, `test_direction_is_long_only_and_keyed` | 12 |
| Symbol case and venue normalisation | `test_non_canonical_symbol_is_refused_not_normalised`, `test_non_canonical_venue_is_refused_not_normalised`, `test_explicit_upstream_normalisation_gives_one_key`, `test_distinct_venues_are_never_merged`, `test_a44_key_is_case_sensitive_today` | 29 |
| Missing or invalid `rule_hash` fails closed | `test_missing_or_invalid_rule_hash_fails_closed`, `test_missing_or_invalid_strategy_version_fails_closed` | 26 |
| Boundary-crossing re-fire | `test_boundary_crossing_refire_of_an_emitted_bar`, `test_boundary_rule_is_needed_even_when_the_version_is_not_keyed`, `test_misrecorded_activation_minute`, `test_rollback_is_a_new_activation`, `test_boundary_dead_zone_lasts_at_most_one_bar` | 10 |
| Compatibility and pins | `test_composition_a_is_the_iteration1_key_unchanged`, `test_composition_b_key_is_pinned_and_version_free`, `test_key_namespaces_are_disjoint_from_a44`, `test_identity_scheme_switch_is_a_rekey_boundary`, `test_composition_a_statuses_equal_the_a44_ledger_within_one_version` | 6 |

These tests show identity properties of synthetic inputs. They are not runtime evidence and say nothing about market behaviour.

## 10. NOT VERIFIED

| Item | Blocker |
|---|---|
| Whether any persisted `signals` row carries an A44 key | VER-02 observes `off` on one date only; reading the database is outside this task |
| Whether migration 011 is applied on the runtime database | a database read |
| How often a cross-version re-fire or a same-bar repeat would occur | counts need protected runtime data (DG-33) |

## 11. Findings and consistency notes

| ID | Finding | Class |
|---|---|---|
| SK-01 | WP-IT-09, OF-T09's acceptance and the R3 acceptance test assume the version is in the key; SK-B would require editing them | SOURCE_VERIFIED |
| SK-02 | The boundary rule is needed under both compositions | INFERRED (synthetic test) |
| SK-03 | The compositions differ only where the rule is mis-recorded or absent | INFERRED (synthetic test) |
| SK-04 | Under SK-B two versions cannot share one emission store, and attribution must come from the stored record | INFERRED |
| SK-05 | The A44 key accepts any symbol case and keys case variants apart (`shared/signal_identity.py:L94-98 @ ea8ae4f`) | SOURCE_VERIFIED |
| SK-06 | The interface type `Timeframe` includes `1w` (STRATEGY_AND_EXECUTION_CONTRACT.md §B3), but A44's `TIMEFRAME_MS` has no `1w` (`shared/signal_identity.py:L35 @ ea8ae4f`). Both keys refuse a `1w` setup, fail closed, until that table grows | CONTRADICTORY |
| SK-07 | SE-84's phrase "lineage-level uniqueness" is read here as uniqueness per `strategy_id`; the `lineage` field stays outside every key (WP-IR-09) | INFERRED |
| SK-08 | WP-C02's file list names `shared/signal_identity.py` for the new identity version, while iteration 1 placed `setup_key_v2` in `shared/signal_integrity_v2.py` (WP2_ENGINEERING_FOUNDATION_STATUS.md, WP-C02 row). This is a placement note, not a conflict: the key can be called from either | SOURCE_VERIFIED |
| SK-09 | A label-only version bump needs no boundary under the version-boundary report, yet it re-keys every setup under SK-A, and it turns in-flight bars into conflicts under SK-B | SOURCE_VERIFIED (report); INFERRED (consequence) |
