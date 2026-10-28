# Trading Signal Bot — Owner Operating Contract

**Status:** APPROVED by owner, consolidated 2026-10-26.
**Purpose:** Single short entrypoint for Claude Code and reviewers. Read this file at the start of every development, research, release or operations task. This is a decision register, not evidence that runtime changes have already been deployed.

## 1. North star

This project is **R&D / PAPER_ONLY**. The goal is to discover and independently validate an economically robust **net-profitable** crypto strategy, not maximize gross signals, apparent backtest returns or procedural activity. No live-money execution, credentials enabling it, or exchange order placement.

Use conservative standard spot fees: **0.10% per side (0.20% round trip)**, independent of account discounts, plus spread, slippage and other realistic execution costs. Report gross and net results, turnover, drawdown, sample sizes, regimes, uncertainty and failure cases. No assertion of profitability without credible prospective independent evidence.

## 2. Workflow — approved 2026-10-26

- **Continuous Development + PR-on-Demand:** `main` is canonical; use only the minimum necessary temporary branch, preferably no branch for ordinary low-risk changes. No automatic Draft PR per task. Relevant CI, security and regression checks still apply.
- Claude Code implements in source files, validates, **pushes the exact candidate commit to GitHub before deployment**, then (only when authorized) builds and deploys from that same commit; no in-container source patching.
- ChatGPT/reviewers assess GitHub commits, tests, documented runtime checks and divergence. Do not claim server parity from GitHub alone. Report **Saved / Integrated / Deployed / Validated** separately and capture deployed SHA, image digests and post-deploy parity evidence.
- **Automatic deployment** only to proven isolated development/lab environments or verified isolated low-risk components after tests, smoke checks and rollback. A shared server, production Compose project or live Paper service is not an isolated lab.
- Live host container deployment, restart, database mutations and Paper strategy activation require their applicable explicit operational approval. A merged commit is not a deployment authorization.
- Deployment blockers must not freeze independent development, and development blockers must not freeze safely authorized operations. External review is advisory for ordinary low-risk R&D development, not a standing gate.
- Existing branches/PRs are consolidated **incrementally** after inventory and verification that unique work and evidence are preserved. No bulk deletion, force-push, secret exposure or history rewrite.

## 3. Paper economic-loss policy — approved 2026-10-26

- During R&D, a negative P&L, consecutive losses, drawdown or low Profit Factor is an **economic observation** to record, alert on and analyze, not by itself an automatic reason to end simulated prospective trade collection.
- Preserve the full historical loss/trade record, strategy version, signals, time, assumptions, execution costs, and failures. No resetting loss counters, backfilling fabricated fills, changing prior outcomes or silently mixing strategy versions.
- Technical data-integrity and operational safeguards remain fail-closed (bad/stale prices, corrupt or missing data, duplicate events, database failures, uncertain service state, explicit administrative stop). If unsafe to generate reliable Paper trades, continue collecting safe market observations only.
- The owner approved **development and tests** to separate economic loss guards (`loss_streak_halt` / `loss_streak_reduce`) from technical halt guards, **not** immediate `/resume`, a forced halt override, restart, live service deployment or technical-safety bypass. Verify actual state from authoritative evidence first.
- Trade-level stop-loss/risk sizing and trading-strategy changes are separate from the research collector's economic-loss stop policy; do not silently remove position controls.

## 4. Strategy research and scientific separation

