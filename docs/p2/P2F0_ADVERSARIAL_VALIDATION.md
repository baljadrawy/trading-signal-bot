# P2-F0 — Adversarial validation foundation

**Status:** foundation only, frozen 2026-10-06 **before any Alpha outcome exists** (contract set **v2**
`617cd797…`, which superseded v1 `9f42105d…` before any use). Branch
`feature/p2f0-adversarial-validation-20261006` (base `a65bbfb` = P2-X1, on P2-X0 and the P2-D0 frozen protocol
`6db8ba5`). Not merged, not deployed. No H01–H07 outcome, no planned trial, no W3 data, no PAPER-R1 result and no
real forward data was read or computed. Every number in this document comes from **synthetic** data.

- Code: `p2_research/falsification/` (stdlib only, deterministic seeds, never imports `p2_forward`).
- Frozen contracts: `p2_research/falsification/contracts_v2/` (governing) and `contracts/` (v1, superseded before
  any use; kept byte-identical) — section 11.
- Tests: `p2_research/tests/test_falsification_f0.py`.
- Evidence: `/home/tradmin/backups/tsb-aiohttp-20260929T122701Z/p2f0-<UTC>/`.

P2-F0 is the adversary of every future candidate. Its job is to show that an apparent edge is false, fragile,
accidental, overfit, economically unrealistic or unlikely to survive forward trading. It never says "proven".

## 1. The one fact that shapes everything: sample size

| Quantity (P2-D0 round 1) | Value |
|---|---|
| validation days (folds 15–21, 22–28) | 14; **13 usable at 24h** (day-28 labels read day 29, section 7.3) |
| independent observations | about one per day: positions entered on the same day share the BTC / market factor |
| symbols | about 39, heavily correlated |
| trials | 48 planned (+ benchmarks, + any later round) |

At 13 day-observations the standard error of a daily Sharpe ratio is about 0.28, i.e. **about 5.3 annualized**.
An edge that 13 days can detect at 80 % power needs an alpha Sharpe of roughly 12–15 annualized. That is far
beyond what any plausible crypto strategy earns after costs. Calibration (section 9) shows the consequence directly.

**Consequence (design decision D1):** round 1 can **screen and reject**; it cannot confirm. Confirmation comes
only from a pre-registered forward test of adequate length (section 8). Forward data are independent of the screen,
so the forward family-wise error is controlled however liberal the screen is (sample splitting). The in-sample stage
is therefore strict about integrity, economics and artifacts, and deliberately liberal about significance.

## 2. Architecture

```
P2-D1 (future)                      P2-F0 (this package)
row panel of the evaluation   -->   battery.Battery.evaluate(evidence, round_context)
window for ONE trial                  1 integrity          I01-I10  (fail -> INVALID_EVIDENCE)
(all eligible rows, signal flag,      2 minimum n          N01      (fail -> INSUFFICIENT_EVIDENCE, nothing computed)
 gross + 3 nets, PIT times)           3 economics          A01 E01-E09
                                      4 attribution        A02 A03 E08
round context (every evaluated        5 robustness         R01-R12 (deterministic + noise-calibrated)
 trial's alpha series, sibling        6 placebos           P01-P03
 p-values, ledger counts)             7 significance /     S00 S01 S02 M01 M02
                                        multiplicity
                                    -> tsb.p2f.verdict (one verdict, every test, reasons, verdict_id)
forward window (registered)   -->   same battery (window.kind = forward) -> forward.forward_verdict
```

- `panel.py` rebuilds positions from rows using the P2-D0 rule: one open position per symbol, entry only when flat,
  time exit at the horizon. **P2-F0 never trusts a candidate's own positions or metrics.** Claimed positions are only
  cross-checked (I07). Placebos go through the same rule.
- `stats.py` holds the inference core: stationary bootstrap, Bartlett HAC and n_eff, Student t, OLS with HAC,
  Holm / BH, Romano-Wolf, PSR / DSR, O'Brien-Fleming spending and a Westfall-Young joint tail.
- `contracts.py` covers frozen-set verification, dependency hashes, candidate registration, ledger cross-checks
  and the anti-retroactive version rule.
- `forward.py` covers forward length, harm monitoring and the forward verdict.
- `synthetic.py` and `calibration.py` hold the generators and the frozen calibration study.

## 3. The primary estimand: net alpha (and why not raw net or vs-control)

`a_d = p_d − β̂·m_d`, where:

- `d` runs over the evaluation days;
- `p_d` is the candidate portfolio value under **EXEC-BASE**: the equal-weight mean net return of the positions
  entered on day `d`, with cash = 0 on a day without entries;
- `m_d` is the **cost-free** unconditional-long factor: the mean gross label of all eligible rows of the day;
- `β̂` is estimated by OLS, so `mean(a)` is the OLS alpha.

This estimand has four properties:

- It **charges every cost**: gross > 0 alone can never pass, which follows the P2-X1 principle.
- It **removes market beta**, which is also most of the day-to-day noise. Raw net returns over 13 days are mostly a
  bet on the market.
- It **credits timing as well as selection**: being in cash on bad days earns alpha.
- It is **absolute, not relative**. P2-D0's vs-control contrast can call a loss-reducing filter "supported" while
  it loses money (finding F-D0-1). P2-F0 still reports that contrast (E04).

**Inference (contract set v2):**

`p = max(p_stationary-bootstrap, p_batch-means-t, p_fixed-b-HAC)`, one-sided.

- **Block length:** L = max(3 days at 24h / 2 at 4h, ⌈n^(1/3)⌉).
- **Batch means:** non-overlapping batches of L days, Student t with k − 2 df (one df for β).
- **Fixed-b HAC:** the Bartlett HAC t referred to its own simulated iid-normal null at the same n and lag
  (4999 draws, deterministic).
- **Bootstrap:** 1999 replicates; seed = `sha256(contract_set|trial|test)`.

Each component is a valid test under its own assumptions; the maximum is never less conservative than any of them.

**Why v2 exists.** Contract set **v1** (`9f42105d…`) used `max(bootstrap, HAC-t)`. Its own frozen calibration
study C1 **failed**. At n = 14 and nominal 5 %, v1 rejected a true null at these rates:

| Series | v1 false-positive rate |
|---|---|
| iid normal | 8.6 % |
| AR(0.3), t4 innovations | 9.3 % |
| AR(0.5), t4 innovations | 14.0 % |

The bootstrap alone rejected at 10–17 %. Per v1's own rule, v1 was not tuned. It was **superseded by a new
version before any use**: no candidate and no real outcome was ever evaluated under it, and its files stay
byte-identical as the record. Both versions are frozen at the genesis ledger head, and v2 governs
(`contracts.versions`, `applicable_version`).

