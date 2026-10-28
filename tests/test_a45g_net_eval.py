"""a45g-ne-v1: synthetic, deterministic tests for research/evaluation/net_eval.py.

They prove accounting, labelling and inference-plumbing properties of the evaluator on generated
inputs only. Nothing here says whether any strategy earns money (evidence class: SYNTHETIC)."""
import ast
import math
import pathlib
import sys

import pytest

sys.path.insert(0, ".")
from research.evaluation import net_eval as N  # noqa: E402
from research.evaluation import synthetic as Y  # noqa: E402
from research.mechanisms.simulate import SYNTHETIC, DatasetPermission  # noqa: E402

PKG = pathlib.Path("research/evaluation")
DAY = 86400.0


def tr(i, gross, *, fee=None, spread=0.0, slip=0.0, day=0, symbol="AAA", risk=None, regime=None, to=2.0):
    fee = 0.001 * to if fee is None else fee
    ts = day * DAY + i
    return N.TradeRecord(f"t{i}", symbol, ts, ts + 3600, gross, fee, spread, slip, to, risk=risk, regime=regime)


def ev(trades, **kw):
    kw.setdefault("permission", SYNTHETIC)
    kw.setdefault("n_resamples", 200)
    return N.evaluate(trades, **kw)


# --- per-trade accounting ------------------------------------------------------------------------

def test_two_leg_trade_identity_and_components():
    t = N.trade_from_prices("a", "X", 0, 60, entry_ref=100.0, exit_ref=103.0, half_spread_entry=0.0002,
                            half_spread_exit=0.0003, slippage_entry=0.0005, slippage_exit=0.0004)
    buy, sell = 100 * 1.0005, 103 * (1 - 0.0004)
    q = 1 / buy
    assert t.turnover == pytest.approx(1 + q * sell, rel=1e-15)
    assert t.fee == pytest.approx(0.001 * t.turnover, rel=1e-15)
    assert t.net == pytest.approx(q * sell - 1 - t.fee - t.spread, abs=1e-15)
    assert t.net == pytest.approx(t.gross - t.fee - t.spread - t.slippage, abs=1e-15)


def test_parity_with_the_a48_cost_ledger():
    from shared.execution_calibration import ExecutedLeg, cost_ledger
    q_e, q_x, h = 0.0005, 0.0010, 0.0002
    legs = [ExecutedLeg("entry", 1.0, 100.0, 100.0 * (1 + q_e), True),
            ExecutedLeg("stop_loss", 1.0, 97.0, 97.0 * (1 - q_x), True)]
    led = cost_ledger(legs, notional_usdt=50.0, half_spread_pct=h * 100)
    a = N.trade_from_cost_ledger(led, trade_id="l", symbol="X", entry_ts=0, exit_ts=1)
    b = N.trade_from_prices("p", "X", 0, 1, entry_ref=100.0, exit_ref=97.0, half_spread_entry=h,
                            half_spread_exit=h, slippage_entry=q_e, slippage_exit=q_x)
    for f in ("gross", "fee", "spread", "slippage", "turnover", "net"):
        assert getattr(a, f) == pytest.approx(getattr(b, f), rel=1e-12, abs=1e-15), f
    assert a.net * 50.0 == pytest.approx(led.net_modeled_pnl_usdt, rel=1e-12)


def test_discounted_fee_is_refused():
    with pytest.raises(N.EvaluationError):
        tr(0, 0.01, fee=0.0019, to=2.0)
    with pytest.raises(N.EvaluationError):
        N.trade_from_prices("a", "X", 0, 1, entry_ref=1, exit_ref=1, half_spread_entry=0, half_spread_exit=0,
                            slippage_entry=0, slippage_exit=0, fee_per_side=0.00075)


@pytest.mark.parametrize("kw", [dict(gross=float("nan")), dict(gross=-1.0), dict(spread=-0.1),
                                dict(to=0.0), dict(risk=0.0)])
