# P2-C Research Trial Ledger — spec v1

**Status:** tooling + spec on branch `feature/p2c-research-layer-20261004`; no trial has been registered; no metric
is computed. Code: `p2_research/ledger.py` (stdlib). Schema: `p2_research/schemas/trial_ledger_v1.schema.json`.
Tests: `p2_research/tests/test_ledger_instrument.py`. Governance: [ROADMAP_AND_RESEARCH_GOVERNANCE.md](ROADMAP_AND_RESEARCH_GOVERNANCE.md)
(P2G-ADR-05).

## Purpose

Every research trial — accepted, rejected, inconclusive or abandoned — is recorded before it runs and can never be
erased or rewritten. This makes the number of trials per hypothesis known (input to Deflated Sharpe and PBO) and
prevents selective reporting. The ledger is bookkeeping only: no optimization, no metric computation.

## Storage

- Default: `/home/tradmin/research-data/trading-signal-bot/p2c/ledger/trials.jsonl` (+ `.lock`). Refused inside the
  collector tree `/home/tradmin/research-data/trading-signal-bot/p2/`. Tests use temporary directories.
- One canonical JSON object per line (`sort_keys`, compact separators, ASCII). Appends use `O_APPEND` + `fsync`
  under an exclusive `flock`; the whole ledger is verified before every append and a failed verification refuses
  the append.

## Events

Common fields: `ledger="tsb.p2c.trial_ledger"`, `ledger_version=1`, `seq` (0, 1, 2, … contiguous), `prev_hash`
(previous `event_hash`; genesis = 64 zeros), `event_hash` = SHA-256 of the canonical event without `event_hash`,
`event`, `trial_id`, `at` (UTC, informational; not part of the trial id), `payload`.

1. `trial_created` — payload `{spec, spec_sha256, creation_seq}`. `spec_sha256` = SHA-256 of the canonical spec;
   `creation_seq` = number of earlier trials with the same spec; `trial_id = "TR-" + sha256(spec_sha256 + "|" +
   creation_seq)[:24]`. Same history + same spec ⇒ same id; re-running an identical spec ⇒ a new id.
2. `trial_result` — payload `{status, rejection_reason, metrics, evidence, notes}`, `status ∈ {accepted, rejected,
   inconclusive}`; `rejected` requires a non-empty `rejection_reason`. **At most one result per trial**: a second
   result is refused (`ResultConflict`), so a later success cannot overwrite a failure. A re-test is a new trial
   with `parent_trial` set.

There is no update or delete API.

## Trial spec (all fields required; `parent_trial` may be null; no other fields)

| Field | Content |
|---|---|
| `hypothesis_id` | `H-<name>`: the documented hypothesis the trial tests |
| `code_commit` | git SHA of the research code |
| `dataset` | `{dataset_id, dataset_hash}` (P2-C `logical_hash` or raw dataset SHA-256) |
| `feature_set_version`, `label_set_version`, `universe_policy` | e.g. `1.0.0`, `1.0.0`, `universe-asof-all-tiers-v1` |
| `market` | `{asset_class, venue, product[, calendar_id]}`; only `crypto/binance/spot` is accepted (P2G-ADR-01) |
| `strategy_family`, `parameter_spec` | family name; the full parameter space or the fixed values (predeclared) |
| `transaction_cost_assumptions`, `execution_assumptions` | fees, spread/slippage model, entry/exit rules |
| `train_period`, `validation_period` | `{start, end}` ISO-8601 UTC, half-open; validation starts at/after train end |
| `holdout` | `{"w3": "sealed_forbidden", <name>: {start, end} \| null, …}` — explicit W3 acknowledgment |
| `metrics_requested` | non-empty list of metric names (from the evaluation contract) |
| `parent_trial` | earlier trial id or null |

**W3 rule:** any period (train, validation, any holdout entry) overlapping W3 = [2026-08-19T09:33:46Z,
2026-10-04T15:26:43.497803Z) is refused (`W3SealedError`); a missing or different `holdout.w3` value is refused.

## Verification

`verify(expected_head=None)` checks: JSON + canonical form, ledger record/version, contiguous `seq`, `prev_hash`
chain, every `event_hash`, every spec (incl. W3 and market rules), trial-id derivation and creation sequence,
duplicate ids, parent ordering, results for known trials only, at most one result per trial, result validity.
Removing, editing, reordering or inserting events is detected. Truncation of the newest events is detectable only
against an externally recorded head (`head()` → `{seq, event_hash}`), e.g. stored in an evidence `SHA256SUMS`.

## Counting

`trial_counts()` → per hypothesis: `trials` (all attempts), `pending`, `accepted`, `rejected`, `inconclusive`. Later
Deflated Sharpe / PBO calculations must use `trials` (not only accepted ones). No such calculation exists yet.