## 4. Tests: purpose, method, assumptions, failure modes

Effect = what a FAIL (or UNDETERMINABLE) does to the verdict (section 5).

**Integrity — INVALID_EVIDENCE**

| ID | Purpose / method | Defends against |
|---|---|---|
| I01 | Schema and scope: long-only, horizon 4h / 24h, H01–H07. Information-mode trials and any `risk_inputs` block are refused (RM0 pending). | out-of-scope claims |
| I02 | Binding to the frozen F0 contract set, the P2-D0 sums `2bedc3f5…`, the P2-X v2 sums `f20e22a5…` and the frozen plan entry (hash, hypothesis, horizon). The candidate must be among `considered_trials`. | silent spec drift, cherry-picked spec |
| I03 | No row inside or reading W3; microsecond-exact boundary. | holdout contamination |
| I04 | In-sample days must equal the frozen layout (15–28, folds 15–21 / 22–28); forward days must equal the forward registration; every row must lie inside its declared day. | **peak-boundary / window selection** |
| I05 | PIT: features available ≤ T; T < entry ≤ T + 60 s; label ≥ horizon. | **look-ahead** (declared) |
| I06 | Unique (symbol, T); on-grid times. | **clone rows** |
| I07 | Claimed positions = P2-F0 rebuild. | **clone re-entry while open** |
| I08 | One quote currency (fail closed). | the D-RM0-2 defect class |
| I09 | Signals only on evaluable rows. | selection on availability |
| I10 | Implausibility tripwire: PSR(alpha Sharpe > 4 annualized) ≥ 0.95, or a Wilson lower bound of the market-excess hit rate > 0.75 → leakage audit. It works on market-adjusted series, so a bull market does not trip it while leakage does. | **hidden look-ahead**, "too good to be true" |

**Minimum n (N01) — INSUFFICIENT_EVIDENCE, and no statistic is computed or reported.** The thresholds are 14
validation days, 10 active days, 30 positions, 5 symbols and n_eff ≥ 7.

**Economics and attribution**

| ID | Rule | Effect |
|---|---|---|
| A01 | net alpha ≤ 0 (exposure or costs explain the return) | REJECT |
| E01 | EXEC-BASE net significantly negative (upper bound < 0) | REJECT |
| E02 | upper bound of the gross edge < mean measured cost | REJECT |
| P01 | worse than the median exposure-matched random entry | REJECT |
| E09 | EXEC-BASE net point ≤ 0 in the window | FRAGILE |
| E03 | EXEC-STRESS alpha or net ≤ 0 | FRAGILE |
| E04 | not above the P2-D0 control (relative, reported) | FRAGILE |
| E05 | cost / gross alpha > 0.5 (thin edges are fragile to ASSUMED costs, with impact UNAVAILABLE) | FRAGILE |
| E06 | refusal rate > 5 %, refusal gap vs control > 2 pp, or imputed refusals flip the sign | FRAGILE |
| E07 | no alpha on positions where 500 USDT fits the displayed depth (capacity; never a capacity claim) | FRAGILE |
| E08 | alpha ≤ 0 after adding BENCH-BTC-TREND or BENCH-TSMOM as a factor (it is the trivial benchmark) | FRAGILE |
| A02 | BTC-model alpha ≤ 0 | FRAGILE |
| A03 | alpha < 50 % of the raw mean | PROVISIONAL only |

**Robustness.** At 14 days the fixed, D0-style rules fail often for *honest* edges. The pilot measured this
directly (section 9.4). So they block only PROVISIONAL. FRAGILE comes from tests calibrated to sampling noise.

| ID | Rule | Effect |
|---|---|---|
| R01 | alpha > 0 in both folds | PROVISIONAL |
| R02 | alpha > 0 after removing the best ⌈10 %⌉ days | PROVISIONAL |
| R03 | leave-one-symbol-out minimum > 0 | PROVISIONAL |
| R04 | > 0 after removing the top ⌈1 %⌉ positions | PROVISIONAL |
| R05 | top-symbol share ≤ 0.5 and best-day share ≤ 0.5 | PROVISIONAL |
| R06 | positive in the tier holding most positions | PROVISIONAL |
| R07 | positive in every regime with ≥ 3 days (needs ≥ 2 such regimes) | PROVISIONAL |
| R08 | plateau: every P2-D0 grid neighbour has a positive **gross information effect**, with median ≥ 0.25 × the candidate's (F-D0-5) | PROVISIONAL |
| R10 | p ≤ 0.10 at mean block 1 and 5 | PROVISIONAL |
| R09 | the signal one decision row stale keeps ≥ 25 % of the alpha (leak or latency knife-edge) | FRAGILE |
| R11 | **joint day fragility**: alpha after the best days, best-day share, fold minimum and regime minimum. Reference: iid t(4) days at the observed mean with a **robust** (MAD) scale; Westfall-Young joint p ≤ 0.10. | FRAGILE |
| R12 | **joint symbol fragility**: LOSO minimum, top-symbol share and main-tier alpha. Reference: within-day permutation of the per-position alpha; joint p ≤ 0.10. | FRAGILE |

**Placebos**

| ID | Rule | Effect |
|---|---|---|
| P02 | beats exposure-matched random entry at 0.05. Same tier counts, uniform over the window, same position rule, same alpha statistic. | PROVISIONAL |
| P03 | beats circular time shifts of the signal (offset ≥ 2 horizons) at 0.05. UNDETERMINABLE when 1/(days − 4 · horizon_days) > 0.05, which always holds at 14 days. | PROVISIONAL |

**Significance and multiplicity**

| ID | Rule | Effect |
|---|---|---|
| S00 | screen: raw net-alpha p ≤ 0.20 | INSUFFICIENT |
| S02 | selection-aware screen: Romano-Wolf adjusted p over **every** evaluated trial of the round ≤ 0.50. The round must be supplied. | INSUFFICIENT |
| S01 | Holm within the hypothesis (P2-D0), or Bonferroni with m = max(plan, ledger) while a sibling is missing | PROVISIONAL |
| M01 | Romano-Wolf ≤ 0.05 | PROVISIONAL |
| M02 | deflated Sharpe ≥ 0.95 | PROVISIONAL |

M02 details:

- N = every ledger trial except benchmarks: pending, aborted, failed and inconclusive trials included.
- Effective N = 1 + (N − 1)(1 − mean|ρ|), with ρ taken over evaluated trials only.
- The variance is the null 1/(n − 1).

