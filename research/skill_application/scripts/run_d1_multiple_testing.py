"""
TASK D1 — Multiple-testing & PBO audit of prior "edge" selection.

Enumerate the FAMILY of cohort filters ever tried as candidate edges.
For EACH: n, WR, net_exp, PF_net, bootstrap (>=5000) two-sided p-value of net_exp != 0.
Apply Bonferroni (FWER 0.05) and Benjamini-Hochberg (FDR 0.10) across the family.
Compute PBO via CSCV over IS/OOS rank flips of these candidate filters.

A filter "survives" only if it has POSITIVE net_exp AND passes FDR/Bonferroni.
"""
import json
import numpy as np
import pandas as pd
from itertools import combinations
import lib

RNG = np.random.default_rng(12345)
N_BOOT = 10000
OUT = "/home/tradmin/trading-signal-bot/research/skill_application/out"

df = lib.load_trades()
N_ALL = len(df)
net_all = df["net_usdt"].values
print(f"Universe: n={N_ALL} WR={100*df.win.mean():.1f}% net_exp={net_all.mean():.4f} PF_net={lib.pf(net_all):.3f}")

# ---------------------------------------------------------------- candidate family
# Each candidate = (name, boolean mask over df)
cands = []

def add(name, mask):
    mask = np.asarray(mask, bool)
    cands.append((name, mask))

# Baseline (whole universe) is the reference, not a candidate edge per se,
# but include it so PBO has the "do nothing" alternative.
add("ALL", np.ones(N_ALL, bool))

# Indicator > 0 gates
for k in ["rsi","macd","stoch_rsi","rsi_divergence","obv","bollinger",
          "volume","ema_cross","order_book","fibonacci","tf_conf"]:
    col = f"st_{k}"
    add(f"{col}>0", df[col].values > 0)

# Stronger thresholds that appeared in prior memory
add("st_stoch_rsi>=0.6", df["st_stoch_rsi"].values >= 0.6)
add("st_rsi>=1.2", df["st_rsi"].values >= 1.2)
add("st_rsi_divergence>=2.0", df["st_rsi_divergence"].values >= 2.0)
add("st_macd>=1.0", df["st_macd"].values >= 1.0)
add("st_obv>=1.0", df["st_obv"].values >= 1.0)
add("st_tf_conf>=2", df["st_tf_conf"].values >= 2)
add("st_tf_conf>=3", df["st_tf_conf"].values >= 3)

# COMBO (the headline prior claim) + its complement
combo = (df["st_stoch_rsi"].values > 0) & (df["st_rsi_divergence"].values > 0)
add("COMBO_stoch>0&div>0", combo)
add("div>0&NOT_stoch", (df["st_rsi_divergence"].values > 0) & ~(df["st_stoch_rsi"].values > 0))
add("div>0&stoch>=0.6", (df["st_rsi_divergence"].values > 0) & (df["st_stoch_rsi"].values >= 0.6))

# score buckets
for s in [2,3,4,5,6]:
    add(f"score=={s}", df["score"].values == s)
add("score>=5", df["score"].values >= 5)
add("score<=3", df["score"].values <= 3)

# market_condition
for mc in df["market_condition"].dropna().unique():
    add(f"mc={mc}", df["market_condition"].values == mc)

# timeframe
for tf in df["timeframe"].dropna().unique():
    add(f"tf={tf}", df["timeframe"].values == tf)

print(f"Family size (incl ALL): {len(cands)} candidates")

# ---------------------------------------------------------------- per-filter stats + bootstrap p
def boot_pvalue_mean(x, n_boot=N_BOOT, rng=RNG):
    """Two-sided bootstrap p-value for H0: mean(x)==0.
    Use a bootstrap distribution of the mean recentred under the null."""
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return np.nan
    obs = x.mean()
    # recenter to null (mean 0), resample, count how often |boot mean| >= |obs|
    centered = x - obs
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = centered[idx].mean(axis=1)
    p = (np.abs(boot_means) >= np.abs(obs)).mean()
    # add-one smoothing to avoid p=0
    p = (np.sum(np.abs(boot_means) >= np.abs(obs)) + 1) / (n_boot + 1)
    return float(p)

