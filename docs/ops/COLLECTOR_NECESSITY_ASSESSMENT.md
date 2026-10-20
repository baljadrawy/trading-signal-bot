# P2 forward Collector: necessity assessment (2026-10-20)

**Status:** decision framework for the owner (OD-DF-3 in `docs/governance/DEVELOPMENT_FIRST_POLICY.md`). Nothing was started, stopped, changed or deleted. Observations are Class A metadata reads (container state, monitor status, file listings); no dataset content and no Paper outcome was read.

## 0. Owner decision (2026-10-20, recorded after this assessment)

The owner decided to **retain continuous prospective collection**, so option C2 applies instead of the recommended C1. The decision is recorded here; the analysis below is kept unchanged as the decision record.
- **CHG-02 (executed, owner-approved):** the Collector was restarted through the gated script at 2026-10-20T08:26:50Z.
  - New run `d1417a9c686b485b9c56a448e7546b65`, `previous_run = 2cfb872f…`, `restart: "no"` kept, monitor re-bound.
  - The running image is now archived (`~/backups/tsb-p2-forward-images/tsb-p2-forward_p2f-160-1bfb5f6-20261014T0652Z.tar`, checksum verified).
  - Day 2026-10-19 sealed PASS with the downtime recorded. The total gap is 2026-10-19 15:04:55Z → 2026-10-20 08:26:56Z (17 h 22 min), and it is not backfilled.
- **CHG-03 (in development, not installed):** gated automatic recovery after a host reboot (`docs/p2/COLLECTOR_REBOOT_RECOVERY.md` on branch `ops/chg03-collector-reboot-recovery`). It replaces the C2 prerequisite list in section 5 for future reboots. `restart: "no"` stays.

The burden noted in section 3 item 6 is accepted as the cost of continuous collection. The C2 prerequisites in section 5 were met by CHG-02.

## 1. Current state (as assessed before CHG-02)

| Item | State | Class |
|---|---|---|
| Container `tsb-p2-forward-collector` (image `324d52c9`, collector 1.6.0) | `Exited (255)` since the host reboot of 2026-10-19; `restartPolicy=no` by owner decision D3 | VERIFIED |
| Observation gap | starts 2026-10-19 ≈ 15:04:55Z (last health write); ongoing | VERIFIED |
| Dataset `p2-forward-continuous-v1` | 15 closed days 2026-10-04 … 2026-10-18; 14 sealed PASS, 2026-10-06 seal FAILED (recorded incident); 2026-10-19 not closed | VERIFIED |
| Last run `2cfb872f` | no stop marker (unclean stop); a restart needs `P2F_ACK_PREVIOUS` after evidence preservation | VERIFIED |
| Sealed-day backups | local only, `~/backups/tsb-p2-forward/` (daily backup + restore test per day) | VERIFIED |
| Running image archive | **none** for 1.6.0 (only 1.4.0 and 1.5.0 rollback tars) | VERIFIED |
| Monitor (`tsb-p2f-monitor.service`) | running, observe-only; alerts written locally, **no external delivery** | VERIFIED |
| Runbook `docs/p2/CONTINUOUS_OPERATIONS.md` | exists only on the held branch `feature/mi-am4a-stage-b-prep-20261011`, not on `main` | VERIFIED |

## 2. What it is for

The Collector records **forward Binance Spot market microstructure** (best bid/ask and depth streams plus REST metadata) for a tiered universe, sealed per day by an independent verifier. Its documented consumers:

