# Learner and optimizer build-hazard design (WP-F02)

| Field | Value |
|---|---|
| Task | WP-F02, lane F ([IMPLEMENTATION_WORKPLAN.md](../design/remediation-design-pack-20261101/IMPLEMENTATION_WORKPLAN.md) §4.6) |
| Register item | R9.d. It feeds R9.d2 (the WP-F03 static guards) and R9.d3 (the WP-G33 install) ([REMEDIATION_REGISTER.md](../design/remediation-design-pack-20261101/REMEDIATION_REGISTER.md), R9) |
| Audit sources | ARC-18 to ARC-20 and LRN-19. Supporting: LRN-01, LRN-03, LRN-05 to LRN-12, LRN-18, RT-05, RT-07, RT-09 to RT-12, RT-15, RT-17, CON-02, CON-19, VER-03, VER-14, VER-23, VER-29, VER-31 |
| Change class of this document | Documentation/design |
| Baseline | Branch `feature/wp2-foundation-20261101` at `a03efdd`. HEAD advanced to `9588f45` while this was written; that commit changes pack documents and adds a runbook, and touches no file cited here by line. The tracked `docker-compose.yml` is blob `d1a4b197`; it is the same blob at `46578aa` and `eba90dd`, and the host file had the same blob on 2026-10-31 (RT-24, `REP:L305 @ 5d977f2`, RUNTIME_VERIFIED) |
| Status | PROPOSED for owner review. Nothing in this document has been applied |
| Gate | WP2-START (DG-70, development-only). Installing a Compose change on the host is WP-G33: a Class B operation that needs a named approval |

## 0. Scope and boundaries

- **No file is changed by this document.** `docker-compose.yml` is not edited.
  - The [integrated-development decision](../governance/WP2_INTEGRATED_DEVELOPMENT_DECISION_2026-11-01.md) makes a change to the tracked Compose file development work (`docs/governance/WP2_INTEGRATED_DEVELOPMENT_DECISION_2026-11-01.md:L9 @ a03efdd`, DOCUMENTED_ONLY). That change goes through its own pull request (§4).
  - Installing the file on the host, any learner operation and any on-host build stay under [COMPOSE_OPERATIONS.md](COMPOSE_OPERATIONS.md) and an operation-specific authorization (same file, L18). The decision excludes learner activation (L27).
- **Nothing is deleted.** §9 lists every object whose removal would need a named approval. None is requested.
- **A disabled flag or a Compose profile authorizes nothing.** Disabled feature flags do not authorize activation, governed experiments or production changes (charter, `docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md:L51 @ a03efdd`, DOCUMENTED_ONLY).
- **No economic claim.** The learner and the optimizer are discussed as operational hazards only. Neither has evidence of a post-cost edge (LRN-07, LRN-08, LRN-11, LRN-12; `REP:L777-782 @ 5d977f2`).
- **The design covers four things:**
  - every Compose service that builds from the working tree, with a guard for each (§2, §3);
  - the exact proposed Compose diff (§4);
  - the version-boundary record required before `LEARNING_GATES_ENABLED` can be set (§5);
  - the static-guard test design for WP-F03 (§6).

## 1. Sources, abbreviations and evidence classes

| Short form | Path | Status on this branch |
|---|---|---|
| REP | `docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md @ 5d977f2` | not merged; cited by path, not linked |
| ADD | `docs/audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md @ 5d977f2` | not merged; cited by path, not linked |

- **Evidence classes** follow the charter (§7.4) and the pack:
  - SOURCE_VERIFIED: read in a tracked file at the named commit; it says nothing about runtime behaviour.
  - RUNTIME_VERIFIED: used only where REP or ADD is cited.
  - Claims about Docker Compose behaviour that this task could not exercise are INFERRED. This task ran no Docker or Compose command.
- **Line numbers.** The following files have the same blob at `a03efdd` and `46578aa`, so their line numbers match the pack's citations: `docker-compose.yml`, `docs/ops/COMPOSE_OPERATIONS.md`, `ops/compose-safe`, `tests/test_compose_safe.py`, `ops/provenance/drift_check.py`, `deploy/DEPLOYED.json`, `deploy/VERSION_BOUNDARY.md`.
  - `CLAUDE.md` gained three lines at `a03efdd`. Its L39-L48 here are L36-L45 at `46578aa`; for example, the learner rule is L44 here and L41 in the pack.
- **Redaction.**
  - No value is reproduced from `.env` or from Compose variables that could hold a credential.
  - Environment variables are named only when they are non-secret flags.
  - No `docker compose config` output was produced.

## 2. Findings

