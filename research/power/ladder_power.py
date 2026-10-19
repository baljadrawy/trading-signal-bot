"""S5-PWR-1 Evidence Ladder power calculator (`s5-pwr-1-v2`). Research only; production never imports it.

Scope and limits (see docs/strategy/EVIDENCE_LADDER_PARAMETERS.md):
* Pure arithmetic on numbers the caller passes in memory. Only exact `int`, `float` and `Fraction` values are
  accepted (no subclasses, no objects with conversion methods), so no caller-supplied code runs. Nothing is read
  from files, databases, the network or the environment, and no default reads as a binding governance choice:
  every calculation names its alpha scenario, its stream and its critical-value mode.
* Every result is ILLUSTRATIVE UNTIL VALIDATED: no critical value has passed independent validation (A31 §9 item 2;
  A33 validation never run; A34-B rates the A33 specification REVISE).
* `daily_hac_sharpe_mde` APPROXIMATES the governed test (A32 §5, A33 §3: HAC-studentized, Bartlett L = 7, mean of the
  daily mark-to-market net excess, decided once at day 365) with normal theory. `approximates_governed_test = True`
  refers only to that statistical endpoint and form. It is not scientific validation, and a planning horizon shorter
  than 365 days does not complete (or imply readiness for) the governed final look. It ignores the non-binding futility
  looks, the skewness gate and finite-sample HAC bias; simulated power in A31 §5 / A32 §6 is the reference.
* Per-trade functions reproduce the A42/A44/A45 planning arithmetic. They do not approximate the governed test, and
  no mapping from per-trade units to the daily HAC statistic is documented (DR-11).
* Insufficient power is not evidence of no edge.
"""
from dataclasses import dataclass
from fractions import Fraction
from math import isfinite, sqrt
from statistics import NormalDist

VERSION = "s5-pwr-1-v2"
GOVERNED_MAX_DAYS = 365          # A30 scope, A31 owner baseline: 365-day maximum, no second-year extension
MIN_DAYS = 30                    # below this the normal / HAC approximation is not meaningful for planning
MIN_TRADES = 2
PROGRAM_MAX_ADMISSIONS = 12      # A31 §3, A32 §4, A33 §7 (12 admissions per 3-year program, provisional)
PROGRAM_FWER = Fraction(1, 20)   # 5 % familywise false confirmation, union bound (A30 §4 item 2)
A33_ALTERNATIVE_TOLERANCE = Fraction(115, 100)   # A33 §8 owner alternative: tolerance CP upper <= 1.15 alpha
VALIDATED_CV_STATUSES = frozenset()              # no critical-value mode has passed independent validation
_N = NormalDist()
_EXACT = (int, float, Fraction)


@dataclass(frozen=True)
class AlphaScenario:
    """A named alpha-allocation scenario. `status` says whether a later document superseded it."""
    name: str
    alpha_main: Fraction
    alpha_reserve: Fraction
    alpha_cal: Fraction                # level the critical value is calibrated at (may differ from allocation)
    status: str
    sources: str


@dataclass(frozen=True)
class CriticalValueMode:
    """A named way of obtaining the final-look critical value c. `status` states its evidential standing."""
    name: str
    status: str
    sources: str


ALPHA_SCENARIOS = {
    "A33_EQUAL_1_240_CAL_1_276": AlphaScenario(
        "A33_EQUAL_1_240_CAL_1_276", Fraction(1, 240), Fraction(1, 240), Fraction(1, 276),
        "LATEST_DOCUMENTED_NOT_GOVERNANCE_CONFIRMED",
        "A32 §4 (equal 1/240), A33 §4 (alpha_cal = alpha/1.15 = 1/276), A33 §7, A34-B §1-2; validation never run"),
    "A33_OWNER_ALTERNATIVE_CAL_1_240": AlphaScenario(
        "A33_OWNER_ALTERNATIVE_CAL_1_240", Fraction(1, 240), Fraction(1, 240), Fraction(1, 240),
        "UNRESOLVED_OWNER_ALTERNATIVE",
        "A33 §8 owner alternative: alpha_cal = 1/240 with tolerance CP upper <= 1.15 alpha (stated bound 5.75 %)"),
    "A30_HALF_WEIGHT_RESERVE": AlphaScenario(
        "A30_HALF_WEIGHT_RESERVE", Fraction(1, 240), Fraction(1, 480), Fraction(1, 240),
        "SUPERSEDED", "A30 §3 and §4 item 4 (RESERVE at alpha_j / 2); withdrawn by A32 §4"),
    "A31_RESERVE_0_21_PCT": AlphaScenario(
        "A31_RESERVE_0_21_PCT", Fraction(1, 240), Fraction(1, 480), Fraction(1, 240),
        "SUPERSEDED", "A31 §3 (equal fixed 0.42 %, RESERVE at half: 0.21 % = 0.05/24); withdrawn by A32 §4"),
}

