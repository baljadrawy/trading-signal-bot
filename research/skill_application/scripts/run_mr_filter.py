"""
TASK E_MR — Mean-reversion filter study.
Does trading only mean-reverting symbols flip expectancy after fees?

For every traded symbol with OHLCV: Hurst, OU half-life, ADF p (close & log-close).
Classify MR = Hurst<0.45 OR adf_p<0.05. Join to trades. Compare WR/net_exp/PF_net/n
for MR vs trending(covered, not-MR) vs uncovered. Overall AND April-only.
Bootstrap CI on net_exp difference (MR - trending). promising only if MR net_exp>0
with bootstrap CI excluding 0.
"""
import json
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller
import lib

OUT = "/home/tradmin/trading-signal-bot/research/skill_application/out"
RNG = np.random.default_rng(42)

def adf_p(series):
    """ADF p-value on a level series. Returns nan on failure/degenerate."""
    x = np.asarray(series, float)
    x = x[np.isfinite(x)]
    if len(x) < 30 or np.std(x) < 1e-12:
        return np.nan
    try:
        # autolag AIC, regression 'c' (constant, no trend) — standard for price levels
        return float(adfuller(x, autolag="AIC", regression="c")[1])
    except Exception:
        return np.nan

def boot_ci_diff(a, b, n_boot=10000, alpha=0.05):
    """Bootstrap CI for mean(a)-mean(b). a,b are arrays of per-trade net_usdt."""
    a = np.asarray(a, float); b = np.asarray(b, float)
    if len(a) == 0 or len(b) == 0:
        return (np.nan, np.nan, np.nan)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        sa = RNG.choice(a, size=len(a), replace=True)
        sb = RNG.choice(b, size=len(b), replace=True)
        diffs[i] = sa.mean() - sb.mean()
    lo, hi = np.percentile(diffs, [100*alpha/2, 100*(1-alpha/2)])
    return (float(diffs.mean()), float(lo), float(hi))

def boot_ci_mean(a, n_boot=10000, alpha=0.05):
    """Bootstrap CI for the mean of a (per-trade net_usdt)."""
    a = np.asarray(a, float)
    if len(a) == 0:
        return (np.nan, np.nan, np.nan)
    means = np.empty(n_boot)
    for i in range(n_boot):
        means[i] = RNG.choice(a, size=len(a), replace=True).mean()
    lo, hi = np.percentile(means, [100*alpha/2, 100*(1-alpha/2)])
    return (float(a.mean()), float(lo), float(hi))

def stats_block(sub):
    """Return dict of n, WR, gross_exp, net_exp, PF_net for a trade subset."""
    if len(sub) == 0:
        return dict(n=0, WR=np.nan, gross_exp=np.nan, net_exp=np.nan, PF_net=np.nan)
    return dict(
        n=int(len(sub)),
        WR=float(sub["win"].mean()),
        gross_exp=float(sub["profit_usdt"].mean()),
        net_exp=float(sub["net_usdt"].mean()),
        PF_net=float(lib.pf(sub["net_usdt"].values)),
    )

# ------------------------------------------------------------------ load
t = lib.load_trades()
idx = lib.ohlcv_index()
traded = sorted(t["symbol"].unique())
covered_syms = [s for s in traded if s in idx]

# ------------------------------------------------------------------ per-symbol MR diagnostics
rows = []
n_trades_by_sym = t["symbol"].value_counts().to_dict()
for s in covered_syms:
    close = lib.load_close(s)
    if close is None or len(close) < 60:
        rows.append(dict(symbol=s, hurst=np.nan, half_life=np.nan,
                         adf_p=np.nan, adf_p_log=np.nan,
                         n_bars=(0 if close is None else len(close)),
                         n_trades=n_trades_by_sym.get(s, 0)))
        continue
    c = close.dropna().values
    H = lib.hurst(close)
    HL = lib.half_life(close)
    p_lvl = adf_p(c)
    logc = np.log(c[c > 0]) if (c > 0).all() else np.log(np.clip(c, 1e-12, None))
    p_log = adf_p(logc)
    rows.append(dict(symbol=s, hurst=H, half_life=HL,
                     adf_p=p_lvl, adf_p_log=p_log,
                     n_bars=len(c), n_trades=n_trades_by_sym.get(s, 0)))

diag = pd.DataFrame(rows)
# Classification: MR if Hurst<0.45 OR adf_p<0.05 (use level ADF as primary per task)
diag["is_mr"] = ((diag["hurst"] < 0.45) | (diag["adf_p"] < 0.05))
# also a stricter variant using either ADF
diag["is_mr_either_adf"] = ((diag["hurst"] < 0.45) |
                            (diag["adf_p"] < 0.05) | (diag["adf_p_log"] < 0.05))
