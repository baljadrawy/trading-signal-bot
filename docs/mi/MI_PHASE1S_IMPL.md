# MI Phase 1S — implementation (offline only, no compute authorization), 2026-10-09

**Status:** IMPLEMENTED and tested offline on branch `feature/mi-phase1s-impl-20261009`.

**Nothing has been executed on the host** beyond bounded offline development tests:

- no pilot;
- no full Phase 1S;
- no MI activation, campaign, reservation or CPU-budget charge;
- no deployment or merge.

Neither ledger was opened or touched: the MI trial ledger (genesis `adcdc0b2…`, 0 trials) and the CPU budget ledger
`f5983b83…` (last verified remaining 28 733.117923 CPU-s).

Small-fixture tests demonstrate formulas, determinism, integrity and fail-closed behaviour. **They are not evidence of
full-scale statistical calibration.**

## 1. Verified baseline

| Item | Value |
|---|---|
| Base commit | `a47e5cccbe35d26d16dae70d70a39bbec81f5b3d` (`docs/mi-ml-historical-research-20261008`, readiness runbook) |
| Contract set MI-C v1.0 | `fdf3366480976db6ada1ac90b62f6b6db1edc35a59d1f3527cfcd6fcbf28e157` — verified before and after implementation |
| Protocol | `412cb6062ea5b4f4c9b8bd9fa34cf0d449b4f8abcab4c173858791a9f9464202` — verified |
| Frozen files | untouched; `contract.verify()` passes |
| Code tree (`phase1s/*.py`) | `1095b4fc05099ddc8881da55d90772990105c77c7e2b384b29137c69a078013b` |

**Recomputed from the frozen protocol:**

- 48 cells: T1 24, T2 18, T3 6. 11 of them are stress cells (6, 3, 2).
- 120 800 reps at ladder step 0, of which 48 000 are null.
- Worst case with both tightening steps: 216 800.
- 0 seed collisions over the full plan.
- Pilot: 4 320 reps plus 40 L2 reps.

## 2. Package `p2_research/mi/phase1s/` (stdlib only)

| File | Content |
|---|---|
| `params.py` | Every implementation choice the frozen documents leave open (`GEN`, `METHODS`), bound into the tree hash and into the output meta |
| `stats.py` | Normal and Student-t (regularised incomplete beta); stationary bootstrap; EWC Diebold–Mariano; Holm; Newton logistic; cluster-robust Cox B3 and calibration-in-the-large; Wilson (the frozen `derive.wilson_upper`) |
| `gen.py` | Seeds; AR(1) / common-factor processes; 6-step overlap; analytic skill tuning; T1 / T2 / T3 worlds |
| `rules.py` | Per-rep B1 (Holm, Bonferroni, max-p), B2, B3; truth classes null / skill / miscal / leak |
| `l2.py` | L2 logistic surrogates (T3: conditional logit) fitted on a dev draw and evaluated on the HLE draw |
| `store.py` | Self-hashed shards; hash-chained journal; atomic writes |
| `engine.py` | Plan, ladder driver, resume reconciliation, aggregation into the derivation-map schema, budget block, CPU report, pilot projection |
| `sandbox.py` | PEP 578 audit-hook allow-list and the MI-slice requirement |
| `release.py` | Frozen-input verification; non-circular code-tree identity |
| `__main__.py` | CLI: `run`, `finalize`, `project`, `plan-info`, `tree-hash`, each with `--mode offline-test\|pilot\|full` |

## 3. Protocol coverage matrix