CRITICAL_VALUE_MODES = {
    "NORMAL_THEORY": CriticalValueMode(
        "NORMAL_THEORY", "ANALYTIC_APPROXIMATION_NOT_ENVELOPE_CALIBRATED",
        "c = z(1 - alpha_cal); the multiplier 3.48 used by A30 §6, A42 l.238 and A45 l.169"),
    "A31_ENVELOPE_IN_SAMPLE": CriticalValueMode(
        "A31_ENVELOPE_IN_SAMPLE", "PROVISIONAL_IN_SAMPLE_UNVALIDATED",
        "A31 §2 item 2: 2.64 / 3.14 / 3.41 at alpha 1.25 / 0.42 / 0.21 %; calibrated in-sample (A31 §9 item 2)"),
    "A33_ENVELOPE_PLUS_ALPHA_CAL_SHIFT": CriticalValueMode(
        "A33_ENVELOPE_PLUS_ALPHA_CAL_SHIFT", "INTERPOLATED_APPROXIMATION_UNVALIDATED",
        "A31 c(1/240) = 3.14 plus 'about 0.06' for alpha_cal = 1/276 (A33 §8, interpolated); about 3.20"),
}

# A31 §2 item 2 envelope critical values, keyed by the allocation level they were reported at.
_A31_ENVELOPE = {Fraction(1, 80): 2.64, Fraction(1, 240): 3.14, Fraction(1, 480): 3.41}
_A33_ALPHA_CAL_SHIFT = 0.06      # A33 §8: "c rises by about 0.06 (interpolated from the A31 table)"
STREAMS = ("MAIN", "RESERVE")


class PowerInputError(ValueError):
    """Raised for inputs the calculator refuses (wrong type, out of the governed range, unknown scenario)."""


def _num(name, value, *, minimum=None, allow_zero=False, positive=True):
    """Coerce an exact builtin number to a finite float. Subclasses and other objects are refused unconverted."""
    if type(value) not in _EXACT:
        raise PowerInputError(f"{name} must be an exact int, float or Fraction, got {type(value)!r}")
    try:
        v = float(value)
    except OverflowError:
        raise PowerInputError(f"{name} is too large to represent as a finite float") from None
    if not isfinite(v):
        raise PowerInputError(f"{name} must be finite")
    if positive and (v < 0 or (v == 0 and not allow_zero)):
        raise PowerInputError(f"{name} must be >= 0" if allow_zero else f"{name} must be > 0")
    if minimum is not None and v < minimum:
        raise PowerInputError(f"{name} must be >= {minimum:g}")
    return v


def _finite(name, value):
    if not isfinite(value):
        raise PowerInputError(f"{name} is not finite for these inputs (outside the planning range)")
    return value


def _power_z(power):
    p = _num("power", power)
    if not 0.5 <= p < 1:
        raise PowerInputError("power must lie in [0.5, 1)")
    return _N.inv_cdf(p)


def _label(name, value, choices):
    if type(value) is not str or value not in choices:
        raise PowerInputError(f"unknown {name} {value!r}; choose one of {sorted(choices)}")
    return value


def alpha_scenario(name):
    return ALPHA_SCENARIOS[_label("alpha scenario", name, ALPHA_SCENARIOS)]


def test_level(scenario, stream):
    """(allocated alpha, calibration level) of one test in `stream`. The calibration level scales with the
    allocation, so a scenario with equal MAIN / RESERVE allocation gives both streams the same level."""
    sc = alpha_scenario(scenario)
    _label("stream", stream, STREAMS)
    alloc = sc.alpha_main if stream == "MAIN" else sc.alpha_reserve
    return alloc, sc.alpha_cal * alloc / sc.alpha_main