rows = []
for name, mask in cands:
    sub_net = net_all[mask]
    n = int(mask.sum())
    if n == 0:
        rows.append(dict(name=name, n=0, wr=np.nan, net_exp=np.nan, gross_exp=np.nan,
                         pf_net=np.nan, p_boot=np.nan))
        continue
    wr = float(df["win"].values[mask].mean())
    net_exp = float(sub_net.mean())
    gross_exp = float(df["profit_usdt"].values[mask].mean())
    pf_net = lib.pf(sub_net)
    p = boot_pvalue_mean(sub_net)
    rows.append(dict(name=name, n=n, wr=100*wr, net_exp=net_exp, gross_exp=gross_exp,
                     pf_net=pf_net, p_boot=p))

res = pd.DataFrame(rows)

# ---------------------------------------------------------------- multiple-testing corrections
# Family for correction = the candidate EDGE filters (exclude "ALL" reference)
edge = res[res["name"] != "ALL"].copy().reset_index(drop=True)
m = len(edge)
pvals = edge["p_boot"].values

# Bonferroni FWER 0.05
alpha_fwer = 0.05
edge["bonf_thresh"] = alpha_fwer / m
edge["bonf_sig"] = edge["p_boot"] < (alpha_fwer / m)

# Benjamini-Hochberg FDR 0.10
alpha_fdr = 0.10
order = np.argsort(pvals)
ranked_p = pvals[order]
bh_thresh = (np.arange(1, m+1) / m) * alpha_fdr
# largest k such that p_(k) <= (k/m)*alpha
passed = ranked_p <= bh_thresh
if passed.any():
    kmax = np.max(np.where(passed)[0])
    bh_cut = ranked_p[kmax]
else:
    bh_cut = -1.0
edge["bh_sig"] = edge["p_boot"] <= bh_cut

# A filter is a real surviving EDGE only if net_exp>0 AND passes correction
edge["pos_net"] = edge["net_exp"] > 0
edge["survives_bonf"] = edge["bonf_sig"] & edge["pos_net"]
edge["survives_bh"]   = edge["bh_sig"]   & edge["pos_net"]

# ---------------------------------------------------------------- PBO via CSCV
# Build a strategy-return matrix: each candidate filter -> per-trade net return series,
# where trades NOT in the filter contribute 0 (flat). Time-ordered by signal_time.
# CSCV then asks: does the IS-best filter stay good OOS, or does its rank flip?
order_t = np.argsort(df["signal_time"].values)
net_ord = net_all[order_t]

# strategy matrix S[t, j] = net_usdt if trade t passes filter j else 0
filt_names = [nm for nm, _ in cands]
S = np.zeros((N_ALL, len(cands)), float)
for j, (nm, mask) in enumerate(cands):
    S[:, j] = np.where(mask, net_all, 0.0)
S = S[order_t]  # time order

def cscv_pbo(returns, n_groups=8, n_test=4):
    n_obs, n_str = returns.shape
    gsize = n_obs // n_groups
    bounds = [(i*gsize, (i+1)*gsize if i < n_groups-1 else n_obs) for i in range(n_groups)]
    logits = []
    n_overfit = 0
    for test_combo in combinations(range(n_groups), n_test):
        test_set = set(test_combo)
        tr, te = [], []
        for g in range(n_groups):
            s,e = bounds[g]
            (te if g in test_set else tr).extend(range(s,e))
        tr = np.array(tr); te = np.array(te)
        is_perf  = returns[tr].mean(axis=0)
        oos_perf = returns[te].mean(axis=0)
        best = int(np.argmax(is_perf))
        # OOS relative rank of IS-best (fraction of strategies it beats)
        rank = np.mean(oos_perf <= oos_perf[best])   # in [0,1], 1 = best OOS
        # convert to "rank from top" -> overfit if IS-best lands in bottom half OOS
        rel = 1.0 - rank   # 0 = best, 1 = worst
        c = np.clip(rel, 0.01, 0.99)
        logits.append(float(np.log((1-c)/c)))  # high logit = good OOS
        if rel > 0.5:
            n_overfit += 1
    n_paths = len(logits)
    return dict(pbo=n_overfit/n_paths, n_paths=n_paths, n_overfit=n_overfit,
                median_logit=float(np.median(logits)))

pbo = cscv_pbo(S, n_groups=8, n_test=4)

