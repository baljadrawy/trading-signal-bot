"""T1 resistance-cap policy (shared/t1_cap.py): synthetic engineering tests, not profitability.

1. Default behaviour is byte-identical to main@1432a90 (frozen copy below), in both the analyzer
   and the strategy_math research copy.
2. Regression for the A45 W3 / A46 defect: under the default, a momentum breakout's own upper
   wick caps T1; under ``independent_swing_v1`` it does not.
3. ``independent_swing_v1`` equals A46 G1 (``trade_geometry.g1_bracket``) everywhere.
4. Unknown policies fail closed, at startup and per call.
"""
import ast
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'analyzer'); sys.path.insert(0, 'tests')

import pandas as pd
import pytest

import a45_synthetic as syn
from technical_analyzer import TechnicalAnalyzer
from shared.config import config
from shared.signal_stop import plan_signal_stop
from shared.strategy_math import calculate_signal_levels
from shared.t1_cap import (INDEPENDENT_SWING_V1, LEGACY_WINDOW_V1, NO_CAP_V1, PRIOR_WINDOW_V1,
                           T1_CAP_POLICIES, capped_t1,
                           independent_swing_resistance, legacy_window_resistance, resistance_for,
                           t1_cap_policy)
from shared.trade_geometry import baseline_bracket, g1_bracket, independent_resistance

TA = TechnicalAnalyzer(None)
TFS = ("15m", "4h", "1d")
TYPES = ("momentum", "reversion", None)


def ind(df):
    return TA._calculate_indicators(df.copy())


def _main_1432a90_levels(df, timeframe, trade_type, *, breakout_n=20):
    """Frozen verbatim copy of shared/strategy_math.calculate_signal_levels at main@1432a90."""
    last = df.iloc[-1]; atr = float(last["atr"]); entry = float(last["close"])
    recent = df.tail(20); support = float(recent["low"].min()); resistance = float(recent["high"].max())
    stop_loss = max(entry - atr * 1.5, support * 0.99)
    if stop_loss >= entry: stop_loss = entry * 0.97
    caps = {"1d": 0.03, "4h": 0.05, "1h": 0.04, "15m": 0.02}
    cap = caps.get(timeframe, 0.04)
    policy, invalidation, valid, reject = "legacy_atr_support", stop_loss, True, None
    if trade_type in ("momentum", "reversion"):
        breakout = float(df["high"].iloc[-(breakout_n + 1):-1].max())
        plan = plan_signal_stop(entry=entry, atr=atr, trade_type=trade_type,
                                structure_low=support, breakout_level=breakout,
                                max_risk_pct=cap)
        stop_loss, policy, invalidation, valid, reject = (plan.stop_price, plan.policy,
                                                          plan.invalidation_price,
                                                          plan.valid, plan.reason)
    elif entry - stop_loss > entry * cap:
        stop_loss = entry - entry * cap
    risk = entry - stop_loss
    t1, t2, t3 = entry + risk, entry + risk * 1.8, entry + risk * 2.2
    if t1 > resistance > entry:
        capped = resistance * 0.99
        if capped > entry: t1 = capped
    return {"entry": round(entry, 8), "stop": round(stop_loss, 8),
            "stop_policy": policy, "stop_invalidation": round(invalidation, 8),
            "stop_risk_pct": round((entry - stop_loss) / entry * 100, 4),
            "stop_valid": valid, "stop_reject_reason": reject,
            "t1": round(t1, 8), "t2": round(t2, 8), "t3": round(t3, 8)}


def _frames():
    for seed in range(40):
        yield f"rw{seed}", ind(syn.random_walk(seed=seed))
    for seed in range(8):
        for ext in (0.001, 0.012, 0.03):
            for upper in (None, 0.004, 0.015):
                yield f"bo{seed}-{ext}-{upper}", ind(syn.breakout(extension=ext, drift=0.006,
                                                                  seed=seed, upper=upper))


def _capped_case():
    probe = baseline_bracket(ind(syn.breakout(extension=0.03, drift=0.006)), "4h", "momentum")
    risk = probe.risk / probe.entry
    return ind(syn.breakout(extension=0.03, drift=0.006, upper=(0.0102 + risk) / 2))