def critical_value(cv_mode, scenario, stream):
    """Return (c, mode) for a named mode, alpha scenario and stream. Raises if the mode has no value there."""
    mode = CRITICAL_VALUE_MODES[_label("critical-value mode", cv_mode, CRITICAL_VALUE_MODES)]
    alloc, cal = test_level(scenario, stream)
    if cv_mode == "NORMAL_THEORY":
        c = _N.inv_cdf(1 - float(cal))
    elif cv_mode == "A31_ENVELOPE_IN_SAMPLE":
        if cal not in _A31_ENVELOPE:
            raise PowerInputError("A31 reported envelope critical values only at alpha 1/80, 1/240 and 1/480; "
                                  f"{scenario}/{stream} calibrates at {cal}")
        c = _A31_ENVELOPE[cal]
    else:
        if alloc != Fraction(1, 240) or cal != Fraction(1, 276):
            raise PowerInputError("the A33 interpolated shift applies only to allocation 1/240 calibrated at 1/276")
        c = _A31_ENVELOPE[Fraction(1, 240)] + _A33_ALPHA_CAL_SHIFT
    return c, mode


def program_bound(scenario, n_main, n_reserve):
    """Union-bound arithmetic for a set of admissions (exact Fractions). Nothing here is certified.

    * governance_allocation: the sum of allocated alphas (the ledger quantity).
    * union_bound_at_test_levels: the sum of each test's calibration level from `test_level` (the mathematical
      union bound IF every test's size equals its calibration level; that premise is unvalidated).
    * bound_stated_if_alternative_adopted: only for the A33 owner alternative, n x 1.15 x alpha, the bound A33 §8
      says must be stated in those words if the alternative is adopted. Not certified either.
    * certified_bound: always None: no calibration has been independently validated."""
    sc = alpha_scenario(scenario)
    for name, n in (("n_main", n_main), ("n_reserve", n_reserve)):
        if type(n) is not int or n < 0:
            raise PowerInputError(f"{name} must be a non-negative int")
    if n_main + n_reserve > PROGRAM_MAX_ADMISSIONS:
        raise PowerInputError("more than 12 admissions needs a new owner-authorized program family (A31 §3)")
    allocation = n_main * sc.alpha_main + n_reserve * sc.alpha_reserve
    levels = n_main * test_level(scenario, "MAIN")[1] + n_reserve * test_level(scenario, "RESERVE")[1]
    stated = (allocation * A33_ALTERNATIVE_TOLERANCE if scenario == "A33_OWNER_ALTERNATIVE_CAL_1_240" else None)
    return {"scenario_status": sc.status, "governance_allocation": allocation,
            "union_bound_at_test_levels": levels, "bound_stated_if_alternative_adopted": stated,
            "certified_bound": None, "calibration_validated": False,
            "allocation_within_program_fwer": allocation <= PROGRAM_FWER}


@dataclass(frozen=True)
class MDEResult:
    value: float
    unit: str
    endpoint: str
    approximates_governed_test: bool
    illustrative_until_validated: bool
    critical_value: float
    cv_mode: str
    cv_status: str
    scenario: str
    scenario_status: str
    stream: str
    power: float
    assumptions: tuple
    caveats: tuple

    def __post_init__(self):
        if self.illustrative_until_validated is not True and self.cv_status not in VALIDATED_CV_STATUSES:
            raise ValueError("a result whose critical value is not independently validated must stay illustrative")


GOVERNED_CAVEATS = (
    "ILLUSTRATIVE UNTIL VALIDATED: no critical value has passed independent validation (A33 / A34-B not run).",
    "Normal approximation to the governed daily HAC test; futility looks, the skewness gate and finite-sample HAC "
    "bias are ignored.",
    "lrv_ratio (long-run variance / variance of the daily series) is an assumption, not a measurement.",
    "Insufficient power is not evidence of no edge.",
)
ILLUSTRATIVE_CAVEATS = (
    "ILLUSTRATIVE ONLY: per-trade planning arithmetic; it does not approximate the governed daily HAC test (DR-11).",
    "deff is an assumed variance-inflation factor; no day-clustering model is documented (DR-10).",
    "Insufficient power is not evidence of no edge.",
)
SHORT_HORIZON_CAVEAT = ("Planning horizon shorter than the governed 365-day final look: this is a planning figure "
                        "only and does not imply confirmation readiness.")
SMALL_SAMPLE_CAVEAT = "Effective sample below 30: the normal approximation is optimistic (a t correction is larger)."


