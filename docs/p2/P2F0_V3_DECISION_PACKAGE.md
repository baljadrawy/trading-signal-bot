# P2-F0 v3 — decision package (design only, not frozen)

**Status:** owner decision package, 2026-10-08. **Nothing here is frozen or implemented.**

- **Governing baseline:** F0 contract set v2 `617cd797…6e78f42`. It is unchanged; this document only proposes a v3.
- **Branch:** `feature/p2f0-adversarial-validation-20261006`. Not merged, not deployed.
- **RM0:** D-RM0-2 is technically ACCEPTED at `623e6e80` on `feature/p2rm0-portfolio-risk-20261006`. It is not
  merged and not deployed.

**Inputs used:**

- the frozen v2 contracts;
- the sealed v2 calibration evidence `p2f0-20261006T142705Z` (C1–C7 JSON; synthetic only);
- the P2-X join code `p2_research/execution/join.py`;
- deterministic arithmetic in `docs/p2/p2f0_v3_decision_calc.py`. Its stdout SHA-256 is `0c599d41…` and it
  reproduces every number below.

**Not done:**

- no Monte Carlo;
- no W3, trial, Paper or real forward data read;
- no frozen file modified;
- no Collector, Paper or G5 touch.

**Rule kept throughout:** no threshold is lowered to obtain a PASS. Every change proposed below is one of these
kinds:

- a Monte-Carlo sample size chosen so a frozen bound is *attainable*;
- a scope split justified by downstream consequence;
- an added generator;
- a *stricter* forward rule.

v3 must be frozen strictly before the first `trial_result` of round 1. The ledger is still at genesis (seq −1), so
v3 can still govern.

## 1. C4 — null-calibration sample size and acceptance rule

**Frozen v2 criterion (C2/C3/C4):**

- screen-pass point estimate ≤ 0.10;
- PROVISIONAL Wilson-95 upper bound ≤ 0.05.

C4 ran 50 reps and observed 0/50 at every level. It FAILED only because 0/50 has an upper bound of 7.1 %.

**What the bound needs (Wilson 95 %, two-sided z = 1.96):**

| events k | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| min n for upper bound ≤ 0.05 | 73 | 110 | 142 | 173 | 202 | 230 |

**P(criterion passes)** depends on n and on the battery's true PROVISIONAL rate p:

| n | max k allowed | p = 0 | p = 0.5 % | p = 1 % | p = 2 % | p = 3 % |
|---|---|---|---|---|---|---|
| 50 (v2) | none | 0 | 0 | 0 | 0 | 0 |
| 100 | 0 | 1.00 | 0.61 | 0.37 | 0.13 | 0.05 |
| 150 | 2 | 1.00 | 0.96 | 0.81 | 0.42 | 0.17 |
| **300** | 7 | 1.00 | 1.00 | **0.99** | **0.75** | 0.32 |
| 500 | 15 | 1.00 | 1.00 | 1.00 | 0.95 | 0.57 |

The observed PROVISIONAL count across all in-sample nulls is 0/250 (C2 0/100, C3 0/100, C4 0/50). The screen-pass
point criterion (≤ 0.10) already has ≥ 0.96 pass probability at n = 50 for a true rate ≤ 5 %.

**Compute cost.** The v2 run was 2635 CPU-s for about 1240 battery reps (C1 included), which is ≤ 2.12 CPU-s per
rep on average. Per-cell timing was not recorded, so this is an average ceiling, not a per-cell figure.

- C4 at n = 300 under the calibration repetition profile (199 / 49 / 49): ≤ 640 CPU-s. That is about 3–5 min wall
  under R1 (4 workers), or about 21 min at the old 50 % single-process envelope.
- At protocol repetitions (1999 bootstrap): ≤ about 10×, i.e. ≤ 1.8 CPU-h.

**Recommended default (D-F3-1):**