diag.to_csv(f"{OUT}/mr_symbol_diagnostics.csv", index=False)

mr_syms = set(diag.loc[diag["is_mr"] == True, "symbol"])
trend_syms = set(diag.loc[(diag["is_mr"] == False) & diag["hurst"].notna(), "symbol"])
covered_set = set(covered_syms)

# ------------------------------------------------------------------ tag trades
def tag(sym):
    if sym in mr_syms: return "MR"
    if sym in trend_syms: return "TREND"
    if sym in covered_set: return "COVERED_UNCLASSIFIED"
    return "UNCOVERED"
t["mr_class"] = t["symbol"].map(tag)

def run_segment(df, label):
    seg = {}
    for cls in ["MR", "TREND", "COVERED_UNCLASSIFIED", "UNCOVERED"]:
        seg[cls] = stats_block(df[df["mr_class"] == cls])
    # bootstrap: MR net_exp absolute CI, and MR-TREND difference CI
    mr_net = df.loc[df["mr_class"] == "MR", "net_usdt"].values
    tr_net = df.loc[df["mr_class"] == "TREND", "net_usdt"].values
    seg["MR_net_exp_CI"] = boot_ci_mean(mr_net)
    seg["MR_minus_TREND_net_exp_CI"] = boot_ci_diff(mr_net, tr_net)
    seg["label"] = label
    return seg

overall = run_segment(t, "overall")
april = run_segment(t[t["signal_time"].dt.month == 4], "april")

# ------------------------------------------------------------------ coverage + summary numbers
coverage = dict(
    n_traded_symbols=len(traded),
    n_covered_symbols=len(covered_syms),
    n_classifiable_symbols=int(diag["hurst"].notna().sum()),
    n_mr_symbols=len(mr_syms),
    n_trend_symbols=len(trend_syms),
    n_trades_total=int(len(t)),
    n_trades_covered=int(t["symbol"].isin(covered_set).sum()),
    n_trades_MR=int((t["mr_class"] == "MR").sum()),
    n_trades_TREND=int((t["mr_class"] == "TREND").sum()),
    n_trades_uncovered=int((t["mr_class"] == "UNCOVERED").sum()),
    pct_trades_covered=float(t["symbol"].isin(covered_set).mean()),
    median_hurst=float(diag["hurst"].median()),
    median_adf_p=float(diag["adf_p"].median()),
)

result = dict(coverage=coverage, overall=overall, april=april)
with open(f"{OUT}/mr_filter_result.json", "w") as f:
    json.dump(result, f, indent=2, default=str)

# ------------------------------------------------------------------ print
def fmt_seg(seg, name):
    print(f"\n===== {name} =====")
    for cls in ["MR", "TREND", "COVERED_UNCLASSIFIED", "UNCOVERED"]:
        b = seg[cls]
        wr = "nan" if b["WR"] != b["WR"] else f"{100*b['WR']:.1f}%"
        ne = "nan" if b["net_exp"] != b["net_exp"] else f"{b['net_exp']:+.4f}"
        ge = "nan" if b["gross_exp"] != b["gross_exp"] else f"{b['gross_exp']:+.4f}"
        pf = "nan" if b["PF_net"] != b["PF_net"] else f"{b['PF_net']:.3f}"
        print(f"  {cls:22s} n={b['n']:5d}  WR={wr:>6s}  gross_exp={ge:>9s}  net_exp={ne:>9s}  PF_net={pf}")
    m, lo, hi = seg["MR_net_exp_CI"]
    print(f"  MR net_exp 95% boot CI:        mean={m:+.4f}  [{lo:+.4f}, {hi:+.4f}]  excludes0={not(lo<=0<=hi)}")
    d, dlo, dhi = seg["MR_minus_TREND_net_exp_CI"]
    print(f"  (MR-TREND) net_exp 95% boot CI: diff={d:+.4f}  [{dlo:+.4f}, {dhi:+.4f}]  excludes0={not(dlo<=0<=dhi)}")

print("COVERAGE:", json.dumps(coverage, indent=2))
fmt_seg(overall, "OVERALL")
fmt_seg(april, "APRIL-ONLY")

# distribution of classifiers
print("\nClassifier distribution (classifiable symbols):")
print("  Hurst<0.45 :", int((diag["hurst"] < 0.45).sum()))
print("  adf_p<0.05 :", int((diag["adf_p"] < 0.05).sum()))
print("  adf_p_log<0.05 :", int((diag["adf_p_log"] < 0.05).sum()))
print("  MR (Hurst<0.45 OR adf_p<0.05):", len(mr_syms))
print("  Hurst range:", f"{diag['hurst'].min():.3f}..{diag['hurst'].max():.3f}",
      "median", f"{diag['hurst'].median():.3f}")
