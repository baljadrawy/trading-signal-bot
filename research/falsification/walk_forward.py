"""Walk-forward (time-ordered) stability of trade returns.

Splits chronologically ordered trades into K contiguous folds and reports per-fold
profit factor / mean, plus the fraction of folds that are profitable. No look-ahead:
folds preserve time order (caller passes returns already sorted by entry time, or
timestamps to sort by).
"""
import numpy as np
from .metrics import profit_factor


def walk_forward(returns, timestamps=None, k_folds: int = 5) -> dict:
    r = np.asarray(returns, float)
    if timestamps is not None:
        order = np.argsort(np.asarray(timestamps))
        r = r[order]
    if r.size < k_folds * 3:
        k_folds = max(2, r.size // 3)
    if r.size < 6:
        return {"n_folds": 0, "pos_fraction": float("nan"), "folds": []}
    folds = np.array_split(r, k_folds)
    rows = []
    for i, f in enumerate(folds):
        if f.size == 0:
            continue
        rows.append({"fold": i, "n": int(f.size),
                     "mean": float(f.mean()), "pf": profit_factor(f)})
    pos = np.mean([1.0 if x["mean"] > 0 else 0.0 for x in rows]) if rows else float("nan")
    return {"n_folds": len(rows), "pos_fraction": float(pos), "folds": rows}