- C4 at **n = 300**, predeclared;
- the criterion is unchanged (upper bound ≤ 0.05, screen point ≤ 0.10);
- a 10-rep timing pilot runs inside the same authorised R1 window before the full run;
- C2 and C3 stay at n = 100 (they already pass).

Rejected alternatives:

- a C1-style non-inferiority rule (point ≤ 0.05 and *lower* bound ≤ 0.05). It is weaker: it cannot demonstrate a
  low PROVISIONAL rate.
- n = 100. It passes a good battery (p = 1 %) only 37 % of the time.

## 2. C7 — what actually failed, separated by cause

**Frozen v2 criterion (every non-best_of cell):**

- forward-eligible Wilson upper bound ≤ 0.15;
- **and** ≥ 80 % of reps decided by a listed catching test.

| cell | forward-eligible | decided by listed test | rest of the verdicts | listed tests |
|---|---|---|---|---|
| fee_blind_gross_edge | 1/30 (UB 16.7 %) | 17/30 = 57 % | FRAGILE 10, INSUFFICIENT 2, FCR 1 | A01, E02 |
| btc_beta_as_alpha | 0/30 | 19/30 = 63 % | FRAGILE 9, INSUFFICIENT 1 | A01 |
| trend_timing_as_alpha | 0/30 | 21/30 = 70 % | FRAGILE 8, INSUFFICIENT 2 | A01, E08 |

The other nine non-best_of cells pass both parts: 0/30 forward-eligible, and 90–100 % decided by a listed test.

**Cause 1 — the acceptance criterion is not attainable by the Monte Carlo (criterion defect).**

- At n = 30 the safety bound tolerates **zero** events, since 1/30 already gives an upper bound of 16.7 %.
- A battery whose true rate equals the measured base null screen rate (1–2 %, C2/C3) passes only 55 % of the time.
- The fee-blind 1/30 is statistically indistinguishable from that base rate: P(≥ 1 of 30 | p = 2 %) = 0.46.
- This is the C4 defect class: the bound is right but n is too small.
- Needed: k = 1 needs n ≥ 34, k = 3 needs n ≥ 55. At **n = 100 per cell** up to 8 events are tolerated, and
  P(pass | p = 3.3 %) = 0.99.

**Cause 2 — classification and routing at n ≈ 13 (a battery property, not a bug).**

- For beta and trend timing, A01 (net alpha ≤ 0) misses because the day-average-factor beta is estimated from 13
  noisy days. The alpha point estimate is then positive in 30–40 % of reps.
- Those reps are stopped by A02 (BTC alpha), E08 (benchmark), E03 (STRESS) or E05 (cost share). They end
  **FRAGILE**, which is also terminal and not forward-eligible. Nothing downstream differs between REJECTED and
  FRAGILE.
- So the safety outcome is met and the *attribution* is not.
- The routing target cannot be reached by adding reps. With a true routing rate of 0.65,
  P(point ≥ 0.80) = 0.06 at n = 30 and ≈ 0 at n = 100.
- This is the documented "timing credit" limitation (section 12 of the foundation doc) and the A01 noise point
  (W8).

**Cause 3 — generator weakness (fee-blind only).**

- The fee-blind generator plants a gross edge of 11.5 bps against about 26 bps costs, i.e. an oracle net of −10 bps.
- That defect is below the battery's resolution: true +10 bps has 3 % screen power.
- So "REJECT via A01" is a *power* expectation the battery cannot meet at any plausible n. The project's real
  fee-blind history was a much larger shortfall (net PF 0.415, fees ≈ 85 % of gross).
- The generator tests the right class at an unrealistically mild magnitude.

**What not to do:**

- widen the listed catching tests now that the results are known (post-hoc);
- lower the 80 % or 15 % targets;
- make A01 reject on an upper confidence bound. That changes the primary REJECT semantics and trades attribution
  for power. It is deferred to a later version and needs explicit owner sign-off.

