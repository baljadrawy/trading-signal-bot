"""S5-PWR-1 outcome-free admissibility screen (`s5-pwr-1-v2`). Research only; production never imports it.

It compares the normal-approximation power implied by a candidate's DECLARED expected-effect range (a written
assumption, never an estimate from data) with the declared target power, under explicitly named scenarios.
* It never reads anything; every input is an exact in-memory number or a short label.
* It never admits, rejects, confirms or consumes alpha, and it refuses SUPERSEDED alpha scenarios.
* Every result is ILLUSTRATIVE UNTIL VALIDATED and records all effective inputs. No result can make a candidate
  eligible for reconsideration while no critical value is independently validated.
* Power below the target is not evidence of no edge.
"""
from dataclasses import dataclass
from statistics import NormalDist

from research.power import ladder_power as lp

VERSION = lp.VERSION
AT_OR_ABOVE_TARGET = "POWER_AT_OR_ABOVE_TARGET_UNDER_STATED_ASSUMPTIONS"
BELOW_TARGET = "POWER_BELOW_TARGET_UNDER_STATED_ASSUMPTIONS"
DEPENDS_ON_ASSUMPTIONS = "POWER_VERSUS_TARGET_DEPENDS_ON_ASSUMPTIONS"
UNKNOWN = "UNKNOWN_INPUTS"
STATUSES = (AT_OR_ABOVE_TARGET, BELOW_TARGET, DEPENDS_ON_ASSUMPTIONS, UNKNOWN)
UNITS = ("daily_hac_sharpe", "per_trade_illustrative")
FIXED_CAVEATS = (
    "Insufficient power is not evidence of no edge.",
    "No result of this screen is an admission, a rejection, a confirmation or an alpha allocation, and none "
    "authorizes one.",
    "Declared effects are written assumptions; they must not be estimated from protected or research-exposed outcomes.",
    "Implied power is a normal approximation and is ILLUSTRATIVE UNTIL VALIDATED.",
)
_UNUSED = {"daily_hac_sharpe": ("sigma", "n1", "n2"), "per_trade_illustrative": ("days",)}
_REQUIRED = {"daily_hac_sharpe": ("days",), "per_trade_illustrative": ("sigma", "n1")}
_N = NormalDist()


@dataclass(frozen=True, kw_only=True)
class CandidateDeclaration:
    """A written, outcome-free declaration. Labels are non-empty strings; every quantity is an exact number."""
    name: str
    unit: str
    scenario: str
    stream: str
    cv_mode: str
    power: object                        # declared target power, required (no default)
    source: str                          # where the declared effect comes from (literature, arithmetic, spec)
    effect_low: object = None
    effect_high: object = None
    sigma: object = None                 # per-trade only (same unit as the effect)
    n1: object = None                    # per-trade only: trades in arm 1 (or the one sample)
    n2: object = None                    # per-trade only: trades in arm 2 (None = one sample)
    days: object = None                  # daily only: forward days (30-365)
    dependence_low: object = None        # daily: lrv_ratio; per-trade: deff (>= 1)
    dependence_high: object = None


@dataclass(frozen=True, kw_only=True)
class ScreenResult:
    name: str
    status: str
    interpretation: str
    endpoint: str
    scenario: str
    scenario_status: str
    stream: str
    cv_mode: str
    cv_status: str
    critical_value: object
    target_power: float
    effect_low: object
    effect_high: object
    dependence_low: object
    dependence_high: object
    days: object
    sigma: object
    n1: object
    n2: object
    mde_at_dependence_low: object
    mde_at_dependence_high: object
    implied_power_min: object
    implied_power_max: object
    approximates_governed_test: bool
    illustrative_until_validated: bool = True
    reconsideration_eligible: bool = False
    reconsideration_blockers: tuple = ()
    caveats: tuple = FIXED_CAVEATS
    is_admission: bool = False
    consumes_alpha: bool = False
    is_evidence_of_no_edge: bool = False
    is_evidence_of_edge: bool = False
    version: str = VERSION

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        if self.is_admission or self.consumes_alpha or self.is_evidence_of_no_edge or self.is_evidence_of_edge:
            raise ValueError("a screen result is never an admission, an alpha use or evidence about an edge")
        validated = self.cv_status in lp.VALIDATED_CV_STATUSES
        if self.illustrative_until_validated is not True and not validated:
            raise ValueError("a result whose critical value is not independently validated must stay illustrative")
        if self.reconsideration_eligible and (self.reconsideration_blockers or not validated
                                              or self.status != AT_OR_ABOVE_TARGET):
            raise ValueError("reconsideration eligibility requires a validated critical value, no blockers and "
                             "power at or above target")