| Frozen element | Implementation | Tests |
|---|---|---|
| 48 cells, stress flags, T2 verification cells | Read verbatim from the protocol; never edited (pilot / full refuse any protocol other than the frozen bytes) | `test_frozen_protocol_figures`, `test_mode_guards` |
| Reps: null 1000, skill 3×200, miscal 4×200, leak 100, L2 4×200; bootstrap 999 | `reps_for("full")` returns exactly the protocol counts and checks L2 4×200 = 800; no automatic reduction anywhere | `test_mode_guards`, `test_frozen_protocol_figures` |
| T1 generator (AR(1) φ, common factor ρ, 2 series × 6 × 517, 24h labels at 6× overlap, ×2 break at the HLE start) | `gen.t1_world` | `test_ar1_and_overlap_dependence`, `test_binary_worlds_base_rate_and_calibration` |
| T2 generator (n events over 517 days, day-clustered loading ρ, base rate π) | `gen.t2_world` | Base-rate and calibration test |
| T3 generator (6-state Markov chain, persistence p, uniform / adjacent off-diagonal mass, 7-day target, 517 days) | `gen.t3_world`, `transition`, `t3_design` | `test_t3_chain_design` |
| Truth class null: candidate = strongest baseline + independent noise | `null_forecast` / `t3_null` (OD-3) | Smoke and engine tests |
| Truth class skill: incremental BSS at each level | κ / w solved analytically so that the expected BSS equals the level exactly | `test_skill_tuning_hits_expected_bss` |
| Truth class miscal: slope 0.7 / 1.4 gated, intercept ±0.3 reported | `miscal_transform` on the bss_min skill candidate; `reject = B3 rejects` | `test_miscal_transform`; B3 tests |
| Truth class leak: the label enters one feature with weight w; A7 canary | `run_leak` (OD-4); `fire_count` against the task trip-wire ceiling | `test_leak_fire_is_strictly_above_ceiling` |
| B1: one-sided Brier differential versus the strongest baseline; p = max(bootstrap, DM HAC fixed-b); Holm within the task; Bonferroni ×3 across tasks | `apply_rule` (OD-1a, OD-1b) | Bootstrap, DM, Holm and short-circuit exactness tests |
| B2: log-loss differential has the same sign | `apply_rule` | Short-circuit test |
| B3: Cox slope CI ∋ 1, intercept CI ∋ 0, calibration-in-the-large CI ∋ 1 | `stats.b3_test` with time-block clusters (OD-5) | B3 tests |
| B4 / B5 / B6 | B5 = n\* is a CDP derived by `derive()`; B4 / B6 are not applicable at L1 (OD-6) | — |
| Ladder: k0 / k1 / k2 (block ×1 / ×2 / ×2, α 0.05 / 0.05 / 0.025); the whole null grid re-run per step; power / miscal / leak at the final step; FAIL → step 2 | `Engine.ladder`, `Engine.run` | `test_ladder_transitions`, engine runs |
| Acceptance: FPR 5/100 point + Wilson UB ≤ 0.07; B3 size ≤ 7 %; power ≥ 80 %; leak ≥ 95 %; L2 ≤ 75 ‰; T3 fallback 50 % | Evaluated by the frozen `derive.null_pass` / `derive()` on the engine output; the engine itself uses `null_pass` for the ladder | `test_derive_round_trip` |
| L1 / L2 layers | `rules.py` / `l2.py`; L2 runs at each L2 cell's task final step | Engine runs |
| Output `tsb.mi.phase1s_output` v1 (derivation-map `input_schema`) | `Engine.assemble` + `finalize` | `test_output_schema_and_metadata`, `test_derive_round_trip` |
| Budget block (`cgroup_cpu_budget_guard_v1`, cap 28 800, ledger-level cumulative) | `budget_block` / `validate_evidence` | `test_budget_evidence_validation` |
| Pilot: 10 reps per cell; projection P = Σ cpu/rep × planned × 1.25 + one null-grid reserve | `pilot_units`, `project` | `test_pilot_plan_is_exact_and_stratified`, `test_projection_arithmetic` |
| `reads_real_data: false` | `sandbox.py` + static checks | Sandbox probe and static tests |

## 4. Implementation choices the frozen documents do not determine — OWNER REVIEW (OD-1 … OD-8)

None of these changes MI-C v1.0. They are implementation parameters, bound into the code-tree hash. **They must be
resolved, and the tree re-pinned if anything changes, before the pilot**, because the plan hash binds the tree and the
pilot's cost and outcome depend on them.

The development diagnostics below come from bounded runs of a few reps. They are indicative, not evidence.