| ID | Finding | Citation | Class |
|---|---|---|---|
| LB-01 | **Exactly two services build from the working tree**: `optimizer` (`build:` at L186-189) and `continuous_learner` (`build:` at L213-216). Both use `context: .`, and both take the shared `x-build-args` anchor, whose `BUILD_REVISION` defaults to `unknown` (L20-22). | `docker-compose.yml:L20-22, L183-191, L211-219 @ a03efdd` | SOURCE_VERIFIED |
| LB-02 | **The five running services never build.** `scanner`, `analyzer`, `signal_engine`, `trade_tracker` and `telegram` each declare `image:` plus `pull_policy: never`, and none has `build:`. | `docker-compose.yml:L37-40, L68-71, L106-109, L147-150, L247-250 @ a03efdd` | SOURCE_VERIFIED |
| LB-03 | **On the host, `context: .` resolves to the production checkout.** That checkout is a stale branch at `63da7d3`, has uncommitted edits, and has no `deploy/` or `ops/` directory. The audit found that only the learner would build from it. The optimizer would too if it were targeted, but its profile is `disabled` and it has no container (LB-11). | RT-01 to RT-05, RT-07 (`REP:L244-250 @ 5d977f2`); ARC-19 (`REP:L215`); LRN-03 (`REP:L773`) | RUNTIME_VERIFIED; SOURCE_VERIFIED |
| LB-04 | **The learner image on the host was built locally from a dirty tree.** It is `trading-signal-bot-continuous_learner`, Id `d1aa69bde63f`, labelled `c4cae2b-dirty`. Its container exited (143) on 2026-08-17 and was still stopped at the 2026-10-31 audit and addendum reads. | RT-09 (`REP:L255-266`); RT-15 (`REP:L291`); ADD:L60 @ 5d977f2; `deploy/DEPLOYED.json:L125-150 @ a03efdd` | RUNTIME_VERIFIED; DOCUMENTED_ONLY |
| LB-05 | **The learner has three start paths, and pinning closes only part of the first.** (a) A Compose command naming the service (`up`, `run`, `start`) runs it, with or without `--profile`. Without `--no-build`, Compose builds the image when it is absent; with `--no-build`, it reuses the local image of LB-04. (b) Starting the existing stopped container runs its original image, whatever the Compose file then says. (c) An `exec` into the running `signal_engine` can run the learner, because the `signal_engine` Dockerfile copies the learner and rollback scripts into that image. | (a) ARC-19 (`REP:L215`); `docs/ops/COMPOSE_OPERATIONS.md:L130-133 @ a03efdd`. (b) RT-09; `COMPOSE_OPERATIONS.md:L130-133`. (c) `signal_engine/Dockerfile:L20-23 @ ea8ae4f` (same blob at `a03efdd`); ARC-20 (`REP:L216`); `deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json:L929-934 @ a03efdd` | (a) SOURCE_VERIFIED for the rules, INFERRED for Compose build behaviour. (b) INFERRED. (c) SOURCE_VERIFIED for the Dockerfile, DOCUMENTED_ONLY for the image (RT-17: image contents not hashed) |
| LB-06 | **The learner restarts unless manually stopped.** Its restart policy is `unless-stopped` (L219). Whether it stays stopped therefore depends on the manual-stop flag, the `learner` profile and the operating procedure. | `docker-compose.yml:L219 @ a03efdd`; RT-11, RT-12 (`REP:L271-272`) | SOURCE_VERIFIED; RUNTIME_VERIFIED; INFERRED |
| LB-07 | **Learned gates are not tied to a strategy version.** The learner labels its rows with `config.APP_VERSION`, and deletes stale throttled cells only when it runs. The runtime query selects every row with `n >= MIN_CELL_N` and `weight <= 0`. It does not filter on `strategy_version`, `updated_at` or run status. | `research/continuous_learner.py:L203-246, L253-272 @ a03efdd` (same blob as `ea8ae4f`); `signal_engine/signal_logic.py:L27-28, L390-394, L740-743, L819-831 @ ea8ae4f`; LRN-18 (`REP:L788`) | SOURCE_VERIFIED |
| LB-08 | **One flag flip would apply throttles immediately and indefinitely.** At the audit, `LEARNING_GATES_ENABLED` was `false`, set from `.env`. `learned_gates` held 18 rows, one of them throttled (`momentum` / `usdtd_flat` / `15m`), all last updated on 2026-08-17. The learner's configured loop is 24 h, not the 12 h code default. Setting the flag to true would make the throttle effective at once, with no expiry while the learner stays stopped, and with no version boundary. | VER-03 (`ADD:L95`); VER-23 (`ADD:L159-163`); VER-14, VER-29 (`ADD:L106, L261-262`); LRN-19 (`REP:L789`); VER-31 item 4 (`ADD:L291`) | RUNTIME_VERIFIED; INFERRED |
| LB-09 | **The reviewed Compose blob does not pin the flag.** `signal_engine` receives it only through `env_file`; its `environment:` block (L115-123) does not set it. A `.env` edit followed by any authorized recreate of `signal_engine` would therefore activate the gates with no Compose diff and no `config --hash` change attributable to the flag. The running process keeps the values it was created with. | `docker-compose.yml:L113-123 @ a03efdd`; `shared/config.py:L100 @ ea8ae4f`; ADD:L84-86, L257 | SOURCE_VERIFIED; INFERRED |
| LB-10 | **The committed draft configuration schema omits the learned-gate keys.** At `a03efdd` it has no entry for `LEARNING_GATES_ENABLED`, `MIN_CELL_N`, `LEARNING_EXPLORATION_RATE` or a digest of the selectable `learned_gates` rows, so a flip would not move `config_hash` under that draft. A parallel WP-A01 revision, uncommitted while this document was written, proposes adding `LEARNING_GATES_ENABLED` as a path-selecting key, with the other learned-gate inputs joining the schema of the version that activates their path. §5 is consistent with that rule; its final form belongs to WP-A01. | `shared/strategy_config_snapshot.py:L213-235 @ a03efdd`; the uncommitted revision is not cited as evidence | SOURCE_VERIFIED; NOT_VERIFIED (revision) |
| LB-11 | **The optimizer is a Compose service and a code path that writes decision inputs.** The service is under profile `disabled`, builds from the working tree, has no container and is not a DEPLOYED.json service. Its code (`optimizer/main.py`, `tuner.py`, `analyzer.py`) writes `optimizer_settings` and `indicator_weights`. Its last database updates fall on or before 2026-06-19. A default-off kill switch for its tuner exists only on an unmerged branch (`safety/disable-auto-tune` at `3d1857d`, not an ancestor of `a03efdd`). | `docker-compose.yml:L178-208 @ a03efdd`; RT-10 (`REP:L270`); LRN-09 to LRN-12 (`REP:L779-782`); VER-21 (`ADD:L118-132`); `git merge-base --is-ancestor` check | SOURCE_VERIFIED; RUNTIME_VERIFIED |
| LB-12 | **A Compose comment tells the reader to run a forbidden command.** The comment above `optimizer` says that re-enabling means deleting the `profiles` line and then running a single-service `up -d optimizer`, without `--no-build`. On the host, that command would build from the production checkout. The canonical runbook and CLAUDE.md forbid any build from or in that checkout (Class C). | `docker-compose.yml:L181-182 @ a03efdd` versus `docs/ops/COMPOSE_OPERATIONS.md:L147-149 @ a03efdd` and `CLAUDE.md:L43 @ a03efdd` | CONTRADICTORY |
| LB-13 | **`ops/compose-safe` refuses both services, but is not present in production.** The helper refuses `continuous_learner` and `optimizer` for every subcommand and in any position. It refuses `--profile`, drops every `COMPOSE_*` variable from the child environment, and deny-lists `build`, `run`, `exec`, `up` and `--build`. Its tests cover this. No test parses `docker-compose.yml` for `build:` stanzas. The helper is absent from the production checkout. | `ops/compose-safe:L10-12, L49-59, L94-118, L211-222 @ a03efdd`; `tests/test_compose_safe.py:L81-142 @ a03efdd`; RT-05 (`REP:L248`); CON-02 (`REP:L1455`) | SOURCE_VERIFIED; RUNTIME_VERIFIED; CONTRADICTORY |
| LB-14 | **The learner's own render hash cannot be produced on the host under the current rules.** CLAUDE.md forbids targeting `continuous_learner` with any Compose command, and `compose-safe render-hash continuous_learner` is refused. The `config --hash` verification of R9.d3 can therefore cover the file blob and the five running services, but not the learner. | `CLAUDE.md:L44 @ a03efdd`; `tests/test_compose_safe.py:L86-107 @ a03efdd`; R9.d3 in REMEDIATION_REGISTER.md | SOURCE_VERIFIED; INFERRED |
| LB-15 | **Two other tracked Compose files exist.** `docker-compose.yml.bak` defines seven services with `build:`, including `claude_review` (ARC-18). It is historical and handled by R9.g / WP-F06. `p2_forward/compose.yml` has no `build:`; it requires its image through interpolation and sets `restart: "no"`. Neither is the production bot file. That file is `docker-compose.yml`, per DEPLOYED.json. | `docker-compose.yml.bak:L23-201 @ a03efdd`; ARC-18 (`REP:L214`); `p2_forward/compose.yml:L1-9 @ a03efdd`; `deploy/DEPLOYED.json:L2-7 @ a03efdd` | SOURCE_VERIFIED |
| LB-16 | **CON-19 still holds in source.** The learner builds from the working tree, while every running service uses a pinned release image. | CON-19 (`REP:L1472`); LB-01, LB-02 | CONTRADICTORY |

