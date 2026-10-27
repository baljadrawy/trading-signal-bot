"""X1 single-look power simulation (`x1-pwr-sim-v1`). SYNTHETIC ONLY; decision support for owner decision RD-2.

What it answers
---------------
For the two candidate X1 look windows (NEXT_LICENSED_DATA_STEP.md §7-§8):

* (a) 2023-01-01 -> 2026-08-18 (1,326 UTC days) and
* (b) 2019-01-01 -> 2026-08-18 (2,787 UTC days),

how often would the roadmap PM-1 pass rule be met when the true annualized Sharpe ratio of the primary series is
0 (false-positive rate), 0.5, 1.0 or 1.5, with heavy-tailed (Student-t), serially dependent daily returns, after
the s4-mech-v1 costs?

Model (every number is a parameter; the [ASM] defaults are assumptions, not estimates from any data)
--------------------------------------------------------------------------------------------------------
* Primary series (PM-1 notion (c)): daily active net return a_t = R_t - B_t of the strategy versus the
  equal-weight buy-and-hold benchmark. a_t = mu_a + sigma_a * y_t, where y_t has unit variance and is
  Student-t (standardized), optionally AR(1) and/or GARCH(1,1). "True Sharpe" is mean / marginal sd of a_t,
  annualized with sqrt(365.25), on the NET basis by default (``sharpe_basis="gross"`` subtracts the cost drag).
* Benchmark B_t (needed for the absolute-return, drawdown and concentration conditions): drift
  ``bench_drift_ann`` (default 0: a market drift chosen from known history would be outcome-informed), vol
  ``bench_vol_ann``, correlation ``rho_active_bench`` with a_t. R_t = B_t + a_t.
* Costs (research/mechanisms/costs.py, reused): fee 0.10 % per side, half-spread 0.01 % (BTC/ETH) and 0.04 %
  (other top-20), slippage 0.05 % per side; blended by ``major_weight`` (2 of 20 names). Stress multiplies the
  spread and slippage by ``stress_mult`` (2.0), never the fee. Daily cost = turnover x per-side cost. Turnover of the
  strategy and of the monthly-rebalanced benchmark is NOT documented for HR-04 in the repository, so it is a
  parameter ([ASM] defaults 0.10 and 0.005 per day).
* DSR trials: ``n_trials`` registered variants (default 3, the contract's candidate cap). ``trial_var_mode``
  "variants" simulates the other variants with correlation ``rho_variants`` to the primary and the same true SR and
  uses the cross-sectional variance of their sample Sharpe ratios (what a ledger would record);
  "null" uses the null sampling variance 1 / n (independent noise trials, conservative).

PM-1 as documented (docs/strategy/PROFITABILITY_ROADMAP_2026-10-24.md §9.1, PR #91, Draft)
--------------------------------------------------------------------------------------------
"active net return vs EW B&H > 0 with HAC t >= 2 (lag 7) and bootstrap 95 % CI excluding 0; DSR >= 0.95 with
N = all logged variants; (a) mean net > 0 under x2 cost stress; none of the five S4 failure criteria triggered".

Core statistical conditions (always simulated):
  C1 HAC t (Bartlett, lag 7, research/stats/inference convention) of mean a_t >= ``hac_t_min`` (2.0);
  C2 stationary-bootstrap (mean block 20 days) percentile 95 % CI of mean a_t has lower bound > 0;
  C3 DSR of a_t (research/stats/sharpe_deflation convention) >= 0.95.
Further conditions (the "full" rule, as far as a single-series simulation can represent them):
  C4 mean absolute net return R_t under x2 cost stress > 0 (PM-1 "(a)");
  F2 fail if active cost drag > 50 % of the sample gross active mean (or gross <= 0);
  F3 fail if MDD(R) > MDD(B) and Sharpe(R) <= Sharpe(B);
  F4 fail if > 50 % of total net P&L of R comes from the best 5 30.44-day blocks ("months"), or total <= 0;
  F5 fail if mean a_t under x2 cost stress <= 0 (sign reversal).
  F1 (HAC t <= 0) is implied by C1. The "1 coin" part of F4 is NOT simulated (single-series model): the full-rule
  power is an upper bound in that respect.

Ambiguities, parameterized rather than resolved
-----------------------------------------------
* PM-1 says HAC t >= 2; NEXT_LICENSED_DATA_STEP.md §8 and the S4 power table use the exploratory family split
  0.05 / 3 (one-sided z about 2.13). ``hac_t_min`` takes either.
* PM-1 does not say on which series the DSR is computed (active vs absolute net); default active (the primary).
* PM-1 says "N = all logged variants"; A19 (held branch 8cb5c9e) recommended an imputed N = 10^4 for exposed
  history. ``n_trials`` takes either.
* Bootstrap resamples: the preregistration fixes the number; the simulation default is 499 per look.

Limits: normal-theory and simulation both ignore model risk, regime change inside the window (see
``regime_split`` for a stylized decay / emergence case) and the adaptive pre-existing search (A19 §1). Synthetic
results prove nothing about any market; insufficient power is not evidence of no effect.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, field, replace
from statistics import NormalDist

import numpy as np

from research.mechanisms.costs import CostModel

VERSION = "x1-pwr-sim-v1"
EVIDENCE_CLASS = "SYNTHETIC"
DAYS_PER_YEAR = 365.25
WINDOWS = {
    "a_2023_2026": ("2023-01-01", "2026-08-18", 1326),
    "b_2019_2026": ("2019-01-01", "2026-08-18", 2787),
}
SPLIT_2019_2022_DAYS = 1461          # 2019-01-01 .. 2022-12-31 inside window (b)
_N = NormalDist()
_EULER_GAMMA = 0.5772156649015329


@dataclass(frozen=True)
class Tails:
    """Shape of the standardized daily innovations of the active series."""
    name: str
    df: float | None = None          # Student-t degrees of freedom (> 2); None = normal
    ar1: float = 0.0                 # AR(1) coefficient of the active series
    garch: tuple | None = None       # (alpha, beta) of a unit-variance GARCH(1,1), or None


@dataclass(frozen=True)
class Design:
    hac_t_min: float = 2.0           # PM-1 literal; 2.128 = one-sided z at 0.05 / 3
    hac_lag: int = 7
    boot_level: float = 0.95
    mean_block: float = 20.0
    n_boot: int = 499
    dsr_min: float = 0.95
    n_trials: int = 3
    trial_var_mode: str = "variants"   # or "null"
    rho_variants: float = 0.8          # [ASM]
    sharpe_basis: str = "net"          # or "gross"
    active_vol_ann: float = 0.40       # [ASM]
    bench_vol_ann: float = 0.75        # [ASM]
    bench_drift_ann: float = 0.0       # [ASM] neutral; known market history would be outcome-informed
    rho_active_bench: float = -0.5     # [ASM] long/cash active return is short the market when in cash
    turnover_strategy: float = 0.10    # [ASM] sum |dw| per day (not documented for HR-04)
    turnover_bench: float = 0.005      # [ASM] monthly rebalance of the EW benchmark
    major_weight: float = 0.10         # 2 of 20 names in the BTC/ETH tier
    half_spread_major: float = 0.0001  # s4-mech-v1 tier (NEXT_LICENSED_DATA_STEP.md §1 item 4)
    half_spread_other: float = 0.0004
    slippage: float = 0.0005
    stress_mult: float = 2.0           # on spread and slippage only, never the fee
    regime_split: tuple | None = None  # (first_days, sr_first, sr_rest): stylized decay / emergence; overrides sr
    concentration_on: str = "absolute"  # F4 series: roadmap §1.4 (a) reads it on absolute net P&L; or "active"
    recency_guard: tuple | None = None  # [PROP] (k_days, t_min): also require HAC t >= t_min on the last k days


def cost_rates(d: Design) -> tuple:
    """Blended per-side cost (base, stress) from s4-mech-v1 CostModel tiers; the fee is never stressed."""
    def blended(mult):
        major = CostModel(half_spread=d.half_spread_major * mult, slippage=d.slippage * mult, label="major")
        other = CostModel(half_spread=d.half_spread_other * mult, slippage=d.slippage * mult, label="other")
        return d.major_weight * major.per_side + (1.0 - d.major_weight) * other.per_side
    return blended(1.0), blended(d.stress_mult)


# --- vectorized statistics (same conventions as research/stats; cross-checked in the tests) ----------------------

def hac_t(x: np.ndarray, lag: int) -> np.ndarray:
    """Row-wise Newey-West t of the mean (Bartlett, ddof = 1 convention of research/stats/inference.hac_t)."""
    n = x.shape[1]
    m = x.mean(axis=1, keepdims=True)
    d = x - m
    lrv = (d * d).sum(axis=1) / n
    for lg in range(1, lag + 1):
        lrv = lrv + 2.0 * (1.0 - lg / (lag + 1.0)) * (d[:, lg:] * d[:, :-lg]).sum(axis=1) / n
    lrv = lrv * n / (n - 1.0)
    return m[:, 0] / np.sqrt(np.maximum(lrv, 1e-300) / n)


def moments(x: np.ndarray) -> tuple:
    """Row-wise per-observation Sharpe (sd ddof 1), population skew and non-excess kurtosis (sample_moments)."""
    n = x.shape[1]
    mu = x.mean(axis=1, keepdims=True)
    d = x - mu
    m2 = (d ** 2).mean(axis=1)
    sr = mu[:, 0] / np.sqrt(m2 * n / (n - 1))
    return sr, (d ** 3).mean(axis=1) / m2 ** 1.5, (d ** 4).mean(axis=1) / m2 ** 2


def expected_max_sr(n_trials: int, var: np.ndarray) -> np.ndarray:
    if n_trials == 1:
        return np.zeros_like(var)
    z1 = _N.inv_cdf(1.0 - 1.0 / n_trials)
    z2 = _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return np.sqrt(var) * ((1.0 - _EULER_GAMMA) * z1 + _EULER_GAMMA * z2)


def dsr(sr, skew, kurt, n, n_trials, trial_var) -> np.ndarray:
    """Deflated Sharpe ratio, research/stats/sharpe_deflation.deflated_sharpe_ratio convention."""
    sr0 = expected_max_sr(n_trials, trial_var)
    v = np.maximum(1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr, 1e-12)
    z = (sr - sr0) / np.sqrt(v / (n - 1))
    return 0.5 * (1.0 + _erf(z / math.sqrt(2.0)))


_erf = np.vectorize(math.erf, otypes=[float])


def boot_lower(x: np.ndarray, d: Design, rng: np.random.Generator) -> np.ndarray:
    """Row-wise lower percentile bound of the stationary-bootstrap CI of the mean.

    Politis-Romano: geometric block lengths with mean ``mean_block``, uniform starts, circular wrap; each resample
    mean is a sum of block sums read from a doubled cumulative sum. Independent resamples per row."""
    reps, n = x.shape
    p = 1.0 / d.mean_block
    k = int(math.ceil(n * p * 2.0 + 10.0 * math.sqrt(n * p) + 20))
    lens = rng.geometric(p, size=(reps, d.n_boot, k)).astype(np.int64)
    ends = np.cumsum(lens, axis=2)
    if not (ends[:, :, -1] >= n).all():                     # practically impossible at this k; fail closed
        raise RuntimeError("bootstrap block budget exceeded")
    begins = ends - lens
    eff = np.clip(np.minimum(ends, n) - begins, 0, None)    # truncate the last block, drop blocks past n
    starts = rng.integers(0, n, size=(reps, d.n_boot, k))
    c = np.concatenate([np.zeros((reps, 1)), np.cumsum(np.concatenate([x, x], axis=1), axis=1)], axis=1)
    rows = np.arange(reps)[:, None, None]
    sums = (c[rows, starts + eff] - c[rows, starts]).sum(axis=2)
    a = (1.0 - d.boot_level) / 2.0
    return np.quantile(sums / n, a, axis=1)                 # linear (type 7) as research/stats/inference


def max_drawdown(r: np.ndarray) -> np.ndarray:
    """Row-wise maximum drawdown of the compounded path, as a positive fraction."""
    w = np.cumprod(1.0 + np.maximum(r, -0.999999), axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.ones((r.shape[0], 1)), w], axis=1), axis=1)[:, 1:]
    return (1.0 - w / peak).max(axis=1)


def top5_share(r: np.ndarray) -> np.ndarray:
    """Share of the total (additive) net P&L from the best five 30.44-day blocks; inf when total <= 0."""
    n = r.shape[1]
    edges = np.floor(np.arange(n) / (DAYS_PER_YEAR / 12.0)).astype(int)
    m = np.zeros((r.shape[0], edges[-1] + 1))
    np.add.at(m.T, edges, r.T)
    total = r.sum(axis=1)
    best = -np.sort(-m, axis=1)[:, :5].sum(axis=1)
    return np.where(total > 0, best / np.where(total > 0, total, 1.0), np.inf)


# --- generator ----------------------------------------------------------------------------------------------------

def _std_innov(rng, tails: Tails, shape) -> np.ndarray:
    if tails.df is None:
        return rng.standard_normal(shape)
    if tails.df <= 2:
        raise ValueError("Student-t df must be > 2 for a finite variance")
    return rng.standard_t(tails.df, shape) / math.sqrt(tails.df / (tails.df - 2.0))


def unit_series(rng, tails: Tails, reps: int, n: int) -> tuple:
    """(y, z): y unit-variance active shocks with the requested tails / GARCH / AR(1); z its iid innovations."""
    z = _std_innov(rng, tails, (reps, n))
    e = z
    if tails.garch is not None:
        al, be = tails.garch
        if al < 0 or be < 0 or al + be >= 1:
            raise ValueError("GARCH needs alpha, beta >= 0 and alpha + beta < 1")
        h = np.ones(reps)
        e = np.empty_like(z)
        for t in range(n):
            e[:, t] = np.sqrt(h) * z[:, t]
            h = (1.0 - al - be) + al * e[:, t] ** 2 + be * h
    phi = tails.ar1
    if phi:
        if not -1 < phi < 1:
            raise ValueError("|ar1| must be < 1")
        y = np.empty_like(e)
        y[:, 0] = e[:, 0]
        s = math.sqrt(1.0 - phi * phi)
        for t in range(1, n):
            y[:, t] = phi * y[:, t - 1] + s * e[:, t]
        return y, z
    return e, z


@dataclass
class CellResult:
    window: str
    tails: str
    sr_ann: float
    reps: int
    core: float          # C1 & C2 & C3
    full: float          # core & C4 & not F2..F5
    c1_hac: float
    c2_given_c1_c3: float   # the bootstrap is only run where C1 and C3 pass
    c3_dsr: float
    c4_abs_stress: float
    normal_ref: float    # Phi(SR sqrt(n / 365.25) / sqrt(LRV) - hac_t_min), iid-normal / AR(1) reference
    extra: dict = field(default_factory=dict)


def simulate_cell(window: str, tails: Tails, sr_ann: float, d: Design, reps: int, seed: int,
                  batch: int = 25) -> CellResult:
    n = WINDOWS[window][2]
    base, stress = cost_rates(d)
    drag_active = (d.turnover_strategy - d.turnover_bench) * base
    extra_stress_s = d.turnover_strategy * (stress - base)
    extra_stress_a = (d.turnover_strategy - d.turnover_bench) * (stress - base)
    sd_a = d.active_vol_ann / math.sqrt(DAYS_PER_YEAR)
    sd_b = d.bench_vol_ann / math.sqrt(DAYS_PER_YEAR)
    mu_b = d.bench_drift_ann / DAYS_PER_YEAR - d.turnover_bench * base

    def mu_for(sr):
        mu = sr / math.sqrt(DAYS_PER_YEAR) * sd_a
        return mu - drag_active if d.sharpe_basis == "gross" else mu

    if d.regime_split is None:
        mu_a = np.full(n, mu_for(sr_ann))
    else:
        k, s1, s2 = d.regime_split
        mu_a = np.where(np.arange(n) < k, mu_for(s1), mu_for(s2))
    rng = np.random.default_rng(seed)
    flags = {key: 0 for key in ("core", "full", "c1", "c2", "c3", "c4", "need", "f2", "f3", "f4", "f5")}
    done = 0
    while done < reps:
        m = min(batch, reps - done)
        y, _ = unit_series(rng, tails, m, n)
        a = mu_a + sd_a * y
        u = _std_innov(rng, Tails("iid", tails.df), (m, n))
        b = mu_b + sd_b * (d.rho_active_bench * y + math.sqrt(1.0 - d.rho_active_bench ** 2) * u)
        r = b + a
        c1 = hac_t(a, d.hac_lag) >= d.hac_t_min
        sr, sk, ku = moments(a)
        if d.trial_var_mode == "variants" and d.n_trials > 1:
            srs = [sr]
            for _ in range(d.n_trials - 1):
                w = _std_innov(rng, Tails("iid", tails.df), (m, n))
                v = mu_a + sd_a * (d.rho_variants * y + math.sqrt(1.0 - d.rho_variants ** 2) * w)
                srs.append(moments(v)[0])
            tv = np.var(np.stack(srs), axis=0, ddof=1)
        elif d.trial_var_mode in ("null", "variants"):
            tv = np.full(m, 1.0 / n)
        else:
            raise ValueError("trial_var_mode must be 'variants' or 'null'")
        c3 = dsr(sr, sk, ku, n, d.n_trials, tv) >= d.dsr_min
        c2 = np.zeros(m, dtype=bool)
        need = c1 & c3                       # the bootstrap only matters where C1 and C3 already pass
        if need.any():
            c2[need] = boot_lower(a[need], d, rng) > 0
        c4 = (r - extra_stress_s).mean(axis=1) > 0
        gross_a = a.mean(axis=1) + drag_active
        f2 = (gross_a <= 0) | (drag_active > 0.5 * gross_a)
        sr_r, sr_b = moments(r)[0], moments(b)[0]
        f3 = (max_drawdown(r) > max_drawdown(b)) & (sr_r <= sr_b)
        if d.concentration_on not in ("absolute", "active"):
            raise ValueError("concentration_on must be 'absolute' or 'active'")
        f4 = top5_share(r if d.concentration_on == "absolute" else a) > 0.5
        f5 = (a - extra_stress_a).mean(axis=1) <= 0
        core = c1 & c2 & c3
        if d.recency_guard is not None:
            k, t_min = d.recency_guard
            if not d.hac_lag < k <= n:
                raise ValueError("recency guard length must be in (hac_lag, n]")
            core = core & (hac_t(a[:, -k:], d.hac_lag) >= t_min)
        full = core & c4 & ~f2 & ~f3 & ~f4 & ~f5
        for key, v in (("core", core), ("full", full), ("c1", c1), ("c2", c2), ("c3", c3), ("c4", c4),
                       ("need", need), ("f2", f2 & core), ("f3", f3 & core), ("f4", f4 & core), ("f5", f5 & core)):
            flags[key] += int(v.sum())
        done += m
    lrv = (1 + tails.ar1) / (1 - tails.ar1)
    ref = _N.cdf(sr_ann * math.sqrt(n / DAYS_PER_YEAR) / math.sqrt(lrv) - d.hac_t_min)
    f = {k: v / reps for k, v in flags.items()}
    c2_cond = flags["c2"] / flags["need"] if flags["need"] else float("nan")
    return CellResult(window, tails.name, sr_ann, reps, f["core"], f["full"], f["c1"], c2_cond, f["c3"], f["c4"],
                      ref, {"cost_base_per_side": base, "cost_stress_per_side": stress,
                            "active_cost_drag_ann": drag_active * DAYS_PER_YEAR,
                            "core_and_fails": {k: f[k] for k in ("f2", "f3", "f4", "f5")}})


def delisting_sr_shift(events_per_year: float, p_strategy_holds: float, weight: float, loss: float,
                       active_vol_ann: float) -> float:
    """Annualized active-Sharpe shift from delisting exits that the EW benchmark always carries and the strategy
    carries with probability ``p_strategy_holds`` (same weight): (1 - p) * weight * loss * events / vol."""
    for v in (events_per_year, weight, loss, active_vol_ann):
        if not (isinstance(v, (int, float)) and math.isfinite(v) and v >= 0):
            raise ValueError("inputs must be finite and >= 0")
    if not 0 <= p_strategy_holds <= 1 or active_vol_ann == 0:
        raise ValueError("p in [0, 1] and vol > 0 required")
    return (1.0 - p_strategy_holds) * weight * loss * events_per_year / active_vol_ann


# --- canonical grid ------------------------------------------------------------------------------------------------

TAILS = (
    Tails("normal_iid"),
    Tails("t5_iid", 5.0),
    Tails("t3_iid", 3.0),
    Tails("t4_ar0.1", 4.0, 0.1),
    Tails("t4_ar0.2", 4.0, 0.2),
    Tails("t4_garch", 4.0, 0.0, (0.10, 0.85)),
)
SR_GRID = (0.0, 0.5, 1.0, 1.5)


def canonical(reps: int = 2000, seed: int = 20261027) -> dict:
    d = Design()
    out = {"version": VERSION, "evidence_class": EVIDENCE_CLASS, "reps": reps, "seed": seed,
           "design": asdict(d), "cells": [], "sensitivity": []}
    for wi, w in enumerate(WINDOWS):
        for ti, t in enumerate(TAILS):
            for si, s in enumerate(SR_GRID):
                cell_seed = seed + 10000 * wi + 100 * ti + si
                out["cells"].append(asdict(simulate_cell(w, t, s, d, reps, cell_seed)))
    t4 = Tails("t4_ar0.1", 4.0, 0.1)
    sens = [
        ("hac_t_min_2.128", replace(d, hac_t_min=2.128)),
        ("dsr_null_N3", replace(d, trial_var_mode="null")),
        ("dsr_null_N10000_A19", replace(d, trial_var_mode="null", n_trials=10000)),
        ("turnover_0.05", replace(d, turnover_strategy=0.05)),
        ("turnover_0.20", replace(d, turnover_strategy=0.20)),
        ("gross_basis", replace(d, sharpe_basis="gross")),
        ("concentration_on_active", replace(d, concentration_on="active")),
        ("bench_drift_-0.30", replace(d, bench_drift_ann=-0.30)),
        ("bench_drift_+0.30", replace(d, bench_drift_ann=0.30)),
    ]
    for name, dd in sens:
        for wi, w in enumerate(WINDOWS):
            for si, s in enumerate((0.0, 1.0)):
                r = simulate_cell(w, t4, s, dd, reps, seed + 500000 + 1000 * len(out["sensitivity"]) + 10 * wi + si)
                out["sensitivity"].append({"name": name, **asdict(r)})
    regimes = [("decay_sr1_2019_2022_then_0", (SPLIT_2019_2022_DAYS, 1.0, 0.0)),
               ("emerge_0_then_sr1_2023_2026", (SPLIT_2019_2022_DAYS, 0.0, 1.0))]
    k = WINDOWS["a_2023_2026"][2]
    const1 = (0, 1.0, 1.0)
    for name, split, guard in [(nm, sp, None) for nm, sp in regimes] + [
            (f"{nm}_guard_t{t:g}", sp, (k, t)) for t in (0.0, 1.0) for nm, sp in regimes + [("constant_sr1", const1)]]:
        dd = replace(d, regime_split=split, recency_guard=guard)
        r = simulate_cell("b_2019_2026", t4, float("nan"), dd, reps, seed + 900000 + len(out["sensitivity"]))
        row = asdict(r)
        row["normal_ref"] = None
        out["sensitivity"].append({"name": name, **row})
    return out


def _fmt(out: dict) -> str:
    lines = [f"{VERSION} {EVIDENCE_CLASS} reps={out['reps']} seed={out['seed']}",
             "window | tails | SR 0 core/full | SR 0.5 core/full | SR 1.0 core/full | SR 1.5 core/full | normal ref SR 1.0"]
    cells = out["cells"]
    for w in WINDOWS:
        for t in TAILS:
            row = [c for c in cells if c["window"] == w and c["tails"] == t.name]
            row.sort(key=lambda c: c["sr_ann"])
            parts = [f"{c['core']:.3f}/{c['full']:.3f}" for c in row]
            ref = [c["normal_ref"] for c in row if c["sr_ann"] == 1.0][0]
            lines.append(f"{w} | {t.name} | " + " | ".join(parts) + f" | {ref:.3f}")
    lines.append("sensitivity (t4_ar0.1) | window | SR | core | full | c1 | c2 given c1,c3 | c3 | c4 | core&F4")
    for s in out["sensitivity"]:
        lines.append(f"{s['name']} | {s['window']} | {s['sr_ann']} | {s['core']:.3f} | {s['full']:.3f} | "
                     f"{s['c1_hac']:.3f} | {s['c2_given_c1_c3']:.3f} | {s['c3_dsr']:.3f} | {s['c4_abs_stress']:.3f} | "
                     f"{s['extra']['core_and_fails']['f4']:.3f}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="X1 single-look power simulation (synthetic only; stdout only)")
    ap.add_argument("--reps", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261027)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    out = canonical(a.reps, a.seed)
    sys.stdout.write((json.dumps(out, indent=1, default=str) if a.json else _fmt(out)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
