# `.env.example` review: 2026-10-18 (record only; nothing changed)

**Scope.**
- Reviewed: the tracked template `.env.example` at develop `28d9f9a` (blob `git rev-parse 28d9f9a:.env.example`).
- Compared against: the `os.getenv`/`os.environ.get` defaults in the service source directories, and the `${...}` interpolations in `docker-compose.yml`.
- **No production `.env` was opened.**

**Secrets: none.** Every credential key holds a placeholder (`your_…_here`):
- `BINANCE_API_KEY` / `BINANCE_API_SECRET`;
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`;
- `ANTHROPIC_API_KEY`;
- `POSTGRES_PASSWORD`;
- `GOOGLE_DRIVE_FOLDER_ID`.

**Outdated or misleading entries.** None of these is changed here; correcting them needs separate owner approval.

| Key | Template | Finding |
|---|---|---|
| `POSTGRES_USER` | `trading_bot` | The deployed role is `trading_signal_bot` (`CLAUDE.md`), and most code defaults use `trading_signal_bot`. Misleading. |
| `MIN_SCORE_TO_SIGNAL` | `7` | Code default is `5`. Live thresholds come from the DB (`optimizer_settings`), which overrides `.env`. Misleading. |
| `RISK_CANARY_MAX_OPEN_TRADES` | `2` | Code default is `1`. Misleading. |
| `TIMEFRAME` | `4h` | Same as the code default. The strategy history records 4h as no longer a primary timeframe. Whether this key still drives anything: UNVERIFIED. |
| `ANTHROPIC_API_KEY` | placeholder | Still read by `shared/config.py`, which is inside the running images. `claude_review` is retired (CR-2). Whether any running path still uses the key: UNVERIFIED. |
| `GOOGLE_DRIVE_FOLDER_ID` | placeholder | Not read by any running service (Colab training only, obsolete). |
| `LIVE_LEARNING_MODE` | **absent** | `docker-compose.yml` interpolates it without a default (service `continuous_learner`, profile `learner`, retired). The template is incomplete for that service. |
| `MAX_SIGNALS_PER_DAY` | `5` | Same as the code default. `docs/claude/troubleshooting.md` says a low cap stops the bot. Keep the documentation consistent. |

**Related finding (not in `.env.example`).** A hard-coded, real-looking `POSTGRES_PASSWORD` fallback exists in tracked research scripts, for example `analyzer/backtest_part18_indicator_combos.py:20`. This is the A60 HIGH finding.
- The value is **not** in any running image: `deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json` has no such blob.
- It is already in GitHub history. Rotation needs the separate credential-rotation plan; deleting the file would not be enough.
