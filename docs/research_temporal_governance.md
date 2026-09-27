# Research temporal governance

## Frozen boundary

The current research boundary is recorded in `research/governance/research_freeze.json`.
The knowledge cutoff is the actual UTC freeze timestamp. Data after that instant is
not historical Discovery data; it may only enter the append-only Forward Holdout.
Changing data, mappings, transformations, configuration, contract, or Git state
requires a new content-addressed dataset and a new freeze artifact.

## Partitions

- `DISCOVERY` permits repeated diagnostics and hypothesis formation. All available
  historical periods are contaminated to some degree and therefore are not an
  untouched test.
- `VALIDATION` is a usage-logged evaluation partition. No trusted historical
  validation period is designated in this freeze; its status is
  `HISTORICAL_VALIDATION_CONTAMINATED`.
- `FORWARD_HOLDOUT` begins strictly after the freeze instant. It is sealed by
  default and is excluded from Discovery reports, outcomes, labels, and aggregates.

The boundaries are time/governance based. They must never be moved because of
returns, trade counts, market regimes, or any strategy metric.

## Contamination and prior knowledge

`contamination_registry.jsonl` is the append-only disclosure of periods already
seen or likely seen. `pre_existing_knowledge.json` records prior claims which may
motivate a hypothesis but cannot be reported as a new independent discovery.
Every future hypothesis must identify its source as `PRE_EXISTING`,
`DISCOVERY_DERIVED`, or `EXTERNAL_THEORY`.

## Validation use

Every Validation access is appended to `validation_usage.jsonl` with hypothesis,
experiment, timestamp, requested metrics, and result artifact. The line count is
the validation-look count. Empty files mean zero looks, not missing governance.

## Forward holdout: one-way door

Normal replay does not unlock the holdout. Explicit opening requires:

```bash
python -m research.data_governance.cli unlock-holdout \
  --opened-by OWNER --reason "final confirmation" \
  --hypothesis-id H01 --experiment-id EXP01 --git-sha SHA
```

Opening records the actor, reason, hypothesis IDs, experiment IDs, Git SHA, and
time. `OPENED` can never return to `SEALED`. Once viewed, that interval is no longer
untouched. Continuing independent confirmation then requires a new future holdout.

## Dataset and correction policy

RAW is preserved, NORMALIZED is a deterministic transformation, and a
RESEARCH_SNAPSHOT is content-addressed. Gaps remain gaps: no forward-fill,
interpolation, or silent candle repair is allowed. Corrections create a new
dataset ID with `supersedes_dataset_id` and a reason; old snapshots remain.

The current indexed RAW source is Binance Public Data monthly spot klines. It is
not yet a certified research snapshot: 15m is absent, authoritative listing and
delisting events are absent, historical USDT dominance is absent, historical
spread is unavailable, and normalized row-level quality has not been certified.

## What is not evidence

Dataset coverage, deterministic replay, parity, and quality checks are necessary
infrastructure. They do not establish edge. No PnL, Profit Factor, Sharpe, win rate,
feature selection, or parameter selection is authorized by this freeze.