@pytest.fixture
def policy(monkeypatch):
    def set_(value):
        monkeypatch.setattr(config, "T1_CAP_POLICY", value, raising=False)
    return set_


# 1 ── default = exact current behaviour ────────────────────────────────────

def test_default_policy_is_legacy():
    assert config.T1_CAP_POLICY == LEGACY_WINDOW_V1 and t1_cap_policy(config) == LEGACY_WINDOW_V1


def test_default_analyzer_and_strategy_math_equal_frozen_main(policy):
    policy(LEGACY_WINDOW_V1)
    n = 0
    for name, df in _frames():
        for tf in TFS:
            for tt in TYPES:
                frozen = _main_1432a90_levels(df, tf, tt)
                assert TA._calculate_levels(df, tf, tt) == frozen, (name, tf, tt)
                assert calculate_signal_levels(df, tf, tt) == frozen, (name, tf, tt)
                n += 1
    assert n == (40 + 72) * 3 * 3


def test_default_rows_carry_no_new_key(policy):
    policy(LEGACY_WINDOW_V1)
    assert "t1_cap_policy" not in TA._calculate_levels(_capped_case(), "4h", "momentum")


# 2 ── regression: the decision bar no longer caps its own target ──────────────

def test_legacy_caps_t1_with_the_breakout_bars_own_wick(policy):
    df = _capped_case()
    policy(LEGACY_WINDOW_V1)
    lv = TA._calculate_levels(df, "4h", "momentum")
    one_r = round(lv["entry"] + (lv["entry"] - lv["stop"]), 8)
    assert legacy_window_resistance(df) == float(df["high"].iloc[-1])      # self-referential level
    assert lv["entry"] < lv["t1"] < one_r                                   # the defect
    assert lv["t1"] == pytest.approx(float(df["high"].iloc[-1]) * 0.99, abs=1e-8)


def test_independent_policy_ignores_the_decision_bar(policy):
    df = _capped_case()
    policy(INDEPENDENT_SWING_V1)
    lv = TA._calculate_levels(df, "4h", "momentum")
    assert independent_swing_resistance(df, lv["entry"]) is None
    assert lv["t1"] == pytest.approx(lv["entry"] + (lv["entry"] - lv["stop"]), abs=2e-8)
    assert lv["t1_cap_policy"] == INDEPENDENT_SWING_V1
    # everything except T1 (and the provenance key) is unchanged
    policy(LEGACY_WINDOW_V1)
    legacy = TA._calculate_levels(df, "4h", "momentum")
    assert {k: v for k, v in lv.items() if k not in ("t1", "t1_cap_policy")} == \
        {k: v for k, v in legacy.items() if k != "t1"}


def test_independent_policy_still_caps_at_a_prior_confirmed_swing_high():
    entry, risk = 100.0, 3.0
    highs = [99.0] * 30
    highs[20] = 102.0                                   # confirmed swing high, two lower bars each side
    df = pd.DataFrame({"high": highs + [100.5]})        # decision bar last
    assert independent_swing_resistance(df, entry) == 102.0
    assert capped_t1(entry, risk, 102.0) == pytest.approx(102.0 * 0.99)


def test_unconfirmed_or_below_entry_highs_never_qualify():
    entry = 100.0
    highs = [99.0] * 30
    highs[-2] = 105.0                                   # only one bar after it: not confirmed
    highs[10] = 99.5                                    # below entry
    df = pd.DataFrame({"high": highs + [100.0]})
    assert independent_swing_resistance(df, entry) is None
    highs[15] = float("nan")
    assert independent_swing_resistance(pd.DataFrame({"high": highs + [100.0]}), entry) is None


def test_legacy_trade_type_path_is_never_changed(policy):
    df = _capped_case()
    policy(INDEPENDENT_SWING_V1)
    lv = TA._calculate_levels(df, "4h", None)
    frozen = _main_1432a90_levels(df, "4h", None)
    assert {k: v for k, v in lv.items() if k != "t1_cap_policy"} == frozen
    assert resistance_for(df, 100.0, None, INDEPENDENT_SWING_V1) == legacy_window_resistance(df)


