"""HR-04 daily time-series momentum, long/cash, with the HR-13 band and HR-08 inverse-volatility sizing.

Version ``hr04-tsmom-v1``. Pure and standard-library only; research only, never imported by production.

Hypotheses (docs/strategy/HYPOTHESIS_REGISTER.md):

* **HR-04** each asset is held only while its trailing ``lookback``-day close-to-close return is > 0, else cash;
  1/N risk budget per asset of the universe (N = universe size, not the number held).
* **HR-13** hysteresis band ``b``: enter when the trailing return > +b, exit when it is < -b, otherwise keep the
  previous state (``band=None`` is plain HR-04; ``band=0.0`` keeps the state on an exactly-zero return).
* **HR-08** inverse-volatility sizing: per asset scale = min(cap, target / vol), vol = sample standard deviation of
  the last ``vol_window`` daily simple returns, target = median vol over the universe assets with a defined vol on
  that day; weight = scale / N; if the weights sum above 1 they are scaled down to sum to 1 (no leverage).

Timing convention (no look-ahead)
---------------------------------
Index t is the daily close of day t. The decision at t is computed from a read-only view of closes[0..t]
(``research.mechanisms.simulate._Past``, which raises on any index beyond t). ``execution_lag`` fixes when the
decision is traded:

* ``execution_lag=1`` (HR-04 register convention, used by the presets): the decision made at close t is traded at
  close t + 1 and held from close t + 1 to close t + 2. One full day separates information and execution.
* ``execution_lag=0``: the decision made at close t is traded at the same price (close t, which on a 24/7 venue is
  the open of day t + 1) and held to close t + 1. This assumes instant execution at the signal price and is the
  optimistic convention of ``research.mechanisms.simulate.run``; it exists for parity with that accountant.

Hysteresis state starts at "cash" at ``start`` for every asset. An asset without enough history is cash.

Accounting (per step t = start .. len - 2; returns are close t -> close t + 1)
------------------------------------------------------------------------------
Before trading at t the weights held over the previous step drift with the day's returns. Turnover is the sum of
absolute weight changes from those drifted weights (a full entry plus a full exit = 2.0). Costs come from the
s4-mech-v1 ``CostModel`` (0.10 %/side fee floor, half-spread and slippage per side, all on traded notional):

    gross[t] = sum_i w[t, i] * r[t+1, i]        (cash earns 0)
    cost[t]  = costs.cost(turnover[t])
    net[t]   = gross[t] - cost[t]

``rebalance="daily"`` trades every asset back to its target each day (drift and HR-08 re-scaling pay turnover).
``rebalance="on_signal_change"`` trades only assets that enter or exit: exits sell to 0, entries buy their target
weight capped by the cash available; held assets keep their drifted weight. Positions open at the end are reported,
not liquidated (strategy and benchmark alike).

The equal-weight buy-and-hold benchmark buys 1/N of every asset at ``start`` and never trades again, so it pays its
own turnover (1.0 at entry) through the same cost model.

Data permission: every entry point refuses input unless ``permission`` is the synthetic marker or a recorded,
licence-cleared, holdout-excluding ``DatasetPermission`` (the s4-mech-v1 gate). That gate encodes the governance
boundary; it does not replace the owner's data decisions. Results are labelled non-confirmatory.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from statistics import median

from research.mechanisms.costs import CostModel, tracker_flat_cost
from research.mechanisms.signals import realized_vol, trailing_return
from research.mechanisms.simulate import EPS, DatasetPermission, SimulationError, _check_prices, _Past
from research.stats.sharpe_deflation import probabilistic_sharpe_ratio, sample_moments

VERSION = "hr04-tsmom-v1"
WEIGHTINGS = ("equal", "inverse_vol")
REBALANCES = ("daily", "on_signal_change")


class TSMOMError(ValueError):
    """Invalid configuration or input."""


def _int(v, name, lo, hi=None):
    if isinstance(v, bool) or not isinstance(v, int) or v < lo or (hi is not None and v > hi):
        raise TSMOMError(f"{name} must be an int in [{lo}, {hi if hi is not None else 'inf'}]")
    return v


def _nonneg(v, name, positive=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 or (positive and v == 0):
        raise TSMOMError(f"{name} must be finite and {'> 0' if positive else '>= 0'}")
    return float(v)


@dataclass(frozen=True)
class TSMOMConfig:
    """Every field is declared (no defaults): values come from the register or a frozen spec, never tuned here."""
    lookback: int
    band: float | None
    weighting: str
    vol_window: int | None
    vol_cap: float | None          # HR-08 maximum per-asset scale, as a multiple of 1/N
    execution_lag: int             # 0 or 1, see the module docstring
    rebalance: str

    def __post_init__(self):
        _int(self.lookback, "lookback", 1)
        if self.band is not None:
            _nonneg(self.band, "band")
        if self.weighting not in WEIGHTINGS:
            raise TSMOMError(f"weighting must be one of {WEIGHTINGS}")
        if self.weighting == "inverse_vol":
            if self.vol_window is None or self.vol_cap is None:
                raise TSMOMError("inverse_vol needs vol_window and vol_cap")
            _int(self.vol_window, "vol_window", 2)
            _nonneg(self.vol_cap, "vol_cap", positive=True)
        elif self.vol_window is not None or self.vol_cap is not None:
            raise TSMOMError("vol_window / vol_cap are only declared with inverse_vol weighting")
        _int(self.execution_lag, "execution_lag", 0, 1)
        if self.rebalance not in REBALANCES:
            raise TSMOMError(f"rebalance must be one of {REBALANCES}")

    @property
    def warmup(self) -> int:
        """First close index at which every input of the decision is defined."""
        return max(self.lookback, self.vol_window or 0)

    def config_hash(self) -> str:
        """SHA-256 of the canonical configuration plus the module version (for ledger ``config_hash``)."""
        doc = dict(asdict(self), version=VERSION)
        return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# Register presets. HR-04/HR-13 values are the register's (14 days, +/-1 %, next-close execution). The HR-08 window
# (20 days) is the register's; the cap 2.0 x (1/N) is an assumption of this module [ASM] to be frozen before data.
# The rebalance policy ("daily") is not fixed by the register and must also be frozen in the preregistration.
HR04 = TSMOMConfig(lookback=14, band=None, weighting="equal", vol_window=None, vol_cap=None, execution_lag=1,
                   rebalance="daily")
HR13 = replace(HR04, band=0.01)
HR08 = replace(HR04, weighting="inverse_vol", vol_window=20, vol_cap=2.0)


# --- pure decision pieces -------------------------------------------------------------------------------------------

def signal_state(prev_in: bool, trailing: float | None, band: float | None) -> bool:
    """Long/cash state for one asset from its trailing return (None = insufficient history = cash)."""
    if trailing is None:
        return False
    if band is None:
        return trailing > 0
    return trailing >= -band if prev_in else trailing > band


def equal_weights(in_assets, n_universe: int) -> dict:
    _int(n_universe, "n_universe", 1)
    return {a: 1.0 / n_universe for a in sorted(in_assets)}


def inverse_vol_weights(in_assets, vols: Mapping, n_universe: int, cap: float) -> dict:
    """HR-08 weights for the assets that are in. ``vols`` holds the defined vol of every universe asset (the
    median target is taken over all of them, in or out). Assets without a positive vol are left in cash."""
    _int(n_universe, "n_universe", 1)
    cap = _nonneg(cap, "cap", positive=True)
    defined = [v for v in vols.values() if v is not None and v > 0]
    if not defined:
        return {}
    target = median(defined)
    w = {}
    for a in sorted(in_assets):
        v = vols.get(a)
        if v is None or v <= 0:
            continue
        w[a] = min(cap, target / v) / n_universe
    total = sum(w.values())
    if total > 1.0:
        w = {a: x / total for a, x in w.items()}
    return w


class _Decider:
    """Causal decision state for one run: called once per close, in order, with a view of closes[0..t]."""

    def __init__(self, config: TSMOMConfig, assets):
        self.cfg, self.assets, self.state, self.last_t = config, tuple(assets), {a: False for a in assets}, None

    def __call__(self, view, t) -> dict:
        if self.last_t is not None and t != self.last_t + 1:
            raise TSMOMError("decisions must be made on consecutive closes")
        self.last_t = t
        cfg = self.cfg
        for a in self.assets:
            self.state[a] = signal_state(self.state[a], trailing_return(view[a], cfg.lookback, a), cfg.band)
        in_assets = [a for a in self.assets if self.state[a]]
        n = len(self.assets)
        if cfg.weighting == "equal":
            return equal_weights(in_assets, n)
        vols = {a: realized_vol(view[a], cfg.vol_window, a) for a in self.assets}
        return inverse_vol_weights(in_assets, vols, n, cfg.vol_cap)


# --- accountant -----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class TSMOMResult:
    label: str
    start: int
    days: int
    gross: list = field(repr=False)
    cost: list = field(repr=False)
    net: list = field(repr=False)
    turnover: list = field(repr=False)
    weights: list = field(repr=False)          # weights held over each step (after that step's trade)
    entries: int = 0                           # asset weight 0 -> > 0
    exits: int = 0                             # asset weight > 0 -> 0
    final_weights: dict = field(default_factory=dict, repr=False)
    tracker_flat_cost_total: float = 0.0       # 0.30 % flat round-trip label, side by side only
    evidence_class: str = "SYNTHETIC_OR_EXPLORATORY_NOT_CONFIRMATORY"

    @property
    def total_turnover(self) -> float:
        return sum(self.turnover)

    @property
    def total_cost(self) -> float:
        return sum(self.cost)

    @property
    def total_gross(self) -> float:
        return sum(self.gross)

    @property
    def mean_net(self) -> float:
        return sum(self.net) / self.days

    @property
    def mean_gross(self) -> float:
        return sum(self.gross) / self.days

    @property
    def cost_drag(self) -> float | None:
        """Total cost / total gross (simple sums); None when gross is not positive."""
        g = self.total_gross
        return self.total_cost / g if g > 0 else None

    @property
    def max_drawdown(self) -> float:
        return max_drawdown(self.net)


def max_drawdown(returns) -> float:
    """Largest peak-to-trough fall of the compounded equity curve, as a fraction (0 = never below a peak)."""
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in returns:
        eq *= 1.0 + r
        peak = max(peak, eq)
        mdd = max(mdd, 1.0 - eq / peak)
    return mdd


def _account(closes, decide, *, label, costs, permission, start, lag, rebalance) -> TSMOMResult:
    if not isinstance(permission, DatasetPermission) or not permission.allows():
        raise SimulationError("dataset permission missing: synthetic marker or licence-cleared, "
                              "holdout-excluding record required")
    if not isinstance(costs, CostModel):
        raise SimulationError("costs must be a CostModel (s4-mech-v1)")
    n = _check_prices(closes)
    if isinstance(start, bool) or not isinstance(start, int) or not 0 <= start < n - 1:
        raise SimulationError("start must be an int in [0, len - 2]")
    assets = tuple(closes)
    decisions, prev, out = [], {}, {k: [] for k in ("gross", "cost", "net", "turnover", "weights")}
    entries = exits = 0
    for t in range(start, n - 1):
        if t > start and prev:                                   # drift yesterday's weights to today's close
            day = {a: closes[a][t] / closes[a][t - 1] - 1.0 for a in prev}
            port = sum(prev[a] * day[a] for a in prev)
            if 1 + port <= EPS:
                raise SimulationError("portfolio value reached zero")
            prev = {a: prev[a] * (1 + day[a]) / (1 + port) for a in prev}
        decisions.append(decide({a: _Past(closes[a], t) for a in assets}, t))
        target = decisions[-1 - lag] if len(decisions) > lag else {}
        if rebalance == "daily":
            new = {a: w for a, w in target.items() if w > 0}
        else:
            new = {a: w for a, w in prev.items() if target.get(a, 0.0) > 0}
            cash = 1.0 - sum(new.values())
            for a in sorted(target):
                if a not in new and target[a] > 0 and cash > EPS:
                    new[a] = min(target[a], cash)
                    cash -= new[a]
        if any(w < 0 for w in new.values()) or sum(new.values()) > 1 + 1e-9:
            raise SimulationError("weights must be long-only with gross exposure <= 1")
        entries += sum(1 for a in new if a not in prev)
        exits += sum(1 for a in prev if a not in new)
        to = sum(abs(new.get(a, 0.0) - prev.get(a, 0.0)) for a in sorted(set(new) | set(prev)))
        c = costs.cost(to)
        g = sum(w * (closes[a][t + 1] / closes[a][t] - 1.0) for a, w in new.items())
        for k, v in (("gross", g), ("cost", c), ("net", g - c), ("turnover", to), ("weights", dict(new))):
            out[k].append(v)
        prev = new
    return TSMOMResult(label=label, start=start, days=len(out["net"]), entries=entries, exits=exits,
                       final_weights=dict(prev), tracker_flat_cost_total=tracker_flat_cost(sum(out["turnover"]) / 2),
                       **out)


def run_tsmom(closes, config: TSMOMConfig, *, costs: CostModel, permission: DatasetPermission,
              start: int | None = None, label: str | None = None) -> TSMOMResult:
    """HR-04 (optionally HR-13 band, HR-08 sizing) on aligned daily closes ``{asset: [close_0, ...]}``.
    ``start`` defaults to ``config.warmup``; use the same ``start`` for every arm of a paired comparison."""
    if not isinstance(config, TSMOMConfig):
        raise TSMOMError("config must be a TSMOMConfig")
    _check_prices(closes)
    start = config.warmup if start is None else start
    return _account(closes, _Decider(config, tuple(closes)), label=label or f"{VERSION}:{config.config_hash()[:12]}",
                    costs=costs, permission=permission, start=start, lag=config.execution_lag,
                    rebalance=config.rebalance)


def run_buy_and_hold(closes, *, costs: CostModel, permission: DatasetPermission, start: int) -> TSMOMResult:
    """Equal-weight buy-and-hold of the whole universe from ``start``; pays only its own entry turnover."""
    _check_prices(closes)
    n = len(closes)
    weights = {a: 1.0 / n for a in sorted(closes)}
    return _account(closes, lambda view, t: weights, label="ew-buy-and-hold", costs=costs, permission=permission,
                    start=start, lag=0, rebalance="on_signal_change")


def active_returns(strategy: TSMOMResult, benchmark: TSMOMResult) -> list:
    """Paired daily net active return (strategy minus benchmark) on the same steps."""
    if strategy.start != benchmark.start or strategy.days != benchmark.days:
        raise TSMOMError("strategy and benchmark must cover the same steps")
    return [a - b for a, b in zip(strategy.net, benchmark.net)]


def summary(result: TSMOMResult, benchmark: TSMOMResult | None = None) -> dict:
    """Engineering summary of one run (per-observation PSR against 0; not a profitability statement)."""
    m = sample_moments(result.net)
    out = {"label": result.label, "days": result.days, "mean_net": m.mean, "mean_gross": result.mean_gross,
           "psr_net_vs_0": probabilistic_sharpe_ratio(m.sr, m.n, m.skew, m.kurtosis),
           "total_turnover": result.total_turnover, "total_cost": result.total_cost,
           "cost_drag": result.cost_drag, "max_drawdown": result.max_drawdown, "entries": result.entries,
           "exits": result.exits, "evidence_class": result.evidence_class}
    if benchmark is not None:
        act = active_returns(result, benchmark)
        out["mean_active_net"] = sum(act) / len(act)
        out["benchmark_max_drawdown"] = benchmark.max_drawdown
    return out
