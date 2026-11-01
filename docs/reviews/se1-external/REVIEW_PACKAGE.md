# SE-1 review package (for independent reviewers)

This is the package for the owner-requested three-reviewer audit of the SE-1 release: signal_engine funnel telemetry. It is self-contained, so that a reviewer outside this repository's development session can run the same audit.

## Target

| Item | Value |
|---|---|
| Repository | `baljadrawy/trading-signal-bot` |
| Baseline (deployed signal_engine source) | `ea8ae4f00e80c5c171536293d2df7472fa338c3e` |
| Candidate | `7ff582fa43b4fd16042ccb6f71035e4031b67eac`, branch `release/se1-funnel-ea8ae4f` |
| Exact diff under review | `git diff ea8ae4f 7ff582f` (six files) |
| Deploy record | `deploy/se1-funnel-ea8ae4f/{Dockerfile,README.md,services.json}` on `feature/wp2-foundation-20261101` |
| Tests | `tests/test_funnel_records.py`, `tests/funnel_service_harness.py`, `tests/test_selection_rank_then_limit.py` on `feature/wp2-foundation-20261101` |
| Owner-selected values (review only; not a deployment approval) | `FUNNEL_RECORDING=on`, `FUNNEL_MAX_RECORDS_PER_DAY=20000`, a 24-hour monitoring window |
| Governance | `docs/governance/WP2_FUNCTIONAL_INCREMENTAL_PAPER_ACTIVATION_2026-11-01.md`, `docs/ops/COMPOSE_OPERATIONS.md`, `CLAUDE.md`, `docs/governance/OWNER_OPERATING_CONTRACT.md`, `docs/governance/DEVELOPMENT_FIRST_POLICY.md` |

Unrelated WP2 development is out of scope for the SE-1 verdict.

## Rules for every reviewer

- **The review is READ-ONLY:**
  - no repository edits and no git writes;
  - no merge, deployment, image build, container start or restart on shared services;
  - no Compose change and no database access or writes.
- **Data access:**
  - no protected research, sealed holdout, trade outcomes or P&L;
  - do not read `.env` files, and never print secrets;
  - PAPER_ONLY and the A29 D1/D2 HOLD are preserved.
- **What you may run:**
  - read-only git commands, and tests in your own scratch directory against `git archive` exports;
  - for image identity: `docker image inspect` and `docker inspect trading_signal_engine` (read-only);
  - a disposable `docker run --rm --network none --read-only` from the baseline image, for file hashing or test runs only.
- **Evidence:**
  - treat the developer's documentation and commit messages as claims to verify;
  - cite file:line and commit SHAs;
  - mark each piece of evidence as independently verified or developer-reported;
  - never invent results.
- **Redaction:** reports must not contain any of the following:
  - a clock time with seconds;
  - the words t-o-k-e-n or p-a-s-s-w-o-r-d;
  - "api" followed by "key";
  - host home paths, IP addresses or personal names.

## Required output

- **A. Verdict:** GO, CONDITIONAL GO, NO-GO or INSUFFICIENT EVIDENCE.
- **B. Findings.** For each one: an ID, a severity (BLOCKER, HIGH, MEDIUM or LOW), the file and lines, the reproduction or reasoning, the operational impact, the minimum corrective action, and whether it blocks SE-1.
- **C. Claim verification.** Mark every relevant developer claim VERIFIED, REFUTED, NOT VERIFIED or NOT APPLICABLE.
- **D. Residual risks.**
- **E. Minimal remediation**, limited to SE-1 safety.

## Reviewer focus areas

| Reviewer | Focus |
|---|---|
| R1, signal logic and behavioural parity | whether telemetry can alter eligibility, selection, ranking, targets or emitted signals; SQL text, order, transactions and database access; the preserved alphabetical `LIMIT 200`; whether exceptions, shared state or timing can affect decisions; the label mapping, `F4.unattributed` and conservation; dependencies and compatibility; strategy identity and version boundary |
| R2, deployment, operations and rollback | baseline image identity and source provenance; overlay paths, ownership, reproducibility, and that only six files enter the image; Compose targeting and isolation; config validation and restart-loop risk; shared-host blast radius and PAPER_HALTED/B3; rollback images and procedure; runtime-manifest verification; version-boundary and deploy provenance; activation without touching other services. Every command is a proposal only |
| R3, observability, data integrity and test evidence | stage definitions, taxonomy and conservation invariants; count accuracy, deduplication and `F4.unattributed`; the UTC daily cap and its boundaries; whether envelopes or other events bypass the limits; memory, CPU, latency, queue saturation and storage; whether funnel events can push out existing evidence_v2 records; whether drops, overflow and unattributed counts stay observable; test completeness, fixture realism and parity independence; the exact commit of each reported result; whether 24 hours can establish operational correctness |
