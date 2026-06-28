"""Mandatory distribution-match gate for Null-A.

The null is usable ONLY if its conditioning distribution matches the strategy's. If the
null is drawn from easier conditions (lower volatility, shorter holds, different regime
mix) it is biased/weaker → quality=FAILED and the null must NOT be used.
"""
import numpy as np
from .conditional_null import signal_profile


def _regime_tv(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    return float(0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys))


def null_quality(real, null, eps_vol: float = 0.10, eps_hold_rel: float = 0.25,
                 eps_regime: float = 0.20) -> dict:
    pr, pn = signal_profile(real), signal_profile(null)
    checks = {}

    vd = abs(pr["volatility_mean"] - pn["volatility_mean"])
    checks["volatility"] = {"diff": vd, "eps": eps_vol, "ok": bool(vd < eps_vol)} \
        if pr["volatility_mean"] == pr["volatility_mean"] else {"ok": True, "skipped": True}

    rm = pr["holding_period_mean"]
    hd = abs(rm - pn["holding_period_mean"])
    rel = hd / abs(rm) if rm not in (0, float("nan")) and rm == rm else float("inf")
    checks["holding_period"] = {"diff": hd, "rel": rel, "eps_rel": eps_hold_rel,
                                "ok": bool(rel < eps_hold_rel)} \
        if rm == rm else {"ok": True, "skipped": True}

    tv = _regime_tv(pr["regime_dist"], pn["regime_dist"])
    checks["regime"] = {"tv": tv, "eps": eps_regime, "ok": bool(tv < eps_regime)}

    passed = all(c.get("ok", False) for c in checks.values())
    return {"quality": "PASS" if passed else "FAILED",
            "checks": checks, "real_profile": pr, "null_profile": pn}
