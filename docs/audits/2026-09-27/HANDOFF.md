# HANDOFF — Trading Signal Bot (2026-09-27, end of post-P1 audits)

## Current production state [confirmed 2026-09-27]
- **Trading:** PAPER_TRADING **HALTED** (`2026-09-11 risk:loss_streak_halt`). PAPER_ONLY; LIVE_TRADING FORBIDDEN; B3 unchanged; holdout sealed. `trading_continuous_learner` is stopped and must stay stopped.
- **Host:** one host (netcup aarch64) for development **and** production; there is no staging.
- **Known-good production baseline:** `deploy/baseline-2026-09-27@3ed49c306ce404359c94ee549dd24b431be2a558`, parent B3 `8bfca778b42fa5c29993d5c57bf1674ae755522f`. Its `DEPLOYED_MANIFEST.json` matches all 7 running image IDs. The proposed tag `prod-baseline-2026-09-27` has **not** been created.
- **Branches:**
  - `develop` `4e3eb0a`; `main` `0a396c2` (default; 44 behind develop; 0 unique).
  - P1 `feature/forward-instrumentation@23dea90`: pushed, **not merged, not deployed**.
  - Governance docs: `docs/market-intelligence-governance-20260927@2ffb44b` (PR #3, draft, GitHub-only).
- **Production folder:** `/home/tradmin/trading-signal-bot`, a dirty checkout of `integration/research-pipeline@63da7d3` with 111 status entries. It includes an uncommitted, unreviewed `analyzer/technical_analyzer.py`. **Do not touch it.**
- **P0 least-privilege DB roles:** designed and tested; deployment deferred (services still use the superuser).

## Audit documents
| Document | Path |
|---|---|
| Dependency audit (matrix, security, P1 readiness, upgrade plan) | `/home/tradmin/backups/tsb-post-p1-audit-20260927/DEPENDENCY_AUDIT_2026-09-27.md` |
| Repository cleanup audit | `/home/tradmin/backups/tsb-post-p1-audit-20260927/REPOSITORY_CLEANUP_AUDIT.md` |
| Raw findings | `/home/tradmin/backups/tsb-post-p1-audit-20260927/work/` |
| P1 report | `/home/tradmin/backups/tsb-p1-instrumentation-20260927/P1_IMPLEMENTATION_REPORT.md` |
| P0 security | `/home/tradmin/backups/tsb-p0-security-20260927/P0_SECURITY_REPORT.md` |
| Execution-bot comparison | `/home/tradmin/backups/tsb-exec-comparison-20260927/COMPARISON_AND_INTEGRATION_REPORT.md` |
| Governance (read first) | GitHub branch `docs/market-intelligence-governance-20260927`: `docs/product/*.md`, `CLAUDE.md` |

## Critical findings
1. **P0 PostgreSQL 16.14** (shared with xsch and wishlist) misses **16.15**: 25 CVEs, several CVSS 8.8.
2. **P0 aiohttp 3.13.5** in 6 containers. **CVE-2026-69244 (HIGH)**; fixed in **3.14.3**.
3. **P0 unreviewed uncommitted analyzer file** in the production folder: a build from it would ship it.
4. **P0 bare `docker compose up -d`** in `setup.sh` and docs would start the learner.
5. **P1 backup gap:** the bundle lacks develop, the baseline, P1, refactor and PR #3. No off-host copy.
6. **P1 no guard on `main`;** the host has a **write** deploy key.
7. **P2 builds are not reproducible:** orphaned base digest, no lockfiles, pip wildcard. Python 3.12.13 < 3.12.14.
8. **P2 develop ≠ production** for 5 of 7 images.

## Unresolved questions
- GitHub plan (branch protection on private repos)?
- Is Colab still writing to the production DB?
- Where should the off-host backup live?
- Merge commit vs fast-forward for develop→main?
- What to do with the analyzer research scripts?
- The remaining 9 PostgreSQL 16.15 CVE IDs (take them from the official notes).

## Recommended next actions (each needs explicit owner approval)
1. Keep the halt; **no builds from the production folder.**
2. Approve fetch, a fresh verified all-refs bundle and an off-host copy decision (A1).
3. Plan the **PostgreSQL 16.15** maintenance window with the xsch and wishlist owners; take a fresh backup; pin by digest (D1).
4. Approve an **aiohttp 3.14.3 + pip 26.2** security branch, tested in an isolated, resource-limited environment (D2, D3).
5. Decide on the refactor file and branch (A5) and fix the bare-compose docs (R2).
6. Create and push the rollback tag `prod-baseline-2026-09-27` (A2).
7. Review PR #3 → develop → `main` (merge commit) → settings → deletion waves (A3–A9).
8. Close the P1 deployment gates G1–G6 and deploy only under an approved release plan.

## Restrictions and pending approvals
- No resume, recover_risk, live trading, learner restart, deploys, migrations, merges, deletions, tags, GitHub settings changes, installs, image builds or container recreation without **specific** owner approval.
- No bare `docker compose up -d`. Never use production `.env`, DB rows, the holdout or credentials in tests. Never print secrets.
- Pending approvals: A1–A12 (REPOSITORY_CLEANUP_AUDIT Part II §10.1); D1–D10 (DEPENDENCY_AUDIT §7); P1 gates G1–G6.
- Pending from earlier sessions: rotate the xsch bearer token that was exposed in a tool output (A4); P0 DB-role deployment deferred; Binance key IP restriction.

## Next safe task for a fresh Claude session
Read `CLAUDE.md` and `docs/product/*.md` on the governance branch, then these two audits. After that, the only safe step **without new approval** is a **read-only** re-verification: `git ls-remote`, running image IDs, the halt row, and upstream latest versions for PostgreSQL and aiohttp. Report any drift since 2026-09-27 and **stop for owner approval**.
