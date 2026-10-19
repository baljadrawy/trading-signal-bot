"""T1 resistance-cap policy — one definition for the analyzer and the research copy.

The analyzer caps T1 at 0.99 × "resistance" when 1R lies above it. Which level counts as
resistance is a versioned policy, selected by ``T1_CAP_POLICY``:

* ``legacy_window_v1`` (default): the max high of the last 20 bars, **including the decision bar**.
  This is the production rule unchanged. For a momentum breakout (close above the prior 20-bar
  high) that max is the breakout bar's own high, so its upper wick caps T1 (A45 W3, A46). It is
  kept as the default so that no deployed behaviour changes until the owner switches it.
* ``independent_swing_v1``: A46 G1 (``a46-g1-independent-resistance-v1``). The nearest confirmed
  swing high above entry among bars that closed before the decision bar; no such level -> T1 = 1R.

Applies to the ``momentum`` and ``reversion`` setups only; the legacy (``trade_type=None``) path
always uses the legacy window. Switching the policy changes signal geometry, so it is a declared
strategy-version boundary that needs owner approval. A correct cap is an engineering correction,
not evidence of an edge.
"""
from __future__ import annotations

import math

LEGACY_WINDOW_V1 = "legacy_window_v1"
INDEPENDENT_SWING_V1 = "independent_swing_v1"
T1_CAP_POLICIES = (LEGACY_WINDOW_V1, INDEPENDENT_SWING_V1)
RESISTANCE_FILL = 0.99
WINDOW = 20


def t1_cap_policy(cfg) -> str:
    """The configured T1_CAP_POLICY; an unknown value refuses to start (fail closed)."""
    policy = str(getattr(cfg, "T1_CAP_POLICY", LEGACY_WINDOW_V1)).strip().lower()
    if policy not in T1_CAP_POLICIES:
        raise RuntimeError(f"unknown T1_CAP_POLICY {policy!r}; expected one of {T1_CAP_POLICIES}")
    return policy


def legacy_window_resistance(df) -> float:
    """Production rule: max high of the last 20 bars, the decision bar included."""
    return float(df.tail(WINDOW)["high"].max())


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
    """The resistance level the cap compares against under ``policy``."""
    if policy not in T1_CAP_POLICIES:
        raise RuntimeError(f"unknown T1_CAP_POLICY {policy!r}")
    if policy == INDEPENDENT_SWING_V1 and trade_type in ("momentum", "reversion"):
        return independent_swing_resistance(df, entry)
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
