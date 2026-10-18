"""A45: production Momentum/Reversion setups under 24 synthetic scenarios + diagnostics parity.

Every decision here is made by PRODUCTION code (analyzer TechnicalAnalyzer indicators/levels,
simple_entry.detect_trade_setup, shared.regime, shared.ohlcv, A43/A44 identity and selection,
A42 replay). The A45 module only explains and measures. Synthetic returns are not evidence of
profitability."""
import math
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'analyzer'); sys.path.insert(0, 'tests')

import numpy as np
import pandas as pd
import pytest

import a45_synthetic as syn
from simple_entry import detect_trade_setup
from technical_analyzer import TechnicalAnalyzer, indicator_warmup_bars
from shared.candidate_selection import EligibilityPolicy, eligibility_reasons, normalize
from shared.config import config
from shared.counterfactual_barrier import Bar, replay_bracket
from shared.ohlcv import closed_klines, prepare_ohlcv, validate_ohlcv
from shared.regime import classify_regime
from shared.setup_diagnostics import (ExtensionCap, MarketStateGate, SeasonalVolumeConfirmation,
                                      ema_seed_weight, explain_setups, setup_geometry,
                                      validate_indicator_frame)
from shared.signal_identity import IdentityError, candle_bounds
from shared.signal_quality import CorrelatedExposurePolicy, Exposure
from shared.signal_stop import candle_invalidated

TA = TechnicalAnalyzer(None)
PARAMS = dict(breakout_n=config.MOM_BREAKOUT_N, vol_mult=config.MOM_VOL_MULT,
              rev_rsi=config.REV_RSI, bb_max_position=config.REV_BB_MAX_POSITION)


def analyse(df, tf="15m"):
    """The production analyzer pipeline without I/O: indicators → regime → setup → levels."""
    d = TA._calculate_indicators(df.copy())
    condition = str(classify_regime(d)["condition"])
    tt, _, feats = detect_trade_setup(d, market_condition=condition, **PARAMS)
    levels = TA._calculate_levels(d, tf, tt)
    return d, condition, tt, levels


def test_production_parameters_are_the_documented_ones():
    assert (config.MOM_BREAKOUT_N, config.MOM_VOL_MULT, config.REV_RSI,
            config.REV_BB_MAX_POSITION) == (20, 1.2, 35.0, 0.20)
    assert indicator_warmup_bars() == 200 == config.CANDLES_TO_FETCH


# ── parity: the explanation never disagrees with production ─────────────────

def test_explanation_matches_detect_trade_setup_on_600_random_frames():
    decided = {"momentum": 0, "reversion": 0, None: 0}
    for seed in range(120):
        d = TA._calculate_indicators(syn.random_walk(seed=seed))
        for mc in (None, "bullish", "bearish", "sideways", "volatile"):
            want = detect_trade_setup(d, market_condition=mc, **PARAMS)[0]
            got = explain_setups(d, market_condition=mc, **PARAMS)
            assert got["decision"] == want, (seed, mc)
            decided[want] += 1
    assert decided["momentum"] > 20 and decided["reversion"] > 0      # non-vacuous


# ── scenarios 1–24 ─────────────────────────────────────────────────────────

def test_01_persistent_uptrend_is_bullish_and_breaks_out():
    d, cond, tt, lv = analyse(syn.breakout())
    assert cond == "bullish" and tt == "momentum" and lv["stop_valid"]
    ex = explain_setups(d, market_condition=cond, **PARAMS)["momentum"]
    assert ex.passed and [c.name for c in ex.conditions][-1] == "volume_confirmation"


def test_02_persistent_downtrend_never_buys_momentum():
    d, cond, tt, _ = analyse(syn.frame(syn.trend(drift=-0.004)))
    assert cond == "bearish" and tt is None
    assert explain_setups(d, market_condition=cond, **PARAMS)["momentum"].first_failure == "regime_bullish"


def test_03_sideways_never_buys_momentum():
    d, cond, tt, _ = analyse(syn.sideways())
    assert cond == "sideways" and tt != "momentum"


def test_04_clean_breakout_has_floor_stop_and_unit_risk():
    d, cond, tt, lv = analyse(syn.breakout(extension=0.001))
    g = setup_geometry(d, lv, tt)
    assert tt == "momentum" and 0 < g.extension_atr <= 0.75
    assert g.stop_anchor == "atr_floor" and g.risk_atr == pytest.approx(1.0, abs=1e-6)