| ID | Open point | Implemented default | Alternative(s) | Indicative consequence |
|---|---|---|---|---|
| **OD-1a** | Contract B1 says "Holm within task (m ≤ 2); Bonferroni ×3 across tasks". Does the Phase 1S per-task null apply the ×3? | **Yes:** α_task = α_step / 3, then Holm over 2 candidates (the decision a Phase 2 claim would face). The variant without ×3 is recorded per rep (`fp_alt`, `pass_alt`) | α_task = α_step | ×3 lowers null FPR and power; n\* moves up |
| **OD-1b** | DM "HAC fixed-b": kernel and bandwidth are not specified | EWC long-run variance with ν = max(2, ⌊3 n_days / (4 L)⌋) and a Student-t(ν) reference. Exact at every Holm / Bonferroni level (down to 0.0042); ν tightens with the ladder's block length L | Bartlett with Kiefer–Vogelsang fixed-b critical values (tabulated only at 0.10 / 0.05 / 0.025 / 0.01, so extrapolation is needed at Holm levels) | ν = 77 / 38 at T1 / T2 step 0 / 1; 13 / 6 at T3 |
| **OD-2** | T1 "×2 base-rate break at the HLE start" with no model fitting at L1 | Forecasts carry the dev rate π/2; HLE outcomes occur at π (positives as listed) | Forecasts recalibrated to the HLE. This makes break = 0 and break = 1 identical at L1, so the break would only matter at L2 | **Break cells lose power: the B3 calibration-in-the-large test rejects. Diagnostic: skill pass 0/8 with the break versus 5/8 without. Expected T1 status: `INSUFFICIENT_ALWAYS`** (12 of 18 non-stress T1 cells are break cells) |
| **OD-3** | Null "baseline + independent noise": sd and persistence | sd 0.1 (probit index), with the cell's own dependence: T1 AR(φ) + factor ρ; T2 day factor ρ; T3 AR(persistence) | Larger sd gives a candidate further below the boundary and a lower FPR. Serially independent noise would make the loss differential serially uncorrelated and would not exercise HAC / blocks | — |
| **OD-4** | Leak weight w and the A7 canary definition | w = 2.0 on the logit of the bss_min skill candidate. Fire = realised BSS strictly above the task trip-wire ceiling (max of max_bss over levels and non-stress cells of the **same run**, as the derivation map defines it) | A smaller w; a label-time-shift canary | Leak BSS minimum 0.31–0.82 versus skill max 0.06–0.15 (30 reps), so firing is near-certain. The test may be too easy |
| **OD-5** | B3 CI construction | Clusters = contiguous blocks of the step's mean block length; CR1 sandwich; t(G−1, 0.975); three 95 % CIs; a structurally degenerate point CI (T3 pooled one-vs-rest sums to 1) passes iff within 1e-9 | Day clusters (diagnostic: size **100 %** in T3 because of serial persistence — rejected); a joint test; wild cluster bootstrap | **Dev size estimates 1–16 % (80–200 reps). `B3_SIZE_FAIL` (> 7 %) is a real risk in T1 φ = 0.95 and T2 ρ = 0.5 cells.** Phase 1S exists to measure this; a STOP would return to the owner |
| **OD-6** | B4 (dev-fold sign consistency) and B6 (W2 S-MAJ) at L1 | Omitted (no dev folds or W2 segment are simulated) | A pseudo-fold B4 | Null FPR is an upper bound with respect to B4 / B6; power is optimistic. n\* may be under-stated |
| **OD-7** | T3 baseline and skill construct; T3 L2 surrogate | The baseline knows the state ℓ days late (the smallest ℓ with full-information BSS ≥ 0.10, else climatology: ℓ = none / 10 / 2 / 2 / 1 / 1). The skill candidate is informed on a random fraction w of days (calibrated). L2 = conditional logit | A noisy-state observation model | T3 skill levels are attainable in every cell (w ≤ 0.81) |
| **OD-8** | Runbook order | **pilot → T3 → T2 → T1 → L2**: L2 cells need their task's final ladder step, and one L2 cell is T1. This replaces the readiness §4 order (… → L2 → T1) | L2 fixed at step 0 | — |

Also recorded, but **not** an open point: the contract's real-data B1 uses 2 000 bootstrap resamples, while the
protocol fixes `bootstrap_resamples_synthetic = 999` for Phase 1S. The protocol is used.

