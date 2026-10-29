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
config_hash_after     : PENDING at the time of this entry (filled by amendment A1)
code_sha_after        : PENDING at the time of this entry (filled by amendment A1)
lineage_note          : config.py at bb7825f also carries #59 T1_CAP_POLICY (=legacy_window_v1, unused by these
                        services) and #74 EVIDENCE_TELEMETRY_MIN_INTERVAL_S (excluded from config_hash);
                        RISK_PRICE_FETCH_RETRIES=0 (default, not set in compose)
unchanged_services    : analyzer, signal_engine (rel-ea8ae4f-r2), scanner (aiohttp 3.14.3 overlay); none of them reads
                        PAPER_ECONOMIC_HALT_MODE
pause_state_at_activation : persisted technical pause (invalid_risk_state: a risk input could not be evaluated, so
                        admissions stay blocked fail-closed) in place; the deployment gate reads of the pause row
                        and the risk outbox passed before and after both steps (values not recorded here: OD-7,
                        redaction R1). NOT cleared by this activation; no /resume issued.
rule                  : trades admitted before activation_utc_minute (econ-enforce-v1) and after it (econ-observe-v1)
                        must never be pooled without stratification; no retroactive attribution; active_trades has no
                        policy column -> separate by evidence label risk_policy_version + this boundary minute.
                        Post-boundary admission activity is not recorded in this file (OD-7, redaction R1).
```

**Late-recording discrepancy (kept explicit).** The deployment procedure
(`~/ops/tsb-paper-observe-pkg/PROCEDURE.md` §D) required this record to be written right after step 1 and amended
after step 2. It was not written after step 1. It was first written on the host after step 2
(`~/ops/tsb-paper-observe-pkg/run-20261027T1149Z-stage2/VERSION_BOUNDARY.md`, 2026-10-27 about 11:55Z) and is
committed here later the same day. The values above come from evidence captured at the time of each step (identity
captures, hash gates, pause reads, CI run IDs), not from memory, and the delay has no effect on attribution, which
uses the activation minute and the evidence identifiers, not the time of writing. Two fields
(`config_hash_after`, `code_sha_after`) stay PENDING until the first evidence record and will be filled by an
amendment, never by rewriting this entry's other fields.

### VB-2026-10-27-01 amendment A1 (recorded 2026-10-28): evidence identifiers

Fills the two PENDING fields above from Evidence v2 records read on the host
(`data/evidence_v2/<service>/`). The fields of the entry above are not rewritten (redaction R1 aside).

```
config_hash_after     : c2af868dbb799919c165717262d6929aba27b0cbbfab27bc2d9d14ded902bb19  (trade_tracker and telegram)
config_hash_before    : 7f5246cb6d843ca2ff14be8dec4afe51fe09629a247a2c56a3c87ead185dcb9e  (both services, last record
                        before each step)
code_sha_after        : trade_tracker ad43026473f46ecb8f3fa13497ad865ef4af02f44ceded869af6cac37c60591a
                        telegram      417bf99f8e27fa9a5bf03a8fbcfed14bc692e2df733031dc62289754d750787d
code_sha_before       : trade_tracker 6a45297bedc818332f2ca756381f352cec75508911563ea81e9bdcefeb639ff9
                        telegram      6beadba130ab5a107762911e1031db6afe84fcda64c65164254d6c0bc1e9ddf6
first_record_after    : the recorder.started record of each service at its activation minute (entry above).
                        Every later record of both services carries the same pair (one distinct pair per service).
first_trading_record  : not recorded here (OD-7, redaction R1)
build_revision        : unknown (the overlay images carry the revision only as an OCI label, not in the records)
strategy_version      : sb-2026.08 (unchanged across the boundary)
```

**Label verification.** The `risk_policy_version` label (`econ-observe-v1`) is carried only by `admission.decision`
payloads; its verification is recorded in amendment A2. Independently of the label, trades are separated by this
boundary minute and by the config_hash/code_sha pairs above, which differ on each side.

**Correction.** The 2026-10-27 operational report named a different record as the first post-activation evidence
record. The first records are the `recorder.started` records listed above; the identifiers are the same.

### VB-2026-10-27-01 amendment A2 (recorded 2026-10-28): risk_policy_version label verified

Records the label verification announced in amendment A1. Source: trade_tracker Evidence v2
(`data/evidence_v2/trade_tracker/`), read on the host. Amendment A1 is not rewritten (redaction R1 aside).

```
first_admission_decision : not recorded here (OD-7, redaction R1)
risk_policy_version      : econ-observe-v1
config_hash / code_sha   : c2af868dbb79… / ad43026473f4… (the A1 values)
```

The label is verified on the first `admission.decision` record after the boundary: admission records after the
boundary carry `risk_policy_version=econ-observe-v1`. The stratification rule of the entry above is unchanged.

### Redaction R1 (recorded 2026-10-29): OD-7

Owner-approved OD-7 remediation. Paper trading counts, outcomes, record identifiers and record timestamps from the
sealed FORWARD_HOLDOUT (after the 2026-08-19 research freeze) were replaced by neutral statements in the entry above
and in amendments A1 and A2. Version-boundary and deployment evidence is preserved: activation minutes, commits,
compose blobs, images, rollback images, config_hash/code_sha pairs, and the policy label and its verification. The
late-recording discrepancy, the attribution rationale and the correction are preserved in substance but reworded
without the protected records. The date of the technical pause was removed from this file because it can indirectly
date a protected record; it remains in other tracked incident and deployment records. Earlier revisions of this file
and the messages of commits eba90dd, 4ba6cad and d1184c8 still contain the replaced values; they remain in Git history
and on GitHub, because history is not rewritten. Redaction does not restore the independence of the affected interval;
the exposure is recorded in `research/governance/contamination_registry.jsonl`. Monitoring after this redaction
follows `docs/ops/SEALED_SAFE_MONITORING.md`.
