"""A42: signal-quality diagnostics + synthetic regime/microstructure scenarios.

These prove engineering properties of pure functions. They are not evidence of
edge, and nothing here reads market data, the database or protected outcomes.
"""
import math
import pathlib
import sys; sys.path.insert(0, '.')

import pytest

from analyzer.simple_entry import detect_trade_setup
from shared.config import config
from shared.entry_execution import decide_long_entry
from shared.partial_exits import aggregate_close, fills_between
from shared.regime import classify_regime
from shared.signal_quality import (
    VERSION, BracketGeometry, CorrelatedExposurePolicy, CostCoveragePolicy, CostModel,
    Exposure, StrategyBracketRules, assess_candidate, bar_gaps, beta_and_correlation,
    bracket_geometry, cost_aware_rank_key, path_payoffs, required_win_rate, signal_fingerprint,
    signal_staleness, split_duplicates, validate_policies)
from shared.strategy_math import (calculate_production_indicators, calculate_signal_levels,
                                  production_indicator_params)
from shared.triple_barrier import (TripleBarrierConfig, TripleBarrierState,
                                   expiry_policy_for_timeframe, step_barrier)
from tests import a42_synthetic as syn

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _analyse(df, timeframe="15m"):
    df = calculate_production_indicators(df, production_indicator_params(config))
    condition = classify_regime(df)["condition"]
    trade_type, _, _ = detect_trade_setup(df, breakout_n=config.MOM_BREAKOUT_N,
                                          vol_mult=config.MOM_VOL_MULT, rev_rsi=config.REV_RSI,
                                          bb_max_position=config.REV_BB_MAX_POSITION,
                                          market_condition=condition)
    levels = calculate_signal_levels(df, timeframe, trade_type, breakout_n=config.MOM_BREAKOUT_N)
    return df, condition, trade_type, levels


def _candidate(levels, *, atr, symbol="SYNUSDT", timeframe="15m", trade_type="momentum", spread=0.02):
    return {"symbol": symbol, "timeframe": timeframe, "trade_type": trade_type,
            "entry_price": levels["entry"], "stop_loss": levels["stop"], "target_1": levels["t1"],
            "target_2": levels["t2"], "target_3": levels["t3"], "atr": atr,
            "order_book": {"spread_pct": spread}}


def _bracket(entry=100.0, risk=1.0, t1=None):
    return {"symbol": "X", "timeframe": "15m", "trade_type": "momentum", "entry_price": entry,
            "stop_loss": entry - risk, "target_1": t1 if t1 is not None else entry + risk,
            "target_2": entry + 1.8 * risk, "target_3": entry + 2.2 * risk, "atr": risk,
            "order_book": {"spread_pct": 0.01}}


# ── defaults, isolation, provenance ─────────────────────────────────────────

def test_policies_disabled_by_default_and_never_block_when_disabled():
    report = assess_candidate(_bracket(risk=0.05))           # cost 0.20 % ≫ 0.05 % stop
    gate = CostCoveragePolicy().evaluate(report)
    assert not CostCoveragePolicy().enabled and not CorrelatedExposurePolicy().enabled
    assert gate.would_allow is False and gate.allow is True   # shadow verdict only
    enabled = CostCoveragePolicy(enabled=True).evaluate(report)
    assert enabled.allow is False and "cost_over_risk_exceeds_cap" in enabled.reasons


def test_no_production_module_imports_signal_quality():
    offenders = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py")
                 if "tests" not in p.parts
                 and p.name not in ("signal_quality.py", "counterfactual_barrier.py",
                                    # A43 modules (checked by test_a43_*)
                                    "candidate_diagnostics.py", "candidate_selection.py",
                                    "signal_identity.py", "dependency_safety.py")
                 and ("signal_quality" in (txt := p.read_text(errors="ignore"))
                      or "counterfactual_barrier" in txt)]
    assert offenders == []


