# Development-First operating policy (R&D stage)

> **OWNER DIRECTIVE — EFFECTIVE 2026-10-26 (Continuous Development + PR-on-Demand).** This dated directive is governing immediately for development workflow and supersedes conflicting procedural requirements below and in `docs/ops/BRANCH_RELEASE_POLICY.md`. It does not erase prior scientific decisions or authorize production trading.
>
> **Workflow:** Prefer the existing `main` and at most one shared, short-lived integration branch when isolation is needed. Do not create one branch or Draft PR per ordinary task. Commit and push small, auditable changes; run proportionate tests, secret scanning and relevant CI. Low-risk D0 development (docs, tests, synthetic research, tooling and default-off non-operational changes) may be integrated into `main` directly or by fast-forward/merge without a PR or repeated owner approval, provided CI is green, the change is reversible, and it does not alter deployed runtime, risk controls, scientific admission, protected data or production configuration. Stop only the affected change if its tests fail. Independent external review is advisory, not a gate for ordinary D0 work.
>
> **Deployment:** Automatically deploy validated D0 changes only to a genuinely isolated development/lab environment with no production secrets, databases, protected datasets, or live service dependency; use a known rollback point and smoke tests. The current shared production host is **not** an isolated development environment merely because trading is Paper-only. On-host changes to live Collector, Scanner, Paper strategy, databases, schedules, monitoring coupled to live services, or production images are **not** automatically authorized. Isolated observability deployments may be automated only after verifying process/data isolation, read-only permissions, no impact on live services, and rollback; otherwise obtain operation-specific approval. Merging to `main` never triggers production deployment by itself.
>
> **Owner gates retained:** changing Paper strategy or its version/window, `/resume` or technical halt, live service deployments/restarts, database writes, access to protected holdouts, confirmatory scientific admissions, and any real-money trading (forbidden) remain separately controlled. Exploratory real-data work requires licensed, explicitly permitted non-holdout data; no implied permission to run protected experiments. Evidence and secrets remain protected. Keep fee baseline 0.10% each side plus spread/slippage.
>
> **Transition:** Inventory existing Draft PRs/branches; classify, preserve their head SHAs and unique work, integrate eligible D0 changes incrementally after tests, and close redundant PRs only after verifying preservation. Never bulk-delete branches or evidence. PR #90 branch protection must be revised to match PR-on-Demand before activation. Record deployed SHA and actual runtime parity when making runtime claims. Report Saved / Integrated / Deployed / Validated distinctly.


**Status: PROPOSED (Draft PR-A, 2026-10-20).** It becomes governing when the owner merges it. Until then the existing records govern. Owner direction behind it (2026-10-20): the project stays in Research & Development, has **not** demonstrated an economically viable edge and is **not** approved for live money; development should be the default activity and procedure should exist only where it serves safety, scientific integrity, security or data preservation.

**What this document does.** It is the single entry point that says which rules apply to which kind of work. It does not delete or rewrite any historical record or scientific decision. Where it would change an owner-approved *scientific* constraint, it only proposes the change (section 7); that change needs a separate owner decision.

## 1. Principles

1. Development is the default permitted activity.
2. Every restriction names its purpose: safety, scientific integrity, security or data preservation.
3. Safe independent work continues when an unrelated workstream is blocked.
4. Exploratory development is separate from confirmatory scientific claims.
5. Historical negative results are evidence against the **tested implementations**, not proof that every alternative must fail.
6. Engineering correctness does not establish profitability.
7. No strategy is production-approved until its economics and risk controls are independently validated.
8. Protected holdouts stay independent of exploratory development.
9. Harmless source changes are not blocked by operational procedure.
10. Prior scientific decisions stay traceable; obsolete operational procedure is not forced onto development tasks.

## 2. Activity classes

