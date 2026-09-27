# Deployed production baseline — 2026-09-27

This branch (`deploy/baseline-2026-09-27`) is based on the B3 commit
`8bfca778b42fa5c29993d5c57bf1674ae755522f`. It records **what was actually running** on the
production host on 2026-09-27. It is a record, not a build recipe.

- Execution mode: **PAPER_ONLY**. Live trading is forbidden.
- Trading state: **HALTED** (`risk:loss_streak_halt`, decision id 29415).

## Reproducibility: NOT PROVEN
The running images were produced by different builds and by single-file overlays (B3). The scanner
and claude_review images contain files that match no git commit (see below). No clean rebuild from
this branch has been performed or compared, so **do not assume** that `docker compose build` on this
branch reproduces the running images.

## Files
| File | Content |
|---|---|
| `DEPLOYED_MANIFEST.json` | Per service: image ID, image reference, start time, file counts by matching commit, files matching no commit, SHA256 of the non-secret configuration; image tags and rollback anchors |
| `deployed_files.json` | Every deployed source file (190 across 7 containers): path under `/app`, SHA256, size, git blob id, matching commit, and whether it exists anywhere in git history |
| `config/<container>.nonsecret.json` | Resolved runtime configuration **excluding** any field whose name looks secret (keys, tokens, passwords, URLs, IDs, hosts, users, chat IDs, and similar) |
| `unmatched/<container>/app/…` | Byte-exact copies of the three deployed files that match no commit. They are evidence only and are not importable by any service |

`source_commit` is the first commit in the order 8bfca77 → 05999ea → 63da7d3 → c4a623c → 7bf6214 →
605a962 → 14fc775 → c4cae2b whose version of that path is byte-identical to the deployed file.
Most files report `8bfca77` simply because they are unchanged since earlier commits.

## Services (images as running)
| Container | Image ID | Notes |
|---|---|---|
| trading_scanner | `9b0b53a6a799` | B3 overlay; the shared modules come from 7bf6214/c4a623c; `shared/telegram_messages.py` matches no commit (not imported by the scanner) |
| trading_analyzer | `ce305ecd7760` | 63da7d3 strategy code; ships the pre-B3 `trading_state.py`, which it does not call |
| trading_signal_engine | `b3d4b6236654` | 63da7d3 |
| trading_tracker | `2b59c6a164c0` | B3 overlay; everything matches 8bfca77 |
| trading_telegram | `b84d3d1528a0` | B3 overlay; everything matches 8bfca77 |
| trading_claude_review | `8bca25750c77` | Auto-approve policy; `shared/schema.py` (REQUIRED_SCHEMA_VERSION=5) and `shared/learning_governance.py` match no commit |
| trading_continuous_learner | `d1aa69bde63f` | **Stopped since 2026-08-17** by decision (fixed-policy window) |

## Rollback anchors
| Tag | Image ID |
|---|---|
| `b3-rollback/scanner:pre-b3` | `4d59ba3d6e79` |
| `b3-rollback/telegram:pre-b3` | `fb0ef1b9097a` |
| `b3-rollback/trade_tracker:pre-b3` | `c60cac87920a` |
| `trade_tracker:pre-risk1-rollback` | `d291f64e0795` |
| `telegram:pre-risk1-rollback` | `ab4bc1077b6c` |

The full image IDs are in `DEPLOYED_MANIFEST.json`. An archive of every listed image exists in the
encrypted local backup (Phase 0, 2026-09-27); it is not stored in git.

## Not recorded (by design)
Runtime `.env` values, container environment variables and compose `config-hash` labels. Those hashes
depend on secrets.
