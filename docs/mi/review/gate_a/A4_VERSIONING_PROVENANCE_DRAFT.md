# A4 — Versioning and provenance for v1.0.1 (draft) — no ledger is reset, rebound or modified

> **DRAFT — NOT APPROVED — NOT FROZEN — NOT EXECUTABLE** — Gate A review material. Nothing here is an owner approval or a frozen artefact, and nothing here may be loaded by any run.

## 1. Principles

1. **Additive only.**
   - MI-C v1.0 stays byte-identical: `contracts_v1_0/*`, `contract.py`, `derive.py`, `timeline.py`, `folds.py`, `FROZEN_SHA256SUMS.json`, all verifying `fdf33664…`.
   - Nothing is edited, renamed or deleted.
2. **Forward links only.**
   - New artefacts point back to their parents; no existing artefact is changed to point forward.
   - The MI trial ledger and the CPU budget ledger receive **no writes** from this process.
3. **No trial accounting change.**
   - Synthetic Phase 1S runs are sealed manifests, not ledger trials (contract `ledger.synthetic_runs`; genesis `rule`).

## 2. Proposed v1.0.1 set (created only at a separately approved freeze)

```
p2_research/mi/contracts_v1_0_1/                       (new directory; v1.0 untouched)
  mi_phase1s_protocol_v1_0_1.json                      chosen A1 variant, draft_status removed
  mi_phase1s_interpretation_v1_0_1.json                machine copy of A2 (owner-approved items only)
  mi_protocol_amendment_MI-P1S-AM-1.json               amendment record (section 4)
  FROZEN_SHA256SUMS.json                               record tsb.mi.frozen_sums, set_version "1.0.1"
p2_research/mi/contract_v1_0_1.py                      new loader (contract.py is frozen and hard-codes v1.0)
```

**What the new sums file covers** (each by path and SHA-256):
1. **Parent:** `contracts_v1_0/FROZEN_SHA256SUMS.json` = `fdf33664…`, so every v1.0 file is covered transitively.
2. **Referenced, not copied:** `contracts_v1_0/mi_contract_v1_0.json` and `contracts_v1_0/mi_derivation_map_v1_0.json`. The contract definitions and the map are unchanged.
3. **New:** the three new JSON files and `contract_v1_0_1.py`.

**Rules:**
- `contract_set_sha256(v1.0.1)` = SHA-256 of the new sums file.
- The loader first runs the frozen `contract.verify()` (v1.0 must still equal `fdf33664…`), then verifies the new set.
- `derive.py` is unchanged: it is called with the v1.0.1 protocol dict and the v1.0.1 hashes (its signature already takes them).
- The Phase 1S engine pins `EXPECTED_*` to the v1.0.1 values and also checks the parent `fdf33664…`.

**Versioning compatibility:**
- The contract's v1.1 = "CDP only, by the frozen derivation map from one sealed COMPLETE Phase 1S output". The Phase 1S output will bind the v1.0.1 set, and v1.1 records that parent chain.
- The "v1.2+" rule (owner-approved, before Phase 2 only) is not used.

## 3. MI trial ledger — genesis preserved, no rebinding

| Item | Treatment |
|---|---|
| Genesis `adcdc0b23655…`, `contract_set_sha256 = fdf33664…`, 0 events, file absent | **Untouched.** It stays valid: MI-C v1.0 definitions are unchanged and the v1.0.1 set is a strict extension that names `fdf33664…` as its parent |
| Ledger code `p2_research/ledger.py` | Unchanged. It supports only `create_trial` / `record_result`; no rebinding event exists or is needed |
| Future real trials (only after v1.1, before Phase 2, separately approved) | The provenance chain goes in the trial spec's free-form `parameter_spec`, which the ledger already validates as a dict: `parameter_spec.provenance = {contract_set_v1_0: fdf33664…, phase1s_protocol_set: <v1.0.1 set>, phase1s_output_sha256: …, contract_v1_1_set: …, ledger_genesis_id: adcdc0b2…}` |
| Verification rule (to be added to the Phase 2 doc) | A trial is valid only if its chain resolves, through pushed and remote-verified artefacts, to genesis `adcdc0b2…` and contract set `fdf33664…` |

## 4. Permanent CPU budget ledger — unchanged

| Item | Value / treatment |
|---|---|
| Ledger id | `f5983b83c32c4278996ec642d385977a`; head and checkpoints untouched; last verified charged 66.882077, remaining 28 733.117923 CPU-s |
| Binding | The budget ledger is not bound to any contract hash, so v1.0.1 needs no change. Protocol `budget` (cap 28 800, `cgroup_cpu_budget_guard_v1`) is unchanged |
| Phase 1S output budget block | Ledger-level cumulative, including the prior 66.88 CPU-s (readiness B3 semantics). Filled only from INT-2 evidence; the evidence file's SHA-256 is recorded (F16) |

## 5. Amendment record (draft content of `mi_protocol_amendment_MI-P1S-AM-1.json`)

```json
{"record": "tsb.mi.protocol_amendment", "v": 1, "id": "MI-P1S-AM-1",
 "parent": {"protocol_sha256": "412cb606...", "contract_set_sha256": "fdf33664...",
            "ledger_genesis_id": "adcdc0b2..."},
 "new_protocol_sha256": "<at freeze>", "clauses": ["AM-1", "AM-2", "AM-3-<K|R>"],
 "motivation": {"AM-1": "F1", "AM-2": "F10", "AM-3": "F3"},
 "evidence": {"implementation_commit": "df43073f6d313cd7b6f524a2d124821133a4ab77",
              "audit": "Phase 1S independent audit (session report)", "plan": "Phase 1S remediation plan",
              "gate_a_drafts": "docs/mi/review/gate_a/"},
 "prior_synthetic_exposure": "<section 6 list>",
 "no_calibration_run_under_v1_0": true,
 "owner_approval": {"date_utc": "<at freeze>", "scope": "<approved clauses>"}}
```

## 6. Forking-path disclosure (everything synthetic seen before the amendment)

All of the following are bounded development diagnostics on `df43073`, never a Phase 1S calibration run:

| Diagnostic | Size |
|---|---|
| Single-rep smoke tests | 4 cells + 4 L2 |
| B3 size checks | 80–200 reps per cell, 6 cells |
| Skill vs leak BSS | 30 reps, 4 cells |
| Break-cell power | 8 + 8 reps |
| Development CPU timing | 3 reps × 4 kinds × 4 cells |
| Null drift | 20 reps × 4 cells |
| Sandbox probes | Nonexistent targets only |
| Analytic calculations | Quadrature, exact binomials |

No full-grid FPR, power or ladder result exists. The amendment rationale is structural and analytic, and is recorded together with this list.

## 7. Reproducibility requirements after freeze

- **Any Phase 1S output must bind:**
  - the v1.0.1 set hash and its parent `fdf33664…`;
  - the protocol and interpretation hashes;
  - the code tree and commit;
  - the generator version (`mi-p1s-gen-1.1.0`);
  - the interpreter version and platform;
  - the plan, seeds and results digests;
  - the evidence hash.
- **Old evidence stays verifiable:** offline evidence at `df43073` remains reproducible under v1.0 and is never mixed with v1.0.1 results.
- **Superseding:** if v1.0.1 is itself superseded before any run, the same additive pattern applies (v1.0.2 names v1.0.1 as its parent).