**Recommended default (D-F3-2):**

1. **Split C7.**
   - **C7a (safety gate):** forward-eligible Wilson upper bound ≤ 0.15, unchanged, at **n = 100 per cell**.
   - **C7b (attribution):** the listed-test share is *reported* against the unchanged 80 % target, and each rep
     records its binding test. A miss is documented as a limitation and does not gate.

   The justification is by consequence: both REJECTED and FRAGILE are terminal.
2. Keep the −10 bps fee-blind cell as is. **Add** `fee_blind_historical`, with net ≈ −50 bps (gross well below cost),
   predeclared with A01 and E02 as catching tests.
3. Cost: 14 cells (plus 1) × 100 reps ≈ 1500 reps, ≤ 3200 CPU-s under the calibration profile. That is about
   15–20 min wall under R1.

## 3. Forward-test duration

v2 rule: n = ⌈((z₀.₉₅ + z₀.₈)·sd / (0.5·mean))²·deff⌉, clamped to [28, 120]; unclamped > 120 → FCR with
`forward_infeasible`. It sizes from the noise-inflated in-sample estimate.

- The SE of a 13-day annualized Sharpe is ≈ 5.3. A candidate is feasible only if its in-sample annualized alpha
  Sharpe is ≳ 8.7.
- Conditional on passing a 13-day screen, that figure is mostly winner's curse.

**t-test upper bound on power** (1 obs/day, one-sided 5 %, m = 1, deff = 1):

| days | S = 2 | S = 3 | S = 4 | S = 6 | MDE at 80 % | SE(S) |
|---|---|---|---|---|---|---|
| 28 | 0.14 | 0.21 | 0.30 | 0.51 | 9.0 | 3.6 |
| 56 | 0.19 | 0.32 | 0.47 | 0.76 | 6.4 | 2.6 |
| **120 (v2 cap)** | 0.31 | 0.53 | 0.74 | 0.96 | 4.3 | 1.7 |
| 180 | 0.41 | 0.68 | 0.88 | 0.99 | 3.5 | 1.4 |
| 252 | 0.51 | 0.80 | 0.95 | 1.00 | 3.0 | 1.2 |
| 365 | 0.64 | 0.91 | 0.99 | 1.00 | 2.5 | 1.0 |

**Days for 80 % power:**

| | S = 2 | S = 3 | S = 4 | S = 6 |
|---|---|---|---|---|
| m = 1, deff = 1 | 565 | 251 | 142 | 63 |
| deff = 1.25 | 706 | 314 | 177 | 79 |
| Holm with m = 3 (first step, α/3) | 805 | 358 | 202 | 90 |

With 3 registered candidates and deff 1.25, power at 120 / 252 / 365 days is 0.14 / 0.26 / 0.37 for S = 2 and
0.47 / 0.80 / 0.93 for S = 4.

**These are upper bounds.** The full battery passes fewer reps than a bare t-test. C6 measured a forward
PROVISIONAL rate of 27 % at 56 days for +100 bps.

| option | rule | what an S = 3 edge gets | Collector horizon |
|---|---|---|---|
| F-A keep v2 | in-sample sizing, cap 120 | usually `forward_infeasible`; if run, 53 % power | ≤ 4 months |
| **F-B plausibility floor** | n = max(v2 formula, n(S = 4)·deff̂) ≈ 180 days, cap 365 | 68 % (S = 4: 88 %) | **6 months, up to 12** |
| F-C target S = 3 | n = n(S = 3)·deff̂ ≈ 251–314 days | 80 % | 10–12 months |
| F-D fixed 120, screen-only | always 120 days; may never reach an Alpha verdict; outcome FORWARD_INSUFFICIENT unless significant, with a CI on S | 53 % | 4 months |
| F-E S = 2 | ≥ 565 days | 80 % | about 19 months (not practical) |

**Common to all options:**

