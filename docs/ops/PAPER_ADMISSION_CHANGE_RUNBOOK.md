# Paper Admission Change Runbook (DRAFT)

> **Status: DRAFT, NOT AUTHORIZED FOR USE.** This is the WP-B13 deliverable of the [implementation workplan](../design/remediation-design-pack-20261101/IMPLEMENTATION_WORKPLAN.md). Before any use it needs owner review and an independent review, as every production-operations definition does (DFP:L73). The runbook executes nothing. Approving it would authorize no operation: each use still needs the owner's approval of that specific operation on that specific service (COPS:L92-93). The approval of WP2-START (DG-70) and the integrated-development decision (WID) do not authorize any step below (WID:L18, L26).

## Document control

| Field | Value |
|---|---|
| This file | `docs/ops/PAPER_ADMISSION_CHANGE_RUNBOOK.md`, task WP-B13 (R6), change class Documentation/design |
| Why it exists | Under current governance, changing Paper admission outside its runbook is forbidden (DFP:L104). The funnel design therefore keeps OF-T12 as a design until the owner decides it and a runbook exists. That is the governance note in [OPPORTUNITY_FUNNEL.md](../design/remediation-design-pack-20261101/OPPORTUNITY_FUNNEL.md) §12 (OFN:L537) and its F7 governance bullet (OFN:L359). The gated item WP-G17 names this runbook as a prerequisite (WPL:L786) |
| Baseline | branch `feature/wp2-foundation-20261101` at `a03efdd`; `main` `46578aa`. This file makes no runtime claim |
| Governing documents | [COMPOSE_OPERATIONS.md](COMPOSE_OPERATIONS.md) for every production command, which takes precedence over this file (DFP:L121); [Development-First Policy](../governance/DEVELOPMENT_FIRST_POLICY.md); [Owner Operating Contract](../governance/OWNER_OPERATING_CONTRACT.md); [WP2 integrated development decision](../governance/WP2_INTEGRATED_DEVELOPMENT_DECISION_2026-11-01.md); the [charter](../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) |
| Companions | [VERSION_BOUNDARY.md](../../deploy/VERSION_BOUNDARY.md) (the append-only boundary log); `deploy/VERSION_BOUNDARY_TEMPLATE.md` (the strategy-boundary template of WP-A01, written in the same iteration and referenced here by path until it is on the branch); [DECISIONS_AND_GATES.md](../design/remediation-design-pack-20261101/DECISIONS_AND_GATES.md) (DG rows) |
| Review state | owner review: PENDING. Independent review: PENDING. A review in the session that wrote this draft is not independent |

### Anti-drift statement (charter §7)

1. **Goal alignment.** An admission change decides which ranked Opportunities become Paper trades. Discovery stays daily and complete. This runbook creates no trade quota and no forced admission, and an empty cycle stays a valid outcome (`CH:L8`, `CH:L10`; OFN:L358).
2. **Branch, SHA, runtime identity.** As in document control. The current halt and pause state is NOT_VERIFIED here; a Class B pre-gate must verify it from the database (COPS:L19-28).
3. **Scope.** WP-B13 for R6; it serves WP-G17 and every later admission change (section 1). Excluded: running anything; choosing any option, parameter or order of services for a specific change; any B3 reset or `/resume`.
4. **Evidence class.** Each rule cites its source with `path:Lx @ commit` or an alias. Rules taken from governance text are DOCUMENTED_ONLY. Rules this draft derives from them are marked INFERRED.
5. **Permission class.** This file is documentation. A use of it is a deployment-class operation (Class B) that carries out a strategy-version change. Neither class implies the other (`CH:L65`).
6. **Acceptance and rollback.** Acceptance needs owner review and independent review (WPL:L397; DFP:L73). Rollback of this file: revert its commit.
7. **DEVIATION ALERT.** None raised.

### Source aliases

