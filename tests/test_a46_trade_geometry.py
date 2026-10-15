"""A46 trade-geometry engine: 30 synthetic engineering scenarios.

Brackets come from PRODUCTION code (strategy_math == analyzer _calculate_levels, asserted);
exits are priced with the tracker's own partial_exits / triple_barrier functions and the A42
counterfactual replay. These tests prove arithmetic and engineering properties, not profitability."""
import math
import random
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'analyzer'); sys.path.insert(0, 'tests')
from dataclasses import replace

import numpy as np
import pytest

import a45_synthetic as syn
from technical_analyzer import TechnicalAnalyzer
from shared.counterfactual_barrier import Bar, replay_bracket
from shared.partial_exits import target_distribution
from shared.signal_identity import freshness_at
from shared.trade_geometry import (BASELINE, G1, G2, G3, PATHS, Bracket, CostFeasibleTarget,
                                   ExecutionCosts, GeometryError, References, baseline_bracket,
                                   break_even_stop, breakeven_requirements, diagnostics, exit_ledger,
                                   g1_bracket, g3_bracket, independent_resistance, quantize,
                                   references, resistance_cap)

TA = TechnicalAnalyzer(None)


def ind(df):
    return TA._calculate_indicators(df.copy())


def manual(risk_pct=0.92, t1_r=1.0, entry=100.0, tt="momentum", tf="15m"):
    r = entry * risk_pct / 100
    refs = References(entry, r, entry - 0.5 * r, entry - r, entry + 10, False)
    return Bracket(BASELINE, tt, tf, entry, entry - r, entry - r, entry + t1_r * r, entry + 1.8 * r,
                   entry + 2.2 * r, "momentum_breakout", True, None, refs, {})


def reversion_frame(seed=4):
    rng = np.random.default_rng(seed)
    c = 100 * (1 + 0.003 * np.sin(np.arange(200) / 3) + rng.normal(0, 0.0008, 200))
    c[-6:-1] = c[-7] * np.array([0.995, 0.99, 0.985, 0.98, 0.976])   # dip
    c[-1] = c[-2] * 1.004                                            # bounce candle
    return syn.frame(c, wick=0.001, seed=seed)


# 29 ── baseline parity with the production analyzer ─────────────────────────

def test_29_baseline_equals_production_analyzer_levels_on_random_frames():
    checked = 0
    for seed in range(60):
        d = ind(syn.random_walk(seed=seed))
        for tf in ("15m", "4h", "1d"):
            for tt in ("momentum", "reversion"):
                prod = TA._calculate_levels(d, tf, tt)
                b = baseline_bracket(d, tf, tt)
                assert (b.entry, b.stop, b.t1, b.t2, b.t3, b.valid, b.stop_policy) == (
                    prod["entry"], prod["stop"], prod["t1"], prod["t2"], prod["t3"],
                    prod["stop_valid"], prod["stop_policy"]), (seed, tf, tt)
                if b.valid:                  # the cap rule is the production one (to 8-decimal rounding:
                    # production applies it to the unrounded close, we to the rounded prices)
                    assert abs(resistance_cap(b.entry, b.risk, b.refs.window_high) - b.t1) <= 2e-8
                checked += 1
    assert checked == 360


# 1–4 ── momentum geometry ────────────────────────────────────────────────

def test_01_clean_breakout_unit_risk_and_target_multiples():
    b = baseline_bracket(ind(syn.breakout(extension=0.001)), "15m", "momentum")
    d = diagnostics(b)
    assert b.valid and d["stop_anchor"] == "atr_floor" and d["risk_atr"] == pytest.approx(1.0, abs=1e-6)
    assert (d["t2_r"], d["t3_r"]) == (pytest.approx(1.8, abs=1e-6), pytest.approx(2.2, abs=1e-6))