Abandoned trials enter N, so stopping a trial cannot hide it. PBO/CSCV is **not used**: P2-D0 selects nothing by
in-sample fit, so PBO answers a question that is not asked.

Every test reports its numbers and reason, plus PASS / FAIL / UNDETERMINABLE / NOT_RUN / NOT_APPLICABLE. All tests
run (transparency) except after an integrity or min-n stop.

## 5. Verdict taxonomy

Precedence: **INVALID_EVIDENCE > INSUFFICIENT_EVIDENCE (min n) > REJECTED > FRAGILE > INSUFFICIENT_EVIDENCE >
FORWARD_CONFIRMATION_REQUIRED > PROVISIONAL**. The verdict is set by the strongest effect among non-passing tests.

| Verdict | Meaning |
|---|---|
| INVALID_EVIDENCE | the evidence fails integrity; nothing about the strategy is concluded |
| INSUFFICIENT_EVIDENCE | below minimum n, or not even suggestive at the screens; absence of evidence |
| REJECTED | the executable-edge claim is contradicted |
| FRAGILE | positive alpha that fails a realism, benchmark, leak-canary or noise-calibrated fragility test |
| FORWARD_CONFIRMATION_REQUIRED | passed the screen; may enter **one** pre-registered forward test; **not evidence of an edge** |
| PROVISIONAL | also passes every local and global multiplicity control and every deterministic robustness rule; still requires the forward test |
| FORWARD_REJECTED / _INSUFFICIENT / _DECAYED / _CONSISTENT | forward outcomes; FORWARD_CONSISTENT = survived one forward test, the strongest label P2-F gives |

"PROVEN", "CONFIRMED", "VALIDATED" and "SUCCESS" do not exist (tested). Every verdict carries
`thresholds_status = PROPOSED_NOT_OWNER_APPROVED` and stays advisory until the owner approves the thresholds.

## 6. Pre-registered vs parameterized vs undeterminable now

| Pre-registered (frozen, hashed) | Parameterized (input, never tuned) | Undeterminable until a candidate exists |
|---|---|---|
| estimand, inference method, blocks, replicates, seeds; every test, threshold and effect; verdict precedence; min n; forward length formula, harm boundary and decay rule; calibration plan and its acceptance criteria; anti-retroactive version rule | trial horizon (4h / 24h); round context (siblings, ledger counts); forward set size (≤ 3); P2-X scenario nets (supplied by P2-D1 / P2-X) | the actual forward length (formula × in-sample sd); which tests are UNDETERMINABLE (regimes present, depth flags); neighbour availability; the dependence actually present; real cost levels; whether real alt noise matches the synthetic one; owner approval of thresholds |

## 7. Defences against the project's past failure classes

| Past failure (memory) | Defence | Synthetic check (C7) |
|---|---|---|
| look-ahead (daily condition measured during the trade; repaint) | I05 PIT; I10 on market-excess; R09 one-row-stale signal | lookahead_metadata, lookahead_hidden |
| clone-signal pseudo-replication (~64 % clones, n_eff ≈ ⅓) | I06 duplicates; I07 rebuild; **day clusters** (clones on one day add no weight); n_eff | clone_rows, clone_reentry_claimed; naive position t-test shown beside |
| peak-boundary holdout (reversion "edge" inverted OOS) | I04 frozen layout; forward window registered before it starts | peak_boundary_window |
| small-n combos (COMBO n = 7) | N01 refuses; no point estimate is reported | small_n_combo |
| regime / BTC beta as alpha (6 months = 99 % of the net) | A01 net alpha; A02 BTC alpha; E08 benchmarks; R07 / R11 regimes | btc_beta_as_alpha, trend_timing_as_alpha |
| fee-blind gates (thresholds on gross) | costs inside the estimand; E02 / E05; IDEALIZED never used | fee_blind_gross_edge |
| "loss-reducer, not an edge" (relative improvement) | absolute net alpha instead of vs-control | relative_to_control_trap |
| best single trade = 54 % of the net; top-3 removal flips | R11 / R12, R02 / R04 / R05 | outlier_day, single_symbol_pump |
| best cell crowned from many (48 cells) | S02 Romano-Wolf screen; M01 / M02; ledger counts abandoned trials | best_of_48_net_zero, best_of_48_bull |
| micro-cap-only edge (zero capacity) | E07 displayed-depth subset; capacity never claimed | (structural) |
| wins capped / losses unbounded (fill asymmetry) | nets come only from P2-X scenarios; E06 refusal imputation | not separately simulated (P2-X responsibility) |

### 7.3 Label-tail rule

Rows whose label ends after the last evaluation day are purged and counted. The forward window starts after the
latest label end that the in-sample evidence read (F-D0-3).

## 8. Forward-survival criteria (`f0_forward_v2.json`; unchanged from v1 except the recorded power reality)

Eligibility: an in-sample FCR or PROVISIONAL verdict. Each forward test takes **at most 3** frozen candidates,
registered before day 1 of the window. The test runs in five steps:

1. **Window.** It starts at the first eligible sealed day after day 29 (round 1) **and** after the latest label end
   read by the in-sample evidence.
2. **Length.** `n = ⌈((z₀.₉₅ + z₀.₈)·sd / (0.5·mean))² · deff⌉`, clamped to [28, 120] days.
   - The length uses a 50 % winner's-curse haircut on the in-sample mean.
   - If the unclamped n > 120, the test is *infeasible*: the verdict stays FCR with note `forward_infeasible`.
3. **Monitoring.** Weekly looks, **harm only**.
   - The test stops as FORWARD_REJECTED when the one-sided p of alpha < 0 falls below that look's
     O'Brien-Fleming-type spending increment.
   - There is **no early success**.
4. **Final judgement.** Once, at the planned end.
   - The full battery runs on the forward window, with Holm across the registered set.
   - The plateau and global search controls do not apply to a pre-registered set.
   - FORWARD_DECAYED applies when the forward mean < 0.25 × the in-sample mean.
5. **After.** Edge and drift monitoring is a later roadmap stage. PAPER-R1 linkage stays unauthorized.

## 9. Synthetic validation of the battery

All numbers below are synthetic. The plan (`f0_calibration_plan_v2.json`) and its acceptance criteria were frozen
and pushed **before** the run.

**The synthetic world.**

- 39 symbols (tiers 2 / 6 / 31) and a BTC-like t(4) factor with a 2-state volatility regime.
- Idiosyncratic t(4) noise: 0.4–4.5 % per day.
- Every replicate is a full 48-cell round with the frozen P2-D0 plan ids. 24h cells use a 6-hourly grid; 4h cells
  use a 4-hourly grid.
