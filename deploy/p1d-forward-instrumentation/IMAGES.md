# P1-D: forward-instrumentation candidate images (deployment provenance)

- **Source:** develop `59297305f9da51ecdde4cb02740b341bcf832ac5`, tree `a2a38a7577344f665736baf577b20c53d7f8a517`.
- **Built and validated in P1-D1/D2:** 90/90 checks, evidence `p1d12-candidates-20261001T204028Z`.
- **Build:** file-only overlays (COPY layers, no RUN, no network, no pull) on the exact running production images.
- **The recorder ships OFF:** each service sets `EVIDENCE_V2_ENABLED: "false"` explicitly in Compose. Merging this file
  is not a deploy.

| Service | Compose tag | Candidate image ID (immutable) | Parent / rollback image ID | Previous Compose `image:` (rollback) | Overlay files |
|---|---|---|---|---|---|
| trade_tracker | `tsb-p1d-trade_tracker:p1d-59297305-20261001T2045Z` | `sha256:698d31730ec309d416efa3f42f2b1d92cb86bd2360b7d3051c007714ae4bba08` | `sha256:f9d0b39800320de698cb24c445b6a42d2224305327dd43ffde27e4fcadec61fd` | `tsb-cr2-trade_tracker:cr1-d2530888-20261001T1415Z` | `main.py`, `shared/config.py`, `shared/evidence_v2.py` |
| telegram | `tsb-p1d-telegram:p1d-59297305-20261001T2045Z` | `sha256:e5f3096b7a7130f868656171193e50e9c575545d034c5f35182636362eb2065a` | `sha256:e87f00f243e84b29d538b1566974796d2227aa51c30dcee7b0e9f36c23881e5d` | `tsb-cr2-telegram:cr1-d2530888-20261001T1415Z` | `main.py`, `shared/config.py`, `shared/evidence_v2.py` |
| analyzer | `tsb-p1d-analyzer:p1d-59297305-20261001T2045Z` | `sha256:b9b13d957bf47054e9c73c49f64a828f70186d3744fbde5e0b9a2e4dee34d378` | `sha256:47877db4cfe86752d411caf252d4ffa54227c920ebef7188abefefb8fa9fd100` | `tsb-aiohttp-test-analyzer:3.14.3-20260929T124120Z` | `main.py`, `technical_analyzer.py`, `shared/config.py`, `shared/evidence_v2.py` |
| signal_engine | `tsb-p1d-signal_engine:p1d-59297305-20261001T2045Z` | `sha256:80096a981b2e68a2ab56de6c9725e6288d0a7b3b9fb595e64699cae48aa37fa2` | `sha256:04df5dd8267f7d4b1999a32e1d39e7eb47f1a981e2ba47139031ef43d853d7b3` | `tsb-cr2-signal_engine:cr1-d2530888-20261001T1415Z` | `main.py`, `signal_logic.py`, `shared/config.py`, `shared/evidence_v2.py` |

Compose pins the local tag, because Compose cannot pull or verify a bare image ID. **D4 must prove tag → ID equality
immediately before each recreate; any mismatch is a hard STOP.**

## Evidence directory
- Each service writes `/app/data/evidence_v2/<service>/events-<UTC-day>.jsonl` plus `_recorder_stats.json`
  (temp file + atomic rename) only inside its own subfolder. There is one writer per file and one fixed container per
  service, so one shared host folder is safe.
- The mount is `./data/evidence_v2:/app/data/evidence_v2`, read-write, on all four services. Nothing is written while
  the recorder is OFF.

## D4 pre-cutover host procedure (owner-authorized; not done in D3)
Run from `/home/tradmin/trading-signal-bot`, before any recreate:
```bash
test ! -e data/evidence_v2 || ls -A data/evidence_v2      # must be absent or empty
install -d -m 0750 -o 1000 -g 1000 data/evidence_v2       # uid 1000 = appuser in the images
stat -c '%u:%g %a' data/evidence_v2                       # expect 1000:1000 750
df -h --output=avail .                                    # expect ample free space
```
If Docker created the folder instead, it would be owned by root and unwritable by the containers. The folder lies
inside the production directory, which is the intended local-backup boundary (D6).

## D4 order and per-service gate
**Order:** trade_tracker → telegram → analyzer → signal_engine. These are the downstream consumers of
signal_engine → `signal.ready` → telegram → trade_tracker first, and the producers last. With the recorder OFF, no
service changes behaviour.

For each service:
1. Verify the tag resolves to the candidate ID above.
2. Run `docker compose -p trading-signal-bot -f docker-compose.yml up -d --no-deps --no-build --pull never --force-recreate <svc>`.
3. Health checked twice (65 s apart), restart count 0, the expected image and config hash.
4. Bounded logs with 0 errors.
5. No `evidence_v2` block in the heartbeat, and the evidence folder still empty.
6. No `pit` or `identity` written.
7. B3 and PAPER_HALTED exact; event flow intact.
8. All other containers unchanged.

Any anomaly: stop before the next service.

## Rollback (no rebuild)
Per service, re-pin the previous `image:` reference above (the parent image is present locally) and recreate only
that service with the same command. Parent images must not be pruned.

## Recorder activation (forbidden until)
1. D4 succeeds.
2. D5 OFF-mode observation succeeds.
3. A recurring local backup of `trading_signals` exists.
4. `data/evidence_v2` is included in the backup.
5. An isolated restore is verified.

Then activation needs a separate owner authorization and its own reviewed Compose change.
