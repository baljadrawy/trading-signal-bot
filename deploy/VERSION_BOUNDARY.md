# Paper strategy version boundaries

Each entry marks the minute from which Paper trades belong to a new risk-policy or strategy version. Entries are
append-only. Trades from different versions must never be pooled without stratification, and no outcome may be
attributed retroactively to a later version (owner contract §3, §4).

## VB-2026-10-27-01: econ-enforce-v1 → econ-observe-v1

```
policy_version_before : econ-enforce-v1 (implicit; images rel-ea8ae4f-r2 carry no label)
policy_version_after  : econ-observe-v1   (RISK_POLICY_VERSION)
activation_utc_minute : 2026-10-27T10:56Z   (trade_tracker = admission authority)
telegram_utc_minute   : 2026-10-27T11:51Z
source_commit         : bb7825f4744278095ef76a1d0f3b872e3043358f  (on main)
compose_commits       : 7305d2eb5c9282a7cf199abbe931b24668629d20 (blob 91430822414fd7e8ab398cfd033d1f7a5e3117ee),
                        26eb4e8c69273bf1eda4d8953c44dad86364f92b (blob d1a4b197e10f31a4972e8f6e5feba6be361c3689)
images                : trade_tracker sha256:8e609ca84740e9cd5c16f79c5fac2ae28a0f5004bb90665e29f4f0a6f5e1410c
                        telegram      sha256:d665388a9092f6e5f4364a3e0dff6cca33e9623c782ea47251b625be6a2a7b83
rollback_images       : trade_tracker sha256:2cf1dd52cd89d44b7dc70c92b0ff797a54e3799d7deaf82b4fe7d1012ba76ae8
                        telegram      sha256:51d62f4dfa512c54c29db8886cff171de7d48b356fde6f1874098df057f4d219
                        (tsb-a561-*:rel-ea8ae4f-r2)
config_hash_after     : PENDING (no evidence record since activation; admissions blocked by the technical pause)
code_sha_after        : PENDING (from the first evidence record)
lineage_note          : config.py at bb7825f also carries #59 T1_CAP_POLICY (=legacy_window_v1, unused by these
                        services) and #74 EVIDENCE_TELEMETRY_MIN_INTERVAL_S (excluded from config_hash);
                        RISK_PRICE_FETCH_RETRIES=0 (default, not set in compose)
unchanged_services    : analyzer, signal_engine (rel-ea8ae4f-r2), scanner (aiohttp 3.14.3 overlay); none of them reads
                        PAPER_ECONOMIC_HALT_MODE
pause_state_at_activation : 2026-10-21|t|t (risk_management date | is_trading_paused | technical
                        invalid_risk_state), risk.halted outbox rows 6; identical before and after both steps;
                        risk.observed rows 0 after stage 2. NOT cleared by this activation; no /resume issued.
rule                  : trades admitted before activation_utc_minute (econ-enforce-v1) and after it (econ-observe-v1)
                        must never be pooled without stratification; no retroactive attribution; active_trades has no
                        policy column -> separate by evidence label risk_policy_version + this boundary minute.
                        No trade has been admitted under econ-observe-v1 as of this record.
```

**Late-recording discrepancy (kept explicit).** The deployment procedure
(`~/ops/tsb-paper-observe-pkg/PROCEDURE.md` §D) required this record to be written right after step 1 and amended
after step 2. It was not written after step 1. It was first written on the host after step 2
(`~/ops/tsb-paper-observe-pkg/run-20261027T1149Z-stage2/VERSION_BOUNDARY.md`, 2026-10-27 about 11:55Z) and is
committed here later the same day. The values above come from evidence captured at the time of each step (identity
captures, hash gates, pause reads, CI run IDs), not from memory, and the delay has no effect on attribution: no trade
was admitted between 10:56Z and the time of writing, because the technical pause blocks admissions. Two fields
(`config_hash_after`, `code_sha_after`) stay PENDING until the first evidence record and will be filled by an
amendment, never by rewriting this entry's other fields.

### VB-2026-10-27-01 amendment A1 (recorded 2026-10-28): evidence identifiers

Fills the two PENDING fields above from Evidence v2 records read on the host
(`data/evidence_v2/<service>/events-2026-10-27.jsonl`). The fields of the entry above are not rewritten.

```
config_hash_after     : c2af868dbb799919c165717262d6929aba27b0cbbfab27bc2d9d14ded902bb19  (trade_tracker and telegram)
config_hash_before    : 7f5246cb6d843ca2ff14be8dec4afe51fe09629a247a2c56a3c87ead185dcb9e  (both services, last record
                        before each step: trade_tracker 10:50Z, telegram 11:46Z)
code_sha_after        : trade_tracker ad43026473f46ecb8f3fa13497ad865ef4af02f44ceded869af6cac37c60591a
                        telegram      417bf99f8e27fa9a5bf03a8fbcfed14bc692e2df733031dc62289754d750787d
code_sha_before       : trade_tracker 6a45297bedc818332f2ca756381f352cec75508911563ea81e9bdcefeb639ff9
                        telegram      6beadba130ab5a107762911e1031db6afe84fcda64c65164254d6c0bc1e9ddf6
first_record_after    : trade_tracker recorder.started 2026-10-27T10:56Z; telegram recorder.started 2026-10-27T11:51Z.
                        Every later record of both services carries the same pair (one distinct pair per service).
first_trading_record  : trade_tracker entry.attempt 2026-10-27T23:21Z (signal 15896, 15m), outcome ENTRY_REJECTED
                        (signal_invalidated_before_fill) after the owner's /resume (risk_management row 36139,
                        manual_resume, first seen 22:46Z). Rejected at the fill stage, before any risk evaluation.
build_revision        : unknown (the overlay images carry the revision only as an OCI label, not in the records)
strategy_version      : sb-2026.08 (unchanged across the boundary)
```

**Still PENDING: first admission.decision.** No `admission.decision` record exists after the boundary yet: the only
post-/resume signal was rejected before the risk check, so 0 trades were admitted. The `risk_policy_version` label
(`econ-observe-v1`) is carried only by `admission.decision` payloads, so its verification waits for the first
admission evaluation. Until then, trades are separated by this boundary minute and by the config_hash/code_sha pairs
above, which differ on each side.

**Correction.** The 2026-10-27 operational report named the 23:21Z `entry.attempt` as the first post-activation
evidence record. The first records are the `recorder.started` events listed above; the identifiers are the same.
