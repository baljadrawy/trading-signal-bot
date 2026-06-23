"""
TASK D4 — Forensic dissection of the COMBO claim (stoch>0 & rsi_divergence>0).
Falsification-first. promising=true only if COMBO survives OOS split AND leave-one-out
AND binomial at p<0.05.
"""
import json
import numpy as np
import pandas as pd
from scipy import stats
import lib

rng = np.random.default_rng(20260623)
BASE_WR = 0.374
out = {}

df = lib.load_trades()
df = df.sort_values("signal_time").reset_index(drop=True)
df["month"] = df["signal_time"].dt.to_period("M").astype(str)

# ---------------------------------------------------------------- COMBO definition
combo_mask = (df["st_stoch_rsi"] > 0) & (df["st_rsi_divergence"] > 0)
combo = df[combo_mask].copy()
out["combo_n"] = int(len(combo))
out["combo_wr"] = float(combo["win"].mean()) if len(combo) else None
out["combo_gross_exp"] = float(combo["profit_usdt"].mean()) if len(combo) else None
out["combo_net_exp"] = float(combo["net_usdt"].mean()) if len(combo) else None
out["combo_pf_net"] = float(lib.pf(combo["net_usdt"].values)) if len(combo) else None
out["combo_net_total"] = float(combo["net_usdt"].sum()) if len(combo) else None

# ---------------------------------------------------------------- FULL trade list
print("="*100)
print("ALL COMBO TRADES (stoch>0 & rsi_divergence>0)")
print("="*100)
cols = ["signal_time","symbol","market_condition","timeframe","profit_usdt","net_usdt","result"]
combo_list = []
for _, r in combo.iterrows():
    rec = {
        "date": str(r["signal_time"]),
        "symbol": r["symbol"],
        "market_condition": r.get("market_condition"),
        "timeframe": r.get("timeframe"),
        "profit_usdt": round(float(r["profit_usdt"]), 4),
        "net_usdt": round(float(r["net_usdt"]), 4),
        "result": r["result"],
        "month": r["month"],
    }
    combo_list.append(rec)
    print(f"{rec['date']:32s} {str(rec['symbol']):14s} {str(rec['market_condition']):16s} "
          f"{str(rec['timeframe']):5s} gross={rec['profit_usdt']:+7.3f} net={rec['net_usdt']:+7.3f} {rec['result']}")
out["combo_trades"] = combo_list

# ---------------------------------------------------------------- Month split (Herfindahl)
by_month = combo.groupby("month").agg(
    n=("win","size"), wins=("win","sum"),
    gross_exp=("profit_usdt","mean"), net_exp=("net_usdt","mean"),
    net_total=("net_usdt","sum")
)
print("\n"+"="*100)
print("COMBO BY MONTH")
print("="*100)
print(by_month.to_string())
out["combo_by_month"] = {m: {"n": int(row.n), "wins": int(row.wins),
                             "wr": float(row.wins/row.n),
                             "net_exp": float(row.net_exp),
                             "net_total": float(row.net_total)}
                         for m, row in by_month.iterrows()}

# Herfindahl over months (concentration of trade COUNT)
shares = (by_month["n"] / by_month["n"].sum()).values
hhi = float(np.sum(shares**2))
out["combo_month_hhi"] = hhi
out["combo_month_effective_n"] = float(1.0/hhi)  # effective number of months
out["combo_n_months"] = int(len(by_month))
print(f"\nHerfindahl (over months, by trade count) = {hhi:.4f}  "
      f"(effective months = {1.0/hhi:.2f}, actual months = {len(by_month)})")

# ---------------------------------------------------------------- IS vs OOS split (strictly by month)
# In-sample = earliest month(s) where COMBO trades first appear; OOS = strictly later months.
months_sorted = sorted(by_month.index.tolist())
out["combo_months_present"] = months_sorted
# Define IS = first month with combo trades, OOS = all strictly later months
is_month = months_sorted[0]
is_mask = combo["month"] == is_month
oos_mask = combo["month"] > is_month
is_tr = combo[is_mask]
oos_tr = combo[oos_mask]

def block(tr):
    if len(tr) == 0:
        return {"n":0,"wins":0,"wr":None,"net_exp":None,"net_total":None}
    return {"n": int(len(tr)), "wins": int(tr["win"].sum()),
            "wr": float(tr["win"].mean()),
            "net_exp": float(tr["net_usdt"].mean()),
            "net_total": float(tr["net_usdt"].sum())}