- Costs are about 26 bps round trip under BASE, plus 20 bps under STRESS.

**Repetitions.**

- Cells: 30–100 replicates each.
- Bootstrap / placebo repetitions: 199 / 49 / 49. The protocol values are 1999 / 199 / 199.
- Fragility references are at protocol size.

**Run.** Commit `cb7c1ba`, 6835 s wall and 2635 s CPU at 50 % CPU, peak 55 MB. The runner paused itself
2 × 13 min in the seal blackout windows. The Collector stayed HEALTHY throughout.

A "forward-eligible" result means the screen passed (verdict FCR or PROVISIONAL). The "naive" column is an iid
position-level t-test with no clustering and no artifact checks: the kind of analysis that produced the project's
past false edges. Intervals are Wilson 95 %.

### 9.1 C1: core p-value calibration (nominal 5 %, 1000 replicates per row)

**v1** (superseded): mean block 3, HAC lag 3. Its criterion **FAILED**.

| generator, n days | p_boot | p_HAC-t | combined p (used) |
|---|---|---|---|
| ar03_t4|n=10 | 19.7 % [17.4, 22.3] | 14.7 % [12.6, 17.0] | 14.4 % [12.4, 16.7] |
| ar03_t4|n=14 | 12.9 % [11.0, 15.1] | 9.7 % [8.0, 11.7] | 9.3 % [7.7, 11.3] |
| ar03_t4|n=28 | 10.9 % [9.1, 13.0] | 8.5 % [6.9, 10.4] | 8.4 % [6.8, 10.3] |
| ar03_t4|n=56 | 9.0 % [7.4, 10.9] | 8.2 % [6.7, 10.1] | 7.9 % [6.4, 9.7] |
| ar03_t4|n=90 | 7.5 % [6.0, 9.3] | 6.5 % [5.1, 8.2] | 6.2 % [4.9, 7.9] |
| ar05_t4|n=10 | 22.9 % [20.4, 25.6] | 17.9 % [15.6, 20.4] | 17.9 % [15.6, 20.4] |
| ar05_t4|n=14 | 18.8 % [16.5, 21.3] | 14.3 % [12.3, 16.6] | 14.0 % [12.0, 16.3] |
| ar05_t4|n=28 | 14.9 % [12.8, 17.2] | 11.7 % [9.9, 13.8] | 11.7 % [9.9, 13.8] |
| ar05_t4|n=56 | 13.5 % [11.5, 15.8] | 12.0 % [10.1, 14.2] | 11.9 % [10.0, 14.1] |
| ar05_t4|n=90 | 11.5 % [9.7, 13.6] | 10.8 % [9.0, 12.9] | 10.8 % [9.0, 12.9] |
| iid_normal|n=10 | 11.3 % [9.5, 13.4] | 8.8 % [7.2, 10.7] | 8.5 % [6.9, 10.4] |
| iid_normal|n=14 | 10.4 % [8.7, 12.4] | 9.1 % [7.5, 11.0] | 8.6 % [7.0, 10.5] |
| iid_normal|n=28 | 8.2 % [6.7, 10.1] | 6.9 % [5.5, 8.6] | 6.6 % [5.2, 8.3] |
| iid_normal|n=56 | 6.9 % [5.5, 8.6] | 5.6 % [4.3, 7.2] | 5.5 % [4.2, 7.1] |
| iid_normal|n=90 | 6.3 % [5.0, 8.0] | 6.1 % [4.8, 7.8] | 5.8 % [4.5, 7.4] |

**v2** (governing): block = max(3, ⌈n^(1/3)⌉). Its criterion **PASSED**.

| generator, n days | p_boot | p_batch | p_fixed-b | **v2 combined p (used)** | v1 combined p |
|---|---|---|---|---|---|
| ar03_t4|n=10 | 17.4 % [15.2, 19.9] | 6.9 % [5.5, 8.6] | 7.2 % [5.8, 9.0] | **4.6 % [3.5, 6.1]** | 13.7 % [11.7, 16.0] |
| ar03_t4|n=14 | 15.2 % [13.1, 17.6] | 7.0 % [5.6, 8.8] | 8.7 % [7.1, 10.6] | **5.4 % [4.2, 7.0]** | 12.1 % [10.2, 14.3] |
| ar03_t4|n=28 | 11.0 % [9.2, 13.1] | 5.6 % [4.3, 7.2] | 6.4 % [5.0, 8.1] | **4.8 % [3.6, 6.3]** | 8.3 % [6.7, 10.2] |
| ar03_t4|n=56 | 9.7 % [8.0, 11.7] | 7.2 % [5.8, 9.0] | 6.6 % [5.2, 8.3] | **6.1 % [4.8, 7.8]** | 8.1 % [6.6, 10.0] |
| ar03_t4|n=90 | 8.1 % [6.6, 10.0] | 6.4 % [5.0, 8.1] | 6.0 % [4.7, 7.6] | **5.4 % [4.2, 7.0]** | 7.4 % [5.9, 9.2] |
| ar05_t4|n=10 | 22.2 % [19.7, 24.9] | 8.4 % [6.8, 10.3] | 10.0 % [8.3, 12.0] | **6.2 % [4.9, 7.9]** | 16.0 % [13.9, 18.4] |
| ar05_t4|n=14 | 18.2 % [15.9, 20.7] | 7.8 % [6.3, 9.6] | 9.5 % [7.8, 11.5] | **5.8 % [4.5, 7.4]** | 13.5 % [11.5, 15.8] |
| ar05_t4|n=28 | 13.3 % [11.3, 15.5] | 7.7 % [6.2, 9.5] | 8.1 % [6.6, 10.0] | **6.8 % [5.4, 8.5]** | 10.5 % [8.7, 12.6] |
| ar05_t4|n=56 | 11.1 % [9.3, 13.2] | 8.6 % [7.0, 10.5] | 7.7 % [6.2, 9.5] | **7.3 % [5.8, 9.1]** | 9.7 % [8.0, 11.7] |
| ar05_t4|n=90 | 9.6 % [7.9, 11.6] | 7.7 % [6.2, 9.5] | 7.3 % [5.8, 9.1] | **6.7 % [5.3, 8.4]** | 8.7 % [7.1, 10.6] |
| iid_normal|n=10 | 12.2 % [10.3, 14.4] | 5.4 % [4.2, 7.0] | 5.5 % [4.2, 7.1] | **2.8 % [1.9, 4.0]** | 9.7 % [8.0, 11.7] |
| iid_normal|n=14 | 11.0 % [9.2, 13.1] | 5.5 % [4.2, 7.1] | 5.2 % [4.0, 6.8] | **2.5 % [1.7, 3.7]** | 7.8 % [6.3, 9.6] |
| iid_normal|n=28 | 8.7 % [7.1, 10.6] | 5.3 % [4.1, 6.9] | 4.4 % [3.3, 5.9] | **3.6 % [2.6, 4.9]** | 6.2 % [4.9, 7.9] |
| iid_normal|n=56 | 6.5 % [5.1, 8.2] | 4.4 % [3.3, 5.9] | 4.4 % [3.3, 5.9] | **3.7 % [2.7, 5.1]** | 5.6 % [4.3, 7.2] |
| iid_normal|n=90 | 7.3 % [5.8, 9.1] | 4.8 % [3.6, 6.3] | 4.8 % [3.6, 6.3] | **3.9 % [2.9, 5.3]** | 4.9 % [3.7, 6.4] |
| ma1_05_t4|n=10 | 16.9 % [14.7, 19.3] | 5.2 % [4.0, 6.8] | 7.6 % [6.1, 9.4] | **3.6 % [2.6, 4.9]** | 12.9 % [11.0, 15.1] |
| ma1_05_t4|n=14 | 14.9 % [12.8, 17.2] | 6.3 % [5.0, 8.0] | 8.3 % [6.7, 10.2] | **4.9 % [3.7, 6.4]** | 11.4 % [9.6, 13.5] |
| ma1_05_t4|n=28 | 11.0 % [9.2, 13.1] | 5.6 % [4.3, 7.2] | 6.0 % [4.7, 7.6] | **4.8 % [3.6, 6.3]** | 7.8 % [6.3, 9.6] |
| ma1_05_t4|n=56 | 9.6 % [7.9, 11.6] | 6.2 % [4.9, 7.9] | 6.7 % [5.3, 8.4] | **5.9 % [4.6, 7.5]** | 7.2 % [5.8, 9.0] |
| ma1_05_t4|n=90 | 8.5 % [6.9, 10.4] | 6.9 % [5.5, 8.6] | 6.5 % [5.1, 8.2] | **5.8 % [4.5, 7.4]** | 7.3 % [5.8, 9.1] |