## 5. Statistical-method validation (offline)

- **Normal and Student-t:**
  - Φ(1.959964) = 0.975 and Φ⁻¹(0.95), to 1e-12.
  - t: Cauchy P(T ≥ 1) = 0.25; the closed form for ν = 2; t₁₀(1.812461) = 0.05; ν → ∞ gives the normal.
  - t₀.₉₇₅ for ν = 10 and 17 match tables to 1e-7.
- **Wilson** is the frozen `derive.wilson_upper` (same object, z = 1.959963984540054).
- **Holm:** step-down decisions, None handled as "> α", boundary ties.
- **Stationary bootstrap:**
  - p ∈ [1/(B+1), 1]; correct direction;
  - p-values are invariant to which series are accumulated (the shared block plan);
  - iid-null size 1–12 % over 200 replicates.
- **DM EWC:**
  - the statistic equals a hand computation to 1e-12;
  - iid-null size 2–9 % over 300 replicates;
  - correct direction;
  - ν rule values.
- **Logistic / Cox:**
  - Newton estimates equal the specialised 2-parameter fit to 1e-8 and recover the true (0.3, 0.8);
  - B3 accepts a calibrated forecast, rejects slope 0.7 (estimate within ±0.08) and intercept +0.3;
  - zero events → reject;
  - the degenerate pooled case passes.
- **Short-circuit exactness** (bootstrap skipped when p_dm > α; B3 evaluated only when it could matter): decisions are
  identical to the full computation in 25 randomised cases.
- **Generators:**
  - AR(1) lag-1 = 0.95 ± 0.02;
  - overlap: variance 1, lag-1 correlation 5/6, lag-6 correlation 0;
  - T2 base rate and binned calibration;
  - T1 dimensions (6 204 rows, 12 per day);
  - break forecasts at π/2;
  - T3 rows sum to 1, the stationary distribution is invariant, adjacency is correct;
  - analytic BSS tuning to 1e-9;
  - an unattainable level raises.

## 6. Reproducibility and release identification

- **Seeds:**
  - `sha256(contract_set | cell_id | kind | level | rep [| boot|<step> | train | eval])[:16]` seeds `random.Random`;
  - null data are identical across ladder steps (common random numbers); only the bootstrap stream depends on the
    step;
  - 0 collisions over the 120 800-rep plan.
- **Canonical output:** `derive.canon` (sorted keys, no NaN).
- **The output meta binds:**
  - `contract_set_sha256` and `protocol_sha256`;
  - `code_tree_sha256` and `impl_commit`;
  - `generator_version`, `impl_version`;
  - `methods` and `gen_params`;
  - `plan_sha256`, `seeds_sha256` and `results_sha256`;
  - reps, the shard count and the re-run summary.

  CPU timings live in `cpu_report.json` / `pilot_report.json` and are never part of the hashed output.
- **Byte-identical outputs:** a serial run and a 2-worker fork-pool run of the same plan produce **byte-identical**
  `output.json` (test).
- **Re-run check (protocol §7):** reps whose seed ≡ 0 (mod 50) — about 2 % — are recomputed inside the same worker. A
  mismatch causes a `REPRO_MISMATCH` STOP.
- **Release identity (non-circular):** `code_tree_sha256` is the SHA-256 over the sorted `<file>\t<sha256>` lines of
  `phase1s/*.py`. The commit is an attestation passed as `--impl-commit` and is never hashed into the tree.

  Pinning procedure:
  1. Commit the code.
  2. `python3 -m p2_research.mi.phase1s tree-hash --out <tmp>`.
  3. Record the hash in a later docs commit.
  4. Pilot and full runs require `--expect-tree-sha256 <pinned>` (else `CODE_TREE_MISMATCH`) and `--impl-commit
     <40-hex>`.

## 7. Checkpointing and resume

**Shards:** one per (task, kind, step, cell, level, rep chunk), written atomically (tmp → fsync → rename → dir fsync).
Each shard is self-hashed. Its plan hash, unit, exact rep range and recomputed seeds are verified on every open.

