"""S5-PWR-1: synthetic, deterministic tests for research/power (no data, database, network or production access)."""
import ast
import builtins
import io
import os
import pathlib
import socket
import subprocess
import sys
from fractions import Fraction
from statistics import NormalDist

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.power import admissibility_screen as ad  # noqa: E402
from research.power import ladder_power as lp  # noqa: E402

PKG = ROOT / "research" / "power"
LATEST = dict(scenario="A33_EQUAL_1_240_CAL_1_276", stream="MAIN")
ALPHA_1_240 = dict(scenario="A33_OWNER_ALTERNATIVE_CAL_1_240", stream="MAIN")


# --- arithmetic anchors from the source documents -------------------------------------------------------------

def test_normal_theory_multiplier_matches_documented_3_48():
    c, mode = lp.critical_value("NORMAL_THEORY", **ALPHA_1_240)
    assert mode.status == "ANALYTIC_APPROXIMATION_NOT_ENVELOPE_CALIBRATED"
    assert c + NormalDist().inv_cdf(0.8) == pytest.approx(3.48, abs=5e-3)


def test_envelope_multiplier_is_about_4_04_and_labelled_unvalidated():
    c, mode = lp.critical_value("A33_ENVELOPE_PLUS_ALPHA_CAL_SHIFT", **LATEST)
    assert c == pytest.approx(3.20) and "UNVALIDATED" in mode.status
    r = lp.daily_hac_sharpe_mde(cv_mode="A33_ENVELOPE_PLUS_ALPHA_CAL_SHIFT", power=0.8, days=365, lrv_ratio=1,
                                **LATEST)
    assert r.value == pytest.approx(4.0416, abs=1e-3)
    assert r.approximates_governed_test and r.illustrative_until_validated


def test_a31_envelope_values_are_reported_only_where_a31_reported_them():
    assert lp.critical_value("A31_ENVELOPE_IN_SAMPLE", **ALPHA_1_240)[0] == 3.14
    assert lp.critical_value("A31_ENVELOPE_IN_SAMPLE", scenario="A30_HALF_WEIGHT_RESERVE", stream="RESERVE")[0] == 3.41
    with pytest.raises(lp.PowerInputError):
        lp.critical_value("A31_ENVELOPE_IN_SAMPLE", **LATEST)            # 1/276 was never reported by A31
    with pytest.raises(lp.PowerInputError):
        lp.critical_value("A33_ENVELOPE_PLUS_ALPHA_CAL_SHIFT", **ALPHA_1_240)


def test_a42_c1_planning_mde_reproduces():
    r = lp.per_trade_mde_illustrative(cv_mode="NORMAL_THEORY", power=0.8, sigma=1.5, deff=1, n1=2300, n2=4700,
                                      **ALPHA_1_240)
    assert r.value == pytest.approx(0.13, abs=0.005) and not r.approximates_governed_test


def test_a45_h2_stated_0_12_does_not_reproduce_from_its_inputs():
    """A45 l.169: ~6,400 setups/year, about 1/3 above the cap, sigma 1.5 % -> stated 0.12 %; recomputed 0.136-0.142."""
    vals = [lp.per_trade_mde_illustrative(cv_mode="NORMAL_THEORY", power=0.8, sigma=1.5, deff=1, n1=6400 * f,
                                          n2=6400 * (1 - f), **ALPHA_1_240).value for f in (0.33, 0.34, 1 / 3)]
    assert all(0.136 <= v <= 0.142 for v in vals)
    assert all(abs(v - 0.12) > 0.01 for v in vals)


# --- governed-test behaviour ------------------------------------------------------------------------------------

def test_governed_horizon_is_capped_at_365_days():
    lp.daily_hac_sharpe_mde(cv_mode="NORMAL_THEORY", power=0.8, days=365, lrv_ratio=1, **LATEST)
    with pytest.raises(lp.PowerInputError):
        lp.daily_hac_sharpe_mde(cv_mode="NORMAL_THEORY", power=0.8, days=366, lrv_ratio=1, **LATEST)


