# R1.4-B dependency locking — governed execution plan

**Status: preparation only, no dependency lock certified.** The five trading services have exact direct requirements but lack committed complete transitive locks. A fabricated lock based on the observed legacy image is prohibited.

## Verified source observations (2026-10-18)
- analyzer and signal_engine declare `aiohttp==3.13.5`, while legacy installed-package evidence records `3.14.3`. Do **not** silently rewrite the historical runtime record or claim equivalence.
- scanner, trade_tracker and telegram declare `aiohttp==3.14.3`.
- All five trading services lack `requirements.lock` in the reviewed R1.4 static audit.
- Collector `p2_forward/requirements.txt` already lists its exact reviewed dependency set and uses `pip install --no-deps`; its OCI revision and independent runtime archive gaps remain.

## Safe implementation gates
1. Choose a single supported target Python and Linux platform for each service and record the build platform; test multiarch separately. Do not infer compatibility from another architecture.
2. In a clean disposable CI environment, resolve each service's committed `requirements.txt` with a pinned resolver version; capture every transitive distribution and hashes where supported. Never generate the lock from a dirty production environment or protected data.
3. Inspect any resolver conflict, especially `aiohttp` for analyzer/signal_engine; propose the smallest reviewed direct-pin change only after proving all imports and dependent services work. No automatic broad upgrades.
4. Commit each reviewed `requirements.lock` with a provenance record: resolver/tool version, Python version, target platform, source requirements SHA256, generation command and resolution timestamp.
5. Install in an isolated environment using the lock with hashes where supported, run `pip check`, compare installed package names and versions exactly to lock, then run service tests and smoke checks.
6. Use `ops/provenance/build_preflight.py` as a **negative readiness gate**; passing it alone is never proof of lock correctness, a canonical image build, or runtime parity.
7. Only then add a separately reviewed canonical CI image build, SBOM, file manifest and immutable digest attestation. No image push or production deploy without separate authorization.

## Stop conditions
Resolver conflicts, platform wheel gaps, failed imports/tests, unreviewed version changes, missing hashes when required, missing evidence, CI failures, or unexpected modifications -> STOP and report. Production images, collector, PostgreSQL, trading mode, research evidence and rollback artifacts remain untouched.
