# Independent review package R2: software architecture, data integrity, container security

**For:** an external reviewer independent of the author. **Status: NOT YET REVIEWED.** No external or independent response has been received as of 2026-10-21. Refreshed 2026-10-21 for `main` @ `614cecd` and Draft PR #67. No secrets or host credentials are included.

## Artifacts
- `docs/lab/STRATEGY_LAB_ARCHITECTURE.md`: current state A1–A12, target, isolation model, owner-decided account rules R0–R10, data-access matrix, gaps G1–G7, tests, resources (§10), lab DB isolation and raw-data immutability (§11).
- Paper engine: `trade_tracker/main.py`, `shared/partial_exits.py`, `shared/risk_management.py`, `shared/risk_epoch.py`, `database/migrations/001`–`011` (`main` @ `614cecd`; deployed service images are still `ea8ae4f`, and `main` differs only by the dormant `T1_CAP_POLICY` flag from #59).
- Collector isolation: `p2_forward/compose.yml`, `p2_forward/ops/`, `ops/host/` (`main`).
- Operations policy: `docs/ops/COMPOSE_OPERATIONS.md`, `docs/ops/BRANCH_RELEASE_POLICY.md`, `docs/ops/EVENT_DRIVEN_RECOVERY_GOVERNANCE.md`.
- Ledger pattern reference: `p2_forward/ops/p2f_reboot_recover.py` (`main`, merged #62, not installed).
- Exit model (single source of truth in production): `shared/triple_barrier.py`; fees: `shared/fees.py`; research costs: `research/mechanisms/costs.py`.
- **Accounting core under review:** `lab/account.py`, `lab/REVIEW.md` (invariants I1–I14, limits, questions), `tests/test_lab_account.py` (Draft PR #67, not merged).
- Research runner source: `ops/research/` (`main`, merged #65; matches the installed copy).

## Context facts (author-verified, read-only)
- No account concept exists in the Paper engine. Size is fixed at 50 USDT, and risk (loss streak, pause, exposure) is global.
- The engine is bracket-based (entry/T1/T2/T3/stop/BE/expiry). It has no target-weight path.
- Raw data: 49,600 files, all writable by the service user `tradmin`. Integrity rests on hash manifests only. The owner decided **no bulk chmod**; no active writer was observed (read-only check, §11.4).
- Owner decisions: logical `tsb_lab` on the existing cluster only if isolation is demonstrated, otherwise a physically separate DB service; R1 4 vCPU, R2 5 vCPU, R3 deferred; S0 read-only measurement; S1/S2 design and validation only; S3 deferred (no production container recreation); up to five strategy containers subject to capacity testing.
- A single shared host (12 cores, 23 GB), a shared Postgres cluster with other projects, and Docker with live-restore and the systemd cgroup driver.
- Production DB `trading_signals`, schema 11. The production Paper account must remain unchanged.
- Risk policy R9 (owner-decided 2026-10-21): `SUSPENDED_REVIEW` at a 30 % drawdown from peak or equity < 2,000 USDT; alert-only at 8 consecutive losses; immediate new-order block (`BLOCKED_INTEGRITY`) on any accounting-integrity failure; open positions keep predeclared exits; no automatic reset or resumption. A pure, inactive reference implementation is in Draft PR #67 and is not for merge before this review.

## Evidence status: completed tests vs. external review

| Item | Status | Evidence |
|---|---|---|
| Ledger correctness and reconciliation (in memory) | **internal tests done** | #67: hash chain, cash recomputed from ledger, re-hashed forgery detected; seeded 1,500-step randomized run over 3 accounts |
| Transactional integrity (in memory) | internal tests done | #67: injected failure mid-operation leaves state and ledger unchanged; replayed fills and exits book once |
| Account isolation (in memory) | internal tests done | #67: no shared state, no cross-account events |
| No production import / image copy | internal test done | #67 test + Dockerfile check |
| DB isolation (`tsb_lab`, roles, RLS, §11.3) | **not built / not tested** | design only |
| Persistence and crash recovery from the DB | **not built** | — |
| Container boundaries (read-only rootfs, UIDs, egress) | **not built** | design only (§2.1) |
| Resource governance | partial | S0 read-only observation running (no gaps, ≈ 0.02 % CPU); S1/S2 design only; 10 vCPU ceiling **not enforced** |
| **Independent architecture / security review** | **NOT DONE** | this package |

## B. Questions by topic

### B1. Account and database isolation
1. Is extending `trade_tracker` (`LAB_MODE`, separate `tsb_lab`, a target-position path) the minimal safe reuse, or is a separate engine process sharing only the fill/fee library better?
2. Logical `tsb_lab` on the shared cluster: are the §11.3 tests sufficient, and which result forces a physically separate service? Are the roles (§11.2), RLS on `signal_intents` and connection limits adequate?

### B2. Ledger correctness and reconciliation
3. #67 re-verifies the whole hash chain and recomputes cash from the ledger after every operation, which is O(n). Is incremental verification plus a periodic full audit acceptable for the persistent engine?
4. Are 1e-8 USDT money rounding and 1e-12 quantity rounding (down) acceptable, and is a round-trip residual below 1e-6 USDT tolerable?

### B3. Transactional integrity
5. Which DB design preserves I7/I8 under concurrency: one transaction per operation, unique keys on intent/order/exit ids, serializable isolation for cap checks, or something else?
6. `BLOCKED_INTEGRITY` keeps executing predeclared exits on a ledger that just failed an invariant (owner rule: open positions keep their risk handling). Is that safe, or must exits be queued for review?

### B4. Reuse versus duplication (owner direction decided 2026-10-21)
7. The owner decided that the lab reuses the shared execution, cost and exit-policy logic, with no duplicated formulas, and no production connection or broad refactor. Review `lab/ARCHITECTURE_ALIGNMENT.md`:
   - the adapter boundary (decisions only from `step_barrier` / `fills_between`; money booked by the lab once with `CostModel`);
   - the versioned `exit_policy_id` / `cost_model_id` / `entry_fill_model` and the shared-blob pins;
   - the stop-trigger option (an additive shared field vs. lab-side inversion);
   - the parity tests P1–P7.

### B5. Resource governance
8. Is the split budget (user `research.slice` plus system `tsblab.slice`) correct, given that Docker scopes live under `system.slice`? Is R2 = 5 vCPU, held by arithmetic only (ceiling not enforced; telegram, tracker and shared postgres uncapped), acceptable without S3?

### B6. Container boundaries
9. Are a read-only rootfs, distinct UIDs, `cap_drop: ALL`, `no-new-privileges`, an egress allowlist, `restart: "no"` and pids/memory limits sufficient for strategy containers?

### B7. Evidence retention
10. Is an append-only hash-chained ledger, JSONL export, retained rejected intents and no delete/reset API sufficient? Where must ledger exports live (backup scope, immutability)?

### B8. Failure and recovery
11. Fault isolation for OOM, disk-full, runaway strategy, DB outage and engine crash between fill and ledger. Required behaviour, and the test for each.
12. Is removing the lab guaranteed to leave production (`trading_signals`, Collector, images) byte-identical?

## Known unresolved issues (author)
- B4: the owner direction is decided (reuse). The alignment is designed, but **not implemented**; it is gated on this review and the parity tests.
- No persistence, DB isolation tests or container implementation yet.
- The installed research-runner R2 profile is still 600 % (owner budget 5 vCPU); the change is pending approval.
- Research-runner admission is open since the Collector became HEALTHY; job start is still explicit only.

## Acceptance tests the reviewer should require or confirm
- RLS cross-strategy denial; replayed-intent single order; fault injection (OOM, kill between fill and ledger).
- Production byte-identity with `LAB_MODE` unset; removing the lab leaves `trading_signals` and the Collector untouched.
- A write to the snapshot mount fails; no mount of `p2` or post-freeze paths.
- CPU/memory burn contained in its slice with production PSI unchanged; admission refused under injected pressure.
- §11.3 DB isolation tests 1–6 on a disposable cluster; pre-run snapshot hash mismatch blocks a run.

## Evidence the reviewer needs (exact versions)
- `main` @ `3bd79a4`:
  - `docs/lab/STRATEGY_LAB_ARCHITECTURE.md` (rev 4);
  - `shared/triple_barrier.py`, `shared/partial_exits.py`, `shared/entry_execution.py`, `shared/execution.py`, `shared/fees.py`;
  - `trade_tracker/main.py` (the `evaluate_trade` path);
  - `research/mechanisms/costs.py`;
  - `ops/research/` (runner);
  - `p2_forward/ops/` (ledger and gate patterns);
  - `docs/ops/COMPOSE_OPERATIONS.md`, `docs/ops/BRANCH_RELEASE_POLICY.md`.
- Draft PR #67 (current head): `lab/account.py`, `lab/REVIEW.md` (invariants I1–I14), `lab/ARCHITECTURE_ALIGNMENT.md` (adapter design, parity tests P1–P7), `tests/test_lab_account.py`.
- Draft PR #71: the research runner's R2 envelope and the aggregate-budget gaps.
- S0 read-only resource observation summary (author report). The raw samples are available on request; they contain no secrets.
- **Not provided:** credentials, the production `.env`, and protected datasets.

## Independence requirement
- The reviewer must not be the author (the operating agent), and must not have contributed to the reviewed artifacts. State any relationship.
- Agent self-checks, CI runs and the author's tests are **not** independent review and do not count toward this gate.

## Expected deliverables
1. A completed response template (below) at an **exact commit SHA**.
2. A finding list. Each finding has an id, severity (BLOCKER / MAJOR / MINOR), statement, evidence (file:line or test), and a recommended correction.
3. The acceptance tests the reviewer requires, marked "must pass before merge" or "before activation".
4. An explicit verdict: GO / REVISE / NO-GO.

## How findings are accepted or rejected (owner-side rule)
- **Accepted:** a finding with reproducible evidence at the reviewed SHA. It is tracked to closure, by a fix PR or a documented owner risk acceptance.
- **Rejected:** only with a written counter-evidence note (a test, code reference or data) attached to the finding. Disagreement alone is not rejection.
- **Severity:** any open BLOCKER means NO-GO for merge or activation. A MAJOR needs a fix or an explicit owner risk acceptance. A MINOR may be deferred, but is recorded.
- **Staleness:** a review is valid only for the reviewed SHA. Later changes to the reviewed files need a delta review.

## Response template
```
Reviewer: <name / affiliation / independence statement>    Date:    Commit reviewed: <sha>
Verdict: GO | REVISE | NO-GO
Findings: [id, severity BLOCKER/MAJOR/MINOR, statement, evidence, recommended correction]
Alternatives considered and trade-offs:
Required acceptance tests:
Owner decisions remaining:
```