def test_report_is_deterministic_versioned_and_does_not_mutate_input():
    cand = _bracket()
    snapshot = repr(cand)
    a, b = assess_candidate(cand), assess_candidate(dict(cand))
    assert repr(cand) == snapshot
    assert a.version == VERSION and a.input_sha256 == b.input_sha256 and len(a.input_sha256) == 64
    assert a.to_dict()["metrics"] == b.to_dict()["metrics"]
    assert assess_candidate({**cand, "stop_loss": 99.01}).input_sha256 != a.input_sha256


def test_configuration_validation():
    assert validate_policies(CostModel(), StrategyBracketRules(), CostCoveragePolicy(),
                             CorrelatedExposurePolicy()) == {
        "CostModel": [], "StrategyBracketRules": [], "CostCoveragePolicy": [],
        "CorrelatedExposurePolicy": []}
    assert CostModel(exchange_fee_roundtrip_pct=-0.1).validate() == ["exchange_fee_roundtrip_pct_out_of_range"]
    assert StrategyBracketRules(fractions=(0.5, 0.5, 0.5)).validate()
    assert CostCoveragePolicy(max_cost_over_risk=0).validate()
    assert CorrelatedExposurePolicy(unknown_beta=0.5).validate() == ["unknown_beta_must_be_at_least_1"]
    with pytest.raises(ValueError, match="invalid_configuration"):
        assess_candidate(_bracket(), CostModel(stop_slippage_frac=0.5))


def test_cost_presets_are_consistent_with_tracker_accounting():
    assert CostModel().roundtrip_pct() == pytest.approx(0.20)
    assert CostModel.tracker_accounting().roundtrip_pct() == pytest.approx(config.FEE_ROUNDTRIP_PCT)
    assert CostModel.tracker_accounting().stop_slippage_frac == pytest.approx(config.STOP_SLIPPAGE)
    rules = StrategyBracketRules()
    cfg = TripleBarrierConfig(symbol="X", entry=100, target_1=101, target_2=101.8, target_3=102.2,
                              stop_loss=99)
    assert bracket_geometry(100, 99, 101, 101.8, 102.2, rules=rules).break_even_stop == \
        pytest.approx(cfg.net_break_even_stop())


# ── payoff model cross-checked against the tracker's own accounting ────────

def _tracker_t1_then_be(entry, stop, t1, t2, t3):
    cfg = TripleBarrierConfig(symbol="X", entry=entry, target_1=t1, target_2=t2, target_3=t3,
                              stop_loss=stop)
    state = TripleBarrierState(peak=entry)
    assert step_barrier(cfg, state, high=t1 * 1.0002, low=t1 * 1.00001, close=t1 * 1.0001) is None   # bar fully above T1
    fills = fills_between(previous_target=0, reached_target=1, entry=entry,
                          targets={1: t1, 2: t2, 3: t3}, trade_amount=50, min_notional=5)
    be = cfg.net_break_even_stop()
    res = step_barrier(cfg, state, high=t1, low=be * 0.999, close=be * 0.999)
    pct, _ = aggregate_close(entry=entry, final_exit=res.exit_price, trade_amount=50,
                             realized_pct=sum(f.gross_pct_contribution for f in fills),
                             realized_usdt=sum(f.gross_usdt for f in fills), remaining_fraction=0.75)
    return res, pct


@pytest.mark.parametrize("t1", [101.0, 100.25])     # T1 above and below the net break-even level
def test_t1_then_break_even_matches_tracker(t1):
    res, tracker_pct = _tracker_t1_then_be(100.0, 99.0, t1, 101.8, 102.2)
    geo = bracket_geometry(100.0, 99.0, t1, 101.8, 102.2)
    model = path_payoffs(geo, CostModel.tracker_accounting())["gross"]["t1_then_break_even"]
    assert res.exit_reason == "break_even"
    assert model == pytest.approx(tracker_pct, abs=1e-3)


