# Independent review package R2: software architecture, data integrity, container security

**For:** an external reviewer independent of the author. **Status:** not yet reviewed (no external response received as of 2026-10-20). Refreshed for design revision 3 (owner decisions applied). No secrets or host credentials are included.

## Artifacts
- `docs/lab/STRATEGY_LAB_ARCHITECTURE.md`: current state A1–A12, target, isolation model, owner-decided account rules R0–R10, data-access matrix, gaps G1–G7, tests, resources (§10), lab DB isolation and raw-data immutability (§11).
- Paper engine: `trade_tracker/main.py`, `shared/partial_exits.py`, `shared/risk_management.py`, `shared/risk_epoch.py`, `database/migrations/001`–`011` (`main` @ `1432a90` = deployed `ea8ae4f` for service code).
- Collector isolation: `p2_forward/compose.yml`, `p2_forward/ops/`, `ops/host/` (`main`).
- Operations policy: `docs/ops/COMPOSE_OPERATIONS.md`, `docs/ops/BRANCH_RELEASE_POLICY.md`, `docs/ops/EVENT_DRIVEN_RECOVERY_GOVERNANCE.md`.
- Ledger pattern reference: `p2_forward/ops/p2f_reboot_recover.py` (Draft PR #62).

## Context facts (author-verified, read-only)
- No account concept exists in the Paper engine. Size is fixed at 50 USDT, and risk (loss streak, pause, exposure) is global.
- The engine is bracket-based (entry/T1/T2/T3/stop/BE/expiry). It has no target-weight path.
- Raw data: 49,600 files, all writable by the service user `tradmin`. Integrity rests on hash manifests only. The owner decided **no bulk chmod**; no active writer was observed (read-only check, §11.4).
- Owner decisions: logical `tsb_lab` on the existing cluster only if isolation is demonstrated, otherwise a physically separate DB service; R1 4 vCPU, R2 5 vCPU, R3 deferred; S0 read-only measurement; S1/S2 design and validation only; S3 deferred (no production container recreation); up to five strategy containers subject to capacity testing.
- A single shared host (12 cores, 23 GB), a shared Postgres cluster with other projects, and Docker with live-restore and the systemd cgroup driver.
- Production DB `trading_signals`, schema 11. The production Paper account must remain unchanged.
- Risk policy R9 (owner-decided 2026-10-21): `SUSPENDED_REVIEW` at a 30 % drawdown from peak or equity < 2,000 USDT; alert-only at 8 consecutive losses; immediate new-order block (`BLOCKED_INTEGRITY`) on any accounting-integrity failure; open positions keep predeclared exits; no automatic reset or resumption. A pure, inactive reference implementation is proposed separately (Draft PR, not for merge before this review).

## Questions
1. Is extending `trade_tracker` (`LAB_MODE`, a separate `tsb_lab` DB, a target-position path) the minimal safe reuse? Or is a technically necessary alternative better (e.g. a separate engine process sharing only the fill/fee library)? State the trade-offs.
2. Logical `tsb_lab` database on the shared cluster: are the §11.3 acceptance tests sufficient to prove isolation, and what result should force the fallback to a physically separate service? Are the role design (§11.2), RLS for `signal_intents` and connection limits adequate?
3. Idempotency and transactions:
   - intent uniqueness;
   - order/fill/ledger atomicity;
   - concurrent intents against the cap (R1);
   - crash recovery.
4. Container hardening:
   - read-only rootfs, distinct UIDs, caps, egress allowlist, resource limits;
   - whether `restart: "no"` plus registry-driven lifecycle is sufficient.
5. Raw-data immutability:
   - read-only bind mounts only via certified snapshots;
   - with no bulk chmod of the originals, is a certified snapshot copy + `:ro` mount + pre-run hash check + periodic read-only re-hash (§11.4) sufficient?
   - manifest verification at mount time.
6. Fault isolation: OOM, disk-full and a runaway strategy must not affect the engine, production services, the Collector or other projects.
7. Reproducibility: image digest pinning, an experiment registry (append-only, hash-chained), and content-addressed results.
8. Deployment and rollback: the minimal steps; how removing the lab leaves production byte-identical.

9. Resource isolation (§10):
   - Is the split budget (user `research.slice` + system `tsblab.slice`) correct given that Docker scopes live under `system.slice`?
   - Is S3 (a project parent slice requiring production recreates) worth it, or are weights plus caps enough?
   - Are PSI thresholds, protected windows and bounded queues adequate?
   - Is R2 at 5 vCPU (budget arithmetic only, ceiling not enforced, three uncapped production services) an acceptable control without S3?

## Acceptance tests the reviewer should require or confirm
- RLS cross-strategy denial.
- Replayed-intent single order.
- Fault injection (OOM, kill between fill and ledger).
- Production byte-identity with `LAB_MODE` unset.
- A write to the snapshot mount fails.
- No mount of `p2` / post-freeze paths.
- Removing the lab leaves `trading_signals` and the Collector untouched.
- A CPU-burn and memory-burn job is throttled and OOM-contained inside its slice, with production PSI and health unchanged.
- Admission is refused under injected pressure.
- §11.3 DB isolation tests 1–6 pass on a disposable cluster.
- Integrity failure blocks new orders in the same transaction that detects it; exits are still booked atomically.
- Pre-run snapshot hash mismatch blocks a run.

## Response template
```
Reviewer: <name / affiliation / independence statement>    Date:    Commit reviewed: <sha>
Verdict: GO | REVISE | NO-GO
Findings: [id, severity BLOCKER/MAJOR/MINOR, statement, evidence, recommended correction]
Alternatives considered and trade-offs:
Required acceptance tests:
Owner decisions remaining:
```
