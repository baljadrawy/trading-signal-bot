"""Implementation choices that the frozen protocol does not determine (owner review items OD-1..OD-7).

Every value here is bound into the code-tree hash and copied into the output meta. Changing one is an implementation
change (new tree hash), never a protocol change; the frozen protocol / contract files are not touched.
"""
from __future__ import annotations

GENERATOR_VERSION = "mi-p1s-gen-1.0.0"

# --------------------------------------------------------------------------- generators (probit latent framework)
# y = 1[mu + s_b + s_x + z > 0]; s_b known to the baseline, s_x incremental, z the (overlapping / clustered) outcome
# shock with N(0,1) margins, so P(y=1 | index) = Phi(index) and every forecast below is exactly calibrated given its
# information set (no approximation).
GEN = {
    "tau_b": 0.6,                 # sd of the baseline-known signal (probit index units)
    "tau_x": 0.6,                 # sd of the incremental signal; max attainable BSS must exceed the top skill level
    "null_noise_sd": 0.1,         # OD-3: null candidate = baseline index + persistent noise of this sd
    "leak_weight": 2.0,           # OD-4: leak candidate = logit(skill_bss_min) + w * (2y - 1)
    "t1_overlap": 6,              # 24h label on the 4h grid (protocol: 6x overlap)
    "t1_series": 2,
    "t1_steps_per_day": 6,
    "days": 517,
    "t1_break_mode": "dev_calibrated",   # OD-2: forecasts carry the pre-break (dev) rate pi/2; HLE outcomes at pi
    "t3_baseline_bss_target": 0.10,      # T3 baseline lag l: smallest l with full-information BSS >= this
    "t3_lag_max": 365,
    "t3_null_noise_sd": 0.1,
    "l2_noise_features_c1": 6,    # c1 = L2 logistic on baseline index + 6 noise features (7 features, as T1 M1)
    "l2_noise_features_c2": 2,    # c2 = L2 logistic on baseline index + 2 noise features
    "l2_t3_noise_features_c1": 6,
    "l2_t3_noise_features_c2": 2,
}

DEFAULT_GEN = dict(GEN)

# --------------------------------------------------------------------------- rules / statistics
METHODS = {
    "B1_bootstrap": "stationary bootstrap (Politis-Romano 1994), day resampling units, circular, mean block "
                    "block_mean_days x block_factor, B = protocol bootstrap_resamples_synthetic (999), centred "
                    "one-sided p = (1 + #{theta* - theta >= theta}) / (B + 1)",
    "B1_dm": "OD-1b: Diebold-Mariano t on the day-level loss differential, EWC (equal-weighted cosine) long-run "
             "variance with nu = max(2, floor(3 n_days / (4 L))) basis terms, fixed-b Student-t(nu) reference "
             "(Lazarus-Lewis-Stock-Watson 2018; Coroneo-Iacone 2020); exact at every Holm / Bonferroni level",
    "B1_combine": "p = max(p_bootstrap, p_dm) per candidate (contract B1)",
    "B1_multiplicity": "OD-1a: Holm within task over m = 2 candidates at alpha_task; primary alpha_task = "
                       "alpha_step / 3 (contract B1 Bonferroni x3 across tasks); diagnostic variant alpha_task = "
                       "alpha_step recorded alongside",
    "B2": "mean log-loss differential (baseline - candidate) > 0",
    "B3": "OD-5: Cox calibration, logit link; clusters = contiguous blocks of the step's mean block length in days "
          "(CR1 sandwich, G/(G-1)), critical value t(G-1, 0.975); slope 95 % CI contains 1; offset-model intercept "
          "95 % CI contains 0; calibration-in-the-large O/E 95 % CI (log scale) contains 1; a structurally "
          "degenerate point CI contains its target iff within 1e-9; T3 pooled one-vs-rest",
    "B4_B6": "not applicable at L1 (no dev folds, no W2 segment are simulated) and omitted: null FPR is an upper "
             "bound with respect to these gates, power an upper bound (OD-6)",
    "b3_size": "B3 applied to the exactly calibrated baseline-information forecast in each null rep",
    "skill_pass": "candidate 1 (calibrated, expected BSS = level) passes B1 (Holm with candidate 2 = null-type) "
                  "and B2 and B3",
    "miscal": "skill candidate at bss_min, logit(c) / s (slope_s) or logit(c) - a (int_a); reject = B3 rejects",
    "leak_fire": "OD-4: A7 trip-wire canary, fires when the realised BSS of the leaky candidate exceeds the "
                 "task trip-wire ceiling (max max_bss over levels and non-stress cells of the same run)",
    "l2": "two logistic surrogates fitted on an independent dev draw of the cell, evaluated on the HLE draw; "
          "full B1(Holm)/B2/B3 rule at the task's final ladder step; T3 conditional logit",
    "wilson": "derive.wilson_upper of the frozen MI-C v1.0 set (frozen)",
}
