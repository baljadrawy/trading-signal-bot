"""S5-PWR-1 remediation regression tests (independent review of PR #58: M1-M6, G1, m1-m12).

Synthetic, deterministic and outcome-free. Each MAJOR test reproduces a defect found against 8b7ceb4."""
import ast
import json
import math
import pathlib
import random
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
LATEST = dict(scenario="A33_EQUAL_1_240_CAL_1_276", stream="MAIN", cv_mode="A33_ENVELOPE_PLUS_ALPHA_CAL_SHIFT")
ALT = dict(scenario="A33_OWNER_ALTERNATIVE_CAL_1_240", stream="MAIN", cv_mode="NORMAL_THEORY")


def daily(**kw):
    base = dict(name="synthetic", unit="daily_hac_sharpe", power=0.8, days=365, dependence_low=1,
                dependence_high=1, source="synthetic test", **LATEST)
    base.update(kw)
    return ad.CandidateDeclaration(**base)


def per_trade(**kw):
    base = dict(name="synthetic", unit="per_trade_illustrative", power=0.8, sigma=1.0, n1=400, dependence_low=1,
                dependence_high=3, source="synthetic test", **LATEST)
    base.update(kw)
    return ad.CandidateDeclaration(**base)


def daily_mde(**kw):
    args = dict(power=0.8, days=365, lrv_ratio=1, **LATEST)
    args.update(kw)
    return lp.daily_hac_sharpe_mde(**args)


# --- M1: power is compared with the declared target; no overstated wording ------------------------------------

def test_m1_near_boundary_reports_implied_power_not_unlikely_confirmation():
    m = daily_mde().value
    r = ad.screen(daily(effect_low=0.99 * m, effect_high=0.99 * m))
    expected = NormalDist().cdf(0.99 * m - 3.20)                    # 0.788 at the A33 envelope value
    assert r.status == ad.BELOW_TARGET
    assert r.implied_power_min == pytest.approx(expected, abs=1e-9)
    assert r.implied_power_max == pytest.approx(expected, abs=1e-9)
    assert "0.788" in r.interpretation and "0.8" in r.interpretation
    assert "unlikely" not in r.interpretation.lower()
    assert "not evidence of no edge" in r.interpretation.lower()


def test_m1_status_boundaries_follow_power_versus_target():
    m = daily_mde().value
    assert ad.screen(daily(effect_low=m, effect_high=m)).status == ad.AT_OR_ABOVE_TARGET
    assert ad.screen(daily(effect_low=0.5 * m, effect_high=2 * m)).status == ad.DEPENDS_ON_ASSUMPTIONS
    lo = ad.screen(daily(effect_low=0.5 * m, effect_high=0.6 * m))
    assert lo.status == ad.BELOW_TARGET and lo.implied_power_max < 0.8


# --- M2: complete provenance; superseded scenarios are not screened ---------------------------------------------

def test_m2_result_records_every_effective_input():
    r = ad.screen(daily(effect_low=5.0, effect_high=6.0))
    assert (r.scenario, r.stream, r.cv_mode, r.endpoint) == (LATEST["scenario"], "MAIN", LATEST["cv_mode"],
                                                              "daily_hac_sharpe")
    assert r.scenario_status == "LATEST_DOCUMENTED_NOT_GOVERNANCE_CONFIRMED"
    assert r.cv_status == "INTERPOLATED_APPROXIMATION_UNVALIDATED"
    assert r.target_power == 0.8 and r.critical_value == pytest.approx(3.20)
    assert (r.effect_low, r.effect_high, r.dependence_low, r.dependence_high, r.days) == (5.0, 6.0, 1.0, 1.0, 365.0)
    assert r.illustrative_until_validated is True and r.approximates_governed_test is True


def test_m2_superseded_scenarios_are_refused_by_the_screen():
    for sc in ("A30_HALF_WEIGHT_RESERVE", "A31_RESERVE_0_21_PCT"):
        with pytest.raises(lp.PowerInputError, match="SUPERSEDED"):
            ad.screen(daily(scenario=sc, cv_mode="NORMAL_THEORY", effect_low=5, effect_high=6))


# --- M3: program bound derived from each test's level; nothing labelled certified ------------------------------