**Journal:** a hash-chained append-only `journal.jsonl` records open, `shard_commit` (file SHA-256, campaign, CPU),
`shard_adopted`, `tmp_discarded`, `shard_void`, `ladder`, `soft_cap_stop`, `repro_mismatch`, `run_done` and
`finalized`.

| State found on resume | Behaviour |
|---|---|
| Stale `.tmp` | Discarded and journaled. The reps were never recorded, so the deterministic recompute is not a new trial |
| Orphan shard (crash after rename) | Fully validated and **adopted, never recomputed** |
| Committed shard missing | `MISSING_SHARD` STOP. A recompute happens only with `--allow-recompute-missing`, journaled as `shard_void` + commit |
| Shard changed or edited | `SHARD_CHANGED` / `SHARD_SELF_HASH` |
| Truncated shard | `SHARD_UNREADABLE` |
| Wrong seeds or rep set | `SHARD_SEEDS` / `SHARD_REP_SET` |
| Unknown file | `UNEXPECTED_FILE` |
| Journal edited | `JOURNAL_HASH` / `JOURNAL_CHAIN` |
| Torn journal tail | `JOURNAL_TORN_TAIL` |
| Different plan (chunk, reps, tree, mode) | `PLAN_MISMATCH` |

Re-running a completed directory adds no `shard_commit` and reproduces the same output bytes (test).

**Separation:** the engine never imports the MI CPU guard, the budget ledger or the MI trial ledger (static test).
CPU is bounded by the guard outside the process. The soft cap (`--cpu-soft-cap-s`) is only an early stop *below* the
guard's kill. Synthetic runs are sealed manifests, not trial-ledger trials (contract `ledger.synthetic_runs`).

## 8. Isolation (fail-closed data access)

**Mechanism:** `sandbox.install()` runs before the engine is imported.

| Access | Rule |
|---|---|
| Read | Only the MI package dir (code + frozen contracts), `p2_research/__init__.py`, the stdlib, `/proc/self`, `/dev/null`, `/dev/urandom`, the output dir and explicitly passed files |
| Write | Only under the output dir |
| Always denied | `~/research-data`, `~/backups`, `~/.local/state/research-runner`, `~/.config/research-runner`, `~/ops`, the production checkout, `~/.config/tsb-backup`, docker / postgres sockets and data dirs |
| Never allowed | subprocess / exec / spawn / `os.system`; socket create / connect / bind / getaddrinfo; sqlite3; ctypes; DB / HTTP clients; imports of reader / stream / ledger / execution / P2-forward / runner / guard modules |
| Fork | Only when a worker pool is requested; children inherit the hook |

Pilot and full refuse to run outside `research-mi.slice`. Any violation raises in the call **and** is recorded;
`check()` re-raises after a library swallowed it (test).

**Negative tests (subprocess probe), all denied:** research-data, backups, the budget ledger, the anchor, `/etc`,
listing `$HOME`, writing `/tmp`, the docker socket, Popen, `os.system`, socket, sqlite3, the reader, the guard
module, fork, and the MI slice outside it.

**Allowed:** the contract read and an output write.

**Static tests:** no forbidden imports in the package, and no ledger / data paths outside the deny list.

**Threat model and limits:** this guards against *accidental* access by this package and its stdlib dependencies. It is
**not a security boundary**: native code, code that ran before `install()`, inherited descriptors and in-process
mutation of interpreter state are out of reach. W3 is excluded structurally, because no market data path is
readable at all.

**Required before the pilot (OD-ISO, runner change, separate approval):** OS-level isolation of the job unit — for
example `InaccessiblePaths=` for the denied roots, `PrivateNetwork=yes`, and read-only paths except the output dir.
Whether systemd honours these properties for the user manager must be tested; it is not provided here.

## 9. Output schema and budget semantics

**Schema compatibility:** `assemble()` emits exactly the derivation-map `input_schema`. On a full test-scaled grid
(all 48 cells), `derive()` behaves as follows:

