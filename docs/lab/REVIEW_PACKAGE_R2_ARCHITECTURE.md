# Independent review package R2: software architecture, data integrity, container security

**For:** an external reviewer independent of the author. **Status:** not yet reviewed. No secrets or host credentials are included.

## Artifacts
- `docs/lab/STRATEGY_LAB_ARCHITECTURE.md`: current state A1–A12, target, isolation model, data-access matrix, gaps G1–G7, tests.
- Paper engine: `trade_tracker/main.py`, `shared/partial_exits.py`, `shared/risk_management.py`, `shared/risk_epoch.py`, `database/migrations/001`–`011` (`main` @ `1432a90` = deployed `ea8ae4f` for service code).
- Collector isolation: `p2_forward/compose.yml`, `p2_forward/ops/`, `ops/host/` (`main`).
- Operations policy: `docs/ops/COMPOSE_OPERATIONS.md`, `docs/ops/BRANCH_RELEASE_POLICY.md`, `docs/ops/EVENT_DRIVEN_RECOVERY_GOVERNANCE.md`.
- Ledger pattern reference: `p2_forward/ops/p2f_reboot_recover.py` (Draft PR #62).

## Context facts (author-verified, read-only)
- No account concept exists in the Paper engine. Size is fixed at 50 USDT, and risk (loss streak, pause, exposure) is global.
- The engine is bracket-based (entry/T1/T2/T3/stop/BE/expiry). It has no target-weight path.
- Raw data: 49,600 files, all writable by the service user `tradmin`. Integrity rests on hash manifests only.
- A single shared host (12 cores, 23 GB), a shared Postgres cluster with other projects, and Docker with live-restore and the systemd cgroup driver.
- Production DB `trading_signals`, schema 11. The production Paper account must remain unchanged.

## Questions
1. Is extending `trade_tracker` (`LAB_MODE`, a separate `tsb_lab` DB, a target-position path) the minimal safe reuse? Or is a technically necessary alternative better (e.g. a separate engine process sharing only the fill/fee library)? State the trade-offs.
2. Separate database vs separate schema on the shared cluster: is it isolation enough? Are the role design, RLS for `signal_intents` and connection limits adequate?
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
   - whether `chmod a-w` / `chattr +i` on `raw/` is warranted;
   - manifest verification at mount time.
6. Fault isolation: OOM, disk-full and a runaway strategy must not affect the engine, production services, the Collector or other projects.
7. Reproducibility: image digest pinning, an experiment registry (append-only, hash-chained), and content-addressed results.
8. Deployment and rollback: the minimal steps; how removing the lab leaves production byte-identical.

## Acceptance tests the reviewer should require or confirm
- RLS cross-strategy denial.
- Replayed-intent single order.
- Fault injection (OOM, kill between fill and ledger).
- Production byte-identity with `LAB_MODE` unset.
- A write to the snapshot mount fails.
- No mount of `p2` / post-freeze paths.
- Removing the lab leaves `trading_signals` and the Collector untouched.

## Response template
```
Reviewer: <name / affiliation / independence statement>    Date:    Commit reviewed: <sha>
Verdict: GO | REVISE | NO-GO
Findings: [id, severity BLOCKER/MAJOR/MINOR, statement, evidence, recommended correction]
Alternatives considered and trade-offs:
Required acceptance tests:
Owner decisions remaining:
```
