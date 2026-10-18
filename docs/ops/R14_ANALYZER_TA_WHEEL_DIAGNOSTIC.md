# R1.4-E — analyzer ta==0.11.0 source-wheel diagnostic

**Status: diagnostic only; no dependency lock, build image or runtime parity is certified.**

## Evidence and question
R1.4-D workflow run [39157330293](https://github.com/baljadrawy/trading-signal-bot/actions/runs/39157330293) had 4/5 successful candidate jobs. The analyzer failed because `pip --only-binary=:all:` could not find a wheel for the unchanged direct pin `ta==0.11.0` on the Ubuntu 24.04 / Python 3.12 Linux x86_64 disposable runner. This is a **distribution-format blocker**, not evidence of a failing analyzer runtime.

## Scoped experiment
A manually dispatched `r14-analyzer-ta-wheel-diagnostic` workflow checks the unchanged direct pin, records source commit, requirements checksum, Python/pip/platform versions, downloads precisely the `ta==0.11.0` source distribution, records its SHA256, builds exactly one `ta` wheel inside an ephemeral CI runner and records wheel SHA256. The job then attempts a full analyzer **dry-run** resolution with the locally built wheel, retaining the original requirements pins, and uploads evidence even on failure.

**Trust warning:** source-wheel builds execute third-party package build code and download build dependencies. Use the dedicated disposable, short-lived runner with read-only repository permissions, no credentials, no protected files, no persistent cache. The resulting artifact is **not** an automatically trusted wheel. Independently review the source, package license, provenance, build dependencies and hashes before any production use. No wheel is committed or published by this test.

## Gates
1. Stop and document if the sdist cannot be acquired, is unexpectedly named, build fails, or another transitive conflict occurs.
2. Inspect logs, sdist and built wheel hashes; review ta metadata and build code, and determine a pinned/reproducible build-toolchain proposal.
3. Next proposed PR must use reviewed immutable inputs, hash-verified dependency locks, isolated installs, `pip check`, exact inventory and analyzer smoke tests; no automatic direct-pin changes.
4. A successful dry run is not equivalent to installation, import testing, canonical OCI images, or runtime parity.

Production deployments/restarts, production database, collector, protected scientific evidence, trading activation, image publication and merge into main remain independently gated.
