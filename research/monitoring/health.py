"""System-HEALTH monitor (shadow-only).

Turns the falsification metrics + input-distribution-shift indicators into a 3-state
health verdict and a reviewable per-cycle decision record. It NEVER flips live flags;
it only computes the state and the action it WOULD recommend.

States (driven by the primary null, Null A = random entries in the same universe):
    P_vs_random >= 0.95          -> HEALTHY   -> log_only
    0.80 <= P_vs_random < 0.95   -> DEGRADED  -> log_alert_freeze_learning
    P_vs_random < 0.80           -> CRITICAL  -> research_mode
Null A is MANDATORY: without it the verdict is UNKNOWN (never assume an edge).
Null B (bootstrap/permutation of actual trade returns) is a SECONDARY cross-check only.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence
import numpy as np

from research.falsification.random_null import p_strategy_gt_random, permutation_null
from research.falsification import metrics as M

# monitor flag thresholds (informational, not hard gates)
PSI_FLAG = 0.20
REGIME_TV_FLAG = 0.30
FREQ_FLAG = 0.50
CONF_DECAY_FLAG = -0.10


@dataclass
class MonitorWindow:
    returns: Sequence[float]
    timestamps: Optional[Sequence] = None
    regimes: Optional[Sequence] = None
    confidences: Optional[Sequence] = None
    features: Optional[np.ndarray] = None


# ---------------- state machine ----------------
def classify_state(p_vs_random):
    if p_vs_random is None or p_vs_random != p_vs_random:
        return ("UNKNOWN", "blocked_no_null_a")
    if p_vs_random >= 0.95:
        return ("HEALTHY", "log_only")
    if p_vs_random >= 0.80:
        return ("DEGRADED", "log_alert_freeze_learning")
    return ("CRITICAL", "research_mode")


def edge_status(p_random, p_bootstrap):
    if p_random is None or p_random < 0.95:
        return "not_proven"
    if p_bootstrap is not None and p_bootstrap >= 0.95:
        return "candidate"
    return "uncertain"


# ---------------- input-distribution-shift monitors ----------------
def psi(expected, actual, bins: int = 10) -> float:
    e = np.asarray(expected, float); a = np.asarray(actual, float)
    e = e[~np.isnan(e)]; a = a[~np.isnan(a)]
    if e.size < bins or a.size < bins:
        return float("nan")
    edges = np.quantile(e, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    e_pct = np.histogram(e, edges)[0] / e.size
    a_pct = np.histogram(a, edges)[0] / a.size
    eps = 1e-6
    e_pct = np.clip(e_pct, eps, None); a_pct = np.clip(a_pct, eps, None)
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def feature_distribution_shift(cur_features, ref_features) -> float:
    if cur_features is None or ref_features is None:
        return float("nan")
    cur = np.asarray(cur_features, float); ref = np.asarray(ref_features, float)
    if cur.ndim == 1:
        cur = cur[:, None]; ref = ref[:, None]
    vals = [psi(ref[:, j], cur[:, j]) for j in range(min(cur.shape[1], ref.shape[1]))]
    vals = [v for v in vals if v == v]
    return float(np.mean(vals)) if vals else float("nan")


def regime_tv_distance(cur_regimes, ref_regimes) -> float:
    if not cur_regimes or not ref_regimes:
        return float("nan")
    labels = set(cur_regimes) | set(ref_regimes)
    cur = {k: 0 for k in labels}; ref = {k: 0 for k in labels}
    for r in cur_regimes:
        cur[r] += 1
    for r in ref_regimes:
        ref[r] += 1
    nc, nr = len(cur_regimes), len(ref_regimes)
    return float(0.5 * sum(abs(cur[k] / nc - ref[k] / nr) for k in labels))


def signal_frequency_change(cur_ts, ref_ts) -> float:
    def freq(ts):
        ts = np.asarray(ts, float)
        span = ts.max() - ts.min()
        return ts.size / span if span > 0 else float("nan")
    fc, fr = freq(cur_ts), freq(ref_ts)
    if fr is None or fr != fr or fr == 0:
        return float("nan")
    return float((fc - fr) / fr)


def confidence_decay(cur_conf, ref_conf) -> float:
    if cur_conf is None or ref_conf is None or len(cur_conf) == 0 or len(ref_conf) == 0:
        return float("nan")
    mc, mr = float(np.mean(cur_conf)), float(np.mean(ref_conf))
    return float((mc - mr) / abs(mr)) if mr != 0 else float("nan")


def _dominant(labels):
    if not labels:
        return None
    vals, counts = np.unique(np.asarray(labels), return_counts=True)
    return str(vals[int(np.argmax(counts))])


# ---------------- end-to-end evaluation ----------------
def evaluate(current: MonitorWindow, reference: MonitorWindow,
             null_a_returns=None, p_threshold: float = 0.95,
             n_boot: int = 10000, now: Optional[str] = None) -> dict:
    r = np.asarray(current.returns, float)
    ts = now or datetime.now(timezone.utc).isoformat()

    # input-distribution-shift monitors (computed regardless of null)
    monitors = {
        "signal_frequency_change": signal_frequency_change(current.timestamps, reference.timestamps)
        if current.timestamps is not None and reference.timestamps is not None else float("nan"),
        "market_regime_shift": regime_tv_distance(current.regimes, reference.regimes)
        if current.regimes and reference.regimes else float("nan"),
        "feature_distribution_shift": feature_distribution_shift(current.features, reference.features),
        "confidence_decay": confidence_decay(current.confidences, reference.confidences),
    }
    warnings = []
    if monitors["feature_distribution_shift"] == monitors["feature_distribution_shift"] and \
            monitors["feature_distribution_shift"] > PSI_FLAG:
        warnings.append("feature_distribution_shift")
    if monitors["market_regime_shift"] == monitors["market_regime_shift"] and \
            monitors["market_regime_shift"] > REGIME_TV_FLAG:
        warnings.append("market_regime_shift")
    if monitors["signal_frequency_change"] == monitors["signal_frequency_change"] and \
            abs(monitors["signal_frequency_change"]) > FREQ_FLAG:
        warnings.append("signal_frequency_change")
    if monitors["confidence_decay"] == monitors["confidence_decay"] and \
            monitors["confidence_decay"] < CONF_DECAY_FLAG:
        warnings.append("confidence_decay")

    # dual null
    if null_a_returns is None:
        p_random = None
        cohens = None
        mean_excess = None
    else:
        p_random = p_strategy_gt_random(r, null_a_returns, n_boot=n_boot)
        cohens = M.cohens_d(r, null_a_returns)
        mean_excess = float(r.mean() - np.asarray(null_a_returns, float).mean())
    p_bootstrap = permutation_null(r, n_boot=n_boot) if r.size else None

    state, action = classify_state(p_random)
    edge = edge_status(p_random, p_bootstrap)

    reason_bits = [f"state={state}", f"edge={edge}"]
    if null_a_returns is None:
        reason_bits.append("null_a missing (mandatory primary null not provided)")
    if warnings:
        reason_bits.append("health_warnings=" + ",".join(warnings))

    return {
        "timestamp": ts,
        "market_regime": _dominant(current.regimes),
        "n_trades": int(r.size),
        "P_strategy_gt_random": p_random,
        "P_strategy_gt_bootstrap": p_bootstrap,
        "Sharpe": M.sharpe(r),
        "PF": M.profit_factor(r),
        # IR needs a real market benchmark (not the strategy's own past window); wired later.
        "InformationRatio": None,
        "CohensD": cohens,
        "mean_excess": mean_excess,
        "edge_status": edge,
        "state": state,
        "recommended_action": action,
        "monitors": monitors,
        "health_warnings": warnings,
        "reason": " | ".join(reason_bits),
    }
