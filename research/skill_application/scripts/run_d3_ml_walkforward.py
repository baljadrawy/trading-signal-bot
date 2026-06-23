#!/usr/bin/env python3
"""
TASK D3 — Purged/embargoed expanding-window walk-forward ML.

Question: is there LEARNABLE, fee-surviving edge in the existing st_* features?

Design (falsification-first):
  - Order trades by exit_time (the moment the label becomes known).
  - Expanding-window walk-forward, >=5 folds.
  - PURGE: drop any TRAIN trade whose label window [signal_time, exit_time] overlaps any
    TEST trade's window  (a trade's outcome can leak if its life overlaps a test trade's life).
  - EMBARGO: additionally drop train trades whose exit_time is within EMBARGO_H hours of the
    test fold's first signal_time (max label life = 48h -> embargo 48h).
  - Features = all st_* (drop constant st_btc_trend) + score + st_tf_conf + one-hot(market_condition, timeframe).
  - Models: XGBoost AND LogisticRegression (standardized).
  - Label = win (1/0).
  - Threshold tuned ONLY on TRAIN out-of-fold preds (maximize TRAIN net expectancy), applied to TEST.
  - Report: per-fold OOS AUC, overall pooled OOS AUC, Brier, and the NET expectancy / PF_net /
    fraction-taken of the threshold strategy on pooled OOS.
  - Permutation/shuffled-label control to gauge how much pooled AUC is luck.
  - promising=true ONLY if OOS AUC>0.55 AND OOS net_exp>0.
"""
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, brier_score_loss
import lib

OUT = "/home/tradmin/trading-signal-bot/research/skill_application/out"
EMBARGO_H = 48.0      # max label life in this dataset
N_FOLDS = 6           # expanding folds (test = each of folds 2..6 of a 6-way time split)
RNG = 42

np.random.seed(RNG)

# ----------------------------------------------------------------- load & features
df = lib.load_trades().sort_values("exit_time").reset_index(drop=True)

st_cols = [c for c in df.columns if c.startswith("st_")]
# drop constant features
const_cols = [c for c in st_cols if df[c].nunique() <= 1]
st_use = [c for c in st_cols if c not in const_cols]

base_num = st_use + ["score"]   # st_tf_conf already in st_use
# one-hot market_condition + timeframe
oh = pd.get_dummies(df[["market_condition", "timeframe"]].astype(str), prefix=["mc", "tf"])
X = pd.concat([df[base_num].astype(float), oh.astype(float)], axis=1).reset_index(drop=True)
feat_names = list(X.columns)

y = df["win"].values.astype(int)
net = df["net_usdt"].values.astype(float)
sig_t = df["signal_time"].values.astype("datetime64[ns]")
exi_t = df["exit_time"].values.astype("datetime64[ns]")

n = len(df)
print(f"n={n}  features={len(feat_names)}  dropped_constant={const_cols}")
print(f"WR={y.mean():.4f}  net_exp_all={net.mean():.4f}  PF_net_all={lib.pf(net):.3f}")

# ----------------------------------------------------------------- model factory
def make_xgb():
    from xgboost import XGBClassifier
    return XGBClassifier(
        n_estimators=200, max_depth=3, learning_rate=0.04,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=8, gamma=0.2,
        reg_lambda=2.0, eval_metric="logloss", random_state=RNG, n_jobs=4, verbosity=0,
    )

# ----------------------------------------------------------------- purge+embargo helpers
def purge_embargo_train(train_idx, test_idx):
    """Remove train rows whose label window overlaps any test window, or whose exit is
    within EMBARGO_H of the test fold start (and any train row that simply postdates test start)."""
    test_start = sig_t[test_idx].min()
    # embargo cutoff: train must have FULLY resolved >= EMBARGO_H before test fold opens
    embargo_cut = test_start - np.timedelta64(int(EMBARGO_H * 3600), "s")
    keep = []
    ts_starts = sig_t[test_idx]
    ts_ends = exi_t[test_idx]
    tmin = ts_starts.min()
    tmax = ts_ends.max()
    for i in train_idx:
        s_i, e_i = sig_t[i], exi_t[i]
        # hard temporal: train must end before test fold opens
        if e_i >= test_start:
            continue
        # embargo: exit must be at least EMBARGO_H before test start
        if e_i > embargo_cut:
            continue
        # purge: drop if window overlaps test span at all (defensive; embargo already covers most)
        if (s_i <= tmax) and (e_i >= tmin):
            continue
        keep.append(i)
    return np.array(keep, dtype=int)