- **output as produced:** `BUDGET_NOT_ENFORCED`, because offline runs never claim enforcement;
- **against the frozen protocol:** `PROTOCOL_MISMATCH`, because test outputs carry the scaled protocol's own hash;
- **with an in-memory TEST FIXTURE budget block:** only legitimate science gates are reached (`LEAK_CANARY_WEAK` /
  B3 / power / B2 / L2), never an `UNRESOLVED_*`, `INCOMPLETE_*` or `FINAL_STEP_MISMATCH`.

**`enforcement_verified`** becomes true only at `finalize --budget-evidence F`, where F is an operator-produced
`tsb.mi.budget_evidence` record. Checks:

- ledger id `f5983b83…` and cap 28 800;
- 0 open reservations and a 64-hex head;
- every campaign DONE with a measured charge;
- every campaign label used by a shard is covered.

The engine never reads the live ledger. `cumulative_cpu_s` is the ledger-level cumulative (readiness B3 semantics),
and `breach` is set when it exceeds the cap.

## 10. CPU instrumentation

| Measurement | Where |
|---|---|
| Per rep | `time.process_time` delta, stored in the shard `cpu` section (unhashed) |
| Per shard | Unit and re-run CPU, also in the journal |
| Per case | cell \| kind \| level |
| Per task \| kind | Stratum mean / sd / max |
| Process | `RUSAGE_SELF` / `RUSAGE_CHILDREN` and parent CPU (init + aggregation + output overhead) |

The authoritative charge remains the cgroup usage measured by the guard.

`project` implements the protocol formula: P = Σ_strata(mean CPU/rep × planned reps × 1.02 re-run) × 1.25 + one
full null-grid reserve. It reports:

- the point estimate and an upper estimate (per-stratum mean + 1.96 SE);
- the worst case with two extra ladder steps;
- a verdict against an owner-confirmed available budget: `FITS` / `FITS_POINT_ONLY` / `EXCEEDS_STOP_TO_OWNER` /
  `INCOMPLETE_PILOT`.

## 11. Pilot plan (design only — NOT executed, separate owner GO required)

| Item | Plan |
|---|---|
| Scope | All 48 cells at step 0: null 10, skill 3 × 10, miscal 4 × 10, leak 10 → **4 320 reps**; L2 4 cells × 10 → **40**; plus about 2 % re-run reps |
| Order | Stratified: all chunk-0 (5 reps) units of every task \| kind first, so a soft-cap stop still measures every stratum |
| Campaign / ceilings | `p1s-pilot`; reservation **1 800 CPU-s** (guard kill at 1 788); `--cpu-soft-cap-s 1500`; R2 600 % `--allow-elevated`, 6 workers; `--max-runtime-s 3600`. The protocol's 3 600 `budget_job_cpu_s` is superseded by the owner's 1 800 cap |
| Command | `research-run run --job-id p1s-pilot-j1 --owner agent:mi-p1s --profile R2 --allow-elevated --mi-campaign p1s-pilot --max-runtime-s 3600 --config CFG --cwd OUT -- python3 -m p2_research.mi.phase1s run --mode pilot --out OUT --workers 6 --campaign p1s-pilot --expect-tree-sha256 <pinned> --impl-commit <commit> --available-cpu-s <owner-confirmed>` |
| Admission | Readiness §4 slots (02:00–07:00 or 11:30–21:30 UTC), outside protected windows, G3 / G5 and F0 v3; `research-run admit --profile R2`; heavy / light locks free; 0 `rj-*` / `rw-*` / `mi-*` units |
| Guard / ledger | `mi ledger-check` head equals the last recorded one before **and** after; `mi open` / `close` per readiness §9; charge = measured cgroup usage |
| Reproducibility | Re-run mismatch must be 0; the code tree equals the pinned hash; seeds digest recorded |
| Health | Before / after snapshots of the 12 containers + monitor; Collector healthy; no restart |
| Stop thresholds | Guard KILL; exit ≠ 0; `SOFT_CAP_STOP`; `REPRO_MISMATCH`; any sandbox violation; `NOT_IN_MI_SLICE`; `CODE_TREE_MISMATCH`; any `LedgerError` / `CheckpointError`; container / monitor change. Each → STOP to the owner, accounting kept |
| Outputs | `pilot_report.json` (CPU per stratum / case, projection, re-run), `journal.jsonl`, `plan.json`, shards; a sealed evidence directory with SHA256SUMS; ledger head before / after; guard logs |
| Full-run GO criteria | Pilot DONE with a measured charge ≤ 1 788; 0 re-run mismatches; 0 violations; **P_upper ≤ available** (≈ 24 060 − pilot actual, owner-confirmed); OD-1…OD-8 and OD-ISO resolved; owner acknowledges the B3-size and T1-break risks (OD-5, OD-2) |