def test_invalid_records_refused(kw):
    base = dict(gross=0.01)
    base.update(kw)
    with pytest.raises(N.EvaluationError):
        tr(0, base.pop("gross"), **base)


def test_unfilled_intents_are_counted_not_dropped():
    trades = [tr(0, 0.02), tr(1, -0.01), N.unfilled_intent("u1", "AAA", 5.0), N.unfilled_intent("u2", "AAA", 6.0)]
    r = ev(trades)
    assert (r.n_intents, r.n_filled, r.fill_rate) == (4, 2, 0.5)
    assert r.per_intent_mean_net == pytest.approx(sum(t.net for t in trades) / 4)
    with pytest.raises(N.EvaluationError):
        N.TradeRecord("u", "AAA", 0, 0, 0.01, 0, 0, 0, 0, filled=False)


def test_no_filled_trades_returns_an_empty_labelled_result():
    r = ev([N.unfilled_intent("u", "AAA", 0.0)])
    assert r.n_filled == 0 and r.mean_net is None and r.stress == () and "no_filled_trades" in r.warnings
    assert r.not_a_profitability_claim is True


# --- attribution, break-even, stress -------------------------------------------------------------

def test_attribution_sums_and_break_even_equals_mean_cost():
    trades = [tr(i, g, spread=0.0004, slip=0.0006 * (i % 3)) for i, g in enumerate([0.01, -0.004, 0.002, -0.01])]
    r = ev(trades)
    c = r.costs
    assert c.mean_fee + c.mean_spread + c.mean_slippage == pytest.approx(c.mean_total, abs=1e-15)
    assert c.fee_share + c.spread_share + c.slippage_share == pytest.approx(1.0)
    assert r.break_even_gross_edge == pytest.approx(r.mean_gross - r.mean_net, abs=1e-15)
    assert r.tracker_flat_mean_net == pytest.approx(r.mean_gross - 0.003)


def test_stress_never_improves_net_and_never_touches_the_fee():
    trades = [tr(i, 0.004, spread=0.0005, slip=0.0005) for i in range(5)]
    r = ev(trades)
    means = [s.mean_net for s in r.stress]
    assert [s.multiplier for s in r.stress] == [1.0, 1.5, 2.0]
    assert means[0] == pytest.approx(r.mean_net) and means == sorted(means, reverse=True)
    fee_only = ev([tr(i, 0.004) for i in range(5)])
    assert len({round(s.mean_net, 15) for s in fee_only.stress}) == 1


def test_price_improvement_is_not_amplified_by_stress():
    t = tr(0, 0.003, slip=-0.0005)
    assert t.stressed_net(2.0) == pytest.approx(t.net)


def test_fragile_flag_when_the_net_sign_flips_under_stress():
    # gross 0.0035, fee 0.002, spread+slip 0.001 -> net +0.0005 at x1, -0.0005 at x2
    r = ev([tr(i, 0.0035, spread=0.0005, slip=0.0005) for i in range(4)])
    assert r.mean_net > 0 > r.stress[-1].mean_net
    assert r.fragile is True and "fragile_net_sign_under_cost_stress" in r.warnings


def test_r_units_only_when_every_trade_has_a_risk():
    r = ev([tr(0, 0.01, risk=0.01), tr(1, -0.01, risk=0.01)])
    assert r.mean_cost_r == pytest.approx(0.2) and r.mean_gross_r == pytest.approx(0.0)
    assert ev([tr(0, 0.01, risk=0.01), tr(1, -0.01)]).mean_cost_r is None


def test_gross_wins_turned_net_losses_are_reported():
    r = ev([tr(0, 0.001), tr(1, 0.01)])
    assert r.gross_win_net_loss_rate == 0.5 and "gross_wins_turned_net_losses" in r.warnings