out["combo_IS_firstmonth"] = is_month
out["combo_IS"] = block(is_tr)
out["combo_OOS_latermonths"] = block(oos_tr)
print("\n"+"="*100)
print(f"IS (first month {is_month}) vs OOS (later months)")
print("="*100)
print("IS :", out["combo_IS"])
print("OOS:", out["combo_OOS_latermonths"])

# Alternative split: by majority month vs rest (the memory says 5/7 in May)
# Identify the dominant month
dom_month = by_month["n"].idxmax()
out["combo_dominant_month"] = dom_month
dom_share = float(by_month.loc[dom_month,"n"] / by_month["n"].sum())
out["combo_dominant_month_share"] = dom_share
non_dom = combo[combo["month"] != dom_month]
out["combo_excluding_dominant_month"] = block(non_dom)
print(f"\nDominant month = {dom_month} ({dom_share*100:.0f}% of combo trades)")
print("COMBO excluding dominant month:", out["combo_excluding_dominant_month"])

# ---------------------------------------------------------------- Bootstrap CI on net_exp (10000)
def bootstrap_ci(x, nboot=10000, alpha=0.05):
    x = np.asarray(x, float)
    n = len(x)
    if n == 0:
        return (None, None, None)
    means = np.empty(nboot)
    for i in range(nboot):
        means[i] = x[rng.integers(0, n, n)].mean()
    lo, hi = np.percentile(means, [100*alpha/2, 100*(1-alpha/2)])
    return float(lo), float(hi), float(means.mean())

lo, hi, bmean = bootstrap_ci(combo["net_usdt"].values)
out["combo_net_exp_boot_mean"] = bmean
out["combo_net_exp_ci95"] = [lo, hi]
out["combo_net_exp_ci_crosses_zero"] = bool(lo is not None and lo <= 0 <= hi)
print("\n"+"="*100)
print("BOOTSTRAP (10000) on COMBO net_exp")
print("="*100)
print(f"net_exp point = {out['combo_net_exp']:+.4f}  boot_mean = {bmean:+.4f}  "
      f"CI95 = [{lo:+.4f}, {hi:+.4f}]  crosses_zero = {out['combo_net_exp_ci_crosses_zero']}")

# Also bootstrap gross_exp (pre-fee) for completeness
glo, ghi, gbmean = bootstrap_ci(combo["profit_usdt"].values)
out["combo_gross_exp_ci95"] = [glo, ghi]
out["combo_gross_exp_ci_crosses_zero"] = bool(glo <= 0 <= ghi)
print(f"gross_exp point = {out['combo_gross_exp']:+.4f}  CI95 = [{glo:+.4f}, {ghi:+.4f}]  "
      f"crosses_zero = {out['combo_gross_exp_ci_crosses_zero']}")

# ---------------------------------------------------------------- Binomial test vs base rate 0.374
n = len(combo); k = int(combo["win"].sum())
bt = stats.binomtest(k, n, BASE_WR, alternative="greater")
out["combo_binom_k_wins"] = k
out["combo_binom_n"] = n
out["combo_binom_base_rate"] = BASE_WR
out["combo_binom_p_greater"] = float(bt.pvalue)
out["combo_binom_significant_p05"] = bool(bt.pvalue < 0.05)
# two-sided for reference
bt2 = stats.binomtest(k, n, BASE_WR, alternative="two-sided")
out["combo_binom_p_twosided"] = float(bt2.pvalue)
print("\n"+"="*100)
print("BINOMIAL TEST (COMBO wins vs base rate 0.374)")
print("="*100)
print(f"k={k}/{n} (WR={k/n:.3f})  H1: WR>0.374  p_greater={bt.pvalue:.4f}  "
      f"p_twosided={bt2.pvalue:.4f}  sig@0.05={out['combo_binom_significant_p05']}")

