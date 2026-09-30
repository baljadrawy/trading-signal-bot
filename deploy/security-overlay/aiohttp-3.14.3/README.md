# aiohttp 3.14.3 security overlay (reproducible, not deployed)

Normal rebuilds are **blocked**: unconstrained resolution drifts unrelated transitive packages (see AIOHTTP_3_14_3_VALIDATION.md).
This overlay changes only aiohttp on the exact current production image.

- Wheel (not committed; fetch from PyPI and verify): `aiohttp-3.14.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl`
  sha256 `f631fe87a6f30df5fbe6d79640b25e4cffb38c31c7fb6f10871517b84b0f8c1a`, 1,765,282 bytes
- Base: a temporary local tag pointing at the exact production image ID (BuildKit rejects `FROM sha256:<id>`)
- Build: `--network=none --pull=false`; install `--no-deps --no-index` from the verified local wheel only
- Acceptance gates (all required per image):
  1. base tag ID == production image ID; same Python/arch/config
  2. overlay RootFS = production RootFS + exactly 2 layers:
     A (COPY) = only `/tmp/overlay/<wheel>` with matching SHA-256;
     B (RUN) = only aiohttp files, 3.14.3 metadata, 3.13.5 and `/tmp/overlay` deletion markers
  3. package inventory differs ONLY by aiohttp 3.13.5 -> 3.14.3
  4. per-file manifests identical except aiohttp-owned paths and runtime mounts proven by `/proc/self/mountinfo`; `/app` byte-identical
  5. aiohttp 3.14.3 imports, metadata 3.14.3, C extensions and yarl/multidict/propcache load
- Note: the wheel bytes remain in immutable layer A even though removed from the final filesystem; acceptable only because it is a public, hash-verified artifact.
- `ORIG_USER` must equal the base image `Config.User` (all six validated images use `appuser`); if a base has no user, omit the final `USER` line so the image config stays identical.