def test_break_even_win_rate():
    assert N.break_even_win_rate(0.01, 0.01, 0.003) == pytest.approx(0.65)
    assert N.break_even_win_rate(0.002, 0.01, 0.003) > 1          # geometry cannot break even
    with pytest.raises(N.EvaluationError):
        N.break_even_win_rate(0.0, 0.01, 0.0)


# --- turnover, drawdown, concentration -------------------------------------------------------------

def test_drawdown_on_a_known_path():
    nets = [0.02, -0.01, -0.02, 0.01]
    trades = [tr(i, g + 0.002, day=i) for i, g in enumerate(nets)]
    r = ev(trades, notional_usdt=50.0, capital_usdt=1000.0)
    assert r.max_drawdown_usdt == pytest.approx(1.5)
    assert r.max_drawdown_frac == pytest.approx(1.5 / 1001.0)
    assert r.max_drawdown_trades == 3
    assert r.total_net_usdt == pytest.approx(0.0, abs=1e-12)


def test_turnover_in_capital_units():
    r = ev([tr(i, 0.0, day=i) for i in range(10)], notional_usdt=50.0, capital_usdt=1000.0)
    assert r.turnover_capital == pytest.approx(10 * 2.0 * 50 / 1000)
    assert r.turnover_capital_per_day == pytest.approx(r.turnover_capital / r.span_days)


def test_one_outlier_carrying_the_mean_is_flagged():
    trades = [tr(i, -0.001, day=i) for i in range(99)] + [tr(99, 0.5, day=99)]
    r = ev(trades)
    assert r.mean_net > 0 >= r.mean_net_without_top_1pct
    assert "net_sign_depends_on_top_1pct" in r.warnings


def test_top_symbol_share():
    r = ev([tr(0, 0.03, symbol="A"), tr(1, 0.012, symbol="B")])
    assert r.top_symbol_share == pytest.approx(0.028 / (0.028 + 0.010))


# --- uncertainty -----------------------------------------------------------------------------------

def test_one_trade_per_day_has_design_effect_one():
    trades = [tr(i, 0.001 * ((i * 7) % 5 - 2), day=i) for i in range(40)]
    r = ev(trades)
    assert r.design_effect == pytest.approx(1.0)
    assert r.se_day_cluster == pytest.approx(r.se_iid)


@pytest.mark.parametrize("k", [2, 5])
def test_identical_copies_within_a_day_inflate_the_design_effect_exactly(k):
    d = 30
    trades = [tr(j * 100 + c, 0.001 * ((j * 7) % 5 - 2), day=j) for j in range(d) for c in range(k)]
    r = ev(trades)
    assert r.design_effect == pytest.approx((k * d - 1) / (d - 1))
    assert r.effective_n == pytest.approx(k * d / r.design_effect)


def test_bootstrap_is_seeded_and_degenerate_for_constant_returns():
    trades = [tr(i, 0.001 * ((i * 7) % 5 - 2), day=i % 12) for i in range(60)]
    a, b = ev(trades, seed=3), ev(trades, seed=3)
    assert a.ci_mean_net == b.ci_mean_net and a.ci_mean_net.low <= a.mean_net <= a.ci_mean_net.high
    const = ev([tr(i, 0.004, day=i) for i in range(20)])
    assert const.ci_mean_net.low == pytest.approx(const.mean_net) == pytest.approx(const.ci_mean_net.high)


def test_single_day_has_no_cluster_inference():
    r = ev([tr(i, 0.001 * i) for i in range(5)])
    assert r.se_day_cluster is None and r.ci_mean_net is None and "single_day_no_cluster_se" in r.warnings


# --- labels and governance ---------------------------------------------------------------------------

def test_synthetic_marker_gives_synthetic_label_and_never_a_claim():
    r = ev([tr(0, 0.01)])
    assert r.evidence_class == "SYNTHETIC" and r.not_a_profitability_claim is True