# ---------------------------------------------------------------- Leave-one-out (remove single best trade)
nv = combo["net_usdt"].values
best_idx = int(np.argmax(nv))
best_trade = combo.iloc[best_idx]
loo = np.delete(nv, best_idx)
out["combo_best_trade"] = {
    "date": str(best_trade["signal_time"]), "symbol": best_trade["symbol"],
    "net_usdt": float(best_trade["net_usdt"]), "result": best_trade["result"],
    "month": best_trade["month"]
}
out["combo_net_exp_LOO"] = float(loo.mean())
out["combo_net_exp_LOO_positive"] = bool(loo.mean() > 0)
out["combo_net_total_LOO"] = float(loo.sum())
loo_lo, loo_hi, loo_bmean = bootstrap_ci(loo)
out["combo_net_exp_LOO_ci95"] = [loo_lo, loo_hi]
print("\n"+"="*100)
print("LEAVE-ONE-OUT (remove single best trade)")
print("="*100)
print(f"best trade: {best_trade['symbol']} {best_trade['signal_time']} net={best_trade['net_usdt']:+.3f} ({best_trade['month']})")
print(f"net_exp full = {out['combo_net_exp']:+.4f}  -> LOO net_exp = {loo.mean():+.4f}  "
      f"positive_after_LOO = {out['combo_net_exp_LOO_positive']}  CI95=[{loo_lo:+.4f},{loo_hi:+.4f}]")

# ============================================================================
# STOCH>0 GATE TEST
# ============================================================================
print("\n\n"+"#"*100)
print("STOCH>0 GATE TEST")
print("#"*100)
g_pos = df[df["st_stoch_rsi"] > 0]
g_zero = df[df["st_stoch_rsi"] <= 0]
out["stoch_pos_n"] = int(len(g_pos)); out["stoch_zero_n"] = int(len(g_zero))
out["stoch_pos_wr"] = float(g_pos["win"].mean())
out["stoch_zero_wr"] = float(g_zero["win"].mean())
out["stoch_pos_net_exp"] = float(g_pos["net_usdt"].mean())
out["stoch_zero_net_exp"] = float(g_zero["net_usdt"].mean())
out["stoch_pos_gross_exp"] = float(g_pos["profit_usdt"].mean())
out["stoch_zero_gross_exp"] = float(g_zero["profit_usdt"].mean())
out["stoch_net_exp_diff"] = out["stoch_pos_net_exp"] - out["stoch_zero_net_exp"]
print(f"stoch>0 : n={len(g_pos):5d} WR={g_pos['win'].mean():.3f} net_exp={g_pos['net_usdt'].mean():+.4f} gross_exp={g_pos['profit_usdt'].mean():+.4f}")
print(f"stoch=0 : n={len(g_zero):5d} WR={g_zero['win'].mean():.3f} net_exp={g_zero['net_usdt'].mean():+.4f} gross_exp={g_zero['profit_usdt'].mean():+.4f}")

# bootstrap CI on the DIFFERENCE of net_exp (stoch>0 minus stoch=0)
def bootstrap_diff_ci(a, b, nboot=10000, alpha=0.05):
    a = np.asarray(a, float); b = np.asarray(b, float)
    na, nb = len(a), len(b)
    diffs = np.empty(nboot)
    for i in range(nboot):
        diffs[i] = a[rng.integers(0,na,na)].mean() - b[rng.integers(0,nb,nb)].mean()
    lo, hi = np.percentile(diffs, [100*alpha/2, 100*(1-alpha/2)])
    return float(lo), float(hi), float(diffs.mean())
dlo, dhi, dmean = bootstrap_diff_ci(g_pos["net_usdt"].values, g_zero["net_usdt"].values)
out["stoch_diff_net_exp_ci95"] = [dlo, dhi]
out["stoch_diff_ci_crosses_zero"] = bool(dlo <= 0 <= dhi)
out["stoch_diff_boot_mean"] = dmean
print(f"diff(stoch>0 - stoch=0) net_exp = {out['stoch_net_exp_diff']:+.4f}  "
      f"CI95=[{dlo:+.4f},{dhi:+.4f}]  crosses_zero={out['stoch_diff_ci_crosses_zero']}")

# Is stoch>0 itself profitable net? (the gate claim)
slo, shi, sbm = bootstrap_ci(g_pos["net_usdt"].values)
out["stoch_pos_net_exp_ci95"] = [slo, shi]
out["stoch_pos_net_exp_positive"] = bool(slo > 0)
print(f"stoch>0 net_exp CI95 = [{slo:+.4f},{shi:+.4f}]  itself_profitable_net = {out['stoch_pos_net_exp_positive']}")