| Class | Examples | Default | Approval |
|---|---|---|---|
| **D0 Development** | source, tests, synthetic data, CI, docs, refactors, research tooling, flags that default to current behaviour | **Allowed** | Pushing development branches and opening Draft PRs: standing owner authorization (2026-10-20). Merge: owner decision per PR |
| **D1 Exploratory research** | calculations on real historical data for hypothesis development | Allowed **only** on a dataset with a recorded permission: licence cleared and every protected holdout excluded (`research/mechanisms/simulate.DatasetPermission`, Draft PR #60). **Today no dataset has one** (A18/A19 licence HOLD), so D1 is synthetic and literature work until section 7 OD-DF-1 is decided | Owner records each dataset permission |
| **D2 Prospective observation** | a declared Paper window for a behaviour change | Owner-declared windows only; never pooled across windows | Owner |
| **D3 Confirmatory validation** | Evidence Ladder (S5) admissions | Unchanged; all HOLDs remain | Owner per admission and budget |
| **D4 Production operations** | anything on the running host | `docs/ops/COMPOSE_OPERATIONS.md` Class A/B/C, unchanged | Class B: owner per operation |
| **D5 Live trading** | real money | **Forbidden** (PAPER_ONLY; four conditions, owner directive 2026-09-27) | — |

A task belongs to the highest class it touches. A D0 task never becomes D4 because it is "small".

## 3. Rules that always apply

| Rule | Purpose |
|---|---|
| `PAPER_TRADING=true`; no live path, flag or automatic promotion | safety |
| No secrets in Git, logs, PRs or reports; `.env` stays host-local | security |
| Learner stays stopped (separate authorization) | safety |
| FORWARD_HOLDOUT (after 2026-08-19T09:33:46Z) stays sealed; no protected outcome, count or timestamp reads (OD-7); `unlock-holdout` is a one-way owner decision | scientific integrity |
| No production database read or write without owner approval | data protection / holdout |
| No deletion, move or rewrite of evidence, recovery points, sealed datasets or historical audits | data preservation |
| Production operations follow Class A/B/C and the absolute STOP rule | safety |
| Cost baseline 0.10 %/side, spread and slippage separate, tracker 0.30 % reported separately; no discounted-fee optimisation | scientific integrity |
| Every result carries its evidence class (engineering, synthetic, exploratory, prospective, confirmatory); synthetic or exploratory success is never reported as profitability | scientific integrity |
| Behaviour changes to Paper (geometry, selection, integrity mode) are declared strategy-version boundaries | scientific integrity |

## 4. What changes for development (friction removed)

| Previous practice | Under this policy | Why |
|---|---|---|
| "No push or merge without the owner's approval for that action" (`BRANCH_RELEASE_POLICY.md` §10) | Development branches may be pushed and Draft PRs opened under the standing authorization. Merge, release and deploy still need per-PR / per-operation decisions | push is reversible and private; merge and deploy are not |
| Absolute STOP applied to whole tasks | The absolute STOP rule applies to **production operations and protected data**. In development, a blocker isolates the affected task; independent work continues and the blocker is reported | principle 3 |
| Drift check at every task start (R1.3 §3) | Required only for tasks that touch or claim runtime state (deploy, release records, runtime docs). Source/research/docs tasks state "no runtime claim" instead | drift is a release gate, not a development gate |
| Runtime provenance section on every PR (`BRANCH_RELEASE_POLICY.md` §3) | Docs-only and research-only PRs state "no runtime effect"; full provenance stays mandatory for deployable code | avoid ritual sections |
| Independent review recorded on every PR before merge (§8) | Still required for deployable service code and production-operations definitions. For docs-only and research-only PRs, the owner's review is sufficient | review effort where risk is |

None of these rows touches a scientific constraint.

## 5. Reconciliation register

| Rule / record | Source | Disposition |
|---|---|---|
| PAPER_ONLY, live forbidden, four conditions | owner 2026-09-27 | **RETAINED** |
| Class A/B/C, single-service steps, STOP rule for production | `COMPOSE_OPERATIONS.md`, `CLAUDE.md` | **RETAINED** (DEPLOY-ONLY scope, section 4 row 2) |
| Temporal governance, FORWARD_HOLDOUT, contamination registry | `docs/research_temporal_governance.md` | **RETAINED** |
| Evidence Ladder: α = 1/240, final look only, FWER, ≤ 3 candidates, 20 % reserve | A29–A33 (local), roadmap | **CONFIRMATORY-ONLY** (D3); not a development gate |
| S5 HOLDs: A34-VS1, MI Stage B, B2, P2-D1, Paper R2, D1–D5 | roadmap | **RETAINED** |
| OD-1..OD-7 (S5-PWR-1) | `docs/strategy/S5_PWR_1_OWNER_DECISIONS.md` | **RETAINED** |
| "Experimental logic pure, versioned, disabled; production never imports it" | roadmap ground rules | **SIMPLIFIED**: equivalent separation may be a production flag that defaults to current behaviour, fails closed on unknown values and is tested byte-identical at the default (example: Draft PR #59, `T1_CAP_POLICY`). Activation stays an owner decision |
| "No real historical backtests … without a separate approval"; S4 HOLD "any backtest or outcome-based selection" | roadmap | **RETAINED**; change **PROPOSED** as OD-DF-1 (section 7) |
| Main-first branch/release policy | `docs/ops/BRANCH_RELEASE_POLICY.md` (merged PR #42) | **RETAINED**; §10 and §3/§8 scope **SIMPLIFIED** (section 4). Its header still says PROPOSED: **STALE**, corrected by dated note |
| R1.3 event-driven recovery | `docs/ops/EVENT_DRIVEN_RECOVERY_GOVERNANCE.md` (merged PR #46) | **RETAINED** for release recovery. Header says "proposed": **STALE**, dated note. Ongoing data protection: `docs/ops/BACKUP_MODEL_RD.md` |
| "Nightly bot backup failing → no working DB backup" | `TSB_BACKUP_RECOVERY_PLAN.md`, `PORTABILITY_AND_DR.md` D-01/D-02 | **FACT CORRECTED**: `trading_signals` is also dumped nightly into the local xsch restic repository (dated note) |
| R-1 install, KEEP=7 retention, CP-9 schedule | `TSB_BACKUP_RECOVERY_PLAN.md` §5 | **SUPERSEDED** by R1.3 (already stated there); not to be installed |
| "PAPER_HALTED" stated as current state | `COMPOSE_OPERATIONS.md` §0, `CLAUDE.md` | **STALE**: B3 is computed from closed trades at each evaluation, not stored; current state UNVERIFIED (dated note) |
| Roadmap "production baseline `59297305`, schema 9" | roadmap ground rules | **STALE**: deployed release is A56.5 `ea8ae4f`, schema 11 (dated note) |
| Collector continuous operation, `restart: "no"` (D3), observe-only monitor (D4/D5) | P2-CR records | **RETAINED**; necessity reassessed in `docs/ops/COLLECTOR_NECESSITY_ASSESSMENT.md` (OD-DF-3) |
| `GIT_GUIDE.md`, `SETUP_GUIDE.md` Git section, `docs/claude/operations.md` direct push | `BRANCH_RELEASE_POLICY.md` §12 | **CONFLICT, still open** (separate docs PR) |

## 6. Approval matrix

| Allowed now (D0) | Needs an owner decision | Forbidden under current governance |
|---|---|---|
| code, tests, synthetic data, CI, docs, research tooling | merging any PR | live trading or any live path |
| pushing development branches; Draft PRs | recording a dataset permission (D1) | reading sealed holdout outcomes, counts or timestamps |
| flags that default to current behaviour and fail closed | switching a strategy flag; declaring a Paper window | changing Paper admission or resetting B3 outside its runbook |
| literature and specifications | any production operation (Class B) | learner start without its own authorization |
| reading public documentation | DB reads; backups, cron, retention, off-host transfer | deleting evidence, recovery points or sealed data |
| | S5 admissions and alpha | Class C commands |

## 7. Proposed changes to owner-approved scientific constraints (not effective until decided)

| ID | Proposal | Current constraint | Why |
|---|---|---|---|
| **OD-DF-1** | Allow D1 exploratory historical analysis for hypothesis development on data with a recorded permission (licence cleared, entirely before the 2026-08-19 freeze or otherwise outside every holdout), labelled exploratory and never used as confirmation | roadmap "no real historical backtests without separate approval"; S4 HOLD "any backtest" | Without any real-data exploration, mechanism research is limited to literature; the A18/A19 licence question still has to be answered first |
| **OD-DF-2** | Decide a validation design for realistic effect sizes: longer prospective windows, a multi-candidate design, or long licence-cleared history for qualification plus a short prospective sanity check | Evidence Ladder 365 days | The 365-day daily-HAC Sharpe MDE is ≈ 3.5–7.0 (`research/power`, illustrative); no realistic daily strategy can be confirmed in one window |
| **OD-DF-3** | ~~Collector option C1 (keep stopped, preserve evidence)~~ **DECIDED 2026-10-20: retain continuous collection** (CHG-02 executed; CHG-03 reboot recovery in development) | P2-CR continuous operation | `docs/ops/COLLECTOR_NECESSITY_ASSESSMENT.md` §0 |
| **OD-DF-4** | Backup model of `docs/ops/BACKUP_MODEL_RD.md` | R1.3 + legacy p1bg cron | the model separates release recovery from ongoing data protection |

## 8. Precedence and document map

1. Owner directives (PAPER_ONLY, holdout, OD-1..OD-7) and the rules in section 3.
2. `docs/ops/COMPOSE_OPERATIONS.md` for every production command.
3. This policy for what work needs which approval.
4. `docs/ops/BRANCH_RELEASE_POLICY.md` (merge, release, deploy), as narrowed in section 4.
5. `docs/ops/EVENT_DRIVEN_RECOVERY_GOVERNANCE.md` and `docs/ops/BACKUP_MODEL_RD.md` (recovery).
6. `docs/research_temporal_governance.md`, `docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md`, `docs/strategy/S5_PWR_1_OWNER_DECISIONS.md` (science).
7. Historical audits and reports: immutable evidence, dated notes only.