def test_stop_path_matches_tracker_and_t3_path_matches_partials():
    cfg = TripleBarrierConfig(symbol="X", entry=100, target_1=101, target_2=101.8, target_3=102.2,
                              stop_loss=99)
    res = step_barrier(cfg, TripleBarrierState(peak=100), high=100.1, low=98.5, close=98.6)
    geo = bracket_geometry(100, 99, 101, 101.8, 102.2)
    pay = path_payoffs(geo, CostModel.tracker_accounting())
    assert res.exit_reason == "stop_loss"
    assert pay["gross"]["stop_before_t1"] == pytest.approx(res.profit_pct, abs=1e-3)
    fills = fills_between(previous_target=0, reached_target=3, entry=100,
                          targets={1: 101, 2: 101.8, 3: 102.2}, trade_amount=50, min_notional=5)
    assert pay["gross"]["t3"] == pytest.approx(sum(f.gross_pct_contribution for f in fills))


def test_required_win_rate():
    assert required_win_rate(1.0, -1.0) == pytest.approx(0.5)
    assert required_win_rate(-0.01, -1.0) is None
    assert required_win_rate(1.0, 0.5) == 0.0
    with pytest.raises(ValueError):
        required_win_rate(float("nan"), -1)


# ── synthetic scenarios ────────────────────────────────────────────────────

def test_strong_trend_produces_valid_momentum_bracket_with_economics():
    df, condition, trade_type, levels = _analyse(syn.strong_trend())
    assert condition == "bullish" and trade_type == "momentum"
    assert levels["stop_valid"] is True
    atr = float(df["atr"].iloc[-1])
    report = assess_candidate(_candidate(levels, atr=atr))
    assert report.geometry["risk_atr"] >= 1.0 - 1e-9          # stop at least 1 ATR away
    assert report.metrics["net_stop_pct"] < 0 < report.metrics["net_t3_path_pct"]


def test_sideways_never_emits_momentum():
    _, condition, trade_type, _ = _analyse(syn.sideways())
    assert condition == "sideways" and trade_type != "momentum"


def test_volatility_spike_is_labelled_volatile_and_emits_nothing():
    _, condition, trade_type, _ = _analyse(syn.volatility_spike())
    assert condition == "volatile" and trade_type is None


def test_sudden_reversal_exits_at_modeled_stop():
    df, _, _, levels = _analyse(syn.strong_trend())
    cfg = TripleBarrierConfig(symbol="X", entry=levels["entry"], target_1=levels["t1"],
                              target_2=levels["t2"], target_3=levels["t3"], stop_loss=levels["stop"])
    crash = levels["stop"] * 0.98
    res = step_barrier(cfg, TripleBarrierState(peak=levels["entry"]), high=levels["entry"],
                       low=crash, close=crash)
    assert res.exit_reason == "stop_loss" and res.stop_hit
    assert res.exit_price == pytest.approx(levels["stop"] * 0.999, rel=1e-6)


def test_gap_through_stop_loses_more_than_the_modeled_stop_path():
    cfg = TripleBarrierConfig(symbol="X", entry=100, target_1=101, target_2=101.8, target_3=102.2,
                              stop_loss=99)
    res = step_barrier(cfg, TripleBarrierState(peak=100), high=97, low=95, close=96,
                       stop_observation_price=96.0)
    modeled = path_payoffs(bracket_geometry(100, 99, 101, 101.8, 102.2), CostModel())
    assert res.exit_price == pytest.approx(96 * 0.999)
    assert res.profit_pct < modeled["gross"]["stop_before_t1"]   # the path model is a lower bound on loss