- weekly harm-only monitoring (unchanged);
- no early success (unchanged);
- **when the result is not significant at the planned end, the verdict is FORWARD_INSUFFICIENT, never an Alpha
  verdict**;
- the report always carries the forward Sharpe CI and the MDE achieved, so INSUFFICIENT is not misread as
  "no edge".
- Prefer m = 1 per forward test: m = 3 costs about 1.43× days.

**Recommended default (D-F3-3): F-B.** It is the shortest rule with useful power at the plausibility bound, and it is
stricter than v2. It requires an owner commitment to a Collector horizon of at least 6 months. If the owner will not
commit beyond 4 months, choose **F-D**, explicitly accepting that a plausible edge will most likely end
FORWARD_INSUFFICIENT.

## 4. P2-X join-hash binding and RM0 integration prerequisites

**P2-X (open weakness W2).** v2 binds the P2-C dataset but not the execution join that produced `net_*`. The join
tool already emits a hashable manifest (`tsb.p2x.join_manifest`, `join_version p2x1-join-v1`). Its `logical_hash`
covers:

- `code_commit` and `code_tree_sha256`;
- `contract_set_sha256` (X1);
- the market-data meta and segment hashes;
- the P2-C manifest logical hash and the features hash;
- `joined.jsonl.gz` and `join_report.json` hashes.

**Proposed v3 binding:**

- `evidence.execution` = {`join_manifest_logical_hash`, `joined_sha256_uncompressed`, `p2x_contract_set_sha256`,
  `join_version`, `nets_producer`: {commit, output hash}}.
- It is equal to `registration.execution`.

F0 then checks, read-only (new I-tests, fail-closed to INVALID_EVIDENCE):

1. The manifest's `p2c_manifest_logical_hash` equals `evidence.dataset.dataset_hash`.
2. `pit_violations_total == 0`, the join key is unique, and the ambiguity count is 0.
3. Every evidence row key (instrument_id, decision_time_ms) is in the joined set. Unmatched rows count as refusals.
4. The P2-X contract hash is in the allowed set (v2 `f20e22a5…`, plus X1 as recorded).

**Prerequisite to verify before freezing:** a hashed, versioned *nets producer* (joined legs → row `net_base` /
`net_stress` / `net_idealized`). If none exists as a separate manifested step, it is a P2-X deliverable, and v3 binds
only what exists.

**RM0.** `risk_inputs` stays refused (I01), and I08 stays as F0's own check. Admission needs all of:

1. owner acceptance and **merge** of RM0 (`623e6e80` or its successor);
2. binding of the RM0 base set `9d9faaf6…` plus `units_amendment_sha256` (RM0-UNITS 1.1.0) and the merged commit;
3. PIT snapshots at decision time, identified by `snapshot_id`;
4. RM0 mixed-quote refusal treated as an F0 refusal, never as a value;
5. **a descriptive-only role**: no RM0 metric enters the estimand or any verdict until a later version pre-registers
   one.

**Recommended default (D-F3-4 / D-F3-5):**

- bind the P2-X join in v3;
- do **not** wait for the RM0 merge. v3 keeps the refusal and freezes the admission schema above as a stub. A v3.1
  admits RM0 after it is merged.

## 5. Independent red team and Romano-Wolf / DSR null studies

**Red team (W7).** The catch rates are optimistic because I wrote the battery and the generators together. Proposed
protocol:

- **Author.** A separate author: a human, or a fresh session with access only to the evidence schema, the verdict
  taxonomy and the public P2-D0 plan. The author has no access to `battery.py`, the calibration code or this
  package.
- **Generators.** At least 8: the known failure classes re-implemented independently, plus at least 3 novel ones.
- **Sealing.** The generator code and its expected outcomes are hashed and pushed **before** any battery run.
- **Running.** One run at n = 100 per cell (cost ≈ C7).
- **Reporting.** The catch rate, the forward-eligible rate with Wilson bounds, and every miss.
- **No tuning.** Misses go to a later version and never into v3 after the run.