def test_mde_monotone_in_n_and_dependence():
    def pt(n, f):
        return lp.per_trade_mde_illustrative(cv_mode="NORMAL_THEORY", power=0.8, sigma=1.0, deff=f, n1=n,
                                             **LATEST).value
    assert pt(100, 1) > pt(400, 1) > pt(800, 1)
    assert pt(400, 1) < pt(400, 2) < pt(400, 3)
    assert pt(400, 4) == pytest.approx(2 * pt(400, 1))
    d = [lp.daily_hac_sharpe_mde(cv_mode="NORMAL_THEORY", power=0.8, days=365, lrv_ratio=r, **LATEST).value
         for r in (1, 1.5, 2, 3)]
    assert d == sorted(d)
    shorter = lp.daily_hac_sharpe_mde(cv_mode="NORMAL_THEORY", power=0.8, days=182, lrv_ratio=1, **LATEST).value
    assert shorter > d[0]


def test_required_trades_inverts_the_mde():
    kw = dict(cv_mode="NORMAL_THEORY", power=0.8, sigma=1.0, deff=2, **LATEST)
    n = lp.required_trades_illustrative(effect=0.1, **kw)
    assert lp.per_trade_mde_illustrative(n1=n, **kw).value == pytest.approx(0.1)


def test_no_scenario_mode_or_stream_has_a_default():
    for fn in (lp.daily_hac_sharpe_mde, lp.per_trade_mde_illustrative, lp.required_trades_illustrative):
        with pytest.raises(TypeError):
            fn(power=0.8)
    with pytest.raises(TypeError):
        lp.critical_value("NORMAL_THEORY")
    for bad in (dict(scenario="BINDING", stream="MAIN"), dict(scenario=LATEST["scenario"], stream="ALL")):
        with pytest.raises(lp.PowerInputError):
            lp.critical_value("NORMAL_THEORY", **bad)


def test_every_scenario_carries_a_status_and_superseded_ones_are_marked():
    st = {k: v.status for k, v in lp.ALPHA_SCENARIOS.items()}
    assert st["A30_HALF_WEIGHT_RESERVE"] == st["A31_RESERVE_0_21_PCT"] == "SUPERSEDED"
    assert "NOT_GOVERNANCE_CONFIRMED" in st["A33_EQUAL_1_240_CAL_1_276"]
    assert not any("BINDING" in s for s in st.values())
    assert all(m.status for m in lp.CRITICAL_VALUE_MODES.values())


def test_program_ledger_arithmetic_is_exact():
    b = lp.program_bound(LATEST["scenario"], 10, 2)
    assert b["governance_allocation"] == Fraction(1, 20) and b["union_bound_at_test_levels"] == Fraction(12, 276)
    assert b["allocation_within_program_fwer"] and b["certified_bound"] is None
    assert lp.program_bound("A30_HALF_WEIGHT_RESERVE", 10, 2)["governance_allocation"] == Fraction(11, 240)
    with pytest.raises(lp.PowerInputError):
        lp.program_bound(LATEST["scenario"], 12, 1)
    with pytest.raises(lp.PowerInputError):
        lp.program_bound(LATEST["scenario"], True, 0)


def test_deff_bound_from_cluster_sizes_only():
    assert lp.deff_bound_any_within_cluster([1] * 50) == 1
    assert lp.deff_bound_any_within_cluster([2, 2]) == 2
    assert lp.deff_bound_any_within_cluster([1, 3]) == 3
    assert lp.deff_exchangeable_homoskedastic([1, 3], 0) == 1
    assert lp.deff_exchangeable_homoskedastic([1, 3], 1) == 2.5
    for bad in ([], [0, 1], [1.5], [True], "1,2,3", b"12", (x for x in [1, 2])):
        with pytest.raises(lp.PowerInputError):
            lp.deff_bound_any_within_cluster(bad)
    with pytest.raises(lp.PowerInputError):
        lp.deff_exchangeable_homoskedastic([1, 2], 1.2)


