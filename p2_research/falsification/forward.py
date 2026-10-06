"""P2-F0 forward-survival rules (``contracts/f0_forward_v1.json``): length, harm monitoring, final verdict.

A forward test is a ONE-SHOT confirmation of a frozen candidate on data no in-sample evaluation has read. It is
registered before its first day (``forward_registration``: candidate hash, first day, planned days, set size), monitored
weekly ONLY for harm (early stop when the edge is significantly NEGATIVE, O'Brien-Fleming-type spending), and judged
for efficacy exactly once, at the planned end. There is no early success.
"""
from __future__ import annotations

import math

from . import stats as S

FWD_ORDER = ("FORWARD_REJECTED", "FORWARD_INSUFFICIENT", "FORWARD_DECAYED", "FORWARD_CONSISTENT")


class ForwardError(ValueError):
    pass


def forward_length(is_alpha_series, fwd: dict, lag: int):
    """Planned forward length in eligible days from the IN-SAMPLE net-alpha day series (frozen formula):
    n = ceil(((z_{1-alpha} + z_{power}) * sd / (haircut * mean))^2 * deff), clamped to [min_days, max_days];
    ``feasible`` is False when the unclamped n exceeds max_days (the edge is too small to confirm in time)."""
    x = list(is_alpha_series)
    m = S.mean(x)
    if m <= 0:
        raise ForwardError("a non-positive in-sample mean has nothing to confirm")
    sd = S.sd(x)
    deff = len(x) / S.n_eff(x, lag)
    za, zb = S.norm_ppf(1 - fwd["alpha"]), S.norm_ppf(fwd["power"])
    raw = ((za + zb) * sd / (fwd["haircut"] * m)) ** 2 * deff
    n = math.ceil(raw)
    return {"n_days": int(min(max(n, fwd["min_days"]), fwd["max_days"])), "n_raw": raw,
            "feasible": raw <= fwd["max_days"], "haircut_mean": fwd["haircut"] * m, "sd": sd, "deff": deff}


def harm_looks(n_days: int, every: int):
    """Look schedule (cumulative active-day counts) and the information fractions."""
    looks = list(range(every, n_days, every)) + [n_days]
    return looks, [k / n_days for k in looks]


def harm_check(series_so_far, n_planned: int, fwd: dict, lag: int, block: float, reps: int, seed: int):
    """At an interim look: stop for HARM when the one-sided p of mean < 0 is below this look's OBF increment.
    Uses the same conservative core test on the negated series. Never stops for success."""
    looks, fracs = harm_looks(n_planned, fwd["look_every_days"])
    k = len(series_so_far)
    if k < 3:
        return {"stop": False, "reason": "fewer than 3 days"}
    inc = S.obf_increments(fwd["harm_alpha"], fracs)
    j = max([i for i, lk in enumerate(looks) if lk <= k], default=None)
    if j is None:
        return {"stop": False, "reason": "before the first look"}
    neg = [-v for v in series_so_far]
    p = S.core_test(neg, block, lag, reps, seed)["p"]
    return {"stop": p <= inc[j], "p_harm": p, "level": inc[j], "look": j + 1, "looks": len(looks)}


def forward_verdict(fwd_battery_record: dict, is_mean: float, fwd: dict, harm_stopped: bool = False) -> dict:
    """Map the battery verdict on the FORWARD window (window.kind = forward) to the forward taxonomy.
      FORWARD_REJECTED     harm stop, or the forward battery says REJECTED / INVALID_EVIDENCE
      FORWARD_INSUFFICIENT INSUFFICIENT_EVIDENCE (min n or null not rejected) or FRAGILE
      FORWARD_DECAYED      local pass, but the forward mean < decay_min_ratio x the in-sample mean
      FORWARD_CONSISTENT   local pass and no decay: survived ONE pre-registered forward test (not proof)
    "Local pass" = forward battery verdict FORWARD_CONFIRMATION_REQUIRED or PROVISIONAL (no invalid, reject, fragile
    or insufficient effect: S01 Holm across the set passed); ``strict`` = PROVISIONAL-level."""
    v = fwd_battery_record["verdict"]
    if fwd_battery_record.get("window", {}).get("kind") != "forward":
        raise ForwardError("not a forward-window battery record")
    core = (fwd_battery_record.get("info") or {}).get("core")
    fm = core.get("mean") if core else ((fwd_battery_record.get("info") or {}).get("alpha") or {}).get("alpha")
    out = {"in_sample_mean": is_mean, "forward_mean": fm, "battery_verdict": v}
    if harm_stopped or v in ("REJECTED", "INVALID_EVIDENCE"):
        out["verdict"] = "FORWARD_REJECTED"
    elif v in ("INSUFFICIENT_EVIDENCE", "FRAGILE"):
        out["verdict"] = "FORWARD_INSUFFICIENT"
    else:
        ratio = fm / is_mean if (fm is not None and is_mean and is_mean > 0) else None
        out["decay_ratio"] = ratio
        out["strict"] = v == "PROVISIONAL"            # every deterministic robustness rule also held on the forward window
        out["verdict"] = "FORWARD_DECAYED" if ratio is None or ratio < fwd["decay_min_ratio"] else \
            "FORWARD_CONSISTENT"
    return out
