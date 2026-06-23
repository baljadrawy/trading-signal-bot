"""
TASK D2 — Deflated Sharpe Ratio & trial-adjusted significance.

For each cohort (FULL system, stoch>0 gate, COMBO), treat net_usdt as a per-trade
return stream ordered by exit_time. Compute:
  - per-trade Sharpe, annualized Sharpe (bars/year from avg trade duration),
  - skew, kurtosis (non-excess),
  - Deflated Sharpe Ratio (Bailey & Lopez de Prado) for N independent trials,
  - DSR p-value, sensitivity to N in {1,10,20,30,40},
  - Minimum Track Record Length (minTRL) for significance at observed Sharpe.

Conclusion: is any positive-Sharpe cohort statistically distinguishable from
zero after deflation? promising=true only if DSR p<0.05 for positive-SR cohort.
"""
import json
import sys
import numpy as np
import pandas as pd
from scipy.stats import norm, skew as sp_skew, kurtosis as sp_kurt
import lib

sys.path.insert(0, "/home/tradmin/trading-signal-bot/research/external_skills/skills/walk-forward-validation/scripts")
import overfit_detector as od  # noqa: E402

OUT = "/home/tradmin/trading-signal-bot/research/skill_application/out/dsr_d2.json"


def sr_pertrade(r):
    r = np.asarray(r, float)
    mu, sd = r.mean(), r.std(ddof=1)
    return float(mu / sd) if sd > 0 else 0.0


def minTRL(sr_pt, skew_v, kurt_v, target_p=0.95):
    """Minimum Track Record Length (Bailey & LdP 2012): number of obs so that
    the probabilistic Sharpe ratio PSR(SR*=0) reaches target_p, given the
    observed per-trade (non-annualized) Sharpe.  Returns obs count."""
    if sr_pt <= 0:
        return float("inf")
    z = norm.ppf(target_p)
    var_factor = 1.0 - skew_v * sr_pt + (kurt_v - 1.0) / 4.0 * sr_pt**2
    return float(1.0 + var_factor * (z / sr_pt) ** 2)


def psr(sr_pt, n, skew_v, kurt_v, sr_benchmark=0.0):
    """Probabilistic Sharpe Ratio: P(true SR > benchmark) given observed SR."""
    if n < 2:
        return np.nan
    se = np.sqrt((1.0 - skew_v * sr_pt + (kurt_v - 1.0) / 4.0 * sr_pt**2) / (n - 1))
    if se <= 0:
        return 1.0 if sr_pt > sr_benchmark else 0.0
    return float(norm.cdf((sr_pt - sr_benchmark) / se))


def analyze(name, sub, full_df, n_trials_list=(1, 10, 20, 30, 40)):
    sub = sub.sort_values("exit_time")
    r = sub["net_usdt"].values.astype(float)
    n = len(r)
    mu = float(r.mean())
    sd = float(r.std(ddof=1)) if n > 1 else 0.0
    sr_pt = sr_pertrade(r)
    sk = float(sp_skew(r)) if n > 2 else 0.0
    ku = float(sp_kurt(r, fisher=False)) if n > 3 else 3.0  # non-excess

    # bars/year from avg trade duration -> trades per year
    avg_dur_h = float(sub["duration_hours"].mean())
    trades_per_year = (365.0 * 24.0) / avg_dur_h if avg_dur_h > 0 else np.nan
    ann_factor = np.sqrt(trades_per_year) if np.isfinite(trades_per_year) else np.nan
    sr_ann = sr_pt * ann_factor if np.isfinite(ann_factor) else np.nan

    # naive p-value (no deflation): one-sided SR>0
    se_pt = np.sqrt((1.0 - sk * sr_pt + (ku - 1.0) / 4.0 * sr_pt**2) / (n - 1)) if n > 1 else np.nan
    p_naive = float(1.0 - norm.cdf(sr_pt / se_pt)) if (se_pt and se_pt > 0) else np.nan
    psr_val = psr(sr_pt, n, sk, ku, 0.0)  # P(SR>0)

    # DSR sensitivity to number of trials N
    dsr_by_N = {}
    for N in n_trials_list:
        # operate on per-trade SR (annualization=1 so de-annualize is identity)
        res = od.deflated_sharpe_ratio(
            observed_sr=sr_pt, num_trials=N, backtest_length=max(n, 10),
            skewness=sk, kurtosis=ku, annualization=1.0,
        )
        # dsr_pvalue here = P(SR>expected_max under null) = "probability it's real"
        # significance at 0.05 => need this >= 0.95
        dsr_by_N[str(N)] = {
            "expected_max_sr_pt": round(res.expected_max_sr, 5),
            "dsr_prob_real": round(res.dsr_pvalue, 5),     # want >=0.95
            "p_value": round(1.0 - res.dsr_pvalue, 5),     # want <0.05
            "significant_p05": bool(res.dsr_pvalue >= 0.95),
        }

    # minimum track record length for significance at observed SR (per-trade)
    mtrl = minTRL(sr_pt, sk, ku, 0.95)

    return {
        "name": name,
        "n": n,
        "WR": round(float(sub["win"].mean()), 4),
        "net_exp_usd": round(mu, 4),
        "net_std_usd": round(sd, 4),
        "PF_net": round(lib.pf(r), 4),
        "sharpe_per_trade": round(sr_pt, 5),
        "avg_duration_h": round(avg_dur_h, 3),
        "trades_per_year": round(trades_per_year, 1) if np.isfinite(trades_per_year) else None,
        "annualization_factor": round(ann_factor, 3) if np.isfinite(ann_factor) else None,
        "sharpe_annualized": round(sr_ann, 4) if np.isfinite(sr_ann) else None,
        "skew": round(sk, 4),
        "kurtosis_nonexcess": round(ku, 4),
        "p_naive_SR_gt0": round(p_naive, 5) if np.isfinite(p_naive) else None,
        "PSR_prob_SR_gt0": round(psr_val, 5),
        "minTRL_obs_for_p05": round(mtrl, 1) if np.isfinite(mtrl) else None,
        "minTRL_vs_have": (round(mtrl / n, 2) if np.isfinite(mtrl) else None),
        "dsr_by_num_trials": dsr_by_N,
    }