def test_m3_program_bound_uses_per_stream_test_levels():
    b = lp.program_bound("A30_HALF_WEIGHT_RESERVE", 10, 2)
    assert b["governance_allocation"] == Fraction(11, 240)
    assert b["union_bound_at_test_levels"] == Fraction(11, 240)          # 8b7ceb4 returned 1/20
    latest = lp.program_bound("A33_EQUAL_1_240_CAL_1_276", 10, 2)
    assert latest["governance_allocation"] == Fraction(1, 20)
    assert latest["union_bound_at_test_levels"] == Fraction(12, 276)


def test_m3_no_bound_is_labelled_certified():
    for sc in lp.ALPHA_SCENARIOS:
        b = lp.program_bound(sc, 3, 0)
        assert b["certified_bound"] is None and b["calibration_validated"] is False
    alt = lp.program_bound("A33_OWNER_ALTERNATIVE_CAL_1_240", 12, 0)
    assert alt["bound_stated_if_alternative_adopted"] == Fraction(12) * Fraction(115, 100) / 240   # 5.75 %
    assert lp.program_bound("A33_EQUAL_1_240_CAL_1_276", 12, 0)["bound_stated_if_alternative_adopted"] is None


# --- M4: DEFF bounds state their assumptions; heteroskedastic counterexample ------------------------------------

def _exact_deff(sizes, sds, rho):
    """Exact variance inflation of the sum for exchangeable within-cluster correlation rho, independent clusters."""
    num = den = 0.0
    for m, s in zip(sizes, sds):
        cluster = [s] * m if isinstance(s, (int, float)) else s
        num += sum(a * a for a in cluster) + rho * (sum(cluster) ** 2 - sum(a * a for a in cluster))
        den += sum(a * a for a in cluster)
    return num / den


def test_m4_reviewer_counterexample_exceeds_homoskedastic_formula_but_not_conservative_bound():
    true = _exact_deff([1, 9], [1.0, 10.0], 1.0)
    assert true == pytest.approx(8.991, abs=1e-3)
    assert lp.deff_exchangeable_homoskedastic([1, 9], 1) == pytest.approx(8.2)   # assumption-bound formula
    assert true > lp.deff_exchangeable_homoskedastic([1, 9], 1)
    assert true <= lp.deff_bound_any_within_cluster([1, 9]) == 9


def test_m4_conservative_bound_holds_for_random_heteroskedastic_synthetic_clusters():
    rng = random.Random(20261019)
    for _ in range(300):
        sizes = [rng.randint(1, 12) for _ in range(rng.randint(1, 8))]
        sds = [[rng.uniform(0.1, 20.0) for _ in range(m)] for m in sizes]
        rho = rng.uniform(0.0, 1.0)
        assert _exact_deff(sizes, sds, rho) <= lp.deff_bound_any_within_cluster(sizes) + 1e-9


def test_m4_effective_sample_size_statement_for_unequal_clusters():
    sizes = [1, 9]
    assert lp.n_eff_lower_bound_any_within_cluster(sizes) == pytest.approx(10 / 9)
    # at rho = 1 (homoskedastic) n_eff = (sum m)^2 / sum m^2 <= number of clusters, equality only if balanced
    assert 100 / 82 < len(sizes) and lp.n_eff_lower_bound_any_within_cluster([3, 3]) == 2


# --- M5: reconsideration cannot be triggered by broad ranges or illustrative endpoints --------------------------

def test_m5_broad_effect_range_never_supports_reconsideration():
    r = ad.screen(daily(effect_low=0, effect_high=1e9))
    assert r.status == ad.DEPENDS_ON_ASSUMPTIONS and r.reconsideration_eligible is False


def test_m5_per_trade_or_unvalidated_results_never_support_reconsideration():
    pt = ad.screen(per_trade(n1=10_000_000, effect_low=0.01, effect_high=0.02, dependence_high=1))
    assert pt.status == ad.AT_OR_ABOVE_TARGET and pt.reconsideration_eligible is False
    assert any("illustrative" in b for b in pt.reconsideration_blockers)
    big = ad.screen(daily(effect_low=50, effect_high=60))
    assert big.status == ad.AT_OR_ABOVE_TARGET and big.reconsideration_eligible is False
    assert any("not independently validated" in b for b in big.reconsideration_blockers)
    assert not (big.is_admission or big.consumes_alpha)