@pytest.mark.parametrize("perm", [None, "synthetic",
                                  DatasetPermission("binance_vision", False, True, "none"),
                                  DatasetPermission("binance_vision", True, False, "none"),
                                  DatasetPermission("fake", True, True, "x", synthetic=True)])
def test_missing_or_invalid_permission_is_refused(perm):
    with pytest.raises(N.EvaluationError):
        N.evaluate([tr(0, 0.01)], permission=perm)


def test_real_data_needs_an_owner_authorization_reference():
    perm = DatasetPermission("hypothetical_cleared_source", True, True, "owner record")
    with pytest.raises(N.EvaluationError):
        N.evaluate([tr(0, 0.01)], permission=perm, n_resamples=100)
    r = N.evaluate([tr(0, 0.01)], permission=perm, authorization_ref="OD-X", n_resamples=100)
    assert r.evidence_class == "EXPLORATORY_NOT_CONFIRMATORY"


@pytest.mark.parametrize("kw", [dict(stress=(1.5, 2.0)), dict(stress=(1.0, 2.0, 1.5)), dict(n_resamples=10),
                                dict(ci_level=1.0), dict(notional_usdt=0)])
def test_invalid_evaluation_arguments_refused(kw):
    with pytest.raises(N.EvaluationError):
        ev([tr(0, 0.01)], **kw)


def test_duplicate_trade_ids_refused():
    with pytest.raises(N.EvaluationError):
        ev([tr(0, 0.01), tr(0, 0.02)])


def test_strata_partition_the_population_and_are_marked_descriptive():
    trades = [tr(i, 0.001 * (i % 4 - 1), day=i, regime=("up" if i % 3 else None)) for i in range(30)]
    s = N.stratified(trades, key=lambda t: t.regime, permission=SYNTHETIC, n_resamples=100)
    assert set(s) == {"up", "unlabelled"}
    assert sum(v.n_filled for v in s.values()) == 30
    assert all("stratum_descriptive_only" in v.warnings for v in s.values())


# --- synthetic null-model engine check (SYNTHETIC; not a strategy) ----------------------------------

def test_null_entries_recover_the_known_cost_drag():
    closes, _ = Y.regime_switching_market(6000, {"flat": (0.0, 0.01)}, stay_prob=1.0, seed=11)
    times = [3600.0 * (i + 1) for i in range(len(closes))]
    trades = Y.null_entry_trades(closes, times, n_trades=1500, horizon=4, seed=5, half_spread=0.0002,
                                 slippage=0.0003)
    r = ev(trades, n_resamples=500)
    expected_cost = 0.002 + 2 * 0.0002 + 2 * 0.0003            # first order, both legs taker
    assert r.costs.mean_total == pytest.approx(expected_cost, rel=0.02)
    assert r.costs.mean_fee == pytest.approx(0.002, rel=0.02)
    assert r.ci_mean_net.low < -expected_cost < r.ci_mean_net.high   # zero-drift gross: net ~ -cost
    assert r.n_days >= 200 and r.design_effect > 0


# --- isolation ---------------------------------------------------------------------------------------

ALLOWED = {"__future__", "math", "random", "bisect", "dataclasses", "collections", "collections.abc"}


def test_package_is_stdlib_only_and_has_no_io():
    for p in PKG.glob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name in ALLOWED, f"{p.name}: import {a.name}"
            elif isinstance(node, ast.ImportFrom):
                assert node.module in ALLOWED or node.module.startswith(("research.evaluation",
                                                                         "research.mechanisms")), \
                    f"{p.name}: from {node.module}"
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("open", "eval", "exec"):
                pytest.fail(f"{p.name}: {node.func.id}()")


def test_no_production_module_imports_the_package():
    for d in ("analyzer", "signal_engine", "trade_tracker", "telegram", "scanner", "shared"):
        for p in pathlib.Path(d).rglob("*.py"):
            assert "research.evaluation" not in p.read_text(encoding="utf-8", errors="ignore"), p