At round-1 size (n ≈ 13–14), every single component is anti-conservative under dependence:

- the bootstrap: 11–18 %;
- batch means and fixed-b HAC: 5–10 %.

Only the three-way maximum is near nominal: 2.5–5.8 %. It still runs at 6–7 % under the long-memory AR(0.5)
stress, which is a residual limitation.

### 9.2 In-sample nulls (14 frozen validation days)

**C2: net-zero null.** The planted gross edge exactly pays the costs.

| cell | reps | forward-eligible (screen pass) | PROVISIONAL | INVALID | REJECTED | FRAGILE | INSUFFICIENT | naive iid t-test rejects | oracle net edge |
|---|---|---|---|---|---|---|---|---|---|
| net_zero_H01 | 100 | 2.0 % [0.6, 7.0] | 0.0 % [0.0, 3.7] | 2 | 53 | 35 | 8 | 25.0 % [17.5, 34.3] | +0.5 bps |

**C3: bull-market beta null.** Drift +0.8 %/day, no edge.

| cell | reps | forward-eligible (screen pass) | PROVISIONAL | INVALID | REJECTED | FRAGILE | INSUFFICIENT | naive iid t-test rejects | oracle net edge |
|---|---|---|---|---|---|---|---|---|---|
| bull_mu80bps | 100 | 1.0 % [0.2, 5.4] | 0.0 % [0.0, 3.7] | 1 | 66 | 26 | 6 | 40.0 % [30.9, 49.8] |  |

**C4: pure null.**

| cell | reps | forward-eligible (screen pass) | PROVISIONAL | INVALID | REJECTED | FRAGILE | INSUFFICIENT | naive iid t-test rejects | oracle net edge |
|---|---|---|---|---|---|---|---|---|---|
| pure_null | 50 | 0.0 % [0.0, 7.1] | 0.0 % [0.0, 7.1] | 1 | 36 | 12 | 1 | 26.0 % [15.9, 39.6] | -25.6 bps |

C4 is formally a FAIL under its own criterion, but only because the criterion could not be met. It requires a
Wilson upper bound ≤ 5 % for PROVISIONAL, and the upper bound of 0/50 is 7.1 %. The observed result is 0/50 at
every level. This is a criterion-design error, reported and not tuned.

### 9.3 C5: in-sample power (14 days)

| cell | reps | forward-eligible (screen pass) | PROVISIONAL | INVALID | REJECTED | FRAGILE | INSUFFICIENT | naive iid t-test rejects | oracle net edge |
|---|---|---|---|---|---|---|---|---|---|
| net+100bps | 60 | 10.0 % [4.7, 20.1] | 0.0 % [0.0, 6.0] | 13 | 5 | 28 | 8 | 46.7 % [34.6, 59.1] | +100.6 bps |
| net+10bps | 60 | 3.3 % [0.9, 11.4] | 0.0 % [0.0, 6.0] | 0 | 27 | 29 | 2 | 21.7 % [13.1, 33.6] | +10.5 bps |
| net+200bps | 60 | 15.0 % [8.1, 26.1] | 0.0 % [0.0, 6.0] | 45 | 1 | 3 | 2 | 76.7 % [64.6, 85.6] | +195.0 bps |
| net+25bps | 60 | 5.0 % [1.7, 13.7] | 0.0 % [0.0, 6.0] | 3 | 26 | 25 | 3 | 28.3 % [18.5, 40.8] | +25.6 bps |
| net+50bps | 60 | 8.3 % [3.6, 18.1] | 0.0 % [0.0, 6.0] | 7 | 10 | 25 | 13 | 40.0 % [28.6, 52.6] | +50.2 bps |

### 9.4 C6: forward test (one pre-registered candidate, Bonferroni m = 1)

