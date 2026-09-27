# PHASE 2A-P0R RUNTIME CONTRACT & REPLAY PARITY REPORT

## 1. Executive Summary

P0 is ready for Phase 2A baseline replay.  The active production wiring was
inspected read-only from the running Docker Compose services.  Contrary to the
host-default inference that triggered the original stop, the analyzer actually
runs `15m,4h,1d`, and the trade tracker enforces
`min(MAX_OPEN_TRADES=10, RISK_CANARY_MAX_OPEN_TRADES=2) = 2`.

The canonical runtime contract was captured from the owning services, a child
contract was derived by deep copy, and an automated allowlist proves that its
only behavioral differences are the three explicit Macro-ablation fields.  The
immutable Parquet snapshot is read directly through a read-only adapter.  A
technical replay ran twice with identical decisions on 15m, 1h, 4h and 1d,
without performance output.

## 2. Runtime Production Source

```text
runtime mode = active Docker Compose services
compose file = /home/tradmin/trading-signal-bot/docker-compose.yml
analyzer     = trading_analyzer / python -u main.py
risk owner   = trading_tracker / python -u main.py
scanner      = trading_scanner / python -u main.py
signal path  = trading_signal_engine / python -u main.py
host git_sha = 63da7d31daef2b952c695b256f81cf174b6451a8
git_dirty    = true
image version labels = sb-2026.08
image revision labels = unknown
```

The missing image revision label is offset for replay traceability by SHA-256
capture of every running code file used in the contract.

## 3. Legacy Contract

```text
contract_id = legacy_research_contract-f8e59381cd0c8d363230
hash = f8e59381cd0c8d3632309cb8d28f3e3ccfe60e4200066d560b82047ae7644de9
timeframes = 15m,4h,1d
max_open_trades = 2
status = LEGACY_RESEARCH_CONTRACT
```

The original freeze artifact was not changed or renamed.

## 4. Canonical Production Runtime Contract

```text
contract_id = production_runtime_canonical-0644d1a08b5dcaeba798
hash = 0644d1a08b5dcaeba798be992e55bd65357b349dd8461d907c78fb195c4a76a5
captured_at = 2026-08-19T17:21:31.668474+00:00
timeframes = 15m,4h,1d
max_open_trades = 2
status = PRODUCTION_RUNTIME_CANONICAL
```

## 5. Full Legacy vs Runtime Diff

There are no semantic parameter differences.  The earlier apparent differences
were caused by evaluating host Python defaults rather than the environments in
the running owner services.

The machine diff contains 20 code-source entries because the legacy contract
used repository-relative source names, while the canonical snapshot uses
`container:absolute-path` identities and also captures runtime entrypoint files.
Matching shared files have matching hashes.  The running analyzer contains the
pre-extraction `technical_analyzer.py`; the current host worktree contains the
uncommitted pure-function extraction.  P0 parity tests cover the extracted
strategy calculations, but the runtime image itself was not changed.

## 6. Research Child Contract

```text
contract_id = phase2a_macro_disabled_contract-00aa3ea80de76428bf4a
parent_contract_id = production_runtime_canonical-0644d1a08b5dcaeba798
hash = 00aa3ea80de76428bf4a1de7af0e67373b95026418407d3026e58906bc4e755f
research_mode = MACRO_DISABLED_RESEARCH_ABLATION
```

## 7. Production vs Research Child Diff

The automated gate passed with exactly:

```text
macro.required
macro.mode
macro.admission_behavior
```

Any other observed path produces `FAIL — RESEARCH_CONTRACT_DRIFT`.

## 8. Macro Bypass Semantics

```text
macro_pass = null
macro_admission = BYPASSED_BY_RESEARCH_ABLATION
```

The bypass is never recorded as `PASS`.

## 9. Dataset Adapter

```text
adapter = NormalizedParquetReader
adapter_version = normalized-parquet-1.0.0
manifest field = identity.normalized_files
input = Parquet
layout = normalized/<timeframe>/<symbol>.parquet
canonical conversion = none
write behavior = none
```