## 3. Services that build from the working tree, and the guard for each

The tracked `docker-compose.yml` has exactly two services with `build:` (LB-01). The five running services are listed for completeness, because the build-policy test (§6.1) must keep them build-free.

| Service | Today (`docker-compose.yml @ a03efdd`) | Guards in place | Residual hazard | Proposed guard | Change class |
|---|---|---|---|---|---|
| `continuous_learner` | `build:` with context `.` and `signal_engine/Dockerfile` (L213-216); profile `learner` (L218); `restart: unless-stopped` (L219); `env_file: .env` (L221-222) | The profile keeps it out of default startup. `ops/compose-safe` refuses it. Starting it is Class B with its own authorization, and the STOP rule applies. Drift check D7 reports SAFETY if it runs (`ops/provenance/drift_check.py:L14, L222-227 @ a03efdd`) | Undeployed code from the production checkout, or the local dirty-built image, could start (LB-03 to LB-05). Learned-gate rows could change with no version boundary (LB-07) | G-L1: pin to a released image with `pull_policy: never` and no `build:` (Diff 1, §4.1). G-L2: optional `restart: "no"` (Diff 2, §4.2). G-L3: build-policy static test (§6.1). G-L4: boundary record before `LEARNING_GATES_ENABLED` is set, plus the guard test (§5, §6.2). G-L5: keep D7, the profile and the `compose-safe` refusal unchanged | G-L1, G-L2: Production/runtime change once installed (WP-G33); the repository edit is development. G-L3, G-L4 tests: Safe development-only correction. G-L4 record: Documentation/design |
| `optimizer` | `build:` with context `.` and `optimizer/Dockerfile` (L186-189); profile `disabled` (L185); `restart: unless-stopped` (L191); the comment at L181-182 gives a forbidden re-enable instruction (LB-12) | The profile keeps it out of default startup. `ops/compose-safe` refuses it. Class C forbids any build from the production checkout. It is absent from DEPLOYED.json, so no deployment record covers it | A single-service `up` naming it would build and run working-tree code that writes `optimizer_settings` and `indicator_weights` every hour (LRN-09). No released optimizer image is recorded in this repository | G-O1: keep the definition (no deletion), and replace the L181-182 comment with a pointer to the runbook (Diff 1, §4.1). G-O2: the build-policy static test pins it as the only allowed `build:` service, under profile `disabled`, refused by `compose-safe` (§6.1). G-O3: no re-enable without a released image, a reviewed Compose PR and a named approval (LB-OD-5). The unmerged kill switch `3d1857d` is a candidate code-level guard for later review, not part of this design | G-O1 comment: Documentation/design inside a Compose PR (no render change, INFERRED). G-O2: Safe development-only correction |
| `scanner`, `analyzer`, `signal_engine`, `trade_tracker`, `telegram` | `image:` plus `pull_policy: never`, no `build:` (LB-02) | Class B canonical form with `--no-build --pull never` (`docs/ops/COMPOSE_OPERATIONS.md:L100-104 @ a03efdd`); never rebuild or retag (`COMPOSE_OPERATIONS.md:L40-48`) | A future edit could add `build:`. `signal_engine` reads `LEARNING_GATES_ENABLED` from `.env` only (LB-09) | G-P1: the build-policy test asserts `image:` plus `pull_policy: never` and no `build:` for each of them (§6.1). G-P2: optional Compose literal `LEARNING_GATES_ENABLED: "false"` on `signal_engine` (Diff 3, §4.3, LB-OD-3) | G-P1: Safe development-only correction. G-P2: Production/runtime change once installed |

