REVIEWER 2 CLOSURE CHECK (model: Claude Opus 5.5), procedure at 78ba705. The candidate is unchanged at 7ff582f.

Three questions you asked:

- **Layer gate:** 26 is correct. The base has 24 layers (checked by image inspect). Only the two COPY instructions add layers; ARG and LABEL change only metadata. The precedent shows the same pattern: tsb-obs-telegram has 21 layers on top of the 19 of its base, and its first 19 layers equal the base's (checked).
- **Digest FROM with --pull=false:** this daemon uses the containerd image store. The image has a `Descriptor`, and its ID is the manifest digest. `docker image inspect tsb-a561-signal_engine@sha256:c5be4e34…` resolves locally (checked). Whether BuildKit resolves it the same way is only proven by running the build. A resolve failure aborts the build because `--network=none` blocks any registry fallback, so the risk fails closed. ACCEPTED-AS-RESIDUAL.
- **Rollback, health and B3:** covered under R2-02 to R2-04 below.

Findings:

- **R2-01: OPEN.** README:85-98. The owner has not declared the boundary. The template (line 9) also requires a byte-identical golden replay for a PATCH boundary. README:89 cites the 25-seed parity tests, but nothing shows they count as that replay. The owner must accept them as the replay or declare MAJOR.
- **R2-02: CLOSED.** README:130-132.
- **R2-03: CLOSED.** README:121 says "a named read-only query" but the query itself is not written down. The exact SQL must be fixed in the gated package before the step runs, and it needs owner approval for the database read.
- **R2-04: CLOSED.** README:158-162 (target blob `d1a4b197…`, config-hash `20dcae19…`, p1d excluded). Residual: after a rollback, production no longer matches main HEAD, so a revert commit on main is needed for parity.
- **R2-05: CLOSED.** Dockerfile:9; README:107, 111-112.
- **R2-06: CLOSED.** README:113, 135.
- **R2-07: CLOSED.** README:114.
- **R2-08: CLOSED.** Dockerfile:5-8; README:112. File modes that depend on the export umask, and recording the Dockerfile's own commit (78ba705), are ACCEPTED-AS-RESIDUAL.
- **R2-09: CLOSED as a plan.** README:165-170.

The verdict stays CONDITIONAL GO. The only open condition is R2-01, the owner's boundary declaration together with the golden-replay decision.
