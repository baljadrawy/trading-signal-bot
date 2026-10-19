"""S5-PWR-1 Evidence Ladder power calculator (`s5-pwr-1-v1`). Research only; production never imports it.

Scope and limits (see docs/strategy/EVIDENCE_LADDER_PARAMETERS.md):
* Pure arithmetic on numbers the caller passes in memory. No file, database, network, environment or production
  access, and no default that could read as a binding governance choice: every calculation names its alpha
  scenario and its critical-value mode explicitly.
* The GOVERNED test (A32 §5, A33 §3) is a HAC-studentized (Bartlett L = 7) mean of the DAILY mark-to-market net
  excess, decided once at day 365. `daily_hac_sharpe_mde` approximates it with normal theory; it ignores the
  non-binding futility looks and the skewness gate, so simulated power (A31 §5, A32 §6) can differ.
* Per-trade figures (`per_trade_mde_illustrative`) reproduce the A42/A44/A45 planning arithmetic. They are
  ILLUSTRATIVE ONLY: they are not the governed test, and no mapping from per-trade units to the daily HAC statistic
  is established (discrepancy register DR-11).
* Critical values from A31 are in-sample envelope calibrations that were never independently validated (A31 §9,
  A33 not run, A34-B REVISE). They are labelled PROVISIONAL and are never presented as binding.
* Insufficient power is not evidence of no edge.
"""
from dataclasses import dataclass
from fractions import Fraction
from math import sqrt
from numbers import Real
from statistics import NormalDist

VERSION = "s5-pwr-1-v1"
GOVERNED_MAX_DAYS = 365          # A30 l.10, A31 l.13/19: 365-day maximum, no second-year extension
PROGRAM_MAX_ADMISSIONS = 12      # A31 l.20, A32 §4, A33 §7 (12 admissions per 3-year program, provisional)
PROGRAM_FWER = Fraction(1, 20)   # 5 % familywise false confirmation, union bound (A30 §4.2)
_N = NormalDist()


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
        "A33 §8 owner alternative: alpha_cal = 1/240 with tolerance CP upper <= 1.15 alpha (certified bound 5.75 %)"),
    "A30_HALF_WEIGHT_RESERVE": AlphaScenario(
        "A30_HALF_WEIGHT_RESERVE", Fraction(1, 240), Fraction(1, 480), Fraction(1, 240),
        "SUPERSEDED", "A30 §3 and §4 item 4 (RESERVE at alpha_j / 2); withdrawn by A32 §4"),
    "A31_RESERVE_0_21_PCT": AlphaScenario(
        "A31_RESERVE_0_21_PCT", Fraction(1, 240), Fraction(1, 480), Fraction(1, 240),
        "SUPERSEDED", "A31 §3 (equal fixed 0.42 %, RESERVE at half: 0.21 % = 0.05/24); withdrawn by A32 §4"),
}