| cell | reps | forward-eligible (screen pass) | PROVISIONAL | INVALID | REJECTED | FRAGILE | INSUFFICIENT | naive iid t-test rejects | oracle net edge |
|---|---|---|---|---|---|---|---|---|---|
| fwd28d_bull_null | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 0 | 24 | 4 | 2 | 33.3 % [19.2, 51.2] |  |
| fwd28d_net+100bps | 30 | 16.7 % [7.3, 33.6] | 6.7 % [1.8, 21.3] | 11 | 0 | 7 | 7 | 76.7 % [59.1, 88.2] | +99.0 bps |
| fwd28d_net+25bps | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 1 | 9 | 16 | 4 | 23.3 % [11.8, 40.9] | +25.7 bps |
| fwd28d_net+50bps | 30 | 13.3 % [5.3, 29.7] | 6.7 % [1.8, 21.3] | 3 | 6 | 11 | 6 | 40.0 % [24.6, 57.7] | +50.4 bps |
| fwd28d_net_zero | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 0 | 18 | 11 | 1 | 30.0 % [16.7, 47.9] | +0.3 bps |
| fwd56d_net+100bps | 30 | 26.7 % [14.2, 44.4] | 26.7 % [14.2, 44.4] | 18 | 0 | 4 | 0 | 73.3 % [55.6, 85.8] | +101.1 bps |
| fwd56d_net+25bps | 30 | 13.3 % [5.3, 29.7] | 13.3 % [5.3, 29.7] | 0 | 8 | 16 | 2 | 33.3 % [19.2, 51.2] | +25.3 bps |
| fwd56d_net+50bps | 30 | 16.7 % [7.3, 33.6] | 10.0 % [3.5, 25.6] | 5 | 3 | 14 | 3 | 40.0 % [24.6, 57.7] | +50.2 bps |
| fwd56d_net_zero | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 0 | 14 | 15 | 1 | 16.7 % [7.3, 33.6] | +0.5 bps |

### 9.5 C7: adversarial generators (the project's past false-edge classes)

| cell | reps | forward-eligible (screen pass) | PROVISIONAL | INVALID | REJECTED | FRAGILE | INSUFFICIENT | naive iid t-test rejects | oracle net edge | caught by listed test |
|---|---|---|---|---|---|---|---|---|---|---|
| best_of_48_bull | 30 | 20.0 % [9.5, 37.3] | 0.0 % [0.0, 11.4] | 2 | 0 | 19 | 3 | 63.3 % [45.5, 78.1] |  | n/a |
| best_of_48_net_zero | 30 | 10.0 % [3.5, 25.6] | 0.0 % [0.0, 11.4] | 1 | 0 | 20 | 6 | 23.3 % [11.8, 40.9] |  | n/a |
| btc_beta_as_alpha | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 0 | 20 | 9 | 1 | 50.0 % [33.2, 66.8] |  | 63.3 % [45.5, 78.1] |
| clone_reentry_claimed | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 30 | 0 | 0 | 0 | 50.0 % [33.2, 66.8] |  | 100.0 % [88.6, 100.0] |
| clone_rows | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 30 | 0 | 0 | 0 | 20.0 % [9.5, 37.3] |  | 100.0 % [88.6, 100.0] |
| fee_blind_gross_edge | 30 | 3.3 % [0.6, 16.7] | 0.0 % [0.0, 11.4] | 0 | 17 | 10 | 2 | 16.7 % [7.3, 33.6] | -10.0 bps | 56.7 % [39.2, 72.6] |
| lookahead_hidden | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 29 | 0 | 1 | 0 | 100.0 % [88.6, 100.0] |  | 100.0 % [88.6, 100.0] |
| lookahead_metadata | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 30 | 0 | 0 | 0 | 100.0 % [88.6, 100.0] |  | 100.0 % [88.6, 100.0] |
| outlier_day | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 1 | 8 | 20 | 1 | 53.3 % [36.1, 69.8] |  | 90.0 % [74.4, 96.5] |
| peak_boundary_window | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 30 | 0 | 0 | 0 | 33.3 % [19.2, 51.2] |  | 100.0 % [88.6, 100.0] |
| relative_to_control_trap | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 0 | 29 | 1 | 0 | 20.0 % [9.5, 37.3] |  | 96.7 % [83.3, 99.4] |
| single_symbol_pump | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 1 | 16 | 13 | 0 | 30.0 % [16.7, 47.9] |  | 96.7 % [83.3, 99.4] |
| small_n_combo | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 0 | 0 | 0 | 30 | 3.3 % [0.6, 16.7] |  | 100.0 % [88.6, 100.0] |
| trend_timing_as_alpha | 30 | 0.0 % [0.0, 11.4] | 0.0 % [0.0, 11.4] | 0 | 20 | 8 | 2 | 63.3 % [45.5, 78.1] |  | 70.0 % [52.1, 83.3] |

Acceptance (frozen criteria): C1 PASS, C2 PASS, C3 PASS, C4 FAIL, C6_null PASS, C7 FAIL

### 9.6 Reading the numbers honestly

- **Integrity-class artifacts are caught 100 %:**
  - look-ahead (declared and hidden);
  - clone rows;
  - clone re-entry;
  - peak-boundary window;
  - small-n combinations.

  These are structural defences and independent of n.
- **Economic artifacts are stopped from becoming forward-eligible:**
  - BTC beta, trend timing, the relative-to-control trap and the single-symbol pump: 0/30 each;
  - fee-blind gross edge: 1/30.
  - C7 still **FAILS** its frozen criterion, for two reasons.
    - That one fee-blind replicate passed the screen. Its Wilson upper bound is 16.7 % against a 15 % limit.
    - For beta, fee-blind and trend timing the listed REJECT test (A01) was the deciding test in only 57–70 % of
      replicates (criterion 80 %). With 13 noisy days the alpha point estimate is sometimes positive; those
      replicates were stopped by FRAGILE-class tests instead (E03 STRESS, E05 cost share, E08 benchmark, A02).
  - Reported, not tuned.
- **Selection is the real in-sample hazard.** When the best of 48 null cells is picked, the round still produces a
  screen-passing candidate in 10 % (net-zero) to 20 % (bull) of rounds. **PROVISIONAL stays at 0.** A naive
  analysis "finds" an edge in 23–63 % of these rounds. The screen is therefore not a significance claim. The
  protection is the forward test, whose false-pass rate was 0/90 under the forward nulls.
- **Power is the binding constraint.**
  - In-sample (14 days), true net edges of +10 / +25 / +50 / +100 bps per 24h position pass the screen in
    3 / 5 / 8 / 10 % of replicates. That is barely above the nulls (1–2 %).
  - Edges large enough to be detected are increasingly flagged as implausible: 22 % of the +100 bps replicates and
    75 % of the +200 bps replicates end in INVALID_EVIDENCE.
  - Forward, at 28 days, the pass rates are 0 / 13 / 17 %; at 56 days they are 13 / 17 / 27 % (for +25 / +50 /
    +100 bps).

  This is the sample-size reality of ~1 independent observation per day, not a defect of a particular test (section
  1, `f0_forward_v2.json` `power_reality`).


