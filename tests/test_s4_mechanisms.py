"""s4-mech-v1: synthetic, deterministic tests for research/mechanisms.

These prove accounting, timing and governance properties of the research tools. They use
generated prices only and say nothing about whether any mechanism earns money."""
import ast
import math
import pathlib
import random
import sys

import pytest

sys.path.insert(0, ".")
from research.mechanisms import costs as C  # noqa: E402
from research.mechanisms import signals as S  # noqa: E402
from research.mechanisms import simulate as M  # noqa: E402

PKG = pathlib.Path("research/mechanisms")


def gbm(n, mu, sigma, seed, p0=100.0):
    rng = random.Random(seed)
    px = [p0]
    for _ in range(n - 1):
        px.append(px[-1] * math.exp(mu - 0.5 * sigma ** 2 + sigma * rng.gauss(0, 1)))
    return px


def universe(n=300, k=6, seed=0):
    return {f"A{i}": gbm(n, 0.0005 * (i - k / 2), 0.03, seed * 100 + i) for i in range(k)}


def run(closes, rule, *, costs=C.BASELINE, start=60, allow_short=False):
    return M.run(closes, rule, costs=costs, permission=M.SYNTHETIC, start=start,
                 allow_short=allow_short)


TSM = S.TimeSeriesMomentum(lookback=20, long_only=True, vol_window=None, target_daily_vol=None)
XSM = S.CrossSectionalMomentum(lookback=20, top_k=2, long_only=True)


# --- costs --------------------------------------------------------------------------------------

def test_baseline_cost_is_ten_bps_per_side_and_twenty_round_trip():
    assert C.BASELINE.per_side == pytest.approx(0.001) and C.BASELINE.round_trip == pytest.approx(0.002)
    assert C.BASELINE.cost(2.0) == pytest.approx(0.002)            # full entry + full exit


def test_discounted_fee_is_refused_and_spread_slippage_are_separate():
    with pytest.raises(C.CostModelError, match="below the 0.10 % baseline"):
        C.CostModel(fee_per_side=0.00075)                           # BNB-discounted taker fee
    m = C.CostModel(half_spread=0.0005, slippage=0.0002, label="stress")
    assert m.fee_per_side == 0.001 and m.per_side == pytest.approx(0.0017)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.001, True, "0.001", None])
def test_invalid_cost_inputs_refused(bad):
    with pytest.raises(C.CostModelError):
        C.CostModel(half_spread=bad)


def test_tracker_flat_label_is_reported_separately():
    assert C.tracker_flat_cost(1) == pytest.approx(0.003)
    r = run(universe(), XSM)
    assert r.tracker_flat_cost_total == pytest.approx(r.total_turnover / 2 * 0.003)
    assert r.total_cost == pytest.approx(r.total_turnover * 0.001)


# --- accounting ---------------------------------------------------------------------------------

def test_cash_only_rule_has_zero_gross_cost_and_net():
    r = run(universe(), lambda past, t: {})
    assert r.days == 300 - 1 - 60 and set(r.gross) == {0.0} and r.total_cost == 0.0


def test_buy_and_hold_one_asset_trades_once_and_tracks_the_asset():
    px = {"A": gbm(200, 0.001, 0.02, 7), "B": gbm(200, 0.0, 0.02, 8)}
    r = run(px, lambda past, t: {"A": 1.0}, start=0)
    assert r.turnover[0] == pytest.approx(1.0) and max(r.turnover[1:]) < 1e-9
    assert r.cost[0] == pytest.approx(0.001)
    growth = math.prod(1 + g for g in r.gross)
    assert growth == pytest.approx(px["A"][-1] / px["A"][0], rel=1e-9)


def test_rebalancing_to_constant_weights_costs_only_the_drift():
    px = {"A": [100, 110, 99, 120], "B": [50, 50, 50, 50]}
    r = run(px, lambda past, t: {"A": 0.5, "B": 0.5}, start=0)
    # day 1: A +10 %, B flat -> drifted A = 0.55/1.05; trade back to 0.5 on both legs
    wa = 0.5 * 1.1 / 1.05
    assert r.turnover[1] == pytest.approx(abs(0.5 - wa) + abs(0.5 - (1 - wa)))
    assert r.net[1] == pytest.approx(r.gross[1] - r.cost[1])


def test_net_equals_gross_minus_cost_every_day():
    for rule in (TSM, XSM):
        r = run(universe(seed=3), rule)
        for g, c, n in zip(r.gross, r.cost, r.net):
            assert n == pytest.approx(g - c, abs=1e-15)


def test_higher_costs_never_increase_net():
    u = universe(seed=4)
    a = run(u, XSM)
    b = run(u, XSM, costs=C.CostModel(half_spread=0.0005, slippage=0.0005))
    assert a.gross == b.gross and all(y <= x + 1e-15 for x, y in zip(a.net, b.net))


# --- timing / look-ahead ------------------------------------------------------------------------

def test_rule_cannot_index_the_future():
    seen = []

    def peeking(past, t):
        seen.append(len(past["A0"]))
        with pytest.raises(IndexError):
            past["A0"][t + 1]
        assert past["A0"][-1] == past["A0"][t]
        return {}
    run(universe(n=100), peeking, start=10)
    assert seen == list(range(11, 100))


def test_changing_future_prices_never_changes_earlier_weights():
    u = universe(seed=5)
    v = {a: list(s) for a, s in u.items()}
    for a in v:                                     # perturb only the last 50 days
        for i in range(250, 300):
            v[a][i] *= 1.5 if a == "A0" else 0.7
    for rule in (TSM, XSM):
        ra, rb = run(u, rule), run(v, rule)
        k = 250 - 60 - 1                             # decisions made before day 250
        assert ra.turnover[:k] == rb.turnover[:k]


