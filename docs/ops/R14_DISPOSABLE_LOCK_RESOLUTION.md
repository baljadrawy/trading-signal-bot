# R1.4-D — disposable dependency-resolution evidence

This phase produces **review-only candidate files**, not committed or certified `requirements.lock` files. It does not build containers, install service dependencies, touch production, access research evidence, or activate trading.

## Procedure
1. Review this PR and its normal test gates before merging.
2. From the reviewed commit on main, manually dispatch `r14-disposable-lock-candidates`. Its five independent jobs use disposable Ubuntu 24.04 / Python 3.12 runners and a wheel-only pip dry run. A resolver failure is evidence of a blocker, not permission to relax direct pins.
3. Download each job's 14-day artifact and review the pip report, exact pins, Python/pip/platform/source-commit record and SHA256 provenance. Artifacts must never be accepted from untrusted or unexpected runs.
4. In a separate reviewed change, establish pinned resolver tooling and a reproducible target platform; capture immutable wheel hashes, run isolated installation with hashes, `pip check`, exact installed inventory comparison, service smoke tests, and security review. Only after these gates can complete `requirements.lock` files be proposed.
5. The pre-existing `r14-build-readiness` workflow **expects locks to be missing** and must be updated before merging actual locks. Passing its current negative gate is not build readiness.

## Fail-closed limitations
- The pip resolution is time-sensitive and not yet reproducible: the workflow uses the runner's installed pip and live package indexes. The recorded pip version and source commit make this visible, but do not solve it.
- Candidate lock files are exact name/version listings, **not hash-locked** and not proof of transitive completeness on every platform.
- `aiohttp` direct pins are preserved: analyzer/signal_engine 3.13.5; scanner/trade_tracker/telegram 3.14.3. Never infer compatibility with legacy runtime 3.14.3 from resolver success.
- Wheel-only restriction prevents an unreviewed sdist build. Any absent wheel or resolver conflict is a STOP, not a reason to change requirements automatically.
- No OCI build, image push, runtime attestation, deployment, or protected experiment is authorized by this workflow.
