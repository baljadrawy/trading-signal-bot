"""T1 resistance-cap policy — one definition for the analyzer and the research copy.

The analyzer caps T1 at 0.99 × "resistance" when 1R lies above it. Which level counts as
resistance is a versioned policy, selected by ``T1_CAP_POLICY`` (the W3 options of
STRATEGY_AND_EXECUTION_CONTRACT.md SE-40 / SE-80):

* ``legacy_window_v1`` (default): the max high of the last 20 bars, **including the decision bar**.
  This is the production rule unchanged (SE-03). For a momentum breakout (close above the prior
  20-bar high) that max is the breakout bar's own high, so its upper wick caps T1 (A45 W3, A46). It
  is kept as the default so that no deployed behaviour changes until the owner switches it.
* ``prior_window_v1`` (SE-40 option a, the A45 correction): the max high of the 20 bars before the
  decision bar. For a momentum breakout that level is below entry, so the cap never binds there.
* ``independent_swing_v1`` (SE-40 option b): A46 G1 (``a46-g1-independent-resistance-v1``). The
  nearest confirmed swing high above entry among bars that closed before the decision bar; no such
  level -> T1 = 1R.
* ``no_cap_v1`` (SE-40 option c): no structure reference; T1 is always the fixed 1R multiple.

Every option falls back to T1 = 1R when no admissible reference above entry exists (SE-40.3).
Options other than the legacy one apply to the ``momentum`` and ``reversion`` setups only; the
legacy (``trade_type=None``) path always uses the legacy window. Switching the policy changes signal
geometry, so it is a declared strategy-version boundary that needs owner approval (SE-80, SE-65).
A correct cap is an engineering correction, not evidence of an edge.

``t1_reference`` returns the SE-40.2 provenance of a T1 (policy, reference value, reference bar,
source). ``bracket_reason`` and ``t1_cost_reason`` evaluate SE-40.4 and SE-40.5 and return the
canonical funnel code or None. Whether a T1 that is not cost-feasible is rejected or takes a declared
fallback is an owner decision (SE-80); this module only reports it, and takes the break-even level as
an explicit input.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

LEGACY_WINDOW_V1 = "legacy_window_v1"
INDEPENDENT_SWING_V1 = "independent_swing_v1"
PRIOR_WINDOW_V1 = "prior_window_v1"
NO_CAP_V1 = "no_cap_v1"
T1_CAP_POLICIES = (LEGACY_WINDOW_V1, INDEPENDENT_SWING_V1, PRIOR_WINDOW_V1, NO_CAP_V1)
RESISTANCE_FILL = 0.99
WINDOW = 20

# SE-40.2 provenance vocabulary and the declared fallback (SE-40.3).
T1_SOURCE_STRUCTURE = "structure"
T1_SOURCE_R_MULTIPLE_FALLBACK = "r_multiple_fallback"
T1_FALLBACK = "r_multiple_1r"
# Canonical funnel codes (shared/funnel_records.py; OPPORTUNITY_FUNNEL.md 8.2 and WP-IR-01).
REASON_BRACKET_INVALID = "F5.bracket_invalid"
REASON_T1_NOT_COST_FEASIBLE = "F5.t1_not_cost_feasible"

_STRUCTURE_SETUPS = ("momentum", "reversion")


def t1_cap_policy(cfg) -> str:
    """The configured T1_CAP_POLICY; an unknown value refuses to start (fail closed)."""
    policy = str(getattr(cfg, "T1_CAP_POLICY", LEGACY_WINDOW_V1)).strip().lower()
    if policy not in T1_CAP_POLICIES:
        raise RuntimeError(f"unknown T1_CAP_POLICY {policy!r}; expected one of {T1_CAP_POLICIES}")
    return policy


def legacy_window_resistance(df) -> float:
    """Production rule: max high of the last 20 bars, the decision bar included."""
    return float(df.tail(WINDOW)["high"].max())


def prior_window_resistance(df) -> float | None:
    """Option a: max high of the 20 bars before the decision bar (the decision bar excluded).
    None when that window is empty or holds no finite high."""
    prior = df["high"].iloc[-(WINDOW + 1):-1].astype(float)
    finite = [h for h in prior.values if math.isfinite(h)]
    return max(finite) if finite else None


def independent_swing_resistance(df, entry: float) -> float | None:
    """A46 G1 reference: the NEAREST confirmed swing high above entry among bars that closed
    before the decision bar. A swing high's high exceeds the highs of the two bars on each side
    (all five already closed). Non-finite highs never qualify. None when no such level exists."""
    prior = df.iloc[:-1]["high"].astype(float).values
    best = None
    for i in range(2, len(prior) - 2):
        h = prior[i]
        if not math.isfinite(h):
            continue
        if h > entry and h > max(prior[i - 2], prior[i - 1], prior[i + 1], prior[i + 2]):
            best = h if best is None else min(best, h)
    return best


def resistance_for(df, entry: float, trade_type, policy: str) -> float | None:
    """The resistance level the cap compares against under ``policy`` (None = no reference)."""
    if policy not in T1_CAP_POLICIES:
        raise RuntimeError(f"unknown T1_CAP_POLICY {policy!r}")
    if policy != LEGACY_WINDOW_V1 and trade_type in _STRUCTURE_SETUPS:
        if policy == INDEPENDENT_SWING_V1:
            return independent_swing_resistance(df, entry)
        if policy == PRIOR_WINDOW_V1:
            return prior_window_resistance(df)
        return None                                            # NO_CAP_V1
    return legacy_window_resistance(df)


def capped_t1(entry: float, risk: float, resistance: float | None) -> float:
    """If 1R > resistance > entry and 0.99 × resistance > entry, T1 = 0.99 × resistance;
    otherwise T1 = 1R. Identical to the analyzer's rule."""
    t1 = entry + risk
    if resistance is not None and t1 > resistance > entry:
        fill = resistance * RESISTANCE_FILL
        if fill > entry:
            t1 = fill
    return t1


