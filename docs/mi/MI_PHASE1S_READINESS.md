# MI Phase 1S — final readiness review and execution runbook (read-only, 2026-10-09)

**Scope.** Assessment and documentation only.

- No MI enablement, campaign, CPU reservation or consumption.
- No change to the frozen contract.
- No synthetic calibration run.

**Verdict: Phase 1S execution is NO-GO today. The blocker is B1: the Phase 1S implementation does not exist yet.**

## 1. Verified baseline

| Item | Value |
|---|---|
| Frozen contract MI-C v1.0 | `p2_research/mi/contracts_v1_0/` @ `6f1e162`; `contract_set_sha256` **`fdf33664…e157`** (re-verified 2026-10-09); protocol `412cb606…` |
| MI **trial** ledger (P2-C ledger; H-MI trials) | genesis `adcdc0b2…` at `research-data/trading-signal-bot/mi/ledger`; 0 trials |
| MI **CPU budget** ledger (guard) | `f5983b83c32c4278996ec642d385977a`, seq 6, head **`87b44bff645d727a34c9f7092f5963b6607a6a5d831c495ae8d4a46e5fd23154`**, charged 66.882077, **remaining 28 733.117923 CPU-s**, checkpoints lag 0 |
| CPU guard | deployed inert @ `1eac499` (runner); real-kernel 4 / 4 and smoke campaign PASS (D4-R `7d4c9c2`); `mi-d4.json` `enabled: false`; research slices inactive |
| Rate cap | `research-mi.slice` CPUQuota 600 % (kernel), idle weight, swap 0 |

## 2. Protocol, grid and acceptance criteria (frozen; verified unchanged)

**Cells.** 48 in total; 11 of them are stress cells.

| Task | Cells | Stress |
|---|---|---|
| T1 | 24 | 6 |
| T2 | 18 (including the π = 0.2 B2-verification level) | 3 |
| T3 | 6 | 2 |

**Reps per cell, per ladder step:**

- null 1 000;
- skill 3 × 200;
- miscalibrated 4 × 200 (2 gated, 2 reported);
- leak 100;
- total **2 500**.

L2 adds 800 null reps. Bootstrap uses 999 resamples.

**Acceptance (frozen):**

- null FPR ≤ 5 % (point) **and** Wilson UB ≤ 7 % in every non-stress cell;
- B3 size ≤ 7 % and B3 power ≥ 80 % (slope 0.7 / 1.4);
- leak canary fires in ≥ 95 % of reps;
- L2 null FPR ≤ 7.5 %;
- the ladder has at most 2 steps, re-running the whole null grid each time;
- the derivation map produces v1.1 or STOPs.

## 3. CPU cost reconciliation

**Rep counts:**

| Component | Reps |
|---|---|
| T1 | 60 000 at step 0 (+24 000 per extra ladder step) |
| T2 | 45 000 (+18 000) |
| T3 | 15 000 (+6 000) |
| L2 | 800 |
| **Total, step 0** | **120 800** |
| **Total, worst case (2 extra steps)** | **216 800** |

**Budget:** 28 733 CPU-s minus a contingency of 10 % (2 873) minus the pilot (≤ 1 800) leaves about **24 060 CPU-s**
for the full run.

**Required mean cost per rep:**

- ≤ 0.199 CPU-s at step 0 only;
- ≤ 0.111 CPU-s if both ladder steps are needed.

**Plausibility.** These figures are **a priori and unmeasured**; no Phase 1S code exists.

- A stdlib-Python T1 rep (6 204 Bernoulli rows, day-aggregated loss differential over 517 days, 999-resample
  stationary bootstrap, Diebold–Mariano HAC, binned Cox IRLS) is estimated at **0.1–0.4 CPU-s**. T2 and T3 are
  cheaper.
- **The full grid may or may not fit.** The frozen K3 rule decides: if the pilot projection exceeds the cap → STOP to
  the owner. No silent scope reduction is allowed; any reduction is a v1.0.x protocol amendment approved by the
  owner (for example power reps 200 → 100, or the numpy path, which needs D8).

| Line item | Budget (CPU-s) |
|---|---|
| Pilot (10 reps per cell per truth class, about 2 400 reps + 40 L2) | reserve **1 800** (stop at 1 788) |
| Full run | P × 1.25 + one full null-grid re-run reserve, measured and projected from the pilot; must be ≤ 24 060 |
| Retries / failures | a failed or killed job is charged its measured CPU (or its full reservation if unreadable); **there is no free retry**. A re-run of a failed task comes out of the contingency or needs owner approval |
| Contingency | 2 873, not reserved up front |