The adapter validates required fields, UTC timestamps, chronological order,
duplicates, checksums on request, and the historical cutoff.  Liquidity is read
point-in-time from the 15m normalized layer using backward-as-of semantics.

## 10. Dataset Integrity

```text
dataset_id = ds-09284abbc6453ff59acd
manifest_sha256 = a7c8eee1ecbd05eef3e28b1a40bd7199cc3fb9ac71ab3aac2c84ac0ca6a33b09
snapshot mode = read-only
files written inside snapshot = 0
```

## 11. Timeframe Parity

| Timeframe | Dataset load | Indicators/regime | Stop/target path | Runtime enabled |
|---|---|---|---|---|
| 15m | PASS | PASS | PASS | YES |
| 1h | PASS | PASS | PASS | NO |
| 4h | PASS | PASS | PASS | YES |
| 1d | PASS | PASS | PASS | YES |

The 1h path is technically valid and resolves expiry to `(48h,24h,24h)`, but it
must not be included in Phase 2A baseline while the active analyzer excludes it.

## 12. Risk Parity

```text
MAX_OPEN_TRADES = 10
RISK_CANARY_MAX_OPEN_TRADES = 2
effective max_open_trades = 2
capacity test = PASS (second-capacity boundary rejects the next candidate)
```

All remaining risk fields were captured from the running trade tracker.

## 13. Technical Replay Dry Run

The immutable BTCUSDT snapshot was sampled at a fixed historical decision time.
All four timeframe paths loaded 240 completed candles, calculated indicators and
regime, read historical liquidity, applied the outcome-blind Tier-3 proxy, and
produced deterministic opportunity IDs and rejection classifications.  No PnL,
PF, Sharpe, expectancy or other performance metric was generated or stored.

## 14. Determinism

```text
two identical technical runs = byte/logical match
contract hashes = match
opportunity IDs = match
decisions = match
rejection reasons = match
stop/target outputs = match
status = PASS
```

The read-only production drift monitor also returned `MATCH`.

## 15. Holdout / Governance

```text
knowledge_cutoff = 2026-08-19T09:33:46Z
historical_end = 2026-05-31
forward_holdout_status = SEALED
holdout_look_count = 0
```

## 16. Production Change Since Knowledge Freeze

The canonical runtime capture occurred after the knowledge freeze and is marked:

```text
CURRENT_RUNTIME_CONTRACT_REBASED_AFTER_KNOWLEDGE_FREEZE
```

Future Phase 2A results describe the current runtime contract replayed on
research-contaminated historical data with Macro disabled.  They do not
reconstruct every policy historically deployed during that data period.

## 17. Tests

```text
passed = 242
failed = 0
skipped = 0
```

## 18. Files Changed

- `research/foundation/runtime_contract.py`: capture, redaction, derivation and diff gate.
- `research/foundation/readers.py`: immutable normalized-Parquet adapter.
- `research/foundation/replay.py`: explicit research Macro-bypass semantics.
- `research/p0r.py`: runtime capture, drift monitor and deterministic dry-run CLI.
- `tests/test_research_p0r.py`: P0R contract, adapter, 1h and bypass tests.
- `research/governance/contracts/*.json`: immutable legacy, canonical, child and diff artifacts.
- `research/runs/p0r-00aa3ea80de7/technical_replay.json`: performance-suppressed dry-run artifact.
- `docs/phase2a_p0r_runtime_contract.md`: this report.

## 19. Git Status

No commit, push, deploy, restart or production mutation was performed.  The
worktree remains dirty from pre-existing research and analyzer changes plus the
P0R files listed above.

## 20. P0 Verdict

```text
P0 READY — RESUME PHASE 2A
```

## 21. Exact Remaining Blockers

None for the Phase 2A technical gate.  Phase 2A must use only the canonical
child contract and must exclude 1h unless the production analyzer runtime is
changed and a new canonical contract is deliberately captured.

## 22. Authorized Next Action

```text
PHASE 2A may resume from Baseline Replay.
```