def _replay(lv, path, tf="15m"):
    bars = [Bar(syn.T0 + 10**10 + i * syn.STEP[tf], *ohlc) for i, ohlc in enumerate(path)]
    return replay_bracket(trade_type="momentum", planned_entry=lv["entry"], stop_loss=lv["stop"],
                          target_1=lv["t1"], target_2=lv["t2"], target_3=lv["t3"],
                          invalidation_price=lv["stop_invalidation"], signal_timeframe=tf,
                          bars=bars, bar_timeframe=tf, decision_ms=syn.T0 + 10**10)


def test_05_false_breakout_closes_back_below_the_level_and_is_invalidated():
    d, cond, tt, lv = analyse(syn.breakout(extension=0.004))
    inv = lv["stop_invalidation"]
    assert candle_invalidated(opened_ms=1, candle_close_ms=2, candle_close=inv * 0.999,
                              invalidation_price=inv, highest_target=0)
    e = lv["entry"]
    out = _replay(lv, [(e, e * 1.001, e * 0.997, e * 0.998), (e * 0.998, e * 0.999, lv["stop"] * 0.99, lv["stop"])])
    assert out.status == "closed" and out.exit_reason == "stop_loss" and out.net_pct < 0


def test_06_breakout_then_reversal_hits_the_stop_before_any_target():
    d, cond, tt, lv = analyse(syn.breakout())
    e, s = lv["entry"], lv["stop"]
    out = _replay(lv, [(e, e * 1.002, s * 0.995, s * 0.996)])
    assert (out.exit_reason, out.target_reached) == ("stop_loss", 0)


def test_07_momentum_exhaustion_is_measured_as_extension():
    d, cond, tt, lv = analyse(syn.breakout(extension=0.03))
    g = setup_geometry(d, lv, tt)
    if tt == "momentum" and lv["stop_valid"]:
        assert g.extension_atr > 0.75 and g.stop_anchor == "structure" and g.risk_atr > 1.0
        assert "extended_entry" in g.flags
        verdict = ExtensionCap().evaluate(g)
        assert verdict.would_allow is False and verdict.allow is True          # disabled: shadow only
    else:                                                                       # or the 2 % 15m cap rejected it
        assert lv["stop_reject_reason"] == "structural_risk_exceeds_cap"


@pytest.mark.parametrize("label,expect_high", [("expansion", True), ("contraction", False)])
def test_08_09_volatility_expansion_and_contraction(label, expect_high):
    rng = np.random.default_rng(5)
    steps = rng.normal(0, 0.002, 200)
    if label == "expansion":
        steps[-8:] = 0.04 * np.array([1, -1] * 4)
    else:
        steps[-40:] *= 0.1
    d = TA._calculate_indicators(syn.frame(100 * np.exp(np.cumsum(steps)), wick=0.004))
    r = classify_regime(d)
    assert (r["atr_percentile_100"] > 0.75) is expect_high
    if expect_high:
        assert r["condition"] == "volatile" and detect_trade_setup(d, market_condition="volatile", **PARAMS)[0] is None


def test_10_volume_spike_without_price_confirmation():
    c = syn.trend()
    c[-1] = c[-21:-1].max() * 0.995                          # below the level
    v = np.full(200, 1000.0); v[-1] = 5000.0
    d, cond, tt, _ = analyse(syn.frame(c, volume=v))
    ex = explain_setups(d, market_condition=cond, **PARAMS)["momentum"]
    assert tt != "momentum" and ex.first_failure in ("breakout_above_prior_high", "close_above_ema20")
    assert {c.name: c.passed for c in ex.conditions}["volume_confirmation"] is True


def _cand(spread, risk=1.0):
    return normalize({"symbol": "THINUSDT", "timeframe": "15m", "trade_type": "momentum",
                      "stop_valid": True, "order_book": {"valid": True, "spread_pct": spread},
                      "entry_price": 100, "stop_loss": 100 - risk, "target_1": 100 + risk})


def test_11_12_thin_liquidity_and_spread_widening_are_rejected_by_eligibility():
    assert eligibility_reasons(_cand(0.05), EligibilityPolicy()) == ()
    assert eligibility_reasons(_cand(0.40), EligibilityPolicy()) == ("spread_exceeds_limit",)
    thin = normalize({"symbol": "T", "timeframe": "15m", "trade_type": "momentum",
                      "order_book": {"valid": False, "spread_pct": None}})
    assert eligibility_reasons(thin, EligibilityPolicy()) == ("order_book_unavailable",)