| Alias | Path @ commit |
|---|---|
| CH, OOC, DFP | `docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md`, `docs/governance/OWNER_OPERATING_CONTRACT.md`, `docs/governance/DEVELOPMENT_FIRST_POLICY.md`, all `@ 46578aa` |
| WID | `docs/governance/WP2_INTEGRATED_DEVELOPMENT_DECISION_2026-11-01.md @ f0c560d` |
| COPS | `docs/ops/COMPOSE_OPERATIONS.md @ 46578aa` |
| VB | `deploy/VERSION_BOUNDARY.md @ 46578aa` |
| PEO | `docs/ops/PAPER_ECONOMIC_OBSERVATION.md @ 46578aa` |
| OFN, SEC, WPL | the pack files [OPPORTUNITY_FUNNEL.md](../design/remediation-design-pack-20261101/OPPORTUNITY_FUNNEL.md), [STRATEGY_AND_EXECUTION_CONTRACT.md](../design/remediation-design-pack-20261101/STRATEGY_AND_EXECUTION_CONTRACT.md) and [IMPLEMENTATION_WORKPLAN.md](../design/remediation-design-pack-20261101/IMPLEMENTATION_WORKPLAN.md), line numbers as committed at `5cd1a61` |

## 1. Scope

**A Paper admission change** is any change to the running Paper path that alters which ranked Opportunities become Paper trades, or how a refusal is decided, ordered or recorded (INFERRED from DFP:L104 and OFN F7). It covers:
- the F7 hand-off of OF-T12: rank-order offering, one capacity authority, a record for every refusal, and declared refusal semantics (WP-G17; DG-32, DG-28, DG-72);
- admission by `setup_key` (WP-G05; DG-35, which is on HOLD, so this is not usable until the owner decides it);
- capacity, exposure or loss-ladder rules applied at admission (WP-G23, WP-G26);
- enabling funnel writers where they touch admission (WP-G19, "DFP:L104 where admission is touched", WPL:L788);
- a mode or flag in the admission-authority service or in the delivery gate that changes an admission result. The observe-mode change of 2026-10-27 was of this kind (VB:L7-35; PEO:L173-199).

**Out of scope:**
- **B3 reset, `/resume` and technical-halt clearance.** These follow the [loss-streak recovery runbook](../loss_streak_recovery_runbook.md) and their own owner gates (DFP:L9, L104). An admission change never clears a pause or halt (PEO:L169-171, L192).
- **The learner.** It stays stopped and needs separate authorization (COPS:L30-32).
- **Every Class C command** (COPS:L142-157).

**Where each kind of work runs** (WID:L16-19; DOCUMENTED_ONLY). The integrated-development decision separates two environments:

| Environment | What may happen there | Does this runbook apply? |
|---|---|---|
| Isolated, disposable development containers, with no shared or live database, protected datasets, production secrets or live service dependencies | development tests of an admission change may start and restart them, with rollback and cleanup (WID:L17) | no. Such a test is not a Paper admission change. Its results are prerequisites (section 2), never runtime validation (OOC:L16-18) |
| Existing running or shared-host bot containers, live Paper paths, shared PostgreSQL, on-host builds, the learner, and service restarts or recreates | only operations under COMPOSE_OPERATIONS.md, with operation-specific authorization; the decision is not blanket Class B approval (WID:L18) | yes, whenever the operation changes admission |

R&D status alone does not prove that an environment is isolated (WID:L16). If a truly isolated environment cannot be established, development continues with source integration and local synthetic tests, and the owner receives the minimal, specific operational request (WID:L19).

**Services involved.** The admission authority is `trade_tracker` (SOURCE_VERIFIED as a record, VB:L12). The delivery gate in `telegram` also applies a capacity check today (OFN:L542-547). In the target design it becomes a recorded mirror of the authority (OFN F7, WP-IR-03). Which services a given change touches is fixed in its approved plan, not here.

## 2. Preconditions and gates

All of these must hold before step S1. If any is missing, the operation does not start; there is nothing to stop, because nothing has run.