def _text(name, value):
    if type(value) is not str or not value.strip() or len(value) > 200:
        raise lp.PowerInputError(f"{name} must be a non-empty label of at most 200 characters")
    return value


def _validated_inputs(decl):
    """Validate every provided value (before any missing value can turn the result into UNKNOWN_INPUTS)."""
    if type(decl) is not CandidateDeclaration:
        raise lp.PowerInputError("screen() takes a CandidateDeclaration")
    for name, value in (("name", decl.name), ("source", decl.source)):
        _text(name, value)
    unit = lp._label("unit", decl.unit, UNITS)
    lp.critical_value(decl.cv_mode, decl.scenario, decl.stream)          # validates scenario, stream and mode
    if lp.alpha_scenario(decl.scenario).status == "SUPERSEDED":
        raise lp.PowerInputError(f"alpha scenario {decl.scenario} is SUPERSEDED; use ladder_power directly for "
                                 "labelled historical comparisons")
    target = lp._num("power", decl.power)
    lp._power_z(target)
    raw = {"effect_low": decl.effect_low, "effect_high": decl.effect_high, "sigma": decl.sigma, "n1": decl.n1,
           "n2": decl.n2, "days": decl.days, "dependence_low": decl.dependence_low,
           "dependence_high": decl.dependence_high}
    for name in _UNUSED[unit]:
        if raw[name] is not None:
            raise lp.PowerInputError(f"field {name} is not used by unit {unit}; leave it unset")
    vals = {}
    for name, value in raw.items():
        if value is None:
            vals[name] = None
        elif name == "effect_low":
            vals[name] = lp._num(name, value, positive=False)
        elif name == "effect_high":
            vals[name] = lp._num(name, value, positive=False)
        elif name in ("dependence_low", "dependence_high"):
            vals[name] = lp._num(name, value, minimum=1)
        else:
            vals[name] = lp._num(name, value)
    lo_e, hi_e = vals["effect_low"], vals["effect_high"]
    if (lo_e is not None and lo_e < 0) or (hi_e is not None and hi_e <= 0):
        raise lp.PowerInputError("a one-sided test of a positive effect needs effect_low >= 0 and effect_high > 0")
    if lo_e is not None and hi_e is not None and lo_e > hi_e:
        raise lp.PowerInputError("effect_low must not exceed effect_high")
    lo_d, hi_d = vals["dependence_low"], vals["dependence_high"]
    if lo_d is not None and hi_d is not None and lo_d > hi_d:
        raise lp.PowerInputError("dependence_low must not exceed dependence_high")
    return unit, target, vals


def _mde(decl, unit, vals, dependence):
    if unit == "daily_hac_sharpe":
        return lp.daily_hac_sharpe_mde(scenario=decl.scenario, stream=decl.stream, cv_mode=decl.cv_mode,
                                       power=decl.power, days=decl.days, lrv_ratio=dependence)
    return lp.per_trade_mde_illustrative(scenario=decl.scenario, stream=decl.stream, cv_mode=decl.cv_mode,
                                         power=decl.power, sigma=decl.sigma, deff=dependence, n1=decl.n1, n2=decl.n2)