| Consumer | Status | Depends on Collector? |
|---|---|---|
| P2-D1 / P2-H1 protocols (A20–A27) | **HOLD** | yes, but on hold |
| A30 cost assumptions (U4: "measured 2026 tier spread table") | U4 **UNCERTAIN**, not used (OD-2) | possibly |
| A47/A48 level-3 execution calibration (real spreads, queueing) | needs a separately approved forward capture | yes, *if* chosen as the route |
| S4 daily mechanisms M1/M2/M4 (`docs/strategy/S4_MECHANISM_COMPARISON.md`, Draft PR #60) | planning | **no**: daily closes and an approximate spread suffice |
| S4 M3 funding/basis | planning | **no**: needs futures/funding data the Collector does not record |
| Paper Trading | running | **no** (separate network, mounts and Binance feed; A37) |

## 3. Questions answered

1. **Purpose today.** A forward microstructure archive for research protocols that are all on HOLD. No running service and no approved experiment consumes it. (INFERRED from the records above.)
2. **Tasks that genuinely depend on it.** Only real-spread/slippage calibration for spread-sensitive (intraday) strategies, and the held P2 protocols.
3. **Replaceable by public sources?** Not exactly. Binance public data has klines and trades, not historical order-book depth or quotes (`docs/research_temporal_governance.md`: "historical spread is unavailable"). Partial substitutes: the bot's own decision-time `order_book` spread on each candidate (already recorded by the bot), and spreads estimated from trade data. (INFERRED)
4. **Lost by leaving it stopped.** The forward record from 2026-10-19 onwards; it cannot be backfilled (gaps are never stitched).
5. **Does the gap invalidate planned tests?** It invalidates any protocol that requires an uninterrupted window across 2026-10-19 onwards. Gaps are recorded explicitly, so earlier sealed days stay valid. Which held protocols require contiguity is UNKNOWN until they are re-opened.
6. **Operational burden.** High relative to current use: fail-closed incidents and acks, a monitor unit, an hourly seal/backup cron, a manual gated restart after every reboot, ~5 GB of local data, and Binance REST weight shared with the bot's IP.
7. **Is the sealed evidence independently valuable?** Yes: 14 verified, immutable days of forward microstructure. Keep it preserved regardless of the option.

## 4. Options

| | C1 Keep stopped, preserve evidence | C2 Resume later under recovery gates | C3 Replace with a simpler development-data capture |
|---|---|---|---|
| Research value now | none lost for current D0/D1 work | regains the forward record, from the restart onwards only | depends on design; no certified verifier |
| Burden | lowest (INFERRED: the hourly seal job returns `not_ready` for an unclosed day, and only sealed days are backed up) | current burden returns | new code and governance |
| Risk | evidence preserved; no new incidents | restart procedure is known (gated script, `P2F_ACK_PREVIOUS`, monitor re-bind); day 2026-10-19 seal may FAIL and raise a CRITICAL incident, which is expected fail-closed behaviour | duplicate data path, licence and storage questions |
| Approvals | owner records the decision | Class B restart + evidence-preservation copy + (recommended) image archive | data contract and design review |

**Recommendation: C1 now, with an explicit C2 trigger.** Resume (C2) when, and only when, the owner approves a research protocol that needs forward microstructure, for example level-3 cost calibration for an intraday candidate or a re-opened P2-D1. Daily mechanisms do not need it. C3 is not justified: it would rebuild a certified pipeline that already exists.

## 5. If C2 is chosen later (prerequisites, each a separate approval)

1. Archive the running image (`docker save`) with a checksum; R1.3 treats a missing collector archive as blocking certification.
2. Copy the evidence listed in the runbook (control, incidents, quarantine, health, monitor, `docker inspect`, logs), never moving or deleting anything.
3. Start only with `p2f_continuous_up.sh` and `P2F_ACK_PREVIOUS=2cfb872f`, between minute :20 and :40, away from 23:00–01:00Z; re-bind the monitor.
4. Accept: writer heartbeat, a new run record pointing to `2cfb872f`, Paper containers unchanged, then the 2026-10-19 seal result reviewed before any acknowledgement.
5. Independently of C1/C2: consider external alert delivery from the existing monitor (`restart: "no"` stays; `on-failure` would bypass the start gates and, per Docker's documentation, would not restart after a daemon restart anyway).

## 6. Under C1, preserve

- the dataset directory, sealed days and seal reports, the local sealed-day backups and the rollback image tars;
- the hourly seal/backup cron line (INFERRED to write nothing while no new day is closed); any change to it is a separate approval.