| # | Precondition | Source |
|---|---|---|
| P1 | The owner has decided every DG row the change depends on (for OF-T12: DG-32, DG-28 and DG-72; any row on HOLD, such as DG-35, blocks), and DG-68 for activation. The packaging of boundaries is decided (DG-38) | DECISIONS_AND_GATES.md section 1 |
| P2 | The owner has declared the version boundary (strategy or risk policy, section 3) and its Paper window (class D2). If the window is meant to produce governed evidence, the WP3 decisions come first | DFP:L43, L63; `CH:L51`; OOC:L36; WPL §6 "WP5 (WP3 if evidential)" |
| P3 | The exact candidate commit is pushed to GitHub before deployment, its tests are green, and the deployable code has an independent review. A merge is a separate owner decision and is not a deployment authorization | DFP:L18, L73; OOC:L15, L18 |
| P4 | At the flag default, admissions are byte-identical to current behaviour on golden fixtures, and an unknown flag value refuses to start | WPL:L387 (WP-B12 acceptance); DFP:L87 |
| P5 | The approved image is named in the plan. No image is built, rebuilt, retagged or pulled in production; a build happens only in an isolated clone with a unique tag | COPS:L40-48, L147-149, L167 |
| P6 | A change to `docker-compose.yml` went through a PR. Installing the merged file in production is its own owner-authorized step with offline hash verification | COPS:L49-51 |
| P7 | The owner has approved this specific Class B operation on this specific service; the decision is not blanket Class B approval. The plan names the exact host, service, database dependency, blast radius, rollback and gate | COPS:L92-93; WID:L18-19 |
| P8 | A written, gated per-rollout plan or checklist exists, with an evidence folder. Rollback is pre-approved as part of it, with the exact prior image named | COPS:L93, L121-122 |
| P9 | The halt and pause state is read from the database by an owner-approved read, not taken from any document. The read changes nothing | COPS:L19-28; DFP:L58 |
| P10 | The learner is stopped | COPS:L30-32, L112 |
| P11 | No step reads sealed holdout outcomes, counts or timestamps | DFP:L57 |
| P12 | Every step mutates one service only | COPS:L29 |

## 3. Version-boundary record

Every Paper admission change is a declared version boundary, of the strategy or of the risk policy (VB:L3; DFP:L63; `CH:L51`; INFERRED for admission changes in general). Its record is appended to [VERSION_BOUNDARY.md](../../deploy/VERSION_BOUNDARY.md), which is append-only: versions are never pooled without stratification, and nothing is attributed retroactively (VB:L3-5).

- **Template.** The entry follows `deploy/VERSION_BOUNDARY_TEMPLATE.md`, the strategy-boundary template of WP-A01. It is written in the same iteration as this draft, and its review is part of DG-69. Until that template is reviewed, the field list of SE-36 is the reference (SEC:L247):
  - `boundary_id` and `strategy_id`;
  - the version before and after;
  - the three hashes (`source_hash`, `config_hash`, `contract_hash`) before and after;
  - `fill_model_id` and `cost_model_id`;
  - the activation minute;
  - the admission-authority service;
  - image identifiers;
  - the stratification rule.
- **Precedent fields.** The existing entry VB-2026-10-27-01 also records these fields, which an admission change needs as well (INFERRED from VB:L10-35):
  - the source commit, and the compose commits with their blobs;
  - the rollback images;
  - the services left unchanged;
  - the pause state at activation;
  - for a change carried out in more than one step, one minute per service.
- **Timing.** The entry is written right after the step that activates the change, and it is amended after each later step. The precedent was written late, and the discrepancy is kept explicit in the record (VB:L38-46). Writing on time avoids that (INFERRED).
- **Amendment, never rewrite.** A field that stays PENDING, for example a hash that only the first evidence record can show, is filled later by an amendment. The entry's other fields are never rewritten (VB:L44-46).
- **Owner-approved activations only.** An entry is written only for an owner-approved activation (SEC:L249). An undeclared identity is a stop condition (section 8).

