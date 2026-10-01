# CR-2: signal.ready production image provenance

A **provenance record**, not an execution script. It records the images that `docker-compose.yml` pins for the
CR-2 cutover to the Option 3 `signal.ready` contract (PR #8, merge `d253088880675d946138c998de794d851d847429`).
Recorded 2026-10-01.

**Scope:** trade_tracker, telegram, signal_engine. Scanner, analyzer and every other service are unchanged.

## Mechanism
- **File-only overlay** on the EXACT image each service was running before CR-2. There is no `RUN` step, no package
  install and no base refresh. Build flags: `--pull=false --network none --provenance=false --sbom=false`.
- Each candidate adds exactly 2 layers. Each layer is one `COPY --chown=1000:1000` of a file taken byte-for-byte from
  merge `d2530888`:
  - the service's changed module;
  - `shared/signal_readiness.py`, mode 664.
- Dockerfile per service, where `<file>` is the changed module and `<mode>` is its git mode:
  ```
  FROM <base tag below>
  COPY --chown=1000:1000 --chmod=<mode> <file> /app/<file>
  COPY --chown=1000:1000 --chmod=664 signal_readiness.py /app/shared/signal_readiness.py
  ```
- **Acceptance gates**, all passed for every image. The candidate was compared with the running container before CR-2:
  - base RootFS layers are an exact prefix, plus exactly 2 layers;
  - the image `Config` is identical: Env, Cmd, Entrypoint, User, WorkingDir, Healthcheck and Labels;
  - the new layers contain only the 2 intended regular files plus their existing parent directories (1000:1000, 755);
  - there are no links and no whiteouts;
  - Python 3.12.13, the interpreter binary, the stdlib (820 files) and the package inventory are identical (aiohttp 3.14.3);
  - every other `/app` file is byte-identical to the running container;
  - for each changed `/app` file, the production copy was byte-identical to its develop@55a29012 blob before CR-2. The
    overlay therefore applies exactly the reviewed CR-1 diff and nothing else.
- **Platform:** `linux/arm64`. Each image ID is a single-platform OCI image manifest digest (no index).

## Images

| Service | Compose `image:` reference (exact) | Immutable image ID | Base (rollback) reference | Base image ID | Files added |
|---|---|---|---|---|---|
| trade_tracker | `tsb-cr2-trade_tracker:cr1-d2530888-20261001T1415Z` | `sha256:f9d0b39800320de698cb24c445b6a42d2224305327dd43ffde27e4fcadec61fd` | `tsb-aiohttp-test-trade_tracker:3.14.3-20260929T124120Z` | `sha256:af063314973ee6f4f988903c9836a91b30b4f3343cb68db8587bd41580b179c3` | `/app/main.py` (664), `/app/shared/signal_readiness.py` |
| telegram | `tsb-cr2-telegram:cr1-d2530888-20261001T1415Z` | `sha256:e87f00f243e84b29d538b1566974796d2227aa51c30dcee7b0e9f36c23881e5d` | `tsb-aiohttp-test-telegram:3.14.3-20260929T124120Z` | `sha256:ef80d11c657967ad21318685eab8ef41cbc08ac7002d06bb8f825960e6bee4f1` | `/app/main.py` (775), `/app/shared/signal_readiness.py` |
| signal_engine | `tsb-cr2-signal_engine:cr1-d2530888-20261001T1415Z` | `sha256:04df5dd8267f7d4b1999a32e1d39e7eb47f1a981e2ba47139031ef43d853d7b3` | `tsb-aiohttp-test-signal_engine:3.14.3-20260929T124120Z` | `sha256:4b7f4a58073abf05e4298dd70d64d6df6c5667be7e1f464c4623ba133f57f957` | `/app/signal_logic.py` (775), `/app/shared/signal_readiness.py` |

## Local archives (`docker save`, OCI layout; kept on this host only)

| Service | SHA-256 |
|---|---|
| trade_tracker | `2684dd311bc494a7591e248b92be8eab515012739a1fae3972d33d5eb490cbeb` |
| telegram | `3a2eebbc2695393c4384eab10cde35ffcc2e64e0e523af7f3131c2f48edf81e3` |
| signal_engine | `f6b23a2ffbbd70c52229e743bb92f02bfce2bbf11050bee202e31918f63580d5` |

## Deployment order and rollback
- **Order:** trade_tracker, then telegram, then signal_engine.
  - Consumers that understand `signal.ready` must exist before any producer emits it.
  - The new telegram and trade_tracker still accept the legacy `signal.reviewed` + `claude_approved` path.
- **Rollback (per service):** pin the base reference above again and recreate only that service with the gated Class B
  command (`docs/ops/COMPOSE_OPERATIONS.md`).
- **Rollback (whole contract):**
  - restore the pre-CR-2 Compose (blob `016aaf9fbf6db95b7b0edcd837057a35f6dc4dc6`);
  - recreate signal_engine first, so `signal.created` is emitted again;
  - restore claude_review;
  - telegram and trade_tracker may stay on CR-2 images, because they dual-accept the legacy path.
- No DB migration is needed in either direction. **Merging this file is not a deploy.**
