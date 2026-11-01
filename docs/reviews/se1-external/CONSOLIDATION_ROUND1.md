# SE-1 review: Round 1 consolidation

**Candidate:** `7ff582fa43b4fd16042ccb6f71035e4031b67eac` (`release/se1-funnel-ea8ae4f`). **Baseline:** `ea8ae4f00e80c5c171536293d2df7472fa338c3e`. The original reports are stored separately in [round-1/](round-1/), unchanged, except for three coordinator redactions in R3, which are marked and explained in that file. This consolidation does not replace those reports.

## Reviewer identities and independence limits

| Reviewer | Model | Independence | Limitations |
|---|---|---|---|
| R1, signal logic and parity | Fable 5.1 | fresh context; did not write or see the implementation work; did not see the other reports or the earlier pre-review | same provider (Anthropic), same host and same coordinating session as the implementation; the coordinator wrote the prompts. **Not external.** |
| R2, deployment, operations and rollback | Opus 5.5 | as above | as above. **Not external.** |
| R3, observability, data integrity and tests | Sonnet 5.5 | as above | as above. **Not external.** R3 read production evidence_v2 counts outside the package scope (see the R3 note) |

No genuinely external reviewer (another provider or another organisation) was available in this session. These are three **independent-context** reviews, not three external audits. [REVIEW_PACKAGE.md](REVIEW_PACKAGE.md) lets an external reviewer repeat the audit.

## Verdicts

R1 **CONDITIONAL GO**, R2 **CONDITIONAL GO**, R3 **CONDITIONAL GO**. No reviewer reported a BLOCKER.

## Findings matrix

| ID | Severity | Topic | Corroborated by | Class | Needs code? | Blocks SE-1? |
|---|---|---|---|---|---|---|
| R2-01 | HIGH | version boundary unresolved; same `APP_VERSION` label with a changed `source_hash` → UNDECLARED, which is a STOP | R1 (D: no boundary entry) | safety and governance | no: owner declaration | **yes, until the owner declares it** |
| R2-02 | MEDIUM | the health check can pass on the old container's heartbeat (database-keyed, 180 s) | — | safety (false acceptance) | no: procedure | yes, until the procedure is fixed |
| R2-03 | MEDIUM | the PAPER_HALTED/B3 gate is undefined | — | safety | no: procedure | yes, until it is defined |
| R2-04 | MEDIUM | rollback not pre-staged; the p1d image is not a valid rollback | — | safety | no: procedure | yes, until it is pre-approved |
| R2-05 | MEDIUM | base pinned by a mutable tag; no post-build layer gate | — | provenance | Dockerfile (deploy artefact) | yes, until it is fixed |
| R2-06 | MEDIUM | no pass/fail criterion for content verification (expected 61/2/0/0) | — | provenance | no: procedure | yes, until it is made a gate |
| R3-B3 | MEDIUM | `valid` is true on incomplete cycles; the acceptance gate is insufficient | — | safety (false acceptance) | no: acceptance gate | yes, until the gate is rewritten |
| R3-B1 | MEDIUM | the daily cap is per process, not per UTC day | — | storage bound | optional | no: disclose it, and make a restart count of 0 a gate |
| R3-B2 | MEDIUM | a failed emit loses the record for its series | — | data integrity, visible as `not_recorded` | optional | no: `not_recorded == 0` becomes a hard gate |
| R1-01 | MEDIUM | the selection-changing path is reachable by environment variables alone | — | governance | no: forbid the keys | no: state that the `SELECTION_*` keys are absent |
| R1-02 | LOW | hook call sites unguarded; an injected raise in `health()` flips the heartbeat to failure | — | robustness | optional | no |
| R1-03 | LOW | the `funnel_hooks` import runs after `Database.connect` | R2-07 residual | robustness | optional | no: covered by the dry-run import |
| R2-07 | LOW | restart loop on refusal | R1-03 | robustness | no: dry run | no |
| R2-08 / R2-09 | LOW | build hygiene; post-deploy provenance steps | — | provenance | no: procedure | no |
| R3-B4 | LOW | a backward clock step resets the cap | — | storage bound | optional | no |
| R3-B5 / B6 / B7 / B9 | LOW / INFO | stage order is not sequential; `unattributed` is hard to diagnose; macro-veto flap; idle cycles | R1 (D) on attribution | observability quality | optional | no |
| R3-B8 / R1-06 | LOW / INFO | test gaps (mutant M8 survives, string JSONB, restart, clock skew, full queue); the strategy-id test cannot run on the release | R1-04, closed by R1 for enforce mode | evidence quality | tests only | no |

**Contradictions.** None on safety-critical behaviour. R1 marked latency NOT VERIFIED; R3 measured it (40 to 140 ms) and VERIFIED it. R2 refuted the "55 Python files" count: the real split is 54 `.py` files, plus `/app/Dockerfile` and `requirements.txt`, and all 56 match. This is a documentation error with no safety effect.

**Independently verified by at least one reviewer:**
- signals, statements and messages are identical with recording off and on, and the same as `ea8ae4f` (R1, R3);
- recording adds zero database statements (R1, R3);
- the `LIMIT 200` literal is identical (R1);
- recorder failures do not change decisions (R1, extended with injected faults);
- the image files match `ea8ae4f` (R2: 56/56);
- the overlay copies only the six files, as 1000:1000 (R2);
- Compose targeting touches only signal_engine (R2, against the reviewed blob);
- start-up fails closed before any database I/O (R2).

## Decision on Round 2

Round 2 is **not triggered**:
- no BLOCKER exists;
- the only HIGH finding (R2-01) needs an owner declaration, not a code correction;
- the reviewers do not disagree on safety-critical behaviour;
- no claim that activation safety depends on remains unverified.

The candidate code therefore stays at `7ff582f`, and the three verdicts apply to that exact SHA. Code hardening that the reviewers marked optional (R3-B1, B2 and B4; R1-02 and R1-03) is deferred to the next increment. If any of it is applied before SE-1, the result is a new candidate, and Round 2 is mandatory.

The safety conditions are procedural and live in `deploy/se1-funnel-ea8ae4f/` (README and Dockerfile). Each reviewer's own conditions go back to that reviewer for a closure check. A closure check is not a new code review.

## Provisional recommendation

**CONDITIONAL GO** for `7ff582f`, subject to:
1. closure of R2-01 through R2-06, R3-B3 and R1-01 in the activation procedure, confirmed by the reviewer who raised each one;
2. the owner's version-boundary declaration (R2-01);
3. the specific Class B approvals.

The review is not external. The owner decides whether three independent-context reviews are enough, or whether an external reviewer must repeat the audit from [REVIEW_PACKAGE.md](REVIEW_PACKAGE.md).
