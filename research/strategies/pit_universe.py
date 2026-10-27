"""Point-in-time (PIT) universe, delisting-aware accountant and monthly EW benchmark for HR-04/HR-08/HR-13.

Version ``hr04-pit-v1``. Pure and standard-library only; research only, never imported by production. Extends
``daily_tsmom`` (fixed aligned universe) to a ragged panel in which assets appear (listing) and disappear
(delisting) and the tradable universe is rebuilt every day from data available at that day only.

Panel
-----
``Panel(n_days, series)``: day index 0..n_days-1 (UTC daily closes). ``series[asset] = AssetSeries(first, close,
quote_volume, final_price_tradable)``: the asset has a close and a quote volume on days ``first .. last`` with
``last = first + len(close) - 1``. No value exists before listing or after delisting (survivorship: an asset that
stops trading inside the panel is kept, never removed from the input). ``last < n_days - 1`` means delisted at
``last``; ``final_price_tradable=False`` marks a delisting without a final tradable price (stress handling below).

PIT membership (no look-ahead)
------------------------------
``membership(panel, t, rule)`` uses only values on days <= t: eligible assets have a close on day t, at least
``rule.min_history`` closes up to t and are not excluded; each is scored by the trailing ``rule.volume_window``-day
quote volume ending at t (``sum`` or ``median``, fixed in the rule before data); the top ``rule.top_n`` by
(score descending, asset name) are members. Decisions read closes through ``simulate._Past`` views that raise on any
index after t. The listing/delisting dates themselves are exchange events (announced), not price data.

Strategy decision at close t: per member, HR-04 / HR-13 long/cash state from its trailing return (state is reset to
cash whenever the asset is not a member); weights 1/N with N = number of members at t (``equal``) or HR-08
inverse-vol over the members (``daily_tsmom.inverse_vol_weights``). Traded at close t + ``execution_lag``.

Accounting (step t: close t -> close t + 1)
-------------------------------------------
As ``daily_tsmom._account`` (drift, turnover = sum |dw|, ``CostModel`` per-side cost on traded notional, cash earns
0), plus:

* **universe exit**: a held asset that is no longer in the executed target is sold like any exit;
* **delisting = forced exit**: at its last day ``last`` an asset cannot be held over ``last -> last + 1``; whatever
  the target says, the position is sold at the last available close with full costs (counted in ``forced_exits``).
  An asset is never bought on its last day or before its listing.
* **stress**: with ``delist_haircut = h`` (default 0) and ``final_price_tradable=False`` the position is marked down by
  the fraction h at the exit (loss ``w * h`` booked in gross of that step; only ``w * (1 - h)`` is sold and costed).
  h = 1 is the "-100 %" variant of NEXT_LICENSED_DATA_STEP.md §2. First-order: weights are not re-normalized for the
  loss within the step.

Benchmark ``run_pit_benchmark``: equal-weight buy-and-hold of the PIT members, rebalanced to 1/N of the members on
the declared rebalance days only (``month_start_indices`` for calendar months, or a fixed period); between
rebalances it drifts; a delisted holding is force-exited to cash until the next rebalance. It pays every unit of its
own turnover through the same cost model and the same ``execution_lag``.

Data permission: refused unless ``permission`` is the synthetic marker or a recorded, licence-cleared,
holdout-excluding ``DatasetPermission``. Results carry ``evidence_class`` "SYNTHETIC" (synthetic marker) or
"EXPLORATORY_NOT_CONFIRMATORY" (permitted real data); never confirmatory.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

from research.mechanisms.costs import CostModel, tracker_flat_cost
from research.mechanisms.signals import realized_vol, trailing_return
from research.mechanisms.simulate import EPS, DatasetPermission, SimulationError, _Past
from research.strategies.daily_tsmom import (TSMOMConfig, TSMOMError, TSMOMResult, equal_weights,
                                             inverse_vol_weights, signal_state)

VERSION = "hr04-pit-v1"
SYNTHETIC_CLASS = "SYNTHETIC"
EXPLORATORY_CLASS = "EXPLORATORY_NOT_CONFIRMATORY"
VOLUME_STATISTICS = ("sum", "median")


def _finite_pos(x, what, allow_zero=False):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 or \
            (x == 0 and not allow_zero):
        raise SimulationError(f"{what} must be finite and {'>= 0' if allow_zero else '> 0'}")
    return float(x)


@dataclass(frozen=True)
class AssetSeries:
    first: int
    close: tuple
    quote_volume: tuple
    final_price_tradable: bool = True

    def __post_init__(self):
        if isinstance(self.first, bool) or not isinstance(self.first, int) or self.first < 0:
            raise SimulationError("first must be an int >= 0")
        object.__setattr__(self, "close", tuple(_finite_pos(x, "close") for x in self.close))
        object.__setattr__(self, "quote_volume", tuple(_finite_pos(x, "quote_volume", True)
                                                       for x in self.quote_volume))
        if not self.close or len(self.close) != len(self.quote_volume):
            raise SimulationError("close and quote_volume must be non-empty and aligned")

    @property
    def last(self) -> int:
        return self.first + len(self.close) - 1

    def has(self, t: int) -> bool:
        return self.first <= t <= self.last

    def at(self, t: int) -> float:
        if not self.has(t):
            raise SimulationError("no close outside the listed period")
        return self.close[t - self.first]


@dataclass(frozen=True)
class Panel:
    n_days: int
    series: dict
    dates: tuple | None = None          # optional UTC dates per day index (calendar rebalancing)

    def __post_init__(self):
        if isinstance(self.n_days, bool) or not isinstance(self.n_days, int) or self.n_days < 2:
            raise SimulationError("n_days must be an int >= 2")
        if not self.series:
            raise SimulationError("panel needs at least one asset")
        for a, s in self.series.items():
            if not isinstance(s, AssetSeries) or s.last >= self.n_days:
                raise SimulationError(f"{a}: series must be an AssetSeries inside the panel")
        if self.dates is not None:
            if len(self.dates) != self.n_days or any(not (hasattr(d, "year") and hasattr(d, "month")) for d in self.dates) or \
                    any(b <= a for a, b in zip(self.dates, self.dates[1:])):
                raise SimulationError("dates must be increasing dates, one per day")

    @property
    def assets(self) -> tuple:
        return tuple(sorted(self.series))

    def truncated(self, t: int) -> "Panel":
        """The panel as it would be known at close t (every value after t removed). For no-look-ahead checks."""
        keep = {}
        for a, s in self.series.items():
            if s.first <= t:
                k = min(s.last, t) - s.first + 1
                keep[a] = AssetSeries(s.first, s.close[:k], s.quote_volume[:k], s.final_price_tradable)
        return Panel(self.n_days, keep, self.dates)


@dataclass(frozen=True)
class UniverseRule:
    """Declared before data (NEXT_LICENSED_DATA_STEP.md §4): no defaults."""
    top_n: int
    volume_window: int
    min_history: int
    statistic: str
    exclude: frozenset = frozenset()

    def __post_init__(self):
        for name in ("top_n", "volume_window", "min_history"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise TSMOMError(f"{name} must be an int >= 1")
        if self.min_history < self.volume_window:
            raise TSMOMError("min_history must be >= volume_window")
        if self.statistic not in VOLUME_STATISTICS:
            raise TSMOMError(f"statistic must be one of {VOLUME_STATISTICS}")
        object.__setattr__(self, "exclude", frozenset(self.exclude))


def membership(panel: Panel, t: int, rule: UniverseRule) -> tuple:
    """PIT top-N members at close t, from quote volumes on days <= t only (sorted by name)."""
    scored = []
    for a, s in panel.series.items():
        if a in rule.exclude or not s.has(t) or t - s.first + 1 < rule.min_history:
            continue
        lo = t - s.first - rule.volume_window + 1
        window = s.quote_volume[lo: t - s.first + 1]
        score = sum(window) if rule.statistic == "sum" else median(window)
        scored.append((-score, a))
    scored.sort()
    return tuple(sorted(a for _, a in scored[:rule.top_n]))


def month_start_indices(dates) -> frozenset:
    """Day indices that open a new calendar month (and index 0)."""
    return frozenset(i for i, d in enumerate(dates) if i == 0 or (d.year, d.month) != (dates[i - 1].year,
                                                                                         dates[i - 1].month))


def period_indices(n_days: int, start: int, period: int) -> frozenset:
    return frozenset(range(start, n_days, period))


class _PITDecider:
    """Causal TSMOM decision on the PIT universe: called once per close, in order."""

    def __init__(self, config: TSMOMConfig, rule: UniverseRule):
        self.cfg, self.rule, self.state, self.last_t = config, rule, {}, None

    def __call__(self, panel: Panel, t: int) -> dict:
        if self.last_t is not None and t != self.last_t + 1:
            raise TSMOMError("decisions must be made on consecutive closes")
        self.last_t = t
        members = membership(panel, t, self.rule)
        cfg, views = self.cfg, {}
        for a in members:
            s = panel.series[a]
            views[a] = _Past(s.close, t - s.first)
        self.state = {a: signal_state(self.state.get(a, False), trailing_return(views[a], cfg.lookback, a), cfg.band)
                      for a in members}                       # non-members drop out: state reset to cash
        if not members:
            return {}
        in_assets = [a for a in members if self.state[a]]
        if cfg.weighting == "equal":
            return equal_weights(in_assets, len(members))
        vols = {a: realized_vol(views[a], cfg.vol_window, a) for a in members}
        return inverse_vol_weights(in_assets, vols, len(members), cfg.vol_cap)


@dataclass(frozen=True)
class PITResult(TSMOMResult):
    forced_exits: int = 0                      # delisting exits
    universe_exits: int = 0                    # exits because the asset left the executed target / universe
    member_counts: list = field(default_factory=list, repr=False)
    delist_loss: float = 0.0                   # total stress haircut booked (0 unless delist_haircut > 0)


def _evidence_class(permission) -> str:
    return SYNTHETIC_CLASS if permission.synthetic else EXPLORATORY_CLASS


def _account_pit(panel, decide, *, label, costs, permission, start, lag, rebalance, delist_haircut, rule):
    if not isinstance(permission, DatasetPermission) or not permission.allows():
        raise SimulationError("dataset permission missing: synthetic marker or licence-cleared, "
                              "holdout-excluding record required")
    if not isinstance(costs, CostModel):
        raise SimulationError("costs must be a CostModel (s4-mech-v1)")
    if not isinstance(panel, Panel):
        raise SimulationError("panel must be a Panel")
    if isinstance(start, bool) or not isinstance(start, int) or not 0 <= start < panel.n_days - 1:
        raise SimulationError("start must be an int in [0, n_days - 2]")
    h = _finite_pos(delist_haircut, "delist_haircut", True)
    if h > 1:
        raise SimulationError("delist_haircut must be in [0, 1]")
    S = panel.series
    decisions, prev = [], {}
    out = {k: [] for k in ("gross", "cost", "net", "turnover", "weights")}
    entries = exits = forced = uexits = 0
    loss_total, members = 0.0, []
    for t in range(start, panel.n_days - 1):
        if t > start and prev:                                    # drift: every held asset has a close at t
            day = {a: S[a].at(t) / S[a].at(t - 1) - 1.0 for a in prev}
            port = sum(prev[a] * day[a] for a in prev)
            if 1 + port <= EPS:
                raise SimulationError("portfolio value reached zero")
            prev = {a: prev[a] * (1 + day[a]) / (1 + port) for a in prev}
        decisions.append(decide(panel, t))
        members.append(len(membership(panel, t, rule)))
        target = decisions[-1 - lag] if len(decisions) > lag else None
        if target is None:                                        # hold (benchmark between rebalances)
            new = dict(prev)
        elif rebalance == "daily":
            new = {a: w for a, w in target.items() if w > 0}
        else:
            new = {a: w for a, w in prev.items() if target.get(a, 0.0) > 0}
            cash = 1.0 - sum(new.values())
            for a in sorted(target):
                if a not in new and target[a] > 0 and cash > EPS and S[a].has(t) and S[a].last > t:
                    new[a] = min(target[a], cash)
                    cash -= new[a]
        delisting = {a for a in set(new) | set(prev) if not S[a].has(t) or S[a].last <= t}
        new = {a: w for a, w in new.items() if a not in delisting}
        if any(w < 0 for w in new.values()) or sum(new.values()) > 1 + 1e-9:
            raise SimulationError("weights must be long-only with gross exposure <= 1")
        step_loss, sold_prev = 0.0, dict(prev)
        for a in prev:
            if a in delisting:
                forced += 1
                if h > 0 and not S[a].final_price_tradable:
                    step_loss += prev[a] * h
                    sold_prev[a] = prev[a] * (1 - h)
            elif a not in new:
                uexits += 1
        entries += sum(1 for a in new if a not in prev)
        exits += sum(1 for a in prev if a not in new)
        to = sum(abs(new.get(a, 0.0) - sold_prev.get(a, 0.0)) for a in sorted(set(new) | set(prev)))
        c = costs.cost(to)
        g = sum(w * (S[a].at(t + 1) / S[a].at(t) - 1.0) for a, w in new.items()) - step_loss
        loss_total += step_loss
        for k, v in (("gross", g), ("cost", c), ("net", g - c), ("turnover", to), ("weights", dict(new))):
            out[k].append(v)
        prev = new
    return PITResult(label=label, start=start, days=len(out["net"]), entries=entries, exits=exits,
                     final_weights=dict(prev), tracker_flat_cost_total=tracker_flat_cost(sum(out["turnover"]) / 2),
                     evidence_class=_evidence_class(permission), forced_exits=forced, universe_exits=uexits,
                     member_counts=members, delist_loss=loss_total, **out)


def run_pit_tsmom(panel: Panel, config: TSMOMConfig, rule: UniverseRule, *, costs: CostModel,
                  permission: DatasetPermission, start: int, delist_haircut: float = 0.0,
                  label: str | None = None) -> PITResult:
    """HR-04 / HR-13 / HR-08 on the PIT universe of ``panel``. Use the same ``start`` for every paired arm."""
    if not isinstance(config, TSMOMConfig) or not isinstance(rule, UniverseRule):
        raise TSMOMError("config must be a TSMOMConfig and rule a UniverseRule")
    return _account_pit(panel, _PITDecider(config, rule), label=label or f"{VERSION}:{config.config_hash()[:12]}",
                        costs=costs, permission=permission, start=start, lag=config.execution_lag,
                        rebalance=config.rebalance, delist_haircut=delist_haircut, rule=rule)


def run_pit_benchmark(panel: Panel, rule: UniverseRule, *, rebalance_at, costs: CostModel,
                      permission: DatasetPermission, start: int, execution_lag: int,
                      delist_haircut: float = 0.0) -> PITResult:
    """EW buy-and-hold of the PIT members, rebalanced to 1/N only on ``rebalance_at`` day indices."""
    if not isinstance(rule, UniverseRule):
        raise TSMOMError("rule must be a UniverseRule")
    if execution_lag not in (0, 1) or isinstance(execution_lag, bool):
        raise TSMOMError("execution_lag must be 0 or 1")
    days = frozenset(rebalance_at)

    def decide(p, t):
        if t not in days:
            return None
        m = membership(p, t, rule)
        return equal_weights(m, len(m)) if m else {}

    return _account_pit(panel, decide, label="pit-ew-bh-rebalanced", costs=costs, permission=permission, start=start,
                        lag=execution_lag, rebalance="daily", delist_haircut=delist_haircut, rule=rule)