**Other Compose files.** They are outside this table (LB-15).
- `docker-compose.yml.bak` is historical. R9.g / WP-F06 marks it, and only a named approval can delete it.
- `p2_forward/compose.yml` belongs to the separate collector project and does not build.

## 4. Proposed `docker-compose.yml` change

These diffs are proposals for the repository. They are not applied here.
- Each one was produced mechanically against blob `d1a4b197`, on a scratch copy outside the repository.
- Each was checked to apply cleanly with `patch`, and each result parses as YAML.
- Compose schema validation was not run, because that needs a `docker compose` invocation, which this task excludes. It is NOT_VERIFIED, and §8 places it in the PR's isolated check.

### 4.1 Diff 1 (required for R9.d): learner pin and optimizer comment

```diff
--- a/docker-compose.yml
+++ b/docker-compose.yml
@@ -180,4 +180,5 @@
   # المحسن كان يعدّل indicator_weights/optimizer_settings حياً كل ساعة — مخالف لبند التجميد.
-  # profiles=["disabled"] يمنع `docker compose up -d` من إعادة تشغيله.
-  # لإعادة تفعيله بعد رفع التجميد: احذف سطر profiles ثم `docker compose up -d optimizer`.
+  # profiles=["disabled"] keeps it out of default startup only; it is NOT an authorization control.
+  # It builds from the working tree: never build or start it on the production host (Class C).
+  # Re-enabling needs a released image, a reviewed Compose PR and a named owner approval (docs/ops/COMPOSE_OPERATIONS.md).
   optimizer:
@@ -212,6 +213,4 @@
     <<: *hardened-runtime
-    build:
-      context: .
-      dockerfile: signal_engine/Dockerfile
-      args: *build-args
+    image: tsb-a561-signal_engine:rel-ea8ae4f-r2   # LB-OD-1 option L1-a: released image, never built from the working tree
+    pull_policy: never
     container_name: trading_continuous_learner
```

- **Effect.** After Diff 1, `optimizer` is the only service with `build:`. The learner can no longer be built by Compose. If it is ever started, by an authorized procedure, it runs a recorded release image.
- **The image value is an owner decision (LB-OD-1).** The diff shows option L1-a, the documented `signal_engine` release image.
  - Why it fits: the learner's current build already uses `signal_engine/Dockerfile` (L215), and that Dockerfile copies `research/continuous_learner.py` and `research/rollback_learned_gates.py` (`signal_engine/Dockerfile:L22-23 @ ea8ae4f`, SOURCE_VERIFIED).
  - What the release record says: the `signal_engine` manifest lists the learner script with git blob `e8a80699`, classified `match` (`deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json:L929-934 @ a03efdd`, DOCUMENTED_ONLY). The same blob is the learner at `ea8ae4f` and at `a03efdd` (SOURCE_VERIFIED).
  - Caveat: the image filesystem was never hashed (RT-17), so whether the image actually contains the script remains DOCUMENTED_ONLY.
  - Under option L1-b, only the `image:` value changes: a dedicated learner release tag, recorded in a release record, takes its place.
- **What stays the same.**
  - `container_name`, `profiles: ["learner"]`, `env_file`, `environment`, `command`, networks, healthcheck and limits are untouched. The Compose `command` overrides the image's default command, which starts `signal_engine` (`signal_engine/Dockerfile:L35 @ ea8ae4f`, INFERRED from Compose semantics).
  - The `x-build-args` anchor stays, because `optimizer` still uses it.
- **No render change for the optimizer.** The comment hunk changes only comment lines, so the optimizer's rendered configuration and render hash should not change (INFERRED; comments are not part of the Compose model).

### 4.2 Diff 2 (optional, LB-OD-2): learner restart policy

This diff applies on top of Diff 1.

```diff
--- a/docker-compose.yml
+++ b/docker-compose.yml
@@ -217,3 +217,3 @@
     profiles: ["learner"]   # excluded from default startup only; NOT an authorization control — never target directly (docs/ops/COMPOSE_OPERATIONS.md)
-    restart: unless-stopped
+    restart: "no"   # LB-OD-2: never auto-restart; staying stopped no longer depends on the manual-stop flag
     logging: *default-logging
```

