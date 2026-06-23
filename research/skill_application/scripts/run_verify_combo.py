"""
ADVERSARIAL VERIFICATION of CLAIM:
  "COMBO (stoch>0 & rsi_divergence>0) is a deployable edge."

Default to refuted=true. Attack on: sample size, concentration, OOS, fees, multiple testing,
few-trade-driven, sensitivity to definition.
"""
import sys, json
import numpy as np
import pandas as pd
from scipy import stats
import lib

sys.path.insert(0, "/home/tradmin/trading-signal-bot/research/external_skills/skills/walk-forward-validation/scripts")
from overfit_detector import deflated_sharpe_ratio

df = lib.load_trades()
N = len(df)
FEE = lib.FEE_USD

out = {}

# ---- Define COMBO exactly as claimed
stoch = df["st_stoch_rsi"] > 0
div   = df["st_rsi_divergence"] > 0
combo = stoch & div

sub = df[combo].copy().sort_values("exit_time")
out["combo_n"] = int(len(sub))
out["combo_wr"] = float(sub["win"].mean()) if len(sub) else float("nan")
out["combo_net_exp"] = float(sub["net_usdt"].mean()) if len(sub) else float("nan")
out["combo_gross_exp"] = float(sub["profit_usdt"].mean()) if len(sub) else float("nan")
out["combo_net_total"] = float(sub["net_usdt"].sum()) if len(sub) else float("nan")
out["combo_pf_net"] = lib.pf(sub["net_usdt"].values) if len(sub) else float("nan")
out["combo_pf_gross"] = lib.pf(sub["profit_usdt"].values) if len(sub) else float("nan")

# Baseline
out["base_n"] = int(N)
out["base_wr"] = float(df["win"].mean())
out["base_net_exp"] = float(df["net_usdt"].mean())

# ---- Concentration by month
sub["month"] = sub["exit_time"].dt.to_period("M").astype(str)
month_tbl = sub.groupby("month").agg(n=("win","size"), wins=("win","sum"),
                                     net=("net_usdt","sum")).reset_index()
out["combo_by_month"] = month_tbl.to_dict("records")

# Concentration by symbol
sym_tbl = sub.groupby("symbol").agg(n=("win","size"), wins=("win","sum"),
                                    net=("net_usdt","sum")).reset_index().sort_values("n", ascending=False)
out["combo_by_symbol"] = sym_tbl.head(15).to_dict("records")
out["combo_unique_symbols"] = int(sub["symbol"].nunique())

# ---- Leave-one-out fragility: drop biggest winner, recompute net exp & WR
if len(sub) > 1:
    nets = sub["net_usdt"].values
    wins = sub["win"].values
    drop_idx = int(np.argmax(nets))
    loo_net = np.delete(nets, drop_idx)
    loo_win = np.delete(wins, drop_idx)
    out["loo_drop_biggest_win_net_exp"] = float(loo_net.mean())
    out["loo_drop_biggest_win_wr"] = float(loo_win.mean())
    # drop 2 biggest winners
    order = np.argsort(nets)[::-1]
    keep = np.ones(len(nets), bool); keep[order[:2]] = False
    out["loo_drop_top2_net_exp"] = float(nets[keep].mean())
    out["loo_drop_top2_wr"] = float(wins[keep].mean())

# ---- OOS split: train on May-and-before, test on June (the natural forward window)
sub["ym"] = sub["exit_time"].dt.strftime("%Y-%m")
is_mask = sub["exit_time"] < pd.Timestamp("2026-06-01", tz="UTC")
oos = sub[~is_mask]
ins = sub[is_mask]
out["IS_n"] = int(len(ins)); out["OOS_n"] = int(len(oos))
out["IS_wr"] = float(ins["win"].mean()) if len(ins) else float("nan")
out["OOS_wr"] = float(oos["win"].mean()) if len(oos) else float("nan")
out["IS_net_exp"] = float(ins["net_usdt"].mean()) if len(ins) else float("nan")
out["OOS_net_exp"] = float(oos["net_usdt"].mean()) if len(oos) else float("nan")
out["OOS_net_total"] = float(oos["net_usdt"].sum()) if len(oos) else float("nan")

