"""Out-of-sample holdout: hold out the most recent `frac` of trades, compare to
the in-sample remainder. Inconsistency = the strategy looked good in-sample but the
sign of the mean flips (or PF drops below break-even) out-of-sample.
"""
import numpy as np
from .metrics import profit_factor


def oos_holdout(returns, timestamps=None, frac: float = 0.3) -> dict:
    r = np.asarray(returns, float)
    if timestamps is not None:
        r = r[np.argsort(np.asarray(timestamps))]
    n = r.size
    if n < 10:
        return {"is_pf": float("nan"), "oos_pf": float("nan"),
                "is_mean": float("nan"), "oos_mean": float("nan"),
                "consistent": False, "evaluable": False}
    cut = int(round(n * (1 - frac)))
    is_r, oos_r = r[:cut], r[cut:]
    is_mean, oos_mean = float(is_r.mean()), float(oos_r.mean())
    is_pf, oos_pf = profit_factor(is_r), profit_factor(oos_r)
    # consistent if in-sample edge (mean>0) is NOT contradicted out-of-sample
    consistent = not (is_mean > 0 and oos_mean <= 0)
    return {"is_pf": is_pf, "oos_pf": oos_pf, "is_mean": is_mean,
            "oos_mean": oos_mean, "consistent": bool(consistent), "evaluable": True}