- **Trade-off.**
  - For: it removes the dependency on the manual-stop flag that RT-12 identified, so a daemon restart could never bring back a learner that someone started by mistake.
  - Against: an authorized learner run would not restart after a crash of its shell loop. The loop itself already tolerates a failed run (`|| true`, L231).
- It takes effect only for a container created after the install. The existing stopped container keeps its old policy (INFERRED).

### 4.3 Diff 3 (optional, LB-OD-3; separate PR and separate install): flag literal on `signal_engine`

This diff applies on `d1a4b197`, and also on top of Diff 1.

```diff
--- a/docker-compose.yml
+++ b/docker-compose.yml
@@ -117,2 +117,3 @@
       SERVICE_NAME: signal_engine
+      LEARNING_GATES_ENABLED: "false"   # LB-OD-3: pinned in the reviewed blob; enabling needs a boundary record (docs/ops/LEARNER_BUILD_HAZARD_DESIGN.md)
       HEALTH_MAX_AGE_SECONDS: "180"
```

- **Effect.** A value in `environment:` takes precedence over `env_file` (INFERRED; the addendum's source model, `ADD:L84-86`, distinguishes the two). The flag would then be fixed by the reviewed Compose blob.
  - It could change only through a Compose PR, a `config --hash` change and a boundary record (§5).
  - It would no longer change silently through a `.env` edit (LB-09).
  - The value `"false"` reproduces the runtime-verified state (VER-03). It chooses nothing new.
- **Costs.**
  - It changes the `signal_engine` render, so `config --hash signal_engine` would differ from the running container's label until `signal_engine` is recreated. Drift check D4 would report DRIFT in the meantime.
  - A recreate is its own Class B operation on a running Paper service. For that reason Diff 3 must never be bundled with Diff 1.

## 5. Version-boundary record required before `LEARNING_GATES_ENABLED` can be set

### 5.1 Why a boundary is required
- **The flag changes decisions.** When it is true, `signal_engine` drops every candidate whose (trade type, timeframe) cell is throttled for the current macro state, unless the hourly exploration hash selects it (`signal_engine/signal_logic.py:L390-394, L740-743, L819-831 @ ea8ae4f`, SOURCE_VERIFIED).
  - That alters `Candidate` and `RejectionRecord` outcomes, so it is a MAJOR step and a strategy-version boundary under SE-38 ([STRATEGY_AND_EXECUTION_CONTRACT.md](../design/remediation-design-pack-20261101/STRATEGY_AND_EXECUTION_CONTRACT.md), SE-38).
  - Flipping it without a boundary is an "unversioned strategy change", a stop condition (`docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md:L57 @ a03efdd`).
- **The decision input is the content of `learned_gates`, not the flag alone.** The rows carry no version filter and do not expire while the learner is stopped (LB-07, LB-08).
  - The boundary must therefore fix both the flag value and a digest of the rows that the runtime query can select.
- **Classes.**
  - Enabling the flag is a Strategy-version-changing correction, delivered by a Production/runtime change (a recreate of `signal_engine`).
  - Writing the record is Documentation/design.
  - The pack's decision table has no row for this activation (§11).

### 5.2 Rule
- `LEARNING_GATES_ENABLED` may be set to `true` for a Paper service only after the boundary record described below exists and has been approved.
- The record is an append-only entry in [VERSION_BOUNDARY.md](../../deploy/VERSION_BOUNDARY.md), using the strategy-boundary template of SE-36. WP-A01 is preparing that template as `deploy/VERSION_BOUNDARY_TEMPLATE.md`; it is not on this branch yet, so it is not linked.
- The entry must cite the named owner approval for this specific activation.
- Until then:
  - a configuration presenting `true` fails the guard of §6.2;
  - every Class B step on `signal_engine` treats an unexpected `true` as a STOP condition (`CLAUDE.md:L48 @ a03efdd`).
- The record does **not** authorize starting the learner. Learner activation is a separate decision, excluded by the integrated-development decision (L27).

### 5.3 Fields

The SE-36 fields come first, followed by the learner-specific fields.

| Field | Content | Source of the value |
|---|---|---|
| `boundary_id` | New identifier, for example `VB-YYYY-MM-DD-NN` | written at activation |
| `strategy_id`, `version_before`, `version_after` | Every identity whose candidates the gates can drop. Learned gates key on trade type, so both `momentum_breakout` and `reversion_rsi_bb` are affected; each takes a MAJOR step (SE-38) | WP-A01 identities |
| `source_hash`, `config_hash`, `contract_hash` before and after | `config_hash_after` must cover `LEARNING_GATES_ENABLED`, `MIN_CELL_N`, `LEARNING_EXPLORATION_RATE` and `learned_gates_digest` (LB-10) | `shared/strategy_identity.py` manifests |
| `learned_gates_digest` | sha256 over the canonical JSON of every `learned_gates` row (trade type, macro state, timeframe, `n`, weight, `strategy_version`, `learning_run_id`, `updated_at`), plus the row count and the number of rows the runtime predicate selects at the recorded `MIN_CELL_N`. Hashing every row, not only the selectable ones, catches a later change to `n` or weight that would make a row selectable | an owner-approved, read-only database read. The audit read configuration metadata only, not `n` (`ADD:L159-163, L253`) |
| `min_cell_n`, `exploration_rate` | Effective values. The legacy code defaults are 10 and 0.10 (`shared/config.py:L85, L99 @ ea8ae4f`); the runtime exploration rate is 0.10 (VER-15, `ADD:L107`). The record reproduces values; it chooses none | configuration snapshot |
| `stale_throttle_policy` | How rows last written on 2026-08-17 are treated, given that expiry exists only in the stopped learner (LRN-19). Options are in LB-OD-6 | owner decision |
| `learner_state` | Learner container not running (D7 MATCH), its image identity, and the last `learning_run_id` | drift check D7; DEPLOYED.json |
| `fill_model_id`, `cost_model_id` | As SE-36. They are unchanged by this flag, and the record must say so | configuration snapshot |
| `activation_utc_minute`, admission authority | Minute of the `signal_engine` recreate that loads the flag; the authority is `signal_engine` (selection) | Class B evidence |
| `images` | `signal_engine` image identity before and after | Class B evidence |
| `approval` | Reference to the named owner approval | owner |
| `rule` | No pooling across the boundary; no retroactive attribution; no re-fire of bars that closed before the activation minute (SE-36) | SE-36 text |

## 6. Static guard design (WP-F03)

- WP-F03 owns these tests, and this section specifies them. They read tracked files only and use synthetic fixtures. They need no Docker, network or database, and no new dependency.
- Test 1 (runbook pin parity) belongs to WP-F01 and WP-F03 and is not specified here.

### 6.1 Test 2: build policy (extends `tests/test_compose_safe.py`)

**Parser.**
- Use the standard library only. Extend the pattern of `compose_images()` (`ops/provenance/parity_inventory.py:L68-79 @ a03efdd`): a two-space service key under `services:`, then four-space attributes.
- Read `build:`, `image:`, `pull_policy:`, `profiles:` and `restart:`, ignoring inline comments.
- Where PyYAML is importable, cross-check the result with `pytest.importorskip("yaml")`, as `tests/test_ci_workflows.py:L111-120 @ a03efdd` does.
- Load `ops/compose-safe` with the file's existing `SourceFileLoader` helper (`tests/test_compose_safe.py:L18-25 @ a03efdd`), so the tests use its live `SERVICES` and `OWNER_ONLY_SERVICES`.

**State switch.** One module constant, `LEARNER_COMPOSE_STATE`, records the reviewed learner state: `"build_refused"` today, and `"pinned"` from the Compose PR onwards. The PR that applies Diff 1 must change the constant in the same commit. This keeps the test green before and after the change, makes the switch reviewable, and fails on any unreviewed drift.

| Case | Assertion | Today | After Diff 1 |
|---|---|---|---|
| T2-1 | The set of services with `build:` equals the expected set | `{"optimizer", "continuous_learner"}` | `{"optimizer"}` |
| T2-2 | Every `build:` service has non-empty `profiles`, all inside the allow-list | allow-list `{"disabled", "learner"}` | `{"disabled"}` |
| T2-3 | Every `build:` service is in `OWNER_ONLY_SERVICES`, and no `SERVICES` entry has `build:` | pass | pass |
| T2-4 | Every service without `build:` has `image:` and `pull_policy: never`, and every `SERVICES` entry exists in the Compose file | pass | pass; the learner is now included |
| T2-5 | When the state is `"pinned"`, the learner's `image:` equals an image reference recorded in a committed release record (for L1-a, `deploy/a561-rel-ea8ae4f/IMAGES.md:L17 @ a03efdd`), and its restart policy equals the LB-OD-2 outcome | skipped | pass |
| T2-6 | No comment line in the Compose file contains a `docker compose` lifecycle command (`up`, `start`, `run`, `build`) without `--no-build` | lands with the Compose PR (it fails on L181-182 today) | pass |
| T2-7 | `OWNER_ONLY_SERVICES` still contains both `continuous_learner` and `optimizer`, so pinning never removes the refusal | pass | pass |

### 6.2 Test 3: learning-gate boundary guard (`tests/test_learning_gates_boundary_guard.py`, new)

**Function under test.**
- A pure function, `check_learning_gates(config, entries, gates_digest)`. Its inputs are:
  - a non-secret mapping of effective configuration values;
  - the parsed boundary entries;
  - the `learned_gates_digest` of the current rows (§5.3).
- It returns a status in the drift-check vocabulary (`MATCH`, `UNKNOWN`, `SAFETY`; `ops/provenance/drift_check.py:L39 @ a03efdd`) together with its reasons.
- WP-F03 lists only test files, so the function's home is an implementation choice to confirm with WP-F03. One option is a new module under `ops/provenance/`, which leaves existing `ops/` files untouched. The other is an addition to the WP2 file `shared/strategy_version_boundary.py`.
- It reads nothing itself.

**Parsing rule.**
- The runtime treats a value as true only when `.lower() == 'true'` (`shared/config.py:L100 @ ea8ae4f`).
- The guard is stricter, so that it fails closed: it accepts only `true` and `false`, in any case. Any other value is `UNKNOWN`, because its intent is ambiguous even though the runtime would read it as false.

| Case | Synthetic input | Expected |
|---|---|---|
| G-1 | flag `false` | `MATCH` |
| G-2 | flag absent (runtime default false) | `MATCH`, reason "default" |
| G-3 | flag `true`, no entry | `SAFETY` |
| G-4 | flag `TRUE`, no entry | `SAFETY` (case-insensitive, as at runtime) |
| G-5 | flag `1`, `yes` or ` true` (leading space) | `UNKNOWN` (fail-closed) |
| G-6 | flag `true`, entry whose `config_hash_after` differs from the presented configuration | `SAFETY` |
| G-7 | flag `true`, entry whose `learned_gates_digest` differs from `gates_digest` (rows rewritten after the record) | `SAFETY` |
| G-8 | flag `true`, entry with `PENDING` hash fields or no approval reference | `SAFETY` |
| G-9 | flag `true`, matching and approved entry | `MATCH` |
| G-10 | flag `false`, but the latest entry declares the gates active | `UNKNOWN` (record and runtime disagree) |

### 6.3 Integration points for later work (none wired by this design)

| Point | Wiring | Behaviour at the default | Proof | Gate |
|---|---|---|---|---|
| `ops/provenance/drift_check.py:L14, L52 @ a03efdd` | a new check beside D8 that reads `LEARNING_GATES_ENABLED` in memory from the container environment, as D8 reads `PAPER_TRADING`, and calls the §6.2 guard | read-only; changes no service | the extended `tests/test_drift_check.py` on synthetic observations | edits an existing `ops/` file: separate owner gate |
| `docs/ops/COMPOSE_OPERATIONS.md:L108-115 @ a03efdd` | add "learned-gate flag as recorded" to the Class B pre-gates for `signal_engine` | documentation | review | runbook edit with independent review (`docs/governance/DEVELOPMENT_FIRST_POLICY.md:L73 @ a03efdd`, as for WP-F01) |
| `docker-compose.yml` | Diffs 1 to 3 | Diff 1 changes only the learner render; Diff 3 changes the `signal_engine` render | §6.1 tests; the PR's isolated validation-only Compose check (§8) | WP-G33 install |

## 7. `ops/compose-safe`, the profile and authorization

| Element | What it does | What it does not do | Citation and class |
|---|---|---|---|
| `profiles: ["learner"]` and `profiles: ["disabled"]` | Keep the service out of normal default Compose startup, which protects against accidental start | A Compose command that names the service still runs it, with or without `--profile`. Adding `--profile learner` is not an approval either. **The profile is not an authorization boundary** | `CLAUDE.md:L44 @ a03efdd`; `docs/ops/COMPOSE_OPERATIONS.md:L127-133, L159-162 @ a03efdd`; `docker-compose.yml:L218 @ a03efdd`; DOCUMENTED_ONLY and SOURCE_VERIFIED |
| `ops/compose-safe` | A read-only, allow-listed helper. It refuses `continuous_learner` and `optimizer` in every position, refuses `--profile` and mutation words, strips `COMPOSE_*` variables, and never prints a full render | It cannot stop a raw `docker compose` command. It is absent from the production checkout (LB-13). It refuses to compute the learner's render hash (LB-14) | `ops/compose-safe:L2-12, L49-59, L94-118, L211-222 @ a03efdd`; SOURCE_VERIFIED; RT-05 RUNTIME_VERIFIED |
| Learner pin (Diff 1) | Ensures that anything that runs under the `continuous_learner` name is a recorded release image and is never a working-tree build | It authorizes nothing. A pinned learner can still be started by direct targeting, and it can still write `learned_gates` | this design; INFERRED |
| Drift check D7 | Reports SAFETY when the learner container is running | It does not see a learner run through `exec` inside `signal_engine` (LB-05 c). It does not check the learner's image | `ops/provenance/drift_check.py:L222-227 @ a03efdd`; SOURCE_VERIFIED |
| **Authorization boundary** | All of: explicit owner approval of the specific operation; the Class B procedure; the canonical runbook; the `compose-safe` refusal as a defence layer; and the absolute STOP rule. Learner activation also needs its own separate authorization, which the integrated-development decision does not give | — | `CLAUDE.md:L40-44, L48 @ a03efdd`; `docs/ops/COMPOSE_OPERATIONS.md:L91-140 @ a03efdd`; integrated-development decision L18, L27; DOCUMENTED_ONLY |

None of the guards in §3 widens what an operator may do. Each one narrows what an unauthorized or mistaken command could cause.

## 8. Path from repository change to host install (WP-G33)

The steps run in this order. No step implies the next one.

1. **Development (authorized now).**
   - A PR with Diff 1, and Diff 2 if the owner chose it under LB-OD-2.
   - In the same PR: the `LEARNER_COMPOSE_STATE` switch and the §6.1 tests.
   - The Compose model is validated only in an isolated, disposable development environment, with synthetic non-secret values. This step is for the main agent only; agents never run Docker.
   - Diff 3, if chosen under LB-OD-3, goes in a separate PR.
2. **Review and merge.** Owner review, plus the independent review required for production-operation definitions (`docs/governance/DEVELOPMENT_FIRST_POLICY.md:L73 @ a03efdd`). Merging deploys nothing.
3. **Named approval for the install** (WP-G33). It names the file, the expected blob and the expected render hashes.
4. **Install (Class B, one file).**
   - Capture before: the identities of every bot container, and the `config --hash` of the five running services.
   - Replace the host file.
   - Verify that the file's blob equals the merged blob.
   - Verify that the five render hashes are unchanged. This is the expected result, because Diff 1 and Diff 2 touch only the learner and comments, and a render hash covers one service definition (INFERRED).
   - Verify that drift check D7 still reports the learner not running.
   - The learner's own render hash is recorded as not run, with LB-14 as the reason.
   - No container is created, recreated, started or removed.
5. **Record.** A reviewed commit updates the Compose `git_blob` in `deploy/DEPLOYED.json` (L4). The learner entry (L125-150) keeps `expected_state` `not_running`.
   - The existing stopped container keeps its old image and its old configuration label. This is expected, and the record says so explicitly (LB-04, LB-05 b).

**STOP points (absolute STOP rule, `CLAUDE.md:L48 @ a03efdd`).** Each of these means stop and return to the owner:
- a render hash of a running service changes;
- the installed blob differs from the merged blob;
- D7 is not MATCH;
- a container identity changes;
- `LEARNING_GATES_ENABLED` is found true without a §5 record.

**Diff 3.** It has its own install, followed by a separately approved Class B recreate of `signal_engine`. Until that recreate, D4 reports DRIFT for `signal_engine`. That is not a STOP only if the approved plan names it in advance as the expected state.

## 9. Deletion: nothing without a named approval

This design deletes nothing and requests no deletion. Each of the following would need its own named approval, and none is requested:

| Object | Why someone might remove it | Consequence to weigh |
|---|---|---|
| `optimizer` service definition (option O2) | it builds from the working tree, and nothing deploys it | It removes the only Compose record of how the optimizer ran (LRN-09 to LRN-12). Running Compose with an orphan-removal option is Class C anyway |
| `continuous_learner` service definition (option L2) | it removes every Compose start path | The existing container becomes an orphan. Drift check D7 and DEPLOYED.json rely on the service and container names (`deploy/DEPLOYED.json:L33, L125-130 @ a03efdd`) |
| The stopped container `trading_continuous_learner` and the image `trading-signal-bot-continuous_learner` (LB-OD-4) | they are the remaining way to start the dirty-built learner (LB-05 b) | Removal destroys the only artefacts of the learner's last run (labelled `c4cae2b-dirty`, RT-15). They may be evidence for the checkout decision (R9.b, WP-G32) |
| `docker-compose.yml.bak` | it still defines `claude_review` and builds from the tree (ARC-18) | It is handled by R9.g / WP-F06 as a dated historical note. Its deletion has no proposed approval |
| `learned_gates` rows | they hold a non-expiring throttle (LB-08) | This is a production database write, outside this design. Options are in LB-OD-6 |

## 10. Owner decisions

These are options with their trade-offs; none is chosen here. Defaults state what holds until a decision is made.

| ID | Question | Options and trade-offs | Default until decided |
|---|---|---|---|
| LB-OD-1 | Which image does the learner pin to? | **L1-a:** the `signal_engine` release image (Diff 1). It needs no new build, and its manifest records the learner script (DOCUMENTED_ONLY). It couples the learner to the `signal_engine` release, so every later `signal_engine` release needs an explicit decision on whether the learner follows. **L1-b:** a dedicated learner release image, built in an isolated clone with a unique tag (`docs/ops/COMPOSE_OPERATIONS.md:L164-167 @ a03efdd`). It gets separate provenance, but needs a release record and a review. **L2:** remove the learner service (a deletion; §9) | Compose unchanged; the learner stays stopped |
| LB-OD-2 | Learner restart policy | Keep `unless-stopped`, or change it to `"no"` (Diff 2; §4.2 trade-off) | `unless-stopped` |
| LB-OD-3 | Pin `LEARNING_GATES_ENABLED` in Compose for `signal_engine`? | **Yes (Diff 3):** the flag can then change only through a reviewed blob, but a `signal_engine` recreate is needed. **No:** rely on the §6.2 guard and the Class B pre-gate | No |
| LB-OD-4 | The stopped learner container and its locally built image | Keep them (they are evidence; they remain a start path guarded only by procedure and D7), or remove them under a named approval | Keep |
| LB-OD-5 | The optimizer | **O1:** keep the definition with guards G-O1 and G-O2 (no deletion). **O2:** remove the service (§9). **O3:** pin it to a released image. No such image is recorded, so O3 first needs a release. The kill-switch branch `3d1857d` could be reviewed as a code-level guard under any of these options | O1 is in effect today, minus the comment correction |
| LB-OD-6 | Throttles last written on 2026-08-17 if the gates are ever enabled | (a) Run the learner under a separate authorization, so that its own expiry applies. (b) A reviewed, one-off expiry procedure, which is a production database write. (c) Accept non-expiring rows, with a declared review date in the §5 record. Each option changes what the record's `learned_gates_digest` captures | Gates off (VER-03) |

## 11. Not verified, gaps and hand-offs

**NOT VERIFIED.**
- Image filesystem contents of `tsb-a561-signal_engine:rel-ea8ae4f-r2`, including the learner script (RT-17).
- Compose behaviour, which this task did not run. It covers:
  - building when an image is absent;
  - `start` of an existing container;
  - precedence of `environment:` over `env_file`;
  - schema validity of Diffs 1 to 3.
- Whether the single throttled cell meets `n >= MIN_CELL_N`; the audit did not read `n` (`ADD:L253`).
- Whether any released optimizer image exists on the host.
- Whether the learner was ever run through `exec` inside `signal_engine`. Detecting that would need an approved read of `learning_runs`.

**Gaps.**
- The pack's decision table ([DECISIONS_AND_GATES.md](../design/remediation-design-pack-20261101/DECISIONS_AND_GATES.md)) has no row for enabling `LEARNING_GATES_ENABLED`; this was checked at `9588f45`. §5 and LB-OD-6 are the candidate content for such a row, which a later pack edit can add.
- No DEVIATION ALERT. Nothing in this design conflicts with the charter.

**Hand-offs.**

| To | What |
|---|---|
| WP-F03 | Implement §6.1 and §6.2, and confirm where the guard function lives |
| WP-A01 | The activation-version schema must include the §5.3 `config_hash` keys and `learned_gates_digest` (LB-10) |
| WP-F01 | The runbook pre-gate line of §6.3, under independent review |
| WP-G33 | The install of §8 |
| WP-G32 / R9.b | Consider LB-OD-4 together with the production-checkout decision |