def test_m5_owner_register_has_no_trivially_satisfiable_criterion():
    text = (ROOT / "docs/strategy/S5_PWR_1_OWNER_DECISIONS.md").read_text()
    assert "POWERED or INDETERMINATE" not in text
    assert "POWER_AT_OR_ABOVE_TARGET_UNDER_STATED_ASSUMPTIONS" in text


# --- G1: precise labels; nothing claims to be the governed decision ----------------------------------------------

def test_g1_labels_are_precise_and_cannot_be_forged():
    r = daily_mde()
    assert not hasattr(r, "governed")
    assert r.approximates_governed_test is True and r.illustrative_until_validated is True
    assert lp.per_trade_mde_illustrative(power=0.8, sigma=1, deff=1, n1=100, **LATEST).approximates_governed_test \
        is False
    with pytest.raises(ValueError):
        lp.MDEResult(**{**r.__dict__, "illustrative_until_validated": False})
    good = ad.screen(daily(effect_low=5, effect_high=6))
    for forged in ({"is_admission": True}, {"consumes_alpha": True}, {"status": "CONFIRMED_EDGE"},
                   {"illustrative_until_validated": False}, {"reconsideration_eligible": True},
                   {"is_evidence_of_no_edge": True}):
        with pytest.raises(ValueError):
            ad.ScreenResult(**{**good.__dict__, **forged})


def test_g1_owner_decisions_recorded():
    text = (ROOT / "docs/strategy/S5_PWR_1_OWNER_DECISIONS.md").read_text()
    for od in ("OD-1", "OD-2", "OD-3", "OD-4", "OD-5", "OD-6", "OD-7"):
        assert f"| {od} | DECIDED" in text, od


# --- M6: input validation fails closed ---------------------------------------------------------------------------

class SideEffectFloat:
    called = False

    def __float__(self):
        SideEffectFloat.called = True
        return 1.0


class FloatSub(float):
    pass


@pytest.mark.parametrize("bad", [SideEffectFloat(), FloatSub(2.0), True, 10 ** 400, Fraction(10 ** 400),
                                 float("nan"), float("inf"), -1.0, 0, pathlib.Path("x.csv"), "1", b"1"])
def test_m6_only_exact_finite_builtin_numbers_are_accepted(bad):
    SideEffectFloat.called = False
    with pytest.raises(lp.PowerInputError):
        lp.per_trade_mde_illustrative(power=0.8, sigma=1, deff=1, n1=bad, **LATEST)
    assert SideEffectFloat.called is False                                  # no caller dunder executed


def test_m6_unused_fields_are_refused_not_ignored():
    with pytest.raises(lp.PowerInputError, match="not used"):
        ad.screen(daily(effect_low=1, effect_high=2, sigma=pathlib.Path("x.csv")))
    with pytest.raises(lp.PowerInputError, match="not used"):
        ad.screen(daily(effect_low=1, effect_high=2, n1="trades.csv"))
    with pytest.raises(lp.PowerInputError, match="not used"):
        ad.screen(per_trade(effect_low=0.1, effect_high=0.2, days=1e6))


def test_m6_invalid_values_are_refused_before_missing_values_become_unknown():
    with pytest.raises(lp.PowerInputError):
        ad.screen(daily(effect_low=pathlib.Path("x"), effect_high=1, dependence_high=None))
    assert ad.screen(daily(effect_low=None, effect_high=1)).status == ad.UNKNOWN


def test_m6_non_positive_effect_ranges_are_refused_for_a_one_sided_claim():
    with pytest.raises(lp.PowerInputError, match="one-sided"):
        ad.screen(daily(effect_low=-2, effect_high=-1))
    with pytest.raises(lp.PowerInputError, match="one-sided"):
        ad.screen(daily(effect_low=-1, effect_high=1))


def test_m6_overflow_underflow_and_tiny_samples_fail_closed():
    for kw in (dict(n1=10 ** 400), dict(n1=5e-324), dict(n1=1), dict(sigma=1e308, deff=100), dict(n1=1.5)):
        args = dict(power=0.8, sigma=1, deff=1, n1=100, **LATEST)
        args.update(kw)
        with pytest.raises(lp.PowerInputError):
            lp.per_trade_mde_illustrative(**args)
    for d in (0.5, 1, 1e-320):
        with pytest.raises(lp.PowerInputError):
            daily_mde(days=d)
    with pytest.raises(lp.PowerInputError):
        lp.required_trades_illustrative(power=0.8, sigma=1, deff=1, effect=1e-200, **LATEST)
    with pytest.raises(lp.PowerInputError):
        lp.deff_bound_any_within_cluster([10 ** 400])