# ---- Statistical: is COMBO WR significantly > baseline WR? (one-sided binomial / 2-prop z)
k = int(sub["win"].sum()); n = int(len(sub))
p0 = float(df["win"].mean())
# exact binomial one-sided (greater)
binom_p = stats.binomtest(k, n, p0, alternative="greater").pvalue if n > 0 else 1.0
out["combo_wr_vs_base_binom_p_onesided"] = float(binom_p)

# Is net expectancy > 0? one-sample t-test on net pnl (one-sided greater)
if n > 1:
    t_stat, t_p_two = stats.ttest_1samp(sub["net_usdt"].values, 0.0)
    t_p_one = (t_p_two/2) if t_stat > 0 else (1 - t_p_two/2)
    out["combo_net_pos_t_p_onesided"] = float(t_p_one)
    out["combo_net_t_stat"] = float(t_stat)

# ---- Multiple testing: COMBO is one of MANY indicator>0 pairwise combos that were screened.
# Enumerate all pairwise "indicator>0 & indicator>0" filters, compute net expectancy, rank COMBO.
keys = [f"st_{k}" for k in lib.SCORE_KEYS]
pairs = []
for i in range(len(keys)):
    for j in range(i+1, len(keys)):
        a, b = keys[i], keys[j]
        m = (df[a] > 0) & (df[b] > 0)
        nn = int(m.sum())
        if nn >= 5:
            pairs.append({"pair": f"{a[3:]}&{b[3:]}", "n": nn,
                          "wr": float(df.loc[m,"win"].mean()),
                          "net_exp": float(df.loc[m,"net_usdt"].mean()),
                          "net_total": float(df.loc[m,"net_usdt"].sum())})
pairs_df = pd.DataFrame(pairs).sort_values("net_exp", ascending=False).reset_index(drop=True)
out["n_pairwise_filters_tested"] = int(len(pairs_df))
# rank of combo
combo_name = "stoch_rsi&rsi_divergence"
rank = pairs_df.index[pairs_df["pair"] == combo_name]
out["combo_rank_by_net_exp_among_pairs"] = int(rank[0]) + 1 if len(rank) else None
out["top5_pairs_by_net_exp"] = pairs_df.head(5).to_dict("records")
out["n_pairs_with_positive_net_exp"] = int((pairs_df["net_exp"] > 0).sum())

# DSR on COMBO per-trade net returns (as fraction of position), num_trials = number of filters screened
ret = sub["net_usdt"].values / lib.POS_USDT
out["combo_DSR_runnable"] = bool(len(ret) >= 10)
if len(ret) >= 10 and ret.std() > 0:
    sr = float(ret.mean() / ret.std())
    skew = float(stats.skew(ret)); kurt = float(stats.kurtosis(ret, fisher=False))
    n_trials = max(2, int(len(pairs_df)))  # number of pairwise filters as the search space
    dsr = deflated_sharpe_ratio(observed_sr=sr, num_trials=n_trials,
                                backtest_length=len(ret), skewness=skew, kurtosis=kurt)
    out["combo_per_trade_SR"] = sr
    out["combo_DSR_pvalue"] = float(dsr.dsr_pvalue)
    out["combo_DSR_expected_max_sr"] = float(dsr.expected_max_sr)
    out["combo_DSR_significant"] = bool(dsr.is_significant)
    out["combo_DSR_num_trials"] = n_trials
else:
    out["combo_DSR_note"] = f"n={len(ret)} < 10: DSR cannot run (insufficient backtest length)"

