# Single-host development and production safety / حوكمة الخادم المشترك
**Owner-confirmed: 2026-09-27.** Development and production share **one physical/virtual host**. Isolated Git worktrees and disposable containers/databases are logical isolation **on that same host**, NOT a separate staging environment. Never claim an independent staging/UAT environment exists.

## Non-negotiable boundaries
1. Read-only audits may inspect Git, manifests, image metadata and installed package versions; never upgrade global Python, host OS, Docker, deployed image or live container during an audit. Never display or store credentials.
2. All code changes belong in a separate Git branch and worktree. Do not change the production checkout, bind-mounted source, live compose files, secrets, production database or running containers.
3. Before any disposable test infrastructure, record baseline host resources and existing Docker container names, networks, ports and mounts. Use unique names/project prefixes, a private network, nonpublished ports, a disposable DB volume and **synthetic/schema-only** test data. Never connect tests to the production DB, production exchange accounts or real Telegram recipients.
4. Apply explicit CPU/memory/PID and storage limits to disposable test workloads. Check host headroom and avoid resource-heavy builds/tests when headroom is inadequate. Do not restart or interrupt existing production services. If isolation or safety cannot be established, stop and ask owner rather than improvise.
5. Use nonsecret scratch environment files; never reuse production .env or copy production DB rows, sealed holdout or credentials. No bare `docker compose up -d` (could restart the deliberately stopped learner); only explicitly scoped commands **after owner approval**.
6. A separate branch, Docker network or temporary PostgreSQL instance on this host **does not remove correlated host failure risk**. Backups and recovery must account for single-host loss; offsite backup remains an owner-deferred decision, not a completed control.
7. No merge/deploy/production DB migrations, service recreation, paper restart or live activation without a specific owner-approved release plan. Before any deployment: independent review, reproducible image build, known-good image IDs, verified backup/restore path, resource impact, one-service-at-a-time rollout, monitoring and tested rollback. If safe same-host image build cannot be demonstrated, propose an external isolated build/test environment for separate approval.

## Post-P1 audit constraint
For dependency currency review, **read-only only** on this host: inspect manifests and current installed versions, verify latest stable upstream versions and publish a dated matrix/proposal. Do not start disposable databases, rebuild images, run tests that compete with production, install packages or modify production. Request separate approval for an isolated upgrade experiment with explicit resource limits.

## Status
P1 branch `feature/forward-instrumentation@23dea904a852` is reported built/tested, but not merged or deployed. PAPER_HALTED, B3 unchanged. Production and development remain on the same host.
