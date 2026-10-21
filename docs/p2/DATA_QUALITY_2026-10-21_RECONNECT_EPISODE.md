# Data-quality record: 2026-10-21 WebSocket reconnect episode

This record is documentation only. No dataset was excluded, modified or re-certified. No stream payload, forward-holdout outcome or protected evidence was read. All figures come from Collector operational metadata: health, incident state, lifecycle WS events, and container and network counters.

## 1. Connection incident (operational)

| Field | Value |
|---|---|
| Interval (UTC) | **2026-10-21 13:34:59 → 16:41:55** (≈ 3 h 07 min); first and last WS disconnect |
| Connections | `conn0-book`: 193 disconnects. `conn1-depth`: 58. Both stopped within 21 s of each other, with no Collector restart, redeploy or configuration change |
| Session pattern | `conn0-book` median session 48–70 s (min 13 s, max ≈ 2 min). All ended as `ws_disconnected`; 0 `connect_failed`; 25 `subscribe_timeout`; 0 `data_stall`; no `serverShutdown` |
| Local indicators | inside the Collector network namespace: TCP retransmissions ≈ 0, connect failures 0, timeouts 0, receive-queue drops 0; event-loop lag ≤ 193 ms; container CPU ≈ 3 % |
| Health | DEGRADED for the whole interval (Docker `unhealthy`). No CRITICAL: `conn_recovery_failed` measures only continuous outages and never fired |
| Cause | **probable but unconfirmed:** remote endpoint or gateway closes. The Collector does not record close codes. Post-episode probes of `data-stream.binance.vision:443`, `stream.binance.com:9443` and `stream.binance.com:443` were all healthy (baseline only, not a reproduction) |
| Recovery | spontaneous. HEALTHY since about 16:42Z and still stable at 18:18Z |

## 2. Observed data gaps (dataset facts, not eligibility)

- Repeated short gaps across book-ticker, depth and market streams, including Tier-0. They are recorded **in the dataset itself** as gap records (gap opened, gap closed, awaiting post-reconnect readiness). Those records are authoritative; this document copies no windows or counts from them.
- The latched WARNING incident `observation_loss:tier0` (`inc-1791981120021-2cfb872f-2`) went from count 10 to **52** during the interval; the last occurrence was 16:42Z. It stays **unacknowledged**.
- Sealing continued normally: the writer and certifier were alive throughout, with 0 certification failures.

## 3. Scientific dataset eligibility (decision pending; not made here)

- No eligibility decision is taken in this record. Any use of forward data covering 2026-10-21 must apply a rule fixed **before any look**. That rule must:
  1. derive excluded or flagged windows from the dataset's gap records (and the lifecycle WS events), never from this summary;
  2. define a coverage threshold per stream tier (for example, minimum Tier-0 coverage per hour or day) and the action taken below it (exclude the window, exclude the day, or flag);
  3. be applied identically to every comparable episode: 2026-10-06, 2026-10-10, the recurring Tier-0 losses of 10-14 to 10-20, and this one.
- The coverage rule and its thresholds are an owner and independent-review decision (review package A, section A3).

## 4. Follow-ups (each needs its own approval)

- Collector observability (Draft PR): `ws_session_end` metadata and a `conn_flapping` episode incident, both off by default. Deploying them is a separate Class B change.
- Prospective coverage and exclusion rule: a written proposal, then owner approval.
