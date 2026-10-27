"""x1-pwr-sim-v1: synthetic, deterministic tests for research/power_sim (no data, database, network or production).

SYNTHETIC ENGINEERING VALIDATION ONLY. Every series is generated in the test from stated parameters. The tests check
that the vectorized statistics reproduce the research/stats conventions, that the simulated single-look rule has
the expected size and power behaviour, and that the package does no I/O. They say nothing about any market."""
import ast
import math
import pathlib
import sys
from dataclasses import replace

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.power_sim import x1_single_look as X  # noqa: E402
from research.stats import inference as I  # noqa: E402
from research.stats import sharpe_deflation as S  # noqa: E402

PKG = ROOT / "research" / "power_sim"
D = X.Design()


def _series(seed, n=600, mu=0.0004, sd=0.02, df=4):
    rng = np.random.default_rng(seed)
    return mu + sd * rng.standard_t(df, n) / math.sqrt(df / (df - 2))


# --- conventions shared with research/stats -----------------------------------------------------------------------

def test_hac_t_matches_research_stats_inference():
    x = _series(1)
    assert X.hac_t(x[None, :], 7)[0] == pytest.approx(I.hac_t(list(x), 7), rel=1e-10)
    assert X.hac_t(x[None, :], 0)[0] == pytest.approx(I.hac_t(list(x), 0), rel=1e-10)


def test_dsr_matches_research_stats_sharpe_deflation():
    x = _series(2)
    sr, sk, ku = (v[0] for v in X.moments(x[None, :]))
    m = S.sample_moments(list(x))
    assert (sr, sk, ku) == pytest.approx((m.sr, m.skew, m.kurtosis), rel=1e-10)
    for n_trials, var in ((1, 0.0), (3, 1.0 / len(x)), (10000, 1.0 / len(x))):
        ref = S.deflated_sharpe_ratio(m.sr, len(x), n_trials, var, m.skew, m.kurtosis).dsr
        got = X.dsr(np.array([sr]), np.array([sk]), np.array([ku]), len(x), n_trials, np.array([var]))[0]
        assert got == pytest.approx(ref, abs=1e-9)


def test_block_bootstrap_lower_bound_agrees_with_research_stats_bootstrap():
    x = _series(3, n=400, mu=0.001)
    ref = I.stationary_bootstrap_ci(list(x), "mean", mean_block=20, n_resamples=4000, seed=7).lower
    got = X.boot_lower(x[None, :], replace(D, n_boot=4000), np.random.default_rng(7))[0]
    se = float(np.std(x, ddof=1)) / math.sqrt(len(x))
    assert abs(got - ref) < 0.25 * se


def test_cost_rates_follow_s4_mech_v1_and_never_stress_the_fee():
    base, stress = X.cost_rates(D)
    assert base == pytest.approx(0.001 + 0.1 * (0.0001 + 0.0005) + 0.9 * (0.0004 + 0.0005))
    assert stress == pytest.approx(0.001 + 0.1 * (0.0002 + 0.0010) + 0.9 * (0.0008 + 0.0010))
    fee_only = replace(D, half_spread_major=0.0, half_spread_other=0.0, slippage=0.0)
    assert X.cost_rates(fee_only) == pytest.approx((0.001, 0.001))