def _daily_core(scenario, stream, cv_mode, days, lrv_ratio):
    d = _num("days", days, minimum=MIN_DAYS)
    if d > GOVERNED_MAX_DAYS:
        raise PowerInputError("the governed horizon is at most 365 days (no second-year extension)")
    lrv = _num("lrv_ratio", lrv_ratio, minimum=1)
    c, mode = critical_value(cv_mode, scenario, stream)
    return d, lrv, c, mode


def daily_hac_sharpe_mde(*, scenario, stream, cv_mode, power, days, lrv_ratio):
    """Minimum detectable annualized Sharpe (365-day annualization) of the daily net-excess series:
    (c + z_power) * sqrt(lrv_ratio) * sqrt(365 / days)."""
    d, lrv, c, mode = _daily_core(scenario, stream, cv_mode, days, lrv_ratio)
    value = _finite("MDE", (c + _power_z(power)) * sqrt(lrv) * sqrt(365.0 / d))
    return MDEResult(value, "annualized Sharpe of daily net excess", "daily_hac_sharpe", True, True, c, mode.name,
                     mode.status, scenario, alpha_scenario(scenario).status, stream, float(power),
                     (f"days={d:g}", f"lrv_ratio={lrv:g}", f"power={float(power):g}", "one-sided, final look"),
                     GOVERNED_CAVEATS + ((SHORT_HORIZON_CAVEAT,) if d < GOVERNED_MAX_DAYS else ()))


def power_daily_hac(*, scenario, stream, cv_mode, days, lrv_ratio, effect):
    """Normal-approximation power for a true annualized Sharpe `effect` (> 0)."""
    d, lrv, c, _ = _daily_core(scenario, stream, cv_mode, days, lrv_ratio)
    e = _num("effect", effect)
    return _N.cdf(e * sqrt(d / 365.0) / sqrt(lrv) - c)


def _trade_core(scenario, stream, cv_mode, sigma, deff, n1, n2):
    s = _num("sigma", sigma)
    f = _num("deff", deff, minimum=1)
    a = _num("n1", n1, minimum=MIN_TRADES)
    b = None if n2 is None else _num("n2", n2, minimum=MIN_TRADES)
    inv = 1.0 / a if b is None else 1.0 / a + 1.0 / b
    se = _finite("standard error", s * sqrt(f * inv))
    if se == 0:
        raise PowerInputError("the standard error underflows to zero for these inputs")
    c, mode = critical_value(cv_mode, scenario, stream)
    n_eff = (a if b is None else min(a, b)) / f
    return s, f, a, b, se, c, mode, n_eff


def per_trade_mde_illustrative(*, scenario, stream, cv_mode, power, sigma, deff, n1, n2=None):
    """ILLUSTRATIVE per-trade MDE in the units of `sigma`.

    One-sample (n2 None): k * sigma * sqrt(deff / n1). Two-group difference: k * sigma * sqrt(deff * (1/n1 + 1/n2)),
    the A42 l.238 / A45 l.169 form (equal sigma, independent arms). k = c + z(power)."""
    s, f, a, b, se, c, mode, n_eff = _trade_core(scenario, stream, cv_mode, sigma, deff, n1, n2)
    value = _finite("MDE", (c + _power_z(power)) * se)
    design = "one-sample mean" if b is None else "two-group difference in means"
    caveats = ILLUSTRATIVE_CAVEATS + ((SMALL_SAMPLE_CAVEAT,) if n_eff < 30 else ())
    return MDEResult(value, "per-trade mean (units of sigma)", "per_trade_illustrative", False, True, c, mode.name,
                     mode.status, scenario, alpha_scenario(scenario).status, stream, float(power),
                     (design, f"sigma={s:g}", f"deff={f:g}", f"n1={a:g}", "n2=None" if b is None else f"n2={b:g}",
                      f"power={float(power):g}"), caveats)


def power_per_trade_illustrative(*, scenario, stream, cv_mode, sigma, deff, n1, effect, n2=None):
    """ILLUSTRATIVE normal-approximation power for a true per-trade effect (> 0, units of sigma)."""
    _, _, _, _, se, c, _, _ = _trade_core(scenario, stream, cv_mode, sigma, deff, n1, n2)
    return _N.cdf(_num("effect", effect) / se - c)