## 10. Relation to P2-D0, P2-X and RM0

- **P2-D0:** P2-F0 consumes its folds, layout, grids (neighbours read from `planned_trials_v1.json`), benchmarks,
  horizons, Holm-within-hypothesis and the ledger. It only **adds** stricter conditions and never edits a P2-D0
  file. The frozen P2-D0 hash is pinned in tests and every registration. P2-D0 weaknesses are recorded as findings
  F-D0-1 … F-D0-11 (frozen in `f0_protocol_v2.json`, first in v1; summarized in section 13) with *proposed* v2 amendments that
  need owner approval.
- **P2-X:** nets are the P2-X scenarios (EXEC-IDEALIZED / BASE / STRESS v2 `f20e22a5…`).
  - Fee, latency and stress are ASSUMED; impact is UNAVAILABLE.
  - BASE is primary, STRESS must stay positive, and IDEALIZED never supports a verdict.
  - Capacity is only "edge on displayed-depth-supported positions", never a capacity estimate.
- **RM0 (pending D-RM0-2):** not imported, not resumed.
  - The abstract interface is a future `risk_inputs` block bound to a closed RM0 contract hash by a later F version.
    It is **refused** until then.
  - P2-F0 itself fails closed on mixed quote currencies (I08), which is exactly the D-RM0-2 class.

## 11. Pre-registration mechanics

The governing frozen set is `contracts_v2/`: `f0_protocol_v2.json`, `f0_evidence_schema_v2.json`,
`f0_forward_v2.json`, `f0_calibration_plan_v2.json` and `FROZEN_SHA256SUMS.json` (record_version 2, `supersedes`
the v1 sums hash). Its `contract_set_sha256` = SHA-256 of the sums file. v1 (`contracts/`) is kept byte-identical.

**Hashes.**

| v2 file (governing) | SHA-256 |
|---|---|
| f0_protocol_v2.json | `cbbe2922f594debbbcb806149df0fbc6f08db9eeb2afb7e315fd8c9d4e597302` |
| f0_evidence_schema_v2.json | `79f5dcde425138ffcd9e68919bed5345cbe378973bf4e37022157e0b13563a80` |
| f0_forward_v2.json | `c637aa1c0e31ba723eefb500db9bd001435140fda4bd29ea8da0c4ecce59d8ec` |
| f0_calibration_plan_v2.json | `01c41fbaa0592d5c6e3c7de8f6bdcc945724f1da665b334749158304b3dfd644` |
| **contracts_v2/FROZEN_SHA256SUMS.json (contract_set_sha256)** | **`617cd797320600421f83b50a85dbaeb7746660b5bb26c6ff5411d5d3c6e78f42`** |

| v1 file (superseded, kept byte-identical) | SHA-256 |
|---|---|
| f0_protocol_v1.json | `4608e74ed3cbc557fc4ef690cb76c5e538d119f18c7bd8ce6b8ee96da7ed2d9f` |
| f0_evidence_schema_v1.json | `9d059a2a83efda1b180791d2d54ee28eaff9b56dd23016cc1ef209f3fb0c2e6b` |
| f0_forward_v1.json | `021089e73d9176bab1a02ec56eef12709242182ac6c6ce3663d6e9d7a3111f7b` |
| f0_calibration_plan_v1.json | `2b7af4e10ec3f8c1534c12b5cb16855aad4a1279a007df40f26a5168d5d8ae77` |
| contracts/FROZEN_SHA256SUMS.json | `9f42105d2d408babdf8f7a96036dd1bdd46ee1ac858b23a7642a3ba1950398b6` |

**Commits and push order.**

- v1 was frozen in `ad541d9`. That commit was pushed before its calibration run.
- v2 was frozen in `cb7c1ba`. That commit was pushed before the v2 calibration run.

**Dependency hashes.** These were recomputed and are unchanged:

- P2-D0 `2bedc3f5…8573` (and the four registries);
- P2-X v1 `3c554702…ec2f`;
- P2-X v2 `f20e22a5…88d0`.

`git diff a65bbfb..HEAD` touches no P2-D0, P2-X, ledger, instrument or RM0 file.

**Ledger state.** The ledger head anchored at freeze time is seq −1: genesis, with no ledger file.

**Binding.** `contracts.registration` binds the following into a record with its own hash:

- the trial id and plan entry hash;
- the F0, P2-D0 and P2-X v2 hashes;
- the code commit;
- `considered_trials`: every trial of the round, so the selection is countable;
- (v2) the P2-C dataset `{dataset_id, dataset_hash}`, equal to the trial's ledger spec and to `evidence.dataset`;
- a predeclared selection rule;
- a ledger anchor (`seq`, `event_hash`);
- the forward registration.

`check_registration_against_ledger` (read-only) checks three things: the ledger verifies against the anchor, no
trial of the hypothesis is missing from `considered_trials` (no hidden siblings), and (v2) the registered dataset
equals the ledger spec's dataset.

**Immutability and versioning.** A change is a new file version with a new sums file. `freeze()` refuses
re-freezing. `applicable_version` applies the latest version frozen **strictly before the first `trial_result` of
the round**. A later version may only add a second verdict, and `governing_verdict` takes the more conservative one,
so retroactive changes can only downgrade. F0 v1 and v2 are both frozen at ledger head seq −1, the genesis state (v2 governs): the ledger
does not exist yet.

## 12. Limitations

- **Power.** In-sample, plausible edges are undetectable (section 1, C5). Forward tests of plausible edges
  (alpha Sharpe 2–4) are infeasible within 120 days (section 9). This is the data, not the battery.
- **Synthetic realism.** The synthetic market (factor + t(4) idio, 2-state volatility, 39 symbols, 6-hour grid for
  24h cells, 4-hour grid for 4h cells) is a stand-in. Real alt noise, cross-correlation and costs may differ. FPR
  and power transfer only approximately.
- **Calibration size.** Calibration uses fewer bootstrap and placebo repetitions than the protocol, and
  30–100 reps per cell. The Monte Carlo error is shown as Wilson intervals.
- **Fixed parameters and approval.** The fixed thresholds (0.20 / 0.50 screens, 0.5 cost share, 25 % lag
  retention, Sharpe-4 plausibility, 0.10 joint fragility) are judgement calls. They are frozen so that outcomes
  cannot shape them, but they are **not owner-approved**.
- **Timing credit.** Alpha against a day-average factor credits intraday timing. A time-matched factor would be
  less noisy but would erase timing skill. Choosing the day average makes beta-estimation noise a channel for false
  screen passes in strong trends (C3).