# ---------------------------------------------------------------- Replication within April alone
apr = df[df["month"] == "2026-04"]
apr_pos = apr[apr["st_stoch_rsi"] > 0]
apr_zero = apr[apr["st_stoch_rsi"] <= 0]
out["april_n"] = int(len(apr))
out["april_stoch_pos_n"] = int(len(apr_pos))
out["april_stoch_zero_n"] = int(len(apr_zero))
out["april_stoch_pos_wr"] = float(apr_pos["win"].mean()) if len(apr_pos) else None
out["april_stoch_zero_wr"] = float(apr_zero["win"].mean()) if len(apr_zero) else None
out["april_stoch_pos_net_exp"] = float(apr_pos["net_usdt"].mean()) if len(apr_pos) else None
out["april_stoch_zero_net_exp"] = float(apr_zero["net_usdt"].mean()) if len(apr_zero) else None
print("\n"+"-"*100)
print("STOCH>0 GATE REPLICATION WITHIN APRIL ALONE (largest window)")
print("-"*100)
print(f"April total n={len(apr)}")
print(f"  stoch>0 : n={len(apr_pos):5d} WR={apr_pos['win'].mean() if len(apr_pos) else float('nan'):.3f} "
      f"net_exp={apr_pos['net_usdt'].mean() if len(apr_pos) else float('nan'):+.4f}")
print(f"  stoch=0 : n={len(apr_zero):5d} WR={apr_zero['win'].mean() if len(apr_zero) else float('nan'):.3f} "
      f"net_exp={apr_zero['net_usdt'].mean() if len(apr_zero) else float('nan'):+.4f}")
if len(apr_pos) and len(apr_zero):
    adlo, adhi, adm = bootstrap_diff_ci(apr_pos["net_usdt"].values, apr_zero["net_usdt"].values)
    out["april_stoch_diff_net_exp"] = float(apr_pos["net_usdt"].mean() - apr_zero["net_usdt"].mean())
    out["april_stoch_diff_ci95"] = [adlo, adhi]
    out["april_stoch_diff_ci_crosses_zero"] = bool(adlo <= 0 <= adhi)
    print(f"  diff net_exp = {out['april_stoch_diff_net_exp']:+.4f}  CI95=[{adlo:+.4f},{adhi:+.4f}]  "
          f"crosses_zero={out['april_stoch_diff_ci_crosses_zero']}")

# Also: April-only COMBO replication
apr_combo = apr[(apr["st_stoch_rsi"]>0)&(apr["st_rsi_divergence"]>0)]
out["april_combo_n"] = int(len(apr_combo))
out["april_combo_wr"] = float(apr_combo["win"].mean()) if len(apr_combo) else None
out["april_combo_net_exp"] = float(apr_combo["net_usdt"].mean()) if len(apr_combo) else None
print(f"\nApril-only COMBO: n={len(apr_combo)} "
      f"WR={apr_combo['win'].mean() if len(apr_combo) else float('nan'):.3f} "
      f"net_exp={apr_combo['net_usdt'].mean() if len(apr_combo) else float('nan'):+.4f}")

# ============================================================================
# VERDICT GATES
# ============================================================================
g_oos = bool(out["combo_OOS_latermonths"]["n"] > 0 and
             out["combo_OOS_latermonths"]["net_exp"] is not None and
             out["combo_OOS_latermonths"]["net_exp"] > 0)
g_loo = bool(out["combo_net_exp_LOO_positive"])
g_binom = bool(out["combo_binom_significant_p05"])
out["verdict_OOS_positive"] = g_oos
out["verdict_LOO_positive"] = g_loo
out["verdict_binom_p05"] = g_binom
out["verdict_all_pass"] = bool(g_oos and g_loo and g_binom)
print("\n\n"+"="*100)
print("VERDICT GATES (promising requires ALL three)")
print("="*100)
print(f"  OOS net_exp > 0 (later months) : {g_oos}")
print(f"  Leave-one-out net_exp > 0      : {g_loo}")
print(f"  Binomial p<0.05 (WR>0.374)     : {g_binom}  (p={out['combo_binom_p_greater']:.4f})")
print(f"  ALL PASS (promising)           : {out['verdict_all_pass']}")

with open("/home/tradmin/trading-signal-bot/research/skill_application/out/d4_combo_forensics.json","w") as f:
    json.dump(out, f, indent=2, default=str)
print("\nwrote out/d4_combo_forensics.json")