def required_trades_illustrative(*, scenario, stream, cv_mode, power, sigma, deff, effect):
    """ILLUSTRATIVE one-sample trade count needed to detect `effect` (same units as sigma)."""
    s, f, e = _num("sigma", sigma), _num("deff", deff, minimum=1), _num("effect", effect)
    c, _ = critical_value(cv_mode, scenario, stream)
    ratio = (c + _power_z(power)) * s / e
    return _finite("required trades", ratio * ratio * f)    # multiplication overflows to inf, never raises


def _sizes(cluster_sizes):
    if type(cluster_sizes) not in (list, tuple):
        raise PowerInputError("cluster_sizes must be an in-memory list or tuple of ints")
    if not cluster_sizes:
        raise PowerInputError("cluster_sizes must not be empty")
    for m in cluster_sizes:
        if type(m) is not int or m < 1:
            raise PowerInputError("every cluster size must be an exact int >= 1")
        _num("cluster size", m)          # refuses sizes too large for a finite float
    return list(cluster_sizes)


def deff_bound_any_within_cluster(cluster_sizes):
    """Conservative design-effect bound for PER-TRADE linear statistics: max cluster size.

    For T = sum_i w_i X_i with fixed (outcome-independent) weights, finite variances and zero covariance between
    clusters: Var(sum_{i in c} w_i X_i) <= (sum |w_i| sd_i)^2 <= m_c * sum w_i^2 sd_i^2 (Cauchy-Schwarz), so
    Var(T) <= max_c m_c * sum_i w_i^2 sd_i^2. The baseline is the independent-observation variance sum w_i^2 sd_i^2,
    so a single `sigma` used with it must be the weighted RMS of the per-trade sds. Any within-cluster covariance
    (including negative) and unequal sizes are allowed. When several arms share a day, m_c counts ALL trades of all
    arms in that cluster. It does NOT cover cross-cluster dependence (serial correlation across days, positions open
    over several days) and it does not apply to the daily HAC endpoint, whose inflation is that serial dependence
    (lrv_ratio). Computed from counts alone it is a planning bound, never a measured variance inflation factor."""
    return float(max(_sizes(cluster_sizes)))


def deff_exchangeable_homoskedastic(cluster_sizes, icc):
    """DEFF = 1 + (m_w - 1) * icc, m_w = sum m^2 / sum m. Valid ONLY for equal variances, exchangeable within-cluster
    correlation `icc` in [0, 1] and independent clusters. Heteroskedastic clusters can exceed it (see DR-10)."""
    sizes = _sizes(cluster_sizes)
    rho = _num("icc", icc, allow_zero=True)
    if rho > 1:
        raise PowerInputError("icc must lie in [0, 1]")
    return 1 + (sum(m * m for m in sizes) / sum(sizes) - 1) * rho


def n_eff_lower_bound_any_within_cluster(cluster_sizes):
    """Lower bound on the effective sample size, N / max(m), under the assumptions of
    `deff_bound_any_within_cluster`. With unequal clusters it can be below the number of clusters."""
    sizes = _sizes(cluster_sizes)
    return sum(sizes) / max(sizes)


def canonical_table():
    """Deterministic text table of Sharpe MDEs for every applicable (scenario, stream, mode) at 365 days."""
    lines = [f"# {VERSION} daily-HAC Sharpe MDE, 365 days, power 0.8, normal approximation - ILLUSTRATIVE UNTIL "
             "VALIDATED",
             "scenario | status | stream | cv_mode | cv_status | c | lrv 1 | 1.5 | 2 | 3"]
    for sname in sorted(ALPHA_SCENARIOS):
        for stream in STREAMS:
            for mname in sorted(CRITICAL_VALUE_MODES):
                try:
                    c, m = critical_value(mname, sname, stream)
                except PowerInputError:
                    continue
                row = [daily_hac_sharpe_mde(scenario=sname, stream=stream, cv_mode=mname, power=0.8, days=365,
                                            lrv_ratio=r).value for r in (1, 1.5, 2, 3)]
                lines.append(f"{sname} | {ALPHA_SCENARIOS[sname].status} | {stream} | {mname} | {m.status} | "
                             f"{c:.4f} | " + " | ".join(f"{v:.3f}" for v in row))
    lines.append("Insufficient power is not evidence of no edge. No row is a binding governance choice, and no "
                 "critical value is independently validated.")
    return "\n".join(lines) + "\n"


def main():
    print(canonical_table(), end="")


if __name__ == "__main__":
    main()
