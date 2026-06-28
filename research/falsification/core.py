"""Unified falsification interface.

    result = validate(StrategyData(returns=..., null_returns=...))

returns a reviewable verdict (NOT a bare pass/fail):

    {
      "pass": bool,
      "metrics": {P_strategy_gt_random, Sharpe, PF, InformationRatio, CohensD, ...},
      "failure_reasons": [...],
      "recommendation": [...],
    }

Philosophy: assume NO alpha. `pass` is True only when an external random-entry null is
beaten with P>threshold, the excess-over-null CI excludes zero, returns are not
concentrated (remove-best survives), information ratio is not negative, and the result
holds out-of-sample. Anything else stays in shadow mode with explicit reasons.
"""
from dataclasses import dataclass, field
from typing import Optional, Sequence
import numpy as np

from . import metrics as M
from .random_null import p_strategy_gt_random
from .bootstrap import mean_ci, excess_ci, crosses_zero
from .remove_best import remove_best_report
from .monte_carlo import monte_carlo
from .walk_forward import walk_forward
from .oos import oos_holdout


@dataclass
class StrategyData:
    returns: Sequence[float]                       # per-trade net returns (required)
    null_returns: Optional[Sequence[float]] = None # pool of random-entry returns (the null)
    timestamps: Optional[Sequence] = None          # for OOS / walk-forward ordering
    benchmark_returns: Optional[Sequence[float]] = None  # aligned per-trade benchmark (IR)
    periods_per_year: float = 365.0
    n_strategies_tested: int = 1                    # for multiple-testing context


def validate(data: StrategyData, p_threshold: float = 0.95, n_boot: int = 10000,
             min_trades: int = 30) -> dict:
    r = np.asarray(data.returns, float)
    reasons: list = []
    rec: list = []
    ppy = data.periods_per_year

    metrics = {
        "n_trades": int(r.size),
        "P_strategy_gt_random": None,
        "Sharpe": M.sharpe(r, ppy),
        "PF": M.profit_factor(r),
        "InformationRatio": None,
        "CohensD": None,
        "mean_return": float(r.mean()) if r.size else float("nan"),
        "mean_excess": None,
    }

    # ---- sample-size gate ----
    if r.size < min_trades:
        reasons.append(f"insufficient sample (n={r.size} < {min_trades})")
        rec.append("collect_more_trades")

    # ---- random-entry null (the core edge test) ----
    if data.null_returns is None:
        reasons.append("no external random-entry null provided")
        rec.append("provide_random_entry_null")
    else:
        P = p_strategy_gt_random(r, data.null_returns, n_boot=n_boot)
        metrics["P_strategy_gt_random"] = P
        metrics["CohensD"] = M.cohens_d(r, data.null_returns)
        eci = excess_ci(r, data.null_returns, n=n_boot)
        metrics["mean_excess"] = float(np.mean(r) - np.mean(np.asarray(data.null_returns, float)))
        metrics["excess_CI"] = eci
        if not (P > p_threshold):
            reasons.append(f"random null failed (P={P:.3f} <= {p_threshold})")
        if crosses_zero(eci):
            reasons.append("excess-over-random CI crosses zero")

    # ---- bootstrap CI of mean trade return ----
    mci = mean_ci(r, n=n_boot)
    metrics["mean_CI"] = mci
    if crosses_zero(mci):
        reasons.append("bootstrap mean CI crosses zero")

    # ---- information ratio (needs a benchmark) ----
    if data.benchmark_returns is not None:
        ir = M.information_ratio(r, data.benchmark_returns, ppy)
        metrics["InformationRatio"] = ir
        if ir == ir and ir < 0:                    # not nan and negative
            reasons.append("information ratio negative")

    # ---- remove-best-trade concentration ----
    rb = remove_best_report(r)
    metrics["remove_best"] = rb
    if rb["collapses"]:
        reasons.append("returns concentrated (remove-best collapses)")

    # ---- out-of-sample consistency ----
    oos = oos_holdout(r, data.timestamps)
    metrics["oos"] = oos
    if oos["evaluable"] and not oos["consistent"]:
        reasons.append("out-of-sample inconsistent (edge does not hold OOS)")

    # ---- walk-forward & monte-carlo (reported, not hard gates) ----
    metrics["walk_forward"] = walk_forward(r, data.timestamps)
    metrics["monte_carlo"] = monte_carlo(r, n=min(n_boot, 10000))

    # ---- verdict ----
    passed = (data.null_returns is not None) and (len(reasons) == 0)
    if passed:
        rec = ["promote_to_shadow_then_gate"]      # never straight to live
    else:
        if "keep_shadow_mode" not in rec:
            rec.insert(0, "keep_shadow_mode")

    return {
        "pass": bool(passed),
        "metrics": metrics,
        "failure_reasons": reasons,
        "recommendation": rec,
    }
