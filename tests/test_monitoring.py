"""Known-answer tests for the system-HEALTH monitor (research/monitoring).

PR#3 reframes monitoring from "profitability" to "system health":
- dual null: P_vs_random (Null A, mandatory) + P_vs_bootstrap (Null B, secondary)
- 3 states HEALTHY/DEGRADED/CRITICAL (no binary RESEARCH_MODE switch)
- input-distribution-shift monitors (strategies die at the input before PnL shows it)
- a reviewable per-cycle decision record
Shadow-only: the monitor COMPUTES state + recommended action; it never flips live flags.
"""
import sys; sys.path.insert(0, '.')
import numpy as np

from research.monitoring import evaluate, MonitorWindow
from research.monitoring.health import (
    classify_state, edge_status, psi, regime_tv_distance,
    signal_frequency_change, confidence_decay,
)


# ---------------- state machine ----------------
def test_state_thresholds():
    assert classify_state(0.97)[0] == "HEALTHY"
    assert classify_state(0.85)[0] == "DEGRADED"
    assert classify_state(0.50)[0] == "CRITICAL"


def test_state_actions():
    assert classify_state(0.99)[1] == "log_only"
    assert classify_state(0.88)[1] == "log_alert_freeze_learning"
    assert classify_state(0.40)[1] == "research_mode"


def test_edge_status_three_way():
    assert edge_status(0.99, 0.99) == "candidate"
    assert edge_status(0.90, 0.99) == "not_proven"      # primary null fails -> not proven
    assert edge_status(0.97, 0.80) == "uncertain"       # primary ok, secondary weak
    assert edge_status(0.50, 0.50) == "not_proven"


# ---------------- input-distribution-shift monitors ----------------
def test_psi_zero_for_identical_large_for_shifted():
    rng = np.random.default_rng(0)
    base = rng.normal(0, 1, 2000)
    assert psi(base, base.copy()) < 0.05
    shifted = rng.normal(2, 1, 2000)                    # mean shifted by 2 sd
    assert psi(base, shifted) > 0.25


def test_regime_tv_distance():
    a = ["bull"] * 8 + ["bear"] * 2
    assert regime_tv_distance(a, a) == 0.0
    b = ["bear"] * 8 + ["bull"] * 2
    assert regime_tv_distance(a, b) > 0.5


def test_signal_frequency_change():
    # same span, current has 2x the trades -> frequency +100%
    ref_ts = list(np.linspace(0, 9, 10))
    cur_ts = list(np.linspace(0, 9, 20))
    ch = signal_frequency_change(cur_ts, ref_ts)
    assert ch > 0.9


def test_confidence_decay_negative_when_dropping():
    ref = [0.8, 0.82, 0.79, 0.81]
    cur = [0.6, 0.58, 0.61, 0.59]
    assert confidence_decay(cur, ref) < 0


# ---------------- end-to-end decision record ----------------
def _win(mean, n, seed, regime="bull", conf=0.8):
    rng = np.random.default_rng(seed)
    return MonitorWindow(
        returns=rng.normal(mean, 0.02, n),
        timestamps=list(range(n)),
        regimes=[regime] * n,
        confidences=list(rng.normal(conf, 0.05, n)),
        features=rng.normal(0, 1, (n, 4)),
    )


def test_evaluate_record_shape_and_keys():
    cur = _win(0.0, 120, 1)
    ref = _win(0.0, 120, 2)
    null_a = np.random.default_rng(3).normal(0.0, 0.02, 5000)
    rec = evaluate(cur, ref, null_a_returns=null_a, now="2026-06-28T00:00:00Z")
    for k in ["timestamp", "market_regime", "n_trades", "P_strategy_gt_random",
              "P_strategy_gt_bootstrap", "Sharpe", "PF", "InformationRatio",
              "CohensD", "mean_excess", "edge_status", "state", "recommended_action",
              "reason", "monitors"]:
        assert k in rec, f"missing key {k}"
    assert set(rec["monitors"]) >= {"signal_frequency_change", "market_regime_shift",
                                    "feature_distribution_shift", "confidence_decay"}


def test_evaluate_no_edge_is_critical():
    cur = _win(0.0, 150, 10)
    ref = _win(0.0, 150, 11)
    null_a = np.random.default_rng(12).normal(0.0, 0.02, 6000)
    rec = evaluate(cur, ref, null_a_returns=null_a)
    assert rec["state"] == "CRITICAL"
    assert rec["edge_status"] == "not_proven"


def test_evaluate_missing_null_a_blocks_verdict():
    cur = _win(0.02, 120, 20)
    ref = _win(0.02, 120, 21)
    rec = evaluate(cur, ref, null_a_returns=None)
    assert rec["P_strategy_gt_random"] is None
    assert rec["state"] == "UNKNOWN"            # Null A is mandatory; no verdict without it
    assert "null_a" in rec["reason"].lower()