- Continue the **A45-G REVISE STRATEGY** work, including signal/entry/exit quality, market regime, risk/reward, turnover, net costs and out-of-sample robustness. The earlier gross PF 0.735 on 2,518 Paper trades is historical review evidence, not a current profitability claim.
- Read the existing strategy roadmap (including PR #91), candidate/hypothesis and statistical accounting work (including PR #94), Paper-monitor/recovery work (#87/#89), and related accepted records. Check whether work is merged or still draft; do not treat PR plans as implemented code.
- Keep exploratory, synthetic engineering tests separate from licensed, explicitly permitted historical-data analysis and **governed confirmatory** tests. Protected/sealed holdouts remain sealed; no unauthorized data reads, peeks, alpha consumption or prospective-window changes.
- A29 Evidence Ladder remains in force with **D1/D2 HOLD** for governed confirmation, up to 365-day prospective horizon, max 3 simultaneous candidates, 20% forward capacity reserved, 5% familywise error control; ENCOURAGING is non-confirmatory. No technical shortcut may silently change these decisions.
- Significant Paper strategy changes create explicit version boundaries and require operational approval for activation; never retroactively attribute prior outcomes to a new version.

## 5. Operational safety and precedence

- Never enable live money; keep `PAPER_TRADING=true`. Keep continuous learner stopped unless separately authorized.
- Production Compose safety is governed by `docs/ops/COMPOSE_OPERATIONS.md`: shared host, one-service-at-a-time restrictions, read-only inspection versus owner-authorized operations. No destructive/bulk Compose commands, protected-evidence deletion, or unauthorized production DB writes.
- Per-release successful backup/rollback policy and protected evidence retention remain active; do not delete historical recovery/evidence without named authorization.
- Read `docs/governance/DEVELOPMENT_FIRST_POLICY.md`, `docs/ops/BRANCH_RELEASE_POLICY.md`, `docs/ops/EVENT_DRIVEN_RECOVERY_GOVERNANCE.md` and relevant strategy/science records as needed.
- **Precedence:** Explicit later owner decision for the same subject > this consolidated contract > older conflicting workflow prose. However, a workflow simplification does **not** implicitly repeal production safety, access restrictions, scientific protection or a required operation-specific approval. If records conflict, identify the exact conflict, follow the narrower safety gate and continue independent permitted work; do not hide the conflict.

## 6. Start/finish checklist

At task start: (1) read this contract and `CLAUDE.md`; (2) check latest `main` and relevant documents/PR status; (3) inspect runtime only when needed and authorized; (4) classify ordinary D0, research, isolated deploy or live-host operation; (5) preserve existing work and evidence.

At task finish: provide an Arabic summary with exact changed file paths, GitHub SHA, test/CI outcome, research significance and cost assumptions when applicable, deployed image digest/actual runtime status if applicable, outstanding safety gates and next independent tasks. **Never state that a documentation approval means code has been implemented or containers resumed.**

## 7. Change control

Add a dated owner-decision entry to this contract whenever the owner revises these rules; update `CLAUDE.md` entrypoint and any directly conflicting policy, rather than distributing instructions through chat alone. New decisions must distinguish development authorization from live operational authorization.

## 8. GitHub Usage and Compute Cost Governance — OWNER DIRECTIVE, permanent, 2026-10-28

Standing owner directive (not a temporary workaround for the 2026-10-27 billing block). Purpose: minimise GitHub
Actions billing and unnecessary CI usage **without** weakening engineering quality, safety or scientific integrity.

1. GitHub remains the source-control and review platform (commits, branches, reviews, integration into `main`).
2. Local or isolated testing is the default: run the tests relevant to a change locally (or in an isolated
   environment) before pushing, and record the result.
3. GitHub Actions runs must be purposeful and cost-conscious: push when a reviewable state is reached, not per edit;
   no re-runs, `workflow_dispatch` runs or empty commits without a stated reason.
4. Avoid duplicate workflows, redundant triggers and unnecessary repeated runs of the same tree.
5. Batch related development changes where practical (one push per coherent batch on the one integration branch).
6. Prefer reproducible, SHA-bound local test evidence: commit SHA, exact command, interpreter and dependency-set
   identity (pinned requirements file hash), pass/fail/skip counts and the kept log path.
7. Integration tests that need PostgreSQL use a **disposable** PostgreSQL environment holding only the schema
   template and synthetic data, destroyed after the run.
8. Never use a production database for development tests (the shared `postgres` container and its databases
   included). Read-only operational evidence queries are operations, not tests, and follow their own approvals.
9. Heavy research, backtesting and scientific compute do not run on GitHub-hosted CI by default; they use the
   governed host runner (`~/ops/research-runner`) and its limits.
10. Never weaken required tests, security controls, protected-data restrictions or deployment gates to reduce cost.
11. If a mandatory gate requires GitHub-hosted CI, propose a formally documented equivalent alternative for owner
    approval instead of silently bypassing it. Until it is approved, the gate stands; a blocked gate is reported and
    the dependent change stays on HOLD (as the Retry Guard did on 2026-10-27).
12. Do not enable paid runners, raise spending limits or introduce new billable services without explicit owner
    approval.

**Relation to existing gates (no silent change).** `docs/ops/BRANCH_RELEASE_POLICY.md` §3 ("CI green, and tests
relevant to the changed component run in CI") and the required checks named in the branch-protection proposal
(PR #90, not merged and not applied) still apply to integration into `main`, and so does the "provided CI is green" condition for direct D0
integration in `docs/governance/DEVELOPMENT_FIRST_POLICY.md`. Its "commit and push small, auditable changes" stays:
commits stay small; rule 5 batches the pushes, not the commits. A local
CI-equivalent evidence standard that could substitute for them is proposed in `docs/ops/CI_EFFICIENCY.md` §10 and
takes effect only after a separate owner approval. Existing CI savings (`CI_EFFICIENCY.md` §3: C1–C5) stay in place;
workflow triggers are changed only after a documented impact assessment and owner approval.

## 9. Local CI-Equivalent (LCE) — OWNER DECISION, 2026-10-28

The owner approved LCE as an alternative verification mechanism for development and integration gates, subject to
strict equivalence and auditable evidence. It does not waive tests, does not bypass enforced GitHub branch
protections and authorises no production operation.

- Runner and procedure: `ops/ci/lce.py`, `docs/ops/CI_EFFICIENCY.md` §11. It runs the jobs of
  `.github/workflows/tests.yml` for one exact SHA in a clean disposable worktree and fails closed on missing
  evidence, failed tests, incomplete coverage, environment mismatch or unverified equivalence (a workflow that differs
  from the reviewed one is refused).
- Disposable PostgreSQL containers only, isolated from production networks, volumes, credentials and databases. No
  host packages are installed and no production service is altered.
- **Substitution takes effect only after the runner and its equivalence have been independently reviewed.** From
  then on, an LCE verdict PASS for a SHA (manifest + checksums) may stand in for the documented development and
  integration CI checks (BRANCH_RELEASE_POLICY §3 "CI green", the Development-First "provided CI is green"
  condition). Existing GitHub-enforced branch protections remain binding; required checks are not disabled and
  protection settings are not modified. If GitHub prevents an integration despite valid LCE evidence, the blocker is
  reported, never bypassed. No PR is opened merely to implement this policy.
- Production deployment, restarts, database changes and protected scientific operations remain separately gated.