def test_canonical_table_is_deterministic_and_never_binding():
    t1, t2 = lp.canonical_table(), lp.canonical_table()
    assert t1 == t2 and "not evidence of no edge" in t1 and "No row is a binding governance choice" in t1
    assert "A33_EQUAL_1_240_CAL_1_276 | LATEST_DOCUMENTED_NOT_GOVERNANCE_CONFIRMED | MAIN | " \
           "A33_ENVELOPE_PLUS_ALPHA_CAL_SHIFT | INTERPOLATED_APPROXIMATION_UNVALIDATED | 3.2000 | 4.042 | 4.950 | " \
           "5.716 | 7.000" in t1


def test_cli_prints_exactly_the_canonical_table():
    out = subprocess.run([sys.executable, "-m", "research.power.ladder_power"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    assert out == lp.canonical_table()


# --- admissibility screen ---------------------------------------------------------------------------------------

def _decl(**kw):
    base = dict(name="synthetic", unit="per_trade_illustrative", scenario=LATEST["scenario"], stream="MAIN",
                cv_mode="NORMAL_THEORY", power=0.8, sigma=1.0, n1=400, dependence_low=1, dependence_high=3,
                source="synthetic")
    base.update(kw)
    return ad.CandidateDeclaration(**base)


def test_screen_statuses_on_synthetic_declarations():
    assert ad.screen(_decl(effect_low=0.01, effect_high=0.05)).status == ad.BELOW_TARGET
    assert ad.screen(_decl(effect_low=1.0, effect_high=2.0)).status == ad.AT_OR_ABOVE_TARGET
    assert ad.screen(_decl(effect_low=0.15, effect_high=0.5)).status == ad.DEPENDS_ON_ASSUMPTIONS
    assert ad.screen(_decl(effect_low=None, effect_high=None)).status == ad.UNKNOWN
    daily = ad.screen(_decl(unit="daily_hac_sharpe", sigma=None, n1=None, days=365, effect_low=1, effect_high=2))
    assert daily.status == ad.BELOW_TARGET and daily.approximates_governed_test


def test_screen_never_admits_rejects_confirms_or_spends_alpha():
    for d in (_decl(effect_low=0.01, effect_high=0.05), _decl(effect_low=1.0, effect_high=2.0)):
        r = ad.screen(d)
        assert not (r.is_admission or r.consumes_alpha or r.is_evidence_of_no_edge or r.is_evidence_of_edge)
        assert "Insufficient power is not evidence of no edge." in r.caveats


def test_screen_vocabulary_has_no_misleading_statistical_claims():
    forbidden_tokens = ("REJECT", "NO_EDGE", "CONFIRM", "SUPPORTED", "PROFIT", "DEPLOY", "PASS", "FAIL")
    assert not any(tok in s for s in ad.STATUSES for tok in forbidden_tokens)
    results = {ad.screen(_decl(effect_low=lo, effect_high=hi)).status: ad.screen(_decl(effect_low=lo, effect_high=hi))
               for lo, hi in ((0.01, 0.05), (1.0, 2.0), (0.15, 0.5), (None, None))}
    assert set(results) == set(ad.STATUSES)
    text = " ".join(r.interpretation for r in results.values()).lower() + " ".join(ad.FIXED_CAVEATS).lower()
    for phrase in ("no edge exists", "there is no edge", "edge confirmed", "is profitable", "deployable",
                   "proves", "edge is real", "unlikely to confirm"):
        assert phrase not in text
    assert "not evidence of no edge" in results[ad.BELOW_TARGET].interpretation.lower()
    assert "not evidence of an edge" in results[ad.AT_OR_ABOVE_TARGET].interpretation.lower()


def test_per_trade_results_are_labelled_illustrative_not_governed():
    r = ad.screen(_decl(effect_low=0.01, effect_high=0.05))
    assert not r.approximates_governed_test and any("ILLUSTRATIVE ONLY" in c for c in r.caveats)


def test_max_dependence_for_target_mde():
    f = ad.max_dependence_for_mde(unit="per_trade_illustrative", cv_mode="NORMAL_THEORY", target_mde=0.2,
                                  power=0.8, sigma=1.5, n1=6400 / 3, n2=6400 * 2 / 3, **ALPHA_1_240)
    assert 2.0 < f < 2.2        # ~2.1: the A45 H2 admission rule needs a small measured design effect


# --- isolation: no data, database, network, environment or production access ----------------------------------

ALLOWED_IMPORTS = {"dataclasses", "fractions", "math", "numbers", "statistics", "research.power"}
FORBIDDEN_CALLS = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals", "vars"}
FORBIDDEN_ATTRS = {"environ", "getenv", "system", "popen", "connect", "urlopen", "read_text", "read_bytes"}


def _sources():
    files = sorted(PKG.glob("*.py"))
    assert {p.name for p in files} == {"__init__.py", "ladder_power.py", "admissibility_screen.py"}
    return files


def test_package_imports_only_the_standard_math_allowlist():
    for p in _sources():
        for node in ast.walk(ast.parse(p.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for n in names:
                assert n in ALLOWED_IMPORTS or n.startswith("research.power"), f"{p.name}: import {n}"


def test_package_has_no_io_eval_or_environment_calls():
    for p in _sources():
        for node in ast.walk(ast.parse(p.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in FORBIDDEN_CALLS, f"{p.name}: {node.func.id}()"
            if isinstance(node, ast.Attribute):
                assert node.attr not in FORBIDDEN_ATTRS, f"{p.name}: .{node.attr}"


def test_runs_with_every_io_and_network_entry_point_disabled(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("prohibited I/O attempted")
    for obj, name in ((builtins, "open"), (io, "open"), (os, "open"), (os, "listdir"), (os, "scandir"),
                      (socket, "socket"), (socket, "create_connection"), (subprocess, "Popen"),
                      (pathlib.Path, "open"), (pathlib.Path, "read_text")):
        monkeypatch.setattr(obj, name, refuse)
    monkeypatch.setattr(os, "environ", {})
    lp.canonical_table()
    lp.program_bound(LATEST["scenario"], 3, 1)
    lp.deff_bound_any_within_cluster([1, 2, 3])
    lp.required_trades_illustrative(cv_mode="NORMAL_THEORY", power=0.8, sigma=1, deff=2, effect=0.1, **LATEST)
    for d in (_decl(effect_low=0.01, effect_high=0.05), _decl(effect_low=None, effect_high=None)):
        ad.screen(d)


@pytest.mark.parametrize("bad", [pathlib.Path("data/evidence_v2/x.jsonl"), "trades.csv", b"1", io.StringIO("1"),
                                 True, float("nan"), float("inf"), None, [100]])
def test_path_file_or_non_numeric_inputs_are_refused(bad):
    with pytest.raises((lp.PowerInputError, TypeError)):
        lp.per_trade_mde_illustrative(cv_mode="NORMAL_THEORY", power=0.8, sigma=1, deff=1, n1=bad, **LATEST)
    if bad is None:                       # a missing declared effect is not refused: it is UNKNOWN_INPUTS
        assert ad.screen(_decl(effect_low=bad, effect_high=1.0)).status == ad.UNKNOWN
        return
    with pytest.raises((lp.PowerInputError, TypeError)):
        ad.screen(_decl(effect_low=bad, effect_high=1.0))


def test_screen_refuses_non_declaration_and_bad_labels():
    for bad in ({"name": "x"}, "candidate.json", pathlib.Path("candidate.json")):
        with pytest.raises(lp.PowerInputError):
            ad.screen(bad)
    with pytest.raises(lp.PowerInputError):
        ad.screen(_decl(name=pathlib.Path("x"), effect_low=0.1, effect_high=0.2))


def test_no_production_module_imports_the_power_package():
    offenders = []
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT)
        if rel.parts[0] in ("tests", ".git") or rel.parts[:2] == ("research", "power"):
            continue
        txt = p.read_text(errors="ignore")
        if "research.power" in txt or "ladder_power" in txt or "admissibility_screen" in txt:
            offenders.append(str(rel))
    assert offenders == []