def test_m6_labels_require_provenance_and_power_has_no_default():
    with pytest.raises(lp.PowerInputError):
        ad.screen(daily(name="", effect_low=1, effect_high=2))
    with pytest.raises(lp.PowerInputError):
        ad.screen(daily(source="", effect_low=1, effect_high=2))
    with pytest.raises(TypeError):
        ad.CandidateDeclaration(name="x", unit="daily_hac_sharpe", source="s", **LATEST)   # no power given


def test_m6_max_dependence_below_one_is_refused():
    with pytest.raises(lp.PowerInputError):
        ad.max_dependence_for_mde(unit="daily_hac_sharpe", target_mde=0.1, power=0.8, days=365, **LATEST)
    with pytest.raises(lp.PowerInputError, match="not used"):
        ad.max_dependence_for_mde(unit="daily_hac_sharpe", target_mde=10, power=0.8, days=365, sigma=1, **LATEST)


def test_m6_per_trade_screen_keeps_every_illustrative_caveat():
    r = ad.screen(per_trade(effect_low=0.01, effect_high=0.02))
    assert set(lp.ILLUSTRATIVE_CAVEATS) <= set(r.caveats)


# --- M6: static isolation checker, with positive controls ---------------------------------------------------------

ALLOWED_FROM_IMPORTS = {
    "dataclasses": {"dataclass", "field"}, "fractions": {"Fraction"}, "math": {"isfinite", "sqrt"},
    "statistics": {"NormalDist"}, "research.power": {"ladder_power"},
}
BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals", "vars", "locals",
                "getattr", "setattr", "delattr", "__builtins__", "memoryview", "help"}