def _replay(b, path_bars, tf="15m"):
    bars = [Bar(syn.T0 + 10**10 + i * syn.STEP[tf], *o) for i, o in enumerate(path_bars)]
    return replay_bracket(trade_type=b.trade_type, planned_entry=b.entry, stop_loss=b.stop,
                          target_1=b.t1, target_2=b.t2, target_3=b.t3, invalidation_price=b.invalidation,
                          signal_timeframe=tf, bars=bars, bar_timeframe=tf, decision_ms=syn.T0 + 10**10)


def test_02_false_breakout_stop_path_ledger_matches_replay_gross():
    b = baseline_bracket(ind(syn.breakout(extension=0.001)), "15m", "momentum")
    e, s = b.entry, b.stop
    out = _replay(b, [(e, e * 1.001, s * 0.999, s * 1.0005)])
    led = exit_ledger(b, "stop_before_t1")
    assert out.exit_reason == "stop_loss"
    assert out.gross_pct == pytest.approx(led.tracker_gross_pct, abs=1e-3)


def test_03_late_entry_expands_risk_mechanically_and_g3_restores_unit_risk():
    base = baseline_bracket(ind(syn.breakout(extension=0.012, drift=0.006)), "4h", "momentum")
    d = diagnostics(base)
    assert base.valid and d["extension_atr"] > 0.75 and d["stop_anchor"] == "structure"
    assert d["risk_atr"] == pytest.approx(d["extension_atr"] + 0.25, abs=1e-6)
    assert d["t1_r"] <= 1.0 + 1e-9                                   # targets scale with R, not ATR
    g3 = g3_bracket(ind(syn.breakout(extension=0.012, drift=0.006)), "4h", "momentum")
    assert g3.version == G3 and g3.entry < base.entry
    assert (g3.entry - g3.stop) / g3.refs.atr == pytest.approx(1.0, abs=1e-6)
    assert g3.stop == pytest.approx(base.stop, abs=1e-8)              # same structural stop


def _capped_case():
    probe = baseline_bracket(ind(syn.breakout(extension=0.03, drift=0.006)), "4h", "momentum")
    risk = probe.risk / probe.entry
    return ind(syn.breakout(extension=0.03, drift=0.006, upper=(0.0102 + risk) / 2))


def test_04_breakout_at_nearby_resistance_is_capped_by_the_decision_bar():
    df = _capped_case()
    b = baseline_bracket(df, "4h", "momentum")
    assert b.t1_cap == {"active": True, "source": "decision_bar", "level": b.refs.window_high}
    assert b.refs.window_high_is_decision_bar and b.entry < b.t1 < b.entry + b.risk
    assert "t1_capped_by_decision_bar" in diagnostics(b)["flags"]


def test_05_no_independent_resistance_means_no_cap_under_g1():
    df = _capped_case()
    g1 = g1_bracket(df, "4h", "momentum")
    assert g1.version == G1 and independent_resistance(df, g1.entry) is None
    assert g1.t1_cap["source"] == "none_above_entry" and g1.t1 == round(g1.entry + g1.risk, 8)


def test_06_resistance_below_entry_or_beyond_1r_never_caps():
    assert resistance_cap(100, 1, 99.5) == 101                       # below entry
    assert resistance_cap(100, 1, 102) == 101                        # beyond 1R
    assert resistance_cap(100, 1, 100.5) == 101                      # 0.99 × 100.5 < entry
    assert resistance_cap(100, 1, 100.9) == 101                      # 0.99 × 100.9 < entry too
    assert resistance_cap(100, 3, 102) == pytest.approx(102 * 0.99)  # binds
    assert resistance_cap(100, 1, None) == 101
    # the cap can bind only if entry/0.99 < resistance < entry + R, i.e. only when R > 1.0101 %
    for r_pct in (0.5, 1.0, 1.01):
        assert all(resistance_cap(100, r_pct, 100 + k * r_pct / 50) == 100 + r_pct for k in range(1, 50))
    assert resistance_cap(100, 1.02, 101.015) < 101.02


# 7–11 ── volatility and stop limits ─────────────────────────────────────

