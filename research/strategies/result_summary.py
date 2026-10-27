"""Compact, labelled result summary for an HR-04-family run (``hr04-summary-v1``). Research only.

``build_summary`` turns a ``TSMOMResult`` / ``PITResult`` (and optionally its paired benchmark) into a frozen
``ResultSummary``: net expectancy per day and per trade, turnover, cost drag, max drawdown, PSR, DSR with the full
family variant count, Newey-West HAC t, stationary-bootstrap CIs for the mean and the per-observation Sharpe ratio,
and the same endpoints for the paired active return vs the benchmark.

Evidence-class guard
--------------------
* ``evidence_class="SYNTHETIC"`` is produced only for runs on the synthetic marker permission.
* The only other class this module will write is ``"EXPLORATORY_NOT_CONFIRMATORY"``, and only with a non-synthetic,
  licence-cleared, holdout-excluding ``DatasetPermission`` **and** a non-empty ``authorization_ref`` (owner record).
* Any other label (``CONFIRMATORY`` included: D1/D2 HOLD) is refused, as is labelling a synthetic run as real or a
  permitted real run as synthetic.

Per-trade expectancy is approximate for a portfolio: (sum of daily net returns) / (number of position entries). It is
reported beside the per-day expectancy, which is the registered primary unit.

Nothing here is a profitability statement; ``not_a_profitability_claim`` is always True.
"""
from __future__ import annotations

from dataclasses import dataclass

from research.mechanisms.simulate import DatasetPermission
from research.stats.inference import (DEFAULT_MEAN_BLOCK, REGISTER_HAC_LAG, BootstrapCI, hac_t, newey_west_se,
                                      stationary_bootstrap_ci)
from research.stats.sharpe_deflation import deflated_sharpe_ratio, probabilistic_sharpe_ratio, sample_moments
from research.strategies.daily_tsmom import TSMOMResult, active_returns

VERSION = "hr04-summary-v1"
SYNTHETIC = "SYNTHETIC"
EXPLORATORY = "EXPLORATORY_NOT_CONFIRMATORY"
_RESULT_CLASSES = {SYNTHETIC: {SYNTHETIC, "SYNTHETIC_OR_EXPLORATORY_NOT_CONFIRMATORY"},
                   EXPLORATORY: {EXPLORATORY, "SYNTHETIC_OR_EXPLORATORY_NOT_CONFIRMATORY"}}


class SummaryRefused(ValueError):
    """The requested evidence label is not allowed for this permission / authorization."""


def authorize_label(evidence_class, permission, authorization_ref=None) -> str:
    """Return the label if allowed, else raise ``SummaryRefused`` (see module docstring)."""
    if not isinstance(permission, DatasetPermission) or not permission.allows():
        raise SummaryRefused("a valid DatasetPermission (synthetic marker or licence-cleared record) is required")
    if evidence_class == SYNTHETIC:
        if not permission.synthetic:
            raise SummaryRefused("a run on non-synthetic data cannot be labelled SYNTHETIC")
        return SYNTHETIC
    if evidence_class != EXPLORATORY:
        raise SummaryRefused(f"evidence_class must be {SYNTHETIC!r} or {EXPLORATORY!r} (confirmatory is on HOLD)")
    if permission.synthetic:
        raise SummaryRefused("a synthetic run can only be labelled SYNTHETIC")
    if not isinstance(authorization_ref, str) or not authorization_ref.strip():
        raise SummaryRefused("a non-synthetic label needs an owner authorization_ref")
    return EXPLORATORY


@dataclass(frozen=True)
class SeriesStats:
    days: int
    mean_per_day: float
    sharpe_per_day: float
    psr_vs_0: float
    hac_lag: int
    hac_se: float
    hac_t: float
    bootstrap_mean: BootstrapCI
    bootstrap_sharpe: BootstrapCI


