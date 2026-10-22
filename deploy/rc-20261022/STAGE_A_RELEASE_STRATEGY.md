# Stage A release strategy: activation without a second Collector restart

**Status: owner chose O2a; deployed 2026-10-22 17:45Z (`STAGE_A_DEPLOYMENT_RECORD.md`). Flapping detection stays disabled.** The Collector reads its configuration only at startup, so every
change of a #76 flag costs one restart and therefore one collection gap.

## Options

| | O1: disabled-default, then activate | O2a: one deployment, lifecycle logging on, flapping off | O2b: one deployment, both on |
|---|---|---|---|
| Restarts / gaps | **2** (≈30–60 s each, about 70 s total) | **1** | **1** |
| Config file | first the unchanged `continuous-v1.json`, then a new file | `continuous-v1-obs-lifecycle.json` (sha256 `0db3f89d…`) | `continuous-v1-obs-both.json` (sha256 `ced616c4…`) |
| Run-record `config_hash` (1.6.0 today `45296f7a…`) | `feb253c3…`, then `6546b479…` | `6546b479…` | `8cb5806e…` |
| New dataset records | lifecycle `ws_session_end` after step 2 | lifecycle `ws_session_end` (metadata only) | same, plus `conn_flapping_open` / `conn_flapping_resolved` |
| New incidents | none, then as chosen | **none** | `conn_flapping:<conn>` WARNING (not latched) |
| Health / monitor / research admission | unchanged | **unchanged** | Overall severity is already WARNING (3 held WARNINGs), so no monitor alert entry. Admission allows WARNING. |
| Rollback to 1.6.0 | image + original config | image + **original config** (1.6.0 refuses the new key) | Image + original config. An open `conn_flapping` WARNING then **stays open** (1.6.0 cannot resolve it) and needs an owner disposition. |
| Soft rollback (keep 1.6.1, original config) | yes | yes | yes |
| Unvalidated part | none | none | the flapping threshold (10 per 30 min) is a candidate, untested on real traffic |

## Evidence

All synthetic and isolated; see `RELEASE_CANDIDATES.md` §4 and `STAGE_A_MANIFEST.md`.
- With flags off the behaviour equals 1.6.0: same lifecycle profile, 0 incidents, days PASS.
- `ws_session_end` is metadata only. Exceptions in the observer are swallowed (`_report_session_end`), and a test
  proves that a failing observer never breaks a session.
- The unchanged verifier, the 1.6.0 verifier and the P2-C reader all accept the new records.
- Resources are equal (CPU mean 14.6 % vs 14.8 %, memory peak 90.7 vs 88.9 MiB).
- Volume: one small record per ended session. The 2026-10-21 episode would have added about 250 records over 3 h.

## Recommendation: O2a

1. **One restart instead of two.** O1's first restart buys nothing that O2a lacks: its zero-behaviour-change step is
   already proven offline, and O2a keeps a soft rollback to exactly that state.
2. **No incident side effects.** A new incident key is the only part of #76 with operational consequences (rollback
   leftovers, owner dispositions), and only O2b introduces it.
3. **Data before threshold.** O2a records exactly the data needed to calibrate flapping. A **shadow replay** of
   `FlapDetector` over the recorded `ws_session_end` events shows which episodes 10 per 30 min would have opened,
   without raising anything live. That replay reads Collector lifecycle metadata, so it needs your authorization.
4. **Flapping later, no extra gap.** Enable `conn_flapping_enabled` in the next Collector restart that happens anyway
   (the next release), or in a dedicated one only if the shadow replay justifies it.

O2b is acceptable if you want live flapping WARNINGs immediately. Its only added cost is the rollback leftover above.

O1 is recommended only if a two-step change record matters more than one extra collection gap.

**Owner decision needed:** the option (O2a recommended), then a separate Stage A deployment approval.