## 4. Execution schedule (bounded; only after the GOs in §8)

| Item | Plan |
|---|---|
| Wall time | 600 % at idle priority: about 1.5 CPU-h per wall-hour on an idle host, so roughly 1.5–4 h wall for the full run plus window freezes |
| Start slots (UTC) | 02:00–07:00, or 11:30–21:30 |
| Avoid: protected windows | hh:12–25 (watchdog freeze), 23:50–00:45, 01:10–01:45. The watchdog kills after 4 200 s frozen, so never start within 2 h of 23:50 |
| Avoid: other work | G3 24 h comparison (≥ 08:29), the G5 window 08:45–09:10 if authorized, F0 v3 calibration, any G6 change, PAPER-R2 checkpoint reads (10:54 and 2026-10-11 10:54; read-only, low impact) |
| Concurrency | **sequential campaigns**, one per task, each bounding its own CPU through its reservation: pilot → T3 → T2 → L2 → T1 (largest last). Heavy lock (R2) excludes G5 and F0 v3 runner jobs |

## 5. Per-job reservations, limits and stop thresholds

| Campaign | Reservation (CPU-s) | Profile | Job `--max-runtime-s` | Guard kill at |
|---|---|---|---|---|
| `p1s-pilot` | 1 800 | R2 600 % (`--allow-elevated`) | 3 600 | 1 788 |
| `p1s-t3` | 1.25 × projected T3 + its null-grid reserve | R2 | 3 × projected wall | reservation − 12 |
| `p1s-t2`, `p1s-l2`, `p1s-t1` | the same formula | R2 | the same | reservation − 12 |

Sum of all reservations ≤ 24 060 + 1 800 ≤ remaining.

**Stop thresholds** (any one → STOP to the owner, accounting kept):

- a guard KILL verdict;
- a job exit ≠ 0, or an admission refusal for more than 24 h;
- actual CPU per rep > 1.5 × the pilot;
- cumulative Phase 1S charge > 1.25 × projection;
- any `LedgerError` or `CheckpointError`;
- the derivation map STOPs;
- a reproducibility check fails (§7);
- any data-access violation (§6).

## 6. Synthetic-only data guarantee

- The generators are pure functions of (cell, truth class, rep, seed). They are stdlib Python and read no input
  except the frozen contract JSON.
- **Required (B1 implementation):** the Phase 1S driver installs a `sys.addaudithook` allow-list on `open`,
  `os.listdir` and `subprocess`, and **fails closed** on any path outside `{contract dir, campaign output dir}`.
  `research-data/`, the Collector dataset, `backups/`, the PostgreSQL / Docker sockets and W3 are denied.
- **Required:** a static test that the Phase 1S package imports nothing from `p2_research.reader`, `stream`,
  `ledger`-data or `execution`, and no DB client.
- The job runs with no network need; any network access is a defect.

## 7. Reproducibility, evidence and PASS / FAIL

**Reproducibility:**

- deterministic seeds `sha256(contract_set | cell_id | truth | rep)`;
- canonical JSON output (`tsb.mi.phase1s_output` v1, the derivation-map input schema);
- the output binds `contract_set_sha256`, `protocol_sha256`, the code commit, the code-tree SHA-256 and the budget
  block. **Budget semantics:** `cap_cpu_s = 28 800` (the permanent cap); `cumulative_cpu_s` = **ledger-level**
  cumulative including the 66.88 CPU-s from D4; `enforcement = cgroup_cpu_budget_guard_v1`;
  `enforcement_verified = true` only if every campaign closed DONE with a measured charge;
- **re-run check:** 2 % of reps per task, re-executed in the same campaign, must be bit-identical.

**Evidence (sealed directory with SHA256SUMS):** pilot and per-task outputs; the merged output plus its hash; guard
logs; ledger, checkpoint and anchor copies (head before and after); job records; admission snapshots;
container / monitor before-and-after snapshots; the derivation-map result (v1.1 CDP or STOP code); and the git
commit of the v1.1 freeze.

**Statistical validity checks** (in the report, not gates beyond the frozen ones):

- seed-collision count 0;
- per-cell rep counts equal the plan;
- Wilson intervals per cell;
- the ladder step history;
- the B2 conservativeness verification;
- the T3 fallback flag.

**PASS / FAIL:**