def test_07_atr_zero_is_refused_and_near_zero_is_flagged():
    df = ind(syn.breakout())
    with pytest.raises(GeometryError, match="atr_non_positive"):
        references(df.assign(atr=0.0))
    d = diagnostics(manual(risk_pct=0.15))
    assert {"risk_not_above_round_trip_fee", "t1_path_net_negative"} <= set(d["flags"])


def test_08_11_very_high_atr_activates_the_stop_cap_and_invalidates():
    df = ind(syn.breakout(extension=0.03))
    b = baseline_bracket(df, "15m", "momentum")                       # 15m cap 2 %
    assert not b.valid and b.reject_reason == "structural_risk_exceeds_cap"
    hi = df.assign(atr=df["atr"] * 20)
    assert not baseline_bracket(hi, "4h", "momentum").valid
    assert not g3_bracket(hi, "4h", "momentum").valid
    with pytest.raises(GeometryError, match="bracket_invalid"):
        exit_ledger(b, "t3")


def test_09_10_tight_structure_is_widened_to_one_atr_and_wide_structure_is_kept():
    df = ind(reversion_frame())
    rev = baseline_bracket(df, "4h", "reversion")
    d = diagnostics(rev)
    structural = rev.refs.structure_low - 0.25 * rev.refs.atr
    if structural >= rev.entry - rev.refs.atr:                        # tight: floor wins
        assert d["stop_anchor"] == "atr_floor" and d["risk_atr"] == pytest.approx(1.0, abs=1e-6)
    else:
        assert d["stop_anchor"] == "structure"
    wide = baseline_bracket(ind(syn.breakout(extension=0.012, drift=0.006)), "4h", "momentum")
    assert diagnostics(wide)["stop_anchor"] == "structure"


# 12–19 ── exit economics ────────────────────────────────────────────────

def test_12_production_never_sets_t1_at_or_below_entry_but_the_flag_exists():
    for seed in range(60):
        d = ind(syn.random_walk(seed=seed))
        for tt in ("momentum", "reversion"):
            b = baseline_bracket(d, "4h", tt)
            if b.valid:
                assert b.t1 > b.entry
    bad = replace(manual(), t1=99.9)
    assert "t1_below_gross_breakeven" in diagnostics(bad)["flags"]
    assert CostFeasibleTarget(enabled=True).evaluate(bad).allow is False


def test_13_t1_below_net_breakeven_is_a_gross_win_net_loss():
    b = manual(risk_pct=0.92, t1_r=0.2)                              # T1 = +0.184 %
    req = breakeven_requirements(b)
    led = exit_ledger(b, "t1_then_break_even")
    assert led.gross_usdt > 0 > led.net_usdt and req["gross_win_net_loss_t1_path"]
    assert req["min_t1_pct_for_t1_path"] == pytest.approx(0.275, abs=1e-3)
    g2 = CostFeasibleTarget()
    assert g2.version == G2 and g2.evaluate(b).would_allow is False and g2.evaluate(b).allow is True


def test_14_partial_t1_fill_and_min_notional_merge():
    assert target_distribution(50, 5) == {1: 0.25, 2: 0.50, 3: 0.25}
    assert target_distribution(10, 5) == {1: 0.0, 2: 1.0, 3: 0.0}    # both sub-minimum edges merged
    led = exit_ledger(manual(), "t1_then_break_even")
    assert [(l.kind, l.fraction) for l in led.legs] == [("entry", 1.0), ("target", 0.25), ("stop", 0.75)]
    merged = exit_ledger(manual(), "t1_then_break_even", notional=10)
    assert [l.kind for l in merged.legs] == ["entry", "stop"]         # nothing sold at T1


def test_15_break_even_level_after_t1():
    hi = manual(risk_pct=2.0)                                         # T1 +2 % > net break-even
    assert break_even_stop(hi) == pytest.approx(100 * 1.003 / 0.999)
    lo = manual(risk_pct=0.3)                                         # T1 +0.3 % < 0.4004 %
    assert break_even_stop(lo) == lo.t1


