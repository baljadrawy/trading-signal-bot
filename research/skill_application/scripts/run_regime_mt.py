"""Multiple-testing + month-robustness check on the top 'positive' regime buckets."""
import warnings; warnings.filterwarnings("ignore")
import json, numpy as np, pandas as pd, lib

OUT = "/home/tradmin/trading-signal-bot/research/skill_application/out"
res = json.load(open(f"{OUT}/regime_results.json"))
allb = pd.DataFrame(res["all_buckets"])

# How many of 30 buckets are net_exp>0 with n>=30 vs expected under null?
n_pos = ((allb.net_exp > 0) & (allb.n >= 30)).sum()
n_big = (allb.n >= 30).sum()
print(f"buckets with n>=30: {n_big}; of those net_exp>0: {n_pos}")
print("best net_exp among n>=30:", allb[allb.n>=30].net_exp.max())

# one-sample t-test p-values per big bucket, Bonferroni over n_big tests
from scipy import stats
# rebuild the trade-level regime frame quickly by re-running regime mapping is heavy;
# instead reload saved per-bucket via recompute of the two key buckets from scratch is needed.
# We re-import the mapping logic by re-executing run_regime's classification on the fly:
import run_regime as rr  # reuses cached loaders; will re-run its main block

R = None
# rr executed its main at import; capture via re-deriving: simplest is to recompute frame.
# rr defines regime_at/get_ohlc/btc_regime; rebuild R here (fast, loaders cached).
df = lib.load_trades()
rows=[]
for _,row in df.iterrows():
    r = rr.regime_at(row["symbol"], row["signal_time"])
    if r is None: continue
    rows.append({"net":row["net_usdt"],"win":row["win"],
                 "vol_lab":"volHi" if r["vol_pct"]>=0.5 else "volLo",
                 "trend":r["trend"],"btc":rr.btc_regime(row["signal_time"]),
                 "month":pd.Timestamp(row["signal_time"]).strftime("%Y-%m")})
R=pd.DataFrame(rows)
R["quad"]=R.vol_lab+"_"+R.trend
R["cross"]=R["quad"]+"|btc_"+R.btc

def tt(x):
    x=np.asarray(x,float)
    if len(x)<3 or x.std()==0: return np.nan
    return stats.ttest_1samp(x,0).pvalue

print("\n--- top candidates: t-test (raw p) + Bonferroni threshold 0.05/%d=%.4f ---"%(n_big,0.05/max(n_big,1)))
for lab,mask in [("quad:volLo_flat", R.quad=="volLo_flat"),
                 ("cross:volHi_down|btc_down", R.cross=="volHi_down|btc_down"),
                 ("cross:volLo_down|btc_down", R.cross=="volLo_down|btc_down")]:
    sub=R[mask]
    p=tt(sub.net.values)
    print(f"  {lab:30s} n={len(sub):4d} net_exp={sub.net.mean():+.4f} raw_p={p:.4f} "
          f"{'PASS-Bonf' if (p is not np.nan and p<0.05/n_big) else 'fail-Bonf'}")

print("\n--- month robustness of top candidate volHi_down|btc_down ---")
sub=R[R.cross=="volHi_down|btc_down"]
mb=sub.groupby("month").agg(n=("net","size"),WR=("win","mean"),net_exp=("net","mean"),net_sum=("net","sum"))
mb["WR"]*=100
print(mb.to_string(float_format=lambda x:f"{x:.3f}"))

print("\n--- month robustness of volLo_flat ---")
sub2=R[R.quad=="volLo_flat"]
mb2=sub2.groupby("month").agg(n=("net","size"),WR=("win","mean"),net_exp=("net","mean"),net_sum=("net","sum"))
mb2["WR"]*=100
print(mb2.to_string(float_format=lambda x:f"{x:.3f}"))
