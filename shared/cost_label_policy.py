"""Tracker cost booking under ``legacy_tracker_v1`` and the R4 single-count alternatives.

``trade_tracker/main.py`` books every cost through the bound model of ``shared/cost_models.py``
(``legacy_tracker_v1_from_config``). This module adds the two flagged R4 alternatives; both are
derived from that same registered model, and neither selects a research model (WP-IR-07).

**R4.a / R4.e (WP-E07): ``net_single_count_legacy_v1``.** The legacy flat round trip
``FEE_ROUNDTRIP_PCT`` is documented as fee plus a slippage allowance (``shared/config.py:L89-91``;
registry attribution ``fee_part_pct`` 0.2 + ``slippage_allowance_pct`` 0.1), while every stop exit
already fills at ``stop × (1 − STOP_SLIPPAGE)`` (``shared/triple_barrier.py:L320``). The
single-count rule books:

* the fee once per leg, on that leg's executed notional, at ``fee_part_pct / 2`` per side;
* slippage once, where it occurs: inside the stop fill, which the stored gross already contains.
  Target exits fill at the target and observed-price exits at the observation, so the legacy
  model itself states no in-price cost for them (``shared/cost_models.py``, component
  ``stop_fill_slippage``). This is the ``a48-cost-v1`` convention
  (``shared/execution_calibration.py``) with spread not modelled.

The attribution 0.2 + 0.1 holds only for the code defaults 0.3 and 0.001. Any other runtime value
refuses (``require_single_count_basis``), so the services refuse to start instead of inventing a
split. The stored legacy columns (``profit_percent``, ``profit_usdt``, ``result``) and the risk-guard
input (``trade_tracker/main.py`` ``assess_new_trade_risk``, SE-11) stay on the legacy model.

**R4.b (WP-G06): ``single_count_legacy_v1`` break-even.** The legacy post-T1 stop is
``entry × (1 + 0.003) / (1 − 0.001)`` (``shared/triple_barrier.py:L92-96``): both cost terms.
SE-42 gives ``entry × (1 + c_entry) / (1 − c_exit)`` from per-side costs. With the single-count
costs above, an exit at stop S nets ``S (1 − s)(1 − f)`` against the outlay ``entry (1 + f)``, so the
level is ``entry (1 + f) / ((1 − s)(1 − f))``. The pinned formula divides by ``(1 − s)`` itself, so
the wrapper passes ``roundtrip_cost = (1 + f) / (1 − f) − 1`` and leaves ``shared/triple_barrier.py``
unchanged. The result is capped at T1 by the pinned code. This changes exits: a strategy-version
boundary (WP-G06; OQ-08, SE-82, SE-83). It is never the default.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

from shared import fees as _fees
from shared.accounting_flags import (BREAK_EVEN_POLICIES, LABEL_POLICIES, LEGACY_BREAK_EVEN,
                                     LEGACY_LABEL_POLICY, SINGLE_COUNT_BREAK_EVEN,
                                     SINGLE_COUNT_LABEL_POLICY)
from shared.cost_models import LegacyTrackerV1, legacy_tracker_v1_from_config

if _fees.LABEL_POLICY != LEGACY_LABEL_POLICY:              # one name, two modules: kept equal
    raise RuntimeError("shared.fees.LABEL_POLICY changed; update shared.accounting_flags")


class SingleCountBasisError(RuntimeError):
    """The runtime costs are not the values the registry attribution describes."""


def bound_costs(cfg) -> LegacyTrackerV1:
    """``legacy_tracker_v1`` bound to ``cfg`` (FEE_ROUNDTRIP_PCT, STOP_SLIPPAGE, TRADE_AMOUNT_USDT).
    Invalid values raise ``CostModelError``; the services call this once at start-up."""
    return legacy_tracker_v1_from_config(cfg)


def fee_per_side(bound: LegacyTrackerV1) -> float:
    """``fee_part_pct / 2 / 100`` of the registered legacy model (0.001 at the code defaults)."""
    require_single_count_basis(bound)
    return float(bound.model.parameter("fee_part_pct").value) / 2 / 100.0


def require_single_count_basis(bound: LegacyTrackerV1) -> None:
    if not bound.matches_code_defaults():
        raise SingleCountBasisError(
            f"single-count costs need the registry attribution of FEE_ROUNDTRIP_PCT 0.3 and "
            f"STOP_SLIPPAGE 0.001; runtime is {bound.fee_roundtrip_pct!r} / {bound.stop_slippage!r}")


def validate_policies(bound: LegacyTrackerV1, *, cost_label_policy: str, break_even_policy: str) -> None:
    """Start-up check: known policy names, and the single-count basis when either needs it."""
    if cost_label_policy not in LABEL_POLICIES:
        raise RuntimeError(f"unknown cost label policy {cost_label_policy!r}")
    if break_even_policy not in BREAK_EVEN_POLICIES:
        raise RuntimeError(f"unknown break-even policy {break_even_policy!r}")
    if SINGLE_COUNT_LABEL_POLICY == cost_label_policy or SINGLE_COUNT_BREAK_EVEN == break_even_policy:
        require_single_count_basis(bound)


def leg_notionals(*, notional: float, entry_price: float, target_fills: Iterable,
                  final_exit_price: float, remaining_fraction: float) -> list:
    """Executed notional of every leg: the entry (the configured notional), each target fill
    ``(fraction, price)`` and the final exit of the remaining fraction (omitted when 0)."""
    entry = float(entry_price)
    out = [float(notional)]
    for fraction, price in target_fills:
        out.append(float(notional) * float(fraction) * float(price) / entry)
    if float(remaining_fraction) > 0:
        out.append(float(notional) * float(remaining_fraction) * float(final_exit_price) / entry)
    return out


def single_count_close(bound: LegacyTrackerV1, gross_usdt: float, *, entry_price: float,
                       target_fills: Sequence, final_exit_price: float,
                       remaining_fraction: float) -> dict:
    """The economic fields of one close under ``net_single_count_legacy_v1``, with the same keys,
    rounding and labels as ``shared.fees.economic_close``. ``target_fills`` are
    ``(quantity_fraction, fill_price)`` pairs of ``trade_target_fills``."""
    if not math.isfinite(float(gross_usdt)):
        raise ValueError(f"single_count_close: non-finite gross {gross_usdt!r}")
    rate = fee_per_side(bound)
    legs = leg_notionals(notional=bound.configured_notional_usdt, entry_price=entry_price,
                         target_fills=target_fills, final_exit_price=final_exit_price,
                         remaining_fraction=remaining_fraction)
    cost = rate * sum(legs)
    if not math.isfinite(cost) or cost < 0:
        raise ValueError(f"single_count_close: invalid cost {cost!r}")
    net = round(round(float(gross_usdt), 4) - cost, 6)
    return {'cost_usdt': round(cost, 6), 'net_profit_usdt': net,
            'economic_result': _fees.economic_result(net), 'label_policy': SINGLE_COUNT_LABEL_POLICY}


def close_economics(bound: LegacyTrackerV1, policy: str, gross_usdt: float, **legs) -> dict:
    """The stored economic fields under ``policy``. The legacy policy ignores ``legs`` and is
    exactly ``bound.economic_close(gross_usdt)``."""
    if policy == LEGACY_LABEL_POLICY:
        return bound.economic_close(gross_usdt)
    if policy == SINGLE_COUNT_LABEL_POLICY:
        return single_count_close(bound, gross_usdt, **legs)
    raise RuntimeError(f"unknown cost label policy {policy!r}")


def close_booking(bound: LegacyTrackerV1, policy: str, **legs):
    """The booking function of one close, ``gross_usdt -> economic fields``, under ``policy``.
    Legacy: ``bound.economic_close`` itself (the leg data is not used)."""
    if policy == LEGACY_LABEL_POLICY:
        return bound.economic_close
    if policy == SINGLE_COUNT_LABEL_POLICY:
        return lambda gross_usdt: single_count_close(bound, gross_usdt, **legs)
    raise RuntimeError(f"unknown cost label policy {policy!r}")


def break_even_roundtrip(bound: LegacyTrackerV1) -> float:
    """``roundtrip_cost`` that makes the pinned break-even formula equal the single-count level."""
    f = fee_per_side(bound)
    return (1 + f) / (1 - f) - 1


def barrier_cost_kwargs(bound: LegacyTrackerV1, policy: str) -> dict:
    """Cost arguments of ``create_config_from_trade``. Legacy: ``bound.barrier_cost_kwargs()``."""
    if policy == LEGACY_BREAK_EVEN:
        return bound.barrier_cost_kwargs()
    if policy == SINGLE_COUNT_BREAK_EVEN:
        return {"stop_slippage": bound.stop_slippage, "roundtrip_cost": break_even_roundtrip(bound)}
    raise RuntimeError(f"unknown break-even policy {policy!r}")
