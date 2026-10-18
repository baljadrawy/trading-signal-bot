# R1.4-F — analyzer isolated install validation

**Status: evidence-gathering only. No lock, canonical image, or production runtime parity is certified.**

## Verified basis
R1.4-E run [39159452766](https://github.com/baljadrawy/trading-signal-bot/actions/runs/39159452766) downloaded `ta==0.11.0` sdist, built a wheel and successfully dry-run-resolved analyzer requirements on Ubuntu 24.04 / Python 3.12 x86_64. It did **not** install the service dependencies or smoke-test imports.

## What this PR adds
A **manual-only** disposable GitHub Actions workflow that:
- Asserts unchanged analyzer pins `ta==0.11.0` and `aiohttp==3.13.5`.
- Captures source commit, platform, Python/pip versions, requirements and source/wheel SHA256.
- Builds a local ta wheel from the exact sdist in a disposable runner.
- Installs analyzer dependencies into a temporary virtual environment using binary-only distribution policy plus the local ta wheel; executes `pip check` and direct dependency import smoke.
- Captures pip installation report and installed inventory, and verifies that reported installed distributions have the expected versions.
- Uploads evidence even on failure.

## Limitations and STOP gates
- **Third-party build code runs in the disposable CI runner.** Treat source and built wheel as untrusted pending review. The runner has read-only repository permissions, no protected data, no long-lived cache or image publishing.
- Resolver/build-tool versions and index responses are not frozen. Wheel hash may change; this workflow does not assert reproducibility or a trusted upstream checksum.
- The inventory check verifies presence and version of resolved packages; it does not assert that the installed environment has no extra packages. It does not compare against a committed transitive hash lock.
- Import smoke is **not** full analyzer application testing, nor scientific strategy validation.
- A failed wheel build, dependency conflict, `pip check`, import smoke, or inventory comparison blocks advancement. Do not auto-upgrade direct pins or waive failures.
- No production deploy/restart, protected research data access, database modification, image build/push or trading activation is authorized.

## Follow-on
After a successful run and independent artifact review: pin resolver/build toolchain and source hashes, build deterministic wheels, capture complete transitive hash locks, run clean installs and exact inventory equality, and only then consider canonical OCI builds and runtime attestation under separate review.