def screen(decl):
    """Screen one CandidateDeclaration. Raises PowerInputError for refused inputs (types, signs, scenario, fields)."""
    unit, target, vals = _validated_inputs(decl)
    c, mode = lp.critical_value(decl.cv_mode, decl.scenario, decl.stream)
    sc = lp.alpha_scenario(decl.scenario)
    governed = unit == "daily_hac_sharpe"
    common = dict(name=decl.name, endpoint=unit, scenario=decl.scenario, scenario_status=sc.status,
                  stream=decl.stream, cv_mode=decl.cv_mode, cv_status=mode.status, critical_value=c,
                  target_power=target, effect_low=vals["effect_low"], effect_high=vals["effect_high"],
                  dependence_low=vals["dependence_low"], dependence_high=vals["dependence_high"],
                  days=vals["days"], sigma=vals["sigma"], n1=vals["n1"], n2=vals["n2"],
                  approximates_governed_test=governed)
    needed = ("effect_low", "effect_high", "dependence_low", "dependence_high") + _REQUIRED[unit]
    if any(vals[n] is None for n in needed):
        return ScreenResult(status=UNKNOWN, interpretation="Required inputs are missing. No power statement is "
                            "possible.", mde_at_dependence_low=None, mde_at_dependence_high=None,
                            implied_power_min=None, implied_power_max=None,
                            reconsideration_blockers=("required inputs are missing",), **common)
    m_lo = _mde(decl, unit, vals, vals["dependence_low"])
    m_hi = _mde(decl, unit, vals, vals["dependence_high"])
    k = c + _N.inv_cdf(target)
    p_min = _N.cdf(vals["effect_low"] / (m_hi.value / k) - c)       # smallest effect, strongest dependence
    p_max = _N.cdf(vals["effect_high"] / (m_lo.value / k) - c)      # largest effect, weakest dependence
    if vals["effect_low"] >= m_hi.value:
        status = AT_OR_ABOVE_TARGET
        text = (f"Estimated power is at least {p_min:.3f}, at or above the declared target {target:g}, for every "
                "stated assumption. This is not evidence of an edge, not an admission, and consumes no alpha.")
    elif vals["effect_high"] < m_lo.value:
        status = BELOW_TARGET
        text = (f"Estimated power is at most {p_max:.3f}, below the declared target {target:g}, for every stated "
                "assumption. Insufficient power is not evidence of no edge.")
    else:
        status = DEPENDS_ON_ASSUMPTIONS
        drivers = [d for d, wide in (("declared effect range", vals["effect_low"] < vals["effect_high"]),
                                     ("assumed dependence range", vals["dependence_low"] < vals["dependence_high"]))
                   if wide]
        text = (f"Estimated power ranges from {p_min:.3f} to {p_max:.3f} around the declared target {target:g}; "
                f"the result depends on the {' and the '.join(drivers)}. Insufficient power is not evidence of no "
                "edge.")
    blockers = []
    if not governed:
        blockers.append("per-trade endpoint is illustrative and does not approximate the governed test")
    if sc.status != "GOVERNANCE_CONFIRMED":
        blockers.append(f"alpha scenario status is {sc.status}, not governance-confirmed")
    if mode.status not in lp.VALIDATED_CV_STATUSES:
        blockers.append(f"critical value ({mode.status}) is not independently validated")
    if status != AT_OR_ABOVE_TARGET:
        blockers.append("power is not at or above the declared target for every stated assumption")
    caveats = FIXED_CAVEATS + tuple(dict.fromkeys(m_lo.caveats + m_hi.caveats))
    return ScreenResult(status=status, interpretation=text, mde_at_dependence_low=m_lo.value,
                        mde_at_dependence_high=m_hi.value, implied_power_min=p_min, implied_power_max=p_max,
                        reconsideration_blockers=tuple(blockers), caveats=caveats, **common)


def max_dependence_for_mde(*, unit, scenario, stream, cv_mode, target_mde, power, days=None, sigma=None, n1=None,
                           n2=None):
    """Largest lrv_ratio / deff (>= 1) at which the MDE stays <= target_mde (MDE scales with sqrt(dependence))."""
    lp._label("unit", unit, UNITS)
    if lp.alpha_scenario(scenario).status == "SUPERSEDED":
        raise lp.PowerInputError(f"alpha scenario {scenario} is SUPERSEDED; use ladder_power directly for labelled "
                                 "historical comparisons")
    given = {"days": days, "sigma": sigma, "n1": n1, "n2": n2}
    for name in _UNUSED[unit]:
        if given[name] is not None:
            raise lp.PowerInputError(f"field {name} is not used by unit {unit}; leave it unset")
    t = lp._num("target_mde", target_mde)
    if unit == "daily_hac_sharpe":
        base = lp.daily_hac_sharpe_mde(scenario=scenario, stream=stream, cv_mode=cv_mode, power=power, days=days,
                                       lrv_ratio=1).value
    else:
        base = lp.per_trade_mde_illustrative(scenario=scenario, stream=stream, cv_mode=cv_mode, power=power,
                                             sigma=sigma, deff=1, n1=n1, n2=n2).value
    ratio = lp._finite("dependence ratio", (t / base) * (t / base))
    if ratio < 1:
        raise lp.PowerInputError("target_mde is below the MDE for independent data (dependence 1); no dependence "
                                 ">= 1 achieves it")
    return ratio
