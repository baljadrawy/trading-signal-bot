# SE-1 review: final consolidated result

**Approved candidate SHA (review verdicts apply to exactly this commit):** `7ff582fa43b4fd16042ccb6f71035e4031b67eac` (`release/se1-funnel-ea8ae4f`). The baseline is `ea8ae4f00e80c5c171536293d2df7472fa338c3e`. The deployment procedure reviewed is `deploy/se1-funnel-ea8ae4f/` at `78ba705`, plus the exact B3 queries added afterwards.

## 1. Reviewers and independence limits

There were three reviewers in fresh contexts on different models: R1 Fable 5.1, R2 Opus 5.5 and R3 Sonnet 5.5. None of them wrote or saw the implementation, and none saw the others' first reports. They were **not external**:
- all three share one provider, one host and one coordinating session with the implementation;
- the coordinator wrote their prompts.

R3 read production evidence_v2 counts outside the package scope. The coordinator redacted them in the stored report and reported the deviation to the owner. An external reviewer can repeat the audit from [REVIEW_PACKAGE.md](REVIEW_PACKAGE.md).

## 2. Individual verdicts

| Reviewer | Round 1 | After the closure check |
|---|---|---|
| R1, signal logic and parity | CONDITIONAL GO | CONDITIONAL GO, all R1 conditions closed or accepted as residual |
| R2, deployment, operations and rollback | CONDITIONAL GO | CONDITIONAL GO, only R2-01 (owner boundary declaration) OPEN |
| R3, observability, data integrity and tests | CONDITIONAL GO | CONDITIONAL GO, conditions met procedurally |

The reports are in [round-1/](round-1/), the closure checks in [closure/](closure/) and the matrix in [CONSOLIDATION_ROUND1.md](CONSOLIDATION_ROUND1.md).

## 3. Confirmed blockers and their closure

No code BLOCKER was found. The safety conditions and their closure evidence:
- **R2-01, version boundary: OPEN. Owner action.**
- **R2-02, health read from the old heartbeat:** closed by a 180 s delay, reads 60 s apart, and a heartbeat-freshness read.
- **R2-03, B3 gate:** closed. The exact read-only SQL is now in the procedure.
- **R2-04, rollback:** closed. The rollback is pre-staged to blob `d1a4b197`, config-hash `20dcae19` and image `c5be4e34`.
- **R2-05, base pinning:** closed. The base is pinned by digest, with a 26-layer gate.
- **R2-06, content verification:** closed. The manifest gate is 61/2/0/0.
- **R3-B3, invalid cycles accepted:** closed. The acceptance gates now require `observation_complete`, empty `integration_failures` and no `gate_block`.
- **R1-01, selection keys:** closed. The `SELECTION_*` keys are absent and forbidden.

## 4. Remaining operational risks (accepted as residual)

- **Daily cap:** it resets on every restart, so it bounds records per process per day. The gate is a RestartCount of 0 (R3-B1).
- **Failed emits:** a failed emit is detected (`not_recorded == 0` is a hard gate) but not repaired (R3-B2).
- **Clock:** a backward clock step resets the cap (R3-B4).
- **Hooks:** the hook call sites are unguarded, but the hooks are trivial (R1-02). The hooks import after the database connects; the dry run covers this (R1-03).
- **Queue:** the evidence_v2 queue is shared, so a long sink stall drops other event types first. Decisions are never affected.
- **Attribution:** per symbol, with the last label winning.
- **Dormant selection path:** it still exists in the image, behind environment variables that are forbidden.
- **Build reference:** the digest `FROM` is proven only by an actual build. It fails closed.
- **After a rollback:** production no longer matches the `main` HEAD, so a revert commit on `main` is needed.
- **What 24 hours cannot show:** cap behaviour, restart behaviour, queue saturation, rare labels, or ground-truth count accuracy.

## 5. Final recommendation

**CONDITIONAL GO for `7ff582f`.** Activation may be requested once the owner makes the R2-01 boundary declaration. The independence limitation above must be accepted by the owner, or an external review commissioned.

## 6. Another review round?

No. No code was changed, no BLOCKER or HIGH finding needs code, and the reviewers do not disagree on anything safety-critical. A Round 2 becomes mandatory only if any of the six files change, for example if the optional hardening (R3-B1, B2, B4; R1-02, R1-03) is applied before SE-1.

## 7. Smallest owner approval required next

1. **Declare the SE-1 version boundary:** signal_engine, observe-only PATCH, `APP_VERSION` unchanged. Either accept the 25-seed before-tree parity (decisions, statements and messages identical to `ea8ae4f`) as the byte-identical replay, or declare the boundary MAJOR.
2. **Accept the reviews' independence limitation**, or name an external reviewer.
3. **Approve the read-only B3 gate queries** (Q1 and Q2 in the procedure) before and after.
4. **Grant the Class B approvals**, in this order, each as specified in `deploy/se1-funnel-ea8ae4f/README.md`:
   - the overlay image build;
   - the Compose change integrated into `main`, then installed;
   - the recreate of signal_engine only;
   - the pre-approved rollback.
