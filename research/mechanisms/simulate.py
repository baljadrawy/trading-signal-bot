"""Daily portfolio accountant for mechanism research (s4-mech-v1).

Timing: the rule sees closes up to day t (a view that cannot index the future), the target weights
are traded at close t and held to close t + 1. Before trading, the previous weights have drifted
with the day's returns; turnover is the sum of absolute changes from the drifted weights.

    gross[t+1] = sum_i w[t, i] * r[t+1, i]          (cash earns 0)
    cost[t]    = costs.cost(turnover[t])            (charged on day t's trade)
    net[t+1]   = gross[t+1] - cost[t]

The positions open at the end are reported, not liquidated.

**Data permission.** ``run`` refuses input unless ``permission`` is the synthetic marker or a
recorded permission whose licence is cleared and which excludes every protected holdout. This
encodes the governance boundary; it does not replace the owner's data decisions.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from research.mechanisms.costs import CostModel, tracker_flat_cost

EPS = 1e-12


class SimulationError(ValueError):
    """Refused input: data permission, shape, prices or weights."""


@dataclass(frozen=True)
class DatasetPermission:
    source: str
    licence_cleared: bool
    holdout_excluded: bool
    reference: str          # owner decision / record that grants the use
    synthetic: bool = False

    def allows(self) -> bool:
        if self.synthetic:
            return self.source == "synthetic"
        return (self.licence_cleared is True and self.holdout_excluded is True
                and bool(self.source.strip()) and bool(self.reference.strip()))


SYNTHETIC = DatasetPermission("synthetic", True, True, "generated in tests", synthetic=True)


class _Past(Sequence):
    """Read-only view of series[0 .. t]; indexing beyond t raises IndexError."""
    __slots__ = ("_s", "_n")

    def __init__(self, series, t):
        self._s, self._n = series, t + 1

    def __len__(self):
        return self._n

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self._s[j] for j in range(*i.indices(self._n))]
        if i < 0:
            i += self._n
        if not 0 <= i < self._n:
            raise IndexError("future data is not visible at decision time")
        return self._s[i]


@dataclass(frozen=True)
class Result:
    days: int
    gross: list = field(repr=False)
    cost: list = field(repr=False)
    net: list = field(repr=False)
    turnover: list = field(repr=False)
    final_weights: dict = field(repr=False)
    tracker_flat_cost_total: float = 0.0
    evidence_class: str = "SYNTHETIC_OR_EXPLORATORY_NOT_CONFIRMATORY"

    @property
    def total_turnover(self) -> float:
        return sum(self.turnover)

    @property
    def total_cost(self) -> float:
        return sum(self.cost)


def _check_prices(closes) -> int:
    if not isinstance(closes, Mapping) or not closes:
        raise SimulationError("closes must be a non-empty mapping asset -> series")
    lengths = {len(v) for v in closes.values()}
    if len(lengths) != 1:
        raise SimulationError("all series must be aligned (same length)")
    n = lengths.pop()
    for a, s in closes.items():
        for x in s:
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0:
                raise SimulationError(f"{a}: prices must be finite and > 0")
    return n


def _check_weights(w, assets, allow_short) -> dict:
    if not isinstance(w, Mapping):
        raise SimulationError("rule must return a mapping")
    out = {}
    for a, x in w.items():
        if a not in assets:
            raise SimulationError(f"unknown asset {a!r}")
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
            raise SimulationError(f"{a}: non-finite weight")
        if x < 0 and not allow_short:
            raise SimulationError(f"{a}: short weight on a long-only market")
        if x != 0:
            out[a] = float(x)
    if sum(abs(x) for x in out.values()) > 1 + 1e-9:
        raise SimulationError("gross exposure above 1 (no leverage)")
    return out


def run(closes, rule, *, costs: CostModel, permission: DatasetPermission, start: int,
        allow_short: bool) -> Result:
    if not isinstance(permission, DatasetPermission) or not permission.allows():
        raise SimulationError("dataset permission missing: synthetic marker or licence-cleared, "
                              "holdout-excluding record required")
    if not isinstance(costs, CostModel):
        raise SimulationError("costs must be a CostModel")
    if not isinstance(allow_short, bool):
        raise SimulationError("allow_short must be a bool")
    n = _check_prices(closes)
    if isinstance(start, bool) or not isinstance(start, int) or not 0 <= start < n - 1:
        raise SimulationError("start must be an int in [0, len - 2]")
    assets = tuple(closes)
    prev = {}
    gross, cost, net, turnover = [], [], [], []
    for t in range(start, n - 1):
        if t > start and prev:                     # drift yesterday's weights to today's close
            day = {a: closes[a][t] / closes[a][t - 1] - 1.0 for a in prev}
            port = sum(prev[a] * day[a] for a in prev)
            if 1 + port <= EPS:
                raise SimulationError("portfolio value reached zero")
            prev = {a: prev[a] * (1 + day[a]) / (1 + port) for a in prev}
        view = {a: _Past(closes[a], t) for a in assets}
        w = _check_weights(rule(view, t), assets, allow_short)
        to = sum(abs(w.get(a, 0.0) - prev.get(a, 0.0)) for a in set(w) | set(prev))
        c = costs.cost(to)
        g = sum(x * (closes[a][t + 1] / closes[a][t] - 1.0) for a, x in w.items())
        gross.append(g); cost.append(c); net.append(g - c); turnover.append(to)
        prev = w
    return Result(days=len(net), gross=gross, cost=cost, net=net, turnover=turnover,
                  final_weights=dict(prev),
                  tracker_flat_cost_total=tracker_flat_cost(sum(turnover) / 2.0))