CRITICAL_VALUE_MODES = {
    "NORMAL_THEORY": CriticalValueMode(
        "NORMAL_THEORY", "ANALYTIC_APPROXIMATION",
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


class PowerInputError(ValueError):
    """Raised for inputs the calculator refuses (wrong type, out of the governed range, unknown scenario)."""


def _num(name, value, *, positive=True, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (Real, Fraction)):
        raise PowerInputError(f"{name} must be an in-memory number, got {type(value).__name__}")
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):
        raise PowerInputError(f"{name} must be finite")
    if positive and (v < 0 or (v == 0 and not allow_zero)):
        raise PowerInputError(f"{name} must be > 0" if not allow_zero else f"{name} must be >= 0")
    return v


def _power_z(power):
    p = _num("power", power)
    if not 0.5 <= p < 1:
        raise PowerInputError("power must lie in [0.5, 1)")
    return _N.inv_cdf(p)


def alpha_scenario(name):
    try:
        return ALPHA_SCENARIOS[name]
    except (KeyError, TypeError):
        raise PowerInputError(f"unknown alpha scenario {name!r}; choose one of {sorted(ALPHA_SCENARIOS)}") from None


STREAMS = ("MAIN", "RESERVE")


def test_level(scenario, stream):
    """(allocated alpha, calibration level) of one test in `stream`. The calibration level scales with the
    allocation, so a scenario with equal MAIN / RESERVE allocation gives both streams the same level."""
    sc = alpha_scenario(scenario)
    if stream not in STREAMS:
        raise PowerInputError(f"stream must be one of {STREAMS}")
    alloc = sc.alpha_main if stream == "MAIN" else sc.alpha_reserve
    return alloc, sc.alpha_cal * alloc / sc.alpha_main


def critical_value(mode, scenario, stream):
    """Return (c, mode) for a named mode, alpha scenario and stream. Raises if the mode has no value there."""
    if mode not in CRITICAL_VALUE_MODES:
        raise PowerInputError(f"unknown critical-value mode {mode!r}; choose one of {sorted(CRITICAL_VALUE_MODES)}")
    alloc, cal = test_level(scenario, stream)
    if mode == "NORMAL_THEORY":
        c = _N.inv_cdf(1 - float(cal))
    elif mode == "A31_ENVELOPE_IN_SAMPLE":
        if cal not in _A31_ENVELOPE:
            raise PowerInputError("A31 reported envelope critical values only at alpha 1/80, 1/240 and 1/480; "
                                  f"{scenario}/{stream} calibrates at {cal}")
        c = _A31_ENVELOPE[cal]
    else:
        if alloc != Fraction(1, 240) or cal != Fraction(1, 276):
            raise PowerInputError("the A33 interpolated shift applies only to allocation 1/240 calibrated at 1/276")
        c = _A31_ENVELOPE[Fraction(1, 240)] + _A33_ALPHA_CAL_SHIFT
    return c, CRITICAL_VALUE_MODES[mode]


def program_bound(scenario, n_main, n_reserve):
    """Union-bound program FWER for the given admissions (exact Fraction). Refuses more than 12 admissions."""
    sc = alpha_scenario(scenario)
    for name, n in (("n_main", n_main), ("n_reserve", n_reserve)):
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise PowerInputError(f"{name} must be a non-negative int")
    if n_main + n_reserve > PROGRAM_MAX_ADMISSIONS:
        raise PowerInputError("more than 12 admissions needs a new owner-authorized program family (A31 §3)")
    allocated = n_main * sc.alpha_main + n_reserve * sc.alpha_reserve
    calibrated = (n_main + n_reserve) * sc.alpha_cal
    return {"allocated": allocated, "calibrated": calibrated, "within_fwer": allocated <= PROGRAM_FWER}


@dataclass(frozen=True)
class MDEResult:
    value: float
    unit: str
    governed: bool
    critical_value: float
    critical_value_mode: str
    critical_value_status: str
    alpha_scenario: str
    assumptions: tuple
    caveats: tuple


GOVERNED_CAVEATS = (
    "Normal approximation to the governed daily HAC test; futility looks and the skewness gate are ignored.",
    "lrv_ratio (long-run variance / variance of the daily series) is an assumption, not a measurement.",
    "Insufficient power is not evidence of no edge.",
)
ILLUSTRATIVE_CAVEATS = (
    "ILLUSTRATIVE ONLY: per-trade planning arithmetic, not the governed daily HAC test (DR-11).",
    "deff is an assumed variance-inflation factor; no day-clustering model is documented (DR-10).",
    "Insufficient power is not evidence of no edge.",
)


def daily_hac_sharpe_mde(*, scenario, stream, cv_mode, power, days, lrv_ratio):
    """Minimum detectable annualized Sharpe (365-day annualization) of the daily net-excess series."""
    d = _num("days", days)
    if d > GOVERNED_MAX_DAYS:
        raise PowerInputError("the governed horizon is at most 365 days (no second-year extension)")
    lrv = _num("lrv_ratio", lrv_ratio)
    if lrv < 1:
        raise PowerInputError("lrv_ratio below 1 assumes negative dependence; refused for planning")
    c, m = critical_value(cv_mode, scenario, stream)
    value = (c + _power_z(power)) * sqrt(lrv) * sqrt(365.0 / d)
    return MDEResult(value, "annualized Sharpe of daily net excess", True, c, m.name, m.status, f"{scenario}/{stream}",
                     (f"days={d:g}", f"lrv_ratio={lrv:g}", f"power={float(power):g}", "one-sided, final look"),
                     GOVERNED_CAVEATS)


def per_trade_mde_illustrative(*, scenario, stream, cv_mode, power, sigma, deff, n1, n2=None):
    """ILLUSTRATIVE per-trade MDE in the units of `sigma`.

    One-sample (n2 None): k * sigma * sqrt(deff / n1). Two-group difference: k * sigma * sqrt(deff * (1/n1 + 1/n2)),
    the A42 l.238 / A45 l.169 form. k = c + z(power)."""
    s, f = _num("sigma", sigma), _num("deff", deff)
    if f < 1:
        raise PowerInputError("deff below 1 is refused for planning")
    a = _num("n1", n1)
    inv = 1.0 / a if n2 is None else 1.0 / a + 1.0 / _num("n2", n2)
    c, m = critical_value(cv_mode, scenario, stream)
    value = (c + _power_z(power)) * s * sqrt(f * inv)
    design = "one-sample mean" if n2 is None else "two-group difference in means"
    return MDEResult(value, "per-trade mean (units of sigma)", False, c, m.name, m.status, f"{scenario}/{stream}",
                     (design, f"sigma={s:g}", f"deff={f:g}", f"n1={a:g}", f"n2={n2}", f"power={float(power):g}"),
                     ILLUSTRATIVE_CAVEATS)


def required_trades_illustrative(*, scenario, stream, cv_mode, power, sigma, deff, effect):
    """ILLUSTRATIVE one-sample trade count needed to detect `effect` (same units as sigma)."""
    s, f, e = _num("sigma", sigma), _num("deff", deff), _num("effect", effect)
    if f < 1:
        raise PowerInputError("deff below 1 is refused for planning")
    c, _ = critical_value(cv_mode, scenario, stream)
    k = c + _power_z(power)
    return (k * s / e) ** 2 * f


def deff_upper_bound(cluster_sizes):
    """Outcome-free upper bound on the day-clustering design effect from cluster sizes alone.

    DEFF = 1 + (m_w - 1) * rho with m_w = sum(m^2) / sum(m) (size-weighted mean cluster size). For a within-cluster
    correlation 0 <= rho <= 1 this is at most m_w. It assumes independence BETWEEN clusters, so cross-day dependence
    (overlapping positions, regimes) is not covered."""
    sizes = _sizes(cluster_sizes)
    return sum(m * m for m in sizes) / sum(sizes)


def deff_from_icc(cluster_sizes, icc):
    sizes = _sizes(cluster_sizes)
    rho = _num("icc", icc, allow_zero=True)
    if rho > 1:
        raise PowerInputError("icc must lie in [0, 1]")
    return 1 + (sum(m * m for m in sizes) / sum(sizes) - 1) * rho


def _sizes(cluster_sizes):
    if isinstance(cluster_sizes, (str, bytes, bytearray)) or not isinstance(cluster_sizes, (list, tuple)):
        raise PowerInputError("cluster_sizes must be an in-memory list or tuple of ints")
    if not cluster_sizes:
        raise PowerInputError("cluster_sizes must not be empty")
    for m in cluster_sizes:
        if isinstance(m, bool) or not isinstance(m, int) or m < 1:
            raise PowerInputError("every cluster size must be an int >= 1")
    return list(cluster_sizes)


def canonical_table():
    """Deterministic text table of governed Sharpe MDEs for every applicable (scenario, mode) pair at 365 days."""
    lines = [f"# {VERSION} governed daily-HAC Sharpe MDE, 365 days, power 0.8 (normal approximation)",
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
    lines.append("Insufficient power is not evidence of no edge. No row is a binding governance choice.")
    return "\n".join(lines) + "\n"


def main():
    print(canonical_table(), end="")


if __name__ == "__main__":
    main()
