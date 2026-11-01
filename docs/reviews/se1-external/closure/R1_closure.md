REVIEWER 1 CLOSURE CHECK

Candidate unchanged: `release/se1-funnel-ea8ae4f` and `7ff582f` resolve to the same SHA (verified). Closure commit 78ba705 touches only `deploy/se1-funnel-ea8ae4f/{README.md,Dockerfile}` plus review docs.

- **R1-01 (MEDIUM, dormant selection path) — CLOSED procedurally.** README @78ba705 line 97: `SELECTION_POLICY`, `SELECTION_VERSION`, `SELECTION_SCORE_KEY` "absent and forbidden" in the version-boundary record; line 114: the dry run must run with "no `SELECTION_*` keys"; line 117: Compose block "No `SELECTION_*` keys". The Dockerfile @78ba705 lines 9-14 adds no env, so the path stays inert unless Compose introduces a key, which the procedure now forbids. The code path itself remains in the image — residual, acknowledged.
- **R1-02 (LOW, unguarded hook call sites) — ACCEPTED-AS-RESIDUAL.** Deferred as optional hardening (CONSOLIDATION_ROUND1.md lines 33, 61). No code change; the exposure is the trivial-body `health/note/start_decision` calls only. Acceptable for a 24-hour observe window.
- **R1-03 (LOW, hooks import after `Database.connect`) — ACCEPTED-AS-RESIDUAL, mitigated.** README @78ba705 line 114: a disposable, no-network, read-only dry run must import `shared.funnel_hooks` and call both start-up parsers from the built image with the exact production flags. This catches an import failure before any recreate; the ordering in `main.py:123-126` is unchanged.
- **R1-04, R1-05 — CLOSED** (evidence/informational; no action required).
- **R1-06 (INFO, strategy-id test) — CLOSED.** README @78ba705 line 83 records that the test cannot run on the release export and is deselected there.

**Verdict for 7ff582f: unchanged — CONDITIONAL GO**, with the conditions now satisfied by the activation procedure at 78ba705. Any code change to the six files before SE-1 would require Round 2.
