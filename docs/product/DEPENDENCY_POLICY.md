# Dependency & Runtime Currency Policy / سياسة تحديث المكتبات
**Owner-approved direction: 2026-09-27.** Applies to all subsequent development, beginning with a dependency audit **after Claude returns the P1 instrumentation report**. This document does not authorize upgrades in the active P1 branch, deployment, paper restart or live trading.

## Principle
Prefer the latest **stable, supported and security-maintained** compatible releases **as of the actual review date**, not merely the numerically newest versions. Check official release notes, Python/package metadata, upstream compatibility and vulnerability advisories at review time. Never invent a version number or assume that today's latest will still be latest later. No alpha, beta, RC, nightly or abandoned packages without an explicit documented exception.

## Required dependency inventory
Inventory every direct/transitive dependency and runtime for Python services, Docker base images, PostgreSQL, OS/ARM64, CCXT/exchange clients, Telegram, data/ML libraries and web/UI dependencies when introduced. Record:
- package, current version, latest stable version and official release date/source;
- Python 3.12 and aarch64/Linux compatibility (wheel or source build), license, supported release/EOL and known CVEs;
- API breaking changes, reproducibility/lockfile status, upstream advisories and actual use in each service;
- compatibility with production/deployed image hashes, B3 and historical replay contracts.

## Upgrade sequence
1. **After P1 report**: read Claude's actual changed files, dependency manifests and test results; inspect deployed runtime read-only. Publish a dated inventory and upgrade proposal; do not edit the running bot.
2. Classify: urgent security fixes; safe patch/minor; major or behavior-changing; unnecessary/retired. Security issues may require separately approved urgent mitigation, not a silent blanket upgrade.
3. Create a **separate isolated dependency-upgrade branch/PR**. Pin direct and transitive versions via reproducible lockfiles and image digests where practical; retain an SBOM and provenance.
4. Test in isolated ARM64-equivalent environment: imports/build, unit/integration, DB migrations in disposable DB, B3 risk tests, exchange client mocks, Telegram mocks, replay and before/after strategy decision parity. Check indicator numerical drift, candle timestamps, CCXT symbol/precision/order semantics, fill/stop/fee/slippage behavior, SQL-driver semantics and ML reproducibility.
5. Review runtime CPU/RAM/latency, vulnerability scan, changelog, risk, rollback and pinned image hashes. Require explicit owner approval before merging/deploying; deploy one service at a time with verified backups and no learner restart.
6. Recheck upstream latest stable releases **again at merge/deployment**, since a report may become stale. Maintain a regular future audit cadence as a proposed operational task, not an automatic updater.

## Invariants
- **PAPER_TRADING HALTED**, PAPER_ONLY, LIVE FORBIDDEN; no real orders or funded exchange credentials.
- No silent upgrades of indicators, TA-Lib/numpy/pandas, CCXT or order/risk logic that alter strategy decisions. A behavior-changing upgrade requires its own experiment, contract hash/version, acceptance tests and owner approval.
- Keep ML research environments reproducible and separate from frozen strategy runtime; never let a model/library upgrade silently change a production decision.
- Security and maintenance matter, but the latest major version is **not** mandatory when unsupported on ARM64, incompatible with the deployed Python runtime, or fails parity.
- Record every dependency change with current→target version, official release source/date, rationale, test evidence and rollback.

## Deliverable after P1
A dated `DEPENDENCY_AUDIT_YYYY-MM-DD.md` and a proposed version matrix. Only implement changes after scope and owner approval. Cross-link any resulting issue/PR in the Decision Log.