def test_low_liquidity_and_spread_widening_raise_cost_and_fail_the_gate():
    base = _bracket(risk=1.0)
    cost = CostModel(include_spread=True)
    ratios = [assess_candidate({**base, "order_book": {"spread_pct": s}}, cost).metrics["cost_over_risk"]
              for s in (0.01, 0.05, 0.15, 0.40)]
    assert ratios == sorted(ratios) and ratios[0] == pytest.approx(0.21)
    wide = assess_candidate({**base, "order_book": {"spread_pct": 0.40}}, cost)
    assert "cost_over_risk_exceeds_cap" in CostCoveragePolicy(enabled=True).evaluate(wide).reasons
    assert CostCoveragePolicy(enabled=True).evaluate(
        assess_candidate({**base, "order_book": {"spread_pct": 0.01}}, cost)).allow is True
    missing = assess_candidate({**base, "order_book": {}}, cost)       # no spread → fail closed
    assert missing.metrics == {} and "cost_unavailable:spread_required_by_cost_model" in missing.flags
    assert CostCoveragePolicy(enabled=True).evaluate(missing).allow is False


def test_cost_aware_rank_prefers_cheapest_cost_per_risk_not_tightest_spread():
    tight_small_stop = assess_candidate({**_bracket(risk=0.3), "symbol": "AAA",
                                         "order_book": {"spread_pct": 0.01}}, CostModel(include_spread=True))
    wider_big_stop = assess_candidate({**_bracket(risk=2.0), "symbol": "BBB",
                                       "order_book": {"spread_pct": 0.05}}, CostModel(include_spread=True))
    ranked = sorted([tight_small_stop, wider_big_stop], key=cost_aware_rank_key)
    assert ranked[0].inputs["symbol"] == "BBB"        # production key (spread first) would pick AAA
    broken = assess_candidate({**_bracket(), "stop_loss": 101.0})
    assert cost_aware_rank_key(broken)[0] == math.inf


def test_delayed_and_look_ahead_signals():
    close = syn.START_MS
    assert signal_staleness(close, close + 60_000, "15m").admissible
    late = signal_staleness(close, close + 2 * 900_000, "15m")
    assert (late.admissible, late.reason) == (False, "stale_signal")
    early = signal_staleness(close, close - 1, "15m")
    assert (early.admissible, early.reason) == (False, "decision_before_bar_close")
    assert signal_staleness(close, close, "2h").reason == "unknown_timeframe"


def test_missing_data_is_detected_not_repaired():
    times = [syn.START_MS + i * 900_000 for i in (0, 1, 2, 5, 6)]
    assert bar_gaps(times, "15m") == [(syn.START_MS + 2 * 900_000, 2)]
    assert bar_gaps([times[1], times[0]], "15m") == [(times[1], -1)]
    nan_atr = assess_candidate({**_bracket(), "atr": float("nan")})
    assert nan_atr.metrics == {} and "invalid:invalid_atr" in nan_atr.flags
    assert not bracket_geometry(100, float("nan"), 101, 102, 103).valid


def test_correlated_simultaneous_signals_hit_the_beta_cap():
    btc, alt = syn.correlated_pair(beta=1.5)
    beta, corr, n = beta_and_correlation(alt, btc)
    assert n == 399 and beta == pytest.approx(1.5, abs=0.1) and corr > 0.9
    assert beta_and_correlation(alt[:10], btc[:10]) == (None, None, 9)
    policy = CorrelatedExposurePolicy(enabled=True)
    open_ = [Exposure("ALTUSDT", 50, beta)]
    assert policy.evaluate(open_, Exposure("ALT2USDT", 50, 1.4)).reasons == ("beta_weighted_cap_exceeded",)
    assert policy.evaluate([Exposure("A", 50, 0.9)], Exposure("B", 50, 0.4)).allow is True
    assert policy.evaluate([Exposure("A", 50, 0.9)], Exposure("A", 50, 0.1)).reasons == ("symbol_already_open",)
    assert policy.evaluate([], Exposure("C", 50, None)).allow is True        # 1.5 × 50 = 75 = cap
    assert policy.evaluate([Exposure("A", 10, 0.1)], Exposure("C", 50, None)).allow is False
    assert CorrelatedExposurePolicy().evaluate(open_, Exposure("ALT2USDT", 50, 1.4)).allow is True


