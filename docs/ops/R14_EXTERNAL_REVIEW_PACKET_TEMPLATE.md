# R1.4-B External Review Packet — Template

**Status: TEMPLATE ONLY.** No release is certified by this file. A reviewer without server access must be able to inspect source/build evidence and verify a separately authenticated runtime observation. Never copy secrets, private IPs, database data, research evidence or raw environment files into this packet.

## Release identity (all required)
- Release tag: `PENDING`
- Full Git commit SHA (reachable from main): `PENDING`
- Git tree SHA: `PENDING`
- CI run URL and conclusion: `PENDING`
- Reviewed Dockerfile and build-context paths: `PENDING`
- Platform and pinned base image digest: `PENDING`
- Per-service dependency lock path and SHA256: `PENDING`
- Per-service SBOM and image application-file manifest SHA256: `PENDING`
- Image digest and immutable artifact location: `PENDING`
- Build provenance attestation URL, subject digest and verification method: `PENDING`
- Independent source/build review and reviewer identity: `PENDING`

## Runtime observation (separate evidence gate)
- Observation UTC timestamp and freshness policy: `PENDING`
- Host identity verification mechanism (do not publish secrets): `PENDING`
- Signed/safely authenticated attestation and verification instructions: `PENDING`
- Observed service container image digest/ID: `PENDING`
- Observed Compose configuration hash: `PENDING`
- Deep image-content verification scope/result: `PENDING`
- Container health, restart count and identity change evidence: `PENDING`
- PAPER_TRADING and stopped learner verification (redacted): `PENDING`
- Independent operator review and result: `PENDING`

## Decision matrix
- **SOURCE_UNVERIFIED:** source or provenance missing.
- **SOURCE_VERIFIED / BUILD_UNVERIFIED:** source reviewed but canonical CI build or dependency lock absent.
- **BUILD_VERIFIED / RUNTIME_UNVERIFIED:** reproducible build evidence exists but authenticated host observation missing.
- **RUNTIME_PARITY_VERIFIED:** source and build verified, and trusted fresh runtime attestation matches the immutable image digest and configured service. Requires explicit reviewer/operator signoff.
- **BLOCKED:** any inconsistent digest, failed safety check, missing required evidence or unresolved exception.

## Legacy A56 disclosure
The 2026-10-18 legacy baseline is **not** a canonical rebuild. Do not replace PENDING values with guessed values from `main` or `deploy/DEPLOYED.json`. Existing collector image archive gap and assembled scanner provenance remain blockers. This template does not authorize image saving, Docker changes, release publishing or production deployment.
