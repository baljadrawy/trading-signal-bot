# P2F rotation / sequence-continuity repair (collector 1.5.0)

Branch `fix/p2f-rotation-seq-continuity-20261007`, from `feature/g4-monitor-supervision-20261007@2526338`.
Not merged, not deployed. This note supersedes rotation behaviour **prospectively only**. Historical records,
incidents, seals and earlier evidence are not rewritten.

## 1. Incident record (2026-10-07, boot `b1b7edb6`)

- 00:10:09.007Z: a universe transition rotated both connections. DOGE, ENA and PUMP were unchanged by it.
- `rotate()` closed the old socket as soon as the replacement delivered its first DATA message, right after the
  SUBSCRIBE ack (conn0: first message .571, old socket closed, `ws_rotation` logged at .572).
- The `cb99c05` overlap flag (`cname in self.rotating`) was therefore true for about 1 ms.
- The replacement socket TRAILED the old one. It re-delivered older `dogeusdt` / `enausdt` / `pumpusdt@bookTicker`
  updates. With the overlap flag false, 20 consecutive older updates were classified as an exchange-side reset:
  - `seq_reset` at .654, .655 and .889;
  - DEGRADED latched incident `inc-1791331810668-b1b7edb6-2`;
  - `seq_regression` counter 131.
- Each accepted reset sequence lies strictly between the neighbouring persisted samples. This was not an exchange
  id-space reset.
- Persisted data shows no loss or corruption: monotone `exchange_seq`, segment SHA-256 values and index counts
  verified. Absence of loss cannot be proven, because the old socket's final per-stream sequence was never recorded.
- Evidence: `backups/tsb-aiohttp-20260929T122701Z/seq-reset-investigation-20261007T081541Z/`.

## 2. What earlier evidence got wrong (recorded, not rewritten)

- `cb99c05` ("continuous-mode overlap regressions ignored") covered only older messages that arrive while the old
  socket is still open. That window ends at the replacement's first message. The fix's test set `overlap=True` by
  hand and never exercised the real `rotate()` timing.
- The 2026-10-05 and 2026-10-06 transitions produced 45 and 126 regressions, each below 20 per stream run. The +36 h
  review called them "benign overlap" on the premise that `cb99c05` covered them. That premise was wrong. They were
  the same trailing-replacement mechanism, which simply had not yet reached 20 in a row on one stream. That
  classification was too confident.
- Latent hazard (not observed in persisted data): a false `seq_reset` ACCEPTS the older value. Had a sample boundary
  fallen between that acceptance and the replacement's catch-up, a decreasing `exchange_seq` would have been
  persisted. The day seal would then have failed with `SEQ_DECREASING`.

## 3. Exchange semantics used

- bookTicker `u` and partial-depth `lastUpdateId` are per-symbol order-book update ids. They are monotonic but
  sparse: not every id is pushed. A forward jump is normal and carries no gap information. Data loss can only be
  seen in time (stale stream / connection gaps), never in id contiguity.
- `!miniTicker@arr` carries no sequence id. Each component has an event time `E`.
- ONE WebSocket session delivers a stream in exchange order (one TCP stream).
- TWO sessions have no mutual ordering. A replacement served by a slower gateway can trail the socket it replaces
  (the 2026-10-07 case) or lead it.

## 4. Corrected invariant (continuous mode; bounded mode keeps the pre-1.5.0 rule unchanged)

Every message carries its **socket epoch**: one epoch per WebSocket session, assigned at each connect (also on every
reconnect of the same connection object) and recorded in `ws_connected`.

Per stream, with `hw` = the accepted latest sequence:

| Message | Classification | Effect |
|---|---|---|
| `seq ≥ hw` (any epoch) | accepted | advances `hw`; equal = same state, accepted as before |
| `seq < hw`, epoch's OWN order intact (`seq ≥` its previous seq), within the catch-up window | `seq_stale`: overlap or catch-up copy | discarded; counted; never a regression, never persisted |
| same, beyond the window | `seq_reset`, cause `catchup_timeout`: the replacement never reached the id space it replaces | accepted VISIBLY: lifecycle + DEGRADED latched incident |
| `seq <` the SAME epoch's previous seq | `seq_regression`: genuine in-socket regression (lifecycle on the first of a run) | discarded; after 20 in a row, `seq_reset`, cause `in_socket_regression` (m5, unchanged) |

- Catch-up window: `recv ≤ max(start of this epoch's behind-run, receive time of hw) + seq_catchup_timeout_s` (30 s).
- While another socket keeps delivering newer data, the window keeps moving: nothing is lost, since the newer data is
  being accepted.