# expanding folds on time order: split into N_FOLDS contiguous blocks; test = block k (k>=1),
# train pool = everything before block k, then purged+embargoed.
bounds = [int(round(n * k / N_FOLDS)) for k in range(N_FOLDS + 1)]
folds = []
for k in range(1, N_FOLDS):
    train_pool = np.arange(0, bounds[k])
    test = np.arange(bounds[k], bounds[k + 1])
    folds.append((train_pool, test))

# ----------------------------------------------------------------- threshold tuned on TRAIN
def tune_threshold_train(p_train, net_train, grid):
    """Pick threshold maximizing TRAIN net expectancy; require >=15 train signals."""
    best_t, best_exp = None, -1e9
    for t in grid:
        m = p_train >= t
        k = int(m.sum())
        if k < 15:
            continue
        e = net_train[m].mean()
        if e > best_exp:
            best_exp, best_t = e, float(t)
    if best_t is None:           # fallback: loosest threshold that yields >=15
        best_t = float(np.quantile(p_train, max(0.0, 1 - 15.0 / len(p_train))))
    return best_t

GRID = np.round(np.arange(0.30, 0.75, 0.01), 2)

# ----------------------------------------------------------------- run one model
def run_model(name, fit_predict):
    fold_rows = []
    pooled_p, pooled_y, pooled_net = [], [], []
    taken_net, taken_y = [], []           # threshold-strategy OOS trades
    importances = np.zeros(len(feat_names))
    imp_folds = 0
    for fi, (train_pool, test) in enumerate(folds, 1):
        train = purge_embargo_train(train_pool, test)
        if len(train) < 60 or len(np.unique(y[train])) < 2:
            fold_rows.append({"fold": fi, "n_train": int(len(train)), "n_test": int(len(test)),
                              "auc": None, "skipped": True})
            continue
        Xtr, ytr = X.iloc[train].values, y[train]
        Xte, yte = X.iloc[test].values, y[test]
        net_te = net[test]
        # in-fold train preds (for threshold tuning) via 3-fold internal CV on train
        from sklearn.model_selection import StratifiedKFold
        p_tr = np.full(len(train), np.nan)
        skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=RNG)
        for a, b in skf.split(Xtr, ytr):
            p_tr[b] = fit_predict(Xtr[a], ytr[a], Xtr[b], return_imp=False)
        # final fit on full train -> test preds + importance
        p_te, imp = fit_predict(Xtr, ytr, Xte, return_imp=True)
        if imp is not None:
            importances += imp
            imp_folds += 1
        # AUC on test
        try:
            auc = roc_auc_score(yte, p_te)
        except ValueError:
            auc = None
        # threshold tuned on TRAIN preds, applied to TEST
        thr = tune_threshold_train(p_tr, net[train], GRID)
        sel = p_te >= thr
        sel_net = net_te[sel]
        sel_y = yte[sel]
        fold_rows.append({
            "fold": fi, "n_train": int(len(train)), "n_test": int(len(test)),
            "auc": (None if auc is None else round(float(auc), 4)),
            "thr": round(thr, 3), "n_taken": int(sel.sum()),
            "taken_net_exp": (None if sel.sum() == 0 else round(float(sel_net.mean()), 4)),
            "taken_wr": (None if sel.sum() == 0 else round(float(sel_y.mean()), 4)),
            "skipped": False,
        })
        pooled_p.extend(p_te.tolist()); pooled_y.extend(yte.tolist()); pooled_net.extend(net_te.tolist())
        taken_net.extend(sel_net.tolist()); taken_y.extend(sel_y.tolist())

    pooled_p = np.array(pooled_p); pooled_y = np.array(pooled_y); pooled_net = np.array(pooled_net)
    taken_net = np.array(taken_net); taken_y = np.array(taken_y)

    pooled_auc = float(roc_auc_score(pooled_y, pooled_p)) if len(np.unique(pooled_y)) > 1 else None
    brier = float(brier_score_loss(pooled_y, pooled_p)) if len(pooled_y) else None
    fold_aucs = [r["auc"] for r in fold_rows if r.get("auc") is not None]
    mean_fold_auc = float(np.mean(fold_aucs)) if fold_aucs else None

    # threshold-strategy OOS aggregates
    if len(taken_net):
        strat = {
            "n_taken": int(len(taken_net)),
            "frac_taken": round(len(taken_net) / len(pooled_net), 4),
            "net_exp": round(float(taken_net.mean()), 4),
            "pf_net": round(lib.pf(taken_net), 3),
            "wr": round(float(taken_y.mean()), 4),
            "total_net": round(float(taken_net.sum()), 2),
        }
    else:
        strat = {"n_taken": 0, "frac_taken": 0.0, "net_exp": None, "pf_net": None, "wr": None, "total_net": 0.0}

    # feature importance (mean over folds)
    imp_rank = []
    if imp_folds:
        imp = importances / imp_folds
        order = np.argsort(imp)[::-1]
        imp_rank = [(feat_names[i], round(float(imp[i]), 4)) for i in order[:12]]

    return {
        "model": name,
        "mean_fold_auc": (None if mean_fold_auc is None else round(mean_fold_auc, 4)),
        "pooled_oos_auc": (None if pooled_auc is None else round(pooled_auc, 4)),
        "brier": (None if brier is None else round(brier, 4)),
        "n_pooled_oos": int(len(pooled_y)),
        "strategy": strat,
        "folds": fold_rows,
        "top_importance": imp_rank,
        "_pooled_p": pooled_p, "_pooled_y": pooled_y,
    }

