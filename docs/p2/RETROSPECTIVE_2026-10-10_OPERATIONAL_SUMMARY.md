# 2026-10-10 conn0-book outage: operational summary for data-quality governance

This is the minimum operational record needed to govern data quality. It was extracted, metadata only, from the local retrospective record. The scientific branch was **not** merged or released.

- **Source:** `docs/audits/2026-10-12/a35_results/RETROSPECTIVE_INCIDENT_2026-10-10.md` on the held local branch `feature/mi-am4a-stage-b-prep-20261011` (commit `c4a5605`).
- **Source sha256:** `8ccaad698f5874b046513753f03b9fa3ce206aa8fbcf45aacb21b4a699d874f1`. This equals the `record_sha256` in the filed incident `inc-1791973646419-2cfb872f-1`.
- **Deliberately excluded:** the source's timeline and its per-stream loss figures (stream timing and counts), and any outcome or holdout information. The dataset's own gap records are the authoritative source for exact windows.

## Facts

| Field | Value |
|---|---|
| Date | 2026-10-10 (one bounded episode of tens of minutes) |
| Dataset / run | `p2-forward-continuous-v1`, boot `2e12ddce`, collector `p2cr-collector-1.5.0` |
| Connection | `conn0-book`: book-ticker streams, including Tier-0, plus the market mini-ticker array. The depth connection was also disrupted at the same time |
| Incident | filed 2026-10-14 as external WARNING `inc-1791973646419-2cfb872f-1` (original assessment CRITICAL; filed as WARNING because it is historical and remediated). **Unacknowledged** |
| Confirmed cause | a collector 1.5.0 recovery defect. A forced reconnect awaited an unbounded aiohttp graceful close, and later forced reconnects were no-ops while the socket stayed reported as connected. Reproduced locally |
| Not confirmed | the upstream trigger (the simultaneous disruption of both sockets suggests a gateway or network-path event), and how much of the loss was Collector-side discard during the close wait |
| Detection gaps (then) | no incident rule for a connection that is up but silent; the watchdog's forced reconnect was not checked for effect |
| Corrective release | `p2cr-collector-1.6.0`: commit `1bfb5f6`, image `sha256:324d52c9…`, **deployed 2026-10-14T10:26:32Z**. It adds a bounded session end (≤ 7 s), generation ownership and wedge replacement, plus the incidents `conn_outage`, `conn_recovery_failed` and `observation_loss:tier0`. The source record predates deployment and still says "not deployed"; that is now superseded |

## Data-quality implications (separate from operational health)

1. The lost observations are **irreplaceable**. The affected windows exist in the dataset as gap records.
2. Any analysis or confirmation that uses forward data covering 2026-10-10 must apply an exclusion or flagging rule fixed **before** any look. That rule must use the dataset's gap records, not this summary.
3. Because the Collector-side discard fraction is unknown, the episode must not be treated as a pure upstream gap. It is a Collector-defect window.
4. The same failure class is now bounded and incident-latched. Later short losses appear as `observation_loss:tier0` (recurring 2026-10-14 to 2026-10-20, WARNING) and need the same pre-declared rule.

## Remaining operational risks

- The upstream trigger is unknown and may recur.
- Outages still lose observations, though they are now bounded and visible.
- The research-watchdog coupling is unchanged (A33 R4, pending).

## Disposition

The incident stays unacknowledged until the owner accepts this summary as the main-branch record. Acknowledging it then removes only the WARNING latch. The incident, the ack and this record stay in history.