def series_stats(xs, *, hac_lag, mean_block, n_resamples, level, seed) -> SeriesStats:
    m = sample_moments(xs)
    return SeriesStats(m.n, m.mean, m.sr, probabilistic_sharpe_ratio(m.sr, m.n, m.skew, m.kurtosis), hac_lag,
                       newey_west_se(xs, hac_lag), hac_t(xs, hac_lag),
                       stationary_bootstrap_ci(xs, "mean", mean_block=mean_block, n_resamples=n_resamples,
                                               level=level, seed=seed),
                       stationary_bootstrap_ci(xs, "sharpe", mean_block=mean_block, n_resamples=n_resamples,
                                               level=level, seed=seed + 1))


@dataclass(frozen=True)
class ResultSummary:
    version: str
    evidence_class: str
    authorization_ref: str | None
    label: str
    days: int
    trades: int
    net_per_day: float
    gross_per_day: float
    net_per_trade: float | None
    total_turnover: float
    turnover_per_day: float
    total_cost: float
    cost_drag: float | None
    max_drawdown: float
    net: SeriesStats
    dsr: float
    dsr_n_trials: int
    dsr_trial_sr_variance: float
    benchmark_label: str | None = None
    benchmark_net_per_day: float | None = None
    benchmark_max_drawdown: float | None = None
    benchmark_total_turnover: float | None = None
    benchmark_total_cost: float | None = None
    active: SeriesStats | None = None
    not_a_profitability_claim: bool = True


def build_summary(result: TSMOMResult, *, evidence_class: str, permission: DatasetPermission,
                  n_trials: int, trial_sr_variance: float, seed: int, benchmark: TSMOMResult | None = None,
                  authorization_ref: str | None = None, ledger=None, family: str | None = None,
                  hac_lag: int = REGISTER_HAC_LAG, mean_block: float = DEFAULT_MEAN_BLOCK,
                  n_resamples: int = 1000, level: float = 0.95) -> ResultSummary:
    """Summary of one run. ``n_trials`` must count every variant of the family, abandoned ones included; when a
    ``ledger`` and ``family`` are given it must equal ``ledger.trials(family)``."""
    label = authorize_label(evidence_class, permission, authorization_ref)
    if not isinstance(result, TSMOMResult):
        raise SummaryRefused("result must be a TSMOMResult / PITResult")
    if result.evidence_class not in _RESULT_CLASSES[label]:
        raise SummaryRefused(f"result evidence_class {result.evidence_class!r} does not match {label!r}")
    if benchmark is not None and benchmark.evidence_class not in _RESULT_CLASSES[label]:
        raise SummaryRefused("benchmark evidence_class does not match")
    if ledger is not None:
        if family is None or ledger.trials(family) != n_trials:
            raise SummaryRefused("n_trials must equal the ledger's full variant count for the family")
    if isinstance(n_trials, bool) or not isinstance(n_trials, int) or n_trials < 1:
        raise SummaryRefused("n_trials must be an int >= 1")
    kw = dict(hac_lag=hac_lag, mean_block=mean_block, n_resamples=n_resamples, level=level)
    net = series_stats(result.net, seed=seed, **kw)
    m = sample_moments(result.net)
    dsr = deflated_sharpe_ratio(m.sr, m.n, n_trials, trial_sr_variance, m.skew, m.kurtosis)
    trades = result.entries
    extra = {}
    if benchmark is not None:
        act = active_returns(result, benchmark)
        extra = dict(benchmark_label=benchmark.label, benchmark_net_per_day=benchmark.mean_net,
                     benchmark_max_drawdown=benchmark.max_drawdown, benchmark_total_turnover=benchmark.total_turnover,
                     benchmark_total_cost=benchmark.total_cost, active=series_stats(act, seed=seed + 2, **kw))
    return ResultSummary(
        version=VERSION, evidence_class=label, authorization_ref=authorization_ref if label != SYNTHETIC else None,
        label=result.label, days=result.days, trades=trades, net_per_day=result.mean_net,
        gross_per_day=result.mean_gross, net_per_trade=(sum(result.net) / trades) if trades else None,
        total_turnover=result.total_turnover, turnover_per_day=result.total_turnover / result.days,
        total_cost=result.total_cost, cost_drag=result.cost_drag, max_drawdown=result.max_drawdown, net=net,
        dsr=dsr.dsr, dsr_n_trials=n_trials, dsr_trial_sr_variance=float(trial_sr_variance), **extra)