def main():
    df = lib.load_trades()
    full = df
    gate = df[df.st_stoch_rsi > 0]
    combo = df[(df.st_stoch_rsi > 0) & (df.st_rsi_divergence > 0)]

    cohorts = [
        ("FULL_system", full),
        ("stoch_gate_>0", gate),
        ("COMBO_stoch&div", combo),
    ]
    results = {}
    for name, sub in cohorts:
        results[name] = analyze(name, sub, full)

    # --- A null calibration: how many filters in the family beat zero net by chance?
    # The "family" of single-indicator gates that could have been tried:
    fam = {}
    for k in lib.SCORE_KEYS:
        col = f"st_{k}"
        s = df[df[col] > 0]
        if len(s) >= 20:
            fam[k] = {
                "n": int(len(s)),
                "WR": round(float(s.win.mean()), 4),
                "net_exp": round(float(s.net_usdt.mean()), 4),
                "sharpe_pt": round(sr_pertrade(s.net_usdt.values), 5),
            }
    # plus the combo family member
    results["_single_gate_family"] = fam
    results["_family_size_observed"] = len(fam)
    # number of gates with positive per-trade sharpe (candidate "winners")
    pos = [k for k, v in fam.items() if v["sharpe_pt"] > 0]
    results["_family_positive_sharpe_gates"] = pos

    # headline verdict
    combo_r = results["COMBO_stoch&div"]
    best_dsr_at_20 = combo_r["dsr_by_num_trials"]["20"]
    verdict = {
        "combo_sharpe_pt": combo_r["sharpe_per_trade"],
        "combo_sharpe_ann": combo_r["sharpe_annualized"],
        "combo_DSR_p_at_N20": best_dsr_at_20["p_value"],
        "combo_significant_at_N20_p05": best_dsr_at_20["significant_p05"],
        "combo_minTRL_obs": combo_r["minTRL_obs_for_p05"],
        "combo_have_n": combo_r["n"],
    }
    results["_verdict"] = verdict

    with open(OUT, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # print summary
    for name in ["FULL_system", "stoch_gate_>0", "COMBO_stoch&div"]:
        r = results[name]
        print(f"\n=== {name} ===")
        print(f"  n={r['n']} WR={r['WR']} net_exp={r['net_exp_usd']} PF_net={r['PF_net']}")
        print(f"  SR/trade={r['sharpe_per_trade']} SR_ann={r['sharpe_annualized']} "
              f"(trades/yr={r['trades_per_year']}, ann_factor={r['annualization_factor']})")
        print(f"  skew={r['skew']} kurt={r['kurtosis_nonexcess']} "
              f"p_naive={r['p_naive_SR_gt0']} PSR(SR>0)={r['PSR_prob_SR_gt0']}")
        print(f"  minTRL for p<0.05 = {r['minTRL_obs_for_p05']} obs (have {r['n']}, "
              f"ratio {r['minTRL_vs_have']}x)")
        print(f"  DSR by N: ", {k: v["p_value"] for k, v in r["dsr_by_num_trials"].items()})
    print("\nFamily of single-indicator gates (n>=20):")
    for k, v in fam.items():
        print(f"  {k:16s} n={v['n']:5d} WR={v['WR']} net_exp={v['net_exp']} SR_pt={v['sharpe_pt']}")
    print("\nPositive-Sharpe single gates:", pos)
    print("\nVERDICT:", json.dumps(verdict, indent=2))
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