# ── SE-40 provenance and invariant checks ──────────────────────────────────

@dataclass(frozen=True)
class T1Reference:
    """SE-40.2 provenance of one T1. ``bar_offset`` counts bars back from the decision bar
    (0 = the decision bar itself); ``bar_close_time`` is that bar's ``close_time`` when the frame
    carries one. Both are None when the policy used no reference level."""
    policy: str
    value: float | None
    bar_offset: int | None
    bar_close_time: int | None
    t1: float
    t1_source: str
    fallback: str = T1_FALLBACK


def _latest_position(highs, positions, value) -> int | None:
    found = None
    for pos, h in zip(positions, highs):
        if h == value:
            found = pos
    return found


def _reference_position(df, entry: float, trade_type, policy: str, value) -> int | None:
    """Row position in ``df`` of the bar that sets ``value`` (the latest one on ties)."""
    if value is None or not math.isfinite(value):
        return None
    n = len(df)
    highs = df["high"].astype(float).values
    if policy == LEGACY_WINDOW_V1 or trade_type not in _STRUCTURE_SETUPS:
        start = max(0, n - WINDOW)
        return _latest_position(highs[start:], range(start, n), value)
    if policy == PRIOR_WINDOW_V1:
        start = max(0, n - 1 - WINDOW)
        return _latest_position(highs[start:n - 1], range(start, n - 1), value)
    # INDEPENDENT_SWING_V1: the latest confirmed swing high at that level (decision bar excluded)
    prior = highs[:n - 1]
    found = None
    for i in range(2, len(prior) - 2):
        if prior[i] == value and prior[i] > max(prior[i - 2], prior[i - 1], prior[i + 1], prior[i + 2]):
            found = i
    return found


def t1_reference(df, entry: float, risk: float, trade_type, policy: str) -> T1Reference:
    """T1 and its SE-40.2 provenance under ``policy``. ``t1`` equals ``capped_t1`` on the level
    ``resistance_for`` returns, so it is the analyzer's unrounded T1. Unknown policies refuse."""
    value = resistance_for(df, entry, trade_type, policy)
    t1 = capped_t1(entry, risk, value)
    finite = value is not None and math.isfinite(value)
    pos = _reference_position(df, entry, trade_type, policy, value) if finite else None
    close_time = None
    if pos is not None and "close_time" in df.columns:
        close_time = int(df["close_time"].iloc[pos])
    source = T1_SOURCE_R_MULTIPLE_FALLBACK if t1 == entry + risk else T1_SOURCE_STRUCTURE
    return T1Reference(policy=policy, value=float(value) if finite else None,
                       bar_offset=None if pos is None else len(df) - 1 - pos,
                       bar_close_time=close_time, t1=t1, t1_source=source)


def bracket_reason(stop: float, entry: float, t1: float, t2: float, t3: float) -> str | None:
    """SE-40.4: ``stop < entry < T1 < T2 < T3`` on the rounded prices, else ``F5.bracket_invalid``."""
    values = (stop, entry, t1, t2, t3)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        return REASON_BRACKET_INVALID
    if stop < entry < t1 < t2 < t3:
        return None
    return REASON_BRACKET_INVALID


def flat_round_trip_break_even(entry: float, round_trip_cost_pct: float) -> float:
    """Net break-even exit price under a flat round-trip charge on entry notional. The charge is a
    required input (for research, the charter's proposed values); there is no default."""
    for name, v in (("entry", entry), ("round_trip_cost_pct", round_trip_cost_pct)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{name} must be a finite number")
    if entry <= 0 or round_trip_cost_pct < 0:
        raise ValueError("entry must be positive and round_trip_cost_pct non-negative")
    return entry * (1.0 + round_trip_cost_pct / 100.0)


def t1_cost_reason(t1: float, net_break_even: float) -> str | None:
    """SE-40.5: T1 must lie strictly above the active cost model's net break-even level, else
    ``F5.t1_not_cost_feasible``. Reject versus declared fallback is the owner's choice (SE-80)."""
    for name, v in (("t1", t1), ("net_break_even", net_break_even)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{name} must be a finite number")
    return None if t1 > net_break_even else REASON_T1_NOT_COST_FEASIBLE