def test_13_15_16_missing_out_of_order_and_duplicate_candles_are_refused():
    base = syn.breakout()
    cases = {"missing": base.drop(base.index[100]),
             "out_of_order": base.iloc[list(range(150)) + [151, 150] + list(range(152, 200))],
             "duplicate": pd.concat([base.iloc[:100], base.iloc[99:]])}
    for name, df in cases.items():
        with pytest.raises(ValueError):
            validate_ohlcv(df, "15m")
        assert not validate_indicator_frame(TA._calculate_indicators(df.copy()), "15m").valid, name


def test_14_incomplete_candle_is_dropped_before_analysis():
    step = syn.STEP["15m"]
    rows = [[syn.T0 + i * step, 1, 1, 1, 1, 1, syn.T0 + (i + 1) * step - 1] + [0] * 5 for i in range(3)]
    now = syn.T0 + 2 * step + 60_000                         # third candle still open
    assert [r[0] for r in closed_klines(rows, now_ms=now)] == [syn.T0, syn.T0 + step]
    assert len(prepare_ohlcv(rows, "15m", now_ms=now)) == 2


def test_17_timeframe_mismatch_is_refused():
    df = syn.breakout()                                      # 15m bars
    with pytest.raises(ValueError):
        validate_ohlcv(df, "4h")
    with pytest.raises(IdentityError):
        candle_bounds(df, "4h")


def test_18_resistance_close_to_entry_caps_t1_and_names_its_source():
    """Production caps T1 at 0.99 × the 20-bar high only when that high lies between entry/0.99
    and 1R. For a momentum bar the 20-bar high is the breakout bar's own high, so the cap fires
    exactly when the bar's upper wick is between ~1.01 % and the risk distance."""
    base = syn.breakout(extension=0.03, drift=0.006)                 # wide structural risk
    d, cond, tt, lv = analyse(base, "4h")                            # 4h stop cap 5 %
    risk = lv["stop_risk_pct"] / 100
    assert tt == "momentum" and lv["stop_valid"] and risk > 0.0125
    upper = (0.0102 + risk) / 2                                      # wick inside the cap window
    d, cond, tt, lv = analyse(syn.breakout(extension=0.03, drift=0.006, upper=upper), "4h")
    g = setup_geometry(d, lv, tt)
    assert tt == "momentum" and g.t1_r < 1.0 and g.t1_cap_source == "current_bar"
    assert "t1_capped_by_own_breakout_bar" in g.flags
    d2, _, tt2, lv2 = analyse(syn.breakout(extension=0.03, drift=0.006, upper=risk * 1.5), "4h")
    assert setup_geometry(d2, lv2, tt2).t1_cap_source == "none"     # wick beyond 1R: no cap


def test_19_stop_distance_below_transaction_costs_is_flagged():
    c = 100 * np.exp(np.cumsum(0.0004 + np.random.default_rng(3).normal(0, 0.0001, 200)))
    c[-1] = c[-21:-1].max() * 1.0004
    v = np.full(200, 1000.0); v[-1] = 3000.0
    d, cond, tt, lv = analyse(syn.frame(c, volume=v, wick=0.0002))
    g = setup_geometry(d, lv, tt or "momentum")
    assert g.risk_pct < 0.2 and g.cost_over_risk > 1.0 and "cost_exceeds_risk" in g.flags


def test_20_gap_through_stop_fills_at_the_open():
    d, cond, tt, lv = analyse(syn.breakout())
    e, s = lv["entry"], lv["stop"]
    out = _replay(lv, [(e, e * 1.001, e * 0.999, e), (s * 0.95, s * 0.96, s * 0.94, s * 0.95)])
    assert out.exit_price == pytest.approx(s * 0.95 * 0.999) and out.net_pct < -(lv["stop_risk_pct"])


def test_21_multiple_correlated_signals_hit_the_exposure_cap_in_shadow():
    p = CorrelatedExposurePolicy()
    v = p.evaluate([Exposure("AAAUSDT", 50, 1.3)], Exposure("BBBUSDT", 50, 1.2))
    assert v.would_allow is False and v.allow is True