def test_16_t2_t3_not_reached_exit_at_break_even():
    b = manual(risk_pct=2.0)
    led = exit_ledger(b, "t1_then_break_even")
    stop_leg = led.legs[-1]
    assert stop_leg.fraction == 0.75 and stop_leg.price == pytest.approx(break_even_stop(b) * 0.999)
    out = _replay(b, [(100, 102.1, 99.9, 102.0), (102.0, 102.0, 100.2, 100.25)])
    assert (out.exit_reason, out.target_reached) == ("break_even", 1)
    assert out.gross_pct == pytest.approx(led.tracker_gross_pct, abs=1e-3)


def test_17_18_spread_and_slippage_raise_costs_monotonically():
    b = manual()
    nets = [exit_ledger(b, "stop_before_t1", ExecutionCosts(entry_half_spread_pct=s,
                                                            stop_half_spread_pct=s)).net_pct
            for s in (0.0, 0.01, 0.05, 0.1)]
    assert nets == sorted(nets, reverse=True)
    slip = [exit_ledger(b, "stop_before_t1", ExecutionCosts(stop_slippage_frac=x)).net_pct
            for x in (0.0, 0.001, 0.005)]
    assert slip == sorted(slip, reverse=True)
    assert exit_ledger(b, "t3", ExecutionCosts(entry_slippage_pct=0.05)).net_pct < exit_ledger(b, "t3").net_pct
    assert ExecutionCosts(fee_rate_per_side=0.5).validate() == ["fee_rate_per_side"]


def test_19_gap_through_stop_loses_more_than_the_modelled_stop_path():
    b = baseline_bracket(ind(syn.breakout(extension=0.001)), "15m", "momentum")
    e, s = b.entry, b.stop
    out = _replay(b, [(e, e * 1.001, e * 0.999, e), (s * 0.97, s * 0.975, s * 0.96, s * 0.97)])
    assert out.gross_pct < exit_ledger(b, "stop_before_t1").tracker_gross_pct


# 20–21 ── reversion ─────────────────────────────────────────────────────

def test_20_reversion_stop_uses_the_structure_low_minus_quarter_atr():
    df = ind(reversion_frame())
    b = baseline_bracket(df, "4h", "reversion")
    assert b.valid and b.stop_policy == "reversion_structure"
    assert b.invalidation == pytest.approx(b.refs.structure_low - 0.25 * b.refs.atr, abs=1e-8)
    assert b.stop == pytest.approx(min(b.invalidation, b.entry - b.refs.atr), abs=1e-8)


def test_21_reversion_cap_comes_from_prior_bars_not_the_decision_bar():
    df = ind(reversion_frame())
    b = baseline_bracket(df, "4h", "reversion")
    assert not b.refs.window_high_is_decision_bar                    # the bar is near the lows
    if b.t1_cap["active"]:
        assert b.t1_cap["source"] == "prior_bars"
    g1 = g1_bracket(df, "4h", "reversion")
    assert g1.t1 >= b.t1 - 2e-8 or g1.t1_cap["source"] == "independent_swing_high"


# 22–26 ── input validation, boundaries, rounding ───────────────────────

def test_22_23_missing_structure_and_nonfinite_indicator_raise():
    df = ind(syn.breakout())
    with pytest.raises(GeometryError, match="history_insufficient"):
        references(df.iloc[-10:])
    bad = df.copy(); bad.iloc[-3, bad.columns.get_loc("high")] = float("nan")
    with pytest.raises(GeometryError, match="structure_non_finite"):
        references(bad)
    with pytest.raises(GeometryError, match="atr_non_finite"):
        references(df.assign(atr=float("nan")))


def test_24_invalid_timeframe_and_setup_are_refused():
    df = ind(syn.breakout())
    with pytest.raises(GeometryError, match="timeframe_invalid"):
        baseline_bracket(df, "2h", "momentum")
    with pytest.raises(GeometryError, match="trade_type_unsupported"):
        baseline_bracket(df, "15m", None)
    with pytest.raises(GeometryError, match="path_unknown"):
        exit_ledger(manual(), "t4")