# 3 ── parity with A46 G1 ──────────────────────────────────────────────────

def test_independent_policy_equals_a46_g1_everywhere(policy):
    policy(INDEPENDENT_SWING_V1)
    checked = 0
    for name, df in _frames():
        for tf in TFS:
            for tt in ("momentum", "reversion"):
                lv = TA._calculate_levels(df, tf, tt)
                assert calculate_signal_levels(df, tf, tt, t1_cap_policy=INDEPENDENT_SWING_V1) == lv
                g1 = g1_bracket(df, tf, tt)
                assert independent_resistance(df, lv["entry"]) == \
                    independent_swing_resistance(df, lv["entry"])
                if g1.valid:
                    # G1 applies the cap to rounded prices, production to the raw close
                    assert abs(g1.t1 - lv["t1"]) <= 2e-8, (name, tf, tt)
                    checked += 1
    assert checked > 200


def test_policy_changes_only_t1_never_entry_stop_or_t2_t3(policy):
    for name, df in _frames():
        for tf in TFS:
            for tt in ("momentum", "reversion"):
                policy(LEGACY_WINDOW_V1)
                a = TA._calculate_levels(df, tf, tt)
                policy(INDEPENDENT_SWING_V1)
                b = TA._calculate_levels(df, tf, tt)
                for k in ("entry", "stop", "t2", "t3", "stop_valid", "stop_policy"):
                    assert a[k] == b[k], (name, tf, tt, k)
                assert b["t1"] > b["entry"] or not b["stop_valid"]


@pytest.mark.parametrize("pol", [PRIOR_WINDOW_V1, NO_CAP_V1])
def test_options_a_and_c_analyzer_equals_research_copy(policy, pol):
    """WP-D02: the SE-40 options a and c reach the analyzer and the strategy_math research copy
    through the same resistance_for dispatch; only T1 and the provenance key differ from legacy."""
    for name, df in _frames():
        for tf in TFS:
            for tt in ("momentum", "reversion"):
                policy(pol)
                lv = TA._calculate_levels(df, tf, tt)
                assert calculate_signal_levels(df, tf, tt, t1_cap_policy=pol) == lv, (name, tf, tt)
                assert lv["t1_cap_policy"] == pol
                policy(LEGACY_WINDOW_V1)
                legacy = TA._calculate_levels(df, tf, tt)
                assert {k: v for k, v in lv.items() if k not in ("t1", "t1_cap_policy")} == \
                    {k: v for k, v in legacy.items() if k != "t1"}


# 4 ── fail closed ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["", "independent", "LEGACY", "g1", "off", "prior_window", "no_cap"])
def test_unknown_policy_refuses(policy, bad):
    if bad.strip().lower() in T1_CAP_POLICIES:
        pytest.skip("case-insensitive alias of a valid policy")
    policy(bad)
    with pytest.raises(RuntimeError, match="unknown T1_CAP_POLICY"):
        t1_cap_policy(config)
    with pytest.raises(RuntimeError, match="unknown T1_CAP_POLICY"):
        TA._calculate_levels(_capped_case(), "4h", "momentum")


def test_policy_is_case_and_space_insensitive(policy):
    policy("  Independent_Swing_V1 ")
    assert t1_cap_policy(config) == INDEPENDENT_SWING_V1


def test_analyzer_main_validates_the_policy_at_startup():
    tree = ast.parse(open("analyzer/main.py", encoding="utf-8").read())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "t1_cap_policy"]
    assert calls, "analyzer/main.py must call t1_cap_policy(config) at startup"
    main_fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "main")
    def callee(stmt):
        v = getattr(stmt, "value", None)
        v = getattr(v, "value", v) if isinstance(v, ast.Await) else v
        return getattr(getattr(v, "func", None), "id", None)
    names = [callee(s) for s in main_fn.body]
    assert names.index("t1_cap_policy") < names.index("mark_started")


def test_t1_cap_module_is_pure():
    src = open("shared/t1_cap.py", encoding="utf-8").read()
    for forbidden in ("Database", "asyncpg", "binance", "requests", "aiohttp", "os.getenv", "open("):
        assert forbidden not in src