## 4. Identity captures before and after

The captures follow the Class B gates exactly (COPS:L108-122). This runbook adds no field to them and drops none. They are taken with the read-only Class A means of COPS:L68-78. A full rendered configuration is never printed, because it would expose every environment secret (COPS:L80-88).

**Where.** Into a timestamped evidence folder with mode 700, created for this operation (COPS:L109-110). Network addresses and other host details stay in that folder, never in a tracked record.

**Before each step (pre-identity, COPS:L109-111).** For the target service:
- container ID;
- image ID and reference;
- `StartedAt` and `RestartCount`;
- network IPs;
- the `com.docker.compose.config-hash` label.

The same fields are captured for every other bot container, to prove later that they were untouched.

**Pre-gates (COPS:L112-115).**
- The halt and pause state is as the approved plan states. It is read from the database (P9), never assumed.
- The learner is still stopped.
- The target is not a D3 service, unless the D3 phase is approved.
- For a recreate, the rendered config hash of the target equals the expected hash, and the image is the approved one.

**After each step (post-checks, COPS:L117-120).**
- The target's new identity matches the plan. For a recreate, that means the expected image and config hash and a new container ID.
- Every other container is unchanged in every captured field.
- The health check reads `healthy` on two consecutive fresh reads, never a cached value.
- The logs are reviewed.
- The halt and pause state and the stopped learner are verified again.

A precedent ran the same comparison after each of its two steps over the other six containers (`deploy/paper-observe-bb7825f/IMAGES.md @ 46578aa`).

## 5. Steps

Each step below is one Class B operation on one service. Nothing here is run by this draft.

| Step | Action | Source |
|---|---|---|
| S0 | **Plan, no host action.** Fix in the approved plan: the change, its DG decisions, the target services and their order, the approved and prior images, the expected config hash per service, the boundary entry draft, the rollback and the evidence folder. The order of services is the plan's decision. The precedent activated the admission authority first and the delivery gate second (VB:L12-13; PEO:L180-181) | COPS:L93; P1–P12 |
| S1 | **Pre-identity capture and pre-gates** for the first target (section 4). Any gate that fails is a STOP | COPS:L109-115 |
| S2 | **Exactly one command for one service**, in the canonical form below, run only from the production checkout that COMPOSE_OPERATIONS.md names (COPS:L100). No other command form is used | COPS:L100-103, L116 |
| S3 | **Post-checks** (section 4) and the verification of section 6 that applies after this step | COPS:L117-120 |
| S4 | **Boundary record.** Write the entry after the activating step, or amend it after a later step (section 3) | VB:L3-5, L38-46 |
| S5 | **Next service**, if the plan names one: repeat S1 to S4. Between steps, the intermediate state is the one the plan declares, and the record states it | VB:L12-13 |
| S6 | **Report.** Report Saved, Integrated, Deployed and Validated as separate states, each only on its own evidence; none implies the next | OOC:L16; DFP:L11; WID:L13 |

The only command form this runbook refers to is the canonical Class B recreate and deploy form, quoted unchanged from COPS:L103. `<svc>` is the one service of the step:

```
docker compose -p trading-signal-bot -f docker-compose.yml up -d --no-deps --no-build --pull never --force-recreate <svc>
```

## 6. Verification

After the last step, all of these must hold. Each is checked against the evidence folder and the plan.

| Check | Expected | Source |
|---|---|---|
| Identity | every target has the planned image and config hash; every other container is unchanged | COPS:L117-119 |
| Health | two consecutive fresh `healthy` reads per target, plus a clean log review | COPS:L119-120 |
| Safety state | the halt and pause state is unchanged by the operation; the learner is stopped; `PAPER_TRADING=true` | COPS:L120; PEO:L169-171; DFP:L54 |
| Setting in effect | the admission flag or mode in effect equals the approved value. It is read from a filtered environment view, never a full render | COPS:L80-88; precedent `deploy/paper-observe-bb7825f/IMAGES.md @ 46578aa` |
| Boundary record | written or amended for each step, with every PENDING field named | section 3 |
| First decision under the new version | when an admission or refusal next occurs, its record carries the new version identity. A refusal carries a `RejectionRecord` with stage F7 and its code, such as `F7.capacity_full` | SEC:L247; OFN F7 (WP-IR-03 to WP-IR-05); PEO:L188-189 |

