# MI ML — Phase 1 record: contract MI-C v1.0 frozen (2026-10-08)

**Scope (owner authorization).** Contract preparation, freeze, ledger genesis, and lightweight synthetic boundary
and unit tests only.

- **Baseline:** `3aff2cc99cd0e7423b030ac234ada28cbfd24cea`.
- **Not done:** no real data or outcomes, no W3, no Collector data, no Phase 1S, no simulation, no model fitting, no
  install, no production change.

## Contract MI-C v1.0

- **Location:** `p2_research/mi/contracts_v1_0/`.
- **contract_set_sha256 = `fdf3366480976db6ada1ac90b62f6b6db1edc35a59d1f3527cfcd6fcbf28e157`** (SHA-256 of
  `FROZEN_SHA256SUMS.json`).
- The sums cover the three JSON documents **and** the implementing code, so a code change is a contract change:

| File | Content |
|---|---|
| `mi_contract_v1_0.json` | governance and owner decisions; data (DS-1…DS-9, W3 sealed including market candles); PIT model; universe (D4 b); segments (S-MAJ development from **2018-01-01**, B1); 16 folds; T1 / T2 / T3; requirements A / B / C (B structure frozen, CDP provisional); utility labelled `REFERENCE_PRICE_COUNTERFACTUAL`; verdicts; versioning; ledger |
| `mi_phase1s_protocol_v1_0.json` | the synthetic-only protocol: 48 cells (T1 24, T2 18 including the π = 0.2 B2-verification level, T3 6; 11 stress cells), reps, meta-acceptance, ladder, applicability thresholds, B2 rule, and the **CPU-budget enforcement requirements G1–G7** |
| `mi_derivation_map_v1_0.json` | input schema, STOP preconditions, CDP rules, numerics |
| `timeline.py`, `folds.py`, `derive.py`, `contract.py` | PIT functions, the fold calendar with K1 assertions, the derivation map (`mi-derivation-map-1.0.0`), and the loader / verifier |

**Owner decisions applied:**

- **B1:** S-MAJ development training starts 2018-01-01. Certified BTC/ETH data starts 2017-08-17, which is ≥ the
  61-day lookback, asserted. The 16 folds from 2021-Q1, the HLE and W3 are unchanged.
- **B2:** the T2 reference base rate is 0.3 (exact 3/10). The derivation map **verifies** it: every non-stress T2
  cell, including the π = 0.2 verification cells, with n_events ≥ ⌈n*/0.3⌉ must reach power ≥ 0.80. Otherwise:
  STOP `B2_REFERENCE_NOT_CONSERVATIVE`, and the question returns to the owner.
- **CPU budget correction:** the cap is defined on **measured cumulative cgroup CPU** (`cpu.stat usage_usec`),
  independent of wall-clock time. RuntimeMaxSec is only an additional safeguard (G6). The derivation map refuses any
  Phase 1S output unless `enforcement = cgroup_cpu_budget_guard_v1` **and** `enforcement_verified = true`
  (`BUDGET_NOT_ENFORCED`).

## Ledger genesis

| Item | Value |
|---|---|
| genesis_id | **`adcdc0b23655075eb975604edf3110138e38416cc6c9f88de5ae7ec2f68effc7`** |
| Ledger dir | `/home/tradmin/research-data/trading-signal-bot/mi/ledger/` (outside the Collector tree `…/p2`) |
| Genesis record | `MI_LEDGER_GENESIS.json` (read-only, 0444); identical copy at `p2_research/mi/ledger_genesis_v1_0.json` |
| Head | seq −1, event_hash `000…0` (P2-C GENESIS); no `trials.jsonl`; 0 events, 0 trials |
| Binding | contract_set_sha256 `fdf33664…`; `p2_research/ledger.py` SHA-256 |
| Rule | no trial before MI-C v1.1 is pushed; real-data trials only after v1.1 and before Phase 2 |

## Tests

`python3 -m unittest p2_research.tests.test_mi_phase1`: **38 / 38 OK** in 0.23 s.

| Group | Tests | Covers |
|---|---|---|
| PIT boundary | 11 | the full §1.1 list (availability at issuance vs +1 ms; µs / ms closes; T1 label start; T2 level and label; T3 at 00:06; month / fold refits; gaps and no back-fill; freeze in features and labels; shift canary; Δ doubling) |
| K1 fold calendar | 6 | 16 contiguous quarters. S-MAJ fold-1 spans: T1 1094.67 / T2 1094.83 / T3 1088.0 days (≥ 730). **The 2019 start fails closed** (729.67 / 729.83 / 723.0). S-ALT is span-exempt with boundaries asserted. Lookback precondition; HLE boundaries |
| K5 derivation map | 16 | pass; ladder steps 1 / 2; FAIL → DESCRIPTIVE_ONLY with failing cells preserved; stress exclusion; exact 5 % boundary and Wilson tie; upward-closed and infeasible n*; B2 STOP and beyond-grid; T3 fallbacks; **every STOP precondition**; determinism |
| Contract / genesis / isolation | 5 | the frozen set verifies and the hash is pinned; grid shape; core values; genesis id recomputed; no MI import outside research |

The existing `test_ledger_instrument` and `test_falsification_f0` suites still pass (55 / 55).

## Blockers

| ID | Blocker | Phase |
|---|---|---|
| **B5** | **The research runner cannot enforce a fail-closed cumulative CPU cap.** Its watchdog samples cgroup CPU but never kills on CPU (G1 missing); an unreadable sample keeps the last value (G2 missing); the job is not bound to the guard (G3 missing); recorded CPU is the last sample and may undercount (G4 partial); there is no cross-job reservation ledger (G5 missing); there are no fault-injection tests (G7 missing). Only RuntimeMaxSec (G6) exists. | **Blocks Phase 1S.** Needs a reviewed runner extension implementing G1–G7, tested and separately approved. The safety requirement is not weakened. |
| B3 | No Phase 1S compute is authorized | Phase 1S |
| B4 | Python environment design only (D8); W2 alt acquisition deferred (D9) | Phase 2 |

## Phase 1S readiness: **NO-GO**

- The protocol, derivation map and fixtures are ready and frozen.
- Phase 1S is blocked by **B5** (no enforceable CPU cap) and **B3** (no compute authorization).
- Next steps, each needing separate approval:
  1. G1–G7 runner extension (design, tests, deployment as a G2-class runner change);
  2. a Phase 1S compute GO.

Nothing is merged or deployed. HARD STOP after Phase 1.