# ---- Definition sensitivity: stoch>0 & div>0 vs div alone vs stoch alone
for name, m in [("stoch_only", stoch & ~div),
                ("div_only", div & ~stoch),
                ("div_any", div),
                ("stoch_any", stoch),
                ("neither", ~stoch & ~div)]:
    mm = df[m]
    out[f"sens_{name}"] = {"n": int(len(mm)),
                           "wr": float(mm["win"].mean()) if len(mm) else float("nan"),
                           "net_exp": float(mm["net_usdt"].mean()) if len(mm) else float("nan")}

# ---- Wilson 95% CI on COMBO WR (lower bound vs baseline)
def wilson(k, n, z=1.96):
    if n == 0: return (np.nan, np.nan)
    p = k/n; d = 1 + z*z/n
    c = (p + z*z/(2*n))/d
    h = z*np.sqrt(p*(1-p)/n + z*z/(4*n*n))/d
    return (c-h, c+h)
lo, hi = wilson(k, n)
out["combo_wr_wilson_ci"] = [float(lo), float(hi)]
out["combo_wr_ci_lower_above_base"] = bool(lo > p0)

# Save
with open("/home/tradmin/trading-signal-bot/research/skill_application/out/verify_combo.json","w") as f:
    json.dump(out, f, indent=2, default=str)

# Print summary
def p(label, v): print(f"{label:42s} {v}")
print("="*70)
print("COMBO ADVERSARIAL VERIFICATION")
print("="*70)
p("COMBO n / WR", f"{out['combo_n']} / {out['combo_wr']:.1%}")
p("baseline n / WR", f"{out['base_n']} / {out['base_wr']:.1%}")
p("COMBO net exp / total", f"${out['combo_net_exp']:.3f} / ${out['combo_net_total']:.2f}")
p("COMBO PF gross / net", f"{out['combo_pf_gross']:.2f} / {out['combo_pf_net']:.2f}")
print("-- concentration --")
for r in out["combo_by_month"]: print("  month", r)
p("unique symbols", out["combo_unique_symbols"])
print("  top symbols:", out["combo_by_symbol"][:5])
print("-- fragility (leave-one-out) --")
p("drop biggest win -> net_exp/WR", f"${out.get('loo_drop_biggest_win_net_exp',float('nan')):.3f} / {out.get('loo_drop_biggest_win_wr',float('nan')):.1%}")
p("drop top-2 wins -> net_exp/WR", f"${out.get('loo_drop_top2_net_exp',float('nan')):.3f} / {out.get('loo_drop_top2_wr',float('nan')):.1%}")
print("-- OOS (June) --")
p("IS n/WR/net_exp", f"{out['IS_n']} / {out['IS_wr']:.1%} / ${out['IS_net_exp']:.3f}")
p("OOS n/WR/net_exp/total", f"{out['OOS_n']} / {out['OOS_wr']:.1%} / ${out['OOS_net_exp']:.3f} / ${out['OOS_net_total']:.2f}")
print("-- stats --")
p("WR>base binomial p (1-sided)", f"{out['combo_wr_vs_base_binom_p_onesided']:.4f}")
p("net>0 t-test p (1-sided)", f"{out.get('combo_net_pos_t_p_onesided',float('nan')):.4f}")
p("Wilson 95% CI on WR", [round(x,3) for x in out['combo_wr_wilson_ci']])
p("CI lower above baseline?", out["combo_wr_ci_lower_above_base"])
print("-- multiple testing --")
p("pairwise filters tested", out["n_pairwise_filters_tested"])
p("COMBO rank by net_exp (of pairs)", out["combo_rank_by_net_exp_among_pairs"])
p("pairs w/ positive net_exp", out["n_pairs_with_positive_net_exp"])
p("DSR p-value / significant", f"{out.get('combo_DSR_pvalue',float('nan')):.4f} / {out.get('combo_DSR_significant')}")
print("-- definition sensitivity --")
for nm in ["stoch_only","div_only","div_any","stoch_any","neither"]:
    s = out[f"sens_{nm}"]
    print(f"  {nm:12s} n={s['n']:5d} WR={s['wr']:.1%} net_exp=${s['net_exp']:.3f}")
print("="*70)
print("Saved -> out/verify_combo.json")