**Validated** is reported only when the last check has been observed. Until a first admission or refusal occurs, the state is "Deployed, not validated". The precedent was reported that way while a pause blocked all admissions (`deploy/paper-observe-bb7825f/IMAGES.md @ 46578aa`). The check reads only what the plan names, and never an outcome, count or timestamp of the sealed holdout (DFP:L57).

**Not verification.** A merged commit, green CI or a passing parity test in an isolated development container is a precondition (P3, P4), not runtime validation (OOC:L16-18). A successful admission change says nothing about profitability (`CH:L46`; DFP:L31).

## 7. Rollback

- **Form.** Rollback uses the same canonical form on the exact prior image, with the same gates and captures (COPS:L124-125). That image is the dedicated rollback override or the rollback tag named in the approved plan.
- **Pre-approval.** Rollback runs only if it was pre-approved as part of the plan (COPS:L121-122). Otherwise a needed rollback is a STOP, and the owner decides.
- **Order.** Rollback goes one service at a time, in the order the plan states (INFERRED from COPS:L29).
- **Compose file.** If the change installed a new `docker-compose.yml`, restoring the prior file is its own reviewed, owner-authorized step with hash verification (COPS:L49-51).
- **Boundary.** A rollback is itself a version boundary. It is appended as a new entry, and the forward entry is never deleted or rewritten. Trades admitted under the new version stay attributed to it (VB:L3-5; PEO:L194-199).
- **Not part of rollback.** Rollback does not clear a pause or halt, and it does not touch historical trade or risk records (DFP:L9; PEO:L167-171).

## 8. Absolute STOP rule

If anything is unexpected, STOP and return to the owner. Do not diagnose and continue, and do not improvise a workaround (COPS:L52-54). Keep the evidence (COPS:L121). In production operations this rule is absolute (DFP:L70). It applies in particular to:
- a hash mismatch or an unexpected diff;
- an unexpected container ID, image or state change, on the target or on any other container;
- a failing gate (sections 2 and 4), including a halt or pause state that differs from the plan;
- a secret in any output;
- a version whose `source_hash`, `config_hash` or `contract_hash` differs from the declared identity, which is an undeclared version (SEC:L237; `CH:L57`);
- a boundary record that cannot be written as section 3 requires;
- a needed rollback that was not pre-approved.

A STOP ends the operation. It resumes only on a new owner decision, never on the operator's own judgement.

## 9. Open items before review

| Item | State |
|---|---|
| Owner review and independent review of this draft | PENDING (DFP:L73; WPL:L390-397) |
| Review of `deploy/VERSION_BOUNDARY_TEMPLATE.md` | part of DG-69, APPROVED FOR COMPLETION AND REVIEW; not yet accepted. Section 3 uses SE-36 until then |
| Cross-check with WP-B12, the F7 hand-off slice | not possible yet (WPL:L394). WP-B12 has F7 record builders only; the hand-off itself is not built ([WP2_ENGINEERING_FOUNDATION_STATUS.md](../design/remediation-design-pack-20261101/WP2_ENGINEERING_FOUNDATION_STATUS.md) section 2) |
| Refusal semantics (DG-32: drop with a record, or a bounded hold) | OPEN; the F7 rows of section 6 depend on it |
| `setup_key` composition (DG-35) | HOLD; admission by `setup_key` is out of use until it is decided |
| Current halt and pause state | NOT_VERIFIED here; P9 requires an approved read (COPS:L19-28) |
| Image-content parity of the running services | NOT_VERIFIED; DG-61 |
