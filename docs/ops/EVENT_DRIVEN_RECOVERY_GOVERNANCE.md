# R1.3 — Event-driven recovery and development-integrated drift governance

**Status: proposed policy, documentation only.** This document does not authorize production installation, cron changes, backup execution, deletion, database access, external transfers, or deployment. It becomes governing project policy only after review and merge. Any production action still requires a separate, operation-specific owner approval.

> **Dated note (2026-10-20):** merged into `main` by PR #46 (2026-10-18), so it **governs**. The §4 transition has not been executed: the p1bg v1 cron is still installed and failing. `trading_signals` is additionally dumped nightly by the xsch backup (local restic, another project). Ongoing data protection between releases is proposed in `docs/ops/BACKUP_MODEL_RD.md`.

## 1. Owner decisions (2026-10-18)

1. **Bot-owned recovery backups are event-driven, not periodic.** Create a new approved recovery set for each owner-authorized update/recreate/rollback that changes a bot container's deployed state. Routine source commits, CI, tests, research outcomes, and an unchanged running container do not trigger a recovery set.
2. **Keep one current certified recovery set and its immediately preceding certified set during replacement.** After the replacement set has been fully certified, retire the previous set only through an explicitly approved, audited deletion step. At steady state, target one certified current set; do not delete historical, sealed, scientific, regulatory, or independently protected evidence under this policy.
3. **Drift detection is a development/release governance gate**, not an independent monitoring service. Do not schedule drift checks, alerts, or a new cron/systemd job without a new owner decision.

## 2. Recovery-set lifecycle

An authorized container update must have a reviewed deployment/rollback plan and a known, verified prior recovery point. Before mutation, inventory the current certified set and validate its checksums and rollback dependencies. If the existing point is inadequate, **STOP** and request explicit approval for a pre-change recovery action; do not proceed assuming a post-change backup can replace rollback protection.

After the authorized update passes all Class B post-gates, assemble a **candidate** recovery set for the affected bot release, including as applicable:

- Immutable deployed container image archive(s) with checksums and image IDs, including collector when affected; source/release provenance and the observed deployment manifest.
- A consistent, authorized `trading_signals` DB dump and bot-owned evidence snapshot if those data are necessary to restore the updated release; explicitly document the DB/evidence consistency skew and any exclusions.
- Versioned deployment/rollback instructions, Compose blob/config hashes, dependency and external shared-service references.
- References to secrets held separately in an owner-controlled store; **never** embed secrets in Git or recovery archives.

Certification requires complete hashes, readable artifacts, structural restore validation in isolation where applicable, an inventory and a recorded restore path, no prohibited scientific data access, and an owner-reviewed success record. A checksum or `pg_restore --list` alone is **not** proof of full restore. A missing collector image archive, missing required DB/evidence, or unverified recovery dependency prevents certification. Any off-host copy or isolated restore test requires its own approval.

**Promotion sequence:** existing certified set remains protected → create candidate → verify all required parts → certify and promote new set → independently verify its retention and restoration evidence → propose retirement of the prior set → obtain separate explicit deletion approval → delete only the named, bot-owned superseded set and record the result. Failed or partial candidates never displace the prior set. Never remove the only restorable set. No deletion by wildcard, age-only policy, or unreviewed automatic retention.

This policy does **not** authorize touching shared-postgres backups, other projects' databases, collector sealed research datasets, protected evidence, or historical release/rollback archives outside an approved named scope. A bot-only recovery set must not be confused with whole-host disaster recovery. **Risk accepted for proposal:** data and changes between authorized container updates may be lost; no continuous or scheduled bot-owned recovery point is promised.

## 3. Drift gates embedded in the development lifecycle

Use `ops/provenance/drift_check.py` only as an **on-demand, read-only** gate, with `deploy/DEPLOYED.json` recording observed runtime rather than desired HEAD:

| Gate | Requirement |
| --- | --- |
| Task start / environment discovery | Run metadata check where host access is available; otherwise record UNKNOWN and the access limitation. Explain pre-existing drift. |
| Before PR merge | Confirm whether the change affects runtime/Compose/host definitions; record relevant drift results or why the runtime gate is not applicable to a docs-only change. No production rollout implied by merge. |
| Before each authorized container update | Run metadata check and a targeted or deep image check when the deployment risk warrants it. Any SAFETY, DRIFT, UNKNOWN or stale baseline requires explicit disposition before mutation. |
| After authorized update/rollback | Verify runtime identities, safety guards, and deployed content; update `DEPLOYED.json` with **observed** facts through a reviewed PR, never to mask unexpected drift. |
| Handover | Record check time, scope (FULL/METADATA_ONLY/INCOMPLETE), exit code, baseline SHA, exceptions and approvals. |

`MATCH` applies only to the executed scope; metadata MATCH does not imply image-content verification or clean-build reproducibility. Never run automatic remediation. Preserve `PAPER_TRADING=true`, the stopped learner, protected evidence, and the separate approval for production DB reads. Development may proceed safely without host access, but it must not claim runtime verification or approve production deployment on UNKNOWN evidence.

## 4. Migration from the existing nightly backup

The existing `ops/tsb-p1bg` nightly cron has been reported failing since 2026-10-10. **This policy change does not disable it.** The current script, cron, existing sealed sets, preserved copies, incomplete sets, and A56 artifacts remain untouched until an independent inventory and a separately approved, precisely scoped transition plan. The transition must identify the bot-only cron line, preserve all unrelated shared-postgres/collector backups, determine which historical sets are protected, and document the loss-of-recovery-point risk. No blanket cron editing, backup deletion, or unapproved retention automation.

## 5. Approval matrix

| Action | Authority |
| --- | --- |
| Documentation-only development, tests, Draft PR | Normal safe development governance |
| Read-only metadata drift inspection | Class A, with secret-safe output |
| Deep image check | Class A only if bounded and resource impact acceptable; stop on unexpected I/O |
| Deploy/recreate/rollback a container | Separate owner approval for that service and gated procedure |
| Backup creation, DB dump, isolated restore, off-host transfer | Separate operation-specific owner approval |
| Disable/change cron or delete any existing backup | Separate explicit owner approval identifying exact target |
| Automatically schedule drift checks or backups | Not authorized under this policy |

**Priority:** this policy supersedes the *proposed* nightly bot-backup schedule and proposed independent hourly/daily drift scheduling in earlier planning documents, but not operational safety controls, immutable evidence rules, or the existing production configuration.
