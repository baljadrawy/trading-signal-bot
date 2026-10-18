# Dated corrections to this release record

`IMAGES.md` and the manifests in this directory are an immutable release record, sealed by `SHA256SUMS`. Corrections are appended here; the sealed files are never edited.

## 2026-10-18 (R0): scanner config-hash

- **Original statement in `IMAGES.md`, "Compose" section:** a canonical `-f docker-compose.yml` render of `scanner` would produce a config-hash different from the running one (`e99de276…`), because the scanner was created with an extra override file.
- **Observed 2026-10-18 (read-only):** `ops/compose-safe --project-dir /home/tradmin/trading-signal-bot render-hash scanner` returned `e99de276a5c2…`. This **equals** the running container's `com.docker.compose.config-hash` label. The same held for analyzer, signal_engine, telegram and trade_tracker (5 of 5 matches).
- **Interpretation:** the override sets only `services.scanner.image`, to the same image as the main compose file. The hash prediction was wrong, and the override has no effect on the rendered configuration. The override file itself still exists outside the repository; nothing was changed.