def test_25_candle_boundary_transition():
    df = ind(syn.breakout())
    close_ms = int(df["close_time"].iloc[-1])
    step = syn.STEP["15m"]
    assert freshness_at("15m", close_ms, close_ms + 1).admissible
    assert freshness_at("15m", close_ms, close_ms + step).admissible           # next candle's last ms
    assert freshness_at("15m", close_ms, close_ms + step + 1).reason == "superseded_by_newer_candle"
    a = baseline_bracket(df, "15m", "momentum")
    nxt = syn.breakout(n=201)
    b = baseline_bracket(ind(nxt), "15m", "momentum")
    assert a == baseline_bracket(df.copy(), "15m", "momentum")      # same candle → same geometry
    assert (a.entry, a.stop) != (b.entry, b.stop)                     # new candle → new geometry


def test_26_price_and_quantity_rounding():
    b = baseline_bracket(ind(syn.breakout()), "15m", "momentum")
    for v in (b.entry, b.stop, b.t1, b.t2, b.t3):
        assert v == round(v, 8)                                        # production 8-decimal prices
    assert quantize(101.23456, 0.01, "floor") == 101.23 and quantize(101.23456, 0.01, "ceil") == 101.24
    assert quantize(0.1 + 0.2, 0.1, "floor") == 0.3                    # decimal, not binary, steps
    with pytest.raises(GeometryError):
        quantize(1.0, 0.0, "floor")


# 27–28 ── fees, determinism ─────────────────────────────────────────────

def test_27_fees_are_applied_per_leg_and_compared_with_the_tracker_flat_model():
    b = manual(risk_pct=0.92)
    led = exit_ledger(b, "t3")
    exits = sum(50 * l.fraction * l.price / b.entry for l in led.legs if l.kind != "entry")
    assert led.cost_usdt == pytest.approx(0.001 * (50 + exits))
    assert led.tracker_flat_net_pct == pytest.approx(led.tracker_gross_pct - 0.3)
    assert led.net_pct - led.tracker_flat_net_pct == pytest.approx(0.3 - led.cost_usdt / 50 * 100)


def test_28_restart_replay_determinism():
    df = ind(syn.breakout())
    a = [diagnostics(baseline_bracket(df.copy(), "15m", "momentum")) for _ in range(3)]
    assert a[0] == a[1] == a[2]
    b = baseline_bracket(df, "15m", "momentum")
    path = [(b.entry, b.entry * 1.001, b.stop * 0.99, b.stop)]
    assert _replay(b, path) == _replay(b, path)
    assert [exit_ledger(b, p) for p in PATHS] == [exit_ledger(b, p) for p in PATHS]


# 30 ── isolation ────────────────────────────────────────────────────────

def test_30_experimental_module_isolation():
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parents[1]
    pat = re.compile(r"(from\s+shared(\.|\s+import\s+[^\n]*\b)|import\s+shared\.)trade_geometry\b")
    assert [str(p) for p in root.rglob("*.py") if "tests" not in p.parts and p.stem != "trade_geometry"
            and pat.search(p.read_text(errors="ignore"))] == []
    for v in (BASELINE, G1, G2, G3):
        assert v
    assert CostFeasibleTarget().enabled is False


def test_c1_capped_t1_can_sit_arbitrarily_close_to_entry_and_below_net_breakeven():
    """With the cap active, T1 = 0.99 × H for H in (entry/0.99, entry + R): T1 − entry ranges over
    (0, R − ~1 %). At 20 bps the T1 → break-even path is net-negative whenever T1 < +0.275 %,
    i.e. whenever the bar's high is within ~1.29 % of entry."""
    entry, risk = 100.0, 3.0
    for wick_pct, negative in ((1.02, True), (1.25, True), (1.30, False), (2.5, False)):
        t1 = resistance_cap(entry, risk, entry * (1 + wick_pct / 100))
        assert entry < t1 < entry + risk
        b = replace(manual(risk_pct=3.0), t1=t1)
        assert (exit_ledger(b, "t1_then_break_even").net_pct < 0) is negative, wick_pct