def test_22_regime_transition_switches_the_eligible_setup():
    up = TA._calculate_indicators(syn.breakout())
    assert str(classify_regime(up)["condition"]) == "bullish"
    up_then_down = np.r_[syn.trend(140), syn.trend(140)[-1] * syn.trend(60, drift=-0.005, seed=9) / 100]
    d = TA._calculate_indicators(syn.frame(up_then_down))
    cond = str(classify_regime(d)["condition"])
    assert cond != "bullish"
    assert explain_setups(d, market_condition=cond, **PARAMS)["momentum"].first_failure == "regime_bullish"


def test_23_indicator_warmup_boundary():
    df = syn.breakout(n=200)
    rep = validate_indicator_frame(TA._calculate_indicators(df.copy()), "15m")
    assert rep.valid and any(n.startswith("ema200:seed_weight=") for n in rep.notes)   # inactive EMA200
    assert ema_seed_weight(200, 200) == pytest.approx((1 - 2 / 201) ** 199)
    assert ema_seed_weight(50, 200) < 1e-3 and ema_seed_weight(20, 200) < 1e-3
    short = TA._calculate_indicators(syn.breakout(n=90).copy())
    rep_short = validate_indicator_frame(short, "15m")
    assert not rep_short.valid
    with pytest.raises(ValueError, match="insufficient"):
        classify_regime(short)


def test_24_nonfinite_indicator_values_fail_closed():
    d = TA._calculate_indicators(syn.breakout().copy())
    d.loc[d.index[-1], "ema20"] = float("nan")
    ex = explain_setups(d, market_condition="bullish", **PARAMS)["momentum"]
    assert ex.first_failure == "close_above_ema20"
    assert detect_trade_setup(d, market_condition="bullish", **PARAMS)[0] is None
    assert "regime:ema20:non_finite_last" in validate_indicator_frame(d, "15m").issues
    bad = setup_geometry(d.assign(atr=float("nan")), {"entry": 100, "stop": 99, "t1": 101}, "momentum")
    assert bad.stop_anchor == "invalid" and "invalid_inputs" in bad.flags


# ── hypothesis specifications stay disabled ────────────────────────────────

def test_hypotheses_are_disabled_versioned_and_fail_closed_when_enabled():
    for policy in (MarketStateGate(), ExtensionCap(), SeasonalVolumeConfirmation()):
        assert policy.enabled is False and policy.version.startswith("a45-h")
    assert MarketStateGate().evaluate("momentum", -1.0).allow is True
    assert MarketStateGate(enabled=True).evaluate("momentum", -1.0).reasons == ("market_trend_negative",)
    assert MarketStateGate(enabled=True).evaluate("momentum", None).reasons == ("market_state_unavailable",)
    assert MarketStateGate(enabled=True).evaluate("reversion", -9).allow is True
    long = syn.frame(syn.trend(n=20 * 96 + 5, drift=0.0002), volume=np.full(20 * 96 + 5, 1000.0))
    sv = SeasonalVolumeConfirmation(enabled=True)
    assert sv.baseline(long, "15m") == pytest.approx(1000.0)
    assert sv.evaluate(long, "15m", "momentum").reasons == ("volume_not_above_slot_baseline",)
    assert sv.evaluate(long.iloc[-100:], "15m", "momentum").reasons == ("slot_history_insufficient",)
    assert math.isnan(sv.baseline(long, "1d"))


def test_no_production_module_imports_setup_diagnostics():
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    pat = re.compile(r"(from\s+shared(\.|\s+import\s+[^\n]*\b)|import\s+shared\.)setup_diagnostics\b")
    assert [str(p) for p in root.rglob("*.py") if "tests" not in p.parts
            and p.stem != "setup_diagnostics" and pat.search(p.read_text(errors="ignore"))] == []


def test_extension_boundary_of_the_production_stop_is_0_75_atr():
    """R = max(extension + 0.25, 1) ATR: below 0.75 ATR of extension the stop is the 1-ATR floor,
    above it the structural level − 0.25 ATR — H2's cap is this boundary, not a fitted value."""
    from shared.signal_stop import plan_signal_stop
    atr, level = 1.0, 100.0
    for ext in (0.0, 0.25, 0.5, 0.74, 0.76, 1.0, 2.0, 3.0):
        p = plan_signal_stop(entry=level + ext, atr=atr, trade_type="momentum", structure_low=90,
                             breakout_level=level, max_risk_pct=0.5)
        risk_atr = (level + ext - p.stop_price) / atr
        assert risk_atr == pytest.approx(max(ext + 0.25, 1.0))
        assert (p.stop_price == pytest.approx(level - 0.25)) is (ext > 0.75)
