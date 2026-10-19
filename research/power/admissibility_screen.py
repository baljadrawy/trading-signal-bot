"""S5-PWR-1 outcome-free admissibility screen (`s5-pwr-1-v1`). Research only; production never imports it.

It compares a candidate's DECLARED expected-effect range (a written assumption, never an estimate from data) with
the minimum detectable effect under explicitly named governance scenarios. It is a planning aid:
* it never reads anything; every input is an in-memory number or a short label;
* it never admits, rejects, confirms or consumes alpha;
* its strongest negative statement is "underpowered under the stated assumptions", which is not evidence of no edge.
"""
from dataclasses import dataclass, field

from research.power import ladder_power as lp

VERSION = lp.VERSION
POWERED = "POWERED_UNDER_STATED_ASSUMPTIONS"
UNDERPOWERED = "UNDERPOWERED_UNDER_STATED_ASSUMPTIONS"
INDETERMINATE = "INDETERMINATE_UNDER_STATED_ASSUMPTIONS"
UNKNOWN = "UNKNOWN_INPUTS"
STATUSES = (POWERED, UNDERPOWERED, INDETERMINATE, UNKNOWN)
UNITS = ("daily_hac_sharpe", "per_trade_illustrative")

INTERPRETATION = {
    POWERED: "The declared effect range lies at or above the MDE for every stated assumption. This is not evidence "
             "of an edge, not an admission, and consumes no alpha.",
    UNDERPOWERED: "The declared effect range lies below the MDE for every stated assumption. Insufficient power is "
                  "not evidence of no edge; it means a 365-day final-look test would be unlikely to confirm it.",
    INDETERMINATE: "The answer depends on assumptions that are not measured (for example the design effect). "
                   "Measure them through a separately approved, outcome-free route before deciding.",
    UNKNOWN: "Required inputs are missing. No power statement is possible.",
}
FIXED_CAVEATS = (
    "Insufficient power is not evidence of no edge.",
    "No result of this screen is an admission, a rejection, a confirmation or an alpha allocation.",
    "Declared effects are written assumptions; they must not be estimated from protected or research-exposed outcomes.",
)


@dataclass(frozen=True)
class CandidateDeclaration:
    """A written, outcome-free declaration. Labels are short strings; every quantity is an in-memory number."""
    name: str
    unit: str
    scenario: str
    stream: str
    cv_mode: str
    effect_low: object = None
    effect_high: object = None
    sigma: object = None                 # per-trade only (same unit as the effect)
    n1: object = None                    # per-trade: trades in arm 1 (or the one sample)
    n2: object = None                    # per-trade: trades in arm 2 (None = one sample)
    days: object = None                  # daily: forward days (<= 365)
    dependence_low: object = None        # daily: lrv_ratio; per-trade: deff
    dependence_high: object = None
    power: object = 0.8
    source: str = ""


@dataclass(frozen=True)
class ScreenResult:
    name: str
    status: str
    interpretation: str
    mde_low_dependence: object
    mde_high_dependence: object
    governed: bool
    critical_value_status: str
    caveats: tuple = field(default=FIXED_CAVEATS)
    is_admission: bool = False
    consumes_alpha: bool = False
    is_evidence_of_no_edge: bool = False
    is_evidence_of_edge: bool = False
    version: str = VERSION


def _label(name, value):
    if not isinstance(value, str) or len(value) > 200:
        raise lp.PowerInputError(f"{name} must be a short label string")
    return value


def _mde(decl, dependence):
    if decl.unit == "daily_hac_sharpe":
        return lp.daily_hac_sharpe_mde(scenario=decl.scenario, stream=decl.stream, cv_mode=decl.cv_mode,
                                       power=decl.power, days=decl.days, lrv_ratio=dependence)
    return lp.per_trade_mde_illustrative(scenario=decl.scenario, stream=decl.stream, cv_mode=decl.cv_mode,
                                         power=decl.power, sigma=decl.sigma, deff=dependence, n1=decl.n1, n2=decl.n2)


def screen(decl):
    """Screen one CandidateDeclaration. Raises PowerInputError for refused inputs (types, horizon, scenario)."""
    if not isinstance(decl, CandidateDeclaration):
        raise lp.PowerInputError("screen() takes a CandidateDeclaration")
    for name in ("name", "unit", "scenario", "stream", "cv_mode", "source"):
        _label(name, getattr(decl, name))
    if decl.unit not in UNITS:
        raise lp.PowerInputError(f"unit must be one of {UNITS}")
    lp.critical_value(decl.cv_mode, decl.scenario, decl.stream)   # validates every name
    governed = decl.unit == "daily_hac_sharpe"
    needed = ["effect_low", "effect_high", "dependence_low", "dependence_high"]
    needed += ["days"] if governed else ["sigma", "n1"]
    if any(getattr(decl, n) is None for n in needed):
        return ScreenResult(decl.name, UNKNOWN, INTERPRETATION[UNKNOWN], None, None, governed, "not computed")
    lo_e = lp._num("effect_low", decl.effect_low, positive=False)
    hi_e = lp._num("effect_high", decl.effect_high, positive=False)
    if lo_e > hi_e:
        raise lp.PowerInputError("effect_low must not exceed effect_high")
    lo_d, hi_d = (lp._num(n, getattr(decl, n)) for n in ("dependence_low", "dependence_high"))
    if lo_d > hi_d:
        raise lp.PowerInputError("dependence_low must not exceed dependence_high")
    m_lo, m_hi = _mde(decl, lo_d), _mde(decl, hi_d)
    if lo_e >= m_hi.value:
        status = POWERED
    elif hi_e < m_lo.value:
        status = UNDERPOWERED
    else:
        status = INDETERMINATE
    return ScreenResult(decl.name, status, INTERPRETATION[status], m_lo.value, m_hi.value, governed,
                        m_lo.critical_value_status,
                        FIXED_CAVEATS + (() if governed else lp.ILLUSTRATIVE_CAVEATS[:1]))


def max_dependence_for_mde(*, unit, scenario, stream, cv_mode, target_mde, power, days=None, sigma=None, n1=None,
                           n2=None):
    """Largest lrv_ratio / deff at which the MDE stays <= target_mde (MDE scales with sqrt(dependence))."""
    t = lp._num("target_mde", target_mde)
    if unit == "daily_hac_sharpe":
        base = lp.daily_hac_sharpe_mde(scenario=scenario, stream=stream, cv_mode=cv_mode, power=power, days=days,
                                       lrv_ratio=1).value
    elif unit == "per_trade_illustrative":
        base = lp.per_trade_mde_illustrative(scenario=scenario, stream=stream, cv_mode=cv_mode, power=power,
                                             sigma=sigma, deff=1, n1=n1, n2=n2).value
    else:
        raise lp.PowerInputError(f"unit must be one of {UNITS}")
    return (t / base) ** 2
