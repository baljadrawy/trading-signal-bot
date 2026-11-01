# Strategy version-boundary template (SE-36, SE-72)

**Template only. Nothing on this page is an entry.** Entries are appended to [VERSION_BOUNDARY.md](VERSION_BOUNDARY.md) only for an owner-approved activation, and that file is append-only. Its rules apply to every entry made from this template: outcomes from different versions are never pooled without stratification, and nothing is attributed retroactively to a later version. Specification: [STRATEGY_INTERFACE_v1.md](../docs/design/STRATEGY_INTERFACE_v1.md) §10 (WP-A01, owner review).

## When an entry is required

| Change | `entry_kind` | Required |
|---|---|---|
| Any of `source_hash`, `config_hash`, `contract_hash` changes, with a new version label | `strategy_boundary` | Yes. A MINOR or PATCH step also needs a byte-identical golden replay (SE-38, SE-71); otherwise the change is MAJOR |
| Version label changes, all three hashes equal | `identity_rekey` | Yes. Decision keys may be derived from the identity tuple, so the change re-keys setups (SK-09 in [SETUP_KEY_PROPOSAL_SE84.md](../docs/design/SETUP_KEY_PROPOSAL_SE84.md)) |
| A hash changes under the same version label | — | **Stop.** This is an undeclared strategy change (SE-38; charter §6). Return to the owner; do not write an entry to legitimise it |
| Only `lineage` changes | — | No. Lineage is metadata (WP-IR-09) |
| Risk-policy change only (`RISK_POLICY_VERSION`, portfolio limits) | — | A risk-policy entry such as VB-2026-10-27-01, not this template |

`python -m shared.strategy_version_boundary BEFORE.json AFTER.json` drafts the fields below from two identity manifests. `ops/provenance/drift_check.py strategy --identity-reference BEFORE.json --identity-current AFTER.json` prints the classification (report-only). Neither writes this file or VERSION_BOUNDARY.md.

## Entry fields

```
boundary_id                 : VB-<YYYY-MM-DD>-<NN>
entry_kind                  : strategy_boundary | identity_rekey
strategy_id                 : <strategy_id>
version_before              : <MAJOR.MINOR.PATCH>
version_after               : <MAJOR.MINOR.PATCH>
source_hash_before          : <64 hex>
source_hash_after           : <64 hex>
config_hash_before          : <64 hex>   (strategy config_hash, not the evidence-v2 envelope hash)
config_hash_after           : <64 hex>
contract_hash_before        : <64 hex>
contract_hash_after         : <64 hex>
closure_spec_hash_after     : <64 hex>   (declared closure of the new version)
cost_model_id               : <id from the contract descriptor>
fill_model_id               : <id from the contract descriptor>
activation_utc_minute       : <YYYY-MM-DDTHH:MMZ>   (owner-approved activation only)
admission_authority_service : <service that admits trades for this strategy>
source_commit               : <40 hex, per service>
images                      : <service> sha256:<64 hex>, one line per service
rollback_images             : <service> sha256:<64 hex>, one line per service
no_refire_rule              : only bars whose bar_close_time is at or after activation_utc_minute are
                              evaluated under the new identity; a bar evaluated under the old identity is
                              never re-evaluated (SE-36)
stratification_rule         : outcomes before and after activation_utc_minute are never pooled without
                              stratification; no retroactive attribution
golden_replay               : <record of the byte-identical replay> | not applicable (MAJOR or identity_rekey)
lineage_note                : <ancestor identities; never a claim of inherited evidence>
pending_fields              : <fields still PENDING, to be filled by amendment, never by rewriting>
```

Fields an activation alone can provide (`activation_utc_minute`, `images`, the evidence-derived hashes) stay `PENDING` in a draft. They are filled later by an amendment appended below the entry, as VB-2026-10-27-01 does for its own PENDING fields.