# ---- XGBoost fit_predict
def xgb_fp(Xtr, ytr, Xte, return_imp=True):
    m = make_xgb()
    m.fit(Xtr, ytr)
    p = m.predict_proba(Xte)[:, 1]
    if return_imp:
        return p, m.feature_importances_
    return p

# ---- Logistic fit_predict (standardized)
def logit_fp(Xtr, ytr, Xte, return_imp=True):
    sc = StandardScaler().fit(Xtr)
    m = LogisticRegression(max_iter=2000, C=0.5, class_weight=None, random_state=RNG)
    m.fit(sc.transform(Xtr), ytr)
    p = m.predict_proba(sc.transform(Xte))[:, 1]
    if return_imp:
        return p, np.abs(m.coef_[0])
    return p

results = {}
for name, fp in [("xgboost", xgb_fp), ("logistic", logit_fp)]:
    print(f"\n=== {name} ===")
    r = run_model(name, fp)
    results[name] = r
    print(f"mean_fold_auc={r['mean_fold_auc']} pooled_oos_auc={r['pooled_oos_auc']} brier={r['brier']} n_oos={r['n_pooled_oos']}")
    print("strategy:", json.dumps(r["strategy"]))
    for fr in r["folds"]:
        print("  fold", fr)
    print("top importance:", r["top_importance"])

# ----------------------------------------------------------------- permutation control (XGB)
# Shuffle labels within the time order, re-run pooled OOS AUC many times -> null distribution.
def perm_null(fp, n_perm=200):
    global y
    real_y = y.copy()
    null_aucs = []
    for s in range(n_perm):
        yp = np.random.permutation(real_y)
        # quick: single expanding split using same folds, pooled auc
        pp, yy = [], []
        for train_pool, test in folds:
            tr = purge_embargo_train(train_pool, test)
            if len(tr) < 60 or len(np.unique(yp[tr])) < 2:
                continue
            p = fp(X.iloc[tr].values, yp[tr], X.iloc[test].values, return_imp=False)
            pp.extend(p.tolist()); yy.extend(yp[test].tolist())
        yy = np.array(yy); pp = np.array(pp)
        if len(np.unique(yy)) > 1:
            null_aucs.append(roc_auc_score(yy, pp))
    return np.array(null_aucs)

print("\n=== permutation null (logistic, faster) ===")
null = perm_null(logit_fp, n_perm=200)
real_auc = results["logistic"]["pooled_oos_auc"]
p_perm = float((np.sum(null >= real_auc) + 1) / (len(null) + 1)) if real_auc is not None else None
print(f"null AUC mean={null.mean():.4f} sd={null.std():.4f} 95pct={np.quantile(null,0.95):.4f}; real={real_auc} p_perm={p_perm}")

# ----------------------------------------------------------------- save & summarize
summary = {
    "n": n, "n_features": len(feat_names), "dropped_constant": const_cols,
    "WR_all": round(float(y.mean()), 4), "net_exp_all": round(float(net.mean()), 4),
    "PF_net_all": round(lib.pf(net), 3),
    "embargo_hours": EMBARGO_H, "n_folds_run": len(folds),
    "models": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in results.items()},
    "perm_null": {"mean": round(float(null.mean()), 4), "sd": round(float(null.std()), 4),
                  "q95": round(float(np.quantile(null, 0.95)), 4),
                  "real_logit_auc": real_auc, "p_perm": p_perm},
}
with open(f"{OUT}/d3_ml_walkforward.json", "w") as f:
    json.dump(summary, f, indent=2, default=str)

# ----------------------------------------------------------------- verdict
def promising_for(r):
    auc = r["pooled_oos_auc"]; ne = r["strategy"]["net_exp"]
    return (auc is not None and auc > 0.55) and (ne is not None and ne > 0)

prom = any(promising_for(results[m]) for m in results)
print("\n=== VERDICT ===")
print("promising:", prom)
print(json.dumps(summary["models"], indent=2, default=str))