- **What the battery cannot see.** It cannot see fill asymmetry, impact or realized slippage (P2-X boundary). It
  cannot see a leak that survives a one-row lag and stays below the Sharpe-4 bound.
- **Abandoned trials.** They count in N (DSR, Bonferroni) but have no series for Romano-Wolf.
- **Regimes.** H04-style regime-gated trials are, by construction, single-regime and cannot pass R07 (at most FCR).

## 13. Self-critique

**The most important correction: the primary p-value.** It came out of my own pre-registered calibration. v1's
primary p-value was anti-conservative at the sample sizes that matter (C1 FAIL, 9–14 % false positives at nominal
5 %). The mechanism designed for exactly this case worked:

- v1 was not quietly tuned;
- a v2 was frozen, pushed and re-calibrated;
- the v1 record stays.

All of this happened before any Alpha outcome. v1's other studies (C2–C7) were halted after C1 to save shared-host
CPU. They are not needed because v2 re-runs every study.

Changes made during design on SYNTHETIC pilots only, all before the v1 freeze. They are listed because they are
forking paths: the battery was shaped while I watched my own generators, so its catch rates on those generators are
optimistic.

1. **Estimand changed.** Raw net (then vs-control) became net alpha. Raw 14-day means were market noise, and
   vs-control lets loss-reducers through.
2. **Robustness split.** Fixed D0-style rules flagged 60–100 % of honest planted edges as FRAGILE. They were moved
   to PROVISIONAL-only, and noise-calibrated joint tests R11 / R12 were added.
3. **Robust R11 scale.** An outlier day had widened its own reference.
4. **S02 selection screen added.** Best-of-48 passed a raw-p screen too often.
5. **Implausibility moved to market-adjusted series.** On raw series a bull market tripped it.
6. **Plateau on the gross information effect.** This addresses F-D0-5.
7. **Synthetic gross made arithmetic.** The convexity created a fake +0.3 %/day null drift.

Weaknesses I see in my own design:

- **W1 (most important) — forward sizing, recorded as an open owner decision in `f0_forward_v2.json`.** The forward length is sized from the in-sample estimate with a 0.5
  haircut. Any candidate passing a 13-day screen has a noise-inflated estimate, so the forward test is sized for an
  edge far larger than plausible and is underpowered against the edge that might be real. Sizing against the
  plausibility bound (alpha Sharpe 4) needs about 141 days at 80 % power without a haircut; that exceeds the
  120-day cap. Annualized alpha Sharpe 2 needs about 560 days. **Proposed F v3 (owner decision first):** n ≥ the
  plausibility-based length. That would make every plausible candidate "forward_infeasible" within 120 days, so the forward
  duration / collector horizon becomes an **owner decision**, not a statistical one. The v1 / v2 rule is kept because
  it was frozen before any outcome. Its verdicts after a short forward test are honest about the result (not significant →
  FORWARD_INSUFFICIENT), but they are not powerful.
- **W2 — partly fixed in v2.** Evidence rows are trusted as produced by P2-C / P2-X: P2-F0 rebuilds positions but
  not labels. v2 binds the P2-C dataset id and hash, cross-checked against the ledger spec. The P2-X join hash is
  **still not bound**; that is proposed for a later version.
- **W3 — FCR can be misread.** FORWARD_CONFIRMATION_REQUIRED will be read by some as "promising". In-sample it
  carries almost no information at plausible effect sizes (C5). The name was chosen to say what it is: a ticket to
  one test, nothing more.
- **W4 — Romano-Wolf at small n.** Romano-Wolf and the deflated Sharpe are studentized with HAC SEs at n ≈ 13.
  Their own calibration was measured only indirectly (C7 best-of-48 cells), not with a dedicated null study. This
  matters more after C1 showed how easily small-n HAC and bootstrap p-values run hot: the Romano-Wolf step still
  uses a stationary bootstrap of HAC-studentized means.
- **W5 — dead weight in round 1.** P03 (time shift) is always UNDETERMINABLE at 14 days.
- **W6 — horizon coverage.** Calibration covers 24h candidates only. 4h cells enter as siblings and neighbours but
  were not calibrated as candidates.
- **W7 — not independently attacked.** An independent red team (generators written without sight of the battery)
  would give an unbiased catch rate. That is recommended before the first real use.
- **W8 — two of my own frozen acceptance criteria failed.**
  - **C4** was unattainable as written (0/50 cannot give a Wilson upper bound ≤ 5 %).
  - **C7** failed in two ways:
    - one fee-blind replicate passed the screen (1/30);
    - the listed REJECT test decided only 57–70 % of the beta, fee-blind and timing cases, which were otherwise
      stopped as FRAGILE.

  Neither failure was tuned away. A v3 should state Monte-Carlo-feasible criteria and could make A01 robust to
  alpha noise, for example by rejecting on an upper confidence bound rather than on the point estimate. That would
  trade attribution clarity for power, so it is an owner-visible choice.

## 11. Status review (2026-10-08, read-only)
- **Branch:** `feature/p2f0-adversarial-validation-20261006` @ `b20d56f`, remote verified; `test_falsification_f0`
  passes. Not merged; nothing deployed.
- **Dependency change:** RM0 D-RM0-2 is repaired on `feature/p2rm0-portfolio-risk-20261006` @ `5f22431` (RM0-UNITS
  1.1.0, not merged). F0 keeps refusing `risk_inputs` (I01) and keeps its own one-quote-currency check (I08) until
  RM0 is owner-accepted and merged. Only then should a versioned F0 amendment admit RM0 inputs.
- **Open items and why none can be done offline now:**

  | Item | Blocked by |
  |---|---|
  | C4 null-calibration (50 reps cannot reach the bound) | compute: needs about 10× reps via the G2 runner (R1) in an authorised window; same gate as G5 |
  | C7 REJECT-routing (57–70 % vs the 80 % target) | an owner decision on criteria attainable by Monte-Carlo n; contract v3 |
  | Independent red-team generators | must be written without sight of the battery, which needs a separate author or session; owner to schedule |
  | Romano-Wolf / DSR dedicated null study | compute (same gate as C4) |
  | P2-X join-hash binding; forward-test length; threshold approval (`PROPOSED_NOT_OWNER_APPROVED`) | owner decisions, then F-contract v3 |
  | F-D0-1/3/5 → P2-D0 v2 amendment proposal | owner decision; P2-D0 frozen files stay untouched |

- **Unchanged:** the 28-day eligibility gate. There is no Alpha claim.