| Outcome | Condition |
|---|---|
| **PASS** | every planned campaign closed DONE; the output is COMPLETE; the derivation map returns a v1.1 CDP set with no DerivationStop, which is then frozen, pushed and remote-verified. Task statuses DESCRIPTIVE_ONLY or INSUFFICIENT are valid PASS results |
| **FAIL / STOP** | any §5 stop threshold; a DerivationStop (e.g. `B2_REFERENCE_NOT_CONSERVATIVE`, `L2_MODEL_FIT_INFLATION`, `BUDGET_*`, `INCOMPLETE_*`); a reproducibility mismatch; a data-access violation |

## 8. Blockers

| ID | Type | Blocker | Resolution |
|---|---|---|---|
| **B1** | technical | **No Phase 1S implementation exists**: generators (L1 / L2), the B1 bootstrap + DM max-p test, the B3 Cox / calibration-in-the-large test, A7 canaries, power evaluation, the ladder driver, the output writer and the audit-hook sandbox | A separately approved **Phase 1S-impl** step: offline development plus synthetic unit tests (tiny CPU, no budget), then code-hash pinning (frozen and pushed before any pilot) |
| **B2** | scientific / operational | Cost feasibility is unknown; 120 800–216 800 reps against about 24 060 CPU-s | Pilot campaign (≤ 1 800 CPU-s) → projection → owner decision. A protocol reduction needs an approved v1.0.x amendment *before* the full run |
| B3 | governance | The derivation-map budget block semantics (cap 28 800 vs remaining 28 733; ledger-level cumulative) are an interpretation | Owner confirms §7 semantics; no contract change needed |
| B4 | operational | 600 % needs the R2 profile (`--allow-elevated`) and the heavy lock; scheduling against G3 / G5 | Owner opt-in for R2 under MI; schedule per §4 |
| B5 | integration | Phase 1S code (`p2_research/mi`, MI branch) and the runner / guard (`feature/mi-cpu-guard`) live on different branches; neither is merged | Deploy the Phase 1S package to a dedicated research directory (not the runner) by hash, as part of the pilot approval |
| B6 | governance | Separate explicit owner GOs: Phase 1S-impl → pilot → full run | — |

## 9. Runbook (for owner review; nothing here has been executed)

**Step 0 — implementation (Phase 1S-impl, separate GO; no CPU budget).**

- Implement §6 and §7 in `p2_research/mi/phase1s/`, stdlib only.
- Offline unit tests: tiny reps, determinism, schema validation, the audit hook, and the derivation-map round-trip on
  a synthetic small output.
- Pin the code tree hash, commit, push and verify. **Phase 1S may not start before this hash is pushed.**

**Step 1 — preflight** (each run day):

1. UTC slot per §4.
2. `research-run admit --profile R2` admits.
3. Heavy and light locks free; 0 `rj-*` / `rw-*` / `mi-*` units.
4. `mi ledger-check` OK, with the head equal to the last recorded one.
5. Snapshot 12 containers and the monitor.
6. Deployed hashes for runner `1eac499` and Phase 1S code at the pinned hash.

**Step 2 — enable (dedicated config only).** Set `~/.config/research-runner/mi-d4.json` (or a new
`mi-phase1s.json`) to `{"mi":{"enabled":true}}`.

**Step 3 — pilot (separate GO):**

```
research-run mi open --campaign p1s-pilot --reservation-cpu-s 1800 --config CFG
research-run run --job-id p1s-pilot-j1 --owner agent:mi-p1s --profile R2 --allow-elevated --mi-campaign p1s-pilot \
    --max-runtime-s 3600 --config CFG --cwd OUT -- python3 -m p2_research.mi.phase1s --mode pilot --out OUT
research-run mi close --campaign p1s-pilot --config CFG
```

Then compute the projection, seal the evidence, and **STOP for the owner decision** (full run, or a v1.0.x
amendment).

**Step 4 — full run (separate GO):** per task in the order T3, T2, L2, T1:

1. `mi open --campaign p1s-<task> --reservation-cpu-s <§5>`;
2. `run … --mode <task>`;
3. `mi close`;
4. check the §5 thresholds after each task.

**Step 5 — merge and derive.** Merge the per-task outputs into `tsb.mi.phase1s_output`, run `derive()`, and freeze
MI-C v1.1 (CDP only) if no STOP. Commit, push and verify; record the ledger head in the GitHub evidence.

**Step 6 — disable.** Set `enabled: false`; stop the empty research slices after a 0-process check; compare
container and monitor snapshots.

## 10. Recommendation

- **Phase 1S execution: NO-GO** (B1: no implementation; B2: cost unproven).
- **Next: GO recommended for Phase 1S-impl only** (offline development and tests, no CPU-budget use). That is
  followed by a pilot GO (≤ 1 800 CPU-s) and then a full-run GO, each separately approved.
