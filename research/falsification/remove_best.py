"""Remove-best-trade test — detects returns concentrated in a few lucky trades."""
import numpy as np
from .metrics import profit_factor


def remove_best_pf(returns, k: int = 5) -> float:
    r = np.asarray(returns, float)
    if r.size <= k:
        return float("nan")
    order = np.argsort(r)[::-1]
    mask = np.ones(r.size, bool)
    mask[order[:k]] = False
    return profit_factor(r[mask])


def remove_best_report(returns) -> dict:
    r = np.asarray(returns, float)
    full = profit_factor(r)
    out = {"pf_full": full,
           "pf_drop1": remove_best_pf(r, 1),
           "pf_drop5": remove_best_pf(r, 5),
           "pf_drop10": remove_best_pf(r, 10)}
    # collapse = was profitable, but drops below break-even once a few winners removed
    drop5 = out["pf_drop5"]
    out["collapses"] = bool(full >= 1.0 and (drop5 != drop5 or drop5 < 1.0))
    return out
