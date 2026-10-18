# Runtime ↔ GitHub parity audit (read-only)

**Status: UNVERIFIED until evidence from the actual runtime host is reviewed.**

GitHub main at audit initiation: `0e5f5866c23b28795c6e33824fb3c5c406c7bfc7`. This is a reference, **not** evidence that the runtime uses this commit.

## Collect on the real runtime host
Run from the deployed repository checkout, if one exists:

```bash
bash ops/audit/collect_runtime_parity.sh /tmp/runtime-parity-evidence
```

This script only reads git metadata and Docker container/image identities; it does not restart containers, change images, read environment variable values, export credentials, or deploy. Treat output as internal operational metadata and review before sharing. If the runtime is not a Git checkout, commit parity is UNVERIFIED until deployment provenance is obtained. If Docker is inaccessible, image parity is UNVERIFIED.

## Evaluation gates
1. Confirm runtime host and service scope (scanner, analyzer, signal_engine, trade_tracker, telegram, and collector if in deployment scope).
2. Compare actual deployed commit / immutable source provenance against GitHub main; check tracked worktree modifications and any bind-mounted source.
3. Compare image IDs and immutable digests against CI build provenance; a Docker tag or local image ID alone does **not** prove the image was built from the same commit.
4. Compare actual installed dependency versions and hash-locked manifests; this collector intentionally does not exec into containers.
5. Compare deployment configuration keys and **redacted** canonical fingerprints, never secret values; account for secrets and non-reproducible settings.
6. Report per service: MATCH only if source, dependency, image, configuration and deployment provenance all verified; DRIFT on proven mismatch; UNVERIFIED if evidence is missing.

**STOP:** no merge, restart, production change, experiment, or trading action is authorized by this audit. No inference of parity from CI success.