def test_entry_rejected_when_price_already_through_invalidation():
    assert decide_long_entry(trade_type="momentum", planned_entry=100, current_price=98.9,
                             stop_loss=99, invalidation_price=99.2).action == "reject"
    assert decide_long_entry(trade_type="momentum", planned_entry=100, current_price=100.4,
                             stop_loss=99).action == "limit_wait"


def test_fees_exceeding_gross_win_is_flagged():
    report = assess_candidate(_bracket(risk=1.0, t1=100.15))      # resistance-capped T1 = +0.15 %
    gross = report.payoffs["gross"]["t1_then_break_even"]
    assert gross > 0 > report.metrics["net_t1_path_pct"]          # a gross "WIN" that loses net
    assert {"t1_capped_below_1r", "break_even_stop_equals_t1", "t1_path_net_non_positive"} <= set(report.flags)
    assert report.metrics["required_t1_rate_two_path"] is None
    assert "t1_path_net_non_positive" in CostCoveragePolicy(enabled=True).evaluate(report).reasons


def test_duplicate_signal_from_the_same_closed_bar():
    bar = syn.START_MS + 14_400_000
    sigs = [{"symbol": "X", "timeframe": "4h", "trade_type": "momentum", "candle_close_ms": bar, "n": 1},
            {"symbol": "X", "timeframe": "4h", "trade_type": "momentum", "candle_close_ms": bar, "n": 2},
            {"symbol": "X", "timeframe": "4h", "trade_type": "momentum", "candle_close_ms": bar + 14_400_000, "n": 3}]
    kept, dupes = split_duplicates(sigs)
    assert [s["n"] for s in kept] == [1, 3] and [s["n"] for s in dupes] == [2]
    assert signal_fingerprint("X", "4h", "momentum", bar) != signal_fingerprint("X", "1d", "momentum", bar)


def test_expired_signal_closes_on_timeframe_policy():
    max_h, t1_h, no_t1_h = expiry_policy_for_timeframe("4h")
    cfg = TripleBarrierConfig(symbol="X", entry=100, target_1=103, target_2=105.4, target_3=106.6,
                              stop_loss=97, expiry_h=max_h, t1_expiry_h=t1_h, no_t1_expiry_h=no_t1_h)
    state, res = TripleBarrierState(peak=100), None
    for _ in range(int(no_t1_h)):
        res = step_barrier(cfg, state, high=100.5, low=99.5, close=100.1)
    assert res is not None and res.exit_reason == f"no_T1_expired_{int(no_t1_h)}h"


# ── the economic caveat behind candidate C1 ────────────────────────────────

def test_cost_gate_can_lower_mean_net_return_under_fixed_notional():
    """With fixed notional, net % = R% × E[R-multiple] − cost. When the gross
    R-expectancy is negative, larger stops lose more per trade, so dropping the
    small-stop trades makes the average trade *worse*, although total cost falls."""
    cost = 0.20
    for e_r in (-0.10, 0.0):
        risks = [0.3, 0.6, 1.0, 2.0, 3.0]
        net = {r: r * e_r - cost for r in risks}
        gated = [r for r in risks if cost / r <= 0.25]
        mean_all = sum(net.values()) / len(risks)
        mean_gated = sum(net[r] for r in gated) / len(gated)
        assert (mean_gated < mean_all) if e_r < 0 else (mean_gated == pytest.approx(mean_all))
    e_r = 0.25                                         # only a positive gross edge makes the gate help
    risks = [0.3, 0.6, 1.0, 2.0, 3.0]
    gated = [r for r in risks if cost / r <= 0.25]
    assert sum(r * e_r - cost for r in gated) / len(gated) > sum(r * e_r - cost for r in risks) / len(risks)