# --- signals ------------------------------------------------------------------------------------

def test_tsmom_sign_and_equal_risk_budget():
    past = {"UP": [100, 101, 103], "DN": [100, 99, 97], "FLAT": [100, 100, 100]}
    assert S.TimeSeriesMomentum(lookback=2, long_only=True, vol_window=None,
                                target_daily_vol=None)(past, 2) == {"UP": pytest.approx(1 / 3)}
    ls = S.TimeSeriesMomentum(lookback=2, long_only=False, vol_window=None, target_daily_vol=None)
    assert ls(past, 2) == {"UP": pytest.approx(1 / 3), "DN": pytest.approx(-1 / 3)}


def test_tsmom_vol_scaling_never_levers_up():
    rule = S.TimeSeriesMomentum(lookback=20, long_only=True, vol_window=20, target_daily_vol=0.5)
    for t in range(60, 299):
        view = {a: M._Past(s, t) for a, s in universe(seed=6).items()}
        assert sum(abs(x) for x in rule(view, t).values()) <= 1 + 1e-12


def test_xs_momentum_picks_top_k_deterministically_with_name_ties():
    past = {"B": [100, 110], "A": [100, 110], "C": [100, 90], "D": [100, 105]}
    assert S.CrossSectionalMomentum(lookback=1, top_k=2, long_only=True)(past, 1) == {"A": 0.5, "B": 0.5}
    ls = S.CrossSectionalMomentum(lookback=1, top_k=1, long_only=False)(past, 1)
    assert ls == {"A": 0.5, "C": -0.5} and sum(ls.values()) == 0


def test_insufficient_history_means_no_position():
    assert S.CrossSectionalMomentum(lookback=5, top_k=1, long_only=True)({"A": [1, 2]}, 1) == {}
    assert TSM({"A": [1.0] * 5}, 4) == {}


@pytest.mark.parametrize("kw", [dict(lookback=0), dict(lookback=True), dict(lookback=2.0),
                                dict(vol_window=10), dict(target_daily_vol=0.01),
                                dict(vol_window=1, target_daily_vol=0.01),
                                dict(vol_window=10, target_daily_vol=float("nan"))])
def test_tsmom_parameters_validated(kw):
    base = dict(lookback=20, long_only=True, vol_window=None, target_daily_vol=None)
    base.update(kw)
    with pytest.raises(S.SignalError):
        S.TimeSeriesMomentum(**base)


def test_signal_parameters_have_no_defaults():
    for cls in (S.TimeSeriesMomentum, S.CrossSectionalMomentum):
        with pytest.raises(TypeError):
            cls()


# --- governance / refusals ----------------------------------------------------------------------

@pytest.mark.parametrize("perm", [
    M.DatasetPermission("binance_vision_spot", licence_cleared=False, holdout_excluded=True, reference="A19"),
    M.DatasetPermission("binance_vision_spot", licence_cleared=True, holdout_excluded=False, reference="x"),
    M.DatasetPermission("binance_vision_spot", licence_cleared=True, holdout_excluded=True, reference=" "),
    M.DatasetPermission("real_data", True, True, "x", synthetic=True),
    None,
])
def test_run_refuses_without_a_valid_data_permission(perm):
    with pytest.raises(M.SimulationError, match="dataset permission"):
        M.run(universe(), XSM, costs=C.BASELINE, permission=perm, start=60, allow_short=False)


def test_short_weights_refused_on_a_long_only_market():
    rule = S.CrossSectionalMomentum(lookback=20, top_k=1, long_only=False)
    with pytest.raises(M.SimulationError, match="long-only"):
        run(universe(), rule)
    assert run(universe(), rule, allow_short=True).days > 0


@pytest.mark.parametrize("w", [{"A0": 0.7, "A1": 0.7}, {"A0": float("nan")}, {"ZZ": 0.1}, {"A0": True}])
def test_invalid_weights_refused(w):
    with pytest.raises(M.SimulationError):
        run(universe(), lambda past, t: w)


@pytest.mark.parametrize("bad", [{"A": [100, float("nan"), 101]}, {"A": [100, 0, 101]},
                                 {"A": [1, 2, 3], "B": [1, 2]}, {}])
def test_bad_prices_refused(bad):
    with pytest.raises(M.SimulationError):
        M.run(bad, TSM, costs=C.BASELINE, permission=M.SYNTHETIC, start=0, allow_short=False)


def test_results_are_labelled_non_confirmatory():
    assert run(universe(), XSM).evidence_class == "SYNTHETIC_OR_EXPLORATORY_NOT_CONFIRMATORY"


# --- isolation ----------------------------------------------------------------------------------

ALLOWED = {"__future__", "math", "dataclasses", "collections", "collections.abc"}


def test_package_is_stdlib_only_and_has_no_io():
    for p in PKG.glob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name in ALLOWED, f"{p.name}: import {a.name}"
            elif isinstance(node, ast.ImportFrom):
                assert node.module in ALLOWED or node.module.startswith("research.mechanisms"), \
                    f"{p.name}: from {node.module}"
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("open", "eval", "exec"):
                pytest.fail(f"{p.name}: {node.func.id}()")


def test_no_production_module_imports_the_package():
    for d in ("analyzer", "signal_engine", "trade_tracker", "telegram", "scanner", "shared"):
        for p in pathlib.Path(d).rglob("*.py"):
            assert "research.mechanisms" not in p.read_text(encoding="utf-8", errors="ignore"), p