**Development cost estimate — indicative only:**
- **Basis:** 3 reps per kind on 4 representative cells, measured under `nice 19` on the shared host. This is **not**
  a pilot measurement.

**CPU per rep:**

| Task | null | skill | miscal | leak | L2 |
|---|---|---|---|---|---|
| T1 | 0.09 | 0.11 | 0.07 | 0.04 | 0.53 |
| T2 | 0.02–0.03 | 0.03–0.10 | ≤ 0.01 | ≈ 0 | 0.04 |
| T3 | 0.03 | 0.03 | 0.02 | 0.01 | 0.48 |

**What that implies:**

| Item | Estimate (CPU-s) |
|---|---|
| Pilot | **≈ 260** — well under the 1 500 soft cap |
| Full run, P (formula) | **≈ 11 800** |
| Full run, worst case (both ladder steps) | **≈ 14 600** |
| Usable for the full run | ≈ 24 060 |

The uncertainty is large: cell mix, bootstrap-trigger rates under skill and host contention all matter. The pilot
exists to replace these figures.

## 12. Offline test results

| Suite | Result |
|---|---|
| `p2_research/tests/test_mi_phase1s.py` (new) | **43 / 43 OK**, 0 skipped, about 37 s wall / 21 s CPU (`nice 19`) |
| `p2_research/tests/test_mi_phase1.py` (existing MI regression) | **38 / 38 OK** |
| Combined | **81 / 81 OK** (`python3 -W error::ResourceWarning -m unittest …`) |

The new suite's test-scaled runs use 30 days, T2 events / 10, B = 29 and reps null 3 / skill 2 / miscal 2 / leak 2 /
L2 1, with all 48 cells for the round trip.

The existing boundary test `test_mi_is_never_imported_outside_research` initially flagged the subpackage: it skips
only the exact `p2_research/mi` directory. The package uses relative imports and the existing test is unchanged.

**Untested at scale (by design):**
- real-scale null FPR, power, B3 size and leak rates;
- the real-host fork pool under the guard and the 600 % quota;
- the `research-mi.slice` path (only its refusal is tested);
- `finalize` with genuine budget evidence (no such evidence exists);
- the OS-level isolation (OD-ISO).

## 13. Remaining blockers before the pilot

| ID | Type | Blocker |
|---|---|---|
| **OD-1 … OD-8** | Scientific | Owner review of the implementation choices in §4. Code changes → new tree hash → re-test → pin |
| **OD-ISO** | Operational | OS-level isolation of the job unit (§8); a runner change with its own tests and approval |
| **R-B3** | Scientific | Indicative B3 size above 7 % in some non-stress cells (OD-5). The pilot gives a first count; the frozen gate decides |
| **R-T1** | Scientific | OD-2 makes T1 `INSUFFICIENT_ALWAYS` likely under the literal break reading |
| **INT-1** | Integration | Deployment of this package to a dedicated research directory by hash (readiness B5) and PYTHONPATH / cwd under the runner; the runner and guard live on `feature/mi-cpu-guard-20261008` (deployed inert 1eac499) |
| **INT-2** | Integration | A read-only budget-evidence export tool (guard side) producing `tsb.mi.budget_evidence` for `finalize`; not built here, to keep the ledgers separate |
| **GOV** | Governance | Readiness B3 (budget semantics) and B4 (R2 opt-in), plus separate pilot and full-run GOs |

## 14. Recommendation

- **Phase 1S implementation: complete for owner review.**
- **Pilot: NO-GO** until OD-1…OD-8, OD-ISO and INT-1 are resolved, the tree is pinned, and the owner gives a separate
  pilot GO.
- **Full Phase 1S: NO-GO** (it needs the pilot projection and a separate GO).