# ---------------------------------------------------------------- DSR for the headline COMBO
from scipy.stats import norm
def sharpe_of(x):
    x = np.asarray(x, float)
    return float(x.mean()/x.std(ddof=1)) if x.std(ddof=1) > 0 else 0.0

combo_net = net_all[combo]
combo_sr = sharpe_of(combo_net)
sk = float(pd.Series(combo_net).skew())
ku = float(pd.Series(combo_net).kurt() + 3.0)  # pandas kurt is excess
# DSR formula from skill (num_trials = full family)
n_trials = len(cands)
bl = len(combo_net)
sr_std = np.sqrt((1 - sk*combo_sr + (ku-1)/4*combo_sr**2)/(bl-1)) if bl > 1 else np.nan
emax = (norm.ppf(1-1/n_trials)*(1-0.5772156649) + 0.5772156649*norm.ppf(1-1/(n_trials*np.e))) if n_trials>1 else 0.0
dsr_combo = float(norm.cdf((combo_sr - emax)/sr_std)) if sr_std and sr_std>0 else np.nan

# ---------------------------------------------------------------- reporting
pd.set_option("display.width", 200, "display.max_columns", 30, "display.max_rows", 100)
show = edge.sort_values("p_boot")[["name","n","wr","gross_exp","net_exp","pf_net","p_boot",
                                   "bonf_sig","bh_sig","survives_bonf","survives_bh"]]
print("\n===== Candidate edge filters (sorted by bootstrap p) =====")
print(show.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

surv_bonf = edge[edge["survives_bonf"]]["name"].tolist()
surv_bh   = edge[edge["survives_bh"]]["name"].tolist()
# also report any positive-net filter regardless of significance
pos = edge[edge["pos_net"]].sort_values("net_exp", ascending=False)

print("\n===== Multiple-testing summary =====")
print(f"Family size m={m}; Bonferroni thresh={alpha_fwer/m:.5f}; BH(FDR=0.10) cutoff p<={bh_cut if bh_cut>=0 else 'NONE'}")
print(f"Filters with POSITIVE net_exp: {len(pos)} / {m}")
print(f"Survive Bonferroni (pos & FWER): {surv_bonf if surv_bonf else 'NONE'}")
print(f"Survive BH FDR0.10 (pos & FDR):  {surv_bh if surv_bh else 'NONE'}")
print("\nPositive-net filters (even if not significant):")
print(pos[["name","n","wr","net_exp","pf_net","p_boot"]].to_string(index=False, float_format=lambda v: f"{v:.4f}"))

print("\n===== PBO (CSCV, 8 groups, 4 test) =====")
print(pbo)

print("\n===== DSR for headline COMBO =====")
print(f"COMBO n={bl} sharpe={combo_sr:.4f} skew={sk:.3f} kurt={ku:.3f} "
      f"E_max(null,{n_trials} trials)={emax:.4f} DSR_pvalue={dsr_combo:.4f} "
      f"significant={dsr_combo>0.95 if dsr_combo==dsr_combo else 'NA'}")

# persist
res.to_csv(f"{OUT}/d1_all_filters.csv", index=False)
edge.to_csv(f"{OUT}/d1_edge_filters.csv", index=False)
summary = dict(
    family_size=int(m), n_all=int(N_ALL),
    bonf_thresh=float(alpha_fwer/m), bh_cutoff=float(bh_cut),
    n_positive_net=int(len(pos)),
    survive_bonferroni=surv_bonf, survive_bh=surv_bh,
    pbo=pbo,
    combo=dict(n=int(bl), wr=float(100*df.win.values[combo].mean()),
               net_exp=float(combo_net.mean()), pf_net=float(lib.pf(combo_net)),
               p_boot=float(edge.loc[edge.name=="COMBO_stoch>0&div>0","p_boot"].iloc[0]),
               sharpe=combo_sr, dsr_pvalue=dsr_combo),
    stoch_gate=dict(
        n=int((df.st_stoch_rsi.values>0).sum()),
        net_exp=float(net_all[df.st_stoch_rsi.values>0].mean()),
        p_boot=float(edge.loc[edge.name=="st_stoch_rsi>0","p_boot"].iloc[0])),
)
with open(f"{OUT}/d1_summary.json","w") as f:
    json.dump(summary, f, indent=2, default=float)
print("\nWrote out/d1_summary.json, d1_all_filters.csv, d1_edge_filters.csv")