def violations(source):
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out.append(f"plain import {[a.name for a in node.names]}")
        elif isinstance(node, ast.ImportFrom):
            allowed = ALLOWED_FROM_IMPORTS.get(node.module or "", set())
            out += [f"from {node.module} import {a.name}" for a in node.names if a.name not in allowed]
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            out.append(f"name {node.id}")
        elif isinstance(node, ast.Name) and node.id.startswith("__") and node.id != "__name__":
            out.append(f"dunder name {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            out.append(f"dunder attribute {node.attr}")
    return out


BYPASSES = (
    "import dataclasses\nx = dataclasses.sys.modules['io'].FileIO(p).readall()",
    "from dataclasses import dataclass\nx = dataclass.__globals__['sys']",
    "import dataclasses\nx = dataclasses.inspect.linecache.getlines(p)",
    "from importlib import import_module\nimport_module('sqlite3')",
    "x = __builtins__['open'](p)",
    "o = open\no(p)",
    "import os\ny = getattr(os, 'env' + 'iron')",
    "from statistics import NormalDist\nm = NormalDist.__module__",
    "from os import environ",
)


@pytest.mark.parametrize("snippet", BYPASSES)
def test_m6_static_checker_flags_every_known_bypass(snippet):
    assert violations(snippet), snippet


def test_m6_package_source_passes_the_static_checker():
    files = sorted(PKG.glob("*.py"))
    assert {p.name for p in files} == {"__init__.py", "ladder_power.py", "admissibility_screen.py"}
    for p in files:
        assert violations(p.read_text()) == [], p.name


# --- M6 / m12: runtime audit hook in a subprocess, every public function, with a positive control -------------

PUBLIC = {
    "ladder_power": {"alpha_scenario", "test_level", "critical_value", "program_bound", "daily_hac_sharpe_mde",
                     "per_trade_mde_illustrative", "required_trades_illustrative", "power_daily_hac",
                     "power_per_trade_illustrative", "deff_bound_any_within_cluster",
                     "deff_exchangeable_homoskedastic", "n_eff_lower_bound_any_within_cluster", "canonical_table",
                     "main"},
    "admissibility_screen": {"screen", "max_dependence_for_mde"},
}

AUDIT_SCRIPT = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from research.power import admissibility_screen as ad, ladder_power as lp
events = []
FLAG = ("open", "import", "exec", "compile", "socket.", "subprocess.", "os.", "shutil.", "sqlite3.", "urllib.",
        "http.", "ftplib.", "smtplib.", "ctypes.", "glob.", "pathlib.", "tempfile.", "marshal.", "pickle.")
sys.addaudithook(lambda ev, args: events.append(ev) if ev.startswith(FLAG) else None)
L = dict(scenario="A33_EQUAL_1_240_CAL_1_276", stream="MAIN", cv_mode="A33_ENVELOPE_PLUS_ALPHA_CAL_SHIFT")
lp.alpha_scenario(L["scenario"]); lp.test_level(L["scenario"], "RESERVE"); lp.critical_value(**L)
lp.program_bound(L["scenario"], 3, 1)
lp.daily_hac_sharpe_mde(power=0.8, days=365, lrv_ratio=2, **L)
lp.per_trade_mde_illustrative(power=0.8, sigma=1.0, deff=2, n1=100, n2=200, **L)
lp.required_trades_illustrative(power=0.8, sigma=1.0, deff=2, effect=0.1, **L)
lp.power_daily_hac(days=365, lrv_ratio=1, effect=3.0, **L)
lp.power_per_trade_illustrative(sigma=1.0, deff=1, n1=100, effect=0.3, **L)
lp.deff_bound_any_within_cluster([1, 2, 3]); lp.deff_exchangeable_homoskedastic([1, 2, 3], 0.5)
lp.n_eff_lower_bound_any_within_cluster([1, 2, 3]); lp.canonical_table()
d = ad.CandidateDeclaration(name="s", unit="daily_hac_sharpe", power=0.8, days=365, effect_low=1, effect_high=2,
                            dependence_low=1, dependence_high=2, source="synthetic", **L)
ad.screen(d)
ad.max_dependence_for_mde(unit="daily_hac_sharpe", target_mde=10, power=0.8, days=365, **L)
package_events = list(events)
open(sys.argv[2]).read()                      # positive control: the hook must see this
print(json.dumps({"package": package_events, "control": events[len(package_events):]}))
"""


def test_m6_audit_hook_sees_no_io_from_any_public_function(tmp_path):
    probe = tmp_path / "probe.txt"
    probe.write_text("synthetic")
    out = subprocess.run([sys.executable, "-c", AUDIT_SCRIPT, str(ROOT), str(probe)], capture_output=True,
                         text=True, check=True).stdout
    res = json.loads(out)
    assert res["package"] == []
    assert "open" in res["control"]                                           # the hook is not vacuous


def test_m12_audit_script_exercises_every_public_function():
    for mod, names in PUBLIC.items():
        module = lp if mod == "ladder_power" else ad
        public = {n for n, v in vars(module).items() if callable(v) and not n.startswith("_")
                  and getattr(v, "__module__", None) == module.__name__ and not isinstance(v, type)}
        assert public == names, (mod, public ^ names)
        for n in names:
            assert f".{n}(" in AUDIT_SCRIPT or n == "main", n


def test_m12_main_prints_the_canonical_table():
    out = subprocess.run([sys.executable, "-m", "research.power.ladder_power"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    assert out == lp.canonical_table() and "ILLUSTRATIVE UNTIL VALIDATED" in out


# --- m1: production-import check by AST and across non-Python files ---------------------------------------------

def test_m1_no_production_file_imports_or_invokes_the_power_package():
    offenders = []
    needles = ("research.power", "research/power", "ladder_power", "admissibility_screen")
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if not p.is_file() or rel.parts[0] in ("tests", ".git", "docs") or rel.parts[:2] == ("research", "power"):
            continue
        if p.suffix not in (".py", ".sh", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".json", ".txt", "") or \
                p.stat().st_size > 2_000_000:
            continue
        txt = p.read_text(errors="ignore")
        if p.suffix == ".py":
            try:
                tree = ast.parse(txt)
            except SyntaxError:
                tree = None
            for node in ast.walk(tree) if tree else ():
                if isinstance(node, ast.ImportFrom) and node.module == "research" and \
                        any(a.name == "power" for a in node.names):
                    offenders.append(str(rel))
        if any(n in txt for n in needles):
            offenders.append(str(rel))
    assert offenders == []
