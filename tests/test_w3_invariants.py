"""W3 geometry invariants (STRATEGY_AND_EXECUTION_CONTRACT.md SE-40, SE-64; REMEDIATION_REGISTER R2).

Synthetic engineering tests over the T1_CAP_POLICY options of shared/t1_cap.py, with
shared/trade_geometry.py as the reference oracle. They prove geometry properties, not
profitability, and choose no option (SE-80) and no cost threshold.

1. Legacy byte-identity: under ``legacy_window_v1`` (and the pre-existing
   ``independent_swing_v1``) the analyzer and the t1_cap functions are byte-identical to the
   sources at ``BASE_COMMIT``, loaded from git (skips when git or the object is unavailable).
2. SE-03 reproduction (R2 test 2): under the legacy option every momentum reference is the
   decision bar's own high.
3. SE-40.1 independence (R2 test 1): under options a, b and c the reference never comes from the
   decision bar, and changing the decision bar's high never changes it.
4. SE-40.2 provenance, SE-40.3 fallback, SE-40.4 ordering (R2 test 3), SE-40.5 cost feasibility
   (R2 test 4, parametrised over the charter's PROPOSED research round trips only).
5. Fail closed on unknown policy values.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, '.'); sys.path.insert(0, 'analyzer'); sys.path.insert(0, 'tests')

import numpy as np
import pandas as pd
import pytest

import a45_synthetic as syn
from technical_analyzer import TechnicalAnalyzer
from simple_entry import detect_trade_setup
from shared import t1_cap
from shared.config import config
from shared.funnel_records import REASON_CODES, SE_NAME_MAP
from shared.signal_stop import plan_signal_stop
from shared.strategy_math import calculate_signal_levels
from shared.t1_cap import (INDEPENDENT_SWING_V1, LEGACY_WINDOW_V1, NO_CAP_V1, PRIOR_WINDOW_V1,
                           REASON_BRACKET_INVALID, REASON_T1_NOT_COST_FEASIBLE, T1_CAP_POLICIES,
                           T1_FALLBACK, T1_SOURCE_R_MULTIPLE_FALLBACK, T1_SOURCE_STRUCTURE,
                           bracket_reason, capped_t1, flat_round_trip_break_even,
                           prior_window_resistance, resistance_for, t1_cap_policy, t1_cost_reason,
                           t1_reference)
from shared.trade_geometry import independent_resistance, references, resistance_cap

REPO = Path(__file__).resolve().parents[1]
BASE_COMMIT = "6ae70a2"           # last commit before WP-D02
TA = TechnicalAnalyzer(None)
TFS = ("15m", "4h", "1d")
SETUPS = ("momentum", "reversion")
CORRECTED = (PRIOR_WINDOW_V1, INDEPENDENT_SWING_V1, NO_CAP_V1)       # SE-40 options a, b, c
# Charter CH:L25, PROPOSED research round trips (baseline, stress) in percent. Not a threshold
# chosen here: the check runs against each declared value (R2 test 4).
PROPOSED_RESEARCH_ROUND_TRIP_PCT = (0.40, 0.60)


def ind(df):
    return TA._calculate_indicators(df.copy())


def _frames():
    for seed in range(40):
        yield f"rw{seed}", ind(syn.random_walk(seed=seed))
    for seed in range(8):
        for ext in (0.001, 0.012, 0.03):
            for upper in (None, 0.004, 0.015):
                yield f"bo{seed}-{ext}-{upper}", ind(syn.breakout(extension=ext, drift=0.006,
                                                                  seed=seed, upper=upper))
    for seed in range(6):                                # downtrends: prior highs above entry
        yield f"dn{seed}", ind(syn.frame(syn.trend(drift=-0.003, seed=seed), seed=seed))


FRAMES = list(_frames())
MOMENTUM = [(n, df) for n, df in FRAMES if detect_trade_setup(df)[0] == "momentum"]


@pytest.fixture
def policy(monkeypatch):
    def set_(value):
        monkeypatch.setattr(config, "T1_CAP_POLICY", value, raising=False)
    return set_


_TF_RISK_CAP = {"1d": 0.03, "4h": 0.05, "1h": 0.04, "15m": 0.02}   # technical_analyzer._calculate_levels


_RISK_CACHE: dict = {}


def _risk(df, tf, tt):
    """Unrounded entry and risk as the analyzer computes them for a momentum or reversion setup
    (same plan_signal_stop call), checked against the rounded stop the analyzer returns. Cached
    per frame object (the frames are never mutated in place)."""
    key = (id(df), tf, tt)
    if key not in _RISK_CACHE:
        _RISK_CACHE[key] = (df, _risk_uncached(df, tf, tt))
    return _RISK_CACHE[key][1]


def _risk_uncached(df, tf, tt):
    lv = calculate_signal_levels(df, tf, tt)
    entry, atr = float(df["close"].iloc[-1]), float(df["atr"].iloc[-1])
    plan = plan_signal_stop(entry=entry, atr=atr, trade_type=tt,
                            structure_low=float(df.tail(20)["low"].min()),
                            breakout_level=float(df["high"].iloc[-21:-1].max()),
                            max_risk_pct=_TF_RISK_CAP[tf])
    assert round(plan.stop_price, 8) == lv["stop"]
    return entry, entry - plan.stop_price, lv


def _with_decision_high(df, high):
    out = df.copy()
    out.iloc[-1, out.columns.get_loc("high")] = high
    return out


# 0 ── registry ──────────────────────────────────────────────────────────────

def test_policy_registry_and_default():
    assert T1_CAP_POLICIES == (LEGACY_WINDOW_V1, INDEPENDENT_SWING_V1, PRIOR_WINDOW_V1, NO_CAP_V1)
    assert config.T1_CAP_POLICY == LEGACY_WINDOW_V1 == t1_cap_policy(config)
    assert len(set(T1_CAP_POLICIES)) == len(T1_CAP_POLICIES)


def test_reason_codes_are_canonical_funnel_codes():
    assert {REASON_BRACKET_INVALID, REASON_T1_NOT_COST_FEASIBLE} <= REASON_CODES
    assert SE_NAME_MAP["strategy.geometry/invalid_geometry"][1] == REASON_BRACKET_INVALID
    assert SE_NAME_MAP["strategy.geometry/t1_not_cost_feasible"][1] == REASON_T1_NOT_COST_FEASIBLE
    assert REASON_T1_NOT_COST_FEASIBLE != "F5.cost_above_budget"


# 1 ── legacy byte-identity against the BASE_COMMIT sources ─────────────────────

def _git_show(path):
    try:
        out = subprocess.run(["git", "show", f"{BASE_COMMIT}:{path}"], cwd=REPO, capture_output=True,
                             text=True, check=True, timeout=30)
    except Exception as exc:                                        # pragma: no cover
        pytest.skip(f"pre-D02 source unavailable ({BASE_COMMIT}:{path}): {exc}")
    return out.stdout


def _load(name, source, tmp_dir):
    target = tmp_dir / f"{name}.py"
    target.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, target)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def before(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("w3_before")
    old_cap = _load("tsb_d02_t1_cap_before", _git_show("shared/t1_cap.py"), tmp)
    current = sys.modules["shared.t1_cap"]
    sys.modules["shared.t1_cap"] = old_cap          # the old analyzer binds the old t1_cap names
    try:
        old_ta = _load("tsb_d02_technical_analyzer_before",
                       _git_show("analyzer/technical_analyzer.py"), tmp)
    finally:
        sys.modules["shared.t1_cap"] = current
    assert old_ta.resistance_for is old_cap.resistance_for
    return old_cap, old_ta.TechnicalAnalyzer(None)


@pytest.mark.parametrize("pol", [LEGACY_WINDOW_V1, INDEPENDENT_SWING_V1])
def test_levels_byte_identical_to_base_commit(before, policy, pol):
    _, old_ta = before
    policy(pol)
    n = 0
    for name, df in FRAMES:
        for tf in TFS:
            for tt in SETUPS + (None,):
                old, new = old_ta._calculate_levels(df, tf, tt), TA._calculate_levels(df, tf, tt)
                assert repr(new) == repr(old), (name, tf, tt)
                n += 1
    assert n == len(FRAMES) * len(TFS) * 3


def test_t1_cap_functions_byte_identical_to_base_commit(before):
    old_cap, _ = before
    assert old_cap.T1_CAP_POLICIES == T1_CAP_POLICIES[:2]
    assert (old_cap.RESISTANCE_FILL, old_cap.WINDOW) == (t1_cap.RESISTANCE_FILL, t1_cap.WINDOW)
    for name, df in FRAMES:
        entry = float(df["close"].iloc[-1])
        assert repr(old_cap.legacy_window_resistance(df)) == repr(t1_cap.legacy_window_resistance(df))
        assert repr(old_cap.independent_swing_resistance(df, entry)) == \
            repr(t1_cap.independent_swing_resistance(df, entry))
        for pol in old_cap.T1_CAP_POLICIES:
            for tt in SETUPS + (None,):
                assert repr(old_cap.resistance_for(df, entry, tt, pol)) == \
                    repr(resistance_for(df, entry, tt, pol)), (name, pol, tt)
        for risk in (0.0, entry * 0.004, entry * 0.02, entry * 0.05):
            for res in (None, entry * 0.99, entry, entry * 1.005, entry * 1.02, float("nan")):
                assert repr(old_cap.capped_t1(entry, risk, res)) == repr(capped_t1(entry, risk, res))


def test_default_rows_carry_no_new_key(policy):
    policy(LEGACY_WINDOW_V1)
    for _, df in FRAMES[:5]:
        assert "t1_cap_policy" not in TA._calculate_levels(df, "4h", "momentum")


# 2 ── SE-03: the legacy option reproduces W3 exactly (R2 test 2) ────────────────

def test_legacy_reference_is_the_decision_bars_own_high_for_every_momentum_signal():
    assert len(MOMENTUM) >= 70
    for name, df in MOMENTUM:
        for tf in TFS:
            entry, risk, lv = _risk(df, tf, "momentum")
            ref = t1_reference(df, entry, risk, "momentum", LEGACY_WINDOW_V1)
            decision_high = float(df["high"].iloc[-1])
            assert ref.value == decision_high and ref.bar_offset == 0, name
            assert ref.bar_close_time == int(df["close_time"].iloc[-1])
            assert references(df).window_high_is_decision_bar               # oracle agrees
            assert round(capped_t1(entry, risk, decision_high), 8) == lv["t1"]


def test_legacy_reference_moves_with_the_decision_bars_high():
    _, df = MOMENTUM[0]
    entry = float(df["close"].iloc[-1])
    seen = {resistance_for(_with_decision_high(df, entry * k), entry, "momentum", LEGACY_WINDOW_V1)
            for k in (1.001, 1.01, 1.05)}
    assert len(seen) == 3                                    # the self-reference (the defect)


# 3 ── SE-40.1 independence (R2 test 1) ─────────────────────────────────────────

@pytest.mark.parametrize("pol", CORRECTED)
def test_reference_never_comes_from_the_decision_bar(pol):
    for name, df in FRAMES:
        decision_close_time = int(df["close_time"].iloc[-1])
        for tt in SETUPS:
            for tf in TFS:
                entry, risk, _ = _risk(df, tf, tt)
                ref = t1_reference(df, entry, risk, tt, pol)
                assert (ref.value is None) == (ref.bar_offset is None) == (ref.bar_close_time is None)
                if ref.bar_offset is not None:
                    assert ref.bar_offset >= 1, (name, pol, tt)
                    assert ref.bar_close_time < decision_close_time
                    assert float(df["high"].iloc[-1 - ref.bar_offset]) == ref.value


@pytest.mark.parametrize("pol", CORRECTED)
@pytest.mark.parametrize("factor", [1.0, 1.0005, 1.004, 1.012, 1.05, 1.5, 3.0])
def test_changing_the_decision_bars_high_never_changes_the_reference(pol, factor):
    for name, df in FRAMES:
        entry = float(df["close"].iloc[-1])
        floor = max(entry, float(df["open"].iloc[-1]))
        for tt in SETUPS:
            base = resistance_for(df, entry, tt, pol)
            moved = resistance_for(_with_decision_high(df, floor * factor), entry, tt, pol)
            assert repr(moved) == repr(base), (name, pol, tt, factor)


def test_options_match_the_trade_geometry_oracle():
    for name, df in FRAMES:
        entry = float(df["close"].iloc[-1])
        refs = references(df)
        for tt in SETUPS:
            assert resistance_for(df, entry, tt, PRIOR_WINDOW_V1) == refs.breakout_level, name
            assert resistance_for(df, entry, tt, INDEPENDENT_SWING_V1) == independent_resistance(df, entry)
            assert resistance_for(df, entry, tt, NO_CAP_V1) is None
        assert resistance_for(df, entry, None, PRIOR_WINDOW_V1) == refs.window_high
        for risk in (entry * 0.004, entry * 0.03):
            for pol in T1_CAP_POLICIES:
                res = resistance_for(df, entry, "momentum", pol)
                assert capped_t1(entry, risk, res) == resistance_cap(entry, risk, res)


def test_option_a_equals_option_c_for_momentum(policy):
    """SE-40 table: for a breakout the prior-window max is below entry, so option a never binds."""
    for name, df in MOMENTUM:
        entry = float(df["close"].iloc[-1])
        assert prior_window_resistance(df) < entry, name
        for tf in TFS:
            policy(PRIOR_WINDOW_V1)
            a = TA._calculate_levels(df, tf, "momentum")
            policy(NO_CAP_V1)
            c = TA._calculate_levels(df, tf, "momentum")
            assert a["t1_cap_policy"] == PRIOR_WINDOW_V1 and c["t1_cap_policy"] == NO_CAP_V1
            assert {k: v for k, v in a.items() if k != "t1_cap_policy"} == \
                {k: v for k, v in c.items() if k != "t1_cap_policy"}
            e, risk, _ = _risk(df, tf, "momentum")
            assert a["t1"] == round(e + risk, 8)


def test_option_b_momentum_reference_is_older_than_the_breakout_window():
    """SE-40 table: a qualifying swing high for a breakout lies more than 20 bars back."""
    highs = [99.0] * 59 + [101.5]                         # decision bar last
    highs[10] = 105.0                                     # confirmed swing high, old
    highs[-2] = 100.0
    df = pd.DataFrame({"high": highs, "close": [98.5] * 59 + [101.0],
                       "close_time": np.arange(60) * 1000 + 999})
    assert 101.0 > max(df["high"].iloc[-21:-1])           # momentum breakout geometry
    ref = t1_reference(df, 101.0, 6.0, "momentum", INDEPENDENT_SWING_V1)
    assert ref.value == 105.0 and ref.bar_offset == len(df) - 1 - 10 and ref.bar_offset > 20
    assert ref.t1_source == T1_SOURCE_STRUCTURE and ref.t1 == pytest.approx(105.0 * 0.99)
    for name, df in MOMENTUM:
        entry = float(df["close"].iloc[-1])
        ref = t1_reference(df, entry, entry * 0.05, "momentum", INDEPENDENT_SWING_V1)
        assert ref.bar_offset is None or ref.bar_offset > 20, name


# 4 ── SE-40.2 provenance and SE-40.3 fallback ───────────────────────────────────

@pytest.mark.parametrize("pol", T1_CAP_POLICIES)
def test_provenance_fields_are_set_and_t1_equals_the_analyzer(policy, pol):
    policy(pol)
    for name, df in FRAMES:
        for tf in TFS:
            for tt in SETUPS:
                entry, risk, _ = _risk(df, tf, tt)
                lv = TA._calculate_levels(df, tf, tt)
                ref = t1_reference(df, entry, risk, tt, pol)
                assert ref.policy == pol and ref.fallback == T1_FALLBACK
                assert ref.t1_source in (T1_SOURCE_STRUCTURE, T1_SOURCE_R_MULTIPLE_FALLBACK)
                assert ref.t1 == capped_t1(entry, risk, resistance_for(df, entry, tt, pol))
                assert round(ref.t1, 8) == lv["t1"], (name, tf, tt, pol)
                if ref.t1_source == T1_SOURCE_STRUCTURE:
                    assert ref.value is not None and ref.t1 == ref.value * t1_cap.RESISTANCE_FILL
                    assert entry < ref.t1 < entry + risk
                else:
                    assert ref.t1 == entry + risk
                assert (pol == LEGACY_WINDOW_V1) == ("t1_cap_policy" not in lv)
                if pol != LEGACY_WINDOW_V1:
                    assert lv["t1_cap_policy"] == pol


def test_no_cap_option_always_takes_the_declared_fallback():
    for name, df in FRAMES:
        entry = float(df["close"].iloc[-1])
        for tt in SETUPS:
            ref = t1_reference(df, entry, entry * 0.03, tt, NO_CAP_V1)
            assert (ref.value, ref.bar_offset, ref.bar_close_time) == (None, None, None)
            assert ref.t1_source == T1_SOURCE_R_MULTIPLE_FALLBACK and ref.t1 == entry + entry * 0.03


@pytest.mark.parametrize("pol", CORRECTED)
def test_no_admissible_reference_above_entry_falls_back_to_1r(pol):
    df = pd.DataFrame({"high": [99.0 + 0.01 * i for i in range(40)] + [100.2],
                       "close_time": np.arange(41) * 1000 + 999})
    ref = t1_reference(df, 100.0, 2.0, "momentum", pol)
    assert ref.t1 == 102.0 and ref.t1_source == T1_SOURCE_R_MULTIPLE_FALLBACK


def test_short_and_non_finite_histories_fall_back_cleanly():
    tiny = pd.DataFrame({"high": [100.5]})
    assert prior_window_resistance(tiny) is None
    for pol in CORRECTED:
        ref = t1_reference(tiny, 100.0, 1.0, "momentum", pol)
        assert ref.t1 == 101.0 and ref.value is None and ref.bar_close_time is None
    nan = pd.DataFrame({"high": [float("nan")] * 25 + [100.5]})
    assert prior_window_resistance(nan) is None
    assert t1_reference(nan, 100.0, 1.0, "reversion", PRIOR_WINDOW_V1).t1 == 101.0


# 5 ── SE-40.4 ordering and R2 test 3 bracket invariants ────────────────────────

@pytest.mark.parametrize("pol", T1_CAP_POLICIES)
def test_bracket_ordering_holds_for_every_option(policy, pol):
    checked = 0
    for name, df in FRAMES:
        for tf in TFS:
            for tt in SETUPS:
                policy(LEGACY_WINDOW_V1)
                legacy = TA._calculate_levels(df, tf, tt)
                policy(pol)
                lv = TA._calculate_levels(df, tf, tt)
                if not lv["stop_valid"]:
                    continue
                one_r = round(lv["entry"] + (lv["entry"] - lv["stop"]), 8)
                assert bracket_reason(lv["stop"], lv["entry"], lv["t1"], lv["t2"], lv["t3"]) is None
                assert lv["stop"] < lv["entry"] < lv["t1"] <= one_r + 2e-8, (name, tf, tt, pol)
                for k in ("entry", "stop", "t2", "t3", "stop_valid", "stop_policy"):
                    assert lv[k] == legacy[k], (name, tf, tt, pol, k)       # the cap moves T1 only
                checked += 1
    assert checked > 300


@pytest.mark.parametrize("prices", [
    (99.0, 100.0, 100.0, 101.8, 102.2),        # T1 at entry
    (99.0, 100.0, 99.5, 101.8, 102.2),         # T1 below entry
    (100.0, 100.0, 101.0, 101.8, 102.2),       # stop at entry
    (99.0, 100.0, 101.9, 101.8, 102.2),        # T1 above T2
    (99.0, 100.0, 101.0, 102.2, 102.2),        # T2 equals T3
    (99.0, 100.0, float("nan"), 101.8, 102.2),
    (99.0, 100.0, 101.0, float("inf"), 102.2),
])
def test_bracket_violations_are_rejected_with_the_canonical_code(prices):
    assert bracket_reason(*prices) == REASON_BRACKET_INVALID


def test_valid_bracket_passes():
    assert bracket_reason(99.0, 100.0, 101.0, 101.8, 102.2) is None


# 6 ── SE-40.5 cost feasibility (R2 test 4: parametrised, no threshold chosen) ─────

@pytest.mark.parametrize("round_trip_pct", PROPOSED_RESEARCH_ROUND_TRIP_PCT)
@pytest.mark.parametrize("pol", T1_CAP_POLICIES)
def test_cost_feasibility_is_evaluated_for_every_option(round_trip_pct, pol):
    for name, df in FRAMES:
        for tf in TFS:
            for tt in SETUPS:
                entry, risk, _ = _risk(df, tf, tt)
                ref = t1_reference(df, entry, risk, tt, pol)
                be = flat_round_trip_break_even(entry, round_trip_pct)
                expected = None if ref.t1 > be else REASON_T1_NOT_COST_FEASIBLE
                assert t1_cost_reason(ref.t1, be) == expected, (name, tf, tt, pol)
                gain_pct = (ref.t1 - entry) / entry * 100.0
                if abs(gain_pct - round_trip_pct) > 1e-9:
                    assert (expected is None) == (gain_pct > round_trip_pct)


def test_cost_feasibility_boundary_is_strict():
    be = flat_round_trip_break_even(100.0, 0.40)
    assert be == pytest.approx(100.4)
    assert t1_cost_reason(be, be) == REASON_T1_NOT_COST_FEASIBLE        # at break-even: not above
    assert t1_cost_reason(be * (1 + 1e-9), be) is None
    assert flat_round_trip_break_even(100.0, 0) == 100.0


def test_legacy_cap_can_put_t1_below_break_even_and_option_a_does_not():
    """The STR-21 mechanism on one synthetic breakout: an upper wick of about 1.1 % of entry
    caps T1 below a 0.40 % round trip under the legacy option only."""
    df = ind(syn.breakout(extension=0.03, drift=0.006, upper=0.011))
    tf, entry = "4h", float(df["close"].iloc[-1])
    _, risk, _ = _risk(df, tf, "momentum")
    assert risk > entry * 0.011                         # 1R lies above the wick: the cap binds
    be = flat_round_trip_break_even(entry, PROPOSED_RESEARCH_ROUND_TRIP_PCT[0])
    legacy = t1_reference(df, entry, risk, "momentum", LEGACY_WINDOW_V1)
    assert legacy.t1_source == T1_SOURCE_STRUCTURE and legacy.bar_offset == 0
    assert t1_cost_reason(legacy.t1, be) == REASON_T1_NOT_COST_FEASIBLE
    for pol in (PRIOR_WINDOW_V1, NO_CAP_V1):
        assert t1_cost_reason(t1_reference(df, entry, risk, "momentum", pol).t1, be) is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, True, "0.4", None])
def test_break_even_needs_an_explicit_finite_cost(bad):
    with pytest.raises(ValueError):
        flat_round_trip_break_even(100.0, bad)
    with pytest.raises(TypeError):
        flat_round_trip_break_even(100.0)                # no default cost


@pytest.mark.parametrize("bad", [float("nan"), True, None])
def test_cost_reason_rejects_non_finite_inputs(bad):
    with pytest.raises(ValueError):
        t1_cost_reason(bad, 100.4)
    with pytest.raises(ValueError):
        t1_cost_reason(101.0, bad)


# 7 ── fail closed ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["prior_window", "no_cap", "nocap_v1", "prior-window-v1",
                                 "legacy_window_v2", "none", "a", "c"])
def test_unknown_policy_refuses_everywhere(policy, bad):
    df = FRAMES[0][1]
    policy(bad)
    with pytest.raises(RuntimeError, match="unknown T1_CAP_POLICY"):
        t1_cap_policy(config)
    with pytest.raises(RuntimeError, match="unknown T1_CAP_POLICY"):
        TA._calculate_levels(df, "4h", "momentum")
    with pytest.raises(RuntimeError, match="unknown T1_CAP_POLICY"):
        resistance_for(df, 100.0, "momentum", bad)
    with pytest.raises(RuntimeError, match="unknown T1_CAP_POLICY"):
        t1_reference(df, 100.0, 1.0, None, bad)
    with pytest.raises(RuntimeError, match="unknown T1_CAP_POLICY"):
        calculate_signal_levels(df, "4h", "momentum", t1_cap_policy=bad)


@pytest.mark.parametrize("raw,expected", [(" Prior_Window_V1 ", PRIOR_WINDOW_V1),
                                          ("NO_CAP_V1", NO_CAP_V1)])
def test_new_policies_parse_case_and_space_insensitively(policy, raw, expected):
    policy(raw)
    assert t1_cap_policy(config) == expected


@pytest.mark.parametrize("pol", CORRECTED)
def test_legacy_trade_type_path_is_unchanged_by_every_option(policy, pol):
    for name, df in FRAMES[:20]:
        policy(LEGACY_WINDOW_V1)
        base = TA._calculate_levels(df, "4h", None)
        policy(pol)
        lv = TA._calculate_levels(df, "4h", None)
        assert {k: v for k, v in lv.items() if k != "t1_cap_policy"} == base, name