- Once the other socket ends, the trailing socket must catch up within 30 s, or the gap is a hard, visible
  discontinuity.
- Market components: an older-`E` component from a trailing socket never overwrites a newer one. Beyond the same
  window it is accepted, so the stream cannot get stuck.

## 5. Rotation hand-off (continuous mode)

1. The replacement connects and subscribes, and delivers its first data message (unchanged).
2. **Hand-off:**
   - The old socket stays open.
   - At first message + `ws_handoff_min_s` (2 s), targets are FROZEN: for every stream the old socket delivered
     during the overlap, its sequence at that moment.
   - The old socket closes when the replacement's own sequence has reached every target. A replacement with a
     constant lag never reaches a moving target, so the targets cannot move.
   - Bounded by `ws_handoff_timeout_s` (15 s). The hand-off also ends if the old socket ends, the replacement
     disconnects, or the collector stops.
3. If the old socket ends during the hand-off (for example a server close after `serverShutdown`):
   - it is NOT a connection-down transition;
   - it never reconnects;
   - it is recorded as lifecycle `ws_superseded_closed`.
4. Incomplete hand-off (pending streams), fail-closed:
   - WARNING latched incident `rotation_handoff_incomplete:<conn>`;
   - for each pending stream, values received before the close are not persisted after it. The gap cause is
     `awaiting_post_reconnect_data` until the replacement delivers an accepted message.
5. Post-close audit (bounded by `seq_catchup_timeout_s`):
   - lifecycle `ws_handoff` with, per stream: target, old FINAL sequence and time, replacement first sequence and
     time, sequence at close, and the first replacement sequence reaching the old final, with its time;
   - plus one class per stream:
     - `proven`: id ranges overlap;
     - `ahead`: the replacement was already newer while both sockets were open;
     - `resumed`: the replacement was silent until after the close, then newer;
     - `quiet`: no evidence yet;
     - `unresolved`: only OLDER messages, so continuity is NOT established. The stream fails closed as in step 4
       and the incident is raised.
     - `no_old`: the old socket never delivered on this stream.

Reconnect and restart have no overlap. They remain explicit gaps (`ws_disconnect_reconnect`,
`awaiting_post_reconnect_data`, downtime records). A trailing reconnected socket is `seq_stale` within the window,
and is never a regression.

## 6. Telemetry and compatibility (all additive)

- New lifecycle events:
  - `ws_handoff`;
  - `ws_superseded_closed`;
  - `seq_regression` (first message of a genuine in-socket regression run; at most 500 per boot).
- Additive payload fields:
  - `ws_connected.epoch`;
  - `ws_rotation.handoff`;
  - `seq_reset`: `cause`, `conn`, `epoch`, `hw`, `hw_recv_ms`, `behind_n`, `behind_ms`, `regress_n`.
- New counters: `seq_stale`, `seq_reset_causes`, `seq_catchups`, `seq_catchup_max_ms`, `handoffs`,
  `handoff_classes`, `market_component_stale`.
- The `seq_reset` incident detail gains `last` and `causes`.
- Config keys with defaults:
  - `ws_handoff_min_s`: 2.0;
  - `ws_handoff_timeout_s`: 15.0;
  - `seq_catchup_timeout_s`: 30.
  The deployed `continuous-v1.json` loads unchanged.
- `collector_version` is `p2cr-collector-1.5.0`.
- No schema version change, no new record type, no new gap cause.
- Checked against the unchanged consumers:
  - `verify_continuous.py`, as seal and test (unknown events ignored; connection timeline only from
    `ws_connected` / `ws_disconnected` / `ws_connect_failed`);
  - `p2f_seal_day.py`;
  - the P2-C reader (generic lifecycle; epochs only from `universe_*` / `day_checkpoint`);
  - the G4 monitor (generic incidents; a WARNING incident key is reported as WARNING, as `rotation_overlap_failed`
    already is).

## 7. Tests

- `tests/test_p2f_rotation_continuity.py`:
  - invariant unit tests;
  - deterministic replay of the production incident from `tests/fixtures/rotation_incident_20261007.json`. The old
    rule reproduces the three production resets exactly. The new rule gives 0 resets and the identical persisted
    values;
  - real `rotate()` hand-off on a lagging fake exchange (trailing, ahead, both connections, another id space, old
    socket closed mid-hand-off, reconnect, restart);
  - the market guard;
  - config bounds.
- `tests/test_p2f_rotation_e2e.py`: the full continuous collector on a lagging exchange, followed by verifier, seal,
  P2-C reader and monitor.