def test_window_lengths_are_the_inclusive_utc_day_counts():
    import datetime as dt
    for start, end, n in X.WINDOWS.values():
        assert (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1 == n
    assert (dt.date(2023, 1, 1) - dt.date(2019, 1, 1)).days == X.SPLIT_2019_2022_DAYS


# --- helpers on hand-built paths -----------------------------------------------------------------------------------

def test_max_drawdown_and_top5_share_on_hand_built_paths():
    r = np.array([[0.10, -0.50, 0.20, 0.0]])
    assert X.max_drawdown(r)[0] == pytest.approx(0.5)
    n = 365
    flat = np.full((1, n), 0.001)
    assert X.top5_share(flat)[0] == pytest.approx(5 * 30.44 / n, abs=0.02)
    assert X.top5_share(-flat)[0] == math.inf


def test_delisting_sr_shift_arithmetic():
    assert X.delisting_sr_shift(2.0, 0.25, 0.05, 1.0, 0.40) == pytest.approx(0.75 * 0.05 * 2.0 / 0.40)
    assert X.delisting_sr_shift(2.0, 1.0, 0.05, 1.0, 0.40) == 0.0
    with pytest.raises(ValueError):
        X.delisting_sr_shift(2.0, 1.5, 0.05, 1.0, 0.40)


# --- simulated rule behaviour --------------------------------------------------------------------------------------

def test_same_seed_same_result():
    a = X.simulate_cell("a_2023_2026", X.TAILS[1], 1.0, D, 50, 11)
    b = X.simulate_cell("a_2023_2026", X.TAILS[1], 1.0, D, 50, 11)
    assert a == b


def test_size_at_true_sharpe_zero_is_at_most_nominal():
    r = X.simulate_cell("a_2023_2026", X.TAILS[0], 0.0, D, 600, 21)
    # HAC t >= 2 is one-sided about 0.023 under normality; allow Monte Carlo and finite-sample slack
    assert r.c1_hac < 0.05
    assert r.core <= r.c1_hac and r.full <= r.core


def test_iid_normal_hac_condition_tracks_the_normal_reference():
    r = X.simulate_cell("a_2023_2026", X.TAILS[0], 1.0, D, 400, 22)
    assert r.normal_ref == pytest.approx(0.462, abs=0.005)
    assert abs(r.c1_hac - r.normal_ref) < 0.08


def test_power_rises_with_window_and_sharpe_and_falls_with_autocorrelation():
    a = X.simulate_cell("a_2023_2026", X.TAILS[0], 1.0, D, 200, 31)
    b = X.simulate_cell("b_2019_2026", X.TAILS[0], 1.0, D, 200, 31)
    b_hi = X.simulate_cell("b_2019_2026", X.TAILS[0], 1.5, D, 200, 31)
    b_ar = X.simulate_cell("b_2019_2026", X.Tails("ar", None, 0.3), 1.0, D, 200, 31)
    assert a.core < b.core < b_hi.core
    assert b_ar.c1_hac < b.c1_hac


def test_invalid_parameters_are_refused():
    with pytest.raises(ValueError):
        X.simulate_cell("a_2023_2026", X.Tails("bad", 2.0), 1.0, D, 5, 1)
    with pytest.raises(ValueError):
        X.simulate_cell("a_2023_2026", X.TAILS[0], 1.0, replace(D, trial_var_mode="other"), 5, 1)
    with pytest.raises(ValueError):
        X.simulate_cell("a_2023_2026", X.TAILS[0], 1.0, replace(D, concentration_on="coin"), 5, 1)
    with pytest.raises(ValueError):
        X.simulate_cell("a_2023_2026", X.TAILS[0], 1.0, replace(D, recency_guard=(5000, 0.0)), 5, 1)


def test_recency_guard_only_removes_passes():
    free = X.simulate_cell("b_2019_2026", X.TAILS[0], 1.0, D, 60, 41)
    loose = X.simulate_cell("b_2019_2026", X.TAILS[0], 1.0, replace(D, recency_guard=(1326, -1e9)), 60, 41)
    tight = X.simulate_cell("b_2019_2026", X.TAILS[0], 1.0, replace(D, recency_guard=(1326, 1.0)), 60, 41)
    assert loose.core == free.core and tight.core <= free.core and tight.full <= free.full


# --- package hygiene -----------------------------------------------------------------------------------------------

ALLOWED = {"__future__", "argparse", "dataclasses", "json", "math", "statistics", "sys", "numpy",
           "research.mechanisms.costs"}


def test_package_imports_only_the_allowlist_and_does_no_io():
    for p in PKG.glob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(a.name in ALLOWED for a in node.names), p.name
            elif isinstance(node, ast.ImportFrom):
                assert node.module in ALLOWED, (p.name, node.module)
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("open", "eval", "exec"):
                pytest.fail(f"{p.name}: {node.func.id}()")
            elif isinstance(node, ast.Attribute) and node.attr in ("load", "loadtxt", "fromfile", "read_csv",
                                                                     "read_pickle", "genfromtxt"):
                pytest.fail(f"{p.name}: .{node.attr}")


def test_no_production_module_imports_the_package():
    for d in ("analyzer", "signal_engine", "trade_tracker", "telegram", "scanner", "shared"):
        for p in (ROOT / d).rglob("*.py"):
            assert "power_sim" not in p.read_text(encoding="utf-8", errors="ignore"), p


def test_cli_prints_a_labelled_table(capsys, monkeypatch):
    monkeypatch.setattr(X, "TAILS", X.TAILS[:1])
    monkeypatch.setattr(X, "SR_GRID", (0.0, 1.0))
    assert X.main(["--reps", "4", "--seed", "3"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{X.VERSION} SYNTHETIC reps=4 seed=3")
    assert "a_2023_2026 | normal_iid" in out and "dsr_null_N10000_A19" in out