**Owner action:** name or schedule the author. It cannot be this session.

**Romano-Wolf / DSR dedicated null study (W4; proposed C8):**

- **Rounds.** Full 48-cell rounds with the frozen P2-D0 sibling structure (shared rows) under three regimes:
  - (i) complete null;
  - (ii) partial null (4 true +50 bps cells; FWER over the true nulls only);
  - (iii) AR(0.5) stress.
- **Metrics.** M01 FWER at 0.05, the S02 screen pass rate, and the M02 false-pass rate at N = 48 and at N = 48 plus
  abandoned trials.
- **Acceptance (C1-style, frozen before the run).** For (i) and (ii): FWER point ≤ 0.065 **and** Wilson lower bound
  ≤ 0.05 at **1000 rounds**. (iii) is reported as stress.
- **Cost.** ≤ 2.1 k CPU-s per 1000 rounds under the calibration profile, and ≤ about 10× (≈ 6 CPU-h) at protocol
  repetitions. The average ceiling may understate a 48-cell round, so a 10-round timing pilot runs first.
- **Window.** It runs under R1 within one authorised window, or two.

**Total v3 calibration envelope (C4 + C7 + C8 + red team):** ≈ 2–8 CPU-h depending on the repetition profile. It
runs via the G2 runner R1 only, with admission gates and protected windows. It is not concurrent with G5, and it
needs the same compute authorization class as G5.

## 6. Owner decisions required before freezing v3

| # | Decision | Options | **Recommended default** |
|---|---|---|---|
| D-F3-1 | C4 rule and n | n = 100 / **300** / 500; criterion unchanged | **n = 300**, upper bound ≤ 0.05 unchanged, timing pilot first |
| D-F3-2 | C7 structure | keep as a single gate (will fail on attribution) / **split C7a safety gate + C7b reported attribution** / widen catching lists (rejected: post-hoc) | **Split; n = 100 per cell; add `fee_blind_historical`**; A01 unchanged |
| D-F3-3 | Forward duration | F-A / **F-B** / F-C / F-D / F-E | **F-B** (≈ 180 days, cap 365, INSUFFICIENT when not significant); fallback F-D if the horizon is ≤ 4 months |
| D-F3-3b | Collector horizon commitment | 4 / **6** / 12 months | **≥ 6 months**: an owner resource decision, linked to G6 |
| D-F3-3c | Forward set size | ≤ 3 (v2) / **1 preferred** | **m = 1 preferred**, ≤ 3 allowed (× 1.43 days) |
| D-F3-4 | P2-X join binding | **bind in v3** / defer | **Bind in v3**, after the nets-producer prerequisite is verified |
| D-F3-5 | RM0 in v3 | wait for merge / **keep refusal plus admission stub** | **Refusal plus stub**; v3.1 after the RM0 merge |
| D-F3-6 | Red team | **approve, with a named independent author** / skip | **Approve**; required before the first real use |
| D-F3-7 | Romano-Wolf / DSR null study C8 | **approve with C1-style criteria at 1000 rounds** / skip | **Approve** |
| D-F3-8 | Fixed thresholds (`PROPOSED_NOT_OWNER_APPROVED`) | **approve as frozen** / revise | **Approve as frozen.** Revising them after seeing synthetic results is a forking path. |
| D-F3-9 | 4h calibration (W6) | **add C2 / C5 analog cells for 4h** / skip | **Add**; cost estimated from the timing pilot |
| D-F3-10 | Compute for v3 calibration | authorize R1 window(s) / defer | Authorize **after** the G3 comparison and the G5 decision. Never concurrent with G5. |

Approving D-F3-1 to D-F3-10 authorizes only the drafting of the v3 contract files. Freezing, the pushed freeze
commit and the calibration run each remain separate gates.
